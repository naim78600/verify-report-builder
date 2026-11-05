"""File History (read-only search by file number / last digits) against the controlled scenario."""
import re
import sys
import threading
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402
import mock_server  # noqa: E402
import prime_scenario as ps  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402

from report_builder.client import Cancelled  # noqa: E402
from report_builder.file_history import (HistoryConfig, make_entry, parse_ids_file, parse_ids_text,  # noqa: E402
                                         collect_history, match_entry, FileIndex)
from report_builder.history_excel import build_history_excel, write_history_outputs  # noqa: E402

TODAY = date(2026, 11, 5)
LIST = "/api/v2/manager/applications"
SHEETS = ["Summary", "Timeline", "Submission History", "Trips", "Appointments", "Re-CPV & Extra", "Concerns", "Not Found"]


def _cfg(base, ids, index_path, **kw):
    return HistoryConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret",
                         ids=ids, index_path=index_path, today=TODAY, **kw)


def _list_calls():
    return sum(1 for m, p in mock_server.STATE["log"] if m == "GET" and p == LIST)


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    # a second file whose number ends with the same digits as F3 (suffix collision); ids avoid the flaky "...7"
    d = "2026-03-05 10:00:00"
    mock_server.STATE["files"].append(ps.application(500008, "PL-20260305000003", d, 6, [
        ps.concern(5000081, 500008, "APPLICANT", "THETA EIGHT", [ps.trip(700080, 5000081, "HOUSE", 5, d, ps.OK)])]))
    yield base, tmp_path_factory.mktemp("hist")
    srv.shutdown()


@pytest.fixture(scope="module")
def run(env):
    base, tmp = env
    mock_server.STATE["log"].clear()
    stages = []
    ids = ["000003", "2", "9999", "PL-20261026000001", "CC-20261027000006", "PL-20269999999999", "2", " 000003 "]
    h = collect_history(_cfg(base, [make_entry(i) for i in ids], tmp / "idx_main.json"),
                        lambda stage, a, b, msg: stages.append((stage, a, b, msg)), threading.Event())
    return h, stages, list(mock_server.STATE["log"]), tmp


# ------------------------------------------------------------------------------ input files
def test_parse_numbers_ints_strings_no_padding():
    assert make_entry(441930).raw == "441930" and make_entry(441930.0).raw == "441930"
    assert make_entry("  35932 ").kind == "suffix" and make_entry("9310").digits == "9310"
    e = make_entry("000003")
    assert e.raw == "000003" and e.digits == "000003"                  # never padded, never stripped
    assert make_entry(3).raw == "3"                                    # a bare 3 stays 3 (no 000003)
    f = make_entry("cc--20261029061512999")
    assert f.kind == "full" and f.key == "CC20261029061512999" and f.raw == "CC-20261029061512999" and f.day == date(2026, 10, 29)
    assert make_entry("hello") is None and make_entry(None) is None and make_entry(12.5) is None and make_entry(True) is None
    assert [e.raw for e in parse_ids_text("441930, 35932\n9310;441930  PL-20261026000001")] == \
        ["441930", "35932", "9310", "PL-20261026000001"]


def test_parse_excel_auto_column_and_dedupe(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["SL", "Tracking No.", "Amount"])
    for i, v in enumerate([441930, 35932.0, "9310", None, "CC-20261029061512999", 441930, "n/a", "PL--20261026000001"], 1):
        ws.append([i, v, 500000])
    wb.save(tmp_path / "bank.xlsx")
    got = parse_ids_file(tmp_path / "bank.xlsx")
    assert [e.raw for e in got] == ["441930", "35932", "9310", "CC-20261029061512999", "PL-20261026000001"]
    assert [e.kind for e in got] == ["suffix"] * 3 + ["full"] * 2


