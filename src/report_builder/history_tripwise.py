"""File History - the trip-wise page (v16 "Design A"): one Excel sheet + one A4 landscape PDF, from history_trips.blocks().

Layout (agreed with Naim 23-11-2026):
  Sl | File no (last digits, full number below, file status) | Applicant | Receive date | Package · SLA · Extra trip |
  Trip type | Trip added (date + Package / Extra Trip n / Re-CPV) | Trip update | Done / Due | Due reason / Done note
  + a 'Report summary: Done-... | Due-...' line under every file, and count tiles on top.
Colours come from theme.py (no red, no yellow).  PDF font: Fira Sans (embedded, assets/fonts); Excel: Calibri.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import theme as T
from .assets_path import asset
from .history_trips import extra_text, sla_text, totals

HEADS = ["Sl", "File no", "Applicant", "Receive date", "Package · SLA · Extra trip", "Trip type", "Trip added",
         "Trip update", "Done / Due", "Due reason / Done note"]
SUB = ("Trip-wise status from the dashboard  ·  Done / Due as per the Report Summary rules of the Daily Submission Tracker  ·  "
       "SLA: In 2, Out 4 working days")
LEGEND = ("Done = finished trip  ·  Due = pending / problem (reason shown)  ·  Negative = done, but the result has a problem (see Report summary)  ·  "
          "In = Dhaka / Chattogram city corporation, Out = everything else")
HOLD_TX, HOLD_BG = T.HILITE, T.HILITE_BG
STATUS = {"Submitted": (T.POS, T.POS_BG), "Partially submitted": (T.NEG, T.NEG_BG), "Hold": (HOLD_TX, HOLD_BG),
          "Cancelled": (T.MUTED, T.PANEL), "Withdrawn": (T.MUTED, T.PANEL), "File not found": (T.MUTED, T.PANEL),
          "Could not read": (T.MUTED, T.PANEL)}
EXTRA_TX = T.KIND_TX.get("Extra", "6D28D9")


def status_colours(s: str) -> tuple[str, str]:
    return STATUS.get(s, (T.OUT, T.OUT_BG))                     # On going / Created / Finished: indigo


def title_of(org: str) -> str:
    return f"{org or 'Organisation'} — File history"


def _tiles(bl):
    t = totals(bl)
    tiles = [("Total files", t["files"], T.NAVY), ("Submitted", t["submitted"], T.POS), ("Partially submitted", t["partial"], T.NEG),
             ("Hold", t["hold"], HOLD_TX), ("Cancelled", t["cancelled"], T.MUTED), ("On going", t["ongoing"], T.OUT),
             ("SLA breach", t["breach"], T.NEG), ("Trips Done / Due", f'{t["done"]} / {t["due"]}', T.NAVY)]
    if t["not_found"]:
        tiles[0] = ("Total files", f'{t["files"]} (+{t["not_found"]} not found)', T.NAVY)
    return tiles


def _file_notes(b) -> list[str]:
    out = []
    if b.get("name_check") and b["name_check"] != "Matches":
        out.append(f'Name given: {b.get("given_name")} ({b["name_check"]})')
    if b.get("match_note") and not b.get("missing"):
        out.append(b["match_note"])
    return out


# ============================================================================================ Excel
FONT = "Calibri"
_thin = Side(style="thin", color=T.BORDER)
_thick = Side(style="medium", color=T.NAVY)
_white = Side(style="thin", color=T.WHITE)


def _f(size=10, bold=False, color=T.TEXT, italic=False):
    return Font(name=FONT, size=size, bold=bold, color=color, italic=italic)


def _if(size=10, b=False, color=T.TEXT):
    return InlineFont(rFont=FONT, sz=size, b=b, color=color)


def _fill(c):
    return PatternFill("solid", fgColor=c)


def add_sheet(wb, bl: list[dict], org: str, when: datetime, index: int = 0):
    ws = wb.create_sheet("File History", index)
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 85
    ws.sheet_properties.tabColor = T.NAVY
    for i, w in enumerate([5, 25, 22, 13, 32, 17, 15, 22, 10, 32], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.merge_cells("A1:G1")
    ws["A1"] = title_of(org)
    ws["A1"].font = _f(16, True, T.NAVY)
    ws.merge_cells("H1:J1")
    ws["H1"] = f"Report date: {when:%d-%b-%Y %H:%M}"
    ws["H1"].font, ws["H1"].alignment = _f(10, color=T.MUTED), Alignment(horizontal="right")
    ws.merge_cells("A2:J2")
    ws["A2"] = SUB
    ws["A2"].font = _f(9, color=T.MUTED, italic=True)
    ws.row_dimensions[1].height = 26
    spans = [(1, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 7), (8, 8), (9, 10)]
    for (k, v, c), (a, b) in zip(_tiles(bl), spans):
        for row, val, font in ((4, v, _f(16, True, c)), (5, k, _f(9, color=T.MUTED))):
            if a != b:
                ws.merge_cells(start_row=row, start_column=a, end_row=row, end_column=b)
            cell = ws.cell(row, a, val)
            cell.font, cell.alignment = font, Alignment(horizontal="center", vertical="center", wrap_text=True)
            for col in range(a, b + 1):
                ws.cell(row, col).fill = _fill(T.PANEL)
                ws.cell(row, col).border = Border(left=_white, right=_white)
    ws.row_dimensions[4].height = ws.row_dimensions[5].height = 26
    H = 7
    for i, h in enumerate(HEADS, 1):
        c = ws.cell(H, i, h)
        c.font, c.fill = _f(10, True, T.WHITE), _fill(T.NAVY)
        c.border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[H].height = 30

    r = H + 1
    for i, b in enumerate(bl, 1):
        sfg, _sbg = status_colours(b["status"])
        start = r
        trips = b["trips"] or [None]
        for k, t in enumerate(trips):
            if k == 0:
                ws.cell(r, 1, i)
                parts = [TextBlock(_if(12, True, T.NAVY), (b.get("short_no") or b.get("file_no") or "") + "\n")]
                if b.get("file_no"):
                    parts.append(TextBlock(_if(8, color=T.MUTED), b["file_no"] + "\n"))
                parts.append(TextBlock(_if(9, True, sfg), b["status"]))
                notes = _file_notes(b)
                if notes:
                    parts.append(TextBlock(_if(8, color=T.NEG), "\n" + "\n".join(notes)))
                ws.cell(r, 2).value = CellRichText(*parts)
                ws.cell(r, 3, b.get("applicant") or b.get("given_name") or "").font = _f(10, True)
                ws.cell(r, 4, b.get("receive", "")).font = _f(10)
                if not b.get("missing"):
                    tat, key = sla_text(b)
                    tc = {"breach": T.NEG, "ok": T.POS}.get(key, T.MUTED)
                    ac = T.IN if b.get("area") == "In" else T.OUT
                    ws.cell(r, 5).value = CellRichText(
                        TextBlock(_if(10), "Package: "), TextBlock(_if(10, True, ac), b.get("area") or "-"),
                        TextBlock(_if(10), f"  ·  SLA {b.get('sla_days') or '-'} days\n"), TextBlock(_if(10, True, tc), tat + "\n"),
                        TextBlock(_if(10), extra_text(b)))
                else:
                    ws.cell(r, 5, b.get("match_note", "")).font = _f(9, color=T.MUTED)
            if t:
                ws.cell(r, 6, t["type"]).font = _f(10, True)
                ws.cell(r, 7).value = CellRichText(TextBlock(_if(10), t["added"] + "\n"),
                                                   TextBlock(_if(8, color=T.MUTED if t["added_as"] == "Package" else EXTRA_TX), t["added_as"]))
                ws.cell(r, 8, t["update"]).font = _f(10)
                rc = T.POS if t["result"] == "Done" else T.NEG if t["result"] == "Due" else T.MUTED
                ws.cell(r, 9, t["result"]).font = _f(10, True, rc)
                ws.cell(r, 10, t["note"] or "–").font = _f(10, t["note"] == "Negative", T.NEG if t["note"] else T.MUTED)
            ws.row_dimensions[r].height = 30 if not t or len(t["note"]) < 34 else 15 * (len(t["note"]) // 30 + 1)
            r += 1
        if not b.get("missing"):
            ws.merge_cells(start_row=r, start_column=6, end_row=r, end_column=10)
            parts = [TextBlock(_if(9, True), "Report summary:  ")]
            if b["status"] in ("Cancelled", "Withdrawn"):
                parts.append(TextBlock(_if(9, color=T.MUTED), b["status"]))
            else:
                parts += [TextBlock(_if(9, color=T.POS), "Done-" + b["summary_done"]), TextBlock(_if(9, color=T.MUTED), "   |   "),
                          TextBlock(_if(9, color=T.NEG), "Due-" + b["summary_due"])]
            ws.cell(r, 6).value = CellRichText(*parts)
            for col in range(6, 11):
                ws.cell(r, col).fill = _fill(T.PANEL)
            text_len = len(b["summary_done"]) + len(b["summary_due"])
            ws.row_dimensions[r].height = max(30, 15 * (text_len // 95 + 1))
            r += 1
        last = r - 1
        for col in range(1, 6):
            if last > start:
                ws.merge_cells(start_row=start, start_column=col, end_row=last, end_column=col)
        for rr in range(start, last + 1):
            for col in range(1, 11):
                cell = ws.cell(rr, col)
                if col == 1:
                    cell.alignment = Alignment(horizontal="center", vertical="top")
                elif col == 9:
                    cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
                else:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(left=_thin, right=_thin, top=_thin, bottom=_thick if rr == last else _thin)
                if i % 2 == 0 and col <= 5:
                    cell.fill = _fill(T.ZEBRA)
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=10)
    ws.cell(r, 1, LEGEND).font = _f(9, color=T.MUTED, italic=True)
    ws.freeze_panes = ws.cell(H + 1, 1)
    ws.print_title_rows = f"{H}:{H}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    ws.page_margins.top = ws.page_margins.bottom = 0.5
    ws.oddFooter.left.text = "Barikoi Technologies"
    ws.oddFooter.right.text = "Page &P of &N"
    return ws


def build_excel(bl: list[dict], path, org: str = "", when: datetime | None = None) -> Path:
    from openpyxl import Workbook
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.title = "File History"
    add_sheet(wb, bl, org, when or datetime.now())
    wb.save(path)
    return path


# ============================================================================================ PDF
_PDF_READY = False


def _pdf_fonts():
    global _PDF_READY
    if _PDF_READY:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    d = asset("fonts")
    for name, f in (("Fira", "FiraSans-Regular"), ("Fira-M", "FiraSans-Medium"), ("Fira-SB", "FiraSans-SemiBold")):
        pdfmetrics.registerFont(TTFont(name, str(d / f"{f}.ttf")))
    pdfmetrics.registerFontFamily("Fira", normal="Fira", bold="Fira-SB", italic="Fira", boldItalic="Fira-SB")
    _PDF_READY = True


def _x(s) -> str:
    return escape(str(s or ""))


def build_pdf(bl: list[dict], path, org: str = "", when: datetime | None = None) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph as P, SimpleDocTemplate, Spacer, Table, TableStyle

    _pdf_fonts()
    when = when or datetime.now()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    C = lambda h: colors.HexColor("#" + h)                    # noqa: E731

    def S(size=8, font="Fira", color=T.TEXT, align=0):
        return ParagraphStyle("s", fontName=font, fontSize=size, textColor=C(color), leading=size * 1.25, alignment=align)

    def chip(text, fg, bg):
        return f'<font backColor="#{bg}" color="#{fg}" name="Fira-M">&nbsp;{_x(text)}&nbsp;</font>'

    W = [w * mm for w in (8, 40, 30, 19, 50, 24, 21, 30, 14, 41)]
    rows = [[P(h, S(7.5, "Fira-M", T.WHITE, 1)) for h in HEADS]]
    style = [("BACKGROUND", (0, 0), (-1, 0), C(T.NAVY)), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
             ("GRID", (0, 0), (-1, -1), 0.4, C(T.BORDER)), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
    r = 1
    for i, b in enumerate(bl, 1):
        sfg, sbg = status_colours(b["status"])
        start = r
        trips = b["trips"] or [None]
        for k, t in enumerate(trips):
            cells = [""] * 10
            if k == 0:
                cells[0] = P(str(i), S(8, align=1))
                fc = [P(_x(b.get("short_no") or b.get("file_no")), S(10, "Fira-SB", T.NAVY))]
                if b.get("file_no"):
                    fc.append(P(_x(b["file_no"]), S(6.8, color=T.MUTED)))
                fc += [Spacer(1, 3), P(chip(b["status"], sfg, sbg), S(7.5))]
                fc += [P(_x(n), S(6.8, color=T.NEG)) for n in _file_notes(b)]
                cells[1] = fc
                cells[2] = P(_x(b.get("applicant") or b.get("given_name")), S(8.5, "Fira-M"))
                cells[3] = P(_x(b.get("receive")), S(8))
                if not b.get("missing"):
                    tat, key = sla_text(b)
                    tc = {"breach": T.NEG, "ok": T.POS}.get(key, T.MUTED)
                    area = b.get("area") or "-"
                    afg, abg = (T.IN, T.IN_BG) if area == "In" else (T.OUT, T.OUT_BG)
                    cells[4] = [P(f'Package: {chip(area, afg, abg)} &nbsp;SLA {b.get("sla_days") or "-"} days', S(8)),
                                P(_x(tat), S(8, "Fira-M", tc)), P(_x(extra_text(b)), S(8))]
                else:
                    cells[4] = P(_x(b.get("match_note")), S(7.5, color=T.MUTED))
            if t:
                cells[5] = P(_x(t["type"]), S(8, "Fira-M"))
                cells[6] = [P(_x(t["added"]), S(8)), P(_x(t["added_as"]), S(6.8, color=T.MUTED if t["added_as"] == "Package" else EXTRA_TX))]
                cells[7] = P(_x(t["update"]), S(8))
                rc = T.POS if t["result"] == "Done" else T.NEG if t["result"] == "Due" else T.MUTED
                cells[8] = P(_x(t["result"]), S(8, "Fira-SB", rc))
                cells[9] = P(_x(t["note"] or "–"), S(8, "Fira-M" if t["note"] == "Negative" else "Fira", T.NEG if t["note"] else T.MUTED))
            rows.append(cells)
            r += 1
        if not b.get("missing"):
            if b["status"] in ("Cancelled", "Withdrawn"):
                body = f'<font color="#{T.MUTED}">{_x(b["status"])}</font>'
            else:
                body = (f'<font color="#{T.POS}">Done-{_x(b["summary_done"])}</font>&nbsp;&nbsp;|&nbsp;&nbsp;'
                        f'<font color="#{T.NEG}">Due-{_x(b["summary_due"])}</font>')
            rows.append(["", "", "", "", "", P(f'<font name="Fira-M">Report summary:</font>&nbsp; {body}', S(7.6)), "", "", "", ""])
            style += [("SPAN", (5, r), (9, r)), ("BACKGROUND", (5, r), (9, r), C(T.PANEL))]
            r += 1
        for c in range(5):
            if r - 1 > start:
                style.append(("SPAN", (c, start), (c, r - 1)))
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, start), (4, r - 1), C(T.ZEBRA)))
        style.append(("LINEBELOW", (0, r - 1), (-1, r - 1), 1.1, C(T.NAVY)))
    table = Table(rows, colWidths=W, repeatRows=1)
    table.setStyle(TableStyle(style))

    tiles = _tiles(bl)
    tt = Table([[[P(_x(v), S(15 if len(str(v)) < 10 else 10, "Fira-SB", c, 1)), P(_x(k), S(7, color=T.MUTED, align=1))] for k, v, c in tiles]],
               colWidths=[277 * mm / 8] * 8)
    tt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), C(T.PANEL)), ("LINEAFTER", (0, 0), (-2, -1), 2, colors.white),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    def page(c, d):
        c.saveState()
        w, h = landscape(A4)
        c.setFillColor(C(T.NAVY))
        c.setFont("Fira-SB", 15)
        c.drawString(10 * mm, h - 14 * mm, title_of(org))
        c.setFont("Fira", 8.5)
        c.setFillColor(C(T.MUTED))
        c.drawString(10 * mm, h - 19 * mm, SUB)
        c.drawRightString(w - 10 * mm, h - 14 * mm, f"Report date: {when:%d-%b-%Y %H:%M}")
        c.setStrokeColor(C(T.NAVY))
        c.setLineWidth(1.2)
        c.line(10 * mm, h - 21.5 * mm, w - 10 * mm, h - 21.5 * mm)
        c.setFont("Fira", 6.8)
        c.drawString(10 * mm, 7 * mm, LEGEND)
        c.drawRightString(w - 10 * mm, 7 * mm, f"Barikoi Technologies  ·  Page {d.page}")
        c.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=25 * mm,
                            bottomMargin=12 * mm, title=title_of(org), author="Verify Report Builder")
    doc.build([tt, Spacer(1, 5 * mm), table], onFirstPage=page, onLaterPages=page)
    return path
