"""v10 pages: Today, BS Tracker, Office receive, Reminders, Verifiers, Settings (the report page is gui.ReportsPage)."""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from datetime import date, datetime, time
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import bs_rules, config, i18n
from . import bs_tracker as BT
from . import reminders as R
from .assets_path import asset
from .client import is_bd_mobile, normalize_phone
from .gui import open_path
from .helper_server import open_chrome_extensions
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
    """V12 'আজ' (Naim, 18-11-2026: very simple): ONE card with the thing to do now + one green button, three numbers in the
    dashboard's own words (On Going, Hold, SLA passed), and the rest of today's schedule.  Test files are never shown."""
    title_bn, title_en = "আজ", "Today"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("↻  ড্যাশবোর্ড থেকে আনুন", "↻  Read the dashboard"), lambda: shell.refresh_data("manual"))
        hint(self.head, self.f, L("ড্যাশবোর্ডের নতুন তথ্য আনে (নিজেও সময়মতো আনে)", "Brings the newest dashboard data (also done by itself)"),
             side="right")
        # ---- the one thing to do now
        self.now = tk.Frame(self.body, bg=P["card"], highlightbackground=P["accent"], highlightthickness=2)
        self.now.pack(fill="x")
        left = tk.Frame(self.now, bg=P["card"])
        left.pack(side="left", fill="x", expand=True, padx=24, pady=20)
        self.now_when = tk.Label(left, text="", bg=P["card"], fg=P["accent"], font=self.f.h3)
        self.now_when.pack(anchor="w")
        self.now_what = tk.Label(left, text="", bg=P["card"], fg=P["text"], font=(self.f.family, 18, "bold"))
        self.now_what.pack(anchor="w")
        self.now_how = tk.Label(left, text="", bg=P["card"], fg=P["mute"], font=self.f.small, wraplength=560, justify="left")
        self.now_how.pack(anchor="w", pady=(2, 0))
        self.now_btn = Button(self.now, L("শুরু করুন", "Start"), self.do_now, kind="primary", font=self.f.big, padx=28, pady=14)
        self.now_btn.pack(side="right", padx=24)
        # ---- three numbers, dashboard words
        grid = tk.Frame(self.body, bg=P["bg"])
        grid.pack(fill="x", pady=16)
        self.k_go = self.kpi(grid, "On Going", hint=L("কাজ চলছে", "work running"))
        self.k_hold = self.kpi(grid, "Hold", color=P["warn"], hint=L("কারণ লিখে আটকে আছে", "stopped with a reason"))
        self.k_sla = self.kpi(grid, L("SLA পার হয়েছে", "SLA passed"), color=P["bad"], hint=L("এদের reminder আগে যায়", "reminded first"))
        for i, k in enumerate((self.k_go, self.k_hold, self.k_sla)):
            k.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            grid.grid_columnconfigure(i, weight=1, uniform="k")
        # ---- today's schedule
        tk.Label(self.body, text=L("আজকের সময়সূচি (সফটওয়্যার নিজে চালায়)", "Today's schedule (the software runs it)"), bg=P["bg"],
                 fg=P["text"], font=self.f.h3).pack(anchor="w", pady=(4, 6))
        self.sched = tk.Frame(self.body, bg=P["bg"])
        self.sched.pack(fill="x", anchor="w")
        self._now_cmd = None

    def on_data(self):
        self.refresh()

    def _schedule(self) -> list:
        st = R.load_state()
        ds = R.day_state(st)
        checks = self.shell.settings.get("bs_checks", {}).get(date.today().isoformat(), [])
        out = []
        for key, t in R.ROUNDS:
            what = R.ROUND_WHAT[R.ROUND_KIND[key]]
            out.append((t, key, L(f"Reminder: {what[0]}", f"Reminder: {what[1]}"), key in ds["rounds"], "round"))
        out += [(time(12, 0), "12pm", L("১ম ফেজ ট্র্যাকার + BS হিসাব", "1st phase tracker + BS check"), "12pm" in checks, "tracker"),
                (time(18, 15), "615pm", L("২য় ফেজ ট্র্যাকার + BS হিসাব", "2nd phase tracker + BS check"), "615pm" in checks, "tracker")]
        return sorted(out, key=lambda x: x[0])

    def refresh(self):
        now = datetime.now()
        self.sub.config(text=f"{now:%A, %d %B %Y}" + L(" · সবুজ বাটনটাই এখনকার কাজ", " · the green button is the job now"))
        sched = self._schedule()
        for w in self.sched.winfo_children():
            w.destroy()
        for t, key, text, done, _k in sched:
            row = tk.Frame(self.sched, bg=P["bg"])
            row.pack(fill="x", pady=2)
            tk.Label(row, text=("✓ " if done else "   ") + t.strftime("%I:%M %p").lstrip("0"), bg=P["bg"],
                     fg=P["ok"] if done else P["side_tx"], font=self.f.btn, width=11, anchor="w").pack(side="left")
            tk.Label(row, text=text, bg=P["bg"], fg=P["mute"] if done else P["text"], font=self.f.small, anchor="w").pack(side="left")
        # the job now: the latest passed slot that is not done, else the next one
        st = R.load_state()
        ds = R.day_state(st)
        rk = R.due_round(st, now)
        sent_all = True
        if ds["rounds"]:
            last_rk = sorted(ds["rounds"], key=lambda k: ds["rounds"][k]["prepared"])[-1]
            items = ds["rounds"][last_rk]["items"]
            sent_all = all(i.get("sent") for i in items)
        if rk or (ds["rounds"] and not sent_all):
            key = rk or last_rk
            n = len(ds["rounds"][key]["items"]) if key in ds["rounds"] else 0
            self.now_when.config(text=L(f"এখন করার কাজ · {R.ROUND_LABEL[key]}", f"The job now · {R.ROUND_LABEL[key]}"))
            self.now_what.config(text=L(f"Reminder পাঠান ({num(n)} জন)" if n else "Reminder তৈরি করে পাঠান",
                                        f"Send the reminder ({n} people)" if n else "Prepare and send the reminder"))
            self.now_how.config(text=L("চাপলে WhatsApp-এ প্রথম চ্যাট খুলবে। মেসেজ ও ভয়েস তৈরি থাকবে, আপনি শুধু Send চাপবেন।",
                                       "WhatsApp opens the first chat with the message and the voice ready; you only press Send."))
            self._now_cmd = lambda: self.shell.show("reminders")
        else:
            nxt = next(((t, text) for t, key, text, done, _k in sched if not done and t > now.time()), None)
            self.now_when.config(text=L("এখন কিছু বাকি নেই", "Nothing waiting now"))
            self.now_what.config(text=L("দৈনিক ট্র্যাকার বানান", "Make the daily tracker"))
            self.now_how.config(text=(L(f"পরের কাজ {nxt[0]:%I:%M %p}-এ: {nxt[1]}। ", f"Next at {nxt[0]:%I:%M %p}: {nxt[1]}. ") if nxt else "")
                                + L("চাইলে এখনই ট্র্যাকার Excel + PDF বানাতে পারেন।", "You can make the tracker Excel + PDF now."))
            self._now_cmd = lambda: self.shell.show("tracker")
        files = self.shell.data["files"]
        if not files:
            return
        live = [f for fl in files.values() for f in fl if "test" not in (f.get("file_no") or "").lower()]
        go = [f for f in live if f.get("status_code") == 2]
        hold = [f for f in live if f.get("status_code") == 3]
        today = date.today()
        sla_pass = [f for f in go + hold if f.get("sla") and f["sla"].date() < today]
        self.k_go.value.config(text=num(len(go)))
        self.k_hold.value.config(text=num(len(hold)))
        self.k_sla.value.config(text=num(len(sla_pass)))

    def do_now(self):
        if self._now_cmd:
            self._now_cmd()


