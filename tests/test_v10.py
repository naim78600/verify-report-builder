"""v10: BS tracker (banks, outcome from remarks, monthly Excel, signed list, office receive), reminders (queue, priority,
appointments, replies, catch-up), the local helper server, A4 page setup."""
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from report_builder import bs_rules as B, bs_tracker as BT, reminders as R  # noqa: E402


# ------------------------------------------------------------------------------------------------ banks
@pytest.mark.parametrize("written,remarks,bank,kind", [
    ("PRIME BANK PLC", "", "Prime Bank PLC", "Online"),
    ("NCC Bank", "", "NCC Bank PLC", "Offline"),
    ("Dutch Bangla Bank PLC", "", "Dutch-Bangla Bank PLC", "Online"),
    ("DBBL", "", "Dutch-Bangla Bank PLC", "Online"),
    ("Mutual Trust Bank", "", "Mutual Trust Bank PLC", "Online"),
    ("Trust Bank", "", "Trust Bank PLC", "Online"),
    ("Standard Chartered", "", "Standard Chartered Bank", "Online"),
    ("STANDARD BANK PLC", "", "Standard Bank PLC / Standard Islami Bank PLC", "Offline"),
    ("Standard Islami Bank PLC", "", "Standard Bank PLC / Standard Islami Bank PLC", "Offline"),
    ("EXIM Bank", "", "EXIM Bank (Export Import Bank of Bangladesh PLC)", "Offline"),
    ("Sammilito Islami Bank", "", "Sammilito Islami Bank PLC", "Offline"),
    ("", "Bank statement verified hard copy provided from Jamuna Bank", "Jamuna Bank PLC", "Offline"),
    ("PBL", "Pubali branch", "Pubali Bank PLC", "Offline"),
    ("NRBC Bank", "", "NRBC Bank PLC", "Offline"),
    ("NRB Bank", "", "NRB Bank PLC", "Online"),
    ("UTTAR BANK PLC", "", "Uttara Bank PLC", "Offline"),               # spellings seen on the dashboard (Oct-Nov 2026)
    ("SOUTHEAST BANK PLC(TAKE APPLICANT HELP TO WITHDRAW BS)", "", "Southeast Bank PLC", "Online"),
    ("IBBPLC", "", "Islami Bank Bangladesh PLC", "Offline"),
    ("SBAC BANK PLC", "", "SBAC BANK PLC", "Offline"),                  # not in the list -> offline, name kept
])
def test_bank_match(written, remarks, bank, kind):
    got = B.match_bank(written, remarks)
    assert got[:2] == (bank, kind), got


def test_unclear_short_form_or_no_bank_counts_offline():
    assert B.match_bank("PBL", "")[1] == "Offline" and "unclear" in B.match_bank("PBL", "")[2]
    assert B.match_bank("", "")[1] == "Offline"


@pytest.mark.parametrize("remark,outcome,note", [
    ("Bank statement verified hard copy provided", B.COLLECTED, ""),
    ("Bank statement hard copy provided verified", B.COLLECTED, ""),
    ("Statement scan copy given by the applicant", B.COLLECTED_SOFT, ""),
    ("Bank statement not verified applicant account insufficient balance", B.NOT_VERIFIED, "Insufficient balance"),
    ("The applicant disagree to give bank statement", B.REFUSED, ""),
    ("Verification not possible, branch closed indefinitely", B.NOT_POSSIBLE, ""),
    ("Bank statement verified", B.VERIFIED_ONLY, ""),
    ("something new", B.CHECK, ""),
])
def test_bs_outcome(remark, outcome, note):
    assert B.bs_outcome(remark, 5) == (outcome, note)


def test_no_remark_open_trip_is_pending():
    assert B.bs_outcome("", 2)[0] == B.PENDING and B.bs_outcome("", 5)[0] == B.CHECK


# ------------------------------------------------------------------------------------------------ BS rows / Excel
def _trip(tid, ttype="BANK", status=5, remarks="", place="", created=None, agent=7, appts=None, verifier="Verifier A"):
    return {"id": tid, "type_code": ttype, "type": ttype.title(), "status_code": status, "status": "Finished" if status == 5 else "Started",
            "remarks": remarks, "place_name": place, "created_at": created or datetime(2026, 11, 3, 10), "agent_id": agent,
            "verifier": verifier, "appointments": appts or []}


def _file(fid, fno, trips, status=2, sla=None, name="Applicant One"):
    return {"id": fid, "file_no": fno, "status_code": status, "status": "On Going", "sla": sla,
            "concerns": [{"role": "applicant", "name": name, "trips": trips}]}


