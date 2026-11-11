import datetime as dt
import unittest
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
        results=[official_doc(1)] if kind=="3" else []
        return results,Coverage("admrulOldAndNew",first,last,"both",
                                len(results),len(results),1,True,rule_kind=kind)


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

    def test_official_index_request_never_invents_a_document(self):
        from urllib.parse import parse_qs,urlparse
        requests=[]
        def transport(url):
            params=parse_qs(urlparse(url).query)
            requests.append(params)
            return ("""<Search><totalCnt>1</totalCnt><admrul>
             <행정규칙ID>1200</행정규칙ID>
             <행정규칙일련번호>2001</행정규칙일련번호>
             <행정규칙명>가상 지원기준 고시</행정규칙명>
             <발령일자>20261020</발령일자>
             </admrul></Search>""").encode("utf-8")
        api=LawAPI("example",transport)
        docs,audit=api.changed_rule_window("2026-10-01","2026-10-31","3")
        self.assertTrue(audit.complete)
        self.assertEqual(docs[0]["law_type"],"고시")
        self.assertEqual(requests[0]["target"],["admrulOldAndNew"])
        self.assertEqual(requests[0]["knd"],["3"])
        self.assertEqual(requests[0]["prmlYd"],["20261001~20261031"])
        self.assertNotIn("nw",requests[0])

if __name__=="__main__":
    unittest.main()
