"""v4.0.0: ANY new trip (Re-CPV, additional / Extra document trip, ...) RESTARTS the SLA at once - In 2 / Out 4 working days again from
the day the trip was created.  The SLA is the file's: the other bill rows of the file count too (only what existed at the time)."""
import sys
from datetime import date, datetime as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from report_builder.billing import BillRow, compute_tat, fold_complete, fold_incomplete, link_siblings, retime_folded  # noqa: E402
from report_builder.report_text import sla_restart_lines  # noqa: E402
from test_v33 import NO_HOLIDAYS, _appt  # noqa: E402

# 2026-11-02 Mon | 11-05 Thu | 11-08 Sun | 11-09 Mon | 11-10 Tue | 11-11 Wed | 11-12 Thu  (Fri + Sat are days off)


def _trip(tid, created, status=5):
    return {"id": tid, "created_at": created, "status_code": status, "type_code": "HOUSE", "appointments": []}


def _bill(kind, tid, created, area="Out", status="Incomplete", sub=None, fid=1, trip_status=5, appts=()):
    r = BillRow()
    r.file_id, r.file_no, r.kind, r.area, r.status = fid, "PL-%d" % fid, kind, area, status
    r.receive_dt = created
    r.trips = [({"role": "APPLICANT"}, _trip(tid, created, trip_status))]
    r.appointments = list(appts)
    if sub:
        r.status, r.submitted_at, r.sub_day = "Submitted", sub, sub.date()
    return r


def _shown(rows, report_date=date(2026, 11, 10)):
    retime_folded(rows, report_date, NO_HOLIDAYS)
    return rows


def _tat(r, report_date=date(2026, 11, 8)):
    compute_tat(r, report_date, NO_HOLIDAYS)
    return r


def test_a_recpv_row_counts_from_its_own_creation_day():
    r = _tat(_bill("ReCpv", 501246, D(2026, 11, 5, 10, 37)), date(2026, 11, 7))
    assert r.sla_start == date(2026, 11, 5) and r.sla_trip is None and r.tat == 0 and not r.sla_breach


def test_a_recpv_submitted_with_the_package_restarts_the_shown_row():
    sub = D(2026, 11, 10, 12, 0)
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="Out", sub=sub)
    rc = _bill("ReCpv", 2, D(2026, 11, 5, 10, 0), area="Out", sub=sub)
    assert _tat(pk, date(2026, 11, 10)).sla_breach              # alone: 11-03 .. 11-10 = 5 working days > 4
    out = _shown(fold_complete([pk, rc]))
    assert len(out) == 1 and out[0] is pk
    assert out[0].sla_start == date(2026, 11, 5) and out[0].sla_trip == date(2026, 11, 5) and out[0].sla_appt is None
    assert out[0].sla_restarted and out[0].sla_why == "new trip"
    assert out[0].tat == 3 and not out[0].sla_breach             # Sun 8, Mon 9, Tue 10


def test_an_extra_document_trip_restarts_the_sla_too():
    sub = D(2026, 11, 10, 12, 0)
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="Out", sub=sub)
    ex = _bill("Extra", 2, D(2026, 11, 5, 10, 0), area="Out", sub=sub)
    out = _shown(fold_complete([pk, ex]))
    assert out[0].sla_start == date(2026, 11, 5) and out[0].sla_trip == date(2026, 11, 5) and out[0].sla_why == "new trip"
    assert out[0].tat == 3 and not out[0].sla_breach


def test_a_single_extra_trip_row_counts_from_its_own_creation_day():
    r = _tat(_bill("Extra", 7, D(2026, 11, 5, 10, 0), area="In"), date(2026, 11, 8))
    assert r.sla_start == date(2026, 11, 5) and r.tat == 1 and not r.sla_breach


def test_the_sla_is_the_files_a_sibling_row_submitted_on_another_day_counts_too():
    # Package submitted Sun 08; an Extra trip was created Thu 05 and is submitted later (another day = another row)
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="In", sub=D(2026, 11, 8, 12, 0))
    ex = _bill("Extra", 2, D(2026, 11, 5, 10, 0), area="In", sub=D(2026, 11, 12, 12, 0))
    link_siblings([pk, ex])
    r = _tat(pk, date(2026, 11, 12))
    assert r.sla_start == date(2026, 11, 5) and r.sla_trip == date(2026, 11, 5) and r.tat == 1 and not r.sla_breach
    assert _tat(ex, date(2026, 11, 12)).sla_start == date(2026, 11, 5)
    pk.file_rows = []                                   # without the sibling: counted from 02/11 = 4 working days > 2
    assert _tat(pk, date(2026, 11, 12)).sla_breach


