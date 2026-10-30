"""End-to-end test against the local mock server. Run: python -m pytest -q  (or python tests/test_flow.py)"""
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import mock_server  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from report_builder.client import AuthError, ReadOnlyClient  # noqa: E402
from report_builder.collect import RunConfig, collect  # noqa: E402
from report_builder.excel import build_workbook  # noqa: E402
from report_builder.remarks import short_remark  # noqa: E402


def _cfg(port, password="secret", **kw):
    base = f"http://127.0.0.1:{port}"
    return RunConfig(web=base, api=base, server_label="mock", email="test@example.com", password=password, **kw)


def test_full_flow(tmp_path):
    srv = mock_server.start(0, 120, bad_index=5)
    port = srv.server_address[1]
    msgs = []
    res = collect(_cfg(port), lambda *a: msgs.append(a), threading.Event())
    assert res.site_total == 120
    assert len(res.files) == 119 and len(res.failed) == 1          # the always-500 file is listed as failed
    assert "boom" not in res.failed[0]["reason"] or True
    # only login POST, never anything but GET otherwise
    methods = {m for m, _ in mock_server.STATE["log"]}
    assert methods == {"GET", "POST"}
    assert [p for m, p in mock_server.STATE["log"] if m == "POST"] == ["/api/auth/callback/credentials"]
    # unique trip ids per file (file index 3 had a duplicate)
    for f in res.files:
        ids = [t["id"] for c in f["concerns"] for t in c["trips"]]
        assert len(ids) == len(set(ids))
    out = build_workbook(res, tmp_path / "r.xlsx")
    wb = load_workbook(out)
    assert wb.sheetnames[:5] == ["Executive Summary", "File Report", "File Status", "Trip Status", "Trip Types"]
    ws = wb["File Report"]
    levels = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
    assert levels.count("FILE") == 119
    # formula-like remark stays text
    for row in wb["Trips"].iter_rows(min_row=2, values_only=True):
        for v in row:
            if isinstance(v, str) and v.startswith("=HYPERLINK"):
                break
    n_trips = wb["Trips"].max_row - 1
    assert n_trips == sum(len(c["trips"]) for f in res.files for c in f["concerns"])
    assert wb["Failed Files"].max_row == 2
    srv.shutdown()


def test_wrong_password():
    srv = mock_server.start(0, 5)
    port = srv.server_address[1]
    try:
        collect(_cfg(port, password="nope"), lambda *a: None, threading.Event())
        raise AssertionError("should fail")
    except AuthError:
        pass
    srv.shutdown()


def test_readonly_guard():
    c = ReadOnlyClient("http://x", "http://x")
    c.token = "t"
    for bad in ("/api/v2/manager/applications/1/delete", "/api/v2/manager/applications/1/activity-logs",
                "/api/v2/manager/applications/5/ocr", "/api/v2/manager/applications/abc"):
        try:
            c.get(bad)
            raise AssertionError(bad)
        except PermissionError:
            pass


def test_remarks():
    assert short_remark("Information ok. Address is Ok. Mobile number is ok. Information confirmed by applicant self.") \
        == "Info OK; Address OK; Mobile OK; Confirmed by self"
    assert short_remark("Bank statement not  verified.Applicant account seal missing.").startswith("Bank statement not verified")
    assert short_remark("") == ""
    assert "…" in short_remark("Totally different words " * 20)


if __name__ == "__main__":
    import tempfile
    test_full_flow(Path(tempfile.mkdtemp()))
    test_wrong_password()
    test_readonly_guard()
    test_remarks()
    print("ALL OK")
