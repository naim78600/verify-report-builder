"""Prime Bank Report - PDF for bankers (reportlab, no other tools needed).

Design goals: simple, same two parts as the daily e-mail (Complete / Incomplete), A3 landscape (the 14 columns
stay big and readable; prints scaled on A4), header row repeated on every page, rows never split across pages,
status and area shown both by colour AND by words (still readable on a black-and-white printer), embedded fonts,
calm colours (no harsh red).
"""
from __future__ import annotations

import os
from html import escape
from pathlib import Path

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import theme as T
from .billing import SLA_IN, SLA_OUT, before_after
from .collect_prime import PrimeData, title_for
from .report_text import appointment_lines, bill_slab_lines, last_update_lines, summary_lines

def _c(hexv: str):
    return colors.HexColor("#" + hexv)


NAVY, GREEN, AMBER, GREY, YELLOW = _c(T.NAVY), _c(T.POS), _c(T.NEG), _c(T.MUTED), _c(T.YELLOW)
KIND_BG = {k: "#" + v for k, v in T.KIND_BG.items()}

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
            self.drawRightString(w - 9 * mm, 6 * mm, f"Page {self._pageNumber} of {n}")
            super().showPage()
        super().save()


_FONT_TAGS = {   # style code -> (bold, colour, size delta)
    "n": (False, T.TEXT), "b": (True, T.TEXT), "m": (False, T.MUTED), "h": (True, T.NAVY),
    "g": (False, T.POS), "gb": (True, T.POS), "a": (False, T.NEG), "ab": (True, T.NEG), "k": (False, T.MUTED),
}


def _markup(lines, kind_color: str | None = None) -> str:
    """Lines of (text, style) -> reportlab paragraph markup."""
    out = []
    for ln in lines:
        seg = []
        for text, st in ln:
            if not text:
                continue
            bold, color = _FONT_TAGS.get(st, _FONT_TAGS["n"])
            if st == "k" and kind_color:
                bold, color = True, kind_color
            t = escape(_safe(text.replace("\u25ba", "\u00bb")))
            if st == "h":
                t = f'<font size="6">{t}</font>'
            if bold:
                t = f"<b>{t}</b>"
            seg.append(f'<font color="#{color}">{t}</font>')
        out.append("".join(seg) or "&nbsp;")
    return "<br/>".join(out)