def test_a_sibling_created_after_the_submission_does_not_touch_the_submitted_row():
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="In", sub=D(2026, 11, 5, 12, 0))
    ex = _bill("Extra", 2, D(2026, 11, 9, 10, 0), area="In")
    link_siblings([pk, ex])
    assert _tat(pk, date(2026, 11, 10)).sla_start == date(2026, 11, 2)


def test_a_new_trip_on_the_same_day_as_the_file_changes_nothing():
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="In")
    pk.file_rows.append(_bill("Extra", 2, D(2026, 11, 2, 15, 0), area="In"))
    r = _tat(pk, date(2026, 11, 8))
    assert r.sla_start == date(2026, 11, 2) and not r.sla_restarted


def test_a_dead_recpv_trip_does_not_restart_the_sla():
    sub = D(2026, 11, 10, 12, 0)
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), sub=sub)
    rc = _bill("ReCpv", 2, D(2026, 11, 5, 10, 0), sub=sub, trip_status=7)
    out = _shown(fold_complete([pk, rc]))
    assert out[0].sla_start == date(2026, 11, 2) and not out[0].sla_restarted


def test_a_recpv_created_after_the_submission_does_not_touch_the_submitted_row():
    sub = D(2026, 11, 5, 12, 0)
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="In", sub=sub)
    rc = _bill("ReCpv", 2, D(2026, 11, 9, 10, 0), area="In")
    pk.folded_rows.append(rc)
    assert _tat(pk, date(2026, 11, 10)).sla_start == date(2026, 11, 2)


def test_the_latest_of_appointment_and_new_trip_wins():
    sub = D(2026, 11, 12, 12, 0)
    ap = _appt(D(2026, 11, 11, 13, 0), D(2026, 11, 3, 10, 0))
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), sub=sub, appts=[ap])
    rc = _bill("ReCpv", 2, D(2026, 11, 5, 10, 0), sub=sub)
    pk.folded_rows.append(rc)
    r = _tat(pk, date(2026, 11, 12))
    assert r.sla_start == date(2026, 11, 11) and r.sla_appt == date(2026, 11, 11) and r.sla_trip is None
    ap2 = _appt(D(2026, 11, 4, 13, 0), D(2026, 11, 3, 10, 0))
    pk2 = _bill("Package", 3, D(2026, 11, 2, 9, 0), sub=sub, appts=[ap2])
    pk2.folded_rows.append(_bill("ReCpv", 4, D(2026, 11, 5, 10, 0), sub=sub))
    r2 = _tat(pk2, date(2026, 11, 12))
    assert r2.sla_start == date(2026, 11, 5) and r2.sla_trip == date(2026, 11, 5) and r2.sla_appt is None


def test_an_appointment_given_on_the_folded_recpv_counts_for_the_shown_row():
    sub = D(2026, 11, 12, 12, 0)
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), sub=sub)
    rc = _bill("ReCpv", 2, D(2026, 11, 3, 10, 0), sub=sub, appts=[_appt(D(2026, 11, 10, 13, 0), D(2026, 11, 4, 10, 0), trip_id=2)])
    out = _shown(fold_complete([pk, rc]), date(2026, 11, 12))
    assert out[0].sla_start == date(2026, 11, 10) and out[0].sla_appt == date(2026, 11, 10)


def test_a_pending_file_shows_the_restart_of_its_newest_recpv():
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="Out")
    rc = _bill("ReCpv", 2, D(2026, 11, 5, 10, 37), area="Out")
    for r in (pk, rc):
        compute_tat(r, date(2026, 11, 8), NO_HOLIDAYS)
    keep = fold_incomplete([pk, rc])
    retime_folded([keep], date(2026, 11, 8), NO_HOLIDAYS)
    assert keep is pk and keep.sla_start == date(2026, 11, 5) and keep.tat == 1 and not keep.sla_breach


def test_the_restart_note_says_new_trip_in_plain_words():
    pk = _bill("Package", 1, D(2026, 11, 2, 9, 0), area="In")
    pk.folded_rows.append(_bill("ReCpv", 2, D(2026, 11, 5, 10, 0), area="In"))
    r = _tat(pk)
    text = " ".join("".join(t for t, _s in line) for line in sla_restart_lines(r))
    assert "SLA restarted from 05/11/2026" in text and "2 working days again" in text and "new trip created on 05/11/2026" in text
