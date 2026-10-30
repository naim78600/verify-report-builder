"""Collect all files: login -> list pages -> per-file details (concurrent, polite)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

from . import config
from .client import ApiError, AuthError, Cancelled, ReadOnlyClient
from .model import normalize_file

Progress = Callable[[str, int, int, str], None]   # stage, done, total, message


@dataclass
class RunConfig:
    web: str
    api: str
    server_label: str
    email: str
    password: str
    days: int = config.DEFAULT_DAYS
    org_name: str = config.DEFAULT_ORG
    workers: int = config.DEFAULT_WORKERS


@dataclass
class CollectResult:
    files: list = field(default_factory=list)
    failed: list = field(default_factory=list)      # dicts: file_no, id, reason
    site_total: int = 0
    listed: int = 0
    date_from: date | None = None
    date_till: date | None = None
    org_name: str = ""
    server_label: str = ""
    generated_at: datetime | None = None
    notes: list = field(default_factory=list)


def _noop(*_a, **_k):
    pass


def collect(cfg: RunConfig, progress: Progress = _noop, cancel: threading.Event | None = None) -> CollectResult:
    cancel = cancel or threading.Event()
    workers = max(1, min(int(cfg.workers), config.MAX_WORKERS))
    client = ReadOnlyClient(cfg.web, cfg.api, cancel=cancel)
    res = CollectResult(server_label=cfg.server_label, org_name=cfg.org_name, generated_at=datetime.now())

    # 1. login ----------------------------------------------------------------
    progress("login", 0, 1, "লগইন হচ্ছে…")
    client.login(cfg.email, cfg.password)
    user = client.get("/api/v2/auth/user").get("data", {})
    orgs = user.get("organizations") or []
    match = [o for o in orgs if (o.get("name") or "").strip().lower() == cfg.org_name.strip().lower()]
    if not match:
        names = ", ".join(o.get("name", "?") for o in orgs) or "কোনোটিই নয়"
        raise ApiError(f"“{cfg.org_name}” নামে কোনো সংস্থা পাওয়া যায়নি। আপনার অ্যাকাউন্টে আছে: {names}")
    org_uuid = match[0]["uuid"]
    agent_names: dict[int, str] = {}
    progress("login", 1, 1, "লগইন সম্পন্ন।")

    # 2. filters --------------------------------------------------------------
    res.date_till = date.today()
    res.date_from = res.date_till - timedelta(days=int(cfg.days))

    def list_params(page: int):
        params = [
            ("dateFrom", res.date_from.isoformat()),
            ("dateTill", res.date_till.isoformat()),
            ("page", page),
            ("sort_by", "end_date"),
            ("sort_order", "ASC"),
            ("org_id[]", org_uuid),
        ]
        params += [("status[]", s) for s in config.ALL_FILE_STATUS_CODES]
        return params

    # 3. list pages -----------------------------------------------------------
    progress("list", 0, 1, "ফাইলের তালিকা সংগ্রহ হচ্ছে…")
    first = client.get("/api/v2/manager/applications", list_params(1))["applications"]
    last_page = int(first.get("last_page") or 1)
    res.site_total = int(first.get("total") or 0)
    pages: dict[int, list] = {1: first.get("data") or []}
    progress("list", 1, last_page, f"তালিকা: পেজ ১/{last_page}")
    if last_page > 1:
        done = 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(client.get, "/api/v2/manager/applications", list_params(p)): p
                    for p in range(2, last_page + 1)}
            try:
                for fut in as_completed(futs):
                    p = futs[fut]
                    pages[p] = fut.result()["applications"].get("data") or []
                    done += 1
                    progress("list", done, last_page, f"তালিকা: {done}/{last_page} পেজ")
            except BaseException:
                for f in futs:
                    f.cancel()
                raise
    items: dict = {}
    for p in sorted(pages):
        for it in pages[p]:
            items.setdefault(it["id"], it)           # de-duplicate by id
    res.listed = len(items)
    if res.listed != res.site_total:
        res.notes.append(
            f"সতর্কতা: সাইটের মোট ফাইল {res.site_total}, কিন্তু তালিকায় পাওয়া গেছে {res.listed}।"
        )
    progress("list", last_page, last_page, f"মোট {res.listed} টি ফাইল পাওয়া গেছে (সাইটের মোট: {res.site_total})")

    # 4. details --------------------------------------------------------------
    total = len(items)
    details: dict = {}
    errors: dict = {}
    done = 0

    def fetch(fid):
        return client.get(f"/api/v2/manager/applications/{fid}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fetch, fid): fid for fid in items}
        try:
            for fut in as_completed(futs):
                fid = futs[fut]
                try:
                    details[fid] = fut.result()
                except AuthError:
                    raise
                except Cancelled:
                    raise
                except Exception as exc:          # keep going, list it as failed later
                    errors[fid] = str(exc)
                done += 1
                progress("detail", done, total, f"ফাইল {done}/{total} সংগ্রহ হয়েছে")
        except BaseException:
            for f in futs:
                f.cancel()
            raise

    # one more sequential try for the failures (server may have recovered)
    for fid in list(errors):
        if cancel.is_set():
            raise Cancelled()
        try:
            details[fid] = fetch(fid)
            del errors[fid]
        except AuthError:
            raise
        except Cancelled:
            raise
        except Exception as exc:
            errors[fid] = str(exc)

    # 5. normalise ------------------------------------------------------------
    for fid, it in items.items():
        if fid in details:
            try:
                res.files.append(normalize_file(it, details[fid], agent_names))
            except Exception as exc:
                res.failed.append({"id": fid, "file_no": it.get("application_id", ""), "reason": f"ডেটা পড়তে সমস্যা: {exc}"})
        else:
            res.failed.append({"id": fid, "file_no": it.get("application_id", ""), "reason": errors.get(fid, "অজানা ত্রুটি")})
    res.files.sort(key=lambda f: f["file_no"])
    res.failed.sort(key=lambda f: str(f["file_no"]))
    return res
