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
                      days=30, mode="tracker", report_date=date(2026, 11, 2), slot="3pm", incomplete_scope="all_pending")
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
    assert d.old_files == 1                                            # F5 (by tracker); F4 is already in the dashboard's Submitted list
    ck = d.dash["check"]
    assert (ck["dashboard"], ck["matched"], ck["missing"], ck["extra"]) == (4, 4, [], 0) and ck["partial"] == 0
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
    assert f2.summary.done.startswith("App House, Office, Sign, LOI")
    assert "Head office disagree" in f2.summary.done and f2.canceled and "slab" in f2.flags
    # problems in Done are repeated in Due with the same wording; good-news notes are not
    assert "Head office disagree" in f2.summary.due and "Signed from branch" not in f2.summary.due
    assert "BS" not in f2.summary.done.split("LOI")[-1] and f2.summary.uncertain    # canceled bank trip is not written, only flagged
    assert any(k == "note" for _x, k in f2.summary.due_parts)
    f3 = next(r for r in d.incomplete if r.file_no.endswith("0003"))
    assert f3.summary.done == "App House" and "Appointment 04-11-2026 12:00 PM" in f3.summary.due
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
    assert wb.sheetnames == ["Complete Report", "Incomplete Report", "Summary", "Holidays"]   # bank copy: no check list
    ws = wb["Complete Report"]
    assert str(ws["K5"].value).startswith("=MAX(0,NETWORKDAYS.INTL(")
    # filter buttons only on File No (B) and Last Update Date (P); every other button is hidden
    for sh in (wb["Complete Report"], wb["Incomplete Report"]):
        hidden = {fc.colId for fc in sh.auto_filter.filterColumn if fc.hiddenButton}
        assert hidden == set(range(18)) - {1, 15}, hidden
        assert sh["P4"].value == "Last Update Date" and sh["Q4"].value == "Last Update Details"
    wb2 = load_workbook(tmp_path / "Prime_Bank_2026-11-02_3pm_Submission_Tracker_INTERNAL.xlsx")
    assert "Check List" in wb2.sheetnames
    html = (tmp_path / "Prime_Bank_2026-11-02_3pm_Submission_Tracker_email.html").read_text(encoding="utf-8")
    assert "Dear Concern," in html and "Incomplete Report" in html
    w = write_recpv_workbook(d, tmp_path)
    wb3 = load_workbook(w)
    assert {"File Report", "Billing Rows", "Calculation"} <= set(wb3.sheetnames)


def test_geo_and_slot_and_holidays(tmp_path):
    assert geo.classify_point(23.7925, 90.4078) == ("In", True, "Dhaka")
    assert geo.classify_point(23.999, 90.420)[::2] == ("Out", "")                  # Joydebpur, Gazipur = Out
    assert geo.classify_point(23.6238, 90.5000)[::2] == ("Out", "")                # Narayanganj Sadar = Out
    assert geo.classify_point(22.3250, 91.8110)[::2] == ("In", "Chattogram")       # Agrabad, Chattogram city
    assert geo.classify_point(23.8968, 90.4314)[0] == "Out"                        # Tongi
    assert geo.classify_text("House 5, Joydebpur, Gazipur") == "Out"
    assert geo.classify_text("Agrabad, Chattogram") == "In"
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
    assert s.done == "BS (Call not received)"


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


