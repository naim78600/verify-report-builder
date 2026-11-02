"""Read-only: the Re-CPV tracker (last year) indexed by trip id and by file number."""
from __future__ import annotations

from datetime import date

from .model import parse_dt


def fetch_tracker(client, org_uuid: str, d_from: date, d_till: date) -> list[dict]:
    raw = client.get("/api/v2/re-cpv/tracker", [("dateFrom", d_from.isoformat()), ("dateTill", d_till.isoformat()),
                                                 ("org_id", org_uuid)])
    tracks = ((raw or {}).get("data") or {}).get("re_cpv_tracks") or []
    out = []
    for t in tracks:
        app = t.get("application") or {}
        out.append({
            "id": t.get("id"),
            "app_id": t.get("application_id") or app.get("id"),
            "file_no": str(app.get("application_id") or "").strip(),
            "reason": str(t.get("reason") or "").strip(),
            "created_at": parse_dt(t.get("created_at")),
            "trip_ids": [x.get("id") for x in (t.get("trips") or []) if x.get("id") is not None],
            "applicant": ((app.get("applicant") or {}).get("name") or "").strip(),
        })
    return out


def index(tracks: list[dict]) -> tuple[dict, dict]:
    by_trip: dict = {}
    by_file: dict = {}
    for t in tracks:
        for tid in t["trip_ids"]:
            by_trip[tid] = t
        by_file.setdefault(t["file_no"].upper(), []).append(t)
    return by_trip, by_file
