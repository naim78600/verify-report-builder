"""Version 5: (1) File History no longer crashes when a sheet is empty ("'MergedCell' object is not iterable"),
(2) the input Excel can carry File No + Applicant Name (+ a ready template), (3) Done / Due follow the verifier's REMARKS only,
never the back-office COMMENT."""
import sys
import threading
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import mock_server  # noqa: E402
import pytest  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402

from report_builder.file_history import (HistoryConfig, collect_history, make_entry, name_check, names_match,  # noqa: E402
                                         parse_ids_file)
from report_builder.history_excel import Col, _sheet, build_history_excel, write_history_template  # noqa: E402
from test_v321 import _trip  # noqa: E402
from test_v322 import _sum  # noqa: E402

TODAY = date(2026, 11, 5)


# ------------------------------------------------------------------------------ File History crash
def test_an_empty_sheet_with_a_file_no_column_does_not_crash():
    wb = Workbook()
    cols = [Col("File No", 20, "file_no"), Col("X", 10, "x")]
    _sheet(wb, "empty", "h", "s", cols, [], file_key="file_no")            # was: TypeError 'MergedCell' object is not iterable
    _sheet(wb, "empty2", "h", "s", cols, [], file_key="nothing")
    assert wb["empty"].freeze_panes == "B4" and wb["empty2"].freeze_panes == "A4"


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    srv = mock_server.start_scenario(0)
    yield f"http://127.0.0.1:{srv.server_address[1]}", tmp_path_factory.mktemp("v5")
    srv.shutdown()


def _run(env, entries, name):
    base, tmp = env
    cfg = HistoryConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", ids=entries,
                        index_path=tmp / f"idx_{name}.json", today=TODAY)
    return collect_history(cfg, lambda *a: None, threading.Event()), tmp


def test_all_files_found_means_an_empty_not_found_sheet_and_the_workbook_is_written(env):
    ids = [make_entry("PL-20261026000001"), make_entry("CC-20261101000002")]
    h, tmp = _run(env, ids, "allfound")
    assert not h.not_found
    path = build_history_excel(h, tmp / "all_found.xlsx")                   # the real-world crash: Not Found had no rows
    wb = load_workbook(path)
    assert "Not Found" in wb.sheetnames
    assert "Every number was found." in [c.value for row in wb["Not Found"].iter_rows() for c in row]


# ------------------------------------------------------------------------------ input Excel: File No + Applicant Name
def _sheet_file(tmp, rows, header=("File No", "Applicant Name"), name="in.xlsx"):
    wb = Workbook()
    ws = wb.active
    ws.append(list(header))
    for r in rows:
        ws.append(list(r))
    p = tmp / name
    wb.save(p)
    return p


def test_input_excel_with_file_no_and_applicant_name(tmp_path):
    p = _sheet_file(tmp_path, [("PL-20261026000001", "  alpha   one "), ("CC-20261101000002", "Gamma Two"), ("441930", None),
                               ("PL-20261026000001", "dup"), ("", "orphan name")])
    got = parse_ids_file(p)
    assert [e.raw for e in got] == ["PL-20261026000001", "CC-20261101000002", "441930"]
    assert [e.name for e in got] == ["alpha one", "Gamma Two", ""]


def test_name_column_found_by_header_words_only(tmp_path):
    p = _sheet_file(tmp_path, [("PL-20261026000001", "x y"), ("CC-20261101000002", "z w")], header=("Tracking No.", "Customer Name"))
    assert [e.name for e in parse_ids_file(p)] == ["x y", "z w"]
    q = _sheet_file(tmp_path, [("PL-20261026000001", "x y")], header=("File No", "Remarks"), name="q.xlsx")     # no name header -> no name guessed
    assert [e.name for e in parse_ids_file(q)] == [""]


def test_the_template_is_readable_and_empty_until_filled(tmp_path):
    p = write_history_template(tmp_path / "File_History_Format.xlsx")
    wb = load_workbook(p)
    assert wb.sheetnames == ["File History", "How to fill"]
    assert [c.value for c in wb["File History"][1]] == ["File No", "Applicant Name"]
    assert parse_ids_file(p) == []                                         # the instruction sheet must never be searched
    wb = load_workbook(p)
    ws = wb["File History"]
    ws["A2"], ws["B2"] = "CC-20261025000001", "SOME APPLICANT"
    ws["A3"], ws["B3"] = "000123", "ANOTHER ONE"
    wb.save(p)
    got = parse_ids_file(p)
    assert [(e.raw, e.name) for e in got] == [("CC-20261025000001", "SOME APPLICANT"), ("000123", "ANOTHER ONE")]
    assert got[0].kind == "full" and got[1].kind == "suffix"
    assert wb["File History"]["A2"].number_format == "@"                    # leading zeros are never lost


