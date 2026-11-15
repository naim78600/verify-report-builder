"""Reports page of the desktop window (tkinter) - Windows and macOS.  v10: lives inside the new window (shell.py),
Bangla or English (i18n.L), the sign-in is shared with the rest of the program."""
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
from .collect_prime import PHASE_TEXT, PrimeConfig, collect_prime, dash_line, slot_for
from .mail_templates import facts_from
from .excel import build_workbook
from .gui_mail import MailDialog, SentLogDialog, SignatureDialog
from .file_history import HistoryConfig, collect_history, parse_ids_file, parse_ids_text
from .history_excel import write_history_outputs, write_history_template
from .reports import write_prime_outputs, write_recpv_workbook
from .monthly_bill import build_month_bill, month_name, month_window
from .bill_out import pdf_from_excel, write_month_bill
from .i18n import L, error_text, progress_text
from .ui_kit import Button, Card, DateField, Entry, P, Progress, Segmented, Stepper, Tile

def stages():
    return [L("লগইন", "Sign in"), L("ফাইল সংগ্রহ", "Files"), L("অ্যাক্টিভিটি লগ", "Activity log"), L("হিসাব", "Rules"),
            L("ফাইল তৈরি", "Output")]


STAGES = stages()
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
        messagebox.showerror(L("ফাইল খোলা যায়নি", "Could not open the file"), str(exc))


