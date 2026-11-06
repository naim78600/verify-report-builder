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
from datetime import date, datetime, time, timedelta

from . import geo, holidays as hol
from .summary import Summary, TripView, analyze, clean_text

PACKAGE_MAX = 5
CUTOFF_HOUR = 15          # "before / after 3 PM"
SLA_IN = 2                # working days allowed, In area (Dhaka / Chattogram city corporation)
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
    sub_day: date | None = None                        # the date the tracker shows (a Fri/Sat/holiday submission -> next working day)
    partial_events: list = field(default_factory=list) # when the FILE became "Partially Submitted" (activity log, Dhaka time)
    file_status: int = 0                               # dashboard status code of the file (1..8)
    file_submitted: list = field(default_factory=list) # every SUBMITTED event of the file (activity log, Dhaka time)
    logs_ok: bool = False                              # the activity log of the file was read
    file_trips: list = field(default_factory=list)     # [(created_at, status_code)] of EVERY trip of the file (re-open detection)
    reason: str = ""                                   # why the row is still pending (appointment / within SLA / hold ...), "" = none found
    reason_kind: str = ""                              # appointment | hold | ongoing | partial | ""
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
    views: list = field(default_factory=list)          # TripView of this row's trips (to rebuild the Done/Due text)
    info: list = field(default_factory=list)           # notes for the Check List only (no yellow)
    folded: list = field(default_factory=list)         # [(kind, first trip id)] rows of the SAME file shown inside this one (Bill Slab history)
    mates: list = field(default_factory=list)          # Incomplete only: every pending row of the file (the reason belongs to the file)

    @property
    def submitted(self) -> bool:
        return self.status == "Submitted"

    @property
    def reported_at(self) -> datetime | None:
        """Submission date-time as the tracker shows it: the real time of day, on the reported (working) day."""
        if not self.submitted_at:
            return None
        if self.sub_day and self.sub_day != self.submitted_at.date():
            return datetime.combine(self.sub_day, self.submitted_at.time())
        return self.submitted_at

    @property
    def rolled(self) -> bool:
        return bool(self.submitted_at and self.sub_day and self.sub_day != self.submitted_at.date())

    @property
    def clock(self) -> time | None:
        """Time of day used for the 3 PM cut-off: a row rolled to the next working day counts as 'Before 3 PM'."""
        if not self.submitted_at:
            return None
        return time(0, 0) if self.rolled else self.submitted_at.time()


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
        r.partial_events = list(logs.partial) if logs is not None and logs.ok else []
        r.file_status = int(file.get("status_code") or 0)
        r.file_submitted = list(logs.submitted) if logs is not None and logs.ok else []
        r.logs_ok = bool(logs is not None and logs.ok)
        r.file_trips = [(t.get("created_at"), t.get("status_code")) for _c, t in flat]
        views = [TripView(t, c["role"].upper(), info[c["id"]]["who"]) for c, t in trips]
        r.views = views
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
def assign_sub_days(rows: list[BillRow], cap: date | None, holiday_set: set[date]) -> int:
    """Tracker convention (checked on the sent mails and the bank's Excel: not one of 3714 rows has a Friday submission):
    a submission that happens on a day off (Fri / Sat / holiday) is reported - and its TAT counted - on the NEXT working
    day.  `cap` = the last day of the report (a report made for a day off keeps that day).  -> rows rolled forward."""
    n = 0
    for r in rows:
        if not r.submitted_at:
            r.sub_day = None
            continue
        a = r.submitted_at.date()
        day = hol.next_working_day(a, holiday_set)
        if cap is not None and day > max(a, cap):
            day = max(a, cap)
        r.sub_day = day
        n += day != a
    return n


def compute_tat(r: BillRow, report_date: date, holiday_set: set[date]) -> None:
    """Same numbers as the Excel formulas (Fri+Sat off, holidays from the list)."""
    if r.receive_dt is None:
        r.tat = r.extra_tat = None
        return
    end = (r.sub_day or r.submitted_at.date()) if r.submitted_at else report_date
    start = r.receive_dt.date() + timedelta(days=1)
    r.tat = max(0, hol.count_business_days(start, end, holiday_set))
    r.sla_days = SLA_OUT if r.area == "Out" else SLA_IN
    r.extra_tat = max(0, r.tat - r.sla_days)
    r.sla_breach = r.extra_tat > 0


