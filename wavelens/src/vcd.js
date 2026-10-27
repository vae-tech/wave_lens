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
// opts.lazy: the text is a dump's header (sva vcd --header: the declarations, the first and last times) and every
// variable is a signal whose changes come later ("lazy": its id codes; a viewer reads them as it needs them, fillRows).
const VCD_UNIT = { s: 1e12, ms: 1e9, us: 1e6, ns: 1e3, ps: 1, fs: 1e-3, as: 1e-6, zs: 1e-9 };
const VCD_TEXT = { real: 'real', realtime: 'real', shortreal: 'real', real_parameter: 'real', string: 'string' };   // -> "kind"
// integer variables (Questa writes an int-based enum as one): signed decimal unless they have an enum table
const VCD_INT = new Set(['integer', 'int', 'shortint', 'longint', 'byte']);
const VCD_SAME = 20;   // notes of one kind kept in the log
function vcdRef(toks) {   // the words of a $var after its code -> [name, range]
  let ref = toks[0] || '', rng = toks.length > 1 && toks[1][0] === '[' ? toks[1] : '';
  if (ref[0] !== '\\' && !rng) { const m = /^(.+?)(\[\d+:\d+\])$/.exec(ref); if (m) { ref = m[1]; rng = m[2]; } }
  return [ref, rng];
}
// The reader is a generator over the text in pieces, so that a big dump is never all in memory (vcdToWaveFile: a File read
// twice, piece by piece; vcdToWave: the whole text as one piece). It yields {pass, n}: the n-th piece of the text from its
// start in this pass (1: the header and the count of the changes, 2: the transitions of the signals kept), and takes the
// string, or null at the end. A token cut at the end of a piece, a value whose code is on the next line and a $comment
// whose $end is not there yet wait for the next piece.
function vcdToWave(text, opts = {}) {
  const g = vcdRead(opts, text.length); let r = g.next();
  while (!r.done) r = g.next(r.value.n === 0 ? text : null);
  return r.value;
}
// a File (Open…, Compare…, a file dropped): read in pieces of about 8 MB (TextDecoder: a character cut between two reads
// waits for the next one) -> the same as vcdToWave of its text; chunk: the size of a piece (the tests: a few bytes)
async function vcdToWaveFile(file, opts = {}, chunk = 8 << 20) {
  const g = vcdRead(opts, file.size); let r = g.next(), rd = null, dec = null, end = false, buf = '';
  const piece = async () => {   // at most chunk characters (the reads the browser makes: as they come)
    while (buf.length < chunk && !end) {
      const { value, done } = await rd.read();
      if (done) { buf += dec.decode(); end = true; } else buf += dec.decode(value, { stream: true });
    }
    const s = buf.length > chunk ? buf.slice(0, chunk) : buf; buf = buf.length > chunk ? buf.slice(chunk) : '';
    return s || null;
  };
  try {
    while (!r.done) {
      if (r.value.n === 0) { if (rd) rd.cancel().catch(() => {}); rd = file.stream().getReader(); dec = new TextDecoder(); end = false; buf = ''; }
      r = g.next(await piece());
    }
  } finally { if (rd) rd.cancel().catch(() => {}); }
  return r.value;
}
function* vcdRead(opts = {}, size = 0) {
  const lazy = !!opts.lazy, budget = lazy ? Infinity : opts.budget ?? 3e6, name = opts.name || 'dump.vcd';
  // the header: pieces until its "$enddefinitions $end" (the whole text at once: vcdToWave), its words read on as the
  // parser below takes them: a section ($comment, $var …) to its $end, so "$enddefinitions" in a comment is not the end
  let text = '', n0 = 0, eof = false, hw = 0, sec = false, defs = false;
  const headEnd = () => {   // the words read so far, a word cut at the end of the text waiting for the next piece
    for (;;) {
      let a = hw; while (a < text.length && text.charCodeAt(a) <= 32) a++;
      let b = a; while (b < text.length && text.charCodeAt(b) > 32) b++;
      if (b === text.length) return false;
      hw = b;
      if (defs) return true;   // the word after it (its $end)
      if (text.charCodeAt(a) !== 36) continue;   // not a $word
      const w = text.slice(a, b);
      if (sec) sec = w !== '$end'; else if (w === '$enddefinitions') defs = true; else sec = w !== '$end';
    }
  };
  for (;;) {
    const s = yield { pass: 1, n: n0++ };
    if (s == null) { eof = true; break; }
    text += s;
    if (headEnd()) break;
  }
  // the line of a character of the text (1 the first), counted on as the notes come (in the order of the text): cur is
  // the piece read now, at its offset in the text
  const ln = { pos: 0, line: 1 }; let cur = text, curAt = 0;
  const lineAt = g => { for (let j = cur.indexOf('\n', ln.pos - curAt); j >= 0 && j < g - curAt; j = cur.indexOf('\n', j + 1)) ln.line++;
    ln.pos = Math.max(ln.pos, g); return ln.line; };
  let i = 0, unit = 1, w0 = 0;   // w0: where the last word starts
  const word = () => { while (i < text.length && text.charCodeAt(i) <= 32) i++; const s = w0 = i; while (i < text.length && text.charCodeAt(i) > 32) i++;
    return text.slice(s, i); };
  const log = [], same = new Map(), info = { size, timescale: null, version: null, date: null };
  const note = (level, at, kind, msg) => { const n = (same.get(kind) || [0])[0] + 1; same.set(kind, [n, level, msg]);
    if (n <= VCD_SAME) log.push({ level, line: at != null ? lineAt(at) : null, msg }); };
  const fail = (at, msg) => { const line = lineAt(at), e = new Error(`${msg} (line ${line})`); e.line = line; throw e; };
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
        const t = {}; for (let j = 0; j < n; j++) if (/^[01]+$/.test(b[2 + n + j])) t[BigInt('0b' + b[2 + n + j])] = b[2 + j];   // (exact past 2^53)
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
  // step: the whole tokens of piece s from p (last: nothing comes after it) -> where the rest starts that waits for the
  // next piece; fn(code, t, value, kind, at) with at the offset in the text, (null, t) at a time
  const body = i;
  const step = (s, p, last, fn, notes, st, at0) => {
    const n = s.length;
    while (p < n) {
      while (p < n && s.charCodeAt(p) <= 32) p++; if (p >= n) break;
      const s0 = p; while (p < n && s.charCodeAt(p) > 32) p++;
      if (p >= n && !last) return s0;   // cut at the end of the piece, maybe
      const c = s[s0];
      if (c === '#') {
        const tn = Number(s.slice(s0 + 1, p)) * unit;
        if (!Number.isFinite(tn) || s0 + 1 === p) { if (notes) note('warning', at0 + s0, 'time', `"${s.slice(s0, p).slice(0, 40)}" is not a time: left out`);
          continue; }
        if (!st.first && tn < st.t) fail(at0 + s0, `time goes back: #${s.slice(s0 + 1, p)} after #${st.t / unit} (a VCD lists its times in order)`);
        st.t = tn; st.first = false; fn(null, st.t);
      }
      else if (c === '$') {   // $dumpvars $dumpall $dumpon $dumpoff $end: nothing; $comment and the like: to their $end
        const kw = s.slice(s0, p);
        if (!/^\$(dumpvars|dumpall|dumpon|dumpoff|end)$/.test(kw)) { const e = s.indexOf('$end', p);
          if (e < 0 && !last) return s0;
          p = e < 0 ? n : e + 4;
          if (notes && e < 0) note('warning', at0 + s0, 'comment', `${kw} without its $end: the rest of the dump skipped`); }
      }
      else if ('bBrRsS'.includes(c)) {   // b… / r… / s… then its code
        while (p < n && s.charCodeAt(p) <= 32) p++; const k0 = p; while (p < n && s.charCodeAt(p) > 32) p++;
        if (p >= n && !last) return s0;   // its code in the next piece
        const v = s.slice(s0 + 1, k0).trim();
        fn(s.slice(k0, p), st.t, c === 'b' || c === 'B' ? vcdBits(v.toLowerCase()) : v, c === 'r' || c === 'R' ? 'real' : c === 's' ||
          c === 'S' ? 'string' : 'b', at0 + s0);
      }
      else if ('01xzXZuUwWhHlL-'.includes(c)) fn(s.slice(s0 + 1, p), st.t, vcdBits(c.toLowerCase()), 'b', at0 + s0);
      else if (notes) note('warning', at0 + s0, 'token', `"${s.slice(s0, p).slice(0, 40)}" is not a value change: left out`);
    }
    return n;
  };
  // one walk over the changes: pass 1 from the body in the header's text on, then the pieces after it; pass 2 from the
  // start of the text again, the header skipped
  function* scan(pass, fn, notes = false) {
    const st = { t: 0, first: true };
    let s, p, at0, k = 0, skip = body;
    if (pass === 1) { s = text; p = body; at0 = 0; k = n0; }
    else {
      for (;;) { s = yield { pass, n: k++ }; if (s == null) return; if (skip < s.length) break; skip -= s.length; }
      p = skip; at0 = body - skip;
    }
    for (let end = pass === 1 && eof; ;) {
      cur = s; curAt = at0;
      const r = step(s, p, end, fn, notes, st, at0);
      if (end) return;
      const next = yield { pass, n: k++ };
      if (pass === 1 && notes) lineAt(at0 + r);   // the lines of what is behind (the notes after it count from there)
      const rest = s.slice(r);
      at0 += r; p = 0;
      if (next == null) { s = rest; end = true; } else s = rest + next;
    }
  }
  const count = new Map();
  yield* scan(1, (k, t, val, kind, at) => {
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
  else if (!count.size && !lazy) note('warning', null, 'empty', 'no value changes after $enddefinitions');
  const changes = v => v.codes.reduce((s, k) => s + (count.get(k) || 0), 0);
  const order = vars.slice().sort((a, b) => a.depth - b.depth);   // stable: declaration order inside a level
  const keep = new Set(); let used = 0;
  // the levels nearest the top, as many as fit
  for (const v of order) { const n = changes(v); if (used + n > budget && keep.size) break; keep.add(v); used += n; }
  // the transitions of the variables kept: per id code, then per variable (codes merged, bits put together)
  const raw = new Map(); for (const v of keep) for (const k of v.codes) raw.set(k, []);
  let t0 = null, t1 = 0;
  text = cur = null;   // (the header's text: not needed any more)
  yield* scan(2, (k, t, val) => {
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
    if (lazy) s.lazy = v.codes;
    if (v.enum) s.enum = v.enum; else if (v.num) s.radix = 'signed';
    node.get(key).push(s);
  }
  const scopes = {};
  for (const [p, k] of Object.entries(kinds)) if (node.has(p) && (k === 'struct' || k === 'union' || k === 'interface'))
    scopes[p] = k === 'interface' ? k : { kind: k, width: vars.filter(v => v.path.startsWith(p + '.')).reduce((n, v) => n + v.width, 0) };
  const end = Math.max(t1, (t0 ?? 0) + 1);
  const doc = { signal: out, head: { text: name }, time: { t0: t0 ?? 0, t1: end, cycle: (end - (t0 ?? 0)) / 40, unit: 'ps' }, config: {} };
  const still = vars.filter(v => keep.has(v) && !changes(v));
  if (still.length && !lazy) note('info', null, 'still', `${still.length} signal${still.length === 1 ? ' has' : 's have'} no value in the dump (drawn x): ` +
    still.slice(0, 5).map(v => v.path).join(', ') + (still.length > 5 ? ' …' : ''));
  if (keep.size < vars.length) note('info', null, 'budget', `${keep.size} of ${vars.length} signals read: the levels nearest the top within ` +
    `dumpBudget (${budget} changes)`);
  for (const [, [n, level, msg]] of same) if (n > VCD_SAME) log.push({ level, line: null, msg: `${n - VCD_SAME} more like "${msg}"` });
  Object.assign(info, { t0: t0 ?? 0, t1: end, scopes: new Set(vars.map(v => v.scope.join('.'))).size, signals: vars.length, shown: keep.size,
    changes: [...count.values()].reduce((a, b) => a + b, 0) });
  if (Object.keys(scopes).length) doc.scopes = scopes;
  const omitted = {};   // past the budget: in the dump, not in the page (its find says so), by scope
  for (const v of vars) if (!keep.has(v)) (omitted[v.scope.join('.')] ||= []).push(v.name);
  if (Object.keys(omitted).length) doc.meta = { omitted: { why: 'dumpBudget', paths: omitted } };
  return { doc, shown: shownVars.length, total: vars.length, changes: used, info,
    log: log.map(x => Object.assign({ level: x.level, text: x.msg }, x.line != null ? { line: x.line } : {})) };
}
// the signals of vcdToWave's WaveJSON, out of their groups
const vcdSignals = a => a.flatMap(x => (Array.isArray(x) ? vcdSignals(x.slice(1)) : [x]));
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
// with two different types (two modules; one a plain vector) gets nothing and a note says so; so does an enum it does not read (a value
// that is an expression or a parameter, labels by macro).
const SV_WORDS = new Set(['input', 'output', 'inout', 'ref', 'var', 'const', 'static', 'automatic', 'logic', 'wire', 'reg', 'bit', 'signed', 'unsigned']);
const SV_BASE = { logic: 1, bit: 1, reg: 1, wire: 1, byte: 8, shortint: 16, int: 32, integer: 32, longint: 64 };
const SV_ENUM = /\btypedef\s+enum\b\s*([^{;]*)\{([^}]*)\}\s*(\w+)\s*;/g, SV_STRUCT = /\btypedef\s+struct\s+packed\b[^{;]*\{([^}]*)\}\s*(\w+)\s*;/g;
const SV_ANON = /(?<!typedef)\s\benum\b[^{;]*\{([^}]*)\}\s*(\w+(?:\s*,\s*\w+)*)\s*;/g;
// what holds no signal declarations: function / task bodies, struct / union bodies (nested: the innermost first, until
// none is left); strings and comments are blanked before anything is read
const SV_SKIP = /\bfunction\b[\s\S]*?\bendfunction\b|\btask\b[\s\S]*?\bendtask\b/g, SV_BODY = /\b(?:struct|union)\b[^{};]*\{[^{}]*\}/g;
const SV_BLANK = /"(?:[^"\\\n]|\\[\s\S])*"|\/\/[^\n]*|\/\*[\s\S]*?\*\//g;   // (a string goes on after a backslash-newline)
// a plain vector or integer variable ("logic [1:0] state;", a port): a name it has besides a type's is not labelled
const SV_PLAIN = new RegExp(String.raw`\b(?:logic|reg|wire|bit|byte|shortint|int|longint|integer)\b\s*(?:signed|unsigned)?\s*(?:\[[^\]]*\]\s*)*` +
  String.raw`(\w+(?:\s*(?:\[[^\]]*\]\s*)*,\s*\w+)*)\s*(?:\[[^\]]*\]\s*)*[;=,)]`, 'gd');   // (d: where its list starts)
// the names a declaration declares, its list read from offset at: "a [3:0] = f(x, y), b, c;" -> [a, b, c]; it ends at the ;
// (or the ) of a port list), and a part that is not "name [dims] = value" (the next port's type) is none (mkconfig sv_names)
function svNames(t, at) {
  const parts = []; let depth = 0, cur = '';
  for (let i = at; i < t.length; i++) { const ch = t[i];
    if ('([{'.includes(ch)) depth++;
    else if (')]}'.includes(ch)) { if (!depth) break; depth--; }
    else if (!depth && (ch === ',' || ch === ';')) { parts.push(cur); cur = ''; if (ch === ';') break; continue; }
    cur += ch; }
  parts.push(cur);
  return parts.map(x => /^\s*(\w+)\s*(?:\[[^\]]*\]\s*)*(?:=[\s\S]*)?$/.exec(x)).filter(Boolean).map(m => m[1]);
}
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
      String.raw`\s*(?:\[[^\]]*\]\s*)*[;=,)]`, 'gd');
    texts.forEach((t, i) => { const st = svSignalsText(t);
      for (const m of st.matchAll(decl)) {
        const ty = m[1];
        for (const n of svNames(st, m.indices[2][0])) {   // (each name past an initialiser too)
          if (!n || SV_WORDS.has(n) || types.has(n) || fields.has(n)) continue;
          used.add(i);
          if (fields.has(ty)) put(n, ['s', fields.get(ty)]);
          else if (types.has(ty)) put(n, ['e', types.get(ty)]);   // an enum not read too: the name is taken
          else if (bodies.has(ty)) put(n, ['s', null]);   // a struct whose fields it cannot tell (or defined twice): the name is taken
        }
      }
    });
  }
  for (const t of texts) { const st = svSignalsText(t);   // the same name as a plain vector somewhere
    for (const m of st.matchAll(SV_PLAIN)) for (const n of svNames(st, m.indices[1][0])) if (n && !SV_WORDS.has(n)) put(n, ['p', null]); }
  for (const n of [...clash].sort()) notes.push(`${n}: declared with different types (in different modules?): no labels`);
  const of = k => Object.fromEntries([...cand].filter(([, v]) => v[0] === k && v[1]).map(([n, v]) => [n, v[1]]));
  return { enums: of('e'), fields: of('s'), notes, files: used.size };
}
// two sets of tables as one (the second wins a name or a path: Sources… over the workspace's)
const svMerge = (a, b) => { if (!a || !b) return a || b;
  const mine = new Set([...Object.keys(b.enums), ...Object.keys(b.fields)]), keep = o => Object.fromEntries(Object.entries(o).filter(([n]) => !mine.has(n)));
  const out = { enums: Object.assign(keep(a.enums), b.enums), fields: Object.assign(keep(a.fields), b.fields), notes: a.notes.concat(b.notes),
    files: a.files + b.files };
  if (a.paths || b.paths) out.paths = Object.assign({}, a.paths, b.paths);
  if (a.producer || b.producer) out.producer = b.producer || a.producer;
  if (a.map || b.map) out.map = Object.assign({}, a.map, b.map);
  if (a.names || b.names) out.names = [...(a.names || []), ...(b.names || [])];
  if (a.plain || b.plain) out.plain = Object.assign({}, a.plain, b.plain);
  if (a.instances || b.instances) out.instances = Object.assign({}, a.instances, b.instances);
  return out; };
