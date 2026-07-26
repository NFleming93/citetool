"""
Stage 1 — hyperlink extraction from a .docx (READ-ONLY).

A .docx is a zip of XML files. Hyperlinks live in three shapes:

  1. <w:hyperlink r:id="rId7"> ... </w:hyperlink>
     The r:id points at a relationship in word/_rels/document.xml.rels
     whose Target is the actual URL. This is what Word creates today.

  2. <w:fldSimple w:instr='HYPERLINK "https://..."'> ... </w:fldSimple>
     Older "simple field" form.

  3. Complex fields: a run containing <w:fldChar w:fldCharType="begin"/>,
     then runs of <w:instrText>HYPERLINK "https://..."</w:instrText>,
     then <w:fldChar w:fldCharType="separate"/>, then the visible runs,
     then <w:fldChar w:fldCharType="end"/>. Produced by some tools and
     by pasting from other apps.

We handle all three, in the document body (including inside tables),
footnotes, and endnotes. Nothing here ever writes to the file.

Locations are recorded as (part, paragraph_index, char_start, char_end)
where offsets are into the paragraph's assembled plain text. The v2
field-writer will re-find links primarily by relationship id / URL +
anchor text; offsets are a human-friendly aid and a cross-check.

Stdlib only (zipfile + xml.etree) so the eventual .exe stays simple.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"

def _w(tag: str) -> str: return f"{{{W}}}{tag}"
def _r(tag: str) -> str: return f"{{{R}}}{tag}"

# Parts we scan, and the rels file that resolves each one's r:id values.
_PARTS = [
    ("body",     "word/document.xml",  "word/_rels/document.xml.rels"),
    ("footnote", "word/footnotes.xml", "word/_rels/footnotes.xml.rels"),
    ("endnote",  "word/endnotes.xml",  "word/_rels/endnotes.xml.rels"),
]

_HYPERLINK_INSTR = re.compile(r'HYPERLINK\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)


@dataclass
class LinkRecord:
    """One hyperlink found in the document."""
    link_id: str            # stable id for this run: L001, L002, ...
    url: str
    anchor_text: str        # the visible, clickable text
    part: str               # body | footnote | endnote
    paragraph_index: int    # 0-based within its part
    char_start: int         # offsets into the paragraph's plain text
    char_end: int
    context: str            # surrounding text, for eyeballing
    source: str             # hyperlink | fldSimple | complexField
    note_id: str | None = None   # footnote/endnote id, when applicable


@dataclass
class ExtractionResult:
    source_file: str
    extracted_at: str
    links: list[LinkRecord] = field(default_factory=list)
    skipped_non_http: list[str] = field(default_factory=list)  # e.g. mailto:, file:
    internal_anchor_count: int = 0   # links to bookmarks within the doc

    def to_json(self) -> str:
        d = {
            "schema": "citetool-links-v1",
            "source_file": self.source_file,
            "extracted_at": self.extracted_at,
            "links": [asdict(l) for l in self.links],
            "skipped_non_http": self.skipped_non_http,
            "internal_anchor_count": self.internal_anchor_count,
        }
        return json.dumps(d, indent=2, ensure_ascii=False)


def _load_rels(zf: zipfile.ZipFile, rels_path: str) -> dict[str, str]:
    """Map relationship id -> external target URL."""
    try:
        data = zf.read(rels_path)
    except KeyError:
        return {}
    rels = {}
    for rel in ET.fromstring(data).iter(f"{{{REL}}}Relationship"):
        if rel.get("TargetMode") == "External":
            rels[rel.get("Id")] = rel.get("Target")
    return rels


def _parse_instr(instr: str) -> str | None:
    """Pull the URL out of a HYPERLINK field instruction, if it is one."""
    m = _HYPERLINK_INSTR.search(instr or "")
    if not m:
        return None
    url = m.group(1) or m.group(2)
    # A '\l' switch means an internal bookmark link — not a citation.
    if r"\l" in instr.split(url)[0]:
        return None
    return url


class _ParagraphScanner:
    """Walks one <w:p>, assembling its plain text and hyperlink spans."""

    def __init__(self, rels: dict[str, str]):
        self.rels = rels
        self.chunks: list[str] = []
        self.pos = 0
        self.spans: list[tuple[int, int, str, str]] = []  # start, end, url, source
        self.internal_anchors = 0
        # complex-field state
        self._fld_mode: str | None = None      # None | "instr" | "result"
        self._fld_instr: list[str] = []
        self._fld_start = 0
        self._fld_depth = 0                    # nested fields: track but only handle depth 1

    def _emit(self, text: str) -> None:
        if text:
            self.chunks.append(text)
            self.pos += len(text)

    def scan(self, p: ET.Element) -> None:
        self._walk(p)

    def _walk(self, elem: ET.Element) -> None:
        for child in elem:
            tag = child.tag
            if tag == _w("hyperlink"):
                rid = child.get(_r("id"))
                start = self.pos
                self._walk(child)
                if rid and rid in self.rels:
                    self.spans.append((start, self.pos, self.rels[rid], "hyperlink"))
                elif child.get(_w("anchor")) is not None:
                    self.internal_anchors += 1
            elif tag == _w("fldSimple"):
                url = _parse_instr(child.get(_w("instr"), ""))
                start = self.pos
                self._walk(child)
                if url:
                    self.spans.append((start, self.pos, url, "fldSimple"))
            elif tag == _w("r"):
                self._run(child)
            elif tag in (_w("pPr"), _w("rPr")):
                continue  # formatting properties — no visible text
            else:
                # w:ins (tracked insertions), w:smartTag, w:sdt wrappers, etc.
                self._walk(child)

    def _run(self, run: ET.Element) -> None:
        for rc in run:
            tag = rc.tag
            if tag == _w("fldChar"):
                fct = rc.get(_w("fldCharType"))
                if fct == "begin":
                    self._fld_depth += 1
                    if self._fld_depth == 1:
                        self._fld_mode, self._fld_instr = "instr", []
                elif fct == "separate" and self._fld_depth == 1 and self._fld_mode == "instr":
                    self._fld_mode = "result"
                    self._fld_start = self.pos
                elif fct == "end":
                    if self._fld_depth == 1:
                        url = _parse_instr("".join(self._fld_instr))
                        if url and self._fld_mode == "result":
                            self.spans.append(
                                (self._fld_start, self.pos, url, "complexField"))
                        self._fld_mode = None
                    self._fld_depth = max(0, self._fld_depth - 1)
            elif tag == _w("instrText"):
                if self._fld_mode == "instr" and self._fld_depth == 1:
                    self._fld_instr.append(rc.text or "")
            elif tag == _w("t"):
                if self._fld_mode != "instr":   # instruction text is never visible
                    self._emit(rc.text or "")
            elif tag == _w("tab"):
                self._emit("\t")
            elif tag in (_w("br"), _w("cr")):
                self._emit(" ")

    @property
    def text(self) -> str:
        return "".join(self.chunks)


def _context(text: str, start: int, end: int, pad: int = 60) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    prefix = "…" if a > 0 else ""
    suffix = "…" if b < len(text) else ""
    return prefix + text[a:b].replace("\t", " ") + suffix


def _note_id_for(p: ET.Element, root: ET.Element, part: str) -> str | None:
    """For footnotes/endnotes, find which numbered note this paragraph sits in."""
    if part == "body":
        return None
    tag = _w("footnote") if part == "footnote" else _w("endnote")
    for note in root.iter(tag):
        for para in note.iter(_w("p")):
            if para is p:
                return note.get(_w("id"))
    return None


def extract_links(docx_path: str) -> ExtractionResult:
    """Extract every external hyperlink from a .docx. Never modifies the file."""
    result = ExtractionResult(
        source_file=docx_path,
        extracted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    counter = 0
    with zipfile.ZipFile(docx_path) as zf:
        names = set(zf.namelist())
        for part, xml_path, rels_path in _PARTS:
            if xml_path not in names:
                continue
            rels = _load_rels(zf, rels_path)
            root = ET.fromstring(zf.read(xml_path))
            # iter() yields every <w:p> in document order, wherever it nests —
            # top level, inside table cells, inside text boxes.
            for p_index, p in enumerate(root.iter(_w("p"))):
                scanner = _ParagraphScanner(rels)
                scanner.scan(p)
                result.internal_anchor_count += scanner.internal_anchors
                if not scanner.spans:
                    continue
                text = scanner.text
                for start, end, url, source in scanner.spans:
                    if not url.lower().startswith(("http://", "https://")):
                        result.skipped_non_http.append(url)
                        continue
                    counter += 1
                    result.links.append(LinkRecord(
                        link_id=f"L{counter:03d}",
                        url=url,
                        anchor_text=text[start:end],
                        part=part,
                        paragraph_index=p_index,
                        char_start=start,
                        char_end=end,
                        context=_context(text, start, end),
                        source=source,
                        note_id=_note_id_for(p, root, part),
                    ))
    return result
