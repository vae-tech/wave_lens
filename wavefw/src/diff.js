/* wavefw/src/diff.js — a second dump over the waves (Compare… in the bar's dump group): where its values differ. */

/* ---------------- compare with a second dump ---------------- */
// The same test before and after a change of the RTL, two seeds: the second dump (B, a VCD read by the page's reader)
// over these waves on the same time scale, signal by signal (by path; else by name under the page's scope; else the one
// path of B that ends with the name). Where B's value differs, a red band on the row; the names of the signals that
// differ get ≠, the ones B has not got are struck (the ones its reader left out for dumpBudget: said apart); ]d [d step
// through the differences (of the selected signal when it has some, else of all). Compared over the time both dumps
// cover; values as values: bits ("'b" bits, x and z apart, a bus of another width differs everywhere), a real as a
// number, a string as text. A packed struct by its whole vector. Not in the saved state: a session's look.

// a value of row r at transition o as compared (o null: before its first change, unknown): a text or a real unknown is
// none of its values ("x" is a text); a bus unknown is its width of x
const cmpKey = (r, o) => (r.kind === 'string' || r.kind === 'real' ? (o && o.k === '=' ? (r.kind === 'real' ? 'r' + Number(o.v) : 's' + o.v) : '\u0000?') :
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
// name (full, then short) under the page's --scope or as it is, else the one path of B ending with it
function cmpFind(bs, byLeaf, a, scope) {
  const p = (a.src && a.src.path) || a.path; if (p && bs.has(p)) return bs.get(p);
  for (const n of [...new Set([a.full, a.name].filter(Boolean))]) {
    const hit = (scope && bs.get(scope + '.' + n)) || bs.get(n); if (hit) return hit;
    const c = (byLeaf.get(n.split('.').pop()) || []).filter(r => (r.path || r.full).endsWith('.' + n)); if (c.length === 1) return c[0];
  }
  return null;
}
const cmpText = r => (r.kind === 'real' || r.kind === 'string');
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
    if (file == null) { this.cmp = null; this.cmpMarks(); this.cmpShow(); this.draw(); return null; }
    const mine = this.cmpRows();
    if (!this.M.timed || !mine.length) {
      this.toast('compare: these waves are clock-sampled (one cell per cycle): open the dump itself (Open…) and compare that'); return null; }
    const nm = name || file.name || 'B';
    let doc;
    try { const text = typeof file === 'string' ? file : await file.text(); doc = vcdToWave(text, { name: nm, budget: this.S.dumpBudget }).doc; }
    catch (e) { if (req === this.cmpReq && this.root.isConnected && VIEWS.has(this)) this.toast(`${nm}: ${e.message}`); return null; }
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
      `${f(doc.time.t1)}): nothing compared`); return null; }
    let differ = 0, missing = 0, omitted = 0;
    for (const a of mine) {
      // left out of B by its reader: under any name it could have there (then not looked for under another one)
      const ns = [(a.src && a.src.path) || a.path, scope && scope + '.' + a.full, scope && scope + '.' + a.name, a.full, a.name].filter(Boolean);
      const out = ns.some(n => left.has(n) && !bs.has(n)) || (!ns.some(n => bs.has(n)) && (leftLeaf.get(String(a.name).split('.').pop()) || [])
        .some(p => p.endsWith('.' + a.name) || p.endsWith('.' + a.full)));
      const b = out ? null : cmpFind(bs, byLeaf, a, scope);
      if (!b) { rows.set(a, { missing: !out, omitted: out, spans: [] }); if (out) omitted++; else missing++; continue; }
      const other = cmpText(a) !== cmpText(b) || (!cmpText(a) && (a.width || 1) !== (b.width || 1));
      const spans = other ? [[from, to]] : diffSpans(a, b, from, to);
      rows.set(a, { spans, other: other ? (cmpText(b) ? b.kind : `${b.width || 1} bits`) : null });
      if (spans.length) differ++;
    }
    const starts = [...new Set([...rows.values()].flatMap(c => c.spans.map(([s]) => s)))].sort((x, y) => x - y);
    this.cmp = { name: nm, rows, differ, missing, omitted, compared: rows.size - missing - omitted, from, to, starts, first: starts.length ? starts[0] : null };
    this.cmpMarks(); this.cmpShow(); this.draw();
    const c = this.cmp;
    this.toast(`${nm}: ${differ} of ${c.compared} signals differ${c.first == null ? '' : `, the first at ${f(c.first)}`}` +
      (missing ? ` · ${missing} not in it` : '') + (omitted ? ` · ${omitted} not read (dumpBudget)` : '') +
      (from > this.M.t0 || to < this.M.t1 ? ` · compared ${f(from)} … ${f(to)} (both dumps)` : '') + (differ ? ' · ]d [d go to them' : ''));
    return { name: nm, compared: c.compared, differ, missing, omitted, first: c.first, from, to };
  },
  // the compare result of a row: a struct's group row its vector, a row of your groups its signal
  cmpOf(r) { return this.cmp ? this.cmp.rows.get(r.sig || r.orig || r) : null; },
  // the rows' marks in the names (≠ differs, struck: not in B; your groups' rows too) and their tooltips
  cmpMarks() {
    const all = [...this.M.rows, ...Object.values(this.M.groups), ...this.ugRows()];
    for (const r of all) {
      const c = this.cmpOf(r), d = !!(c && c.spans.length), m = !!(c && (c.missing || c.omitted));
      this.rowClass(r, 'cmpd', d).rowClass(r, 'cmpm', m);
      if (d || m) { this.rowTitle(r, `${r.full || r.name} — ${c.missing ? `not in ${this.cmp.name}` : c.omitted ? `not read from ${this.cmp.name} ` +
        `(dumpBudget ${this.S.dumpBudget} changes)` : c.other ? `${this.cmp.name}: ${c.other}` : `${c.spans.length} stretch${c.spans.length === 1 ? '' :
        'es'} other in ${this.cmp.name}`}`); (this.cmpTitled ||= new Set()).add(r); }
      else if (this.cmpTitled && this.cmpTitled.delete(r)) this.rowTitle(r, null);
    }
  },
  cmpShow() {   // the bar's ≠ N ✕ (no compare: hidden)
    const b = this.root.querySelector('button[data-act=dcmpx]'); if (!b) return;
    b.hidden = !this.cmp; if (this.cmp) b.textContent = `≠ ${this.cmp.differ} ✕`;
    b.title = this.cmp ? `${this.cmp.name}: ${this.cmp.differ} of ${this.cmp.compared} signals differ${this.cmp.missing ? `, ${this.cmp.missing} not in it` :
      ''}; ]d [d go to the differences; click: compare no more` : '';
  },
  // the red bands of the stretches that differ, on the rows laid out (lay entries), over [t0, t1): the first one in view
  // found by a binary search, none past t1
  paintDiff(P, lay, X, t0, t1) {
    if (!this.cmp) return;
    for (const o of lay) {
      const c = this.cmpOf(o.row); if (!c || !c.spans.length) continue;
      for (let i = Math.max(0, lastBefore(c.spans.length, j => c.spans[j][0], t0)); i < c.spans.length; i++) {
        const [a, b] = c.spans[i]; if (a >= t1) break; if (b <= t0) continue;
        const x0 = X(Math.max(a, t0)), x1 = Math.max(X(Math.min(b, t1)), x0 + 1.5);
        P.rect(x0, o.y + 1, x1 - x0, o.h - 2, 'x', 0.16); P.rect(x0, o.y + o.h - 3, x1 - x0, 2, 'x', 0.85);
      }
    }
  },
  // ]d [d: the cursor to the next / previous start of a difference: of the selected signal when it has some, else of all
  diffStep(dir) {
    if (!this.cmp) { this.toast(']d [d: compare with a second dump first (Compare… in the bar)'); return this; }
    const s = this.sel && this.cmpOf(this.sel), ts = s && s.spans.length ? s.spans.map(([a]) => a) : this.cmp.starts;
    if (!ts.length) { this.toast(`no difference from ${this.cmp.name}`); return this; }
    const t = ts[stepTo(ts, this.cursor, dir)];
    this.cursor = t; if (t < this.t0 || t > this.t0 + this.span) this.t0 = this.clamp(t - this.span / 2);
    this.draw(); this.syncCursorFields(true); return this;
  },
});
PLUGINS.push(v => v.addKey(']d', () => v.diffStep(1)).addKey('[d', () => v.diffStep(-1)));