# ============================================================================================ BS Tracker
def hint(parent, f, text, side=None, bg=None, wrap=260):
    """The small grey line that says what a button does (Naim: an instruction under every button)."""
    lab = tk.Label(parent, text=text, bg=bg or parent.cget("bg"), fg=P["mute"], font=f.tiny, wraplength=wrap, justify="left")
    if side:
        lab.pack(side=side, padx=(8, 0))
    else:
        lab.pack(anchor="w")
    return lab


class BSPage(Page):
    """V12 BS (Naim, 18-11-2026): press the button for what happened - three big cards; the Online BS line (slip photos from
    WhatsApp, saved by date / trip / verifier); 'who still holds how many BS' with the bank and the day it was withdrawn."""
    title_bn, title_en = "Bank Statement", "Bank Statement"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("মাসের Excel", "Monthly Excel"), self.monthly_excel)
        bar = tk.Frame(self.body, bg=P["bg"])
        bar.pack(fill="x", pady=(0, 10))
        today = date.today()
        self.month = tk.StringVar(value=f"{today:%Y-%m}")
        months = [f"{(today.year * 12 + today.month - 1 - i) // 12}-{(today.year * 12 + today.month - 1 - i) % 12 + 1:02d}"
                  for i in range(0, 12)]                          # every month, none skipped
        tk.Label(bar, text=L("মাস", "Month"), bg=P["bg"], fg=P["mute"], font=self.f.small).pack(side="left")
        cb = ttk.Combobox(bar, textvariable=self.month, values=months, width=9, state="readonly")
        cb.pack(side="left", padx=(6, 16))
        cb.bind("<<ComboboxSelected>>", lambda _e: self.month_changed())
        self.org = tk.StringVar(value="all")
        Segmented(bar, self.f, [("all", L("দুই ক্লায়েন্ট", "Both clients")), ("Prime Bank PLC", "Prime Bank"),
                                ("LankaBangla Finance Limited", "LankaBangla")], self.org, self.refresh).pack(side="left")
        hint(bar, self.f, L("যা ঘটল, সেই বাটন চাপুন। বাকি হিসাব সফটওয়্যার রাখে।", "Press the button for what happened; the software keeps the rest."),
             side="left", wrap=360)
        # ---- three cards
        cards = tk.Frame(self.body, bg=P["bg"])
        cards.pack(fill="x")
        self.cards = []
        for i, (title, how, btn, cmd, kind) in enumerate((
                (L("Verifier BS অফিসে দিল", "Verifier brought the BS"), L("Offline BS হাতে পেলে চাপুন, Trip ID লিখে টিক দিন",
                 "When an offline BS reaches you, press and tick its Trip ID"), L("অফিসে পেলাম", "Received in office"),
                 lambda: shell.show("receive"), "primary"),
                (L("ব্যাংকে পাঠালাম", "Sent to the bank"), L("অফিসে থাকা BS-এর কুরিয়ারের নাম, স্লিপ নম্বর আর স্লিপের ছবি দিন",
                 "Courier name, slip number and slip picture of the BS in the office"), L("কুরিয়ার দিন", "Add courier"), self.courier, "soft"),
                (L("ব্যাংক বুঝে পেল", "The bank received them"), L("ব্যাংকের সই করা তালিকার ছবি / PDF / Excel দিন, নিজে মিলিয়ে নেবে",
                 "Give the bank's signed list (photo / PDF / Excel); it is matched by itself"), L("তালিকা দিন", "Give the list"),
                 self.upload_signed, "soft"))):
            c = tk.Frame(cards, bg=P["card"], highlightbackground=P["accent"] if i == 0 else P["line"], highlightthickness=2 if i == 0 else 1)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 12, 0))
            cards.grid_columnconfigure(i, weight=1, uniform="c")
            v = tk.Label(c, text="–", bg=P["card"], fg=P["accent"] if i == 0 else P["text"], font=(self.f.family, 24, "bold"))
            v.pack(anchor="w", padx=18, pady=(14, 0))
            tk.Label(c, text=title, bg=P["card"], fg=P["text"], font=self.f.h3).pack(anchor="w", padx=18)
            tk.Label(c, text=how, bg=P["card"], fg=P["mute"], font=self.f.tiny, wraplength=240, justify="left").pack(anchor="w", padx=18, pady=(2, 8))
            Button(c, btn, cmd, kind=kind, font=self.f.btn, padx=14, pady=10).pack(fill="x", padx=18, pady=(0, 16))
            self.cards.append(v)
        # ---- online BS line
        on = self.card(self.body, fill="x", pady=(12, 0))
        left = tk.Frame(on, bg=P["card"])
        left.pack(side="left", fill="x", expand=True, padx=18, pady=12)
        tk.Label(left, text=L("Online BS: verifier নিজে ব্যাংকে জমা দেয়", "Online BS: the verifier hands it in at the bank"),
                 bg=P["card"], fg=P["text"], font=self.f.h3).pack(anchor="w")
        tk.Label(left, text=L("WhatsApp-এ “জমা দিয়েছি” + স্লিপের ছবি পাঠালে নিজে জমা হয় (তারিখ › Trip ID › verifier ফোল্ডারে)",
                              "“Handed in” + the slip photo on WhatsApp is saved by itself (date › Trip ID › verifier folders)"),
                 bg=P["card"], fg=P["mute"], font=self.f.tiny).pack(anchor="w")
        self.online = tk.Label(on, text="", bg=P["card"], fg=P["text"], font=self.f.body)
        self.online.pack(side="left", padx=12)
        Button(on, L("ফোল্ডার খুলুন", "Open the folder"), self.open_slips, font=self.f.small, padx=12, pady=8).pack(side="right", padx=18)
        # ---- who holds how many BS
        head = tk.Frame(self.body, bg=P["bg"])
        head.pack(fill="x", pady=(16, 6))
        self.list_title = tk.Label(head, text=L("কার কাছে BS আছে (অফিসে আসেনি)", "Who still holds a BS (not in the office)"),
                                   bg=P["bg"], fg=P["text"], font=self.f.h3)
        self.list_title.pack(side="left")
        self.all_btn = Button(head, L("সব BS দেখুন", "See every BS"), self.toggle_all, font=self.f.small, padx=10, pady=5)
        self.all_btn.pack(side="right")
        tbl = self.who_card = self.card(self.body, fill="both", expand=True)
        box, self.who = self.table(tbl, [("ver", L("ভেরিফায়ার", "Verifier"), 210, "w"), ("trip", "Trip ID", 80, "center"),
                                         ("file", "File No", 170, "w"), ("bank", L("ব্যাংক", "Bank"), 200, "w"),
                                         ("type", L("ধরন", "Type"), 70, "center"),
                                         ("wd", L("Withdraw তারিখ", "Withdrawn on"), 130, "center"),
                                         ("days", L("কত দিন", "Days"), 60, "center")], height=10)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.full = self.card(self.body)                  # shown in place of the table above ("see every BS")
        fbox, self.tv = self.table(self.full, [("created", L("Created", "Created"), 110, "w"), ("trip", "Trip ID", 70, "w"),
                                               ("file", "File No", 160, "w"), ("bank", L("ব্যাংক", "Bank"), 150, "w"),
                                               ("type", L("ধরন", "Type"), 64, "w"), ("ver", L("ভেরিফায়ার", "Verifier"), 110, "w"),
                                               ("out", L("রিমার্ক থেকে ফলাফল", "Outcome (from remarks)"), 190, "w"),
                                               ("now", L("এখন কোথায়", "Now"), 120, "w")], height=10)
        fbox.pack(fill="both", expand=True, padx=1, pady=1)
        self.show_all = False
        self.rows: list = []
        self.month_rows: dict = {}

    def toggle_all(self):
        self.show_all = not self.show_all
        self.all_btn.config(text=L("লুকান", "Hide") if self.show_all else L("সব BS দেখুন", "See every BS"))
        self.list_title.config(text=L("এই মাসের সব BS", "Every BS of this month") if self.show_all else
                               L("কার কাছে BS আছে (অফিসে আসেনি)", "Who still holds a BS (not in the office)"))
        (self.who_card if self.show_all else self.full).pack_forget()
        (self.full if self.show_all else self.who_card).pack(fill="both", expand=True)

    def open_slips(self):
        p = self.shell.helper.slips_dir or config.default_output_dir() / "BS Slips"
        p.mkdir(parents=True, exist_ok=True)
        open_path(p)

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
                r.bank_submitted = s.get("bank_submitted") or {}
        else:
            rows = [r for r in self.shell.bs_all() if r.created and (r.created.year, r.created.month) == (y, m)]
        if self.org.get() != "all":
            rows = [r for r in rows if r.org == self.org.get()]
        return [r for r in rows if "test" not in (r.file_no or "").lower()]

    def refresh(self):
        rows = self.current_rows()
        self.rows = rows
        held = BT.still_with_verifier(rows)
        office = [r for r in rows if r.office and not r.courier.get("no") and not r.bank_received]
        cour = [r for r in rows if r.courier.get("no") and not r.bank_received]
        for v, n in zip(self.cards, (len(held), len(office), len(cour))):
            v.config(text=num(n))
        online = [r for r in rows if r.bs_type == "Online" and r.collected]
        sub = sum(1 for r in online if r.bank_submitted)
        self.online.config(text=L(f"{num(sub)} জমা · {num(len(online) - sub)} বাকি", f"{sub} handed in · {len(online) - sub} left"))
        when = self.shell.data["at"]
        y, m = map(int, self.month.get().split("-"))
        self.sub.config(text=f"{date(y, m, 1):%B %Y}" + (L(f" · ড্যাশবোর্ড {when:%I:%M %p}", f" · dashboard {when:%I:%M %p}") if when else ""))
        # who holds how many: one bold line per verifier (with the count), then his BS, oldest first
        self.who.delete(*self.who.get_children())
        today = date.today()
        for ver, items in BT.by_verifier(held):
            self.who.insert("", "end", values=(f"{ver}  ({num(len(items))})", "", "", "", "", "", ""), tags=("blue",))
            for r in items:
                d = (today - r.finished.date()).days if r.finished else None
                self.who.insert("", "end", iid=f"w|{r.org}|{r.trip_id}",
                                values=("", r.trip_id, r.file_no, r.bank or r.bank_written,
                                        L("অনলাইন", "Online") if r.bs_type == "Online" else L("অফলাইন", "Offline"),
                                        f"{r.finished:%d %b %Y}" if r.finished else "–", num(d) if d is not None else "–"),
                                tags=("bad",) if d is not None and d >= 3 else ())
        if not held:
            self.who.insert("", "end", values=(L("কারো কাছে BS নেই ✓", "No BS left with anyone ✓"),
                                               "", "", "", "", "", ""), tags=("ok",))
        self.tv.delete(*self.tv.get_children())
        prev, zebra = None, False
        for r in rows:
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
        if not sel:                                                 # nothing chosen: every BS waiting in the office
            sel = [r for r in self.rows if r.office and not r.courier.get("no") and not r.bank_received]
        if not sel:
            messagebox.showinfo(L("অফিসে কোনো BS নেই", "No BS in the office"),
                                L("আগে “অফিসে পেলাম” দিয়ে BS রিসিভ করুন, তারপর কুরিয়ার দিন।",
                                  "First receive the BS with “Received in office”, then add the courier."))
            return
        CourierDialog(self, sel)


