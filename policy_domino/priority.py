"""Evidence-led impact classification for NEXT, independent from numeric scores."""
from __future__ import annotations
import re
from .meaning import explain, is_placeholder_clause

TIERS = {"direct_regulated_institution", "explicit_changed_clause",
         "verified_official_rule_citation", "verified_program_citation"}
NATIONAL = re.compile(
    r"기준\s*중위소득|(?:생계|의료|주거|교육)급여|기초생활보장|"
    r"국민건강보험|국민연금|최저임금|전국\s*(?:공통|적용|기준)|전\s*국민")
CRITERION = re.compile(
    r"급여|지원금|보조금|지급|소득|수급|금액|부담금|보험료|"
    r"선정기준|선정대상|지원대상|자격|요건|최저보장|요율|"
    r"수수료|장학금|보장수준|기준액|권리|법적\s*의무")
RIGHTS = re.compile(
    r"지원대상|선정기준|수급자격|수급대상|입주자격|"
    r"지원요건|법적\s*의무|자격요건|보장수준|지급대상")
DRAFT = re.compile(r"입법예고|행정예고|(?:제정|개정|고시)안(?:$|\s)")
REGISTRY = re.compile(r"업체명|사업장명|법인명|소재지|대표자|사업자등록")
MONEY = re.compile(r"(?<![0-9])\d[\d,.]*\s*(?:억\s*원|만원|원|%|배|개월)")

def _material_change(change):
    """Real change to a numeric criterion or legal eligibility, not a title hit."""
    old, new = str(change.get("before", "")), str(change.get("after", ""))
    if not old.strip() or not new.strip() or old == new:
        return False
    meaning = change.get("meaning") or explain(old, new)
    if (meaning.get("source_check_required") or meaning.get("editorial")
            or meaning.get("change_kind") in ("editorial", "citation", "source_check")
            or is_placeholder_clause(old) or is_placeholder_clause(new)):
        return False
    heading = " ".join((str(change.get("document_title", "")),
                        str(change.get("article", ""))))
    if REGISTRY.search(heading):
        return False
    if not CRITERION.search(old[:2000] + " " + new[:2000] + " " + heading):
        return False
    old_amounts = MONEY.findall(old)
    new_amounts = MONEY.findall(new)
    if old_amounts != new_amounts and (old_amounts or new_amounts):
        return True
    # An HWPX numeric cell has an exact table/row/column identifier.
    if (str(change.get("article", "")).startswith("표 ")
            and re.fullmatch(r"[\d,.]+", old.strip())
            and re.fullmatch(r"[\d,.]+", new.strip())):
        return True
    if RIGHTS.search(old + " " + new) and meaning.get("label") == "대상·자격 기준":
        return (re.sub(r"[^가-힣a-zA-Z0-9]", "", old) !=
                re.sub(r"[^가-힣a-zA-Z0-9]", "", new))
    return False

def assess_impact(event):
    changes = [c for c in event.get("changes", [])
               if c.get("before") != c.get("after")
               and not (c.get("meaning") or {}).get("source_check_required")]
    agencies = {str(row.get("institution", "")).strip()
                for row in event.get("institutional_reviews", [])
                if row.get("basis_tier") in TIERS and row.get("institution")}
    five = bool(changes) and len(agencies) >= 5
    source = (event.get("members") or [{}])[0].get("source")
    national = any(
        source in ("law", "admrul")
        and not DRAFT.search(str(c.get("document_title", "")))
        and NATIONAL.search(" ".join((
            str(c.get("document_title", "")), str(c.get("article", "")),
            str(c.get("before", ""))[:600], str(c.get("after", ""))[:600])))
        and _material_change(c) for c in changes)
    high = five or national
    return {
        "impact_level": "high" if high else "normal" if changes else "pending",
        "impact_high_basis": (
            "변경 조문과 공식 근거로 연결된 공공기관 5곳 이상" if five else
            "전국 공통 기준의 실질적인 금액·자격 변경 확인" if national else ""),
        "verified_institution_count_for_impact": len(agencies),
        "impact_assessment_version": "verified-criteria-and-five-agencies-v2",
    }

def score_and_sort(events):
    for event in events:
        event.update(assess_impact(event))
        event.pop("impact_score", None)
        event.pop("impact_reasons", None)
    events.sort(key=lambda e: (
        e.get("impact_level") == "high", e.get("impact_level") == "normal",
        str(e.get("published_at", "")), str(e.get("id", ""))), reverse=True)
