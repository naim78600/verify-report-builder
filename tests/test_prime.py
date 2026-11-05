"""v2 end-to-end test against the controlled scenario (no real server is touched)."""
import sys
import threading
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402
import mock_server  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from report_builder import geo, holidays as hol, summary as S  # noqa: E402
from report_builder.client import ReadOnlyClient  # noqa: E402
from report_builder.collect_prime import PrimeConfig, collect_prime, slot_for, title_for  # noqa: E402
from report_builder.reports import write_prime_outputs, write_recpv_workbook  # noqa: E402


@pytest.fixture(scope="module")
def data():
    srv = mock_server.start_scenario(0)
    port = srv.server_address[1]
    base = f"http://127.0.0.1:{port}"
    cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret",
                      days=30, mode="tracker", report_date=date(2026, 11, 2), slot="3pm")
    d = collect_prime(cfg, lambda *a: None, threading.Event())
    yield d, srv
    srv.shutdown()


def test_rows_and_selection(data):
    d, _ = data
    key = lambda r: (r.file_no, r.kind)                                # noqa: E731
    assert sorted(map(key, d.complete)) == sorted([
        ("PL-20261026000001", "ReCpv"), ("CC-20261101000002", "Package"), ("CC-20260115000004", "Extra"),
        ("CC--20261027000006", "Package"), ("CC--20261027000006", "Single"), ("CC--20261027000006", "Single")])
    assert sorted(map(key, d.incomplete)) == sorted([("PL-20261020000003", "Package"), ("PL-20250901000005", "ReCpv")])
    assert d.old_files == 2                                            # F4 (found by trip id) and F5 (by tracker)
    assert title_for(d) == "Prime Bank PLC 2-11-2026 3pm Submission Tracker"


def test_trip_count_never_changes(data):
    d, _ = data
    assert d.recon["row_trips"] == d.recon["file_trips"]
    f1 = [r for r in d.all_rows if r.file_no == "PL-20261026000001"]
    assert [r.kind for r in f1] == ["Package", "Single", "ReCpv"] and len(f1[0].trips) == 5


def test_package_area_and_slabs(data):
    d, _ = data
    f1 = {r.kind: r for r in d.all_rows if r.file_no == "PL-20261026000001"}
    assert f1["Package"].area == "Out"                                 # guarantor house is in Savar
    assert f1["Single"].slab.startswith("Single Document")
    assert f1["ReCpv"].category == "Re-CPV" and "ReCPV House Verification" in "\n".join(f1["ReCpv"].history_lines)
    f4 = next(r for r in d.all_rows if r.kind == "Extra")
    assert f4.category == "Extra Document(LOI)" and f4.receive_dt == datetime(2026, 10, 31, 11, 0)


def test_submission_and_tat(data):
    d, _ = data
    rc = next(r for r in d.complete if r.kind == "ReCpv")
    assert rc.submitted_at == datetime(2026, 11, 2, 16, 30) and rc.receive_dt.date() == date(2026, 10, 30)
    f2 = next(r for r in d.complete if r.file_no == "CC-20261101000002")
    assert f2.submitted_at == datetime(2026, 11, 2, 11, 0) and (f2.tat, f2.extra_tat) == (1, 0)
    f6 = next(r for r in d.complete if r.kind == "Package" and r.file_no.startswith("CC--"))
    assert f6.area == "Out" and (f6.tat, f6.extra_tat) == (4, 0) and f6.sla_days == 4 and not f6.sla_breach
    f3 = d.incomplete[0] if d.incomplete[0].file_no.endswith("0003") else d.incomplete[1]
    assert f3.status == "Incomplete" and f3.status_note == "Partially Submitted" and f3.tat == 7


from report_builder.report_text import appointment_lines, last_update_lines, plain as text_of


def test_summary_text(data):
    d, _ = data
    f2 = next(r for r in d.complete if r.file_no == "CC-20261101000002")
    assert f2.summary.due == "0" and f2.summary.done.startswith("App House, Office, Sign, LOI")
    assert "Head office does not verify" in f2.summary.done and f2.canceled and "slab" in f2.flags
    f3 = next(r for r in d.incomplete if r.file_no.endswith("0003"))
    assert f3.summary.done == "App House" and "Gave appointment on 04-11-2026" in f3.summary.due
    f5 = next(r for r in d.incomplete if r.file_no.endswith("0005"))
    assert f5.summary.due.startswith("App Office")


def test_read_only(data):
    _d, _ = data
    methods = {m for m, _p in mock_server.STATE["log"]}
    assert methods == {"GET", "POST"}
    assert [p for m, p in mock_server.STATE["log"] if m == "POST"] == ["/api/auth/callback/credentials"]