def before_after(r: BillRow) -> str:
    if not r.submitted_at:
        return ""
    return "Before 3 PM" if r.clock.hour < CUTOFF_HOUR else "After 3 PM"


# ------------------------------------------------------------------------------ selection
PHASE1_CUTOFF = time(CUTOFF_HOUR, 0)     # the 3:30 PM mail covers everything submitted BEFORE 3 PM


def apply_as_of(rows: list[BillRow], cutoff: date | None, until: datetime | None = None) -> int:
    """Roll the data back to the moment of the report.  A row submitted AFTER the last day of the report dates (or, for the
    first-phase mail, at / after `until` = 3 PM of the report day) was still waiting then, so it is shown as Incomplete
    ("Submitted later ...") instead of silently disappearing.  -> number of rows changed."""
    n = 0
    for r in rows:
        if not r.submitted:
            continue
        late_day = bool(cutoff and r.submitted_at.date() > cutoff)
        late_hour = bool(until and not late_day and not r.rolled and r.submitted_at >= until)
        if not (late_day or late_hour):
            continue
        r.status_note = (f"Submitted later ({r.submitted_at:%d/%m/%Y})" if late_day
                         else f"Submitted after 3 PM ({r.submitted_at:%I:%M %p})")
        r.status, r.submitted_at = "Incomplete", None
        if r.views:
            r.summary = analyze(r.views, False, "BS")
        n += 1
    return n


INCOMPLETE_SCOPES = ("sla_partial", "partial_today", "partial_open", "all_pending")
SCOPE_TEXT = {
    "sla_partial": "ড্যাশবোর্ডে এখনও Submitted হয়নি এমন ফাইল, স্ট্যাটাস ধরে: Hold (কারণসহ), Finished কিন্তু Submit হয়নি, Partially Submitted সবসময়; On Going শুধু SLA পেরোলে (In ২ / Out ৪ কর্মদিবস)",
    "partial_today": "আজ Partially Submitted হয়েছে এমন ফাইলের বাকি সারি",
    "partial_open": "Partially Submitted হয়ে এখনও খোলা সব ফাইলের বাকি সারি",
    "all_pending": "Submitted না হওয়া সব সারি",
}
LOOKBACK_DAYS = 90                        # a pending row is looked at only if its file came in during the last 90 days


def tracker_window(report_date: date, hset: set[date] | None) -> tuple[date, date]:
    """The days one tracker covers: from the day after the previous working day up to the report date, so the Friday /
    Saturday / holiday submissions come out in the next working day's tracker (Thursday's tracker covers Thursday only)."""
    return hol.previous_working_day(report_date, hset or set()) + timedelta(days=1), report_date


_TEST_FILE = re.compile(r"(^|[-_ ])test([-_ \d]|$)", re.IGNORECASE)


def is_test_file(file_no: str) -> bool:
    """Practice / test applications (e.g. "PB-PL-Test-123456") are not bank work and never belong in the bank's report."""
    return bool(_TEST_FILE.search(file_no or ""))


DEAD_TRIP = (6, 7, 8)         # Canceled / Inactive / Withdrawn trip: nothing left to submit for it (live 05-11-2026: an Inactive extra
                              # trip of an old, already Submitted file came back as an overdue ghost row once the file was re-opened)


