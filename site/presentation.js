/* Pure projections for source-verified POLICY EVENTS (not raw document rows). */
(function (global) {
  "use strict";
  const MODES = Object.freeze([
    "all","impact","benefit","new","amended","repealed"
  ]);
  const BENEFITS = new Set(["금액·비율","선정·자격"]);

  function category(event) {
    if (event.kind === "new") return "신규 제정";
    if (event.kind === "repealed") return "폐지";
    return "개정";
  }

  function hasInstitutionalReview(event) {
    return Array.isArray(event.institutional_reviews) &&
      event.institutional_reviews.length > 0;
  }

  function isBenefitEvent(event) {
    return Array.isArray(event.changes) &&
      event.changes.some(change => BENEFITS.has(change.category));
  }

  function matches(event, mode) {
    if (mode === "all") return true;
    if (mode === "impact") return hasInstitutionalReview(event);
    if (mode === "benefit") return isBenefitEvent(event);
    return event.kind === mode;
  }

  function filterEvents(events, {mode = "all", query = ""} = {}) {
    if (!MODES.includes(mode)) throw new Error("Unsupported event filter");
    const term = String(query).trim().toLocaleLowerCase("ko-KR");
    return [...events].filter(event => {
      const names = (event.institutional_reviews || []).map(x =>
        x.institution + " " + (x.program || "")).join(" ");
      const searchable = [
        event.title, event.headline, event.ministry,
        ...(event.members || []).map(x => x.title),
        names,
      ].join(" ").toLocaleLowerCase("ko-KR");
      return matches(event, mode) && searchable.includes(term);
    }).sort((a,b) =>
      String(b.published_at || "").localeCompare(String(a.published_at || "")) ||
      (b.institution_count || 0) - (a.institution_count || 0) ||
      String(a.id || "").localeCompare(String(b.id || "")));
  }

  function impactGroups(event) {
    const grouped = new Map();
    for (const review of event.institutional_reviews || []) {
      const agency = String(review.institution || "").trim();
      if (!agency) continue;
      if (!grouped.has(agency)) grouped.set(agency, []);
      grouped.get(agency).push(review);
    }
    return Array.from(grouped, ([agency, reviews]) => ({
      agency, reviews,
    })).sort((a,b) => a.agency.localeCompare(b.agency, "ko-KR"));
  }

  function overview(events, progress = {}) {
    const agencies = new Set(
      events.flatMap(e => (e.institutional_reviews || [])
        .map(x => x.institution).filter(Boolean))
    );
    return {
      events: events.length,
      institutions: agencies.size,
      actions: events.reduce((sum,e) =>
        sum + (e.institutional_reviews || []).length, 0),
      sources: Number(progress.indexed_documents || 0),
      comparedDocuments: Number(progress.verified_document_changes || 0),
    };
  }

  global.PolicyDominoView = Object.freeze({
    MODES, category, hasInstitutionalReview, isBenefitEvent,
    filterEvents, impactGroups, overview,
  });
})(window);
