"""Billing rows: one row = one billable event (Package / Single / ReCpv / Extra).

Rules (agreed with the user)
  * Trips created on the file-creation date, in creation order: the first 5 = ONE Package
    (any trip type counts). The 6th, 7th, 8th ... same-day trips = separate single rows
    labelled Extra Trip 1, 2, 3 ... (billed In or Out by their own address).
  * Every trip created after the creation date is a single bill: in the Re-CPV tracker -> ReCpv,
    otherwise Extra Document / Extra Trip.
  * Inactive trips are billable; Canceled trips are marked light-blue (internal copy).
  * In = inside Dhaka city, Gazipur city or Narayanganj city (lat/long); everything else = Out.
  * Package is Out if ANY of its trips is Out; a single row is judged on its own trip.
  * SLA (working days from Receive Date): In = 2, Out = 4. Extra TAT = TAT - SLA (never below 0).
  * The number of trips never changes because of Re-CPV - Re-CPV only labels a trip.
  * Each row has its own Receive Date, Submission, TAT and Extra TAT.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from . import geo, holidays as hol
from .summary import Summary, TripView, analyze

PACKAGE_MAX = 5
CUTOFF_HOUR = 15          # "before / after 3 PM"
SLA_IN = 2                # working days allowed, In area (Dhaka / Gazipur / Narayanganj city)
SLA_OUT = 4               # working days allowed, Out area

BASE_TYPE = {
    "HOUSE": "House", "GUARANTOR_HOUSE": "House", "OFFICE": "Office", "GUARANTOR_OFFICE": "Office",
    "BANK": "BS", "DOCUMENT": "Document", "RENTAL": "Rental", "CAR_QUATATION": "Car Quotation",
    "PROPERTY": "Property", "DOC_SERVICE": "Document", "DOC_DRCHAMBER": "Chamber", "DOC_TUITION": "Tuition",
}
SLAB_DOC = "Single Document(Salary Certificate/Pay Slip/LOI/Signature) Verification"
SLAB_PG = "PG Verification(House+Office/Business+Signature)"


def slab_for(trip: dict, role: str) -> str:
    code = trip.get("type_code", "")
    if role == "GUARANTOR" or code in ("GUARANTOR_HOUSE", "GUARANTOR_OFFICE"):
        return SLAB_PG
    if code == "HOUSE":
        return "Single House"
    if code == "OFFICE":
        return "Single Office"
    if code == "BANK":
        return "BS"
    return SLAB_DOC


@dataclass
class FileLogs:
    """What the activity log tells us about one file (times already in Dhaka time)."""
    ok: bool = False
    created: datetime | None = None
    submitted: list = field(default_factory=list)     # ascending
    partial: list = field(default_factory=list)
    trip_finished: dict = field(default_factory=dict)
    events: list = field(default_factory=list)       # LogEvent, newest first


@dataclass
class LogEvent:
    when: datetime
    etype: str                # APPLICATION | TRIP | CONCERN
    entity_id: int | None
    text: str                 # short, human words ("Finished", "On Hold", "Allocated to X" ...)
    user: str = ""


@dataclass
class Event:
    """A Re-CPV or Extra trip of a file (history, last year)."""
    kind: str                 # "Re-CPV" | "Extra"
    trip_id: int
    at: datetime | None
    reason: str
    trip_type: str = ""


@dataclass
class BillRow:
    sl: int = 0
    file_id: int = 0
    file_no: str = ""
    file_type: str = ""
    kind: str = "Package"                 # Package | Single | ReCpv | Extra
    slab: str = ""
    category: str = ""                    # line 2 of Bill Slab (dashboard words)
    trips: list = field(default_factory=list)          # [(concern, trip)]
    concern_lines: list = field(default_factory=list)
    history_lines: list = field(default_factory=list)
    receive_dt: datetime | None = None
    area: str = "In"
    area_sure: bool = True
    area_why: str = ""
    submitted_at: datetime | None = None
    status: str = "Incomplete"
    status_note: str = ""
    summary: Summary = field(default_factory=Summary)
    flags: dict = field(default_factory=dict)          # column -> reason text (light-blue cells)
    tat: int | None = None
    extra_tat: int | None = None
    canceled: bool = False
    sla_days: int = 2
    sla_breach: bool = False
    bill_note: str = ""                                # "Out bill" / "In bill" (single-trip rows)
    file_history: list = field(default_factory=list)   # every billing event of this file, first to last
    history_pos: int = 0                               # index of this row inside file_history (0-based)
    last_file: tuple | None = None                     # (when, text, user) newest log entry of the file
    last_trips: list = field(default_factory=list)     # [(trip_id, type label, when, text, user)]
    appointments: list = field(default_factory=list)   # [dict] appointments of this row's trips
    info: list = field(default_factory=list)           # notes for the Check List only (no yellow)

    @property
    def submitted(self) -> bool:
        return self.status == "Submitted"


# ------------------------------------------------------------------------------ concerns
def file_type_of(file_no: str, fallback: str = "") -> str:
    up = (file_no or "").upper().lstrip()
    if up.startswith("PL"):
        return "Loan"
    if up.startswith("CC"):
        return "Card"
    return fallback


def concern_info(file: dict) -> dict:
    """concern id -> dict(no, label, who, role, name)."""
    order = {"APPLICANT": 0, "CO_APPLICANT": 1, "GUARANTOR": 2}
    cons = sorted(file["concerns"], key=lambda c: (order.get(c["role"].upper(), 3), c["id"] or 0))
    n_pg = sum(1 for c in cons if c["role"].upper() == "GUARANTOR")
    out, pg_i = {}, 0
    for i, c in enumerate(cons, 1):
        role = c["role"].upper()
        if role == "APPLICANT":
            label, who = "Applicant", "App"
        elif role == "CO_APPLICANT":
            label, who = "Co-Applicant", "Co-App"
        elif role == "GUARANTOR":
            pg_i += 1
            label, who = f"Guarantor {pg_i}", ("PG" if n_pg == 1 else f"PG{pg_i}")
        else:
            label, who = role.replace("_", " ").title(), "App"
        out[c["id"]] = {"no": i, "label": label, "who": who, "role": role, "name": c["name"]}
    return out


def concern_lines(file: dict, info: dict, trips: list | None) -> list[str]:
    """Numbered lines: '1. Applicant: NAME - House, Office'. trips=None -> names only (all concerns)."""
    lines = []
    only = {c["id"] for c, _t in trips} if trips is not None else None
    for c in sorted(file["concerns"], key=lambda c: info[c["id"]]["no"]):
        if only is not None and c["id"] not in only:
            continue
        ci = info[c["id"]]
        text = f'{ci["no"]}. {ci["label"]}: {c["name"]}'
        if trips is not None:
            kinds: list[str] = []
            for cc, t in trips:
                if cc["id"] == c["id"]:
                    kinds.append(BASE_TYPE.get(t.get("type_code", ""), t.get("type") or "Trip"))
            if kinds:
                counted = []
                for k in dict.fromkeys(kinds):
                    n = kinds.count(k)
                    counted.append(f"{k} x{n}" if n > 1 else k)
                text += " - " + ", ".join(counted)
        lines.append(text)
    return lines


# ------------------------------------------------------------------------------ events / history
def extra_category(trip: dict) -> str:
    code = trip.get("type_code", "")
    blob = f'{trip.get("comment") or ""} {trip.get("remarks") or ""}'.lower()
    if code == "BANK":
        return "Extra Document(BS)"
    if code in ("HOUSE", "OFFICE", "GUARANTOR_HOUSE", "GUARANTOR_OFFICE"):
        return "Extra Trip"
    if "loi" in blob:
        return "Extra Document(LOI)"
    return "Extra Document"


def history_for(file_no: str, file: dict, recpv_by_file: dict, row_trip_ids: set, since: datetime) -> list[str]:
    """Column 'Re-CPV / Extra Trip (ID)': last-year events of this file number, this row's own first."""
    events: list[Event] = []
    tracker_trip_ids: set = set()
    for tr in recpv_by_file.get((file_no or "").strip().upper(), []):
        for tid in tr["trip_ids"]:
            tracker_trip_ids.add(tid)
            events.append(Event("Re-CPV", tid, tr["created_at"], tr["reason"]))
    start = file.get("start_date")
    for c in file["concerns"]:
        for t in c["trips"]:
            if t["id"] in tracker_trip_ids:
                continue
            if t.get("created_at") and start and t["created_at"].date() > start.date():
                events.append(Event("Extra", t["id"], t["created_at"], (t.get("comment") or "").strip(),
                                    BASE_TYPE.get(t.get("type_code", ""), "")))
    events = [e for e in events if e.at is None or e.at >= since]
    if not events:
        return ["N/A"]
    events.sort(key=lambda e: (e.trip_id not in row_trip_ids, e.at or datetime.min, e.trip_id))
    out = []
    for e in events:
        when = f"{e.at:%d-%m-%Y %H:%M}" if e.at else "-"
        head = f"{e.kind} | {when} | Trip ID {e.trip_id}"
        if e.trip_type and e.kind == "Extra":
            head += f" ({e.trip_type})"
        if e.reason:
            head += f"\nReason: {e.reason}"
        out.append(head)
    return out