def test_done_due_convention():
    def view(tid, code, status, remarks, comment="", who="App", role="APPLICANT"):
        return S.TripView({"id": tid, "type_code": code, "status_code": status, "remarks": remarks, "comment": comment,
                           "appointments": []}, role, who)
    # I/F is written "Insufficient fund"; two bank trips become BS1 / BS2; tracker order App -> LOI -> BS -> Co-App -> PG
    views = [view(1, "HOUSE", 5, "Information ok."), view(2, "OFFICE", 5, "Information ok. LOI signed in front of me."),
             view(3, "BANK", 5, "Bank statement not verified. I/F."), view(4, "BANK", 5, "Information ok."),
             view(5, "HOUSE", 5, "Information ok.", who="PG1", role="GUARANTOR"),
             view(6, "HOUSE", 5, "Information ok.", who="Co-App", role="CO_APPLICANT")]
    s = S.analyze(views, True)
    assert s.done == "App House, Office, LOI, BS1 (Insufficient fund), BS2, Co-App House, PG1 House"
    assert s.due == "BS1 (Insufficient fund)"                    # the problem is repeated in Due, nothing else
    assert ("BS1", "ok") in s.due_parts and (" (Insufficient fund)", "note") in s.due_parts
    # nothing wrong -> Due-0
    s = S.analyze([view(1, "HOUSE", 5, "Information ok."), view(2, "OFFICE", 5, "Information ok.")], True)
    assert (s.done, s.due) == ("App House, Office", "0")
    # good-news notes stay in Done only
    s = S.analyze([view(1, "HOUSE", 5, "Given address mismatch. New address found and verified.")], True)
    assert s.done == "App House (New address found & verified)" and s.due == "0"
    # long text is shortened and phone numbers / e-mails never appear
    long = "The head office accounts officer informed us about the process. Contact: 01711099977 mail abc@bank.com. He disagree to verify the given LOI at all."
    s = S.analyze([view(1, "DOCUMENT", 5, long, "LOI VERIFICATION")], True)
    assert "01711" not in s.done and "@" not in s.done and len(s.done) < 90
    assert S.scrub("call 01711099977 or x@y.com Name: Rahim Uddin") == "call or"
    # incomplete: pending trip with an appointment goes to Due with the reason
    t = {"id": 9, "type_code": "OFFICE", "status_code": 2, "remarks": "", "comment": "",
         "appointments": [{"time": datetime(2026, 11, 6, 11, 0), "reason": "come tomorrow", "active": True}]}
    s = S.analyze([S.TripView(t, "APPLICANT", "App")], False)
    assert s.done == "0" and s.due.startswith("App Office (Appointment 06-11-2026 11:00 AM")


def test_report_cells_done_due_colours_and_last_update(data, tmp_path):
    """Problems: amber in Done, repeated in Due on a soft marker ('hl'); no problem -> Due-0 in green.
    The Excel has no red / yellow fills and a real, filterable 'Last Update Date' column."""
    from report_builder.report_text import has_due, last_update_date, summary_lines
    d, _ = data
    f2 = next(r for r in d.complete if r.file_no == "CC-20261101000002")
    done, due = summary_lines(f2)
    assert done[0] == ("Done-", "gb") and any(st == "dn" for _t, st in done)
    assert due[0] == ("Due-", "ab") and any(st == "hl" for _t, st in due) and has_due(f2)
    ok = next(r for r in d.complete if not has_due(r))
    d_ok, due_ok = summary_lines(ok)
    assert due_ok == [("Due-", "gb"), ("0", "g")]
    assert last_update_date(ok) == ok.last_file[0]
    paths = write_prime_outputs(d, tmp_path, excel=True, pdf=False, internal=True, bank=True, email=False)
    wb = load_workbook(next(p for p in paths if p.name.endswith("Tracker_INTERNAL.xlsx")))
    ws = wb["Complete Report"]
    heads = [c.value for c in ws[4]]
    assert heads.index("Last Update Date") == 15 and heads[16] == "Last Update Details"
    assert isinstance(ws.cell(5, 16).value, __import__("datetime").date)             # a real date, so Excel can filter it
    banned = {"FFF200", "FFFF00", "FF0000", "FEF3C7", "FEE2E2", "DC2626", "EF4444", "FFE7A8", "F8C9C9"}
    for sh in wb.worksheets:
        for row in sh.iter_rows():
            for c in row:
                for col in (c.fill.fgColor.rgb if c.fill and c.fill.fill_type else None,):
                    if isinstance(col, str):
                        assert col[-6:].upper() not in banned, (sh.title, c.coordinate, col)
    assert any(c.fill.fgColor.rgb[-6:] == "BFE3FF" for sh in (wb["Complete Report"], wb["Incomplete Report"])
               for row in sh.iter_rows() for c in row if c.fill and c.fill.fill_type and isinstance(c.fill.fgColor.rgb, str))


