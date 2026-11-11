"""ALIOPLUS institution directory is source-derived, not an impact map."""
import json
import unittest
from policy_domino.agency_registry import collect_institutions,parse_registry

class OfficialDirectoryTests(unittest.TestCase):
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