// the labels and fields of the sources onto the signals of a WaveJSON that have none (a name's table only when its values
// fit the signal's width; fields when they cover it, as mkconfig.py apply_sv) -> how many signals got them
// What it puts there is marked (svEnum, svFields): tables of other sources replace those, and only those (the dump's own
// tables and a config's stay); sources without a name's table take its labels away again.
// With a types file (sv.paths, svTypes) a signal takes only its own path's type, when its width is the type's (else a note
// in log), and the names of the sources are not used: the design's types say which `state` is which.
// why (a Map, optional): each signal's path -> what the types did with it, for the inspector (the right button's Type…):
// {status: 'typed' | 'width' | 'none', key: the types' path, width, as: the path remapped, labels / fields: 'types' (put
// there now), 'own' (the row's own: the dump's table, the config's, kept), null (none)}
// an integer labelled by a narrower enum (svApply): the values of the dump that are no code of it (shown as numbers), or
// only x (a VCD of wlf2vcd, which loses the values of enums) -> a note, or null when every value read is one of its codes
function svIntValues(it, e, w) {
  const keys = new Set(Object.keys(e.enum)), out = new Set(), name = it.path || it.name;
  let known = 0, xs = 0;
  for (const [, v] of it.tv || []) {
    const s = String(v ?? '');
    if (!/^[0-9a-f]+$/i.test(s)) { xs++; continue; }
    const n = BigInt('0x' + s).toString();
    if (keys.has(n)) known++; else out.add(n);
  }
  if (xs && !known && !out.size) return `${name}: only x in the dump, an enum in the types (a VCD of wlf2vcd? it loses the values of enums)`;
  if (!out.size) return null;
  const vs = [...out];
  return `${name}: an integer of ${w} bits labelled by its enum of ${e.width}: ${vs.length} value${vs.length === 1 ? '' : 's'} no code of it ` +
    `(${vs.slice(0, 4).join(', ')}${vs.length > 4 ? ', …' : ''}), shown as numbers`;
}
const svIntSaid = n => `${n} enum${n === 1 ? '' : 's'} of the types on integers of the dump (wider: a Questa VCD writes an enum as integer 32): ` +
  'labelled by their codes';
