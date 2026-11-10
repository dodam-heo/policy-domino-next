import datetime as dt
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from policy_domino.api import Coverage
from policy_domino.core import document_key, load_state, new_state
from policy_domino.pipeline import analyze_one, quality, render, run_once, work_queue


def record(source, stable, serial, date="2026-11-09", title="가상 절차기준"):
    return {"id":document_key(source,stable,serial),"source":source,
            "stable_id":stable,"serial":serial,"published_at":date,
            "title":title,"revision":"일부개정",
            "url":"https://www.law.go.kr/가상","ministry":"가상 기관",
            "kind":"규정","effective_date":date}


class DummyAPI:
    def __init__(self,docs):
        self.docs=docs
    def search_window(self,source,first,last,version,rule_kind=""):
        rows=[x for x in self.docs if x["source"]==source and
              first<=x["published_at"]<=last]
        return rows,Coverage(source,first,last,version,len(rows),len(rows),1,True)
    def detail(self,doc):
        root=ET.Element("Root")
        clause=ET.SubElement(root,"조문단위")
        ET.SubElement(clause,"조문번호").text="3"
        amount="30만원" if doc["serial"].endswith("0") else "40만원"
        ET.SubElement(clause,"조문내용").text="제3조(기준) 지급액은 "+amount+"이다."
        return root
    def history(self,doc):
        return [x for x in self.docs if x["source"]==doc["source"] and
                x["stable_id"]==doc["stable_id"] and
                x["serial"]!=doc["serial"] and
                x["published_at"]<doc["published_at"]]


