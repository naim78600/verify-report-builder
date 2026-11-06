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
