"""v3.2.2: Done/Due follow the LAST statement - a later "LOI signed ..." settles an earlier "signatory not available";
an unfinished trip shows only its newest appointment's reason."""
import sys
from datetime import datetime as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_builder.summary import TripView, analyze  # noqa: E402


def _trip(tid, code, remarks="", comment="", status=5, appts=None):
    return {"id": tid, "type_code": code, "status_code": status, "remarks": remarks, "comment": comment,
            "created_at": D(2026, 11, 2, 10, 0), "appointments": appts or []}


def _sum(trips, submitted=True):
    views = [TripView(t, "APPLICANT", "App") for t in trips]
    return analyze(views, submitted, "BS")


def _loi_doc(remarks):
    return _trip(9, "DOCUMENT", remarks, "LOI verification")


def test_loi_completed_by_another_person_after_the_staff_was_not_available_is_done():
    # the case of file ...853366: HR/Accounts/Admin not available, then the LOI was finished through a senior person
    s = _sum([_loi_doc("As no one from HR, Accounts, or Admin was available, the LOI was completed through the AGM. "
                       "LOI signed by Name: A Person, Designation: AGM.")])
    assert s.due == "0"
    assert "LOI" in s.done and "(" not in s.done


def test_signatory_not_available_first_and_signed_infront_of_me_later_is_done():
    s = _sum([_loi_doc("Information ok. Signatory not available at first. LOI signed infront of me.")])
    assert s.due == "0" and s.done == "LOI"


def test_previous_signatory_not_available_new_signatory_signed_is_done():
    s = _sum([_loi_doc("Information ok. Verified by receptionist. Loi signed Infront of me. Previous signatory not available. "
                       "New signatory name is. Name : A Person. Designation : Sr Executive.")])
    assert s.due == "0" and s.done == "LOI"


def test_a_problem_written_after_the_signed_statement_still_counts():
    s = _sum([_loi_doc("Information ok. LOI signed infront of me. Second signatory not available.")])
    assert "LOI" in s.due and "Signatory not available" in s.due


def test_will_be_verified_from_head_office_is_not_done():
    s = _sum([_trip(1, "OFFICE", "Information ok. Address ok. LOI will be verified from head office.")])
    assert "LOI" in s.due and "Will be signed from head office" in s.due


def test_will_be_signed_from_head_office_is_not_reported_as_signed_from_head_office():
    s = _sum([_trip(1, "OFFICE", "Information ok. Address ok. LOI will be signed From head office")])
    assert "Signed from head office" not in s.done + s.due
    assert "Will be signed from head office" in s.due


def test_loi_not_verified_stays_due_when_nothing_later_settles_it():
    s = _sum([_loi_doc("LOI not verified. Signatory is not available today.")])
    assert "LOI" in s.due


def _appt(aid, created, when, reason):
    return {"id": aid, "created_at": created, "time": when, "active": True, "reason": reason}


def test_an_unfinished_trip_shows_only_the_newest_appointment_reason():
    t = _trip(1, "HOUSE", "", status=4, appts=[
        _appt(1, D(2026, 11, 3, 14, 47), D(2026, 11, 4, 13, 30), "Phone switch off, applicant not available"),
        _appt(2, D(2026, 11, 5, 11, 40), D(2026, 11, 11, 13, 30), "Applicant is busy, asked me to come later"),
    ])
    s = _sum([t], submitted=False)
    assert "Appointment 11-11-2026" in s.due
    assert "Phone switch off" not in s.due and "Not available" not in s.due


def test_an_unfinished_trip_with_a_single_appointment_keeps_its_reason():
    t = _trip(1, "HOUSE", "", status=4, appts=[
        _appt(1, D(2026, 11, 3, 14, 47), D(2026, 11, 4, 13, 30), "Applicant disagree to verify")])
    s = _sum([t], submitted=False)
    assert "Appointment 04-11-2026" in s.due and "Disagree to verify" in s.due
