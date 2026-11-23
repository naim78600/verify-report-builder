# Live check v16 (runs inside Pyodide in the worker): File History for a list of numbers + names, GET only.
# Output: JSON {blocks, notes, org} built by history_trips.blocks (the same rows the Excel / PDF use).
import json, js, threading
from datetime import date
from urllib.parse import urlencode, urlparse
import report_builder.client as C
import report_builder.collect_prime as CP
import report_builder.file_history as FH
from report_builder.history_trips import blocks


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


CP._pool_map = FH._pool_map = seq_pool
FH.ReadOnlyClient = Shim
P = PARAMS.to_py() if hasattr(PARAMS, "to_py") else PARAMS
ents = []
for no, name in P["ids"]:
    e = FH.make_entry(no)
    if e:
        e.name = name
        ents.append(e)
cfg = FH.HistoryConfig(web="", api="", server_label="live", email="x", password="x", org_name=P["org"], ids=ents,
                       index_path=__import__("pathlib").Path("/tmp/file_index.json"), today=date.fromisoformat(P["today"]))
h = FH.collect_history(cfg, lambda *a: None, threading.Event())
json.dumps({"blocks": blocks(h), "notes": h.notes, "org": h.org_name, "at": str(h.generated_at)}, ensure_ascii=False, default=str)
