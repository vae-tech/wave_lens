/* wavelens src/vcd.js — a VCD read in the page (Open… / a file dropped on a viewer): WaveJSON with exact transitions */

/* ---------------- VCD -> WaveJSON ---------------- */
// The signals of a VCD as WaveJSON groups by scope (the "tv" extension: [[ps, value]], a bus's value in hex, x / z
// kept), "time" in ps, "scopes" with the struct / union / interface scopes. A big dump is cut to fit a page: the
// signals nearest the top first, until `budget` value changes; -> {doc, shown, total, changes}. An FST is binary:
// sva vcd, fst2vcd (GTKWave) or make html. The rules are tools/dumpscan.py's (its tests in tests/unit compare the two): the
// reference of a $var (parse_ref: an escaped \name whole, a range glued or apart is the vector's, a 1-bit "err[3]" a
// bit of "err", "mem[1]" an element "mem.[1]"), the same path under two id codes with one range merged, a path in
// parts (bits "err[0]" "err[1]", ranges apart "data [7:0]" "data [15:8]") one vector from its lowest index to its highest,
// real (realtime shortreal real_parameter) and string variables as texts ("kind"), the enum tables of an FST
// written as text ("enum": FSM states by name), integer variables signed decimal ("radix"), events left out, $comment … $end
// skipped in the body, VHDL's U W H L - folded, time in order.
// What it noticed on the way goes to `log`: [{level: error | warning | info, line, text}] (a line of the text, 1 the first;
// none: the whole dump), at most VCD_SAME of a kind and then how many more; `info`: the dump's parameters ($version,
// $date, $timescale, its time, scopes, signals, changes). An error it cannot read past is thrown with its line (e.line).
const VCD_UNIT = { s: 1e12, ms: 1e9, us: 1e6, ns: 1e3, ps: 1, fs: 1e-3, as: 1e-6, zs: 1e-9 };
const VCD_TEXT = { real: 'real', realtime: 'real', shortreal: 'real', real_parameter: 'real', string: 'string' };   // -> "kind"
// integer variables (Questa writes an int-based enum as one): signed decimal unless they have an enum table
const VCD_INT = new Set(['integer', 'int', 'shortint', 'longint', 'byte']);
const VCD_SAME = 20;   // notes of one kind kept in the log
// the lines (1 the first) of offsets into text: one walk over the text up to the last of them
function vcdLines(text, offs) {
  const at = [...new Set(offs)].sort((a, b) => a - b), out = new Map(); let line = 1, p = 0;
  for (const o of at) { for (let i = text.indexOf('\n', p); i >= 0 && i < o; i = text.indexOf('\n', i + 1)) { line++; p = i + 1; } out.set(o, line); }
  return out;
}
function vcdRef(toks) {   // the words of a $var after its code -> [name, range]
  let ref = toks[0] || '', rng = toks.length > 1 && toks[1][0] === '[' ? toks[1] : '';
  if (ref[0] !== '\\' && !rng) { const m = /^(.+?)(\[\d+:\d+\])$/.exec(ref); if (m) { ref = m[1]; rng = m[2]; } }
  return [ref, rng];
}
function vcdToWave(text, opts = {}) {
  const budget = opts.budget ?? 3e6, name = opts.name || 'dump.vcd';
  let i = 0, unit = 1, w0 = 0;   // w0: where the last word starts
  const word = () => { while (i < text.length && text.charCodeAt(i) <= 32) i++; const s = w0 = i; while (i < text.length && text.charCodeAt(i) > 32) i++;
    return text.slice(s, i); };
  const log = [], same = new Map(), info = { size: text.length, timescale: null, version: null, date: null };
  const note = (level, at, kind, msg) => { const n = (same.get(kind) || [0])[0] + 1; same.set(kind, [n, level, msg]);
    if (n <= VCD_SAME) log.push({ level, at, msg }); };
  const fail = (at, msg) => { const line = vcdLines(text, [at]).get(at), e = new Error(`${msg} (line ${line})`); e.line = line; throw e; };
  const upTo = () => { const s = i; for (let x = word(); x && x !== '$end'; x = word()); return text.slice(s, w0).trim(); };   // the words to $end
  const decls = new Map(), scope = [], kinds = {};   // path -> {path, name, scope, kind, depth, enum, ds: [[code, [msb, lsb] | null, size, glued bit]]}
  const codes = new Map();   // id code -> its widest size (0: a text; events too: a value of theirs is no stranger)
  const tables = {}; let pending = null;   // the enum tables of an FST as VCD text (fst2vcd -e, sva vcd): handle -> {value: label}
  // the header: $scope / $var / $upscope / $timescale / $attrbegin up to $enddefinitions
  for (;;) {
    const w = word(), at = w0; if (!w) fail(text.length, 'no $enddefinitions: not a VCD, or its header is cut off');
    if (w === '$enddefinitions') { word(); break; }
    if (w === '$scope') { const kind = word(), n = word(); word(); scope.push(n); if (kind !== 'module') kinds[scope.join('.')] = kind; }
    else if (w === '$upscope') { word(); if (!scope.length) note('warning', at, 'upscope', '$upscope without its $scope'); scope.pop(); }
    else if (w === '$timescale') { const t = upTo().replace(/\s+/g, ''), m = /^(\d+)(s|ms|us|ns|ps|fs|as|zs)$/.exec(t);
      unit = m ? +m[1] * VCD_UNIT[m[2]] : 1; info.timescale = m ? t : null;
      if (!m) note('warning', at, 'timescale', `$timescale "${t}" not understood: a step of 1 ps taken`); }
    else if (w === '$version' || w === '$date') info[w.slice(1)] = upTo().replace(/\s+/g, ' ') || null;
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
      const kind = word().toLowerCase(), sz = word(), size = Number.isInteger(+sz) && +sz >= 1 ? +sz : 1, code = word(), toks = [];
      const en = pending != null ? tables[pending] : null;
      pending = null;
      if ([kind, sz, code].includes('$end')) { note('warning', at, 'var', 'a $var without its type, size, code or name: left out'); continue; }
      for (let x = word(); x && x !== '$end'; x = word()) toks.push(x);
      if (!toks.length) { note('warning', at, 'var', 'a $var without its type, size, code or name: left out'); continue; }
      if (!VCD_TEXT[kind] && (!(+sz >= 1) || !Number.isInteger(+sz))) note('warning', at, 'size', `$var ${toks[0]}: its size "${sz}" is not a number ` +
        'of bits: 1 taken');
      codes.set(code, Math.max(codes.get(code) || 0, VCD_TEXT[kind] ? 0 : size));
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
          scope: !esc && leaf.includes('.') ? scope.concat(leaf.split('.').slice(0, -1)) : scope.slice(), ds: [], num: VCD_INT.has(kind) });
        if (en && !decls.get(path).enum) decls.get(path).enum = en;
      }
      decls.get(path).ds.push(d);
    }
    else if (w === '$end') continue;   // a stray end (the second $end of a comment that had one inside)
    else if (w[0] === '$') { upTo(); if (w !== '$comment' && w !== '$attrend') note('warning', at, 'section', `${w} is not a section of a VCD header: ` +
      'skipped'); }
    else note('warning', at, 'stray', `"${w.slice(0, 40)}" outside a section of the header: left out`);
  }
  if (scope.length) note('warning', w0, 'scope', `${scope.length} $scope without $upscope at $enddefinitions (${scope.join('.')})`);
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
  const scan = (fn, notes = false) => {   // notes: the first walk says what it could not read
    let p = body, t = 0, first = true; const n = text.length;
    while (p < n) {
      while (p < n && text.charCodeAt(p) <= 32) p++; if (p >= n) break;
      const s0 = p; while (p < n && text.charCodeAt(p) > 32) p++;
      const c = text[s0];
      if (c === '#') {
        const tn = Number(text.slice(s0 + 1, p)) * unit;
        if (!Number.isFinite(tn) || s0 + 1 === p) { if (notes) note('warning', s0, 'time', `"${text.slice(s0, p).slice(0, 40)}" is not a time: left out`);
          continue; }
        if (!first && tn < t) fail(s0, `time goes back: #${text.slice(s0 + 1, p)} after #${t / unit} (a VCD lists its times in order)`);
        t = tn; first = false; fn(null, t);
      }
      else if (c === '$') {   // $dumpvars $dumpall $dumpon $dumpoff $end: nothing; $comment and the like: to their $end
        const kw = text.slice(s0, p);
        if (!/^\$(dumpvars|dumpall|dumpon|dumpoff|end)$/.test(kw)) { const e = text.indexOf('$end', p); p = e < 0 ? n : e + 4;
          if (notes && e < 0) note('warning', s0, 'comment', `${kw} without its $end: the rest of the dump skipped`); }
      }
      else if ('bBrRsS'.includes(c)) {   // b… / r… / s… then its code
        while (p < n && text.charCodeAt(p) <= 32) p++; const k0 = p; while (p < n && text.charCodeAt(p) > 32) p++;
        const v = text.slice(s0 + 1, k0).trim();
        fn(text.slice(k0, p), t, c === 'b' || c === 'B' ? vcdBits(v.toLowerCase()) : v, c === 'r' || c === 'R' ? 'real' : c === 's' ||
          c === 'S' ? 'string' : 'b', s0);
      }
      else if ('01xzXZuUwWhHlL-'.includes(c)) fn(text.slice(s0 + 1, p), t, vcdBits(c.toLowerCase()), 'b', s0);
      else if (notes) note('warning', s0, 'token', `"${text.slice(s0, p).slice(0, 40)}" is not a value change: left out`);
    }
  };
  scan((k, t, val, kind, at) => {
    if (k == null) return;
    const w = codes.get(k);
    if (w === undefined) { note('warning', at, 'code', k ? `a value of "${k}", a code no $var declares: left out` : 'a value without its code: left out');
      return; }
    count.set(k, (count.get(k) || 0) + 1);
    if (kind !== 'b' || !w) return;
    if (val.length > w && val.slice(0, val.length - w).includes('1')) note('warning', at, 'wide', `${val.length} bits for "${k}" of ${w}: ` +
      `the last ${w} taken`);
    if (val.length > 1 ? /[^01xz]/.test(val) : !'01xz'.includes(val)) note('warning', at, 'digit', `"${val.slice(0, 40)}" for "${k}" is not binary: ` +
      'drawn as written');
  }, true);
  if (!vars.length) note('warning', null, 'novar', 'no $var: the dump has no signals');
  else if (!count.size) note('warning', null, 'empty', 'no value changes after $enddefinitions');
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
    if (v.enum) s.enum = v.enum; else if (v.num) s.radix = 'signed';
    node.get(key).push(s);
  }
  const scopes = {};
  for (const [p, k] of Object.entries(kinds)) if (node.has(p) && (k === 'struct' || k === 'union' || k === 'interface'))
    scopes[p] = k === 'interface' ? k : { kind: k, width: vars.filter(v => v.path.startsWith(p + '.')).reduce((n, v) => n + v.width, 0) };
  const end = Math.max(t1, (t0 ?? 0) + 1);
  const doc = { signal: out, head: { text: name }, time: { t0: t0 ?? 0, t1: end, cycle: (end - (t0 ?? 0)) / 40, unit: 'ps' }, config: {} };
  const still = vars.filter(v => keep.has(v) && !changes(v));
  if (still.length) note('info', null, 'still', `${still.length} signal${still.length === 1 ? ' has' : 's have'} no value in the dump (drawn x): ` +
    still.slice(0, 5).map(v => v.path).join(', ') + (still.length > 5 ? ' …' : ''));
  if (keep.size < vars.length) note('info', null, 'budget', `${keep.size} of ${vars.length} signals read: the levels nearest the top within ` +
    `dumpBudget (${budget} changes)`);
  for (const [, [n, level, msg]] of same) if (n > VCD_SAME) log.push({ level, at: null, msg: `${n - VCD_SAME} more like "${msg}"` });
  const lines = vcdLines(text, log.filter(x => x.at != null).map(x => x.at));
  Object.assign(info, { t0: t0 ?? 0, t1: end, scopes: new Set(vars.map(v => v.scope.join('.'))).size, signals: vars.length, shown: keep.size,
    changes: [...count.values()].reduce((a, b) => a + b, 0) });
  if (Object.keys(scopes).length) doc.scopes = scopes;
  const omitted = {};   // past the budget: in the dump, not in the page (its find says so), by scope
  for (const v of vars) if (!keep.has(v)) (omitted[v.scope.join('.')] ||= []).push(v.name);
  if (Object.keys(omitted).length) doc.meta = { omitted: { why: 'dumpBudget', paths: omitted } };
  return { doc, shown: shownVars.length, total: vars.length, changes: used, info,
    log: log.map(x => Object.assign({ level: x.level, text: x.msg }, x.at != null ? { line: lines.get(x.at) } : {})) };
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

