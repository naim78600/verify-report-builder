// Barikoi Verify Helper - runs inside web.whatsapp.com.
// It NEVER presses Send.  It opens the next verifier's chat with the reminder typed in (WhatsApp's own
// "click to chat" link), attaches the voice clip, waits until YOU press Send, takes a short break, then goes on.
// It also reads verifiers' replies from the chat list and gives them to the Verify Report Builder program.
(() => {
  "use strict";
  if (window.__bkHelper) return;
  window.__bkHelper = true;

  const BREAK_SECONDS = 8;             // pause after each verifier (5-10 s, as asked)
  const READ_EVERY_MS = 20000;         // look for new replies every 20 s
  const S = { items: [], contacts: {}, connected: false };

  // ---------------------------------------------------------------- talk to the program (via background.js)
  const call = (msg) => new Promise((res) => {
    try { chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false })); } catch (e) { res({ ok: false }); }
  });
  const get = (path) => call({ type: "get", path });
  const post = (path, body) => call({ type: "post", path, body });
  const store = {
    get: (k) => new Promise((res) => chrome.storage.local.get(k, (v) => res(v[k]))),
    set: (k, v) => new Promise((res) => chrome.storage.local.set({ [k]: v }, res)),
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const digits = (s) => (s || "").replace(/\D/g, "");

  // ---------------------------------------------------------------- WhatsApp Web page parts (several fallbacks each)
  const q = (sels, root = document) => { for (const s of sels) { const e = root.querySelector(s); if (e) return e; } return null; };
  const composer = () => q(['footer div[contenteditable="true"]', 'div[contenteditable="true"][data-tab="10"]',
                             '#main div[contenteditable="true"][role="textbox"]']);
  const chatTitle = () => {
    const h = q(["#main header"]);
    if (!h) return "";
    const t = q(['span[dir="auto"][title]', 'span[title]', 'span[dir="auto"]'], h);
    return (t && (t.getAttribute("title") || t.textContent) || "").trim();
  };
  const outgoingCount = () => document.querySelectorAll("#main .message-out, #main [data-id^='true_']").length;
  const invalidNumberPopup = () => {
    const d = q(['div[data-animate-modal-popup="true"]', 'div[role="dialog"]']);
    return d && /invalid|isn.t on whatsapp|not on whatsapp/i.test(d.textContent || "") ? d : null;
  };

  // ---------------------------------------------------------------- panel
  const box = document.createElement("div");
  box.id = "bk-helper";
  box.innerHTML = `
    <div class="bk-head"><div class="bk-logo">V</div><div class="bk-title">Barikoi helper</div>
      <span class="bk-dot" id="bk-conn">…</span><button id="bk-min" title="ছোট / বড়">–</button></div>
    <div class="bk-body">
      <div><div class="bk-muted" id="bk-round">রিমাইন্ডার রাউন্ড</div><div style="font-size:18px;font-weight:700" id="bk-count">–</div>
        <div class="bk-bar"><div id="bk-prog"></div></div></div>
      <div class="bk-now" id="bk-now" style="display:none"></div>
      <div class="bk-muted" id="bk-msg">প্রোগ্রামে রাউন্ড তৈরি হলে এখানে দেখাবে।</div>
      <div class="bk-row"><button class="bk-primary" id="bk-start">শুরু করুন</button><button id="bk-stop">থামান</button>
        <button id="bk-skip">পরের জন</button></div>
    </div>`;
  document.body.appendChild(box);
  const $ = (id) => box.querySelector("#" + id);
  $("bk-min").onclick = () => box.classList.toggle("bk-min");
  const say = (t) => { $("bk-msg").textContent = t; };

  async function refresh() {
    const r = await get("/round");
    S.connected = !!r.ok;
    $("bk-conn").textContent = r.ok ? "● যুক্ত" : "● প্রোগ্রাম বন্ধ";
    $("bk-conn").style.color = r.ok ? "#15803D" : "#B91C1C";
    if (!r.ok) return;
    S.items = r.data.items || [];
    S.contacts = r.data.contacts || {};
    const sent = S.items.filter((i) => i.sent).length;
    $("bk-count").textContent = S.items.length ? `${sent} / ${S.items.length} পাঠানো` : "এখন কোনো রাউন্ড নেই";
    $("bk-round").textContent = S.items.length ? `রাউন্ড ${S.items[0].round}` : "রিমাইন্ডার রাউন্ড";
    $("bk-prog").style.width = S.items.length ? `${Math.round((sent * 100) / S.items.length)}%` : "0";
  }

  // ---------------------------------------------------------------- the one-by-one flow
  async function nextItem() {
    await refresh();
    const skipped = (await store.get("bk_skip")) || [];
    return S.items.find((i) => !i.sent && !skipped.includes(i.phone)) || null;
  }

  async function openNext() {
    const it = await nextItem();
    if (!it) { await store.set("bk_run", null); say("এই রাউন্ডের সবাইকে পাঠানো শেষ ✓"); return; }
    await store.set("bk_run", { phone: it.phone, at: Date.now() });
    // WhatsApp's own click-to-chat link: opens the chat with the message already typed in (nothing is sent)
    location.href = `https://web.whatsapp.com/send?phone=${it.phone}&text=${encodeURIComponent(it.text)}`;
  }

  async function attachVoice(name) {
    const v = await call({ type: "voice", name });
    if (!v.ok) return false;
    const bin = atob(v.b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    const ext = v.type.includes("mpeg") ? "mp3" : v.type.includes("wav") ? "wav" : "ogg";
    const file = new File([arr], `barikoi-${name}.${ext}`, { type: v.type });
    const dt = new DataTransfer();
    dt.items.add(file);
    const c = composer();
    if (!c) return false;
    c.focus();
    c.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
    await sleep(1500);
    return true;
  }

  async function continueRun() {
    const run = await store.get("bk_run");
    if (!run || Date.now() - run.at > 10 * 60 * 1000) return;     // nothing in progress (or very old)
    await refresh();
    const it = S.items.find((i) => i.phone === run.phone);
    if (!it) return;
    $("bk-now").style.display = "block";
    $("bk-now").innerHTML = `<div class="bk-muted">এখন</div><b>${escapeHtml(it.verifier)}</b> · ${escapeHtml(it.priority || "")}
      <div class="bk-muted">মেসেজ লেখা আছে, ভয়েস যুক্ত হচ্ছে… তারপর Send চাপুন।</div>`;
    // wait for the chat to open (or WhatsApp to say the number is not on WhatsApp)
    for (let i = 0; i < 60 && !composer(); i++) {
      if (invalidNumberPopup()) {
        await post("/reply", { phone: it.phone, text: "__no_whatsapp__" });
        say(`${it.verifier}: এই নম্বরে WhatsApp নেই। পরের জনে যাচ্ছি…`);
        const sk = (await store.get("bk_skip")) || []; sk.push(it.phone); await store.set("bk_skip", sk);
        await sleep(3000);
        return openNext();
      }
      await sleep(500);
    }
    if (!composer()) { say("চ্যাট খোলেনি। ‘শুরু করুন’ আবার চাপুন।"); return; }
    const name = chatTitle();
    if (name) post("/contact", { name, phone: it.phone });
    if (it.voice) {
      const ok = await attachVoice(it.voice);
      say(ok ? "ভয়েস যুক্ত হয়েছে: আগে ভয়েসের Send, তারপর মেসেজের Send চাপুন।" : "ভয়েস যুক্ত করা যায়নি; শুধু মেসেজ পাঠান (Send চাপুন)।");
    } else {
      say("মেসেজ লেখা আছে। Send চাপুন।");
    }
    // wait until YOU press Send: the message box becomes empty and a new outgoing message appears
    const before = outgoingCount();
    for (let i = 0; i < 1200; i++) {                       // up to 10 minutes
      await sleep(500);
      const c = composer();
      const text = c ? (c.textContent || "").trim() : "";
      if (outgoingCount() > before && text === "") break;
      if (!(await store.get("bk_run"))) return;            // stopped
    }
    await post("/sent", { phone: it.phone });
    for (let s = BREAK_SECONDS; s > 0; s--) {
      say(`পাঠানো হয়েছে ✓  বিরতি… পরের জন ${s} সেকেন্ড পরে`);
      await sleep(1000);
      if (!(await store.get("bk_run"))) { say("থামানো হয়েছে।"); return; }
    }
    openNext();
  }

  // ---------------------------------------------------------------- replies (read only)
  const seen = new Map();
  function phoneForTitle(title) {
    if (!title) return "";
    if (S.contacts[title]) return S.contacts[title];
    const d = digits(title);
    if (d.length >= 11) return d.startsWith("01") ? "88" + d : d;
    return "";
  }
  // The last message of a chat-list row is OURS when WhatsApp draws its ticks / clock there.
  // (checked on the real WhatsApp Web, Nov 2026: an <svg><title>wds-ic-read</title> inside [data-testid="last-msg-status"];
  //  older builds: span[data-icon="msg-check"] etc.)
  function lastIsMine(row) {
    if (row.querySelector('span[data-icon^="msg-"], span[data-icon*="check"], [data-icon="status-time"]')) return true;
    for (const t of row.querySelectorAll("svg title")) {
      if (/(^|-)ic-(read|delivered|sent|check|dblcheck|done|done-all|pending|clock|schedule|msg-)|msg-(check|dblcheck|time)/i.test(t.textContent || "")) return true;
    }
    return false;
  }
  async function readReplies() {
    if (!S.connected || !S.items.length) return;
    const known = new Set(S.items.map((i) => i.phone));
    const rows = document.querySelectorAll('#pane-side [role="listitem"], #pane-side [role="row"]');
    for (const row of rows) {
      const spans = row.querySelectorAll("span[title]");
      if (!spans.length) continue;
      const title = spans[0].getAttribute("title") || "";
      const phone = phoneForTitle(title);
      if (!phone || !known.has(phone)) continue;
      if (lastIsMine(row)) continue;                       // our own message shows ticks
      const preview = (spans[spans.length - 1].getAttribute("title") || "").trim();
      if (!preview || preview === title || seen.get(phone) === preview) continue;
      seen.set(phone, preview);
      await post("/reply", { phone, text: preview });
    }
    // the open chat: incoming messages after our last one
    const t = chatTitle();
    const phone = phoneForTitle(t);
    if (phone && known.has(phone)) {
      const all = [...document.querySelectorAll("#main .message-in, #main .message-out")];
      let lastOut = -1;
      all.forEach((m, i) => { if (m.classList.contains("message-out")) lastOut = i; });
      for (const m of all.slice(lastOut + 1)) {
        const txt = (q(["span.selectable-text", "span[dir='ltr']"], m) || {}).textContent || "";
        if (txt && seen.get(phone + "#" + txt) !== true) {
          seen.set(phone + "#" + txt, true);
          await post("/reply", { phone, text: txt });
        }
      }
    }
  }

  function escapeHtml(s) { return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  $("bk-start").onclick = async () => { await store.set("bk_skip", []); openNext(); };
  $("bk-stop").onclick = async () => { await store.set("bk_run", null); say("থামানো হয়েছে। আবার ‘শুরু করুন’ চাপলে যেখানে থেমেছিল সেখান থেকে চলবে।"); };
  $("bk-skip").onclick = async () => {
    const run = await store.get("bk_run");
    if (run) { const sk = (await store.get("bk_skip")) || []; sk.push(run.phone); await store.set("bk_skip", sk); }
    openNext();
  };

  (async () => {
    await refresh();
    setInterval(refresh, 30000);
    // "Start sending" pressed in the program: the first WhatsApp tab that sees it starts (the chats open, Send stays yours)
    setInterval(async () => {
      const r = await get("/round");
      S.connected = !!r.ok;
      $("bk-conn").textContent = r.ok ? "● যুক্ত" : "● প্রোগ্রাম বন্ধ";
      $("bk-conn").style.color = r.ok ? "#15803D" : "#B91C1C";
      const run = await store.get("bk_run");
      if (!r.ok || !r.data.start || (run && Date.now() - run.at < 10 * 60 * 1000)) return;
      const c = await post("/claim", { token: r.data.start });
      if (c.ok && c.data && c.data.ok) { await store.set("bk_skip", []); openNext(); }
    }, 4000);
    setInterval(readReplies, READ_EVERY_MS);
    continueRun();
  })();
})();
