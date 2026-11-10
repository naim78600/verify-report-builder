"""Prime Bank Report - PDF for bankers (reportlab, no other tools needed).

Design goals: simple, same two parts as the daily e-mail (Complete / Incomplete), A3 landscape (the 16 columns
stay big and readable; prints scaled on A4), header row repeated on every page, rows never split across pages,
status and area shown both by colour AND by words (still readable on a black-and-white printer), embedded fonts,
calm colours (no red, no yellow).  Problems written in Done are amber; the same problems repeated in Due sit on a
soft peach marker.  Internal copy: light sky-blue cells = "please check".
"""
from __future__ import annotations

import os
from html import escape
from pathlib import Path
from types import SimpleNamespace

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
from .report_text import _dt, appointment_lines, bill_slab_lines, has_due, last_update_lines, sla_restart_lines, summary_lines

HIST_MAX = 6              # history lines shown per row in the PDF (newest); the Excel has them all
LINES = {"concerns": 10, "history": 18, "slab": 16, "summary": 14, "last": 14, "appt": 14, "reason": 14}   # printed lines per cell
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
    "dn": (False, T.NOTE), "hl": (True, T.HILITE), "rs": (True, T.RESTART),
}


SHOW_TRIPS = 3            # Last Update: newest trip updates shown per row in the PDF
SHOW_APPTS = 2            # Appointment: appointments shown per row in the PDF


def last_update_short(r) -> list:
    """PDF version of the Last Update column: the file line + the newest SHOW_TRIPS trip updates; the rest is counted
    ("+N older trip updates, M trips with no activity - see the Excel").  The Excel keeps every trip."""
    if r.last_file is None or len(r.last_trips) <= SHOW_TRIPS:
        return last_update_lines(r)
    when, what, user = r.last_file
    lines = [[("FILE ", "h"), (_dt(when), "b")], [(what + (f" \u00b7 {user}" if user else ""), "n")]]
    active = sorted((t for t in r.last_trips if t[2] is not None), key=lambda t: t[2], reverse=True)
    idle = len(r.last_trips) - len(active)
    for tid, ttype, tw, text, user_t in active[:SHOW_TRIPS]:
        lines += [[("", "n")], [(f"Trip {tid} \u00b7 {ttype}", "b")],
                  [(f"{_dt(tw)} {text}" + (f" \u00b7 {user_t}" if user_t else ""), "n")]]
    notes = []
    if len(active) > SHOW_TRIPS:
        notes.append(f"+{len(active) - SHOW_TRIPS} older trip updates")
    if idle:
        notes.append(f"{idle} trip{'s' if idle > 1 else ''} with no activity")
    if notes:
        lines += [[("", "n")], [("; ".join(notes) + " (all in the Excel)", "m")]]
    return lines


