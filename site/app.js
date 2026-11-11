(() => {
  "use strict";
  const $ = name => document.getElementById(name);
  const view = window.PolicyDominoView;
  const state = {
    data: null, events: [], selected: null, mode: "all",
    query: "", visible: 60, institutionFilter: "all"
  };
  const mobile = () => window.matchMedia("(max-width:850px)").matches;
  const num = n => Number(n || 0).toLocaleString("ko-KR");
  const compact = (value, limit = 130) => {
    const str = String(value || "").replace(/\s+/g, " ").trim();
    return str.length > limit ? str.slice(0, limit) + "…" : str;
  };
  const create = (tag, className = "", value) => {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined) el.textContent = String(value);
    return el;
  };
  const append = (parent,...children) => children.forEach(c => {
    if (c) parent.appendChild(c);
  });
  function link(url, label) {
    try {
      const valid = new URL(url);
      if (valid.protocol !== "https:" ||
          !["law.go.kr","www.law.go.kr","www.alioplus.go.kr",
            "alioplus.go.kr","gov.kr","www.gov.kr",
            "data.go.kr","www.data.go.kr"].includes(valid.hostname)) return null;
      const a = create("a","official-link",label);
      a.href = valid.href;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      return a;
    } catch { return null; }
  }
  const pill = (text, modifier = "") =>
    create("span","pill "+modifier,text);
  function heading(text, description = "") {
    const s = create("section","detail-section");
    append(s,create("h3","section-heading",text));
    if (description) append(s,create("p","section-help",description));
    return s;
  }
  function eventHash() {
    const match = location.hash.match(/^#event=(.+)$/);
    if (!match) return null;
    try { return decodeURIComponent(match[1]); }
    catch { return null; }
  }
  function scrollTop() {
    try { window.scrollTo({top:0,behavior:"instant"}); }
    catch { window.scrollTo(0,0); }
  }
  function back(updateUrl=true) {
    $("layout").classList.remove("detail-open");
    document.body.classList.remove("detail-active");
    if (updateUrl) {
      try { history.replaceState(null,"",location.pathname+location.search); }
      catch {}
    }
    if (mobile()) scrollTop();
  }
  function select(id, updateUrl=true) {
    if (!state.events.some(e => e.id === id)) return;
    if (state.selected !== id) state.institutionFilter = "all";
    state.selected = id;
    renderList();
    renderDetail();
    if (updateUrl) {
      try { history.pushState({policyEvent:id},"","#event="+encodeURIComponent(id)); }
      catch {}
    }
    if (mobile()) {
      $("layout").classList.add("detail-open");
      document.body.classList.add("detail-active");
      scrollTop();
    }
  }
  function renderFilters() {
    for (const mode of view.MODES) {
      const button=$("mode-"+mode);
      const active=state.mode===mode;
      if(active)button.classList.add("active");
      else button.classList.remove("active");
      button.setAttribute("aria-pressed",String(active));
    }
  }
  function filtered() {
    return view.filterEvents(state.events,state);
  }
  function renderIndexedOfficialSources(root, events) {
    // The official index and a verified policy change are different stages.
    // A document without completed comparison must be discoverable, but must
    // NEVER be represented as an already verified amendment or agency impact.
    if(state.mode!=="all")return;
    const terms=state.query.trim().toLocaleLowerCase("ko-KR")
      .split(/\s+/).filter(Boolean);
    if(!terms.length || terms.join("").length<2)return;
    const verified=new Set(state.events.flatMap(e=>e.source_documents||[]));
    const docs=(state.data?.documents||[]).filter(doc=>{
      if(verified.has(doc.id))return false;
      const text=[doc.title,doc.law_type,doc.ministry]
        .join(" ").toLocaleLowerCase("ko-KR");
      return terms.every(term=>text.includes(term));
    });
    const section=create("details","indexed-search-section");
    section.open=!events.length;
    append(section,create("summary","",
      "공식자료 검색 · 분석 대기 포함 "+num(docs.length)+"건"));
    append(section,create("p","index-warning",
      "여기는 공식 원천에서 색인한 문서 목록입니다. 신구 비교가 완료되지 않은 자료는 정책 변경으로 확정하거나 기관별 업무 변경으로 표시하지 않습니다."));
    if(!docs.length){
      append(section,create("p","empty",
        "현재 색인에 일치하는 공식자료가 없습니다. 미수집 연혁·고시 원문은 별도 수집이 필요합니다."));
    }
    for(const doc of docs.slice(0,25)){
      const item=create("div","indexed-source-item");
      const status=doc.analysis?.status||"queued";
      const label={
        queued:"신구 분석 대기",
        body_unavailable:"본문 미확보",
        history_unavailable:"종전 이력 미확보",
        baseline_unavailable:"종전 기준 미확보",
        partial_unresolved:"원문 일부 미확인",
        source_error:"공식 조회 오류",
        compared:"변경 사건 없음",
        no_text_change:"텍스트 변경 없음",
        enactment:"신규 제정",
        repeal:"폐지",
      }[status]||"원문 비교 확인 중";
      append(item,create("strong","",doc.title),
        create("p","",[
          doc.law_type||doc.source,doc.published_at,
          doc.ministry,label].filter(Boolean).join(" · ")),
        link(doc.url,"공식 법령·고시 원문"));
      append(section,item);
    }
    if(docs.length>25)
      append(section,create("p","section-help",
        "처음 25건만 표시합니다. 검색어를 더 구체화하세요."));
    append(root,section);
  }

  function renderList() {
    renderFilters();
    const events=filtered();
    const root=$("items");root.replaceChildren();
    $("list-count").textContent=
      "전체 "+num(state.events.length)+"건 · 표시 "+
      num(Math.min(events.length,state.visible))+"건";
    if (!events.length) {
      append(root,create("p","empty",
        "조건에 맞는 검증된 정책 변경 사건이 없습니다. 다른 조건으로 확인하세요."));
    }
    for (const event of events.slice(0,state.visible)) {
      const item=create("button","item"+(event.id===state.selected?" selected":""));
      item.type="button";
      item.dataset.eventId=event.id;
      const header=create("div","item-top");
      const categories=[...new Set((event.members||[])
        .map(x=>x.kind).filter(Boolean))];
      append(header,pill(view.category(event),"type "+event.kind),
        categories.length===1&&categories[0]!=="법령"?
          pill(categories[0]):null,
        create("span","item-date",event.published_at||"날짜 미확인"));
      const tags=create("div","item-tags");
      if (event.source_count>1) append(tags,pill("동시 개정 "+num(event.source_count)+"건"));
      if (event.institution_count) append(tags,pill("검토 기관 "+num(event.institution_count)+"곳","impact"));
      if (event.review_count) append(tags,pill("업무 "+num(event.review_count)+"건"));
      if (event.public_service_lead_count)
        append(tags,pill("공공서비스 기준 "+num(event.public_service_lead_count)+"건"));
      if (event.ai_count) append(tags,pill("AI 보조검토","ai"));
      const highlighted=(event.highlights||[])[0];
      const important=highlighted && (event.changes||[]).find(ch=>
        ch.document_id===highlighted.document_id && ch.article===highlighted.article);
      const brief=important?.brief||event.changes?.[0]?.brief;
      append(item,header,create("h3","",event.title),
        create("p","item-brief",brief||event.headline),tags);
      item.onclick=()=>select(event.id);
      append(root,item);
    }
    renderIndexedOfficialSources(root,events);
    $("more").hidden=events.length<=state.visible;
  }
  function sourceDiffPreview(change, beforeLabel="변경 전", afterLabel="변경 후") {
    const meaning=change.meaning||{};
    const focus=Array.isArray(meaning.focus)?meaning.focus:[];
    const wrapper=create("div","source-diff-preview");
    if(!focus.length) {
      const pair=create("div","highlight-comparison");
      const a=create("div","highlight-old"),b=create("div","highlight-new");
      append(a,create("small","",beforeLabel),
        create("p","",meaning.before||"확인된 변경 부분 없음"));
      append(b,create("small","",afterLabel),
        create("p","",meaning.after||"확인된 변경 부분 없음"));
      append(pair,a,b);
      append(wrapper,pair);
      return wrapper;
    }
    for(const [index,part] of focus.entries()){
      const pair=create("div","highlight-comparison");
      if(focus.length>1)
        append(wrapper,create("p","diff-window-label",
          "실제 변경 위치 "+num(index+1)+" / "+num(focus.length)));
      for(const [side,label,className] of [
        ["before",beforeLabel,"highlight-old"],
        ["after",afterLabel,"highlight-new"]
      ]) {
        const block=create("div",className);
        append(block,create("small","",label));
        const p=create("p","diff-preview-text");
        const snippet=part[side]||{};
        if(snippet.prefix)append(p,create("span","diff-context",snippet.prefix));
        if(snippet.changed)append(p,create("mark","diff-changed",snippet.changed));
        else append(p,create("span","diff-absent",
          side==="before"?"[추가된 부분]":"[삭제된 부분]"));
        if(snippet.suffix)append(p,create("span","diff-context",snippet.suffix));
        append(block,p);
        append(pair,block);
      }
      append(wrapper,pair);
    }
    return wrapper;
  }

  function sourcePair(change) {
    const wrap=create("div","clause");
    const label=change.meaning?.label||"조문 내용 변경";
    append(wrap,create("div","clause-name",
      change.document_title+" · "+change.article+" · "+label));
    if(change.brief)append(wrap,create("p","clause-description",change.brief));
    append(wrap,sourceDiffPreview(change,"변경 전","변경 후"));
    const full=create("details","original-clause");
    append(full,create("summary","","변경 전·후 조문 전체 보기"));
    const complete=create("div","pair");
    const oldBox=create("div","before");
    const newBox=create("div","after");
    append(oldBox,create("small","value-label","종전 조문 전문"),
      create("p","full-clause-text",change.before||"미확인"));
    append(newBox,create("small","value-label","현행 조문 전문"),
      create("p","full-clause-text",change.after||"미확인"));
    append(complete,oldBox,newBox);
    append(full,complete);
    append(wrap,full,link(change.source_url,"공식 법령 원문"));
    return wrap;
  }
  function renderCore(event) {
    const section=heading("이번 개정에서 달라진 내용");
    section.className="detail-section core";
    const summary=create("div","core-summary");
    append(summary,create("strong","",event.headline),
      create("p","","원문에서 확인한 변경과 실제 업무 영향 검토 근거를 구분해 보여줍니다."));
    append(section,summary);
    if (event.changes?.length) {
      const verifiedAi=new Map((event.ai_summaries||[])
        .map(row=>[row.document_id+"|"+row.article,row]));
      const highlights=create("div","highlights");
      const featured=(event.highlights||[]).map(key=>
        (event.changes||[]).find(ch=>ch.document_id===key.document_id &&
          ch.article===key.article)).filter(Boolean);
      const shown=featured.length?featured:event.changes.slice(0,3);
      for (const change of shown) {
        const meaning=change.meaning||{};
        const row=create("div","highlight");
        if(meaning.source_check_required)row.className+=" highlight-caution";
        const lead=create("div","highlight-lead");
        append(lead,create("span","highlight-cat",
            meaning.label||"변경 조문"),
          create("span","highlight-doc",
            change.document_title+" · "+change.article));
        append(row,lead);
        const ai=verifiedAi.get(change.document_id+"|"+change.article);
        if(ai?.summary && !meaning.source_check_required) {
          append(row,create("strong","highlight-description",compact(ai.summary,160)),
            create("p","highlight-source-label",
              "AI 보조 요약 · 원문 인용 검증 완료"));
          if(ai.summary.length>160){
            const more=create("details","highlight-detail");
            append(more,create("summary","","핵심 요약 전체 보기"),
              create("p","",ai.summary));
            append(row,more);
          }
        } else {
          const description=meaning.description||change.brief||"원문 내용 확인 필요";
          append(row,create("strong","highlight-description",compact(description,160)));
          if(description.length>160){
            const more=create("details","highlight-detail");
            append(more,create("summary","","변경 설명 전체 보기"),
              create("p","",description));
            append(row,more);
          }
          if(meaning.source_check_required) {
            append(row,create("p","highlight-warning",
              "수집된 종전·현행 본문만으로는 실제 개정 내용을 단정할 수 없어 이 조문은 재확인 대상입니다."));
          }
        }
        if(meaning.before || meaning.after || meaning.focus?.length) {
          const toggle=create("details","highlight-detail");
          append(toggle,create("summary","","실제 달라진 부분 보기"));
          append(toggle,sourceDiffPreview(change,
            meaning.change_kind==="citation"?"종전 인용 조문":"변경 전",
            meaning.change_kind==="citation"?"현행 인용 조문":"변경 후"));
          append(row,toggle);
        }
        append(highlights,row);
      }
      if (event.changes.length>shown.length)
        append(highlights,create("p","section-help",
          "그 밖의 "+num(event.changes.length-shown.length)+
          "개 변경 조문은 아래 '공식 변경 전·후와 출처'에서 확인할 수 있습니다."));
      append(section,highlights);
    }
    const stats=create("div","impact-numbers");
    append(stats,create("span","","검토 기관 "+num(event.institution_count)+"곳"),
      create("span","","업무 검토사항 "+num(event.review_count)+"건"));
    if (event.public_service_lead_count)
      append(stats,create("span","","공공서비스 검토 후보 "+
        num(event.public_service_lead_count)+"건"));
    if (event.dependent_rules?.length)
      append(stats,create("span","","연관 규정 "+num(event.dependent_rules.length)+"건"));
    append(section,stats);
    return section;
  }
  function reviewCard(review) {
    const card=create("div","review-card");
    const type={
      direct_regulated_institution:"직접 규율기관",
      explicit_changed_clause:"변경 조문에 명시",
      verified_official_rule_citation:"관련 공식 규정 인용",
      verified_program_citation:"공식 사업 인용"
    }[review.basis_tier]||"공식 근거";
    append(card,create("div","review-meta",
      type+" · "+(review.program||review.document_title)+" · "+review.article));
    append(card,create("p","review-task",review.task));
    if (review.program && review.change)
      append(card,create("div","review-change",compact(review.change,150)));
    if (review.ai?.work_impact || review.ai?.question) {
      const suggestion=create("details","ai-inline");
      append(suggestion,create("summary","","AI 업무 영향 추가 검토"));
      if (review.ai.work_impact)
        append(suggestion,create("p","",review.ai.work_impact));
      if (review.ai.question)
        append(suggestion,create("p","",review.ai.question));
      append(card,suggestion);
    }
    const proof=create("details","proof");
    append(proof,create("summary","","변경 근거 확인"),
      create("p","",compact(review.basis_quote,420)),
      link(review.source_url,"변경 조문"),
      link(review.related_rule_url,"관련 공식 규정"),
      link(review.program_url,"공식 사업자료"));
    append(card,proof);
    return card;
  }
  function renderInstitutions(event) {
    const section=heading("기관별 변경·사업 검토사항",
      "변경 조문에 직접 연결된 기관 검토와 정부24에 등록된 실제 공공서비스 기준을 함께 찾되, 각각의 근거 수준은 구분해 보여줍니다.");
    const groups=view.impactGroups(event);
    if (!groups.length) {
      append(section,create("p","no-impacts",
        "이 변경 조문과 연결되는 기관·공공사업의 공식 근거가 아직 확인되지 않았습니다. 원천자료 수집·인용 대조가 더 필요합니다."));
      return section;
    }
    // Names come solely from this event's verified institutional reviews.
    // Switching policy events resets the selection in select(), never carrying
    // an agency from another policy into an unrelated event.
    if (state.institutionFilter!=="all" &&
        !groups.some(g=>g.agency===state.institutionFilter)) {
      state.institutionFilter="all";
    }

    const layout=create("div","institution-layout");
    const sidebar=create("aside","agency-filter-panel");
    append(sidebar,create("div","agency-filter-title","기관명 필터"));
    const search=create("input","agency-filter-search");
    search.type="search";
    search.placeholder="기관명 검색";
    search.setAttribute("aria-label","검토 대상 기관명 검색");
    const buttons=create("div","agency-filter-buttons");
    append(sidebar,search,buttons);

    const main=create("div","agency-filter-results");
    const compactLabel=create("label","agency-select-label","기관 선택");
    const compactSelect=create("select","agency-select");
    compactSelect.id="institution-select-"+event.id;
    compactLabel.setAttribute("for",compactSelect.id);
    compactSelect.setAttribute("aria-label","기관별 변경 검토사항 기관 선택");
    const all=create("option","","전체 기관 ("+num(groups.length)+")");
    all.value="all";
    append(compactSelect,all);
    for(const entry of groups) {
      const opt=create("option","",entry.agency+" ("+num(entry.reviews.length+entry.services.length)+")");
      opt.value=entry.agency;
      append(compactSelect,opt);
    }
    compactSelect.value=state.institutionFilter;
    const compactControl=create("div","agency-mobile-filter");
    append(compactControl,compactLabel,compactSelect);
    const counter=create("div","section-counter");
    counter.setAttribute("aria-live","polite");
    const results=create("div","agency-group-results");
    append(main,compactControl,counter,results);
    append(layout,sidebar,main);
    append(section,layout);

    function drawResults(){
      const shown=state.institutionFilter==="all" ? groups :
        groups.filter(g=>g.agency===state.institutionFilter);
      const reviewCount=shown.reduce((total,g)=>total+g.reviews.length,0);
      const serviceCount=shown.reduce((total,g)=>total+g.services.length,0);
      counter.textContent=num(shown.length)+"개 기관 · 변경 조문 검토 "+
        num(reviewCount)+"건 · 공공서비스 기준 확인 "+num(serviceCount)+"건";
      compactSelect.value=state.institutionFilter;
      results.replaceChildren();
      for(let i=0;i<shown.length;i++){
        const entry=shown[i];
        const group=create("details","agency-group");
        group.open=state.institutionFilter!=="all" ||
          shown.length<=3 || i===0;
        const top=create("summary","agency-heading");
        append(top,create("strong","",entry.agency),
          create("span","",num(entry.reviews.length+entry.services.length)+"건"));
        append(group,top);
        for(const review of entry.reviews){
          append(group,reviewCard(review));
        }
        for(const service of entry.services) {
          append(group,serviceLeadCard(service));
        }
        append(results,group);
      }
    }
    function drawFilterButtons(){
      const term=search.value.trim().toLocaleLowerCase("ko-KR");
      buttons.replaceChildren();
      const allButton=create("button",
        "agency-filter-button"+(state.institutionFilter==="all"?" active":""),
        "전체 기관");
      allButton.type="button";
      allButton.setAttribute("aria-pressed",
        String(state.institutionFilter==="all"));
      append(allButton,create("span","agency-filter-count",num(groups.length)));
      allButton.onclick=()=>choose("all");
      append(buttons,allButton);
      let matched=0;
      for(const entry of groups){
        if(!entry.agency.toLocaleLowerCase("ko-KR").includes(term))continue;
        matched++;
        const selected=state.institutionFilter===entry.agency;
        const button=create("button",
          "agency-filter-button"+(selected?" active":""));
        button.type="button";
        button.setAttribute("aria-pressed",String(selected));
        button.dataset.institution=entry.agency;
        append(button,create("span","agency-filter-name",entry.agency),
          create("span","agency-filter-count",num(entry.reviews.length+entry.services.length)));
        button.onclick=()=>choose(entry.agency);
        append(buttons,button);
      }
      if(!matched && term)
        append(buttons,create("p","agency-no-match","검색된 기관이 없습니다."));
    }
    function choose(name){
      state.institutionFilter=name;
      drawFilterButtons();
      drawResults();
    }
    search.oninput=()=>drawFilterButtons();
    compactSelect.onchange=()=>choose(compactSelect.value);
    drawFilterButtons();
    drawResults();
    return section;
  }
  function renderEvidence(event) {
    const section=heading("공식 변경 전·후와 출처");
    const wrapper=create("details","evidence-panel");
    append(wrapper,create("summary","",
      "조문 대조 "+num(event.changes?.length||0)+"건 · 원문 펼쳐 보기"));
    for (const [i,ch] of (event.changes||[]).entries()) {
      if (i===5) {
        const more=create("details","more-clauses");
        append(more,create("summary","",
          "추가 변경 조문 "+num(event.changes.length-5)+"건"));
        for (const other of event.changes.slice(5))
          append(more,sourcePair(other));
        append(wrapper,more);
        break;
      }
      append(wrapper,sourcePair(ch,i));
    }
    if (!event.changes?.length)
      append(wrapper,create("p","section-help",
        "신규 제정 또는 폐지 사실을 확인했습니다. 종전·현행 조문 대조는 없습니다."));
    append(section,wrapper);
    if (event.source_count>1) {
      const documents=create("details","evidence-panel");
      append(documents,create("summary","",
        "동시 개정된 법령 "+num(event.source_count)+"건 확인"));
      for (const member of event.members||[]) {
        const row=create("div","member-row");
        append(row,create("span","",member.title),
          link(member.url,"공식 원문"));
        append(documents,row);
      }
      append(section,documents);
    }
    if (event.dependent_rules?.length) {
      const refs=create("details","evidence-panel");
      append(refs,create("summary","",
        "변경 조문을 인용하는 관련 규정 "+num(event.dependent_rules.length)+"건"));
      for (const ref of event.dependent_rules) {
        const row=create("div","member-row");
        append(row,create("span","",ref.title+" · "+ref.article),
          link(ref.url,"규정 원문"));
        append(refs,row);
      }
      append(section,refs);
    }
    return section;
  }
  function renderAI(event) {
    if (!event.ai_summaries?.length) return null;
    const section=heading("AI 보조검토");
    const drawer=create("details","evidence-panel");
    append(drawer,create("summary","",
      "원문 근거를 확인한 AI 추가 검토 "+num(event.ai_summaries.length)+"건"));
    for (const item of event.ai_summaries.slice(0,12)) {
      const card=create("div","ai-review");
      append(card,create("strong","",item.summary),
        create("p","",item.question),
        create("small","",item.article+" · 공식 원문 인용: "+
          item.before_quote+" → "+item.after_quote));
      append(drawer,card);
    }
    if (event.ai_summaries.length>12)
      append(drawer,create("p","section-help","나머지 AI 검토는 공식 조문 상세에 반영됩니다."));
    append(section,drawer);
    return section;
  }
  function serviceLeadCard(item) {
    const card=create("details","review-card service-review-lead");
    const title=create("summary","service-review-heading");
    append(title,create("strong","",item.service_name),
      create("span","",item.match_tier==="official_clause_citation"?
        "공식 변경 조문 인용":"공식 법령명 인용 · 조문 확인 필요"));
    append(card,title);
    const content=create("div","public-service-lead-body");
    append(content,create("p","",
      "개정 근거: "+item.law_title+" "+item.article));
    for(const target of item.review_targets||[]) {
      const box=create("div","service-criterion");
      append(box,create("strong","",target.field+" · 검토할 기준"),
        create("p","",target.review_question));
      if(target.old_value&&target.new_legal_value)
        append(box,create("p","service-criterion-values",
          "서비스 등록기준 "+target.old_value+" → 개정 조문 "+target.new_legal_value));
      const original=create("details","service-source");
      append(original,create("summary","","실제 서비스 등록기준 원문"),
        create("p","",target.source_excerpt));
      append(box,original);
      append(content,box);
    }
    const proof=create("details","service-source");
    append(proof,create("summary","","공식 법령 인용 근거 펼쳐보기"),
      create("p","",item.basis_quote));
    append(content,proof,
      link(item.service_url||item.source_url,
        item.service_url?"정부24 서비스 원문":"정부24 공식 서비스 데이터"));
    append(card,content);
    return card;
  }

  function renderDetail() {
    const root=$("detail");root.replaceChildren();
    const event=state.events.find(e=>e.id===state.selected);
    if (!event) {
      append(root,create("p","empty","정책 변경 사건을 선택하세요."));
      return;
    }
    const head=create("header","detail-head");
    const meta=create("div","detail-meta");
    append(meta,pill(view.category(event),"type "+event.kind),
      create("span","",event.published_at||""),
      event.verification==="partial" ?
        pill("일부 조문 대조","partial"):null);
    append(head,meta,create("h2","",event.title),
      event.effective_date ?
        create("p","effective","시행일 "+event.effective_date):null);
    append(root,head,renderCore(event),
      renderInstitutions(event),renderEvidence(event),renderAI(event));
  }
  function renderAgencyDirectory(query) {
    const root=$("agency-directory-results");
    root.replaceChildren();
    const term=String(query||"").trim().toLocaleLowerCase("ko-KR");
    root.hidden=!term;
    if(!term)return;
    const results=(state.data?.agency_directory||[]).filter(row=>
      String(row.agency||"").toLocaleLowerCase("ko-KR").includes(term));
    if(!results.length) {
      append(root,create("p","empty","해당 이름의 공식기관 명부 기록이 없습니다."));
      return;
    }
    for(const agency of results.slice(0,20)) {
      const row=create("div","directory-entry");
      append(row,create("strong","",agency.agency),
        create("span","",
          "알리오 사업 "+num(agency.alioplus_programs)+"건 · 정부24 서비스 "+
          num(agency.gov24_services)+"건"));
      append(root,row);
    }
    if(results.length>20)
      append(root,create("p","section-help",
        "상위 20개 기관만 표시합니다. 기관명을 더 구체화하세요."));
  }
  function show(data) {
    if (data.schema !== "policy-domino-next-v1" ||
        !Array.isArray(data.events)) throw Error("정책 변경 사건 데이터가 없습니다.");
    state.data=data;
    state.events=data.events;
    state.mode="all";
    state.institutionFilter="all";
    const stats=view.overview(data.events,data.ai_progress||{});
    const progress=data.ai_progress||{};
    const run=data.ai_run||{};
    const total=progress.verified_clauses ?? 0;
    const analyzed=progress.ai_analyzed_clauses ?? 0;
    const audit=(data.quality||{}).analysis_status||{};
    const count=(data.collection_run||{}).failed_windows||0;
    $("analysis-coverage").textContent=
      "공식 판본 "+num(audit.indexed??progress.indexed_documents)+"건"+
      " · 신구 차이 확인 "+num(progress.verified_document_changes??audit.checked)+"건"+
      " · 수집·분석 현황 펼치기";
    $("analysis-diagnostics").textContent=
      "공식 문서 "+num(audit.indexed??progress.indexed_documents)+"건 중"+
      " 신구·제정·폐지 확인 "+num(audit.checked??progress.verified_document_changes)+"건"+
      " · 아직 미분석 "+num(audit.unexamined)+"건"+
      " · 재확인 대상 "+num(audit.retryable)+"건"+
      " · 재확인 유예 "+num(audit.blocked)+"건"+
      (count?" · 원천 수집 미완료 구간 "+num(count)+"개":"");
    const checked=run.checked_at?String(run.checked_at).replace("T"," ").slice(0,16)+" UTC":"미실행";
    $("ai-review-progress").textContent=
      "AI 정책 변경 설명 "+num(progress.analyzed_events)+"건"+
      " · 추가 분석 대상 "+num(progress.pending_events)+"건";
    $("ai-diagnostics").textContent=
      "AI 검토 완료 "+num(analyzed)+" / 변경 조문 "+num(total)+"건"+
      " · 최근 실행 "+checked+
      " · 요청 "+num(run.attempted)+"회, 신규 결과 "+num(run.generated)+"건"+
      (run.errors?" · 검증/호출 오류 "+num(run.errors)+"건":"")+
      (run.stopped_reason?" · 중단 사유: "+run.stopped_reason:"");
    const rules=(data.quality||{}).rule_categories||{};
    const notices=rules["고시"];
    const unclassified=rules["미분류"];
    const noticeEnd=(data.collection_run?.backfill_end_dates||{})["admrul|2|3"];
    $("institution-diagnostics").textContent=
      (notices?"고시 "+num(notices.indexed)+"건 색인 · 변경 확인 "+
        num(notices.changed)+"건 · 분석 대기 "+num(notices.pending)+"건 · ":"")+
      (unclassified?.indexed?"행정규칙 종류 미확인 "+num(unclassified.indexed)+"건 · ":"")+
      (noticeEnd?"고시 연혁 과거 수집 기준일 "+noticeEnd+" · ":"")+
      "기관별 검토사항 "+num(progress.institutional_reviews)+"건"+
      " · 공공사업 인용 연결 "+num(progress.verified_program_links)+"건"+
      " · 관련 공식 규정 소관기관 연결 "+num(progress.referencing_public_rule_reviews)+"건"+
      " · 알리오 공공사업 원천자료 "+num(progress.official_program_records)+"건"+
      " · 정부24 공공서비스 "+num(data.public_services_indexed||0)+"건"+
      " · 검토 후보 "+num(data.public_service_review_leads||0)+"건";
    const register=data.agency_directory_audit||{};
    const gov24=data.gov24_audit||{};
    $("institution-link-progress").textContent=
      "알리오플러스 공공사업 "+num(progress.official_program_records)+"건"+
      " / 운영기관 "+num(register.alioplus_agencies)+"곳 · 정부24 공공서비스 "+
      num(data.public_services_indexed)+"건 / 운영기관 "+
      num(register.gov24_agencies)+"곳. 기관 명부 등재와 정책별 영향 연결은 별개이며, "+
      (gov24.status==="collected_incrementally"?
        "정부24 수집은 증분 진행 중입니다.":
        gov24.status==="not_configured"?
        "정부24 API 인증이 설정되지 않았습니다.":
        "정부24 최신 전체 갱신 여부는 확인되지 않았습니다.");
    $("stat-events").textContent=num(audit.indexed??progress.indexed_documents??data.documents?.length??0);
    $("stat-agencies").textContent=num(stats.institutions);
    $("stat-actions").textContent=num(stats.actions);

    $("updated").textContent=data.generated_at ?
      " · 자료 갱신 "+String(data.generated_at).replace("T"," ").slice(0,16)+" UTC":"";
    const linked=eventHash();
    state.selected=state.events.some(e=>e.id===linked) ?
      linked:(view.filterEvents(state.events)[0]?.id||null);
    renderList();renderDetail();
    if (linked && mobile()) select(linked,false);
    else if (mobile()) back(false);
  }
  for (const mode of view.MODES) {
    $("mode-"+mode).onclick=()=>{
      state.mode=mode;
      state.visible=60;
      renderList();
      if(!mobile()){
        const shown=filtered();
        if(shown.length&&!shown.some(event=>event.id===state.selected)){
          select(shown[0].id,false);
        } else if(!shown.length) {
          state.selected=null;
          renderDetail();
        }
      }
    };
  }
  $("search").oninput=ev=>{
    state.query=String(ev.target.value||"").trim();
    state.visible=60;
    renderList();
  };
  $("agency-directory-search").oninput=ev=>
    renderAgencyDirectory(ev.target.value);
  $("more").onclick=()=>{state.visible+=60;renderList();};
  $("backToList").onclick=()=>back();
  window.addEventListener("popstate",()=>{
    const id=eventHash();
    if (id && state.events.some(e=>e.id===id)) select(id,false);
    else back(false);
  });
  window.addEventListener("resize",()=>{
    if (!mobile()) {
      $("layout").classList.remove("detail-open");
      document.body.classList.remove("detail-active");
    } else if (!eventHash()) back(false);
  });
  fetch("./data.json",{cache:"no-store"})
    .then(res=>{
      if(!res.ok)throw Error("공식 정책 데이터 응답 오류");
      return res.json();
    }).then(show).catch(err=>{
      $("items").replaceChildren(create("p","empty",
        "공식 정책 변경 데이터를 불러오지 못했습니다."));
      $("detail").replaceChildren(create("p","no-impacts",String(err)));
      $("list-count").textContent="불러오기 실패";
    });
})();