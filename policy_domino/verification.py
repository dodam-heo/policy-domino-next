"""Production coverage audit: distinguish internal integrity from completeness.

A successful schema/evidence contract proves a claim is internally supported.
It does not prove that every official instrument, annex, service or public
institution was collected or that every relevant downstream impact was found.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .events import is_office_title

FINISHED = {"compared", "no_text_change", "enactment", "repeal"}


def audit(data: dict) -> dict:
    documents = data.get("documents", [])
    events = data.get("events", [])
    by_source = defaultdict(Counter)
    statuses = Counter()
    for document in documents:
        source = str(document.get("source") or "unknown")
        status = str((document.get("analysis") or {}).get("status") or "queued")
        by_source[source]["indexed"] += 1
        by_source[source][status] += 1
        statuses[status] += 1

    offices = sorted({
        str(review.get("institution"))
        for event in events
        for review in event.get("institutional_reviews", [])
        if is_office_title(review.get("institution", ""))
    })
    directory_offices = sorted({
        str(row.get("agency")) for row in data.get("agency_directory", [])
        if is_office_title(row.get("agency", ""))
    })
    total = len(documents)
    reviewed = sum(count for status, count in statuses.items()
                   if status in FINISHED)
    unfinished = total - reviewed
    incomplete_source = (data.get("collection_run") or {})
    independent = (data.get("reconciliation_run") or {})
    rules = (data.get("quality") or {}).get("rule_categories") or {}
    nonstandard = rules.get("미분류") or {}
    source_windows = {
        "recent_complete": incomplete_source.get("recent_complete") is True,
        "historical_complete": incomplete_source.get("historical_complete") is True,
        "failed_windows": int(incomplete_source.get("failed_windows") or 0),
        "deferred_streams": int(incomplete_source.get("deferred_streams") or 0),
        "independent_comparison_status": independent.get("status", "not_reported"),
        "independent_windows_checked": independent.get("windows_checked"),
        "independent_windows_total": independent.get("windows_total"),
    }
    # No independent nationwide ground truth is supplied for the entire
    # legal/ordinance/rule time horizon. Never declare 100% collection.
    complete = (
        unfinished == 0
        and not offices
        and source_windows["recent_complete"]
        and source_windows["historical_complete"]
        and source_windows["failed_windows"] == 0
        and source_windows["deferred_streams"] == 0
    )
    reviews = [row for event in events
               for row in event.get("institutional_reviews", [])]
    evidence_tiers = Counter(row.get("basis_tier", "unknown") for row in reviews)
    output = {
        "status": "incomplete" if not complete else "indexed_inventory_processed",
        "official_universe_exhaustively_reconciled": False,
        "institutional_impact_completeness_verified": False,
        "indexed_documents": total,
        "fully_processed_indexed_documents": reviewed,
        "incompletely_processed_indexed_documents": unfinished,
        "status_counts": dict(sorted(statuses.items())),
        "source_breakdown": {source: dict(sorted(counts.items()))
                             for source, counts in sorted(by_source.items())},
        "collection_audit": source_windows,
        "unclassified_administrative_rules": int(nonstandard.get("indexed") or 0),
        "verified_change_events": len(events),
        "source_bound_institutional_review_rows": len(reviews),
        "review_evidence_tiers": dict(sorted(evidence_tiers.items())),
        "official_public_services_indexed": data.get("public_services_indexed", 0),
        "public_service_review_candidates": data.get("public_service_review_leads", 0),
        "officeholders_misclassified_as_agencies": offices,
        "officeholders_in_public_directory": directory_offices,
        "explanation": (
            "The official index and existing proof links were checked. "
            "External nationwide source exhaustiveness and all possible "
            "business-impact connections remain unverified."
        ),
    }
    return output


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m policy_domino.verification INPUT [OUTPUT]")
    source = Path(sys.argv[1])
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("distribution") == "split-v1":
        base = source.parent
        sources = json.loads((base / "sources.json").read_text(encoding="utf-8"))
        data["documents"] = sources["documents"]
        data["events"] = [
            json.loads((base / "details" / (event["id"] + ".json")
                       ).read_text(encoding="utf-8"))
            for event in data.get("events", [])
        ]
    result = audit(data)
    if len(sys.argv) >= 3:
        Path(sys.argv[2]).write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
    print("Production completeness and linkage audit:",
          json.dumps(result, ensure_ascii=False))
    if (result["officeholders_misclassified_as_agencies"] or
            result["officeholders_in_public_directory"]):
        raise SystemExit("Invalid public institution: statutory officeholders found.")


if __name__ == "__main__":
    main()
