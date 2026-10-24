/* wavelens/src/boot.js — themes and colours, global settings, the declarative upgrade, the page hooks, the exports.
   Closes the scope opened in model.js. */

/* ---------------- themes & colours ---------------- */
function lookCss(map) { // {trace: '#c00', '--wave-bus': 'navy'} -> "--wave-1:#c00;--wave-bus:navy"
  return Object.entries(map || {}).filter(([, v]) => v != null && v !== '').map(([k, v]) => `${CVAR[k] || TOK[k] || k}:${v}`).join(';');
}
function applyLook(el, theme, colors) { // theme: light | white | dark | auto (= inherit); colors: map, null value removes
  if (theme !== undefined && theme !== null) { if (THEMES.includes(theme)) el.dataset.theme = theme; else delete el.dataset.theme; }
  for (const [k, v] of Object.entries(colors || {})) {
    const name = CVAR[k] || TOK[k] || k;
    if (v == null || v === '') el.style.removeProperty(name); else el.style.setProperty(name, v);
  }
}
// Global (default: <html>, i.e. the page and every wave) or one element; static SVGs follow through CSS, viewers are redrawn.
function setTheme(name, el = document.documentElement) { applyLook(el, name || 'auto', null); redrawAll(); }
function setColors(map, el = document.documentElement) { applyLook(el, undefined, map); redrawAll(); }
const redrawAll = () => VIEWS.forEach(v => { if (v.root.isConnected) v.draw(); else v.destroy(); });
// the static SVG hosts, re-rendered by configure(): their model and options by the element (WeakMap), the elements by
// weak reference (a host that leaves the page and is collected takes its model with it)
const SVGS = new WeakMap(), SVG_HOSTS = new Set();
const SVG_PLUGINS = [];   // WaveLens.svgPlugin(fn): fn(model, settings, opts) -> [extraRows fn] for every static SVG
const redrawSvgs = () => SVG_HOSTS.forEach(ref => { const el = ref.deref(), d = el && SVGS.get(el); if (d && el.isConnected) WaveSVG.render(el, d[0], d[1]);
  else SVG_HOSTS.delete(ref); });
// Global settings, e.g. from a config file: { theme, colors, rowHeight, nameWidth, fontSize, traceWidth, sort, sortIgnore, … }.
// theme/colors go to <html> like setTheme/setColors; the rest becomes the default for every wave (null removes a key).
function configure(cfg = {}) {
  const { theme, colors, ...rest } = cfg || {}, html = document.documentElement;
  warnKeys(rest, 'the global settings (wavelens.config.js, WaveLens.configure)');
  for (const [k, v] of Object.entries(rest)) { if (v == null) delete GLOBAL[k]; else GLOBAL[k] = v; }
  for (const [k, name] of Object.entries(STYLE_VAR)) if (k in rest && rest[k] == null) html.style.removeProperty(name);
  for (const [name, v] of styleVars(rest)) html.style.setProperty(name, v);
  if (theme !== undefined) applyLook(html, theme || 'auto', null);
  if (colors) applyLook(html, undefined, colors);
  VIEWS.forEach(v => { if (v.root.isConnected) v.restyle(); else v.destroy(); });
  redrawSvgs();
  return Object.assign({}, GLOBAL);
}