def test_names_match_tolerates_how_people_write_a_name():
    assert names_match("MOHAMMAD ZAHIR UDDIN", "Md. Zahir Uddin")
    assert names_match("ZAHIR UDDIN MOHAMMAD", "mohammad zahir uddin")
    assert names_match("Zahir Uddin", "MOHAMMAD ZAHIR UDDIN")                # one word less
    assert not names_match("ALPHA ONE", "GAMMA TWO") and not names_match("", "A B")


def test_history_with_names_adds_the_check_columns_and_without_names_nothing_changes(env):
    ids = [make_entry("PL-20261026000001"), make_entry("CC-20261101000002"), make_entry("CC-20260115000004"), make_entry("PL-20261026999999")]
    for e, n in zip(ids, ["alpha one", "SOMEONE ELSE", "beta one", "NOBODY"]):
        e.name = n
    h, tmp = _run(env, ids, "names")
    ws = load_workbook(build_history_excel(h, tmp / "names.xlsx"))["Summary"]
    head = [c.value for c in ws[3]]
    assert head[:4] == ["Searched", "Applicant Name (given)", "Name Check", "Applicant on the file"]
    rows = {r[0].value: [c.value for c in r] for r in ws.iter_rows(min_row=4)}
    assert rows["PL-20261026000001"][1:4] == ["alpha one", "Matches", "ALPHA ONE"]
    assert rows["CC-20261101000002"][2] == "Different" and rows["CC-20261101000002"][3] == "GAMMA TWO"
    assert rows["PL-20261026999999"][1] == "NOBODY" and "not found" in str(rows["PL-20261026999999"][4]).lower()
    # the guarantor's name is recognised as another concern of the file
    pl1 = next(x for x in h.results if x.file_no == "PL-20261026000001").file
    assert name_check("BETA ONE", pl1)[0].startswith("Matches Guarantor")
    nf = [c.value for c in load_workbook(tmp / "names.xlsx")["Not Found"][3]]
    assert nf[:2] == ["Searched", "Applicant Name (given)"]
    # no names in the input -> the sheets are exactly the old ones
    h2, tmp2 = _run(env, [make_entry("PL-20261026000001")], "nonames")
    wb2 = load_workbook(build_history_excel(h2, tmp2 / "nonames.xlsx"))
    assert [c.value for c in wb2["Summary"][3]][:3] == ["Searched", "File No", "Type"]
    assert [c.value for c in wb2["Not Found"][3]][:2] == ["Searched", "Kind"]


# ------------------------------------------------------------------------------ Done / Due = remarks, never the comment
REM_500204 = "HR payslip will be not verified. HR will verified only salary certificate."      # the shape of the reported file's trip
COMMENT = "LOI will be signed From head office"                                                   # back-office instruction


def _dd(remarks, comment="", submitted=True, **kw):
    s = _sum([_trip(9, "DOCUMENT", remarks, comment, **kw)], submitted=submitted)
    return s.done, s.due


def test_the_back_office_comment_never_changes_done_or_due():
    base = _dd(REM_500204, "")
    assert _dd(REM_500204, COMMENT) == base
    assert _dd(REM_500204, "Collect LOI. Signatory may disagree to verify. Not available on Saturday") == _dd(REM_500204, "LOI verification")
    ok = _dd("Information ok. LOI signed infront of me.", "LOI verification")
    assert _dd("Information ok. LOI signed infront of me.", COMMENT) == ok
    assert _dd("Information ok. LOI signed infront of me.", "LOI will be signed From head office. Need forwarding letter.") == ok


def test_the_reported_trip_reads_the_remarks_not_the_comment():
    done, due = _dd(REM_500204, COMMENT)
    assert done == "LOI (HR verifies salary certificate only)" and due == done
    assert "head office" not in (done + due).lower()                       # neither the comment's wording nor a made-up refusal


def test_an_instruction_in_the_comment_alone_is_not_a_due_item():
    assert _dd("", COMMENT) == ("LOI", "0")                                # finished trip, nothing reported = nothing due
    done, due = _dd("", COMMENT, submitted=False, status=2)                # not started: the reason is the status, not the comment
    assert due == "LOI (Not visited yet)" and done == "0"


def test_hr_refusal_in_the_remarks_is_still_a_head_office_problem():
    done, due = _dd("HR does not agree to verify the LOI. Head office disagree.", COMMENT)
    assert "Head office disagree" in due and "Will be signed from head office" not in due
    done, due = _dd("Will be signed from head office, as told by the guard.", "")
    assert "Will be signed from head office" in due                         # the same words in the REMARKS still count


