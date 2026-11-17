"""V12 (18-11-2026): the five reminder rounds, tap-link answers with codes, follow-ups (slip photo / short note), the slip photo
saved by date / trip / verifier, the BS 'who still holds a BS' table, the spoken text (Pradeep)."""
import base64
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from report_builder import bs_tracker as BT, reminders as R  # noqa: E402
from test_v10 import NOW, PHONES, _file, _snap, _trip, tmp_store  # noqa: E402,F401

OWN = "8801700000099"


def _bs(tid=501263, agent=2, verifier="B", place="PRIME BANK PLC", status=5, end=None, remarks="hard copy provided"):
    t = _trip(tid, remarks=remarks, place=place, agent=agent, verifier=verifier, status=status)
    t["end_time"] = end
    return BT.bs_rows([_file(9, "F-BS", [t])], "Prime Bank PLC", store={})


# ------------------------------------------------------------------------------------------------ rounds
def test_five_rounds_what_each_one_reminds():
    assert [k for k, _t in R.ROUNDS] == ["8am", "10am", "1pm", "3pm", "530pm"]
    assert R.BS_ROUNDS == ("1pm", "530pm")
    at = lambda h, m=0: NOW.replace(hour=h, minute=m)  # noqa: E731
    assert [r.verifier for r in R.build_queue(_snap(), PHONES, round_key="8am", now=at(8))] == ["D"]       # appointments only
    assert [r.verifier for r in R.build_queue(_snap(), PHONES, round_key="3pm", now=at(15))] == ["D"]      # appointments still open
    for rk, h in (("10am", 10), ("1pm", 13), ("530pm", 17)):
        q = R.build_queue(_snap(), PHONES, round_key=rk, now=at(h, 30 if h == 17 else 0))
        assert [r.verifier for r in q] == ["A", "B", "D", "E"], rk                 # every On Going + Hold trip, SLA passed first
    q = R.build_queue(_snap(), PHONES, round_key="1pm", now=NOW)
    assert all("F-DONE" != t.file_no and "F-SUBMITTED" != t.file_no for r in q for t in r.tasks)    # finished / submitted: never


def test_test_files_are_never_reminded():
    snap = {"Prime Bank PLC": [_file(1, "PB-PL-Test-123456", [_trip(11, "HOUSE", status=3, agent=1, verifier="A")],
                                     sla=NOW + timedelta(days=1))]}
    assert R.build_queue(snap, PHONES, round_key="1pm", now=NOW) == []


def test_hold_section_asks_for_the_reason_and_on_going_shows_sla():
    q = R.build_queue(_snap(), PHONES, round_key="10am", now=NOW.replace(hour=10))
    e = R.message(q[3], "10am", NOW.date())
    assert "⛔ *HOLD — ১টি*" in e and "Hold-এর সঠিক কারণ লিখে Update করুন" in e and "▶ *ON GOING — ১টি*" in e
    assert e.index("HOLD") < e.index("ON GOING")
    a = R.message(q[0], "10am", NOW.date())
    assert "SLA: ❌ পার হয়ে গেছে" in a and "করণীয়: " in a


def test_task_specific_instructions():
    assert R.task_kind("DOC_DRCHAMBER") == "chamber" and "Chamber report form" in R.TODO["chamber"]
    assert R.task_kind("DOCUMENT", "Rental verification") == "rental" and "Rental report form" in R.TODO["rental"]
    assert R.task_kind("DOCUMENT", "LOI sign") == "loi" and R.task_kind("RENTAL") == "rental"
    assert R.task_kind("DOCUMENT", "take PG sign") == "sign_pg"


