"""Version 6: (1) after an appointment the report is due the next working day by 5:59 PM (tests in test_v33.py),
(2) the tracker has the 20 columns in the bank's order (tests in test_prime.py), (3) the bill rows are built the way the manual
bill is written (In-station document of an Out package, guarantor rows, Canceled trips), (4) the monthly bill: everything CREATED
in the month, Card and Loan apart, Excel + PDF, penalty list, check sheet."""
import sys
import threading
from datetime import date, datetime as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import mock_server  # noqa: E402
import pytest  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from report_builder.bill_out import pdf_from_excel, read_bill_excel, write_month_bill  # noqa: E402
from report_builder.billing import SLAB_DOC, SLAB_PG, build_rows, slab_for, trip_billable  # noqa: E402
from report_builder.collect_prime import PrimeConfig, collect_prime  # noqa: E402
from report_builder.monthly_bill import (bill_ref, build_month_bill, in_words, month_window, penalty_pct, rate_for,  # noqa: E402
                                         section_key)

GULSHAN, SAVAR = (23.7925, 90.4078), (23.8583, 90.2667)


def _t(tid, code, created, status=5, loc=GULSHAN, start=True, recpv=False, comment=""):
    return {"id": tid, "type_code": code, "type": code.title(), "status_code": status, "created_at": created, "remarks": "Information ok.",
            "comment": comment, "lat": loc[0], "lon": loc[1], "end_lat": None, "end_lon": None, "address": "", "exact_address": "",
            "area": "", "place_name": "", "appointments": [], "re_cpv": recpv, "start_time": created if start else None, "end_time": None}


def _file(trips_by_role, no="PL-20260901000001", start=D(2026, 9, 1, 10, 0)):
    cons = []
    for n, (role, trips) in enumerate(trips_by_role, 1):
        cons.append({"id": n, "role": role, "name": f"{role} {n}", "trips": trips})
    return {"id": 9, "file_no": no, "type": "", "status_code": 6, "station": "Out Station", "start_date": start, "created_at": start,
            "concerns": cons}


def _rows(file):
    return build_rows(file, {}, {}, None, D(2025, 1, 1))


# ------------------------------------------------------------------------------ bill rows (the manual bill's way)
def test_an_in_station_document_of_an_out_package_is_billed_on_its_own_row():
    d = D(2026, 9, 1, 10, 0)
    f = _file([("APPLICANT", [_t(1, "HOUSE", d, loc=SAVAR), _t(2, "OFFICE", d, loc=SAVAR), _t(3, "BANK", d, loc=SAVAR),
                              _t(4, "DOCUMENT", d, loc=GULSHAN, comment="LOI VERIFICATION")])])
    rows = _rows(f)
    assert [(r.kind, r.slab, r.area, r.split) for r in rows] == [("Package", "Package", "Out", False), ("Single", SLAB_DOC, "In", True)]
    assert rows[1].category == "Created - Extra Document(LOI)" and len(rows[0].trips) == 3
    # the applicant himself is In station: the LOI stays inside the package
    f2 = _file([("APPLICANT", [_t(1, "HOUSE", d), _t(2, "OFFICE", d), _t(4, "DOCUMENT", d)]),
                ("GUARANTOR", [_t(5, "GUARANTOR_HOUSE", d, loc=SAVAR)])])
    assert [(r.kind, r.area, len(r.trips)) for r in _rows(f2)] == [("Package", "Out", 4)]
    # an Out document of an Out package stays inside the package too
    f3 = _file([("APPLICANT", [_t(1, "HOUSE", d, loc=SAVAR), _t(4, "DOCUMENT", d, loc=SAVAR)])])
    assert [(r.kind, len(r.trips)) for r in _rows(f3)] == [("Package", 2)]


