"""v10 pages: Today, BS Tracker, Office receive, Reminders, Verifiers, Settings (the report page is gui.ReportsPage)."""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import bs_rules, config, i18n
from . import bs_tracker as BT
from . import reminders as R
from .assets_path import asset
from .client import is_bd_mobile, normalize_phone
from .gui import open_path
from .i18n import L
from .ui_kit import Button, Entry, P, Segmented

BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def num(n) -> str:
    return str(n).translate(BN_DIGITS) if not i18n.is_en() else str(n)


# ============================================================================================ building blocks
class Page(tk.Frame):
    title_bn, title_en = "", ""

    def __init__(self, master, shell):
        super().__init__(master, bg=P["bg"])
        self.shell, self.f = shell, shell.fonts
        self.head = tk.Frame(self, bg=P["bg"])
        self.head.pack(fill="x", padx=30, pady=(26, 14))
        left = tk.Frame(self.head, bg=P["bg"])
        left.pack(side="left")
        self.sub = tk.Label(left, text="", bg=P["bg"], fg=P["mute"], font=self.f.small)
        self.sub.pack(anchor="w")
        tk.Label(left, text=L(self.title_bn, self.title_en), bg=P["bg"], fg=P["text"], font=self.f.title).pack(anchor="w")
        self.actions = tk.Frame(self.head, bg=P["bg"])
        self.actions.pack(side="right")
        self.body = tk.Frame(self, bg=P["bg"])
        self.body.pack(fill="both", expand=True, padx=30, pady=(0, 24))

    def action(self, text, cmd, kind="secondary"):
        b = Button(self.actions, text, cmd, kind=kind, font=self.f.small if kind == "secondary" else self.f.btn, padx=14, pady=8)
        b.pack(side="left", padx=(8, 0))
        return b

    def card(self, parent, **pack):
        c = tk.Frame(parent, bg=P["card"], highlightbackground=P["line"], highlightthickness=1)
        if pack:
            c.pack(**pack)
        return c

    def kpi(self, parent, label, value="–", color=None, hint=""):
        c = self.card(parent)
        tk.Label(c, text=label, bg=P["card"], fg=P["mute"], font=self.f.small).pack(anchor="w", padx=16, pady=(14, 0))
        v = tk.Label(c, text=value, bg=P["card"], fg=color or P["text"], font=(self.f.family, 24, "bold"))
        v.pack(anchor="w", padx=16)
        h = tk.Label(c, text=hint, bg=P["card"], fg=P["mute"], font=self.f.tiny)
        h.pack(anchor="w", padx=16, pady=(0, 14))
        c.value, c.hint = v, h
        return c

    def table(self, parent, cols, height=12):
        """cols = [(key, heading, width, anchor)] -> Treeview with a scrollbar."""
        box = tk.Frame(parent, bg=P["card"])
        tv = ttk.Treeview(box, columns=[c[0] for c in cols], show="headings", height=height, selectmode="extended")
        for key, head, width, anchor in cols:
            tv.heading(key, text=head, anchor=anchor)
            tv.column(key, width=width, anchor=anchor, stretch=key == cols[-1][0] or width >= 200)
        sb = ttk.Scrollbar(box, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        tv.pack(side="left", fill="both", expand=True)
        for tag, fg in (("bad", P["bad"]), ("warn", P["warn"]), ("ok", P["ok"]), ("mute", P["mute"]), ("blue", P["accent"])):
            tv.tag_configure(tag, foreground=fg)
        tv.tag_configure("zebra", background="#FAFBFD")
        return box, tv

    def need_data(self) -> bool:
        if self.shell.data["at"] is None:
            messagebox.showinfo(L("একটু অপেক্ষা করুন", "One moment"),
                                L("ড্যাশবোর্ড থেকে তথ্য আনা হচ্ছে। শেষ হলে আবার চাপুন।", "The dashboard is being read. Try again when it is done."))
            return False
        return True


# ============================================================================================ Today
class HomePage(Page):
    title_bn, title_en = "আজকের কাজ", "Today"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("↻  ড্যাশবোর্ড থেকে আনুন", "↻  Read the dashboard"), lambda: shell.refresh_data("manual"))
        self.action(L("দৈনিক ট্র্যাকার বানান", "Make the daily tracker"), lambda: shell.show("tracker"), kind="dark")
        self.sched = self.card(self.body, fill="x")
        tk.Label(self.sched, text=L("আজকের সময়সূচি", "Today's schedule"), bg=P["card"], fg=P["text"], font=self.f.h3).pack(anchor="w", padx=18, pady=(14, 8))
        self.slots = tk.Frame(self.sched, bg=P["card"])
        self.slots.pack(fill="x", padx=18, pady=(0, 16))
        grid = tk.Frame(self.body, bg=P["bg"])
        grid.pack(fill="x", pady=14)
        self.k_open = self.kpi(grid, L("চলমান ফাইল", "Open files"), hint="ON GOING + HOLD")
        self.k_sla = self.kpi(grid, L("SLA পার / আজ শেষ", "SLA passed / due today"), color=P["bad"])
        self.k_bs = self.kpi(grid, L("বাকি BS", "Pending BS"), color=P["warn"])
        self.k_rep = self.kpi(grid, L("WhatsApp উত্তর", "WhatsApp replies"), color=P["ok"])
        for i, k in enumerate((self.k_open, self.k_sla, self.k_bs, self.k_rep)):
            k.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            grid.grid_columnconfigure(i, weight=1, uniform="k")
        att = self.card(self.body, fill="both", expand=True)
        tk.Label(att, text=L("নজর দিতে হবে", "Needs attention"), bg=P["card"], fg=P["text"], font=self.f.h3).pack(anchor="w", padx=18, pady=(14, 8))
        box, self.tv = self.table(att, [("st", L("অবস্থা", "Status"), 120, "w"), ("file", "File No", 190, "w"),
                                        ("what", L("কী বাকি", "What is left"), 300, "w"), ("ver", L("ভেরিফায়ার", "Verifier"), 160, "w"),
                                        ("rep", L("শেষ উত্তর", "Last reply"), 260, "w")], height=9)
        box.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    def on_data(self):
        self.refresh()

    def refresh(self):
        now = datetime.now()
        self.sub.config(text=f"{now:%A, %d %B %Y}")
        for w in self.slots.winfo_children():
            w.destroy()
        st = R.load_state()
        ds = R.day_state(st)
        checks = self.shell.settings.get("bs_checks", {}).get(date.today().isoformat(), [])
        slots = [("10:00", "10am", L("রিমাইন্ডার রাউন্ড (সব চলমান/হোল্ড)", "Reminder round (all on-going / hold)")),
                 ("12:00", "12pm", L("১ম ফেজ ট্র্যাকার + BS চেক", "1st phase tracker + BS check")),
                 ("01:00", "1pm", L("রিমাইন্ডার রাউন্ড", "Reminder round")),
                 ("04:00", "4pm", L("রিমাইন্ডার রাউন্ড", "Reminder round")),
                 ("06:15", "615pm", L("২য় ফেজ ট্র্যাকার + BS চেক", "2nd phase tracker + BS check"))]
        for i, (clock, key, text) in enumerate(slots):
            done = key in ds["rounds"] or key in checks
            col = tk.Frame(self.slots, bg=P["card"])
            col.grid(row=0, column=i, sticky="nsew")
            self.slots.grid_columnconfigure(i, weight=1, uniform="s")
            dot = tk.Canvas(col, width=18, height=18, bg=P["card"], highlightthickness=0)
            dot.create_oval(2, 2, 16, 16, fill=P["ok"] if done else "#E5E7EB", outline="")
            dot.pack(anchor="w")
            tk.Label(col, text=clock, bg=P["card"], fg=P["text"], font=self.f.h3).pack(anchor="w", pady=(4, 0))
            tk.Label(col, text=("✓ " if done else "") + text, bg=P["card"], fg=P["ok"] if done else P["mute"], font=self.f.tiny,
                     wraplength=170, justify="left").pack(anchor="w")
        files = self.shell.data["files"]
        if not files:
            return
        open_files = [f for fl in files.values() for f in fl if f.get("status_code") in (2, 3)]
        today = date.today()
        sla_pass = [f for f in open_files if f.get("sla") and f["sla"].date() < today]
        sla_today = [f for f in open_files if f.get("sla") and f["sla"].date() == today]
        self.k_open.value.config(text=num(len(open_files)))
        self.k_sla.value.config(text=f"{num(len(sla_pass))} / {num(len(sla_today))}")
        self.k_sla.hint.config(text=L("এদের রিমাইন্ডার আগে যায়", "these are reminded first"))
        pend = BT.pending_bs(self.shell.bs_all())
        off = sum(1 for r in pend if r.bs_type == "Offline")
        self.k_bs.value.config(text=num(len(pend)))
        self.k_bs.hint.config(text=L(f"অফলাইন {num(off)} · অনলাইন {num(len(pend) - off)}", f"offline {off} · online {len(pend) - off}"))
        sm = R.day_summary(st)
        self.k_rep.value.config(text=num(sm["replied"]))
        self.k_rep.hint.config(text=L(f"সমস্যা {num(sm['problems'])} · উত্তর আসেনি {num(sm['no_reply'])}",
                                      f"problems {sm['problems']} · no reply {sm['no_reply']}"))
        last = {r["phone"]: r for r in ds["replies"]}
        phones = self.shell.data["phones"]
        self.tv.delete(*self.tv.get_children())
        rows = []
        for f in sla_pass + sla_today:
            for c in f.get("concerns") or []:
                for t in c.get("trips") or []:
                    if t.get("status_code") in R.OPEN_TRIP:
                        ph = (phones.get(t.get("agent_id")) or {}).get("phone", "")
                        rp = last.get(ph)
                        rows.append(((L("SLA পার", "SLA passed"), "bad") if f in sla_pass else (L("আজ শেষ", "Due today"), "warn"),
                                     f["file_no"], f"{t.get('type', '')} · {t.get('status', '')}", t.get("verifier", ""),
                                     (f"{R.REPLY_TEXT.get(rp['kind'], '')} {('· ' + rp['reason']) if rp.get('reason') else ''}" if rp else
                                      L("উত্তর আসেনি", "no reply"))))
        for (st_txt, tag), fno, what, ver, rep in rows[:60]:
            self.tv.insert("", "end", values=(st_txt, fno, what, ver, rep), tags=(tag,))


