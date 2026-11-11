"""Trace issuing body, changed instrument and actual delegation citations."""
import re
REFERENCES=re.compile(r"[「｢]([^」｣]{3,120})[」｣]\s*(제\s*\d+\s*조(?:의\s*\d+)?(?:제\s*\d+\s*항)?)?")
DELEGATION=re.compile(r"규정에\s*따라|에\s*따라|근거하여|위임|정하는\s*바에\s*따라")

def origin_of(doc, snapshot):
    obj={"issuer":doc.get("ministry",""),"instrument":doc.get("title",""),
         "instrument_type":doc.get("law_type") or doc.get("kind",""),
         "number":doc.get("number",""),"url":doc.get("url",""),
         "upper_bases":[]}
    seen=set()
    for location,record in (snapshot or {}).get("clauses",{}).items():
        body=record.get("text","") if isinstance(record,dict) else str(record)
        for match in REFERENCES.finditer(body):
            title=" ".join(match.group(1).split())
            if title==obj["instrument"] or not re.search(r"법|령|조례|규칙",title):continue
            if not DELEGATION.search(body[match.end():match.end()+70]):continue
            article=re.sub(r"\s+","",match.group(2) or "")
            if (title,article) in seen:continue
            seen.add((title,article))
            obj["upper_bases"].append({"title":title,"article":article,
                "location":location,"quote":body[max(0,match.start()-15):match.end()+70],
                "source_url":obj["url"],"relationship":"direct_source_delegation_citation"})
            if len(obj["upper_bases"])>=8:return obj
    return obj
