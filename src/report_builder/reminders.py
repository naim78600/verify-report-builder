"""V12 WhatsApp reminders for verifiers (Prime Bank + LankaBangla) - Naim's plan of 18-11-2026.

Rounds (office days, Sunday-Thursday):
   8:00 AM  appointments of today only                       (kind "appt")
  10:00 AM  every On Going + Hold trip                        (kind "open")
   1:00 PM  every On Going + Hold trip  + BS hand-in          (kind "open")
   3:00 PM  today's appointments that are still open, kindly  (kind "appt_left": thanks for what was finished today)
   5:30 PM  every On Going + Hold trip  + BS hand-in          (kind "open")
Each round is built from the dashboard's LATEST data: a finished trip is never reminded again.  A trip whose appointment is
on a later day is left out until that day.  If the PC was off at a round time, the latest missed round is offered.

Message: written in the dashboard's own words (Trip ID, trip type, status, File No, applicant, appointment, comment, SLA),
with three tap links (wa.me, free): the verifier taps one, WhatsApp writes the answer with a code, he presses Send.  The
program reads the code, so it knows exactly which message (and which trips) the answer belongs to.  "জমা দিয়েছি" asks for the
slip photo, "সমস্যা" asks for a short note; both are follow-up messages Naim sends with one press.
Voice: the same content, spoken by the Pradeep voice (made on the PC when the round is prepared; see voice.py).
Nothing is sent by the program: the helper in WhatsApp Web opens each chat with the text typed in and the voice attached.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from . import config
from .client import is_bd_mobile

ROUNDS = [("8am", time(8, 0)), ("10am", time(10, 0)), ("1pm", time(13, 0)), ("3pm", time(15, 0)), ("530pm", time(17, 30))]
ROUND_LABEL = {"8am": "08:00 AM", "10am": "10:00 AM", "1pm": "01:00 PM", "3pm": "03:00 PM", "530pm": "05:30 PM"}
ROUND_KIND = {"8am": "appt", "10am": "open", "1pm": "open", "3pm": "appt_left", "530pm": "open"}
ROUND_WHAT = {"appt": ("আজকের appointment", "Today's appointments"),
              "open": ("সব On Going + Hold", "Every On Going + Hold trip"),
              "appt_left": ("বাকি appointment (ধন্যবাদসহ)", "Appointments still open (with thanks)")}
BS_ROUNDS = ("1pm", "530pm")             # bank statement hand-in reminders ride along with these rounds
OFFICE_END = time(18, 15)
OPEN_FILE = (2, 3)                      # On Going, Hold
OPEN_TRIP = (1, 2, 3, 4)                # Created, Allocated, Started, Hold
STATE_FILE = config.SETTINGS_DIR / "reminders.json"
MAX_TRIPS = 8                           # more than this in one message -> "আরও nটি - ড্যাশবোর্ডে দেখুন"

P_SLA, P_TODAY, P_APPT, P_NORMAL = 0, 1, 2, 3
PRIORITY_TEXT = {P_SLA: "SLA passed", P_TODAY: "Due today", P_APPT: "Appointment today", P_NORMAL: "Normal"}
NO_WA_CACHE: set = set()                 # numbers WhatsApp said are not on WhatsApp (filled from the state file)
STATUS_NAME = config.TRIP_STATUS


@dataclass
class Task:
    org: str
    file_no: str
    trip_id: int
    trip_type: str
    priority: int
    note: str = ""
    applicant: str = ""
    status: str = ""                     # dashboard words: Created / Allocated / Started / Hold
    status_code: int | None = None
    type_code: str = ""
    comment: str = ""
    appt: datetime | None = None         # today's appointment (active)
    appt_type: str = ""
    sla: datetime | None = None
    designation: str = ""

    @property
    def kind(self) -> str:
        """What the verifier has to do, read from the trip type, the back-office comment and the applicant's designation."""
        return task_kind(self.type_code, self.comment, self.designation)

    @property
    def type_label(self) -> str:
        k = self.kind
        if self.type_code == "DOCUMENT" and k in DOC_KINDS:
            return f"Document ({DOC_KINDS[k][0]})"
        return self.trip_type


@dataclass
class BSDue:
    trip_id: int
    file_no: str
    bank: str
    applicant: str
    collected: datetime | None
    online: bool


@dataclass
class Reminder:
    verifier_id: int | None
    verifier: str
    phone: str
    tasks: list = field(default_factory=list)
    bs_due: list = field(default_factory=list)      # BSDue
    thanks: list = field(default_factory=list)      # Tasks finished today (3 PM round)

    @property
    def priority(self) -> int:
        ps = [t.priority for t in self.tasks] + ([P_NORMAL] if self.bs_due else [])
        return min(ps) if ps else P_NORMAL

    @property
    def has_whatsapp_number(self) -> bool:
        return is_bd_mobile(self.phone) and self.phone not in NO_WA_CACHE


# ============================================================================================ what each trip asks for
DOC_KINDS = {            # kind -> (short name, what to do)
    "loi": ("LOI", "signatory-র স্বাক্ষর + সিল + visiting card নেবেন"),
    "chamber": ("Chamber", "চেম্বার দেখে Chamber report form পূরণ করে Submit করবেন"),
    "rental": ("Rental", "Rental report form পূরণ করবেন (ভাড়াটিয়ার নাম, ভাড়া)"),
    "tuition": ("Tuition", "Tuition যাচাই করবেন"),
    "car": ("Car quotation", "Car quotation যাচাই করবেন"),
    "pec": ("Experience certificate", "Experience certificate যাচাই করবেন"),
    "sign_pg": ("PG Sign", "গ্যারান্টরের স্বাক্ষর নেবেন"),
    "sign_app": ("Applicant Sign", "আবেদনকারীর স্বাক্ষর নেবেন"),
    "payslip": ("Pay slip", "Pay slip / salary certificate যাচাই করবেন"),
}
TODO = {
    "house": "ঠিকানা, মোবাইল, কতদিন আছেন, কে কনফার্ম করলেন — remarks-এ লিখবেন",
    "office": "অফিস, পদবি, বেতন যাচাই + আবেদনকারীর স্বাক্ষর",
    "bank": "Bank statement hard copy + ব্যাংক কর্মকর্তার নাম ও নম্বর",
    "pg_house": "গ্যারান্টরের বাসা যাচাই + স্বাক্ষর",
    "pg_office": "গ্যারান্টরের অফিস যাচাই + স্বাক্ষর",
    **{k: v[1] for k, v in DOC_KINDS.items()},
    "doc": "ডকুমেন্ট যাচাই করবেন",
}
_DOCTOR = re.compile(r"doctor|\bdr\b|physician|surgeon|consultant|medical officer|mbbs|dental", re.I)