class PipelineTests(unittest.TestCase):
    def test_ai_check_cli_prints_json_and_detects_failure(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from policy_domino.core import write_json
        from policy_domino.pipeline import main
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = new_state()
            state["ai_run"] = {
                "status": "generated", "attempted": 1,
                "generated": 1, "errors": 0,
            }
            write_json(state_path, state)
            capture = StringIO()
            with redirect_stdout(capture):
                main(["ai-check", "--state", str(state_path)])
            self.assertIn('"status": "generated"', capture.getvalue())
            state["ai_run"]["status"] = "failed"
            write_json(state_path, state)
            with redirect_stdout(StringIO()), self.assertRaises(SystemExit) as ctx:
                main(["ai-check", "--state", str(state_path)])
            self.assertEqual(ctx.exception.code, 1)

    def test_ai_check_warns_for_partial_or_transient_but_fails_auth(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from policy_domino.core import write_json
        from policy_domino.pipeline import main
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            state = new_state()
            state["ai_run"] = {
                "status": "partial_generated", "attempted": 2,
                "generated": 1, "errors": 1,
                "error_codes": {"http_503_overloaded": 1},
            }
            write_json(state_path, state)
            output = StringIO()
            with redirect_stdout(output):
                main(["ai-check", "--state", str(state_path)])
            self.assertIn("::warning", output.getvalue())
            self.assertIn("generated=1", output.getvalue())

            state["ai_run"].update(status="failed", generated=0)
            write_json(state_path, state)
            output = StringIO()
            with redirect_stdout(output):
                main(["ai-check", "--state", str(state_path)])
            self.assertIn("::warning", output.getvalue())

            state["ai_run"]["error_codes"] = {"http_403_forbidden": 1}
            write_json(state_path, state)
            output = StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as ctx:
                main(["ai-check", "--state", str(state_path)])
            self.assertEqual(ctx.exception.code, 1)
            self.assertIn("::error", output.getvalue())

    def test_public_oc_fallback_preserves_prior_working_configuration(self):
        from unittest.mock import patch
        from policy_domino.pipeline import configured_law_oc
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(configured_law_oc(),"dori")
        with patch.dict("os.environ", {"LAW_OC":" custom-public-oc "}):
            self.assertEqual(configured_law_oc(),"custom-public-oc")


    def test_annual_notice_baseline_uses_two_documented_history_modes(self):
        from policy_domino.pipeline import _annual_baseline
        import xml.etree.ElementTree as ET
        current=record("admrul","777","2027","2026-11-10",
                       "가상 연례 운영기준 2027년도 고시")
        class API:
            def __init__(self):
                self.modes=[]
            def request(self,endpoint,target,**params):
                self.modes.append(params["nw"])
                if params["nw"]=="1":
                    return ET.fromstring("<Search><totalCnt>0</totalCnt></Search>")
                return ET.fromstring("""<Search><totalCnt>1</totalCnt><admrul>
                    <행정규칙명>가상 연례 운영기준 2026년도 고시</행정규칙명>
                    <행정규칙ID>900</행정규칙ID>
                    <행정규칙일련번호>212</행정규칙일련번호>
                    <발령일자>20251110</발령일자>
                    <행정규칙종류>고시</행정규칙종류>
                    </admrul></Search>""")
        api=API()
        previous=_annual_baseline(api,current)
        self.assertEqual(api.modes,["1","2"])
        self.assertEqual(previous["title"],"가상 연례 운영기준 2026년도 고시")
        self.assertEqual(previous["law_type"],"고시")

    def test_round_robin_sources_without_manual_institution_registration(self):
        state=new_state()
        docs=[record("law",str(i),str(i)) for i in range(10)]
        docs +=[record("admrul","20","21"),record("ordin","30","31")]
        state["documents"]={x["id"]:x for x in docs}
        queue=work_queue(state,dt.date(2026,11,10),6)
        self.assertIn("admrul",{x["source"] for x in queue})
        self.assertIn("ordin",{x["source"] for x in queue})
        self.assertEqual(len(queue),6)

    def test_end_to_end_persistence_and_unseeded_change(self):
        original=record("law","1","10","2026-11-08")
        new=record("law","1","11","2026-11-09")
        admrul=record("admrul","2","21")
        ordin=record("ordin","3","31")
        state=new_state()
        api=DummyAPI([original,new,admrul,ordin])
        run_once(state,api,dt.date(2026,11,9),limit=4)
        self.assertIn(new["id"],state["findings"])
        self.assertEqual(state["findings"][new["id"]]["status"],"compared")
        self.assertTrue(state["findings"][new["id"]]["changes"])
        self.assertTrue(state["findings"][new["id"]]["baseline"])
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/"data.json"
            report=render(state,output)
            self.assertEqual(report["schema"],"policy-domino-next-v1")
            self.assertTrue(output.exists())
            self.assertEqual(report["quality"]["law"]["verified_changes"],1)
            self.assertIn("rule_categories",report["quality"])
            self.assertIn("고시",report["quality"]["rule_categories"])
            self.assertEqual(report["ai_progress"]["analyzed_events"], 0)
            self.assertGreaterEqual(report["ai_progress"]["verified_events"], 1)
            self.assertEqual(report["ai_progress"]["pending_events"],
                             report["ai_progress"]["verified_events"])
            self.assertEqual(report["ai_progress"]["source_events"],
                             len(report["events"]))
            self.assertLessEqual(len(report["events"]), len(report["documents"]))
            self.assertTrue(all(e["source_documents"] for e in report["events"]))
            self.assertEqual(
                report["ai_progress"]["institutional_reviews"],
                sum(e["review_count"] for e in report["events"]))
            self.assertTrue(all(not x.get("reference_only")
                                for x in report["documents"]))

    def test_failed_previous_source_never_fakes_a_change(self):
        new=record("ordin","3","31")
        class NoHistory(DummyAPI):
            def history(self,doc):
                raise RuntimeError("upstream unavailable")
        state=new_state()
        item=analyze_one(NoHistory([new]),state,new)
        self.assertEqual(item["status"],"history_unavailable")
        self.assertFalse(item["changes"])

    def test_ref_only_previous_version_never_creates_new_policy_event(self):
        current=record("admrul","2","21","2026-11-09")
        old=record("admrul","2","20","2026-11-08")
        state=new_state()
        state["documents"]={current["id"]:current}
        result=analyze_one(DummyAPI([current,old]),state,current)
        self.assertEqual(result["status"],"compared")
        self.assertTrue(state["documents"][old["id"]]["reference_only"])
        self.assertNotIn(old["id"],[x["id"] for x in
                                   work_queue(state,dt.date(2026,11,10),10)])


if __name__=="__main__":
    unittest.main()
