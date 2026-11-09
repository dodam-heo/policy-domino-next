const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("site/index.html","utf8");
const inline = html.match(/<script>\s*([\s\S]*?)<\/script>/);
assert.ok(inline,"The maintained page must have its renderer");
new vm.Script(inline[1],{filename:"site/index.html"});
for(const word of [
  "① 정책에서 실제 바뀐 내용","② 기관별 변경 검토사항",
  "③ 변경 조문을 직접 인용하는 관련 규정",
  "④ 원문 변경에 따른 추가 검토 후보",
  "operational_program_verified","required_action_verified",
  'fetch("./data.json"'
]){
  assert.ok(html.includes(word),"Missing source-evidence feature: "+word);
}
for(const deprecated of ['data-law="organization"','data-law="lifecycle"']){
  assert.ok(!html.includes(deprecated),"Unrequested filter: "+deprecated);
}
const json=JSON.parse(fs.readFileSync("site/data.json","utf8"));
assert.equal(json.schema,"policy-domino-next-v1");
assert.ok(Array.isArray(json.documents));
assert.ok(Array.isArray(json.relationships));
assert.equal(json.principles.manual_institutions,false);
console.log("PASS: independent source-grounded interface contract");


// A real click-flow regression: synthetic browser DOM, no external library.
// Verifies that mobile opens a separate detail view instead of stacking below
// the list; also checks the back control and browser history navigation.
class FakeClassList {
  constructor(){this.values=new Set();}
  add(x){this.values.add(x);}
  remove(x){this.values.delete(x);}
  contains(x){return this.values.has(x);}
}
class FakeElement {
  constructor(tag="div"){
    this.tag=tag;this.children=[];this.classList=new FakeClassList();
    this.dataset={};this.hidden=false;this.textContent="";this.onclick=null;
    this.attributes={};
  }
  setAttribute(name,value){this.attributes[name]=String(value);}
  getAttribute(name){return this.attributes[name]??null;}
  appendChild(x){this.children.push(x);return x;}
  replaceChildren(...children){this.children=[...children];}
}
function setupBrowser(mobile=true,initialHash="",override=null){
  const ids=["layout","listPanel","detailPanel","detail","items","feed-state",
      "indexed","compared","pending","links","updated","search","more","backToList",
      "filter-explain","mode-substantive","mode-new","mode-amended",
      "mode-repealed","mode-all","sort-impact","sort-latest"];
  const dom=new Map(ids.map(x=>[x,new FakeElement()]));
  const body=new FakeElement("body");
  const listeners={};
  const location={hash:initialHash,pathname:"/policy-domino-next/",search:""};
  const calls={push:[],replace:[],scrolls:0};
  const win={
    matchMedia:()=>({matches:mobile}),
    scrollTo:()=>{calls.scrolls++;},
    addEventListener:(k,fn)=>{listeners[k]=fn;},
  };
  const history={
    pushState:(state,title,url)=>{calls.push.push(url);location.hash=url;},
    replaceState:(state,title,url)=>{
      calls.replace.push(url);
      location.hash=(url.match(/#.*$/)||[])[0]||"";
    },
  };
  const document={
    body,
    getElementById:id=>{
      if(!dom.has(id))throw Error("Unexpected missing element: "+id);
      return dom.get(id);
    },
    createElement:tag=>new FakeElement(tag),
  };
  const fakeDocs=[0,1].map(i=>({
    id:"policy"+i,source:"law",kind:"법령",
    title:"가상 규정 "+i, ministry:"가상 부처",
    published_at:"2026-11-09",url:"https://www.law.go.kr/법령/test",
    analysis:{status:"compared",changes:[],review_candidates:[],
              direct_actor_reviews:[],reason:"가상 데이터"},
  }));
  const fetch=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({
    schema:"policy-domino-next-v1",configuration:"running",
    documents:override?.documents||fakeDocs,
    relationships:override?.relationships||[],quality:{},
    cross_document_review_candidates:override?.cross_document_review_candidates||[],
    generated_at:"",
  })});
  vm.runInNewContext(inline[1],{
    document,window:win,history,location,fetch,URL,console,
    encodeURIComponent,decodeURIComponent,
  },{filename:"site/index.html"});
  return {dom,body,listeners,location,calls};
}
async function flush(){
  await new Promise(resolve=>setImmediate(resolve));
}
async function verifyNavigation(){
  const mobile=setupBrowser(true);
  await flush();
  assert.equal(mobile.dom.get("items").children.length,2);
  assert.equal(mobile.dom.get("layout").classList.contains("detail-open"),false,
    "Mobile must start as a standalone list view");
  assert.equal(mobile.body.classList.contains("detail-active"),false);
  mobile.dom.get("items").children[1].onclick();
  assert.equal(mobile.dom.get("layout").classList.contains("detail-open"),true,
    "Mobile card tap must switch to the detail view");
  assert.equal(mobile.body.classList.contains("detail-active"),true);
  assert.equal(mobile.location.hash,"#change=policy1");
  assert.ok(mobile.calls.scrolls>0,"Detail must be scrolled into view immediately");
  assert.ok(mobile.dom.get("detail").children.length>0);
  mobile.dom.get("backToList").onclick();
  assert.equal(mobile.dom.get("layout").classList.contains("detail-open"),false);
  assert.equal(mobile.body.classList.contains("detail-active"),false);
  assert.equal(mobile.location.hash,"");
  // Android/system back button must also return to the list.
  mobile.dom.get("items").children[0].onclick();
  mobile.location.hash="";
  mobile.listeners.popstate();
  assert.equal(mobile.dom.get("layout").classList.contains("detail-open"),false);
  // Direct-linked policy page should open in detail mode without tapping list.
  const deep=setupBrowser(true,"#change=policy0");
  await flush();
  assert.equal(deep.dom.get("layout").classList.contains("detail-open"),true);
  // Desktop retains side-by-side selection behavior.
  const desktop=setupBrowser(false);
  await flush();
  assert.equal(desktop.dom.get("layout").classList.contains("detail-open"),false);
  assert.ok(desktop.dom.get("detail").children.length>0);
  desktop.dom.get("items").children[1].onclick();
  assert.equal(desktop.dom.get("layout").classList.contains("detail-open"),false);
  console.log("PASS: mobile tap -> detail -> back, browser back, deep link and desktop");
}