def task_kind(type_code: str, comment: str = "", designation: str = "") -> str:
    tc, cm = (type_code or "").upper(), (comment or "").lower()
    if tc == "HOUSE":
        return "house"
    if tc == "OFFICE":
        return "office"
    if tc == "BANK":
        return "bank"
    if tc == "GUARANTOR_HOUSE":
        return "pg_house"
    if tc == "GUARANTOR_OFFICE":
        return "pg_office"
    if tc == "RENTAL" or "rental" in cm:
        return "rental"
    if tc == "DOC_DRCHAMBER" or "chamber" in cm:
        return "chamber"
    if tc == "DOC_TUITION" or re.search(r"tuition|tution", cm):
        return "tuition"
    if tc == "CAR_QUATATION" or "car quot" in cm:
        return "car"
    if re.search(r"experience|\bpec\b", cm):
        return "pec"
    if re.search(r"pg\s+sign|guarantor\s+sign", cm):
        return "sign_pg"
    if re.search(r"applicant\s+sign", cm):
        return "sign_app"
    if re.search(r"pay\s*slip|salary", cm):
        return "payslip"
    if "loi" in cm or tc == "DOCUMENT":
        return "loi" if ("loi" in cm or not cm) else "doc"
    return "doc"


def _appt_today(trip: dict, today: date) -> dict | None:
    ap = [a for a in trip.get("appointments") or [] if a.get("active", True) and a.get("time") and a["time"].date() == today]
    return max(ap, key=lambda a: a.get("created_at") or datetime.min) if ap else None


def _appt_later_only(trip: dict, today: date) -> bool:
    days = {a["time"].date() for a in trip.get("appointments") or [] if a.get("active", True) and a.get("time")}
    return bool(days) and today not in days and any(d > today for d in days)


def _applicant(f: dict) -> tuple[str, str]:
    cs = f.get("concerns") or []
    for c in cs:
        if (c.get("role") or "").lower() in ("applicant", "") and c.get("name"):
            return c["name"], c.get("designation", "")
    return (cs[0].get("name", ""), cs[0].get("designation", "")) if cs else ("", "")


# ============================================================================================ the queue
def build_queue(snapshot: dict, phones: dict, bs_pending: list | None = None, round_key: str = "1pm",
                now: datetime | None = None, overrides: dict | None = None) -> list[Reminder]:
    """snapshot = {org name: [normalised files]}; phones = {verifier id: {"name","phone"}};
    bs_pending = BSRow-like rows (bs_tracker); overrides = numbers Naim added / changed {verifier id (str): phone}."""
    now = now or datetime.now()
    today = now.date()
    kind = ROUND_KIND.get(round_key, "open")
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
            if "test" in (f.get("file_no") or "").lower():
                continue                                            # practice files are never reminded
            applicant, desig = _applicant(f)
            sla = f.get("sla")
            for c in f.get("concerns") or []:
                for t in c.get("trips") or []:
                    st = t.get("status_code")
                    ap = _appt_today(t, today)
                    if kind == "appt_left" and st == 5 and ap and t.get("end_time") and t["end_time"].date() == today:
                        rem_for(t.get("agent_id"), t.get("verifier", "")).thanks.append(
                            Task(org, f.get("file_no", ""), t.get("id"), t.get("type", ""), P_APPT, applicant=applicant,
                                 type_code=t.get("type_code", ""), comment=t.get("comment", ""), designation=desig))
                        continue
                    if f.get("status_code") not in OPEN_FILE or st not in OPEN_TRIP:
                        continue
                    if kind in ("appt", "appt_left") and not ap:
                        continue
                    if kind == "open" and _appt_later_only(t, today):
                        continue                                    # appointment on a later day: wait for that day
                    if sla and sla.date() < today:
                        pr, note = P_SLA, "SLA passed"
                    elif sla and sla.date() == today:
                        pr, note = P_TODAY, "Due today"
                    elif ap:
                        pr, note = P_APPT, "Appointment today"
                    else:
                        pr, note = P_NORMAL, ""
                    rem_for(t.get("agent_id"), t.get("verifier", "")).tasks.append(
                        Task(org, f.get("file_no", ""), t.get("id"), t.get("type", ""), pr, note, applicant,
                             status=STATUS_NAME.get(st, ""), status_code=st, type_code=t.get("type_code", ""),
                             comment=(t.get("comment") or "").strip(), appt=ap["time"] if ap else None,
                             appt_type=(ap or {}).get("type", ""), sla=sla, designation=desig))
    if round_key in BS_ROUNDS:
        for r in bs_pending or []:
            if not getattr(r, "collected", False) or r.office or (r.courier or {}).get("no") or (r.bank_received or {}).get("at"):
                continue
            online = (getattr(r, "bs_type", "") or "").lower() == "online"
            if online and getattr(r, "bank_submitted", None):
                continue
            rem = rem_for(r.verifier_id, r.verifier)
            if all(b.trip_id != r.trip_id for b in rem.bs_due):
                rem.bs_due.append(BSDue(r.trip_id, r.file_no, r.bank or r.bank_written, r.applicant,
                                        getattr(r, "finished", None), online))
    out = [r for r in by.values() if r.tasks or r.bs_due]
    for r in out:
        r.tasks.sort(key=lambda t: (t.priority, 0 if t.status_code == 4 else 1, t.appt or datetime.max, t.trip_id or 0))
    out.sort(key=lambda r: (r.priority, -len(r.tasks), r.verifier))
    return out


