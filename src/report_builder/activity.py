"""Read-only: turn one file's activity log into the few facts we need (times in Dhaka time)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .billing import FileLogs, LogEvent

DHAKA = timedelta(hours=6)          # logs are UTC ("...Z"); Bangladesh is UTC+6 all year


def _utc_to_dhaka(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", str(s))
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S") + DHAKA


def short_activity(act: str, prev, cur, etype: str) -> str:
    """One short, plain phrase for a log line (kept close to the dashboard's own words)."""
    a = (act or "").strip()
    al = a.lower()
    c = str(cur or "").strip()
    if al.startswith("application created"):
        return "File created"
    if "status updated" in al and etype == "APPLICATION":
        return "File " + c.replace("_", " ").title()
    if al.startswith("additional trips created"):
        return "Additional trips created"
    if al.startswith("trip created"):
        return "Trip created"
    if al.startswith("trip updated"):
        return "Trip details edited"
    if al.startswith("concern updated"):
        return "Concern details edited"
    if al.startswith("application outcome"):
        return "Outcome / remarks updated"
    m = re.match(r"trip\s*:\s*\d+\s+allocated from .* to (.+?) by (.+)$", a, re.I)
    if m:
        return f"Re-allocated to {m.group(1)}"
    m = re.match(r"trip\s*:\s*\d+\s+allocated to (.+?) by (.+)$", a, re.I)
    if m:
        return f"Allocated to {m.group(1)}"
    m = re.match(r"trip\s*:\s*\d+\s+([A-Za-z_ ]+)$", a, re.I)
    if m:
        word = m.group(1).strip().replace("_", " ").title()
        return {"Hold": "On Hold"}.get(word, word)
    return a[:70]


def parse_logs(raw: dict) -> FileLogs:
    rows = ((raw or {}).get("data") or {}).get("activity_logs") or []
    out = FileLogs(ok=True)
    for r in rows:
        when = _utc_to_dhaka(r.get("created_at"))
        if when is None:
            continue
        etype = (r.get("entity_type") or "").upper()
        act = str(r.get("activity") or "")
        eid = r.get("entity_id")
        eid = int(eid) if isinstance(eid, int) or str(eid).isdigit() else None
        out.events.append(LogEvent(when, etype, eid, short_activity(act, r.get("previous_data"), r.get("current_data"), etype),
                                   str(r.get("causer_name") or "").strip()))
        cur = str(r.get("current_data") or "").strip().upper()
        if etype == "APPLICATION":
            if act.lower().startswith("application created"):
                out.created = when
            elif "status updated" in act.lower() or cur in ("SUBMITTED", "PARTIALLY_SUBMITTED", "PARTIAL_SUBMITTED"):
                if cur == "SUBMITTED":
                    out.submitted.append(when)
                elif cur.startswith("PARTIAL"):
                    out.partial.append(when)
        elif etype == "TRIP" and re.search(r"\bFINISHED\b", act) and act.lower().startswith("trip"):
            tid = r.get("entity_id")
            if isinstance(tid, int) or str(tid).isdigit():
                tid = int(tid)
                if tid not in out.trip_finished or when > out.trip_finished[tid]:
                    out.trip_finished[tid] = when
    out.submitted.sort()
    out.partial.sort()
    out.events.sort(key=lambda e: e.when, reverse=True)          # newest first (stable: API order kept on ties)
    return out