@pytest.fixture()
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(BT, "STORE_FILE", tmp_path / "bs_store.json")
    monkeypatch.setattr(BT, "SLIP_DIR", tmp_path / "slips")
    monkeypatch.setattr(R, "STATE_FILE", tmp_path / "reminders.json")
    return tmp_path


def test_two_bs_of_one_file_sit_next_to_each_other_and_month_filter(tmp_store):
    files = [
        _file(1, "PL-20261101000001", [_trip(101, remarks="Bank statement verified hard copy provided", place="NCC Bank",
                                             created=datetime(2026, 11, 1, 9))]),
        _file(2, "CC-20261101000002", [_trip(201, place="BRAC Bank", created=datetime(2026, 11, 2, 9)),
                                       _trip(202, place="Pubali Bank", created=datetime(2026, 11, 5, 9)),
                                       _trip(203, ttype="HOUSE")]),
        _file(3, "PL-20261001000003", [_trip(301, place="NCC Bank", created=datetime(2026, 10, 20))]),
    ]
    rows = BT.bs_rows(files, "Prime Bank PLC", phones={7: {"phone": "8801711000000"}}, month=(2026, 11), store={})
    assert [r.trip_id for r in rows] == [101, 201, 202]
    assert rows[0].collected and rows[0].bs_type == "Offline" and rows[0].phone == "8801711000000"
    assert rows[1].bs_type == "Online" and rows[2].bs_type == "Offline"
    p = BT.write_bs_excel(rows, tmp_store / "bs.xlsx", "Prime Bank PLC · BS Tracker · November 2026")
    ws = load_workbook(p)["BS Tracker"]
    assert [c.value for c in ws[4]][:3] == ["Created Date-Time", "Trip ID", "File No"]
    assert [ws.cell(r, 2).value for r in (5, 6, 7)] == [101, 201, 202]
    assert ws.auto_filter.ref.startswith("A4:") and int(ws.page_setup.paperSize) == 9 and ws.page_setup.orientation == "landscape"


def test_office_receive_courier_signed_list_and_pending(tmp_store):
    files = [_file(1, "PL-20261101000001", [_trip(101, remarks="Bank statement verified hard copy provided")]),
             _file(2, "CC-20261101000002", [_trip(201, remarks="hard copy provided"), _trip(202, status=2)], name="Karim Uddin Ahmed"),
             _file(3, "PL-20261101000003", [_trip(301, remarks="Bank statement not verified")])]
    store = {}
    rows = BT.bs_rows(files, "Prime Bank PLC", store=store)
    assert {r.trip_id for r in BT.pending_bs(rows)} == {101, 201, 202}           # not-collected (301) is not pending
    BT.set_office(store, 101, giver="Verifier A", receiver="Naim", pages="6", file_no="PL-20261101000001", bank="NCC Bank")
    slip = tmp_store / "slip.png"
    from PIL import Image
    Image.new("RGB", (400, 300), "white").save(slip)
    BT.set_courier(store, 201, name="SA Paribahan", no="SA123", status="In transit", slip=slip)
    rows = BT.bs_rows(files, "Prime Bank PLC", store=store)
    assert {r.trip_id for r in BT.pending_bs(rows)} == {202}
    by = {r.trip_id: r for r in rows}
    assert by[101].where == "Office received" and by[201].where == "Courier · In transit"
    # the client's signed list: Trip ID 101 written, and the applicant's full name for 201
    for r in rows:
        if r.trip_id == 201:
            r.bank = "BRAC Bank PLC"
    found = BT.match_signed_list(rows, "SL | Trip 101 | NCC\n2 | KARIM UDDIN AHMED | BRAC | signed")
    assert found == {101: "Trip ID", 201: "Applicant name + bank"}            # 202 (same file, other BS) is not ticked
    assert BT.apply_signed_list(store, rows, found, "signed.xlsx") == 2
    rows = BT.bs_rows(files, "Prime Bank PLC", store=store)
    assert {r.trip_id: r for r in rows}[101].where == "Bank received"
    # file number found by its digits too
    assert BT.match_signed_list(rows, "PL 20261101000003 received")[301] == "File No"
    # Excel with the slip picture, and the A4 received-today sheet
    p = BT.write_bs_excel(rows, tmp_store / "bs.xlsx", "t")
    assert load_workbook(p)["BS Tracker"]._images
    s = BT.write_receive_sheet(store, tmp_store / "today.xlsx")
    ws = load_workbook(s).active
    assert ws["A1"].value.startswith("আজ রিসিভ হয়েছে") and ws["C5"].value == "PL-20261101000001" and ws.page_setup.orientation == "portrait"


