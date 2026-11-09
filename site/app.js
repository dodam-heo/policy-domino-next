(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const FILTER_MODES=["all","new","amended","repealed","pending"];
  const SORT_MODES=["verified","latest"];
  const state = {data: null, selected: null, query: "", visible: 80,
                 mode:"all", sort:"verified", agencyFilter:"all",
                 linkCounts:new Map(), verifiedActionCounts:new Map(),
                 crossCounts:new Map()};
  // Mobile navigation follows the original policy-domino list→detail UX.
  // The detail is a distinct view, never an extra page section below the list.
  const mobile = () => window.matchMedia("(max-width:850px)").matches;
  function fragmentId(){
    const match = location.hash.match(/^#change=(.+)$/);
    try{return match ? decodeURIComponent(match[1]) : null;}catch{return null;}
  }
  function scrollTop(){
    try{window.scrollTo({top:0,behavior:"instant"});}catch{window.scrollTo(0,0);}
  }
  function showList(updateUrl=true){
    $("layout").classList.remove("detail-open");
    document.body.classList.remove("detail-active");
    if(updateUrl){
      try{history.replaceState(null,"",location.pathname+location.search);}catch(e){}
    }
    if(mobile())scrollTop();
  }
  function selectDoc(id,updateUrl=true){
    if(!state.data || !state.data.documents.some(d=>d.id===id))return;
    state.selected=id;
    state.agencyFilter="all";
    renderList();
    renderDetail();
    if(mobile()){
      $("layout").classList.add("detail-open");
      document.body.classList.add("detail-active");
      if(updateUrl){
        try{history.pushState({policyId:id},"","#change="+encodeURIComponent(id));}catch(e){}
      }
      scrollTop();
    }
  }
  const create = (tag, className, content) => {
    const el = document.createElement(tag);
    if(className) el.className = className;
    if(content !== undefined) el.textContent = String(content);
    return el;
  };
  const append = (parent, ...items) => items.forEach(item => {if(item)parent.appendChild(item)});
  const normalize = str => String(str || "").toLocaleLowerCase("ko-KR");
  const badge = (content, kind) => create("span", "pill " + (kind || ""), content);
  const num = n => Number(n || 0).toLocaleString("ko-KR");
  const okHref = link => {
    try{
      const u = new URL(link);
      if(u.protocol !== "https:")return null;
      if(u.hostname !== "www.law.go.kr" && u.hostname !== "law.go.kr")return null;
      return u.href;
    }catch{return null;}
  };
  function external(url, title){
    const safe = okHref(url);
    if(!safe)return create("span","micro","공식 링크 미확인");
    const a = create("a","source",title || "공식 원문 확인");
    a.href = safe;a.target="_blank";a.rel="noopener noreferrer";
    return a;
  }
  function formatAgencyNames(name){
    return String(name||"소관기관 미확인")
      .split(/[,，、;；]+/).map(s=>s.trim()).filter(Boolean).join(" · ");
  }
  function analysisLabel(a){
    const x = a?.status || "queued";
    return ({
      compared: ["실제 신구 비교 확인","verified"],
      partial_compared: ["일부 조문 비교 · 나머지 미확인","pending"],
      enactment: ["신규 제정 본문 확인","verified"],
      repeal: ["공식 폐지 확인","verified"],
      no_text_change: ["본문 변경 미검출",""],
      queued: ["본문 비교 대기","pending"],
      baseline_unavailable: ["종전 본문 미확보","pending"],
      history_unavailable: ["종전 이력 확인 실패","pending"],
      partial_unresolved: ["일부 조문 비교 불가","pending"],
      body_unavailable: ["공식 본문 미확보","pending"],
      source_error: ["원천 접근·분석 오류","pending"],
    })[x] || ["검증 대기","pending"];
  }
  const heading = (title, help) => {
    const s=create("section");
    append(s,create("h3","",title));
    if(help)append(s,create("p","help",help));
    return s;
  };
  function compactText(value,limit=125){
    const s=String(value||"");
    if(s.length<=limit)return s;
    const left=Math.ceil(limit*0.65);
    return s.slice(0,left)+" … [중간 생략] … "+s.slice(-Math.floor(limit*0.25));
  }
  function changedParts(before,after){
    const a=String(before||""),b=String(after||"");
    let prefix=0;
    while(prefix<Math.min(a.length,b.length) && a[prefix]===b[prefix])prefix++;
    let suffix=0;
    while(suffix<Math.min(a.length-prefix,b.length-prefix) &&
          a[a.length-1-suffix]===b[b.length-1-suffix])suffix++;
    // A digit within a number must highlight the WHOLE source number:
    // 192 → 197 (not only 2 → 7) and 20만원 → 30만원 (not 2 → 3).
    if(/[0-9]/.test(a[prefix]||"") || /[0-9]/.test(b[prefix]||"") ||
       /[0-9]/.test(a[prefix-1]||"")){
      while(prefix>0 && /[0-9,.]/.test(a[prefix-1]||"") &&
            a[prefix-1]===b[prefix-1])prefix--;
      while(suffix>0 && /[0-9,.]/.test(a[a.length-suffix]||"") &&
            a[a.length-suffix]===b[b.length-suffix])suffix--;
    }
    return {a,b,prefix,suffix};
  }
  function renderShortDelta(element,before,after,side){
    // Bold/highlight ONLY the actual differing span. Context is kept short.
    const {a,b,prefix,suffix}=changedParts(before,after);
    const src=side==="before"?a:b;
    const end=src.length-suffix;
    const beforeContext=src.slice(Math.max(0,prefix-30),prefix);
    const changed=src.slice(prefix,end);
    const afterContext=src.slice(end,Math.min(src.length,end+30));
    if(prefix>30)append(element,create("span","","…"));
    append(element,create("span","",beforeContext));
    const marker=create("mark","diff-focus",compactText(changed,125) ||
      (side==="before"?"[신설 전 해당 문구 없음]":"[해당 문구 삭제]"));
    append(element,marker,create("span","",afterContext));
    if(src.length>end+30)append(element,create("span","","…"));
  }
  function sourceDiffCard(change){
    const article=create("div","change");
    append(article,create("div","change-title",
      (change.article||"변경 조문")+" · "+(change.category||"문구 변경")));
    const edits=(Array.isArray(change.actual_edits) && change.actual_edits.length?
      change.actual_edits.map(x=>({
        before:String(x.old_excerpt||""),after:String(x.new_excerpt||"")})):
      [{before:String(change.before||""),after:String(change.after||"")}])
      .filter(x=>x.before!==x.after);
    for(const [index,edit] of edits.slice(0,3).entries()){
      const block=create("div","diff-row");
      if(edits.length>1)append(block,create("div","diff-caption","차이 "+(index+1)+
        " / "+edits.length));
      const columns=create("div","two");
      const before=create("div","before"),after=create("div","after");
      append(before,create("span","value-label","변경 전"));
      append(after,create("span","value-label","변경 후"));
      renderShortDelta(before,edit.before,edit.after,"before");
      renderShortDelta(after,edit.before,edit.after,"after");
      append(columns,before,after);append(block,columns);append(article,block);
    }
    if(edits.length>3)append(article,create("p","help",
      "추가 차이 "+(edits.length-3)+"곳은 아래 원문에서 확인할 수 있습니다."));
    const drawer=create("details","original-drawer");
    const summary=create("summary","","종전·현행 조문 전체 펼쳐 보기");
    const columns=create("div","two");
    const before=create("div","before"),after=create("div","after");
    append(before,create("span","value-label","변경 전 원문"),
      create("div","",change.before||"원문 없음"));
    append(after,create("span","value-label","변경 후 원문"),
      create("div","",change.after||"원문 없음"));
    append(columns,before,after);append(drawer,summary,columns);
    append(article,drawer,external(change.source_url,"변경 조문 공식 출처"));
    return article;
  }
  function renderDetail(){
    const doc=state.data.documents.find(d=>d.id===state.selected);
    const root=$("detail");root.replaceChildren();
    if(!doc){append(root,create("div","empty","변경 항목을 선택해 주세요."));return;}
    const analysis=doc.analysis || {};
    const top=create("header","detail-head");
    append(top,create("div","eyebrow",doc.kind+" · "+doc.published_at),
      create("h2","",doc.title),
      create("div","sub","공식 소관 · 발령기관: "+formatAgencyNames(doc.ministry)),
      badge(analysisLabel(analysis)[0],analysisLabel(analysis)[1]),
      external(doc.url,"공식 법령 페이지"));
    append(root,top);
    const diffs=analysis.changes||[];
    const edges=state.data.relationships.filter(e=>e.source_event_id===doc.id);
    const cross=(state.data.cross_document_review_candidates||[])
      .filter(x=>x.source_event_id===doc.id);
    const direct=analysis.direct_actor_reviews||[];
    const confirmed=edges.filter(e=>e.operational_program_verified &&
      e.required_action_verified);
    const unassigned=analysis.review_candidates||[];
    const overview=create("div","overview");
    append(overview,create("div","overview-label","이번 개정, 한눈에 보기"));
    const numeric=diffs.find(c=>c.old_values?.length===1 &&
      c.new_values?.length===1 && c.old_values[0]!==c.new_values[0]);
    append(overview,create("div","overview-title",
      numeric?numeric.old_values[0]+" → "+numeric.new_values[0]:
      diffs.length?"실제 변경 조문 "+num(diffs.length)+"개 확인":
      analysisLabel(analysis)[0]));
    const overviewTags=create("div","overview-tags");
    append(overviewTags,create("span","", "검토 대상 조문 "+num(diffs.length)+"개"),
      create("span","", "직접 인용 규정 "+num(edges.length)+"건"),
      create("span","", "업무 검토 후보 "+num(direct.length+cross.length)+"건"));
    append(overview,overviewTags);
    append(root,overview);

    // ① Actual changed clauses always precede agency review.
    const changes=heading("① 정책에서 실제 바뀐 내용",
      "바뀐 문장·수치만 먼저 보여줍니다. 조문 전체는 필요한 경우 펼쳐서 확인할 수 있습니다.");
    if(!diffs.length){
      append(changes,create("div","muted-box",analysis.reason ||
        "종전 또는 현행 본문을 검증하지 못했습니다. 변경 내용을 임의로 작성하지 않습니다."));
    }else{
      for(const c of diffs)append(changes,sourceDiffCard(c));
    }
    append(root,changes);

    // ② Agency-name filters, derived only from specific sourced actors/programs.
    const impacts=heading("② 기관별 변경 검토사항",
      "기관 이름을 선택해 관련 검토사항을 확인합니다. 소관기관과 실제 집행기관은 구별합니다.");
    const verifiedRows=[];
    for(const edge of confirmed){
      if(edge.verified_agency && edge.required_review && edge.official_operational_url)
        verifiedRows.push({
          agency:edge.verified_agency,kind:"공식 사업자료 적용관계 확인",
          detail:edge.verified_program||"공식 사업자료",
          review:edge.required_review,url:edge.official_operational_url,
          evidenceLevel:"official_program_dependency"
        });
    }
    for(const work of cross){
      if(work.actor && work.source_url)
        verifiedRows.push({
          agency:work.actor,kind:"관련 규정에 명시된 수행주체",
          detail:(work.work_regulation||"공식 규정")+" · "+(work.target_location||""),
          review:work.review||"변경 조항 적용 문구 확인",url:work.source_url,
          evidenceLevel:"named_actor_in_citing_rule"
        });
    }
    for(const actor of direct){
      if(actor.actor && actor.source_url)
        verifiedRows.push({
          agency:actor.actor,kind:"변경 조문에 명시된 수행주체",
          detail:(actor.article||"변경 조문")+" · 원문 직접 기재",
          review:actor.review||"변경된 업무 기준 대조",url:actor.source_url,
          evidenceLevel:"named_actor_in_changed_clause"
        });
    }
    // Publishing ministry is not itself proof of implementation. Never
    // enroll it as a "review agency" solely because it issued the source.
    const groups=new Map();
    for(const item of verifiedRows){
      const name=String(item.agency).trim();
      if(!name)continue;
      if(!groups.has(name))groups.set(name,[]);
      const rows=groups.get(name);
      if(!rows.some(row=>row.kind===item.kind&&row.detail===item.detail&&
                          row.review===item.review))
        rows.push(item);
    }
    if(!groups.has(state.agencyFilter))state.agencyFilter="all";
    const tabs=create("div","review-filters");
    tabs.setAttribute("role","group");
    tabs.setAttribute("aria-label","기관 이름별 검토 필터");
    const filters=[["all","전체 기관",verifiedRows.length],
                   ...[...groups].map(([name,rows])=>[name,name,rows.length])];
    for(const [key,name,count] of filters){
      const active=state.agencyFilter===key;
      const b=create("button","review-chip"+(active?" active":""),
        name+" "+num(count));
      b.type="button";b.dataset.agencyFilter=key;
      b.setAttribute("aria-pressed",String(active));
      b.onclick=()=>{state.agencyFilter=key;renderDetail();};
      append(tabs,b);
    }
    append(impacts,tabs);
    if(!groups.size){
      append(impacts,create("div","agency-empty",
        "해당 변경을 실제 업무에 적용하는 공공기관·수행주체가 공식 원문에서 아직 확인되지 않았습니다. 발령기관만으로 집행기관을 지정하지 않습니다."));
    }else{
      const selected=state.agencyFilter==="all"?groups:
        new Map([[state.agencyFilter,groups.get(state.agencyFilter)]]);
      for(const [name,records] of selected){
        const group=create("div","agency-group");
        append(group,create("h4","agency-group-head",name));
        for(const record of records){
          const card=create("div","agency-card");
          append(card,create("div","review-type",record.kind),
            create("div","micro",record.detail),
            create("p","",record.review),
            create("div","micro",record.evidenceLevel==="official_program_dependency"?
              "공식 사업자료 적용 관계 확인 · 실제 조치 완료는 미확인":
              "공식 규정에 이름이 기재됨 · 별도 공공사업 적용·조치 의무는 미확인"),
            external(record.url,"검토 근거 원문"));
          append(group,card);
        }
        append(impacts,group);
      }
    }
    append(root,impacts);

    const related=heading("③ 변경 조문을 직접 인용하는 관련 규정",
      "인용된 조문이 실제 변경 조문과 정확히 일치할 때만 표시합니다. 사업 영향의 확정 근거는 아닙니다.");
    if(!edges.length)append(related,create("div","muted-box",
      "검증된 직접 인용 관계가 없습니다. 실제로 관련 기관이 없다는 뜻은 아닙니다."));
    for(const edge of edges){
      const card=create("div","agency-card");
      append(card,create("strong","",edge.referencing_title),
        create("div","micro",edge.referencing_article+" → "+edge.changed_article),
        create("p","",edge.reference_quote),
        create("div","micro","공포 소관: "+(edge.publishing_agency||"확인 필요")+
          " · 실제 사업 적용 미검증"),
        external(edge.referencing_source_url,"관련 규정 원문"));
      append(related,card);
    }
    append(root,related);

    const topics=heading("④ 원문 변경에 따른 추가 검토 후보",
      "기관을 배정하지 않은 변경 항목입니다. 실제 기관별 조치 확정과 구분합니다.");
    if(!(analysis.review_candidates||[]).length){
      append(topics,create("p","help","확정된 신구 조문이 없어 후보를 만들지 않았습니다."));
    }
    for(const c of analysis.review_candidates||[]){
      const card=create("div","agency-card");
      append(card,create("strong","",c.article+" · "+c.category),
        create("p","",c.review),
        create("div","micro","근거 수준: 개정 조문에만 기반 · 기관 미배정"));
      append(topics,card);
    }
    append(root,topics);

    if(analysis.excluded?.length){
      const note=create("div","state-note");
      note.textContent="비교 제외 조문 "+analysis.excluded.length+
        "개: 불완전한 원문을 변경으로 추정하지 않았습니다.";
      append(root,note);
    }
    const prior=analysis.baseline;
    if(prior)append(root,external(prior.url,"종전 버전의 공식 원문 확인"));
  }
  function policyType(doc){
    const revision=String(doc.revision||"");
    if(doc.analysis?.status==="repeal" || /폐지|실효/.test(revision))return "repealed";
    if(doc.analysis?.status==="enactment" || /제정|신설/.test(revision) && !/개정/.test(revision))return "new";
    if(/개정|정정/.test(revision))return "amended";
    return "unknown";
  }
  function verifiedScore(doc){
    const a=doc.analysis||{};
    if(a.status==="compared" && a.changes?.length)return 4;
    if(a.status==="partial_compared" && a.changes?.length)return 3;
    if(["enactment","repeal","no_text_change"].includes(a.status))return 2;
    return 0;
  }
  function analysisPending(doc){
    return verifiedScore(doc)===0;
  }
  function filtered(){
    const docs=state.data?.documents||[];
    const rows=docs.filter(doc=>{
      const matches=normalize(doc.title+" "+doc.ministry).includes(state.query);
      if(!matches)return false;
      if(state.mode==="all")return true;
      if(state.mode==="pending")return analysisPending(doc);
      return policyType(doc)===state.mode;
    });
    rows.sort((a,b)=>{
      if(state.sort==="verified"){
        const diff=verifiedScore(b)-verifiedScore(a);
        if(diff)return diff;
      }
      return String(b.published_at||"").localeCompare(String(a.published_at||"")) ||
        String(b.serial||"").localeCompare(String(a.serial||""));
    });
    return rows;
  }
  function updateFilterControls(){
    for(const mode of FILTER_MODES){
      const el=$("mode-"+mode);const active=mode===state.mode;
      if(active)el.classList.add("active");
      else el.classList.remove("active");
      el.setAttribute("aria-pressed",String(active));
    }
    for(const sort of SORT_MODES){
      const el=$("sort-"+sort);const active=sort===state.sort;
      if(active)el.classList.add("active");
      else el.classList.remove("active");
      el.setAttribute("aria-pressed",String(active));
    }
    $("filter-explain").textContent=state.sort==="verified"?
      "변경 확인 우선: 신구 원문이 확인된 자료를 앞에 표시하고, 대기·실패 자료도 남겨둡니다.":
      "최신순: 공식 공포·발령일에 따라 정렬하며, 미분석 항목도 함께 표시합니다.";
  }
  function renderList(){
    const list=$("items");list.replaceChildren();
    const all=filtered();
    updateFilterControls();
    $("feed-state").textContent=num(state.data?.documents.length||0)+
       "개 공식 변경 사건 중 "+num(all.length)+"개 표시";
    if(!all.length)append(list,create("div","empty",
      "이 조건에 해당하는 공식 변경 항목이 없습니다. 전체 공식자료에서 다른 항목을 확인할 수 있습니다."));
    for(const doc of all.slice(0,state.visible)){
      const row=create("button","item"+(doc.id===state.selected?" selected":""));
      row.type="button";row.dataset.id=doc.id;
      const topline=create("div","list-topline");
      const type=policyType(doc);
      const tag=type==="new"?"신규":type==="amended"?"개정":type==="repealed"?"폐지":"변경";
      append(topline,create("span","item-type "+type,tag),
        create("span","micro","공포·확정 "+(doc.published_at||"날짜 미확인")));
      append(row,topline,create("h3","",doc.title),
        create("div","micro",(doc.ministry||"소관기관 미확인")+" · "+(doc.kind||doc.source||"공식 규정")));
      const tags=create("div","pills");
      append(tags,badge(analysisLabel(doc.analysis)[0],analysisLabel(doc.analysis)[1]));
      const changes=doc.analysis?.changes?.length||0;
      if(changes)append(tags,badge("변경 조문 "+changes+"개"));
      const cited=state.linkCounts.get(doc.id)||0;
      if(cited)append(tags,badge("관련 규정 인용 "+cited+"건"));
      const actors=(doc.analysis?.direct_actor_reviews||[]).length+
        (state.crossCounts.get(doc.id)||0);
      if(actors)append(tags,badge("업무 검토 후보 "+actors+"건"));
      append(row,tags);
      row.onclick=()=>selectDoc(doc.id);
      append(list,row);
    }
    $("more").hidden=all.length<=state.visible;
  }
  function show(data){
    if(data.schema!=="policy-domino-next-v1")throw Error("잘못된 데이터 스키마");
    data.documents=data.documents||[];data.relationships=data.relationships||[];
    data.cross_document_review_candidates=data.cross_document_review_candidates||[];
    state.data=data;
    state.linkCounts=new Map();
    state.verifiedActionCounts=new Map();
    state.crossCounts=new Map();
    for(const rel of data.relationships){
      const id=rel.source_event_id;
      state.linkCounts.set(id,(state.linkCounts.get(id)||0)+1);
      if(rel.operational_program_verified && rel.required_action_verified)
        state.verifiedActionCounts.set(id,(state.verifiedActionCounts.get(id)||0)+1);
    }
    for(const item of data.cross_document_review_candidates){
      const id=item.source_event_id;
      state.crossCounts.set(id,(state.crossCounts.get(id)||0)+1);
    }
    state.mode="all";
    const linked=fragmentId();
    const hasLinked=linked && data.documents.some(doc=>doc.id===linked);
    state.selected=hasLinked?linked:(mobile()?null:(data.documents[0]?.id||null));
    const q=data.quality||{};
    $("indexed").textContent=num(data.documents.length);
    $("compared").textContent=num(["law","admrul","ordin"].reduce(
      (sum,k)=>sum+(q[k]?.verified_changes||0),0));
    $("pending").textContent=num(["law","admrul","ordin"].reduce(
      (sum,k)=>sum+(q[k]?.waiting||0),0));
    $("links").textContent=num(data.relationships.length);
    $("updated").textContent=data.generated_at?"마지막 분석 "+data.generated_at:
      "공식 원천 갱신 대기";
    renderList();renderDetail();
    if(hasLinked && mobile())selectDoc(linked,false);
    else if(mobile())showList(false);
  }
  $("backToList").onclick=()=>showList();
  window.addEventListener("popstate",()=>{
    const id=fragmentId();
    if(id && state.data?.documents.some(doc=>doc.id===id))selectDoc(id,false);
    else showList(false);
  });
  window.addEventListener("resize",()=>{
    if(!mobile()){
      $("layout").classList.remove("detail-open");
      document.body.classList.remove("detail-active");
      if(!state.selected && state.data?.documents.length){
        state.selected=state.data.documents[0].id;renderList();renderDetail();
      }
    }else if(!fragmentId()){
      showList(false);
    }
  });
  for(const mode of FILTER_MODES){
    $("mode-"+mode).onclick=()=>{state.mode=mode;state.visible=80;renderList();};
  }
  for(const sort of SORT_MODES){
    $("sort-"+sort).onclick=()=>{state.sort=sort;state.visible=80;renderList();};
  }
  $("search").oninput=ev=>{state.query=normalize(ev.target.value);state.visible=80;renderList();};
  $("more").onclick=()=>{state.visible+=80;renderList();};
  fetch("./data.json",{cache:"no-store"}).then(res=>{
    if(!res.ok)throw Error("정책 데이터 응답 오류");
    return res.json();
  }).then(show).catch(err=>{
    $("items").replaceChildren(create("div","empty","원천 데이터를 불러오지 못했습니다."));
    $("detail").replaceChildren(create("div","muted-box",String(err)));
    $("feed-state").textContent="수집 데이터 연결 오류";
  });
})();
