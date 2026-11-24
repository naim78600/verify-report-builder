// Verify New Dashboard - talks to Verify Report Builder (VRB) on THIS computer only (127.0.0.1), for the verifier directory.
const BASE = "http://127.0.0.1:47321";
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    try {
      if (msg.type !== "vrb") return reply({ ok: false });
      const opt = { cache: "no-store", headers: { "X-VRB-Dashboard": "1" } };
      if (msg.body !== undefined) { opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(msg.body); }
      const r = await fetch(BASE + msg.path, opt);
      if (!r.ok) return reply({ ok: false, status: r.status });
      if ((r.headers.get("Content-Type") || "").startsWith("image/")) {
        const buf = new Uint8Array(await r.arrayBuffer()); let bin = "";
        for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
        return reply({ ok: true, data: "data:image/jpeg;base64," + btoa(bin) });
      }
      reply({ ok: true, data: await r.json() });
    } catch (e) { reply({ ok: false, error: String(e) }); }
  })();
  return true;
});
