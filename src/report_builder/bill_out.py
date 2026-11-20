"""Monthly bill outputs (v6): one Excel workbook and one PDF per bill (Card, Loan), in the layout of the invoice the bank knows.

Excel  -  Invoice (live formulas) | Details (every billed row) | Penalty (Apply = Yes / No) | Check
PDF    -  page 1 the invoice, then one list per section (SL, Ref. No., Applicants Name, Rec. Date, Sub. Date, TAT, Amount, Category);
          a row that carries a penalty is highlighted, as on the hand-made invoice.
`read_bill_excel` reads a (hand-edited) workbook back, so the PDF can be made again with the user's penalty choices.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from . import theme as T
from .monthly_bill import (ADDRESS, IN_NAME, ORG_TO, OUT_NAME, PAY_TO, PENALTY_MAX, PENALTY_PCT, SECTIONS, VAT_PCT, Bill, Item, MonthBill,
                           bill_ref, file_stem, in_words, month_name)
from .mushak import mushak_stem, write_mushak_pdf
from .signature import bundled_logo as logo_path
from .summary import xml_safe

FONT = "Calibri"
THIN = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HILITE = "FFFF00"
DET_COLS = [("Section Key", 11), ("SL", 5), ("Station", 8), ("Section", 46), ("Ref. No.", 24), ("Applicants Name", 30), ("Rec. Date", 12),
            ("Sub. Date", 12), ("TAT", 6), ("Extra TAT", 9), ("Amount", 9), ("Category", 16), ("Bill Slab", 34), ("Trip ID(s)", 16),
            ("Trip Status", 14), ("Note", 44)]
PEN_COLS = [("Item No", 8), ("Ref. No.", 24), ("Applicants Name", 30), ("Station", 8), ("Group", 10), ("Section", 46), ("Rec. Date", 12),
            ("Sub. Date", 12), ("TAT", 6), ("Extra TAT", 9), ("Amount", 9), ("Penalty %", 10), ("Deduction", 11), ("Apply", 8)]


def _station(area: str) -> str:
    return IN_NAME if area == "In" else OUT_NAME


def _sec_title(bill: Bill, key: str, detail: bool = False) -> str:
    for k, _st, title, det in SECTIONS[bill.file_type]:
        if k == key:
            return det if detail else title
    return key


def _ordered(bill: Bill) -> list:
    order = {k: n for n, (k, *_r) in enumerate(SECTIONS[bill.file_type])}
    return sorted(bill.items, key=lambda i: (order.get(i.section, 99), i.rec or date.min, i.file_no))


def _cell(ws, r, c, v, bold=False, align="left", size=11, border=True, fill=None, fmt=None, wrap=False):
    x = ws.cell(r, c)
    x.value = xml_safe(v) if isinstance(v, str) else v
    x.font = Font(name=FONT, bold=bold, size=size)
    x.alignment = Alignment(horizontal=align, vertical="center", wrap_text=wrap)
    if border:
        x.border = BOX
    if fill:
        x.fill = PatternFill("solid", fgColor=fill)
    if fmt:
        x.number_format = fmt
    return x


def _details(wb: Workbook, bill: Bill) -> tuple[dict, list]:
    ws = wb.create_sheet("Details")
    for i, (t, w) in enumerate(DET_COLS, 1):
        _cell(ws, 1, i, t, bold=True, align="center", fill="D9E1F2", wrap=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    items = _ordered(bill)
    sl: dict = {}
    for n, it in enumerate(items, 2):
        sl[it.section] = sl.get(it.section, 0) + 1
        vals = [it.section, sl[it.section], it.area, _sec_title(bill, it.section), it.file_no, it.applicant, it.rec, it.sub, it.tat, it.extra_tat,
                it.amount, it.category, it.slab, it.trip_ids, it.trip_status, it.note]
        for c, v in enumerate(vals, 1):
            x = _cell(ws, n, c, v, align="center" if c in (1, 2, 3, 7, 8, 9, 10, 11) else "left",
                      fmt="dd/mm/yyyy" if c in (7, 8) else None)
            if it.pct:
                x.fill = PatternFill("solid", fgColor=HILITE)
    ws.freeze_panes = "E2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(DET_COLS))}{max(len(items) + 1, 2)}"
    return {id(it): n for n, it in enumerate(items, 2)}, items


def _penalty(wb: Workbook, bill: Bill, rowno: dict, items: list) -> int:
    ws = wb.create_sheet("Penalty")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(PEN_COLS))
    _cell(ws, 1, 1, "Every row with an Extra TAT.  Extra TAT 1 = 20 %, 2 = 30 %, 3 or more = 50 % of the amount.  Apply starts as Yes for a "
                    "submitted package / bank statement and as No for the other rows - change Yes / No freely, the Invoice sheet follows at once.",
          size=10, border=False)
    _cell(ws, 2, len(PEN_COLS) + 1, "Why (starting choice)", bold=True, align="center", fill="D9E1F2", wrap=True)
    ws.column_dimensions[get_column_letter(len(PEN_COLS) + 1)].width = 60
    for i, (t, w) in enumerate(PEN_COLS, 1):
        _cell(ws, 2, i, t, bold=True, align="center", fill="D9E1F2", wrap=True)
        ws.column_dimensions[get_column_letter(i)].width = w
    r = 3
    for it in items:
        if not it.pct:
            continue
        vals = [rowno[id(it)], it.file_no, it.applicant, it.area, "Package" if it.cls == "Package" else "Single", _sec_title(bill, it.section),
                it.rec, it.sub, it.tat, it.extra_tat, it.amount, it.pct, None, "Yes" if it.apply else "No"]
        for c, v in enumerate(vals, 1):
            _cell(ws, r, c, v, align="left" if c in (2, 3, 6) else "center", fmt="dd/mm/yyyy" if c in (7, 8) else None)
        _cell(ws, r, len(PEN_COLS) + 1, it.pen_note, align="left", size=9)
        ws.cell(r, 13).value = f"=K{r}*L{r}/100"
        ws.cell(r, 14).fill = PatternFill("solid", fgColor="FFF2CC")
        r += 1
    last = max(r - 1, 3)
    dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"N3:N{last + 200}")
    ws.freeze_panes = "C3"
    return last


def _invoice(wb: Workbook, bill: Bill, pen_last: int) -> None:
    ws = wb.active
    ws.title = "Invoice"
    ws.sheet_view.showGridLines = False
    for col, w in zip("ABCDE", (30, 52, 9, 12, 16)):
        ws.column_dimensions[col].width = w
    ws.merge_cells("A1:E1")
    _cell(ws, 1, 1, bill.title, bold=True, align="center", size=13, border=False)
    ws.merge_cells("A2:C2")
    _cell(ws, 2, 1, f"Ref: {bill_ref(bill.year, bill.month)}", border=False)
    ws.merge_cells("D2:E2")
    _cell(ws, 2, 4, f"Date: {bill.bill_date:%B %d, %Y}", border=False, align="right")
    for n, line in enumerate(ORG_TO, 3):
        ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=5)
        _cell(ws, n, 1, line, border=False)
    r = 6
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
    _cell(ws, r, 1, bill.title, bold=True, align="center")
    for c in range(2, 6):
        ws.cell(r, c).border = BOX
    r += 1
    for c, t in enumerate(("Station", "Verification Type", "Qty", "Unit Price", "Amount(BDT)"), 1):
        _cell(ws, r, c, t, bold=True, align="center")
    r += 1
    first = r
    lines = bill.lines()
    for key, station, title, _qty, unit, _amt in lines:
        _cell(ws, r, 1, _station(station), align="center", wrap=True)
        _cell(ws, r, 2, title, align="center", wrap=True)
        _cell(ws, r, 3, f'=COUNTIF(Details!$A:$A,"{key}")', align="center")
        _cell(ws, r, 4, unit, align="center")
        _cell(ws, r, 5, f"=C{r}*D{r}", align="center")
        ws.row_dimensions[r].height = 32
        r += 1
    for station in ("In", "Out"):                       # one merged station cell per block, like the paper invoice
        idx = [first + n for n, ln in enumerate(lines) if ln[1] == station]
        if len(idx) > 1:
            ws.merge_cells(start_row=idx[0], start_column=1, end_row=idx[-1], end_column=1)
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
    _cell(ws, r, 1, "Subtotal Before Penalty", bold=True, align="center")
    ws.cell(r, 2).border = BOX
    _cell(ws, r, 3, f"=SUM(C{first}:C{r - 1})", bold=True, align="center")
    _cell(ws, r, 4, None)
    _cell(ws, r, 5, f"=SUM(E{first}:E{r - 1})", bold=True, align="center")
    sub_row = r
    r += 1
    ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
    _cell(ws, r, 1, "Penalty Calculation\n(deduct this amount from the Sub-total Before the Penalty)", bold=True, align="center", wrap=True)
    for c in range(2, 6):
        ws.cell(r, c).border = BOX
    ws.row_dimensions[r].height = 32
    r += 1
    for c, t in enumerate(("Station", "Verification Type", "Qty", "Penalty %", "Deduction Amount(BDT)"), 1):
        _cell(ws, r, c, t, bold=True, align="center", wrap=True)
    r += 1
    pfirst = r
    groups = []
    for station in ("In", "Out"):
        for grp, title in (("Package", f"{'Card' if bill.file_type == 'Card' else 'Loan'} ({station} Station)"),
                           ("Single", f"Single Trips / ReCpv ({station} Station)")):
            for pct in sorted(set(PENALTY_PCT.values()) | {PENALTY_MAX}):
                if any(i.area == station and ("Package" if i.cls == "Package" else "Single") == grp and i.pct == pct for i in bill.items):
                    groups.append((station, grp, title, pct))
    rng = lambda col: f"Penalty!${col}$3:${col}${pen_last}"            # noqa: E731
    for station, grp, title, pct in groups:
        cond = f'{rng("D")},"{station}",{rng("E")},"{grp}",{rng("L")},{pct},{rng("N")},"Yes"'
        _cell(ws, r, 1, _station(station), align="center", wrap=True)
        _cell(ws, r, 2, title, align="center")
        _cell(ws, r, 3, f"=COUNTIFS({cond})", align="center")
        _cell(ws, r, 4, f"{pct}%", align="center")
        _cell(ws, r, 5, f"=SUMIFS({rng('M')},{cond})", align="center")
        ws.row_dimensions[r].height = 30
        r += 1
    if not groups:
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        _cell(ws, r, 1, "No row with an Extra TAT this month.", align="center")
        for c in range(2, 6):
            ws.cell(r, c).border = BOX
        r += 1

    def total(label, formula, bold=True):
        nonlocal r
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        _cell(ws, r, 1, label, bold=bold, align="center")
        for c in range(2, 5):
            ws.cell(r, c).border = BOX
        _cell(ws, r, 5, formula, bold=True, align="center")
        r += 1
        return r - 1

    ded = total("Total Deduction Amount", f"=SUM(E{pfirst}:E{r - 1})" if groups else 0)
    aft = total("Subtotal After Penalty Deduction", f"=E{sub_row}-E{ded}")
    vat = total(f"* Digital Platform Based CPV (IT Enabled)          VAT({VAT_PCT}%)*", f"=ROUND(E{aft}*{VAT_PCT}/100,2)", bold=False)
    total("Grand-Total", f"=E{aft}+E{vat}")
    r += 1
    _cell(ws, r, 1, "In words: printed on the PDF (it is made from this workbook, with the penalty choices of the Penalty sheet).",
          size=9, border=False)
    r += 1
    for n, line in enumerate(PAY_TO):
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=5)
        _cell(ws, r, 1, line, bold=n in (0, 1, 2), border=False)
        r += 1
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def _check(wb: Workbook, mb: MonthBill, bill: Bill) -> None:
    ws = wb.create_sheet("Check")
    for col, w in zip("ABC", (30, 58, 80)):
        ws.column_dimensions[col].width = w
    _cell(ws, 1, 1, f"Check - {month_name(mb.month)} {mb.year} (both bills together)", bold=True, size=12, border=False)
    st = mb.stats
    r = 3
    rows = [("Bill rows created in the month (dashboard)", st.get("rows_in_month")),
            ("On the Card bill", len(mb.bills["Card"].items)), ("On the Loan bill", len(mb.bills["Loan"].items)),
            ("Left out (listed below, with the reason)", st.get("excluded")),
            ("Card + Loan + left out", f"=B{r + 1}+B{r + 2}+B{r + 3}"),
            ("Files that have a row in the month", st.get("files_in_month")),
            ("New files created in the month on the dashboard", st.get("dashboard_files_created")),
            ("Trips created in the month on the dashboard", st.get("dashboard_trips_created")),
            ("Trips inside the rows of the month", st.get("trips_in_month"))]
    for label, v in rows:
        _cell(ws, r, 1, label)
        _cell(ws, r, 2, v, align="center")
        r += 1
    _cell(ws, r, 1, "Result", bold=True)
    ok = st.get("rows_in_month") == st.get("billed", 0) + st.get("excluded", 0)
    _cell(ws, r, 2, "OK - every row of the month is on a bill or on the left-out list" if ok else "CHECK - the numbers do not add up",
          bold=True, fill="C6EFCE" if ok else "FFC7CE")
    r += 2
    for title, data, heads in (("Left out of the bill", mb.excluded, ("File No", "Row", "Reason")),
                               ("Billed - please have a look", mb.review, ("File No", "Row", "Note"))):
        _cell(ws, r, 1, f"{title} ({len(data)})", bold=True, size=12, border=False)
        r += 1
        for c, h in enumerate(heads, 1):
            _cell(ws, r, c, h, bold=True, fill="D9E1F2")
        r += 1
        for fno, what, why in data:
            _cell(ws, r, 1, fno)
            _cell(ws, r, 2, what, wrap=True)
            _cell(ws, r, 3, why, wrap=True)
            r += 1
        r += 1


def write_bill_excel(mb: MonthBill, bill: Bill, path: Path) -> Path:
    wb = Workbook()
    rowno, items = None, None
    ws0 = wb.active
    rowno, items = _details(wb, bill)
    pen_last = _penalty(wb, bill, rowno, items)
    _invoice(wb, bill, pen_last)
    _check(wb, mb, bill)
    wb._sheets = [ws0] + [s for s in wb._sheets if s is not ws0]
    wb.active = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    from .pagesetup import a4
    a4(wb, portrait=("Invoice",))            # the invoice stays a portrait A4 letter; the lists are landscape
    wb.save(path)
    return path


def read_bill_excel(path: Path) -> Bill:
    """A (hand-edited) bill workbook -> Bill, with the Apply = Yes / No choices of the Penalty sheet."""
    import re
    wb = load_workbook(path, data_only=False)
    inv, det, pen = wb["Invoice"], wb["Details"], wb["Penalty"]
    title = str(inv["A1"].value or "")
    m = re.match(r"Verification Bill For (\w+) (\d{4}) - (Card|Loan)", title)
    if not m:
        raise ValueError("This is not a bill workbook made by Verify Report Builder (the title on the Invoice sheet is missing).")
    import calendar
    month = list(calendar.month_name).index(m.group(1))
    bdate = date.today()
    dm = re.search(r"Date: (\w+ \d{1,2}, \d{4})", str(inv["D2"].value or ""))
    if dm:
        bdate = datetime.strptime(dm.group(1), "%B %d, %Y").date()
    bill = Bill(year=int(m.group(2)), month=month, file_type=m.group(3), bill_date=bdate)

    def d_(v):
        return v.date() if isinstance(v, datetime) else v

    by_row: dict = {}
    for r in range(2, det.max_row + 1):
        v = [det.cell(r, c).value for c in range(1, len(DET_COLS) + 1)]
        if not v[0] or not v[4]:
            continue
        it = Item(file_type=bill.file_type, section=str(v[0]), area=str(v[2] or "In"), file_no=str(v[4]), applicant=str(v[5] or ""),
                  rec=d_(v[6]), sub=d_(v[7]), tat=v[8], extra_tat=int(v[9] or 0), amount=int(v[10] or 0), category=str(v[11] or ""),
                  slab=str(v[12] or ""), trip_ids=str(v[13] or ""), trip_status=str(v[14] or ""), note=str(v[15] or ""))
        it.cls = "Package" if it.section.endswith("pkg") else ("house" if it.section == "in_single" else it.section.split("_")[1])
        bill.items.append(it)
        by_row[r] = it
    for r in range(3, pen.max_row + 1):
        no = pen.cell(r, 1).value
        it = by_row.get(int(no)) if isinstance(no, (int, float)) else None
        if it is None:
            continue
        it.pct = int(pen.cell(r, 12).value or 0)
        it.apply = str(pen.cell(r, 14).value or "Yes").strip().lower() != "no"
    return bill


# ------------------------------------------------------------------------------------------------- PDF
def write_bill_pdf(bill: Bill, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .prime_pdf import _fonts, _safe
    _fonts()
    base = ParagraphStyle("b", fontName="Vera", fontSize=9, leading=11.5)
    cen = ParagraphStyle("c", parent=base, alignment=1)
    bold = ParagraphStyle("bb", parent=base, fontName="Vera-Bold")
    cenb = ParagraphStyle("cb", parent=cen, fontName="Vera-Bold")
    small = ParagraphStyle("s", parent=cen, fontSize=8.2, leading=10)
    W = A4[0] - 30 * mm
    logo = logo_path()

    def P(t, st=cen):
        return Paragraph(escape(_safe(t)).replace("\n", "<br/>"), st)

    def on_page(cv, doc):
        cv.saveState()
        top = A4[1] - 12 * mm
        try:
            if logo and Path(logo).exists():
                from reportlab.lib.utils import ImageReader
                img = ImageReader(str(logo))
                iw, ih = img.getSize()
                h = 27 * mm                                # the logo as large as on the manual invoice
                w = h * iw / ih
                cv.drawImage(img, (A4[0] - w) / 2, top - h, w, h, mask="auto")
        except Exception:                                  # noqa: BLE001 - the bill is still right without the logo
            pass
        cv.setFont("Vera-Bold", 8.5)
        cv.drawCentredString(A4[0] / 2, top - 31 * mm, ADDRESS[0])
        cv.drawCentredString(A4[0] / 2, top - 35 * mm, ADDRESS[1])
        cv.setLineWidth(0.5)
        cv.setStrokeColorRGB(0.55, 0.55, 0.55)
        cv.line(15 * mm, top - 39 * mm, A4[0] - 15 * mm, top - 39 * mm)
        cv.setFont("Vera", 7.5)
        cv.drawCentredString(A4[0] / 2, 8 * mm, f"Page {doc.page}")
        cv.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=54 * mm, bottomMargin=14 * mm,
                            title=bill.title, author="Barikoi Technologies Limited")
    grid = [("GRID", (0, 0), (-1, -1), 0.7, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    story = [Paragraph(f"<u>{escape(bill.title)}</u>", cenb), Spacer(1, 2)]
    head = Table([[P(f"Ref: {bill_ref(bill.year, bill.month)}", base), P(f"Date: {bill.bill_date:%B %d, %Y}", ParagraphStyle('r', parent=base, alignment=2))]],
                 colWidths=[W * 0.62, W * 0.38])
    story += [head] + [P(x, base) for x in ORG_TO]
    cw = [W * 0.25, W * 0.37, W * 0.08, W * 0.13, W * 0.17]
    data = [[P(bill.title, cenb), "", "", "", ""], [P(h, cenb) for h in ("Station", "Verification Type", "Qty", "Unit Price", "Amount(BDT)")]]
    style = list(grid) + [("SPAN", (0, 0), (-1, 0))]
    lines = bill.lines()
    for _key, station, title, qty, unit, amt in lines:
        data.append([P(_station(station)), P(title), P(qty), P(unit), P(amt)])
    for station in ("In", "Out"):
        idx = [2 + n for n, ln in enumerate(lines) if ln[1] == station]
        if len(idx) > 1:
            style.append(("SPAN", (0, idx[0]), (0, idx[-1])))
    n = len(data)
    data.append([P("Subtotal Before Penalty", cenb), "", P(len(bill.items), cenb), "", P(_num(bill.subtotal), cenb)])
    style.append(("SPAN", (0, n), (1, n)))
    n += 1
    data.append([P("Penalty Calculation\n(deduct this amount from the Sub-total Before the Penalty)", cenb), "", "", "", ""])
    style.append(("SPAN", (0, n), (-1, n)))
    data.append([P(h, cenb) for h in ("Station", "Verification Type", "Qty", "Penalty %", "Deduction Amount(BDT)")])
    pl = bill.penalty_lines()
    first = len(data)
    for station, title, pct, qty, dedn in pl:
        data.append([P(_station(station)), P(title), P(qty), P(f"{pct}%"), P(_num(dedn))])
    for col, keyf in ((0, lambda x: x[0]), (1, lambda x: (x[0], x[1]))):      # one Station / Verification Type cell per group, as on the manual invoice
        i = 0
        while i < len(pl):
            j = i
            while j + 1 < len(pl) and keyf(pl[j + 1]) == keyf(pl[i]):
                j += 1
            if j > i:
                style.append(("SPAN", (col, first + i), (col, first + j)))
            i = j + 1
    if not pl:
        data.append([P("No penalty."), "", "", "", ""])
        style.append(("SPAN", (0, len(data) - 1), (-1, len(data) - 1)))
    for label, val, b in (("Total Deduction Amount", bill.deduction, True), ("Subtotal After Penalty Deduction", bill.after_penalty, True),
                          (f"* Digital Platform Based CPV (IT Enabled)          VAT({VAT_PCT}%)*", bill.vat, False),
                          ("Grand-Total", bill.grand_total, True)):
        data.append([P(label, cenb if b else cen), "", "", "", P(_num(val), cenb)])
        style.append(("SPAN", (0, len(data) - 1), (3, len(data) - 1)))
    if len(data) > 22:                                     # many penalty lines: the whole summary still has to be ONE page
        style += [("TOPPADDING", (0, 0), (-1, -1), 2.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2)]
    t = Table(data, colWidths=cw)
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 3), Paragraph(f"<b>In words</b>: {escape(in_words(bill.grand_total))}", base)]
    for i, line in enumerate(PAY_TO):
        story.append(P(line, bold if i < 3 else base))

    # detail lists ---------------------------------------------------------------------------------
    dw = [W * 0.05, W * 0.225, W * 0.25, W * 0.115, W * 0.115, W * 0.055, W * 0.085, W * 0.105]
    small = ParagraphStyle("d", parent=cen, fontSize=7.8, leading=9.6)           # a 22-character file number stays on one line
    dhead = ParagraphStyle("dh", parent=cenb, fontSize=7.8, leading=9.6)
    period = f"{month_name(bill.month)} {bill.year}"
    order = [k for k, *_r in SECTIONS[bill.file_type]]
    items = _ordered(bill)
    for key in order:
        rows = [i for i in items if i.section == key]
        if not rows:
            continue
        station = "In" if key.startswith("in_") else "Out"
        story += [PageBreak(), P(f"Contact Point Verification Bill - ({period}) - {bill.file_type}", cenb), P(_station(station), cenb),
                  P(_sec_title(bill, key, detail=True), cenb), Spacer(1, 3)]
        data = [[P(h, dhead) for h in ("SL.", "Ref. No.", "Applicants Name", "Rec. Date", "Sub. Date", "TAT", "Amount", "Category")]]
        style = list(grid) + [("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                              ("TOPPADDING", (0, 0), (-1, -1), 6.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6.6)]       # 25 rows a page, as on the manual invoice
        for n, it in enumerate(rows, 1):
            data.append([P(n, small), P(it.file_no, small), P(it.applicant, small), P(f"{it.rec:%d/%m/%Y}" if it.rec else "", small),
                         P(f"{it.sub:%d/%m/%Y}" if it.sub else "", small), P("" if it.tat is None else it.tat, small), P(it.amount, small),
                         P(it.category, small)])
            if it.pct and it.apply:
                style.append(("BACKGROUND", (1, n), (5, n), colors.HexColor("#" + HILITE)))
        data.append([P("Total", cenb), "", P(len(rows), cenb), "", "", "", P(_num(sum(i.amount for i in rows)), cenb), ""])
        style.append(("SPAN", (0, len(data) - 1), (1, len(data) - 1)))
        t = Table(data, colWidths=dw, repeatRows=1)
        t.setStyle(TableStyle(style))
        story.append(t)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return path


def _num(v) -> str:
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else f"{v:.2f}".rstrip("0").rstrip(".")


def write_month_bill(mb: MonthBill, out_dir: Path, excel: bool = True, pdf: bool = True, mushak: bool = True) -> list[Path]:
    paths: list[Path] = []
    for ft in ("Card", "Loan"):
        bill = mb.bills[ft]
        if excel:
            paths.append(write_bill_excel(mb, bill, out_dir / f"{file_stem(bill)}.xlsx"))
        if pdf:
            paths.append(write_bill_pdf(bill, out_dir / f"{file_stem(bill)}.pdf"))
        if mushak:                                    # V15: the Mushak-6.3 of the same bill
            paths.append(write_mushak_pdf(bill, out_dir / f"{mushak_stem(bill)}.pdf"))
    return paths


ATTACH_DIR = "Bill Attachments"


def bill_attachments(out_dir: Path) -> list[Path]:
    """V15: files the user keeps in <output folder>/Bill Attachments (tax certificates etc.) go with every bill.
    They stay on the PC only - nothing of them is in the program."""
    folder = Path(out_dir) / ATTACH_DIR
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith((".", "~$")))


def pdf_from_excel(xlsx: Path, out_dir: Path | None = None) -> Path:
    """PDF of an edited bill Excel. V15: the Mushak-6.3 is remade too, so its amounts follow the edits."""
    bill = read_bill_excel(xlsx)
    out = out_dir or xlsx.parent
    write_mushak_pdf(bill, out / f"{mushak_stem(bill)}.pdf")
    return write_bill_pdf(bill, out / f"{file_stem(bill)}.pdf")