def build_prime_pdf(d: PrimeData, path: Path, internal: bool) -> Path:
    _fonts()
    title = title_for(d)
    page = landscape(A3)
    left = right = 9 * mm
    usable = page[0] - left - right
    base = ParagraphStyle("b", fontName="Vera", fontSize=7.6, leading=9.6, textColor=_c(T.TEXT))
    center = ParagraphStyle("c", parent=base, alignment=1)
    head = ParagraphStyle("h", parent=base, fontName="Vera-Bold", textColor=colors.white, alignment=1, fontSize=8)
    small = ParagraphStyle("s", parent=base, fontSize=7, leading=8.6, textColor=GREY)

    heads = ["SL", "File No", "Concerns", "Re-CPV / Extra Trip (ID)", "Bill Slab", "Area", "Receive Date",
             "Submission Date-Time", "TAT", "Extra TAT / SLA", "Report Status", "Report Summary", "Last Update", "Appointment"]
    widths_mm = [8, 37, 40, 34, 52, 11, 18, 22, 10, 17, 21, 50, 50, 40]
    scale = usable / (sum(widths_mm) * mm)
    widths = [w * mm * scale for w in widths_mm]

    def table_for(rows) -> Table:
        data = [[Paragraph(h, head) for h in heads]]
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("GRID", (0, 0), (-1, -1), 0.4, _c(T.BORDER)),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ]
        for i, r in enumerate(rows, 1):
            sub = r.submitted
            if sub:
                when = f"{r.submitted_at:%d/%m/%Y}<br/>{r.submitted_at:%I:%M %p}<br/><font color='#{T.MUTED}'>({before_after(r)})</font>"
            else:
                when = f"<font color='#{T.MUTED}'>Pending</font>"
            st_color = T.POS if sub else T.NEG
            status = r.status + (f"<br/><font size='6.5'>({escape(r.status_note)})</font>" if r.status_note and not sub else "")
            out = r.area == "Out"
            xt = r.extra_tat if r.extra_tat is not None else ""
            sla_txt = "SLA Breach" if r.sla_breach else "Within SLA"
            sla_col = T.NEG if r.sla_breach else T.POS
            hist = "\n".join(r.history_lines)
            kc = T.KIND_TX.get(r.kind)
            data.append([
                _p(r.sl, center),
                Paragraph(f"<b><font color='#{T.NAVY}'>{escape(_safe(r.file_no))}</font></b><br/><font color='#{T.MUTED}'>{escape(r.file_type)}</font>", base),
                _p("\n".join(r.concern_lines), base),
                _p(hist, base),
                Paragraph(_markup(bill_slab_lines(r), kc), base),
                Paragraph(f'<font color="#{T.OUT if out else T.IN}"><b>{r.area}</b></font>', center),
                _p(f"{r.receive_dt:%d/%m/%Y}" if r.receive_dt else "", center),
                Paragraph(when, center),
                _p(r.tat if r.tat is not None else "", center),
                Paragraph(f"<b><font color='#{sla_col}'>{xt}</font></b><br/><font size='6.6' color='#{sla_col}'>{sla_txt}<br/>"
                          f"(SLA {r.sla_days} days)</font>", center),
                Paragraph(f'<font color="#{st_color}"><b>{status}</b></font>', center),
                Paragraph(_markup(summary_lines(r)), base),
                Paragraph(_markup(last_update_lines(r)), base),
                Paragraph(_markup(appointment_lines(r)), base),
            ])
            style.append(("BACKGROUND", (4, i), (4, i), _c(T.KIND_BG.get(r.kind, "FFFFFF"))))
            style.append(("BACKGROUND", (5, i), (5, i), _c(T.OUT_BG if out else T.IN_BG)))
            style.append(("BACKGROUND", (10, i), (10, i), _c(T.POS_BG if sub else T.NEG_BG)))
            if i % 2 == 0:
                for col in (0, 1, 2, 3, 6, 7, 8, 9, 11, 12, 13):
                    style.append(("BACKGROUND", (col, i), (col, i), _c(T.ZEBRA)))
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

    def band(text, bg, fg):
        t = Table([[Paragraph(f"<b>{escape(text)}</b>", ParagraphStyle("band", parent=base, fontSize=12, leading=14,
                                                                        textColor=_c(fg)))]], colWidths=[usable])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _c(bg)), ("LINEBEFORE", (0, 0), (0, -1), 4, _c(fg)),
                               ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        return t

    def on_page(cv, doc):
        cv.saveState()
        w, h = page
        cv.setFont("Vera-Bold", 12)
        cv.setFillColor(NAVY)
        cv.drawString(left, h - 8 * mm, _safe(title))
        cv.setStrokeColor(NAVY)
        cv.setLineWidth(1)
        cv.line(left, h - 10 * mm, w - right, h - 10 * mm)
        cv.setFont("Vera", 7.5)
        cv.setFillColor(GREY)
        cv.drawString(left, 6 * mm, f"Generated {d.generated_at:%d/%m/%Y %I:%M %p}   |   BS = Bank Statement   |   "
                                    f"SLA: In area {SLA_IN} working days, Out area {SLA_OUT} working days (Fri, Sat and holidays excluded)")
        cv.restoreState()

    story = []
    story.append(Spacer(1, 1 * mm))
    allr = d.complete + d.incomplete
    n_pk = sum(1 for r in allr if r.kind == "Package")
    n_sg = sum(1 for r in allr if r.kind == "Single")
    n_rc = sum(1 for r in allr if r.kind == "ReCpv")
    n_ex = sum(1 for r in allr if r.kind == "Extra")
    n_br = sum(1 for r in allr if r.sla_breach)
    cells = [("Complete", len(d.complete), T.POS), ("Incomplete", len(d.incomplete), T.NEG), ("Package", n_pk, T.TEXT),
             ("Extra Trip", n_sg, T.TEXT), ("Re-CPV", n_rc, T.TEXT), ("Extra Doc / Trip", n_ex, T.TEXT), ("SLA Breach", n_br, T.NEG)]
    stat_style = ParagraphStyle("st", parent=center, fontSize=8, leading=17)
    stats = Table([[Paragraph(f"{k}<br/><font size='14' color='#{c}'><b>{v}</b></font>", stat_style) for k, v, c in cells]],
                  colWidths=[usable / len(cells)] * len(cells))
    stats.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, _c(T.BORDER)), ("INNERGRID", (0, 0), (-1, -1), 0.3, _c(T.BORDER)),
                               ("BACKGROUND", (0, 0), (-1, -1), _c("F1F5F9")),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [stats, Spacer(1, 4 * mm)]

    story.append(band(f"Complete Report  ({len(d.complete)})", T.BAND_OK_BG, T.BAND_OK_TX))
    story.append(Spacer(1, 1.5 * mm))
    if d.complete:
        story.append(table_for(d.complete))
    else:
        story.append(_p("No submitted files for this report.", small))
    story.append(PageBreak())
    story.append(band(f"Incomplete Report  ({len(d.incomplete)})", T.BAND_NO_BG, T.BAND_NO_TX))
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
            f"Internal check - trips in report rows: {rc.get('row_trips')}, trips in files: {rc.get('file_trips')}. "
            f"Yellow cells need a person to check (see the Check List sheet of the Excel).", small)]

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=left, rightMargin=right, topMargin=14 * mm,
                            bottomMargin=12 * mm, title=title, author="Verify Report Builder")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page, canvasmaker=_NumberedCanvas)
    return path