def file_state(r: BillRow, as_of: datetime | None = None) -> str:
    """What was the FILE (not one bill row) waiting for at `as_of` (None = now)?  The dashboard works per file, so the
    Incomplete list does too:
        "closed"     the file is Canceled / Withdrawn - it is never pending
        "submitted"  it was Submitted and nothing was added after that - NO row of it is pending
        "partial"    the last status event is Partially Submitted (documents still due)
        "pending"    not submitted yet, or re-opened (a live trip - Re-CPV / extra - created after the last Submitted)
    Activity log first; if the log could not be read the file stays "pending" (visible, flagged) instead of vanishing."""
    if r.file_status in (5, 8):
        return "closed"
    if not r.logs_ok:                                       # no log = no submission time: keep it visible (blue "status" cell) rather than lose it
        return "partial" if r.file_status == 7 else "pending"
    t = as_of or datetime.max
    subs = [x for x in r.file_submitted if x <= t]
    parts = [x for x in r.partial_events if x <= t]
    last_sub = max(subs, default=None)
    last_part = max(parts, default=None)
    if last_part and (last_sub is None or last_part > last_sub):
        return "partial"
    if last_sub is None:
        return "pending"
    if any(ca and last_sub < ca <= t and sc not in DEAD_TRIP for ca, sc in r.file_trips):
        return "pending"                                    # re-opened after its last submission
    return "submitted"


def is_dead_row(r: BillRow) -> bool:
    """A Re-CPV / Extra row whose trips are all Canceled / Inactive / Withdrawn is not a pending bill."""
    return r.kind in ("ReCpv", "Extra") and bool(r.trips) and all(t.get("status_code") in DEAD_TRIP for _c, t in r.trips)


KIND_RANK = {"Package": 0, "Single": 1, "ReCpv": 2, "Extra": 3}


def _live_trips(rs: list[BillRow]) -> list[dict]:
    return [t for r in rs for _c, t in r.trips if t.get("status_code") not in DEAD_TRIP]


def pending_kind(rs: list[BillRow], state: str = "pending") -> str:
    """What is the (not yet submitted) FILE doing right now?  Looks at the live trips of its pending rows and at the
    dashboard's file status:   partial | hold | ongoing | finished | dead
        partial   Partially Submitted (documents still due)
        hold      the file / a live trip is on Hold
        ongoing   a live trip is Created / Allocated / Started (the work is still running)
        finished  every live trip is Finished, but the file was not Submitted
        dead      nothing live is left (all Canceled / Inactive / Withdrawn)"""
    if state == "partial":
        return "partial"
    live = _live_trips(rs)
    if not live:
        return "dead"
    fs = rs[0].file_status
    if fs == 3 or any(t.get("status_code") == 4 for t in live):
        return "hold"
    if any(t.get("status_code") in (1, 2, 3) for t in live):
        return "ongoing"
    return "finished"


def classify_reason(r: BillRow, mates: list[BillRow] | None = None, state: str = "pending") -> None:
    """Why is the file not submitted?  Sets r.reason / r.reason_kind (empty = nothing found -> light-blue cell + Check List line).
    `mates` = every pending row of the same file (the reason belongs to the FILE, not to one bill row).
        Partially Submitted   the documents named in Due
        Hold                  "Hold: <the remark written on the dashboard>"   (always listed; a Hold without a remark is flagged)
        Finished              "Finished - not yet submitted"
        Appointment           the newest given appointment (added to the above, or alone for an On Going file past its SLA)
        On Going              only inside its SLA = a valid reason by itself ("On Going, within SLA")"""
    mates = mates or [r]
    r.reason, r.reason_kind = "", ""
    if r.submitted:
        return
    kind = pending_kind(mates, state)
    parts: list[tuple[str, str]] = []
    if kind == "partial":
        due = r.summary.due.replace("\n", " ").strip()
        if due in ("", "0", "Report not yet submitted"):
            due = next((m.summary.due.replace("\n", " ").strip() for m in mates
                        if m.summary.due.strip() not in ("", "0", "Report not yet submitted")), "")
        if due:
            parts.append(("partial", "Partially Submitted: " + due[:90]))
    elif kind == "hold":
        texts = []
        for t in _live_trips(mates):
            if t.get("status_code") == 4:
                text = " ".join(x for x in (clean_text(t.get("remarks")), clean_text(t.get("comment"))) if x)
                if len(text) >= 4 and text not in texts:
                    texts.append(text)
        if texts:
            parts.append(("hold", "Hold: " + " / ".join(texts)[:120]))
        else:
            parts.append(("hold", "Hold: no reason written on the dashboard"))
            r.flags["reason"] = "Hold-এর কারণ ড্যাশবোর্ডে লেখা নেই"
    elif kind == "finished":
        parts.append(("finished", "Finished - not yet submitted"))
    appts = sorted((a for m in mates for a in m.appointments if a.get("active", True) and a.get("time")),
                   key=lambda a: a["time"])
    if appts and not (parts and parts[0][0] == "partial" and "appointment" in parts[0][1].lower()):
        parts.append(("appointment", f"Appointment {appts[-1]['time']:%d/%m/%Y %I:%M %p}"))
    if not parts and kind == "ongoing" and not any(m.sla_breach for m in mates):
        parts.append(("ongoing", "On Going, within SLA"))
    if parts:
        r.reason_kind = parts[0][0]
        r.reason = " | ".join(p[1] for p in parts)


