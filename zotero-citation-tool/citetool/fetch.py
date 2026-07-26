"""Fetch a cited page and distill it into what Claude needs to judge the
citation: <title>, metadata tags, and visible text. Handles PDFs (common
for government reports) via pypdf. Read-only, size-capped, honest about
failures."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import requests

USER_AGENT = "CiteTool/1.0 (citation metadata tool; respects robots and rate limits)"
MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT_CHARS = 15_000
_INTERESTING_META = ("citation_", "dc.", "dcterms.", "og:", "article:",
                     "author", "date", "description", "prism.")


@dataclass
class PageContent:
    url: str
    final_url: str = ""
    ok: bool = False
    status: int | None = None
    content_type: str = ""
    is_pdf: bool = False
    title: str = ""
    meta: dict[str, str] = field(default_factory=dict)
    text: str = ""
    error: str = ""


class _Distiller(HTMLParser):
    _SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            a = dict(attrs)
            key = (a.get("name") or a.get("property") or "").lower()
            content = a.get("content", "")
            if content and any(key.startswith(p) for p in _INTERESTING_META):
                self.meta.setdefault(key, content[:500])

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        elif data.strip():
            self.text_parts.append(data)


def _pdf_text(data: bytes, max_pages: int = 8) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    chunks = []
    for page in reader.pages[:max_pages]:
        chunks.append(page.extract_text() or "")
    return "\n".join(chunks)


def fetch_page(url: str, timeout: int = 30) -> PageContent:
    pc = PageContent(url=url)
    try:
        resp = requests.get(
            url, timeout=timeout, stream=True, allow_redirects=True,
            headers={"User-Agent": USER_AGENT,
                     "Accept": "text/html,application/xhtml+xml,application/pdf,*/*"},
        )
        pc.status = resp.status_code
        pc.final_url = resp.url
        pc.content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        if resp.status_code >= 400:
            pc.error = f"HTTP {resp.status_code}"
            return pc
        body = b""
        for chunk in resp.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                break
        pc.is_pdf = "pdf" in pc.content_type or body[:5] == b"%PDF-"
        if pc.is_pdf:
            try:
                pc.text = re.sub(r"\s+", " ", _pdf_text(body))[:MAX_TEXT_CHARS]
                pc.ok = True
            except Exception as e:
                pc.error = f"PDF text extraction failed: {e}"
                pc.ok = True   # we still know it exists; Claude gets URL + headers
        else:
            enc = resp.encoding or "utf-8"
            d = _Distiller()
            try:
                d.feed(body.decode(enc, errors="replace"))
            except Exception:
                pass
            pc.title = re.sub(r"\s+", " ", "".join(d.title_parts)).strip()[:300]
            pc.meta = d.meta
            pc.text = re.sub(r"\s+", " ", " ".join(d.text_parts))[:MAX_TEXT_CHARS]
            pc.ok = True
    except requests.exceptions.Timeout:
        pc.error = "timed out"
    except requests.exceptions.SSLError:
        pc.error = "SSL/certificate error"
    except requests.exceptions.ConnectionError:
        pc.error = "could not connect"
    except Exception as e:
        pc.error = str(e)[:200]
    return pc