def test_parse_excel_without_header_takes_the_number_column(tmp_path):
    wb = Workbook()
    ws = wb.active
    for i, v in enumerate([441930, 35932, 9310, 128], 1):
        ws.append([i, "note", v])                                      # 1,2,3,4 is a serial column; col C has the numbers
    wb.save(tmp_path / "plain.xlsx")
    assert [e.raw for e in parse_ids_file(tmp_path / "plain.xlsx")] == ["441930", "35932", "9310", "128"]


def test_parse_csv_and_txt(tmp_path):
    (tmp_path / "a.csv").write_text("File Number;Remarks\n441930;x\n35932;y\n\n9310;z\n", encoding="utf-8-sig")
    assert [e.raw for e in parse_ids_file(tmp_path / "a.csv")] == ["441930", "35932", "9310"]
    (tmp_path / "b.csv").write_text("PL-20261026000001\nCC-20261027000006\n", encoding="utf-8")
    assert [e.kind for e in parse_ids_file(tmp_path / "b.csv")] == ["full", "full"]
    (tmp_path / "c.txt").write_text("441930\n35932\n", encoding="utf-8")
    assert len(parse_ids_file(tmp_path / "c.txt")) == 2


# ------------------------------------------------------------------------------ search
def test_matching_rules_are_exact_suffix_and_normalised():
    table = [(1, "PL-20261026000001", "2026-10-26", "PL20261026000001", "20261026000001"),
             (2, "CC--20261027000006", "2026-10-27", "CC20261027000006", "20261027000006"),
             (3, "PL-20260305000003", "2026-03-05", "PL20260305000003", "20260305000003")]
    assert [m[0] for m in match_entry(table, make_entry("6"))] == [2]                # suffix as given, no padding
    assert match_entry(table, make_entry("000006")) and not match_entry(table, make_entry("0000006"))
    assert [m[0] for m in match_entry(table, make_entry("CC-20261027000006"))] == [2]   # single dash finds the double-dash file
    assert not match_entry(table, make_entry("PL-20261027000006"))                      # prefix must agree for a full number
    assert [m[0] for m in match_entry(table, make_entry("1"))] == [1]
    assert [m[0] for m in match_entry(table, make_entry("0"))] == []


def test_suffix_full_notfound_and_multiple(run):
    h, _stages, _log, _tmp = run
    assert [e.raw for e in h.entries] == ["000003", "2", "9999", "PL-20261026000001", "CC-20261027000006", "PL-20269999999999"]
    by = {}
    for m in h.matches:
        by.setdefault(m.entry.raw, []).append(m)
    # collision: both files shown, both flagged
    multi = by["000003"]
    assert sorted(h.files[m.file_id].file_no for m in multi) == ["PL-20260305000003", "PL-20261020000003"]
    assert all(m.note == "Multiple files end with 000003" for m in multi)
    # a bare 2 is NOT padded: it finds the one file whose number ends with 2
    assert [h.files[m.file_id].file_no for m in by["2"]] == ["CC-20261101000002"] and by["2"][0].note == ""
    # full numbers
    assert [h.files[m.file_id].file_no for m in by["PL-20261026000001"]] == ["PL-20261026000001"]
    assert [h.files[m.file_id].file_no for m in by["CC-20261027000006"]] == ["CC--20261027000006"]
    # not found: a row, never an exception
    assert [m.found for m in by["9999"]] == [False] and "File not found" in by["9999"][0].note
    assert [e.raw for e in h.not_found] == ["9999", "PL-20269999999999"]
    assert len(h.results) == 5                                         # 2 collision files + F2 + F1 + F6, each once


def test_progress_signature(run):
    _h, stages, _log, _tmp = run
    assert all(len(s) == 4 for s in stages)
    assert {"login", "list", "detail", "log", "rows"} <= {s[0] for s in stages}


