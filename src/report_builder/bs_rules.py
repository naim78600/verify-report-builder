"""v10 BS (bank statement) rules: which bank a BS trip is for, online / offline, and - from the verifier's exact remarks -
whether the statement was actually collected.

Bank list: Naim's online / offline sheet (15 Nov 2026) with short names (SWIFT code, common spellings, the way they are
written in the Verify dashboard).  No manual checking (Naim: "kono checking rakha lagbe na"): a short form that can mean
two banks (PBL, JBL, MBL, SBL, UBL ...) is decided from the words around it (remarks, branch); when it is still unclear
the BS counts as OFFLINE, so no statement is ever missed.  Standard Bank = Standard Islami Bank PLC (renamed 10 Feb
2026) = offline.  EXIM, First Security, Global Islami, Union and Social Islami are one bank since Aug 2026
(Sammilito Islami Bank), all offline.

Outcome rules were learnt from the exact remarks of the 283 BS trips of 1 Oct - 15 Nov 2026 (Prime Bank + LankaBangla):
240 of the 242 finished trips are recognised; anything new is "Check remark" (the reason is shown, nothing is hidden).
"""
from __future__ import annotations

import re

ONLINE = [
    ("IFIC Bank PLC", "IFIC", "IFIC; IFIC BANK; IFIC BANK PLC; International Finance Investment and Commerce Bank"),
    ("The City Bank PLC", "CIBL", "City Bank; CITY BANK PLC; CBL; The City Bank"),
    ("Standard Chartered Bank", "SCBL", "SCB; StanChart; Standard Chartered; STANDARD CHARTERED BANK PLC; Standerd Chartered"),
    ("Dhaka Bank PLC", "DHBL", "Dhaka Bank; DHAKA BANK PLC; DBL (ambiguous)"),
    ("Mutual Trust Bank PLC", "MTBL", "MTB; MTBL; Mutual Trust; MUTUAL TRUST BANK PLC"),
    ("Trust Bank PLC", "TTBL", "Trust Bank; TBL; TRUST BANK PLC"),
    ("Dutch-Bangla Bank PLC", "DBBL", "DBBL; Dutch Bangla; DUTCH BANGLA BANK PLC; Dutch-Bangla Bank"),
    ("Community Bank Bangladesh PLC", "COYM", "Community Bank; CBBL"),
    ("Sonali Bank PLC", "BSON", "Sonali; SONALI BANK PLC; SBL (ambiguous)"),
    ("Eastern Bank PLC", "EBLD", "EBL; EBL BANK; Eastern Bank; EASTERN BANK PLC"),
    ("Shimanto Bank PLC", "SHMT", "Simanto Bank; Shimanto"),
    ("BRAC Bank PLC", "BRAK", "BRAC; BRAC BANK PLC; BBL"),
    ("United Commercial Bank PLC", "UCBL", "UCB; UCBL; United Commercial Bank; UNITED COMMERCIAL BANK PLC"),
    ("NRB Bank PLC", "NRBD", "NRB Bank; NRB BANK PLC; NRBBL (not NRBC)"),
    ("HSBC", "HSBC", "HSBC; Hongkong and Shanghai Banking Corporation"),
    ("Bank Alfalah", "ALFH", "Al Falah; Alfalah; Bank Al Falah"),
    ("Woori Bank", "HVBK", "Woori; Wori Bank"),
    ("Mercantile Bank PLC", "MBLB", "Mercantile; MERCANTILE BANK PLC; MBL (ambiguous)"),
    ("ONE Bank PLC", "ONEB", "One Bank; ONE BANK PLC; OBL"),
    ("Prime Bank PLC", "PRBL", "Prime Bank; PRIME BANK PLC; PBL (ambiguous)"),
    ("Bengal Commercial Bank PLC", "BCOL", "Bengal Commercial Bank; BCBL (ambiguous)"),
    ("Southeast Bank PLC", "SEBD", "Southeast; South East Bank; SEBL; SOUTHEAST BANK PLC"),
    ("Midland Bank PLC", "MDBL", "Midland; MDBL; MBL (ambiguous)"),
    ("Bangladesh Commerce Bank Limited", "BCBL", "BCB; Bangladesh Commerce Bank; BCBL (ambiguous)"),
    ("State Bank of India", "SBIN", "SBI; State Bank (India)"),
    ("Habib Bank Limited", "HABB", "HBL; Habib Bank (Pakistan)"),
    ("Commercial Bank of Ceylon PLC", "CCEY", "Commercial Bank of Ceylon; CBC"),
    ("AB Bank PLC", "ABBL", "AB Bank; AB BANK PLC; ABBL"),
]
OFFLINE = [
    ("NCC Bank PLC", "NCCL", "NCC; NCCBL; NCC BANK PLC; National Credit and Commerce Bank"),
    ("The Premier Bank PLC", "PRMR", "Premier Bank; PREMIER BANK PLC; PBL (ambiguous)"),
    ("Jamuna Bank PLC", "JAMU", "Jamuna; JAMUNA BANK PLC; JAMUNA BANK PLC.; JBL (ambiguous)"),
    ("Bank Asia PLC", "BALB", "Bank Asia; BANK ASIA PLC; BAL"),
    ("Janata Bank PLC", "JANB", "Janata; JANATA BANK PLC; JBL (ambiguous)"),
    ("Pubali Bank PLC", "PUBA", "Pubali; PUBALI BANK; PUBALI BANK PLC; PBL (ambiguous)"),
    ("Uttara Bank PLC", "UTBL", "Uttara; UTTARA BANK PLC; Uttar Bank; UBL (ambiguous)"),
    ("Agrani Bank PLC", "AGBK", "Agrani; AGRANI BANK PLC; ABL"),
    ("Union Bank PLC", "UBLD", "Union Bank; UBL (ambiguous); now part of Sammilito Islami Bank"),
    ("Shahjalal Islami Bank PLC", "SJBL", "SJIBL; Shahjalal; SHAHJALAL ISLAMI BANK PLC"),
    ("Social Islami Bank PLC", "SOIV", "SIBL; Social Islami; now part of Sammilito Islami Bank"),
    ("First Security Islami Bank PLC", "FSEB", "FSIBL; First Security; Fast Security Islami Bank; now part of Sammilito Islami Bank"),
    ("Al-Arafah Islami Bank PLC", "ALAR", "AIBL; Al Arafah; AL ARAFAH ISLAMI BANK PLC"),
    ("National Bank PLC", "NBLB", "NBL; National Bank; NATIONAL BANK PLC"),
    ("Islami Bank Bangladesh PLC", "IBBL", "IBBL; IBBPLC; Islami Bank; ISLAMI BANK PLC; ISLAMI BANK BANGLADESH PLC; Islami Bank Bangladesh Limited"),
    ("Bangladesh Krishi Bank", "BKBA", "BKB; Krishi Bank; BANGLADESH KRISHI BANK PLC"),
    ("Global Islami Bank PLC", "NGBL", "GIB; Global Islami; formerly NRB Global Bank; now part of Sammilito Islami Bank"),
    ("Standard Bank PLC / Standard Islami Bank PLC", "SDBL", "Standard Bank; STANDARD BANK PLC; STANDARD ISLAMI BANK PLC; SBL (ambiguous); not Standard Chartered"),
    ("Padma Bank PLC", "FRMS", "Padma; formerly Farmers Bank"),
    ("Meghna Bank PLC", "MGBL", "Meghna; MEGHNA BANK PLC; MBL (ambiguous)"),
    ("Modhumoti Bank PLC", "MODH", "Modhumita Bank; Modhumoti; MMBL"),
    ("NRBC Bank PLC", "NRBB", "NRBC; NRBC BANK PLC; NRBC Bank (not NRB Bank)"),
    ("Rupali Bank PLC", "RUPB", "Rupali; RUPALI BANK PLC; RBL"),
    ("EXIM Bank (Export Import Bank of Bangladesh PLC)", "EXBK", "EXIM; Exim Bank; now part of Sammilito Islami Bank"),
    ("Sammilito Islami Bank PLC", "-", "Sammilito Islami Bank (merged EXIM, First Security, Global Islami, Union, Social Islami; old branch names still used)"),
]