/* ---------------- declarative upgrade ---------------- */
function resolveSrc(el) {
  if (el.tagName === 'SCRIPT') return el.textContent;
  const ref = el.dataset.wave;
  if (ref.startsWith('#')) { const s = document.querySelector(ref); if (!s) throw new Error(`data-wave="${ref}": no such element`); return s.textContent; }
  const v = ref.split('.').reduce((o, key) => (o == null ? o : o[key]), G);
  if (v == null) throw new Error(`data-wave="${ref}": not found (is the data <script src> loaded?)`);
  return v;
}
function optsFrom(ds) {
  const o = ds.config ? Object.assign({}, parseText(ds.config)) : {};   // data-config='{"rowHeight": 30, "sort": "asc"}'
  if (ds.title) o.title = ds.title;
  for (const k of ['cursor', 'from', 'to']) if (ds[k] != null) o[k] = parseT(ds[k]);
  if (ds.width) o.width = +ds.width;
  if (ds.fit != null) o.fit = true;
  if (ds.theme) o.theme = ds.theme;
  if (ds.colors) o.colors = parseText(ds.colors);
  if (ds.sort != null) o.sort = ds.sort || 'asc';
  if (ds.sortIgnore != null) o.sortIgnore = ds.sortIgnore;
  if (ds.highlight != null) o.highlight = ds.highlight;   // data-highlight="tb.dut, *.valid"
  return o;
}
function mount(host, el, mode, opts) {
  try {
    const M = parse(resolveSrc(el));
    if (host.waveView) host.waveView.destroy();   // built again (upgrade of a host that had a viewer)
    if (mode === 'svg') WaveSVG.render(host, M, opts); else new WaveView(host, M, opts);
  } catch (e) { host.className = 'wvf-err'; host.textContent = 'wavelens: ' + e.message; }
}
function upgrade(root = document) {
  VIEWS.forEach(v => { if (!v.root.isConnected) v.destroy(); });   // viewers whose element left the page
  root.querySelectorAll('script[type="application/wavedrom"], script[type="WaveDrom"], [data-wave]').forEach(el => {
    if (el.dataset.wvfDone) return; el.dataset.wvfDone = '1';
    let host = el;
    if (el.tagName === 'SCRIPT') { host = document.createElement('div'); if (el.id) host.id = el.id + '-view'; el.after(host); }
    const mode = el.dataset.mode || (el.type === 'WaveDrom' ? 'svg' : 'view'), opts = optsFrom(el.dataset);
    const go = () => { host.classList.remove('wvf-lazy'); host.innerHTML = ''; mount(host, el, mode, opts); };
    if (el.dataset.lazy == null) return go();
    // lazy: build on button click or when the enclosing <details> opens (template.html "Load waveform" pattern)
    let done = false; const once = () => { if (!done) { done = true; go(); } };
    host.classList.add('wvf-lazy'); host.innerHTML = '<button type="button">Load waveform</button>';
    host.querySelector('button').addEventListener('click', once);
    const det = host.closest('details');
    if (det) { if (det.open) once(); else det.addEventListener('toggle', () => { if (det.open) once(); }); }
  });
}