# ------------------------------------------------------------------------------ area
def row_area(trips: list) -> tuple[str, bool, str]:
    results = [(geo.trip_area(t),) for _c, t in trips]
    res = [r[0] for r in results]
    outs = [r for r in res if r[0] == "Out"]
    if outs:
        sure = any(r[1] for r in outs)
        why = next((r[2] for r in outs if r[1]), outs[0][2])
        return "Out", sure, why
    sure = all(r[1] for r in res) if res else False
    why = next((r[2] for r in res if not r[1]), res[0][2] if res else "")
    return "In", sure, why


# ------------------------------------------------------------------------------ appointments / last update
def _trip_label(t: dict) -> str:
    return BASE_TYPE.get(t.get("type_code", ""), t.get("type") or "Trip")


def appointments_for(trips: list) -> list[dict]:
    """Appointments of the trips of ONE row (oldest first) - straight from the dashboard."""
    out = []
    for _c, t in trips:
        for a in t.get("appointments") or []:
            out.append({"trip_id": t["id"], "trip_type": _trip_label(t), "time": a.get("time"),
                        "type": a.get("type") or "", "reason": a.get("reason") or "",
                        "created_at": a.get("created_at"), "active": a.get("active", True)})
    out.sort(key=lambda a: (a["created_at"] or datetime.min, a["trip_id"] or 0))
    return out


