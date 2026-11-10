import copy
import unittest

from policy_domino.gov24 import (
    CATALOG, Gov24Client, Gov24SourceError, collect_gov24,
    discover_public_service_leads, normalize_record,
)
from policy_domino.gov24_contract import validate_public_service_candidates


def record(service_id, name="공공 생활지원 사업",
           agency="가상 공공서비스 관리기관"):
    return {
        "서비스ID": service_id,
        "서비스명": name,
        "소관기관명": agency,
        "소관기관유형": "중앙행정기관",
        "소관기관코드": "1234500",
        "법령": "「가상 공공서비스 운영법」 제3조에 따른 대상자 심사",
        "선정기준": "소득 50만원 이하이면 신청 가능",
        "지원내용": "자격 심사 및 지원",
        "지원대상": "지원 대상자",
        "상세조회URL": "https://www.gov.kr/portal/service",
    }


def policy_event():
    return {
        "id": "event-1", "changes": [{
            "document_id": "official-doc-1", "document_title": "가상 공공서비스 운영법",
            "article": "제3조", "before": "소득 50만원 이하",
            "after": "소득 70만원 이하",
        }], "source_documents": ["official-doc-1"],
    }


class Gov24Tests(unittest.TestCase):
    def test_official_schema_normalization_preserves_real_service_and_issuer(self):
        entry = normalize_record(record("S0001"))
        self.assertEqual(entry["source"], "gov24")
        self.assertEqual(entry["service_id"], "S0001")
        self.assertEqual(entry["agency"], "가상 공공서비스 관리기관")
        self.assertIn("50만원", entry["fields"]["선정기준"])
        self.assertEqual(entry["source_url"], CATALOG)
        self.assertTrue(entry["service_url"].startswith("https://www.gov.kr"))
        altered = record("S0002")
        altered["소관기관명"] = ""
        with self.assertRaises(Gov24SourceError):
            normalize_record(altered)
        altered["소관기관명"] = "가상공공기관"
        altered["상세조회URL"] = "https://attacker.example/service"
        self.assertEqual(normalize_record(altered)["service_url"], "")

    def test_missing_key_collects_nothing_and_shows_unconfigured(self):
        state = {}
        result = collect_gov24(state, "")
        self.assertEqual(result["status"], "not_configured")
        self.assertNotIn("public_services", state)
        self.assertEqual(result["attempted_pages"], 0)

    def test_cursor_persists_and_detail_enriches_real_official_listing(self):
        state = {}
        calls = []
        def transport(op, page, size):
            calls.append((op, page, size))
            if op == "serviceList":
                return {"page": page, "totalCount": 2, "data":
                        [record("S000"+str(page))]}
            item = record("S000"+str(page))
            item["선정기준"] = "새 공식 대상 자격 확인"
            item["행정규칙"] = "「가상 공공서비스 운영법」 제3조"
            return {"page": page, "totalCount": 2, "data": [item]}
        result=collect_gov24(state,"test-key",pages_per_feed=1,
                             page_size=1,transport=transport)
        self.assertEqual(result["accepted"],2)
        self.assertEqual(state["gov24_cursors"],{
            "serviceList":2,"serviceDetail":2})
        self.assertEqual(len(state["public_services"]),1)
        self.assertIn("행정규칙",
                      state["public_services"]["S0001"]["fields"])
        second=collect_gov24(state,"test-key",pages_per_feed=1,
                             page_size=1,transport=transport)
        self.assertEqual(len(state["public_services"]),2)
        self.assertEqual(state["gov24_cursors"],{
            "serviceList":1,"serviceDetail":1})
        self.assertEqual(calls,[
            ("serviceList",1,1),("serviceDetail",1,1),
            ("serviceList",2,1),("serviceDetail",2,1)])
        self.assertEqual(second["status"],"collected_incrementally")

    def test_unsupported_api_response_does_not_advance_cursor(self):
        state = {}
        def bad(op,page,size):
            return {"page":page,"data":[]}
        audit = collect_gov24(state,"test-key",transport=bad)
        self.assertEqual(audit["status"],"partial")
        self.assertEqual(audit["attempted_pages"],0)
        self.assertEqual(len(audit["errors"]),2)
        self.assertEqual(state["gov24_cursors"],
                         {"serviceList":1,"serviceDetail":1})

    def test_real_public_service_legal_citation_creates_unverified_lead(self):
        service = normalize_record(record("S111"))
        state = {"public_services":{"S111":service}}
        event=policy_event()
        result=discover_public_service_leads(state,[event])
        self.assertEqual(result["total_candidates"],1)
        item=event["public_service_leads"][0]
        self.assertEqual(item["match_tier"],"official_clause_citation")
        self.assertEqual(item["agency"],service["agency"])
        self.assertEqual(item["service_name"],service["service_name"])
        self.assertIn("50만원",item["old_value_seen_in_service"])
        self.assertEqual(item["verification"],"candidate_not_confirmed")
        self.assertIn("S111",result["proofs"])
        public = {"events":[event],"public_service_proofs":result["proofs"],
                  "public_services_indexed":1,"public_service_review_leads":1}
        self.assertEqual(validate_public_service_candidates(public),[])
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["agency"]="출처 없는 기관"
        self.assertTrue(validate_public_service_candidates(forged))
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["basis_quote"]="근거 없는 법령"
        self.assertTrue(validate_public_service_candidates(forged))
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["verification"]="confirmed_action"
        self.assertTrue(validate_public_service_candidates(forged))

    def test_title_only_basis_does_not_pretend_article_level_citation(self):
        raw=record("S777")
        raw["법령"]="가상 공공서비스 운영법"
        state={"public_services":{"S777":normalize_record(raw)}}
        ev=policy_event()
        discover_public_service_leads(state,[ev])
        self.assertEqual(ev["public_service_leads"][0]["match_tier"],
                         "official_rule_title")

    def test_unrelated_similar_program_without_exact_rule_name_does_not_link(self):
        raw=record("S555")
        raw["법령"]="「다른 공공서비스 운영법」 제3조"
        raw["서비스명"]="가상 공공서비스 운영법 안내"
        ev=policy_event()
        discover_public_service_leads({"public_services":{
            "S555": normalize_record(raw)}},[ev])
        self.assertEqual(ev["public_service_lead_count"],0)
        self.assertEqual(ev["public_service_leads"],[])


if __name__ == "__main__":
    unittest.main()
