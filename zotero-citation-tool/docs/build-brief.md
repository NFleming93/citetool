# Build Brief: Zotero Citation Tool (v1)

## Who you're working with

I'm not a programmer. Explain choices in plain language, make sensible technical decisions on my behalf (telling me the trade-offs when they matter), and build in stages I can actually test. I'll supply a real document to test against. This brief was developed in a prior planning conversation with Claude — the decisions below are settled unless you spot a genuine problem with one, in which case flag it before building around it.

## The problem

I write documents (.docx) where in-text citations are just ad-hoc hyperlinked parentheticals — e.g. *"Claude is a very good AI and can do lots of things ([Claude](https://example.com))"* — where the parenthetical text is a hyperlink to the source. I want a desktop tool that visits each of those links, works out the correct citation metadata, and populates my Zotero library cleanly and reproducibly.

## V1 scope — build this now

A Windows desktop app with a first-run setup wizard, that then runs this pipeline on a chosen .docx:

1. **Parse the document.** Extract every hyperlink plus its anchor text and location. Read-only — v1 never modifies the source document.
2. **Resolve metadata.** For each URL, try Zotero's translation machinery first (translation server or equivalent — pick the simplest option that packages reliably into a shippable exe).
3. **Claude verification layer.** Whether the translator succeeded or failed, fetch the page content and have Claude verify/repair the metadata. This is the core value-add: translators are poor on government documents and grey literature. Claude's judgement calls include item type (report vs document vs webpage), corporate/institutional authors buried in page text rather than metadata tags, publication dates hidden in body text, and replacing garbage page titles ("Home | Department of Health") with real ones. Claude returns structured metadata plus an uncertainty flag and short note for any field it isn't confident about. Unresolvable links get reported honestly — never silently guessed.
4. **Validate.** Check Claude's output against Zotero's per-item-type schema before any write (invalid fields for an item type are rejected by the API; corporate authors must use the single-field creator format).
5. **Deduplicate.** Match against the existing library by DOI, then URL, then fuzzy title. If the item already exists, don't create a copy — add the existing item's key to the project collection instead.
6. **Review screen.** Before anything is written: show a table of every citation with Claude's uncertainty flags highlighted (amber) alongside its note ("author inferred from page footer — check me"). I edit or approve, *then* it commits. Nothing writes to Zotero without passing this screen.
7. **Write to Zotero** via the Web API v3 into a tidy collection structure (below).
8. **Report.** Summary screen plus a saved log: items added, items matched-to-existing, links that failed and why.

## V2 intention — design for it, don't build it yet

V2 will replace each ad-hoc parenthetical in the document with a real Zotero citation field (the CSL_CITATION field codes the Zotero Word plugin uses), written into a *new copy* of the docx, so opening it and hitting Refresh in the Zotero tab makes every citation live and restyleable. This is known to be the fiddly part, hence deferred.

What v1 must do to make v2 easy later:

- Save a per-run **mapping file** (JSON): each hyperlink → its location in the document → the Zotero item key it resolved to. V2 consumes this.
- Keep the pipeline stages modular so a "write fields" stage can bolt onto the end.
- Field codes reference items by library-specific URIs, so the mapping must record the user's library ID alongside item keys.

## Technical decisions already made

### Claude integration

- Use the **Claude Agent SDK** (Python or TypeScript — your call) with **subscription sign-in**, not API keys. First run shows a "Sign in with Claude" button that does the browser auth flow (same as Claude Code login) and stores the token locally. Usage draws from the user's own Pro/Max plan.
- **Verify current Agent SDK auth/billing docs at build time.** The subscription-usage arrangements were in flux mid-2026 (see https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) — confirm the current mechanics before wiring auth.
- **Model dropdown** in settings: Haiku / Sonnet / Opus with one-line descriptions ("fastest, lightest on your plan" / "recommended" / "most careful judgement"). Default: Sonnet.
- Keep the model-call layer thin and isolated so billing/auth changes later mean a small adjustment, not a rewrite.

### Zotero integration

- **Web API v3.** Auth is userID + API key with library write access, both from zotero.org → Settings → Security.
- Handle the known gotchas: version-based concurrency (send the last-seen library version; on a 412, re-fetch and retry), max 50 items per write request, honour rate-limit/backoff headers.
- **Collections:** create one parent collection ("Cited Documents"), with a subcollection per source document named from its filename. Assign items to the subcollection **at creation time** so nothing lands loose in the library root. Re-running on the same document reuses its existing subcollection rather than creating "Paper X (2)".
- Remember collections are pointers, not containers — dedup + add-to-collection keeps one canonical item per source across many projects.
- Note in the UI that items appear in the desktop app after its next sync.

### First-run setup wizard

- Screen 1: "Sign in with Claude" button → browser flow.
- Screen 2: Zotero credentials, with hand-holding — a button that opens the exact zotero.org settings page, plain instructions on which permissions to tick, and two paste boxes. On paste, immediately fire a test API call and show either "✓ Connected — [library name], N items, write access confirmed" or a precise error ("your key doesn't have write access ticked").
- Config stored locally per machine. Treat the Zotero key like a password (never logged, never transmitted anywhere but zotero.org).

### Run experience

- Drag-and-drop or file picker for the .docx.
- Live progress table, one row per link, marching through: found → resolved → verified → added (or flagged/failed).
- Then the review screen, then commit, then the report.

### Packaging and distribution

- Single Windows executable a non-technical person can run. (Cross-platform is a nice-to-have, not a requirement.)
- Include a short README for recipients covering: the SmartScreen "unknown publisher" warning on unsigned exes and how to run anyway; the two-account setup (Claude paid plan + free zotero.org account); and the three-minute Zotero key creation.
- Each user brings their own Claude subscription and their own Zotero key — nothing shared, nothing pooled.

## Non-goals for v1

- No document modification / field writing (that's v2).
- No downloading of PDF attachments into Zotero.
- No group libraries (fine as a later stretch — the API supports them via groupID).
- No citation style formatting — Zotero's Word plugin owns that once v2 exists.

## How to work with me

Start by confirming your stack choices and showing me the project skeleton before writing much code. Then build in testable stages — suggested order: (1) docx link extraction with a printed list I can eyeball, (2) metadata resolution + Claude verification on those links with results shown to me, (3) Zotero writing with collections + dedup, (4) the GUI wizard and review screen wrapping it all, (5) packaging to an exe. I'll test each stage against a real document. When a judgement call affects citation *accuracy* (as opposed to code internals), ask me — I know what a correct government-document citation looks like; you handle everything else.
