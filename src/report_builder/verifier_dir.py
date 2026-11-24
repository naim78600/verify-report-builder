"""V18: verifier directory - WhatsApp numbers, the WhatsApp check and photos, for verifiers only.

* Who is in it: only the people the dashboard lists as verifiers (/api/v2/verifiers, role 4).  A row of an import that is
  not one of them is skipped; nobody else can be added.
* WhatsApp number: the dashboard number, or the number Naim set (settings "phone_overrides" - the same list the reminder
  rounds already use, so a number saved here is used by the next round).
* WhatsApp check: the Chrome helper on WhatsApp Web opens each number's chat (nothing is typed or sent) and reports
  "connected" (the chat opens) or "not on WhatsApp" (WhatsApp says so).  Results sit in the reminders state:
  "no_whatsapp" {8801...: date} (already used since v10) and "wa_ok" {8801...: date}.
* Photos: any picture the computer can open (JPG, PNG, WEBP, GIF, BMP, TIFF; HEIC when pillow-heif is installed) is
  saved as a 320 x 320 JPEG in ~/.verify_report_builder/verifier_photos/<verifier id>.jpg.
Nothing here is sent to the Verify dashboard: it stays on this computer.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from pathlib import Path

from . import config
from .client import is_bd_mobile, normalize_phone

PHOTO_DIR = config.SETTINGS_DIR / "verifier_photos"
PHOTO_SIZE = 320
RECHECK_DAYS = 30                       # a number checked "connected" is checked again after this many days
VERIFIER_ROLE = 4                       # /api/v2/verifiers user_role of a field verifier (all 142 on 24 Nov 2026)


# ----------------------------------------------------------------------------------------------- numbers and status
def number_of(vid, phones: dict, overrides: dict) -> str:
    return overrides.get(str(vid)) or (phones.get(int(vid)) or {}).get("phone", "") if str(vid).isdigit() else ""


def wa_status(phone: str, state: dict) -> str:
    """'none' (no number) | 'bad' (not a Bangladesh mobile) | 'no' (not on WhatsApp) | 'ok' (connected) | 'unchecked'."""
    if not phone:
        return "none"
    if not is_bd_mobile(phone):
        return "bad"
    if phone in (state.get("no_whatsapp") or {}):
        return "no"
    if phone in (state.get("wa_ok") or {}):
        return "ok"
    return "unchecked"


STATUS_TEXT = {"ok": ("WhatsApp আছে", "WhatsApp connected"), "unchecked": ("এখনো চেক হয়নি", "Not checked yet"),
               "no": ("WhatsApp নেই", "Not on WhatsApp"), "bad": ("নম্বর ঠিক নেই", "Number not valid"),
               "none": ("নম্বর নেই", "No number")}


def record_check(state: dict, phone: str, connected: bool, when: date | None = None) -> None:
    """One result of the WhatsApp check (from the helper)."""
    when = (when or date.today()).isoformat()
    ok, no = state.setdefault("wa_ok", {}), state.setdefault("no_whatsapp", {})
    if connected:
        ok[phone] = when
        no.pop(phone, None)
    else:
        no[phone] = when
        ok.pop(phone, None)


def mark_not_on_whatsapp(state: dict, phone: str) -> None:
    record_check(state, phone, False)


def to_check(phones: dict, overrides: dict, state: dict, today: date | None = None) -> list[dict]:
    """Numbers the helper should check: valid numbers never checked, and "connected" ones older than RECHECK_DAYS.
    A number WhatsApp said is not on WhatsApp is not checked again (Naim changes the number instead)."""
    today = today or date.today()
    out, seen = [], set()
    ids = set(phones) | {int(k) for k in overrides if str(k).isdigit()}
    for vid in sorted(ids):
        ph = number_of(vid, phones, overrides)
        if not is_bd_mobile(ph) or ph in seen or ph in (state.get("no_whatsapp") or {}):
            continue
        seen.add(ph)
        last = (state.get("wa_ok") or {}).get(ph)
        if last:
            try:
                if today - date.fromisoformat(last) < timedelta(days=RECHECK_DAYS):
                    continue
            except ValueError:
                pass
        out.append({"phone": ph, "verifier": (phones.get(vid) or {}).get("name", "") or str(vid), "vid": vid})
    return out


# ----------------------------------------------------------------------------------------------- import (Excel / CSV)
def read_rows(path: Path) -> list[list[str]]:
    """The rows of an Excel (.xlsx / .xlsm) or CSV / TXT file, as text."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        rows = [["" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)) for v in r]
                for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        raw = path.read_bytes()
        text = None
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        text = text or raw.decode("utf-8", "replace")
        dialect = csv.excel
        try:
            dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
        except csv.Error:
            pass
        rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    return [[str(c).strip() for c in r] for r in rows if any(str(c).strip() for c in r)]


