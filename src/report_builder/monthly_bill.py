"""Monthly bill (v6) - one click: pick a month, get the Card bill and the Loan bill (Excel + PDF), in the format of the
invoice that has always been sent to the bank.

WHAT IS BILLED
    Everything that was CREATED on the dashboard between the first and the last day of the month: a new file (its package), a
    Re-CPV trip, an extra trip / extra document.  Whether it has been submitted does not matter (a row that is still pending has
    an empty submission date).  The bill rows are the SAME rows the daily tracker shows (billing.build_rows), so the tracker and
    the bill can never disagree.
    Not billed: a test file, a Withdrawn trip, and a Canceled trip that nobody ever started.  An Inactive trip IS billed.

RATES (BDT, from the September 2026 invoice)          In station (Dhaka / Chattogram city)     Out station
    Card package                                              450                                 600
    Loan package                                              600                                 700
    single document (salary certificate / pay slip / LOI / signature)   140                       170
    single house / office / bank statement                              140                       240
    PG verification (house + office / business + signature)             140                       230
    VAT 5 % on the amount after the penalty.

PENALTY     Extra TAT 1 day = 20 %, 2 days = 30 %, 3 days or more = 50 % of the amount of that row (In and Out alike).
    Every row with an Extra TAT is LISTED on the "Penalty" sheet.  Apply starts as Yes for a submitted PACKAGE or BANK STATEMENT (what
    the manual bill charges) and as No for an extra document / Re-CPV row and for a row that is not submitted yet.  Change Yes / No
    freely (the bank caused the delay ...) - every total in the workbook follows at once, and "PDF from the edited Excel" makes the
    PDF with exactly those choices.

CHECK SHEET   what the dashboard has for the month against what is on the bill, and every row that was left out, with the reason.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .billing import SLAB_DOC, SLAB_PG, BillRow, is_test_file

VAT_PCT = 5
PKG_RATE = {("Card", "In"): 450, ("Card", "Out"): 600, ("Loan", "In"): 600, ("Loan", "Out"): 700}
SINGLE_IN = 140
SINGLE_OUT = {"doc": 170, "house": 240, "pg": 230}
PENALTY_PCT = {1: 20, 2: 30}          # Extra TAT days -> % ; 3 or more = 50 %
PENALTY_MAX = 50

IN_NAME = "Instation - Dhaka City & Chattagram City"
OUT_NAME = "Outstation - Outside Dhaka City & Chattagram City"
ORG_TO = ("To,", "Head of Retail, Prime Bank PLC", "Facilities Tower, Kha-199/2, Maddhya Badda, Pragati Sarani, Dhaka-1212.")
PAY_TO = ("Please Pay To - Barikoi Technologies Limited - BIN: 003495542-0408", "Prime Bank Plc, Pallabi Branch, Dhaka",
          "Account Number: 2164139026686", "Routing Number: 170262580")
ADDRESS = ("Dr Mohsin Plaza, House 2/7, Pallabi, Mirpur, Dhaka-1216", "Phone: +8801708-549077, Email: hello@barikoi.com")

# section key -> (station, title on the summary page, heading on the detail pages)
SECTIONS = {
    "Card": [
        ("in_pkg", "In", "Card", "Card"),
        ("in_single", "In", "ReCpv-Single Trips (Salary Certificate/Pay Slip/LOI)",
         "Single Document(Salary Certificate/Pay Slip/LOI/Signature) Verification"),
        ("out_pkg", "Out", "Card", "Card"),
        ("out_house", "Out", "ReCpv-Card Single House(Residence,Office Verification)",
         "Single Trips (House/Office/Rent/Practice Income/Trade License) Verification"),
        ("out_doc", "Out", "ReCpv Single Document(Salary Certificate/Pay Slip/LOI/Signature/BS) Verification",
         "Single Document(Salary Certificate/Pay Slip/LOI/Signature) Verification"),
        ("out_pg", "Out", "ReCpv PG( Residence+office/Business+ Signature)", "ReCpv PG( Residence+office/Business+ Signature)"),
    ],
    "Loan": [
        ("in_pkg", "In", "Personal Loan", "Personal Loan"),
        ("in_single", "In", "ReCpv Single Document(Salary Certificate/Pay Slip/LOI/Signature) Verification",
         "Single Trips (House/Office/Rent/Practice Income/Trade License/Document)"),
        ("out_pkg", "Out", "Personal Loan", "Personal Loan"),
        ("out_house", "Out", "ReCpv Single House(Residence,Office Verification)", "ReCpv Single House(Residence,Office Verification)"),
        ("out_doc", "Out", "ReCpv Single Document(Salary Certificate/Pay Slip/LOI/Signature/BS) Verification",
         "Single Document(Salary Certificate/Pay Slip/LOI/Signature) Verification"),
        ("out_pg", "Out", "ReCpv PG( Residence+office/Business+ Signature)", "ReCpv PG( Residence+office/Business+ Signature)"),
    ],
}
ALWAYS = {"Card": ("in_pkg", "in_single", "out_pkg", "out_house", "out_doc"),
          "Loan": ("in_pkg", "in_single", "out_pkg", "out_house", "out_doc", "out_pg")}     # lines printed even with Qty 0


def month_window(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def month_name(month: int) -> str:
    return calendar.month_name[month]


def bill_ref(year: int, month: int) -> str:
    return f"Barikoi/PrimeBank/CPVBill-{month_name(month)}/{year}/{month:02d}"


def slab_class(r: BillRow) -> str:
    """Package | doc | house | pg  (a bank statement is priced with house / office, as on the invoices)."""
    if r.kind == "Package":
        return "Package"
    if r.slab == SLAB_PG:
        return "pg"
    if r.slab in ("Single House", "Single Office", "BS"):
        return "house"
    return "doc"


def rate_for(file_type: str, cls: str, area: str) -> int:
    if cls == "Package":
        return PKG_RATE[(file_type, area)]
    return SINGLE_IN if area == "In" else SINGLE_OUT[cls]


def section_key(cls: str, area: str) -> str:
    if cls == "Package":
        return "in_pkg" if area == "In" else "out_pkg"
    return "in_single" if area == "In" else f"out_{cls}"


def penalty_pct(extra_tat) -> int:
    n = int(extra_tat or 0)
    if n <= 0:
        return 0
    return PENALTY_PCT.get(n, PENALTY_MAX)


def category_of(r: BillRow, cls: str) -> str:
    ft = r.file_type
    if cls == "Package":
        return "Card" if ft == "Card" else "Package"
    what = {"Single House": "House", "Single Office": "Office", "BS": "Bank", SLAB_PG: "PG", SLAB_DOC: "Document"}.get(r.slab, "Single")
    lead = "ReCPV" if r.kind == "ReCpv" else "Extra"
    return f"{lead}({what})"


@dataclass
class Item:
    file_type: str = ""
    section: str = ""
    area: str = "In"
    cls: str = ""
    file_no: str = ""
    applicant: str = ""
    rec: date | None = None
    sub: date | None = None
    tat: int | None = None
    extra_tat: int = 0
    amount: int = 0
    category: str = ""
    kind: str = ""
    slab: str = ""
    trip_ids: str = ""
    trip_status: str = ""
    note: str = ""
    pct: int = 0                 # penalty % this row is liable to (0 = none)
    apply: bool = True           # the penalty is charged (False = waived by the user)
    pen_note: str = ""           # why Apply starts as Yes / No

    @property
    def deduction(self) -> float:
        return self.amount * self.pct / 100 if (self.pct and self.apply) else 0


@dataclass
class Bill:
    year: int = 0
    month: int = 0
    file_type: str = ""          # Card | Loan
    bill_date: date | None = None
    items: list = field(default_factory=list)

    @property
    def title(self) -> str:
        return f"Verification Bill For {month_name(self.month)} {self.year} - {self.file_type}"

    def lines(self) -> list:
        """Summary lines: (section key, station, title, qty, unit price, amount)."""
        out = []
        for key, station, title, _detail in SECTIONS[self.file_type]:
            rows = [i for i in self.items if i.section == key]
            if not rows and key not in ALWAYS[self.file_type]:
                continue
            cls = "Package" if key.endswith("pkg") else ("house" if key == "in_single" else key.split("_")[1])
            unit = rate_for(self.file_type, cls, station)
            out.append((key, station, title, len(rows), unit, sum(i.amount for i in rows)))
        return out

    def penalty_lines(self) -> list:
        """(station, title, pct, qty, deduction) for every charged penalty, grouped."""
        out = []
        for station in ("In", "Out"):
            for pk, title in ((True, f"{'Card' if self.file_type == 'Card' else 'Loan'} ({station} Station)"),
                              (False, f"Single Trips / ReCpv ({station} Station)")):
                for pct in sorted(set(PENALTY_PCT.values()) | {PENALTY_MAX}):
                    rows = [i for i in self.items if i.area == station and (i.cls == "Package") == pk and i.pct == pct and i.apply]
                    if rows:
                        out.append((station, title, pct, len(rows), sum(i.deduction for i in rows)))
        return out

    @property
    def subtotal(self) -> float:
        return sum(i.amount for i in self.items)

    @property
    def deduction(self) -> float:
        return sum(i.deduction for i in self.items)

    @property
    def after_penalty(self) -> float:
        return self.subtotal - self.deduction

    @property
    def vat(self) -> float:
        return round(self.after_penalty * VAT_PCT / 100, 2)

    @property
    def grand_total(self) -> float:
        return round(self.after_penalty + self.vat, 2)


@dataclass
class MonthBill:
    year: int = 0
    month: int = 0
    bills: dict = field(default_factory=dict)          # "Card" / "Loan" -> Bill
    excluded: list = field(default_factory=list)       # (file no, what, reason)
    review: list = field(default_factory=list)         # (file no, what, note) billed, but worth a look
    stats: dict = field(default_factory=dict)


def file_key(file_no: str) -> str:
    """V15: the file number without its letter prefix (PL-, HL-, CC-, PB-PL-, CC--...) when it has the long date-time digits,
    so a file re-created under another prefix is known as the same file.  Short / odd numbers are kept as they are."""
    n = (file_no or "").strip().upper()
    m = re.match(r"^[A-Z]+(?:-+[A-Z]+)*-+(\d{14,})$", n)
    return m.group(1) if m else n


def _trip_ids(r: BillRow) -> str:
    return ", ".join(str(t["id"]) for _c, t in r.trips)


def _trip_status(r: BillRow) -> str:
    from .billing import FILE_STATUS_NAME  # noqa: F401  (kept for readers; trip statuses have their own names)
    names = {1: "Created", 2: "Allocated", 3: "Started", 4: "Hold", 5: "Finished", 6: "Canceled", 7: "Inactive", 8: "Withdrawn"}
    return ", ".join(dict.fromkeys(names.get(t.get("status_code"), "?") for _c, t in r.trips))


def build_month_bill(rows: list, year: int, month: int, bill_date: date | None = None, files: list | None = None) -> MonthBill:
    """rows = every BillRow of the run (PrimeData.all_rows, TAT already computed).  Nothing created in the month is dropped silently:
    a row is either on a bill or on the excluded list with its reason."""
    lo, hi = month_window(year, month)
    mb = MonthBill(year=year, month=month)
    for ft in ("Card", "Loan"):
        mb.bills[ft] = Bill(year=year, month=month, file_type=ft, bill_date=bill_date or date.today())
    in_month = [r for r in rows if r.receive_dt and lo <= r.receive_dt.date() <= hi]
    # A file that was created twice (the first copy Canceled, the same file number created again) is ONE package: the living copy
    # is billed, the Canceled copy is left out and listed - never two packages for one file number (live September 2026: 6 files).
    # V15: the number is compared without its letter prefix, so a copy re-created as PL- -> HL- (or PB-PL-, CC--) is found too.
    living_pkg = {file_key(r.file_no) for r in rows if r.kind == "Package" and not r.canceled}
    living_no = {file_key(r.file_no): r.file_no for r in rows if r.kind == "Package" and not r.canceled}
    for r in sorted(in_month, key=lambda r: (r.receive_dt, r.file_no, r.trips[0][1]["id"] or 0 if r.trips else 0)):
        what = f"{r.slab} / {r.category} (trip {_trip_ids(r)})"
        if is_test_file(r.file_no):
            mb.excluded.append((r.file_no, what, "test file"))
            continue
        if r.kind == "Package" and r.canceled and file_key(r.file_no) in living_pkg:
            again = living_no[file_key(r.file_no)]
            same = again.strip().upper() == r.file_no.strip().upper()
            mb.excluded.append((r.file_no, what, "Canceled copy of the file - the same file number was created again and that one is billed"
                                + ("" if same else f" ({again})")))
            continue
        if not getattr(r, "billable", True):
            mb.excluded.append((r.file_no, what, f"{_trip_status(r)} - never started (not billed)"))
            continue
        if r.file_type not in ("Card", "Loan"):
            mb.excluded.append((r.file_no, what, "file number is neither CC nor PL - please bill by hand"))
            continue
        cls = slab_class(r)
        area = r.area if r.area in ("In", "Out") else "Out"
        it = Item(file_type=r.file_type, section=section_key(cls, area), area=area, cls=cls, file_no=r.file_no,
                  applicant=getattr(r, "applicant", "") or "", rec=r.receive_dt.date(),
                  sub=(r.sub_day or r.submitted_at.date()) if r.submitted_at else None, tat=r.tat,
                  extra_tat=int(r.extra_tat or 0), amount=rate_for(r.file_type, cls, area), category=category_of(r, cls),
                  kind=r.kind, slab=r.slab, trip_ids=_trip_ids(r), trip_status=_trip_status(r))
        it.pct = penalty_pct(it.extra_tat)
        if it.pct:
            # The manual bill (September 2026: 15 penalties, every one a submitted package) charges a late PACKAGE or BANK STATEMENT
            # only.  Every other late row is still listed, with Apply = No, so nothing is hidden and the user decides.
            if not r.submitted_at:
                it.apply, it.pen_note = False, "not yet submitted - not charged until it is submitted"
            elif cls != "Package" and r.slab != "BS":
                it.apply, it.pen_note = False, "extra document / Re-CPV row - the manual bill charges packages and bank statements only"
            else:
                it.pen_note = "submitted after the SLA"
        notes = []
        if r.canceled:
            notes.append("Canceled, but it was started - billed")
            mb.review.append((r.file_no, what, "Canceled trip that had been started: billed (v6 rule) - please confirm"))
        if not r.area_sure:
            notes.append(f"area not sure: {r.area_why}")
            mb.review.append((r.file_no, what, f"In / Out is not certain ({r.area_why}) - billed as {area}"))
        if getattr(r, "split", False):
            notes.append("document created with the package - own row")
        if not r.submitted_at:
            notes.append("not yet submitted")
        it.note = "; ".join(notes)
        mb.bills[r.file_type].items.append(it)
    billed = sum(len(b.items) for b in mb.bills.values())
    mb.stats = {"rows_in_month": len(in_month), "billed": billed, "excluded": len(mb.excluded),
                "files_in_month": len({r.file_no for r in in_month}),
                "trips_in_month": sum(len(r.trips) for r in in_month),
                "trips_billed_rows": sum(len(r.trips) for r in in_month if getattr(r, "billable", True) and not is_test_file(r.file_no)),
                "dashboard_files_created": None}
    if files is not None:
        mb.stats["dashboard_files_created"] = sum(
            1 for f in files if (f.get("start_date") or f.get("created_at")) and lo <= (f.get("start_date") or f.get("created_at")).date() <= hi
            and not is_test_file(f["file_no"]))
        mb.stats["dashboard_trips_created"] = sum(
            1 for f in files if not is_test_file(f["file_no"]) for c in f["concerns"] for t in c["trips"]
            if t.get("created_at") and lo <= t["created_at"].date() <= hi)
    return mb


# ------------------------------------------------------------------------------------------- amount in words
_ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
         "nineteen").split()
_TENS = "x x twenty thirty forty fifty sixty seventy eighty ninety".split()


def _below_1000(n: int) -> str:
    out = []
    if n >= 100:
        out.append(_ONES[n // 100] + " hundred")
        n %= 100
    if n >= 20:
        out.append(_TENS[n // 10] + (f"-{_ONES[n % 10]}" if n % 10 else ""))
    elif n or not out:
        out.append(_ONES[n])
    return " ".join(out)


def in_words(amount: float) -> str:
    """Bangladeshi grouping (crore / lakh / thousand): 213664.5 -> 'Two lakh thirteen thousand six hundred sixty-four taka and fifty paisa only.'"""
    taka = int(amount)
    paisa = int(round((amount - taka) * 100))
    parts = []
    for size, name in ((10_000_000, "crore"), (100_000, "lakh"), (1000, "thousand")):
        if taka >= size:
            parts.append(f"{_below_1000(taka // size) if taka // size < 1000 else in_words(taka // size).split(' taka')[0].lower()} {name}")
            taka %= size
    if taka or not parts:
        parts.append(_below_1000(taka))
    text = " ".join(parts) + " taka"
    if paisa:
        text += f" and {_below_1000(paisa)} paisa"
    text += " only."
    return text[0].upper() + text[1:]


def file_stem(bill: Bill) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", f"Prime_Bank_PLC_{bill.file_type}_Invoice_{month_name(bill.month)}_{bill.year}")
