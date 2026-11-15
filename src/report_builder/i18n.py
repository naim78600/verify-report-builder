"""v10: Bangla / English.  The language is chosen on the opening screen every time the program starts (the last choice
is pre-selected) and can be changed in Settings.  Reports, Excel and PDF files are not affected (they are English, as
the bank reads them); only the program's own screens and messages change."""
from __future__ import annotations

import re

LANG = "bn"            # "bn" | "en"

STAGE_EN = {"login": "Signing in", "list": "Reading the file list", "detail": "Reading files", "recpv": "Reading Re-CPV list",
            "old": "Looking for extra trips of older files", "log": "Reading activity logs", "rows": "Building the rows",
            "write": "Writing the files", "excel": "Writing the Excel", "bs": "Reading bank statements", "phones": "Reading verifier numbers"}


def set_lang(lang: str) -> None:
    global LANG
    LANG = "en" if lang == "en" else "bn"


def L(bn: str, en: str) -> str:
    """The text in the chosen language."""
    return en if LANG == "en" else bn


def is_en() -> bool:
    return LANG == "en"


_BN = re.compile(r"[ঀ-৿]")
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def progress_text(stage: str, done: int, total: int, text: str) -> str:
    """Progress lines come from the collectors in Bangla; in English mode a plain English line is shown instead."""
    if LANG != "en" or not _BN.search(text or ""):
        return text
    label = STAGE_EN.get(stage, "Working")
    if text.strip() in ("সম্পন্ন।", "লগইন সম্পন্ন।"):
        return "Done." if stage != "login" else "Signed in."
    return f"{label} {done}/{total}" if total and total > 1 else f"{label}…"


_ERRORS = [
    (r"লগইন হয়নি", "Sign-in failed. The e-mail or password may be wrong."),
    (r"সার্ভারে সংযোগ করা যায়নি", "Could not reach the server (check the internet)."),
    (r"টোকেন গ্রহণ হয়নি", "The server did not accept the sign-in. Please sign in again."),
    (r"বার চেষ্টার পরও ব্যর্থ", "The server did not answer after several tries. Try again in a few minutes."),
    (r"নামে কোনো সংস্থা পাওয়া যায়নি", "This client was not found in your account."),
    (r"অপ্রত্যাশিত সমস্যা", "Unexpected problem"),
]


def error_text(text: str) -> str:
    if LANG != "en" or not _BN.search(text or ""):
        return text
    for rx, en in _ERRORS:
        if re.search(rx, text):
            tail = re.sub(r"[ঀ-৿।]+", "", text).strip(" :;,.-")
            return en + (f" ({tail})" if tail and len(tail) < 120 else "")
    return text
