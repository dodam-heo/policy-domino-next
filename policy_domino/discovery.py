"""Incremental discovery of exact public-law citations in official rule texts.

Each changed act gets a resumable cursor PER source. An incomplete first
search page is not falsely marked complete or permanently skipped. The public
agency issuing a citing regulation is audited separately from confirmed
program-operation duties.
"""
from __future__ import annotations

from .analysis import extract_references
from .api import field, nodes, parse_record
from .core import SOURCES, utc_now
from .parser import parse_document


def discover_dependents(api, state: dict, limit_events: int = 3,
                        page_size: int = 40,
                        max_bodies_per_source: int = 8) -> dict:
    ledger = state.setdefault("dependency_discovery", {})
    documents = state.setdefault("documents", {})
    findings = state.setdefault("findings", {})
    versions = state.setdefault("versions", {})

    pending = [
        (eid, row) for eid, row in findings.items()
        if row.get("changes") and eid in documents and
        not documents[eid].get("reference_only") and
        not ledger.get(eid, {}).get("fully_checked")
    ]
    # Round-robin unfinished events instead of repeatedly allocating the
    # entire search budget to the three newest incomplete citations.
    pending.sort(key=lambda pair: (
        ledger.get(pair[0], {}).get("last_checked_at", ""),
        -int(documents[pair[0]].get("published_at", "")[:4] or 0),
        pair[0],
    ))
    metrics = {
        "events": 0, "pages": 0, "possible_documents": 0,
        "official_bodies_checked": 0, "exact_article_references": 0,
        "incomplete_queries": 0,
        "pending_events": len(pending),
        "previously_incomplete_resumed": 0,
    }
    for event_id, finding in pending[:max(0, limit_events)]:
        changed = documents[event_id]
        wanted = {item["article"] for item in finding["changes"]
                  if item.get("article")}
        previous = ledger.get(event_id, {})
        prior_sources = {
            row["source"]: row for row in previous.get("queries", [])
            if isinstance(row, dict) and row.get("source") in SOURCES
        }
        reports = []
        metrics["events"] += 1
        if previous:
            metrics["previously_incomplete_resumed"] += 1
        for source in SOURCES:
            prior = prior_sources.get(source, {})
            if prior.get("complete"):
                reports.append(prior)
                continue
            page = max(1, int(prior.get("next_page", 1)))
            offset = max(0, int(prior.get("next_offset", 0)))
            report = {
                "source": source, "reported": prior.get("reported", -1),
                "searched": 0, "verified": 0, "complete": False,
                "error": "", "next_page": page, "next_offset": offset,
                "checked_total": int(prior.get("checked_total", 0)),
            }
            try:
                params = {
                    "query": changed["title"], "search": 2,
                    "display": page_size, "page": page,
                }
                if source != "law":
                    params["nw"] = "1"
                root = api.request("lawSearch.do", source, **params)
                total = field(root, "totalCnt")
                if not total.isdigit():
                    raise ValueError("Missing official full-text search count")
                report["reported"] = int(total)
                raw_candidates = [parse_record(x, source) for x in nodes(root, source)]
                rows_on_page = len(raw_candidates)
                candidates = [x for x in raw_candidates if x and x["id"] != event_id]
                # The cursor counts actual page rows, never made-up indexes.
                if offset > len(candidates):
                    # Search result was repaginated since the last run:
                    # re-examine this page rather than silently skip evidence.
                    offset = 0
                page_candidates = candidates[offset:offset + max_bodies_per_source]
                report["searched"] = len(page_candidates)
                metrics["possible_documents"] += len(page_candidates)
                for doc in page_candidates:
                    package = versions.get(doc["id"])
                    if not package:
                        package = parse_document(api.detail(doc))
                    report["checked_total"] += 1
                    metrics["official_bodies_checked"] += 1
                    proof = []
                    for article, clause in package.get("clauses", {}).items():
                        if not clause.get("complete"):
                            continue
                        for ref in extract_references(clause["text"]):
                            if (ref["title"] == changed["title"]
                                    and ref["article"] in wanted):
                                proof.append((article, ref["article"]))
                    if not proof:
                        continue
                    report["verified"] += len(proof)
                    metrics["exact_article_references"] += len(proof)
                    if doc["id"] not in documents:
                        documents[doc["id"]] = {**doc, "reference_only": True}
                    versions[doc["id"]] = package
                next_offset = offset + len(page_candidates)
                last_page = (
                    page * page_size >= report["reported"] or
                    rows_on_page < page_size
                )
                if next_offset >= len(candidates):
                    if last_page:
                        report["complete"] = True
                        report["next_offset"] = 0
                    else:
                        report["next_page"] = page + 1
                        report["next_offset"] = 0
                else:
                    report["next_page"] = page
                    report["next_offset"] = next_offset
                if not report["complete"]:
                    metrics["incomplete_queries"] += 1
            except Exception as exc:
                report["error"] = type(exc).__name__ + ": " + str(exc)[:150]
                metrics["incomplete_queries"] += 1
            metrics["pages"] += 1
            reports.append(report)
        ledger[event_id] = {
            "queries": reports,
            "fully_checked": all(row.get("complete") for row in reports),
            "last_checked_at": utc_now(),
        }
    state["discovery_metrics"] = metrics
    return metrics
