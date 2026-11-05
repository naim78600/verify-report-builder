"""The e-mail signature (name, designation, phone, company, logo).

Default = the signature saved in the Zoho Mail account verify@barikoi.com.  Every field can be changed in the
mail-settings window; the choice is remembered in the settings file (never a password)."""
from __future__ import annotations

import html
import sys
from pathlib import Path

from .config import load_settings, save_settings

LOGO_CID = "barikoi_logo"

DEFAULT_SIGNATURE = {
    "closing": "Regards,",
    "name": "Saikat Francis Gomes",
    "title": "Executive-Client Operation",
    "phone": "+8801321167537",
    "company": "Barikoi Technologies Limited",
    "tagline": "Maps for Businesses",
    "logo_path": "",                 # empty = the built-in Barikoi logo
    "use_logo": True,
}


def bundled_logo() -> Path:
    """The Barikoi logo shipped with the program (works from source and from the PyInstaller bundle)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for p in (base / "report_builder" / "assets" / "barikoi_logo.png", base / "assets" / "barikoi_logo.png",
              Path(__file__).resolve().parent / "assets" / "barikoi_logo.png"):
        if p.is_file():
            return p
    return Path(__file__).resolve().parent / "assets" / "barikoi_logo.png"


def load_signature() -> dict:
    sig = dict(DEFAULT_SIGNATURE)
    saved = load_settings().get("mail_signature")
    if isinstance(saved, dict):
        sig.update({k: v for k, v in saved.items() if k in DEFAULT_SIGNATURE})
    return sig


def save_signature(sig: dict) -> None:
    save_settings({"mail_signature": {k: sig.get(k, DEFAULT_SIGNATURE[k]) for k in DEFAULT_SIGNATURE}})


def logo_file(sig: dict) -> Path | None:
    """The logo file to embed, or None when the signature has no logo."""
    if not sig.get("use_logo", True):
        return None
    custom = (sig.get("logo_path") or "").strip()
    if custom and Path(custom).is_file():
        return Path(custom)
    p = bundled_logo()
    return p if p.is_file() else None


def signature_text(sig: dict) -> str:
    lines = [sig.get("closing", ""), sig.get("name", ""), sig.get("title", "")]
    if sig.get("phone"):
        lines.append(f"Phone: {sig['phone']}")
    lines.append(sig.get("company", ""))
    return "\n".join(x for x in lines if x)


def signature_html(sig: dict, with_logo: bool = True) -> str:
    e = html.escape
    rows = []
    if sig.get("closing"):
        rows.append(f'<div style="margin-bottom:6px">{e(sig["closing"])}</div>')
    if sig.get("name"):
        rows.append(f'<div style="font-weight:bold;font-size:14px;color:#1f2937">{e(sig["name"])}</div>')
    if sig.get("title"):
        rows.append(f'<div style="color:#374151">{e(sig["title"])}</div>')
    if sig.get("phone"):
        rows.append(f'<div style="color:#374151">Phone: {e(sig["phone"])}</div>')
    if sig.get("company"):
        rows.append(f'<div style="color:#374151;font-weight:bold">{e(sig["company"])}</div>')
    out = '<div style="font-family:Segoe UI,Arial,sans-serif;font-size:13px;line-height:1.5">' + "".join(rows)
    if with_logo and logo_file(sig):
        out += f'<div style="margin-top:8px"><img src="cid:{LOGO_CID}" alt="Barikoi" width="120" style="border:0"></div>'
    return out + "</div>"