def test_receive_template_roundtrip_and_find(tmp_store):
    t = BT.write_receive_template(tmp_store / "form.xlsx")
    wb = load_workbook(t)
    ws = wb.active
    ws.append(["15/11/2026 11:30", "PL-20261101000001", "NCC Bank", "Verifier A", "Naim", 6, ""])
    ws.append([None, "1001", "", "Verifier B", "Naim", "", "seal ok"])
    wb.save(t)
    got = BT.read_receive_upload(t)
    assert [g["key"] for g in got] == ["PL-20261101000001", "1001"] and got[0]["when"] == datetime(2026, 11, 15, 11, 30)
    rows = BT.bs_rows([_file(1, "PL-20261101000001", [_trip(101), _trip(102)])], "Prime Bank PLC", store={})
    assert [r.trip_id for r in BT.find_row(rows, "PL-20261101000001")] == [101, 102]
    assert [r.trip_id for r in BT.find_row(rows, "101")] == [101]
    assert [r.trip_id for r in BT.find_row(rows, "0001")] == [101, 102]


# ------------------------------------------------------------------------------------------------ reminders
NOW = datetime(2026, 11, 16, 13, 5)          # a Monday


def _snap():
    today = NOW.date()
    appt = lambda d: [{"time": datetime.combine(d, datetime.min.time()).replace(hour=15), "active": True}]  # noqa: E731
    return {"Prime Bank PLC": [
        _file(1, "F-SLA", [_trip(11, "HOUSE", status=3, agent=1, verifier="A")], sla=NOW - timedelta(days=1)),
        _file(2, "F-TODAY", [_trip(21, "OFFICE", status=2, agent=2, verifier="B")], sla=NOW + timedelta(hours=3)),
        _file(3, "F-FUTURE", [_trip(31, "HOUSE", status=2, agent=3, verifier="C", appts=appt(today + timedelta(days=2)))],
              sla=NOW + timedelta(days=3)),
        _file(4, "F-APPT", [_trip(41, "HOUSE", status=2, agent=4, verifier="D", appts=appt(today))], sla=NOW + timedelta(days=3)),
        _file(5, "F-NORMAL", [_trip(51, "HOUSE", status=2, agent=5, verifier="E")], sla=NOW + timedelta(days=3)),
        _file(6, "F-DONE", [_trip(61, "HOUSE", status=5, agent=6, verifier="F")], sla=NOW + timedelta(days=3)),
        _file(7, "F-SUBMITTED", [_trip(71, "HOUSE", status=2, agent=7, verifier="G")], status=6),
    ], "LankaBangla Finance Limited": [
        _file(8, "L-HOLD", [_trip(81, "HOUSE", status=4, agent=5, verifier="E")], status=3, sla=NOW + timedelta(days=2)),
    ]}


PHONES = {i: {"name": n, "phone": f"880171100000{i}"} for i, n in enumerate("xABCDEFG") if i}


def test_queue_priority_appointments_and_both_clients():
    q = R.build_queue(_snap(), PHONES, round_key="1pm", now=NOW)
    assert [r.verifier for r in q] == ["A", "B", "D", "E"]                       # SLA passed, due today, appointment today, rest
    assert "C" not in [r.verifier for r in q]                                  # appointment on a later day: skipped
    e = q[-1]
    assert sorted(t.file_no for t in e.tasks) == ["F-NORMAL", "L-HOLD"]          # both clients in one message
    assert q[0].voice == "sla_passed" and q[2].voice == "appointment_today" and e.voice == "general"
    msg = R.message(q[0], "1pm")
    assert "F-SLA" in msg and "SLA পার" in msg and "১ = যাচ্ছি" in msg
    q10 = R.build_queue(_snap(), PHONES, round_key="10am", now=NOW.replace(hour=10))
    assert [r.verifier for r in q10] == ["A", "B", "D", "E"]                      # 10 AM: appointments first, then every on-going / hold trip
    assert "C" not in [r.verifier for r in q10]                                # later-day appointment still skipped
    assert "আজ অ্যাপয়েন্টমেন্ট" in R.message(q10[2], "10am") and "চলমান" in R.message(q10[3], "10am")


def test_bs_due_in_reminders_and_number_override():
    rows = BT.bs_rows([_file(9, "F-BS", [_trip(91, remarks="hard copy provided", agent=2, verifier="B")])], "Prime Bank PLC", store={})
    q = R.build_queue({}, PHONES, bs_pending=rows, round_key="4pm", now=NOW, overrides={"2": "8801999999999"})
    assert q[0].bs_due == ["F-BS"] and q[0].phone == "8801999999999" and q[0].voice == "bs_submit"
    assert "ব্যাংক স্টেটমেন্ট অফিসে জমা দিন" in R.message(q[0], "4pm")