def last_update_for(logs: "FileLogs | None", trips: list, labels: dict | None = None) -> tuple:
    """Newest activity-log entry of the whole file, and of each trip of this row."""
    if logs is None or not logs.ok or not logs.events:
        return None, []
    labels = labels or {}
    ev = logs.events                                     # newest first
    newest = ev[0]
    what = newest.text
    if newest.etype == "TRIP" and newest.entity_id:
        what = f"Trip {newest.entity_id} ({labels.get(newest.entity_id, 'Trip')}) - {newest.text}"
    file_last = (newest.when, what, newest.user)
    rows = []
    for _c, t in trips:
        mine = next((e for e in ev if e.etype == "TRIP" and e.entity_id == t["id"]), None)
        if mine:
            rows.append((t["id"], _trip_label(t), mine.when, mine.text, mine.user))
        else:
            rows.append((t["id"], _trip_label(t), None, "", ""))
    return file_last, rows


def short_slab(slab: str) -> str:
    if slab == SLAB_DOC:
        return "Single Document"
    if slab == SLAB_PG:
        return "PG Verification"
    return slab


def fill_history(rows: list[BillRow]) -> None:
    """Every row of a file carries the same numbered history (first to last) of that file's bills."""
    by_file: dict = {}
    for r in rows:
        by_file.setdefault(r.file_id, []).append(r)
    for rs in by_file.values():
        rs.sort(key=lambda r: (r.receive_dt or datetime.max, r.trips[0][1]["id"] or 0))
        rs.sort(key=lambda r: {"Package": 0, "Single": 1, "ReCpv": 2, "Extra": 2}.get(r.kind, 3))
        # chronological by receive date, Package always first
        pkg = [r for r in rs if r.kind == "Package"]
        rest = sorted([r for r in rs if r.kind != "Package"],
                      key=lambda r: (r.receive_dt or datetime.max, r.trips[0][1]["id"] or 0))
        rs[:] = pkg + rest
        lines = []
        for i, r in enumerate(rs, 1):
            when = f" - {r.receive_dt:%d-%m-%Y}" if r.receive_dt else ""
            if r.kind == "Package":
                what = f"Package ({len(r.trips)} trip{'s' if len(r.trips) != 1 else ''})"
            elif r.kind == "Single":
                what = f"{r.category.replace('Created - ', '')} - {short_slab(r.slab)}"
            else:
                what = f"{r.category} - {short_slab(r.slab)}"
            lines.append(f"{i}. {what} - {r.area}{when}")
        for pos, r in enumerate(rs):
            r.file_history = lines
            r.history_pos = pos


