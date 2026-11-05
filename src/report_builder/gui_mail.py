"""Mail windows: send the finished tracker, mail settings / signature, sent-mail history.

The report is the attached Excel; the body is a few professional paragraphs (no tables) + the signature.
The mail goes out from verify@barikoi.com through SMTP.  The password (Zoho App Password) is typed when you send,
kept only in memory while the program is open (if you tick the box) and never written to disk.
"""
from __future__ import annotations

import queue
import sys
import tempfile
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import mailer
from . import signature as sigmod
from .mail_templates import TEMPLATES, facts_from, render
from .reports import count_blue_cells, has_checklist, strip_checklist
from .ui_kit import Button, Entry, P, Segmented


def _kb(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


class _TextVar:
    """StringVar-like wrapper around a small multi-line Text (so long address lists stay fully visible)."""

    def __init__(self, text: tk.Text):
        self.t = text

    def get(self) -> str:
        return self.t.get("1.0", "end").strip()

    def set(self, value: str) -> None:
        self.t.delete("1.0", "end")
        self.t.insert("1.0", value)


class _Base(tk.Toplevel):
    def __init__(self, app, title: str):
        super().__init__(app)
        self.app, self.f = app, app.fonts
        self.title(title)
        self.configure(bg=P["bg"])
        self.transient(app)
        self.resizable(False, False)

    def card(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=P["card"], highlightbackground=P["line"], highlightthickness=1)
        tk.Label(outer, text=title, bg=P["card"], fg=P["navy"], font=self.f.h3, anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        body = tk.Frame(outer, bg=P["card"])
        body.pack(fill="x", padx=12, pady=(0, 10))
        outer.body = body                                    # type: ignore[attr-defined]
        return outer

    def row(self, parent, label: str, var, width=44, show=None, labelw=9):
        r = tk.Frame(parent, bg=P["card"])
        r.pack(fill="x", pady=3)
        tk.Label(r, text=label, bg=P["card"], fg=P["mute"], font=self.f.small, width=labelw, anchor="w").pack(side="left")
        e = Entry(r, self.f, var, show=show, width=width)
        e.pack(side="left", fill="x", expand=True, ipady=3)
        return e

    def center(self):
        self.update_idletasks()
        cols = getattr(self, "cols", None)
        if cols is not None:                                   # fit the scrolling middle part to the screen
            need = cols.winfo_reqheight()
            fixed = self.winfo_reqheight() - self.canvas.winfo_reqheight()
            room = max(300, self.winfo_screenheight() - 130 - fixed)
            self.canvas.configure(width=cols.winfo_reqwidth(), height=min(need, room), scrollregion=(0, 0, cols.winfo_reqwidth(), need))
            if need > room:
                self.vbar.pack(side="right", fill="y")
                self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-1 * (e.delta if sys.platform == "darwin" else e.delta // 120), "units"))
            else:
                self.vbar.pack_forget()
            self.update_idletasks()
        a = self.app
        x = a.winfo_rootx() + max(0, (a.winfo_width() - self.winfo_reqwidth()) // 2)
        y = max(10, a.winfo_rooty() + 20)
        self.geometry(f"+{x}+{y}")
        self.grab_set()


# ======================================================================================== send window
class MailDialog(_Base):
    def __init__(self, app, data, files: list[Path]):
        super().__init__(app, "ইমেইল পাঠান — Submission Tracker")
        self.d, self.facts = data, facts_from(data)
        self.xlsx = next((p for p in files if p.suffix.lower() == ".xlsx"), None)
        self.pdf = next((p for p in files if p.suffix.lower() == ".pdf"), None)
        self.smtp = mailer.load_smtp_settings()
        self.rec = mailer.load_recipients()
        self.sig = sigmod.load_signature()
        self.q: queue.Queue = queue.Queue()
        self.sending = False
        self.edited = False
        f = self.f

        head = tk.Frame(self, bg=P["navy"])
        head.pack(fill="x")
        tk.Label(head, text="✉  ব্যাংককে ট্র্যাকার ইমেইল", bg=P["navy"], fg="white", font=f.h2).pack(side="left", padx=16, pady=10)
        self.from_lbl = tk.Label(head, text="", bg=P["navy"], fg=P["side_tx"], font=f.small)
        self.from_lbl.pack(side="right", padx=16)

        # the middle part scrolls when the screen is short (small laptops)
        self.bar_holder = tk.Frame(self, bg=P["bg"])
        self.canvas = tk.Canvas(self.bar_holder, bg=P["bg"], highlightthickness=0, borderwidth=0)
        self.vbar = tk.Scrollbar(self.bar_holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        cols = tk.Frame(self.canvas, bg=P["bg"], padx=14, pady=12)
        self.canvas.create_window((0, 0), window=cols, anchor="nw")
        self.cols = cols
        self.bar_holder.pack(fill="both", expand=True)
        left = tk.Frame(cols, bg=P["bg"])
        left.grid(row=0, column=0, sticky="n", padx=(0, 10))
        right = tk.Frame(cols, bg=P["bg"])
        right.grid(row=0, column=1, sticky="n")

        # ---- recipients
        c = self.card(left, "প্রাপক")
        c.pack(fill="x", pady=(0, 10))
        self.v_cc = tk.StringVar(value=", ".join(self.rec["cc"]))
        self.v_bcc = tk.StringVar(value=", ".join(self.rec["bcc"]))
        r_to = tk.Frame(c.body, bg=P["card"])
        r_to.pack(fill="x", pady=3)
        tk.Label(r_to, text="To", bg=P["card"], fg=P["mute"], font=f.small, width=9, anchor="w").pack(side="left", anchor="n", pady=4)
        t_to = tk.Text(r_to, width=62, height=3, font=f.body, relief="flat", wrap="word", highlightthickness=1,
                       highlightbackground=P["line"], highlightcolor=P["accent"], padx=6, pady=4)
        t_to.pack(side="left", fill="x", expand=True)
        self.v_to = _TextVar(t_to)
        self.v_to.set(", ".join(self.rec["to"]))
        self.row(c.body, "Cc", self.v_cc, 62)
        self.row(c.body, "Bcc", self.v_bcc, 62)
        tk.Label(c.body, text="একাধিক ঠিকানা কমা (,) বা সেমিকোলন (;) দিয়ে আলাদা করুন। বদলালে পরের বারও মনে থাকবে।", bg=P["card"],
                 fg=P["mute"], font=f.tiny, anchor="w").pack(fill="x")

        # ---- message
        m = self.card(left, "বার্তা")
        m.pack(fill="x")
        self.tpl = tk.StringVar(value=app.settings.get("mail_template", "formal"))
        top = tk.Frame(m.body, bg=P["card"])
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="নমুনা", bg=P["card"], fg=P["mute"], font=f.small, width=9, anchor="w").pack(side="left")
        Segmented(top, f, [(k, t.split(" — ")[0]) for k, t in TEMPLATES], self.tpl, self._apply_template).pack(side="left")
        self.tpl_hint = tk.Label(m.body, text="", bg=P["card"], fg=P["mute"], font=f.tiny, anchor="w")
        self.tpl_hint.pack(fill="x")
        self.v_subject = tk.StringVar()
        self.row(m.body, "Subject", self.v_subject, 62)
        self.body = tk.Text(m.body, width=76, height=13, font=f.body, relief="flat", wrap="word", highlightthickness=1,
                            highlightbackground=P["line"], padx=8, pady=6, undo=True)
        self.body.pack(fill="x", pady=(6, 0))
        self.body.bind("<<Modified>>", self._mark_edited)
        tk.Label(m.body, text="নিচের সিগনেচার নিজে থেকেই যুক্ত হবে। বার্তায় কোনো টেবিল নেই—রিপোর্ট Excel আকারে সংযুক্ত থাকবে।", bg=P["card"],
                 fg=P["mute"], font=f.tiny, anchor="w").pack(fill="x", pady=(4, 0))

        # ---- attachments
        a = self.card(right, "সংযুক্তি")
        a.pack(fill="x", pady=(0, 10))
        self.use_pdf = tk.BooleanVar(value=False)
        self.strip = tk.BooleanVar(value=True)
        self.extra: list[Path] = []
        if self.xlsx:
            tk.Label(a.body, text=f"📎 {self.xlsx.name}\n    {_kb(self.xlsx.stat().st_size)} · সম্পাদনাযোগ্য Excel (পাঠানোর মুহূর্তের ফাইল)",
                     bg=P["card"], fg=P["text"], font=f.small, anchor="w", justify="left").pack(fill="x")
        if self.pdf:
            tk.Checkbutton(a.body, text=f"PDF-ও সংযুক্ত করুন ({self.pdf.name[-30:]})", variable=self.use_pdf, bg=P["card"],
                           activebackground=P["card"], font=f.small, fg=P["text"], anchor="w", highlightthickness=0,
                           selectcolor="white").pack(fill="x", pady=(4, 0))
        self.chk_present = bool(self.xlsx and has_checklist(self.xlsx))
        if self.chk_present:
            tk.Checkbutton(a.body, text="অভ্যন্তরীণ ‘Check List’ শিট বাদ দিয়ে পাঠান", variable=self.strip, bg=P["card"],
                           activebackground=P["card"], font=f.small, fg=P["text"], anchor="w", highlightthickness=0,
                           selectcolor="white").pack(fill="x", pady=(4, 0))
        self.extra_lbl = tk.Label(a.body, text="", bg=P["card"], fg=P["text"], font=f.tiny, anchor="w", justify="left", wraplength=300)
        self.extra_lbl.pack(fill="x")
        Button(a.body, "＋ আরেকটি ফাইল যোগ করুন", self._add_file, kind="secondary", font=f.tiny, padx=8, pady=4).pack(anchor="w", pady=(6, 0))

        # ---- checks
        k = self.card(right, "পাঠানোর আগে যাচাই")
        k.pack(fill="x", pady=(0, 10))
        self.checks = tk.Frame(k.body, bg=P["card"])
        self.checks.pack(fill="x")
        Button(k.body, "↻ আবার যাচাই করুন (Excel সম্পাদনার পর)", self._refresh_checks, kind="ghost", font=f.tiny, padx=0, pady=3).pack(anchor="w", pady=(4, 0))

        # ---- signature
        g = self.card(right, "সিগনেচার (ইমেইলের নিচে যুক্ত হবে)")
        g.pack(fill="x")
        self.sig_box = tk.Frame(g.body, bg=P["card"])
        self.sig_box.pack(fill="x")
        Button(g.body, "সিগনেচার বদলান…", self._edit_signature, kind="ghost", font=f.tiny, padx=0, pady=3).pack(anchor="w", pady=(4, 0))

        # ---- action bar: password + buttons
        bar = tk.Frame(self, bg=P["card"], highlightbackground=P["line"], highlightthickness=1)
        bar.pack(fill="x")
        pwrow = tk.Frame(bar, bg=P["card"])
        pwrow.pack(fill="x", padx=14, pady=(10, 0))
        self.v_pw = tk.StringVar(value=app.smtp_password or "")
        self.v_remember = tk.BooleanVar(value=bool(app.smtp_password))
        tk.Label(pwrow, text="Zoho App Password", bg=P["card"], fg=P["mute"], font=f.small).pack(side="left")
        Entry(pwrow, f, self.v_pw, show="•", width=26).pack(side="left", padx=8, ipady=3)
        tk.Checkbutton(pwrow, text="প্রোগ্রাম খোলা থাকা পর্যন্ত মনে রাখুন (ফাইলে সেভ হয় না)", variable=self.v_remember, bg=P["card"],
                       activebackground=P["card"], font=f.tiny, fg=P["text"], anchor="w", highlightthickness=0,
                       selectcolor="white").pack(side="left")
        Button(pwrow, "সার্ভার সেটিং…", self._server_settings, kind="ghost", font=f.tiny, padx=6, pady=3).pack(side="right")
        inner = tk.Frame(bar, bg=P["card"])
        inner.pack(fill="x", padx=14, pady=10)
        self.send_btn = Button(inner, "✉  পাঠান", self._send, kind="primary", font=f.big, padx=26, pady=9)
        self.send_btn.pack(side="left")
        self.test_btn = Button(inner, "নিজেকে টেস্ট পাঠান", self._send_test, kind="secondary", font=f.body, padx=14, pady=8)
        self.test_btn.pack(side="left", padx=10)
        Button(inner, "বন্ধ", self.destroy, kind="secondary", font=f.body, padx=14, pady=8).pack(side="right")
        self.status = tk.StringVar(value="")
        tk.Label(inner, textvariable=self.status, bg=P["card"], fg=P["text"], font=f.small, anchor="w", justify="left",
                 wraplength=520).pack(side="left", padx=10, fill="x", expand=True)

        self._fill_from_template()
        self._draw_signature()
        self._refresh_checks()
        self._refresh_from()
        self.center()
        self.after(100, self._poll)

    # -------------------------------------------------------------- template / text
    def _mark_edited(self, _e=None):
        if self.body.edit_modified():
            self.edited = True
        self.body.edit_modified(False)

    def _fill_from_template(self):
        subject, body = render(self.tpl.get(), self.facts)
        self.v_subject.set(subject)
        self.body.delete("1.0", "end")
        self.body.insert("1.0", body.strip())
        self.body.edit_modified(False)
        self.edited = False
        self.tpl_hint.config(text=dict(TEMPLATES).get(self.tpl.get(), ""))

    def _apply_template(self):
        if self.edited and not messagebox.askyesno("নমুনা বদলাবেন?", "আপনি বার্তাটি সম্পাদনা করেছেন। নতুন নমুনা বসালে সেই পরিবর্তন মুছে যাবে।", parent=self):
            return
        self._fill_from_template()
        self.app.settings["mail_template"] = self.tpl.get()
        from . import config
        config.save_settings({"mail_template": self.tpl.get()})

    def _refresh_from(self):
        self.from_lbl.config(text=f"প্রেরক: {self.smtp.from_name} <{self.smtp.from_addr}>")

    # -------------------------------------------------------------- signature preview
    def _draw_signature(self):
        for w in self.sig_box.winfo_children():
            w.destroy()
        f = self.f
        txt = tk.Frame(self.sig_box, bg=P["card"])
        txt.pack(side="left", anchor="n")
        tk.Label(txt, text=self.sig.get("closing", ""), bg=P["card"], fg=P["text"], font=f.small, anchor="w").pack(fill="x")
        tk.Label(txt, text=self.sig.get("name", ""), bg=P["card"], fg=P["text"], font=f.h3, anchor="w").pack(fill="x")
        for key, pre in (("title", ""), ("phone", "Phone: "), ("company", "")):
            if self.sig.get(key):
                tk.Label(txt, text=pre + self.sig[key], bg=P["card"], fg=P["mute"], font=f.tiny, anchor="w").pack(fill="x")
        logo = sigmod.logo_file(self.sig)
        if logo:
            try:
                img = tk.PhotoImage(file=str(logo))
                shrink = max(1, round(img.width() / 110))
                self._logo_img = img.subsample(shrink, shrink)
                tk.Label(self.sig_box, image=self._logo_img, bg=P["card"]).pack(side="right", anchor="n", padx=(10, 0))
            except tk.TclError:
                tk.Label(self.sig_box, text="[logo]", bg=P["card"], fg=P["mute"], font=f.tiny).pack(side="right")

    def _edit_signature(self):
        SignatureDialog(self.app, on_save=self._after_signature)

    def _after_signature(self):
        self.sig = sigmod.load_signature()
        self._draw_signature()
        self.center()

    # -------------------------------------------------------------- checks
    def _refresh_checks(self):
        for w in self.checks.winfo_children():
            w.destroy()
        items = []
        ck = (self.d.dash or {}).get("check")
        if ck:
            ok = not ck["missing"]
            items.append((ok, f"ড্যাশবোর্ডের Submitted {ck['dashboard']} টি ফাইল · রিপোর্টে মিলেছে {ck['matched']} টি"))
        fa = self.facts
        items.append((True, f"Complete {fa.complete_files} ফাইল ({fa.complete_rows} সারি) · Incomplete {fa.incomplete_files} ফাইল ({fa.incomplete_rows} সারি)"))
        if self.xlsx and self.xlsx.is_file():
            try:
                n = count_blue_cells(self.xlsx)
            except Exception as exc:                                  # noqa: BLE001
                n, items = -1, items + [(False, f"Excel পড়া যায়নি: {exc}")]
            if n == 0:
                items.append((True, "কোনো হালকা-নীল (কারণ নেই) ঘর বাকি নেই"))
            elif n > 0:
                items.append((False, f"{n} টি ঘর হালকা-নীল—কারণ পাওয়া যায়নি। Excel-এ লিখে সেভ করে ‘আবার যাচাই’ চাপুন, অথবা এভাবেই পাঠান"))
        else:
            items.append((False, "Excel ফাইলটি আর পাওয়া যাচ্ছে না"))
        prev = mailer.already_sent(self.d.report_date, self.d.slot)
        if prev:
            items.append((False, f"এই তারিখ/ফেজের ইমেইল আগেই পাঠানো হয়েছে ({prev['sent_at']})"))
        for ok, text in items:
            r = tk.Frame(self.checks, bg=P["card"])
            r.pack(fill="x", pady=1)
            tk.Label(r, text="✓" if ok else "⚠", bg=P["card"], fg=P["ok"] if ok else P["warn"], font=self.f.h3, width=2).pack(side="left", anchor="n")
            tk.Label(r, text=text, bg=P["card"], fg=P["text"], font=self.f.tiny, anchor="w", justify="left", wraplength=330).pack(side="left", fill="x")

    def _add_file(self):
        path = filedialog.askopenfilename(parent=self, title="সংযুক্ত করার ফাইল বাছুন")
        if path:
            self.extra.append(Path(path))
            self.extra_lbl.config(text="\n".join(f"📎 {p.name}" for p in self.extra))

    # -------------------------------------------------------------- server settings
    def _server_settings(self):
        ServerDialog(self.app, self.smtp, on_save=self._after_server)

    def _after_server(self, smtp: mailer.SmtpSettings):
        self.smtp = smtp
        self._refresh_from()

    # -------------------------------------------------------------- draft + send
    def _draft(self, test: bool = False):
        to = mailer.parse_addresses(self.v_to.get())
        cc = mailer.parse_addresses(self.v_cc.get())
        bcc = mailer.parse_addresses(self.v_bcc.get())
        subject = self.v_subject.get().strip()
        atts: list[Path] = []
        tmp = None
        if self.xlsx and self.xlsx.is_file():
            if self.chk_present and self.strip.get():
                tmp = Path(tempfile.mkdtemp(prefix="vrb_mail_"))
                atts.append(strip_checklist(self.xlsx, tmp / self.xlsx.name))
            else:
                atts.append(self.xlsx)
        if self.pdf and self.use_pdf.get():
            atts.append(self.pdf)
        atts += self.extra
        if test:
            to, cc, bcc, subject = [self.smtp.from_addr], [], [], "[TEST] " + subject
        draft = mailer.MailDraft(to=to, cc=cc, bcc=bcc, subject=subject, body=self.body.get("1.0", "end").strip(),
                                 attachments=[str(p) for p in atts], signature=self.sig)
        return draft, tmp

    def _password(self) -> str | None:
        pw = self.v_pw.get()
        if not pw and self.smtp.security != "none":
            messagebox.showwarning("পাসওয়ার্ড দিন", "ইমেইল পাঠাতে verify@barikoi.com-এর Zoho App Password দিন।\n"
                                   "(Zoho Mail → My Account → Security → App Passwords)", parent=self)
            return None
        return pw or None

    def _send_test(self):
        self._go(test=True)

    def _send(self):
        self._go(test=False)

    def _go(self, test: bool):
        if self.sending:
            return
        if not self.v_to.get().strip() and not test:
            messagebox.showwarning("প্রাপক নেই", "To ঘরে অন্তত একটি ঠিকানা দিন।", parent=self)
            return
        try:
            draft, tmp = self._draft(test)
        except Exception as exc:                                       # noqa: BLE001
            messagebox.showerror("ফাইল তৈরি হয়নি", f"{type(exc).__name__}: {exc}", parent=self)
            return
        problems = mailer.check_draft(draft)
        if problems:
            self._cleanup(tmp)
            messagebox.showwarning("পাঠানো যাচ্ছে না", "\n".join("• " + p for p in problems), parent=self)
            return
        pw = self._password()
        if pw is None and self.smtp.security != "none":
            self._cleanup(tmp)
            return
        if not test:
            blue = count_blue_cells(Path(self.xlsx)) if self.xlsx and self.xlsx.is_file() else 0
            prev = mailer.already_sent(self.d.report_date, self.d.slot)
            lines = [f"প্রেরক: {self.smtp.from_name} <{self.smtp.from_addr}>", f"To: {', '.join(draft.to)}"]
            if draft.cc:
                lines.append(f"Cc: {', '.join(draft.cc)}")
            lines += [f"Subject: {draft.subject}", "সংযুক্তি: " + ", ".join(Path(p).name for p in draft.attachments)]
            if blue:
                lines.append(f"\n⚠ {blue} টি ঘর এখনও হালকা-নীল (কারণ নেই)।")
            if prev:
                lines.append(f"\n⚠ একই তারিখ/ফেজের ইমেইল আগেই পাঠানো হয়েছে ({prev['sent_at']})।")
            if not messagebox.askyesno("নিশ্চিত করুন — পাঠাবেন?", "\n".join(lines), parent=self):
                self._cleanup(tmp)
                return
        if self.v_remember.get() and pw:
            self.app.smtp_password = pw
        else:
            self.app.smtp_password = ""
        mailer.save_recipients(mailer.parse_addresses(self.v_to.get()), mailer.parse_addresses(self.v_cc.get()),
                               mailer.parse_addresses(self.v_bcc.get()))
        mailer.save_smtp_settings(self.smtp)
        self.sending = True
        self.send_btn.enable(False)
        self.test_btn.enable(False)
        self.status.set("পাঠানো হচ্ছে…")
        threading.Thread(target=self._worker, args=(draft, pw, test, tmp), daemon=True).start()

    def _worker(self, draft, pw, test, tmp):
        try:
            smtp = self.smtp
            if test:                                           # test goes to yourself only (no Bcc copy)
                smtp = mailer.SmtpSettings(**{**self.smtp.__dict__, "bcc_self": False})
            msg = mailer.build_message(draft, smtp)
            mailer.send_message(msg, smtp, pw, mailer.envelope_recipients(draft, smtp))
            if not test:
                mailer.log_sent(self.d.report_date, self.d.slot, draft, Path(draft.attachments[0]).name)
            self.q.put(("ok", test, len(draft.to) + len(draft.cc)))
        except mailer.MailError as exc:
            self.q.put(("err", str(exc)))
        except Exception as exc:                               # noqa: BLE001
            self.q.put(("err", f"{type(exc).__name__}: {exc}"))
        finally:
            self._cleanup(tmp)

    @staticmethod
    def _cleanup(tmp):
        if tmp:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.sending = False
                self.send_btn.enable(True)
                self.test_btn.enable(True)
                if msg[0] == "ok":
                    if msg[1]:
                        self.status.set(f"✓ টেস্ট ইমেইল {self.smtp.from_addr}-এ পাঠানো হয়েছে। ইনবক্স দেখুন।")
                    else:
                        self.status.set(f"✓ পাঠানো হয়েছে ({msg[2]} জন প্রাপক)।")
                        self._refresh_checks()
                        messagebox.showinfo("পাঠানো হয়েছে", "ইমেইল সফলভাবে পাঠানো হয়েছে।\n(Sent তালিকা: সাইডবারের ‘পাঠানো ইমেইল’)", parent=self)
                else:
                    self.status.set("পাঠানো যায়নি।")
                    messagebox.showerror("পাঠানো যায়নি", msg[1], parent=self)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(150, self._poll)


# ======================================================================================== signature window
class SignatureDialog(_Base):
    def __init__(self, app, on_save=None):
        super().__init__(app, "ইমেইল সিগনেচার")
        self.on_save = on_save
        self.sig = sigmod.load_signature()
        self.vars = {k: tk.StringVar(value=self.sig.get(k, "")) for k in ("closing", "name", "title", "phone", "company", "logo_path")}
        self.use_logo = tk.BooleanVar(value=bool(self.sig.get("use_logo", True)))
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=12)
        body.pack()
        c = self.card(body, "সিগনেচারের তথ্য")
        c.pack()
        for key, label in (("closing", "শুভেচ্ছা"), ("name", "নাম"), ("title", "পদবি"), ("phone", "ফোন"), ("company", "কোম্পানি")):
            self.row(c.body, label, self.vars[key], 40)
        tk.Checkbutton(c.body, text="Barikoi লোগো যুক্ত করুন", variable=self.use_logo, bg=P["card"], activebackground=P["card"],
                       font=self.f.small, fg=P["text"], anchor="w", highlightthickness=0, selectcolor="white").pack(fill="x", pady=(6, 0))
        r = tk.Frame(c.body, bg=P["card"])
        r.pack(fill="x", pady=3)
        tk.Label(r, text="নিজের লোগো", bg=P["card"], fg=P["mute"], font=self.f.small, width=9, anchor="w").pack(side="left")
        Entry(r, self.f, self.vars["logo_path"], width=28).pack(side="left", ipady=3)
        Button(r, "বাছুন", self._pick, kind="secondary", font=self.f.tiny, padx=8, pady=4).pack(side="left", padx=4)
        tk.Label(c.body, text="ফাঁকা রাখলে Zoho-তে থাকা Barikoi লোগোই ব্যবহার হবে (PNG)।", bg=P["card"], fg=P["mute"], font=self.f.tiny,
                 anchor="w").pack(fill="x")
        row = tk.Frame(body, bg=P["bg"])
        row.pack(pady=(10, 0))
        Button(row, "সংরক্ষণ", self._save, kind="primary", font=self.f.body, padx=18, pady=7).pack(side="left", padx=4)
        Button(row, "আগের মতো করুন", self._reset, kind="secondary", font=self.f.body, padx=14, pady=7).pack(side="left", padx=4)
        Button(row, "বন্ধ", self.destroy, kind="secondary", font=self.f.body, padx=14, pady=7).pack(side="left", padx=4)
        self.center()

    def _pick(self):
        path = filedialog.askopenfilename(parent=self, title="লোগো (PNG)", filetypes=[("PNG", "*.png"), ("All", "*.*")])
        if path:
            self.vars["logo_path"].set(path)

    def _reset(self):
        for k, v in self.vars.items():
            v.set(sigmod.DEFAULT_SIGNATURE.get(k, ""))
        self.use_logo.set(True)

    def _save(self):
        sig = {k: v.get().strip() for k, v in self.vars.items()}
        sig["use_logo"] = self.use_logo.get()
        sig["tagline"] = self.sig.get("tagline", "")
        sigmod.save_signature(sig)
        if self.on_save:
            self.on_save()
        self.destroy()


# ======================================================================================== server window
class ServerDialog(_Base):
    def __init__(self, app, smtp: mailer.SmtpSettings, on_save=None):
        super().__init__(app, "পাঠানোর সার্ভার")
        self.smtp, self.on_save = smtp, on_save
        self.v = {"host": tk.StringVar(value=smtp.host), "port": tk.StringVar(value=str(smtp.port)),
                  "username": tk.StringVar(value=smtp.username), "from_addr": tk.StringVar(value=smtp.from_addr),
                  "from_name": tk.StringVar(value=smtp.from_name)}
        self.sec = tk.StringVar(value=smtp.security)
        self.bcc_self = tk.BooleanVar(value=smtp.bcc_self)
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=12)
        body.pack()
        c = self.card(body, "SMTP সেটিং (Zoho Mail)")
        c.pack()
        r = tk.Frame(c.body, bg=P["card"])
        r.pack(fill="x", pady=3)
        tk.Label(r, text="সার্ভার", bg=P["card"], fg=P["mute"], font=self.f.small, width=12, anchor="w").pack(side="left")
        cb = ttk.Combobox(r, textvariable=self.v["host"], values=[h for h, _n in mailer.SMTP_PRESETS], width=34)
        cb.pack(side="left")
        self.row(c.body, "পোর্ট", self.v["port"], 8, labelw=12)
        r2 = tk.Frame(c.body, bg=P["card"])
        r2.pack(fill="x", pady=3)
        tk.Label(r2, text="নিরাপত্তা", bg=P["card"], fg=P["mute"], font=self.f.small, width=12, anchor="w").pack(side="left")
        Segmented(r2, self.f, [("ssl", "SSL 465"), ("starttls", "STARTTLS 587")], self.sec, self._sec_changed).pack(side="left")
        self.row(c.body, "লগইন ইউজার", self.v["username"], 34, labelw=12)
        self.row(c.body, "From ঠিকানা", self.v["from_addr"], 34, labelw=12)
        self.row(c.body, "From নাম", self.v["from_name"], 34, labelw=12)
        tk.Checkbutton(c.body, text="প্রতিটি ইমেইলের একটি কপি নিজের ঠিকানায় (Bcc) রাখুন", variable=self.bcc_self, bg=P["card"],
                       activebackground=P["card"], font=self.f.small, fg=P["text"], anchor="w", highlightthickness=0,
                       selectcolor="white").pack(fill="x", pady=(6, 0))
        tk.Label(c.body, text="Zoho-র ডেটা সেন্টার অনুযায়ী সার্ভার বদলাতে পারে (smtp.zoho.com / .in / .eu / .com.au)।\n"
                              "লগইনে সাধারণ পাসওয়ার্ড নয়—App Password লাগবে। এটি কোথাও সংরক্ষণ হয় না।", bg=P["card"], fg=P["mute"],
                 font=self.f.tiny, anchor="w", justify="left").pack(fill="x", pady=(6, 0))
        row = tk.Frame(body, bg=P["bg"])
        row.pack(pady=(10, 0))
        Button(row, "সংরক্ষণ", self._save, kind="primary", font=self.f.body, padx=18, pady=7).pack(side="left", padx=4)
        Button(row, "বন্ধ", self.destroy, kind="secondary", font=self.f.body, padx=14, pady=7).pack(side="left", padx=4)
        self.center()

    def _sec_changed(self):
        self.v["port"].set("465" if self.sec.get() == "ssl" else "587")

    def _save(self):
        try:
            port = int(self.v["port"].get())
        except ValueError:
            messagebox.showwarning("পোর্ট ঠিক নেই", "পোর্ট সংখ্যায় দিন (যেমন 465)।", parent=self)
            return
        bad = mailer.invalid_addresses([self.v["from_addr"].get().strip()])
        if bad:
            messagebox.showwarning("ঠিকানা ঠিক নেই", "From ঠিকানাটি সঠিক ইমেইল নয়।", parent=self)
            return
        s = mailer.SmtpSettings(host=self.v["host"].get().strip(), port=port, security=self.sec.get(),
                                username=self.v["username"].get().strip(), from_addr=self.v["from_addr"].get().strip(),
                                from_name=self.v["from_name"].get().strip(), bcc_self=self.bcc_self.get())
        mailer.save_smtp_settings(s)
        if self.on_save:
            self.on_save(s)
        self.destroy()


# ======================================================================================== sent history
class SentLogDialog(_Base):
    def __init__(self, app):
        super().__init__(app, "পাঠানো ইমেইল")
        body = tk.Frame(self, bg=P["bg"], padx=14, pady=12)
        body.pack()
        c = self.card(body, "সর্বশেষ পাঠানো ইমেইল")
        c.pack()
        rows = mailer.sent_log()
        box = tk.Listbox(c.body, width=96, height=12, font=self.f.small, relief="flat", highlightthickness=1,
                         highlightbackground=P["line"], activestyle="none")
        box.pack()
        if not rows:
            box.insert("end", "এখনও কোনো ইমেইল পাঠানো হয়নি।")
        for e in rows:
            ph = "1st" if e.get("slot") == "3pm" else "2nd"
            box.insert("end", f"{e.get('sent_at', '')}   {e.get('report_date', '')}  {ph} phase   →  {', '.join(e.get('to', []))[:60]}")
        tk.Label(c.body, text="শুধু তারিখ, ফেজ ও প্রাপকের তালিকা রাখা হয়—পাসওয়ার্ড বা রিপোর্টের তথ্য নয়।", bg=P["card"], fg=P["mute"],
                 font=self.f.tiny, anchor="w").pack(fill="x", pady=(6, 0))
        Button(body, "বন্ধ", self.destroy, kind="secondary", font=self.f.body, padx=14, pady=7).pack(pady=(10, 0))
        self.center()