def _name_key(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def parse_import(rows: list[list[str]], phones: dict) -> list[dict]:
    """Matches each row to a verifier (by ID, else by exact name) and reads the WhatsApp number.
    Returns [{row, key, vid, name, phone, ok, why}] - nothing is saved here."""
    if not rows:
        return []
    head = [c.lower() for c in rows[0]]
    has_head = any(re.search(r"name|id|whats|phone|mobile|number|নাম|নম্বর", h) for h in head)

    def col(pattern: str, default: int) -> int:
        if has_head:
            for i, h in enumerate(head):
                if re.search(pattern, h):
                    return i
        return default
    i_id = col(r"^id$|verifier id|agent id|^আইডি", -1)
    i_name = col(r"name|নাম", 0)
    i_num = col(r"whats|phone|mobile|number|নম্বর", 1)
    by_name = {}
    for vid, p in phones.items():
        by_name.setdefault(_name_key(p.get("name")), []).append(vid)
    out = []
    for n, r in enumerate(rows[1:] if has_head else rows, start=2 if has_head else 1):
        cell = lambda i: r[i] if 0 <= i < len(r) else ""                              # noqa: E731
        vid = None
        rid = re.sub(r"\D", "", cell(i_id)) if i_id >= 0 else ""
        if rid and int(rid) in phones:
            vid = int(rid)
        elif len(by_name.get(_name_key(cell(i_name)), [])) == 1:
            vid = by_name[_name_key(cell(i_name))][0]
        ph = normalize_phone(cell(i_num))
        why = "" if vid is not None and is_bd_mobile(ph) else ("not a verifier" if vid is None else "number not valid")
        if vid is None and len(by_name.get(_name_key(cell(i_name)), [])) > 1:
            why = "two verifiers with this name - give the ID"
        out.append({"row": n, "key": " · ".join(x for x in (cell(i_id) if i_id >= 0 else "", cell(i_name)) if x),
                    "vid": vid, "name": (phones.get(vid) or {}).get("name", "") if vid is not None else "",
                    "phone": ph, "ok": not why, "why": why})
    return out


def apply_import(items: list[dict], overrides: dict) -> int:
    """Puts the good rows into the number list (overrides).  Returns how many numbers were saved."""
    n = 0
    for it in items:
        if it.get("ok"):
            overrides[str(it["vid"])] = it["phone"]
            n += 1
    return n


def export_csv(path: Path, phones: dict, overrides: dict, state: dict) -> Path:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Verifier ID", "Name", "WhatsApp", "Status", "Photo"])
        for vid in sorted(phones, key=lambda i: (phones[i].get("name") or "").lower()):
            ph = number_of(vid, phones, overrides)
            w.writerow([vid, phones[vid].get("name", ""), ph, STATUS_TEXT[wa_status(ph, state)][1], "yes" if photo_path(vid) else ""])
    return path


# ----------------------------------------------------------------------------------------------- photos
def photo_path(vid) -> Path | None:
    p = PHOTO_DIR / f"{int(vid)}.jpg"
    return p if p.is_file() else None


def save_photo(vid, src) -> Path:
    """src = a file path or the picture's bytes.  Any format Pillow can open; HEIC when pillow-heif is installed."""
    from PIL import Image, ImageOps
    try:
        import pillow_heif                                   # optional: iPhone HEIC photos
        pillow_heif.register_heif_opener()
    except Exception:                                        # noqa: BLE001
        pass
    data = Path(src).read_bytes() if isinstance(src, (str, Path)) else bytes(src)
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im).convert("RGB")
    im = ImageOps.fit(im, (PHOTO_SIZE, PHOTO_SIZE), Image.LANCZOS)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    out = PHOTO_DIR / f"{int(vid)}.jpg"
    tmp = out.with_suffix(".tmp")
    im.save(tmp, "JPEG", quality=86)
    tmp.replace(out)
    return out


def match_photo_files(paths: list, phones: dict) -> tuple[list[tuple[int, Path]], list[Path]]:
    """Many photos at once: each file name is a verifier's name or ID (e.g. 'Zihadul Islam.jpg', '5532.png')."""
    by_name = {}
    for vid, p in phones.items():
        by_name.setdefault(_name_key(p.get("name")), []).append(vid)
    found, missed = [], []
    for p in map(Path, paths):
        stem = _name_key(p.stem)
        m = re.search(r"\d{3,}", stem)
        if stem.isdigit() and int(stem) in phones:
            found.append((int(stem), p))
        elif len(by_name.get(stem, [])) == 1:
            found.append((by_name[stem][0], p))
        elif m and int(m.group()) in phones:
            found.append((int(m.group()), p))
        else:
            missed.append(p)
    return found, missed


# ----------------------------------------------------------------------------------------------- for the new dashboard
def directory(phones: dict, overrides: dict, state: dict) -> list[dict]:
    """The list the new dashboard (Chrome extension) shows: only verifiers."""
    out = []
    for vid, p in phones.items():
        ph = number_of(vid, phones, overrides)
        pp = photo_path(vid)
        out.append({"id": vid, "name": p.get("name", ""), "num": ph[2:] if ph.startswith("880") else ph,
                    "fromDashboard": str(vid) not in overrides, "wa": wa_status(ph, state),
                    "checked": (state.get("wa_ok") or {}).get(ph) or (state.get("no_whatsapp") or {}).get(ph) or "",
                    "photo": int(pp.stat().st_mtime) if pp else 0})
    return out
