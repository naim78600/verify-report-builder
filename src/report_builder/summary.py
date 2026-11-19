# ######################################################################################################################
# ★★★ REPORT SUMMARY (DONE / DUE) LOGIC OF VERIFY REPORT BUILDER - THIS WHOLE FILE ★★★
#
# Every block of the Done / Due logic is marked "★ DONE/DUE LOGIC" (search for it). Other rules the dashboard's tracker must copy to
# give the same report are marked "◆ DASHBOARD-MATCH LOGIC" (billing.py, report_text.py, activity.py, geo.py, prime_excel.py).
# Reading order for a developer:
#   1. clean_text / xml_safe        - how the remark text is cleaned
#   2. NOTE_RULES / INFO_NOTES      - the words in brackets and what triggers them
#   3. _doc_name                    - what a Document trip is (LOI, Chamber, Rental ...)
#   4. _trip_text / _notes_for      - remarks only, "Information ok", "last statement wins", fallback note
#   5. analyze                      - per trip: Done or Due, notes, Sign / LOI read from other remarks, Inactive rules
#   6. _merge / _beats              - one entry per (person, part)
#   7. _head_office_loi             - "LOI (New trip created for head office verification)" / "(Will be verified from head office)"
#   8. _sorted / _render / _finish  - order, printed text, "Due-0", "Report not yet submitted"
# Which trips go into one report line: billing.refresh_summary (one summary over all folded rows of the file).
# Full explanation: the doc "VRB report logic for the dashboard team (v13)" and docs/TECH_MEMO.md.
# ######################################################################################################################
"""Report Summary engine: reads EVERY trip's full remarks / appointment reasons (never the back-office comment)
and writes the tracker-style two lines

    Done-App House, Office, Sign, LOI (Will be signed from head office)
    Due-LOI (Will be signed from head office)

Rules (agreed with the user)
  * Done / Due follow the verifier's REMARKS (what was found after the work), not the back-office COMMENT (the instruction given
    to the verifier).  The comment is used only to tell what a "Document" trip is about (LOI, payslip, tuition ...).
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
from datetime import datetime, timedelta

from . import config

_I = re.IGNORECASE
_INVIS = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
RULES_FILE = config.SETTINGS_DIR / "summary_rules.json"


_XML_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ufffe\uffff]")


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 1. text cleaning
#   \x19 / curly quote -> apostrophe, forbidden characters dropped, invisible marks removed.
# ==============================================================================================================
def xml_safe(s):
    """Text for an Excel cell: characters XML 1.0 forbids (and C1 controls) are dropped - Excel / Numbers call a file with
    one of them "damaged".  The dashboard sends a right single quote cut to a lone \x19 ("Didn\x19t"): it becomes an apostrophe."""
    if not isinstance(s, str):
        return s
    return _XML_BAD.sub("", s.replace("\x19", "'").replace("\x18", "'"))


_QUOTES = str.maketrans({"\u2019": "'", "\u2018": "'", "\u02bc": "'", "\u0060": "'", "\u00b4": "'", "\u201c": '"', "\u201d": '"'})


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    # The dashboard separates a verifier's sentences with invisible marks ("...in front of me.<LRM><LRM>Loi pending."): dropping them
    # glued the sentences together ("me.Loi") so "signed in front of me" was lost inside a sentence that names the LOI.  After a sentence
    # end they become a space; elsewhere they are simply removed.
    s = _INVIS.sub("", re.sub(r"(?<=[.!?;:])(?:%s)+(?=\S)" % _INVIS.pattern, " ", str(s)))
    s = xml_safe(s).replace("\r", "\n")
    s = s.translate(_QUOTES)                        # curly apostrophes / quotes -> straight ("doesn’t" must match "doesn't")
    s = re.sub(r"[ \t ]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


# ---------------------------------------------------------------------------------------
# note rules: (regex, note, target).  target "loi" = about the LOI, "trip" = about the visit itself.
# "HR payslip will be not verified. HR will verified only salary certificate." = HR verifies the salary certificate only.
_PAYSLIP_ONLY = (r"(?:does\s*n[o']?t|do\s*n[o']?t|not)\s+(?:be\s+)?verif\w*[^.\n]{0,40}(?:pay\s*slip|payslip)|pay\s*slip[^.\n]{0,60}"
                 r"(?:(?:will\s+)?(?:be\s+)?not\s+verif|does\s*n[o']?t\s+verif)|"
                 r"only\s+(?:verif\w*\s+)?(?:the\s+)?salary\s+certificate|verif\w*\s+only\s+(?:the\s+)?salary\s+certificate")
_PAYSLIP_RX = re.compile(_PAYSLIP_ONLY, re.IGNORECASE)
# "Phone number :- Not interested" / "Number: Disagree to give number" / "signatory deny to provide visiting card" describe a contact detail the
# person kept back, not a refusal to verify
# ==============================================================================================================
# ★ DONE/DUE LOGIC: 2a. remarks that are NOT problems
#   a refusal to give a phone number / visiting card is ignored.
# ==============================================================================================================
_CONTACT_REFUSAL = re.compile(
    r"(?:(?:phone|mobile|cell|contact)\s*(?:no\.?|number)?|\bnumber|\bno\.?)\s*[:\-]+\s*(?:not\s+interest\w*|dis\s?agre\w*|deny|denied|refus\w+|unwilling|not\s+willing)"
    r"(?:\s+to\s+(?:give|provid\w*|share|tell)(?:\s+(?:the\s+|his\s+|her\s+)?(?:phone\s+|mobile\s+)?(?:number|no\.?))?)?"
    r"|(?:not\s+interest\w*|dis\s?agre\w*|den(?:y|ied)|refus\w+|not\s+willing|unwilling|did\s*n[o']?t\s+want)\s+to\s+(?:give|provid\w*|share|tell)\s+"
    r"(?:the\s+|his\s+|her\s+|their\s+)?(?:visiting\s+card|phone|mobile|cell|number|name|designation|contact)[^.\n]{0,40}"
    r"|(?:visiting\s+card|name\s+seal)\s+(?:is\s+|was\s+)?(?:not\s+available|unavailable|not\s+given|not\s+provided)", re.IGNORECASE)


def _r(p: str, note: str, target: str = "trip"):
    return (re.compile(p, _I), note, target)


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 2. NOTE RULES - the bracket notes
#   (regex, printed note, target). target 'loi' = a LOI note, 'trip' = about the visit. Tried in order, every
#   match kept, max 2 shown per trip. User rules from ~/.verify_report_builder/summary_rules.json are tried first.
# ==============================================================================================================
NOTE_RULES = [
    # ---- good news (kept in Done only) ----
    _r(r"new\s+address[^.\n]{0,40}(?:verif\w*|found|confirm\w*|ok)|(?:verif\w*|found|confirm\w*)[^.\n]{0,25}new\s+address|"
       r"address\s+(?:is\s+)?(?:mis\s?match|different|changed)[^.\n]{0,40}new", "New address found & verified"),
    _r(r"(?<!can\s)(?<!be\s)signed\s+(?:from|by|at)\s+(?:the\s+)?(?:applicant'?s?\s+)?branch|sign\s+by\s+branch\s+manager|"
       r"loi\s+(?:is\s+)?signed\s+from\s+branch", "Signed from branch", "loi"),
    # v10.0.6: "LOI Signed Dhaka Head Office" (no from / by / at) too - PL-20261115074128799, 17-11-2026
    _r(r"(?:loi\s+(?:has\s+been\s+)?|has\s+been\s+)?(?<!be\s)(?<!not\s)signed\s+(?:(?:from|by|at|in)\s+)?(?:the\s+)?(?:dhaka\s+)?(?:head\s*office|hq|corporate)",
       "Signed from head office", "loi"),
    # v10.0.6: "LOI not signed in front of me as entry restricted. LOI signed by Signatory Name: ..." - signed, but not before the
    # verifier: shown with the LOI (Done only, not a Due), so the bank sees it (PL-20261115074128799)
    _r(r"\bloi\s+(?:was\s+|is\s+|did\s+)?not\s+sign\w*\s+(?:in\s*front|infront)(?=[^\n]{0,200}(?:signed\s+by|signator\w*\s*(?:name|:)))",
       "Not signed in front of me", "loi"),
    # ---- LOI ----
    _r(r"(?:need|want|requir|ask|must|without|bring|provide|send)\w*[^.\n]{0,40}forwarding\s+l[ae]t+er|forwarding\s+l[ae]t+er[^.\n]{0,20}(?:required|needed|not\s+(?:provided|submitted|given|have))",
       "Need forwarding letter", "loi"),
    _r(r"wi?ll?\s+be\s+(?:sign|signed|verif\w*)[^.\n]{0,40}(?:hq|head\s*office|corporate|dhaka\s+head)"
       r"|(?:sign\w*|verif\w*)\s+wi?ll?\s+be[^.\n]{0,25}(?:hq|head\s*office|corporate)"
       r"|loi[^.\n]{0,30}wi?ll?\s+be\s+(?:verif|sign)\w*[^.\n]{0,25}(?:head|hq|corporate)", "Will be signed from head office", "loi"),
    _r(r"(?:head|corporate|hr|human\s+resource)[^.\n]{0,70}(?:does\s*n[o']?t|do\s*n[o']?t|not|unwilling|refus\w+|disagree\w*|denied)[^.\n]{0,35}"
       r"(?:verif|sign)\w*", "Head office disagree", "loi"),
    _r(r"(?:they|hr|head\s*office|accounts?|finance)\s+(?:(?:do|does|did|will)\s*n[o']?t|(?:do|does|did|will)\s+not)\s+verif\w*\s+(?:this|the|it|any|applicant)\b(?!\s+way)(?![^.\n]{0,60}\b(?:hard\s+cop\w*|physical\w*|directly|via\s+e-?mail|by\s+e-?mail)\b)",
       "Head office disagree", "loi"),
    _r(r"\bno\s+one\s+(?:in\s+[^.\n]{0,25}?\s+)?(?:will|can|would)\s+verif\w*", "Head office disagree", "loi"),
    _r(_PAYSLIP_ONLY, "HR verifies salary certificate only", "loi"),
    _r(r"(?:can|could|must|should|will)\s+(?:be\s+)?(?:verif\w*|sign\w*)[^.\n]{0,30}(?:from|by|at|through)\s+"
       r"(?:the\s+)?(?:respective\s+|applicant'?s?\s+|[\w'’-]+\s+){0,2}branch", "Can be verified from branch", "loi"),
    _r(r"(?:dispat?ch|dispach)\b[^.\n]{0,120}\b(?:mail|e-?mail)\b|\b(?:they|will)\s+send\s+(?:the\s+)?verified\s+loi\s+by\s+(?:e-?)?mail", "Submitted for verification", "loi"),
    _r(r"(?:told|asked|requested|advised)\s+(?:me|us)\s+to\s+v[ae]rif\w*[^.\n]{0,25}\bby\s+mail\b|\b(?:do|does)\s+so\s+(?:by|via|through)\s+e-?mail|(?<!send\s)(?<!sends\s)(?<!sent\s)(?:verif\w*|sign\w*)[^.\n]{0,25}(?:by|via|through|on)\s+e-?mail|need\s+to\s+verif\w*\s+by\s+(?:e-?)?mail|by\s+e-?mail|"
       r"gmail\s+address", "Need to verify by email", "loi"),
    _r(r"signator\w*[^.\n]{0,50}(?:out\s+of\s+(?:the\s+)?country|abroad|not\s+available|not\s+present|on\s+leave)",
       "Signatory not available", "loi"),
    _r(r"\bloi\b[^\n]{0,90}?\bno\s+sign(?:ature)?\s+(?:is\s+)?(?:required|needed)|\bloi\b[^\n]{0,60}?sign(?:ature)?\s+(?:is\s+)?not\s+(?:required|needed)",
       "System generated - no sign required", "loi"),
    _r(r"loi\s+not\s+(?:sign\w*|verif\w*)|loi[^.\n]{0,40}(?:could\s+not|couldn'?t|unable)[^.\n]{0,20}verif|"
       r"\bloi\b[^.\n]{0,40}(?:cannot|can\s*not|can't|will\s+not)\s+(?:be\s+)?(?:v[ae]rif\w*)|could\s*n[o']?t\s+get[^.\n]{0,25}loi\s+verif\w*|"
       r"will\s+not\s+do\s+(?:the\s+)?loi\s+verif\w*|no\s+senior\s+authority[^.\n]{0,30}loi|"
       r"not\s+verif\w*[^.\n]{0,25}\bloi\b|loi\s+not\s+verify", "LOI not verified", "loi"),
    # ---- bank statement ----
    _r(r"insufficient\s+(?:balance|fund\w*)|low\s+balance|\bi\s*/\s*f\b", "Insufficient fund"),
    _r(r"(?:account|a/?c)\s*(?:no|number)\s*(?:is\s+)?(?:wrong|incorrect|invalid|not\s+found)|account\s+branch\s+number\s+not\s+found",
       "Account no wrong"),
    _r(r"stop\s+by\s+bank|bank\s+(?:has\s+)?(?:instructed|confirmed|informed|said)[^.\n]{0,60}(?:not\s+required|stop|not\s+to)|"
       r"verification\s+is\s+not\s+required", "Stop by bank"),
    _r(r"signature\s+(?:is\s+)?(?:mis\s?match\w*|different|not\s+match\w*)|account\s+signature\s+different|sign(?!board|brod|bord|age)\w*\s+mis\s?match|siganture",
       "Signature mismatch"),
    _r(r"seal\s+(?:is\s+)?(?:miss\w+|not|required|different)|without\s+seal|no\s+seal", "Seal missing"),
    # ---- visit / person ----
    _r(r"(?:dis\s?agre\w*|disgaree|refus\w+|not\s+willing|unwilling|not\s+interested|denied|didn'?t\s+agree)", "Disagree to verify"),
    _r(r"(?:out\s+of|outside)\s+(?:our\s+)?(?:cpv\s+)?coverage|outside\s+(?:our\s+)?cpv", "Out of CPV coverage area"),
    _r(r"(?:does\s*n[o']?t|do\s*n[o']?t|did\s*n[o']?t|not)\s+(?:live|lives|stay|stays|resid\w+)\s+(?:(?:in|at|on)\s+)?(?:the\s+)?(?:file\s+|fill\s+)?"
       r"(?:given|mention\w*|provided)|(?:applicant|guarantor|grantor|gurantor|pg)\s+(?:does\s*n[o']?t|doesn'?t|do\s*n[o']?t)\s+live|not\s+live\s+here|"
       r"(?:does\s*n[o']?t|do\s*n[o']?t)\s+(?:usually|normally|always)\s+(?:live|stay)", "Does not live at given address"),
    _r(r"(?:does\s*n[o']?t|do\s*n[o']?t|did\s*n[o']?t|not)\s+(?:sit|work|serve)\s+(?:in|at)\s+(?:the\s+)?(?:given|mention\w*)|"
       r"no\s+(?:visible\s+)?office\s+found|does\s+not\s+have\s+any\s+office|"
       r"(?:does\s*n[o']?t|do\s*n[o']?t)\s+have\s+(?:an?\s+|any\s+)?(?:separate\s+)?(?:office|b[iu]\w{2,9}|chamber|shop)\b[^.\n]{0,30}(?:address|here|there)|"
       r"\bhas\s+no\s+(?:office|b[iu]\w{2,9}|chamber|shop)\b[^.\n]{0,30}(?:address|here|there)|"
       r"\bno\s+(?:visible\s+)?office\s+(?:at|in)\s+(?:the\s+)?(?:given|file|mention\w*|this|provided)|there\s+is\s+no\s+(?:\w+'?s?\s+)?office\b|"
       r"\bnot\s+(?:their|his|her)\s+office|(?:does\s*n[o']?t|do\s*n[o']?t)\s+practi[sc]e\s+(?:at|in)|"
       r"(?:does\s*n[o']?t|do\s*n[o']?t)\s+(?:do|run|have)\s+(?:an?\s+)?(?:office|business|job)\s+(?:at|in)|"
       r"(?:does\s*n[o']?t|do\s*n[o']?t)\s+have\s+(?:an?\s+|any\s+)?(?:separate\s+)?office\b|not\s+currently\s+based\s+at|"
       r"\bno\s+(?:separate\s+)?office\b[^.\n]{0,45}\b(?:was|were|is)\s+found", "Does not sit in given office"),
    _r(r"\bnot\s+found\b[^.\n]{0,60}\b(?:at|in)\s+(?:the\s+)?(?:given|mention\w*|provided)\s+address", "Not found at given address"),
    _r(r"(?:will|would|do|does)\s+not\s+(?:be\s+)?tak\w+\s+(?:the\s+|a\s+|any\s+)?loan|not\s+interested\s+in\s+(?:the\s+|a\s+|any\s+)?loan", "Applicant not taking the loan"),
    _r(r"no\s+transactions?\s+(?:are\s+)?(?:being\s+)?(?:conducted|made|done|found)", "No transactions in account"),
    _r(r"(?:office|business|buissness|organi[sz]ation|company|chamber|shop|factory)\s+(?:was\s+|is\s+|has\s+|have\s+)?(?:been\s+)?"
       r"(?:shift\w*|moved|relocat\w*|vacat\w*)|vacated\s+(?:these|the|this)\s+premises|office\s+shift\w*", "Moved to another address"),
    _r(r"resign\w*|no\s+longer\s+(?:employed|work\w*|serv\w*)|left\s+the\s+(?:job|organi[sz]ation|company|office)|"
       r"not\s+working\s+(?:here|there)|not\s+(?:currently\s+)?employed", "No longer employed at given office"),
    _r(r"no\s+longer\s+operat\w*|no\s+longer\s+sit\w*", "No longer operates at given address"),
    _r(r"(?:office|chamber|shop|factory|house)\s+(?:was\s+|is\s+)?(?:found\s+)?(?:closed|locked)|chamber\s+(?:is\s+)?not\s+found", "Office closed"),
    _r(r"no\s+tuition|not?\s+have\s+any\s+tuition|does\s*n[o']?t\s+have\s+any\s+tuition", "No tuition scheduled"),
    _r(r"given\s+address\s+(?:is\s+)?(?:wrong|incorrect|invalid)|(?:wrong|incorrect)\s+address|address\s+(?:is\s+)?(?:wrong|incorrect|invalid)",
       "Given address wrong"),
    _r(r"address\s+(?:is\s+)?not\s+found|could\s*n[o']?t\s+(?:find|locate)\s+(?:the\s+)?address|unable\s+to\s+(?:find|locate)|can\s*n?'?t\s+(?:find|locate)",
       "Address not found"),
    _r(r"call\s+not\s+(?:received|picked|answered|recived)|did\s*n[o']?t\s+(?:receive|pick|answer|respon\w*)|not\s+(?:picking|receiving|responding)|"
       r"no\s+response", "Call not received"),
    _r(r"switch\w*\s+off|(?:phone|number|mobile)\s+(?:is\s+)?(?:off|closed)|not\s+reachable|unreachable", "Phone switch off"),
    _r(r"(?:absence|absent)\s+of\s+(?:the\s+)?(?:family|members)|no\s+one\s+(?:was\s+)?(?:at|in)\s+(?:the\s+)?(?:home|house)|"
       r"family\s+members?\s+(?:not|were\s+not)\s+(?:present|available|at\s+home)|out\s+of\s+house",
       "No one at home"),
    _r(r"(?:not|n'?t)\s+well\s+known|(?:neighbo\w+|local\s+residents?)[^.\n]{0,40}(?:don'?t|do\s+not|did\s+not|not)\s+know|"
       r"no\s+contact\s+person|did\s+not\s+know\s+the\s+applicant", "Not known to neighbours/guard"),
    _r(r"(?:sign\w*|signature)\s+(?:is\s+)?(?:miss\w+|not\s+(?:taken|collected|possible|done)|pending|panding)|"
       r"not\s+signed|(?:could\s*n[o']?t|can\s*n?[o']?t|unable\s+to|not\s+possible\s+to|failed\s+to)\s+(?:take|get|collect|obtain)\s+(?:the\s+)?(?:\w+'?s?\s+){0,3}sign|"
       r"\bsign(?:ature)?s?\b(?:\s+of\s+(?:the\s+)?[\w'-]+(?:\s+[\w'-]+)?)?\s+(?:could\s*n[o']?t|can\s*n[o']?t|was\s+not|were\s+not)\s+(?:be\s+)?(?:taken|obtained|collected|received|possible)",
       "Signature missing"),
    _r(r"(?:not\s+available|unavailable|not\s+present|absent|on\s+leave|out\s+of\s+(?:station|town|dhaka)|is\s*n'?t\s+available|was\s*n'?t\s+(?:available|present)|will\s+not\s+be\s+available|"
       r"very\s+ill|not\s+(?:at|in)\s+(?:the\s+)?(?:office|home|house))", "Not available"),
    _r(r"will\s+(?:be\s+)?available\s+(?:again|on|at|tomorrow|next)|(?:come|visit)\s+(?:again|tomorrow|next)|try\s+again|"
       r"next\s+day|another\s+day|asked\s+to\s+come|will\s+come", "Will try again later"),
    _r(r"bank\s+statement[^.\n]{0,25}not\s+verif\w*", "Statement not verified"),
    _r(r"unable\s+to|could\s*n[o']?t\s+(?:be\s+)?(?:verif\w*|complet\w*)|not\s+possible\s+to\s+verif\w*|"
       r"verification\s+(?:could\s+not|cannot|can'?t)", "Could not verify"),
]
# good-news notes: written in Done only, never repeated in Due
# ==============================================================================================================
# ★ DONE/DUE LOGIC: 2b. good-news notes
#   shown in Done only, never repeated in Due.
# ==============================================================================================================
INFO_NOTES = {"System generated - no sign required", "New address found & verified", "Signed from branch", "Signed from head office",
              "Not signed in front of me"}

# ==============================================================================================================
# ★ DONE/DUE LOGIC: 2c. fallback note
#   no rule matched: the first negative sentence (about 60 characters) becomes the note.
# ==============================================================================================================
_NEG_FALLBACK = re.compile(
    r"\b(?:not\s+(?:verif\w*|found|available|possible|allowed|signed|provided|match\w*|willing|interested|cooperat\w*|present|"
    r"received|picked|responding|exist\w*|working|available)|n't|unable|cannot|can't|couldn't|refus\w*|wrong|missing|"
    r"mismatch\w*|pending|failed|problem|issue|disagree\w*|denied|never|without\s+(?:the\s+)?(?:applicant|help|assistance)|"
    r"insufficient|no\s+(?:response|one|contact|access)|resign\w*|closed|locked|"
    r"away\s+(?:for|on|from)|expected\s+to\s+return|on\s+leave|abroad|out\s+of\s+(?:the\s+)?(?:country|station|town)|admitted)\b", _I)
# second-tier negative words (contractions such as isn't / wasn't / didn't, shifted, vacated, not employed): only used when the first tier found nothing
_NEG_EXTRA = re.compile(r"\b(?:\w+n't|shift\w*|vacat\w*|not\s+(?:currently\s+)?employed|not\s+(?:their|his|her)\s+office)\b", _I)
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
    inferred: bool = False                        # "LOI" / "Sign" read out of ANOTHER trip's remark (not the trip of that item)
    src: tuple = ()                               # (created_at, id) of the trip the item came from

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
    done_items: list = field(default_factory=list)   # the Items behind the text (apply_later re-checks the Due ones)
    due_items: list = field(default_factory=list)

    def text(self) -> str:
        return f"Done-{self.done}\nDue-{self.due}"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+|\.{2,}", text)
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


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 3. what a Document trip is
#   trip type first (Chamber, Rental, Car Quotation, Tuition), then the COMMENT, then remarks / place.
# ==============================================================================================================
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
        (r"car\s*(?:quo|qua|quat)", "Car Quotation"), (r"chamber", "Chamber"), (r"\brent", "Rental"),      # \b: "different", "current", "parent" are not rent
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
                       r"loi\s+not\s+sign\w*[^.\n]{0,25}front|"
                       # v6 (tracker training): "the applicant's signature could not be collected / obtained", "can not take applicant sign"
                       r"sign(?:ature)?\s+(?:could\s*n[o']?t|can\s*n[o']?t|cannot|was\s*n[o']?t|is\s+not)\s+(?:be\s+)?(?:collect\w*|obtain\w*|taken?|g[eo]t)|"
                       r"(?:can\s*n[o']?t|cannot|could\s*n[o']?t|not\s+possible\s+to|unable\s+to)\s+(?:take|collect|get|obtain)\s+(?:the\s+)?"
                       r"(?:(?:applicant|guarantor|grantor|gurantor|pg|co[- ]?applicant)(?:'s|’s|s)?\s+)?sign", _I)
_LOI_POS = re.compile(r"\bloi\b[^.\n]{0,50}(?:sign\w*|verif\w*|varif\w*)|(?:sign\w*|verif\w*)[^.\n]{0,15}\bloi\b", _I)
_LOI_NEG = re.compile(r"loi\s+not\s+(?:sign\w*|verif\w*)[^.\n]{0,40}|not\s+(?:sign\w*|verif\w*)\s+(?:the\s+)?loi|"
                      r"loi[^.\n]{0,20}(?:wasn'?t|was\s+not|couldn'?t|could\s+not)", _I)


# A sentence that states the work is DONE ("LOI signed by ...", "verification had to be completed through the AGM", "signed in front of me").
# The report follows the LAST update: such a sentence settles what the verifier wrote before it - "Previous signatory not available.
# LOI signed in front of me" is a finished LOI, not a due one.  A sentence that is itself negative / future ("LOI not signed",
# "will be signed from head office", "need forwarding letter") is never a "done" statement.
# ==============================================================================================================
# ★ DONE/DUE LOGIC: 4a. 'done' sentences
#   a sentence saying the LOI / sign was done settles problems written before it (last statement wins).
# ==============================================================================================================
_DONE = re.compile(      # (sing / singed / varified / verifed are the verifiers' usual typos)
    r"\bloi\b[^.\n]{0,25}\b(?:sign(?:ed)?|sing(?:ed)?|verified|varified|verifed|varifed|verifie|varifie|veriffied)\s+(?:by|in\s*front|infront)\b"
    r"|\bloi\b[^.\n]{0,25}\b(?:signed|singed|verified|varified|verifed|varifed|verifie|varifie|veriffied)\b"
    r"|\b(?:sign(?:ed)?|sing(?:ed)?|verified|varified|verifed)\s+(?:in\s*front|infront|by\b|and\s+returned)"
    r"|\b(?:completed|done)\s+(?:through|by|from|at|with)\b"
    r"|\bverification\s+(?:was\s+|has\s+been\s+)?(?:completed|done)\b", _I)
_NOT_DONE = re.compile(
    r"\b(?:can|could|will|would|shall|may|might|must|should)\s+(?:\w+\s+)?(?:v[ae]rif\w*|sign\w*)|\bnot\b(?!\s+(?:in\s*)?front)|n['’]t\b|\bunable\b|\bcannot\b|\bwill\s+be\b|\bcan\s+be\b|\bcould\s+be\b|"
    r"\bto\s+be\s+(?:sign\w*|verif\w*|varif\w*)\b|\bbe\s+(?:signed|verified|varified)\b|\bneed\w*|\bmust\b|\bshould\b|\bwould\b|\bmay\b|\bmight\b|"
    r"\bshall\b|\bif\b|\bwithout\b|\bwill\s+(?:sign|verify)\b|\b(?:want|ask|request|advis|inform|said|stated)\w*", _I)
_HISTORY = re.compile(r"\s*(?:the\s+)?(?:previous|earlier|former)\b", _I)
_LOI_WORD = re.compile(r"\bloi\b|signator\w*|salary\s*cert\w*|letter\s+of\s+intro\w*", _I)


def _done_sentence(s: str) -> bool:
    return bool(_DONE.search(s)) and not _NOT_DONE.search(s)


def _latest_appt_reason(trip: dict) -> list:
    """The reason of the NEWEST appointment only (last update wins): an older "applicant not available, come Monday" is replaced by the
    next appointment's reason, exactly as the running tracker keeps just the latest reason in its Report Summary column."""
    ap = [a for a in (trip.get("appointments") or []) if a.get("reason")]
    if not ap:
        return []
    ap.sort(key=lambda a: (a.get("created_at") or datetime.min, a.get("time") or datetime.min, a.get("id") or 0))
    return [clean_text(ap[-1].get("reason"))]


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 4b. text read = REMARKS only
#   the back-office comment is the instruction, not the result; an open trip adds its newest appointment reason.
# ==============================================================================================================
def _trip_text(trip: dict) -> tuple[str, str]:
    """(outcome text = remarks (+ appointment reasons while the trip is still open), comment)."""
    rem = clean_text(trip.get("remarks"))
    appts = [] if trip.get("status_code") == 5 else _latest_appt_reason(trip)
    outcome = _CONTACT_REFUSAL.sub(" ", "\n".join([x for x in [rem] + appts if x]))
    return outcome, clean_text(trip.get("comment"))


