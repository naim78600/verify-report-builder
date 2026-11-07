"""v3.3.0: Done/Due follow the LATEST activity - sentence attribution (a refusal written about the LOI is the LOI's problem),
typo-tolerant "LOI signed" statements, and a later LOI trip of the same submission settling / re-opening an earlier statement."""
import sys
from datetime import datetime as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from report_builder.billing import fold_complete  # noqa: E402
from test_v321 import SUB, _row, _trip  # noqa: E402
from test_v322 import _loi_doc, _sum  # noqa: E402


def test_office_remark_with_the_applicant_refusing_the_loi_is_a_loi_problem_not_an_office_one():
    s = _sum([_trip(1, "OFFICE", "Applicant present at office. Signatory disagree to verify the LOI.")])
    assert "LOI (Disagree to verify)" in s.due
    assert "Office (Disagree to verify)" not in s.due


def test_a_house_refusal_stays_a_house_problem():
    s = _sum([_trip(1, "HOUSE", "Applicant disagree to verify.", status=5)])
    assert "House (Disagree to verify)" in s.due and "LOI" not in s.due


def test_loi_signed_with_typos_is_done():
    s = _sum([_loi_doc("Information ok. Loi sing by new signatory. Name: A Person.")])
    assert s.due == "0" and s.done == "LOI"


def test_loi_verified_not_front_of_me_is_done():
    s = _sum([_loi_doc("Information ok. Loi Verified Not front of Me. No visible holding number.")])
    assert s.due == "0" and s.done == "LOI"


def test_double_dot_separates_sentences_signatory_was_not_present_then_new_signatory_signed():
    s = _sum([_loi_doc("LOI signatory was not present..Loi sing by new signatory (name: A Person)")])
    assert s.due == "0" and s.done == "LOI"


def test_can_verify_from_a_named_branch_is_a_note():
    s = _sum([_loi_doc("Signatory said LOI can be verified from the Sylhet branch.")])
    assert "LOI (Can be verified from branch)" in s.due


def _pack(created=D(2026, 10, 27, 10, 0)):
    return _row("Package", [(_trip(1, "OFFICE", "Information ok. Applicant signed in front of me. LOI signed infront of me. "
                                                "LOI verified by, Name: A B, Mobile: 01712345678", created=created), "App")], SUB)


def test_a_later_loi_trip_of_the_same_submission_that_is_refused_reopens_the_loi():
    pk = _pack()
    assert pk.summary.due == "0"
    ex = _row("Extra", [(_trip(2, "DOCUMENT", "Denied to LOI verification from head office.", "LOI sign from this address",
                                created=D(2026, 10, 28, 10, 0)), "App")], SUB)
    out = fold_complete([pk, ex])
    assert len(out) == 1
    assert out[0].summary.due.startswith("LOI") and "LOI" in out[0].summary.done


def test_a_later_clean_loi_trip_settles_an_earlier_loi_problem_of_the_same_submission():
    pk = _pack()
    e1 = _row("Extra", [(_trip(2, "DOCUMENT", "LOI verification needs to be completed via email. Gmail Address is: x@y.com",
                                "LOI sign from this address", created=D(2026, 10, 28, 10, 0)), "App")], SUB)
    e2 = _row("Extra", [(_trip(3, "DOCUMENT", "Information ok. LOI verified by, Name: A B, Mobile: 01712345678",
                                "LOI will be verify from Branch", created=D(2026, 10, 29, 10, 0)), "App")], SUB)
    out = fold_complete([pk, e1, e2])
    assert len(out) == 1 and out[0].summary.due == "0" and "LOI" in out[0].summary.done


def test_a_loi_problem_of_an_earlier_day_is_history_when_the_next_submission_settles_it():
    # separate submission days = separate rows: each row describes its own day (as-of the submission)
    day1 = _row("Extra", [(_trip(2, "DOCUMENT", "LOI verification needs to be completed via email.",
                                  created=D(2026, 10, 28, 10, 0)), "App")], D(2026, 10, 28, 15, 0))
    day2 = _row("Extra", [(_trip(3, "DOCUMENT", "Information ok. LOI verified by, Name: A B.",
                                  created=D(2026, 11, 2, 10, 0)), "App")], D(2026, 11, 2, 15, 0))
    out = fold_complete([day1, day2])
    assert len(out) == 2
    assert "LOI" in day1.summary.due and day2.summary.due == "0"
