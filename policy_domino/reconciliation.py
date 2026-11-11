"""Independent evidence reconciliation against the official admrulOldAndNew feed.

No notice title, agency or beneficiary program is seeded. Each official
rule-kind / date window is audited; discovered items flow through exactly
the same document comparison and public-service impact pipeline.
"""
from __future__ import annotations

import datetime as dt
import time
from .core import ADMIN_RULE_KINDS, utc_now


def _windows(start: dt.date, end: dt.date, days: int = 28):
    windows = []
    right = end
    while right >= start:
        left = max(start, right - dt.timedelta(days=days-1))
        # Rotate the six formal types for every window, not every year.
        for kind in ADMIN_RULE_KINDS:
            windows.append((left.isoformat(), right.isoformat(), kind))
        right = left - dt.timedelta(days=1)
    return windows


def _query(api, first: str, last: str, kind: str, splits: int = 4):
    records, audit = api.changed_rule_window(first, last, kind)
    if audit.complete:
        return records, [audit.as_dict()], True
    # Split a dense date range if pagination exceeds its page cap.
    # Transport, parser and authorization errors must remain failures.
    if splits <= 0 or first == last or audit.reported < 0:
        return records, [audit.as_dict()], False
    start, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    mid = start + (end-start)//2
    if mid >= end:
        return records, [audit.as_dict()], False
    a, ar, ok1 = _query(api, first, mid.isoformat(), kind, splits-1)
    b, br, ok2 = _query(api,
                      (mid+dt.timedelta(days=1)).isoformat(),last,kind,splits-1)
    merged = {doc["id"]: doc for doc in records}
    merged.update({doc["id"]: doc for doc in a})
    merged.update({doc["id"]: doc for doc in b})
    return list(merged.values()), [audit.as_dict()]+ar+br,ok1 and ok2


def reconcile_changed_rules(api, state: dict, today: dt.date, *,
                            earliest: dt.date | None = None,
                            window_days: int = 28,
                            max_windows: int = 12,
                            max_seconds: float = 210.0) -> dict:
    if earliest is None:
        # Rolling historical breadth, not a fixed list of example notices.
        earliest = today - dt.timedelta(days=720)
    start = time.monotonic()
    windows = _windows(earliest, today, window_days)
    offset = int(state.get("reconcile_cursor", 0)) % len(windows)
    index = offset
    examined = 0
    discovered = 0
    categories = {}
    audits = state.setdefault("reconciliation_windows", {})
    documents = state.setdefault("documents", {})
    newly_identified = []
    while (examined < min(max_windows,len(windows)) and
           time.monotonic() - start < max_seconds):
        first, last, kind = windows[index]
        key = "admrulOldAndNew|" + kind + "|" + first + "|" + last
        try:
            records, pages, complete = _query(api, first, last, kind)
        except Exception as exc:
            records, pages, complete = [], [{
                "source":"admrulOldAndNew", "first":first,"last":last,
                "rule_kind":kind,"complete":False,
                "error":type(exc).__name__+": "+str(exc)[:120]}],False
        missing=[]
        for doc in records:
            if doc["id"] not in documents:
                discovered += 1
                missing.append(doc["id"])
                newly_identified.append(doc["id"])
                documents[doc["id"]] = {**doc,
                    "catalog_sources":["admrulOldAndNew"]}
            else:
                saved = documents[doc["id"]]
                if saved.get("law_type") not in ADMIN_RULE_KINDS.values():
                    saved["law_type"] = ADMIN_RULE_KINDS[kind]
                seen = saved.setdefault("catalog_sources",[])
                if "admrulOldAndNew" not in seen:
                    seen.append("admrulOldAndNew")
        audits[key] = {
            "source":"admrulOldAndNew",
            "kind":ADMIN_RULE_KINDS[kind],
            "first":first,"last":last,
            "indexed_count":len(records),"newly_discovered":len(missing),
            "missing_document_ids":missing[:40],
            "complete":complete,
            "attempted_pages":len(pages),
            "errors":[x.get("error","") for x in pages
                      if x.get("error")][:5],
            "checked_at":utc_now(),
        }
        categories.setdefault(ADMIN_RULE_KINDS[kind],0)
        categories[ADMIN_RULE_KINDS[kind]] += len(records)
        index = (index+1)%len(windows)
        examined += 1
    state["reconcile_cursor"] = index
    # Exact official IDs only. The existing fair work queue will process
    # discovered documents; no previously extracted version is discarded.
    pending = state.setdefault("reconciliation_priority_ids", [])
    pending.extend(x for x in newly_identified if x not in pending)
    state["reconciliation_priority_ids"] = pending[-1500:]
    report = {
        "checked_at":utc_now(), "source":"admrulOldAndNew",
        "windows_checked":examined,
        "windows_total":len(windows),
        "complete_windows":sum(bool(a.get("complete")) for a in audits.values()),
        "failed_windows":sum(not bool(a.get("complete")) for a in audits.values()),
        "new_documents":discovered,
        "documents_awaiting_analysis":len(state["reconciliation_priority_ids"]),
        "range_start":earliest.isoformat(),
        "range_end":today.isoformat(),
        "next_cursor":index,
        "status":"partial" if any(not v.get("complete") for v in audits.values())
                 else "progressing",
    }
    state["reconciliation_run"]=report
    return report
