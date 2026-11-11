"""Local corporation names come from official institutional source, not guesses."""
import unittest
from policy_domino.agency_registry import parse_local_registry

class CleanEyeRegistryTests(unittest.TestCase):
 def test_extracts_government_corporations_but_not_topic_labels(self):
  html="""<table><tr><th>지역</th><th>구분</th><th>유형</th><th>기관명</th></tr>
  <tr><td>서울</td><td>광역</td><td>공사</td><td>""" + (
     ", ".join(f"가상{i}도시공사" for i in range(35)))+"""</td></tr></table>"""
  values=parse_local_registry(html)
  self.assertEqual(len(values),35)
  self.assertNotIn("공사", [x["agency"] for x in values.values()])