def test_payslip_sentence_is_the_salary_certificate_note_not_a_refusal():
    for rem in ("HR payslip will be not verified. HR will verified only salary certificate.",
                "HR does not verify payslip.", "Payslip not verified, only salary certificate verified by HR."):
        done, due = _dd(rem, "")
        assert "HR verifies salary certificate only" in due, rem
        assert "Head office disagree" not in due, rem


# ------------------------------------------------------------------------------ end to end: dashboard -> tracker Excel
import prime_scenario as ps  # noqa: E402
from report_builder.collect_prime import PrimeConfig, collect_prime  # noqa: E402
from report_builder.reports import write_prime_outputs  # noqa: E402

RDAY = date(2026, 11, 2)


def _e2e_file(fid, no, comment):
    """A Submitted package shaped like the reported file: house + office fine, a Document trip whose back-office COMMENT is the
    instruction and whose REMARKS are what the verifier found."""
    d = "2026-10-27 10:00:00"
    cid = fid * 10 + 1
    app = ps.application(fid, no, d, 6, [ps.concern(cid, fid, "APPLICANT", "TEST APPLICANT", [
        ps.trip(fid * 100 + 1, cid, "HOUSE", 5, d, ps.OK),
        ps.trip(fid * 100 + 2, cid, "OFFICE", 5, d, "Information ok. Applicant signed in front of me."),
        ps.trip(fid * 100 + 3, cid, "DOCUMENT", 5, d, REM_500204, comment)])])
    ps.LOGS[fid] = [ps._log("APPLICATION", fid, f"Application : {fid} status updated to SUBMITTED by Mgr", "HOLD", "SUBMITTED", "2026-11-02 12:00:00")]
    return app


def _report_summary(srv, tmp, fid):
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30, mode="tracker",
                      report_date=RDAY, slot="7pm")
    xlsx = write_prime_outputs(collect_prime(cfg, lambda *a: None, threading.Event()), tmp)[0]
    ws = load_workbook(xlsx)["Complete Report"]
    head = {c.value: c.column for c in ws[next(r[0].row for r in ws.iter_rows(max_row=12) if any(c.value == "File No" for c in r))]}
    for row in ws.iter_rows():
        if any(isinstance(c.value, str) and c.value == f"PL-{fid}" for c in row):
            return str(row[head["Report Summary"] - 1].value)
    raise AssertionError("file row not found in the Complete Report")


def test_end_to_end_the_tracker_excel_summary_follows_the_remarks_not_the_comment(tmp_path):
    srv = mock_server.start_scenario(0)
    try:
        mock_server.STATE["files"].append(_e2e_file(600001, "PL-600001", COMMENT))
        mock_server.STATE["files"].append(_e2e_file(600002, "PL-600002", "Some completely different instruction. Signatory may refuse. Need forwarding letter."))
        a = _report_summary(srv, tmp_path / "a", 600001)
        b = _report_summary(srv, tmp_path / "b", 600002)
    finally:
        for k in (600001, 600002):
            ps.LOGS.pop(k, None)
        srv.shutdown()
    assert a == b                                                          # the comment changes nothing
    assert "LOI (HR verifies salary certificate only)" in a
    assert "Will be signed from head office" not in a and "forwarding" not in a.lower() and "refuse" not in a.lower()


def test_a_comment_word_that_only_contains_rent_does_not_make_a_rental_item():
    done, _due = _dd("Information ok. LOI signed infront of me.", "Verify at a different address, current parent office")
    assert "Rental" not in done
    done, _due = _dd("Information ok.", "Rental agreement verification")
    assert "Rental" in done


# ------------------------------------------------------------------------------ the "due check": comment-invariance over many remark styles
_REMARKS = [
    "", "Information ok.", "Information ok. Applicant signed in front of me. LOI signed infront of me.", REM_500204, "HR does not verify payslip.",
    "HR does not agree to verify the LOI.", "LOI will be signed from head office.", "Need forwarding letter for LOI verification.",
    "LOI not verified. Signatory not available.", "Applicant disagree to verify.", "Applicant not available. Will come again tomorrow.",
    "Office closed.", "Given address wrong.", "Call not received. Phone switch off.", "Bank statement not verified. Insufficient fund.",
    "Signature mismatch. Seal missing.", "Previous signatory not available.. LOI sing by new signatory",
    "Signatory said LOI can be verified from the Sylhet branch.", "Verification need to be done by email.",
]
_COMMENTS = ["", "LOI VERIFICATION", COMMENT, "Collect LOI. Signatory may disagree to verify", "Need forwarding letter",
             "Applicant not available on Saturday. Not verified earlier.", "Verify at a different address"]


