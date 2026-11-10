"""Real LLM request contract and evidence-first output regression tests.

All model responses are transport fixtures; the test suite never spends API
tokens and never pretends a fixture was a live AI inference.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from policy_domino.ai import (
    AIAnalysisError, analyze_batch, call_model, publishable_draft,
    source_fingerprint, source_packet, validate_draft)
from policy_domino.core import new_state
from policy_domino.pipeline import render
from policy_domino.programs import ingest_programs, discover_program_links

TITLE = "가상 학비지원법"
SOURCE_URL = "https://www.law.go.kr/법령/가상학비지원법"
PROGRAM_URL = ("https://www.alioplus.go.kr/business/bsnDetail.do?"
               "bsnSeq=814&bsnTyp=DET")


def state_and_links(with_program: bool = True):
    state = new_state()
    state["documents"]["e1"] = {
        "id": "e1", "source": "law", "stable_id": "100", "serial": "110",
        "title": TITLE, "ministry": "가상부", "published_at": "2026-11-09",
        "kind": "법령", "revision": "일부개정", "url": SOURCE_URL}
    state["findings"]["e1"] = {
        "status": "compared",
        "changes": [{
            "article": "제3조", "before": "제3조 지급액은 30만원으로 한다.",
            "after": "제3조 지급액은 40만원으로 한다.",
            "actual_edits": [{"old_excerpt": "30만원", "new_excerpt": "40만원"}],
            "source_url": SOURCE_URL, "evidence": {
                "old_body_sha256": "official-a", "new_body_sha256": "official-b"}
        }]}
    if with_program:
        ingest_programs(state, [{
            "agency": "가상장학공사", "name": "교육비 지원운영 사업",
            "description": ("이 사업은 「가상 학비지원법」 제3조에 따른 "
                            "소득기준으로 30만원을 지원하며 해당 기준을 안내합니다."),
            "url": PROGRAM_URL
        }])
    return state, discover_program_links(state, [])


def proposal(packet):
    data = {
        "change_reviews": [{
            "article": "제3조", "summary": "지급액이 30만원에서 40만원으로 변경",
            "before_quote": "30만원", "after_quote": "40만원",
            "review_question": "관련 지원사업 지급액의 적용 기준을 확인할 필요가 있는가?"
        }],
        "program_reviews": []
    }
    if packet["programs"]:
        p = packet["programs"][0]
        data["program_reviews"] = [{
            "program_id": p["program_id"], "article": p["article"],
            "agency": p["agency"],
            "program_quote": "「가상 학비지원법」 제3조",
            "reason": "사업 안내의 조문 인용이 변경된 지급액 기준과 연결될 가능성",
            "review_question": "사업 안내의 지급액 및 적용 시점을 확인해야 하는가?"
        }]
    return data


def fake_api_return(payload):
    return {"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}}]}


class AIIntegrationTests(unittest.TestCase):
    def test_only_verified_changed_text_and_programs_in_packet(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        self.assertEqual(len(packet["changes"]), 1)
        self.assertEqual(len(packet["programs"]), 1)
        self.assertEqual(packet["programs"][0]["agency"], "가상장학공사")
        self.assertEqual(packet["programs"][0]["article"], "제3조")
        self.assertIsNone(source_packet(state, "unknown", links))

    def test_citing_public_rule_issuer_is_available_for_ai_work_review(self):
        state, links = state_and_links(with_program=False)
        state["documents"]["r1"] = {
            "id": "r1", "source": "ordin", "reference_only": True,
            "title": "가상 복지심사 운영조례",
            "ministry": "가상시청",
            "url": "https://www.law.go.kr/자치법규/가상복지심사운영조례",
        }
        edge = {
            "source_event_id": "e1", "changed_article": "제3조",
            "referencing_document_id": "r1",
            "referencing_title": "가상 복지심사 운영조례",
            "referencing_article": "제7조",
            "reference_quote": "「가상 학비지원법」 제3조를 적용한다.",
            "referencing_source_url":
                "https://www.law.go.kr/자치법규/가상복지심사운영조례",
            "publishing_agency": "가상시청",
            "relationship": "verified_exact_article_citation",
        }
        packet=source_packet(state,"e1",links,relationships=[edge])
        reviews=packet.get("institutions",[])
        self.assertEqual(len(reviews),1)
        self.assertEqual(reviews[0]["agency"],"가상시청")
        self.assertEqual(reviews[0]["tier"],"verified_official_rule_citation")
        base=proposal(packet)
        base["institution_reviews"]=[{
            "review_id":reviews[0]["review_id"],
            "article":"제3조", "agency":"가상시청",
            "basis_quote":reviews[0]["basis_quote"],
            "work_impact":"공식 심사 운영조례의 조문 인용 기준을 점검합니다.",
            "review_question":"기존 제7조 업무 기준을 조정할 필요가 있는가?",
        }]
        result=analyze_batch(state,links,key="TEST",limit=1,
            relationships=[edge],transport=lambda _:fake_api_return(base))
        self.assertEqual(result["generated"],1)
        output=publishable_draft(state,"e1",links,relationships=[edge])
        self.assertEqual(output["institution_reviews"][0]["agency"],"가상시청")
        self.assertFalse(output["required_action_verified"])

    def test_source_verified_institution_review_is_model_bound(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        self.assertEqual(len(packet["institutions"]), 1)
        proof = packet["institutions"][0]
        self.assertEqual(proof["agency"], "가상장학공사")
        draft = proposal(packet)
        draft["institution_reviews"] = [{
            "review_id": proof["review_id"],
            "article": proof["article"],
            "agency": proof["agency"],
            "basis_quote": proof["basis_quote"][:70],
            "work_impact": "교육비 지원운영 사업의 산정 기준이 달라지는지 검토합니다.",
            "review_question": "공식 사업 운영 기준의 변경 전후를 대조해야 하는가?",
        }]
        validated = validate_draft(packet, draft)
        self.assertEqual(len(validated["institution_reviews"]), 1)
        self.assertEqual(validated["institution_reviews"][0]["review_id"],
                         proof["review_id"])
        wrong = json.loads(json.dumps(draft, ensure_ascii=False))
        wrong["institution_reviews"][0]["agency"] = "출처없는기관"
        with self.assertRaises(AIAnalysisError):
            validate_draft(packet, wrong)
        wrong = json.loads(json.dumps(draft, ensure_ascii=False))
        wrong["institution_reviews"][0]["basis_quote"] = "공식 문서에 없는 구절"
        with self.assertRaises(AIAnalysisError):
            validate_draft(packet, wrong)
        wrong = json.loads(json.dumps(draft, ensure_ascii=False))
        wrong["institution_reviews"][0]["review_id"] = "forged-review"
        with self.assertRaises(AIAnalysisError):
            validate_draft(packet, wrong)

    def test_gemini_request_is_structured_not_keyword_matching(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        requests = []
        def transport(body):
            requests.append(json.loads(body))
            return fake_api_return(proposal(packet))
        result = call_model(packet, key="TEST_INJECTED_ONLY", transport=transport)
        self.assertEqual(result["change_reviews"][0]["after_quote"], "40만원")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(requests[0]["generationConfig"]["responseSchema"]["type"], "object")
        self.assertEqual(requests[0]["generationConfig"]["maxOutputTokens"], 4096)
        self.assertIn("systemInstruction", requests[0])
        self.assertNotIn("additionalProperties", json.dumps(requests[0]))
        self.assertNotIn("TEST_INJECTED_ONLY", json.dumps(requests[0]))
        self.assertNotIn("GEMINI_API_KEY", json.dumps(state))

    def test_grounded_response_accepts_questions_not_actions(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        validated = validate_draft(packet, proposal(packet))
        self.assertEqual(len(validated["program_reviews"]), 1)
        self.assertIn("확인", validated["program_reviews"][0]["review_question"])

    def test_forged_quote_rejected(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        altered = proposal(packet)
        altered["change_reviews"][0]["after_quote"] = "500만원"
        with self.assertRaises(AIAnalysisError):
            validate_draft(packet, altered)
        altered = proposal(packet)
        altered["program_reviews"][0]["program_quote"] = "미존재 사업 시행규칙"
        with self.assertRaises(AIAnalysisError):
            validate_draft(packet, altered)

    def test_unverified_agency_and_program_id_rejected(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        altered = proposal(packet)
        altered["program_reviews"][0]["agency"] = "임의기관"
        with self.assertRaises(AIAnalysisError):
            validate_draft(packet, altered)
        altered = proposal(packet)
        altered["program_reviews"][0]["program_id"] = "made-up-id"
        with self.assertRaises(AIAnalysisError):
            validate_draft(packet, altered)

    def test_unconfigured_state_never_invokes_remote_model(self):
        state, links = state_and_links()
        with patch.dict("os.environ", {}, clear=True):
            report = analyze_batch(state, links)
        self.assertEqual(report["status"], "not_configured")
        self.assertNotIn("e1", state["ai_reviews"])
        self.assertEqual(state["ai_status"], "not_configured")

    def test_generated_draft_persists_and_matches_evidence_hash(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        hits = []
        def transport(body):
            hits.append(body)
            return fake_api_return(proposal(packet))
        status = analyze_batch(state, links, key="TEST", transport=transport)
        self.assertEqual(status["status"], "generated")
        self.assertEqual(status["generated"], 1)
        self.assertEqual(len(hits), 1)
        entry = publishable_draft(state, "e1", links)
        self.assertEqual(entry["source_sha256"], source_fingerprint(packet))
        self.assertFalse(entry["required_action_verified"])
        status = analyze_batch(state, links, key="TEST", transport=transport)
        self.assertEqual(status["generated"], 0)
        self.assertEqual(len(hits), 1)

    def test_updated_official_text_invalidates_old_ai_claim(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        analyze_batch(state, links, key="TEST", transport=lambda _: fake_api_return(proposal(packet)))
        state["findings"]["e1"]["changes"][0]["after"] = "제3조 지급액은 50만원으로 한다."
        self.assertIsNone(publishable_draft(state, "e1", links))

    def test_model_errored_or_unknown_articles_are_not_published(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        wrong = proposal(packet)
        wrong["change_reviews"][0]["article"] = "제90조"
        status = analyze_batch(state, links, key="TEST",
                               transport=lambda _: fake_api_return(wrong))
        self.assertEqual(status["errors"], 1)
        self.assertIsNone(publishable_draft(state, "e1", links))
        with self.assertRaises(AIAnalysisError):
            call_model(packet, key="TEST", transport=lambda _: {
                "status": "incomplete", "output": []})

    def test_render_retains_both_verified_dependency_and_ai_proposal(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        analyze_batch(state, links, key="TEST", transport=lambda _: fake_api_return(proposal(packet)))
        with tempfile.TemporaryDirectory() as tmp:
            data = render(state, Path(tmp) / "data.json")
        self.assertEqual(len(data["program_dependencies"]), 1)
        self.assertEqual(data["ai_status"], "generated")
        ai = data["documents"][0]["analysis"]["ai"]
        self.assertEqual(len(ai["change_reviews"]), 1)
        self.assertEqual(len(ai["program_reviews"]), 1)
        self.assertFalse(ai["required_action_verified"])


    def test_failed_attempts_are_capped_and_reported(self):
        state, links = state_and_links()
        state["documents"]["e2"] = dict(state["documents"]["e1"], id="e2")
        state["findings"]["e2"] = state["findings"]["e1"]
        hits = []
        def transport(body):
            hits.append(body)
            return {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": []}}]}
        report = analyze_batch(state, links, key="TEST", limit=2, transport=transport)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["attempted"], 2)
        self.assertEqual(report["errors"], 2)
        self.assertEqual(len(hits), 2)
        self.assertEqual(state["ai_run"]["status"], "failed")

    def test_quota_limit_stops_more_calls(self):
        from policy_domino.ai import AIRequestError
        state, links = state_and_links()
        state["documents"]["e2"] = dict(state["documents"]["e1"], id="e2")
        state["findings"]["e2"] = state["findings"]["e1"]
        hits = []
        def transport(body):
            hits.append(body)
            raise AIRequestError("http_429_rate_or_quota", blocking=True)
        report = analyze_batch(state, links, key="TEST", limit=2, transport=transport)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["error_codes"], {"http_429_rate_or_quota": 1})
        self.assertEqual(len(hits), 1)

    def test_no_eligible_change_does_not_call_api(self):
        state = new_state()
        report = analyze_batch(state, [], key="TEST",
                               transport=lambda _: self.fail("unexpected Gemini call"))
        self.assertEqual(report["status"], "no_eligible_changes")
        self.assertEqual(report["attempted"], 0)

    def test_empty_ai_review_is_rejected(self):
        state, links = state_and_links()
        report = analyze_batch(state, links, key="TEST",
                               transport=lambda _: fake_api_return(
                                   {"change_reviews": [], "program_reviews": []}))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["generated"], 0)



    def test_transient_503_retries_once_inside_shared_api_budget(self):
        from policy_domino.ai import AIRequestError
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        calls = []
        def transport(body):
            calls.append(body)
            if len(calls) == 1:
                raise AIRequestError("http_503_overloaded")
            return fake_api_return(proposal(packet))
        report = analyze_batch(state, links, key="TEST", limit=2, transport=transport)
        self.assertEqual(report["attempted"], 2)
        self.assertEqual(report["retries"], 1)
        self.assertEqual(report["retry_error_codes"], {"http_503_overloaded": 1})
        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["generated"], 1)
        self.assertEqual(report["status"], "generated")
        self.assertEqual(len(calls), 2)
        self.assertIsNotNone(publishable_draft(state, "e1", links))

    def test_partial_generation_is_not_misclassified_as_total_failure(self):
        from policy_domino.ai import AIRequestError, assess_ai_run
        state, links = state_and_links()
        state["documents"]["e2"] = dict(state["documents"]["e1"], id="e2")
        state["findings"]["e2"] = state["findings"]["e1"]
        packet = source_packet(state, "e1", links)
        calls = []
        def transport(body):
            calls.append(body)
            if len(calls) == 2:
                raise AIRequestError("http_503_overloaded")
            return fake_api_return(proposal(packet))
        report = analyze_batch(state, links, key="TEST", limit=2, transport=transport)
        self.assertEqual(report["attempted"], 2)
        self.assertEqual(report["generated"], 1)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["status"], "partial_generated")
        self.assertEqual(report["error_codes"], {"http_503_overloaded": 1})
        self.assertEqual(assess_ai_run(report), "warning")
        report["error_codes"] = {"invalid_evidence": 1}
        self.assertEqual(assess_ai_run(report), "error")
        self.assertIsNotNone(publishable_draft(state, "e1", links))

    def test_only_transient_full_failures_are_operational_warnings(self):
        from policy_domino.ai import assess_ai_run
        transient = {"status": "failed", "generated": 0, "errors": 1,
                     "error_codes": {"http_503_overloaded": 1}}
        self.assertEqual(assess_ai_run(transient), "warning")
        transient["error_codes"] = {"invalid_model_output": 1}
        self.assertEqual(assess_ai_run(transient), "error")
        transient["error_codes"] = {"http_403_forbidden": 1}
        self.assertEqual(assess_ai_run(transient), "error")
        transient["status"] = "not_configured"
        self.assertEqual(assess_ai_run(transient), "error")

    def test_verified_events_accumulate_across_runs_without_example_shortcuts(self):
        state, links = state_and_links(with_program=False)
        for event_id in ("e2", "e3"):
            state["documents"][event_id] = dict(state["documents"]["e1"], id=event_id)
            state["findings"][event_id] = state["findings"]["e1"]
        calls = []
        def transport(body):
            calls.append(body)
            return fake_api_return(proposal(source_packet(state, "e1", links)))
        for step in range(3):
            report = analyze_batch(state, links, key="TEST", limit=1, transport=transport)
            self.assertEqual(report["generated"], 1)
            self.assertEqual(len(state["ai_reviews"]), step + 1)
        self.assertEqual(len(calls), 3)
        report = analyze_batch(state, links, key="TEST", limit=1, transport=transport)
        self.assertEqual(report["status"], "cached")
        self.assertEqual(report["attempted"], 0)



    def test_valid_article_is_kept_when_sibling_quote_is_fabricated(self):
        state, links = state_and_links(with_program=False)
        first = state["findings"]["e1"]["changes"][0]
        state["findings"]["e1"]["changes"].append({
            **first, "article": "제4조",
            "before": "제4조 지급액은 30만원으로 한다.",
            "after": "제4조 지급액은 40만원으로 한다."})
        def transport(body):
            return fake_api_return({
                "change_reviews": [
                    {"article": "제3조",
                     "summary": "지급액 기준 변경을 검토합니다.",
                     "before_quote": "30만원", "after_quote": "40만원",
                     "review_question": "기존 지원 기준을 대조해야 하는가?"},
                    {"article": "제4조",
                     "summary": "지급액 기준 변경을 검토합니다.",
                     "before_quote": "출처에 없는 금액",
                     "after_quote": "40만원",
                     "review_question": "기존 지원 기준을 대조해야 하는가?"},
                ], "program_reviews": [],
                "institution_reviews": [],
            })
        report = analyze_batch(state, links, key="TEST", limit=1, transport=transport)
        self.assertEqual(report["generated"], 1)
        self.assertEqual(report["salvaged_batches"], 1)
        self.assertEqual(report["discarded_model_rows"], 1)
        review = publishable_draft(state, "e1", links)
        self.assertEqual(review["reviewed_articles"], 1)
        self.assertEqual(review["verified_articles"], 2)
        self.assertEqual(review["coverage"], "partial")
        self.assertEqual(review["change_reviews"][0]["article"], "제3조")

    def test_salvage_never_accepts_a_forged_institution(self):
        state, links = state_and_links(with_program=True)
        packet = source_packet(state, "e1", links)
        bad = proposal(packet)
        bad["institution_reviews"] = [{
            "review_id": "invented", "article": "제3조",
            "agency": "임의 기관", "basis_quote": "근거가 없는 말",
            "work_impact": "임의 기준을 변경해야 합니다.",
            "review_question": "임의 시스템을 바꿔야 하는가?",
        }]
        report = analyze_batch(state, links, key="TEST",
                               transport=lambda _: fake_api_return(bad))
        self.assertEqual(report["generated"], 1)
        self.assertEqual(report["discarded_model_rows"], 1)
        result = publishable_draft(state, "e1", links)
        self.assertEqual(result["institution_reviews"], [])
        self.assertEqual(result["change_reviews"][0]["article"], "제3조")

    def test_each_changed_clause_is_reviewed_in_three_article_batches(self):
        state, links = state_and_links(with_program=False)
        first = state["findings"]["e1"]["changes"][0]
        state["findings"]["e1"]["changes"] = [
            {**first, "article": f"제{i}조",
             "before": f"제{i}조 지급액은 30만원으로 한다.",
             "after": f"제{i}조 지급액은 40만원으로 한다."}
            for i in range(1, 8)
        ]
        seen = []
        def transport(body):
            request = json.loads(body)
            packet = json.loads(request["contents"][0]["parts"][0]["text"].split("\n",1)[1])
            seen.extend(x["article"] for x in packet["changes"])
            return fake_api_return({
                "change_reviews": [{
                    "article": change["article"],
                    "summary": "지급액이 30만원에서 40만원으로 변경됐습니다.",
                    "before_quote": "30만원", "after_quote": "40만원",
                    "review_question": "실제 급여 산정 기준을 점검해야 하는가?"
                } for change in packet["changes"]],
                "program_reviews": [],
                "institution_reviews": [],
            })
        first_run = analyze_batch(state, links, key="TEST", limit=1,
                                  transport=transport)
        self.assertEqual(first_run["eligible_total"], 3)
        self.assertEqual(first_run["generated"], 1)
        partial = publishable_draft(state, "e1", links)
        self.assertEqual(partial["coverage"], "partial")
        self.assertEqual(partial["reviewed_articles"], 3)
        self.assertEqual(partial["verified_articles"], 7)
        second_run = analyze_batch(state, links, key="TEST", limit=1,
                                   transport=transport)
        self.assertEqual(second_run["generated"], 1)
        third_run = analyze_batch(state, links, key="TEST", limit=1,
                                  transport=transport)
        self.assertEqual(third_run["generated"], 1)
        completed = publishable_draft(state, "e1", links)
        self.assertEqual(completed["coverage"], "complete")
        self.assertEqual(completed["reviewed_articles"], 7)
        self.assertEqual(len(completed["change_reviews"]), 7)
        self.assertEqual(len(set(seen)), 7)
        fourth_run = analyze_batch(state, links, key="TEST", limit=1,
                                   transport=transport)
        self.assertEqual(fourth_run["attempted"], 0)
        self.assertEqual(fourth_run["cached"], 3)

    def test_default_budget_analyzes_entire_verified_queue_incrementally(self):
        from policy_domino.ai import DEFAULT_REQUEST_BUDGET
        self.assertEqual(DEFAULT_REQUEST_BUDGET, 24)
        state, links = state_and_links(with_program=False)
        for i in range(2, 31):
            event_id = f"e{i}"
            state["documents"][event_id] = dict(
                state["documents"]["e1"], id=event_id)
            state["findings"][event_id] = state["findings"]["e1"]

        requests = []
        def transport(body):
            requests.append(body)
            return fake_api_return(proposal(source_packet(state, "e1", links)))

        first = analyze_batch(state, links, key="TEST", transport=transport)
        self.assertEqual(first["eligible_total"], 30)
        self.assertEqual(first["request_budget"], 24)
        self.assertEqual(first["attempted"], 24)
        self.assertEqual(first["generated"], 24)
        self.assertEqual(first["analyzed_total"], 24)
        self.assertEqual(first["pending_total"], 6)
        self.assertEqual(first["stopped_reason"], "request_budget")
        second = analyze_batch(state, links, key="TEST", transport=transport)
        self.assertEqual(second["generated"], 6)
        self.assertEqual(second["cached"], 24)
        self.assertEqual(second["analyzed_total"], 30)
        self.assertEqual(second["pending_total"], 0)
        third = analyze_batch(state, links, key="TEST", transport=transport)
        self.assertEqual(third["attempted"], 0)
        self.assertEqual(third["cached"], 30)
        self.assertEqual(third["status"], "cached")
        self.assertEqual(len(requests), 30)

    def test_quota_pauses_pending_queue_without_erasing_completed_results(self):
        from policy_domino.ai import AIRequestError, assess_ai_run
        state, links = state_and_links(with_program=False)
        state["documents"]["e2"] = dict(state["documents"]["e1"], id="e2")
        state["findings"]["e2"] = state["findings"]["e1"]
        first = analyze_batch(state, links, key="TEST", limit=1,
            transport=lambda _: fake_api_return(
                proposal(source_packet(state, "e1", links))))
        self.assertEqual(first["generated"], 1)
        report = analyze_batch(state, links, key="TEST", limit=24,
            transport=lambda _: (_ for _ in ()).throw(
                AIRequestError("http_429_rate_or_quota", blocking=True)))
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["stopped_reason"], "quota_paused")
        self.assertEqual(report["cached"], 1)
        self.assertEqual(report["pending_total"], 1)
        self.assertEqual(assess_ai_run(report), "warning")
        self.assertEqual(len(state["ai_reviews"]), 1)

    def test_verified_program_evidence_takes_priority_without_hardcoded_event(self):
        state, links = state_and_links()
        state["documents"]["older"] = dict(
            state["documents"]["e1"], id="older", published_at="2026-11-01")
        state["findings"]["older"] = state["findings"]["e1"]
        moved = [dict(dep, source_event_id="older") for dep in links]
        state["documents"]["e1"]["published_at"] = "2026-11-10"
        done = []
        def transport(body):
            request = json.loads(body)
            packet = json.loads(request["contents"][0]["parts"][0]["text"].split("\n",1)[1])
            done.append(packet["event_id"])
            return fake_api_return(proposal(packet))
        report = analyze_batch(state, moved, key="TEST", limit=1, transport=transport)
        self.assertEqual(report["generated"], 1)
        self.assertEqual(done, ["older"])


if __name__ == "__main__":
    unittest.main()
