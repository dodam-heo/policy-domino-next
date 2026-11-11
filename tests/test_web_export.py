"""Production list text must use quoted evidence, not generic fallback prose."""
import unittest
from policy_domino.web_export import _summary


def fixture():
    return {
        "id": "event-abc", "title": "가상 공공규정",
        "changes": [{
            "document_id": "doc-one", "article": "제7조",
            "brief": "추상적인 설명", "before": "신문에 의무적으로 공고한다.",
            "after": "홈페이지에 공고하며 필요시 신문을 병행한다.",
            "meaning": {"source_check_required": False},
        }],
        "highlights": [{"document_id": "doc-one", "article": "제7조"}],
        "ai_summaries": [{
            "document_id": "doc-one", "article": "제7조",
            "summary": "공고 방식이 신문 의무 게재에서 홈페이지 공고로 변경됐습니다.",
            "before_quote": "신문에 의무적으로 공고한다.",
            "after_quote": "홈페이지에 공고하며 필요시 신문을 병행한다.",
        }],
    }


class ListSummaryTests(unittest.TestCase):
    def test_quoted_ai_summary_used_in_listing(self):
        event = fixture()
        self.assertEqual(_summary(event)["list_brief"],
                         event["ai_summaries"][0]["summary"])

    def test_unmatched_or_stale_ai_quote_never_overrides_source(self):
        event = fixture()
        event["ai_summaries"][0]["before_quote"] = "원문에 없는 문구"
        self.assertEqual(_summary(event)["list_brief"], "추상적인 설명")

    def test_no_ai_uses_source_based_fallback(self):
        event = fixture()
        event["ai_summaries"] = []
        self.assertEqual(_summary(event)["list_brief"], "추상적인 설명")

    def test_incomplete_source_cannot_show_ai_as_confirmed(self):
        event = fixture()
        event["changes"][0]["meaning"]["source_check_required"] = True
        self.assertEqual(_summary(event)["list_brief"], "추상적인 설명")
