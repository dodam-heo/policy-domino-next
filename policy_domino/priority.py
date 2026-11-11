"""Classify impact from the *edited clause* and verified institutional tasks.

A title, an unmodified number, a citing agency, or a directory entry is
never by itself evidence of a high-impact policy change.
"""
from __future__ import annotations
import re
from .meaning import explain, is_placeholder_clause

DIRECT_TIERS = frozenset({
    "direct_regulated_institution", "explicit_changed_clause",
    "verified_program_citation",
})
CRITERION = re.compile(
    r"급여|소득|보장|수급|지원|지급|보조|보험료|부담금|수수료|"
    r"세율|과세|납부|징수|요율|자격|선정|대상|요건|최저임금|"
    r"감면|면제|공제|권리|의무|허가|기준금액|기준액")
AMOUNT = re.compile(
    r"(?<!\d)\d[\d,.]*\s*(?:억\s*원|만원|천원|원|%|퍼센트|배)")
NATIONWIDE = re.compile(
    r"전국|전\s*국민|국민\s*(?:전체|공통)|기준\s*중위소득|"
    r"최저임금|기초생활보장|(?:생계|의료|주거|교육)급여|"
    r"국민건강보험|국민연금|공통\s*(?:지급|선정|적용|기준)")
ELIGIBILITY = re.compile(
    r"지원대상|선정기준|수급자격|수급대상|자격요건|"
    r"지원요건|적용대상|면제대상|지급대상|입주자격|"
    r"가입대상|납부의무|수급요건")
INTERNAL = re.compile(r"직제|정원|조직|부서|업무분장|인사발령|직급")
DRAFT = re.compile(r"입법예고|행정예고|(?:제정|개정|고시)안(?:$|\s)")
RENDERED_DIGITS = re.compile(r"\d[\d,.]*")


def _meaning(change):
    return change.get("meaning") or explain(str(change.get("before", "")),
                                             str(change.get("after", "")))


def _real_change(change):
    old, new = str(change.get("before", "")), str(change.get("after", ""))
    if not old.strip() or not new.strip() or old == new:
        return False
    m = _meaning(change)
    return not (m.get("editorial") or m.get("source_check_required")
                or m.get("change_kind") in ("editorial", "citation", "source_check")
                or is_placeholder_clause(old) or is_placeholder_clause(new))


def _changed_windows(change):
    """Only compare the text surrounding the actual modification."""
    for window in _meaning(change).get("focus", []):
        a, b = window.get("before", {}), window.get("after", {})
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        def snippet(data):
            return (str(data.get("prefix", ""))[-110:]
                    + str(data.get("changed", ""))
                    + str(data.get("suffix", ""))[:110])
        yield snippet(a), snippet(b)


def _material_standard(change):
    if not _real_change(change):
        return False
    old, new = str(change.get("before", "")), str(change.get("after", ""))
    article = str(change.get("article", ""))
    # Structured numeric tables have source-verified section/row identities.
    if (article.startswith("표 ") and CRITERION.search(article)
            and RENDERED_DIGITS.fullmatch(old.strip())
            and RENDERED_DIGITS.fullmatch(new.strip())
            and old.strip() != new.strip()):
        return True
    for before, after in _changed_windows(change):
        local = before + " " + after
        # A title-wide keyword cannot make an unrelated number significant.
        if not CRITERION.search(local):
            continue
        x, y = AMOUNT.findall(before), AMOUNT.findall(after)
        if x and y and x != y:
            return True
        m = _meaning(change)
        if (m.get("label") == "대상·자격 기준" and ELIGIBILITY.search(local)
                and re.sub(r"\s+", "", before) != re.sub(r"\s+", "", after)):
            return True
    return False


def assess_impact(event):
    changes = [c for c in event.get("changes", []) if _real_change(c)]
    changed_ids = {(c.get("document_id"), c.get("article")) for c in changes}
    agencies = set()
    for review in event.get("institutional_reviews", []):
        if review.get("basis_tier") not in DIRECT_TIERS or not review.get("institution"):
            continue
        if (review.get("document_id") or review.get("article")) and (
                review.get("document_id"), review.get("article")) not in changed_ids:
            continue
        agencies.add(str(review["institution"]).strip())
    members = event.get("members") or []
    central = len(members) == 1 and members[0].get("source") in ("law", "admrul")
    title = str(event.get("title") or (members[0].get("title") if members else "") or "")
    nationwide = central and not DRAFT.search(title) and not INTERNAL.search(title) and any(
        _material_standard(c) and (
            members[0]["source"] == "law" or
            bool(NATIONWIDE.search(title + " " + str(c.get("article", "")) +
                                   " " + str(c.get("before", ""))[:220] +
                                   " " + str(c.get("after", ""))[:220]))
        )
        for c in changes)
    five = bool(changes) and len(agencies) >= 5
    high = five or nationwide
    return {
        "impact_level": "high" if high else "normal" if changes else "pending",
        "impact_high_basis": (
            "변경된 업무가 연결된 기관 5곳 이상" if five else
            "전국 공통 금액·자격 기준의 실제 변경" if nationwide else ""),
        "verified_institution_count_for_impact": len(agencies),
        "impact_assessment_version": "actual-changed-criterion-and-agency-v3",
    }


def score_and_sort(events):
    for event in events:
        event.update(assess_impact(event))
        event.pop("impact_score", None)
        event.pop("impact_reasons", None)
    events.sort(key=lambda e: (
        e.get("impact_level") == "high",
        e.get("impact_level") == "normal",
        str(e.get("published_at", "")), str(e.get("id", ""))), reverse=True)
