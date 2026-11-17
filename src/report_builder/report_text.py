"""Shared wording of the rich cells (Bill Slab, Report Summary, Last Update, Appointment).

Every builder returns `lines`: a list of lines, each line a list of (text, style) pairs.
Styles:  n normal | b bold | m muted | h small heading | g green | gb green bold | a amber | ab amber bold
         dn problem note inside Done (amber) | hl problem repeated in Due (amber on a soft marker)
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
    """Done / Due as two lines.  Done: finished items (problems in amber brackets).
    Due: the same problems repeated with a soft marker; "0" (green) when nothing is open."""
    sm = r.summary
    done_parts = sm.done_parts or [(sm.done, "ok")]
    due_parts = sm.due_parts or [(sm.due, "ok" if sm.due.strip() == "0" else "note")]
    clear = sm.due.strip() == "0"
    done = [("Done-", "gb")] + [(t, "g" if st == "ok" else "dn") for t, st in done_parts]
    due = [("Due-", "gb" if clear else "ab")] + [(t, "g" if clear else ("a" if st == "ok" else "hl")) for t, st in due_parts]
    return [done, due]


def has_due(r: BillRow) -> bool:
    return r.summary.due.strip() not in ("", "0")


def last_update_date(r: BillRow):
    """The file's newest activity (a real datetime, so Excel can filter by date), or None."""
    return r.last_file[0] if r.last_file else None


def last_update_lines(r: BillRow) -> list:
    """Details part: what the file did last and the newest line of every trip (trip id + type)."""
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


def sla_start_label(r: BillRow) -> str:
    """The SLA Start / Restart Date as a short text (dd/mm/yyyy), '' when unknown."""
    return f"{r.sla_start:%d/%m/%Y}" if getattr(r, "sla_start", None) else ""


def sla_restart_lines(r: BillRow) -> list:
    """Plain words for a banker: the SLA was restarted (by an appointment or by a new trip), and from which day.  [] = no restart."""
    if not getattr(r, "sla_start", None):
        return []
    appt, trip = getattr(r, "sla_appt", None), getattr(r, "sla_trip", None)
    if appt:
        note = f"(appointment on {appt:%d/%m/%Y}: report due the next working day by 5:59 PM)"
    elif trip:
        note = f"({r.sla_days} working days again, from the new trip created on {trip:%d/%m/%Y})"
    else:
        return []
    return [[("SLA restarted from ", "rs"), (f"{r.sla_start:%d/%m/%Y}", "rs")], [(note, "m")]]


def shown_appointments(r) -> list:
    """What the Appointment History cell shows: every trip of the file (v10.0.6), else the row's own."""
    return getattr(r, "file_appointments", None) or getattr(r, "appointments", None) or []


def appointment_lines(r: BillRow) -> list:
    appts = shown_appointments(r)
    if not appts:
        return [[("NO", "m")]]
    lines = []
    for i, a in enumerate(appts):
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
