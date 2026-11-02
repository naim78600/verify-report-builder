"""Built-in holiday list + user additions (editable from the window).

TAT counting skips Friday & Saturday automatically; this list holds the extra
(public) holidays only. Dates already in the tracker's own Holidays sheet are
included as they are (they run to 2026-10-31). Everything after that comes from
the government list (2026) and estimates for 2027 - the user adds later dates in
the window ("ছুটির তালিকা"), stored in ~/.verify_report_builder/holidays.json.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import config

TRACKER_DATES = [
    "2025-03-26", "2025-03-27", "2025-03-30", "2025-03-31", "2025-04-01", "2025-04-02",
    "2025-04-03", "2025-04-14", "2025-06-05", "2025-06-06", "2025-06-07", "2025-06-08",
    "2025-06-09", "2025-06-10", "2025-06-11", "2025-06-12", "2025-06-13", "2025-06-14",
    "2025-06-20", "2025-06-21", "2025-06-27", "2025-06-28", "2025-07-04", "2025-07-05",
    "2025-07-06", "2025-07-11", "2025-07-12", "2025-07-18", "2025-07-19", "2025-07-25",
    "2025-07-26", "2025-08-05", "2025-08-08", "2025-08-09", "2025-08-15", "2025-08-16",
    "2025-08-22", "2025-08-23", "2025-08-29", "2025-08-30", "2025-09-05", "2025-09-06",
    "2025-09-12", "2025-09-13", "2025-09-19", "2025-09-20", "2025-09-26", "2025-09-27",
    "2025-12-16", "2025-12-25", "2025-12-31", "2026-02-04", "2026-02-11", "2026-02-12",
    "2026-03-17", "2026-03-18", "2026-03-19", "2026-03-22", "2026-03-23", "2026-03-26",
    "2026-04-14", "2026-05-25", "2026-05-26", "2026-05-27", "2026-05-28", "2026-05-31",
    "2026-07-01", "2026-08-05", "2026-08-26", "2026-09-04", "2026-09-05", "2026-09-11",
    "2026-09-12", "2026-09-18", "2026-09-19", "2026-09-25", "2026-09-26", "2026-10-02",
    "2026-10-03", "2026-10-09", "2026-10-10", "2026-10-16", "2026-10-20", "2026-10-21",
    "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-30", "2026-10-31",
]

# (from, to, name, source)  source: "সরকারি" = official gazette, "আনুমানিক" = estimate
BUILTIN_RANGES = [
    ("2026-12-16", "2026-12-16", "Victory Day", "সরকারি"),
    ("2026-12-25", "2026-12-25", "Christmas Day", "সরকারি"),
    ("2027-01-24", "2027-01-24", "Shab-e-Barat", "আনুমানিক"),
    ("2027-02-21", "2027-02-21", "Shaheed Day", "নির্দিষ্ট"),
    ("2027-03-06", "2027-03-06", "Shab-e-Qadr", "আনুমানিক"),
    ("2027-03-09", "2027-03-11", "Eid ul Fitr", "আনুমানিক"),
    ("2027-03-26", "2027-03-26", "Independence Day", "নির্দিষ্ট"),
    ("2027-04-14", "2027-04-14", "Pahela Baishakh", "নির্দিষ্ট"),
    ("2027-05-01", "2027-05-01", "May Day", "নির্দিষ্ট"),
    ("2027-05-16", "2027-05-18", "Eid ul Azha", "আনুমানিক"),
    ("2027-05-20", "2027-05-20", "Buddha Purnima", "আনুমানিক"),
    ("2027-06-15", "2027-06-15", "Ashura", "আনুমানিক"),
    ("2027-08-05", "2027-08-05", "Mass Uprising Day", "নির্দিষ্ট"),
    ("2027-08-15", "2027-08-15", "Eid-e-Miladunnabi", "আনুমানিক"),
    ("2027-08-25", "2027-08-25", "Janmashtami", "আনুমানিক"),
    ("2027-10-09", "2027-10-09", "Durga Puja", "আনুমানিক"),
    ("2027-12-16", "2027-12-16", "Victory Day", "নির্দিষ্ট"),
    ("2027-12-25", "2027-12-25", "Christmas Day", "নির্দিষ্ট"),
]

HOLIDAY_FILE = config.SETTINGS_DIR / "holidays.json"


def _d(s: str) -> date:
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def _expand(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def builtin() -> dict[date, str]:
    out: dict[date, str] = {_d(s): "Tracker holiday list" for s in TRACKER_DATES}
    for a, b, name, _src in BUILTIN_RANGES:
        for d in _expand(_d(a), _d(b)):
            out[d] = name
    return out


def _load_user(path: Path | None = None) -> dict:
    try:
        return json.loads((path or HOLIDAY_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {"added": [], "removed": []}


def load(path: Path | None = None) -> dict[date, str]:
    """All holidays: built-in + user added - user removed."""
    out = builtin()
    user = _load_user(path)
    for item in user.get("added", []):
        try:
            for d in _expand(_d(item["from"]), _d(item["to"])):
                out[d] = item.get("name") or "Holiday"
        except Exception:
            continue
    for s in user.get("removed", []):
        try:
            out.pop(_d(s), None)
        except Exception:
            continue
    return out


def _save_user(data: dict, path: Path | None = None) -> None:
    p = path or HOLIDAY_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_line(line: str) -> tuple[date, date, str]:
    """'2027-03-09 | 2027-03-11 | Eid ul Fitr'  (end date may be empty; | , ; tab all accepted)."""
    parts = [p.strip() for p in re.split(r"[|;,\t]", line.strip()) if p.strip() != ""]
    if not parts:
        raise ValueError("ফাঁকা লাইন")
    try:
        start = _d(parts[0])
    except ValueError:
        raise ValueError(f"তারিখ ঠিক নয়: {parts[0]} (লিখুন YYYY-MM-DD, যেমন 2027-03-09)") from None
    end, name = start, ""
    rest = parts[1:]
    if rest and re.fullmatch(r"\d{4}-\d{2}-\d{2}", rest[0]):
        end = _d(rest[0])
        rest = rest[1:]
    if end < start:
        raise ValueError("শেষ তারিখ শুরুর আগে হতে পারে না")
    if rest:
        name = " ".join(rest)
    return start, end, name or "Holiday"


def add_ranges(lines: list[str], path: Path | None = None) -> tuple[int, list[str]]:
    """Add many lines. Returns (days_added, error_messages)."""
    user = _load_user(path)
    errors, n = [], 0
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            a, b, name = parse_line(line)
        except ValueError as exc:
            errors.append(f"লাইন {i}: {exc}")
            continue
        user.setdefault("added", []).append({"from": a.isoformat(), "to": b.isoformat(), "name": name})
        user["removed"] = [r for r in user.get("removed", []) if not (a <= _d(r) <= b)]
        n += (b - a).days + 1
    _save_user(user, path)
    return n, errors


def import_file(path: Path) -> tuple[int, list[str]]:
    """CSV / text file: one holiday per line, same format as add_ranges."""
    lines: list[str] = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        for row in csv.reader(fh):
            if row and not row[0].lower().startswith(("date", "from", "শুরু")):
                lines.append("|".join(row))
    return add_ranges(lines)


def remove_date(d: date, path: Path | None = None) -> None:
    user = _load_user(path)
    user.setdefault("removed", []).append(d.isoformat())
    _save_user(user, path)


def last_date() -> date:
    return max(load()) if load() else date(2000, 1, 1)


def needs_update(today: date | None = None) -> bool:
    """True when the list ends within 30 days (reminder in the window)."""
    today = today or date.today()
    return last_date() < today + timedelta(days=30)


def count_business_days(start: date, end: date, holidays: set[date]) -> int:
    """Excel NETWORKDAYS.INTL(start, end, "0000110", holidays): Friday+Saturday off. Negative if start>end."""
    sign = 1
    if start > end:
        start, end, sign = end, start, -1
    n, d = 0, start
    while d <= end:
        if d.weekday() not in (4, 5) and d not in holidays:   # Mon=0 ... Fri=4, Sat=5
            n += 1
        d += timedelta(days=1)
    return sign * n
