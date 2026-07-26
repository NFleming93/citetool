# First run — what to expect

## The Windows warning (normal, one time)

The first time you open **CiteTool.exe**, Windows SmartScreen will likely say
*"Windows protected your PC"*. That's not a virus detection — it just means
the app isn't signed with a paid publisher certificate. Click **More info**,
then **Run anyway**. You built this app yourself from code you can read, which
is more than can be said for most things you install.

## What you need (two accounts, both yours)

1. **A Claude subscription** (Pro or Max) — this powers the citation
   checking, and usage comes out of your own plan's limits.
2. **A free Zotero account** — https://www.zotero.org/user/register if you
   don't have one. Your library, your data.

Nothing is shared with anyone else and no keys ever leave your computer
except to the service they belong to.

## The setup wizard (runs once)

**Step 1 — Claude.** Choose "Use my Claude subscription" and press **Sign in
with Claude…**. A small black window opens and your web browser asks you to
approve — this is Claude's official sign-in, the same one Claude Code uses.
Approve it, come back, press **Check connection**, and wait for the green tick.

**Step 2 — Zotero (about 3 minutes).** The wizard opens Zotero's key page in
your browser. Log in, tick **both** boxes — *Allow library access* and *Allow
write access* — press **Save Key**, copy the key it shows, and paste it into
the wizard. It tests immediately and tells you exactly what it found
("✓ Connected — your library, 1,204 items, write access confirmed") or
exactly what's wrong ("write access isn't ticked — re-create the key").
You never need to look up your user ID; the app works it out from the key.

## Using it

1. Drop a `.docx` onto the window (your document is only ever **read**,
   never modified).
2. Press **Analyse document** and watch each link get resolved and checked
   by Claude. Amber = "I did it, but check this field"; red = "I couldn't
   verify this and won't guess".
3. Press **Review & write to Zotero**, look over the table (double-click
   any row to fix it), untick anything unwanted, and approve.
4. Items land in Zotero under **Cited Documents → (your document's name)**.
   If you use the Zotero desktop app, they appear after its next sync —
   press the green sync arrow or wait a minute.

A `yourdocument.citemap.json` file is saved next to your document. Keep it —
it's the map a future version uses to insert live citations into the
document itself.

## If something breaks

Every run writes a log with no passwords in it. Press **Open run log** (or
find them in `%APPDATA%\CiteTool\logs`), copy the contents to Claude at
claude.ai, and describe what you saw. First runs of new software hit snags;
that log is designed to make them quick to fix.
