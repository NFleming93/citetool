"""First-pass metadata resolution.

Two sources, no local translation server to bundle:
  1. Citoid — Wikimedia's public service that runs Zotero's actual
     translator library server-side and returns Zotero-shaped items.
  2. CrossRef — authoritative for anything with a DOI.

Any failure here simply means the Claude verification layer works from
the page content alone, which it does for every link regardless.
"""

from __future__ import annotations

import re
import urllib.parse

import requests

from .fetch import USER_AGENT

CITOID = "https://en.wikipedia.org/api/rest_v1/data/citation/zotero/{}"
CROSSREF = "https://api.crossref.org/works/{}"
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>#?]+)", re.IGNORECASE)

_CROSSREF_TYPES = {
    "journal-article": "journalArticle",
    "proceedings-article": "conferencePaper",
    "book": "book", "monograph": "book", "edited-book": "book",
    "book-chapter": "bookSection",
    "report": "report", "report-component": "report",
    "dissertation": "thesis",
    "dataset": "dataset",
    "posted-content": "preprint",
}


def extract_doi(url: str) -> str | None:
    m = _DOI_RE.search(urllib.parse.unquote(url))
    return m.group(1).rstrip(".,;)") if m else None


def _citoid(url: str, timeout: int = 25) -> dict | None:
    endpoint = CITOID.format(urllib.parse.quote(url, safe=""))
    r = requests.get(endpoint, timeout=timeout,
                     headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    if r.status_code != 200:
        return None
    data = r.json()
    if isinstance(data, list) and data and isinstance(data[0], dict):
        item = data[0]
        # Citoid returns Zotero-shaped items but with some non-item extras.
        for junk in ("key", "version", "accessDate", "source"):
            item.pop(junk, None)
        return item
    return None


def _crossref(doi: str, timeout: int = 25) -> dict | None:
    r = requests.get(CROSSREF.format(urllib.parse.quote(doi)), timeout=timeout,
                     headers={"User-Agent": USER_AGENT})
    if r.status_code != 200:
        return None
    m = r.json().get("message", {})
    item: dict = {"itemType": _CROSSREF_TYPES.get(m.get("type", ""), "journalArticle"),
                  "DOI": doi}
    if m.get("title"):
        item["title"] = m["title"][0]
    creators = []
    for a in m.get("author", []) or []:
        if a.get("family"):
            creators.append({"creatorType": "author",
                             "firstName": a.get("given", ""), "lastName": a["family"]})
        elif a.get("name"):
            creators.append({"creatorType": "author", "name": a["name"]})
    if creators:
        item["creators"] = creators
    parts = (m.get("issued") or {}).get("date-parts", [[]])
    if parts and parts[0]:
        item["date"] = "-".join(f"{p:02d}" if i else str(p)
                                for i, p in enumerate(parts[0]))
    if m.get("container-title"):
        item["publicationTitle"] = m["container-title"][0]
    if m.get("publisher"):
        item["publisher"] = m["publisher"]
    return item


def resolve(url: str) -> tuple[dict | None, str]:
    """Return (zotero-shaped metadata or None, provenance string)."""
    doi = extract_doi(url)
    if doi:
        try:
            item = _crossref(doi)
            if item and item.get("title"):
                return item, "CrossRef (DOI)"
        except requests.RequestException:
            pass
    try:
        item = _citoid(url)
        if item:
            return item, "Zotero translators (via Citoid)"
    except requests.RequestException:
        pass
    return None, "no translator match"
