"""Incremental official ALIOPLUS institution register; NOT impact proof.

This is a factual institution index. Actual policy impacts still require
article-by-article and operational-source evidence.
"""
from __future__ import annotations
import json
import re
from urllib.request import Request,urlopen

ROOT="https://www.alioplus.go.kr"
LIST_URL=ROOT+"/organization/organByTypeList.do?schApbaGb=APBA&pageNo=1"
DATA_URL=ROOT+"/comm/searchApbaList.do"

def parse_registry(payload:dict,reported:int|None) -> dict:
    rows=payload.get("apbaList")
    if not isinstance(rows,list) or not rows:
        raise ValueError("Official institution list missing")
    found={}
    for row in rows:
        code=str(row.get("apbaId","")).strip()
        name=str(row.get("apbaNa","")).strip()
        if not re.fullmatch(r"C\d+",code) or not name or code in found:
            raise ValueError("Invalid or duplicated official institution")
        found[code]={
            "id":code,"agency":name,"type_code":str(row.get("apbaType","")).strip(),
            "source":"alioplus_institution_directory",
            "source_url":DATA_URL,
            "url":ROOT+"/organization/organHeadDetail.do?apbaId="+code
        }
    if reported is None or len(found)!=reported:
        raise ValueError("Official institution count not reconciled")
    return found

def collect_institutions(state:dict,transport=None)->dict:
    def read(url,post=False):
        if transport:
            return transport(url,post)
        req=Request(url,data=b"" if post else None,
                    headers={"User-Agent":"PolicyDominoNext/1.0",
                             "Referer":LIST_URL,
                             "Content-Type":"application/x-www-form-urlencoded"})
        with urlopen(req,timeout=18) as response:
            if not response.geturl().startswith(ROOT+"/"):
                raise ValueError("Untrusted institution directory redirect")
            raw=response.read(2_000_001)
            if len(raw)>2_000_000:raise ValueError("Institution list too large")
            return raw
    try:
        html=read(LIST_URL).decode("utf-8","replace")
        match=re.search(r'<div\s+class="total">\s*총\s*<strong>([\d,]+)',html)
        count=int(match.group(1).replace(",","")) if match else None
        payload=json.loads(read(DATA_URL,True))
        validated=parse_registry(payload,count)
        state["official_institutions"]=validated
        report={"source":"alioplus","status":"collected","count":len(validated),
                "scope":"central public institution headquarters; local public enterprises need separate evidence"}
    except (OSError,ValueError,UnicodeError,TypeError) as exc:
        report={"source":"alioplus","status":"refresh_failed",
                "count":len(state.get("official_institutions",{})),
                "error":type(exc).__name__+":"+str(exc)[:120]}
    state["official_institution_audit"]=report
    return report


# 지방공사·공단은 중앙 ALIO 명부에 포함되지 않는다.
# 지방공기업의 공식 원천은 행정안전부 클린아이 설립현황이다.
CLEANEYE_URL="https://www.cleaneye.go.kr/siteGuide/pubCompStatus.do"