def appointment_short(r) -> list:
    """PDF version of the Appointment column: the active / newest SHOW_APPTS appointments, the rest counted."""
    restart = sla_restart_lines(r)
    head = (restart + [[("", "n")]]) if restart else []
    if len(r.appointments) <= SHOW_APPTS:
        lines = appointment_lines(r)
        return head + ([] if restart and lines == [[("NO", "m")]] else lines)
    keep = sorted(r.appointments, key=lambda a: (a.get("active", True), a.get("time") or a.get("created_at")), reverse=True)[:SHOW_APPTS]
    lines = appointment_lines(SimpleNamespace(appointments=keep))      # that function only reads .appointments
    lines += [[("", "n")], [(f"+{len(r.appointments) - SHOW_APPTS} more appointments (all in the Excel)", "m")]]
    return head + lines


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
    base = ParagraphStyle("b", fontName="Vera", fontSize=8.6, leading=10.8, textColor=_c(T.TEXT))
    center = ParagraphStyle("c", parent=base, alignment=1)
    head = ParagraphStyle("h", parent=base, fontName="Vera-Bold", textColor=colors.white, alignment=1, fontSize=8.8)
    small = ParagraphStyle("s", parent=base, fontSize=7.8, leading=9.6, textColor=GREY)

    # v6 order - the same reading order as the Excel tracker (File Type sits under the File No, Before / After 3 PM under the
    # submission time, SLA under the Extra TAT, the last-update date inside "Last Update")
    heads = ["SL", "File No", "Applicant Name", "Concerns", "Receive Date", "Submission Date-Time", "Report Status", "Report Summary",
             "Last Update", "Re-CPV / Extra Trip (ID)", "Bill Slab", "Area", "SLA Start / Restart Date", "TAT", "Extra TAT / SLA",
             "Appointment"]
    widths_mm = [7, 38, 24, 28, 21, 22, 21, 40, 34, 25, 38, 11, 22, 9, 17, 33]
    SHOWN = {"Concerns": "Concerns Name", "Receive Date": "Receive Date-Time", "Re-CPV / Extra Trip (ID)": "Re-CPV / Extra Trip",
             "Report Summary": "Report Summary (Done / Due)", "Appointment": "Appointment History"}
    REASON_MM = 34                       # Incomplete table only: "Pending Reason" right after "Report Status"
    cur = {"w": []}

    def set_layout(reason: bool):
        w_mm = list(widths_mm)
        if reason:
            w_mm.insert(heads.index("Report Status") + 1, REASON_MM)
        scale = usable / (sum(w_mm) * mm)
        cur["w"] = [w * mm * scale for w in w_mm]
        return cur["w"]

    def cap(flow, col: int, max_lines: int):
        """Keep every cell readable.  A long cell (a file with dozens of trips) is cut to `max_lines` printed lines at the
        normal font size and ends with "+N more lines (full text in the Excel)" - the font is never made tiny.  Whatever
        is left is still forced to fit one page (shrink) so reportlab can never stop with a LayoutError."""
        w = cur["w"][col] - 6
        flow.wrap(w, 10 ** 6)
        n = len(flow.blPara.lines)
        parts = [flow]
        if n > max_lines:
            first = flow.split(w, max_lines * flow.style.leading)
            if first:
                parts = [first[0], Paragraph(f"<font color='#{T.MUTED}'><i>... +{n - max_lines} more lines (full text in the Excel)</i></font>", small)]
        return KeepInFrame(w, MAX_CELL_H, parts, mode="shrink", hAlign="LEFT", vAlign="TOP")

    def table_for(rows, reason: bool = False) -> Table:
        widths = set_layout(reason)
        hs = list(heads)
        if reason:
            hs.insert(hs.index("Report Status") + 1, "Pending Reason")
        ix = {h: i for i, h in enumerate(hs)}                    # column index by name (the Incomplete table has one more column)
        data = [[Paragraph(SHOWN.get(h, h), head) for h in hs]]
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
            start = r.sla_start or (r.receive_dt.date() if r.receive_dt else None)
            if r.sla_restarted:                                      # restarted (appointment / new trip): plum, with the reason in words
                start_cell = Paragraph(f"<font color='#{T.RESTART}'><b>{start:%d/%m/%Y}</b><br/><font size='6.6'>SLA restarted<br/>"
                                       f"({r.sla_why})</font></font>", center)
            else:
                start_cell = _p(f"{start:%d/%m/%Y}" if start else "", center)
            cells = {
                "SL": _p(r.sl, center),
                "File No": Paragraph(f"<b><font color='#{T.NAVY}'>{escape(_safe(r.file_no))}</font></b><br/><font color='#{T.MUTED}'>{escape(r.file_type)}</font>", base),
                "Applicant Name": _p(getattr(r, "applicant", "") or "", base),
                "Concerns": cap(_p("\n".join(r.concern_lines), base), ix["Concerns"], LINES["concerns"]),
                "Re-CPV / Extra Trip (ID)": cap(_p(hist, base), ix["Re-CPV / Extra Trip (ID)"], LINES["history"]),
                "Bill Slab": cap(Paragraph(_markup(bill_slab_lines(r), kc), base), ix["Bill Slab"], LINES["slab"]),
                "Area": Paragraph(f'<font color="#{T.OUT if out else T.IN}"><b>{r.area}</b></font>', center),
                "Receive Date": _p(f"{r.receive_dt:%d/%m/%Y}\n{r.receive_dt:%I:%M %p}" if r.receive_dt else "", center),
                "SLA Start / Restart Date": start_cell,
                "Submission Date-Time": Paragraph(when, center),
                "TAT": _p(r.tat if r.tat is not None else "", center),
                "Extra TAT / SLA": Paragraph(f"<b><font color='#{sla_col}'>{xt}</font></b><br/><font size='6.6' color='#{sla_col}'>{sla_txt}<br/>"
                                             f"(SLA {r.sla_days} days)</font>", center),
                "Report Status": Paragraph(f'<font color="#{st_color}"><b>{status}</b></font>', center),
                "Report Summary": cap(Paragraph(_markup(summary_lines(r)), base), ix["Report Summary"], LINES["summary"]),
                "Last Update": cap(Paragraph(_markup(last_update_short(r)), base), ix["Last Update"], LINES["last"]),
                "Appointment": cap(Paragraph(_markup(appointment_short(r)), base), ix["Appointment"], LINES["appt"]),
            }
            if reason:
                cells["Pending Reason"] = cap(_reason_flow(r), ix["Pending Reason"], LINES["reason"])
            data.append([cells[h] for h in hs])
            style.append(("BACKGROUND", (ix["Bill Slab"], i), (ix["Bill Slab"], i), _c(T.KIND_BG.get(r.kind, "FFFFFF"))))
            style.append(("BACKGROUND", (ix["Area"], i), (ix["Area"], i), _c(T.OUT_BG if out else T.IN_BG)))
            style.append(("BACKGROUND", (ix["Report Status"], i), (ix["Report Status"], i), _c(T.POS_BG if sub else T.NEG_BG)))
            if r.sla_restarted:
                style.append(("BACKGROUND", (ix["SLA Start / Restart Date"], i), (ix["SLA Start / Restart Date"], i), _c(T.RESTART_BG)))
            if has_due(r):
                style.append(("BACKGROUND", (ix["Report Summary"], i), (ix["Report Summary"], i), _c(T.DUE_CELL_BG)))
            if i % 2 == 0:
                zebra_cols = ["SL", "File No", "Applicant Name", "Concerns", "Re-CPV / Extra Trip (ID)", "Receive Date", "Submission Date-Time", "TAT",
                              "Extra TAT / SLA", "Last Update", "Appointment"]
                if not r.sla_restarted:
                    zebra_cols.append("SLA Start / Restart Date")
                if not has_due(r):
                    zebra_cols.append("Report Summary")
                if reason:
                    zebra_cols.append("Pending Reason")
                for h in zebra_cols:
                    style.append(("BACKGROUND", (ix[h], i), (ix[h], i), _c(T.ZEBRA)))
            if internal:
                col_for = {"area": ix["Area"], "slab": ix["Bill Slab"], "summary": ix["Report Summary"], "status": ix["Report Status"]}
                if reason:
                    col_for["reason"] = ix["Pending Reason"]
                for key in r.flags:
                    if key in col_for:
                        style.append(("BACKGROUND", (col_for[key], i), (col_for[key], i), CHECK))
                if r.canceled:
                    style.append(("BACKGROUND", (ix["Bill Slab"], i), (ix["Bill Slab"], i), CHECK))
        t = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
        t.setStyle(TableStyle(style))
        return t

    def _reason_flow(r):
        """Why the file is still pending, one fact per line (Hold comment / Finished - not yet submitted / Appointment ...)."""
        if not r.reason:
            if r.file_status in (1, 2) and r.sla_breach:
                return Paragraph(f"<font color='#{T.NEG}'><b>On Going - SLA breached</b></font>", base)
            return Paragraph(f"<font color='#{T.MUTED}'>-</font>", base)
        colour = {"hold": T.NEG, "finished": T.NAVY, "partial": T.NEG, "appointment": T.NAVY, "ongoing": T.POS}.get(r.reason_kind, T.TEXT)
        lines = [escape(_safe(x)) for x in r.reason.split(" | ")]
        lines[0] = f"<b><font color='#{colour}'>{lines[0]}</font></b>"
        return Paragraph("<br/>".join(lines), base)

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
                                    f"SLA: In area {SLA_IN} working days, Out area {SLA_OUT} working days (Fri, Sat and holidays excluded), from the "
                                    f"SLA Start Date = Receive Date; an appointment (latest scheduled date) or any new trip (creation day) restarts it from that day")
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
        story.append(table_for(d.incomplete, reason=True))
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
