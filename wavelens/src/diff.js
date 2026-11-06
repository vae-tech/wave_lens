/* wavelens/src/diff.js — a second dump over the waves (Compare… in the bar's dump group): where its values differ. */

/* ---------------- compare with a second dump ---------------- */
// The same test before and after a change of the RTL, two seeds: the second dump (B, a VCD read by the page's reader)
// over these waves on the same time scale, signal by signal (by path; else by name under the page's scope; else the one
// path of B that ends with the name). B is read once, its signals that could be these rows only and over these waves' time
// (a large B: its progress said, ≠ … ✕ stops it). Where B's value differs, a red band on the row; the names of the signals that
// differ get ≠, the ones B has not got are struck (the ones its reader left out for dumpBudget: said apart); ]d [d step
// through the differences (of the selected signal when it has some, else of all). Compared over the time both dumps
// cover; values as values: bits ("'b" bits, x and z apart, a bus of another width differs everywhere), a real as a
// number, a string as text. A packed struct by its whole vector. Not in the saved state: a session's look.
//
// What the waves show of the two (compareView, keys d D, the bar's A B A+B, the command compare's show; its name on the time
// axis): 'a' these waves; 'b' the second dump's values on these rows, in place: the rows that differ take its changes (the rows
// it has not got none, a field or a struct made again), so the cursor's values, the edges, the find, the FSM panel and the
// picture are of B, the colours are the same, and d flipping to and fro moves only what differs. The assertions stay A's.
// 'overlay' both at once, on the stretches that differ: a bit's B over its A in B's colour, a bus's row in two lanes, A above B.
// B's values are kept of the rows that differ only (the others have A's): the rows of a dump read here, the result's "vcd", a
// cut of B of those signals (svabuild.compare; read at its first use), "shift" its offset; a result without it: bands only.
// A row of another width or kind has no values on these rows: empty in B's view (its tooltip says what B has), bands only.
// The bits of a bus (b) compare by their own values, once B's are here; bands only: the bus's bands.

// a value of row r at transition o as compared (o null: before its first change, unknown): a text or a real unknown is
// none of its values ("x" is a text); a bus unknown is its width of x. A real as a number: inf, -inf and nan as the
// simulators write them, three values apart (Number("inf") is NaN), a text that is no number as its text
const realKey = v => { const s = String(v).trim().toLowerCase(), m = /^([+-]?)inf(inity)?$/.exec(s), n = Number(s);
  return m ? 'r' + m[1].replace('+', '') + 'inf' : /^[+-]?nan/.test(s) ? 'rnan' : s !== '' && !isNaN(n) ? 'r' + n : 's' + s; };
const cmpKey = (r, o) => (r.kind === 'string' || r.kind === 'real' ? (o && o.k === '=' ? (r.kind === 'real' ? realKey(o.v) : 's' + o.v) : '\u0000?') :
  (r.width || 1) === 1 ? (o ? o.k : 'x') : bitsOf(o, r.width));
