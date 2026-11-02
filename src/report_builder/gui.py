"""Small desktop window (tkinter) - works on Windows and macOS."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, config
from .client import ApiError, AuthError, Cancelled
from .collect import RunConfig, collect
from .excel import build_workbook
from . import holidays as hol
from .collect_prime import PrimeConfig, collect_prime, slot_for
from .email_copy import build_email_html, load_signature, save_signature
from .reports import write_prime_outputs, write_recpv_workbook


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
        self.resizable(False, False)
        self._setup_fonts()
        self.settings = config.load_settings()
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.out_file: Path | None = None
        self.out_dir = Path(self.settings.get("out_dir") or config.default_output_dir())
        self._build()
        self.after(100, self._poll)

    def _setup_fonts(self):
        """Prefer a font that has Bengali glyphs on the current OS."""
        wanted = ["Nirmala UI", "Kohinoor Bangla", "Bangla Sangam MN", "Noto Sans Bengali", "Vrinda"]
        have = set(tkfont.families(self))
        family = next((f for f in wanted if f in have), None)
        if family:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                try:
                    tkfont.nametofont(name).configure(family=family, size=11)
                except tk.TclError:
                    pass

    # ---------------------------------------------------------------- layout
    def _build(self):
        pad = {"padx": 10, "pady": 5}
        root = ttk.Frame(self, padding=14)
        root.grid()
        r = 0

        ttk.Label(root, text="সার্ভার").grid(row=r, column=0, sticky="w", **pad)
        self.server = tk.StringVar(value=self.settings.get("server", config.SERVER_PRODUCTION))
        cb = ttk.Combobox(root, textvariable=self.server, values=config.SERVER_CHOICES, state="readonly", width=34)
        cb.grid(row=r, column=1, sticky="ew", **pad)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._toggle_urls())
        r += 1

        self.url_frame = ttk.Frame(root)
        self.url_frame.grid(row=r, column=0, columnspan=2, sticky="ew")
        ttk.Label(self.url_frame, text="ওয়েব ঠিকানা").grid(row=0, column=0, sticky="w", **pad)
        self.web = tk.StringVar(value=self.settings.get("web", ""))
        ttk.Entry(self.url_frame, textvariable=self.web, width=37).grid(row=0, column=1, **pad)
        ttk.Label(self.url_frame, text="API ঠিকানা").grid(row=1, column=0, sticky="w", **pad)
        self.api = tk.StringVar(value=self.settings.get("api", ""))
        ttk.Entry(self.url_frame, textvariable=self.api, width=37).grid(row=1, column=1, **pad)
        ttk.Label(self.url_frame, text="(API ঠিকানা ফাঁকা রাখলে ওয়েব ঠিকানা থেকে নিজে ঠিক হবে)",
                  foreground="#666").grid(row=2, column=0, columnspan=2, sticky="w", padx=10)
        r += 1

        ttk.Label(root, text="ইমেইল").grid(row=r, column=0, sticky="w", **pad)
        self.email = tk.StringVar(value=self.settings.get("email", ""))
        ttk.Entry(root, textvariable=self.email, width=37).grid(row=r, column=1, **pad)
        r += 1

        ttk.Label(root, text="পাসওয়ার্ড").grid(row=r, column=0, sticky="w", **pad)
        self.password = tk.StringVar()
        ttk.Entry(root, textvariable=self.password, show="•", width=37).grid(row=r, column=1, **pad)
        r += 1

        ttk.Label(root, text="দিন সংখ্যা").grid(row=r, column=0, sticky="w", **pad)
        self.days = tk.StringVar(value=str(self.settings.get("days", config.DEFAULT_DAYS)))
        ttk.Spinbox(root, from_=1, to=730, textvariable=self.days, width=8).grid(row=r, column=1, sticky="w", **pad)
        r += 1

        ttk.Label(root, text="সেভের জায়গা").grid(row=r, column=0, sticky="w", **pad)
        f = ttk.Frame(root)
        f.grid(row=r, column=1, sticky="ew", **pad)
        self.dir_label = ttk.Label(f, text=str(self.out_dir), width=28)
        self.dir_label.pack(side="left")
        ttk.Button(f, text="বদলান", width=7, command=self._choose_dir).pack(side="right")
        r += 1

        btns = ttk.Frame(root)
        btns.grid(row=r, column=0, columnspan=2, pady=(10, 4))
        self.go_btn = ttk.Button(btns, text="রিপোর্ট তৈরি করুন", command=self._start)
        self.go_btn.pack(side="left", padx=4)
        self.cancel_btn = ttk.Button(btns, text="বাতিল", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.open_btn = ttk.Button(btns, text="এক্সেল খুলুন", command=self._open, state="disabled")
        self.open_btn.pack(side="left", padx=4)
        r += 1

        # ---- v2: Prime Bank buttons --------------------------------------------------
        sep = ttk.Separator(root, orient="horizontal")
        sep.grid(row=r, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 2))
        r += 1
        pb = ttk.Frame(root)
        pb.grid(row=r, column=0, columnspan=2, pady=(4, 2))
        self.prime_btn = ttk.Button(pb, text="Prime Bank Report", command=self._prime_dialog)
        self.prime_btn.grid(row=0, column=0, padx=4, pady=2)
        self.recpv_btn = ttk.Button(pb, text="Re-CPV সহ এক্সেল রিপোর্ট", command=self._start_recpv)
        self.recpv_btn.grid(row=0, column=1, padx=4, pady=2)
        self.email_btn = ttk.Button(pb, text="ইমেইলের জন্য কপি", command=self._email_copy, state="disabled")
        self.email_btn.grid(row=1, column=0, padx=4, pady=2)
        ttk.Button(pb, text="ছুটির তালিকা", command=self._holiday_dialog).grid(row=1, column=1, padx=4, pady=2)
        ttk.Button(pb, text="ইমেইল সিগনেচার", command=self._signature_dialog).grid(row=2, column=0, padx=4, pady=2)
        self.folder_btn = ttk.Button(pb, text="ফোল্ডার খুলুন", command=lambda: open_path(self.out_dir))
        self.folder_btn.grid(row=2, column=1, padx=4, pady=2)
        self.last_prime = None
        r += 1

        self.bar = ttk.Progressbar(root, length=420, mode="determinate")
        self.bar.grid(row=r, column=0, columnspan=2, padx=10, pady=(8, 2))
        r += 1
        self.status = tk.StringVar(value="প্রস্তুত।")
        ttk.Label(root, textvariable=self.status, wraplength=430).grid(row=r, column=0, columnspan=2, padx=10)
        r += 1
        ttk.Label(root, text="এই সফটওয়্যার শুধু তথ্য পড়ে; কিছু বদলায় না। পাসওয়ার্ড কোথাও সংরক্ষণ হয় না।",
                  foreground="#666", wraplength=430).grid(row=r, column=0, columnspan=2, padx=10, pady=(8, 0))
        self._toggle_urls()

    def _toggle_urls(self):
        if self.server.get() == config.SERVER_PRODUCTION:
            self.url_frame.grid_remove()
        else:
            self.url_frame.grid()

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.out_dir), title="এক্সেল কোথায় সেভ হবে?")
        if d:
            self.out_dir = Path(d)
            self.dir_label.config(text=str(self.out_dir))

    # ---------------------------------------------------------------- run
    def _resolve_urls(self):
        if self.server.get() == config.SERVER_PRODUCTION:
            return config.PRODUCTION["web"], config.PRODUCTION["api"]
        web = self.web.get().strip().rstrip("/")
        if not web:
            raise ValueError("ওয়েব ঠিকানা দিন (যেমন https://staging.example.com)।")
        if not web.startswith(("http://", "https://")):
            web = "https://" + web
        api = self.api.get().strip().rstrip("/") or config.derive_api_url(web)
        if not api.startswith(("http://", "https://")):
            api = "https://" + api
        return web, api

    def _common_inputs(self):
        """Validate the login part of the window. -> (web, api, email, password, days) or None."""
        try:
            web, api = self._resolve_urls()
            days = int(self.days.get())
            if not 1 <= days <= 730:
                raise ValueError
        except ValueError as exc:
            messagebox.showwarning("তথ্য ঠিক নেই", str(exc) or "দিন সংখ্যা ১ থেকে ৭৩০ এর মধ্যে দিন।")
            return None
        email, pw = self.email.get().strip(), self.password.get()
        if not email or not pw:
            messagebox.showwarning("তথ্য ঠিক নেই", "ইমেইল ও পাসওয়ার্ড দিন।")
            return None
        config.save_settings({
            "server": self.server.get(), "web": self.web.get().strip(), "api": self.api.get().strip(),
            "email": email, "days": days, "out_dir": str(self.out_dir),
        })
        return web, api, email, pw, days

    def _busy(self, text="শুরু হচ্ছে…"):
        self.cancel.clear()
        self.out_file = None
        for b in (self.go_btn, self.prime_btn, self.recpv_btn):
            b.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.bar.config(value=0, maximum=100)
        self.status.set(text)

    # ---------------------------------------------------------------- Prime Bank Report
    def _prime_dialog(self):
        if self._common_inputs() is None:
            return
        dlg = tk.Toplevel(self)
        dlg.title("Prime Bank Report")
        dlg.resizable(False, False)
        dlg.transient(self)
        f = ttk.Frame(dlg, padding=14)
        f.grid()
        pad = {"padx": 8, "pady": 4}
        mode = tk.StringVar(value="tracker")
        ttk.Radiobutton(f, text="ট্র্যাকার (প্রতিদিনের 3pm / 7pm রিপোর্ট)", variable=mode, value="tracker").grid(
            row=0, column=0, columnspan=3, sticky="w", **pad)
        ttk.Radiobutton(f, text="বিলিং রিপোর্ট (তারিখের সীমা)", variable=mode, value="billing").grid(
            row=1, column=0, columnspan=3, sticky="w", **pad)
        today = date.today()
        ttk.Label(f, text="রিপোর্টের তারিখ").grid(row=2, column=0, sticky="w", **pad)
        rdate = tk.StringVar(value=today.isoformat())
        ttk.Entry(f, textvariable=rdate, width=14).grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(f, text="সময় (শিরোনামে)").grid(row=3, column=0, sticky="w", **pad)
        slot = tk.StringVar(value=f"অটো ({slot_for()})")
        ttk.Combobox(f, textvariable=slot, width=14, state="readonly",
                     values=[f"অটো ({slot_for()})", "3pm", "7pm"]).grid(row=3, column=1, sticky="w", **pad)
        ttk.Label(f, text="কত দিন পিছনে দেখবে").grid(row=4, column=0, sticky="w", **pad)
        look = tk.StringVar(value="60")
        ttk.Spinbox(f, from_=7, to=365, textvariable=look, width=8).grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(f, text="বিলিং: শুরু").grid(row=5, column=0, sticky="w", **pad)
        d_from = tk.StringVar(value=(today - timedelta(days=30)).isoformat())
        ttk.Entry(f, textvariable=d_from, width=14).grid(row=5, column=1, sticky="w", **pad)
        ttk.Label(f, text="শেষ").grid(row=5, column=2, sticky="w", **pad)
        d_till = tk.StringVar(value=today.isoformat())
        ttk.Entry(f, textvariable=d_till, width=14).grid(row=5, column=3, sticky="w", **pad)
        ttk.Label(f, text="(তারিখ লিখুন YYYY-MM-DD, যেমন 2026-11-02)", foreground="#666").grid(
            row=6, column=0, columnspan=4, sticky="w", padx=8)
        opts = {}
        for i, (key, text, dflt) in enumerate((
                ("excel", "Excel", True), ("pdf", "PDF", True),
                ("bank", "ব্যাংক কপি (পরিষ্কার)", True), ("internal", "অভ্যন্তরীণ কপি (হলুদ চিহ্ন সহ)", True),
                ("email", "ইমেইলের জন্য কপি (ব্রাউজারে খুলবে)", True))):
            opts[key] = tk.BooleanVar(value=dflt)
            ttk.Checkbutton(f, text=text, variable=opts[key]).grid(row=7 + i, column=0, columnspan=4, sticky="w", **pad)

        def go():
            try:
                rd = datetime.strptime(rdate.get().strip(), "%Y-%m-%d").date()
                a = datetime.strptime(d_from.get().strip(), "%Y-%m-%d").date()
                b = datetime.strptime(d_till.get().strip(), "%Y-%m-%d").date()
                lk = int(look.get())
            except ValueError:
                messagebox.showwarning("তথ্য ঠিক নেই", "তারিখ YYYY-MM-DD ফরম্যাটে দিন।", parent=dlg)
                return
            if not (opts["excel"].get() or opts["pdf"].get() or opts["email"].get()):
                messagebox.showwarning("তথ্য ঠিক নেই", "Excel, PDF বা ইমেইল—অন্তত একটি বাছুন।", parent=dlg)
                return
            if (opts["excel"].get() or opts["pdf"].get()) and not (opts["bank"].get() or opts["internal"].get()):
                messagebox.showwarning("তথ্য ঠিক নেই", "ব্যাংক কপি বা অভ্যন্তরীণ কপি—অন্তত একটি বাছুন।", parent=dlg)
                return
            sl = slot.get()
            sl = sl if sl in ("3pm", "7pm") else slot_for()
            dlg.destroy()
            self._start_prime(mode.get(), rd, sl, lk, a, b, {k: v.get() for k, v in opts.items()})

        ttk.Button(f, text="তৈরি করুন", command=go).grid(row=13, column=0, columnspan=4, pady=(10, 2))
        dlg.grab_set()

    def _start_prime(self, mode, report_date, slot, lookback, d_from, d_till, opts):
        inp = self._common_inputs()
        if inp is None:
            return
        web, api, email, pw, _days = inp
        cfg = PrimeConfig(web=web, api=api, server_label=self.server.get(), email=email, password=pw,
                          days=lookback, mode=mode, report_date=report_date, slot=slot, date_from=d_from,
                          date_till=d_till, workers=int(self.settings.get("workers", config.DEFAULT_WORKERS)),
                          org_name=self.settings.get("org_name", config.DEFAULT_ORG))
        self._busy()
        self.worker = threading.Thread(target=self._work_prime, args=(cfg, opts), daemon=True)
        self.worker.start()

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

    # ---------------------------------------------------------------- Excel with Re-CPV
    def _start_recpv(self):
        inp = self._common_inputs()
        if inp is None:
            return
        web, api, email, pw, days = inp
        today = date.today()
        cfg = PrimeConfig(web=web, api=api, server_label=self.server.get(), email=email, password=pw, days=days,
                          mode="billing", date_from=today - timedelta(days=days), date_till=today,
                          workers=int(self.settings.get("workers", config.DEFAULT_WORKERS)),
                          org_name=self.settings.get("org_name", config.DEFAULT_ORG))
        self._busy()
        self.worker = threading.Thread(target=self._work_recpv, args=(cfg,), daemon=True)
        self.worker.start()

    def _work_recpv(self, cfg: PrimeConfig):
        try:
            d = collect_prime(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "write", 0, 1, "Re-CPV সহ এক্সেল তৈরি হচ্ছে…"))
            path = write_recpv_workbook(d, self.out_dir)
            self.q.put(("prime_done", [path], d))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:
            self.q.put(("error", f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}"))

    def _email_copy(self):
        d = self.last_prime
        if d is None or d.mode != "tracker":
            messagebox.showinfo("ইমেইল কপি", "আগে ট্র্যাকার ধরনে একটি Prime Bank Report তৈরি করুন।")
            return
        path = build_email_html(d, self.out_dir / f"Prime_Bank_{d.report_date:%Y-%m-%d}_{d.slot}_email.html")
        open_path(path)

    # ---------------------------------------------------------------- holidays / signature
    def _holiday_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("ছুটির তালিকা")
        dlg.transient(self)
        f = ttk.Frame(dlg, padding=12)
        f.grid()
        note = f"তালিকা {hol.last_date():%d-%m-%Y} পর্যন্ত আছে।"
        if hol.needs_update():
            note += "  ⚠ নতুন ছুটি যোগ করুন।"
        ttk.Label(f, text=note, foreground="#B00020" if hol.needs_update() else "#2E7D32").grid(row=0, column=0, sticky="w")
        box = tk.Listbox(f, width=52, height=12, selectmode="extended")
        box.grid(row=1, column=0, pady=6)

        def refresh():
            box.delete(0, "end")
            self._hol_dates = []
            for d, name in sorted(hol.load().items()):
                if d >= date.today() - timedelta(days=15):
                    box.insert("end", f"{d.isoformat()}   {name}")
                    self._hol_dates.append(d)
        refresh()
        ttk.Label(f, text="নতুন ছুটি (প্রতি লাইনে একটি):  শুরু | শেষ | নাম\nযেমন:  2027-03-09 | 2027-03-11 | Eid ul Fitr\n"
                          "এক দিনের হলে শেষ তারিখ বাদ দেওয়া যায়।", foreground="#555", justify="left").grid(row=2, column=0, sticky="w")
        txt = tk.Text(f, width=52, height=5)
        txt.grid(row=3, column=0, pady=4)

        def add():
            lines = txt.get("1.0", "end").splitlines()
            n, errs = hol.add_ranges(lines)
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
                hol.remove_date(self._hol_dates[i])
            refresh()

        b = ttk.Frame(f)
        b.grid(row=4, column=0, pady=4)
        ttk.Button(b, text="যোগ করুন", command=add).pack(side="left", padx=4)
        ttk.Button(b, text="ফাইল থেকে ইমপোর্ট", command=import_csv).pack(side="left", padx=4)
        ttk.Button(b, text="নির্বাচিত মুছুন", command=remove).pack(side="left", padx=4)
        ttk.Button(b, text="বন্ধ করুন", command=dlg.destroy).pack(side="left", padx=4)

    def _signature_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("ইমেইল সিগনেচার")
        dlg.transient(self)
        f = ttk.Frame(dlg, padding=12)
        f.grid()
        ttk.Label(f, text="‘Regards,’ এর নিচে যা থাকবে (নাম, পদবি, ফোন…):").grid(row=0, column=0, sticky="w")
        txt = tk.Text(f, width=46, height=7)
        txt.grid(row=1, column=0, pady=6)
        txt.insert("1.0", load_signature())

        def save():
            save_signature(txt.get("1.0", "end").strip())
            dlg.destroy()
        ttk.Button(f, text="সংরক্ষণ", command=save).grid(row=2, column=0)

    def _start(self):
        try:
            web, api = self._resolve_urls()
            days = int(self.days.get())
            if not 1 <= days <= 730:
                raise ValueError
        except ValueError as exc:
            messagebox.showwarning("তথ্য ঠিক নেই", str(exc) or "দিন সংখ্যা ১ থেকে ৭৩০ এর মধ্যে দিন।")
            return
        email, pw = self.email.get().strip(), self.password.get()
        if not email or not pw:
            messagebox.showwarning("তথ্য ঠিক নেই", "ইমেইল ও পাসওয়ার্ড দিন।")
            return
        config.save_settings({
            "server": self.server.get(), "web": self.web.get().strip(), "api": self.api.get().strip(),
            "email": email, "days": days, "out_dir": str(self.out_dir),
        })
        cfg = RunConfig(web=web, api=api, server_label=self.server.get(), email=email, password=pw, days=days,
                        workers=int(self.settings.get("workers", config.DEFAULT_WORKERS)),
                        org_name=self.settings.get("org_name", config.DEFAULT_ORG))
        self.cancel.clear()
        self.out_file = None
        self.go_btn.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.bar.config(value=0, maximum=100)
        self.status.set("শুরু হচ্ছে…")
        self.worker = threading.Thread(target=self._work, args=(cfg,), daemon=True)
        self.worker.start()

    def _work(self, cfg: RunConfig):
        try:
            res = collect(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "excel", 0, 1, "এক্সেল ফাইল তৈরি হচ্ছে…"))
            name = f"Verify_Report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
            path = build_workbook(res, self.out_dir / name)
            self.q.put(("done", path, res))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:                      # unexpected
            self.q.put(("error", f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}"))

    def _cancel(self):
        self.cancel.set()
        self.status.set("বাতিল হচ্ছে…")

    def _open(self):
        if self.out_file:
            open_path(self.out_file)

    def _finish_ui(self):
        self.go_btn.config(state="normal")
        self.prime_btn.config(state="normal")
        self.recpv_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.password.set("")

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, stage, done, total, text = msg
                    self.bar.config(maximum=max(total, 1), value=done)
                    self.status.set(text)
                elif kind == "done":
                    _, path, res = msg
                    self.out_file = path
                    self._finish_ui()
                    self.open_btn.config(state="normal")
                    self.bar.config(value=self.bar["maximum"])
                    txt = f"সম্পন্ন! ফাইল {len(res.files)}/{res.site_total} টি সংগৃহীত।"
                    if res.failed:
                        txt += f" ব্যর্থ: {len(res.failed)} টি (এক্সেলের 'Failed Files' শিটে)।"
                    self.status.set(txt + f"\n{path}")
                elif kind == "prime_done":
                    _, paths, d = msg
                    self.last_prime = d
                    self.out_file = paths[0] if paths else None
                    self._finish_ui()
                    self.bar.config(value=self.bar["maximum"])
                    if d.mode == "tracker":
                        self.email_btn.config(state="normal")
                    txt = f"সম্পন্ন! Complete {len(d.complete)}, Incomplete {len(d.incomplete)} সারি।"
                    if d.mode != "tracker":
                        txt = f"সম্পন্ন! মোট {len(d.all_rows)} সারি, ফাইল {len(d.files)} টি।"
                    if d.notes:
                        txt += "\n" + " ".join(d.notes[:2])
                    self.status.set(txt + f"\n{len(paths)} টি ফাইল: {self.out_dir}")
                    self.open_btn.config(state="normal")
                elif kind == "cancelled":
                    self._finish_ui()
                    self.status.set("বাতিল করা হয়েছে।")
                elif kind == "error":
                    self._finish_ui()
                    self.status.set("ব্যর্থ হয়েছে।")
                    messagebox.showerror("সমস্যা হয়েছে", msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)


def run() -> None:
    App().mainloop()
