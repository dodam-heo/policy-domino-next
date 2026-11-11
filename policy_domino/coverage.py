"""Independent official-source backfill and fair analysis queues.

Source indexes are not analyzed changes. Each source/version keeps an absolute
historical cursor, while recent documents and old untouched records receive
separate processing turns. Failed windows never silently count as covered.
"""
from __future__ import annotations

import datetime as dt
import time
import re
from .core import SOURCES, ADMIN_RULE_KINDS, utc_now
from collections import defaultdict, deque

MAX_ATTEMPTS = 4
DONE = frozenset({"compared", "no_text_change", "enactment", "repeal"})
ANNUAL_RULE_TITLE = re.compile(r"(19|20)\d{2}\s*년(?:도)?")


def collect_streams(api, state, today: dt.date, ingest_window,
                    *, max_seconds: float | None = None) -> bool:
    started = time.monotonic()
    recent_first = (today - dt.timedelta(days=6)).isoformat()
    recent_last = today.isoformat()
    cursors = state.setdefault("backfill_end_dates", {})
    audits = state.setdefault("collection_windows", {})
    state["coverage"] = []
    results = []

    def load(source, version, first, last, stage, rule_kind=""):
        try:
            if rule_kind:
                completed = ingest_window(
                    api, state, source, first, last, version, rule_kind=rule_kind)
            else:
                completed = ingest_window(api, state, source, first, last, version)
            error = "" if completed else "Official pagination incomplete"
        except Exception as exc:
            completed = False
            error = type(exc).__name__ + ": " + str(exc)[:160]
            state["coverage"].append({
                "source": source, "version": version, "rule_kind": rule_kind,
                "first": first, "last": last, "complete": False,
                "reported": -1, "collected": 0, "pages": 0, "error": error})
        record = {
            "source": source, "version": version,
            "rule_kind": rule_kind,
            "rule_category": ADMIN_RULE_KINDS.get(rule_kind, ""),
            "first": first, "last": last, "stage": stage,
            "complete": completed, "error": error, "checked_at": utc_now()}
        audits["|".join((source,version,rule_kind,first,last))] = record
        results.append(record)
        return completed

    streams = ([("law", "1", "")] +
               [("admrul", version, kind)
                for version in ("1", "2")
                for kind in ADMIN_RULE_KINDS] +
               [("ordin", version, "") for version in ("1", "2")])
    offset=int(state.get("collection_stream_offset", 0)) % len(streams)
    streams=streams[offset:]+streams[:offset]
    executed=0
    for source, version, rule_kind in streams:
        if (max_seconds is not None and
                time.monotonic() - started >= max_seconds):
            break
        executed+=1
        key = "|".join(filter(None, (source, version, rule_kind)))
        load(source, version, recent_first, recent_last, "recent", rule_kind)
        if key in cursors:
            old_end = dt.date.fromisoformat(cursors[key])
        elif rule_kind and f"admrul|{version}" in cursors:
            # Inherit the previous verified history boundary when migrating
            # the generic rule stream into official knd-specific streams.
            old_end = dt.date.fromisoformat(cursors[f"admrul|{version}"])
        else:
            old_end = today - dt.timedelta(days=7+int(state.get("cursor_days",0)))
        # Advance the independent historical cursors in useful blocks.
        # Each queried block is recursively split by ingest_window when the
        # public API page limit would omit records; never advance on failure.
        span = 28 if source == "admrul" else 14
        old_start = old_end - dt.timedelta(days=span - 1)
        if load(source, version, old_start.isoformat(),
                old_end.isoformat(), "historical", rule_kind):
            cursors[key]=(old_start-dt.timedelta(days=1)).isoformat()
        else:
            cursors[key]=old_end.isoformat()

    state["collection_stream_offset"] = (offset+executed) % len(streams)
    deferred=len(streams)-executed
    state["collection_run"] = {
        "checked_at": utc_now(),
        "streams": len(results),
        "deferred_streams": deferred,
        "elapsed_seconds": round(time.monotonic()-started, 1),
        "completed_windows": sum(int(x["complete"]) for x in results),
        "failed_windows": sum(int(not x["complete"]) for x in results),
        "rule_kinds": {
            label: {
                "completed": sum(int(r["complete"]) for r in results
                                 if r["rule_kind"] == kind),
                "failed": sum(int(not r["complete"]) for r in results
                              if r["rule_kind"] == kind)}
            for kind,label in ADMIN_RULE_KINDS.items()},
        "recent_complete": deferred == 0 and all(
            x["complete"] for x in results if x["stage"] == "recent"),
        "historical_complete": deferred == 0 and all(
            x["complete"] for x in results if x["stage"] == "historical"),
        "backfill_end_dates": dict(cursors),
        "historical_window_days": {"law": 14, "admrul": 28, "ordin": 14},
    }
    state["last_collected_at"] = state["collection_run"]["checked_at"]
    return deferred == 0 and all(row["complete"] for row in results)


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
    if limit <= 0:
        return []
    cutoff = (today - dt.timedelta(days=21)).isoformat()
    attempts = state.get("attempts", {})
    pools = {source: {"recent": [], "backlog": [], "retry": []}
             for source in SOURCES}
    for doc in state.get("documents", {}).values():
        if doc.get("reference_only") or doc.get("source") not in pools:
            continue
        key = doc["id"]
        status=state.get("findings", {}).get(key, {}).get("status")
        annual_recheck=(
            status == "enactment" and
            doc.get("source") == "admrul" and
            bool(ANNUAL_RULE_TITLE.search(doc.get("title",""))) and
            key not in state.get("annual_recheck_completed_ids",[]))
        if status in DONE and not annual_recheck:
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

    # Every *official kind* of administrative rules receives a fair turn.
    # Otherwise thousands of generic rules can starve newly discovered
    # notices and guidelines while the source-level round robin looks fair.
    # Preserve existing recency/oldest/retry ordering within each kind.
    offset = int(state.get("rule_processing_rotation", 0))
    for channel in ("recent", "backlog", "retry"):
        by_kind = defaultdict(deque)
        for doc in pools["admrul"][channel]:
            kind = doc.get("law_type", "")
            if kind not in ADMIN_RULE_KINDS.values():
                kind = "미분류"
            by_kind[kind].append(doc)
        kinds = sorted(by_kind)
        if not kinds:
            continue
        rotated = kinds[offset % len(kinds):] + kinds[:offset % len(kinds)]
        woven = []
        while any(by_kind.values()):
            for kind in rotated:
                if by_kind[kind]:
                    woven.append(by_kind[kind].popleft())
        pools["admrul"][channel] = woven
    state["rule_processing_rotation"] = offset + 1

    # Guaranteed but bounded slots for records verified by a second
    # independent official comparison feed. Never starve the standard queue.
    priority = []
    for key in state.get("reconciliation_priority_ids", []):
        row = state.get("documents", {}).get(key)
        if (row and not row.get("reference_only") and
            state.get("findings", {}).get(key, {}).get("status") not in DONE
            and retry_due(attempts.get(key, {}), today)
            and attempts.get(key, {}).get("last_date") != today.isoformat()):
            priority.append(row)
    priority = priority[:max(1, limit // 3)]
    # Publication order alone strands notices issued months before they take
    # effect. Reserve a bounded share for upcoming official effective dates,
    # across every source and subject, while keeping the historical lanes.
    priority_ids = {d["id"] for d in priority}
    horizon = (today + dt.timedelta(days=366)).isoformat()
    upcoming = [row for queues in pools.values()
                for rows in queues.values() for row in rows
                if today.isoformat() < row.get("effective_date", "") <= horizon
                and row["id"] not in priority_ids]
    upcoming.sort(key=lambda row: (
        not bool(re.search(r"기준|금액|요건|선정|수준", row.get("title", ""))),
        row["effective_date"], attempts.get(row["id"], {}).get("count", 0),
        row.get("published_at", ""), row["id"]))
    priority.extend(upcoming[:min(max(1, limit // 6), limit-len(priority))])
    priority_ids = {d["id"] for d in priority}
    for source in SOURCES:
        for channel in ("recent","backlog","retry"):
            pools[source][channel] = [
                row for row in pools[source][channel]
                if row["id"] not in priority_ids]
    chosen = list(priority)
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
