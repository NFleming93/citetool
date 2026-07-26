# Per-run mapping file (v2 handoff)

Written as `<document>.citemap.json` after every successful commit. V2 reads
this to replace each ad-hoc parenthetical with a live CSL_CITATION field in a
new copy of the docx.

```json
{
  "schema": "citetool-map-v1",
  "source_file": "paper.docx",
  "source_sha256": "…",              // detect if the doc changed since the run
  "run_at": "2026-07-26T03:12:00Z",
  "zotero": {
    "library_type": "user",          // field codes use library-specific URIs,
    "library_id": "1234567",         // so the library ID must travel with keys
    "collection_key": "ABCD1234"     // the per-document subcollection
  },
  "links": [
    {
      "link_id": "L001",
      "url": "https://…",
      "anchor_text": "Claude",
      "part": "body",
      "paragraph_index": 3,
      "char_start": 42,
      "char_end": 48,
      "link_source": "hyperlink",    // hyperlink | fldSimple | complexField
      "status": "added",             // added | matched-existing | failed
      "item_key": "XYZ98765",        // null when failed
      "failure_reason": null
    }
  ]
}
```

Stage 1 already emits the location half of this (`*.links.json`); the commit
stage merges in item keys and library info. V2's re-finding strategy: locate
the link by relationship id / URL + anchor text, using the recorded offsets as
a cross-check, so minor edits to the document don't break the swap.
