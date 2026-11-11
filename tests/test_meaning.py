"""Readable policy wording regressions: complete words, relevance and truthfulness."""
import unittest

from policy_domino.meaning import explain, event_headline, highlight_changes, focused_differences


def item(name, old, new):
    meaning = explain(old, new)
    return {
        "document_id": name,
        "document_title": name,
        "article": "제3조",
        "meaning": meaning,
        "category": meaning["label"],
        "brief": meaning["description"],
        "actual_edits": [],
    }


class MeaningTests(unittest.TestCase):
    def test_multiple_household_tables_align_only_by_section_identity(self):
        # Four distinct eligibility criteria share the exact same seven-column
        # layout; the old and new numbers must never cross table boundaries.
        old = (
            "1. 가상 기본생활 지원기준 구 분 1인가구 2인가구 "
            "금액(원/월) 100,000 200,000 * 다음 기준 "
            "2. 가상 주택이용 선정기준 구 분 1인가구 2인가구 "
            "금액(원/월) 300,000 400,000 * "
        )
        new = (
            "제4조(가상 주택이용 수급자 선정기준) 구 분 1인가구 2인가구 "
            "금액(원/월) 330,000 440,000 * 다음 기준 "
            "제3조(가상 기본생활 지원기준) 구 분 1인가구 2인가구 "
            "금액(원/월) 110,000 220,000 * "
        )
        from policy_domino.meaning import _currency_table_changes
        rows = _currency_table_changes(old, new)
        self.assertEqual(len(rows), 4)
        self.assertEqual([(x["before"], x["after"]) for x in rows],
                         [("100,000", "110,000"), ("200,000", "220,000"),
                          ("300,000", "330,000"), ("400,000", "440,000")])
        self.assertIn("기본생활", rows[0]["column"])
        self.assertIn("주택이용", rows[2]["column"])

    def test_ambiguous_duplicate_table_titles_never_pair_values(self):
        from policy_domino.meaning import _currency_table_changes
        old = ("1. 중복사업 선정기준 구 분 1인가구 2인가구 "
               "금액(원/월) 100,000 200,000 "
               "2. 중복사업 운영기준 구 분 1인가구 2인가구 "
               "금액(원/월) 300,000 400,000")
        new = ("제3조(중복사업 선정기준) 구 분 1인가구 2인가구 "
               "금액(원/월) 900,000 800,000 * 다음 기준 "
               "제4조(중복사업 운영기준) 구 분 1인가구 2인가구 "
               "금액(원/월) 700,000 600,000")
        self.assertEqual(_currency_table_changes(old, new), [])

    def test_household_table_amounts_take_priority_over_changed_year_headers(self):
        old = "2026년 고시 제1호 구 분 1인가구 2인가구 금액(원/월) 1,000,000 2,000,000 부칙"
        new = "2027년 고시 제2호 구 분 1인가구 2인가구 금액(원/월) 1,100,000 2,200,000 부칙"
        result = explain(old, new)
        self.assertEqual(result["change_kind"], "numeric")
        self.assertIn("2개 기준", result["description"])
        self.assertEqual(result["focus"][0]["before"]["changed"], "1,000,000")
        self.assertEqual(result["focus"][0]["after"]["changed"], "1,100,000")
        self.assertNotIn("2026", result["description"])
        from policy_domino.meaning import _currency_table_changes
        self.assertEqual(_currency_table_changes(old + old, new + new), [])
        self.assertEqual(_currency_table_changes(old, new.replace("1인가구 2인가구", "2인가구 1인가구")), [])

    def test_amount_change_is_a_natural_sentence(self):
        result = explain("제3조 지원금액은 10만원으로 한다.",
                         "제3조 지원금액은 12만원으로 한다.")
        self.assertEqual(result["label"], "금액·수치 기준")
        self.assertIn("10만원", result["description"])
        self.assertIn("12만원", result["description"])
        self.assertIn("12만원으로", result["description"])
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
        self.assertEqual(only_typography["label"], "표기 정비")

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
        self.assertIn("4개 조문에서 변경 확인", headline)
        self.assertNotIn("그 밖의 조문 변경 관련 변경", headline)
        featured = highlight_changes(changes, limit=3)
        self.assertEqual(len(featured), 3)
        self.assertTrue(all(not c["meaning"]["editorial"] for c in featured))
        self.assertIn("공고·공표 방식", [x["meaning"]["label"] for x in featured])

    def test_very_long_annex_uses_bounded_diff_and_keeps_real_change(self):
        shared = "관할 공공업무의 집행 기준과 절차를 확인한다. " * 700
        before = shared + "관보에 공고한다. " + shared
        after = shared + "인터넷 홈페이지에 공고한다. " + shared
        result = explain(before, after)
        self.assertEqual(result["label"], "공고·공표 방식")
        self.assertTrue(result["before"])
        self.assertTrue(result["after"])
        self.assertLess(len(result["before"]), 400)
        self.assertLess(len(result["after"]), 400)
        self.assertIn("공고", before[result["priority"]*0:])

    def test_unclassified_rule_still_has_intelligible_description(self):
        result = explain("제2조 필요한 조치는 A에 따른다.",
                         "제2조 필요한 조치는 B에 따른다.")
        self.assertIn("종전 조문에는", result["description"])
        self.assertIn("현행 조문에는", result["description"])
        self.assertNotIn("그 밖의 조문 변경", result["description"])

    def test_real_reference_change_is_not_an_impact_summary(self):
        result = explain("제12조제2항에", "제12조제3항에")
        self.assertEqual(result["change_kind"], "citation")
        self.assertEqual(result["label"], "인용 조문 변경")
        self.assertEqual(result["before"], "제12조제2항")
        self.assertEqual(result["after"], "제12조제3항")
        self.assertIn("인용하는 조문", result["description"])
        self.assertNotIn("인용 법령·조문에 쓰인 표현", result["description"])

    def test_different_programs_are_not_described_as_equivalent(self):
        result = explain("적극행정국민신청", "적극행정 보호지원단")
        self.assertIn(result["change_kind"], ("rewrite", "multiple_edits"))
        self.assertNotIn("신청·처리 절차", result["label"])
        self.assertNotIn("신청·처리 절차", result["description"])
        self.assertNotIn("표현이 ‘적극행정국민신청’에서", result["description"])
        self.assertIn("적극행정국민신청", result["before"])
        self.assertIn("적극행정 보호지원단", result["after"])

    def test_number_only_preceding_body_is_not_a_verified_change(self):
        from policy_domino.parser import take
        from policy_domino.analysis import compare
        old = "③"
        new = ("지방자치단체의 장은 소속 공무원의 적극행정 노력을 "
               "장려하고 보상할 수 있다.")
        result = explain(old, new)
        self.assertEqual(result["change_kind"], "source_check")
        self.assertTrue(result["source_check_required"])
        self.assertIn("판단할 수 없습니다", result["description"])
        self.assertFalse(take(old)["complete"])
        previous = {"status": "extracted", "clauses": {
            "제13조": {"text": old, "complete": True, "sha256": "old"}}}
        current = {"status": "extracted", "clauses": {
            "제13조": {"text": new, "complete": True, "sha256": "new"}}}
        compared = compare(previous, current, {"url": "https://www.law.go.kr"})
        self.assertEqual(compared["status"], "partial_unresolved")
        self.assertEqual(len(compared["excluded"]), 1)
        self.assertEqual(compared["changes"], [])

    def test_unverified_source_cannot_outrank_real_relevant_changes(self):
        bad = item("가상지원규정", "③",
                   "지방자치단체의 장은 적극행정 노력을 포상할 수 있다.")
        cite = item("가상지원규정", "제12조제2항에", "제12조제3항에")
        actual = item("가상지원규정", "제3조 지원금액은 10만원이다.",
                      "제3조 지원금액은 12만원이다.")
        bad["article"],cite["article"],actual["article"]="제13조","제10조","제3조"
        choices = highlight_changes([cite,bad,actual], limit=2,
            institution_reviews=[{"document_id":"가상지원규정","article":"제3조",
                                  "basis_tier":"verified_program_citation"}])
        self.assertEqual(choices[0]["article"],"제3조")
        self.assertEqual(choices[1]["article"],"제10조")

    def test_identical_clause_openings_reveal_real_replaced_word_far_below(self):
        unchanged = ("금융위원회는 법에 따른 계약이전을 받는 자의 지정을 "
                     "공개설명회를 개최하여 심사한다. ") * 35
        before = unchanged + "공고는 일간신문에 게시한다."
        after = unchanged + "공고는 금융위원회 홈페이지에 게시한다."
        result = explain(before, after)
        snippets = result["focus"]
        self.assertGreaterEqual(len(snippets), 1)
        combined_old = " ".join(x["before"]["changed"] for x in snippets)
        combined_new = " ".join(x["after"]["changed"] for x in snippets)
        self.assertIn("일간신문", combined_old)
        self.assertIn("홈페이지", combined_new)
        self.assertNotEqual(combined_old, combined_new)
        self.assertNotIn(unchanged[:120], result["before"])

    def test_long_annex_diff_focus_is_not_common_prefix(self):
        shared = "공공서비스 기준 적용 기록을 보존한다. " * 480
        result = explain(shared + "기준금액 100만원" + shared,
                         shared + "기준금액 120만원" + shared)
        pair = result["focus"][0]
        self.assertIn("100", "".join(pair["before"].values()))
        self.assertIn("120", "".join(pair["after"].values()))
        self.assertLess(len("".join(pair["before"].values())), 350)
        self.assertNotEqual(pair["before"]["changed"],
                            pair["after"]["changed"])

    def test_focus_marks_insertions_and_deletions_without_inventing_text(self):
        source = "제1조 관보에 공고한다."
        updated = "제1조 관보 및 홈페이지에 공고한다."
        lead = focused_differences(source, updated)
        self.assertTrue(lead)
        self.assertNotEqual(lead[0]["before"],lead[0]["after"])
        self.assertIn("홈페이지", "".join(lead[0]["after"].values()))
        self.assertEqual(focused_differences(source,source), [])

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
