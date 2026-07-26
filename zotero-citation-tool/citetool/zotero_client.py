"""Zotero Web API v3 client. Handles the known gotchas:
- version-based concurrency: send If-Unmodified-Since-Version; on 412,
  re-fetch the library version and retry once
- max 50 items per write request
- honour Backoff / Retry-After headers
- collections are pointers, not containers: one canonical item, many
  collection memberships
The API key is held in memory only and never appears in any log or error."""

from __future__ import annotations

import time

import requests


class ZoteroError(Exception):
    pass


class ZoteroClient:
    def __init__(self, api_key: str, user_id: str = "",
                 base_url: str = "https://api.zotero.org", timeout: int = 30):
        self.base = base_url.rstrip("/")
        self.user_id = user_id
        self.timeout = timeout
        self._s = requests.Session()
        self._s.headers.update({"Zotero-API-Version": "3",
                                "Zotero-API-Key": api_key,
                                "User-Agent": "CiteTool/1.0"})
        self._backoff_until = 0.0

    # ---------------- low-level ----------------

    def _req(self, method: str, path: str, **kw) -> requests.Response:
        wait = self._backoff_until - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, 60))
        r = self._s.request(method, self.base + path, timeout=self.timeout, **kw)
        backoff = r.headers.get("Backoff") or (
            r.headers.get("Retry-After") if r.status_code in (429, 503) else None)
        if backoff:
            try:
                self._backoff_until = time.monotonic() + float(backoff)
            except ValueError:
                pass
        if r.status_code in (429, 503):
            time.sleep(min(float(r.headers.get("Retry-After", 5)), 60))
            r = self._s.request(method, self.base + path, timeout=self.timeout, **kw)
        return r

    def _lib(self) -> str:
        if not self.user_id:
            raise ZoteroError("user ID not set")
        return f"/users/{self.user_id}"

    def library_version(self) -> int:
        r = self._req("GET", self._lib() + "/items/top", params={"limit": 1, "format": "keys"})
        return int(r.headers.get("Last-Modified-Version", 0))

    # ---------------- setup / verification ----------------

    def key_info(self) -> dict:
        """Verify the key and derive userID + access rights from it."""
        r = self._req("GET", "/keys/current")
        if r.status_code in (401, 403):
            raise ZoteroError("Zotero rejected this key. Check you copied the whole key.")
        r.raise_for_status()
        info = r.json()
        self.user_id = str(info.get("userID", ""))
        return info

    def connection_summary(self) -> dict:
        """For the wizard: precise success or precise failure."""
        info = self.key_info()
        user_access = (info.get("access") or {}).get("user") or {}
        if not user_access.get("library"):
            raise ZoteroError("This key can't read your library — re-create it with "
                              "'Allow library access' ticked.")
        if not user_access.get("write"):
            raise ZoteroError("This key doesn't have write access ticked — re-create it "
                              "with 'Allow write access' ticked.")
        r = self._req("GET", self._lib() + "/items/top", params={"limit": 1})
        r.raise_for_status()
        return {"username": info.get("username", ""), "user_id": self.user_id,
                "item_count": int(r.headers.get("Total-Results", 0)), "write": True}

    # ---------------- reading (for dedup) ----------------

    def all_items(self, progress=None) -> list[dict]:
        """Every regular item's data (no attachments) for the dedup index."""
        items, start = [], 0
        while True:
            r = self._req("GET", self._lib() + "/items",
                          params={"format": "json", "itemType": "-attachment",
                                  "limit": 100, "start": start})
            r.raise_for_status()
            batch = r.json()
            items.extend(d["data"] for d in batch if "data" in d)
            total = int(r.headers.get("Total-Results", len(items)))
            if progress:
                progress(len(items), total)
            start += 100
            if start >= total or not batch:
                return items

    # ---------------- collections ----------------

    def _find_collection(self, name: str, parent: str | None) -> str | None:
        start = 0
        while True:
            r = self._req("GET", self._lib() + "/collections",
                          params={"limit": 100, "start": start})
            r.raise_for_status()
            for c in r.json():
                d = c["data"]
                if d["name"] == name and (d.get("parentCollection") or None) == parent:
                    return d["key"]
            total = int(r.headers.get("Total-Results", 0))
            start += 100
            if start >= total:
                return None

    def _create_collection(self, name: str, parent: str | None) -> str:
        body = [{"name": name, "parentCollection": parent or False}]
        for attempt in range(2):
            version = self.library_version()
            r = self._req("POST", self._lib() + "/collections", json=body,
                          headers={"If-Unmodified-Since-Version": str(version)})
            if r.status_code == 412 and attempt == 0:
                continue                      # stale version — refetch and retry
            r.raise_for_status()
            ok = r.json().get("successful", {})
            if "0" in ok:
                return ok["0"]["key"]
            raise ZoteroError(f"collection create failed: {r.json().get('failed')}")
        raise ZoteroError("collection create kept failing on version conflicts")

    def ensure_collections(self, doc_name: str,
                           parent_name: str = "Cited Documents") -> tuple[str, str]:
        """Reuses existing collections on re-runs — never 'Paper X (2)'."""
        parent = self._find_collection(parent_name, None) \
            or self._create_collection(parent_name, None)
        sub = self._find_collection(doc_name, parent) \
            or self._create_collection(doc_name, parent)
        return parent, sub

    # ---------------- writing ----------------

    def create_items(self, items: list[dict]) -> list[dict]:
        """Create items (each already carrying its 'collections' key so
        nothing lands loose). Returns one {key}|{error} per input item."""
        results: list[dict] = [None] * len(items)  # type: ignore
        for base in range(0, len(items), 50):      # API max 50 per request
            chunk = items[base:base + 50]
            for attempt in range(2):
                version = self.library_version()
                r = self._req("POST", self._lib() + "/items", json=chunk,
                              headers={"If-Unmodified-Since-Version": str(version)})
                if r.status_code == 412 and attempt == 0:
                    continue
                r.raise_for_status()
                body = r.json()
                for idx_s, obj in (body.get("successful") or {}).items():
                    results[base + int(idx_s)] = {"key": obj["key"]}
                for idx_s, obj in (body.get("unchanged") or {}).items():
                    key = obj if isinstance(obj, str) else obj.get("key", "")
                    results[base + int(idx_s)] = {"key": key}
                for idx_s, obj in (body.get("failed") or {}).items():
                    results[base + int(idx_s)] = {"error": obj.get("message", "unknown")}
                break
            else:
                for i in range(base, base + len(chunk)):
                    results[i] = {"error": "persistent version conflict (412)"}
        return results

    def add_item_to_collection(self, item_key: str, collection_key: str) -> None:
        r = self._req("GET", self._lib() + f"/items/{item_key}")
        r.raise_for_status()
        data = r.json()["data"]
        colls = data.get("collections") or []
        if collection_key in colls:
            return
        for attempt in range(2):
            r2 = self._req("PATCH", self._lib() + f"/items/{item_key}",
                           json={"collections": colls + [collection_key]},
                           headers={"If-Unmodified-Since-Version": str(data["version"])})
            if r2.status_code == 412 and attempt == 0:
                r = self._req("GET", self._lib() + f"/items/{item_key}")
                r.raise_for_status()
                data = r.json()["data"]
                colls = data.get("collections") or []
                if collection_key in colls:
                    return
                continue
            if r2.status_code not in (204, 200):
                raise ZoteroError(f"couldn't add item to collection (HTTP {r2.status_code})")
            return