def test_range_mode_lists_what_the_dashboard_lists(tmp_path):
    """The bank pressed Submit on the Reports page (status Submitted, 02-Nov..02-Nov): 4 files.  The range report used to
    keep only rows RECEIVED inside the dates and returned almost none of them.  Now Complete = rows SUBMITTED inside the dates."""
    import prime_scenario as ps
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    f7 = ps.application(500007, "PL-20261020000007", "2026-10-20 09:00:00", 6, [
        ps.concern(5000071, 500007, "APPLICANT", "THETA SEVEN", [ps.trip(700070, 5000071, "HOUSE", 5, "2026-10-20 09:00:00", ps.OK)])])
    ps.LOGS[500007] = [ps._log("APPLICATION", 500007, "Application : 500007 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-11-01 15:00:00"),
                       ps._log("APPLICATION", 500007, "Application : 500007 status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-11-02 12:00:00")]
    mock_server.STATE["files"].append(f7)
    try:
        cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                          mode="range", date_from=date(2026, 11, 2), date_till=date(2026, 11, 2))
        d = collect_prime(cfg, lambda *a: None, threading.Event())
        key = lambda r: (r.file_no, r.kind)                            # noqa: E731
        assert sorted(map(key, d.complete)) == sorted([
            ("PL-20261026000001", "ReCpv"), ("CC-20261101000002", "Package"), ("CC-20260115000004", "Extra"),
            ("CC--20261027000006", "Package"), ("CC--20261027000006", "Single"), ("CC--20261027000006", "Single")])
        ck = d.dash["check"]
        assert ck["dashboard"] == 5 and ck["matched"] == 4 and ck["extra"] == 0
        # F7 is in the dashboard's list (submitted again on 02-Nov) but its first Submitted event was 01-Nov: it is reported, not hidden
        assert [no for no, _why in ck["missing"]] == ["PL-20261020000007"] and "01/11/2026" in ck["missing"][0][1]
        assert any("PL-20261020000007" in n for n in d.notes)
        # a wider range keeps working: rows received inside it that are still open stay in Incomplete
        cfg2 = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                           mode="range", date_from=date(2026, 10, 1), date_till=date(2026, 11, 3))
        d2 = collect_prime(cfg2, lambda *a: None, threading.Event())
        assert {r.file_no for r in d2.incomplete} >= {"PL-20261020000003", "PL-20250901000005"}
        assert d2.dash["check"]["missing"] == []                       # the full range: every Submitted file has a Complete row
        # a range that ENDS before a later submission: that row was still waiting on its last day
        cfg3 = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                           mode="range", date_from=date(2026, 10, 25), date_till=date(2026, 10, 31))
        d3 = collect_prime(cfg3, lambda *a: None, threading.Event())
        later = [r for r in d3.incomplete if r.file_no == "PL-20261026000001" and r.kind == "ReCpv"]
        assert later and later[0].status_note.startswith("Submitted later (02/11/2026)") and d3.recon["submitted_later"] >= 1
        # live-site rule: WITH a status filter the dates mean "the day the current status began", WITHOUT one they mean
        # the Start Date.  F2 started 01-Nov and was submitted 02-Nov, so a report for 01-Nov only finds it through the
        # Start-Date list - and must show it as still waiting on that day.
        cfg4 = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                           mode="range", date_from=date(2026, 11, 1), date_till=date(2026, 11, 1))
        d4 = collect_prime(cfg4, lambda *a: None, threading.Event())
        assert any(r.file_no == "CC-20261101000002" for r in d4.incomplete)
        assert not any(r.file_no == "CC-20261101000002" for r in d4.complete)
    finally:
        mock_server.STATE["files"].remove(f7)
        ps.LOGS.pop(500007, None)
        srv.shutdown()


