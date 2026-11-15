"""Files shipped with the program (logo, fonts, voice clips, the WhatsApp helper extension).

Works from source and from the PyInstaller bundle (where the files sit under sys._MEIPASS/report_builder/assets)."""
from __future__ import annotations

import sys
from pathlib import Path


def asset(*parts: str) -> Path:
    here = Path(__file__).resolve().parent / "assets"
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "_MEIPASS", None) else None
    for root in ([base / "report_builder" / "assets", base / "assets"] if base else []) + [here]:
        p = root.joinpath(*parts)
        if p.exists():
            return p
    return here.joinpath(*parts)