_NOT_INFRONT = re.compile(r"\bloi\s+(?:was\s+|is\s+|did\s+)?not\s+sign\w*\s+(?:in\s*front|infront)[^.\n]*", _I)
_POSITIVE = re.compile(r"information\s+(?:is\s+)?ok|address\s+(?:is\s+)?ok", _I)


_LOI_ATTRIBUTED = ("Disagree to verify",)       # a refusal written in a sentence about the LOI is the LOI's problem, not the house's / office's


def _collect(text: str, rules) -> dict:
    """Notes found in `text`, each attributed to what the sentence is about: a sentence that names the LOI / signatory / salary
    certificate is about the LOI ("Applicant disagree to LOI verify" in an Office visit is a LOI problem, not an Office one)."""
    sl = _sentences(text)
    about_loi = "\n".join(x for x in sl if _LOI_WORD.search(x))
    other = "\n".join(x for x in sl if not _LOI_WORD.search(x))
    found: dict[str, list[str]] = {"loi": [], "trip": []}
    no_payslip = "\n".join(x for x in sl if not _PAYSLIP_RX.search(x))
    for rx, note, target in rules:
        if target == "loi":
            dest = "loi" if rx.search(no_payslip if note == "Head office disagree" else text) else None
        elif rx.search(other):
            dest = "trip"
        elif note in _LOI_ATTRIBUTED and rx.search(about_loi):
            dest = "loi"
        else:
            dest = None
        if dest and note not in found[dest]:
            found[dest].append(note)
    return found


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 4c. notes of one trip
#   'Information ok' keeps only good news; last statement wins; head-office / payslip special cases; fallback.
# ==============================================================================================================
def _notes_for(text_all: str, outcome: str, rules, loi_trip: bool = False) -> tuple[dict, bool]:
    """-> ({"loi": [...], "trip": [...]}, fallback_used).

    A visit whose verifier wrote "Information ok" is a successful visit: stray negative words in it
    (visiting card not available, applicant was not present ... but signed) are NOT problems, so only
    good-news notes and LOI notes are kept for it. A negative outcome keeps every note.
    """
    found = _collect(text_all, rules)
    positive = bool(_POSITIVE.search(outcome)) and not _INFO_NOT_OK.search(outcome)
    if positive:
        found["muted"] = [n for n in found["trip"] if n not in INFO_NOTES and n in M9_SEVERE]
        found["trip"] = [n for n in found["trip"] if n in INFO_NOTES]
    sl = _sentences(outcome)
    last_done = max((i for i, x in enumerate(sl) if _done_sentence(x)), default=-1)
    last_loi_done = max((i for i, x in enumerate(sl) if _done_sentence(x) and (loi_trip or _LOI_WORD.search(x))), default=-1)
    if last_loi_done >= 0 and found["loi"]:
        # the LOI was finished by a later statement: only LOI problems written in / after that statement still count
        # "Previous signatory not available. New signatory name is ..." describes a signatory that was replaced: history, not a problem
        tail = "\n".join(x for x in sl[last_loi_done:] if not _HISTORY.match(x))
        in_tail = _collect(tail, rules)
        found["loi"] = [n for n in found["loi"] if n in INFO_NOTES] + [n for n in in_tail["loi"] if n not in INFO_NOTES]
        if loi_trip:                                    # a LOI visit settled by its last statement: earlier visit problems are history too
            found["trip"] = [n for n in found["trip"] if n in INFO_NOTES] + [n for n in in_tail["trip"] if n not in INFO_NOTES]
    if "LOI not verified" in found["loi"] and re.search(
            r"loi\s+(?:was\s+|is\s+)?(?:signed|verified|varified)\s+(?:by\s+(?:the\s+)?signator|in\s*front|infront)|"
            r"verified\s+and\s+returned|loi\s+(?:has\s+been\s+)?verified", text_all, _I) \
            and not re.search(r"dis\s?agre\w*|refus\w+|not\s+verif\w*\s+(?:the\s+)?hard|does\s*n[o']?t\s+verif", text_all, _I):
        found["loi"].remove("LOI not verified")
    if "LOI not verified" in found["loi"]:
        # v6: "LOI not signed in front of me. LOI signatory name: ..." - it WAS signed (by the named signatory), only not before the verifier
        bare = _NOT_INFRONT.sub(" ", text_all)
        if bare != text_all and re.search(r"signator\w*\s*(?:name|:)|sign\w*\s+by\b", text_all, _I) \
                and not any(rx.search(bare) for rx, note, _t in rules if note == "LOI not verified"):
            found["loi"].remove("LOI not verified")
    if "Will be signed from head office" in found["loi"] and "LOI not verified" in found["loi"]:
        found["loi"].remove("LOI not verified")                  # v10.0.6: "Loi not signed because loi sign will be head office" = one reason, not two
    if "Submitted for verification" in found["loi"] and "Need to verify by email" in found["loi"]:
        found["loi"].remove("Need to verify by email")           # "they send the verified LOI by e-mail" answers a submitted LOI, it is not a request
    if "New address found & verified" in found["trip"] and "Given address wrong" in found["trip"]:
        found["trip"].remove("Given address wrong")
    fallback = False
    # keep the "disagree"/"could not verify" families from piling up with a more specific note
    for generic in ("Could not verify", "Statement not verified"):
        if len(found["trip"]) > 1 and generic in found["trip"]:
            found["trip"].remove(generic)
    if not found["trip"] and not found["loi"] and not positive:
        neg = _INFO_NOT_OK.search(outcome) or None
        cand = [(i, x) for i, x in enumerate(sl) if i > last_done and not _NEUTRAL.search(x) and not re.match(r"information\s+not\s+ok$", x, _I)]
        sents = [x for i, x in cand if _NEG_FALLBACK.search(x)] or [x for i, x in cand if _NEG_EXTRA.search(x)]
        if sents:
            found["trip"].append(_short(sents[0]))
            fallback = True
        elif neg:
            rest = re.sub(r"information\s+not\s+ok\.?", "", outcome, flags=_I).strip()
            # "Information not ok. Mobile no is ok. Information confirmed by applicant's wife." - what follows is not the reason
            found["trip"].append(_short(rest) if rest and not re.search(r"\bok\b|confirm\w*", rest, _I) else "Information not ok")
            fallback = True
    elif _INFO_NOT_OK.search(outcome) and not found["trip"] and found["loi"]:
        pass
    return found, fallback