BT_LOOKBACK = 85
GOOD = (R.GOING, R.DONE, R.WILL_SUBMIT, R.SUBMITTED)
VOICE_DIR = config.SETTINGS_DIR / "voices"


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
    """Three steps, top to bottom (Naim's choice, 'Demo A'): 1 messages ready -> 2 send on WhatsApp -> 3 replies."""
    title_bn, title_en = "রিমাইন্ডার (WhatsApp)", "Reminders (WhatsApp)"

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("দিনের সারাংশ", "Day summary"), self.summary)
        self.round = tk.StringVar(value=R.due_round({}) or "1pm")
        self.tab = tk.StringVar(value="all")
        self.show_list = False

        # ---- step 1: messages ready
        c1, self.n1, t1 = self._step(1, L("মেসেজ তৈরি", "Messages are ready"))
        self.s1_text = t1
        right = tk.Frame(c1, bg=P["card"])
        right.pack(side="right", padx=(0, 18))
        self.s1_btn = Button(right, L("এখনই তৈরি করুন", "Prepare now"), self.prepare, kind="secondary", font=self.f.small, padx=12, pady=7)
        self.s1_btn.pack(side="right")
        Segmented(right, self.f, [(k, R.ROUND_LABEL[k]) for k, _t in R.ROUNDS], self.round).pack(side="right", padx=(0, 10))

        # ---- step 2: send on WhatsApp
        c2, self.n2, t2 = self._step(2, L("WhatsApp-এ পাঠান", "Send on WhatsApp"), strong=True)
        self.c2, self.s2_text = c2, t2
        self.s2_prog = tk.Label(t2.master, text="", bg=P["card"], fg=P["accent"], font=self.f.btn)
        self.s2_prog.pack(anchor="w", pady=(4, 0))
        self.s2_btn = Button(c2, L("পাঠানো শুরু করুন", "Start sending"), self.start, kind="primary", font=self.f.btn, padx=22, pady=13)
        self.s2_btn.pack(side="right", padx=(0, 18))

        # ---- helper not in Chrome yet (shown only when needed)
        self.setup_box = tk.Frame(self.body, bg=P["warn_bg"])
        tk.Label(self.setup_box, bg=P["warn_bg"], fg=P["warn"], font=self.f.small, justify="left", anchor="w", wraplength=700,
                 text=L("Chrome-এ হেল্পার এখনো যুক্ত হয়নি (একবারই করতে হবে, ১ মিনিট):\n"
                        "১. ‘হেল্পার যোগ করুন’ চাপুন: Chrome-এর Extensions পাতা ও একটি ফোল্ডার খুলবে\n"
                        "২. Chrome-এ ডানে উপরে ‘Developer mode’ চালু করুন, তারপর ‘Load unpacked’ চাপুন\n"
                        "৩. খোলা ফোল্ডারটি বাছুন (ফোল্ডারের ঠিকানা কপি করা আছে: Paste করলেও হবে)\n"
                        "এরপর আর কিছু করতে হবে না: প্রতিবার নিজে থেকেই যুক্ত হবে।",
                        "The helper is not in Chrome yet (once only, 1 minute):\n"
                        "1. Press ‘Add the helper’: Chrome's Extensions page and a folder open\n"
                        "2. In Chrome turn on ‘Developer mode’ (top right), then press ‘Load unpacked’\n"
                        "3. Choose the folder that opened (its address is copied: Paste works too)\n"
                        "After that nothing more: it connects by itself every time.")).pack(side="left", padx=14, pady=10)
        Button(self.setup_box, L("হেল্পার যোগ করুন", "Add the helper"), self.setup, kind="dark", font=self.f.small, padx=14, pady=9).pack(side="right", padx=14)

        # ---- step 3: replies
        c3, self.n3, t3 = self._step(3, L("উত্তর নিজে থেকেই এখানে আসে", "Replies come here by themselves"))
        self.c3 = c3
        t3.config(text=L("WhatsApp Web খোলা রাখুন। কিছু চাপতে হবে না।", "Keep WhatsApp Web open. Nothing to press."))
        self.s3_btn = Button(c3, L("তালিকা দেখুন", "See the list"), self.toggle_list, kind="secondary", font=self.f.small, padx=12, pady=7)
        self.s3_btn.pack(side="right", padx=(0, 18))
        nums = tk.Frame(c3, bg=P["card"])
        nums.pack(side="right", padx=(0, 18))
        self.k = []
        for label, color in ((L("যাচ্ছি / শেষ", "Going / done"), P["ok"]), (L("সমস্যা", "Problem"), P["bad"]),
                             (L("উত্তর আসেনি", "No reply yet"), P["text"])):
            col = tk.Frame(nums, bg=P["card"])
            col.pack(side="left", padx=10)
            v = tk.Label(col, text="–", bg=P["card"], fg=color, font=(self.f.family, 18, "bold"))
            v.pack()
            tk.Label(col, text=label, bg=P["card"], fg=P["mute"], font=self.f.tiny).pack()
            self.k.append(v)

        self.nowa = tk.Frame(self.body, bg=P["bad_bg"])
        self.nowa_lbl = tk.Label(self.nowa, text="", bg=P["bad_bg"], fg=P["bad"], font=self.f.small, anchor="w", justify="left", wraplength=760)
        self.nowa_lbl.pack(side="left", padx=14, pady=8)
        Button(self.nowa, L("নম্বর যোগ করুন", "Add numbers"), lambda: shell.show("verifiers"), kind="secondary", font=self.f.small,
               padx=12, pady=7).pack(side="right", padx=14)

        # ---- the list (hidden until asked for)
        self.list_box = tk.Frame(self.body, bg=P["bg"])
        bar = tk.Frame(self.list_box, bg=P["bg"])
        bar.pack(fill="x", pady=(0, 8))
        Segmented(bar, self.f, [("all", L("সব", "All")), ("replied", L("উত্তর এসেছে", "Replied")), ("problem", L("সমস্যা", "Problem")),
                                ("none", L("উত্তর আসেনি", "No reply"))], self.tab, self.refresh).pack(side="left")
        tbl = self.card(self.list_box, fill="both", expand=True)
        box, self.tv = self.table(tbl, [("p", L("অগ্রাধিকার", "Priority"), 120, "w"), ("ver", L("ভেরিফায়ার", "Verifier"), 150, "w"),
                                        ("files", L("ফাইল", "Files"), 260, "w"), ("voice", L("ভয়েস", "Voice"), 130, "w"),
                                        ("state", L("অবস্থা", "State"), 120, "w"), ("rep", L("উত্তর (সফটওয়্যার যা বুঝল)", "Reply (as understood)"), 260, "w")],
                                  height=8)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.next_lbl = tk.Label(self.body, text="", bg=P["bg"], fg=P["mute"], font=self.f.small, anchor="w")
        self.next_lbl.pack(side="bottom", fill="x", pady=(8, 0))
        self._waiting_since = None
        self.after(4000, self._watch)

    # ------------------------------------------------------------------ pieces
    def _step(self, n, title, strong=False):
        c = tk.Frame(self.body, bg=P["card"], highlightbackground=P["accent"] if strong else P["line"], highlightthickness=2 if strong else 1)
        c.pack(fill="x", pady=(0, 12))
        dot = tk.Label(c, text=num(n), bg=P["line"], fg=P["mute"], font=(self.f.family, 14, "bold"), width=3, pady=6)
        dot.pack(side="left", padx=18, pady=16)
        mid = tk.Frame(c, bg=P["card"])
        mid.pack(side="left", fill="x", expand=True, pady=12)
        tk.Label(mid, text=title, bg=P["card"], fg=P["text"], font=self.f.h3).pack(anchor="w")
        text = tk.Label(mid, text="", bg=P["card"], fg=P["mute"], font=self.f.small, justify="left", anchor="w", wraplength=520)
        text.pack(anchor="w")
        return c, dot, text

    def _dot(self, dot, state):
        bg, fg = {"done": (P["ok"], "#FFFFFF"), "now": (P["accent"], "#FFFFFF")}.get(state, (P["line"], P["mute"]))
        dot.config(bg=bg, fg=fg)

    def _watch(self):
        """Every few seconds: is WhatsApp (with the helper) connected?  Keeps the page honest without a click."""
        try:
            if self.winfo_ismapped():
                self._connection()
                self.shell._status()
            self.after(4000, self._watch)
        except tk.TclError:
            pass

    def _connection(self):
        h = self.shell.helper
        if h.extension_connected:
            self._waiting_since = None
            self.setup_box.pack_forget()
        elif self._waiting_since and (datetime.now() - self._waiting_since).total_seconds() > 30:
            self.setup_box.pack(fill="x", pady=(0, 12), after=self.c2)       # WhatsApp was opened but no helper answered

    # ------------------------------------------------------------------ actions
    def prepare(self):
        if not self.need_data():
            return
        self.shell.prepare_round(self.round.get())

    def start(self):
        st = R.load_state()
        ds = R.day_state(st)
        if not ds["rounds"]:
            if not self.need_data():
                return
            self.shell.prepare_round(self.round.get(), notify=False)
        how = self.shell.start_sending()
        if how == "started":
            self.shell.toast(L("WhatsApp ট্যাবে যান: প্রথম চ্যাট খুলছে। আপনি শুধু Send চাপবেন।",
                               "Go to the WhatsApp tab: the first chat is opening. You only press Send."))
        else:
            self._waiting_since = datetime.now()
            self.shell.toast(L("WhatsApp Web খোলা হলো। পেজ চালু হলে প্রথম চ্যাট নিজে খুলবে।",
                               "WhatsApp Web is opening. When the page is ready the first chat opens by itself."))

    def toggle_list(self):
        self.show_list = not self.show_list
        self.s3_btn.config(text=L("তালিকা লুকান", "Hide the list") if self.show_list else L("তালিকা দেখুন", "See the list"))
        if self.show_list:
            self.list_box.pack(fill="both", expand=True, pady=(4, 0))
        else:
            self.list_box.pack_forget()

    def refresh(self):
        st = R.load_state()
        ds = R.day_state(st)
        rk = self.shell.helper.round_key or (sorted(ds["rounds"], key=lambda k: ds["rounds"][k]["prepared"])[-1] if ds["rounds"] else None)
        due = R.due_round(st)
        items = ds["rounds"][rk]["items"] if rk else []
        last = {}
        for rp in ds["replies"]:
            last[rp["phone"]] = rp
        sent = sum(1 for i in items if i.get("sent"))
        self.sub.config(text=L(f"{R.ROUND_LABEL[rk]}-এর রিমাইন্ডার · উপর থেকে নিচে ৩টি ধাপ", f"{R.ROUND_LABEL[rk]} reminder · 3 steps, top to bottom") if rk
                        else L("আজ এখনো কোনো রিমাইন্ডার তৈরি হয়নি", "No reminder prepared yet today"))
        # step 1
        if rk:
            nv = sum(1 for i in items if (VOICE_DIR / f"{i.get('voice')}.mp3").exists())
            self.s1_text.config(text=L(f"{num(len(items))} জনের মেসেজ লেখা হয়েছে, ভয়েস তৈরি {num(nv)}/{num(len(items))} ({ds['rounds'][rk]['prepared'][11:16]})।",
                                       f"{len(items)} messages written, voice ready {nv}/{len(items)} (at {ds['rounds'][rk]['prepared'][11:16]})."))
            self.s1_btn.config(text=L("আবার তৈরি করুন", "Prepare again"))
        else:
            self.s1_text.config(text=L("সফটওয়্যার সকাল ৮টা, ১০টা, দুপুর ১টা, ৩টা ও বিকেল ৫:৩০-এ নিজে তৈরি করে। এখনই চাইলে ডানের বাটন চাপুন।",
                                       "The software prepares it at 8, 10, 1, 3 and 5:30 by itself. Press the button to do it now."))
            self.s1_btn.config(text=L("এখনই তৈরি করুন", "Prepare now"))
        self._dot(self.n1, "done" if rk else "now")
        # step 2
        all_sent = bool(items) and sent == len(items)
        self.s2_text.config(text=L("বাটন চাপুন। WhatsApp প্রথম চ্যাট খুলবে: ভয়েস যুক্ত ও মেসেজ লেখা থাকবে। আপনি ২ বার Send চাপবেন (আগে ভয়েস, পরে মেসেজ)। তারপর পরের চ্যাট নিজে খুলবে।",
                                   "Press the button. WhatsApp opens the first chat with the voice attached and the message typed. "
                                   "You press Send twice (first the voice, then the message). Then the next chat opens by itself."))
        self.s2_prog.config(text=(L(f"{num(len(items))} জনের মধ্যে {num(sent)} জনকে পাঠানো হয়েছে", f"{sent} of {len(items)} sent") if items else
                                  (L("পাঠানোর মতো কেউ নেই (নম্বর নেই, বা কোনো চলমান ট্রিপ নেই)।", "No one to send to (no numbers, or no open trips).") if rk else "")),
                            fg=P["accent"] if items else P["bad"])
        self.s2_btn.config(text=L("সব পাঠানো শেষ ✓", "All sent ✓") if all_sent else
                           (L("বাকিদের পাঠান", "Send the rest") if sent else L("পাঠানো শুরু করুন", "Start sending")))
        self.s2_btn.enable(not all_sent)
        self._dot(self.n2, "done" if all_sent else ("now" if rk else ""))
        # step 3
        good = sum(1 for i in items if last.get(i["phone"], {}).get("kind") in GOOD)
        bad = sum(1 for i in items if last.get(i["phone"], {}).get("kind") == R.PROBLEM)
        none = sum(1 for i in items if i.get("sent") and i["phone"] not in last)
        for lbl, v in zip(self.k, (good, bad, none)):
            lbl.config(text=num(v))
        self._dot(self.n3, "now" if sent else "")
        self._connection()
        # the list
        self.tv.delete(*self.tv.get_children())
        tab = self.tab.get()
        for it in items:
            rp = last.get(it["phone"])
            kind = rp["kind"] if rp else None
            if tab == "replied" and not rp or tab == "problem" and kind != R.PROBLEM or tab == "none" and rp:
                continue
            pr = it.get("priority", 3)
            tag = "bad" if kind == R.PROBLEM else ("ok" if kind in GOOD else ("bad" if pr == 0 else ("warn" if pr in (1, 2) else "")))
            self.tv.insert("", "end", values=(R.PRIORITY_TEXT.get(pr, ""), it["verifier"], ", ".join(it.get("files", []))[:120],
                                              "✓" if (VOICE_DIR / f"{it.get('voice')}.mp3").exists() else L("নেই", "none"),
                                              (L(f"পাঠানো {it['sent'][11:16]}", f"sent {it['sent'][11:16]}") if it.get("sent") else L("তৈরি", "ready")),
                                              (f"{R.REPLY_TEXT.get(kind, kind)}" + (f" · {rp['reason'][:60]}" if rp.get("reason") else "")) if rp else "—"),
                           tags=(tag,) if tag else ())
        no = (ds["rounds"][rk].get("no_whatsapp", []) if rk else []) + [
            {"verifier": i["verifier"], "phone": i["phone"]} for i in items if i["phone"] in R.NO_WA_CACHE]
        if no:
            self.nowa_lbl.config(text=L(f"{num(len(no))} জনের WhatsApp নম্বর নেই: ", f"{len(no)} verifiers have no WhatsApp number: ")
                                 + ", ".join(n["verifier"] for n in no[:12]) + ("…" if len(no) > 12 else ""))
            self.nowa.pack(fill="x", pady=(0, 12), after=self.c3)
        else:
            self.nowa.pack_forget()
        self.next_lbl.config(text=L(f"পরের রিমাইন্ডার: {R.ROUND_LABEL[due]} (সফটওয়্যার নিজে তৈরি করবে)", f"Next reminder: {R.ROUND_LABEL[due]} (prepared by the software)")
                             if due else "")

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
        """Opens Chrome's Extensions page and the helper's folder; the folder's address goes to the clipboard."""
        folder = self.shell.helper_dir
        try:
            self.clipboard_clear()
            self.clipboard_append(str(folder))
        except tk.TclError:
            pass
        ok = open_chrome_extensions()
        open_path(folder)
        if not ok:
            messagebox.showinfo(L("হেল্পার যোগ করুন", "Add the helper"),
                                L("Chrome-এর ঠিকানার ঘরে লিখুন:  chrome://extensions", "In Chrome's address bar type:  chrome://extensions"))