# ============================================================================================ the WhatsApp text
GREETING = "আসসালামু আলাইকুম"
BN_NUM = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")
WEEKDAY_BN = ["সোমবার", "মঙ্গলবার", "বুধবার", "বৃহস্পতিবার", "শুক্রবার", "শনিবার", "রবিবার"]
OPTIONS = {   # message part -> the three answers
    "T": ("যাচ্ছি / কাজ চলছে", "Finish করেছি", "সমস্যা আছে"),
    "B": ("আজ জমা দেব", "জমা দিয়েছি", "সমস্যা আছে"),
}
# The words the link writes for the verifier.  Plain English letters on purpose: a link with Bangla letters shows on the phone as
# a long %E0%A6… line (3 of them per message); "Joma diyechi #VB-1118-1pm-3-B2" stays one short readable line.
REPLY_WORDS = {"T": ("Jacchi", "Finish korechi", "Somossa ache"), "B": ("Aaj joma dibo", "Joma diyechi", "Somossa ache")}


def bn(n) -> str:
    return str(n).translate(BN_NUM)


def _t12(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def next_working_day(d: date, holidays: set | None = None) -> date:
    holidays = holidays or set()
    d = d + timedelta(days=1)
    while d.weekday() in (4, 5) or d in holidays:
        d += timedelta(days=1)
    return d


def report_due(t: Task, today: date, holidays: set | None = None) -> datetime | None:
    """When the report is due: an appointment -> the next working day after it, 5:59 PM (the SLA rule);
    otherwise the file's SLA date."""
    if t.appt:
        return datetime.combine(next_working_day(t.appt.date(), holidays), time(17, 59))
    return t.sla


def _sla_line(t: Task, today: date, holidays: set | None) -> str:
    due = report_due(t, today, holidays)
    if not due:
        return ""
    if due.date() < today:
        days = (today - due.date()).days
        return f"SLA: ❌ পার হয়ে গেছে ({bn(days)} দিন)"
    if due.date() == today:
        return "SLA: ⚠ আজ 5:59 PM পর্যন্ত"
    return f"SLA: {WEEKDAY_BN[due.weekday()]} {due:%d/%m}, 5:59 PM পর্যন্ত"


def item_code(day: date, round_key: str, idx: int) -> str:
    return f"VB-{day:%m%d}-{round_key}-{idx}"


def tap_links(own_number: str, code: str, part: str) -> list[str]:
    """Three wa.me links: tapping one writes the answer (with the code) in the verifier's chat with us; he presses Send."""
    out = []
    for n, label in enumerate(OPTIONS[part], 1):
        text = f"{REPLY_WORDS[part][n - 1]} #{code}-{part}{n}"
        if own_number:
            out.append(f"👉 {label}: https://wa.me/{own_number}?text={quote(text)}")
        else:
            out.append(f"{n} = {label}")
    return out


def _trip_block(n: int, t: Task, today: date, holidays: set | None, short: bool = False) -> list[str]:
    head = f"*{n}) Trip ID {t.trip_id} · {t.type_label} · {t.status}*" if t.status else f"*{n}) Trip ID {t.trip_id} · {t.type_label}*"
    lines = [head, f"File No: {t.file_no}" + (f" · Applicant: {t.applicant}" if t.applicant else "")]
    if short:
        if t.appt:
            lines[-1] += f" · আজ {_t12(t.appt)}"
        return lines
    if t.appt:
        lines.append(f"Appointment: আজ {_t12(t.appt)}" + (f" ({t.appt_type})" if t.appt_type else ""))
    if t.comment:
        lines.append(("Hold reason: " if t.status_code == 4 else "Comment: ") + t.comment[:120])
    lines.append("করণীয়: " + TODO.get(t.kind, TODO["doc"]))
    sl = _sla_line(t, today, holidays)
    if sl:
        lines.append(sl)
    return lines


def message(rem: Reminder, round_key: str, today: date | None = None, idx: int = 0, own_number: str = "",
            holidays: set | None = None) -> str:
    today = today or date.today()
    kind = ROUND_KIND.get(round_key, "open")
    code = item_code(today, round_key, idx)
    name = rem.verifier if rem.verifier and rem.verifier != "?" else ""
    L = [f"{GREETING}" + (f", {name}" if name else "")]
    trips = rem.tasks[:MAX_TRIPS]
    more = len(rem.tasks) - len(trips)
    if kind == "appt" and rem.tasks:
        L.append(f"*আজ আপনার Appointment: {bn(len(rem.tasks))}টি*")
        for n, t in enumerate(trips, 1):
            L.append("")
            L += _trip_block(n, t, today, holidays)
    elif kind == "appt_left" and rem.tasks:
        if rem.thanks:
            done = ", ".join(f"Trip ID {t.trip_id} ({t.type_label})" for t in rem.thanks[:3])
            L.append(f"আজ আপনি দারুণ কাজ করছেন — {done} Finish হয়েছে, ধন্যবাদ! 🌟")
        else:
            L.append("আজকের কাজের জন্য ধন্যবাদ! 🌟")
        L.append("")
        L.append(f"আজকের Appointment-এর মধ্যে আর *{bn(len(rem.tasks))}টি* বাকি:")
        for n, t in enumerate(trips, 1):
            L.append("")
            L += _trip_block(n, t, today, holidays, short=True)
        L.append("")
        L.append("আর একটু চেষ্টা করলেই আজকের সব কাজ শেষ 💪 কোনো সমস্যা হলে সাথে সাথে জানাবেন — আমরা পাশে আছি।")
    elif rem.tasks:
        L.append(f"ড্যাশবোর্ডে আপনার *{bn(len(rem.tasks))}টি ট্রিপ* এখনো খোলা।")
        hold = [t for t in trips if t.status_code == 4]
        going = [t for t in trips if t.status_code != 4]
        n = 0
        if hold:
            L.append("")
            L.append(f"⛔ *HOLD — {bn(sum(1 for t in rem.tasks if t.status_code == 4))}টি*")
            L.append("Hold-এর সঠিক কারণ লিখে Update করুন, কাজ হলে Remarks দিয়ে Trip Finish করুন। Hold-এ থাকলে SLA ভাঙছে।")
            for t in hold:
                n += 1
                L.append("")
                L += _trip_block(n, t, today, holidays)
        if going:
            L.append("")
            L.append(f"▶ *ON GOING — {bn(sum(1 for t in rem.tasks if t.status_code != 4))}টি*")
            for t in going:
                n += 1
                L.append("")
                L += _trip_block(n, t, today, holidays)
    if more > 0:
        L.append("")
        L.append(f"আরও {bn(more)}টি ট্রিপ — ড্যাশবোর্ডে দেখুন।")
    if rem.tasks:
        L.append("")
        L.append("উত্তর দিন (চাপ দিন, তারপর Send):" if own_number else "উত্তর দিন:")
        L += tap_links(own_number, code, "T")
    if rem.bs_due:
        L.append("")
        off = [b for b in rem.bs_due if not b.online]
        onl = [b for b in rem.bs_due if b.online]
        if off:
            L.append(f"🏦 *আপনার সংগ্রহ করা {bn(len(off))}টি Bank Statement এখনো অফিসে জমা হয়নি:*")
            for b in off[:MAX_TRIPS]:
                L.append(f"• Trip ID {b.trip_id}" + (f" · {b.bank}" if b.bank else ""))
                L.append(f"  File No: {b.file_no}" + (f" · Collected: {b.collected:%d/%m}" if b.collected else ""))
            L.append("অনুগ্রহ করে hard copy অফিসে জমা দিন, যাতে সময়মতো ব্যাংকে পাঠানো যায়।")
        if onl:
            L.append(f"🏦 *Online Bank Statement — {bn(len(onl))}টি ব্যাংকে জমা দিন:*")
            for b in onl[:MAX_TRIPS]:
                L.append(f"• Trip ID {b.trip_id}" + (f" · {b.bank}" if b.bank else "") + f" · File No: {b.file_no}")
            L.append("জমা দিয়ে জমার স্লিপের ছবি এখানে পাঠাবেন।")
        L.append("")
        L.append("BS-এর উত্তর (চাপ দিন, তারপর Send):" if own_number else "BS-এর উত্তর:")
        L += tap_links(own_number, code, "B")
    return "\n".join(L)


def is_own_text(text: str) -> bool:
    """True when a 'reply' is really our own reminder shown back by WhatsApp (its last-message preview)."""
    t = (text or "").strip()
    return t.startswith(GREETING) and any(k in t for k in ("Trip ID", "ট্রিপ", "Appointment", "Bank Statement", "উত্তর দিন", "File No",
                                                           "SLA", "চলমান", "File:"))


# ============================================================================================ the voice text (Pradeep)
_BN_WORD = dict(zip("0123456789", ["শূন্য", "এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়", "সাত", "আট", "নয়"]))
_HOUR = ["বারোটা", "একটা", "দুইটা", "তিনটা", "চারটা", "পাঁচটা", "ছয়টা", "সাতটা", "আটটা", "নয়টা", "দশটা", "এগারোটা"]
_NUM_WORD = ["শূন্য", "একটি", "দুটি", "তিনটি", "চারটি", "পাঁচটি", "ছয়টি", "সাতটি", "আটটি", "নয়টি", "দশটি"]
_MIN = {15: "সোয়া", 30: "সাড়ে"}
_BN_1_59 = ("শূন্য এক দুই তিন চার পাঁচ ছয় সাত আট নয় দশ এগারো বারো তেরো চৌদ্দ পনেরো ষোল সতেরো আঠারো উনিশ বিশ একুশ বাইশ তেইশ চব্বিশ "
            "পঁচিশ ছাব্বিশ সাতাশ আঠাশ ঊনত্রিশ ত্রিশ একত্রিশ বত্রিশ তেত্রিশ চৌত্রিশ পঁয়ত্রিশ ছত্রিশ সাঁইত্রিশ আটত্রিশ ঊনচল্লিশ চল্লিশ "
            "একচল্লিশ বিয়াল্লিশ তেতাল্লিশ চুয়াল্লিশ পঁয়তাল্লিশ ছেচল্লিশ সাতচল্লিশ আটচল্লিশ ঊনপঞ্চাশ পঞ্চাশ একান্ন বাহান্ন তিপ্পান্ন "
            "চুয়ান্ন পঞ্চান্ন ছাপ্পান্ন সাতান্ন আটান্ন ঊনষাট").split()
_ORD = ["প্রথমটি", "দ্বিতীয়টি", "তৃতীয়টি", "চতুর্থটি", "পঞ্চমটি", "ষষ্ঠটি", "সপ্তমটি", "অষ্টমটি"]
_MONTH = ["জানুয়ারি", "ফেব্রুয়ারি", "মার্চ", "এপ্রিল", "মে", "জুন", "জুলাই", "আগস্ট", "সেপ্টেম্বর", "অক্টোবর", "নভেম্বর", "ডিসেম্বর"]
_DAY = ["", "এক", "দুই", "তিন", "চার", "পাঁচ", "ছয়", "সাত", "আট", "নয়", "দশ", "এগারো", "বারো", "তেরো", "চৌদ্দ", "পনেরো", "ষোল", "সতেরো",
        "আঠারো", "উনিশে", "বিশে", "একুশে", "বাইশে", "তেইশে", "চব্বিশে", "পঁচিশে", "ছাব্বিশে", "সাতাশে", "আঠাশে", "ঊনত্রিশে", "ত্রিশে",
        "একত্রিশে"]
KIND_SPOKEN = {"house": "বাসা যাচাই", "office": "অফিস যাচাই", "bank": "bank statement", "pg_house": "গ্যারান্টরের বাসা",
               "pg_office": "গ্যারান্টরের অফিস", "loi": "এল, ও, আই, যাচাই", "chamber": "chamber যাচাই", "rental": "rental যাচাই",
               "tuition": "tuition যাচাই", "car": "car quotation যাচাই", "pec": "experience certificate যাচাই",
               "sign_pg": "গ্যারান্টরের স্বাক্ষর", "sign_app": "আবেদনকারীর স্বাক্ষর", "payslip": "pay slip যাচাই", "doc": "ডকুমেন্ট যাচাই"}
TODO_SPOKEN = {"loi": "অনুগ্রহ করে signatory-র স্বাক্ষর, সিল এবং visiting card সংগ্রহ করবেন।",
               "chamber": "চেম্বার পরিদর্শন করে chamber report form পূরণ করে submit করবেন।",
               "rental": "rental report form পূরণ করে submit করবেন।",
               "bank": "hard copy সংগ্রহ করবেন।",
               "pg_house": "গ্যারান্টরের স্বাক্ষর নিতে হবে।", "pg_office": "গ্যারান্টরের স্বাক্ষর নিতে হবে।"}


def say_digits(n) -> str:
    return ", ".join(_BN_WORD[c] for c in str(n) if c.isdigit())


def say_count(n: int) -> str:
    return _NUM_WORD[n] if 0 <= n < len(_NUM_WORD) else bn(n) + "টি"


def say_time(dt: datetime) -> str:
    h, m = dt.hour, dt.minute
    part = "ভোর" if h < 6 else "সকাল" if h < 12 else "দুপুর" if h < 15 else "বিকেল" if h < 18 else "সন্ধ্যা" if h < 20 else "রাত"
    hh = _HOUR[h % 12]
    if m == 0:
        return f"{part} {hh}"
    if m in _MIN:
        return f"{part} {_MIN[m]} {hh}"
    if m == 45:
        return f"{part} পৌনে {_HOUR[(h + 1) % 12]}"
    return f"{part} {hh} {_BN_1_59[m]} মিনিট"


def say_date(d: date) -> str:
    return f"{WEEKDAY_BN[d.weekday()]}, {_DAY[d.day]} {_MONTH[d.month - 1]}"


def voice_text(rem: Reminder, round_key: str, today: date | None = None, holidays: set | None = None) -> str:
    today = today or date.today()
    kind = ROUND_KIND.get(round_key, "open")
    first = (rem.verifier or "").split()[0] if rem.verifier and rem.verifier != "?" else ""
    name = translit(first) if first.lower() not in ("md", "md.", "mohammad", "mohammed") else translit(" ".join(rem.verifier.split()[:2]))
    out = [f"আসসালামু আলাইকুম{', ' + name + ' ভাই' if name else ''}।"]
    trips = rem.tasks[:5]

    def one(n: int, t: Task, full: bool = True) -> str:
        s = f"{_ORD[n] if n < len(_ORD) else ''}। ট্রিপ আইডি: {say_digits(t.trip_id)}।"
        if t.applicant:
            s += f" আবেদনকারী: {translit(t.applicant)}।"
        s += f" কাজ: {KIND_SPOKEN.get(t.kind, 'যাচাই')}।"
        if t.appt:
            s += f" সময়: {say_time(t.appt)}।"
        if full and t.kind in TODO_SPOKEN:
            s += " " + TODO_SPOKEN[t.kind]
        return s

    if kind == "appt" and rem.tasks:
        out.append(f"আজ আপনার {say_count(len(rem.tasks))} appointment নির্ধারিত আছে।")
        out += [one(i, t) for i, t in enumerate(trips)]
        dues = [report_due(t, today, holidays) for t in trips if report_due(t, today, holidays)]
        if dues:
            d = min(dues)
            out.append(f"এই কাজগুলোর report জমার শেষ সময় {say_date(d.date())}, বিকেল পাঁচটা ঊনষাট মিনিট। এর পরে জমা হলে, S, L, A, ভঙ্গ হবে। "
                       "অনুগ্রহ করে আজকের মধ্যেই কাজগুলো সম্পন্ন করুন।")
    elif kind == "appt_left" and rem.tasks:
        out.append("আজ আপনি খুব ভালো কাজ করছেন, সে জন্য আপনাকে আন্তরিক ধন্যবাদ।")
        out.append(f"আজকের appointment-এর মধ্যে আর {say_count(len(rem.tasks))} বাকি আছে।")
        out += [one(i, t, full=False) for i, t in enumerate(trips)]
        out.append("আর একটু চেষ্টা করলেই আজকের সব কাজ সম্পন্ন হবে। কোনো সমস্যা হলে সঙ্গে সঙ্গে জানাবেন, আমরা আপনার পাশে আছি।")
    elif rem.tasks:
        out.append(f"Dashboard অনুযায়ী আপনার {say_count(len(rem.tasks))} trip এখনো খোলা আছে।")
        hold = [t for t in trips if t.status_code == 4]
        going = [t for t in trips if t.status_code != 4]
        i = 0
        if hold:
            out.append(f"Hold অবস্থায় আছে {say_count(len(hold))}।")
            for t in hold:
                out.append(one(i, t)); i += 1
            out.append("অনুগ্রহ করে Hold-এর সঠিক কারণ লিখে update করুন। কাজ সম্পন্ন হলে remarks লিখে trip শেষ করুন। "
                       "Hold অবস্থায় থাকলে, S, L, A, ভঙ্গ হচ্ছে এবং মূল্যবান সময় নষ্ট হচ্ছে।")
        if going:
            out.append(f"চলমান আছে {say_count(len(going))}।")
            for t in going:
                s = one(i, t); i += 1
                due = report_due(t, today, holidays)
                if due:
                    s += " শেষ সময় আজ বিকেল পাঁচটা ঊনষাট মিনিট।" if due.date() == today else \
                         (" S, L, A, পার হয়ে গেছে।" if due.date() < today else f" শেষ সময় {WEEKDAY_BN[due.weekday()]}।")
                out.append(s)
    if len(rem.tasks) > len(trips):
        out.append(f"আরও {say_count(len(rem.tasks) - len(trips))} trip মেসেজে লেখা আছে।")
    if rem.bs_due:
        off = [b for b in rem.bs_due if not b.online]
        onl = [b for b in rem.bs_due if b.online]
        if off:
            out.append(f"আপনার সংগ্রহ করা {say_count(len(off))} bank statement এখনো অফিসে জমা হয়নি।")
            for b in off[:4]:
                s = f"ট্রিপ আইডি: {say_digits(b.trip_id)}।" + (f" ব্যাংক: {translit(b.bank)}।" if b.bank else "")
                if b.collected:
                    s += f" সংগ্রহ করেছেন {_DAY[b.collected.day].rstrip('ে')} {_MONTH[b.collected.month - 1]}।"
                out.append(s)
            out.append("অনুগ্রহ করে আজকের মধ্যেই hard copy-গুলো অফিসে জমা দিন, যাতে আমরা সময়মতো ব্যাংকে পাঠাতে পারি।")
        if onl:
            out.append(f"Online bank statement আছে {say_count(len(onl))}। ব্যাংকে জমা দিয়ে জমার স্লিপের ছবি পাঠাবেন।")
    out.append("উত্তর দিতে মেসেজের নিচের লিংকে চাপ দিয়ে Send করুন। ধন্যবাদ।")
    return "\n".join(out)


# English (dashboard) names -> Bangla letters, for the voice.  Common names from the dashboard first, then letter rules.
_NAMES = {
    "md": "মোহাম্মদ", "md.": "মোহাম্মদ", "mohammad": "মোহাম্মদ", "mohammed": "মোহাম্মদ", "muhammad": "মুহাম্মদ", "mst": "মোসাম্মৎ",
    "mst.": "মোসাম্মৎ", "most": "মোসাম্মৎ", "most.": "মোসাম্মৎ", "dr": "ডাক্তার", "dr.": "ডাক্তার", "sk": "শেখ", "sk.": "শেখ",
    "abdul": "আব্দুল", "abdur": "আব্দুর", "abu": "আবু", "ahmed": "আহমেদ", "ahmad": "আহমদ", "akter": "আক্তার", "akhter": "আক্তার",
    "aktar": "আক্তার", "alam": "আলম", "ali": "আলী", "amin": "আমিন", "anwar": "আনোয়ার", "ashik": "আশিক", "begum": "বেগম",
    "chowdhury": "চৌধুরী", "das": "দাস", "hasan": "হাসান", "hassan": "হাসান", "hossain": "হোসেন", "hossen": "হোসেন", "islam": "ইসলাম",
    "jahan": "জাহান", "kabir": "কবির", "karim": "করিম", "khan": "খান", "khatun": "খাতুন", "kumar": "কুমার", "mahmud": "মাহমুদ",
    "mamun": "মামুন", "mandal": "মণ্ডল", "mondal": "মণ্ডল", "mia": "মিয়া", "miah": "মিয়া", "mollah": "মোল্লা", "molla": "মোল্লা",
    "nasrin": "নাসরিন", "nur": "নূর", "rahman": "রহমান", "rahim": "রহিম", "rana": "রানা", "rashed": "রাশেদ", "roy": "রায়",
    "saha": "সাহা", "sarkar": "সরকার", "shahariar": "শাহরিয়ার", "shahriar": "শাহরিয়ার", "sheikh": "শেখ", "sultana": "সুলতানা",
    "sumon": "সুমন", "talukder": "তালুকদার", "uddin": "উদ্দিন", "ullah": "উল্লাহ", "zaman": "জামান", "jaman": "জামান",
    "bank": "ব্যাংক", "plc": "পি এল সি", "limited": "লিমিটেড", "ltd": "লিমিটেড", "brac": "ব্র্যাক", "dutch": "ডাচ", "bangla": "বাংলা",
    "sonali": "সোনালী", "janata": "জনতা", "agrani": "অগ্রণী", "rupali": "রূপালী", "pubali": "পূবালী", "uttara": "উত্তরা",
    "standard": "স্ট্যান্ডার্ড", "chartered": "চার্টার্ড", "city": "সিটি", "eastern": "ইস্টার্ন", "prime": "প্রাইম",
    "mutual": "মিউচুয়াল", "trust": "ট্রাস্ট", "one": "ওয়ান", "southeast": "সাউথইস্ট", "jamuna": "যমুনা", "mercantile": "মার্কেন্টাইল",
    "united": "ইউনাইটেড", "commercial": "কমার্শিয়াল", "asia": "এশিয়া", "islami": "ইসলামী", "bangladesh": "বাংলাদেশ",
    "national": "ন্যাশনাল", "ific": "আই এফ আই সি", "ncc": "এন সি সি", "nrb": "এন আর বি", "nrbc": "এন আর বি সি", "ab": "এবি",
    "dhaka": "ঢাকা", "omar": "ওমর", "faruk": "ফারুক", "faruque": "ফারুক", "tarek": "তারেক", "esmail": "ইসমাইল", "ismail": "ইসমাইল",
    "ratan": "রতন", "habiganj": "হবিগঞ্জ", "habignj": "হবিগঞ্জ", "sylhet": "সিলেট", "ctg": "চট্টগ্রাম", "gazipur": "গাজীপুর",
    "faridpur": "ফরিদপুর", "pabna": "পাবনা", "chadpur": "চাঁদপুর", "chandpur": "চাঁদপুর", "kawsar": "কাওসার", "rimon": "রিমন",
    "kamrul": "কামরুল", "sujon": "সুজন", "sahel": "সাহেল", "ratul": "রাতুল", "tanvir": "তানভীর", "rashed": "রাশেদ", "jitu": "জিতু", "al-arafah": "আল-আরাফাহ", "arafah": "আরাফাহ", "al": "আল", "exim": "এক্সিম", "premier": "প্রিমিয়ার",
    "shahjalal": "শাহজালাল", "social": "সোশ্যাল", "first": "ফার্স্ট", "security": "সিকিউরিটি", "midland": "মিডল্যান্ড",
    "modhumoti": "মধুমতি", "meghna": "মেঘনা", "padma": "পদ্মা", "bengal": "বেঙ্গল", "community": "কমিউনিটি", "global": "গ্লোবাল",
}
_PAIRS = [("sh", "শ"), ("ch", "চ"), ("kh", "খ"), ("gh", "ঘ"), ("th", "থ"), ("dh", "ধ"), ("ph", "ফ"), ("bh", "ভ"), ("jh", "ঝ"),
          ("ng", "ং"), ("oo", "ু"), ("ee", "ী"), ("ou", "ৌ"), ("oi", "ৈ")]
_CONS = {"b": "ব", "c": "ক", "d": "দ", "f": "ফ", "g": "গ", "h": "হ", "j": "জ", "k": "ক", "l": "ল", "m": "ম", "n": "ন", "p": "প",
         "q": "ক", "r": "র", "s": "স", "t": "ত", "v": "ভ", "w": "ও", "x": "ক্স", "y": "য়", "z": "জ"}
_VOW_INIT = {"a": "আ", "e": "এ", "i": "ই", "o": "ও", "u": "উ"}
_VOW_SIGN = {"a": "া", "e": "ে", "i": "ি", "o": "ো", "u": "ু"}


_LETTER = dict(zip("abcdefghijklmnopqrstuvwxyz", "এ বি সি ডি ই এফ জি এইচ আই জে কে এল এম এন ও পি কিউ আর এস টি ইউ ভি ডাবলিউ এক্স ওয়াই জেড".split()))


def _word(w: str) -> str:
    lw = w.lower().strip(".,")
    if lw in _NAMES:
        return _NAMES[lw]
    if "." in lw or "-" in lw:                                       # K.M. / Dutch-Bangla
        parts = [p for p in re.split(r"[.\-]", lw) if p]
        return " ".join(_word(p) if len(p) > 1 else _LETTER.get(p, p) for p in parts)
    if w.isupper() and len(lw) <= 3 and lw not in ("ali", "abu", "nur", "roy", "das", "mia"):
        return " ".join(_LETTER.get(c, c) for c in lw)              # CTG -> সি টি জি
    if not lw or not lw.isalpha():
        return w
    out, i, prev_cons = "", 0, False
    while i < len(lw):
        two = lw[i:i + 2]
        hit = next((b for a, b in _PAIRS if two == a), None)
        if hit and two not in ("oo", "ee", "ou", "oi"):
            out += hit; prev_cons = True; i += 2; continue
        if hit:
            out += (hit if prev_cons else {"oo": "উ", "ee": "ঈ", "ou": "ঔ", "oi": "ঐ"}[two]); prev_cons = False; i += 2; continue
        ch = lw[i]
        if ch in _VOW_SIGN:
            if prev_cons:
                out += _VOW_SIGN[ch]
            else:
                out += _VOW_INIT[ch]
            prev_cons = False
        else:
            c = _CONS.get(ch, "")
            if prev_cons and i > 0 and lw[i - 1] == ch and c:
                out += "্" + c                                        # nn -> ন্ন, ll -> ল্ল
            else:
                out += c
            prev_cons = True
        i += 1
    return out


def translit(text: str) -> str:
    """Dashboard (English) name -> Bangla letters for the voice.  Already-Bangla text is kept."""
    if not text or re.search(r"[ঀ-৿]", text):
        return text or ""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text.strip())          # MdRatanIslam -> Md Ratan Islam
    return " ".join(_word(w) for w in re.split(r"\s+", text) if w)