def test_guarantor_rows_follow_the_manual_bill():
    d, later = D(2026, 9, 1, 10, 0), D(2026, 9, 10, 12, 0)
    assert slab_for({"type_code": "GUARANTOR_HOUSE"}, "GUARANTOR") == SLAB_PG                    # a new guarantor visit
    assert slab_for({"type_code": "GUARANTOR_HOUSE"}, "GUARANTOR", recpv=True) == "Single House"    # the same house again
    assert slab_for({"type_code": "GUARANTOR_OFFICE"}, "GUARANTOR", recpv=True) == "Single Office"
    assert slab_for({"type_code": "DOCUMENT"}, "GUARANTOR") == SLAB_DOC                           # only the guarantor's signature
    assert slab_for({"type_code": "HOUSE"}, "APPLICANT") == "Single House" and slab_for({"type_code": "BANK"}, "APPLICANT") == "BS"
    f = _file([("APPLICANT", [_t(1, "HOUSE", d)]),
               ("GUARANTOR", [_t(5, "GUARANTOR_HOUSE", later), _t(6, "GUARANTOR_OFFICE", later)]),
               ("GUARANTOR", [_t(7, "GUARANTOR_HOUSE", later, recpv=True)])])
    rows = _rows(f)
    assert [(r.kind, r.slab, len(r.trips), r.category) for r in rows] == [
        ("Package", "Package", 1, "Created (1 trips)"), ("Extra", SLAB_PG, 2, "Extra Trip"), ("ReCpv", "Single House", 1, "Re-CPV")]
    assert sum(len(r.trips) for r in rows) == 4                                                   # no trip is ever lost


def test_canceled_trips_never_take_a_package_place_and_the_cancel_rule():
    d = D(2026, 9, 1, 10, 0)
    dead = [_t(n, "HOUSE", d, status=6, start=False) for n in range(1, 6)]                        # a batch created twice by mistake
    live = [_t(11, "HOUSE", d), _t(12, "OFFICE", d), _t(13, "BANK", d), _t(14, "DOCUMENT", d)]
    rows = _rows(_file([("APPLICANT", dead + live)]))
    assert [(r.kind, len(r.trips), r.billable, r.canceled) for r in rows] == [("Package", 9, True, False)]
    assert trip_billable(_t(1, "HOUSE", d, status=7)) and trip_billable(_t(1, "HOUSE", d, status=6, start=True))   # Inactive; Canceled but started
    assert not trip_billable(_t(1, "HOUSE", d, status=6, start=False)) and not trip_billable(_t(1, "HOUSE", d, status=8))
    stopped = _rows(_file([("APPLICANT", [_t(1, "HOUSE", d, status=6), _t(2, "OFFICE", d, status=6)])]))    # the bank stopped a started file
    assert [(r.kind, r.billable, r.canceled) for r in stopped] == [("Package", True, True)]
    mistake = _rows(_file([("APPLICANT", [_t(1, "HOUSE", d, status=6, start=False)])]))
    assert [(r.billable, r.canceled) for r in mistake] == [(False, True)]


# ------------------------------------------------------------------------------ rates / penalty / words
def test_rates_penalty_and_words():
    assert [rate_for("Card", "Package", a) for a in ("In", "Out")] == [450, 600]
    assert [rate_for("Loan", "Package", a) for a in ("In", "Out")] == [600, 700]
    assert [rate_for("Loan", c, "In") for c in ("doc", "house", "pg")] == [140, 140, 140]
    assert [rate_for("Card", c, "Out") for c in ("doc", "house", "pg")] == [170, 240, 230]
    assert [section_key(c, "Out") for c in ("Package", "doc", "house", "pg")] == ["out_pkg", "out_doc", "out_house", "out_pg"]
    assert section_key("pg", "In") == "in_single"
    assert [penalty_pct(n) for n in (None, 0, 1, 2, 3, 9)] == [0, 0, 20, 30, 50, 50]
    assert in_words(213664.5) == "Two lakh thirteen thousand six hundred sixty-four taka and fifty paisa only."
    assert in_words(120446) == "One lakh twenty thousand four hundred forty-six taka only."
    assert in_words(0) == "Zero taka only." and in_words(100000) == "One lakh taka only."
    assert month_window(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28)) and bill_ref(2026, 9) == "Barikoi/PrimeBank/CPVBill-September/2026/09"