function svApply(doc, sv, log, why) {
  if (!doc || !doc.signal) return 0;
  sv = sv || { enums: {}, fields: {} };
  const byPath = !!sv.paths;   // a types file, even an empty one: the names of the sources are not used
  let n = 0;
  const rows = [], all = items => { for (const it of items) {
    if (Array.isArray(it)) all(it.slice(typeof it[0] === 'string' ? 1 : 0));
    else if (it && typeof it === 'object' && it.name && !it.kind) rows.push(it); } };
  all(doc.signal);
  const mp = sv.map || {}, tops = byPath ? svTops(sv.paths, rows.map(it => svRemap(String(it.path || it.name), mp))) : new Set();
  for (const it of rows) {
    if (!it.tv) continue;
    let wy = null;   // a clock-sampled row's labels are made already (make html with mkconfig.py --sv does its own)
    // an element of an array (state.[0], state[0]): the array's name
    const leaf = String(it.path || it.name).replace(/(\.?\[-?\d+\])+$/, '').split('.').pop(), w = +it.width || 1;
    let t = !byPath && sv.enums && sv.enums[leaf], fl = !byPath && sv.fields && sv.fields[leaf];
    if (byPath) {
      const p = svRemap(String(it.path || it.name), mp), k = svLookupKey(sv.paths, p, tops), e = k != null ? sv.paths[k] : null;
      // an enum on a wider integer of the dump (the VCD reader's signed radix: Questa 2023 writes an enum as integer 32)
      const int = !!(e && e.enum && e.width < w && (it.radix === 'signed' || it.svRadix === 'signed'));
      if (e && (e.width === w || int)) { t = e.enum; fl = e.fields; }
      else if (e && log) log.push(`${it.path || it.name}: ${w} bits in the dump, ${e.width} in the types: left as it is`);
      if (int && log) { const n = svIntValues(it, e, w); if (n) log.push(n); }
      if (why) why.set(String(it.path || it.name), wy = { status: !e ? 'none' : e.width === w || int ? 'typed' : 'width', key: k,
        width: e ? e.width : null, as: p, int });
    }
    if (it.svEnum) { delete it.enum; delete it.svEnum; if (it.svRadix) it.radix = it.svRadix; delete it.svRadix; }   // the sources' before
    if (it.svFields) { delete it.fields; delete it.svFields; }
    let got = false, ge = false, gf = false;
    const fits = k => /^\d+$/.test(k) && BigInt(k) < 1n << BigInt(w);   // (exact past 2^53: a 64-bit enum's)
    if (!it.enum && t && Object.keys(t).length && Object.keys(t).every(fits)) {   // (an integer's signed radix: the labels instead)
      it.enum = Object.fromEntries(Object.entries(t).map(([k, v]) => [String(k), v])); it.svEnum = true;
      if (it.radix === 'signed') { it.svRadix = it.radix; delete it.radix; }
      got = ge = true; }
    if (!it.fields && fl && fl.length && fl[0].msb + 1 === w) { it.fields = fl; it.svFields = true; got = gf = true; }
    if (wy) Object.assign(wy, { labels: ge ? 'types' : it.enum ? 'own' : null, fields: gf ? 'types' : it.fields ? 'own' : null });
    if (got) n++;
  }
  return n;
}

