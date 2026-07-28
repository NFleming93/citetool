"""The Claude verification layer (the core value-add).

Whether or not a translator produced metadata, Claude sees the URL, the
translator's attempt, and the distilled page content, and returns
verified metadata + per-field uncertainty flags — or an honest
"unresolvable". No guessing, no tools: the page was already fetched, so
each verification is a single deterministic call.

Auth (kept deliberately thin and isolated — billing arrangements may
change again):
  - "subscription" mode: the bundled Claude Code CLI's stored sign-in.
    Verified against docs 2026-07-26: third-party Agent SDK apps using
    subscription sign-in draw from the user's own plan limits.
  - "api_key" mode: a console.anthropic.com key, pay-as-you-go fallback.
An API key in the environment would silently shadow subscription auth,
so subscription mode strips it from the subprocess environment.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field

# A pragmatic subset of Zotero item types for web-cited material. The
# schema validator is still the gatekeeper; this just steers Claude.
ITEM_TYPES = ["webpage", "report", "document", "journalArticle", "book",
              "bookSection", "newspaperArticle", "magazineArticle", "blogPost",
              "conferencePaper", "presentation", "thesis", "dataset", "preprint",
              "statute", "bill", "hearing", "encyclopediaArticle"]

MODEL_CHOICES = [
    ("haiku", "Haiku — fastest, lightest on your plan"),
    ("sonnet", "Sonnet — recommended"),
    ("opus", "Opus — most careful judgement"),
]

PEDANTRY_CHOICES = [
    ("strict", "Thorough — flag every uncertainty",
     "Flag every field you are not fully confident about, however minor. "
     "Err on the side of flagging; the reviewer wants to see your doubts."),
    ("balanced", "Balanced — flag what's worth a look",
     "Flag a field only when a careful author would genuinely want to "
     "double-check it: inferred authorship, ambiguous or conflicting dates, "
     "retitled documents, guessed publishers. Routine judgement calls you "
     "are reasonably confident about need no flag."),
    ("relaxed", "Relaxed — only real problems",
     "Only flag genuine problems: contradictions, fields you had to guess, "
     "or key information you could not determine. If title, author, and "
     "date check out against the page, return an empty flags list — "
     "verified is good enough."),
]

PROMPT_TEMPLATE = """You are verifying citation metadata for a reference manager (Zotero).

URL cited in the document: {url}
Anchor text the author used: {anchor}

Translator's attempt at metadata (may be empty, wrong, or good):
{raw}

Distilled page content ({page_status}):
TITLE TAG: {page_title}
METADATA TAGS: {page_meta}
VISIBLE TEXT (truncated): {page_text}

Your job — verify or repair the metadata. Judgement calls that matter:
- itemType: choose the best fit from {item_types}. Government and \
institutional publications are usually "report" or "document", not "webpage".
- Corporate/institutional authors are often only in page text or footers, \
not metadata tags. Use the single-field creator form for them: \
{{"creatorType":"author","name":"Australian Institute of Health and Welfare"}}. \
Use {{"creatorType":"author","firstName":"…","lastName":"…"}} for people.
- Publication dates are often buried in body text ("Published 14 March 2024", \
"© 2023"). Prefer a real date over none; use the precision the page supports \
("2024-03-14", "March 2024", or "2023").
- Replace garbage titles ("Home | Department of Health") with the real \
document title.
- Useful fields when applicable: publisher, institution, reportNumber, \
reportType, websiteTitle, publicationTitle, DOI, language.

Honesty rules:
- Flagging policy for this run: {pedantry} \
Flags look like: {{"field":"…","note":"short reason, e.g. 'author inferred from page footer'"}}.
- If the page content is unavailable/paywalled/irrelevant AND the translator \
gave nothing usable, set "resolvable": false with a short "reason". \
NEVER invent metadata.

