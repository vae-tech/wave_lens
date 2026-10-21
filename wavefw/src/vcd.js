/* wavefw src/vcd.js — a VCD read in the page (Open… / a file dropped on a viewer): WaveJSON with exact transitions */

/* ---------------- VCD -> WaveJSON ---------------- */
// The signals of a VCD as WaveJSON groups by scope (the "tv" extension: [[ps, value]], a bus's value in hex, x / z
// kept), "time" in ps, "scopes" with the struct / union / interface scopes. A big dump is cut to fit a page: the
// signals nearest the top first, until `budget` value changes; -> {doc, shown, total, changes}. An FST is binary:
// sva vcd, fst2vcd (GTKWave) or make html. The rules are tools/dumpscan.py's (its tests in tests/unit compare the two): the
// reference of a $var (parse_ref: an escaped \name whole, a range glued or apart is the vector's, a 1-bit "err[3]" a
// bit of "err", "mem[1]" an element "mem.[1]"), the same path under two id codes merged, real and string variables
// as texts ("kind"), events left out, $comment … $end skipped in the body, VHDL's U W H L - folded, time in order.
const VCD_UNIT = { s: 1e12, ms: 1e9, us: 1e6, ns: 1e3, ps: 1, fs: 1e-3, as: 1e-6, zs: 1e-9 };
const VCD_TEXT = { real: 1, string: 1 };
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
  const vars = [], byPath = new Map(), byCode = new Map(), scope = [], kinds = {}, blasted = new Map();
  const own = (code, v, bit) => { if (!byCode.has(code)) byCode.set(code, []); byCode.get(code).push([v, bit]); };
  // the header: $scope / $var / $upscope / $timescale up to $enddefinitions
  for (;;) {
    const w = word(); if (!w) throw new Error('no $enddefinitions: not a VCD, or its header is cut off');
    if (w === '$enddefinitions') { word(); break; }
    if (w === '$scope') { const kind = word(), n = word(); word(); scope.push(n); if (kind !== 'module') kinds[scope.join('.')] = kind; }
    else if (w === '$upscope') { word(); scope.pop(); }
    else if (w === '$timescale') { let t = ''; for (let x = word(); x && x !== '$end'; x = word()) t += x; const m = /^(\d+)(s|ms|us|ns|ps|fs|as|zs)$/.exec(t);
      unit = m ? +m[1] * VCD_UNIT[m[2]] : 1; }
    else if (w === '$var') {
      const kind = word().toLowerCase(), size = +word() || 1, code = word(), toks = [];
      for (let x = word(); x && x !== '$end'; x = word()) toks.push(x);
      if (kind === 'event') continue;   // no value to draw
      const [ref, rng] = vcdRef(toks), esc = ref[0] === '\\', m = esc ? null : /^(.+)\[(\d+)\]$/.exec(ref);
      if (m && !rng && size === 1 && !VCD_TEXT[kind]) {   // one bit of a bit-blasted vector: the vector under its name
        const path = scope.concat(m[1]).join('.');
        let v = blasted.get(path);
        if (!v) { v = { path, name: m[1], scope: scope.slice(), width: 0, bits: [], depth: scope.length }; blasted.set(path, v); vars.push(v); }
        v.width = Math.max(v.width, +m[2] + 1); v.bits.push(code); own(code, v, +m[2]);
        continue;
      }
      const leaf = !esc && ref.includes('[') ? ref.replace('[', '.[') : ref, path = scope.concat(leaf).join('.');
      let v = byPath.get(path);
      if (v) { if (!v.codes.includes(code)) { v.codes.push(code); own(code, v, null); } continue; }   // the same path again: merged
      v = { path, name: leaf.split('.').pop(), scope: !esc && leaf.includes('.') ? scope.concat(leaf.split('.').slice(0, -1)) : scope.slice(),
        width: size, kind: VCD_TEXT[kind] ? kind : null, codes: [code], depth: scope.length };
      if (esc) v.name = leaf;
      byPath.set(path, v); vars.push(v); own(code, v, null);
    }
    else if (w[0] === '$') { for (let x = word(); x && x !== '$end'; x = word()); }   // $date $version $comment …
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
  const changes = v => (v.codes || v.bits).reduce((s, k) => s + (count.get(k) || 0), 0);
  const order = vars.slice().sort((a, b) => a.depth - b.depth);   // stable: declaration order inside a level
  const keep = new Set(); let used = 0;
  // the levels nearest the top, as many as fit
  for (const v of order) { const n = changes(v); if (used + n > budget && keep.size) break; keep.add(v); used += n; }
  // the transitions of the variables kept: per id code, then per variable (codes merged, bits put together)
  const raw = new Map(); for (const v of keep) for (const k of v.codes || v.bits) raw.set(k, []);
  let t0 = null, t1 = 0;
  scan((k, t, val) => {
    if (k == null) { if (t0 == null) t0 = t; t1 = Math.max(t1, t); return; }
    if (t0 == null) t0 = t;   // values before the first time (a $dumpvars block): the dump starts at 0
    const a = raw.get(k); if (a && val != null) a.push([t, val]);
  });
  const tvOf = v => {
    const out = [], put = (t, x) => { const L = out[out.length - 1]; if (L && L[0] === t) { L[1] = x;
      if (out.length > 1 && out[out.length - 2][1] === x) out.pop(); } else if (!L || L[1] !== x) out.push([t, x]); };
    if (v.bits) {   // a bit-blasted vector: its bits after every time step with a change of any of them
      const st = new Array(v.width).fill('x'), ev = v.bits.flatMap(k => raw.get(k).map(([t, x]) => [t, byCode.get(k).find(o => o[0] === v)[1], x]));
      ev.sort((a, b) => a[0] - b[0]);
      ev.forEach(([t, b, x], j) => { st[v.width - 1 - b] = x.slice(-1); if (j + 1 === ev.length || ev[j + 1][0] !== t) put(t, vcdHex(st.join(''), v.width)); });
      return out;
    }
    const ev = v.codes.length === 1 ? raw.get(v.codes[0]) : v.codes.flatMap(k => raw.get(k)).sort((a, b) => a[0] - b[0]);
    for (const [t, x] of ev) put(t, v.kind === 'real' ? gfmt(parseFloat(x), 15) : v.kind === 'string' ? x : vcdHex(x, v.width));
    return out;
  };
  // WaveJSON: groups by scope in declaration order
  const out = [], node = new Map([['', out]]);
  const shownVars = vars.filter(v => keep.has(v));
  for (const v of shownVars) {
    let key = '';
    for (const p of v.scope) { const k2 = key ? key + '.' + p : p; if (!node.has(k2)) { const g = [p]; node.get(key).push(g); node.set(k2, g); } key = k2; }
    const s = { name: v.name, path: v.path, tv: tvOf(v) }; if (v.width > 1) s.width = v.width; if (v.kind) s.kind = v.kind;
    node.get(key).push(s);
  }
  const scopes = {};
  for (const [p, k] of Object.entries(kinds)) if (node.has(p) && (k === 'struct' || k === 'union' || k === 'interface'))
    scopes[p] = k === 'interface' ? k : { kind: k, width: vars.filter(v => v.path.startsWith(p + '.')).reduce((n, v) => n + v.width, 0) };
  const end = Math.max(t1, (t0 ?? 0) + 1);
  const doc = { signal: out, head: { text: name }, time: { t0: t0 ?? 0, t1: end, cycle: (end - (t0 ?? 0)) / 40, unit: 'ps' }, config: {} };
  if (Object.keys(scopes).length) doc.scopes = scopes;
  return { doc, shown: shownVars.length, total: vars.length, changes: used };
}
// VHDL's nine values in VCD digits: U W - unknown, H L weak 1 / 0
const vcdBits = b => b.replace(/[uw-]/g, 'x').replace(/h/g, '1').replace(/l/g, '0');
// a VCD vector value (binary, maybe shorter than the width: extended with 0, or x / z) -> hex as GTKWave shows it
// (hexOf: a nibble all z is z, one with an x or a partial z is x); all x / all z one letter; a bit its level
function vcdHex(b, w) {
  if (b.length < w) b = (b[0] === 'x' || b[0] === 'z' ? b[0] : '0').repeat(w - b.length) + b;
  else if (b.length > w) b = b.slice(b.length - w);
  if (w === 1) return b;
  if (/^x+$/.test(b)) return 'x'; if (/^z+$/.test(b)) return 'z';
  return hexOf(b);
}
