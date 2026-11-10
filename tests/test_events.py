"""Source-only event grouping and institution/operational review regression tests.

All public institutions and regulations here are synthetic; no name is
pre-enrolled in production code or assumed affected by a subject keyword.
"""
from __future__ import annotations

import unittest

from policy_domino.events import build_events, event_identity
from policy_domino.core import document_key


def doc(name, serial, number, *, date="2026-11-09",
        law_type="대통령령", source="law"):
    stable = name
    return {
        "id": document_key(source, stable, serial),
        "source": source, "stable_id": stable, "serial": serial,
        "title": name, "published_at": date,
        "number": number, "law_type": law_type,
        "kind": "법령", "revision": "일부개정",
        "ministry": "가상국", "effective_date": date,
        "url": "https://www.law.go.kr/법령/" + name,
    }


def changed(document, *, article="제3조", category="조직·정원"):
    return {
        "status": "compared",
        "changes": [{
            "article": article,
            "before": "제3조 인원을 10명으로 한다.",
            "after": "제3조 인원을 12명으로 한다.",
            "actual_edits": [
                {"old_excerpt": "10명", "new_excerpt": "12명"}],
            "category": category,
            "source_url": document["url"],
            "evidence": {
                "old_body_sha256": "old-source-hash",
                "new_body_sha256": "new-source-hash",
            },
        }],
        "direct_actor_reviews": [],
    }


