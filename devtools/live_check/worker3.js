// Live-check worker: Pyodide + the real report_builder code, GET-only (sync XHR with a response cache).
// Messages: init {sources}, preload {entries:[[key,json]]}, run {code, params, token, api}
let py = null;
const CACHE = new Map();
function post(type, data){ self.postMessage({type, data}); }
onmessage = async (ev) => {
  const m = ev.data;
  try {
    if (m.cmd === "init") {
      importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");
      py = await loadPyodide();
      py.FS.mkdirTree("/app/report_builder");
      for (const f of Object.keys(m.sources)) py.FS.writeFile("/app/report_builder/" + f + ".py", m.sources[f]);
      py.runPython(`
import sys, types
sys.path.insert(0, "/app")
rq = types.ModuleType("requests")
class RequestException(Exception): pass
rq.RequestException = RequestException; rq.Session = object
sys.modules["requests"] = rq
`);
      post("ready", Object.keys(m.sources).length);
    } else if (m.cmd === "preload") {
      for (const [k, v] of m.entries) CACHE.set(k, v);
      post("preloaded", CACHE.size);
    } else if (m.cmd === "run") {
      self.__tok = m.token; self.__api = m.api; self.__n = 0;
      py.globals.set("PARAMS", py.toPy(m.params));
      const out = py.runPython(m.code);
      post("done", out === undefined ? null : out);
    }
  } catch (e) { post("error", String(e && e.stack || e).slice(0, 1500)); }
};
self.syncGet = (path, qs) => {
  const key = path + "?" + qs;
  if (CACHE.has(key)) return CACHE.get(key);
  const x = new XMLHttpRequest();
  x.open("GET", self.__api + path + (qs ? "?" + qs : ""), false);
  x.setRequestHeader("Authorization", "Bearer " + self.__tok);
  x.setRequestHeader("Accept", "application/json");
  x.send(null); self.__n++;
  if (self.__n % 25 === 0) post("progress", self.__n);
  const res = JSON.stringify({status: x.status, body: x.responseText});
  if (x.status === 200) CACHE.set(key, res);
  return res;
};
