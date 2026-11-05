"""Writes every requested output of one Prime Bank run (Excel / PDF / e-mail page / Re-CPV workbook)."""
from __future__ import annotations

import re
from pathlib import Path

from .collect_prime import PrimeData
from .email_copy import build_email_html
from .prime_excel import build_prime_excel
from .prime_pdf import build_prime_pdf
from .recpv_excel import build_recpv_workbook


def base_name(d: PrimeData) -> str:
    if d.mode == "tracker":
        return f"Prime_Bank_{d.report_date:%Y-%m-%d}_{d.slot}_Submission_Tracker"
    return f"Prime_Bank_Report_{d.w_from:%Y%m%d}-{d.w_till:%Y%m%d}"


def write_prime_outputs(d: PrimeData, out_dir: Path, excel: bool = True, pdf: bool = True,
                        internal: bool = True, bank: bool = True, email: bool = False) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", base_name(d))
    paths: list[Path] = []
    copies = []
    if bank:
        copies.append(("", False))
    if internal:
        copies.append(("_INTERNAL", True))
    for suffix, is_internal in copies:
        if excel:
            paths.append(build_prime_excel(d, out_dir / f"{stem}{suffix}.xlsx", is_internal))
        if pdf:
            paths.append(build_prime_pdf(d, out_dir / f"{stem}{suffix}.pdf", is_internal))
    if email:
        paths.append(build_email_html(d, out_dir / f"{stem}_email.html"))
    return paths


def write_recpv_workbook(d: PrimeData, out_dir: Path) -> Path:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", base_name(d).replace("Submission_Tracker", "Report"))
    return build_recpv_workbook(d, out_dir / f"{stem}_with_ReCPV.xlsx")
