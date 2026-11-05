"""File History (read-only): the bank / Barikoi gives a list of file numbers (full number or only the
last digits) in an Excel / CSV sheet and gets the complete end-to-end history of every file.

Search rules (agreed with the user)
  * No time limit. A bare number such as 441930 or 35932 is a SUFFIX of the digits of the file number,
    exactly as given (no zero padding).  Every file whose number ends with those digits is returned.
  * A full file number (CC-20261029061512999) carries its creation date, so only that date +-1 day is
    searched (+-10 days if it is not there).
  * Suffix searches need every file of the organisation: the whole list is read once, month by month, from
    the oldest file to today.  The file numbers + dates are remembered in a small local index
    (~/.verify_report_builder/file_index.json, no personal data) so the next run only reads the new days.
  * Nothing found  -> a row with 'File not found'.   Several files with the same ending -> all are shown and flagged.
  * Strictly read-only: only the already allowed GET paths are used.
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config, holidays as hol
from .activity import parse_logs
from .billing import BASE_TYPE, BillRow, FileLogs, build_rows, compute_tat, concern_info, file_type_of, fill_history
from .client import ApiError, AuthError, Cancelled, ReadOnlyClient
from .collect import Progress, RunConfig, _noop
from .collect_prime import _list_files, _pool_map
from .model import normalize_file
from .summary import TripView, analyze
from .recpv import fetch_tracker, index as recpv_index

INDEX_NAME = "file_index.json"
MAX_MATCHES = 20            # a very short ending (e.g. 3 digits) could match hundreds of files: show the newest 20
NARROW_DAYS = 1             # full file number: date +- 1 day ...
WIDE_DAYS = 10              # ... and, if not found, date +- 10 days
EARLIEST_FALLBACK = date(2023, 1, 1)
HISTORY_SINCE = datetime(2000, 1, 1)

_FULL_RE = re.compile(r"^([A-Za-z]{2,3})[-\s_]*(\d{8,})$")
_BARE_RE = re.compile(r"^(?:[A-Za-z]{2,3}[-\s_]+)?(\d+)(?:\.0+)?$")
_HEADER_STRONG = re.compile(r"tracking|file\s*(no|num)|application|app\.?\s*id|ফাইল|ট্রাকিং", re.I)
_HEADER_WEAK = re.compile(r"number|\bno\b|\bid\b|ref|digit|নম্বর|সংখ্যা", re.I)
_HEADER_SERIAL = re.compile(r"^\s*(?:s\.?\s*l\.?(?:\s*no\.?)?|sr\.?(?:\s*no\.?)?|serial(?:\s*(?:no|number)\.?)?|#|ক্রম|ক্র\.?\s*নং)\s*$", re.I)


# =============================================================================== input
@dataclass
class IdEntry:
    raw: str                   # what is shown in the report ("Searched" column)
    kind: str                  # "full" | "suffix"
    key: str                   # full: PREFIX+digits (upper case) | suffix: digits
    digits: str
    prefix: str = ""
    day: date | None = None    # full numbers: the creation date written inside the number

    @property
    def uid(self) -> str:
        return f"{self.kind}:{self.key}"


def _day_from(digits: str) -> date | None:
    try:
        y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
        if 2015 <= y <= 2100:
            return date(y, m, d)
    except ValueError:
        pass
    return None


def make_entry(value) -> IdEntry | None:
    """One cell / token -> IdEntry (None when it does not look like a file number)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float):
        if value != value or not value.is_integer():
            return None
        value = int(value)
    if isinstance(value, int):
        s = str(value)
    elif isinstance(value, str):
        s = value.replace("​", "").strip().strip("'\"`").strip()
    else:
        return None
    m = _FULL_RE.match(s)
    if m:
        prefix, digits = m.group(1).upper(), m.group(2)
        return IdEntry(raw=f"{prefix}-{digits}", kind="full", key=prefix + digits, digits=digits, prefix=prefix,
                       day=_day_from(digits))
    m = _BARE_RE.match(s)
    if m:
        digits = m.group(1)
        return IdEntry(raw=digits, kind="suffix", key=digits, digits=digits)
    return None