def test_tracker_window_rollover_and_incomplete_scope():
    """Rules read from the mails sent 25/10-05/11/2026 and the live activity logs (see README v2.3.0):
      * Complete = SUBMITTED on the report day; Fri / Sat / holiday submissions go into the NEXT working day's tracker,
        shown with that day's date, and the TAT is counted up to it.
      * Incomplete = rows still not Submitted of the files that became Partially Submitted inside the tracker window."""
    import prime_scenario as ps
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    d = "2026-10-27 10:00:00"
    f8 = ps.application(500008, "CC-20261027000008", d, 6, [
        ps.concern(5000081, 500008, "APPLICANT", "IOTA EIGHT", [ps.trip(700080, 5000081, "HOUSE", 5, d, ps.OK, loc=ps.SAVAR)])], atype=2)
    ps.LOGS[500008] = [ps._log("APPLICATION", 500008, "Application : 500008 status updated to SUBMITTED by Mgr", "FINISHED", "SUBMITTED", "2026-10-31 15:00:00")]
    f9 = ps.application(500009, "PL-20261028000009", "2026-10-28 09:00:00", 7, [
        ps.concern(5000091, 500009, "APPLICANT", "KAPPA NINE", [
            ps.trip(700090 + 1, 5000091, "HOUSE", 5, "2026-10-28 09:00:00", ps.OK),
            ps.trip(700090 + 2, 5000091, "OFFICE", 2, "2026-10-28 09:00:00", "")])])
    ps.LOGS[500009] = [ps._log("APPLICATION", 500009, "Application : 500009 status updated to PARTIAL_SUBMITTED by Mgr", "HOLD", "PARTIAL_SUBMITTED", "2026-11-02 12:00:00")]
    mock_server.STATE["files"].extend([f8, f9])

    def run(day, scope=None, mode_kwargs=None):
        kw = dict(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                  mode="tracker", report_date=day)
        if scope:
            kw["incomplete_scope"] = scope
        return collect_prime(PrimeConfig(**kw), lambda *a: None, threading.Event())
    nos = lambda rows: sorted({r.file_no for r in rows})               # noqa: E731
    try:
        # Sunday 01-Nov: the tracker covers Fri 30-Oct .. Sun 01-Nov
        d1 = run(date(2026, 11, 1))
        assert d1.track_from == date(2026, 10, 30)
        r8 = next(r for r in d1.complete if r.file_no == "CC-20261027000008")
        assert r8.submitted_at == datetime(2026, 10, 31, 15, 0) and r8.sub_day == date(2026, 11, 1) and r8.rolled
        assert r8.reported_at == datetime(2026, 11, 1, 15, 0)
        assert (r8.tat, r8.extra_tat) == (3, 0)                        # Wed 28, Thu 29, Sun 01 - counted up to the reported day
        assert d1.dash["check"]["missing"] == [] and d1.dash["check"]["matched"] == 1
        assert nos(d1.incomplete) == ["PL-20261020000003"]             # F3 became Partially Submitted on Fri 30-Oct
        assert any("পরের কর্মদিবস" in n for n in d1.notes)
        # Saturday 31-Oct (a day off, report made anyway): that day stays that day
        d0 = run(date(2026, 10, 31))
        r8 = next(r for r in d0.complete if r.file_no == "CC-20261027000008")
        assert not r8.rolled and r8.sub_day == date(2026, 10, 31) and r8.tat == 2
        # Monday 02-Nov: F8 was already in Sunday's tracker; only F9 became Partially Submitted today
        d2 = run(date(2026, 11, 2))
        assert d2.track_from == date(2026, 11, 2) and "CC-20261027000008" not in nos(d2.complete)
        assert nos(d2.incomplete) == ["PL-20261028000009"] and d2.incomplete_scope == "partial_today"
        f9r = d2.incomplete[0]
        assert f9r.status == "Incomplete" and f9r.status_note == "Partially Submitted"
        # the wider lists
        assert nos(run(date(2026, 11, 2), "partial_open").incomplete) == ["PL-20261020000003", "PL-20261028000009"]
        assert nos(run(date(2026, 11, 2), "all_pending").incomplete) == ["PL-20250901000005", "PL-20261020000003", "PL-20261028000009"]
    finally:
        for f in (f8, f9):
            mock_server.STATE["files"].remove(f)
        ps.LOGS.pop(500008, None)
        ps.LOGS.pop(500009, None)
        srv.shutdown()