/* ---------------- enum labels and struct fields from SystemVerilog sources (a VCD has none) ---------------- */
// The rules of tools/mkconfig.py sv_tables (the twin; tests/unit/sv/sources.sv with its expected tables for both):
// "typedef enum … {A, B = 2'd3} name_t;" and "typedef struct packed {…} name_t;" (fields MSB first; a member of a width
// it cannot tell leaves the struct out), then the declarations of signals with those types ("p::name_t a, b;", ports,
// arrays; not function arguments, not struct members) and "enum {…} st;". By the variable's name only: a name declared
// with two different types (two modules) gets nothing and a note says so; so does an enum it does not read (a value
// that is an expression or a parameter, labels by macro).
const SV_WORDS = new Set(['input', 'output', 'inout', 'ref', 'var', 'const', 'static', 'automatic', 'logic', 'wire', 'reg', 'bit', 'signed', 'unsigned']);
const SV_BASE = { logic: 1, bit: 1, reg: 1, wire: 1, byte: 8, shortint: 16, int: 32, integer: 32, longint: 64 };
const SV_ENUM = /\btypedef\s+enum\b\s*([^{;]*)\{([^}]*)\}\s*(\w+)\s*;/g, SV_STRUCT = /\btypedef\s+struct\s+packed\b[^{;]*\{([^}]*)\}\s*(\w+)\s*;/g;
const SV_ANON = /(?<!typedef)\s\benum\b[^{;]*\{([^}]*)\}\s*(\w+(?:\s*,\s*\w+)*)\s*;/g;
// what holds no signal declarations: function / task bodies, struct / union bodies (nested: the innermost first, until
// none is left); strings and comments are blanked before anything is read
const SV_SKIP = /\bfunction\b[\s\S]*?\bendfunction\b|\btask\b[\s\S]*?\bendtask\b/g, SV_BODY = /\b(?:struct|union)\b[^{};]*\{[^{}]*\}/g;
const SV_BLANK = /"(?:[^"\\\n]|\\[\s\S])*"|\/\/[^\n]*|\/\*[\s\S]*?\*\//g;   // (a string goes on after a backslash-newline)
const svSignalsText = t => { t = t.replace(SV_SKIP, ' '); for (let u = t.replace(SV_BODY, ' '); u !== t; u = t.replace(SV_BODY, ' ')) t = u; return t; };
const svRe = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// an enum label's value: its initializer ('' none: prev + 1) -> a number; null when it is not a literal (the table is left
// out rather than guessed)
function svValue(v, prev) {
  if (!v.trim()) return prev + 1;
  v = v.trim().replace(/_/g, '');   // (after: "_" alone is an identifier, not an omitted value)
  const m = /^(?:\d+)?'[sS]?([bodhBODH])([0-9a-fA-F]+)$/.exec(v);
  if (m) { const b = { b: 2, o: 8, d: 10, h: 16 }[m[1].toLowerCase()], ok = { 2: /^[01]+$/, 8: /^[0-7]+$/, 10: /^\d+$/, 16: /./ }[b];
    return ok.test(m[2]) ? parseInt(m[2], b) : null; }
  return /^\d+$/.test(v) ? parseInt(v, 10) : /^0[xX][0-9a-fA-F]+$/.test(v) ? parseInt(v.slice(2), 16) : null;
}
function svItems(body) {   // "A, B = 2'd3, C" -> {0: 'A', 3: 'B', 4: 'C'}; null: a label or value not read, or none
  const table = {}; let v = -1, n = 0;
  for (const it of body.split(',')) {
    const k = it.indexOf('='), name = (k < 0 ? it : it.slice(0, k)).trim();
    if (!name && k < 0) continue;
    if (!/^\w+$/.test(name)) return null;
    v = svValue(k < 0 ? '' : it.slice(k + 1), v);
    if (v == null) return null;
    table[v] = name; n++;
  }
  return n ? table : null;
}
function svDims(s) {   // "[7:0][1:0]" -> the bits they hold (1 for none), null when a bound is not a number
  let n = 1;
  for (const [, d] of s.matchAll(/\[([^\]]*)\]/g)) { const m = /^\s*(\d+)\s*:\s*(\d+)\s*$/.exec(d); if (!m) return null; n *= Math.abs(+m[1] - +m[2]) + 1; }
  return n;
}
// the sources' texts -> {enums: {variable: {value: label}}, fields: {variable: [{name, msb, lsb, enum?}]}, notes, files}
// (files: how many texts declared a type or a signal of one)
function svTables(texts) {
  texts = [].concat(texts || []).map(t => String(t).replace(SV_BLANK, m => (m[0] === '"' ? '""' : ' ')));
  const types = new Map(), widths = {}, bodies = new Map(), anon = [], notes = [], used = new Set(), twice = new Set();
  const unread = n => `enum ${n}: a label or value it does not read (an expression, a parameter, a macro): no labels`;
  texts.forEach((t, i) => {
    for (const m of t.matchAll(SV_ENUM)) {
      const table = svItems(m[2]), name = m[3]; used.add(i);
      if (!table) notes.push(unread(name));
      if (types.has(name) && JSON.stringify(types.get(name)) !== JSON.stringify(table) && !twice.has(name)) {   // p::t_t and q::t_t
        twice.add(name); notes.push(`enum ${name}: defined twice with different labels (two packages?): no labels`); }
      types.set(name, twice.has(name) ? null : table);
      const bm = /^(\w+)?\s*(?:signed|unsigned)?\s*((?:\[[^\]]*\]\s*)*)$/.exec(m[1].trim());
      const w = bm ? (bm[1] ? SV_BASE[bm[1]] ?? null : 32) : null, d = bm ? svDims(bm[2]) : null;
      if (w != null && d != null) widths[name] = w * d;
    }
    for (const m of t.matchAll(SV_STRUCT)) {
      if (bodies.has(m[2]) && bodies.get(m[2]) !== m[1]) { twice.add(m[2]); notes.push(`struct ${m[2]}: defined twice with different members: no fields`); }
      bodies.set(m[2], m[1]); used.add(i); }
    for (const m of svSignalsText(t).matchAll(SV_ANON)) {
      const table = svItems(m[1]); if (!table) notes.push(unread(m[2].trim()));
      for (const n of m[2].split(',')) anon.push([n.trim(), table]); used.add(i); }
  });
  for (const name of types.keys()) if (bodies.has(name)) {   // an enum in one package, a struct in another: which one is not known
    if (!twice.has(name)) { twice.add(name); notes.push(`${name}: defined as an enum and as a struct (two packages?): no labels, no fields`); }
    types.set(name, null); }
  const fields = new Map();
  for (let pass = 0; pass <= bodies.size; pass++) {   // nested typedefs: until nothing new resolves
    let grew = false;
    for (const [name, body] of bodies) {
      if (fields.has(name) || twice.has(name)) continue;
      let members = [];
      for (const decl of body.split(';').map(x => x.trim()).filter(Boolean)) {
        const m = /^(?:\w+::)?(\w+)\s*(?:signed|unsigned)?\s*((?:\[[^\]]*\]\s*)*)(\w+(?:\s*,\s*\w+)*)$/.exec(decl);
        const base = m && (SV_BASE[m[1]] || widths[m[1]]), d = m && svDims(m[2]);
        if (!base || d == null) { members = null; break; }
        for (const n of m[3].split(',')) members.push([n.trim(), base * d, types.get(m[1])]);
      }
      if (!members || !members.length) continue;
      let lsb = members.reduce((a, x) => a + x[1], 0); const out = [];
      for (const [n, w, e] of members) {
        lsb -= w; const f = { name: n, msb: lsb + w - 1, lsb };
        if (e) f.enum = Object.fromEntries(Object.entries(e).sort((a, b) => a[0] - b[0]));
        out.push(f);
      }
      fields.set(name, out); widths[name] = members.reduce((a, x) => a + x[1], 0); grew = true;
    }
    if (!grew) break;
  }
  // one name, one candidate: ['e', table] or ['s', fields]; null for an enum or struct it does not read (it takes the name)
  const cand = new Map(), clash = new Set();
  const put = (name, val) => { if (clash.has(name)) return;
    if (cand.has(name) && JSON.stringify(cand.get(name)) !== JSON.stringify(val)) { clash.add(name); cand.delete(name); return; }
    cand.set(name, val); };
  for (const [n, table] of anon) put(n, ['e', table]);
  const known = [...new Set([...types.keys(), ...fields.keys(), ...bodies.keys()])].sort((a, b) => b.length - a.length);
  if (known.length) {
    const decl = new RegExp(String.raw`\b(?:\w+::)?(${known.map(svRe).join('|')})\b\s+(?:\[[^\]]*\]\s*)*(\w+(?:\s*(?:\[[^\]]*\]\s*)*,\s*\w+)*)` +
      String.raw`\s*(?:\[[^\]]*\]\s*)*[;=,)]`, 'g');
    texts.forEach((t, i) => {
      for (const m of svSignalsText(t).matchAll(decl)) {
        const ty = m[1];
        for (const n of m[2].split(/\s*(?:\[[^\]]*\]\s*)*,\s*/)) {
          if (!n || SV_WORDS.has(n) || types.has(n) || fields.has(n)) continue;
          used.add(i);
          if (fields.has(ty)) put(n, ['s', fields.get(ty)]);
          else if (types.has(ty)) put(n, ['e', types.get(ty)]);   // an enum not read too: the name is taken
          else if (bodies.has(ty)) put(n, ['s', null]);   // a struct whose fields it cannot tell (or defined twice): the name is taken
        }
      }
    });
  }
  for (const n of [...clash].sort()) notes.push(`${n}: declared with different types (in different modules?): no labels`);
  const of = k => Object.fromEntries([...cand].filter(([, v]) => v[0] === k && v[1]).map(([n, v]) => [n, v[1]]));
  return { enums: of('e'), fields: of('s'), notes, files: used.size };
}
// two sets of tables as one (the second wins a name: Sources… over the workspace's)
const svMerge = (a, b) => { if (!a || !b) return a || b;
  const mine = new Set([...Object.keys(b.enums), ...Object.keys(b.fields)]), keep = o => Object.fromEntries(Object.entries(o).filter(([n]) => !mine.has(n)));
  return { enums: Object.assign(keep(a.enums), b.enums), fields: Object.assign(keep(a.fields), b.fields), notes: a.notes.concat(b.notes),
    files: a.files + b.files }; };
