"""v10 WhatsApp reminders for verifiers (Prime Bank + LankaBangla).

Who:  every verifier with an open trip (trip Created / Allocated / Started / Hold) in an ON GOING or HOLD file, both clients,
      plus verifiers who still have to hand in a collected bank statement.  No cap - everyone keeps getting reminders.
When: 10:00 AM - short reminder about TODAY's appointments only;  1:00 PM and 4:00 PM - everyone.
      A trip whose appointment is on a later day is skipped until that day; a trip with an appointment today is reminded
      until it is finished.  If the PC was off at a round time, the latest missed round is offered when the program opens
      (the exact time does not matter).
Order: SLA passed or due today first, then appointment today, then the rest.
How:  nothing is sent by the program.  The helper in WhatsApp Web opens each chat with the message typed in and the voice
      clip attached; Naim presses Send.  Replies are read back (helper) and understood here (parse_reply).
Day end: a summary inside the program only (nothing is sent anywhere).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from . import config
from .client import is_bd_mobile

ROUNDS = [("10am", time(10, 0)), ("1pm", time(13, 0)), ("4pm", time(16, 0))]
ROUND_LABEL = {"10am": "10:00 AM", "1pm": "01:00 PM", "4pm": "04:00 PM"}
OPEN_FILE = (2, 3)                      # On Going, Hold
OPEN_TRIP = (1, 2, 3, 4)                # Created, Allocated, Started, Hold
STATE_FILE = config.SETTINGS_DIR / "reminders.json"

P_SLA, P_TODAY, P_APPT, P_NORMAL = 0, 1, 2, 3
PRIORITY_TEXT = {P_SLA: "SLA passed", P_TODAY: "Due today", P_APPT: "Appointment today", P_NORMAL: "Normal"}

NO_WA_CACHE: set = set()                 # numbers WhatsApp said are not on WhatsApp (filled from the state file)

VOICE = {"sla": "sla_passed", "appt": "appointment_today", "bs": "bs_submit", "general": "general"}


@dataclass
class Task:
    org: str
    file_no: str
    trip_id: int
    trip_type: str
    priority: int
    note: str = ""


@dataclass
class Reminder:
    verifier_id: int | None
    verifier: str
    phone: str
    tasks: list = field(default_factory=list)
    bs_due: list = field(default_factory=list)     # file numbers whose collected BS is not yet in the office

    @property
    def priority(self) -> int:
        ps = [t.priority for t in self.tasks] + ([P_NORMAL] if self.bs_due else [])
        return min(ps) if ps else P_NORMAL

    @property
    def has_whatsapp_number(self) -> bool:
        return is_bd_mobile(self.phone) and self.phone not in NO_WA_CACHE

    @property
    def voice(self) -> str:
        if self.priority <= P_TODAY:
            return VOICE["sla"]
        if self.priority == P_APPT:
            return VOICE["appt"]
        if self.bs_due and not self.tasks:
            return VOICE["bs"]
        return VOICE["general"]


def _appt_days(trip: dict) -> list[date]:
    return sorted({a["time"].date() for a in trip.get("appointments") or [] if a.get("active", True) and a.get("time")})


def build_queue(snapshot: dict, phones: dict, bs_pending: list | None = None, round_key: str = "1pm",
                now: datetime | None = None, overrides: dict | None = None) -> list[Reminder]:
    """snapshot = {org name: [normalised files]}; phones = {verifier id: {"name","phone"}};
    overrides = numbers Naim added / changed in the program {verifier id (str): phone}."""
    now = now or datetime.now()
    today = now.date()
    overrides = overrides or {}
    by: dict = {}

    def rem_for(vid, name):
        key = vid if vid is not None else f"name:{name}"
        if key not in by:
            phone = overrides.get(str(vid)) if vid is not None else None
            phone = phone or (phones.get(vid) or {}).get("phone", "") if vid is not None else ""
            by[key] = Reminder(vid, name or (phones.get(vid) or {}).get("name", "") or "?", phone or "")
        return by[key]

    for org, files in snapshot.items():
        for f in files:
            if f.get("status_code") not in OPEN_FILE:
                continue
            sla = f.get("sla")
            for c in f.get("concerns") or []:
                for t in c.get("trips") or []:
                    if t.get("status_code") not in OPEN_TRIP:
                        continue
                    days = _appt_days(t)
                    future = [d for d in days if d > today]
                    has_today = today in days
                    if future and not has_today:
                        continue                                    # appointment on a later day: skip until then
                    if round_key == "10am" and not has_today:
                        continue                                    # 10 AM: today's appointments only
                    if sla and sla.date() < today:
                        pr, note = P_SLA, "SLA passed"
                    elif sla and sla.date() == today:
                        pr, note = P_TODAY, "Due today"
                    elif has_today:
                        pr, note = P_APPT, "Appointment today"
                    else:
                        pr, note = P_NORMAL, ""
                    rem_for(t.get("agent_id"), t.get("verifier", "")).tasks.append(
                        Task(org, f.get("file_no", ""), t.get("id"), t.get("type", ""), pr, note))
    if round_key != "10am":
        for r in bs_pending or []:
            if r.collected and not r.office and not r.courier.get("no"):
                rem = rem_for(r.verifier_id, r.verifier)
                if r.file_no not in rem.bs_due:
                    rem.bs_due.append(r.file_no)
    out = [r for r in by.values() if r.tasks or r.bs_due]
    out.sort(key=lambda r: (r.priority, -len(r.tasks), r.verifier))
    return out


def message(rem: Reminder, round_key: str) -> str:
    """Short Bangla message (the voice clip says the same thing in general words)."""
    lines = ["আসসালামু আলাইকুম।"]
    by_pr: dict = {}
    for t in rem.tasks:
        by_pr.setdefault(t.priority, []).append(t)
    if round_key == "10am":
        files = ", ".join(sorted({t.file_no for t in rem.tasks}))
        lines.append(f"আজ অ্যাপয়েন্টমেন্ট আছে: {files}। আজই শেষ করুন।")
    else:
        if by_pr.get(P_SLA):
            lines.append(f"SLA পার হয়ে গেছে: {_files(by_pr[P_SLA])}। আজই শেষ করুন।")
        if by_pr.get(P_TODAY):
            lines.append(f"আজ SLA শেষ: {_files(by_pr[P_TODAY])}।")
        if by_pr.get(P_APPT):
            lines.append(f"আজ অ্যাপয়েন্টমেন্ট: {_files(by_pr[P_APPT])}।")
        if by_pr.get(P_NORMAL):
            lines.append(f"চলমান: {_files(by_pr[P_NORMAL])}।")
        if rem.bs_due:
            lines.append(f"ব্যাংক স্টেটমেন্ট অফিসে জমা দিন: {', '.join(rem.bs_due)}।")
    lines.append("উত্তর দিন: ১ = যাচ্ছি, ২ = শেষ, ৩ = সমস্যা আছে (কারণ লিখুন)।")
    return "\n".join(lines)


def _files(tasks) -> str:
    seen = []
    for t in tasks:
        label = f"{t.file_no} ({t.trip_type})"
        if label not in seen:
            seen.append(label)
    return ", ".join(seen)


# ============================================================================================ replies
GOING, DONE, PROBLEM, OTHER = "going", "done", "problem", "other"
REPLY_TEXT = {GOING: "যাচ্ছি", DONE: "শেষ", PROBLEM: "সমস্যা আছে", OTHER: "অন্য উত্তর"}
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_PROBLEM = re.compile(r"\b(somossa|shomossa|problem|issue|pacchi\s*na|paccina|pai\s*ni|paini|pawa\s*jay\s*ni|off|bondho|bandh|"
                      r"cancel|asbe\s*na|dibe\s*na|refuse|disagree|rajinna|raji\s*na|not\s+available|nai|nei|hocche\s*na|hoy\s*ni|hoini)\b|"
                      r"সমস্যা|পাচ্ছি না|পাইনি|বন্ধ|রাজি না|হচ্ছে না|হয়নি|নেই|নাই")
_DONE = re.compile(r"\b(done|shesh|sesh|complete\w*|finish\w*|submit\w*|kora\s*hoise|korsi|korechi|hoye\s*geche|hoyse|ok\s*done)\b|"
                   r"শেষ|হয়ে গেছে|করেছি|সাবমিট|জমা দিয়েছি")
_GOING = re.compile(r"\b(jacchi|jassi|jabo|jaitesi|jaitasi|going|on\s*the\s*way|ji|jee|ok|okay|thik\s*ache|accha|insha\s*allah|inshallah)\b|"
                    r"যাচ্ছি|যাব|জি|ঠিক আছে|আচ্ছা|ইনশাআল্লাহ")


def parse_reply(text: str) -> tuple[str, str]:
    """-> (kind, reason).  Codes 1/2/3 (Bangla or English digits) first, then common words (Banglish / Bangla / English).
    For "problem" the reason is the reply without the code."""
    raw = (text or "").strip()
    t = raw.translate(_BN_DIGITS).lower()
    m = re.match(r"^\s*([123])\b[\s.,:=\-)]*(.*)$", t, re.S)
    if m:
        kind = {"1": GOING, "2": DONE, "3": PROBLEM}[m.group(1)]
        rest = raw[len(raw) - len(m.group(2)):].strip() if m.group(2) else ""
        return kind, (rest if kind == PROBLEM else "")
    if _PROBLEM.search(t):
        return PROBLEM, raw
    if _DONE.search(t):
        return DONE, ""
    if _GOING.search(t):
        return GOING, ""
    return OTHER, raw


# ============================================================================================ state (local file)
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(st: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(STATE_FILE)


def day_state(st: dict, day: date | None = None) -> dict:
    d = (day or date.today()).isoformat()
    days = st.setdefault("days", {})
    for old in [k for k in days if k < (date.fromisoformat(d) - timedelta(days=30)).isoformat()]:
        days.pop(old, None)                                 # keep one month
    return days.setdefault(d, {"rounds": {}, "replies": []})


def due_round(st: dict, now: datetime | None = None) -> str | None:
    """The latest round whose time has passed today and that has not been prepared yet (catch-up after the PC was off).
    Office hours only (until 6:15 PM)."""
    now = now or datetime.now()
    if now.time() > time(18, 15) or now.weekday() in (4, 5):
        return None
    ds = day_state(st, now.date())
    passed = [k for k, t in ROUNDS if now.time() >= t]
    if not passed:
        return None
    latest = passed[-1]
    return None if latest in ds["rounds"] else latest


def record_round(st: dict, round_key: str, queue: list[Reminder], now: datetime | None = None) -> None:
    now = now or datetime.now()
    ds = day_state(st, now.date())
    ds["rounds"][round_key] = {"prepared": now.isoformat(timespec="minutes"),
                               "items": [{"phone": r.phone, "verifier": r.verifier, "vid": r.verifier_id, "priority": r.priority,
                                          "files": sorted({t.file_no for t in r.tasks} | set(r.bs_due)),
                                          "text": message(r, round_key), "voice": r.voice, "sent": None}
                                         for r in queue if r.has_whatsapp_number],
                               "no_whatsapp": [{"verifier": r.verifier, "vid": r.verifier_id, "phone": r.phone}
                                               for r in queue if not r.has_whatsapp_number]}


NO_WHATSAPP = "__no_whatsapp__"          # sent by the helper when WhatsApp says the number is not on WhatsApp


def record_reply(st: dict, phone: str, text: str, when: str | None = None) -> dict:
    if text == NO_WHATSAPP:
        st.setdefault("no_whatsapp", {})[phone] = date.today().isoformat()
        return {"phone": phone, "kind": "no_whatsapp"}
    kind, reason = parse_reply(text)
    ds = day_state(st)
    e = {"phone": phone, "text": text[:500], "kind": kind, "reason": reason[:300], "at": when or datetime.now().isoformat(timespec="minutes")}
    if not any(x["phone"] == phone and x["text"] == e["text"] for x in ds["replies"]):
        ds["replies"].append(e)
    return e


def day_summary(st: dict, day: date | None = None) -> dict:
    """Numbers + one line per verifier, for the day-end view (inside the program only)."""
    ds = day_state(st, day)
    people: dict = {}
    for rk, rd in ds["rounds"].items():
        for it in rd.get("items", []):
            p = people.setdefault(it["phone"], {"verifier": it["verifier"], "rounds": 0, "sent": 0, "files": set(), "last": None, "reason": ""})
            p["rounds"] += 1
            p["sent"] += 1 if it.get("sent") else 0
            p["files"] |= set(it.get("files") or [])
    for rp in ds["replies"]:
        p = people.setdefault(rp["phone"], {"verifier": rp["phone"], "rounds": 0, "sent": 0, "files": set(), "last": None, "reason": ""})
        p["last"] = rp["kind"]
        if rp["kind"] == PROBLEM:
            p["reason"] = rp["reason"]
    rows = sorted(({**v, "phone": k, "files": sorted(v["files"])} for k, v in people.items()),
                  key=lambda x: (x["last"] != PROBLEM, x["last"] is not None, x["verifier"]))
    return {"rows": rows,
            "sent": sum(r["sent"] for r in rows),
            "replied": sum(1 for r in rows if r["last"]),
            "problems": sum(1 for r in rows if r["last"] == PROBLEM),
            "no_reply": sum(1 for r in rows if r["sent"] and not r["last"])}
