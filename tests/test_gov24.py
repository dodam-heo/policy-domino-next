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
    def test_all_matching_agencies_remain_available_beyond_preview_limit(self):
        services = {
            f"S{i:03}": normalize_record(record(
                f"S{i:03}", agency=f"가상 공공기관 {i:03}"))
            for i in range(25)
        }
        event = policy_event()
        result = discover_public_service_leads({"public_services": services}, [event])
        self.assertEqual(event["public_service_lead_count"], 25)
        self.assertEqual(len(event["public_service_leads"]), 25)
        self.assertEqual(len(result["proofs"]), 25)
        self.assertEqual(validate_public_service_candidates({
            "events": [event], "public_service_proofs": result["proofs"],
        }), [])

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

    def test_official_list_without_agency_is_kept_until_detail_supplies_issuer(self):
        raw=record("S090")
        raw.pop("소관기관명")
        partial=normalize_record(raw,allow_missing_agency=True)
        self.assertEqual(partial["agency"],"")
        state={"public_services":{"S090":partial}}
        ev=policy_event()
        discover_public_service_leads(state,[ev])
        self.assertEqual(ev["public_service_lead_count"],0)
        from policy_domino.gov24 import merge_record
        detailed=normalize_record(record("S090"))
        state["public_services"]["S090"]=merge_record(partial,detailed)
        ev=policy_event()
        discover_public_service_leads(state,[ev])
        self.assertEqual(ev["public_service_lead_count"],1)

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
        self.assertEqual(item["review_targets"][0]["field"],"선정기준")
        self.assertEqual(item["review_targets"][0]["old_value"],"50만원")
        self.assertEqual(item["review_targets"][0]["new_legal_value"],"70만원")
        self.assertIn("선정기준",item["review_targets"][0]["review_question"])
        self.assertEqual(item["verification"],"candidate_not_confirmed")
        self.assertIn("S111",result["proofs"])
        public = {"events":[event],"public_service_proofs":result["proofs"],
                  "public_services_indexed":1,"public_service_review_leads":1}
        self.assertEqual(validate_public_service_candidates(public),[])
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["agency"]="출처 없는 기관"
        self.assertTrue(validate_public_service_candidates(forged))
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["review_targets"][0]["source_excerpt"]="공식 자료에 없는 기준"
        self.assertTrue(validate_public_service_candidates(forged))
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["review_targets"][0]["new_legal_value"]="900만원"
        self.assertTrue(validate_public_service_candidates(forged))
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["basis_quote"]="근거 없는 법령"
        self.assertTrue(validate_public_service_candidates(forged))
        forged=copy.deepcopy(public)
        forged["events"][0]["public_service_leads"][0]["verification"]="confirmed_action"
        self.assertTrue(validate_public_service_candidates(forged))

    def test_annual_notice_links_through_parent_clause_and_exact_service_criterion(self):
        service = normalize_record(record("ANNUAL"))
        service["fields"]["선정기준"] = "생활안정급여 소득 50만원 이하"
        event = policy_event()
        change = event["changes"][0]
        change.update({
            "document_title": "2027년 생활안정급여 선정기준 및 최저보장수준",
            "article": "첨부 전문",
            "before": "「가상 공공서비스 운영법」 제3조 생활안정급여 소득 50만원 이하",
            "after": "「가상 공공서비스 운영법」 제3조 생활안정급여 소득 70만원 이하",
        })
        state = {"public_services": {"ANNUAL": service}}
        result = discover_public_service_leads(state, [event])
        lead = event["public_service_leads"][0]
        self.assertEqual(lead["match_tier"], "official_shared_clause_and_criterion")
        self.assertEqual(lead["review_targets"][0]["new_legal_value"], "70만원")
        payload = {"events": [event], "public_service_proofs": result["proofs"],
                   "public_services_indexed": 1, "public_service_review_leads": 1}
        self.assertEqual(validate_public_service_candidates(payload), [])
        # Another benefit under the SAME law/article must not be mixed in.
        unrelated = copy.deepcopy(service)
        unrelated["service_id"] = "OTHER"
        unrelated["fields"]["선정기준"] = "별도주택급여 소득 50만원 이하"
        state["public_services"]["OTHER"] = unrelated
        discover_public_service_leads(state, [event])
        self.assertEqual(event["public_service_lead_count"], 1)
        # Same criterion label without an exact common legal article is not a link.
        state["public_services"]["ANNUAL"]["regulatory_basis"] = (
            "「가상 공공서비스 운영법」 제9조")
        discover_public_service_leads(state, [event])
        self.assertEqual(event["public_service_lead_count"], 0)

    def test_official_parenthesized_citation_and_alternate_legal_brackets_match(self):
        service = normalize_record(record("RAW"))
        service["service_name"] = "생활안정급여"
        service["regulatory_basis"] = "가상 공공서비스 운영법(제12조)"
        service["fields"] = {"지원내용": "초등학생 502,000원"}
        change = {"document_title": "2027년 생활안정급여 선정기준",
                  "document_id": "RAW-DOC", "article": "첨부 전문",
                  "before": "「가상 공공서비스 운영법」 제6조 및 제12조제1항 초등학생 502,000원",
                  "after": "｢가상 공공서비스 운영법｣ 제6조 및 제12조제1항 초등학생 513,000원"}
        event = {"id": "RAW-EVENT", "changes": [change]}
        result = discover_public_service_leads({"public_services": {"RAW": service}}, [event])
        self.assertEqual(event["public_service_lead_count"], 1)
        self.assertEqual(event["public_service_leads"][0]["review_targets"][0]["new_legal_value"],
                         "513,000원")
        self.assertEqual(validate_public_service_candidates({"events": [event],
                         "public_service_proofs": result["proofs"]}), [])

    def test_explicit_defined_criterion_can_flow_to_a_different_entitlement_article(self):
        service = normalize_record(record("DEFINITION"))
        service["regulatory_basis"] = "가상 공공서비스 운영법(제12조)"
        service["fields"] = {"선정기준": "생활안정기준소득의 50% 이하"}
        change = {"document_title": "생활안정기준소득 및 급여 선정기준",
                  "article": "첨부 전문", "document_id": "DEF",
                  "before": "가상 공공서비스 운영법 제2조에 따른 ‘생활안정기준소득’을 100만원으로 정한다.",
                  "after": "「가상 공공서비스 운영법」 제2조에 따른 “생활안정기준소득”을 120만원으로 정한다."}
        event = {"id": "DEF-E", "changes": [change]}
        result = discover_public_service_leads({"public_services": {"DEFINITION": service}}, [event])
        self.assertEqual(event["public_service_lead_count"], 1)
        self.assertEqual(event["public_service_leads"][0]["match_tier"],
                         "official_defined_criterion_and_parent_law")
        self.assertEqual(validate_public_service_candidates({"events": [event],
                         "public_service_proofs": result["proofs"]}), [])
        service["fields"]["선정기준"] = "다른급여의 50% 이하"
        discover_public_service_leads({"public_services": {"DEFINITION": service}}, [event])
        self.assertEqual(event["public_service_lead_count"], 0)

    def test_application_procedure_is_a_distinct_public_service_review_target(self):
        raw=record("S888")
        raw["선정기준"]=""
        raw["지원대상"]=""
        raw["지원내용"]=""
        raw["신청방법"]="가상 기관에 방문 신청"
        state={"public_services":{"S888":normalize_record(raw)}}
        event=policy_event()
        discover_public_service_leads(state,[event])
        target=event["public_service_leads"][0]["review_targets"][0]
        self.assertEqual(target["field"],"신청방법")
        self.assertEqual(target["source_excerpt"],"가상 기관에 방문 신청")
        self.assertEqual(target["old_value"],"")
        self.assertIn("제3조",target["review_question"])

    def test_multirow_official_annex_values_create_specific_program_review(self):
        from policy_domino.gov24 import changed_numeric_pairs,criteria_to_review
        change={"article":"별표 1",
                "before":"4인 가구 지원기준 100만원, 5인 가구 지원기준 150만원.",
                "after":"4인 가구 지원기준 120만원, 5인 가구 지원기준 180만원."}
        pairs=changed_numeric_pairs(change)
        self.assertEqual(len(pairs),2)
        self.assertIn(("100만원","120만원"),pairs)
        entry=normalize_record(record("S2027"))
        entry["fields"]["선정기준"]="4인 가구 지원기준 100만원"
        item=criteria_to_review(entry,change,"official_clause_citation")[0]
        self.assertEqual(item["field"],"선정기준")
        self.assertEqual(item["old_value"],"100만원")
        self.assertEqual(item["new_legal_value"],"120만원")
        self.assertIn("120만원",item["review_question"])

    def test_intact_named_rows_survive_removal_of_a_different_numeric_formula(self):
        from policy_domino.gov24 import changed_numeric_pairs, criteria_to_review
        change = {"article": "첨부 전문",
                  "before": "추가 가구원 100원. 초등학생 502,000원 중학생 699,000원 고등학생 860,000원",
                  "after": "초등학생 513,000원 중학생 714,000원 고등학생 945,000원"}
        pairs = changed_numeric_pairs(change)
        self.assertEqual(set(pairs), {("502,000원", "513,000원"),
                         ("699,000원", "714,000원"), ("860,000원", "945,000원")})
        service = normalize_record(record("ROWS"))
        service["fields"] = {"지원내용": "초등학생 502,000원 중학생 699,000원 고등학생 860,000원"}
        targets = criteria_to_review(service, change, "official_shared_clause_and_criterion")
        self.assertEqual(len(targets), 3)
        self.assertEqual({t["new_legal_value"] for t in targets},
                         {"513,000원", "714,000원", "945,000원"})

    def test_ambiguous_amount_alignment_does_not_claim_specific_threshold(self):
        from policy_domino.gov24 import changed_numeric_pairs
        before={"article":"별표 1","before":"가 기준은 100만원, 나 기준은 150만원",
                "after":"나 기준 180만원, 가 기준 120만원"}
        pairs=changed_numeric_pairs(before)
        self.assertNotIn(("100만원","180만원"),pairs)
        self.assertNotIn(("150만원","120만원"),pairs)

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