_STATUS_TEXT = {1: "Not visited yet", 2: "Not visited yet", 3: "Visit in progress", 4: "On hold",
                6: "Canceled", 7: "Inactive", 8: "Withdrawn"}
FINISHED = 5
# problems that contradict "Information ok" strongly enough to ask a human to look (the Done / Due text is NOT changed)
M9_SEVERE = {"Does not sit in given office", "Does not live at given address", "No longer employed at given office", "Moved to another address",
             "Given address wrong", "No longer operates at given address", "Office closed", "Signature missing", "Phone switch off"}
M9_ON = __import__("os").environ.get("M9", "1") == "1"
import os as _os
M1_STATUSES = tuple(int(x) for x in _os.environ.get('M1_STATUSES', '6,7').split(',') if x)     # Canceled / Inactive with a problem remark stay Due
M1_ANY_TEXT = _os.environ.get('M1_ANY_TEXT') == '1'


AS_OF = None        # the day the report describes (set by the collector); None = today


def _report_day():
    return AS_OF or datetime.now().date()


def _appt_time(trip: dict):
    """Scheduled time of the latest active appointment (else any), or None."""
    ap = [a for a in (trip.get("appointments") or []) if a.get("time")]
    if not ap:
        return None
    ap.sort(key=lambda a: (a.get("active") or False, a["time"]))
    return ap[-1]["time"]


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 5a. appointment text in Due
#   'Appointment dd-mm-yyyy hh:mm AM/PM' of the latest active appointment.
# ==============================================================================================================
def _appt_text(trip: dict) -> str:
    """'Appointment 02-11-2026 10:00 AM' from the latest active appointment (else any)."""
    t = _appt_time(trip)
    return f"Appointment {t:%d-%m-%Y %I:%M %p}" if t else ""


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 5b. upcoming appointment
#   until the appointment day has passed, no negative note is written for the open trip.
# ==============================================================================================================
def appt_upcoming(trip: dict) -> bool:
    """v6: the appointment day has not passed yet (today counts).  Until then nothing negative is written about the trip - the
    applicant GAVE a time, that is all the bank needs to read.  A negative note is written only once the day is over and the
    remarks say the applicant was not there / did not meet."""
    t = _appt_time(trip)
    return bool(t and t.date() >= _report_day())


