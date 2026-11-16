"""v10 main window: opening screen (language + sign-in), white side bar, pages.

Pages: Today (home) · Daily Tracker · Monthly Bill · File History (the v1-v7 report page, same rules) · BS Tracker ·
Office receive · Reminders (WhatsApp) · Verifiers · Settings.

Background work (only while the program is open, office days, 10:00 AM - 6:15 PM; nothing is done when the PC is off,
the latest missed job runs when it is opened again):
  10:00 AM, 1:00 PM, 4:00 PM  -> reminder round prepared (reminders.py); Naim sends it from WhatsApp Web with the helper
  12:00 PM, 6:15 PM           -> BS check (every pending bank statement) + "time for the daily tracker" note
The dashboard is only read.  The password stays in memory while the program is open; it is never written to disk.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime, time
from pathlib import Path
from tkinter import messagebox, ttk

from . import __version__, config, i18n
from . import reminders as R
from .bs_tracker import bs_rows, load_store, pending_bs
from .client import ApiError, AuthError, Cancelled, ReadOnlyClient, verifier_phones
from .collect import RunConfig, collect
from .helper_server import HelperServer, helper_folder, helper_version
from .i18n import L, error_text
from .ui_kit import Button, Entry, Fonts, P, pick_font_family

CLIENTS = ["Prime Bank PLC", "LankaBangla Finance Limited"]
BS_CHECKS = [("12pm", time(12, 0)), ("615pm", time(18, 15))]
LOOKBACK_DAYS = 90


def nav_items():
    return [
        ("home", L("আজ", "Today"), "⌂"),
        ("tracker", L("দৈনিক ট্র্যাকার", "Daily Tracker"), "▤"),
        ("bill", L("মাসিক বিল", "Monthly Bill"), "▭"),
        ("bs", L("BS ট্র্যাকার", "BS Tracker"), "🏦"),
        ("receive", L("অফিস রিসিভ", "Office receive"), "📥"),
        ("reminders", L("রিমাইন্ডার", "Reminders"), "💬"),
        ("-", L("তথ্য", "Info"), ""),
        ("verifiers", L("ভেরিফায়ার", "Verifiers"), "👥"),
        ("history", L("ফাইল হিস্টরি", "File History"), "🕘"),
        ("settings", L("সেটিংস", "Settings"), "⚙"),
    ]


class Shell(tk.Tk):
    def __init__(self, start_helper: bool = True):
        super().__init__()
        self.title(f"{config.APP_NAME} {__version__}")
        self.configure(bg=P["bg"])
        self.settings = config.load_settings()
        i18n.set_lang(self.settings.get("lang", "bn"))
        self.fonts = Fonts(self, pick_font_family(self))
        self._tune()
        self.server = tk.StringVar(value=self.settings.get("server", config.SERVER_PRODUCTION))
        self.web = tk.StringVar(value=self.settings.get("web", ""))
        self.api = tk.StringVar(value=self.settings.get("api", ""))
        self.email = tk.StringVar(value=self.settings.get("email", ""))
        self.password = tk.StringVar()
        self.lang = tk.StringVar(value=i18n.LANG)
        self.out_dir = Path(self.settings.get("out_dir") or config.default_output_dir())
        self.q: queue.Queue = queue.Queue()
        self.jobs: set = set()
        self.data = {"files": {}, "phones": {}, "at": None, "bs": []}
        self.pages: dict = {}
        self.signed_in = False
        self.helper = HelperServer(lambda k, e: self.q.put(("helper", k, e)))
        self.helper_running = self.helper.start() if start_helper else False
        self.helper_dir = helper_folder()            # fixed folder for Chrome's "Load unpacked", always the newest files
        st = R.load_state()
        R.NO_WA_CACHE.update(st.get("no_whatsapp", {}).keys())
        self.geometry(self.settings.get("geometry") or "1280x800")
        self.minsize(1100, 700)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.root = tk.Frame(self, bg=P["bg"])
        self.root.pack(fill="both", expand=True)
        self.login_screen()
        self.after(150, self._poll)
        self.after(30_000, self._tick)

    def _tune(self):
        import tkinter.font as tkfont
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=self.fonts.family, size=11)
            except tk.TclError:
                pass
        st = ttk.Style(self)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground=P["text"], rowheight=32,
                     font=(self.fonts.family, 10), borderwidth=0)
        st.configure("Treeview.Heading", background="#F9FAFB", foreground=P["mute"], font=(self.fonts.family, 10, "bold"),
                     relief="flat", padding=(6, 7))
        st.map("Treeview", background=[("selected", P["accent_soft"])], foreground=[("selected", P["text"])])
        st.configure("TCombobox", padding=4)

    # ================================================================== opening screen (every start)
    def login_screen(self):
        for w in self.root.winfo_children():
            w.destroy()
        f = self.fonts
        wrap = tk.Frame(self.root, bg=P["bg"])
        wrap.place(relx=0.5, rely=0.45, anchor="center")
        card = tk.Frame(wrap, bg=P["card"], highlightbackground=P["line"], highlightthickness=1, padx=34, pady=28)
        card.pack()
        top = tk.Frame(card, bg=P["card"])
        top.pack(fill="x")
        tk.Label(top, text="V", bg=P["accent"], fg="white", font=f.title, width=2).pack(side="left")
        box = tk.Frame(top, bg=P["card"])
        box.pack(side="left", padx=12)
        tk.Label(box, text="Verify Report Builder", bg=P["card"], fg=P["text"], font=f.h2).pack(anchor="w")
        tk.Label(box, text=f"Barikoi · v{__version__}", bg=P["card"], fg=P["mute"], font=f.small).pack(anchor="w")
        # language first - asked every time the program opens, the last choice is pre-selected
        tk.Label(card, text="ভাষা বাছুন  ·  Choose language", bg=P["card"], fg=P["text"], font=f.h3).pack(anchor="w", pady=(22, 6))
        lrow = tk.Frame(card, bg=P["card"])
        lrow.pack(fill="x")
        self._lang_btns = {}
        for code, text in (("bn", "বাংলা"), ("en", "English")):
            b = tk.Label(lrow, text=text, font=f.big, padx=26, pady=10, cursor="hand2")
            b.pack(side="left", padx=(0, 10))
            b.bind("<Button-1>", lambda _e, c=code: self._pick_lang(c))
            self._lang_btns[code] = b
        self._paint_lang()
        self.login_form = tk.Frame(card, bg=P["card"])
        self.login_form.pack(fill="x", pady=(18, 0))
        self._login_fields()

    def _pick_lang(self, code):
        self.lang.set(code)
        i18n.set_lang(code)
        self._paint_lang()
        self._login_fields()

    def _paint_lang(self):
        for code, b in self._lang_btns.items():
            on = self.lang.get() == code
            b.config(bg=P["accent"] if on else "#F3F4F6", fg="white" if on else P["text"])

    def _login_fields(self):
        f = self.fonts
        for w in self.login_form.winfo_children():
            w.destroy()
        frm = self.login_form

        def row(label, widget_fn):
            r = tk.Frame(frm, bg=P["card"])
            r.pack(fill="x", pady=5)
            tk.Label(r, text=label, bg=P["card"], fg=P["mute"], font=f.small, width=12, anchor="w").pack(side="left")
            w = widget_fn(r)
            w.pack(side="left", fill="x", expand=True, ipady=4)
            return w
        cb = row(L("সার্ভার", "Server"), lambda r: ttk.Combobox(r, textvariable=self.server, values=config.SERVER_CHOICES,
                                                                 state="readonly", width=32))
        self.url_rows = tk.Frame(frm, bg=P["card"])
        for label, var in ((L("ওয়েব ঠিকানা", "Web address"), self.web), (L("API ঠিকানা", "API address"), self.api)):
            r = tk.Frame(self.url_rows, bg=P["card"])
            r.pack(fill="x", pady=3)
            tk.Label(r, text=label, bg=P["card"], fg=P["mute"], font=f.small, width=12, anchor="w").pack(side="left")
            Entry(r, f, var, width=34).pack(side="left", fill="x", expand=True, ipady=4)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._urls())
        self.email_entry = row(L("ইমেইল", "E-mail"), lambda r: Entry(r, f, self.email, width=34))
        self.pw_entry = row(L("পাসওয়ার্ড", "Password"), lambda r: Entry(r, f, self.password, show="•", width=34))
        self.pw_entry.bind("<Return>", lambda _e: self.sign_in())
        tk.Label(frm, text=L("🔒 শুধু তথ্য পড়ে, কিছু বদলায় না। পাসওয়ার্ড কোথাও সেভ হয় না (প্রোগ্রাম খোলা থাকা পর্যন্ত মনে থাকে)।",
                            "🔒 Only reads, never changes anything. The password is never saved (kept only while the program is open)."),
                 bg=P["card"], fg=P["mute"], font=f.tiny, wraplength=430, justify="left").pack(anchor="w", pady=(10, 0))
        self.login_btn = Button(frm, L("শুরু করুন", "Start"), self.sign_in, kind="primary", font=f.big, padx=30, pady=10)
        self.login_btn.pack(anchor="w", pady=(16, 0))
        self.login_msg = tk.Label(frm, text="", bg=P["card"], fg=P["bad"], font=f.small, wraplength=430, justify="left")
        self.login_msg.pack(anchor="w", pady=(8, 0))
        self._urls()
        (self.pw_entry if self.email.get() else self.email_entry).focus_set()

    def _urls(self):
        if self.server.get() == config.SERVER_PRODUCTION:
            self.url_rows.pack_forget()
        else:
            self.url_rows.pack(fill="x", after=self.url_rows.master.winfo_children()[0])

    def resolve(self):
        if self.server.get() == config.SERVER_PRODUCTION:
            return config.PRODUCTION["web"], config.PRODUCTION["api"]
        web = self.web.get().strip().rstrip("/")
        if not web.startswith("http"):
            raise ValueError(L("ওয়েব ঠিকানা লিখুন (https:// দিয়ে শুরু)।", "Write the web address (starting with https://)."))
        return web, (self.api.get().strip().rstrip("/") or config.derive_api_url(web))

    def sign_in(self):
        try:
            web, api = self.resolve()
        except ValueError as exc:
            self.login_msg.config(text=str(exc))
            return
        if not self.email.get().strip() or not self.password.get():
            self.login_msg.config(text=L("ইমেইল ও পাসওয়ার্ড দিন।", "Give the e-mail and password."))
            return
        self.login_btn.enable(False)
        self.login_msg.config(text=L("লগইন হচ্ছে…", "Signing in…"), fg=P["mute"])

        email, pw = self.email.get().strip(), self.password.get()        # Tk variables are read on this (the window's) thread only

        def work():
            try:
                ReadOnlyClient(web, api).login(email, pw)
                self.q.put(("signed_in",))
            except Exception as exc:                                       # noqa: BLE001
                self.q.put(("login_failed", error_text(str(exc))))
        threading.Thread(target=work, daemon=True).start()

    def _after_sign_in(self):
        self.signed_in = True
        config.save_settings({"lang": self.lang.get(), "server": self.server.get(), "web": self.web.get().strip(),
                              "api": self.api.get().strip(), "email": self.email.get().strip(), "out_dir": str(self.out_dir)})
        self.settings = config.load_settings()
        self.build_main()
        self.refresh_data("start")

    # ================================================================== main window
    def build_main(self, page: str = "home"):
        from .pages import BSPage, HomePage, ReceivePage, RemindersPage, SettingsPage, VerifiersPage
        from .gui import ReportsPage
        for w in self.root.winfo_children():
            w.destroy()
        f = self.fonts
        side = tk.Frame(self.root, bg=P["side"], width=232, highlightbackground=P["line"], highlightthickness=1)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=P["side"])
        brand.pack(fill="x", padx=16, pady=(20, 18))
        tk.Label(brand, text="V", bg=P["accent"], fg="white", font=f.h2, width=2).pack(side="left")
        b2 = tk.Frame(brand, bg=P["side"])
        b2.pack(side="left", padx=10)
        tk.Label(b2, text="Verify Builder", bg=P["side"], fg=P["text"], font=f.h3).pack(anchor="w")
        tk.Label(b2, text=f"Barikoi · v{__version__}", bg=P["side"], fg=P["mute"], font=f.tiny).pack(anchor="w")
        self.nav = {}
        for key, text, icon in nav_items():
            if key == "-":
                tk.Label(side, text=text.upper() if i18n.is_en() else text, bg=P["side"], fg=P["side_mute"], font=f.tiny,
                         anchor="w").pack(fill="x", padx=22, pady=(14, 4))
                continue
            b = tk.Label(side, text=f"  {icon}   {text}", bg=P["side"], fg=P["side_tx"], font=f.body, anchor="w", padx=12, pady=9,
                         cursor="hand2")
            b.pack(fill="x", padx=10, pady=1)
            b.bind("<Button-1>", lambda _e, k=key: self.show(k))
            b.bind("<Enter>", lambda _e, k=key: self._nav_hover(k, True))
            b.bind("<Leave>", lambda _e, k=key: self._nav_hover(k, False))
            self.nav[key] = b
        tk.Frame(side, bg=P["side"]).pack(fill="both", expand=True)
        self.status_box = tk.Label(side, text="", bg=P["ok_bg"], fg=P["ok"], font=f.tiny, justify="left", anchor="w",
                                   padx=10, pady=8, wraplength=190)
        self.status_box.pack(fill="x", padx=12, pady=(0, 14))
        self.content = tk.Frame(self.root, bg=P["bg"])
        self.content.pack(side="left", fill="both", expand=True)
        self.toast_bar = tk.Frame(self.content, bg=P["warn_bg"])
        self.toast_lbl = tk.Label(self.toast_bar, text="", bg=P["warn_bg"], fg=P["warn"], font=f.small, anchor="w", padx=14, pady=8)
        self.toast_lbl.pack(side="left", fill="x", expand=True)
        Button(self.toast_bar, "✕", lambda: self.toast_bar.pack_forget(), kind="danger", font=f.small, padx=10, pady=4).pack(side="right", padx=8)
        self.stack = tk.Frame(self.content, bg=P["bg"])
        self.stack.pack(fill="both", expand=True)
        self.reports = ReportsPage(self.stack, self)
        self.pages = {"home": HomePage(self.stack, self), "reports": self.reports, "bs": BSPage(self.stack, self),
                      "receive": ReceivePage(self.stack, self), "reminders": RemindersPage(self.stack, self),
                      "verifiers": VerifiersPage(self.stack, self), "settings": SettingsPage(self.stack, self)}
        for p in self.pages.values():
            p.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._status()
        self.show(page)

    def _nav_hover(self, key, on):
        if key != getattr(self, "current", None):
            self.nav[key].config(bg=P["side_hi"] if on else P["side"])

    def show(self, key: str):
        self.current = key
        for k, b in self.nav.items():
            sel = k == key
            b.config(bg=P["accent_soft"] if sel else P["side"], fg=P["side_on"] if sel else P["side_tx"])
        page = key
        if key in ("tracker", "bill", "history"):
            page = "reports"
            self.reports.rtype.set(key)
            self.reports.page_title.config(text={"tracker": L("দৈনিক সাবমিশন ট্র্যাকার", "Daily submission tracker"),
                                                 "bill": L("মাসিক বিল", "Monthly bill"),
                                                 "history": L("ফাইল হিস্টরি", "File history")}[key])
            self.reports._sync_ui()
        p = self.pages[page]
        p.tkraise()
        if hasattr(p, "refresh"):
            p.refresh()

    def toast(self, text: str):
        self.toast_lbl.config(text=text)
        self.toast_bar.pack(fill="x", before=self.stack)

    def set_out_dir(self, d: Path):
        self.out_dir = Path(d)
        self.reports.out_dir = self.out_dir
        config.save_settings({"out_dir": str(self.out_dir)})

    def _status(self):
        if not hasattr(self, "status_box"):
            return
        at = self.data["at"]
        busy = "refresh" in self.jobs
        txt = (L("● ড্যাশবোর্ড পড়া হচ্ছে…", "● Reading the dashboard…") if busy else
               (L(f"● ড্যাশবোর্ড (শুধু পড়া) · {at:%I:%M %p}", f"● Dashboard (read-only) · {at:%I:%M %p}") if at else
                L("● ড্যাশবোর্ড (শুধু পড়া)", "● Dashboard (read-only)")))
        ext = self.helper.extension_connected
        old_ext = ext and self.helper.ext_version and self.helper.ext_version != helper_version()
        if not self.helper_running:
            line = L("● হেল্পার চালু হয়নি (প্রোগ্রাম আরেকটা খোলা?)", "● Helper off (program open twice?)")
        elif old_ext:
            line = L("● Chrome হেল্পার পুরনো: Chrome বন্ধ করে আবার খুলুন", "● Chrome helper is old: close and reopen Chrome")
        elif ext:
            line = L("● WhatsApp-এর সাথে যুক্ত", "● Connected to WhatsApp")
        else:
            line = L("● WhatsApp যুক্ত নয় (রিমাইন্ডার পেজ দেখুন)", "● WhatsApp not connected (see Reminders)")
        good = self.helper_running and ext and not old_ext
        self.status_box.config(text=txt + "\n" + line, bg=P["ok_bg"] if good else P["warn_bg"], fg=P["ok"] if good else P["warn"])

    # ================================================================== data (read-only)
    def refresh_data(self, reason: str = "manual", then=None):
        """Both clients' files of the last 90 days + verifier phone numbers.  `then` runs on the UI thread afterwards."""
        if "refresh" in self.jobs or not self.signed_in:
            return
        self.jobs.add("refresh")
        self._status()
        try:
            web, api = self.resolve()
        except ValueError:
            self.jobs.discard("refresh")
            return
        email, pw, label = self.email.get().strip(), self.password.get(), self.server.get()
        workers = int(self.settings.get("workers", config.DEFAULT_WORKERS))

        def work():
            try:
                files, failed = {}, []
                for org in CLIENTS:
                    cfg = RunConfig(web=web, api=api, server_label=label, email=email, password=pw,
                                    days=LOOKBACK_DAYS, org_name=org, workers=workers)
                    try:
                        res = collect(cfg, lambda *a: self.q.put(("progress", org, *a)))
                        files[org] = res.files
                    except ApiError as exc:                      # e.g. the account has only one of the two clients
                        failed.append(f"{org}: {exc}")
                        files[org] = []
                c = ReadOnlyClient(web, api)
                c.login(email, pw)
                try:
                    phones = verifier_phones(c)
                except Exception:                                # noqa: BLE001 - phones are optional (a manager without access)
                    phones = {}
                self.q.put(("data", files, phones, failed, reason, then))
            except (AuthError, ApiError, Cancelled, PermissionError) as exc:
                self.q.put(("data_failed", str(exc)))
            except Exception as exc:                             # noqa: BLE001
                self.q.put(("data_failed", f"{type(exc).__name__}: {exc}"))
        threading.Thread(target=work, daemon=True).start()

    def bs_all(self) -> list:
        store = load_store()
        out = []
        for org, files in self.data["files"].items():
            out += bs_rows(files, org, self.data["phones"], store=store)
        return out

    def phone_overrides(self) -> dict:
        return dict(self.settings.get("phone_overrides") or {})

    # ================================================================== reminders round
    def prepare_round(self, round_key: str, notify: bool = True) -> int:
        bs = pending_bs(self.bs_all())
        q = R.build_queue(self.data["files"], self.data["phones"], bs_pending=bs, round_key=round_key,
                          overrides=self.phone_overrides())
        st = R.load_state()
        R.record_round(st, round_key, q)
        R.save_state(st)
        self.helper.round_key = round_key
        n = sum(1 for r in q if r.has_whatsapp_number)
        if notify:
            self.toast(L(f"💬 {R.ROUND_LABEL[round_key]} রিমাইন্ডার তৈরি: {n} জন। ‘রিমাইন্ডার’ পেজে ‘পাঠানো শুরু করুন’ চাপুন।",
                         f"💬 {R.ROUND_LABEL[round_key]} reminder ready: {n} verifiers. Go to ‘Reminders’ and press ‘Start sending’."))
        if "reminders" in self.pages:
            self.pages["reminders"].refresh()
        return n

    # ================================================================== clock (office days, 10 AM - 6:15 PM)
    def _tick(self):
        try:
            self._scheduled()
        finally:
            self.after(30_000, self._tick)

    def _scheduled(self, now: datetime | None = None):
        if not self.signed_in:
            return
        now = now or datetime.now()
        if now.weekday() in (4, 5):
            return
        st = R.load_state()
        due = R.due_round(st, now)
        if due and "refresh" not in self.jobs and "round" not in self.jobs:
            self.jobs.add("round")
            self.refresh_data("round", then=lambda: (self.jobs.discard("round"), self.prepare_round(due)))
            return
        done = self.settings.get("bs_checks", {})
        today = now.date().isoformat()
        for key, t in BS_CHECKS:
            if now.time() >= t and key not in done.get(today, []) and now.time() <= time(23, 59):
                passed = [k for k, tt in BS_CHECKS if now.time() >= tt]
                if key != passed[-1]:
                    continue                                      # only the latest missed check
                done = {today: list(set(done.get(today, [])) | set(passed))}
                config.save_settings({"bs_checks": done})
                self.settings["bs_checks"] = done
                label = "12:00 PM" if key == "12pm" else "6:15 PM"

                def after_check(label=label):
                    pend = pending_bs(self.bs_all())
                    off = sum(1 for r in pend if r.bs_type == "Offline")
                    self.toast(L(f"🏦 {label} BS চেক: {len(pend)} টি BS বাকি (অফলাইন {off})। দৈনিক ট্র্যাকারের সময়ও হয়েছে।",
                                 f"🏦 {label} BS check: {len(pend)} bank statements pending (offline {off}). Also time for the daily tracker."))
                    if "bs" in self.pages:
                        self.pages["bs"].refresh()
                self.refresh_data("bs", then=after_check)
                return

    # ================================================================== queue from threads
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "signed_in":
                    self._after_sign_in()
                elif kind == "login_failed":
                    self.login_btn.enable(True)
                    self.login_msg.config(text=msg[1], fg=P["bad"])
                elif kind == "data":
                    _, files, phones, failed, reason, then = msg
                    self.data.update(files=files, phones=phones, at=datetime.now())
                    self.jobs.discard("refresh")
                    self._status()
                    for p in self.pages.values():
                        if hasattr(p, "on_data"):
                            p.on_data()
                    if failed and reason == "manual":
                        self.toast("⚠ " + "; ".join(failed)[:200])
                    if then:
                        then()
                elif kind == "data_failed":
                    self.jobs.discard("refresh")
                    self.jobs.discard("round")
                    self._status()
                    self.toast("⚠ " + L("ড্যাশবোর্ড পড়া যায়নি: ", "Could not read the dashboard: ") + error_text(msg[1])[:180])
                elif kind == "call":
                    msg[1]()
                elif kind == "helper":
                    _, k, e = msg
                    self._status()
                    if k == "reply" and e.get("kind") == "no_whatsapp":
                        R.NO_WA_CACHE.add(e.get("phone", ""))
                    if "reminders" in self.pages:
                        self.pages["reminders"].refresh()
                    if "home" in self.pages:
                        self.pages["home"].refresh()
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def open_whatsapp(self):
        webbrowser.open("https://web.whatsapp.com/")

    def start_sending(self) -> str:
        """The one button: -> "started" (a WhatsApp tab with the helper is open and takes over) or "opened"
        (WhatsApp Web was opened; the helper starts by itself when the page is ready, if it has been added to Chrome)."""
        self.helper.request_start()
        if self.helper.extension_connected:
            return "started"
        self.open_whatsapp()
        return "opened"

    def _close(self):
        try:
            if self.state() == "normal":
                config.save_settings({"geometry": self.geometry().split("+")[0]})
        except tk.TclError:
            pass
        self.helper.stop()
        self.destroy()


def run() -> None:
    Shell().mainloop()
