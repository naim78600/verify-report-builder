"""Small, self-drawn widgets so the window looks the same (and modern) on Windows and Mac.

Only plain tkinter is used (no extra packages), which keeps the single-file app small.
"""
from __future__ import annotations

import calendar
import os
import tkinter as tk
import tkinter.font as tkfont
from datetime import date, datetime

P = {   # v12 look: Barikoi colours (barikoi.com: green #16A249, light green #D1FAE2, slate page), white side bar
    "side": "#FFFFFF", "side_hi": "#D1FAE2", "side_tx": "#334155", "side_mute": "#64748B", "side_on": "#0F7A36",
    "bg": "#F8FAFC", "card": "#FFFFFF", "line": "#E2E8F0", "text": "#020817", "mute": "#64748B",
    "accent": "#16A249", "accent_hi": "#0F7A36", "accent_soft": "#D1FAE2", "navy": "#1F3A5F", "ink": "#020817",
    "ok": "#15803D", "ok_bg": "#DCFCE7", "warn": "#B45309", "warn_bg": "#FEF3C7", "bad": "#B91C1C", "bad_bg": "#FEE2E2",
    "off": "#E5E7EB", "off_tx": "#9CA3AF", "wa": "#16A34A",
}


def pick_font_family(root) -> str | None:
    wanted = ["Nirmala UI", "Kohinoor Bangla", "Bangla Sangam MN", "Noto Sans Bengali", "Vrinda", "FreeSans"]
    forced = os.environ.get("VRB_FONT")
    if forced:
        wanted.insert(0, forced)
    have = set(tkfont.families(root))
    return next((f for f in wanted if f in have), None)


class Fonts:
    def __init__(self, root, family: str | None):
        base = family or tkfont.nametofont("TkDefaultFont").actual("family")
        mk = lambda size, bold=False: tkfont.Font(root=root, family=base, size=size, weight="bold" if bold else "normal")  # noqa: E731
        self.family = base
        self.title, self.h2, self.h3 = mk(20, True), mk(13, True), mk(11, True)
        self.body, self.small, self.tiny = mk(11), mk(10), mk(9)
        self.btn, self.big = mk(11, True), mk(13, True)


class Button(tk.Label):
    """Flat button made from a Label (colours are honoured on every OS)."""
    KINDS = {
        "primary": ("#FFFFFF", P["accent"], P["accent_hi"]),
        "dark": ("#FFFFFF", P["ink"], "#374151"),
        "green": ("#FFFFFF", P["wa"], "#15803D"),
        "secondary": (P["text"], "#FFFFFF", "#F3F4F6"),
        "ghost": (P["side_tx"], P["side"], P["side_hi"]),
        "danger": (P["bad"], P["bad_bg"], "#FECACA"),
        "soft": (P["accent_hi"], P["accent_soft"], "#BBF7D0"),
    }

    def __init__(self, parent, text, command, kind="secondary", font=None, padx=16, pady=8, **kw):
        fg, bg, hi = self.KINDS[kind]
        if kind == "secondary":
            kw.setdefault("highlightthickness", 1)
            kw.setdefault("highlightbackground", "#D1D5DB")
        super().__init__(parent, text=text, fg=fg, bg=bg, font=font, padx=padx, pady=pady, cursor="hand2", **kw)
        self._cmd, self._fg, self._bg, self._hi, self._on = command, fg, bg, hi, True
        self.bind("<Button-1>", lambda _e: self._on and self._cmd())
        self.bind("<Enter>", lambda _e: self._on and self.config(bg=self._hi))
        self.bind("<Leave>", lambda _e: self.config(bg=self._bg if self._on else P["off"]))

    def enable(self, on: bool):
        self._on = on
        self.config(bg=self._bg if on else P["off"], fg=self._fg if on else P["off_tx"], cursor="hand2" if on else "arrow")


class Card(tk.Frame):
    def __init__(self, parent, fonts: Fonts, title: str, step: str = ""):
        super().__init__(parent, bg=P["card"], highlightbackground=P["line"], highlightthickness=1)
        head = tk.Frame(self, bg=P["card"])
        head.pack(fill="x", padx=16, pady=(12, 4))
        if step:
            tk.Label(head, text=step, bg=P["accent_soft"], fg=P["accent"], font=fonts.small, width=2).pack(side="left", padx=(0, 8))
        tk.Label(head, text=title, bg=P["card"], fg=P["text"], font=fonts.h3).pack(side="left")
        self.body = tk.Frame(self, bg=P["card"])
        self.body.pack(fill="both", expand=True, padx=16, pady=(2, 14))


