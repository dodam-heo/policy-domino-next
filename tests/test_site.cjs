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
