import unittest
from policy_domino.gov24 import changed_numeric_pairs,_title_only_criterion_match,service_change_basis
from policy_domino.priority import assess_impact

class ProvenNumericTableTests(unittest.TestCase):
 def test_structured_table_has_unitless_exact_numeric_delta(self):
  change={"article":"표 1 · 4인 · 기준 중위소득","document_title":"기준 중위소득 고시",
          "before":"6,494,738","after":"6,929,885"}
  self.assertEqual(changed_numeric_pairs(change),[("6,494,738","6,929,885")])
  score=assess_impact({"changes":[change],"members":[{"source":"admrul"}]})
  self.assertEqual(score["impact_score"],75)
 def test_delegated_table_requires_old_amount_and_matching_household(self):
  change={"article":"표 1 · 4인 · 기준 중위소득","document_title":"기준 중위소득 고시",
          "before":"6,494,738","after":"6,929,885",
          "origin_upper_bases":[{"title":"가상복지법","article":"제6조"}]}
  service={"regulatory_basis":"「가상복지법」 제6조",
           "fields":{"선정기준":"4인 가구 기준 중위소득 6,494,738원"},
           "service_name":"공공임대 소득기준"}
  self.assertTrue(_title_only_criterion_match(service,change))
  self.assertEqual(service_change_basis(service,change)[0],"official_delegated_numeric_criterion")
  service["fields"]["선정기준"]="3인 가구 기준 중위소득 6,494,738원"
  self.assertFalse(_title_only_criterion_match(service,change))