# ============================================================================================ BS Tracker
class BSPage(Page):
    title_bn, title_en = "BS ট্র্যাকার", "BS Tracker"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("Signed list আপলোড", "Upload signed list"), self.upload_signed)
        self.action(L("কুরিয়ার", "Courier"), self.courier)
        self.action(L("অফিস রিসিভ", "Office receive"), lambda: shell.show("receive"))
        self.action(L("মাসিক Excel", "Monthly Excel"), self.monthly_excel, kind="dark")
        bar = tk.Frame(self.body, bg=P["bg"])
        bar.pack(fill="x", pady=(0, 12))
        today = date.today()
        self.month = tk.StringVar(value=f"{today:%Y-%m}")
        months = [f"{(today.year * 12 + today.month - 1 - i) // 12}-{(today.year * 12 + today.month - 1 - i) % 12 + 1:02d}"
                  for i in range(0, 12)]                          # every month, none skipped
        tk.Label(bar, text=L("মাস (trip create)", "Month (trip created)"), bg=P["bg"], fg=P["mute"], font=self.f.small).pack(side="left")
        cb = ttk.Combobox(bar, textvariable=self.month, values=months, width=9, state="readonly")
        cb.pack(side="left", padx=(6, 16))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.month_changed())
        self.org = tk.StringVar(value="all")
        Segmented(bar, self.f, [("all", L("দুই ক্লায়েন্ট", "Both clients")), ("Prime Bank PLC", "Prime Bank"),
                                ("LankaBangla Finance Limited", "LankaBangla")], self.org, self.refresh).pack(side="left")
        self.only = tk.StringVar(value="all")
        Segmented(bar, self.f, [("all", L("সব", "All")), ("pending", L("বাকি", "Pending")), ("no", L("তোলা হয়নি", "Not collected"))],
                  self.only, self.refresh).pack(side="left", padx=12)
        self.funnel = self.card(self.body, fill="x")
        self.fcells = []
        for i, lab in enumerate((L("১ · trip create", "1 · trip created"), L("২ · ব্যাংক থেকে তোলা", "2 · collected"),
                                 L("৩ · অফিসে জমা", "3 · in the office"), L("৪ · কুরিয়ার", "4 · courier"),
                                 L("৫ · ব্যাংক রিসিভ", "5 · bank received"))):
            c = tk.Frame(self.funnel, bg=P["card"])
            c.grid(row=0, column=i, sticky="nsew", padx=16, pady=12)
            self.funnel.grid_columnconfigure(i, weight=1, uniform="f")
            tk.Label(c, text=lab, bg=P["card"], fg=P["mute"], font=self.f.tiny).pack(anchor="w")
            v = tk.Label(c, text="–", bg=P["card"], fg=P["text"], font=(self.f.family, 20, "bold"))
            v.pack(anchor="w")
            s = tk.Label(c, text="", bg=P["card"], fg=P["mute"], font=self.f.tiny)
            s.pack(anchor="w")
            self.fcells.append((v, s))
        tbl = self.card(self.body, fill="both", expand=True, pady=(12, 0))
        box, self.tv = self.table(tbl, [("created", L("Created", "Created"), 110, "w"), ("trip", "Trip ID", 70, "w"),
                                        ("file", "File No", 160, "w"), ("bank", L("ব্যাংক", "Bank"), 150, "w"),
                                        ("type", L("ধরন", "Type"), 64, "w"), ("ver", L("ভেরিফায়ার", "Verifier"), 110, "w"),
                                        ("out", L("রিমার্ক থেকে ফলাফল", "Outcome (from remarks)"), 190, "w"),
                                        ("now", L("এখন কোথায়", "Now"), 120, "w")], height=14)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.rows: list = []
        self.month_rows: dict = {}

    def on_data(self):
        self.month_rows.clear()
        self.refresh()

    def month_changed(self):
        y, m = map(int, self.month.get().split("-"))
        lo = date(y, m, 1)
        if (date.today() - lo).days > BT_LOOKBACK and (y, m) not in self.month_rows:
            self.load_old_month(y, m)
        self.refresh()

    def load_old_month(self, y, m):
        """A month older than the 90-day window: read it on its own (both clients, the month + 90 days before it)."""
        from .collect import RunConfig, collect
        sh = self.shell
        try:
            web, api = sh.resolve()
        except ValueError:
            return
        email, pw, label = sh.email.get().strip(), sh.password.get(), sh.server.get()
        self.sub.config(text=L("পুরনো মাস পড়া হচ্ছে…", "Reading the older month…"))

        def work():
            out = []
            for org in ("Prime Bank PLC", "LankaBangla Finance Limited"):
                try:
                    days = (date.today() - date(y, m, 1)).days + 1
                    res = collect(RunConfig(web=web, api=api, server_label=label, email=email, password=pw, days=days,
                                            org_name=org))
                    out += BT.bs_rows(res.files, org, sh.data["phones"], month=(y, m))
                except Exception:                                   # noqa: BLE001
                    continue
            self.month_rows[(y, m)] = out
            sh.q.put(("call", self.refresh))                         # back on the window's own thread
        threading.Thread(target=work, daemon=True).start()

    def current_rows(self) -> list:
        y, m = map(int, self.month.get().split("-"))
        if (y, m) in self.month_rows:
            rows = self.month_rows[(y, m)]
            store = BT.load_store()
            for r in rows:                                          # the person's entries may have changed since
                s = store.get(str(r.trip_id), {})
                r.office, r.courier, r.bank_received = s.get("office") or {}, s.get("courier") or {}, s.get("bank_received") or {}
        else:
            rows = [r for r in self.shell.bs_all() if r.created and (r.created.year, r.created.month) == (y, m)]
        if self.org.get() != "all":
            rows = [r for r in rows if r.org == self.org.get()]
        return rows

    def refresh(self):
        rows = self.current_rows()
        self.rows = rows
        got = [r for r in rows if r.collected]
        no = [r for r in rows if r.outcome in bs_rules.NOT_COLLECTED_SET]
        office = [r for r in rows if r.office]
        cour = [r for r in rows if r.courier.get("no")]
        bank = [r for r in rows if r.bank_received]
        vals = [(len(rows), L(f"অফলাইন {num(sum(1 for r in rows if r.bs_type == 'Offline'))}", f"offline {sum(1 for r in rows if r.bs_type == 'Offline')}")),
                (len(got), L(f"তোলা হয়নি {num(len(no))}", f"not collected {len(no)}")),
                (len(office), L(f"বাকি {num(max(0, len(got) - len(office)))}", f"pending {max(0, len(got) - len(office))}")),
                (len(cour), ""), (len(bank), "")]
        for (v, s), (n, hint) in zip(self.fcells, vals):
            v.config(text=num(n))
            s.config(text=hint)
        when = self.shell.data["at"]
        self.sub.config(text=L(f"{self.month.get()} · ড্যাশবোর্ড {when:%I:%M %p}" if when else self.month.get(),
                               f"{self.month.get()} · dashboard {when:%I:%M %p}" if when else self.month.get()))
        show = rows
        if self.only.get() == "pending":
            show = BT.pending_bs(rows)
        elif self.only.get() == "no":
            show = no
        self.tv.delete(*self.tv.get_children())
        prev, zebra = None, False
        for r in show:
            if (r.org, r.file_id) != prev:
                zebra, prev = not zebra, (r.org, r.file_id)
            tag = "ok" if r.collected else ("bad" if r.outcome in bs_rules.NOT_COLLECTED_SET else ("warn" if r.outcome == bs_rules.CHECK else "mute"))
            self.tv.insert("", "end", iid=f"{r.org}|{r.trip_id}",
                           values=(f"{r.created:%d/%m %I:%M %p}" if r.created else "", r.trip_id, r.file_no, r.bank or r.bank_written,
                                   L("অনলাইন", "Online") if r.bs_type == "Online" else L("অফলাইন", "Offline"), r.verifier,
                                   r.outcome + (f" · {r.outcome_note}" if r.outcome_note else ""), r.where),
                           tags=(tag,) + (("zebra",) if zebra else ()))

    def selected(self) -> list:
        ids = set(self.tv.selection())
        return [r for r in self.rows if f"{r.org}|{r.trip_id}" in ids]

    def monthly_excel(self):
        rows = self.current_rows()
        if not rows:
            messagebox.showinfo(L("BS নেই", "No BS"), L("এই মাসে কোনো BS trip নেই।", "No BS trips in this month."))
            return
        y, m = map(int, self.month.get().split("-"))
        orgname = {"all": "Prime_LankaBangla", "Prime Bank PLC": "Prime_Bank", "LankaBangla Finance Limited": "LankaBangla"}[self.org.get()]
        path = self.shell.out_dir / f"BS_Tracker_{orgname}_{y}-{m:02d}.xlsx"
        title = f"{orgname.replace('_', ' ')} · BS Tracker · {date(y, m, 1):%B %Y}"
        try:
            BT.write_bs_excel(rows, path, title)
        except PermissionError:
            messagebox.showerror(L("সমস্যা হয়েছে", "Something went wrong"), L("Excel ফাইলটি খোলা আছে। বন্ধ করে আবার চেষ্টা করুন।",
                                                                            "The Excel file is open. Close it and try again."))
            return
        open_path(path)

    def upload_signed(self):
        path = filedialog.askopenfilename(title=L("ক্লায়েন্টের সই করা রিসিভ লিস্ট", "The client's signed received list"),
                                          filetypes=[("Excel / CSV / PDF / Photo", "*.xlsx *.xlsm *.csv *.pdf *.png *.jpg *.jpeg *.webp"),
                                                     ("All", "*.*")])
        if not path:
            return
        rows = self.current_rows() or self.shell.bs_all()
        try:
            text = BT.read_text_any(Path(path))
        except Exception as exc:                                    # noqa: BLE001
            messagebox.showwarning(L("ফাইল পড়া যায়নি", "Could not read the file"), str(exc))
            return
        found = BT.match_signed_list(rows, text)
        store = BT.load_store()
        n = BT.apply_signed_list(store, rows, found, path)
        BT.save_store(store)
        sent = [r for r in rows if r.collected and (r.office or r.courier.get("no"))]
        missing = [r for r in sent if r.trip_id not in found and not r.bank_received]
        messagebox.showinfo(L("রিসিভ লিস্ট", "Received list"),
                            L(f"{num(n)} টি BS ব্যাংক রিসিভ করেছে বলে পাওয়া গেছে।\nপাঠানো হয়েছে কিন্তু লিস্টে নেই: {num(len(missing))} টি"
                              + ("\n\n" + "\n".join(f"• {r.file_no} ({r.trip_id})" for r in missing[:15]) if missing else ""),
                              f"{n} bank statements found as received by the bank.\nSent but not in the list: {len(missing)}"
                              + ("\n\n" + "\n".join(f"• {r.file_no} ({r.trip_id})" for r in missing[:15]) if missing else "")))
        self.refresh()

    def courier(self):
        sel = self.selected()
        if not sel:
            messagebox.showinfo(L("সারি বাছুন", "Choose rows"), L("তালিকা থেকে এক বা একাধিক BS বাছুন (Ctrl চেপে)।",
                                                                 "Choose one or more BS in the list (hold Ctrl)."))
            return
        CourierDialog(self, sel)


