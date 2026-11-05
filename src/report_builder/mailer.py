"""Builds and sends the Submission Tracker e-mail.

* The body is plain paragraphs (no tables) + the signature; the report is the attached Excel.
* Sent through SMTP (Zoho by default) as verify@barikoi.com.
* The password / app password is asked when you press Send, kept only in memory, and never written to disk.
* A small local log (date, phase, recipients, file name) prevents sending the same phase twice by mistake.
"""
from __future__ import annotations

import html
import json
import re
import smtplib
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from .config import SETTINGS_DIR, load_settings, save_settings
from .signature import LOGO_CID, logo_file, signature_html, signature_text

DEFAULT_FROM = "verify@barikoi.com"
DEFAULT_TO = [
    "mustafijur.rahman14@primebank.com.bd",
    "begum.tahmina@primebank.com.bd",
    "rifat.uddin@primebank.com.bd",
]
SMTP_PRESETS = [
    ("smtp.zoho.com", "Zoho (global, .com)"),
    ("smtp.zoho.in", "Zoho (India, .in)"),
    ("smtp.zoho.eu", "Zoho (Europe, .eu)"),
    ("smtp.zoho.com.au", "Zoho (Australia)"),
]
SECURITY = [("ssl", "SSL (port 465)"), ("starttls", "STARTTLS (port 587)"), ("none", "None (testing only)")]
SENT_LOG = SETTINGS_DIR / "sent_mail_log.json"
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$|^[A-Za-z0-9._%+\-']+@localhost$")


@dataclass
class SmtpSettings:
    host: str = "smtp.zoho.com"
    port: int = 465
    security: str = "ssl"                    # ssl | starttls | none
    username: str = DEFAULT_FROM
    from_addr: str = DEFAULT_FROM
    from_name: str = "Verify Barikoi"
    bcc_self: bool = True
    timeout: int = 30


@dataclass
class MailDraft:
    to: list = field(default_factory=list)
    cc: list = field(default_factory=list)
    bcc: list = field(default_factory=list)
    subject: str = ""
    body: str = ""
    attachments: list = field(default_factory=list)      # paths
    signature: dict | None = None


# ----------------------------------------------------------------------------- addresses
def parse_addresses(text) -> list[str]:
    """'a@x.com, b@y.com; c@z.com' or a list -> ['a@x.com', ...] (order kept, duplicates dropped, lower-cased)."""
    if isinstance(text, (list, tuple)):
        text = ",".join(text)
    out, seen = [], set()
    for part in re.split(r"[,;\s]+", text or ""):
        part = part.strip().strip("<>").strip()
        if part and part.lower() not in seen:
            seen.add(part.lower())
            out.append(part.lower())
    return out


def invalid_addresses(addrs) -> list[str]:
    return [a for a in addrs if not _EMAIL_RE.match(a)]


# ----------------------------------------------------------------------------- settings (no secrets)
def load_smtp_settings() -> SmtpSettings:
    s = SmtpSettings()
    saved = load_settings().get("smtp")
    if isinstance(saved, dict):
        for k, v in saved.items():
            if hasattr(s, k) and "pass" not in k.lower():
                setattr(s, k, v)
    return s


def save_smtp_settings(s: SmtpSettings) -> None:
    data = {k: getattr(s, k) for k in ("host", "port", "security", "username", "from_addr", "from_name", "bcc_self")}
    save_settings({"smtp": data})


def load_recipients() -> dict:
    saved = load_settings().get("mail_recipients")
    base = {"to": list(DEFAULT_TO), "cc": [], "bcc": []}
    if isinstance(saved, dict):
        for k in base:
            if isinstance(saved.get(k), list):
                base[k] = saved[k]
    return base


def save_recipients(to, cc, bcc) -> None:
    save_settings({"mail_recipients": {"to": list(to), "cc": list(cc), "bcc": list(bcc)}})


# ----------------------------------------------------------------------------- message
def body_html(body: str, sig: dict) -> str:
    """Plain paragraphs -> simple HTML (no tables) followed by the signature."""
    paras = [p for p in re.split(r"\n\s*\n", (body or "").strip()) if p.strip()]
    chunks = []
    for p in paras:
        chunks.append('<p style="margin:0 0 12px 0">' + html.escape(p.strip()).replace("\n", "<br>") + "</p>")
    return ('<html><body style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1f2937;line-height:1.55">'
            + "".join(chunks) + '<div style="margin-top:18px">' + signature_html(sig) + "</div></body></html>")


def build_message(draft: MailDraft, smtp: SmtpSettings) -> EmailMessage:
    sig = draft.signature or {}
    msg = EmailMessage()
    msg["From"] = formataddr((smtp.from_name, smtp.from_addr)) if smtp.from_name else smtp.from_addr
    msg["To"] = ", ".join(draft.to)
    if draft.cc:
        msg["Cc"] = ", ".join(draft.cc)
    msg["Subject"] = draft.subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(smtp.from_addr.split("@")[-1] or "localhost"))
    text = (draft.body or "").strip() + "\n\n" + signature_text(sig) + "\n"
    msg.set_content(text)
    msg.add_alternative(body_html(draft.body, sig), subtype="html")
    logo = logo_file(sig)
    if logo:
        html_part = msg.get_payload()[-1]
        html_part.add_related(logo.read_bytes(), "image", "png", cid=f"<{LOGO_CID}>", filename="barikoi_logo.png",
                              disposition="inline")
    for path in draft.attachments:
        p = Path(path)
        data = p.read_bytes()
        if p.suffix.lower() == ".xlsx":
            maintype, subtype = "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        elif p.suffix.lower() == ".pdf":
            maintype, subtype = "application", "pdf"
        else:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)
    return msg


