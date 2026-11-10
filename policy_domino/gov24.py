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


def normalize_record(raw: dict) -> dict:
    """Never create an agency/service name not supplied by the public API."""
    if not isinstance(raw, dict):
        raise Gov24SourceError("official record must be an object")
    service_id = _safe_text(raw.get("서비스ID"), 100)
    name = _safe_text(raw.get("서비스명"), 260)
    agency = _safe_text(raw.get("소관기관명"), 190)
    agency_type = _safe_text(raw.get("소관기관유형"), 80)
    if not service_id or not name or not agency:
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
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                # Don't leak the serviceKey embedded in a request URL.
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
        for _ in range(max(0, min(6, pages_per_feed))):
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
                    fresh = normalize_record(item)
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
    audit["cursors"] = dict(cursors)
    audit["status"] = "partial" if audit["errors"] else "collected_incrementally"
    state["gov24_audit"] = audit
    return audit


def _plain(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _explicit_law_basis(service: dict, title: str, article: str) -> tuple[str, str] | None:
    """Real legal citation is a *discovery lead*, not a proven obligation."""
    basis = service.get("regulatory_basis", "")
    if not title or len(title) < 5 or _plain(title) not in _plain(basis):
        return None
    for ref in extract_references(basis):
        if _plain(ref.get("title", "")) == _plain(title) and (
                _plain(ref.get("article", "")) == _plain(article)):
            return "official_clause_citation", ref.get("quote", "")[:280]
    # The full named rule is present but its particular changed article is not
    # cited. Do not upgrade this to confirmed article-level impact.
    at = _plain(basis).find(_plain(title))
    return "official_rule_title", basis[:280]


def discover_public_service_leads(state: dict, events: list[dict],
                                  *, max_per_event: int = 15) -> dict:
    """Find possible institution/service review locations from legal evidence.

    A result is a *lead requiring validation*, not an institutional review or
    a claim that a service value has actually changed.
    """
    sources = state.get("public_services", {})
    linked = {}
    proofs = {}
    for event in events:
        selected = {}
        for change in event.get("changes", []):
            title, article = change["document_title"], change["article"]
            for service in sources.values():
                basis = _explicit_law_basis(service, title, article)
                if not basis:
                    continue
                tier, quote = basis
                key = (service["service_id"],change["document_id"],article)
                source_text = service.get("fields", {})
                matched_old = [
                    x for x in re.findall(
                        r"\d[\d,.]*\s*(?:억원|만원|원|%|개월|일)",
                        change.get("before", ""))
                    if any(x in source_text.get(field, "") for field
                           in ("선정기준", "지원내용", "지원대상"))
                ]
                lead = {
                    "service_id": service["service_id"],
                    "service_name": service["service_name"],
                    "agency": service["agency"],
                    "agency_type": service.get("agency_type", ""),
                    "document_id": change["document_id"],
                    "article": article, "law_title": title,
                    "match_tier": tier, "basis_quote": quote,
                    "old_value_seen_in_service": matched_old[:3],
                    "source_url": service["source_url"],
                    "service_url": service.get("service_url", ""),
                    "verification": "candidate_not_confirmed",
                    "review_question": (
                        "해당 공공서비스의 운영·선정 기준에 개정 조문이 "
                        "적용되는지 공식 사업자료와 대조 필요"),
                }
                selected[key] = lead
                proofs[service["service_id"]] = service
        ordered = sorted(selected.values(),key=lambda x:(
            x["match_tier"] != "official_clause_citation",
            not x["old_value_seen_in_service"], x["agency"],
            x["service_name"], x["article"]))
        event["public_service_leads"] = ordered[:max_per_event]
        event["public_service_lead_count"] = len(ordered)
        linked[event["id"]] = len(ordered)
    used = {x["service_id"] for ev in events
            for x in ev.get("public_service_leads", [])}
    return {"proofs": {x: proofs[x] for x in sorted(used)},
            "leads_by_event": linked,
            "total_candidates": sum(linked.values())}
