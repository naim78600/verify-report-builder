"""V15: Mushak-6.3 (কর চালানপত্র / tax invoice) for the monthly Prime Bank bill.

One page per bill (Card, Loan), in the same layout as the Mushak-6.3 that Accounts fills in by hand.
The form itself (Bangla text, lines) is a fixed template: assets/mushak63_template.pdf
(made from devtools/mushak/template.html). This module only writes the month's values on it.

Filled from the bill:      buyer, buyer BIN, buyer address, issue date, the service line
                           "CPV service Card/Loan (for the month of <Month> <Year>)",
                           value (6) = subtotal after penalty, VAT rate (9) = 5%,
                           VAT (10), total with VAT (11), and the same three in the total row.
Left blank on purpose:     challan number (চালানপত্র নম্বর), issue time, the responsible person's
                           name / designation, signature and seal.  Accounts fills these in and
                           signs / stamps the printed copy, as before.
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from .assets_path import asset
from .monthly_bill import VAT_PCT, Bill, file_stem, month_name

# Buyer (Prime Bank PLC), as written on the Mushak-6.3 that Accounts issues.
BUYER_NAME = "Prime Bank PLC"
BUYER_BIN = "000000309-0002"
BUYER_ADDRESS = ("Simple Tree Anarkali, 89 Plot No. 03,", "Gulshan PS, Dhaka-1212")

TEMPLATE = "mushak63_template.pdf"
PAGE_W_MM, PAGE_H_MM = 210.0, 297.0

# Geometry of the template in mm from the top-left corner (measured from template.html).
_COL = {          # (left, right) of the columns used
    1: (10.1, 18.9), 2: (18.9, 61.5), 6: (105.1, 127.1), 9: (146.2, 153.8), 10: (153.8, 174.5), 11: (174.5, 200.1),
}
_BODY_TOP, _BODY_BOTTOM = 118.2, 236.2
_TOTAL_TOP, _TOTAL_BOTTOM = 236.2, 245.2
_FIELD_X = 55.0                                   # after the ":" of the buyer labels
_ROW_Y = {"name": 56.0, "bin": 63.0, "addr1": 70.0, "addr2": 77.0}
_DATE_X, _DATE_Y = 165.0, 72.0
_BLUE = (0.12, 0.25, 0.61)                        # value colour (as the printed blue fields)


def money(v: float) -> str:
    """73320 -> '73320'; 3128.6 -> '3128.60' (no thousands separator, as written on the form)."""
    v = round(float(v), 2)
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def service_line(bill: Bill) -> str:
    return f"CPV service {bill.file_type} (for the month of {month_name(bill.month)} {bill.year})"


def issue_date_text(d: date | None) -> str:
    d = d or date.today()
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def mushak_values(bill: Bill) -> dict:
    """The numbers that go on the form (also used by the tests)."""
    return {
        "value": round(bill.after_penalty, 2),
        "vat_pct": VAT_PCT,
        "vat": bill.vat,
        "total": bill.grand_total,
    }


def mushak_stem(bill: Bill) -> str:
    return file_stem(bill).replace("_Invoice_", "_Mushak6.3_")


def _overlay(bill: Bill) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    from .prime_pdf import _fonts
    _fonts()

    W, H = PAGE_W_MM * mm, PAGE_H_MM * mm
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setFillColorRGB(*_BLUE)

    def text(x_mm, top_mm, s, size=10.5, font="Vera"):
        c.setFont(font, size)
        c.drawString(x_mm * mm, H - (top_mm + 4.2) * mm, s)

    def right(col, top_mm, bottom_mm, s, size=9.5, font="Vera"):
        l, r = _COL[col]
        c.setFont(font, size)
        y = H - ((top_mm + bottom_mm) / 2 + 1.2) * mm
        c.drawRightString((r - 1.2) * mm, y, s)

    text(_FIELD_X, _ROW_Y["name"], BUYER_NAME)
    text(_FIELD_X, _ROW_Y["bin"], BUYER_BIN)
    text(_FIELD_X, _ROW_Y["addr1"], BUYER_ADDRESS[0])
    text(_FIELD_X, _ROW_Y["addr2"], BUYER_ADDRESS[1])
    text(_DATE_X, _DATE_Y, issue_date_text(bill.bill_date))

    # the one service row, a little below the top of the body
    v = mushak_values(bill)
    row_top = _BODY_TOP + 6
    l, r = _COL[1]
    c.setFont("Vera", 9.5)
    c.drawCentredString((l + r) / 2 * mm, H - (row_top + 4) * mm, "1")
    # description, wrapped to the width of column 2
    from reportlab.pdfbase.pdfmetrics import stringWidth
    l, r = _COL[2]
    width = (r - l - 2.4) * mm
    words, lines, cur = service_line(bill).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if stringWidth(t, "Vera", 9.5) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    for i, ln in enumerate(lines):
        c.drawString((l + 1.2) * mm, H - (row_top + 4 + i * 4.6) * mm, ln)
    num_top, num_bottom = row_top, row_top + 6
    right(6, num_top, num_bottom, money(v["value"]))
    right(9, num_top, num_bottom, f"{v['vat_pct']}%", size=8.5)
    right(10, num_top, num_bottom, money(v["vat"]))
    right(11, num_top, num_bottom, money(v["total"]))

    # total row (সর্বমোট)
    right(6, _TOTAL_TOP, _TOTAL_BOTTOM, money(v["value"]) + "/-", font="Vera-Bold")
    right(10, _TOTAL_TOP, _TOTAL_BOTTOM, money(v["vat"]) + "/-", font="Vera-Bold")
    right(11, _TOTAL_TOP, _TOTAL_BOTTOM, money(v["total"]) + "/-", font="Vera-Bold")

    c.showPage()
    c.save()
    return buf.getvalue()


def write_mushak_pdf(bill: Bill, path: Path) -> Path:
    """Write the Mushak-6.3 of one bill (template + this month's values)."""
    from pypdf import PdfReader, PdfWriter

    tpl = PdfReader(str(asset(TEMPLATE)))
    page = tpl.pages[0]
    page.merge_page(PdfReader(io.BytesIO(_overlay(bill))).pages[0])
    w = PdfWriter()
    w.add_page(page)
    w.add_metadata({"/Title": f"Mushak-6.3 - Prime Bank PLC - {bill.file_type} - {month_name(bill.month)} {bill.year}",
                    "/Author": "Barikoi Technologies Limited"})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        w.write(fh)
    return path
