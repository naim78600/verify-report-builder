"""v16: read the bank's file list from photos (JPG / PNG ...), PDFs, Excel or CSV -> file numbers + applicant names.

The bank sends a table (photographed on a phone, or as a PDF) like:
    TAT 7+ | 523659 | Bijoy Talukder, NICU Incharge, Medical Centre Hospital, ... - 01760878559 | 11-Oct-2026 | ...
For every row we keep:
    * the file number the bank wrote (last digits, a full number such as PL-20261111070745532, or CPV-0229-AL);
    * every other file-number-like value of the same row (e.g. "PEC-20261007071238531" in another column, "(610885)")
      as extra keys to try;
    * the applicant name = the start of the name cell, up to the first comma;
    * the date of the row (used only to narrow a search by name).
Reading a photo uses the computer's own OCR (Windows OCR / macOS Vision; tesseract when present) WITH the position of
every word, so a row is put together by position, not by the order the OCR returns the lines.
The user sees the result as editable lines "number | name | date" before anything is searched.
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
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .file_history import IdEntry, make_entry, parse_ids_file

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic")

_PHONE = re.compile(r"(?<!\d)(?:\+?88)?01\d{9}(?!\d)")
_DATE = re.compile(r"(?<!\d)(\d{1,2})[-/ .]([A-Za-z]{3})[A-Za-z]*[-/ .,]*(\d{4}|\d{2})(?!\d)")
_FULL = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,3})\s*[-_]?\s*(\d{12,})(?!\d)")        # PL-20261111070745532, PEC-2026...
_CPV = re.compile(r"(?<![A-Za-z0-9])CPV\s*[-_]?\s*(\d{3,6})\s*[-_]?\s*([A-Za-z]{2})?", re.I)  # CPV-0229-AL
_NUM = re.compile(r"(?<![\d/:.-])\(?(\d{4,8})\)?(?![\d/:])")
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_JUNK_START = re.compile(r"^[^A-Za-z]+")
_MARK = re.compile(r"^(?:[A-Z]{0,3}\s*)?[7T]\s*[+4?]$|^TAT$", re.I)
_TITLES = re.compile(r"^(?:tat\s*7\+?\s*)", re.I)


@dataclass
class Box:
    """One word / phrase of a photo, position as fractions of the picture (0..1, top-left origin)."""
    x: float
    y: float
    w: float
    h: float
    text: str

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class ListRow:
    number: str                 # what the bank wrote (shown in the report)
    alts: list                  # other file-number-like values of the row
    name: str = ""
    row_date: date | None = None

    def to_line(self) -> str:
        nums = " / ".join([self.number or "?"] + [a for a in self.alts if a != self.number])
        d = f"{self.row_date:%d-%m-%Y}" if self.row_date else ""
        return " | ".join([nums, self.name, d]).rstrip(" |")


# ================================================================================================ OCR with positions
_WIN_OCR_BOXES = r"""
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
$W = [double]$bitmap.PixelWidth; $H = [double]$bitmap.PixelHeight
foreach ($line in $result.Lines) { foreach ($w in $line.Words) {
  $r = $w.BoundingRect
  "{0:F5}`t{1:F5}`t{2:F5}`t{3:F5}`t{4}" -f ($r.X / $W), ($r.Y / $H), ($r.Width / $W), ($r.Height / $H), $w.Text
} }
"""


def _parse_box_lines(out: str) -> list[Box]:
    boxes = []
    for ln in out.splitlines():
        p = ln.rstrip("\r").split("\t")
        if len(p) >= 5:
            try:
                boxes.append(Box(float(p[0]), float(p[1]), float(p[2]), float(p[3]), "\t".join(p[4:]).strip()))
            except ValueError:
                continue
    return [b for b in boxes if b.text]


def _prepare(path: Path) -> Path:
    """Upright, grey, large enough: phone photos are often rotated by EXIF and small text reads better bigger."""
    from PIL import Image, ImageOps
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("L")
    if max(im.size) < 2200:
        k = 2200 / max(im.size)
        im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    im = ImageOps.autocontrast(im, cutoff=1)
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    im.save(tmp)
    return Path(tmp)


def _tesseract_exe() -> str | None:
    exe = shutil.which("tesseract")
    if exe:
        return exe
    for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
              "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
        if Path(p).exists():
            return p
    return None


def _tesseract_boxes(img: Path) -> list[Box]:
    exe = _tesseract_exe()
    if not exe:
        return []
    from PIL import Image
    W, H = Image.open(img).size
    r = subprocess.run([exe, str(img), "-", "--psm", "6", "tsv"], capture_output=True, text=True, timeout=180,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    boxes = []
    for ln in r.stdout.splitlines()[1:]:
        p = ln.split("\t")
        if len(p) < 12 or not p[11].strip():
            continue
        try:
            if float(p[10]) < 10:                                # very low confidence: noise
                continue
            x, y, w, h = (int(p[6]), int(p[7]), int(p[8]), int(p[9]))
        except ValueError:
            continue
        boxes.append(Box(x / W, y / H, w / W, h / H, p[11].strip()))
    return boxes


def ocr_boxes(path: Path) -> list[Box]:
    """Words of a photo with their positions.  Windows: its own OCR; Mac: Vision (assets/bin/mac_ocr --boxes);
    otherwise / as a fallback: tesseract when installed."""
    img = _prepare(Path(path))
    try:
        if sys.platform.startswith("win"):
            with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as fh:
                fh.write(_WIN_OCR_BOXES)
                script = fh.name
            try:
                r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, str(img.resolve())],
                                   capture_output=True, text=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                boxes = _parse_box_lines(r.stdout) if r.returncode == 0 else []
                if boxes:
                    return boxes
            finally:
                Path(script).unlink(missing_ok=True)
        if sys.platform == "darwin":
            try:
                from .assets_path import asset
                exe = Path(asset("bin", "mac_ocr"))
                if exe.exists():
                    if not os.access(exe, os.X_OK):
                        exe.chmod(0o755)
                    r = subprocess.run([str(exe), "--boxes", str(img.resolve())], capture_output=True, text=True, timeout=180)
                    boxes = _parse_box_lines(r.stdout) if r.returncode == 0 else []
                    if boxes:
                        return boxes
            except Exception:                                     # noqa: BLE001
                pass
        boxes = _tesseract_boxes(img)
        if boxes:
            return boxes
    finally:
        img.unlink(missing_ok=True)
    raise ValueError("ছবি থেকে লেখা পড়া যায়নি। Windows বা Mac-এ চালান, অথবা PDF / Excel দিন।")


# ================================================================================================ rows from positions
def _num_tokens(text: str) -> list[str]:
    """File-number-like values in a piece of text (no phone numbers, no dates)."""
    t = _PHONE.sub(" ", text)
    t = _DATE.sub(" ", t)
    out = []
    for m in _FULL.finditer(t):
        out.append(f"{m.group(1).upper()}-{m.group(2)}")
    t2 = _FULL.sub(" ", t)
    for m in _CPV.finditer(t2):
        out.append(f"CPV-{m.group(1)}" + (f"-{m.group(2).upper()}" if m.group(2) else ""))
    t3 = _CPV.sub(" ", t2)
    t3 = re.sub(r"\bTAT\s*7\s*\+?", " ", t3, flags=re.I)
    for m in _NUM.finditer(t3):
        out.append(m.group(1))
    return out


def _row_date(text: str) -> date | None:
    for m in _DATE.finditer(text):
        d, mon, y = m.groups()
        mo = _MON.get(mon[:3].lower())
        if not mo:
            continue
        y = int(y) + (2000 if len(y) == 2 else 0)
        try:
            return date(y, mo, int(d))
        except ValueError:
            continue
    return None


def _clean_name(text: str) -> str:
    t = _PHONE.sub(" ", text)
    t = _TITLES.sub("", t.strip())
    t = t.split(",")[0]
    t = _JUNK_START.sub("", t)
    t = re.sub(r"[|_=~“”\"\[\]{}]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" .-")
    return t[:60]


def rows_from_boxes(boxes: list[Box]) -> list[ListRow]:
    """Group the words of one photo into table rows.
    1. Candidate numbers: words that are 4-8 digits (or a full file number / CPV-xxxx) - not phones, not dates.
    2. The file-number column = the x-position shared by most candidates (house numbers inside addresses fall out).
    3. Each candidate of that column starts a row; a row reaches half way to the next one (rows are centred).
    4. In the row: the name cell = the words right of the number column; name = its text up to the first comma.
       Other file-number-like values in the row (another column, "(610885)") become extra keys."""
    if not boxes:
        return []
    cands = []
    for b in boxes:
        for tok in _num_tokens(b.text):
            cands.append((b, tok))
    if not cands:
        return []
    # 2. the column: cluster the x centres
    xs = sorted(b.cx for b, _t in cands)
    best, best_n = xs[0], 0
    for x in xs:
        n = sum(1 for y in xs if abs(y - x) <= 0.05)
        if n > best_n:
            best, best_n = x, n
    col = [(b, t) for b, t in cands if abs(b.cx - best) <= 0.06]
    if len(col) < 1:
        return []
    col_right = max(b.x + b.w for b, _t in col)
    med_h = sorted(b.h for b in boxes)[len(boxes) // 2] or 0.01
    col.sort(key=lambda bt: bt[0].cy)
    # row markers: a column left of the numbers with the same short word in every row ("TAT 7+")
    marks = sorted((b for b in boxes if _MARK.match(b.text.strip()) and b.cx < best - 0.03), key=lambda b: b.cy)
    centres_m: list[float] = []
    for b in marks:
        if not centres_m or b.cy - centres_m[-1] > 1.5 * med_h:
            centres_m.append(b.cy)
    groups: list[list] = []
    for b, t in col:
        near = 3.5 if (t.startswith("CPV") or b.text.strip().startswith("(")) else 2.2
        if groups and b.cy - groups[-1][-1][0].cy < near * med_h:
            groups[-1].append((b, t))
        else:
            groups.append([(b, t)])
    centres = [sum(b.cy for b, _t in g) / len(g) for g in groups]
    if len(centres_m) >= 3 and len(centres) >= 2:            # a marker with no number next to it = a row the OCR missed
        gaps = sorted(b - a for a, b in zip(centres, centres[1:]))
        step = gaps[len(gaps) // 2]
        for m in centres_m:
            if all(abs(m - c) > 0.45 * step for c in centres):
                centres.append(m)
                groups.append([])
        order = sorted(range(len(centres)), key=lambda i: centres[i])
        centres = [centres[i] for i in order]
        groups = [groups[i] for i in order]
    rows = []
    for i, g in enumerate(groups):
        top = (centres[i - 1] + centres[i]) / 2 if i else -1
        bot = (centres[i] + centres[i + 1]) / 2 if i + 1 < len(groups) else 2
        band = [b for b in boxes if top <= b.cy < bot]
        name_words = sorted([b for b in band if b.x >= col_right - 0.005], key=lambda b: b.cy)
        lines: list[list] = []
        for b in name_words:
            if lines and abs(b.cy - lines[-1][0].cy) <= 0.6 * med_h:
                lines[-1].append(b)
            else:
                lines.append([b])
        cell = []
        for ln in lines:                                        # stop at the next column (date / items): keep the first block
            ln = sorted(ln, key=lambda b: b.x)
            cell.append(" ".join(b.text for b in ln))
        name_text = " ".join(cell)
        # the name cell ends where the date column starts: cut at a date
        mdate = _DATE.search(name_text)
        name = _clean_name(name_text[:mdate.start()] if mdate and mdate.start() > 3 else name_text)
        nums = [t for _b, t in g]
        if not nums and not name:
            continue
        band_text = " ".join(b.text for b in band)
        for t in _num_tokens(band_text):
            if t not in nums and (len(re.sub(r"\D", "", t)) >= 12 or t.startswith("CPV")):
                nums.append(t)                                   # another column: full number / CPV reference
        main = next((t for t in nums if not t.startswith("CPV") and len(re.sub(r"\D", "", t)) < 12), nums[0] if nums else "")
        rows.append(ListRow(main, [t for t in nums if t != main], name, _row_date(band_text)))
    return rows


# ================================================================================================ text (PDF with text)
def rows_from_text(text: str) -> list[ListRow]:
    """PDF / pasted text without positions: a row ends at the phone number of the name cell."""
    rows, buf = [], []
    for ln in text.splitlines():
        buf.append(ln)
        if _PHONE.search(ln):
            rows.append(" ".join(buf))
            buf = []
    if buf:
        rows.append(" ".join(buf))
    out = []
    for r in rows:
        nums = _num_tokens(r)
        if not nums:
            continue
        main = next((t for t in nums if not t.startswith("CPV") and len(re.sub(r"\D", "", t)) < 12), nums[0])
        rest = r
        for t in nums:
            rest = rest.replace(t, " ")
        rest = re.sub(r"\bTAT\s*7\s*\+?", " ", rest, flags=re.I)
        d = _row_date(r)
        mdate = _DATE.search(rest)
        name = _clean_name(rest[:mdate.start()] if mdate and mdate.start() > 3 else rest)
        out.append(ListRow(main, [t for t in nums if t != main], name, d))
    return out


# ================================================================================================ files -> rows
def _pdf_rows(path: Path) -> list[ListRow]:
    from pypdf import PdfReader
    rd = PdfReader(str(path))
    text = "\n".join((pg.extract_text() or "") for pg in rd.pages)
    if len(_num_tokens(text)) >= 1 and text.strip():
        return rows_from_text(text)
    rows = []                                                   # a scanned PDF: read the pictures inside it
    with tempfile.TemporaryDirectory() as td:
        n = 0
        for pg in rd.pages:
            for im in getattr(pg, "images", []):
                n += 1
                p = Path(td) / f"p{n}{Path(im.name).suffix or '.png'}"
                p.write_bytes(im.data)
                rows += rows_from_boxes(ocr_boxes(p))
    return rows


def read_rows(paths) -> tuple[list[ListRow], list[str]]:
    """Every chosen file -> rows (in order, the same number only once) + problems to show."""
    rows, problems, seen = [], [], set()
    for p in map(Path, paths):
        try:
            suf = p.suffix.lower()
            if suf in IMAGE_EXT:
                got = rows_from_boxes(ocr_boxes(p))
            elif suf == ".pdf":
                got = _pdf_rows(p)
            elif suf in (".xlsx", ".xlsm", ".csv", ".txt"):
                got = [ListRow(e.raw, [], getattr(e, "name", ""), None) for e in parse_ids_file(p)]
            else:
                raise ValueError(f"এই ধরনের ফাইল পড়া যায় না: {suf}")
            if not got:
                problems.append(f"{p.name}: কোনো ফাইল নম্বর পাওয়া যায়নি")
        except ValueError as exc:
            problems.append(f"{p.name}: {exc}")
            got = []
        except Exception as exc:                                  # noqa: BLE001
            problems.append(f"{p.name}: {type(exc).__name__}: {exc}")
            got = []
        from .file_history import names_match
        for r in got:
            key = re.sub(r"\D", "", r.number) or r.number
            if key and key in seen:                               # overlapping photos of the same list
                continue
            if not key and (not r.name or any(names_match(r.name, o.name) for o in rows)):
                continue                                          # a row without a number that is already in the list
            seen.add(key)
            rows.append(r)
    return rows, problems


def rows_to_text(rows: list[ListRow]) -> str:
    return "\n".join(r.to_line() for r in rows)
