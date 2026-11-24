"""V18: verifier directory - verifiers only, WhatsApp check, Excel / CSV import, photos, helper endpoints."""
import base64
import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from report_builder import client as C                       # noqa: E402
from report_builder import reminders as R                    # noqa: E402
from report_builder import verifier_dir as VD                # noqa: E402

PHONES = {5532: {"name": "Abdul Khalek", "phone": "8801712345678"}, 5521: {"name": "Zihadul Islam", "phone": "8801811111111"},
          900: {"name": "No Phone", "phone": ""}, 901: {"name": "Md Rahim", "phone": "8801911000001"},
          902: {"name": "Md Rahim", "phone": "8801911000002"}}


@pytest.fixture(autouse=True)
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setattr(VD, "PHOTO_DIR", tmp_path / "photos")
    monkeypatch.setattr(R, "STATE_FILE", tmp_path / "reminders.json")
    yield tmp_path


def test_verifiers_only_and_active():
    class Fake:
        def get(self, _p):
            return {"taskers": [{"id": 1, "name": "A", "phone": "01711000001", "user_role": 4, "status": 1, "admin_access_token": "x"},
                                {"id": 2, "name": "Manager", "phone": "01711000002", "user_role": 2, "status": 1},
                                {"id": 3, "name": "Old", "phone": "01711000003", "user_role": 4, "status": 0}]}
    out = C.verifier_phones(Fake())
    assert list(out) == [1] and out[1] == {"name": "A", "phone": "8801711000001"}


def test_status_and_check_list():
    st = {}
    assert VD.wa_status("", st) == "none" and VD.wa_status("12345", st) == "bad"
    assert VD.wa_status("8801712345678", st) == "unchecked"
    items = VD.to_check(PHONES, {}, st, today=date(2026, 11, 24))
    assert [i["vid"] for i in items] == [901, 902, 5521, 5532]
    VD.record_check(st, "8801712345678", True, date(2026, 11, 24))
    VD.record_check(st, "8801811111111", False, date(2026, 11, 24))
    assert VD.wa_status("8801712345678", st) == "ok" and VD.wa_status("8801811111111", st) == "no"
    left = [i["vid"] for i in VD.to_check(PHONES, {}, st, today=date(2026, 11, 25))]
    assert 5532 not in left and 5521 not in left                     # checked ok (fresh) / not on WhatsApp: not again
    assert 5532 in [i["vid"] for i in VD.to_check(PHONES, {}, st, today=date(2026, 12, 30))]   # re-checked after 30 days
    VD.record_check(st, "8801811111111", True)
    assert VD.wa_status("8801811111111", st) == "ok" and "8801811111111" not in st["no_whatsapp"]


def test_import_csv_and_excel(tmp_path):
    csvp = tmp_path / "n.csv"
    csvp.write_text("Verifier ID,Name,WhatsApp\n5532,,01722-222222\n,Zihadul Islam,+8801899999999\n,Nobody,01700000000\n,Md Rahim,01700000001\n900,No Phone,0171\n",
                    encoding="utf-8")
    items = VD.parse_import(VD.read_rows(csvp), PHONES)
    assert [(i["vid"], i["ok"]) for i in items] == [(5532, True), (5521, True), (None, False), (None, False), (900, False)]
    assert items[2]["why"] == "not a verifier" and "two verifiers" in items[3]["why"] and items[4]["why"] == "number not valid"
    ov = {}
    assert VD.apply_import(items, ov) == 2 and ov == {"5532": "8801722222222", "5521": "8801899999999"}
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["Name", "WhatsApp number"])
    wb.active.append(["abdul  khalek", 1733333333])
    xp = tmp_path / "n.xlsx"
    wb.save(xp)
    items = VD.parse_import(VD.read_rows(xp), PHONES)
    assert items[0]["vid"] == 5532 and items[0]["phone"] == "8801733333333" and items[0]["ok"]