# ------------------------------------------------------------------------------ the monthly bill, end to end (mock dashboard)
@pytest.fixture(scope="module")
def october():
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    lo, hi = month_window(2026, 10)
    cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30, mode="bill",
                      date_from=lo, date_till=hi)
    d = collect_prime(cfg, lambda *a: None, threading.Event())
    yield d, build_month_bill(d.all_rows, 2026, 10, date(2026, 11, 10), d.files)
    srv.shutdown()


def test_everything_created_in_the_month_is_on_a_bill(october):
    d, mb = october
    card, loan = mb.bills["Card"], mb.bills["Loan"]
    key = lambda i: (i.file_no[-4:], i.section, i.amount, i.kind)                                    # noqa: E731
    # F6 (27 Oct, Out, two In documents), F4 = an OLD file (January) with an extra LOI created on 31 Oct
    assert sorted(map(key, card.items)) == sorted([("0006", "out_pkg", 600, "Package"), ("0006", "in_single", 140, "Single"),
                                                   ("0006", "in_single", 140, "Single"), ("0004", "in_single", 140, "Extra")])
    # F3 (20 Oct, still pending), F1 (26 Oct, Out because of the guarantor) + its 6th trip + its Re-CPV of 30 Oct, F5 = a 2025 file's Re-CPV
    assert sorted(map(key, loan.items)) == sorted([("0003", "in_pkg", 600, "Package"), ("0001", "out_pkg", 700, "Package"),
                                                   ("0001", "in_single", 140, "Single"), ("0001", "in_single", 140, "ReCpv"),
                                                   ("0005", "in_single", 140, "ReCpv")])
    assert not any(i.file_no.endswith("0002") for b in mb.bills.values() for i in b.items)             # F2 was created on 1 November
    st = mb.stats
    assert st["rows_in_month"] == st["billed"] + st["excluded"] == 9 and st["dashboard_trips_created"] == st["trips_in_month"]
    pending = next(i for i in loan.items if i.file_no.endswith("0003"))
    assert pending.sub is None and "not yet submitted" in pending.note                              # created = billed, submitted or not
    f1 = next(i for i in loan.items if i.file_no.endswith("0001") and i.kind == "Package")
    assert f1.sub == date(2026, 10, 29) and (f1.tat, f1.extra_tat, f1.pct) == (3, 0, 0)
    # a submission AFTER the month is still read (F6 was submitted on 2 November)
    assert next(i for i in card.items if i.section == "out_pkg").sub == date(2026, 11, 2)