# --------------------------------------------------------------------------------------------- bank matching
_SHORT_AMBIG = {"PBL", "JBL", "MBL", "SBL", "UBL", "BCBL", "DBL", "NRB", "STANDARD", "TRUST"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower()).replace(" plc", " ").replace(" ltd", " ").replace(" limited", " ").strip()


def _aliases():
    out = []
    for kind, rows in (("Online", ONLINE), ("Offline", OFFLINE)):
        for name, code, al in rows:
            names = {name, name.split(" (")[0], name.replace(" PLC", "")}
            if code and code != "-":
                names.add(code)
            for a in al.split(";"):
                a = a.strip()
                if not a or "(ambiguous)" in a or a.startswith(("now part", "formerly", "not ", "merged")) or "(not" in a:
                    continue
                names.add(a.split(" (")[0])
            for n in names:
                k = _norm(n)
                if k and k.upper() not in _SHORT_AMBIG:
                    out.append((k, name, kind))
    out.sort(key=lambda t: -len(t[0]))          # longest name first: "mutual trust bank" before "trust bank"
    return out


ALIASES = _aliases()
# a short form that can mean more than one bank -> the banks it can mean (the words around it decide)
AMBIG_SHORT = {
    "pbl": ["Prime Bank PLC", "The Premier Bank PLC", "Pubali Bank PLC"],
    "jbl": ["Jamuna Bank PLC", "Janata Bank PLC"],
    "mbl": ["Mercantile Bank PLC", "Midland Bank PLC", "Meghna Bank PLC"],
    "sbl": ["Sonali Bank PLC", "Standard Bank PLC / Standard Islami Bank PLC"],
    "ubl": ["Uttara Bank PLC", "Union Bank PLC"],
    "bcbl": ["Bengal Commercial Bank PLC", "Bangladesh Commerce Bank Limited"],
    "dbl": ["Dhaka Bank PLC"],
}
KIND = {name: kind for kind, rows in (("Online", ONLINE), ("Offline", OFFLINE)) for name, _c, _a in rows}
SHORT_NAME = {name: (code if code and code != "-" else "SIBL") for rows in (ONLINE, OFFLINE) for name, code, _a in rows}


