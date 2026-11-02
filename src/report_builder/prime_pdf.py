"""Prime Bank Report - PDF for bankers (reportlab, no other tools needed).

Design goals: simple, same two parts as the daily e-mail (Complete / Incomplete), A4 landscape,
header row repeated on every page, rows never split across pages, status and area shown both
by colour AND by words (still readable on a black-and-white printer), embedded fonts.
"""
from __future__ import annotations

import os
from html import escape
from pathlib import Path

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .billing import before_after
from .collect_prime import PrimeData, title_for

NAVY = colors.HexColor("#1F3864")
GREEN = colors.HexColor("#2E7D32")
RED = colors.HexColor("#C00000")
GREY = colors.HexColor("#666666")
YELLOW = colors.HexColor("#FFF200")
KIND_BG = {"Package": "#DDEBF7", "Single": "#EDEDED", "ReCpv": "#FCE4D6", "Extra": "#E4DFEC"}

_FONT_READY = False
_CMAP: set[int] = set()


def _fonts():
    global _FONT_READY, _CMAP
    if _FONT_READY:
        return
    d = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    pdfmetrics.registerFont(TTFont("Vera", os.path.join(d, "Vera.ttf")))
    pdfmetrics.registerFont(TTFont("Vera-Bold", os.path.join(d, "VeraBd.ttf")))
    pdfmetrics.registerFont(TTFont("Vera-Italic", os.path.join(d, "VeraIt.ttf")))
    pdfmetrics.registerFontFamily("Vera", normal="Vera", bold="Vera-Bold", italic="Vera-Italic", boldItalic="Vera-Bold")
    _CMAP = set(pdfmetrics.getFont("Vera").face.charToGlyph.keys())
    _FONT_READY = True


def _safe(text) -> str:
    """Keep only characters the embedded font has (Bengali etc. would show as boxes)."""
    out = []
    for ch in ("" if text is None else str(text)):
        out.append(ch if (ord(ch) in _CMAP or ch in "\n") else "?")
    return "".join(out)


def _p(text, style, color: str | None = None) -> Paragraph:
    t = escape(_safe(text)).replace("\n", "<br/>")
    if color:
        t = f'<font color="{color}">{t}</font>'
    return Paragraph(t, style)