/* ---------------- theme / font redraws, auto-run, exports ---------------- */
if (G.matchMedia) G.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', redrawAll);
// print: every viewer draws all its rows (paintPrint), the screen canvas comes back after
G.addEventListener('beforeprint', () => VIEWS.forEach(v => { if (v.root.isConnected) v.print(true); }));
G.addEventListener('afterprint', () => VIEWS.forEach(v => { if (v.printing) v.print(false); }));
document.addEventListener('keydown', e => {   // Esc with nothing focused (after a click on text): reset the viewer used last
  if (e.key === 'Escape' && (e.target === document.body || e.target === document.documentElement) && ACTIVE.view &&
    ACTIVE.view.root.isConnected) ACTIVE.view.reset();
});
if (G.MutationObserver) {
  new MutationObserver(redrawAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
  // data-theme on any element below <html> (the viewer itself, a card around it): the viewers inside it draw again
  new MutationObserver(ms => {
    const els = ms.map(m => m.target).filter(t => t !== document.documentElement);
    if (els.length) VIEWS.forEach(v => { if (v.root.isConnected && els.some(t => t.contains(v.root))) v.draw(); });
  }).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['data-theme'] });
}
if (document.fonts && document.fonts.ready) document.fonts.ready.then(redrawAll);
const HTML_STYLE = document.documentElement.getAttribute('style');   // the page's own, before the settings' variables go on it (Save page)
if (G.WAVELENS_CONFIG) configure(G.WAVELENS_CONFIG);   // settings file loaded before wavelens.js (see docs/USAGE.md "Settings")
const manual = document.currentScript && document.currentScript.dataset.manual != null;
// a page that carries the live link (tools/wavemcp.py view_live) or is opened with #wavelens-live=<port>:<token> connects to the
// agent once its viewers are there
const liveHash = () => {
  const m = /[#&]wavelens-live=([^&]+)/.exec(location.hash), el = document.getElementById('wavelens-live');
  try { const o = !m && el ? JSON.parse(el.textContent) : null; if (m || o) live(m ? decodeURIComponent(m[1]) : `${o.port}:${o.token}`); }
  catch (e) { console.error('wavelens live: ' + e.message); }
};
// Save page: the page as it was read, taken before a viewer is built; only a page that is all in itself (no script or
// stylesheet of its own beside it: a page of mkhtml.py) and whose viewers are not built yet (else PAGE.why says why);
// savePage: false leaves it (a big page: one more copy of its text)
const takeSrc = () => {
  if (PAGE.src != null || PAGE.why || settings(GLOBAL).savePage === false) return;
  const own = [...document.querySelectorAll('script[src], link[rel~=stylesheet][href]')].find(e => !/^(https?:)?\/\//i.test(e.getAttribute('src') ||
    e.getAttribute('href') || ''));
  if (own) { PAGE.why = `this page needs ${own.getAttribute('src') || own.getAttribute('href')} beside it: Save page is for a page that is all in ` +
    'itself (make html, mkhtml.py); Save keeps the view'; return; }
  if (VIEWS.size || document.querySelector('[data-wvf-done]')) { PAGE.why = 'the viewers of this page were built before it was read: Save keeps the ' +
    'view'; return; }
  const d = document.doctype;
  PAGE.src = document.documentElement.outerHTML; PAGE.style = HTML_STYLE;
  const ids = d && (d.publicId ? ` PUBLIC "${d.publicId}"` : d.systemId ? ' SYSTEM' : '') + (d.systemId ? ` "${d.systemId}"` : '');
  PAGE.doctype = d ? `<!DOCTYPE ${d.name}${ids}>\n` : '';
};
// the theme the bar's ◐ chose in this browser (a page with a theme of its own, or a button of its own, keeps its own)
const keptTheme = () => { if (!themeButtonOn(settings(GLOBAL)) || document.documentElement.dataset.theme) return;
  let t = null; try { t = localStorage.getItem('wavelens-theme'); } catch (e) { /* none */ }
  if (THEMES.includes(t)) applyLook(document.documentElement, t, null); };
const start = () => {   // built already: no Save page
  takeSrc(); keptTheme(); if (PAGE.why) VIEWS.forEach(v => v.layoutShow()); if (!manual) upgrade(); liveHash(); };
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();

/* ---------------- tooltips: what a control of a viewer does and its keys ---------------- */
// [text, keys] of a control: TIPS by its data-act / -sv / -x / -bm / -m / -jump value or a class, else its own title
const TIP_DATA = ['act', 'sv', 'x', 'bm', 'm', 'jump'];
function tipOf(el) {
  const d = el.dataset;
  for (const k of TIP_DATA) if (d[k] != null) { const t = TIPS[`${k}:${d[k]}`] || (k === 'jump' && TIPS.jump); if (t) return t; }
  for (const c of el.classList) if (TIPS['.' + c]) return TIPS['.' + c];
  const own = el.title || d.ttl;
  return own ? [own] : null;
}
const TIP_SEL = '.wv button, .wv input, .wv select, .wv .mk, .wv label.mi, .wv [data-tip]';
let tipEl = null, tipAt = null, tipT = 0;
function tipHide() { clearTimeout(tipT); tipAt = null; if (tipEl) { tipEl.remove(); tipEl = null; } }
function tipShow(el) {
  const t = el.isConnected && tipOf(el), root = el.closest('.wv'); if (!t || !root) return;
  if (el.title) { el.dataset.ttl = el.title; el.removeAttribute('title'); }   // ours instead of the browser's
  tipEl = document.createElement('div'); tipEl.className = 'wv-tip'; tipEl.setAttribute('role', 'tooltip');
  tipEl.innerHTML = `<span>${esc(t[0])}</span>${t[1] && t[1].length ? `<span class="tk">${t[1].map(k => `<kbd>${esc(k)}</kbd>`).join('')}</span>` : ''}`;
  root.append(tipEl);
  const r = el.getBoundingClientRect(), b = tipEl.getBoundingClientRect(), below = r.bottom + 6 + b.height < innerHeight;
  tipEl.style.left = Math.max(4, Math.min(r.left + r.width / 2 - b.width / 2, innerWidth - b.width - 4)) + 'px';
  tipEl.style.top = (below ? r.bottom + 6 : r.top - b.height - 6) + 'px';
}
// the wait before a tooltip: 350 ms, in the right button's menu menuTipDelay (2 s: it reads, it is not in the way)
const tipWait = el => { const v = el.closest('.wv-menu') && el.closest('.wv'), S = v && v.waveView && v.waveView.S;
  return S ? Math.max(0, +S.menuTipDelay || 0) : 350; };
