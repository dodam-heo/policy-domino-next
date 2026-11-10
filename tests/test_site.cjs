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
for(const id of ["items","detail","mode-all","mode-new",
                 "mode-amended","mode-repealed","mode-impact",
                 "stat-events","stat-agencies","stat-actions",
                 "list-count","search","backToList"]){
  assert.ok(html.includes('id="'+id+'"'),"Missing coherent event UI element "+id);
}
assert.ok(!html.includes("신구 확인"),"Comparison state is not a user browsing category");
assert.ok(!app.includes("agencyFilter"),"Institutional reviews must not be hidden by a filter");
assert.ok(style.includes(".agency-group"),"Impact grouping must be styled");

const existing=JSON.parse(fs.readFileSync("site/data.json","utf8"));
assert.equal(existing.schema,"policy-domino-next-v1");
assert.ok(Array.isArray(existing.documents));
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
  generated_at:"2026-11-10T05:00:00+00:00",
};
function browser(isMobile=false,hash="",data=payload) {
  const ids=["layout","listPanel","detailPanel","detail","items",
    "stat-events","stat-agencies","stat-actions","list-count",
    "ai-review-progress","institution-link-progress",
    "analysis-coverage",
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
  const fetch=()=>Promise.resolve({ok:true,json:()=>Promise.resolve(data)});
  vm.runInNewContext(presenter,{window:win,console},
                     {filename:"site/presentation.js"});
  vm.runInNewContext(app,{
    window:win,document:dom,history,location:here,fetch,URL,
    console,encodeURIComponent,decodeURIComponent
  },{filename:"site/app.js"});
  return {elements,body,historyCalls,here,callbacks,win};
}
function node(context,id){return context.elements.get(id)}
async function flush(){await new Promise(resolve=>setImmediate(resolve))}
async function verifiedNavigation(){
  const ui=browser(false);
  await flush();
  assert.equal(node(ui,"stat-events").textContent,"4");
  assert.equal(node(ui,"stat-agencies").textContent,"1");
  assert.equal(node(ui,"stat-actions").textContent,"1");
  assert.equal(node(ui,"list-count").textContent,"전체 4건 · 표시 4건");
  assert.ok(html.includes("정책 변경 목록"));
  assert.ok(html.includes("공포·발령일 최신순"));
  assert.ok(!html.includes("급여·지원기준"));
  assert.ok(!html.includes("filter-grid"));
  assert.ok(html.includes("법령명·정책명·소관기관 검색"));
  assert.ok(node(ui,"analysis-coverage").textContent.includes("아직 미분석 9,840건"));
  assert.ok(node(ui,"analysis-coverage").textContent.includes("재확인 대상 204건"));
  assert.ok(node(ui,"analysis-coverage").textContent.includes("재확인 유예 21건"));
  assert.ok(node(ui,"analysis-coverage").textContent.includes("수집 미완료 구간 2개"));
  assert.ok(node(ui,"ai-review-progress").textContent.includes("24 / 변경 조문 468건"));
  assert.ok(node(ui,"ai-review-progress").textContent.includes("신규 결과 9건"));
  assert.ok(node(ui,"ai-review-progress").textContent.includes("오류 15건"));
  assert.ok(node(ui,"institution-link-progress").textContent.includes("관련 공식 규정 소관기관 연결 1건"));
  assert.equal(node(ui,"items").children.length,4);
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),
                   ["amended","new","ordinary","repealed"]);
  node(ui,"mode-impact").onclick();
  assert.deepEqual(node(ui,"items").children
    .filter(x=>x.dataset.eventId).map(x=>x.dataset.eventId),[],
    "A single verified agency must not be mislabeled as high impact");
  assert.equal(node(ui,"list-count").textContent,"전체 4건 · 표시 0건");
  node(ui,"mode-new").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["new"]);
  node(ui,"mode-repealed").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["repealed"]);
  node(ui,"mode-amended").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),
    ["amended","ordinary"]);
  node(ui,"mode-all").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),
    ["amended","new","ordinary","repealed"]);
  assert.equal(node(ui,"list-count").textContent,"전체 4건 · 표시 4건");
  node(ui,"search").oninput({target:{value:"가상 지원운영사업"}});
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["amended"]);
  node(ui,"search").oninput({target:{value:""}});
  node(ui,"items").children[0].onclick();
  assert.equal(ui.here.hash,"#event=amended");
  const detail=node(ui,"detail");
  const text=textOf(detail);
  assert.ok(text.includes("가상공공기관"),"Direct affected institution is visible");
  assert.ok(text.includes("가상 지원운영사업의 적용 금액을 제3조와 대조"));
  assert.ok(text.includes("공식 변경 전·후와 출처"));
  assert.ok(text.includes("동시 개정된 법령 17건"));
  assert.ok(text.includes("AI 보조검토"));
  assert.ok(text.includes("AI 보조 요약 · 원문 인용 검증 완료"),
    "Verified AI clause summary should be on the main change card");
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
      x.children.some(y=>y.textContent==="기관별 변경 검토사항"));
  const legal=flatten(detail).findIndex(x=>x.className==="detail-section" &&
      x.children.some(y=>y.textContent==="공식 변경 전·후와 출처"));
  assert.ok(core>=0 && impact>core && legal>impact,
            "User's event -> affected agency -> evidence order must be preserved");
  const original=flatten(detail).find(x=>x.className==="evidence-panel");
  assert.ok(original&&!original.open,"Long original legal text should start collapsed");
  console.log("PASS: policy events, institution/program reviews, search and evidence order");
}
async function mobileNavigation(){
  const ui=browser(true);
  await flush();
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
  assert.ok(textOf(detail).includes("1개 기관 · 1건"));

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
  ];
  event.institution_count=2;
  event.review_count=2;
  const data={schema:"policy-domino-next-v1",
    events:[event,sample("solo",{date:"2026-11-11",impact:true})],
    ai_progress:{indexed_documents:200},generated_at:""};
  const ui=browser(false,"",data);
  await flush();
  node(ui,"mode-impact").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["many"]);
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
  const text=textOf(node(ui,"detail"));
  assert.ok(text.includes("인용하는 조문이 제12조제2항에서 제12조제3항으로"));
  assert.ok(text.includes("종전 인용 조문"));
  assert.ok(text.includes("현행 인용 조문"));
  const changes=flatten(node(ui,"detail")).filter(el=>
    el.className==="highlight-detail" && el.children.some(x=>x.className==="highlight-comparison"));
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
  const detail=node(ui,"detail");
  const text=textOf(detail);
  assert.ok(text.includes("공공기관·서비스 적용기준 검토"));
  assert.ok(text.includes("가상광역시청 · 가상생활지원서비스"));
  assert.ok(text.includes("검토할 공공서비스 1건"));
  assert.ok(text.includes("조치 의무나 반영 완료를 확정한 내용은 아닙니다"));
  assert.ok(text.includes("10만원"));
  assert.ok(text.includes("선정기준 · 확인할 업무"));
  assert.ok(text.includes("개정 조문 12만원"));
  const lead=flatten(detail).find(el=>el.className.includes("service-criterion"));
  assert.ok(lead,"The existing public service criterion is visible on expansion");
  const links=flatten(detail).filter(el=>el.tag==="a");
  assert.ok(links.some(a=>a.href==="https://www.gov.kr/portal/service"),
    "Only approved official Gov24 service links can be opened");
  assert.ok(node(ui,"institution-link-progress").textContent.includes(
    "정부24 공공서비스 1,000건"));
  console.log("PASS: actual Gov24 public-service evidence displayed as candidates");
}
async function noFabricatedImpact(){
  const only=sample("nothing",{impact:false,benefit:true});
  const ui=browser(false,"",{
    schema:"policy-domino-next-v1",events:[only],
    ai_progress:{indexed_documents:1000},generated_at:"",
  });
  await flush();
  assert.equal(node(ui,"stat-agencies").textContent,"0");
  assert.ok(textOf(node(ui,"detail")).includes("연결 근거는 아직 확인되지 않았습니다"));
  node(ui,"mode-impact").onclick();
  assert.equal(node(ui,"items").children.filter(x=>x.dataset.eventId).length,0);
  console.log("PASS: no invented institutions or operational actions");
}
Promise.all([
  verifiedNavigation(),mobileNavigation(),noFabricatedImpact(),
  institutionFilterNavigation(),largeScopeFiltering(),screenshotComparisonSafety(),
  realServiceLeadDiscoveryPresentation()
]).catch(error=>{console.error(error);process.exitCode=1});
