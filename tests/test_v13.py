"""v13 (Naim, 19-11-2026): rules added after comparing the VRB tracker with the dashboard's own tracker of 19-11-2026 Phase 2.
Only these rules changed; every other rule stays as it was."""
import sys
from datetime import datetime as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_builder.billing import build_rows  # noqa: E402
from report_builder.summary import TripView, analyze  # noqa: E402


def _t(tid, code, remarks="", status=5, at=D(2026, 11, 12, 10, 0), comment=""):
    return {"id": tid, "type_code": code, "status_code": status, "remarks": remarks, "comment": comment,
            "created_at": at, "appointments": []}


def _sum(trips, submitted=True, who="App"):
    return analyze([TripView(t, "APPLICANT", who) for t in trips], submitted, "BS")


# ---- 1. an Inactive BS redone by a later Finished BS is not Due (PL-20261111115745017)
def test_inactive_bs_redone_by_a_later_finished_bs_is_dropped():
    s = _sum([_t(1, "HOUSE", "Information ok."),
              _t(2, "BANK", "Called the applicant several times. Call not received.", status=7),
              _t(3, "BANK", "Bank statement collected. Information ok.", at=D(2026, 11, 17, 17, 26))])
    assert s.due == "0"
    assert "BS" in s.done and "BS1" not in s.done and "BS2" not in s.done


def test_inactive_bs_whose_redo_is_still_open_stays_due():
    # PL-20261116092821248: the Re-CPV BS is not finished yet -> the old problem stays Due
    s = _sum([_t(2, "BANK", "Signature mismatch.", status=7),
              _t(3, "BANK", "", status=2, at=D(2026, 11, 19, 13, 41))], submitted=False)
    assert "BS" in s.due


def test_inactive_bs_without_a_later_bs_is_unchanged():
    s = _sum([_t(2, "BANK", "Call not received.", status=7)], submitted=False)
    assert "BS" in s.due


def test_two_finished_bs_keep_their_numbers():
    s = _sum([_t(2, "BANK", "Bank statement collected."), _t(3, "BANK", "Bank statement collected.", at=D(2026, 11, 13))])
    assert "BS1" in s.done and "BS2" in s.done


# ---- 2. Concerns Name lists every trip of the file
def _file():
    def c(cid, role, name, trips):
        return {"id": cid, "role": role, "name": name, "trips": trips}
    start = D(2026, 11, 12, 9, 0)
    app = c(1, "APPLICANT", "APP ONE", [_t(11, "HOUSE", at=start), _t(12, "OFFICE", at=start), _t(13, "BANK", at=start),
                                        _t(14, "DOCUMENT", at=start, comment="LOI verification"),
                                        _t(15, "DOC_DRCHAMBER", at=D(2026, 11, 16, 17, 15), status=4)])
    co = c(2, "CO_APPLICANT", "CO TWO", [_t(21, "HOUSE", at=start), _t(22, "BANK", at=start)])
    pg = c(3, "GUARANTOR", "PG THREE", [_t(31, "GUARANTOR_HOUSE", at=start), _t(32, "GUARANTOR_OFFICE", at=start),
                                         _t(33, "BANK", at=start)])
    return {"id": 9, "file_no": "PL-20261112000001", "type": "Loan", "start_date": start, "created_at": start,
            "station": "In Station", "status_code": 3, "concerns": [app, co, pg]}


def test_concerns_name_lists_every_trip_of_the_file():
    rows = build_rows(_file(), {}, {}, None, D(2025, 1, 1))
    assert len(rows) > 1                                    # package + LOI row + chamber row (bill rows unchanged)
    lines = rows[0].file_concern_lines
    assert lines == ["1. Applicant: APP ONE - House, Office, BS, Document, Chamber",
                     "2. Co-Applicant: CO TWO - House, BS",
                     "3. Guarantor 1: PG THREE - House, Office, BS"]
    assert all(r.file_concern_lines == lines for r in rows)
    assert "Chamber" not in "\n".join(rows[0].concern_lines)    # the bill row's own trips are unchanged


# ---- 3. the header counts unique file numbers
def test_header_counts_unique_file_numbers():
    import inspect
    from report_builder import prime_excel
    assert "len({x.file_no for x in rows})" in inspect.getsource(prime_excel)


# ---- 4. a re-opened file stays in the Complete Report, marked in its row (Excel + PDF)
def test_reopened_file_is_marked_in_the_complete_row(tmp_path):
    import threading
    from datetime import date
    import openpyxl
    sys.path.insert(0, str(ROOT / "tests"))
    import mock_server
    from report_builder.collect_prime import PrimeConfig, collect_prime
    from report_builder.prime_excel import build_prime_excel
    from report_builder.prime_pdf import build_prime_pdf
    srv = mock_server.start_scenario(0)
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                          mode="tracker", report_date=date(2026, 11, 2), slot="7pm", incomplete_scope="all_pending")
        d = collect_prime(cfg, lambda *a: None, threading.Event())
    finally:
        srv.shutdown()
    assert d.complete, "the mock scenario needs a Complete row"
    r = d.complete[0]
    r.reopen_note = "Re-opened since - now On Going on the dashboard"
    ws = openpyxl.load_workbook(build_prime_excel(d, tmp_path / "t.xlsx"))["Complete Report"]
    hdr = [c.value for c in ws[4]]
    cell = ws.cell(5, hdr.index("Report Status") + 1)
    assert cell.value == "Submitted\n(Re-opened since - now On Going on the dashboard)"
    assert build_prime_pdf(d, tmp_path / "t.pdf").exists()
    # Concerns Name in the tracker = every trip of the file
    assert ws.cell(5, hdr.index("Concerns Name") + 1).value == "\n".join(r.file_concern_lines or r.concern_lines)
