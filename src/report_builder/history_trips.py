"""File History - trip-wise view (v16, Naim 23-11-2026: "Design A").

One block per file, one line per trip.  Nothing new is decided here - every value comes from the rules the software
already has:
  * Receive date, Package In / Out, SLA days, TAT, Extra TAT, SLA breach  -> billing.build_rows + compute_tat (the Package row)
  * Extra trips (how many, when they were added)                         -> the other bill rows of the file (Single / Re-CPV / Extra)
  * Done / Due per trip and the Report summary line                       -> summary.analyze over every trip of the file
    (the Daily Submission Tracker's Report Summary rules: notes in brackets, every problem of Done repeated in Due,
     'Due-0', 'Due-Report not yet submitted').
Per trip:  Due  -> the bracket note is the reason.
           Done -> 'Negative' (one word) when the same item also carries a problem note (it is repeated in Due).
           Canceled / Inactive / Withdrawn trips that the summary leaves out -> '–' with the dashboard status.
The result is plain data (JSON-safe) so the Excel sheet, the PDF and the live check all use the same rows.
"""
from __future__ import annotations

from datetime import date, datetime

from .billing import concern_info, file_type_of
from .file_history import FileData, HistoryData, _views_at, name_check, timeline, trip_label
from .summary import _doc_name, _sorted, analyze, info_notes

FILE_DONE = {"Submitted"}
FAR = datetime(9999, 12, 31)
DOC_WHO = ""


def _d(v) -> str:
    if isinstance(v, datetime):
        v = v.date()
    return f"{v:%d-%b-%Y}" if isinstance(v, date) else ""


def _short_day(v) -> str:
    if isinstance(v, datetime):
        v = v.date()
    return f"{v:%d-%b}" if isinstance(v, date) else ""


def file_status_word(status: str) -> str:
    """Dashboard file status in the words of the report (Canceled -> Cancelled, Partially Submitted -> Partially submitted)."""
    s = (status or "").strip()
    return {"Canceled": "Cancelled", "Partially Submitted": "Partially submitted", "On Going": "On going"}.get(s, s or "Unknown")


def _added_as(fd: FileData) -> dict:
    """trip id -> (label, bill row).  Package | Extra Trip n | Re-CPV | Extra Document ... (billing.build_rows categories)."""
    out = {}
    for r in sorted(fd.rows, key=lambda x: x.history_pos):
        if r.kind == "Package":
            label = "Package"
        elif r.kind == "ReCpv":
            label = "Re-CPV"
        else:
            label = r.category.replace("Created - ", "") or "Extra Trip"
        for _c, t in r.trips:
            out.setdefault(t["id"], (label, r))
    return out


def _trip_updates(fd: FileData) -> dict:
    """trip id -> (when, text) of the newest activity-log event of that trip."""
    out = {}
    for e in timeline(fd):                                 # newest first
        if e["trip_id"] is not None and e["trip_id"] not in out:
            out[e["trip_id"]] = (e["when"], e["text"])
    return out


def _results_by_trip(summary, info: set) -> dict:
    """trip id -> {"label", "result", "note", "extra"} from the Report summary items (Item.src = (created_at, trip id)).
    A Due item that only repeats a problem of a Done item (same person + label) is not a second result: that trip is
    'Done' + 'Negative'.  Items read out of another trip's remark (inferred LOI / Sign ...) do not name the trip; a Due one
    is added to the trip's note as 'LOI: reason'."""
    labels = {}
    for it, label in _sorted(summary.done_items + summary.due_items):
        labels[id(it)] = label if not it.who or label.startswith(it.who + " ") else f"{it.who} {label}"
    done_keys = {(d.who, d.label) for d in summary.done_items}
    out: dict = {}

    def slot(it):
        tid = it.src[1] if len(it.src) > 1 else None
        return None if tid is None else out.setdefault(tid, {"label": "", "result": "", "note": [], "extra": []})

    for it in summary.done_items:
        s = slot(it)
        if s is None:
            continue
        if not it.inferred:
            s["label"] = s["label"] or labels.get(id(it), it.label)
        s["result"] = s["result"] or "Done"
        if it.is_problem(info):
            s["neg"] = True                                   # the trip's own item or one read out of its remark (LOI ...)
    for it in summary.due_items:
        if (it.who, it.label) in done_keys:
            continue                                          # repeat of a Done problem (shown as 'Negative')
        s = slot(it)
        if s is None:
            continue
        if it.inferred:
            s["extra"].append(f"{it.label}: {it.note}" if it.note else it.label)
        else:
            s["label"] = labels.get(id(it), it.label)
            s["result"] = "Due"
            if it.note:
                s["note"].append(it.note)
    for s in out.values():
        if s["extra"] and s["result"] != "Due":
            s["result"] = "Due"
        if s["result"] == "Done" and s.get("neg"):
            s["note"] = ["Negative"]
        s["note"] = "; ".join(dict.fromkeys(s["note"] + s["extra"]))
    return out


