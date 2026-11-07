"""v3.3: an appointment RESTARTS the SLA - 2 (In) / 4 (Out) working days again from the scheduled date of the latest appointment."""
import sys
from datetime import date, datetime as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_builder.billing import BillRow, compute_tat, sla_start_for  # noqa: E402

# 2026-10-26 Mon | 11-09 Mon, 11-10 Tue, 11-11 Wed, 11-12 Thu, 11-13 Fri, 11-14 Sat, 11-15 Sun, 11-16 Mon, 11-17 Tue, 11-18 Wed
NO_HOLIDAYS: set = set()


def _appt(sched, created, trip_id=1):
    return {"trip_id": trip_id, "trip_type": "House", "time": sched, "type": "", "reason": "", "created_at": created, "active": True}


def _row(area="In", appts=(), sub=None, receive=D(2026, 10, 26, 10, 0)):
    r = BillRow()
    r.receive_dt, r.area, r.appointments = receive, area, list(appts)
    if sub:
        r.status, r.submitted_at, r.sub_day = "Submitted", sub, sub.date()
    return r


def _tat(r, report_date=date(2026, 11, 18), hol=NO_HOLIDAYS):
    compute_tat(r, report_date, hol)
    return r


def test_without_an_appointment_the_clock_starts_at_the_receive_date_as_before():
    r = _tat(_row("In", sub=D(2026, 10, 29, 12, 0)))
    assert r.sla_start == date(2026, 10, 26) and r.sla_appt is None
    assert (r.tat, r.sla_days, r.extra_tat, r.sla_breach) == (3, 2, 1, True)       # Tue, Wed, Thu are 3 working days after Mon


def test_an_appointment_restarts_the_sla_from_its_scheduled_date_in_area():
    ap = [_appt(D(2026, 11, 11, 15, 0), D(2026, 11, 2, 11, 0))]                    # asked on 02 Nov for Wed 11 Nov
    ok = _tat(_row("In", ap, D(2026, 11, 15, 12, 0)))                              # Thu 12 (1), Sun 15 (2)
    assert ok.sla_start == date(2026, 11, 11) and ok.sla_appt == date(2026, 11, 11)
    assert (ok.tat, ok.extra_tat, ok.sla_breach) == (2, 0, False)
    late = _tat(_row("In", ap, D(2026, 11, 16, 12, 0)))                            # Mon 16 = the 3rd working day
    assert (late.tat, late.extra_tat, late.sla_breach) == (3, 1, True)


def test_out_area_gets_four_working_days_from_the_appointment_date():
    ap = [_appt(D(2026, 11, 9, 11, 0), D(2026, 11, 1, 10, 0))]
    ok = _tat(_row("Out", ap, D(2026, 11, 15, 12, 0)))                             # Tue 10, Wed 11, Thu 12, Sun 15 = 4
    assert (ok.sla_days, ok.tat, ok.sla_breach) == (4, 4, False)
    late = _tat(_row("Out", ap, D(2026, 11, 16, 12, 0)))
    assert (late.tat, late.sla_breach) == (5, True)


def test_a_friday_saturday_or_holiday_appointment_date_moves_to_the_next_working_day():
    fri = _tat(_row("In", [_appt(D(2026, 11, 13, 10, 0), D(2026, 11, 2, 9, 0))], D(2026, 11, 17, 12, 0)))
    assert fri.sla_start == date(2026, 11, 15) and fri.sla_appt == date(2026, 11, 13)       # Friday -> Sunday
    assert (fri.tat, fri.sla_breach) == (2, False)                                           # Mon 16, Tue 17
    assert _tat(_row("In", [_appt(D(2026, 11, 13, 10, 0), D(2026, 11, 2, 9, 0))], D(2026, 11, 18, 12, 0))).sla_breach
    sat = _tat(_row("In", [_appt(D(2026, 11, 14, 10, 0), D(2026, 11, 2, 9, 0))]))
    assert sat.sla_start == date(2026, 11, 15)
    off = _tat(_row("In", [_appt(D(2026, 11, 11, 10, 0), D(2026, 11, 2, 9, 0))]), hol={date(2026, 11, 11)})
    assert off.sla_start == date(2026, 11, 12)                                               # a public holiday


def test_the_latest_created_appointment_decides_not_the_latest_scheduled_one():
    ap = [_appt(D(2026, 11, 20, 10, 0), D(2026, 11, 2, 9, 0)), _appt(D(2026, 11, 11, 10, 0), D(2026, 11, 3, 9, 0), trip_id=2)]
    assert _tat(_row("In", ap)).sla_start == date(2026, 11, 11)


def test_an_appointment_given_after_the_submission_or_before_the_receive_date_changes_nothing():
    sub = D(2026, 10, 29, 12, 0)
    r = _tat(_row("In", [_appt(D(2026, 11, 11, 10, 0), D(2026, 10, 30, 9, 0))], sub))      # created the day after it was submitted
    assert r.sla_start == date(2026, 10, 26) and r.sla_appt is None and r.sla_breach
    early = _tat(_row("In", [_appt(D(2026, 10, 20, 10, 0), D(2026, 10, 19, 9, 0))], sub))
    assert early.sla_start == date(2026, 10, 26) and early.sla_appt is None


def test_a_pending_row_is_counted_up_to_the_report_date_from_the_restart():
    ap = [_appt(D(2026, 11, 11, 10, 0), D(2026, 11, 2, 9, 0))]
    r = _tat(_row("In", ap), report_date=date(2026, 11, 12))                                 # Thu 12 = day 1
    assert (r.tat, r.sla_breach) == (1, False)
    future = _tat(_row("In", ap), report_date=date(2026, 11, 5))                             # the appointment day has not come yet
    assert future.sla_start == date(2026, 11, 11) and (future.tat, future.sla_breach) == (0, False)
    # an appointment that is created later does not exist yet in a report of an earlier day
    later = _tat(_row("In", [_appt(D(2026, 11, 11, 10, 0), D(2026, 11, 9, 9, 0))]), report_date=date(2026, 11, 5))
    assert later.sla_appt is None and later.sla_start == date(2026, 10, 26)


def test_sla_start_for_without_receive_date():
    r = _row("In")
    r.receive_dt = None
    assert sla_start_for(r, date(2026, 11, 8), NO_HOLIDAYS) == (None, None)
    compute_tat(r, date(2026, 11, 8), NO_HOLIDAYS)
    assert r.tat is None and r.sla_start is None
