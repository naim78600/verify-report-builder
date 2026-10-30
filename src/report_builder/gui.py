"""Small desktop window (tkinter) - works on Windows and macOS."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, config
from .client import ApiError, AuthError, Cancelled
from .collect import RunConfig, collect
from .excel import build_workbook


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