def test_read_only_no_write_calls(run):
    _h, _stages, log, _tmp = run
    assert {m for m, _p in log} == {"GET", "POST"}
    assert [p for m, p in log if m == "POST"] == ["/api/auth/callback/credentials"]
    allowed = ("/api/auth/", "/api/v2/auth/user", LIST, "/api/v2/re-cpv/tracker", "/api/v2/applications/activity-logs")
    assert all(p.startswith(allowed) for m, p in log if m == "GET")


def test_index_cache_second_run_reads_less(env):
    base, tmp = env
    path = tmp / "idx_cache.json"
    ids = [make_entry("000003"), make_entry("2")]
    mock_server.STATE["log"].clear()
    h1 = collect_history(_cfg(base, ids, path), lambda *a: None, threading.Event())
    first = _list_calls()
    assert path.exists() and h1.index_info["from_cache"] is False and h1.index_info["files"] == 7
    idx = FileIndex.load(path, next(iter(__import__("json").loads(path.read_text())["servers"])))
    assert idx.swept_until == TODAY and idx.files["500008"][0] == "PL-20260305000003"
    assert "THETA" not in path.read_text() and "ALPHA" not in path.read_text()      # numbers and dates only
    mock_server.STATE["log"].clear()
    h2 = collect_history(_cfg(base, ids, path), lambda *a: None, threading.Event())
    second = _list_calls()
    assert h2.index_info["from_cache"] is True and second < first and second <= 2
    assert [(m.entry.raw, m.file_id) for m in h2.matches] == [(m.entry.raw, m.file_id) for m in h1.matches]
    # a corrupt cache is ignored, not fatal
    path.write_text("{ not json", encoding="utf-8")
    h3 = collect_history(_cfg(base, ids, path), lambda *a: None, threading.Event())
    assert h3.index_info["from_cache"] is False and len(h3.results) == 3


def test_full_number_searches_only_around_its_date(env):
    base, tmp = env
    mock_server.STATE["log"].clear()
    h = collect_history(_cfg(base, [make_entry("PL-20261026000001")], tmp / "idx_full.json"), lambda *a: None, threading.Event())
    assert _list_calls() == 1                                          # date -1..+1 day only, no full sweep
    assert h.results[0].file_no == "PL-20261026000001"
    mock_server.STATE["log"].clear()
    collect_history(_cfg(base, [make_entry("PL-20260201000999")], tmp / "idx_full2.json"), lambda *a: None, threading.Event())
    assert _list_calls() == 2                                          # +-1 day, then +-10 days, then "File not found"


def test_cancel_before_start(env):
    base, tmp = env
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        collect_history(_cfg(base, [make_entry("2")], tmp / "idx_cancel.json"), lambda *a: None, ev)


# ------------------------------------------------------------------------------ what is inside a history
def _file(h, no):
    return next(fd for fd in h.results if fd.file_no == no)


def test_timeline_submission_history_and_last_update(run):
    from report_builder.file_history import overview, submission_history, timeline
    h, *_ = run
    f1 = _file(h, "PL-20261026000001")
    ev = timeline(f1)
    assert [e["when"] for e in ev] == sorted((e["when"] for e in ev), reverse=True) and ev[0]["when"] == datetime(2026, 11, 2, 16, 30)
    assert any(e["scope"] == "Trip" and e["trip_id"] == 700030 for e in ev)
    sub = submission_history(f1)
    assert [s["when"] for s in sub] == [datetime(2026, 11, 2, 16, 30), datetime(2026, 10, 29, 14, 0)]
    assert all(re.match(r"^\d{4}-\d\d-\d\d Done-.+\. Due-.+$", s["line"]) for s in sub)
    assert sub[1]["line"].startswith("2026-10-29 Done-")
    # at the first submission the Re-CPV trip (created 30 Oct) did not exist yet
    assert "House" in sub[1]["done"]
    o = overview(f1)
    assert o["type"] == "Loan" and o["last_update"][0].startswith("02/11/2026 16:30:00") and o["area"].startswith("Out")
    assert o["appointments"] == 0
    f3 = _file(h, "PL-20261020000003")
    assert overview(f3)["appointments"] == 1 and overview(f3)["status"] == "Partially Submitted"
    assert len(f1.recpv_events) == 1 and f1.recpv_events[0]["reason"] == "ReCPV House Verification"
    assert len(f1.rows) == 3 and f1.rows[0].file_history


