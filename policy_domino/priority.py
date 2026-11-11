"""Reproducible, source-grounded policy impact classification."""
import re

SUBSTANTIVE=re.compile(r"기준\s*중위소득|급여|지원금|소득기준|소득인정액|선정기준|수급자격|입주자격|지원대상|지원요건|부담금|수수료|세율|보험료|과태료|최저임금|최저보장|보조율|요율|기준금액")
PROCEDURE=re.compile(r"신청절차|심사절차|승인절차|허가절차|처리기간|제출서류|신청방법|신고방법|접수방법|인허가|선정방법|업무처리|운영절차|의무화|법정기한")
ORGANIZATION=re.compile(r"직제|정원|조직|부서|소속기관|업무분장|권한|위임|사무")
NATIONAL=re.compile(r"기준\s*중위소득|최저임금|전국|전\s*국민|국민\s*전체|국민건강보험|국민기초생활")
SECTOR=re.compile(r"급여|지원|수급|소득|보험|주택|임대|근로자|교육|자격|인허가|과세|사업")
TIERS={"direct_regulated_institution","explicit_changed_clause","verified_official_rule_citation","verified_program_citation"}

def assess_impact(event):
    changes=[c for c in event.get("changes",[]) if c.get("before")!=c.get("after")
             and not (c.get("meaning") or {}).get("source_check_required")]
    combined=" ".join((str(c.get("before",""))[-5000:]+" "+
         str(c.get("after",""))[-5000:]+" "+str(c.get("article",""))+
         " "+str(c.get("document_title",""))) for c in changes)
    if not changes: substantive,reason_s=0,"신구 원문 비교에 의한 실질적 변경 평가 대기"
    elif SUBSTANTIVE.search(combined): substantive,reason_s=40,"금액·자격·선정 등 실질 기준 변경"
    elif PROCEDURE.search(combined): substantive,reason_s=30,"신청·심사 등 절차 변경"
    elif ORGANIZATION.search(combined): substantive,reason_s=20,"조직·권한·업무분장 변경"
    else: substantive,reason_s=10,"그 밖의 실제 조문 변경"
    central=(event.get("members") or [{}])[0].get("source") in ("law","admrul")
    if not changes: scope,reason_b=0,"변경 원문 분석 뒤 적용 범위 평가"
    elif central and NATIONAL.search(combined): scope,reason_b=35,"전국 공통 적용 기준"
    elif central and SECTOR.search(combined): scope,reason_b=25,"전국 단위 특정 분야·대상"
    elif central: scope,reason_b=15,"중앙 규범의 제한된 업무 범위"
    elif SECTOR.search(combined): scope,reason_b=15,"특정 지역·사업 분야"
    else: scope,reason_b=5,"기관 내부·제한적 지역 업무"
    agencies={r.get("institution","").strip() for r in event.get("institutional_reviews",[])
              if r.get("institution") and r.get("basis_tier") in TIERS}
    programs=[r for r in event.get("institutional_reviews",[]) if r.get("basis_tier")=="verified_program_citation"]
    services=[r for r in event.get("public_service_leads",[]) if r.get("basis_quote") and r.get("source_url")]
    if len(agencies)>=2 and (programs or services): pathway,reason_p=25,"복수 기관과 실제 공공사업 연결"
    elif agencies or programs or services: pathway,reason_p=15,"공식 근거로 업무·사업 연결"
    elif event.get("dependent_rules"): pathway,reason_p=8,"관련 규정 인용 관계 확인"
    else: pathway,reason_p=0,"후속 연결은 추가 분석 대상"
    total=substantive+scope+pathway
    five=len(agencies)>=5
    high= five or (substantive>=30 and total>=65)
    return {
        "impact_score":total,"impact_level":"high" if high else "pending" if not changes else "normal",
        "impact_high_basis":"공식 근거로 연결된 공공기관 5곳 이상" if five else
            "실질성 30점 이상·총점 65점 이상" if high else "",
        "verified_institution_count_for_impact":len(agencies),
        "impact_reasons":[
            {"axis":"변경의 실질성","score":substantive,"maximum":40,"reason":reason_s},
            {"axis":"적용 범위","score":scope,"maximum":35,"reason":reason_b},
            {"axis":"파급 경로","score":pathway,"maximum":25,"reason":reason_p}
        ]}
def score_and_sort(events):
    for e in events:e.update(assess_impact(e))
    events.sort(key=lambda e:(e["impact_level"]=="high",e["impact_level"]=="pending",
                              e["impact_score"],e.get("published_at",""),e["id"]),reverse=True)