def file_block(fd: FileData, given_name: str = "", match_note: str = "") -> dict:
    f = fd.file
    info_c = concern_info(f)
    status = file_status_word(f.get("status", ""))
    submitted = status in FILE_DONE
    views = _views_at(f, fd.logs, FAR)
    summary = analyze(views, submitted, "BS")
    by_trip = _results_by_trip(summary, info_notes())
    added = _added_as(fd)
    updates = _trip_updates(fd)

    rows = sorted(fd.rows, key=lambda r: r.history_pos)
    pkg = next((r for r in rows if r.kind == "Package"), rows[0] if rows else None)
    extras = [r for r in rows if r is not pkg and not r.split]

    trips = []
    who_of = {c["id"]: info_c[c["id"]]["who"] for c in f["concerns"]}
    for c in f["concerns"]:
        for t in c["trips"]:
            res = by_trip.get(t["id"])
            label_kind, _row = added.get(t["id"], ("Package", None))
            upd = updates.get(t["id"])
            st = t.get("status", "")
            base = trip_label(t)
            if base in ("House", "Office"):
                plain = f"{who_of.get(c['id'], '')} {base}".strip()
            elif t.get("type_code") == "BANK":
                plain = "BS"
            else:
                plain = _doc_name(t) or base                  # the Report Summary's own name: LOI, Chamber, Rental ...
                if plain == "Sign":
                    plain = f"{who_of.get(c['id'], '')} Sign".strip()
            if res and res["result"]:
                result, note, name = res["result"], res["note"], res["label"] or plain
                if result == "Due" and not note:
                    note = st
            else:
                code = t.get("status_code")
                result = "–" if code in (6, 7, 8) else ("Done" if code == 5 else "Due")
                note, name = ("" if code == 5 else st), plain
            when = upd[0] if upd else (t.get("end_time") or t.get("start_time") or t.get("created_at"))
            text = upd[1] if upd else st
            trips.append({
                "trip_id": t["id"], "type": name, "added": _d(t.get("created_at")), "added_as": label_kind,
                "status": st, "update": f"{text} · {_short_day(when)}" if when else text, "result": result, "note": note,
                "_sort": (t.get("created_at") or datetime.min, t["id"] or 0),
            })
    trips.sort(key=lambda x: x.pop("_sort"))

    res, app = name_check(given_name, f)
    applicant = app or next((c["name"] for c in f["concerns"] if info_c[c["id"]]["role"] == "APPLICANT"), "")
    if not applicant and f["concerns"]:
        applicant = f["concerns"][0]["name"]
    no = f["file_no"] or ""
    digits = "".join(ch for ch in no if ch.isdigit())
    return {
        "file_no": no, "short_no": digits[-6:] if digits else no, "type": file_type_of(no, f.get("type", "")),
        "applicant": applicant, "given_name": given_name, "name_check": res, "match_note": match_note,
        "receive": _d(f.get("start_date") or f.get("created_at") or (pkg.receive_dt if pkg else None)),
        "status": status,
        "area": pkg.area if pkg else "", "sla_days": pkg.sla_days if pkg else None,
        "tat": pkg.tat if pkg else None, "extra_tat": pkg.extra_tat if pkg else None,
        "sla_breach": bool(pkg.sla_breach) if pkg and pkg.tat is not None else None,
        "extra_trips": [{"kind": (r.category.replace("Created - ", "") if r.kind != "ReCpv" else "Re-CPV"), "date": _d(r.receive_dt),
                         "short": _short_day(r.receive_dt), "area": r.area} for r in extras],
        "summary_done": summary.done, "summary_due": summary.due,
        "trips": trips,
    }


def blocks(h: HistoryData, short_from_input: bool = True) -> list[dict]:
    """Every searched number in the input order: found files (one block each) and 'File not found' blocks."""
    out, seen = [], set()
    for m in h.matches:
        given = getattr(m.entry, "name", "")
        if not m.found or m.file_id not in h.files:
            out.append({"file_no": "", "short_no": m.entry.raw, "searched": m.entry.raw, "given_name": given,
                        "status": "File not found", "match_note": m.note, "trips": [], "missing": True})
            continue
        if m.file_id in seen:
            continue
        seen.add(m.file_id)
        fd = h.files[m.file_id]
        if fd.error:
            out.append({"file_no": fd.file_no, "short_no": m.entry.raw, "searched": m.entry.raw, "given_name": given,
                        "status": "Could not read", "match_note": fd.error, "trips": [], "missing": True})
            continue
        b = file_block(fd, given, m.note)
        b["searched"] = m.entry.raw
        if short_from_input and m.entry.kind == "suffix":
            b["short_no"] = m.entry.raw
        out.append(b)
    return out


def totals(bl: list[dict]) -> dict:
    found = [b for b in bl if not b.get("missing")]
    st = [b["status"] for b in found]
    trips = [t for b in found for t in b["trips"]]
    return {"files": len(found), "not_found": sum(1 for b in bl if b.get("missing")),
            "submitted": st.count("Submitted"), "partial": st.count("Partially submitted"), "hold": st.count("Hold"),
            "cancelled": st.count("Cancelled") + st.count("Withdrawn"),
            "ongoing": sum(1 for s in st if s not in ("Submitted", "Partially submitted", "Hold", "Cancelled", "Withdrawn")),
            "breach": sum(1 for b in found if b.get("sla_breach")),
            "done": sum(1 for t in trips if t["result"] == "Done"), "due": sum(1 for t in trips if t["result"] == "Due")}


def sla_text(b: dict) -> tuple[str, str]:
    """-> (TAT line, colour key: breach | ok | none)."""
    if b.get("tat") is None:
        return "TAT –", "none"
    if b.get("sla_breach"):
        return f"TAT {b['tat']} days · SLA breach +{b.get('extra_tat') or 0}", "breach"
    return f"TAT {b['tat']} days · Within SLA", "ok"


def extra_text(b: dict) -> str:
    ex = b.get("extra_trips") or []
    if not ex:
        return "Extra trip: 0"
    return f"Extra trip: {len(ex)} (" + ", ".join(e["short"] for e in ex) + ")"
