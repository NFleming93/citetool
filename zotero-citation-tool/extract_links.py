#!/usr/bin/env python3
"""
Stage 1 runner.

    python extract_links.py path/to/document.docx

Prints every hyperlink found (with anchor text and location) and writes
<document>.links.json next to this script — the seed of the per-run
mapping file that v2 will consume. The source document is never modified.
"""

import sys
from pathlib import Path

from citetool.docx_links import extract_links


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    docx = Path(sys.argv[1])
    if not docx.exists():
        print(f"File not found: {docx}")
        return 1

    result = extract_links(str(docx))

    if not result.links:
        print("No external hyperlinks found.")
    else:
        idw = 4
        anchw = max(12, min(34, max(len(l.anchor_text) for l in result.links)))
        print(f"\n{len(result.links)} link(s) found in {docx.name}\n")
        print(f"{'id':<{idw}}  {'anchor text':<{anchw}}  {'where':<22}  url")
        print("-" * (idw + anchw + 22 + 40))
        for l in result.links:
            where = f"{l.part} ¶{l.paragraph_index}"
            if l.note_id:
                where += f" (note {l.note_id})"
            anchor = (l.anchor_text[:anchw - 1] + "…") if len(l.anchor_text) > anchw else l.anchor_text
            print(f"{l.link_id:<{idw}}  {anchor:<{anchw}}  {where:<22}  {l.url}")
        print("\nContext for each (check the anchor is what you expect):\n")
        for l in result.links:
            print(f"  {l.link_id}: {l.context}")

    if result.skipped_non_http:
        print(f"\nSkipped {len(result.skipped_non_http)} non-web link(s) "
              f"(mailto:, file:, etc.): {', '.join(result.skipped_non_http)}")
    if result.internal_anchor_count:
        print(f"Ignored {result.internal_anchor_count} internal link(s) "
              f"(cross-references within the document).")

    out = docx.with_suffix(".links.json")
    out.write_text(result.to_json(), encoding="utf-8")
    print(f"\nSaved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
