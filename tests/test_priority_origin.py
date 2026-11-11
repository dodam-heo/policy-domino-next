import unittest
from policy_domino.priority import assess_impact
from policy_domino.legal_origin import origin_of
class PriorityOriginTests(unittest.TestCase):
 def test_national_standard_qualifies_without_agencies(self):
  e={"members":[{"source":"admrul"}],"changes":[{"before":"기준 중위소득 100원","after":"기준 중위소득 120원"}]}
  self.assertEqual(assess_impact(e)["impact_score"],75)
  self.assertEqual(assess_impact(e)["impact_level"],"high")
 def test_five_unique_verified_agencies_qualify(self):
  e={"members":[{"source":"ordin"}],"changes":[{"before":"직제 제1과","after":"직제 제2과"}],
     "institutional_reviews":[{"institution":f"기관{i}","basis_tier":"explicit_changed_clause"} for i in range(5)]}
  self.assertEqual(assess_impact(e)["impact_level"],"high")
  e["institutional_reviews"]=e["institutional_reviews"][:2]
  self.assertEqual(assess_impact(e)["impact_level"],"normal")
 def test_missing_analysis_pending(self):
  self.assertEqual(assess_impact({"changes":[]})["impact_level"],"pending")
 def test_only_quoted_delegation_is_upstream(self):
  d={"title":"가상 고시","ministry":"가상부처"}
  r=origin_of(d,{"clauses":{"본문":{"text":"「가상법」 제6조의 규정에 따라 정한다."}}})
  self.assertEqual(r["upper_bases"][0]["title"],"가상법")
  self.assertEqual(origin_of(d,{"clauses":{"본문":{"text":"「가상법」의 취지"}}})["upper_bases"],[])
