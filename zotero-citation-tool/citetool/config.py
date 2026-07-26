"""Local per-machine configuration. The Zotero key is a password: it is
stored only here, sent only to zotero.org, and never written to any log."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "CiteTool"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = config_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {
    "claude_auth_mode": "subscription",   # "subscription" | "api_key"
    "anthropic_api_key": "",              # only used in api_key mode
    "model": "sonnet",                    # haiku | sonnet | opus (CLI aliases)
    "zotero_api_key": "",
    "zotero_user_id": "",                 # derived automatically from the key
    "zotero_username": "",
    "setup_complete": False,
}


def load() -> dict:
    p = config_dir() / "config.json"
    cfg = dict(DEFAULTS)
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg: dict) -> None:
    p = config_dir() / "config.json"
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)   # owner-only where the OS supports it
    except OSError:
        pass
