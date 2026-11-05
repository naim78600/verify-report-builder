"""Desktop window (tkinter) - Windows and macOS.  Bengali interface, one screen, four steps."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, config
from . import holidays as hol
from .client import ApiError, AuthError, Cancelled
from .collect import RunConfig, collect
from .collect_prime import PrimeConfig, collect_prime, slot_for
from .email_copy import build_email_html, load_signature, save_signature
from .excel import build_workbook
from .reports import write_prime_outputs, write_recpv_workbook
from .ui_kit import (Button, Card, DateField, Entry, Fonts, P, Progress, Segmented, Stepper, Tile, parse_date,
                     pick_font_family)

STAGES = ["লগইন", "ফাইল সংগ্রহ", "অ্যাক্টিভিটি লগ", "হিসাব", "ফাইল তৈরি"]
STAGE_INDEX = {"login": 0, "list": 1, "detail": 1, "recpv": 1, "old": 1, "log": 2, "rows": 3, "write": 4, "excel": 4}


def open_path(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))            # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showerror("ফাইল খোলা যায়নি", str(exc))


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{config.APP_NAME} {__version__}")
        self.configure(bg=P["bg"])
        self.resizable(False, False)
        self.fonts = Fonts(self, pick_font_family(self))
        self._tune_default_fonts()
        self.settings = config.load_settings()
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.out_dir = Path(self.settings.get("out_dir") or config.default_output_dir())
        self.last_prime = None
        self.out_files: list[Path] = []
        self._build()
        self._sync_ui()
        self.after(100, self._poll)
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = max(0, (self.winfo_screenwidth() - w) // 2)
        y = max(0, (self.winfo_screenheight() - h) // 3)
        self.geometry(f"+{x}+{y}")

    def _tune_default_fonts(self):
        import tkinter.font as tkfont
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
            try:
                tkfont.nametofont(name).configure(family=self.fonts.family, size=11)
            except tk.TclError:
                pass

    # ================================================================== layout
    def _build(self):
        f = self.fonts
        side = tk.Frame(self, bg=P["side"], width=236)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        holder = tk.Frame(self, bg=P["bg"])
        holder.grid(row=0, column=1, sticky="nsew")
        foot = tk.Frame(holder, bg=P["bg"], padx=18)
        foot.pack(side="bottom", fill="x", pady=(0, 12))
        self._foot = foot
        canvas = tk.Canvas(holder, bg=P["bg"], highlightthickness=0, borderwidth=0)
        vbar = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        main = tk.Frame(canvas, bg=P["bg"], padx=18, pady=14)
        win = canvas.create_window((0, 0), window=main, anchor="nw")
        self._canvas, self._vbar, self._main_win = canvas, vbar, win

        def _fit(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            need = main.winfo_reqheight() + 28
            room = max(380, self.winfo_screenheight() - 130 - foot.winfo_reqheight())
            canvas.configure(height=min(need, room), width=main.winfo_reqwidth() + 36)
            if need > room:
                vbar.pack(side="right", fill="y")
            else:
                vbar.pack_forget()
            canvas.itemconfigure(win, width=max(main.winfo_reqwidth(), canvas.winfo_width() - 36))
        main.bind("<Configure>", _fit)
        self._fit_scroll = _fit

        def _wheel(e):
            if vbar.winfo_ismapped():
                canvas.yview_scroll(-1 * (e.delta if sys.platform == "darwin" else e.delta // 120), "units")
        self.bind_all("<MouseWheel>", _wheel)

        # ---- sidebar -------------------------------------------------------------
        tk.Label(side, text="Verify", bg=P["side"], fg="white", font=f.title).pack(anchor="w", padx=20, pady=(22, 0))
        tk.Label(side, text="Report Builder", bg=P["side"], fg=P["side_tx"], font=f.h2).pack(anchor="w", padx=20)
        tk.Label(side, text=f"Prime Bank PLC · v{__version__}", bg=P["side"], fg=P["side_mute"], font=f.tiny).pack(anchor="w", padx=20, pady=(2, 18))
        note = tk.Frame(side, bg=P["side_hi"])
        note.pack(fill="x", padx=16)
        tk.Label(note, text="🔒 শুধু তথ্য পড়ে\nকিছু বদলায় না, পাসওয়ার্ড সংরক্ষণ হয় না", bg=P["side_hi"], fg=P["side_tx"],
                 font=f.tiny, justify="left", anchor="w", padx=10, pady=8).pack(fill="x")
        tk.Frame(side, bg=P["side"], height=14).pack()
        for text, cmd in (("📅  ছুটির তালিকা", self._holiday_dialog), ("✉  ইমেইল সিগনেচার", self._signature_dialog),
                          ("📂  ফোল্ডার খুলুন", lambda: open_path(self.out_dir))):
            Button(side, text, cmd, kind="ghost", font=f.body, anchor="w", padx=20, pady=9).pack(fill="x")
        tk.Label(side, text="সেভের জায়গা", bg=P["side"], fg=P["side_mute"], font=f.tiny).pack(anchor="w", padx=20, pady=(20, 0))
        self.dir_label = tk.Label(side, text=self._short(self.out_dir), bg=P["side"], fg=P["side_tx"], font=f.tiny, wraplength=200, justify="left")
        self.dir_label.pack(anchor="w", padx=20)
        Button(side, "বদলান", self._choose_dir, kind="ghost", font=f.small, anchor="w", padx=20, pady=4).pack(fill="x")

        # ---- main: header --------------------------------------------------------
        tk.Label(main, text="নতুন রিপোর্ট", bg=P["bg"], fg=P["navy"], font=f.title).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(main, text="লগইন করুন, রিপোর্টের ধরন ও সময়সীমা বাছুন, তারপর ‘রিপোর্ট তৈরি করুন’ চাপুন।", bg=P["bg"], fg=P["mute"],
                 font=f.small).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        colA = tk.Frame(main, bg=P["bg"])
        colA.grid(row=2, column=0, sticky="n", padx=(0, 10))
        colB = tk.Frame(main, bg=P["bg"])
        colB.grid(row=2, column=1, sticky="n")

        # ---- 1 login -------------------------------------------------------------
        c1 = Card(colA, f, "লগইন", "১")
        c1.pack(fill="x", pady=(0, 10))
        b = c1.body
        self.server = tk.StringVar(value=self.settings.get("server", config.SERVER_PRODUCTION))
        row = tk.Frame(b, bg=P["card"])
        row.pack(fill="x", pady=(0, 6))
        tk.Label(row, text="সার্ভার", bg=P["card"], fg=P["mute"], font=f.small, width=9, anchor="w").pack(side="left")
        cb = ttk.Combobox(row, textvariable=self.server, values=config.SERVER_CHOICES, state="readonly", width=30)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._toggle_urls())
        self.url_frame = tk.Frame(b, bg=P["card"])
        self.web = tk.StringVar(value=self.settings.get("web", ""))
        self.api = tk.StringVar(value=self.settings.get("api", ""))
        for i, (lab, var) in enumerate((("ওয়েব ঠিকানা", self.web), ("API ঠিকানা", self.api))):
            r_ = tk.Frame(self.url_frame, bg=P["card"])
            r_.pack(fill="x", pady=2)
            tk.Label(r_, text=lab, bg=P["card"], fg=P["mute"], font=f.small, width=9, anchor="w").pack(side="left")
            Entry(r_, f, var, width=30).pack(side="left", ipady=3)
        self.email = tk.StringVar(value=self.settings.get("email", ""))
        self.password = tk.StringVar()
        for lab, var, show in (("ইমেইল", self.email, None), ("পাসওয়ার্ড", self.password, "•")):
            r_ = tk.Frame(b, bg=P["card"])
            r_.pack(fill="x", pady=4)
            tk.Label(r_, text=lab, bg=P["card"], fg=P["mute"], font=f.small, width=9, anchor="w").pack(side="left")
            Entry(r_, f, var, show=show, width=31).pack(side="left", ipady=4)

        # ---- 2 period ------------------------------------------------------------
        c2 = Card(colA, f, "ফাইলের সময়সীমা", "২")
        c2.pack(fill="x")
        b = c2.body
        self.period = tk.StringVar(value="days")
        Segmented(b, f, [("days", "শেষ কয়েক দিন"), ("range", "তারিখ বাছুন")], self.period, self._sync_ui).pack(anchor="w", pady=(0, 8))
        d_row = tk.Frame(b, bg=P["card"])
        d_row.pack(fill="x", pady=2)
        tk.Label(d_row, text="শেষ", bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.days = tk.StringVar(value=str(self.settings.get("days", 60)))
        self.days_entry = Entry(d_row, f, self.days, width=5, justify="center")
        self.days_entry.pack(side="left", padx=6, ipady=4)
        tk.Label(d_row, text="দিনের ফাইল", bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.chips = []
        for n in (30, 60, 90):
            ch = Button(d_row, str(n), lambda n=n: self.days.set(str(n)), kind="secondary", font=f.tiny, padx=8, pady=3)
            ch.pack(side="left", padx=(8 if n == 30 else 3, 0))
            self.chips.append(ch)
        r_row = tk.Frame(b, bg=P["card"])
        r_row.pack(fill="x", pady=(10, 2))
        today = date.today()
        tk.Label(r_row, text="থেকে", bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.d_from = DateField(r_row, f, today - timedelta(days=30))
        self.d_from.pack(side="left", padx=6)
        tk.Label(r_row, text="পর্যন্ত", bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.d_till = DateField(r_row, f, today)
        self.d_till.pack(side="left", padx=6)
        self.period_hint = tk.Label(b, text="", bg=P["card"], fg=P["mute"], font=f.tiny, anchor="w", justify="left", wraplength=380)
        self.period_hint.pack(fill="x", pady=(8, 0))

        # ---- 3 report type -------------------------------------------------------
        c3 = Card(colB, f, "রিপোর্টের ধরন", "৩")
        c3.pack(fill="x", pady=(0, 10))
        b = c3.body
        self.rtype = tk.StringVar(value=self.settings.get("rtype", "tracker"))
        for val, title, help_ in (
                ("tracker", "দৈনিক সাবমিশন ট্র্যাকার", "Complete + Incomplete রিপোর্ট, ইমেইলের মতো সাজানো (3pm / 7pm)"),
                ("range", "সময়সীমার সব ফাইলের রিপোর্ট", "বাছাই করা সময়ের সব সারি: Submitted ও Incomplete"),
                ("recpv", "Re-CPV সহ বিস্তারিত এক্সেল", "প্রতি ফাইলের নিচে Re-CPV/Extra + Calculation শিট"),
                ("v1", "সাধারণ বিস্তারিত এক্সেল", "ফাইল ও ট্রিপের পুরো রিপোর্ট (আগের ভার্সনের মতো)")):
            Tile(b, f, val, title, help_, self.rtype, self._sync_ui).pack(fill="x", pady=3)
        self.track_row = tk.Frame(b, bg=P["card"])
        self.track_row.pack(fill="x", pady=(8, 0))
        tk.Label(self.track_row, text="রিপোর্টের তারিখ", bg=P["card"], fg=P["text"], font=f.small).pack(side="left")
        self.rdate = DateField(self.track_row, f, today)
        self.rdate.pack(side="left", padx=(6, 12))
        self.slot = tk.StringVar(value="auto")
        Segmented(self.track_row, f, [("auto", f"অটো ({slot_for()})"), ("3pm", "3pm"), ("7pm", "7pm")], self.slot).pack(side="left")

        # ---- 4 outputs -----------------------------------------------------------
        c4 = Card(colA, f, "যা তৈরি হবে", "৪")
        c4.pack(fill="x", pady=(10, 0))
        b = c4.body
        self.opts = {}
        self.opt_boxes = []
        for key, text, dflt in (("excel", "Excel", True), ("pdf", "PDF", True), ("email", "ইমেইলের জন্য পেজ", True),
                                ("bank", "ব্যাংক কপি (পরিষ্কার)", True), ("internal", "অভ্যন্তরীণ কপি (হলুদ চিহ্ন সহ)", True)):
            self.opts[key] = tk.BooleanVar(value=dflt)
            cbx = tk.Checkbutton(b, text=text, variable=self.opts[key], bg=P["card"], activebackground=P["card"], font=f.body,
                                 fg=P["text"], anchor="w", highlightthickness=0, selectcolor="white", command=self._sync_ui)
            cbx.pack(fill="x", anchor="w")
            self.opt_boxes.append((key, cbx))

        # ---- action bar ----------------------------------------------------------
        bar = tk.Frame(foot, bg=P["card"], highlightbackground=P["line"], highlightthickness=1)
        bar.pack(fill="x")
        top = tk.Frame(bar, bg=P["card"])
        top.pack(fill="x", padx=14, pady=(10, 4))
        self.go_btn = Button(top, "রিপোর্ট তৈরি করুন", self._go, kind="primary", font=f.big, padx=26, pady=10)
        self.go_btn.pack(side="left")
        self.cancel_btn = Button(top, "বাতিল", self._cancel, kind="danger", font=f.body, padx=14, pady=9)
        self.cancel_btn.pack(side="left", padx=10)
        self.cancel_btn.enable(False)
        self.status = tk.StringVar(value="প্রস্তুত।")
        tk.Label(top, textvariable=self.status, bg=P["card"], fg=P["text"], font=f.small, anchor="w", justify="left",
                 wraplength=470).pack(side="left", padx=10, fill="x", expand=True)
        self.bar = Progress(bar, f)
        self.bar.pack(fill="x", padx=14, pady=(2, 4))
        self.stepper = Stepper(bar, f, STAGES)
        self.stepper.pack(anchor="w", padx=8, pady=(0, 6))
        self.result = tk.Frame(bar, bg=P["card"])
        self.result.pack(fill="x", padx=14, pady=(0, 8))
        main.grid_columnconfigure(0, weight=1)
        main.grid_columnconfigure(1, weight=1)
        foot.bind("<Configure>", lambda _e: self._fit_scroll())
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._toggle_urls()

    @staticmethod
    def _short(p: Path, n=34) -> str:
        s = str(p)
        return s if len(s) <= n else "…" + s[-(n - 1):]

    def _toggle_urls(self):
        if self.server.get() == config.SERVER_PRODUCTION:
            self.url_frame.pack_forget()
        else:
            self.url_frame.pack(fill="x", before=self.url_frame.master.winfo_children()[2] if len(self.url_frame.master.winfo_children()) > 2 else None)

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.out_dir), title="রিপোর্ট কোথায় সেভ হবে?")
        if d:
            self.out_dir = Path(d)
            self.dir_label.config(text=self._short(self.out_dir))

    def _sync_ui(self):
        rng = self.period.get() == "range"
        self.days_entry.enable(not rng)
        for ch in self.chips:
            ch.enable(not rng)
        self.d_from.enable(rng)
        self.d_till.enable(rng)
        rt = self.rtype.get()
        pb = rt in ("tracker", "range")
        if rt == "tracker":
            self.track_row.pack(fill="x", pady=(8, 0))
        else:
            self.track_row.pack_forget()
        self.rdate.enable(not rng)
        self.period_hint.config(text=(
            "তারিখ বাছলে ‘শেষ কয়েক দিন’ বন্ধ থাকে। ট্র্যাকারে ‘পর্যন্ত’ তারিখই রিপোর্টের তারিখ।" if rng else
            "‘শেষ কয়েক দিন’ থেকে আজ পর্যন্ত। নির্দিষ্ট তারিখ চাইলে ‘তারিখ বাছুন’ চাপুন।"))
        for key, cbx in self.opt_boxes:
            on = pb and (key != "email" or rt == "tracker")
            if key in ("bank", "internal"):
                on = on and (self.opts["excel"].get() or self.opts["pdf"].get())
            cbx.config(state="normal" if on else "disabled")

    # ================================================================== run
    def _inputs(self):
        """-> dict or None (a warning was shown)."""
        try:
            web, api = self._resolve_urls()
        except ValueError as exc:
            messagebox.showwarning("তথ্য ঠিক নেই", str(exc))
            return None
        email, pw = self.email.get().strip(), self.password.get()
        if not email or not pw:
            messagebox.showwarning("তথ্য ঠিক নেই", "ইমেইল ও পাসওয়ার্ড দিন।")
            return None
        days, d_from, d_till = None, None, None
        if self.period.get() == "range":
            d_from, d_till = self.d_from.get(), self.d_till.get()
            if not d_from or not d_till:
                messagebox.showwarning("তারিখ ঠিক নেই", "তারিখ এভাবে লিখুন: 05-11-2026 (অথবা 📅 চেপে বাছুন)।")
                return None
            if d_from > d_till:
                messagebox.showwarning("তারিখ ঠিক নেই", "শুরুর তারিখ শেষ তারিখের পরে হতে পারে না।")
                return None
            days = max(1, (date.today() - d_from).days)
        else:
            try:
                days = int(self.days.get())
                if not 1 <= days <= 730:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("দিন সংখ্যা ঠিক নেই", "দিন সংখ্যা ১ থেকে ৭৩০ এর মধ্যে দিন।")
                return None
        config.save_settings({
            "server": self.server.get(), "web": self.web.get().strip(), "api": self.api.get().strip(), "email": email,
            "days": days if not d_from else int(self.settings.get("days", 60)), "out_dir": str(self.out_dir),
            "rtype": self.rtype.get()})
        return {"web": web, "api": api, "email": email, "pw": pw, "days": days, "from": d_from, "till": d_till}

    def _resolve_urls(self):
        label = self.server.get()
        if label == config.SERVER_PRODUCTION:
            web = config.PRODUCTION["web"]
            return web, config.PRODUCTION["api"]
        web = self.web.get().strip().rstrip("/")
        if not web.startswith("http"):
            raise ValueError("ওয়েব ঠিকানা লিখুন (https:// দিয়ে শুরু)।")
        api = self.api.get().strip().rstrip("/") or config.derive_api_url(web)
        return web, api

    def _go(self):
        inp = self._inputs()
        if inp is None:
            return
        rt = self.rtype.get()
        workers = int(self.settings.get("workers", config.DEFAULT_WORKERS))
        org = self.settings.get("org_name", config.DEFAULT_ORG)
        if rt in ("tracker", "range", "recpv"):
            mode = "tracker" if rt == "tracker" else "range"
            rdate = inp["till"] if (rt == "tracker" and inp["till"]) else (self.rdate.get() or date.today())
            slot = self.slot.get()
            cfg = PrimeConfig(web=inp["web"], api=inp["api"], server_label=self.server.get(), email=inp["email"],
                              password=inp["pw"], days=inp["days"], mode=mode, report_date=rdate,
                              slot=slot_for() if slot == "auto" else slot, date_from=inp["from"],
                              date_till=inp["till"] if mode == "range" else None, workers=workers, org_name=org)
            opts = {k: v.get() for k, v in self.opts.items()}
            if rt in ("tracker", "range"):
                if not (opts["excel"] or opts["pdf"] or (opts["email"] and rt == "tracker")):
                    messagebox.showwarning("তথ্য ঠিক নেই", "Excel, PDF বা ইমেইল পেজ—অন্তত একটি বাছুন।")
                    return
                if (opts["excel"] or opts["pdf"]) and not (opts["bank"] or opts["internal"]):
                    messagebox.showwarning("তথ্য ঠিক নেই", "ব্যাংক কপি বা অভ্যন্তরীণ কপি—অন্তত একটি বাছুন।")
                    return
                opts["email"] = opts["email"] and rt == "tracker"
            target = self._work_prime if rt != "recpv" else self._work_recpv
            args = (cfg, opts) if rt != "recpv" else (cfg,)
        else:
            cfg = RunConfig(web=inp["web"], api=inp["api"], server_label=self.server.get(), email=inp["email"],
                            password=inp["pw"], days=inp["days"], workers=workers, org_name=org)
            target, args = self._work_v1, (cfg,)
        self._busy()
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _busy(self):
        self.cancel.clear()
        self.out_files = []
        for w in self.result.winfo_children():
            w.destroy()
        self.go_btn.enable(False)
        self.cancel_btn.enable(True)
        self.bar.set(0)
        self.stepper.set(0)
        self.status.set("শুরু হচ্ছে…")

    def _work_prime(self, cfg: PrimeConfig, opts: dict):
        try:
            d = collect_prime(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "write", 0, 1, "Excel / PDF তৈরি হচ্ছে…"))
            paths = write_prime_outputs(d, self.out_dir, excel=opts["excel"], pdf=opts["pdf"], internal=opts["internal"],
                                        bank=opts["bank"], email=opts["email"])
            self.q.put(("prime_done", paths, d))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:                      # unexpected
            self.q.put(("error", f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}"))

    def _work_recpv(self, cfg: PrimeConfig):
        try:
            d = collect_prime(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "write", 0, 1, "Re-CPV সহ এক্সেল তৈরি হচ্ছে…"))
            self.q.put(("prime_done", [write_recpv_workbook(d, self.out_dir)], d))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:
            self.q.put(("error", f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}"))

    def _work_v1(self, cfg: RunConfig):
        try:
            res = collect(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "excel", 0, 1, "এক্সেল ফাইল তৈরি হচ্ছে…"))
            name = f"Verify_Report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
            self.q.put(("v1_done", build_workbook(res, self.out_dir / name), res))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:
            self.q.put(("error", f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}"))

    def _cancel(self):
        self.cancel.set()
        self.status.set("বাতিল হচ্ছে…")

    def _finish_ui(self):
        self.go_btn.enable(True)
        self.cancel_btn.enable(False)
        self.password.set("")

    def _show_results(self, paths: list[Path], extra_email: bool):
        for w in self.result.winfo_children():
            w.destroy()
        f = self.fonts
        row = tk.Frame(self.result, bg=P["card"])
        row.pack(fill="x")
        for p in paths:
            Button(row, f"{p.suffix[1:].upper()}  {p.stem[-26:]}", lambda p=p: open_path(p), kind="secondary", font=f.tiny,
                   padx=8, pady=4).pack(side="left", padx=(0, 6), pady=2)
        if extra_email:
            Button(row, "✉ ইমেইলের জন্য কপি", self._email_copy, kind="primary", font=f.tiny, padx=8, pady=4).pack(side="left", padx=(6, 0))

    def _email_copy(self):
        d = self.last_prime
        if d is None or d.mode != "tracker":
            messagebox.showinfo("ইমেইল কপি", "আগে ‘দৈনিক সাবমিশন ট্র্যাকার’ তৈরি করুন।")
            return
        open_path(build_email_html(d, self.out_dir / f"Prime_Bank_{d.report_date:%Y-%m-%d}_{d.slot}_email.html"))

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, stage, done, total, text = msg
                    idx = STAGE_INDEX.get(stage, 1)
                    self.stepper.set(idx)
                    self.bar.set((idx + (done / total if total else 0)) / len(STAGES))
                    self.status.set(text)
                elif kind == "prime_done":
                    _, paths, d = msg
                    self.last_prime = d
                    self.out_files = paths
                    self._finish_ui()
                    self.bar.set(1)
                    self.stepper.set(len(STAGES))
                    br = sum(1 for r in d.complete + d.incomplete if r.sla_breach)
                    if d.mode == "tracker":
                        txt = f"সম্পন্ন!  Complete {len(d.complete)} · Incomplete {len(d.incomplete)} · SLA Breach {br}"
                    else:
                        txt = f"সম্পন্ন!  মোট {len(d.all_rows)} সারি · ফাইল {len(d.files)} টি"
                    if d.notes:
                        txt += "\n" + " ".join(d.notes[:2])
                    self.status.set(txt)
                    self._show_results(paths, d.mode == "tracker")
                elif kind == "v1_done":
                    _, path, res = msg
                    self.out_files = [path]
                    self._finish_ui()
                    self.bar.set(1)
                    self.stepper.set(len(STAGES))
                    txt = f"সম্পন্ন! ফাইল {len(res.files)}/{res.site_total} টি সংগৃহীত।"
                    if res.failed:
                        txt += f" ব্যর্থ: {len(res.failed)} টি (এক্সেলের 'Failed Files' শিটে)।"
                    self.status.set(txt)
                    self._show_results([path], False)
                elif kind == "cancelled":
                    self._finish_ui()
                    self.bar.set(0)
                    self.stepper.set(-1)
                    self.status.set("বাতিল করা হয়েছে।")
                elif kind == "error":
                    self._finish_ui()
                    self.bar.set(0)
                    self.stepper.set(-1)
                    self.status.set("ব্যর্থ হয়েছে।")
                    messagebox.showerror("সমস্যা হয়েছে", msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ================================================================== dialogs
    def _dialog(self, title: str):
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=P["card"], padx=16, pady=14)
        dlg.transient(self)
        dlg.resizable(False, False)
        return dlg

    def _holiday_dialog(self):
        f = self.fonts
        dlg = self._dialog("ছুটির তালিকা")
        warn = hol.needs_update()
        note = f"তালিকা {hol.last_date():%d-%m-%Y} পর্যন্ত আছে।" + ("  ⚠ নতুন ছুটি যোগ করুন।" if warn else "")
        tk.Label(dlg, text=note, bg=P["card"], fg=P["warn"] if warn else P["ok"], font=f.h3).pack(anchor="w")
        box = tk.Listbox(dlg, width=54, height=11, selectmode="extended", font=f.small, relief="flat", highlightthickness=1,
                         highlightbackground=P["line"])
        box.pack(pady=8)
        dates: list[date] = []

        def refresh():
            box.delete(0, "end")
            dates.clear()
            for d, name in sorted(hol.load().items()):
                if d >= date.today() - timedelta(days=15):
                    box.insert("end", f"{d.isoformat()}   {name}")
                    dates.append(d)
        refresh()
        tk.Label(dlg, text="নতুন ছুটি (প্রতি লাইনে একটি):   শুরু | শেষ | নাম\nযেমন:  2027-03-09 | 2027-03-11 | Eid ul Fitr\n"
                           "এক দিনের ছুটি হলে শেষ তারিখ বাদ দিন।", bg=P["card"], fg=P["mute"], font=f.tiny, justify="left").pack(anchor="w")
        txt = tk.Text(dlg, width=54, height=4, font=f.small, relief="flat", highlightthickness=1, highlightbackground=P["line"])
        txt.pack(pady=6)

        def add():
            n, errs = hol.add_ranges(txt.get("1.0", "end").splitlines())
            if errs:
                messagebox.showwarning("কিছু লাইন যোগ হয়নি", "\n".join(errs), parent=dlg)
            if n:
                txt.delete("1.0", "end")
                messagebox.showinfo("যোগ হয়েছে", f"{n} দিন যোগ হয়েছে।", parent=dlg)
            refresh()

        def import_csv():
            path = filedialog.askopenfilename(parent=dlg, title="CSV বা টেক্সট ফাইল বাছুন",
                                              filetypes=[("CSV / Text", "*.csv *.txt"), ("All", "*.*")])
            if path:
                n, errs = hol.import_file(Path(path))
                messagebox.showinfo("ইমপোর্ট", f"{n} দিন যোগ হয়েছে।" + ("\n" + "\n".join(errs) if errs else ""), parent=dlg)
                refresh()

        def remove():
            for i in box.curselection():
                hol.remove_date(dates[i])
            refresh()

        row = tk.Frame(dlg, bg=P["card"])
        row.pack(pady=(4, 0))
        for text, cmd, kind in (("যোগ করুন", add, "primary"), ("ফাইল থেকে ইমপোর্ট", import_csv, "secondary"),
                                ("নির্বাচিত মুছুন", remove, "secondary"), ("বন্ধ", dlg.destroy, "secondary")):
            Button(row, text, cmd, kind=kind, font=f.small, padx=10, pady=6).pack(side="left", padx=4)

    def _signature_dialog(self):
        f = self.fonts
        dlg = self._dialog("ইমেইল সিগনেচার")
        tk.Label(dlg, text="‘Regards,’ এর নিচে যা থাকবে (নাম, পদবি, ফোন…):", bg=P["card"], fg=P["text"], font=f.body).pack(anchor="w")
        txt = tk.Text(dlg, width=48, height=7, font=f.body, relief="flat", highlightthickness=1, highlightbackground=P["line"])
        txt.pack(pady=8)
        txt.insert("1.0", load_signature())

        def save():
            save_signature(txt.get("1.0", "end").strip())
            dlg.destroy()
        Button(dlg, "সংরক্ষণ", save, kind="primary", font=f.body, padx=18, pady=7).pack()


def run() -> None:
    App().mainloop()