def test_photos_any_format(tmp_path):
    from PIL import Image
    for name, fmt in (("Zihadul Islam.png", "PNG"), ("5532.webp", "WEBP"), ("unknown.gif", "GIF"), ("Abdul Khalek.tif", "TIFF")):
        Image.new("RGB", (640, 400), (20, 120, 200)).save(tmp_path / name, fmt)
    found, missed = VD.match_photo_files([tmp_path / n for n in ("Zihadul Islam.png", "5532.webp", "unknown.gif")], PHONES)
    assert sorted(v for v, _ in found) == [5521, 5532] and [p.name for p in missed] == ["unknown.gif"]
    for vid, p in found:
        out = VD.save_photo(vid, p)
        assert Image.open(out).size == (VD.PHOTO_SIZE, VD.PHOTO_SIZE)
    VD.save_photo(5532, tmp_path / "Abdul Khalek.tif")
    assert VD.photo_path(5532) and VD.photo_path(900) is None
    with pytest.raises(Exception):
        VD.save_photo(900, b"not a picture")


def test_export_and_directory(tmp_path):
    st = {}
    VD.record_check(st, "8801712345678", True, date(2026, 11, 24))
    rows = (VD.export_csv(tmp_path / "x.csv", PHONES, {"901": "8801555666777"}, st)).read_text(encoding="utf-8-sig").splitlines()
    assert rows[0] == "Verifier ID,Name,WhatsApp,Status,Photo" and any(r.startswith("5532,Abdul Khalek,8801712345678,WhatsApp connected") for r in rows)
    d = {x["id"]: x for x in VD.directory(PHONES, {"901": "8801555666777"}, st)}
    assert d[5532]["wa"] == "ok" and d[5532]["num"] == "01712345678" and d[901]["num"] == "01555666777" and not d[901]["fromDashboard"]
    assert d[900]["wa"] == "none"


def _call(port, path, body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=None if body is None else json.dumps(body).encode(),
                                 headers={"Origin": "chrome-extension://abc", "Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read() if r.headers.get("Content-Type", "").startswith("image/") else json.loads(r.read())


def test_helper_endpoints(tmp_path):
    from report_builder.helper_server import HelperServer
    saved = {}
    events = []
    srv = HelperServer(lambda k, e: events.append(k), port=47391)
    srv.dir_source = lambda: (PHONES, dict(saved))
    srv.set_number = lambda vid, ph: saved.__setitem__(str(vid), ph)
    assert srv.start()
    try:
        H = {"X-VRB-Dashboard": "1"}
        _call(47391, "/directory", None, H)
        assert not srv.extension_connected                                  # the dashboard extension is not the WhatsApp helper
        assert _call(47391, "/wa_check")["items"] == []                     # nothing until a check is asked
        tok = _call(47391, "/directory_check", {}, H)["token"]
        r = _call(47391, "/wa_check")
        assert r["start"] == tok and len(r["items"]) == 4 and r["auto"] is False
        assert _call(47391, "/wa_check_claim", {"token": tok})["ok"] and not _call(47391, "/wa_check_claim", {"token": tok})["ok"]
        assert _call(47391, "/wa_check", {"phone": "8801712345678", "ok": True})["ok"]
        assert _call(47391, "/wa_check", {"phone": "8801811111111", "ok": False})["ok"]
        assert not _call(47391, "/wa_check", {"phone": "8801000000000", "ok": True})["ok"]    # not a verifier's number
        d = {x["id"]: x for x in _call(47391, "/directory", None, H)["items"]}
        assert d[5532]["wa"] == "ok" and d[5521]["wa"] == "no"
        assert _call(47391, "/directory", {"id": 900, "num": "01999888777"}, H)["ok"] and saved["900"] == "8801999888777"
        assert not _call(47391, "/directory", {"id": 12345, "num": "01999888777"}, H)["ok"]      # nobody else can be added
        assert not _call(47391, "/directory", {"id": 901, "num": "123"}, H)["ok"]
        assert _call(47391, "/directory", {"id": 901, "noWa": True}, H)["ok"]
        assert "8801911000001" in R.load_state()["no_whatsapp"]
        from PIL import Image
        b = io.BytesIO()
        Image.new("RGB", (50, 80), (200, 30, 30)).save(b, "PNG")
        assert _call(47391, "/photo", {"id": 5532, "b64": "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()}, H)["ok"]
        assert _call(47391, "/photo/5532", None, H)[:2] == b"\xff\xd8"
        assert not _call(47391, "/photo", {"id": 5532, "b64": "bm90IGEgcGljdHVyZQ=="}, H)["ok"]
        with pytest.raises(urllib.error.HTTPError):
            _call(47391, "/directory", None, {"Origin": "https://evil.example"})
        assert "wa_check" in events and "directory" in events
    finally:
        srv.stop()
