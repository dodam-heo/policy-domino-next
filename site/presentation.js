/* Pure presentation projections. No DOM access and no inferred agency duties. */
(function (global) {
  "use strict";

  const TYPES = Object.freeze(["all", "new", "amended", "repealed", "verified", "ai"]);

  function policyType(doc) {
    const revision = String(doc.revision || "");
    const status = doc.analysis?.status;
    if (status === "repeal" || /폐지|실효/.test(revision)) return "repealed";
    if (status === "enactment" || (/제정|신설/.test(revision) && !/개정/.test(revision))) return "new";
    if (/개정|정정/.test(revision)) return "amended";
    return "unknown";
  }

  function aiComplete(doc) {
    return doc?.analysis?.ai?.status === "generated" &&
      Array.isArray(doc.analysis.ai.change_reviews) &&
      doc.analysis.ai.change_reviews.length > 0;
  }

  function hasVerifiedDifference(doc) {
    return ["compared", "partial_compared"].includes(doc?.analysis?.status) &&
      Array.isArray(doc.analysis.changes) && doc.analysis.changes.length > 0;
  }

  function analysisProgress(documents) {
    const verified = documents.filter(hasVerifiedDifference).length;
    const analyzed = documents.filter(aiComplete).length;
    return {
      indexed: documents.length, verified, analyzed,
      pending: Math.max(0, verified - analyzed),
    };
  }

  function filterDocuments(documents, { query = "", mode = "all" } = {}) {
    if (!TYPES.includes(mode)) throw new Error("Unsupported policy type");
    const phrase = String(query).toLocaleLowerCase("ko-KR");
    return [...documents].filter(doc => {
      if (!String(doc.title + " " + (doc.ministry || "")).toLocaleLowerCase("ko-KR").includes(phrase)) {
        return false;
      }
      if (mode === "ai") return aiComplete(doc);
      if (mode === "verified") return hasVerifiedDifference(doc);
      return mode === "all" || policyType(doc) === mode;
    }).sort((left, right) =>
      String(right.published_at || "").localeCompare(String(left.published_at || "")) ||
      String(right.serial || "").localeCompare(String(left.serial || "")));
  }

  function groupByAgency(rows) {
    const groups = new Map();
    const seen = new Set();
    for (const row of rows) {
      const agency = String(row.agency || "").trim();
      if (!agency) continue;
      const key = JSON.stringify([agency, row.program, row.review, row.url, row.location]);
      if (seen.has(key)) continue;
      seen.add(key);
      if (!groups.has(agency)) groups.set(agency, []);
      groups.get(agency).push(row);
    }
    return groups;
  }

  function impactView(doc, relationships = [], crossDocumentCandidates = [], programDependencies = []) {
    const edges = relationships.filter(edge => edge.source_event_id === doc.id);
    const actions = [];
    const namedActors = [];
    const programs = [];
    for (const dep of programDependencies) {
      if (dep.source_event_id !== doc.id ||
          dep.verification !== "verified_program_citation" ||
          dep.operational_program_verified !== true ||
          dep.required_action_verified !== false ||
          !dep.agency || !dep.program || !dep.program_url || !dep.citation_quote) continue;
      programs.push({
        agency: dep.agency, program: dep.program, programId: dep.program_id,
        article: dep.changed_article, path: dep.path,
        review: dep.review || "사업에 변경된 정책 기준이 적용되는지 확인",
        citation: dep.citation_quote, url: dep.program_url,
        location: dep.referenced_article || "", evidence: "verified_citation"
      });
    }

    for (const edge of edges) {
      // An exact legal citation is never an independently established program duty.
      if (edge.operational_program_verified === true &&
          edge.required_action_verified === true &&
          edge.verified_agency && edge.verified_program && edge.required_review &&
          edge.official_operational_url) {
        actions.push({
          agency: edge.verified_agency, program: edge.verified_program,
          review: edge.required_review, url: edge.official_operational_url,
          location: edge.operational_location || "", evidence: "program"
        });
      }
    }
    for (const candidate of crossDocumentCandidates) {
      if (candidate.source_event_id !== doc.id ||
          candidate.operational_program_verified !== false ||
          candidate.required_action_verified !== false ||
          !candidate.actor || !candidate.source_url) continue;
      namedActors.push({
        agency: candidate.actor, program: candidate.work_regulation || "관련 규정",
        location: candidate.target_location || "",
        review: candidate.review || "관련 조문 검토",
        url: candidate.source_url, evidence: "cited_actor"
      });
    }
    for (const candidate of doc.analysis?.direct_actor_reviews || []) {
      if (candidate.operational_program_verified !== false ||
          candidate.required_action_verified !== false ||
          !candidate.actor || !candidate.source_url) continue;
      namedActors.push({
        agency: candidate.actor, program: "변경 조문",
        location: candidate.article || "",
        review: candidate.review || "관련 조문 검토",
        url: candidate.source_url, evidence: "named_actor"
      });
    }
    return {
      actions: groupByAgency(actions),
      programs: groupByAgency(programs),
      namedActors: groupByAgency(namedActors),
      citations: edges,
    };
  }

  global.PolicyDominoView = Object.freeze({
    policyType, filterDocuments, aiComplete, hasVerifiedDifference, analysisProgress,
    groupByAgency, impactView
  });
})(window);
