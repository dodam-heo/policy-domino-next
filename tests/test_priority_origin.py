import unittest
from policy_domino.priority import assess_impact, _material_standard
from policy_domino.legal_origin import origin_of

class PriorityOriginTests(unittest.TestCase):
 def test_national_standard_real_numeric_change_qualifies(self):
  e={"members":[{"source":"admrul"}],"changes":[{
      "document_title":"기준 중위소득 고시",
      "before":"기준 중위소득 100원","after":"기준 중위소득 120원"}]}
  self.assertEqual(assess_impact(e)["impact_level"],"high")
 def test_structured_table_numeric_change_is_high(self):
  e={"members":[{"source":"admrul"}],"changes":[{
      "document_title":"기준 중위소득 고시",
      "article":"표 1 · 4인 · 기준 중위소득",
      "before":"6,494,738","after":"6,929,885"}]}
  self.assertEqual(assess_impact(e)["impact_level"],"high")
 def test_title_keyword_with_unrelated_number_is_not_high(self):
  e={"members":[{"source":"admrul"}],"changes":[{
      "document_title":"기준 중위소득 고시",
      "before":"담당 부서 연락처 02-1234-5678",
      "after":"담당 부서 연락처 02-1234-5679"}]}
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_changed_year_unchanged_amount_is_not_high(self):
  e={"members":[{"source":"admrul"}],"changes":[{
      "document_title":"기준 중위소득 고시",
      "before":"2026년 100원 기준","after":"2027년 100원 기준"}]}
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_unrelated_money_in_other_part_of_long_clause_is_not_high(self):
  e={"members":[{"source":"admrul"}],"changes":[{
      "document_title":"기준 중위소득 고시",
      "before":"기준 중위소득 100원. "+("같은 기준을 적용한다. "*30)+"연락처 0212345678",
      "after":"기준 중위소득 100원. "+("같은 기준을 적용한다. "*30)+"연락처 0212345679"}]}
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_five_distinct_directly_linked_agencies(self):
  e={"members":[{"source":"ordin"}],"changes":[{
      "document_id":"source-1","article":"제1조",
      "before":"직제 제1과","after":"직제 제2과"}],
     "institutional_reviews":[{
       "document_id":"source-1","article":"제1조",
       "institution":f"기관{i}","basis_tier":"explicit_changed_clause"
     } for i in range(5)]}
  self.assertEqual(assess_impact(e)["impact_level"],"high")
  e["institutional_reviews"]=e["institutional_reviews"][:2]
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_five_citing_agencies_do_not_count_as_work_changes(self):
  e={"members":[{"source":"law"}],"changes":[{
      "document_id":"source-1","article":"제1조",
      "before":"업무 A","after":"업무 B"}],
     "institutional_reviews":[{
       "document_id":"source-1","article":"제1조",
       "institution":f"기관{i}","basis_tier":"verified_official_rule_citation"
     } for i in range(7)]}
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_references_to_unrelated_articles_do_not_count(self):
  e={"members":[{"source":"ordin"}],"changes":[{
      "document_id":"source-1","article":"제1조",
      "before":"직제 A","after":"직제 B"}],
     "institutional_reviews":[{
       "document_id":"source-1","article":"제2조",
       "institution":f"기관{i}","basis_tier":"explicit_changed_clause"
     } for i in range(5)]}
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_citation_only_does_not_qualify_five(self):
  e={"members":[{"source":"ordin"}],"changes":[{
      "before":"제1조에 따른다.","after":"제2조에 따른다."}],
     "institutional_reviews":[{
       "institution":f"기관{i}","basis_tier":"explicit_changed_clause"
     } for i in range(6)]}
  self.assertEqual(assess_impact(e)["impact_level"],"pending")
 def test_names_without_verified_basis_do_not_count(self):
  e={"members":[{"source":"law"}],
     "changes":[{"before":"옛 규정","after":"새 규정"}],
     "agency_names":["기관"+str(i) for i in range(8)]}
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_missing_analysis_pending(self):
  self.assertEqual(assess_impact({"changes":[]})["impact_level"],"pending")
 def test_only_quoted_delegation_is_upstream(self):
  d={"title":"가상 고시","ministry":"가상부처"}
  r=origin_of(d,{"clauses":{"본문":{"text":"「가상법」 제6조의 규정에 따라 정한다."}}})
  self.assertEqual(r["upper_bases"][0]["title"],"가상법")
  self.assertEqual(origin_of(d,{"clauses":{"본문":{"text":"「가상법」의 취지"}}})["upper_bases"],[])