def _fold_into(keep: BillRow, dropped: list[BillRow]) -> None:
    for x in dropped:
        keep.folded.append((x.kind, x.trips[0][1].get("id")))


def fold_complete(rows: list[BillRow]) -> list[BillRow]:
    """ONE row per file and submission day.  The Bill Slab column already carries the whole billing history of the file, so a
    Re-CPV / Extra row that was submitted together with (or on the same day as) the Package row is not listed a second time:
    Package (or Single) submitted that day -> the Package row; only a Re-CPV / Extra was submitted -> that row (a Re-CPV rather
    than an Extra, the later one if there are several).  Package + Single rows of one file stay (they are different bills)."""
    groups: dict = {}
    for r in rows:
        groups.setdefault((r.file_id, r.sub_day or (r.submitted_at.date() if r.submitted_at else None)), []).append(r)
    out: list[BillRow] = []
    for g in groups.values():
        main = [r for r in g if r.kind in ("Package", "Single")]
        follow = [r for r in g if r.kind not in ("Package", "Single")]
        if main:
            _fold_into(main[0], follow)
            out.extend(main)
        else:
            follow.sort(key=lambda r: (r.submitted_at or datetime.min, -KIND_RANK.get(r.kind, 9), r.receive_dt or datetime.min),
                        reverse=True)
            _fold_into(follow[0], follow[1:])
            out.append(follow[0])
    return out


def fold_incomplete(rs: list[BillRow]) -> BillRow:
    """ONE row per pending file: the row that is the most overdue (then the oldest, then Package before Re-CPV / Extra).
    The others are shown in its Bill Slab history; the reason is worked out over all of them."""
    keep = sorted(rs, key=lambda r: (-(r.extra_tat or 0), r.receive_dt or datetime.max, KIND_RANK.get(r.kind, 9),
                                     r.trips[0][1].get("id") or 0))[0]
    _fold_into(keep, [x for x in rs if x is not keep])
    return keep


def listed_by_status(rs: list[BillRow], state: str) -> bool:
    """The Incomplete rule, by the status of the file (as the dashboard shows it):
        Partially Submitted -> listed          Hold -> listed (with the written reason)
        Finished, not Submitted -> listed ("not yet submitted")
        On Going / Created -> listed ONLY when the SLA is already breached (a running file inside its SLA is not late)."""
    kind = pending_kind(rs, state)
    if kind in ("partial", "hold", "finished"):
        return True
    if kind == "ongoing":
        return any((x.extra_tat or 0) > 0 for x in rs)
    return False


