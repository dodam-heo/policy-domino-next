import hashlib
import unittest
import xml.etree.ElementTree as ET
from policy_domino.parser import parse_document
from policy_domino.annexes import (
    authorized_law_pdf_url, enrich_annexes, normalize_legacy_annex_keys,
    extract_hwpx_text
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

    def test_flat_notice_body_and_root_pdf_survive_supplementary_provisions(self):
        def notice(amount, seq):
            return ET.fromstring("""<행정규칙>
              <조문내용>1. 선정기준은 표와 같다.&lt;img id="1"&gt;&lt;/img&gt;</조문내용>
              <부칙><부칙내용>이 고시는 다음 해부터 시행한다.</부칙내용></부칙>
              <첨부파일><첨부파일명>연간 기준(전문).pdf</첨부파일명>
              <첨부파일링크>http://law.go.kr/flDownload.do?flSeq=""" + seq + """</첨부파일링크>
              <첨부파일명>연간 기준(전문).hwp</첨부파일명>
              <첨부파일링크>http://law.go.kr/flDownload.do?flSeq=999</첨부파일링크>
              </첨부파일></행정규칙>""")
        old, new = notice("100", "11"), notice("120", "12")
        self.assertIn("본문", parse_document(new)["clauses"])
        urls = []
        def download(url):
            urls.append(url)
            return b"%PDF official test"
        before = enrich_annexes(old, parse_document(old), downloader=download,
                               pdf_extractor=lambda _: "선정기준 100만원")
        after = enrich_annexes(new, parse_document(new), downloader=download,
                              pdf_extractor=lambda _: "선정기준 120만원")
        result = compare(before, after, {"url": "https://www.law.go.kr"})
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["article"], "첨부 전문")
        self.assertEqual(len(urls), 2)
        self.assertFalse(any("999" in url for url in urls))
        self.assertTrue(after["annex_evidence"]["첨부 전문"]["pdf_sha256"])

    def test_dated_supplements_in_full_attachments_are_not_false_missing_clauses(self):
        from policy_domino.parser import take
        before = {"status": "extracted", "clauses": {
            "부칙 2025-1": take("2026년 시행"),
            "첨부 전문": take("지원금액 100만원 부칙 2026년 시행")}}
        after = {"status": "extracted", "clauses": {
            "부칙 2026-1": take("2027년 시행"),
            "첨부 전문": take("지원금액 120만원 부칙 2027년 시행")}}
        result = compare(before, after, {"url": "https://www.law.go.kr"})
        self.assertEqual(result["status"], "compared")
        self.assertEqual(result["excluded"], [])
        self.assertEqual(len(result["changes"]), 1)
        self.assertIn("120만원", result["changes"][0]["after"])

    def test_hwpx_only_official_notice_extracts_table_cells(self):
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Contents/section0.xml", """<section xmlns:hp="urn:test">
              <hp:p><hp:t>가구원 수별 선정기준</hp:t></hp:p>
              <hp:tbl><hp:tr><hp:tc><hp:t>4인</hp:t></hp:tc>
              <hp:tc><hp:t>100만원</hp:t></hp:tc></hp:tr></hp:tbl></section>""")
        blob = buffer.getvalue()
        self.assertIn("4인 100만원", extract_hwpx_text(blob))
        root = ET.fromstring("""<행정규칙><첨부파일>
          <첨부파일명>지원기준.hwpx</첨부파일명>
          <첨부파일링크>http://law.go.kr/flDownload.do?flSeq=20</첨부파일링크>
          </첨부파일></행정규칙>""")
        result = enrich_annexes(root, parse_document(root),
                               hwpx_downloader=lambda _: blob)
        self.assertIn("100만원", result["clauses"]["첨부 전문"]["text"])
        self.assertEqual(result["annex_evidence"]["첨부 전문"]["source"],
                         "law_go_kr_official_hwpx")

    def test_explanatory_pdf_is_not_used_instead_of_actual_hwpx_instrument(self):
        root = ET.fromstring("""<행정규칙><첨부파일>
          <첨부파일명>조문별제개정이유서.pdf</첨부파일명>
          <첨부파일링크>http://law.go.kr/flDownload.do?flSeq=100</첨부파일링크>
          <첨부파일명>연간 선정기준 고시.hwpx</첨부파일명>
          <첨부파일링크>http://law.go.kr/flDownload.do?flSeq=101</첨부파일링크>
          </첨부파일></행정규칙>""")
        calls = []
        def fetch(url):
            calls.append(url)
            return b"PK actual legal text"
        result = enrich_annexes(root, parse_document(root),
                               downloader=lambda _: self.fail("explanatory file is not law"),
                               hwpx_downloader=fetch,
                               hwpx_extractor=lambda _: "4인 가구 기준 100만원")
        self.assertEqual(len(calls), 1)
        self.assertIn("101", calls[0])
        self.assertEqual(result["clauses"]["첨부 전문"]["text"], "4인 가구 기준 100만원")

    def test_unresolved_inline_image_table_remains_partial(self):
        root = ET.fromstring("""<행정규칙><조문내용>
            선정기준은 다음 표와 같다. &lt;img id="30"&gt;&lt;/img&gt;
            </조문내용></행정규칙>""")
        result = enrich_annexes(root, parse_document(root))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["unresolved_annexes"][0]["reason"],
                         "image_table_unresolved")

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