// ---------------- types by path: tools/questa/wavelens_types.tcl, svtypes.py verilator (the twin of tools/svtypes.py) ----------------
// A types file {"wavelens": "types", "describe": {path: Questa's text} | "signals": {path: {width, enum | fields}}} -> the
// tables of svApply with paths: {enums: {}, fields: {}, paths, notes, files: 1, producer}. A nested struct gives dotted fields
// (in.st), an array of enums or structs a field per element (pair[1]); a union, an enum of more than 32 bits from describe
// (Questa keeps 32) or a text it does not read a note, and the signal stays as numbers.
const TY_INTS = { int: 32, integer: 32, shortint: 16, longint: 64, byte: 8, time: 64 };
const TY_REAL = /^(?:Floating point type\b.*|Real|Shortreal|Realtime)$/;   // svtypes.py DESC_REAL
function tyParse(text) {   // Questa's describe of one signal -> a type {kind: enum | vec | record | union | array | unknown, …}
  const lines = String(text).split(/\r?\n/).map(x => x.trim()).filter(Boolean); let pos = 0;
  const one = () => {
    if (pos >= lines.length) return { kind: 'unknown', text: '(nothing)' };
    const s = lines[pos++]; let m;
    if ((m = /^Verilog enum: \((-?\d+) (?:downto|to) (-?\d+)\) \[(\d+) enumeration values?\]$/.exec(s))) {
      let body = '';
      while (pos < lines.length) { body += lines[pos++]; if (body.includes('(') && body.split('(').length <= body.split(')').length) break; }
      const items = [];   // (A=0,B=1, …): a label is an SV identifier (letters, digits, _ and $)
      for (const x of body.trim().replace(/^\(/, '').replace(/\)$/, '').split(',')) {
        const e = /^([A-Za-z_][\w$]*)=(-?\d+)$/.exec(x.trim());
        if (!e) return { kind: 'unknown', text: `enum values "${x.trim() || body}"` };
        items.push([e[1], +e[2]]); }
      return { kind: 'enum', width: Math.abs(+m[1] - +m[2]) + 1, count: +m[3], describe: true, items }; }
    if ((m = /^(Record|Union) \[(\d+) elements?\]$/.exec(s))) {
      const members = [];
      for (let i = 0; i < +m[2]; i++) {
        const e = pos < lines.length && /^Element #\d+ "([^"]*)" =>$/.exec(lines[pos]);
        if (!e) return { kind: 'unknown', text: s };
        pos++; members.push([e[1], one()]); }
      return { kind: m[1] === 'Record' ? 'record' : 'union', members }; }
    if ((m = /^Array\((-?\d+) (downto|to) (-?\d+)\) \[length (\d+)\] of$/.exec(s))) return { kind: 'array', left: +m[1], right: +m[3], elem: one() };
    if (s in TY_INTS) return { kind: 'vec', width: TY_INTS[s] };
    if ((m = /^(?:Signed )?(?:Register|Net|Wire|reg|wire|logic|bit)(?: \[(-?\d+):(-?\d+)\])?$/.exec(s)))
      return { kind: 'vec', width: m[1] != null ? Math.abs(+m[1] - +m[2]) + 1 : 1 };
    return { kind: 'unknown', text: s };
  };
  return one();
}
function tyWidth(t) {
  if (t.kind === 'enum' || t.kind === 'vec') return t.width;
  if (t.kind === 'record' || t.kind === 'union') { const ws = t.members.map(x => tyWidth(x[1]));
    return ws.includes(null) || !ws.length ? null : t.kind === 'record' ? ws.reduce((a, b) => a + b, 0) : Math.max(...ws); }
  if (t.kind === 'array') { const w = tyWidth(t.elem); return w == null ? null : w * (Math.abs(t.left - t.right) + 1); }
  return null;
}
function tyTable(t) {   // an enum's values -> [{"value": "label"} unsigned on its width, or null, the reason]
  if (t.width > 32 && t.describe) return [null, `an enum of ${t.width} bits: Questa's describe keeps 32 bits of each value`];
  if (t.items.length !== t.count) return [null, `${t.items.length} of its ${t.count} enum values read`];
  const u = v => (t.width >= 32 ? (v < 0 ? v + 2 ** 32 : v) : ((v % 2 ** t.width) + 2 ** t.width) % 2 ** t.width);
  return [Object.fromEntries(t.items.map(([nm, v]) => [u(v), nm]).sort((a, b) => a[0] - b[0]).map(([v, nm]) => [String(v), nm])), null];
}
function tyFlat(t, name, lsb, out) {   // the fields of a type that starts at bit lsb, MSB first; a reason when it cannot be told
  const w = tyWidth(t), typed = k => k === 'enum' || k === 'record' || k === 'array';
  if (w == null) return `${name || 'the signal'}: a type it does not read (${t.text || t.kind})`;
  if (t.kind === 'enum') { const [tb, why] = tyTable(t); if (why) return `${name}: ${why}`; out.push({ name, msb: lsb + w - 1, lsb, enum: tb }); }
  else if (t.kind === 'record') {
    let at = lsb + w; const part = [];
    for (const [mn, mt] of t.members) { at -= tyWidth(mt); const why = tyFlat(mt, name ? `${name}.${mn}` : mn, at, part); if (why) return why; }
    out.push(...part); }
  else if (t.kind === 'array' && typed(t.elem.kind)) {
    const n = Math.abs(t.left - t.right) + 1, ew = tyWidth(t.elem), step = t.left > t.right ? -1 : 1;
    for (let j = 0; j < n; j++) { const why = tyFlat(t.elem, `${name}[${t.left + j * step}]`, lsb + (n - 1 - j) * ew, out); if (why) return why; } }
  else out.push({ name, msb: lsb + w - 1, lsb });   // a vector, an array of vectors, a union inside a struct: one field
  return null;
}
function tyLower(t) {   // a type -> [entry {width, enum | fields} or null for a plain vector, a note or null]
  if (t.kind === 'enum') { const [tb, why] = tyTable(t); return why ? [null, why] : [{ width: t.width, enum: tb }, null]; }
  if (t.kind === 'union') return [null, 'a packed union: which member holds the value is not known'];
  const typed = k => k === 'enum' || k === 'record' || k === 'array';
  if (t.kind === 'record' || (t.kind === 'array' && typed(t.elem.kind))) {
    const out = [], why = tyFlat(t, '', 0, out);
    if (why) return [null, why];
    const has = x => x.kind === 'enum' || x.kind === 'record' || (x.members || []).some(m => has(m[1])) || (x.elem && has(x.elem));
    if (t.kind === 'array' && !has(t.elem)) return [null, null];   // an array of plain vectors: a vector
    return [{ width: tyWidth(t), fields: out }, null]; }
  return t.kind === 'unknown' ? [null, `a type it does not read (${t.text})`] : [null, null];
}
const tyMark = t => { if (t.kind === 'enum') t.describe = true; for (const [, m] of t.members || []) tyMark(m); if (t.elem) tyMark(t.elem); return t; };
function svTypes(d, where = 'types') {
  if (typeof d === 'string') d = jsonParse(d, where, 'not a types file');   // its error: the line and column (the log shows them)
  if (!d || d.wavelens !== 'types') throw new Error(`${where}: not a WaveLens types file (no "wavelens": "types"; made by ` +
    'tools/questa/wavelens_types.tcl or svtypes.py verilator)');
  const paths = Object.assign({}, d.signals), notes = [...(d.notes || [])], plain = {};   // plain: what describe says of one with no type: its words
  for (const [p, text] of Object.entries(d.describe || {})) {
    if (String(text).startsWith('describe failed')) { notes.push(`${p}: ${text}`); continue; }
    if (TY_REAL.test(String(text).trim())) { plain[p] = String(text).trim(); continue; }   // a real (an analog model's parameter): a number, no note
    const [e, why] = tyLower(tyMark(tyParse(text)));
    if (e) paths[p] = e; else plain[p] = why || String(text).split('\n')[0].trim();
    if (why) notes.push(`${p}: ${why}`);
  }
  // none or null: no map; anything but an object of texts an error (svtypes.py's read)
  const map = d.map == null ? {} : typeof d.map === 'object' && !Array.isArray(d.map) ? Object.assign({}, d.map) : null;
  if (!map || Object.values(map).some(x => typeof x !== 'string')) throw new Error(`${where}: "map" is {"dump.prefix": "types.prefix"}`);
  return { enums: {}, fields: {}, paths, notes, files: 1, producer: d.producer || {}, map, names: [where], plain,
    instances: d.instances && typeof d.instances === 'object' ? d.instances : {} };
}
// the top scopes a dump adds above the design's (TOP. of Verilator's FST): its roots that are none of the types' roots but
// have one as a child; none when a root of the dump is one of the types' (other.tb.state is not tb.state)
function svTops(paths, dump) {
  const mine = new Set(Object.keys(paths).map(p => p.split('.')[0])), roots = new Set(dump.map(p => p.split('.')[0]));
  if ([...roots].some(r => mine.has(r))) return new Set();
  return new Set(dump.map(p => p.split('.')).filter(q => q.length > 1 && mine.has(q[1])).map(q => q[0]));
}
// a dump's path in the types: its own; else without a top scope the dump adds (svTops); an element of an array the array's
function svLookupKey(paths, p, tops = new Set()) {
  if (hasKey(paths, p)) return p;
  const k = p.indexOf('.');
  if (k > 0 && tops.has(p.slice(0, k)) && hasKey(paths, p.slice(k + 1))) return p.slice(k + 1);
  const base = p.replace(/(\.?\[-?\d+\])+$/, '');
  return base !== p ? svLookupKey(paths, base, tops) : null;
}
const svLookup = (paths, p, tops) => { const k = svLookupKey(paths, p, tops); return k != null ? paths[k] : null; };
// a dump's path as the types name it: the longest prefix of the map ({"top.dut_i": "dut"}: top.dut_i.state -> dut.state)
function svRemap(p, m) {
  for (const k of Object.keys(m || {}).sort((a, b) => b.length - a.length)) if (p === k || p.startsWith(k + '.')) return m[k] + p.slice(k.length);
  return p;
}
// whether the types are of the run of the dump (svtypes.py fingerprint): written more than a day apart; instances of the
// types under modules the dump has that it does not have -> [notes]
// the scopes of a WaveJSON: every prefix of a signal's path (the instances the dump has)
const svScopes = doc => { const out = new Set(), walk = items => { for (const it of items || []) {
  if (Array.isArray(it)) walk(it.slice(typeof it[0] === 'string' ? 1 : 0));
  else if (it && it.path) { const p = String(it.path).split('.'); for (let i = 1; i < p.length; i++) out.add(p.slice(0, i).join('.')); } } };
  walk(doc && doc.signal); return out; };
