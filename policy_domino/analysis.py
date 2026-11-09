"""Version-safe difference and source-proven reference edges.

No agency, organization, program, amount or action is enrolled as an
expected answer. Every claim must point to a specific retrieved text span.
"""
from __future__ import annotations

import difflib
import re
from .core import clean

AMOUNT = re.compile(r"(?<!\d)\d[\d,]*(?:\.\d+)?\s*(?:원|만원|억\s*원|%|명|개월|일)(?![가-힣])")
CITATION = re.compile(r"「([^」]{2,110})」\s*(제\s*\d+\s*조(?:의\s*\d+)?)?")
ACTOR = re.compile(
    r"(?<![가-힣])([가-힣]{2,35}(?:장관|청장|원장|시장|군수|구청장|위원회|공사|공단|기관장))"
    r"(?:은|는|이|가)\s+")


def classify(text: str) -> str:
    patterns = (
        ("금액·비율", r"\d[\d,]*\s*(?:원|만원|억\s*원|%)|산정|요율"),
        ("선정·자격", r"자격|선정|대상자|수급자|소득|요건"),
        ("기한·절차", r"기한|처리기간|이내|제출|신청|통지"),
        ("서식·증빙", r"별지|서식|첨부서류|증명서|증빙"),
        ("허가·감독", r"허가|등록|검사|승인|신고|감독"),
        ("조직·정원", r"정원|직급|직제|사무분장|부서"),
    )
    return next((name for name, pattern in patterns if re.search(pattern, text)), "그 밖의 조문 변경")


def spans(before: str, after: str, limit: int = 6) -> list[dict]:
    seq = difflib.SequenceMatcher(None, before, after, autojunk=False)
    found = []
    for operation, i, j, k, m in seq.get_opcodes():
        if operation == "equal":
            continue
        left = before[max(0, i - 16):min(len(before), j + 16)]
        right = after[max(0, k - 16):min(len(after), m + 16)]
        if left == right:
            continue
        found.append({"old_excerpt":left, "new_excerpt":right})
        if len(found) >= limit:
            break
    return found


def compare(before: dict, after: dict, record: dict) -> dict:
    """Only full official body pairs can be certified as compared."""
    if before.get("status") in ("body_missing", "attachment_only") or \
       after.get("status") in ("body_missing", "attachment_only"):
        return {"status": "body_unavailable", "changes": [],
                "excluded": [], "reason": "종전 또는 현행 본문 미확보"}
    a, b = before.get("clauses", {}), after.get("clauses", {})
    changed = []
    excluded = []
    for article in sorted(set(a) | set(b)):
        old, new = a.get(article), b.get(article)
        if (old is None or new is None):
            # A missing key may mean the API omitted an annex, not a legal deletion.
            excluded.append({"article": article, "reason": "동일 조문 대응본 없음"})
            continue
        if not old.get("complete") or not new.get("complete"):
            excluded.append({"article": article, "reason": "본문 잘림·불완전"})
            continue
        old_text, new_text = old["text"], new["text"]
        if old_text == new_text:
            continue
        changed.append({
            "article": article, "before": old_text, "after": new_text,
            "actual_edits": spans(old_text, new_text),
            "category": classify(
                " ".join(x["old_excerpt"] + " " + x["new_excerpt"]
                         for x in spans(old_text, new_text))),
            "old_values": AMOUNT.findall(old_text),
            "new_values": AMOUNT.findall(new_text),
            "source_url": record["url"],
            "evidence": {
                "old_body_sha256": old["sha256"],
                "new_body_sha256": new["sha256"],
            },
        })
    if excluded or before["status"] == "partial" or after["status"] == "partial":
        status = "partial_compared" if changed else "partial_unresolved"
    else:
        status = "compared" if changed else "no_text_change"
    return {
        "status": status, "changes": changed, "excluded": excluded,
        "reason": ("일부만 비교됨" if excluded else "공식 전후 본문 비교"),
    }


def review_topics(changes: list[dict]) -> list[dict]:
    """Unassigned review suggestions, NEVER a confirmed institution action."""
    return [{
        "article": c["article"], "category": c["category"],
        "old_excerpt": c["actual_edits"][0]["old_excerpt"] if c["actual_edits"] else "",
        "new_excerpt": c["actual_edits"][0]["new_excerpt"] if c["actual_edits"] else "",
        "review": c["article"] + "의 변경 문구가 실제 업무 기준에 적용되는지 대조",
        "verification": "unassigned_source_clause",
        "source_url": c["source_url"],
    } for c in changes]


def extract_references(text: str) -> list[dict]:
    rows = []
    for match in CITATION.finditer(text):
        title = clean(match.group(1))
        clause = re.sub(r"\s+", "", match.group(2) or "")
        if not title:
            continue
        key = (title, clause)
        if key not in {(r["title"], r["article"]) for r in rows}:
            rows.append({"title": title, "article": clause,
                         "quote": text[max(0, match.start() - 35):
                                      min(len(text), match.end() + 75)]})
    return rows


def actors_in(text: str) -> list[str]:
    return list(dict.fromkeys(m.group(1) for m in ACTOR.finditer(text)))


def connect_changes(findings: dict, versions: dict, documents: dict,
                    max_edges: int = 1200) -> list[dict]:
    """Join exact published legal references to *changed* articles.

    Complexity: one pass over known official bodies plus a title/changed-
    article index. Citation is verified; real business/program adaptation is
    NOT inferred from citation alone.
    """
    changed_by_title = {}
    for event_id, finding in findings.items():
        doc = documents.get(event_id)
        if not doc or not finding.get("changes"):
            continue
        for change in finding["changes"]:
            changed_by_title.setdefault(
                (doc["title"], change["article"]), []).append(doc)
    edges = {}
    for citing_id, package in versions.items():
        citing = documents.get(citing_id)
        if not citing:
            continue
        for article, entry in package.get("clauses", {}).items():
            if not entry.get("complete"):
                continue
            body = entry["text"]
            for reference in extract_references(body):
                matched = changed_by_title.get(
                    (reference["title"], reference["article"]), ())
                for changed_doc in matched:
                    if citing_id == changed_doc["id"]:
                        continue
                    # A document predating a policy change may continue to
                    # reference it, but that is NOT a verified new impact.
                    if citing["published_at"] < changed_doc["published_at"]:
                        continue
                    key = (changed_doc["id"], citing_id, article,
                           reference["article"])
                    edges[key] = {
                        "source_event_id": changed_doc["id"],
                        "referencing_document_id": citing_id,
                        "referencing_title": citing["title"],
                        "referencing_article": article,
                        "changed_article": reference["article"],
                        "reference_quote": reference["quote"],
                        "referencing_source_url": citing["url"],
                        "publishing_agency": citing.get("ministry", ""),
                        "explicit_actors": actors_in(body),
                        "relationship": "verified_exact_article_citation",
                        "operational_program_verified": False,
                        "required_action_verified": False,
                    }
                    if len(edges) >= max_edges:
                        return list(edges.values())
    return list(edges.values())
