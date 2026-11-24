"""v18.0.2: Bangla text in the tracker PDF (was "??????"); Re-CPV / Extra rows show only their own appointments."""
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
from report_builder.report_text import appointment_lines, plain, shown_appointments  # noqa: E402

BANGLA = "ব্যাংক এশিয়া টাওয়ার"


@pytest.fixture()
def d():
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                      mode="tracker", report_date=date(2026, 11, 2), slot="7pm", incomplete_scope="all_pending")
    data = collect_prime(cfg, lambda *a: None, threading.Event())
    yield data
    srv.shutdown()


def test_bangla_runs_go_to_the_bangla_font():
    prime_pdf._fonts()
    m = prime_pdf._mark(f"Hold: Loi sign will be head office. Address: {BANGLA} (Bank Asia Tower) <b>")
    assert f'<font name="{prime_pdf.BN}">{BANGLA}</font>' in m
    assert "(Bank Asia Tower)" in m and "&lt;b&gt;" in m and "?" not in m


def test_tracker_pdf_embeds_the_bangla_font_and_no_question_marks(d, tmp_path):
    d.incomplete[0].reason, d.incomplete[0].reason_kind = f"Hold: Loi sign will be head office. Address: {BANGLA}", "hold"
    out = prime_pdf.build_prime_pdf(d, tmp_path / "bn.pdf")
    fonts = set()
    for page in PdfReader(str(out)).pages:
        for f in (page.get("/Resources", {}).get("/Font", {}) or {}).values():
            fonts.add(str(f.get_object().get("/BaseFont")))
    assert any("FreeSans" in f for f in fonts), fonts       # the embedded Bangla font
    assert "??????" not in "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)


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
