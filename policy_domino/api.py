"""Official Law Information API client; no third-party search or seed catalogue."""
from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Callable

from .core import SOURCE_CONFIG, SOURCES, clean, date_string, document_key, official_url

API = "https://www.law.go.kr/DRF/"
MAX_BYTES = 16_000_000
ROW_FIELDS = ("법령일련번호", "행정규칙일련번호", "자치법규일련번호")


def tag(node: ET.Element) -> str:
    return node.tag.split("}")[-1]


def field(node: ET.Element, name: str, direct: bool = False) -> str:
    elements = list(node) if direct else node.iter()
    child = next((x for x in elements if tag(x) == name), None)
    return clean("".join(child.itertext())) if child is not None else ""


def nodes(root: ET.Element, source: str) -> list[ET.Element]:
    cfg = SOURCE_CONFIG[source]
    required = {cfg["title"], cfg["serial"]}
    out = []
    for node in root.iter():
        if node is root:
            continue
        children = {tag(child) for child in node}
        if required <= children:
            out.append(node)
    return out


def parse_record(node: ET.Element, source: str) -> dict | None:
    cfg = SOURCE_CONFIG[source]
    title = field(node, cfg["title"], True)
    stable = field(node, cfg["stable"], True)
    serial = field(node, cfg["serial"], True)
    issued = date_string(field(node, cfg["date"], True))
    if source == "admrul" and not issued:
        issued = date_string(field(node, "공포일자", True))
    if not (title and stable and serial and issued):
        return None
    number = field(node, "공포번호", True) or field(node, "발령번호", True)
    revision = field(node, "제개정구분명", True) or field(node, "제개정구분", True)
    ministry = field(node, cfg["ministry"], True)
    law_type = (field(node, "법령구분명", True) or
                field(node, "법령구분", True) or cfg["type"])
    if source == "ordin" and not ministry:
        ministry = field(node, "지자체명", True)
    return {
        "id": document_key(source, stable, serial), "source": source,
        "stable_id": stable, "serial": serial, "title": title,
        "published_at": issued, "effective_date": date_string(field(node, "시행일자", True)),
        "number": number, "revision": revision,
        "ministry": ministry, "kind": cfg["type"], "law_type": law_type,
        "url": official_url(source, title),
    }


class ApiError(RuntimeError):
    pass


@dataclass
class Coverage:
    source: str
    first: str
    last: str
    version: str
    reported: int
    collected: int
    pages: int
    complete: bool
    error: str = ""

    def as_dict(self) -> dict:
        return vars(self).copy()


class LawAPI:
    def __init__(self, credential: str, transport: Callable | None = None):
        if not credential or not credential.strip():
            raise ValueError("LAW_OC is required; never use a built-in credential")
        self.credential = credential.strip()
        self.transport = transport

    def request(self, endpoint: str, target: str, **params) -> ET.Element:
        args = {"OC": self.credential, "target": target, "type": "XML", **params}
        url = API + endpoint + "?" + urllib.parse.urlencode(args)
        if self.transport:
            data = self.transport(url)
        else:
            req = urllib.request.Request(url, headers={
                "User-Agent": "PolicyDominoNext/0.1 (public legal API research)"})
            last = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=25) as response:
                        data = response.read(MAX_BYTES + 1)
                    break
                except (OSError, urllib.error.URLError) as exc:
                    last = exc
                    if attempt < 2:
                        time.sleep(1 + attempt)
            else:
                raise ApiError("Official API transport failure: " + str(last)[:160])
        if len(data) > MAX_BYTES:
            raise ApiError("Official API response exceeded size limit")
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            raise ApiError("Malformed official XML") from exc
        if tag(root).lower() in ("html", "error"):
            raise ApiError("Official API returned an error page")
        return root

    def search_window(self, source: str, first: str, last: str,
                      version: str = "1", max_pages: int = 25) -> tuple[list[dict], Coverage]:
        if source not in SOURCES:
            raise ValueError("Unsupported source")
        key = SOURCE_CONFIG[source]["date_filter"]
        seen: dict[str, dict] = {}
        reported: int | None = None
        pages = 0
        error = ""
        for page in range(1, max_pages + 1):
            try:
                params = {
                    key: first.replace("-", "") + "~" + last.replace("-", ""),
                    "page": page, "display": 100, "sort": "ddes",
                }
                if source != "law":
                    params["nw"] = version
                root = self.request("lawSearch.do", source, **params)
                count_text = field(root, "totalCnt")
                if not count_text.isdigit():
                    raise ApiError("Missing official totalCnt")
                count = int(count_text)
                if reported is not None and count != reported:
                    raise ApiError("Official totalCnt changed during pagination")
                reported = count
                matches = nodes(root, source)
                if count and not matches:
                    raise ApiError("Official result has rows but parser found none")
                for node in matches:
                    rec = parse_record(node, source)
                    if rec and first <= rec["published_at"] <= last:
                        seen[rec["id"]] = rec
                pages = page
                if count == 0 or page * 100 >= count or len(matches) < 100:
                    complete = len(seen) == count
                    msg = "" if complete else "Records differ from official totalCnt"
                    return list(seen.values()), Coverage(
                        source, first, last, version, count, len(seen), pages, complete, msg)
            except Exception as exc:
                error = type(exc).__name__ + ": " + str(exc)[:170]
                break
        return list(seen.values()), Coverage(
            source, first, last, version, reported if reported is not None else -1,
            len(seen), pages, False, error or "Official pagination limit reached")

    def detail(self, record: dict) -> ET.Element:
        source = record["source"]
        param = SOURCE_CONFIG[source]["detail_key"]
        return self.request("lawService.do", source, **{param: record["serial"]})

    def history(self, record: dict) -> list[dict]:
        source = record["source"]
        if source == "law":
            root = self.request("lawSearch.do", "eflaw",
                                LID=record["stable_id"], nw="1,2,3",
                                display=100, page=1, sort="ddes")
            entries = nodes(root, "law")
        else:
            root = self.request("lawSearch.do", source, query=record["title"],
                                nw="2", display=100, page=1, sort="ddes")
            entries = nodes(root, source)
        rows = [parse_record(x, source) for x in entries]
        return sorted((x for x in rows if x and
                       x["stable_id"] == record["stable_id"] and
                       x["serial"] != record["serial"] and
                       x["published_at"] <= record["published_at"]),
                      key=lambda x: (x["published_at"], x["serial"]), reverse=True)