// the stretches [t, u) of [from, to) where rows a and b hold different values: their changes merged in one pass
function diffSpans(a, b, from, to) {
  const A = a.tr, B = b.tr, out = [];
  let i = lastLE(A, from), j = lastLE(B, from), t = from, open = null;
  while (t < to) {
    const d = cmpKey(a, i < 0 ? null : A[i]) !== cmpKey(b, j < 0 ? null : B[j]);
    if (d && open == null) open = t; else if (!d && open != null) { out.push([open, t]); open = null; }
    const na = i + 1 < A.length ? A[i + 1].t : Infinity, nb = j + 1 < B.length ? B[j + 1].t : Infinity, n = Math.min(na, nb);
    if (n >= to) break;
    if (na === n) i++;
    if (nb === n) j++;
    t = n;
  }
  if (open != null) out.push([open, to]);
  return out;
}
// row a of these waves in B (bs: B's rows by path, byLeaf: by the last part of the path): its path in the dump, else its
// name (full, then short) under the page's --scope or as it is, else the one path of B ending with it -> {b, byName}
// (byName: found by its short name only, B's path not ending with a's full name: tb.a.ready as tb.b.ready, said) or null
function cmpFind(bs, byLeaf, a, scope) {
  const p = (a.src && a.src.path) || a.path; if (p && bs.has(p)) return { b: bs.get(p), byName: false };
  for (const n of [...new Set([a.full, a.name].filter(Boolean))]) {
    let b = (scope && bs.get(scope + '.' + n)) || bs.get(n);
    if (!b) { const c = (byLeaf.get(n.split('.').pop()) || []).filter(r => (r.path || r.full).endsWith('.' + n)); if (c.length === 1) b = c[0]; }
    if (b) { const q = b.path || b.full; return { b, byName: n !== a.full && q !== a.full && !q.endsWith('.' + a.full) }; }
  }
  return null;
}
const cmpPath = r => (r.src && r.src.path) || r.path || r.full;
// "matched by name: tb.a.ready → tb.b.ready" (+ how many more) for the toast and the bar's ≠ button, '' when none
const cmpByName = c => (c.byName.length ? `matched by name: ${c.byName[0][0]} → ${c.byName[0][1]}${c.byName.length > 1 ? ` (+${c.byName.length - 1} more: ` +
  'their tooltips)' : ''}` : '');
const cmpText = r => (r.kind === 'real' || r.kind === 'string');
const CMP_SHOWS = ['a', 'b', 'overlay'];
// the row of B's values over s, a row of these waves (its width, kind, enum): a bit's tr is a getter, so defined, not set
const cmpView = (c, s) => c.view || (c.view = Object.create(s, { tr: { value: c.row.tr, writable: true } }));
// the first difference: a row of another width differs from the start, which says nothing of where it goes wrong (as sva diff)
const cmpFirst = rows => { let f = null; for (const x of rows.values()) if (!x.other && x.spans.length && (f == null || x.spans[0][0] < f)) f = x.spans[0][0];
  return f; };
// who differed first, and what followed: the rows by the start of their first difference -> [{row, t}] (the first n)
const cmpRank = (rows, n = 5) => [...rows].filter(([, x]) => !x.other && x.spans.length).map(([r, x]) => ({ row: r, t: x.spans[0][0] }))
  .sort((p, q) => p.t - q.t || (p.row.full < q.row.full ? -1 : 1)).slice(0, n);
const cmpStarts = rows => [...new Set([...rows.values()].flatMap(x => x.spans.map(([t]) => t)))].sort((x, y) => x - y);
// which run the waves show, on a picture's axis: the run's letter and name on its colour, the two of the overlay in the colours of their
// waves; a strip under the axis while B is shown. names: [A's, B's]
function paintRunTagOf(P, xR, y, h, run, names) {
  const [na, nb] = names.map(s => (s.length > 32 ? s.slice(0, 31) + '…' : s)), st = { size: 10.5, weight: 600 };
  const parts = run === 'b' ? [['B', nb, 'runb']] : run === 'overlay' ? [['A', na, 'one'], ['B', nb, 'runb']] : [['A', na, 'acc']];
  let x = xR - 4;
  for (const [l, n, col] of parts.reverse()) {
    const t = `${l} · ${n}`, w = P.measure(t, st) + 12; x -= w;
    P.rect(x, y + 3, w, h - 6, col); P.text(x + 6, y + h / 2, t, Object.assign({ fill: 'panel' }, st)); x -= 3;
  }
  if (run === 'b') P.rect(0, y + h - 2, xR, 2, 'runb');
}
const cmpNameA = (M, title) => String((M.src && M.src.meta && M.src.meta.waves) || title || M.title || 'these waves').split(/[\\/]/).pop();
// the "vcd" of a result: its rows by path, on A's time (shift: B's time less A's)
function cmpCut(c) {
  const by = new Map();
  for (const r of parse(vcdToWave(c.vcd, { name: c.name, budget: Infinity }).doc).rows) {
    if (r.type !== 'sig' || !r.tr) continue;
    if (c.shift) for (const o of r.tr) o.t -= c.shift;
    by.set(r.path || r.full, r);
  }
  return by;
}
// a stretch x0 … x1 ([a, b) of time) of row o with both runs (paintCmp, overlay): a bit's B over its A in B's colour; a bus's row
// in two lanes, A above B, so that both values are read; an analog row B's line on A's scale
function paintBoth(P, o, c, a, b, x0, x1, X, tEnd) {
  const s = o.row.sig || o.row, vb = cmpView(c, s);
  const px = 2 * (b - a) / Math.max(x1 - x0, 1), hl = o.h / 2;
  vb.an = s.an;
  P.clip(x0 - 1, o.y, x1 - x0 + 2, o.h, () => {
    if (!((s.width || 1) > 1 || cmpText(s)) || s.analog) return paintSig(P, vb, o.y, o.h, X, a - px, b, x0 - 1, x1 + 1, tEnd, 'runb');
    P.rect(x0 - 1, o.y, x1 - x0 + 2, o.h, 'panel');
    paintSig(P, s, o.y, hl, X, a - px, b, x0, x1, tEnd, undefined, 'panel', false, true);
    paintSig(P, vb, o.y + hl, hl, X, a - px, b, x0, x1, tEnd, 'runb', 'panel', false, true);
  });
}
// the time of a view that B does not cover, shaded (the rows that differ have B's values, the others A's: not a run's there)
function paintCmpOut(P, lay, X, t0, t1, c) {
  if (!lay.length) return;
  const y = lay[0].y, h = lay[lay.length - 1].y + lay[lay.length - 1].h - y;
  for (const [a, b] of [[t0, Math.min(c.from, t1)], [Math.max(c.to, t0), t1]]) if (b > a) P.rect(X(a), y, X(b) - X(a), h, 'panel2', 0.6);
}
// the red bands of the stretches that differ (of(row): {spans} or null), on the rows laid out (lay entries), over [t0, t1): the
// first one in view found by a binary search, none past t1; the stretches less than a pixel apart one band (as a burst of
// edges: a clock a picosecond late differs twice a cycle), the next one found by a binary search too: a band per pixel at most;
// both: the overlay, B's waves in them (paintBoth), up to tEnd
function paintCmp(P, lay, X, t0, t1, of, both = false, tEnd = t1) {
  if (!(t1 > t0)) return;
  const k = (X(t1) - X(t0)) / (t1 - t0), px = k > 0 ? 1 / k : 0;   // the time of a pixel
  for (const o of lay) {
    const c = of(o.row); if (!c || !c.spans.length) continue;
    const S = c.spans, n = S.length, at = j => S[j][0];
    for (let i = Math.max(0, lastBefore(n, at, t0)); i < n;) {
      const a = S[i][0]; let b = S[i][1], j = i + 1;
      if (a >= t1) break;
      while (j < n && S[j][0] < t1 && S[j][0] <= b + px) { const m = lastBefore(n, at, b + px); b = Math.max(b, S[m][1]); j = m + 1; }
      i = j; if (b <= t0) continue;
      const x0 = X(Math.max(a, t0)), x1 = Math.max(X(Math.min(b, t1)), x0 + 1.5);
      if (both && c.row && !o.row.lazy) paintBoth(P, o, c, Math.max(a, t0), Math.min(b, t1), x0, x1, X, tEnd);
      P.rect(x0, o.y + 1, x1 - x0, o.h - 2, 'x', both && c.row ? 0.06 : 0.16);
      if (!(both && c.row)) P.rect(x0, o.y + o.h - 3, x1 - x0, 2, 'x', 0.85);   // over B's waves: it would hide a bit low in B
    }
  }
}
// a compare result of the page (WaveJSON "compare", sva diff's made by the build or given by the command compare) for the
// static SVG: a row's stretches by its path, a struct's by its group's vector
const cmpOfDoc = c => (c ? r => { const x = r && c.signals[cmpPath(r.sig || r.orig || r)]; return x || null; } : () => null);
// the static SVG of a result with "show" and its "vcd": B's values on the rows that differ (M is the figure's own) -> b / overlay, else null
function cmpDocShow(M) {
  const c = M.compare; if (!c || !c.vcd || (c.show !== 'b' && c.show !== 'overlay')) return null;
  const by = cmpCut(c), got = new Set();
  for (const r of [...M.rows, ...Object.values(M.groups).filter(g => g.sig).map(g => g.sig)]) {
    if (r.type !== 'sig' || !r.tr) continue;
    const p = cmpPath(r), x = c.signals[p], b = x && x.spans.length && !x.other ? by.get(x.b || p) : null;
    if (b) { x.row = b; if (c.show === 'b') { r.tr = b.tr; got.add(r); } }
    else if (c.show === 'b' && ((x && x.other) || c.missing.includes(p))) { r.tr = []; got.add(r); }
  }
  if (got.size) rowsMade(M, got);
  return c.show;
}
Object.assign(WaveView.prototype, {
  // the rows these waves compare: the signals of exact transitions (not a struct's fields: its whole vector instead, on its group)
  cmpRows() {
    return [...this.M.rows.filter(r => r.type === 'sig' && r.tr && r.tv && !r.field), ...Object.values(this.M.groups).filter(g => g.sig && g.sig.tv)
      .map(g => g.sig)];
  },
  // a second dump (a File, or a VCD's text and its name) over these waves; null: none again -> { name, compared, differ,
  // missing, omitted, first, from, to } (null: nothing compared; a newer call or the viewer gone meanwhile: null)
  async compare(file, name) {
    const req = this.cmpReq = (this.cmpReq || 0) + 1;
    if (file == null) { this.cmpBack(); this.cmp = null; this.cmpMarks(); this.cmpShow(); this.draw(); return null; }
    const mine = this.cmpRows();
    if (!this.M.timed || !mine.length) {
      this.toast('compare: these waves are clock-sampled (one cell per cycle): open the dump itself (Open…) and compare that'); return null; }
    const nm = name || file.name || 'B'; this.cmpSrc = { file, name: nm };   // what ⟳ reads again (openDump)
    // a compare that fails leaves the one before as it was, and says so (its bands are still drawn)
    const still = () => (this.cmp ? `; still compared with ${this.cmp.name}` : '');
    let doc;
    // B's variables that could be these rows (a path, a name, the last part of either: cmpFind's), its changes over their time
    const only = new Set();
    for (const a of mine) for (const n of [cmpPath(a), a.full, a.name]) if (n) { only.add(String(n)); only.add(String(n).split('.').pop()); }
    const mb = n => (n / 1048576).toFixed(n < 10485760 ? 1 : 0);
    let told = 0;   // the bytes the last progress said
    const o = { name: nm, only, from: this.M.t0, to: this.M.t1, cancel: () => req !== this.cmpReq || !this.root.isConnected,
      progress: (got, size) => { if (size >= 8 << 20 && got - told >= 8 << 20 && got < size) { told = got;
        this.toast(`compare: ${mb(got)} of ${mb(size)} MB of ${nm} read (≠ … ✕ stops)`); } } };
    this.cmpReading = req; this.cmpShow();
    try {   // a File in pieces; a text, or something with a text(), at once
      doc = (typeof file === 'string' ? vcdToWave(file, o) : typeof file.stream === 'function' ? await vcdToWaveFile(file, o) :
        vcdToWave(await file.text(), o)).doc; }
    catch (e) { if (req === this.cmpReq && this.root.isConnected && VIEWS.has(this)) { this.toast(`${nm}: ${e.message}${still()}`);
      this.logError(e, `cannot compare with ${nm}${e.line ? ` (line ${e.line})` : ''}: ${e.message}`); } return null; }
    finally { if (this.cmpReading === req) { this.cmpReading = 0; this.cmpShow(); } }
    if (req !== this.cmpReq || !this.root.isConnected || !VIEWS.has(this)) return null;   // compared again, or no more, meanwhile
    const brows = parse(doc).rows.filter(r => r.type === 'sig' && r.tr), bs = new Map(brows.map(r => [r.path || r.full, r])), byLeaf = new Map();
    for (const r of brows) { const k = (r.path || r.full).split('.').pop(); byLeaf.set(k, (byLeaf.get(k) || []).concat([r])); }
    const om = (doc.meta && doc.meta.omitted && doc.meta.omitted.paths) || {}, left = new Set(), leftLeaf = new Map();   // left out by B's reader
    for (const [sc, ns] of Object.entries(om)) {
      for (const n of ns) { const p = sc ? sc + '.' + n : n; left.add(p); leftLeaf.set(n, (leftLeaf.get(n) || []).concat([p])); }
    }
    const scope = (this.M.src && this.M.src.meta && this.M.src.meta.scope) || '';
    const from = Math.max(this.M.t0, doc.time.t0 ?? 0), to = Math.min(this.M.t1, doc.time.t1 ?? this.M.t1), rows = new Map();
    const f = t => this.fmt(t, (this.M.t1 - this.M.t0) / 1000, this.M.t1 - this.M.t0);
    if (to <= from) { this.toast(`${nm}: no time in common (these waves ${f(this.M.t0)} … ${f(this.M.t1)}, ${nm} ${f(doc.time.t0 ?? 0)} … ` +
      `${f(doc.time.t1)}): nothing compared${still()}`); return null; }
    if (!left.size && !mine.some(a => cmpFind(bs, byLeaf, a, scope))) {   // as sva diff: nothing to compare is no compare (the one before stays)
      this.toast(`${nm}: none of these ${mine.length} signals is in it: nothing compared${still()}`); return null; }
    this.cmpBack();   // these rows' own values again: compared with B, or the one before
    let differ = 0, missing = 0, omitted = 0; const byName = [];
    for (const a of mine) {
      // left out of B by its reader: under any name it could have there (then not looked for under another one)
      const ns = [(a.src && a.src.path) || a.path, scope && scope + '.' + a.full, scope && scope + '.' + a.name, a.full, a.name].filter(Boolean);
      const out = ns.some(n => left.has(n) && !bs.has(n)) || (!ns.some(n => bs.has(n)) && (leftLeaf.get(String(a.name).split('.').pop()) || [])
        .some(p => p.endsWith('.' + a.name) || p.endsWith('.' + a.full)));
      const hit = out ? null : cmpFind(bs, byLeaf, a, scope), b = hit && hit.b;
      if (!b) { rows.set(a, { missing: !out, omitted: out, spans: [] }); if (out) omitted++; else missing++; continue; }
      const other = cmpText(a) !== cmpText(b) || (!cmpText(a) && (a.width || 1) !== (b.width || 1));
      const spans = other ? [[from, to]] : diffSpans(a, b, from, to), by = hit.byName ? cmpPath(b) : null;
      if (by) byName.push([cmpPath(a), by]);
      rows.set(a, { spans, other: other ? (cmpText(b) ? b.kind : `${b.width || 1} bits`) : null, by, row: spans.length && !other ? b : null });
      if (spans.length) differ++;
    }
    this.cmp = { name: nm, rows, differ, missing, omitted, compared: rows.size - missing - omitted, from, to, starts: cmpStarts(rows), first: cmpFirst(rows),
      byName, waves: true };
    this.cmpMarks(); this.cmpShow(); this.draw();
    const c = this.cmp, who = this.cmpWho();
    const said = `${nm}: ${differ} of ${c.compared} signals differ${c.first == null ? '' : `, the first at ${f(c.first)}`}${who}` +
      (missing ? ` · ${missing} not in it` : '') + (omitted ? ` · ${omitted} not read (dumpBudget)` : '') +
      (from > this.M.t0 || to < this.M.t1 ? ` · compared ${f(from)} … ${f(to)} (both dumps)` : '') + (byName.length ? ' · ' + cmpByName(c) : '');
    this.toast(said + (differ ? ' · ]d [d go to them' : '')); this.log('ok', 'compared with ' + said);
    return { name: nm, compared: c.compared, differ, missing, omitted, first: c.first, from, to, byName: byName.length, rank: c.rank };
  },
  // who differed first and what followed (the compare's rank), for its toast: " · first PSEL, then PENABLE +10 ns"
  cmpWho() {
    const rank = cmpRank(this.cmp.rows), d = q => this.fmt(q, (this.M.t1 - this.M.t0) / 1000, this.M.t1 - this.M.t0);
    this.cmp.rank = rank.map(o => ({ signal: o.row.full, t: o.t }));
    const then = rank.slice(1).map(o => `${o.row.name} +${d(o.t - rank[0].t)}`).join(', ');
    return rank.length ? ` · first ${rank[0].row.name}${then ? `, then ${then}` : ''}` : '';
  },
  // the compare as a result (the saved state's "compare", as the WaveJSON's): the one given, else the one of a dump read here
  cmpState() {
    const c = this.cmp; if (!c) return null;
    if (c.result) return c.result;
    const signals = {}, missing = [];
    for (const [r, x] of c.rows) {
      if (x.missing || x.omitted) missing.push(cmpPath(r));
      else signals[cmpPath(r)] = Object.assign({ spans: x.spans }, x.other ? { other: x.other } : {});
    }
    return { name: c.name, from: c.from, to: c.to, first: c.first, signals, missing };
  },
  // the compare result of a row: a struct's group row its vector, a row of your groups its signal, a bit of a bus its own
  cmpOf(r) {
    if (!this.cmp) return null;
    const k = r.sig || r.orig || r;
    return k.bit != null ? this.cmpBit(k) : this.cmp.rows.get(k.dupOf || k);
  },
  // a bit of a bus: its own stretches and B's bit, the changes of the bits of a bus read once for all of them; without B's
  // values, a row of another width: the bus's
  cmpBit(r) {
    const c = this.cmp, x = c.rows.get(r.of.dupOf || r.of); if (!x) return null;
    if (this.cmpCan()) this.cmpLoad();
    if (!x.row) return x;
    const w = r.of.width || 1, j = w - 1 - r.bit, tr = x.atr || r.of.tr, memo = c.bits || (c.bits = new WeakMap());
    let m = memo.get(x);
    if (!m || m.tr !== tr) { m = { tr, a: bitTrs({ width: w, tr }), b: bitTrs(x.row), rows: [] }; memo.set(x, m); }
    return m.rows[j] || (m.rows[j] = { spans: diffSpans({ width: 1, tr: m.a[j] }, { width: 1, tr: m.b[j] }, c.from, c.to), other: null, by: null,
      row: { tr: m.b[j] }, atr: m.a[j] });
  },
  // the rows' marks in the names (≠ differs, struck: not in B; your groups' rows and the bits of a bus too) and their tooltips
  cmpMarks() {
    const all = [...this.sigPool(), ...Object.values(this.M.groups), ...this.ugRows()], bits = new Set(this.cmpBits);
    if (this.bitsOpen.size) {
      for (const r of all) if (r.type === 'sig' && this.bitsOpen.has((r.orig || r).full) && isVec(r)) for (const k of this.bitsOf(r)) bits.add(k);
    }
    this.cmpBits = bits;   // the bits folded meanwhile too: their marks go with the compare
    for (const r of [...all, ...bits]) {
      const c = this.cmpOf(r), d = !!(c && c.spans.length), m = !!(c && (c.missing || c.omitted)), by = c && c.by ? ` (matched by name: ` +
        `${cmpPath(r.sig || r.orig || r)} → ${c.by})` : '';
      this.rowClass(r, 'cmpd', d).rowClass(r, 'cmpm', m);
      if (d || m || by) { this.rowTitle(r, `${r.full || r.name} — ${c.missing ? `not in ${this.cmp.name}` : c.omitted ? `not read from ${this.cmp.name} ` +
        `(dumpBudget ${this.S.dumpBudget} changes)` : c.other ? `${c.other} in ${this.cmp.name}` : d ? `${c.spans.length} stretch${c.spans.length === 1 ? '' :
        'es'} other in ${this.cmp.name}` : `the same in ${this.cmp.name}`}${by}`); (this.cmpTitled ||= new Set()).add(r); }
      else if (this.cmpTitled && this.cmpTitled.delete(r)) this.rowTitle(r, null);
    }
  },
  // a second dump being read stopped (≠ … ✕): the compare before it stays
  compareStop() { this.cmpReq = (this.cmpReq || 0) + 1; this.cmpReading = 0; this.cmpShow(); this.toast(`compare: stopped${this.cmp ? `; still compared ` +
    `with ${this.cmp.name}` : ''}`); },
  cmpShow() {   // the bar's ≠ N ✕ (no compare: hidden; a dump being read: ≠ … ✕ stops it) and its A B A+B; the Runs panel's B
    if (this.runsP) this.runsP.render();
    const b = this.root.querySelector('button[data-act=dcmpx]'), seg = this.root.querySelector('.cmpv'); if (!b) return;
    const has = this.cmpCan(), names = this.cmp ? { a: this.cmpNames()[0], b: this.cmpNames()[1] } : null;
    if (seg) { seg.hidden = !this.cmp; if (this.cmp) for (const x of seg.querySelectorAll('button')) { const s = x.dataset.run, on = s === this.cmpRun;
      x.setAttribute('aria-pressed', on); x.disabled = s !== 'a' && !has;
      x.title = s !== 'a' && !has ? this.cmpCant(s) : s === 'a' ? `Show ${names.a} (the run of these waves; d flips to the other)` : s === 'b' ?
        `Show ${names.b}, the second run, on these rows (d flips to the other)` : `Both runs over each other where they differ: ${names.a}, ${names.b} (D)`; } }
    this.root.classList.toggle('wv-runb', !!this.cmp && this.cmpRun === 'b');
    if (this.cmpReading) { b.hidden = false; b.textContent = '≠ … ✕'; b.title = 'reading the second dump: click to stop'; return; }
    b.hidden = !this.cmp; if (this.cmp) b.textContent = `≠ ${this.cmp.differ} ✕`;
    b.title = this.cmp ? `${this.cmp.name}: ${this.cmp.differ} of ${this.cmp.compared} signals differ${this.cmp.missing ? `, ${this.cmp.missing} not in it` :
      ''}${this.cmp.byName.length ? `; ${cmpByName(this.cmp)}` : ''}; ]d [d go to the differences; click: compare no more` : '';
  },
  // the red bands of a dump compared (paintCmp); B shown: the time it does not cover shaded
  paintDiff(P, lay, X, t0, t1) {
    if (!this.cmp) return;
    if (this.cmpRun === 'b') paintCmpOut(P, lay, X, t0, t1, this.cmp);
    paintCmp(P, lay, X, t0, t1, r => this.cmpOf(r), this.cmpRun === 'overlay', this.M.t1);
  },
  // the names of the two runs: of these waves (the dump they are made of, the title), of the second dump
  cmpNames() {
    return [cmpNameA(this.M, this.opts.title), this.cmp ? this.cmp.name : 'B'];
  },
  // which run the waves show, on the time axis at the right, always in sight (the bar may be folded or off the screen) and in
  // the picture: with a compare (bands only: A's), and while a run kept is shown (runs.js: A)
  paintRunTag(P, xR, y, h) { if (this.cmp || this.runsShown) paintRunTagOf(P, xR, y, h, this.cmp && this.cmpCan() ? this.cmpRun : 'a', this.cmpNames()); },
  // B's values here (a dump read here, a result's "vcd")?
  cmpCan() { const c = this.cmp; return !!c && !!(c.waves || (c.result && c.result.vcd)); },
  // a result's "vcd" read, at its first use: its rows to the ones that differ
  cmpLoad() {
    const c = this.cmp; if (c.waves) return;
    const by = cmpCut(c.result);
    for (const [a, x] of c.rows) if (x.spans.length && !x.other) x.row = by.get(x.b || cmpPath(a)) || null;
    c.waves = true;
  },
  // why this view cannot be shown, '' when it can
  cmpCant(show) {
    if (!this.cmp) return `compare ${show}: compare with a second dump first (Compare… in the bar)`;
    return show === 'a' || this.cmpCan() ? '' : `compare ${show}: this compare has the differences only, not the values of ${this.cmp.name} ` +
      '(a saved one, a cut too large for the page, one of --align): compare again';
  },
  // the rows that differ take B's changes (those B has not got none), or their own again
  cmpSwap(on) {
    const c = this.cmp; if (!c || !!c.swapped === on) return;
    c.swapped = on;
    const got = new Set();
    for (const [a, x] of c.rows) {
      if (!x.row && !x.missing && !x.omitted && !x.other) continue;
      if (on) { x.atr = a.tr; a.tr = x.row ? x.row.tr : []; } else a.tr = x.atr;
      a.an = null; RISES.delete(a); got.add(a);
      for (const k of this.bitMemo.get(a) || []) RISES.delete(k);   // its bits follow its changes
      for (const d of this.dupsBy.get(a) || []) { RISES.delete(d); for (const k of this.bitMemo.get(d) || []) RISES.delete(k); }
    }
    rowsMade(this.M, got);
    this.clkMemo = null; this.cycMemo = null; this.fsmSt = null; this.rangeKey = null; this.valsAt = null;
    if (this.fsmP) this.fsmP.render(true);
  },
  // these waves again, before the compare changes
  cmpBack() { this.cmpSwap(false); this.cmpRun = 'a'; this.valsAt = null; },
  // what the waves show of a compare ('a', 'b', 'overlay'; see above) -> it, null when it cannot be (said, unless quiet) or a
  // newer call came meanwhile; a large dump's rows are read first
  async compareView(show, quiet) {
    if (!CMP_SHOWS.includes(show)) throw new Error(`compare: show is ${CMP_SHOWS.join(', ')}, not "${show}"`);
    const no = this.cmpCant(show); if (no) { if (!quiet) this.toast(no); return null; }
    const req = this.cmpViewReq = (this.cmpViewReq || 0) + 1, c = this.cmp;
    if (show !== 'a') this.cmpLoad();
    if (show === 'b') await this.need([...c.rows].filter(([, x]) => x.row || x.missing || x.omitted || x.other).map(([r]) => r));
    if (req !== this.cmpViewReq || c !== this.cmp) return null;
    if (show === 'overlay' && this.cmpRun !== 'overlay') this.cmpLast = this.cmpRun;
    this.cmpSwap(show === 'b'); this.cmpRun = show; this.valsAt = null;
    this.cmpShow(); this.draw();
    const [na, nb] = this.cmpNames();
    if (!quiet) this.toast(show === 'overlay' ? `A + B: ${na}, ${nb} · D: one run again` : `${show === 'b' ? `B: ${nb}` : `A: ${na}`} · d: the other`);
    this.root.dispatchEvent(new CustomEvent('wavelens:compare', { detail: { show, name: show === 'a' ? na : nb } }));
    return show;
  },
  // d: the other run (from the overlay: A); D: the overlay, again the run before it
  cmpFlip() { if (!this.cmp) { this.toast('d: compare with a second dump first (Compare… in the bar)'); return this; }
    this.compareView(this.cmpRun === 'b' ? 'a' : this.cmpRun === 'overlay' ? 'a' : 'b'); return this; },
  cmpBoth() { if (!this.cmp) { this.toast('D: compare with a second dump first (Compare… in the bar)'); return this; }
    this.compareView(this.cmpRun === 'overlay' ? this.cmpLast || 'a' : 'overlay'); return this; },
  // the value at the cursor in the overlay: both when they differ
  valueBoth(s, t) {
    const a = String(this.valueAt(s, t)), c = this.cmpRun === 'overlay' ? this.cmpOf(s) : null; if (!c || !c.row) return a;
    const b = String(this.valueAt(cmpView(c, s), t));
    return a === b ? a : `${a} ≠ ${b}`;
  },
  // a row's value in the other run, for its tooltip: '' when it has none, or it is the same
  cmpTip(r, t) {
    const c = this.cmp && this.cmpOf(r), b = this.cmpRun === 'b'; if (!c || !(b ? c.atr : c.row)) return '';
    const o = Object.create(r, { tr: { value: b ? c.atr : c.row.tr } }), v = String(this.valueAt(o, t));
    return v === String(this.valueAt(r, t)) ? '' : `\n${b ? 'A' : 'B'}: ${v}`;
  },
  // a compare result already made (sva diff's, by the build from the config's "compare", or the command compare): the WaveJSON
  // extension "compare" {name, from, to, signals: {path: {spans, other, b}}, missing: [path]} over these waves, as compare()
  // puts a dump read here; null: compared no more. quiet: no toast (the page opens with it) -> as compare()
  compareResult(c, quiet) {
    this.cmpReq = (this.cmpReq || 0) + 1;
    if (c == null) { this.cmpBack(); this.cmp = null; this.cmpMarks(); this.cmpShow(); this.draw(); return null; }
    c = cmpNorm(c);
    if (!c) throw new Error('compare: a result {name, from, to, signals: {path: {spans}}} (sva diff\'s, as the page\'s "compare")');
    if (!this.M.timed) { this.toast('compare: these waves are clock-sampled (one cell per cycle): a compare is of exact waves'); return null; }
    this.cmpBack();
    // on these waves: a result of another window, a saved state, an agent's: the time of the page, nothing outside it counted
    const { t0, t1 } = this.M, from = Math.min(Math.max(isFinite(c.from) ? c.from : t0, t0), t1), to = Math.max(Math.min(isFinite(c.to) ? c.to : t1, t1), from);
    const cut = sp => sp.flatMap(([a, b]) => (b > from && a < to ? [[Math.max(a, from), Math.min(b, to)]] : []));
    const rows = new Map(), miss = new Set(c.missing);
    let differ = 0, missing = 0;
    for (const a of this.cmpRows()) {
      const p = cmpPath(a), s = c.signals[p];
      if (miss.has(p)) { rows.set(a, { missing: true, omitted: false, spans: [] }); missing++; continue; }
      if (!s) continue;
      const spans = cut(s.spans);
      rows.set(a, { spans, other: s.other || null, by: null, b: s.b || null });
      if (spans.length) differ++;
    }
    this.cmp = { name: c.name, rows, differ, missing, omitted: 0, compared: rows.size - missing, from, to, starts: cmpStarts(rows), first: cmpFirst(rows),
      byName: [], result: Object.assign({}, c, { from, to }) };
    this.cmpMarks(); this.cmpShow(); this.draw();
    const f = t => this.fmt(t, (this.M.t1 - this.M.t0) / 1000, this.M.t1 - this.M.t0), x = this.cmp;
    const who = this.cmpWho();
    const said = `${x.name}: ${differ} of ${x.compared} signals differ${x.first == null ? '' : `, the first at ${f(x.first)}`}${who}` +
      (missing ? ` · ${missing} not in it` : '') + (from > t0 || to < t1 ? ` · compared ${f(from)} … ${f(to)}` : '');
    if (!quiet) this.toast(said + (differ ? ' · ]d [d go to them' : ''));
    this.log('ok', 'compared with ' + said);
    return { name: x.name, compared: x.compared, differ, missing, omitted: 0, first: x.first, from, to, byName: 0, rank: this.cmp.rank };
  },
  // ]d [d: the cursor to the next / previous start of a difference: of the selected signal when it has some, else of all
  // the signals in the view (hidden ones and the ones Only leaves out: not stepped to). In the view: a row drawn, a row of your
  // groups standing for its signal (.orig: Only keeps your groups whole, the signal's module left out)
  diffStep(dir) {
    if (!this.cmp) { this.toast(']d [d: compare with a second dump first (Compare… in the bar)'); return this; }
    const s = this.sel && this.cmpOf(this.sel), some = this.onlyOn() || this.hiddenRows.size;
    const drawn = () => { if (this.rowsStale) this.allRows(); return new Set((this.rowsAll || []).map(r => r.orig || r)); };
    const ts = s && s.spans.length ? s.spans.map(([a]) => a) : !some ? this.cmp.starts :
      ((bySig, on) => [...new Set([...this.cmp.rows].filter(([r]) => on.has(r) || on.has(bySig.get(r))).flatMap(([, c]) => c.spans.map(([a]) => a)))]
        .sort((x, y) => x - y))(new Map(Object.values(this.M.groups).filter(g => g.sig).map(g => [g.sig, g])), drawn());   // a struct's value: by its row
    if (!ts.length) { this.toast(`no difference from ${this.cmp.name}`); return this; }
    const t = Math.min(Math.max(ts[stepTo(ts, this.cursor, dir)], this.M.t0), this.M.t1);
    this.cursor = t; if (t < this.t0 || t > this.t0 + this.span) this.center(t);
    this.draw(); this.syncCursorFields(true); return this;
  },
});
// a compare result of the page (WaveJSON "compare"): its bands when the viewer opens
PLUGINS.push(v => {
  v.cmpRun = 'a';
  v.addKey(']d', () => v.diffStep(1)).addKey('[d', () => v.diffStep(-1)).addKey('d', () => v.cmpFlip()).addKey('D', () => v.cmpBoth());
  if (v.M.compare && v.M.timed) {
    v.compareResult(v.M.compare, true);
    if (v.M.compare.show) v.compareView(v.M.compare.show, true).catch(e => v.logError(e, e.message));
  }
});
