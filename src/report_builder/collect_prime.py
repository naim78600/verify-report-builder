"""Event-based collection for the Prime Bank report (read-only).

Steps
  1  login, organisation
  2  files created in the chosen window                         (list pages + one detail call per file)
  3  Re-CPV tracker for the last year (one call)
  4  OLD files that had a Re-CPV or an Extra trip created inside the window
       - Re-CPV: taken straight from the tracker
       - Extra trips: older files found from the list (no detail call) by trip id, then opened
  5  activity log of the files that may have a submission                (one GET per file)
  6  billing rows (billing.py), TAT, selection (complete / incomplete)
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import config, holidays as hol
from .activity import parse_logs
from .billing import (INCOMPLETE_SCOPES, LOOKBACK_DAYS, PHASE1_CUTOFF, SCOPE_TEXT, apply_as_of, assign_sub_days, build_rows, compute_tat,
                      dashboard_check, fill_history, reconcile, select_rows, tracker_window, BillRow, FileLogs)
from .client import ApiError, AuthError, Cancelled, ReadOnlyClient
from .collect import Progress, RunConfig, _noop
from .model import normalize_file
from .recpv import fetch_tracker, index

HISTORY_DAYS = 365
TRIP_ID_MARGIN = 2500          # safety margin when guessing which older files may hold new trips
SUBMITTED, PARTIAL = 6, 7                 # file status codes of "Submitted" / "Partially Submitted"
LOG_STATUSES = {1, 2, 3, 4, 5, 6, 7, 8}  # every file: the log gives Submitted time AND the Last Update column


@dataclass
class PrimeConfig(RunConfig):
    mode: str = "tracker"                  # "tracker" (daily 3pm/7pm) | "range" (all files of a period; "billing" = old name)
    report_date: date | None = None        # tracker: the date in the title (default today)
    date_from: date | None = None          # period start / end (None = use `days`)
    date_till: date | None = None
    slot: str = "3pm"                      # "3pm" (1st phase, 3:30 PM mail) | "7pm" (2nd phase, full day)
    find_old_extras: bool = True
    incomplete_scope: str = "sla_partial"  # tracker Incomplete list: "sla_partial" (V3) | "partial_today" | "partial_open" | "all_pending"
    after3_only: bool = False              # 2nd phase only: Complete = just the rows submitted after 3 PM (not in the 1st mail)


@dataclass
class PrimeData:
    mode: str = "tracker"
    org_name: str = ""
    server_label: str = ""
    generated_at: datetime | None = None
    report_date: date | None = None
    slot: str = "3pm"
    incomplete_scope: str = "sla_partial"
    after3_only: bool = False
    track_from: date | None = None          # tracker: first day it covers (the day after the previous working day)
    rolled: int = 0                         # rows submitted on a day off and reported on the next working day
    w_from: date | None = None
    w_till: date | None = None
    complete: list = field(default_factory=list)
    incomplete: list = field(default_factory=list)
    all_rows: list = field(default_factory=list)
    files: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    recon: dict = field(default_factory=dict)
    holidays: dict = field(default_factory=dict)
    dash: dict = field(default_factory=dict)       # the dashboard's own Submitted list for the same dates + the match result
    site_total: int = 0
    old_files: int = 0
    tracker_total: int = 0
    log_failed: int = 0


def slot_for(now: datetime | None = None) -> str:
    """Laptop clock decides the headline: before 5 PM -> 3pm report, 5 PM or later -> 7pm."""
    now = now or datetime.now()
    return "3pm" if now.hour < 17 else "7pm"


PHASE_TEXT = {"3pm": "1st Phase · 3:30 PM", "7pm": "2nd Phase · 7:00 PM"}


def title_for(d: PrimeData) -> str:
    if d.mode == "tracker":
        return f"Prime Bank PLC · Submission Tracker · {d.report_date:%d %b %Y} · {PHASE_TEXT.get(d.slot, d.slot)}"
    a, b = d.w_from, d.w_till
    return f"Prime Bank PLC {a.day}-{a.month}-{a.year} to {b.day}-{b.month}-{b.year} Report"


# ---------------------------------------------------------------------------------------
def _pool_map(workers, cancel, fn, keys, progress=None, label=""):
    """Run fn(key) concurrently. -> ({key: result}, {key: error text})"""
    results, errors = {}, {}
    done = 0
    total = len(keys)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(fn, k): k for k in keys}
        try:
            for fut in as_completed(futs):
                k = futs[fut]
                try:
                    results[k] = fut.result()
                except (AuthError, Cancelled):
                    raise
                except Exception as exc:          # noqa: BLE001 - recorded, run continues
                    errors[k] = str(exc)
                done += 1
                if progress and (done % 5 == 0 or done == total):
                    progress(done, total)
        except BaseException:
            for f in futs:
                f.cancel()
            raise
    if cancel.is_set():
        raise Cancelled()
    return results, errors


NO_STATUS = "no-status"        # _list_files(statuses=NO_STATUS): send no status[] at all


def _list_files(client, org_uuid, d_from: date, d_till: date, workers, cancel, progress_cb,
                statuses=None) -> tuple[dict, int]:
    """All list items for a date window. Paging with sort ties can drop rows, so if the unique count is
    short of the server total we sweep again with another sort and merge.

    What the date window means depends on the status filter (checked on the live Reports page, 2026-11-05):
      * NO status[]        -> files whose Start Date (received) is inside the window, whatever their status now.
      * any status[] given -> files whose CURRENT status was entered inside the window: Submitted = the day it was
                              submitted, Hold = the day it went on hold, On Going / Created = the day it started.
                              This is also true when all eight codes are sent.
    `statuses` = file status codes (default: all eight); NO_STATUS = no filter."""
    codes = [] if statuses == NO_STATUS else (list(statuses) if statuses else config.ALL_FILE_STATUS_CODES)
    found: dict = {}
    total = 0
    sweeps = [("start_date", "DESC"), ("end_date", "ASC")]            # the only sort fields the live API accepts
    for n, (sort_by, order) in enumerate(sweeps):
        def params(page):
            p = [("dateFrom", d_from.isoformat()), ("dateTill", d_till.isoformat()), ("page", page),
                 ("sort_by", sort_by), ("sort_order", order), ("org_id[]", org_uuid)]
            return p + [("status[]", s) for s in codes]
        try:
            first = client.get("/api/v2/manager/applications", params(1))["applications"]
        except ApiError:
            if n == len(sweeps) - 1:
                raise
            continue                                  # this sort field is not accepted: try the next
        total = int(first.get("total") or 0)
        last = int(first.get("last_page") or 1)
        for it in first.get("data") or []:
            found[it["id"]] = it
        if last > 1:
            res, errs = _pool_map(workers, cancel, lambda p: client.get("/api/v2/manager/applications", params(p)),
                                  list(range(2, last + 1)), lambda d, t: progress_cb(d + 1, last))
            if errs:
                raise ApiError("তালিকার কিছু পেজ পড়া যায়নি: " + next(iter(errs.values())))
            for p in sorted(res):
                for it in res[p]["applications"].get("data") or []:
                    found.setdefault(it["id"], it)
        if len(found) >= total:
            break
    return found, total


def collect_prime(cfg: PrimeConfig, progress: Progress = _noop, cancel: threading.Event | None = None) -> PrimeData:
    cancel = cancel or threading.Event()
    workers = max(1, min(int(cfg.workers), config.MAX_WORKERS))
    client = ReadOnlyClient(cfg.web, cfg.api, cancel=cancel)
    now = datetime.now()
    today = now.date()
    d = PrimeData(mode=cfg.mode, org_name=cfg.org_name, server_label=cfg.server_label, generated_at=now,
                  slot=cfg.slot or slot_for(now))
    if cfg.mode == "tracker":
        d.report_date = cfg.report_date or today
        d.w_till = d.report_date
        d.w_from = cfg.date_from or (d.report_date - timedelta(days=LOOKBACK_DAYS))     # tracker: fixed 90-day look-back
    else:
        d.w_till = cfg.date_till or today
        d.w_from = cfg.date_from or (d.w_till - timedelta(days=int(cfg.days)))
        d.report_date = d.w_till
    if d.w_from > d.w_till:
        raise ApiError("শুরুর তারিখ শেষ তারিখের পরে হতে পারে না।")
    d.mode = "tracker" if cfg.mode == "tracker" else "range"
    d.incomplete_scope = cfg.incomplete_scope if cfg.incomplete_scope in INCOMPLETE_SCOPES else "sla_partial"
    d.after3_only = bool(cfg.after3_only and d.slot == "7pm")
    hist_from = d.w_from - timedelta(days=HISTORY_DAYS)
    holiday_map = hol.load()
    hset = set(holiday_map)
    if d.mode == "tracker":
        d.track_from, _hi = tracker_window(d.report_date, hset)

    # 1. login ----------------------------------------------------------------------
    progress("login", 0, 1, "লগইন হচ্ছে…")
    client.login(cfg.email, cfg.password)
    user = client.get("/api/v2/auth/user").get("data", {})
    orgs = user.get("organizations") or []
    match = [o for o in orgs if (o.get("name") or "").strip().lower() == cfg.org_name.strip().lower()]
    if not match:
        names = ", ".join(o.get("name", "?") for o in orgs) or "কোনোটিই নয়"
        raise ApiError(f"“{cfg.org_name}” নামে কোনো সংস্থা পাওয়া যায়নি। আপনার অ্যাকাউন্টে আছে: {names}")
    org_uuid = match[0]["uuid"]
    progress("login", 1, 1, "লগইন সম্পন্ন।")

    # 2. files of the window ---------------------------------------------------------
    # Two lists are merged.  (a) NO status filter = files that were RECEIVED (Start Date) inside the window,
    # whatever their status is today - this keeps files that were pending at the end of a past window but were
    # submitted / put on hold later.  (b) all statuses = files whose CURRENT status began inside the window
    # (re-opened old files, Hold, Finished ...), which is what the Reports page shows when statuses are picked.
    progress("list", 0, 1, "ফাইলের তালিকা সংগ্রহ হচ্ছে…")
    items, site_total = _list_files(client, org_uuid, d.w_from, d.w_till, workers, cancel,
                                    lambda a, b: progress("list", a, b, f"তালিকা (গ্রহণের তারিখ): পেজ {a}/{b}"),
                                    statuses=NO_STATUS)
    if len(items) != site_total:
        d.notes.append(f"সতর্কতা: সাইটের মোট ফাইল {site_total}, তালিকায় পাওয়া গেছে {len(items)}।")
    by_status, total_b = _list_files(client, org_uuid, d.w_from, d.w_till, workers, cancel,
                                     lambda a, b: progress("list", a, b, f"তালিকা (স্ট্যাটাস অনুযায়ী): পেজ {a}/{b}"))
    if len(by_status) != total_b:
        d.notes.append(f"সতর্কতা: স্ট্যাটাস-তালিকায় সাইটের মোট {total_b}, পাওয়া গেছে {len(by_status)}।")
    for fid, it in by_status.items():
        items.setdefault(fid, it)
    d.site_total = len(items)
    progress("list", 1, 1, f"মোট {len(items)} টি ফাইল (সাইটের মোট: {site_total}; স্ট্যাটাস-তালিকা: {total_b})")

    # 2b. the dashboard's own "Submitted" list for the same dates ------------------------------------
    # The Reports page (status = Submitted + the same dates + "Submit") lists files by the day they were
    # submitted - confirmed on the live page: it sends dateFrom/dateTill/org_id[]/status[]=6 and shows files whose
    # Start/End dates are days earlier.  The same request is made here, the files are added, and the finished
    # report is compared with that list at the end ("Dashboard check").
    dash_from, dash_till = (d.track_from, d.report_date) if d.mode == "tracker" else (d.w_from, d.w_till)
    d.dash = {"from": dash_from, "till": dash_till, "ok": False, "submitted": {}, "partial": {}}
    progress("list", 0, 1, "ড্যাশবোর্ডের Submitted তালিকা পড়া হচ্ছে…")
    try:
        sub, _t = _list_files(client, org_uuid, dash_from, dash_till, workers, cancel, lambda a, b: None, statuses=[SUBMITTED])
        par, _t = _list_files(client, org_uuid, dash_from, dash_till, workers, cancel, lambda a, b: None, statuses=[PARTIAL])
        d.dash.update(ok=True, submitted={fid: it.get("application_id") or str(fid) for fid, it in sub.items()},
                      partial={fid: it.get("application_id") or str(fid) for fid, it in par.items()})
        for fid, it in list(sub.items()) + list(par.items()):
            items.setdefault(fid, it)
    except (AuthError, Cancelled):
        raise
    except Exception as exc:                              # noqa: BLE001 - the report still works without the cross-check
        d.notes.append(f"সতর্কতা: ড্যাশবোর্ডের Submitted তালিকা পড়া যায়নি ({exc}); ড্যাশবোর্ডের সঙ্গে মেলানো যায়নি।")
    progress("list", 1, 1, f"ড্যাশবোর্ডে Submitted: {len(d.dash['submitted'])} টি ফাইল ({dash_from:%d-%m-%Y} – {dash_till:%d-%m-%Y})")

    def fetch(fid):
        return client.get(f"/api/v2/manager/applications/{fid}")

    def detail_progress(label):
        return lambda a, b: progress("detail", a, b, f"{label} {a}/{b}")

    details, errors = _pool_map(workers, cancel, fetch, list(items), detail_progress("ফাইল সংগ্রহ"))
    for fid in list(errors):                              # one calm second try for failures
        try:
            details[fid] = fetch(fid)
            del errors[fid]
        except (AuthError, Cancelled):
            raise
        except Exception as exc:                          # noqa: BLE001
            errors[fid] = str(exc)

    # 3. Re-CPV tracker (last year) --------------------------------------------------
    progress("recpv", 0, 1, "Re-CPV তালিকা (গত ১ বছর) সংগ্রহ হচ্ছে…")
    try:
        tracks = fetch_tracker(client, org_uuid, hist_from, d.w_till)
    except (AuthError, Cancelled):
        raise
    except Exception as exc:                              # noqa: BLE001
        raise ApiError(f"Re-CPV তালিকা পড়া যায়নি, তাই রিপোর্ট ভুল হতো। কারণ: {exc}") from None
    d.tracker_total = len(tracks)
    recpv_by_trip, recpv_by_file = index(tracks)
    progress("recpv", 1, 1, f"Re-CPV: {len(tracks)} টি (গত ১ বছর)")

    # 4. older files with new events inside the window -------------------------------
    need: dict[int, str] = {}
    for tr in tracks:
        ca = tr["created_at"]
        if ca and d.w_from <= ca.date() <= d.w_till and tr["app_id"] and tr["app_id"] not in items:
            need[int(tr["app_id"])] = "recpv"
    if cfg.find_old_extras and details:
        progress("old", 0, 1, "পুরনো ফাইলের Extra ট্রিপ খোঁজা হচ্ছে…")
        ids = [t["id"] for det in details.values()
               for c in (det.get("application", det).get("concerns") or []) for t in (c.get("trips") or [])
               if t.get("id")]
        if ids:
            threshold = min(ids) - TRIP_ID_MARGIN
            try:
                old_items, _tot = _list_files(client, org_uuid, hist_from, d.w_from - timedelta(days=1), workers,
                                              cancel, lambda a, b: progress("old", a, b, f"পুরনো ফাইলের তালিকা: পেজ {a}/{b}"))
            except (AuthError, Cancelled):
                raise
            except Exception as exc:                      # noqa: BLE001
                old_items = {}
                d.notes.append(f"সতর্কতা: পুরনো ফাইলের Extra ট্রিপ খোঁজা যায়নি ({exc})।")
            for fid, it in old_items.items():
                if fid in items or fid in need:
                    continue
                if any((t.get("id") or 0) >= threshold for t in it.get("trips") or []):
                    need[fid] = "extra"
    old_ids = [i for i in need if i not in details]
    if old_ids:
        o_details, o_errors = _pool_map(workers, cancel, fetch, old_ids, detail_progress("পুরনো ফাইল"))
        details.update(o_details)
        errors.update(o_errors)
        for fid in o_errors:
            items.setdefault(fid, {"id": fid, "application_id": str(fid)})
    d.old_files = len([i for i in old_ids if i in details])

    # normalise ---------------------------------------------------------------------
    files: dict[int, dict] = {}
    for fid, det in details.items():
        try:
            files[fid] = normalize_file(items.get(fid, {"id": fid}), det, {})
        except Exception as exc:                          # noqa: BLE001
            errors[fid] = f"ডেটা পড়তে সমস্যা: {exc}"
    for fid, msg in errors.items():
        if fid not in files:
            d.failed.append({"id": fid, "file_no": (items.get(fid) or {}).get("application_id", ""), "reason": msg})
    d.files = sorted(files.values(), key=lambda f: f["file_no"])
    if d.failed:
        d.notes.append(f"{len(d.failed)} টি ফাইল পড়া যায়নি (Failed Files শিটে)।")

    # 5. activity logs ---------------------------------------------------------------
    want = [fid for fid, f in files.items() if f["status_code"] in LOG_STATUSES]

    def fetch_log(fid):
        return parse_logs(client.get("/api/v2/applications/activity-logs", [("application_id", fid)]))

    progress("log", 0, max(len(want), 1), f"অ্যাক্টিভিটি লগ (সাবমিশন ও Last Update) 0/{len(want)}")
    logs, log_errs = _pool_map(workers, cancel, fetch_log, want,
                               lambda a, b: progress("log", a, b, f"অ্যাক্টিভিটি লগ (সাবমিশন ও Last Update) {a}/{b}"))
    d.log_failed = len(log_errs)
    if log_errs:
        d.notes.append(f"{len(log_errs)} টি ফাইলের অ্যাক্টিভিটি লগ পড়া যায়নি; সেগুলো Incomplete ধরা হয়েছে।")

    # 6. rows -------------------------------------------------------------------------
    progress("rows", 0, 1, "সারি ও হিসাব তৈরি হচ্ছে…")
    d.holidays = holiday_map
    since = datetime.combine(d.w_till, datetime.min.time()) - timedelta(days=HISTORY_DAYS)
    rows: list[BillRow] = []
    for f in d.files:
        rows.extend(build_rows(f, recpv_by_trip, recpv_by_file, logs.get(f["id"]), since))
    report_date = d.report_date
    until = datetime.combine(d.report_date, PHASE1_CUTOFF) if (d.mode == "tracker" and d.slot == "3pm") else None
    later = apply_as_of(rows, d.w_till, until)             # submitted after the report moment (last day / 3 PM) = still waiting then
    d.rolled = assign_sub_days(rows, d.w_till, hset)       # Fri / Sat / holiday submissions are reported on the next working day
    for r in rows:
        compute_tat(r, report_date, hset)
    fill_history(rows)
    d.all_rows = rows
    d.complete, d.incomplete = select_rows(rows, d.mode, d.report_date, d.w_from, d.w_till, hset, d.incomplete_scope,
                                           today=today, after3_only=d.after3_only)
    for r in d.complete:
        if r.rolled:
            r.info.append(f"আসল সাবমিশন {r.submitted_at:%a %d/%m/%Y %I:%M %p} (ছুটির দিন); ট্র্যাকারে পরের কর্মদিবস {r.sub_day:%d/%m/%Y}-এ দেখানো হয়েছে")
    d.recon = reconcile(rows, d.files)
    d.recon["submitted_later"] = later
    if d.dash.get("ok"):
        d.dash["check"] = dashboard_check(d)
        ck = d.dash["check"]
        if ck["missing"]:
            d.notes.append(f"ড্যাশবোর্ডের Submitted তালিকায় {ck['dashboard']} টি ফাইল, রিপোর্টের Complete-এ মিলেছে {ck['matched']} টি। "
                           "মেলেনি: " + "; ".join(f"{no} ({why})" for no, why in ck["missing"][:6]) + ("…" if len(ck["missing"]) > 6 else ""))
    nroll = sum(1 for r in d.complete if r.rolled)
    if nroll:
        d.notes.append(f"{nroll} টি সারি ছুটির দিনে (শুক্র/শনি/ছুটি) Submitted হয়েছিল; ট্র্যাকারের নিয়মে সেগুলো পরের কর্মদিবসের তারিখে দেখানো ও TAT গোনা হয়েছে।")
    if d.mode == "tracker":
        d.notes.append(f"Incomplete তালিকা: {SCOPE_TEXT[d.incomplete_scope]}।")
    if hol.needs_update(today):
        d.notes.append(f"ছুটির তালিকা {hol.last_date():%d-%m-%Y} পর্যন্ত আছে; নতুন ছুটি যোগ করুন।")
    progress("rows", 1, 1, "সম্পন্ন।")
    return d
