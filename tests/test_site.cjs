const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const html = fs.readFileSync("site/index.html","utf8");
const appSource = fs.readFileSync('site/app.js','utf8');
const viewSource = fs.readFileSync('site/presentation.js','utf8');
const styleSource = fs.readFileSync('site/styles.css','utf8');
assert.ok(html.includes('<script src="./app.js"></script>'),"UI controller must load externally");
assert.ok(html.indexOf('presentation.js') < html.indexOf('app.js'),"View model must load before DOM controller");
assert.ok(html.includes('<link rel="stylesheet" href="./styles.css">'),"UI style must load externally");
new vm.Script(viewSource,{filename:'site/presentation.js'});
new vm.Script(appSource,{filename:'site/app.js'});
const source = html+'\n'+appSource;
for(const word of [
  "① 실제 변경 내용","② 기관별 변경 검토사항",
  "operational_program_verified","required_action_verified",
  'fetch("./data.json"'
]){
  assert.ok((source+'\n'+viewSource).includes(word),"Missing evidence-first feature: "+word);
}
for(const deprecated of ['data-law="organization"','data-law="lifecycle"']){
  assert.ok(!source.includes(deprecated),"Unrequested filter: "+deprecated);
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
    program_dependencies:override?.program_dependencies||[],
    ai_status:override?.ai_status||"not_run",
    cross_document_review_candidates:override?.cross_document_review_candidates||[],
    generated_at:"",
  })});
  const context={
    document,window:win,history,location,fetch,URL,console,
    encodeURIComponent,decodeURIComponent,
  };
  vm.runInNewContext(viewSource,context,{filename:"site/presentation.js"});
  vm.runInNewContext(appSource,context,{filename:"site/app.js"});
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
    actor:"가상청장",article:"제3조",review:"변경 문구 확인",
    source_url:"https://www.law.go.kr/법령/example",
    operational_program_verified:false,required_action_verified:false,
  }];
  substantive.analysis.review_candidates=[{
    article:"제3조",category:"금액·비율",review:"기관 미배정 검토 후보",
  }];
  const structural=sample("c2","일부개정","compared","2026-11-08","조직·정원");
  const newPolicy=sample("n1","제정","enactment","2026-11-09");
  const repealed=sample("r1","폐지","repeal","2026-11-04");
  const later=sample("c3","일부개정","compared","2026-11-10","기한·절차");
  const pending=sample("p1","일부개정","queued","2026-11-11");
  const docs=[substantive,structural,newPolicy,repealed,later,pending];

  const citation={source_event_id:"c1",referencing_document_id:"r1",
    relationship:"verified_exact_article_citation",
    operational_program_verified:false,required_action_verified:false,
    referencing_title:"가상 규정",referencing_article:"제7조",changed_article:"제3조",
    reference_quote:"「가상 c1 정책」 제3조",referencing_source_url:"https://www.law.go.kr/법령/example"};
  const verified={...citation,referencing_document_id:"r2",
    verified_agency:"가상지원공사",verified_program:"공식 지원업무",
    operational_program_verified:true,required_action_verified:true,
    official_operational_url:"https://www.law.go.kr/법령/example",
    required_review:"변경 전후 지급기준을 지원업무에 적용할지 검토"};
  const verified2={...verified,referencing_document_id:"r3",
    verified_agency:"가상행정청",verified_program:"공식 심사업무"};
  const cross=[{source_event_id:"c1",actor:"가상보건청장",
    work_regulation:"가상 집행규정",target_location:"제7조",
    review:"사업 적용 여부 추가 확인",source_url:"https://www.law.go.kr/법령/example",
    operational_program_verified:false,required_action_verified:false}];

  const ui=setupBrowser(true,"",{documents:docs,relationships:[citation,verified,verified2],
                                    cross_document_review_candidates:cross});
  await flush();
  assert.deepEqual(cardIds(ui),["p1","c3","n1","c2","c1","r1"],
    "Latest official changes must be the default even if comparison is queued");
  assert.equal(ui.dom.get("mode-all").getAttribute("aria-pressed"),"true");
  ui.dom.get("mode-new").onclick();
  assert.deepEqual(cardIds(ui),["n1"]);
  ui.dom.get("mode-amended").onclick();
  assert.deepEqual(cardIds(ui),["p1","c3","c2","c1"]);
  ui.dom.get("mode-repealed").onclick();
  assert.deepEqual(cardIds(ui),["r1"]);
  ui.dom.get("mode-all").onclick();
  ui.dom.get("search").oninput({target:{value:"가상 c1"}});
  assert.deepEqual(cardIds(ui),["c1"]);
  ui.dom.get("search").oninput({target:{value:""}});
  ui.dom.get("items").children[4].onclick();

  const nodes=()=>flattened(ui.dom.get("detail"));
  const tabs=()=>nodes().filter(x=>x.dataset.agencyFilter!==undefined);
  assert.deepEqual(tabs().map(x=>x.dataset.agencyFilter),
    ["all","가상지원공사","가상행정청"],
    "Only institutionally verified program duties qualify for action filters");
  const section=()=>nodes().find(x=>x.tag==="section" &&
    flattened(x).some(y=>y.tag==="h3" && y.textContent.includes("② 기관별")));
  const actionText=()=>flattened(section()).filter(x=>x.className==="agency-group")
    .flatMap(flattened).map(x=>x.textContent).join(" ");
  assert.ok(actionText().includes("공식 지원업무"));
  assert.ok(!actionText().includes("가상청장") &&
            !actionText().includes("가상보건청장"),
    "Statutory actor mentions must NOT be represented as verified actions");
  tabs().find(x=>x.dataset.agencyFilter==="가상행정청").onclick();
  assert.ok(actionText().includes("가상행정청"));
  assert.ok(!actionText().includes("가상지원공사"),
    "Agency-name filtering must not leak other agency's actions");

  const evidenceDrawer=nodes().find(x=>x.tag==="details"&&
    x.className==="evidence-drawer");
  assert.ok(evidenceDrawer,"Investigative leads stay available in a collapsed disclosure");
  const leads=flattened(evidenceDrawer).map(x=>x.textContent).join(" ");
  assert.ok(leads.includes("가상청장")&&leads.includes("가상보건청장"));
  assert.ok(!actionText().includes("기관 미배정 검토 후보"),
    "Generic source-clause review topics must not masquerade as institution duties");

  const unverified=setupBrowser(true,"",{documents:[substantive],
    relationships:[citation],cross_document_review_candidates:cross});
  await flush();
  unverified.dom.get("items").children[0].onclick();
  const unverifiedNodes=flattened(unverified.dom.get("detail"));
  assert.equal(unverifiedNodes.filter(x=>x.dataset.agencyFilter!==undefined).length,0);
  assert.ok(unverifiedNodes.some(x=>x.className==="agency-empty"&&
    x.textContent.includes("아직 없습니다")),
    "No proven program actions must show an honest empty result");

  ui.dom.get("backToList").onclick();
  assert.equal(ui.dom.get("layout").classList.contains("detail-open"),false);
  assert.deepEqual(cardIds(ui),["p1","c3","n1","c2","c1","r1"]);

  const largeBefore="제3조 앞 내용 "+"가".repeat(1200)+" 20만원 지급한다.";
  const largeAfter="제3조 앞 내용 "+"가".repeat(1200)+" 30만원 지급한다.";
  const long=sample("long","일부개정","compared","2026-11-10");
  long.analysis.changes=[{
    article:"제3조",category:"금액·비율",before:largeBefore,after:largeAfter,
    actual_edits:[{old_excerpt:"지원 기준 20만원 지급",new_excerpt:"지원 기준 30만원 지급"}],
    old_values:["20만원"],new_values:["30만원"],
    source_url:"https://www.law.go.kr/법령/example"
  }];
  const detail=setupBrowser(true,"",{documents:[long]});
  await flush();
  detail.dom.get("items").children[0].onclick();
  const rendered=flattened(detail.dom.get("detail"));
  const disclosure=rendered.find(x=>x.tag==="details"&&x.className==="original-drawer");
  assert.ok(disclosure,"Full text must be collapsed by default");
  assert.ok(rendered.some(x=>x.tag==="mark"&&x.textContent==="20"));
  assert.ok(rendered.some(x=>x.tag==="mark"&&x.textContent==="30"));
  assert.ok(flattened(disclosure).some(x=>x.textContent.includes("가".repeat(300))));
  console.log("PASS: latest-first, actual duties separated from research leads, focused comparison");
}
async function verifyAIProgramEvidence(){
  const document=sample("ai1","일부개정","compared","2026-11-10","금액·비율");
  const official={
    source_event_id:"ai1",changed_article:"제3조",agency:"가상장학공사",
    program:"학비지원 운영사업",program_id:"official-program-1",
    referenced_article:"제3조",path:"direct",
    verification:"verified_program_citation",operational_program_verified:true,
    required_action_verified:false,
    review:"지급금액 적용 여부를 기관에서 확인",
    citation_quote:"「가상 ai1 정책」 제3조에 따른 지급기준",
    program_url:"https://www.alioplus.go.kr/business/bsnDetail.do?bsnSeq=814&bsnTyp=DET"
  };
  document.analysis.ai={
    status:"generated",source_sha256:"f".repeat(64),model:"gemini-3.1-flash-lite",
    generated_at:"2026-11-10T03:00:00Z",required_action_verified:false,
    change_reviews:[{
      article:"제3조",summary:"지급액이 달라짐",
      before_quote:"20만원",after_quote:"30만원",
      review_question:"지급액 변경을 사업 기준에 적용할지 확인할까?"
    }],
    program_reviews:[{
      program_id:"official-program-1",article:"제3조",agency:"가상장학공사",
      program_quote:"「가상 ai1 정책」 제3조",
      reason:"공식 인용 사업의 적용 대상이 달라질 수 있음",
      review_question:"신구 지급 기준을 사업 공고와 대조해야 하는가?"
    }]
  };
  const ui=setupBrowser(true,"",{
    documents:[document],program_dependencies:[official],ai_status:"generated"
  });
  await flush();
  ui.dom.get("items").children[0].onclick();
  const nodes=flattened(ui.dom.get("detail"));
  const all=nodes.map(x=>x.textContent).join(" ");
  assert.ok(all.includes("가상장학공사"));
  assert.ok(all.includes("학비지원 운영사업"));
  assert.ok(all.includes("공식 사업자료에서 제3조 인용 확인"));
  assert.ok(all.includes("AI 업무 검토 초안"));
  assert.ok(all.includes("신구 지급 기준을 사업 공고와 대조"));
  assert.ok(all.includes("③ AI 변경 영향 분석"));
  assert.ok(all.includes("지급액 변경을 사업 기준에 적용할지"));
  assert.ok(nodes.some(x=>x.tag==="a"&&x.href===official.program_url),
    "Official program URLs should be reachable");
  assert.deepEqual(nodes.filter(x=>x.dataset.agencyFilter!==undefined)
    .map(x=>x.dataset.agencyFilter),["all","가상장학공사"]);
  const noAI=setupBrowser(true,"",{
    documents:[sample("plain","일부개정","compared","2026-11-10","금액·비율")],
    ai_status:"not_configured"
  });
  await flush();
  noAI.dom.get("items").children[0].onclick();
  const texts=flattened(noAI.dom.get("detail")).map(x=>x.textContent).join(" ");
  assert.ok(texts.includes("AI 분석 미실행"));
  assert.ok(!texts.includes("③ AI 변경 영향 분석"),
    "Missing credentials must not produce synthetic AI inference");
  const partial=setupBrowser(true,"",{
    documents:[sample("pending","일부개정","compared","2026-11-10","금액·비율")],
    ai_status:"partial_generated"
  });
  await flush();
  partial.dom.get("items").children[0].onclick();
  const partialText=flattened(partial.dom.get("detail"))
    .map(x=>x.textContent).join(" ");
  assert.ok(partialText.includes("AI 검토 일부 생성됨"),
    "Partial model output must not be labeled as a total pipeline failure");
  assert.ok(!partialText.includes("검증 실패"),
    "A transient overload does not imply the quoted evidence failed");
  console.log("PASS: official program links and clearly labeled AI proposals");
}
Promise.all([verifyNavigation(),verifyRealFilters(),verifyAIProgramEvidence()]).catch(error=>{
  console.error(error);process.exitCode=1;
});

