"""Nationwide public service directory connector (Gov24, official MOIS data).

Source: https://www.data.go.kr/data/15113968/openapi.do
Official REST schema: /gov24/v3/{serviceList,serviceDetail,supportConditions}

The registry is not a ledger of policy-change implementation. It only
identifies real public agencies, services, eligibility, operational
criteria and explicit regulatory references. A connection candidate is NOT
a confirmed institutional action, and it is never presented as one.
"""
from __future__ import annotations

import hashlib
import json
import re
import difflib
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

from .analysis import extract_references
from .core import clean, utc_now

ENDPOINT = "https://api.odcloud.kr/api/gov24/v3/"
CATALOG = "https://www.data.go.kr/data/15113968/openapi.do"
SCHEMA = ("serviceList", "serviceDetail")
FIELDS = (
    "지원대상", "선정기준", "지원내용", "신청방법", "신청기한", "서비스목적",
    "서비스목적요약", "구비서류", "행정규칙", "자치법규", "법령",
)
SOURCE_NAMES = {"central", "regional", "education", "public", "other"}


class Gov24SourceError(RuntimeError):
    pass


def _safe_text(v: object, limit: int = 8000) -> str:
    if not isinstance(v, str):
        return ""
    return re.sub(r"\s+", " ", v).strip()[:limit]


def official_service_url(value: object) -> str:
    if not isinstance(value, str):
        return ""
    try:
        url = urllib.parse.urlparse(value)
        host = (url.hostname or "").lower()
        if (url.scheme == "https" and
                (host == "gov.kr" or host.endswith(".gov.kr"))):
            return value
    except ValueError:
        return ""
    return ""


