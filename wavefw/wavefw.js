/* wavefw.js — WaveDrom-format waveform framework: parser, interactive canvas viewer (WaveView), static SVG (WaveSVG).
   No dependencies, no build step, works from file://. See README.md for the supported WaveDrom subset and extensions. */
(function (G) {
'use strict';

/* ---------------- tokens & helpers ---------------- */
// Colour names used by the painters -> CSS custom properties (defined in wavefw.css, overridable by the page).
const TOK = { fg: '--fg', muted: '--muted', line: '--line', panel: '--panel', panel2: '--panel-2', acc: '--accent',
  one: '--wave-1', bus: '--wave-bus', x: '--wave-x', xsoft: '--wave-x-soft', z: '--wave-z',
  c3: '--wave-c3', c4: '--wave-c4', c5: '--wave-c5', c6: '--wave-c6', c7: '--wave-c7', c8: '--wave-c8', c9: '--wave-c9',
  hl1: '--wave-hl1', hl2: '--wave-hl2', hl3: '--wave-hl3', hl4: '--wave-hl4', hl5: '--wave-hl5', hl6: '--wave-hl6', hl7: '--accent' };   // hl7: find
// Friendly names for colour maps (config.colors, data-colors, WaveFW.setColors) -> CSS custom properties.
const CVAR = { trace: '--wave-1', one: '--wave-1', bus: '--wave-bus', x: '--wave-x', xfill: '--wave-x-soft', z: '--wave-z',
  bg: '--panel', panel: '--panel', header: '--panel-2', grid: '--line', text: '--fg', muted: '--muted', accent: '--accent', cursor: '--accent',
  page: '--bg', c3: '--wave-c3', c4: '--wave-c4', c5: '--wave-c5', c6: '--wave-c6', c7: '--wave-c7', c8: '--wave-c8', c9: '--wave-c9',
  hl1: '--wave-hl1', hl2: '--wave-hl2', hl3: '--wave-hl3', hl4: '--wave-hl4', hl5: '--wave-hl5', hl6: '--wave-hl6' };
const THEMES = ['light', 'white', 'dark'];
const ENUMS = {};   // global enum registry: signal name -> { value: label }, like decode() in template.html
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const num = v => (typeof v === 'number' ? v : parseFloat(v));
function lastLE(a, t) { // binary search: index of the last transition with time <= t (-1 if none)
  let lo = 0, hi = a.length - 1, ans = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (a[m].t <= t) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans;
}
const flatText = t => Array.isArray(t) ? t.slice(typeof t[1] === 'object' && !Array.isArray(t[1]) ? 2 : 1).map(flatText).join('') : (t == null ? '' : String(t));

/* ---------------- settings (config file / WaveFW.configure / config in the JSON / data-* / opts) ---------------- */
// Layers, later wins: DEFAULTS < global (window.WAVEFW_CONFIG, WaveFW.configure) < WaveJSON "config" < element / opts.
// theme and colors are not merged here: they become data-theme / CSS custom properties (see applyLook).
const DEFAULTS = { rowHeight: 26, groupHeight: 22, spaceHeight: 14, headerHeight: 24, traceWidth: 1.4, busWidth: 1.2,
  labelSize: 11, fontSize: 11.5, sort: 'none', sortIgnore: [], sortButton: true, hint: true, style: 'auto', radix: 'auto', fold: null,
  highlight: null, dim: 0.3, groupColors: null, arrowLabels: 'lane', laneHeight: 16, maxHeight: null,
  groupOrder: 'file', moduleShading: true, findHighlight: true, findOpen: true };
const SVG_DEFAULTS = { groupHeight: 20, spaceHeight: 12 };   // the static figure is a little denser
const GLOBAL = {};
// settings that live in CSS (so the names column, fonts and static SVG text follow them too); numbers are px
const STYLE_VAR = { nameWidth: '--wv-names', fontSize: '--wv-font-size', fontMono: '--font-mono', fontBody: '--font-body', maxHeight: '--wv-max-h' };
const prefixes = v => (Array.isArray(v) ? v : String(v ?? '').split(',')).map(s => String(s).trim()).filter(Boolean);
function settings(...layers) {
  const S = Object.assign({}, DEFAULTS);
  for (const l of layers) for (const [k, v] of Object.entries(l || {})) if (v != null && k !== 'theme' && k !== 'colors') S[k] = v;
  for (const k of ['rowHeight', 'groupHeight', 'spaceHeight', 'headerHeight', 'traceWidth', 'busWidth', 'labelSize', 'fontSize', 'dim', 'laneHeight']) S[k] = num(S[k]) || DEFAULTS[k];
  S.sort = sortDir(S.sort); S.sortIgnore = prefixes(S.sortIgnore).sort((a, b) => b.length - a.length);
  if (!EDGES[S.style]) S.style = 'auto';
  if (S.groupsFirst && S.groupOrder === 'file') S.groupOrder = 'first';   // older setting
  return S;
}
const styleVars = cfg => Object.entries(STYLE_VAR).filter(([k]) => cfg && cfg[k] != null && cfg[k] !== '')
  .map(([k, name]) => [name, typeof cfg[k] === 'number' ? cfg[k] + 'px' : String(cfg[k])]);
// edge styles ("style" setting or per signal): slope = px of a slanted 1-bit edge (null: WaveDrom wave strings slanted,
// exact "tv" transitions vertical), bevel = px of the bus "<>" ends. questa/square = vertical edges like a simulator viewer.
const EDGES = { auto: { slope: null, bevel: 3 }, wavedrom: { slope: 2.5, bevel: 3 }, questa: { slope: 0, bevel: 1.5 }, square: { slope: 0, bevel: 0 } };
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
function hlPick(M, list) {
  const picks = new Map();
  prefixes(list).forEach((p, i) => {
    const rx = p.includes('*') ? glob(p) : null;
    for (const r of M.rows) if (r.type !== 'space' && !picks.has(r) && (rx ? rx.test(r.full) : r.full === p || r.name === p)) picks.set(r, i % HL_N);
  });
  return picks;
}
// picks -> { cover: Map(row -> colour) for picked rows and members of picked groups, on: rows drawn in front, dim }
function hlState(M, picks, dim) {
  if (!picks || !picks.size) return null;
  const cover = new Map(), on = new Set();
  for (const r of M.rows) {
    let c = picks.get(r);
    for (let i = r.anc.length - 1; c === undefined && i >= 0; i--) c = picks.get(M.groups[r.anc[i]]);
    if (c !== undefined) { cover.set(r, c); on.add(r); r.anc.forEach(id => on.add(M.groups[id])); }   // keep their group headers too
  }
  return { cover, on, dim };
}

/* ---------------- group colours: every signal of a group in one colour (AXI channels, modules …) ---------------- */
// "groupColors" setting {group: colour}: group = full path, name or "*" pattern; the nearest matching group wins. Its
// signals take the colour (trace, bus outline, name) unless they have their own "color" / "stroke"; the group's name too.
function groupPaint(M, map) {
  const list = Object.entries(map || {}).map(([p, c]) => [p.includes('*') ? glob(p) : p, c]);
  const of = g => { for (const [p, c] of list) if (typeof p === 'string' ? g.full === p || g.name === p : p.test(g.full)) return c; };
  for (const r of M.rows) {
    if (r.type === 'space' || r.type === 'lane') continue;
    if (!('own' in r)) r.own = r.stroke;
    let c = r.type === 'group' ? of(r) : undefined;
    for (let i = r.anc.length - 1; c === undefined && i >= 0; i--) c = of(M.groups[r.anc[i]]);
    const v = r.own ?? c;
    if ('stroke0' in r) r.stroke0 = v ?? null; else r.stroke = v;   // painted by find: the paint stays on top
  }
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

/* ---------------- fuzzy find (fzf-like): the letters of the query in order, anywhere in the name ---------------- */
// -> null or { score, idx: matched positions }; consecutive letters and word starts (after . _ [ /) score higher
function fuzzy(q, s) {
  const t = s.toLowerCase(), idx = [];
  let j = 0, score = 0, prev = -2;
  q = q.toLowerCase();
  for (let i = 0; i < t.length && j < q.length; i++) {
    if (t[i] !== q[j]) continue;
    score += (i === prev + 1 ? 6 : 1) + (i === 0 || '._[/ '.includes(t[i - 1]) ? 4 : 0);
    idx.push(i); prev = i; j++;
  }
  return j === q.length ? { score: score - t.length / 100, idx } : null;
}
// a row against the query words (all must match). A word "a.b" = "a" in the path of the modules above the row and "b"
// in its name (fzf over paths): "dev.fifo_s" = a fifo_s… signal somewhere below a …dev… module.
function findRow(r, terms) {
  const name = r.name, full = r.full || name, scope = full.length > name.length ? full.slice(0, full.length - name.length - 1) : '';
  let score = 0; const idx = [];
  for (const w of terms) {
    const k = w.lastIndexOf('.'), sq = k < 0 ? '' : w.slice(0, k), nq = k < 0 ? w : w.slice(k + 1);
    const ms = sq ? fuzzy(sq.replace(/\./g, ''), scope) : { score: 0 }, mn = nq ? fuzzy(nq, name) : { score: 0, idx: [] };
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
const RADIX = ['auto', 'hex', 'dec', 'signed', 'bin', 'oct', 'ascii'];
function decode(sig, v, radix) {
  if (v === undefined) return '?';
  if (/[xz]/i.test(v)) return v;
  const e = sig.enum || ENUMS[sig.name];
  if (e) { const n = parseInt(v, 16); if (e[n] !== undefined) return e[n]; }
  const big = () => BigInt('0x' + (v || '0')), w = sig.width || 1;
  const r = sig.radix || radix;
  switch ({ unsigned: 'dec', sdec: 'signed' }[r] || r) {
    case 'dec': return big().toString();
    case 'signed': { const n = big(), m = 1n << BigInt(w); return String(w > 1 && n >= m >> 1n ? n - m : n); }
    case 'bin': return big().toString(2).padStart(w, '0');
    case 'oct': return '0o' + big().toString(8);
    case 'hex': return '0x' + v.toUpperCase();
    case 'ascii': return '"' + (v.length % 2 ? '0' + v : v).match(/../g).map(h => parseInt(h, 16)).filter((c, i, a) => c || i === a.length - 1)
      .map(c => (c >= 32 && c < 127 ? String.fromCharCode(c) : '.')).join('') + '"';
  }
  if (w <= 6) return String(parseInt(v, 16));
  return '0x' + v.toUpperCase();
}
// bus label of transition o with the radix in effect (re-decoded only when the radix changes)
const vtext = (s, o, radix) => o.raw == null ? o.v : (s.radix || radix || 'auto') === o.rk ? o.vr : (o.rk = s.radix || radix || 'auto', o.vr = decode(s, o.raw, o.rk));

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
    else push(c0, { k: '=', v: data[di++] ?? '', c: ch === '=' ? 2 : +ch, s: false });
  }
  return { tr, gaps, end: wave.length * per - ph };
}
function parseTV(s, sig) { // extension: exact transitions [[time, value], …]; bit values 0/1/x/z, bus values hex
  const tv = s.tv || [];
  sig.width = num(s.width) || (tv.every(([, v]) => /^[01xz]$/i.test(String(v))) ? 1 : 8); sig.tv = true;
  const tr = [];
  for (const [t, v0] of tv) {
    const v = String(v0).toLowerCase(); let o;
    if (sig.width === 1) o = { k: v === '1' ? '1' : v === '0' ? '0' : v === 'z' ? 'z' : 'x' };
    else if (/^x+$/.test(v)) o = { k: 'x' };
    else if (/^z+$/.test(v)) o = { k: 'z' };
    else {
      const e = sig.enum || ENUMS[sig.name], n = parseInt(v, 16);
      o = { k: '=', raw: v, v: decode(sig, v), bad: /[xz]/.test(v),
        c: /^[2-9]$/.test(String(s.color)) ? +s.color : (e && !isNaN(n) ? 3 + (n % 7) : 2) };
    }
    const L = tr[tr.length - 1];
    if (L && L.k === o.k && L.raw === o.raw) continue;
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
  if (src && src.__wavefw) return src;
  const j = typeof src === 'string' ? parseText(src) : src;
  if (!j || !Array.isArray(j.signal)) throw new Error('WaveJSON needs a "signal" array');
  const tm = j.time || null, C = cycMap(tm);
  const M = { __wavefw: true, src: j, timed: !!tm, rows: [], groups: {}, nodes: {}, edges: [],
    title: flatText(j.head && j.head.text), foot: flatText(j.foot && j.foot.text),
    tick: j.head && j.head.tick != null ? num(j.head.tick) : null, every: (j.head && num(j.head.every)) || 1,
    tock: j.foot && j.foot.tock != null ? num(j.foot.tock) : null, hscale: (j.config && num(j.config.hscale)) || 1,
    theme: j.config && j.config.theme, colors: (j.config && j.config.colors) || null, cfg: j.config || {} };
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
        const sig = { type: 'sig', name: flatText(it.name), depth, anc, width: 1, enum: it.enum, radix: it.radix || it.fmt, style: it.style, path: it.path, src: it,
          stroke: it.stroke || (typeof it.color === 'string' && !/^[2-9]$/.test(it.color) ? it.color : undefined), fill: it.fill };
        sig.full = it.path || anc.map(id => M.groups[id].name).concat(sig.name).join('.');
        const r = it.tv ? parseTV(it, sig) : parseWave(it, C);
        sig.tr = r.tr; sig.gaps = r.gaps;
        if (r.end != null) { cyc = Math.max(cyc, r.end); sig.end = C(r.end); }
        if (sig.tr.length) { if (it.tv) tmin = Math.min(tmin, sig.tr[0].t); tmax = Math.max(tmax, sig.tr[sig.tr.length - 1].t); }
        if (it.node && !it.tv) {
          const per = num(it.period) || 1, ph = num(it.phase) || 0;
          [...String(it.node)].forEach((ch, i) => { if (ch !== '.') M.nodes[ch] = { t: C(i * per - ph), row: sig }; });
        }
        M.rows.push(sig);
      } else M.rows.push({ type: 'space', name: it && it.name ? flatText(it.name) : '', depth, anc });
    }
  };
  walk(j.signal, 0, []);
  M.edges = (j.edge || []).map(parseEdge).filter(Boolean);
  M.t0 = Math.min(C(0), tmin); // like stock WaveDrom, a positive phase is clipped at cycle 0
  M.t1 = Math.max(C(cyc), tm && tm.t1 != null ? num(tm.t1) : -Infinity, isFinite(tmax) ? tmax : -Infinity);
  if (!(M.t1 > M.t0)) M.t1 = M.t0 + (tm ? num(tm.cycle) || 1 : 1);
  M.cycle = tm ? num(tm.cycle) || (M.t1 - M.t0) / 40 : 1;
  const mt = m => m.cycle != null ? C(num(m.cycle)) : num(parseT(m.t));
  M.markers = (j.markers || []).map(m => ({ t: mt(m), label: m.label || '' }));
  M.jumps = j.jumps ? j.jumps.map(m => ({ t: mt(m), span: num(parseT(m.span)) || (M.t1 - M.t0) / 5, label: m.label || '' })) : null;
  M.cursor = j.cursor != null ? num(parseT(j.cursor)) : null;
  M.bookmarks = bmNorm(j.bookmarks); M.arrows = arNorm(j.arrows, j.bookmarks);
  return M;
}
// template.html's dump format ({ t0, t1, signals: [{ name, w, t: [[ps, value]] }] }) -> WaveJSON with the time extension
function fromTV(wave, extra = {}) {
  return Object.assign({ signal: wave.signals.map(s => ({ name: s.name, width: s.w, tv: s.t })),
    time: { t0: wave.t0, t1: wave.t1, cycle: (wave.t1 - wave.t0) / 40 } }, extra);
}

/* ---------------- painters: one drawing routine, two back-ends ---------------- */
class CanvasPainter {
  constructor(g, cs, S) { this.g = g; this.cs = cs; this.S = S; this.cache = {}; this.fade = 1; this.mono = cs.getPropertyValue('--font-mono').trim() || 'monospace'; this.body = cs.getPropertyValue('--font-body').trim() || 'sans-serif'; }
  col(n) { return this.cache[n] || (this.cache[n] = TOK[n] ? this.cs.getPropertyValue(TOK[n]).trim() || '#888' : n); }
  path(cmds, st) {
    const g = this.g; g.beginPath();
    for (const c of cmds) {
      if (c[0] === 'M') g.moveTo(c[1], c[2]); else if (c[0] === 'L') g.lineTo(c[1], c[2]);
      else if (c[0] === 'C') g.bezierCurveTo(c[1], c[2], c[3], c[4], c[5], c[6]); else g.closePath();
    }
    g.globalAlpha = (st.alpha ?? 1) * this.fade;
    if (st.fill) { g.fillStyle = this.col(st.fill); g.fill(); }
    if (st.stroke) { g.strokeStyle = this.col(st.stroke); g.lineWidth = st.w || 1; g.setLineDash(st.dash || []); g.stroke(); g.setLineDash([]); }
    g.globalAlpha = 1;
  }
  rect(x, y, w, h, fill, alpha = 1) { const g = this.g; g.globalAlpha = alpha * this.fade; g.fillStyle = this.col(fill); g.fillRect(x, y, w, h); g.globalAlpha = 1; }
  font(st) { return `${st.weight || 400} ${st.size || 11}px ${st.body ? this.body : this.mono}`; }
  text(x, y, s, st = {}) {
    const g = this.g; g.font = this.font(st); g.fillStyle = this.col(st.fill || 'fg');
    g.textAlign = { start: 'left', middle: 'center', end: 'right' }[st.anchor || 'start']; g.textBaseline = 'middle';
    g.globalAlpha = this.fade; g.fillText(s, x, y); g.globalAlpha = 1;
  }
  measure(s, st = {}) { this.g.font = this.font(st); return this.g.measureText(s).width; }
  clip(x, y, w, h, fn) { const g = this.g; g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip(); fn(); g.restore(); }
}
let clipId = 0, measureCtx = null;
class SvgPainter {
  constructor(S) {
    this.out = []; this.S = S; this.fade = 1;
    const cs = getComputedStyle(document.documentElement);
    this.monoF = S.fontMono || cs.getPropertyValue('--font-mono').trim() || 'monospace'; this.bodyF = S.fontBody || cs.getPropertyValue('--font-body').trim() || 'sans-serif';
    measureCtx = measureCtx || document.createElement('canvas').getContext('2d');
  }
  col(n) { return !n ? 'none' : TOK[n] ? `var(${TOK[n]})` : esc(n); }
  path(cmds, st) {
    const f = v => Math.round(v * 100) / 100;
    const d = cmds.map(c => c[0] + c.slice(1).map(f).join(' ')).join('');
    let css = `fill:${st.fill ? this.col(st.fill) : 'none'}`;
    if (st.stroke) css += `;stroke:${this.col(st.stroke)};stroke-width:${st.w || 1}` + (st.dash ? `;stroke-dasharray:${st.dash.join(' ')}` : '');
    const op = (st.alpha ?? 1) * this.fade;
    if (op !== 1) css += `;opacity:${op}`;
    this.out.push(`<path d="${d}" style="${css}"/>`);
  }
  rect(x, y, w, h, fill, alpha = 1) { const op = alpha * this.fade; this.out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" style="fill:${this.col(fill)}${op !== 1 ? ';opacity:' + op : ''}"/>`); }
  text(x, y, s, st = {}) {
    this.out.push(`<text x="${Math.round(x * 100) / 100}" y="${Math.round(y * 100) / 100}" dominant-baseline="central" text-anchor="${st.anchor || 'start'}" style="font-family:var(${st.body ? '--font-body' : '--font-mono'});font-size:${st.size || 11}px;font-weight:${st.weight || 400};fill:${this.col(st.fill || 'fg')}${this.fade !== 1 ? ';opacity:' + this.fade : ''}">${esc(s)}</text>`);
  }
  measure(s, st = {}) { measureCtx.font = `${st.weight || 400} ${st.size || 11}px ${st.body ? this.bodyF : this.monoF}`; return measureCtx.measureText(s).width; }
  clip(x, y, w, h, fn) { const id = 'wvfclip' + (++clipId); this.out.push(`<clipPath id="${id}"><rect x="${x}" y="${y}" width="${w}" height="${h}"/></clipPath><g clip-path="url(#${id})">`); fn(); this.out.push('</g>'); }
}

/* ---------------- shared drawing ---------------- */
function arrowHead(P, x, y, fx, fy, fill) { // filled arrow with its tip at (x, y), coming from (fx, fy)
  let dx = x - fx, dy = y - fy; const L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
  P.path([['M', x, y], ['L', x - 7 * dx + 3 * dy, y - 7 * dy - 3 * dx], ['L', x - 7 * dx - 3 * dy, y - 7 * dy + 3 * dx], ['Z']], { fill });
}
function paintSig(P, s, y, h, X, tA, tB, xL, xR, tEnd) {
  const a = s.tr; if (!a.length) return;
  const yh = y + 4, yl = y + h - 5, ym = (yh + yl) / 2;
  const cl = x => Math.min(Math.max(x, xL - 8), xR + 8);
  let lv = null, lvDash = null, pk = null, py = ym, pw = Infinity, xe = 0;
  const trace = s.stroke || 'one', S = P.S, lab = { anchor: 'middle', size: S.labelSize };
  const E = EDGES[s.style] || EDGES[S.style] || EDGES.auto, slope = E.slope ?? (s.tv ? 0 : 2.5);
  const flush = x => { if (lv) { lv.push(['L', cl(x), py]); P.path(lv, { stroke: trace, w: S.traceWidth, dash: lvDash }); lv = null; } };
  for (let i = Math.max(lastLE(a, tA), 0); i < a.length && a[i].t <= tB; i++) {
    const o = a[i], xs = X(o.t);
    // burst: transitions less than 1 px apart (a clock or busy bus far zoomed out) -> one solid bar, not thousands of edges
    if (i + 2 < a.length && X(a[i + 1].t) - xs < 1 && X(a[i + 2].t) - X(a[i + 1].t) < 1) {
      let j = i + 2;
      while (j + 1 < a.length && a[j + 1].t <= tB && X(a[j + 1].t) - X(a[j].t) < 1) j++;
      const x0 = cl(xs), x1 = cl(X(a[j].t)), bit = s.width === 1 && o.k !== '=';
      flush(xs);
      P.path([['M', x0, yh], ['L', x1, yh], ['L', x1, yl], ['L', x0, yl], ['Z']], { fill: bit ? trace : s.stroke || 'bus', alpha: bit ? 0.85 : 0.55 });
      pk = null; pw = 1; i = j - 1; continue;
    }
    xe = X(i + 1 < a.length ? a[i + 1].t : (s.end ?? tEnd));
    const w = xe - xs, sl = o.s ? 0 : Math.max(0, Math.min(slope, w / 3, pw / 3));
    if (o.k === '0' || o.k === '1' || o.k === 'u' || o.k === 'd') {
      const yv = (o.k === '1' || o.k === 'u') ? yh : yl, dash = (o.k === 'u' || o.k === 'd') ? [3, 2] : null;
      if (lv && String(dash) !== String(lvDash)) flush(xs - sl);
      if (!lv) {
        lvDash = dash;
        lv = pk === 'L' ? [['M', cl(xs - sl), py], ['L', cl(xs + sl), yv]] : pk ? [['M', cl(xs), ym], ['L', cl(xs + sl), yv]] : [['M', cl(xs), yv]];
      } else if (py !== yv) lv.push(['L', cl(xs - sl), py], ['L', cl(xs + sl), yv]);
      if (o.a && pk === 'L' && py !== yv) arrowHead(P, xs, yv < py ? ym - 4 : ym + 4, xs, yv < py ? ym + 4 : ym - 4, trace);
      pk = 'L'; py = yv;
    } else {
      flush(xs);
      if (o.k === 'z') P.path([['M', cl(xs), ym], ['L', cl(xe), ym]], { stroke: s.stroke || 'z', w: S.traceWidth });
      else if (w < 2) P.path([['M', xs, yh], ['L', xs, yl]], { stroke: o.k === 'x' || o.bad ? 'x' : s.stroke || 'bus', w: 1 });
      else {
        const sb = Math.min(E.bevel, w / 2), x0 = cl(xs), x1 = cl(xe);
        const hex = [['M', x0, ym], ['L', x0 + sb, yh], ['L', x1 - sb, yh], ['L', x1, ym], ['L', x1 - sb, yl], ['L', x0 + sb, yl], ['Z']];
        const isx = o.k === 'x';
        P.path(hex, { fill: isx ? 'xsoft' : s.fill || (o.c >= 3 && o.c <= 9 ? 'c' + o.c : 'panel') });
        if (isx && w > 4) P.clip(x0 + sb, yh, x1 - x0 - 2 * sb, yl - yh, () => {
          const hh = yl - yh, d = []; for (let x = x0 - hh; x < x1; x += 6) d.push(['M', x, yl], ['L', x + hh, yh]);
          P.path(d, { stroke: 'x', w: 0.8, alpha: 0.7 });
        });
        P.path(hex, { stroke: isx || o.bad ? 'x' : s.stroke || 'bus', w: S.busWidth });
        if (o.k === '=' && o.v !== '') {
          const vx0 = Math.max(x0, xL), vx1 = Math.min(x1, xR);
          if (vx1 - vx0 > 14) { const t = vtext(s, o, S.radix), tw = P.measure(t, lab); if (vx1 - vx0 > tw + 8) P.text((vx0 + vx1) / 2, ym, t, lab); }
        }
      }
      pk = o.k; py = ym;
    }
    pw = w;
  }
  flush(xe);
  for (const g of s.gaps) { // WaveDrom '|' gap mark: a slanted break through the row
    if (g < tA || g > tB) continue;
    const x = X(g), y0 = y + 2, y1 = y + h - 2;
    P.path([['M', x - 5, y1], ['L', x - 1, y0], ['L', x + 3, y0], ['L', x - 1, y1], ['Z']], { fill: 'panel' });
    P.path([['M', x - 5, y1], ['L', x - 1, y0], ['M', x - 1, y1], ['L', x + 3, y0]], { stroke: 'one', w: 1 });
  }
}
function paintAxis(P, o) { // o: { from, span, xL, xR, y, h, yEnd, X, timed, tick, every, cycles }
  const W = o.xR - o.xL;
  P.rect(o.xL, o.y, W, o.h, 'panel2');
  const step = o.step || (o.timed ? niceStep(90 * o.span / W) : Math.max(niceStep(60 * o.span / W, true), o.every || 1));
  const first = Math.ceil(o.from / step) * step, d = [], lab = [];
  for (let t = first; t <= o.from + o.span + 1e-9; t += step) {
    const x = o.X(t); d.push(['M', x, o.y + o.h - 6], ['L', x, o.yEnd]);
    lab.push([x, o.timed ? fmtTime(t, step) : String(Math.round((t + (o.tick || 0)) * 100) / 100)]);
  }
  P.path(d, { stroke: 'line', w: 1, alpha: 0.6 });
  for (const [x, s] of lab) { // keep edge labels inside the axis band
    const hw = P.measure(s, { size: 10.5 }) / 2 + 2;
    P.text(Math.min(Math.max(x, o.xL + hw), o.xR - hw), o.y + o.h / 2, s, { anchor: 'middle', size: 10.5, fill: 'muted' });
  }
}
function edgeGeom(e, x1, y1, x2, y2) { // WaveDrom edge shapes -> path, label point, arrow "from" points
  const dx = x2 - x1, dy = y2 - y1;
  switch (e.shape) {
    case '~': return { d: [['M', x1, y1], ['C', x1 + 0.7 * dx, y1, x1 + 0.3 * dx, y2, x2, y2]], m: [x1 + dx / 2, y1 + dy / 2], s: [x1 + 0.7 * dx, y1], e: [x1 + 0.3 * dx, y2] };
    case '-~': return { d: [['M', x1, y1], ['C', x1 + 0.7 * dx, y1, x2, y2, x2, y2]], m: [x1 + 0.66 * dx, y1 + 0.3 * dy], s: [x1 + 0.7 * dx, y1], e: [x1 + 0.7 * dx, y1] };
    case '~-': return { d: [['M', x1, y1], ['C', x1, y1, x1 + 0.3 * dx, y2, x2, y2]], m: [x1 + 0.34 * dx, y1 + 0.7 * dy], s: [x1 + 0.3 * dx, y2], e: [x1 + 0.3 * dx, y2] };
    case '-|': return { d: [['M', x1, y1], ['L', x2, y1], ['L', x2, y2]], m: [x1 + dx / 2, y1], s: [x2, y1], e: [x2, y1] };
    case '|-': return { d: [['M', x1, y1], ['L', x1, y2], ['L', x2, y2]], m: [x1 + dx / 2, y2], s: [x1, y2], e: [x1, y2] };
    case '-|-': return { d: [['M', x1, y1], ['L', x1 + dx / 2, y1], ['L', x1 + dx / 2, y2], ['L', x2, y2]], m: [x1 + dx / 2, y1 + dy / 2], s: [x1 + dx / 2, y1], e: [x1 + dx / 2, y2] };
    default: return { d: [['M', x1, y1], ['L', x2, y2]], m: [x1 + dx / 2, y1 + dy / 2], s: [x2, y2], e: [x1, y1] };
  }
}
function paintEdges(P, M, rowY, X) {
  for (const e of M.edges) {
    const A = M.nodes[e.from], B = M.nodes[e.to];
    if (!A || !B || !rowY.has(A.row) || !rowY.has(B.row)) continue;
    const x1 = X(A.t), y1 = rowY.get(A.row), x2 = X(B.t), y2 = rowY.get(B.row), g = edgeGeom(e, x1, y1, x2, y2);
    P.path(g.d, { stroke: 'acc', w: 1.2 });
    const near = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5;
    if (e.ae) { const f = near(g.e, [x2, y2]) ? [x1, y1] : g.e; arrowHead(P, x2, y2, f[0], f[1], 'acc'); }
    if (e.as) { const f = near(g.s, [x1, y1]) ? [x2, y2] : g.s; arrowHead(P, x1, y1, f[0], f[1], 'acc'); }
    if (e.label) {
      const tw = P.measure(e.label, { size: 10.5 });
      P.rect(g.m[0] - tw / 2 - 3, g.m[1] - 7, tw + 6, 14, 'panel');
      P.text(g.m[0], g.m[1], e.label, { anchor: 'middle', size: 10.5, fill: 'acc', weight: 600 });
    }
  }
  for (const [ch, n] of Object.entries(M.nodes)) { // lowercase nodes are labelled, as in stock WaveDrom
    if (!/^[a-z]$/.test(ch) || !rowY.has(n.row)) continue;
    const x = X(n.t), y = rowY.get(n.row);
    P.rect(x - 4, y - 6, 8, 12, 'panel'); P.text(x, y, ch, { anchor: 'middle', size: 10, fill: 'muted' });
  }
}
// rows (signals, group bands, separators), gaps, edges and markers inside [xL, xR]
function paintBody(P, M, lay, X, tA, tB, xL, xR, hl, sel, allLay, band) {   // allLay: every row (edges may end off screen)
  const rowY = new Map(), sep = [], edge = [];
  let pb;
  if (allLay) for (const o of allLay) if (o.row.type === 'sig') rowY.set(o.row, o.y + o.h / 2);
  for (const { row, y, h } of lay) {
    const c = hl ? hl.cover.get(row) : undefined;
    P.fade = hl && row.type !== 'lane' && !hl.on.has(row) ? hl.dim : 1;
    const b = band ? band.get(row) : undefined;
    if (b !== undefined) { if (pb !== undefined && b !== pb) edge.push(['M', xL, y + 0.5], ['L', xR, y + 0.5]); pb = b; }
    if (b === 1) P.rect(xL, y, xR - xL, h, 'panel2', 0.6);
    if (row.type === 'lane') { P.rect(xL, y, xR - xL, h, 'panel2', 0.45); continue; }
    if (row.type === 'group') { P.rect(xL, y, xR - xL, h, 'panel2'); P.rect(xL, y, xR - xL, h, 'fg', 0.08); edge.push(['M', xL, y + 0.5], ['L', xR, y + 0.5]); pb = undefined; }
    if (c !== undefined) P.rect(xL, y, xR - xL, h, 'hl' + (c + 1), 0.1);
    if (row === sel) P.rect(xL, y, xR - xL, h, 'acc', 0.08);
    if (row.type !== 'space') sep.push(['M', xL, y + h - 0.5], ['L', xR, y + h - 0.5]);
    if (row.type === 'sig') { paintSig(P, row, y, h, X, tA, tB, xL, xR, M.t1); rowY.set(row, y + h / 2); }
  }
  P.fade = 1;
  P.path(sep, { stroke: 'line', w: 1, alpha: 0.5 });
  P.path(edge, { stroke: 'line', w: 1 });   // module borders
  paintEdges(P, M, rowY, X);
  return rowY;
}
function paintMarkers(P, markers, X, tA, tB, y0, y1) {
  for (const m of markers) {
    if (m.t < tA || m.t > tB) continue;
    const x = X(m.t); P.path([['M', x, y0], ['L', x, y1]], { stroke: 'muted', w: 1, dash: [3, 3] });
    if (m.label) { P.rect(x + 1, y0 + 2, P.measure(m.label, { size: 10 }) + 4, 12, 'panel'); P.text(x + 3, y0 + 8, m.label, { size: 10, fill: 'muted' }); }
  }
}

/* ---------------- edge search & bookmarks ---------------- */
// kind: any | rise | fall. A bus has no direction: every value change counts.
const EDGE_KINDS = { any: '↕ edge', rise: '↑ rise', fall: '↓ fall' };
function edgeOk(s, a, i, kind) {
  if (i <= 0) return false;
  if (kind === 'any' || s.width > 1 || a[i].k === '=') return true;
  return kind === 'rise' ? a[i].k === '1' && a[i - 1].k !== '1' : a[i].k === '0' && a[i - 1].k !== '0';
}
function findEdge(s, t, dir, kind) { // time of the next (dir 1) / previous (-1) edge of s strictly after / before t, or null
  const a = s.tr, eps = 1e-9 * Math.max(1, Math.abs(t));
  if (dir > 0) { for (let i = lastLE(a, t + eps) + 1; i < a.length; i++) if (edgeOk(s, a, i, kind)) return a[i].t; }
  else for (let i = lastLE(a, t - eps); i >= 0; i--) if (a[i].t < t - eps && edgeOk(s, a, i, kind)) return a[i].t;
  return null;
}
function edgeGlyph(s, t) { // ↑ / ↓ / value of the transition of s exactly at t ('' if there is none)
  if (!s) return '';
  const a = s.tr, i = lastLE(a, t + 1e-9 * Math.max(1, Math.abs(t))), o = a[i];
  if (!o || i === 0 || Math.abs(o.t - t) > 1e-9 * Math.max(1, Math.abs(t))) return '';
  return o.k === '=' ? '= ' + o.v : o.k === '1' ? '↑' : o.k === '0' ? '↓' : o.k;
}
// extension "bookmarks": [{n, t, signal (full path), text, color}] and "arrows": [{from, to, shape, head, line, color, label}]
// (from / to = bookmark numbers). An old bookmark with "to" / "shape" / "label" becomes an arrow.
const AR_SHAPES = { '~': 'curve', '-': 'straight', '-~': 'curve, late', '~-': 'curve, early', '-|': 'corner ┐', '|-': 'corner └', '-|-': 'step' };
const AR_HEADS = { '>': '→ end', '<>': '↔ both', '<': '← start', '': '— none' };
const AR_LINES = { solid: null, dashed: [6, 4], dotted: [1.5, 3] };
function bmNorm(list) {
  return (Array.isArray(list) ? list : []).map((b, i) => ({ n: +b.n || i + 1, t: num(parseT(b.t)), signal: b.signal || null, text: b.text || '',
    color: b.color || null })).filter(b => isFinite(b.t));
}
function arNorm(list, bms) {
  const old = (Array.isArray(bms) ? bms : []).map((b, i) => b && b.to != null && b.to !== '' ? { from: +b.n || i + 1, to: +b.to, shape: b.shape, label: b.label } : null);
  return old.filter(Boolean).concat(Array.isArray(list) ? list : []).map(a => ({ from: +a.from, to: +a.to, shape: AR_SHAPES[a.shape] ? a.shape : '~',
    head: AR_HEADS[a.head] !== undefined ? a.head : '>', line: a.line in AR_LINES ? a.line : 'solid', color: a.color || null, label: a.label || '' }))
    .filter(a => a.from && a.to && a.from !== a.to);
}
const circle = (x, y, r) => { const k = 0.5523 * r; return [['M', x - r, y], ['C', x - r, y - k, x - k, y - r, x, y - r], ['C', x + k, y - r, x + r, y - k, x + r, y],
  ['C', x + r, y + k, x + k, y + r, x, y + r], ['C', x - k, y + r, x - r, y + k, x - r, y], ['Z']]; };
// arrow labels in lanes: a thin row inserted under the upper end of a labelled arrow (above the row when both ends share
// it; the top when an end is on the time axis), so the text never covers a signal. -> Map(row index it follows -> [arrow index])
function arrowLanes(rows, bms, arrows) {
  const idx = new Map(), lanes = new Map(), has = n => bms.some(b => b.n === n);
  rows.forEach((r, i) => { if (r.type === 'sig') idx.set(r.full, i); });
  const rowOf = n => { const b = bms.find(x => x.n === n); return b && b.signal != null && idx.has(b.signal) ? idx.get(b.signal) : -1; };
  arrows.forEach((a, i) => {
    if (!a.label || !has(a.from) || !has(a.to)) return;
    const r1 = rowOf(a.from), r2 = rowOf(a.to), at = Math.max(-1, r1 === r2 ? r1 - 1 : Math.min(r1, r2));
    if (!lanes.has(at)) lanes.set(at, []);
    lanes.get(at).push(i);
  });
  return lanes;
}
function withLanes(rows, lanes) { // rows with {type: 'lane', ids: [arrow index]} rows spliced in
  const out = [], lane = i => { if (lanes.has(i)) out.push({ type: 'lane', ids: lanes.get(i), name: '', depth: 0, anc: [] }); };
  lane(-1); rows.forEach((r, i) => { out.push(r); lane(i); });
  return out;
}
// module shading: signal rows alternate between two backgrounds each time their module (enclosing group) changes, so
// the border between two modules' waves shows. -> Map(row -> 0 | 1); lanes and spacers take the band of the row before.
function bands(rows) {
  const out = new Map(); let band = 0, prev;
  for (const r of rows) {
    if (r.type === 'sig') { const k = r.anc.length ? r.anc[r.anc.length - 1] : -1; if (prev !== undefined && k !== prev) band ^= 1; prev = k; }
    if (r.type !== 'group') out.set(r, band);
  }
  return out;
}
const laneY = (lay, h) => { const m = new Map(); for (const o of lay) if (o.row.type === 'lane') o.row.ids.forEach((a, k) => m.set(a, o.y + h * k + h / 2)); return m; };
// numbered circles on their signal rows (on the axis when the row is not shown), guide lines, arrows between bookmarks;
// rubber: {from, x, y} = an arrow being drawn. Returns {pos: n -> [x, y], mids: [[arrow index, x, y]]} for hit tests.
function paintBookmarks(P, bms, arrows, X, tA, tB, rowY, y0, y1, yAxis, rubber, lanes) {
  const at = new Map(), pos = new Map(), mids = [];
  for (const [r, y] of rowY) at.set(r.full, y);
  for (const b of bms) pos.set(b.n, [X(b.t), b.signal != null && at.has(b.signal) ? at.get(b.signal) : yAxis]);
  for (const b of bms) if (b.t >= tA && b.t <= tB) { const x = X(b.t); P.path([['M', x, y0], ['L', x, y1]], { stroke: b.color || 'acc', w: 1, dash: [2, 3], alpha: 0.45 }); }
  const near = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5;
  const tip = (p, f) => { const L = Math.hypot(p[0] - f[0], p[1] - f[1]) || 1; return [p[0] - 9 * (p[0] - f[0]) / L, p[1] - 9 * (p[1] - f[1]) / L]; };   // on the circle
  arrows.forEach((a, i) => {
    const A = pos.get(a.from), B = pos.get(a.to); if (!A || !B) return;
    const g = edgeGeom({ shape: a.shape }, A[0], A[1], B[0], B[1]), col = a.color || 'acc';
    P.path(g.d, { stroke: col, w: 1.4, dash: AR_LINES[a.line] });
    if (a.head.includes('>')) { const f = near(g.e, B) ? A : g.e, p = tip(B, f); arrowHead(P, p[0], p[1], f[0], f[1], col); }
    if (a.head.includes('<')) { const f = near(g.s, A) ? B : g.s, p = tip(A, f); arrowHead(P, p[0], p[1], f[0], f[1], col); }
    const ly = lanes && lanes.get(i), m = ly != null ? [g.m[0], ly] : g.m;   // in its lane, else on the arrow
    if (a.label) {
      const tw = P.measure(a.label, { size: 10.5 });
      if (ly != null && Math.abs(g.m[1] - ly) > 9) P.path([['M', m[0], ly + (g.m[1] > ly ? 6 : -6)], ['L', g.m[0], g.m[1]]], { stroke: col, w: 1, dash: [1.5, 2.5], alpha: 0.7 });
      P.rect(m[0] - tw / 2 - 3, m[1] - 7, tw + 6, 14, 'panel'); P.text(m[0], m[1], a.label, { anchor: 'middle', size: 10.5, fill: col, weight: 600 });
    }
    mids.push([i, m[0], m[1]]);
  });
  const R = rubber && pos.get(rubber.from);
  if (R) { P.path([['M', R[0], R[1]], ['L', rubber.x, rubber.y]], { stroke: 'acc', w: 1.4, dash: [4, 3] }); arrowHead(P, rubber.x, rubber.y, R[0], R[1], 'acc'); }
  for (const b of bms) {
    if (b.t < tA || b.t > tB) continue;
    const [x, y] = pos.get(b.n);
    P.path(circle(x, y, 8), { fill: b.color || 'acc', stroke: 'panel', w: 1.5 });
    P.text(x, y + 0.5, String(b.n), { anchor: 'middle', size: b.n > 9 ? 9 : 10.5, weight: 700, fill: 'panel' });
  }
  return { pos, mids };
}

/* ---------------- interactive viewer ---------------- */
const VIEWS = new Set(), ACTIVE = { view: null };   // ACTIVE.view: the viewer used last (Esc while the focus is on the page)
class WaveView {
  constructor(root, model, opts = {}) {
    this.root = root; this.M = parse(model); this.opts = opts;
    const M = this.M;
    applyLook(root, opts.theme ?? M.theme, Object.assign({}, M.colors, opts.colors));
    this.restyle(false); this.collapsed = foldSet(M, this.S.fold);
    this.picks = hlPick(M, this.S.highlight); this.hlFrom = JSON.stringify(this.S.highlight ?? null);
    this.found = new Map(); this.findPicks = new Map(); this.findHl = this.S.findHighlight; this.findOpen = this.S.findOpen;   // fuzzy find
    this.paintKey = 'wavefw.paint:' + location.pathname + ':' + (opts.key || root.id || root.dataset.wave || M.title);
    this.painted = new Map(); this.loadPaint();
    this.t0 = M.t0; this.span = M.t1 - M.t0;
    this.minSpan = opts.minSpan ?? (M.timed ? Math.max(this.span / 1e6, 10) : 0.5);
    this.cursor = opts.cursor ?? M.cursor ?? M.t0;
    this.markers = (opts.markers || []).concat(M.markers);
    this.jumps = opts.jumps || M.jumps || (this.markers.length && this.markers.length <= 6
      ? this.markers.map(m => ({ label: '→ ' + m.label, t: m.t, span: this.span / 5 })) : []);
    this.sel = null; this.edgeKind = 'any';   // selected signal row (edge search, bookmarks), edge kind
    this.bmKey = 'wavefw.bookmarks:' + location.pathname + ':' + (opts.key || root.id || root.dataset.wave || M.title);
    Object.assign(this, this.loadBookmarks()); root.waveView = this;   // this.bms, this.arrows
    this.build(); this.fit();
    if (opts.from != null || opts.to != null) { // initial view window (Fit still shows everything)
      const a = opts.from ?? M.t0, b = opts.to ?? M.t1;
      this.span = Math.min(Math.max(b - a, this.minSpan), M.t1 - M.t0); this.t0 = this.clamp(a); this.draw();
    }
    this.ro = new ResizeObserver(() => this.draw()); this.ro.observe(this.wcol);
    // the canvas is only as tall as the visible part of the rows (sticky in its column): redraw when that part moves
    this.onScroll = () => { if (!this.raf && this.lay && this.lay.H > this.hc + 1) this.raf = requestAnimationFrame(() => { this.raf = 0; if (this.root.isConnected) this.draw(); }); };
    window.addEventListener('scroll', this.onScroll, { passive: true }); window.addEventListener('resize', this.onScroll);
    this.bodyEl.addEventListener('scroll', this.onScroll, { passive: true });
    VIEWS.add(this);
  }
  // settings from all layers; a global WaveFW.configure() calls this again on every viewer
  restyle(redraw = true) {
    const S = this.S = settings(GLOBAL, this.M.cfg, this.opts);
    groupPaint(this.M, S.groupColors);
    for (const [name, v] of styleVars(Object.assign({}, this.M.cfg, this.opts))) this.root.style.setProperty(name, v);
    this.rowH = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight }; this.hdrH = S.headerHeight;
    this.sort = S.sort; this.sortIgnore = S.sortIgnore;
    this.root.style.setProperty('--wv-dim', S.dim);
    this.root.classList.toggle('wv-scroll', S.maxHeight != null && S.maxHeight !== '');   // own scroll bar, bar stays in view
    const hlFrom = JSON.stringify(S.highlight ?? null);   // a new "highlight" setting (configure) replaces the picks
    if (redraw && hlFrom !== this.hlFrom) { this.hlFrom = hlFrom; this.picks = hlPick(this.M, S.highlight); }
    if (redraw && this.qEl && this.q) this.find(this.q);
    if (redraw) { const i = this.root.querySelector('input.pfx'); if (i) i.value = S.sortIgnore.join(','); this.fitPfx(); this.renderNames(); this.draw(); }
  }
  build() {
    const r = this.root, S = this.S, groups = Object.keys(this.M.groups).length > 0; r.classList.add('wv');
    const jumps = this.jumps.map((j, i) => `<button type="button" data-jump="${i}">${esc(j.label)}</button>`).join('');
    const sort = S.sortButton ? `<button type="button" data-act="sort" title="Sort signals by name (key: s)"></button><input type="text" class="pfx" spellcheck="false" size="8" value="${esc(this.sortIgnore.join(','))}" placeholder="i_,o_" title="Name prefixes ignored when sorting (comma-separated)" aria-label="prefixes ignored when sorting">` : '';
    const seg = (...parts) => `<span class="seg">${parts.join('')}</span>`, grp = (label, ...parts) => `<span class="tg"><span class="tl">${label}</span>${parts.join('')}</span>`;
    const find = grp('find',
      seg(`<input type="search" class="q" spellcheck="false" autocomplete="off" placeholder="find  /" aria-label="fuzzy find signals" title="Fuzzy find: the letters in order (pxvd finds s_pix_valid); a word with '.' searches full paths (dev.fifo); words separated by spaces must all match. Enter / n: next, shift+Enter / N: previous, Esc: reset">`,
        '<span class="cnt"></span><button type="button" data-act="fprev" title="Previous match (N, shift+Enter)">‹</button><button type="button" data-act="fnext" title="Next match (n, Enter)">›</button>'),
      seg(`<button type="button" data-act="fhl" aria-pressed="${!!S.findHighlight}" title="Found rows in front, the rest dimmed">Highlight</button>`, `<button type="button" data-act="fopen" aria-pressed="${!!S.findOpen}" title="Every module folded except the ones with a match">Open</button>`),
      seg('<input type="color" class="fcol" value="#d6336c" aria-label="paint colour" title="Colour for Paint">', '<button type="button" data-act="fpaint" title="Paint the found signals in this colour (kept in this browser)">Paint</button>'),
      `<button type="button" data-act="funpaint" title="Back to the signals' own colours" hidden>Unpaint</button><button type="button" data-act="fcopy" title="Copy the full paths of the found rows, one per line">Copy</button>`).replace('class="tg"', 'class="tg find"');
    // cursor: type a time (in the unit chosen, or with its own: 85.12us) and Set; a span and Show: the window around the cursor
    const units = this.M.timed ? `<select class="cu" aria-label="time unit" title="Unit of the two fields">${['ps', 'ns', 'µs', 'ms', 's'].map(u => `<option${u === this.unit() ? ' selected' : ''}>${u}</option>`).join('')}</select>` : '<span class="cyc">cyc</span>';
    const cursor = seg('<input type="text" class="ct" inputmode="decimal" spellcheck="false" aria-label="cursor time" title="Cursor time: a number in the unit shown, or with a unit (85.12us); Enter or Set">',
        units, '<button type="button" data-act="cset" title="Put the cursor at this time">Set</button>') +
      seg('<span class="lbl">span</span><input type="text" class="cs" inputmode="decimal" spellcheck="false" aria-label="view span" title="Width of the window; Enter or Show">',
        units.replace('class="cu"', 'class="su"'), '<button type="button" data-act="cshow" title="Window of this span centred on the cursor (key: c)">Show</button>');
    const list = grp('list', sort ? seg(sort) : '', groups ? seg('<button type="button" data-act="expand" title="Expand all groups">Expand</button>', '<button type="button" data-act="collapse" title="Collapse all groups">Collapse</button>') : '',
      '<button type="button" data-act="hl" title="Clear the highlight (Esc)" hidden></button>');
    const edges = grp('edges', seg('<button type="button" data-act="prev" title="Previous edge of the selected signal, or of any shown signal ([)">◀</button>',
      `<select class="edge" aria-label="edge kind" title="Edge kind (e)">${Object.entries(EDGE_KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>`,
      '<button type="button" data-act="next" title="Next edge (])">▶</button>'), '<button type="button" data-act="mark" title="Bookmark at the cursor, on the selected signal (m)">+ Mark</button>');
    r.innerHTML = `<div class="bar"><div class="head"><span class="eyebrow">${esc(this.opts.title || this.M.title || 'Waveform').replace(/µ/g, '<span class="mu">µ</span>')}</span><span class="toast" role="status" aria-live="polite"></span><span class="cur"></span></div>
      <div class="tools">${grp('cursor', cursor)}${grp('view', seg('<button type="button" data-act="out" title="Zoom out (−)">−</button>', '<button type="button" data-act="in" title="Zoom in (+)">+</button>', '<button type="button" data-act="fit" title="Show everything (0)">Fit</button>'))}${find}${list}${edges}${jumps ? grp('go to', jumps) : ''}</div></div>
      <div class="body"><div class="names"></div><div class="wcol"><canvas tabindex="0" aria-label="waveform canvas"></canvas></div></div>
      <div class="notes" hidden></div>
      ${S.hint ? `<div class="hint">Wheel: zoom · shift+wheel / drag: pan · click: cursor + select a signal · keys on the waves: + − 0 zoom · ← → pan · c window at the cursor · ↑ ↓ select · / find, n N next / previous match · [ ] edges, e edge kind · m bookmark${S.sortButton ? ' · s sort' : ''} · Esc reset${groups ? ' · click a module to fold it' : ''} · ○ or ctrl+click a name: highlight</div>` : ''}`;
    this.canvas = r.querySelector('canvas'); this.wcol = r.querySelector('.wcol'); this.bodyEl = r.querySelector('.body'); this.namesEl = r.querySelector('.names'); this.curEl = r.querySelector('.cur');
    this.sortBtn = r.querySelector('button[data-act=sort]'); this.hlBtn = r.querySelector('button[data-act=hl]');
    this.notesEl = r.querySelector('.notes'); this.edgeSel = r.querySelector('select.edge');
    this.ctEl = r.querySelector('input.ct'); this.csEl = r.querySelector('input.cs');
    this.cuEl = r.querySelector('select.cu'); this.suEl = r.querySelector('select.su');
    for (const [inp, fn] of [[this.ctEl, v => this.setCursor(v)], [this.csEl, v => this.showCursor(v)]])
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); fn(inp.value); } });
    for (const sel of [this.cuEl, this.suEl]) if (sel) sel.addEventListener('change', () => { this.syncCursorFields(true); });
    this.qEl = r.querySelector('input.q'); this.cntEl = r.querySelector('.find .cnt'); this.fcol = r.querySelector('input.fcol');
    this.unpaintBtn = r.querySelector('button[data-act=funpaint]'); this.unpaintBtn.hidden = !this.painted.size;
    let qt = 0;
    this.qEl.addEventListener('input', () => { cancelAnimationFrame(qt); qt = requestAnimationFrame(() => this.find(this.qEl.value)); });   // live, while typing
    this.qEl.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); this.findStep(e.shiftKey ? -1 : 1); }

    });
    this.edgeSel.addEventListener('change', () => { this.edgeKind = this.edgeSel.value; });
    r.querySelector('.bar').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.act === 'in') this.zoom(0.5, 0.5);
      else if (b.dataset.act === 'out') this.zoom(2, 0.5);
      else if (b.dataset.act === 'fit') this.fit();
      else if (b.dataset.act === 'sort') this.setSort(SORTS[(SORTS.indexOf(this.sort) + 1) % SORTS.length]);
      else if (b.dataset.act === 'hl') this.highlight(null);
      else if (b.dataset.act === 'expand') this.expandAll();
      else if (b.dataset.act === 'collapse') this.collapseAll();
      else if (b.dataset.act === 'prev' || b.dataset.act === 'next') this.edge(b.dataset.act === 'next' ? 1 : -1);
      else if (b.dataset.act === 'mark') this.mark();
      else if (b.dataset.act === 'fhl' || b.dataset.act === 'fopen') {
        const k = b.dataset.act === 'fhl' ? 'findHl' : 'findOpen'; this[k] = !this[k]; b.setAttribute('aria-pressed', this[k]); this.find(this.q || '', k === 'findOpen');
      }
      else if (b.dataset.act === 'fpaint') this.paint(this.fcol.value);
      else if (b.dataset.act === 'funpaint') this.unpaint();
      else if (b.dataset.act === 'cset') this.setCursor(this.ctEl.value);
      else if (b.dataset.act === 'cshow') this.showCursor(this.csEl.value);
      else if (b.dataset.act === 'fnext' || b.dataset.act === 'fprev') this.findStep(b.dataset.act === 'fnext' ? 1 : -1);
      else if (b.dataset.act === 'fcopy') this.copyRows(orderRows(this.M.rows, this.sort, this.sortIgnore, this.S.groupOrder).filter(r => this.found.has(r)));
      else if (b.dataset.jump !== undefined) { const j = this.jumps[b.dataset.jump]; this.goto(j.t, j.span); }
    });
    const pfx = r.querySelector('input.pfx');
    if (pfx) pfx.addEventListener('input', () => { this.fitPfx(); this.setSort(this.sort, pfx.value); });
    this.fitPfx();
    const toggle = el => { const id = +el.dataset.g; this.collapsed.has(id) ? this.collapsed.delete(id) : this.collapsed.add(id); this.renderNames(); this.draw(); };
    const rowOf = el => this.vis[+el.closest('.row').dataset.r];
    // copying from the names column gives the full paths of the selected rows, one per line (no values, no marks)
    this.namesEl.addEventListener('copy', e => {
      const s = getSelection(); if (!s || s.isCollapsed) return;
      const rows = [...this.namesEl.querySelectorAll('.row[data-r]')].filter(el => s.containsNode(el, true)).map(rowOf).filter(r => r && r.type !== 'space');
      if (!rows.length) return;
      e.preventDefault(); e.clipboardData.setData('text/plain', rows.map(r => r.full || r.name).join('\n')); this.toast(`copied ${rows.length}`);
    });
    this.namesEl.addEventListener('click', e => {
      const sel = getSelection(); if (sel && !sel.isCollapsed && this.namesEl.contains(sel.anchorNode)) return;   // selecting text to copy
      const row = e.target.closest('.row'); if (!row || row.classList.contains('space')) return;
      if (e.target.closest('.mk') || e.ctrlKey || e.metaKey) { this.toggleHighlight(rowOf(row)); this.canvas.focus({ preventScroll: true }); return; }   // mark / ctrl+click: highlight
      if (row.classList.contains('grp')) toggle(row);
      else { const s = rowOf(row); this.select(this.sel === s ? null : s); }   // a signal name: select it (again: unselect)
      this.canvas.focus({ preventScroll: true });   // the keys (Esc, arrows, n, m …) act on this viewer
    });
    this.namesEl.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const mk = e.target.closest('.mk'), g = e.target.closest('.grp');
      if (mk) { e.preventDefault(); this.toggleHighlight(rowOf(mk)); this.namesEl.querySelector(`.row[data-r="${mk.closest('.row').dataset.r}"] .mk`)?.focus(); }
      else if (g) { e.preventDefault(); toggle(g); }
    });
    const c = this.canvas;
    c.addEventListener('wheel', e => {
      e.preventDefault();
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) { this.t0 = this.clamp(this.t0 + this.span * 0.1 * Math.sign(e.deltaX || e.deltaY)); this.draw(); }
      else this.zoom(e.deltaY > 0 ? 1.25 : 0.8, this.frac(e));
    }, { passive: false });
    let drag = null;
    const local = e => { const b = c.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top + (this.oy || 0)]; };   // layout y
    // on a bookmark: drag moves it (time + signal row), shift+drag draws an arrow to another bookmark; elsewhere drag pans
    c.addEventListener('pointerdown', e => {
      const [x, y] = local(e), bm = this.bmAt(x, y);
      drag = { x: e.clientX, y: e.clientY, t0: this.t0, moved: false, bm, arrow: bm && e.shiftKey };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove', e => {
      const [x, y] = local(e);
      if (!drag) { const bm = this.bmAt(x, y); c.style.cursor = bm ? 'grab' : ''; c.title = bm ? `Bookmark ${bm.n}: drag to move it, shift+drag to another bookmark for an arrow` : ''; return; }
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.hypot(dx, dy) > 3) drag.moved = true;
      if (!drag.moved) return;
      if (drag.arrow) { this.rubber = { from: drag.bm.n, x, y }; this.draw(); }
      else if (drag.bm) { c.style.cursor = 'grabbing'; this.moveBookmark(drag.bm, x, y); }
      else { this.t0 = this.clamp(drag.t0 - dx / this.pxPerT()); this.draw(); }
    });
    c.addEventListener('pointerup', e => {
      const [x, y] = local(e);
      if (drag && drag.moved && drag.arrow) {
        const to = this.bmAt(x, y); this.rubber = null;
        if (to && to.n !== drag.bm.n) { this.arrows.push(arNorm([{ from: drag.bm.n, to: to.n }])[0]); this.saveBookmarks(); this.renderNotes(); }
        this.draw();
      } else if (drag && drag.moved && drag.bm) { c.style.cursor = 'grab'; this.saveBookmarks(); this.renderNotes(); }
      else if (drag && !drag.moved) {
        const hit = this.bmAt(x, y), mid = !hit && this.bmGeo && this.bmGeo.mids.find(([, mx, my]) => Math.hypot(mx - x, my - y) <= 10);
        if (hit) { this.cursor = hit.t; this.draw(); this.notesEl.querySelector(`li[data-n="${hit.n}"] input.txt`)?.focus(); }
        else if (mid) this.notesEl.querySelector(`li[data-a="${mid[0]}"] input.lab`)?.focus();
        else {   // cursor here; the signal row under the pointer becomes the selected one
          this.cursor = this.t0 + x / this.pxPerT();
          const row = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
          if (row && row.row.type === 'sig') this.sel = row.row;
          this.renderNames(); this.draw();
        }
      }
      drag = null;
    });
    c.addEventListener('pointercancel', () => { drag = null; if (this.rubber) { this.rubber = null; this.draw(); } });
    c.addEventListener('keydown', e => {
      const k = e.key; let h = true;
      if (k === '+' || k === '=') this.zoom(0.5, 0.5); else if (k === '-') this.zoom(2, 0.5); else if (k === '0') this.fit();
      else if (k === 's' && this.S.sortButton) this.setSort(SORTS[(SORTS.indexOf(this.sort) + 1) % SORTS.length]);
      else if (this.q && (k === 'c' || k === 'C') && (e.ctrlKey || e.metaKey)) this.clearFind();   // on the waves: ctrl+C ends the search
      else if (k === 'Escape') h = false;   // handled by the viewer (reset)
      else if (k === ']' || k === '[') this.edge(k === ']' ? 1 : -1);
      else if (k === 'e') { const ks = Object.keys(EDGE_KINDS); this.edgeKind = ks[(ks.indexOf(this.edgeKind) + 1) % ks.length]; this.edgeSel.value = this.edgeKind; }
      else if (k === 'm') this.mark();
      else if (k === '/') { this.qEl.focus(); this.qEl.select(); }
      else if (k === 'c' && !e.ctrlKey && !e.metaKey) this.showCursor();   // the window around the cursor
      else if ((k === 'n' || k === 'N') && !e.ctrlKey && !e.metaKey && this.found.size) this.findStep(k === 'n' ? 1 : -1);   // like vim
      else if ((k === 'c' || k === 'C') && (e.ctrlKey || e.metaKey)) {   // copy: the selected signal, else the highlighted rows
        const rows = this.sel ? [this.sel] : [...this.picks.keys()]; if (rows.length) this.copyRows(rows); else h = false;
      }
      else if (k === 'ArrowDown' || k === 'ArrowUp') {
        const sigs = this.vis.filter(r => r.type === 'sig'), i = sigs.indexOf(this.sel);
        this.select(sigs[Math.min(Math.max(i < 0 ? 0 : i + (k === 'ArrowDown' ? 1 : -1), 0), sigs.length - 1)] || null);
      }
      else if (k === 'ArrowLeft') { this.t0 = this.clamp(this.t0 - this.span * 0.2); this.draw(); }
      else if (k === 'ArrowRight') { this.t0 = this.clamp(this.t0 + this.span * 0.2); this.draw(); }
      else h = false;
      if (h) e.preventDefault();
    });
    // Esc anywhere in the viewer (waves, find field, names) except the bookmark fields: back to no search, no highlight,
    // no selected signal; the view (opened modules, scroll, time) stays
    r.addEventListener('pointerdown', () => { ACTIVE.view = this; }, true);
    r.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || e.target.closest('.notes')) return;
      e.preventDefault(); this.reset();
      if (e.target === this.qEl) this.canvas.focus({ preventScroll: true });
    });
    this.notesEl.addEventListener('click', e => this.noteClick(e));
    this.notesEl.addEventListener('input', e => this.noteInput(e));
    this.notesEl.addEventListener('change', e => this.noteChange(e));
    this.notesEl.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault(); this.canvas.focus({ preventScroll: true }); } });
    this.renderNames(); this.renderNotes();
  }
  fitPfx() { const i = this.root.querySelector('input.pfx'); if (i) i.style.width = Math.max(7, i.value.length + 2) + 'ch'; }
  visible() { return orderRows(this.M.rows, this.sort, this.sortIgnore, this.S.groupOrder).filter(r => !r.anc.some(id => this.collapsed.has(id))); }
  // dir: none | asc | desc; ignore: prefixes skipped when comparing names ("i_,o_" or an array)
  setSort(dir, ignore) {
    this.sort = sortDir(dir);
    if (ignore !== undefined) this.sortIgnore = prefixes(ignore).sort((a, b) => b.length - a.length);
    this.renderNames(); this.draw(); return this;
  }
  // highlight: list of full paths / names / "*" patterns (one colour each), or null to clear; returns the viewer
  highlight(list) { this.picks = hlPick(this.M, list); this.renderNames(); this.draw(); return this; }
  toggleHighlight(row) { // row: a model row, a full path or a name
    if (typeof row === 'string') row = this.M.rows.find(r => r.full === row) || this.M.rows.find(r => r.name === row);
    if (!row || row.type === 'space') return this;
    if (this.picks.has(row)) this.picks.delete(row);
    else { const used = new Set(this.picks.values()); let c = 0; while (used.has(c) && c < HL_N) c++; this.picks.set(row, c % HL_N); }
    this.renderNames(); this.draw(); return this;
  }
  highlighted() { return [...this.picks.keys()].map(r => r.full); }
  // fuzzy find: rows matching every word; options: found rows in front (findHl), only their modules open (findOpen)
  // restore: give back the folding from before the search (the Open option switched off); clearing the search keeps the
  // modules it opened, so the view stays where it is
  find(q, restore = false) {
    this.q = q;
    const terms = String(q || '').trim().split(/\s+/).filter(Boolean);
    this.found = new Map();
    if (terms.length) for (const r of this.M.rows) { if (r.type !== 'space') { const m = findRow(r, terms); if (m) this.found.set(r, m); } }
    if (terms.length && this.findOpen) {   // fold everything but the way to the matches
      if (!this.foldSaved) this.foldSaved = new Set(this.collapsed);
      const keep = new Set(); for (const r of this.found.keys()) r.anc.forEach(id => keep.add(id));
      this.collapsed = new Set(Object.keys(this.M.groups).map(Number).filter(id => !keep.has(id)));
    } else if (this.foldSaved) { if (restore) this.collapsed = this.foldSaved; this.foldSaved = null; }
    this.findPicks = terms.length && this.findHl ? new Map([...this.found.keys()].map(r => [r, 6])) : new Map();
    this.fi = -1;
    if (this.cntEl) { const n = this.found.size; this.cntEl.textContent = terms.length ? (n ? `${n} found` : 'no match') : ''; this.cntEl.classList.toggle('none', !!terms.length && !n); }
    this.renderNames(); this.draw(); return this;
  }
  reset() { // Esc: search, highlight and the selected signal go; folding, scroll and time stay
    if (this.qEl) this.qEl.value = '';
    this.picks = new Map(); this.sel = null;
    return this.find('');
  }
  unit() { // the unit the cursor fields start in: the one of a tenth of the whole span
    const ref = (this.M.t1 - this.M.t0) / 10, u = UNITS.find(([f]) => ref >= f) || UNITS[UNITS.length - 1];
    return u[1];
  }
  // "250" in the unit chosen (cycles for an untimed diagram), or "85.12us" with its own unit -> model time
  parseIn(v, sel) {
    v = String(v ?? '').trim();
    if (!v) return undefined;
    if (/^-?[\d.]+(e-?\d+)?$/i.test(v)) return parseFloat(v) * (this.M.timed && sel ? UNIT_PS[sel.value] : 1);
    return this.M.timed ? parseT(v) : undefined;
  }
  bad(inp) { inp.classList.add('bad'); setTimeout(() => inp.classList.remove('bad'), 900); }
  setCursor(v) { // cursor at a typed time; the view follows when it is outside
    const t = typeof v === 'number' ? v : this.parseIn(v, this.cuEl);
    if (t == null || !isFinite(t)) { this.bad(this.ctEl); return this; }
    this.cursor = Math.min(Math.max(t, this.M.t0), this.M.t1);
    if (this.cursor < this.t0 || this.cursor > this.t0 + this.span) this.t0 = this.clamp(this.cursor - this.span / 2);
    this.draw(); this.syncCursorFields(true); return this;
  }
  showCursor(v) { // window of a span (typed, else the current one) centred on the cursor
    const sp = v == null || v === '' ? this.span : typeof v === 'number' ? v : this.parseIn(v, this.suEl);
    if (sp == null || !isFinite(sp) || sp <= 0) { this.bad(this.csEl); return this; }
    this.span = Math.min(Math.max(sp, this.minSpan), this.M.t1 - this.M.t0);
    this.t0 = this.clamp(this.cursor - this.span / 2); this.draw(); this.syncCursorFields(true); return this;
  }
  syncCursorFields(force) { // the fields show the cursor and the span, except while one is being typed in
    if (!this.ctEl) return;
    const show = (inp, sel, t) => { if (force || document.activeElement !== inp) inp.value = String(Number((t / (this.M.timed && sel ? UNIT_PS[sel.value] : 1)).toPrecision(7))); };
    show(this.ctEl, this.cuEl, this.cursor); show(this.csEl, this.suEl, this.span);
  }
  clearFind() { // the search ends; the view stays where it left it (modules it opened, scroll, selection, time)
    if (this.qEl) this.qEl.value = '';
    return this.find('');
  }
  findStep(dir) { // Enter / shift+Enter: the next / previous match in display order (its modules are opened)
    const order = orderRows(this.M.rows, this.sort, this.sortIgnore, this.S.groupOrder).filter(r => this.found.has(r));
    if (!order.length) return this;
    this.fi = ((this.fi ?? -1) + dir + order.length) % order.length;
    const r = order[this.fi];
    r.anc.forEach(id => this.collapsed.delete(id));
    if (r.type === 'sig') this.select(r); else { this.renderNames(); this.draw(); }
    this.namesEl.querySelector(`.row[data-r="${this.vis.indexOf(r)}"]`)?.scrollIntoView({ block: 'nearest' });
    if (this.cntEl) this.cntEl.textContent = `${this.fi + 1} / ${order.length}`;
    return this;
  }
  copyRows(rows) { // full paths, one per line, to the clipboard
    const text = rows.map(r => r.full || r.name).join('\n'), done = () => this.toast(`copied ${rows.length}`);
    if (!rows.length) return this.toast('nothing to copy');
    const fallback = () => { const ta = document.createElement('textarea'); ta.value = text; ta.style.cssText = 'position:fixed;opacity:0;top:0';
      document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (e) { /* no clipboard */ } ta.remove(); this.canvas.focus({ preventScroll: true }); };
    try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
    this.copied = text; return this;
  }
  toast(msg) { const t = this.root.querySelector('.bar .toast'); if (!t) return; t.textContent = msg; clearTimeout(this.toastT); this.toastT = setTimeout(() => { t.textContent = ''; }, 1600); }
  paint(color) { // the found signals take this colour (trace, outline, name); kept in this browser
    for (const r of this.found.keys()) if (r.type === 'sig') { if (!('stroke0' in r)) r.stroke0 = r.stroke ?? null; r.stroke = color; this.painted.set(r.full, color); }
    this.savePaint(); this.renderNames(); this.draw(); return this;
  }
  unpaint() {
    for (const r of this.M.rows) if ('stroke0' in r) { r.stroke = r.stroke0 ?? undefined; delete r.stroke0; }
    this.painted.clear(); this.savePaint(); this.renderNames(); this.draw(); return this;
  }
  loadPaint() {
    try { const v = JSON.parse(localStorage.getItem(this.paintKey) || '{}'); for (const r of this.M.rows) if (r.type === 'sig' && v[r.full]) { r.stroke0 = r.stroke ?? null; r.stroke = v[r.full]; this.painted.set(r.full, v[r.full]); } }
    catch (e) { /* no storage */ }
  }
  savePaint() {
    try { if (this.painted.size) localStorage.setItem(this.paintKey, JSON.stringify(Object.fromEntries(this.painted))); else localStorage.removeItem(this.paintKey); } catch (e) { /* private mode */ }
    if (this.unpaintBtn) this.unpaintBtn.hidden = !this.painted.size;
  }
  expandAll() { this.collapsed = new Set(); this.renderNames(); this.draw(); return this; }
  collapseAll() { this.collapsed = new Set(Object.keys(this.M.groups).map(Number)); this.renderNames(); this.draw(); return this; }
  select(row) { // the signal for edge search and bookmarks: a row, a full path / name, or null
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row) || this.M.rows.find(r => r.type === 'sig' && r.name === row);
    this.sel = row && row.type === 'sig' ? row : null; this.renderNames(); this.draw();
    this.namesEl.querySelector('.row.sel')?.scrollIntoView({ block: 'nearest' });
    return this;
  }
  // cursor to the next (dir 1) / previous (-1) edge of the selected signal, or of any shown signal; the view follows
  edge(dir, kind = this.edgeKind) {
    let best = null;
    for (const s of this.sel ? [this.sel] : this.vis.filter(r => r.type === 'sig')) {
      const t = findEdge(s, this.cursor, dir, kind);
      if (t != null && (best == null || (dir > 0 ? t < best : t > best))) best = t;
    }
    if (best == null) return this;
    this.cursor = best;
    if (best < this.t0 || best > this.t0 + this.span) this.t0 = this.clamp(best - this.span / 2);
    this.draw(); return this;
  }
  // nearest edge of signal s within px pixels of t (the initial value is not an edge), else t
  snap(s, t, px = 6) {
    if (!s) return t;
    const tol = px / this.pxPerT(), i = lastLE(s.tr, t);
    const near = [i, i + 1].filter(k => k > 0 && k < s.tr.length && Math.abs(s.tr[k].t - t) <= tol).sort((a, b) => Math.abs(s.tr[a].t - t) - Math.abs(s.tr[b].t - t))[0];
    return near != null ? s.tr[near].t : t;
  }
  bmAt(x, y) { const pos = this.bmGeo && this.bmGeo.pos; return pos && this.bms.find(b => { const p = pos.get(b.n); return p && Math.hypot(p[0] - x, p[1] - y) <= 9; }); }
  // drag on the waves: time from x (snapped to an edge of the row), signal from the row under y (the time axis: no signal)
  moveBookmark(b, x, y) {
    const o = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
    if (y < (this.oy || 0) + this.hdrH) b.signal = null; else if (o && o.row.type === 'sig') b.signal = o.row.full;
    const s = b.signal != null ? this.M.rows.find(r => r.type === 'sig' && r.full === b.signal) : null;
    b.t = Math.min(Math.max(this.snap(s, this.t0 + x / this.pxPerT()), this.M.t0), this.M.t1);
    this.draw();
  }
  // bookmark: numbered circle at the cursor on the selected signal (snapped to its edge within 6 px), described below the waves
  mark(text = '') {
    const s = this.sel, t = this.cursor = this.snap(s, this.cursor);
    const n = Math.max(0, ...this.bms.map(b => b.n)) + 1;
    this.bms.push({ n, t, signal: s ? s.full : null, text, color: null });
    this.saveBookmarks(); this.renderNotes(); this.draw();
    if (!text) this.notesEl.querySelector(`li[data-n="${n}"] input.txt`)?.focus();
    return n;
  }
  arrow(from, to, opts = {}) { this.arrows.push(...arNorm([Object.assign({ from, to }, opts)])); this.saveBookmarks(); this.renderNotes(); this.draw(); return this; }
  // JSON for a config file / WaveJSON (t in model units: ps for timed waves, else cycles); defaults are left out
  bookmarks() { return this.bms.map(b => Object.fromEntries(Object.entries({ n: b.n, t: b.t, signal: b.signal, text: b.text, color: b.color }).filter(([, v]) => v != null && v !== ''))); }
  arrowList() {
    return this.arrows.map(a => Object.fromEntries(Object.entries({ from: a.from, to: a.to, shape: a.shape, head: a.head === '>' ? null : a.head, line: a.line === 'solid' ? null : a.line,
      color: a.color, label: a.label }).filter(([k, v]) => v != null && (v !== '' || k === 'head'))));   // head "" = no head
  }
  setBookmarks(list, arrows = []) { this.bms = bmNorm(list); this.arrows = arNorm(arrows, list); this.saveBookmarks(); this.renderNotes(); this.draw(); return this; }
  loadBookmarks() { // this browser's copy (localStorage) wins over the page's "bookmarks" / "arrows"
    try {
      const v = localStorage.getItem(this.bmKey);
      if (v != null) { const o = JSON.parse(v), list = Array.isArray(o) ? o : o.bookmarks; return { bms: bmNorm(list), arrows: arNorm(o.arrows, list) }; }
    } catch (e) { /* no storage: page bookmarks */ }
    return { bms: this.M.bookmarks.map(b => Object.assign({}, b)), arrows: this.M.arrows.map(a => Object.assign({}, a)) };
  }
  saveBookmarks() { try { localStorage.setItem(this.bmKey, JSON.stringify({ bookmarks: this.bookmarks(), arrows: this.arrowList() })); } catch (e) { /* private mode */ } }
  when(t) { return this.M.timed ? fmtTime(t, this.M.cycle / 100, t) : String(Math.round(t * 1000) / 1000); }
  // typed time: "250ns", "85.12us"; a plain number is in the unit shown (µs for "85.120 µs"), or cycles
  parseWhen(str, ref) {
    const v = String(str).trim().replace(/^cycle\s*/i, '');
    if (this.M.timed && /^-?[\d.]+(e-?\d+)?$/i.test(v)) return parseFloat(v) * (UNITS.find(([f]) => Math.abs(ref) >= f) || UNITS[UNITS.length - 1])[0];
    return parseT(v);
  }
  renderNotes() {
    const el = this.notesEl, M = this.M; el.hidden = !this.bms.length;
    if (!this.bms.length) { el.innerHTML = ''; return; }
    const sigs = M.rows.filter(r => r.type === 'sig'), byFull = new Map(sigs.map(r => [r.full, r]));
    const acc = getComputedStyle(this.root).getPropertyValue('--accent').trim(), hex = c => /^#[0-9a-f]{6}$/i.test(c || '') ? c : /^#[0-9a-f]{6}$/i.test(acc) ? acc : '#b5551b';
    const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
    const nums = cur => this.bms.map(o => opt(String(o.n), String(o.n), String(cur))).join('');
    el.innerHTML = `<div class="nh"><b>Bookmarks</b><span class="muted">click a number to go there · drag a circle on the waves to move it, shift+drag to another one for an arrow · kept in this browser</span>
      <button type="button" data-bm="json">JSON</button><button type="button" data-bm="clear" title="Remove the bookmarks of this browser (the page's own come back on reload)">Clear</button></div><ol class="bms">` +
      this.bms.map(b => { const s = byFull.get(b.signal);
        return `<li data-n="${b.n}"><button type="button" class="bn" data-bm="go" title="Go to bookmark ${b.n}"${b.color ? ` style="background:${esc(b.color)}"` : ''}>${b.n}</button>
        <input type="text" class="tm" value="${esc(this.when(b.t))}" spellcheck="false" aria-label="bookmark ${b.n} time" title="Time: 250ns, 85.12us, or a number in the unit shown">
        <button type="button" class="ic" data-bm="here" title="Move the bookmark to the cursor">cursor</button>
        <select class="sig" aria-label="bookmark ${b.n} signal" title="${esc(b.signal || 'time axis')}">${opt('', '— axis', b.signal || '')}${b.signal && !s ? opt(b.signal, b.signal, b.signal) : ''}${sigs.map(r => opt(r.full, r.full, b.signal)).join('')}</select>
        <span class="eg">${esc(edgeGlyph(s, b.t))}</span>
        <input type="color" class="col" value="${hex(b.color)}" aria-label="bookmark ${b.n} colour" title="Colour">
        <input type="text" class="txt" value="${esc(b.text)}" placeholder="describe the event" aria-label="bookmark ${b.n} text">
        <button type="button" class="ic" data-bm="del" title="Delete bookmark ${b.n} (and its arrows)">✕</button></li>`; }).join('') +
      `</ol><div class="nh"><b>Arrows</b><span class="muted">from → to · shape · head · line · colour · label</span><button type="button" data-bm="addar"${this.bms.length < 2 ? ' disabled' : ''}>+ Arrow</button></div><ol class="ars">` +
      this.arrows.map((a, i) => `<li data-a="${i}"><select class="from" aria-label="arrow ${i + 1} from">${nums(a.from)}</select>→<select class="to" aria-label="arrow ${i + 1} to">${nums(a.to)}</select>
        <select class="shape" aria-label="arrow shape">${Object.entries(AR_SHAPES).map(([k, v]) => opt(k, `${k}  ${v}`, a.shape)).join('')}</select>
        <select class="head" aria-label="arrow head">${Object.entries(AR_HEADS).map(([k, v]) => opt(k, v, a.head)).join('')}</select>
        <select class="line" aria-label="arrow line">${Object.keys(AR_LINES).map(k => opt(k, k, a.line)).join('')}</select>
        <input type="color" class="col" value="${hex(a.color)}" aria-label="arrow colour" title="Colour">
        <input type="text" class="lab" value="${esc(a.label)}" placeholder="label" aria-label="arrow label">
        <button type="button" class="ic" data-bm="adel" title="Delete this arrow">✕</button></li>`).join('') +
      '</ol><textarea class="json" readonly hidden aria-label="bookmarks as JSON"></textarea>';
  }
  changed(list) { this.saveBookmarks(); if (list) this.renderNotes(); this.draw(); }
  noteClick(e) {
    const b = e.target.closest('button[data-bm]'); if (!b) return;
    const li = b.closest('li'), n = li ? +li.dataset.n : NaN, bm = this.bms.find(x => x.n === n), act = b.dataset.bm;
    if (act === 'go' && bm) { this.cursor = bm.t; if (bm.t < this.t0 || bm.t > this.t0 + this.span) this.t0 = this.clamp(bm.t - this.span / 2); if (bm.signal) this.sel = this.M.rows.find(r => r.full === bm.signal) || this.sel; this.renderNames(); this.draw(); }
    else if (act === 'here' && bm) { bm.t = this.cursor; this.changed(true); }
    else if (act === 'del') { this.bms = this.bms.filter(x => x.n !== n); this.arrows = this.arrows.filter(a => a.from !== n && a.to !== n); this.changed(true); }
    else if (act === 'adel') { this.arrows.splice(+li.dataset.a, 1); this.changed(true); }
    else if (act === 'addar') { const k = this.bms.length; this.arrows.push(arNorm([{ from: this.bms[k - 2].n, to: this.bms[k - 1].n }])[0]); this.changed(true); }
    else if (act === 'clear') { this.bms = []; this.arrows = []; try { localStorage.removeItem(this.bmKey); } catch (err) { /* ignore */ } this.renderNotes(); this.draw(); }
    else if (act === 'json') {
      const ta = this.notesEl.querySelector('textarea.json'), rows = l => l.map(x => '  ' + JSON.stringify(x)).join(',\n');
      const txt = `"bookmarks": [\n${rows(this.bookmarks())}\n],\n"arrows": [\n${rows(this.arrowList())}\n]`;
      ta.hidden = !ta.hidden; ta.value = txt; ta.rows = this.bms.length + this.arrows.length + 5;
      if (!ta.hidden) { ta.select(); try { navigator.clipboard.writeText(txt).then(() => { b.textContent = 'JSON (copied)'; }, () => {}); } catch (err) { /* select only */ } }
    }
  }
  noteInput(e) { // text, colours, arrow settings: live
    const T = e.target, li = T.closest('li'); if (!li) return;
    if (li.dataset.a != null) {
      const a = this.arrows[+li.dataset.a]; if (!a) return;
      if (T.matches('select.from, select.to')) { a[T.className] = +T.value; }
      else if (T.matches('select.shape, select.head, select.line')) a[T.className] = T.value;
      else if (T.matches('input.col')) a.color = T.value;
      else if (T.matches('input.lab')) a.label = T.value;
      return this.changed(false);
    }
    const bm = this.bms.find(x => x.n === +li.dataset.n); if (!bm) return;
    if (T.matches('input.txt')) { bm.text = T.value; this.saveBookmarks(); }
    else if (T.matches('input.col')) { bm.color = T.value; li.querySelector('.bn').style.background = T.value; this.changed(false); }
  }
  noteChange(e) { // time and signal of a bookmark: on Enter / leaving the field
    const T = e.target, li = T.closest('li'), bm = li && this.bms.find(x => x.n === +li.dataset.n); if (!bm) return;
    if (T.matches('input.tm')) {
      const t = this.parseWhen(T.value, bm.t);
      if (t == null || !isFinite(t)) { T.value = this.when(bm.t); T.classList.add('bad'); setTimeout(() => T.classList.remove('bad'), 900); return; }
      bm.t = Math.min(Math.max(t, this.M.t0), this.M.t1);
      if (bm.t < this.t0 || bm.t > this.t0 + this.span) this.t0 = this.clamp(bm.t - this.span / 2);
      this.changed(true);
    } else if (T.matches('select.sig')) { bm.signal = T.value || null; this.changed(true); }
  }
  renderNames() {
    this.vis = this.visible(); this.vals = [];
    this.lanes = this.S.arrowLabels === 'lane' ? arrowLanes(this.vis, this.bms || [], this.arrows || []) : new Map();
    this.laneSig = JSON.stringify([...this.lanes]); this.rowsL = withLanes(this.vis, this.lanes);
    this.band = this.S.moduleShading && Object.keys(this.M.groups).length ? bands(this.rowsL) : null;
    const alt = r => this.band && this.band.get(r) === 1 ? ' alt' : '';
    const picks = this.findPicks && this.findPicks.size ? new Map([...this.findPicks, ...this.picks]) : this.picks;   // your own picks keep their colour
    const hl = this.hl = hlState(this.M, picks, this.S.dim);
    if (this.hlBtn) { this.hlBtn.hidden = !this.picks.size; this.hlBtn.textContent = `Highlight: ${this.picks.size} ✕`; }
    const mark = r => { const c = hl ? hl.cover.get(r) : undefined, own = this.picks.has(r);
      return [`${c !== undefined ? ' hl' : ''}${hl && !hl.on.has(r) ? ' dim' : ''}`, c !== undefined ? `--hl:${c === 6 ? 'var(--accent)' : `var(--wave-hl${c + 1})`};` : '',
        `<span class="mk" role="checkbox" tabindex="0" aria-checked="${own}" aria-label="highlight ${esc(r.full || r.name)}" title="${own ? 'Remove the highlight' : 'Highlight (the other rows dim; several at once)'}"></span>`]; };
    if (this.sortBtn) { this.sortBtn.textContent = 'Sort: ' + { none: 'off', asc: 'A→Z', desc: 'Z→A' }[this.sort]; this.sortBtn.setAttribute('aria-pressed', this.sort !== 'none'); }
    const pad = r => `padding-left:${17 + r.depth * 12}px`, sorted = this.sort !== 'none';
    const label = r => {
      const [p, rest] = sorted ? stripPfx(r.name, this.sortIgnore) : ['', r.name], m = this.found && this.found.get(r);
      const at = m ? new Set(m.idx) : null, txt = (s, off) => at ? [...s].map((ch, i) => at.has(off + i) ? `<b class="fm">${esc(ch)}</b>` : esc(ch)).join('') : esc(s);
      return (p ? `<span class="pfx">${txt(p, 0)}</span>` : '') + txt(rest, p.length);
    };
    let vi = -1;
    this.namesEl.innerHTML = `<div class="hdr" style="height:${this.hdrH}px"></div>` + this.rowsL.map(r => {
      if (r.type === 'lane') return `<div class="row lane${alt(r)}" style="height:${this.S.laneHeight * r.ids.length}px" title="arrow labels"></div>`;
      const h = this.rowH[r.type], i = ++vi;
      if (r.type === 'space') return `<div class="row space${alt(r)}${hl ? ' dim' : ''}" data-r="${i}" style="height:${h}px;${pad(r)}"><span class="n">${esc(r.name)}</span></div>`;
      const [cls, st, mk] = mark(r);
      if (r.type === 'group') { const open = !this.collapsed.has(r.id); return `<div class="row grp${cls}" data-r="${i}" style="height:${h}px;${st}${pad(r)}" data-g="${r.id}" tabindex="0" role="button" aria-expanded="${open}" title="${esc(r.path)}">${mk}<span class="n"${r.stroke ? ` style="color:${esc(r.stroke)}"` : ''}>${open ? '▾' : '▸'} ${label(r)}</span></div>`; }
      return `<div class="row${cls}${alt(r)}${r === this.sel ? ' sel' : ''}" data-r="${i}" style="height:${h}px;${st}${pad(r)}">${mk}<span class="n" title="${esc(r.full || r.name)}"${r.stroke ? ` style="color:${esc(r.stroke)}"` : ''}>${label(r)}</span><span class="v"></span></div>`;
    }).join('');
    this.vals = [...this.namesEl.querySelectorAll('.row .v')];
  }
  layout() {
    let y = this.hdrH;
    const lay = this.rowsL.map(row => { const h = row.type === 'lane' ? this.S.laneHeight * row.ids.length : this.rowH[row.type], o = { row, y, h }; y += h; return o; });
    lay.H = y; return lay;
  }
  frac(e) { const r = this.canvas.getBoundingClientRect(); return (e.clientX - r.left) / r.width; }
  pxPerT() { return this.canvas.getBoundingClientRect().width / this.span; }
  clamp(t) { return Math.min(Math.max(t, this.M.t0), this.M.t1 - this.span); }
  zoom(f, at) {
    const tAt = this.t0 + at * this.span;
    this.span = Math.min(Math.max(this.span * f, this.minSpan), this.M.t1 - this.M.t0);
    this.t0 = this.clamp(tAt - at * this.span); this.draw();
  }
  fit() { this.t0 = this.M.t0; this.span = this.M.t1 - this.M.t0; this.draw(); }
  goto(t, span) { this.span = Math.min(Math.max(span, this.minSpan), this.M.t1 - this.M.t0); this.t0 = this.clamp(t - this.span * 0.1); this.cursor = t; this.draw(); }
  fmt(t, ref, unitRef) { return this.M.timed ? fmtTime(t, ref, unitRef) : 'cycle ' + (t + (this.M.tick || 0)).toFixed(Math.max(0, Math.min(2, Math.ceil(-Math.log10(ref))))); }
  valueAt(sig, t) {
    const i = lastLE(sig.tr, t); if (i < 0) return '';
    const o = sig.tr[i]; return o.k === '=' ? vtext(sig, o, this.S.radix) : o.k;
  }
  // The canvas covers only the rows in view (any number of rows; a browser canvas is at most ~32k px tall): it is sticky
  // in a column as tall as all rows, and draws the layout shifted by oy = its offset in that column. The axis stays on top.
  draw() {
    if (this.S.arrowLabels === 'lane' && JSON.stringify([...arrowLanes(this.vis, this.bms, this.arrows)]) !== this.laneSig) this.renderNames();   // a label came or went
    const c = this.canvas, dpr = window.devicePixelRatio || 1, lay = this.layout(), H = lay.H, hdr = this.hdrH;
    if (this.wcol.style.height !== H + 'px') this.wcol.style.height = H + 'px';
    const W = c.getBoundingClientRect().width || 600, view = this.root.classList.contains('wv-scroll') ? this.bodyEl.clientHeight : window.innerHeight;
    const Hc = this.hc = Math.max(Math.min(H, hdr + 40), Math.min(H, view || H));
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(Hc * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(Hc * dpr); c.style.height = Hc + 'px'; }
    const oy = this.oy = Math.max(0, Math.min(H - Hc, c.getBoundingClientRect().top - this.wcol.getBoundingClientRect().top));
    const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const P = new CanvasPainter(g, getComputedStyle(this.root), this.S), M = this.M;
    P.rect(0, 0, W, Hc, 'panel');
    const k = W / this.span, X = t => (t - this.t0) * k, tB = this.t0 + this.span;
    paintAxis(P, { from: this.t0, span: this.span, xL: 0, xR: W, y: 0, h: hdr, yEnd: Hc, X, timed: M.timed, tick: M.tick, every: 1 });
    if (this.sel && !this.vis.includes(this.sel)) this.sel = null;   // folded away
    const shown = lay.filter(o => o.y + o.h > oy + hdr && o.y < oy + Hc);
    g.save(); g.beginPath(); g.rect(0, hdr, W, Hc - hdr); g.clip(); g.translate(0, -oy);   // rows: layout coordinates, under the axis
    const rowY = paintBody(P, M, shown, X, this.t0, tB, 0, W, this.hl, this.sel, lay, this.band);
    paintMarkers(P, this.markers, X, this.t0, tB, oy + hdr, oy + Hc);
    g.restore();
    if (this.cursor >= this.t0 && this.cursor <= tB) P.path([['M', X(this.cursor), 0], ['L', X(this.cursor), Hc]], { stroke: 'acc', w: 1.2 });
    g.save(); g.translate(0, -oy);
    this.lay = lay; this.bmGeo = paintBookmarks(P, this.bms, this.arrows, X, this.t0, tB, rowY, oy + hdr, oy + Hc, oy + hdr / 2, this.rubber, laneY(lay, this.S.laneHeight));
    g.restore();
    this.syncCursorFields();
    this.curEl.textContent = 'cursor ' + this.fmt(this.cursor, this.span / 1000, this.span) + ' · view ' + (M.timed ? fmtTime(this.span, this.span / 10, this.span) : this.span.toFixed(1) + ' cycles');
    if (this.valsAt !== this.cursor || this.valsVis !== this.vis || this.valsRadix !== this.S.radix) {   // value column: only when it changes
      this.valsAt = this.cursor; this.valsVis = this.vis; this.valsRadix = this.S.radix;
      let vi = 0;
      for (const r of this.vis) if (r.type === 'sig') this.vals[vi++].textContent = this.valueAt(r, this.cursor);
    }
  }
  setTheme(name) { applyLook(this.root, name || 'auto', null); this.draw(); return this; }
  setColors(map) { applyLook(this.root, undefined, map); this.draw(); return this; }
  destroy() { this.ro.disconnect(); window.removeEventListener('scroll', this.onScroll); window.removeEventListener('resize', this.onScroll); VIEWS.delete(this); }
}
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
const SVGS = new Map();   // static SVG host -> [model, opts], re-rendered by configure()
// Global settings, e.g. from a config file: { theme, colors, rowHeight, nameWidth, fontSize, traceWidth, sort, sortIgnore, … }.
// theme/colors go to <html> like setTheme/setColors; the rest becomes the default for every wave (null removes a key).
function configure(cfg = {}) {
  const { theme, colors, ...rest } = cfg || {}, html = document.documentElement;
  for (const [k, v] of Object.entries(rest)) { if (v == null) delete GLOBAL[k]; else GLOBAL[k] = v; }
  for (const [k, name] of Object.entries(STYLE_VAR)) if (k in rest && rest[k] == null) html.style.removeProperty(name);
  for (const [name, v] of styleVars(rest)) html.style.setProperty(name, v);
  if (theme !== undefined) applyLook(html, theme || 'auto', null);
  if (colors) applyLook(html, undefined, colors);
  VIEWS.forEach(v => { if (v.root.isConnected) v.restyle(); else v.destroy(); });
  SVGS.forEach(([m, o], el) => { if (el.isConnected) WaveSVG.render(el, m, o); else SVGS.delete(el); });
  return Object.assign({}, GLOBAL);
}

