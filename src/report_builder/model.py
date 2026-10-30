"""Turn raw API JSON into clean, flat-friendly Python structures."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from . import config
from .remarks import short_remark


def parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _s(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _pretty(code: str) -> str:
    return code.replace("_", " ").title() if code else ""


def _appointment(raw: dict) -> dict:
    atype = _s(raw.get("appointment_type"))
    return {
        "id": raw.get("id"),
        "task_id": raw.get("task_id"),
        "time": parse_dt(raw.get("appointment_time")),
        "type": config.APPOINTMENT_TYPE.get(atype, _pretty(atype)),
        "reason": _s(raw.get("reason")),
        "active": bool(raw.get("is_active")),
        "created_at": parse_dt(raw.get("created_at")),
    }


def _trip(raw: dict, agent_names: dict[int, str]) -> dict:
    code = raw.get("status")
    ttype = _s(raw.get("type"))
    agent = raw.get("agent") or {}
    verifier = _s(agent.get("name"))
    if not verifier:
        try:
            verifier = agent_names.get(int(raw.get("assigned_to")), "")
        except (TypeError, ValueError):
            verifier = ""
    remarks = _s(raw.get("remarks"))
    appts = [_appointment(a) for a in (raw.get("appointments") or [])]
    appts.sort(key=lambda a: (a["time"] or datetime.min, a["id"] or 0))
    return {
        "id": raw.get("id"),
        "concern_id": raw.get("concern_id"),
        "type": config.TRIP_TYPE.get(ttype, _pretty(ttype)),
        "status_code": code,
        "status": config.TRIP_STATUS.get(code, f"Status {code}"),
        "verifier": verifier,
        "assigned_by": _s(raw.get("assigned_by")),
        "address_exact": None if raw.get("is_address_exact") is None else bool(raw.get("is_address_exact")),
        "address": _s(raw.get("address")),
        "exact_address": _s(raw.get("exact_address")),
        "area": _s(raw.get("area")),
        "place_name": _s(raw.get("place_name")),
        "created_at": parse_dt(raw.get("created_at")),
        "start_time": parse_dt(raw.get("start_time")),
        "end_time": parse_dt(raw.get("end_time")),
        "remarks": remarks,
        "short_remarks": short_remark(remarks),
        "comment": _s(raw.get("comment")),
        "is_verified": bool(raw.get("is_verified")),
        "re_cpv": bool(raw.get("is_for_recpv")),
        "appointments": appts,
    }


def normalize_file(list_item: dict, detail: dict, agent_names: dict[int, str] | None = None) -> dict:
    """Build one file record. `detail` is the JSON of /manager/applications/{id}."""
    agent_names = agent_names or {}
    app = detail.get("application", detail)
    code = app.get("status", list_item.get("status"))
    atype = app.get("application_type", list_item.get("application_type"))
    seen_trips: set = set()
    concerns = []
    for c in app.get("concerns") or []:
        trips = []
        for t in c.get("trips") or []:
            tid = t.get("id")
            if tid in seen_trips:          # unique Trip ID per file
                continue
            seen_trips.add(tid)
            trips.append(_trip(t, agent_names))
        trips.sort(key=lambda x: x["id"] or 0)
        concerns.append(
            {
                "id": c.get("id"),
                "name": _s(c.get("name")),
                "role": _s(c.get("type")),
                "designation": _s(c.get("designation")),
                "phone": _s(c.get("phone")),
                "trips": trips,
            }
        )
    return {
        "id": app.get("id", list_item.get("id")),
        "file_no": _s(app.get("application_id") or list_item.get("application_id")),
        "type": config.APPLICATION_TYPE.get(atype, _s(atype)),
        "status_code": code,
        "status": config.FILE_STATUS.get(code, f"Status {code}"),
        "start_date": parse_dt(app.get("start_date") or list_item.get("start_date")),
        "sla": parse_dt(app.get("sla") or list_item.get("sla")),
        "station": _pretty(_s(app.get("station"))),
        "org": _s((app.get("group") or list_item.get("group") or {}).get("name")),
        "assigned_by": _s(app.get("assigned_by", list_item.get("assigned_by"))),
        "concerns": concerns,
    }


def file_trips(f: dict):
    for c in f["concerns"]:
        for t in c["trips"]:
            yield c, t
