"""Source-grounded legal hierarchy, distinct from verified institutional duties.

This module DOES NOT assume that a parent amendment automatically changes
every subordinate rule. It records explicit cited legal dependencies and
provides candidate review paths with transparent evidence and uncertainty.
"""
from __future__ import annotations

import re
from collections import defaultdict, deque

from .analysis import extract_references

# Words are legal relationship markers, never registered agency names.
DELEGATION = re.compile(r"위임(?:한|된|받은|하는)?\s*사항|위임에\s*따라|위임을\s*받|위임받|그\s*시행에\s*필요한\s*사항")
PURPOSE = re.compile(r"목적|규정함을|정함을")
MAX_PATH_DEPTH = 3


def delegation_evidence(body: str, cited_title: str, quote: str) -> bool:
    """Recognize a real delegation expression nearby a quoted regulation.

    A whole document containing '위임' somewhere is NOT enough. It must
    occur in the same quoted citation span or shortly following the title.
    """
    key = "「" + cited_title + "」"
    at = body.find(key)
    if at < 0:
        return False
    window = body[max(0, at - 65):min(len(body), at + len(key) + 115)]
    return bool(DELEGATION.search(window))


def legal_reference_matches(package: dict, changed_title: str) -> list[dict]:
    """Return typed references from complete official clauses only."""
    results=[]
    for article, clause in package.get("clauses", {}).items():
        if not clause.get("complete"):
            continue
        body=clause.get("text","")
        for ref in extract_references(body):
            if ref["title"]!=changed_title:
                continue
            delegated=delegation_evidence(body,changed_title,ref["quote"])
            results.append({
                "citing_article":article,
                "referenced_article":ref["article"],
                "quote":ref["quote"],
                "relation":"explicit_legal_delegation" if delegated
                           else ("exact_article_reference" if ref["article"]
                                 else "title_only_reference"),
                "delegation_explicit":delegated,
            })
    return results


def build_legal_dependencies(documents: dict, versions: dict,
                             max_edges: int=7000) -> list[dict]:
    """Discover all source-authored parent-title -> subordinate-document edges.

    Publishing ministry is metadata, NOT evidence that the ministry must take
    an action. The exact citation and the source document remain attached.
    """
    known_titles={doc.get("title") for doc in documents.values()
                  if doc.get("title")}
    seen=set()
    output=[]
    for child_id, package in versions.items():
        child=documents.get(child_id)
        if not child:
            continue
        for article, clause in package.get("clauses",{}).items():
            if not clause.get("complete"):
                continue
            text=clause.get("text","")
            for ref in extract_references(text):
                parent=ref["title"]
                if parent not in known_titles or parent==child.get("title"):
                    continue
                delegated=delegation_evidence(text,parent,ref["quote"])
                relation=("explicit_legal_delegation" if delegated else
                          "exact_article_reference" if ref["article"] else
                          "title_only_reference")
                key=(parent,child_id,article,ref["article"])
                if key in seen:
                    continue
                seen.add(key)
                output.append({
                    "parent_title":parent,
                    "child_document_id":child_id,
                    "child_title":child["title"],
                    "child_published_at":child.get("published_at",""),
                    "child_source":child.get("source",""),
                    "citing_article":article,
                    "referenced_article":ref["article"],
                    "evidence_quote":ref["quote"],
                    "source_url":child.get("url",""),
                    "issuing_agency":child.get("ministry",""),
                    "relation":relation,
                    "delegation_explicit":delegated,
                    "operational_application_verified":False,
                })
                if len(output)>=max_edges:
                    return output
    return output


def cascade_review_paths(findings: dict, documents: dict,
                         dependencies: list[dict], max_depth: int=MAX_PATH_DEPTH,
                         max_paths: int=1500) -> list[dict]:
    """Create candidate paths, never a claim that lower rules MUST be amended.

    An exact citation to a changed article proves direct use. General
    title-reference/delegation proves relationship only, not that this
    specific changed article affects its child.
    """
    index=defaultdict(list)
    for edge in dependencies:
        index[edge["parent_title"]].append(edge)
    results=[]
    for event_id, finding in findings.items():
        root=documents.get(event_id)
        if not root or not finding.get("changes"):
            continue
        changed_articles={x.get("article") for x in finding["changes"]}
        q=deque([(root["title"],[],frozenset([root["title"]]))])
        while q and len(results)<max_paths:
            title,path,visited=q.popleft()
            if len(path)>=max_depth:
                continue
            for edge in index.get(title,()):
                child_title=edge["child_title"]
                if child_title in visited:
                    continue
                direct=(not path and edge["referenced_article"] in changed_articles
                        and bool(edge["referenced_article"]))
                # At depth 1, title-only citation with no delegation is merely
                # a mention; do not overstate it as an institutional cascade.
                if not direct and not edge["delegation_explicit"]:
                    continue
                step={**edge,
                      "change_article_directly_cited":direct,
                      "impact_verified":False}
                steps=path+[step]
                results.append({
                    "source_event_id":event_id,
                    "root_title":root["title"],
                    "depth":len(steps),
                    "path":steps,
                    "destination_title":child_title,
                    "destination_source_url":edge["source_url"],
                    "destination_issuing_agency":edge["issuing_agency"],
                    "verification":("changed_article_directly_cited"
                                    if direct and len(steps)==1 else
                                    "explicit_delegation_review_path"),
                    "actual_duty_change_verified":False,
                    "internal_implementation_verified":False,
                })
                if len(results)>=max_paths:
                    break
                q.append((child_title,steps,visited|{child_title}))
    return results
