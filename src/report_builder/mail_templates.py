"""Professional subject / body templates for the Submission Tracker e-mail.

The body never carries a table - the report is the attached Excel.  Counts are filled in automatically.
Three styles are offered; the text can still be edited before sending."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

TEMPLATES = [
    ("formal", "Formal — full explanation"),
    ("concise", "Concise — short and direct"),
    ("executive", "Executive summary — status first"),
]
PHASE_NAME = {"3pm": ("1st", "3:30 PM"), "7pm": ("2nd", "7:00 PM")}


@dataclass
class MailFacts:
    """Numbers the body talks about (taken from the finished report)."""
    report_date: date
    slot: str = "7pm"                  # "3pm" | "7pm"
    after3_only: bool = False
    complete_files: int = 0
    complete_rows: int = 0
    incomplete_files: int = 0
    incomplete_rows: int = 0
    sla_breach_rows: int = 0
    partial_files: int = 0
    reason_missing: int = 0
    bank: str = "Prime Bank PLC"


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _ctx(f: MailFacts) -> dict:
    ordinal, clock = PHASE_NAME.get(f.slot, ("", ""))
    return {
        "bank": f.bank, "ordinal": ordinal, "clock": clock,
        "date_long": f"{f.report_date.day:02d} {f.report_date:%B %Y}", "date_dmy": f"{f.report_date:%d/%m/%Y}",
        "weekday": f"{f.report_date:%A}",
        "c_files": _n(f.complete_files, "file"), "c_rows": _n(f.complete_rows, "bill row"),
        "i_files": _n(f.incomplete_files, "file"), "i_rows": _n(f.incomplete_rows, "bill row"),
        "sla": f.sla_breach_rows, "partial": f.partial_files,
    }


def _scope_line(f: MailFacts, c: dict) -> str:
    if f.slot == "3pm":
        return (f"This 1st-phase report covers the files submitted before 3:00 PM on {c['weekday']}, {c['date_long']}, "
                "together with the position of the pending files at that time.")
    if f.after3_only:
        return (f"This 2nd-phase report covers the files submitted after 3:00 PM on {c['weekday']}, {c['date_long']} "
                "(the earlier submissions were sent with the 1st-phase tracker), together with the pending files at the end of the day.")
    return (f"This 2nd-phase report covers all files submitted on {c['weekday']}, {c['date_long']}, "
            "together with the pending files at the end of the day.")


def _status_paragraph(f: MailFacts, c: dict) -> str:
    done = (f"{c['c_files'].capitalize()} ({c['c_rows']}) {'have' if f.complete_files != 1 else 'has'} been submitted and "
            "listed in the Complete Report.") if f.complete_files else "No file has been submitted in this period."
    if not f.incomplete_files:
        return done + " There is no pending file to report."
    pend = (f"{c['i_files'].capitalize()} ({c['i_rows']}) {'are' if f.incomplete_files != 1 else 'is'} still pending and listed in the "
            "Incomplete Report")
    extra = []
    if f.sla_breach_rows:
        extra.append(f"{f.sla_breach_rows} {'rows have' if f.sla_breach_rows != 1 else 'row has'} crossed the SLA")
    if f.partial_files:
        extra.append(f"{_n(f.partial_files, 'file')} {'are' if f.partial_files != 1 else 'is'} partially submitted")
    pend += (" (" + "; ".join(extra) + ")") if extra else ""
    return done + " " + pend + "."


def render(template_id: str, f: MailFacts) -> tuple[str, str]:
    """-> (subject, body text)."""
    c = _ctx(f)
    reasons = ("For every pending file the Incomplete Report states the reason - an appointment given, a hold remark, "
               "the file being within its SLA, or the documents still due for a partially submitted file.")
    if template_id == "concise":
        subject = f"Verification Submission Tracker – {c['bank']} – {c['date_dmy']} – {c['ordinal']} Phase"
        body = (f"Dear Sir / Madam,\n\nPlease find attached the {c['ordinal']}-phase Submission Tracker of {c['bank']} for "
                f"{c['date_long']}.\n\n{_status_paragraph(f, c)}\n\n"
                "Kindly let us know if you need any clarification.\n")
    elif template_id == "executive":
        subject = f"{c['bank']} – Daily Verification Submission Report | {c['date_long']} | {c['ordinal']} Phase ({c['clock']})"
        body = (f"Dear Team,\n\nGreetings from Barikoi Technologies Limited.\n\n"
                f"{_status_paragraph(f, c)}\n\n"
                f"{reasons if f.incomplete_files else ''}{chr(10) + chr(10) if f.incomplete_files else ''}"
                f"The detailed tracker for {c['weekday']}, {c['date_long']} ({c['ordinal']} phase, {c['clock']}) is attached as an Excel "
                "workbook with the Complete Report, the Incomplete Report and a Summary sheet.\n\n"
                "Please feel free to reach out if you would like to discuss any file.\n")
    else:                                                    # formal
        subject = f"{c['bank']} | Submission Tracker – {c['date_long']} ({c['ordinal']} Phase)"
        body = (f"Dear Sir / Madam,\n\nGreetings from Barikoi Technologies Limited.\n\n"
                f"Please find attached the Submission Tracker of {c['bank']} for {c['weekday']}, {c['date_long']} "
                f"({c['ordinal']} phase, {c['clock']}).\n\n{_scope_line(f, c)}\n\n{_status_paragraph(f, c)}"
                f"{chr(10) + chr(10) + reasons if f.incomplete_files else ''}\n\n"
                "Should you require any clarification or further detail on a particular file, please do not hesitate to reply to this e-mail.\n"
                "\nThank you for your continued support.\n")
    return subject, body


def facts_from(d) -> MailFacts:
    """Numbers for the mail body, taken from a finished tracker (PrimeData)."""
    files = lambda rows: len({r.file_no for r in rows})                       # noqa: E731
    return MailFacts(
        report_date=d.report_date, slot=d.slot, after3_only=bool(getattr(d, "after3_only", False)),
        complete_files=files(d.complete), complete_rows=len(d.complete),
        incomplete_files=files(d.incomplete), incomplete_rows=len(d.incomplete),
        sla_breach_rows=sum(1 for r in d.incomplete if (r.extra_tat or 0) > 0),
        partial_files=len({r.file_no for r in d.incomplete if r.file_status == 7}),
        reason_missing=sum(1 for r in d.incomplete if "reason" in r.flags),
        bank=(d.org_name or "Prime Bank PLC"))