class Segmented(tk.Frame):
    """Row of toggle buttons bound to a StringVar."""

    def __init__(self, parent, fonts: Fonts, options: list[tuple[str, str]], var: tk.StringVar, command=None):
        super().__init__(parent, bg="#F3F4F6")
        self.var, self.command, self.items = var, command, {}
        for i, (value, text) in enumerate(options):
            lb = tk.Label(self, text=text, font=fonts.small, padx=12, pady=5, cursor="hand2", bg="#F3F4F6", fg=P["text"])
            lb.grid(row=0, column=i, padx=2, pady=2)
            lb.bind("<Button-1>", lambda _e, v=value: self.select(v))
            self.items[value] = lb
        var.trace_add("write", lambda *_: self._paint())
        self._paint()

    def select(self, value):
        self.var.set(value)
        if self.command:
            self.command()

    def _paint(self):
        for v, lb in self.items.items():
            on = self.var.get() == v
            lb.config(bg=P["accent"] if on else "#F3F4F6", fg="white" if on else P["text"])


class Entry(tk.Entry):
    def __init__(self, parent, fonts: Fonts, var, show=None, width=24, justify="left"):
        super().__init__(parent, textvariable=var, show=show or "", width=width, font=fonts.body, relief="flat", bg="white",
                         fg=P["text"], insertbackground=P["text"], highlightthickness=1, highlightbackground=P["line"],
                         highlightcolor=P["accent"], justify=justify, disabledbackground="#EEF2F7", disabledforeground=P["off_tx"])

    def enable(self, on: bool):
        self.config(state="normal" if on else "disabled")


def parse_date(text: str) -> date | None:
    t = (text or "").strip().replace("/", "-").replace(".", "-")
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d-%m-%y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


class DateField(tk.Frame):
    """Entry (dd-mm-yyyy) + calendar pop-up."""

    def __init__(self, parent, fonts: Fonts, initial: date):
        super().__init__(parent, bg=P["card"])
        self.fonts = fonts
        self.var = tk.StringVar(value=f"{initial:%d-%m-%Y}")
        self.entry = Entry(self, fonts, self.var, width=11, justify="center")
        self.entry.pack(side="left", ipady=4)
        self.btn = tk.Label(self, text="📅", font=fonts.body, bg=P["card"], cursor="hand2")
        self.btn.pack(side="left", padx=(6, 0))
        self.btn.bind("<Button-1>", lambda _e: self._open())
        self._enabled = True

    def get(self) -> date | None:
        return parse_date(self.var.get())

    def enable(self, on: bool):
        self._enabled = on
        self.entry.enable(on)
        self.btn.config(fg=P["text"] if on else P["off_tx"], cursor="hand2" if on else "arrow")

    def _open(self):
        if not self._enabled:
            return
        CalendarPopup(self, self.fonts, self.get() or date.today(), self._picked)

    def _picked(self, d: date):
        self.var.set(f"{d:%d-%m-%Y}")


