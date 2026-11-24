"""Prime Bank Report - Excel (ONE editable workbook: this is what goes to the bank).

Workbook:   Complete Report | Incomplete Report | Summary | Holidays | (Check List - only when something needs a look)

Each report sheet has: banner, info line, KPI tiles, one header row and the table.  The only filter buttons are on
**File No** and **Last Update Date** (all other columns have their button hidden).
A light sky-blue cell means "no reason / detail could be found for this cell" - fill it in (the file is editable) or leave it.
The Incomplete sheet lists only Hold / Finished-not-submitted / Partially Submitted files (never a running On Going file) and
has a "Pending Reason" column: a Hold with its written reason (and any Appointment), "Finished - not yet submitted", or the
documents named in Due for a Partially Submitted file.

TAT and Extra TAT are LIVE Excel formulas:
    SLA Start / Restart Date = the Receive Date, or - when ANY new trip of the file (Re-CPV, extra / additional, ...) was created -
                               its creation day, or - when an appointment was given - the scheduled date of the latest appointment;
                               the latest of them.
    TAT       = MAX(0, NETWORKDAYS.INTL(SLA Start+1, Submission, "0000110", Holidays))    (Fri + Sat off)
    Extra TAT = MAX(0, TAT - 4) when Area = Out,  MAX(0, TAT - 2) when Area = In          (SLA 4 / 2 working days)
                after an APPOINTMENT (v6): MAX(0, TAT - 1 [+1 when submitted after 5:59 PM]) - due the next working day, In and Out alike
    SLA       = "SLA Breach" when Extra TAT > 0
For an Incomplete row the end date is the report date (running TAT).
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
from .billing import SLA_APPT, SLA_IN, SLA_OUT, before_after
from .collect_prime import PrimeData, title_for
from .excel import _clean
from .summary import xml_safe
from .report_text import english_only
from .report_text import (appointment_lines, bill_slab_lines, has_due, last_update_date, last_update_lines, plain,
                          sla_restart_lines, summary_lines)

CHECK = PatternFill("solid", fgColor=T.CHECK)
HEAD = PatternFill("solid", fgColor=T.NAVY)
PANEL = PatternFill("solid", fgColor=T.PANEL)
THIN = Side(style="thin", color=T.BORDER)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FONT = "Calibri"

COLS = [  # internal title, width - v6 order (20 columns), as the bank reads it; v10 widths = "A4 Classic" (all on one A4 width)
    ("SL", 3.8), ("File No", 17.5), ("Type", 5.2), ("Applicant Name", 12), ("Concerns", 16),
    ("Receive Date", 13.2), ("Submission Date-Time", 13.2), ("Report Status", 9.5), ("Report Summary", 24), ("Last Update Date", 9.8),
    ("Re-CPV / Extra Trip (ID)", 14), ("Bill Slab", 14), ("Area", 4.8), ("SLA Start / Restart Date", 9.8), ("SLA", 8.5),
    ("TAT", 4.3), ("Extra TAT", 5), ("Appointment", 16), ("Last Update Details", 18), ("Before / After 12 PM", 7.5),
]
# what the header cell shows (the internal titles stay, so every other writer keeps working)
SHOWN = {"Type": "File Type", "Concerns": "Concerns Name", "Receive Date": "Receive Date-Time", "Re-CPV / Extra Trip (ID)": "Re-CPV / Extra Trip",
         "Report Summary": "Report Summary (Done / Due)", "Appointment": "Appointment History"}
REASON_COL = ("Pending Reason", 16)


def cols_for(incomplete: bool) -> list:
    """Incomplete sheet = the same columns + "Pending Reason" right after "Report Status"."""
    if not incomplete:
        return list(COLS)
    out = list(COLS)
    out.insert([t for t, _w in out].index("Report Status") + 1, REASON_COL)
    return out


def col_index(cols: list) -> dict:
    return {t: i for i, (t, _w) in enumerate(cols, 1)}


COL = col_index(COLS)
HOLIDAY_RANGE = "Holidays!$A$2:$A$3000"
CENTER_COLS = ("SL", "Type", "Area", "Receive Date", "SLA Start / Restart Date", "Submission Date-Time", "Before / After 12 PM", "Report Status",
               "SLA", "TAT", "Extra TAT", "Last Update Date")
WRAP_REASON = ("Pending Reason",)
HEADER_ROW, FIRST_ROW = 4, 5

_STYLE = {   # style code -> (bold, colour, size)
    "n": (False, T.TEXT, 10), "b": (True, T.TEXT, 10), "m": (False, T.MUTED, 9), "h": (True, T.NAVY, 8),
    "g": (False, T.POS, 10), "gb": (True, T.POS, 10), "a": (False, T.NEG, 10), "ab": (True, T.NEG, 10),
    "k": (False, T.MUTED, 10), "dn": (False, T.NOTE, 10), "hl": (True, T.HILITE, 10), "rs": (True, T.RESTART, 10),
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
            parts.append(TextBlock(InlineFont(rFont=FONT, b=bold, color="FF" + color, sz=size), xml_safe(english_only(text)) + tail))
    return CellRichText(*parts) if parts else ""


def _lines(text: str, width: float) -> int:
    if not text:
        return 1
    return sum(max(1, math.ceil(len(part) / max(width - 1.5, 1))) for part in str(text).split("\n"))


def _put(ws, r, c, v, formula=False, **kw):
    cell = ws.cell(row=r, column=c)
    v = _clean(v)
    v = xml_safe(english_only(v))               # v18.0.3: no Bangla in the bank's tracker
    cell.value = v
    if isinstance(v, str) and not formula:
        cell.data_type = "s"
    for k, val in kw.items():
        setattr(cell, k, val)
    return cell


def _fill(hexv: str) -> PatternFill:
    return PatternFill("solid", fgColor=hexv)


# ------------------------------------------------------------------------------------ banner + tiles
def _tile_spans(n: int, cols: list) -> list[tuple[int, int]]:
    """Split the columns into n groups of about the same width (for the KPI tiles)."""
    widths = [w for _t, w in cols]
    total, out, start = sum(widths), [], 0
    for k in range(1, n + 1):
        target = total * k / n
        end, acc = start, sum(widths[:start])
        while end < len(widths) and (acc < target - widths[end] / 2 or end == start):
            acc += widths[end]
            end += 1
        if k == n:
            end = len(widths)
        out.append((start + 1, end))
        start = end
    return out


def _tiles(ws, r: int, items, cols: list) -> None:
    spans = _tile_spans(len(items), cols)
    for (c1, c2), (label, value, color) in zip(spans, items):
        if c2 > c1:
            ws.merge_cells(start_row=r, start_column=c1, end_row=r, end_column=c2)
        cell = ws.cell(r, c1)
        cell.value = CellRichText(
            TextBlock(InlineFont(rFont=FONT, b=True, color="FF" + T.MUTED, sz=8), label.upper() + "\n"),
            TextBlock(InlineFont(rFont=FONT, b=True, color="FF" + color, sz=16), str(value)))
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        for c in range(c1, c2 + 1):
            x = ws.cell(r, c)
            x.fill = PANEL
            x.border = Border(left=Side(style="thick", color="FFFFFF") if c == c1 else None,
                              right=Side(style="thick", color="FFFFFF") if c == c2 else None,
                              bottom=Side(style="medium", color=color))
    ws.row_dimensions[r].height = 42


def _banner(ws, d: PrimeData, name: str, rows, is_incomplete: bool, cols: list) -> None:
    n = len(cols)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    accent = T.POS if not is_incomplete else T.NEG
    _put(ws, 1, 1, f"{title_for(d)}   ·   {name}  ({len(rows)})",
         font=Font(name=FONT, bold=True, size=16, color=T.WHITE), fill=HEAD,
         alignment=Alignment(vertical="center", indent=1))
    for c in range(2, n + 1):
        ws.cell(1, c).fill = HEAD
    ws.row_dimensions[1].height = 32

    # info line --------------------------------------------------------------------------------
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
    _put(ws, 2, 1, "Report Date", font=Font(name=FONT, bold=True, size=10, color=T.NAVY),
         alignment=Alignment(horizontal="right", vertical="center"))
    ws.merge_cells(start_row=2, start_column=3, end_row=2, end_column=4)
    c = _put(ws, 2, 3, d.report_date, font=Font(name=FONT, bold=True, size=11, color=T.NAVY), fill=_fill(T.PANEL),
             alignment=Alignment(horizontal="center", vertical="center"))
    c.number_format = "dd/mm/yyyy"
    ws.cell(2, 4).fill = _fill(T.PANEL)
    if is_incomplete:
        ws.cell(2, 3).fill = _fill(T.NEG_BG)       # the one date that drives the running TAT of this sheet
        ws.cell(2, 4).fill = _fill(T.NEG_BG)
    else:
        ws.cell(2, 3).value = "=ReportDate"
    note = (f"Generated {d.generated_at:%d/%m/%Y %I:%M %p}   |   BS = Bank Statement   |   SLA: In area {SLA_IN} working days, "
            f"Out area {SLA_OUT} working days (Fri, Sat and holidays excluded), counted from the SLA Start Date = Receive Date; "
            f"any new trip restarts the SLA from its creation day; after an appointment the report is due on the next working day "
            f"after the scheduled date, by 5:59 PM, In and Out alike (plum cell)")
    if is_incomplete:
        note += "   |   TAT is counted up to the Report Date"
    note += "   |   Light-blue cell = reason / detail not found"
    ws.merge_cells(start_row=2, start_column=5, end_row=2, end_column=n)
    _put(ws, 2, 5, note, font=Font(name=FONT, size=9, italic=True, color=T.MUTED),
         alignment=Alignment(vertical="center", indent=1))
    ws.row_dimensions[2].height = 20

    # KPI tiles --------------------------------------------------------------------------------
    pk = sum(1 for x in rows if x.kind == "Package")
    sg = sum(1 for x in rows if x.kind == "Single")
    rc = sum(1 for x in rows if x.kind == "ReCpv")
    ex = sum(1 for x in rows if x.kind == "Extra")
    n_files = len({x.file_no for x in rows})          # v13: unique file numbers (two applications of one File No = one file)
    items = [(("Incomplete" if is_incomplete else "Complete") + f" rows · {n_files} files", len(rows), accent),
             ("Package", pk, T.NAVY), ("Extra Trip", sg, T.NAVY), ("Re-CPV", rc, T.NAVY), ("Extra Doc / Trip", ex, T.NAVY),
             ("Area In", sum(1 for x in rows if x.area == "In"), T.IN), ("Area Out", sum(1 for x in rows if x.area == "Out"), T.OUT),
             ("SLA Breach", sum(1 for x in rows if x.sla_breach), T.NEG)]
    _tiles(ws, 3, items, cols)


def _header(ws, r, cols: list):
    for i, (t, _w) in enumerate(cols, 1):
        _put(ws, r, i, SHOWN.get(t, t), font=Font(name=FONT, bold=True, color=T.WHITE, size=10), fill=_fill(T.NAVY_DARK), border=BOX,
             alignment=Alignment(horizontal="center", vertical="center", wrap_text=True))
    ws.row_dimensions[r].height = 34


# ------------------------------------------------------------------------------------ rows
def _write_rows(ws, r0: int, rows, checks: list, section: str, cols: list) -> int:
    col = col_index(cols)
    top = Alignment(vertical="top", wrap_text=True)
    mid = Alignment(vertical="top", horizontal="center", wrap_text=True)
    widths = {t: w for t, w in cols}
    r = r0
    for n, row in enumerate(rows):
        sub = row.submitted
        zebra = _fill(T.ZEBRA) if n % 2 else None
        concerns = "\n".join(row.file_concern_lines or row.concern_lines)
        history = "\n\n".join(row.history_lines)
        slab_l, sum_l, upd_l, app_l = bill_slab_lines(row), summary_lines(row), last_update_lines(row), appointment_lines(row)
        lu = last_update_date(row)
        base = {
            "SL": row.sl, "File No": row.file_no, "Type": row.file_type, "Applicant Name": row.applicant, "Concerns": concerns,
            "Re-CPV / Extra Trip (ID)": history, "Area": row.area,
            "Receive Date": row.receive_dt if row.receive_dt else None,
            "SLA Start / Restart Date": row.sla_start or (row.receive_dt.date() if row.receive_dt else None),
            "Submission Date-Time": row.reported_at if sub else "Pending",
            "Before / After 12 PM": before_after(row) if sub else "-",
            "Report Status": row.status + (f"\n({row.status_note})" if row.status_note and not sub else "")
                             + (f"\n({row.reopen_note})" if sub and row.reopen_note else ""),
            "Last Update Date": lu.date() if lu else "N/A",
        }
        for t in col:
            c = ws.cell(r, col[t])
            c.border = BOX
            c.alignment = mid if t in CENTER_COLS else top
            c.font = Font(name=FONT, size=10, color=T.TEXT)
            if zebra:
                c.fill = zebra
        for t, v in base.items():
            c = _put(ws, r, col[t], v)
            if t in ("SLA Start / Restart Date", "Last Update Date") and not isinstance(v, str):
                c.number_format = "dd/mm/yyyy"
            elif t == "Receive Date" and v is not None:
                c.number_format = "dd/mm/yyyy hh:mm"
            elif t == "Submission Date-Time" and sub:
                c.number_format = "dd/mm/yyyy hh:mm"
        kc = T.KIND_TX.get(row.kind)
        restart_l = sla_restart_lines(row)
        if restart_l:                                         # the first thing a banker reads in the Appointment cell
            app_l = restart_l + [[("", "n")]] + ([] if app_l == [[("NO", "m")]] else app_l)
        for t, lines in (("Bill Slab", slab_l), ("Report Summary", sum_l), ("Last Update Details", upd_l), ("Appointment", app_l)):
            ws.cell(r, col[t]).value = _rich(lines, kc)
        # live formulas ------------------------------------------------------
        rc = get_column_letter(col["SLA Start / Restart Date"])        # the SLA clock starts here (Receive Date, or the appointment day)
        sc = get_column_letter(col["Submission Date-Time"])
        tc = get_column_letter(col["TAT"])
        ec = get_column_letter(col["Extra TAT"])
        ac = get_column_letter(col["Area"])
        end = f"INT({sc}{r})" if sub else "ReportDate"
        # ======================================================================================================
        # ◆ DASHBOARD-MATCH LOGIC: Excel formulas TAT / Extra TAT / SLA
        #   plain NETWORKDAYS.INTL (no _xlfn.), Holidays sheet filled; Extra TAT by Area or appointment.
        # ======================================================================================================
        _put(ws, r, col["TAT"], f'=MAX(0,NETWORKDAYS.INTL({rc}{r}+1,{end},"0000110",{HOLIDAY_RANGE}))', formula=True)
        if row.sla_appt:                                      # appointment: due the next working day by 5:59 PM, In and Out alike
            late = f'+IF(MOD({sc}{r},1)>=0.75,1,0)' if sub else ""
            _put(ws, r, col["Extra TAT"], f'=MAX(0,{tc}{r}-{SLA_APPT}{late})', formula=True)
        else:
            _put(ws, r, col["Extra TAT"], f'=IF({ac}{r}="Out",MAX(0,{tc}{r}-{SLA_OUT}),MAX(0,{tc}{r}-{SLA_IN}))', formula=True)
        _put(ws, r, col["SLA"], f'=IF({ec}{r}>0,"SLA Breach","Within SLA")', formula=True)
        # look ---------------------------------------------------------------
        ws.cell(r, col["Bill Slab"]).fill = _fill(T.KIND_BG.get(row.kind, "FFFFFF"))
        out = row.area == "Out"
        ws.cell(r, col["Area"]).font = Font(name=FONT, bold=True, color=T.OUT if out else T.IN)
        ws.cell(r, col["Area"]).fill = _fill(T.OUT_BG if out else T.IN_BG)
        reo = sub and bool(row.reopen_note)
        ws.cell(r, col["Report Status"]).font = Font(name=FONT, bold=True, color=T.NEG if reo or not sub else T.POS)
        ws.cell(r, col["Report Status"]).fill = _fill(T.NEG_BG if reo or not sub else T.POS_BG)
        ws.cell(r, col["File No"]).font = Font(name=FONT, bold=True, color=T.NAVY)
        if row.sla_restarted:                                 # restarted (appointment / new trip): plum cell, easy to see
            ws.cell(r, col["SLA Start / Restart Date"]).font = Font(name=FONT, bold=True, color=T.RESTART)
            ws.cell(r, col["SLA Start / Restart Date"]).fill = _fill(T.RESTART_BG)
        ws.cell(r, col["Extra TAT"]).font = Font(name=FONT, bold=True, color=T.NEG if (row.extra_tat or 0) > 0 else T.POS)
        ws.cell(r, col["SLA"]).font = Font(name=FONT, bold=True, color=T.NEG if row.sla_breach else T.POS)
        if has_due(row):
            ws.cell(r, col["Report Summary"]).fill = _fill(T.DUE_CELL_BG)
        # light sky-blue cells: nothing could be found for this cell (kept in the file, listed in the Check List) -----------
        marks = {"area": "Area", "slab": "Bill Slab", "summary": "Report Summary", "status": "Report Status",
                 "reason": "Pending Reason"}
        for key, why in row.flags.items():
            cname = marks.get(key)
            if cname and cname in col:
                ws.cell(r, col[cname]).fill = CHECK
                checks.append((section, row.sl, row.file_no, cname, why))
        for note in row.info:
            checks.append((section, row.sl, row.file_no, "(info)", note))
        if row.canceled:
            ws.cell(r, col["Bill Slab"]).fill = CHECK
        if "Pending Reason" in col and row.reason:
            ws.cell(r, col["Pending Reason"]).value = xml_safe(english_only(row.reason))
        texts = {"Concerns": concerns, "Re-CPV / Extra Trip (ID)": history, "Bill Slab": plain(slab_l),
                 "Report Summary": plain(sum_l), "Last Update Details": plain(upd_l), "Appointment": plain(app_l),
                 "Report Status": base["Report Status"], "Pending Reason": row.reason}
        height = max([_lines(v, widths[k]) for k, v in texts.items() if k in widths] + [2])
        ws.row_dimensions[r].height = min(409, 13.2 * height + 6)
        r += 1
    return r


def _report_sheet(wb: Workbook, d: PrimeData, name: str, rows, checks: list, is_incomplete: bool):
    cols = cols_for(is_incomplete)
    col = col_index(cols)
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    ws.sheet_properties.tabColor = T.NEG if is_incomplete else T.POS
    for i, (_t, w) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    _banner(ws, d, name, rows, is_incomplete, cols)
    _header(ws, HEADER_ROW, cols)
    end = _write_rows(ws, FIRST_ROW, rows, checks, "Incomplete" if is_incomplete else "Complete", cols)
    last = end - 1
    lastcol = get_column_letter(len(cols))
    if not rows:
        ws.merge_cells(start_row=FIRST_ROW, start_column=1, end_row=FIRST_ROW, end_column=len(cols))
        _put(ws, FIRST_ROW, 1, "No incomplete files." if is_incomplete else "No submitted files for this report.",
             font=Font(name=FONT, italic=True, color=T.MUTED), alignment=Alignment(horizontal="center", vertical="center"))
        ws.row_dimensions[FIRST_ROW].height = 28
        last = FIRST_ROW
    else:
        dv = DataValidation(type="list", formula1='"In,Out"', allow_blank=False)
        ws.add_data_validation(dv)
        dv.add(f"{get_column_letter(col['Area'])}{FIRST_ROW}:{get_column_letter(col['Area'])}{last}")
    # v10: a filter button on EVERY column (Naim, 15 Nov 2026) ---------------------------------
    ws.auto_filter.ref = f"A{HEADER_ROW}:{lastcol}{max(last, FIRST_ROW)}"
    ws.freeze_panes = f"C{FIRST_ROW}"
    ws.sheet_view.zoomScale = 75
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{HEADER_ROW}:{HEADER_ROW}"
    ws.oddFooter.center.text = "Page &P of &N"
    ws.oddFooter.center.size = 8
    return ws


# ------------------------------------------------------------------------------------ workbook
def _sum_sheet(wb: Workbook, d: PrimeData) -> None:
    s = wb.create_sheet("Summary")
    s.sheet_view.showGridLines = False
    s.sheet_properties.tabColor = T.NAVY
    s.column_dimensions["A"].width = 52
    for col in "BCD":
        s.column_dimensions[col].width = 14
    s.merge_cells("A1:D1")
    _put(s, 1, 1, title_for(d), font=Font(name=FONT, bold=True, size=15, color=T.WHITE), fill=HEAD,
         alignment=Alignment(vertical="center", indent=1))
    for c in "BCD":
        s[f"{c}1"].fill = HEAD
    s.row_dimensions[1].height = 30
    s.page_setup.fitToWidth = 1
    s.page_setup.fitToHeight = 0
    s.sheet_properties.pageSetUpPr.fitToPage = True
    cen = Alignment(horizontal="center")

    def head(r, label):
        _put(s, r, 1, label, font=Font(name=FONT, bold=True, color=T.WHITE), fill=_fill(T.NAVY_DARK))
        for j, h in enumerate(("Complete", "Incomplete", "Total"), 2):
            _put(s, r, j, h, font=Font(name=FONT, bold=True, color=T.WHITE), fill=_fill(T.NAVY_DARK), alignment=cen)

    def line(r, label, a, b, zebra):
        f = _fill(T.ZEBRA) if zebra else None
        _put(s, r, 1, label, border=BOX, **({"fill": f} if f else {}))
        _put(s, r, 2, a, alignment=cen, border=BOX, **({"fill": f} if f else {}))
        _put(s, r, 3, b, alignment=cen, border=BOX, **({"fill": f} if f else {}))
        _put(s, r, 4, f"=B{r}+C{r}", alignment=cen, formula=True, border=BOX, **({"fill": f} if f else {}))

    head(3, "Bill type")
    kinds = [("Package", "Package"), ("Extra Trip (created with the file, 6th trip onward)", "Single"),
             ("Re-CPV", "ReCpv"), ("Extra Document / Extra Trip (added later)", "Extra")]
    r = 4
    for i, (label, k) in enumerate(kinds):
        line(r, label, sum(1 for x in d.complete if x.kind == k), sum(1 for x in d.incomplete if x.kind == k), i % 2)
        r += 1
    _put(s, r, 1, "Total rows", font=Font(name=FONT, bold=True), border=BOX)
    for j, col in enumerate("BCD", 2):
        _put(s, r, j, f"=SUM({col}4:{col}{r - 1})", font=Font(name=FONT, bold=True), alignment=cen, formula=True, border=BOX)
    r += 2
    head(r, "Area")
    r += 1
    for i, area in enumerate(("In", "Out")):
        line(r, area, sum(1 for x in d.complete if x.area == area), sum(1 for x in d.incomplete if x.area == area), i % 2)
        r += 1
    r += 1
    head(r, "SLA")
    r += 1
    for i, (label, flag) in enumerate((("Within SLA", False), ("SLA Breach", True))):
        line(r, label, sum(1 for x in d.complete if x.sla_breach == flag), sum(1 for x in d.incomplete if x.sla_breach == flag), i % 2)
        r += 1
    line(r, "SLA restarted (appointment / new trip)", sum(1 for x in d.complete if x.sla_restarted), sum(1 for x in d.incomplete if x.sla_restarted), 0)
    r += 1
    ck = (d.dash or {}).get("check")
    if ck:
        r += 1
        _put(s, r, 1, f"Dashboard check  (status Submitted, {ck['from']:%d/%m/%Y} – {ck['till']:%d/%m/%Y})",
             font=Font(name=FONT, bold=True, color=T.WHITE), fill=_fill(T.NAVY_DARK))
        for j in (2, 3, 4):
            s.cell(r, j).fill = _fill(T.NAVY_DARK)
        r += 1
        lines_ = [("Files in the dashboard's Submitted list", ck["dashboard"]), ("Of these, in the Complete Report", ck["matched"])]
        if ck.get("other_phase"):
            lines_.append(("Of these, belong to the other phase's mail", len(ck["other_phase"])))
        lines_ += [("Not matched", len(ck["missing"])), ("Files in Complete Report (all rows)", ck["report_files"])]
        if ck.get("reopened"):
            lines_.append(("Of these, re-opened since (not Submitted on the dashboard now)", len(ck["reopened"])))
        for i, (label, val) in enumerate(lines_):
            line_f = _fill(T.ZEBRA) if i % 2 else None
            _put(s, r, 1, label, border=BOX, **({"fill": line_f} if line_f else {}))
            _put(s, r, 2, val, alignment=cen, border=BOX, **({"fill": line_f} if line_f else {}),
                 font=Font(name=FONT, bold=True, color=T.POS if (label == "Not matched" and val == 0) or label.startswith("Of these, in") and val + len(ck.get("other_phase") or []) == ck["dashboard"] else T.TEXT))
            r += 1
    if d.incomplete and d.mode == "tracker":
        r += 1
        _put(s, r, 1, "Incomplete rows - reason for pending", font=Font(name=FONT, bold=True, color=T.WHITE), fill=_fill(T.NAVY_DARK))
        for j in (2, 3, 4):
            s.cell(r, j).fill = _fill(T.NAVY_DARK)
        _put(s, r, 2, "Rows", font=Font(name=FONT, bold=True, color=T.WHITE), fill=_fill(T.NAVY_DARK), alignment=cen)
        r += 1
        kinds = (("hold", "Hold (comment / appointment written)"), ("finished", "Finished, not yet submitted"),
                 ("partial", "Partially Submitted (documents due)"), ("", "Reason not found (light-blue cell)"))
        for i, (k, label) in enumerate(kinds):
            n = sum(1 for x in d.incomplete if x.reason_kind == k)
            line_f = _fill(T.ZEBRA) if i % 2 else None
            _put(s, r, 1, label, border=BOX, **({"fill": line_f} if line_f else {}))
            _put(s, r, 2, n, alignment=cen, border=BOX, **({"fill": line_f} if line_f else {}),
                 font=Font(name=FONT, bold=True, color=T.NEG if (k == "" and n) else T.TEXT))
            r += 1


def _holidays_sheet(wb: Workbook, d: PrimeData) -> None:
    h = wb.create_sheet("Holidays")
    h.sheet_properties.tabColor = T.MUTED
    h.column_dimensions["A"].width = 14
    h.column_dimensions["B"].width = 34
    _put(h, 1, 1, "Date", font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD)
    _put(h, 1, 2, "Holiday", font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD)
    for i, (day, name) in enumerate(sorted(d.holidays.items()), 2):
        c = _put(h, i, 1, datetime(day.year, day.month, day.day))
        c.number_format = "dd/mm/yyyy"
        _put(h, i, 2, name)
    h.freeze_panes = "A2"


def _check_items(d: PrimeData, checks: list) -> list:
    items = list(checks)
    ck = (d.dash or {}).get("check") or {}
    for no, why in ck.get("missing", []):
        items.append(("Dashboard", "", no, "(not matched)", why))
    # one line per file of the dashboard's Submitted list, so the dashboard number can be tied to the report line by line
    for no, at, where in ck.get("files", []):
        if where.startswith("NOT"):
            continue                                                       # already listed above
        items.append(("Dashboard", "", no, f"Submitted {at:%d/%m/%Y %H:%M}" if at else "Submitted", where))
    for no, why in ck.get("reopened", []):
        items.append(("Dashboard", "", no, "(re-opened)", f"In this report, but the dashboard no longer lists it as Submitted ({why})"))
    for n in d.notes:
        if n.startswith("Incomplete তালিকা:"):                # the standing rule note, not something to check
            continue
        items.append(("Run note", "", "", "", n))
    rc = d.recon or {}
    if rc and rc.get("row_trips") != rc.get("file_trips"):
        items.append(("Trip count", "", "", "", f"Trips in rows {rc.get('row_trips')} / trips in files {rc.get('file_trips')} - please check"))
    for f in d.failed:
        items.append(("Failed file", "", f.get("file_no", ""), "", f.get("reason", "")))
    return items


def _check_sheet(wb: Workbook, items: list) -> None:
    k = wb.create_sheet("Check List")
    k.sheet_properties.tabColor = T.CHECK
    for i, (t, w) in enumerate((("Report", 12), ("SL", 6), ("File No", 26), ("Column", 18), ("Why (light-blue cell / note) - internal, remove before sending", 90)), 1):
        k.column_dimensions[get_column_letter(i)].width = w
        _put(k, 1, i, t, font=Font(name=FONT, bold=True, color=T.WHITE), fill=HEAD)
    for i, row in enumerate(items, 2):
        for j, v in enumerate(row, 1):
            _put(k, i, j, v, alignment=Alignment(wrap_text=True, vertical="top"))
    k.freeze_panes = "A2"


def build_prime_excel(d: PrimeData, path: Path, with_checklist: bool = True) -> Path:
    """-> the workbook.  `with_checklist=False` builds the clean copy (no internal Check List sheet) for e-mailing."""
    wb = Workbook()
    wb.remove(wb.active)
    checks: list = []
    _report_sheet(wb, d, "Complete Report", d.complete, checks, False)
    _report_sheet(wb, d, "Incomplete Report", d.incomplete, checks, True)
    wb.defined_names["ReportDate"] = DefinedName("ReportDate", attr_text="'Incomplete Report'!$C$2")
    _sum_sheet(wb, d)
    _holidays_sheet(wb, d)
    items = _check_items(d, checks)
    if with_checklist and items:
        _check_sheet(wb, items)
    wb.active = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    from .pagesetup import a4
    a4(wb)
    wb.save(path)
    return path


def checklist_count(d: PrimeData) -> int:
    """How many light-blue cells the workbook has (rows whose reason / detail was not found)."""
    n = 0
    for lst in (d.complete, d.incomplete):
        for row in lst:
            n += sum(1 for k in row.flags if k in ("area", "slab", "summary", "status", "reason"))
            n += 1 if row.canceled and "slab" not in row.flags else 0
    return n
