"""V3.1 tests: Incomplete is decided PER FILE like the dashboard (a Submitted file has no pending rows), phase-1 reconciliation
with the dashboard, and the Excel must never contain characters XML forbids."""
import re
import sys
import threading
import zipfile
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402
import mock_server  # noqa: E402
import prime_scenario as ps  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from report_builder.billing import BillRow, file_state, is_dead_row  # noqa: E402
from report_builder.collect_prime import PrimeConfig, collect_prime  # noqa: E402
from report_builder.reports import write_prime_outputs  # noqa: E402

R = date(2026, 11, 2)
T0 = "2026-10-26 10:00:00"


def _run(srv, **kw):
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    cfg = dict(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
               mode="tracker", report_date=R, slot="7pm")
    cfg.update(kw)
    return collect_prime(PrimeConfig(**cfg), lambda *a: None, threading.Event())


def _sub(fid, when):
    return ps._log("APPLICATION", fid, f"Application : {fid} status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", when)


@pytest.fixture()
def extra_files():
    """Four files that copy what the live dashboard showed on 05/11/2026:
       G1 Submitted file whose old extra rows are Canceled / Inactive   -> must NOT be Incomplete (dashboard: Submitted)
       G2 Submitted, then re-opened by a new extra trip, now on Hold     -> Incomplete (only the new row)
       G3 never submitted, on Hold, with a live and a canceled extra row -> Incomplete (package + live extra; canceled row hidden)
       G4 never submitted, received on the report day, On Going          -> not listed (a running file is never listed)"""
    s = mock_server.start_scenario(0)
    cid = iter(range(9100000, 9200000))
    g1 = ps.application(500101, "PL-20261010000101", "2026-10-10 10:00:00", 6, [ps.concern(next(cid), 500101, "APPLICANT", "G ONE", [
        ps.trip(710001, 0, "HOUSE", 5, "2026-10-10 10:00:00", ps.OK),
        ps.trip(710002, 0, "DOCUMENT", 6, "2026-10-13 10:00:00", "", "LOI VERIFICATION"),       # canceled extra, created before the last Submit
        ps.trip(710003, 0, "DOCUMENT", 7, "2026-10-13 11:00:00", "", "LOI VERIFICATION")])])   # inactive extra
    g2 = ps.application(500102, "PL-20261010000102", "2026-10-10 10:00:00", 3, [ps.concern(next(cid), 500102, "APPLICANT", "G TWO", [
        ps.trip(710011, 0, "HOUSE", 5, "2026-10-10 10:00:00", ps.OK),
        ps.trip(710012, 0, "DOCUMENT", 2, "2026-10-26 10:00:00", "", "LOI VERIFICATION")])])
    g3 = ps.application(500103, "PL-20261026000103", T0, 3, [ps.concern(next(cid), 500103, "APPLICANT", "G THREE", [
        ps.trip(710021, 0, "HOUSE", 2, T0, ""),
        ps.trip(710022, 0, "DOCUMENT", 2, "2026-11-02 09:00:00", "", "LOI VERIFICATION"),
        ps.trip(710023, 0, "DOCUMENT", 6, "2026-10-28 09:00:00", "", "LOI VERIFICATION")])])
    g4 = ps.application(500104, "PL-20261102000104", "2026-11-02 09:00:00", 2, [ps.concern(next(cid), 500104, "APPLICANT", "G FOUR", [
        ps.trip(710031, 0, "HOUSE", 2, "2026-11-02 09:00:00", "")])])
    for g in (g1, g2, g3, g4):
        for c in g["concerns"]:
            for t in c["trips"]:
                t["concern_id"] = c["id"]
    mock_server.STATE["files"] += [g1, g2, g3, g4]
    ps.LOGS[500101] = [_sub(500101, "2026-10-15 12:00:00")]
    ps.LOGS[500102] = [_sub(500102, "2026-10-12 12:00:00")]
    ps.LOGS[500103] = []
    ps.LOGS[500104] = []
    try:
        yield s
    finally:
        for k in (500101, 500102, 500103, 500104):
            ps.LOGS.pop(k, None)
        s.shutdown()


def test_submitted_file_never_has_pending_rows(extra_files):
    d = _run(extra_files)
    inc = {}
    for r in d.incomplete:
        inc.setdefault(r.file_no, []).append(r)
    assert "PL-20261010000101" not in inc                                   # Submitted file with Canceled / Inactive extras
    assert [r.kind for r in inc["PL-20261010000102"]] == ["Extra"]          # re-opened: only the NEW row is pending, package is not
    assert [r.kind for r in inc["PL-20261026000103"]] == ["Package"]       # ONE row per file; the canceled extra is hidden, the live extra is folded in
    assert [k for k, _t in inc["PL-20261026000103"][0].folded] == ["Extra"]
    assert "PL-20261102000104" not in inc                                   # received today, inside the 2-day In SLA
    # a pending file is judged by its Start Date: F-G3 started Mon 26-Oct, 5 working days later it is past the In SLA of 2
    pkg = inc["PL-20261026000103"][0]
    assert pkg.receive_dt == datetime(2026, 10, 26, 10, 0) and (pkg.extra_tat or 0) > 0


