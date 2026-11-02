"""Controlled scenario for the v2 (Prime Bank report) tests.  Report date = 2026-11-02, look-back 30 days.

Expected result (tracker mode, 2026-11-02):
  Complete   (submitted on 2026-11-02): F1 Re-CPV, F2 Package, F4 Extra(LOI), F6 Package + 2 Singles   = 6 rows
  Incomplete (not submitted)          : F3 Package (Partially Submitted), F5 Re-CPV (trip not finished) = 2 rows
  F1 Package / F1 Single were submitted on 2026-10-29, so they are in neither list for that day.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

ORG = "24e11bd5-0000-0000-0000-b0d45b4c20b0"
GULSHAN = ("23.7925", "90.4078")
MIRPUR = ("23.8069", "90.3686")
SAVAR = ("23.8583", "90.2667")


def trip(tid, cid, ttype, status, created, remarks="", comment="", loc=GULSHAN, appts=None):
    return {"id": tid, "concern_id": cid, "type": ttype, "status": status, "created_at": created,
            "remarks": remarks, "comment": comment, "latitude": loc[0], "longitude": loc[1],
            "address": f"House {tid}, Dhaka", "exact_address": "", "area": "", "place_name": "",
            "is_for_recpv": 0, "is_address_exact": 1, "assigned_by": "Mgr", "agent": {"id": 1, "name": "Verifier"},
            "appointments": appts, "start_time": None, "end_time": created if status == 5 else None}


def concern(cid, fid, ctype, name, trips):
    return {"id": cid, "application_id": fid, "type": ctype, "name": name, "designation": "OFFICER",
            "phone": "01700000000", "trips": trips}


def application(fid, no, start, status, concerns, atype=1):
    return {"id": fid, "application_id": no, "application_type": atype, "start_date": start, "created_at": start,
            "status": status, "sla": "2026-11-10 10:00:00", "is_verified": 0, "station": "IN_STATION",
            "group_uuid": ORG, "is_download_enabled": 1, "assigned_by": 1, "issues": [],
            "group": {"id": 40, "uuid": ORG, "name": "Prime Bank PLC"}, "concerns": concerns, "attachments": [], "ocrs": []}


OK = "Information ok. Address is ok."


def build():
    d = "2026-10-26 10:00:00"
    f1 = application(500001, "PL-20261026000001", d, 6, [
        concern(5000011, 500001, "APPLICANT", "ALPHA ONE", [
            trip(700010, 5000011, "HOUSE", 5, d, OK), trip(700011, 5000011, "OFFICE", 5, d, "Information ok. LOI signed in front of me."),
            trip(700012, 5000011, "DOCUMENT", 5, d, "Information ok.", "LOI VERIFICATION"), trip(700013, 5000011, "BANK", 5, d, "Bank statement verified. Hard copy provided."),
            trip(700015, 5000011, "DOCUMENT", 5, "2026-10-26 10:00:05", "Chamber verified done. Information ok.", "CHAMBER VERIFICATION"),
            trip(700030, 5000011, "HOUSE", 5, "2026-10-30 12:00:00", "Information ok. House verified again.")]),
        concern(5000012, 500001, "GUARANTOR", "BETA ONE", [trip(700014, 5000012, "GUARANTOR_HOUSE", 5, d, OK, loc=SAVAR)])])
    f2 = application(500002, "CC-20261101000002", "2026-11-01 11:00:00", 6, [
        concern(5000021, 500002, "APPLICANT", "GAMMA TWO", [
            trip(700040, 5000021, "HOUSE", 5, "2026-11-01 11:00:00", "Information ok. Applicant signed in front of me."),
            trip(700041, 5000021, "OFFICE", 5, "2026-11-01 11:00:00",
                 "Information ok. LOI signed in front of me. Head office does not verify the LOI, can be verified from branch."),
            trip(700042, 5000021, "BANK", 6, "2026-11-01 11:00:00", "")])], atype=2)
    f3 = application(500003, "PL-20261020000003", "2026-10-20 09:00:00", 7, [
        concern(5000031, 500003, "APPLICANT", "DELTA THREE", [
            trip(700050, 5000031, "HOUSE", 5, "2026-10-20 09:00:00", OK),
            trip(700051, 5000031, "OFFICE", 2, "2026-10-20 09:00:00", "", appts=[{
                "id": 1, "task_id": 700051, "appointment_time": "2026-11-04 12:00:00", "appointment_type": "VISIT_PLACE",
                "reason": "Applicant not available at office", "is_active": 1, "created_at": "2026-11-01 10:00:00"}])])])
    f4 = application(500004, "CC-20260115000004", "2026-01-15 10:00:00", 6, [
        concern(5000041, 500004, "APPLICANT", "EPSILON FOUR", [
            trip(650001, 5000041, "HOUSE", 5, "2026-01-15 10:00:00", OK),
            trip(700090, 5000041, "DOCUMENT", 5, "2026-10-31 11:00:00", "Information ok. LOI signed in front of me.", "LOI VERIFICATION")])], atype=2)
    f5 = application(500005, "PL-20250901000005", "2025-09-01 10:00:00", 2, [
        concern(5000051, 500005, "APPLICANT", "ZETA FIVE", [
            trip(650002, 5000051, "HOUSE", 5, "2025-09-01 10:00:00", OK),
            trip(690000, 5000051, "OFFICE", 2, "2026-10-28 15:00:00", "")])])
    t6 = "2026-10-27 12:00:00"
    f6 = application(500006, "CC--20261027000006", t6, 6, [
        concern(5000061, 500006, "APPLICANT", "ETA SIX", [
            trip(700060, 5000061, "HOUSE", 5, t6, OK, loc=SAVAR), trip(700061, 5000061, "OFFICE", 5, t6, "Information ok. Applicant sign in front of me.", loc=SAVAR),
            trip(700062, 5000061, "BANK", 5, t6, "Bank statement verified. Hard copy provided."),
            trip(700063, 5000061, "BANK", 5, t6, "Bank statement not verified. Applicant call not received."),
            trip(700064, 5000061, "DOCUMENT", 5, t6, "Information ok.", "CHAMBER VERIFICATION"),
            trip(700065, 5000061, "DOCUMENT", 5, "2026-10-27 12:00:09", "Information ok. LOI signed in front of me.", "LOI VERIFICATION"),
            trip(700066, 5000061, "BANK", 5, "2026-10-27 12:00:10", "Bank statement verified. Hard copy provided.")])], atype=2)
    return [f1, f2, f3, f4, f5, f6]


TRACKS = [
    {"id": 9001, "application_id": 500001, "type": "REGULAR", "reason": "ReCPV House Verification", "created_at": "2026-10-30 12:00:00",
     "application": {"id": 500001, "application_id": "PL-20261026000001", "applicant": {"name": "ALPHA ONE"}}, "trips": [{"id": 700030, "re_cpv_tracker_id": 9001}]},
    {"id": 9002, "application_id": 500005, "type": "REGULAR", "reason": "LOI Re CPV", "created_at": "2026-10-28 15:00:00",
     "application": {"id": 500005, "application_id": "PL-20250901000005", "applicant": {"name": "ZETA FIVE"}}, "trips": [{"id": 690000, "re_cpv_tracker_id": 9002}]},
]


def _utc(dhaka: str) -> str:
    return (datetime.strptime(dhaka, "%Y-%m-%d %H:%M:%S") - timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _log(entity, eid, activity, prev=None, cur=None, when=""):
    return {"activity": activity, "entity_type": entity, "entity_id": eid, "previous_data": prev, "current_data": cur,
            "created_at": _utc(when), "causer_name": "Mgr"}


LOGS = {
    500001: [_log("APPLICATION", 500001, "Application created", when="2026-10-26 10:00:00"),
             _log("APPLICATION", 500001, "Application : 500001 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-10-29 14:00:00"),
             _log("TRIP", 700030, "Trip : 700030 FINISHED", when="2026-10-31 12:00:00"),
             _log("APPLICATION", 500001, "Application : 500001 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-11-02 16:30:00")],
    500002: [_log("APPLICATION", 500002, "Application : 500002 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-11-02 11:00:00")],
    500003: [_log("APPLICATION", 500003, "Application : 500003 status updated to PARTIALLY_SUBMITTED by Mgr", "HOLD", "PARTIALLY_SUBMITTED", "2026-10-30 10:00:00")],
    500004: [_log("APPLICATION", 500004, "Application : 500004 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-01-17 10:00:00"),
             _log("TRIP", 700090, "Trip : 700090 FINISHED", when="2026-11-01 10:00:00"),
             _log("APPLICATION", 500004, "Application : 500004 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-11-02 18:00:00")],
    500005: [], 
    500006: [_log("APPLICATION", 500006, "Application : 500006 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-11-02 09:00:00")],
}


def list_item(f):
    return {k: f[k] for k in ("id", "application_id", "is_verified", "status", "start_date", "application_type", "sla",
                              "group_uuid", "assigned_by", "issues", "group")} | {
        "concerns": [{k: v for k, v in c.items() if k != "trips"} for c in f["concerns"]],
        "trips": [{"id": t["id"], "type": t["type"], "status": t["status"]} for c in f["concerns"] for t in c["trips"]]}


def handle(h, p, q):
    """-> True if the request was answered here."""
    files = h.server_files
    if p == "/api/v2/manager/applications":
        a, b = q["dateFrom"][0], q["dateTill"][0]
        sel = [f for f in files if a <= f["start_date"][:10] <= b]
        sel.sort(key=lambda f: f["id"])
        page = int(q.get("page", ["1"])[0])
        chunk = sel[(page - 1) * 50: page * 50]
        h._send(200, {"applications": {"current_page": page, "data": [list_item(f) for f in chunk],
                                       "last_page": max(1, -(-len(sel) // 50)), "per_page": 50, "total": len(sel)}})
        return True
    if p == "/api/v2/re-cpv/tracker":
        assert q.get("org_id") == [ORG], q
        a, b = q["dateFrom"][0], q["dateTill"][0]
        h._send(200, {"data": {"re_cpv_tracks": [t for t in TRACKS if a <= t["created_at"][:10] <= b]}, "message": "Success", "status": 200})
        return True
    if p == "/api/v2/applications/activity-logs":
        fid = int(q["application_id"][0])
        h._send(200, {"data": {"activity_logs": LOGS.get(fid, [])}})
        return True
    return False
