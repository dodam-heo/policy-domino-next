"""Human-readable, evidence-bound descriptions of actual legal text differences.

Unlike raw SequenceMatcher character windows, this module never cuts Korean
words at arbitrary character offsets or equates punctuation with a substantive
public-program change. It makes no model call and invents no policy effect.
"""
from __future__ import annotations

import difflib
import re

TOKEN = re.compile(r"\s+|[^\W_]+|[^\w\s]|\S", re.UNICODE)
NON_CONTENT = re.compile(r"[\W_]+", re.UNICODE)
NUMERIC = re.compile(r"\d[\d,.]*\s*(?:억\s*원|만원|원|%|명|일|개월|년|배)")
LABELS = (
    ("금액·수치 기준", r"급여|지원금|지급액|금액|기준액|소득|산정|요율|부담금|정원|비율"),
    ("대상·자격 기준", r"자격|선정|대상자|수급자|입주|지원대상|요건|심사기준"),
    ("공고·공표 방식", r"공고|공표|신문|관보|공보|홈페이지|게시|공개|게재|통지"),
    ("신청·처리 절차", r"접수|처리|신청|제출|승인|신고|기한|기간|절차|이의신청"),
    ("조직·직무 기준", r"조직|정원|직급|직제|부서|업무분장|담당|위임|권한"),
    ("서식·증빙 기준", r"서식|첨부|증빙|증명서|별지|별표|서류"),
    ("인허가·감독 기준", r"허가|등록|검사|감독|행정처분|제재"),
    ("인용 법령·조문", r"법률|시행령|시행규칙|제\d+조|법령명|인용"),
)


def _tokens(value: str) -> list[str]:
    return TOKEN.findall(str(value or ""))


