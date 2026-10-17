/* wavefw.js — WaveDrom-format waveform framework: parser, interactive canvas viewer (WaveView), static SVG (WaveSVG).
   No dependencies, no build step, works from file://. See README.md for the supported WaveDrom subset and extensions. */
(function (G) {
'use strict';

/* ---------------- tokens & helpers ---------------- */
// Colour names used by the painters -> CSS custom properties (defined in wavefw.css, overridable by the page).
const TOK = { fg: '--fg', muted: '--muted', line: '--line', panel: '--panel', panel2: '--panel-2', acc: '--accent',
  one: '--wave-1', bus: '--wave-bus', x: '--wave-x', xsoft: '--wave-x-soft', z: '--wave-z',
  c3: '--wave-c3', c4: '--wave-c4', c5: '--wave-c5', c6: '--wave-c6', c7: '--wave-c7', c8: '--wave-c8', c9: '--wave-c9' };
// Friendly names for colour maps (config.colors, data-colors, WaveFW.setColors) -> CSS custom properties.
const CVAR = { trace: '--wave-1', one: '--wave-1', bus: '--wave-bus', x: '--wave-x', xfill: '--wave-x-soft', z: '--wave-z',
  bg: '--panel', panel: '--panel', header: '--panel-2', grid: '--line', text: '--fg', muted: '--muted', accent: '--accent', cursor: '--accent',
  page: '--bg', c3: '--wave-c3', c4: '--wave-c4', c5: '--wave-c5', c6: '--wave-c6', c7: '--wave-c7', c8: '--wave-c8', c9: '--wave-c9' };
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
  labelSize: 11, fontSize: 11.5, sort: 'none', sortIgnore: [], sortButton: true, hint: true, style: 'auto', radix: 'auto', fold: null };
const SVG_DEFAULTS = { groupHeight: 20, spaceHeight: 12 };   // the static figure is a little denser
const GLOBAL = {};
// settings that live in CSS (so the names column, fonts and static SVG text follow them too); numbers are px
const STYLE_VAR = { nameWidth: '--wv-names', fontSize: '--wv-font-size', fontMono: '--font-mono', fontBody: '--font-body' };
const prefixes = v => (Array.isArray(v) ? v : String(v ?? '').split(',')).map(s => String(s).trim()).filter(Boolean);
function settings(...layers) {
  const S = Object.assign({}, DEFAULTS);
  for (const l of layers) for (const [k, v] of Object.entries(l || {})) if (v != null && k !== 'theme' && k !== 'colors') S[k] = v;
  for (const k of ['rowHeight', 'groupHeight', 'spaceHeight', 'headerHeight', 'traceWidth', 'busWidth', 'labelSize', 'fontSize']) S[k] = num(S[k]) || DEFAULTS[k];
  S.sort = sortDir(S.sort); S.sortIgnore = prefixes(S.sortIgnore).sort((a, b) => b.length - a.length);
  if (!EDGES[S.style]) S.style = 'auto';
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

/* ---------------- signal sorting (natural order, optional prefixes ignored: i_, o_ …) ---------------- */
const SORTS = ['none', 'asc', 'desc'];
const sortDir = v => (v === true ? 'asc' : SORTS.includes(v) ? v : 'none');
const COLL = typeof Intl !== 'undefined' ? new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' }) : null;
const stripPfx = (name, pfx) => { const p = pfx.find(p => name.startsWith(p) && name.length > p.length); return p ? [p, name.slice(p.length)] : ['', name]; };
// rows in display order: siblings (one group level, between {} spacers) sorted by name; groups move as a block
function orderRows(rows, dir, pfx) {
  if (dir !== 'asc' && dir !== 'desc') return rows;
  const kids = new Map([[null, []]]);
  for (const r of rows) { kids.get(r.anc.length ? r.anc[r.anc.length - 1] : null).push(r); if (r.type === 'group') kids.set(r.id, []); }
  const key = r => stripPfx(r.name, pfx)[1], sgn = dir === 'desc' ? -1 : 1;
  const c = (x, y) => (COLL ? COLL.compare(x, y) : x < y ? -1 : x > y ? 1 : 0);
  const cmp = (a, b) => sgn * (c(key(a), key(b)) || c(a.name, b.name));   // i_data / o_data: full name breaks the tie
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
          M.groups[g.id] = g; M.rows.push(g);
          walk(it.slice(1), depth + 1, anc.concat(g.id)); g.last = M.rows.length - 1;
        } else walk(named ? it.slice(1) : it, depth, anc);
      } else if (it && typeof it === 'object' && (it.wave != null || it.tv || it.same)) {
        if (!it.tv && it.same && byPath[it.same]) it = Object.assign({}, it, { tv: byPath[it.same] });
        const sig = { type: 'sig', name: flatText(it.name), depth, anc, width: 1, enum: it.enum, radix: it.radix || it.fmt, style: it.style, path: it.path, src: it,
          stroke: it.stroke || (typeof it.color === 'string' && !/^[2-9]$/.test(it.color) ? it.color : undefined), fill: it.fill };
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
  return M;
}
// template.html's dump format ({ t0, t1, signals: [{ name, w, t: [[ps, value]] }] }) -> WaveJSON with the time extension
function fromTV(wave, extra = {}) {
  return Object.assign({ signal: wave.signals.map(s => ({ name: s.name, width: s.w, tv: s.t })),
    time: { t0: wave.t0, t1: wave.t1, cycle: (wave.t1 - wave.t0) / 40 } }, extra);
}

/* ---------------- painters: one drawing routine, two back-ends ---------------- */
class CanvasPainter {
  constructor(g, cs, S) { this.g = g; this.cs = cs; this.S = S; this.cache = {}; this.mono = cs.getPropertyValue('--font-mono').trim() || 'monospace'; this.body = cs.getPropertyValue('--font-body').trim() || 'sans-serif'; }
  col(n) { return this.cache[n] || (this.cache[n] = TOK[n] ? this.cs.getPropertyValue(TOK[n]).trim() || '#888' : n); }
  path(cmds, st) {
    const g = this.g; g.beginPath();
    for (const c of cmds) {
      if (c[0] === 'M') g.moveTo(c[1], c[2]); else if (c[0] === 'L') g.lineTo(c[1], c[2]);
      else if (c[0] === 'C') g.bezierCurveTo(c[1], c[2], c[3], c[4], c[5], c[6]); else g.closePath();
    }
    g.globalAlpha = st.alpha ?? 1;
    if (st.fill) { g.fillStyle = this.col(st.fill); g.fill(); }
    if (st.stroke) { g.strokeStyle = this.col(st.stroke); g.lineWidth = st.w || 1; g.setLineDash(st.dash || []); g.stroke(); g.setLineDash([]); }
    g.globalAlpha = 1;
  }
  rect(x, y, w, h, fill) { this.g.fillStyle = this.col(fill); this.g.fillRect(x, y, w, h); }
  font(st) { return `${st.weight || 400} ${st.size || 11}px ${st.body ? this.body : this.mono}`; }
  text(x, y, s, st = {}) {
    const g = this.g; g.font = this.font(st); g.fillStyle = this.col(st.fill || 'fg');
    g.textAlign = { start: 'left', middle: 'center', end: 'right' }[st.anchor || 'start']; g.textBaseline = 'middle'; g.fillText(s, x, y);
  }
  measure(s, st = {}) { this.g.font = this.font(st); return this.g.measureText(s).width; }
  clip(x, y, w, h, fn) { const g = this.g; g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip(); fn(); g.restore(); }
}
let clipId = 0, measureCtx = null;
class SvgPainter {
  constructor(S) {
    this.out = []; this.S = S;
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
    if (st.alpha != null) css += `;opacity:${st.alpha}`;
    this.out.push(`<path d="${d}" style="${css}"/>`);
  }
  rect(x, y, w, h, fill) { this.out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" style="fill:${this.col(fill)}"/>`); }
  text(x, y, s, st = {}) {
    this.out.push(`<text x="${Math.round(x * 100) / 100}" y="${Math.round(y * 100) / 100}" dominant-baseline="central" text-anchor="${st.anchor || 'start'}" style="font-family:var(${st.body ? '--font-body' : '--font-mono'});font-size:${st.size || 11}px;font-weight:${st.weight || 400};fill:${this.col(st.fill || 'fg')}">${esc(s)}</text>`);
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
function paintBody(P, M, lay, X, tA, tB, xL, xR) {
  const rowY = new Map(), sep = [];
  for (const { row, y, h } of lay) {
    if (row.type === 'group') P.rect(xL, y, xR - xL, h, 'panel2');
    if (row.type !== 'space') sep.push(['M', xL, y + h - 0.5], ['L', xR, y + h - 0.5]);
    if (row.type === 'sig') { paintSig(P, row, y, h, X, tA, tB, xL, xR, M.t1); rowY.set(row, y + h / 2); }
  }
  P.path(sep, { stroke: 'line', w: 1, alpha: 0.5 });
  paintEdges(P, M, rowY, X);
}
function paintMarkers(P, markers, X, tA, tB, y0, y1) {
  for (const m of markers) {
    if (m.t < tA || m.t > tB) continue;
    const x = X(m.t); P.path([['M', x, y0], ['L', x, y1]], { stroke: 'muted', w: 1, dash: [3, 3] });
    if (m.label) { P.rect(x + 1, y0 + 2, P.measure(m.label, { size: 10 }) + 4, 12, 'panel'); P.text(x + 3, y0 + 8, m.label, { size: 10, fill: 'muted' }); }
  }
}

/* ---------------- interactive viewer ---------------- */
const VIEWS = new Set();
class WaveView {
  constructor(root, model, opts = {}) {
    this.root = root; this.M = parse(model); this.opts = opts;
    const M = this.M;
    applyLook(root, opts.theme ?? M.theme, Object.assign({}, M.colors, opts.colors));
    this.restyle(false); this.collapsed = foldSet(M, this.S.fold);
    this.t0 = M.t0; this.span = M.t1 - M.t0;
    this.minSpan = opts.minSpan ?? (M.timed ? Math.max(this.span / 1e6, 10) : 0.5);
    this.cursor = opts.cursor ?? M.cursor ?? M.t0;
    this.markers = (opts.markers || []).concat(M.markers);
    this.jumps = opts.jumps || M.jumps || (this.markers.length && this.markers.length <= 6
      ? this.markers.map(m => ({ label: '→ ' + m.label, t: m.t, span: this.span / 5 })) : []);
    this.build(); this.fit();
    if (opts.from != null || opts.to != null) { // initial view window (Fit still shows everything)
      const a = opts.from ?? M.t0, b = opts.to ?? M.t1;
      this.span = Math.min(Math.max(b - a, this.minSpan), M.t1 - M.t0); this.t0 = this.clamp(a); this.draw();
    }
    this.ro = new ResizeObserver(() => this.draw()); this.ro.observe(this.canvas);
    VIEWS.add(this);
  }
  // settings from all layers; a global WaveFW.configure() calls this again on every viewer
  restyle(redraw = true) {
    const S = this.S = settings(GLOBAL, this.M.cfg, this.opts);
    for (const [name, v] of styleVars(Object.assign({}, this.M.cfg, this.opts))) this.root.style.setProperty(name, v);
    this.rowH = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight }; this.hdrH = S.headerHeight;
    this.sort = S.sort; this.sortIgnore = S.sortIgnore;
    if (redraw) { const i = this.root.querySelector('input.pfx'); if (i) i.value = S.sortIgnore.join(','); this.fitPfx(); this.renderNames(); this.draw(); }
  }
  build() {
    const r = this.root, S = this.S; r.classList.add('wv');
    const jumps = this.jumps.map((j, i) => `<button type="button" data-jump="${i}">${esc(j.label)}</button>`).join('');
    const sort = S.sortButton ? `<button type="button" data-act="sort" title="Sort signals by name (key: s)"></button><input type="text" class="pfx" spellcheck="false" size="8" value="${esc(this.sortIgnore.join(','))}" placeholder="i_,o_" title="Name prefixes ignored when sorting (comma-separated)" aria-label="prefixes ignored when sorting">` : '';
    r.innerHTML = `<div class="bar"><span class="eyebrow">${esc(this.opts.title || this.M.title || 'Waveform').replace(/µ/g, '<span class="mu">µ</span>')}</span>
      <button type="button" data-act="in">Zoom +</button><button type="button" data-act="out">Zoom −</button>
      <button type="button" data-act="fit">Fit</button>${sort}${jumps}<span class="cur"></span></div>
      <div class="body"><div class="names"></div><canvas tabindex="0" aria-label="waveform canvas"></canvas></div>
      ${S.hint ? `<div class="hint">Wheel: zoom at pointer · shift+wheel or drag: pan · click: cursor · keys: + − 0 ← →${S.sortButton ? ' s' : ''}${this.M.groups && Object.keys(this.M.groups).length ? ' · click a group to fold it' : ''}</div>` : ''}`;
    this.canvas = r.querySelector('canvas'); this.namesEl = r.querySelector('.names'); this.curEl = r.querySelector('.cur');
    this.sortBtn = r.querySelector('button[data-act=sort]');
    r.querySelector('.bar').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.act === 'in') this.zoom(0.5, 0.5);
      else if (b.dataset.act === 'out') this.zoom(2, 0.5);
      else if (b.dataset.act === 'fit') this.fit();
      else if (b.dataset.act === 'sort') this.setSort(SORTS[(SORTS.indexOf(this.sort) + 1) % SORTS.length]);
      else if (b.dataset.jump !== undefined) { const j = this.jumps[b.dataset.jump]; this.goto(j.t, j.span); }
    });
    const pfx = r.querySelector('input.pfx');
    if (pfx) pfx.addEventListener('input', () => { this.fitPfx(); this.setSort(this.sort, pfx.value); });
    this.fitPfx();
    const toggle = el => { const id = +el.dataset.g; this.collapsed.has(id) ? this.collapsed.delete(id) : this.collapsed.add(id); this.renderNames(); this.draw(); };
    this.namesEl.addEventListener('click', e => { const g = e.target.closest('.grp'); if (g) toggle(g); });
    this.namesEl.addEventListener('keydown', e => { const g = e.target.closest('.grp'); if (g && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggle(g); } });
    const c = this.canvas;
    c.addEventListener('wheel', e => {
      e.preventDefault();
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) { this.t0 = this.clamp(this.t0 + this.span * 0.1 * Math.sign(e.deltaX || e.deltaY)); this.draw(); }
      else this.zoom(e.deltaY > 0 ? 1.25 : 0.8, this.frac(e));
    }, { passive: false });
    let drag = null;
    c.addEventListener('pointerdown', e => { drag = { x: e.clientX, t0: this.t0, moved: false }; c.setPointerCapture(e.pointerId); });
    c.addEventListener('pointermove', e => {
      if (!drag) return; const dx = e.clientX - drag.x; if (Math.abs(dx) > 3) drag.moved = true;
      if (drag.moved) { this.t0 = this.clamp(drag.t0 - dx / this.pxPerT()); this.draw(); }
    });
    c.addEventListener('pointerup', e => { if (drag && !drag.moved) { this.cursor = this.t0 + (e.clientX - c.getBoundingClientRect().left) / this.pxPerT(); this.draw(); } drag = null; });
    c.addEventListener('pointercancel', () => { drag = null; });
    c.addEventListener('keydown', e => {
      const k = e.key; let h = true;
      if (k === '+' || k === '=') this.zoom(0.5, 0.5); else if (k === '-') this.zoom(2, 0.5); else if (k === '0') this.fit();
      else if (k === 's' && this.S.sortButton) this.setSort(SORTS[(SORTS.indexOf(this.sort) + 1) % SORTS.length]);
      else if (k === 'ArrowLeft') { this.t0 = this.clamp(this.t0 - this.span * 0.2); this.draw(); }
      else if (k === 'ArrowRight') { this.t0 = this.clamp(this.t0 + this.span * 0.2); this.draw(); }
      else h = false;
      if (h) e.preventDefault();
    });
    this.renderNames();
  }
  fitPfx() { const i = this.root.querySelector('input.pfx'); if (i) i.style.width = Math.max(7, i.value.length + 2) + 'ch'; }
  visible() { return orderRows(this.M.rows, this.sort, this.sortIgnore).filter(r => !r.anc.some(id => this.collapsed.has(id))); }
  // dir: none | asc | desc; ignore: prefixes skipped when comparing names ("i_,o_" or an array)
  setSort(dir, ignore) {
    this.sort = sortDir(dir);
    if (ignore !== undefined) this.sortIgnore = prefixes(ignore).sort((a, b) => b.length - a.length);
    this.renderNames(); this.draw(); return this;
  }
  renderNames() {
    this.vis = this.visible(); this.vals = [];
    if (this.sortBtn) { this.sortBtn.textContent = 'Sort: ' + { none: 'off', asc: 'A→Z', desc: 'Z→A' }[this.sort]; this.sortBtn.setAttribute('aria-pressed', this.sort !== 'none'); }
    const pad = r => `padding-left:${8 + r.depth * 12}px`, sorted = this.sort !== 'none';
    const label = r => { const [p, rest] = sorted ? stripPfx(r.name, this.sortIgnore) : ['', r.name]; return (p ? `<span class="pfx">${esc(p)}</span>` : '') + esc(rest); };
    this.namesEl.innerHTML = `<div class="hdr" style="height:${this.hdrH}px"></div>` + this.vis.map(r => {
      const h = this.rowH[r.type];
      if (r.type === 'group') { const open = !this.collapsed.has(r.id); return `<div class="row grp" style="height:${h}px;${pad(r)}" data-g="${r.id}" tabindex="0" role="button" aria-expanded="${open}" title="${esc(r.path)}"><span class="n">${open ? '▾' : '▸'} ${label(r)}</span></div>`; }
      if (r.type === 'space') return `<div class="row space" style="height:${h}px;${pad(r)}"><span class="n">${esc(r.name)}</span></div>`;
      return `<div class="row" style="height:${h}px;${pad(r)}"><span class="n" title="${esc(r.path || r.name)}"${r.stroke ? ` style="color:${esc(r.stroke)}"` : ''}>${label(r)}</span><span class="v"></span></div>`;
    }).join('');
    this.vals = [...this.namesEl.querySelectorAll('.row .v')];
  }
  layout() { let y = this.hdrH; const lay = this.vis.map(row => { const h = this.rowH[row.type], o = { row, y, h }; y += h; return o; }); lay.H = y; return lay; }
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
  draw() {
    const c = this.canvas, dpr = window.devicePixelRatio || 1, lay = this.layout();
    const W = c.getBoundingClientRect().width || 600, H = lay.H;
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(H * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); c.style.height = H + 'px'; }
    const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const P = new CanvasPainter(g, getComputedStyle(this.root), this.S), M = this.M;
    P.rect(0, 0, W, H, 'panel');
    const k = W / this.span, X = t => (t - this.t0) * k, tB = this.t0 + this.span;
    paintAxis(P, { from: this.t0, span: this.span, xL: 0, xR: W, y: 0, h: this.hdrH, yEnd: H, X, timed: M.timed, tick: M.tick, every: 1 });
    paintBody(P, M, lay, X, this.t0, tB, 0, W);
    paintMarkers(P, this.markers, X, this.t0, tB, this.hdrH, H);
    if (this.cursor >= this.t0 && this.cursor <= tB) P.path([['M', X(this.cursor), 0], ['L', X(this.cursor), H]], { stroke: 'acc', w: 1.2 });
    this.curEl.textContent = 'cursor ' + this.fmt(this.cursor, this.span / 1000, this.span) + ' · view ' + (M.timed ? fmtTime(this.span, this.span / 10, this.span) : this.span.toFixed(1) + ' cycles');
    let vi = 0;
    for (const r of this.vis) if (r.type === 'sig') this.vals[vi++].textContent = this.valueAt(r, this.cursor);
  }
  setTheme(name) { applyLook(this.root, name || 'auto', null); this.draw(); return this; }
  setColors(map) { applyLook(this.root, undefined, map); this.draw(); return this; }
  destroy() { this.ro.disconnect(); VIEWS.delete(this); }
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
    const from = parseT(opts.from) ?? M.t0, to = parseT(opts.to) ?? M.t1, fs = S.fontSize;
    const rows = orderRows(M.rows, S.sort, S.sortIgnore), rh = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight };
    const nameW = Math.ceil(Math.max(40, ...rows.map(r => P.measure(r.name || '', { size: fs, weight: r.type === 'group' ? 600 : 400 }) + 22 + r.depth * 12)));
    let k = ((opts.cyclePx || 40) * M.hscale) / M.cycle;
    if (opts.width) k = (opts.width - nameW - 8) / (to - from);
    const waveW = (to - from) * k, Wt = Math.ceil(nameW + waveW + 8);
    const showAxis = opts.axis ?? (M.timed || M.tick != null), showTock = M.tock != null;
    let y = 4;
    const titleY = y; if (M.title) y += 22;
    const axisY = y; if (showAxis) y += 20;
    const lay = rows.map(row => { const h = rh[row.type], o = { row, y, h }; y += h; return o; });
    const bodyEnd = y, tockY = y; if (showTock) y += 20;
    const footY = y; if (M.foot) y += 20;
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
      if (!row.name) return;
      const g = row.type === 'group';
      P.text(6 + row.depth * 12 + (g ? 0 : 8), ry + h / 2, row.name, { size: fs, weight: g ? 600 : 400, fill: g ? 'muted' : row.stroke || 'fg' });
      if (g && last[row.id] > i) {
        const end = lay[last[row.id]], bx = 3 + row.depth * 12;
        P.path([['M', bx + 4, ry + h], ['L', bx, ry + h], ['L', bx, end.y + end.h - 3], ['L', bx + 4, end.y + end.h - 3]], { stroke: 'muted', w: 1 });
      }
    });
    P.clip(xL, 0, waveW, Ht, () => {
      const step = M.timed ? null : Math.max(1, M.every);
      if (showAxis) paintAxis(P, { from, span: to - from, xL, xR, y: axisY, h: 20, yEnd: bodyEnd, X, timed: M.timed, tick: M.tick, every: M.every, step });
      if (showTock) paintAxis(P, { from, span: to - from, xL, xR, y: tockY, h: 20, yEnd: tockY, X, timed: M.timed, tick: M.tock, every: M.every, step });
      paintBody(P, M, lay, X, from, to, xL, xR);
      paintMarkers(P, (opts.markers || []).concat(M.markers), X, from, to, showAxis ? axisY + 20 : lay.length ? lay[0].y : y, bodyEnd);
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
if (G.MutationObserver) new MutationObserver(redrawAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme', 'class', 'style'] });
if (document.fonts && document.fonts.ready) document.fonts.ready.then(redrawAll);
if (G.WAVEFW_CONFIG) configure(G.WAVEFW_CONFIG);   // settings file loaded before wavefw.js (see README "Config file")
const manual = document.currentScript && document.currentScript.dataset.manual != null;
if (!manual) { if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => upgrade()); else upgrade(); }

G.WaveFW = { version: '1.3.0', parse, fromTV, WaveView, WaveSVG, upgrade, redrawAll, setTheme, setColors, configure, defaults: DEFAULTS,
  sortRows: (M, dir = 'asc', ignore = []) => orderRows(parse(M).rows, sortDir(dir), prefixes(ignore)), themes: THEMES, colorNames: CVAR, styles: Object.keys(EDGES), radixes: RADIX, enums: ENUMS, decode, fmtTime, parseT };
G.WaveView = WaveView; G.WaveSVG = WaveSVG;
})(window);