def normalize_record(raw: dict, *, allow_missing_agency: bool = False) -> dict:
    """Never create an agency/service name not supplied by the public API."""
    if not isinstance(raw, dict):
        raise Gov24SourceError("official record must be an object")
    service_id = _safe_text(raw.get("서비스ID"), 100)
    name = _safe_text(raw.get("서비스명"), 260)
    agency = _safe_text(raw.get("소관기관명"), 190)
    agency_type = _safe_text(raw.get("소관기관유형"), 80)
    if not service_id or not name or (not agency and not allow_missing_agency):
        raise Gov24SourceError("service ID, name and public agency are required")
    if re.search(r"민간업체|민간기업|사기업", agency_type):
        raise Gov24SourceError("private provider cannot be an impacted public institution")
    values = {field: _safe_text(raw.get(field)) for field in FIELDS}
    basis = " ".join(v for k, v in values.items()
                     if k in ("행정규칙", "자치법규", "법령") and v)
    normalized = {
        "source": "gov24",
        "service_id": service_id,
        "agency": agency,
        "agency_code": _safe_text(raw.get("소관기관코드"), 100),
        "agency_type": agency_type,
        "service_name": name,
        "source_url": CATALOG,
        "service_url": official_service_url(
            raw.get("상세조회URL") or raw.get("온라인신청사이트URL")),
        "updated_at": _safe_text(raw.get("수정일시"), 45),
        "regulatory_basis": basis,
        "fields": {k: v for k, v in values.items() if v},
    }
    normalized["content_sha256"] = hashlib.sha256(json.dumps(
        normalized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return normalized


def merge_record(existing: dict | None, incoming: dict) -> dict:
    """Keep detailed legal, selection and service fields across two feeds."""
    if not existing:
        return incoming
    if existing.get("service_id") != incoming.get("service_id"):
        raise Gov24SourceError("cannot merge different service IDs")
    values = dict(existing.get("fields", {}))
    values.update({k: v for k, v in incoming.get("fields", {}).items() if v})
    merged = dict(existing)
    for key in ("agency", "agency_code", "agency_type", "service_name",
                "updated_at", "service_url"):
        if incoming.get(key):
            merged[key] = incoming[key]
    merged["fields"] = values
    merged["regulatory_basis"] = " ".join(values.get(k, "") for k in
                                   ("법령", "행정규칙", "자치법규") if values.get(k))
    merged["content_sha256"] = hashlib.sha256(json.dumps(
        {k: v for k, v in merged.items() if k != "content_sha256"},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return merged


class Gov24Client:
    def __init__(self, api_key: str, transport=None):
        self.api_key = str(api_key or "").strip()
        self.transport = transport

    def fetch_page(self, endpoint: str, page: int, page_size: int) -> dict:
        if endpoint not in SCHEMA:
            raise Gov24SourceError("unsupported official source operation")
        if not self.api_key:
            raise Gov24SourceError("Gov24 authorization not configured")
        url = ENDPOINT + endpoint + "?" + urllib.parse.urlencode({
            "page": page, "perPage": page_size, "serviceKey": self.api_key,
            "returnType": "JSON",
        })
        if self.transport is not None:
            result = self.transport(endpoint, page, page_size)
        else:
            request = urllib.request.Request(
                url, headers={"User-Agent": "PolicyDominoNext/1.0",
                              "Accept": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    if urllib.parse.urlparse(response.geturl()).hostname != "api.odcloud.kr":
                        raise Gov24SourceError("unapproved official API redirect")
                    body = response.read(2_000_001)
                    if len(body) > 2_000_000:
                        raise Gov24SourceError("Gov24 official response too large")
                    result = json.loads(body.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # HTTP status is safe; never include the credential-bearing URL.
                raise Gov24SourceError(
                    "official source rejected request (HTTP " + str(exc.code) + ")"
                ) from None
            except (urllib.error.URLError, TimeoutError, ValueError):
                raise Gov24SourceError("official source request or JSON failed") from None
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise Gov24SourceError("official response has no data list")
        if not isinstance(result.get("totalCount"), int) or result["totalCount"] < 0:
            raise Gov24SourceError("official response has no valid total count")
        if result.get("page", page) != page:
            raise Gov24SourceError("official page number differs from request")
        if len(result["data"]) > page_size:
            raise Gov24SourceError("official page exceeds requested size")
        return result


def collect_gov24(state: dict, key: str, *, pages_per_feed: int = 2,
                  page_size: int = 100, transport=None) -> dict:
    """Durable cursors per official list/detail feed, never fabricated data.

    Missing API authorization does NOT cause a broken website or trigger a
    fake set of government programs.
    """
    audit = {"source": "gov24_public_services", "status": "not_configured",
             "checked_at": utc_now(), "attempted_pages": 0,
             "accepted": 0, "rejected": 0, "total_known": {},
             "incomplete": True, "errors": []}
    if not key:
        audit["note"] = "GOV24_SERVICE_KEY is absent; no nationwide data ingested"
        state["gov24_audit"] = audit
        return audit
    client = Gov24Client(key, transport)
    store = state.setdefault("public_services", {})
    cursors = state.setdefault("gov24_cursors", {})
    audit["status"] = "partial"
    for source in SCHEMA:
        page = max(1, int(cursors.get(source, 1)))
        for _ in range(max(0, min(12, pages_per_feed))):
            try:
                response = client.fetch_page(source, page, page_size)
            except Gov24SourceError as exc:
                audit["errors"].append(source + " page " + str(page) +
                                       ": " + str(exc))
                break
            audit["attempted_pages"] += 1
            audit["total_known"][source] = response["totalCount"]
            for item in response["data"]:
                try:
                    fresh = normalize_record(
                        item, allow_missing_agency=(source == "serviceList"))
                    old = store.get(fresh["service_id"])
                    store[fresh["service_id"]] = merge_record(old, fresh)
                    audit["accepted"] += 1
                except Gov24SourceError:
                    audit["rejected"] += 1
            if page * page_size >= response["totalCount"]:
                page = 1  # Revisit earlier pages on the next refresh cycle.
                break
            page += 1
        cursors[source] = page
    audit["records_stored"] = len(store)
    audit["records_with_issuer"] = sum(bool(x.get("agency")) for x in store.values())
    audit["records_with_legal_basis"] = sum(bool(x.get("regulatory_basis")) for x in store.values())
    audit["records_with_operational_criteria"] = sum(bool(
        any(x.get("fields", {}).get(field) for field in CRITERION_FIELDS))
        for x in store.values())
    audit["cursors"] = dict(cursors)
    audit["status"] = "partial" if audit["errors"] else "collected_incrementally"
    state["gov24_audit"] = audit
    return audit


def _plain(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _explicit_law_basis(service: dict, title: str, article: str) -> tuple[str, str] | None:
    """Exact official legal-title evidence; article citation has higher weight."""
    basis = service.get("regulatory_basis", "")
    title_plain = _plain(title)
    if not title_plain or len(title_plain) < 5 or title_plain not in _plain(basis):
        return None
    for ref in extract_references(basis):
        if _plain(ref.get("title", "")) == title_plain and (
                _plain(ref.get("article", "")) == _plain(article)):
            return "official_clause_citation", ref.get("quote", "")[:280]
    # Title-only reference is intentionally NOT a confirmed article link.
    # A shorter name embedded inside a differently named 「legal title」 is
    # insufficient proof of the requested rule.
    quoted = re.findall(r"「([^」]{2,150})」", basis)
    if quoted and not any(_plain(x) == title_plain for x in quoted):
        # A source may contain several unquoted texts too, but ambiguity
        # must not be converted into an institutional impact automatically.
        return None
    return "official_rule_title", basis[:280]


CRITERION_FIELDS = ("선정기준", "지원대상", "지원내용", "신청방법", "신청기한")


def _changed_values(change: dict) -> tuple[str, str]:
    """Numeric before/after ONLY if the literal statute values differ uniquely."""
    unit = r"\d[\d,.]*\s*(?:억\s*원|만원|원|%|명|개월|일)"
    before = set(re.findall(unit, change.get("before", "")))
    after = set(re.findall(unit, change.get("after", "")))
    old, new = sorted(before - after), sorted(after - before)
    return (old[0], new[0]) if len(old) == len(new) == 1 else ("", "")


def changed_numeric_pairs(change: dict) -> list[tuple[str, str]]:
    """Locate changed numerals by matching intact neighboring legal context.

    Pairs from a table are admitted only when old/new sequences are equally
    long and both sides retain comparable surrounding labels. Arbitrary
    amount-order pairing is not permitted.
    """
    pattern=re.compile(r"(?<![\d,.])\d[\d,.]*\s*(?:억\s*원|만원|원|%|명|개월|일)")
    before=change.get("before","")
    after=change.get("after","")
    old=list(pattern.finditer(before))
    new=list(pattern.finditer(after))
    if not old or len(old)!=len(new):
        return []
    values=[]
    for a,b in zip(old,new):
        x,y=a.group().strip(),b.group().strip()
        if x==y:
            continue
        unit=r"(?:억\s*원|만원|원|%|명|개월|일)$"
        old_unit=re.search(unit,x)
        new_unit=re.search(unit,y)
        if not old_unit or not new_unit or old_unit.group()!=new_unit.group():
            continue
        if len(old)>1:
            left_old=before[max(0,a.start()-18):a.start()]
            left_new=after[max(0,b.start()-18):b.start()]
            if (len(left_old.strip())<3 or len(left_new.strip())<3 or
                difflib.SequenceMatcher(
                    None,left_old,left_new,autojunk=False).ratio()<0.88):
                continue
        context_before=(before[max(0,a.start()-36):a.start()]+"|"+
                        before[a.end():a.end()+30])
        context_after=(after[max(0,b.start()-36):b.start()]+"|"+
                       after[b.end():b.end()+30])
        # Similar neighboring row labels are evidence; raw ordinal is not.
        if difflib.SequenceMatcher(
                None,context_before,context_after,autojunk=False).ratio()<0.72:
            continue
        values.append((x,y))
    return list(dict.fromkeys(values))


def criteria_to_review(service: dict, change: dict, tier: str) -> list[dict]:
    """Concrete review targets from actual government-service field snapshots.

    A matched former legal number is evidence for a TARGETED comparison,
    not proof that an agency's internal rules have already changed.
    """
    fields = service.get("fields", {})
    single=_changed_values(change)
    pairs=changed_numeric_pairs(change)
    if single!=("","") and single not in pairs:
        pairs.insert(0,single)
    targets = []
    for field in CRITERION_FIELDS:
        source = fields.get(field, "")
        if not source:
            continue
        applicable=[(a,b) for a,b in pairs if a and a in source]
        old,new=applicable[0] if len(applicable)==1 else ("","")
        old_found=bool(old)
        question=(
            field + "에 기재된 " + old +
            " 기준을 변경 조문의 " + new + " 기준과 대조하고 적용 여부를 확인"
            if old_found and new else
            field + "의 실제 적용기준과 " + change["article"] +
            " 개정내용의 관계를 확인")
        targets.append({
            "field": field,
            "source_excerpt": source[:300],
            "old_value": old if old_found else "",
            "new_legal_value": new if old_found else "",
            "review_question": question,
            "verification": "source_field_and_legal_change_only",
        })
    targets.sort(key=lambda x: (
        not bool(x["old_value"]),
        CRITERION_FIELDS.index(x["field"]),
    ))
    if not targets:
        return [{
            "field": "근거법령",
            "source_excerpt": service.get("regulatory_basis", "")[:300],
            "old_value": "", "new_legal_value": "",
            "review_question": (
                "공식 서비스에 적용하는 근거 조문과 " +
                change["article"] + " 개정 내용의 관계를 확인"),
            "verification": "source_field_and_legal_change_only",
        }]
    # Quoted source excerpts and questions remain discoverable in the
    # original Gov24 record. Never turn these into a completed action.
    return targets[:3]


def discover_public_service_leads(state: dict, events: list[dict],
                                  *, max_per_event: int = 15) -> dict:
    """Join actual public-service agencies, program fields and changed laws.

    Strict legal title/article citation is distinguished from title-only
    leads. Only source-evidenced criterion differences get specific numeric
    review tasks; no inferred or hardcoded agency/program names.
    """
    sources = state.get("public_services", {})
    matched = {}
    all_titles = {
        change.get("document_title", "") for event in events
        for change in event.get("changes", [])
        if change.get("document_title")
    }
    candidates_by_title = defaultdict(list)
    # One scan of official public-service records, not O(changes × services).
    for service in sources.values():
        if not service.get("agency") or not service.get("service_name"):
            continue
        basis_plain = _plain(service.get("regulatory_basis", ""))
        if not basis_plain:
            continue
        for title in all_titles:
            if len(title) >= 5 and _plain(title) in basis_plain:
                candidates_by_title[title].append(service)

    linked = {}
    proofs = {}
    for event in events:
        selected = {}
        for change in event.get("changes", []):
            title, article = change["document_title"], change["article"]
            for service in candidates_by_title.get(title, []):
                basis = _explicit_law_basis(service, title, article)
                if not basis:
                    continue
                tier, quote = basis
                key = (service["service_id"],change["document_id"],article)
                targets = criteria_to_review(service, change, tier)
                old_values = list(dict.fromkeys(
                    item["old_value"] for item in targets if item["old_value"]))
                selected[key] = {
                    "service_id": service["service_id"],
                    "service_name": service["service_name"],
                    "agency": service["agency"],
                    "agency_type": service.get("agency_type", ""),
                    "document_id": change["document_id"],
                    "article": article, "law_title": title,
                    "match_tier": tier, "basis_quote": quote,
                    "review_targets": targets,
                    "old_value_seen_in_service": old_values[:3],
                    "source_url": service["source_url"],
                    "service_url": service.get("service_url", ""),
                    "verification": "candidate_not_confirmed",
                    "review_question": (
                        "실제 공공서비스의 업무·자격·신청 기준에 "
                        "변경 조문을 적용해야 하는지 검토"),
                }
                proofs[service["service_id"]] = service
        ordered = sorted(selected.values(), key=lambda x: (
            x["match_tier"] != "official_clause_citation",
            not x["old_value_seen_in_service"],
            x["agency"],x["service_name"],x["article"]))
        event["public_service_leads"] = ordered[:max_per_event]
        event["public_service_lead_count"] = len(ordered)
        linked[event["id"]] = len(ordered)
    used = {x["service_id"] for ev in events
            for x in ev.get("public_service_leads", [])}
    return {"proofs": {x: proofs[x] for x in sorted(used)},
            "leads_by_event": linked,
            "total_candidates": sum(linked.values())}
