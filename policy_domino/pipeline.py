"""The ONLY production ingestion and analysis pipeline of Policy Domino Next."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

from .analysis import compare, review_topics, direct_actor_reviews
from .api import LawAPI
from .core import SOURCES, document_key, load_state, new_state, utc_now, write_json
from .state_store import save_shards
from .core import SCHEMA
from .parser import parse_document

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "state.json"
DATA_FILE = ROOT / "site" / "catalog.json"

YEAR_TITLE = re.compile(r"(19|20)\d{2}\s*년(?:도)?")
TERMINAL = {"compared", "no_text_change", "enactment", "repeal"}


def windows(today: dt.date, cursor_days: int = 0):
    latest = (today - dt.timedelta(days=6), today)
    older_end = today - dt.timedelta(days=7 + cursor_days)
    older = (older_end - dt.timedelta(days=6), older_end)
    return [(x.isoformat(), y.isoformat()) for x, y in (latest, older)]


def ingest_window(api: LawAPI, state: dict, source: str, first: str, last: str,
                  version: str, splits: int = 3,
                  rule_kind: str = "") -> bool:
    found, audit = (api.search_window(source, first, last, version,
                                      rule_kind=rule_kind)
                    if rule_kind else api.search_window(source, first, last, version))
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
    left = ingest_window(api, state, source, first, mid.isoformat(), version,
                         splits - 1, rule_kind=rule_kind)
    right = ingest_window(api, state, source,
                          (mid + dt.timedelta(days=1)).isoformat(), last,
                          version, splits - 1, rule_kind=rule_kind)
    return left and right


def collect(api: LawAPI, state: dict, today: dt.date,
            *, max_seconds: float | None = None):
    from .coverage import collect_streams
    return collect_streams(api, state, today, ingest_window,
                           max_seconds=max_seconds)


def work_queue(state: dict, today: dt.date, limit: int) -> list[dict]:
    from .coverage import fair_work_queue
    return fair_work_queue(state, today, limit)


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
    from .api import nodes, parse_record
    options = []
    for version in ("1", "2"):
        # Official admrul nw accepts an INTEGER (1=current, 2=history).
        # A comma-separated 1,2 is not a documented request value.
        root = api.request("lawSearch.do", "admrul", query=old_title,
                           nw=version, display=100, page=1)
        options.extend(parse_record(x, "admrul") for x in nodes(root, "admrul"))
    options = [x for x in options if x and x["title"] == old_title and
               x["published_at"] < doc["published_at"]]
    return max(options, key=lambda x: x["published_at"]) if options else None


def analyze_one(api: LawAPI, state: dict, doc: dict) -> dict:
    root = api.detail(doc)
    if doc.get("source") == "admrul":
        from .api import field
        from .core import ADMIN_RULE_KINDS
        # Repair older unclassified records with exact official detail metadata.
        official_code = field(root, "행정규칙종류코드")
        official_type = field(root, "행정규칙종류")
        verified_type = ADMIN_RULE_KINDS.get(
            official_code, official_type if official_type in
            ADMIN_RULE_KINDS.values() else "")
        if verified_type:
            doc["law_type"] = verified_type
            state["documents"][doc["id"]]["law_type"] = verified_type
    from .annexes import enrich_annexes
    after = enrich_annexes(
        root, parse_document(root),
        previous_snapshot=state["versions"].get(doc["id"]))
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
    # Annual standards may be formally issued as a new notice each year.
    # Search the preceding official edition before marking them as a
    # stand-alone enactment with no comparable previous criteria.
    annual_rule=(doc.get("source")=="admrul" and
                 bool(YEAR_TITLE.search(doc.get("title",""))))
    is_new=("제정" in revision and "개정" not in revision)
    if is_new and not annual_rule:
        return dict(base,status="enactment",reason="공식 신규 제정 본문 확보")
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
        if is_new:
            return dict(base,status="enactment",
                        reason="전년도 공식 동일 기준이 확인되지 않은 신규 고시")
        return dict(base, status="history_unavailable" if history_error else
                    "baseline_unavailable",
                    reason=history_error or "이전 공식 개정 이력 미확보")
    # Keep both official versions, but do not treat baseline as a new change.
    if prior["id"] not in state["documents"]:
        state["documents"][prior["id"]] = {**prior, "reference_only": True}
    from .annexes import normalize_legacy_annex_keys
    previous = state["versions"].get(prior["id"])
    missing_pdf = bool(previous and previous.get("attachment_link_count")
                       and (previous.get("status") != "extracted" or
                            previous.get("extraction_schema") != 3))
    if not previous or missing_pdf:
        previous_root = api.detail(prior)
        previous = enrich_annexes(
            previous_root,parse_document(previous_root),
            previous_snapshot=previous)
        state["versions"][prior["id"]] = previous
    else:
        previous = normalize_legacy_annex_keys(previous)
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
    from .coverage import pending_counts
    from .core import ADMIN_RULE_KINDS
    categories = {}
    rule_docs = [d for d in docs.values()
                 if d.get("source")=="admrul" and
                 not d.get("reference_only")]
    for kind in list(ADMIN_RULE_KINDS.values())+["미분류"]:
        matches=[d for d in rule_docs if (
            d.get("law_type", "행정규칙") == kind
            if kind!="미분류" else
            d.get("law_type", "행정규칙") not in ADMIN_RULE_KINDS.values())]
        statuses=Counter(findings.get(d["id"], {}).get("status","queued")
                         for d in matches)
        categories[kind]={
            "indexed":len(matches),
            "changed":sum(bool(findings.get(d["id"], {}).get("changes"))
                          for d in matches),
            "pending":sum(v for k,v in statuses.items()
                          if k not in TERMINAL),
            "unavailable":sum(statuses[k] for k in (
                "body_unavailable","history_unavailable",
                "baseline_unavailable","partial_unresolved"))}
    result["rule_categories"]=categories
    pending = pending_counts(state)
    result["analysis_status"] = {
        "indexed": sum(v["indexed"] for v in pending.values()),
        "checked": sum(v["verified"]+v["partial"] for v in pending.values()),
        "partially_checked": sum(v["partial"] for v in pending.values()),
        "unexamined": sum(v["unexamined"] for v in pending.values()),
        "retryable": sum(v["retryable"] for v in pending.values()),
        "blocked": sum(v["blocked"] for v in pending.values()),
    }
    run = state.get("collection_run", {})
    result["coverage_incomplete"] = ((run["failed_windows"] +
                                    run.get("deferred_streams",0))
         if "failed_windows" in run else
         sum(not x.get("complete", False) for x in state.get("coverage", [])))
    result["official_source_streams"] = run.get("streams", 0)
    result["backfill_window_failures"] = run.get("failed_windows", 0)
    result["deferred_source_streams"] = run.get("deferred_streams", 0)
    return result


def run_once(state: dict, api: LawAPI, today: dt.date, limit: int = 24,
             *, max_seconds: float | None = None,
             collect_sources: bool = True,
             source_budget_seconds: float = 150) -> dict:
    """Process as much verified backlog as fits; always save partial progress.

    The CLI stops before the Actions timeout rather than wasting a long source
    session. Official index refresh remains every six hours while historical
    version comparison is independently scheduled more often.
    """
    started = time.monotonic()
    since = state.get("last_collected_at", "")
    due = True
    if isinstance(api, LawAPI) and since:
        try:
            prior = dt.datetime.fromisoformat(since)
            elapsed = dt.datetime.now(dt.timezone.utc) - prior
            due = (elapsed.total_seconds() >= 6 * 3600 or
                   not state.get("collection_run", {}).get("recent_complete", False) or
                   "admrul|1|3" not in state.get("backfill_end_dates", {}))
        except (TypeError, ValueError):
            due = True
    if collect_sources and due:
        # The source crawl may be slow. It must not consume most of the time
        # reserved for parsing existing unexamined documents.
        source_budget=(max(20, min(
            source_budget_seconds, max_seconds-240))
            if max_seconds is not None else source_budget_seconds)
        collect(api, state, today, max_seconds=source_budget)

    selected = work_queue(state, today, limit)
    analyzed = 0
    source_failures = 0
    for doc in selected:
        # Budget is a safety stop: source API requests have independent network
        # timeouts. Save all results actually completed before job termination.
        if max_seconds is not None and time.monotonic() - started > max_seconds - 70:
            break
        attempt = state.setdefault("attempts", {}).setdefault(doc["id"], {})
        attempt["count"] = int(attempt.get("count", 0)) + 1
        attempt["last_date"] = today.isoformat()
        try:
            state["findings"][doc["id"]] = analyze_one(api, state, doc)
        except Exception as exc:
            source_failures += 1
            state["findings"][doc["id"]] = {
                "event_id": doc["id"], "status": "source_error",
                "changes": [], "excluded": [], "review_candidates": [],
                "reason": type(exc).__name__ + ": " + str(exc)[:160],
            }
        if (doc.get("source") == "admrul" and
            YEAR_TITLE.search(doc.get("title","")) and
            "제정" in doc.get("revision","") and
            state.get("findings",{}).get(doc["id"],{}).get("status")
                in ("compared","partial_compared","enactment",
                    "no_text_change","partial_unresolved")):
            done=state.setdefault("annual_recheck_completed_ids",[])
            if doc["id"] not in done:
                done.append(doc["id"])
        analyzed += 1
    # Additional official citation/program discovery is optional and may never
    # prevent source-comparison results from being persisted.
    remaining = (max_seconds - (time.monotonic()-started)
                 if max_seconds is not None else None)
    if (hasattr(api, "request") and
            (remaining is None or remaining > 65)):
        from .discovery import discover_dependents
        discover_dependents(api, state, limit_events=min(3, max(1, analyzed // 8)))
    remaining = (max_seconds - (time.monotonic()-started)
                 if max_seconds is not None else None)
    if isinstance(api, LawAPI) and (remaining is None or remaining > 55):
        from .alioplus import ALIOPlusClient
        state["program_source_audit"] = ALIOPlusClient().collect(
            state, max_details=15)
    from .coverage import pending_counts
    state["analysis_run"] = {
        "checked_at": utc_now(),
        "selected": len(selected),
        "analyzed": analyzed,
        "failed": source_failures,
        "remaining": sum(v["unexamined"]+v["retryable"]
                         for v in pending_counts(state).values()),
        "budget_exhausted": analyzed < len(selected),
        "collection_requested": bool(collect_sources and due),
        "source_budget_seconds": (
            source_budget_seconds if collect_sources and due else 0),
        "time_seconds": round(time.monotonic()-started, 1),
    }
    # Remove identifiers after analysis, preserving still-unexamined leads.
    processed = {d["id"] for d in selected[:analyzed]}
    if state.get("reconciliation_priority_ids"):
        state["reconciliation_priority_ids"] = [
            x for x in state["reconciliation_priority_ids"] if x not in processed]
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
    # Public-service discovery is deliberately a separate evidence tier.
    # A confirmed service name and statutory citation is a review lead,
    # NOT proof that the agency must already change a program or system.
    from .gov24 import discover_public_service_leads
    from .legal_origin import origin_of
    from .priority import score_and_sort
    for event in events:
        document_id=event.get("source_documents", [""])[0]
        event["origin"]=origin_of(docs.get(document_id,{}),
                                  state.get("versions",{}).get(document_id))
        for change in event.get("changes",[]):
            change["origin_upper_bases"]=event["origin"]["upper_bases"]
    # Search both the changed notice and its directly quoted parent basis,
    # but require a matching previous amount in the official service fields.
    gov24_links = discover_public_service_leads(state, events)
    score_and_sort(events)
    # Institution directory is a factual source index, not an impact finding.
    # Each counter is obtained from retained official records, never examples.
    # A statutory officeholder is not a public institution. This applies
    # independently to the factual directory as well as the impact engine.
    from .events import is_office_title
    directory = {}
    def register_agency(name: str, key: str):
        name = str(name or "").strip()
        if not name or is_office_title(name):
            return
        row = directory.setdefault(name, {
            "agency": name, "alioplus_programs": 0,
            "gov24_services": 0, "official_registry": 0})
        row[key] += 1
    for institution in state.get("official_institutions",{}).values():
        register_agency(institution.get("agency",""),"official_registry")
    for program in state.get("official_programs", {}).values():
        register_agency(program.get("agency", ""), "alioplus_programs")
    for service in state.get("public_services", {}).values():
        register_agency(service.get("agency", ""), "gov24_services")
    agency_directory = sorted(directory.values(), key=lambda row: row["agency"])
    agency_directory_audit = {
        "alioplus_agencies": sum(row["alioplus_programs"] > 0 for row in agency_directory),
        "gov24_agencies": sum(row["gov24_services"] > 0 for row in agency_directory),
        "official_registry_agencies": sum(row["official_registry"] > 0 for row in agency_directory),
    }
    data = {
        "schema": state["schema"],
        "generated_at": state.get("generated_at", ""),
        "configuration": "running" if state.get("generated_at") else
                         "not_run_or_credential_missing",
        "coverage": state.get("coverage", []),
        "quality": quality(state),
        "analysis_run": state.get("analysis_run", {}),
        "collection_run": state.get("collection_run", {}),
        "reconciliation_run": state.get("reconciliation_run", {}),
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
        "public_service_proofs": gov24_links["proofs"],
        "agency_directory": agency_directory,
        "agency_directory_audit": agency_directory_audit,
        "official_institution_audit": state.get("official_institution_audit",{}),
        "gov24_audit": state.get("gov24_audit", {
            "source":"gov24_public_services","status":"not_configured"}),
        "public_services_indexed": len(state.get("public_services", {})),
        "public_service_review_leads": gov24_links["total_candidates"],
        "relationships": edges,
        "cross_document_review_candidates": work_reviews,
        "program_dependencies": program_links,
        "ai_progress": {
            "indexed_documents": len(indexed),
            "source_events": len(events),
            "verified_events": len(events),
            "analyzed_events": sum(bool(e["ai_count"]) for e in events),
            "pending_events": sum(
                bool(e["changes"]) and e["ai_count"] < len(e["changes"])
                for e in events),
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
    if output.resolve() == DATA_FILE.resolve():
        from .web_export import export_site
        export_site(data, output)
    else:
        # Explicit non-production output remains useful to existing research
        # and regression tests; it is never published by GitHub Pages.
        write_json(output, data)
    return data


DEFAULT_LAW_OC = "dori"  # Same public OC fallback as the prior project.


def configured_law_oc() -> str:
    return os.getenv("LAW_OC", "").strip() or DEFAULT_LAW_OC


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("run", "render", "ai", "ai-check", "gov24", "institutions", "migrate", "reconcile"))
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--page-budget", type=int, default=2)
    parser.add_argument("--reconcile-windows",type=int,default=12)
    parser.add_argument("--time-budget", type=float, default=670)
    parser.add_argument("--analysis-only", action="store_true",
                        help="Revisit existing official documents without recrawling index")
    parser.add_argument("--source-budget", type=float, default=150)
    parser.add_argument("--state", type=Path, default=STATE_FILE)
    parser.add_argument("--output", type=Path, default=DATA_FILE)
    args = parser.parse_args(argv)
    state = load_state(args.state)
    if args.mode == "migrate":
        # Offline, non-destructive one-time conversion of a fully verified
        # original state. Subsequent render uses the new state store.
        report = save_shards(args.state, state, SCHEMA)
        recovered = load_state(args.state)
        if recovered != state:
            raise SystemExit("Migration blocked: original state and migrated state differ")
        print("Official state shard migration:", json.dumps(report))
    if args.mode == "reconcile":
        from .reconciliation import reconcile_changed_rules
        credential=configured_law_oc()
        api = LawAPI(credential)
        api.deadline = time.monotonic() + max(30, min(args.time_budget, 600))
        report=reconcile_changed_rules(
            api,state,dt.date.today(),
            max_windows=max(1,min(args.reconcile_windows,60)),
            max_seconds=max(30,min(args.time_budget,600)))
        save_shards(args.state,state,SCHEMA)
        print("Official historical rule reconciliation:",
              json.dumps(report,ensure_ascii=False))
    if args.mode == "run":
        # The previous project's publicly configured official API OC is
        # "dori". It is an OC identifier, not a private API secret.
        # Keep the same working fallback; explicit LAW_OC may override it.
        credential = configured_law_oc()
        run_once(state, LawAPI(credential), dt.date.today(),
                 max(1, min(args.limit, 150)),
                 max_seconds=max(120, min(args.time_budget, 840)),
                 collect_sources=not args.analysis_only,
                 source_budget_seconds=max(30, min(args.source_budget, 300)))
        save_shards(args.state, state, SCHEMA)
    if args.mode == "gov24":
        from .gov24 import collect_gov24
        credential = (os.getenv("GOV24_SERVICE_KEY", "").strip() or
                      os.getenv("DATA_GO_KR_KEY", "").strip())
        audit = collect_gov24(state, credential,
                              pages_per_feed=max(1, min(args.page_budget, 120)))
        save_shards(args.state, state, SCHEMA)
        print("Gov24 public-service collection:",
              json.dumps(audit, ensure_ascii=False))
    if args.mode == "institutions":
        from .agency_registry import collect_institutions
        audit=collect_institutions(state)
        save_shards(args.state,state,SCHEMA)
        print("Official institution directory:",json.dumps(audit,ensure_ascii=False))
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
        save_shards(args.state, state, SCHEMA)
        print("Policy Domino AI:", json.dumps(report, ensure_ascii=False))
    result = render(state, args.output)
    print("Policy Domino Next:", {
        "documents": len(result["documents"]),
        "relationships": len(result["relationships"]),
        "quality": result["quality"]})


if __name__ == "__main__":
    main()
