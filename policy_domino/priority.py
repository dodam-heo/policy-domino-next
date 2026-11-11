"""Impact importance is based on substantive public-policy and public-workflow changes.

An unrelated amount, a rule that merely cites the law, an issuer or a document
title is insufficient to claim a large downstream public-sector impact.
"""
from __future__ import annotations

import re
from .meaning import explain, is_placeholder_clause

DIRECT_TIERS = frozenset({
    "direct_regulated_institution",
    "explicit_changed_clause",
    "verified_program_citation",
})
PUBLIC_WORK_TIERS = frozenset({
    "explicit_changed_clause",
    "verified_program_citation",
})
BENEFIT_SCOPE = re.compile(
    r"급여|지원금|보조금|연금|기준\s*중위소득|최저임금|"
    r"최저보장|생활보장|수급|선정기준|장학금|보험료|"
    r"주거\s*지원|소득기준|소득\s*인정액")
FINANCIAL_CRITERION = re.compile(
    r"급여|소득|보장|수급|지원|지급|보조|보험료|부담금|"
    r"기준액|기준\s*금액|연금|임금|요율|금액|가구")
ELIGIBILITY = re.compile(
    r"선정기준|수급자격|수급대상|자격요건|"
    r"지원요건|적용대상|면제대상|지급대상|입주자격")
DRAFT = re.compile(r"입법예고|행정예고|(?:제정|개정|고시)안(?:$|\s)")
AMOUNT = re.compile(
    r"(?<!\d)\d[\d,.]*\s*(?:억\s*원|만원|천원|원|%|퍼센트|배)")
CELL_AMOUNT = re.compile(r"\d[\d,.]*")
# Changed administrative channel or mandatory procedure; not generic words
# from unchanged titles, unchanged paragraphs or merely cited institutions.
CHANNEL = re.compile(
    r"일간신문|신문|홈페이지|웹사이트|인터넷|정보통신망|전자문서|"
    r"온라인|우편|방문|서면|관보|전자우편|전자적|게시|공보")
PROCEDURE = re.compile(
    r"공고|공표|고지|통지|공개|안내|게시|신청|접수|신고|제출|보고")
LEGAL_EFFECT = re.compile(
    r"해야\s*한다|하여야\s*한다|할\s*수\s*없다|"
    r"하지\s*못한다|의무|금지|반드시|"
    r"허가|승인|취소|정지|면제|제재")


def _meaning(change):
    return change.get("meaning") or explain(
        str(change.get("before", "")), str(change.get("after", "")))


def _real_change(change):
    old, new = str(change.get("before", "")), str(change.get("after", ""))
    if not old.strip() or not new.strip() or old == new:
        return False
    m = _meaning(change)
    return not (m.get("editorial") or m.get("source_check_required")
                or m.get("change_kind") in ("editorial", "citation", "source_check")
                or is_placeholder_clause(old) or is_placeholder_clause(new))


def _changed_windows(change):
    """Keep changed tokens separate from nearby unchanged source context."""
    for item in _meaning(change).get("focus", []):
        before, after = item.get("before", {}), item.get("after", {})
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        x = str(before.get("changed", "")).strip()
        y = str(after.get("changed", "")).strip()
        if x == y:
            continue
        left = str(before.get("prefix", ""))[-120:]
        right = str(after.get("suffix", ""))[:100]
        yield x, y, left + " " + x + " " + right, left + " " + y + " " + right


def _public_benefit_change(change):
    """Substantive national benefit/eligibility change, not an arbitrary sum."""
    if not _real_change(change):
        return False
    old, new = str(change.get("before", "")), str(change.get("after", ""))
    article = str(change.get("article", ""))
    if (article.startswith("표 ") and FINANCIAL_CRITERION.search(article)
            and CELL_AMOUNT.fullmatch(old.strip())
            and CELL_AMOUNT.fullmatch(new.strip())
            and old.strip() != new.strip()):
        return True
    for x, y, old_local, new_local in _changed_windows(change):
        if not FINANCIAL_CRITERION.search(old_local + " " + new_local):
            continue
        old_amounts, new_amounts = AMOUNT.findall(x), AMOUNT.findall(y)
        if old_amounts and new_amounts and old_amounts != new_amounts:
            return True
        # Exact edited digits followed by a literal monetary unit.
        for item in _meaning(change).get("focus", []):
            a,b=item.get("before",{}),item.get("after",{})
            if (str(a.get("changed","")).strip()==x
                    and str(b.get("changed","")).strip()==y
                    and CELL_AMOUNT.fullmatch(x) and CELL_AMOUNT.fullmatch(y)
                    and x!=y and re.match(
                        r"^\s*(?:억\s*원|만원|천원|원|%|퍼센트)",
                        str(b.get("suffix","")))):
                return True
        if (_meaning(change).get("label")=="대상·자격 기준"
                and ELIGIBILITY.search(old_local + " " + new_local)
                and x and y and not CELL_AMOUNT.fullmatch(x)):
            return True
    return False


