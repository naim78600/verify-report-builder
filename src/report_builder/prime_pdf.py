"""Prime Bank Report - PDF for bankers (reportlab, no other tools needed).

Design goals: simple, same two parts as the daily e-mail (Complete / Incomplete), A3 landscape (the 14 columns
stay big and readable; prints scaled on A4), header row repeated on every page, rows never split across pages,
status and area shown both by colour AND by words (still readable on a black-and-white printer), embedded fonts,
calm colours (no red, no yellow).  Problems written in Done are amber; the same problems repeated in Due sit on a
soft peach marker.  Internal copy: light sky-blue cells = "please check".
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
from reportlab.platypus import KeepInFrame, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import theme as T
from .billing import SLA_IN, SLA_OUT, before_after
from .collect_prime import PrimeData, title_for
from .report_text import appointment_lines, bill_slab_lines, has_due, last_update_lines, summary_lines

HIST_MAX = 15             # history lines shown per row in the PDF (newest); the Excel has them all
MAX_CELL_H = 600          # points; the page frame is ~747 pt high, minus the repeated header row and the cell padding


def _c(hexv: str):
    return colors.HexColor("#" + hexv)


NAVY, GREEN, AMBER, GREY, CHECK = _c(T.NAVY), _c(T.POS), _c(T.NEG), _c(T.MUTED), _c(T.CHECK)
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
    "dn": (False, T.NOTE), "hl": (True, T.HILITE),
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
            if st == "hl":
                seg.append(f'<font color="#{color}" backColor="#{T.HILITE_BG}">{t}</font>')
            else:
                seg.append(f'<font color="#{color}">{t}</font>')
        out.append("".join(seg) or "&nbsp;")
    return "<br/>".join(out)


def build_prime_pdf(d: PrimeData, path: Path, internal: bool = False) -> Path:
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

    def cap(flow, col: int):
        """A row can never be taller than a page (reportlab stops with a LayoutError).  A very long cell - e.g. the whole
        history of a file with dozens of trips - is shrunk to fit instead of being cut: nothing is lost, the Excel has it too."""
        return KeepInFrame(widths[col] - 6, MAX_CELL_H, [flow], mode="shrink", hAlign="LEFT", vAlign="TOP")

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
                when = f"{r.reported_at:%d/%m/%Y}<br/>{r.reported_at:%I:%M %p}<br/><font color='#{T.MUTED}'>({before_after(r)})</font>"
            else:
                when = f"<font color='#{T.MUTED}'>Pending</font>"
            st_color = T.POS if sub else T.NEG
            status = r.status + (f"<br/><font size='6.5'>({escape(r.status_note)})</font>" if r.status_note and not sub else "")
            out = r.area == "Out"
            xt = r.extra_tat if r.extra_tat is not None else ""
            sla_txt = "SLA Breach" if r.sla_breach else "Within SLA"
            sla_col = T.NEG if r.sla_breach else T.POS
            hl = r.history_lines
            if len(hl) > HIST_MAX:                                   # PDF only - the Excel keeps the whole history
                hl = [f"... {len(hl) - HIST_MAX} earlier events (full list in the Excel)"] + hl[-HIST_MAX:]
            hist = "\n".join(hl)
            kc = T.KIND_TX.get(r.kind)
            data.append([
                _p(r.sl, center),
                Paragraph(f"<b><font color='#{T.NAVY}'>{escape(_safe(r.file_no))}</font></b><br/><font color='#{T.MUTED}'>{escape(r.file_type)}</font>", base),
                cap(_p("\n".join(r.concern_lines), base), 2),
                cap(_p(hist, base), 3),
                cap(Paragraph(_markup(bill_slab_lines(r), kc), base), 4),
                Paragraph(f'<font color="#{T.OUT if out else T.IN}"><b>{r.area}</b></font>', center),
                _p(f"{r.receive_dt:%d/%m/%Y}" if r.receive_dt else "", center),
                Paragraph(when, center),
                _p(r.tat if r.tat is not None else "", center),
                Paragraph(f"<b><font color='#{sla_col}'>{xt}</font></b><br/><font size='6.6' color='#{sla_col}'>{sla_txt}<br/>"
                          f"(SLA {r.sla_days} days)</font>", center),
                Paragraph(f'<font color="#{st_color}"><b>{status}</b></font>', center),
                cap(Paragraph(_markup(summary_lines(r)), base), 11),
                cap(Paragraph(_markup(last_update_lines(r)), base), 12),
                cap(Paragraph(_markup(appointment_lines(r)), base), 13),
            ])
            style.append(("BACKGROUND", (4, i), (4, i), _c(T.KIND_BG.get(r.kind, "FFFFFF"))))
            style.append(("BACKGROUND", (5, i), (5, i), _c(T.OUT_BG if out else T.IN_BG)))
            style.append(("BACKGROUND", (10, i), (10, i), _c(T.POS_BG if sub else T.NEG_BG)))
            if has_due(r):
                style.append(("BACKGROUND", (11, i), (11, i), _c(T.DUE_CELL_BG)))
            if i % 2 == 0:
                for col in (0, 1, 2, 3, 6, 7, 8, 9, 12, 13) + (() if has_due(r) else (11,)):
                    style.append(("BACKGROUND", (col, i), (col, i), _c(T.ZEBRA)))
            if internal:
                col_for = {"area": 5, "slab": 4, "summary": 11, "status": 10}
                for key in r.flags:
                    if key in col_for:
                        style.append(("BACKGROUND", (col_for[key], i), (col_for[key], i), CHECK))
                if r.canceled:
                    style.append(("BACKGROUND", (4, i), (4, i), CHECK))
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
        cv.setFillColor(NAVY)
        cv.rect(0, h - 13 * mm, w, 13 * mm, stroke=0, fill=1)
        cv.setFillColor(colors.white)
        cv.setFont("Vera-Bold", 13)
        cv.drawString(left, h - 8.6 * mm, _safe(title))
        cv.setFont("Vera", 8)
        cv.drawRightString(w - right, h - 8.2 * mm, _safe(f"Report date {d.report_date:%d/%m/%Y}"))
        cv.setStrokeColor(_c(T.BORDER))
        cv.setLineWidth(0.4)
        cv.line(left, 9.5 * mm, w - right, 9.5 * mm)
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
    cells = [("Complete", len(d.complete), T.POS), ("Incomplete", len(d.incomplete), T.NEG), ("Package", n_pk, T.NAVY),
             ("Extra Trip", n_sg, T.NAVY), ("Re-CPV", n_rc, T.NAVY), ("Extra Doc / Trip", n_ex, T.NAVY),
             ("Area In", sum(1 for r in allr if r.area == "In"), T.IN), ("Area Out", sum(1 for r in allr if r.area == "Out"), T.OUT),
             ("SLA Breach", n_br, T.NEG)]
    stat_style = ParagraphStyle("st", parent=center, fontSize=7.5, leading=17, textColor=GREY)
    stats = Table([[Paragraph(f"{k.upper()}<br/><font size='15' color='#{c}'><b>{v}</b></font>", stat_style) for k, v, c in cells]],
                  colWidths=[usable / len(cells)] * len(cells))
    tstyle = [("BACKGROUND", (0, 0), (-1, -1), _c(T.PANEL)), ("LINEAFTER", (0, 0), (-2, -1), 3, colors.white),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
    for j, (_k, _v, c) in enumerate(cells):
        tstyle.append(("LINEBELOW", (j, 0), (j, 0), 2, _c(c)))
    stats.setStyle(TableStyle(tstyle))
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
            f"Light-blue cells need a person to check (see the Check List sheet of the Excel).", small)]

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=page, leftMargin=left, rightMargin=right, topMargin=17 * mm,
                            bottomMargin=12 * mm, title=title, author="Verify Report Builder")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page, canvasmaker=_NumberedCanvas)
    return path
