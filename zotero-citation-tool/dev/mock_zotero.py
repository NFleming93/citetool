"""A mock Zotero Web API v3 for end-to-end testing without touching a
real library. Implements just enough: /keys/current, item listing,
collection find/create, batched item creation, PATCH collections —
including version headers and one deliberate 412 to prove retry works."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class State:
    def __init__(self):
        self.version = 100
        self.forced_412s = 1          # first item POST fails once
        self.items = {                # seeded duplicate: matches by URL
            "EXIST001": {"key": "EXIST001", "version": 90, "itemType": "webpage",
                         "title": "Claude — existing entry",
                         "url": "https://www.anthropic.com/claude",
                         "collections": []},
        }
        self.collections: dict[str, dict] = {}
        self.counter = 0

    def new_key(self, prefix):
        self.counter += 1
        return f"{prefix}{self.counter:05d}"


def make_handler(state: State):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):   # keep test output clean
            pass

        def _send(self, code, body=None, headers=None):
            self.send_response(code)
            self.send_header("Last-Modified-Version", str(state.version))
            self.send_header("Content-Type", "application/json")
            payload = json.dumps(body).encode() if body is not None else b""
            if headers:
                for k, v in headers.items():
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _body(self):
            n = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(n)) if n else None

        def do_GET(self):
            if self.path.startswith("/keys/current"):
                self._send(200, {"userID": 1, "username": "testuser",
                                 "access": {"user": {"library": True, "write": True}}})
            elif re.match(r"^/users/1/items/top", self.path):
                self._send(200, [], {"Total-Results": str(len(state.items))})
            elif m := re.match(r"^/users/1/items/(\w+)$", self.path):
                it = state.items.get(m.group(1))
                self._send(200, {"key": it["key"], "data": it}) if it else self._send(404)
            elif self.path.startswith("/users/1/items"):
                data = [{"key": k, "data": v} for k, v in state.items.items()]
                self._send(200, data, {"Total-Results": str(len(data))})
            elif self.path.startswith("/users/1/collections"):
                data = [{"key": k, "data": v} for k, v in state.collections.items()]
                self._send(200, data, {"Total-Results": str(len(data))})
            else:
                self._send(404)

        def do_POST(self):
            sent_version = int(self.headers.get("If-Unmodified-Since-Version", -1))
            if self.path.startswith("/users/1/collections"):
                if sent_version != state.version:
                    return self._send(412)
                body = self._body()
                ok = {}
                for i, c in enumerate(body):
                    key = state.new_key("COL")
                    parent = c.get("parentCollection") or None
                    if parent is False:
                        parent = None
                    state.collections[key] = {"key": key, "name": c["name"],
                                              "parentCollection": parent}
                    ok[str(i)] = {"key": key}
                state.version += 1
                self._send(200, {"successful": ok, "failed": {}})
            elif self.path.startswith("/users/1/items"):
                if state.forced_412s > 0:
                    state.forced_412s -= 1
                    return self._send(412)          # deliberate conflict once
                if sent_version != state.version:
                    return self._send(412)
                body = self._body()
                ok, failed = {}, {}
                if len(body) > 50:
                    return self._send(400, {"error": "max 50 items"})
                for i, item in enumerate(body):
                    if not item.get("title"):
                        failed[str(i)] = {"code": 400, "message": "title required"}
                        continue
                    key = state.new_key("ITEM")
                    stored = dict(item)
                    stored.update({"key": key, "version": state.version + 1})
                    state.items[key] = stored
                    ok[str(i)] = {"key": key}
                state.version += 1
                self._send(200, {"successful": ok, "unchanged": {}, "failed": failed})
            else:
                self._send(404)

        def do_PATCH(self):
            m = re.match(r"^/users/1/items/(\w+)$", self.path)
            if not m or m.group(1) not in state.items:
                return self._send(404)
            item = state.items[m.group(1)]
            if int(self.headers.get("If-Unmodified-Since-Version", -1)) != item["version"]:
                return self._send(412)
            item.update(self._body())
            state.version += 1
            item["version"] = state.version
            self._send(204)

    return H


def start(port: int = 0) -> tuple[ThreadingHTTPServer, State, str]:
    state = State()
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state, f"http://127.0.0.1:{server.server_address[1]}"
