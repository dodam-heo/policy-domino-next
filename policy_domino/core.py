"""One public contract for every official source and pipeline stage."""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import quote

SCHEMA = "policy-domino-next-v1"
SOURCES = ("law", "admrul", "ordin")
SOURCE_CONFIG = {
    "law": {
        "title": "법령명한글", "stable": "법령ID", "serial": "법령일련번호",
        "date": "공포일자", "date_filter": "ancYd", "detail_key": "MST",
        "type": "법령", "ministry": "소관부처명", "history_target": "eflaw",
    },
    "admrul": {
        "title": "행정규칙명", "stable": "행정규칙ID", "serial": "행정규칙일련번호",
        "date": "발령일자", "date_filter": "prmlYd", "detail_key": "ID",
        "type": "행정규칙", "ministry": "소관부처명", "history_target": "admrul",
    },
    "ordin": {
        "title": "자치법규명", "stable": "자치법규ID", "serial": "자치법규일련번호",
        "date": "공포일자", "date_filter": "ancYd", "detail_key": "MST",
        "type": "자치법규", "ministry": "지자체기관명", "history_target": "ordin",
    },
}


def clean(text: object) -> str:
    value = html.unescape(str(text or ""))
    value = re.sub(r"<[^>]{1,800}>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def date_string(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) != 8:
        return ""
    try:
        return dt.date(int(digits[:4]), int(digits[4:6]), int(digits[6:])).isoformat()
    except ValueError:
        return ""


def document_key(source: str, stable_id: str, serial: str) -> str:
    if source not in SOURCES or not stable_id or not serial:
        raise ValueError("Official source, stable ID and revision serial are mandatory")
    return hashlib.sha256(
        (source + "|" + stable_id + "|" + serial).encode("utf8")
    ).hexdigest()[:24]


def official_url(source: str, title: str) -> str:
    route = {"law": "법령", "admrul": "행정규칙", "ordin": "자치법규"}[source]
    return "https://www.law.go.kr/" + quote(route) + "/" + quote(title)


def new_state() -> dict:
    return {
        "schema": SCHEMA, "documents": {}, "versions": {},
        "findings": {}, "coverage": [], "attempts": {}, "cursor_days": 0,
        "errors": [], "generated_at": "",
    }


def load_state(path: Path) -> dict:
    if not path.exists():
        return new_state()
    value = json.loads(path.read_text(encoding="utf8"))
    if value.get("schema") != SCHEMA:
        raise ValueError("State schema mismatch; migration is required")
    for key, default in new_state().items():
        value.setdefault(key, default)
    return value


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf8")
    temp.replace(path)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
