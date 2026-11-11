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


def _to_particle(value: str) -> str:
    value = value.strip()
    if not value:
        return "로"
    final = ord(value[-1])-0xAC00
    if 0 <= final <= 11171 and final % 28 not in (0, 8):
        return "으로"
    return "로"


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


def focused_differences(before: str, after: str, limit: int = 3) -> list[dict]:
    """Source-exact windows surrounding the actual edits, never clause starts.

    Original text stays available in its entirety on demand. Parts are kept
    separate so the frontend can emphasize changed tokens without raw HTML.
    """
    before, after = str(before or ""), str(after or "")
    if before == after:
        return []
    small = len(before) + len(after) <= 8000
    windows = []
    if small:
        a, b = _tokens(before), _tokens(after)
        ai, bi = [0], [0]
        for token in a:
            ai.append(ai[-1] + len(token))
        for token in b:
            bi.append(bi[-1] + len(token))
        opcodes = difflib.SequenceMatcher(
            None, a, b, autojunk=(len(a)+len(b) > 350)).get_opcodes()
        for tag, i, j, k, m in opcodes:
            if tag == "equal":
                continue
            old_start,old_end,new_start,new_end=ai[i],ai[j],bi[k],bi[m]
            windows.append((old_start,old_end,new_start,new_end))
    else:
        # Linear-time common-prefix/suffix diff for large annexes and tables.
        common = 0
        m = min(len(before), len(after))
        while common < m and before[common] == after[common]:
            common += 1
        tail = 0
        while (tail < m-common and
               before[-tail-1] == after[-tail-1]):
            tail += 1
        windows=[(common,len(before)-tail,common,len(after)-tail)]
    if not windows:
        # Defensive fallback for unusual difflib behavior.
        windows=[(0,len(before),0,len(after))]

    def parts(text: str, start: int, end: int) -> dict:
        context = 55
        left=max(0,start-context)
        right=min(len(text),end+context)
        prefix = ("…" if left else "") + text[left:start]
        changed = text[start:end]
        suffix = text[end:right] + ("…" if right<len(text) else "")
        # Never disguise a giant replacement as an identical unchanging
        # prefix. Display at least the beginning of the changed source span.
        if len(changed)>190:
            changed=changed[:180]+"…"
        return {"prefix":prefix,"changed":changed,"suffix":suffix}

    ranked=[]
    for i,j,k,m in windows:
        old,new=parts(before,i,j),parts(after,k,m)
        weight=_score_fragment(before[i:j][:160],after[k:m][:160])
        if not old["changed"] and not new["changed"]:
            continue
        ranked.append((weight,i,{
            "before":old,"after":new,
            "type":("추가" if i==j else "삭제" if k==m else "교체"),
        }))
    selected=sorted(ranked,key=lambda x:(-x[0],x[1]))[:max(0,limit)]
    return [x[2] for x in sorted(selected,key=lambda x:x[1])]


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


def _currency_table_changes(before: str, after: str) -> list[dict]:
    """Align household amount tables only by matching official section titles.

    The same law can contain several visually identical seven-column tables
    (income, eligibility, facility, etc.). Matching rows by position or amount
    would falsely equate different programmes. A multi-table result is allowed
    only when every heading gives an unambiguous one-to-one match.
    """
    pattern = re.compile(
        r"구\s*분(?P<header>[^()]{1,180}?)금\s*액\s*\(\s*"
        r"(?P<unit>원(?:\s*/\s*월)?)\s*\)\s*"
        r"(?P<values>\d[\d,]*(?:\s+\d[\d,]*)*)")
    clause_title = re.compile(r"제\s*\d+\s*조\s*\(([^)]{2,140})\)")
    legacy_title = re.compile(
        r"(?<!\d)\d+\.\s*([가-힣ㆍ·‧\s]{3,85})")

    def latest_heading(text: str, position: int) -> str:
        prefix = text[:position]
        named = list(clause_title.finditer(prefix))
        old = list(legacy_title.finditer(prefix))
        matches = named + old
        if not matches:
            return ""
        return max(matches, key=lambda m: m.start()).group(1).strip()

    def tables(text: str) -> list[dict]:
        rows = []
        for match in pattern.finditer(text):
            columns = re.findall(r"(\d+)\s*인\s*가구", match["header"])
            values = match["values"].split()
            if (len(columns) < 2 or len(columns) != len(values)
                    or len(set(columns)) != len(columns)):
                continue
            heading = latest_heading(text, match.start())
            rows.append({"columns":columns, "values":values,
                         "unit":re.sub(r"\s+", "", match["unit"]),
                         "heading":heading,
                         "key":re.sub(r"[^가-힣a-zA-Z]", "", heading).lower()})
        return rows

    old_tables, new_tables = tables(before), tables(after)
    if not old_tables or len(old_tables) != len(new_tables):
        return []

    if len(old_tables) == 1:
        pairs = [(old_tables[0], new_tables[0])]
    else:
        def identity(table: dict) -> str:
            # Require a substantial literal prefix of the source's actual
            # section heading, not just a shared generic ending ("선정기준").
            return table["key"][:6] if len(table["key"]) >= 6 else ""
        old_ids = [identity(t) for t in old_tables]
        new_ids = [identity(t) for t in new_tables]
        if (not all(old_ids + new_ids)
                or len(set(old_ids)) != len(old_ids)
                or len(set(new_ids)) != len(new_ids)
                or set(old_ids) != set(new_ids)):
            return []
        by_id = dict(zip(new_ids, new_tables))
        pairs = [(row, by_id[identity(row)]) for row in old_tables]

    changes = []
    for a, b in pairs:
        if a["columns"] != b["columns"] or a["unit"] != b["unit"]:
            return []
        title = b["heading"].strip() if len(pairs) > 1 else ""
        for column, x, y in zip(a["columns"], a["values"], b["values"]):
            if x != y:
                label = (title + " · " if title else "") + column + "인 가구"
                changes.append({"column":label, "before":x,
                                "after":y, "unit":a["unit"]})
    return changes


