"""v16: the bank's list from a photo / PDF, and the search order number -> other number of the row -> applicant name."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from report_builder.file_history import find_files, make_entry, parse_ids_text  # noqa: E402
from report_builder.list_reader import Box, ListRow, rows_from_boxes, rows_from_text, rows_to_text  # noqa: E402


def _row(y, *cells):
    """cells: (x, text) - one box per cell line."""
    return [Box(x, y, 0.08 if x < 0.3 else 0.3, 0.012, t) for x, t in cells]


def _photo():
    b = []
    b += _row(0.10, (0.05, "TAT"), (0.09, "7+"), (0.20, "523659"), (0.35, "Bijoy Talukder, NICU Incharge,"), (0.75, "11-Oct-2026"))
    b += _row(0.115, (0.35, "Medical Centre, 953, O.R Nizam Road,"))
    b += _row(0.13, (0.35, "Chattogram- 01760878559"))
    b += _row(0.20, (0.05, "TAT"), (0.09, "7+"), (0.35, "Md Arif Mia, Field Supervisor,"), (0.75, "11-Nov-2026"))   # number not read
    b += _row(0.215, (0.35, "TMSS, Chandpur- 01897612874"))
    b += _row(0.29, (0.20, "CPV-0229-AL"), (0.35, "Mohammad Tanvir Mizan"), (0.75, "24-Sep-2026"))
    b += _row(0.30, (0.05, "TAT"), (0.09, "7+"))
    b += _row(0.31, (0.20, "(610885)"))
    b += _row(0.40, (0.05, "TAT"), (0.09, "7+"), (0.20, "813507"), (0.35, "Sabit Al Mujahid, Executive- I,"), (0.65, "PEC-20261007071238531"))
    b += _row(0.415, (0.35, "Plot- 1088, Dhaka-1207- 01821469113"), (0.75, "10-Nov-2026"))
    return b


def test_rows_from_a_photo_by_position():
    rows = rows_from_boxes(_photo())
    assert [r.number for r in rows] == ["523659", "", "610885", "813507"]
    assert rows[0].name == "Bijoy Talukder" and rows[0].row_date == date(2026, 10, 11)
    assert rows[1].name == "Md Arif Mia" and rows[1].row_date == date(2026, 11, 11)          # TAT marker row kept
    assert rows[2].alts == ["CPV-0229-AL"] and rows[2].name == "Mohammad Tanvir Mizan"
    assert rows[3].alts == ["PEC-20261007071238531"] and "1088" not in rows[3].alts          # house number is not a file no
    text = rows_to_text(rows)
    assert text.splitlines()[1].startswith("? | Md Arif Mia")


def test_rows_from_pdf_text():
    t = "TAT 7+ 145532 Shriti Rani Bala, Staff Nurse, Labaid - 01869744670 11-Nov-2026\nTAT 7+ 256737 Md Tanvir Ahmed, Senior Executive - 01777371467"
    rows = rows_from_text(t)
    assert [(r.number, r.name) for r in rows] == [("145532", "Shriti Rani Bala"), ("256737", "Md Tanvir Ahmed")]


def test_editable_lines_back_to_entries():
    es = parse_ids_text("523659 | Bijoy Talukder | 11-10-2026\n? | Md Arif Mia | 11-11-2026\n610885 / CPV-0229-AL | Mohammad Tanvir Mizan\n12345 67890")
    assert [(e.raw, e.kind) for e in es] == [("523659", "suffix"), ("(Md Arif Mia)", "name"), ("610885", "suffix"), ("12345", "suffix"), ("67890", "suffix")]
    assert es[0].name == "Bijoy Talukder" and es[0].row_date == date(2026, 10, 11)
    assert [a.raw for a in es[2].alts] == ["CPV-0229-AL"] and es[2].alts[0].digits == "0229"
    assert make_entry("CPV-0266-HL").digits == "0266"


class FakeNames:
    def __init__(self, rows):
        self.rows = rows

    def between(self, a, b):
        return [r for r in self.rows if a.isoformat() <= r[2] <= b.isoformat()]

    def names_of(self, fid, _start):
        return next((r[3] for r in self.rows if r[0] == fid), "")


TABLE = [(1, "PL-0229", "2026-09-24", "PL0229", "0229"),
         (2, "PL-20261111070745532", "2026-11-11", "PL20261111070745532", "20261111070745532"),
         (3, "CC-20261007071238531", "2026-10-07", "CC20261007071238531", "20261007071238531"),
         (4, "CC-20260300266", "2026-03-03", "CC20260300266", "20260300266"),
         (5, "PL-0266", "2026-10-11", "PL0266", "0266"),
         (6, "PL-010164", "2025-05-13", "PL010164", "010164")]
NAMES = FakeNames([(1, "PL-0229", "2026-09-24", "MOHAMMAD TANVIR MIZAN|SHAMIMA AKHTER"), (2, "PL-20261111070745532", "2026-11-11", "Shriti Rani Bala"),
                   (3, "CC-20261007071238531", "2026-10-07", "SABIT AL MUJAHID"), (4, "CC-20260300266", "2026-03-03", "MD SHAHNAWAZ"),
                   (5, "PL-0266", "2026-10-11", "ABU TAHER KHAN|ZAKIA SULTANA"), (6, "PL-010164", "2025-05-13", "MD. SUMON MIA")])


def _e(line):
    return parse_ids_text(line)[0]


def test_search_order_number_alt_name():
    today = date(2026, 11, 23)
    # several files end with 0266: only the one with the applicant's name is kept
    got, note = find_files(TABLE, _e("CPV-0266-HL | Abu Taher Khan | 11-10-2026"), today, NAMES)
    assert [g[0] for g in got] == [5] and note == ""
    # the list's number is not a file number, the other number of the row is
    got, note = find_files(TABLE, _e("610885 / CPV-0229-AL | Mohammad Tanvir Mizan | 24-09-2026"), today, NAMES)
    assert [g[0] for g in got] == [1] and note.startswith("Found by CPV-0229-AL")
    # one digit wrong (145532 for ...745532) + same name
    got, note = find_files(TABLE, _e("145532 | Shriti Rani Bala"), today, NAMES)
    assert [g[0] for g in got] == [2] and "one digit off" in note
    # a different number, same name, received near the list's date
    got, note = find_files(TABLE, _e("813507 | Sabit Al Mujahid | 10-11-2026"), today, NAMES)
    assert [g[0] for g in got] == [3] and "date of the list" in note
    # a similar name long ago is NOT taken (Md Sumen Miah, 15-Oct-2026 vs MD. SUMON MIA, 2025)
    got, note = find_files(TABLE, _e("948905 | Md Sumen Miah | 15-10-2026"), today, NAMES)
    assert got == [] and note == ""
    # no name: exactly as before
    got, note = find_files(TABLE, make_entry("0266"), today, NAMES)
    assert sorted(g[0] for g in got) == [4, 5] and note == ""