// the labels and fields of the sources onto the signals of a WaveJSON that have none (a name's table only when its values
// fit the signal's width; fields when they cover it, as mkconfig.py apply_sv) -> how many signals got them
// What it puts there is marked (svEnum, svFields): tables of other sources replace those, and only those (the dump's own
// tables and a config's stay); sources without a name's table take its labels away again.
function svApply(doc, sv) {
  if (!doc || !doc.signal) return 0;
  sv = sv || { enums: {}, fields: {} };
  let n = 0;
  const walk = items => { for (const it of items) {
    if (Array.isArray(it)) { walk(it.slice(typeof it[0] === 'string' ? 1 : 0)); continue; }
    if (!it || typeof it !== 'object' || !it.name || it.kind) continue;
    if (!it.tv) continue;   // a clock-sampled row's labels are made already (make html with mkconfig.py --sv does its own)
    // an element of an array (state.[0], state[0]): the array's name
    const leaf = String(it.path || it.name).replace(/(\.?\[-?\d+\])+$/, '').split('.').pop(), w = +it.width || 1, t = sv.enums && sv.enums[leaf];
    const fl = sv.fields && sv.fields[leaf];
    if (it.svEnum) { delete it.enum; delete it.svEnum; if (it.svRadix) it.radix = it.svRadix; delete it.svRadix; }   // the sources' before
    if (it.svFields) { delete it.fields; delete it.svFields; }
    let got = false;
    if (!it.enum && t && Object.keys(t).length && Math.max(...Object.keys(t).map(Number)) < 2 ** w) {   // (an integer's signed radix: the labels instead)
      it.enum = Object.fromEntries(Object.entries(t).map(([k, v]) => [String(k), v])); it.svEnum = true;
      if (it.radix === 'signed') { it.svRadix = it.radix; delete it.radix; }
      got = true; }
    if (!it.fields && fl && fl[0].msb + 1 === w) { it.fields = fl; it.svFields = true; got = true; }
    if (got) n++;
  } };
  walk(doc.signal);
  return n;
}
