"""Validate items against Zotero's per-item-type schema before any write.
The live schema is fetched from api.zotero.org/schema and cached; a small
bundled fallback covers offline first runs. Invalid fields are dropped
and reported, never silently written (the API would reject them)."""

from __future__ import annotations

import json
from pathlib import Path

import requests

SCHEMA_URL = "https://api.zotero.org/schema"
_FALLBACK = Path(__file__).parent / "data" / "schema-fallback.json"


def get_schema(cache_path: Path, timeout: int = 30) -> dict:
    try:
        r = requests.get(SCHEMA_URL, timeout=timeout,
                         headers={"Accept-Encoding": "gzip"})
        if r.status_code == 200:
            schema = r.json()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(schema), encoding="utf-8")
            return schema
    except requests.RequestException:
        pass
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return json.loads(_FALLBACK.read_text(encoding="utf-8"))


def _type_map(schema: dict) -> dict[str, dict]:
    out = {}
    for t in schema.get("itemTypes", []):
        fields = {f.get("field") for f in t.get("fields", [])} | {"itemType", "creators", "tags", "collections", "relations"}
        creator_types = {c.get("creatorType") for c in t.get("creatorTypes", [])}
        out[t["itemType"]] = {"fields": fields, "creatorTypes": creator_types,
                              "primaryCreator": next((c["creatorType"] for c in t.get("creatorTypes", [])
                                                      if c.get("primary")), "author")}
    return out


def validate_item(item: dict, schema: dict) -> tuple[dict, list[str]]:
    """Return (cleaned item safe to POST, list of human-readable problems)."""
    problems: list[str] = []
    types = _type_map(schema)
    itype = item.get("itemType", "")
    if itype not in types:
        problems.append(f"unknown item type '{itype}' — changed to 'webpage'")
        itype = "webpage"
    spec = types[itype]
    clean: dict = {"itemType": itype}

    for key, value in item.items():
        if key in ("itemType", "creators"):
            continue
        if value in (None, "", [], {}):
            continue
        if key in spec["fields"]:
            clean[key] = value
        else:
            problems.append(f"field '{key}' not valid for {itype} — dropped")

    creators = []
    for c in item.get("creators") or []:
        if not isinstance(c, dict):
            continue
        ctype = c.get("creatorType") or spec["primaryCreator"]
        if ctype not in spec["creatorTypes"]:
            problems.append(f"creator type '{ctype}' not valid for {itype} — "
                            f"changed to '{spec['primaryCreator']}'")
            ctype = spec["primaryCreator"]
        if c.get("name"):
            creators.append({"creatorType": ctype, "name": str(c["name"]).strip()})
        elif c.get("lastName") or c.get("firstName"):
            creators.append({"creatorType": ctype,
                             "firstName": str(c.get("firstName", "")).strip(),
                             "lastName": str(c.get("lastName", "")).strip()})
    if creators:
        clean["creators"] = creators

    if not clean.get("title"):
        problems.append("no title")
    return clean, problems