_CHAMBER_NEG = re.compile(r"no\s+longer|does\s*n[o']?t\s+have|do\s+not\s+have|\bclosed\b|not\s+(?:available|found|possible|operat\w*|verif\w*)|"
                          r"is\s*n[o']?t\s+available|no\s+chamber|without\s+(?:the\s+)?applicant", _I)
_CHAMBER_OK = re.compile(r"chamber\s+verif\w*\s+(?:is\s+|was\s+)?(?:done|complet\w*|ok)|chamber\s+(?:is\s+)?(?:ok|verified)|verif\w*\s+(?:the\s+)?chamber", _I)
# a house / office remark that says nothing good at all ("The guarantor is currently away for training ...")
_ANY_OK = re.compile(r"\bok\b|verif\w*|confirm\w*|\bsign\w*|\bfound\b|\bpresent\b|\blives?\b|\bresid\w*|\bworks?\b|\bsits?\b|correct|"
                     r"proper\s+address|new\s+address|complet\w*|\bdone\b", _I)
# "Applicant wasn't present at office because his duty starts at 8 pm, LOI signatory signed ..." - nobody took the applicant's signature
_ABSENT = re.compile(r"\bapplicant\s+(?:was\s*n[o'’]?t|is\s*n[o'’]?t|not)\s+present\b", _I)
_PEC_HEAD = re.compile(r"\bpec\b|experience\s+cert\w*|previous\s+(?:company|employer|office)", _I)
_PEC_NEG = re.compile(r"unable|not\s+(?:available|possible|verif\w*|found|sign\w*)|\bclosed\b|disagre\w*|refus\w*|does\s*n[o']?t|did\s*n[o']?t|can\s*n[o']?t", _I)
_INACTIVE_NEG = re.compile(r"\bnot\b|\w+n['’]t\b|\b(?:cannot|cant|dont|doesnt)\b|\bno\s+(?:response|one|body)|unable|disagre|refus|mismatch|missing|wrong|switch\w*\s+off|"
                           r"invalid|insufficient|closed|different|required|without", _I)


