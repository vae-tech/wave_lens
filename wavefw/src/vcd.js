/* wavefw src/vcd.js — a VCD read in the page (Open… / a file dropped on a viewer): WaveJSON with exact transitions */

/* ---------------- VCD -> WaveJSON ---------------- */
// The signals of a VCD as WaveJSON groups by scope (the "tv" extension: [[ps, value]], a bus's value in hex, x / z
// kept), "time" in ps, "scopes" with the struct / union / interface scopes. A big dump is cut to fit a page: the
// signals nearest the top first, until `budget` value changes (opts.depth: scope levels below the top, all when
// null); -> {doc, shown, total, changes}. An FST is binary: fst2vcd (GTKWave) or make html.
const VCD_UNIT = { s: 1e12, ms: 1e9, us: 1e6, ns: 1e3, ps: 1, fs: 1e-3 };
function vcdToWave(text, opts = {}) {
  const budget = opts.budget ?? 3e6, name = opts.name || 'dump.vcd';
  let i = 0, unit = 1;
  const word = () => { while (i < text.length && text.charCodeAt(i) <= 32) i++; const s = i; while (i < text.length && text.charCodeAt(i) > 32) i++; return text.slice(s, i); };
  const vars = [], byCode = new Map(), scope = [], kinds = {};
  // the header: $scope / $var / $upscope / $timescale up to $enddefinitions
  for (;;) {
    const w = word(); if (!w) throw new Error('no $enddefinitions: not a VCD');
    if (w === '$enddefinitions') { word(); break; }
    if (w === '$scope') { const kind = word(), n = word(); word(); scope.push(n); if (kind !== 'module') kinds[scope.join('.')] = kind; }
    else if (w === '$upscope') { word(); scope.pop(); }
    else if (w === '$timescale') { let t = ''; for (let x = word(); x && x !== '$end'; x = word()) t += x; const m = /^(\d+)(s|ms|us|ns|ps|fs)$/.exec(t); unit = m ? +m[1] * VCD_UNIT[m[2]] : 1; }
    else if (w === '$var') {
      const type = word(), size = +word(), code = word(); let ref = word(), x = word();
      while (x && x !== '$end') x = word();   // the range ([7:0]) is the width's
      const r = ref.replace(/\s+/g, ''), el = r.includes('[') ? r.replace('[', '.[') : r;   // an array element regs[1]: "[1]" under regs (dumpscan's spelling)
      const v = { path: scope.concat(el).join('.'), name: el.split('.').pop(), width: size || 1, code, real: type === 'real', depth: scope.length };
      vars.push(v); if (!byCode.has(code)) byCode.set(code, []); byCode.get(code).push(v);
    }
    else if (w[0] === '$') { for (let x = word(); x && x !== '$end'; x = word()); }   // $date $version $comment …
  }
  // the value changes, token by token (one per line or several on a line): #time, 0! 1! x! z!, b0101 !, r1.5 !
  const body = i, count = new Map();
  const scan = fn => {
    let p = body, t = 0; const n = text.length;
    while (p < n) {
      while (p < n && text.charCodeAt(p) <= 32) p++; if (p >= n) break;
      const s0 = p; while (p < n && text.charCodeAt(p) > 32) p++;
      const c = text.charCodeAt(s0);
      if (c === 35) { t = Number(text.slice(s0 + 1, p)) * unit; fn(null, t); }   // #time
      else if (c === 98 || c === 66 || c === 114 || c === 82) {   // b… / r… then its code
        while (p < n && text.charCodeAt(p) <= 32) p++; const k0 = p; while (p < n && text.charCodeAt(p) > 32) p++;
        fn(text.slice(k0, p), t, c === 98 || c === 66 ? text.slice(s0 + 1, k0).trim().toLowerCase() : null);
      }
      else if (c === 48 || c === 49 || c === 120 || c === 88 || c === 122 || c === 90) fn(text.slice(s0 + 1, p), t, text[s0].toLowerCase(), true);
    }
  };
  scan(k => { if (k != null) count.set(k, (count.get(k) || 0) + 1); });
  const order = [...new Set(vars.filter(v => !v.real && (opts.depth == null || v.depth <= opts.depth + 1)).sort((a, b) => a.depth - b.depth).map(v => v.code))];
  const keep = new Set(); let used = 0;
  for (const k of order) { const n = count.get(k) || 0; if (used + n > budget && keep.size) continue; keep.add(k); used += n; }
  // the transitions of the codes kept
  const tv = new Map([...keep].map(k => [k, []])), w1 = new Map(vars.map(v => [v.code, v.width]));
  let t0 = null, t1 = 0;
  scan((k, t, val, bit) => {
    if (k == null) { if (t0 == null) t0 = t; t1 = Math.max(t1, t); return; }
    const a = tv.get(k); if (!a || val == null) return;
    const w = w1.get(k), x = bit ? (w > 1 ? vcdHex(val, w) : val) : vcdHex(val, w);
    const L = a[a.length - 1]; if (L && L[1] === x) return; if (L && L[0] === t) L[1] = x; else a.push([t, x]);
  });
  // WaveJSON: groups by scope in declaration order
  const out = [], node = new Map([['', out]]);
  const shownVars = vars.filter(v => keep.has(v.code));
  for (const v of shownVars) {
    const parts = v.path.split('.'); parts.pop();
    let key = '';
    for (const p of parts) { const k2 = key ? key + '.' + p : p; if (!node.has(k2)) { const g = [p]; node.get(key).push(g); node.set(k2, g); } key = k2; }
    const s = { name: v.name, path: v.path, tv: tv.get(v.code) }; if (v.width > 1) s.width = v.width;
    node.get(key).push(s);
  }
  const scopes = {};
  for (const [p, k] of Object.entries(kinds)) if (node.has(p) && (k === 'struct' || k === 'union' || k === 'interface'))
    scopes[p] = k === 'interface' ? k : { kind: k, width: vars.filter(v => v.path.startsWith(p + '.')).reduce((n, v) => n + v.width, 0) };
  const end = Math.max(t1, (t0 ?? 0) + 1);
  const doc = { signal: out, head: { text: name }, time: { t0: t0 ?? 0, t1: end, cycle: (end - (t0 ?? 0)) / 40, unit: 'ps' }, config: {} };
  if (Object.keys(scopes).length) doc.scopes = scopes;
  return { doc, shown: shownVars.length, total: vars.filter(v => !v.real).length, changes: used };
}
// a VCD vector value (binary, maybe shorter than the width: extended with 0, or x / z) -> hex, x / z digits kept
function vcdHex(b, w) {
  if (b.length < w) b = (b[0] === 'x' || b[0] === 'z' ? b[0] : '0').repeat(w - b.length) + b;
  if (/^x+$/.test(b)) return 'x'; if (/^z+$/.test(b)) return 'z';
  const p = b.padStart(Math.ceil(b.length / 4) * 4, '0'); let h = '';
  for (let k = 0; k < p.length; k += 4) { const n = p.slice(k, k + 4); h += /x/.test(n) ? 'x' : /z/.test(n) ? 'z' : parseInt(n, 2).toString(16); }
  return h;
}
