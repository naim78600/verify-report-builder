"""GUI smoke test - drives the REAL window (tkinter) against the mock server; run by CI on Windows / macOS / Linux (needs a display).

    python tests/gui_smoke.py

It uses a throw-away home folder, so nothing of the user's settings is touched.  Exit code 0 = every step passed.
"""
import os
import sys
import tempfile
import threading
import time
from datetime import date, datetime
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


SHOTS = os.environ.get("VRB_SHOTS")                                        # folder: save a picture of every page (CI artifact)


def shot(app, name):
    if not SHOTS:
        return
    import subprocess
    pump(app, 0.6)
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["import", "-window", "root", str(Path(SHOTS) / f"{name}.png")], timeout=20, check=False)
    except Exception as exc:                                               # noqa: BLE001
        print("[gui-smoke] (no screenshot)", exc)


def main():
    from report_builder.shell import Shell
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    out = Path(tempfile.mkdtemp(prefix="vrb_gui_out_"))
    try:
        shell = Shell(start_helper=False)
    except tk.TclError as exc:
        fail(f"no display / Tk: {exc}")
    shell.geometry("1280x800+0+0")
    pump(shell, 0.3)
    step("opening screen: language + sign-in")
    if __version__ not in shell.title():
        fail("version missing in the window title")
    shot(shell, "00_open_bn")
    shell._pick_lang("en")
    pump(shell, 0.2)
    shot(shell, "01_open_en")
    shell._pick_lang("bn")
    shell.server.set(config.SERVER_CUSTOM)
    shell._urls()
    shell.web.set(base)
    shell.api.set(base)
    shell.email.set("test@example.com")
    shell.password.set("wrong")
    shell.sign_in()
    if not pump(shell, until=lambda: bool(shell.login_msg.cget("text")) and shell.login_btn._on, limit=30):
        fail("a wrong password gave no message")
    shell.password.set("secret")
    shell.sign_in()
    if not pump(shell, until=lambda: shell.signed_in and "reports" in shell.pages, limit=60):
        fail(f"sign-in did not open the main window: {shell.login_msg.cget('text')!r}")
    step("main window; dashboard read (both clients) + verifier numbers")
    if not pump(shell, until=lambda: shell.data["at"] is not None, limit=120):
        fail("the dashboard was not read")
    if not shell.data["phones"] or "admin_access_token" in repr(shell.data["phones"]):
        fail(f"verifier numbers wrong: {shell.data['phones']}")
    for key in ("home", "tracker", "bill", "bs", "receive", "reminders", "verifiers", "history", "settings"):
        shell.show(key)
        shot(shell, f"bn_{key}")
    step("BS tracker lists the bank statements of the scenario")
    shell.show("bs")
    bsp = shell.pages["bs"]
    bsp.month.set("2026-11")
    bsp.refresh()
    if not bsp.rows:
        bsp.month.set("2026-10")
        bsp.refresh()
    if not bsp.rows:
        fail("no BS rows on the BS page")
    shell.update()
    if not bsp.who.get_children() or not bsp.who.winfo_ismapped():
        fail("the 'who still holds a BS' table is empty or not shown")
    bsp.toggle_all()
    shell.update()
    if not bsp.full.winfo_ismapped() or not bsp.tv.get_children():
        fail("'see every BS' did not open the full list")
    shot(shell, "bn_bs_all")
    bsp.toggle_all()
    step("Today: one job card + On Going / Hold / SLA passed")
    shell.show("home")
    hp = shell.pages["home"]
    hp.refresh()
    if not hp.now_what.cget("text") or hp.k_go.value.cget("text") == "–":
        fail("the Today page did not fill in")
    shell.show("settings")
    shell.pages["settings"].own.set("01700000099")
    shell.pages["settings"].save_own()
    if shell.settings.get("own_whatsapp") != "8801700000099":
        fail(f"own WhatsApp number not saved: {shell.settings.get('own_whatsapp')!r}")
    p = out / "bs.xlsx"
    from report_builder import bs_tracker as BT
    BT.write_bs_excel(bsp.rows, p, "smoke")
    shot(shell, "bn_bs_rows")
    step("office receive: add one by Trip ID, A4 sheet")
    rcv = shell.pages["receive"]
    shell.show("receive")
    rcv.key.set(str(bsp.rows[0].trip_id))
    rcv.pages_v.set("5")
    rcv.add()
    if not rcv.tv.get_children():
        fail("the receive was not listed")
    BT.write_receive_sheet(BT.load_store(), out / "today.xlsx")
    shot(shell, "bn_receive_added")
    step("reminder round prepared")
    shell.prepare_round("1pm")
    from report_builder import reminders as R
    its = R.day_state(R.load_state())["rounds"]["1pm"]["items"]
    if its and "wa.me/8801700000099" not in its[0]["text"]:
        fail("the answer links (own number) are missing in the reminder")
    shell.show("reminders")
    shot(shell, "bn_reminders_round")
    rp = shell.pages["reminders"]
    rp.toggle_list()
    shell.update()
    if not rp.list_box.winfo_ismapped():
        fail("the reminder list did not open")
    shot(shell, "bn_reminders_list")
    rp.toggle_list()
    rp._waiting_since = datetime(2020, 1, 1)          # WhatsApp opened long ago, no helper answered -> the setup box shows
    rp._connection()
    shell.update()
    if not rp.setup_box.winfo_ismapped():
        fail("the 'add the helper' box did not show")
    shot(shell, "bn_reminders_no_helper")
    import time as _t
    shell.helper.ext_seen = _t.time()                 # the helper answered -> the box goes, the status turns green
    rp._connection()
    shell._status()
    shell.update()
    if rp.setup_box.winfo_ismapped():
        fail("the 'add the helper' box stayed after the helper connected")
    step("English screens")
    shell.pages["settings"].shell.lang.set("en")
    shell.pages["settings"].lang_changed()
    for key in ("home", "tracker", "bs", "receive", "reminders", "verifiers", "settings"):
        shell.show(key)
        shot(shell, f"en_{key}")
    shell.pages["settings"].shell.lang.set("bn")
    shell.pages["settings"].lang_changed()
    app = shell.reports
    shell.show("tracker")
    app.out_dir = out
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
    if not app.password.get():
        fail("v10: the password must stay in memory while the program is open (scheduled jobs need it)")
    app.out_files = []
    app._go()
    if not pump(app, until=lambda: finished(app)):
        fail(f"range run did not finish; status: {app.status.get()!r}; boxes: {shown}")
    if ".xlsx" not in {p.suffix for p in app.out_files}:
        fail("range report has no Excel")

    step("monthly bill through the window (October 2026: Card + Loan, Excel + PDF)")
    app.rtype.set("bill")
    app.bill_month.set("October")
    app.bill_year.set("2026")
    app._sync_ui()
    pump(app, 0.3)
    if not app.c_bill.winfo_ismapped():
        fail("the month card is not shown for the monthly bill")
    app.password.set("secret")
    app.out_files = []
    app._go()
    if not pump(app, until=lambda: finished(app)):
        fail(f"monthly bill did not finish; status: {app.status.get()!r}; boxes: {shown}")
    names = sorted(p.name for p in app.out_files)
    if names != ["Prime_Bank_PLC_Card_Invoice_October_2026.pdf", "Prime_Bank_PLC_Card_Invoice_October_2026.xlsx",
                 "Prime_Bank_PLC_Card_Mushak6.3_October_2026.pdf",
                 "Prime_Bank_PLC_Loan_Invoice_October_2026.pdf", "Prime_Bank_PLC_Loan_Invoice_October_2026.xlsx",
                 "Prime_Bank_PLC_Loan_Mushak6.3_October_2026.pdf"]:          # V15: + Mushak-6.3
        fail(f"monthly bill files: {names}; status: {app.status.get()!r}")
    from report_builder.bill_out import read_bill_excel
    loan = read_bill_excel(next(p for p in app.out_files if p.name.startswith("Prime_Bank_PLC_Loan") and p.suffix == ".xlsx"))
    if len(loan.items) != 6 or loan.subtotal != 1860:                    # v7: the package's two documents are own rows
        fail(f"monthly Loan bill: {len(loan.items)} rows, subtotal {loan.subtotal} (expected 6 rows, 1860)")

    step("file history through the window (input Excel = File No + Applicant Name, every file found)")
    from openpyxl import load_workbook
    from report_builder.file_history import parse_ids_file
    from report_builder.history_excel import write_history_template
    tpl = out / "File_History_Format.xlsx"
    write_history_template(tpl)                                            # the template the window offers
    wb = load_workbook(tpl)
    ws = wb["File History"]
    ws["A2"], ws["B2"] = "PL-20261026000001", "alpha one"
    ws["A3"], ws["B3"] = "CC-20261101000002", "Gamma Two"
    wb.save(tpl)
    app.hist_ids = parse_ids_file(tpl)
    if [e.name for e in app.hist_ids] != ["alpha one", "Gamma Two"]:
        fail(f"names not read from the input Excel: {[e.name for e in app.hist_ids]}")
    app.rtype.set("history")
    app._sync_ui()
    pump(app, 0.3)
    app.password.set("secret")
    app.out_files = []
    shown.clear()
    app._go()
    if not pump(app, until=lambda: finished(app)):
        fail(f"file history did not finish; status: {app.status.get()!r}; boxes: {shown}")
    if any(k == "showerror" for k, _a in shown):
        fail(f"an error box was shown for the file history: {shown}")
    hx = [p for p in app.out_files if p.suffix == ".xlsx"]
    if not hx:
        fail("file history has no Excel")
    hwb = load_workbook(hx[0])
    if "Not Found" not in hwb.sheetnames or "Applicant Name (given)" not in [c.value for c in hwb["Summary"][3]]:
        fail(f"file history workbook is incomplete: {hwb.sheetnames}")

    step("settings saved without the password")
    sf = config.SETTINGS_FILE
    if sf.exists() and "secret" in sf.read_text(encoding="utf-8", errors="ignore"):
        fail("the password was written to disk")

    step("window closes")
    shell._close()
    srv.shutdown()
    print(f"[gui-smoke] OK - {len(STEPS)} steps passed", flush=True)


if __name__ == "__main__":
    t = threading.Timer(400, lambda: (print("[gui-smoke] FAILED: timeout", flush=True), os._exit(1)))
    t.daemon = True
    t.start()
    main()
