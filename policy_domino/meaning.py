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


def explain(before: str, after: str) -> dict:
    """Describe *literal* changed phrases, distinguishing mechanical edits.

    The preview strings must occur as source-aligned token runs. A future
    AI-generated natural-language description belongs in a separate, verified
    field instead of replacing official-source evidence.
    """
    ranked = []
    # Huge published annexes may contain tens of thousands of repeated tokens.
    # SequenceMatcher(autojunk=False) can become prohibitively slow there.
    if len(before) + len(after) > 8000:
        ranked = _large_clause_fragment(before, after)
    else:
        a, b = _tokens(before), _tokens(after)
        for tag, i, j, k, m in difflib.SequenceMatcher(
                None, a, b, autojunk=(len(a)+len(b) > 350)
                ).get_opcodes():
            if tag == "equal":
                continue
            old = _local_phrase(a, i, j)
            new = _local_phrase(b, k, m)
            if old == new:
                continue
            ranked.append({
                "before": _abbreviate(old),
                "after": _abbreviate(new),
                "score": _score_fragment(old, new),
                "offset": i,
            })
    if not ranked:
        # Rare case where tokenization erased only a whitespace adjustment.
        ranked = [{"before": _abbreviate(before), "after": _abbreviate(after),
                   "score": 0, "offset": 0}]
    ranked.sort(key=lambda item: (-item["score"], item["offset"]))
    best = ranked[0]
    editorial = NON_CONTENT.sub("", before) == NON_CONTENT.sub("", after)
    if editorial:
        label = "띄어쓰기·표기 정비"
        priority = 0
    else:
        # Decide meaning from the changed text plus its local statutory
        # sentence; do not scan unrelated clauses in an omnibus instrument.
        local_text = best["before"] + " " + best["after"]
        raw = str(before) + " " + str(after)
        label = "조문 내용 변경"
        if NUMERIC.search(local_text):
            has_money = bool(re.search(
                r"\d[\d,.]*\s*(?:억\s*원|만원|원|%)", local_text))
            has_money = has_money or bool(re.search(
                r"지급액|지원금|기준액|요율|부담금", raw))
            label = "금액·수치 기준" if has_money else "인원·기간·수치 기준"
        else:
            # A bounded complete sentence often contains the governing verb
            # (e.g. 공고) even if the modified object is the newspaper.
            context = raw[:900] if len(raw) < 900 else local_text
            for name, pattern in LABELS:
                if re.search(pattern, local_text):
                    label = name
                    break
            if label == "조문 내용 변경":
                for name, pattern in LABELS:
                    if re.search(pattern, context):
                        label = name
                        break
        priority = max((x["score"] for x in ranked), default=0)
        if label != "조문 내용 변경":
            priority += 15
    old_quote, new_quote = best["before"], best["after"]
    if editorial:
        description = "띄어쓰기나 문장부호가 정비됐습니다."
    else:
        nums_old = set(NUMERIC.findall(old_quote))
        nums_new = set(NUMERIC.findall(new_quote))
        removed, added = sorted(nums_old - nums_new), sorted(nums_new - nums_old)
        if len(removed) == len(added) == 1 and label in {
                "금액·수치 기준", "인원·기간·수치 기준"}:
            description = (
                f"{label}이 {removed[0]}에서 {added[0]}로 바뀌었습니다.")
        elif (old_quote and new_quote and old_quote != new_quote and
              max(len(old_quote), len(new_quote)) <= 38 and
              not ("…" in old_quote + new_quote)):
            description = (
                f"{label}에 쓰인 표현이 ‘{old_quote}’에서 "
                f"‘{new_quote}’로 바뀌었습니다.")
        elif label == "조문 내용 변경":
            description = (
                "조문의 문구가 수정됐습니다. 변경 전후의 표현을 확인하세요.")
        else:
            description = f"{label}에 관한 조문 문구가 수정됐습니다."
    return {
        "label": label,
        "description": description,
        "before": best["before"],
        "after": best["after"],
        "editorial": editorial,
        "priority": priority,
        "edits_count": len(ranked),
    }


def event_headline(changes: list[dict]) -> str:
    """Count confirmed amendments, not unverified impacts or raw documents."""
    if not changes:
        return "공식 제정·폐지 확인"
    from collections import Counter
    count = len(changes)
    labels = Counter(ch["meaning"]["label"] for ch in changes
                     if not ch["meaning"]["editorial"] and
                     ch["meaning"]["label"] != "조문 내용 변경")
    if labels:
        top = labels.most_common(2)
        short = " · ".join(f"{name} {size}건" for name, size in top)
        return f"{count}개 조문 변경 · {short}"
    if all(ch["meaning"]["editorial"] for ch in changes):
        return f"{count}개 조문 표기·문장부호 정비"
    return f"{count}개 조문 내용 변경"


def highlight_changes(changes: list[dict], limit: int = 3) -> list[dict]:
    """Preview distinct substantive categories before minor formatting edits."""
    ranked = sorted(changes, key=lambda ch: (
        -ch["meaning"]["priority"],
        -len(ch.get("actual_edits") or []),
        ch.get("document_title", ""), ch.get("article", ""),
    ))
    chosen, kinds = [], set()
    for change in ranked:
        if len(chosen) >= limit:
            break
        label = change["meaning"]["label"]
        if label not in kinds and not change["meaning"]["editorial"]:
            chosen.append(change)
            kinds.add(label)
    for change in ranked:
        if len(chosen) >= limit:
            break
        if change not in chosen:
            chosen.append(change)
    return chosen
