"""A big synthetic Prime Bank workload (1000+ files, 90 days) for the volume / blank-result tests.

Every file is ONE In-station (Gulshan) Package row, so the expected report can be worked out here independently of
the program's own code (plain Python date arithmetic, Friday + Saturday off, the program's holiday list as input).
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

import prime_scenario as ps

SUBMITTED, ONGOING, HOLD, PARTIAL, CANCELED = 6, 2, 3, 7, 5
HOLD_TEXT = "Applicant is abroad, will return next week. Verification put on hold as requested."


def working_days(lo: date, hi: date, holidays: set) -> int:
    """NETWORKDAYS.INTL(lo, hi, "0000110") - Friday and Saturday off."""
    n, d = 0, lo
    while d <= hi:
        if d.weekday() not in (4, 5) and d not in holidays:
            n += 1
        d += timedelta(days=1)
    return n


def build(n: int = 1100, report: date = date(2026, 11, 2), seed: int = 7):
    """-> list of dicts: {file (application json), id, no, start (datetime), status, sub (datetime|None), partial (datetime|None)}.
    Fills prime_scenario.LOGS for every file."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        fid = 600000 + i
        start_day = report - timedelta(days=rnd.randint(-2, 118))          # a few after the report day, some older than 90 days
        start = datetime.combine(start_day, time(rnd.randint(9, 16), rnd.choice((0, 15, 30, 45))))
        no = f"PL-{start:%Y%m%d}{i:06d}"
        kind = rnd.random()
        sub = partial = None
        if kind < 0.52:
            status, trip_status = SUBMITTED, 5
            sub_day = max(start_day, report - timedelta(days=rnd.randint(0, 40))) if rnd.random() < 0.35 else \
                start_day + timedelta(days=rnd.randint(0, 6))
            sub = datetime.combine(sub_day, time(rnd.randint(9, 21), rnd.choice((0, 10, 20, 40, 50))))
            if sub < start + timedelta(hours=1):
                sub = start + timedelta(hours=1)
        elif kind < 0.66:
            status, trip_status = ONGOING, rnd.choice((2, 3))
        elif kind < 0.75:
            status, trip_status = HOLD, 4
        elif kind < 0.86:
            status, trip_status = PARTIAL, 5
            partial = start + timedelta(days=rnd.randint(0, 9), hours=rnd.randint(1, 6))
        elif kind < 0.92:
            status, trip_status = CANCELED, 6
        else:                                                              # submitted AFTER the report day
            status, trip_status = SUBMITTED, 5
            sub = datetime.combine(report + timedelta(days=rnd.randint(1, 4)), time(rnd.randint(9, 20), 30))
        created = f"{start:%Y-%m-%d %H:%M:%S}"
        remarks = HOLD_TEXT if status == HOLD else (ps.OK if trip_status == 5 else "")
        trips = [ps.trip(800000 + i * 3, 700000 + i, "HOUSE", trip_status, created, remarks)]
        if status == PARTIAL:
            trips.append(ps.trip(800000 + i * 3 + 1, 700000 + i, "OFFICE", 2, created, ""))
        f = ps.application(fid, no, created, status, [ps.concern(700000 + i, fid, "APPLICANT", f"APPLICANT {i:04d}", trips)])
        logs = [ps._log("APPLICATION", fid, f"Application created", when=created)]
        if partial:
            logs.append(ps._log("APPLICATION", fid, f"Application : {fid} status updated to PARTIAL_SUBMITTED by Mgr", "HOLD",
                                "PARTIAL_SUBMITTED", f"{partial:%Y-%m-%d %H:%M:%S}"))
        if sub:
            logs.append(ps._log("APPLICATION", fid, f"Application : {fid} status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED",
                                f"{sub:%Y-%m-%d %H:%M:%S}"))
        ps.LOGS[fid] = logs
        out.append({"file": f, "id": fid, "no": no, "start": start, "status": status, "sub": sub, "partial": partial})
    return out


def expected(items, report: date, slot: str, holidays: set, after3_only: bool = False, lookback: int = 90):
    """(complete file numbers, incomplete file numbers) of the tracker, from the written rules (see README v3)."""
    prev = report - timedelta(days=1)
    while prev.weekday() in (4, 5) or prev in holidays:
        prev -= timedelta(days=1)
    t_lo = prev + timedelta(days=1)
    cutoff = datetime.combine(report, time(15, 0))
    complete, incomplete = set(), set()
    for it in items:
        sub, start = it["sub"], it["start"]
        reported = sub                                                      # reported day: a day-off submission moves to the next working day
        if sub:
            rd = sub.date()
            while rd.weekday() in (4, 5) or rd in holidays:
                rd += timedelta(days=1)
            reported = datetime.combine(rd, sub.time())
        done_by_report = bool(sub) and sub.date() <= report
        late_hour = (slot == "3pm" and bool(sub) and sub.date() == report and sub >= cutoff and rd == sub.date())
        if done_by_report and not late_hour:
            if t_lo <= reported.date() <= report:
                if after3_only and (reported.date() != sub.date() or sub.time() < time(15, 0)):   # a rolled row counts as "before 3 PM"
                    continue
                complete.add(it["no"])
            continue
        # pending as of the report
        if it["status"] in (CANCELED, 8):
            continue
        if start.date() > report or start.date() < report - timedelta(days=lookback):
            continue
        tat = max(0, working_days(start.date() + timedelta(days=1), report, holidays))
        partial_open = bool(it["partial"]) and it["partial"].date() <= report and not (sub and it["partial"] < sub and sub.date() <= report)
        # v3.2.1: by the status of the file at that moment - ONLY Partially Submitted / Hold / Finished-but-not-Submitted are listed;
        # a file that is still On Going / Created (or became Partially Submitted only later) is running and never listed, SLA or not
        kind = "partial" if partial_open else {HOLD: "hold", ONGOING: "ongoing", PARTIAL: "ongoing", SUBMITTED: "finished"}[it["status"]]
        if kind in ("partial", "hold", "finished"):
            incomplete.add(it["no"])
    return complete, incomplete
