import unittest
import xml.etree.ElementTree as ET

from policy_domino.analysis import connect_changes
from policy_domino.core import document_key,new_state
from policy_domino.discovery import discover_dependents


class OfficialDependencyDiscovery(unittest.TestCase):
    def test_unregistered_public_rule_is_discovered_only_from_exact_citation(self):
        source_id=document_key("admrul","5","90")
        source={"id":source_id,"source":"admrul","title":"가상 기준고시",
                "stable_id":"5","serial":"90","published_at":"2026-11-09",
                "ministry":"가상발령기관","url":"https://www.law.go.kr/a"}
        state=new_state()
        state["documents"][source_id]=source
        state["findings"][source_id]={"status":"compared",
                                     "changes":[{"article":"제3조"}]}
        ref_id=document_key("ordin","8","71")
        class FakeAPI:
            def request(self,endpoint,target,**params):
                if target!="ordin":
                    return ET.fromstring("<Root><totalCnt>0</totalCnt></Root>")
                return ET.fromstring("""<Root><totalCnt>1</totalCnt><law>
                    <자치법규명>가상사업 운영조례</자치법규명>
                    <자치법규ID>8</자치법규ID>
                    <자치법규일련번호>71</자치법규일련번호>
                    <공포일자>20251109</공포일자>
                    </law></Root>""")
            def detail(self,doc):
                return ET.fromstring("""<Root><조문단위>
                  <조문번호>7</조문번호>
                  <조문내용>이 조례는 「가상 기준고시」 제3조에 따라 신청을 심사한다.</조문내용>
                  </조문단위></Root>""")
        results=discover_dependents(FakeAPI(),state,limit_events=1)
        self.assertEqual(results["exact_article_references"],1)
        self.assertIn(ref_id,state["versions"])
        self.assertTrue(state["documents"][ref_id]["reference_only"])
        edges=connect_changes(state["findings"],state["versions"],state["documents"])
        self.assertEqual(len(edges),1)
        self.assertTrue(edges[0]["reference_predates_amendment"])
        self.assertFalse(edges[0]["required_action_verified"])
        self.assertFalse(edges[0]["operational_program_verified"])

    def test_incomplete_official_search_resumes_next_offset_and_page(self):
        state=new_state()
        primary=document_key("law","5","90")
        state["documents"][primary]={
            "id":primary,"source":"law","stable_id":"5","serial":"90",
            "title":"가상공공정책법","published_at":"2026-11-09",
            "ministry":"가상행정부","url":"https://www.law.go.kr/법령/가상공공정책법"
        }
        state["findings"][primary]={
            "status":"compared","changes":[{"article":"제3조"}]
        }
        class FakeAPI:
            def __init__(self):
                self.pages=[]
                self.details=[]
            def request(self,endpoint,target,**params):
                if target!="ordin":
                    return ET.fromstring("<Root><totalCnt>0</totalCnt></Root>")
                page=params.get("page",1)
                self.pages.append(page)
                records=([("11","101"),("12","102")] if page==1
                         else [("13","103")])
                xml="".join(
                    "<law><자치법규명>가상자치규칙"+stable+
                    "</자치법규명><자치법규ID>"+stable+
                    "</자치법규ID><자치법규일련번호>"+serial+
                    "</자치법규일련번호><공포일자>20261109</공포일자>"+
                    "<지자체명>가상자치단체</지자체명></law>"
                    for stable,serial in records)
                return ET.fromstring("<Root><totalCnt>3</totalCnt>"+xml+"</Root>")
            def detail(self,doc):
                self.details.append(doc["id"])
                return ET.fromstring("""<Root><조문단위>
                    <조문번호>7</조문번호>
                    <조문내용>「가상공공정책법」 제3조에 따라 업무를 검토한다.</조문내용>
                    </조문단위></Root>""")
        api=FakeAPI()
        for _ in range(3):
            discover_dependents(api,state,limit_events=1,page_size=2,
                                max_bodies_per_source=1)
        self.assertEqual(api.pages,[1,1,2])
        self.assertEqual(len(api.details),3)
        self.assertEqual(len(set(api.details)),3)
        self.assertTrue(state["dependency_discovery"][primary]["fully_checked"])
        self.assertEqual(len([
            d for d in state["documents"].values()
            if d.get("reference_only")]),3)
        links=connect_changes(state["findings"],state["versions"],
                              state["documents"])
        self.assertEqual(len(links),3)
        self.assertTrue(all(edge["publishing_agency"]=="가상자치단체"
                            for edge in links))

    def test_search_result_without_matching_article_is_not_evidence(self):
        source_id=document_key("law","5","91")
        source={"id":source_id,"source":"law","title":"가상 금액규정",
                "stable_id":"5","serial":"91","published_at":"2026-11-09",
                "ministry":"가상발령기관","url":"https://www.law.go.kr/a"}
        state=new_state()
        state["documents"][source_id]=source
        state["findings"][source_id]={"status":"compared",
                                     "changes":[{"article":"제3조"}]}
        class FakeAPI:
            def request(self,endpoint,target,**params):
                if target!="law":
                    return ET.fromstring("<Root><totalCnt>0</totalCnt></Root>")
                return ET.fromstring("""<Root><totalCnt>1</totalCnt><law>
                  <법령명한글>가상 후속규칙</법령명한글>
                  <법령ID>6</법령ID><법령일련번호>80</법령일련번호>
                  <공포일자>20261109</공포일자></law></Root>""")
            def detail(self,doc):
                return ET.fromstring("""<Root><조문단위><조문번호>8</조문번호>
                  <조문내용>「가상 금액규정」 제9조를 적용한다.</조문내용>
                  </조문단위></Root>""")
        results=discover_dependents(FakeAPI(),state,limit_events=1)
        self.assertEqual(results["exact_article_references"],0)
        self.assertEqual(len(state["versions"]),0)
        self.assertEqual(len(state["documents"]),1)


if __name__=="__main__":
    unittest.main()
