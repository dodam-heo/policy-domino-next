"""The ONLY production ingestion and analysis pipeline of Policy Domino Next."""
from __future__ import annotations

import datetime as dt
import os
import re
from collections import Counter
from pathlib import Path

from .analysis import compare, review_topics
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
    state["generated_at"] = utc_now()
    return state


def render(state: dict, output: Path = DATA_FILE) -> dict:
    from .analysis import connect_changes
    docs = state.get("documents", {})
    findings = state.get("findings", {})
    edges = connect_changes(findings, state.get("versions", {}), docs)
    indexed = sorted((d.copy() for d in docs.values() if not d.get("reference_only")),
                     key=lambda d: (
        d.get("published_at", ""), d.get("serial", "")), reverse=True)
    for row in indexed:
        row["analysis"] = findings.get(row["id"], {
            "status": "queued", "changes": [], "review_candidates": [],
            "reason": "공식 목록 수집 · 이전·현재 본문 분석 대기"})
    data = {
        "schema": state["schema"],
        "generated_at": state.get("generated_at", ""),
        "configuration": "running" if state.get("generated_at") else
                         "not_run_or_credential_missing",
        "coverage": state.get("coverage", []),
        "quality": quality(state),
        "documents": indexed,
        "relationships": edges,
        "principles": {
            "manual_institutions": False,
            "inferred_programs_count_as_confirmed": False,
            "internal_compliance_status_known": False,
        },
    }
    write_json(output, data)
    return data


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run", "render"))
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--state", type=Path, default=STATE_FILE)
    parser.add_argument("--output", type=Path, default=DATA_FILE)
    args = parser.parse_args(argv)
    state = load_state(args.state)
    if args.mode == "run":
        credential = os.getenv("LAW_OC", "")
        if not credential:
            raise SystemExit("LAW_OC missing: cannot claim a live source run")
        run_once(state, LawAPI(credential), dt.date.today(), max(1, min(args.limit, 150)))
        write_json(args.state, state)
    result = render(state, args.output)
    print("Policy Domino Next:", {
        "documents": len(result["documents"]),
        "relationships": len(result["relationships"]),
        "quality": result["quality"]})


if __name__ == "__main__":
    main()