def test_outputs(data, tmp_path):
    d, _ = data
    paths = write_prime_outputs(d, tmp_path, excel=True, pdf=True, internal=True, bank=True, email=True)
    names = sorted(p.name for p in paths)
    assert len(names) == 5 and any(n.endswith("_INTERNAL.pdf") for n in names)
    wb = load_workbook(tmp_path / "Prime_Bank_2026-11-02_3pm_Submission_Tracker.xlsx")
    assert wb.sheetnames == ["Prime Bank Report", "Summary", "Holidays"]            # bank copy: no check list
    ws = wb["Prime Bank Report"]
    assert str(ws["K7"].value).startswith("=MAX(0,NETWORKDAYS.INTL(")
    wb2 = load_workbook(tmp_path / "Prime_Bank_2026-11-02_3pm_Submission_Tracker_INTERNAL.xlsx")
    assert "Check List" in wb2.sheetnames
    html = (tmp_path / "Prime_Bank_2026-11-02_3pm_Submission_Tracker_email.html").read_text(encoding="utf-8")
    assert "Dear Concern," in html and "Incomplete Report" in html
    w = write_recpv_workbook(d, tmp_path)
    wb3 = load_workbook(w)
    assert {"File Report", "Billing Rows", "Calculation"} <= set(wb3.sheetnames)


def test_geo_and_slot_and_holidays(tmp_path):
    assert geo.classify_point(23.7925, 90.4078) == ("In", True, "Dhaka")
    assert geo.classify_point(23.999, 90.420)[::2] == ("In", "Gazipur")            # Joydebpur
    assert geo.classify_point(23.6238, 90.5000)[::2] == ("In", "Narayanganj")      # Narayanganj Sadar
    assert geo.classify_point(23.8583, 90.2667)[0] == "Out"
    assert geo.trip_area({})[:2] == ("In", False)
    assert slot_for(datetime(2026, 11, 2, 14, 59)) == "3pm" and slot_for(datetime(2026, 11, 2, 17, 0)) == "7pm"
    n, errs = hol.add_ranges(["2028-01-02 | 2028-01-03 | Test", "bad line"], tmp_path / "h.json")
    assert n == 2 and len(errs) == 1 and date(2028, 1, 3) in hol.load(tmp_path / "h.json")
    assert hol.count_business_days(date(2026, 11, 6), date(2026, 11, 8), set()) == 1     # Fri Sat off, Sun counts


def test_readonly_guard_v2():
    c = ReadOnlyClient("http://x", "http://x")
    c.token = "t"
    for bad in ("/api/v2/applications/activity-logs/5", "/api/v2/re-cpv/tracker/9", "/api/v2/re-cpv/delete"):
        with pytest.raises(PermissionError):
            c.get(bad)


def test_remark_engine_samples():
    def view(code, status, remarks, comment="", who="App"):
        return S.TripView({"id": 1, "type_code": code, "status_code": status, "remarks": remarks, "comment": comment,
                           "appointments": []}, "APPLICANT", who)
    s = S.analyze([view("HOUSE", 5, "Information ok. Applicant signed in front of me."),
                   view("DOCUMENT", 5, "Information ok.", "CHAMBER VERIFICATION")], True)
    assert s.done == "App House, Sign, Chamber" and s.due == "0"
    s = S.analyze([view("BANK", 5, "Bank statement not verified. Applicant call not received.")], True)
    assert s.done == "BS (Call not received; Statement not verified)"


def test_bs_label_history_and_extra_trip_names(data):
    d, _ = data
    f6 = [r for r in d.all_rows if r.file_no.startswith("CC--")]
    assert [r.category for r in f6 if r.kind == "Single"] == ["Created - Extra Trip 1", "Created - Extra Trip 2"]
    assert any(r.slab == "BS" for r in f6 if r.kind == "Single")
    assert "Bank" not in " ".join(" ".join(r.concern_lines) for r in d.all_rows)
    f1 = sorted([r for r in d.all_rows if r.file_no == "PL-20261026000001"], key=lambda r: r.history_pos)
    assert [r.kind for r in f1] == ["Package", "Single", "ReCpv"]
    h = f1[0].file_history
    assert len(h) == 3 and h[0].startswith("1. Package (5 trips)") and h[1].startswith("2. Extra Trip 1") and h[2].startswith("3. Re-CPV")
    assert f1[2].history_pos == 2
    assert all(r.file_history == h for r in f1)


def test_sla_in_out(data):
    d, _ = data
    f2 = next(r for r in d.all_rows if r.file_no == "CC-20261101000002")
    assert f2.area == "In" and f2.sla_days == 2
    pk = next(r for r in d.all_rows if r.file_no == "PL-20261026000001" and r.kind == "Package")
    assert pk.area == "Out" and pk.sla_days == 4          # one guarantor trip is in Savar


def test_last_update_and_appointments(data):
    d, _ = data
    f3 = next(r for r in d.incomplete if r.file_no.endswith("0003"))
    when, what, user = f3.last_file
    assert when == datetime(2026, 11, 1, 10, 0) and "Trip 700051 (Office)" in what and "On Hold" in what and user == "Verifier"
    assert [t[0] for t in f3.last_trips] == [700050, 700051]
    assert len(f3.appointments) == 1 and f3.appointments[0]["time"] == datetime(2026, 11, 4, 12, 0)
    assert f3.appointments[0]["created_at"] == datetime(2026, 11, 1, 10, 0)
    f2 = next(r for r in d.complete if r.file_no == "CC-20261101000002")
    assert text_of(appointment_lines(f2)) == "NO"
    assert "Trip 700051 · Office" in text_of(appointment_lines(f3)) + text_of(last_update_lines(f3))
