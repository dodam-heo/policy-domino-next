"""Conservative law/admrul/ordin XML body parser with explicit completeness."""
from __future__ import annotations

import hashlib
import re
from defusedxml import ElementTree as ET
from .api import field, tag
from .core import clean
from .meaning import is_placeholder_clause

CLAUSE_LIMIT = 15000
BODY_TAGS = {"조문내용", "조내용", "항내용", "호내용", "목내용"}
ANNEX_TAGS = {"별표내용", "서식내용", "본문내용"}
LINK_TAGS = {"별표서식파일링크", "별표서식PDF파일링크",
             "첨부파일링크", "첨부파일명", "별표파일링크"}
HEADING = re.compile(r"(?<![가-힣0-9])제\s*(\d+)\s*조(?:의\s*(\d+))?\s*\([^)]{1,75}\)")


def text(node: ET.Element) -> str:
    return clean("".join(node.itertext()))


def take(value: str) -> dict:
    return {"text": value[:CLAUSE_LIMIT],
            "complete": len(value) < CLAUSE_LIMIT and
                        not is_placeholder_clause(value),
            "sha256": hashlib.sha256(value.encode("utf8")).hexdigest()}


def parse_document(root: ET.Element) -> dict:
    out: dict[str, dict] = {}
    attachment_links = 0
    pending_annex_links = []
    for el in root.iter():
        name = tag(el)
        if name in LINK_TAGS and text(el):
            attachment_links += 1
            if name in ("별표서식PDF파일링크","별표서식파일링크",
                        "첨부파일링크","별표파일링크"):
                pending_annex_links.append({
                    "tag":name,"href":text(el)[:750]})
        if name == "조문단위":
            number = field(el, "조문번호")
            branch = field(el, "조문가지번호")
            if not number:
                continue
            key = "제" + number + "조" + ("의" + branch if branch not in ("", "0") else "")
            pieces = []
            for item in el.iter():
                if tag(item) not in BODY_TAGS:
                    continue
                # Embedded XML can contain a nested 항/호: do not copy parent
                # and all descendants twice.
                contains_nested = any(tag(x) in BODY_TAGS for x in item if x is not item)
                value = clean(item.text) if contains_nested else text(item)
                if value and value not in pieces:
                    pieces.append(value)
            if pieces:
                out[key] = take(" ".join(pieces))
        if name in ("조항", "자치법규조문"):
            direct = {tag(x): x for x in el}
            if "조문번호" in direct and "조내용" in direct:
                number = text(direct["조문번호"])
                is_article = text(direct["조문여부"]) if "조문여부" in direct else "Y"
                value = text(direct["조내용"])
                if number and value and is_article.upper() != "N":
                    key = "제" + number + "조"
                    title = text(direct["조제목"]) if "조제목" in direct else ""
                    if title and not value.startswith(key):
                        value = key + "(" + title + ") " + value
                    out[key] = take(value)
        if name in ("별표단위", "서식단위"):
            number = field(el, "별표번호") or field(el, "서식번호")
            branch = field(el, "별표가지번호")
            title = field(el, "별표제목") or field(el, "서식제목")
            value = field(el, "별표내용") or field(el, "서식내용") or field(el, "본문내용")
            if value:
                label = ("별표 " if name == "별표단위" else "서식 ") + (number or str(len(out) + 1))
                if branch not in ("", "0"):
                    label += "의" + branch
                # Stable annex identity is its official number, not title.
                # Annual or amended table titles frequently change, while the
                # same annex number remains the comparable legal location.
                out[label] = take(value)
        if name in ("부칙", "부칙단위"):
            if name == "부칙" and any(tag(x) == "부칙단위" for x in el):
                continue
            value = field(el, "부칙내용")
            if value:
                number = field(el, "부칙공포번호")
                date = field(el, "부칙공포일자")
                label = "부칙" + (" " + number if number else "") + (" " + date if date else "")
                if label in out:
                    label += " " + str(len(out))
                out[label] = take(value)
    if not any(k.startswith("제") or k == "본문" for k in out):
        # Supplements and annexes do not replace an unnumbered rule body.
        # Flat administrative rules sometimes have only body-level text.
        flat = []
        for node in root.iter():
            if tag(node) not in ("조문내용", "조내용", "본문내용", "행정규칙본문", "행정규칙내용"):
                continue
            # Only leaf body elements; ignore wrapping element duplication.
            if any(tag(child) in BODY_TAGS for child in node):
                continue
            val = text(node)
            if val and val not in flat:
                flat.append(val)
        entire = clean(" ".join(flat))
        if entire:
            matches = list(HEADING.finditer(entire))
            if matches:
                for i, match in enumerate(matches):
                    stop = matches[i + 1].start() if i + 1 < len(matches) else len(entire)
                    key = "제" + match.group(1) + "조"
                    if match.group(2):
                        key += "의" + match.group(2)
                    out[key] = take(entire[match.start():stop])
            else:
                out["본문"] = take(entire)
    image_count = sum(len(re.findall(r"<img\b", node.text or "", re.I))
                      for node in root.iter())
    incomplete = [k for k, v in out.items() if not v["complete"]]
    if not out:
        status = "attachment_only" if attachment_links else "body_missing"
    elif incomplete or attachment_links or image_count:
        status = "partial"
    else:
        status = "extracted"
    return {
        "image_placeholder_count": image_count,
        "extraction_schema": 3,
        "status": status, "clauses": out,
        "incomplete_keys": incomplete, "attachment_link_count": attachment_links,
        "attachment_links":pending_annex_links,
        "body_sha256": hashlib.sha256(
            "|".join(k + v["sha256"] for k, v in sorted(out.items()))
            .encode("utf8")).hexdigest() if out else "",
    }
