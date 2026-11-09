"""Contract tests use synthetic evidence, never an enrolled policy or agency."""
import copy
import unittest

from policy_domino.contracts import ContractError, validate_public
from policy_domino.core import SCHEMA


def example():
    return {
        "schema": SCHEMA,
        "documents": [{
            "id": "official-1", "source": "law", "title": "가상 지원기준",
            "published_at": "2026-11-09",
            "url": "https://www.law.go.kr/법령/가상규정",
            "analysis": {"status": "compared",
                         "changes": [{
                             "article": "제3조", "before": "10일 이내 처리한다",
                             "after": "12일 이내 처리한다",
                             "source_url": "https://www.law.go.kr/법령/가상규정",
                             "evidence": {
                                 "old_body_sha256": "prior",
                                 "new_body_sha256": "current",
                             },
                         }], "direct_actor_reviews": []},
        }],
        "relationships": [], "cross_document_review_candidates": [],
        "principles": {
            "manual_institutions": False,
            "inferred_programs_count_as_confirmed": False,
            "internal_compliance_status_known": False,
        },
    }


class EvidenceContractTests(unittest.TestCase):
    def test_real_change_not_a_fake_program(self):
        self.assertEqual(validate_public(example())["changed_provisions"], 1)

    def test_unverified_source_does_not_prove_difference(self):
        x = example()
        x["documents"][0]["analysis"]["status"] = "body_unavailable"
        with self.assertRaisesRegex(ContractError, "unverified"):
            validate_public(x)

    def test_issuing_actor_cannot_be_confirmed_program(self):
        x = example()
        x["documents"][0]["analysis"]["direct_actor_reviews"].append({
            "actor": "가상청장", "article": "제3조",
            "operational_program_verified": False, "required_action_verified": True
        })
        with self.assertRaisesRegex(ContractError, "statutory actor"):
            validate_public(x)

    def test_exact_reference_is_not_independent_operational_proof(self):
        x = example()
        x["relationships"].append({
            "source_event_id": "official-1",
            "relationship": "verified_exact_article_citation",
            "changed_article": "제3조", "referencing_article": "제4조",
            "referencing_source_url": "https://www.law.go.kr/법령/가상규정",
            "operational_program_verified": True, "required_action_verified": True,
        })
        with self.assertRaisesRegex(ContractError, "independent official"):
            validate_public(x)

    def test_forged_official_domain_is_rejected(self):
        x = example()
        x["documents"][0]["analysis"]["changes"][0]["source_url"] = \
            "https://www.law.go.kr.evil.test/forged"
        with self.assertRaisesRegex(ContractError, "official"):
            validate_public(x)

    def test_duplicate_event_is_rejected(self):
        x = example()
        x["documents"].append(copy.deepcopy(x["documents"][0]))
        with self.assertRaisesRegex(ContractError, "duplicate"):
            validate_public(x)

    def test_index_waiting_for_official_history_must_remain_visible(self):
        x = example()
        x["documents"][0]["analysis"] = {
            "status": "history_unavailable", "changes": []}
        self.assertEqual(validate_public(x)["changed_provisions"], 0)


if __name__ == "__main__":
    unittest.main()