function flattened(el){
  return [el,...(el.children||[]).flatMap(flattened)];
}
function cardIds(ctx){return ctx.dom.get("items").children.map(x=>x.dataset.id);}
function sample(id,revision,status,date,category=null){
  const text=category ? [{
    article:"제3조",category,before:"제3조 지급금액 20만원",
    after:"제3조 지급금액 30만원",actual_edits:[],
    old_values:["20만원"],new_values:["30만원"],
    source_url:"https://www.law.go.kr/법령/example",
  }] : [];
  return {
    id,title:"가상 "+id+" 정책",source:"law",kind:"대통령령",
    revision,published_at:date,ministry:"가상 공공기관",
    url:"https://www.law.go.kr/법령/example",
    analysis:{status,changes:text,review_candidates:[],
              direct_actor_reviews:[],reason:"합성 테스트"},
  };
}
async function verifyRealFilters(){
  const substantive=sample("c1","일부개정","compared","2026-11-07","금액·비율");
  substantive.analysis.direct_actor_reviews=[{
    actor:"가상청장",article:"제3조",review:"신규 지급액 기준 대조",
    source_url:"https://www.law.go.kr/법령/example",
  }];
  substantive.analysis.review_candidates=[{
    article:"제3조",category:"금액·비율",
    review:"공공부문 사업 적용 관계 재검증",
    source_url:"https://www.law.go.kr/법령/example",
  }];
  const structural=sample("c2","일부개정","compared","2026-11-08","조직·정원");
  const newPolicy=sample("n1","제정","enactment","2026-11-09");
  const repealed=sample("r1","폐지","repeal","2026-11-04");
  const newerSubstantive=sample("c3","일부개정","compared","2026-11-10","기한·절차");
  const pending=sample("p1","일부개정","queued","2026-11-11");
  const docs=[substantive,structural,newPolicy,repealed,newerSubstantive,pending];
  const rel=[
    {source_event_id:"c1",referencing_document_id:"a",relationship:"verified_exact_article_citation",
      operational_program_verified:false,required_action_verified:false,
      referencing_title:"가상 집행규정",referencing_article:"제7조",changed_article:"제3조",
      publishing_agency:"가상청",reference_quote:"「가상 c1 정책」 제3조를 인용한다.",
      referencing_source_url:"https://www.law.go.kr/법령/example"},
    {source_event_id:"c1",referencing_document_id:"b",relationship:"verified_exact_article_citation",
      operational_program_verified:false,required_action_verified:false,
      referencing_title:"가상 시행규칙",referencing_article:"제4조",changed_article:"제3조",
      publishing_agency:"가상청",reference_quote:"「가상 c1 정책」 제3조를 인용한다.",
      referencing_source_url:"https://www.law.go.kr/법령/example"},
  ];
  const cross=[{source_event_id:"c1",actor:"가상보건청장",
    work_regulation:"가상 집행규정",target_location:"제7조",
    review:"가상 사업의 기준 대조",source_url:"https://www.law.go.kr/법령/example",
    operational_program_verified:false,required_action_verified:false}];
  const ui=setupBrowser(true,"",{documents:docs,relationships:rel,
                                    cross_document_review_candidates:cross});
  await flush();
  // Screenshot: '실질 정책 변경' is the default: actual non-structural deltas only.
  assert.deepEqual(cardIds(ui),["c1","c3"],"Default substantive policy filter");
  assert.equal(ui.dom.get("mode-substantive").getAttribute("aria-pressed"),"true");
  ui.dom.get("sort-latest").onclick();
  assert.deepEqual(cardIds(ui),["c3","c1"],"Latest should sort independently");
  ui.dom.get("sort-impact").onclick();
  assert.deepEqual(cardIds(ui),["c1","c3"],"Verified citation count should sort first");
  ui.dom.get("mode-all").onclick();
  assert.equal(cardIds(ui).length,6,"Full catalogue must preserve all events");
  ui.dom.get("mode-new").onclick();
  assert.deepEqual(cardIds(ui),["n1"]);
  ui.dom.get("mode-amended").onclick();
  assert.deepEqual(new Set(cardIds(ui)),new Set(["c1","c2","c3","p1"]));
  ui.dom.get("mode-repealed").onclick();
  assert.deepEqual(cardIds(ui),["r1"]);
  ui.dom.get("mode-all").onclick();
  ui.dom.get("search").oninput({target:{value:"가상 c2"}});
  assert.deepEqual(cardIds(ui),["c2"],"Search must apply to the selected mode");
  ui.dom.get("search").oninput({target:{value:""}});
  ui.dom.get("mode-substantive").onclick();
  ui.dom.get("items").children[0].onclick();
  assert.equal(ui.dom.get("layout").classList.contains("detail-open"),true);
  const filterButtons=()=>flattened(ui.dom.get("detail"))
    .filter(x=>x.dataset.reviewFilter!==undefined);
  let tabs=filterButtons();
  assert.deepEqual(tabs.map(x=>x.dataset.reviewFilter),
    ["all","action","source","research"]);
  assert.ok(tabs.find(x=>x.dataset.reviewFilter==="source").textContent.includes("2"));
  assert.ok(tabs.find(x=>x.dataset.reviewFilter==="research").textContent.includes("1"));
  tabs.find(x=>x.dataset.reviewFilter==="source").onclick();
  tabs=filterButtons();
  assert.equal(tabs.find(x=>x.dataset.reviewFilter==="source").getAttribute("aria-pressed"),"true");
  const allText=()=>flattened(ui.dom.get("detail")).map(x=>x.textContent).join(" ");
  assert.ok(allText().includes("가상청장"),"Statutory actor visible under source tab");
  assert.ok(!allText().includes("담당 집행기관 추가 조사"),"Investigation tab excluded");
  tabs.find(x=>x.dataset.reviewFilter==="research").onclick();
  assert.ok(allText().includes("담당 집행기관 추가 조사"),"Research tab shows only unassigned sources");
  assert.ok(!allText().includes("가상보건청장"),"Source tab excluded");
  ui.dom.get("backToList").onclick();
  assert.equal(ui.dom.get("layout").classList.contains("detail-open"),false);
  assert.deepEqual(cardIds(ui),["c1","c3"],"Mobile back should preserve filters");
  console.log("PASS: seven restored list filters, independent sorting, agency review tabs and mobile navigation");
}
Promise.all([verifyNavigation(),verifyRealFilters()]).catch(error=>{
  console.error(error);process.exitCode=1;
});

