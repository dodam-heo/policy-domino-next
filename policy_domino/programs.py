"""Official public-program evidence and policy-to-operations joins.

A named actor, a topic match, and a verified *program dependency* are different
claims. This module never guesses an institution's obligation or completion.
No agency, program, law title, or expected answer is hard-coded.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlparse

from .analysis import extract_references
from .core import clean

SOURCE_NAME = "alioplus"
PROGRAM_PATH = "/business/bsnDetail.do"
SCHEMA_FIELDS = ("id", "agency", "name", "url", "description", "body_sha256")
_VALUE = re.compile(r"(?<![\d,.])\d[\d,]*(?:\.\d+)?\s*(?:억원|만원|원|%|개월|일)")
_AMOUNT = re.compile(r"(?:원|%)\s*$")


def canonical_url(url: object) -> str:
    """Only allow known official portal *business detail* pages as evidence."""
    if not isinstance(url, str):
        return ""
    try:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        seq = query.get("bsnSeq", [""])[0]
        if (parsed.scheme != "https" or
            parsed.hostname not in ("www.alioplus.go.kr", "alioplus.go.kr") or
            parsed.path != PROGRAM_PATH or
            not seq.isdecimal() or len(seq) > 12):
            return ""
        return ("https://www.alioplus.go.kr" + PROGRAM_PATH +
                "?bsnSeq=" + seq + "&bsnTyp=DET")
    except (ValueError, AttributeError, TypeError):
        return ""


def normalize_program(raw: dict) -> dict:
    """Reject untraceable, incomplete or non-portal records (fail closed)."""
    if not isinstance(raw, dict):
        raise ValueError("Official program record must be an object")
    url = canonical_url(raw.get("url"))
    agency = clean(raw.get("agency"))
    name = clean(raw.get("name"))
    description = clean(raw.get("description"))
    if not url or len(agency) < 2 or len(name) < 3 or len(description) < 20:
        raise ValueError("Program needs a verified portal URL, agency, name and body")
    if len(agency) > 100 or len(name) > 240 or len(description) > 80_000:
        raise ValueError("Unreasonable public program record size")
    body_hash = hashlib.sha256(description.encode("utf8")).hexdigest()
    return {
        "id": hashlib.sha256(url.encode("utf8")).hexdigest()[:24],
        "source": SOURCE_NAME,
        "agency": agency,
        "name": name,
        "url": url,
        "description": description,
        "body_sha256": body_hash,
    }


def ingest_programs(state: dict, records: list[dict]) -> dict:
    """Dedupe by official URL, retaining last valid content and audit failures."""
    store = state.setdefault("official_programs", {})
    accepted = 0
    rejected = 0
    errors = []
    for raw in records:
        try:
            entry = normalize_program(raw)
        except (ValueError, TypeError) as exc:
            rejected += 1
            errors.append(str(exc))
            continue
        store[entry["id"]] = entry
        accepted += 1
    return {"accepted": accepted, "rejected": rejected,
            "reasons": sorted(set(errors))[:5]}


def _exact_references(text: str) -> set[tuple[str, str]]:
    # Preserve legal article precision. Law-title-only mentions are insufficient.
    return {(ref["title"], ref["article"])
            for ref in extract_references(text) if ref["article"]}


def _reference_quote(text: str, title: str, article: str) -> str:
    for ref in extract_references(text):
        if (ref["title"], ref["article"]) == (title, article):
            return ref["quote"]
    return ""


def _numerical_review(change: dict, program_text: str) -> dict:
    """Report only complete old/new numeric values; never assert an update."""
    before = set(_VALUE.findall(change.get("before", "")))
    after = set(_VALUE.findall(change.get("after", "")))
    old_only = sorted(before - after)
    new_only = sorted(after - before)
    # Multiple old/new figures cannot be paired safely without a full table.
    if len(old_only) != 1 or len(new_only) != 1:
        return {}
    old, new = old_only[0], new_only[0]
    if not (_AMOUNT.search(old) and _AMOUNT.search(new)):
        return {}
    if not re.search(r"(?<!\d)" + re.escape(old) + r"(?!\d)", program_text):
        return {}
    return {"old_value": old, "new_value": new,
            "value_note": "사업 안내에 종전 수치가 기재됨. 적용 여부 및 개정 필요성 검토"}


def discover_program_links(state: dict, relationships: list[dict],
                           *, limit_events: int | None = None) -> list[dict]:
    """Prove direct or two-hop explicit citations in official program bodies.

    Program title/keyword overlap does not create an edge. Exact references
    in the published program document are required; a legal citation alone
    cannot prove a changed operational criterion.
    """
    documents = state.get("documents", {})
    findings = state.get("findings", {})
    indexed = state.get("official_programs", {})
    cases = []
    for event_id, finding in findings.items():
        if finding.get("status") not in ("compared", "partial_compared"):
            continue
        doc = documents.get(event_id)
        if not doc or doc.get("reference_only"):
            continue
        for change in finding.get("changes", []):
            if change.get("article") and change.get("before") != change.get("after"):
                cases.append((doc, change))
    cases.sort(key=lambda row: (row[0].get("published_at", ""),
                                row[0].get("id", "")), reverse=True)
    if limit_events is not None:
        ids = list(dict.fromkeys(doc["id"] for doc, _ in cases))[:max(0, limit_events)]
        cases = [(doc, change) for doc, change in cases if doc["id"] in ids]

    # A legal intermediary is usable only when an exact changed-article
    # citation is already proven and its own referenced clause is known.
    graph = {}
    for edge in relationships:
        if edge.get("relationship") != "verified_exact_article_citation":
            continue
        key = (edge.get("source_event_id"), edge.get("changed_article"))
        if all(edge.get(x) for x in ("referencing_title", "referencing_article",
                                     "referencing_source_url")):
            graph.setdefault(key, []).append(edge)

    found = {}
    for record in indexed.values():
        try:
            trusted = normalize_program(record)
        except (ValueError, TypeError):
            continue
        body = trusted["description"]
        references = _exact_references(body)
        if not references:
            continue
        for doc, change in cases:
            article = change["article"]
            direct_key = (doc["title"], article)
            if direct_key in references:
                via = None
                quote = _reference_quote(body, *direct_key)
            else:
                via = next((edge for edge in graph.get((doc["id"], article), [])
                            if (edge["referencing_title"], edge["referencing_article"])
                            in references), None)
                if not via:
                    continue
                quote = _reference_quote(body, via["referencing_title"],
                                         via["referencing_article"])
            if not quote:
                continue
            note = _numerical_review(change, body)
            # Distinguish verified citation chain from unproven required action.
            result = {
                "source_event_id": doc["id"],
                "changed_article": article,
                "agency": trusted["agency"],
                "program": trusted["name"],
                "program_id": trusted["id"],
                "program_url": trusted["url"],
                "program_body_sha256": trusted["body_sha256"],
                "referenced_title": via["referencing_title"] if via else doc["title"],
                "referenced_article": via["referencing_article"] if via else article,
                "citation_quote": quote,
                "path": "via_regulation" if via else "direct",
                "intermediate_url": via["referencing_source_url"] if via else None,
                "verification": "verified_program_citation",
                "operational_program_verified": True,
                "required_action_verified": False,
                "review": (trusted["name"] + "의 " + article +
                           " 관련 운영기준 적용 여부 확인"),
                **note,
            }
            key = (doc["id"], article, trusted["id"])
            # Prefer a direct program citation when both paths exist.
            if key not in found or result["path"] == "direct":
                found[key] = result
    return sorted(found.values(), key=lambda x: (
        x["source_event_id"], x["agency"], x["program"], x["changed_article"]))


def program_audit(state: dict, links: list[dict]) -> dict:
    programs = state.get("official_programs", {})
    return {"official_program_records": len(programs),
            "verified_program_citations": len(links),
            "distinct_agencies_with_citations": len({x["agency"] for x in links}),
            "action_obligations_verified": 0,
            "coverage": "partial_not_nationwide"}
