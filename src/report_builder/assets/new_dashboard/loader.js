// VRB live loader (staged).  Reads the Verify dashboard API with GET requests only, using the signed-in user's own
// session.  The token stays inside this closure; it is never shown, logged or stored.
(function () {
  const API = 'https://api.verify.bmapsbd.com/api/v2/';
  const SH = { 'Brac Bank PLC': 'BRAC', 'City Bank PLC': 'City', 'Prime Bank PLC': 'Prime', 'LankaBangla Finance Limited': 'LBFL', 'Bank Asia': 'Bank Asia', 'Southeast Bank PLC': 'SEBL', 'IPDC': 'IPDC', 'Biniyog.io': 'Biniyog' };
  const ORG = ['BRAC', 'City', 'Prime', 'LBFL', 'Bank Asia', 'SEBL', 'IPDC', 'Biniyog'];
  const ORGN = ['Brac Bank PLC', 'City Bank PLC', 'Prime Bank PLC', 'LankaBangla Finance', 'Bank Asia', 'Southeast Bank PLC', 'IPDC Finance', 'Biniyog.io'];
  const TYL = { HOUSE: 'House', OFFICE: 'Office', GUARANTOR_HOUSE: 'PG House', BANK: 'Bank (BS)', DOCUMENT: 'Document', GUARANTOR_OFFICE: 'PG Office', DOC_DRCHAMBER: 'Dr chamber', DOC_TUITION: 'Tuition', RENTAL: 'Rental', CAR_QUOTATION: 'Car Quotation' };
  const MONS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const DH = 6 * 3600e3, pad = (n) => String(n).padStart(2, '0');
  let token = null;
  async function get(p) {
    for (let i = 0; i < 3; i++) {
      try {
        if (!token) token = (await (await fetch('/api/auth/session', { credentials: 'include' })).json()).accessToken;
        const r = await fetch(API + p, { headers: { Authorization: 'Bearer ' + token, Accept: 'application/json' } });
        if (r.ok) return await r.json();
        if (r.status === 401) token = null; else if (r.status < 500 && r.status !== 429) return null;
      } catch (e) { /* retry */ }
      await new Promise((res) => setTimeout(res, 800 * (i + 1)));
    }
    return null;
  }
  async function pool(items, fn, n, tick) { let i = 0, done = 0; await Promise.all(Array.from({ length: n }, async () => { while (i < items.length) { const k = i++; try { await fn(items[k]); } catch (e) { /* skip */ } done++; if (tick) tick(done, items.length); } })); }
  function parseMs(s) {
    if (!s || s === 'null') return null;
    if (/[zZ]$|[+-]\d\d:?\d\d$/.test(s)) { const t = Date.parse(s); return isNaN(t) ? null : t; }
    const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?/.exec(s); if (!m) { const t = Date.parse(s); return isNaN(t) ? null : t; }
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)) - DH;
  }
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').replace(/(\+?88)?01[3-9]\d{8}/g, '[phone]').trim().slice(0, 110);

  // store: { key, monthKey, day: {d: {sc:{org:obj}, os:{org:obj}, at:ms}}, det: {id:{sig, app}} } kept by the caller
  window.vrbLoadStaged = async function (store, onStage, progress) {
    progress = progress || (() => {});
    const b = new Date(Date.now() + DH), Y = b.getUTCFullYear(), M = b.getUTCMonth() + 1, T = b.getUTCDate();
    const mk = Y + '-' + pad(M);
    if (store.monthKey !== mk) { store.monthKey = mk; store.day = {}; store.det = {}; }
    store.day = store.day || {}; store.det = store.det || {};
    const ms0 = Date.UTC(Y, M - 1, 1) - DH;
    const mins = (s) => { const t = parseMs(s); return t == null ? null : Math.round((t - ms0) / 60000); };
    const iso = (d) => Y + '-' + pad(M) + '-' + pad(d);
    const range = 'dateFrom=' + iso(1) + '&dateTill=' + iso(T);
    const D = { live: true, year: Y, mon: M, monName: MONS[M - 1], today: T, now: Math.round((Date.now() - ms0) / 60000), orgs: ORG, orgN: ORGN, types: [], files: [], trips: [], sla: { upcoming: [], today: [], all: [] }, ver: [], daily: [], dailyMode: 'month', recpvOld: [], types1: [], stage: 1 };

    // ---- stage 1: month totals, SLA, verifiers, attendance (about 15 calls) ----
    progress('Dashboard totals', 0.05);
    const tot = await get('dashboard/status-counts?' + range);
    const orgIds = ((tot && tot.data && tot.data.organizations) || []).filter((o) => SH[o.name]).map((o) => [SH[o.name], o.org_id]);
    const scM = {}; ((tot && tot.data && tot.data.organizations) || []).forEach((o) => { if (SH[o.name]) scM[SH[o.name]] = o; });
    const osM = {};
    const [slaU, slaT, slaA, verJ, flJ, rcJ, tcJ] = await Promise.all([
      'dashboard/sla-breaches?type=upcoming', 'dashboard/sla-breaches?type=today', 'dashboard/sla-breaches?type=all', 'verifiers',
      'analytics/agents/first-last-task?' + range, 're-cpv/tracker?' + range, 'analytics/trips/completed?' + range,
    ].map(get).concat([]));
    await pool(orgIds, async (o) => { const j = await get('dashboard/org/summery?' + range + '&org_id=' + o[1]); if (j && j.data) osM[o[0]] = j.data; }, 4, (a, n) => progress('Dashboard totals', 0.05 + 0.25 * a / n));
    const row = (d, oi, x, s) => { x = x || {}; const f = (s && s.files) || {}, t = (s && s.trips) || {};
      return [d, oi, x.total_applications || 0, x.total_loan || 0, x.total_card || 0, x.application_finished_in_one_go || 0, x.total_trips || 0, x.total_re_cpv || 0, x.trip_not_accepted || 0, x.trip_on_process || 0, x.trip_on_hold || 0, x.trip_finished || 0,
        (s && s.total_files) || 0, (s && s.total_trips) || 0, f.submitted || 0, f.partially_submitted || 0, f.finished || 0, f.cancelled || 0, t.cancelled || 0, t.inactive || 0]; };
    D.daily = ORG.map((o, oi) => row(0, oi, osM[o], scM[o]));
    const slaRows = (j) => (((j && j.data && j.data.data) || [])).filter((r) => SH[r.organization_name]).map((r) => [r.trip_id, ORG.indexOf(SH[r.organization_name]), r.station === 'IN_STATION' ? 1 : 0, r.agent_name || '', r.area || '', mins(r.created_date), mins(r.sla_date), Math.round((r.breach_duration || 0) / 3600)]);
    D.sla = { upcoming: slaRows(slaU), today: slaRows(slaT), all: slaRows(slaA) };
    D.recpvOld = (((rcJ && rcJ.data && rcJ.data.re_cpv_tracks) || [])).map((r) => { const dd = mins(r.created_at);
      return { file: (r.application && r.application.application_id) || '', os: '—', reason: clean(r.reason), trips: String((r.trips || []).length), day: dd == null ? '' : (Math.floor(dd / 1440) + 1) + ' ' + MONS[M - 1], bill: r.type === 'REGULAR' ? 'Regular' : String(r.type || '') }; }).reverse();
    D.types1 = (((tcJ && tcJ.data && tcJ.data.trip_completed) || [])).sort((a, z) => z.total - a.total).map((x) => ({ l: x.trip_type, nF: Number(x.total || 0).toLocaleString('en-US') }));
    const vers = ((verJ && verJ.taskers) || []).filter((v) => String(v.status) === '1');
    const att = {}; (((flJ && flJ.data && flJ.data.first_last_tasks) || [])).forEach((r) => { (att[r.agent_id] = att[r.agent_id] || []).push([+String(r.date).slice(8, 10), (r.first_task_start_time || '').slice(11, 16), (r.last_task_end_time || '').slice(11, 16), r.finished_count || 0, r.task_count || 0]); });
    function buildVer() {
      const areaCt = {}, orgCt = {}, name2id = {};
      vers.forEach((v) => { name2id[String(v.name || '').trim().toLowerCase()] = v.id; });
      const bump = (m, k, x) => { if (!x) return; (m[k] = m[k] || {}); m[k][x] = (m[k][x] || 0) + 1; };
      D.trips.forEach((t) => { if (t[5]) { bump(areaCt, t[5], t[4]); bump(orgCt, t[5], ORG[D.files[t[1]][1]]); } });
      ['all', 'today', 'upcoming'].forEach((k) => D.sla[k].forEach((r) => { const id = name2id[String(r[3]).trim().toLowerCase()]; if (id) { bump(areaCt, id, r[4]); bump(orgCt, id, ORG[r[1]]); } }));
      const hm = (s) => (s ? +s.slice(0, 2) * 60 + +s.slice(3, 5) : null), f2 = (m) => (m == null ? '—' : pad(Math.floor(m / 60)) + ':' + pad(m % 60));
      const keys = (m) => Object.entries(m || {}).sort((a, z) => z[1] - a[1]).map((x) => x[0]);
      D.ver = vers.map((v) => {
        const A = (att[v.id] || []).sort((a, z) => a[0] - z[0]), fs = A.map((a) => hm(a[1])).filter((x) => x != null), ls = A.map((a) => hm(a[2])).filter((x) => x != null);
        const areas = keys(areaCt[v.id]), ph = String(v.phone || '').replace(/\D/g, '');
        return { id: v.id, a: String(v.name || '').trim(), seen: mins(v.updated_at), act: +v.activity_status || 0, ph: ph.slice(-3), phOk: /^(88)?01[3-9]\d{8}$/.test(ph) ? 1 : 0,
          home: areas[0] || '', sup: areas.slice(1, 7), orgs: keys(orgCt[v.id]).slice(0, 4), days: A.length,
          avgFirst: fs.length ? f2(Math.round(fs.reduce((x, y) => x + y, 0) / fs.length)) : '—', avgLast: ls.length ? f2(Math.round(ls.reduce((x, y) => x + y, 0) / ls.length)) : '—',
          late: fs.filter((m) => m > 630).length, tasks: A.reduce((x, a) => x + a[4], 0), fin: A.reduce((x, a) => x + a[3], 0), dl: A };
      });
    }
    buildVer();
    onStage(D);

    // ---- stage 2: files and trips (details only for files that changed since last time) ----
    D.stage = 2;
    const base = 'manager/applications?' + range + '&sort_by=start_date&sort_order=DESC';
    const list = [];
    for (const st of [1, 2, 3, 4, 5, 7, 8]) {
      let p = 1, last = 1;
      do { const j = await get(base + '&status=' + st + '&page=' + p); const a = j && j.applications; if (!a) break; last = a.last_page || 1; a.data.forEach((f) => list.push(f)); p++; progress('File list', 0.3 + 0.1 * list.length / Math.max(list.length, 1200)); } while (p <= last);
    }
    const sig = (f) => f.status + ':' + (f.trips || []).map((t) => t.id + '.' + t.status).join(',');
    const need = list.filter((f) => !(store.det[f.id] && store.det[f.id].sig === sig(f)));
    const types = D.types, tIdx = (k) => { const l = TYL[k] || String(k || '—').replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase()); let i = types.indexOf(l); if (i < 0) { types.push(l); i = types.length - 1; } return i; };
    function buildFiles() {
      const files = [], trips = [];
      list.forEach((f) => {
        const c = store.det[f.id]; const org = SH[f.group && f.group.name]; if (!c || !org) return;
        const a = c.app, fi = files.length;
        files.push([f.application_id, ORG.indexOf(org), a.application_type, a.status, mins(a.start_date), mins(a.sla), a.station === 'IN_STATION' ? '1' : a.station ? '0' : '', f.has_all_required_attachments ? 1 : 0, mins(f.end_date || a.end_date), 0]);
        (a.concerns || []).forEach((cn) => (cn.trips || []).forEach((t) => {
          const keep = [4, 6, 7].includes(t.status), ap = (t.appointments || []).slice(-1)[0];
          trips.push([t.id, fi, tIdx(t.type), t.status, t.area || '', t.agent ? t.agent.id : 0, mins(t.created_at), mins(t.start_time), [5, 6].includes(t.status) ? mins(t.end_time) : null, t.is_for_recpv ? 1 : 0,
            keep ? clean(t.remarks) : '', keep || t.status === 3 ? clean(t.comment) : '', ap && ap.is_active ? [mins(ap.appointment_time), ap.appointment_type || '', clean(ap.reason)] : 0]);
        }));
      });
      D.files = files; D.trips = trips; buildVer();
    }
    let lastPush = 0;
    await pool(need, async (f) => {
      const j = await get('manager/applications/' + f.id);
      if (j && j.application) store.det[f.id] = { sig: sig(f), app: j.application };
    }, 6, (a, n) => { progress('File details', 0.4 + 0.35 * a / n); if (Date.now() - lastPush > 8000) { lastPush = Date.now(); buildFiles(); onStage(D); } });
    const keep = new Set(list.map((f) => String(f.id))); Object.keys(store.det).forEach((k) => { if (!keep.has(k)) delete store.det[k]; });
    buildFiles(); onStage(D);

    // ---- stage 3: per-day numbers for the date filter (old days reused for 6 h, last 2 days always fresh) ----
    D.stage = 3;
    const jobs = [];
    for (let d = 1; d <= T; d++) { const c = store.day[d]; if (!c || d >= T - 1 || Date.now() - c.at > 6 * 3600e3) jobs.push(d); }
    await pool(jobs, async (d) => {
      const one = 'dateFrom=' + iso(d) + '&dateTill=' + iso(d);
      const j = await get('dashboard/status-counts?' + one); const sc = {}; ((j && j.data && j.data.organizations) || []).forEach((o) => { if (SH[o.name]) sc[SH[o.name]] = o; });
      const os = {}; await Promise.all(orgIds.map(async (o) => { const k = await get('dashboard/org/summery?' + one + '&org_id=' + o[1]); if (k && k.data) os[o[0]] = k.data; }));
      store.day[d] = { sc, os, at: Date.now() };
    }, 3, (a, n) => progress('Day-by-day numbers', 0.75 + 0.25 * a / n));
    const daily = [];
    for (let d = 1; d <= T; d++) { const c = store.day[d]; if (!c) continue; ORG.forEach((o, oi) => daily.push(row(d, oi, c.os[o], c.sc[o]))); }
    D.daily = daily; D.dailyMode = 'day'; D.stage = 4; D.now = Math.round((Date.now() - ms0) / 60000);
    progress('Up to date', 1);
    onStage(D);
    return D;
  };
})();