def explain(before: str, after: str) -> dict:
    """Evidence-bound comparison: do not mistake token substitutions for meaning."""
    before, after = str(before or ""), str(after or "")
    fragmentary = _source_fragmentary(before, after)
    table_rows = _currency_table_changes(before, after) if not fragmentary else []
    citation = _literal_reference_update(before, after) if not fragmentary else None
    edits = _changed_fragments(before, after)
    best = edits[0]
    old_quote, new_quote = best["before"], best["after"]
    editorial = NON_CONTENT.sub("", before) == NON_CONTENT.sub("", after)
    focus = focused_differences(before, after)
    kind, score = "text_revision", 55
    if fragmentary:
        kind, label, score = "source_check", "종전·현행 원문 확인 필요", -10
        description = ("종전 또는 현행 조문이 항 번호만 수집되어 "
                       "정확한 변경 내용을 판단할 수 없습니다.")
        old_quote, new_quote = _abbreviate(before, 175), _abbreviate(after, 175)
    elif editorial:
        kind, label, score = "editorial", "표기 정비", 0
        description = "띄어쓰기 또는 문장부호가 정비됐습니다."
    elif table_rows:
        kind, label, score = "numeric", "금액·수치 기준", 105
        first = table_rows[0]
        old_quote, new_quote = first["before"], first["after"]
        description = (f"가구원 수별 금액표의 {len(table_rows)}개 기준이 변경됐습니다. "
                       f"{first['column']}: {old_quote} → {new_quote}{first['unit']}.")
        focus = [{"before": {"prefix": row["column"] + " ", "changed": row["before"],
                              "suffix": row["unit"]},
                  "after": {"prefix": row["column"] + " ", "changed": row["after"],
                             "suffix": row["unit"]}, "type": "교체"}
                 for row in table_rows[:6]]
    elif citation:
        kind, label, score = "citation", "인용 조문 변경", 18
        old_quote, new_quote = citation
        description = (f"이 조문에서 인용하는 조문이 {old_quote}에서 "
                       f"{new_quote}{_to_particle(new_quote)} 바뀌었습니다.")
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
            description = (f"{label}이 {old_quote}에서 "
                           f"{new_quote}{_to_particle(new_quote)} 바뀌었습니다.")
            score = 105
        elif broad:
            kind, label, score = "rewrite", (
                area if area != "조문 내용 변경" else "조문 내용 재구성"), 86
            if len(edits) == 1 and max(len(before), len(after)) <= 130:
                description = ("종전과 현행의 문구가 크게 달라, "
                               "동일 제도나 기관의 단순 명칭 변경으로 단정할 수 없습니다.")
            else:
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
    # Show the words that actually changed, not identical clause openings.
    # Preserve exact citations and amounts as the concise labels when present.
    if kind in ("rewrite", "multiple_edits", "source_check") and focus:
        first = focus[0]
        old_quote = _abbreviate("".join(first["before"].values()), 210)
        new_quote = _abbreviate("".join(first["after"].values()), 210)
    return {
        "label": label, "description": description,
        "focus": focus,
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
