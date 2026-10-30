"""Rule-based remark shortener. Free, offline, no data leaves the computer.

Each rule recognises a typical phrase and contributes a short tag. Tags are
joined with "; ". If nothing matches, the first sentence (trimmed) is used.
The full remark is always kept in its own column.
"""
from __future__ import annotations

import re

_I = re.IGNORECASE

_RELATIONS = (
    "wife|husband|spouse|mother in law|mother-in-law|mother|father|brother|sister|son|daughter|"
    "caretaker|care taker|security guard|security|guard|receptionist|driver|land ?lord|"
    "colleague|neighbou?r|servant|maid|manager|hr|staff|tenant|assistant"
)

# (regex, tag) evaluated in order; a tag is added once.
_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\binformation\s+(?:is\s+)?(?:ok|correct)\b|\binformation (?:was )?confirmed as correct", _I), "Info OK"),
    (re.compile(r"\baddress\s+(?:is\s+|was\s+)?(?:ok|correct)\b", _I), "Address OK"),
    (re.compile(r"\b(?:mobile|phone|contact)\s*(?:no\.?|number)?\s*(?:is\s+)?ok\b|\b(?:mobile|phone)\s+number\s+(?:is\s+)?(?:ok|correct)\b|applicants?\s+(?:proper\s+)?(?:mobile|phone)\s+number\s+is\s+ok", _I), "Mobile OK"),
    (re.compile(r"address\s+(?:is\s+)?(?:mis\s?match(?:ed)?|not match(?:ed)?)|given\s+(?:residence\s+)?address\s+(?:is\s+)?mis\s?match(?:ed)?", _I), "Address mismatch"),
    (re.compile(r"new\s+address\s+(?:found|is)", _I), "New address found"),
    (re.compile(r"(?:does\s*n[o']?t|do not|doesn't)\s+live\s+in\s+(?:the\s+)?(?:given|mention(?:ed)?)", _I), "Not living at given address"),
    (re.compile(r"(?:applicants?|co[- ]?applicants?|guarantors?|gurantors?)\s+(?:was\s+|were\s+)?present\s+(?:at|in)\s+(?:the\s+)?office", _I), "Present at office"),
    (re.compile(r"(?:signed|sign(?:ed)?\s+in\s+front|signed\s+infront|sign\s+form\s+signed|signed\s+front)", _I), "Signed in front of verifier"),
    (re.compile(r"\bloi\b[^.\n]{0,40}\b(?:not\s+verif|could not be verif)|\bloi\b[^.\n]{0,60}(?:not\s+issue|not verifie|didn't|didation)|(?:not|n't)\s+verif[^.\n]{0,40}\bloi\b|that documents not verified", _I), "LOI not verified"),
    (re.compile(r"\bloi\b[^.\n]{0,40}\b(?:verif|varif)|\bloi\s+sign", _I), "LOI verified/signed"),
    (re.compile(r"\bloi\b[^.\n]{0,40}(?:will be signed|can verif)", _I), "LOI via head office/branch"),
    (re.compile(r"pay\s*slip\s+verif", _I), "Pay slip verified"),
    (re.compile(r"bank statement[^.\n]{0,30}\bnot\s+verified|bank statement\s+(?:does\s+not|doesn't)\s+provide", _I), "Bank statement not verified"),
    (re.compile(r"bank statement[^.\n]{0,30}\b(?:verified|provided)", _I), "Bank statement verified"),
    (re.compile(r"hard\s*copy\s+provided", _I), "Hard copy provided"),
    (re.compile(r"seal\s+(?:is\s+)?(?:missing|required)", _I), "Seal issue"),
    (re.compile(r"signature\s+mis\s?match", _I), "Signature mismatch"),
    (re.compile(r"(?:applicants?|guarantors?)\s+call\s+not\s+received", _I), "Call not received"),
    (re.compile(r"(?:not\s+possible|could\s+not\s+be\s+(?:completed|possible)|couldn't|unable)\s+(?:to\s+)?(?:verif|be\s+complet)|verification\s+could\s+not|not possible to verify", _I), "Could not verify"),
    (re.compile(r"(?:disagree|not\s+interest)", _I), "Refused / not interested"),
    (re.compile(r"entry\s+restricted|photograph\w*\s+(?:of\s+[^.]*)?(?:is\s+)?prohibited|restricted\s+area", _I), "Entry/photo restricted"),
    (re.compile(r"no\s+visible\s+(?:holding|name\s*plate|house\s+number)", _I), "No visible holding/nameplate"),
]

_SELF = re.compile(r"confirm(?:ed|ation)?\s+(?:by|from)\s+[^.\n]{0,25}\b(?:self|himself|herself|her self|his self)\b", _I)
_REL = re.compile(r"(?:confirm(?:ed|ation)?|provided|information was provided)\s+(?:by|from)\s+(?:the\s+)?(?:applicants?[' ]*s?\s+|guarantors?\s+|house\s+)?(" + _RELATIONS + r")\b", _I)


def _first_sentence(text: str, limit: int = 90) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", flat)
    sent = m.group(1) if m else flat
    return sent if len(sent) <= limit else sent[: limit - 1].rstrip() + "…"


def short_remark(text: str | None) -> str:
    if not text or not text.strip():
        return ""
    tags: list[str] = []

    def add(tag: str) -> None:
        if tag not in tags:
            tags.append(tag)

    for rx, tag in _RULES:
        if rx.search(text):
            add(tag)
    if _SELF.search(text):
        add("Confirmed by self")
    else:
        m = _REL.search(text)
        if m:
            add("Confirmed by " + m.group(1).lower().replace("  ", " "))

    # conflicting tags: keep the more specific/negative one
    if "LOI not verified" in tags and "LOI verified/signed" in tags:
        tags.remove("LOI verified/signed")
    if "Bank statement not verified" in tags and "Bank statement verified" in tags:
        tags.remove("Bank statement verified")
    if "Could not verify" in tags and "Info OK" in tags:
        tags.remove("Info OK")

    if not tags:
        return _first_sentence(text)
    return "; ".join(tags)
