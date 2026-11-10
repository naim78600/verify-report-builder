"""v3.3: an appointment RESTARTS the SLA from the scheduled date of the latest appointment.
v6: the report is then due on the next working day by 5:59 PM, In and Out alike."""
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


def test_after_an_appointment_the_report_is_due_the_next_working_day_by_5_59_pm():
    """v6: scheduled date + 1 working day, 5:59 PM - whatever the area."""
    ap = [_appt(D(2026, 11, 11, 15, 0), D(2026, 11, 2, 11, 0))]                    # asked on 02 Nov for Wed 11 Nov
    ok = _tat(_row("In", ap, D(2026, 11, 12, 17, 59)))                             # Thu 12, 5:59 PM = on time
    assert ok.sla_start == date(2026, 11, 11) and ok.sla_appt == date(2026, 11, 11)
    assert (ok.sla_days, ok.tat, ok.extra_tat, ok.sla_breach) == (1, 1, 0, False)
    same_day = _tat(_row("In", ap, D(2026, 11, 11, 16, 0)))                        # submitted on the appointment day itself
    assert (same_day.tat, same_day.extra_tat, same_day.sla_breach) == (0, 0, False)
    evening = _tat(_row("In", ap, D(2026, 11, 12, 18, 0)))                         # the due day, but after 5:59 PM
    assert evening.appt_late and (evening.tat, evening.extra_tat, evening.sla_breach) == (1, 1, True)
    late = _tat(_row("In", ap, D(2026, 11, 15, 12, 0)))                            # Sun 15 = the 2nd working day
    assert (late.tat, late.extra_tat, late.sla_breach) == (2, 1, True)


def test_in_and_out_area_get_the_same_one_day_after_an_appointment():
    ap = [_appt(D(2026, 11, 9, 11, 0), D(2026, 11, 1, 10, 0))]
    ok = _tat(_row("Out", ap, D(2026, 11, 10, 12, 0)))                             # Tue 10
    assert (ok.sla_days, ok.tat, ok.sla_breach) == (1, 1, False)
    late = _tat(_row("Out", ap, D(2026, 11, 11, 12, 0)))
    assert (late.tat, late.extra_tat, late.sla_breach) == (2, 1, True)
    plain = _tat(_row("Out", sub=D(2026, 10, 29, 12, 0)))                          # no appointment: Out still has 4 working days
    assert (plain.sla_days, plain.sla_breach) == (4, False)


def test_a_friday_saturday_or_holiday_after_the_appointment_is_not_counted():
    thu = [_appt(D(2026, 11, 12, 10, 0), D(2026, 11, 2, 9, 0))]                    # Thursday appointment -> due Sunday 15
    r = _tat(_row("In", thu, D(2026, 11, 15, 17, 0)))
    assert r.sla_start == date(2026, 11, 12) and (r.tat, r.sla_breach) == (1, False)
    assert _tat(_row("In", thu, D(2026, 11, 16, 12, 0))).sla_breach                # Monday = one day late
    fri = _tat(_row("In", [_appt(D(2026, 11, 13, 10, 0), D(2026, 11, 2, 9, 0))], D(2026, 11, 15, 12, 0)))
    assert fri.sla_start == date(2026, 11, 13) and fri.sla_appt == date(2026, 11, 13)       # a Friday appointment: due Sunday too
    assert (fri.tat, fri.sla_breach) == (1, False)
    off = _tat(_row("In", [_appt(D(2026, 11, 11, 10, 0), D(2026, 11, 2, 9, 0))], D(2026, 11, 15, 12, 0)), hol={date(2026, 11, 12)})
    assert (off.tat, off.sla_breach) == (1, False)                                           # Thu 12 is a holiday -> due Sunday 15


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
    assert sla_start_for(r, date(2026, 11, 8), NO_HOLIDAYS) == (None, None, None)
    compute_tat(r, date(2026, 11, 8), NO_HOLIDAYS)
    assert r.tat is None and r.sla_start is None
