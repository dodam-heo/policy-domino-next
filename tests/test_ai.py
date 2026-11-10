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
    return {"status": "completed", "output": [
        {"type": "message", "content": [
            {"type": "output_text", "text": json.dumps(payload, ensure_ascii=False)}
        ]}
    ]}


class AIIntegrationTests(unittest.TestCase):
    def test_only_verified_changed_text_and_programs_in_packet(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        self.assertEqual(len(packet["changes"]), 1)
        self.assertEqual(len(packet["programs"]), 1)
        self.assertEqual(packet["programs"][0]["agency"], "가상장학공사")
        self.assertEqual(packet["programs"][0]["article"], "제3조")
        self.assertIsNone(source_packet(state, "unknown", links))

    def test_real_responses_request_is_structured_not_keyword_matching(self):
        state, links = state_and_links()
        packet = source_packet(state, "e1", links)
        requests = []
        def transport(body):
            requests.append(json.loads(body))
            return fake_api_return(proposal(packet))
        result = call_model(packet, key="TEST_INJECTED_ONLY", transport=transport)
        self.assertEqual(result["change_reviews"][0]["after_quote"], "40만원")
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["model"], "gpt-4.1-mini")
        self.assertEqual(requests[0]["text"]["format"]["type"], "json_schema")
        self.assertTrue(requests[0]["text"]["format"]["strict"])
        self.assertEqual(requests[0]["store"], False)
        self.assertNotIn("TEST_INJECTED_ONLY", json.dumps(requests[0]))
        self.assertNotIn("OPENAI_API_KEY", json.dumps(state))

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


if __name__ == "__main__":
    unittest.main()