class CalendarPopup(tk.Toplevel):
    def __init__(self, anchor: tk.Widget, fonts: Fonts, start: date, on_pick):
        super().__init__(anchor)
        self.title("তারিখ বাছুন")
        self.resizable(False, False)
        self.transient(anchor.winfo_toplevel())
        self.configure(bg=P["card"], padx=10, pady=10)
        self.fonts, self.on_pick, self.year, self.month, self.sel = fonts, on_pick, start.year, start.month, start
        self.top = tk.Frame(self, bg=P["card"])
        self.top.pack(fill="x")
        self.grid_f = tk.Frame(self, bg=P["card"])
        self.grid_f.pack(pady=(6, 0))
        self._draw()
        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        self.geometry(f"+{x}+{y}")
        self.grab_set()

    def _shift(self, months: int):
        m = self.month - 1 + months
        self.year += m // 12
        self.month = m % 12 + 1
        self._draw()

    def _draw(self):
        for w in self.top.winfo_children() + self.grid_f.winfo_children():
            w.destroy()
        for txt, d in (("‹", -1), ("›", 1)):
            b = tk.Label(self.top, text=txt, font=self.fonts.big, bg=P["card"], fg=P["navy"], cursor="hand2", width=2)
            b.pack(side="left" if d < 0 else "right")
            b.bind("<Button-1>", lambda _e, k=d: self._shift(k))
        tk.Label(self.top, text=f"{calendar.month_name[self.month]} {self.year}", font=self.fonts.h3, bg=P["card"],
                 fg=P["text"]).pack(side="top")
        for i, wd in enumerate(("Su", "Mo", "Tu", "We", "Th", "Fr", "Sa")):
            tk.Label(self.grid_f, text=wd, font=self.fonts.tiny, bg=P["card"], fg=P["mute"], width=4).grid(row=0, column=i)
        cal = calendar.Calendar(firstweekday=6)
        today = date.today()
        for r, week in enumerate(cal.monthdatescalendar(self.year, self.month), 1):
            for c, d in enumerate(week):
                inm = d.month == self.month
                is_sel, is_today = d == self.sel, d == today
                lb = tk.Label(self.grid_f, text=str(d.day), font=self.fonts.small, width=4, pady=3, cursor="hand2",
                              bg=P["accent"] if is_sel else (P["accent_soft"] if is_today else P["card"]),
                              fg="white" if is_sel else (P["text"] if inm else P["off_tx"]))
                lb.grid(row=r, column=c, padx=1, pady=1)
                lb.bind("<Button-1>", lambda _e, dd=d: self._pick(dd))

    def _pick(self, d: date):
        self.on_pick(d)
        self.destroy()


class Progress(tk.Canvas):
    def __init__(self, parent, fonts: Fonts, height=12):
        super().__init__(parent, height=height, bg=P["card"], highlightthickness=0)
        self.value = 0.0
        self.bind("<Configure>", lambda _e: self._draw())

    def set(self, fraction: float):
        self.value = max(0.0, min(1.0, fraction))
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), int(self["height"])
        self.create_rectangle(0, 0, w, h, fill="#E5EAF3", outline="")
        if self.value > 0:
            self.create_rectangle(0, 0, w * self.value, h, fill=P["accent"], outline="")


class Stepper(tk.Frame):
    """Shows which stage of the run is active."""

    def __init__(self, parent, fonts: Fonts, labels: list[str]):
        super().__init__(parent, bg=P["card"])
        self.labels = []
        for i, t in enumerate(labels):
            lb = tk.Label(self, text=f"{i + 1}. {t}", font=fonts.tiny, bg=P["card"], fg=P["off_tx"], padx=6)
            lb.pack(side="left")
            self.labels.append(lb)

    def set(self, index: int):
        for i, lb in enumerate(self.labels):
            if index < 0:
                lb.config(fg=P["off_tx"])
            elif i < index:
                lb.config(fg=P["ok"])
            elif i == index:
                lb.config(fg=P["accent"])
            else:
                lb.config(fg=P["off_tx"])


class Tile(tk.Frame):
    """Radio tile: title + one-line help."""

    def __init__(self, parent, fonts: Fonts, value: str, title: str, help_: str, var: tk.StringVar, command=None):
        super().__init__(parent, bg=P["card"], highlightthickness=1, highlightbackground=P["line"], cursor="hand2")
        self.value, self.var, self.command = value, var, command
        self.t = tk.Label(self, text=title, font=fonts.h3, bg=P["card"], fg=P["text"], anchor="w", justify="left")
        self.t.pack(fill="x", padx=10, pady=(6, 0))
        self.h = tk.Label(self, text=help_, font=fonts.tiny, bg=P["card"], fg=P["mute"], anchor="w", justify="left", wraplength=360)
        self.h.pack(fill="x", padx=10, pady=(0, 6))
        for w in (self, self.t, self.h):
            w.bind("<Button-1>", lambda _e: self._click())
        var.trace_add("write", lambda *_: self._paint())
        self._paint()

    def _click(self):
        self.var.set(self.value)
        if self.command:
            self.command()

    def _paint(self):
        on = self.var.get() == self.value
        bg = P["accent_soft"] if on else P["card"]
        self.config(bg=bg, highlightbackground=P["accent"] if on else P["line"], highlightthickness=2 if on else 1)
        self.t.config(bg=bg)
        self.h.config(bg=bg)
