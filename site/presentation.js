/* Source-driven navigation; separate amendment type, changed item and impacts.
   No policy topic gets a privileged, hard-coded pill. */
(function (global) {
  "use strict";
  const KINDS=Object.freeze(["all","new","amended","repealed"]);
  const IMPACTS=Object.freeze(["all","linked","unlinked"]);
  function category(event) {
    if(event.kind==="new")return "신규 제정";
    if(event.kind==="repealed")return "폐지";
    return "개정";
  }
  function hasInstitutionalReview(event) {
    return Array.isArray(event.institutional_reviews) &&
      event.institutional_reviews.length>0;
  }
  function eventTopics(event) {
    return [...new Set((event.changes||[])
      .map(x=>String(x.meaning?.label||x.category||"").trim())
      .filter(Boolean))];
  }
  function topicOptions(events) {
    return [...new Set(events.flatMap(eventTopics))].sort((a,b)=>
      a.localeCompare(b,"ko-KR"));
  }
  function filterEvents(events, {kind="all",topic="all",impact="all",query=""}={}) {
    if (!KINDS.includes(kind))throw Error("Unsupported change kind");
    if (!IMPACTS.includes(impact))throw Error("Unsupported institution-connection state");
    const term=String(query).trim().toLocaleLowerCase("ko-KR");
    return [...events].filter(event=>{
      if (kind!=="all"&&event.kind!==kind)return false;
      if (topic!=="all"&&!eventTopics(event).includes(topic))return false;
      if (impact==="linked"&&!hasInstitutionalReview(event))return false;
      if (impact==="unlinked"&&hasInstitutionalReview(event))return false;
      const searchable=[
        event.title,event.headline,event.ministry,
        ...(event.members||[]).map(x=>x.title),
        ...(event.changes||[]).map(x=>x.meaning?.label||x.category||""),
        ...(event.institutional_reviews||[]).flatMap(x=>[x.institution,x.program])
      ].join(" ").toLocaleLowerCase("ko-KR");
      return searchable.includes(term);
    }).sort((a,b)=>
      String(b.published_at||"").localeCompare(String(a.published_at||""))||
      (b.institution_count||0)-(a.institution_count||0)||
      String(a.id||"").localeCompare(String(b.id||"")));
  }
  function impactGroups(event) {
    const grouped=new Map();
    for(const review of event.institutional_reviews||[]) {
      const agency=String(review.institution||"").trim();
      if(!agency)continue;
      if(!grouped.has(agency))grouped.set(agency,[]);
      grouped.get(agency).push(review);
    }
    return Array.from(grouped,([agency,reviews])=>({agency,reviews}))
      .sort((a,b)=>a.agency.localeCompare(b.agency,"ko-KR"));
  }
  function overview(events,progress={}) {
    const agencies=new Set(events.flatMap(e=>
      (e.institutional_reviews||[]).map(x=>x.institution).filter(Boolean)));
    return {
      events:events.length,institutions:agencies.size,
      actions:events.reduce((sum,e)=>sum+(e.institutional_reviews||[]).length,0),
      sources:Number(progress.indexed_documents||0),
      comparedDocuments:Number(progress.verified_document_changes||0)
    };
  }
  global.PolicyDominoView=Object.freeze({
    KINDS,IMPACTS,category,hasInstitutionalReview,eventTopics,topicOptions,
    filterEvents,impactGroups,overview
  });
})(window);