def match_bank(place_name: str, remarks: str = "") -> tuple[str, str, str]:
    """-> (standard bank name or "", "Online" | "Offline", how).  `how` says why (for the Excel's note column).
    Order: the bank written on the trip, then the remarks.  Unclear -> Offline (never missed)."""
    for text, where in ((place_name, "bank name"), (remarks, "remarks")):
        t = " " + _norm(text) + " "
        if not t.strip():
            continue
        # Standard Chartered vs Standard Bank: decide before the generic match
        if " standard chartered " in t or " stanchart " in t or " scb " in t:
            return "Standard Chartered Bank", "Online", where
        if re.search(r" standard (islami )?bank ", t):
            return "Standard Bank PLC / Standard Islami Bank PLC", "Offline", where
        if " sammilito " in t or " sommilito " in t:
            return "Sammilito Islami Bank PLC", "Offline", where
        for alias, name, kind in ALIASES:
            if f" {alias} " in t:
                return name, kind, where
        for short, names in AMBIG_SHORT.items():
            if f" {short} " in t:
                if len(names) == 1:
                    return names[0], KIND[names[0]], where
                ctx = " " + _norm(place_name + " " + remarks) + " "
                for n in names:                       # another word in the text names one of them
                    first = _norm(n).split()[0] if not n.startswith("The ") else _norm(n).split()[1]
                    if f" {first} " in ctx:
                        return n, KIND[n], where + " (short form)"
                return names[0] + " (?)", "Offline", where + f" (short form {short.upper()} unclear - counted offline)"
    if (place_name or "").strip():
        return place_name.strip(), "Offline", "not in the bank list - counted offline"
    return "", "Offline", "bank not written - counted offline"


# --------------------------------------------------------------------------------------------- outcome from remarks
COLLECTED, COLLECTED_SOFT, NOT_VERIFIED, REFUSED, NOT_POSSIBLE, VERIFIED_ONLY, CHECK, PENDING = (
    "Collected (hard copy)", "Collected (soft copy)", "Not collected - statement not verified", "Not collected - applicant disagreed",
    "Not collected - not possible", "Verified (copy not mentioned)", "Check remark", "Pending (no remark yet)")
COLLECTED_SET = {COLLECTED, COLLECTED_SOFT}
NOT_COLLECTED_SET = {NOT_VERIFIED, REFUSED, NOT_POSSIBLE}


def _n(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z#\s]", " ", re.sub(r"[0-9]+", "#", (s or "").lower()))).strip()


_RULES = [
    (REFUSED, re.compile(r"disagree|refus|denied|not agree|not willing|unwilling")),
    (NOT_POSSIBLE, re.compile(r"not possible|not available|closed|transferred|returned|without (his |her )?signature|abroad|home country")),
    (NOT_VERIFIED, re.compile(r"statement (is )?not verified|not verified|not ok|mismatch|not match")),
    (COLLECTED, re.compile(r"hard ?copy (provided|received|collected|given)|(provided|received|collected) hard ?copy|statement (hard ?copy )?provided")),
    (COLLECTED_SOFT, re.compile(r"scan(ned)? copy|soft ?copy|e ?mail")),
    (VERIFIED_ONLY, re.compile(r"verified")),
]
_LOW = re.compile(r"insufficient|low balance|no balance")


def bs_outcome(remarks: str, trip_status_code: int | None = None) -> tuple[str, str]:
    """-> (outcome, extra note).  Note = "insufficient balance" when the remark says so."""
    n = _n(remarks)
    if not n:
        return (PENDING if trip_status_code not in (5, 7) else CHECK), ""
    note = "Insufficient balance" if _LOW.search(n) else ""
    for label, rx in _RULES:
        if rx.search(n):
            return label, note
    return CHECK, note


def is_collected(outcome: str) -> bool:
    return outcome in COLLECTED_SET
