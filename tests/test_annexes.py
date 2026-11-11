import hashlib
import unittest
import xml.etree.ElementTree as ET
from policy_domino.parser import parse_document
from policy_domino.annexes import (
    authorized_law_pdf_url, enrich_annexes, normalize_legacy_annex_keys
)
from policy_domino.analysis import compare


class AnnexIntegrationTests(unittest.TestCase):
    def test_official_pdf_annex_is_extracted_and_compared_by_stable_number(self):
        def official_annex(title, flseq):
            return ET.fromstring(
                "<행정규칙><별표단위><별표번호>1</별표번호>"
                "<별표제목>"+title+"</별표제목>"
                "<별표서식PDF파일링크>/LSW/flDownload.do?flSeq="+flseq+
                "</별표서식PDF파일링크></별표단위></행정규칙>")
        urls=[]
        def downloader(url):
            urls.append(url)
            return b"%PDF-1.4 official mock"
        old=official_annex("2026년도 선정기준","201")
        new=official_annex("2027년도 선정기준","202")
        before=enrich_annexes(old,parse_document(old),downloader=downloader,
                 pdf_extractor=lambda _: "별표 1 지원기준 100만원")
        after=enrich_annexes(new,parse_document(new),downloader=downloader,
                 pdf_extractor=lambda _: "별표 1 지원기준 120만원")
        self.assertEqual(before["status"],"extracted")
        self.assertEqual(after["status"],"extracted")
        self.assertIn("별표 1",before["clauses"])
        self.assertNotIn("2026년도 선정기준",str(before["clauses"].keys()))
        change=compare(before,after,{"url":"https://www.law.go.kr"})
        self.assertEqual(change["status"],"compared")
        self.assertEqual(len(change["changes"]),1)
        self.assertIn("100만원",change["changes"][0]["before"])
        self.assertIn("120만원",change["changes"][0]["after"])
        self.assertEqual(len(urls),2)
        self.assertTrue(after["annex_evidence"]["별표 1"]["pdf_sha256"])

    def test_unextractable_annex_fails_closed(self):
        root=ET.fromstring("""<행정규칙><별표단위><별표번호>4</별표번호>
          <별표서식PDF파일링크>/LSW/flDownload.do?flSeq=15</별표서식PDF파일링크>
          </별표단위></행정규칙>""")
        result=enrich_annexes(root,parse_document(root),
             downloader=lambda url: b"not a pdf",
             pdf_extractor=lambda b: (_ for _ in ()).throw(ValueError("No digital text")))
        self.assertEqual(result["status"],"attachment_only")
        self.assertEqual(len(result["unresolved_annexes"]),1)
        self.assertEqual(result["clauses"],{})

    def test_pdf_attachment_url_never_accepts_external_host_or_other_path(self):
        self.assertEqual(
            authorized_law_pdf_url("/LSW/flDownload.do?flSeq=123&extra=1"),
            "https://www.law.go.kr/LSW/flDownload.do?flSeq=123")
        for url in ("https://outside.example/LSW/flDownload.do?flSeq=1",
                    "https://www.law.go.kr/LSW/notdownload.do?flSeq=1",
                    "https://www.law.go.kr/LSW/flDownload.do?flSeq=bad",
                    "//evil.example/LSW/flDownload.do?flSeq=123",
                    "file:///etc/passwd"):
            self.assertFalse(authorized_law_pdf_url(url), url)

    def test_old_stored_legal_annex_title_is_normalized_not_restored(self):
        legacy={
            "status":"extracted",
            "clauses":{"별표 1 (2026년도 자격표)":{
                "text":"소득기준 100만원","complete":True,
                "sha256":"old"}},
            "incomplete_keys":[],
        }
        same=normalize_legacy_annex_keys(legacy)
        self.assertIn("별표 1",same["clauses"])
        self.assertNotIn("별표 1 (2026년도 자격표)",same["clauses"])
        self.assertEqual(same["clauses"]["별표 1"]["text"],"소득기준 100만원")

    def test_annex_fetch_budget_retains_unresolved_followup(self):
        root=ET.fromstring("""<행정규칙>
          <별표단위><별표번호>1</별표번호>
            <별표서식PDF파일링크>/LSW/flDownload.do?flSeq=10</별표서식PDF파일링크>
          </별표단위>
          <별표단위><별표번호>2</별표번호>
            <별표서식PDF파일링크>/LSW/flDownload.do?flSeq=11</별표서식PDF파일링크>
          </별표단위></행정규칙>""")
        calls=[]
        def downloader(url):
            calls.append(url)
            return b"%PDF"
        first=enrich_annexes(root,parse_document(root),
                  downloader=downloader,pdf_extractor=lambda b:"기준액 100만원",
                  max_downloads=1)
        self.assertEqual(first["status"],"partial")
        self.assertEqual(first["unresolved_annexes"][0]["reason"],
                         "deferred_pdf_budget")
        second=enrich_annexes(root,parse_document(root),previous_snapshot=first,
                  downloader=downloader,pdf_extractor=lambda b:"기준액 100만원",
                  max_downloads=1)
        self.assertEqual(second["status"],"extracted")
        self.assertEqual(len(second["clauses"]),2)
        self.assertEqual(len(calls),2)

    def test_inline_annex_is_preserved_and_not_fetched(self):
        root=ET.fromstring("""<행정규칙><별표단위><별표번호>1</별표번호>
          <별표제목>자격 기준표</별표제목>
          <별표내용>지원금액 150만원</별표내용>
          <별표서식PDF파일링크>/LSW/flDownload.do?flSeq=8</별표서식PDF파일링크>
          </별표단위></행정규칙>""")
        result=enrich_annexes(root,parse_document(root),
            downloader=lambda _: self.fail("inline annex already present"))
        self.assertEqual(result["status"],"extracted")
        self.assertEqual(result["clauses"]["별표 1"]["text"],"지원금액 150만원")

if __name__=="__main__":
    unittest.main()