# ------------------------------------------------------------------------------ Excel
def test_excel_sheets_and_cells(run, tmp_path):
    h, *_ = run
    paths = write_history_outputs(h, tmp_path / "out")
    assert len(paths) == 1 and re.fullmatch(r"File_History_\d{4}-\d\d-\d\d_\d{4}\.xlsx", paths[0].name)
    wb = load_workbook(paths[0])
    assert wb.sheetnames == SHEETS
    ws = wb["Summary"]
    rows = {ws.cell(r, 1).value: [ws.cell(r, c).value for c in range(1, 12)] for r in range(4, ws.max_row + 1)}
    assert rows["9999"][1] == "File not found" and rows["PL-20269999999999"][1] == "File not found"
    assert rows["PL-20261026000001"][2] == "Loan" and rows["PL-20261026000001"][3] == "Submitted"
    notes = [ws.cell(r, 11).value for r in range(4, ws.max_row + 1) if ws.cell(r, 1).value == "000003"]
    assert notes == ["Multiple files end with 000003"] * 2
    assert ws.sheet_view.zoomScale == 85 and ws.freeze_panes == "C4"
    f3 = [r for r in range(4, ws.max_row + 1) if ws.cell(r, 2).value == "PL-20261020000003"][0]
    assert ws.cell(f3, 10).value == "Yes"
    tl = wb["Timeline"]
    assert tl.cell(4, 1).value and isinstance(tl.cell(4, 2).value, datetime)
    ap = wb["Appointments"]
    vals = [[c.value for c in row] for row in ap.iter_rows(min_row=4)]
    assert vals[0][0] == "PL-20261020000003" and vals[0][4] == datetime(2026, 11, 1, 10, 0, 0)
    assert "ss" in ap.cell(4, 5).number_format
    rc = wb["Re-CPV & Extra"]
    assert any(rc.cell(r, 2).value == "Re-CPV" and "ReCPV House" in str(rc.cell(r, 6).value) for r in range(4, rc.max_row + 1))
    nf = wb["Not Found"]
    assert [nf.cell(r, 3).value for r in range(4, 6)] == ["File not found"] * 2
    sh = wb["Submission History"]
    assert "calculated from dashboard events" in sh["A2"].value.lower()
    assert any(str(sh.cell(r, 5).value).startswith("2026-11-02 Done-") for r in range(4, sh.max_row + 1))


def test_excel_filter_only_on_file_no_and_no_red_or_yellow(run, tmp_path):
    h, *_ = run
    p = build_history_excel(h, tmp_path / "h.xlsx")
    wb = load_workbook(p)
    for ws in wb.worksheets:
        assert ws.sheet_view.zoomScale == 85 and ws.freeze_panes
        if ws.auto_filter.ref:
            hidden = {fc.colId for fc in ws.auto_filter.filterColumn if fc.hiddenButton}
            n = ws.max_column
            shown = set(range(n)) - hidden
            assert len(shown) == 1                                     # exactly one filter button ...
            assert ws.cell(3, shown.pop() + 1).value in ("File No", "Searched")      # ... on the file-number column
    banned = {"FFF200", "FFFF00", "FF0000", "FEF3C7", "FEE2E2", "DC2626", "EF4444"}
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                for col in (c.fill.fgColor.rgb if c.fill and c.fill.fill_type else None, c.font.color.rgb if c.font and c.font.color else None):
                    if isinstance(col, str):
                        assert col[-6:].upper() not in banned, (ws.title, c.coordinate, col)