# ============================================================================================ Verifiers
class VerifiersPage(Page):
    """V18: verifiers only - WhatsApp number, the automatic WhatsApp check, photos, Excel / CSV import."""
    title_bn, title_en = "ভেরিফায়ার · WhatsApp ও ছবি", "Verifiers · WhatsApp & photos"
    FILTERS = (("all", "সবাই", "All"), ("missing", "WhatsApp নেই", "No WhatsApp"), ("unchecked", "চেক হয়নি", "Not checked"),
               ("ok", "WhatsApp আছে", "Connected"), ("nophoto", "ছবি নেই", "No photo"))

    def __init__(self, master, shell):
        super().__init__(master, shell)
        self.action(L("↻  নম্বর আবার আনুন", "↻  Read numbers again"), lambda: shell.refresh_data("manual"))
        self.action(L("CSV রাখুন", "Save CSV"), self.export)
        self.action(L("Excel / CSV দিন", "Import Excel / CSV"), self.import_file)
        self.action(L("ছবি দিন (অনেকগুলো)", "Add photos (many)"), self.add_photos)
        self.action(L("নতুন ড্যাশবোর্ড (Chrome)", "New dashboard (Chrome)"), self.new_dashboard)
        self.action(L("WhatsApp চেক করুন", "Check WhatsApp"), self.check_now, kind="primary")
        top = tk.Frame(self.body, bg=P["bg"])
        top.pack(fill="x")
        self.k_all = self.kpi(top, L("ভেরিফায়ার", "Verifiers"))
        self.k_ok = self.kpi(top, L("WhatsApp আছে", "WhatsApp connected"), color=P["ok"])
        self.k_un = self.kpi(top, L("চেক হয়নি", "Not checked yet"), color=P["warn"])
        self.k_no = self.kpi(top, L("WhatsApp নেই", "No WhatsApp"), color=P["bad"], hint=L("নম্বর নেই / ভুল / WhatsApp নেই", "no / wrong number or not on WhatsApp"))
        self.k_ph = self.kpi(top, L("ছবি নেই", "No photo"))
        for i, k in enumerate((self.k_all, self.k_ok, self.k_un, self.k_no, self.k_ph)):
            k.pack(side="left", fill="x", expand=True, padx=(0 if i == 0 else 10, 0))
        edit = self.card(self.body, fill="x", pady=(12, 0))
        row = tk.Frame(edit, bg=P["card"], padx=18, pady=12)
        row.pack(fill="x")
        self.photo_lbl = tk.Label(row, text="", bg=P["line"], width=8, height=4, cursor="hand2")
        self.photo_lbl.pack(side="left", padx=(0, 14))
        self.photo_lbl.bind("<Button-1>", lambda _e: self.add_photo_one())
        mid = tk.Frame(row, bg=P["card"])
        mid.pack(side="left", fill="x", expand=True)
        self.sel_name = tk.Label(mid, text=L("তালিকা থেকে একজনকে বাছুন", "Choose someone in the list"), bg=P["card"], fg=P["text"], font=self.f.h3)
        self.sel_name.pack(anchor="w")
        self.sel_info = tk.Label(mid, text="", bg=P["card"], fg=P["mute"], font=self.f.small)
        self.sel_info.pack(anchor="w")
        line = tk.Frame(mid, bg=P["card"])
        line.pack(anchor="w", pady=(6, 0))
        self.phone = tk.StringVar()
        tk.Label(line, text=L("WhatsApp নম্বর", "WhatsApp number"), bg=P["card"], fg=P["mute"], font=self.f.small).pack(side="left", padx=(0, 6))
        Entry(line, self.f, self.phone, width=18).pack(side="left", ipady=4)
        Button(line, L("সেভ", "Save"), self.save, kind="primary", font=self.f.small, padx=14, pady=6).pack(side="left", padx=8)
        Button(line, L("WhatsApp নেই", "Not on WhatsApp"), self.mark_no, font=self.f.small, padx=10, pady=6).pack(side="left")
        Button(line, L("ড্যাশবোর্ডের নম্বরে ফেরত", "Back to the dashboard number"), self.reset, font=self.f.small, padx=10, pady=6).pack(side="left", padx=8)
        Button(line, L("ছবি দিন", "Add photo"), self.add_photo_one, font=self.f.small, padx=10, pady=6).pack(side="left")
        fl = tk.Frame(self.body, bg=P["bg"])
        fl.pack(fill="x", pady=(12, 6))
        self.flt = tk.StringVar(value="all")
        Segmented(fl, self.f, [(k, L(bn, en)) for k, bn, en in self.FILTERS], self.flt, command=lambda *_: self.refresh()).pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self.refresh())
        tk.Label(fl, text=L("খুঁজুন", "Search"), bg=P["bg"], fg=P["mute"], font=self.f.small).pack(side="left", padx=(16, 6))
        Entry(fl, self.f, self.q, width=24).pack(side="left", ipady=3)
        tbl = self.card(self.body, fill="both", expand=True)
        box, self.tv = self.table(tbl, [("name", L("নাম", "Name"), 200, "w"), ("id", "ID", 70, "w"), ("wa", "WhatsApp", 170, "w"),
                                        ("phone", L("নম্বর", "Number"), 150, "w"), ("src", L("কোথা থেকে", "From"), 130, "w"),
                                        ("photo", L("ছবি", "Photo"), 60, "w"), ("checked", L("চেক", "Checked"), 100, "w"),
                                        ("open", L("চলমান ট্রিপ", "On Going trips"), 110, "w")], height=14)
        box.pack(fill="both", expand=True, padx=1, pady=1)
        self.tv.bind("<<TreeviewSelect>>", lambda _e: self.pick())
        self.sel = None
        self._img = None

    def on_data(self):
        self.refresh()

    def _open_trips(self) -> dict:
        out: dict = {}
        for fl in self.shell.data["files"].values():
            for f in fl:
                if f.get("status_code") in R.OPEN_FILE:
                    for c in f.get("concerns") or []:
                        for t in c.get("trips") or []:
                            if t.get("status_code") in R.OPEN_TRIP and t.get("agent_id") is not None:
                                out[t["agent_id"]] = out.get(t["agent_id"], 0) + 1
        return out

    def refresh(self):
        from . import verifier_dir as VD
        phones = self.shell.data["phones"]
        ov = self.shell.phone_overrides()
        st = R.load_state()
        open_trips = self._open_trips()
        rank = {"none": 0, "bad": 0, "no": 0, "unchecked": 1, "ok": 2}
        rows = []
        for vid, p in phones.items():
            ph = VD.number_of(vid, phones, ov)
            ws = VD.wa_status(ph, st)
            rows.append((vid, p.get("name", ""), ph, ws, VD.photo_path(vid) is not None))
        cnt = lambda f: sum(1 for r in rows if f(r))                                   # noqa: E731
        self.k_all.value.config(text=num(len(rows)))
        self.k_ok.value.config(text=num(cnt(lambda r: r[3] == "ok")))
        self.k_un.value.config(text=num(cnt(lambda r: r[3] == "unchecked")))
        self.k_no.value.config(text=num(cnt(lambda r: r[3] in ("none", "bad", "no"))))
        self.k_ph.value.config(text=num(cnt(lambda r: not r[4])))
        f, q = self.flt.get(), self.q.get().strip().lower()
        keep = {"all": lambda r: True, "missing": lambda r: r[3] in ("none", "bad", "no"), "unchecked": lambda r: r[3] == "unchecked",
                "ok": lambda r: r[3] == "ok", "nophoto": lambda r: not r[4]}[f]
        rows = [r for r in rows if keep(r) and (not q or q in f"{r[1]} {r[0]} {r[2]}".lower())]
        rows.sort(key=lambda r: (rank[r[3]], -open_trips.get(r[0], 0), r[1].lower()))
        self.tv.delete(*self.tv.get_children())
        for vid, name, ph, ws, has_photo in rows:
            dot = {"ok": "🟢 ", "unchecked": "🟠 ", "no": "🔴 ", "bad": "🔴 ", "none": "🔴 "}[ws]
            checked = (st.get("wa_ok") or {}).get(ph) or (st.get("no_whatsapp") or {}).get(ph) or "—"
            self.tv.insert("", "end", iid=str(vid), values=(name, vid, dot + L(*VD.STATUS_TEXT[ws]), ph or "—",
                                                            L("আপনি দিয়েছেন", "added by you") if str(vid) in ov else L("ড্যাশবোর্ড", "dashboard"),
                                                            "✓" if has_photo else "—", checked, num(open_trips.get(vid, 0))),
                           tags=("bad",) if ws in ("none", "bad", "no") else ("warn",) if ws == "unchecked" else ())
        self.sub.config(text=L(f"শুধু ভেরিফায়ার · দেখানো {num(len(rows))} জন", f"Verifiers only · showing {len(rows)}"))
        if self.sel and self.tv.exists(self.sel):
            self.tv.selection_set(self.sel)

    def pick(self):
        from . import verifier_dir as VD
        s = self.tv.selection()
        if not s:
            return
        self.sel = s[0]
        vals = self.tv.item(s[0], "values")
        self.sel_name.config(text=vals[0])
        self.sel_info.config(text=f"ID {vals[1]} · {vals[2]} · {L('চলমান ট্রিপ', 'On Going trips')} {vals[7]}")
        self.phone.set("" if vals[3] == "—" else vals[3])
        self._show_photo(VD.photo_path(self.sel))

    def _show_photo(self, path):
        self._img = None
        try:
            if path:
                from PIL import Image, ImageTk
                im = Image.open(path)
                im.thumbnail((72, 72))
                self._img = ImageTk.PhotoImage(im)
        except Exception:                                    # noqa: BLE001 - no Pillow Tk support: show text instead
            self._img = None
        if self._img:
            self.photo_lbl.config(image=self._img, text="", width=72, height=72)
        else:
            self.photo_lbl.config(image="", text=L("ছবি\nদিন", "Add\nphoto"), width=8, height=4)

    def _set_number(self, vid: str, ph: str):
        self.shell.set_verifier_number(int(vid), ph)
        R.NO_WA_CACHE.discard(ph)

    def save(self):
        if not self.sel:
            return
        ph = normalize_phone(self.phone.get())
        if not is_bd_mobile(ph):
            messagebox.showwarning(L("নম্বর ঠিক নেই", "Number not valid"), L("বাংলাদেশের মোবাইল নম্বর দিন (01XXXXXXXXX)।",
                                                                           "Give a Bangladesh mobile number (01XXXXXXXXX)."))
            return
        self._set_number(self.sel, ph)
        self.refresh()

    def mark_no(self):
        from . import verifier_dir as VD
        if not self.sel:
            return
        ph = VD.number_of(self.sel, self.shell.data["phones"], self.shell.phone_overrides())
        if not ph:
            return
        st = R.load_state()
        VD.mark_not_on_whatsapp(st, ph)
        R.save_state(st)
        R.NO_WA_CACHE.add(ph)
        self.refresh()

    def reset(self):
        if not self.sel:
            return
        ov = self.shell.phone_overrides()
        ov.pop(self.sel, None)
        config.save_settings({"phone_overrides": ov})
        self.shell.settings["phone_overrides"] = ov
        self.refresh()

    def add_photo_one(self):
        from . import verifier_dir as VD
        if not self.sel:
            messagebox.showinfo(L("একজনকে বাছুন", "Choose someone"), L("আগে তালিকা থেকে একজন ভেরিফায়ার বাছুন।", "Choose a verifier in the list first."))
            return
        path = filedialog.askopenfilename(title=L("ভেরিফায়ারের ছবি", "Verifier photo"),
                                          filetypes=[(L("ছবি", "Pictures"), "*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tif *.tiff *.heic *.heif"), ("*", "*.*")])
        if not path:
            return
        try:
            VD.save_photo(self.sel, path)
        except Exception as exc:                             # noqa: BLE001
            messagebox.showwarning(L("ছবি খোলা যায়নি", "Could not open the picture"), f"{Path(path).name}: {type(exc).__name__}")
            return
        self.refresh()
        self.pick()

    def add_photos(self):
        from . import verifier_dir as VD
        paths = filedialog.askopenfilenames(title=L("অনেক ছবি একসাথে (ফাইলের নাম = নাম বা ID)", "Many photos (file name = name or ID)"),
                                            filetypes=[(L("ছবি", "Pictures"), "*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tif *.tiff *.heic *.heif"), ("*", "*.*")])
        if not paths:
            return
        found, missed = VD.match_photo_files(list(paths), self.shell.data["phones"])
        bad = []
        for vid, p in found:
            try:
                VD.save_photo(vid, p)
            except Exception:                                # noqa: BLE001
                bad.append(p.name)
        msg = L(f"{num(len(found) - len(bad))}টি ছবি সেভ হয়েছে।", f"{len(found) - len(bad)} photos saved.")
        if missed:
            msg += "\n" + L("নাম / ID মেলেনি: ", "No matching name / ID: ") + ", ".join(p.name for p in missed[:8])
        if bad:
            msg += "\n" + L("খোলা যায়নি: ", "Could not open: ") + ", ".join(bad[:8])
        messagebox.showinfo(L("ছবি", "Photos"), msg)
        self.refresh()

    def import_file(self):
        from . import verifier_dir as VD
        if not self.need_data():
            return
        path = filedialog.askopenfilename(title=L("WhatsApp নম্বরের তালিকা (Excel / CSV)", "WhatsApp numbers (Excel / CSV)"),
                                          filetypes=[("Excel / CSV", "*.xlsx *.xlsm *.csv *.txt"), ("*", "*.*")])
        if not path:
            return
        try:
            items = VD.parse_import(VD.read_rows(Path(path)), self.shell.data["phones"])
        except Exception as exc:                             # noqa: BLE001
            messagebox.showwarning(L("ফাইল পড়া যায়নি", "Could not read the file"), f"{Path(path).name}: {type(exc).__name__}")
            return
        ImportDialog(self, items, Path(path).name)

    def apply_import(self, items):
        from . import verifier_dir as VD
        ov = self.shell.phone_overrides()
        n = VD.apply_import(items, ov)
        config.save_settings({"phone_overrides": ov})
        self.shell.settings["phone_overrides"] = ov
        for it in items:
            if it.get("ok"):
                R.NO_WA_CACHE.discard(it["phone"])
        self.shell.toast(L(f"{num(n)}টি WhatsApp নম্বর সেভ হয়েছে", f"{n} WhatsApp numbers saved"))
        self.refresh()

    def export(self):
        from . import verifier_dir as VD
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="Verifier WhatsApp.csv", filetypes=[("CSV", "*.csv")])
        if path:
            VD.export_csv(Path(path), self.shell.data["phones"], self.shell.phone_overrides(), R.load_state())
            open_path(Path(path).parent)

    def check_now(self):
        if not self.shell.helper_running:
            messagebox.showinfo("WhatsApp", L("হেল্পার চালু নেই। প্রোগ্রাম একবার বন্ধ করে আবার খুলুন।", "The helper is not running. Close and open the program again."))
            return
        self.shell.helper.request_check(auto=False)
        msg = L("WhatsApp Web-এ হেল্পার এখন একে একে নম্বরগুলো খুলে দেখবে (কিছু লেখা বা পাঠানো হয় না)।",
                "The helper on WhatsApp Web now opens each number to see if it is on WhatsApp (nothing is typed or sent).")
        if not self.shell.helper.extension_connected:
            msg += "\n\n" + L("Chrome-এ web.whatsapp.com খুলুন — হেল্পার যুক্ত হলেই চেক শুরু হবে।", "Open web.whatsapp.com in Chrome; the check starts when the helper connects.")
        messagebox.showinfo("WhatsApp", msg)


    def new_dashboard(self):
        """V18: set up the new dashboard extension (live screens + this verifier list) in Chrome."""
        from .helper_server import new_dashboard_folder
        folder = new_dashboard_folder()
        open_path(folder)
        open_chrome_extensions()
        messagebox.showinfo(L("নতুন ড্যাশবোর্ড", "New dashboard"), L(
            "Chrome-এ: Developer mode চালু → Load unpacked → যে ফোল্ডার খুলেছে সেটি বাছুন।\n"
            "তারপর verify.bmapsbd.com-এ ডানদিকে নিচে “New dashboard (VRB)” চাপুন, বা খুলুন: https://verify.bmapsbd.com/vrb-dashboard\n"
            "এই প্রোগ্রাম খোলা থাকলে নম্বর, ছবি ও WhatsApp চেক দুই জায়গায় একসাথে দেখাবে।",
            "In Chrome: Developer mode on → Load unpacked → choose the folder that just opened.\n"
            "Then press “New dashboard (VRB)” at the bottom right of verify.bmapsbd.com, or open https://verify.bmapsbd.com/vrb-dashboard\n"
            "While this program is open, numbers, photos and the WhatsApp check show in both places."))


