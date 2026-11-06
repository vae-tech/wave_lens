/* wavelens/src/runs.js — the runs kept of a dump (gu, Runs… in the bar): the dumps of runs before, kept by hand with a
   name, tags and a comment (VS Code: sva runs keep, into .wavelens-runs beside the dump, as FSTs). The list holds the dump
   of now (the row "now") and every run; two of them have a role, a letter on their row: A, the waves shown here (the dump
   of now at first; w on a row, ]w [w anywhere: a run's waves read into this viewer, the window, the rows and the markers
   kept), and B, the run compared with A over a window — the waves in sight or one of your spans: only that window of the
   runs is read (sva runs diff, then the values of the signals that differ there), so a large run costs the window, not the
   dump. A click on a row (Enter, ↑ ↓ in the list, ]r [r anywhere) makes it B; x: no B, the waves only (]w [w then walk
   the runs, nothing compared). The compare's A B A+B and ]d [d as Compare… has them; Δ all: how many signals of each run
   differ from A in the window. Keep this dump… adds the dump of now. The page asks its host (window.WAVELENS_RUNS: list,
   keep, set, rm, diff, compare, open; the VS Code extension's media/host.js gives it); without one (a page in a browser)
   there are none. A run keeps its test cases (your spans with a label when kept, or cocotb's marks beside the dump): a span
   of yours a run has a case of (by name) is compared with that case of the run, wherever it is in the run (B offset to it,
   over the shorter of the two). */

/* ---------------- the viewer's side ---------------- */
const RUN_SETTLE = 250;   // ms: the list's keys move the row, the compare goes when they stop (Enter at once)
// a case's name of a span's label: without "TC3 " before it and " · PASS" after it (cocotb's marks); sva runs.rs case_name
const caseName = l => { const s = String(l || '').split(' · ')[0].trim(), m = /^TC\d+ (.*)$/.exec(s); return (m ? m[1] : s).trim(); };
const sameSpan = (s, w) => !!s && !!w && s.from === w.from && s.to === w.to && (s.label || '') === (w.label || '');
// the keys of a view's state that are of its time, not of its rows: a step of A keeps them as they are on the screen (the rest
// from the snapshot when the run shown lacked rows of it)
const RUN_TIME_KEYS = ['from', 'to', 'cursor', 'cursor2', 'range', 'markers', 'spans', 'bookmarks', 'arrows', 'compare', 'compareShow', 'runsOver'];
// B: the run compared (its id; 0 the dump of now, while A is a run), the compare's own: dropped with it (✕, compare off,
// Compare… with a file), kept with it in a saved state
Object.defineProperty(WaveView.prototype, 'runCur', { configurable: true,
  get() { const c = this.cmp && this.cmp.result; return c && c.run != null && isFinite(c.run) ? +c.run : null; } });