class ReportsPage(tk.Frame):
    """Every report of v1-v7 (daily tracker, range, monthly bill, Re-CPV, detailed, file history) - same rules."""

    def __init__(self, master, shell):
        super().__init__(master, bg=P["bg"])
        global STAGES
        STAGES = stages()
        self.shell = shell
        self.fonts = shell.fonts
        self.settings = shell.settings
        # the sign-in is entered once on the opening screen (shell); these are the same variables
        self.server, self.web, self.api, self.email, self.password = shell.server, shell.web, shell.api, shell.email, shell.password
        self.q: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.out_dir = shell.out_dir
        self.last_prime = None
        self.smtp_password = ""                     # kept in memory only (never written to disk)
        self.out_files: list[Path] = []
        self._build()
        self._sync_ui()
        self.after(100, self._poll)

    # ================================================================== layout
    def _build(self):
        f = self.fonts
        holder = tk.Frame(self, bg=P["bg"])
        holder.pack(fill="both", expand=True)
        foot = tk.Frame(holder, bg=P["bg"], padx=26)
        foot.pack(side="bottom", fill="x", pady=(0, 14))
        self._foot = foot
        canvas = tk.Canvas(holder, bg=P["bg"], highlightthickness=0, borderwidth=0)
        vbar = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        main = tk.Frame(canvas, bg=P["bg"], padx=26, pady=20)
        win = canvas.create_window((0, 0), window=main, anchor="nw")
        self._canvas, self._vbar, self._main_win = canvas, vbar, win

        def _fit(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win, width=max(main.winfo_reqwidth(), canvas.winfo_width()))
        main.bind("<Configure>", _fit)
        canvas.bind("<Configure>", _fit)
        self._fit_scroll = _fit

        def _wheel(e):
            if self.winfo_ismapped():
                canvas.yview_scroll(-1 * (e.delta if sys.platform == "darwin" else e.delta // 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        # ---- header + tools ------------------------------------------------------
        head = tk.Frame(main, bg=P["bg"])
        head.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.page_title = tk.Label(head, text=L("রিপোর্ট", "Reports"), bg=P["bg"], fg=P["text"], font=f.title)
        self.page_title.pack(side="left")
        tools = tk.Frame(head, bg=P["bg"])
        tools.pack(side="right")
        for text, cmd in ((L("✉  ইমেইল পাঠান", "✉  Send e-mail"), self._open_mail),
                          (L("📨  পাঠানো ইমেইল", "📨  Sent e-mails"), lambda: SentLogDialog(self)),
                          (L("📂  ফোল্ডার", "📂  Folder"), lambda: open_path(self.out_dir))):
            Button(tools, text, cmd, kind="secondary", font=f.small, padx=10, pady=6).pack(side="left", padx=(6, 0))
        tk.Label(main, text=L("রিপোর্টের ধরন ও সময়সীমা বাছুন, তারপর ‘রিপোর্ট তৈরি করুন’ চাপুন।",
                              "Choose the report and the period, then press ‘Make report’."), bg=P["bg"], fg=P["mute"],
                 font=f.small).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 12))
        colA = tk.Frame(main, bg=P["bg"])
        colA.grid(row=2, column=0, sticky="n", padx=(0, 14))
        colB = tk.Frame(main, bg=P["bg"])
        colB.grid(row=2, column=1, sticky="n")

        # ---- 2 period ------------------------------------------------------------
        c2 = Card(colA, f, L("ফাইলের সময়সীমা", "File period"), L("২", "2"))
        c2.pack(fill="x")
        self.c2 = c2
        b = c2.body
        self.period = tk.StringVar(value="days")
        Segmented(b, f, [("days", L("শেষ কয়েক দিন", "Last few days")), ("range", L("তারিখ বাছুন", "Pick dates"))], self.period, self._sync_ui).pack(anchor="w", pady=(0, 8))
        d_row = tk.Frame(b, bg=P["card"])
        d_row.pack(fill="x", pady=2)
        tk.Label(d_row, text=L("শেষ", "Last"), bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.days = tk.StringVar(value=str(self.settings.get("days", config.DEFAULT_DAYS)))
        self.days_entry = Entry(d_row, f, self.days, width=5, justify="center")
        self.days_entry.pack(side="left", padx=6, ipady=4)
        tk.Label(d_row, text=L("দিনের ফাইল", "days of files"), bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.chips = []
        for n in (30, 60, 90):
            ch = Button(d_row, str(n), lambda n=n: self.days.set(str(n)), kind="secondary", font=f.tiny, padx=8, pady=3)
            ch.pack(side="left", padx=(8 if n == 30 else 3, 0))
            self.chips.append(ch)
        r_row = tk.Frame(b, bg=P["card"])
        r_row.pack(fill="x", pady=(10, 2))
        today = date.today()
        tk.Label(r_row, text=L("থেকে", "From"), bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.d_from = DateField(r_row, f, today - timedelta(days=30))
        self.d_from.pack(side="left", padx=6)
        tk.Label(r_row, text=L("পর্যন্ত", "To"), bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.d_till = DateField(r_row, f, today)
        self.d_till.pack(side="left", padx=6)
        self.period_hint = tk.Label(b, text="", bg=P["card"], fg=P["mute"], font=f.tiny, anchor="w", justify="left", wraplength=380)
        self.period_hint.pack(fill="x", pady=(8, 0))

        # ---- 3 report type -------------------------------------------------------
        c3 = Card(colB, f, L("রিপোর্টের ধরন", "Report type"), L("৩", "3"))
        c3.pack(fill="x", pady=(0, 10))
        b = c3.body
        self.rtype = tk.StringVar(value=self.settings.get("rtype", "tracker"))
        for val, title, help_ in (
                ("tracker", L("দৈনিক সাবমিশন ট্র্যাকার", "Daily submission tracker"), L("Complete + Incomplete রিপোর্ট, ইমেইলের মতো সাজানো (12:00 PM / 6:15 PM)", "Complete + Incomplete report, laid out like the e-mail (12:00 PM / 6:15 PM)")),
                ("range", L("সময়সীমার সব ফাইলের রিপোর্ট", "All files of a period"), L("বাছাই করা সময়ের সব সারি: Submitted ও Incomplete", "Every row of the chosen period: Submitted and Incomplete")),
                ("bill", L("মাসিক বিল (Card + Loan)", "Monthly bill (Card + Loan)"), L("মাস বাছুন: ওই মাসে তৈরি হওয়া সব ফাইল / Re-CPV / extra ট্রিপের বিল — Excel + PDF", "Pick a month: the bill of every file / Re-CPV / extra trip created in that month - Excel + PDF")),
                ("recpv", L("Re-CPV সহ বিস্তারিত এক্সেল", "Detailed Excel with Re-CPV"), L("প্রতি ফাইলের নিচে Re-CPV/Extra + Calculation শিট", "Re-CPV / Extra under each file + Calculation sheet")),
                ("v1", L("সাধারণ বিস্তারিত এক্সেল", "Plain detailed Excel"), L("ফাইল ও ট্রিপের পুরো রিপোর্ট (আগের ভার্সনের মতো)", "Full report of files and trips (as in the old versions)")),
                ("history", L("ফাইল হিস্টরি", "File history"), L("ফাইল নম্বরের Excel/CSV দিন: প্রতিটি ফাইলের শুরু থেকে শেষ পর্যন্ত পুরো ইতিহাস", "Give an Excel/CSV of file numbers: the whole history of each file from start to end"))):
            Tile(b, f, val, title, help_, self.rtype, self._sync_ui).pack(fill="x", pady=3)

        # ---- 2 (tracker only): date + phase --------------------------------------
        ct = Card(colA, f, L("তারিখ ও ফেজ", "Date and phase"), L("২", "2"))
        self.c_trk = ct
        b = ct.body
        self.track_row = tk.Frame(b, bg=P["card"])
        self.track_row.pack(fill="x")
        tk.Label(self.track_row, text=L("রিপোর্টের তারিখ", "Report date"), bg=P["card"], fg=P["text"], font=f.small).pack(side="left")
        self.rdate = DateField(self.track_row, f, today)
        self.rdate.pack(side="left", padx=(6, 12))
        self.rdate.var.trace_add("write", lambda *_a: self.after_idle(self._sync_ui))
        self.phase_row = tk.Frame(b, bg=P["card"])
        self.phase_row.pack(fill="x", pady=(8, 0))
        tk.Label(self.phase_row, text=L("ফেজ", "Phase"), bg=P["card"], fg=P["text"], font=f.small).pack(side="left")
        self.slot = tk.StringVar(value="auto")
        Segmented(self.phase_row, f, [("auto", L(f"অটো ({'1st' if slot_for() == '3pm' else '2nd'})", f"Auto ({'1st' if slot_for() == '3pm' else '2nd'})")), ("3pm", "1st · 12:00 PM"),
                                      ("7pm", "2nd · 6:15 PM")], self.slot, self._sync_ui).pack(side="left", padx=(8, 0))
        self.after3_var = tk.BooleanVar(value=bool(self.settings.get("after3_only", False)))
        self.after3_cb = tk.Checkbutton(b, text=L("২য় ফেজে শুধু দুপুর ১২টার পরের সাবমিশন দেখান\n(১ম ফেজে যা গেছে তা বাদ)", "2nd phase: only files submitted after 12 PM\n(what the 1st phase already sent is left out)"), variable=self.after3_var,
                                        bg=P["card"], activebackground=P["card"], font=f.tiny, fg=P["text"], anchor="w", justify="left",
                                        highlightthickness=0, selectcolor="white")
        self.day_warn = tk.Label(b, text="", bg=P["card"], fg=P["warn"], font=f.tiny, anchor="w", justify="left", wraplength=380)
        self.rule_hint = tk.Label(b, text=L("Incomplete = ড্যাশবোর্ডে এখনও Submitted হয়নি এমন ফাইলের মধ্যে শুধু Hold (কারণসহ), Finished কিন্তু Submit হয়নি, আর Partially Submitted। On Going / Created (চলমান) ফাইল আসে না। Submitted ফাইল কখনো Incomplete-এ আসে না। কারণ না পেলে ঘর হালকা নীল। লুক-ব্যাক ৯০ দিন।", "Incomplete = among the files not yet Submitted on the dashboard: only Hold (with the reason), Finished but not submitted, and Partially Submitted. On Going / Created files are not listed. A Submitted file is never Incomplete. A light-blue cell = no reason found. Look-back 90 days."),
                                  bg=P["card"], fg=P["mute"], font=f.tiny, anchor="w", justify="left", wraplength=380)
        self.rule_hint.pack(fill="x", pady=(8, 0))

        # ---- 4 outputs -----------------------------------------------------------
        c4 = Card(colA, f, L("যা তৈরি হবে", "What is made"), L("৪", "4"))
        c4.pack(fill="x", pady=(10, 0))
        self.c4 = c4
        b = c4.body
        self.opts = {}
        self.opt_boxes = []
        for key, text, dflt in (("excel", L("Excel (সম্পাদনাযোগ্য — ইমেইলে এটিই যায়)", "Excel (editable - this goes in the e-mail)"), True), ("pdf", L("PDF (ঐচ্ছিক)", "PDF (optional)"), False),
                                ("mail", L("তৈরির পর ইমেইল উইন্ডো খুলুন", "Open the e-mail window afterwards"), True)):
            self.opts[key] = tk.BooleanVar(value=self.settings.get("opt_" + key, dflt))
            cbx = tk.Checkbutton(b, text=text, variable=self.opts[key], bg=P["card"], activebackground=P["card"], font=f.body,
                                 fg=P["text"], anchor="w", highlightthickness=0, selectcolor="white", command=self._sync_ui)
            cbx.pack(fill="x", anchor="w")
            self.opt_boxes.append((key, cbx))

        # ---- 2 (monthly bill only): month ---------------------------------------------------
        cbill = Card(colA, f, L("বিলের মাস", "Bill month"), L("২", "2"))
        self.c_bill = cbill
        b = cbill.body
        mrow = tk.Frame(b, bg=P["card"])
        mrow.pack(fill="x")
        prev = (today.replace(day=1) - timedelta(days=1))
        tk.Label(mrow, text=L("মাস", "Month"), bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.bill_month = tk.StringVar(value=month_name(prev.month))
        ttk.Combobox(mrow, textvariable=self.bill_month, values=[month_name(m) for m in range(1, 13)], state="readonly", width=12,
                     font=f.body).pack(side="left", padx=(6, 12))
        tk.Label(mrow, text=L("বছর", "Year"), bg=P["card"], fg=P["text"], font=f.body).pack(side="left")
        self.bill_year = tk.StringVar(value=str(prev.year))
        ttk.Combobox(mrow, textvariable=self.bill_year, values=[str(y) for y in range(today.year - 2, today.year + 1)], state="readonly",
                     width=6, font=f.body).pack(side="left", padx=6)
        tk.Label(b, text=L("ওই মাসের ১ তারিখ থেকে শেষ তারিখ পর্যন্ত ড্যাশবোর্ডে যা তৈরি (create) হয়েছে—নতুন ফাইল, Re-CPV, extra ট্রিপ—সবকিছুর বিল। Submit হয়েছে কি না দেখা হয় না। Card ও Loan-এর আলাদা Excel + PDF তৈরি হয়; প্রতিটি Excel-এ ‘Penalty’ শিটে Apply = No করলে সেই জরিমানা বাদ যায়, আর ‘Check’ শিটে কোন সারি কেন বাদ পড়েছে তা লেখা থাকে।", "Everything created on the dashboard from the 1st to the last day of that month - new files, Re-CPV, extra trips - is billed. Submission does not matter. Card and Loan get their own Excel + PDF; in each Excel, Apply = No on the ‘Penalty’ sheet drops that penalty, and the ‘Check’ sheet says why a row was left out."),
                 bg=P["card"], fg=P["mute"], font=f.tiny, anchor="w", justify="left", wraplength=380).pack(fill="x", pady=(8, 4))
        Button(b, L("📄  সম্পাদিত বিল Excel থেকে PDF বানান", "📄  Make the PDF from an edited bill Excel"), self._bill_pdf_from_excel, kind="secondary", font=f.small, padx=10, pady=6).pack(anchor="w")

        # ---- 2/4 (file history only) -------------------------------------------------------
        ch = Card(colA, f, L("ফাইল নম্বর দিন", "Give file numbers"), L("২", "2"))
        self.c_hist = ch
        b = ch.body
        self.hist_ids: list = []
        pick = tk.Frame(b, bg=P["card"])
        pick.pack(fill="x")
        Button(pick, L("📄  Excel / CSV বাছুন", "📄  Choose Excel / CSV"), self._pick_ids_file, kind="secondary", font=f.body, padx=12, pady=7).pack(side="left")
        self.hist_file = tk.Label(pick, text=L("কোনো ফাইল বাছা হয়নি", "No file chosen"), bg=P["card"], fg=P["mute"], font=f.small, anchor="w", wraplength=210, justify="left")
        self.hist_file.pack(side="left", padx=10)
        Button(b, L("⬇  নমুনা Excel (File No + Applicant Name) সংরক্ষণ করুন", "⬇  Save the sample Excel (File No + Applicant Name)"), self._save_hist_template, kind="ghost", font=f.tiny, padx=0, pady=3).pack(anchor="w", pady=(2, 0))
        tk.Label(b, text=L("অথবা নম্বরগুলো এখানে লিখুন বা পেস্ট করুন (প্রতি লাইনে একটি):", "Or type / paste the numbers here (one per line):"), bg=P["card"], fg=P["text"],
                 font=f.small, anchor="w").pack(fill="x", pady=(10, 2))
        self.hist_text = tk.Text(b, width=46, height=5, font=f.body, relief="flat", highlightthickness=1, highlightbackground=P["line"])
        self.hist_text.pack(fill="x")
        self.hist_text.bind("<KeyRelease>", lambda _e: self._hist_count())
        self.hist_count = tk.Label(b, text="", bg=P["card"], fg=P["ok"], font=f.small, anchor="w")
        self.hist_count.pack(fill="x", pady=(4, 0))
        self.hist_refresh = tk.BooleanVar(value=False)
        tk.Checkbutton(b, text=L("সব ফাইলের তালিকা নতুন করে পড়ুন (ধীর; সাধারণত দরকার নেই)", "Read the whole file list again (slow; usually not needed)"), variable=self.hist_refresh, bg=P["card"],
                       activebackground=P["card"], font=f.tiny, fg=P["text"], anchor="w", highlightthickness=0,
                       selectcolor="white").pack(fill="x", pady=(4, 0))
        tk.Label(b, text=L("পুরো ফাইল নম্বর বা শেষের কয়েকটি অঙ্ক—দুটোই চলবে (শূন্য যোগ করতে হবে না)। কোনো সময়সীমা নেই। প্রথমবার কয়েক মিনিট লাগতে পারে; পরের বার অনেক দ্রুত। না পেলে ‘File not found’ লেখা থাকবে।", "A full file number or just its last digits - both work (no zeros to add). No time limit. The first run can take a few minutes; later runs are much faster. Numbers not found say ‘File not found’."),
                 bg=P["card"], fg=P["mute"], font=f.tiny, anchor="w", justify="left", wraplength=380).pack(fill="x", pady=(6, 0))

        # ---- action bar ----------------------------------------------------------
        bar = tk.Frame(foot, bg=P["card"], highlightbackground=P["line"], highlightthickness=1)
        bar.pack(fill="x")
        top = tk.Frame(bar, bg=P["card"])
        top.pack(fill="x", padx=14, pady=(10, 4))
        self.go_btn = Button(top, L("রিপোর্ট তৈরি করুন", "Make report"), self._go, kind="primary", font=f.big, padx=26, pady=10)
        self.go_btn.pack(side="left")
        self.cancel_btn = Button(top, L("বাতিল", "Cancel"), self._cancel, kind="danger", font=f.body, padx=14, pady=9)
        self.cancel_btn.pack(side="left", padx=10)
        self.cancel_btn.enable(False)
        self.status = tk.StringVar(value=L("প্রস্তুত।", "Ready."))
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

    @staticmethod
    def _short(p: Path, n=34) -> str:
        s = str(p)
        return s if len(s) <= n else "…" + s[-(n - 1):]

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.out_dir), title=L("রিপোর্ট কোথায় সেভ হবে?", "Where should reports be saved?"))
        if d:
            self.out_dir = Path(d)
            self.shell.set_out_dir(self.out_dir)

    def _sync_ui(self):
        hist = self.rtype.get() == "history"
        rt = self.rtype.get()
        for w in (self.c2, self.c_trk, self.c_hist, self.c4, self.c_bill):
            w.pack_forget()
        if hist:
            self.c_hist.pack(fill="x")
        elif rt == "bill":
            self.c_bill.pack(fill="x")
        else:
            (self.c_trk if rt == "tracker" else self.c2).pack(fill="x")
            self.c4.pack(fill="x", pady=(10, 0))
        self.go_btn.config(text=L("ইতিহাস তৈরি করুন", "Make history") if hist else (L("বিল তৈরি করুন", "Make bill") if rt == "bill" else L("রিপোর্ট তৈরি করুন", "Make report")))
        rng = self.period.get() == "range"
        self.days_entry.enable(not rng)
        for ch in self.chips:
            ch.enable(not rng)
        self.d_from.enable(rng)
        self.d_till.enable(rng)
        pb = rt in ("tracker", "range")
        slot = self.slot.get()
        if slot == "7pm" or (slot == "auto" and slot_for() == "7pm"):
            self.after3_cb.pack(fill="x", pady=(6, 0), after=self.phase_row)
        else:
            self.after3_cb.pack_forget()
        rd = self.rdate.get()
        if rd and rd.weekday() in (4, 5):
            self.day_warn.config(text=L("⚠ এই তারিখটি সাপ্তাহিক ছুটির দিন (শুক্র/শনি)। ছুটির দিনের সাবমিশন পরের কর্মদিবসের ট্র্যাকারে যায়।", "⚠ This date is a weekly holiday (Fri/Sat). Holiday submissions go to the next working day's tracker."))
            self.day_warn.pack(fill="x", pady=(6, 0), before=self.rule_hint)
        else:
            self.day_warn.pack_forget()
        self.period_hint.config(text=(
            L("তারিখ বাছলে ‘শেষ কয়েক দিন’ বন্ধ থাকে। ‘পর্যন্ত’ তারিখই রিপোর্টের শেষ তারিখ।", "With dates picked, ‘Last few days’ is off. The ‘To’ date is the report's last day.") if rng else
            L("‘শেষ কয়েক দিন’ থেকে আজ পর্যন্ত। নির্দিষ্ট তারিখ চাইলে ‘তারিখ বাছুন’ চাপুন।", "From ‘Last few days’ until today. For exact dates press ‘Pick dates’.")))
        for key, cbx in self.opt_boxes:
            on = pb and (key != "mail" or rt == "tracker")
            cbx.config(state="normal" if on else "disabled")

    # ================================================================== run
    def _inputs(self):
        """-> dict or None (a warning was shown)."""
        try:
            web, api = self._resolve_urls()
        except ValueError as exc:
            messagebox.showwarning(L("তথ্য ঠিক নেই", "Check the details"), str(exc))
            return None
        email, pw = self.email.get().strip(), self.password.get()
        if not email or not pw:
            messagebox.showwarning(L("তথ্য ঠিক নেই", "Check the details"), L("ইমেইল ও পাসওয়ার্ড দিন।", "Give the e-mail and password."))
            return None
        days, d_from, d_till = None, None, None
        if self.rtype.get() in ("history", "tracker", "bill"):
            days = int(self.settings.get("days", config.DEFAULT_DAYS))
        elif self.period.get() == "range":
            d_from, d_till = self.d_from.get(), self.d_till.get()
            if not d_from or not d_till:
                messagebox.showwarning(L("তারিখ ঠিক নেই", "Date not right"), L("তারিখ এভাবে লিখুন: 05-11-2026 (অথবা 📅 চেপে বাছুন)।", "Write the date like this: 05-11-2026 (or pick it with 📅)."))
                return None
            if d_from > d_till:
                messagebox.showwarning(L("তারিখ ঠিক নেই", "Date not right"), L("শুরুর তারিখ শেষ তারিখের পরে হতে পারে না।", "The start date cannot be after the end date."))
                return None
            days = max(1, (date.today() - d_from).days)
        else:
            try:
                days = int(self.days.get())
                if not 1 <= days <= 730:
                    raise ValueError
            except ValueError:
                messagebox.showwarning(L("দিন সংখ্যা ঠিক নেই", "Number of days not right"), L("দিন সংখ্যা ১ থেকে ৭৩০ এর মধ্যে দিন।", "Give a number of days between 1 and 730."))
                return None
        config.save_settings({
            "server": self.server.get(), "web": self.web.get().strip(), "api": self.api.get().strip(), "email": email,
            "days": days if not d_from else int(self.settings.get("days", config.DEFAULT_DAYS)), "out_dir": str(self.out_dir),
            "rtype": self.rtype.get(), "after3_only": self.after3_var.get(),
            **{"opt_" + k: v.get() for k, v in self.opts.items()}})
        return {"web": web, "api": api, "email": email, "pw": pw, "days": days, "from": d_from, "till": d_till}

    def _resolve_urls(self):
        label = self.server.get()
        if label == config.SERVER_PRODUCTION:
            web = config.PRODUCTION["web"]
            return web, config.PRODUCTION["api"]
        web = self.web.get().strip().rstrip("/")
        if not web.startswith("http"):
            raise ValueError(L("ওয়েব ঠিকানা লিখুন (https:// দিয়ে শুরু)।", "Write the web address (starting with https://)."))
        api = self.api.get().strip().rstrip("/") or config.derive_api_url(web)
        return web, api

    def _go(self):
        inp = self._inputs()
        if inp is None:
            return
        rt = self.rtype.get()
        workers = int(self.settings.get("workers", config.DEFAULT_WORKERS))
        org = self.settings.get("org_name", config.DEFAULT_ORG)
        if rt == "history":
            ids = self._collect_ids()
            if not ids:
                messagebox.showwarning(L("ফাইল নম্বর নেই", "No file numbers"), L("Excel/CSV বাছুন, অথবা ফাইল নম্বর (বা শেষের কয়েকটি অঙ্ক) লিখুন।", "Choose an Excel/CSV, or type file numbers (or their last digits)."))
                return
            cfg = HistoryConfig(web=inp["web"], api=inp["api"], server_label=self.server.get(), email=inp["email"],
                                password=inp["pw"], workers=workers, org_name=org, ids=ids,
                                refresh_index=self.hist_refresh.get())
            self._busy()
            self.worker = threading.Thread(target=self._work_history, args=(cfg,), daemon=True)
            self.worker.start()
            return
        if rt == "bill":
            year, month = int(self.bill_year.get()), [month_name(m) for m in range(1, 13)].index(self.bill_month.get()) + 1
            lo, hi = month_window(year, month)
            if lo > date.today():
                messagebox.showwarning(L("মাস ঠিক নেই", "Month not right"), L("এই মাস এখনো শুরু হয়নি।", "This month has not started yet."))
                return
            cfg = PrimeConfig(web=inp["web"], api=inp["api"], server_label=self.server.get(), email=inp["email"], password=inp["pw"],
                              days=inp["days"], mode="bill", date_from=lo, date_till=hi, workers=workers, org_name=org)
            self._busy()
            self.worker = threading.Thread(target=self._work_bill, args=(cfg, year, month), daemon=True)
            self.worker.start()
            return
        if rt in ("tracker", "range", "recpv"):
            mode = "tracker" if rt == "tracker" else "range"
            rdate = self.rdate.get() or date.today() if rt == "tracker" else (inp["till"] or date.today())
            slot = self.slot.get()
            slot = slot_for() if slot == "auto" else slot
            cfg = PrimeConfig(web=inp["web"], api=inp["api"], server_label=self.server.get(), email=inp["email"],
                              password=inp["pw"], days=inp["days"], mode=mode, report_date=rdate,
                              slot=slot, date_from=inp["from"],
                              date_till=inp["till"] if mode == "range" else None, workers=workers, org_name=org,
                              after3_only=bool(self.after3_var.get() and slot == "7pm" and rt == "tracker"))
            opts = {k: v.get() for k, v in self.opts.items()}
            if rt in ("tracker", "range"):
                if not (opts["excel"] or opts["pdf"]):
                    messagebox.showwarning(L("তথ্য ঠিক নেই", "Check the details"), L("Excel বা PDF—অন্তত একটি বাছুন।", "Choose at least one: Excel or PDF."))
                    return
                opts["mail"] = opts["mail"] and rt == "tracker" and opts["excel"]
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
        self.status.set(L("শুরু হচ্ছে…", "Starting…"))

    def _work_prime(self, cfg: PrimeConfig, opts: dict):
        try:
            d = collect_prime(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "write", 0, 1, L("Excel / PDF তৈরি হচ্ছে…", "Making the Excel / PDF…")))
            paths = write_prime_outputs(d, self.out_dir, excel=opts["excel"], pdf=opts["pdf"])
            self.q.put(("prime_done", paths, d, bool(opts.get("mail"))))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:                      # unexpected
            self.q.put(("error", L(f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}", f"Unexpected problem: {type(exc).__name__}: {exc}")))

    def _work_bill(self, cfg: PrimeConfig, year: int, month: int):
        try:
            d = collect_prime(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "write", 0, 1, L("বিলের Excel / PDF তৈরি হচ্ছে…", "Making the bill Excel / PDF…")))
            mb = build_month_bill(d.all_rows, year, month, date.today(), d.files)
            paths = write_month_bill(mb, self.out_dir, excel=True, pdf=True)
            self.q.put(("bill_done", paths, mb, d))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:                      # unexpected
            self.q.put(("error", L(f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}", f"Unexpected problem: {type(exc).__name__}: {exc}")))

    def _bill_pdf_from_excel(self):
        path = filedialog.askopenfilename(title=L("বিলের Excel বাছুন", "Choose the bill Excel"), initialdir=str(self.out_dir), filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            out = pdf_from_excel(Path(path))
        except PermissionError:
            messagebox.showerror(L("সমস্যা হয়েছে", "Something went wrong"), L("PDF ফাইলটি অন্য কোথাও খোলা আছে। বন্ধ করে আবার চেষ্টা করুন।", "The PDF file is open somewhere else. Close it and try again."))
            return
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror(L("সমস্যা হয়েছে", "Something went wrong"), L(f"এই Excel থেকে PDF বানানো যায়নি।\n{exc}", f"Could not make a PDF from this Excel.\n{exc}"))
            return
        self.status.set(L(f"PDF তৈরি হয়েছে: {out.name}  (Penalty শিটের Apply = Yes / No অনুযায়ী)", f"PDF made: {out.name}  (by Apply = Yes / No of the Penalty sheet)"))
        self._show_results([out], False)

    def _work_history(self, cfg: HistoryConfig):
        try:
            h = collect_history(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "write", 0, 1, L("ফাইল হিস্টরি Excel তৈরি হচ্ছে…", "Making the file history Excel…")))
            self.q.put(("hist_done", write_history_outputs(h, self.out_dir), h))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError, ValueError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:
            self.q.put(("error", L(f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}", f"Unexpected problem: {type(exc).__name__}: {exc}")))

    # ---- file history input -------------------------------------------------------------------------
    def _pick_ids_file(self):
        path = filedialog.askopenfilename(title=L("ফাইল নম্বরের Excel / CSV বাছুন", "Choose the Excel / CSV of file numbers"),
                                          filetypes=[("Excel / CSV", "*.xlsx *.xlsm *.csv *.txt"), ("All", "*.*")])
        if not path:
            return
        try:
            self.hist_ids = parse_ids_file(Path(path))
        except ValueError as exc:
            self.hist_ids = []
            messagebox.showwarning(L("ফাইল পড়া যায়নি", "Could not read the file"), str(exc))
        except Exception as exc:                                  # noqa: BLE001
            self.hist_ids = []
            messagebox.showwarning(L("ফাইল পড়া যায়নি", "Could not read the file"), f"{type(exc).__name__}: {exc}")
        self.hist_file.config(text=Path(path).name if self.hist_ids else L("কোনো ফাইল নম্বর পাওয়া যায়নি", "No file numbers found"), fg=P["text"] if self.hist_ids else P["warn"])
        self._hist_count()

    def _collect_ids(self) -> list:
        seen, out = set(), []
        for e in list(self.hist_ids) + parse_ids_text(self.hist_text.get("1.0", "end")):
            if e.uid not in seen:
                seen.add(e.uid)
                out.append(e)
        return out

    def _hist_count(self):
        ids = self._collect_ids()
        n, named = len(ids), sum(1 for e in ids if getattr(e, "name", ""))
        self.hist_count.config(text=(L(f"✓ {n} টি ফাইল নম্বর পাওয়া গেছে", f"✓ {n} file numbers found") + (L(f" (আবেদনকারীর নামসহ: {named} টি)", f" (with applicant name: {named})") if named else "")) if n else "")

    def _save_hist_template(self):
        path = filedialog.asksaveasfilename(title=L("নমুনা Excel সংরক্ষণ", "Save the sample Excel"), defaultextension=".xlsx", initialfile="File_History_Format.xlsx",
                                            filetypes=[("Excel", "*.xlsx")])
        if not path:
            return
        try:
            write_history_template(path)
        except OSError as exc:
            messagebox.showwarning(L("সংরক্ষণ করা যায়নি", "Could not save"), str(exc))
            return
        messagebox.showinfo(L("নমুনা Excel", "Sample Excel"), L(f"সংরক্ষিত হয়েছে:\n{path}\n\nA কলামে File No, B কলামে Applicant Name লিখে ‘Excel / CSV বাছুন’-এ দিন।", f"Saved:\n{path}\n\nWrite File No in column A and Applicant Name in column B, then use ‘Choose Excel / CSV’."))

    def _work_recpv(self, cfg: PrimeConfig):
        try:
            d = collect_prime(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "write", 0, 1, L("Re-CPV সহ এক্সেল তৈরি হচ্ছে…", "Making the Excel with Re-CPV…")))
            self.q.put(("prime_done", [write_recpv_workbook(d, self.out_dir)], d, False))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:
            self.q.put(("error", L(f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}", f"Unexpected problem: {type(exc).__name__}: {exc}")))

    def _work_v1(self, cfg: RunConfig):
        try:
            res = collect(cfg, lambda *a: self.q.put(("progress", *a)), self.cancel)
            self.q.put(("progress", "excel", 0, 1, L("এক্সেল ফাইল তৈরি হচ্ছে…", "Making the Excel file…")))
            name = f"Verify_Report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
            self.q.put(("v1_done", build_workbook(res, self.out_dir / name), res))
        except Cancelled:
            self.q.put(("cancelled",))
        except (AuthError, ApiError, PermissionError) as exc:
            self.q.put(("error", str(exc)))
        except Exception as exc:
            self.q.put(("error", L(f"অপ্রত্যাশিত সমস্যা: {type(exc).__name__}: {exc}", f"Unexpected problem: {type(exc).__name__}: {exc}")))

    def _cancel(self):
        self.cancel.set()
        self.status.set(L("বাতিল হচ্ছে…", "Cancelling…"))

    def _finish_ui(self):
        self.go_btn.enable(True)
        self.cancel_btn.enable(False)
        # v10: the password stays in memory for this session only (the 10 AM / 12 PM / ... jobs need it); never on disk

    def _show_results(self, paths: list[Path], mail_ok: bool, d=None):
        for w in self.result.winfo_children():
            w.destroy()
        f = self.fonts
        if d is not None and d.mode == "tracker":
            fa = facts_from(d)
            kp = tk.Frame(self.result, bg=P["card"])
            kp.pack(fill="x", pady=(0, 6))
            for label, big, small, bg, fg in (
                    ("Complete", f"{fa.complete_files}", L(f"ফাইল · {fa.complete_rows} সারি", f"files · {fa.complete_rows} rows"), P["ok_bg"], P["ok"]),
                    ("Incomplete", f"{fa.incomplete_files}", L(f"ফাইল · {fa.incomplete_rows} সারি", f"files · {fa.incomplete_rows} rows"), P["warn_bg"], P["warn"]),
                    (L("SLA পার", "SLA passed"), f"{fa.sla_breach_rows}", L("সারি", "rows"), P["warn_bg"], P["warn"]),
                    ("Partial", f"{fa.partial_files}", L("ফাইল", "files"), P["accent_soft"], P["accent_hi"]),
                    (L("কারণ নেই", "No reason"), f"{fa.reason_missing}", L("সারি (নীল ঘর)", "rows (blue cells)"), "#E3F1FD", P["navy"])):
                t = tk.Frame(kp, bg=bg, padx=10, pady=4)
                t.pack(side="left", padx=(0, 6))
                tk.Label(t, text=label, bg=bg, fg=fg, font=f.tiny).pack(anchor="w")
                tk.Label(t, text=big, bg=bg, fg=fg, font=f.h2).pack(side="left")
                tk.Label(t, text=" " + small, bg=bg, fg=fg, font=f.tiny).pack(side="left", anchor="s", pady=(0, 3))
        row = tk.Frame(self.result, bg=P["card"])
        row.pack(fill="x")
        if mail_ok:
            Button(row, L("✉  ইমেইল পাঠান", "✉  Send e-mail"), self._open_mail, kind="primary", font=f.small, padx=12, pady=5).pack(side="left", padx=(0, 8), pady=2)
        for p in paths:
            Button(row, f"{p.suffix[1:].upper()}  {p.stem[-26:]}", lambda p=p: open_path(p), kind="secondary", font=f.tiny,
                   padx=8, pady=4).pack(side="left", padx=(0, 6), pady=2)

    def _open_mail(self):
        d = self.last_prime
        if d is None or d.mode != "tracker" or not any(p.suffix.lower() == ".xlsx" for p in self.out_files):
            messagebox.showinfo(L("ইমেইল পাঠান", "Send e-mail"), L("আগে ‘দৈনিক সাবমিশন ট্র্যাকার’ তৈরি করুন (Excel সহ)।\nতারপর এখান থেকে ইমেইল পাঠানো যাবে।", "First make the ‘Daily submission tracker’ (with Excel).\nThen the e-mail can be sent from here."))
            return
        MailDialog(self, d, list(self.out_files))

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
                    self.status.set(progress_text(stage, done, total, text))
                elif kind == "prime_done":
                    _, paths, d, open_mail = msg
                    self.last_prime = d
                    self.out_files = paths
                    self._finish_ui()
                    self.bar.set(1)
                    self.stepper.set(len(STAGES))
                    if d.mode == "tracker":
                        cf, inf = len({r.file_id for r in d.complete}), len({r.file_id for r in d.incomplete})
                        txt = (L(f"সম্পন্ন!  {PHASE_TEXT.get(d.slot, d.slot)} · {d.report_date:%d-%m-%Y}  —  Complete {cf} ফাইল ({len(d.complete)} সারি) · Incomplete {inf} ফাইল ({len(d.incomplete)} সারি)", f"Done!  {PHASE_TEXT.get(d.slot, d.slot)} · {d.report_date:%d-%m-%Y}  —  Complete {cf} files ({len(d.complete)} rows) · Incomplete {inf} files ({len(d.incomplete)} rows)"))
                    else:
                        txt = L(f"সম্পন্ন!  মোট {len(d.all_rows)} সারি · ফাইল {len(d.files)} টি", f"Done!  {len(d.all_rows)} rows · {len(d.files)} files")
                    if dash_line(d):
                        txt += "\n" + dash_line(d)
                    if d.notes:
                        txt += "\n" + " ".join(n for n in d.notes[:2] if not n.startswith("ড্যাশবোর্ডের Submitted তালিকায়"))
                    self.status.set(txt)
                    self._show_results(paths, d.mode == "tracker" and any(p.suffix.lower() == ".xlsx" for p in paths), d)
                    if open_mail:
                        self.after(300, self._open_mail)
                elif kind == "bill_done":
                    _, paths, mb, d = msg
                    self.out_files = paths
                    self._finish_ui()
                    self.bar.set(1)
                    self.stepper.set(len(STAGES))
                    card, loan = mb.bills["Card"], mb.bills["Loan"]
                    txt = (L(f"সম্পন্ন!  {month_name(mb.month)} {mb.year} এর বিল  —  Card {len(card.items)} সারি · {card.grand_total:,.2f} টাকা   |   Loan {len(loan.items)} সারি · {loan.grand_total:,.2f} টাকা (জরিমানা সব Apply ধরে, VAT সহ)", f"Done!  Bill of {month_name(mb.month)} {mb.year}  —  Card {len(card.items)} rows · Tk {card.grand_total:,.2f}   |   Loan {len(loan.items)} rows · Tk {loan.grand_total:,.2f} (every penalty applied, with VAT)"))
                    if mb.excluded:
                        txt += L(f"\nবিলের বাইরে {len(mb.excluded)} টি সারি (কারণসহ ‘Check’ শিটে)।", f"\n{len(mb.excluded)} rows outside the bill (with the reason on the ‘Check’ sheet).")
                    if mb.review:
                        txt += L(f"  একবার দেখে নিন: {len(mb.review)} টি সারি (‘Check’ শিটে)।", f"  Please look at: {len(mb.review)} rows (‘Check’ sheet).")
                    if d.failed:
                        txt += L(f"\n⚠ {len(d.failed)} টি ফাইল পড়া যায়নি — বিল অসম্পূর্ণ হতে পারে, আবার চালান।", f"\n⚠ {len(d.failed)} files could not be read - the bill may be incomplete, run it again.")
                    self.status.set(txt)
                    self._show_results(paths, False)
                elif kind == "hist_done":
                    _, paths, h = msg
                    self.out_files = paths
                    self._finish_ui()
                    self.bar.set(1)
                    self.stepper.set(len(STAGES))
                    txt = L(f"সম্পন্ন!  পাওয়া গেছে {len(h.results)} টি ফাইল · পাওয়া যায়নি {len(h.not_found)} টি নম্বর", f"Done!  Found {len(h.results)} files · not found {len(h.not_found)} numbers")
                    if h.notes:
                        txt += "\n" + " ".join(h.notes[:2])
                    self.status.set(txt)
                    self._show_results(paths, False)
                elif kind == "v1_done":
                    _, path, res = msg
                    self.out_files = [path]
                    self._finish_ui()
                    self.bar.set(1)
                    self.stepper.set(len(STAGES))
                    txt = L(f"সম্পন্ন! ফাইল {len(res.files)}/{res.site_total} টি সংগৃহীত।", f"Done! {len(res.files)}/{res.site_total} files collected.")
                    if res.failed:
                        txt += L(f" ব্যর্থ: {len(res.failed)} টি (এক্সেলের 'Failed Files' শিটে)।", f" Failed: {len(res.failed)} (on the Excel's 'Failed Files' sheet).")
                    self.status.set(txt)
                    self._show_results([path], False)
                elif kind == "cancelled":
                    self._finish_ui()
                    self.bar.set(0)
                    self.stepper.set(-1)
                    self.status.set(L("বাতিল করা হয়েছে।", "Cancelled."))
                elif kind == "error":
                    self._finish_ui()
                    self.bar.set(0)
                    self.stepper.set(-1)
                    self.status.set(L("ব্যর্থ হয়েছে।", "Failed."))
                    messagebox.showerror(L("সমস্যা হয়েছে", "Something went wrong"), error_text(msg[1]))
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # ================================================================== dialogs
    def _dialog(self, title: str):
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=P["card"], padx=16, pady=14)
        dlg.transient(self.winfo_toplevel())
        dlg.resizable(False, False)
        return dlg

    def _holiday_dialog(self):
        f = self.fonts
        dlg = self._dialog(L("ছুটির তালিকা", "Holiday list"))
        warn = hol.needs_update()
        note = L(f"তালিকা {hol.last_date():%d-%m-%Y} পর্যন্ত আছে।", f"The list goes until {hol.last_date():%d-%m-%Y}.") + (L("  ⚠ নতুন ছুটি যোগ করুন।", "  ⚠ Add the new holidays.") if warn else "")
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
        tk.Label(dlg, text=L("নতুন ছুটি (প্রতি লাইনে একটি):   শুরু | শেষ | নাম\nযেমন:  2027-03-09 | 2027-03-11 | Eid ul Fitr\nএক দিনের ছুটি হলে শেষ তারিখ বাদ দিন।", "New holidays (one per line):   start | end | name\nfor example:  2027-03-09 | 2027-03-11 | Eid ul Fitr\nFor a one-day holiday leave out the end date."), bg=P["card"], fg=P["mute"], font=f.tiny, justify="left").pack(anchor="w")
        txt = tk.Text(dlg, width=54, height=4, font=f.small, relief="flat", highlightthickness=1, highlightbackground=P["line"])
        txt.pack(pady=6)

        def add():
            n, errs = hol.add_ranges(txt.get("1.0", "end").splitlines())
            if errs:
                messagebox.showwarning(L("কিছু লাইন যোগ হয়নি", "Some lines were not added"), "\n".join(errs), parent=dlg)
            if n:
                txt.delete("1.0", "end")
                messagebox.showinfo(L("যোগ হয়েছে", "Added"), L(f"{n} দিন যোগ হয়েছে।", f"{n} days added."), parent=dlg)
            refresh()

        def import_csv():
            path = filedialog.askopenfilename(parent=dlg, title=L("CSV বা টেক্সট ফাইল বাছুন", "Choose a CSV or text file"),
                                              filetypes=[("CSV / Text", "*.csv *.txt"), ("All", "*.*")])
            if path:
                n, errs = hol.import_file(Path(path))
                messagebox.showinfo(L("ইমপোর্ট", "Import"), L(f"{n} দিন যোগ হয়েছে।", f"{n} days added.") + ("\n" + "\n".join(errs) if errs else ""), parent=dlg)
                refresh()

        def remove():
            for i in box.curselection():
                hol.remove_date(dates[i])
            refresh()

        row = tk.Frame(dlg, bg=P["card"])
        row.pack(pady=(4, 0))
        for text, cmd, kind in ((L("যোগ করুন", "Add"), add, "primary"), (L("ফাইল থেকে ইমপোর্ট", "Import from a file"), import_csv, "secondary"),
                                (L("নির্বাচিত মুছুন", "Delete selected"), remove, "secondary"), (L("বন্ধ", "Close"), dlg.destroy, "secondary")):
            Button(row, text, cmd, kind=kind, font=f.small, padx=10, pady=6).pack(side="left", padx=4)


def run() -> None:
    from .shell import Shell
    Shell().mainloop()