BT_LOOKBACK = 85


class CourierDialog(tk.Toplevel):
    def __init__(self, page: BSPage, rows):
        super().__init__(page)
        self.page, self.rows, f = page, rows, page.f
        self.title(L("কুরিয়ার", "Courier"))
        self.configure(bg=P["card"], padx=20, pady=16)
        self.transient(page.winfo_toplevel())
        first = rows[0].courier
        tk.Label(self, text=L(f"{num(len(rows))} টি BS", f"{len(rows)} bank statements"), bg=P["card"], fg=P["text"], font=f.h3).pack(anchor="w")
        self.name = tk.StringVar(value=first.get("name") or page.shell.settings.get("courier_name", ""))
        self.no = tk.StringVar(value=first.get("no", ""))
        self.status = tk.StringVar(value=first.get("status") or "Booked")
        self.slip = tk.StringVar(value=first.get("slip", ""))
        for lab, var in ((L("কুরিয়ারের নাম", "Courier name"), self.name), (L("কুরিয়ার নম্বর", "Courier number"), self.no)):
            r = tk.Frame(self, bg=P["card"])
            r.pack(fill="x", pady=4)
            tk.Label(r, text=lab, bg=P["card"], fg=P["mute"], font=f.small, width=14, anchor="w").pack(side="left")
            Entry(r, f, var, width=30).pack(side="left", ipady=3)
        r = tk.Frame(self, bg=P["card"])
        r.pack(fill="x", pady=4)
        tk.Label(r, text=L("অবস্থা", "Status"), bg=P["card"], fg=P["mute"], font=f.small, width=14, anchor="w").pack(side="left")
        ttk.Combobox(r, textvariable=self.status, values=BT.COURIER_STATUS, state="readonly", width=16).pack(side="left")
        r = tk.Frame(self, bg=P["card"])
        r.pack(fill="x", pady=4)
        tk.Label(r, text=L("স্লিপের ছবি", "Slip picture"), bg=P["card"], fg=P["mute"], font=f.small, width=14, anchor="w").pack(side="left")
        Button(r, L("ছবি বাছুন", "Choose picture"), self.pick, font=f.small, padx=10, pady=5).pack(side="left")
        tk.Label(r, textvariable=self.slip, bg=P["card"], fg=P["mute"], font=f.tiny, wraplength=220).pack(side="left", padx=8)
        Button(self, L("সেভ করুন", "Save"), self.save, kind="primary", font=f.btn, padx=18, pady=8).pack(anchor="e", pady=(12, 0))

    def pick(self):
        p = filedialog.askopenfilename(parent=self, filetypes=[("Picture", "*.png *.jpg *.jpeg *.webp *.bmp")])
        if p:
            self.slip.set(p)

    def save(self):
        store = BT.load_store()
        for r in self.rows:
            BT.set_courier(store, r.trip_id, name=self.name.get().strip(), no=self.no.get().strip(), status=self.status.get(),
                           slip=self.slip.get() or None if self.slip.get() != r.courier.get("slip") else None)
        BT.save_store(store)
        config.save_settings({"courier_name": self.name.get().strip()})
        self.destroy()
        self.page.refresh()