Object.assign(WaveView.prototype, {
  // who keeps the runs: the page's host (VS Code), null in a browser
  runsHost() { return this.opts.runsHost || (typeof window !== 'undefined' && window.WAVELENS_RUNS) || null; },
  // A: the run whose waves these are (0: the dump of now)
  runsA() { return this.runsShown || 0; },
  // a run's name as the list says it: "#3 golden"; the dump of now: "now"
  runName(id) { if (!id) return 'now'; const r = (this.runsL || []).find(x => x.id === id); return r ? `#${id} ${r.name}` : `#${id}`; },
  // the Runs panel: open, closed (false), or as it is toggled
  runsPanel(on = !this.runsP, focus = true) {
    if (!on) { if (this.runsP) this.runsP.close(); return this; }
    if (!this.runsHost()) { this.toast('the runs kept are VS Code\'s (WaveLens: the Runs panel there), or sva runs keep / diff in a shell'); return this; }
    if (!this.M.timed) { this.toast('runs: these waves are clock-sampled (one cell per cycle): a run is compared on exact waves'); return this; }
    if (!this.runsP) this.runsP = new Runs(this);
    if (focus) this.runsP.focusRow(); else this.refocus();
    return this;
  },
  // the range a … b of the waves shown kept as a slice: a run of its own, its times from 0 (its first sample is 0), so slices
  // compare with each other from their first sample (A one, B another); the panel opens on it
  async keepSlice(a, b) {
    const h = this.runsHost(); if (!h) { this.toast('the slices are kept by VS Code (or sva runs keep DUMP --from T --to T)'); return null; }
    const w = `${this.fmtCursor(a)} … ${this.fmtCursor(b)}`; this.toast(`keeping ${w} as a slice…`);
    let m; try { m = await h.keep({ from: a, to: b }); } catch (e) { m = { error: e.message }; }
    if (m.error || !m.run) { this.toast(`not kept: ${m.error || 'no answer'}`); return null; }
    this.runsPanel(true, false); if (this.runsP) { await this.runsP.load(); this.runsP.fi = this.runsP.rowOf(m.run.id); this.runsP.render(); }
    const s = `#${m.run.id} ${m.run.name} kept: ${w}, its times from 0 (w shows it, B compares it with A)`;
    this.toast(s); if (this.runsP) this.runsP.status(s);
    return m.run;
  },
  // the range a … b of the waves shown as an FST of its own (its times from 0), where the host's save dialog says
  async saveSlice(a, b) {
    const h = this.runsHost();
    if (!h || !h.cut) { this.toast('an FST is written by VS Code (or sva fst DUMP --from T --to T --zero --out X.fst)'); return null; }
    let m; try { m = await h.cut(a, b); } catch (e) { m = { error: e.message }; }
    if (m.cancel) return null;
    this.toast(m.error ? `not saved: ${m.error}` : `saved ${m.path}: ${this.fmtCursor(a)} … ${this.fmtCursor(b)}, its times from 0`);
    return m.path || null;
  },
  // the window a run is compared over: your span chosen (runsWin: its label, from and to — the span followed by what it is,
  // not by its place in the list), else the waves in sight; inside the page's time. A span gone: the waves in sight again (said)
  runsWindow() {
    const { t0, t1 } = this.M, w = this.runsWin, s = w ? this.spans.find(x => sameSpan(x, w)) : null;
    if (w && !s) { this.runsWin = null;
      if (this.runsP) { this.runsP.windows(); this.runsP.status(`the span ${w.label || ''} is gone: over the waves in sight`); } }
    const a = s ? s.from : this.t0, b = s ? s.to : this.t0 + this.span, from = Math.min(Math.max(a, t0), t1);
    return { from, to: Math.max(Math.min(b, t1), from), span: s };
  },
  // the paths compared: the rows of the view, as Compare… sends them
  runsSignals() { return this.cmpRows().map(r => (r.src && r.src.path) || r.path || r.full); },
  // the runs of this dump as the host lists them (newest first), read again when asked (the panel, ]r [r, runs.json changed);
  // the dump of now with them (runsNow: its name, time and size on the disk)
  async runsList(again) {
    const h = this.runsHost(); if (!h) return [];
    if (!this.runsL || again) {
      const m = await h.list(); if (m.error) throw new Error(m.error);
      this.runsL = (m.runs || []).slice().reverse(); this.runsDir = m.dir || ''; this.runsOthers = m.others || 0; this.runsNow = m.now || null;
    }
    return this.runsL;
  },
  // A compared with B (a run's id; 0: the dump of now, while A is a run) over the window: the view shown (A, B, A+B) kept;
  // a later ask wins (the host stops the one before). show: the view to show after it (a step of A: the one of before)
  async runCompare(id, quiet, show) {
    const h = this.runsHost(); if (!h) { this.toast('no runs kept here'); return null; }
    const a = this.runsA(), say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); return null; };
    if (id === a) return say(id ? `#${id} is A, the waves shown: B is another run (or now)` : 'A and B are both now: make a run A (w) first');
    let runs = await this.runsList(), run = id ? runs.find(r => r.id === id) : null;
    if (id && !run) { runs = await this.runsList(true); run = runs.find(r => r.id === id); }   // kept in a shell meanwhile
    if (id && !run) return say(`no run #${id}`);
    const w = this.runsWindow(), req = this.runReq = (this.runReq || 0) + 1, sh = show || (this.cmp ? this.cmpRun : 'a');
    const f = t => this.fmt(t, (this.M.t1 - this.M.t0) / 1000, this.M.t1 - this.M.t0), na = `A ${this.runName(a)}`, nb = `B ${this.runName(id)}`;
    // your span is a test case of the run (its name): the run's case compared, wherever it is in the run
    const cn = w.span && w.span.label ? caseName(w.span.label) : '', byCase = !!run && !!cn && (run.cases || []).some(c => c.name === cn);
    const what = byCase ? `its case ${cn}` : `${f(w.from)} … ${f(w.to)}`;
    if (!quiet) this.toast(`${nb}: comparing with ${na} over ${what}…`);
    if (this.runsP) this.runsP.status(`comparing ${na} with ${nb} over ${what}…`);
    let m;
    try { m = await h.compare(Object.assign({ id, against: a, signals: this.runsSignals(), from: w.from, to: w.to }, byCase ? { case: cn } : {})); }
    catch (e) { m = { error: e.message }; }
    if (req !== this.runReq) return null;   // another run asked meanwhile
    if (m.error || !m.result) { const e = m.error || 'no result'; this.toast(`${nb}: ${e}`); if (this.runsP) this.runsP.status(`${nb}: ${e}`);
      return null; }
    Object.assign(m.result, { name: this.runName(id), run: id, a: a || null });   // B named, and both ids: the saved state has them
    const r = this.compareResult(m.result, quiet);
    if (!r) return null;
    if (sh !== 'a' && this.cmpCan()) await this.compareView(sh, true);
    if (this.runsP) { this.runsP.got(id, w, r);
      this.runsP.status(runSaid(na, nb, r, m.result, w, f, this.cmpCan()) + (cn && !byCase && run && run.cases ? ` · no case ${cn} in it` : '')); }
    return r;
  },
  // ]r [r: B, the next (older) / previous (newer) run of the list (read again: a run kept in a shell is there), A not among
  // them; ]w [w: A, the waves shown, through now and the runs (wrapping), B compared with each, if one is chosen
  async runStep(dir, what = 'b') {
    if (!this.runsHost()) { this.toast(`]${what === 'a' ? 'w' : 'r'}: the runs kept are VS Code's (the Runs panel)`); return this; }
    let runs; try { runs = await this.runsList(true); } catch (e) { this.toast('runs: ' + e.message); return this; }
    if (this.runsP) this.runsP.render();
    const a = this.runsA();
    if (what === 'a') {
      const ids = [0, ...runs.map(r => r.id)], i = ids.indexOf(a);
      if (ids.length < 2) { this.toast('no run kept: Keep this dump… in the Runs panel (gu)'); return this; }
      return this.runsShow(ids[i < 0 ? 0 : (i + dir + ids.length) % ids.length]);
    }
    const ids = runs.map(r => r.id).filter(x => x !== a);
    if (!ids.length) {
      this.toast(runs.length ? 'the one run kept is A, the waves shown: ]w back to now' : 'no run kept: Keep this dump… in the Runs panel (gu)');
      return this; }
    const i = ids.indexOf(this.runCur), j = i < 0 ? (dir > 0 ? 0 : ids.length - 1) : (i + dir + ids.length) % ids.length;
    if (this.runsP) { this.runsP.fi = this.runsP.rowOf(ids[j]); this.runsP.render(); }   // the row lit is the run compared
    await this.runCompare(ids[j]);
    return this;
  },
  // A: a run's waves (0: the dump of now) read into this viewer by the host, the view kept — the window, rows, markers,
  // spans, the panels; the rows a run has not got come back on the next waves that have them (the snapshot: the view as it
  // was on the last waves with all of its rows). B, if any, compared with the new A -> the viewer then
  async runsShow(id, quiet) {
    const h = this.runsHost();
    if (!h || !h.open) { this.toast('a run shown here: VS Code\'s Runs panel (an older extension: update it)'); return this; }
    const say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); return this; };
    if (id === this.runsA()) return say(`${this.runName(id)} is A already: the waves shown`);
    let runs; try { runs = await this.runsList(); } catch (e) { return say('runs: ' + e.message); }
    if (id && !runs.some(r => r.id === id)) runs = await this.runsList(true).catch(() => runs);
    if (id && !runs.some(r => r.id === id)) return say(`no run #${id}`);
    const name = this.runName(id);
    if (this.runsP) this.runsP.status(`reading ${name}…`);
    let m; try { m = await h.open(id); } catch (e) { m = { error: e.message }; }
    if (m.error || !m.file) return say(`${name}: ${m.error || 'not read'}`);
    this.runsTo = id;
    const v = await this.openDump(m.file, m.handle || null, true);
    this.runsTo = undefined;
    return v;
  },
  // the snapshot of the view the runs shown take their rows from: taken on now, and on a run that has every row of it
  runsSnapTake() { if (!this.runsA() || !this.runsSnap || !(this.runsMiss || []).length) this.runsSnap = this.state(); },
  // the view's state for the next waves (openDump keep): its time as it is, its rows from the snapshot while A is a run
  // (A moves: a run shown, or ⟳ — the dump of now — while a run is)
  runsKeep() {
    const move = (this.runsTo !== undefined ? this.runsTo : 0) !== this.runsA();
    if (move) this.runsSnapTake();
    const st = this.state(), snap = move && this.runsSnap;
    if (snap) for (const k of Object.keys(snap)) if (!RUN_TIME_KEYS.includes(k)) st[k] = snap[k];
    if (move) { delete st.compare; delete st.compareShow; }   // the compare of the A of before: made again with the new one (runsAgain)
    // a slice's times are from 0: from the dump to a slice of it (or back, or to a slice elsewhere in it) the times of the view
    // go with it — the same place of the dump in sight, your markers on the same moments
    const d = move ? this.runOrigin(this.runsA()) - this.runOrigin(this.runsTo || 0) : 0;
    if (d) {
      const t = x => (typeof x === 'number' && isFinite(x) ? x + d : x);
      for (const k of ['from', 'to', 'cursor', 'cursor2']) st[k] = t(st[k]);
      if (st.range) st.range = Object.assign({}, st.range, { from: t(st.range.from), to: t(st.range.to) });
      st.markers = (st.markers || []).map(m => Object.assign({}, m, { t: t(m.t) }));
      st.bookmarks = (st.bookmarks || []).map(b => Object.assign({}, b, { t: t(b.t) }));
      st.spans = (st.spans || []).map(x => Object.assign({}, x, { from: t(x.from), to: t(x.to) }));
    }
    return st;
  },
  // where a run's time 0 is in the time of the dump: a slice's from (ps), else 0 (the dump of now, a whole run)
  runOrigin(id) { const r = id && (this.runsL || []).find(x => x.id === id); return r && r.slice && isFinite(r.slice.from) ? +r.slice.from : 0; },
  // the runs' part of the view, kept over a dump read again (⟳, a run shown): the panel, the window, the run compared and
  // how, A (a read again of the dump: now), the snapshot, the list
  runsOf() {
    const to = this.runsTo !== undefined ? this.runsTo : 0;
    if (!this.runsP && this.runCur == null && !this.runsWin && !this.runsA() && !to) return null;
    return { open: !!this.runsP, win: this.runsWin, cur: this.runCur, show: this.cmp ? this.cmpRun : null, shown: to, was: this.runsA(),
      to: this.t0 + this.span, focus: !!this.runsP && this.runsP.el.contains(document.activeElement),
      snap: this.runsSnap || null, list: this.runsL || null, now: this.runsNow || null, dir: this.runsDir, others: this.runsOthers };
  },
  async runsAgain(o) {
    if (!o || !this.runsHost()) return this;
    Object.assign(this, { runsWin: o.win || null, runsShown: o.shown || 0, runsSnap: o.snap, runsL: o.list, runsNow: o.now, runsDir: o.dir,
      runsOthers: o.others });
    if (o.open) this.runsPanel(true, o.focus);   // the keys where they were: the list, or the waves (]w ]w … walks on)
    // what openDump's toast adds (runsNote): A now again, or a run's rows and end
    if (!o.shown && o.was) { this.runsNote = `the dump of now again (${this.runName(o.was)} was shown)`; if (this.runsP) this.runsP.status(this.runsNote); }
    else if (o.shown) this.runsSaid(o);
    const cur = o.cur === this.runsA() ? null : o.cur;   // B made A: compared no more
    if (cur != null) await this.runCompare(cur, true, o.show);   // compared with the new A, over the new waves
    else if (o.cur != null && this.runsP) this.runsP.status(`${this.runName(o.cur)} is A now: no B (click a run to compare)`);
    return this;
  },
  // a run shown: its name, the rows of the snapshot it has not got, where it ends against the window
  runsSaid(o) {
    const miss = (this.runsMiss || []).length, f = t => this.fmt(t, (this.M.t1 - this.M.t0) / 1000, this.M.t1 - this.M.t0);
    const ends = o.to > this.M.t1 ? ` · it ends at ${f(this.M.t1)} (the window reached ${f(o.to)})` : '';
    const note = `A ${this.runName(o.shown)}${miss ? ` · ${miss} of yours not in it: ${this.runsMiss.slice(0, 3).join(', ')}` +
      `${miss > 3 ? ', …' : ''} (back on waves that have them)` : ''}${ends}`;
    this.runsNote = note; if (this.runsP) this.runsP.status(note.replace(/^A [^·]*/, m => `${m.trim()}: the waves shown `).trim());
  },
  // the run removed was the one compared: the compare goes with it; the one shown: the waves stay (the file is read), A says so
  runGone(id) { if (this.runCur === id) this.compare(null); },
});
// what a compare of A with B says: equal, or how many differ and the first; the rows B has not; B's values not loaded and why
function runSaid(na, nb, r, res, w, f, can) {
  const c = res.case, miss = (res.missing || []).length, over = c ? `over the case ${c.name} (B's at ${f(c.from)}` +
    `${c.shorter != null ? `; over the shorter, ${f(c.shorter)}` : ''})` : `over ${f(w.from)} … ${f(w.to)}`;
  const head = r.differ ? `${na} ≠ ${nb}: ${r.differ} of ${r.compared} signals differ ${over}${r.first == null ? '' : `, the first at ${f(r.first)}`}` :
    `${na} = ${nb}: equal ${over} (${r.compared} signals)`;
  return head + (miss ? ` · ${miss} row${miss === 1 ? '' : 's'} B has not` : '') + ((res.notes || []).length ? ` · ${res.notes.join('; ')}` : '') +
    (r.differ && !can ? ` · B's values not loaded${res.cutError ? ': ' + res.cutError : ''} (bands only)` : '');
}
PLUGINS.push(v => { v.addKey(']r', () => v.runStep(1)).addKey('[r', () => v.runStep(-1));
  v.addKey(']w', () => v.runStep(1, 'a')).addKey('[w', () => v.runStep(-1, 'a')); });

