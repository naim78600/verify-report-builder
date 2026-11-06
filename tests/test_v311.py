"""v3.1.1: a PDF row taller than a page must not stop the run (reportlab LayoutError on a Mac, 05-11-2026 Phase 1)."""
import sys
import threading
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import mock_server  # noqa: E402
import pytest  # noqa: E402

from report_builder import reports  # noqa: E402
from report_builder.collect_prime import PrimeConfig, collect_prime  # noqa: E402
from report_builder.prime_pdf import build_prime_pdf  # noqa: E402


@pytest.fixture()
def d():
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    cfg = PrimeConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret", days=30,
                      mode="tracker", report_date=date(2026, 11, 2), slot="7pm", incomplete_scope="all_pending")
    data = collect_prime(cfg, lambda *a: None, threading.Event())
    yield data
    srv.shutdown()


def _monster(d):
    r = d.incomplete[0]
    r.history_lines = [f"{i:02d}/10/2026 Re-CPV House Verification: customer was not at home, come after Friday prayer"
                       for i in range(80)]
    r.concern_lines = [f"{i}. Guarantor: A VERY LONG NAME NUMBER {i} OF THE GUARANTOR, House, Office" for i in range(1, 120)]
    return r


def test_pdf_with_row_taller_than_a_page(d, tmp_path):
    _monster(d)
    out = build_prime_pdf(d, tmp_path / "t.pdf")                  # used to raise reportlab LayoutError
    assert out.exists() and out.stat().st_size > 5000


def test_pdf_failure_keeps_the_excel(d, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("layout exploded")
    monkeypatch.setattr(reports, "build_prime_pdf", boom)
    paths = reports.write_prime_outputs(d, tmp_path, excel=True, pdf=True)
    assert [p.suffix for p in paths] == [".xlsx"] and paths[0].exists()
    assert d.notes[0].startswith("PDF তৈরি হয়নি")


def test_pdf_long_cells_become_short_summaries(d, tmp_path):
    """Many trips / appointments: the PDF shows the newest few + a count, never a tiny font."""
    from datetime import datetime, timedelta
    from report_builder.prime_pdf import appointment_short, last_update_short
    r = d.incomplete[0]
    base = datetime(2026, 11, 1, 10)
    r.last_trips = [(700000 + i, "House", base + timedelta(hours=i) if i % 4 else None, "Finished", "Mgr") for i in range(12)]
    r.appointments = [{"trip_id": 700000 + i, "trip_type": "House", "time": base + timedelta(days=i), "type": "Visit",
                       "created_at": base, "reason": "not at home", "active": i == 11} for i in range(9)]
    lu = "\n".join("".join(t for t, _s in ln) for ln in last_update_short(r))
    assert lu.count("· House") == 3 and "older trip updates" in lu and "no activity" in lu
    ap = "\n".join("".join(t for t, _s in ln) for ln in appointment_short(r))
    assert ap.count("Appointment:") == 2 and "+7 more appointments" in ap
    assert len(r.appointments) == 9                                          # the row itself is not changed
    assert build_prime_pdf(d, tmp_path / "s.pdf").exists()


@pytest.mark.skipif(__import__("shutil").which("pdftotext") is None, reason="poppler (pdftotext) not installed")
def test_pdf_incomplete_table_shows_the_pending_reason(d, tmp_path):
    """The banker reads the PDF: every Incomplete row must say WHY it is pending (Hold comment, Finished - not yet submitted ...)."""
    import subprocess
    d.incomplete[0].reason, d.incomplete[0].reason_kind = "Hold: customer abroad until 12 Nov | Appointment 12/11/2026 11:00 AM", "hold"
    d.incomplete[1].reason, d.incomplete[1].reason_kind = "Finished - not yet submitted", "finished"
    out = build_prime_pdf(d, tmp_path / "r.pdf")
    txt = subprocess.run(["pdftotext", "-raw", str(out), "-"], capture_output=True, text=True).stdout
    txt = " ".join(txt.split())
    assert "Pending Reason" in txt
    assert "customer abroad until 12 Nov" in txt and "Finished - not yet submitted" in txt