@pytest.mark.parametrize("text,kind", [
    ("1", R.GOING), ("১", R.GOING), ("2", R.DONE), ("২ done", R.DONE), ("ji vai jacchi", R.GOING), ("done vai", R.DONE),
    ("শেষ", R.DONE), ("3 address pacchi na", R.PROBLEM), ("phone off", R.PROBLEM), ("সমস্যা আছে, বাসা বন্ধ", R.PROBLEM),
    ("kal jabo inshallah", R.GOING), ("hmm", R.OTHER),
])
def test_parse_reply(text, kind):
    assert R.parse_reply(text)[0] == kind


def test_problem_reason_kept():
    assert R.parse_reply("3 applicant phone off")[1] == "applicant phone off"


def test_catch_up_round_and_day_summary(tmp_store):
    st = {}
    assert R.due_round(st, datetime(2026, 11, 16, 9, 0)) is None
    assert R.due_round(st, datetime(2026, 11, 16, 14, 30)) == "1pm"             # PC was off at 1 PM: offered when it opens
    assert R.due_round(st, datetime(2026, 11, 16, 19, 0)) is None               # after 6:15 PM: nothing
    assert R.due_round(st, datetime(2026, 11, 20, 14, 0)) is None               # Friday
    q = R.build_queue(_snap(), PHONES, round_key="1pm", now=NOW)
    R.record_round(st, "1pm", q, now=datetime.combine(date.today(), NOW.time()))
    assert R.due_round(st, datetime.combine(date.today(), NOW.time()).replace(hour=14)) is None or date.today().weekday() in (4, 5)
    R.record_reply(st, PHONES[1]["phone"], "3 address pacchi na")
    R.record_reply(st, PHONES[2]["phone"], "done")
    s = R.day_summary(st)
    assert s["replied"] == 2 and s["problems"] == 1 and s["rows"][0]["last"] == R.PROBLEM and s["rows"][0]["reason"] == "address pacchi na"


# ------------------------------------------------------------------------------------------------ helper server
def test_helper_server_local_only_and_flow(tmp_store):
    from report_builder.helper_server import HelperServer
    events = []
    srv = HelperServer(lambda k, e: events.append(k), port=47399)
    st = {}
    R.record_round(st, "1pm", R.build_queue(_snap(), PHONES, round_key="1pm", now=NOW))
    R.save_state(st)
    assert srv.start()
    base = "http://127.0.0.1:47399"
    try:
        def req(path, body=None, origin=None):
            r = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                       headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
            try:
                with urllib.request.urlopen(r, timeout=5) as resp:
                    return resp.status, json.loads(resp.read())
            except urllib.error.HTTPError as e:
                return e.code, None
        assert req("/ping", origin="chrome-extension://abc")[0] == 200
        assert req("/round", origin="https://evil.example")[0] == 403              # a web page can never read the list
        code, data = req("/round", origin="chrome-extension://abc")
        assert code == 200 and len(data["items"]) == 4 and data["items"][0]["voice"] == "sla_passed"
        assert req("/sent", {"phone": PHONES[1]["phone"]}, "chrome-extension://abc")[1]["ok"]
        assert req("/reply", {"phone": PHONES[2]["phone"], "text": "ji jacchi"}, "chrome-extension://abc")[1]["kind"] == R.GOING
        assert req("/reply", {"phone": "8801000000000", "text": "spam"}, "chrome-extension://abc")[1] == {"ignored": True}
        items = req("/round", origin="chrome-extension://abc")[1]["items"]
        assert items[-1]["sent"] and not items[0]["sent"]                          # unsent first
        assert events == ["sent", "reply"]
    finally:
        srv.stop()


def test_extension_files_present():
    from report_builder.assets_path import asset
    m = json.loads(asset("whatsapp_helper", "manifest.json").read_text())
    assert m["manifest_version"] == 3 and m["host_permissions"] == ["http://127.0.0.1:47321/*"]
    assert m["content_scripts"][0]["matches"] == ["https://web.whatsapp.com/*"] and "permissions" in m
    js = asset("whatsapp_helper", "content.js").read_text()
    assert "send?phone=" in js and ".click()" not in js                         # never clicks Send


def test_verifier_phone_keeps_only_id_name_phone():
    from report_builder.client import verifier_phones

    class C:
        def get(self, path):
            return {"data": [{"id": 5, "name": " Rahim ", "phone": "01711-000005", "admin_access_token": "SECRET", "email": "x@y"}]}
    got = verifier_phones(C())
    assert got == {5: {"name": "Rahim", "phone": "8801711000005"}}


def test_mac_photo_reader_is_used_on_mac(monkeypatch, tmp_path):
    import stat, sys
    from report_builder import assets_path
    exe = tmp_path / "bin" / "mac_ocr"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\necho 'PL-20261001094920785  Sonali Bank'\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(assets_path, "asset", lambda *p: tmp_path.joinpath(*p))
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    assert "PL-20261001094920785" in BT.ocr_image(img)