def test_bill_totals_and_penalty_choices(october, tmp_path):
    _d, mb = october
    loan = mb.bills["Loan"]
    assert loan.subtotal == 600 + 700 + 3 * 140
    # the starting choice follows the manual bill: a late row is charged only when it is a SUBMITTED package / bank statement;
    # the pending package (F3) and the late extra-document / Re-CPV rows are listed with Apply = No
    late = [i for i in loan.items if i.pct]
    assert sorted((i.kind, i.pct, i.apply) for i in late) == [("Package", 50, False), ("ReCpv", 50, False), ("Single", 20, False)]
    assert "not yet submitted" in next(i for i in late if i.kind == "Package").pen_note
    assert loan.deduction == 0 and loan.grand_total == round(loan.subtotal * 1.05, 2)
    f1 = next(i for i in loan.items if i.file_no.endswith("0001") and i.kind == "Package")
    f1.extra_tat, f1.pct, f1.apply = 2, 30, True                      # a submitted package that is 2 days late IS charged
    assert loan.deduction == 210 and loan.grand_total == round((loan.subtotal - 210) * 1.05, 2)
    f1.extra_tat, f1.pct = 0, 0
    paths = write_month_bill(mb, tmp_path)
    assert sorted(p.name for p in paths) == ["Prime_Bank_PLC_Card_Invoice_October_2026.pdf", "Prime_Bank_PLC_Card_Invoice_October_2026.xlsx",
                                             "Prime_Bank_PLC_Loan_Invoice_October_2026.pdf", "Prime_Bank_PLC_Loan_Invoice_October_2026.xlsx"]
    assert all(p.stat().st_size > 3000 for p in paths)
    xlsx = tmp_path / "Prime_Bank_PLC_Loan_Invoice_October_2026.xlsx"
    wb = load_workbook(xlsx)
    assert wb.sheetnames == ["Invoice", "Details", "Penalty", "Check"]
    inv = wb["Invoice"]
    assert inv["A1"].value == "Verification Bill For October 2026 - Loan" and "CPVBill-October/2026/10" in inv["A2"].value
    assert inv["C8"].value == '=COUNTIF(Details!$A:$A,"in_pkg")' and inv["E8"].value == "=C8*D8" and inv["D8"].value == 600
    back = read_bill_excel(xlsx)                                                                       # the workbook reads back exactly
    assert (len(back.items), back.subtotal, back.deduction, back.grand_total) == (len(loan.items), loan.subtotal, loan.deduction, loan.grand_total)
    # the user waives one penalty on the Penalty sheet -> the PDF made from the workbook follows
    pen = wb["Penalty"]
    assert pen.cell(2, 15).value == "Why (starting choice)" and all(pen.cell(r, 15).value for r in range(3, 6))
    first = next(r for r in range(3, pen.max_row + 1) if pen.cell(r, 14).value == "No")
    charged = pen.cell(first, 11).value * pen.cell(first, 12).value / 100
    pen.cell(first, 14).value = "Yes"                                 # the user decides to charge a listed row
    wb.save(xlsx)
    after = read_bill_excel(xlsx)
    assert after.deduction == loan.deduction + charged and after.grand_total < loan.grand_total
    assert pdf_from_excel(xlsx).stat().st_size > 3000
    check = [[c.value for c in row] for row in wb["Check"].iter_rows(max_row=14)]
    assert any(r[0] == "Result" and str(r[1]).startswith("OK") for r in check)


# ------------------------------------------------------------------------------ Done / Due (v6 training against the manual tracker)
def _sum(trips):
    from report_builder.summary import TripView, analyze
    return analyze([TripView(t, "APPLICANT", "App") for t in trips], True, "BS")


def _rt(tid, code, remarks, status=5, comment=""):
    return {"id": tid, "type_code": code, "status_code": status, "remarks": remarks, "comment": comment, "created_at": D(2026, 9, 1, 10, 0),
            "appointments": []}


def test_an_inactive_bank_trip_with_a_problem_is_its_own_statement_and_stays_due():
    s = _sum([_rt(1, "HOUSE", "Information ok."), _rt(2, "BANK", "Bank statement verified. Hard copy provided."),
              _rt(3, "BANK", "Bank statement not verified.Applicant account seal not available.", status=7)])
    assert "BS1" in s.done and s.due.startswith("BS2 (") and s.uncertain                      # was lost: both were "BS", the Done one hid the Due one
    s = _sum([_rt(1, "HOUSE", "Applicant is very ill and not at the address now, he does not know when he returns.", status=7)])
    assert s.due.startswith("App House (") and s.uncertain                                    # words no rule knows: still Due, flagged
    s = _sum([_rt(1, "DOCUMENT", "Loi Verification complete.", status=7, comment="LOI VERIFICATION")])
    assert s.due == "0"                                                                       # an Inactive trip that reads finished is not a problem