# ------------------------------------------------------------------------------ building
def build_rows(file: dict, recpv_by_trip: dict, recpv_by_file: dict, logs: FileLogs | None,
               history_since: datetime) -> list[BillRow]:
    info = concern_info(file)
    flat = []
    for c in file["concerns"]:
        for t in c["trips"]:
            flat.append((c, t))
    if not flat:
        return []
    far = datetime(2100, 1, 1)
    flat.sort(key=lambda ct: (ct[1].get("created_at") or far, ct[1]["id"] or 0))
    created = file.get("start_date") or file.get("created_at")
    cdate = created.date() if created else None
    same_day, later = [], []
    for c, t in flat:
        ca = t.get("created_at")
        if cdate is None or ca is None or ca.date() <= cdate:
            same_day.append((c, t))
        else:
            later.append((c, t))
    groups: list[tuple[str, list]] = []
    if same_day:
        groups.append(("Package", same_day[:PACKAGE_MAX]))
        groups += [("Single", [ct]) for ct in same_day[PACKAGE_MAX:]]      # 6th, 7th, 8th ... = Extra Trip 1, 2, 3 ...
    for ct in later:
        t = ct[1]
        kind = "ReCpv" if (t["id"] in recpv_by_trip or t.get("re_cpv")) else "Extra"
        groups.append((kind, [ct]))

    rows: list[BillRow] = []
    ftype = file_type_of(file["file_no"], file.get("type", ""))
    total_rows = len(groups)
    single_no = 0
    labels = {t["id"]: _trip_label(t) for _c, t in flat}
    for kind, trips in groups:
        r = BillRow(file_id=file["id"], file_no=file["file_no"], file_type=ftype, kind=kind, trips=trips)
        t0 = trips[0][1]
        if kind == "Package":
            r.slab = "Package"
            r.category = "Created" + (f" ({len(trips)} trips)" if len(trips) else "")
            r.receive_dt = created or t0.get("created_at")
            r.concern_lines = concern_lines(file, info, trips)
            # all concerns of the file are shown, even those without a trip in this package
            shown = {c["id"] for c, _ in trips}
            for c in sorted(file["concerns"], key=lambda c: info[c["id"]]["no"]):
                if c["id"] not in shown:
                    ci = info[c["id"]]
                    r.concern_lines.append(f'{ci["no"]}. {ci["label"]}: {c["name"]}')
            r.concern_lines.sort(key=lambda s: int(re.match(r"(\d+)\.", s).group(1)))
        else:
            r.slab = slab_for(t0, trips[0][0]["role"].upper())
            if kind == "Single":
                single_no += 1
                r.category = f"Created - Extra Trip {single_no}"
                r.receive_dt = created or t0.get("created_at")
            elif kind == "ReCpv":
                r.category = "Re-CPV"
                tr = recpv_by_trip.get(t0["id"])
                r.receive_dt = t0.get("created_at") or (tr["created_at"] if tr else None)
            else:
                r.category = extra_category(t0)
                r.receive_dt = t0.get("created_at")
            r.concern_lines = concern_lines(file, info, trips)
        r.history_lines = history_for(file["file_no"], file, recpv_by_file, {t["id"] for _c, t in trips}, history_since)
        r.area, r.area_sure, r.area_why = row_area(trips)
        if not r.area_sure:
            r.flags["area"] = r.area_why
        r.sla_days = SLA_OUT if r.area == "Out" else SLA_IN
        if kind != "Package":
            r.bill_note = f"{r.area} bill"
        if kind == "Package":
            st = (file.get("station") or "").lower()
            if st.startswith("out") and r.area == "In" or st.startswith("in ") and r.area == "Out":
                r.info.append(f"ড্যাশবোর্ডের Station = {file.get('station')}, কিন্তু ম্যাপ অনুযায়ী {r.area}")
        r.appointments = appointments_for(trips)
        r.last_file, r.last_trips = last_update_for(logs, trips, labels)
        if any(t.get("status_code") == 6 for _c, t in trips):
            r.canceled = True
            r.flags["slab"] = "Canceled ট্রিপ আছে (বিলযোগ্য কি না সিদ্ধান্ত বাকি)"
        _assign_submission(r, file, logs, has_followups=total_rows > 1 and any(g[0] in ("ReCpv", "Extra") for g in groups))
        views = [TripView(t, c["role"].upper(), info[c["id"]]["who"]) for c, t in trips]
        r.summary = analyze(views, r.submitted, "BS")
        if r.summary.uncertain:
            r.flags["summary"] = "; ".join(dict.fromkeys(r.summary.reasons)) or "সংক্ষেপ নিশ্চিত নয়"
        rows.append(r)
    return rows


