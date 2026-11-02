"""Read-only: turn one file's activity log into the few facts we need (times in Dhaka time)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .billing import FileLogs

DHAKA = timedelta(hours=6)          # logs are UTC ("...Z"); Bangladesh is UTC+6 all year


def _utc_to_dhaka(s: str | None) -> datetime | None:
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", str(s))
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M:%S") + DHAKA


def parse_logs(raw: dict) -> FileLogs:
    rows = ((raw or {}).get("data") or {}).get("activity_logs") or []
    out = FileLogs(ok=True)
    for r in rows:
        when = _utc_to_dhaka(r.get("created_at"))
        if when is None:
            continue
        etype = (r.get("entity_type") or "").upper()
        act = str(r.get("activity") or "")
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
    return out