# ============================================================================================ Office receive
class ReceivePage(Page):
    title_bn, title_en = "অফিসে BS রিসিভ", "Office receive"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("নমুনা ফর্ম (Excel)", "Blank form (Excel)"), self.template)
        self.action(L("পূরণ করা ফর্ম আপলোড", "Upload filled form"), self.upload)
        self.action(L("“আজ রিসিভ হয়েছে” A4 প্রিন্ট", "“Received today” A4 print"), self.print_sheet, kind="dark")
        cols = tk.Frame(self.body, bg=P["bg"])
        cols.pack(fill="both", expand=True)
        form = self.card(cols)
        form.pack(side="left", fill="y")
        f = self.f
        inner = tk.Frame(form, bg=P["card"], padx=20, pady=18)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=L("নতুন রিসিভ", "New receive"), bg=P["card"], fg=P["text"], font=f.h3).pack(anchor="w")
        tk.Label(inner, text=L("Trip ID বা File No", "Trip ID or File No"), bg=P["card"], fg=P["text"], font=f.small).pack(anchor="w", pady=(14, 4))
        self.key = tk.StringVar()
        e = Entry(inner, f, self.key, width=30)
        e.pack(fill="x", ipady=6)
        e.bind("<KeyRelease>", lambda _e: self.lookup())
        e.bind("<Return>", lambda _e: self.add())
        self.info = tk.Label(inner, text=L("লিখুন, বাকিটা নিজে আসবে", "Type it; the rest fills itself"), bg="#F9FAFB", fg=P["mute"],
                             font=f.small, justify="left", anchor="w", padx=12, pady=10, wraplength=300)
        self.info.pack(fill="x", pady=(10, 4))
        self.pages_v = tk.StringVar()
        self.recv = tk.StringVar(value=shell.settings.get("receiver_name") or (shell.email.get().split("@")[0].title()))
        self.note = tk.StringVar()
        two = tk.Frame(inner, bg=P["card"])
        two.pack(fill="x", pady=(8, 0))
        for i, (lab, var, w) in enumerate(((L("পাতা", "Pages"), self.pages_v, 8), (L("কে রিসিভ করল", "Received by"), self.recv, 18))):
            c = tk.Frame(two, bg=P["card"])
            c.grid(row=0, column=i, sticky="w", padx=(0 if i == 0 else 12, 0))
            tk.Label(c, text=lab, bg=P["card"], fg=P["text"], font=f.small).pack(anchor="w")
            Entry(c, f, var, width=w).pack(anchor="w", ipady=5)
        tk.Label(inner, text=L("মন্তব্য (ঐচ্ছিক)", "Note (optional)"), bg=P["card"], fg=P["text"], font=f.small).pack(anchor="w", pady=(10, 2))
        Entry(inner, f, self.note, width=30).pack(fill="x", ipady=5)
        Button(inner, L("রিসিভ যোগ করুন", "Add receive"), self.add, kind="primary", font=f.btn, padx=20, pady=10).pack(fill="x", pady=(18, 0))
        self.msg = tk.Label(inner, text="", bg=P["card"], fg=P["ok"], font=f.small, wraplength=300, justify="left")
        self.msg.pack(anchor="w", pady=(8, 0))
        right = self.card(cols)
        right.pack(side="left", fill="both", expand=True, padx=(16, 0))
        self.count = tk.Label(right, text="", bg=P["card"], fg=P["text"], font=f.h3)
        self.count.pack(anchor="w", padx=18, pady=(14, 8))
        box, self.tv = self.table(right, [("t", L("সময়", "Time"), 70, "w"), ("file", "File No / Trip", 200, "w"),
                                          ("bank", L("ব্যাংক", "Bank"), 150, "w"), ("giver", L("কে দিল", "Given by"), 130, "w"),
                                          ("pages", L("পাতা", "Pages"), 60, "w"), ("note", L("মন্তব্য", "Note"), 160, "w")], height=14)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.match: list = []

    def lookup(self):
        rows = BT.find_row(self.shell.bs_all(), self.key.get())
        self.match = rows
        if not self.key.get().strip():
            self.info.config(text=L("লিখুন, বাকিটা নিজে আসবে", "Type it; the rest fills itself"), fg=P["mute"])
        elif not rows:
            self.info.config(text=L("এই নম্বরে কোনো BS পাওয়া যায়নি (ড্যাশবোর্ড থেকে আবার আনুন?)",
                                    "No BS with this number (read the dashboard again?)"), fg=P["warn"])
        else:
            r = rows[0]
            more = L(f"\nএই ফাইলে {num(len(rows))} টি BS: সবগুলো যোগ হবে", f"\nThis file has {len(rows)} BS: all are added") if len(rows) > 1 else ""
            self.info.config(text=f"{r.file_no}\n{L('ব্যাংক', 'Bank')}: {r.bank or r.bank_written} · "
                                  f"{L('অনলাইন', 'Online') if r.bs_type == 'Online' else L('অফলাইন', 'Offline')}\n"
                                  f"{L('কে দিল', 'Given by')}: {r.verifier}{more}", fg=P["text"])

    def add(self):
        self.lookup()
        if not self.match:
            return
        store = BT.load_store()
        for r in self.match:
            BT.set_office(store, r.trip_id, giver=r.verifier, receiver=self.recv.get().strip(), pages=self.pages_v.get().strip(),
                          note=self.note.get().strip(), file_no=r.file_no, bank=r.bank or r.bank_written)
        BT.save_store(store)
        config.save_settings({"receiver_name": self.recv.get().strip()})
        self.msg.config(text=L(f"✓ যোগ হয়েছে: {self.match[0].file_no}", f"✓ Added: {self.match[0].file_no}"))
        self.key.set("")
        self.pages_v.set("")
        self.note.set("")
        self.lookup()
        self.refresh()

    def refresh(self):
        items = BT.office_today(BT.load_store())
        self.sub.config(text=f"{date.today():%d %B %Y}")
        self.count.config(text=L(f"আজ রিসিভ হয়েছে · {num(len(items))} টি", f"Received today · {len(items)}"))
        self.tv.delete(*self.tv.get_children())
        for tid, o in items:
            self.tv.insert("", "end", values=(o.get("at", "")[11:16], f"{o.get('file_no', '')} · {tid}", o.get("bank", ""), o.get("giver", ""),
                                              o.get("pages", ""), o.get("note", "")))

    def print_sheet(self):
        path = self.shell.out_dir / f"BS_Received_Today_{date.today():%Y-%m-%d}.xlsx"
        try:
            BT.write_receive_sheet(BT.load_store(), path)
        except PermissionError:
            messagebox.showerror(L("সমস্যা হয়েছে", "Something went wrong"), L("ফাইলটি খোলা আছে। বন্ধ করে আবার চেষ্টা করুন।",
                                                                            "The file is open. Close it and try again."))
            return
        if sys.platform.startswith("win") and messagebox.askyesno(L("প্রিন্ট", "Print"), L("এখনই প্রিন্টারে পাঠাবেন?", "Send it to the printer now?")):
            import os
            try:
                os.startfile(str(path), "print")                     # type: ignore[attr-defined]
                return
            except OSError:
                pass
        open_path(path)

    def template(self):
        p = filedialog.asksaveasfilename(defaultextension=".xlsx", initialfile="BS_Office_Receive_Form.xlsx", filetypes=[("Excel", "*.xlsx")])
        if p:
            BT.write_receive_template(Path(p))
            open_path(Path(p))

    def upload(self):
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if not p:
            return
        try:
            items = BT.read_receive_upload(Path(p))
        except Exception as exc:                                    # noqa: BLE001
            messagebox.showwarning(L("ফাইল পড়া যায়নি", "Could not read the file"), str(exc))
            return
        rows = self.shell.bs_all()
        store = BT.load_store()
        ok, miss = 0, []
        for it in items:
            hit = BT.find_row(rows, it["key"])
            if not hit:
                miss.append(it["key"])
                continue
            for r in hit:
                BT.set_office(store, r.trip_id, giver=it["giver"] or r.verifier, receiver=it["receiver"], pages=it["pages"],
                              note=it["note"], when=it["when"], file_no=r.file_no, bank=it["bank"] or r.bank or r.bank_written)
                ok += 1
        BT.save_store(store)
        messagebox.showinfo(L("আপলোড", "Upload"), L(f"{num(ok)} টি BS রিসিভ হিসেবে যোগ হয়েছে।", f"{ok} BS added as received.")
                            + (L(f"\nপাওয়া যায়নি: {', '.join(miss[:10])}", f"\nNot found: {', '.join(miss[:10])}") if miss else ""))
        self.refresh()


