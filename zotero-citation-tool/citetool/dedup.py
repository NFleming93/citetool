"""Match a candidate item against the existing library:
DOI first, then normalised URL, then fuzzy title. One canonical item per
source — a hit means 'add to collection', never 'create a copy'."""

from __future__ import annotations

import difflib
import re
import urllib.parse


def norm_doi(doi: str) -> str:
    doi = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def norm_url(url: str) -> str:
    try:
        p = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/")
    query = "&".join(sorted(
        q for q in p.query.split("&")
        if q and not q.lower().startswith(("utm_", "fbclid", "gclid", "mc_cid", "mc_eid"))
    ))
    return f"{host}{path}" + (f"?{query}" if query else "")


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


class LibraryIndex:
    def __init__(self, items: list[dict]):
        self.by_doi: dict[str, str] = {}
        self.by_url: dict[str, str] = {}
        self.titles: list[tuple[str, str]] = []
        for it in items:
            key = it.get("key", "")
            if not key:
                continue
            if it.get("DOI"):
                self.by_doi.setdefault(norm_doi(it["DOI"]), key)
            if it.get("url"):
                self.by_url.setdefault(norm_url(it["url"]), key)
            if it.get("title"):
                t = norm_title(it["title"])
                if len(t) >= 16:
                    self.titles.append((t, key))

    def find(self, item: dict) -> tuple[str, str] | None:
        """Return (existing item key, how it matched) or None."""
        if item.get("DOI"):
            key = self.by_doi.get(norm_doi(item["DOI"]))
            if key:
                return key, "DOI"
        if item.get("url"):
            key = self.by_url.get(norm_url(item["url"]))
            if key:
                return key, "URL"
        title = norm_title(item.get("title", ""))
        if len(title) >= 16:
            for t, key in self.titles:
                if difflib.SequenceMatcher(None, title, t).ratio() >= 0.93:
                    return key, "similar title"
        return None
