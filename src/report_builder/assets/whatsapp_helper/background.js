// Barikoi Verify Helper - talks to the Verify Report Builder program on THIS computer only (127.0.0.1).
const BASE = "http://127.0.0.1:47321";

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    try {
      if (msg.type === "get") {
        const r = await fetch(BASE + msg.path + "?v=" + chrome.runtime.getManifest().version, { cache: "no-store" });
        reply({ ok: r.ok, data: await r.json() });
      } else if (msg.type === "post") {
        const r = await fetch(BASE + msg.path, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(msg.body || {}),
        });
        reply({ ok: r.ok, data: await r.json() });
      } else if (msg.type === "voice") {
        const r = await fetch(BASE + "/voice/" + encodeURIComponent(msg.name), { cache: "no-store" });
        if (!r.ok) return reply({ ok: false });
        const buf = await r.arrayBuffer();
        let bin = "";
        const bytes = new Uint8Array(buf);
        for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        reply({ ok: true, b64: btoa(bin), type: r.headers.get("Content-Type") || "audio/ogg" });
      }
    } catch (e) {
      reply({ ok: false, error: String(e) });
    }
  })();
  return true; // async reply
});