def _inactive_fine(outcome: str) -> bool:
    """The remark of an Inactive trip reads as a finished visit ("Information ok ...", "LOI verification complete")."""
    if _SIGN_NEG.search(outcome):                 # "Information ok ... so it's not possible to take guarantor sign"
        return False
    if _POSITIVE.search(outcome) and not _INFO_NOT_OK.search(outcome):
        return True
    sl = _sentences(outcome)
    if re.search(r"bank\s+statement\s+verified", outcome, _I) and not re.search(r"not\s+verif", outcome, _I):
        return True
    return bool(sl) and _done_sentence(sl[-1])


def _reason_of(outcome: str) -> str:
    """Short reason for a remark no rule knows: what follows "... not verified." when there is something, else the remark itself."""
    m = re.search(r"not\s+verif\w*\s*[.:,-]+\s*(.+)", outcome, _I | re.S)
    return _short(m.group(1) if m and len(m.group(1).strip()) > 5 else outcome)


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 5c. v13 replaced BS
#   Inactive / Canceled / Withdrawn BS redone by a LATER Finished BS of the same person: dropped, no BS number.
# ==============================================================================================================
def _replaced_banks(views: list) -> set:
    """id() of every BANK trip that is Canceled / Inactive / Withdrawn and was redone by a LATER Finished BANK trip of the same
    person (same role label: App / Co-App / PG1 ...)."""
    far = datetime(2100, 1, 1)
    banks = [v for v in views if v.trip.get("type_code") == "BANK"]
    out = set()
    for v in banks:
        t = v.trip
        if t.get("status_code") not in (6, 7, 8):
            continue
        made = t.get("created_at") or far
        if any(w is not v and w.who == v.who and w.trip.get("status_code") == FINISHED and (w.trip.get("created_at") or far) > made
               for w in banks):
            out.add(id(t))
    return out


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 5. THE ENGINE - Done / Due of one report line
#   per trip: House / Office / BS1.. / LOI / Sign / Chamber ...; finished -> Done (+ notes); open -> Due (appointment / status);
#   Canceled / Inactive with a problem remark -> Due; then merge, redone items leave Due, every problem repeats in Due,
#   head-office LOI rule, order, final text.
# ==============================================================================================================
def analyze(views: list[TripView], submitted: bool, bank_label: str = "BS") -> Summary:
    rules = _user_rules() + NOTE_RULES
    info = info_notes()
    done: list[Item] = []
    due: list[Item] = []                 # items that are still pending (not finished)
    n_bank = 0
    def _bank_counts(t: dict) -> bool:       # an Inactive bank trip that carries a remark is a statement of its own (BS2 ...)
        st = t.get("status_code")
        return st not in (6, 7, 8) or (st == 7 and (t.get("remarks") or "").strip() not in ("", "-"))
    # v13 (Naim, 19-11-2026): a bank statement trip made Inactive / Canceled / Withdrawn and REDONE by a later bank trip of the same
    # person that is Finished (a Re-CPV BS) is replaced: its old problem is no longer Due and it takes no BS number
    # (PL-20261111115745017: BS 507264 Inactive "call not received" -> Re-CPV BS 511377 done -> Done "BS", Due-0).
    replaced = _replaced_banks(views)
    total_bank = sum(1 for v in views if v.trip.get("type_code") == "BANK" and _bank_counts(v.trip) and id(v.trip) not in replaced)
    skipped: list[str] = []

    for v in views:
        t = v.trip
        outcome, _comment = _trip_text(t)
        # The back-office COMMENT is the instruction given to the verifier ("LOI will be signed from head office"), the REMARKS are what
        # the verifier reports after the work: Done / Due are written from the remarks only (the comment still names what the trip is).
        text_all = outcome
        code = t.get("type_code", "")
        status = t.get("status_code")
        finished = status == FINISHED
        notes, fallback = _notes_for(text_all, outcome, rules,
                                     loi_trip=code not in ("HOUSE", "GUARANTOR_HOUSE", "OFFICE", "GUARANTOR_OFFICE", "BANK") and _doc_name(t) == "LOI")
        who = v.who
        src = (t.get("created_at") or datetime.min, t.get("id") or 0)
        # v6: "LOI signed in front of me ... PEC verify. Mentioned signatory not available" - the LOI is done, the problem written after
        # the PEC heading belongs to the PEC (previous employer's experience certificate), not to the LOI
        pec_notes: list[str] = []
        pec_unruled = ""
        if finished and code in ("OFFICE", "DOCUMENT", "DOC_SERVICE"):
            sl_ = _sentences(outcome)
            k_ = next((i for i, x in enumerate(sl_) if _PEC_HEAD.search(x)), None)
            if k_:
                head_ = "\n".join(sl_[:k_])
                if (_LOI_POS.search(head_) and not _LOI_NEG.search(head_)) or re.search(r"verified\s+and\s+returned", head_, _I):
                    before_ = _collect(head_, rules)["loi"]
                    pec_notes = [n for n in notes["loi"] if n not in before_ and n not in INFO_NOTES]
                    if pec_notes:
                        notes["loi"] = [n for n in notes["loi"] if n in before_ or n in INFO_NOTES]
                    else:                    # no rule knows the wording: a plainly negative PEC part is still shown (and flagged)
                        tail_ = [x for x in sl_[k_:] if len(x.split()) > 3 or not _PEC_HEAD.search(x)]
                        bad_ = [x for x in tail_ if _PEC_NEG.search(x)]
                        if bad_ and not any(_done_sentence(x) for x in tail_):
                            pec_unruled = _short(re.sub(r"^\s*pec\s*(?:verif\w*)?\s*[.:-]*\s*", "", bad_[0], flags=_I))

        # ---- primary component ----
        if code in ("HOUSE", "GUARANTOR_HOUSE"):
            primary = Item(who, "House")
        elif code in ("OFFICE", "GUARANTOR_OFFICE"):
            primary = Item(who, "Office")
        elif code == "BANK":
            if id(t) in replaced:
                skipped.append(f"ট্রিপ {t.get('id')} {_STATUS_TEXT.get(status, status)} - পরে নতুন BS ট্রিপ Finished (রিপোর্ট সারাংশে বাদ)")
                continue
            if _bank_counts(t):
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
        if M9_ON and notes.get("muted") and finished:
            primary.uncertain = True
            primary.reasons.append("ট্রিপ %s: 'Information ok' লেখা, কিন্তু রিমার্কে সমস্যাও আছে (%s) - Due-তে যায়নি, যাচাই করুন" % (t.get("id"), ", ".join(notes["muted"][:2])))
        extra: list[Item] = []

        # ---- sign / LOI mentioned inside a house/office/document remark ----
        if code in ("HOUSE", "GUARANTOR_HOUSE", "OFFICE", "GUARANTOR_OFFICE", "DOCUMENT", "DOC_SERVICE") and finished:
            sign_text = " . ".join(x for x in _sentences(outcome) if not re.search(r"\bloi\b", x, _I))
            if primary.label != "Sign" and (_SIGN_POS.search(sign_text) or _SIGN_POS2.search(sign_text)) and not _SIGN_NEG.search(sign_text):
                extra.append(Item(who, "Sign"))
            elif primary.label != "Sign" and (_SIGN_NEG.search(sign_text) or code == "OFFICE" and _ABSENT.search(outcome)):
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

        # v6: a chamber that could not be verified, written inside an Office / document remark ("Chamber - the applicant no longer
        # operates a chamber at the given address"), is its own Due item
        if finished and code in ("OFFICE", "GUARANTOR_OFFICE", "DOCUMENT", "DOC_SERVICE") and primary.label != "Chamber":
            cs_ = [x for x in _sentences(outcome) if re.search(r"\bchamber\b", x, _I)]
            bad_c = [x for x in cs_ if _CHAMBER_NEG.search(x) and not re.search(r"no\s+chamber\s+name", x, _I)]
            if bad_c and not any(_CHAMBER_OK.search(x) for x in cs_):
                ci_ = Item("", "Chamber", note=_short(re.sub(r"^\s*chamber\s*(?:verif\w*)?\s*[-.:]+\s*", "", bad_c[0], flags=_I)))
                ci_.uncertain = True
                ci_.reasons.append(f"ট্রিপ {t.get('id')}: চেম্বার যাচাই হয়নি বলে মনে হয়েছে - যাচাই করুন")
                extra.append(ci_)
        if pec_notes:
            extra.append(Item("", "PEC", note="; ".join(pec_notes[:2])))
        elif pec_unruled:
            pi_ = Item("", "PEC", note=pec_unruled)
            pi_.uncertain = True
            pi_.reasons.append(f"ট্রিপ {t.get('id')}: PEC অংশে সমস্যা লেখা বলে মনে হয়েছে - যাচাই করুন")
            extra.append(pi_)
        for it in extra:
            it.inferred = True
        for it in [primary] + extra:
            it.src = src
        if (finished and code in ("HOUSE", "GUARANTOR_HOUSE", "OFFICE", "GUARANTOR_OFFICE") and outcome.strip() not in ("", "-")
                and not primary.note and not notes["trip"] and not notes["loi"] and not _ANY_OK.search(outcome)):
            primary.note = "Check - " + _short(outcome, 50)           # nothing good is written: never passed as Done silently
            primary.uncertain = True
            primary.reasons.append(f"ট্রিপ {t.get('id')}: রিমার্কে কোনো ইতিবাচক কথা নেই - যাচাই করুন")
        if finished and not outcome.strip() and not primary.note:      # v6: a finished trip without one word of remarks is never passed silently
            primary.note = "Check - no remarks written"
            primary.uncertain = True
            primary.reasons.append(f"ট্রিপ {t.get('id')}: Finished, কিন্তু কোনো remarks লেখা নেই")
        items = [primary] + extra
        if not finished:
            if status in (6, 7, 8):                      # canceled / inactive / withdrawn
                problem_notes = [n for n in trip_notes if n not in INFO_NOTES]        # "New address found & verified" is good news, not a problem
                # v6: an Inactive trip whose remark tells of a problem in words no rule knows is still Due (never dropped silently)
                unruled = (not problem_notes and outcome.strip() not in ("", "-") and not _inactive_fine(outcome)
                           and bool(_INACTIVE_NEG.search(outcome)))
                wrote = (t.get("remarks") or "").strip() not in ("", "-")       # a Canceled trip counts only for what the verifier wrote
                if status in M1_STATUSES and (status != 6 or wrote) and not (status == 6 and _inactive_fine(outcome)) \
                        and (problem_notes or unruled or M1_ANY_TEXT and outcome.strip() not in ("", "-")):
                    primary.rank = 1
                    primary.note = ("; ".join(problem_notes[:2]) if problem_notes
                                    else "Signature could not be taken" if _SIGN_NEG.search(outcome) else _reason_of(outcome))
                    primary.pending = True
                    primary.uncertain = True
                    primary.reasons.append(f"ট্রিপ {t.get('id')} {_STATUS_TEXT[status]} কিন্তু রিমার্কে সমস্যা লেখা (Due-তে দেখানো)")
                    due.append(primary)
                    continue
                skipped.append(f"ট্রিপ {t.get('id')} {_STATUS_TEXT[status]} (রিপোর্ট সারাংশে বাদ)")
                continue
            primary.rank = 1
            reason_bits = []
            if _appt_text(t):
                reason_bits.append(_appt_text(t))
            if not appt_upcoming(t):                      # v6: an appointment that is still to come carries no negative note
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
    fin = [i for i in done if i.rank == 2]
    due = [i for i in due if not any(f.who == i.who and f.label == i.label and not (_weak(f) and _newer(i, f)) for f in fin)]
    # a weak inference ("LOI verification head office." in an Office remark) that a NEWER open trip of the same kind contradicts is not Done
    done = [d for d in done if not (_weak(d) and any(p.who == d.who and p.label == d.label and _newer(p, d) for p in due))]
    # every problem item of Done is repeated in Due (same wording)
    problems = [i.problem_only(info) for i in done if i.is_problem(info)]
    due = _merge(problems + due)
    done, due = _head_office_loi(done, due, views)

    return _finish(done, due, list(skipped), submitted)