def select_rows(rows: list[BillRow], mode: str, report_date: date, w_from: date | None = None,
                w_till: date | None = None, hset: set[date] | None = None,
                scope: str = "sla_partial", today: date | None = None,
                after3_only: bool = False, as_of: datetime | None = None) -> tuple[list[BillRow], list[BillRow]]:
    """-> (complete rows, incomplete rows), each sorted by Receive Date then file number.

    Complete   = rows SUBMITTED inside the dates (tracker: on the report date and the days off just before it; range:
                 from..till), whenever they were received - exactly what the dashboard's Reports page lists for Submitted.
                 `after3_only` (second-phase mail): only the rows submitted after 3 PM, i.e. not sent in the first mail.
    Incomplete = decided PER FILE, like the dashboard (see file_state): only files that were NOT Submitted at `as_of`
                 (default: the end of the report day) can have pending rows - a Submitted file never does.  Of such a file
                 every live pending row is listed when, tracker, by `scope`:
                   sla_partial   : (V3 default) the file is overdue - one of its pending rows is past its SLA, counted from
                                   the file's Start Date (In 2 / Out 4 working days) - or it is "Partially Submitted"
                                   (its Due text says which documents are missing)
                   partial_today / partial_open : only the Partially Submitted files (checked against the sent mails)
                   all_pending   : every pending file (received inside the look-back window)
                 range: pending rows of files not submitted yet, received inside the dates."""
    if scope not in INCOMPLETE_SCOPES:
        scope = "sla_partial"
    t_lo, t_hi = tracker_window(report_date, hset) if mode == "tracker" else (None, None)
    if as_of is None:
        as_of = datetime.combine(report_date if mode == "tracker" else (w_till or report_date), time(23, 59, 59))
    complete: list[BillRow] = []
    pending: dict[int, list[BillRow]] = {}
    state_of: dict[int, str] = {}
    for r in rows:
        rd = r.receive_dt.date() if r.receive_dt else None
        if mode == "tracker":
            if r.submitted:
                if t_lo <= r.submitted_at.date() <= t_hi:
                    if after3_only and r.clock.hour < CUTOFF_HOUR:
                        continue
                    complete.append(r)
                continue
            if rd is not None and rd > report_date:                    # not even received on that day
                continue
            if rd is not None and w_from and rd < w_from:              # outside the look-back window
                continue
        else:
            if r.submitted:
                sd = r.sub_day or r.submitted_at.date()
                if (w_from is None or sd >= w_from) and (w_till is None or sd <= w_till):
                    complete.append(r)
                continue
            if not (rd is not None and (w_from is None or rd >= w_from) and (w_till is None or rd <= w_till)):
                continue
        if is_dead_row(r):
            continue
        st = state_of.get(r.file_id)
        if st is None:
            st = state_of[r.file_id] = file_state(r, as_of)
        if st in ("closed", "submitted"):                              # the dashboard says this file is done / withdrawn
            continue
        pending.setdefault(r.file_id, []).append(r)
    incomplete: list[BillRow] = []
    for fid, rs in pending.items():
        if mode != "tracker" or scope == "all_pending":
            keep = True
        elif scope == "sla_partial":
            keep = listed_by_status(rs, state_of[fid])
        else:
            days = [e.date() for e in rs[0].partial_events]
            keep = (scope == "partial_today" and any(t_lo <= x <= t_hi for x in days)) or \
                   (scope == "partial_open" and any(x <= t_hi for x in days))
        if keep:
            mates = sorted(rs, key=lambda r: (r.receive_dt or datetime.max, r.trips[0][1].get("id") or 0))
            main = fold_incomplete(mates)
            main.mates = mates                                         # every pending row of the file (reason is per file)
            incomplete.append(main)
    complete = fold_complete(complete)
    key = lambda r: (r.receive_dt or datetime.max, r.file_no, r.trips[0][1]["id"] or 0)   # noqa: E731
    complete.sort(key=key)
    incomplete.sort(key=key)
    for lst in (complete, incomplete):
        for i, r in enumerate(lst, 1):
            r.sl = i
    for r in incomplete:
        classify_reason(r, r.mates or None, state_of.get(r.file_id, "pending"))
        if not r.reason and mode == "tracker":
            r.flags["reason"] = "কোনো কারণ পাওয়া যায়নি (Appointment / Hold reason / SLA-র মধ্যে On Going নেই)"
    return complete, incomplete


FILE_STATUS_NAME = {1: "Created", 2: "On Going", 3: "Hold", 4: "Finished", 5: "Canceled", 6: "Submitted", 7: "Partially Submitted", 8: "Withdrawn"}


