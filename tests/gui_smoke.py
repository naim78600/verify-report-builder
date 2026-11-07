"""GUI smoke test - drives the REAL window (tkinter) against the mock server; run by CI on Windows / macOS / Linux (needs a display).

    python tests/gui_smoke.py

It uses a throw-away home folder, so nothing of the user's settings is touched.  Exit code 0 = every step passed.
"""
import os
import sys
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

HOME = tempfile.mkdtemp(prefix="vrb_gui_home_")
os.environ["HOME"] = os.environ["USERPROFILE"] = HOME                     # before report_builder is imported (settings live there)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

try:                                                                       # Windows consoles are cp1252: never die on Bengali text
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                          # noqa: BLE001
    pass

import tkinter as tk                                                       # noqa: E402
from tkinter import messagebox                                             # noqa: E402

import mock_server                                                         # noqa: E402
from report_builder import __version__, config                             # noqa: E402

STEPS = []


def step(name):
    STEPS.append(name)
    print(f"[gui-smoke] {name}", flush=True)


def fail(msg):
    print(f"[gui-smoke] FAILED: {msg}", flush=True)
    sys.exit(1)


shown = []                                                                 # message boxes the window tried to open (they would block)
for fn in ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel"):
    setattr(messagebox, fn, lambda *a, _f=fn, **k: shown.append((_f, a)) or True)


def pump(app, seconds=0.0, until=None, limit=120):
    end = time.time() + (seconds or limit)
    while time.time() < end:
        app.update()
        if until is not None and until():
            return True
        time.sleep(0.03)
    return until is None


def finished(app):
    return app.worker is not None and not app.worker.is_alive() and app.q.empty() and bool(app.out_files)


def main():
    from report_builder.gui import App
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    out = Path(tempfile.mkdtemp(prefix="vrb_gui_out_"))
    try:
        app = App()
    except tk.TclError as exc:
        fail(f"no display / Tk: {exc}")
    pump(app, 0.3)
    step("window opens")
    if __version__ not in app.title():
        fail("version missing in the window title")
    app.out_dir = out
    app.server.set(config.SERVER_CUSTOM)
    app.web.set(base)
    app.api.set(base)
    app.email.set("test@example.com")
    app.password.set("secret")
    app.rtype.set("tracker")
    app.rdate.var.set("02-11-2026")
    app.slot.set("7pm")
    for k in ("excel", "pdf"):
        app.opts[k].set(True)
    if "mail" in app.opts:
        app.opts["mail"].set(False)
    app._sync_ui()
    pump(app, 0.3)

    step("tracker run (Excel + PDF) through the window")
    app._go()
    if not pump(app, until=lambda: finished(app)):
        fail(f"tracker run did not finish; status: {app.status.get()!r}; boxes: {shown}")
    names = sorted(p.suffix for p in app.out_files)
    if ".xlsx" not in names or ".pdf" not in names:
        fail(f"outputs missing: {app.out_files}")
    if not all(p.exists() and p.stat().st_size > 2000 for p in app.out_files):
        fail("an output file is empty")
    if app.last_prime is None or not app.last_prime.complete:
        fail("no Complete rows from the mock scenario")
    if any(k == "showerror" for k, _a in shown):
        fail(f"an error box was shown: {shown}")

    step("e-mail window opens for the finished tracker")
    n0 = len([w for w in app.winfo_children() if isinstance(w, tk.Toplevel)])
    app._open_mail()
    pump(app, 0.5)
    tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    if len(tops) <= n0:
        fail("the e-mail window did not open")
    for w in tops:
        w.destroy()

    step("holiday list window opens")
    app._holiday_dialog()
    pump(app, 0.5)
    for w in [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]:
        w.destroy()

    step("range report through the window")
    app.rtype.set("range")
    app.period.set("range")
    app.d_from.var.set("20-10-2026")
    app.d_till.var.set("02-11-2026")
    app._sync_ui()
    pump(app, 0.3)
    if app.password.get():
        fail("the password stayed in the window after the run (it must be cleared)")
    app.password.set("secret")                                             # the window clears it after every run (by design)
    app.out_files = []
    app._go()
    if not pump(app, until=lambda: finished(app)):
        fail(f"range run did not finish; status: {app.status.get()!r}; boxes: {shown}")
    if ".xlsx" not in {p.suffix for p in app.out_files}:
        fail("range report has no Excel")

    step("settings saved without the password")
    sf = config.SETTINGS_FILE
    if sf.exists() and "secret" in sf.read_text(encoding="utf-8", errors="ignore"):
        fail("the password was written to disk")

    step("window closes")
    app.destroy()
    srv.shutdown()
    print(f"[gui-smoke] OK - {len(STEPS)} steps passed", flush=True)


if __name__ == "__main__":
    t = threading.Timer(400, lambda: (print("[gui-smoke] FAILED: timeout", flush=True), os._exit(1)))
    t.daemon = True
    t.start()
    main()
