import json, js, time, threading
from datetime import date, datetime, time as dtime
from urllib.parse import urlencode
import report_builder.client as C
import report_builder.collect_prime as CP
import report_builder.billing as B

class Shim:
    def __init__(self, web, api, cancel=None, **kw):
        self.token = "x"
    def login(self, email, pw):
        pass
    def get(self, path, params=None):
        from urllib.parse import urlparse
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
    for i, k in enumerate(keys, 1):
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
kw = dict(web="", api="", server_label="live", email="x", password="x", days=int(P["days"]), mode=P["mode"],
          report_date=date.fromisoformat(P["date"]))
for k in ("incomplete_scope", "slot"):
    if P.get(k):
        kw[k] = P[k]
t0 = time.time()
cfg = CP.PrimeConfig(**kw)
d = CP.collect_prime(cfg, lambda *a: None, threading.Event())
STAT = {1: "Created", 2: "OnGoing", 3: "Hold", 4: "Finished", 5: "Canceled", 6: "Submitted", 7: "Partial", 8: "Withdrawn"}
TST = {1: "Cr", 2: "Al", 3: "St", 4: "HOLD", 5: "Fin", 6: "Can", 7: "Inact", 8: "Wd"}
def tr(r):
    return ",".join(TST.get(t.get("status_code"), "?") for _c, t in r.trips)
def sub(r):
    sd = r.reported_at
    return sd.strftime("%d/%m %H:%M") if sd else "-"
lines = []
lines.append("SECS %s files %s rows %s failed %s log_failed %s" % (round(time.time() - t0), len(d.files), len(d.all_rows), len(d.failed), d.log_failed))
ck = d.dash.get("check") or {}
lines.append("DASH " + json.dumps({k: v for k, v in ck.items() if not isinstance(v, (dict, list))}))
lines.append("DASH_MISSING " + json.dumps(ck.get("missing", [])[:10], ensure_ascii=False))
lines.append("COMPLETE %d rows / %d files" % (len(d.complete), len({r.file_id for r in d.complete})))
for r in d.complete:
    lines.append("C|%s|%s|%s|rcv %s|sub %s|tat %s/%s|fs %s|trips %s|folded %s" % (r.file_no, r.kind, r.area + ("?" if not r.area_sure else ""),
        r.receive_dt.strftime("%d/%m") if r.receive_dt else "-", sub(r), r.tat, r.extra_tat, STAT.get(r.file_status), tr(r), [k for k, _ in r.folded]))
lines.append("INCOMPLETE %d rows / %d files" % (len(d.incomplete), len({r.file_id for r in d.incomplete})))
for r in d.incomplete:
    lines.append("I|%s|%s|%s|rcv %s|tat %s/%s|fs %s|trips %s|folded %s|%s|%s%s" % (r.file_no, r.kind, r.area + ("?" if not r.area_sure else ""),
        r.receive_dt.strftime("%d/%m") if r.receive_dt else "-", r.tat, r.extra_tat, STAT.get(r.file_status), tr(r), [k for k, _ in r.folded],
        r.reason_kind or "-", r.reason or "(none)", " [BLUE]" if "reason" in r.flags else ""))
# pending but NOT listed (what the status rule leaves out)
asof = datetime.combine(d.report_date, dtime(23, 59, 59)) if d.slot != "3pm" else datetime.combine(d.report_date, dtime(15, 0))
listed = {r.file_id for r in d.incomplete}
seen = {}
for r in d.all_rows:
    if r.submitted or B.is_dead_row(r) or r.file_id in listed:
        continue
    if r.receive_dt and r.receive_dt.date() > d.report_date:
        continue
    st = B.file_state(r, asof)
    if st in ("closed", "submitted"):
        continue
    seen.setdefault(r.file_no, []).append(r)
lines.append("PENDING_NOT_LISTED %d files" % len(seen))
for no, rs in sorted(seen.items()):
    r = rs[0]
    lines.append("N|%s|%s|fs %s|rcv %s|tat %s|trips %s" % (no, "+".join(x.kind for x in rs), STAT.get(r.file_status), ",".join(x.receive_dt.strftime("%d/%m") for x in rs if x.receive_dt),
        ",".join(str(x.extra_tat) for x in rs), " ; ".join(tr(x) for x in rs)))
for n in d.notes[:14]:
    lines.append("NOTE " + n[:300])
json.dumps(lines, ensure_ascii=False)
