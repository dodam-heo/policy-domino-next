"""Unseeded official full-text discovery of potentially affected regulations.

Search results are never treated as proof of a policy effect. The official
retrieved body must contain an exact citation to the changed article.
"""
from __future__ import annotations

from .analysis import extract_references
from .api import field, nodes, parse_record
from .core import SOURCES
from .parser import parse_document


def discover_dependents(api, state: dict, limit_events: int = 3,
                        page_size: int = 40, max_bodies_per_source: int = 8) -> dict:
    ledger = state.setdefault("dependency_discovery", {})
    documents = state.setdefault("documents", {})
    findings = state.setdefault("findings", {})
    versions = state.setdefault("versions", {})
    pending = [
        (eid, item) for eid, item in findings.items()
        if item.get("changes") and eid in documents and
        eid not in ledger
    ]
    pending.sort(key=lambda pair: documents[pair[0]]["published_at"],reverse=True)
    metrics={"events":0, "pages":0, "possible_documents":0,
             "official_bodies_checked":0,"exact_article_references":0,
             "incomplete_queries":0}
    for event_id, finding in pending[:max(0, limit_events)]:
        changed = documents[event_id]
        wanted = {item["article"] for item in finding["changes"]}
        reports = []
        metrics["events"] += 1
        for source in SOURCES:
            report={"source":source,"reported":-1,
                    "searched":0,"verified":0,"complete":False,"error":""}
            try:
                args={"query":changed["title"],"search":2,
                      "display":page_size,"page":1}
                if source != "law":
                    args["nw"]="1"
                root=api.request("lawSearch.do",source,**args)
                total=field(root,"totalCnt")
                if not total.isdigit():
                    raise ValueError("Missing official full-text search count")
                report["reported"]=int(total)
                candidates=[parse_record(x,source) for x in nodes(root,source)]
                candidates=[x for x in candidates if x and x["id"] != event_id]
                report["searched"]=len(candidates)
                metrics["possible_documents"] += len(candidates)
                checked=0
                for doc in candidates[:max_bodies_per_source]:
                    package=versions.get(doc["id"])
                    if not package:
                        package=parse_document(api.detail(doc))
                    checked+=1
                    metrics["official_bodies_checked"]+=1
                    proof=[]
                    for article,clause in package.get("clauses",{}).items():
                        if not clause.get("complete"):
                            continue
                        for ref in extract_references(clause["text"]):
                            if ref["title"] == changed["title"] and ref["article"] in wanted:
                                proof.append((article,ref["article"]))
                    if not proof:
                        # Search-engine matches never enter the final graph.
                        continue
                    report["verified"]+=len(proof)
                    metrics["exact_article_references"]+=len(proof)
                    if doc["id"] not in documents:
                        documents[doc["id"]] = {**doc,"reference_only":True}
                    versions[doc["id"]]=package
                report["complete"]=(report["reported"]<=page_size and
                                    len(candidates)<=max_bodies_per_source)
                if not report["complete"]:
                    metrics["incomplete_queries"]+=1
            except Exception as exc:
                report["error"]=type(exc).__name__+": "+str(exc)[:150]
                metrics["incomplete_queries"]+=1
            reports.append(report)
            metrics["pages"]+=1
        # State reports evidence-finding coverage, never nationwide completeness.
        ledger[event_id]={"queries":reports,
                          "fully_checked":all(x["complete"] for x in reports)}
    state["discovery_metrics"]=metrics
    return metrics
