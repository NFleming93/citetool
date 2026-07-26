"""Orchestrates the run: extract → resolve → fetch → verify → validate,
then STOP for human review, then commit (dedup + collections + write),
then report + the v2 mapping file. Injectable resolver/fetcher/verifier
so every stage is testable alone. Nothing writes to Zotero before
commit() is called with the reviewed proposals."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config as cfg
from .docx_links import extract_links, LinkRecord
from .zotero_schema import get_schema, validate_item
from .dedup import LibraryIndex

log = logging.getLogger("citetool")


@dataclass
class Proposal:
    """One unique URL's citation-in-waiting (several links may share it)."""
    url: str
    link_ids: list[str]
    anchor: str
    provenance: str = ""
    item: dict = field(default_factory=dict)
    flags: list[dict] = field(default_factory=list)
    schema_problems: list[str] = field(default_factory=list)
    status: str = "pending"       # pending|ready|flagged|unresolvable|error
    reason: str = ""
    approved: bool = False
    # filled in by commit():
    action: str = ""              # added | matched-existing | failed
    item_key: str = ""
    match_how: str = ""
    failure: str = ""


class Pipeline:
    def __init__(self, resolver=None, fetcher=None, verifier=None,
                 zotero=None, schema=None, progress=None):
        from . import resolve as _resolve, fetch as _fetch
        self.resolver = resolver or _resolve.resolve
        self.fetcher = fetcher or _fetch.fetch_page
        self.verifier = verifier
        self.zotero = zotero
        self.schema = schema
        self.progress = progress or (lambda *a, **k: None)
        self.links: list[LinkRecord] = []
        self.proposals: list[Proposal] = []
        self.docx_path: Path | None = None

    def _emit(self, url: str, status: str, detail: str = ""):
        self.progress(url, status, detail)

    # ---------- phase 1: read the document (read-only) ----------

    def load_document(self, docx_path: str):
        self.docx_path = Path(docx_path)
        result = extract_links(docx_path)
        self.links = result.links
        by_url: dict[str, Proposal] = {}
        for l in self.links:
            p = by_url.get(l.url)
            if p:
                p.link_ids.append(l.link_id)
            else:
                by_url[l.url] = Proposal(url=l.url, link_ids=[l.link_id],
                                         anchor=l.anchor_text)
        self.proposals = list(by_url.values())
        log.info("Extracted %d links (%d unique URLs) from %s",
                 len(self.links), len(self.proposals), self.docx_path.name)
        return result

    # ---------- phase 2: metadata (network + Claude, still no writes) ----------

    def run_metadata(self):
        today = datetime.now(timezone.utc).date().isoformat()
        for p in self.proposals:
            try:
                self._emit(p.url, "resolving", "")
                raw, p.provenance = self.resolver(p.url)
                self._emit(p.url, "fetching",
                           p.provenance if raw else "translators failed — fetching page")
                page = self.fetcher(p.url)
                self._emit(p.url, "verifying", "asking Claude…")
                v = self.verifier.verify(p.url, p.anchor, raw, page)
                if not v.resolvable:
                    p.status, p.reason = "unresolvable", v.reason or "no usable metadata"
                    self._emit(p.url, "unresolvable", p.reason)
                    log.warning("UNRESOLVABLE %s — %s", p.url, p.reason)
                    continue
                item = dict(v.item)
                item.setdefault("url", p.url)
                item.setdefault("accessDate", today)
                clean, problems = validate_item(item, self.schema)
                p.item, p.flags, p.schema_problems = clean, v.flags, problems
                if "no title" in problems:
                    p.status, p.reason = "error", "verification produced no title"
                    self._emit(p.url, "error", p.reason)
                    continue
                p.status = "flagged" if (v.flags or problems) else "ready"
                p.approved = True
                detail = "; ".join(f"{f.get('field')}: {f.get('note')}" for f in v.flags)
                self._emit(p.url, p.status, detail)
                log.info("%s %s -> %s '%s' %s", p.status.upper(), p.url,
                         clean.get("itemType"), clean.get("title", "")[:80],
                         f"[{detail}]" if detail else "")
            except Exception as e:
                p.status, p.reason = "error", f"{type(e).__name__}: {e}"[:300]
                p.approved = False
                self._emit(p.url, "error", p.reason)
                log.error("ERROR %s — %s", p.url, p.reason)

    # ---------- phase 3: commit (only after human review) ----------

    def commit(self) -> dict:
        assert self.zotero and self.docx_path
        approved = [p for p in self.proposals
                    if p.approved and p.status in ("ready", "flagged")]
        self._emit("", "commit", "reading your library for duplicate matching…")
        index = LibraryIndex(self.zotero.all_items())
        self._emit("", "commit", "preparing collections…")
        _, sub_key = self.zotero.ensure_collections(self.docx_path.stem)

        to_create: list[Proposal] = []
        for p in approved:
            hit = index.find(p.item)
            if hit:
                p.item_key, p.match_how = hit
                try:
                    self.zotero.add_item_to_collection(p.item_key, sub_key)
                    p.action = "matched-existing"
                    self._emit(p.url, "matched", f"already in library ({p.match_how})")
                except Exception as e:
                    p.action, p.failure = "failed", f"collection update: {e}"[:200]
                    self._emit(p.url, "failed", p.failure)
            else:
                p.item.setdefault("collections", [sub_key])  # assigned at creation
                to_create.append(p)

        if to_create:
            self._emit("", "commit", f"writing {len(to_create)} new item(s) to Zotero…")
            results = self.zotero.create_items([p.item for p in to_create])
            for p, res in zip(to_create, results):
                if res and "key" in res:
                    p.action, p.item_key = "added", res["key"]
                    self._emit(p.url, "added", res["key"])
                else:
                    p.action = "failed"
                    p.failure = (res or {}).get("error", "unknown write error")
                    self._emit(p.url, "failed", p.failure)

        for p in self.proposals:
            if p.status in ("unresolvable", "error"):
                p.action, p.failure = "failed", p.reason
            elif not p.approved and not p.action:
                p.action, p.failure = "skipped", "not approved at review"

        summary = self._write_outputs(sub_key)
        return summary

    # ---------- outputs: mapping file (v2 handoff) + report ----------

    def _write_outputs(self, collection_key: str) -> dict:
        lib_id = getattr(self.zotero, "user_id", "")
        key_by_url = {p.url: p for p in self.proposals}
        links_out = []
        for l in self.links:
            p = key_by_url[l.url]
            links_out.append({
                "link_id": l.link_id, "url": l.url, "anchor_text": l.anchor_text,
                "part": l.part, "paragraph_index": l.paragraph_index,
                "char_start": l.char_start, "char_end": l.char_end,
                "link_source": l.source,
                "status": p.action or p.status,
                "item_key": p.item_key or None,
                "failure_reason": p.failure or None,
            })
        citemap = {
            "schema": "citetool-map-v1",
            "source_file": self.docx_path.name,
            "source_sha256": hashlib.sha256(self.docx_path.read_bytes()).hexdigest(),
            "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "zotero": {"library_type": "user", "library_id": lib_id,
                       "collection_key": collection_key},
            "links": links_out,
        }
        map_path = self.docx_path.with_suffix(".citemap.json")
        map_path.write_text(json.dumps(citemap, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        counts = {"added": 0, "matched-existing": 0, "failed": 0, "skipped": 0}
        for p in self.proposals:
            counts[p.action] = counts.get(p.action, 0) + 1
        log.info("RUN COMPLETE %s — %s. Mapping: %s", self.docx_path.name,
                 counts, map_path)
        return {"counts": counts, "citemap": str(map_path),
                "proposals": self.proposals,
                "note": "New items appear in the Zotero desktop app after its next sync."}


def setup_logging() -> Path:
    """One log file per run — safe to send to a human or a Claude for help.
    Credentials never pass through logging."""
    path = cfg.logs_dir() / f"run-{datetime.now():%Y%m%d-%H%M%S}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    return path


def load_schema_cached():
    return get_schema(cfg.config_dir() / "zotero-schema.json")
