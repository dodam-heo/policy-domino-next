"""Provenance-based public data contract; no policy- or institution-specific rules."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

from .core import SCHEMA, SOURCES


class ContractError(ValueError):
    """The public result asserts information that is not supported by evidence."""


UNVERIFIED = {
    "queued", "body_unavailable", "history_unavailable", "baseline_unavailable",
    "source_error", "partial_unresolved",
}
ALLOWED = UNVERIFIED | {
    "compared", "partial_compared", "no_text_change", "enactment", "repeal",
}


def official_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        url = urlparse(value)
        return (url.scheme == "https" and url.hostname in
                {"law.go.kr", "www.law.go.kr", "open.law.go.kr"})
    except ValueError:
        return False


def validate_public(payload: dict) -> dict:
    """Reject false change or institutional-action claims before publication.

    A direct legal citation is not, by itself, a proved downstream business
    process, and an issuing ministry is not a demonstrated executing agency.
    """
    errors: list[str] = []

    def verify(ok: bool, path: str, reason: str) -> None:
        if not ok:
            errors.append(path + ": " + reason)

    if not isinstance(payload, dict):
        raise ContractError("Public result must be a JSON object")
    verify(payload.get("schema") == SCHEMA, "schema", "unknown schema")
    for key in ("documents", "relationships", "events"):
        verify(isinstance(payload.get(key), list), key, "must be a list")
    if errors:
        raise ContractError("\n".join(errors))
    docs: dict[str, dict] = {}
    changes_count = 0
    for i, document in enumerate(payload["documents"]):
        loc = f"documents[{i}]"
        if not isinstance(document, dict):
            verify(False, loc, "must be a document")
            continue
        key = document.get("id")
        verify(isinstance(key, str) and bool(key), loc, "missing official event ID")
        verify(key not in docs, loc, "duplicate event ID")
        docs[key] = document
        verify(document.get("source") in SOURCES, loc, "unknown official source")
        verify(bool(document.get("title")) and bool(document.get("published_at")),
               loc, "missing title or publication date")
        verify(official_url(document.get("url")), loc, "missing official URL")
        verify(not document.get("reference_only"), loc, "historical baseline in new event feed")
        analysis = document.get("analysis", {"status": "queued", "changes": []})
        if not isinstance(analysis, dict):
            verify(False, loc + ".analysis", "must be object")
            continue
        status = analysis.get("status", "queued")
        verify(status in ALLOWED, loc + ".status", "unsupported state")
        differences = analysis.get("changes", [])
        if not isinstance(differences, list):
            verify(False, loc + ".changes", "must be a list")
            continue
        if status in UNVERIFIED | {"enactment", "repeal", "no_text_change"}:
            verify(not differences, loc, "unverified/lifecycle item has unsupported before-after edits")
        if differences:
            verify(status in {"compared", "partial_compared"}, loc,
                   "change must have actual before-after comparison")
        for j, change in enumerate(differences):
            pos = loc + f".changes[{j}]"
            if not isinstance(change, dict):
                verify(False, pos, "must be object")
                continue
            verify(bool(change.get("article")), pos, "missing provision")
            verify(isinstance(change.get("before"), str) and
                   isinstance(change.get("after"), str) and
                   change.get("before") != change.get("after"), pos,
                   "missing source before-after difference")
            verify(official_url(change.get("source_url")), pos, "changed source must be official")
            evidence = change.get("evidence") or {}
            verify(isinstance(evidence, dict) and
                   bool(evidence.get("old_body_sha256")) and
                   bool(evidence.get("new_body_sha256")), pos,
                   "both official text hashes are required")
            changes_count += 1
        for j, review in enumerate(analysis.get("direct_actor_reviews", [])):
            pos = loc + f".direct_actor_reviews[{j}]"
            verify(bool(review.get("actor")) and bool(review.get("article")),
                   pos, "missing explicitly named actor or provision")
            verify(review.get("operational_program_verified") is False and
                   review.get("required_action_verified") is False,
                   pos, "statutory actor alone cannot establish business impact")
    for i, edge in enumerate(payload["relationships"]):
        pos = f"relationships[{i}]"
        if not isinstance(edge, dict):
            verify(False, pos, "must be object")
            continue
        verify(edge.get("source_event_id") in docs, pos, "unknown parent event")
        verify(edge.get("relationship") == "verified_exact_article_citation",
               pos, "unsupported relationship evidence")
        verify(bool(edge.get("changed_article")) and
               bool(edge.get("referencing_article")), pos,
               "missing exact legal citation")
        verify(official_url(edge.get("referencing_source_url")), pos,
               "citing regulation needs official source")
        if edge.get("operational_program_verified") or edge.get("required_action_verified"):
            verify(bool(edge.get("verified_agency")) and
                   bool(edge.get("verified_program")) and
                   bool(edge.get("required_review")) and
                   bool(edge.get("official_operational_url")), pos,
                   "institutional action requires independent official program evidence")
    for i, item in enumerate(payload.get("cross_document_review_candidates", [])):
        pos = f"cross_document_review_candidates[{i}]"
        if not isinstance(item, dict):
            verify(False, pos, "must be object")
            continue
        verify(item.get("source_event_id") in docs and
               bool(item.get("actor")) and bool(item.get("target_location")), pos,
               "candidate requires source event, actor and cited clause")
        verify(item.get("operational_program_verified") is False and
               item.get("required_action_verified") is False, pos,
               "candidate may not claim confirmed program/action")
    # Operational dependencies are a separate evidence tier: a public
    # program's exact citation is verified, its required action is NOT.
    from .analysis import extract_references
    from .programs import canonical_url
    for i, impact in enumerate(payload.get("program_dependencies", [])):
        pos = f"program_dependencies[{i}]"
        if not isinstance(impact, dict):
            verify(False, pos, "must be an object")
            continue
        event_id = impact.get("source_event_id")
        changed = impact.get("changed_article")
        parent = docs.get(event_id, {})
        analyses = parent.get("analysis", {}) if isinstance(parent, dict) else {}
        deltas = analyses.get("changes", []) if isinstance(analyses, dict) else []
        verify(bool(parent) and any(
            isinstance(c, dict) and c.get("article") == changed for c in deltas),
            pos, "program linkage requires a verified changed provision")
        verify(bool(impact.get("agency")) and bool(impact.get("program")),
               pos, "missing public institution or actual program")
        verify(bool(canonical_url(impact.get("program_url"))) and
               impact.get("program_url") == canonical_url(impact.get("program_url")),
               pos, "unverified official business source URL")
        proof_hash = impact.get("program_body_sha256", "")
        verify(isinstance(proof_hash, str) and len(proof_hash) == 64 and
               all(ch in "0123456789abcdef" for ch in proof_hash),
               pos, "missing official program text fingerprint")
        verify(impact.get("operational_program_verified") is True and
               impact.get("required_action_verified") is False and
               impact.get("verification") == "verified_program_citation",
               pos, "program citation cannot prove mandatory business actions")
        title = impact.get("referenced_title")
        article = impact.get("referenced_article")
        refs = {(x["title"], x["article"])
                for x in extract_references(str(impact.get("citation_quote", "")))}
        verify((title, article) in refs and bool(article), pos,
               "program quote must explicitly cite the claimed regulation/article")
        if impact.get("path") == "direct":
            verify(title == parent.get("title") and article == changed, pos,
                   "direct link must cite the changed exact article")
            verify(not impact.get("intermediate_url"), pos,
                   "direct evidence must not invent an intermediary")
        elif impact.get("path") == "via_regulation":
            verify(any(e.get("source_event_id") == event_id and
                       e.get("changed_article") == changed and
                       e.get("referencing_title") == title and
                       e.get("referencing_article") == article and
                       e.get("referencing_source_url") == impact.get("intermediate_url")
                       for e in payload["relationships"]), pos,
                   "indirect link requires a proven intermediary legal edge")
        else:
            verify(False, pos, "unsupported program dependency path")
    # LLM analysis is evidence-anchored draft text, never official action.
    for i, document in enumerate(payload["documents"]):
        analysis = document.get("analysis", {}) if isinstance(document, dict) else {}
        ai = analysis.get("ai") if isinstance(analysis, dict) else None
        if ai is None:
            continue
        pos = f"documents[{i}].analysis.ai"
        if not isinstance(ai, dict):
            verify(False, pos, "AI analysis must be an object")
            continue
        verify(ai.get("status") == "generated" and bool(ai.get("model")),
               pos, "AI model invocation not recorded")
        verify(ai.get("required_action_verified") is False,
               pos, "AI cannot confirm mandatory institutional actions")
        fingerprint = ai.get("source_sha256", "")
        verify(isinstance(fingerprint, str) and len(fingerprint) == 64 and
               all(ch in "0123456789abcdef" for ch in fingerprint),
               pos, "source evidence fingerprint required")
        source_changes = {
            ch.get("article"): ch for ch in analysis.get("changes", [])
            if isinstance(ch, dict)
        }
        for j, proposal in enumerate(ai.get("change_reviews", [])):
            location = pos + f".change_reviews[{j}]"
            if not isinstance(proposal, dict):
                verify(False, location, "change review must be object")
                continue
            before_after = source_changes.get(proposal.get("article"), {})
            before_q = proposal.get("before_quote")
            after_q = proposal.get("after_quote")
            verify(bool(before_after) and isinstance(before_q, str) and
                   bool(before_q.strip()) and before_q in before_after.get("before", "") and
                   isinstance(after_q, str) and bool(after_q.strip()) and
                   after_q in before_after.get("after", ""),
                   location, "AI literal before-after evidence not found")
            verify(bool(proposal.get("summary")) and
                   bool(proposal.get("review_question")), location,
                   "AI change review must describe what changed and what to check")
        for j, proposal in enumerate(ai.get("program_reviews", [])):
            location = pos + f".program_reviews[{j}]"
            if not isinstance(proposal, dict):
                verify(False, location, "program review must be object")
                continue
            matched = next((dep for dep in payload.get("program_dependencies", [])
                            if dep.get("source_event_id") == document.get("id") and
                            dep.get("program_id") == proposal.get("program_id") and
                            dep.get("changed_article") == proposal.get("article") and
                            dep.get("agency") == proposal.get("agency")), None)
            snippet = proposal.get("program_quote")
            verify(matched is not None and isinstance(snippet, str) and
                   bool(snippet.strip()) and
                   snippet in (matched or {}).get("citation_quote", ""),
                   location, "AI program quote not found in verified official citation")
            verify(bool(proposal.get("reason")) and
                   bool(proposal.get("review_question")), location,
                   "AI program review lacks concrete rationale or check item")
    # The user-facing unit is an OFFICIAL CHANGE EVENT, not a raw index row.
    # Every combined event and every institutional review is independently
    # checked against current source documents and their verified provenance.
    from .events import ORGANIZATION_RULE, event_identity, _id
    seen_event_ids = set()
    covered_source_ids = set()
    event_actions = 0
    for i, event in enumerate(payload["events"]):
        pos = f"events[{i}]"
        if not isinstance(event, dict):
            verify(False, pos, "event must be an object")
            continue
        event_id = event.get("id")
        verify(bool(event_id) and event_id not in seen_event_ids,
               pos, "missing or repeated policy event identity")
        seen_event_ids.add(event_id)
        source_ids = event.get("source_documents", [])
        if not isinstance(source_ids, list) or not source_ids:
            verify(False, pos, "event must name actual official source documents")
            continue
        verify(len(source_ids) == len(set(source_ids)), pos,
               "duplicate document inside change event")
        source_docs = [docs[x] for x in source_ids if x in docs]
        verify(len(source_docs) == len(source_ids), pos,
               "event points to missing source document")
        if not source_docs:
            continue
        group_keys = {event_identity(d) for d in source_docs}
        verify(len(group_keys) == 1 and
               event.get("identity") in group_keys and
               event_id == _id(event.get("identity", "")), pos,
               "event grouping must use identical official promulgation identifiers")
        verify(len(source_docs) == event.get("source_count") and
               event.get("source_count") == len(event.get("members", [])),
               pos, "event member count does not match official source documents")
        for source_id in source_ids:
            verify(source_id not in covered_source_ids, pos,
                   "one source document cannot belong to multiple policy events")
            covered_source_ids.add(source_id)
        changes_in_event = event.get("changes", [])
        if not isinstance(changes_in_event, list):
            verify(False, pos, "event changes must be a list")
            continue
        by_clause = {
            (document.get("id"), ch.get("article")): ch
            for document in source_docs
            for ch in document.get("analysis", {}).get("changes", [])
            if isinstance(ch, dict)
        }
        verified_event_changes = set()
        for j, change in enumerate(changes_in_event):
            loc = pos + f".changes[{j}]"
            if not isinstance(change, dict):
                verify(False, loc, "event change must be object")
                continue
            clause_key = (change.get("document_id"), change.get("article"))
            actual = by_clause.get(clause_key)
            verify(bool(actual), loc, "change not present in verified official clauses")
            if not actual:
                continue
            verified_event_changes.add(clause_key)
            verify(actual.get("before") == change.get("before") and
                   actual.get("after") == change.get("after") and
                   actual.get("evidence") == change.get("evidence") and
                   actual.get("source_url") == change.get("source_url"),
                   loc, "event changes must preserve exact official before/after and hashes")
        verify(verified_event_changes == set(by_clause), pos,
               "policy event omitted or invented a verified changed provision")

        actions = event.get("institutional_reviews", [])
        if not isinstance(actions, list):
            verify(False, pos, "institutional reviews must be a list")
            continue
        verify(len(actions) == event.get("review_count"), pos,
               "institutional review count mismatch")
        verify(len({x.get("institution") for x in actions
                    if isinstance(x, dict)}) == event.get("institution_count"), pos,
               "institution count mismatch")
        unique_action_ids = set()
        for j, action in enumerate(actions):
            loc = pos + f".institutional_reviews[{j}]"
            if not isinstance(action, dict):
                verify(False, loc, "review must be object")
                continue
            aid = action.get("id")
            verify(aid and aid not in unique_action_ids, loc,
                   "review identity must be nonempty and unique")
            unique_action_ids.add(aid)
            doc_id = action.get("document_id")
            article = action.get("article")
            institution = action.get("institution")
            source = docs.get(doc_id, {})
            change = by_clause.get((doc_id, article))
            verify(bool(source) and bool(change) and bool(institution), loc,
                   "review requires an actual changed clause and target institution")
            if not change:
                continue
            verify(action.get("source_url") == change.get("source_url"), loc,
                   "institutional review source must match changed official clause")
            verify(bool(action.get("task")) and
                   action.get("implementation_status") == "not_verified", loc,
                   "review may not claim verified operational implementation")
            tier = action.get("basis_tier")
            if tier == "direct_regulated_institution":
                match = ORGANIZATION_RULE.fullmatch(source.get("title", "").strip())
                verify(bool(match and match.group(1).strip() == institution) and
                       str(action.get("basis_quote", "")).strip() in
                       (change.get("after") or change.get("before") or ""), loc,
                       "direct subject requires the regulated organization title and literal clause")
                verify(not action.get("program"), loc,
                       "direct legal rule cannot invent a public program")
            elif tier == "explicit_changed_clause":
                actor_reviews = source.get("analysis", {}).get(
                    "direct_actor_reviews", [])
                verify(any(r.get("actor") == institution and
                           r.get("article") == article and
                           r.get("evidence_level") == "changed_clause_explicit_actor"
                           for r in actor_reviews), loc,
                       "direct actor is not verified in the changed source clause")
                verify(not action.get("program"), loc,
                       "actor mention alone cannot prove a public program")
            elif tier == "verified_program_citation":
                evidence = next((
                    dep for dep in payload.get("program_dependencies", [])
                    if dep.get("source_event_id") == doc_id and
                    dep.get("changed_article") == article and
                    dep.get("agency") == institution and
                    dep.get("program_id") == action.get("program_id") and
                    dep.get("program") == action.get("program") and
                    dep.get("program_url") == action.get("program_url") and
                    dep.get("verification") == "verified_program_citation"
                ), None)
                quote = action.get("basis_quote", "")
                verify(bool(evidence) and bool(quote) and
                       quote in (evidence or {}).get("citation_quote", ""),
                       loc, "program review requires independently verified literal citation")
            else:
                verify(False, loc, "unsupported institutional review evidence tier")
            if action.get("ai"):
                ai = action["ai"]
                model = source.get("analysis", {}).get("ai", {})
                if ai.get("work_impact"):
                    original = next((
                        row for row in model.get("institution_reviews", [])
                        if row.get("review_id") == action.get("id") and
                        row.get("agency") == institution and
                        row.get("article") == article
                    ), None)
                    verify(bool(original) and
                           ai.get("work_impact") == original.get("work_impact") and
                           ai.get("question") == original.get("review_question"),
                           loc, "institutional AI draft must match validated actor/quote")
                elif ai.get("reason"):
                    original = next((
                        row for row in model.get("program_reviews", [])
                        if row.get("program_id") == action.get("program_id") and
                        row.get("agency") == institution and
                        row.get("article") == article
                    ), None)
                    verify(bool(original) and
                           ai.get("reason") == original.get("reason") and
                           ai.get("question") == original.get("review_question"),
                           loc, "program AI draft must match source-bound review")
            event_actions += 1

        for j, draft in enumerate(event.get("ai_summaries", [])):
            loc = pos + f".ai_summaries[{j}]"
            if not isinstance(draft, dict):
                verify(False, loc, "AI summary must be object")
                continue
            document = docs.get(draft.get("document_id"), {})
            analysis = document.get("analysis", {})
            original = next((
                x for x in analysis.get("ai", {}).get("change_reviews", [])
                if x.get("article") == draft.get("article")
            ), None)
            verify(bool(original) and
                   draft.get("summary") == (original or {}).get("summary") and
                   draft.get("before_quote") == (original or {}).get("before_quote") and
                   draft.get("after_quote") == (original or {}).get("after_quote"),
                   loc, "AI event summary must reproduce verified source-bound proposal")
        verify(event.get("ai_count") == len(event.get("ai_summaries", [])), pos,
               "AI summary count mismatch")

    expected_covered = {
        d["id"] for d in payload["documents"]
        if (d.get("analysis", {}).get("status") in {"enactment", "repeal"} or
            (d.get("analysis", {}).get("status") in
             {"compared", "partial_compared"} and
             d.get("analysis", {}).get("changes")))
    }
    verify(covered_source_ids == expected_covered, "events",
           "officially changed source documents must form exactly one policy event")

    for key in ("manual_institutions", "inferred_programs_count_as_confirmed",
                "internal_compliance_status_known"):
        verify(payload.get("principles", {}).get(key) is False, "principles." + key,
               "unsupported impacts must never be declared verified")
    if errors:
        raise ContractError("\n".join(errors[:25]) +
                            (f"\n... {len(errors)-25} more" if len(errors)>25 else ""))
    return {
        "source_events": len(docs),
        "changed_provisions": changes_count,
        "confirmed_direct_legal_references": len(payload["relationships"]),
        "verified_policy_events": len(payload["events"]),
        "source_bound_institutional_reviews": event_actions,
    }


def main() -> None:
    path = Path(sys.argv[1])
    print("Evidence contract passed:", validate_public(
        json.loads(path.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