# ============================================================================================ Reminders
class RemindersPage(Page):
    title_bn, title_en = "রিমাইন্ডার (WhatsApp)", "Reminders (WhatsApp)"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("হেল্পার সেটআপ", "Helper setup"), self.setup)
        self.action(L("দিনের সারাংশ", "Day summary"), self.summary)
        self.action(L("WhatsApp Web খুলুন", "Open WhatsApp Web"), shell.open_whatsapp, kind="green")
        bar = tk.Frame(self.body, bg=P["bg"])
        bar.pack(fill="x", pady=(0, 12))
        self.round = tk.StringVar(value=R.due_round({}) or "1pm")
        tk.Label(bar, text=L("রাউন্ড", "Round"), bg=P["bg"], fg=P["mute"], font=self.f.small).pack(side="left")
        Segmented(bar, self.f, [(k, R.ROUND_LABEL[k]) for k, _t in R.ROUNDS], self.round).pack(side="left", padx=8)
        Button(bar, L("এই রাউন্ড এখনই তৈরি করুন", "Prepare this round now"), self.prepare, kind="primary", font=self.f.small, padx=12, pady=6).pack(side="left", padx=8)
        self.tab = tk.StringVar(value="all")
        Segmented(bar, self.f, [("all", L("সব", "All")), ("replied", L("উত্তর এসেছে", "Replied")), ("problem", L("সমস্যা", "Problem")),
                                ("none", L("উত্তর আসেনি", "No reply"))], self.tab, self.refresh).pack(side="right")
        grid = tk.Frame(self.body, bg=P["bg"])
        grid.pack(fill="x", pady=(0, 12))
        self.k = [self.kpi(grid, L("এই রাউন্ডে", "In this round")), self.kpi(grid, L("আপনি পাঠিয়েছেন", "You sent"), color=P["accent"]),
                  self.kpi(grid, L("উত্তর এসেছে", "Replied"), color=P["ok"]), self.kpi(grid, L("সমস্যা জানিয়েছে", "Problems"), color=P["bad"])]
        for i, k in enumerate(self.k):
            k.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            grid.grid_columnconfigure(i, weight=1, uniform="k")
        tbl = self.card(self.body, fill="both", expand=True)
        box, self.tv = self.table(tbl, [("p", L("অগ্রাধিকার", "Priority"), 120, "w"), ("ver", L("ভেরিফায়ার", "Verifier"), 150, "w"),
                                        ("files", L("ফাইল", "Files"), 260, "w"), ("voice", L("ভয়েস", "Voice"), 130, "w"),
                                        ("state", L("অবস্থা", "State"), 120, "w"), ("rep", L("উত্তর (সফটওয়্যার যা বুঝল)", "Reply (as understood)"), 260, "w")],
                                  height=12)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.nowa = tk.Label(self.body, text="", bg=P["bad_bg"], fg=P["bad"], font=self.f.small, anchor="w", justify="left", padx=14, pady=8,
                             wraplength=900)

    def prepare(self):
        if not self.need_data():
            return
        self.shell.prepare_round(self.round.get())

    def refresh(self):
        st = R.load_state()
        ds = R.day_state(st)
        rk = self.shell.helper.round_key or (sorted(ds["rounds"], key=lambda k: ds["rounds"][k]["prepared"])[-1] if ds["rounds"] else None)
        due = R.due_round(st)
        self.sub.config(text=(L(f"এখনকার রাউন্ড: {R.ROUND_LABEL[rk]}", f"Current round: {R.ROUND_LABEL[rk]}") if rk else
                              L("আজ এখনো কোনো রাউন্ড তৈরি হয়নি", "No round prepared yet today"))
                        + (L(f" · বাকি: {R.ROUND_LABEL[due]}", f" · due: {R.ROUND_LABEL[due]}") if due else ""))
        items = ds["rounds"][rk]["items"] if rk else []
        last = {}
        for rp in ds["replies"]:
            last[rp["phone"]] = rp
        self.k[0].value.config(text=num(len(items)))
        self.k[1].value.config(text=num(sum(1 for i in items if i.get("sent"))))
        self.k[2].value.config(text=num(sum(1 for i in items if i["phone"] in last)))
        self.k[3].value.config(text=num(sum(1 for i in items if last.get(i["phone"], {}).get("kind") == R.PROBLEM)))
        self.tv.delete(*self.tv.get_children())
        tab = self.tab.get()
        voice_name = {"sla_passed": L("SLA পার", "SLA passed"), "appointment_today": L("আজ অ্যাপয়েন্টমেন্ট", "Appointment today"),
                      "bs_submit": L("BS জমা দিন", "Hand in BS"), "general": L("সাধারণ", "General")}
        for it in items:
            rp = last.get(it["phone"])
            kind = rp["kind"] if rp else None
            if tab == "replied" and not rp or tab == "problem" and kind != R.PROBLEM or tab == "none" and rp:
                continue
            pr = it.get("priority", 3)
            tag = "bad" if kind == R.PROBLEM else ("ok" if kind in (R.GOING, R.DONE) else ("bad" if pr == 0 else ("warn" if pr in (1, 2) else "")))
            self.tv.insert("", "end", values=(R.PRIORITY_TEXT.get(pr, ""), it["verifier"], ", ".join(it.get("files", []))[:120],
                                              voice_name.get(it.get("voice"), ""),
                                              (L(f"পাঠানো {it['sent'][11:16]}", f"sent {it['sent'][11:16]}") if it.get("sent") else L("তৈরি", "ready")),
                                              (f"{R.REPLY_TEXT.get(kind, kind)}" + (f" · “{rp['text'][:60]}”" if rp else "")) if rp else "—"),
                           tags=(tag,) if tag else ())
        no = (ds["rounds"][rk].get("no_whatsapp", []) if rk else []) + [
            {"verifier": i["verifier"], "phone": i["phone"]} for i in items if i["phone"] in R.NO_WA_CACHE]
        if no:
            self.nowa.config(text=L("🔴 WhatsApp নেই / নম্বর নেই: ", "🔴 No WhatsApp / no number: ")
                             + ", ".join(f"{n['verifier']} ({n['phone'] or '—'})" for n in no[:30])
                             + L("  ·  ‘ভেরিফায়ার’ পেজে নম্বর ঠিক করুন।", "  ·  fix the number on the ‘Verifiers’ page."))
            self.nowa.pack(fill="x", pady=(10, 0))
        else:
            self.nowa.pack_forget()

    def summary(self):
        s = R.day_summary(R.load_state())
        dlg = tk.Toplevel(self)
        dlg.title(L("দিনের সারাংশ", "Day summary"))
        dlg.configure(bg=P["card"], padx=20, pady=16)
        dlg.transient(self.winfo_toplevel())
        tk.Label(dlg, text=L(f"আজ: পাঠানো {num(s['sent'])} · উত্তর {num(s['replied'])} · সমস্যা {num(s['problems'])} · উত্তর আসেনি {num(s['no_reply'])}",
                             f"Today: sent {s['sent']} · replied {s['replied']} · problems {s['problems']} · no reply {s['no_reply']}"),
                 bg=P["card"], fg=P["text"], font=self.f.h3).pack(anchor="w", pady=(0, 10))
        box, tv = self.table(dlg, [("v", L("ভেরিফায়ার", "Verifier"), 160, "w"), ("r", L("রাউন্ড", "Rounds"), 70, "w"),
                                   ("s", L("পাঠানো", "Sent"), 70, "w"), ("l", L("শেষ উত্তর", "Last reply"), 120, "w"),
                                   ("why", L("সমস্যার কারণ", "Problem reason"), 260, "w"), ("f", L("ফাইল", "Files"), 220, "w")], height=14)
        box.pack(fill="both", expand=True)
        for r in s["rows"]:
            tv.insert("", "end", values=(r["verifier"], r["rounds"], r["sent"], R.REPLY_TEXT.get(r["last"], "—") if r["last"] else "—",
                                         r["reason"], ", ".join(r["files"])[:120]), tags=("bad",) if r["last"] == R.PROBLEM else ())

    def setup(self):
        folder = asset("whatsapp_helper")
        msg = L("WhatsApp হেল্পার একবার Chrome-এ যোগ করতে হবে (১ মিনিট):\n\n"
                "১. Chrome-এ ঠিকানা লিখুন:  chrome://extensions\n"
                "২. ডান দিকের উপরে ‘Developer mode’ চালু করুন\n"
                "৩. ‘Load unpacked’ চাপুন, তারপর যে ফোল্ডারটি এখন খুলবে সেটি বাছুন\n"
                "৪. web.whatsapp.com খুলুন: ডান দিকের নিচে ‘Barikoi helper’ দেখাবে\n\n"
                "হেল্পার নিজে কখনো Send চাপে না। প্রতিটি চ্যাট খুলে মেসেজ লিখে ও ভয়েস যুক্ত করে রাখে, Send আপনি চাপবেন।",
                "Add the WhatsApp helper to Chrome once (1 minute):\n\n"
                "1. In Chrome go to:  chrome://extensions\n"
                "2. Turn on ‘Developer mode’ (top right)\n"
                "3. Press ‘Load unpacked’ and choose the folder that opens now\n"
                "4. Open web.whatsapp.com: ‘Barikoi helper’ shows at the bottom right\n\n"
                "The helper never presses Send. It opens each chat with the message typed in and the voice attached; you press Send.")
        messagebox.showinfo(L("হেল্পার সেটআপ", "Helper setup"), msg)
        open_path(folder)


