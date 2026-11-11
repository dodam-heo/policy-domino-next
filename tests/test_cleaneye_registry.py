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
 def test_renamed_institution_keeps_verified_alias(self):
  html="""<table><tr><th>지역</th><th>기관명</th></tr>
  <tr><td>광역</td><td>""" + (
     ", ".join(f"가상{i}도시공사" for i in range(35)))+"""</td></tr></table>
  <p>● 명칭변경 : 가상1도시공사 > 새가상1도시공사</p>"""
  rows=parse_local_registry(html)
  target=next(v for v in rows.values() if v["agency"]=="새가상1도시공사")
  self.assertEqual(target["former_names"],["가상1도시공사"])
  self.assertIn("cleaneye.go.kr",target["rename_source_url"])


class CleanEyeOfficialTargetTests(unittest.TestCase):
 def test_from_official_target_agency_column(self):
  from policy_domino.agency_registry import parse_local_target_list
  html="""<table><tr><th>순번</th><th>회계연도</th><th>기관명</th><th>기관분류</th></tr>
  <tr><td>5</td><td>2025</td><td>서울주택도시개발공사</td><td>도시개발공사</td></tr>
  <tr><td>1</td><td>2025</td><td>통합테스트공기업</td><td>도시철도공사</td></tr></table>"""
  rows=parse_local_target_list(html)
  self.assertEqual(len(rows),1)
  self.assertEqual(next(iter(rows.values()))["agency"],"서울주택도시개발공사")
 def test_secondary_official_source_after_first_unavailable(self):
  from policy_domino.agency_registry import collect_local_institutions
  html="""<table><tr><th>순번</th><th>회계연도</th><th>기관명</th><th>기관분류</th></tr>
  <tr><td>5</td><td>2025</td><td>서울주택도시개발공사</td><td>도시개발공사</td></tr></table>"""
  def transport(url):
   if "pubCompStatus" in url:raise OSError("first source unavailable")
   return html.encode("utf8")
  state={}
  report=collect_local_institutions(state,transport)
  self.assertEqual(report["status"],"partial_official_target_list")
  self.assertEqual(len(state["official_local_institutions"]),1)