def _abbreviate(text: str, max_chars: int = 155) -> str:
    """Truncate only at whitespace/punctuation boundaries, not mid-word."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= max_chars:
        return text
    split = text.rfind(" ", 0, max_chars)
    if split < max_chars // 2:
        split = max((text.rfind(p, 0, max_chars) for p in ("，", "、", ",", ";", "·")),
                    default=-1)
    if split < max_chars // 2:
        # A single unspaced legal token cannot be safely shortened as a quote:
        # preserve it even when longer than the preferred display width.
        next_word = text.find(" ", max_chars)
        if next_word < 0:
            return text
        return text[:next_word].rstrip() + "…"
    return text[:split].rstrip() + "…"


def _clean_quote(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _local_phrase(tokens: list[str], start: int, stop: int) -> str:
    """Prefer the changed complete tokens and minimal insertion context."""
    if start != stop:
        return _clean_quote("".join(tokens[start:stop]))
    # For insertions/deletions, retain one whole adjacent token as an anchor.
    left = start - 1
    while left >= 0 and not tokens[left].strip():
        left -= 1
    right = stop
    while right < len(tokens) and not tokens[right].strip():
        right += 1
    if left >= 0 and NON_CONTENT.sub("", tokens[left]):
        return _clean_quote(tokens[left])
    if right < len(tokens):
        return _clean_quote(tokens[right])
    return ""


def _score_fragment(old: str, new: str) -> int:
    if NON_CONTENT.sub("", old) == NON_CONTENT.sub("", new):
        return 0
    score = 10
    if NUMERIC.search(old + " " + new):
        score += 30
    if len(old) + len(new) > 4:
        score += 8
    return score


def _large_clause_fragment(before: str, after: str) -> list[dict]:
    """Linear fallback for huge annexes; never perform quadratic token diff.

    Remove the identical prefix and suffix. This isolates a genuine changed
    source span even when a long clause has no paragraph separators.
    """
    left = 0
    limit = min(len(before), len(after))
    while left < limit and before[left] == after[left]:
        left += 1
    right = 0
    while (right < limit-left and
           before[len(before)-right-1] == after[len(after)-right-1]):
        right += 1
    last_old = len(before)-right if right else len(before)
    last_new = len(after)-right if right else len(after)

    def excerpt(text: str, first: int, last: int) -> str:
        if first == last:
            first = max(0, first - 35)
            last = min(len(text), last + 45)
        else:
            first = max(0, first - 35)
            last = min(len(text), last + 35)
        # For multiple distant replacements keep a bounded preview,
        # while full official before/after text remains available on demand.
        if last - first > 250:
            last = first + 190
        # Expand toward a complete word where possible.
        while first > 0 and not text[first-1].isspace() and (
                text[first-1].isalnum()) and first > max(0,left-100):
            first -= 1
        max_end = min(len(text), last + 80)
        while last < max_end and text[last].isalnum():
            last += 1
        return _abbreviate(text[first:last])

    a = excerpt(before, left, last_old)
    b = excerpt(after, left, last_new)
    return [{"before": a, "after": b,
             "score": _score_fragment(a,b), "offset": left}]


# Match exact legal references separately from financial values.
ARTICLE_REFERENCE = re.compile(
    r"제\s*\d+\s*조(?:의\s*\d+)?(?:\s*제\s*\d+\s*항)?"
    r"(?:\s*제\s*\d+\s*호)?"
)
ONLY_MARKER = re.compile(r"^(?:[①-⑳㉑-㊿]|[가-하]\s*[.)]|(?:제\s*)?\d+\s*[.)])$")


def is_placeholder_clause(value: str) -> bool:
    """An isolated paragraph marker is not evidence of complete legal text."""
    return bool(ONLY_MARKER.fullmatch(str(value or "").strip()))


def _literal_reference_update(before: str, after: str) -> tuple[str, str] | None:
    old = ARTICLE_REFERENCE.findall(before)
    new = ARTICLE_REFERENCE.findall(after)
    if len(old) != len(new) or not old:
        return None
    differing = [(x, y) for x, y in zip(old, new) if x != y]
    if len(differing) != 1:
        return None
    old_base = ARTICLE_REFERENCE.sub("<인용>", before)
    new_base = ARTICLE_REFERENCE.sub("<인용>", after)
    if re.sub(r"\s+", "", old_base) != re.sub(r"\s+", "", new_base):
        return None
    return differing[0]


def _changed_numeric(before: str, after: str) -> tuple[str, str] | None:
    old = set(NUMERIC.findall(before))
    new = set(NUMERIC.findall(after))
    a, b = sorted(old-new), sorted(new-old)
    return (a[0], b[0]) if len(a) == len(b) == 1 else None


def _changed_fragments(before: str, after: str) -> list[dict]:
    if len(before) + len(after) > 8000:
        return _large_clause_fragment(before, after)
    a, b = _tokens(before), _tokens(after)
    ranked = []
    for tag, i, j, k, m in difflib.SequenceMatcher(
            None, a, b, autojunk=(len(a)+len(b) > 350)
            ).get_opcodes():
        if tag == "equal":
            continue
        old, new = _local_phrase(a, i, j), _local_phrase(b, k, m)
        if old == new:
            continue
        ranked.append({
            "before": _abbreviate(old), "after": _abbreviate(new),
            "score": _score_fragment(old, new), "offset": i,
            "tag": tag,
        })
    if not ranked:
        ranked = [{
            "before": _abbreviate(before), "after": _abbreviate(after),
            "score": 0, "offset": 0, "tag": "replace",
        }]
    return sorted(ranked, key=lambda row: (-row["score"], row["offset"]))


def _subject_area(before: str, after: str, old_piece: str, new_piece: str) -> str:
    """Do not infer a changed procedure from a keyword on only one side."""
    for name, pattern in LABELS:
        if name == "인용 법령·조문":
            continue
        if re.search(pattern, old_piece) and re.search(pattern, new_piece):
            return name
    if len(before)+len(after) < 3600:
        similarity = difflib.SequenceMatcher(
            None, _tokens(before), _tokens(after), autojunk=True).ratio()
        # Only a near-identical rule offers enough common context to infer
        # the operation whose words changed. Wholly replaced actors do not.
        if similarity > 0.87:
            for name, pattern in LABELS:
                if name != "인용 법령·조문" and (
                        re.search(pattern, before[:1500]) and
                        re.search(pattern, after[:1500])):
                    return name
    return "조문 내용 변경"

def _source_fragmentary(before: str, after: str) -> bool:
    old, new = before.strip(), after.strip()
    return (is_placeholder_clause(old) and len(new) > 18 or
            is_placeholder_clause(new) and len(old) > 18)


def explain(before: str, after: str) -> dict:
    """Evidence-bound comparison: do not mistake token substitutions for meaning."""
    before, after = str(before or ""), str(after or "")
    fragmentary = _source_fragmentary(before, after)
    citation = _literal_reference_update(before, after) if not fragmentary else None
    edits = _changed_fragments(before, after)
    best = edits[0]
    old_quote, new_quote = best["before"], best["after"]
    editorial = NON_CONTENT.sub("", before) == NON_CONTENT.sub("", after)
    kind, score = "text_revision", 55
    if fragmentary:
        kind, label, score = "source_check", "종전·현행 원문 확인 필요", -10
        description = ("종전 또는 현행 조문이 항 번호만 수집되어 "
                       "정확한 변경 내용을 판단할 수 없습니다.")
        old_quote, new_quote = _abbreviate(before, 175), _abbreviate(after, 175)
    elif editorial:
        kind, label, score = "editorial", "표기 정비", 0
        description = "띄어쓰기 또는 문장부호가 정비됐습니다."
    elif citation:
        kind, label, score = "citation", "인용 조문 변경", 18
        old_quote, new_quote = citation
        description = (f"이 조문에서 인용하는 조문이 {old_quote}에서 "
                       f"{new_quote}으로 바뀌었습니다.")
    else:
        numeric = _changed_numeric(before, after)
        area = _subject_area(before, after, old_quote, new_quote)
        total = max(1, max(len(before), len(after)))
        low_commonality = len(before)+len(after) < 3600 and (
            difflib.SequenceMatcher(None, _tokens(before), _tokens(after),
                                    autojunk=True).ratio() < 0.48)
        broad = (low_commonality or
                 (len(edits) >= 3 and
                  sum(len(x["before"])+len(x["after"]) for x in edits)
                  > 0.35 * total))
        if numeric and not broad:
            kind = "numeric"
            old_quote, new_quote = numeric
            label = ("금액·수치 기준" if re.search(
                r"원|%|지급|소득|금액", old_quote+new_quote+area)
                else "인원·기간·수치 기준")
            description = f"{label}이 {old_quote}에서 {new_quote}로 변경됐습니다."
            score = 105
        elif broad:
            kind, label, score = "rewrite", (
                area if area != "조문 내용 변경" else "조문 내용 재구성"), 86
            description = ("여러 문구가 함께 바뀌어, 특정 단어 하나만으로 "
                           "개정 내용을 설명할 수 없습니다.")
            old_quote, new_quote = _abbreviate(before, 175), _abbreviate(after, 175)
        elif len(edits) == 1 and (not old_quote or not new_quote):
            kind = "addition" if not old_quote else "removal"
            label = "조문 문구 추가" if kind == "addition" else "조문 문구 삭제"
            description = ("현행 조문에 문구가 추가됐습니다." if kind == "addition"
                           else "종전 조문의 일부 문구가 삭제됐습니다.")
            score = 68
        elif len(edits) == 1 and old_quote and new_quote:
            kind, label = "term_edit", area
            if max(len(old_quote), len(new_quote)) <= 95 and (
                    "…" not in old_quote+new_quote):
                description = (f"종전 조문에는 ‘{old_quote}’, 현행 조문에는 "
                               f"‘{new_quote}’ 문구가 각각 사용됐습니다.")
            else:
                description = "조문 문구가 수정됐습니다. 신구 문맥을 대조하세요."
            score = 67 if area != "조문 내용 변경" else 60
        else:
            kind = "multiple_edits"
            label = area if area != "조문 내용 변경" else "여러 문구 변경"
            description = (f"조문 안의 {len(edits)}곳에서 문구가 변경됐습니다. "
                           "신구 문장과 원문을 함께 확인하세요.")
            old_quote, new_quote = _abbreviate(before, 175), _abbreviate(after, 175)
            score = 75
    return {
        "label": label, "description": description,
        "before": old_quote, "after": new_quote,
        "editorial": editorial and not fragmentary,
        "priority": score, "edits_count": len(edits),
        "change_kind": kind, "source_check_required": fragmentary,
    }


def event_headline(changes: list[dict]) -> str:
    """Count observed types instead of guessing program effects from keywords."""
    if not changes:
        return "공식 제정·폐지 확인"
    count = len(changes)
    ref = sum(x["meaning"]["change_kind"] == "citation" for x in changes)
    typ = sum(x["meaning"]["change_kind"] == "editorial" for x in changes)
    check = sum(x["meaning"]["change_kind"] == "source_check" for x in changes)
    substantive = count - ref - typ - check
    terms = [f"{count}개 조문에서 변경 확인"]
    if substantive:
        terms.append(f"내용 개정 {substantive}건")
    if ref:
        terms.append(f"인용 조문 수정 {ref}건")
    if typ:
        terms.append(f"표기 정비 {typ}건")
    if check:
        terms.append(f"원문 재확인 {check}건")
    return " · ".join(terms)


def highlight_changes(changes: list[dict], limit: int = 3, *,
                      institution_reviews: list[dict] | None = None,
                      ai_summaries: list[dict] | None = None) -> list[dict]:
    """Prioritize source-backed public-agency effects and substantive changes."""
    linked = {}
    weights = {
        "verified_program_citation": 55,
        "explicit_changed_clause": 40,
        "verified_official_rule_citation": 34,
        "direct_regulated_institution": 24,
    }
    for review in institution_reviews or []:
        key = (review.get("document_id"), review.get("article"))
        linked[key] = max(linked.get(key, 0),
                          weights.get(review.get("basis_tier"), 0))
    reviewed = {(x.get("document_id"), x.get("article"))
                for x in (ai_summaries or [])}
    ranked = sorted(changes, key=lambda row: (
        row["meaning"].get("source_check_required", False),
        row["meaning"].get("change_kind") in ("citation", "editorial"),
        -(row["meaning"]["priority"] +
          linked.get((row["document_id"], row["article"]), 0) +
          (15 if (row["document_id"], row["article"]) in reviewed else 0)),
        row.get("document_title", ""), row.get("article", ""),
    ))
    return ranked[:max(0, limit)]
