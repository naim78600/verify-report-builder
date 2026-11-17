"""v10 BS Tracker: every BANK (bank statement) trip, from the verifier's visit to the bank's signed received list.

The path of one BS (one row per BS trip; a file with two BS has two rows, next to each other, told apart by Trip ID):
  1. trip created on the dashboard (the month a trip is created decides the monthly Excel it is in)
  2. verifier's exact remarks -> collected or not (bs_rules.bs_outcome)
  3. office receive: the verifier hands the paper in (entered in the program during the day; an A4 "Received today"
     sheet is printed at day end and signed)
  4. courier: courier name + number, slip picture, latest status
  5. bank received: Naim uploads the client's signed received list (Excel / CSV / PDF / photo); the program finds each
     BS in it by Trip ID, File No or applicant name

Everything the person adds (office receive, courier, bank received) is kept in a small local file
(~/.verify_report_builder/bs_store.json); the dashboard is only read.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import config
from .bs_rules import COLLECTED_SET, NOT_COLLECTED_SET, PENDING, SHORT_NAME, bs_outcome, match_bank

STORE_FILE = config.SETTINGS_DIR / "bs_store.json"
SLIP_DIR = config.SETTINGS_DIR / "bs_slips"
COURIER_STATUS = ["Booked", "In transit", "Delivered", "Returned"]


# ============================================================================================ rows
@dataclass
class BSRow:
    org: str
    trip_id: int
    file_id: int
    file_no: str
    applicant: str
    created: datetime | None
    bank_written: str
    bank: str
    bs_type: str                 # Online / Offline
    bank_how: str
    verifier: str
    verifier_id: int | None
    phone: str
    trip_status: str
    trip_status_code: int | None
    remarks: str
    outcome: str
    outcome_note: str
    file_status: str
    sla: datetime | None = None
    # added by the person (from the store)
    office: dict = field(default_factory=dict)
    courier: dict = field(default_factory=dict)
    bank_received: dict = field(default_factory=dict)
    finished: datetime | None = None             # v12: when the verifier finished the trip (= the day the BS was withdrawn / collected)
    bank_submitted: dict = field(default_factory=dict)   # v12: Online BS handed in at the bank by the verifier (slip photo from WhatsApp)

    @property
    def collected(self) -> bool:
        return self.outcome in COLLECTED_SET

    @property
    def where(self) -> str:
        """Where the paper is now, in words."""
        if self.bank_received:
            return "Bank received"
        if self.courier.get("no"):
            return f"Courier · {self.courier.get('status') or 'Booked'}"
        if self.office:
            return "Office received"
        if self.outcome in NOT_COLLECTED_SET:
            return "-"
        if self.collected:
            return "Office receive pending"
        return "At verifier / pending"


def _applicant(f: dict) -> str:
    for c in f.get("concerns") or []:
        if (c.get("role") or "").lower() in ("applicant", "") and c.get("name"):
            return c["name"]
    cs = f.get("concerns") or []
    return cs[0].get("name", "") if cs else ""


def bs_rows(files: list[dict], org: str, phones: dict | None = None, month: tuple[int, int] | None = None,
            store: dict | None = None) -> list[BSRow]:
    """All BANK trips of these (normalised) files; `month` = (year, month) keeps only trips created in that month.
    Order: by the first BS of the file, then the file, then Trip ID - so the BS of one file sit next to each other."""
    phones = phones or {}
    store = store if store is not None else load_store()
    out: list[BSRow] = []
    for f in files:
        for c in f.get("concerns") or []:
            for t in c.get("trips") or []:
                if (t.get("type_code") or "").upper() != "BANK":
                    continue
                cr = t.get("created_at")
                if month and not (cr and (cr.year, cr.month) == month):
                    continue
                bank, kind, how = match_bank(t.get("place_name", ""), t.get("remarks", ""),
                                             " , ".join(x for x in (t.get("address", ""), t.get("exact_address", "")) if x))
                outcome, note = bs_outcome(t.get("remarks", ""), t.get("status_code"))
                vid = t.get("agent_id")
                key = str(t.get("id"))
                s = store.get(key, {})
                out.append(BSRow(
                    org=org, trip_id=t.get("id"), file_id=f.get("id"), file_no=f.get("file_no", ""), applicant=_applicant(f),
                    created=cr, bank_written=t.get("place_name", "") or t.get("address", ""), bank=bank, bs_type=kind, bank_how=how,
                    verifier=t.get("verifier", ""), verifier_id=vid, phone=(phones.get(vid) or {}).get("phone", "") if vid else "",
                    trip_status=t.get("status", ""), trip_status_code=t.get("status_code"), remarks=t.get("remarks", ""),
                    outcome=outcome, outcome_note=note, file_status=f.get("status", ""), sla=f.get("sla"),
                    office=s.get("office") or {}, courier=s.get("courier") or {}, bank_received=s.get("bank_received") or {},
                    finished=t.get("end_time") if t.get("status_code") == 5 else None, bank_submitted=s.get("bank_submitted") or {}))
    first = {}
    for r in out:
        k = (r.org, r.file_id)
        first[k] = min(first.get(k, r.created or datetime.max), r.created or datetime.max)
    out.sort(key=lambda r: (first[(r.org, r.file_id)], r.file_no, r.trip_id or 0))
    return out


def pending_bs(rows: list[BSRow]) -> list[BSRow]:
    """BS still to do something about (no cap - Naim: every pending BS): not yet collected (trip open), or collected but
    not yet in the office / with the bank."""
    out = []
    for r in rows:
        if r.bank_received or r.outcome in NOT_COLLECTED_SET or r.trip_status_code in (6, 8):
            continue
        if r.collected and (r.office or r.courier.get("no") or r.bank_submitted):
            continue
        out.append(r)
    return out


def still_with_verifier(rows: list[BSRow]) -> list[BSRow]:
    """V12 'who still holds a BS': withdrawn from the bank (collected), but not yet in the office, with a courier, received
    by the bank, or (Online BS) handed in at the bank by the verifier.  Cancelled / withdrawn trips are left out."""
    return [r for r in rows if r.collected and r.trip_status_code not in (6, 8)
            and not (r.office or r.courier.get("no") or r.bank_received or r.bank_submitted)]


def by_verifier(rows: list[BSRow]) -> list[tuple[str, list[BSRow]]]:
    """Groups by verifier: the one holding the most first; inside, the oldest withdrawal first."""
    groups: dict[str, list[BSRow]] = {}
    for r in rows:
        groups.setdefault(r.verifier or "—", []).append(r)
    far = datetime.max
    for g in groups.values():
        g.sort(key=lambda r: (r.finished or far, r.trip_id))
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))


# ============================================================================================ store
def load_store() -> dict:
    try:
        return json.loads(STORE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_store(store: dict) -> None:
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(STORE_FILE)


def set_office(store: dict, trip_id, *, giver: str, receiver: str, pages: str = "", note: str = "", when: datetime | None = None,
               file_no: str = "", bank: str = "") -> dict:
    e = store.setdefault(str(trip_id), {})
    e["office"] = {"at": (when or datetime.now()).isoformat(timespec="minutes"), "giver": giver, "receiver": receiver,
                   "pages": str(pages), "note": note, "file_no": file_no, "bank": bank}
    return e


def set_bank_submitted(store: dict, trip_id, *, photos: list, verifier: str = "", via: str = "WhatsApp") -> dict:
    """v12: an Online BS the verifier handed in at the bank himself; `photos` = the saved slip pictures."""
    e = store.setdefault(str(trip_id), {})
    b = dict(e.get("bank_submitted") or {})
    b.update({"at": b.get("at") or datetime.now().isoformat(timespec="minutes"), "verifier": verifier, "via": via,
              "photos": sorted(set(b.get("photos", [])) | {str(p) for p in photos})})
    e["bank_submitted"] = b
    return e


def set_courier(store: dict, trip_id, *, name: str = "", no: str = "", status: str = "Booked", slip: str | Path | None = None) -> dict:
    e = store.setdefault(str(trip_id), {})
    c = dict(e.get("courier") or {})
    c.update({"name": name or c.get("name", ""), "no": no or c.get("no", ""), "status": status or c.get("status", "Booked"),
              "updated": datetime.now().isoformat(timespec="minutes")})
    if slip:
        SLIP_DIR.mkdir(parents=True, exist_ok=True)
        src = Path(slip)
        dst = SLIP_DIR / f"{trip_id}{src.suffix.lower()}"
        if src.resolve() != dst.resolve():
            shutil.copyfile(src, dst)
        c["slip"] = str(dst)
    e["courier"] = c
    return e


def office_today(store: dict, day: date | None = None) -> list[tuple[str, dict]]:
    day = day or date.today()
    out = [(k, v["office"]) for k, v in store.items() if (v.get("office") or {}).get("at", "")[:10] == day.isoformat()]
    out.sort(key=lambda kv: kv[1].get("at", ""))
    return out


# ============================================================================================ signed list (bank received)
_FILE_NO = re.compile(r"[A-Z]{1,4}-{1,2}\d{8,16}")
_LONG_NUM = re.compile(r"\d{6,16}")


def read_text_any(path: Path) -> str:
    """All the text of an Excel / CSV / PDF / photo.  Photo: Windows' own OCR (built in, free), else tesseract if present."""
    p = Path(path)
    suf = p.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        wb = load_workbook(p, read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                parts.append(" | ".join("" if v is None else str(v) for v in row))
        return "\n".join(parts)
    if suf in (".csv", ".txt"):
        with open(p, encoding="utf-8-sig", errors="replace", newline="") as fh:
            return "\n".join(" | ".join(r) for r in csv.reader(fh))
    if suf == ".pdf":
        from pypdf import PdfReader
        text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        if text.strip():
            return text
        raise ValueError("এই PDF-এ লেখা নেই (স্ক্যান করা ছবি)। ছবি হিসেবে (JPG/PNG) দিন, অথবা Excel দিন।")
    if suf in (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"):
        return ocr_image(p)
    raise ValueError(f"এই ধরনের ফাইল পড়া যায় না: {suf}")


_WIN_OCR = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($args[0])) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$result.Lines | ForEach-Object { $_.Text }
"""


def ocr_image(path: Path) -> str:
    if sys.platform.startswith("win"):
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as fh:
            fh.write(_WIN_OCR)
            script = fh.name
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, str(Path(path).resolve())],
                               capture_output=True, text=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout
        finally:
            Path(script).unlink(missing_ok=True)
    if sys.platform == "darwin":                       # Mac: the small Vision tool built into the app (assets/bin/mac_ocr)
        try:
            from .assets_path import asset
            exe = Path(asset("bin", "mac_ocr"))
            if exe.exists():
                if not os.access(exe, os.X_OK):
                    exe.chmod(0o755)
                r = subprocess.run([str(exe), str(Path(path).resolve())], capture_output=True, text=True, timeout=120)
                if r.returncode == 0 and r.stdout.strip():
                    return r.stdout
        except Exception:
            pass
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(path))
    except Exception:
        pass
    raise ValueError("ছবি থেকে লেখা পড়া যায়নি। PDF বা Excel দিন (Windows ও Mac-এ ছবি সাধারণত পড়া যায়)।")


def _tokens(text: str) -> tuple[set, set, str]:
    up = text.upper()
    fnos = {re.sub(r"-+", "-", m) for m in _FILE_NO.findall(up.replace(" ", ""))} | {re.sub(r"-+", "-", m) for m in _FILE_NO.findall(up)}
    nums = set(_LONG_NUM.findall(re.sub(r"(?<=\d)[\s,]+(?=\d)", "", up)))
    words = " " + re.sub(r"[^a-z]+", " ", text.lower()) + " "
    return fnos, nums, words


def match_signed_list(rows: list[BSRow], text: str) -> dict[int, str]:
    """-> {trip_id: how it was found}.  A BS counts as received when its Trip ID, its File No (or the File No's digits),
    or the applicant's full name (2+ words) appears in the signed list.  When a file has two BS and only the name is
    found, the bank's name must be on the same line (so the other BS of that file is not ticked by mistake)."""
    fnos, nums, words = _tokens(text)
    ids = set(re.findall(r"(?<!\d)\d{3,9}(?!\d)", text))
    lines = [" " + re.sub(r"[^a-z]+", " ", ln.lower()) + " " for ln in text.splitlines()]
    per_file: dict = {}
    for r in rows:
        per_file[(r.org, r.file_id)] = per_file.get((r.org, r.file_id), 0) + 1
    found = {}
    for r in rows:
        fno = re.sub(r"-+", "-", (r.file_no or "").upper())
        digits = re.sub(r"\D", "", fno)
        if r.trip_id and str(r.trip_id) in ids:
            found[r.trip_id] = "Trip ID"
        elif per_file[(r.org, r.file_id)] == 1 and fno and (fno in fnos or (len(digits) >= 10 and digits in nums)):
            found[r.trip_id] = "File No"
        else:
            name = re.sub(r"[^a-z]+", " ", (r.applicant or "").lower()).strip()
            if len(name.split()) < 2 or f" {name} " not in words:
                continue
            if per_file[(r.org, r.file_id)] == 1:
                found[r.trip_id] = "Applicant name"
                continue
            bank_words = [w for w in re.sub(r"[^a-z]+", " ", (r.bank or r.bank_written).lower()).split()
                          if w not in ("bank", "plc", "the", "limited", "ltd", "of")]
            if bank_words and any(f" {name} " in ln and f" {bank_words[0]} " in ln for ln in lines):
                found[r.trip_id] = "Applicant name + bank"
    return found


def apply_signed_list(store: dict, rows: list[BSRow], found: dict, source: str) -> int:
    n = 0
    for r in rows:
        if r.trip_id in found:
            store.setdefault(str(r.trip_id), {})["bank_received"] = {"at": datetime.now().isoformat(timespec="minutes"),
                                                                       "source": Path(source).name, "by": found[r.trip_id]}
            n += 1
    return n


# ============================================================================================ Excel
NAVY, LINE = "1F3A5F", "CBD5E1"
THIN = Side(style="thin", color=LINE)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
GREEN, RED, AMBER, BLUE = "047857", "B91C1C", "B45309", "1D4ED8"

BS_COLS = [("Created Date-Time", 15), ("Trip ID", 9), ("File No", 19), ("Applicant", 18), ("Bank (as written)", 16),
           ("Bank", 20), ("BS Type", 8), ("Verifier", 15), ("Verifier Phone", 13), ("Trip Status", 9),
           ("Exact Remarks", 40), ("BS Outcome", 20), ("Office Received", 15), ("Courier", 16), ("Courier Slip", 14),
           ("Bank Received", 14), ("Now", 15)]


def write_bs_excel(rows: list[BSRow], path: Path, title: str) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "BS Tracker"
    n = len(BS_COLS)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    c = ws.cell(1, 1, title)
    c.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    c.fill = PatternFill("solid", fgColor=NAVY)
    c.alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 28
    got = sum(1 for r in rows if r.collected)
    no = sum(1 for r in rows if r.outcome in NOT_COLLECTED_SET)
    rec = sum(1 for r in rows if r.bank_received)
    ws.cell(2, 1, f"BS trips {len(rows)}  ·  collected {got}  ·  not collected {no}  ·  office received "
                  f"{sum(1 for r in rows if r.office)}  ·  bank received {rec}  ·  "
                  f"generated {datetime.now():%d/%m/%Y %I:%M %p}").font = Font(name="Calibri", size=10, color="475569")
    hr = 4
    for i, (h, w) in enumerate(BS_COLS, 1):
        x = ws.cell(hr, i, h)
        x.font = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
        x.fill = PatternFill("solid", fgColor=NAVY)
        x.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        x.border = BOX
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[hr].height = 30
    r = hr + 1
    prev_file = None
    shade = False
    images = []
    for row in rows:
        if (row.org, row.file_id) != prev_file:
            shade = not shade
            prev_file = (row.org, row.file_id)
        off = row.office
        cour = row.courier
        vals = [row.created, row.trip_id, row.file_no, row.applicant, row.bank_written, row.bank, row.bs_type, row.verifier,
                row.phone, row.trip_status, row.remarks,
                row.outcome + (f" · {row.outcome_note}" if row.outcome_note else ""),
                (f"{off.get('at', '').replace('T', ' ')} · {off.get('receiver', '')}" if off else ""),
                (f"{cour.get('name', '')} {cour.get('no', '')} · {cour.get('status', '')}".strip(" ·") if cour.get("no") else ""),
                "", (f"{row.bank_received.get('at', '')[:10]} ({row.bank_received.get('by', '')})" if row.bank_received else ""),
                row.where]
        for i, v in enumerate(vals, 1):
            x = ws.cell(r, i, v)
            x.font = Font(name="Calibri", size=10, bold=(i == 3))
            x.alignment = Alignment(vertical="top", wrap_text=True, horizontal="center" if i in (1, 2, 7, 10) else "left")
            x.border = BOX
            if shade:
                x.fill = PatternFill("solid", fgColor="F4F7FB")
        ws.cell(r, 1).number_format = "dd/mm/yy h:mm AM/PM"
        oc = ws.cell(r, 12)
        oc.font = Font(name="Calibri", size=10, bold=True,
                       color=GREEN if row.collected else (RED if row.outcome in NOT_COLLECTED_SET else (AMBER if row.outcome != PENDING else "475569")))
        ws.cell(r, 7).font = Font(name="Calibri", size=10, bold=True, color=BLUE if row.bs_type == "Online" else AMBER)
        height = max(30, min(400, 13 * max(1, len(row.remarks) // 42 + 1) + 6))
        slip = cour.get("slip")
        if slip and Path(slip).is_file():
            images.append((r, slip))
            height = max(height, 78)
        ws.row_dimensions[r].height = height
        r += 1
    for rr, slip in images:                                 # the courier slip at a moderate size (about 100 x 100 px)
        try:
            from openpyxl.drawing.image import Image as XLImage
            from PIL import Image as PILImage
            tmp = Path(tempfile.gettempdir()) / f"bs_slip_{Path(slip).stem}.png"
            im = PILImage.open(slip)
            im.thumbnail((100, 100))
            im.save(tmp)
            pic = XLImage(str(tmp))
            ws.add_image(pic, f"{get_column_letter(15)}{rr}")
        except Exception:
            ws.cell(rr, 15, Path(slip).name)
    ws.freeze_panes = ws.cell(hr + 1, 4)
    ws.auto_filter.ref = f"A{hr}:{get_column_letter(n)}{max(r - 1, hr + 1)}"
    ws.print_title_rows = f"{hr}:{hr}"
    # second sheet: the rules in words
    s = wb.create_sheet("How to read")
    for i, line in enumerate([
        "One row = one BS trip.  A file with two BS has two rows, one under the other (Trip ID tells them apart).",
        "BS Outcome comes from the verifier's exact remarks: hard / soft copy provided = collected; statement not verified, applicant "
        "disagreed, not possible = not collected; 'Check remark' = the program did not recognise the words.",
        "BS Type: Online / Offline from the bank list.  A short form that can mean two banks is counted Offline unless the words say which.",
        "Office Received: entered in the program when the verifier hands the paper in.  Bank Received: found in the client's signed list.",
    ], 1):
        s.cell(i, 1, line).alignment = Alignment(wrap_text=True, vertical="top")
        s.row_dimensions[i].height = 32
    s.column_dimensions["A"].width = 120
    from .pagesetup import a4
    a4(wb)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def write_receive_sheet(store: dict, path: Path, day: date | None = None) -> Path:
    """The A4 "আজ রিসিভ হয়েছে" (received today) sheet: print it at day end and sign it."""
    day = day or date.today()
    items = office_today(store, day)
    wb = Workbook()
    ws = wb.active
    ws.title = "Received today"
    heads = [("SL", 5), ("সময়", 9), ("File No", 22), ("Trip ID", 10), ("ব্যাংক", 20), ("কে দিল", 18), ("পাতা", 7), ("মন্তব্য", 22)]
    ws.merge_cells("A1:H1")
    t = ws.cell(1, 1, f"আজ রিসিভ হয়েছে  ·  Bank Statement  ·  {day:%d/%m/%Y}")
    t.font = Font(name="Calibri", size=15, bold=True, color=NAVY)
    ws.row_dimensions[1].height = 28
    ws.cell(2, 1, f"মোট {len(items)} টি  ·  Barikoi Technologies Limited").font = Font(name="Calibri", size=10, color="475569")
    for i, (h, w) in enumerate(heads, 1):
        x = ws.cell(4, i, h)
        x.font = Font(name="Calibri", bold=True, color="FFFFFF")
        x.fill = PatternFill("solid", fgColor=NAVY)
        x.alignment = Alignment(horizontal="center", vertical="center")
        x.border = BOX
        ws.column_dimensions[get_column_letter(i)].width = w
    r = 5
    for n, (tid, o) in enumerate(items, 1):
        at = o.get("at", "")
        vals = [n, at[11:16], o.get("file_no", ""), tid, o.get("bank", ""), o.get("giver", ""), o.get("pages", ""), o.get("note", "")]
        for i, v in enumerate(vals, 1):
            x = ws.cell(r, i, v)
            x.border = BOX
            x.font = Font(name="Calibri", size=11)
            x.alignment = Alignment(vertical="center", wrap_text=True, horizontal="center" if i in (1, 2, 4, 7) else "left")
        ws.row_dimensions[r].height = 22
        r += 1
    r += 2
    for i, lab in ((1, "রিসিভকারীর সই"), (5, "যাচাইকারীর সই")):
        ws.cell(r, i, "_______________________")
        ws.cell(r + 1, i, lab).font = Font(name="Calibri", size=10, color="475569")
    ws.print_title_rows = "4:4"
    from .pagesetup import a4
    a4(wb, portrait=("Received today",))
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


RECEIVE_TEMPLATE_HEADS = ["Date-Time", "Trip ID or File No", "Bank", "Given by", "Received by", "Pages", "Note"]


def write_receive_template(path: Path) -> Path:
    """The simple form to fill during the day (one row per BS) and upload."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Office receive"
    for i, h in enumerate(RECEIVE_TEMPLATE_HEADS, 1):
        x = ws.cell(1, i, h)
        x.font = Font(name="Calibri", bold=True, color="FFFFFF")
        x.fill = PatternFill("solid", fgColor=NAVY)
        x.border = BOX
        ws.column_dimensions[get_column_letter(i)].width = (17, 22, 20, 18, 16, 8, 26)[i - 1]
    ws.cell(2, 1, "15/11/2026 11:30").font = Font(color="94A3B8", italic=True)
    ws.cell(2, 2, "1234567  (or PL-2026...)").font = Font(color="94A3B8", italic=True)
    ws.freeze_panes = "A2"
    from .pagesetup import a4
    a4(wb, portrait=("Office receive",))
    wb.save(path)
    return path


def read_receive_upload(path: Path) -> list[dict]:
    """Rows of the filled form -> [{when, key, bank, giver, receiver, pages, note}] (sample / empty rows skipped)."""
    wb = load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    out = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        vals = list(row) + [None] * 7
        when, key = vals[0], vals[1]
        if key is None or "(or PL-" in str(key):
            continue
        if isinstance(when, str):
            for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %I:%M %p", "%d-%m-%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y"):
                try:
                    when = datetime.strptime(when.strip(), fmt)
                    break
                except ValueError:
                    continue
        out.append({"when": when if isinstance(when, datetime) else None, "key": str(key).strip(), "bank": str(vals[2] or ""),
                    "giver": str(vals[3] or ""), "receiver": str(vals[4] or ""), "pages": str(vals[5] or ""), "note": str(vals[6] or "")})
    return out


def find_row(rows: list[BSRow], key: str) -> list[BSRow]:
    """Trip ID, full File No, or the last digits of a File No -> matching BS rows (a File No can have two BS)."""
    k = (key or "").strip().upper()
    if not k:
        return []
    if k.isdigit():
        hit = [r for r in rows if str(r.trip_id) == k]
        if hit:
            return hit
        return [r for r in rows if re.sub(r"\D", "", r.file_no).endswith(k) and len(k) >= 4]
    k2 = re.sub(r"-+", "-", k)
    return [r for r in rows if re.sub(r"-+", "-", r.file_no.upper()) == k2]


def short_bank(name: str) -> str:
    return SHORT_NAME.get(name.replace(" (?)", ""), "")
