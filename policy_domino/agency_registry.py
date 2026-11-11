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