# ============================================================================================ Verifiers
class VerifiersPage(Page):
    title_bn, title_en = "ভেরিফায়ার", "Verifiers"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("↻  নম্বর আবার আনুন", "↻  Read numbers again"), lambda: shell.refresh_data("manual"))
        edit = self.card(self.body, fill="x")
        row = tk.Frame(edit, bg=P["card"], padx=18, pady=14)
        row.pack(fill="x")
        self.sel_name = tk.Label(row, text=L("তালিকা থেকে একজনকে বাছুন", "Choose someone in the list"), bg=P["card"], fg=P["text"], font=self.f.h3)
        self.sel_name.pack(side="left")
        self.phone = tk.StringVar()
        tk.Label(row, text=L("WhatsApp নম্বর", "WhatsApp number"), bg=P["card"], fg=P["mute"], font=self.f.small).pack(side="left", padx=(24, 6))
        Entry(row, self.f, self.phone, width=18).pack(side="left", ipady=4)
        Button(row, L("সেভ", "Save"), self.save, kind="primary", font=self.f.small, padx=14, pady=6).pack(side="left", padx=8)
        Button(row, L("ড্যাশবোর্ডের নম্বরে ফেরত", "Back to the dashboard number"), self.reset, font=self.f.small, padx=10, pady=6).pack(side="left")
        tbl = self.card(self.body, fill="both", expand=True, pady=(12, 0))
        box, self.tv = self.table(tbl, [("name", L("নাম", "Name"), 200, "w"), ("phone", L("নম্বর", "Number"), 150, "w"),
                                        ("src", L("কোথা থেকে", "From"), 140, "w"), ("wa", "WhatsApp", 160, "w"),
                                        ("open", L("চলমান ট্রিপ", "Open trips"), 100, "w")], height=16)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.tv.bind("<<TreeviewSelect>>", lambda _e: self.pick())
        self.sel = None

    def on_data(self):
        self.refresh()

    def refresh(self):
        phones = self.shell.data["phones"]
        ov = self.shell.phone_overrides()
        open_trips: dict = {}
        for fl in self.shell.data["files"].values():
            for f in fl:
                if f.get("status_code") in R.OPEN_FILE:
                    for c in f.get("concerns") or []:
                        for t in c.get("trips") or []:
                            if t.get("status_code") in R.OPEN_TRIP and t.get("agent_id") is not None:
                                open_trips[t["agent_id"]] = open_trips.get(t["agent_id"], 0) + 1
        ids = sorted(set(phones) | {int(k) for k in ov if str(k).isdigit()}, key=lambda i: (-(open_trips.get(i, 0)), (phones.get(i) or {}).get("name", "")))
        self.tv.delete(*self.tv.get_children())
        red = 0
        for vid in ids:
            ph = ov.get(str(vid)) or (phones.get(vid) or {}).get("phone", "")
            bad = not is_bd_mobile(ph) or ph in R.NO_WA_CACHE
            red += bad
            wa = (L("🔴 WhatsApp নেই", "🔴 not on WhatsApp") if ph in R.NO_WA_CACHE else
                  (L("🔴 নম্বর ঠিক নেই", "🔴 number not valid") if not is_bd_mobile(ph) else L("✓ আছে", "✓ ok")))
            self.tv.insert("", "end", iid=str(vid), values=((phones.get(vid) or {}).get("name", str(vid)), ph or "—",
                                                            L("আপনি বদলেছেন", "changed by you") if str(vid) in ov else L("ড্যাশবোর্ড", "dashboard"),
                                                            wa, num(open_trips.get(vid, 0))), tags=("bad",) if bad else ())
        self.sub.config(text=L(f"মোট {num(len(ids))} জন · লাল {num(red)} জন", f"{len(ids)} people · red {red}"))

    def pick(self):
        s = self.tv.selection()
        if not s:
            return
        self.sel = s[0]
        vals = self.tv.item(s[0], "values")
        self.sel_name.config(text=vals[0])
        self.phone.set("" if vals[1] == "—" else vals[1])

    def save(self):
        if not self.sel:
            return
        ph = normalize_phone(self.phone.get())
        if not is_bd_mobile(ph):
            messagebox.showwarning(L("নম্বর ঠিক নেই", "Number not valid"), L("বাংলাদেশের মোবাইল নম্বর দিন (01XXXXXXXXX)।",
                                                                           "Give a Bangladesh mobile number (01XXXXXXXXX)."))
            return
        ov = self.shell.phone_overrides()
        ov[self.sel] = ph
        config.save_settings({"phone_overrides": ov})
        self.shell.settings["phone_overrides"] = ov
        R.NO_WA_CACHE.discard(ph)
        self.refresh()

    def reset(self):
        if not self.sel:
            return
        ov = self.shell.phone_overrides()
        ov.pop(self.sel, None)
        config.save_settings({"phone_overrides": ov})
        self.shell.settings["phone_overrides"] = ov
        self.refresh()


