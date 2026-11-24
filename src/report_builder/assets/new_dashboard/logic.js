function vrbMakeComponent(DATA) {
const MON = DATA.monName || 'Nov', YEAR = DATA.year || 2026, MONTH = DATA.mon || 11, TODAY = DATA.today || 23;
const DIM = new Date(Date.UTC(YEAR, MONTH, 0)).getUTCDate(), PDIM = new Date(Date.UTC(YEAR, MONTH - 1, 0)).getUTCDate();
const MONS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmt(n) { return Math.round(n || 0).toLocaleString('en-US'); }
function pct(a, b) { return b ? Math.round(a * 1000 / b) / 10 : 0; }
const TST = { 1: 'Created', 2: 'Allocated', 3: 'Started', 4: 'Hold', 5: 'Finished', 6: 'Canceled', 7: 'Inactive', 8: 'Withdrawn' };
const TSC = { 1: 'ts1', 2: 'ts2', 3: 'ts3', 4: 'ts4', 5: 'ts5', 6: 'ts6', 7: 'ts7', 8: 'ts8' };
const FST = { 1: 'Created', 2: 'On Going', 3: 'Hold', 4: 'Finished', 5: 'Canceled', 6: 'Submitted', 7: 'Partially Submitted', 8: 'Withdrawn' };
const FSC = { 1: 'fs1', 2: 'fs2', 3: 'fs3', 4: 'fs4', 5: 'fs5', 6: 'fs6', 7: 'fs7', 8: 'fs8' };
const ACT = { 1: ['Online', 'act1'], 2: ['Waiting', 'act2'], 3: ['Break', 'act3'], 4: ['Away', 'act4'], 5: ['Offline', 'act5'] };
const TODO = { House: 'ঠিকানা, মোবাইল, কতদিন আছেন, কে কনফার্ম করলেন — remarks-এ লিখবেন', Office: 'অফিস, পদবি, বেতন যাচাই + আবেদনকারীর স্বাক্ষর',
  'Bank (BS)': 'Bank statement hard copy + ব্যাংক কর্মকর্তার নাম ও নম্বর', 'PG House': 'গ্যারান্টরের বাসা যাচাই + স্বাক্ষর', 'PG Office': 'গ্যারান্টরের অফিস যাচাই + স্বাক্ষর' };
const BN = (n) => String(n).replace(/[0-9]/g, (c) => '০১২৩৪৫৬৭৮৯'[c]);
function dayOf(m) { return m == null ? null : Math.floor(m / 1440) + 1; }
function tTxt(m) { if (m == null) return '—'; const d = dayOf(m), r = ((m % 1440) + 1440) % 1440; return (d < 1 ? (d + PDIM) + ' ' + MONS[(MONTH + 10) % 12] : d > DIM ? (d - DIM) + ' ' + MONS[MONTH % 12] : d + ' ' + MON) + ', ' + String(Math.floor(r / 60)).padStart(2, '0') + ':' + String(r % 60).padStart(2, '0'); }
function hTxt(m) { if (m == null) return '—'; const r = ((m % 1440) + 1440) % 1440; return String(Math.floor(r / 60)).padStart(2, '0') + ':' + String(r % 60).padStart(2, '0'); }
function ago(h) { if (h == null) return '—'; if (h < 1) return 'just now'; if (h < 24) return Math.round(h) + 'h ago'; return Math.round(h / 24) + 'd ago'; }
function ageCls(h) { return h == null ? '' : h >= 72 ? 'age-red' : h >= 24 ? 'age-amber' : 'age-ok'; }
function ini(n) { return String(n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase(); }
function bars(pairs, n, onPick) { const m = Math.max(1, ...pairs.map((p) => p[1])); return pairs.slice(0, n || 10).map(([k, v, sub]) => ({ n: k, v: fmt(v), sub: sub || '', w: 'width:' + Math.max(2, v * 100 / m) + '%', pick: onPick ? () => onPick(k) : null })); }
function reason(rem) {
  const r = (rem || '').toLowerCase();
  if (!r) return 'No reason written';
  if (r.includes('withdraw')) return 'Withdraw letter not provided';
  if (r.includes('previous report')) return 'Duplicate (see earlier report)';
  if (r.includes('not found') || r.includes('switched off')) return 'Applicant / office not found';
  if (r.includes(' ok') || r.includes('confirm')) return 'Info was OK, canceled anyway';
  return 'Other';
}

// ---- one-time expansion of compact data ----
const ORG = DATA.orgs, NOW = DATA.now;
const VER = {}; DATA.ver.forEach((v) => { VER[v.id] = v; });
const FILES = DATA.files.map((f, i) => ({ i, file: f[0], o: f[1], os: ORG[f[1]], app: f[2] === 1 ? 'Loan' : 'Card', st: f[3], start: f[4], sla: f[5], station: f[6] === '1' ? 'In' : f[6] === '0' ? 'Out' : '—', attach: f[7], end: f[8], finN: f[9], day: dayOf(f[4]) }));
const TRIPS = DATA.trips.map((t) => {
  const f = FILES[t[1]], upd = Math.max(t[6] || 0, t[7] || 0, t[8] || 0);
  const ap = t[12] ? { at: t[12][0], kind: t[12][1], why: t[12][2] } : null;
  return { tid: t[0], fi: t[1], file: f.file, o: f.o, os: f.os, tl: DATA.types[t[2]], st: t[3], area: t[4] || '—', ag: t[5], agent: t[5] ? (VER[t[5]] || { a: 'Verifier ' + t[5] }).a : 'Not assigned',
    cr: t[6], start: t[7], end: t[8], recpv: t[9], rem: t[10], cmt: t[11], ap, upd, ageH: (NOW - upd) / 60, day: dayOf(t[6]), sla: f.sla, station: f.station };
});
FILES.forEach((f) => { f.trips = []; }); TRIPS.forEach((t) => FILES[t.fi].trips.push(t));
const OPEN = TRIPS.filter((t) => t.st >= 1 && t.st <= 4);
const SLA = {};
['upcoming', 'today', 'all'].forEach((k) => { SLA[k] = DATA.sla[k].map((r) => ({ tid: r[0], o: r[1], os: ORG[r[1]], st: r[2] ? 'In' : 'Out', agent: r[3] || 'Unassigned', area: r[4] || '—', cr: r[5], sla: r[6], h: r[7] })); });
SLA.last7 = SLA.all.filter((r) => r.sla >= NOW - 7 * 1440);

function waMsg(name, list) {
  const L = ['আসসালামু আলাইকুম' + (name && name !== 'Not assigned' ? ', ' + name : ''), 'ড্যাশবোর্ডে আপনার *' + BN(list.length) + 'টি ট্রিপ* এখনো On Going / Hold-এ আছে।'];
  const one = (t, i) => {
    L.push('', '*' + (i + 1) + ') Trip ID ' + t.tid + ' · ' + t.tl + ' · ' + TST[t.st] + '*', 'File No: ' + t.file + ' · ' + t.os);
    if (t.ap) L.push('Appointment: ' + tTxt(t.ap.at) + ' (' + t.ap.kind + ')');
    if (t.st === 4 && t.cmt) L.push('Hold reason: ' + t.cmt);
    if (TODO[t.tl]) L.push('করণীয়: ' + TODO[t.tl]);
    if (t.sla) L.push('SLA: ' + tTxt(t.sla) + (t.sla < NOW ? ' ⚠ পার হয়ে গেছে' : ''));
  };
  const shown = list.slice(0, 8), hold = shown.filter((t) => t.st === 4), going = shown.filter((t) => t.st !== 4);
  let i = 0;
  if (hold.length) { L.push('', '⛔ *HOLD — ' + BN(list.filter((t) => t.st === 4).length) + 'টি*', 'Hold-এর সঠিক কারণ লিখে Update করুন, কাজ হলে Remarks দিয়ে Trip Finish করুন।'); hold.forEach((t) => one(t, i++)); }
  if (going.length) { L.push('', '▶ *ON GOING — ' + BN(list.filter((t) => t.st !== 4).length) + 'টি*'); going.forEach((t) => one(t, i++)); }
  if (list.length > 8) L.push('', 'আরও ' + BN(list.length - 8) + 'টি ট্রিপ — ড্যাশবোর্ডে দেখুন।');
  L.push('', 'উত্তর দিন: 1 = যাচ্ছি / কাজ চলছে, 2 = Finish করেছি, 3 = সমস্যা আছে');
  return 'https://wa.me/?text=' + encodeURIComponent(L.join('\n'));
}
function waSla(name, rows, up) {
  const L = ['আসসালামু আলাইকুম' + (name && name !== 'Unassigned' ? ', ' + name : ''), up ? 'আপনার *' + BN(rows.length) + 'টি ট্রিপের* SLA আগামী ২৪ ঘণ্টার মধ্যে শেষ হবে। আগে এগুলো শেষ করুন:' : 'আপনার *' + BN(rows.length) + 'টি ট্রিপের* SLA পার হয়ে গেছে। আজই শেষ করুন:'];
  rows.slice(0, 10).forEach((r, i) => { L.push('', '*' + (i + 1) + ') Trip ID ' + r.tid + '* · ' + r.os + ' · ' + r.area, 'SLA: ' + tTxt(r.sla) + (up ? ' (আর ' + Math.abs(r.h) + ' ঘণ্টা)' : ' (' + r.h + ' ঘণ্টা দেরি)')); });
  if (rows.length > 10) L.push('', 'আরও ' + BN(rows.length - 10) + 'টি — ড্যাশবোর্ডে দেখুন।');
  L.push('', 'উত্তর দিন: 1 = যাচ্ছি / কাজ চলছে, 2 = Finish করেছি, 3 = সমস্যা আছে');
  return 'https://wa.me/?text=' + encodeURIComponent(L.join('\n'));
}
const NAME2ID = {}; DATA.ver.forEach((v) => { NAME2ID[v.a.toLowerCase()] = v.id; });

function normPhone(v) { let d = String(v == null ? '' : v).replace(/\D/g, ''); if (d.startsWith('880')) d = d.slice(2); if (d.length === 10 && d[0] === '1') d = '0' + d; return d; }
function isBd(v) { return /^01[3-9]\d{8}$/.test(v); }
function maskPh(v) { return v ? v.slice(0, 3) + '•• •••' + v.slice(-3) : '—'; }
function parseCsv(text) {
  const rows = []; let row = [], cell = '', q = false;
  for (let i = 0; i < text.length; i++) { const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
    else if (c === '"') q = true; else if (c === ',' || c === '\t' || c === ';') { row.push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; row.push(cell); rows.push(row); row = []; cell = ''; } else cell += c; }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((x) => String(x).trim()));
}
async function unzipEntries(buf) {
  const dv = new DataView(buf), u8 = new Uint8Array(buf); let eocd = -1;
  for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 66000); i--) if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error('not a zip');
  const n = dv.getUint16(eocd + 10, true); let p = dv.getUint32(eocd + 16, true); const out = {};
  for (let k = 0; k < n; k++) {
    const method = dv.getUint16(p + 10, true), csize = dv.getUint32(p + 20, true), nlen = dv.getUint16(p + 28, true), elen = dv.getUint16(p + 30, true), clen = dv.getUint16(p + 32, true), off = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(u8.subarray(p + 46, p + 46 + nlen));
    const lo = off + 30 + dv.getUint16(off + 26, true) + dv.getUint16(off + 28, true), data = u8.subarray(lo, lo + csize);
    out[name] = method === 0 ? data : new Uint8Array(await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer());
    p += 46 + nlen + elen + clen;
  }
  return out;
}
async function parseXlsx(buf) {
  const z = await unzipEntries(buf), td = new TextDecoder(), xml = (k) => (z[k] ? new DOMParser().parseFromString(td.decode(z[k]), 'application/xml') : null);
  const ss = xml('xl/sharedStrings.xml'), strs = ss ? Array.from(ss.getElementsByTagName('si')).map((si) => Array.from(si.getElementsByTagName('t')).map((t) => t.textContent).join('')) : [];
  const sheetName = Object.keys(z).filter((k) => /^xl\/worksheets\/sheet\d+\.xml$/.test(k)).sort()[0]; const sh = xml(sheetName); if (!sh) return [];
  const col = (ref) => { let c = 0; for (const ch of ref.replace(/\d+/g, '')) c = c * 26 + (ch.charCodeAt(0) - 64); return c - 1; };
  return Array.from(sh.getElementsByTagName('row')).map((r) => { const a = []; Array.from(r.getElementsByTagName('c')).forEach((c) => {
    const t = c.getAttribute('t'), v = c.getElementsByTagName('v')[0], is = c.getElementsByTagName('t')[0];
    a[col(c.getAttribute('r') || 'A1')] = t === 's' ? strs[+(v && v.textContent)] : t === 'inlineStr' ? (is ? is.textContent : '') : (v ? v.textContent : ''); });
    return Array.from(a, (x) => (x == null ? '' : String(x))); }).filter((r) => r.some((x) => x.trim()));
}
async function thumb(file) {
  try { const bmp = await createImageBitmap(file); const s = 160, c = document.createElement('canvas'); c.width = s; c.height = s; const x = c.getContext('2d');
    const k = Math.max(s / bmp.width, s / bmp.height), w = bmp.width * k, h = bmp.height * k; x.drawImage(bmp, (s - w) / 2, (s - h) / 2, w, h); return c.toDataURL('image/jpeg', 0.82); }
  catch (e) { return ''; }
}
const WA_KEY = 'vrb_verifier_directory_v1';
function loadDir() { try { return JSON.parse(localStorage.getItem(WA_KEY) || '{}'); } catch (e) { return {}; } }
function saveDir(d) { try { localStorage.setItem(WA_KEY, JSON.stringify(d)); } catch (e) { /* storage blocked */ } }