def _public_procedure_change(change):
    """A specific governmental process/channel changed in the literal edit."""
    if not _real_change(change):
        return False
    for x,y,old_local,new_local in _changed_windows(change):
        edits=x+" "+y
        contexts=old_local+" "+new_local
        if not PROCEDURE.search(contexts):
            continue
        if CHANNEL.search(edits):
            return True
        # An actual mandatory procedural rule, not just two equivalent
        # expressions like "공고하여야 한다" -> "공고해야 한다".
        if (LEGAL_EFFECT.search(edits)
                and not re.sub(r"하여야", "해야", x).strip()
                    == re.sub(r"하여야", "해야", y).strip()
                and (PROCEDURE.search(edits) or
                     ELIGIBILITY.search(edits))):
            return True
    return False


def _direct_reviews(event, changes):
    changed = {(c.get("document_id"), c.get("article")) for c in changes}
    reviews = []
    for review in event.get("institutional_reviews", []):
        if (review.get("basis_tier") not in DIRECT_TIERS
                or not review.get("institution")):
            continue
        key=(review.get("document_id"),review.get("article"))
        # A source-specific review must cite a changed clause.
        if (key!=(None,None) and key not in changed):
            continue
        reviews.append(review)
    return reviews


def assess_impact(event):
    changes=[c for c in event.get("changes", []) if _real_change(c)]
    linked=_direct_reviews(event, changes)
    agencies={str(r["institution"]).strip() for r in linked}
    five=bool(changes) and len(agencies)>=5

    members=event.get("members") or []
    title=str(event.get("title") or (members[0].get("title") if members else "") or (changes[0].get("document_title") if changes else "") or "")
    national_benefit=(
        len(members)==1 and members[0].get("source") in ("law","admrul")
        and not DRAFT.search(title)
        and bool(BENEFIT_SCOPE.search(title))
        and any(_public_benefit_change(c) for c in changes)
    )
    public_work=any(
        r.get("basis_tier") in PUBLIC_WORK_TIERS and
        any((not c.get("document_id") or c.get("document_id")==r.get("document_id"))
            and (not c.get("article") or c.get("article")==r.get("article"))
            and _public_procedure_change(c) for c in changes)
        for r in linked)
    program_benefit=any(
        r.get("basis_tier")=="verified_program_citation" and
        any((not c.get("document_id") or c.get("document_id")==r.get("document_id"))
            and (not c.get("article") or c.get("article")==r.get("article"))
            and _public_benefit_change(c) for c in changes)
        for r in linked)

    high=five or national_benefit or public_work or program_benefit
    reason=("변경 조문에 직접 연결된 기관 5곳 이상" if five else
            "공공기관의 업무 절차 변경" if public_work else
            "공공사업의 지급·자격 기준 변경" if program_benefit else
            "전국적인 급여·지원 기준 변경" if national_benefit else "")
    return {
        "impact_level": "high" if high else "normal" if changes else "pending",
        "impact_high_basis": reason,
        "verified_institution_count_for_impact": len(agencies),
        "impact_assessment_version": "public-workflow-and-direct-impact-v4",
    }


def score_and_sort(events):
    for event in events:
        event.update(assess_impact(event))
        event.pop("impact_score", None)
        event.pop("impact_reasons", None)
    events.sort(key=lambda e: (
        e.get("impact_level") == "high",
        e.get("impact_level") == "normal",
        str(e.get("published_at", "")),
        e.get("verified_institution_count_for_impact", 0),
        str(e.get("id", ""))), reverse=True)
