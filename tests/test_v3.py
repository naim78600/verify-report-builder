"""V3 tests: phases (3 PM cut-off), Incomplete rule, reasons, single Excel + Check List, volume at 90 days."""
import sys
import threading
from copy import copy
import time as _time
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402
import mock_server  # noqa: E402
import prime_scenario as ps  # noqa: E402
import bulk_scenario as bulk  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from report_builder import holidays as hol  # noqa: E402
from report_builder.billing import BillRow, before_after, classify_reason  # noqa: E402
from report_builder.collect_prime import PrimeConfig, collect_prime  # noqa: E402
from report_builder.mail_templates import facts_from  # noqa: E402
from report_builder.reports import count_blue_cells, has_checklist, strip_checklist, write_prime_outputs  # noqa: E402

R = date(2026, 11, 2)


def _run(srv, **kw):
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    cfg = dict(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
               mode="tracker", report_date=R, slot="7pm")
    cfg.update(kw)
    return collect_prime(PrimeConfig(**cfg), lambda *a: None, threading.Event())


@pytest.fixture()
def srv():
    s = mock_server.start_scenario(0)
    yield s
    s.shutdown()


@pytest.fixture()
def srv_f5_hold(srv):
    """F5 is On Going in the mock (a running file is never listed since v3.2.1); as a Hold with no written reason it is the
    example of "listed, but no reason could be found" (light-blue cell + Check List)."""
    f5 = next(f for f in mock_server.STATE["files"] if f["id"] == 500005)
    f5["status"] = 3
    yield srv
    f5["status"] = 2


def nos(rows):
    return sorted({r.file_no for r in rows})


# ----------------------------------------------------------------------------- phases
def test_phase_cutoff(srv):
    """1st phase (3:30 PM mail) = state at 3 PM: F1 (16:30) and F4 (18:00) were still waiting; 2nd phase = whole day;
    'only after 3 PM' = just what the 1st mail did not already carry."""
    p1, p2, p2b = _run(srv, slot="3pm"), _run(srv, slot="7pm"), _run(srv, slot="7pm", after3_only=True)
    assert nos(p1.complete) == ["CC--20261027000006", "CC-20261101000002"]
    assert nos(p2.complete) == ["CC--20261027000006", "CC-20260115000004", "CC-20261101000002", "PL-20261026000001"]
    assert nos(p2b.complete) == ["CC-20260115000004", "PL-20261026000001"]
    assert p2b.after3_only and not p1.after3_only
    # before / after column and the title wording
    assert {r.file_no: before_after(r) for r in p2.complete}["PL-20261026000001"] == "After 3 PM"
    assert {r.file_no: before_after(r) for r in p2.complete}["CC-20261101000002"] == "Before 3 PM"
    # the 3 PM mail must not report the late files as "not matched" with the dashboard (they belong to the 2nd mail)
    assert p1.dash["check"]["missing"] == [] and len(p1.dash["check"]["other_phase"]) == 2
    assert p2b.dash["check"]["missing"] == [] and len(p2b.dash["check"]["other_phase"]) == 2
    assert p2.dash["check"]["missing"] == [] and p2.dash["check"]["matched"] == 4


def test_incomplete_rule_sla_plus_partial(srv):
    d = _run(srv)
    assert d.incomplete_scope == "sla_partial"
    by = {r.file_no: r for r in d.incomplete}
    assert set(by) == {"PL-20261020000003"}                                       # Partially Submitted
    assert by["PL-20261020000003"].file_status == 7 and (by["PL-20261020000003"].extra_tat or 0) > 0
    # F5 is On Going and past its SLA (In = 2 working days) but it is a running file: never listed (v3.2.1)
    f5 = [r for r in d.all_rows if r.file_no == "PL-20250901000005"]
    assert f5 and all((r.extra_tat or 0) > 0 for r in f5) and "PL-20250901000005" not in by


def test_canceled_and_withdrawn_files_are_not_pending(srv):
    files = mock_server.STATE["files"]
    f5 = next(f for f in files if f["id"] == 500005)
    f5["status"] = 5
    try:
        assert "PL-20250901000005" not in nos(_run(srv).incomplete)
    finally:
        f5["status"] = 2


# ----------------------------------------------------------------------------- reasons
def _row(**kw):
    r = BillRow()
    r.file_status = kw.pop("file_status", 2)
    r.trips = kw.pop("trips", [])
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def _trip(code, remarks="", comment=""):
    return ({}, {"status_code": code, "remarks": remarks, "comment": comment, "id": 1})


