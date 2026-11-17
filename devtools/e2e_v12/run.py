"""V12 end-to-end check (run: python devtools/e2e_v12/run.py).  Needs Node + Playwright's Chromium and a display (xvfb-run).

The program side is real: reminders.build_queue / record_round / record_reply, the HelperServer on 127.0.0.1:47321 and its
/media slip saving; the Chrome side is the real helper extension.  Only WhatsApp is a mock page (devtools/e2e_v12/mock_whatsapp.html).
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

HOME = Path(tempfile.mkdtemp(prefix="vrb_e2e_"))
os.environ["HOME"] = str(HOME)                       # the program keeps its state under ~/.verify_report_builder
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from report_builder import bs_tracker as BT, config, reminders as R  # noqa: E402
from report_builder.helper_server import HelperServer, helper_folder  # noqa: E402
from test_v10 import _file, _trip  # noqa: E402

assert str(config.SETTINGS_DIR).startswith(str(HOME))
OWN = "8801700000099"
now = datetime.now().replace(hour=13, minute=5)
P1, P2 = "8801711000001", "8801711000002"
phones = {1: {"name": "Ratul", "phone": P1}, 2: {"name": "Sabbir", "phone": P2}}
snap = {"Prime Bank PLC": [_file(1, "PB-F1", [_trip(11, "HOUSE", status=3, agent=1, verifier="Ratul")], sla=now + timedelta(days=1)),
                           _file(2, "PB-F2", [_trip(21, "OFFICE", status=4, agent=2, verifier="Sabbir")], sla=now - timedelta(days=1))]}
bs = BT.bs_rows([_file(3, "PB-F3", [_trip(501263, remarks="hard copy provided", place="PRIME BANK PLC", agent=1, verifier="Ratul", status=5)])],
                "Prime Bank PLC", store={})
q = R.build_queue(snap, phones, bs_pending=bs, round_key="1pm", now=now)
st = R.load_state()
items = R.record_round(st, "1pm", q, now=datetime.combine(date.today(), now.time()), own_number=OWN)
R.save_state(st)
voices = config.SETTINGS_DIR / "voices"
voices.mkdir(parents=True, exist_ok=True)
for it in items:                                     # stand-in clips (the real ones come from the online voice)
    (voices / f"{it['voice']}.mp3").write_bytes(b"ID3" + os.urandom(4000))
codes = {it["phone"]: it["code"] for it in items}
print("round:", [(i["verifier"], i["code"], i["trips"], i["bs_trips"]) for i in items])
assert {i["phone"] for i in items} == {P1, P2} and any(i["bs_trips"] == [501263] for i in items)

events = []
srv = HelperServer(lambda k, e: events.append((k, e)))
srv.round_key = "1pm"
srv.slips_dir = HOME / "Reports" / "BS Slips"
assert srv.start(), "port 47321 busy"
try:
    cfg = {"profile": str(HOME / "chrome"), "ext": str(helper_folder()), "names": {P1: "Ratul Verifier", P2: "Sabbir Verifier"},
           "order": [i["phone"] for i in items], "codes": codes, "bs_phone": P1, "trip_phone": P2, "out": str(HOME / "e2e_out.json")}
    env = {**os.environ, "E2E_CFG": json.dumps(cfg)}
    cmd = ["node", str(Path(__file__).with_name("e2e.js"))]
    if not os.environ.get("DISPLAY"):
        cmd = ["xvfb-run", "-a"] + cmd
    res = subprocess.run(cmd, env=env, timeout=600)
    assert res.returncode == 0, "browser part failed"
finally:
    srv.stop()

# ---------------------------------------------------------------- what the program now knows
st = R.load_state()
ds = R.day_state(st)
its = ds["rounds"]["1pm"]["items"]
assert all(i["sent"] for i in its), "a message was not marked sent"
out = json.loads((HOME / "e2e_out.json").read_text())
assert all(a and a["type"] == "audio/mpeg" and a["size"] > 1000 for a in out["attaches"]), out
rep = {(r["phone"], r["kind"]): r for r in ds["replies"]}
b2 = rep[(P1, R.SUBMITTED)]
assert b2["code"] == codes[P1] and b2["trips"] == [501263], b2
t3 = rep[(P2, R.PROBLEM)]
assert t3["code"] == codes[P2] and t3["trips"] == [21] and t3["reason"] == "Bank bondho chilo, kal jabo", t3
assert st["asks"][P1]["sent"] and st["asks"][P2]["sent"] and st["asks"][P1]["answered"] and st["asks"][P2]["answered"]
day = srv.slips_dir / date.today().isoformat()
pics = list(day.glob("501263 - Ratul/slip *.jpg"))
assert len(pics) == 1 and pics[0].stat().st_size > 5000 and pics[0].read_bytes()[:2] == b"\xff\xd8", pics
store = BT.load_store()
assert store["501263"]["bank_submitted"]["photos"] == [str(pics[0])], store
assert not any(e[0] == "reply" and "Joma diyechi" not in e[1].get("text", "") and e[1].get("phone") == P1 and e[1].get("kind") == R.OTHER
               for e in events), "the photo preview was taken as a text reply"
assert [k for k, _e in events].count("media") == 1
print("\nE2E OK:")
print(" - 2 chats opened with the text typed + voice (audio/mpeg) attached; Send pressed by 'Naim'; both marked sent")
print(f" - 'Joma diyechi #{codes[P1]}-B2' -> BS trip 501263, photo asked; 'Somossa ache #{codes[P2]}-T3' -> trip 21, reason asked")
print(" - both follow-ups opened typed, sent by 'Naim'")
print(f" - slip photo saved: {pics[0].relative_to(HOME)}  and BS 501263 marked handed in at the bank")
print(" - reason saved: 'Bank bondho chilo, kal jabo'")
