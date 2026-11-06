# Live check (runs inside Pyodide in the worker): the REAL report_builder code on the live dashboard (GET only).
# Runs the report twice from the same cached responses - without and with the combined Report Summary - and lists what changed.
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

ORIG = B.refresh_summary


def one(variant):
    B.refresh_summary = (lambda keep, others: None) if variant == "old" else ORIG
    t0 = time.time()
    d = CP.collect_prime(CP.PrimeConfig(**kw), lambda *a: None, threading.Event())
    return d, round(time.time() - t0)


def rec(r, sheet):
    return dict(k=(sheet, r.file_no, r.kind, r.trips[0][1].get("id")), no=r.file_no, kind=r.kind, sheet=sheet,
                folded=[k for k, _ in r.folded], text=r.summary.text().replace("\n", " / "), flag=bool(r.flags.get("summary")),
                reason=r.reason, sub=str(r.sub_day or ""), tat=r.tat, area=r.area)


OLD, t_old = one("old")
NEW, t_new = one("new")
B.refresh_summary = ORIG
old = {x["k"]: x for x in [rec(r, "C") for r in OLD.complete] + [rec(r, "I") for r in OLD.incomplete]}
new = {x["k"]: x for x in [rec(r, "C") for r in NEW.complete] + [rec(r, "I") for r in NEW.incomplete]}
L = []
ck = NEW.dash.get("check") or {}
L.append("TIMES old %ss new %ss | files %d rows %d failed %d log_failed %d" % (t_old, t_new, len(NEW.files), len(NEW.all_rows), len(NEW.failed), NEW.log_failed))
L.append("COMPLETE old %d new %d | INCOMPLETE old %d new %d | same row set: %s" % (len(OLD.complete), len(NEW.complete), len(OLD.incomplete),
         len(NEW.incomplete), set(old) == set(new)))
L.append("DASH " + json.dumps({k: v for k, v in ck.items() if not isinstance(v, (dict, list))}, default=str))
L.append("DASH_MISSING " + json.dumps(ck.get("missing", [])[:10], ensure_ascii=False))
changed = [k for k in new if k in old and (new[k]["text"] != old[k]["text"] or new[k]["reason"] != old[k]["reason"] or new[k]["flag"] != old[k]["flag"])]
other = [k for k in new if k in old and any(new[k][f] != old[k][f] for f in ("tat", "area", "sub", "kind", "folded"))]
L.append("CHANGED rows %d (Complete %d, Incomplete %d); other fields changed on %d rows" % (len(changed), sum(1 for k in changed if k[0] == "C"),
         sum(1 for k in changed if k[0] == "I"), len(other)))
for k in sorted(changed, key=lambda k: (k[0], new[k]["no"])):
    o, n = old[k], new[k]
    L.append("%s|%s|%s|fold %s" % (k[0], o["no"], o["kind"], ",".join(o["folded"])))
    L.append("   OLD %s%s" % (o["text"], " [blue]" if o["flag"] else ""))
    L.append("   NEW %s%s" % (n["text"], " [blue]" if n["flag"] else ""))
    if o["reason"] != n["reason"]:
        L.append("   REASON old=%s | new=%s" % (o["reason"], n["reason"]))
RES_TEXT = "\n".join(L)
json.dumps(RES_TEXT, ensure_ascii=False)
