# CiteTool — Zotero Citation Tool

Reads the hyperlinks out of a Word document, verifies each source's real
citation metadata (with Claude doing the judgement work translators can't),
lets you review everything, and files it neatly into your Zotero library
under **Cited Documents → (document name)**. Your document is never modified.

**If you just want the app:** read `docs/GET-THE-EXE.md`, then
`docs/FIRST-RUN.md`. No programming involved in either.

## Status

- [x] Stage 1 — link extraction from .docx (all three hyperlink formats,
      tables, footnotes/endnotes; read-only)
- [x] Stage 2 — metadata resolution (Zotero's translators via Citoid +
      CrossRef for DOIs)
- [x] Stage 3 — Claude verification layer (item types, corporate authors,
      buried dates, garbage titles, honest failures, uncertainty flags)
- [x] Stage 4 — validation against Zotero's per-item-type schema
- [x] Stage 5 — duplicate matching (DOI → URL → fuzzy title; existing items
      are added to the collection, never copied)
- [x] Stage 6 — review screen (amber flags, edit anything, nothing writes
      without approval)
- [x] Stage 7 — Zotero writes (version concurrency + 412 retry, ≤50-item
      batches, backoff headers, tidy collections, re-runs reuse them)
- [x] Stage 8 — report + per-run log + `*.citemap.json` mapping file (the
      v2 handoff for writing citations back into the document)
- [x] Setup wizard, main window, review/edit dialogs (PySide6)
- [x] End-to-end test suite against a mock Zotero server — passing
- [ ] First run on a real Windows machine (yours!) — the sign-in flow and
      real-library writes can only be truly tested there

## For any Claude (or human) working on this

- `docs/build-brief.md` is the specification; `docs/mapping-schema.md`
  defines the citemap contract v2 depends on.
- `python dev/make_test_doc.py && python dev/test_end_to_end.py` must pass
  before shipping changes. `python dev/screenshot_gui.py` renders every
  screen headlessly for visual checks.
- Stack notes: no bundled translation server — Citoid (Zotero's real
  translators, run by Wikimedia) + CrossRef, with the Claude layer as the
  universal backstop. Claude calls go through the deliberately thin
  `citetool/claude_verify.py`; subscription billing arrangements have been
  in flux, so keep auth isolated there. The Agent SDK bundles a ~275MB CLI,
  hence the app-folder (onedir) build in `CiteTool.spec`.
- The Zotero API key is a password: memory + config file only, never logged.
