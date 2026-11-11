/* Integrated interface contract: official *events*, not raw law index rows. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");

const html=fs.readFileSync("site/index.html","utf8");
const app=fs.readFileSync("site/app.js","utf8");
const presenter=fs.readFileSync("site/presentation.js","utf8");
const style=fs.readFileSync("site/styles.css","utf8");
new vm.Script(app,{filename:"site/app.js"});
new vm.Script(presenter,{filename:"site/presentation.js"});
assert.ok(html.indexOf('src="./presentation.js"')<html.indexOf('src="./app.js"'));
assert.ok(html.includes('class="site-header"'),"The navy topbar must remain");
assert.ok(html.includes("정책이 바뀌면, 무엇을 고쳐야 할까?"),"The compact hero must remain");
assert.ok(style.includes(".site-header"),"The nav bar must be visibly styled");
assert.ok(!app.includes("원천자료 수집·인용 대조가 더 필요합니다."));
assert.ok(!app.includes("각각의 근거 수준은 구분해 보여줍니다."));
for(const id of ["items","detail","mode-all","mode-new",
                 "mode-amended","mode-repealed","mode-impact",
                 "stat-events","stat-agencies","stat-actions",
                 "stat-change-events","stat-linked-actions",
                 "list-count","search","backToList"]){
  assert.ok(html.includes('id="'+id+'"'),"Missing coherent event UI element "+id);
}
assert.ok(!html.includes("신구 확인"),"Comparison state is not a user browsing category");
assert.ok(!app.includes("agencyFilter"),"Institutional reviews must not be hidden by a filter");
assert.ok(style.includes(".agency-group"),"Impact grouping must be styled");
assert.ok(!app.includes('create("div","impact-assessment")'),
  "Policy detail must not render a numeric impact score breakdown");
assert.ok(style.includes(".agency-directory-modal[hidden]{display:none}"),
  "Modal must obey hidden attribute when not opened");

const existing=JSON.parse(fs.readFileSync("site/catalog.json","utf8"));
assert.equal(existing.schema,"policy-domino-next-v1");
assert.equal(existing.distribution,"split-v1");
assert.ok(Array.isArray(existing.events));
assert.ok(fs.existsSync("site/sources.json"));
assert.ok(!fs.existsSync("site/data.json"),
  "The legacy combined 42MB public file must not be deployed");
console.log("PASS: one event-centered interface, source documents kept as evidence");

class ClassList{
  constructor(){this.set=new Set()}
  add(x){this.set.add(x)}
  remove(x){this.set.delete(x)}
  contains(x){return this.set.has(x)}
}
class Element{
  constructor(tag="div"){
    this.tag=tag;this.className="";this.children=[];this.textContent="";
    this.classList=new ClassList();this.dataset={};this.hidden=false;
    this.attributes={};this.onclick=null;this.oninput=null;this.value="";
  }
  appendChild(element){this.children.push(element);return element;}
  replaceChildren(...xs){this.children=[...xs]}
  setAttribute(name,value){this.attributes[name]=String(value);}
  getAttribute(name){return this.attributes[name]??null;}
}
const flatten=element=>[element,...element.children.flatMap(flatten)];
const textOf=element=>flatten(element).map(x=>x.textContent).join(" ");
const sample=(id,{date="2026-11-09",kind="amended",impact=false,
                    benefit=false,group=false,ai=false}={})=>{
  const name="가상정책 "+id;
  const a=impact?{
    id:"review-"+id,document_id:"source-"+id,document_title:name,
    institution:"가상공공기관",article:"제3조",category:benefit?"금액·비율":"조직·정원",
    program:"가상 지원운영사업",program_id:"test-program",
    change:"기준 10만원 → 12만원",
    task:"가상 지원운영사업의 적용 금액을 제3조와 대조",
    basis_tier:"verified_program_citation",
    basis_quote:"「가상정책」 제3조를 적용합니다.",
    implementation_status:"not_verified",
    source_url:"https://www.law.go.kr/법령/가상정책",
    program_url:"https://www.alioplus.go.kr/business/bsnDetail.do?bsnSeq=1&bsnTyp=DET"
  }:null;
  const changes=kind==="new"||kind==="repealed"?[]:[{
    document_id:"source-"+id,document_title:name,
    article:"제3조",category:benefit?"금액·수치 기준":"조문 내용 변경",
    brief:"지급 기준 금액이 10만원에서 12만원으로 바뀌었습니다.",
    meaning:{
      label:benefit?"금액·수치 기준":"조문 내용 변경",
      description:"지급 기준 금액이 10만원에서 12만원으로 바뀌었습니다.",
      before:"10만원",after:"12만원",editorial:false,priority:48,edits_count:1,
    },
    before:"10만원",after:"12만원",
    actual_edits:[{old_excerpt:"10만원",new_excerpt:"12만원"}],
    source_url:"https://www.law.go.kr/법령/가상정책",
    evidence:{old_body_sha256:"old",new_body_sha256:"new"}
  }];
  return {
    id,title:name,published_at:date,kind,
    source_count:group?17:1,
    verification:"verified",
    effective_date:"2027-01-01",
    headline:benefit?"금액·비율 관련 변경 · 1개 조문":
      "조직·정원 관련 변경 · 1개 조문",
    members:group?[{title:name,url:"https://www.law.go.kr/법령/가상정책"}]:[],
    changes,
    highlights:changes.map(ch=>({document_id:ch.document_id,article:ch.article})),
    institutional_reviews:a?[a]:[],
    institution_count:a?1:0,review_count:a?1:0,
    dependent_rules:[],ai_count:ai?1:0,
    ai_summaries:ai?[{
      document_id:"source-"+id,article:"제3조",
      summary:"금액 기준 변경 검토",
      question:"지급기준을 대조할 필요가 있는가?",
      before_quote:"10만원",after_quote:"12만원"
    }]:[],
  };
};
const items=[
  sample("amended", {date:"2026-11-10",impact:true,benefit:true,group:true,ai:true}),
  sample("new", {date:"2026-11-09",kind:"new"}),
  sample("ordinary",{date:"2026-11-08"}),
  sample("repealed",{date:"2026-11-07",kind:"repealed"}),
];
const payload={
  schema:"policy-domino-next-v1",
  events:items,
  quality:{analysis_status:{
    indexed:10166,checked:101,partially_checked:40,
    unexamined:9840,retryable:204,blocked:21,
  }},
  collection_run:{failed_windows:2},
  ai_progress:{
    indexed_documents:10166,verified_document_changes:101,
    verified_clauses:468,ai_analyzed_clauses:24,
    institutional_reviews:2,verified_program_links:1,
    referencing_public_rule_reviews:1,official_program_records:15,
  },
  ai_run:{
    attempted:24,generated:9,errors:15,
    stopped_reason:"request_budget",
    checked_at:"2026-11-10T09:33:59+00:00",
  },
  agency_directory:[
    {agency:"가상공공기관",alioplus_programs:1,gov24_services:2},
    {agency:"가상교육청",alioplus_programs:0,gov24_services:1},
    {agency:"가상복지공단",alioplus_programs:3,gov24_services:0},
  ],
  generated_at:"2026-11-10T05:00:00+00:00",
};
function browser(isMobile=false,hash="",data=payload,remote={}) {
  const ids=["layout","listPanel","detailPanel","detail","items",
    "stat-events","stat-agencies","stat-actions",
    "stat-change-events","stat-linked-actions","list-count",
    "ai-review-progress","institution-link-progress",
    "agency-directory-open","agency-directory-close",
    "agency-directory-modal","agency-directory-backdrop",
    "agency-directory-search","agency-directory-results",
    "agency-directory-count",
    "search","updated","more","backToList",
    "mode-all","mode-new","mode-amended","mode-repealed","mode-impact"];
  const elements=new Map(ids.map(id=>[id,new Element()]));
  const body=new Element("body");
  const historyCalls=[];
  const here={hash,pathname:"/policy-domino-next/",search:""};
  const callbacks={};
  const win={
    matchMedia:()=>({matches:isMobile}),
    scrollTo:()=>{},
    addEventListener:(name,fn)=>{callbacks[name]=fn},
  };
  const history={
    pushState:(_,__,to)=>{historyCalls.push(to);here.hash=to},
    replaceState:(_,__,to)=>{here.hash=(to.match(/#.*$/)||[])[0]||""},
  };
  const dom={
    body,
    getElementById:id=>{
      if(!elements.has(id))throw Error("Unexpected document element "+id);
      return elements.get(id);
    },
    createElement:tag=>new Element(tag),
  };
  const fetchCalls=[];
  const fetch=(path)=>{
    fetchCalls.push(path);
    const match=String(path).match(/^\.\/details\/([^/]+)\.json$/);
    const value=match ? (remote.details?.[match[1]] ??
      data.events.find(event=>event.id===match[1])) :
      (path==="./sources.json" ?
        {documents:remote.sources??data.documents??[]} : data);
    return Promise.resolve({ok:value!==undefined,
      json:()=>Promise.resolve(value)});
  };
  vm.runInNewContext(presenter,{window:win,console},
                     {filename:"site/presentation.js"});
  vm.runInNewContext(app,{
    window:win,document:dom,history,location:here,fetch,URL,
    console,encodeURIComponent,decodeURIComponent
  },{filename:"site/app.js"});
  return {elements,body,historyCalls,here,callbacks,win,fetchCalls};
}
function node(context,id){return context.elements.get(id)}
async function flush(){await new Promise(resolve=>setImmediate(resolve))}
async function verifiedNavigation(){
  const ui=browser(false);
  await flush();
  assert.equal(node(ui,"stat-events").textContent,"10,166");
  assert.equal(node(ui,"stat-agencies").textContent,"1");
  assert.equal(node(ui,"stat-actions").textContent,"1");
  assert.equal(node(ui,"list-count").textContent,"전체 4건 · 표시 0건");
  assert.equal(node(ui,"mode-impact").getAttribute("aria-pressed"),"true");
  node(ui,"mode-all").onclick();
  assert.equal(node(ui,"list-count").textContent,"전체 4건 · 표시 4건");
  assert.ok(html.includes("공공기관 명부 보기"));
  assert.ok(!html.includes("수집·분석 진도 및 연결 근거 상세"));
  assert.ok(html.includes("공식 정책 변경 · 업무 영향 분석"));
  node(ui,"agency-directory-open").onclick();
  assert.equal(node(ui,"agency-directory-modal").hidden,false);
  node(ui,"agency-directory-close").onclick();
  assert.equal(node(ui,"agency-directory-modal").hidden,true);
  assert.ok(html.includes("정책 변경 목록"));
  assert.ok(html.includes("기본 조회: 영향도 큼 · 최신 변경순"));
  assert.ok(!html.includes("급여·지원기준"));
  assert.ok(!html.includes("filter-grid"));
  assert.ok(html.includes("법령명·정책명·소관기관 검색"));
  assert.equal(node(ui,"items").children.length,4);
  assert.deepEqual(node(ui,"items").children.filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),
                   ["amended","new","ordinary","repealed"]);
  node(ui,"mode-impact").onclick();
  assert.deepEqual(node(ui,"items").children
    .filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),[],
    "A single verified agency must not be mislabeled as high impact");
  assert.equal(node(ui,"list-count").textContent,"전체 4건 · 표시 0건");
  node(ui,"mode-new").onclick();
  assert.deepEqual(node(ui,"items").children.filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),["new"]);
  node(ui,"mode-repealed").onclick();
  assert.deepEqual(node(ui,"items").children.filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),["repealed"]);
  node(ui,"mode-amended").onclick();
  assert.deepEqual(node(ui,"items").children.filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),
    ["amended","ordinary"]);
  node(ui,"mode-all").onclick();
  assert.deepEqual(node(ui,"items").children.filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),
    ["amended","new","ordinary","repealed"]);
  assert.equal(node(ui,"list-count").textContent,"전체 4건 · 표시 4건");
  node(ui,"search").oninput({target:{value:"가상 지원운영사업"}});
  assert.deepEqual(node(ui,"items").children.filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),["amended"]);
  node(ui,"search").oninput({target:{value:""}});
  node(ui,"items").children[0].onclick();
  assert.equal(ui.here.hash,"#event=amended");
  const detail=node(ui,"detail");
  const text=textOf(detail);
  assert.ok(text.includes("가상공공기관"),"Direct affected institution is visible");
  assert.ok(text.includes("가상 지원운영사업의 적용 금액을 제3조와 대조"));
  assert.ok(text.includes("전체 조문·공식 근거 보기"));
  assert.ok(text.includes("동시 개정된 법령 17건"));
  assert.ok(text.includes("AI 보조분석"));
  assert.ok(text.includes("AI 요약"),
    "AI summary should stay on the main change card");
  assert.ok(text.includes("지급 기준 금액이 10만원에서 12만원으로 바뀌었습니다."),
    "Meaningful source-bound sentence must replace the fragmented raw arrow");
  assert.ok(text.includes("변경 전") && text.includes("변경 후"));
  assert.ok(flatten(detail).some(x=>x.className==="original-clause"),
    "Every excerpt must offer a full official-clause comparison on demand");
  assert.ok(!text.includes("그 밖의 조문 변경 관련 변경"),
    "The main event title must not repeat empty machine categories");
  assert.ok(!text.includes("이미 조치 완료"),"No false completion");
  const core=flatten(detail).findIndex(x=>x.className==="detail-section core");
  const impact=flatten(detail).findIndex(x=>x.className==="detail-section" &&
      x.children.some(y=>y.textContent==="기관별 변경·사업 검토사항"));
  const archive=flatten(detail).filter(x=>x.className==="evidence-panel evidence-archive");
  assert.ok(core>=0 && impact>core && archive.length===1,
    "One official evidence archive must remain in the change summary");
  assert.ok(flatten(detail)[core].children.includes(archive[0]));
  assert.ok(!archive[0].open,"Official evidence should start collapsed");
  assert.ok(!text.includes("공식 변경 전·후와 출처"));
  console.log("PASS: policy events, institution/program reviews, search and evidence order");
}
async function effectiveYearAndRenamedAnnualCriteriaSearch(){
  // The official title can change between years and omit the effective year.
  const event=sample("annual-basis",{date:"2026-07-29"});
  event.title="새로운 생활보장 선정기준 및 최저보장수준";
  event.effective_date="2027-01-01";
  const ui=browser(false,"",{
    schema:"policy-domino-next-v1",events:[event],
    ai_progress:{indexed_documents:1},generated_at:"",
  });
  await flush();
  node(ui,"mode-all").onclick();
  node(ui,"search").oninput({target:{value:"2027년 생활보장"}});
  assert.equal(node(ui,"items").children.filter(x=>x.dataset.eventId).length,1);
  node(ui,"search").oninput({target:{value:"2027년도 선정 기준"}});
  assert.equal(node(ui,"items").children.filter(x=>x.dataset.eventId).length,1);
  node(ui,"search").oninput({target:{value:"2027년 무관한상황"}});
  assert.equal(node(ui,"items").children.filter(x=>x.dataset.eventId).length,0);
  console.log("PASS: effective year and renamed annual criteria remain searchable");
}
async function directoryModalNavigation(){
  const ui=browser();await flush();
  node(ui,"agency-directory-open").onclick();
  assert.equal(flatten(node(ui,"agency-directory-results"))
    .filter(x=>x.className==="agency-directory-entry").length,3);
  assert.ok(node(ui,"agency-directory-count").textContent.includes("3곳 중 3곳"));
  node(ui,"agency-directory-search").value="교육청";
  node(ui,"agency-directory-search").oninput({target:{value:"교육청"}});
  const filtered=flatten(node(ui,"agency-directory-results"))
    .filter(x=>x.className==="agency-directory-entry");
  assert.equal(filtered.length,1);
  assert.ok(textOf(filtered[0]).includes("가상교육청"));
  ui.callbacks.keydown({key:"Escape"});
  assert.equal(node(ui,"agency-directory-modal").hidden,true);
  console.log("PASS: searchable modal displays all registered agencies");
}
async function mobileNavigation(){
  const ui=browser(true);
  await flush();
  node(ui,"mode-all").onclick();
  assert.equal(node(ui,"layout").classList.contains("detail-open"),false);
  node(ui,"items").children[0].onclick();
  assert.equal(node(ui,"layout").classList.contains("detail-open"),true);
  assert.equal(ui.here.hash,"#event=amended");
  node(ui,"backToList").onclick();
  assert.equal(ui.here.hash,"");
  assert.equal(node(ui,"layout").classList.contains("detail-open"),false);
  const deep=browser(true,"#event=amended");
  await flush();
  assert.equal(node(deep,"layout").classList.contains("detail-open"),true);
  assert.ok(textOf(node(deep,"detail")).includes("가상공공기관"));
  console.log("PASS: mobile event detail, back, and deep link");
}
async function institutionFilterNavigation(){
  const multi=sample("multi",{date:"2026-11-12",impact:true,group:true});
  const first=multi.institutional_reviews[0];
  multi.institutional_reviews=[
    {...first,id:"r-a",institution:"가상교통공사",task:"교통 운영 변경 대조"},
    {...first,id:"r-b",institution:"가상복지공단",task:"복지 기준 변경 대조"},
    {...first,id:"r-c",institution:"가상교육청",task:"교육 지원 변경 대조"},
  ];
  multi.review_count=3;
  multi.institution_count=3;
  const other=sample("other",{date:"2026-11-11",impact:true});
  other.institutional_reviews[0].institution="다른가상기관";
  const data={schema:"policy-domino-next-v1",events:[multi,other],
    ai_progress:{indexed_documents:80},generated_at:""};
  const ui=browser(false,"",data);
  await flush();
  node(ui,"mode-all").onclick();
  let detail=node(ui,"detail");
  const pick=(root,klass)=>flatten(root).find(x=>x.className===klass);
  const controls=pick(detail,"agency-filter-panel");
  assert.ok(controls,"A policy detail with institutions needs the left agency filter");
  const results=pick(detail,"agency-group-results");
  assert.equal(results.children.length,3,
    "All verified institutional reviews should be visible by default");
  assert.ok(flatten(controls).some(x=>x.textContent==="기관명 필터"));
  const agencyButtons=()=>flatten(controls).filter(x=>x.dataset.institution);
  assert.equal(agencyButtons().length,3);
  const welfare=agencyButtons().find(x=>x.dataset.institution==="가상복지공단");
  welfare.onclick();
  assert.equal(results.children.length,1,
    "Selecting an institution must leave only that institution's review cards");
  assert.ok(textOf(results).includes("복지 기준 변경 대조"));
  assert.ok(!textOf(results).includes("교통 운영 변경 대조"));
  assert.ok(!textOf(results).includes("교육 지원 변경 대조"));
  assert.equal(agencyButtons().find(x=>x.dataset.institution==="가상복지공단")
    .getAttribute("aria-pressed"),"true");
  assert.ok(textOf(detail).includes("1개 기관 · 검토사항 1건"));

  const agencySearch=pick(detail,"agency-filter-search");
  agencySearch.value="교육";
  agencySearch.oninput();
  assert.equal(agencyButtons().length,1,
    "The institution search must filter names from this event, not all projects");
  assert.equal(agencyButtons()[0].dataset.institution,"가상교육청");
  agencySearch.value="";
  agencySearch.oninput();

  const all=flatten(controls).find(x=>x.className==="agency-filter-button");
  assert.ok(all&&all.textContent==="전체 기관");
  all.onclick();
  assert.equal(results.children.length,3,"All institutions must be recoverable");
  const next=flatten(node(ui,"items"))
    .find(x=>x.dataset.eventId==="other");
  next.onclick();
  detail=node(ui,"detail");
  const nextResults=pick(detail,"agency-group-results");
  assert.equal(nextResults.children.length,1);
  assert.ok(textOf(nextResults).includes("다른가상기관"),
    "Switching events should reset the prior event's agency filter");
  assert.equal(pick(detail,"agency-select").value,"all");

  const mobile=browser(true,"",data);
  await flush();
  node(mobile,"mode-all").onclick();
  node(mobile,"items").children[0].onclick();
  const mobileDetail=node(mobile,"detail");
  const mobileSelect=pick(mobileDetail,"agency-select");
  const mobileResults=pick(mobileDetail,"agency-group-results");
  assert.equal(mobileSelect.children.length,4,
    "Mobile selector includes all agencies and the all-institutions option");
  mobileSelect.value="가상교육청";
  mobileSelect.onchange();
  assert.equal(mobileResults.children.length,1);
  assert.ok(textOf(mobileResults).includes("교육 지원 변경 대조"));
  mobileSelect.value="all";
  mobileSelect.onchange();
  assert.equal(mobileResults.children.length,3);
  console.log("PASS: detail institution filter, search, reset, and mobile select");
}

async function largeScopeFiltering(){
  const event=sample("many",{date:"2026-11-12",impact:true,group:true});
  const verified=event.institutional_reviews[0];
  event.institutional_reviews=[
    {...verified,id:"multi-1",institution:"가상시청"},
    {...verified,id:"multi-2",institution:"가상교육청"},
    {...verified,id:"multi-3",institution:"가상기관삼"},
    {...verified,id:"multi-4",institution:"가상기관사"},
    {...verified,id:"multi-5",institution:"가상기관오"},
  ];
  event.institution_count=5;
  event.review_count=5;
  const data={schema:"policy-domino-next-v1",
    events:[event,sample("solo",{date:"2026-11-11",impact:true})],
    ai_progress:{indexed_documents:200},generated_at:""};
  const ui=browser(false,"",data);
  await flush();
  node(ui,"mode-impact").onclick();
  assert.deepEqual(node(ui,"items").children.filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),["many"]);
  assert.equal(node(ui,"list-count").textContent,"전체 2건 · 표시 1건");
  assert.equal(node(ui,"mode-impact").getAttribute("aria-pressed"),"true");
  node(ui,"mode-all").onclick();
  assert.equal(node(ui,"list-count").textContent,"전체 2건 · 표시 2건");
  console.log("PASS: compact quick filters and evidence-based high-impact scope");
}
async function screenshotComparisonSafety(){
  const event=sample("comparison",{date:"2026-11-12"});
  const base=event.changes[0];
  const marker={
    ...base,article:"제13조",before:"③",
    after:"지방자치단체의 장은 소속 공무원의 적극행정 노력을 장려하고 보상할 수 있다.",
    category:"종전·현행 원문 확인 필요",
    brief:"종전 또는 현행 조문이 항 번호만 수집되어 정확한 변경 내용을 판단할 수 없습니다.",
    meaning:{
      label:"종전·현행 원문 확인 필요",
      description:"종전 또는 현행 조문이 항 번호만 수집되어 정확한 변경 내용을 판단할 수 없습니다.",
      before:"③",
      after:"지방자치단체의 장은 소속 공무원의 적극행정 노력을 장려하고 보상할 수 있다.",
      source_check_required:true,change_kind:"source_check",
      priority:-10,edits_count:1,editorial:false,
    },
  };
  const citation={
    ...base,article:"제10조",before:"제12조제2항에",after:"제12조제3항에",
    category:"인용 조문 변경",
    brief:"이 조문에서 인용하는 조문이 제12조제2항에서 제12조제3항으로 바뀌었습니다.",
    meaning:{
      label:"인용 조문 변경",
      description:"이 조문에서 인용하는 조문이 제12조제2항에서 제12조제3항으로 바뀌었습니다.",
      before:"제12조제2항",after:"제12조제3항",source_check_required:false,
      change_kind:"citation",priority:18,edits_count:1,editorial:false,
    },
  };
  event.changes=[citation,marker];
  event.highlights=event.changes.map(ch=>({document_id:ch.document_id,article:ch.article}));
  event.headline="2개 조문에서 변경 확인 · 인용 조문 수정 1건 · 원문 재확인 1건";
  const ui=browser(false,"",{
    schema:"policy-domino-next-v1",events:[event],
    ai_progress:{indexed_documents:1000},generated_at:"",
  });
  await flush();
  node(ui,"mode-all").onclick();
  const text=textOf(node(ui,"detail"));
  assert.ok(text.includes("인용하는 조문이 제12조제2항에서 제12조제3항으로"));
  assert.ok(text.includes("종전 인용 조문"));
  assert.ok(text.includes("현행 인용 조문"));
  const changes=flatten(node(ui,"detail")).filter(el=>
    el.className==="highlight-detail" &&
    flatten(el).some(x=>x.className==="highlight-comparison"));
  assert.ok(changes.length>=1,"Core changes show short summary and collapse the before/after excerpts");
  assert.ok(changes.every(x=>!x.open),"Before/after source excerpts must start collapsed");
  assert.ok(text.includes("정확한 변경 내용을 판단할 수 없습니다"));
  assert.ok(text.includes("재확인 대상"));
  assert.ok(!text.includes("대상·자격 기준에 관한 조문 문구"),
    "Incomplete official text must never be treated as a verified eligibility change");
  console.log("PASS: real-style citation changes and incomplete source are distinct");
}

async function realServiceLeadDiscoveryPresentation(){
  const event=sample("gov24",{date:"2026-11-10",impact:false,benefit:true});
  event.public_service_lead_count=1;
  event.public_service_leads=[{
    service_id:"S101",service_name:"가상생활지원서비스",
    agency:"가상광역시청",agency_type:"지방자치단체",
    document_id:"source-gov24",article:"제3조",law_title:event.title,
    match_tier:"official_clause_citation",
    basis_quote:"「가상지원정책」 제3조에 따른 사업",
    old_value_seen_in_service:["10만원"],
    verification:"candidate_not_confirmed",
    review_question:"해당 공공서비스의 운영·선정 기준에 개정 조문이 적용되는지 확인",
    review_targets:[{
      field:"선정기준",
      source_excerpt:"가구 소득과 지원기준 10만원을 비교",
      old_value:"10만원",new_legal_value:"12만원",
      review_question:"선정기준에 기재된 10만원을 개정 조문의 12만원과 대조",
      verification:"source_field_and_legal_change_only",
    }],
    source_url:"https://www.data.go.kr/data/15113968/openapi.do",
    service_url:"https://www.gov.kr/portal/service",
  }];
  const data={
    schema:"policy-domino-next-v1",events:[event],
    ai_progress:{indexed_documents:400},public_services_indexed:1000,
    public_service_review_leads:1,
    gov24_audit:{status:"collected_incrementally"},generated_at:"",
  };
  const ui=browser(false,"",data);
  await flush();
  node(ui,"mode-all").onclick();
  const detail=node(ui,"detail");
  const text=textOf(detail);
  assert.ok(text.includes("기관별 변경·사업 검토사항"));
  assert.ok(text.includes("가상광역시청"));
  assert.ok(text.includes("가상생활지원서비스"));
  assert.ok(text.includes("관련 서비스 1건"));
  assert.ok(!text.includes("근거 수준은 구분해 보여줍니다"));
  assert.ok(text.includes("10만원"));
  assert.ok(text.includes("선정기준 · 검토할 기준"));
  assert.ok(text.includes("개정 조문 12만원"));
  const grouped=flatten(detail).find(el=>el.className==="agency-group-results");
  assert.ok(grouped && grouped.children.length===1,
    "Public-service-only agency must be available in the institution selector");
  const options=flatten(detail).find(el=>el.className==="agency-select");
  assert.ok(options.children.some(x=>x.value==="가상광역시청"));
  const agencyButton=flatten(detail).find(x=>x.dataset.institution==="가상광역시청");
  assert.ok(agencyButton);
  agencyButton.onclick();
  assert.ok(textOf(grouped).includes("가상생활지원서비스"));
  const lead=flatten(detail).find(el=>el.className.includes("service-criterion"));
  assert.ok(lead,"The existing public service criterion is visible on expansion");
  const links=flatten(detail).filter(el=>el.tag==="a");
  assert.ok(links.some(a=>a.href==="https://www.gov.kr/portal/service"),
    "Only approved official Gov24 service links can be opened");
  assert.ok(!html.includes("institution-link-progress"),
    "Verbose source diagnostics belong to the audit, not the banner");
  console.log("PASS: actual Gov24 public-service evidence displayed as candidates");
}
async function indexedNoticesAreSearchableWithoutFakingImpact(){
  const event=sample("confirmed",{date:"2026-11-10"});
  const official={
    id:"official-queued-01",title:"2027년도 가상 지원기준 고시",
    source:"admrul",law_type:"고시",published_at:"2026-07-29",
    ministry:"가상복지부",url:"https://www.law.go.kr/행정규칙/가상지원기준",
    analysis:{status:"queued",changes:[]},
  };
  const bodyMissing={...official,id:"official-missing-02",
    title:"2027년도 가상 서비스기준 고시",
    analysis:{status:"body_unavailable",changes:[]}};
  const data={schema:"policy-domino-next-v1",events:[event],
    documents:[official,bodyMissing],
    ai_progress:{indexed_documents:3},generated_at:""};
  const ui=browser(false,"",data);
  await flush();
  node(ui,"mode-all").onclick();
  node(ui,"search").oninput({target:{value:"2027년도 가상 고시"}});
  const items=node(ui,"items");
  const text=textOf(items);
  assert.ok(text.includes("공식자료 검색 · 분석 대기 포함 2건"));
  assert.ok(text.includes("신구 분석 대기"));
  assert.ok(text.includes("본문 미확보"));
  assert.ok(!text.includes("정책 변경으로 확정하거나 기관별 업무 변경으로 표시하지 않습니다"));
  assert.equal(flatten(items).filter(x=>x.dataset.eventId==="official-queued-01").length,0);
  assert.ok(flatten(items).some(x=>x.tag==="a" &&
    decodeURI(x.href||"")==="https://www.law.go.kr/행정규칙/가상지원기준"));
  node(ui,"search").oninput({target:{value:"2027년도 존재하지않음"}});
  assert.ok(textOf(node(ui,"items")).includes(
    "현재 색인에 일치하는 공식자료가 없습니다"));
  console.log("PASS: indexed notices and analysis failures visible without fictitious change event");
}

async function realDiffDoesNotRepeatSameClauseStart(){
  const event=sample("deep-diff",{date:"2026-11-10"});
  const oldText=("같은 규정의 적용 요건과 심사 절차를 유지한다. ").repeat(25)+
    "계약이전 공개설명회를 일간신문에 공고한다.";
  const newText=("같은 규정의 적용 요건과 심사 절차를 유지한다. ").repeat(25)+
    "계약이전 공개설명회를 금융위원회 홈페이지에 공고한다.";
  const focus=[{
    before:{prefix:"…계약이전 공개설명회를 ",changed:"일간신문",
            suffix:"에 공고한다."},
    after:{prefix:"…계약이전 공개설명회를 ",
           changed:"금융위원회 홈페이지",suffix:"에 공고한다."},
    type:"교체",
  }];
  event.changes[0].before=oldText;
  event.changes[0].after=newText;
  event.changes[0].meaning={
    ...event.changes[0].meaning,
    before:oldText.slice(0,145),after:newText.slice(0,145),
    focus,
  };
  const ui=browser(false,"",{
    schema:"policy-domino-next-v1",events:[event],
    ai_progress:{indexed_documents:1000},generated_at:"",
  });
  await flush();
  node(ui,"mode-all").onclick();
  const detail=node(ui,"detail");
  const marked=flatten(detail).filter(el=>el.tag==="mark" &&
    el.className==="diff-changed");
  assert.ok(marked.length>=4,"Both summary and source comparison mark real edits");
  assert.ok(marked.some(el=>el.textContent==="일간신문"));
  assert.ok(marked.some(el=>el.textContent==="금융위원회 홈페이지"));
  assert.ok(!marked.some(el=>el.textContent==="같은 규정"),
    "Identical clause beginnings must not appear as changes");
  assert.ok(flatten(detail).some(el=>el.className==="full-clause-text"),
    "Full official source must remain expandable");
  console.log("PASS: identical long clause beginnings never conceal the actual edit");
}

async function shortProofEmphasis(){
  const ev=sample("source-proof",{impact:true,benefit:true});
  ev.changes[0].meaning.focus=[{
    before:{prefix:"",changed:"10만원",suffix:""},
    after:{prefix:"",changed:"12만원",suffix:""}
  }];
  ev.institutional_reviews[0].basis_quote=
    "제3조 법령 검토. "+("기준 설정 및 업무 범위. ").repeat(20)+
    "변경된 10만원 기준 적용.";
  const ui=browser(false,"",{schema:"policy-domino-next-v1",
    events:[ev],ai_progress:{indexed_documents:1},generated_at:""});
  await flush();
  node(ui,"mode-all").onclick();
  const card=flatten(node(ui,"detail")).find(x=>x.className==="review-card");
  const p=flatten(card).find(x=>x.className==="proof-preview");
  const marks=flatten(p).filter(x=>x.tag==="mark");
  assert.equal(marks.length,1);
  assert.equal(marks[0].textContent,"10만원");
  assert.ok(textOf(p).length<200);
  assert.ok(flatten(card).some(x=>x.className==="proof-full"));
  console.log("PASS: short quote anchored to actual changed source text");
}
async function officialNoticeCanBeFoundByKind(){
  const e=sample("notice",{date:"2026-11-10"});
  e.members=[{
    id:"source-notice",title:"연례 공공기준표",
    kind:"고시",url:"https://www.law.go.kr/행정규칙/연례공공기준표",
  }];
  const ui=browser(false,"",{
    schema:"policy-domino-next-v1",events:[e],
    quality:{rule_categories:{고시:{indexed:1,changed:1,pending:0}}},
    ai_progress:{indexed_documents:1},generated_at:"",
  });
  await flush();
  node(ui,"mode-all").onclick();
  node(ui,"search").oninput({target:{value:"고시"}});
  assert.equal(node(ui,"items").children.filter(x=>x.dataset.eventId).length,1);
  assert.ok(textOf(node(ui,"items")).includes("고시"));
  assert.ok(html.includes("공공기관 명부"));
  console.log("PASS: official notices are identifiable by source metadata");
}

async function noFabricatedImpact(){
  const only=sample("nothing",{impact:false,benefit:true});
  const ui=browser(false,"",{
    schema:"policy-domino-next-v1",events:[only],
    ai_progress:{indexed_documents:1000},generated_at:"",
  });
  await flush();
  node(ui,"mode-all").onclick();
  assert.equal(node(ui,"stat-agencies").textContent,"0");
  assert.ok(!textOf(node(ui,"detail")).includes("공식 근거가 아직 확인되지 않았습니다"));
  assert.ok(!flatten(node(ui,"detail")).some(el=>el.textContent==="기관별 변경·사업 검토사항"),
    "No empty institution-impact panel should appear without identified rows");
  node(ui,"mode-impact").onclick();
  assert.equal(node(ui,"items").children.filter(x=>x.dataset.eventId).length,0);
  console.log("PASS: no invented institutions or operational actions");
}

async function splitDistributionLoadsOnlyClickedDetail(){
  const first=sample("lazy-one",{date:"2026-11-12",impact:true});
  first.impact_level="high";
  const second=sample("lazy-two",{date:"2026-11-11",benefit:true});
  const synopsis=event=>({
    id:event.id,title:event.title,kind:event.kind,
    published_at:event.published_at,effective_date:event.effective_date,
    impact_level:event.impact_level,
    institution_count:event.institution_count,review_count:event.review_count,
    agency_names:event.institutional_reviews.map(row=>row.institution),
    source_documents:[],list_brief:"공식 개정 요약",
    detail_path:"./details/"+event.id+".json",
  });
  const data={schema:"policy-domino-next-v1",distribution:"split-v1",
    events:[synopsis(first),synopsis(second)],
    documents_path:"./sources.json",ai_progress:{indexed_documents:10}};
  const ui=browser(false,"",data,{details:{
    [first.id]:first,[second.id]:second,
  },sources:[{id:"pending-document",title:"2027년도 신규 심사기준 고시",
    source:"admrul",law_type:"고시",published_at:"2026-11-09",
    analysis:{status:"queued"},url:"https://www.law.go.kr/행정규칙/2027년도신규심사기준"}]});
  await flush();
  assert.equal(ui.fetchCalls.filter(x=>x==="./catalog.json").length,1);
  assert.equal(ui.fetchCalls.filter(x=>x==="./details/lazy-one.json").length,1);
  assert.equal(ui.fetchCalls.filter(x=>x==="./details/lazy-two.json").length,0);
  assert.ok(textOf(node(ui,"detail")).includes("가상공공기관"),
    "Selected detail must be hydrated from the separate verified file");
  node(ui,"mode-all").onclick(); // Full-index search is intentionally scoped to 전체.
  node(ui,"search").oninput({target:{value:"2027년도 신규"}});
  await flush();
  assert.equal(ui.fetchCalls.filter(x=>x==="./sources.json").length,1,
    "Unverified official source index loads only when searched");
  assert.ok(textOf(node(ui,"items")).includes("신구 분석 대기"));
  node(ui,"search").oninput({target:{value:""}});
  node(ui,"mode-all").onclick();
  const other=flatten(node(ui,"items")).find(x=>x.dataset.eventId==="lazy-two");
  other.onclick();
  await flush();
  assert.equal(ui.fetchCalls.filter(x=>x==="./details/lazy-two.json").length,1);
  assert.ok(textOf(node(ui,"detail")).includes("가상정책 lazy-two"));
  node(ui,"items").children[0].onclick();
  await flush();
  assert.equal(ui.fetchCalls.filter(x=>x==="./details/lazy-one.json").length,1,
    "Previously viewed official detail must be cached in the browser");
  console.log("PASS: split catalog, on-demand source index and one-detail-at-a-time fetching");
}

async function collapsedDetailPreviews(){
  const e=sample("preview",{date:"2026-11-12",impact:true,ai:true});
  const initial=e.changes[0];
  e.changes=[initial,...Array.from({length:5},(_,i)=>({
    ...initial,article:"제"+(i+4)+"조",brief:"추가 변경 "+(i+4)
  }))];
  e.highlights=e.changes.map(ch=>({document_id:ch.document_id,article:ch.article}));
  const first=e.institutional_reviews[0];
  e.institutional_reviews=Array.from({length:10},(_,i)=>({
    ...first,id:"review-"+i,task:"업무 "+i
  }));
  e.review_count=10;
  e.impact_level="high";
  const ui=browser(false,"",{
    schema:"policy-domino-next-v1",events:[e],
    ai_progress:{indexed_documents:10},generated_at:""
  });
  await flush();
  const detail=node(ui,"detail");
  const core=flatten(detail).find(x=>x.className==="detail-section core");
  const initialCards=core.children.find(x=>x.className==="highlights");
  assert.ok(initialCards,"Policy change highlights must exist");
  assert.equal(initialCards.children.filter(x=>x.className.startsWith("highlight")).length,1);
  const more=flatten(core).find(x=>x.className==="more-change-items");
  assert.ok(more && !more.open && textOf(more).includes("다른 변경 내용 5건 펼쳐보기"));
  const group=flatten(detail).find(x=>x.className==="agency-group");
  assert.equal(group.children.filter(x=>x.className==="review-card").length,2);
  const rest=flatten(group).find(x=>x.className==="agency-more-reviews");
  assert.ok(rest&&!rest.open && textOf(rest).includes("검토사항 8건 더 보기"));
  assert.ok(textOf(detail).includes("AI 보조분석"));
  assert.ok(!textOf(detail).includes("위임 관계 확인 중"));
  console.log("PASS: one policy preview, two agency cards, expand all, AI section reachable");
}

Promise.all([
  collapsedDetailPreviews(),
  splitDistributionLoadsOnlyClickedDetail(),
  verifiedNavigation(),mobileNavigation(),directoryModalNavigation(),
  effectiveYearAndRenamedAnnualCriteriaSearch(),noFabricatedImpact(),
  institutionFilterNavigation(),largeScopeFiltering(),screenshotComparisonSafety(),
  realServiceLeadDiscoveryPresentation(),officialNoticeCanBeFoundByKind(),
  realDiffDoesNotRepeatSameClauseStart(),shortProofEmphasis(),
  indexedNoticesAreSearchableWithoutFakingImpact()
]).catch(error=>{console.error(error);process.exitCode=1});
