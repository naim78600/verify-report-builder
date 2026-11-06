"""v3.2.1: Report Summary = the file's LAST update (one row for several bill rows describes all their trips)."""
import sys
from datetime import datetime as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_builder.billing import BillRow, fold_complete, fold_incomplete  # noqa: E402
from report_builder.summary import TripView, analyze  # noqa: E402


def _trip(tid, code, remarks="", comment="", created=D(2026, 10, 27, 19, 20), status=5):
    return {"id": tid, "type_code": code, "status_code": status, "remarks": remarks, "comment": comment,
            "created_at": created, "appointments": []}


def _row(kind, trips, sub=None, fid=1):
    """trips = [(trip, 'App'|'PG')]"""
    r = BillRow()
    r.file_id, r.file_no, r.kind = fid, f"PL-{fid}", kind
    r.trips = [({"role": "APPLICANT"}, t) for t, _w in trips]
    r.views = [TripView(t, "GUARANTOR" if w == "PG" else "APPLICANT", w) for t, w in trips]
    if sub:
        r.status, r.submitted_at, r.sub_day = "Submitted", sub, sub.date()
    r.summary = analyze(r.views, r.submitted, "BS")
    return r


SUB = D(2026, 11, 5, 12, 5)
OFFICE_NO_LOI = ("Information ok. Confirmed Applicant's self. Applicant was present at office and signed in front of me. "
                 "Loi Panding. signatory is not available.")
LOI_OK = "Information OK. Confirmed by Receptionist. LOI signed infront of me. LOI signed by Signatory."


def _erico(loi_remark=LOI_OK):
    pk = _row("Package", [(_trip(1, "HOUSE", "Information ok. Address is ok."), "App"),
                          (_trip(2, "OFFICE", OFFICE_NO_LOI), "App"),
                          (_trip(3, "GUARANTOR_HOUSE", "Information ok.", "TAKE GUARANTOR SIGN FROM HOME"), "PG")], SUB)
    ex = _row("Extra", [(_trip(9, "DOCUMENT", loi_remark, "Loi Sing.", created=D(2026, 11, 2, 17, 47)), "App")], SUB)
    return pk, ex


def test_the_package_alone_still_says_loi_is_due_that_is_the_old_wrong_picture():
    pk, _ex = _erico()
    assert "LOI (Signatory not available)" in pk.summary.due


def test_a_later_loi_trip_submitted_with_the_package_clears_the_due():
    pk, ex = _erico()
    out = fold_complete([pk, ex])
    assert len(out) == 1 and out[0] is pk and out[0].folded == [("Extra", 9)]
    assert out[0].summary.due == "0"
    assert "LOI" in out[0].summary.done and "Signatory not available" not in out[0].summary.done
    assert "summary" not in out[0].flags


def test_the_latest_outcome_wins_also_when_it_is_the_worse_one():
    pk, ex = _erico("LOI not verified. Signatory is not available today.")
    out = fold_complete([pk, ex])
    assert "LOI" in out[0].summary.due                      # the later trip did not settle it


def test_follow_up_rows_of_another_day_are_not_mixed_in():
    pk, ex = _erico()
    ex.sub_day, ex.submitted_at = D(2026, 11, 8).date(), D(2026, 11, 8, 12, 0)
    out = fold_complete([pk, ex])
    assert len(out) == 2
    assert "LOI (Signatory not available)" in pk.summary.due


def test_a_row_without_folded_rows_keeps_its_own_summary_untouched():
    pk, _ex = _erico()
    before = (pk.summary.done, pk.summary.due)
    out = fold_complete([pk])
    assert (out[0].summary.done, out[0].summary.due) == before and out[0].folded == []


def test_items_the_row_did_not_have_are_never_added_from_the_folded_rows():
    pk = _row("Package", [(_trip(1, "HOUSE", "Information ok."), "App")], SUB)
    ex = _row("Extra", [(_trip(9, "DOCUMENT", LOI_OK, "LOI", created=D(2026, 11, 2, 17, 47)), "App"),
                        (_trip(10, "BANK", "Statement ok.", created=D(2026, 11, 2, 17, 48)), "App")], SUB)
    before = (pk.summary.done, pk.summary.due)
    out = fold_complete([pk, ex])
    assert (out[0].summary.done, out[0].summary.due) == before == ("App House", "0")


