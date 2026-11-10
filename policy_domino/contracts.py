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
    for key in ("documents", "relationships"):
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
    }


def main() -> None:
    path = Path(sys.argv[1])
    print("Evidence contract passed:", validate_public(
        json.loads(path.read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