# ------------------------------------------------------------------------------------------------ tap links and codes
def test_tap_links_carry_a_code_per_message_and_short_english_words():
    q = R.build_queue({}, PHONES, bs_pending=_bs(), round_key="1pm", now=NOW)
    msg = R.message(q[0], "1pm", NOW.date(), 3, OWN)
    assert f"👉 জমা দিয়েছি: https://wa.me/{OWN}?text=Joma%20diyechi%20%23VB-1116-1pm-3-B2" in msg
    assert "%E0" not in msg                                                    # no long %E0%A6… lines on the phone
    assert "Trip ID 501263 · Prime Bank PLC" in msg
    for words, code in (("Joma diyechi #VB-1116-1pm-3-B2", "B2"), ("Jacchi #VB-1116-10am-12-T1", "T1"),
                        ("somossa ache #vb-1116-530PM-1-t3", "T3")):
        assert R.parse_code(words)[1] == code
    assert R.parse_reply("Joma diyechi #VB-1116-1pm-3-B2")[0] == R.SUBMITTED
    assert R.parse_reply("Aaj joma dibo #VB-1116-1pm-3-B1")[0] == R.WILL_SUBMIT
    assert R.parse_reply("Somossa ache #VB-1116-1pm-3-B3")[0] == R.PROBLEM
    no_own = R.message(q[0], "1pm", NOW.date(), 3, "")
    assert "wa.me" not in no_own and "1 = আজ জমা দেব" in no_own                    # no own number yet: numbered answers


def test_bs_only_in_the_1pm_and_530pm_rounds_and_online_skipped_once_handed_in():
    rows = _bs()
    assert R.build_queue({}, PHONES, bs_pending=rows, round_key="10am", now=NOW.replace(hour=10)) == []
    assert R.build_queue({}, PHONES, bs_pending=rows, round_key="530pm", now=NOW.replace(hour=17, minute=31))[0].bs_due[0].online
    rows[0].bank_submitted = {"at": "x"}
    assert R.build_queue({}, PHONES, bs_pending=rows, round_key="1pm", now=NOW) == []
    off = _bs(place="NCC Bank")
    off[0].office = {"at": "x"}
    assert R.build_queue({}, PHONES, bs_pending=off, round_key="1pm", now=NOW) == []      # already in the office


def test_answers_go_to_the_right_trips_and_ask_for_photo_or_note(tmp_store):
    st = {}
    q = R.build_queue(_snap(), PHONES, bs_pending=_bs(), round_key="1pm", now=datetime.combine(date.today(), NOW.time()))
    items = R.record_round(st, "1pm", q, now=datetime.combine(date.today(), NOW.time()), own_number=OWN)
    b = next(i for i in items if i["bs_trips"])
    a = next(i for i in items if i["verifier"] == "A")
    e = R.record_reply(st, b["phone"], f"Joma diyechi #{b['code']}-B2")
    assert e["kind"] == R.SUBMITTED and e["trips"] == [501263]
    assert st["asks"][b["phone"]]["want"] == "photo" and st["asks"][b["phone"]]["text"] == R.FOLLOW_PHOTO
    e = R.record_reply(st, a["phone"], f"Somossa ache #{a['code']}-T3")
    assert e["kind"] == R.PROBLEM and e["trips"] == a["trips"] == [11]
    assert R.record_reply(st, a["phone"], R.FOLLOW_NOTE) == {"ignored": True}           # our own follow-up shown back
    n = R.record_reply(st, a["phone"], "Applicant er phone off")
    assert n["kind"] == "note" and st["asks"][a["phone"]]["answered"]
    prob = [r for r in R.day_state(st)["replies"] if r["kind"] == R.PROBLEM]
    assert prob[0]["reason"] == "Applicant er phone off"
    assert [x["phone"] for x in R.open_asks(st)] == [b["phone"]]                        # the note is done, the photo waits
    st["asks"][b["phone"]]["answered"] = (datetime.now() - timedelta(hours=7)).isoformat(timespec="minutes")
    assert R.open_asks(st) == []                                                        # 6 hours after the first slip: closed


