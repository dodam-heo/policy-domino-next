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
      "filter-explain","mode-all","mode-new","mode-amended",
      "mode-repealed","mode-pending","sort-verified","sort-latest"];
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
  // Full official catalogue stays visible: never hide structural changes,
  // enactments, repeals or incomplete source records behind a fake rating.
  assert.deepEqual(cardIds(ui),["c3","c2","c1","n1","r1","p1"]);
  assert.equal(ui.dom.get("mode-all").getAttribute("aria-pressed"),"true");
  ui.dom.get("sort-latest").onclick();
  assert.deepEqual(cardIds(ui),["p1","c3","n1","c2","c1","r1"]);
  ui.dom.get("sort-verified").onclick();
  assert.deepEqual(cardIds(ui),["c3","c2","c1","n1","r1","p1"]);
  ui.dom.get("mode-pending").onclick();
  assert.deepEqual(cardIds(ui),["p1"],"Pending data is searchable without fabricated changes");
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
  ui.dom.get("items").children[2].onclick(); // c1 source with 2 named actors
  assert.equal(ui.dom.get("layout").classList.contains("detail-open"),true);
  const filterButtons=()=>flattened(ui.dom.get("detail"))
    .filter(x=>x.dataset.agencyFilter!==undefined);
  let tabs=filterButtons();
  assert.deepEqual(tabs.map(x=>x.dataset.agencyFilter),
    ["all","가상보건청장","가상청장"]);
  assert.ok(!tabs.some(x=>x.textContent.includes("집행기관 추가 조사")),
    "Never invent a fake agency name for unassigned source clauses");
  tabs.find(x=>x.dataset.agencyFilter==="가상청장").onclick();
  tabs=filterButtons();
  assert.equal(tabs.find(x=>x.dataset.agencyFilter==="가상청장")
    .getAttribute("aria-pressed"),"true");
  const impacts=()=>flattened(ui.dom.get("detail")).find(
    x=>x.tag==="section" && flattened(x).some(child=>
      child.tag==="h3" && child.textContent.includes("② 기관별")));
  const sectionText=()=>flattened(impacts()).filter(x=>x.className==="agency-group")
    .flatMap(flattened).map(x=>x.textContent).join(" ");
  assert.ok(sectionText().includes("가상청장"),"Statutory named actor must appear");
  assert.ok(!sectionText().includes("가상보건청장"),
    "Selecting a named actor must filter other agencies out");
  assert.ok(!sectionText().includes("담당 집행기관 추가 조사"),
    "Unassigned clause is not an institution");
  tabs.find(x=>x.dataset.agencyFilter==="가상보건청장").onclick();
  assert.ok(sectionText().includes("가상보건청장"),
    "Different agency must show its own separately evidenced duties");
  assert.ok(!sectionText().includes("가상청장"),
    "Other actors must be excluded from selected agency cards");
  ui.dom.get("backToList").onclick();
  assert.equal(ui.dom.get("layout").classList.contains("detail-open"),false);
  assert.deepEqual(cardIds(ui),["c3","c2","c1","n1","r1","p1"],
    "Mobile back should preserve filters and verified sort");
  // Long official before/after must be present ONLY within collapsed disclosure.
  const largeBefore="제3조 앞 내용 "+"가".repeat(1200)+" 20만원 지급한다.";
  const largeAfter ="제3조 앞 내용 "+"가".repeat(1200)+" 30만원 지급한다.";
  const long=sample("long","일부개정","compared","2026-11-10");
  long.analysis.changes=[{
    article:"제3조",category:"금액·비율",
    before:largeBefore,after:largeAfter,
    actual_edits:[{old_excerpt:"지원 기준 20만원 지급",new_excerpt:"지원 기준 30만원 지급"}],
    old_values:["20만원"],new_values:["30만원"],
    source_url:"https://www.law.go.kr/법령/example"
  }];
  const detail=setupBrowser(true,"",{documents:[long]});
  await flush();
  detail.dom.get("items").children[0].onclick();
  const rendered=flattened(detail.dom.get("detail"));
  const disclosure=rendered.find(x=>x.tag==="details");
  assert.ok(disclosure,"Full original clauses should be hidden in a disclosure");
  assert.ok(rendered.some(x=>x.tag==="mark"&&x.textContent==="20"),
    "Before changed digits must be highlighted");
  assert.ok(rendered.some(x=>x.tag==="mark"&&x.textContent==="30"),
    "After changed digits must be highlighted");
  assert.ok(disclosure.children.some(x=>x.tag==="summary"),
    "A clear show-full-text control is required");
  assert.ok(flattened(disclosure).some(x=>x.textContent.includes("가".repeat(300))),
    "Entire official text must remain available on demand");
  assert.ok(!flattened(detail.dom.get("detail")).some(
    x=>x.tag==="div" && x.className==="before" &&
    x.children.some(z=>z.tag==="mark") &&
    x.textContent.includes("가".repeat(300))),
    "Default changed-text preview must not print a full giant provision");
  console.log("PASS: trustworthy source filters, agency-name filters, compact highlighted clause diff and mobile navigation");
}
Promise.all([verifyNavigation(),verifyRealFilters()]).catch(error=>{
  console.error(error);process.exitCode=1;
});