def _dedupe(entries) -> list[IdEntry]:
    seen, out = set(), []
    for e in entries:
        if e is not None and e.uid not in seen:
            seen.add(e.uid)
            out.append(e)
    return out


def parse_ids_text(text: str) -> list[IdEntry]:
    """Pasted text: numbers separated by new lines, spaces, commas or semicolons."""
    return _dedupe(make_entry(tok) for tok in re.split(r"[\s,;|]+", text or "") if tok)


def _is_serial(ents: list) -> bool:
    """1, 2, 3 ... n  (a row-number column, never file numbers)."""
    nums = [int(e.digits) for e in ents if e is not None and e.kind == "suffix" and len(e.digits) <= 6]
    return len(nums) >= 3 and len(nums) == sum(1 for e in ents if e is not None) and nums == list(range(nums[0], nums[0] + len(nums))) and nums[0] in (0, 1)


def _pick_column(rows: list[list]) -> tuple[int | None, int]:
    """-> (column index or None, score).  Header words such as 'Tracking No.' win; otherwise the column
    with the most number-like values.  A 1, 2, 3 ... serial column is never taken."""
    width = max((len(r) for r in rows), default=0)
    best, best_score = None, 0.0
    for c in range(width):
        vals = [r[c] for r in rows if c < len(r)]
        ents = [make_entry(v) for v in vals]
        n = sum(1 for e in ents if e is not None)
        if n == 0:
            continue
        head = next((str(v) for v in vals[:6] if isinstance(v, str) and v.strip() and make_entry(v) is None), "")
        if _HEADER_SERIAL.search(head) or _is_serial(ents):
            continue
        score = n + 0.001 * sum(len(e.digits) for e in ents if e)
        if _HEADER_STRONG.search(head):
            score += 10000
        elif _HEADER_WEAK.search(head):
            score += 5000
        if score > best_score:
            best, best_score = c, score
    return best, best_score


def _entries_from_rows(rows: list[list]) -> tuple[list[IdEntry], float]:
    col, score = _pick_column(rows)
    if col is None:
        return [], 0.0
    return _dedupe(make_entry(r[col]) for r in rows if col < len(r)), score