HO_NOTE = "Will be signed from head office"
HO_NEW_TRIP = "New trip created for head office verification"
HO_ONLY = "Will be verified from head office"
_HO = re.compile(r"head\s*office|\bhq\b|head\s*quarter|corporate\s+office", re.I)


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 7. head-office LOI
#   never Done; Due as 'LOI (New trip created for head office verification)' or '(Will be verified from head office)'.
# ==============================================================================================================
def _head_office_loi(done: list[Item], due: list[Item], views: list) -> tuple[list[Item], list[Item]]:
    """v10.0.6 (Naim, 17-11-2026): a LOI that will be signed / verified at the head office is NOT done - it is only Due, worded:
         a new document trip was made for it at the head office -> "LOI (New trip created for head office verification)"
         otherwise (only the remark says so)                      -> "LOI (Will be verified from head office)"
    A document trip counts as made for the head office when its comment or address names the head office (HQ / corporate office),
    or when it is a LOI trip created after the remark that sent the LOI to the head office."""
    def ho(i: Item) -> bool:
        return i.label == "LOI" and HO_NOTE in (i.note or "")
    hits = [i for i in done + due if ho(i)]
    if not hits:
        return done, due
    remark_at = min((i.src[0] for i in hits if i.src and i.src[0]), default=None)
    remark_ids = {i.src[1] for i in hits if len(i.src) > 1}
    new_trip = False
    for v in views:
        t = v.trip
        if t.get("type_code") in ("HOUSE", "OFFICE", "BANK", "GUARANTOR_HOUSE", "GUARANTOR_OFFICE") or t.get("id") in remark_ids:
            continue                     # the trip whose own remark says "head office" is not a NEW trip for it
        blob = " ".join(str(t.get(k) or "") for k in ("comment", "address", "exact_address", "place_name"))
        later = bool(remark_at and t.get("created_at") and t["created_at"] - remark_at >= timedelta(minutes=30) and _doc_name(t) == "LOI")
        if _HO.search(blob) or later:
            new_trip = True
            break
    word = HO_NEW_TRIP if new_trip else HO_ONLY
    keep = [n for i in hits for n in (i.note or "").split("; ") if n and n != HO_NOTE and n != "LOI not verified"]
    note = "; ".join(dict.fromkeys([word] + keep))
    base = hits[-1]
    done = [i for i in done if not ho(i)]
    due = [i for i in due if not ho(i)] + [replace(base, note=note, pending=True, rank=min(base.rank, 1))]
    return done, _merge(due)


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 8c. final text
#   'Done-0' / 'Due-0'; nothing due but the file not Submitted -> 'Due-Report not yet submitted'.
# ==============================================================================================================
def _finish(done: list[Item], due: list[Item], skipped: list[str], submitted: bool) -> Summary:
    uncertain, reasons = bool(skipped), list(skipped)
    for it in done + due:
        if it.uncertain:
            uncertain = True
            reasons.extend(it.reasons)
    reasons = list(dict.fromkeys(reasons))
    s = Summary(done=_render(done) or "0", due=_render(due) or "0", uncertain=uncertain, reasons=reasons,
                done_parts=_parts(done) or [("0", "ok")], due_parts=_parts(due) or [("0", "ok")],
                done_items=done, due_items=due)
    if not submitted and not due:
        s.due = "Report not yet submitted"
        s.due_parts = [(s.due, "note")]
        s.uncertain = True
        s.reasons.append("সব ট্রিপ শেষ কিন্তু রিপোর্ট Submitted নয়")
    return s


