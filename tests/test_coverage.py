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
        self.assertEqual(cursors["law|1"],"2026-10-20")
        self.assertEqual(cursors["ordin|2"],"2026-10-20")
        self.assertTrue(collect_streams(None,state,today,ingest))
        self.assertEqual(cursors["admrul|1|3"],"2026-10-06")
        self.assertEqual(cursors["law|1"],"2026-10-06")
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
        self.assertIn(("1","2026-06-04","2026-07-01"),seen)
        self.assertIn(("2","2026-05-05","2026-06-01"),seen)
        self.assertEqual(state["backfill_end_dates"]["admrul|1|3"],
                         "2026-06-03")
        self.assertEqual(state["collection_run"]["rule_kinds"]["고시"]["completed"],4)
        self.assertEqual(state["collection_run"]["streams"],30)

    def test_existing_annual_enactment_gets_one_official_prior_year_recheck(self):
        doc={"id":"admrul|101|2027","source":"admrul",
             "title":"가상 2027년도 운영기준","revision":"제정",
             "published_at":"2026-07-29","serial":"2027",
             "stable_id":"101","reference_only":False}
        state=new_state()
        state["documents"]={doc["id"]:doc}
        state["findings"]={doc["id"]:{"status":"enactment"}}
        queue=fair_work_queue(state,dt.date(2026,11,10),limit=4)
        self.assertEqual(len(queue),1)
        self.assertEqual(queue[0]["id"],doc["id"])
        state["annual_recheck_completed_ids"]=[doc["id"]]
        self.assertEqual(fair_work_queue(state,dt.date(2026,11,10),4),[])

    def test_historical_backfill_uses_multiweek_blocks_for_all_sources(self):
        state=new_state()
        queries=[]
        def ingest(api,state,source,first,last,version,*,rule_kind=""):
            queries.append((source,version,rule_kind,first,last))
            return True
        collect_streams(None,state,dt.date(2026,11,10),ingest)
        latest={x[:3]:x for x in queries if x[-1]=="2026-11-03"}
        self.assertEqual(latest[("admrul","1","3")][-2],"2026-10-07")
        self.assertEqual(latest[("law","1","")][-2],"2026-10-21")
        self.assertEqual(latest[("ordin","2","")][-2],"2026-10-21")
        self.assertEqual(state["collection_run"]["historical_window_days"],
                         {"law":14,"admrul":28,"ordin":14})

    def test_incomplete_time_budget_defers_unchecked_categories_without_losing_cursors(self):
        from unittest.mock import patch
        state=new_state()
        calls=[]
        def ingest(api,state,source,first,last,version,*,rule_kind=""):
            calls.append((source,version,rule_kind,first,last))
            return True
        # First official stream is checked; later ones must be deferred
        # instead of falsely marking the full history as complete.
        with patch("policy_domino.coverage.time.monotonic",
                   side_effect=[0.0,0.1,0.7,0.8]):
            ok=collect_streams(None,state,dt.date(2026,11,10),ingest,
                               max_seconds=0.5)
        self.assertFalse(ok)
        self.assertEqual(state["collection_run"]["streams"],2)
        self.assertEqual(state["collection_run"]["deferred_streams"],14)
        self.assertFalse(state["collection_run"]["recent_complete"])
        self.assertEqual(state["collection_stream_offset"],1)
        self.assertEqual(len(calls),2)
        previous=len(calls)
        self.assertTrue(collect_streams(None,state,dt.date(2026,11,10),ingest))
        self.assertEqual(state["collection_run"]["deferred_streams"],0)
        self.assertNotEqual(calls[previous][0:3],("law","1",""))

    def test_admrul_kinds_are_interleaved_in_comparison_queue(self):
        state=new_state()
        kinds=("고시","공고","지침","훈령","예규","기타")
        for index,kind in enumerate(kinds):
            for n in range(8):
                item=document("admrul",index*100+n,"2026-11-09")
                item["law_type"]=kind
                state["documents"][item["id"]]=item
        queue=fair_work_queue(state,dt.date(2026,11,10),12)
        self.assertEqual(len(queue),12)
        self.assertEqual({d["law_type"] for d in queue},set(kinds))
        self.assertEqual(len({d["id"] for d in queue}),12)
        self.assertEqual(state["rule_processing_rotation"],1)

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

    def test_upcoming_effective_notices_do_not_wait_behind_old_backlog(self):
        state = new_state()
        today = dt.date(2026, 11, 11)
        for n in range(100):
            row = document("admrul", n, "2026-05-01")
            state["documents"][row["id"]] = row
        upcoming = document("admrul", "upcoming", "2026-08-31")
        upcoming["effective_date"] = "2027-01-01"
        state["documents"][upcoming["id"]] = upcoming
        queue = fair_work_queue(state, today, 12)
        self.assertIn(upcoming["id"], {row["id"] for row in queue})
        self.assertEqual(len(queue), 12)
        self.assertEqual(len({row["id"] for row in queue}), 12)
        self.assertTrue(any(row.get("published_at") == "2026-05-01"
                            for row in queue))
        self.assertEqual(fair_work_queue(state, today, 0), [])
        state["attempts"][upcoming["id"]] = {
            "count": 1, "last_date": today.isoformat()}
        self.assertNotIn(upcoming["id"], {row["id"] for row in
                         fair_work_queue(state, today, 12)})

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
