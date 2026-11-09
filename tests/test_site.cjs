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
  }
  appendChild(x){this.children.push(x);return x;}
  replaceChildren(...children){this.children=[...children];}
}
function setupBrowser(mobile=true,initialHash=""){
  const ids=["layout","listPanel","detailPanel","detail","items","feed-state",
      "indexed","compared","pending","links","updated","search","more","backToList"];
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
    documents:fakeDocs,relationships:[],quality:{},
    cross_document_review_candidates:[],generated_at:"",
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
verifyNavigation().catch(error=>{console.error(error);process.exitCode=1;});
