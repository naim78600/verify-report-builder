"""V15: the Mushak-6.3 (tax invoice) is made with every monthly bill; certificates come from the Bill Attachments folder."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pypdf import PdfReader  # noqa: E402

from report_builder.assets_path import asset  # noqa: E402
from report_builder.bill_out import bill_attachments, pdf_from_excel, write_month_bill  # noqa: E402
from report_builder.monthly_bill import Bill, Item, MonthBill  # noqa: E402
from report_builder.mushak import (BUYER_BIN, issue_date_text, money, mushak_stem, mushak_values, service_line,  # noqa: E402
                                   write_mushak_pdf)


def _bill(ft="Card"):
    items = [Item(file_type=ft, section="in_pkg", area="In", cls="Package", file_no="CC-1", amount=450, kind="Package"),
             Item(file_type=ft, section="out_pkg", area="Out", cls="Package", file_no="CC-2", amount=600, kind="Package", extra_tat=1, pct=20, apply=True),
             Item(file_type=ft, section="in_single", area="In", cls="doc", file_no="CC-3", amount=140, kind="Extra")]
    return Bill(year=2026, month=11, file_type=ft, bill_date=date(2026, 11, 20), items=items)


def test_values_follow_the_bill():
    b = _bill()
    v = mushak_values(b)
    assert v == {"value": 1190 - 120, "vat_pct": 5, "vat": 53.5, "total": 1123.5}
    assert v["value"] == b.after_penalty and v["vat"] == b.vat and v["total"] == b.grand_total
    assert money(73320) == "73320" and money(3128.6) == "3128.60" and money(65700.6) == "65700.60"
    assert service_line(b) == "CPV service Card (for the month of November 2026)"
    assert issue_date_text(date(2026, 11, 8)) == "Nov 8, 2026"
    assert mushak_stem(b) == "Prime_Bank_PLC_Card_Mushak6.3_November_2026"


def test_pdf_has_the_values_and_leaves_challan_sign_seal_blank(tmp_path):
    assert asset("mushak63_template.pdf").exists()
    out = write_mushak_pdf(_bill("Loan"), tmp_path / "m.pdf")
    r = PdfReader(str(out))
    assert len(r.pages) == 1
    t = r.pages[0].extract_text()
    for s in ("Prime Bank PLC", BUYER_BIN, "Nov 20, 2026", "CPV service Loan", "1070", "53.50", "1123.50", "1070/-", "1123.50/-", "5%",
              "Barikoi Technologies Limited", "003495542-0408"):
        assert s in t, s
    # nothing is written for the challan number, the issue time, the name / designation, signature or seal
    assert "Saifur" not in t and "PM" not in t


def test_month_bill_writes_mushak_and_edited_excel_remakes_it(tmp_path):
    mb = MonthBill(year=2026, month=11, bills={"Card": _bill("Card"), "Loan": _bill("Loan")})
    paths = write_month_bill(mb, tmp_path)
    names = sorted(p.name for p in paths)
    assert "Prime_Bank_PLC_Card_Mushak6.3_November_2026.pdf" in names and "Prime_Bank_PLC_Loan_Mushak6.3_November_2026.pdf" in names
    assert len(names) == 6
    m = tmp_path / "Prime_Bank_PLC_Card_Mushak6.3_November_2026.pdf"
    m.unlink()
    pdf_from_excel(tmp_path / "Prime_Bank_PLC_Card_Invoice_November_2026.xlsx")
    assert m.exists() and "1123.50" in PdfReader(str(m)).pages[0].extract_text()


def test_bill_attachments_folder(tmp_path):
    assert bill_attachments(tmp_path) == []
    d = tmp_path / "Bill Attachments"
    d.mkdir()
    (d / "Certificate of Return of Income 2025.pdf").write_bytes(b"%PDF-1.4")
    (d / ".DS_Store").write_bytes(b"x")
    assert [p.name for p in bill_attachments(tmp_path)] == ["Certificate of Return of Income 2025.pdf"]


def test_a_copy_re_created_under_another_prefix_is_one_package():
    """Live November 2026: PL-20261115112802097 (all trips Canceled) was created again next day as HL-20261115112802097."""
    from datetime import datetime as D
    from test_v6 import _file, _rows, _t
    from report_builder.monthly_bill import build_month_bill, file_key
    assert file_key("PL-20261115112802097") == file_key("HL-20261115112802097") == "20261115112802097"
    assert file_key("PB-PL-20261108060811878") == file_key("PL-20261108060811878")
    assert file_key("CC--20261027071214529") == file_key("CC-20261027071214529")
    assert file_key("PL-0274") == "PL-0274"                                   # short numbers are not folded
    c = D(2026, 11, 15, 10, 0)
    dead = _file([("APPLICANT", [_t(1, "HOUSE", c, status=6), _t(2, "OFFICE", c, status=6)])], no="PL-20261115112802097", start=c)
    dead["id"] = 8
    live = _file([("APPLICANT", [_t(3, "HOUSE", c), _t(4, "OFFICE", c)])], no="HL-20261115112802097", start=c)
    live["type"] = "Loan"                                                    # HL- numbers are Loan files on the dashboard (application type)
    mb = build_month_bill(_rows(dead) + _rows(live), 2026, 11, date(2026, 11, 20))
    billed = [i for b in mb.bills.values() for i in b.items]
    assert [i.trip_ids for i in billed] == ["3, 4"]
    assert len(mb.excluded) == 1 and "created again" in mb.excluded[0][2] and "HL-20261115112802097" in mb.excluded[0][2]
