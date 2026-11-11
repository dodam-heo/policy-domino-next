"""ALIOPLUS institution directory is source-derived, not an impact map."""
import json
import unittest
from policy_domino.agency_registry import collect_institutions,parse_registry

class OfficialDirectoryTests(unittest.TestCase):
 def test_independent_local_corporation_foundation_is_directory_only(self):
  from policy_domino.agency_registry import institution_from_ordinance
  item={"source":"ordin","title":"서울특별시 서울주택도시개발공사 설립 및 운영에 관한 조례",
        "ministry":"서울특별시","url":"https://www.law.go.kr/자치법규/가상"}
  result=institution_from_ordinance(item)
  self.assertEqual(result["agency"],"서울주택도시개발공사")
  self.assertNotIn("institutional_review",result)
  self.assertIsNone(institution_from_ordinance({**item,"source":"admrul"}))

 def test_reject_unmatched_header(self):
  with self.assertRaises(ValueError):
   parse_registry({"apbaList":[{"apbaId":"C1","apbaNa":"가상기관"}]},2)
 def test_official_directory_is_independent_from_impacts(self):
  state={}
  def transport(url,post):
   if post:return json.dumps({"apbaList":[{"apbaId":"C100","apbaNa":"가상공공기관"}]}).encode()
   return b'<div class="total">\xec\xb4\x9d <strong>1</strong></div>'
  result=collect_institutions(state,transport)
  self.assertEqual(result["status"],"collected")
  self.assertEqual(state["official_institutions"]["C100"]["agency"],"가상공공기관")
  self.assertNotIn("institutional_reviews",state)
