"""Report Summary engine: reads EVERY trip's full remarks / comment / appointment reasons
and writes the tracker-style two lines

    Done-App House, Office, Sign, LOI (Will be signed from head office)
    Due-LOI (Will be signed from head office)

Rules (agreed with the user)
  * Done lists every finished item in the tracker order  App -> Sign -> LOI -> BS -> Co-App -> PG.
    A problem found on an item is written in brackets next to it, in the bank's short wording.
  * Due repeats EVERY problem item with the same bracket (the report shows them in a soft highlight),
    and adds the items that are still pending (with the reason). Nothing wrong at all -> Due-0.
  * Package row uses only the package trips; a Single / Re-CPV / Extra row uses only its own trip.
  * Bank trips are always "BS" (BS1, BS2 ... when a file has several); I/F is written "Insufficient fund".
  * Bracket text is short (about 60 characters) and never carries phone numbers, e-mails or names.

Everything is rule based and offline (no text leaves the computer). The note rules can
be extended without touching code: put a JSON list in ~/.verify_report_builder/summary_rules.json
    [{"pattern": "regex", "note": "short text", "target": "loi" | "trip", "info": false}]
Those rules are tried first ("info": true = a good-news note that is NOT repeated in Due).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from datetime import datetime

from . import config

_I = re.IGNORECASE
_INVIS = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
RULES_FILE = config.SETTINGS_DIR / "summary_rules.json"


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = _INVIS.sub("", str(s)).replace("\r", "\n")
    s = re.sub(r"[ \t ]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


# ---------------------------------------------------------------------------------------
# note rules: (regex, note, target).  target "loi" = about the LOI, "trip" = about the visit itself.
def _r(p: str, note: str, target: str = "trip"):
    return (re.compile(p, _I), note, target)


NOTE_RULES = [
    # ---- good news (kept in Done only) ----
    _r(r"new\s+address[^.\n]{0,40}(?:verif\w*|found|confirm\w*|ok)|(?:verif\w*|found|confirm\w*)[^.\n]{0,25}new\s+address|"
       r"address\s+(?:is\s+)?(?:mis\s?match|different|changed)[^.\n]{0,40}new", "New address found & verified"),
    _r(r"(?<!can\s)(?<!be\s)signed\s+(?:from|by|at)\s+(?:the\s+)?(?:applicant'?s?\s+)?branch|sign\s+by\s+branch\s+manager|"
       r"loi\s+(?:is\s+)?signed\s+from\s+branch", "Signed from branch", "loi"),
    _r(r"(?:loi\s+(?:has\s+been\s+)?|has\s+been\s+)?signed\s+(?:from|by|at)\s+(?:the\s+)?(?:dhaka\s+)?(?:head\s*office|hq|corporate)",
       "Signed from head office", "loi"),
    # ---- LOI ----
    _r(r"forwarding\s+l[ae]t+er", "Need forwarding letter", "loi"),
    _r(r"will\s+be\s+(?:sign|signed|verif\w*)[^.\n]{0,40}(?:hq|head\s*office|corporate|dhaka\s+head)"
       r"|(?:sign\w*|verif\w*)\s+will\s+be[^.\n]{0,25}(?:hq|head\s*office|corporate)"
       r"|loi[^.\n]{0,30}will\s+be\s+(?:verif|sign)\w*[^.\n]{0,25}(?:head|hq|corporate)", "Will be signed from head office", "loi"),
    _r(r"(?:head|corporate|hr|human\s+resource)[^.\n]{0,70}(?:does\s*n[o']?t|do\s*n[o']?t|not|unwilling|refus\w+|disagree\w*|denied)[^.\n]{0,35}"
       r"(?:verif|sign)\w*", "Head office disagree", "loi"),
    _r(r"(?:does\s*n[o']?t|do\s*n[o']?t|not)\s+verif\w*[^.\n]{0,40}(?:pay\s*slip|payslip)|pay\s*slip[^.\n]{0,60}"
       r"(?:not\s+verif|does\s*n[o']?t\s+verif)|only\s+verif\w*\s+(?:the\s+)?salary\s+certificate", "HR verifies salary certificate only", "loi"),
    _r(r"(?:can|could|must|should|will)\s+(?:be\s+)?(?:verif\w*|sign\w*)[^.\n]{0,30}(?:from|by|at|through)\s+"
       r"(?:the\s+)?(?:respective\s+|applicant'?s?\s+)?branch", "Can be verified from branch", "loi"),
    _r(r"(?:verif\w*|sign\w*)[^.\n]{0,25}(?:by|via|through|on)\s+e-?mail|need\s+to\s+verif\w*\s+by\s+(?:e-?)?mail|by\s+e-?mail|"
       r"gmail\s+address", "Need to verify by email", "loi"),
    _r(r"signator\w*[^.\n]{0,50}(?:out\s+of\s+(?:the\s+)?country|abroad|not\s+available|not\s+present|on\s+leave)",
       "Signatory not available", "loi"),
    _r(r"loi\s+not\s+(?:sign\w*|verif\w*)|loi[^.\n]{0,40}(?:could\s+not|couldn'?t|unable)[^.\n]{0,20}verif|"
       r"not\s+verif\w*[^.\n]{0,25}\bloi\b|loi\s+not\s+verify", "LOI not verified", "loi"),
    # ---- bank statement ----
    _r(r"insufficient\s+(?:balance|fund\w*)|low\s+balance|\bi\s*/\s*f\b", "Insufficient fund"),
    _r(r"(?:account|a/?c)\s*(?:no|number)\s*(?:is\s+)?(?:wrong|incorrect|invalid|not\s+found)|account\s+branch\s+number\s+not\s+found",
       "Account no wrong"),
    _r(r"stop\s+by\s+bank|bank\s+(?:has\s+)?(?:instructed|confirmed|informed|said)[^.\n]{0,60}(?:not\s+required|stop|not\s+to)|"
       r"verification\s+is\s+not\s+required", "Stop by bank"),
    _r(r"signature\s+(?:is\s+)?(?:mis\s?match\w*|different|not\s+match\w*)|account\s+signature\s+different|sign\w*\s+mis\s?match|siganture",
       "Signature mismatch"),
    _r(r"seal\s+(?:is\s+)?(?:miss\w+|not|required|different)|without\s+seal|no\s+seal", "Seal missing"),
    # ---- visit / person ----
    _r(r"(?:dis\s?agre\w*|disgaree|refus\w+|not\s+willing|unwilling|not\s+interested|denied|didn'?t\s+agree)", "Disagree to verify"),
    _r(r"(?:out\s+of|outside)\s+(?:our\s+)?(?:cpv\s+)?coverage|outside\s+(?:our\s+)?cpv", "Out of CPV coverage area"),
    _r(r"(?:does\s*n[o']?t|do\s*n[o']?t|did\s*n[o']?t|not)\s+(?:live|stay|resid\w+)\s+(?:in|at|on)\s+(?:the\s+)?(?:file\s+)?"
       r"(?:given|mention\w*|provided)|applicant\s+(?:does\s*n[o']?t|doesn'?t)\s+live|not\s+live\s+here", "Does not live at given address"),
    _r(r"(?:does\s*n[o']?t|do\s*n[o']?t|did\s*n[o']?t|not)\s+(?:sit|work|serve)\s+(?:in|at)\s+(?:the\s+)?(?:given|mention\w*)|"
       r"no\s+(?:visible\s+)?office\s+found|does\s+not\s+have\s+any\s+office", "Does not sit in given office"),
    _r(r"resign\w*|no\s+longer\s+(?:employed|work\w*|serv\w*)|left\s+the\s+(?:job|organi[sz]ation|company|office)|"
       r"not\s+working\s+(?:here|there)", "No longer employed at given office"),
    _r(r"no\s+longer\s+operat\w*|no\s+longer\s+sit\w*", "No longer operates at given address"),
    _r(r"(?:office|chamber|shop|factory|house)\s+(?:was\s+|is\s+)?(?:found\s+)?(?:closed|locked)|chamber\s+(?:is\s+)?not\s+found", "Office closed"),
    _r(r"no\s+tuition|not?\s+have\s+any\s+tuition|does\s*n[o']?t\s+have\s+any\s+tuition", "No tuition scheduled"),
    _r(r"given\s+address\s+(?:is\s+)?(?:wrong|incorrect|invalid)|(?:wrong|incorrect)\s+address|address\s+(?:is\s+)?(?:wrong|incorrect|invalid)",
       "Given address wrong"),
    _r(r"address\s+(?:is\s+)?not\s+found|could\s*n[o']?t\s+(?:find|locate)\s+(?:the\s+)?address|unable\s+to\s+(?:find|locate)",
       "Address not found"),
    _r(r"call\s+not\s+(?:received|picked|answered|recived)|did\s*n[o']?t\s+(?:receive|pick|answer)|not\s+(?:picking|receiving|responding)|"
       r"no\s+response", "Call not received"),
    _r(r"switch\w*\s+off|(?:phone|number|mobile)\s+(?:is\s+)?(?:off|closed)|not\s+reachable|unreachable", "Phone switch off"),
    _r(r"(?:absence|absent)\s+of\s+(?:the\s+)?(?:family|members)|no\s+one\s+(?:was\s+)?(?:at|in)\s+(?:the\s+)?(?:home|house)|"
       r"family\s+members?\s+(?:not|were\s+not)\s+(?:present|available|at\s+home)|out\s+of\s+house",
       "No one at home"),
    _r(r"(?:not|n'?t)\s+well\s+known|(?:neighbo\w+|local\s+residents?)[^.\n]{0,40}(?:don'?t|do\s+not|did\s+not|not)\s+know|"
       r"no\s+contact\s+person|did\s+not\s+know\s+the\s+applicant", "Not known to neighbours/guard"),
    _r(r"(?:sign\w*|signature)\s+(?:is\s+)?(?:miss\w+|not\s+(?:taken|collected|possible|done)|pending|panding)|"
       r"not\s+signed|(?:could\s*n[o']?t|can\s*n?[o']?t|unable\s+to)\s+(?:take|get|collect)\s+(?:the\s+)?(?:\w+\s+){0,2}sign",
       "Signature missing"),
    _r(r"(?:not\s+available|unavailable|not\s+present|absent|on\s+leave|out\s+of\s+(?:station|town|dhaka)|"
       r"very\s+ill|not\s+(?:at|in)\s+(?:the\s+)?(?:office|home|house))", "Not available"),
    _r(r"will\s+(?:be\s+)?available\s+(?:again|on|at|tomorrow|next)|(?:come|visit)\s+(?:again|tomorrow|next)|try\s+again|"
       r"next\s+day|another\s+day|asked\s+to\s+come|will\s+come", "Will try again later"),
    _r(r"bank\s+statement[^.\n]{0,25}not\s+verif\w*", "Statement not verified"),
    _r(r"unable\s+to|could\s*n[o']?t\s+(?:be\s+)?(?:verif\w*|complet\w*)|not\s+possible\s+to\s+verif\w*|"
       r"verification\s+(?:could\s+not|cannot|can'?t)", "Could not verify"),
]
# good-news notes: written in Done only, never repeated in Due
INFO_NOTES = {"New address found & verified", "Signed from branch", "Signed from head office"}

_NEG_FALLBACK = re.compile(
    r"\b(?:not\s+(?:verif\w*|found|available|possible|allowed|signed|provided|match\w*|willing|interested|cooperat\w*|present|"
    r"received|picked|responding|exist\w*|working|available)|n't|unable|cannot|can't|couldn't|refus\w*|wrong|missing|"
    r"mismatch\w*|pending|failed|problem|issue|disagree\w*|denied|never|without\s+(?:the\s+)?(?:applicant|help|assistance)|"
    r"insufficient|no\s+(?:response|one|contact|access)|resign\w*|closed|locked)\b", _I)
# sentences that look negative but are normal verifier remarks - never turned into a note
_NEUTRAL = re.compile(
    r"no\s+visible|not\s+visible|(?:mobile|phone|contact)\s*(?:no\.?|number)?\s*[:\-]?\s*(?:is\s+)?(?:ok|n/?a|not\s+provided|"
    r"not\s+given)|hard\s*copy\s+provided|information\s+ok|address\s+(?:is\s+)?ok|proper\s+address|phone\s*(?:number)?\s*:\s*n/?a|"
    r"no\s+(?:business\s+)?(?:sign\s*board|name\s*plate|holding)|name\s*:|designation\s*:|organi[sz]ation\s*:|"
    r"address\s+(?:is\s+)?mis\s?match|given\s+(?:residence\s+)?address|new\s+address|(?:mobile|phone)\s+(?:number|no)\s+(?:is\s+)?wrong|"
    r"correct\s+(?:mobile\s+)?number|entry\s+restricted|outsiders?\s+(?:are\s+)?not\s+allowed|photograph|remarks\s+update",
    _I)
_INFO_NOT_OK = re.compile(r"information\s+not\s+ok", _I)


def _user_rules():
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        try:
            out.append(_r(item["pattern"], item["note"], item.get("target", "trip")))
        except Exception:
            continue
    return out


def info_notes() -> set:
    """Good-news notes (not repeated in Due): the built-in ones + user rules marked "info": true."""
    out = set(INFO_NOTES)
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        for item in data if isinstance(data, list) else []:
            if item.get("info") and item.get("note"):
                out.add(item["note"])
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------------------
@dataclass
class Item:
    who: str            # "App", "Co-App", "PG", "PG1", "PG2" or "" for documents
    label: str          # "House", "Office", "Sign", "LOI", "BS" ...
    note: str = ""
    pending: bool = False
    rank: int = 2       # 2 finished, 1 still open, 0 canceled / inactive / withdrawn
    reasons: list = field(default_factory=list)   # "please check" reasons carried by this item
    uncertain: bool = False

    def is_problem(self, info: set) -> bool:
        return self.pending or self.rank < 2 or any(p not in info for p in self.note.split("; ") if p)

    def problem_only(self, info: set) -> "Item":
        """Copy for Due: good-news parts of the bracket are dropped, problem parts stay."""
        if self.pending or self.rank < 2:
            return replace(self)
        return replace(self, note="; ".join(p for p in self.note.split("; ") if p and p not in info))


@dataclass
class TripView:
    """What the engine needs from one trip (built by billing.py)."""
    trip: dict
    role: str           # APPLICANT / CO_APPLICANT / GUARANTOR
    who: str            # App / Co-App / PG / PG1 / PG2


@dataclass
class Summary:
    done: str = "0"
    due: str = "0"
    uncertain: bool = False
    reasons: list = field(default_factory=list)
    done_parts: list = field(default_factory=list)   # [(text, style)]  style: ok | note   (for coloured output)
    due_parts: list = field(default_factory=list)

    def text(self) -> str:
        return f"Done-{self.done}\nDue-{self.due}"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" .;,-") for p in parts if p and p.strip(" .;,-")]


_PII = re.compile(r"(?:e-?mail|gmail|contact|phone|mobile|cell)?\s*(?:no\.?|number|address)?\s*[:\-]?\s*[\w.+-]+@[\w-]+(?:\.[\w-]+)+|"
                  r"(?:\+?88)?0?1[3-9][\d\s-]{8,11}|\b\d{9,}\b|(?:signatory\s+)?name\s*[:\-][^.\n]*|(?:contact|phone)\s*[:\-][^.\n]*", _I)


def scrub(s: str) -> str:
    """Remove phone numbers, e-mail addresses and 'Name: ...' parts."""
    return re.sub(r"\s+", " ", _PII.sub("", s or "")).strip(" .,;:-")


def _short(s: str, limit: int = 60) -> str:
    s = scrub(s)
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return (cut or s[:limit]) + "…"


def _doc_name(trip: dict) -> str:
    c = (trip.get("comment") or "")
    t = " ".join([c, trip.get("remarks") or "", trip.get("place_name") or ""])
    code = trip.get("type_code", "")
    if code == "CAR_QUATATION":
        return "Car Quotation"
    if code == "RENTAL":
        return "Rental"
    if code == "DOC_DRCHAMBER":
        return "Chamber"
    if code == "DOC_TUITION":
        return "Tuition"
    cl = c.lower()
    if re.search(r"pay\s*slip", cl) and not re.search(r"\bloi\b|salary\s*cert", cl):
        return "Payslip"
    for rx, name in (
        (r"car\s*(?:quo|qua|quat)", "Car Quotation"), (r"chamber", "Chamber"), (r"rent", "Rental"),
        (r"\bpec\b|experience\s+certificate", "PEC"),
        (r"tuition|tution", "Tuition"), (r"\bloi\b|letter of intro|salary cert|pay\s*slip", "LOI"),
        (r"voucher", "Cash Voucher"), (r"sign|sing", "Sign"), (r"statement|\bbs\b", "BS"),
    ):
        if re.search(rx, cl, _I):
            return name
    for rx, name in (
        (r"car\s*(?:quo|qua|quat)", "Car Quotation"), (r"chamber", "Chamber"), (r"\brent", "Rental"),
        (r"tuition", "Tuition"), (r"\bloi\b|letter of intro|salary cert|pay\s*slip", "LOI"),
        (r"voucher", "Cash Voucher"),
    ):
        if re.search(rx, t, _I):
            return name
    return ""


_SIGN_POS = re.compile(
    r"(?:sign\w*|signature|sing\w*)\s+(?:\w+\s+){0,3}?(?:in\s*front|infront|front\s+(?:of\s+)?me|verif\w*)|"
    r"(?:applicant|grantor|guarantor|guaranntor|pg|co[- ]?applicant)\s+sign\w*\s+(?:in\s*front|infront|front)|"
    r"signed\s+(?:in\s*)?front|sign\s+form\s+signed|signature\s+form\s+signature\s+in\s+front|sign\s+and\s+loi\s+sign",
    _I)
_SIGN_POS2 = re.compile(r"sign\w*\s+(?:collect\w*|taken|done|verified)|collect\w*\s+(?:\w+\s+){0,3}sign\w*\s+(?:from|at|in)|"
                        r"signed\s+(?:\w+\s+){0,4}(?:front|me)", _I)
_SIGN_NEG = re.compile(r"not\s+sign(?:ed|ature)?\b|\bsign(?:ed|ature)?\s+(?:is\s+)?(?:miss\w+|pending|panding|not)\b|"
                       r"loi\s+not\s+sign\w*[^.\n]{0,25}front", _I)
_LOI_POS = re.compile(r"\bloi\b[^.\n]{0,50}(?:sign\w*|verif\w*|varif\w*)|(?:sign\w*|verif\w*)[^.\n]{0,15}\bloi\b", _I)
_LOI_NEG = re.compile(r"loi\s+not\s+(?:sign\w*|verif\w*)[^.\n]{0,40}|not\s+(?:sign\w*|verif\w*)\s+(?:the\s+)?loi|"
                      r"loi[^.\n]{0,20}(?:wasn'?t|was\s+not|couldn'?t|could\s+not)", _I)


def _trip_text(trip: dict) -> tuple[str, str]:
    """(outcome text = remarks (+ appointment reasons while the trip is still open), comment)."""
    rem = clean_text(trip.get("remarks"))
    appts = [] if trip.get("status_code") == 5 else \
        [clean_text(a.get("reason")) for a in (trip.get("appointments") or []) if a.get("reason")]
    outcome = "\n".join([x for x in [rem] + appts if x])
    return outcome, clean_text(trip.get("comment"))


_POSITIVE = re.compile(r"information\s+(?:is\s+)?ok|address\s+(?:is\s+)?ok", _I)


def _notes_for(text_all: str, outcome: str, rules) -> tuple[dict, bool]:
    """-> ({"loi": [...], "trip": [...]}, fallback_used).

    A visit whose verifier wrote "Information ok" is a successful visit: stray negative words in it
    (visiting card not available, applicant was not present ... but signed) are NOT problems, so only
    good-news notes and LOI notes are kept for it. A negative outcome keeps every note.
    """
    found: dict[str, list[str]] = {"loi": [], "trip": []}
    for rx, note, target in rules:
        if rx.search(text_all) and note not in found[target]:
            found[target].append(note)
    positive = bool(_POSITIVE.search(outcome)) and not _INFO_NOT_OK.search(outcome)
    if positive:
        found["trip"] = [n for n in found["trip"] if n in INFO_NOTES]
    if "LOI not verified" in found["loi"] and re.search(
            r"loi\s+(?:was\s+|is\s+)?(?:signed|verified|varified)\s+(?:by\s+(?:the\s+)?signator|in\s*front|infront)|"
            r"verified\s+and\s+returned|loi\s+(?:has\s+been\s+)?verified", text_all, _I) \
            and not re.search(r"dis\s?agre\w*|refus\w+|not\s+verif\w*\s+(?:the\s+)?hard|does\s*n[o']?t\s+verif", text_all, _I):
        found["loi"].remove("LOI not verified")
    if "New address found & verified" in found["trip"] and "Given address wrong" in found["trip"]:
        found["trip"].remove("Given address wrong")
    fallback = False
    # keep the "disagree"/"could not verify" families from piling up with a more specific note
    for generic in ("Could not verify", "Statement not verified"):
        if len(found["trip"]) > 1 and generic in found["trip"]:
            found["trip"].remove(generic)
    if not found["trip"] and not found["loi"] and not positive:
        neg = _INFO_NOT_OK.search(outcome) or None
        sents = [x for x in _sentences(outcome) if _NEG_FALLBACK.search(x) and not _NEUTRAL.search(x)
                 and not re.match(r"information\s+not\s+ok$", x, _I)]
        if sents:
            found["trip"].append(_short(sents[0]))
            fallback = True
        elif neg:
            rest = re.sub(r"information\s+not\s+ok\.?", "", outcome, flags=_I).strip()
            found["trip"].append(_short(rest) if rest else "Information not ok")
            fallback = True
    elif _INFO_NOT_OK.search(outcome) and not found["trip"] and found["loi"]:
        pass
    return found, fallback


_STATUS_TEXT = {1: "Not visited yet", 2: "Not visited yet", 3: "Visit in progress", 4: "On hold",
                6: "Canceled", 7: "Inactive", 8: "Withdrawn"}
FINISHED = 5


def _appt_text(trip: dict) -> str:
    """'Gave appointment on 02-11-2026' from the latest active appointment (else any)."""
    ap = [a for a in (trip.get("appointments") or []) if a.get("time")]
    if not ap:
        return ""
    ap.sort(key=lambda a: (a.get("active") or False, a["time"]))
    t: datetime = ap[-1]["time"]
    return f"Appointment {t:%d-%m-%Y %I:%M %p}"


def analyze(views: list[TripView], submitted: bool, bank_label: str = "BS") -> Summary:
    rules = _user_rules() + NOTE_RULES
    info = info_notes()
    done: list[Item] = []
    due: list[Item] = []                 # items that are still pending (not finished)
    n_bank = 0
    total_bank = sum(1 for v in views if v.trip.get("type_code") == "BANK" and v.trip.get("status_code") not in (6, 7, 8))
    skipped: list[str] = []

    for v in views:
        t = v.trip
        outcome, comment = _trip_text(t)
        text_all = f"{outcome}\n{comment}"
        code = t.get("type_code", "")
        status = t.get("status_code")
        finished = status == FINISHED
        notes, fallback = _notes_for(text_all, outcome, rules)
        who = v.who

        # ---- primary component ----
        if code in ("HOUSE", "GUARANTOR_HOUSE"):
            primary = Item(who, "House")
        elif code in ("OFFICE", "GUARANTOR_OFFICE"):
            primary = Item(who, "Office")
        elif code == "BANK":
            if status not in (6, 7, 8):
                n_bank += 1
            primary = Item("", f"{bank_label}{n_bank}" if total_bank > 1 else bank_label)
        else:
            name = _doc_name(t)
            if name == "Sign":
                primary = Item(who, "Sign")
            else:
                primary = Item("" if name else who, name or "Document")
                if not name:
                    primary.uncertain = True
                    primary.reasons.append("ডকুমেন্টের ধরন চেনা যায়নি (ট্রিপ %s)" % t.get("id"))
        if fallback:
            primary.uncertain = True
            primary.reasons.append("সংক্ষিপ্ত নোট নিয়মে মেলেনি (ট্রিপ %s)" % t.get("id"))
        extra: list[Item] = []

        # ---- sign / LOI mentioned inside a house/office/document remark ----
        if code in ("HOUSE", "GUARANTOR_HOUSE", "OFFICE", "GUARANTOR_OFFICE", "DOCUMENT", "DOC_SERVICE") and finished:
            sign_text = " . ".join(x for x in _sentences(outcome) if not re.search(r"\bloi\b", x, _I))
            if primary.label != "Sign" and (_SIGN_POS.search(sign_text) or _SIGN_POS2.search(sign_text)) and not _SIGN_NEG.search(sign_text):
                extra.append(Item(who, "Sign"))
            elif primary.label != "Sign" and _SIGN_NEG.search(sign_text):
                miss = Item(who, "Sign", note="Signature missing", pending=True, rank=1)
                miss.uncertain = True
                miss.reasons.append(f"ট্রিপ {t.get('id')}: সাইন নেওয়া হয়নি বলে মনে হয়েছে")
                (done if submitted else due).append(miss)
            if primary.label != "LOI" and (_LOI_POS.search(outcome) and not _LOI_NEG.search(outcome)):
                extra.append(Item("", "LOI"))
            elif _LOI_NEG.search(outcome) or notes["loi"]:
                extra.append(Item("", "LOI"))
        loi_notes = notes["loi"]
        trip_notes = notes["trip"]
        # LOI notes belong to the LOI item (the primary one for a LOI document trip)
        for it in [primary] + extra:
            if it.label == "LOI" and loi_notes:
                it.note = "; ".join(loi_notes[:2])
        if primary.label == "LOI" and not primary.note and trip_notes:
            primary.note = "; ".join(trip_notes[:2])
        elif primary.label != "LOI" and trip_notes:
            primary.note = "; ".join(trip_notes[:2])
        if code == "BANK" and finished and re.search(r"bank\s+statement[^.\n]{0,30}not\s+verif", outcome, _I) and not primary.note:
            primary.note = "Statement not verified"

        items = [primary] + extra
        if not finished:
            if status in (6, 7, 8):                      # canceled / inactive / withdrawn: not written in the summary
                skipped.append(f"ট্রিপ {t.get('id')} {_STATUS_TEXT[status]} (রিপোর্ট সারাংশে বাদ)")
                continue
            primary.rank = 1
            reason_bits = []
            if _appt_text(t):
                reason_bits.append(_appt_text(t))
            reason_bits += trip_notes[:2] if not primary.note else [primary.note]
            if not reason_bits:
                reason_bits.append(_STATUS_TEXT.get(status, "Pending"))
            primary.note = "; ".join(dict.fromkeys(reason_bits))
            primary.pending = True
            if submitted:                                  # file is Submitted but this trip never finished: show it, flag it
                primary.uncertain = True
                primary.reasons.append(f"ট্রিপ {t.get('id')} শেষ হয়নি কিন্তু ফাইল Submitted")
                done.append(primary)
            else:
                due.append(primary)
            continue
        done.extend(items)

    done = _merge(done)
    due = _merge(due)
    # a pending trip that was later redone and finished is no longer due
    finished_keys = {(i.who, i.label) for i in done if i.rank == 2}
    due = [i for i in due if (i.who, i.label) not in finished_keys]
    # every problem item of Done is repeated in Due (same wording)
    problems = [i.problem_only(info) for i in done if i.is_problem(info)]
    due = _merge(problems + due)

    uncertain, reasons = bool(skipped), list(skipped)
    for it in done + due:
        if it.uncertain:
            uncertain = True
            reasons.extend(it.reasons)
    reasons = list(dict.fromkeys(reasons))
    s = Summary(done=_render(done) or "0", due=_render(due) or "0", uncertain=uncertain, reasons=reasons,
                done_parts=_parts(done) or [("0", "ok")], due_parts=_parts(due) or [("0", "ok")])
    if not submitted and not due:
        s.due = "Report not yet submitted"
        s.due_parts = [(s.due, "note")]
        s.uncertain = True
        s.reasons.append("সব ট্রিপ শেষ কিন্তু রিপোর্ট Submitted নয়")
    return s


def _merge(items: list[Item]) -> list[Item]:
    """One entry per (who, label). A finished trip beats an open / canceled one; later beats earlier."""
    out: list[Item] = []
    for it in items:
        idx = next((i for i, o in enumerate(out) if o.who == it.who and o.label == it.label), None)
        if idx is None:
            out.append(it)
        elif it.rank >= out[idx].rank:
            out[idx] = it
    return out


_ORDER = ["App", "", "Co-App", "PG", "PG1", "PG2"]            # tracker order: App -> docs (LOI, BS ...) -> Co-App -> PG
_DOC_ORDER = ["LOI", "BS", "BS1", "BS2", "BS3", "BS4", "Chamber", "Rental", "Car Quotation", "PEC", "Payslip", "Tuition"]
_PART_ORDER = {"House": 0, "Office": 1, "Sign": 2}


def _sorted(items: list[Item]) -> list[tuple[Item, str]]:
    """-> [(item, printed label)] in tracker order."""
    groups: dict[str, list[Item]] = {}
    for it in items:
        groups.setdefault(it.who, []).append(it)
    out: list[tuple[Item, str]] = []
    for who in sorted(groups, key=lambda w: _ORDER.index(w) if w in _ORDER else 99):
        if who:
            ordered = sorted(groups[who], key=lambda x: _PART_ORDER.get(x.label, 3))
        else:
            ordered = sorted(groups[who], key=lambda x: _DOC_ORDER.index(x.label) if x.label in _DOC_ORDER else 50)
        for i, it in enumerate(ordered):
            out.append((it, f"{who} {it.label}" if who and i == 0 else it.label))
    return out


def _render(items: list[Item]) -> str:
    return ", ".join(f"{label} ({it.note})" if it.note else label for it, label in _sorted(items))


def _parts(items: list[Item]) -> list[tuple[str, str]]:
    """Same text as _render, split into coloured runs: item names 'ok', bracket notes 'note'."""
    parts: list[tuple[str, str]] = []
    for n, (it, label) in enumerate(_sorted(items)):
        if n:
            parts.append((", ", "ok"))
        parts.append((label, "ok"))
        if it.note:
            parts.append((f" ({it.note})", "note"))
    return parts
