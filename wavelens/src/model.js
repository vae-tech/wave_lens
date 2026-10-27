/* wavelens/src/model.js — the model: tokens, settings, highlight, sorting, plugin rows, find, time, values, the WaveJSON
   parser, edge search and the bookmark lists. Opens the one scope of wavelens.js (closed in boot.js). */
(function (G) {
'use strict';

/* ---------------- tokens & helpers ---------------- */
// Colour names used by the painters -> CSS custom properties (defined in wavelens.css, overridable by the page).
const TOK = { fg: '--fg', muted: '--muted', line: '--line', panel: '--panel', panel2: '--panel-2', acc: '--accent',
  one: '--wave-1', bus: '--wave-bus', x: '--wave-x', xsoft: '--wave-x-soft', z: '--wave-z',
  c3: '--wave-c3', c4: '--wave-c4', c5: '--wave-c5', c6: '--wave-c6', c7: '--wave-c7', c8: '--wave-c8', c9: '--wave-c9',
  band: '--wave-band', cursor2: '--wave-cursor2',
  // hl7: find, hl8: plugins
  hl1: '--wave-hl1', hl2: '--wave-hl2', hl3: '--wave-hl3', hl4: '--wave-hl4', hl5: '--wave-hl5', hl6: '--wave-hl6', hl7: '--accent', hl8: '--wave-hl8',
  paint: '--wave-paint' };   // the find group's Paint colour; plugins add their own (WaveLens.registerTokens)
// a colour name of the painters: a token, a CSS custom property ("--x", "var(--x)") or a colour as it is
const registerTokens = map => { for (const [k, v] of Object.entries(map || {})) TOK[k] = v; return Object.assign({}, TOK); };
// a key a table has of its own, not one every object inherits ("constructor", "toString"): what a command, a setting or
// this browser's storage names is looked up so
const hasKey = (o, k) => k != null && Object.prototype.hasOwnProperty.call(o, k);
const tokVar = n => hasKey(TOK, n) ? `var(${TOK[n]})` : /^--[\w-]+$/.test(n) ? `var(${n})` : n;   // a colour name as CSS
// Friendly names for colour maps (config.colors, data-colors, WaveLens.setColors) -> CSS custom properties.
const CVAR = { trace: '--wave-1', one: '--wave-1', bus: '--wave-bus', x: '--wave-x', xfill: '--wave-x-soft', z: '--wave-z',
  bg: '--panel', panel: '--panel', header: '--panel-2', grid: '--line', text: '--fg', muted: '--muted', accent: '--accent', cursor: '--accent',
  page: '--bg', c3: '--wave-c3', c4: '--wave-c4', c5: '--wave-c5', c6: '--wave-c6', c7: '--wave-c7', c8: '--wave-c8', c9: '--wave-c9',
  hl1: '--wave-hl1', hl2: '--wave-hl2', hl3: '--wave-hl3', hl4: '--wave-hl4', hl5: '--wave-hl5', hl6: '--wave-hl6',
  band: '--wave-band', cursor2: '--wave-cursor2' };
const THEMES = ['light', 'white', 'dark'];
const ENUMS = {};   // global enum registry: full path (or a signal name, for every signal of that name) -> { value: label }
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = v => (typeof v === 'number' ? v : parseFloat(v));
// a key as keysLeft names it: ctrl+ (cmd too) alt+ shift+ and the key, a letter by its place (ctrl+G on any layout)
const keyName = e => (e.ctrlKey || e.metaKey ? 'ctrl+' : '') + (e.altKey ? 'alt+' : '') + (e.shiftKey ? 'shift+' : '') +
  (/^Key[A-Z]$/.test(e.code || '') ? e.code.slice(3) : String(e.key || '').length === 1 ? String(e.key).toUpperCase() : String(e.key || ''));
// a key the viewer leaves to its host (keysLeft: ["ctrl+G"]; the VS Code tab: wavelens.keysToVSCode): not taken, not stopped
const keyLeft = (S, e) => { const l = S && S.keysLeft; if (!l || !l.length || !(e.ctrlKey || e.metaKey || e.altKey)) return false;
  const k = keyName(e).toLowerCase(); return [].concat(l).some(x => String(x).replace(/\s+/g, '').replace(/^cmd\+/i, 'ctrl+').toLowerCase() === k); };
// binary search over n sorted items: the index of the last one with at(i) <= t (strict: < t), -1 if none
function lastBefore(n, at, t, strict = false) {
  let lo = 0, hi = n - 1, ans = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1, a = at(m); if (strict ? a < t : a <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans;
}
const lastLE = (a, t) => lastBefore(a.length, i => a[i].t, t);   // the last transition with time <= t
// the rounding step of a time t in ps: a few hundred ulps of a double (0.01 ps at 1 s), so a step from the cursor never
// jumps over an event a picosecond away on a long run (1e-9 · t was 1 ps at 1 ms)
const timeEps = t => Math.max(1e-10, 1e-14 * Math.abs(t));   // 1e-10 ps: under a zeptosecond, the finest VCD unit
// the index of the next (dir > 0) or previous item of the sorted times beyond t by more than a rounding step, round
// the ends; -1: no item. ]m [m, ]t [t, ]f [f and the ƒ expression's ◀ ▶ step by it
function stepTo(times, t, dir) {
  const n = times.length, eps = timeEps(t);
  if (!n) return -1;
  if (dir > 0) { for (let i = 0; i < n; i++) if (times[i] > t + eps) return i; return 0; }
  for (let i = n - 1; i >= 0; i--) if (times[i] < t - eps) return i;
  return n - 1;
}
// an edge as IEEE 1800-2017 9.4.2 (and the sva CLI) between two bit levels 0 1 x z: posedge 0->1 0->x 0->z x->1 z->1,
// negedge the mirror, edge either; prev null: the first value, no edge. The bus decoders and the assertions use it
function isEdge(edge, prev, b) {
  if (prev === null) return false;
  const u = v => v === 'x' || v === 'z', rise = (prev === '0' && b !== '0') || (u(prev) && b === '1'),
    fall = (prev === '1' && b !== '1') || (u(prev) && b === '0');
  return edge === 'posedge' ? rise : edge === 'negedge' ? fall : rise || fall;
}
const flatText = t => Array.isArray(t) ? t.slice(typeof t[1] === 'object' && !Array.isArray(t[1]) ? 2 : 1).map(flatText).join('') : (t == null ? '' :
  String(t));

/* ---------------- settings (config file / WaveLens.configure / config in the JSON / data-* / opts) ---------------- */
// Layers, later wins: DEFAULTS < global (window.WAVELENS_CONFIG, WaveLens.configure) < WaveJSON "config" < element / opts.
// theme and colors are not merged here: they become data-theme / CSS custom properties (see applyLook).
const DEFAULTS = { rowHeight: 26, groupHeight: 22, spaceHeight: 14, headerHeight: 24, traceWidth: 1.4, busWidth: 1.2,
  labelSize: 11, fontSize: 11.5, sort: 'none', sortIgnore: [], sortButton: true, hint: true, style: 'auto', radix: 'auto', fold: null,
  highlight: null, dim: 0.3, groupColors: null, bookmarkLeft: 0.2, arrowLabels: 'lane', laneHeight: 16, maxHeight: null, toolsFolded: false, toolsHidden: [],
  groupOrder: 'file', moduleShading: true, findHighlight: true, findOpen: true, findMask: false, findCase: false, findWord: false,
  findRegex: false, cursorSnap: 8,
    wheel: 'scroll', contextMenu: true, enumColors: null, dumpBudget: 3000000, gaps: false, gapIdle: 16, gapKeep: 2,
    gapSignals: null, gapClock: null, gapAux: null, gapOnly: false, gapCount: 'clock', gapLine: 'dashdot', menuTipDelay: 2000, cycles: false,
    cycleClock: null, cycleZero: null, savePage: true, themeButton: 'auto', version: true, keysLeft: [], log: 'auto' };
// a plugin's settings with their defaults (bus.js: busDetect, buses; sva.js: svaOpen, svaShow, svaSignals): in every
// layer like the framework's own, listed in WaveLens.defaults, known to the warning on unknown keys
const registerDefaults = map => { Object.assign(DEFAULTS, map || {}); return Object.assign({}, DEFAULTS); };
const SVG_DEFAULTS = { groupHeight: 20, spaceHeight: 12 };   // the static figure is a little denser
const GLOBAL = {};
// settings that live in CSS (so the names column, fonts and static SVG text follow them too); numbers are px
const STYLE_VAR = { nameWidth: '--wv-names', fontSize: '--wv-font-size', fontMono: '--font-mono', fontBody: '--font-body', maxHeight: '--wv-max-h' };
// the bar's tool groups left out (toolsHidden): their labels, lower case, sorted ("cursor,go to" or a list)
const toolNames = v => [...new Set((Array.isArray(v) ? v : String(v ?? '').split(',')).map(s => String(s).trim().toLowerCase()).filter(Boolean))].sort();
const prefixes = v => (Array.isArray(v) ? v : String(v ?? '').split(',')).map(s => String(s).trim()).filter(Boolean);
function settings(...layers) {
  const S = Object.assign({}, DEFAULTS);
  for (const l of layers) for (const [k, v] of Object.entries(l || {})) if (v != null && k !== 'theme' && k !== 'colors') S[k] = v;
  for (const k of ['rowHeight', 'groupHeight', 'spaceHeight', 'headerHeight', 'traceWidth', 'busWidth', 'labelSize', 'fontSize', 'dim',
    'laneHeight']) S[k] = num(S[k]) || DEFAULTS[k];
  S.sort = sortDir(S.sort); S.sortIgnore = prefixes(S.sortIgnore).sort((a, b) => b.length - a.length);
  if (!hasKey(EDGES, S.style)) S.style = 'auto';
  if (S.groupsFirst && S.groupOrder === 'file') S.groupOrder = 'first';   // older setting
  return S;
}
// a setting the framework does not know (a typo in a config file, "rowHeigth"): a warning in the console, once per key;
// the plugins' keys and WaveDrom's own are known too (the tools refuse such a key: tools/common.py check_config)
const KNOWN_KEYS = new Set(['theme', 'colors', 'groupsFirst', 'hscale', 'skin']), WARNED = new Set();
function warnKeys(cfg, where) {
  const keys = Object.keys(cfg || {});
  const run = () => { for (const k of keys) if (!(k in DEFAULTS) && !(k in STYLE_VAR) && !KNOWN_KEYS.has(k) && !WARNED.has(k)) {
    WARNED.add(k); console.warn(`wavelens: ${where}: unknown setting "${k}" (the settings are the keys of wavelens.config.js)`);
  } };
  // while the page loads, the plugins' scripts (registerDefaults) may come after this: checked when they are all there
  if (typeof document !== 'undefined' && document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run, { once: true }); else run();
}
const styleVars = cfg => Object.entries(STYLE_VAR).filter(([k]) => cfg && cfg[k] != null && cfg[k] !== '')
  .map(([k, name]) => [name, typeof cfg[k] === 'number' ? cfg[k] + 'px' : String(cfg[k])]);
// edge styles ("style" setting or per signal): slope = px of a slanted 1-bit edge (null: WaveDrom wave strings slanted,
// exact "tv" transitions vertical), bevel = px of the bus "<>" ends. questa/square = vertical edges like a simulator viewer.
const EDGES = { auto: { slope: null, bevel: 3 }, wavedrom: { slope: 2.5, bevel: 3 }, questa: { slope: 0, bevel: 1.5 }, square: { slope: 0, bevel: 0 } };
const STYLE_NAMES = { auto: 'auto', wavedrom: 'slanted', questa: 'vertical', square: 'square' };   // in the viewer's list
// fold setting: true (every group), a depth (groups at that nesting depth and deeper) or group paths ("tb.dut", "dut")
function foldSet(M, f) {
  const out = new Set(), names = Array.isArray(f) ? new Set(f.map(String)) : typeof f === 'string' ? new Set(prefixes(f)) : null;
  if (f == null || f === false) return out;
  for (const g of Object.values(M.groups))
    if (f === true || (typeof f === 'number' && g.depth >= f) || (names && (names.has(g.path) || names.has(g.name)))) out.add(g.id);
  return out;
}

/* ---------------- highlight: picked signals / groups stay in front, the other rows dim ---------------- */
const HL_N = 6;   // colours --wave-hl1…6, one per picked instance
const glob = p => new RegExp('^' + p.split('*').map(s => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$');
// "highlight" setting -> Map(row -> colour index): each entry (full path, name or "*" pattern) is one instance / colour
function hlPick(M, list, rows = M.rows) {   // rows: where to look (a viewer: its own groups too)
  const picks = new Map();
  prefixes(list).forEach((p, i) => {
    const rx = p.includes('*') ? glob(p) : null;
    for (const r of rows) if (r.type !== 'space' && !picks.has(r) && (rx ? rx.test(r.full) : r.full === p || r.name === p)) picks.set(r, i % HL_N);
  });
  return picks;
}
// picks -> { cover: Map(row -> colour) for picked rows and members of picked groups, on: rows drawn in front, dim }.
// Your picks and the find's (a colour index) only bring their rows to the front; a plugin's (a token: 'hl8') also tints them
function hlState(M, picks, dim, rows = M.rows) {
  if (!picks || !picks.size) return null;
  const cover = new Map(), on = new Set();
  for (const r of rows) {
    let c = picks.get(r) ?? (r.orig && picks.get(r.orig));   // a signal highlighted: its row in your group too
    for (let i = r.anc.length - 1; c === undefined && i >= 0; i--) c = picks.get(M.groups[r.anc[i]]);
    if (c !== undefined) { cover.set(r, c); on.add(r); r.anc.forEach(id => on.add(M.groups[id])); }   // keep their group headers too
  }
  return { cover, on, dim };
}

/* ---------------- group colours: every signal of a group in one colour (AXI channels, modules …) ---------------- */
// "groupColors" setting {group: colour}: group = full path, name or "*" pattern; the nearest matching group wins. Its
// signals take the colour (trace, bus outline, name) unless they have their own "color" / "stroke"; the group's name too.
// -> Map(row -> colour); the model's rows stay as they are (a viewer and an SVG of one model may colour differently).
function groupPaint(M, map) {
  const out = new Map(), list = Object.entries(map || {}).map(([p, c]) => [p.includes('*') ? glob(p) : p, c]);
  if (!list.length) return out;
  const of = g => { for (const [p, c] of list) if (typeof p === 'string' ? g.full === p || g.name === p : p.test(g.full)) return c; };
  for (const r of M.rows) {
    if (r.type === 'space' || r.type === 'lane' || r.stroke) continue;
    let c = r.type === 'group' ? of(r) : undefined;
    for (let i = r.anc.length - 1; c === undefined && i >= 0; i--) c = of(M.groups[r.anc[i]]);
    if (c !== undefined) out.set(r, c);
  }
  return out;
}

/* ---------------- signal sorting (natural order, optional prefixes ignored: i_, o_ …) ---------------- */
const SORTS = ['none', 'asc', 'desc'];
const sortDir = v => (v === true ? 'asc' : SORTS.includes(v) ? v : 'none');
const COLL = typeof Intl !== 'undefined' ? new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' }) : null;
const stripPfx = (name, pfx) => { const p = pfx.find(p => name.startsWith(p) && name.length > p.length); return p ? [p, name.slice(p.length)] : ['', name]; };
// rows in display order: siblings (one group level, between {} spacers) sorted by name; groups move as a block;
// groupOrder: 'first' / 'last' = inside every group the sub-groups (modules) come before / after the signals; 'file' = as given
function orderRows(rows, dir, pfx, groupOrder) {
  const sorting = dir === 'asc' || dir === 'desc', gs = groupOrder === 'first' ? -1 : groupOrder === 'last' ? 1 : 0;
  if (!sorting && !gs) return rows;
  const kids = new Map([[null, []]]);
  for (const r of rows) { kids.get(r.anc.length ? r.anc[r.anc.length - 1] : null).push(r); if (r.type === 'group') kids.set(r.id, []); }
  const key = r => stripPfx(r.name, pfx)[1], sgn = dir === 'desc' ? -1 : 1;
  const c = (x, y) => (COLL ? COLL.compare(x, y) : x < y ? -1 : x > y ? 1 : 0);
  const byName = (a, b) => sgn * (c(key(a), key(b)) || c(a.name, b.name));   // i_data / o_data: full name breaks the tie
  const cmp = (a, b) => gs * ((a.type === 'group') - (b.type === 'group')) || (sorting ? byName(a, b) : 0);   // stable sort
  const out = [];
  const emit = list => {
    let run = [];
    const flush = () => { for (const r of run.sort(cmp)) { out.push(r); if (r.type === 'group') emit(kids.get(r.id)); } run = []; };
    for (const r of list) { if (r.type === 'space') { flush(); out.push(r); } else run.push(r); }
    flush();
  };
  emit(kids.get(null));
  return out;
}

/* ---------------- rows of plugins (view.extraRows, WaveSVG opts.extraRows) ---------------- */
// fn(group | null) -> [row] for every group of the diagram and its top (null); the rows go after the group's own signals
// (as a block: sorting does not move them). A returned row without `anc` belongs to the group; a group row takes its
// `id` from WaveLens.rowId() and joins the model's groups (folding, Expand / Collapse); a row with draw(P, {y, h, X, tA,
// tB, xL, xR}) paints itself, a "sig" row with `tr` like a signal. Return the same objects while they stay: the viewer
// keys its state (selection, highlight, folding) by them. More, all optional: `height` (px), `cls` (classes of its name),
// `title` (of a group's name), `value(t)` (the value column), `overlay(P, {pos: Map(row -> {y, h}), X, tA, tB, xL, xR, yA, yB})`
// (drawn once after all rows: arrows between rows; yA–yB the rows drawn; `overlay.rows`: other rows it draws on, it runs
// when one of those is on screen too), `click(x, y, view)` / `tip(x, y, view)` (a click / the tooltip on
// the waves, y inside the row; click returns true when it handled it), `same: true` (a copy of a signal shown elsewhere:
// bookmarks stay on the original), `legend: [{n?, text, color?, bold?}]` (lines under the static SVG). A function with
// `head: true` puts its top rows (group null) before every other row (the viewer's own groups), not after the top's signals.
let XID = 1e6;
const XGROUPS = new WeakMap();   // owner (a viewer, an SVG host, a model) -> the ids of the groups its plugins added last time
function withExtra(rows, fns, M, owner = M) {
  if (!fns || !fns.length) return rows;
  const ids = new Set();
  const extras = (g, head = false) => {
    const out = [];
    for (const f of fns) if (!!f.head === head) for (const r of f(g) || []) {
      if (!r.anc) { r.anc = g ? g.anc.concat(g.id) : []; r.depth = g ? g.depth + 1 : 0; }
      if (r.type === 'group' && r.id != null) { M.groups[r.id] = r; ids.add(r.id); }
      out.push(r);
    }
    return out;
  };
  const at = new Map([['top', -1]]);   // where each group's rows go: after its last own row (or its header)
  rows.forEach((r, i) => {
    if (r.type === 'group') at.set(r.id, i);
    else at.set(r.anc.length ? r.anc[r.anc.length - 1] : 'top', i);
  });
  const after = new Map();
  for (const [k, i] of at) { if (!after.has(i)) after.set(i, []); after.get(i).push(k); }
  const out = extras(null, true);
  const put = i => { for (const k of after.get(i) || []) out.push(...extras(k === 'top' ? null : M.groups[k])); };
  put(-1);
  rows.forEach((r, i) => { out.push(r); put(i); });
  for (const id of XGROUPS.get(owner) || []) if (!ids.has(id) && M.groups[id] && M.groups[id].id === id) delete M.groups[id];   // gone ones leave
  XGROUPS.set(owner, ids);
  return out;
}

/* ---------------- fuzzy find (fzf-like): the letters of the query in order, anywhere in the name ---------------- */
// -> null or { score, idx: matched positions }; consecutive letters and word starts (after . _ [ /) score higher
function fuzzy(q, s, cs = false) {   // cs: the case matters
  const t = cs ? s : s.toLowerCase(), idx = [];
  let j = 0, score = 0, prev = -2;
  if (!cs) q = q.toLowerCase();
  for (let i = 0; i < t.length && j < q.length; i++) {
    if (t[i] !== q[j]) continue;
    score += (i === prev + 1 ? 6 : 1) + (i === 0 || '._[/ '.includes(t[i - 1]) ? 4 : 0);
    idx.push(i); prev = i; j++;
  }
  return j === q.length ? { score: score - t.length / 100, idx } : null;
}
// a row against the query words (all must match). A word "a.b" = "a" in the path of the modules above the row and "b"
// in its name (fzf over paths): "dev.fifo_s" = a fifo_s… signal somewhere below a …dev… module.
// The scope is the path of the groups above the row (its own path without the leaf when it has no groups); the name
// matches as shown or as the dump's leaf (a signal shown under an alias is found by its own name too, without marks).
// The options o (the find group's toggles): cs the case matters (Aa); full a word is the whole name, or with "." the end
// of the full path at a dot (Full); re a RegExp instead of the words (.*), tried on the shown name, the leaf, the full path.
function findRow(r, terms, M, o = {}) {
  const name = r.name, full = r.full || name;
  const scope = r.anc.length ? r.anc.map(id => (M.groups[id] || {}).name || '').join('.') : r.scope != null ? r.scope : full.includes('.') ?
    full.slice(0, full.lastIndexOf('.')) : '';
  const leaf = r.path ? r.path.slice(r.path.lastIndexOf('.') + 1) : '';
  const span = (a, n) => Array.from({ length: n }, (_, i) => a + i);
  if (o.re) {
    const m = o.re.exec(name);
    if (m) return { score: 100 - name.length / 100, idx: span(m.index, m[0].length) };
    return (leaf && o.re.test(leaf)) || o.re.test(full) ? { score: 50 - full.length / 100, idx: [] } : null;
  }
  let score = 0; const idx = [];
  for (const w of terms) {
    if (o.full) {
      const eq = (a, b) => (o.cs ? a === b : a.toLowerCase() === b.toLowerCase());
      if (w.includes('.') ? !(eq(full, w) || (full.length > w.length && eq(full.slice(-w.length - 1), '.' + w))) : !(eq(name, w) ||
        (leaf && eq(leaf, w)))) return null;
      score += 10; if (w.includes('.') || eq(name, w)) idx.push(...span(0, name.length));   // the whole name marked
      continue;
    }
    const k = w.lastIndexOf('.'), sq = k < 0 ? '' : w.slice(0, k).replace(/\./g, ''), nq = k < 0 ? w : w.slice(k + 1);
    const ms = sq ? fuzzy(sq, scope, o.cs) : { score: 0 };
    let mn = nq ? fuzzy(nq, name, o.cs) : { score: 0, idx: [] };
    if (!mn && leaf && leaf !== name) { const ml = fuzzy(nq, leaf, o.cs); if (ml) mn = { score: ml.score - 1, idx: [] }; }
    if (!ms || !mn) return null;
    score += ms.score + mn.score; idx.push(...mn.idx);   // marks inside the shown name
  }
  return { score, idx };
}

/* ---------------- time formatting ---------------- */
const UNITS = [[1e12, 's'], [1e9, 'ms'], [1e6, 'µs'], [1e3, 'ns'], [1, 'ps']];
const UNIT_PS = { fs: 1e-3, ps: 1, ns: 1e3, us: 1e6, 'µs': 1e6, ms: 1e9, s: 1e12 };
function fmtTime(ps, ref, unitRef) { // ref = resolution (axis step, span/1000 …) -> decimals; unitRef (default ref) -> unit
  ref = Math.abs(ref || ps) || 1;
  const uref = Math.abs(unitRef || ref) || 1;
  const [f, u] = UNITS.find(([f]) => uref >= f) || UNITS[UNITS.length - 1];
  const d = Math.max(0, Math.min(3, Math.ceil(-Math.log10(ref / f) - 1e-9)));
  return (ps / f).toFixed(d) + ' ' + u;
}
// every digit down to 1 ps, trailing zeros dropped, in the unit of unitRef (default ps itself): the cursor and the
// bookmarks read the same at any zoom (1234567 ps -> "1.234567 µs")
function fmtExact(ps, unitRef) {
  const uref = Math.abs(unitRef || ps) || 1, [f, u] = UNITS.find(([f]) => uref >= f) || UNITS[UNITS.length - 1];
  let s = (ps / f).toFixed(Math.round(Math.log10(f)));
  if (s.includes('.')) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return s + ' ' + u;
}
const trimNum = (v, d = 3) => String(Math.round(v * 10 ** d) / 10 ** d);
// a period (ps) as its frequency, four digits: 40000 -> "25 MHz", 6400 -> "156.3 MHz"
function fmtFreq(ps) {
  const f = 1e12 / ps, [m, u] = [[1e9, 'GHz'], [1e6, 'MHz'], [1e3, 'kHz']].find(([m]) => f >= m) || [1, 'Hz'], v = f / m;
  return trimNum(v, v >= 100 ? 1 : v >= 10 ? 2 : 3) + ' ' + u;
}
function parseT(v) { // "1.5us" -> 1.5e6 (ps); plain numbers are model units
  if (v == null || v === '') return undefined;
  const m = /^\s*(-?[\d.]+(?:e-?\d+)?)\s*(fs|ps|ns|us|µs|ms|s)?\s*$/i.exec(String(v));
  if (!m) return undefined;
  return parseFloat(m[1]) * (m[2] ? UNIT_PS[m[2].toLowerCase()] : 1);
}
function niceStep(target, cycles) { // smallest 1-2-5 step >= target
  const e = 10 ** Math.floor(Math.log10(Math.max(target, 1e-9)));
  const s = [1, 2, 5, 10].find(m => m * e >= target - 1e-12) * e;
  return cycles ? Math.max(1, Math.round(s)) : Math.max(1, s);
}

/* ---------------- value decoding (extension signals with "tv") ---------------- */
// radix (per signal "radix", else the "radix" setting): auto (≤6 bits dec, else hex) | hex | dec | signed | bin | oct | ascii
const RADIX = ['auto', 'hex', 'dec', 'signed', 'bin', 'oct', 'ascii', 'float'];
// a radix: one of RADIX, or fixed point "q<F>" / "sq<F>" (unsigned / signed, F fraction bits: q8, sq15)
const isRadix = r => RADIX.includes(r) || /^s?q\d{1,3}$/.test(String(r));
// a number as C's %.<p>g (also tools/vcd2wavedrom.py: the same text): fixed between 1e-5 and 1e<p>, else d.ddde±x
function gfmt(f, p = 7) {
  if (Number.isNaN(f)) return 'nan';
  if (!isFinite(f)) return f < 0 ? '-inf' : 'inf';
  if (f === 0) return Object.is(f, -0) ? '-0' : '0';
  const e = Math.floor(Math.log10(Math.abs(Number(f.toPrecision(p)))));
  const trim = s => (s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s);
  if (e >= -4 && e < p) return trim(f.toFixed(Math.max(0, p - 1 - e)));   // C's %g: exponential below 1e-4
  const [m, x] = f.toExponential(p - 1).split('e');
  return trim(m) + 'e' + (x[0] === '-' ? '-' : '+') + x.replace(/^[+-]/, '').padStart(2, '0');
}
// IEEE 754 of a w-bit pattern (16, 32, 64), else null
function toFloat(n, w) {
  if (w === 64) { const d = new DataView(new ArrayBuffer(8)); d.setBigUint64(0, n); return d.getFloat64(0); }
  if (w === 32) { const d = new DataView(new ArrayBuffer(4)); d.setUint32(0, Number(n)); return d.getFloat32(0); }
  if (w === 16) { const h = Number(n), s = h >> 15 ? -1 : 1, e = (h >> 10) & 31, m = h & 1023;
    return e === 0 ? s * m * 2 ** -24 : e === 31 ? (m ? NaN : s * Infinity) : s * (1 + m / 1024) * 2 ** (e - 15); }
  return null;
}
// a value's key in an enum table (decimal, as the JSON has it): exact past 2^53 too (Verilator's 64-bit enums)
const enumKey = h => (h.length <= 13 ? String(parseInt(h, 16)) : BigInt('0x' + h).toString());
function decode(sig, v, radix) {
  if (v === undefined) return '?';
  if (/[xz]/i.test(v)) return (sig.radix || radix) === 'bin' ? [...v].map(c => (/[xz]/i.test(c) ? c.repeat(4) : parseInt(c, 16).toString(2)
    .padStart(4, '0'))).join('').slice(-(sig.width || 1)) : v;   // whole nibbles x / z: bin spells them out
  const e = sig.enum || ENUMS[sig.full] || ENUMS[sig.name];
  if (e && v) { const n = enumKey(v); if (e[n] !== undefined) return e[n]; }
  const w = sig.width || 1, big = () => BigInt('0x' + (v || '0')) & ((1n << BigInt(w)) - 1n);   // a value wider than the signal: its low bits
  const r = sig.radix || radix, q = /^(s?)q(\d+)$/.exec(r || '');
  if (q) {   // fixed point: the value / 2^F exactly (the F decimals of 1/2^F: the fraction times 5^F), trailing zeros left out
    let n = big(); const m = 1n << BigInt(w); if (q[1] && w > 1 && n >= m >> 1n) n -= m;
    const F = BigInt(q[2]), neg = n < 0n, a = neg ? -n : n, ip = a >> F, fp = a & ((1n << F) - 1n);
    const frac = fp ? '.' + (fp * 5n ** F).toString().padStart(Number(F), '0').replace(/0+$/, '') : '';
    return (neg ? '-' : '') + ip + frac;
  }
  switch ({ unsigned: 'dec', sdec: 'signed' }[r] || r) {
    case 'float': { const f = toFloat(big(), w); if (f != null) return gfmt(f, w === 64 ? 15 : w === 16 ? 4 : 7); break; }
    case 'dec': return big().toString();
    case 'signed': { const n = big(), m = 1n << BigInt(w); return String(w > 1 && n >= m >> 1n ? n - m : n); }
    case 'bin': return big().toString(2).padStart(w, '0');
    case 'oct': return '0o' + big().toString(8);
    case 'hex': return '0x' + v.toUpperCase();
    case 'ascii': if (!v) return '""'; return '"' + (v.length % 2 ? '0' + v : v).match(/../g).map(h => parseInt(h, 16)).filter((c, i, a) => c ||
      i === a.length - 1)
      .map(c => (c >= 32 && c < 127 ? String.fromCharCode(c) : '.')).join('') + '"';
  }
  if (w <= 6) return String(parseInt(v, 16));
  return '0x' + v.toUpperCase();
}
// bus label of transition o with the radix in effect (re-decoded only when the radix changes)
const vtext = (s, o, radix) => o.raw == null ? o.v : (s.radix || radix || 'auto') === o.rk ? o.vr : (o.rk = s.radix || radix || 'auto',
  o.vr = o.bits && o.rk === 'bin' ? o.bits : decode(s, o.raw, o.rk));

// where JSON.parse stopped in a text -> {line, col (1 the first), text: that line}, from its message (V8: "… at position 12
// (line 2 column 5)", Firefox: "… at line 2 column 5 …"; an end too soon: the end), null when it says no place (Safari)
function jsonWhere(text, e) {
  const m = String((e && e.message) || ''), lc = /line (\d+) column (\d+)/.exec(m), pos = /position (\d+)/.exec(m), lines = String(text).split('\n');
  let line, col;
  if (lc) { line = +lc[1]; col = +lc[2]; }
  else if (pos) { const b = String(text).slice(0, +pos[1]).split('\n'); line = b.length; col = b[b.length - 1].length + 1; }
  else if (/end of (JSON )?(input|data)|unexpected EOF/i.test(m)) { line = lines.length; col = lines[line - 1].length + 1; }
  else return null;
  return { line, col, text: (lines[line - 1] || '').replace(/\r$/, '') };
}
// JSON.parse with the place of an error: Error "<name>: <what> at line L, column C" whose .json is {name, msg, line, col,
// text} (the log shows the line and a caret under the column)
function jsonParse(text, name = 'JSON', what = 'not JSON') {
  if (!String(text).trim()) { const e = new Error(`${name}: ${what}: the file is empty`); e.json = { name, msg: 'the file is empty' }; throw e; }
  try { return JSON.parse(text); } catch (x) {
    const w = jsonWhere(text, x), msg = String(x.message).replace(/^JSON\.parse: /, '').replace(/ (in JSON )?at (position \d+|line \d+ column \d+).*$/, '');
    const e = new Error(`${name}: ${what}${w ? ` at line ${w.line}, column ${w.col}` : ''}: ${msg}`);
    e.json = Object.assign({ name, msg }, w); throw e;
  }
}

/* ---------------- parser: WaveJSON -> model ---------------- */
function parseText(txt) {
  try { return JSON.parse(txt); } catch (e) {
    // WaveDrom editor syntax (unquoted keys, single quotes, trailing commas) — evaluated like stock WaveDrom does
    return Function('"use strict"; return (' + txt + '\n);')();
  }
}
function cycMap(tm) { // cycle -> model time; "skip": [[k, n]] = the char at index k ('|') stands for n cycles
  if (!tm) return c => c;
  const t0 = num(tm.t0) || 0, cy = num(tm.cycle) || 1, skip = (tm.skip || []).slice().sort((a, b) => a[0] - b[0]);
  return c => {
    let extra = 0;
    for (const [k, n] of skip) { if (c >= k + 1) extra += n - 1; else if (c > k) extra += (c - k) * (n - 1); }
    return t0 + (c + extra) * cy;
  };
}
const WAVE_CHARS = new Set('01xzpnPNhlHLud=23456789.|');
function parseWave(s, C) {
  const per = num(s.period) || 1, ph = num(s.phase) || 0, wave = String(s.wave || '');
  const data = Array.isArray(s.data) ? s.data.map(flatText) : (s.data != null ? String(s.data).trim().split(/\s+/) : []);
  const tr = [], gaps = [];
  let di = 0, last = null, clk = null;
  const push = (c, o) => { o.t = C(c); tr.push(o); last = o; };
  const level = (c, k, s, a) => { if (!last || last.k !== k) push(c, { k, s, a }); };
  const clock = (c0, ch) => { // one clock period per char: p/P rise at the cell start, n/N fall
    const up = ch === 'p' || ch === 'P';
    level(c0, up ? '1' : '0', true, ch === 'P' || ch === 'N');
    level(c0 + per / 2, up ? '0' : '1', true, false);
  };
  for (let i = 0; i < wave.length; i++) {
    const ch = wave[i], c0 = i * per - ph;
    if (ch === '|') gaps.push(C(c0 + per / 2));
    if (ch === '.' || ch === '|' || !WAVE_CHARS.has(ch)) { if (clk) clock(c0, clk); continue; }
    clk = null;
    if ('pnPN'.includes(ch)) { clk = ch; clock(c0, ch); }
    else if (ch === '0' || ch === '1' || ch === 'u' || ch === 'd' || ch === 'x' || ch === 'z') level(c0, ch, false, false);
    else if ('hlHL'.includes(ch)) level(c0, 'hH'.includes(ch) ? '1' : '0', true, ch === 'H' || ch === 'L');
    else {
      const k = di++, hx = Array.isArray(s.raw) ? s.raw[k] : undefined, b = typeof hx === 'string' && hx.startsWith("'b") ? hx.slice(2) : null;
      push(c0, Object.assign({ k: '=', v: data[k] ?? '', hex: b ? hexOf(b) : hx, c: ch === '=' ? 2 : +ch, s: false }, b ? { bits: b } : {}));
    }
  }
  return { tr, gaps, end: wave.length * per - ph };
}
// a value's bits, MSB first, w long: '0' '1' 'x' 'z' (a bus's hex raw, a bit's level)
function bitsOf(o, w) {
  if (!o) return 'x'.repeat(w);
  if (o.k !== '=') return (o.k === '0' || o.k === '1' || o.k === 'z' ? o.k : 'x').repeat(w);
  if (o.bits) return o.bits.length >= w ? o.bits.slice(o.bits.length - w) : o.bits.padStart(w, '0');   // known bits among x / z
  // WaveDrom data: 0x.. or a number
  const v = String(o.v ?? ''), h = String(o.raw ?? o.hex ?? (/^0x[0-9a-f_]+$/i.test(v) ? v.slice(2).replace(/_/g,
    '') : /^\d+$/.test(v) ? BigInt(v).toString(16) : '')).toLowerCase();
  if (!/^[0-9a-fxz]+$/.test(h)) return 'x'.repeat(w);
  const b = [...h].map(c => (c === 'x' || c === 'z' ? c.repeat(4) : parseInt(c, 16).toString(2).padStart(4, '0'))).join('');
  return b.length >= w ? b.slice(b.length - w) : b.padStart(w, b[0] === 'x' || b[0] === 'z' ? b[0] : '0');
}
const hexOf = bits => { const p = bits.padStart(Math.ceil(bits.length / 4) * 4, '0'); let out = '';
  for (let i = 0; i < p.length; i += 4) { const n = p.slice(i, i + 4); out += /x/.test(n) ? 'x' : /z/.test(n) ? (n === 'zzzz' ? 'z' : 'x') : parseInt(n,
    2).toString(16); }
  return out; };
// true when hex would lose bits: a nibble with an x or z that is not all x or all z ("10x1": hex x)
const mixedBits = bits => { const p = bits.padStart(Math.ceil(bits.length / 4) * 4, '0');
  for (let i = 0; i < p.length; i += 4) { const n = p.slice(i, i + 4); if (/[xz]/.test(n) && n !== 'xxxx' && n !== 'zzzz') return true; }
  return false; };
// a vector's value from its bits: x / z when all of them are, else its hex, the bits kept too when the hex loses some
const bitsVal = bits => (/^x+$/.test(bits) ? { k: 'x' } : /^z+$/.test(bits) ? { k: 'z' } : Object.assign({ k: '=', raw: hexOf(bits) },
  mixedBits(bits) ? { bits } : {}));
// a struct's whole value: its parts' bits put together (the first part the MSB) at every change of any of them
function joinBits(g, parts) {
  const w = parts.reduce((n, p) => n + (p.width || 1), 0), ts = [...new Set(parts.flatMap(p => p.tr.map(o => o.t)))].sort((a, b) => a - b), tr = [];
  const sig = { type: 'sig', name: g.name, full: g.path, path: g.path, depth: g.depth, anc: g.anc, width: w, tr, gaps: [], struct: true, src: {} };
  for (const t of ts) {
    const bits = parts.map(p => bitsOf(p.tr[lastLE(p.tr, t)], p.width || 1)).join('');
    const o = bitsVal(bits);
    if (o.k === '=') { o.c = 2; o.v = decode(sig, o.raw); o.bad = /[xz]/.test(o.raw); }
    const L = tr[tr.length - 1]; if (L && L.k === o.k && L.raw === o.raw && L.bits === o.bits) continue;
    o.t = t; tr.push(o);
  }
  return sig;
}
// the parts of a struct group, its first field first: its signals and its structs' whole values (sub: a struct's whole)
function structParts(M, g, sub = x => x.sig) {
  return M.rows.filter(r => r.anc.length === g.anc.length + 1 && r.anc[g.anc.length] === g.id && (r.type === 'sig' ? r.tr && !r.same : r.type === 'group'))
    .map(r => (r.type === 'group' ? sub(r) : r)).filter(Boolean);
}
// a field [msb:lsb] of a packed vector as a row of its own (its name under the vector's, its radix, its labels)
function fieldRow(sig, f, depth, anc) {
  const msb = num(f && f.msb), lsb = num(f && (f.lsb ?? f.msb)); if (!f || !f.name || !isFinite(msb) || !isFinite(lsb)) return null;
  if (msb < lsb || lsb < 0 || msb >= (sig.width || 1)) {   // outside the vector: said, and left out (it would read past it: NaN)
    console.warn(`wavelens: ${sig.full}: field ${f.name} [${msb}:${lsb}] is not inside the ${sig.width || 1}-bit vector (msb first, lsb 0): left out`);
    return null;
  }
  const w = msb - lsb + 1, r = { type: 'sig', name: String(f.name), depth, anc, width: w, enum: f.enum, radix: f.radix, path: null, src: f, fromTv: !!sig.tv,
    full: sig.full + '.' + f.name, field: [msb, lsb], tr: [], gaps: [], of: sig };
  for (const o of sig.tr) {
    const b = bitsOf(o, sig.width), fb = b.slice(b.length - 1 - msb, b.length - lsb);
    const n = w === 1 ? { k: /^[01z]$/.test(fb) ? fb : 'x' } : bitsVal(fb);
    if (n.k === '=') { n.v = decode(r, n.raw); n.bad = /[xz]/.test(n.raw); const e = r.enum || ENUMS[r.full] || ENUMS[r.name], k = parseInt(n.raw, 16);
      n.c = e && !isNaN(k) ? 3 + (k % 7) : 2; }
    const L = r.tr[r.tr.length - 1]; if (L && L.k === n.k && L.raw === n.raw && L.bits === n.bits) continue;
    n.t = o.t; r.tr.push(n);
  }
  return r;
}
function parseTV(s, sig) { // extension: exact transitions [[time, value], …]; bit values 0/1/x/z, bus values hex or "'b" + bits;
  // "kind": "real" / "string": the values are texts shown as they are (a real's number, a string), null unknown
  const tv = s.tv || [], text = s.kind === 'real' || s.kind === 'string';
  sig.width = num(s.width) || (!text && tv.every(([, v]) => /^[01xz]$/i.test(String(v))) ? 1 : 8); sig.tv = true;
  const tr = [];
  for (const [t, v0] of tv) {
    const v = String(v0).toLowerCase(); let o;
    if (text) o = v0 == null ? { k: 'x' } : { k: '=', v: String(v0), c: 2 };
    else if (sig.width === 1) o = { k: v === '1' ? '1' : v === '0' ? '0' : v === 'z' ? 'z' : 'x' };
    else if (/^x+$/.test(v)) o = { k: 'x' };
    else if (/^z+$/.test(v)) o = { k: 'z' };
    else {   // hex, or "'b" and binary digits: known bits among x / z (vcdHex)
      const b = /^'b[01xz]+$/.test(v) ? v.slice(2) : null, h = b ? hexOf(b) : v, e = sig.enum || ENUMS[sig.full] || ENUMS[sig.name], n = parseInt(h, 16);
      o = { k: '=', raw: h, v: decode(sig, h), bad: /[xz]/.test(h),
        c: /^[2-9]$/.test(String(s.color)) ? +s.color : (e && !isNaN(n) ? 3 + (n % 7) : 2) };
      if (b) o.bits = b;
    }
    const L = tr[tr.length - 1];
    if (L && L.k === o.k && L.raw === o.raw && L.v === o.v && L.bits === o.bits) continue;
    o.t = num(t); tr.push(o);
  }
  return { tr, gaps: [] };
}
function parseEdge(str) { // "a~>b label": from node, shape, to node, label
  const m = /^(\S)(\S*?)(\S)(?:\s+(.*))?$/.exec(String(str).trim());
  if (!m) return null;
  const sh = m[2], plus = sh === '+';
  return { from: m[1], to: m[3], label: m[4] || '', as: plus || sh.startsWith('<'), ae: plus || sh.endsWith('>'),
    shape: plus ? '-' : (sh.replace(/^</, '').replace(/>$/, '') || '-') };
}
function parse(src) {
  if (src && src.__wavelens) return src;
  const j = typeof src === 'string' ? parseText(src) : src;
  if (!j || !Array.isArray(j.signal)) throw new Error('WaveJSON needs a "signal" array');
  const tm = j.time || null, C = cycMap(tm);
  const M = { __wavelens: true, src: j, timed: !!tm, rows: [], groups: {}, nodes: {}, edges: [],
    title: flatText(j.head && j.head.text), foot: flatText(j.foot && j.foot.text),
    tick: j.head && j.head.tick != null ? num(j.head.tick) : null, every: (j.head && num(j.head.every)) || 1,
    tock: j.foot && j.foot.tock != null ? num(j.foot.tock) : null, hscale: (j.config && num(j.config.hscale)) || 1,
    theme: j.config && j.config.theme, colors: (j.config && j.config.colors) || null, cfg: j.config || {} };
  warnKeys(M.cfg, 'WaveJSON "config"');
  let cyc = 0, tmin = Infinity, tmax = -Infinity, gid = 0;
  // extension "same": "path" = the transitions of the signal with that "path" (one net seen at several levels)
  const byPath = {}, collect = a => a.forEach(it => { if (Array.isArray(it)) collect(it); else if (it && it.path && it.tv) byPath[it.path] = it.tv; });
  collect(j.signal);
  const walk = (arr, depth, anc) => {
    for (let it of arr) {
      if (Array.isArray(it)) {
        const named = typeof it[0] === 'string', label = named ? it[0] : '';
        if (label) {
          const g = { type: 'group', name: label, depth, anc, id: gid++, path: anc.map(id => M.groups[id].name).concat(label).join('.') };
          g.full = g.path;
          M.groups[g.id] = g; M.rows.push(g);
          walk(it.slice(1), depth + 1, anc.concat(g.id)); g.last = M.rows.length - 1;
        } else walk(named ? it.slice(1) : it, depth, anc);
      } else if (it && typeof it === 'object' && (it.wave != null || it.tv || it.same)) {
        if (!it.tv && it.same && byPath[it.same]) it = Object.assign({}, it, { tv: byPath[it.same] });
        const sig = { type: 'sig', name: flatText(it.name), depth, anc, width: 1, enum: it.enum, radix: it.radix || it.fmt, style: it.style, path: it.path,
          src: it,
          stroke: it.stroke || (typeof it.color === 'string' && !/^[2-9]$/.test(it.color) ? it.color : undefined), fill: it.fill, enumColors: it.enumColors,
            analog: it.analog,
          kind: it.kind, height: num(it.height) || undefined };
        if (it.lazy) sig.lazy = true;   // a large dump read as it is needed: its changes come later (fillRows)
        sig.full = it.path || anc.map(id => M.groups[id].name).concat(sig.name).join('.');
        const r = it.tv ? parseTV(it, sig) : parseWave(it, C);
        if (!it.tv && num(it.width) > 1) sig.width = num(it.width);   // a clock-sampled bus: its width (signed search, analog, fields)
        sig.tr = r.tr; sig.gaps = r.gaps;
        if (r.end != null) { cyc = Math.max(cyc, r.end); sig.end = C(r.end); }
        if (sig.tr.length) { if (it.tv) tmin = Math.min(tmin, sig.tr[0].t); tmax = Math.max(tmax, sig.tr[sig.tr.length - 1].t); }
        if (it.node && !it.tv) {
          const per = num(it.period) || 1, ph = num(it.phase) || 0;
          [...String(it.node)].forEach((ch, i) => { if (ch !== '.') M.nodes[ch] = { t: C(i * per - ph), row: sig }; });
        }
        if (Array.isArray(it.fields) && it.fields.length && sig.width > 1) {   // a packed struct: a group of its fields, the whole value on its row
          const g = { type: 'group', name: sig.name, depth, anc, id: gid++, path: sig.full, full: sig.full, kind: 'struct', sig };
          M.groups[g.id] = g; M.rows.push(g);
          for (const f of it.fields) { const fr = fieldRow(sig, f, depth + 1, anc.concat(g.id)); if (fr) M.rows.push(fr); }
          g.last = M.rows.length - 1;
        } else M.rows.push(sig);
      } else M.rows.push({ type: 'space', name: it && it.name ? flatText(it.name) : '', depth, anc });
    }
  };
  walk(j.signal, 0, []);
  // extension "scopes": {group path: "struct" | "union" | "interface"} (vcd2wavedrom.py from the dump's scope types): the
  // group says so; a struct's (union's) row carries its whole value, its fields put together in their order (MSB first)
  const kinds = j.scopes || {};   // a value: "struct" or {kind, width} (its width in the dump: a whole value only from every bit)
  for (const g of Object.values(M.groups)) { const k = kinds[g.path]; if (!g.kind && k) { g.kind = typeof k === 'string' ? k : k.kind;
    if (k.width) g.bits = num(k.width); } }
  const done = new Set(), whole = g => {
    if (done.has(g) || g.sig) return g.sig; done.add(g);
    if (g.kind !== 'struct' && g.kind !== 'union') return null;
    const parts = structParts(M, g, whole);
    const w = parts.reduce((n, p) => n + (p.width || 1), 0);
    if (g.kind === 'struct' && parts.length && (!g.bits || w === g.bits)) g.sig = joinBits(g, parts);
    else if (g.kind === 'struct' && parts.length) g.partial = [w, g.bits];   // some fields not shown: no whole value
    return g.sig;
  };
  Object.values(M.groups).forEach(whole);
  M.edges = (j.edge || []).map(parseEdge).filter(Boolean);
  M.t0 = Math.min(C(0), tmin); // like stock WaveDrom, a positive phase is clipped at cycle 0
  M.t1 = Math.max(C(cyc), tm && tm.t1 != null ? num(tm.t1) : -Infinity, isFinite(tmax) ? tmax : -Infinity);
  if (!(M.t1 > M.t0)) M.t1 = M.t0 + (tm ? num(tm.cycle) || 1 : 1);
  M.cycle = tm ? num(tm.cycle) || (M.t1 - M.t0) / 40 : 1;
  const mt = m => m.cycle != null ? C(num(m.cycle)) : num(parseT(m.t));
  M.markers = (j.markers || []).map(m => ({ t: mt(m), label: m.label || '' }));
  M.jumps = j.jumps ? j.jumps.map(m => ({ t: mt(m), span: num(parseT(m.span)) || (M.t1 - M.t0) / 5, label: m.label || '' })) : null;
  M.cursor = j.cursor != null ? num(parseT(j.cursor)) : null;
  M.bookmarks = bmNorm(j.bookmarks); M.arrows = arNorm(j.arrows, j.bookmarks); M.spans = spanNorm(j.spans);
  return M;
}
// lazy rows (a large dump read as it is needed, "lazy": the id codes of a signal not read yet): the WaveJSON signals read
// later (their path, their tv) onto their rows, the fields of a vector and a struct's whole value made again -> the rows
function fillRows(M, sigs) {
  const by = new Map(sigs.filter(s => s && s.path && s.tv).map(s => [s.path, s])), got = new Set();
  for (const r of M.rows) {
    if (r.type !== 'sig' || !r.lazy || r.field) continue;
    const s = by.get(r.path); if (!s) continue;
    const w = r.width; r.src.tv = s.tv; r.tr = parseTV(r.src, r).tr; r.width = w; r.lazy = false; got.add(r);
  }
  if (!got.size) return [];
  for (const r of M.rows) if (r.field && got.has(r.of)) { const f = fieldRow(r.of, r.src, r.depth, r.anc); if (f) r.tr = f.tr; }
  // a struct of the dump's scopes (the innermost first): its whole value once every part has its changes
  for (const g of Object.values(M.groups).sort((a, b) => b.depth - a.depth)) {
    if (!g.sig || !g.sig.struct) continue;
    const kids = M.rows.slice(M.rows.indexOf(g) + 1, g.last + 1);
    if (!kids.some(r => got.has(r)) || kids.some(r => r.lazy)) continue;
    g.sig.tr = joinBits(g, structParts(M, g)).tr;
  }
  return [...got];
}
// the rows a row on the screen needs read (lazy): itself, the vector of a field, every signal of a struct
const lazyOf = (M, r) => (r.type === 'sig' ? (r.lazy ? [r] : r.field && r.of && r.of.lazy ? [r.of] : []) :
  r.type === 'group' && r.sig && r.sig.struct ? M.rows.slice(M.rows.indexOf(r) + 1, r.last + 1).filter(q => q.lazy) : []);
// template.html's dump format ({ t0, t1, signals: [{ name, w, t: [[ps, value]] }] }) -> WaveJSON with the time extension
function fromTV(wave, extra = {}) {
  return Object.assign({ signal: wave.signals.map(s => ({ name: s.name, width: s.w, tv: s.t })),
    time: { t0: wave.t0, t1: wave.t1, cycle: (wave.t1 - wave.t0) / 40 } }, extra);
}

/* ---------------- edge search & bookmarks ---------------- */
// kind: any | rise | fall | value (the signal becomes `want`) | xz (an x or z value, a bus with x / z bits too). A bus has
// no direction: every value change counts.
const EDGE_KINDS = { any: '↕ edge', rise: '↑ rise', fall: '↓ fall', value: '= value', xz: '✕ X / Z' };
// a value to search for: 0x40 'h40 8'h40 64 -3 0b101 'b101 'o17, else a text (an enum label, an ASCII string) -> {n: BigInt
// | null, neg, text}
function parseWant(str) {
  const s = String(str ?? '').trim(); if (!s) return null;
  const q = /^(\d*)'([bh])([0-9a-fxz_]+)$/i.exec(s), d = q && q[3].replace(/_/g, '').toLowerCase();   // 'b10x1, 8'hx5: the exact bits, x and z apart
  if (q && /[xz]/.test(d) && (q[2].toLowerCase() === 'h' || /^[01xz]+$/.test(d))) {
    let b = q[2].toLowerCase() === 'b' ? d : [...d].map(c => (/[xz]/.test(c) ? c.repeat(4) : parseInt(c, 16).toString(2).padStart(4, '0'))).join('');
    const n = +q[1]; if (n) b = b.length >= n ? b.slice(b.length - n) : b.padStart(n, /[xz]/.test(b[0]) ? b[0] : '0');   // 4'bx1: xxx1, then 0s to the bus
    return { n: null, neg: false, text: s, bits: b, sized: !!n };
  }
  const m = /^(-)?(?:\d*'s?([hdbo])|0([xbo]))?([0-9a-f_]+)$/i.exec(s);
  if (m && !(m[2] || m[3] ? false : /[a-f]/i.test(m[4]))) {
    const base = { h: 16, x: 16, d: 10, b: 2, o: 8 }[(m[2] || m[3] || 'd').toLowerCase()], digits = m[4].replace(/_/g, '');
    try { const n = [...digits.toLowerCase()].reduce((acc, ch) => acc * BigInt(base) + BigInt(parseInt(ch, base)), 0n);
      if (!digits.split('').some(ch => isNaN(parseInt(ch, base)))) return { n, neg: !!m[1], text: s }; } catch (e) { /* a text */ }
  }
  return { n: null, neg: false, text: s.replace(/^"|"$/g, '') };
}
function valueIs(s, o, want, radix) {   // transition o of signal s holds the value searched for
  if (want && want.bits) { const w = s.width || 1, b = want.bits, e = !want.sized && /[xz]/.test(b[0]) ? b[0] : '0';   // a four-state literal: bit for bit
    return bitsOf(o, w) === (b.length >= w ? b.slice(b.length - w) : b.padStart(w, e)); }
  if (!want || o.k === 'x' || o.k === 'z') return false;
  if (want.n != null) {
    const w = BigInt(s.width || 1), n = want.neg ? ((1n << w) - want.n) & ((1n << w) - 1n) : want.n;   // -3: two's complement in the signal's width
    if (o.k === '0' || o.k === '1') return n === BigInt(o.k);
    if (o.raw != null && !/[xz]/i.test(o.raw)) return BigInt('0x' + (o.raw || '0')) === n;
  }
  const t = want.text.toLowerCase(), v = String(o.k === '=' ? vtext(s, o, radix) : o.k).toLowerCase();
  return v === t || v === '"' + t + '"' || (o.v != null && String(o.v).toLowerCase() === t);
}
const isXZ = o => o.k === 'x' || o.k === 'z' || o.bad || (o.raw != null && /[xz]/i.test(o.raw));
function edgeOk(s, a, i, kind, want, radix) {
  if (kind === 'value') return valueIs(s, a[i], want, radix) && (i === 0 || !valueIs(s, a[i - 1], want, radix));   // becomes it
  if (kind === 'xz') return isXZ(a[i]) && (i === 0 || !isXZ(a[i - 1]));
  if (i <= 0) return false;
  if (kind === 'any' || s.width > 1 || a[i].k === '=') return true;
  return kind === 'rise' ? a[i].k === '1' && a[i - 1].k !== '1' : a[i].k === '0' && a[i - 1].k !== '0';
}
function findEdge(s, t, dir, kind, want, radix) { // time of the next (dir 1) / previous (-1) edge of s strictly after / before t, or null
  const a = s.tr, eps = timeEps(t);
  if (dir > 0) { for (let i = lastLE(a, t + eps) + 1; i < a.length; i++) if (edgeOk(s, a, i, kind, want, radix)) return a[i].t; }
  else for (let i = lastLE(a, t - eps); i >= 0; i--) if (a[i].t < t - eps && edgeOk(s, a, i, kind, want, radix)) return a[i].t;
  return null;
}
function edgeGlyph(s, t) { // ↑ / ↓ / value of the transition of s exactly at t ('' if there is none)
  if (!s) return '';
  const a = s.tr, i = lastLE(a, t + timeEps(t)), o = a[i];
  if (!o || i === 0 || Math.abs(o.t - t) > timeEps(t)) return '';
  return o.k === '=' ? '= ' + o.v : o.k === '1' ? '↑' : o.k === '0' ? '↓' : o.k;
}
// a clock by its name: a 1-bit *clk* / *clock* that toggles; the times it rises (cached per row)
const isClkRow = r => r.type === 'sig' && r.width === 1 && r.tr && r.tr.length > 4 && /clk|clock/i.test(r.name);
const RISES = new WeakMap();
const riseTimes = clk => RISES.get(clk) || (RISES.set(clk, clk.tr.filter(o => o.k === '1').map(o => o.t)), RISES.get(clk));
// the cycles of a clock (its rising edges ups): the index of cycle 0, the first edge at or after zero (null: the first edge);
// the cycle at t, the last edge at or before t (negative before cycle 0); the time of cycle n, or null past the ends
// the setting cycleZero: a time ("50ns", as gapIdle and the cursor take it) or model units; null / "": the first edge
const zeroTime = z => (z == null || z === '' ? null : typeof z === 'number' ? z : num(parseT(z)));
const cycZero = (ups, zero) => (zero == null || !isFinite(zero) ? 0 : lastBefore(ups.length, j => ups[j], zero - timeEps(zero), true) + 1);
const cycAt = (ups, iz, t) => lastBefore(ups.length, j => ups[j], t + timeEps(t)) - iz;
// the rising edges the cycles count: a dump's first value 1 ("tv") is its level at the start, not an edge (a wave's p is one)
const cycUps = clk => ((clk.tv || clk.fromTv) && clk.tr[0] && clk.tr[0].k === '1' ? riseTimes(clk).slice(1) : riseTimes(clk));
// the clock of the cycles: a path exactly, else a name (gapRefs); none given: a 1-bit *clk* / *clock* with rising edges
const cycClock = (rows, name) => (name ? rows.find(r => r.type === 'sig' && r.tr && r.full === name) || gapRefs(rows, name)[0] || null :
  rows.find(r => isClkRow(r) && cycUps(r).length) || rows.find(r => r.type === 'sig' && r.width === 1 && r.tr && /clk|clock/i.test(r.name) &&
    cycUps(r).length) || null);
// the ticks and numbers of a cycles band: the edges in [from, to] at x (X), a tick when 3 px from the last one, a number
// every k-th cycle (1 2 5 10 …) where its text (at x + 3, at least xL + 2) fits after the last one's (its width + 6 px)
// -> { ticks: [x], labels: [[x, text]] }
function cycMarks(o, measure) {
  const ups = o.ups, a = Math.max(0, lastBefore(ups.length, j => ups[j], o.from)), b = lastBefore(ups.length, j => ups[j], o.to), ticks = [], labels = [];
  if (b < 0) return { ticks, labels };
  const px = b > a ? (o.X(ups[b]) - o.X(ups[a])) / (b - a) : Infinity;
  let k = 1; for (let m = 1, j = 0; k * px < 44 && m < 1e15;) { j = (j + 1) % 3; if (!j) m *= 10; k = [1, 2, 5][j] * m; }
  if (px >= 3) { let last = -Infinity; for (let i = a; i <= b; i++) { const x = o.X(ups[i]); if (x - last >= 3) { ticks.push(x); last = x; } } }
  let end = -Infinity;
  for (let i = a + (((o.iz - a) % k) + k) % k; i <= b; i += k) {
    const x = o.X(ups[i]), t = String(i - o.iz), w = measure(t), tx = Math.max(x + 3, (o.xL || 0) + 2);
    if (tx >= end && x + 3 < o.xR) { labels.push([x, t]); end = tx + w + 6; }
  }
  return { ticks, labels };
}
const cycTime = (ups, iz, n) => (Number.isInteger(n) && iz + n >= 0 && iz + n < ups.length ? ups[iz + n] : null);
// gaps in a figure (settings gaps, gapIdle, gapKeep): where nothing changes in [p, q] for idle or longer (p, q: the changes
// and the ends a, b of the range, ts their sorted times), the stretch from keep after p to keep before q is left out, min
// long at least; its ends on the rising edges ups (sorted, if any): the cycle of p and keep more kept, keep before the cycle
// of q -> the parts kept, [[from, to], …] ([[a, b]]: no gap)
function idleCuts(ts, a, b, idle, keep, ups = [], min = 0) {
  const out = [], pts = [a, ...ts.filter(t => t > a && t < b), b];
  let from = a;
  for (let i = 1; i < pts.length; i++) {
    const p = pts[i - 1], q = pts[i];
    if (!(q - p >= idle)) continue;
    let hs = p + keep, he = q - keep;
    if (ups.length) { const j = lastBefore(ups.length, k => ups[k], hs) + 1, k = lastBefore(ups.length, k => ups[k], he);
      hs = j < ups.length ? ups[j] : Infinity; he = k >= 0 ? ups[k] : -Infinity; }
    if (he - hs > 0 && he - hs >= min && hs > from) { out.push([from, hs]); from = he; }
  }
  out.push([from, b]);
  return out;
}
// a gap's length: clock cycles (a number, "16") or a time ("2us"; model units when the waves have no time)
const gapLen = (v, cyc) => (/^\s*[\d.]+(e[-+]?\d+)?\s*$/i.test(String(v ?? '')) ? +v * cyc : parseT(v));
// the signals the gaps follow (setting gapSignals: full paths, names or * patterns; none: []), one row per path (the first);
// the clock they count cycles of (gapClock): gapRefs(rows, gapClock)[0]
function gapRefs(rows, list) {
  const ps = prefixes(list), rx = ps.filter(p => p.includes('*')).map(glob), at = new Set(ps.filter(p => !p.includes('*'))), seen = new Set();
  return ps.length ? rows.filter(r => r.type === 'sig' && r.tr && (at.has(r.full) || at.has(r.name) || rx.some(x => x.test(r.full))) &&
    !seen.has(r.full) && seen.add(r.full)) : [];
}
// a signal in a gap [p, q): its rising edges (kind "rise"), falling ("fall"), both ("edges"), or changes ("any"; a bus: its
// changes) -> "12↑", "3↓", "12↑ 11↓", "5↕", "4×"; '' for none
function gapText(s, p, q, kind) {
  const a = s.tr, i0 = lastBefore(a.length, j => a[j].t, p, true) + 1, i1 = lastBefore(a.length, j => a[j].t, q, true), bus = s.width > 1 ||
    (a.length > 0 && (a[0].k === '=' || a[a.length - 1].k === '='));
  if (kind === 'edges' && !bus) return [gapText(s, p, q, 'rise'), gapText(s, p, q, 'fall')].filter(Boolean).join(' ');
  let n = 0;
  if (bus || kind === 'any' || kind === 'edges') n = Math.max(0, i1 - Math.max(i0, 1) + 1);   // the first value is no change
  else for (let i = Math.max(i0, 1); i <= i1; i++) if (kind === 'rise' ? a[i].k === '1' && a[i - 1].k !== '1' : a[i].k === '0' && a[i - 1].k !== '0') n++;
  return n ? n + (bus ? '×' : kind === 'any' ? '↕' : kind === 'rise' ? '↑' : '↓') : '';
}
// the parts of [a, b] a figure of these rows keeps (S: gaps, gapIdle, gapKeep): the changes of their signals but clk's
// (and the other clocks', unless the rows were picked: picked), and the times of also (bookmarks), counted; the lengths in
// cycles of clk (the step of its rising edges in the range), else of the model's cycle; a gap at least two cycles long
function gapCuts(rows, a, b, S, clk, cycle = 1, also = [], picked = false) {
  if (!S.gaps || !(b > a)) return [[a, b]];
  const ups = clk ? riseTimes(clk) : [], u = ups.filter(t => t >= a && t <= b), d = u.slice(1).map((t, i) => t - u[i]).sort((x, y) => x - y);
  const cyc = d.length ? d[d.length >> 1] : cycle, idle = gapLen(S.gapIdle, cyc), keep = Math.max(0, gapLen(S.gapKeep, cyc) || 0);
  if (!(idle > 0)) return [[a, b]];
  const ts = new Set(also.filter(t => t > a && t < b));
  for (const r of rows) {
    const s = r.type === 'group' ? r.sig : r;
    if (!s || !s.tr || !s.tr.length || s === clk || (!picked && isClkRow(s))) continue;
    for (let i = lastLE(s.tr, a) + 1; i < s.tr.length && s.tr[i].t < b; i++) if (s.tr[i].t > a) ts.add(s.tr[i].t);
  }
  return idleCuts([...ts].sort((x, y) => x - y), a, b, idle, keep, d.length ? ups : [], d.length ? 2 * cyc : 0);
}
// extension "bookmarks": [{n, t, at, signal (full path), text, color, top (the row at the top of the waves when it was made:
// a signal's full path or a module's path; going to it puts that row there again)}] and "arrows": [{from, to, shape, head, line, color, label}]
// (from / to = bookmark numbers). An old bookmark with "to" / "shape" / "label" becomes an arrow.
const AR_SHAPES = { '~': 'curve', '-': 'straight', '-~': 'curve, late', '~-': 'curve, early', '-|': 'corner ┐', '|-': 'corner └', '-|-': 'step' };
const AR_HEADS = { '>': '→ end', '<>': '↔ both', '<': '← start', '': '— none' };
const AR_LINES = { solid: null, dashed: [6, 4], dotted: [1.5, 3] };
function bmNorm(list) {
  const obj = x => x && typeof x === 'object';   // an entry that is no object (a bad copy in this browser): left out
  // lift: false, true (the lane above its signal) or "below" (the lane under it); label: a short text by the circle (an
  // old bookmark with "to": the arrow's)
  return (Array.isArray(list) ? list : []).filter(obj).map((b, i) => Object.assign({ n: +b.n || i + 1, t: num(parseT(b.t)), signal: b.signal || null,
    text: b.text || '', label: (b.to == null || b.to === '') && b.label != null ? String(b.label) : '', color: b.color || null,
    lift: b.signal ? liftOf(b.lift) : false, top: typeof b.top === 'string' && b.top ? b.top : null },
    b.at != null && (typeof b.at === 'string' || obj(b.at)) ? { at: b.at } : {},   // at: the event its time came from (mkhtml.py); moved, it goes
    linkOf(b.link) ? { link: linkOf(b.link) } : {}))   // link: another view of the page ({view, bookmark}) its button opens
    .filter(b => isFinite(b.t));
}
const liftOf = x => (x === 'below' ? 'below' : x === 'above' || !!x);   // "above" is true
// a bookmark's link: "crc" (the section of that view) or {view: "crc", bookmark: 3} (its viewer goes to that bookmark)
const linkOf = x => (typeof x === 'string' && x ? { view: x } : x && typeof x === 'object' && typeof x.view === 'string' && x.view ?
  Object.assign({ view: x.view }, +x.bookmark > 0 ? { bookmark: +x.bookmark } : {}) : null);
// extension "spans": [{from, to, label, color, signals}] coloured stretches of time, over every row or the rows of
// "signals" (full paths or names): the page's (mkhtml.py resolves their ends) and yours (the span command)
function spanNorm(list) {
  return (Array.isArray(list) ? list : []).filter(s => s && typeof s === 'object').map(s => {
    const a = num(parseT(s.from)), b = num(parseT(s.to));
    return { from: Math.min(a, b), to: Math.max(a, b), label: s.label != null ? String(s.label) : '', color: s.color || null,
      signals: Array.isArray(s.signals) ? s.signals.map(String) : typeof s.signals === 'string' && s.signals ? [s.signals] : null };
  }).filter(s => isFinite(s.from) && isFinite(s.to));
}
function arNorm(list, bms) {
  const old = (Array.isArray(bms) ? bms : []).map((b, i) => b && b.to != null && b.to !== '' ? { from: +b.n || i + 1, to: +b.to, shape: b.shape,
    label: b.label } : null);
  // a shape, head or line of no table of its own ("constructor", a typo): the default one
  return old.filter(Boolean).concat(Array.isArray(list) ? list.filter(a => a && typeof a === 'object') : []).map(a => ({ from: +a.from, to: +a.to,
    shape: hasKey(AR_SHAPES, a.shape) ? a.shape : '~', head: hasKey(AR_HEADS, a.head) ? a.head : '>', line: hasKey(AR_LINES, a.line) ? a.line : 'solid',
    color: a.color || null, label: a.label || '' }))
    .filter(a => a.from && a.to && a.from !== a.to);
}
// your markers [{t, label, color}] (a saved state, this browser) and groups [{name, signals: [full path], color}]: normalised
function markNorm(list) {
  return (Array.isArray(list) ? list : []).map(m => ({ t: num(parseT(m && m.t)), label: m && m.label != null ? String(m.label) : '',
    color: (m && m.color) || null })).filter(m => isFinite(m.t));
}
function groupNorm(list) {
  const seen = new Set();
  return (Array.isArray(list) ? list : []).filter(g => g && String(g.name ?? '').trim() && !seen.has(String(g.name).trim()) && seen.add(String(g.name).trim()))
    .map(g => Object.assign({ name: String(g.name).trim(), signals: [...new Set(prefixes(g.signals))], color: g.color || null }, g.uid ? { uid: g.uid } : {}));
}