def envelope_recipients(draft: MailDraft, smtp: SmtpSettings) -> list[str]:
    allr = list(draft.to) + list(draft.cc) + list(draft.bcc)
    if smtp.bcc_self and smtp.from_addr:
        allr.append(smtp.from_addr)
    seen, out = set(), []
    for a in allr:
        if a.lower() not in seen:
            seen.add(a.lower())
            out.append(a)
    return out


def check_draft(draft: MailDraft) -> list[str]:
    """Problems that must be fixed before sending (empty list = OK)."""
    problems = []
    if not draft.to:
        problems.append("Add at least one recipient in To.")
    bad = invalid_addresses(list(draft.to) + list(draft.cc) + list(draft.bcc))
    if bad:
        problems.append("Invalid e-mail address: " + ", ".join(bad))
    if not draft.subject.strip():
        problems.append("The subject is empty.")
    if not draft.body.strip():
        problems.append("The message body is empty.")
    if not draft.attachments:
        problems.append("No report is attached.")
    for a in draft.attachments:
        if not Path(a).is_file():
            problems.append(f"Attachment not found: {a}")
    return problems


# ----------------------------------------------------------------------------- sending
class MailError(Exception):
    pass


def _friendly(exc: Exception) -> str:
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return ("Login failed. Zoho needs an App Password (Zoho Mail → My Account → Security → App Passwords), "
                "not the normal sign-in password. Check the user name too.")
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "The server refused the recipient address(es): " + ", ".join(exc.recipients)
    if isinstance(exc, smtplib.SMTPSenderRefused):
        return "The server refused the sender address – it must be the account you log in with."
    if isinstance(exc, (smtplib.SMTPConnectError, ConnectionError, TimeoutError, OSError)):
        return f"Could not reach the mail server ({exc}). Check the internet connection, host and port."
    if isinstance(exc, ssl.SSLError):
        return f"Secure connection failed ({exc}). Try the other security option (SSL 465 / STARTTLS 587)."
    return f"Sending failed: {exc}"


def send_message(msg: EmailMessage, smtp: SmtpSettings, password: str | None, recipients: list[str]) -> None:
    """Sends through SMTP.  The password is used for this call only.  Raises MailError with a readable text."""
    try:
        if smtp.security == "ssl":
            server = smtplib.SMTP_SSL(smtp.host, smtp.port, timeout=smtp.timeout, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(smtp.host, smtp.port, timeout=smtp.timeout)
        with server:
            server.ehlo()
            if smtp.security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if password:
                server.login(smtp.username, password)
            server.send_message(msg, from_addr=smtp.from_addr, to_addrs=recipients)
    except Exception as exc:                       # noqa: BLE001 - turned into a readable message
        raise MailError(_friendly(exc)) from exc


# ----------------------------------------------------------------------------- sent log / duplicate guard
def _read_log() -> list:
    try:
        data = json.loads(SENT_LOG.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def sent_log() -> list:
    return list(reversed(_read_log()))


def log_sent(report_date, slot: str, draft: MailDraft, file_name: str) -> None:
    entries = _read_log()
    entries.append({
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "report_date": str(report_date), "slot": slot,
        "to": draft.to, "cc": draft.cc, "subject": draft.subject, "file": file_name,
    })
    try:
        SENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        SENT_LOG.write_text(json.dumps(entries[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def already_sent(report_date, slot: str) -> dict | None:
    """The earlier log entry for the same report date + phase (to warn before a duplicate), or None."""
    for e in reversed(_read_log()):
        if e.get("report_date") == str(report_date) and e.get("slot") == slot:
            return e
    return None
