"""v10: every Excel the program writes prints on A4 landscape (Naim, 15 Nov 2026: "A4 landscape, no column cut").

`a4(wb)` is called right before each workbook is saved.  Each sheet: A4, landscape, fit all columns to the page width
(as many pages down as needed), narrow margins, centred, "Page x of y" footer.  A sheet that already repeats a header
row keeps it.  Nothing about the cells changes."""
from __future__ import annotations

from openpyxl.worksheet.page import PageMargins

FOOTER = "Barikoi Technologies Limited"


def a4_sheet(ws, portrait: bool = False) -> None:
    ps = ws.page_setup
    ps.paperSize = ws.PAPERSIZE_A4
    ps.orientation = "portrait" if portrait else "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ps.fitToWidth = 1
    ps.fitToHeight = 0
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.45, bottom=0.45, header=0.2, footer=0.2)
    ws.print_options.horizontalCentered = True
    if not ws.oddFooter.right.text and not ws.oddFooter.center.text:
        ws.oddFooter.right.text = "Page &P of &N"
        ws.oddFooter.right.size = 8
    if not ws.oddFooter.left.text:
        ws.oddFooter.left.text = FOOTER
        ws.oddFooter.left.size = 8


def a4(wb, portrait: tuple[str, ...] = ()) -> None:
    for ws in wb.worksheets:
        a4_sheet(ws, portrait=ws.title in portrait)