def test_reason_kinds():
    ap = _row(trips=[_trip(2)], appointments=[{"active": True, "time": datetime(2026, 11, 4, 12, 0), "type": "", "reason": "Not available"}], sla_breach=True)
    classify_reason(ap)
    assert ap.reason_kind == "appointment" and ap.reason == "Appointment 04/11/2026 12:00 PM (Not available)"
    hold = _row(trips=[_trip(4, comment="Applicant is abroad, will return next week.")], file_status=3)
    classify_reason(hold)
    assert hold.reason_kind == "hold" and hold.reason == "Hold: Applicant is abroad, will return next week."
    hold_no_remark = _row(trips=[_trip(4, "")], sla_breach=True, file_status=3)
    classify_reason(hold_no_remark)
    assert hold_no_remark.reason_kind == "hold" and hold_no_remark.reason == "Hold: no reason written on the dashboard"
    assert "reason" in hold_no_remark.flags                                       # a Hold is always listed; nothing explains it -> light-blue cell
    hold_appt = _row(trips=[_trip(4, "")], file_status=3,
                     appointments=[{"active": True, "time": datetime(2026, 11, 8, 11, 0), "type": "", "reason": ""}])
    classify_reason(hold_appt)
    assert hold_appt.reason == "Hold | Appointment 08/11/2026 11:00 AM" and "reason" not in hold_appt.flags   # the appointment explains the Hold
    fin = _row(trips=[_trip(5)], file_status=4)
    classify_reason(fin)
    assert fin.reason_kind == "finished" and fin.reason == "Finished - not yet submitted"
    going = _row(trips=[_trip(2)], sla_breach=False)
    classify_reason(going)
    assert going.reason_kind == "ongoing" and going.reason == "On Going, within SLA"
    late = _row(trips=[_trip(2)], sla_breach=True)
    classify_reason(late)
    assert late.reason == ""                                                      # overdue and nothing explains it -> light-blue
    done = _row(trips=[_trip(5)])
    done.status = "Submitted"
    classify_reason(done)
    assert done.reason == ""
    # a file that is Submitted NOW but was waiting at the report time: the live trips say what it was
    past = _row(trips=[_trip(4, comment="Customer asked to wait")], file_status=6)
    classify_reason(past)
    assert past.reason == "Hold: Customer asked to wait"


def test_pending_reason_cell_and_blue_flag(srv_f5_hold, tmp_path):
    d = _run(srv_f5_hold)
    xlsx = write_prime_outputs(d, tmp_path)[0]
    wb = load_workbook(xlsx)
    ws = wb["Incomplete Report"]
    heads = [c.value for c in ws[4]]
    col = heads.index("Pending Reason") + 1
    texts = {ws.cell(r, 2).value: ws.cell(r, col).value for r in range(5, ws.max_row + 1)}
    assert texts["PL-20261020000003"].startswith("Partially Submitted: App Office | Appointment 04/11/2026 12:00 PM")
    assert texts["PL-20250901000005"] == "Hold: no reason written on the dashboard"   # Hold without any written reason ...
    cell = next(ws.cell(r, col) for r in range(5, ws.max_row + 1) if ws.cell(r, 2).value == "PL-20250901000005")
    assert cell.fill.fgColor.rgb[-6:] == "BFE3FF"                                  # ... is flagged light sky-blue
    assert count_blue_cells(xlsx) >= 1 and has_checklist(xlsx)
    chk = [[c for c in row] for row in wb["Check List"].iter_rows(values_only=True)]
    assert any(row[3] == "Pending Reason" and row[2] == "PL-20250901000005" for row in chk)


