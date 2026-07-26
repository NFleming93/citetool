# Getting your CiteTool app (no programming involved)

Windows apps have to be *built on Windows*, and Claude's workspace isn't one —
so the build happens on GitHub, a free service that runs the build for you in
the cloud. You upload the folder once, press one button, and download the app.
Budget 20–30 minutes the first time. Every step is a click; there is no typing
of commands anywhere.

**Safety note:** this project contains no passwords or keys — they only ever
live on your own computer after setup. Never upload your `config.json` or any
file containing a key.

## One-time setup

1. **Create a free GitHub account** at https://github.com/signup (just an
   email and a password).

2. **Create a repository** (GitHub's word for "a project folder"):
   - Click the **+** at the top-right → **New repository**
   - Repository name: `citetool`
   - Choose **Public** (public repos get unlimited free builds; the code has
     no secrets in it)
   - Click **Create repository**

3. **Upload the project:**
   - On the new repository page, click the link that says
     **"uploading an existing file"**
   - Open the unzipped `zotero-citation-tool` folder on your computer,
     press Ctrl+A to select everything inside it, and **drag it all** onto
     the GitHub upload box (folders drag along with their contents)
   - Wait for the file list to finish appearing, then click
     **Commit changes** at the bottom

## Getting the app

4. Click the **Actions** tab at the top of your repository.
   - If GitHub asks you to enable workflows, click the green enable button.
   - The upload itself usually starts a build automatically — you'll see
     **"Build Windows app"** with a spinning amber dot.
   - If nothing is running: click **Build Windows app** in the left list →
     **Run workflow** button → green **Run workflow**.

5. **Wait ~10–15 minutes** until the dot turns into a green tick ✓.
   (It runs the full test suite first, then builds.)

6. Click the finished run, scroll to the bottom to **Artifacts**, and click
   **CiteTool-windows** to download a zip.

7. Unzip it anywhere you like (e.g. your Desktop). Inside is a `CiteTool`
   folder — open it and double-click **CiteTool.exe**.
   Now read **FIRST-RUN.md**, because Windows will show a warning the first
   time (that's normal and explained there).

## If something goes wrong

- **Red ✗ instead of green ✓:** click the failed run, click the step with
  the red mark, copy the last screenful of text, and paste it to Claude at
  claude.ai with "my CiteTool build failed with this". That's genuinely all
  the debugging you need to do.
- **Can't find the Artifacts section:** it only appears after the run
  finishes. You also need to be signed in to GitHub to download it.

## When Claude gives you an updated version later

Upload the changed files the same way (repository page → **Add file** →
**Upload files**), commit, and a fresh build starts automatically.