def test_a_problem_written_under_the_pec_heading_belongs_to_the_pec_not_the_loi():
    s = _sum([_rt(1, "OFFICE", "Information ok. LOI signed infront of me. LOI sign by Name: A B, Designation: Manager. PEC verify. "
                               "Mention signatory person not available. The signatory is currently in Dhaka.")])
    assert "LOI" in s.done.replace("PEC", "") and s.due == "PEC (Signatory not available)"
    s = _sum([_rt(1, "OFFICE", "Information ok. LOI signed in front of me. LOI signatory name: A B. PEC verify.Address found but unable "
                               "to contact with office anyone.")])
    assert s.due.startswith("PEC (Address found but unable") and s.uncertain


def test_loi_not_signed_in_front_of_me_with_a_named_signatory_is_a_signed_loi():
    s = _sum([_rt(1, "DOCUMENT", "Information ok. LOI not signed in front of me. LOI signatory name: A B. Designation: Manager, HR.",
                  comment="LOI VERIFICATION")])
    assert (s.done, s.due) == ("LOI", "0")
    s = _sum([_rt(1, "DOCUMENT", "LOI not signed in front of me. Signatory not available today.", comment="LOI VERIFICATION")])
    assert "LOI" in s.due


def test_signature_that_could_not_be_taken_is_due_even_in_an_information_ok_remark():
    s = _sum([_rt(1, "OFFICE", "Information is ok. The applicant resides in Dhaka and visits the business address very rarely. "
                               "Therefore, the applicant's signature could not be obtained.")])
    assert s.due == "App Sign (Signature missing)"
    s = _sum([_rt(1, "OFFICE", "Information ok. LOI signed infront of me. LOI sign by (Name: A B). The applicant is on leave due to an "
                               "accident. Thats why can not take applicant sign.")])
    assert "App Sign (Signature missing)" in s.due and "LOI" in s.done
    s = _sum([_rt(1, "OFFICE", "Information ok. Applicant was present at office and signed in front of me.")])
    assert s.due == "0" and "Sign" in s.done


def test_chamber_problem_inside_an_office_remark_is_its_own_due_item():
    s = _sum([_rt(1, "OFFICE", "Information is ok. Applicant was present at office and signed in front of me. LOI signed in front of me. "
                               "Loi verified by Name: Dr. M. Chamber-The applicant no longer operates a chamber at the given address.")])
    assert s.due.startswith("Chamber (The applicant no longer operates") and "LOI" in s.done and s.uncertain
    s = _sum([_rt(1, "OFFICE", "Information ok. Applicant was present office and signed front of me. Chamber verification done.")])
    assert s.due == "0"
    s = _sum([_rt(1, "OFFICE", "Information ok. LoI signed infront of me. Chamber verification- No Chamber Name Found. But people know "
                               "this address is Dr. F chamber.")])
    assert s.due == "0"                                                       # no name board, but the chamber is known: not a problem


def test_a_remark_with_nothing_good_in_it_is_never_passed_as_done():
    from report_builder.summary import TripView, analyze
    t = _rt(1, "GUARANTOR_OFFICE", "The guarantor is currently away for training and is expected to return to the given address after one month.")
    s = analyze([TripView(t, "GUARANTOR", "PG")], True, "BS")
    assert s.due.startswith("PG Office (") and s.uncertain
    s = _sum([_rt(1, "HOUSE", "Information not ok. Mobile no is ok. Information confirm by applicant wife.")])
    assert s.due == "App House (Information not ok)"
    s = _sum([_rt(1, "OFFICE", "Information ok. Applicant said the LOI is ibase generated. No sign required.")])
    assert s.due == "LOI (No sign required (system generated))"


def test_a_canceled_trip_counts_only_for_a_problem_the_verifier_wrote():
    assert _sum([_rt(1, "OFFICE", "Information not ok.Given address is applicants head office address. He does not sit in this office.",
                     status=6)]).due.startswith("App Office (")
    assert _sum([_rt(1, "BANK", "Bank statement verified. Hard copy provided.", status=6)]).due == "0"
    assert _sum([_rt(1, "HOUSE", "", status=6)]).due == "0"
