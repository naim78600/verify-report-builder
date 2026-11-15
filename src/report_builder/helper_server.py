"""v10: a tiny local server the WhatsApp Web helper (browser extension) talks to.

Listens on 127.0.0.1 only (never reachable from another computer).  Only the helper extension may call it: a request
that carries a web page's Origin (any https://... site) is refused, so no website can read the reminder list.

  GET  /ping              -> {"ok": true}
  GET  /round             -> the prepared round: [{phone, verifier, text, voice, sent}]  (unsent first)
  GET  /voice/<name>      -> the voice clip (assets/voices/<name>.ogg)
  POST /sent   {phone}    -> marks that verifier's message as sent (Naim pressed Send)
  POST /reply  {phone, text, at}   -> a reply read from WhatsApp Web; understood by reminders.parse_reply
  POST /contact {name, phone}      -> the chat name WhatsApp shows for that number (to read replies from the chat list)
Nothing is sent to WhatsApp from here; the helper only fills the message box and attaches the clip.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from . import reminders as R
from .assets_path import asset

PORT = 47321


class HelperServer:
    def __init__(self, on_event: Callable[[str, dict], None] | None = None, port: int = PORT):
        self.on_event = on_event or (lambda *_a: None)
        self.port = port
        self.lock = threading.Lock()
        self.round_key: str | None = None
        self.httpd: ThreadingHTTPServer | None = None

    # ------------------------------------------------------------------ data
    def current_items(self) -> list[dict]:
        with self.lock:
            st = R.load_state()
            ds = R.day_state(st)
            rk = self.round_key or (sorted(ds["rounds"], key=lambda k: ds["rounds"][k]["prepared"])[-1] if ds["rounds"] else None)
            if not rk:
                return []
            items = ds["rounds"][rk]["items"]
            out = [{"phone": i["phone"], "verifier": i["verifier"], "text": i["text"], "voice": i["voice"], "sent": bool(i.get("sent")),
                    "round": rk, "priority": R.PRIORITY_TEXT.get(i.get("priority"), "")} for i in items]
            out.sort(key=lambda i: i["sent"])
            return out

    def contacts(self) -> dict:
        st = R.load_state()
        return st.get("contacts", {})

    def mark_sent(self, phone: str) -> bool:
        with self.lock:
            st = R.load_state()
            ds = R.day_state(st)
            rk = self.round_key or (sorted(ds["rounds"], key=lambda k: ds["rounds"][k]["prepared"])[-1] if ds["rounds"] else None)
            ok = False
            if rk:
                for i in ds["rounds"][rk]["items"]:
                    if i["phone"] == phone and not i.get("sent"):
                        from datetime import datetime
                        i["sent"] = datetime.now().isoformat(timespec="minutes")
                        ok = True
            R.save_state(st)
        if ok:
            self.on_event("sent", {"phone": phone})
        return ok

    def add_reply(self, phone: str, text: str, at: str | None) -> dict:
        with self.lock:
            st = R.load_state()
            known = {i["phone"] for d in st.get("days", {}).values() for rd in d.get("rounds", {}).values() for i in rd.get("items", [])}
            if phone not in known:
                return {"ignored": True}
            e = R.record_reply(st, phone, text, at)
            R.save_state(st)
        self.on_event("reply", e)
        return e

    def add_contact(self, name: str, phone: str) -> None:
        with self.lock:
            st = R.load_state()
            st.setdefault("contacts", {})[name[:80]] = phone
            R.save_state(st)

    # ------------------------------------------------------------------ http
    def start(self) -> bool:
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *_a):           # quiet
                pass

            def _allowed(self) -> bool:
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return False
                origin = self.headers.get("Origin") or ""
                return origin == "" or origin.startswith("chrome-extension://") or origin.startswith("moz-extension://")

            def _send(self, code: int, body, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def _json(self) -> dict:
                n = min(int(self.headers.get("Content-Length") or 0), 100_000)
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return {}

            def do_GET(self):
                if not self._allowed():
                    return self._send(403, {"error": "forbidden"})
                if self.path == "/ping":
                    from . import __version__
                    return self._send(200, {"ok": True, "app": "Verify Report Builder", "version": __version__})
                if self.path == "/round":
                    return self._send(200, {"items": srv.current_items(), "contacts": srv.contacts()})
                if self.path.startswith("/voice/"):
                    name = self.path.split("/voice/", 1)[1].split("?")[0]
                    if not name.replace("_", "").isalnum():
                        return self._send(404, {"error": "no such clip"})
                    for ext, ctype in ((".ogg", "audio/ogg"), (".mp3", "audio/mpeg"), (".wav", "audio/wav")):
                        p = asset("voices", name + ext)
                        if p.is_file():
                            return self._send(200, p.read_bytes(), ctype)
                    return self._send(404, {"error": "no such clip"})
                return self._send(404, {"error": "not found"})

            def do_POST(self):
                if not self._allowed():
                    return self._send(403, {"error": "forbidden"})
                body = self._json()
                if self.path == "/sent":
                    return self._send(200, {"ok": srv.mark_sent(str(body.get("phone", "")))})
                if self.path == "/reply":
                    return self._send(200, srv.add_reply(str(body.get("phone", "")), str(body.get("text", "")), body.get("at")))
                if self.path == "/contact":
                    srv.add_contact(str(body.get("name", "")), str(body.get("phone", "")))
                    return self._send(200, {"ok": True})
                return self._send(404, {"error": "not found"})

        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        except OSError:
            return False                                   # another copy of the program already runs the helper server
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return True

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd = None
