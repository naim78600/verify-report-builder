"""v16: File History trip-wise page ("Design A") - every value comes from the existing rules (bill rows, Report Summary)."""
import sys
import threading
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402
import mock_server  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from report_builder.file_history import HistoryConfig, collect_history, make_entry  # noqa: E402
from report_builder.history_trips import blocks, extra_text, sla_text, totals  # noqa: E402
from report_builder.history_tripwise import HEADS, build_excel, build_pdf  # noqa: E402


@pytest.fixture(scope="module")
def bl(tmp_path_factory):
    srv = mock_server.start_scenario(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    tmp = tmp_path_factory.mktemp("v16")
    ids = ["000003", "2", "9999", "PL-20261026000001"]
    cfg = HistoryConfig(web=base, api=base, server_label="mock", email="test@example.com", password="secret",
                        ids=[make_entry(i) for i in ids], index_path=tmp / "idx.json", today=date(2026, 11, 5))
    h = collect_history(cfg, lambda *a: None, threading.Event())
    srv.shutdown()
    return h, blocks(h), tmp


def _by(bl, no):
    return next(b for b in bl if b.get("file_no") == no)


def test_input_order_missing_and_short_number(bl):
    h, b, _ = bl
    assert [x["searched"] for x in b][:3] == ["000003", "2", "9999"]
    nf = next(x for x in b if x["searched"] == "9999")
    assert nf["missing"] and nf["status"] == "File not found" and nf["trips"] == []
    assert _by(b, "CC-20261101000002")["short_no"] == "2"            # the number the bank gave stays on top


def test_trip_results_follow_report_summary(bl):
    h, b, _ = bl
    f = _by(b, "CC-20261101000002")
    assert f["status"] == "Submitted"
    res = {t["type"]: (t["result"], t["note"]) for t in f["trips"]}
    assert res["App House"] == ("Done", "")
    assert res["App Office"] == ("Done", "Negative")                 # LOI problem read from the office remark -> repeated in Due
    assert res["BS"] == ("–", "Canceled")                            # canceled, left out of the summary
    assert f["summary_due"].startswith("LOI (")
    p = _by(b, "PL-20261020000003")
    office = next(t for t in p["trips"] if t["type"] == "App Office")
    assert office["result"] == "Due" and office["note"].startswith("Appointment")      # reason = the open appointment (+ note)


def test_sla_and_extra_from_bill_rows(bl):
    h, b, _ = bl
    for x in b:
        if x.get("missing"):
            continue
        fd = next(fd for fd in h.files.values() if fd.file["file_no"] == x["file_no"])
        pkg = next(r for r in fd.rows if r.kind == "Package")
        assert (x["tat"], x["sla_days"], x["area"]) == (pkg.tat, pkg.sla_days, pkg.area)
        line, key = sla_text(x)
        assert key == ("breach" if pkg.sla_breach else "ok") if pkg.tat is not None else key == "none"
        assert extra_text(x).startswith(f"Extra trip: {len(x['extra_trips'])}")
    t = totals(b)
    assert t["not_found"] == 1 and t["files"] == len([x for x in b if not x.get("missing")])


def test_excel_and_pdf(bl):
    h, b, tmp = bl
    x = build_excel(b, tmp / "t.xlsx", "Prime Bank PLC")
    ws = load_workbook(x)["File History"]
    assert [ws.cell(7, c).value for c in range(1, 11)] == HEADS
    assert ws.page_setup.orientation == "landscape" and int(ws.page_setup.paperSize) == 9
    assert ws["A1"].value.startswith("Prime Bank PLC") and ws["A1"].font.name == "Calibri"
    p = build_pdf(b, tmp / "t.pdf", "Prime Bank PLC")
    data = p.read_bytes()
    assert data[:5] == b"%PDF-" and b"FiraSans" in data
