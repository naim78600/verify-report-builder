"""Excel workbook builder (openpyxl)."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from . import config
from .collect import CollectResult
from .model import file_trips

_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
DT_FMT = "yyyy-mm-dd hh:mm"

NAVY = "1F3864"
FILE_FILL = PatternFill("solid", fgColor=NAVY)
CONCERN_FILL = PatternFill("solid", fgColor="DCE6F5")
APPT_FILL = PatternFill("solid", fgColor="F3F3F3")
HEADER_FILL = PatternFill("solid", fgColor="2F5597")
THIN = Side(style="thin", color="D0D0D0")
BORDER = Border(bottom=THIN)

FILE_STATUS_COLOR = {
    "Created": "E4DCF2", "On Going": "CFE0F7", "Hold": "FBDCC0", "Finished": "CDEFD0",
    "Canceled": "CBD5E1", "Submitted": "BFE9E4", "Partially Submitted": "FFD9B3", "Withdrawn": "DDDDDD",
}
TRIP_STATUS_COLOR = {
    "Created": "E4DCF2", "Allocated": "D6E6F7", "Started": "B9D3F2", "Hold": "FBDCC0",
    "Finished": "CDEFD0", "Canceled": "CBD5E1", "Inactive": "D9D9D9", "Withdrawn": "C4C4C4",
}


# ----------------------------------------------------------------------------- helpers
def _clean(v):
    if isinstance(v, str):
        return _ILLEGAL.sub("", v)
    return v


def put(ws, row, col, value, *, fmt=None, fill=None, font=None, align=None, formula=False):
    cell = ws.cell(row=row, column=col)
    value = _clean(value)
    cell.value = value
    if isinstance(value, str) and not formula:
        cell.data_type = "s"            # never treat user text such as "=..." as a formula
    if fmt:
        cell.number_format = fmt
    elif isinstance(value, datetime):
        cell.number_format = DT_FMT
    if fill:
        cell.fill = fill
    if font:
        cell.font = font
    if align:
        cell.alignment = align
    return cell


def _widths(ws, widths):
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _header(ws, row, titles):
    for i, t in enumerate(titles, 1):
        put(ws, row, i, t, fill=HEADER_FILL, font=Font(bold=True, color="FFFFFF"),
            align=Alignment(horizontal="center", vertical="center", wrap_text=True))
    ws.row_dimensions[row].height = 32


def _table(ws, name, ncols, nrows):
    if nrows < 1:
        return
    ref = f"A1:{get_column_letter(ncols)}{nrows + 1}"
    t = Table(displayName=name, ref=ref)
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)
    ws.freeze_panes = "A2"


def _status_cell_fill(table, status):
    c = table.get(status)
    return PatternFill("solid", fgColor=c) if c else None


# ----------------------------------------------------------------------------- File Report
FR_COLS = [
    ("Level", 15), ("File No", 24), ("ID / Task Id", 12), ("Name / Type", 30), ("Role / Designation", 32),
    ("Phone / Verifier", 20), ("Status", 18), ("Assigned By", 16), ("Address", 40),
    ("Exact Address / Place", 40), ("Address Check", 13), ("Created", 16), ("Start", 16),
    ("End", 16), ("SLA / Appt. Time", 16), ("Short Remarks", 38), ("Full Remarks", 55),
    ("Comment / Reason", 40), ("Total Concerns", 10), ("Total Trips", 10),
]
C = {name: i for i, (name, _) in enumerate(FR_COLS, 1)}


def _file_report(wb, res: CollectResult):
    ws = wb.create_sheet("File Report")
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "1:1"
    ws.sheet_properties.outlinePr.summaryBelow = False
    ws.sheet_properties.outlinePr.summaryRight = False
    _header(ws, 1, [n for n, _ in FR_COLS])
    _widths(ws, [w for _, w in FR_COLS])
    wrap = Alignment(wrap_text=True, vertical="top")
    top = Alignment(vertical="top")
    white_bold = Font(bold=True, color="FFFFFF")

    r = 2
    tot_c = tot_t = tot_a = 0
    for f in res.files:
        n_c = len(f["concerns"])
        n_t = sum(len(c["trips"]) for c in f["concerns"])
        tot_c += n_c
        tot_t += n_t
        # file header row ---------------------------------------------------
        vals = {
            "Level": "FILE", "File No": f["file_no"], "ID / Task Id": f["id"], "Name / Type": f["type"],
            "Role / Designation": f["org"], "Phone / Verifier": f["station"], "Status": f["status"],
            "Assigned By": f["assigned_by"], "Start": f["start_date"], "SLA / Appt. Time": f["sla"],
            "Total Concerns": n_c, "Total Trips": n_t,
        }
        for col in range(1, len(FR_COLS) + 1):
            put(ws, r, col, None, fill=FILE_FILL, font=white_bold)
        for k, v in vals.items():
            put(ws, r, C[k], v, fill=FILE_FILL, font=white_bold)
        ws.row_dimensions[r].outlineLevel = 0
        r += 1
        for ev in getattr(res, "recpv_events", {}).get(f["id"], []):      # v2: Re-CPV / Extra under the file
            ev_fill = PatternFill("solid", fgColor="FCE4D6" if ev["kind"] == "Re-CPV" else "E4DFEC")
            for col in range(1, len(FR_COLS) + 1):
                put(ws, r, col, None, fill=ev_fill)
            put(ws, r, C["Level"], "  " + ev["kind"].upper(), fill=ev_fill, font=Font(bold=True))
            put(ws, r, C["File No"], f["file_no"], fill=ev_fill)
            put(ws, r, C["ID / Task Id"], ev["trip_id"], fill=ev_fill)
            put(ws, r, C["Name / Type"], ev.get("trip_type") or ev["kind"], fill=ev_fill, font=Font(bold=True))
            put(ws, r, C["Created"], ev["at"], fill=ev_fill)
            put(ws, r, C["Comment / Reason"], ev["reason"], fill=ev_fill, align=Alignment(wrap_text=True, vertical="top"))
            ws.row_dimensions[r].outlineLevel = 1
            r += 1
        for c in f["concerns"]:
            for col in range(1, len(FR_COLS) + 1):
                put(ws, r, col, None, fill=CONCERN_FILL)
            put(ws, r, C["Level"], "  CONCERN", fill=CONCERN_FILL, font=Font(bold=True))
            put(ws, r, C["File No"], f["file_no"], fill=CONCERN_FILL)
            put(ws, r, C["ID / Task Id"], c["id"], fill=CONCERN_FILL)
            put(ws, r, C["Name / Type"], c["name"], fill=CONCERN_FILL, font=Font(bold=True))
            put(ws, r, C["Role / Designation"],
                f'{c["role"]} · {c["designation"]}' if c["designation"] else c["role"], fill=CONCERN_FILL)
            put(ws, r, C["Phone / Verifier"], c["phone"], fill=CONCERN_FILL)
            put(ws, r, C["Total Trips"], len(c["trips"]), fill=CONCERN_FILL)
            ws.row_dimensions[r].outlineLevel = 1
            r += 1
            for t in c["trips"]:
                tfill = _status_cell_fill(TRIP_STATUS_COLOR, t["status"])
                tag = getattr(res, "trip_tags", {}).get(t["id"])
                put(ws, r, C["Level"], "    TRIP" + (f" · {tag}" if tag else ""), align=top,
                    fill=PatternFill("solid", fgColor="FFF2E5") if tag else None)
                put(ws, r, C["File No"], f["file_no"], align=top)
                put(ws, r, C["ID / Task Id"], t["id"], align=top)
                put(ws, r, C["Name / Type"], t["type"], align=top)
                put(ws, r, C["Role / Designation"], c["name"], align=top)
                put(ws, r, C["Phone / Verifier"], t["verifier"], align=top)
                put(ws, r, C["Status"], t["status"], fill=tfill, align=top)
                put(ws, r, C["Assigned By"], t["assigned_by"], align=top)
                put(ws, r, C["Address"], t["address"], align=wrap)
                place = t["exact_address"]
                if t["place_name"]:
                    place = f'{t["place_name"]} | {place}' if place else t["place_name"]
                put(ws, r, C["Exact Address / Place"], place, align=wrap)
                chk = "" if t["address_exact"] is None else ("সঠিক" if t["address_exact"] else "অসঠিক")
                put(ws, r, C["Address Check"], chk, align=top)
                put(ws, r, C["Created"], t["created_at"], align=top)
                put(ws, r, C["Start"], t["start_time"], align=top)
                put(ws, r, C["End"], t["end_time"], align=top)
                put(ws, r, C["Short Remarks"], t["short_remarks"], align=wrap)
                put(ws, r, C["Full Remarks"], t["remarks"], align=wrap)
                put(ws, r, C["Comment / Reason"], t["comment"], align=wrap)
                ws.row_dimensions[r].outlineLevel = 2
                r += 1
                for a in t["appointments"]:
                    tot_a += 1
                    for col in range(1, len(FR_COLS) + 1):
                        put(ws, r, col, None, fill=APPT_FILL)
                    grey = Font(italic=True, color="555555")
                    put(ws, r, C["Level"], "      APPT", fill=APPT_FILL, font=grey)
                    put(ws, r, C["File No"], f["file_no"], fill=APPT_FILL, font=grey)
                    put(ws, r, C["ID / Task Id"], a["task_id"], fill=APPT_FILL, font=grey)
                    put(ws, r, C["Name / Type"], a["type"], fill=APPT_FILL, font=grey)
                    put(ws, r, C["Status"], "Active" if a["active"] else "Inactive", fill=APPT_FILL, font=grey)
                    put(ws, r, C["Created"], a["created_at"], fill=APPT_FILL, font=grey)
                    put(ws, r, C["SLA / Appt. Time"], a["time"], fill=APPT_FILL, font=grey)
                    put(ws, r, C["Comment / Reason"], a["reason"], fill=APPT_FILL, font=grey,
                        align=Alignment(wrap_text=True, vertical="top"))
                    ws.row_dimensions[r].outlineLevel = 3
                    r += 1
    last_data = r - 1
    # grand total ------------------------------------------------------------
    r += 1
    gt = PatternFill("solid", fgColor="FFF2CC")
    bold = Font(bold=True)
    for col in range(1, len(FR_COLS) + 1):
        put(ws, r, col, None, fill=gt, font=bold)
    put(ws, r, C["Level"], "GRAND TOTAL", fill=gt, font=bold)
    put(ws, r, C["File No"], f"{len(res.files)} files", fill=gt, font=bold)
    put(ws, r, C["Name / Type"], f"Concerns: {tot_c}   Trips: {tot_t}   Appointments: {tot_a}", fill=gt, font=bold)
    put(ws, r, C["Total Concerns"], tot_c, fill=gt, font=bold)
    put(ws, r, C["Total Trips"], tot_t, fill=gt, font=bold)
    for (cell,) in ws.iter_rows(min_row=2, max_row=last_data, min_col=3, max_col=3):
        cell.alignment = Alignment(horizontal="left", vertical="top")
    ws.freeze_panes = "C2"
    if last_data >= 2:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(FR_COLS))}{last_data}"
    ws.sheet_view.zoomScale = 90
    return tot_c, tot_t, tot_a


# ----------------------------------------------------------------------------- status sheets
def _status_sheet(wb, title, order, counts: Counter, colors):
    ws = wb.create_sheet(title)
    _header(ws, 1, ["Status", "Count", "Share %"])
    total = sum(counts.values()) or 1
    keys = list(order) + [k for k in counts if k not in order]
    r = 2
    for k in keys:
        put(ws, r, 1, k, fill=_status_cell_fill(colors, k))
        put(ws, r, 2, counts.get(k, 0))
        put(ws, r, 3, counts.get(k, 0) / total, fmt="0.0%")
        r += 1
    put(ws, r, 1, "Total", font=Font(bold=True))
    put(ws, r, 2, f"=SUM(B2:B{r - 1})", font=Font(bold=True), formula=True)
    _widths(ws, [26, 10, 10])
    return r - 2  # number of status rows (excludes header and total)


# ----------------------------------------------------------------------------- data sheets
def _data_sheets(wb, res: CollectResult):
    ws = wb.create_sheet("Files")
    cols = ["File No", "File ID", "Type", "Status", "Organization", "Station", "Start Date", "SLA",
            "Assigned By (ID)", "Concerns", "Trips", "Appointments"]
    _header(ws, 1, cols)
    for i, f in enumerate(res.files, 2):
        n_t = sum(len(c["trips"]) for c in f["concerns"])
        n_a = sum(len(t["appointments"]) for _, t in file_trips(f))
        for j, v in enumerate([f["file_no"], f["id"], f["type"], f["status"], f["org"], f["station"],
                               f["start_date"], f["sla"], f["assigned_by"], len(f["concerns"]), n_t, n_a], 1):
            put(ws, i, j, v)
    _widths(ws, [24, 10, 10, 18, 20, 14, 17, 17, 14, 10, 8, 13])
    _table(ws, "tblFiles", len(cols), len(res.files))

    ws = wb.create_sheet("Concerns")
    cols = ["File No", "Concern ID", "Name", "Role", "Designation", "Phone", "Trips"]
    _header(ws, 1, cols)
    i = 2
    for f in res.files:
        for c in f["concerns"]:
            for j, v in enumerate([f["file_no"], c["id"], c["name"], c["role"], c["designation"], c["phone"],
                                   len(c["trips"])], 1):
                put(ws, i, j, v)
            i += 1
    _widths(ws, [24, 11, 30, 14, 24, 15, 8])
    _table(ws, "tblConcerns", len(cols), i - 2)

    ws = wb.create_sheet("Trips")
    cols = ["File No", "Concern ID", "Concern", "Concern Role", "Trip ID", "Trip Type", "Status", "Verifier",
            "Assigned By", "Address Check", "Address", "Exact Address", "Place Name", "Area", "Created", "Start",
            "End", "Verified", "Re-CPV / Extra", "Short Remarks", "Full Remarks", "Comment", "Appointments"]
    _header(ws, 1, cols)
    i = 2
    for f in res.files:
        for c, t in file_trips(f):
            chk = "" if t["address_exact"] is None else ("সঠিক" if t["address_exact"] else "অসঠিক")
            row = [f["file_no"], c["id"], c["name"], c["role"], t["id"], t["type"], t["status"], t["verifier"],
                   t["assigned_by"], chk, t["address"], t["exact_address"], t["place_name"], t["area"],
                   t["created_at"], t["start_time"], t["end_time"], "Yes" if t["is_verified"] else "No",
                   getattr(res, "trip_tags", {}).get(t["id"]) or ("Re-CPV" if t["re_cpv"] else "No"), t["short_remarks"], t["remarks"], t["comment"],
                   len(t["appointments"])]
            for j, v in enumerate(row, 1):
                put(ws, i, j, v)
            i += 1
    _widths(ws, [24, 11, 28, 14, 10, 16, 12, 18, 16, 12, 40, 40, 24, 20, 16, 16, 16, 9, 8, 36, 50, 36, 12])
    _table(ws, "tblTrips", len(cols), i - 2)

    ws = wb.create_sheet("Appointments")
    cols = ["File No", "Trip ID (Task Id)", "Appointment ID", "Appointment Time", "Type", "Reason", "Active",
            "Created"]
    _header(ws, 1, cols)
    i = 2
    for f in res.files:
        for _, t in file_trips(f):
            for a in t["appointments"]:
                for j, v in enumerate([f["file_no"], a["task_id"], a["id"], a["time"], a["type"], a["reason"],
                                       "Yes" if a["active"] else "No", a["created_at"]], 1):
                    put(ws, i, j, v)
                i += 1
    _widths(ws, [24, 14, 14, 17, 12, 60, 8, 17])
    _table(ws, "tblAppointments", len(cols), i - 2)


# ----------------------------------------------------------------------------- summary
def _summary(wb, res: CollectResult, totals, nfs_rows, nts_rows, trip_types_rows):
    ws = wb["Executive Summary"]
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 3
    for col, w in zip("BCDEFGHIJKLMN", [30, 16, 4, 30, 16, 4, 30, 16, 4, 14, 14, 14, 14]):
        ws.column_dimensions[col].width = w
    put(ws, 2, 2, "ফাইল রিপোর্ট – Executive Summary", font=Font(size=18, bold=True, color=NAVY))
    meta = [
        ("সংস্থা", res.org_name),
        ("সার্ভার", res.server_label),
        ("সময়কাল", f"{res.date_from:%d %b %Y} – {res.date_till:%d %b %Y}"),
        ("তৈরির সময়", f"{res.generated_at:%d %b %Y, %H:%M}"),
    ]
    for i, (k, v) in enumerate(meta):
        put(ws, 3 + i, 2, k, font=Font(color="666666"))
        put(ws, 3 + i, 3, v, font=Font(bold=True))
    tot_c, tot_t, tot_a = totals
    kpis = [
        ("মোট ফাইল (সাইটের হিসাব)", res.site_total),
        ("সংগৃহীত ফাইল", len(res.files)),
        ("ব্যর্থ ফাইল", len(res.failed)),
        ("মোট কনসার্ন", tot_c),
        ("মোট ট্রিপ", tot_t),
        ("মোট অ্যাপয়েন্টমেন্ট", tot_a),
    ]
    r0 = 8
    for i, (label, val) in enumerate(kpis):
        col = 2 + (i % 3) * 3
        row = r0 + (i // 3) * 3
        fill = PatternFill("solid", fgColor="EAF0FA" if label != "ব্যর্থ ফাইল" or val == 0 else "FBD5D5")
        put(ws, row, col, label, font=Font(color="555555", size=10), fill=fill)
        put(ws, row + 1, col, val, font=Font(size=22, bold=True, color=NAVY), fill=fill,
            align=Alignment(horizontal="left"))
        put(ws, row, col + 1, None, fill=fill)
        put(ws, row + 1, col + 1, None, fill=fill)
        ws.row_dimensions[row + 1].height = 34
    note_row = r0 + 6
    if res.site_total != len(res.files):
        put(ws, note_row, 2,
            f"লক্ষ্য করুন: সাইটের মোট {res.site_total}, সংগৃহীত {len(res.files)}, ব্যর্থ {len(res.failed)} (বিস্তারিত 'Failed Files' শিটে)।",
            font=Font(bold=True, color="C00000"))
    else:
        put(ws, note_row, 2, "✔ সংগৃহীত ফাইলের সংখ্যা সাইটের মোট ফাইলের সাথে মিলেছে।", font=Font(bold=True, color="2E7D32"))
    for n in res.notes:
        note_row += 1
        put(ws, note_row, 2, n, font=Font(color="C00000"))

    def chart(sheet, nrows, title, anchor, color):
        src = wb[sheet]
        ch = BarChart()
        ch.type = "col"
        ch.title = title
        ch.style = 10
        ch.legend = None
        ch.height, ch.width = 8.5, 15
        ch.add_data(Reference(src, min_col=2, min_row=1, max_row=nrows + 1), titles_from_data=True)
        ch.set_categories(Reference(src, min_col=1, min_row=2, max_row=nrows + 1))
        ch.dataLabels = DataLabelList()
        ch.dataLabels.showVal = True
        ch.dataLabels.showSerName = False
        ch.dataLabels.showCatName = False
        ch.dataLabels.showLegendKey = False
        ch.dataLabels.showPercent = False
        ch.series[0].graphicalProperties.solidFill = color
        ws.add_chart(ch, anchor)

    base = note_row + 2
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    chart("File Status", nfs_rows, "ফাইল স্ট্যাটাস", f"B{base}", "2F5597")
    chart("Trip Status", nts_rows, "ট্রিপ স্ট্যাটাস", f"H{base}", "548235")
    chart("Trip Types", trip_types_rows, "ট্রিপের ধরন", f"B{base + 18}", "C55A11")


def _failed_sheet(wb, res: CollectResult):
    ws = wb.create_sheet("Failed Files")
    _header(ws, 1, ["File No", "File ID", "Reason"])
    for i, f in enumerate(res.failed, 2):
        put(ws, i, 1, f["file_no"])
        put(ws, i, 2, f["id"])
        put(ws, i, 3, f["reason"])
    _widths(ws, [26, 12, 90])


# ----------------------------------------------------------------------------- entry
def build_workbook(res: CollectResult, path: Path, extra_sheets=None) -> Path:
    wb = Workbook()
    wb.active.title = "Executive Summary"
    totals = _file_report(wb, res)

    fs = Counter(f["status"] for f in res.files)
    ts = Counter(t["status"] for f in res.files for _, t in file_trips(f))
    tt = Counter(t["type"] for f in res.files for _, t in file_trips(f))
    n_fs = _status_sheet(wb, "File Status", list(config.FILE_STATUS.values()), fs, FILE_STATUS_COLOR)
    n_ts = _status_sheet(wb, "Trip Status", list(config.TRIP_STATUS.values()), ts, TRIP_STATUS_COLOR)
    n_tt = _status_sheet(wb, "Trip Types", sorted(tt, key=lambda k: -tt[k]), tt, {})
    _data_sheets(wb, res)
    if res.failed:
        _failed_sheet(wb, res)
    _summary(wb, res, totals, n_fs, n_ts, max(n_tt, 1))

    if extra_sheets:
        extra_sheets(wb)
    # sheet order
    order = ["Executive Summary", "File Report", "File Status", "Trip Status", "Trip Types", "Files", "Concerns",
             "Trips", "Appointments", "Failed Files", "Billing Rows", "Calculation"]
    wb._sheets = [wb[n] for n in order if n in wb.sheetnames]
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
