import unittest
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, urlparse

from policy_domino.api import LawAPI, nodes, parse_record
from policy_domino.core import SOURCES, document_key, official_url
from policy_domino.parser import parse_document


class SourceExtractionTests(unittest.TestCase):
    def test_three_distinct_official_index_formats(self):
        examples = [
            ("law", """<Search><law><법령ID>11</법령ID><법령일련번호>113</법령일련번호>
               <법령명한글>가상 지원 시행령</법령명한글><공포일자>20261109</공포일자>
               </law></Search>"""),
            ("admrul", """<Search><admrul><행정규칙ID>21</행정규칙ID>
               <행정규칙일련번호>214</행정규칙일련번호><행정규칙명>가상 심사 고시</행정규칙명>
               <발령일자>20261109</발령일자></admrul></Search>"""),
            ("ordin", """<Search><law><자치법규ID>31</자치법규ID>
               <자치법규일련번호>316</자치법규일련번호><자치법규명>가상 조례</자치법규명>
               <공포일자>20261109</공포일자></law></Search>"""),
        ]
        for src, body in examples:
            with self.subTest(source=src):
                root = ET.fromstring(body)
                records = [parse_record(x, src) for x in nodes(root, src)]
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["source"], src)
                self.assertEqual(records[0]["published_at"], "2026-11-09")
                self.assertEqual(records[0]["id"], document_key(
                    src, records[0]["stable_id"], records[0]["serial"]))

    def test_official_rule_kind_search_covers_all_six_categories_without_seed_data(self):
        queries=[]
        def fake(url):
            args=parse_qs(urlparse(url).query)
            queries.append(args)
            return ("""<Search><totalCnt>1</totalCnt><admrul>
                 <행정규칙ID>987</행정규칙ID>
                 <행정규칙일련번호>1001</행정규칙일련번호>
                 <행정규칙명>가상 시설 운영기준</행정규칙명>
                 <행정규칙종류>고시</행정규칙종류>
                 <발령일자>20261110</발령일자>
                 <소관부처명>가상 중앙기관</소관부처명>
                 </admrul></Search>""").encode()
        api=LawAPI("test_oc",fake)
        docs,audit=api.search_window(
            "admrul","2026-11-10","2026-11-10",
            version="1",rule_kind="3")
        self.assertTrue(audit.complete)
        self.assertEqual(audit.rule_kind,"3")
        self.assertEqual(docs[0]["law_type"],"고시")
        self.assertEqual(queries[0]["knd"],["3"])
        self.assertEqual(queries[0]["nw"],["1"])
        with self.assertRaises(ValueError):
            api.search_window("law","2026-11-10","2026-11-10",rule_kind="3")
        with self.assertRaises(ValueError):
            api.search_window("admrul","2026-11-10","2026-11-10",rule_kind="99")

    def test_regulation_category_comes_from_official_metadata_not_title(self):
        from policy_domino.core import ADMIN_RULE_KINDS
        self.assertEqual(set(ADMIN_RULE_KINDS.values()),
                         {"훈령","예규","고시","공고","지침","기타"})
        doc=ET.fromstring("""<admrul>
            <행정규칙ID>1</행정규칙ID><행정규칙일련번호>2</행정규칙일련번호>
            <행정규칙명>기준표</행정규칙명><행정규칙종류>고시</행정규칙종류>
            <발령일자>20261110</발령일자></admrul>""")
        self.assertEqual(parse_record(doc,"admrul")["law_type"],"고시")

    def test_regulation_kind_code_from_official_record_is_not_lost(self):
        root=ET.fromstring("""<admrul>
          <행정규칙ID>401</행정규칙ID>
          <행정규칙일련번호>505</행정규칙일련번호>
          <행정규칙명>가상 소관 부처 기준서</행정규칙명>
          <행정규칙종류코드>3</행정규칙종류코드>
          <발령일자>20260803</발령일자>
          </admrul>""")
        parsed=parse_record(root,"admrul")
        self.assertEqual(parsed["law_type"],"고시")
        self.assertEqual(parsed["published_at"],"2026-08-03")

    def test_official_api_page_limit_is_audited_not_silently_complete(self):
        def fake(url):
            return ("""<Search><totalCnt>250</totalCnt><law>
                <법령명한글>가상법</법령명한글><법령ID>5</법령ID>
                <법령일련번호>10</법령일련번호><공포일자>20261109</공포일자>
                </law></Search>""").encode()
        api = LawAPI("synthetic", fake)
        docs, coverage = api.search_window(
            "law", "2026-11-09", "2026-11-09", max_pages=1)
        self.assertEqual(len(docs), 1)
        self.assertFalse(coverage.complete)
        self.assertEqual(coverage.reported, 250)

    def test_detail_parameter_by_source(self):
        calls = []
        def fake(url):
            calls.append(parse_qs(urlparse(url).query))
            return b"<Root/>"
        api = LawAPI("fake", fake)
        for src in SOURCES:
            api.detail({"source": src, "serial": "42"})
        self.assertEqual([list(x.get("MST",[])) for x in calls],
                         [["42"], [], ["42"]])
        self.assertEqual(calls[1]["ID"], ["42"])
        self.assertTrue(all(x["OC"] == ["fake"] for x in calls))

    def test_never_embeds_api_credential(self):
        with self.assertRaises(ValueError):
            LawAPI("")

    def test_numbered_articles_include_nested_text_once(self):
        root = ET.fromstring("""<법령><조문단위><조문번호>4</조문번호>
          <조문내용>제4조(심사) 기준에 따라 심사한다.</조문내용>
          <항내용>① 신청일부터 10일 이내 처리한다.</항내용>
          </조문단위></법령>""")
        parsed = parse_document(root)
        self.assertEqual(parsed["status"], "extracted")
        self.assertIn("제4조", parsed["clauses"])
        self.assertEqual(parsed["clauses"]["제4조"]["text"].count("신청일부터"),1)

    def test_annex_and_supplement_are_real_content(self):
        xml = """<AdmRul><별표><별표단위><별표번호>1</별표번호>
          <별표내용>금액 기준표 150만원</별표내용></별표단위></별표>
          <부칙><부칙내용>2027년 1월 1일부터 시행한다.</부칙내용></부칙></AdmRul>"""
        parsed = parse_document(ET.fromstring(xml))
        self.assertTrue(any(k.startswith("별표 1") for k in parsed["clauses"]))
        self.assertIn("부칙", parsed["clauses"])
        self.assertEqual(parsed["status"], "extracted")

    def test_attachment_link_only_never_counts_as_body(self):
        xml = """<AdmRul><별표단위><별표서식파일링크>https://law.go.kr/x</별표서식파일링크>
          </별표단위></AdmRul>"""
        parsed = parse_document(ET.fromstring(xml))
        self.assertEqual(parsed["status"], "attachment_only")
        self.assertEqual(parsed["clauses"], {})

    def test_flat_html_is_split_only_at_real_article_headings(self):
        xml = """<AdmRul><조문내용>&lt;p&gt;제1조(지원)&lt;/p&gt; 35만원을 지급한다.
        &lt;p&gt;제2조(조건)&lt;/p&gt; 18세 이상에게 적용한다.</조문내용></AdmRul>"""
        data = parse_document(ET.fromstring(xml))
        self.assertEqual(set(data["clauses"]), {"제1조","제2조"})
        self.assertIn("18세", data["clauses"]["제2조"]["text"])
        self.assertNotIn("<p>",str(data["clauses"]))

    def test_ordinance_jo_naeyong_is_parsed(self):
        xml = """<LawService><조항><조문번호>9</조문번호><조제목>선정</조제목>
          <조내용>대상자 기준은 25만원이다.</조내용></조항></LawService>"""
        data = parse_document(ET.fromstring(xml))
        self.assertEqual(data["clauses"]["제9조"]["text"],
                         "제9조(선정) 대상자 기준은 25만원이다.")

    def test_untrusted_document_size_is_marked_incomplete(self):
        body = "제4조(기준)" + "A"*15001
        root=ET.Element("Root")
        ET.SubElement(root,"조문내용").text=body
        data=parse_document(root)
        self.assertEqual(data["status"],"partial")
        self.assertFalse(data["clauses"]["제4조"]["complete"])


if __name__ == "__main__":
    unittest.main()
