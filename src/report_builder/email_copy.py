"""'Copy for e-mail': builds the same simple table as the daily e-mail, as a small web page.

The page opens in the default browser with a big "Copy" button; the person pastes into
Zoho Mail. (The software never sends e-mail itself.)
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from . import config, theme as T
from .billing import before_after
from .collect_prime import PrimeData, title_for
from .report_text import appointment_lines, bill_slab_lines, has_due, last_update_lines, summary_lines

SIGNATURE_FILE = config.SETTINGS_DIR / "email_signature.txt"
HEAD = ["S.N", "File Number", "Type", "Concerns", "Re-CPV / Extra Trip (ID)", "Bill Slab", "Area", "Receive Date",
        "Submission Date", "Before/After 3 PM", "Tat", "Extra Tat", "SLA", "Report Status", "Report Summary",
        "Last Update", "Appointment"]

TD = f"border:1px solid #{T.BORDER};padding:3px 5px;vertical-align:top;text-align:center;font-size:12px;"
TDL = f"border:1px solid #{T.BORDER};padding:3px 5px;vertical-align:top;text-align:left;font-size:12px;"
TH = f"border:1px solid #{T.BORDER};padding:4px 5px;text-align:center;font-weight:bold;font-size:12px;background:#{T.NAVY};color:#fff;"


def load_signature() -> str:
    try:
        return SIGNATURE_FILE.read_text(encoding="utf-8")
    except Exception:
        return ""


def save_signature(text: str) -> None:
    SIGNATURE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SIGNATURE_FILE.write_text(text, encoding="utf-8")


def _br(s) -> str:
    return escape(str(s if s is not None else "")).replace("\n", "<br>")


_ST = {"n": "", "b": "font-weight:bold;", "m": f"color:#{T.MUTED};", "h": f"font-weight:bold;font-size:10px;color:#{T.NAVY};",
       "g": f"color:#{T.POS};", "gb": f"font-weight:bold;color:#{T.POS};", "a": f"color:#{T.NEG};",
       "ab": f"font-weight:bold;color:#{T.NEG};", "k": f"color:#{T.MUTED};",
       "dn": f"color:#{T.NOTE};",
       "hl": f"font-weight:bold;color:#{T.HILITE};background:#{T.HILITE_BG};padding:0 2px;border-radius:2px;"}


def _html(lines, kind_color=None) -> str:
    out = []
    for ln in lines:
        seg = []
        for text, st in ln:
            css = _ST.get(st, "")
            if st == "k" and kind_color:
                css = f"font-weight:bold;color:#{kind_color};"
            seg.append(f'<span style="{css}">{escape(text)}</span>' if text else "")
        out.append("".join(seg) or "&nbsp;")
    return "<br>".join(out)


def _table(title: str, rows) -> str:
    out = [f'<table style="border-collapse:collapse;border:1px solid #{T.BORDER};font-family:Calibri,Arial,sans-serif;margin-bottom:14px;">',
           f'<tr><td colspan="{len(HEAD)}" style="{TH}font-size:14px;">{escape(title)}</td></tr>',
           "<tr>" + "".join(f'<td style="{TH}">{escape(h)}</td>' for h in HEAD) + "</tr>"]
    for r in rows:
        sub = r.submitted
        when = f"{r.reported_at:%d/%m/%Y} {r.reported_at:%I:%M %p}" if sub else "Pending"
        sla_c = T.NEG if r.sla_breach else T.POS
        out_a = r.area == "Out"
        cells = [
            (escape(str(r.sl)), TD), (f"<b>{escape(r.file_no)}</b>", TD + "white-space:nowrap;"), (escape(r.file_type), TD),
            (_br("\n".join(r.concern_lines)), TDL), (_br("\n\n".join(r.history_lines)), TDL),
            (_html(bill_slab_lines(r), T.KIND_TX.get(r.kind)), TDL + f"background:#{T.KIND_BG.get(r.kind, 'FFFFFF')};"),
            (f"<b>{r.area}</b>", TD + f"color:#{T.OUT if out_a else T.IN};background:#{T.OUT_BG if out_a else T.IN_BG};"),
            (f"{r.receive_dt:%d/%m/%Y}" if r.receive_dt else "", TD), (escape(when), TD),
            (escape(before_after(r)) if sub else "-", TD), (str(r.tat) if r.tat is not None else "", TD),
            (f"<b>{r.extra_tat}</b>" if r.extra_tat is not None else "", TD + f"color:#{sla_c};"),
            ("SLA Breach" if r.sla_breach else "Within SLA", TD + f"color:#{sla_c};font-weight:bold;"),
            (escape(r.status), TD + f"font-weight:bold;color:#{T.POS if sub else T.NEG};background:#{T.POS_BG if sub else T.NEG_BG};"),
            (_html(summary_lines(r)), TDL + (f"background:#{T.DUE_CELL_BG};" if has_due(r) else "")), (_html(last_update_lines(r)), TDL), (_html(appointment_lines(r)), TDL),
        ]
        out.append("<tr>" + "".join(f'<td style="{st}">{v}</td>' for v, st in cells) + "</tr>")
    out.append("</table>")
    return "".join(out)


def build_email_html(d: PrimeData, path: Path, signature: str | None = None) -> Path:
    sig = load_signature() if signature is None else signature
    dd = d.report_date
    when = f"{dd.day}-{dd.month}-{dd.year}"
    body = (
        f'<div id="mail" style="font-family:Arial,Helvetica,sans-serif;font-size:13px;">'
        f"<p>Dear Concern,</p><p>Please receive {when} submission report tracker</p>"
        + _table("Complete Report", d.complete) + _table("Incomplete Report", d.incomplete)
        + f"<p>Regards,</p><p>{_br(sig)}</p></div>"
    )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{escape(title_for(d))}</title>
<style>body{{font-family:Arial,sans-serif;margin:16px;background:#f4f6fa}}
#bar{{position:sticky;top:0;background:#fff;padding:10px 14px;border:1px solid #cfd6e4;border-radius:8px;margin-bottom:14px}}
button{{background:#1F3864;color:#fff;border:0;padding:10px 18px;font-size:15px;border-radius:6px;cursor:pointer}}
#msg{{margin-left:12px;color:#2E7D32;font-weight:bold}}
#paper{{background:#fff;padding:16px;border:1px solid #cfd6e4;border-radius:8px;overflow:auto}}</style></head><body>
<div id="bar"><button onclick="copyMail()">কপি করুন (Copy)</button><span id="msg"></span>
<div style="margin-top:6px;color:#555;font-size:13px">কপি করার পর Zoho Mail-এর নতুন মেইলে Paste করুন। Subject: <b>{escape(when)} submission tracker</b></div></div>
<div id="paper">{body}</div>
<script>
function copyMail(){{
  var el=document.getElementById('mail'); var r=document.createRange(); r.selectNode(el);
  var s=window.getSelection(); s.removeAllRanges(); s.addRange(r);
  var ok=false; try{{ok=document.execCommand('copy');}}catch(e){{}}
  s.removeAllRanges();
  document.getElementById('msg').textContent= ok ? 'কপি হয়েছে। এখন মেইলে Paste করুন।' : 'কপি হয়নি; টেবিল সিলেক্ট করে Ctrl+C / Cmd+C চাপুন।';
}}
</script></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
