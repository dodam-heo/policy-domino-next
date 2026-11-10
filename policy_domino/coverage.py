"""Independent official-source backfill and fair analysis queues.

Source indexes are not analyzed changes. Each source/version keeps an absolute
historical cursor, while recent documents and old untouched records receive
separate processing turns. Failed windows never silently count as covered.
"""
from __future__ import annotations

import datetime as dt
from .core import SOURCES, utc_now

MAX_ATTEMPTS = 4
DONE = frozenset({"compared", "no_text_change", "enactment", "repeal"})


def collect_streams(api, state, today: dt.date, ingest_window) -> bool:
    recent_first = (today - dt.timedelta(days=6)).isoformat()
    recent_last = today.isoformat()
    cursors = state.setdefault("backfill_end_dates", {})
    audits = state.setdefault("collection_windows", {})
    state["coverage"] = []
    results = []

    def load(source, version, first, last, stage):
        try:
            completed = ingest_window(api, state, source, first, last, version)
            error = "" if completed else "Official pagination incomplete"
        except Exception as exc:
            completed = False
            error = type(exc).__name__ + ": " + str(exc)[:160]
            state["coverage"].append({
                "source": source, "version": version, "first": first,
                "last": last, "complete": False, "reported": -1,
                "collected": 0, "pages": 0, "error": error,
            })
        record = {
            "source": source, "version": version, "first": first,
            "last": last, "stage": stage, "complete": completed,
            "error": error, "checked_at": utc_now(),
        }
        audits["|".join((source, version, first, last))] = record
        results.append(record)
        return completed

    for source in SOURCES:
        for version in (("1", "2") if source != "law" else ("1",)):
            key = source + "|" + version
            load(source, version, recent_first, recent_last, "recent")
            if key in cursors:
                old_end = dt.date.fromisoformat(cursors[key])
            else:
                older_days = 7 + int(state.get("cursor_days", 0))
                old_end = today - dt.timedelta(days=older_days)
            old_start = old_end - dt.timedelta(days=6)
            if load(source, version, old_start.isoformat(),
                    old_end.isoformat(), "historical"):
                cursors[key] = (old_start - dt.timedelta(days=1)).isoformat()
            else:
                cursors[key] = old_end.isoformat()

    state["collection_run"] = {
        "checked_at": utc_now(),
        "streams": len(results),
        "completed_windows": sum(int(x["complete"]) for x in results),
        "failed_windows": sum(int(not x["complete"]) for x in results),
        "recent_complete": all(x["complete"] for x in results
                               if x["stage"] == "recent"),
        "historical_complete": all(x["complete"] for x in results
                                   if x["stage"] == "historical"),
        "backfill_end_dates": dict(cursors),
    }
    state["last_collected_at"] = state["collection_run"]["checked_at"]
    return all(row["complete"] for row in results)


def retry_due(attempt: dict, today: dt.date) -> bool:
    """Past the initial retry threshold, retry after bounded cool-down.

    Source data may become available later. Never make four failures a
    permanent terminal state; avoid hammering the public API on each run.
    """
    count = int(attempt.get("count", 0))
    if count < MAX_ATTEMPTS:
        return True
    try:
        previous = dt.date.fromisoformat(attempt.get("last_date", ""))
    except (ValueError, TypeError):
        return False
    interval = min(30, 2 ** min(5, count - MAX_ATTEMPTS + 1))
    return (today - previous).days >= interval


def pending_counts(state, today: dt.date | None = None) -> dict:
    """Separate analyzed, untouched, active retries and cooled-off retries."""
    today = today or dt.date.today()
    data = {}
    for source in SOURCES:
        docs = [x for x in state.get("documents", {}).values()
                if x.get("source") == source and not x.get("reference_only")]
        stats = {"indexed": len(docs), "verified": 0,
                 "partial": 0, "unexamined": 0, "retryable": 0, "blocked": 0}
        for doc in docs:
            finding = state.get("findings", {}).get(doc["id"], {})
            if finding.get("status") in DONE:
                stats["verified"] += 1
            else:
                if finding.get("status") == "partial_compared":
                    stats["partial"] += 1
                if not state.get("attempts", {}).get(doc["id"], {}).get("count", 0):
                    stats["unexamined"] += 1
                elif not retry_due(state["attempts"][doc["id"]], today):
                    stats["blocked"] += 1
                else:
                    stats["retryable"] += 1
        data[source] = stats
    return data

def fair_work_queue(state, today: dt.date, limit: int) -> list[dict]:
    """A protected backlog share prevents newest-first permanent starvation."""
    cutoff = (today - dt.timedelta(days=21)).isoformat()
    attempts = state.get("attempts", {})
    pools = {source: {"recent": [], "backlog": [], "retry": []}
             for source in SOURCES}
    for doc in state.get("documents", {}).values():
        if doc.get("reference_only") or doc.get("source") not in pools:
            continue
        key = doc["id"]
        if state.get("findings", {}).get(key, {}).get("status") in DONE:
            continue
        attempt = attempts.get(key, {})
        if not retry_due(attempt, today):
            continue
        if attempt.get("last_date") == today.isoformat():
            continue
        group = ("retry" if attempt.get("count", 0) else
                 "recent" if doc.get("published_at", "") >= cutoff
                 else "backlog")
        pools[doc["source"]][group].append(doc)

    for source in SOURCES:
        pools[source]["recent"].sort(key=lambda d:
            (d.get("published_at", ""), d.get("serial", "")), reverse=True)
        pools[source]["backlog"].sort(key=lambda d:
            (d.get("published_at", ""), d.get("serial", "")))
        pools[source]["retry"].sort(key=lambda d: (
            attempts.get(d["id"], {}).get("count", 0),
            attempts.get(d["id"], {}).get("last_date", ""),
            d.get("published_at", "")))

    chosen = []
    rhythm = ("recent", "backlog", "recent", "backlog", "retry")
    turn = 0
    while len(chosen) < max(0, limit):
        progressed = False
        preferred = rhythm[turn % len(rhythm)]
        for source in SOURCES:
            if len(chosen) >= limit:
                break
            queues = pools[source]
            for channel in dict.fromkeys((preferred, "recent", "backlog", "retry")):
                if queues[channel]:
                    chosen.append(queues[channel].pop(0))
                    progressed = True
                    break
        if not progressed:
            break
        turn += 1
    return chosen
