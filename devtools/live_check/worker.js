// Web Worker: runs the REAL report_builder python (Pyodide) against the live dashboard API (GET only).
// Developer check tool: runs the real python code against the live API from the browser tab (GET only).
let py = null;
function post(type, data){ self.postMessage({type, data}); }
onmessage = async (ev) => {
  const m = ev.data;
  try {
    if (m.cmd === "init") {
      importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");
      py = await loadPyodide();
      py.FS.mkdirTree("/app/report_builder");
      for (const f of Object.keys(m.sources)) {
        py.FS.writeFile("/app/report_builder/" + f + ".py", m.sources[f]);
      }
      py.runPython(`
import sys, types
sys.path.insert(0, "/app")
rq = types.ModuleType("requests"); 
class RequestException(Exception): pass
rq.RequestException = RequestException; rq.Session = object
sys.modules["requests"] = rq
`);
      post("ready", Object.keys(m.sources).length);
    } else if (m.cmd === "run") {
      self.__tok = m.token; self.__api = m.api; self.__n = 0; self.__bad = [];
      py.globals.set("PARAMS", py.toPy(m.params));
      const out = py.runPython(m.code);
      post("done", out === undefined ? null : (out && out.toJs ? out.toJs({dict_converter: Object.fromEntries}) : out));
    }
  } catch (e) { post("error", String(e && e.stack || e).slice(0, 1500)); }
};
// sync GET used by the python shim
self.syncGet = (path, qs) => {
  const x = new XMLHttpRequest();
  x.open("GET", self.__api + path + (qs ? "?" + qs : ""), false);
  x.setRequestHeader("Authorization", "Bearer " + self.__tok);
  x.setRequestHeader("Accept", "application/json");
  x.send(null); self.__n++;
  if (self.__n % 50 === 0) post("progress", self.__n);
  return JSON.stringify({status: x.status, body: x.responseText});
};