def _assign_submission(r: BillRow, file: dict, logs: FileLogs | None, has_followups: bool) -> None:
    r.status, r.submitted_at = "Incomplete", None
    if logs is None or not logs.ok:
        if file.get("status_code") in (6, 7, 4):
            r.flags["status"] = "অ্যাক্টিভিটি লগ পাওয়া যায়নি"
        return
    subs = sorted(logs.submitted)
    if r.kind in ("Package", "Single"):
        if subs:
            if file.get("status_code") == 7 and not has_followups:
                r.status_note = "Partially Submitted"
                return
            r.status, r.submitted_at = "Submitted", subs[0]
            if file.get("status_code") == 7:
                r.flags["status"] = "ফাইল Partially Submitted, আগে একবার Submitted হয়েছিল"
        elif file.get("status_code") == 7:
            r.status_note = "Partially Submitted"
        return
    # ReCpv / Extra: the trip must be finished, then the first Submitted event after its finish
    t = r.trips[0][1]
    if t.get("status_code") != 5:
        return
    finish = logs.trip_finished.get(t["id"]) or t.get("end_time") or t.get("created_at")
    after = [s for s in subs if finish is None or s >= finish]
    if after:
        r.status, r.submitted_at = "Submitted", after[0]


# ------------------------------------------------------------------------------ TAT
def compute_tat(r: BillRow, report_date: date, holiday_set: set[date]) -> None:
    """Same numbers as the Excel formulas (Fri+Sat off, holidays from the list)."""
    if r.receive_dt is None:
        r.tat = r.extra_tat = None
        return
    end = r.submitted_at.date() if r.submitted_at else report_date
    start = r.receive_dt.date() + timedelta(days=1)
    r.tat = max(0, hol.count_business_days(start, end, holiday_set))
    r.sla_days = SLA_OUT if r.area == "Out" else SLA_IN
    r.extra_tat = max(0, r.tat - r.sla_days)
    r.sla_breach = r.extra_tat > 0


def before_after(r: BillRow) -> str:
    if not r.submitted_at:
        return ""
    return "Before 3 PM" if r.submitted_at.hour < CUTOFF_HOUR else "After 3 PM"


# ------------------------------------------------------------------------------ selection
def select_rows(rows: list[BillRow], mode: str, report_date: date, w_from: date | None = None,
                w_till: date | None = None) -> tuple[list[BillRow], list[BillRow]]:
    """-> (complete rows, incomplete rows), each sorted by Receive Date then file number."""
    complete, incomplete = [], []
    for r in rows:
        rd = r.receive_dt.date() if r.receive_dt else None
        if mode == "tracker":
            if rd is not None and w_from and rd < w_from:      # outside the look-back window
                continue
            if r.submitted and r.submitted_at.date() == report_date:
                complete.append(r)
            elif not r.submitted:
                incomplete.append(r)
        else:
            if rd is None or (w_from and rd < w_from) or (w_till and rd > w_till):
                continue
            (complete if r.submitted else incomplete).append(r)
    key = lambda r: (r.receive_dt or datetime.max, r.file_no, r.trips[0][1]["id"] or 0)   # noqa: E731
    complete.sort(key=key)
    incomplete.sort(key=key)
    for lst in (complete, incomplete):
        for i, r in enumerate(lst, 1):
            r.sl = i
    return complete, incomplete


def reconcile(rows: list[BillRow], files: list[dict]) -> dict:
    """Trip count check: trips in rows == trips of the files (Re-CPV never changes the count)."""
    row_trips = sum(len(r.trips) for r in rows)
    file_trips = sum(len(c["trips"]) for f in files for c in f["concerns"])
    by_kind = {k: sum(1 for r in rows if r.kind == k) for k in ("Package", "Single", "ReCpv", "Extra")}
    return {"rows": len(rows), "row_trips": row_trips, "file_trips": file_trips, "by_kind": by_kind,
            "package_trips": sum(len(r.trips) for r in rows if r.kind == "Package")}
