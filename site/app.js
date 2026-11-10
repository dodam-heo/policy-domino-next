(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const FILTER_MODES=["all","new","amended","repealed"];
  const view = window.PolicyDominoView;
  const state = {data: null, selected: null, query: "", visible: 80,
                 mode:"all", agencyFilter:"all"};
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
      if(!["www.law.go.kr","law.go.kr","www.alioplus.go.kr","alioplus.go.kr"].includes(u.hostname))return null;
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
    const diffRow=(edit,index)=>{
      const block=create("div","diff-row");
      if(edits.length>1)append(block,create("div","diff-caption",
        "차이 "+(index+1)+" / "+edits.length));
      const columns=create("div","two");
      const before=create("div","before"),after=create("div","after");
      append(before,create("span","value-label","변경 전"));
      append(after,create("span","value-label","변경 후"));
      renderShortDelta(before,edit.before,edit.after,"before");
      renderShortDelta(after,edit.before,edit.after,"after");
      append(columns,before,after);append(block,columns);
      return block;
    };
    edits.slice(0,3).forEach((edit,index)=>append(article,diffRow(edit,index)));
    if(edits.length>3){
      const more=create("details","evidence-drawer");
      append(more,create("summary","","추가 변경 부분 "+num(edits.length-3)+"곳 보기"));
      edits.slice(3).forEach((edit,index)=>append(more,diffRow(edit,index+3)));
      append(article,more);
    }
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
    append(top,create("div","eyebrow",(doc.kind||"공식 규정")+" · "+(doc.published_at||"")),
      create("h2","",doc.title),
      create("div","sub","소관 · 발령기관: "+formatAgencyNames(doc.ministry)),
      badge(analysisLabel(analysis)[0],analysisLabel(analysis)[1]),
      external(doc.url,"공식 원문 확인"));
    append(root,top);

    const diffs=analysis.changes||[];
    const changes=heading("① 실제 변경 내용");
    if(!diffs.length){
      append(changes,create("div","muted-box",analysis.reason ||
        "공식 신구 원문 비교가 완료되지 않았습니다. 변경 내용을 임의로 작성하지 않습니다."));
    }else{
      for(const c of diffs.slice(0,6))append(changes,sourceDiffCard(c));
      if(diffs.length>6){
        const more=create("details","evidence-drawer");
        append(more,create("summary","","나머지 변경 조문 "+num(diffs.length-6)+"개 보기"));
        for(const c of diffs.slice(6))append(more,sourceDiffCard(c));
        append(changes,more);
      }
    }
    append(root,changes);

    // Agency actions require independently verified public program evidence.
    // Merely naming an official in a law is a discovery lead, not an action.
    const evidence=view.impactView(doc,state.data.relationships||[],
      state.data.cross_document_review_candidates||[],
      state.data.program_dependencies||[]);
    const impacts=heading("② 기관별 변경 검토사항");
    const agencies=Array.from(new Set([
      ...evidence.actions.keys(), ...evidence.programs.keys()
    ])).sort((a,b)=>a.localeCompare(b,"ko-KR"));
    if(!agencies.length){
      append(impacts,create("div","agency-empty",
        "공식 사업자료와 변경 조문 사이의 적용 관계가 아직 확인되지 않았습니다. 인용·기관명만으로 수정 의무를 추정하지 않습니다."));
    }else{
      if(state.agencyFilter!=="all" && !agencies.includes(state.agencyFilter))
        state.agencyFilter="all";
      const filters=create("div","review-filters");
      filters.setAttribute("role","group");
      filters.setAttribute("aria-label","기관 이름별 검토 필터");
      for(const name of ["all",...agencies]){
        const btn=create("button","review-chip"+
          (state.agencyFilter===name?" active":""),name==="all"?"전체 기관":name);
        btn.type="button";btn.dataset.agencyFilter=name;
        btn.setAttribute("aria-pressed",String(state.agencyFilter===name));
        btn.onclick=()=>{state.agencyFilter=name;renderDetail();};
        append(filters,btn);
      }
      append(impacts,filters);
      for(const agency of agencies){
        if(state.agencyFilter!=="all" && state.agencyFilter!==agency)continue;
        const group=create("div","agency-group");
        append(group,create("h4","agency-group-head",agency));
        for(const row of evidence.actions.get(agency)||[]){
          const card=create("div","agency-card");
          append(card,create("strong","",row.program),
            row.location?create("div","micro",row.location):null,
            create("p","",row.review),
            create("div","micro","공식 적용 근거 확인 · 실제 조치 완료 여부 미확인"),
            external(row.url,"사업 적용 근거"));
          append(group,card);
        }
        for(const row of evidence.programs.get(agency)||[]){
          const card=create("div","agency-card");
          append(card,create("strong","",row.program),
            create("div","micro","공식 사업자료에서 "+row.article+" 인용 확인 · 수정 의무 미확정"),
            create("p","",row.review),
            create("div","evidence-quote",row.citation),
            external(row.url,"공식 공공사업 원문"));
          const aiReview=(analysis.ai?.program_reviews||[]).find(x=>
            x.program_id===row.programId && x.article===row.article);
          if(aiReview){
            append(card,create("div","ai-review-label","AI 업무 검토 초안 · 조치 확정 아님"),
              create("p","",aiReview.reason),
              create("p","ai-review-question",aiReview.review_question));
          }
          append(group,card);
        }
        append(impacts,group);
      }
    }
    append(root,impacts);

    if(analysis.ai?.status==="generated"){
      const ai=heading("③ AI 변경 영향 분석",
        "공식 변경 원문과 연결 근거를 바탕으로 작성한 AI 검토 초안입니다. 기관의 수정 의무를 확정하지 않습니다.");
      append(ai,create("div","micro","실행 모델: "+analysis.ai.model+
        " · 분석시점: "+(analysis.ai.generated_at||"")));
      for(const item of analysis.ai.change_reviews||[]){
        const card=create("div","agency-card ai-card");
        append(card,create("strong","",item.article+" · "+item.summary),
          create("p","ai-review-question",item.review_question),
          create("div","micro","공식 원문 발췌: "+item.before_quote+
            " → "+item.after_quote));
        append(ai,card);
      }
      append(root,ai);
    }else if(state.data.ai_status==="not_configured" && diffs.length){
      append(root,create("div","state-note",
        "AI 분석 미실행 · 모델 인증키 미설정. 공식 신구 비교 결과는 별도로 제공됩니다."));
    }

    // Keep investigative traces available without presenting them as duties.
    if(evidence.citations.length || evidence.namedActors.size){
      const drawer=create("details","evidence-drawer");
      append(drawer,create("summary","",
        "추가 근거·미확정 연결 살펴보기 ("+
        num(evidence.citations.length)+"개 인용, "+
        num(evidence.namedActors.size)+"개 수행주체)"));
      if(evidence.citations.length){
        const related=heading("변경 조문을 인용하는 관련 규정",
          "실제 조문 인용이 확인된 자료이며, 기관 사업의 변경을 입증하지는 않습니다.");
        for(const edge of evidence.citations){
          const card=create("div","agency-card");
          append(card,create("strong","",edge.referencing_title),
            create("div","micro",edge.referencing_article+" → "+edge.changed_article),
            create("p","",edge.reference_quote),
            external(edge.referencing_source_url,"관련 규정 원문"));
          append(related,card);
        }
        append(drawer,related);
      }
      if(evidence.namedActors.size){
        const actors=heading("공식 조문에 명시된 수행주체",
          "원문에 이름이 등장한 사실만 확인되었습니다. 별도 사업 적용과 조치 필요 여부는 미검증입니다.");
        for(const [agency,rows] of evidence.namedActors){
          const group=create("div","agency-group");
          append(group,create("h4","agency-group-head",agency));
          for(const row of rows){
            const card=create("div","agency-card");
            append(card,create("div","micro",row.program+" · "+row.location),
              create("p","",row.review),external(row.url,"관련 조문"));
            append(group,card);
          }
          append(actors,group);
        }
        append(drawer,actors);
      }
      append(root,drawer);
    }

    if(analysis.excluded?.length){
      append(root,create("div","state-note",
        "비교 제외 조문 "+num(analysis.excluded.length)+
        "개 · 원문 누락 또는 불완전으로 변경 여부 미확정"));
    }
    if(analysis.baseline?.url)
      append(root,external(analysis.baseline.url,"종전 버전의 공식 원문"));
  }
  const policyType=view.policyType;
  const filtered=()=>view.filterDocuments(state.data?.documents||[],state);
  function updateModeControls(){
    for(const mode of FILTER_MODES){
      const control=$("mode-"+mode);
      const active=mode===state.mode;
      if(active)control.classList.add("active");
      else control.classList.remove("active");
      control.setAttribute("aria-pressed",String(active));
    }
  }
  function renderList(){
    updateModeControls();
    const list=$("items");list.replaceChildren();
    const all=filtered();
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
    state.mode="all";
    const linked=fragmentId();
    const hasLinked=linked && data.documents.some(doc=>doc.id===linked);
    state.selected=hasLinked?linked:(mobile()?null:(view.filterDocuments(data.documents)[0]?.id||null));
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
        state.selected=view.filterDocuments(state.data.documents)[0].id;renderList();renderDetail();
      }
    }else if(!fragmentId()){
      showList(false);
    }
  });
  for(const mode of FILTER_MODES){
    $("mode-"+mode).onclick=()=>{state.mode=mode;state.visible=80;renderList();};
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
