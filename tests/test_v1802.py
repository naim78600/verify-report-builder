"""v18.0.2 / v18.0.3: no Bangla in the tracker (English only, never "??????"); Re-CPV / Extra rows show only their own appointments."""
import re
import sys
import threading
from datetime import date, datetime as D
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import mock_server  # noqa: E402
import pytest  # noqa: E402
from pypdf import PdfReader  # noqa: E402

from report_builder import prime_pdf  # noqa: E402
from report_builder.collect_prime import PrimeConfig, collect_prime  # noqa: E402
from report_builder.report_text import BANGLA_NOTE, appointment_lines, english_only, plain, shown_appointments  # noqa: E402



@pytest.fixture()
def d():
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                      mode="tracker", report_date=date(2026, 11, 2), slot="7pm", incomplete_scope="all_pending")
    data = collect_prime(cfg, lambda *a: None, threading.Event())
    yield data
    srv.shutdown()


ADDR = "Hold: Loi sign will be head office. Address: ব্যাংক এশিয়া টাওয়ার (Bank Asia Tower), ৩২ ও ৩৪ কাজী নজরুল ইসলাম এভিনিউ"


def test_english_only_keeps_the_english_and_drops_bangla():
    """v18.0.3 (Naim): banks do not take Bangla in the report - English only, never "??????"."""
    assert english_only(ADDR) == "Hold: Loi sign will be head office. Address: Bank Asia Tower"
    assert english_only("Address: মিরপুর ১০, ঢাকা") == "Address: " + BANGLA_NOTE
    assert english_only("House 12, Road 5 (পুরাতন ঠিকানা), Dhanmondi") == "House 12, Road 5, Dhanmondi"
    assert english_only("ঠিকানা পাওয়া যায়নি") == BANGLA_NOTE
    assert english_only("Line one\nAll English") == "Line one\nAll English" and english_only(None) is None and english_only(5) == 5


def test_tracker_pdf_and_excel_have_no_bangla_and_no_question_marks(d, tmp_path):
    import openpyxl
    from report_builder.prime_excel import build_prime_excel
    d.incomplete[0].reason, d.incomplete[0].reason_kind = ADDR, "hold"
    pdf = prime_pdf.build_prime_pdf(d, tmp_path / "t.pdf")
    txt = " ".join(" ".join((p.extract_text() or "").split()) for p in PdfReader(str(pdf)).pages)
    assert "Bank Asia Tower" in txt and "??" not in txt and not re.search("[\u0980-\u09FF]", txt)
    wb = openpyxl.load_workbook(build_prime_excel(d, tmp_path / "t.xlsx"))
    cells = " ".join(str(c.value) for ws in wb for row in ws.iter_rows() for c in row if c.value is not None)
    assert "Bank Asia Tower" in cells and not re.search("[\u0980-\u09FF]", cells)


def _appt(tid, day):
    return {"trip_id": tid, "trip_type": "Office", "time": D(2026, 11, day, 11), "type": "Visit", "created_at": D(2026, 11, day - 1),
            "reason": "", "active": True}


def test_recpv_row_shows_only_its_own_appointments():
    old, own = _appt(504505, 11), _appt(514629, 23)
    r = SimpleNamespace(kind="ReCpv", appointments=[own], file_appointments=[old, own])
    assert shown_appointments(r) == [own]
    r = SimpleNamespace(kind="ReCpv", appointments=[], file_appointments=[old])
    assert plain(appointment_lines(r)) == "NO"                               # the old package trip's 11/11 is not this row's


def test_package_row_still_shows_every_trip_of_the_file():
    a, b = _appt(1, 11), _appt(2, 16)
    r = SimpleNamespace(kind="Package", appointments=[a], file_appointments=[a, b])
    assert shown_appointments(r) == [a, b]                                   # v10.0.6 rule unchanged for the package


def test_recpv_row_lists_appointments_of_later_document_trip_too():
    """v18.0.4 (live CC-20261104095224032): the Re-CPV row lost the appointments of the LOI document trip (another
    Re-CPV / Extra row of the file) - they come back; the package's own trips stay out."""
    pkg, doc, own = _appt(500745, 5), _appt(510318, 18), _appt(505455, 12)
    package = SimpleNamespace(kind="Package", appointments=[pkg], receive_dt=D(2026, 11, 4))
    extra = SimpleNamespace(kind="Extra", appointments=[doc], receive_dt=D(2026, 11, 16))
    r = SimpleNamespace(kind="ReCpv", appointments=[own], folded_rows=[], file_rows=[package, extra], file_appointments=[pkg, own, doc],
                        receive_dt=D(2026, 11, 11))
    assert shown_appointments(r) == [own, doc]


def test_recpv_row_leaves_out_older_recpv_and_extra_rows():
    """v18.0.5 (live PL-20261104113123122): the 22/11 Re-CPV row showed the 11/11 appointment of the 10/11 Extra LOI trip;
    (CC-20260910075957434): the 12/11 Re-CPV row showed the 07/10 appointment of the 04/10 Re-CPV.  Older rows stay out."""
    old_extra = SimpleNamespace(kind="Extra", appointments=[_appt(504505, 11)], receive_dt=D(2026, 11, 10, 13, 57))
    r = SimpleNamespace(kind="ReCpv", appointments=[], folded_rows=[], file_rows=[old_extra], receive_dt=D(2026, 11, 22, 16, 14))
    assert shown_appointments(r) == [] and plain(appointment_lines(r)) == "NO"
    old_recpv = SimpleNamespace(kind="ReCpv", appointments=[_appt(480051, 7)], receive_dt=D(2026, 10, 4))
    new_trip = _appt(506489, 16)
    r = SimpleNamespace(kind="ReCpv", appointments=[new_trip], folded_rows=[old_recpv], file_rows=[old_recpv], receive_dt=D(2026, 11, 12))
    assert shown_appointments(r) == [new_trip]


def test_no_stray_comma_where_bangla_was_removed():
    assert english_only(ADDR + " | Appointment 25/11/2026 03:00 AM") == \
        "Hold: Loi sign will be head office. Address: Bank Asia Tower | Appointment 25/11/2026 03:00 AM"