class ImportDialog(tk.Toplevel):
    """V18: every row of the Excel / CSV before anything is saved; rows that are not a verifier are skipped."""

    def __init__(self, page: VerifiersPage, items: list, name: str):
        super().__init__(page)
        self.page, self.items = page, items
        f = page.f
        self.title(L("দেখে নিন, তারপর সেভ", "Check, then save"))
        self.configure(bg=P["bg"])
        self.geometry("820x520")
        good = sum(1 for i in items if i["ok"])
        tk.Label(self, text=f"{name} · " + L(f"সেভ হবে {num(good)} · বাদ {num(len(items) - good)}", f"will be saved {good} · skipped {len(items) - good}"),
                 bg=P["bg"], fg=P["text"], font=f.h3).pack(anchor="w", padx=18, pady=(14, 6))
        box, tv = page.table(self, [("row", L("সারি", "Row"), 60, "w"), ("key", L("ফাইলে", "In the file"), 220, "w"),
                                    ("who", L("ভেরিফায়ার", "Verifier"), 200, "w"), ("phone", "WhatsApp", 150, "w"), ("res", L("ফল", "Result"), 160, "w")], height=14)
        box.pack(fill="both", expand=True, padx=18)
        for it in items:
            tv.insert("", "end", values=(it["row"], it["key"], it["name"] or "—", it["phone"] or "—",
                                         L("সেভ হবে", "will be saved") if it["ok"] else it["why"]), tags=("ok",) if it["ok"] else ("bad",))
        bar = tk.Frame(self, bg=P["bg"])
        bar.pack(fill="x", padx=18, pady=12)
        Button(bar, L(f"{num(good)}টি সেভ করুন", f"Save {good}"), self.ok, kind="primary", font=f.small, padx=14, pady=8).pack(side="right")
        Button(bar, L("বাতিল", "Cancel"), self.destroy, font=f.small, padx=14, pady=8).pack(side="right", padx=8)

    def ok(self):
        self.page.apply_import(self.items)
        self.destroy()


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
        self.own = tk.StringVar(value=shell.settings.get("own_whatsapp", ""))

        def own_box(r):
            box = tk.Frame(r, bg=P["card"])
            Entry(box, f, self.own, width=16).pack(side="left", ipady=3)
            Button(box, L("সেভ", "Save"), self.save_own, kind="primary", font=f.small, padx=12, pady=5).pack(side="left", padx=6)
            tk.Label(box, text=L("যে নম্বরে WhatsApp Web চলে। Verifier-এর ‘উত্তর দিন’ লিংক এই নম্বরে আসে।",
                                 "The number WhatsApp Web runs on. The verifiers' answer links come to this number."),
                     bg=P["card"], fg=P["mute"], font=f.tiny).pack(side="left", padx=6)
            return box
        line(L("আপনার WhatsApp নম্বর", "Your WhatsApp number"), own_box)
        line(L("WhatsApp হেল্পার", "WhatsApp helper"), lambda r: Button(r, L("ফোল্ডার খুলুন", "Open folder"), lambda: open_path(asset("whatsapp_helper")), font=f.small, padx=10, pady=6))
        line(L("সাইন আউট", "Sign out"), lambda r: Button(r, L("সাইন আউট", "Sign out"), self.sign_out, kind="danger", font=f.small, padx=10, pady=6))
        tk.Label(self.body, text=L("Excel / PDF রিপোর্ট সবসময় ইংরেজিতে (ব্যাংক যেভাবে পড়ে)। শুধু প্রোগ্রামের স্ক্রিন বাংলা / ইংরেজি হয়।",
                                   "Excel / PDF reports are always in English (as the bank reads them). Only the program's screens change."),
                 bg=P["bg"], fg=P["mute"], font=f.small).pack(anchor="w", pady=(12, 0))

    def save_own(self):
        ph = normalize_phone(self.own.get())
        if ph and not is_bd_mobile(ph):
            messagebox.showwarning(L("নম্বর ঠিক নেই", "Number not valid"), L("বাংলাদেশের মোবাইল নম্বর দিন (01XXXXXXXXX)।",
                                                                           "Give a Bangladesh mobile number (01XXXXXXXXX)."))
            return
        config.save_settings({"own_whatsapp": ph})
        self.shell.settings["own_whatsapp"] = ph
        self.own.set(ph)
        self.shell.toast(L("সেভ হয়েছে। পরের রিমাইন্ডার থেকে ‘উত্তর দিন’ লিংক যাবে।", "Saved. Answer links go out from the next reminder."))

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
