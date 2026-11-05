"""'Excel Report with Re-CPV': the v1 detailed workbook + Re-CPV / Extra under every file
+ a 'Billing Rows' sheet and a 'Calculation' sheet that explains every number."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .billing import BASE_TYPE
from .collect import CollectResult
from .collect_prime import PrimeData
from .excel import HEADER_FILL, build_workbook, put

HDR_FONT = Font(bold=True, color="FFFFFF")


def to_collect_result(d: PrimeData) -> CollectResult:
    res = CollectResult(files=d.files, failed=d.failed, site_total=d.site_total, listed=len(d.files),
                        date_from=d.w_from, date_till=d.w_till, org_name=d.org_name, server_label=d.server_label,
                        generated_at=d.generated_at, notes=list(d.notes))
    for r in d.all_rows:
        for _c, t in r.trips:
            if r.kind == "ReCpv":
                res.trip_tags[t["id"]] = "Re-CPV"
            elif r.kind == "Extra":
                res.trip_tags[t["id"]] = "Extra"
    for r in d.all_rows:
        if r.kind in ("ReCpv", "Extra"):
            t = r.trips[0][1]
            reason = ""
            for ln in r.history_lines:
                if f"Trip ID {t['id']}" in ln and "\nReason: " in ln:
                    reason = ln.split("\nReason: ", 1)[1]
                    break
            res.recpv_events.setdefault(r.file_id, []).append({
                "kind": "Re-CPV" if r.kind == "ReCpv" else "Extra", "trip_id": t["id"], "at": t.get("created_at"),
                "reason": reason or (t.get("comment") or ""), "trip_type": BASE_TYPE.get(t.get("type_code", ""), "")})
    return res


def _billing_rows_sheet(wb, d: PrimeData):
    ws = wb.create_sheet("Billing Rows")
    cols = [("File No", 24), ("Bill Kind", 10), ("Bill Slab", 34), ("Category", 22), ("Trip IDs", 22), ("Trips", 7),
            ("Concerns", 48), ("Receive Date", 12), ("Area", 7), ("Area basis", 26), ("Submission", 17), ("TAT", 6),
            ("Extra TAT", 9), ("Status", 12), ("Canceled trip", 12)]
    for i, (t, w) in enumerate(cols, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
        put(ws, 1, i, t, fill=HEADER_FILL, font=HDR_FONT, align=Alignment(horizontal="center", wrap_text=True))
    for n, r in enumerate(sorted(d.all_rows, key=lambda x: (x.file_no, x.receive_dt or datetime.max)), 2):
        vals = [r.file_no, r.kind, r.slab, r.category, ", ".join(str(t["id"]) for _c, t in r.trips), len(r.trips),
                "; ".join(r.concern_lines), r.receive_dt.date() if r.receive_dt else None, r.area, r.area_why,
                r.reported_at, r.tat, r.extra_tat, r.status, "Yes" if r.canceled else ""]
        for j, v in enumerate(vals, 1):
            c = put(ws, n, j, v)
            if j == 8:
                c.number_format = "dd/mm/yyyy"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{max(2, len(d.all_rows) + 1)}"
    return len(d.all_rows)


def _calculation_sheet(wb, d: PrimeData, n_rows: int):
    ws = wb.create_sheet("Calculation")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 46
    for c in "BCD":
        ws.column_dimensions[c].width = 14
    put(ws, 1, 1, "Billing calculation (every number is a formula over the 'Billing Rows' sheet)",
        font=Font(bold=True, size=13, color="1F3864"))
    last = max(n_rows + 1, 2)
    rng = lambda col: f"'Billing Rows'!${col}$2:${col}${last}"        # noqa: E731
    r = 3
    for j, h in enumerate(("Bill type", "In", "Out", "Total"), 1):
        put(ws, r, j, h, fill=HEADER_FILL, font=HDR_FONT, align=Alignment(horizontal="center"))
    for label, kind in (("Package", "Package"), ("Single (same-day 6th+ trip)", "Single"), ("Re-CPV", "ReCpv"), ("Extra", "Extra")):
        r += 1
        put(ws, r, 1, label)
        put(ws, r, 2, f'=COUNTIFS({rng("B")},"{kind}",{rng("I")},"In")', align=Alignment(horizontal="center"), formula=True)
        put(ws, r, 3, f'=COUNTIFS({rng("B")},"{kind}",{rng("I")},"Out")', align=Alignment(horizontal="center"), formula=True)
        put(ws, r, 4, f"=B{r}+C{r}", align=Alignment(horizontal="center"), formula=True)
    r += 1
    put(ws, r, 1, "Total billable events", font=Font(bold=True))
    for j, col in enumerate("BCD", 2):
        put(ws, r, j, f"=SUM({col}4:{col}{r - 1})", font=Font(bold=True), align=Alignment(horizontal="center"), formula=True)
    tot_row = r
    r += 2
    put(ws, r, 1, "Trip count check", font=Font(bold=True, color="1F3864"))
    r += 1
    put(ws, r, 1, "Trips counted in the billing rows")
    put(ws, r, 2, f"=SUM({rng('F')})", align=Alignment(horizontal="center"), formula=True)
    r += 1
    put(ws, r, 1, "Trips in the files (Reports page count)")
    put(ws, r, 2, sum(len(c["trips"]) for f in d.files for c in f["concerns"]), align=Alignment(horizontal="center"))
    r += 1
    put(ws, r, 1, "Difference (must be 0 - Re-CPV never changes the trip count)", font=Font(bold=True))
    put(ws, r, 2, f"=B{r - 2}-B{r - 1}", font=Font(bold=True), align=Alignment(horizontal="center"), formula=True)
    r += 2
    put(ws, r, 1, "Package trips (max 5 each)")
    put(ws, r, 2, f'=SUMIFS({rng("F")},{rng("B")},"Package")', align=Alignment(horizontal="center"), formula=True)
    r += 1
    put(ws, r, 1, "Rows with a Canceled trip (billing undecided)")
    put(ws, r, 2, f'=COUNTIF({rng("O")},"Yes")', align=Alignment(horizontal="center"), formula=True)
    r += 1
    put(ws, r, 1, "Submitted rows")
    put(ws, r, 2, f'=COUNTIF({rng("N")},"Submitted")', align=Alignment(horizontal="center"), formula=True)
    r += 1
    put(ws, r, 1, "Incomplete rows")
    put(ws, r, 2, f'=COUNTIF({rng("N")},"Incomplete")', align=Alignment(horizontal="center"), formula=True)
    r += 2
    for note in ("Package = trips created on the file-creation date, first 5 in creation order (any type).",
                 "Extra Trip 1, 2, 3 = 6th, 7th, 8th trip created with the file (billed alone). Re-CPV / Extra Document / Extra Trip = trip created after the creation date.",
                 "In = inside Dhaka City Corporation (DNCC / DSCC) or Chattogram City Corporation (from latitude/longitude); everything else (Gazipur, Narayanganj, Savar, Tongi ...) is Out. A Package is Out if any trip is Out; a single row is judged on its own trip.",
                 "SLA: In = 2 working days, Out = 4 working days. Extra TAT = TAT - SLA.",
                 "TAT counts working days (Friday and Saturday off, plus the Holidays list)."):
        put(ws, r, 1, note, font=Font(color="555555", italic=True))
        r += 1


def build_recpv_workbook(d: PrimeData, path: Path) -> Path:
    res = to_collect_result(d)

    def extra(wb):
        n = _billing_rows_sheet(wb, d)
        _calculation_sheet(wb, d, n)

    return build_workbook(res, path, extra_sheets=extra)
