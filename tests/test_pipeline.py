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
    def search_window(self,source,first,last,version):
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
        run_once(state,api,dt.date(2026,11,09),limit=4)
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