def test_slip_photo_saved_by_date_trip_verifier_and_bs_marked(tmp_store, tmp_path):
    from report_builder.helper_server import HelperServer
    st = {}
    q = R.build_queue({}, PHONES, bs_pending=_bs(), round_key="1pm", now=datetime.combine(date.today(), NOW.time()))
    items = R.record_round(st, "1pm", q, now=datetime.combine(date.today(), NOW.time()), own_number=OWN)
    ph = items[0]["phone"]
    R.record_reply(st, ph, f"Joma diyechi #{items[0]['code']}-B2")
    R.save_state(st)
    events = []
    srv = HelperServer(lambda k, e: events.append(k), port=47398)
    srv.slips_dir = tmp_path / "BS Slips"
    assert srv.start()
    jpg = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 8 + b"\xff\xd9"
    try:
        def post(path, body):
            r = urllib.request.Request("http://127.0.0.1:47398" + path, data=json.dumps(body).encode(),
                                       headers={"Content-Type": "application/json", "Origin": "chrome-extension://x"})
            with urllib.request.urlopen(r, timeout=5) as resp:
                return json.loads(resp.read())
        body = {"phone": ph, "b64": "data:image/jpeg;base64," + base64.b64encode(jpg).decode(), "type": "image/jpeg", "msg": "conv-msg-1"}
        r1 = post("/media", body)
        assert r1["ok"] and len(r1["files"]) == 1
        assert post("/media", body)["ignored"]                                         # the same message twice: once
        r2 = post("/media", {**body, "msg": "conv-msg-2"})                              # a second slip: kept too
        assert r2["ok"] and r2["files"][0] != r1["files"][0]
        assert post("/media", {**body, "phone": "8801000000000"})["ignored"]             # nobody asked this number
    finally:
        srv.stop()
    p = Path(r1["files"][0])
    assert p.parent == tmp_path / "BS Slips" / date.today().isoformat() / "501263 - B" and p.read_bytes() == jpg
    store = BT.load_store()
    assert store["501263"]["bank_submitted"]["photos"] and events.count("media") == 2


# ------------------------------------------------------------------------------------------------ BS page: who holds how many
def test_who_still_holds_a_bs_with_bank_and_withdraw_day():
    rows = (_bs(1, agent=1, verifier="A", end=datetime(2026, 11, 10, 15)) + _bs(2, agent=1, verifier="A", end=datetime(2026, 11, 8, 11))
            + _bs(3, agent=2, verifier="B", end=datetime(2026, 11, 12, 9)) + _bs(4, agent=2, verifier="B", status=3, remarks=""))
    rows[2].office = {"at": "x"}
    held = BT.still_with_verifier(rows)
    assert [r.trip_id for r in held] == [1, 2]                                         # B's is in the office; trip 4 not collected yet
    groups = BT.by_verifier(held + _bs(5, agent=3, verifier="C", end=datetime(2026, 11, 11, 9)))
    assert [g[0] for g in groups] == ["A", "C"] and [r.trip_id for r in groups[0][1]] == [2, 1]   # most first, oldest first
    assert held[0].finished == datetime(2026, 11, 10, 15) and held[0].bank == "Prime Bank PLC"


# ------------------------------------------------------------------------------------------------ the voice text
def test_voice_text_speaks_trip_id_digit_by_digit_and_sla_slowly():
    q = R.build_queue(_snap(), PHONES, round_key="1pm", now=NOW)
    v = R.voice_text(q[0], "1pm", NOW.date())
    assert "ট্রিপ আইডি: এক, এক" in v and "S, L, A" in v
    assert R.say_digits(501263) == "পাঁচ, শূন্য, এক, দুই, ছয়, তিন"
    assert R.translit("Md Rakibul Hasan").startswith("এমডি") or "রাকিবুল" in R.translit("Md Rakibul Hasan")
    assert R.translit("রাতুল") == "রাতুল"
    assert R.say_time(datetime(2026, 11, 16, 15, 30)).endswith("সাড়ে তিনটা") or "সাড়ে তিনটা" in R.say_time(datetime(2026, 11, 16, 15, 30))
