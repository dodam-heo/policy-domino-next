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
for(const id of ["items","detail","mode-impact","mode-benefit",
                 "mode-new","mode-amended","mode-repealed","stat-events",
                 "stat-agencies","stat-actions","search","backToList"]){
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
    article:"제3조",category:benefit?"금액·비율":"조직·정원",
    brief:"10만원 → 12만원",before:"10만원",after:"12만원",
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
    changes,institutional_reviews:a?[a]:[],
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
  ai_progress:{indexed_documents:10166,verified_document_changes:101},
  generated_at:"2026-11-10T05:00:00+00:00",
};
function browser(isMobile=false,hash="",data=payload) {
  const ids=["layout","listPanel","detailPanel","detail","items",
    "stat-events","stat-agencies","stat-actions","list-count",
    "search","source-status","updated","more","backToList",
    "mode-all","mode-impact","mode-benefit","mode-new","mode-amended","mode-repealed"];
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
  assert.ok(node(ui,"source-status").textContent.includes("10,166"));
  assert.equal(node(ui,"items").children.length,4);
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),
                   ["amended","new","ordinary","repealed"]);
  node(ui,"mode-impact").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["amended"]);
  node(ui,"mode-benefit").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["amended"]);
  node(ui,"mode-new").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["new"]);
  node(ui,"mode-repealed").onclick();
  assert.deepEqual(node(ui,"items").children.map(x=>x.dataset.eventId),["repealed"]);
  node(ui,"mode-all").onclick();
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
  verifiedNavigation(),mobileNavigation(),noFabricatedImpact()
]).catch(error=>{console.error(error);process.exitCode=1});