# ----------------------------------------------------------------------------- Check List removal
def test_strip_checklist_keeps_everything_else(srv_f5_hold, tmp_path):
    d = _run(srv_f5_hold)
    xlsx = write_prime_outputs(d, tmp_path)[0]
    # simulate the user's edit: fill the missing reason in Excel and save
    wb = load_workbook(xlsx, rich_text=True)
    ws = wb["Incomplete Report"]
    col = [c.value for c in ws[4]].index("Pending Reason") + 1
    for r in range(5, ws.max_row + 1):
        if ws.cell(r, 2).value == "PL-20250901000005":
            ws.cell(r, col).value = "Applicant asked to visit on Wednesday"
            ws.cell(r, col).fill = copy(ws.cell(r, col - 1).fill)
    wb.save(xlsx)
    out = strip_checklist(xlsx, tmp_path / "sent" / xlsx.name)
    a, b = load_workbook(xlsx, rich_text=True), load_workbook(out, rich_text=True)
    assert b.sheetnames == ["Complete Report", "Incomplete Report", "Summary", "Holidays"]
    for name in b.sheetnames:
        sa, sb = a[name], b[name]
        assert sa.dimensions == sb.dimensions and sa.freeze_panes == sb.freeze_panes
        assert (sa.auto_filter.ref, len(sa.merged_cells.ranges)) == (sb.auto_filter.ref, len(sb.merged_cells.ranges))
        for row in sa.iter_rows():
            for c in row:
                o = sb[c.coordinate]
                assert c.value == o.value and c.number_format == o.number_format, (name, c.coordinate)
                assert (c.fill.fgColor.rgb, c.font.b, c.font.color.rgb if c.font.color else None) == \
                       (o.fill.fgColor.rgb, o.font.b, o.font.color.rgb if o.font.color else None), (name, c.coordinate)
        assert {k: v.width for k, v in sa.column_dimensions.items()} == {k: v.width for k, v in sb.column_dimensions.items()}
    assert b["Incomplete Report"].cell(6, col).value == "Applicant asked to visit on Wednesday"      # the user's edit survived
    assert not has_checklist(out) and has_checklist(xlsx)
    assert count_blue_cells(out) < count_blue_cells(xlsx) + 1


def test_facts_from(srv_f5_hold):
    d = _run(srv_f5_hold)
    f = facts_from(d)
    assert (f.complete_files, f.complete_rows, f.incomplete_files, f.incomplete_rows) == (4, 6, 2, 2)
    assert f.sla_breach_rows == 2 and f.partial_files == 1 and f.reason_missing == 1 and f.slot == "7pm"


# ----------------------------------------------------------------------------- volume: 1000+ files, 90 days
@pytest.fixture(scope="module")
def big():
    items = bulk.build(1100, R)
    mock_server.STATE["files"].clear()
    srv = mock_server.start_scenario(0)
    mock_server.STATE["files"] = [it["file"] for it in items]
    saved_tracks = list(ps.TRACKS)
    ps.TRACKS.clear()                                                            # the two Re-CPV tracks belong to the small scenario
    yield srv, items
    ps.TRACKS.extend(saved_tracks)
    srv.shutdown()
    for it in items:
        ps.LOGS.pop(it["id"], None)


@pytest.mark.parametrize("slot,after3", [("7pm", False), ("3pm", False), ("7pm", True)])
def test_bulk_90_days_tracker_matches_independent_rules(big, slot, after3, tmp_path):
    srv, items = big
    hset = set(hol.load())
    exp_c, exp_i = bulk.expected(items, R, slot, hset, after3_only=after3)
    t0 = _time.time()
    d = _run(srv, slot=slot, after3_only=after3, days=90, workers=6)
    took = _time.time() - t0
    got_c, got_i = {r.file_no for r in d.complete}, {r.file_no for r in d.incomplete}
    assert got_c == exp_c, (len(got_c), len(exp_c), sorted(got_c ^ exp_c)[:8])
    assert got_i == exp_i, (len(got_i), len(exp_i), sorted(got_i ^ exp_i)[:8])
    assert len(exp_c) > 5 and len(exp_i) > 50                                     # the scenario is not trivially empty
    assert not d.failed and d.log_failed == 0 and d.dash["check"]["missing"] == []
    assert all(r.reason or "reason" in r.flags for r in d.incomplete)             # every pending row: a reason or a blue cell
    paths = write_prime_outputs(d, tmp_path, excel=True, pdf=True)
    assert all(p.stat().st_size > 5000 for p in paths)
    ws = load_workbook(paths[0])["Incomplete Report"]
    assert ws.max_row - 4 == len(d.incomplete)
    print(f"[bulk {slot} after3={after3}] files={len(d.files)} complete={len(got_c)} incomplete={len(got_i)} collect={took:.1f}s")


def test_bulk_range_90_days_is_not_blank(big):
    srv, items = big
    d = _run(srv, mode="range", days=90, report_date=None, date_from=date(2026, 8, 5), date_till=R)
    subs = {it["no"] for it in items if it["sub"] and date(2026, 8, 5) <= it["sub"].date() <= R}
    assert subs and {r.file_no for r in d.complete} == subs
    assert len(d.incomplete) > 50 and len(d.files) > 800
