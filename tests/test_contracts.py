"""Contract tests use synthetic evidence, never an enrolled policy or agency."""
import copy
import unittest

from policy_domino.contracts import ContractError, validate_public
from policy_domino.core import SCHEMA
from policy_domino.events import build_events


def example():
    data = {
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
    doc = data["documents"][0]
    data["events"] = build_events({doc["id"]: doc},
                                 {doc["id"]: doc["analysis"]})
    return data


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
        x["events"] = []
        self.assertEqual(validate_public(x)["changed_provisions"], 0)

    def test_forged_institutional_review_fails_contract(self):
        x = example()
        source = x["documents"][0]
        event = x["events"][0]
        review = {
            "id": "fake", "document_id": source["id"], "article": "제3조",
            "institution": "근거없는가상기관", "program": "",
            "task": "상관없는 사업 변경", "source_url": source["url"],
            "basis_tier": "direct_regulated_institution",
            "basis_quote": "10일 이내 처리한다",
            "implementation_status": "not_verified",
        }
        event["institutional_reviews"] = [review]
        event["institution_count"] = 1
        event["review_count"] = 1
        with self.assertRaisesRegex(ContractError, "direct subject requires"):
            validate_public(x)

    def test_official_referencing_rule_issuer_is_a_traceable_review(self):
        x = example()
        document = x["documents"][0]
        reference = {
            "id": "official-referencing-rule",
            "source": "ordin", "title": "가상 지원 심사 운영조례",
            "ministry": "가상지방자치단체",
            "url": "https://www.law.go.kr/자치법규/가상지원심사운영조례",
            "reference_only": True,
        }
        edge = {
            "source_event_id": document["id"],
            "changed_article": "제3조",
            "referencing_document_id": reference["id"],
            "referencing_title": reference["title"],
            "referencing_article": "제7조",
            "reference_quote": "「가상 지원기준」 제3조에 따른 심사",
            "referencing_source_url": reference["url"],
            "publishing_agency": reference["ministry"],
            "relationship": "verified_exact_article_citation",
            "operational_program_verified": False,
            "required_action_verified": False,
        }
        x["relationships"] = [edge]
        x["reference_documents"] = [{
            key: reference[key] for key in ("id", "source", "title",
                                            "ministry", "url")
        }]
        x["events"] = build_events(
            {document["id"]: document, reference["id"]: reference},
            {document["id"]: document["analysis"]}, relationships=[edge])
        self.assertEqual(x["events"][0]["review_count"], 1)
        self.assertEqual(validate_public(x)["source_bound_institutional_reviews"], 1)
        forged = copy.deepcopy(x)
        forged["reference_documents"][0]["ministry"] = "근거 없는 기관"
        with self.assertRaisesRegex(ContractError, "citing-rule issuer"):
            validate_public(forged)

    def test_representative_title_cannot_hide_merged_regulations(self):
        x = example()
        x["events"][0]["title"] = "다른 법령 시행령"
        with self.assertRaisesRegex(ContractError, "exact official amended"):
            validate_public(x)

    def test_forged_omnibus_merge_fails_contract(self):
        x = example()
        doc = copy.deepcopy(x["documents"][0])
        doc["id"] = "official-2"
        doc["published_at"] = "2026-11-10"
        x["documents"].append(doc)
        x["events"][0]["source_documents"].append(doc["id"])
        x["events"][0]["source_count"] = 2
        x["events"][0]["members"].append(
            {"id": doc["id"], "title": doc["title"]})
        with self.assertRaisesRegex(
                ContractError, "one policy change event cannot mix"):
            validate_public(x)


if __name__ == "__main__":
    unittest.main()
