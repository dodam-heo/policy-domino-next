"""Conservative ALIOPLUS public-program discovery adapter (stdlib only).

ALIOPLUS is an official public-institution programme directory, not a
complete register of central/local government programs. No result is counted
as coverage merely because an HTML page was downloaded.
"""
from __future__ import annotations

import html
import re
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlencode, urlparse

from .programs import canonical_url, ingest_programs

ORIGIN = "https://www.alioplus.go.kr"
INDEX = ORIGIN + "/business/bsnByLifeList.do"
DETAIL = ORIGIN + "/business/bsnDetail.do"
MAX_BYTES = 1_500_000
FIELDS = ("기관명", "사업소개", "사업 기간", "사업기간", "이용대상",
          "이용방법", "이용문의")


class ProgramSourceError(RuntimeError):
    pass


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skipped = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skipped += 1
        if not self.skipped and tag in ("h1", "h2", "h3", "h4", "li", "p",
                                        "div", "dt", "dd", "tr", "br"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skipped = max(0, self.skipped - 1)
        if not self.skipped and tag in ("h1", "h2", "h3", "h4", "li", "p",
                                        "div", "dt", "dd", "tr"):
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.skipped:
            self.parts.append(value)

    def lines(self):
        return [x.strip() for x in re.split(r"[\r\n]+", "".join(self.parts))
                if x.strip()]


def parse_detail(content: str, url: str) -> dict:
    """Extract field-labelled official business pages, not free-form guesses."""
    canonical = canonical_url(url)
    if not canonical:
        raise ProgramSourceError("Untrusted business detail URL")
    parser = _VisibleText()
    parser.feed(content)
    lines = parser.lines()

    def label_index(label):
        return next((i for i, text in enumerate(lines) if text == label), None)

    agency_pos = label_index("기관명")
    intro_pos = label_index("사업소개")
    if (agency_pos is None or intro_pos is None or
        not agency_pos < intro_pos or intro_pos + 1 >= len(lines)):
        raise ProgramSourceError("Official business fields not found")
    next_agency = lines[agency_pos + 1:intro_pos]
    if len(next_agency) != 1:
        raise ProgramSourceError("Ambiguous issuing institution")

    next_field = next((i for i in range(intro_pos + 1, len(lines))
                       if lines[i] in FIELDS), len(lines))
    summary = " ".join(lines[intro_pos + 1:next_field]).strip()
    if not summary:
        raise ProgramSourceError("Empty official business description")

    title = ""
    for line in reversed(lines[max(0, agency_pos - 12):agency_pos]):
        candidate = line.split(">")[-1].strip()
        if (3 <= len(candidate) <= 240 and
            candidate not in ("사업정보", "사업분야별", "생애주기별",
                              "상세정보", "HOME", "공공기관 알리오플러스")):
            title = candidate
            break
    if not title:
        raise ProgramSourceError("Official business name not found")
    return {"name": title, "agency": next_agency[0],
            "description": summary, "url": canonical}


def listing_detail_urls(content: str) -> list[str]:
    """Take IDs only from explicit programme-detail links/attributes.

    Pagination numbers and unrelated article IDs can never become program IDs.
    """
    plain = html.unescape(content)
    found = []
    seen = set()
    patterns = (
        r"bsnDetail\.do[^\"'<>]*?bsnSeq=(\d{1,12})",
        r"(?:data-bsn-seq|data-bsnseq)\s*=\s*[\"'](\d{1,12})[\"']",
        r"bsnSeq\s*[:=]\s*[\"']?(\d{1,12})",
        r"fnDetail\s*\(\s*[\"']?(\d{1,12})[\"']?\s*,\s*[\"']?(?:DET|SCT)[\"']?",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, plain, re.IGNORECASE):
            value = match.group(1)
            if value in seen:
                continue
            seen.add(value)
            found.append(canonical_url(DETAIL + "?" + urlencode({
                "bsnSeq": value, "bsnTyp": "DET"})))
    return [x for x in found if x]


class _ListingTitles(HTMLParser):
    """Associate list display names only with their explicit official detail URL."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.names = {}
        self.url = ""
        self.title_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "a":
            href = props.get("href", "") + " " + props.get("onclick", "")
            matched = re.search(
                r"fnDetail\s*\(\s*[\x22\x27]?(\d{1,12})[\x22\x27]?\s*,"
                r"\s*[\x22\x27]?(?:DET|SCT)[\x22\x27]?", href, re.IGNORECASE)
            self.url = (canonical_url(DETAIL + "?bsnSeq=" + matched.group(1) +
                                      "&bsnTyp=DET") if matched else "")
            self.parts = []
        elif tag == "div" and self.url and "tit" in props.get("class", "").split():
            self.title_depth = 1
        elif self.title_depth:
            self.title_depth += 1

    def handle_endtag(self, tag):
        if tag == "a":
            title = " ".join(self.parts).strip()
            if self.url and 3 <= len(title) <= 240:
                self.names[self.url] = title
            self.url = ""
            self.parts = []
            self.title_depth = 0
        elif self.title_depth:
            self.title_depth -= 1

    def handle_data(self, data):
        if self.title_depth and self.url:
            self.parts.append(data.strip())


def listing_business_titles(content: str) -> dict[str, str]:
    parser = _ListingTitles()
    parser.feed(content)
    return parser.names


class ALIOPlusClient:
    """Bounded, auditable public portal connector; no credential required."""

    def __init__(self, transport=None, delay_seconds: float = 0.2):
        self.transport = transport
        self.delay_seconds = delay_seconds

    def fetch(self, url: str) -> str:
        p = urlparse(url)
        if (p.scheme != "https" or p.hostname != "www.alioplus.go.kr" or
            p.path not in ("/business/bsnByLifeList.do", "/business/bsnDetail.do")):
            raise ProgramSourceError("Unapproved official portal endpoint")
        if self.transport:
            return self.transport(url)
        request = urllib.request.Request(url, headers={
            "User-Agent": "PolicyDominoNext/0.2 (bounded public program research)"})
        with urllib.request.urlopen(request, timeout=12) as response:
            if (urlparse(response.geturl()).hostname != "www.alioplus.go.kr" or
                urlparse(response.geturl()).scheme != "https"):
                raise ProgramSourceError("Unapproved portal redirect")
            raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ProgramSourceError("Official program response too large")
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                return raw.decode(charset, errors="replace")
            except LookupError as exc:
                raise ProgramSourceError("Unknown official portal charset") from exc

    def collect(self, state: dict, max_details: int = 6) -> dict:
        """Fetch one index page, then explicitly linked official detail records."""
        audit = {"source": "alioplus", "pages_attempted": 1, "ids_discovered": 0,
                 "pages_checked": 0, "accepted": 0, "rejected": 0,
                 "complete": False, "error": ""}
        try:
            raw = self.fetch(INDEX)
            urls = listing_detail_urls(raw)
            display_names = listing_business_titles(raw)
            audit["ids_discovered"] = len(urls)
            if not urls:
                raise ProgramSourceError(
                    "Program IDs not exposed in known listing markup; no results certified")
            already = {p["url"] for p in state.get("official_programs", {}).values()
                       if isinstance(p, dict) and p.get("url")}
            todo = [url for url in urls if url not in already]
            if not todo:
                audit["error"] = "No new program IDs on the current index page"
                return audit
            records = []
            for url in todo[:max(0, min(max_details, 15))]:
                try:
                    body = self.fetch(url)
                    record = parse_detail(body, url)
                    # The list's labelled title excludes category prefixes
                    # which can be concatenated in the detail-page heading.
                    if url in display_names:
                        record["name"] = display_names[url]
                    records.append(record)
                except (ProgramSourceError, OSError, ValueError) as exc:
                    audit["rejected"] += 1
                    audit.setdefault("reasons", []).append(type(exc).__name__ + ": " +
                                                           str(exc)[:100])
                audit["pages_checked"] += 1
                if self.delay_seconds:
                    time.sleep(self.delay_seconds)
            result = ingest_programs(state, records)
            audit["accepted"] = result["accepted"]
            audit["rejected"] += result["rejected"]
            if result["reasons"]:
                audit.setdefault("reasons", []).extend(result["reasons"])
            # One listing page is NOT national coverage or even portal coverage.
            audit["complete"] = False
            audit["error"] = audit["error"] or "Bounded sample; portal pagination unchecked"
        except (ProgramSourceError, OSError, ValueError) as exc:
            audit["error"] = type(exc).__name__ + ": " + str(exc)[:160]
        return audit