/* ---------------- static SVG ---------------- */
const WaveSVG = {
  // opts: from/to (model units or "12us"), width (px, fits the wave area), cyclePx (default 40·hscale), axis (force), bg, markers
  toString(model, opts = {}) {
    const M = parse(model), S = settings(SVG_DEFAULTS, GLOBAL, M.cfg, opts), P = new SvgPainter(S);
    groupPaint(M, S.groupColors);
    const from = parseT(opts.from) ?? M.t0, to = parseT(opts.to) ?? M.t1, fs = S.fontSize;
    const sorted = orderRows(M.rows, S.sort, S.sortIgnore, S.groupOrder), rh = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight };
    const rows = S.arrowLabels === 'lane' ? withLanes(sorted, arrowLanes(sorted, M.bookmarks, M.arrows)) : sorted;
    const hl = hlState(M, hlPick(M, S.highlight), S.dim);
    const nameW = Math.ceil(Math.max(40, ...rows.map(r => P.measure(r.name || '', { size: fs, weight: r.type === 'group' ? 600 : 400 }) + 22 + r.depth * 12)));
    let k = ((opts.cyclePx || 40) * M.hscale) / M.cycle;
    if (opts.width) k = (opts.width - nameW - 8) / (to - from);
    const waveW = (to - from) * k, Wt = Math.ceil(nameW + waveW + 8);
    const showAxis = opts.axis ?? (M.timed || M.tick != null), showTock = M.tock != null;
    let y = 4;
    const titleY = y; if (M.title) y += 22;
    const axisY = y; if (showAxis) y += 20;
    const lay = rows.map(row => { const h = row.type === 'lane' ? S.laneHeight * row.ids.length : rh[row.type], o = { row, y, h }; y += h; return o; });
    const bodyEnd = y, tockY = y; if (showTock) y += 20;
    const footY = y; if (M.foot) y += 20;
    const notes = M.bookmarks.filter(b => b.text), notesY = y + 6; if (notes.length) y += 8 + notes.length * 20;   // bookmark legend
    const Ht = Math.ceil(y + 4), xL = nameW, xR = nameW + waveW, X = t => xL + (t - from) * k;
    const theme = opts.theme ?? M.theme, colors = Object.assign({}, M.colors, opts.colors);
    const bg = opts.bg || (theme && theme !== 'auto') || colors.bg ? opts.bg || 'panel' : null;
    if (bg) P.rect(0, 0, Wt, Ht, bg);
    if (M.title) P.text(nameW + waveW / 2, titleY + 9, M.title, { anchor: 'middle', size: 13, weight: 600, body: true });
    if (M.foot) P.text(nameW + waveW / 2, footY + 9, M.foot, { anchor: 'middle', size: 12, fill: 'muted', body: true });
    // names and group brackets (a group spans down to its last member in display order)
    const last = {};
    rows.forEach((r, i) => r.anc.forEach(id => { last[id] = i; }));
    lay.forEach(({ row, y: ry, h }, i) => {
      const c = hl ? hl.cover.get(row) : undefined;
      P.fade = hl && !hl.on.has(row) ? hl.dim : 1;
      if (c !== undefined) { P.rect(0, ry, xL, h, 'hl' + (c + 1), 0.1); P.rect(0, ry, 3, h, 'hl' + (c + 1)); }
      if (!row.name) return;
      const g = row.type === 'group';
      P.text(6 + row.depth * 12 + (g ? 0 : 8), ry + h / 2, row.name, { size: fs, weight: g ? 700 : 400, fill: row.stroke || 'fg' });
      if (g && last[row.id] > i) {
        const end = lay[last[row.id]], bx = 3 + row.depth * 12;
        P.path([['M', bx + 4, ry + h], ['L', bx, ry + h], ['L', bx, end.y + end.h - 3], ['L', bx + 4, end.y + end.h - 3]], { stroke: 'muted', w: 1 });
      }
    });
    P.fade = 1;
    P.clip(xL, 0, waveW, Ht, () => {
      const step = M.timed ? null : Math.max(1, M.every);
      if (showAxis) paintAxis(P, { from, span: to - from, xL, xR, y: axisY, h: 20, yEnd: bodyEnd, X, timed: M.timed, tick: M.tick, every: M.every, step });
      if (showTock) paintAxis(P, { from, span: to - from, xL, xR, y: tockY, h: 20, yEnd: tockY, X, timed: M.timed, tick: M.tock, every: M.every, step });
      const rowY = paintBody(P, M, lay, X, from, to, xL, xR, hl, null, null, S.moduleShading && Object.keys(M.groups).length ? bands(rows) : null), top = showAxis ? axisY + 20 : lay.length ? lay[0].y : y;
      paintMarkers(P, (opts.markers || []).concat(M.markers), X, from, to, top, bodyEnd);
      paintBookmarks(P, M.bookmarks, M.arrows, X, from, to, rowY, top, bodyEnd, showAxis ? axisY + 10 : top + 10, null, laneY(lay, S.laneHeight));
    });
    notes.forEach((b, i) => {
      const cy = notesY + i * 20 + 10;
      P.path(circle(14, cy, 8), { fill: b.color || 'acc' }); P.text(14, cy + 0.5, String(b.n), { anchor: 'middle', size: b.n > 9 ? 9 : 10.5, weight: 700, fill: 'panel' });
      P.text(28, cy, b.text, { size: 12, body: true });
    });
    const css = [lookCss(colors), ...styleVars(Object.assign({}, M.cfg, opts)).map(([n, v]) => `${n}:${v}`)].filter(Boolean).join(';');
    const look = (THEMES.includes(theme) ? ` data-theme="${theme}"` : '') + (css ? ` style="${esc(css)}"` : '');
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${Wt} ${Ht}" width="${Wt}" height="${Ht}" role="img" aria-label="${esc(M.title || 'waveform')}"${look}>${P.out.join('')}</svg>`;
  },
  render(el, model, opts = {}) { el.classList.add('wvs'); if (opts.fit) el.classList.add('fit'); el.innerHTML = this.toString(model, opts); SVGS.set(el, [model, opts]); return el; },
};

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
    if (mode === 'svg') WaveSVG.render(host, M, opts); else new WaveView(host, M, opts);
  } catch (e) { host.className = 'wvf-err'; host.textContent = 'wavefw: ' + e.message; }
}
function upgrade(root = document) {
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
document.addEventListener('keydown', e => {   // Esc with nothing focused (after a click on text): reset the viewer used last
  if (e.key === 'Escape' && (e.target === document.body || e.target === document.documentElement) && ACTIVE.view && ACTIVE.view.root.isConnected) ACTIVE.view.reset();
});
if (G.MutationObserver) new MutationObserver(redrawAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
if (document.fonts && document.fonts.ready) document.fonts.ready.then(redrawAll);
if (G.WAVEFW_CONFIG) configure(G.WAVEFW_CONFIG);   // settings file loaded before wavefw.js (see README "Config file")
const manual = document.currentScript && document.currentScript.dataset.manual != null;
if (!manual) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => upgrade()); else upgrade(); }

G.WaveFW = { version: '1.5.0', parse, fromTV, WaveView, WaveSVG, upgrade, redrawAll, setTheme, setColors, configure, defaults: DEFAULTS,
  sortRows: (M, dir = 'asc', ignore = [], groupOrder = 'file') => orderRows(parse(M).rows, sortDir(dir), prefixes(ignore), groupOrder), fuzzy, themes: THEMES, colorNames: CVAR, styles: Object.keys(EDGES), radixes: RADIX, enums: ENUMS, decode, fmtTime, parseT };
G.WaveView = WaveView; G.WaveSVG = WaveSVG;
})(window);
