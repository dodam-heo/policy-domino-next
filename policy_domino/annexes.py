"""Official law.go.kr PDF annex enrichment with complete source provenance.

Only digital PDF text is supported. Scanned/empty HWP/PDF files remain
explicitly unresolved, never guessed from titles or a language model.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET
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
        if (parsed.scheme not in ("http", "https") or
            parsed.hostname not in ("www.law.go.kr","law.go.kr") or
            parsed.username or parsed.password or
            parsed.path not in ("/LSW/flDownload.do", "/flDownload.do")):
            return ""
        args = urllib.parse.parse_qs(parsed.query)
        seq = args.get("flSeq", [""])[0]
        if not seq.isdecimal() or len(seq)>18:
            return ""
        return "https://www.law.go.kr/LSW/flDownload.do?flSeq="+seq
    except ValueError:
        return ""


def fetch_official_file(href: str, magic: bytes) -> bytes:
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
    if not content.startswith(magic):
        raise ValueError("Official attachment format mismatch")
    return content


def fetch_official_pdf(href: str) -> bytes:
    return fetch_official_file(href, b"%PDF")


def fetch_official_hwpx(href: str) -> bytes:
    return fetch_official_file(href, b"PK")


def extract_hwpx_text(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        sections = [item for item in archive.infolist()
                    if re.fullmatch(r"Contents/section\d+\.xml", item.filename)]
        if not sections or len(sections) > 100 or sum(
                item.file_size for item in sections) > 20_000_000:
            raise ValueError("HWPX section size/count invalid")
        chunks = []
        for item in sorted(sections, key=lambda x: int(re.search(
                r"section(\d+)", x.filename).group(1))):
            root = ET.fromstring(archive.read(item))
            chunks.extend(clean("".join(node.itertext())) for node in root.iter()
                          if tag(node) == "t" and "".join(node.itertext()).strip())
        value = clean(" ".join(chunks))
        if not value or len(value) > MAX_TEXT:
            raise ValueError("HWPX text empty or excessive")
        return value


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
                   max_downloads: int = 4,
                   hwpx_downloader=fetch_official_hwpx,
                   hwpx_extractor=extract_hwpx_text) -> dict:
    """Materialize missing annex bodies from official PDF links; retain audit."""
    result=dict(parsed)
    clauses=dict(result.get("clauses",{}))
    previous_snapshot=normalize_legacy_annex_keys(previous_snapshot or {})
    provenance=(dict(previous_snapshot.get("annex_evidence",{}))
                if previous_snapshot.get("extraction_schema") == 3 else {})
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
    # Notices often embed tables as <img> and attach the whole legal text
    # as a root-level PDF, without any 별표단위 nodes. Pair each sibling link
    # with its actual filename; do not try HWP/HWPX as if they were PDFs.
    root_pdfs = []
    root_hwpx = []
    for parent in root.iter():
        filename = ""
        for child in parent:
            if tag(child) == "첨부파일명":
                filename = clean("".join(child.itertext()))
            elif tag(child) == "첨부파일링크":
                href = clean("".join(child.itertext()))
                if re.search(r"이유서|개정이유|신구.*대비|검토보고", filename):
                    continue  # Supporting explanations are not the legal text.
                if re.search(r"별표|별지|서식|신청서", filename) and "전문" not in filename:
                    continue  # A standalone form is not the whole instrument.
                if filename.lower().endswith(".pdf"):
                    root_pdfs.append(href)
                elif filename.lower().endswith(".hwpx"):
                    root_hwpx.append(href)
    root_pdfs = list(dict.fromkeys(root_pdfs))
    # A single official PDF has an unambiguous whole-document identity.
    # Multiple PDFs require explicit mapping, never arbitrary ordinal pairing.
    if len(root_pdfs) == 1 and len(set(root_hwpx)) != 1:
        label = "첨부 전문"
        approved = authorized_law_pdf_url(root_pdfs[0])
        if not approved:
            failures.append({"annex": label, "reason": "official_pdf_not_available"})
        elif not (label in clauses and clauses[label].get("complete")):
            if processed >= max_downloads:
                failures.append({"annex": label, "reason": "deferred_pdf_budget"})
            else:
                try:
                    blob = downloader(approved)
                    clause = take(pdf_extractor(blob))
                    if not clause["complete"]:
                        raise ValueError("Full-text PDF incomplete")
                    clauses[label] = clause
                    provenance[label] = {
                        "source": "law_go_kr_official_pdf", "url": approved,
                        "scope": "whole_instrument",
                        "pdf_sha256": hashlib.sha256(blob).hexdigest(),
                        "text_sha256": clause["sha256"],
                    }
                    processed += 1
                except Exception as exc:
                    failures.append({"annex": label, "reason": type(exc).__name__})
    elif len(root_pdfs) > 1:
        failures.append({"annex": "첨부 전문", "reason": "ambiguous_multiple_pdfs"})
    if len(set(root_hwpx)) == 1:
        label = "첨부 전문"
        approved = authorized_law_pdf_url(root_hwpx[0])
        if not approved:
            failures.append({"annex": label, "reason": "official_hwpx_not_available"})
        elif not (label in clauses and clauses[label].get("complete")):
            if processed >= max_downloads:
                failures.append({"annex": label, "reason": "deferred_hwpx_budget"})
            else:
                try:
                    blob = hwpx_downloader(approved)
                    clause = take(hwpx_extractor(blob))
                    if not clause["complete"]:
                        raise ValueError("Full-text HWPX incomplete")
                    clauses[label] = clause
                    provenance[label] = {
                        "source": "law_go_kr_official_hwpx", "url": approved,
                        "scope": "whole_instrument",
                        "file_sha256": hashlib.sha256(blob).hexdigest(),
                        "text_sha256": clause["sha256"],
                    }
                    processed += 1
                except Exception as exc:
                    failures.append({"annex": label, "reason": type(exc).__name__})
    if "첨부 전문" in provenance:
        # The complete attachment supersedes flat XML with omitted images.
        # Avoid a second, misleading comparison of the same incomplete body.
        if provenance["첨부 전문"].get("scope") == "whole_instrument":
            clauses = {"첨부 전문": clauses["첨부 전문"]}
        else:
            clauses.pop("본문", None)
    if result.get("image_placeholder_count") and "첨부 전문" not in provenance:
        failures.append({"annex": "본문 표", "reason": "image_table_unresolved"})
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
