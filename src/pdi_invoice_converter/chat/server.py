"""Local support-agent service (stdlib only — no web framework dependency).

Runs on the always-on office server; members open it from their own machines.
The Windows-username auto-detect is SERVER-SIDE (the process runs as/near the
member), which a plain browser chat cannot do. The API/subscription stays on the
server, never on a member PC.

Run:  python -m pdi_invoice_converter.chat.server   (default http://127.0.0.1:8756)
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..config import Settings
from . import agent as agent_mod
from . import identity as ident
from .chatlog import log_event

_WEB = Path(__file__).resolve().parent / "web"
_SETTINGS = Settings.load()
_PENDING: dict = {}            # username -> pending action (in-process)


class Handler(BaseHTTPRequestHandler):
    server_version = "PDIInvoiceAssistant/1.0"

    def log_message(self, *args):  # quieter console
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            return {}

    # --- routes ---------------------------------------------------------- #
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            f = _WEB / "index.html"
            self._send(200, f.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/whoami":
            who = ident.resolve(settings=_SETTINGS)
            self._json(200, {"username": who.username, "name": who.name,
                             "role": who.role, "known": who.known})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/register":
            body = self._read_json()
            name = (body.get("name") or "").strip()
            if not name:
                return self._json(400, {"error": "name required"})
            who = ident.register_name(name, settings=_SETTINGS)
            log_event(who.username, "register", {"name": name}, _SETTINGS)
            self._json(200, {"username": who.username, "name": who.name,
                             "role": who.role, "known": who.known})
        elif self.path == "/api/chat":
            body = self._read_json()
            msg = (body.get("message") or "").strip()
            who = ident.resolve(settings=_SETTINGS)
            if not msg:
                return self._json(400, {"error": "message required"})
            resp = agent_mod.handle(who, msg, _SETTINGS, _PENDING)
            self._json(200, {
                "reply": resp.reply, "status_color": resp.status_color,
                "pending": resp.pending, "action": resp.action,
                "source": resp.source, "details": resp.details,
                "name": who.name, "role": who.role,
            })
        else:
            self._json(404, {"error": "not found"})


def serve(host: str = "127.0.0.1", port: int = 8756) -> None:
    who = ident.resolve(settings=_SETTINGS)
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"PDI Invoice Assistant chat agent -> http://{host}:{port}")
    print(f"Detected Windows user: {who.username}  (role: {who.role}, "
          f"{'known' if who.known else 'new — will ask name'})")
    print("Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    serve()
