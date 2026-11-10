"""Official policy-event projection: CHANGE -> SOURCE-BOUND IMPACT -> REVIEW.

The collection ledger stores *documents*. This module constructs independently
auditable policy *events* from the current official findings. It never loads
legacy outputs, registers specific government bodies, or infers a program from
a coincidentally similar title.

Every public change event is scoped to ONE amended legal instrument.
A shared promulgation number may identify an omnibus issuing event but never
licenses cross-law mixing of changed clauses, actors, or public-service effects.
Legal citations and official program evidence form downstream links only from
the exact changed source document and its own amended article.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import re

from .core import clean
from .meaning import explain, event_headline, highlight_changes

# A regulation that directly governs the organization named in its *title*.
# This is a generic structural pattern, not a list of known agencies.
ORGANIZATION_RULE = re.compile(
    r"^(.+?)(?:와|과) 그 소속기관 직제(?: 시행규칙)?$"
)
VALID_COMPARISONS = {"compared", "partial_compared"}
VERIFIED_LIFECYCLE = {"enactment", "repeal"}


def event_identity(document: dict) -> str:
    """One change event per official amended document, never per proclamation.

    A number shared by different decrees is provenance metadata, not a
    legal basis for mixing their changed articles or responsible institutions.
    Keep stable source/version identity so separately amended instruments
    remain distinct even under an official omnibus amendment.
    """
    return "document|" + str(document["id"])

def _id(key: str) -> str:
    return "event-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _review_task(kind: str, place: str) -> str:
    """Operational checkpoint from what *actually* changed; no legal rewrite."""
    actions = {
        "금액·비율": "지급·산정 금액과 계산식",
        "선정·자격": "대상자 선정과 자격 심사 조건",
        "기한·절차": "접수·처리 일정과 업무 절차",
        "서식·증빙": "신청 서식과 제출·증빙 항목",
        "허가·감독": "심사·허가·검사 기준",
        "조직·정원": "조직별 역할·정원·업무분장 기준",
        "금액·수치 기준": "금액·비율·수치 적용 기준",
        "인원·기간·수치 기준": "인원·기간 등 적용 수치",
        "대상·자격 기준": "대상자 선정·자격 심사 조건",
        "공고·공표 방식": "공고·공표 매체와 안내 방식",
        "신청·처리 절차": "접수·신청·처리 절차",
        "조직·직무 기준": "조직별 담당 업무·정원 기준",
        "서식·증빙 기준": "신청서·증빙 서류 기준",
        "인허가·감독 기준": "인허가·감독 처리 기준",
        "인용 법령·조문": "업무 기준에서 인용하는 법령·조문",
        "띄어쓰기·표기 정비": "관련 규정 안내 문구",
    }
    work = actions.get(kind, "해당 조문의 업무 적용 기준")
    return place + "의 " + work + " 변경 여부를 신구 조문과 대조"


def _change_brief(change: dict) -> str:
    """An evidence-derived *description*, never a broken character window."""
    meaning = explain(change.get("before", ""), change.get("after", ""))
    return meaning["description"]


def _main_title(rows: list[dict]) -> str:
    """Exact official document title; never a representative of other laws."""
    if len(rows) != 1:
        raise ValueError("Policy events must contain exactly one changed document")
    return rows[0]["title"]

def _direct_subject(document: dict) -> str:
    matched = ORGANIZATION_RULE.fullmatch(clean(document.get("title", "")))
    return matched.group(1).strip() if matched else ""


def _review_row(document: dict, change: dict, institution: str, *,
                tier: str, source_quote: str, program: str = "",
                program_id: str = "", program_url: str = "",
                linking_regulation: str = "", ai: dict | None = None,
                related_rule_url: str = "", related_rule_article: str = "") -> dict:
    article = change["article"]
    place = (program + " 운영 기준") if program else (institution + " 담당 업무")
    source_category = change.get("category", "")
    category = source_category if source_category in {
        "금액·비율", "선정·자격", "기한·절차", "서식·증빙",
        "허가·감독", "조직·정원",
    } else explain(change.get("before", ""), change.get("after", ""))["label"]
    identity = [document["id"], article, institution, program_id, tier]
    if tier == "verified_official_rule_citation":
        identity += [linking_regulation, related_rule_article, related_rule_url]
    result = {
        "id": _id("|".join(identity)),
        "document_id": document["id"],
        "document_title": document["title"],
        "institution": institution,
        "program": program,
        "program_id": program_id,
        "article": article,
        "category": category,
        "change": _change_brief(change),
        "task": _review_task(category, place),
        "basis_tier": tier,
        "basis_quote": source_quote[:450],
        "source_url": change.get("source_url", document.get("url", "")),
        "program_url": program_url,
        "linking_regulation": linking_regulation,
        "related_rule_url": related_rule_url,
        "related_rule_article": related_rule_article,
        # Source text establishes a review target, NOT a changed internal system.
        "implementation_status": "not_verified",
    }
    if ai:
        result["ai"] = ai
    return result


def build_events(documents: dict, findings: dict, *,
                 relationships: list[dict] | None = None,
                 program_dependencies: list[dict] | None = None,
                 cross_document_reviews: list[dict] | None = None,
                 ai_reviews: dict | None = None) -> list[dict]:
    """Create one canonical, current-source-only event list.

    Unexamined index entries are *not policy change events*.
    Rows reference exact source documents and changed articles so every
    downstream review can be independently checked before publication.
    """
    relationships = relationships or []
    program_dependencies = program_dependencies or []
    cross_document_reviews = cross_document_reviews or []
    ai_reviews = ai_reviews or {}
    groups: dict[str, list[dict]] = defaultdict(list)

    for doc in documents.values():
        if doc.get("reference_only") or not doc.get("id"):
            continue
        finding = findings.get(doc["id"], {})
        status = finding.get("status")
        if status in VERIFIED_LIFECYCLE or (
                status in VALID_COMPARISONS and finding.get("changes")):
            groups[event_identity(doc)].append(doc)

    deps: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for dep in program_dependencies:
        if (dep.get("verification") == "verified_program_citation"
                and dep.get("operational_program_verified") is True
                and dep.get("required_action_verified") is False):
            deps[(dep.get("source_event_id"), dep.get("changed_article"))].append(dep)

    citing: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in relationships:
        if edge.get("relationship") == "verified_exact_article_citation":
            citing[(edge.get("source_event_id"), edge.get("changed_article"))].append(edge)

    # Specific operational subjects may be located in an exact changed clause,
    # even if the issuing ministry is a different organization.
    cross: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in cross_document_reviews:
        if row.get("verification") == "exact_changed_article_cited_with_named_actor":
            cross[(row.get("source_event_id"), row.get("changed_article"))].append(row)

    events = []
    for key, members in groups.items():
        members = sorted(members, key=lambda x: x["id"])
        if len(members) != 1:
            raise ValueError("Cross-document change-event grouping is forbidden")
        entries = []
        tasks = []
        ai_summaries = []
        linked = []
        seen_actions = set()
        for doc in members:
            doc_id = doc["id"]
            analysis = findings.get(doc_id, {})
            model = ai_reviews.get(doc_id) or {}
            ai_change = {
                x.get("article"): x
                for x in model.get("change_reviews", [])
                if isinstance(x, dict)
            } if model.get("status") == "generated" else {}
            for ch in analysis.get("changes", []):
                if not ch.get("article") or ch.get("before") == ch.get("after"):
                    continue
                article = ch["article"]
                meaning = explain(ch["before"], ch["after"])
                entries.append({
                    "document_id": doc_id,
                    "document_title": doc["title"],
                    "article": article,
                    "category": meaning["label"],
                    "brief": meaning["description"],
                    "meaning": meaning,
                    "before": ch["before"],
                    "after": ch["after"],
                    "actual_edits": ch.get("actual_edits", []),
                    "source_url": ch["source_url"],
                    "evidence": ch.get("evidence", {}),
                })
                if article in ai_change:
                    item = ai_change[article]
                    ai_summaries.append({
                        "document_id": doc_id, "article": article,
                        "summary": item.get("summary", ""),
                        "question": item.get("review_question", ""),
                        "before_quote": item.get("before_quote", ""),
                        "after_quote": item.get("after_quote", ""),
                    })

                candidates = []
                owner = _direct_subject(doc)
                if owner:
                    candidates.append(_review_row(
                        doc, ch, owner, tier="direct_regulated_institution",
                        source_quote=ch["after"] or ch["before"]))
                for actor in analysis.get("direct_actor_reviews", []):
                    if (actor.get("article") == article
                            and actor.get("evidence_level") ==
                            "changed_clause_explicit_actor"
                            and actor.get("actor")):
                        candidates.append(_review_row(
                            doc, ch, actor["actor"], tier="explicit_changed_clause",
                            source_quote=ch["after"] or ch["before"]))

                for dep in deps[(doc_id, article)]:
                    program_review = next((
                        x for x in model.get("program_reviews", [])
                        if x.get("program_id") == dep.get("program_id")
                        and x.get("article") == article
                        and x.get("agency") == dep.get("agency")
                    ), None)
                    candidates.append(_review_row(
                        doc, ch, dep["agency"], tier="verified_program_citation",
                        source_quote=dep["citation_quote"],
                        program=dep["program"],
                        program_id=dep["program_id"],
                        program_url=dep["program_url"],
                        linking_regulation=dep.get("referenced_title", ""),
                        ai=({
                            "reason": program_review.get("reason", ""),
                            "question": program_review.get("review_question", ""),
                        } if program_review else None),
                    ))

                for edge in citing[(doc_id, article)]:
                    # Exact changed-article citation in an OFFICIAL regulation
                    # makes its issuing public institution a traceable *review
                    # lead*, not a presumed implementation duty. Both the
                    # changed clause and citing clause must have legal evidence.
                    issuer_id = edge.get("referencing_document_id", "")
                    issuer_doc = documents.get(issuer_id, {})
                    issuer = issuer_doc.get("ministry", "")
                    if (issuer_doc.get("source") in ("law", "admrul", "ordin")
                            and issuer and issuer == edge.get("publishing_agency")
                            and edge.get("referencing_source_url")
                            and edge.get("reference_quote")
                            and edge.get("referencing_article")):
                        review = _review_row(
                            doc, ch, issuer,
                            tier="verified_official_rule_citation",
                            source_quote=edge["reference_quote"],
                            linking_regulation=edge["referencing_title"],
                            related_rule_url=edge["referencing_source_url"],
                            related_rule_article=edge["referencing_article"],
                        )
                        review["task"] = (
                            edge["referencing_title"] + " " +
                            edge["referencing_article"] +
                            "에서 인용하는 " + doc["title"] + " " +
                            article + "의 변경 적용 여부 검토")
                        candidates.append(review)
                    linked.append({
                        "document_id": doc_id, "changed_article": article,
                        "title": edge.get("referencing_title", ""),
                        "article": edge.get("referencing_article", ""),
                        "quote": edge.get("reference_quote", ""),
                        "url": edge.get("referencing_source_url", ""),
                        "relationship": "verified_exact_article_citation",
                    })
                for row in cross[(doc_id, article)]:
                    # A cited actor is an investigation lead unless its actual
                    # changed responsibility is verified in a source clause.
                    linked.append({
                        "document_id": doc_id,
                        "changed_article": article,
                        "title": row.get("work_regulation", ""),
                        "article": row.get("target_location", ""),
                        "quote": row.get("citing_quote", ""),
                        "url": row.get("source_url", ""),
                        "actor_lead": row.get("actor", ""),
                        "relationship": "actor_in_referencing_regulation",
                    })
                verified_ai = {
                    item["review_id"]: item for item in model.get(
                        "institution_reviews", [])
                    if isinstance(item, dict) and item.get("review_id")
                }
                for item in candidates:
                    # Server-side AI validation has already checked that the
                    # exact review ID, actor, article and quote match evidence.
                    addition = verified_ai.get(item["id"])
                    if addition:
                        item["ai"] = {
                            **(item.get("ai") or {}),
                            "work_impact": addition["work_impact"],
                            "question": addition["review_question"],
                        }
                    if item["id"] not in seen_actions:
                        seen_actions.add(item["id"])
                        tasks.append(item)

        if not entries and not any(findings[m["id"]].get("status") in
                                   VERIFIED_LIFECYCLE for m in members):
            continue
        date = max(m.get("published_at", "") for m in members)
        kind = "amended" if entries else (
            "new" if any(findings[m["id"]].get("status") == "enactment"
                         for m in members) else "repealed")
        title = _main_title(members)
        agencies = sorted({x["institution"] for x in tasks})
        headline = event_headline(entries) if entries else (
                    "신규 제정 확인" if kind == "new" else "공식 폐지 확인")
        # Distinguish verified scope from a claim of completed business change.
        status = ("partial" if any(
            findings[m["id"]].get("status") == "partial_compared"
            for m in members) else "verified")
        event = {
            "id": _id(key),
            "identity": key,
            "title": title,
            "published_at": date,
            "effective_date": min(
                (m["effective_date"] for m in members
                 if m.get("effective_date")), default=""),
            "kind": kind,
            "verification": status,
            "source_count": len(members),
            "source_documents": [m["id"] for m in members],
            "members": [{
                "id": m["id"], "title": m["title"],
                "kind": m.get("law_type", m.get("kind", "")),
                "url": m["url"], "published_at": m.get("published_at"),
            } for m in members],
            "ministry": " · ".join(sorted({
                m["ministry"] for m in members if m.get("ministry")
            })[:3]),
            "headline": headline,
            "changes": sorted(entries, key=lambda x: (
                x["document_title"], x["article"])),
            "highlights": [{
                "document_id": ch["document_id"],
                "article": ch["article"],
            } for ch in highlight_changes(
                entries, institution_reviews=tasks, ai_summaries=ai_summaries)],
            "institutional_reviews": sorted(tasks, key=lambda x: (
                x["institution"], x["program"], x["document_title"], x["article"])),
            "institution_count": len(agencies),
            "review_count": len(tasks),
            "dependent_rules": sorted({
                (x["document_id"], x["changed_article"], x["title"],
                 x["article"], x["url"]): x for x in linked
            }.values(), key=lambda x: (x["title"], x["article"])),
            "ai_summaries": ai_summaries,
            "ai_count": len(ai_summaries),
        }
        events.append(event)
    events.sort(key=lambda e: (
        e["published_at"], e["institution_count"], e["source_count"], e["id"]),
        reverse=True)
    return events