def dashboard_check(d) -> dict:
    """Compare the dashboard's own Submitted list (same dates) with the Complete Report, file by file.
    -> {dashboard, report_files, matched, extra, partial, missing: [(file no, why)], other_phase: [file no],
        files: [(file no, submitted at, where it is)], reopened: [(file no, why)]}
    `files` lists EVERY dashboard file with its submission time and where it went (this report / the other phase's mail /
    not matched), so the dashboard number can be tied to the report number line by line.  `reopened` = files in the
    Complete Report that the dashboard no longer lists as Submitted (they were submitted in the dates, then re-opened)."""
    dash = d.dash
    ids = {fid: no for fid, no in dict(dash.get("submitted") or {}).items() if not is_test_file(no)}
    in_report = {r.file_id for r in d.complete}
    files = {f["id"]: f for f in d.files}
    lo, hi = dash.get("from"), dash.get("till")
    missing, other, listing = [], [], []
    after3 = bool(getattr(d, "after3_only", False))
    phase_label = "2nd phase mail (after 3 PM)" if d.slot == "3pm" else "1st phase mail (before 3 PM)"
    by_file: dict = {}
    for r in d.all_rows:
        by_file.setdefault(r.file_id, []).append(r)

    def sub_time(fid):
        mine = by_file.get(fid) or []
        subs = [x for x in (mine[0].file_submitted if mine else []) if (lo is None or x.date() >= lo) and (hi is None or x.date() <= hi)]
        return max(subs) if subs else None

    for fid in sorted(ids, key=lambda i: ids[i]):
        mine = by_file.get(fid, [])
        if fid in in_report:
            listing.append((ids[fid], sub_time(fid), "This report (Complete)"))
            continue
        if mine and d.mode == "tracker" and d.slot == "3pm" and any(r.status_note.startswith("Submitted after 3 PM") for r in mine):
            other.append(ids[fid])                         # submitted after 3 PM: belongs to the 2nd-phase mail, not "missing"
            listing.append((ids[fid], sub_time(fid), phase_label))
            continue
        if mine and after3 and all(r.submitted and r.clock and r.clock.hour < CUTOFF_HOUR for r in mine if r.submitted) \
                and any(r.submitted for r in mine):
            other.append(ids[fid])                         # submitted before 3 PM: already sent in the 1st-phase mail
            listing.append((ids[fid], sub_time(fid), phase_label))
            continue
        if fid not in files:
            why = "ফাইলের তথ্য পড়া যায়নি"
        elif not mine:
            why = "কোনো বিল-সারি তৈরি হয়নি"
        else:
            subs = sorted({r.submitted_at for r in mine if r.submitted_at})
            why = ("Activity log-এ Submitted: " + ", ".join(f"{t:%d/%m/%Y %H:%M}" for t in subs[:3])) if subs else \
                  "Activity log-এ এই সময়ের Submitted ঘটনা নেই"
        missing.append((ids[fid], why))
        listing.append((ids[fid], sub_time(fid), "NOT MATCHED - " + why))
    reopened = []
    for fid in sorted(in_report - set(ids), key=lambda i: files.get(i, {}).get("file_no", "")):
        f = files.get(fid) or {}
        reopened.append((f.get("file_no", str(fid)), "now " + FILE_STATUS_NAME.get(int(f.get("status_code") or 0), "?")))
    listing.sort(key=lambda x: (x[1] or datetime.max, x[0]))
    return {"from": lo, "till": hi, "dashboard": len(ids), "report_files": len(in_report),
            "matched": len(set(ids) & in_report), "extra": len(in_report - set(ids)), "partial": len(dash.get("partial") or {}),
            "missing": missing, "other_phase": other, "files": listing, "reopened": reopened}


def reconcile(rows: list[BillRow], files: list[dict]) -> dict:
    """Trip count check: trips in rows == trips of the files (Re-CPV never changes the count)."""
    row_trips = sum(len(r.trips) for r in rows)
    file_trips = sum(len(c["trips"]) for f in files for c in f["concerns"])
    by_kind = {k: sum(1 for r in rows if r.kind == k) for k in ("Package", "Single", "ReCpv", "Extra")}
    return {"rows": len(rows), "row_trips": row_trips, "file_trips": file_trips, "by_kind": by_kind,
            "package_trips": sum(len(r.trips) for r in rows if r.kind == "Package")}