@pytest.mark.parametrize("code", ["HOUSE", "OFFICE", "BANK", "GUARANTOR_HOUSE", "GUARANTOR_OFFICE"])
@pytest.mark.parametrize("status,submitted", [(5, True), (2, False), (4, False)])
def test_due_check_house_office_bank_trips_ignore_the_comment_completely(code, status, submitted):
    for rem in _REMARKS:
        want = None
        for com in _COMMENTS:
            s = _sum([_trip(1, code, rem, com, status=status)], submitted=submitted)
            got = (s.done, s.due)
            assert want in (None, got), (code, status, rem, com, want, got)
            want = got


def test_due_check_a_loi_document_trip_ignores_the_comment_text():
    for status, submitted in ((5, True), (2, False), (4, False)):
        for rem in _REMARKS:
            outs = {_dd(rem, com, submitted=submitted, status=status) for com in ("LOI VERIFICATION", COMMENT, "Collect LOI. Signatory may disagree to verify",
                                                                                    "LOI sign. Need forwarding letter. Applicant not available")}
            assert len(outs) == 1, (status, rem, outs)


# ------------------------------------------------------------------------------ cases read from the LIVE dashboard (names / numbers removed)
from datetime import datetime as _D  # noqa: E402
from report_builder.billing import fold_complete  # noqa: E402
from test_v321 import _row  # noqa: E402

_LRM = "‎‎"        # the dashboard puts two invisible marks between a verifier's sentences


def test_invisible_marks_between_sentences_do_not_glue_them_together():
    rem = (f"Information ok.{_LRM}Confirmed Applicant's self. {_LRM}Applicant was present at office and signed in front of me.{_LRM}"
           "Loi Panding.signatory is not available.")
    s = _sum([_trip(1, "OFFICE", rem)])
    assert "Sign" in s.done and "LOI" in s.due                          # was: "Sign" lost (sentence glued to the LOI sentence)


def test_live_file_package_plus_later_document_trip_settles_the_loi_from_the_remarks():
    """File shaped like the one reported (house + office + bank in the package, a later Document trip on the same Submit day)."""
    sub = _D(2026, 11, 4, 17, 9)
    pk = _row("Package", [
        (_trip(498280, "HOUSE", "Information ok. Proper address is : <address>. Mobile number is ok.", "-", created=_D(2026, 11, 1, 20, 35)), "App"),
        (_trip(498281, "OFFICE", "Information ok. Address is Ok. Applicant was present at office And signed in front of me. "
                                 "LOI will be signed From head office.", "- Office Name: <office>", created=_D(2026, 11, 1, 20, 35)), "App"),
        (_trip(498282, "BANK", "Bank statement Hard copy provided. verified.", "<account number>", created=_D(2026, 11, 1, 20, 35)), "App")], sub)
    assert pk.summary.due == "LOI (Will be signed from head office)"      # what the OFFICE remarks said
    ex = _row("Extra", [(_trip(500204, "DOCUMENT", REM_500204, COMMENT, created=_D(2026, 11, 4, 16, 7)), "App")], sub)
    out = fold_complete([pk, ex])
    assert len(out) == 1
    assert out[0].summary.done == "App House, Office, Sign, LOI (HR verifies salary certificate only), BS"
    assert out[0].summary.due == "LOI (HR verifies salary certificate only)"       # the later trip's remarks win; no made-up refusal


def test_live_file_loi_pending_in_the_office_visit_and_signed_by_a_later_document_trip_is_done():
    sub = _D(2026, 11, 4, 14, 9)
    office = ("Information ok." + _LRM + "Confirmed Applicant's self. " + _LRM + "Applicant was present at office and signed in front of me." + _LRM +
              "Loi Panding.signatory is not available. Remarks Update 04-11-2026:- LOI signed infront of me. LOI signed by Signatory Name :- <name>")
    pk = _row("Package", [(_trip(495023, "HOUSE", "Information ok. Address is ok.", "-", created=_D(2026, 10, 27, 19, 20)), "App"),
                          (_trip(495024, "OFFICE", office, "- Office Name: <office>", created=_D(2026, 10, 27, 19, 20)), "App")], sub)
    ex = _row("Extra", [(_trip(498731, "DOCUMENT", "Information OK. Confirmed by Receptionist. LOI signed infront of me. LOI signed by Signatory Name :- <name>",
                               "Loi Sing.", created=_D(2026, 11, 2, 17, 47)), "App")], sub)
    out = fold_complete([pk, ex])
    assert (out[0].summary.done, out[0].summary.due) == ("App House, Office, Sign, LOI", "0")
