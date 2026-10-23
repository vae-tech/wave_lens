/* wavefw src/vcd.js — a VCD read in the page (Open… / a file dropped on a viewer): WaveJSON with exact transitions */

/* ---------------- VCD -> WaveJSON ---------------- */
// The signals of a VCD as WaveJSON groups by scope (the "tv" extension: [[ps, value]], a bus's value in hex, x / z
// kept), "time" in ps, "scopes" with the struct / union / interface scopes. A big dump is cut to fit a page: the
// signals nearest the top first, until `budget` value changes; -> {doc, shown, total, changes}. An FST is binary:
// sva vcd, fst2vcd (GTKWave) or make html. The rules are tools/dumpscan.py's (its tests in tests/unit compare the two): the
// reference of a $var (parse_ref: an escaped \name whole, a range glued or apart is the vector's, a 1-bit "err[3]" a
// bit of "err", "mem[1]" an element "mem.[1]"), the same path under two id codes with one range merged, a path in
// parts (bits "err[0]" "err[1]", ranges apart "data [7:0]" "data [15:8]") one vector from its lowest index to its highest,
// real (realtime shortreal real_parameter) and string variables as texts ("kind"), the enum tables of an FST
// written as text ("enum": FSM states by name), events left out, $comment … $end
// skipped in the body, VHDL's U W H L - folded, time in order.
const VCD_UNIT = { s: 1e12, ms: 1e9, us: 1e6, ns: 1e3, ps: 1, fs: 1e-3, as: 1e-6, zs: 1e-9 };
const VCD_TEXT = { real: 'real', realtime: 'real', shortreal: 'real', real_parameter: 'real', string: 'string' };   // -> "kind"
function vcdRef(toks) {   // the words of a $var after its code -> [name, range]
  let ref = toks[0] || '', rng = toks.length > 1 && toks[1][0] === '[' ? toks[1] : '';
  if (ref[0] !== '\\' && !rng) { const m = /^(.+?)(\[\d+:\d+\])$/.exec(ref); if (m) { ref = m[1]; rng = m[2]; } }
  return [ref, rng];
}
function vcdToWave(text, opts = {}) {
  const budget = opts.budget ?? 3e6, name = opts.name || 'dump.vcd';
  let i = 0, unit = 1;
  const word = () => { while (i < text.length && text.charCodeAt(i) <= 32) i++; const s = i; while (i < text.length && text.charCodeAt(i) > 32) i++;
    return text.slice(s, i); };
  const decls = new Map(), scope = [], kinds = {};   // path -> {path, name, scope, kind, depth, enum, ds: [[code, [msb, lsb] | null, size, glued bit]]}
  const tables = {}; let pending = null;   // the enum tables of an FST as VCD text (fst2vcd -e, sva vcd): handle -> {value: label}
  // the header: $scope / $var / $upscope / $timescale / $attrbegin up to $enddefinitions
  for (;;) {
    const w = word(); if (!w) throw new Error('no $enddefinitions: not a VCD, or its header is cut off');
    if (w === '$enddefinitions') { word(); break; }
    if (w === '$scope') { const kind = word(), n = word(); word(); scope.push(n); if (kind !== 'module') kinds[scope.join('.')] = kind; }
    else if (w === '$upscope') { word(); scope.pop(); }
    else if (w === '$timescale') { let t = ''; for (let x = word(); x && x !== '$end'; x = word()) t += x; const m = /^(\d+)(s|ms|us|ns|ps|fs|as|zs)$/.exec(t);
      unit = m ? +m[1] * VCD_UNIT[m[2]] : 1; }
    else if (w === '$attrbegin') {   // misc 07 NAME COUNT LABEL… VALUE… HANDLE: a table; misc 07 "" HANDLE: the next $var's (dumpscan's _enum_table)
      const toks = []; for (let x = word(); x && x !== '$end'; x = word()) toks.push(x);
      if (toks[0] !== 'misc' || (toks[1] !== '07' && toks[1] !== '7') || toks.length < 4) continue;
      const b = toks.slice(2), n = +b[1];
      if (b.length === 2) pending = b[1];
      else if (Number.isInteger(n) && b.length > 2 + 2 * n) {
        const t = {}; for (let j = 0; j < n; j++) if (/^[01]+$/.test(b[2 + n + j])) t[parseInt(b[2 + n + j], 2)] = b[2 + j];
        tables[b[2 + 2 * n]] = t;
      }
    }
    else if (w === '$var') {
      const kind = word().toLowerCase(), size = +word() || 1, code = word(), toks = [], en = pending != null ? tables[pending] : null;
      pending = null;
      for (let x = word(); x && x !== '$end'; x = word()) toks.push(x);
      if (kind === 'event') continue;   // no value to draw
      const [ref, rng] = vcdRef(toks), esc = ref[0] === '\\', m = esc ? null : /^(.+)\[(\d+)\]$/.exec(ref);
      let path, d;
      if (m && !rng && size === 1 && !VCD_TEXT[kind]) {   // one bit of a bit-blasted vector: the vector under its name
        path = scope.concat(m[1]).join('.'); d = [code, [+m[2], +m[2]], 1, true];
        if (!decls.has(path)) decls.set(path, { path, name: m[1], scope: scope.slice(), kind: null, depth: scope.length, ds: [] });
      } else {
        const leaf = !esc && ref.includes('[') ? ref.replace('[', '.[') : ref, r = /^\[(\d+)(?::(\d+))?\]$/.exec(rng);
        path = scope.concat(leaf).join('.'); d = [code, r ? [+r[1], +(r[2] ?? r[1])] : null, size, false];
        if (!decls.has(path)) decls.set(path, { path, name: esc ? leaf : leaf.split('.').pop(), depth: scope.length, kind: VCD_TEXT[kind] || null,
          scope: !esc && leaf.includes('.') ? scope.concat(leaf.split('.').slice(0, -1)) : scope.slice(), ds: [] });
        if (en && !decls.get(path).enum) decls.get(path).enum = en;
      }
      decls.get(path).ds.push(d);
    }
    else if (w[0] === '$') { for (let x = word(); x && x !== '$end'; x = word()); }   // $date $version $comment …
  }
  // a path declared once, or again under another code with the same range: one value (the codes merged); in parts (bits,
  // ranges): one vector from the lowest index to the highest, members [code, [msb, lsb]] counted from bit 0 (the last)
  const vars = [...decls.values()];
  for (const v of vars) {
    const ds = v.ds, key = p => (p ? p.join(':') : '');
    if (!ds.some(d => d[3]) && ds.every(d => key(d[1]) === key(ds[0][1]))) { v.width = ds[0][2]; v.members = ds.map(d => [d[0], null]); }
    else {
      const ps = ds.map(([k, p, n]) => [k, p || [n - 1, 0]]), ix = ps.flatMap(x => x[1]);
      const lo = ix.reduce((a, b) => Math.min(a, b)), hi = ix.reduce((a, b) => Math.max(a, b));
      const asc = ps.some(x => x[1][0] < x[1][1]), pos = i => (asc ? hi - i : i - lo);   // ascending ([0:3] [4:7]): index 0 on the left
      v.width = hi - lo + 1; v.members = ps.map(([k, p]) => [k, [pos(p[0]), pos(p[1])]]);
    }
    const seen = new Set(); v.members = v.members.filter(x => !seen.has(x[0] + ' ' + key(x[1])) && seen.add(x[0] + ' ' + key(x[1])));
    v.codes = [...new Set(v.members.map(x => x[0]))];   // each code once: its changes counted once for the budget
  }
  // the value changes, token by token (one per line or several on a line): #time, 0! 1! x! z!, b0101 !, r1.5 !, sText !
  const body = i, count = new Map();
  const scan = fn => {
    let p = body, t = 0, first = true; const n = text.length;
    while (p < n) {
      while (p < n && text.charCodeAt(p) <= 32) p++; if (p >= n) break;
      const s0 = p; while (p < n && text.charCodeAt(p) > 32) p++;
      const c = text[s0];
      if (c === '#') {
        const tn = Number(text.slice(s0 + 1, p)) * unit;
        if (!first && tn < t) throw new Error(`time goes back: #${text.slice(s0 + 1, p)} after #${t / unit} (a VCD lists its times in order)`);
        t = tn; first = false; fn(null, t);
      }
      else if (c === '$') {   // $dumpvars $dumpall $dumpon $dumpoff $end: nothing; $comment and the like: to their $end
        const kw = text.slice(s0, p);
        if (!/^\$(dumpvars|dumpall|dumpon|dumpoff|end)$/.test(kw)) { const e = text.indexOf('$end', p); p = e < 0 ? n : e + 4; }
      }
      else if ('bBrRsS'.includes(c)) {   // b… / r… / s… then its code
        while (p < n && text.charCodeAt(p) <= 32) p++; const k0 = p; while (p < n && text.charCodeAt(p) > 32) p++;
        const v = text.slice(s0 + 1, k0).trim();
        fn(text.slice(k0, p), t, c === 'b' || c === 'B' ? vcdBits(v.toLowerCase()) : v, c === 'r' || c === 'R' ? 'real' : c === 's' ||
          c === 'S' ? 'string' : 'b');
      }
      else if ('01xzXZuUwWhHlL-'.includes(c)) fn(text.slice(s0 + 1, p), t, vcdBits(c.toLowerCase()), 'b');
    }
  };
  scan(k => { if (k != null) count.set(k, (count.get(k) || 0) + 1); });
  const changes = v => v.codes.reduce((s, k) => s + (count.get(k) || 0), 0);
  const order = vars.slice().sort((a, b) => a.depth - b.depth);   // stable: declaration order inside a level
  const keep = new Set(); let used = 0;
  // the levels nearest the top, as many as fit
  for (const v of order) { const n = changes(v); if (used + n > budget && keep.size) break; keep.add(v); used += n; }
  // the transitions of the variables kept: per id code, then per variable (codes merged, bits put together)
  const raw = new Map(); for (const v of keep) for (const k of v.codes) raw.set(k, []);
  let t0 = null, t1 = 0;
  scan((k, t, val) => {
    if (k == null) { if (t0 == null) t0 = t; t1 = Math.max(t1, t); return; }
    if (t0 == null) t0 = t;   // values before the first time (a $dumpvars block): the dump starts at 0
    const a = raw.get(k); if (a && val != null) a.push([t, val]);
  });
  const tvOf = v => {
    const out = [], put = (t, x) => { const L = out[out.length - 1]; if (L && L[0] === t) { L[1] = x;
      if (out.length > 1 && out[out.length - 2][1] === x) out.pop(); } else if (!L || L[1] !== x) out.push([t, x]); };
    if (v.members[0][1]) {   // a vector in parts: its bits after every time step with a change of any part
      const st = new Array(v.width).fill('x'), ev = v.members.flatMap(([k, p]) => raw.get(k).map(([t, x]) => [t, p, x]));
      ev.sort((a, b) => a[0] - b[0]);   // stable: a code's changes in their order
      ev.forEach(([t, [h, l], x], j) => {
        const n = Math.abs(h - l) + 1, s = h >= l ? -1 : 1, b = vcdExt(x || 'x', n);   // b01 for one bit: its last digit
        for (let q = 0; q < n; q++) st[v.width - 1 - (h + q * s)] = b[q];
        if (j + 1 === ev.length || ev[j + 1][0] !== t) put(t, vcdHex(st.join(''), v.width));
      });
      return out;
    }
    const ev = v.codes.length === 1 ? raw.get(v.codes[0]) : v.codes.flatMap(k => raw.get(k)).sort((a, b) => a[0] - b[0]);
    for (const [t, x] of ev) put(t, v.kind === 'real' ? vcdReal(x) : v.kind === 'string' ? x : vcdHex(x, v.width));
    return out;
  };
  // WaveJSON: groups by scope in declaration order
  const out = [], node = new Map([['', out]]);
  const shownVars = vars.filter(v => keep.has(v));
  for (const v of shownVars) {
    let key = '';
    for (const p of v.scope) { const k2 = key ? key + '.' + p : p; if (!node.has(k2)) { const g = [p]; node.get(key).push(g); node.set(k2, g); } key = k2; }
    const s = { name: v.name, path: v.path, tv: tvOf(v) }; if (v.width > 1) s.width = v.width; if (v.kind) s.kind = v.kind;
    if (v.enum) s.enum = v.enum;
    node.get(key).push(s);
  }
  const scopes = {};
  for (const [p, k] of Object.entries(kinds)) if (node.has(p) && (k === 'struct' || k === 'union' || k === 'interface'))
    scopes[p] = k === 'interface' ? k : { kind: k, width: vars.filter(v => v.path.startsWith(p + '.')).reduce((n, v) => n + v.width, 0) };
  const end = Math.max(t1, (t0 ?? 0) + 1);
  const doc = { signal: out, head: { text: name }, time: { t0: t0 ?? 0, t1: end, cycle: (end - (t0 ?? 0)) / 40, unit: 'ps' }, config: {} };
  if (Object.keys(scopes).length) doc.scopes = scopes;
  const omitted = {};   // past the budget: in the dump, not in the page (its find says so), by scope
  for (const v of vars) if (!keep.has(v)) (omitted[v.scope.join('.')] ||= []).push(v.name);
  if (Object.keys(omitted).length) doc.meta = { omitted: { why: 'dumpBudget', paths: omitted } };
  return { doc, shown: shownVars.length, total: vars.length, changes: used };
}
// a VCD vector value in w digits: a shorter one extended with 0, or x / z; a longer one its last w
const vcdExt = (b, w) => (b.length < w ? (b[0] === 'x' || b[0] === 'z' ? b[0] : '0').repeat(w - b.length) + b : b.length > w ? b.slice(b.length - w) : b);
// a real as written (r1.5, rinf, r-inf, rnan) -> its number as gfmt prints it (15 digits); not a number: as written (the
// tools' float())
function vcdReal(x) {
  const s = x.toLowerCase(), m = /^([+-]?)(?:(inf(?:inity)?)|nan)$/.exec(s);
  if (m) return gfmt(m[2] ? (m[1] === '-' ? -Infinity : Infinity) : NaN, 15);
  return /^[+-]?(\d+\.?\d*|\.\d+)(e[+-]?\d+)?$/.test(s) ? gfmt(Number(s), 15) : x;
}
// VHDL's nine values in VCD digits: U W - unknown, H L weak 1 / 0
const vcdBits = b => b.replace(/[uw-]/g, 'x').replace(/h/g, '1').replace(/l/g, '0');
// a VCD vector value (binary, maybe shorter than the width: extended with 0, or x / z) -> hex as GTKWave shows it
// (hexOf: a nibble all z is z, one with an x or a partial z is x); all x / all z one letter; a bit its level
function vcdHex(b, w) {
  b = vcdExt(b, w);
  if (w === 1) return b;
  if (/^x+$/.test(b)) return 'x'; if (/^z+$/.test(b)) return 'z';
  return mixedBits(b) ? "'b" + b : hexOf(b);   // a nibble of known bits and x / z: its binary digits (hex would make it x)
}