document.addEventListener('pointerover', e => {
  const el = e.target.closest && e.target.closest(TIP_SEL);
  if (el === tipAt) return;
  tipHide(); if (!el) return;
  if (el.title) { el.dataset.ttl = el.title; el.removeAttribute('title'); }   // no browser tooltip while ours waits
  tipAt = el; tipT = setTimeout(() => tipShow(el), tipWait(el));
});
document.addEventListener('pointerout', e => { if (tipAt && !(e.relatedTarget && tipAt.contains(e.relatedTarget))) tipHide(); });
document.addEventListener('focusin', e => { const el = e.target.closest && e.target.closest(TIP_SEL); tipHide();
  if (el && el.matches(':focus-visible')) { tipAt = el; tipT = setTimeout(() => tipShow(el), tipWait(el)); } });
for (const ev of ['pointerdown', 'keydown', 'wheel']) document.addEventListener(ev, e => { if (ev !== 'keydown' || e.key !== 'Tab') tipHide(); }, true);
G.addEventListener('scroll', tipHide, true);
const tips = { add: map => Object.assign(TIPS, map), of: tipOf };

// plugins: fn(viewer) runs for every viewer already built and every later one
const plugin = fn => { PLUGINS.push(fn); VIEWS.forEach(v => { if (v.root.isConnected) try { fn(v); } catch (e) { console.error('wavelens plugin:', e); } }); };
// static SVGs: fn(model, settings, opts) -> extraRows functions; the SVGs already drawn are drawn again
const svgPlugin = fn => { SVG_PLUGINS.push(fn); redrawSvgs(); };
G.WaveLens = { version: '0.20',   // the project's version: VERSION (make check compares them)
  rowId: () => ++XID, parse, fromTV, vcdToWave, vcdToWaveFile, svTables, svApply, svTypes, WaveView, WaveSVG, upgrade, redrawAll, redrawSvgs, setTheme,
  setColors,
  configure, savePage, pageText,
  plugin, svgPlugin, views: () => [...VIEWS], defaults: DEFAULTS, live,
  commands: () => Object.fromEntries(Object.entries(CMDS).map(([k, c]) => [k, { args: c.args, doc: c.doc }])),
  paint: { circle, arrowHead, edgeGeom, lastLE },
  sortRows: (M, dir = 'asc', ignore = [], groupOrder = 'file') => orderRows(parse(M).rows, sortDir(dir), prefixes(ignore), groupOrder), fuzzy, themes: THEMES,
    colorNames: CVAR, styles: Object.keys(EDGES), radixes: RADIX, enums: ENUMS, decode, fmtTime, fmtExact, parseT,
  registerTokens, registerDefaults, tips, util: { esc, glob, lastLE, lastBefore, stepTo, isEdge, circle, timeEps },
  // unstable: the pure functions for the unit table of tests/smoke.py and peek(view), the fields the tests read; not an API
  internal: { findRow, parseWant, valueIs, findEdge, edgeGlyph, bitsOf, hexOf, mixedBits, bitsVal, vcdHex, cycZero, cycAt, cycTime, cycUps, cycClock,
    diffSpans, cmpKey, svTypes, svApply, fsmStats,
    cycMarks, enumColor, analogValue, niceStep, cycMap, parseWave,
    idleCuts, gapLen, gapText, gapRefs, fmtFreq, gfmt, toFloat, fieldRow, stripPfx, trimNum,
    peek: v => ({ get lay() { return v.lay; }, get oy() { return v.oy; }, get vis() { return v.vis; }, get collapsed() { return v.collapsed; },
      get rowEls() { return v.rowEls; }, get namesEl() { return v.namesEl; } }) } };
G.WaveView = WaveView; G.WaveSVG = WaveSVG;
})(window);