def apply_later(own: Summary, later: Summary, submitted: bool) -> Summary:
    """Report Summary = the LAST update.  `own` = Done / Due of a row's own trips; `later` = the summary of trips of the same file that
    came AFTER them (a Re-CPV / Extra trip listed inside this row).  An item the row has - Done or Due - that a later trip finished
    again (the LOI document trip created after "signatory not available", finished and submitted with the file) takes the LATER
    outcome: clean -> Done and not Due any more; a problem again -> Due with the later wording ("LOI signed" in the package, then the
    LOI trip says the applicant disagrees: LOI is due).  Items the row did not have are not added."""
    info = info_notes()
    redone = {(i.who, i.label): i for i in later.done_items if i.rank == 2}
    hit = {(i.who, i.label) for i in own.done_items + own.due_items if (i.who, i.label) in redone}
    if not hit:
        return own
    done = [redone[(i.who, i.label)] if (i.who, i.label) in hit else i for i in own.done_items]
    have = {(i.who, i.label) for i in own.done_items}
    done += [redone[k] for k in sorted(hit) if k not in have]       # a Due item the later trip finished is Done now (it was not in Done before)
    due = [i for i in own.due_items if (i.who, i.label) not in hit]
    due += [redone[k].problem_only(info) for k in hit if redone[k].is_problem(info)]
    skipped = [r for r in own.reasons if not any(r in i.reasons for i in own.done_items + own.due_items)]
    return _finish(done, _merge(due), skipped, submitted)


