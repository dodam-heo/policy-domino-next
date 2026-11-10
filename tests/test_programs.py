"""Offline source-contract, operational linkage and false-positive tests."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from policy_domino.alioplus import (
    ALIOPlusClient, ProgramSourceError, listing_detail_urls, parse_detail)
from policy_domino.contracts import ContractError, validate_public
from policy_domino.core import new_state, SCHEMA
from policy_domino.pipeline import render
from policy_domino.programs import (
    canonical_url, discover_program_links, ingest_programs, normalize_program)


LAW = "가상 공공사업법"
URL = "https://www.law.go.kr/법령/가상공공사업법"
PROGRAM_URL = ("https://www.alioplus.go.kr/business/bsnDetail.do?"
               "bsnSeq=2183&bsnTyp=DET")


def event():
    return {"id": "changed-1", "source": "law", "stable_id": "42",
            "serial": "52", "title": LAW, "ministry": "가상 부처",
            "published_at": "2026-11-08", "url": URL,
            "revision": "일부개정", "kind": "법령"}


def changed():
    return {"article": "제3조", "before": "제3조 지급 기준 30만원을 적용한다.",
            "after": "제3조 지급 기준 40만원을 적용한다.",
            "source_url": URL, "evidence": {
                "old_body_sha256": "old-body", "new_body_sha256": "new-body"}}


def program(text, url=PROGRAM_URL):
    return {"agency": "가상 공사", "name": "가상 장학지원 사업",
            "url": url, "description": text}


def state_with_change():
    state = new_state()
    state["documents"] = {"changed-1": event()}
    state["findings"] = {"changed-1": {"status": "compared",
                                     "changes": [changed()]}}
    return state


class VerifiedProgramTests(unittest.TestCase):
    def test_only_official_canonical_program_url(self):
        self.assertEqual(canonical_url(PROGRAM_URL), PROGRAM_URL)
        for forged in (
            "https://www.alioplus.go.kr.evil.test/business/bsnDetail.do?bsnSeq=1",
            "https://www.alioplus.go.kr/business/other.do?bsnSeq=1",
            "http://www.alioplus.go.kr/business/bsnDetail.do?bsnSeq=1",
            "https://www.alioplus.go.kr/business/bsnDetail.do?bsnSeq=abc",
        ):
            self.assertFalse(canonical_url(forged))

    def test_direct_exact_change_becomes_program_dependency_not_action(self):
        s = state_with_change()
        body = ("본 사업은 「가상 공공사업법」 제3조에 따라 30만원을 지원하며 "
                "공식 사업운영 기준을 안내하는 자료입니다.")
        report = ingest_programs(s, [program(body)])
        self.assertEqual(report["accepted"], 1)
        links = discover_program_links(s, [])
        self.assertEqual(len(links), 1)
        result = links[0]
        self.assertEqual(result["agency"], "가상 공사")
        self.assertEqual(result["changed_article"], "제3조")
        self.assertEqual(result["verification"], "verified_program_citation")
        self.assertTrue(result["operational_program_verified"])
        self.assertFalse(result["required_action_verified"])
        self.assertEqual(result["old_value"], "30만원")
        self.assertEqual(result["new_value"], "40만원")
        self.assertEqual(result["path"], "direct")
        self.assertEqual(result["program_body_sha256"],
                         hashlib.sha256(body.encode()).hexdigest())

    def test_wrong_article_and_title_only_are_not_program_dependencies(self):
        for body in [
            "당해 지원사업은 「가상 공공사업법」을 참고하여 운영됩니다.",
            "당해 지원사업은 「가상 공공사업법」 제4조에 따라 운영됩니다.",
            "공고기관은 가상 공사이며 30만원을 지급하는 지원사업입니다.",
            "당해 지원사업은 「다른 정책법」 제3조에 따라 운영됩니다.",
        ]:
            with self.subTest(body=body):
                s = state_with_change()
                ingest_programs(s, [program(body)])
                self.assertEqual(discover_program_links(s, []), [])

    def test_two_hop_chain_requires_verified_intermediary_article(self):
        s = state_with_change()
        body = ("이 장학사업은 「가상 사업시행규칙」 제7조에 따라 운영하고 "
                "신청요건을 확인하는 공공 사업 안내입니다.")
        ingest_programs(s, [program(body)])
        edge = {"source_event_id": "changed-1", "changed_article": "제3조",
                "relationship": "verified_exact_article_citation",
                "referencing_title": "가상 사업시행규칙",
                "referencing_article": "제7조",
                "referencing_source_url": URL}
        self.assertEqual(discover_program_links(s, []), [])
        self.assertEqual(len(discover_program_links(s, [edge])), 1)
        self.assertEqual(discover_program_links(s, [{**edge,
                          "relationship": "search_result"}]), [])
        self.assertEqual(discover_program_links(s, [{**edge,
                          "referencing_article": "제9조"}]), [])
        self.assertEqual(discover_program_links(s, [{**edge,
                          "changed_article": "제4조"}]), [])

    def test_dedup_and_unsafe_records_excluded(self):
        s = state_with_change()
        text = "「가상 공공사업법」 제3조에 따른 기관의 장학운영 사업 안내입니다."
        invalid = program(text, "https://example.com/not-official")
        status = ingest_programs(s, [program(text), invalid, program(text)])
        self.assertEqual(status["accepted"], 2)
        self.assertEqual(status["rejected"], 1)
        self.assertEqual(len(s["official_programs"]), 1)
        self.assertEqual(len(discover_program_links(s, [])), 1)

    def test_public_contract_verifies_link_quote_and_required_action(self):
        s = state_with_change()
        ingest_programs(s, [program(
            "「가상 공공사업법」 제3조에 따라 운영하는 공공장학 신청 안내 사업입니다.")])
        with tempfile.TemporaryDirectory() as tmp:
            data = render(s, Path(tmp) / "data.json")
            self.assertEqual(len(data["program_dependencies"]), 1)
            self.assertEqual(validate_public(data)["changed_provisions"], 1)
            row = data["program_dependencies"][0]
            row["required_action_verified"] = True
            with self.assertRaisesRegex(ContractError, "mandatory"):
                validate_public(data)
            row["required_action_verified"] = False
            row["citation_quote"] = "「가상 공공사업법」 제4조"
            with self.assertRaisesRegex(ContractError, "quote"):
                validate_public(data)

    def test_no_new_false_action_in_naked_catalogue(self):
        s = state_with_change()
        with tempfile.TemporaryDirectory() as tmp:
            data = render(s, Path(tmp) / "data.json")
        self.assertEqual(data["program_dependencies"], [])
        self.assertEqual(data["program_discovery_audit"]["coverage"],
                         "partial_not_nationwide")


class PublicDirectoryTests(unittest.TestCase):
    def test_link_extractor_ignores_nonbusiness_or_pagination_ids(self):
        listing = (('<li><a href="/business/bsnDetail.do?bsnSeq=2183&amp;'
                    'bsnTyp=DET">사업</a></li><input name="pageNo" value="123"/>') +
                   '<a href="/business/bsnDetail.do?bsnSeq=2183">중복</a>')
        self.assertEqual(listing_detail_urls(listing), [PROGRAM_URL])
        self.assertEqual(listing_detail_urls(
            "<li onclick=\\\"fnDetail('2183','DET')\\\">사업</li>"), [PROGRAM_URL])

    def test_extract_actual_field_names_from_official_like_html(self):
        document = ("""<html><h3>교육/연구 > 가상 장학지원 사업</h3>
          <div>기관명</div><div>가상 공사</div><div>사업소개</div>
          <p>이 사업은 「가상 공공사업법」 제3조에 따라 운영하는
          교육장학 지원 프로그램입니다.</p><div>사업 기간</div>
          <p>상시</p></html>""")
        record = parse_detail(document, PROGRAM_URL)
        self.assertEqual(record["name"], "가상 장학지원 사업")
        self.assertEqual(record["agency"], "가상 공사")
        self.assertIn("제3조", record["description"])
        self.assertEqual(normalize_program(record)["url"], PROGRAM_URL)

    def test_missing_labels_cannot_create_pseudo_program(self):
        with self.assertRaises(ProgramSourceError):
            parse_detail("<html><h3>사업소개</h3>이름 미확인</html>", PROGRAM_URL)

    def test_bounded_collection_ingests_only_verified_detail(self):
        body = """<h3>교육/연구 > 가상 장학지원 사업</h3>
                <div>기관명</div><div>가상 공사</div>
                <div>사업소개</div><p>「가상 공공사업법」 제3조에 따라
                운영하는 공공장학 신청 안내 사업입니다.</p>
                <div>사업 기간</div><p>상시</p>"""
        def transport(url):
            if "bsnByLifeList" in url:
                return ('<a href="/business/bsnDetail.do?bsnSeq=2183'
                        '&amp;bsnTyp=DET">가상 사업</a>')
            if "bsnDetail.do" in url:
                return body
            raise OSError("Unknown path")
        client = ALIOPlusClient(transport=transport, delay_seconds=0)
        s = state_with_change()
        audit = client.collect(s, max_details=1)
        self.assertEqual(audit["accepted"], 1)
        self.assertEqual(audit["pages_checked"], 1)
        self.assertFalse(audit["complete"])
        self.assertEqual(len(discover_program_links(s, [])), 1)
        second = client.collect(s, max_details=1)
        self.assertEqual(second["accepted"], 0)
        self.assertIn("No new", second["error"])


if __name__ == "__main__":
    unittest.main()