class Component extends DCLogic {
  constructor(props) {
    super(props);
    this.state = { tab: 'overview', orgs: [], from: 1, to: TODAY, q: '', drawer: null, wlq: '', wlF: 'all', wlSort: 'count',
      cancOrg: null, cancStage: 'all', cancReason: null, slaWin: 'upcoming', slaFocus: null, slaSt: 'all', slaSort: 'count', apv: 'overdue',
      qcF: 'wait', qcChecks: {}, qcDone: {}, dir: loadDir(), waF: 'all', waQ: '', waEdit: null, waDraft: '', waErr: '', imp: null, impMsg: '', prof: null, profQ: '', sent: {}, billMonth: 'nov', billGen: false, faq: 'Prime Bank', navOpen: false,
      menu: null, toast: '', rSt: '', rVer: '', rSort: 'start', rQ: '', apQ: '', tmQ: '', uaUser: '', uQ: '', perms: {}, permUser: '', billTab: 'regular', billOrg: 'Prime', cfTab: 'dash', agSort: 'tasks', rcQ: '' };
  }
  renderVals() {
    const S = this.state, self = this, D = DATA;
    const set = (o) => () => self.setState(o);
    const inO = (o) => !S.orgs.length || S.orgs.includes(o);
    const inD = (d) => d != null && d >= S.from && d <= S.to;
    const open = (kind, id) => () => self.setState({ drawer: { kind, id } });
    const sent = (k) => () => self.setState({ sent: { ...S.sent, [k]: true } });
    const out = { asOf: tTxt(NOW), design: this.props.designName || '', live: !!DATA.live, snap: !DATA.live, liveTxt: DATA.live ? 'Live' : 'Snapshot', refresh: () => { if (window.vrbRefresh) window.vrbRefresh(); }, liveState: (window.vrbState && window.vrbState()) || '' };

    // ---------- navigation ----------
    const TABS = [['overview', 'Dashboard'], ['createfile', 'Create File'], ['reports', 'Reports'], ['appt', 'Appointments'], ['taskmap', 'Task Map'], ['recpv', 'ReCPV'], ['issues', 'Issue Management'], ['sla', 'SLA Breaches'],
      ['analytics', 'Analytics'], ['adminpanel', 'Admin Panel'], ['uanalytics', 'Users Analytics'], ['travel', 'Travel Expenses'], ['zones', 'Zones Manage'], ['documents', 'Documents'], ['company', 'Company Profile'],
      ['route', 'Route Statistics'], ['perms', 'Permissions'], ['requested', 'Requested Trips'], ['billcalc', 'Bill Calculation'], ['register', 'Register'], ['users', 'Users'],
      ['workload', 'Verifier Tasks'], ['wadir', 'Verifier WhatsApp & Photos'], ['cancel', 'Cancellations'], ['profile', 'Verifier Profile'], ['area', 'In / Out Area'], ['faq', 'FAQ']];
    TABS.forEach(([t, l]) => { out['is_' + t] = S.tab === t; out['cls_' + t] = S.tab === t ? 'on' : ''; out['go_' + t] = () => self.setState({ tab: t, drawer: null, navOpen: false, q: '', menu: null, toast: '' }); });
    const GRP = { admin: ['analytics', 'adminpanel', 'uanalytics', 'travel', 'zones', 'documents', 'company', 'route', 'perms', 'requested', 'billcalc', 'register', 'users'], plus: ['workload', 'wadir', 'cancel', 'profile', 'area', 'faq'] };
    out.adminOn = GRP.admin.includes(S.tab) ? 'on' : ''; out.plusOn = GRP.plus.includes(S.tab) ? 'on' : '';
    out.menuAdmin = S.menu === 'admin'; out.menuPlus = S.menu === 'plus';
    out.toggleAdmin = set({ menu: S.menu === 'admin' ? null : 'admin' }); out.togglePlus = set({ menu: S.menu === 'plus' ? null : 'plus' });
    const demo = (msg) => () => self.setState({ toast: msg });
    out.toast = S.toast; out.hasToast = !!S.toast; out.closeToast = set({ toast: '' });
    out.demoSave = demo('Saved in this demo only. In the live build this button calls the same dashboard API.');
    out.demoDl = demo('Download starts in the live build (same file the dashboard gives today).');
    out.tabTitle = (TABS.find((x) => x[0] === S.tab) || TABS[0])[1];

    // ---------- filters: org + date ----------
    out.orgChips = ORG.map((o, i) => ({ short: o, full: D.orgN[i], on: S.orgs.includes(o) ? 'on' : '', pick: () => self.setState({ orgs: S.orgs.includes(o) ? S.orgs.filter((x) => x !== o) : S.orgs.concat([o]) }) }));
    out.allOrgsCls = S.orgs.length ? '' : 'on'; out.allOrgs = set({ orgs: [] });
    const presets = [['Today', TODAY, TODAY], ['Yesterday', Math.max(1, TODAY - 1), Math.max(1, TODAY - 1)], ['Last 7 days', Math.max(1, TODAY - 6), TODAY], ['This month', 1, TODAY]];
    out.presets = presets.map(([l, a, b]) => ({ l, cls: S.from === a && S.to === b ? 'on' : '', pick: set({ from: a, to: b }) }));
    const iso = (d) => YEAR + '-' + String(MONTH).padStart(2, '0') + '-' + String(d).padStart(2, '0');
    out.minIso = iso(1); out.maxIso = iso(TODAY);
    out.fromIso = iso(S.from); out.toIso = iso(S.to);
    const pd = (v) => { const d = parseInt(String(v).slice(8, 10), 10); return d >= 1 && d <= TODAY ? d : null; };
    out.onFrom = (e) => { const d = pd(e.target.value); if (d) self.setState({ from: d, to: Math.max(d, S.to) }); };
    out.onTo = (e) => { const d = pd(e.target.value); if (d) self.setState({ to: d, from: Math.min(d, S.from) }); };
    out.rangeTxt = S.from === S.to ? S.from + ' ' + MON + ' ' + YEAR : S.from + '–' + S.to + ' ' + MON + ' ' + YEAR;
    out.filterTxt = (S.orgs.length ? S.orgs.join(', ') : 'All organizations') + ' · ' + out.rangeTxt;

    // ---------- global search ----------
    out.q = S.q; out.onQ = (e) => self.setState({ q: e.target.value });
    const q = S.q.trim().toLowerCase();
    const hits = q.length >= 3 ? TRIPS.filter((t) => String(t.tid).includes(q) || t.file.toLowerCase().includes(q)).slice(0, 8) : [];
    out.hasHits = hits.length > 0; out.noHits = q.length >= 3 && !hits.length;
    out.hits = hits.map((t) => ({ ...t, stTxt: TST[t.st], stCls: TSC[t.st], pick: () => self.setState({ drawer: { kind: 'trip', id: t.tid }, q: '' }) }));
    out.toggleNav = set({ navOpen: !S.navOpen }); out.clearQ = set({ q: '' }); out.navOpen = S.navOpen;

    // ---------- main dashboard numbers (same columns as verify.bmapsbd.com/dashboard) ----------
    const monthMode = D.dailyMode === 'month';
    out.monthMode = monthMode; out.loading = !!(D.live && D.stage && D.stage < 4); out.loadTxt = (window.vrbState && window.vrbState()) || '';
    const dRows = D.daily.filter((r) => (monthMode || inD(r[0])) && inO(ORG[r[1]]));
    const sumBy = (rows, i) => rows.reduce((a, r) => a + (r[i] || 0), 0);
    const orgAgg = ORG.map((o, oi) => { const rs = dRows.filter((r) => r[1] === oi); return { scFilesN: sumBy(rs, 12), o, oi, n: D.orgN[oi], apps: sumBy(rs, 2), loan: sumBy(rs, 3), card: sumBy(rs, 4), oneGo: sumBy(rs, 5), trips: sumBy(rs, 6), recpv: sumBy(rs, 7), notAcc: sumBy(rs, 8), onProc: sumBy(rs, 9), hold: sumBy(rs, 10), fin: sumBy(rs, 11), scTrips: sumBy(rs, 13), sub: sumBy(rs, 14), partial: sumBy(rs, 15), finFiles: sumBy(rs, 16), cancFiles: sumBy(rs, 17), canc: sumBy(rs, 18), inact: sumBy(rs, 19) }; }).filter((x) => inO(x.o));
    const tot = {}; ['scFilesN', 'apps', 'loan', 'card', 'oneGo', 'trips', 'recpv', 'notAcc', 'onProc', 'hold', 'fin', 'scTrips', 'sub', 'partial', 'finFiles', 'cancFiles', 'canc', 'inact'].forEach((k) => { tot[k] = orgAgg.reduce((a, x) => a + x[k], 0); });
    const row = (x, name) => ({ appPct: pct(x.finFiles + x.sub + x.partial, x.scFilesN) + '%', n: name, apps: fmt(x.apps), loan: fmt(x.loan), card: fmt(x.card), oneGo: fmt(x.oneGo), trips: fmt(x.trips), recpv: fmt(x.recpv), notAcc: fmt(x.notAcc), onProc: fmt(x.onProc), fin: fmt(x.fin), hold: fmt(x.hold), canc: fmt(x.canc), pctTxt: pct(x.fin, x.trips) + '%', w: 'width:' + pct(x.fin, x.trips) + '%' });
    out.mainRows = orgAgg.filter((x) => x.trips || x.apps).sort((a, b) => b.trips - a.trips).map((x) => ({ ...row(x, x.n), pick: () => self.setState({ orgs: [x.o] }) }));
    out.mainAll = row(tot, 'ALL');
    out.goNotAcc = () => self.setState({ tab: 'workload', wlF: 'new', drawer: null }); out.goHold = () => self.setState({ tab: 'workload', wlF: 'hold', drawer: null });
    const slaUp = SLA.upcoming.filter((r) => inO(r.os));
    const qcQueue = FILES.filter((f) => (f.st === 4 || f.st === 7) && inO(f.os) && !S.qcDone[f.i]);
    const apOpen = OPEN.filter((t) => t.ap && inO(t.os));
    const apOver = apOpen.filter((t) => t.ap.at < NOW);
    const stale = OPEN.filter((t) => t.ag && t.ageH >= 72 && inO(t.os));
    out.k = { apps: fmt(tot.apps), loan: fmt(tot.loan), card: fmt(tot.card), trips: fmt(tot.trips), fin: fmt(tot.fin), finPct: pct(tot.fin, tot.trips) + '%', finW: 'width:' + pct(tot.fin, tot.trips) + '%',
      notAcc: fmt(tot.notAcc), onProc: fmt(tot.onProc), hold: fmt(tot.hold), recpv: fmt(tot.recpv), canc: fmt(tot.canc), cancPct: pct(tot.canc, tot.scTrips) + '%', oneGo: fmt(tot.oneGo),
      slaUp: fmt(slaUp.length), qc: fmt(qcQueue.length), apOver: fmt(apOver.length), stale: fmt(stale.length), open: fmt(OPEN.filter((t) => inO(t.os)).length), sub: fmt(tot.sub) };
    const days = []; for (let d = S.from; d <= S.to; d++) days.push(d);
    const trend = days.map((d) => { const rs = dRows.filter((r) => r[0] === d); return { d, t: sumBy(rs, 6), f: sumBy(rs, 11), c: sumBy(rs, 18) }; });
    const maxT = Math.max(1, ...trend.map((x) => x.t));
    out.trend = trend.map((x) => ({ d: x.d, h: 'height:' + Math.max(2, x.t * 100 / maxT) + '%', hf: 'height:' + Math.max(0, x.f * 100 / maxT) + '%', tip: x.d + ' ' + MON + ': ' + fmt(x.t) + ' trips, ' + fmt(x.f) + ' finished, ' + fmt(x.c) + ' canceled' }));
    out.alerts = [
      { n: apOver.length, t: 'appointments are past their time', s: 'Follow up with the verifier today', cls: 'bad', go: out.go_appt },
      { n: slaUp.length, t: 'trips will breach SLA in the next 24 h', s: 'Assign or push them first', cls: 'warn', go: () => self.setState({ tab: 'sla', slaWin: 'upcoming', drawer: null }) },
      { n: stale.length, t: 'On Going / Hold trips have had no update for 3+ days', s: 'Send a WhatsApp reminder', cls: 'bad', go: () => self.setState({ tab: 'workload', wlF: 'stale', drawer: null }) },
      { n: qcQueue.length, t: 'Finished / Partially Submitted files waiting to be submitted', s: 'Check the report and submit', cls: 'acc', go: () => self.setState({ tab: 'reports', rSt: '4', drawer: null }) },
      { n: OPEN.filter((t) => !t.ag && inO(t.os)).length, t: 'Created trips not accepted by any verifier', s: 'Assign a verifier', cls: 'warn', go: () => self.setState({ tab: 'workload', wlF: 'unassigned', drawer: null }) },
    ].filter((a) => a.n > 0).map((a) => ({ ...a, nF: fmt(a.n) }));

    // ---------- verifier tasks ----------
    const wq = S.wlq.trim().toLowerCase();
    const wlTrips = OPEN.filter((t) => inO(t.os) && (S.wlF === 'all' || (S.wlF === 'hold' && t.st === 4) || (S.wlF === 'stale' && t.ageH >= 72) || (S.wlF === 'new' && t.st === 1) || (S.wlF === 'unassigned' && !t.ag) || (S.wlF === 'appt' && t.ap))
      && (!wq || (t.agent + ' ' + t.tid + ' ' + t.file + ' ' + t.area).toLowerCase().includes(wq)));
    const byAg = {}; wlTrips.forEach((t) => { (byAg[t.ag] = byAg[t.ag] || []).push(t); });
    let groups = Object.entries(byAg).map(([ag, ts]) => ({ ag: +ag, ts: ts.sort((a, b) => b.ageH - a.ageH) }));
    groups.sort(S.wlSort === 'count' ? (a, b) => b.ts.length - a.ts.length : (a, b) => b.ts[0].ageH - a.ts[0].ageH);
    groups.sort((a, b) => (a.ag ? 0 : 1) - (b.ag ? 0 : 1));
    out.wlFilters = [['all', 'On Going + Hold'], ['stale', 'No update 3+ days'], ['hold', 'Hold'], ['new', 'Created (not accepted)'], ['appt', 'Has appointment'], ['unassigned', 'Not assigned']]
      .map(([k, l]) => ({ l, cls: S.wlF === k ? 'on' : '', pick: set({ wlF: k }) }));
    out.wlq = S.wlq; out.onWlq = (e) => self.setState({ wlq: e.target.value });
    out.sortCount = set({ wlSort: 'count' }); out.sortAge = set({ wlSort: 'age' });
    out.sortCountCls = S.wlSort === 'count' ? 'on' : ''; out.sortAgeCls = S.wlSort === 'age' ? 'on' : '';
    out.wlCount = fmt(wlTrips.length); out.wlPeople = fmt(groups.filter((g) => g.ag).length);
    out.wl = groups.slice(0, 60).map(({ ag, ts }) => {
      const by = (s) => ts.filter((t) => t.st === s).length, n = ts.length, v = VER[ag];
      const name = ag ? (v ? v.a : 'Verifier ' + ag) : 'Not assigned';
      return { ag, a: name, ini: ag ? ini(name) : '?', n, nF: fmt(n), orgsTxt: [...new Set(ts.map((t) => t.os))].join(' · '), home: v && v.home ? v.home : '',
        alloc: by(2), started: by(3), hold: by(4), fresh: by(1),
        wAlloc: 'width:' + by(2) * 100 / n + '%', wStart: 'width:' + by(3) * 100 / n + '%', wHold: 'width:' + by(4) * 100 / n + '%', wNew: 'width:' + by(1) * 100 / n + '%',
        oldTxt: 'oldest update ' + ago(ts[0].ageH), oldCls: ageCls(ts[0].ageH),
        chips: ts.slice(0, 14).map((t) => ({ tid: t.tid, cls: TSC[t.st] + ' ' + ageCls(t.ageH), tip: t.os + ' · ' + t.tl + ' · ' + TST[t.st] + ' · updated ' + ago(t.ageH), pick: open('trip', t.tid) })),
        more: n > 14 ? '+' + (n - 14) + ' more' : '',
        pick: open('ver', ag), wa: waMsg(name, ts), canRemind: !!ag, sentTxt: S.sent['v' + ag] ? 'Reminder opened ✓' : '', onSend: sent('v' + ag) };
    });
    const nowMin = NOW % 1440;
    const rounds = [[480, '08:00', 'Today\'s appointments'], [600, '10:00', 'All On Going + Hold'], [780, '13:00', 'On Going + Hold + bank statement'], [900, '15:00', 'Appointments not done yet'], [1050, '17:30', 'On Going + Hold + bank statement']];
    const nextI = rounds.findIndex((r) => r[0] > nowMin);
    out.rounds = rounds.map((r, i) => ({ t: r[1], w: r[2], cls: r[0] <= nowMin ? 'done' : i === nextI ? 'next' : '' }));
    out.nextRound = nextI >= 0 ? 'Next round ' + rounds[nextI][1] + ' today' : 'All 5 rounds done today · next 08:00 tomorrow';

    // ---------- cancellations ----------
    const cAll = TRIPS.filter((t) => t.st === 6 && inO(t.os) && inD(t.day));
    out.cancOrgs = orgAgg.filter((x) => x.canc > 0 || cAll.some((t) => t.os === x.o)).map((x) => {
      const ts = cAll.filter((t) => t.os === x.o), st = ts.filter((t) => t.start).length, nr = ts.filter((t) => !t.rem).length;
      const ty = {}; ts.forEach((t) => { ty[t.tl] = (ty[t.tl] || 0) + 1; }); const topTy = Object.entries(ty).sort((a, b) => b[1] - a[1])[0];
      return { o: x.o, n: x.n, canc: x.canc, cF: fmt(x.canc), p: pct(x.canc, x.scTrips), pTxt: pct(x.canc, x.scTrips) + '%', listed: ts.length, started: st, before: ts.length - st, noRem: pct(nr, ts.length) + '%',
        topTy: topTy ? topTy[0] + ' (' + topTy[1] + ')' : '—', cls: S.cancOrg === x.o ? 'sel' : '', w: 'width:' + Math.max(2, pct(x.canc, x.scTrips) * 4) + '%',
        pick: () => self.setState({ cancOrg: S.cancOrg === x.o ? null : x.o }) };
    }).sort((a, b) => b.canc - a.canc);
    let cl = cAll.filter((t) => (!S.cancOrg || t.os === S.cancOrg) && (S.cancStage === 'all' || (S.cancStage === 'started' ? t.start : !t.start)) && (!S.cancReason || reason(t.rem) === S.cancReason));
    const cBase = cAll.filter((t) => !S.cancOrg || t.os === S.cancOrg);
    const cStarted = cBase.filter((t) => t.start).length;
    out.cStages = [['all', 'All', cBase.length], ['started', 'After visit started', cStarted], ['before', 'Before start', cBase.length - cStarted]].map(([k, l, n]) => ({ l, nF: fmt(n), cls: S.cancStage === k ? 'on' : '', pick: set({ cancStage: k }) }));
    const rs = {}; cBase.forEach((t) => { const r = reason(t.rem); rs[r] = (rs[r] || 0) + 1; });
    out.cReasons = Object.entries(rs).sort((a, b) => b[1] - a[1]).map(([r, n]) => ({ r, nF: fmt(n), p: pct(n, cBase.length) + '%', w: 'width:' + Math.max(2, n * 100 / Math.max(1, cBase.length)) + '%', cls: S.cancReason === r ? 'sel' : '', pick: () => self.setState({ cancReason: S.cancReason === r ? null : r }) }));
    const cty = {}; cBase.forEach((t) => { cty[t.tl] = (cty[t.tl] || 0) + 1; });
    out.cTypes = bars(Object.entries(cty).sort((a, b) => b[1] - a[1]), 8);
    const cag = {}; cBase.forEach((t) => { cag[t.agent] = (cag[t.agent] || 0) + 1; });
    out.cAgents = bars(Object.entries(cag).sort((a, b) => b[1] - a[1]), 8);
    const cd = days.map((d) => ({ d, n: cBase.filter((t) => t.day === d).length })), maxCd = Math.max(1, ...cd.map((x) => x.n));
    out.cDaily = cd.map((x) => ({ d: x.d, h: 'height:' + Math.max(2, x.n * 100 / maxCd) + '%', tip: x.d + ' ' + MON + ': ' + x.n + ' canceled' }));
    out.cList = cl.sort((a, b) => b.cr - a.cr).slice(0, 80).map((t) => ({ ...t, crTxt: tTxt(t.cr), stage: t.start ? 'After start (' + hTxt(t.start) + ')' : 'Before start', stageCls: t.start ? 'warn' : '', why: reason(t.rem), remTxt: t.rem || '—', pick: open('trip', t.tid) }));
    out.cListN = fmt(cl.length);
    out.k.cListed = fmt(cAll.length); out.k.cStarted = fmt(cAll.filter((t) => t.start).length); out.k.cStartedPct = pct(cAll.filter((t) => t.start).length, cAll.length) + '%';
    out.k.cNoRem = pct(cAll.filter((t) => !t.rem).length, cAll.length) + '%'; out.k.cancFiles = fmt(tot.cancFiles);
    out.cancSel = !!S.cancOrg; out.cancOrgName = S.cancOrg || ''; out.clearCanc = set({ cancOrg: null, cancReason: null, cancStage: 'all' });
    const so = out.cancOrgs.find((x) => x.o === S.cancOrg);
    out.cancStory = so ? so.n + ': ' + so.cF + ' trips canceled (' + so.pTxt + ' of its trips). In the list, ' + so.started + ' were canceled after the verifier started the visit and ' + so.before + ' before anyone started. ' + so.noRem + ' have no reason written.' : '';

    // ---------- SLA ----------
    const wins = [['upcoming', 'Next 24 h (at risk)'], ['today', 'Today'], ['last7', 'Last 7 days'], ['all', 'All breached']];
    out.slaWins = wins.map(([k, l]) => ({ l, nF: fmt(SLA[k].filter((r) => inO(r.os)).length), cls: S.slaWin === k ? 'on' : '', pick: set({ slaWin: k, slaFocus: null }) }));
    const up = S.slaWin === 'upcoming';
    let sl = SLA[S.slaWin].filter((r) => inO(r.os) && (S.slaWin !== 'all' || inD(dayOf(r.sla))));
    const sBase = sl;
    if (S.slaFocus) sl = sl.filter((r) => r[S.slaFocus.k] === S.slaFocus.v);
    out.slaFocusTxt = S.slaFocus ? 'Showing ' + S.slaFocus.v : ''; out.hasSlaFocus = !!S.slaFocus; out.clearSla = set({ slaFocus: null });
    const foc = (k) => (v) => self.setState({ slaFocus: S.slaFocus && S.slaFocus.v === v ? null : { k, v } });
    const cnt = (arr, k) => { const m = {}; arr.forEach((r) => { m[r[k]] = (m[r[k]] || 0) + 1; }); return Object.entries(m).sort((a, b) => b[1] - a[1]); };
    out.slaOrg = bars(cnt(sBase, 'os'), 8, foc('os')); out.slaAgent = bars(cnt(sBase, 'agent'), 10, foc('agent')); out.slaArea = bars(cnt(sBase, 'area'), 10, foc('area'));
    const unas = sBase.filter((r) => r.agent === 'Unassigned').length;
    out.sk = { total: fmt(sBase.length), unas: fmt(unas), unasP: pct(unas, sBase.length) + '% of this window', as: fmt(sBase.length - unas), agents: fmt(new Set(sBase.map((r) => r.agent)).size - (unas ? 1 : 0)) + ' verifiers handling',
      areas: fmt(new Set(sBase.map((r) => r.area)).size), topArea: (cnt(sBase, 'area')[0] || ['—', 0]).join(' · '), inN: fmt(sBase.filter((r) => r.st === 'In').length), outN: fmt(sBase.filter((r) => r.st === 'Out').length),
      bad: fmt(sBase.filter((r) => r.sla < r.cr).length) };
    out.slaUp = up; out.slaHead = up ? 'Time left' : 'Late by';
    out.slaList = sl.slice().sort((a, b) => b.h - a.h).slice(0, 120).map((r) => {
      const hh = Math.abs(r.h), txt = hh >= 48 ? Math.round(hh / 24) + ' days' : hh + ' h';
      return { ...r, dur: up ? (r.h <= 0 ? txt + ' left' : 'due now') : txt, sev: up ? (Math.abs(r.h) <= 6 ? 'sev3' : 'sev2') : r.h >= 72 ? 'sev3' : r.h >= 24 ? 'sev2' : 'sev1',
        crTxt: tTxt(r.cr), slaTxt: tTxt(r.sla), flag: r.sla < r.cr ? 'SLA date before created' : '', pick: open('trip', r.tid) };
    });
    out.slaShown = fmt(sl.length);
    out.slaStF = [['all', 'All'], ['In', 'In station'], ['Out', 'Out station']].map(([k, l]) => ({ l, cls: S.slaSt === k ? 'on' : '', pick: set({ slaSt: k }) }));
    out.slaSortCount = set({ slaSort: 'count' }); out.slaSortUrg = set({ slaSort: 'urgent' });
    out.slaSortCountCls = S.slaSort === 'count' ? 'on' : ''; out.slaSortUrgCls = S.slaSort === 'urgent' ? 'on' : '';
    const sev = (r) => up ? (Math.abs(r.h) <= 16 ? 3 : Math.abs(r.h) <= 20 ? 2 : 1) : (r.h >= 72 ? 3 : r.h >= 24 ? 2 : 1);
    const sc = sl.filter((r) => S.slaSt === 'all' || r.st === S.slaSt);
    const byA = {}; sc.forEach((r) => { (byA[r.agent] = byA[r.agent] || []).push(r); });
    let sg = Object.entries(byA).map(([a, rs]) => ({ a, rs: rs.sort((x, y) => (up ? y.h - x.h : y.h - x.h)) }));
    const urg = (g) => g.rs.filter((r) => sev(r) === 3).length;
    sg.sort(S.slaSort === 'count' ? (x, y) => y.rs.length - x.rs.length : (x, y) => urg(y) - urg(x) || y.rs.length - x.rs.length);
    sg.sort((x, y) => (x.a === 'Unassigned' ? 1 : 0) - (y.a === 'Unassigned' ? 1 : 0));
    out.slaLabels = up ? ['16 h or less left', '16–20 h left', '20–24 h left'] : ['3+ days late', '1–3 days late', 'under 1 day late'];
    out.slaCardsN = fmt(sg.filter((g) => g.a !== 'Unassigned').length);
    out.slaCards = sg.slice(0, 60).map((g) => {
      const n = g.rs.length, c3 = g.rs.filter((r) => sev(r) === 3).length, c2 = g.rs.filter((r) => sev(r) === 2).length, c1 = n - c3 - c2;
      const areas = {}; g.rs.forEach((r) => { areas[r.area] = (areas[r.area] || 0) + 1; });
      const un = g.a === 'Unassigned';
      return { a: un ? 'Not assigned yet' : g.a, ini: un ? '?' : ini(g.a), n, nF: fmt(n), un, notUn: !un,
        sub: [...new Set(g.rs.map((r) => r.os))].join(' · ') + ' · ' + Object.entries(areas).sort((x, y) => y[1] - x[1]).slice(0, 2).map((x) => x[0]).join(', '),
        c3, c2, c1, w3: 'width:' + c3 * 100 / n + '%', w2: 'width:' + c2 * 100 / n + '%', w1: 'width:' + c1 * 100 / n + '%',
        first: up ? 'first one due in ' + Math.abs(g.rs[0].h) + ' h' : 'worst: ' + (g.rs[0].h >= 48 ? Math.round(g.rs[0].h / 24) + ' days' : g.rs[0].h + ' h') + ' late',
        chips: g.rs.slice(0, 14).map((r) => ({ tid: r.tid, cls: 'sv' + sev(r), tip: r.os + ' · ' + r.area + ' · ' + r.st + ' · SLA ' + tTxt(r.sla), pick: open('trip', r.tid) })),
        more: n > 14 ? '+' + (n - 14) + ' more' : '', pick: open('slav', g.a),
        wa: waSla(g.a, g.rs, up), onSend: sent('s' + g.a), sentTxt: S.sent['s' + g.a] ? 'Reminder opened ✓' : '' };
    });

    // ---------- appointments ----------
    const apToday = apOpen.filter((t) => t.ap.at >= NOW && dayOf(t.ap.at) === dayOf(NOW)), apLater = apOpen.filter((t) => dayOf(t.ap.at) > dayOf(NOW));
    out.apTabs = [['overdue', 'Time passed', apOver.length], ['today', 'Later today', apToday.length], ['upcoming', 'Upcoming days', apLater.length], ['all', 'All', apOpen.length]].map(([k, l, n]) => ({ l, nF: fmt(n), cls: S.apv === k ? 'on' : '', pick: set({ apv: k }) }));
    const aq = S.apQ.trim().toLowerCase();
    out.apQ = S.apQ; out.onApQ = (e) => self.setState({ apQ: e.target.value });
    const apv = (S.apv === 'overdue' ? apOver : S.apv === 'today' ? apToday : S.apv === 'all' ? apOpen : apLater).filter((t) => inD(dayOf(t.ap.at)) || S.apv !== 'all').filter((t) => !aq || (t.tid + ' ' + t.file).toLowerCase().includes(aq));
    out.apList = apv.slice().sort((a, b) => a.ap.at - b.ap.at).slice(0, 80).map((t) => ({ ...t, time: hTxt(t.ap.at), date: tTxt(t.ap.at).split(',')[0], kind: t.ap.kind, why: t.ap.why || '—', late: t.ap.at < NOW ? ago((NOW - t.ap.at) / 60).replace(' ago', ' late') : '', cls: t.ap.at < NOW ? 'overdue' : 'today', stTxt: TST[t.st], stCls: TSC[t.st], pick: open('trip', t.tid), wa: waMsg(t.agent, [t]), onSend: sent('t' + t.tid), sentTxt: S.sent['t' + t.tid] ? 'Sent ✓' : '' }));
    const apAg = {}; apOver.forEach((t) => { apAg[t.agent] = (apAg[t.agent] || 0) + 1; });
    out.apAgents = bars(Object.entries(apAg).sort((a, b) => b[1] - a[1]), 8);

    // ---------- reports QC ----------
    const qcAll = FILES.filter((f) => (f.st === 4 || f.st === 7) && inO(f.os) && inD(f.day));
    const qcW = qcAll.filter((f) => !S.qcDone[f.i]), qcDoneL = qcAll.filter((f) => S.qcDone[f.i]);
    out.qcTabs = [['wait', 'Waiting for QC', qcW.length], ['done', 'Done in this session', qcDoneL.length]].map(([k, l, n]) => ({ l, nF: fmt(n), cls: S.qcF === k ? 'on' : '', pick: set({ qcF: k }) }));
    out.qcPipe = [['Finished, waiting QC', tot.finFiles, 'acc'], ['Partially submitted', tot.partial, 'warn'], ['Submitted to bank', tot.sub, 'good'], ['Canceled files', tot.cancFiles, 'bad']].map(([l, n, c]) => ({ l, nF: fmt(n), cls: c }));
    out.qcList = (S.qcF === 'wait' ? qcW : qcDoneL).sort((a, b) => (a.sla || 0) - (b.sla || 0)).slice(0, 80).map((f) => {
      const fin = f.trips.filter((t) => t.st === 5).length + f.finN, all = f.trips.length + f.finN;
      const late = f.sla && f.sla < NOW;
      return { ...f, stTxt: FST[f.st], stCls: f.st === 7 ? 'warn' : 'acc', tripsTxt: fin + ' / ' + all + ' finished', attTxt: f.attach ? 'Complete' : 'Missing', attCls: f.attach ? 'good' : 'bad',
        startTxt: tTxt(f.start), slaTxt: tTxt(f.sla), slaCls: late ? 'bad-t' : '', endTxt: tTxt(f.end), wait: f.end ? ago((NOW - f.end) / 60).replace(' ago', '') : '—',
        doneTxt: S.qcDone[f.i] === 'sub' ? 'Submitted' : S.qcDone[f.i] === 'back' ? 'Sent back' : '', pick: open('file', f.i) };
    });

    // ---------- re-cpv ----------
    const rc = TRIPS.filter((t) => t.recpv && inO(t.os) && inD(t.day));
    out.rcN = fmt(tot.recpv); out.rcListed = fmt(rc.length);
    out.rcList = rc.sort((a, b) => b.cr - a.cr).slice(0, 60).map((t) => ({ ...t, crTxt: tTxt(t.cr), stTxt: TST[t.st], stCls: TSC[t.st], pick: open('trip', t.tid) }));
    const rco = {}; rc.forEach((t) => { rco[t.os] = (rco[t.os] || 0) + 1; }); out.rcOrgs = bars(Object.entries(rco).sort((a, b) => b[1] - a[1]), 8);
    const rct = {}; rc.forEach((t) => { rct[t.tl] = (rct[t.tl] || 0) + 1; }); out.rcTypes = bars(Object.entries(rct).sort((a, b) => b[1] - a[1]), 8);

    // ---------- verifier profile ----------
    const pq = S.profQ.trim().toLowerCase();
    const pl = DATA.ver.filter((v) => !pq || (v.a + ' ' + v.home + ' ' + v.sup.join(' ')).toLowerCase().includes(pq)).slice().sort((a, b) => b.tasks - a.tasks);
    const pSel = VER[S.prof] || pl[0] || DATA.ver[0];
    out.profQ = S.profQ; out.onProfQ = (e) => self.setState({ profQ: e.target.value });
    out.profList = pl.slice(0, 60).map((v) => ({ a: v.a, ini: ini(v.a), sub: v.home || '—', n: fmt(OPEN.filter((t) => t.ag === v.id).length), cls: v.id === pSel.id ? 'on' : '', pick: set({ prof: v.id }) }));
    const pOpen = OPEN.filter((t) => t.ag === pSel.id).sort((a, b) => b.ageH - a.ageH);
    const pdl = pSel.dl.filter((d) => inD(d[0])), maxPd = Math.max(1, ...pdl.map((d) => d[4]));
    const pslaN = SLA.all.filter((r) => r.agent === pSel.a).length;
    out.p = { a: pSel.a, ini: ini(pSel.a), ph: '+880 1••• •••' + (pSel.ph || '???'), phOk: !!pSel.phOk, phBad: !pSel.phOk, seen: ago((NOW - pSel.seen) / 60), home: pSel.home || 'Not enough data yet',
      orgs: pSel.orgs.join(' · ') || '—', days: pdl.length, tasks: fmt(pdl.reduce((a, d) => a + d[4], 0)), fin: fmt(pdl.reduce((a, d) => a + d[3], 0)),
      finRate: pct(pdl.reduce((a, d) => a + d[3], 0), pdl.reduce((a, d) => a + d[4], 0)) + '%', avgFirst: pSel.avgFirst, avgLast: pSel.avgLast, late: pSel.late,
      pend: pOpen.length, stale: pOpen.filter((t) => t.ageH >= 72).length, sla: pslaN, canc: TRIPS.filter((t) => t.st === 6 && t.ag === pSel.id).length,
      wa: waMsg(pSel.a, pOpen), hasOpen: pOpen.length > 0, onSend: sent('v' + pSel.id), sentTxt: S.sent['v' + pSel.id] ? 'Reminder opened ✓' : '' };
    out.pSup = pSel.sup.length ? pSel.sup.map((s) => ({ s })) : [{ s: 'No support area recorded' }];
    out.pDays = pdl.map((d) => ({ dd: d[0], h: 'height:' + Math.max(3, d[4] * 100 / maxPd) + '%', hf: 'height:' + (d[3] * 100 / maxPd) + '%', tip: d[0] + ' ' + MON + ': first task ' + (d[1] || '—') + ', last ' + (d[2] || '—') + ', ' + d[3] + '/' + d[4] + ' finished', lateCls: d[1] && d[1] > '10:30' ? 'late' : '' }));
    out.pAtt = pdl.slice().reverse().slice(0, 10).map((d) => ({ d: d[0] + ' ' + MON, first: d[1] || '—', last: d[2] || '—', ft: d[3] + ' / ' + d[4], cls: d[1] && d[1] > '10:30' ? 'warn-t' : '' }));
    out.pOpen = pOpen.slice(0, 30).map((t) => ({ ...t, stTxt: TST[t.st], stCls: TSC[t.st], updTxt: ago(t.ageH), ageCls: ageCls(t.ageH), pick: open('trip', t.tid) }));

    // ---------- in / out area ----------
    const areaM = {};
    OPEN.filter((t) => inO(t.os)).forEach((t) => { const a = areaM[t.area] = areaM[t.area] || { n: t.area, open: 0, sla: 0, st: t.station, v: new Set(), o: new Set() }; a.open++; if (t.ag) a.v.add(t.agent); a.o.add(t.os); });
    SLA.all.concat(SLA.upcoming).filter((r) => inO(r.os)).forEach((r) => { const a = areaM[r.area] = areaM[r.area] || { n: r.area, open: 0, sla: 0, st: r.st, v: new Set(), o: new Set() }; a.sla++; a.st = r.st; a.o.add(r.os); });
    const areas = Object.values(areaM).filter((a) => a.n !== '—').sort((a, b) => b.open + b.sla - a.open - a.sla);
    const amap = (a) => ({ n: a.n, open: a.open, sla: a.sla, vers: [...a.v].slice(0, 3).join(', ') || '—', orgs: [...a.o].join(' · ') });
    out.areaIn = areas.filter((a) => a.st === 'In').slice(0, 14).map(amap); out.areaOut = areas.filter((a) => a.st !== 'In').slice(0, 14).map(amap);

    // ---------- billing + faq ----------
    out.bill = D.bill[S.billMonth]; out.billGen = S.billGen; out.genBill = set({ billGen: true });
    out.bmOct = set({ billMonth: 'oct', billGen: false }); out.bmNov = set({ billMonth: 'nov', billGen: false });
    out.bmOctCls = S.billMonth === 'oct' ? 'on' : ''; out.bmNovCls = S.billMonth === 'nov' ? 'on' : '';
    out.faqOrgs = D.faq.map((f) => ({ n: f.org, cls: f.org === S.faq ? 'on' : '', pick: set({ faq: f.org }) }));
    out.faqItems = (D.faq.find((f) => f.org === S.faq) || D.faq[0]).items;

    // ---------- shared select options ----------
    out.verOpts = [{ v: '', l: 'Select Verifier' }].concat(DATA.ver.slice().sort((a, b) => a.a.localeCompare(b.a)).map((v) => ({ v: String(v.id), l: v.a })));
    out.orgOpts = [{ v: '', l: 'Select Org' }].concat(ORG.map((o, i) => ({ v: o, l: D.orgN[i] })));

    // ---------- Reports (with QC + submit) ----------
    out.rStOpts = [{ v: '', l: 'Select Status' }].concat([1, 2, 3, 4, 5, 6, 7, 8].map((k) => ({ v: String(k), l: FST[k] })));
    out.rSortOpts = [['start', 'Start Date'], ['end', 'End Date'], ['status', 'Status'], ['sla', 'SLA']].map(([v, l]) => ({ v, l: 'Sort By: ' + l }));
    out.rSt = S.rSt; out.rVer = S.rVer; out.rSort = S.rSort; out.rQ = S.rQ;
    out.onRSt = (e) => self.setState({ rSt: e.target.value }); out.onRVer = (e) => self.setState({ rVer: e.target.value });
    out.onRSort = (e) => self.setState({ rSort: e.target.value }); out.onRQ = (e) => self.setState({ rQ: e.target.value });
    const rq = S.rQ.trim().toLowerCase();
    const fStatus = (f) => S.qcDone[f.i] === 'sub' ? 6 : f.st;
    let rf = FILES.filter((f) => inO(f.os) && inD(f.day) && (!S.rSt || String(fStatus(f)) === S.rSt) && (!S.rVer || f.trips.some((t) => String(t.ag) === S.rVer)) && (!rq || (f.file + ' ' + f.trips.map((t) => t.tid).join(' ')).toLowerCase().includes(rq)));
    const rsk = { start: (f) => -(f.start || 0), end: (f) => -(f.end || 0), status: (f) => fStatus(f), sla: (f) => f.sla || 0 }[S.rSort] || ((f) => -(f.start || 0));
    rf = rf.slice().sort((a, b) => rsk(a) - rsk(b));
    const stCount = (k) => FILES.filter((f) => inO(f.os) && inD(f.day) && fStatus(f) === k).length;
    out.rChips = [1, 2, 3, 4, 7, 5, 8].map((k) => ({ l: FST[k], nF: fmt(stCount(k)), cls: S.rSt === String(k) ? 'on' : '', pick: set({ rSt: S.rSt === String(k) ? '' : String(k) }) }))
      .concat([{ l: 'Submitted', nF: fmt(tot.sub), cls: S.rSt === '6' ? 'on' : '', pick: set({ rSt: S.rSt === '6' ? '' : '6' }) }]);
    out.rN = fmt(rf.length); out.rSubNote = S.rSt === '6';
    out.rList = rf.slice(0, 100).map((f, i) => {
      const st = fStatus(f), late = f.sla && f.sla < NOW && [1, 2, 3].includes(st);
      return { sl: i + 1, file: f.file, os: D.orgN[f.o], stTxt: FST[st], stCls: FSC[st], attTxt: f.attach ? 'Uploaded' : 'Pending', attCls: f.attach ? 'good' : 'warn',
        tids: f.trips.slice(0, 6).map((t) => ({ tid: t.tid, cls: TSC[t.st], pick: open('trip', t.tid) })), moreT: f.trips.length > 6 ? '+' + (f.trips.length - 6) : '',
        startTxt: tTxt(f.start), slaTxt: tTxt(f.sla), slaCls: late ? 'bad-t' : 'good-t', endTxt: f.end ? tTxt(f.end) : 'N/A',
        view: open('file', f.i), dl: demo('Report download for ' + f.file + ' starts in the live build.'), hasBank: f.trips.some((t) => t.tl === 'Bank (BS)'), bank: demo('Bank top-sheet for ' + f.file + ' downloads in the live build.'),
        canSubmit: st === 4 || st === 7, submitted: st === 6, check: open('file', f.i) };
    });
    out.dlSla = demo('SLA report downloads in the live build.'); out.dlTrip = demo('Trip Status report downloads in the live build.'); out.dlExec = demo('Executive report downloads in the live build.');

    // ---------- Task Map (verifier list; map tiles load in the live build) ----------
    out.tmQ = S.tmQ; out.onTmQ = (e) => self.setState({ tmQ: e.target.value });
    const tq = S.tmQ.trim().toLowerCase();
    out.tmList = DATA.ver.filter((v) => !tq || (v.a + ' ' + v.home).toLowerCase().includes(tq)).map((v) => ({ v, h: (NOW - v.seen) / 60, n: OPEN.filter((t) => t.ag === v.id).length }))
      .sort((a, b) => a.h - b.h).slice(0, 60).map(({ v, h, n }) => ({ a: v.a, ini: ini(v.a), home: v.home || '—', seen: ago(h), cls: (ACT[v.act] || ['', 'act0'])[1], actTxt: (ACT[v.act] || ['—'])[0], n, pick: open('ver', v.id) }));
    out.tmActive = fmt(DATA.ver.filter((v) => v.act === 1).length); out.tmToday = fmt(DATA.ver.filter((v) => (NOW - v.seen) / 60 < 24).length);
    out.tmLegend = [1, 2, 3, 4, 5].map((k) => ({ l: ACT[k][0], cls: ACT[k][1], n: DATA.ver.filter((v) => v.act === k).length }));

    // ---------- ReCPV tracks ----------
    out.rcQ = S.rcQ; out.onRcQ = (e) => self.setState({ rcQ: e.target.value });
    const rcq = S.rcQ.trim().toLowerCase();
    out.rcTracks = (D.recpvOld || []).filter((r) => (r.os === '—' || inO(r.os)) && (!rcq || r.file.toLowerCase().includes(rcq))).map((r) => ({ ...r, bill: r.bill || 'Regular' }));
    out.rcFind = rcq.length >= 4 ? FILES.filter((f) => f.file.toLowerCase().includes(rcq)).slice(0, 3).map((f) => ({ file: f.file, os: f.os, trips: f.trips.map((t) => ({ tid: t.tid, tl: t.tl, st: TST[t.st] })) })) : [];
    out.rcHasFind = out.rcFind.length > 0;

    // ---------- Analytics ----------
    const runApps = Math.max(0, tot.scFilesN - tot.sub - tot.partial - tot.finFiles - tot.cancFiles);
    out.an = { total: fmt(tot.apps), running: fmt(runApps), finished: fmt(tot.finFiles + tot.sub + tot.partial), loan: fmt(tot.loan), card: fmt(tot.card), oneGo: fmt(tot.oneGo), finPct: pct(tot.finFiles + tot.sub + tot.partial, tot.scFilesN) + '%',
      trips: fmt(tot.trips), runTrips: fmt(tot.onProc + tot.hold), notAcc: fmt(tot.notAcc), finTrips: fmt(tot.fin) };
    out.anOrgs = orgAgg.filter((x) => x.scFilesN || x.trips).map((x) => ({ n: x.n, files: fmt(x.scFilesN), trips: fmt(x.scTrips) }));
    out.anTypes = D.types1 || [];
    const agS = DATA.ver.map((v) => { const dl = v.dl.filter((d) => inD(d[0])); return { a: v.a, id: v.id, tasks: dl.reduce((x, d) => x + d[4], 0), fin: dl.reduce((x, d) => x + d[3], 0) }; }).filter((x) => x.tasks);
    agS.sort(S.agSort === 'fin' ? (a, b) => b.fin - a.fin : (a, b) => b.tasks - a.tasks);
    const agMax = Math.max(1, ...agS.map((x) => (S.agSort === 'fin' ? x.fin : x.tasks)));
    out.agStats = agS.slice(0, 15).map((x) => ({ ...x, v: S.agSort === 'fin' ? x.fin : x.tasks, w: 'width:' + (S.agSort === 'fin' ? x.fin : x.tasks) * 100 / agMax + '%', pick: set({ tab: 'profile', prof: x.id }) }));
    out.agAlloc = set({ agSort: 'tasks' }); out.agFin = set({ agSort: 'fin' }); out.agIssues = demo('Raised issues count comes from Issue Management in the live build.');
    out.agAllocCls = S.agSort === 'tasks' ? 'on' : ''; out.agFinCls = S.agSort === 'fin' ? 'on' : '';

    // ---------- Users Analytics ----------
    out.uaUser = S.uaUser; out.onUaUser = (e) => self.setState({ uaUser: e.target.value });
    const uaRows = []; DATA.ver.filter((v) => !S.uaUser || String(v.id) === S.uaUser).forEach((v) => v.dl.filter((d) => inD(d[0])).forEach((d) => uaRows.push({ d: d[0], a: v.a, first: d[1] || '—', last: d[2] || '—', fin: d[3], tasks: d[4] })));
    uaRows.sort((a, b) => b.d - a.d || b.tasks - a.tasks);
    out.uaRows = uaRows.slice(0, 120).map((r) => ({ ...r, dTxt: r.d + ' ' + MON + ' ' + YEAR, cls: r.first !== '—' && r.first > '10:30' ? 'warn-t' : '' }));
    out.uaN = fmt(uaRows.length);
    out.uaCsv = demo('CSV export downloads in the live build.'); out.uaCopy = demo('Table copied (live build).');

    // ---------- Permissions ----------
    out.permUser = S.permUser; out.onPermUser = (e) => self.setState({ permUser: e.target.value });
    out.hasPermUser = !!S.permUser;
    const pk = S.perms[S.permUser] || {};
    out.permList = TABS.map(([k, l]) => ({ l, on: !!pk[k], cls: pk[k] ? 'on' : '', toggle: () => self.setState({ perms: { ...S.perms, [S.permUser]: { ...pk, [k]: !pk[k] } } }) }));

    // ---------- Bill Calculation (VRB rules) ----------
    out.billOrg = S.billOrg; out.onBillOrg = (e) => self.setState({ billOrg: e.target.value, billGen: false });
    out.isPrime = S.billOrg === 'Prime'; out.notPrime = S.billOrg !== 'Prime';
    out.btReg = set({ billTab: 'regular' }); out.btRc = set({ billTab: 'recpv' });
    out.btRegCls = S.billTab === 'regular' ? 'on' : ''; out.btRcCls = S.billTab === 'recpv' ? 'on' : '';
    out.isBtReg = S.billTab === 'regular'; out.isBtRc = S.billTab === 'recpv';

    // ---------- Users ----------
    out.uQ = S.uQ; out.onUQ = (e) => self.setState({ uQ: e.target.value });
    const uq = S.uQ.trim().toLowerCase();
    out.userList = DATA.ver.filter((v) => !uq || v.a.toLowerCase().includes(uq)).sort((a, b) => a.a.localeCompare(b.a)).slice(0, 80).map((v, i) => ({ sl: i + 1, a: v.a, mail: 'hidden in demo', type: 'Agent', pick: set({ tab: 'profile', prof: v.id }) }));
    out.userN = fmt(DATA.ver.length);

    // ---------- Create File ----------
    out.cfTabs = [['bulk', 'Bulk Upload'], ['dash', 'Create From Dashboard'], ['ocr', 'OCR']].map(([k, l]) => ({ l, cls: S.cfTab === k ? 'on' : '', pick: set({ cfTab: k }) }));
    out.cfBulk = S.cfTab === 'bulk'; out.cfDash = S.cfTab === 'dash'; out.cfOcr = S.cfTab === 'ocr';

    // ---------- Verifier WhatsApp & Photos (directory) ----------
    const DIR = S.dir || {};
    const setDir = (id, patch) => { const nd = { ...DIR, [id]: { ...(DIR[id] || {}), ...patch, at: Date.now() } }; if (patch.noWa) nd[id].wa = 'no'; if (patch.num) nd[id].wa = 'unchecked'; saveDir(nd); if (window.vrbDirSync) window.vrbDirSync(id, patch); self.setState({ dir: nd }); };
    const waOf = (v) => { const d = DIR[v.id] || {}; const num = d.num || ''; const st = d.wa ? ({ ok: 'ok', no: 'nowa', unchecked: 'unchecked', bad: 'bad', none: 'none' }[d.wa] || 'unchecked') : d.noWa ? 'nowa' : num ? (isBd(num) ? 'unchecked' : 'bad') : (v.phOk ? 'unchecked' : 'none'); return { d, num, st }; };
    const WST = { ok: ['WhatsApp connected', 'good'], unchecked: ['Not checked yet', 'warn'], nowa: ['Not on WhatsApp', 'bad'], bad: ['Number not valid', 'bad'], none: ['No number', 'bad'] };
    const waq = S.waQ.trim().toLowerCase();
    const allV = DATA.ver.map((v) => ({ v, ...waOf(v) }));
    const cntSt = (f) => allV.filter(f).length;
    out.waK = { total: fmt(allV.length), ok: fmt(cntSt((x) => x.st === 'ok')), dash: fmt(cntSt((x) => x.st === 'unchecked')), missing: fmt(cntSt((x) => ['nowa', 'bad', 'none'].includes(x.st))), noPhoto: fmt(cntSt((x) => !x.d.photo)) };
    out.waFilters = [['all', 'All verifiers'], ['missing', 'No WhatsApp'], ['dash', 'Not checked yet'], ['ok', 'WhatsApp connected'], ['nophoto', 'No photo']].map(([k, l]) => ({ l, cls: S.waF === k ? 'on' : '', pick: set({ waF: k }) }));
    out.waQ = S.waQ; out.onWaQ = (e) => self.setState({ waQ: e.target.value });
    const pf = (x) => S.waF === 'all' || (S.waF === 'missing' && ['nowa', 'bad', 'none'].includes(x.st)) || (S.waF === 'dash' && x.st === 'unchecked') || (S.waF === 'ok' && x.st === 'ok') || (S.waF === 'nophoto' && !x.d.photo);
    const openN = {}; OPEN.forEach((t) => { if (t.ag) openN[t.ag] = (openN[t.ag] || 0) + 1; });
    const rank = { nowa: 0, bad: 0, none: 0, unchecked: 1, ok: 2 };
    out.waList = allV.filter(pf).filter((x) => !waq || (x.v.a + ' ' + x.v.home + ' ' + x.v.id + ' ' + x.num).toLowerCase().includes(wq))
      .sort((a, b) => rank[a.st] - rank[b.st] || (openN[b.v.id] || 0) - (openN[a.v.id] || 0)).slice(0, 150).map((x) => {
        const v = x.v, editing = S.waEdit === v.id;
        return { id: v.id, a: v.a, ini: ini(v.a), photo: x.d.photo || '', hasPhoto: !!x.d.photo, noPhoto: !x.d.photo, home: v.home || '—', sup: v.sup.slice(0, 3).join(', '),
          dash: v.phOk ? '+880 1••• •••' + v.ph : 'none', num: x.num ? (DATA.live ? x.num : maskPh(x.num)) : '—', checked: x.d.checked || '', stTxt: WST[x.st][0], stCls: WST[x.st][1], open: openN[v.id] || 0,
          upd: x.d.at ? new Date(x.d.at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—',
          editing, notEditing: !editing, draft: S.waDraft, err: editing ? S.waErr : '',
          edit: () => self.setState({ waEdit: v.id, waDraft: x.d.num || '', waErr: '' }), cancel: set({ waEdit: null, waErr: '' }),
          onDraft: (e) => self.setState({ waDraft: e.target.value }),
          save: () => { const n = normPhone(S.waDraft); if (!isBd(n)) { self.setState({ waErr: 'Give a Bangladesh mobile number (01XXXXXXXXX)' }); return; } setDir(v.id, { num: n, noWa: false }); self.setState({ waEdit: null, waErr: '', toast: v.a + ': WhatsApp saved' }); },
          markNo: () => { setDir(v.id, { noWa: true }); self.setState({ toast: v.a + ': marked “not on WhatsApp”' }); },
          onPhoto: async (e) => { const f = e.target.files && e.target.files[0]; if (!f) return; const t = await thumb(f); if (!t) { if (window.vrbPhotoRaw) { window.vrbPhotoRaw(v.id, f); self.setState({ toast: v.a + ': photo sent to VRB' }); } else self.setState({ toast: 'This photo type cannot be shown in the browser. Add it in VRB (HEIC, TIFF …).' }); return; } setDir(v.id, { photo: t }); self.setState({ toast: v.a + ': photo saved' }); },
          wa: x.num ? 'https://wa.me/88' + x.num : '', hasWa: !!x.num };
      });
    out.waShown = fmt(out.waList.length);
    const vs = (window.vrbDirState && window.vrbDirState()) || { connected: false };
    out.vrbOn = !!vs.connected; out.vrbOff = !vs.connected; out.vrbChecking = !!vs.checking;
    out.waCheck = () => { if (window.vrbDirCheck) { window.vrbDirCheck(); self.setState({ toast: 'WhatsApp check started: the helper on WhatsApp Web opens each number (nothing is typed or sent).' }); } else self.setState({ toast: 'Open VRB on this computer: the WhatsApp check runs from its helper on WhatsApp Web.' }); };
    // import: CSV / Excel (numbers) and photos (many files, matched by name or ID in the file name)
    const byName = {}; DATA.ver.forEach((v) => { byName[v.a.toLowerCase().replace(/\s+/g, ' ').trim()] = v; });
    const findV = (key) => { const k = String(key || '').toLowerCase().replace(/\s+/g, ' ').trim(); if (!k) return null; if (/^\d+$/.test(k) && VER[+k]) return VER[+k]; return byName[k] || null; };
    out.onSheet = async (e) => {
      const f = e.target.files && e.target.files[0]; if (!f) return;
      try {
        const rows = /\.xlsx$/i.test(f.name) ? await parseXlsx(await f.arrayBuffer()) : parseCsv(await f.text());
        const head = (rows[0] || []).map((h) => String(h).toLowerCase());
        const hasHead = head.some((h) => /name|id|whats|phone|mobile|number/.test(h));
        const ci = (re, d) => { const i = head.findIndex((h) => re.test(h)); return hasHead && i >= 0 ? i : d; };
        const iId = ci(/^id$|verifier id|agent id/, -1), iName = ci(/name/, 0), iNum = ci(/whats|phone|mobile|number/, 1);
        const items = (hasHead ? rows.slice(1) : rows).map((r) => { const v = (iId >= 0 && findV(r[iId])) || findV(r[iName]); const n = normPhone(r[iNum]);
          return { key: (iId >= 0 ? r[iId] + ' · ' : '') + (r[iName] || ''), v, n, ok: !!v && isBd(n) }; });
        self.setState({ imp: { name: f.name, items }, impMsg: '' });
      } catch (err) { self.setState({ impMsg: 'Could not read ' + f.name + '. Save it as .xlsx or .csv and try again.' }); }
    };
    out.onPhotos = async (e) => {
      const fs = Array.from((e.target.files) || []); if (!fs.length) return; let ok = 0, miss = []; const nd = { ...DIR };
      for (const f of fs) { const base = f.name.replace(/\.[^.]+$/, ''); const v = findV(base) || findV((base.match(/\d{3,}/) || [''])[0]);
        if (!v) { miss.push(f.name); continue; } const t = await thumb(f); if (!t) { miss.push(f.name + ' (type)'); continue; } nd[v.id] = { ...(nd[v.id] || {}), photo: t, at: Date.now() }; ok++; if (window.vrbDirSync) window.vrbDirSync(v.id, nd[v.id]); }
      saveDir(nd); self.setState({ dir: nd, toast: ok + ' photos saved' + (miss.length ? ' · not matched: ' + miss.slice(0, 4).join(', ') + (miss.length > 4 ? ' …' : '') : '') });
    };
    const imp = S.imp;
    out.hasImp = !!imp; out.impMsg = S.impMsg; out.hasImpMsg = !!S.impMsg;
    if (imp) {
      out.impName = imp.name; out.impOk = fmt(imp.items.filter((x) => x.ok).length); out.impBad = fmt(imp.items.filter((x) => !x.ok).length);
      out.impRows = imp.items.slice(0, 200).map((x) => ({ key: x.key, who: x.v ? x.v.a : 'No verifier with this name / ID', num: x.n ? maskPh(x.n) : '—', cls: x.ok ? 'good' : 'bad', st: x.ok ? 'Will be saved' : !x.v ? 'Not matched' : 'Number not valid' }));
      out.impApply = () => { const nd = { ...DIR }; let n = 0; imp.items.filter((x) => x.ok).forEach((x) => { nd[x.v.id] = { ...(nd[x.v.id] || {}), num: x.n, noWa: false, at: Date.now() }; n++; if (window.vrbDirSync) window.vrbDirSync(x.v.id, nd[x.v.id]); }); saveDir(nd); self.setState({ dir: nd, imp: null, toast: n + ' WhatsApp numbers saved' }); };
      out.impCancel = set({ imp: null });
    }

    // ---------- drawer ----------
    const dr = S.drawer; out.drawerOpen = !!dr; out.closeDrawer = set({ drawer: null });
    out.dTrip = false; out.dVer = false; out.dFile = false;
    if (dr && dr.kind === 'trip') {
      const t = TRIPS.find((x) => x.tid === dr.id); const s = SLA.all.concat(SLA.upcoming, SLA.today).find((r) => r.tid === dr.id);
      if (t) {
        out.dTrip = true;
        out.dt = { ...t, stTxt: TST[t.st], stCls: TSC[t.st], crTxt: tTxt(t.cr), startTxt: tTxt(t.start), endTxt: tTxt(t.end), updTxt: ago(t.ageH), ageCls: ageCls(t.ageH), slaTxt: tTxt(t.sla),
          apTxt: t.ap ? tTxt(t.ap.at) + ' · ' + t.ap.kind : 'None', apWhy: t.ap ? t.ap.why : '', remTxt: t.rem || '—', cmtTxt: t.cmt || '—', fileSt: FST[FILES[t.fi].st],
          slaRow: s ? (s.h > 0 ? 'Late by ' + s.h + ' h' : 'Due in ' + Math.abs(s.h) + ' h') : 'Not in SLA list', canRemind: t.ag && t.st <= 4, wa: waMsg(t.agent, [t]), onSend: sent('t' + t.tid), sentTxt: S.sent['t' + t.tid] ? 'Reminder opened ✓' : '',
          goVer: t.ag ? () => self.setState({ tab: 'profile', prof: t.ag, drawer: null }) : null };
        out.dtSiblings = FILES[t.fi].trips.filter((x) => x.tid !== t.tid).map((x) => ({ tid: x.tid, tl: x.tl, stTxt: TST[x.st], stCls: TSC[x.st], pick: open('trip', x.tid) }));
      } else if (s) {
        out.dTrip = true;
        out.dt = { tid: s.tid, os: s.os, tl: '—', file: '(submitted file)', stTxt: 'In SLA list', stCls: 'st-hold', agent: s.agent, area: s.area, station: s.st, crTxt: tTxt(s.cr), startTxt: '—', endTxt: '—', updTxt: '—', slaTxt: tTxt(s.sla), apTxt: '—', apWhy: '', remTxt: '—', cmtTxt: '—', fileSt: '—', slaRow: s.h > 0 ? 'Late by ' + s.h + ' h' : 'Due in ' + Math.abs(s.h) + ' h', canRemind: false };
        out.dtSiblings = [];
      }
    }
    if (dr && dr.kind === 'ver') {
      const ts = OPEN.filter((t) => t.ag === dr.id && inO(t.os)).sort((a, b) => b.ageH - a.ageH), v = VER[dr.id];
      const name = dr.id ? (v ? v.a : 'Verifier ' + dr.id) : 'Not assigned';
      out.dVer = true;
      out.dv = { a: name, ini: dr.id ? ini(name) : '?', n: ts.length, home: v ? v.home || '—' : '—', sup: v ? v.sup.slice(0, 4).join(', ') || '—' : '—', ph: v ? '+880 1••• •••' + v.ph : '—', seen: v ? ago((NOW - v.seen) / 60) : '—',
        hold: ts.filter((t) => t.st === 4).length, stale: ts.filter((t) => t.ageH >= 72).length, canRemind: !!dr.id && ts.length > 0, wa: waMsg(name, ts), onSend: sent('v' + dr.id), sentTxt: S.sent['v' + dr.id] ? 'Reminder opened ✓' : '',
        goProf: dr.id ? () => self.setState({ tab: 'profile', prof: dr.id, drawer: null }) : null };
      out.dvTrips = ts.map((t) => ({ ...t, stTxt: TST[t.st], stCls: TSC[t.st], updTxt: ago(t.ageH), ageCls: ageCls(t.ageH), apTxt: t.ap ? tTxt(t.ap.at) : '', slaTxt: tTxt(t.sla), slaCls: t.sla && t.sla < NOW ? 'bad-t' : '',
        wa: waMsg(name, [t]), onSend: sent('t' + t.tid), sentTxt: S.sent['t' + t.tid] ? '✓' : '', canRemind: !!dr.id, pick: open('trip', t.tid) }));
    }
    out.dSla = false;
    if (dr && dr.kind === 'slav') {
      const rs = SLA[S.slaWin].filter((r) => r.agent === dr.id && inO(r.os)).sort((x, y) => y.h - x.h), vid = NAME2ID[String(dr.id).toLowerCase()];
      out.dSla = true;
      out.ds = { a: dr.id === 'Unassigned' ? 'Not assigned yet' : dr.id, ini: dr.id === 'Unassigned' ? '?' : ini(dr.id), n: rs.length, win: (wins.find((w) => w[0] === S.slaWin) || wins[0])[1],
        canRemind: dr.id !== 'Unassigned', wa: waSla(dr.id, rs, up), onSend: sent('s' + dr.id), sentTxt: S.sent['s' + dr.id] ? 'Reminder opened ✓' : '',
        goProf: vid ? () => self.setState({ tab: 'profile', prof: vid, drawer: null }) : null, hasProf: !!vid };
      out.dsRows = rs.map((r) => { const hh = Math.abs(r.h); const t = hh >= 48 ? Math.round(hh / 24) + ' days' : hh + ' h';
        return { ...r, dur: up ? t + ' left' : t + ' late', sev: up ? (hh <= 16 ? 'sev3' : hh <= 20 ? 'sev2' : 'sev1') : r.h >= 72 ? 'sev3' : r.h >= 24 ? 'sev2' : 'sev1', slaTxt: tTxt(r.sla), crTxt: tTxt(r.cr), pick: open('trip', r.tid) }; });
    }
    if (dr && dr.kind === 'file') {
      const f = FILES[dr.id], ck = S.qcChecks[f.i] || {};
      const items = [['report', 'Report opened and read'], ['attach', 'All attachments present (photos, signature, BS)'], ['inout', 'In / Out station is right for every visit'], ['remarks', 'Remarks are clear and match the bank\'s format'], ['trips', 'Every trip is Finished or has a valid reason']];
      out.dFile = true;
      out.df = { ...f, stTxt: FST[f.st], startTxt: tTxt(f.start), slaTxt: tTxt(f.sla), endTxt: tTxt(f.end), attTxt: f.attach ? 'All required attachments uploaded' : 'Some required attachments are missing', attCls: f.attach ? 'good' : 'bad',
        allOk: items.every(([k]) => ck[k]), doneTxt: S.qcDone[f.i] === 'sub' ? 'Submitted in this demo ✓' : S.qcDone[f.i] === 'back' ? 'Sent back to verifier' : '',
        submit: () => self.setState({ qcDone: { ...S.qcDone, [f.i]: 'sub' } }), back: () => self.setState({ qcDone: { ...S.qcDone, [f.i]: 'back' } }) };
      out.dfChecks = items.map(([k, l]) => ({ l, on: !!ck[k], cls: ck[k] ? 'on' : '', toggle: () => self.setState({ qcChecks: { ...S.qcChecks, [f.i]: { ...ck, [k]: !ck[k] } } }) }));
      out.dfTrips = f.trips.map((t) => ({ tid: t.tid, tl: t.tl, agent: t.agent, stTxt: TST[t.st], stCls: TSC[t.st], area: t.area, pick: open('trip', t.tid) }));
      out.dfDoneN = f.finN ? '+ ' + f.finN + ' finished trips not listed' : '';
    }
    return out;
  }
}

return Component;
}
