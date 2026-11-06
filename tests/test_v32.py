"""v3.2: area text rule (Keraniganj Out, Panchlaish In), status-based Incomplete, one row per file."""
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from report_builder import geo  # noqa: E402
from report_builder.billing import BillRow, classify_reason, fold_complete, fold_incomplete, listed_by_status  # noqa: E402

D = datetime


def _trip(tid, code, remarks=""):
    return ({}, {"id": tid, "status_code": code, "remarks": remarks, "comment": ""})


def _row(fid, kind, tid, status_code=5, sub=None, recv=D(2026, 11, 1, 10), extra_tat=0, file_status=2):
    r = BillRow()
    r.file_id, r.file_no, r.kind, r.file_status = fid, f"F{fid}", kind, file_status
    r.trips = [_trip(tid, status_code)]
    r.receive_dt, r.extra_tat = recv, extra_tat
    if sub:
        r.status, r.submitted_at, r.sub_day = "Submitted", sub, sub.date()
    return r


# ---------------------------------------------------------------- area
def test_keraniganj_is_out_even_when_the_pin_falls_in_the_rough_dhaka_outline():
    inside = (23.80, 90.40)                                   # well inside Dhaka
    assert geo.classify_point(*inside)[0] == "In"
    t = {"lat": inside[0], "lon": inside[1], "address": "House 5, Zinzira, Keraniganj, Dhaka"}
    area, sure, _ = geo.trip_area(t)
    assert area == "Out" and not sure                         # address names a place outside the two cities -> Out (and shown for a check)
    t2 = dict(t, address="House 5, Gulshan, Dhaka")
    assert geo.trip_area(t2)[0] == "In"


def test_panchlaish_is_inside_chattogram_city_corporation():
    t = {"lat": 22.3600, "lon": 91.8250, "address": "Panchlaish, Chattogram"}
    assert geo.trip_area(t) [0] == "In"
    assert geo.trip_area({"address": "Panchlaish R/A, Chattogram"})[0] == "In"


def test_everything_outside_dhaka_and_chattogram_city_is_out():
    for place in ("Savar", "Gazipur", "Narayanganj", "Sitakunda", "Sylhet"):
        assert geo.trip_area({"address": f"Road 1, {place}"})[0] == "Out"


# ---------------------------------------------------------------- one row per file
def test_complete_shows_package_once_when_extra_and_recpv_were_submitted_with_it():
    day = D(2026, 11, 5, 12, 0)
    pk, ex, rc = _row(1, "Package", 11, sub=day), _row(1, "Extra", 12, sub=day), _row(1, "ReCpv", 13, sub=day)
    other = _row(2, "Package", 21, sub=day)
    out = fold_complete([pk, ex, rc, other])
    assert [(r.file_no, r.kind) for r in out] == [("F1", "Package"), ("F2", "Package")]
    assert sorted(k for k, _t in out[0].folded) == ["Extra", "ReCpv"]


def test_complete_shows_the_recpv_row_when_only_a_recpv_was_submitted():
    ex, rc = _row(3, "Extra", 31, sub=D(2026, 11, 5, 10)), _row(3, "ReCpv", 32, sub=D(2026, 11, 5, 14))
    out = fold_complete([ex, rc])
    assert [r.kind for r in out] == ["ReCpv"] and out[0].folded == [("Extra", 31)]


def test_complete_keeps_package_and_single_bills_but_not_a_second_listing_per_day():
    day = D(2026, 11, 5, 12, 0)
    out = fold_complete([_row(4, "Package", 41, sub=day), _row(4, "Single", 42, sub=day), _row(4, "ReCpv", 43, sub=day)])
    assert sorted(r.kind for r in out) == ["Package", "Single"]


def test_incomplete_is_one_row_per_file_the_most_overdue_one():
    a = _row(5, "ReCpv", 51, status_code=2, recv=D(2026, 11, 4), extra_tat=0)
    b = _row(5, "Package", 52, status_code=2, recv=D(2026, 10, 20), extra_tat=9)
    keep = fold_incomplete([a, b])
    assert keep is b and keep.folded == [("ReCpv", 51)]


# ---------------------------------------------------------------- status-based Incomplete
def test_listing_by_file_status():
    ongoing_ok = [_row(6, "Package", 61, status_code=2, extra_tat=0)]
    ongoing_late = [_row(6, "Package", 61, status_code=2, extra_tat=3)]
    hold = [_row(6, "Package", 61, status_code=4, extra_tat=0, file_status=3)]
    finished = [_row(6, "Package", 61, status_code=5, extra_tat=0, file_status=4)]
    assert not listed_by_status(ongoing_ok, "pending")            # running, SLA not breached -> not late
    assert listed_by_status(ongoing_late, "pending")
    assert listed_by_status(hold, "pending")                      # Hold is always listed ...
    assert listed_by_status(finished, "pending")                  # ... and so is Finished-but-not-submitted
    partial = [_row(6, "Package", 61, status_code=2, extra_tat=0, file_status=6)]      # Submitted now, but "Partially Submitted" at the report time
    assert listed_by_status(partial, "partial")                   # Partially Submitted always


def test_reason_is_worked_out_over_the_whole_file():
    pk = _row(7, "Package", 71, status_code=5, file_status=3)
    hold_row = _row(7, "Extra", 72, status_code=4, file_status=3)
    hold_row.trips = [({}, {"id": 72, "status_code": 4, "remarks": "", "comment": "Applicant abroad until 12 Nov"})]
    classify_reason(pk, [pk, hold_row])
    assert pk.reason_kind == "hold" and pk.reason == "Hold: Applicant abroad until 12 Nov"