# ============================================================================================ replies
GOING, DONE, PROBLEM, OTHER = "going", "done", "problem", "other"
WILL_SUBMIT, SUBMITTED = "will_submit", "submitted"
REPLY_TEXT = {GOING: "যাচ্ছি / কাজ চলছে", DONE: "Finish করেছি", PROBLEM: "সমস্যা আছে", OTHER: "অন্য উত্তর",
              WILL_SUBMIT: "আজ BS জমা দেবে", SUBMITTED: "BS জমা দিয়েছে", "note": "কারণ লিখেছে", "photo": "স্লিপের ছবি দিয়েছে"}
CODE_KIND = {"T1": GOING, "T2": DONE, "T3": PROBLEM, "B1": WILL_SUBMIT, "B2": SUBMITTED, "B3": PROBLEM}
_CODE = re.compile(r"#?\s*(VB-\d{4}-[0-9a-z]+-\d+)-([TB][123])", re.I)
FOLLOW_PHOTO = "ধন্যবাদ! অনুগ্রহ করে জমার স্লিপের ছবি এখানে পাঠান। 📷"
FOLLOW_NOTE = "ঠিক আছে। সমস্যাটি ছোট করে এক লাইনে লিখে পাঠান, আমরা দেখছি।"
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_PROBLEM = re.compile(r"\b(somossa|shomossa|problem|issue|pacchi\s*na|paccina|pai\s*ni|paini|pawa\s*jay\s*ni|off|bondho|bandh|"
                      r"cancel|asbe\s*na|dibe\s*na|refuse|disagree|rajinna|raji\s*na|not\s+available|nai|nei|hocche\s*na|hoy\s*ni|hoini)\b|"
                      r"সমস্যা|পাচ্ছি না|পাইনি|বন্ধ|রাজি না|হচ্ছে না|হয়নি|নেই|নাই")