# ============================================================================================ Settings
class SettingsPage(Page):
    title_bn, title_en = "সেটিংস", "Settings"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        f = self.f
        c = self.card(self.body, fill="x")
        inner = tk.Frame(c, bg=P["card"], padx=20, pady=16)
        inner.pack(fill="x")

        def line(label, widget):
            r = tk.Frame(inner, bg=P["card"])
            r.pack(fill="x", pady=8)
            tk.Label(r, text=label, bg=P["card"], fg=P["mute"], font=f.small, width=18, anchor="w").pack(side="left")
            widget(r).pack(side="left")
        line(L("ভাষা", "Language"), lambda r: Segmented(r, f, [("bn", "বাংলা"), ("en", "English")], shell.lang, self.lang_changed))
        self.dir = tk.Label(inner, text="", bg=P["card"])
        line(L("রিপোর্ট সেভের জায়গা", "Reports folder"), lambda r: Button(r, str(shell.out_dir)[-60:], self.choose_dir, font=f.small, padx=10, pady=6))
        line(L("ছুটির তালিকা", "Holiday list"), lambda r: Button(r, L("📅  খুলুন", "📅  Open"), shell.reports._holiday_dialog, font=f.small, padx=10, pady=6))
        from .gui_mail import SentLogDialog, SignatureDialog
        line(L("ইমেইল সিগনেচার", "E-mail signature"), lambda r: Button(r, L("🖋  বদলান", "🖋  Change"), lambda: SignatureDialog(shell.reports), font=f.small, padx=10, pady=6))
        line(L("পাঠানো ইমেইল", "Sent e-mails"), lambda r: Button(r, L("📨  দেখুন", "📨  Show"), lambda: SentLogDialog(shell.reports), font=f.small, padx=10, pady=6))
        line(L("WhatsApp হেল্পার", "WhatsApp helper"), lambda r: Button(r, L("ফোল্ডার খুলুন", "Open folder"), lambda: open_path(asset("whatsapp_helper")), font=f.small, padx=10, pady=6))
        line(L("সাইন আউট", "Sign out"), lambda r: Button(r, L("সাইন আউট", "Sign out"), self.sign_out, kind="danger", font=f.small, padx=10, pady=6))
        tk.Label(self.body, text=L("Excel / PDF রিপোর্ট সবসময় ইংরেজিতে (ব্যাংক যেভাবে পড়ে)। শুধু প্রোগ্রামের স্ক্রিন বাংলা / ইংরেজি হয়।",
                                   "Excel / PDF reports are always in English (as the bank reads them). Only the program's screens change."),
                 bg=P["bg"], fg=P["mute"], font=f.small).pack(anchor="w", pady=(12, 0))

    def lang_changed(self):
        i18n.set_lang(self.shell.lang.get())
        config.save_settings({"lang": self.shell.lang.get()})
        self.shell.build_main("settings")

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=str(self.shell.out_dir))
        if d:
            self.shell.set_out_dir(Path(d))
            self.shell.build_main("settings")

    def sign_out(self):
        self.shell.password.set("")
        self.shell.signed_in = False
        self.shell.data.update(files={}, phones={}, at=None)
        self.shell.login_screen()
