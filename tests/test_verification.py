"""Audits cannot quietly turn a partial collection into a full claim."""
import unittest
from policy_domino.verification import audit


class CompletenessAuditTests(unittest.TestCase):
    def test_pending_document_disqualifies_completeness(self):
        report = audit({"documents": [
            {"source": "law", "analysis": {"status": "compared"}},
            {"source": "admrul", "analysis": {"status": "queued"}},
            {"source": "ordin", "analysis": {"status": "partial_compared"}},
        ], "events": []})
        self.assertEqual(report["indexed_documents"], 3)
        self.assertEqual(report["fully_processed_indexed_documents"], 1)
        self.assertEqual(report["incompletely_processed_indexed_documents"], 2)
        self.assertEqual(report["status"], "incomplete")
        self.assertFalse(report["official_universe_exhaustively_reconciled"])

    def test_known_index_is_not_universal_ground_truth(self):
        report = audit({"documents": [{"source": "law",
            "analysis": {"status": "compared"}}], "events": [],
            "collection_run": {"recent_complete": True,
                               "historical_complete": True}})
        self.assertFalse(report["official_universe_exhaustively_reconciled"])
        self.assertFalse(report["institutional_impact_completeness_verified"])
        self.assertEqual(report["status"], "indexed_inventory_processed")

    def test_role_misclassification_reported_separately(self):
        report = audit({"documents": [], "events": [
            {"institutional_reviews": [
                {"institution": "행정안전부장관",
                 "basis_tier": "explicit_changed_clause"},
                {"institution": "국민권익위원회",
                 "basis_tier": "verified_official_rule_citation"}]}]})
        self.assertEqual(report["officeholders_misclassified_as_agencies"],
                         ["행정안전부장관"])
        self.assertEqual(report["source_bound_institutional_review_rows"], 2)


if __name__ == "__main__":
    unittest.main()
