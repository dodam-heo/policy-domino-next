"""The ONLY production ingestion and analysis pipeline of Policy Domino Next."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from collections import Counter
from pathlib import Path

from .analysis import compare, review_topics, direct_actor_reviews
from .api import LawAPI
from .core import SOURCES, document_key, load_state, new_state, utc_now, write_json
from .parser import parse_document

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "state.json"
DATA_FILE = ROOT / "site" / "data.json"

YEAR_TITLE = re.compile(r"(19|20)\d{2}\s*년(?:도)?")
TERMINAL = {"compared", "no_text_change", "enactment", "repeal"}
RETRYABLE = {"queued", "body_unavailable", "history_unavailable",
             "baseline_unavailable", "partial_compared", "partial_unresolved",
             "source_error"}
MAX_ATTEMPTS = 4


def windows(today: dt.date, cursor_days: int = 0):
    latest = (today - dt.timedelta(days=6), today)
    older_end = today - dt.timedelta(days=7 + cursor_days)
    older = (older_end - dt.timedelta(days=6), older_end)
    return [(x.isoformat(), y.isoformat()) for x, y in (latest, older)]


def ingest_window(api: LawAPI, state: dict, source: str, first: str, last: str,
                  version: str, splits: int = 3) -> bool:
    found, audit = api.search_window(source, first, last, version)
    for record in found:
        state["documents"][record["id"]] = record
    state["coverage"].append(audit.as_dict())
    if audit.complete:
        return True
    if splits <= 0 or first == last or audit.reported < 0:
        return False
    a, b = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    mid = a + (b - a) // 2
    if mid >= b:
        return False
    left = ingest_window(api, state, source, first, mid.isoformat(), version, splits - 1)
    right = ingest_window(api, state, source,
                          (mid + dt.timedelta(days=1)).isoformat(), last,
                          version, splits - 1)
    return left and right


def collect(api: LawAPI, state: dict, today: dt.date):
    recent, older = windows(today, int(state.get("cursor_days", 0)))
    completed = True
    state["coverage"] = []
    for source in SOURCES:
        for version in (("1", "2") if source != "law" else ("1",)):
            for first, last in (recent, older):
                try:
                    complete = ingest_window(api, state, source, first, last, version)
                    if not complete:
                        completed = False
                except Exception as exc:
                    completed = False
                    state["coverage"].append({
                        "source": source, "first": first, "last": last,
                        "version": version, "complete": False,
                        "reported": -1, "collected": 0, "pages": 0,
                        "error": type(exc).__name__ + ": " + str(exc)[:170]})
    if completed:
        state["cursor_days"] = int(state.get("cursor_days", 0)) + 7
    return completed


def work_queue(state: dict, today: dt.date, limit: int) -> list[dict]:
    """Round-robin official sources, prioritizing fresh, retriable versions.

    A source may have tens of thousands of changes: a hard per-run limit
    is never interpreted as complete discovery or lack of impact.
    """
    pool = {source: [] for source in SOURCES}
    attempts = state.get("attempts", {})
    for doc in state.get("documents", {}).values():
        if doc.get("reference_only"):
            # Baselines fetched during comparison are not new events.
            continue
        key = doc["id"]
        finding = state.get("findings", {}).get(key, {})
        if finding.get("status") in TERMINAL:
            continue
        attempt = attempts.get(key, {})
        if attempt.get("count", 0) >= MAX_ATTEMPTS:
            continue
        if attempt.get("last_date") == today.isoformat():
            continue
        pool[doc["source"]].append(doc)
    for source in SOURCES:
        pool[source].sort(key=lambda d: (
            d.get("published_at", ""), -attempts.get(d["id"], {}).get("count", 0),
            d.get("serial", "")), reverse=True)
    picked = []
    while len(picked) < limit and any(pool.values()):
        for source in SOURCES:
            if len(picked) >= limit:
                break
            if pool[source]:
                picked.append(pool[source].pop(0))
    return picked


def _prior_from_catalog(state: dict, doc: dict):
    versions = [x for x in state["documents"].values()
                if x["source"] == doc["source"] and
                   x["stable_id"] == doc["stable_id"] and
                   (x["published_at"], x["serial"]) <
                   (doc["published_at"], doc["serial"])]
    return max(versions, key=lambda x: (x["published_at"], x["serial"])) if versions else None


def _annual_baseline(api: LawAPI, doc: dict) -> dict | None:
    if doc["source"] != "admrul":
        return None
    hit = YEAR_TITLE.search(doc["title"])
    if not hit:
        return None
    year = int(re.search(r"\d{4}", hit.group()).group())
    if year < 1901:
        return None
    old_title = doc["title"][:hit.start()] + hit.group().replace(
        str(year), str(year - 1), 1) + doc["title"][hit.end():]
    # Only the actual preceding-year title, dynamically derived.
    root = api.request("lawSearch.do", "admrul", query=old_title,
                       nw="1,2", display=100, page=1)
    from .api import nodes, parse_record
    options = [parse_record(x, "admrul") for x in nodes(root, "admrul")]
    options = [x for x in options if x and x["title"] == old_title and
               x["published_at"] < doc["published_at"]]
    return max(options, key=lambda x: x["published_at"]) if options else None


def analyze_one(api: LawAPI, state: dict, doc: dict) -> dict:
    after = parse_document(api.detail(doc))
    state["versions"][doc["id"]] = after
    base = {
        "event_id": doc["id"], "status": "",
        "baseline": None, "changes": [], "excluded": [],
        "review_candidates": [], "reason": "",
    }
    if after["status"] in ("body_missing", "attachment_only"):
        return dict(base, status="body_unavailable", reason=after["status"])
    revision = doc.get("revision", "")
    if "폐지" in revision:
        return dict(base, status="repeal", reason="공식 폐지문 확인; 새 의무 생성 없음")
    if "제정" in revision and "개정" not in revision:
        return dict(base, status="enactment", reason="공식 신규 제정 본문 확보")
    prior = _prior_from_catalog(state, doc)
    history_error = ""
    try:
        older = api.history(doc)
        for candidate in older:
            if ((candidate["published_at"], candidate["serial"]) <
                    (doc["published_at"], doc["serial"])):
                if not prior or ((candidate["published_at"], candidate["serial"]) >
                                  (prior["published_at"], prior["serial"])):
                    prior = candidate
                break
    except Exception as exc:
        history_error = str(exc)[:140]
    if not prior:
        try:
            prior = _annual_baseline(api, doc)
        except Exception as exc:
            history_error += " annual: " + str(exc)[:100]
    if not prior:
        return dict(base, status="history_unavailable" if history_error else
                    "baseline_unavailable",
                    reason=history_error or "이전 공식 개정 이력 미확보")
    # Keep both official versions, but do not treat baseline as a new change.
    if prior["id"] not in state["documents"]:
        state["documents"][prior["id"]] = {**prior, "reference_only": True}
    previous = state["versions"].get(prior["id"])
    if not previous:
        previous = parse_document(api.detail(prior))
        state["versions"][prior["id"]] = previous
    result = compare(previous, after, doc)
    result.update({
        "event_id": doc["id"],
        "baseline": {
            "id": prior["id"], "serial": prior["serial"],
            "published_at": prior["published_at"], "url": prior["url"],
        },
        "review_candidates": review_topics(result["changes"]),
        "direct_actor_reviews": direct_actor_reviews(result["changes"]),
    })
    return result


def quality(state: dict) -> dict:
    docs = state.get("documents", {})
    findings = state.get("findings", {})
    result = {}
    for source in SOURCES:
        ids = [k for k, value in docs.items()
               if value["source"] == source and not value.get("reference_only")]
        counts = Counter(findings.get(k, {}).get("status", "queued") for k in ids)
        result[source] = {
            "indexed": len(ids), "status_counts": dict(sorted(counts.items())),
            "verified_changes": counts["compared"] + counts["partial_compared"],
            "waiting": sum(v for k, v in counts.items() if k not in TERMINAL),
            "unavailable_bodies": counts["body_unavailable"],
            "unavailable_history": counts["history_unavailable"] + counts["baseline_unavailable"],
        }
    result["coverage_incomplete"] = sum(
        not x.get("complete", False) for x in state.get("coverage", []))
    return result


def run_once(state: dict, api: LawAPI, today: dt.date, limit: int = 24) -> dict:
    collect(api, state, today)
    for doc in work_queue(state, today, limit):
        attempt = state.setdefault("attempts", {}).setdefault(doc["id"], {})
        attempt["count"] = int(attempt.get("count", 0)) + 1
        attempt["last_date"] = today.isoformat()
        try:
            state["findings"][doc["id"]] = analyze_one(api, state, doc)
        except Exception as exc:
            state["findings"][doc["id"]] = {
                "event_id": doc["id"], "status": "source_error",
                "changes": [], "excluded": [], "review_candidates": [],
                "reason": type(exc).__name__ + ": " + str(exc)[:160],
            }
    # Search the official legal corpus beyond this week's indexed changes.
    # Search hits become graph edges only after full-body exact article proof.
    if hasattr(api,"request"):
        from .discovery import discover_dependents
        discover_dependents(api,state,limit_events=min(3,max(1,limit//8)))
    # Separately discover official public-program evidence. Failure to parse
    # an external source never removes previously collected legal or program data.
    # Synthetic unit-test clients do not initiate uncontrolled network requests.
    if isinstance(api, LawAPI):
        from .alioplus import ALIOPlusClient
        # Exhaust the safely linked first-page public programmes incrementally.
        # This is still not a nationwide programme register and must not be
        # marked complete until the official provider's pagination is verified.
        state["program_source_audit"] = ALIOPlusClient().collect(state, max_details=15)
    # LLM calls run in a separate bounded step against persisted source data.
    # Collection must never burn API quota or conceal a failed analysis.
    state["generated_at"] = utc_now()
    return state


def render(state: dict, output: Path = DATA_FILE) -> dict:
    from .analysis import connect_changes
    docs = state.get("documents", {})
    findings = state.get("findings", {})
    edges = connect_changes(findings, state.get("versions", {}), docs)
    from .analysis import cross_document_actor_reviews
    work_reviews = cross_document_actor_reviews(edges, findings)
    from .programs import discover_program_links, program_audit
    program_links = discover_program_links(state, edges)
    indexed = sorted((d.copy() for d in docs.values() if not d.get("reference_only")),
                     key=lambda d: (
        d.get("published_at", ""), d.get("serial", "")), reverse=True)
    from .ai import publishable_draft
    from .events import build_events
    verified_count = 0
    ai_review_count = 0
    validated_ai = {}
    for row in indexed:
        row["analysis"] = findings.get(row["id"], {
            "status": "queued", "changes": [], "review_candidates": [],
            "reason": "공식 목록 수집 · 이전·현재 본문 분석 대기"}).copy()
        generated = publishable_draft(
            state, row["id"], program_links, relationships=edges)
        if row["analysis"].get("changes"):
            verified_count += 1
        if generated is not None:
            row["analysis"]["ai"] = generated
            validated_ai[row["id"]] = generated
            ai_review_count += 1
    # Document records remain the audited *input*. Public navigation is
    # constructed from exact officially verified *change events*, never
    # directly from an unverified document index.
    events = build_events(
        docs, findings, relationships=edges,
        program_dependencies=program_links,
        cross_document_reviews=work_reviews,
        ai_reviews=validated_ai,
    )
    data = {
        "schema": state["schema"],
        "generated_at": state.get("generated_at", ""),
        "configuration": "running" if state.get("generated_at") else
                         "not_run_or_credential_missing",
        "coverage": state.get("coverage", []),
        "quality": quality(state),
        "documents": indexed,
        # Minimal metadata for official rules found via downstream citation
        # searches. A source-only referencing regulation is not a new change.
        "reference_documents": sorted(({
            "id": item["id"], "source": item["source"],
            "title": item["title"], "ministry": item.get("ministry", ""),
            "url": item["url"],
        } for item in docs.values() if item.get("reference_only")),
            key=lambda x: x["id"]),
        "events": events,
        "relationships": edges,
        "cross_document_review_candidates": work_reviews,
        "program_dependencies": program_links,
        "ai_progress": {
            "indexed_documents": len(indexed),
            "source_events": len(events),
            "verified_events": len(events),
            "analyzed_events": sum(bool(e["ai_count"]) for e in events),
            "pending_events": sum(not e["ai_count"] for e in events),
            "analyzed_documents": ai_review_count,
            "verified_document_changes": verified_count,
            "verified_clauses": sum(len(event["changes"]) for event in events),
            "ai_analyzed_clauses": sum(
                len({(x.get("document_id", ""), x.get("article", ""))
                     for x in event["ai_summaries"]})
                for event in events),
            "official_program_records": len(state.get("official_programs", {})),
            "verified_program_links": len(program_links),
            "referencing_public_rule_reviews": sum(
                1 for event in events
                for review in event["institutional_reviews"]
                if review["basis_tier"] == "verified_official_rule_citation"),
            "institutional_reviews": sum(e["review_count"] for e in events),
            "affected_institutions": len({
                a["institution"]
                for e in events for a in e["institutional_reviews"]
            }),
            "last_checked_at": state.get("ai_run", {}).get("checked_at", ""),
            "last_attempted": state.get("ai_run", {}).get("attempted", 0),
            "last_generated": state.get("ai_run", {}).get("generated", 0),
        },
        "ai_status": state.get("ai_status", "not_run"),
        "ai_run": state.get("ai_run", {}),
        "program_discovery_audit": {
            **program_audit(state, program_links),
            "source": state.get("program_source_audit", {}),
        },
        "discovery_audit": state.get("discovery_metrics",{}),
        "principles": {
            "manual_institutions": False,
            "inferred_programs_count_as_confirmed": False,
            "internal_compliance_status_known": False,
        },
    }
    from .contracts import validate_public
    validate_public(data)
    write_json(output, data)
    return data


DEFAULT_LAW_OC = "dori"  # Same public OC fallback as the prior project.


def configured_law_oc() -> str:
    return os.getenv("LAW_OC", "").strip() or DEFAULT_LAW_OC


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run", "render", "ai", "ai-check"))
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--state", type=Path, default=STATE_FILE)
    parser.add_argument("--output", type=Path, default=DATA_FILE)
    args = parser.parse_args(argv)
    state = load_state(args.state)
    if args.mode == "run":
        # The previous project's publicly configured official API OC is
        # "dori". It is an OC identifier, not a private API secret.
        # Keep the same working fallback; explicit LAW_OC may override it.
        credential = configured_law_oc()
        run_once(state, LawAPI(credential), dt.date.today(), max(1, min(args.limit, 150)))
        write_json(args.state, state)
    if args.mode == "ai-check":
        from .ai import assess_ai_run
        report = state.get("ai_run", {})
        print("Policy Domino AI verification:", json.dumps(report, ensure_ascii=False))
        health = assess_ai_run(report)
        if health != "success":
            codes = ",".join(sorted(report.get("error_codes") or {})) or "none"
            detail = ("status=" + str(report.get("status", "missing")) +
                      "; requested=" + str(report.get("attempted", 0)) +
                      "; generated=" + str(report.get("generated", 0)) +
                      "; failures=" + str(report.get("errors", 0)) +
                      "; error_codes=" + codes)
            if health == "warning":
                print("::warning title=Gemini analysis partially available::" + detail)
            else:
                print("::error title=Gemini analysis unavailable::" + detail)
                raise SystemExit(1)
        return
    if args.mode == "ai":
        from .analysis import connect_changes
        from .programs import discover_program_links
        from .ai import analyze_batch
        edges = connect_changes(state["findings"], state["versions"], state["documents"])
        links = discover_program_links(state, edges)
        report = analyze_batch(
            state, links, limit=max(1, min(args.limit, 60)),
            relationships=edges)
        write_json(args.state, state)
        print("Policy Domino AI:", json.dumps(report, ensure_ascii=False))
    result = render(state, args.output)
    print("Policy Domino Next:", {
        "documents": len(result["documents"]),
        "relationships": len(result["relationships"]),
        "quality": result["quality"]})


if __name__ == "__main__":
    main()
