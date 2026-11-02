"""Prime Bank Report - Excel (two copies: internal with yellow cells, bank copy clean).

Layout follows the daily e-mail the user already sends: a "Complete Report" table, then an
"Incomplete Report" table. TAT and Extra TAT are LIVE Excel formulas (same as the tracker):

    TAT       = MAX(0, NETWORKDAYS.INTL(Receive+1, Submission, "0000110", Holidays))
    Extra TAT = MAX(0, TAT - 3) when Area = Out, MAX(0, TAT - 2) when Area = In

For an Incomplete row the end date is the report date (running TAT), as in the e-mail.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from .billing import before_after
from .collect_prime import PrimeData, title_for
from .excel import _clean

NAVY = "1F3864"
YELLOW = PatternFill("solid", fgColor="FFF200")
HEAD = PatternFill("solid", fgColor=NAVY)
BAND_OK = PatternFill("solid", fgColor="E2EFDA")
BAND_NO = PatternFill("solid", fgColor="FCE4D6")
KIND_FILL = {"Package": "DDEBF7", "Single": "EDEDED", "ReCpv": "FCE4D6", "Extra": "E4DFEC"}
THIN = Side(style="thin", color="9A9A9A")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

COLS = [  # title, width
    ("SL", 5), ("File No", 24), ("Type", 8), ("Concerns", 44), ("Re-CPV / Extra Trip (ID)", 38),
    ("Bill Slab", 30), ("Area", 7), ("Receive Date", 12), ("Submission Date-Time", 17),
    ("Before / After 3 PM", 12), ("TAT", 6), ("Extra TAT", 8), ("Report Status", 13), ("Report Summary", 62),
]
COL = {t: i for i, (t, _w) in enumerate(COLS, 1)}
HOLIDAY_RANGE = "Holidays!$A$2:$A$3000"


def _lines(text: str, width: int) -> int:
    if not text:
        return 1
    return sum(max(1, math.ceil(len(part) / max(width - 2, 1))) for part in str(text).split("\n"))


def _put(ws, r, c, v, formula=False, **kw):
    cell = ws.cell(row=r, column=c)
    v = _clean(v)
    cell.value = v
    if isinstance(v, str) and not formula:
        cell.data_type = "s"
    for k, val in kw.items():
        setattr(cell, k, val)
    return cell


def _section(ws, r, title, n, fill):
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(COLS))
    _put(ws, r, 1, f"{title} ({n})", font=Font(bold=True, size=13, color="FFFFFF" if fill is HEAD else "000000"),
         fill=fill, alignment=Alignment(horizontal="left", vertical="center", indent=1))
    ws.row_dimensions[r].height = 24


def _header(ws, r):
    for i, (t, _w) in enumerate(COLS, 1):
        _put(ws, r, i, t, font=Font(bold=True, color="FFFFFF"), fill=HEAD, border=BOX,
             alignment=Alignment(horizontal="center", vertical="center", wrap_text=True))
    ws.row_dimensions[r].height = 30


def _write_rows(ws, r0: int, rows, internal: bool, checks: list, section: str) -> int:
    top = Alignment(vertical="top", wrap_text=True)
    mid = Alignment(vertical="top", horizontal="center", wrap_text=True)
    r = r0
    for row in rows:
        sub = row.submitted
        concerns = "\n".join(row.concern_lines)
        history = "\n\n".join(row.history_lines)
        slab = f"{row.slab}\n{row.category}"
        summary = row.summary.text()
        cells = {
            "SL": row.sl, "File No": row.file_no, "Type": row.file_type, "Concerns": concerns,
            "Re-CPV / Extra Trip (ID)": history, "Bill Slab": slab, "Area": row.area,
            "Receive Date": row.receive_dt.date() if row.receive_dt else None,
            "Submission Date-Time": row.submitted_at if sub else "Pending",
            "Before / After 3 PM": before_after(row) if sub else "-",
            "Report Status": row.status + (f"\n({row.status_note})" if row.status_note and not sub else ""),
            "Report Summary": summary,
        }
        for t, v in cells.items():
            c = _put(ws, r, COL[t], v, border=BOX, alignment=mid if t in ("SL", "Type", "Area", "Receive Date",
                     "Submission Date-Time", "Before / After 3 PM", "Report Status") else top)
            if t == "Receive Date":
                c.number_format = "dd/mm/yyyy"
            elif t == "Submission Date-Time" and sub:
                c.number_format = "dd/mm/yyyy hh:mm"
        # live formulas ------------------------------------------------------
        rc = get_column_letter(COL["Receive Date"])
        sc = get_column_letter(COL["Submission Date-Time"])
        tc = get_column_letter(COL["TAT"])
        ac = get_column_letter(COL["Area"])
        end = f"INT({sc}{r})" if sub else "ReportDate"
        _put(ws, r, COL["TAT"], f'=MAX(0,NETWORKDAYS.INTL({rc}{r}+1,{end},"0000110",{HOLIDAY_RANGE}))',
             border=BOX, alignment=mid, formula=True)
        _put(ws, r, COL["Extra TAT"], f'=IF({ac}{r}="Out",MAX(0,{tc}{r}-3),MAX(0,{tc}{r}-2))', border=BOX, alignment=mid, formula=True)
        # look ---------------------------------------------------------------
        ws.cell(r, COL["Bill Slab"]).fill = PatternFill("solid", fgColor=KIND_FILL.get(row.kind, "FFFFFF"))
        ws.cell(r, COL["Bill Slab"]).font = Font(bold=True)
        ws.cell(r, COL["Area"]).font = Font(bold=True, color="C00000" if row.area == "Out" else "2E7D32")
        ws.cell(r, COL["Report Status"]).font = Font(bold=True, color="2E7D32" if sub else "C00000")
        ws.cell(r, COL["File No"]).font = Font(bold=True)
        # yellow (internal copy only) ---------------------------------------
        if internal:
            marks = {"area": "Area", "slab": "Bill Slab", "summary": "Report Summary", "status": "Report Status"}
            for key, reason in row.flags.items():
                col = marks.get(key)
                if col:
                    ws.cell(r, COL[col]).fill = YELLOW
                    checks.append((section, row.sl, row.file_no, col, reason))
            if row.canceled:
                ws.cell(r, COL["Bill Slab"]).fill = YELLOW
        height = max(_lines(concerns, COLS[COL["Concerns"] - 1][1]), _lines(history, COLS[COL["Re-CPV / Extra Trip (ID)"] - 1][1]),
                     _lines(summary, COLS[COL["Report Summary"] - 1][1]), _lines(slab, COLS[COL["Bill Slab"] - 1][1]), 2)
        ws.row_dimensions[r].height = min(409, 13.5 * height + 4)
        r += 1
    return r


def build_prime_excel(d: PrimeData, path: Path, internal: bool) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Prime Bank Report"
    for i, (_t, w) in enumerate(COLS, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.sheet_view.showGridLines = False
    title = title_for(d)

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLS))
    _put(ws, 1, 1, title, font=Font(bold=True, size=16, color=NAVY), alignment=Alignment(vertical="center", indent=1))
    ws.row_dimensions[1].height = 28
    _put(ws, 2, 1, "Report Date", font=Font(color="666666"))
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
    c = _put(ws, 2, 3, d.report_date, font=Font(bold=True), alignment=Alignment(horizontal="left"))
    c.number_format = "dd/mm/yyyy"
    ws.merge_cells(start_row=2, start_column=3, end_row=2, end_column=4)
    _put(ws, 2, 5, f"Generated: {d.generated_at:%d/%m/%Y %I:%M %p}", font=Font(color="666666"))
    _put(ws, 2, 6, f"Complete: {len(d.complete)}   Incomplete: {len(d.incomplete)}", font=Font(bold=True))
    wb.defined_names["ReportDate"] = DefinedName("ReportDate", attr_text="'Prime Bank Report'!$C$2")

    checks: list = []
    r = 4
    _section(ws, r, "Complete Report", len(d.complete), BAND_OK)
    _header(ws, r + 1)
    first_data = r + 2
    r = _write_rows(ws, first_data, d.complete, internal, checks, "Complete")
    last_complete = r - 1
    r += 1
    _section(ws, r, "Incomplete Report", len(d.incomplete), BAND_NO)
    _header(ws, r + 1)
    inc_first = r + 2
    r = _write_rows(ws, inc_first, d.incomplete, internal, checks, "Incomplete")

    dv = DataValidation(type="list", formula1='"In,Out"', allow_blank=False)
    ws.add_data_validation(dv)
    for a, b in ((first_data, last_complete), (inc_first, r - 1)):
        if b >= a:
            dv.add(f"{get_column_letter(COL['Area'])}{a}:{get_column_letter(COL['Area'])}{b}")
    ws.freeze_panes = "C4"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "4:5"
    ws.sheet_view.zoomScale = 90

    # ---- Summary -------------------------------------------------------------------
    s = wb.create_sheet("Summary")
    s.sheet_view.showGridLines = False
    s.column_dimensions["A"].width = 34
    s.column_dimensions["B"].width = 14
    s.column_dimensions["C"].width = 14
    s.column_dimensions["D"].width = 14
    _put(s, 1, 1, title, font=Font(bold=True, size=14, color=NAVY))
    _put(s, 3, 1, "Bill type", font=Font(bold=True, color="FFFFFF"), fill=HEAD)
    for j, h in enumerate(("Complete", "Incomplete", "Total"), 2):
        _put(s, 3, j, h, font=Font(bold=True, color="FFFFFF"), fill=HEAD, alignment=Alignment(horizontal="center"))
    kinds = [("Package", "Package"), ("Single (same day, 6th+ trip)", "Single"), ("Re-CPV", "ReCpv"), ("Extra", "Extra")]
    r = 4
    for label, k in kinds:
        a = sum(1 for x in d.complete if x.kind == k)
        b = sum(1 for x in d.incomplete if x.kind == k)
        _put(s, r, 1, label)
        _put(s, r, 2, a, alignment=Alignment(horizontal="center"))
        _put(s, r, 3, b, alignment=Alignment(horizontal="center"))
        _put(s, r, 4, f"=B{r}+C{r}", alignment=Alignment(horizontal="center"), formula=True)
        r += 1
    _put(s, r, 1, "Total rows", font=Font(bold=True))
    for j, col in enumerate("BCD", 2):
        _put(s, r, j, f"=SUM({col}4:{col}{r - 1})", font=Font(bold=True), alignment=Alignment(horizontal="center"), formula=True)
    r += 2
    _put(s, r, 1, "Area", font=Font(bold=True, color="FFFFFF"), fill=HEAD)
    for j, h in enumerate(("Complete", "Incomplete", "Total"), 2):
        _put(s, r, j, h, font=Font(bold=True, color="FFFFFF"), fill=HEAD, alignment=Alignment(horizontal="center"))
    r += 1
    for area in ("In", "Out"):
        _put(s, r, 1, area)
        _put(s, r, 2, sum(1 for x in d.complete if x.area == area), alignment=Alignment(horizontal="center"))
        _put(s, r, 3, sum(1 for x in d.incomplete if x.area == area), alignment=Alignment(horizontal="center"))
        _put(s, r, 4, f"=B{r}+C{r}", alignment=Alignment(horizontal="center"), formula=True)
        r += 1
    if internal:
        r += 1
        rc = d.recon
        _put(s, r, 1, "Trip count check (internal)", font=Font(bold=True, color=NAVY))
        r += 1
        for label, val in (("Trips in all billing rows", rc.get("row_trips")), ("Trips in the files", rc.get("file_trips")),
                           ("Match", "Yes" if rc.get("row_trips") == rc.get("file_trips") else "NO - check")):
            _put(s, r, 1, label)
            _put(s, r, 2, val, alignment=Alignment(horizontal="center"))
            r += 1
        for n in d.notes:
            r += 1
            _put(s, r, 1, n, font=Font(color="C00000"))

    # ---- Holidays ------------------------------------------------------------------
    h = wb.create_sheet("Holidays")
    h.column_dimensions["A"].width = 14
    h.column_dimensions["B"].width = 34
    _put(h, 1, 1, "Date", font=Font(bold=True, color="FFFFFF"), fill=HEAD)
    _put(h, 1, 2, "Holiday", font=Font(bold=True, color="FFFFFF"), fill=HEAD)
    for i, (day, name) in enumerate(sorted(d.holidays.items()), 2):
        c = _put(h, i, 1, datetime(day.year, day.month, day.day))
        c.number_format = "dd/mm/yyyy"
        _put(h, i, 2, name)
    h.freeze_panes = "A2"

    # ---- Check list (internal only) -----------------------------------------------
    if internal:
        k = wb.create_sheet("Check List")
        for i, (t, w) in enumerate((("Report", 12), ("SL", 6), ("File No", 26), ("Column", 18), ("Why yellow", 90)), 1):
            k.column_dimensions[get_column_letter(i)].width = w
            _put(k, 1, i, t, font=Font(bold=True, color="FFFFFF"), fill=HEAD)
        for i, row in enumerate(checks, 2):
            for j, v in enumerate(row, 1):
                _put(k, i, j, v, alignment=Alignment(wrap_text=True, vertical="top"))
        k.freeze_panes = "A2"
        if not checks:
            _put(k, 2, 1, "কোনো হলুদ ঘর নেই।")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
