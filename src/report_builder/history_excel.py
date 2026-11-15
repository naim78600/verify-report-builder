"""File History - Excel (one workbook, read-only data from the dashboard).

Sheets:  Summary | Timeline | Submission History | Trips | Appointments | Re-CPV & Extra | Concerns | Not Found
(+ Notes when something could not be read).  Colours come from theme.py; no red and no yellow anywhere.
Only the File No column has a filter button; headers are frozen; text is wrapped; zoom 85 %.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.filters import FilterColumn

from . import theme as T
from .billing import concern_info
from .excel import _clean
from .file_history import FileData, HistoryData, name_check, overview, submission_history, timeline, trip_label

FONT = "Calibri"
DT = "dd/mm/yyyy hh:mm:ss"
DT_SHORT = "dd/mm/yyyy hh:mm"
THIN = Side(style="thin", color=T.BORDER)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD = PatternFill("solid", fgColor=T.NAVY)
ZEBRA = PatternFill("solid", fgColor=T.ZEBRA)
SLATE = PatternFill("solid", fgColor=T.KIND_BG.get("Single", "E2E8F0"))
POS_FILL = PatternFill("solid", fgColor=T.POS_BG)
OUT_FILL = PatternFill("solid", fgColor=T.OUT_BG)
IN_FILL = PatternFill("solid", fgColor=T.IN_BG)
CAUTION = getattr(T, "NEG", "B45309")          # amber-brown TEXT only (never a yellow / red fill)
MAX_CELL = 32000

TOP = Alignment(vertical="top", wrap_text=True)
MID = Alignment(vertical="top", horizontal="center", wrap_text=True)


class Col:
    def __init__(self, title: str, width: int, key: str, center: bool = False, fmt: str | None = None):
        self.title, self.width, self.key, self.center, self.fmt = title, width, key, center, fmt


def _put(ws, r, c, v):
    cell = ws.cell(row=r, column=c)
    v = _clean(v)
    if isinstance(v, str):
        v = v[:MAX_CELL]
    cell.value = v
    if isinstance(v, str):
        cell.data_type = "s"                       # text such as "=..." must never become a formula
    return cell


def _est_lines(text, width: int) -> int:
    if text in (None, ""):
        return 1
    return sum(max(1, math.ceil(len(part) / max(width - 2, 1))) for part in str(text).split("\n"))


def _sheet(wb: Workbook, title: str, heading: str, sub: str, cols: list[Col], rows: list[dict], file_key: str = "file_no",
           empty: str = "Nothing to show.", styler=None) -> None:
    ws = wb.create_sheet(title)
    n = len(cols)
    ws.sheet_view.zoomScale = 85
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = T.NAVY
    # title + subtitle
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=max(n, 2))
    _put(ws, 1, 1, heading).font = Font(name=FONT, bold=True, size=14, color=T.NAVY)
    ws.cell(1, 1).alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 28
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=max(n, 2))
    _put(ws, 2, 1, sub).font = Font(name=FONT, size=9, italic=True, color=T.MUTED)
    ws.cell(2, 1).alignment = Alignment(vertical="center", wrap_text=True, indent=1)
    ws.row_dimensions[2].height = max(16, 13 * _est_lines(sub, sum(c.width for c in cols)))
    # header
    hdr = 3
    for i, c in enumerate(cols, 1):
        _put(ws, hdr, i, c.title)
        cell = ws.cell(hdr, i)
        cell.font = Font(name=FONT, bold=True, color=T.WHITE, size=10)
        cell.fill, cell.border = HEAD, BOX
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = c.width
    ws.row_dimensions[hdr].height = 30
    # rows
    r = hdr
    for k, row in enumerate(rows):
        r += 1
        longest = 1
        for i, c in enumerate(cols, 1):
            v = row.get(c.key)
            cell = _put(ws, r, i, v)
            cell.border = BOX
            cell.alignment = MID if c.center else TOP
            cell.font = Font(name=FONT, size=10, color=T.TEXT)
            if k % 2:
                cell.fill = ZEBRA
            if isinstance(v, datetime):
                cell.number_format = c.fmt or DT
            elif isinstance(v, date):
                cell.number_format = "dd/mm/yyyy"
            elif c.fmt and v is not None:
                cell.number_format = c.fmt
            longest = max(longest, _est_lines(v if not isinstance(v, (datetime, date)) else "x", c.width))
        if styler:
            styler(ws, r, cols, row)
        ws.row_dimensions[r].height = min(409, max(18, 13.5 * longest + 4))
    if not rows:
        ws.merge_cells(start_row=hdr + 1, start_column=1, end_row=hdr + 1, end_column=max(n, 2))
        _put(ws, hdr + 1, 1, empty).font = Font(name=FONT, italic=True, color=T.MUTED, size=10)
        ws.cell(hdr + 1, 1).alignment = Alignment(indent=1, vertical="center")
        ws.row_dimensions[hdr + 1].height = 22
        r = hdr + 1
    # filter button ONLY on the File No column
    fkeys = [i for i, c in enumerate(cols) if c.key == file_key]
    if fkeys:
        ws.auto_filter.ref = f"A{hdr}:{get_column_letter(n)}{max(r, hdr + 1)}"
        for i in range(n):
            if i != fkeys[0]:
                ws.auto_filter.filterColumn.append(FilterColumn(colId=i, hiddenButton=True))
        # headers + everything up to the File No column. A coordinate string, never a cell object: on an EMPTY sheet that
        # cell sits inside the merged "nothing to show" row (a MergedCell) and openpyxl raised
        # "TypeError: 'MergedCell' object is not iterable" (File History run failed).
        ws.freeze_panes = f"{get_column_letter(fkeys[0] + 2)}{hdr + 1}"
    else:
        ws.freeze_panes = f"A{hdr + 1}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{hdr}:{hdr}"


# ------------------------------------------------------------------------------ styling of single cells
def _colour(cell, fill=None, color=None, bold=None):
    f = cell.font
    cell.font = Font(name=f.name, size=f.size, bold=f.bold if bold is None else bold, italic=f.italic, color=color or f.color)
    if fill is not None:
        cell.fill = fill


def _summary_style(ws, r, cols, row):
    idx = {c.key: i for i, c in enumerate(cols, 1)}
    if row.get("_missing"):
        for i in range(1, len(cols) + 1):
            _colour(ws.cell(r, i), SLATE, T.MUTED)
        _colour(ws.cell(r, idx["file_no"]), SLATE, T.MUTED, True)
        return
    st = (row.get("status") or "").lower()
    if st == "submitted":
        _colour(ws.cell(r, idx["status"]), POS_FILL, T.POS, True)
    elif st:
        _colour(ws.cell(r, idx["status"]), SLATE, T.TEXT, True)
    area = row.get("area")
    if area == "Out":
        _colour(ws.cell(r, idx["area"]), OUT_FILL, T.OUT, True)
    elif area == "In":
        _colour(ws.cell(r, idx["area"]), IN_FILL, T.IN, True)
    if row.get("match_note"):
        _colour(ws.cell(r, idx["match_note"]), None, CAUTION, True)
    nc = row.get("name_check") or ""
    if "name_check" in idx and nc:
        if nc.startswith("Matches"):
            _colour(ws.cell(r, idx["name_check"]), POS_FILL, T.POS, True)
        else:
            _colour(ws.cell(r, idx["name_check"]), None, CAUTION, True)
    sla = row.get("sla") or ""
    if "SLA Breach" in sla:
        _colour(ws.cell(r, idx["sla"]), None, CAUTION)
    if row.get("appointments") == "Yes":
        _colour(ws.cell(r, idx["appointments"]), None, T.OUT, True)


def _event_style_submission(ws, r, cols, row):
    idx = {c.key: i for i, c in enumerate(cols, 1)}
    ev = row.get("event")
    if ev == "Submitted":
        _colour(ws.cell(r, idx["event"]), POS_FILL, T.POS, True)
    elif ev:
        _colour(ws.cell(r, idx["event"]), SLATE, T.TEXT, True)


# ------------------------------------------------------------------------------ rows of each sheet
def _has_names(h: HistoryData) -> bool:
    return any(getattr(e, "name", "") for e in h.entries)


def _summary_rows(h: HistoryData) -> list[dict]:
    rows = []
    for m in h.matches:
        given = getattr(m.entry, "name", "")
        if not m.found or m.file_id not in h.files:
            rows.append({"searched": m.entry.raw, "given_name": given, "file_no": "File not found", "_missing": True, "match_note": m.note})
            continue
        fd = h.files[m.file_id]
        if fd.error:
            rows.append({"searched": m.entry.raw, "given_name": given, "file_no": fd.file_no, "type": "", "status": "Could not read",
                         "match_note": " · ".join(x for x in (m.note, f"File could not be read: {fd.error}") if x)})
            continue
        o = overview(fd)
        res, app = name_check(given, fd.file)
        rows.append({
            "given_name": given, "name_check": res, "file_applicant": app,
            "searched": m.entry.raw, "file_no": o["file_no"], "type": o["type"], "status": o["status"], "created": o["created"],
            "area": o["area"], "bill_rows": "\n".join(o["bill_rows"]) or "-", "sla": "\n".join(o["sla"]) or "-",
            "last_update": "\n".join(o["last_update"]) or "N/A", "appointments": "Yes" if o["appointments"] else "No",
            "match_note": m.note})
    return rows


def _results(h: HistoryData) -> list[FileData]:
    return [fd for fd in h.results if not fd.error]


def _timeline_rows(h: HistoryData) -> list[dict]:
    rows = []
    for fd in _results(h):
        for e in timeline(fd):
            rows.append({"file_no": fd.file_no, "when": e["when"], "scope": e["scope"], "trip_id": e["trip_id"],
                         "trip_type": e["trip_type"], "text": e["text"], "user": e["user"]})
    return rows


def _submission_rows(h: HistoryData) -> list[dict]:
    rows = []
    for fd in _results(h):
        for s in submission_history(fd):
            rows.append({"file_no": fd.file_no, "when": s["when"], "event": s["event"], "user": s["user"],
                         "line": s["line"], "done": s["done"], "due": s["due"]})
    return rows


def _trip_rows(h: HistoryData) -> list[dict]:
    rows = []
    for fd in _results(h):
        info = concern_info(fd.file)
        for c in fd.file["concerns"]:
            ci = info.get(c["id"], {})
            who = f'{ci.get("label", c["role"])}: {c["name"]}'
            for t in c["trips"]:
                rem = t.get("remarks") or ""
                if t.get("comment"):
                    rem = (rem + "\n" if rem else "") + "Comment: " + t["comment"]
                rows.append({"file_no": fd.file_no, "trip_id": t["id"], "concern": who, "type": trip_label(t),
                             "status": t.get("status", ""), "created": t.get("created_at"), "start": t.get("start_time"),
                             "end": t.get("end_time"), "verifier": t.get("verifier", ""), "assigned_by": t.get("assigned_by", ""),
                             "remarks": rem or "-", "_sort": (t.get("created_at") or datetime.min, t["id"] or 0)})
    rows.sort(key=lambda x: (x["file_no"], x["_sort"]))
    return rows


def _appointment_rows(h: HistoryData) -> list[dict]:
    rows = []
    for fd in _results(h):
        for c in fd.file["concerns"]:
            for t in c["trips"]:
                for a in t.get("appointments") or []:
                    rows.append({"file_no": fd.file_no, "trip_id": t["id"], "trip_type": trip_label(t), "time": a.get("time"),
                                 "created": a.get("created_at"), "type": a.get("type", ""), "reason": a.get("reason", "") or "-",
                                 "active": "Yes" if a.get("active") else "No",
                                 "_sort": (a.get("created_at") or datetime.min, t["id"] or 0)})
    rows.sort(key=lambda x: (x["file_no"], x["_sort"]))
    return rows


def _extra_rows(h: HistoryData) -> list[dict]:
    rows = []
    for fd in _results(h):
        trips = {t["id"]: t for c in fd.file["concerns"] for t in c["trips"]}
        area_of = {t["id"]: r.area for r in fd.rows for _c, t in r.trips}
        for tr in sorted(fd.recpv_events, key=lambda x: x.get("created_at") or datetime.min):
            ids = tr.get("trip_ids") or []
            rows.append({"file_no": fd.file_no, "kind": "Re-CPV", "trip_id": ", ".join(str(i) for i in ids) or "-",
                         "trip_type": ", ".join(dict.fromkeys(trip_label(trips[i]) for i in ids if i in trips)) or "-",
                         "created": tr.get("created_at"), "reason": tr.get("reason") or "-",
                         "area": next((area_of[i] for i in ids if i in area_of), "")})
        for r in sorted(fd.rows, key=lambda x: x.history_pos):
            if r.kind not in ("Extra", "Single"):
                continue
            t = r.trips[0][1]
            rows.append({"file_no": fd.file_no, "kind": r.category, "trip_id": str(t["id"]), "trip_type": trip_label(t),
                         "created": t.get("created_at"), "reason": (t.get("comment") or "").strip() or "-", "area": r.area})
    return rows


def _concern_rows(h: HistoryData) -> list[dict]:
    rows = []
    for fd in _results(h):
        info = concern_info(fd.file)
        for c in sorted(fd.file["concerns"], key=lambda c: info[c["id"]]["no"]):
            ci = info[c["id"]]
            kinds = [trip_label(t) for t in c["trips"]]
            counted = ", ".join(f"{k} x{kinds.count(k)}" if kinds.count(k) > 1 else k for k in dict.fromkeys(kinds))
            rows.append({"file_no": fd.file_no, "no": ci["no"], "role": ci["label"], "name": c["name"],
                         "designation": c.get("designation", "") or "-", "trips": counted or "-"})
    return rows


def _not_found_rows(h: HistoryData) -> list[dict]:
    rows = []
    for m in h.matches:
        if not m.found:
            rows.append({"searched": m.entry.raw, "given_name": getattr(m.entry, "name", ""),
                         "kind": "Full file number" if m.entry.kind == "full" else "Last digits",
                         "result": "File not found", "where": m.note.replace("File not found", "").strip(" ()")})
    return rows


# ------------------------------------------------------------------------------ workbook
def build_history_excel(h: HistoryData, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.title = "File History"
    when = h.generated_at or datetime.now()
    found = len({m.file_id for m in h.matches if m.found})
    head = (f"{h.org_name or 'Organisation'} · searched {len(h.entries)} number(s) · {found} file(s) found · "
            f"{len(h.not_found)} not found · {when:%d/%m/%Y %H:%M}" + (f" · {h.server_label}" if h.server_label else ""))

    S = lambda t, w, k, c=False, f=None: Col(t, w, k, c, f)                      # noqa: E731
    names = _has_names(h)
    name_cols = [S("Applicant Name (given)", 26, "given_name"), S("Name Check", 22, "name_check", True),
                 S("Applicant on the file", 26, "file_applicant")] if names else []
    _sheet(wb, "Summary", "File History - Summary", head, [
        S("Searched", 17, "searched", True), *name_cols, S("File No", 24, "file_no", True), S("Type", 8, "type", True),
        S("Current Status", 16, "status", True), S("Created", 17, "created", True, DT_SHORT), S("Area", 9, "area", True),
        S("Bill Rows (history)", 48, "bill_rows"), S("SLA / TAT", 44, "sla"),
        S("Last Update (newest first)", 56, "last_update"), S("Appointments", 13, "appointments", True),
        S("Match Note", 34, "match_note")], _summary_rows(h), styler=_summary_style,
        empty="No file numbers were searched.")
    _sheet(wb, "Timeline", "File History - Timeline (every dashboard event, newest first)",
           "Taken from the file's activity log; times are Bangladesh time. Each file's events are together, newest first.", [
               S("File No", 24, "file_no", True), S("Date-Time", 19, "when", True), S("Scope", 8, "scope", True),
               S("Trip ID", 10, "trip_id", True), S("Trip Type", 16, "trip_type", True), S("Event", 48, "text"),
               S("User", 20, "user")], _timeline_rows(h), empty="No activity found for the matched files.")
    _sheet(wb, "Submission History", "File History - Submission History",
           "Calculated from dashboard events (a trip counts as Done only if the log shows it finished by that moment). "
           "It is a rebuilt line, not a copy of what was written in the bank's tracker.", [
               S("File No", 24, "file_no", True), S("Date-Time", 19, "when", True), S("Event", 20, "event", True),
               S("By", 18, "user"), S("Done / Due (bank style)", 60, "line"), S("Done", 46, "done"), S("Due", 46, "due")],
           _submission_rows(h), styler=_event_style_submission, empty="No Submitted / Partially Submitted event found.")
    _sheet(wb, "Trips", "File History - Trips", "Every trip of every matched file, with the verifier's full remarks.", [
        S("File No", 24, "file_no", True), S("Trip ID", 10, "trip_id", True), S("Concern", 30, "concern"),
        S("Trip Type", 14, "type", True), S("Status", 12, "status", True), S("Created", 18, "created", True, DT),
        S("Start", 18, "start", True, DT), S("End", 18, "end", True, DT), S("Assigned To", 18, "verifier"),
        S("Assigned By", 16, "assigned_by"), S("Remarks (full)", 80, "remarks")], _trip_rows(h), empty="No trips.")
    _sheet(wb, "Appointments", "File History - Appointments", "Appointment time, and when it was created (with seconds).", [
        S("File No", 24, "file_no", True), S("Trip ID", 10, "trip_id", True), S("Trip Type", 14, "trip_type", True),
        S("Appointment Time", 19, "time", True, DT), S("Appointment Created", 19, "created", True, DT),
        S("Type", 14, "type", True), S("Reason", 60, "reason"), S("Active", 9, "active", True)], _appointment_rows(h),
        empty="No appointment on any matched file.")
    _sheet(wb, "Re-CPV & Extra", "File History - Re-CPV and Extra trips", "Re-CPV from the Re-CPV tracker; Extra trips from the file's own trips.", [
        S("File No", 24, "file_no", True), S("Kind", 24, "kind", True), S("Trip ID", 14, "trip_id", True),
        S("Trip Type", 16, "trip_type", True), S("Created", 19, "created", True, DT), S("Reason / Comment", 64, "reason"),
        S("Area", 9, "area", True)], _extra_rows(h), empty="No Re-CPV or Extra trip on any matched file.")
    _sheet(wb, "Concerns", "File History - Concerns", "Applicant / Co-Applicant / Guarantors of each matched file.", [
        S("File No", 24, "file_no", True), S("No.", 6, "no", True), S("Role", 16, "role", True), S("Name", 32, "name"),
        S("Designation", 22, "designation"), S("Trips", 34, "trips")], _concern_rows(h), empty="No concerns.")
    _sheet(wb, "Not Found", "File History - Not Found", "These numbers matched no file of the organisation.", [
        S("Searched", 24, "searched", True), *([S("Applicant Name (given)", 26, "given_name")] if names else []),
        S("Kind", 18, "kind", True), S("Result", 18, "result", True),
        S("Searched Where", 60, "where")], _not_found_rows(h), file_key="searched", empty="Every number was found.")
    if h.notes:
        _sheet(wb, "Notes", "File History - Notes", "Things that could not be read completely.",
               [S("Note", 120, "note")], [{"note": n} for n in h.notes], file_key="note")
    from .pagesetup import a4
    a4(wb)
    wb.save(path)
    return path


def write_history_outputs(h: HistoryData, out_dir) -> list[Path]:
    out_dir = Path(out_dir)
    when = h.generated_at or datetime.now()
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"File_History_{when:%Y-%m-%d_%H%M}")
    return [build_history_excel(h, out_dir / f"{stem}.xlsx")]


# ------------------------------------------------------------------------------ input template
def write_history_template(path) -> Path:
    """The ready-to-fill input sheet of the File History option:  File No | Applicant Name.
    The software reads it as it is (header words decide the columns; the sheet with the most numbers is used)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "File History"
    ws.sheet_properties.tabColor = T.NAVY
    for i, (title, w) in enumerate((("File No", 30), ("Applicant Name", 44)), 1):
        c = ws.cell(1, i, title)
        c.font, c.fill, c.border = Font(name=FONT, bold=True, color=T.WHITE, size=11), HEAD, BOX
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 24
    for r in range(2, 502):                                  # 500 ready rows; File No is TEXT so leading zeros are never lost
        a, b = ws.cell(r, 1), ws.cell(r, 2)
        a.number_format = "@"
        for c in (a, b):
            c.border, c.font = BOX, Font(name=FONT, size=11, color=T.TEXT)
    ws.freeze_panes = "A2"
    g = wb.create_sheet("How to fill")
    g.sheet_view.showGridLines = False
    g.column_dimensions["A"].width = 120
    lines = [
        ("File History - how to fill the first sheet", True),
        ("", False),
        ("1. Column A (File No): the full file number, for example the letters CC or PL, a dash and the long number - OR only the last digits of the number.", False),
        ("2. Column B (Applicant Name): the applicant's name. It is optional - the file is found by the File No; the name is shown in the report and checked against the dashboard.", False),
        ("3. One file per row. Do not leave the header row out and do not add other columns in front of these two.", False),
        ("4. Open the software > Report type: File History > choose this Excel > Create history.", False),
        ("5. The result is one Excel: Summary (with Applicant Name (given) + Name Check), Timeline, Submission History, Trips, Appointments, Re-CPV & Extra, Concerns, Not Found.", False),
        ("6. Name Check: Matches = the same person; Matches Guarantor / Co-Applicant = the name belongs to another concern of the file; Different = the file's applicant is another name (shown beside it).", False),
        ("7. If the number matches nothing the row is shown as File not found - the other files are not affected.", False),
    ]
    for i, (t, bold) in enumerate(lines, 1):
        c = g.cell(i, 1, t)
        c.font = Font(name=FONT, size=13 if bold else 11, bold=bold, color=T.NAVY if bold else T.TEXT)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        g.row_dimensions[i].height = 22 if bold else 32
    from .pagesetup import a4
    a4(wb)
    wb.save(path)
    return path