_DONE = re.compile(r"\b(done|shesh|sesh|complete\w*|finish\w*|submit\w*|kora\s*hoise|korsi|korechi|hoye\s*geche|hoyse|ok\s*done)\b|"
                   r"শেষ|হয়ে গেছে|করেছি|সাবমিট|জমা দিয়েছি")
_GOING = re.compile(r"\b(jacchi|jassi|jabo|jaitesi|jaitasi|going|on\s*the\s*way|ji|jee|ok|okay|thik\s*ache|accha|insha\s*allah|inshallah)\b|"
                    r"যাচ্ছি|যাব|জি|ঠিক আছে|আচ্ছা|ইনশাআল্লাহ")


def parse_code(text: str) -> tuple[str, str] | None:
    """'জমা দিয়েছি #VB-1118-1pm-3-B2' -> ('VB-1118-1pm-3', 'B2')."""
    m = _CODE.search(text or "")
    return (m.group(1).replace("PM", "pm").replace("AM", "am"), m.group(2).upper()) if m else None


def parse_reply(text: str) -> tuple[str, str]:
    """-> (kind, reason).  A tap-link code first, then 1/2/3 (Bangla or English digits), then common words."""
    raw = (text or "").strip()
    pc = parse_code(raw)
    if pc:
        return CODE_KIND[pc[1]], ""
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
    ds = days.setdefault(d, {"rounds": {}, "replies": []})
    if any(is_own_text(r.get("text", "")) for r in ds["replies"]):
        ds["replies"] = [r for r in ds["replies"] if not is_own_text(r.get("text", ""))]
    return ds