def parse_ids_file(path) -> list[IdEntry]:
    """Excel (.xlsx) / CSV / text file -> ordered, de-duplicated list of file numbers."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        try:
            wb = load_workbook(str(p), read_only=True, data_only=True)
        except Exception as exc:                                  # noqa: BLE001
            raise ValueError(f"Excel ফাইলটি পড়া যায়নি: {exc}") from None
        best: list[IdEntry] = []
        best_score = 0.0
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            ents, score = _entries_from_rows(rows)
            if ents and score > best_score:
                best, best_score = ents, score
        wb.close()
        return best
    if ext == ".xls":
        raise ValueError("পুরনো .xls ফাইল পড়া যায় না। Excel-এ খুলে ‘Save As → .xlsx’ করে দিন।")
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    if ext == ".txt":
        return parse_ids_text(text)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    return _entries_from_rows(rows)[0]


# =============================================================================== local index
def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def default_index_path() -> Path:
    return config.SETTINGS_DIR / INDEX_NAME


class FileIndex:
    """file internal id -> [file no, start date]; plus how far the whole list has been read."""

    def __init__(self, path: Path, key: str):
        self.path, self.key = Path(path), key
        self.files: dict[str, list] = {}
        self.swept_from: date | None = None
        self.swept_until: date | None = None

    @classmethod
    def load(cls, path: Path, key: str) -> "FileIndex":
        idx = cls(path, key)
        try:
            block = (json.loads(Path(path).read_text(encoding="utf-8")).get("servers") or {}).get(key) or {}
            files = block.get("files") or {}
            if isinstance(files, dict):
                idx.files = {str(k): [str(v[0]), str(v[1])] for k, v in files.items() if isinstance(v, list) and len(v) >= 2}
            idx.swept_from = date.fromisoformat(block["swept_from"]) if block.get("swept_from") else None
            idx.swept_until = date.fromisoformat(block["swept_until"]) if block.get("swept_until") else None
            if not idx.files:
                idx.swept_from = idx.swept_until = None
        except Exception:                                         # noqa: BLE001 - missing / corrupt cache = start fresh
            idx.files, idx.swept_from, idx.swept_until = {}, None, None
        return idx

    def reset(self) -> None:
        self.files, self.swept_from, self.swept_until = {}, None, None

    def add(self, item: dict) -> None:
        fid = item.get("id")
        if fid is None:
            return
        self.files[str(fid)] = [str(item.get("application_id") or ""), str(item.get("start_date") or "")[:10]]

    def save(self) -> None:
        try:
            try:
                whole = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(whole, dict):
                    whole = {}
            except Exception:                                     # noqa: BLE001
                whole = {}
            servers = whole.setdefault("servers", {})
            servers[self.key] = {"swept_from": self.swept_from.isoformat() if self.swept_from else None,
                                 "swept_until": self.swept_until.isoformat() if self.swept_until else None,
                                 "files": self.files}
            whole["version"] = 1
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(whole, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass                                                  # a cache that cannot be written is only slower

    def table(self) -> list[tuple]:
        return [(int(fid), no, sd, _norm(no), _digits(no)) for fid, (no, sd) in self.files.items()]


def match_entry(table: list[tuple], e: IdEntry) -> list[tuple]:
    """-> [(file id, file no, start date)] newest first."""
    out = []
    for fid, no, sd, nn, dg in table:
        ok = (nn == e.key) if e.kind == "full" else dg.endswith(e.digits)
        if ok:
            out.append((fid, no, sd))
    out.sort(key=lambda x: (x[2], x[0]), reverse=True)
    return out


# =============================================================================== config / data
@dataclass
class HistoryConfig(RunConfig):
    ids: list = field(default_factory=list)            # IdEntry or str / int (no time limit)
    refresh_index: bool = False                        # ignore the remembered index and read everything again
    index_path: Path | None = None                     # tests use their own file
    max_matches: int = MAX_MATCHES
    today: date | None = None                          # tests pin the day; normally the laptop's date


@dataclass
class FileData:
    file: dict
    logs: FileLogs | None = None
    rows: list = field(default_factory=list)           # BillRow
    recpv_by_trip: dict = field(default_factory=dict)  # trip id -> Re-CPV tracker entry
    recpv_events: list = field(default_factory=list)   # Re-CPV tracker entries of this file number
    error: str = ""

    @property
    def file_no(self) -> str:
        return self.file.get("file_no", "")


@dataclass
class Match:
    """One searched number -> one file (or nothing)."""
    entry: IdEntry
    file_id: int | None = None
    found: bool = False
    note: str = ""


@dataclass
class HistoryData:
    entries: list = field(default_factory=list)
    matches: list = field(default_factory=list)        # Match, in the order of the input
    files: dict = field(default_factory=dict)          # file id -> FileData
    not_found: list = field(default_factory=list)      # IdEntry
    notes: list = field(default_factory=list)
    generated_at: datetime | None = None
    server_label: str = ""
    org_name: str = ""
    index_info: dict = field(default_factory=dict)

    @property
    def results(self) -> list:
        """Every matched file once, in the order of first appearance."""
        seen, out = set(), []
        for m in self.matches:
            if m.found and m.file_id not in seen and m.file_id in self.files:
                seen.add(m.file_id)
                out.append(self.files[m.file_id])
        return out


# =============================================================================== search
def _month_windows(start: date, end: date) -> list[tuple[date, date]]:
    out, cur = [], start
    while cur <= end:
        nxt = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
        out.append((cur, min(end, nxt - timedelta(days=1))))
        cur = nxt
    return out


def _earliest(client, org_uuid: str, today: date) -> date | None:
    """Oldest file of the organisation: first page of the oldest-first list + last page of the newest-first
    list (so it is right even if the server ignores the sort order)."""
    def page(order: str, n: int):
        params = [("dateFrom", "2015-01-01"), ("dateTill", today.isoformat()), ("page", n), ("sort_by", "start_date"),
                  ("sort_order", order), ("org_id[]", org_uuid)] + [("status[]", s) for s in config.ALL_FILE_STATUS_CODES]
        return client.get("/api/v2/manager/applications", params)["applications"]

    found: list[date] = []

    def take(block):
        for it in block.get("data") or []:
            try:
                found.append(date.fromisoformat(str(it.get("start_date") or "")[:10]))
            except ValueError:
                pass
            d = _day_from(_digits(it.get("application_id") or ""))
            if d:
                found.append(d)

    try:
        first = page("ASC", 1)
    except ApiError:
        return EARLIEST_FALLBACK
    if int(first.get("total") or 0) == 0:
        return None
    take(first)
    last = int(first.get("last_page") or 1)
    if last > 1:
        try:
            take(page("DESC", last))
        except ApiError:
            pass
    return min(found) if found else EARLIEST_FALLBACK


def _sweep(client, org_uuid: str, idx: FileIndex, workers: int, cancel, progress: Progress, notes: list, today: date) -> bool:
    """Read the whole file list (or only the days since the last run) into the index."""
    incremental = bool(idx.swept_from and idx.swept_until)
    if incremental:
        start = idx.swept_until - timedelta(days=2)
    else:
        earliest = _earliest(client, org_uuid, today)
        if earliest is None:
            idx.swept_from = idx.swept_until = today
            return True
        start = date(earliest.year, earliest.month, 1)
    windows = _month_windows(start, today)
    ok_all = True
    for i, (a, b) in enumerate(windows, 1):
        if cancel.is_set():
            raise Cancelled()
        progress("list", i - 1, len(windows), f"ফাইল তালিকা পড়া হচ্ছে: {a:%b %Y} ({i}/{len(windows)})")
        got = None
        for _try in range(2):
            try:
                got, _total = _list_files(client, org_uuid, a, b, workers, cancel, lambda *_a: None)
                break
            except (AuthError, Cancelled):
                raise
            except Exception:                                      # noqa: BLE001
                got = None
        if got is None:
            ok_all = False
            notes.append(f"সতর্কতা: {a:%d-%m-%Y} – {b:%d-%m-%Y} এর ফাইল তালিকা পড়া যায়নি; ফলাফল অসম্পূর্ণ হতে পারে।")
            continue
        for it in got.values():
            idx.add(it)
    progress("list", len(windows), len(windows), "ফাইল তালিকা পড়া শেষ।")
    if ok_all:
        idx.swept_from = idx.swept_from if incremental else start
        idx.swept_until = today
    return ok_all


def _narrow(client, org_uuid: str, idx: FileIndex, e: IdEntry, workers: int, cancel) -> None:
    """Full file number: look only around the date written in the number."""
    for span in (NARROW_DAYS, WIDE_DAYS):
        got, _t = _list_files(client, org_uuid, e.day - timedelta(days=span), e.day + timedelta(days=span),
                              workers, cancel, lambda *_a: None)
        for it in got.values():
            idx.add(it)
        if match_entry(idx.table(), e):
            return


def _login(client, cfg: RunConfig, progress: Progress) -> str:
    progress("login", 0, 1, "লগইন হচ্ছে…")
    client.login(cfg.email, cfg.password)
    user = client.get("/api/v2/auth/user").get("data", {})
    orgs = user.get("organizations") or []
    match = [o for o in orgs if (o.get("name") or "").strip().lower() == cfg.org_name.strip().lower()]
    if not match:
        names = ", ".join(o.get("name", "?") for o in orgs) or "কোনোটিই নয়"
        raise ApiError(f"“{cfg.org_name}” নামে কোনো সংস্থা পাওয়া যায়নি। আপনার অ্যাকাউন্টে আছে: {names}")
    progress("login", 1, 1, "লগইন সম্পন্ন।")
    return match[0]["uuid"]


def _blank_file(fid: int, file_no: str, start: str) -> dict:
    try:
        sd = datetime.strptime(start[:10], "%Y-%m-%d") if start else None
    except ValueError:
        sd = None
    return {"id": fid, "file_no": file_no, "type": "", "status_code": None, "status": "", "start_date": sd,
            "created_at": sd, "sla": None, "station": "", "org": "", "assigned_by": "", "concerns": []}


# =============================================================================== main
def collect_history(cfg: HistoryConfig, progress: Progress = _noop, cancel: threading.Event | None = None) -> HistoryData:
    cancel = cancel or threading.Event()
    entries = _dedupe(e if isinstance(e, IdEntry) else make_entry(e) for e in cfg.ids)
    if not entries:
        raise ApiError("কোনো ফাইল নম্বর পাওয়া যায়নি। Excel/CSV-এ ফাইল নম্বর বা শেষ কয়েকটি অঙ্ক দিন।")
    workers = max(1, min(int(cfg.workers), config.MAX_WORKERS))
    client = ReadOnlyClient(cfg.web, cfg.api, cancel=cancel)
    now = datetime.now()
    today = cfg.today or now.date()
    h = HistoryData(entries=entries, generated_at=now, server_label=cfg.server_label, org_name=cfg.org_name)

    org_uuid = _login(client, cfg, progress)

    # 1. find the files -------------------------------------------------------------
    idx = FileIndex.load(cfg.index_path or default_index_path(), f"{cfg.web.rstrip('/')}|{org_uuid}")
    if cfg.refresh_index:
        idx.reset()
    from_cache = bool(idx.swept_until)
    swept_now = False
    if any(e.kind == "suffix" for e in entries):
        swept_now = _sweep(client, org_uuid, idx, workers, cancel, progress, h.notes, today)
    for i, e in enumerate(entries, 1):
        if e.kind == "full" and e.day and not swept_now and not match_entry(idx.table(), e):
            progress("list", i, len(entries), f"ফাইল খোঁজা হচ্ছে: {e.raw}")
            try:
                _narrow(client, org_uuid, idx, e, workers, cancel)
            except (AuthError, Cancelled):
                raise
            except Exception as exc:                               # noqa: BLE001
                h.notes.append(f"{e.raw}: খোঁজা যায়নি ({exc})")
    idx.save()
    h.index_info = {"files": len(idx.files), "swept_from": idx.swept_from, "swept_until": idx.swept_until,
                    "from_cache": from_cache}
    table = idx.table()

    hits: dict[str, list] = {}
    for e in entries:
        found = match_entry(table, e)
        cap = max(1, int(cfg.max_matches))
        hits[e.uid] = (found[:cap], len(found) > cap)

    # 2. details of every matched file (once) -----------------------------------------
    need = {fid: (no, sd) for (found, _c) in hits.values() for fid, no, sd in found}
    items = {fid: {"id": fid, "application_id": no, "start_date": sd} for fid, (no, sd) in need.items()}

    def fetch(fid):
        return client.get(f"/api/v2/manager/applications/{fid}")

    details, errors = _pool_map(workers, cancel, fetch, list(need),
                                lambda a, b: progress("detail", a, b, f"ফাইল সংগ্রহ {a}/{b}"))
    for fid in list(errors):                                       # one calm second try
        try:
            details[fid] = fetch(fid)
            del errors[fid]
        except (AuthError, Cancelled):
            raise
        except Exception as exc:                                   # noqa: BLE001
            errors[fid] = str(exc)
    files: dict[int, dict] = {}
    for fid, det in details.items():
        try:
            files[fid] = normalize_file(items[fid], det, {})
        except Exception as exc:                                   # noqa: BLE001
            errors[fid] = f"ডেটা পড়তে সমস্যা: {exc}"
    for fid, msg in errors.items():
        if fid not in files:
            files[fid] = _blank_file(fid, need[fid][0], need[fid][1])
            h.files[fid] = FileData(file=files[fid], error=msg)
            h.notes.append(f"{need[fid][0]}: ফাইল পড়া যায়নি ({msg})")

    # 3. Re-CPV tracker (one call, from the oldest matched file) -------------------------
    recpv_by_trip, recpv_by_file = {}, {}
    ok_files = [f for fid, f in files.items() if fid not in h.files]
    if ok_files:
        progress("recpv", 0, 1, "Re-CPV তালিকা সংগ্রহ হচ্ছে…")
        oldest = min((f["start_date"].date() for f in ok_files if f.get("start_date")), default=today)
        try:
            tracks = fetch_tracker(client, org_uuid, oldest - timedelta(days=1), today)
            recpv_by_trip, recpv_by_file = recpv_index(tracks)
        except (AuthError, Cancelled):
            raise
        except Exception as exc:                                   # noqa: BLE001
            h.notes.append(f"Re-CPV তালিকা পড়া যায়নি; Re-CPV/Extra চিহ্ন অসম্পূর্ণ হতে পারে ({exc})")
        progress("recpv", 1, 1, "Re-CPV তালিকা সংগ্রহ হয়েছে।")

    # 4. activity logs ----------------------------------------------------------------
    want = [fid for fid in files if fid not in h.files]

    def fetch_log(fid):
        return parse_logs(client.get("/api/v2/applications/activity-logs", [("application_id", fid)]))

    progress("log", 0, max(len(want), 1), f"অ্যাক্টিভিটি লগ 0/{len(want)}")
    logs, log_errs = _pool_map(workers, cancel, fetch_log, want,
                               lambda a, b: progress("log", a, b, f"অ্যাক্টিভিটি লগ {a}/{b}"))
    if log_errs:
        h.notes.append(f"{len(log_errs)} টি ফাইলের অ্যাক্টিভিটি লগ পড়া যায়নি।")

    # 5. billing rows (history, area, SLA) ------------------------------------------------
    progress("rows", 0, 1, "ইতিহাস তৈরি হচ্ছে…")
    hset = set(hol.load())
    for fid in want:
        f = files[fid]
        fd = FileData(file=f, logs=logs.get(fid))
        fd.recpv_by_trip = {t["id"]: recpv_by_trip[t["id"]] for c in f["concerns"] for t in c["trips"] if t["id"] in recpv_by_trip}
        fd.recpv_events = list(recpv_by_file.get((f["file_no"] or "").strip().upper(), []))
        try:
            fd.rows = build_rows(f, recpv_by_trip, recpv_by_file, fd.logs, HISTORY_SINCE)
            for r in fd.rows:
                compute_tat(r, today, hset)
            fill_history(fd.rows)
        except Exception as exc:                                   # noqa: BLE001
            fd.rows = []
            h.notes.append(f"{f['file_no']}: বিলের ইতিহাস তৈরি করা যায়নি ({exc})")
        h.files[fid] = fd

    # 6. one Match per searched number x file ------------------------------------------------
    for e in entries:
        found, capped = hits[e.uid]
        if not found:
            if e.kind == "full" and e.day and not swept_now:
                why = f"searched only {e.day - timedelta(days=WIDE_DAYS):%d-%m-%Y} to {e.day + timedelta(days=WIDE_DAYS):%d-%m-%Y}, the dates around the number"
            else:
                why = f"searched all files up to {idx.swept_until:%d-%m-%Y}" if idx.swept_until else "searched"
            h.matches.append(Match(e, None, False, f"File not found ({why})"))
            h.not_found.append(e)
            continue
        multi = len(found) > 1 or capped
        for fid, no, _sd in found:
            note = ""
            if multi:
                note = (f"Multiple files end with {e.digits}" if e.kind == "suffix" else f"Multiple files match {e.raw}")
                if capped:
                    note += f" (showing the newest {len(found)})"
            h.matches.append(Match(e, fid, True, note))
    progress("rows", 1, 1, "সম্পন্ন।")
    if cancel.is_set():
        raise Cancelled()
    return h


# =============================================================================== what the report shows
SUBMIT_RE = re.compile(r"^file\s+(partially\s+|partial\s+)?submitted$", re.I)


def trip_label(t: dict) -> str:
    return BASE_TYPE.get(t.get("type_code", ""), t.get("type") or "Trip")


def timeline(fd: FileData) -> list[dict]:
    """Every activity-log event of the file, newest first."""
    if fd.logs is None or not fd.logs.ok:
        return []
    labels = {t["id"]: trip_label(t) for c in fd.file["concerns"] for t in c["trips"]}
    out = []
    for e in fd.logs.events:                                   # already newest first
        trip = e.etype == "TRIP" and e.entity_id is not None
        out.append({"when": e.when, "scope": "Trip" if trip else "File", "trip_id": e.entity_id if trip else None,
                    "trip_type": labels.get(e.entity_id, "") if trip else "", "text": e.text, "user": e.user})
    return out


def _views_at(f: dict, logs: FileLogs | None, when: datetime) -> list:
    """The trips of the file as they stood at `when` (created by then; finished only if the log says so)."""
    info = concern_info(f)
    views = []
    for c in f["concerns"]:
        for t in c["trips"]:
            ca = t.get("created_at")
            if ca and ca > when:
                continue
            t2 = dict(t)
            if t.get("status_code") == 5:
                done_at = (logs.trip_finished.get(t["id"]) if logs else None) or t.get("end_time") or ca
                if done_at and done_at > when:
                    t2["status_code"], t2["status"] = 2, "Allocated"
            views.append(TripView(t2, c["role"].upper(), info[c["id"]]["who"]))
    return views


def submission_history(fd: FileData) -> list[dict]:
    """Each Submitted / Partially Submitted event with the Done / Due line as it was at that moment
    (rebuilt from the dashboard events, newest first):  '2026-09-08 Done-PG. Due-App (...)'."""
    if fd.logs is None or not fd.logs.ok:
        return []
    out = []
    for e in fd.logs.events:
        if e.etype != "APPLICATION" or not SUBMIT_RE.match(e.text.strip()):
            continue
        partial = "partial" in e.text.lower()
        try:
            s = analyze(_views_at(fd.file, fd.logs, e.when), False, "BS")
            done, due = s.done, s.due
            if due == "Report not yet submitted":
                due = "0"
        except Exception:                                      # noqa: BLE001 - the summary engine must never stop a history
            done = due = "?"
        out.append({"when": e.when, "event": "Partially Submitted" if partial else "Submitted", "user": e.user,
                    "done": done, "due": due, "line": f"{e.when:%Y-%m-%d} Done-{done}. Due-{due}"})
    return out


def overview(fd: FileData) -> dict:
    """Facts for the Summary sheet (plain values)."""
    f = fd.file
    rows = sorted(fd.rows, key=lambda r: r.history_pos)
    areas = list(dict.fromkeys(r.area for r in rows))
    appts = sum(len(r.appointments) for r in rows)
    if not rows:
        appts = sum(len(t.get("appointments") or []) for c in f["concerns"] for t in c["trips"])
    sla = []
    for i, r in enumerate(rows, 1):
        if r.tat is None:
            sla.append(f"{i}. TAT n/a")
            continue
        end = f"submitted {r.submitted_at:%d/%m/%Y}" if r.submitted and r.submitted_at else "running"
        verdict = f"SLA Breach (+{r.extra_tat})" if r.sla_breach else "Within SLA"
        sla.append(f"{i}. TAT {r.tat} / SLA {r.sla_days} · {verdict} · {end}")
    events = timeline(fd)
    last = [f"{e['when']:%d/%m/%Y %H:%M:%S} · {e['text']}" + (f" · {e['user']}" if e["user"] else "") for e in events[:5]]
    if len(events) > 5:
        last.append(f"(+{len(events) - 5} older events in Timeline)")
    return {
        "file_no": f["file_no"], "type": file_type_of(f["file_no"], f.get("type", "")), "status": f.get("status", ""),
        "created": f.get("start_date") or f.get("created_at"),
        "area": " / ".join(areas),                       # "Out" | "In" | "Out / In" (bill rows in history order)
        "bill_rows": rows[0].file_history if rows else [], "sla": sla, "last_update": last,
        "appointments": appts,
    }