class _NumberedCanvas(rl_canvas.Canvas):
    """Two-pass canvas: 'Page x of y'."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._saved = []

    def showPage(self):
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._saved)
        for st in self._saved:
            self.__dict__.update(st)
            self.setFont("Vera", 7)
            self.setFillColor(GREY)
            w, _h = self._pagesize
            self.drawRightString(w - 10 * mm, 6 * mm, f"Page {self._pageNumber} of {n}")
            super().showPage()
        super().save()


def build_prime_pdf(d: PrimeData, path: Path, internal: bool) -> Path:
    _fonts()
    title = title_for(d)
    page = landscape(A4)
    left = right = 8 * mm
    usable = page[0] - left - right
    base = ParagraphStyle("b", fontName="Vera", fontSize=6.9, leading=8.6)
    bold = ParagraphStyle("bb", parent=base, fontName="Vera-Bold")
    center = ParagraphStyle("c", parent=base, alignment=1)
    head = ParagraphStyle("h", parent=base, fontName="Vera-Bold", textColor=colors.white, alignment=1, fontSize=7)
    small = ParagraphStyle("s", parent=base, fontSize=6.2, leading=7.6, textColor=GREY)

    widths_mm = [7, 31, 45, 30, 29, 9, 16, 21, 8, 9, 22, 48]
    scale = usable / (sum(widths_mm) * mm)
    widths = [w * mm * scale for w in widths_mm]
    heads = ["SL", "File No", "Concerns", "Re-CPV / Extra Trip (ID)", "Bill Slab", "Area", "Receive Date",
             "Submission Date-Time", "TAT", "Extra TAT", "Report Status", "Report Summary"]

    def table_for(rows) -> Table:
        data = [[Paragraph(h, head) for h in heads]]
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9A9A9A")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2.5), ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for i, r in enumerate(rows, 1):
            sub = r.submitted
            if sub:
                when = f"{r.submitted_at:%d/%m/%Y}\n{r.submitted_at:%I:%M %p}\n({before_after(r)})"
            else:
                when = "Pending"
            status_color = "#2E7D32" if sub else "#C00000"
            status = r.status + (f"\n({r.status_note})" if r.status_note and not sub else "")
            summ = r.summary
            summary_par = Paragraph(
                f'<font color="#2E7D32"><b>Done-</b>{escape(_safe(summ.done))}</font><br/>'
                f'<font color="{"#C00000" if summ.due != "0" else "#2E7D32"}"><b>Due-</b>{escape(_safe(summ.due))}</font>', base)
            slab = Paragraph(f"<b>{escape(_safe(r.slab))}</b><br/><font color='#666666'>{escape(_safe(r.category))}</font>", base)
            hist = "\n".join(r.history_lines)
            data.append([
                _p(r.sl, center),
                Paragraph(f"<b>{escape(_safe(r.file_no))}</b><br/><font color='#666666'>{escape(r.file_type)}</font>", base),
                _p("\n".join(r.concern_lines), base),
                _p(hist, base),
                slab,
                Paragraph(f'<font color="{"#C00000" if r.area == "Out" else "#2E7D32"}"><b>{r.area}</b></font>', center),
                _p(f"{r.receive_dt:%d/%m/%Y}" if r.receive_dt else "", center),
                _p(when, center),
                _p(r.tat if r.tat is not None else "", center),
                _p(r.extra_tat if r.extra_tat is not None else "", center),
                Paragraph(f'<font color="{status_color}"><b>{escape(_safe(status)).replace(chr(10), "<br/>")}</b></font>', center),
                summary_par,
            ])
            style.append(("BACKGROUND", (4, i), (4, i), colors.HexColor(KIND_BG.get(r.kind, "#FFFFFF"))))
            if internal:
                col_for = {"area": 5, "slab": 4, "summary": 11, "status": 10}
                for key in r.flags:
                    if key in col_for:
                        style.append(("BACKGROUND", (col_for[key], i), (col_for[key], i), YELLOW))
                if r.canceled:
                    style.append(("BACKGROUND", (4, i), (4, i), YELLOW))
        t = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
        t.setStyle(TableStyle(style))
        return t

    def band(text, bg):
        t = Table([[Paragraph(f"<b>{escape(text)}</b>", ParagraphStyle("band", parent=base, fontSize=10, leading=12,
                                                                        textColor=colors.black))]], colWidths=[usable])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(bg)),
                               ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t

    def on_page(cv, doc):
        cv.saveState()
        w, h = page
        cv.setFont("Vera-Bold", 9)
        cv.setFillColor(NAVY)
        cv.drawString(left, h - 7 * mm, _safe(title))
        cv.setStrokeColor(NAVY)
        cv.setLineWidth(0.8)
        cv.line(left, h - 8.6 * mm, w - right, h - 8.6 * mm)
        cv.setFont("Vera", 7)
        cv.setFillColor(GREY)
        cv.drawString(left, 6 * mm, f"Generated {d.generated_at:%d/%m/%Y %I:%M %p}")
        cv.restoreState()

    story = []
    story.append(Spacer(1, 1 * mm))
    n_pk = sum(1 for r in d.complete + d.incomplete if r.kind == "Package")
    n_sg = sum(1 for r in d.complete + d.incomplete if r.kind == "Single")
    n_rc = sum(1 for r in d.complete + d.incomplete if r.kind == "ReCpv")
    n_ex = sum(1 for r in d.complete + d.incomplete if r.kind == "Extra")
    stats = Table([[Paragraph(f"<b>Complete</b> {len(d.complete)}", base), Paragraph(f"<b>Incomplete</b> {len(d.incomplete)}", base),
                    Paragraph(f"<b>Package</b> {n_pk}", base), Paragraph(f"<b>Single</b> {n_sg}", base),
                    Paragraph(f"<b>Re-CPV</b> {n_rc}", base), Paragraph(f"<b>Extra</b> {n_ex}", base)]],
                  colWidths=[usable / 6] * 6)
    stats.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#9A9A9A")),
                               ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
                               ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F7FB")),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    story += [stats, Spacer(1, 3 * mm)]

    story.append(band(f"Complete Report ({len(d.complete)})", "#E2EFDA"))
    story.append(Spacer(1, 1.5 * mm))
    if d.complete:
        story.append(table_for(d.complete))
    else:
        story.append(_p("No submitted files for this report.", small))
    story.append(PageBreak())
    story.append(band(f"Incomplete Report ({len(d.incomplete)})", "#FCE4D6"))
    story.append(Spacer(1, 1.5 * mm))
    if d.incomplete:
        story.append(table_for(d.incomplete))
        story.append(Spacer(1, 1.5 * mm))
        story.append(_p("For Incomplete rows TAT / Extra TAT are counted up to the report date.", small))
    else:
        story.append(_p("No incomplete files.", small))
    if internal:
        rc = d.recon
        story += [Spacer(1, 4 * mm), _p(
            f"Internal check - trips in billing rows: {rc.get('row_trips')}, trips in files: {rc.get('file_trips')}. "
            f"Yellow cells need a person to check (see the Check List sheet of the Excel).", small)]

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=left, rightMargin=right, topMargin=12 * mm,
                            bottomMargin=11 * mm, title=title, author="Verify Report Builder")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page, canvasmaker=_NumberedCanvas)
    return path
