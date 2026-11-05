"""Shared wording of the rich cells (Bill Slab, Report Summary, Last Update, Appointment).

Every builder returns `lines`: a list of lines, each line a list of (text, style) pairs.
Styles:  n normal | b bold | m muted | h small heading | g green | gb green bold | a amber | ab amber bold
The Excel, PDF and e-mail writers turn the same lines into their own formatting, so all three always say the same thing.
"""
from __future__ import annotations

from .billing import BillRow


def _dt(x, secs=True):
    if not x:
        return "-"
    return f"{x:%d/%m/%Y %H:%M:%S}" if secs else f"{x:%d/%m/%Y %H:%M}"


def bill_slab_lines(r: BillRow) -> list:
    lines = [[(r.slab, "b")], [(r.category, "k")]]
    if r.bill_note:
        lines.append([(r.bill_note, "m")])
    if len(r.file_history) > 1:
        lines.append([("", "n")])
        lines.append([("FILE HISTORY", "h")])
        for i, h in enumerate(r.file_history):
            if i == r.history_pos:
                lines.append([("► " + h, "b")])
            else:
                lines.append([("   " + h, "m")])
    return lines


def summary_lines(r: BillRow) -> list:
    done, due = r.summary.done, r.summary.due
    due_style = "g" if due == "0" else "a"
    return [[("Done-", "gb"), (done, "g")], [("Due-", "gb" if due == "0" else "ab"), (due, due_style)]]


def last_update_lines(r: BillRow) -> list:
    if r.last_file is None:
        return [[("N/A", "m")]]
    when, what, user = r.last_file
    lines = [[("FILE ", "h"), (_dt(when), "b")],
             [(what + (f" · {user}" if user else ""), "n")]]
    for tid, ttype, tw, text, user_t in r.last_trips:
        lines.append([("", "n")])
        lines.append([(f"Trip {tid} · {ttype}", "b")])
        if tw is None:
            lines.append([("no activity found", "m")])
        else:
            lines.append([(f"{_dt(tw)} {text}" + (f" · {user_t}" if user_t else ""), "n")])
    return lines


def appointment_lines(r: BillRow) -> list:
    if not r.appointments:
        return [[("NO", "m")]]
    lines = []
    for i, a in enumerate(r.appointments):
        if i:
            lines.append([("", "n")])
        lines.append([(f"Trip {a['trip_id']} · {a['trip_type']}", "b")])
        lines.append([("Appointment: ", "m"), (f"{_dt(a['time'])}" + (f" ({a['type']})" if a["type"] else ""), "ab" if a["active"] else "m")])
        lines.append([("Created: ", "m"), (_dt(a["created_at"]), "n")])
        if a["reason"]:
            lines.append([("Reason: ", "m"), (a["reason"], "n")])
        if not a["active"]:
            lines.append([("(not active)", "m")])
    return lines


def plain(lines: list) -> str:
    return "\n".join("".join(t for t, _s in ln) for ln in lines)