class _InstitutionTable(__import__("html.parser",fromlist=["HTMLParser"]).HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows=[]
        self.row=None
        self.cell=None
        self.collect=False
    def handle_starttag(self,tag,attrs):
        if tag=="tr":
            self.row=[]
        elif tag in ("td","th") and self.row is not None:
            self.cell=[]
        elif tag=="br" and self.cell is not None:
            self.cell.append(", ")
    def handle_data(self,data):
        if self.cell is not None:
            self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ("td","th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell=None
        elif tag=="tr" and self.row is not None:
            if self.row:self.rows.append(self.row)
            self.row=None

def parse_local_registry(html:str) -> dict:
    """Parse publisher-labelled 기관명 columns; never infer an institution from a keyword."""
    import hashlib
    parser=_InstitutionTable()
    parser.feed(html)
    valid_header=any("기관명" in " ".join(r) for r in parser.rows)
    if not valid_header:
        raise ValueError("Official CleanEye institution column absent")
    found={}
    for row in parser.rows:
        if not row or "기관명" in row[-1] or len(row[-1])<5:
            continue
        # Only institution-name cells in the official establishment table,
        # never the region, count, class, or unverified footer narrative.
        names=re.split(r"[,，、]|(?:\s{2,})",row[-1])
        for item in names:
            name=" ".join(item.split()).strip()
            if not (5<=len(name)<=100 and
                    re.search(r"공사|공단|상수도|하수도|공영개발|사업소|교통공사",name)):
                continue
            if any(word in name for word in ("총계","소계","기관명","유형","분류")):
                continue
            code=hashlib.sha256(name.encode("utf8")).hexdigest()[:18]
            found[code]={"id":code,"agency":name,"source":"cleaneye_establishment",
                         "source_url":CLEANEYE_URL}
    if len(found)<30:
        raise ValueError("Official CleanEye rows too few to trust")
    # The same official establishment page publishes explicit historical
    # institution renames (e.g. a list may still show a former title).
    # Apply only a literal old > new pair issued on the original source.
    from html import unescape
    visible=unescape(re.sub(r"<[^>]+>"," ",html))
    rename=re.search(r"명칭변경\s*[:：]\s*([^\n●○]{1,340})",visible)
    if rename:
        for row in rename.group(1).split(","):
            if ">" not in row:
                continue
            old_name,new_name=(part.strip() for part in row.split(">",1))
            if (not old_name or not new_name or
                    not re.search(r"공사|공단",new_name)):
                continue
            for record in found.values():
                if record["agency"]==old_name:
                    record["agency"]=new_name
                    record["former_names"]=[old_name]
                    record["rename_source_url"]=CLEANEYE_URL
    return found

def collect_local_institutions(state:dict, transport=None)->dict:
    try:
        if transport:
            raw=transport(CLEANEYE_URL)
        else:
            request=Request(CLEANEYE_URL,headers={
                "User-Agent":"PolicyDominoNext/1.0"})
            with urlopen(request,timeout=18) as response:
                if not response.geturl().startswith(
                        "https://www.cleaneye.go.kr/siteGuide/"):
                    raise ValueError("Untrusted CleanEye redirect")
                raw=response.read(3_000_001)
        if len(raw)>3_000_000:raise ValueError("CleanEye page too large")
        parsed=parse_local_registry(raw.decode("utf8","replace"))
        state["official_local_institutions"]=parsed
        audit={"source":"cleaneye","status":"collected",
               "count":len(parsed),"coverage":"extracted establishment table; not verified exhaustive"}
    except (OSError,ValueError,TypeError,UnicodeError) as exc:
        audit={"source":"cleaneye","status":"refresh_failed",
               "count":len(state.get("official_local_institutions",{})),
               "error":type(exc).__name__+":"+str(exc)[:120]}
    state["official_local_audit"]=audit
    return audit


def institution_from_ordinance(document:dict)->dict|None:
    """Register a public corporation only if an official local ordinance is
    explicitly named for the establishment and operation of that corporation.
    A directory entry is NOT proof of an impact from another policy.
    """
    if document.get("source")!="ordin":
        return None
    title=" ".join(str(document.get("title","")).split())
    suffix=" 설립 및 운영에 관한 조례"
    if not title.endswith(suffix):
        return None
    name=title[:-len(suffix)].strip()
    issuer=" ".join(str(document.get("ministry","")).split())
    if issuer and name.startswith(issuer+" "):
        name=name[len(issuer):].strip()
    # Match an actual organization noun, not an individual official or a topic.
    if not (re.fullmatch(r"[가-힣A-Za-z0-9·()\\s]{4,110}(?:공사|공단)",name)
            and document.get("url")):
        return None
    return {"agency":name,"source":"official_institution_founding_ordinance",
            "source_url":document["url"],"issuer":issuer}
