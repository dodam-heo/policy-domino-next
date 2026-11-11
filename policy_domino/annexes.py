"""Official law.go.kr PDF annex enrichment with complete source provenance.

Only digital PDF text is supported. Scanned/empty HWP/PDF files remain
explicitly unresolved, never guessed from titles or a language model.
"""
from __future__ import annotations

import hashlib
import io
import re
import urllib.parse
import urllib.request

from .api import field, tag
from .core import clean
from .parser import take

MAX_ATTACHMENT_BYTES = 9_000_000
MAX_PAGES = 45
MAX_TEXT = 70_000


def authorized_law_pdf_url(href: str) -> str:
    if not isinstance(href, str) or len(href) > 900:
        return ""
    absolute = urllib.parse.urljoin("https://www.law.go.kr/", href)
    try:
        parsed = urllib.parse.urlparse(absolute)
        if (parsed.scheme != "https" or
            parsed.hostname not in ("www.law.go.kr","law.go.kr") or
            parsed.username or parsed.password or
            parsed.path != "/LSW/flDownload.do"):
            return ""
        args = urllib.parse.parse_qs(parsed.query)
        seq = args.get("flSeq", [""])[0]
        if not seq.isdecimal() or len(seq)>18:
            return ""
        return "https://www.law.go.kr/LSW/flDownload.do?flSeq="+seq
    except ValueError:
        return ""


def fetch_official_pdf(href: str) -> bytes:
    url=authorized_law_pdf_url(href)
    if not url:
        raise ValueError("Only official law.go.kr PDF download URLs are allowed")
    request=urllib.request.Request(url,headers={
        "User-Agent":"PolicyDominoNext/1.0",
        "Accept":"application/pdf"})
    # Disallow redirecting data extraction to any other host.
    class OfficialRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            target=urllib.parse.urlparse(newurl)
            if target.scheme!="https" or target.hostname not in (
                    "law.go.kr","www.law.go.kr"):
                raise ValueError("Non-official PDF redirect")
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    opener=urllib.request.build_opener(OfficialRedirect)
    with opener.open(request,timeout=18) as response:
        content=response.read(MAX_ATTACHMENT_BYTES+1)
    if len(content)>MAX_ATTACHMENT_BYTES:
        raise ValueError("Official PDF exceeds size limit")
    if not content.startswith(b"%PDF"):
        raise ValueError("Official attachment was not a PDF")
    return content


def extract_digital_pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(pdf),strict=False)
    if len(reader.pages)>MAX_PAGES:
        raise ValueError("Official PDF is too large for verified automated extraction")
    chunks=[]
    for page in reader.pages:
        text=clean(page.extract_text(extraction_mode="layout") or "")
        if text:
            chunks.append(text)
        if sum(map(len,chunks)) > MAX_TEXT:
            raise ValueError("Official PDF text exceeds the verified limit")
    result=clean("\n".join(chunks))
    if not result:
        raise ValueError("Official PDF is scanned or contains no extractable text")
    return result


def normalize_legacy_annex_keys(version: dict) -> dict:
    """Migrate old parser keys with annex titles to stable official numbers.

    This does not alter any legal text or invent a comparison. Collisions
    are deliberately left unresolved to prevent merging distinct evidence.
    """
    clauses = version.get("clauses", {})
    updated = {}
    for old_key, entry in clauses.items():
        fixed = re.sub(
            r"^((?:별표|서식) \d+(?:의\d+)?) \([^)]{1,180}\)$",
            r"\1", old_key)
        if fixed in updated and old_key != fixed:
            # Cannot prove which duplicate snapshot is the correct annex.
            fixed = old_key
        updated[fixed] = entry
    normalized = dict(version)
    normalized["clauses"] = updated
    normalized["incomplete_keys"] = [k for k,v in updated.items()
                                     if not v.get("complete",False)]
    normalized["body_sha256"] = (
        hashlib.sha256("|".join(k+v["sha256"] for k,v in
                               sorted(updated.items())).encode("utf-8")).hexdigest()
        if updated else "")
    return normalized


def enrich_annexes(root, parsed: dict, *,
                   downloader=fetch_official_pdf,
                   pdf_extractor=extract_digital_pdf_text,
                   previous_snapshot: dict | None = None,
                   max_downloads: int = 4) -> dict:
    """Materialize missing annex bodies from official PDF links; retain audit."""
    result=dict(parsed)
    clauses=dict(result.get("clauses",{}))
    previous_snapshot=normalize_legacy_annex_keys(previous_snapshot or {})
    provenance=dict(previous_snapshot.get("annex_evidence",{}))
    failures=[]
    processed=0
    for old_label, evidence in provenance.items():
        if old_label not in clauses and old_label in previous_snapshot.get("clauses",{}):
            clauses[old_label]=previous_snapshot["clauses"][old_label]
    for node in root.iter():
        kind=tag(node)
        if kind not in ("별표단위","서식단위"):
            continue
        number=field(node,"별표번호") or field(node,"서식번호")
        branch=field(node,"별표가지번호")
        label=("별표 " if kind=="별표단위" else "서식 ")+(number or "")
        if branch not in ("","0"):
            label+="의"+branch
        links=[
            field(node,"별표서식PDF파일링크"),
            field(node,"별표서식파일링크"),
            field(node,"첨부파일링크"),
        ]
        links=[x for x in links if x]
        if not label.strip() or not links:
            continue
        if label in clauses and clauses[label].get("complete"):
            continue  # Official inline text already exists.
        approved=next((authorized_law_pdf_url(x) for x in links
                       if authorized_law_pdf_url(x)), "")
        if not approved:
            failures.append({"annex":label,"reason":"official_pdf_not_available"})
            continue
        if processed >= max_downloads:
            failures.append({"annex":label,"reason":"deferred_pdf_budget"})
            continue
        try:
            blob=downloader(approved)
            text=pdf_extractor(blob)
            clause=take(text)
            if not clause["complete"]:
                raise ValueError("Annex text incomplete")
            clauses[label]=clause
            provenance[label]={
                "source":"law_go_kr_official_pdf",
                "url":approved,
                "pdf_sha256":hashlib.sha256(blob).hexdigest(),
                "text_sha256":clause["sha256"],
            }
            processed+=1
        except Exception as exc:
            failures.append({"annex":label,"reason":type(exc).__name__})
    result["clauses"]=clauses
    result["annex_evidence"]=provenance
    result["unresolved_annexes"]=failures
    result["annexes_extracted"]=processed
    result["incomplete_keys"]=[k for k,v in clauses.items()
                               if not v.get("complete")]
    if not clauses:
        result["status"]="attachment_only" if failures else result.get("status","body_missing")
    elif result["incomplete_keys"] or failures:
        result["status"]="partial"
    else:
        result["status"]="extracted"
    result["body_sha256"]=(
        hashlib.sha256("|".join(
            k+v["sha256"] for k,v in sorted(clauses.items())
        ).encode("utf-8")).hexdigest() if clauses else "")
    return result
