import datetime as dt
import unittest
from unittest.mock import patch
from policy_domino.api import LawAPI, Coverage
from policy_domino.core import new_state, document_key
from policy_domino.reconciliation import reconcile_changed_rules
from policy_domino.coverage import fair_work_queue


def official_doc(i, kind="고시"):
    return {
        "id":document_key("admrul",str(100+i),str(1000+i)),
        "source":"admrul","stable_id":str(100+i),
        "serial":str(1000+i),"title":"가상 "+kind+" 운영기준 "+str(i),
        "published_at":"2026-10-29","law_type":kind,
        "url":"https://www.law.go.kr",
        "revision":"일부개정",
    }


class FakeAPI:
    def __init__(self):
        self.calls=[]
    def changed_rule_window(self,first,last,kind,max_pages=20):
        self.calls.append((first,last,kind))
        results=[{
            "source":"admrulOldAndNew","title":official_doc(1)["title"],
            "comparison_id":"C1","comparison_serial":"X1",
            "published_at":"2026-10-29","rule_kind":"3","law_type":"고시",
        }] if kind=="3" else []
        return results,Coverage("admrulOldAndNew",first,last,"both",
                                len(results),len(results),1,True,rule_kind=kind)
    def resolve_changed_rule(self,candidate):
        return official_doc(1)


