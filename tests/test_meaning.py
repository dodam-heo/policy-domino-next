"""Readable policy wording regressions: complete words, relevance and truthfulness."""
import unittest

from policy_domino.meaning import explain, event_headline, highlight_changes


def item(name, old, new):
    meaning = explain(old, new)
    return {
        "document_title": name,
        "article": "제3조",
        "meaning": meaning,
        "category": meaning["label"],
        "brief": meaning["description"],
        "actual_edits": [],
    }


class MeaningTests(unittest.TestCase):
    def test_amount_change_is_a_natural_sentence(self):
        result = explain("제3조 지원금액은 10만원으로 한다.",
                         "제3조 지원금액은 12만원으로 한다.")
        self.assertEqual(result["label"], "금액·수치 기준")
        self.assertIn("10만원", result["description"])
        self.assertIn("12만원", result["description"])
        self.assertNotIn("관련 변경 관련 변경", result["description"])
        self.assertIn("10만원", result["before"])
        self.assertIn("12만원", result["after"])

    def test_announcement_change_keeps_whole_korean_word(self):
        old = ("제53조 가상위원회는 인터넷 홈페이지 또는 "
               "「가상신문법」에 따른 일간신문에 공고한다.")
        new = "제53조 가상위원회는 인터넷 홈페이지에 공고한다."
        result = explain(old, new)
        self.assertEqual(result["label"], "공고·공표 방식")
        self.assertTrue(result["before"])
        self.assertTrue(result["after"])
        self.assertNotIn("관련 변경 ·", result["description"])
        self.assertTrue(result["priority"] > 0)

    def test_punctuation_and_spacing_are_not_a_major_policy_change(self):
        old = "제5조 관보 및 2개 이상의 일간신문에 공고한다."
        new = "제5조 관보, 2개 이상의 일간신문에 공고한다."
        result = explain(old, new)
        self.assertFalse(result["editorial"])
        self.assertNotEqual(result["label"], "그 밖의 조문 변경")
        only_typography = explain(
            "제5조 관보, 2개 이상의 일간신문에 공고한다.",
            "제5조 관보，2개 이상의 일간신문에 공고한다.")
        self.assertTrue(only_typography["editorial"])
        self.assertEqual(only_typography["label"], "띄어쓰기·표기 정비")

    def test_substantive_updates_win_over_formatting_and_diverse_categories(self):
        changes = [
            item("가상절차령", "제1조 신청인은 서류를 제출한다.",
                 "제1조 신청인은 서류를 제출한다，"),
            item("가상급여령", "제3조 지원금액은 10만원이다.",
                 "제3조 지원금액은 12만원이다."),
            item("가상운영령", "제4조 신문에 공고한다.",
                 "제4조 홈페이지에 공고한다."),
            item("가상급여시행령", "제7조 지원금액은 5만원이다.",
                 "제7조 지원금액은 8만원이다."),
        ]
        headline = event_headline(changes)
        self.assertIn("4개 조문 변경", headline)
        self.assertNotIn("그 밖의 조문 변경 관련 변경", headline)
        featured = highlight_changes(changes, limit=3)
        self.assertEqual(len(featured), 3)
        self.assertTrue(all(not c["meaning"]["editorial"] for c in featured))
        self.assertIn("공고·공표 방식", [x["meaning"]["label"] for x in featured])

    def test_unclassified_rule_still_has_intelligible_description(self):
        result = explain("제2조 필요한 조치는 A에 따른다.",
                         "제2조 필요한 조치는 B에 따른다.")
        self.assertTrue(result["description"].endswith("바뀌었습니다.") or
                        result["description"].endswith("확인하세요."))
        self.assertNotIn("그 밖의 조문 변경", result["description"])

    def test_no_early_100_character_chop_of_a_korean_legal_token(self):
        long_word = "가상복합지원자격심사위원회"
        before = "제3조 "+long_word+"에서 신문에 공고한다."
        after = "제3조 "+long_word+"에서 홈페이지에 공고한다."
        result = explain(before, after)
        self.assertNotIn("복합지원자격심사위원회에서 신", result["before"])
        self.assertTrue(result["before"])
        self.assertTrue(result["after"])


if __name__ == "__main__":
    unittest.main()