def test_file_state_unit():
    def mk(status, subs=(), parts=(), trips=(), logs=True):
        r = BillRow()
        r.file_status, r.logs_ok = status, logs
        r.file_submitted, r.partial_events, r.file_trips = list(subs), list(parts), list(trips)
        return r
    d = datetime
    assert file_state(mk(5)) == "closed" and file_state(mk(8)) == "closed"
    assert file_state(mk(2)) == "pending"
    assert file_state(mk(6, subs=[d(2026, 10, 1, 10)], trips=[(d(2026, 9, 30), 5)])) == "submitted"
    # a live trip created after the last Submitted re-opens the file; a canceled one does not
    assert file_state(mk(2, subs=[d(2026, 10, 1, 10)], trips=[(d(2026, 10, 5), 2)])) == "pending"
    assert file_state(mk(6, subs=[d(2026, 10, 1, 10)], trips=[(d(2026, 10, 5), 6)])) == "submitted"
    assert file_state(mk(6, subs=[d(2026, 10, 1, 10)], trips=[(d(2026, 10, 5), 7)])) == "submitted"      # an Inactive trip does not re-open it
    # partial, and as-of time travel: submitted at 16:00 was still pending at 15:00
    assert file_state(mk(7, parts=[d(2026, 10, 3, 9)], subs=[d(2026, 10, 1, 10)])) == "partial"
    sub = mk(6, subs=[d(2026, 11, 5, 16, 0)])
    assert file_state(sub, d(2026, 11, 5, 15, 0)) == "pending" and file_state(sub, d(2026, 11, 5, 23, 59)) == "submitted"
    # unreadable log: never silently dropped
    assert file_state(mk(6, logs=False)) == "pending" and file_state(mk(7, logs=False)) == "partial"


def test_dead_row():
    r = BillRow()
    r.kind, r.trips = "Extra", [({}, {"status_code": 6}), ({}, {"status_code": 8})]
    assert is_dead_row(r)
    r.trips = [({}, {"status_code": 7})]
    assert is_dead_row(r)                                                   # Inactive extra trip = no bill (05-11-2026 ghost rows)
    r.trips = [({}, {"status_code": 6}), ({}, {"status_code": 2})]
    assert not is_dead_row(r)
    r.kind, r.trips = "Package", [({}, {"status_code": 6})]
    assert not is_dead_row(r)                                               # a Package keeps its "Canceled trip" light-blue flag


def test_phase1_dashboard_reconciliation_lists_every_file(extra_files):
    p1 = _run(extra_files, slot="3pm")
    ck = p1.dash["check"]
    assert ck["missing"] == []
    files = {no: where for no, _t, where in ck["files"]}
    assert len(files) == ck["dashboard"] == ck["matched"] + len(ck["other_phase"])
    assert any("2nd phase mail" in w for w in files.values()) and any("Complete" in w for w in files.values())
    p2 = _run(extra_files, slot="7pm")
    assert all(w == "This report (Complete)" for _n, _t, w in p2.dash["check"]["files"])
    assert all(t is not None for _n, t, _w in p2.dash["check"]["files"])    # every dashboard file shows its submission time


def test_excel_has_no_illegal_xml_characters(extra_files, tmp_path):
    """The live Excel had a raw \\x19 (from "Didn\\x19t", an appointment reason) in a rich-text run.  Without lxml (the packaged
    app) openpyxl writes it as is -> Excel / Numbers asked to "repair" the file."""
    for f in mock_server.STATE["files"]:
        if f["id"] == 500003:
            f["concerns"][0]["trips"][1]["appointments"][0]["reason"] = "Applicant Didn\x19t receive the call \x0e\x0c"
    d = _run(extra_files)
    xlsx = write_prime_outputs(d, tmp_path)[0]
    seen = False
    with zipfile.ZipFile(xlsx) as z:
        for name in z.namelist():
            if name.endswith(".xml"):
                text = z.read(name).decode("utf8")
                assert not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text), name
                seen = seen or "Didn't receive the call" in text
    assert seen                                                              # the text is kept, the apostrophe restored
    load_workbook(xlsx)                                                      # opens cleanly


def test_test_files_are_skipped(extra_files):
    g4 = next(f for f in mock_server.STATE["files"] if f["id"] == 500103)
    g4["application_id"] = "PB-PL-Test-123456"                 # the bank's practice application seen on the live dashboard
    d = _run(extra_files)
    assert "PB-PL-Test-123456" not in {r.file_no for r in d.incomplete + d.complete}
    assert any("টেস্ট ফাইল" in n for n in d.notes)
    assert d.recon["row_trips"] == d.recon["file_trips"]        # trip-count check stays clean
