"""Prime Bank Report - Excel (two copies: internal with yellow cells, bank copy clean).

Layout follows the daily e-mail the user already sends: a "Complete Report" table, then an
"Incomplete Report" table. TAT and Extra TAT are LIVE Excel formulas:

    TAT       = MAX(0, NETWORKDAYS.INTL(Receive+1, Submission, "0000110", Holidays))      (Fri + Sat off)
    Extra TAT = MAX(0, TAT - 4) when Area = Out,  MAX(0, TAT - 2) when Area = In          (SLA 4 / 2 working days)
    SLA       = "SLA Breach" when Extra TAT > 0

For an Incomplete row the end date is the report date (running TAT), as in the e-mail.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from . import theme as T
from .billing import SLA_IN, SLA_OUT, before_after
from .collect_prime import PrimeData, title_for
from .excel import _clean
from .report_text import appointment_lines, bill_slab_lines, last_update_lines, plain, summary_lines

YELLOW = PatternFill("solid", fgColor=T.YELLOW)
HEAD = PatternFill("solid", fgColor=T.NAVY)
BAND_OK = PatternFill("solid", fgColor=T.BAND_OK_BG)
BAND_NO = PatternFill("solid", fgColor=T.BAND_NO_BG)
THIN = Side(style="thin", color=T.BORDER)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FONT = "Calibri"

COLS = [  # title, width
    ("SL", 5), ("File No", 24), ("Type", 8), ("Concerns", 42), ("Re-CPV / Extra Trip (ID)", 36),
    ("Bill Slab", 40), ("Area", 8), ("Receive Date", 12), ("Submission Date-Time", 17),
    ("Before / After 3 PM", 12), ("TAT", 6), ("Extra TAT", 8), ("SLA", 12), ("Report Status", 14),
    ("Report Summary", 56), ("Last Update", 46), ("Appointment", 44),
]
COL = {t: i for i, (t, _w) in enumerate(COLS, 1)}
HOLIDAY_RANGE = "Holidays!$A$2:$A$3000"
CENTER_COLS = ("SL", "Type", "Area", "Receive Date", "Submission Date-Time", "Before / After 3 PM", "Report Status", "SLA")

_STYLE = {   # style code -> (bold, colour, size, italic)
    "n": (False, T.TEXT, 10), "b": (True, T.TEXT, 10), "m": (False, T.MUTED, 9), "h": (True, T.NAVY, 8),
    "g": (False, T.POS, 10), "gb": (True, T.POS, 10), "a": (False, T.NEG, 10), "ab": (True, T.NEG, 10),
    "k": (False, T.MUTED, 10),
}


def _rich(lines, kind_color: str | None = None):
    """Lines of (text, style) pairs -> openpyxl rich text."""
    parts = []
    for i, ln in enumerate(lines):
        for j, (text, st) in enumerate(ln):
            bold, color, size = _STYLE.get(st, _STYLE["n"])
            if st == "k" and kind_color:
                color, bold = kind_color, True
            tail = "\n" if (j == len(ln) - 1 and i < len(lines) - 1) else ""
            parts.append(TextBlock(InlineFont(rFont=FONT, b=bold, color="FF" + color, sz=size), text + tail))
    return CellRichText(*parts) if parts else ""


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


def _section(ws, r, title, n, fill, text_color):
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=len(COLS))
    _put(ws, r, 1, f"{title}  ({n})", font=Font(name=FONT, bold=True, size=13, color=text_color),
         fill=fill, alignment=Alignment(horizontal="left", vertical="center", indent=1))
    ws.row_dimensions[r].height = 26


def _header(ws, r):
    for i, (t, _w) in enumerate(COLS, 1):
        _put(ws, r, i, t, font=Font(name=FONT, bold=True, color=T.WHITE, size=10), fill=HEAD, border=BOX,
             alignment=Alignment(horizontal="center", vertical="center", wrap_text=True))
    ws.row_dimensions[r].height = 32


def _write_rows(ws, r0: int, rows, internal: bool, checks: list, section: str) -> int:
    top = Alignment(vertical="top", wrap_text=True)
    mid = Alignment(vertical="top", horizontal="center", wrap_text=True)
    r = r0
    for n, row in enumerate(rows):
        sub = row.submitted
        zebra = PatternFill("solid", fgColor=T.ZEBRA) if n % 2 else None
        concerns = "\n".join(row.concern_lines)
        history = "\n\n".join(row.history_lines)
        slab_l, sum_l, upd_l, app_l = bill_slab_lines(row), summary_lines(row), last_update_lines(row), appointment_lines(row)
        base = {
            "SL": row.sl, "File No": row.file_no, "Type": row.file_type, "Concerns": concerns,
            "Re-CPV / Extra Trip (ID)": history, "Area": row.area,
            "Receive Date": row.receive_dt.date() if row.receive_dt else None,
            "Submission Date-Time": row.submitted_at if sub else "Pending",
            "Before / After 3 PM": before_after(row) if sub else "-",
            "Report Status": row.status + (f"\n({row.status_note})" if row.status_note and not sub else ""),
        }
        for t in COL:
            c = ws.cell(r, COL[t])
            c.border = BOX
            c.alignment = mid if t in CENTER_COLS or t in ("TAT", "Extra TAT") else top
            c.font = Font(name=FONT, size=10, color=T.TEXT)
            if zebra:
                c.fill = zebra
        for t, v in base.items():
            c = _put(ws, r, COL[t], v)
            if t == "Receive Date":
                c.number_format = "dd/mm/yyyy"
            elif t == "Submission Date-Time" and sub:
                c.number_format = "dd/mm/yyyy hh:mm"
        kc = T.KIND_TX.get(row.kind)
        for t, lines in (("Bill Slab", slab_l), ("Report Summary", sum_l), ("Last Update", upd_l), ("Appointment", app_l)):
            cell = ws.cell(r, COL[t])
            cell.value = _rich(lines, kc)
        # live formulas ------------------------------------------------------
        rc = get_column_letter(COL["Receive Date"])
        sc = get_column_letter(COL["Submission Date-Time"])
        tc = get_column_letter(COL["TAT"])
        ec = get_column_letter(COL["Extra TAT"])
        ac = get_column_letter(COL["Area"])
        end = f"INT({sc}{r})" if sub else "ReportDate"
        _put(ws, r, COL["TAT"], f'=MAX(0,NETWORKDAYS.INTL({rc}{r}+1,{end},"0000110",{HOLIDAY_RANGE}))', formula=True)
        _put(ws, r, COL["Extra TAT"], f'=IF({ac}{r}="Out",MAX(0,{tc}{r}-{SLA_OUT}),MAX(0,{tc}{r}-{SLA_IN}))', formula=True)
        _put(ws, r, COL["SLA"], f'=IF({ec}{r}>0,"SLA Breach","Within SLA")', formula=True)
        # look ---------------------------------------------------------------
        ws.cell(r, COL["Bill Slab"]).fill = PatternFill("solid", fgColor=T.KIND_BG.get(row.kind, "FFFFFF"))
        out = row.area == "Out"
        ws.cell(r, COL["Area"]).font = Font(name=FONT, bold=True, color=T.OUT if out else T.IN)
        ws.cell(r, COL["Area"]).fill = PatternFill("solid", fgColor=T.OUT_BG if out else T.IN_BG)
        ws.cell(r, COL["Report Status"]).font = Font(name=FONT, bold=True, color=T.POS if sub else T.NEG)
        ws.cell(r, COL["Report Status"]).fill = PatternFill("solid", fgColor=T.POS_BG if sub else T.NEG_BG)
        ws.cell(r, COL["File No"]).font = Font(name=FONT, bold=True, color=T.NAVY)
        ws.cell(r, COL["Extra TAT"]).font = Font(name=FONT, bold=True, color=T.NEG if (row.extra_tat or 0) > 0 else T.POS)
        ws.cell(r, COL["SLA"]).font = Font(name=FONT, bold=True, color=T.NEG if row.sla_breach else T.POS)
        # yellow (internal copy only) ---------------------------------------
        if internal:
            marks = {"area": "Area", "slab": "Bill Slab", "summary": "Report Summary", "status": "Report Status"}
            for key, reason in row.flags.items():
                col = marks.get(key)
                if col:
                    ws.cell(r, COL[col]).fill = YELLOW
                    checks.append((section, row.sl, row.file_no, col, reason))
            for note in row.info:
                checks.append((section, row.sl, row.file_no, "(info)", note))
            if row.canceled:
                ws.cell(r, COL["Bill Slab"]).fill = YELLOW
        widths = {t: w for t, w in COLS}
        texts = {"Concerns": concerns, "Re-CPV / Extra Trip (ID)": history, "Bill Slab": plain(slab_l),
                 "Report Summary": plain(sum_l), "Last Update": plain(upd_l), "Appointment": plain(app_l)}
        height = max([_lines(v, widths[k]) for k, v in texts.items()] + [2])
        ws.row_dimensions[r].height = min(409, 13.2 * height + 6)
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
    _put(ws, 1, 1, title, font=Font(name=FONT, bold=True, size=18, color=T.NAVY), alignment=Alignment(vertical="center", indent=1))
    ws.row_dimensions[1].height = 32
    _put(ws, 2, 1, "Report Date", font=Font(name=FONT, color=T.MUTED))
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
    c = _put(ws, 2, 3, d.report_date, font=Font(name=FONT, bold=True), alignment=Alignment(horizontal="left"))
    c.number_format = "dd/mm/yyyy"
    ws.merge_cells(start_row=2, start_column=3, end_row=2, end_column=4)
    _put(ws, 2, 5, f"Generated: {d.generated_at:%d/%m/%Y %I:%M %p}", font=Font(name=FONT, color=T.MUTED))
    _put(ws, 2, 6, f"Complete: {len(d.complete)}   Incomplete: {len(d.incomplete)}", font=Font(name=FONT, bold=True, color=T.NAVY))
    _put(ws, 3, 1, f"BS = Bank Statement.   SLA: In area {SLA_IN} working days, Out area {SLA_OUT} working days "
                   f"(Friday, Saturday and government holidays excluded; counted from Receive Date).",
         font=Font(name=FONT, size=9, italic=True, color=T.MUTED))
    wb.defined_names["ReportDate"] = DefinedName("ReportDate", attr_text="'Prime Bank Report'!$C$2")

    checks: list = []
    r = 5
    _section(ws, r, "Complete Report", len(d.complete), BAND_OK, T.BAND_OK_TX)
    _header(ws, r + 1)
    first_data = r + 2
    r = _write_rows(ws, first_data, d.complete, internal, checks, "Complete")
    last_complete = r - 1
    r += 1
    _section(ws, r, "Incomplete Report", len(d.incomplete), BAND_NO, T.BAND_NO_TX)
    _header(ws, r + 1)
    inc_first = r + 2
    r = _write_rows(ws, inc_first, d.incomplete, internal, checks, "Incomplete")

    dv = DataValidation(type="list", formula1='"In,Out"', allow_blank=False)
    ws.add_data_validation(dv)
    for a, b in ((first_data, last_complete), (inc_first, r - 1)):
        if b >= a:
            dv.add(f"{get_column_letter(COL['Area'])}{a}:{get_column_letter(COL['Area'])}{b}")
    ws.freeze_panes = "C7"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "5:6"
    ws.sheet_view.zoomScale = 85

    # ---- Summary -------------------------------------------------------------------
    s = wb.create_sheet("Summary")
    s.sheet_view.showGridLines = False
    s.column_dimensions["A"].width = 40
    for col in "BCD":
        s.column_dimensions[col].width = 14
    _put(s, 1, 1, title, font=Font(name=FONT, bold=True, size=14, color=T.NAVY))

    def head(r, label):
        _put(s, r, 1, label, font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD)
        for j, h in enumerate(("Complete", "Incomplete", "Total"), 2):
            _put(s, r, j, h, font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD, alignment=Alignment(horizontal="center"))

    head(3, "Bill type")
    kinds = [("Package", "Package"), ("Extra Trip (created with the file, 6th trip onward)", "Single"),
             ("Re-CPV", "ReCpv"), ("Extra Document / Extra Trip (added later)", "Extra")]
    r = 4
    for label, k in kinds:
        _put(s, r, 1, label)
        _put(s, r, 2, sum(1 for x in d.complete if x.kind == k), alignment=Alignment(horizontal="center"))
        _put(s, r, 3, sum(1 for x in d.incomplete if x.kind == k), alignment=Alignment(horizontal="center"))
        _put(s, r, 4, f"=B{r}+C{r}", alignment=Alignment(horizontal="center"), formula=True)
        r += 1
    _put(s, r, 1, "Total rows", font=Font(name=FONT, bold=True))
    for j, col in enumerate("BCD", 2):
        _put(s, r, j, f"=SUM({col}4:{col}{r - 1})", font=Font(name=FONT, bold=True), alignment=Alignment(horizontal="center"), formula=True)
    r += 2
    head(r, "Area")
    r += 1
    for area in ("In", "Out"):
        _put(s, r, 1, area)
        _put(s, r, 2, sum(1 for x in d.complete if x.area == area), alignment=Alignment(horizontal="center"))
        _put(s, r, 3, sum(1 for x in d.incomplete if x.area == area), alignment=Alignment(horizontal="center"))
        _put(s, r, 4, f"=B{r}+C{r}", alignment=Alignment(horizontal="center"), formula=True)
        r += 1
    r += 1
    head(r, "SLA")
    r += 1
    for label, flag in (("Within SLA", False), ("SLA Breach", True)):
        _put(s, r, 1, label)
        _put(s, r, 2, sum(1 for x in d.complete if x.sla_breach == flag), alignment=Alignment(horizontal="center"))
        _put(s, r, 3, sum(1 for x in d.incomplete if x.sla_breach == flag), alignment=Alignment(horizontal="center"))
        _put(s, r, 4, f"=B{r}+C{r}", alignment=Alignment(horizontal="center"), formula=True)
        r += 1
    if internal:
        r += 1
        rc = d.recon
        _put(s, r, 1, "Trip count check (internal)", font=Font(name=FONT, bold=True, color=T.NAVY))
        r += 1
        for label, val in (("Trips in all report rows", rc.get("row_trips")), ("Trips in the files", rc.get("file_trips")),
                           ("Match", "Yes" if rc.get("row_trips") == rc.get("file_trips") else "NO - check")):
            _put(s, r, 1, label)
            _put(s, r, 2, val, alignment=Alignment(horizontal="center"))
            r += 1
        for n in d.notes:
            r += 1
            _put(s, r, 1, n, font=Font(name=FONT, color=T.NEG))

    # ---- Holidays ------------------------------------------------------------------
    h = wb.create_sheet("Holidays")
    h.column_dimensions["A"].width = 14
    h.column_dimensions["B"].width = 34
    _put(h, 1, 1, "Date", font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD)
    _put(h, 1, 2, "Holiday", font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD)
    for i, (day, name) in enumerate(sorted(d.holidays.items()), 2):
        c = _put(h, i, 1, datetime(day.year, day.month, day.day))
        c.number_format = "dd/mm/yyyy"
        _put(h, i, 2, name)
    h.freeze_panes = "A2"

    # ---- Check list (internal only) -----------------------------------------------
    if internal:
        k = wb.create_sheet("Check List")
        for i, (t, w) in enumerate((("Report", 12), ("SL", 6), ("File No", 26), ("Column", 18), ("Why (yellow cell / note)", 90)), 1):
            k.column_dimensions[get_column_letter(i)].width = w
            _put(k, 1, i, t, font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD)
        for i, row in enumerate(checks, 2):
            for j, v in enumerate(row, 1):
                _put(k, i, j, v, alignment=Alignment(wrap_text=True, vertical="top"))
        k.freeze_panes = "A2"
        if not checks:
            _put(k, 2, 1, "কোনো হলুদ ঘর নেই।")
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
