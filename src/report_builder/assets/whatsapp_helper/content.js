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
  // WhatsApp Web, Nov 2026 (checked on the live page): each message is [data-testid="conv-msg-<id>"]; our own ones carry
  // a status icon (<svg><title>wds-ic-read | wds-ic-delivered | ...</title>).  Older builds: .message-out / .message-in.
  const STATUS = /(^|-)ic-(read|delivered|sent|check|dblcheck|done|done-all|pending|clock|schedule|time|sending|error)|msg-(check|dblcheck|time)/i;
  const messages = () => [...document.querySelectorAll('#main [data-testid^="conv-msg-"], #main .message-in, #main .message-out')];
  const isMine = (m) => {
    if (m.classList.contains("message-out")) return true;
    if (m.classList.contains("message-in")) return false;
    for (const t of m.querySelectorAll("svg title")) if (STATUS.test(t.textContent || "")) return true;
    return false;
  };
  const lastMsgId = () => {
    const all = messages();
    const m = all[all.length - 1];
    return m ? (m.getAttribute("data-testid") || m.getAttribute("data-id") || String(all.length)) : "";
  };
  const attachmentOpen = () => !!document.querySelector('[aria-label="Remove attachment"], [aria-label^="Send "][aria-label$="selected"]');
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
      <div class="bk-fu" id="bk-fu" style="display:none"></div>
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
    for (let i = 0; i < 15 && !attachmentOpen(); i++) await sleep(100);   // WhatsApp shows the attachment drawer
    return attachmentOpen() || (await sleep(1000), true);
  }

  async function continueRun() {
    const run = await store.get("bk_run");
    if (!run || Date.now() - run.at > 10 * 60 * 1000) return;     // nothing in progress (or very old)
    await refresh();
    const it = S.items.find((i) => i.phone === run.phone);
    if (!it) return;
    $("bk-now").style.display = "block";
    $("bk-now").innerHTML = `<div class="bk-muted">এখন</div><b>${escapeHtml(it.verifier)}</b> · +${escapeHtml(it.phone)} · ${escapeHtml(it.priority || "")}
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
    const before = lastMsgId();                            // taken before the voice goes in: a quick Send is still seen
    if (it.voice) {
      const ok = await attachVoice(it.voice);
      say(ok ? "২ বার Send: ১) ডানে নিচের সবুজ Send (ভয়েস যাবে)  ২) তারপর মেসেজের Send।"
                                    : "ভয়েস যুক্ত করা যায়নি; শুধু মেসেজ পাঠান (Send চাপুন)।");
    } else {
      say("মেসেজ লেখা আছে। Send চাপুন।");
    }
    // wait until YOU press Send: a new message of yours is the last one, the message box is empty and no attachment waits
    let done = false;
    for (let i = 0; i < 1200; i++) {                       // up to 10 minutes
      await sleep(500);
      const c = composer();
      const text = c ? (c.textContent || "").trim() : "";
      const now = lastMsgId();
      if (now && now !== before && !attachmentOpen() && text === "") { done = true; break; }
      if (!(await store.get("bk_run"))) return;            // stopped
    }
    if (!done) { say("১০ মিনিটে পাঠানো হয়নি। ‘শুরু করুন’ চাপলে আবার এখান থেকে চলবে।"); await store.set("bk_run", null); return; }
    await post("/sent", { phone: it.phone });
    for (let s = BREAK_SECONDS; s > 0; s--) {
      say(`পাঠানো হয়েছে ✓  বিরতি… পরের জন ${s} সেকেন্ড পরে`);
      await sleep(1000);
      if (!(await store.get("bk_run"))) { say("থামানো হয়েছে।"); return; }
    }
    openNext();
  }

  // ---------------------------------------------------------------- V12 follow-ups ("ছবি পাঠান" / "সমস্যা লিখুন") and slip photos
  S.asks = [];
  async function refreshAsks() {
    const r = await get("/asks");
    S.asks = r.ok ? (r.data.asks || []) : [];
    const toSend = S.asks.filter((a) => !a.sent && !a.answered);
    const photos = S.asks.filter((a) => a.want === "photo" && !a.answered);
    const arrived = photos.filter((a) => S.photoIn[a.phone]);
    const el = $("bk-fu");
    if (!toSend.length && !photos.length) { el.style.display = "none"; return; }
    el.style.display = "block";
    el.innerHTML = (toSend.length ? `<div><b>ফিরতি মেসেজ: ${toSend.length}টি</b> <span class="bk-muted">(ছবি / কারণ চাওয়া)</span></div>
        <div class="bk-row"><button class="bk-primary" id="bk-fu-go">পাঠানো শুরু</button></div>` : "") +
      (arrived.length ? `<div style="margin-top:6px"><b>📷 ছবি এসেছে: ${arrived.map((a) => escapeHtml(a.verifier)).join(", ")}</b></div>
        <div class="bk-muted">বাঁ দিকের তালিকা থেকে চ্যাটটি খুলুন — ছবি নিজে সেভ হবে।</div>` : "") +
      (photos.length > arrived.length ? `<div class="bk-muted" style="margin-top:6px">স্লিপের ছবির অপেক্ষা: ${photos.filter((a) => !S.photoIn[a.phone]).map((a) => escapeHtml(a.verifier)).join(", ")}</div>` : "");
    const b = el.querySelector("#bk-fu-go");
    if (b) b.onclick = async () => { await store.set("bk_fu_skip", []); openNextAsk(); };
  }
  async function openNextAsk() {
    await refreshAsks();
    const skip = (await store.get("bk_fu_skip")) || [];
    const a = S.asks.find((x) => !x.sent && !x.answered && !skip.includes(x.phone));
    if (!a) { await store.set("bk_fu", null); say("ফিরতি মেসেজ সব পাঠানো শেষ ✓"); return; }
    await store.set("bk_fu", { phone: a.phone, at: Date.now() });
    location.href = `https://web.whatsapp.com/send?phone=${a.phone}&text=${encodeURIComponent(a.text)}`;
  }
  async function continueAsk() {
    const run = await store.get("bk_fu");
    if (!run || Date.now() - run.at > 10 * 60 * 1000) return false;
    for (let i = 0; i < 60 && !composer(); i++) await sleep(500);
    if (!composer()) return true;
    say("ফিরতি মেসেজ লেখা আছে — Send চাপুন।");
    const before = lastMsgId();
    for (let i = 0; i < 1200; i++) {
      await sleep(500);
      const c = composer();
      if (lastMsgId() !== before && c && !(c.textContent || "").trim()) {
        await post("/ask_sent", { phone: run.phone });
        for (let s = BREAK_SECONDS; s > 0; s--) { say(`পাঠানো হয়েছে ✓  পরেরটি ${s} সেকেন্ড পরে`); await sleep(1000); }
        await openNextAsk();
        return true;
      }
      if (!(await store.get("bk_fu"))) return true;
    }
    await store.set("bk_fu", null);
    return true;
  }
  // a picture in the open chat, sent by the verifier after our "send the slip photo" message -> saved by the program
  const imgSeen = new Set();
  S.photoIn = {};                                          // chat-list rows showing a new photo from someone we asked for a slip
  const PHOTO_PREVIEW = /^(📷\s*)?(photo|ছবি|image)$/i;
  async function grabPhotos(phone) {
    const a = S.asks.find((x) => x.phone === phone && x.want === "photo");
    if (!a) return;
    const all = messages();
    let lastOut = -1;
    all.forEach((m, i) => { if (isMine(m)) lastOut = i; });
    for (const m of all.slice(lastOut + 1)) {
      const id = m.getAttribute("data-testid") || m.getAttribute("data-id") || "";
      if (!id || imgSeen.has(id)) continue;
      const img = [...m.querySelectorAll("img")].filter((i) => (i.src || "").startsWith("blob:"))
        .sort((x, y) => (y.naturalWidth * y.naturalHeight) - (x.naturalWidth * x.naturalHeight))[0];
      if (!img) continue;
      imgSeen.add(id);
      try {
        const blob = await (await fetch(img.src)).blob();
        const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
        const r = await post("/media", { phone, b64, type: blob.type, msg: id });
        if (r.ok && r.data && r.data.ok) { delete S.photoIn[phone]; say(`স্লিপের ছবি সেভ হয়েছে ✓ (${r.data.files.length}টি ট্রিপ)`); }
      } catch (e) { imgSeen.delete(id); }
    }
  }

  // ---------------------------------------------------------------- V18: WhatsApp check (which verifier numbers are on WhatsApp)
  // Opens each number's chat WITHOUT any text: the chat opens = connected, WhatsApp's "not on WhatsApp" box = not connected.
  // Nothing is typed or sent.  A check asked by the program's button starts at once; the daily automatic one waits until
  // this tab has not been used for 90 seconds, and stops as soon as you click or type.
  const CHECK_GAP_MS = 6000;
  let lastUse = Date.now();
  ["mousedown", "keydown", "wheel", "touchstart"].forEach((ev) => document.addEventListener(ev, (e) => { if (e.isTrusted && !box.contains(e.target)) lastUse = Date.now(); }, true));
  async function openNextCheck() {
    const c = await store.get("bk_check");
    if (!c || c.i >= c.items.length) { await store.set("bk_check", null); say("WhatsApp চেক শেষ ✓"); return; }
    c.at = Date.now(); await store.set("bk_check", c);
    location.href = `https://web.whatsapp.com/send?phone=${c.items[c.i].phone}`;
  }
  async function continueCheck() {
    const c = await store.get("bk_check");
    if (!c || Date.now() - c.at > 5 * 60 * 1000) return false;
    const it = c.items[c.i];
    if (!it) { await store.set("bk_check", null); return false; }
    $("bk-now").style.display = "block";
    $("bk-now").innerHTML = `<div class="bk-muted">WhatsApp চেক ${c.i + 1} / ${c.items.length}</div><b>${escapeHtml(it.verifier)}</b> · +${escapeHtml(it.phone)}`;
    let ok = null;
    for (let i = 0; i < 60 && ok === null; i++) {
      if (invalidNumberPopup()) ok = false; else if (composer()) ok = true; else await sleep(500);
    }
    if (ok !== null) await post("/wa_check", { phone: it.phone, ok });
    say(ok === null ? `${it.verifier}: উত্তর পাওয়া যায়নি, পরে আবার চেক হবে।` : ok ? `${it.verifier}: WhatsApp আছে ✓` : `${it.verifier}: এই নম্বরে WhatsApp নেই`);
    c.i += 1; await store.set("bk_check", c);
    for (let s = CHECK_GAP_MS / 1000; s > 0; s--) {
      await sleep(1000);
      if (c.auto && Date.now() - lastUse < 3000) { await store.set("bk_check", null); say("আপনি WhatsApp ব্যবহার করছেন, চেক থামানো হলো। পরে আবার চলবে।"); return true; }
      if (!(await store.get("bk_check"))) { say("চেক থামানো হয়েছে।"); return true; }
    }
    await openNextCheck();
    return true;
  }
  async function maybeStartCheck() {
    if ((await store.get("bk_run")) || (await store.get("bk_fu")) || (await store.get("bk_check"))) return;
    const r = await get("/wa_check");
    if (!r.ok || !r.data.start || !(r.data.items || []).length) return;
    if (r.data.auto && Date.now() - lastUse < 90000) return;          // automatic check: only while the tab is not in use
    const c = await post("/wa_check_claim", { token: r.data.start });
    if (!(c.ok && c.data && c.data.ok)) return;
    await store.set("bk_check", { items: r.data.items, i: 0, at: Date.now(), auto: !!r.data.auto });
    say(`WhatsApp চেক শুরু: ${r.data.items.length}টি নম্বর (কিছু লেখা বা পাঠানো হয় না)`);
    openNextCheck();
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
      if (STATUS.test(t.textContent || "")) return true;
    }
    return false;
  }
  async function readReplies() {
    if (!S.connected) return;
    await refreshAsks();
    const known = new Set(S.items.map((i) => i.phone).concat(S.asks.map((a) => a.phone)));
    if (!known.size) return;
    const rows = document.querySelectorAll('#pane-side [role="listitem"], #pane-side [role="row"]');
    for (const row of rows) {
      const spans = row.querySelectorAll("span[title]");
      if (!spans.length) continue;
      const title = spans[0].getAttribute("title") || "";
      const phone = phoneForTitle(title);
      if (!phone || !known.has(phone)) continue;
      if (lastIsMine(row)) continue;                       // our own message shows ticks
      const preview = (spans[spans.length - 1].getAttribute("title") || "").trim();
      const wantsPhoto = S.asks.some((a) => a.phone === phone && a.want === "photo");
      if (wantsPhoto && (row.querySelector('[data-icon="status-image"], [data-icon*="image"]') || PHOTO_PREVIEW.test(preview))) {
        S.photoIn[phone] = true;                           // a photo is not a text answer: the program saves it from the open chat
        continue;
      }
      if (!preview || preview === title || seen.get(phone) === preview) continue;
      seen.set(phone, preview);
      await post("/reply", { phone, text: preview });
    }
    // the open chat: incoming messages after our last one
    const t = chatTitle();
    const phone = phoneForTitle(t);
    if (phone && known.has(phone)) {
      await grabPhotos(phone);
      const all = messages();
      let lastOut = -1;
      all.forEach((m, i) => { if (isMine(m)) lastOut = i; });
      for (const m of all.slice(lastOut + 1)) {
        const txt = ((q(['[data-testid="selectable-text"]', "span.selectable-text", "span[dir='ltr']"], m) || {}).textContent || "").trim();
        if (txt && seen.get(phone + "#" + txt) !== true) {
          seen.set(phone + "#" + txt, true);
          await post("/reply", { phone, text: txt });
        }
      }
    }
  }

  function escapeHtml(s) { return String(s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  $("bk-start").onclick = async () => { await store.set("bk_skip", []); openNext(); };
  $("bk-stop").onclick = async () => { await store.set("bk_run", null); await store.set("bk_check", null); say("থামানো হয়েছে। আবার ‘শুরু করুন’ চাপলে যেখানে থেমেছিল সেখান থেকে চলবে।"); };
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
    setInterval(maybeStartCheck, 5000);
    await refreshAsks();
    if (!(await continueAsk()) && !(await continueCheck())) continueRun();
  })();
})();
