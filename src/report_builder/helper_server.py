"""v10: a tiny local server the WhatsApp Web helper (browser extension) talks to.

Listens on 127.0.0.1 only (never reachable from another computer).  Only the helper extension may call it: a request
that carries a web page's Origin (any https://... site) is refused, so no website can read the reminder list.

  GET  /ping              -> {"ok": true}
  GET  /round             -> the prepared round: [{phone, verifier, text, voice, sent}]  (unsent first)
  GET  /voice/<name>      -> the voice clip (assets/voices/<name>.ogg)
  POST /sent   {phone}    -> marks that verifier's message as sent (Naim pressed Send)
  POST /reply  {phone, text, at}   -> a reply read from WhatsApp Web; understood by reminders.parse_reply
  POST /contact {name, phone}      -> the chat name WhatsApp shows for that number (to read replies from the chat list)
  GET  /asks               -> V12 follow-ups: messages to send ("send the slip photo", "write the problem") and photo waits
  POST /ask_sent {phone}   -> Naim pressed Send on a follow-up
  POST /media {phone, b64, type, msg}  -> a photo the verifier sent after "জমা দিয়েছি": saved in
                              <reports folder>/BS Slips/<date>/<Trip ID> - <verifier>/  and the BS marked "handed in at the bank"
Nothing is sent to WhatsApp from here; the helper only fills the message box and attaches the clip.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
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
        self.ext_seen = 0.0                 # when the Chrome helper last asked for something (time.time())
        self.ext_version = ""
        self.start_token: str | None = None  # "Start sending" pressed in the program: the first WhatsApp tab takes it
        self.start_until = 0.0
        self.httpd: ThreadingHTTPServer | None = None
        self.slips_dir: Path | None = None   # <reports folder>/BS Slips (the program sets it; default: the default reports folder)

    # ------------------------------------------------------------------ the Chrome helper
    @property
    def extension_connected(self) -> bool:
        """True while a WhatsApp Web tab with the helper is open (it asks every few seconds)."""
        return time.time() - self.ext_seen < 45

    def request_start(self) -> str:
        """The program's 'Start sending' button: valid for 3 minutes, taken by one tab only."""
        self.start_token = f"{time.time():.3f}"
        self.start_until = time.time() + 180
        return self.start_token

    def pending_start(self) -> str | None:
        return self.start_token if self.start_token and time.time() < self.start_until else None

    def claim_start(self, token: str) -> bool:
        with self.lock:
            if token and token == self.pending_start():
                self.start_token = None
                return True
            return False

    # ------------------------------------------------------------------ data
    def current_items(self) -> list[dict]:
        with self.lock:
            st = R.load_state()
            ds = R.day_state(st)
            rk = self.round_key or (sorted(ds["rounds"], key=lambda k: ds["rounds"][k]["prepared"])[-1] if ds["rounds"] else None)
            if not rk:
                return []
            items = ds["rounds"][rk]["items"]
            from . import voice as V
            out = [{"phone": i["phone"], "verifier": i["verifier"], "text": i["text"], "sent": bool(i.get("sent")),
                    "voice": i["voice"] if (V.clip_path(i["voice"]).exists() or asset("voices", i["voice"] + ".ogg").is_file()) else "",
                    "round": rk, "code": i.get("code", ""), "priority": R.PRIORITY_TEXT.get(i.get("priority"), "")} for i in items]
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

    # ------------------------------------------------------------------ V12 follow-ups and slip photos
    def asks(self) -> list[dict]:
        with self.lock:
            st = R.load_state()
            names = {i["phone"]: i["verifier"] for d in st.get("days", {}).values() for rd in d.get("rounds", {}).values()
                     for i in rd.get("items", [])}
            return [{**a, "verifier": names.get(a["phone"], a["phone"])} for a in R.open_asks(st)]

    def ask_sent(self, phone: str) -> bool:
        with self.lock:
            st = R.load_state()
            a = st.get("asks", {}).get(phone)
            if not a:
                return False
            from datetime import datetime
            a["sent"] = datetime.now().isoformat(timespec="minutes")
            R.save_state(st)
            return True

    def save_media(self, phone: str, b64: str, ctype: str, msg: str = "") -> dict:
        """A slip photo after "জমা দিয়েছি": one copy per BS trip of that answer, in a folder people can open."""
        import base64
        from datetime import datetime
        from . import bs_tracker as BT
        from . import config
        with self.lock:
            st = R.load_state()
            a = st.get("asks", {}).get(phone)
            if not a or a.get("want") != "photo":
                return {"ignored": True}
            if a.get("answered") and (datetime.now() - datetime.fromisoformat(a["answered"])).total_seconds() > 6 * 3600:
                return {"ignored": True, "why": "old answer"}         # more slips are taken for 6 hours after the first one
            seen = a.setdefault("msgs", [])
            if msg and msg in seen:
                return {"ignored": True, "why": "already saved"}
            try:
                data = base64.b64decode(b64.split(",", 1)[-1], validate=False)
            except ValueError:
                return {"error": "bad picture"}
            if len(data) < 500:
                return {"error": "too small"}
            ext = ".png" if "png" in (ctype or "") else ".webp" if "webp" in (ctype or "") else ".jpg"
            item = R.find_item(st, a.get("code", "")) or {}
            who = "".join(ch for ch in (item.get("verifier") or phone) if ch.isalnum() or ch in " .-_").strip() or phone
            now = datetime.now()
            base = (self.slips_dir or config.default_output_dir() / "BS Slips") / f"{now:%Y-%m-%d}"
            saved = []
            store = BT.load_store()
            for tid in a.get("trips") or ["no-trip"]:
                folder = base / f"{tid} - {who}"
                folder.mkdir(parents=True, exist_ok=True)
                p = folder / f"slip {now:%H%M%S}{ext}"
                n = 2
                while p.exists():
                    p = folder / f"slip {now:%H%M%S} ({n}){ext}"
                    n += 1
                p.write_bytes(data)
                saved.append(str(p))
                if tid != "no-trip":
                    BT.set_bank_submitted(store, tid, photos=[p], verifier=item.get("verifier", ""))
            BT.save_store(store)
            if msg:
                seen.append(msg)
            a.setdefault("answered", now.isoformat(timespec="minutes"))
            a["photos"] = a.get("photos", []) + saved
            R.save_state(st)
        self.on_event("media", {"phone": phone, "files": saved})
        return {"ok": True, "files": saved}

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
                if origin.startswith("chrome-extension://") or origin.startswith("moz-extension://") or (origin == "" and "v=" in self.path):
                    was = srv.extension_connected
                    srv.ext_seen = time.time()
                    if "v=" in self.path:
                        srv.ext_version = self.path.split("v=", 1)[1].split("&")[0][:20]
                    if not was:
                        srv.on_event("connected", {})
                self.path = self.path.split("?")[0]
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
                cap = 20_000_000 if self.path == "/media" else 100_000          # a slip photo can be a few MB
                n = min(int(self.headers.get("Content-Length") or 0), cap)
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
                    return self._send(200, {"items": srv.current_items(), "contacts": srv.contacts(), "start": srv.pending_start()})
                if self.path == "/asks":
                    return self._send(200, {"asks": srv.asks()})
                if self.path.startswith("/voice/"):
                    name = self.path.split("/voice/", 1)[1].split("?")[0]
                    if not name.replace("_", "").isalnum():
                        return self._send(404, {"error": "no such clip"})
                    from . import voice as V
                    if V.clip_path(name).is_file():
                        return self._send(200, V.clip_path(name).read_bytes(), "audio/mpeg")
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
                if self.path == "/claim":
                    return self._send(200, {"ok": srv.claim_start(str(body.get("token", "")))})
                if self.path == "/sent":
                    return self._send(200, {"ok": srv.mark_sent(str(body.get("phone", "")))})
                if self.path == "/reply":
                    return self._send(200, srv.add_reply(str(body.get("phone", "")), str(body.get("text", "")), body.get("at")))
                if self.path == "/ask_sent":
                    return self._send(200, {"ok": srv.ask_sent(str(body.get("phone", "")))})
                if self.path == "/media":
                    return self._send(200, srv.save_media(str(body.get("phone", "")), str(body.get("b64", "")),
                                                          str(body.get("type", "")), str(body.get("msg", ""))))
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


