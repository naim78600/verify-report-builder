# Live check (runs inside Pyodide in the worker): the REAL report_builder code on the live dashboard (GET only).
# v3.2.1b: runs the report twice from the same cached responses - with the OLD Incomplete rule (running On Going files listed) and the NEW one.
import json, js, time, threading
from datetime import date
from urllib.parse import urlencode, urlparse
import report_builder.client as C
import report_builder.collect_prime as CP
import report_builder.billing as B


class Shim:
    def __init__(self, web, api, cancel=None, **kw):
        self.token = "x"

    def login(self, email, pw):
        pass

    def get(self, path, params=None):
        if not any(p.match(urlparse(path).path) for p in C._ALLOWED_GET):
            raise PermissionError(path)
        qs = urlencode(params or [])
        for attempt in range(4):
            r = json.loads(js.syncGet(path, qs))
            st = r["status"]
            if st == 200:
                return json.loads(r["body"])
            if st in (401, 403):
                raise C.AuthError("HTTP %d" % st)
            if st == 404:
                raise C.ApiError("HTTP 404")
            if st < 500 and st != 429:
                raise C.ApiError("HTTP %d" % st)
        raise C.ApiError("failed")


def seq_pool(workers, cancel, fn, keys, progress=None, label=""):
    results, errors = {}, {}
    for k in keys:
        try:
            results[k] = fn(k)
        except (C.AuthError, C.Cancelled):
            raise
        except Exception as exc:
            errors[k] = str(exc)
    return results, errors


CP._pool_map = seq_pool
CP.ReadOnlyClient = Shim
P = PARAMS.to_py() if hasattr(PARAMS, "to_py") else PARAMS
kw = dict(web="", api="", server_label="live", email="x", password="x", days=int(P.get("days", 90)), mode=P["mode"])
if P.get("date"):
    kw["report_date"] = date.fromisoformat(P["date"])
for k in ("date_from", "date_till"):
    if P.get(k):
        kw[k] = date.fromisoformat(P[k])
for k in ("incomplete_scope", "slot"):
    if P.get(k):
        kw[k] = P[k]

from collections import Counter

ORIG_LISTED = B.listed_by_status
NAME = B.FILE_STATUS_NAME


def old_listed(rs, state):
    kind = B.pending_kind(rs, state)
    if kind in ("partial", "hold", "finished"):
        return True
    return kind == "ongoing" and any((x.extra_tat or 0) > 0 for x in rs)


def one(variant):
    k2 = dict(kw)
    B.listed_by_status = old_listed if variant == "old" else ORIG_LISTED
    if variant == "old" and kw["mode"] == "range":
        k2["incomplete_scope"] = "all_pending"                    # the old range report listed every pending file
    t0 = time.time()
    d = CP.collect_prime(CP.PrimeConfig(**k2), lambda *a: None, threading.Event())
    B.listed_by_status = ORIG_LISTED
    return d, round(time.time() - t0)


def rec(r, sheet):
    return dict(k=(sheet, r.file_no, r.kind, r.trips[0][1].get("id")), no=r.file_no, kind=r.kind, sheet=sheet, fs=NAME.get(r.file_status, str(r.file_status)),
                folded=[k for k, _ in r.folded], text=r.summary.text().replace("\n", " / "), reason=r.reason, sub=str(r.sub_day or ""),
                tat=r.tat, area=r.area, etat=r.extra_tat or 0)


OLD, t_old = one("old")
NEW, t_new = one("new")
old = {x["k"]: x for x in [rec(r, "C") for r in OLD.complete] + [rec(r, "I") for r in OLD.incomplete]}
new = {x["k"]: x for x in [rec(r, "C") for r in NEW.complete] + [rec(r, "I") for r in NEW.incomplete]}
oc = {k for k in old if k[0] == "C"}
nc = {k for k in new if k[0] == "C"}
oi = {k for k in old if k[0] == "I"}
ni = {k for k in new if k[0] == "I"}
L = []
ck = NEW.dash.get("check") or {}
L.append("TIMES old %ss new %ss | files %d rows %d failed %d log_failed %d" % (t_old, t_new, len(NEW.files), len(NEW.all_rows), len(NEW.failed), NEW.log_failed))
L.append("COMPLETE old %d new %d same %s same-fields %s" % (len(oc), len(nc), oc == nc, all(all(new[k][f] == old[k][f] for f in ("text", "tat", "area", "sub", "folded", "etat")) for k in nc & oc)))
L.append("INCOMPLETE old %d new %d | added %d removed %d" % (len(oi), len(ni), len(ni - oi), len(oi - ni)))
L.append("NEW_INCOMPLETE_BY_STATUS " + json.dumps(dict(Counter(new[k]["fs"] for k in ni)), ensure_ascii=False))
L.append("OLD_INCOMPLETE_BY_STATUS " + json.dumps(dict(Counter(old[k]["fs"] for k in oi)), ensure_ascii=False))
L.append("REMOVED_BY_STATUS " + json.dumps(dict(Counter(old[k]["fs"] for k in oi - ni)), ensure_ascii=False))
L.append("NEW_INCOMPLETE_REASON_KINDS " + json.dumps(dict(Counter((new[k]["reason"].split(":")[0].split(" - ")[0] or "-")[:22] for k in ni)), ensure_ascii=False))
L.append("DASH " + json.dumps({k: v for k, v in ck.items() if not isinstance(v, (dict, list))}, default=str))
want = {f["file_no"] for f in NEW.files if f.get("status_code") in (3, 4, 7) and not B.is_test_file(f["file_no"])}
got = {new[k]["no"] for k in ni}
L.append("DASH_HOLD_FIN_PARTIAL_FILES %d | in report %d | missing %s | extra %s" % (len(want), len(got), sorted(want - got)[:8], sorted(got - want)[:8]))
RES_TEXT = "\n".join(L)
json.dumps(RES_TEXT, ensure_ascii=False)