def due_round(st: dict, now: datetime | None = None) -> str | None:
    """The latest round whose time has passed today and that has not been prepared yet (catch-up after the PC was off).
    Office days only, until 6:15 PM."""
    now = now or datetime.now()
    if now.time() > OFFICE_END or now.weekday() in (4, 5):
        return None
    ds = day_state(st, now.date())
    passed = [k for k, t in ROUNDS if now.time() >= t]
    if not passed:
        return None
    latest = passed[-1]
    return None if latest in ds["rounds"] else latest


def record_round(st: dict, round_key: str, queue: list[Reminder], now: datetime | None = None, own_number: str = "",
                 holidays: set | None = None) -> list[dict]:
    """Saves the round; returns its items (each with its code, text and the words for the voice)."""
    now = now or datetime.now()
    ds = day_state(st, now.date())
    items = []
    for idx, r in enumerate([q for q in queue if q.has_whatsapp_number], 1):
        code = item_code(now.date(), round_key, idx)
        items.append({"phone": r.phone, "verifier": r.verifier, "vid": r.verifier_id, "priority": r.priority, "code": code,
                      "files": sorted({t.file_no for t in r.tasks} | {b.file_no for b in r.bs_due}),
                      "trips": [t.trip_id for t in r.tasks], "bs_trips": [b.trip_id for b in r.bs_due],
                      "text": message(r, round_key, now.date(), idx, own_number, holidays),
                      "say": voice_text(r, round_key, now.date(), holidays),
                      "voice": f"r_{now:%m%d}_{round_key}_{idx}", "sent": None})
    ds["rounds"][round_key] = {"prepared": now.isoformat(timespec="minutes"), "items": items,
                               "no_whatsapp": [{"verifier": r.verifier, "vid": r.verifier_id, "phone": r.phone}
                                               for r in queue if not r.has_whatsapp_number]}
    return items