function svFingerprint(sv, date, modules) {
  const out = [], p = (sv && sv.producer) || {}, when = x => { const t = Date.parse(String(x || '').replace(/\s+/g, ' ')); return isNaN(t) ? null : t; };
  const a = when(p.date), b = when(date);
  if (a != null && b != null && Math.abs(a - b) > 864e5) { const d = Math.floor(Math.abs(a - b) / 864e5);
    out.push(`the types were written ${d} day${d === 1 ? '' : 's'} ${a > b ? 'after' : 'before'} the dump (${p.date}; the dump: ${date}): another run? ` +
      '(the labels of another design or other parameters may not fit)'); }
  const mods = new Set([...(modules || [])].map(x => svRemap(x, sv.map))), inst = Object.keys((sv && sv.instances) || {});
  if (mods.size && inst.length) {
    const miss = inst.filter(i => !mods.has(i) && mods.has(i.slice(0, Math.max(0, i.lastIndexOf('.'))))).sort();
    if (miss.length) out.push(`${miss.length} instance${miss.length === 1 ? '' : 's'} of the types not in the dump, under modules it has: ` +
      `${miss.slice(0, 3).join(', ')}${miss.length > 3 ? ' …' : ''} (none of its signals dumped, or another design)`);
  }
  return out;
}
