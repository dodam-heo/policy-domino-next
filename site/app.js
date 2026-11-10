(() => {
  "use strict";
  const $ = name => document.getElementById(name);
  const view = window.PolicyDominoView;
  const state = {
    data: null, events: [], selected: null, mode: "all", query: "", visible: 60
  };
  const MODES = view.MODES;
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
            "alioplus.go.kr"].includes(valid.hostname)) return null;
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
    for (const mode of MODES) {
      const button=$("mode-"+mode);
      const active=state.mode===mode;
      if (active) button.classList.add("active");
      else button.classList.remove("active");
      button.setAttribute("aria-pressed",String(active));
    }
  }
  function filtered() {
    return view.filterEvents(state.events,state);
  }
  function renderList() {
    renderFilters();
    const events=filtered();
    const root=$("items");root.replaceChildren();
    $("list-count").textContent=num(events.length)+"건";
    if (!events.length) {
      append(root,create("p","empty",
        "조건에 맞는 검증된 정책 변경 사건이 없습니다. 다른 조건으로 확인하세요."));
    }
    for (const event of events.slice(0,state.visible)) {
      const item=create("button","item"+(event.id===state.selected?" selected":""));
      item.type="button";
      item.dataset.eventId=event.id;
      const header=create("div","item-top");
      append(header,pill(view.category(event),"type "+event.kind),
        create("span","item-date",event.published_at||"날짜 미확인"));
      const tags=create("div","item-tags");
      if (event.source_count>1) append(tags,pill("동시 개정 "+num(event.source_count)+"건"));
      if (event.institution_count) append(tags,pill("검토 기관 "+num(event.institution_count)+"곳","impact"));
      if (event.review_count) append(tags,pill("업무 "+num(event.review_count)+"건"));
      if (event.ai_count) append(tags,pill("AI 보조검토","ai"));
      const brief=event.changes?.[0]?.brief;
      append(item,header,create("h3","",event.title),
        create("p","item-brief",compact(brief||event.headline,95)),tags);
      item.onclick=()=>select(event.id);
      append(root,item);
    }
    $("more").hidden=events.length<=state.visible;
  }
  function sourcePair(change, index) {
    const wrap=create("div","clause");
    const name=(change.document_title||"공식 규정")+" · "+change.article;
    append(wrap,create("div","clause-name",name));
    const edits=(change.actual_edits||[]).filter(x=>
      String(x.old_excerpt||"")!==String(x.new_excerpt||""));
    const pairs=edits.length ? edits.slice(0,3) : [{
      old_excerpt:compact(change.before,190),
      new_excerpt:compact(change.after,190),
    }];
    for (const pair of pairs) {
      const values=create("div","pair");
      const before=create("div","before");
      const after=create("div","after");
      append(before,create("small","value-label","변경 전"),
        create("p","",pair.old_excerpt||"해당 문구 없음"));
      append(after,create("small","value-label","변경 후"),
        create("p","",pair.new_excerpt||"해당 문구 삭제"));
      append(values,before,after);
      append(wrap,values);
    }
    append(wrap,link(change.source_url,"공식 변경 조문"));
    return wrap;
  }
  function renderCore(event) {
    const section=heading("이번 정책의 핵심 변경");
    section.className="detail-section core";
    const summary=create("div","core-summary");
    append(summary,create("strong","",event.headline),
      create("p","",event.source_count>1 ?
        "공식 공포번호·공포일이 같은 "+num(event.source_count)+
        "개 법령을 하나의 변경 사건으로 묶었습니다." :
        "공식 자료에서 확인된 제·개정 내용을 표시합니다."));
    append(section,summary);
    if (event.changes?.length) {
      const highlights=create("div","highlights");
      for (const change of event.changes.slice(0,3)) {
        const row=create("div","highlight");
        append(row,create("span","highlight-cat",change.category||"조문"),
          create("strong","",change.article+" · "+compact(change.brief,145)));
        if (event.source_count>1)
          append(row,create("span","highlight-doc",change.document_title));
        append(highlights,row);
      }
      if (event.changes.length>3)
        append(highlights,create("p","section-help",
          "나머지 "+num(event.changes.length-3)+"개 변경 조문은 아래 공식 대조에서 확인"));
      append(section,highlights);
    }
    const stats=create("div","impact-numbers");
    append(stats,create("span","","검토 기관 "+num(event.institution_count)+"곳"),
      create("span","","업무 검토사항 "+num(event.review_count)+"건"));
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
      link(review.program_url,"공식 사업자료"));
    append(card,proof);
    return card;
  }
  function renderInstitutions(event) {
    const section=heading("기관별 변경 검토사항",
      "변경된 조문으로 검토 대상이 특정된 기관·사업입니다. 실제 반영 여부는 확인되지 않았습니다.");
    const groups=view.impactGroups(event);
    if (!groups.length) {
      append(section,create("p","no-impacts",
        "변경 내용은 확인됐지만, 직접 규율받는 기관이나 사업의 연결 근거는 아직 확인되지 않았습니다."));
      return section;
    }
    const counter=create("div","section-counter",
      num(groups.length)+"개 기관 · "+num(event.review_count)+"건");
    append(section,counter);
    for (let i=0;i<groups.length;i++) {
      const entry=groups[i];
      const group=create("details","agency-group");
      group.open=groups.length<=3||i===0;
      const top=create("summary","agency-heading");
      append(top,create("strong","",entry.agency),
        create("span","",num(entry.reviews.length)+"건"));
      append(group,top);
      for (const review of entry.reviews)
        append(group,reviewCard(review));
      append(section,group);
    }
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
    append(root,head,renderCore(event),renderInstitutions(event),
      renderEvidence(event),renderAI(event));
  }
  function show(data) {
    if (data.schema !== "policy-domino-next-v1" ||
        !Array.isArray(data.events)) throw Error("정책 변경 사건 데이터가 없습니다.");
    state.data=data;
    state.events=data.events;
    state.mode="all";
    const stats=view.overview(data.events,data.ai_progress||{});
    $("stat-events").textContent=num(stats.events);
    $("stat-agencies").textContent=num(stats.institutions);
    $("stat-actions").textContent=num(stats.actions);
    $("source-status").textContent=
      "공식 수집 문서 "+num(stats.sources)+"건 중 "+
      "변경을 확인해 구성한 사건 "+num(stats.events)+"건";
    $("updated").textContent=data.generated_at ?
      " · 자료 갱신 "+String(data.generated_at).replace("T"," ").slice(0,16)+" UTC":"";
    const linked=eventHash();
    state.selected=state.events.some(e=>e.id===linked) ?
      linked:(view.filterEvents(state.events)[0]?.id||null);
    renderList();renderDetail();
    if (linked && mobile()) select(linked,false);
    else if (mobile()) back(false);
  }
  for (const mode of MODES) {
    $("mode-"+mode).onclick=()=>{
      state.mode=mode;
      state.visible=60;
      renderList();
      if (!mobile()) {
        const shown=filtered();
        if (shown.length && !shown.some(e=>e.id===state.selected))
          select(shown[0].id,false);
      }
    };
  }
  $("search").oninput=ev=>{
    state.query=String(ev.target.value||"").trim();
    state.visible=60;
    renderList();
  };
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