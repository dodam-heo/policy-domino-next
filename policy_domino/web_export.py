"""Stable, evidence-preserving GitHub Pages projection.

Public index and search metadata are small; one detail is fetched only on
selection. Full source data never becomes one enormous deployable JSON.
The original in-memory payload is validated before this projection.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path

def _encode(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,
                       separators=(",",":"))+"\n").encode("utf-8")

def _save(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes()==data:
        return False
    pending=path.with_name(path.name+".tmp")
    pending.write_bytes(data)
    pending.replace(path)
    return True

def _small_document(doc):
    return {key:doc.get(key,"") for key in (
        "id","source","title","law_type","published_at","effective_date",
        "ministry","url")} | {
        "analysis":{"status":(doc.get("analysis") or {}).get("status","queued")}
    }

def _summary(event):
    highlights={(h.get("document_id"),h.get("article"))
                for h in event.get("highlights",[])}
    featured=next((c for c in event.get("changes",[])
                   if (c.get("document_id"),c.get("article")) in highlights),
                  next(iter(event.get("changes",[])),{}))
    names=sorted({row.get("institution","") for row
                  in event.get("institutional_reviews",[]) if row.get("institution")})
    search=" ".join(str(x) for x in (
        [event.get("title",""),event.get("headline",""),event.get("ministry","")]
        + [m.get("title","") for m in event.get("members",[])]
        + [m.get("kind","") for m in event.get("members",[])]
        + [x.get("category","") for x in event.get("changes",[])]
        + [x.get("article","") for x in event.get("changes",[])]
        + [r.get("program","") for r in event.get("institutional_reviews",[])]
        + [r.get("task","") for r in event.get("institutional_reviews",[])]
        + [s.get("service_name","") for s in event.get("public_service_leads",[])]
        + names))
    selected={key:event.get(key) for key in (
        "id","title","published_at","effective_date","kind",
        "verification","source_count","institution_count","review_count",
        "public_service_lead_count","ai_count","headline","ministry")}
    selected["members"]=[{"title":m.get("title",""),"kind":m.get("kind","")}
                         for m in event.get("members",[])]
    selected["source_documents"]=event.get("source_documents",[])
    selected["list_brief"]=featured.get("brief","")
    selected["agency_names"]=names
    selected["search_text"]=search
    selected["detail_path"]="./details/"+event["id"]+".json"
    return selected

def export_site(data: dict, output: Path) -> dict:
    output=Path(output)
    if output.name!="catalog.json":
        raise ValueError("Production output must be catalog.json")
    dest=output.parent
    details=dest/"details"
    required=set()
    changed=0
    for event in data.get("events",[]):
        identity=str(event.get("id",""))
        if not re.fullmatch(r"event-[a-f0-9]{24}",identity):
            raise ValueError("Unsafe policy event identity: "+identity)
        file=details/(identity+".json")
        required.add(file.name)
        changed+=_save(file,_encode(event))
    if details.exists():
        for file in details.glob("*.json"):
            if file.name not in required:
                file.unlink()
    summary={key:data.get(key) for key in (
        "schema","generated_at","configuration","quality",
        "collection_run","reconciliation_run","ai_progress","ai_status",
        "ai_run","agency_directory","agency_directory_audit",
        "gov24_audit","public_services_indexed","public_service_review_leads",
        "program_discovery_audit","discovery_audit","principles")}
    summary.update({
        "distribution":"split-v1","events":[_summary(e) for e in data["events"]],
        "documents_path":"./sources.json","detail_count":len(required),
    })
    _save(dest/"sources.json",_encode({"schema":data["schema"],
        "documents":[_small_document(d) for d in data.get("documents",[])]}))
    _save(output,_encode(summary))
    # A legacy public payload is intentionally not an output of this system.
    legacy=dest/"data.json"
    if legacy.exists():
        legacy.unlink()
    return {"events":len(required),"updated_details":changed,
            "catalog_bytes":output.stat().st_size,
            "sources_bytes":(dest/"sources.json").stat().st_size}
