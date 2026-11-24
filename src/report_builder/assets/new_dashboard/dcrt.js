// Tiny standalone runtime for the .dc.html template format ({{ }}, sc-for, sc-if, onX events).
(function () {
  const SVGNS = 'http://www.w3.org/2000/svg';
  const EV = { onclick: 'click', oninput: 'input', onchange: 'change', onsubmit: 'submit' };
  function look(path, scope) {
    path = path.trim();
    if (path === 'true') return true; if (path === 'false') return false; if (path === 'null') return null;
    if (/^-?\d+(\.\d+)?$/.test(path)) return Number(path);
    const parts = path.split('.');
    let v;
    for (let i = scope.length - 1; i >= 0; i--) { if (scope[i] && Object.prototype.hasOwnProperty.call(scope[i], parts[0])) { v = scope[i][parts[0]]; break; } }
    for (let j = 1; j < parts.length && v != null; j++) v = v[parts[j]];
    return v;
  }
  const ONE = /^\s*\{\{([^{}]+)\}\}\s*$/;
  function interp(str, scope) {
    return str.replace(/\{\{([^{}]+)\}\}/g, (_, p) => { const v = look(p, scope); return v == null || v === false ? '' : String(v); });
  }
  function build(node, scope, parent, inSvg) {
    if (node.nodeType === 3) { const t = node.nodeValue; parent.appendChild(document.createTextNode(t.includes('{{') ? interp(t, scope) : t)); return; }
    if (node.nodeType !== 1) return;
    const tag = node.localName;
    if (tag === 'sc-if') {
      const m = ONE.exec(node.getAttribute('value') || '');
      if (m && look(m[1], scope)) for (const c of node.childNodes) build(c, scope, parent, inSvg);
      return;
    }
    if (tag === 'sc-for') {
      const m = ONE.exec(node.getAttribute('list') || ''); const as = node.getAttribute('as') || 'item';
      const list = m ? look(m[1], scope) : null;
      (Array.isArray(list) ? list : []).forEach((it, i) => { const sc = scope.concat([{ [as]: it, $index: i }]); for (const c of node.childNodes) build(c, sc, parent, inSvg); });
      return;
    }
    const svg = inSvg || tag === 'svg';
    const el = svg ? document.createElementNS(SVGNS, tag) : document.createElement(tag);
    for (const a of Array.from(node.attributes)) {
      const name = a.name, val = a.value, low = name.toLowerCase();
      if (low.startsWith('hint-')) continue;
      const m = ONE.exec(val);
      if (EV[low]) { const fn = m ? look(m[1], scope) : null; if (typeof fn === 'function') el.addEventListener(EV[low], fn); continue; }
      let v = m ? look(m[1], scope) : (val.includes('{{') ? interp(val, scope) : val);
      if ((low === 'value') && !svg) { el.__v = v == null ? '' : String(v); el.value = el.__v; el.setAttribute('value', el.__v); continue; }
      if (v === false || v == null) continue;
      if (typeof v === 'function') continue;
      el.setAttribute(name, v === true ? '' : String(v));
    }
    for (const c of node.childNodes) build(c, scope, el, svg);
    if (tag === 'select' && el.__v != null) el.value = el.__v;
    parent.appendChild(el);
  }
  class DCLogic {
    constructor(props) { this.props = props || {}; this.state = {}; }
    setState(o) { Object.assign(this.state, typeof o === 'function' ? o(this.state) : o); if (this.__render) this.__render(); }
    forceUpdate() { if (this.__render) this.__render(); }
  }
  window.DCLogic = DCLogic;
  window.dcMount = function (tplXml, Comp, props, root) {
    const doc = new DOMParser().parseFromString('<root xmlns="http://www.w3.org/1999/xhtml">' + tplXml + '</root>', 'application/xml');
    const err = doc.getElementsByTagName('parsererror')[0];
    if (err) { root.textContent = 'Template error: ' + err.textContent; return; }
    const tpl = doc.documentElement;
    const comp = new Comp(props);
    comp.__render = function () {
      const act = document.activeElement; let key = null, s = null, e = null;
      if (act && root.contains(act) && (act.tagName === 'INPUT' || act.tagName === 'TEXTAREA')) { key = act.getAttribute('placeholder') || act.type; try { s = act.selectionStart; e = act.selectionEnd; } catch (x) {} }
      const vals = comp.renderVals();
      const frag = document.createDocumentFragment();
      for (const c of tpl.childNodes) build(c, [vals], frag, false);
      root.replaceChildren(frag);
      if (key) { const n = Array.from(root.querySelectorAll('input,textarea')).find((x) => (x.getAttribute('placeholder') || x.type) === key); if (n) { n.focus(); try { if (s != null) n.setSelectionRange(s, e); } catch (x) {} } }
    };
    comp.__render();
    return comp;
  };
})();