def test_only_items_that_are_due_are_replaced_the_other_done_items_stay():
    pk, ex = _erico()
    out = fold_complete([pk, ex])
    done = out[0].summary.done
    assert "App House" in done and "Office" in done and "PG House" in done


def test_an_older_trip_never_clears_a_newer_rows_due():
    newer = _row("ReCpv", [(_trip(30, "DOCUMENT", OFFICE_NO_LOI, "LOI", created=D(2026, 10, 28, 11, 36)), "App")], SUB)
    older = _row("Extra", [(_trip(5, "DOCUMENT", LOI_OK, "LOI", created=D(2026, 10, 4, 10, 46)), "App")], SUB)
    assert "LOI" in newer.summary.due
    out = fold_complete([newer, older])
    assert len(out) == 1 and out[0] is newer and "LOI" in out[0].summary.due


def test_a_pending_file_row_also_follows_its_latest_trip():
    pk = _row("Package", [(_trip(1, "HOUSE", "Information ok."), "App"),
                          (_trip(2, "OFFICE", OFFICE_NO_LOI), "App")])
    ex = _row("Extra", [(_trip(9, "DOCUMENT", LOI_OK, "Loi Sing.", created=D(2026, 11, 2, 17, 47)), "App")])
    pk.receive_dt, ex.receive_dt = D(2026, 10, 27), D(2026, 11, 2)
    assert "LOI" in pk.summary.due
    keep = fold_incomplete([pk, ex])
    assert "Signatory not available" not in keep.summary.done and "LOI" in keep.summary.done
    assert "Signatory not available" not in keep.summary.due


# ---------------------------------------------------------------- Incomplete = only Hold / Finished / Partially Submitted
def _pending(fid, file_status, status_code=2, recv=D(2026, 10, 20, 10), extra_tat=0):
    r = BillRow()
    r.file_id, r.file_no, r.kind, r.file_status = fid, f"PL-{fid}", "Package", file_status
    r.trips = [({"role": "APPLICANT"}, {"id": fid * 10, "status_code": status_code, "remarks": "", "comment": "", "appointments": [],
                                         "created_at": recv})]
    r.receive_dt, r.extra_tat = recv, extra_tat
    return r


def _select(rows, mode):
    from datetime import date
    from report_builder.billing import select_rows
    kw = dict(mode=mode, report_date=date(2026, 11, 6))
    if mode == "range":
        kw.update(w_from=date(2026, 8, 8), w_till=date(2026, 11, 6))
    else:
        kw.update(w_from=date(2026, 8, 8), hset=set())
    return select_rows(rows, **kw)[1]


def test_running_files_are_never_in_incomplete_even_past_the_sla_in_both_modes():
    running_late = _pending(1, file_status=2, extra_tat=5)         # On Going, SLA crossed
    created = _pending(2, file_status=1, extra_tat=3)               # Created, SLA crossed
    running_ok = _pending(3, file_status=2, extra_tat=0)
    hold = _pending(4, file_status=3, status_code=4)
    finished = _pending(5, file_status=4, status_code=5)
    for mode in ("range", "tracker"):
        got = sorted(r.file_no for r in _select([running_late, created, running_ok, hold, finished], mode))
        assert got == ["PL-4", "PL-5"], (mode, got)


def test_a_partially_submitted_file_is_listed_in_both_modes():
    from datetime import date
    from report_builder.billing import select_rows
    r = _pending(6, file_status=7, status_code=5)
    r.partial_events = [D(2026, 11, 5, 11, 0)]
    for mode in ("range", "tracker"):
        kw = dict(mode=mode, report_date=date(2026, 11, 6), w_from=date(2026, 8, 8), hset=set())
        if mode == "range":
            kw["w_till"] = date(2026, 11, 6)
        assert [x.file_no for x in select_rows([r], **kw)[1]] == ["PL-6"], mode
