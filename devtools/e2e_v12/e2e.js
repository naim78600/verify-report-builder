// V12 end-to-end: the REAL helper extension (content.js + background.js) on a mock WhatsApp Web page, talking to the REAL
// HelperServer of the program (started by run.py).  Playwright plays Naim (presses Send, opens a chat) and the verifiers
// (their tap-link answers and the slip photo).  Nothing goes to the internet: web.whatsapp.com is answered by the mock.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const CFG = JSON.parse(process.env.E2E_CFG);
const MOCK = fs.readFileSync(path.join(__dirname, "mock_whatsapp.html"), "utf8");
const log = (...a) => console.log("[e2e]", ...a);

(async () => {
  const ctx = await chromium.launchPersistentContext(CFG.profile, {
    headless: false,
    args: [`--disable-extensions-except=${CFG.ext}`, `--load-extension=${CFG.ext}`, "--no-sandbox"],
  });
  await ctx.route("https://web.whatsapp.com/**", (r) => r.fulfill({ status: 200, contentType: "text/html", body: MOCK }));
  const page = ctx.pages()[0] || (await ctx.newPage());
  global.__page = page;
  page.on("console", (m) => { if (/bk|error/i.test(m.text())) log("console:", m.text().slice(0, 200)); });
  await page.goto("https://web.whatsapp.com/");
  await page.evaluate((n) => { localStorage.clear(); localStorage.setItem("mock_names", JSON.stringify(n)); }, CFG.names);
  await page.reload();
  await page.waitForFunction(() => (document.querySelector("#bk-conn") || {}).textContent === "● যুক্ত", null, { timeout: 30000 });
  log("helper connected to the program");

  // ---- 1. the round: Start -> each chat opens with the text typed + the voice attached; Naim presses Send twice
  await page.click("#bk-start");
  const attaches = [];
  for (const ph of CFG.order) {
    await page.waitForURL((u) => u.pathname.startsWith("/send") && u.searchParams.get("phone") === ph, { timeout: 30000 });
    await page.waitForSelector("#mock-send-attach", { timeout: 30000 });              // voice pasted by the helper
    const typed = await page.textContent("footer div[contenteditable]");
    if (!typed.includes(CFG.codes[ph])) throw new Error("message not typed for " + ph);
    await page.click("#mock-send-attach");                                             // Send 1: the voice
    attaches.push(await page.evaluate(() => window.__lastAttach));
    await page.click("#mock-send");                                                    // Send 2: the message
    log("sent to", ph, "voice", JSON.stringify(attaches[attaches.length - 1]));
  }
  await page.waitForFunction(() => /সবাইকে পাঠানো শেষ/.test(document.querySelector("#bk-msg").textContent), null, { timeout: 60000 });
  log("round finished");

  // ---- 2. the verifiers tap their links: P1 "Joma diyechi" (BS handed in at the bank), P2 "Somossa ache" (trip problem)
  const p1 = CFG.bs_phone, p2 = CFG.trip_phone;          // p1 holds the online BS, p2 has the Hold trip
  await page.evaluate(([a, t]) => window.mockIncoming(a, t), [p1, `Joma diyechi #${CFG.codes[p1]}-B2`]);
  await page.evaluate(([a, t]) => window.mockIncoming(a, t), [p2, `Somossa ache #${CFG.codes[p2]}-T3`]);
  await page.waitForFunction(() => /ফিরতি মেসেজ: 2টি/.test((document.querySelector("#bk-fu") || {}).textContent || ""), null, { timeout: 60000 });
  log("two follow-ups waiting");

  // ---- 3. Naim sends the follow-ups ("send the slip photo", "write the problem") - Send pressed by him
  await page.click("#bk-fu-go");
  for (let i = 0; i < 2; i++) {
    await page.waitForURL((u) => u.pathname.startsWith("/send"), { timeout: 30000 });
    await page.waitForFunction(() => /Send চাপুন/.test(document.querySelector("#bk-msg").textContent), null, { timeout: 30000 });
    const who = new URL(page.url()).searchParams.get("phone");
    const typed = await page.textContent("footer div[contenteditable]");
    log("follow-up to", who, ":", typed.slice(0, 40));
    await page.click("#mock-send");
    if (i === 0) await page.waitForURL((u) => u.searchParams.get("phone") !== who, { timeout: 30000 });
  }
  await page.waitForFunction(() => /ফিরতি মেসেজ সব পাঠানো শেষ/.test(document.querySelector("#bk-msg").textContent), null, { timeout: 30000 });
  log("follow-ups sent");
  await page.goto("https://web.whatsapp.com/");                     // Naim is on the chat list, no chat open
  await page.waitForFunction(() => (document.querySelector("#bk-conn") || {}).textContent === "● যুক্ত", null, { timeout: 30000 });

  // ---- 4. P1 sends the slip photo; P2 writes the reason.  Naim opens P1's chat when the panel says a photo came.
  await page.evaluate((a) => window.mockIncoming(a, "", true), p1);
  await page.evaluate(([a, t]) => window.mockIncoming(a, t), [p2, "Bank bondho chilo, kal jabo"]);
  await page.waitForFunction(() => /ছবি এসেছে/.test((document.querySelector("#bk-fu") || {}).textContent || ""), null, { timeout: 60000 });
  log("panel: photo arrived");
  await page.click(`#pane-side [data-phone="${p1}"]`);
  await page.waitForFunction(() => /স্লিপের ছবি সেভ হয়েছে/.test(document.querySelector("#bk-msg").textContent), null, { timeout: 60000 });
  log("photo saved by the program");
  await page.waitForTimeout(23000);                                 // one more reading pass (P2's note from the chat list)
  fs.writeFileSync(CFG.out, JSON.stringify({ attaches }));
  await ctx.close();
  log("OK");
})().catch(async (e) => {
  console.error("[e2e] FAILED:", e.message.split("\n")[0]);
  try {
    const p = global.__page;
    console.error("[e2e] url:", p.url());
    console.error("[e2e] panel:", await p.evaluate(() => (document.querySelector("#bk-helper") || {}).innerText));
    await p.screenshot({ path: process.env.E2E_SHOT || "/tmp/e2e_fail.png" });
  } catch (_e) { /* the page is gone */ }
  process.exit(1);
});