# ====================================================================================== the Chrome helper's folder
def helper_folder() -> Path:
    """A folder that stays in one place (~/.verify_report_builder/whatsapp_helper) with the newest helper files.
    Chrome's "Load unpacked" must point at a folder that does not move: the program's own copy sits in a temporary
    folder (Windows) or inside the .app (Mac) and changes with every update."""
    import shutil
    from . import config
    src, dst = asset("whatsapp_helper"), config.SETTINGS_DIR / "whatsapp_helper"
    try:
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file() and (not (dst / f.name).exists() or (dst / f.name).read_bytes() != f.read_bytes()):
                shutil.copyfile(f, dst / f.name)
    except OSError:
        return src
    return dst


def helper_version() -> str:
    try:
        return json.loads((asset("whatsapp_helper") / "manifest.json").read_text(encoding="utf-8"))["version"]
    except Exception:
        return ""


def open_chrome_extensions() -> bool:
    """Opens Chrome's extensions page (the one place where the helper is added).  False = could not; open it by hand."""
    import subprocess
    import sys
    url = "chrome://extensions"
    try:
        if sys.platform == "darwin":
            return subprocess.call(["open", "-a", "Google Chrome", url]) == 0
        if sys.platform.startswith("win"):
            subprocess.Popen(["cmd", "/c", "start", "", "chrome", url], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return True
        subprocess.Popen(["google-chrome", url])
        return True
    except Exception:
        return False
