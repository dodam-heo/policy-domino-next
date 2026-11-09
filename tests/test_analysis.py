import unittest
from policy_domino.analysis import compare, connect_changes, extract_references, review_topics
from policy_domino.core import document_key
from policy_domino.parser import take


class CausalityTests(unittest.TestCase):
    def setUp(self):
        self.rec = {"id": document_key("admrul","1","12"),"source":"admrul",
                    "title":"가상지원 기준고시","url":"https://www.law.go.kr/x",
                    "published_at":"2026-11-09","ministry":"가상부처"}

    def test_before_after_actual_text_and_amounts(self):
        prior={"status":"extracted","clauses":{"제3조":take("제3조(기준) 지원액은 30만원이다.")}}
        current={"status":"extracted","clauses":{"제3조":take("제3조(기준) 지원액은 40만원이다.")}}
        result=compare(prior,current,self.rec)
        self.assertEqual(result["status"],"compared")
        self.assertEqual(len(result["changes"]),1)
        self.assertEqual(result["changes"][0]["old_values"],["30만원"])
        self.assertEqual(result["changes"][0]["new_values"],["40만원"])
        self.assertIn("제3조",review_topics(result["changes"])[0]["review"])

    def test_unmatched_articles_are_never_fake_deletions(self):
        prior={"status":"extracted","clauses":{"제3조":take("기준 문구")}}
        current={"status":"partial","clauses":{"제4조":take("다른 문구")}}
        result=compare(prior,current,self.rec)
        self.assertEqual(result["status"],"partial_unresolved")
        self.assertFalse(result["changes"])
        self.assertEqual(len(result["excluded"]),2)

    def test_truncated_body_never_claims_real_change(self):
        prior={"status":"partial","clauses":{"제3조":take("A"*16000)}}
        current={"status":"extracted","clauses":{"제3조":take("B"*200)}}
        result=compare(prior,current,self.rec)
        self.assertFalse(result["changes"])
        self.assertEqual(result["status"],"partial_unresolved")

    def test_direct_actor_review_is_derived_from_changed_clause_only(self):
        from policy_domino.analysis import direct_actor_reviews
        change={"article":"제3조","category":"금액·비율",
                "before":"제3조(지원) 가상지원청장은 20만원을 지급한다.",
                "after":"제3조(지원) 가상지원청장은 30만원을 지급한다.",
                "source_url":"https://www.law.go.kr/가상"}
        rows=direct_actor_reviews([change])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["actor"],"가상지원청장")
        self.assertFalse(rows[0]["operational_program_verified"])
        self.assertFalse(rows[0]["required_action_verified"])
        self.assertEqual(direct_actor_reviews([{**change,
            "after":"제3조(지원) 신청인은 30만원을 받는다."}]),[])

    def test_verified_reference_requires_exact_changed_article(self):
        changed_id=self.rec["id"]
        referring_id=document_key("ordin","3","31")
        consumer={ "id":referring_id,"source":"ordin",
            "title":"가상 지역지원 조례","published_at":"2026-11-09",
            "url":"https://www.law.go.kr/y","ministry":"가상지자체"}
        findings={changed_id:{"changes":[{"article":"제3조"}]}}
        versions={referring_id:{"clauses":{
            "제5조":take("이 조례는 「가상지원 기준고시」 제3조를 적용한다."),
            "제7조":take("「가상지원 기준고시」 제4조는 변경과 무관하다.")}}}
        docs={changed_id:self.rec,referring_id:consumer}
        edges=connect_changes(findings,versions,docs)
        self.assertEqual(len(edges),1)
        self.assertEqual(edges[0]["changed_article"],"제3조")
        self.assertEqual(edges[0]["referencing_title"],"가상 지역지원 조례")
        self.assertFalse(edges[0]["required_action_verified"])
        self.assertFalse(edges[0]["operational_program_verified"])

    def test_named_actor_in_dependent_rule_yields_grounded_review_only(self):
        from policy_domino.analysis import cross_document_actor_reviews
        change={"article":"제3조","before":"지원액 20만원",
                "after":"지원액 30만원"}
        edges=[{"source_event_id":"event1","referencing_document_id":"rule1",
                "referencing_article":"제7조","changed_article":"제3조",
                "explicit_actors":["가상지원청장"],"referencing_title":"가상 조례",
                "reference_quote":"제3조에 따라 처리한다",
                "referencing_source_url":"https://www.law.go.kr/ref"}]
        candidates=cross_document_actor_reviews(edges,{"event1":{"changes":[change]}})
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]["actor"],"가상지원청장")
        self.assertEqual(candidates[0]["target_location"],"제7조")
        self.assertFalse(candidates[0]["operational_program_verified"])
        self.assertFalse(candidates[0]["required_action_verified"])
        self.assertEqual(cross_document_actor_reviews(
            [{**edges[0],"explicit_actors":[]}],{"event1":{"changes":[change]}}),[])

    def test_older_subordinate_regulation_may_reference_changed_parent(self):
        changed=self.rec
        old_id=document_key("ordin","101","104")
        older={"id":old_id,"source":"ordin","title":"가상 지역 기준조례",
               "published_at":"2025-03-01","url":"https://www.law.go.kr/older",
               "ministry":"가상 지방기관"}
        refs=connect_changes(
            {changed["id"]:{"changes":[{"article":"제3조"}]}},
            {old_id:{"clauses":{"제5조":take(
                "「가상지원 기준고시」 제3조에 따른 금액을 적용한다.")}}},
            {changed["id"]:changed,old_id:older})
        self.assertEqual(len(refs),1)
        self.assertTrue(refs[0]["reference_predates_amendment"])
        self.assertFalse(refs[0]["required_action_verified"])

    def test_title_only_mention_does_not_prove_article(self):
        extracted=extract_references("「가상지원 기준고시」를 준용한다.")
        self.assertEqual(extracted[0]["article"],"")
        self.assertEqual(connect_changes(
            {self.rec["id"]:{"changes":[{"article":"제3조"}]}},
            {document_key("law","2","2"):{"clauses":{
                "제1조":take("「가상지원 기준고시」를 준용한다.")}}},
            {self.rec["id"]:self.rec,
             document_key("law","2","2"):{"id":document_key("law","2","2"),
              "source":"law","title":"가상 법","published_at":"2026-11-09",
              "ministry":"가상청","url":"https://www.law.go.kr/z"}}),[])


if __name__=="__main__":
    unittest.main()
