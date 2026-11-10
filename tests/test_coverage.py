"""Official collection completeness and fair source comparison regression tests."""
from __future__ import annotations

import datetime as dt
import unittest

from policy_domino.coverage import collect_streams, fair_work_queue, pending_counts
from policy_domino.core import new_state


def document(source, serial, published):
    return {
        "id": source+"-"+str(serial), "source": source,
        "title": "가상 정책규정 "+str(serial),
        "serial": str(serial), "published_at": published,
    }


class CoverageTests(unittest.TestCase):
    def test_each_official_stream_backfills_independently_and_retries_failed_window(self):
        state=new_state()
        today=dt.date(2026,11,10)
        calls=[]
        failed={"done":False}
        def ingest(api, state, source, first, last, version, *, rule_kind=""):
            calls.append((source, version, rule_kind, first, last))
            if ((source,version,rule_kind,last)==
                ("admrul","1","3","2026-11-03") and not failed["done"]):
                failed["done"]=True
                return False
            return True
        self.assertFalse(collect_streams(None,state,today,ingest))
        cursors=state["backfill_end_dates"]
        self.assertEqual(state["collection_run"]["streams"],30)
        self.assertEqual(state["collection_run"]["failed_windows"],1)
        self.assertEqual(cursors["admrul|1|3"],"2026-11-03")
        self.assertEqual(state["collection_run"]["rule_kinds"]["고시"]["failed"],1)
        self.assertEqual(cursors["law|1"],"2026-10-27")
        self.assertEqual(cursors["ordin|2"],"2026-10-27")
        self.assertTrue(collect_streams(None,state,today,ingest))
        self.assertEqual(cursors["admrul|1|3"],"2026-10-27")
        self.assertEqual(cursors["law|1"],"2026-10-20")
        self.assertEqual(state["collection_run"]["failed_windows"],0)
        self.assertTrue(any(x[:3]==("admrul","1","3") and
                            x[4]=="2026-11-03" for x in calls))

    def test_administrative_notice_categories_inherit_legacy_history_boundary(self):
        state=new_state()
        state["backfill_end_dates"]={"admrul|1":"2026-07-01",
                                     "admrul|2":"2026-06-01"}
        seen=[]
        def ingest(api,state,source,first,last,version,*,rule_kind=""):
            if source=="admrul" and rule_kind=="3":
                seen.append((version,first,last))
            return True
        collect_streams(None,state,dt.date(2026,11,10),ingest)
        self.assertIn(("1","2026-06-25","2026-07-01"),seen)
        self.assertIn(("2","2026-05-26","2026-06-01"),seen)
        self.assertEqual(state["backfill_end_dates"]["admrul|1|3"],
                         "2026-06-24")
        self.assertEqual(state["collection_run"]["rule_kinds"]["고시"]["completed"],4)
        self.assertEqual(state["collection_run"]["streams"],30)

    def test_recent_and_old_pending_both_get_processing_turns(self):
        state=new_state()
        state["documents"]={
            d["id"]:d for d in (
                [document("law",n,"2026-11-09") for n in range(30)]+
                [document("law",n+100,"2026-06-01") for n in range(30)]+
                [document("admrul",n+200,"2026-11-08") for n in range(10)]+
                [document("ordin",n+300,"2026-07-01") for n in range(10)]
            )
        }
        queue=fair_work_queue(state,dt.date(2026,11,10),12)
        self.assertEqual(len(queue),12)
        self.assertIn("law", {d["source"] for d in queue})
        self.assertIn("admrul",{d["source"] for d in queue})
        self.assertIn("ordin",{d["source"] for d in queue})
        self.assertTrue(any(d["published_at"]=="2026-06-01" for d in queue))
        self.assertTrue(any(d["published_at"]=="2026-11-09" for d in queue))
        self.assertEqual(len(set(d["id"] for d in queue)),len(queue))

    def test_retry_threshold_is_not_permanent_exclusion(self):
        from policy_domino.coverage import retry_due
        previous={"count":4,"last_date":"2026-11-08"}
        self.assertFalse(retry_due(previous,dt.date(2026,11,9)))
        self.assertTrue(retry_due(previous,dt.date(2026,11,10)))
        state=new_state()
        item=document("law","old","2026-06-01")
        state["documents"][item["id"]]=item
        state["attempts"][item["id"]]=previous
        queue=fair_work_queue(state,dt.date(2026,11,10),5)
        self.assertEqual([d["id"] for d in queue],[item["id"]])
        self.assertEqual(pending_counts(state,dt.date(2026,11,10))
                         ["law"]["retryable"],1)

    def test_verified_partial_unattempted_retry_and_blocked_are_distinct(self):
        state=new_state()
        for n in range(5):
            doc=document("law",n,"2026-11-09")
            state["documents"][doc["id"]]=doc
        state["findings"]={
            "law-0":{"status":"compared"},
            "law-1":{"status":"partial_compared"},
            "law-3":{"status":"source_error"},
            "law-4":{"status":"history_unavailable"},
        }
        state["attempts"]={
            "law-0":{"count":1},
            "law-1":{"count":1},
            "law-3":{"count":2},
            "law-4":{"count":4},
        }
        result=pending_counts(state)["law"]
        self.assertEqual(result["indexed"],5)
        self.assertEqual(result["verified"],1)
        self.assertEqual(result["partial"],1)
        self.assertEqual(result["unexamined"],1)
        self.assertEqual(result["retryable"],2)
        self.assertEqual(result["blocked"],1)
        queue=fair_work_queue(state,dt.date(2026,11,10),10)
        self.assertNotIn("law-4",{d["id"] for d in queue})
        self.assertNotIn("law-0",{d["id"] for d in queue})


if __name__=="__main__":
    unittest.main()
