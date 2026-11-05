"""Writes the outputs of one Prime Bank run: ONE editable Excel (the file that is e-mailed), an optional PDF, the Re-CPV workbook."""
from __future__ import annotations

import re
from pathlib import Path

from .collect_prime import PrimeData
from .prime_excel import build_prime_excel
from .prime_pdf import build_prime_pdf
from .recpv_excel import build_recpv_workbook

PHASE_FILE = {"3pm": "Phase1", "7pm": "Phase2"}


def base_name(d: PrimeData) -> str:
    if d.mode == "tracker":
        return f"Prime_Bank_Submission_Tracker_{d.report_date:%Y-%m-%d}_{PHASE_FILE.get(d.slot, d.slot)}"
    return f"Prime_Bank_Report_{d.w_from:%Y%m%d}-{d.w_till:%Y%m%d}"


def _stem(d: PrimeData) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", base_name(d))


def write_prime_outputs(d: PrimeData, out_dir: Path, excel: bool = True, pdf: bool = False) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    if excel:
        paths.append(build_prime_excel(d, out_dir / f"{_stem(d)}.xlsx"))
    if pdf:
        paths.append(build_prime_pdf(d, out_dir / f"{_stem(d)}.pdf", False))
    return paths


def strip_checklist(src: Path, dst: Path) -> Path:
    """Copy of an edited workbook WITHOUT the internal "Check List" sheet (everything else, incl. the user's edits, is kept)."""
    from openpyxl import load_workbook
    wb = load_workbook(src, rich_text=True)
    if "Check List" in wb.sheetnames:
        del wb["Check List"]
    wb.active = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return dst


def has_checklist(path: Path) -> bool:
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True)
    try:
        return "Check List" in wb.sheetnames
    finally:
        wb.close()


def count_blue_cells(path: Path) -> int:
    """Light sky-blue "please check" cells in the Complete / Incomplete sheets of a (possibly hand-edited) workbook."""
    from openpyxl import load_workbook
    from . import theme as T
    want = "00" + T.CHECK.upper()
    wb = load_workbook(path, read_only=True)
    n = 0
    try:
        for name in ("Complete Report", "Incomplete Report"):
            if name not in wb.sheetnames:
                continue
            for row in wb[name].iter_rows():
                for c in row:
                    fg = getattr(getattr(c.fill, "fgColor", None), "rgb", None)
                    if c.fill is not None and c.fill.fill_type == "solid" and isinstance(fg, str) and fg.upper().endswith(want[2:]):
                        n += 1
    finally:
        wb.close()
    return n


def write_recpv_workbook(d: PrimeData, out_dir: Path) -> Path:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", base_name(d).replace("Submission_Tracker", "Report"))
    return build_recpv_workbook(d, out_dir / f"{stem}_with_ReCPV.xlsx")
