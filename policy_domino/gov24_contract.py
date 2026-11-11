"""Gov24 public service evidence and independent legal-basis verification."""
from __future__ import annotations

import re

from .gov24 import CATALOG, service_change_basis, criteria_to_review


def validate_public_service_candidates(payload: dict) -> list[str]:
    errors: list[str] = []
    proofs = payload.get("public_service_proofs", {})
    if not isinstance(proofs, dict):
        return ["public_service_proofs: expected verified source map"]
    events = payload.get("events", [])
    displayed = 0
    for i, event in enumerate(events):
        leads = event.get("public_service_leads", [])
        if not isinstance(leads, list):
            errors.append(f"events[{i}].public_service_leads must be a list")
            continue
        if event.get("public_service_lead_count", 0) < len(leads):
            errors.append(f"events[{i}] candidate count too small")
        changes = {(x.get("document_id"), x.get("article")): x
                   for x in event.get("changes", [])}
        seen = set()
        for j, lead in enumerate(leads):
            loc = f"events[{i}].public_service_leads[{j}]"
            displayed += 1
            if not isinstance(lead, dict):
                errors.append(loc+": not a source-backed object")
                continue
            key = (lead.get("service_id"), lead.get("document_id"),
                   lead.get("article"))
            if key in seen:
                errors.append(loc+": duplicate candidate")
            seen.add(key)
            proof = proofs.get(lead.get("service_id"))
            if not proof:
                errors.append(loc+": missing official Gov24 service record")
                continue
            change = changes.get((lead.get("document_id"),lead.get("article")))
            if not change or change.get("document_title") != lead.get("law_title"):
                errors.append(loc+": law or changed-article identity mismatch")
                continue
            if (lead.get("agency") != proof.get("agency") or
                lead.get("service_name") != proof.get("service_name") or
                lead.get("source_url") != CATALOG or
                proof.get("source") != "gov24" or
                lead.get("verification") != "candidate_not_confirmed"):
                errors.append(loc+": unsupported agency, service or implementation claim")
            evidence = service_change_basis(proof, change)
            if evidence != (lead.get("match_tier"),lead.get("basis_quote")):
                errors.append(loc+": legal basis is not the original public service citation")
            targets=lead.get("review_targets", [])
            if not isinstance(targets, list) or not targets or len(targets)>3:
                errors.append(loc+": missing or oversized official service review targets")
            elif targets != criteria_to_review(proof,change,lead.get("match_tier","")):
                errors.append(loc+": service review target differs from official service and changed clause")
            found = lead.get("old_value_seen_in_service", [])
            if not isinstance(found, list) or len(found)>3:
                errors.append(loc+": numeric candidate must be a bounded list")
                continue
            combined = " ".join(proof.get("fields", {}).get(field, "") for
                                field in ("선정기준","지원내용","지원대상"))
            expected_old=list(dict.fromkeys(
                t["old_value"] for t in targets
                if isinstance(t,dict) and t.get("old_value")))[:3]
            if found != expected_old:
                errors.append(loc+": old service criteria must follow verified official field targets")
            for value in found:
                if not isinstance(value, str) or value not in combined or (
                    value not in change.get("before","")):
                    errors.append(loc+": unproven previous numeric criterion")
    if displayed != sum(len(ev.get("public_service_leads",[]))
                        for ev in events):
        errors.append("Gov24 candidate display count inconsistent")
    if not isinstance(payload.get("public_services_indexed", 0), int):
        errors.append("Gov24 indexed count must be integer")
    if not isinstance(payload.get("public_service_review_leads", 0), int):
        errors.append("Gov24 candidate count must be integer")
    return errors
