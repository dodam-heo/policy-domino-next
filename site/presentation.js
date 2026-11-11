/* One policy list, five evidence-based navigation choices. */
(function (global) {
  "use strict";
  const MODES=Object.freeze(["all","new","amended","repealed","impact"]);
  function category(event) {
    if(event.kind==="new")return "신규 제정";
    if(event.kind==="repealed")return "폐지";
    return "개정";
  }
  function hasInstitutionalReview(event) {
    return Array.isArray(event.institutional_reviews) &&
      event.institutional_reviews.length>0;
  }
  function highImpactScope(event) {
    // This pill measures only the *verified breadth of public-institution
    // review targets*, NOT a predicted socioeconomic impact score.
    if(Array.isArray(event.agency_names))
      return new Set(event.agency_names.filter(Boolean)).size>=2;
    const institutions=new Set((event.institutional_reviews||[])
      .map(review=>String(review.institution||"").trim())
      .filter(Boolean));
    return institutions.size>=2;
  }
  // Search names and effective years independently so re-titled annual
  // criteria remain discoverable without hard-coded example titles.
  const searchKey=value=>String(value||"")
    .toLocaleLowerCase("ko-KR").replace(/\s+/g,"");
  function effectiveYear(date) {
    const match=/^\d{4}/.exec(String(date||""));
    return match ? [match[0]+"년",match[0]+"년도"] : [];
  }
  function filterEvents(events,{mode="all",query=""}={}) {
    if(!MODES.includes(mode))throw Error("Unsupported event filter");
    const terms=String(query||"").trim().split(/\s+/)
      .map(searchKey).filter(Boolean);
    return [...events].filter(event=>{
      if(mode==="impact"&&!highImpactScope(event))return false;
      if(mode!=="all"&&mode!=="impact"&&event.kind!==mode)return false;
      const searchable=[
        event.title,event.headline,event.ministry,
        event.effective_date,...effectiveYear(event.effective_date),
        event.published_at,event.search_text||"",
        ...(event.members||[]).flatMap(x=>[x.title,x.kind]),
        ...(event.changes||[]).flatMap(x=>[
          x.document_title,x.article,x.meaning?.label||x.category||"",
        ]),
        ...(event.institutional_reviews||[]).flatMap(x=>[
          x.institution,x.program,x.task
        ]),
        ...(event.public_service_leads||[]).flatMap(x=>[
          x.agency,x.service_name,
          ...(x.review_targets||[]).map(y=>y.field)
        ])
      ].join(" ");
      const haystack=searchKey(searchable);
      return terms.every(term=>haystack.includes(term));
    }).sort((a,b)=>
      String(b.published_at||"").localeCompare(String(a.published_at||""))||
      (b.institution_count||0)-(a.institution_count||0)||
      String(a.id||"").localeCompare(String(b.id||"")));
  }
  function impactGroups(event) {
    // A single institution selector for independently verified changed-clause
    // reviews and official public-service review leads. These evidence tiers
    // must never be merged into "confirmed institutional actions".
    const grouped=new Map();
    function item(agency) {
      agency=String(agency||"").trim();
      if(!agency)return null;
      if(!grouped.has(agency))grouped.set(agency,{
        agency,reviews:[],services:[],
      });
      return grouped.get(agency);
    }
    for(const review of event.institutional_reviews||[]) {
      const target=item(review.institution);
      if(target)target.reviews.push(review);
    }
    for(const service of event.public_service_leads||[]) {
      if(service.verification!=="candidate_not_confirmed")continue;
      const target=item(service.agency);
      if(target)target.services.push(service);
    }
    return [...grouped.values()].sort((a,b)=>
      a.agency.localeCompare(b.agency,"ko-KR"));
  }
  function overview(events,progress={}) {
    const agencies=new Set(events.flatMap(e=>
      Array.isArray(e.agency_names)?e.agency_names:
        (e.institutional_reviews||[]).map(x=>x.institution).filter(Boolean)));
    return {
      events:events.length,institutions:agencies.size,
      actions:events.reduce((sum,e)=>sum+(e.review_count??
        (e.institutional_reviews||[]).length),0),
      sources:Number(progress.indexed_documents||0),
      comparedDocuments:Number(progress.verified_document_changes||0)
    };
  }
  global.PolicyDominoView=Object.freeze({
    MODES,category,hasInstitutionalReview,highImpactScope,searchKey,
    filterEvents,impactGroups,overview
  });
})(window);