class PolicyEventModelTests(unittest.TestCase):
    def test_same_official_promulgation_is_one_event_not_many_rows(self):
        docs = [
            doc("가상지원청과 그 소속기관 직제", "11", "12015"),
            doc("가상산업청과 그 소속기관 직제", "21", "12015"),
            doc("가상인력특례", "31", "12015"),
        ]
        results = {d["id"]: changed(d) for d in docs}
        events = build_events({d["id"]: d for d in docs}, results)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["source_count"], 3)
        self.assertEqual(len(event["changes"]), 3)
        self.assertEqual(event["institution_count"], 2)
        self.assertEqual(event["review_count"], 2)
        self.assertIn("3건 동시 개정", event["title"])
        self.assertEqual(
            {x["institution"] for x in event["institutional_reviews"]},
            {"가상지원청", "가상산업청"})
        self.assertTrue(all(x["implementation_status"] == "not_verified"
                            for x in event["institutional_reviews"]))
        self.assertTrue(all(x["basis_tier"] == "direct_regulated_institution"
                            for x in event["institutional_reviews"]))

    def test_same_day_not_same_number_or_type_remains_separate(self):
        docs = [
            doc("가상기준가", "11", "12015"),
            doc("가상기준나", "12", "12016"),
            doc("가상기준다", "13", "12015", law_type="법률"),
        ]
        out = build_events({d["id"]: d for d in docs},
                           {d["id"]: changed(d) for d in docs})
        self.assertEqual(len(out), 3)
        self.assertEqual(len({event_identity(d) for d in docs}), 3)

    def test_unidentified_legal_class_does_not_create_false_omnibus(self):
        docs = [
            doc("가상재정법", "11", "12015", law_type="법령"),
            doc("가상산업법", "12", "12015", law_type="법령"),
        ]
        events = build_events(
            {d["id"]: d for d in docs},
            {d["id"]: changed(d) for d in docs})
        self.assertEqual(len(events), 2)
        self.assertTrue(all(e["source_count"] == 1 for e in events))
        self.assertEqual(len({event_identity(d) for d in docs}), 2)

    def test_invalid_promulgation_number_does_not_group(self):
        docs = [
            doc("가상지원법A", "11", "0"),
            doc("가상지원법B", "12", "0"),
        ]
        events = build_events(
            {d["id"]: d for d in docs},
            {d["id"]: changed(d) for d in docs})
        self.assertEqual(len(events), 2)

    def test_event_readability_is_rebuilt_from_verified_source(self):
        d = doc("가상지원청과 그 소속기관 직제", "11", "12015")
        f = changed(d)
        event = build_events({d["id"]: d}, {d["id"]: f})[0]
        self.assertIn("1개 조문 변경", event["headline"])
        self.assertNotIn("그 밖의 조문 변경 관련 변경", event["headline"])
        ch = event["changes"][0]
        self.assertTrue(ch["meaning"]["before"])
        self.assertTrue(ch["meaning"]["after"])
        self.assertIn("바뀌었습니다", ch["brief"])
        self.assertEqual(event["highlights"], [
            {"document_id": d["id"], "article": "제3조"}])

    def test_local_same_number_never_cross_merges(self):
        docs = [
            doc("가상A 조례", "11", "121", source="ordin"),
            doc("가상B 조례", "21", "121", source="ordin"),
        ]
        result = build_events({d["id"]: d for d in docs},
                              {d["id"]: changed(d) for d in docs})
        self.assertEqual(len(result), 2)

    def test_no_unverified_index_entry_is_masqueraded_as_change(self):
        d = doc("가상정책", "11", "991")
        out = build_events({d["id"]: d},
                           {d["id"]: {"status": "queued", "changes": []}})
        self.assertEqual(out, [])

    def test_institution_not_in_source_is_not_inferred_from_ministry(self):
        d = doc("가상복지법", "11", "998")
        d["ministry"] = "가상복지부"
        out = build_events({d["id"]: d}, {d["id"]: changed(d)})
        self.assertEqual(out[0]["institutional_reviews"], [])
        self.assertEqual(out[0]["institution_count"], 0)

    def test_changed_clause_explicit_actor_has_bounded_review(self):
        d = doc("가상복지법", "11", "998")
        finding = changed(d)
        finding["direct_actor_reviews"] = [{
            "actor": "가상급여청장", "article": "제3조",
            "evidence_level": "changed_clause_explicit_actor",
            "operational_program_verified": False,
            "required_action_verified": False,
        }]
        result = build_events({d["id"]: d}, {d["id"]: finding})
        a = result[0]["institutional_reviews"][0]
        self.assertEqual(a["institution"], "가상급여청장")
        self.assertEqual(a["basis_tier"], "explicit_changed_clause")
        self.assertEqual(a["implementation_status"], "not_verified")

    def test_exact_downstream_public_rule_citation_creates_issuer_review(self):
        source = doc("가상 지원기준법", "11", "19821")
        downstream = doc("가상 복지업무 시행규칙", "22", "5412", source="admrul")
        downstream["ministry"] = "가상지방정부"
        downstream["reference_only"] = True
        documents = {d["id"]: d for d in (source, downstream)}
        ref = {
            "source_event_id": source["id"],
            "changed_article": "제3조",
            "referencing_document_id": downstream["id"],
            "referencing_title": downstream["title"],
            "referencing_article": "제7조",
            "reference_quote": "「가상 지원기준법」 제3조에 따라 심사한다.",
            "referencing_source_url": downstream["url"],
            "publishing_agency": "가상지방정부",
            "relationship": "verified_exact_article_citation",
        }
        events = build_events(documents, {source["id"]: changed(source)},
                              relationships=[ref])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["review_count"], 1)
        review = events[0]["institutional_reviews"][0]
        self.assertEqual(review["institution"], "가상지방정부")
        self.assertEqual(review["basis_tier"], "verified_official_rule_citation")
        self.assertEqual(review["linking_regulation"], downstream["title"])
        self.assertEqual(review["related_rule_url"], downstream["url"])
        self.assertIn("제7조", review["task"])
        self.assertEqual(review["implementation_status"], "not_verified")

    def test_unverified_or_missing_rule_issuer_does_not_create_impact(self):
        source = doc("가상 지원기준법", "11", "19821")
        downstream = doc("가상 시행규칙", "22", "5412", source="admrul")
        downstream["reference_only"] = True
        downstream["ministry"] = ""
        edge = {
            "source_event_id": source["id"], "changed_article": "제3조",
            "referencing_document_id": downstream["id"],
            "referencing_title": downstream["title"], "referencing_article": "제7조",
            "reference_quote": "「가상 지원기준법」 제3조",
            "referencing_source_url": downstream["url"],
            "publishing_agency": "출처에 없는 기관",
            "relationship": "verified_exact_article_citation",
        }
        result = build_events({x["id"]: x for x in (source, downstream)},
                              {source["id"]: changed(source)},
                              relationships=[edge])
        self.assertEqual(result[0]["institution_count"], 0)
        self.assertEqual(result[0]["review_count"], 0)

    def test_verified_public_program_citation_is_separate_evidence_tier(self):
        d = doc("가상복지법", "11", "998")
        f = changed(d, category="금액·비율")
        dep = {
            "source_event_id": d["id"],
            "changed_article": "제3조",
            "agency": "가상생활공단",
            "program": "가상생계지원사업",
            "program_id": "a-program",
            "program_url": "https://www.alioplus.go.kr/business/bsnDetail.do?bsnSeq=333&bsnTyp=DET",
            "citation_quote": "「가상복지법」 제3조에 따른 지급 기준",
            "verification": "verified_program_citation",
            "operational_program_verified": True,
            "required_action_verified": False,
        }
        events = build_events({d["id"]: d}, {d["id"]: f},
                              program_dependencies=[dep])
        a = events[0]["institutional_reviews"][0]
        self.assertEqual(a["basis_tier"], "verified_program_citation")
        self.assertEqual(a["program"], "가상생계지원사업")
        self.assertIn("지급·산정", a["task"])
        self.assertEqual(a["program_url"], dep["program_url"])

    def test_legacy_ai_is_not_automatically_adopted_without_validation(self):
        d = doc("가상복지법", "11", "998")
        f = changed(d)
        events = build_events({d["id"]: d}, {d["id"]: f})
        self.assertEqual(events[0]["ai_count"], 0)
        # Only the caller's *current-source-validated* AI summaries qualify.
        valid = {
            "status": "generated",
            "change_reviews": [{
                "article": "제3조", "summary": "인원 기준 변경",
                "review_question": "심사 인원을 대조할 것인가?",
                "before_quote": "10명", "after_quote": "12명",
            }],
        }
        out = build_events({d["id"]: d}, {d["id"]: f},
                           ai_reviews={d["id"]: valid})
        self.assertEqual(out[0]["ai_count"], 1)

    def test_identical_source_output_is_deterministic(self):
        docs = [
            doc("가상지원청과 그 소속기관 직제", "11", "12015"),
            doc("가상산업청과 그 소속기관 직제", "21", "12015"),
        ]
        records = {d["id"]: d for d in docs}
        findings = {d["id"]: changed(d) for d in docs}
        one = build_events(records, findings)
        two = build_events(dict(reversed(list(records.items()))), findings)
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