NO_WHATSAPP = "__no_whatsapp__"          # sent by the helper when WhatsApp says the number is not on WhatsApp


def find_item(st: dict, code: str) -> dict | None:
    for d in st.get("days", {}).values():
        for rd in d.get("rounds", {}).values():
            for it in rd.get("items", []):
                if it.get("code", "").lower() == code.lower():
                    return it
    return None


def record_reply(st: dict, phone: str, text: str, when: str | None = None) -> dict:
    """Stores one reply.  A tap-link code ties it to its message and trips; "জমা দিয়েছি" asks for the slip photo and
    "সমস্যা" for a short note (st["asks"][phone]); a later plain text answers an open note-ask."""
    if text == NO_WHATSAPP:
        st.setdefault("no_whatsapp", {})[phone] = date.today().isoformat()
        return {"phone": phone, "kind": "no_whatsapp"}
    if is_own_text(text) or text.strip() in (FOLLOW_PHOTO, FOLLOW_NOTE):
        return {"ignored": True}
    ds = day_state(st)
    at = when or datetime.now().isoformat(timespec="minutes")
    asks = st.setdefault("asks", {})
    pc = parse_code(text)
    ask = asks.get(phone)
    if not pc and ask and ask.get("want") == "note" and not ask.get("answered"):
        ask["answered"] = at
        for rp in reversed(ds["replies"]):
            if rp["phone"] == phone and rp.get("code") == ask.get("code") and rp["kind"] == PROBLEM:
                rp["reason"] = text.strip()[:300]
                break
        e = {"phone": phone, "text": text[:500], "kind": "note", "reason": text.strip()[:300], "at": at, "code": ask.get("code")}
        ds["replies"].append(e)
        return e
    kind, reason = parse_reply(text)
    e = {"phone": phone, "text": text[:500], "kind": kind, "reason": reason[:300], "at": at}
    if pc:
        item = find_item(st, pc[0])
        e.update(code=pc[0], part=pc[1][0], trips=(item or {}).get("bs_trips" if pc[1][0] == "B" else "trips", []))
        if kind == SUBMITTED:
            asks[phone] = {"want": "photo", "code": pc[0], "trips": e["trips"], "at": at, "text": FOLLOW_PHOTO, "sent": None}
        elif kind == PROBLEM:
            asks[phone] = {"want": "note", "code": pc[0], "trips": e["trips"], "at": at, "text": FOLLOW_NOTE, "sent": None}
    if not any(x["phone"] == phone and x["text"] == e["text"] for x in ds["replies"]):
        ds["replies"].append(e)
    return e


def open_asks(st: dict) -> list[dict]:
    """Follow-up messages still to send (Naim presses Send) and photo asks still waiting."""
    now = datetime.now()

    def live(a):
        if not a.get("answered"):
            return True                                      # a photo ask stays readable 6 hours after the first slip (more slips)
        return a.get("want") == "photo" and (now - datetime.fromisoformat(a["answered"])).total_seconds() < 6 * 3600
    return [{"phone": p, **a} for p, a in st.get("asks", {}).items() if live(a)]


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
        if rp["kind"] == "note":
            p["reason"] = rp["reason"]
            continue
        p["last"] = rp["kind"]
        if rp["kind"] == PROBLEM and rp.get("reason"):
            p["reason"] = rp["reason"]
    rows = sorted(({**v, "phone": k, "files": sorted(v["files"])} for k, v in people.items()),
                  key=lambda x: (x["last"] != PROBLEM, x["last"] is not None, x["verifier"]))
    return {"rows": rows,
            "sent": sum(r["sent"] for r in rows),
            "replied": sum(1 for r in rows if r["last"]),
            "problems": sum(1 for r in rows if r["last"] == PROBLEM),
            "no_reply": sum(1 for r in rows if r["sent"] and not r["last"])}