Respond with ONLY this JSON, no markdown fences, no commentary:
{{"resolvable": true|false, "reason": null|"…", \
"item": {{"itemType":"…","title":"…","creators":[…],"date":"…","url":"{url}", …}}, \
"flags": [{{"field":"…","note":"…"}}]}}"""


@dataclass
class VerifiedItem:
    resolvable: bool
    item: dict = field(default_factory=dict)
    flags: list[dict] = field(default_factory=list)
    reason: str | None = None
    model_used: str = ""
    raw_response: str = ""


def build_prompt(url: str, anchor: str, raw: dict | None, page,
                 pedantry: str = "strict") -> str:
    pedantry_text = next(t for k, _, t in PEDANTRY_CHOICES if k == pedantry)
    return PROMPT_TEMPLATE.format(
        url=url, anchor=anchor, pedantry=pedantry_text,
        raw=json.dumps(raw, ensure_ascii=False, indent=1) if raw else "(none — translators failed on this URL)",
        page_status=("fetched OK" if page.ok else f"FETCH FAILED: {page.error}"),
        page_title=page.title or "(none)",
        page_meta=json.dumps(page.meta, ensure_ascii=False) if page.meta else "(none)",
        page_text=page.text or "(none)",
        item_types=", ".join(ITEM_TYPES),
    )


def parse_response(text: str, model: str) -> VerifiedItem:
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        raise ValueError("no JSON object in response")
    data = json.loads(m.group(0))
    return VerifiedItem(
        resolvable=bool(data.get("resolvable")),
        item=data.get("item") or {},
        flags=[f for f in (data.get("flags") or []) if isinstance(f, dict)],
        reason=data.get("reason"),
        model_used=model,
        raw_response=text,
    )


def _clean_env(auth_mode: str, api_key: str) -> dict:
    # NOTE: the SDK MERGES this over the inherited environment (verified in
    # subprocess_cli.py), so deleting keys from a copy does nothing — an
    # empty-string override is how you neutralise a stray API key that would
    # otherwise shadow the subscription sign-in.
    if auth_mode == "subscription":
        overlay = {"ANTHROPIC_API_KEY": ""}
        # The sign-in flow ("setup-token") PRINTS a long-lived code rather
        # than storing one, so the wizard captures it into config and we
        # hand it to every call here.
        from . import config as _config
        token = _config.load().get("claude_oauth_token", "")
        if token:
            overlay["CLAUDE_CODE_OAUTH_TOKEN"] = token
        return overlay
    return {"ANTHROPIC_API_KEY": api_key}


class ClaudeVerifier:
    """Real implementation over the Agent SDK. Imports lazily so the rest
    of the app (and all tests) run without the SDK present."""

    def __init__(self, model: str = "sonnet", auth_mode: str = "subscription",
                 api_key: str = "", pedantry: str = "strict"):
        self.model = model
        self.auth_mode = auth_mode
        self.api_key = api_key
        self.pedantry = pedantry

    def _ask(self, prompt: str) -> str:
        import anyio
        from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

        # No max_turns cap: with no tools there is exactly one reply anyway,
        # and the cap made some CLI versions mark the finished run as an error
        # ("error result: success") and exit non-zero.
        options = ClaudeAgentOptions(
            model=self.model,
            allowed_tools=[],          # page already fetched; pure judgement call
            env=_clean_env(self.auth_mode, self.api_key),
        )

        async def run() -> str:
            parts: list[str] = []
            try:
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                parts.append(block.text)
            except Exception:
                # If Claude's reply already arrived, a tantrum from the helper
                # process while shutting down doesn't invalidate it.
                if not parts:
                    raise
                logging.getLogger("citetool").debug(
                    "ignored post-reply SDK error", exc_info=True)
            return "".join(parts)

        return anyio.run(run)

    def verify(self, url: str, anchor: str, raw: dict | None, page) -> VerifiedItem:
        prompt = build_prompt(url, anchor, raw, page, self.pedantry)
        text = self._ask(prompt)
        try:
            return parse_response(text, self.model)
        except (ValueError, json.JSONDecodeError):
            retry = prompt + "\n\nYour previous reply was not valid bare JSON. Respond with ONLY the JSON object."
            return parse_response(self._ask(retry), self.model)

    def check_auth(self) -> tuple[bool, str]:
        """A tiny call to confirm sign-in works. Returns (ok, detail)."""
        try:
            text = self._ask("Reply with exactly: OK")
            return ("OK" in text, text.strip()[:200] or "empty reply")
        except Exception as e:
            return (False, f"{type(e).__name__}: {e}"[:300])


def find_bundled_cli() -> str | None:
    """Locate the Claude Code CLI executable that ships inside the
    claude-agent-sdk package, so the wizard can launch the sign-in flow."""
    try:
        import claude_agent_sdk
    except ImportError:
        return None
    import pathlib
    pkg = pathlib.Path(claude_agent_sdk.__file__).parent
    pattern = "claude.exe" if sys.platform == "win32" else "claude"
    hits = [p for p in pkg.rglob(pattern) if p.is_file()]
    if hits:
        return str(hits[0])
    import shutil
    return shutil.which("claude")   # fall back to a system-wide install