/* ---------------- the panel ---------------- */
// One per viewer, over it, as the Modules panel (its look, its header moves it, its corner sizes it). Rows: the dump of now
// first, then a run each, newest first: #id, its name, tags, when kept, its comment; on the left the two roles, A (the
// waves shown) and B (compared with A), lit on the row that has it and buttons on each; after a compare or Δ all, how many
// signals differ from A in the window and the first difference. Keys: ↑ ↓ Home End go through the rows and make them B,
// Enter makes the row B, w makes it A, x: no B (the waves only), e edits, Delete removes (the host asks), k keeps this dump,
// a Δ all, Esc closes (the form: cancels it).
const RUN_H = 40;
class Runs {
  constructor(v) {
    this.v = v; this.fi = 0; this.ac = new AbortController(); this.deltas = new Map(); this.edit = null; this.settle = null;
    const el = this.el = document.createElement('div'); el.className = 'wv-mods wv-runs'; el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'runs kept');
    el.innerHTML = ('<div class="mh"><b>Runs kept</b><span class="mt"></span><button type="button" data-a="x" aria-label="close" ' +
      'title="Close (Esc)">✕</button></div>' +
      '<div class="mf"><button type="button" data-a="keep" title="Keep the dump of now as a run: a name, tags, a comment (k)">Keep this dump…</button>' +
      '<label title="The window a run is compared over: the waves in sight, or one of your spans (only that time of the run is read)">over ' +
      '<select class="rw" aria-label="the window compared"></select></label>' +
      '<button type="button" data-a="all" title="How many signals of each run differ from A in the window (a)">Δ all</button>' +
      '<button type="button" data-a="again" title="Compare A with B again over the window as it is now">⟳</button>' +
      '<button type="button" data-a="nob" title="No B: the waves only, nothing compared (x); ]w [w then walk the runs">no B</button></div>' +
      '<form class="rf" hidden><input type="text" class="rfn" spellcheck="false" placeholder="name" aria-label="the run\'s name">' +
      '<input type="text" class="rft" spellcheck="false" placeholder="tags, a comma between them" aria-label="tags">' +
      '<textarea class="rfc" rows="2" placeholder="comment" aria-label="comment"></textarea>' +
      '<span class="rfb"><button type="submit" class="rfo">Keep</button><button type="button" data-a="cancel">Cancel</button></span></form>' +
      '<div class="ms"></div><div class="mtr rl" role="listbox" aria-label="runs kept" tabindex="0"><div class="mrows"></div></div>');
    v.root.append(el);
    this.rowsEl = el.querySelector('.mrows'); this.list = el.querySelector('.rl'); this.stEl = el.querySelector('.ms'); this.form = el.querySelector('.rf');
    this.win = el.querySelector('.rw');
    panelPlace(this, 'runs');
    this.events(); this.windows(); this.load();
  }
  close(quiet) { panelKeep(this, 'runs'); clearTimeout(this.settle); this.ac.abort(); this.el.remove(); if (this.v.runsP === this) this.v.runsP = null;
    if (!quiet) this.v.refocus(); }
  focusRow() { if (this.form.hidden) this.list.focus(); else this.form.querySelector('.rfn').focus(); }
  status(s) { this.stEl.textContent = s || ''; }
  // the rows: the dump of now (id 0), then the runs, newest first
  rows() { const n = this.v.runsNow || {}; return [Object.assign({}, n, { id: 0, now: true, name: 'now', dump: n.name || '' }), ...(this.v.runsL || [])]; }
  rowOf(id) { return Math.max(0, this.rows().findIndex(r => r.id === id)); }
  async load(again = true) {
    try { await this.v.runsList(again); } catch (e) { this.status('runs: ' + e.message); return; }
    const o = this.v.runsOthers, mt = this.el.querySelector('.mt');
    mt.textContent = (this.v.runsDir || '') + (o ? ` · ${o} of other dumps` : '');
    mt.title = o ? `${o} run${o === 1 ? '' : 's'} of other dumps in this directory (sva runs list --all)` : '';
    const cur = this.v.runCur; this.fi = this.rowOf(cur != null ? cur : this.v.runsA());
    this.render();
    if (!this.v.runsL.length) this.status('no run kept yet: Keep this dump… (the dump of now, as an FST in the runs\' directory)');
  }
  // the window choices: the waves in sight, then your spans as they are now (a span chosen and gone: the waves in sight)
  windows() {
    const v = this.v, f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0);
    const i = v.runsWin ? v.spans.findIndex(x => sameSpan(x, v.runsWin)) : -1;
    if (v.runsWin && i < 0) v.runsWin = null;
    const cases = new Set((v.runsL || []).flatMap(r => (r.cases || []).map(c => c.name)));
    this.win.innerHTML = '<option value="view">the waves in sight</option>' + v.spans.map((s, k) =>
      `<option value="${k}">${esc(s.label || 'span')} (${esc(f(s.from))} … ${esc(f(s.to))})` +
      `${s.label && cases.has(caseName(s.label)) ? ' · a case' : ''}</option>`).join('');
    this.win.value = i < 0 ? 'view' : String(i);
  }
  // a compare's numbers for the run (against A), of that window
  got(id, w, r) { if (r) this.deltas.set(id, { from: w.from, to: w.to, differ: r.differ, compared: r.compared, first: r.first, a: this.v.runsA() });
    this.render(); }
  // Δ numbers of another window than the one now, or of another A: greyed, their window in their text
  stale(d) { const w = this.v.runsWindow(); return Math.abs(d.from - w.from) > 1e-6 || Math.abs(d.to - w.to) > 1e-6 || (d.a || 0) !== this.v.runsA(); }
  render() {
    const v = this.v, rows = this.rows(), f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0), a = v.runsA(), b = v.runCur;
    const hm = s => (s || '').slice(0, 16).replace('T', ' ');
    const mb = n => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} kB`);
    const me = v.runsNow && v.runsNow.name;
    this.fi = Math.max(0, Math.min(this.fi, rows.length - 1));
    this.rowsEl.style.height = rows.length * RUN_H + 'px';
    this.rowsEl.innerHTML = rows.map((r, i) => {
      const d = this.deltas.get(r.id), tags = (r.tags || []).map(t => `<span class="rtag">${esc(t)}</span>`).join('');
      const old = d && !d.error && this.stale(d), over = d && !d.error ? `${esc(f(d.from))} … ${esc(f(d.to))}` : '';
      const cmpOld = old && r.id === b ? ' (the compare on the waves)' : '';
      const delta = !d || r.id === a ? '' : d.error ? `<span class="rd bad" title="${esc(d.error)}">${esc(d.error)}</span>` :
        `<span class="rd${d.differ ? ' bad' : ''}${old ? ' old' : ''}" title="against A ${esc(v.runName(d.a || 0))} over ${over}${cmpOld}` +
        `${old ? ' (not the window or the A of now: ⟳ or Δ all again)' : ''}">` +
        `${d.outside ? 'not in this window' : d.differ ? `≠ ${d.differ} of ${d.compared}${d.first == null ? '' : ` · ${esc(f(d.first))}`}` : '= equal'}` +
        `${old ? ` (${over})` : ''}</span>`;
      const ab = `<span class="rab"><button type="button" data-a="ra" class="rA${r.id === a ? ' on' : ''}" aria-pressed="${r.id === a}" ` +
        `title="${r.id === a ? 'A: the waves shown here' : 'Make it A: its waves shown here, the view kept (w)'}">A</button>` +
        `<button type="button" data-a="rb" class="rB${r.id === b ? ' on' : ''}" aria-pressed="${r.id === b}" ` +
        `title="${r.id === b ? 'B: compared with A (click: no B)' : 'Make it B: compared with A over the window (Enter)'}">B</button></span>`;
      const when = r.now ? `${r.mtime ? new Date(r.mtime).toISOString().slice(0, 16).replace('T', ' ') + ' on the disk' : 'the dump on the disk'}` :
        `kept ${hm(r.kept)}${r.source_mtime && Math.abs(Date.parse(r.source_mtime) - Date.parse(r.kept)) > 60000 ?
          ` of a dump of ${hm(r.source_mtime).slice(11)}` : ''}`;
      const size = r.now || r.slice ? r.bytes : r.source_bytes, sl = r.slice && isFinite(r.slice.from) && isFinite(r.slice.to) ?
        `slice ${f(r.slice.from)} … ${f(r.slice.to)}, from 0` : '';
      const line2 = [r.now ? r.dump : r.dump && r.dump !== me ? r.dump : '', sl, when, size ? mb(size) : '',
        r.cases && r.cases.length ? `${r.cases.length} case${r.cases.length === 1 ? '' : 's'}` : '', r.comment ? r.comment.split('\n')[0] : '']
        .filter(Boolean).map(esc).join(' · ');
      return `<div class="mn rn${r.now ? ' rnow' : ''}${i === this.fi ? ' pv' : ''}" role="option" data-i="${i}" style="top:${i * RUN_H}px" ` +
        `title="${esc(r.now ? `the dump of now: ${r.dump}` : `${r.dump || ''} kept ${(r.kept || '').replace('T', ' ').replace('Z', ' UTC')}` +
          `${r.comment ? '\n' + r.comment : ''}`)}">` +
        `<span class="r1">${ab}<b>${r.now ? 'now' : '#' + esc(String(r.id))}</b> <span class="nm">${r.now ? '' : esc(r.name || '')}</span>` +
        `<span class="rtags">${tags}</span>${delta}` + (r.now ? '' :
          '<button type="button" data-a="ed" title="Name, tags, comment (e)">✎</button>' +
          '<button type="button" data-a="rm" title="Remove the run and its file (Delete)">✕</button>') + '</span>' +
        `<span class="r2">${line2}</span></div>`;
    }).join('');
    const cur = this.rowsEl.children[this.fi];
    if (cur) { const t = cur.offsetTop, h = this.list.clientHeight; if (t < this.list.scrollTop) this.list.scrollTop = t;
      else if (t + RUN_H > this.list.scrollTop + h) this.list.scrollTop = t + RUN_H - h; }
  }
  // the form: keep the dump of now (edit null), or a run's name, tags, comment
  openForm(run) {
    if (run && run.now) { this.status('now is the dump on the disk: keep it as a run first (k)'); return; }
    const v = this.v; this.edit = run || null; this.form.hidden = false;
    this.form.querySelector('.rfn').value = run ? run.name : (v.runsNow && v.runsNow.name) || v.opts.title || v.M.title || '';
    this.form.querySelector('.rft').value = run ? (run.tags || []).join(', ') : '';
    this.form.querySelector('.rfc').value = run ? run.comment || '' : '';
    this.form.querySelector('.rfo').textContent = run ? 'Save' : 'Keep';
    this.form.querySelector('.rfn').select(); this.focusRow();
  }
  closeForm() { this.form.hidden = true; this.edit = null; this.list.focus(); }
  async submit() {
    const h = this.v.runsHost(), q = s => this.form.querySelector(s).value;
    const body = { name: q('.rfn').trim(), tags: q('.rft').split(',').map(s => s.trim()).filter(Boolean), comment: q('.rfc') };
    const run = this.edit; this.closeForm();
    this.status(run ? `#${run.id}: saving…` : 'keeping the dump of now (written as an FST in the runs\' directory)…');
    // a run kept: your spans with a label as its test cases (none: the host takes cocotb's marks beside the dump)
    const cases = this.v.spans.filter(s => s.label && caseName(s.label)).map(s => ({ label: s.label, from: s.from, to: s.to }));
    let m;
    try { m = run ? await h.set(run.id, body) : await h.keep(cases.length ? Object.assign({ cases }, body) : body); } catch (e) { m = { error: e.message }; }
    if (m.error) { this.status((run ? 'not saved: ' : 'not kept: ') + m.error); return; }
    await this.load(); if (!run && m.run) { this.fi = this.rowOf(m.run.id); this.render(); }
    this.status(run ? `#${run.id} saved` : m.run ? `kept as #${m.run.id} ${m.run.name}` : 'kept');
  }
  async remove(run) {
    if (run.now) { this.status('now is the dump on the disk: not a run'); return; }
    let m; try { m = await this.v.runsHost().rm(run.id); } catch (e) { m = { error: e.message }; }
    if (m.error) { this.status('not removed: ' + m.error); return; }
    if (m.cancelled) return;
    const cur = this.v.runCur === run.id, shown = this.v.runsA() === run.id; this.v.runGone(run.id);
    this.deltas.delete(run.id); await this.load(); this.status(`#${run.id} ${run.name} removed${cur ? ', the compare with it dropped' : ''}`);
    if (shown) await this.v.runsShow(0);   // its file is gone: the dump of now shown again
  }
  // Δ all: sva runs diff over the window, each run's numbers against A on its row
  async all() {
    const v = this.v, w = v.runsWindow(), f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0), a = v.runsA();
    // your span a case of some run: each run over its case of that name (a run without it: said on its row)
    const cn = w.span && w.span.label ? caseName(w.span.label) : '', byCase = !!cn && (v.runsL || []).some(r => (r.cases || []).some(c => c.name === cn));
    const over = byCase ? `the case ${cn}` : `${f(w.from)} … ${f(w.to)}`;
    this.status(`each run against A ${v.runName(a)} over ${over}…`);
    let m; try { m = await v.runsHost().diff(Object.assign({ signals: v.runsSignals(), from: w.from, to: w.to, against: a }, byCase ? { case: cn } : {})); }
    catch (e) { m = { error: e.message }; }
    if (m.error) { this.status('Δ all: ' + m.error); return; }
    let n = 0;
    for (const x of m.runs || []) {
      const id = x.id === 'now' ? 0 : x.id;
      if (x.error) { this.deltas.set(id, { error: x.error }); continue; }
      if (x.signals_differ || x.outside) n++;
      this.deltas.set(id, { from: x.from ?? w.from, to: x.to ?? w.to, differ: x.signals_differ || 0, compared: x.signals_compared || 0,
        first: x.first ? x.first.t : null, outside: !!x.outside, a });
    }
    this.render();
    this.status(`${n} of ${(m.runs || []).length} runs differ from A ${v.runName(a)} over ${over}`);
  }
  // a row chosen: made B at once (a click, Enter) or when the keys stop (settle: ↑ ↓ Home End PgUp PgDn held down
  // compare once, the row they stop on); the row of A only focused
  pick(i, compare = true, settle = false) {
    const rows = this.rows();
    this.fi = Math.max(0, Math.min(i, rows.length - 1)); this.render();
    clearTimeout(this.settle);
    const id = rows[this.fi].id;
    if (!compare) return;
    if (id === this.v.runsA()) { if (!settle) this.status(`${this.v.runName(id)} is A, the waves shown: B is another row`); return; }
    if (settle) this.settle = setTimeout(() => this.v.runCompare(id, true), RUN_SETTLE); else this.v.runCompare(id, true);
  }
  // no B: the compare dropped, the waves only
  noB() { clearTimeout(this.settle); if (this.v.runCur != null) this.v.compare(null);
    this.render(); this.status('no B: the waves only (]w [w walk the runs)'); }
  events() {
    const v = this.v, el = this.el, sig = { signal: this.ac.signal };
    el.addEventListener('click', e => {
      const b = e.target.closest('button[data-a]'), row = e.target.closest('.rn'), run = row && this.rows()[+row.dataset.i];
      if (b) {
        const a = b.dataset.a;
        if (a === 'x') this.close();
        else if (a === 'keep') this.openForm(null);
        else if (a === 'cancel') this.closeForm();
        else if (a === 'all') this.all();
        else if (a === 'nob') this.noB();
        else if (a === 'again') { if (v.runCur != null) v.runCompare(v.runCur, true);
          else this.status('no B: click a run first, it is compared with A over the window'); }
        else if (a === 'ed' && run) this.openForm(run);
        else if (a === 'rm' && run) this.remove(run);
        else if (a === 'ra' && run) { this.fi = +row.dataset.i; v.runsShow(run.id); }
        else if (a === 'rb' && run) { if (v.runCur === run.id) this.noB(); else this.pick(+row.dataset.i); }
        return;
      }
      if (row) this.pick(+row.dataset.i);
    }, sig);
    this.form.addEventListener('submit', e => { e.preventDefault(); this.submit(); }, sig);
    this.win.addEventListener('focus', () => this.windows(), sig);   // your spans as they are now
    this.win.addEventListener('change', () => { const s = this.win.value === 'view' ? null : v.spans[+this.win.value];
      v.runsWin = s ? { label: s.label || '', from: s.from, to: s.to } : null; this.render(); }, sig);
    el.addEventListener('keydown', e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (!this.form.hidden) this.closeForm(); else this.close(); return; }
      if (e.target.closest('input, textarea, select')) { e.stopPropagation(); return; }   // typing: not the viewer's keys
      const rows = this.rows(), run = rows[this.fi], k = e.key;
      const go = { ArrowDown: this.fi + 1, ArrowUp: this.fi - 1, Home: 0, End: rows.length - 1, PageDown: this.fi + 5, PageUp: this.fi - 5 }[k];
      if (go !== undefined) this.pick(go, true, true);
      else if (k === 'Enter' && run) this.pick(this.fi);
      else if (k === 'w' && run) v.runsShow(run.id);
      else if (k === 'x') this.noB();
      else if (k === 'e' && run) this.openForm(run);
      else if ((k === 'Delete' || k === 'Backspace') && run) this.remove(run);
      else if (k === 'k') this.openForm(null);
      else if (k === 'a') this.all();
      else return;
      e.preventDefault(); e.stopPropagation();
    }, sig);
    panelFrame(this, 'runs');   // the header moves it, its edges and corners size it (modules.js)
  }
}