class ReconciliationTests(unittest.TestCase):
    def test_missing_official_legal_record_is_registered_and_prioritized(self):
        api=FakeAPI()
        state=new_state()
        today=dt.date(2026,11,10)
        audit=reconcile_changed_rules(
            api,state,today,earliest=dt.date(2026,10,20),
            max_windows=6,max_seconds=30)
        self.assertEqual(audit["new_documents"],1)
        self.assertEqual(audit["windows_checked"],6)
        self.assertEqual(len(api.calls),6)
        record=official_doc(1)
        self.assertIn(record["id"],state["documents"])
        self.assertEqual(state["documents"][record["id"]]["catalog_sources"],
                         ["admrulOldAndNew"])
        selected=fair_work_queue(state,today,6)
        self.assertEqual(selected[0]["id"],record["id"])
        audit2=reconcile_changed_rules(
            api,state,today,earliest=dt.date(2026,10,20),
            max_windows=6,max_seconds=30)
        self.assertEqual(audit2["new_documents"],0)
        self.assertEqual(len(state["documents"]),1)

    def test_failed_window_does_not_disappear_from_evidence_audit(self):
        class Failure:
            def changed_rule_window(self,*args,**kwargs):
                raise ValueError("official upstream unavailable")
        state=new_state()
        out=reconcile_changed_rules(Failure(),state,dt.date(2026,11,10),
                    earliest=dt.date(2026,11,1),max_windows=2,max_seconds=30)
        self.assertEqual(out["failed_windows"],2)
        self.assertEqual(out["new_documents"],0)
        self.assertTrue(any(not v["complete"] for v in
                            state["reconciliation_windows"].values()))

    def test_previous_failure_is_retried_without_rewinding_primary_cursor(self):
        from policy_domino.core import ADMIN_RULE_KINDS
        state = new_state()
        today = dt.date(2026, 11, 10)
        first_kind = next(iter(ADMIN_RULE_KINDS))
        old_key = "admrulOldAndNew|" + first_kind + "|2026-11-01|2026-11-10"
        state["reconciliation_windows"][old_key] = {
            "complete": False, "checked_at": "2026-11-01T00:00:00+00:00"}
        state["reconcile_cursor"] = 3
        api = FakeAPI()
        report = reconcile_changed_rules(
            api, state, today, earliest=dt.date(2026, 11, 1),
            max_windows=2, max_seconds=30)
        self.assertEqual(report["retried_previous_failure_windows"], 1)
        self.assertEqual(report["windows_checked"], 2)
        self.assertEqual(report["next_cursor"], 4)
        self.assertTrue(state["reconciliation_windows"][old_key]["complete"])
        self.assertEqual(api.calls[0][2], first_kind)

    def test_budget_exhaustion_preserves_partial_window_for_resume(self):
        class Slow(FakeAPI):
            def changed_rule_window(self, first, last, kind, max_pages=20):
                rows = [{"title": official_doc(i)["title"],
                         "published_at": "2026-10-29",
                         "comparison_id": str(i), "comparison_serial": str(i)}
                        for i in (1, 2)]
                return rows, Coverage("admrulOldAndNew", first, last,
                                      "both", 2, 2, 1, True)
        state = new_state()
        with patch("policy_domino.reconciliation.time.monotonic",
                   side_effect=[0, 0, 1, 31]):
            report = reconcile_changed_rules(
                Slow(), state, dt.date(2026, 11, 10),
                earliest=dt.date(2026, 10, 20), max_seconds=30)
        self.assertEqual(report["new_documents"], 1)
        self.assertEqual(report["next_cursor"], 0)
        window = next(iter(state["reconciliation_windows"].values()))
        self.assertFalse(window["complete"])
        self.assertEqual(window["deferred_canonical_records"], 1)
        self.assertEqual(len(state["reconciliation_priority_ids"]), 1)

    def test_upstream_failure_never_fans_out_into_recursive_requests(self):
        class Broken(FakeAPI):
            def changed_rule_window(self, first, last, kind, max_pages=20):
                self.calls.append(kind)
                return [], Coverage("admrulOldAndNew", first, last,
                                     "both", 200, 0, 0, False,
                                     "Official API time budget exhausted")
        api = Broken()
        reconcile_changed_rules(api, new_state(), dt.date(2026, 11, 10),
                                max_windows=1, max_seconds=30)
        self.assertEqual(len(api.calls), 1)

    def test_expired_api_budget_never_starts_another_transport(self):
        from policy_domino.api import ApiError
        transport = unittest.mock.Mock()
        api = LawAPI("example", transport)
        api.deadline = 1
        with patch("policy_domino.api.time.monotonic", return_value=2):
            with self.assertRaises(ApiError):
                api.request("lawSearch.do", "admrul")
        transport.assert_not_called()

    def test_comparison_api_requires_independent_canonical_identity(self):
        from urllib.parse import parse_qs,urlparse
        requests=[]
        def transport(url):
            params=parse_qs(urlparse(url).query)
            requests.append(params)
            if params["target"]==["admrulOldAndNew"]:
                return ("""<Search><totalCnt>1</totalCnt><oldAndNew>
                  <신구법ID>90001</신구법ID>
                  <신구법일련번호>70001</신구법일련번호>
                  <신구법명>가상 지원기준 고시</신구법명>
                  <발령일자>20261020</발령일자>
                  </oldAndNew></Search>""").encode("utf-8")
            return ("""<Search><totalCnt>1</totalCnt><admrul>
             <행정규칙ID>1200</행정규칙ID>
             <행정규칙일련번호>2001</행정규칙일련번호>
             <행정규칙명>가상 지원기준 고시</행정규칙명>
             <발령일자>20261020</발령일자>
             <행정규칙종류>고시</행정규칙종류>
             </admrul></Search>""").encode("utf-8")
        api=LawAPI("example",transport)
        candidates,audit=api.changed_rule_window("2026-10-01","2026-10-31","3")
        self.assertTrue(audit.complete)
        self.assertEqual(candidates[0]["source"],"admrulOldAndNew")
        self.assertNotIn("id",candidates[0])
        doc=api.resolve_changed_rule(candidates[0])
        self.assertEqual(doc["source"],"admrul")
        self.assertEqual(doc["stable_id"],"1200")
        self.assertEqual(doc["serial"],"2001")
        self.assertNotEqual(doc["serial"],candidates[0]["comparison_serial"])
        self.assertEqual(requests[0]["target"],["admrulOldAndNew"])
        self.assertEqual(requests[0]["knd"],["3"])
        self.assertEqual(requests[0]["prmlYd"],["20261001~20261031"])
        self.assertEqual(requests[1]["target"],["admrul"])
        self.assertEqual(requests[1]["prmlYd"],["20261020~20261020"])

    def test_unresolvable_comparison_record_is_audited_not_invented(self):
        class Unresolved(FakeAPI):
            def resolve_changed_rule(self,candidate):
                return None
        state=new_state()
        result=reconcile_changed_rules(
            Unresolved(),state,dt.date(2026,11,10),
            earliest=dt.date(2026,10,20),max_windows=6,max_seconds=30)
        self.assertEqual(result["new_documents"],0)
        self.assertEqual(len(state["documents"]),0)
        self.assertTrue(any(
            x.get("unresolved_canonical_records")
            for x in state["reconciliation_windows"].values()))


if __name__=="__main__":
    unittest.main()
