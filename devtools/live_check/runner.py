import json, js, time, threading
from datetime import date
from urllib.parse import urlencode
import report_builder.client as C
import report_builder.collect_prime as CP

class Shim:
    def __init__(self, web, api, cancel=None, **kw):
        self.token = "x"
    def login(self, email, pw):
        pass
    def get(self, path, params=None):
        import re
        from urllib.parse import urlparse
        if not any(p.match(urlparse(path).path) for p in C._ALLOWED_GET):
            raise PermissionError(path)
        qs = urlencode(params or [])
        last = ""
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
            last = "HTTP %d" % st
        raise C.ApiError("failed " + last)

def seq_pool(workers, cancel, fn, keys, progress=None, label=""):
    results, errors = {}, {}
    total = len(keys)
    for i, k in enumerate(keys, 1):
        try:
            results[k] = fn(k)
        except (C.AuthError, C.Cancelled):
            raise
        except Exception as exc:
            errors[k] = str(exc)
        if progress and (i % 5 == 0 or i == total):
            progress(i, total)
    return results, errors

CP._pool_map = seq_pool
CP.ReadOnlyClient = Shim

P = PARAMS.to_py() if hasattr(PARAMS, "to_py") else PARAMS
kw = dict(web="", api="", server_label="live", email="x", password="x", days=int(P["days"]), mode=P["mode"],
          report_date=date.fromisoformat(P["date"]) if P.get("date") else None)
for k in ("incomplete_scope", "slot"):
    if P.get(k):
        kw[k] = P[k]
t0 = time.time()
cfg = CP.PrimeConfig(**kw)
d = CP.collect_prime(cfg, lambda *a: None, threading.Event())
def row(r):
    sd = r.reported_at if hasattr(r, "reported_at") else r.submitted_at
    return "%s|%s|%s|%s|%s|%s|%s|%s" % (r.file_no, r.kind, r.area, r.receive_dt.strftime("%d/%m") if r.receive_dt else "-",
                                        sd.strftime("%d/%m %H:%M") if sd else "-", r.tat, r.extra_tat, (r.status_note or ""))
res = {
  "secs": round(time.time() - t0), "files": len(d.files), "rows": len(d.all_rows), "failed": len(d.failed), "log_failed": d.log_failed,
  "complete": [row(r) for r in d.complete], "incomplete": [row(r) for r in d.incomplete], "notes": d.notes[:12],
  "dash": {k: (v if not isinstance(v, (dict, list)) else None) for k, v in (d.dash.get("check") or {}).items()},
  "dash_missing": (d.dash.get("check") or {}).get("missing", [])[:10], "recon": {k: v for k, v in d.recon.items() if not isinstance(v, dict)},
}
json.dumps(res)