def _newer(a: Item, b: Item) -> bool:
    """a came from a trip created AFTER b's trip (unknown creation times never count as newer)."""
    try:
        return bool(a.src) and bool(b.src) and (a.src[0] - b.src[0]) >= timedelta(minutes=30)       # trips of one package are created seconds apart
    except TypeError:
        return False


def _weak(i: Item) -> bool:
    """A LOI / Sign only INFERRED from another trip's remark and carrying no problem of its own ("LOI verification head office.")."""
    return i.inferred and not i.note and i.rank == 2


def _beats(it: Item, old: Item) -> bool:
    """A finished trip beats an open one, later beats earlier - except that a weak inference (see _weak) does not cancel an open trip
    of its own kind that was created after the remark was written: that trip is the newer update."""
    if it.rank > old.rank:
        return not (_weak(it) and _newer(old, it))
    if it.rank == old.rank:
        return True
    return _weak(old) and _newer(it, old)


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 6. merge
#   one entry per (person, part): a finished trip beats an open one, a later trip an earlier one.
# ==============================================================================================================
def _merge(items: list[Item]) -> list[Item]:
    """One entry per (who, label). A finished trip beats an open / canceled one; later beats earlier."""
    out: list[Item] = []
    for it in items:
        idx = next((i for i, o in enumerate(out) if o.who == it.who and o.label == it.label), None)
        if idx is None:
            out.append(it)
        elif _beats(it, out[idx]):
            out[idx] = it
    return out


# ==============================================================================================================
# ★ DONE/DUE LOGIC: 8a. order
#   App -> documents (LOI, BS, BS1.., Chamber, Rental ...) -> Co-App -> PG; House, Office, Sign inside a person.
# ==============================================================================================================
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
