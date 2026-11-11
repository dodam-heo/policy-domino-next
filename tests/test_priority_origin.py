import unittest
from policy_domino.priority import assess_impact
from policy_domino.legal_origin import origin_of

def event(title, before, after, article="제1조", source="law", reviews=None):
    change={"document_id":"doc-one","article":article,
            "document_title":title,"before":before,"after":after}
    return {"title":title,"members":[{"source":source}],
            "changes":[change],"institutional_reviews":reviews or []}

def actor(name,article="제1조",tier="explicit_changed_clause"):
    return {"institution":name,"document_id":"doc-one","article":article,
            "basis_tier":tier,"source_url":"https://www.law.go.kr/법령/가상규정",
            "basis_quote":"공식 개정 조문 본문"}

class PriorityOriginTests(unittest.TestCase):
 def test_annual_national_income_standard_high(self):
  e=event("2027년 기준 중위소득 및 생계급여 고시",
          "기준 중위소득 · 1인 가구 2,564,238원",
          "기준 중위소득 · 1인 가구 2,736,042원",
          "첨부 전문","admrul")
  self.assertEqual(assess_impact(e)["impact_level"],"high")
 def test_structured_numeric_table_qualifies(self):
  e=event("기준 중위소득 고시","6,494,738","6,929,885",
          "표 1 · 4인 · 기준 중위소득","admrul")
  self.assertEqual(assess_impact(e)["impact_level"],"high")
 def test_five_public_institutions_high(self):
  e=event("공공 업무 기준","직제 제1과","직제 제2과",
          reviews=[actor("기관"+str(i)) for i in range(5)])
  self.assertEqual(assess_impact(e)["impact_level"],"high")
  e["institutional_reviews"]=e["institutional_reviews"][:2]
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_citation_only_institutions_not_counted(self):
  e=event("공공 업무 기준","직제 제1과","직제 제2과",
          reviews=[actor("기관"+str(i),tier="verified_official_rule_citation")
                   for i in range(9)])
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_financial_administration_notice_switch_is_high(self):
  e=event("금융기관 관련 시행령",
          "금융위원회는 공개설명회를 개최하려면 미리 일간신문에 공고하고 정보통신망으로 알려야 한다.",
          "금융위원회는 공개설명회를 개최하려면 미리 금융위원회의 인터넷 홈페이지에 공고해야 하고 필요하면 신문에 공고할 수 있다.",
          "제18조의2",
          reviews=[actor("금융위원회","제18조의2"),
                   actor("예금보험공사","제18조의2")])
  self.assertEqual(assess_impact(e)["impact_level"],"high")
  self.assertEqual(assess_impact(e)["impact_high_basis"],"공공기관의 업무 절차 변경")
 def test_web_channel_without_direct_public_actor_not_high(self):
  e=event("계엄법 시행령",
          "계엄지역의 보상청구개시일 전에 일간신문에 공고한다.",
          "계엄지역의 보상청구개시일 전에 인터넷 홈페이지에 공고한다.")
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_seafarers_private_industry_without_direct_public_task_not_high(self):
  e=event("선원법",
          "선박소유자는 선원의 임금을 100만원 지급한다.",
          "선박소유자는 선원의 임금을 120만원 지급한다.",
          reviews=[actor("국토교통부",tier="verified_official_rule_citation")])
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_court_staff_rule_not_a_national_public_benefit(self):
  e=event("법원공무원규칙",
          "시험 불합격 후 6개월이 경과하여야 재응시할 수 있다.",
          "시험 응시자격은 3회로 제한한다.")
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_irrelevant_amount_is_not_public_benefit(self):
  e=event("기준 중위소득 고시",
          "담당부서 전화번호 02-1234-5678",
          "담당부서 전화번호 02-1234-5679",source="admrul")
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_unchanged_money_with_new_year_not_high(self):
  e=event("기준 중위소득 고시","2026년 기준액 100원",
          "2027년 기준액 100원",source="admrul")
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_citation_only_change_is_pending(self):
  e=event("근거 규정","제12조에 따른다.","제13조에 따른다.",
          reviews=[actor("기관"+str(i)) for i in range(6)])
  self.assertEqual(assess_impact(e)["impact_level"],"pending")
 def test_no_changes_pending(self):
  self.assertEqual(assess_impact({"changes":[]})["impact_level"],"pending")
 def test_only_quoted_delegation_is_upstream(self):
  d={"title":"가상 고시","ministry":"가상부처"}
  r=origin_of(d,{"clauses":{"본문":{"text":"「가상법」 제6조의 규정에 따라 정한다."}}})
  self.assertEqual(r["upper_bases"][0]["title"],"가상법")
  self.assertEqual(origin_of(d,{"clauses":{"본문":{"text":"「가상법」의 취지"}}})["upper_bases"],[])
