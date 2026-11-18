/* wavelens/src/runs.js — the runs kept of a dump (gu, Runs… in the bar): the dumps of runs before, kept by hand with a
   name, tags and a comment (VS Code: sva runs keep, into .wavelens-runs beside the dump, as FSTs). The list holds the dump
   of now (the row "now") and every run; two of them have a role, a letter on their row: A, the waves shown here (the dump
   of now at first; w on a row, ]w [w anywhere: a run's waves read into this viewer, the window, the rows and the markers
   kept), and B, the run compared with A over a window — the waves in sight or one of your spans: only that window of the
   runs is read (sva runs diff, then the values of the signals that differ there), so a large run costs the window, not the
   dump. Choosing does nothing but pick: a click on a row (Enter, ↑ ↓ in the list, ]r [r anywhere) picks it as B, w picks
   it as A — their letters lit, nothing read; Compare (c in the list, the panel's and the bar's button, g=) then opens A when
   it is not the waves shown (the view kept) and compares A with B over the window in sight; zoomed or panned since, the
   compare on the waves stays as it was until Compare again. x: no B, the waves only (]w [w then walk the runs, nothing
   compared). The compare's A B A+B and ]d [d as Compare… has them; Δ all: how many signals of each run
   differ from A in the window. Keep this dump… adds the dump of now. The panel has two modes (its switch, o in the list;
   runsMode, kept with the view's state): Compare, as said, and Open — a row chosen opens its waves here (A), one run after
   another, no B, nothing compared. A slice's row applies its span (s): the window and the range of the waves shown on the
   slice's start and end, in A's time. The directory of the runs is the panel's last line (its ★: the setting wavelens.runsDir
   written by the host). The page asks its host (window.WAVELENS_RUNS: list, keep, set, rm, diff, compare, cancel, open, cut,
   dir; the VS Code extension's media/host.js gives it); without one (a page in a browser) there are none. A run keeps its
   test cases (your spans with a label when kept, or cocotb's marks beside the dump): a span of yours a run has a case of (by
   name) is compared with that case of the run, wherever it is in the run (B offset to it, over the shorter of the two). */

// the snapshot's part of the rows these waves lack (miss: their paths) put back into the state st of now — their colour, radix,
// plot, hidden, copies, bits, places in your groups, the selection, the signals of your marks; the rest is st's (the edits
// made meanwhile)
function runsMerge(st, snap, miss) {
  const m = new Set(miss), lost = p => typeof p === 'string' && m.has(p);
  for (const k of ['paint', 'radix', 'analog']) { const o = snap[k] || {}; st[k] = Object.assign({}, st[k] || {});
    for (const p of Object.keys(o)) if (lost(p) && !(p in st[k])) st[k][p] = o[p]; }
  for (const k of ['hidden', 'dups', 'bits']) { const now = st[k] || []; st[k] = now.concat((snap[k] || []).filter(p => lost(p) && !now.includes(p))); }
  if (snap.config && st.config) for (const k of ['fold', 'highlight']) { const now = st.config[k] || [];
    st.config[k] = now.concat((snap.config[k] || []).filter(p => lost(p) && !now.includes(p))); }
  if (st.select == null && lost(snap.select)) st.select = snap.select;
  // a group: the signals it had there, back at their places (one of yours made meanwhile: as it is); a group with only lost ones: back
  const gs = (st.groups || []).map(g => Object.assign({}, g, { signals: [...(g.signals || [])] }));
  for (const g of snap.groups || []) { const h = gs.find(x => x.name === g.name);
    if (!h) { if ((g.signals || []).length && g.signals.every(lost)) gs.push(Object.assign({}, g)); continue; }
    (g.signals || []).forEach((p, i) => { if (lost(p) && !h.signals.includes(p)) h.signals.splice(Math.min(i, h.signals.length), 0, p); }); }
  st.groups = gs;
  if (snap.only && st.only) { const ms = st.only.modules || []; st.only = Object.assign({}, st.only,
    { modules: ms.concat((snap.only.modules || []).filter(p => lost(p) && !ms.includes(p))) }); }
  // a mark whose signal these waves lacked went to the top: the same mark (its place in the list, its label) takes it back
  for (const k of ['markers', 'bookmarks']) (st[k] || []).forEach((x, i) => { const o = (snap[k] || [])[i];
    if (!o || (o.label || '') !== (x.label || '') || (o.text || '') !== (x.text || '')) return;
    for (const s of ['signal', 'dsignal']) if (x[s] == null && lost(o[s])) { x[s] = o[s]; if (s === 'signal' && o.lift != null) x.lift = o.lift;
      if (s === 'dsignal' && o.dlift != null) x.dlift = o.dlift; } });
}
/* ---------------- the viewer's side ---------------- */
const RUN_OPEN_SETTLE = 600;   // ms: the Open mode, the keys move the row, its waves are read (a dump) when they rest (Enter at once)
// a tag's hue, of its text (FNV-1a, then murmur3's last mix: short texts that differ by a letter fall far apart): the same tag
// the same colour on every row, every day; the CSS mixes it with the theme's
const tagHue = t => {
  let h = 2166136261; for (const c of String(t)) h = Math.imul(h ^ c.codePointAt(0), 16777619);
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b); h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); h ^= h >>> 16;
  return (h >>> 0) % 360;
};
// a case's name of a span's label: without "TC3 " before it and " · PASS" after it (cocotb's marks); sva runs.rs case_name
const caseName = l => { const s = String(l || '').split(' · ')[0].trim(), m = /^TC\d+ (.*)$/.exec(s); return (m ? m[1] : s).trim(); };
const sameSpan = (s, w) => !!s && !!w && s.from === w.from && s.to === w.to && (s.label || '') === (w.label || '');
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
  runName(id) { if (!id) return 'now'; const r = (this.runsL || []).find(x => x.id === id);
    return r ? `#${id} ${r.name}` : id === this.runsA() && this.runsAOf ? this.runsAOf.name : `#${id}`; },
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
    let m; try { m = await h.keep({ from: a, to: b, of: this.runsA() }); } catch (e) { m = { error: e.message }; }
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
    let m; try { m = await h.cut(a, b, this.runsA()); } catch (e) { m = { error: e.message }; }
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
      this.runsDirOf = m.dirOf || null;   // where the directory comes from: {set: the setting's text ('' the default), scope}
    }
    return this.runsL;
  },
  // A compared with B (a run's id; 0: the dump of now, while A is a run) over the window: the view shown (A, B, A+B) kept;
  // a later ask wins (the host stops the one before). show: the view to show after it (a step of A: the one of before)
  async runCompare(id, quiet, show) {
    const h = this.runsHost(); if (!h) { this.toast('no runs kept here'); return null; }
    if (this.runsMode === 'open') this.runsModeSet('compare', true);   // a B asked (]r [r, a caller): the panel compares again
    const a = this.runsA(), say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); return null; };
    if (id === a) return say(id ? `#${id} is A, the waves shown: B is another run (or now)` : 'A and B are both now: make a run A (w) first');
    let runs = await this.runsList(), run = id ? runs.find(r => r.id === id) : null;
    if (id && !run) { runs = await this.runsList(true); run = runs.find(r => r.id === id); }   // kept in a shell meanwhile
    if (id && !run) return say(`no run #${id}`);
    const w = this.runsWindow(), req = this.runReq = (this.runReq || 0) + 1, sh = show || (this.cmp ? this.cmpRun : 'a');
    this.cmpReq = (this.cmpReq || 0) + 1;   // a compare asked before (Compare…, a dump read here) not taken when it comes
    const f = t => this.fmt(t, (this.M.t1 - this.M.t0) / 1000, this.M.t1 - this.M.t0), na = `A ${this.runName(a)}`, nb = `B ${this.runName(id)}`;
    // your span is a test case of the run (its name): the run's case compared, wherever it is in the run
    const cn = w.span && w.span.label ? caseName(w.span.label) : '', byCase = !!run && !!cn && (run.cases || []).some(c => c.name === cn);
    const what = byCase ? `its case ${cn}` : `${f(w.from)} … ${f(w.to)}`;
    if (!quiet) this.toast(`${nb}: comparing with ${na} over ${what}…`);
    if (this.runsP) this.runsP.status(`comparing ${na} with ${nb} over ${what}…`);
    let m;
    this.runWait = req;
    try { m = await h.compare(Object.assign({ id, against: a, signals: this.runsSignals(), from: w.from, to: w.to }, byCase ? { case: cn } : {})); }
    catch (e) { m = { error: e.message }; }
    if (this.runWait === req) this.runWait = 0;
    if (req !== this.runReq) return null;   // another run asked meanwhile, or B dropped or replaced (runsDrop)
    if (m.error || !m.result) { const e = m.error || 'no result'; this.toast(`${nb}: ${e}`); if (this.runsP) this.runsP.status(`${nb}: ${e}`);
      return null; }
    Object.assign(m.result, { name: this.runName(id), run: id, a: a || null });   // B named, and both ids: the saved state has them
    if (this.runPickB === id) this.runPickB = null; if (this.runPickA === a) this.runPickA = null;   // the picks are the compare now
    const r = this.compareResult(m.result, quiet);
    if (!r) return null;
    if (sh !== 'a' && this.cmpCan()) await this.compareView(sh, true);
    if (this.runsP) { this.runsP.got(id, w, r);
      this.runsP.status(runSaid(na, nb, r, m.result, w, f, this.cmpCan()) + (cn && !byCase && run && run.cases ? ` · no case ${cn} in it` : '')); }
    return r;
  },
  // the panel's mode: 'compare' (a row chosen is B, compared with A) or 'open' (a row chosen opens its waves here, one run
  // after another: no B, nothing compared — the B of before dropped); kept with the view's state (runsMode)
  runsModeSet(mode, quiet) {
    const m = mode === 'open' ? 'open' : 'compare', was = this.runsMode === 'open' ? 'open' : 'compare', b = this.runCur;
    this.runsMode = m;
    if (m === was) return this;
    if (m === 'open') { this.runsDrop(); this.runPickA = this.runPickB = null; if (b != null) this.compare(null); else this.cmpShow(); }
    if (this.runsP) this.runsP.mode(quiet, m === 'open' && b != null);
    return this;
  },
  // a slice's span on the waves shown (A): the window and the range on the slice's start and end — its from … to in the time
  // of the dump it was cut from, less A's origin when A is a slice itself (its times from 0) — so Slice ▸ takes the same
  // piece of these waves. A span past an end of A: cut to A (said); wholly outside: said, not applied -> [from, to] or null
  runsSpan(id, quiet) {
    const say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); };
    const r = (this.runsL || []).find(x => x.id === id), s = r && r.slice, name = this.runName(id);
    if (!r) { say(id ? `no run #${id}` : 'now is the dump on the disk: a slice\'s row has a span'); return null; }
    if (!s || !isFinite(s.from) || !isFinite(s.to)) { say(`${name} is a whole run, not a slice: no span of its own`); return null; }
    const { t0, t1 } = this.M, f = t => this.fmt(t, (t1 - t0) / 1000, t1 - t0), a = this.runsA();
    const d = this.runOrigin(a) || 0, p = s.from - d, q = s.to - d, lo = Math.max(p, t0), hi = Math.min(q, t1);
    // where it is in the dump, when A's time is not the dump's
    const of = d ? ` (${f(s.from)} … ${f(s.to)} of the dump: A is a slice from ${f(d)})` : '';
    if (!(hi > lo)) { say(`the span of ${name}, ${f(p)} … ${f(q)}${of}, is outside these waves (A ${this.runName(a)}: ${f(t0)} … ${f(t1)}): ` +
      'not applied'); return null; }
    this.zoomTo(lo, hi); this.warpSync(); this.setRange(lo, hi);
    say(`the span of ${name} on A ${this.runName(a)}: the window and the range ${f(lo)} … ${f(hi)}${of}` +
      `${lo > p || hi < q ? ` — cut to these waves (its ${f(p)} … ${f(q)})` : ''} · Slice ▸ takes this piece`);
    return [lo, hi];
  },
  // ★: the directory of the runs made the permanent one (on false: no more) — the host writes the setting wavelens.runsDir
  // (VS Code: the workspace's settings when the dump is in a workspace folder, else the user's), the list read again
  async runsDirKeep(on = true) {
    const h = this.runsHost(), say = s => { this.toast(s); if (this.runsP) this.runsP.status(s); return this; };
    if (!h || !h.dir) return say('the runs\' directory is set by VS Code (the setting wavelens.runsDir)');
    let m; try { m = await h.dir(!!on); } catch (e) { m = { error: e.message }; }
    if (m.error) return say(`the runs' directory: ${m.error}`);
    const o = m.dirOf || {}, was = this.runsDir, moved = m.dir !== was;
    const where = o.scope ? `the ${o.scope === 'user' ? 'user' : 'workspace'}'s settings` : 'the settings';
    // another directory: its runs are others (their numbers too) — no B, no Δ of before, the dump of now shown
    if (moved) { this.runsDrop(); if (this.runCur != null) this.compare(null); if (this.runsP) this.runsP.deltas.clear(); }
    if (this.runsP) await this.runsP.load(); else await this.runsList(true).catch(() => {});
    if (moved && this.runsA()) this.runsShow(0, true);
    return say(o.set ? `★ wavelens.runsDir = ${o.set} (${where}): the runs of this dump are kept in ${m.dir}, the other dumps' by the same ` +
      `setting${on ? '' : ' — still set there'}` : `wavelens.runsDir cleared: the runs beside each dump again (.wavelens-runs)` +
      `${moved ? `, here ${m.dir}; the ones of before stay in ${was}` : ''}`);
  },
  // B dropped or replaced (no B, ✕, compare off, Compare…, a result given): a run compare still asked is not taken when it comes,
  // and the host stops it (runs cancel; B-63, B-64)
  runsDrop() {
    this.runReq = (this.runReq || 0) + 1;
    if (!this.runWait) return;
    this.runWait = 0; const h = this.runsHost();
    if (h && h.cancel) Promise.resolve().then(() => h.cancel()).catch(() => {});
  },
  // ]r [r: B, the next (older) / previous (newer) run of the list (read again: a run kept in a shell is there), A not among
  // them; ]w [w: A, the waves shown, through now and the runs (wrapping), B compared with each, if one is chosen
  async runStep(dir, what = 'b') {
    if (!this.runsHost()) { this.toast(`]${what === 'a' ? 'w' : 'r'}: the runs kept are VS Code's (the Runs panel)`); return this; }
    let runs; try { runs = await this.runsList(true); } catch (e) { this.toast('runs: ' + e.message); return this; }
    if (this.runsP) this.runsP.render();
    const a = this.runsA();
    if (what === 'a') {
      // the ring goes on from the run tried last when its waves did not open (a file gone): A stays, the one after it next
      const ids = [0, ...runs.map(r => r.id)], from = this.runsTried != null && ids.includes(this.runsTried) ? this.runsTried : a;
      if (ids.length < 2) { this.toast('no run kept: Keep this dump… in the Runs panel (gu)'); return this; }
      const at = k => ids[(ids.indexOf(from) + k * dir + ids.length * 2) % ids.length];
      const next = at(1) === a && from !== a && ids.length > 2 ? at(2) : at(1);
      this.runsTried = next;
      return this.runsShow(next);
    }
    const ids = [...runs.map(r => r.id), ...(a ? [0] : [])].filter(x => x !== a);   // A a run: now is a B too (the panel's row)
    if (!ids.length) {
      this.toast(runs.length ? 'the one run kept is A, the waves shown: ]w back to now' : 'no run kept: Keep this dump… in the Runs panel (gu)');
      return this; }
    const i = ids.indexOf(this.runsB()), j = i < 0 ? (dir > 0 ? 0 : ids.length - 1) : (i + dir + ids.length) % ids.length;
    this.runsPickB(ids[j]);   // picked, not compared: Compare (g=) compares it
    if (this.runsP) { this.runsP.fi = this.runsP.rowOf(ids[j]); this.runsP.render(); }
    return this;
  },
  // A: a run's waves (0: the dump of now) read into this viewer by the host, the view kept — the window, rows, markers,
  // spans, the panels; the rows a run has not got come back on the next waves that have them (the snapshot: the view as it
  // was on the last waves with all of its rows). B, if any, compared with the new A -> the viewer then
  async runsShow(id, quiet) {
    const h = this.runsHost();
    if (!h || !h.open) { this.toast('a run shown here: VS Code\'s Runs panel (an older extension: update it)'); return this; }
    const say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); return this; };
    // one ask at a time per element: an answer to an ask made before the last one is dropped (the later ask wins, B-61)
    const tok = this.root.wlRunsAsk = (this.root.wlRunsAsk || 0) + 1, stale = () => tok !== this.root.wlRunsAsk;
    if (id === this.runsA()) return say(`${this.runName(id)} is A already: the waves shown`);
    let runs; try { runs = await this.runsList(); } catch (e) { return say('runs: ' + e.message); }
    if (id && !runs.some(r => r.id === id)) runs = await this.runsList(true).catch(() => runs);
    if (id && !runs.some(r => r.id === id)) return say(`no run #${id}`);
    const name = this.runName(id);
    if (this.runsP) this.runsP.status(`reading ${name}…`);
    this.runsOpening = id;   // the run being read (the panel: the keys back on A meanwhile open A again)
    let m; try { m = await h.open(id); } catch (e) { m = { error: e.message }; }
    if (stale()) return this.root.waveView || this;
    this.runsOpening = null;
    if (m.error || !m.file) return say(`${name}: ${m.error || 'not read'}${this.runsTried === id ? ' (]w goes on)' : ''}`);
    return this.openDump(m.file, m.handle || null, { runs: id });   // the run asked goes with the open (to the viewer there then)
  },
  // the snapshot of the view the runs shown take their rows from: the view of now, and what the snapshot of before said of
  // the rows these waves lack (runsMiss): an edit made meanwhile stays, a row missing twice in a row is not forgotten
  runsSnapTake() {
    const st = this.state(), miss = this.runsMiss || [];
    if (this.runsA() && this.runsSnap && miss.length) runsMerge(st, this.runsSnap, miss);
    return (this.runsSnap = st);
  },
  // the view's state for the next waves (openDump keep): its time as it is, its rows from the snapshot while A is a run
  // (A moves: a run shown, or ⟳ — the dump of now — while a run is)
  runsKeep() {
    const move = (this.runsTo !== undefined ? this.runsTo : 0) !== this.runsA();
    const st = move ? JSON.parse(JSON.stringify(this.runsSnapTake())) : this.state();
    // the compare of the A of before (or of these waves before they were read again): not taken over, its B picked again (runsAgain)
    // (null, not left out: the viewer may be this one, its compare would stay)
    if (move || this.runCur != null || (this.cmp && this.cmp.result && this.cmp.result.src)) { st.compare = null; delete st.compareShow; }
    // a slice's times are from 0: from a whole one (the dump, a whole run) to a slice and back the times of the view go with
    // it — the same place of the dump in sight, your markers on the same moments; slice to slice: both from 0, as they compare
    const d = move ? this.runsShift() : 0;
    if (d) {
      const t = x => (typeof x === 'number' && isFinite(x) ? x + d : x);
      for (const k of ['from', 'to', 'cursor', 'cursor2']) st[k] = t(st[k]);
      if (st.range) st.range = Object.assign({}, st.range, { from: t(st.range.from), to: t(st.range.to) });
      st.markers = (st.markers || []).map(m => Object.assign({}, m, { t: t(m.t) }));
      st.bookmarks = (st.bookmarks || []).map(b => Object.assign({}, b, { t: t(b.t) }));
      st.spans = (st.spans || []).map(x => Object.assign({}, x, { from: t(x.from), to: t(x.to) }));
      if (st.runsOver) st.runsOver = Object.assign({}, st.runsOver, { from: t(st.runsOver.from), to: t(st.runsOver.to) });   // still the span
    }
    return st;
  },
  // how far the view's times move from A to the run asked (runsTo): a slice's start between a slice and a whole one, else 0
  runsShift() {
    const to = this.runsTo !== undefined ? this.runsTo : 0;
    if (to === this.runsA()) return 0;
    const oa = this.runOrigin(this.runsA()), ob = this.runOrigin(to || 0);
    return (oa == null) !== (ob == null) ? (oa || 0) - (ob || 0) : 0;
  },
  // where a slice's time 0 is in the time of its dump (ps); null: a whole run, the dump of now (sva runs.rs origin)
  // A's as it was when it became A (runsAOf): the run removed since (Delete, a shell) is still the waves shown (B-62)
  runOrigin(id) { if (id && id === this.runsA() && this.runsAOf) return this.runsAOf.origin;
    const r = id && (this.runsL || []).find(x => x.id === id); return r && r.slice && isFinite(r.slice.from) ? +r.slice.from : null; },
  // the runs' part of the view, kept over a dump read again (⟳, a run shown): the panel, the window, the run compared and
  // how, A (a read again of the dump: now), the snapshot, the list
  runsOf() {
    const to = this.runsTo !== undefined ? this.runsTo : 0;
    // a compare with a file of the host's Compare… (no run): its name, and its path when the host gave one (compared again)
    const res = this.cmp && this.runCur == null ? this.cmp.result : null, file = res ? { name: this.cmp.name || res.name || 'B',
      path: res.src && typeof res.src.path === 'string' ? res.src.path : null } : this.cmpPick && this.cmpPick.path ? { name: this.cmpPick.name,
      path: this.cmpPick.path } : null, filePick = !res && !!file;   // (a file picked, not compared yet: picked again over the next waves)
    if (!this.runsP && this.runCur == null && this.runPickB == null && !this.runsWin && !this.runsA() && !to && !file && !this.runsGoAfter) return null;
    // the window and its end in the time of the waves asked (a slice's from 0), as runsKeep moved the spans
    const d = this.runsShift(), w = this.runsWin && d ? Object.assign({}, this.runsWin, { from: this.runsWin.from + d, to: this.runsWin.to + d })
      : this.runsWin;
    const go = !!this.runsGoAfter; this.runsGoAfter = false;
    return { open: !!this.runsP, win: w, cur: this.runCur, show: this.cmp ? this.cmpRun : null, shown: to, was: this.runsA(), go, pickB: this.runsB(), filePick,
      wasName: this.runName(this.runsA()),
      aOf: to ? { origin: this.runOrigin(to), name: this.runName(to) } : null,   // A's slice origin and name, kept while it is A
      to: this.t0 + this.span + d, focus: !!this.runsP && this.runsP.el.contains(document.activeElement), file,
      deltas: this.runsP ? [...this.runsP.deltas] : null,   // Δ all's numbers on the rows (still of the window and A they say)
      // the Open mode: the row the keys went on to while a run was read (its open still waits for them to rest), when it is
      // not the run asked: lit again over the new waves, opened when the keys rest. A row lit another way (↔, a keep) is not
      lit: this.runsP && this.runsMode === 'open' && this.runsP.pend != null && this.runsP.pend !== to ? this.runsP.pend : null,
      snap: this.runsSnap || null, list: this.runsL || null, now: this.runsNow || null, dir: this.runsDir, dirOf: this.runsDirOf || null,
      others: this.runsOthers };
  },
  async runsAgain(o) {
    if (!o || !this.runsHost()) return this;
    Object.assign(this, { runsWin: o.win || null, runsShown: o.shown || 0, runsSnap: o.snap, runsL: o.list, runsNow: o.now, runsDir: o.dir,
      runsOthers: o.others, runsAOf: o.shown ? o.aOf || null : null, runsDirOf: o.dirOf || null });
    if (o.open) this.runsPanel(true, o.focus);   // the keys where they were: the list, or the waves (]w ]w … walks on)
    if (o.lit != null && this.runsP) this.runsP.want = o.lit;
    if (o.deltas && this.runsP) { this.runsP.deltas = new Map(o.deltas); this.runsP.render(); }
    // what openDump's toast adds (runsNote): A now again, or a run's rows and end
    if (!o.shown && o.was) { this.runsNote = `the dump of now again (${o.wasName || this.runName(o.was)} was shown)`;
      if (this.runsP) this.runsP.status(this.runsNote); }
    else if (o.shown) this.runsSaid(o);
    // B stays picked (B made A: none); compared again only when Compare asked for it (it opened this A), else Compare does it
    const b = o.pickB != null ? o.pickB : o.cur, pick = b === this.runsA() ? null : b;
    if (o.file) this.runsFileAgain(o.file, o.go);
    if (o.go) { if (pick != null) await this.runCompare(pick, true, o.show); else if (this.cmpPick) await this.compareGo(); }
    else if (pick != null) { this.runPickB = pick; this.cmpShow(); if (this.runsP) { this.runsP.render();
      this.runsP.status(`B ${this.runName(pick)} picked, not compared with this A · Compare (c, g=)`); } }
    else if (b != null && this.runsP) this.runsP.status(`${this.runName(b)} is A now: no B (click a run, then Compare)`);
    return this;
  },
  // A moved while a file of Compare… was compared: that file picked as B again (the host has its path; Compare compares it with
  // the new A), else said that it went
  runsFileAgain(f, quiet) {
    const say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); };
    if (!f.path || !this.runsHost() || !this.runsHost().compareFile) { say(`the compare with ${f.name} dropped: A moved (Compare… again)`); return; }
    this.cmpPick = { name: f.name, path: f.path }; this.cmpShow();
    say(`B ${f.name} picked, not compared with this A · Compare (g=)`);
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
  runGone(id) { if (this.runPickA === id) this.runPickA = null; if (this.runPickB === id) this.runPickB = null;
    if (this.runCur === id) this.compare(null); else this.cmpShow(); },
  // B: the run picked (not compared yet), else the one compared
  runsB() { return this.runPickB != null ? this.runPickB : this.runCur; },
  // a run picked as B / as A: its letter lit, nothing read or compared (Compare does it); A's own waves: no pick
  runsPickB(id, quiet) {
    const say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); };
    if (this.runsMode === 'open') this.runsModeSet('compare', true);   // a B asked (]r [r): the panel compares again
    const a = this.runPickA != null ? this.runPickA : this.runsA();
    if (id === a) { say(id ? `#${id} is A: B is another run (or now)` : 'now is A: B is a run'); return this; }
    this.runPickB = id === this.runCur ? null : id; this.cmpShow(); if (this.runsP) this.runsP.render();
    say(`B ${this.runName(id)} picked · Compare (c, g=) compares it with A ${this.runName(a)} over the window in sight`); return this;
  },
  runsPickA(id, quiet) {
    const say = s => { if (!quiet) this.toast(s); if (this.runsP) this.runsP.status(s); };
    this.runPickA = id === this.runsA() ? null : id;
    if (this.runPickB === id) this.runPickB = null;
    this.cmpShow(); if (this.runsP) this.runsP.render();
    say(this.runPickA == null ? `A ${this.runName(id)}: the waves shown` : `A ${this.runName(id)} picked · Compare (c, g=) opens its waves (the view ` +
      `kept) and compares${this.runsB() != null ? ` B ${this.runName(this.runsB())}` : ''} with it over the window in sight`); return this;
  },
  // Compare with the runs: A opened first when another one is picked (its waves read, the view kept; the compare goes on
  // over the new waves: runsAgain), then B compared with A over the window in sight
  async runsGo() {
    const a = this.runPickA, b = this.runsB();
    if (a != null && a !== this.runsA()) { this.runsGoAfter = true; this.runPickA = null; await this.runsShow(a, true); return null; }
    this.runPickA = null;
    if (b == null) { const s = 'Compare: pick B first — a run (or now) in the Runs panel (gu), or Compare… a dump (gC)';
      this.toast(s); if (this.runsP) this.runsP.status(s); this.cmpShow(); return null; }
    return this.runCompare(b);
  },
});
// what a compare of A with B says: equal, or how many differ and the first; the rows B has not; B's values not loaded and why
function runSaid(na, nb, r, res, w, f, can) {
  const c = res.case, miss = (res.missing || []).length, over = c ? `over the case ${c.name} (B's at ${f(c.from)}` +
    `${c.shorter != null ? `; over the shorter, ${f(c.shorter)}` : ''})` : `over ${f(w.from)} … ${f(w.to)}` +
    // a slice and a whole one (the dump, a whole run): B read at A's moment of the dump
    (res.shift ? ` (B's ${f(w.from + res.shift)} … ${f(w.to + res.shift)}: a slice at its place)` : '');
  const head = r.differ ? `${na} ≠ ${nb}: ${r.differ} of ${r.compared} signals differ ${over}${r.first == null ? '' : `, the first at ${f(r.first)}`}` :
    `${na} = ${nb}: equal ${over} (${r.compared} signals)`;
  return head + (miss ? ` · ${miss} row${miss === 1 ? '' : 's'} B has not` : '') + ((res.notes || []).length ? ` · ${res.notes.join('; ')}` : '') +
    (r.differ && !can ? ` · B's values not loaded${res.cutError ? ': ' + res.cutError : ''} (bands only)` : '');
}
PLUGINS.push(v => { v.addKey(']r', () => v.runStep(1)).addKey('[r', () => v.runStep(-1));
  v.addKey(']w', () => v.runStep(1, 'a')).addKey('[w', () => v.runStep(-1, 'a')); });

/* ---------------- the panel ---------------- */
// One per viewer, over it, as the Modules panel (its look, its header moves it, its corner sizes it). Rows: the dump of now
// first, then a run each, newest first. A row's first line: the two roles, A (the waves shown) and B (compared with A), lit
// on the row that has it and buttons on each; #id, its name (muted when it is only the dump's name), its tags, each in a
// colour of its own; after a compare or Δ all, how many signals differ from A in the window and the first difference; its
// buttons (a slice: ↔ its span). Its second line: the comment first, in the text's colour (it tells the runs apart), then
// what the run is, muted — a slice's times, when kept, its size, its cases, its dump. The last line of the panel: the
// directory of the runs (selectable), Copy, and ★: it is made the permanent one.
// Keys: ↑ ↓ Home End go through the rows and pick them as B (Open mode: open the row they rest on), Enter picks the row as B
// (Open: opens it), w picks it as A, c compares (A opened when picked, then B with it over the window in sight), o: the mode
// (Compare / Open), s: a slice's span on the waves, x: no B (the waves only), e edits, Delete removes (the host asks), k keeps
// this dump, a Δ all, Esc closes (the form: cancels it).
const RUN_H = 40;
class Runs {
  constructor(v) {
    this.v = v; this.fi = 0; this.ac = new AbortController(); this.deltas = new Map(); this.edit = null; this.settle = null;
    const el = this.el = document.createElement('div'); el.className = 'wv-mods wv-runs'; el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'runs kept');
    el.innerHTML = ('<div class="mh"><b>Runs kept</b><span class="mt"></span><button type="button" data-a="x" aria-label="close" ' +
      'title="Close (Esc)">✕</button></div>' +
      '<div class="mf"><span class="rmode" role="group" aria-label="what a row chosen does">' +
      '<button type="button" data-a="mcmp" title="Compare: a row chosen is B, w on a row A — picked; Compare (c) compares them over the window ' +
      '(o: the other mode)">Compare</button>' +
      '<button type="button" data-a="mopen" title="Open: a row chosen opens its waves here, one run after another — no B, nothing compared ' +
      '(o: the other mode)">Open</button></span>' +
      '<button type="button" data-a="keep" title="Keep the dump of now as a run: a name, tags, a comment (k)">Keep this dump…</button>' +
      '<label class="rc" title="The window a run is compared over: the waves in sight, or one of your spans (only that time of the run is read)">' +
      'over <select class="rw" aria-label="the window compared"></select></label>' +
      '<button type="button" class="rc" data-a="all" title="How many signals of each run differ from A in the window (a)">Δ all</button>' +
      '<button type="button" class="rc rgo" data-a="go" title="Compare A with B over the window as it is now (c, g=): A opened first when ' +
      'another is picked; zoomed or panned since: again">Compare</button>' +
      '<button type="button" class="rc" data-a="nob" title="No B: the waves only, nothing compared (x); ]w [w then walk the runs">no B</button></div>' +
      '<form class="rf" hidden><input type="text" class="rfn" spellcheck="false" placeholder="name" aria-label="the run\'s name">' +
      '<input type="text" class="rft" spellcheck="false" placeholder="tags, a comma between them" aria-label="tags">' +
      '<textarea class="rfc" rows="2" placeholder="comment" aria-label="comment"></textarea>' +
      '<span class="rfb"><button type="submit" class="rfo">Keep</button><button type="button" data-a="cancel">Cancel</button></span></form>' +
      '<div class="ms"></div><div class="mtr rl" role="listbox" aria-label="runs kept" tabindex="0"><div class="mrows"></div></div>' +
      '<div class="rdir" hidden><span class="rp"></span><button type="button" data-a="cpd" title="Copy the path of the runs\' directory">Copy</button>' +
      '<button type="button" class="rstar" data-a="star" aria-pressed="false" aria-label="the permanent directory of the runs">☆</button></div>');
    v.root.append(el);
    this.rowsEl = el.querySelector('.mrows'); this.list = el.querySelector('.rl'); this.stEl = el.querySelector('.ms'); this.form = el.querySelector('.rf');
    this.win = el.querySelector('.rw'); this.dirEl = el.querySelector('.rdir'); this.said = ''; this.want = this.pend = null;
    panelPlace(this, 'runs');
    this.events(); this.windows(); this.mode(true); this.load();
  }
  close(quiet) { panelKeep(this, 'runs'); clearTimeout(this.settle); this.ac.abort(); this.el.remove(); if (this.v.runsP === this) this.v.runsP = null;
    if (!quiet) this.v.refocus(); }
  focusRow() { if (this.form.hidden) this.list.focus(); else this.form.querySelector('.rfn').focus(); }
  // the status line; in the Open mode it starts with the mode's name (a row chosen does another thing there)
  status(s, ofMode = false) { this.said = s || ''; this.saidMode = ofMode; const open = this.v.runsMode === 'open';
    this.stEl.textContent = open ? `Open · ${this.said || 'a row chosen opens its waves here, nothing compared (o: Compare)'}` : this.said; }
  // the mode shown: the switch, the compare's tools and B's letters away in the Open mode, the status line (quiet: its text kept)
  mode(quiet, dropped) {
    const open = this.v.runsMode === 'open';
    clearTimeout(this.settle); this.pend = null; this.el.classList.toggle('open', open);
    this.el.querySelector('[data-a=mcmp]').setAttribute('aria-pressed', String(!open));
    this.el.querySelector('[data-a=mopen]').setAttribute('aria-pressed', String(open));
    if (this.v.runsL) this.render();
    // quiet: what the line said stays, but a word about the mode of before
    if (quiet && !this.saidMode) this.status(this.said);
    else this.status(open ? `a row chosen opens its waves here, nothing compared${dropped ? ' (B dropped)' : ''} · o: Compare` :
      quiet ? '' : 'Compare: a row chosen is B (w: A), picked; c compares them over the window (o: Open)', true);
  }
  // the rows: the dump of now (id 0), then the runs, newest first
  rows() { const n = this.v.runsNow || {}; return [Object.assign({}, n, { id: 0, now: true, name: 'now', dump: n.name || '' }), ...(this.v.runsL || [])]; }
  rowOf(id) { return Math.max(0, this.rows().findIndex(r => r.id === id)); }
  async load(again = true) {
    try { await this.v.runsList(again); } catch (e) { this.status('runs: ' + e.message); return; }
    // the row waited for: the one handed over (want), else the one the keys rest on (the list read again meanwhile)
    const v = this.v, o = v.runsOthers, mt = this.el.querySelector('.mt'), want = this.want != null ? this.want : this.pend;
    mt.textContent = o ? `${o} of other dumps` : '';
    mt.title = o ? `${o} run${o === 1 ? '' : 's'} of other dumps in this directory (sva runs list --all)` : '';
    this.dir();
    // a row the keys went on to while a run was read (Open): lit again, opened when they rest; else B's row, else A's
    const on = want != null && this.rows().some(r => r.id === want); this.want = null; clearTimeout(this.settle); this.pend = null;
    const cur = v.runCur; this.fi = this.rowOf(on ? want : cur != null ? cur : v.runsA());
    this.render();
    if (on) this.pick(this.fi, true, true);
    if (!v.runsL.length) this.status('no run kept yet: Keep this dump… (the dump of now, as an FST in the runs\' directory)');
  }
  // the directory of the runs: its path (selectable text), where it comes from in its tooltip, ★ lit when the setting names it
  dir() {
    const v = this.v, d = v.runsDir || '', o = v.runsDirOf, h = v.runsHost(), p = this.dirEl.querySelector('.rp'), st = this.dirEl.querySelector('.rstar');
    const scope = o && o.scope ? ` in the ${o.scope === 'user' ? 'user' : 'workspace'}'s settings` : '';
    this.dirEl.hidden = !d; p.textContent = d;
    p.title = `the directory of the runs: ${d}\n` + (!o ? '' : o.set ?
      `from the setting wavelens.runsDir (${o.set})${scope}` :
      'the default: .wavelens-runs beside the dump (the setting wavelens.runsDir is empty)');
    const lit = !!(o && o.set); st.hidden = !(h && h.dir && o);
    st.textContent = lit ? '★' : '☆'; st.setAttribute('aria-pressed', String(lit)); st.classList.toggle('on', lit);
    st.title = lit ? `The permanent directory: the setting wavelens.runsDir names it${scope}. A click: the setting cleared — ` +
      '.wavelens-runs beside each dump again (the runs kept here stay here)' : 'Make this directory the permanent one: the setting wavelens.runsDir ' +
      'written (the workspace\'s settings when the dump is in a workspace folder, else yours), the runs of the dumps opened later kept here too';
  }
  // the window choices: the waves in sight, then your spans as they are now (a span chosen and gone: the waves in sight)
  windows() {
    const v = this.v, f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0);
    const i = v.runsWin ? v.spans.findIndex(x => sameSpan(x, v.runsWin)) : -1;
    if (v.runsWin && i < 0) { const w = v.runsWin; v.runsWin = null; this.status(`the span ${w.label || ''} is gone: over the waves in sight`); }
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
  // a run's Δ against A on its row (none in the Open mode: nothing is compared there)
  deltaHtml(r, f) {
    const v = this.v, d = this.deltas.get(r.id);
    if (!d || r.id === v.runsA() || v.runsMode === 'open') return '';
    if (d.error) return `<span class="rd bad" title="${esc(d.error)}">${esc(d.error)}</span>`;
    const old = this.stale(d), over = `${esc(f(d.from))} … ${esc(f(d.to))}`, cmpOld = old && r.id === v.runCur ? ' (the compare on the waves)' : '';
    return `<span class="rd${d.differ ? ' bad' : ''}${old ? ' old' : ''}" title="against A ${esc(v.runName(d.a || 0))} over ${over}${cmpOld}` +
      `${old ? ' (not the window or the A of now: ⟳ or Δ all again)' : ''}">` +
      `${d.outside ? 'not in this window' : d.differ ? `≠ ${d.differ} of ${d.compared}${d.first == null ? '' : ` · ${esc(f(d.first))}`}` : '= equal'}` +
      `${old ? ` (${over})` : ''}</span>`;
  }
  // the roles of a row: A and B, lit where they are; the Open mode: A only (the run shown), a click opens the row
  rolesHtml(r) {
    const v = this.v, open = v.runsMode === 'open', pa = !open && v.runPickA != null, a = r.id === (pa ? v.runPickA : v.runsA());
    const b = !open && r.id === v.runsB(), pb = b && v.runPickB != null;   // picked, not compared yet: the letter lit, dashed
    return `<span class="rab"><button type="button" data-a="ra" class="rA${a ? ' on' : ''}${a && pa ? ' pk' : ''}" aria-pressed="${a}" ` +
      `title="${a && pa ? 'A picked: Compare (c) opens its waves here and compares' : a ? 'A: the waves shown here' :
        open ? 'Open it: its waves shown here, the view kept (Enter, w)' : 'Pick it as A: Compare (c) opens its waves here, the view kept (w)'}">A</button>` +
      (open ? '' : `<button type="button" data-a="rb" class="rB${b ? ' on' : ''}${pb ? ' pk' : ''}" aria-pressed="${b}" ` +
      `title="${pb ? 'B picked: Compare (c) compares it with A (click: no B)' : b ? 'B: compared with A (click: no B)' :
        'Pick it as B: Compare (c) compares it with A over the window (Enter)'}">B</button>`) + '</span>';
  }
  // what a run is, the muted part of its second line: a slice's times, when kept, its size, its cases, its dump when another
  // than this one's (now: the dump on the disk)
  metaOf(r, f) {
    const hm = s => (s || '').slice(0, 16).replace('T', ' '), me = this.v.runsNow && this.v.runsNow.name;
    const mb = n => (n >= 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} kB`);
    const when = r.now ? `${r.mtime ? new Date(r.mtime).toISOString().slice(0, 16).replace('T', ' ') + ' on the disk' : 'the dump on the disk'}` :
      `kept ${hm(r.kept)}${r.source_mtime && Math.abs(Date.parse(r.source_mtime) - Date.parse(r.kept)) > 60000 ?
        ` of a dump of ${hm(r.source_mtime).slice(11)}` : ''}`;
    const size = r.now || r.slice ? r.bytes : r.source_bytes, sl = this.sliceOf(r) ? `slice ${f(r.slice.from)} … ${f(r.slice.to)}, from 0` : '';
    return [r.now ? r.dump : '', sl, when, size ? mb(size) : '', r.cases && r.cases.length ? `${r.cases.length} case${r.cases.length === 1 ? '' : 's'}` : '',
      !r.now && r.dump && r.dump !== me ? r.dump : ''].filter(Boolean).join(' · ');
  }
  sliceOf(r) { return !!r && !!r.slice && isFinite(r.slice.from) && isFinite(r.slice.to); }
  // a run's name is only its dump's (what a keep without a name gives; a slice: "DUMP FROM–TO"): it does not tell the runs apart
  plainName(r) { return !r.name || r.name === r.dump || (!!r.slice && !!r.dump && r.name.startsWith(r.dump + ' ')); }
  rowHtml(r, i, f) {
    const tags = (r.tags || []).map(t => `<span class="rtag" style="--h:${tagHue(t)}" title="tag: ${esc(t)}">${esc(t)}</span>`).join('');
    const comment = r.comment ? r.comment.trim().split('\n')[0] : '', sl = this.sliceOf(r);
    const title = r.now ? `the dump of now: ${r.dump}` : `#${r.id} ${r.name || ''}${(r.tags || []).length ? ` [${r.tags.join(', ')}]` : ''}\n` +
      `${r.dump || ''} kept ${(r.kept || '').replace('T', ' ').replace('Z', ' UTC')}${r.comment ? '\n' + r.comment : ''}`;
    return `<div class="mn rn${r.now ? ' rnow' : ''}${i === this.fi ? ' pv' : ''}" role="option" data-i="${i}" style="top:${i * RUN_H}px" ` +
      `title="${esc(title)}"><span class="r1">${this.rolesHtml(r)}<b>${r.now ? 'now' : '#' + esc(String(r.id))}</b> ` +
      `<span class="nm${!r.now && this.plainName(r) ? ' dn' : ''}">${r.now ? '' : esc(r.name || '')}</span>` +
      `<span class="rtags">${tags}</span>${this.deltaHtml(r, f)}` +
      (sl ? '<button type="button" data-a="sp" aria-label="its span on the waves shown" ' +
        `title="Its span on the waves shown: the window and the range on ${esc(f(r.slice.from))} … ` +
        `${esc(f(r.slice.to))} of the dump, in A's time (s) — Slice ▸ then takes the same piece of these waves">↔</button>` : '') + (r.now ? '' :
        '<button type="button" data-a="ed" title="Name, tags, comment (e)">✎</button>' +
        '<button type="button" data-a="rm" title="Remove the run and its file (Delete)">✕</button>') + '</span>' +
      `<span class="r2">${comment ? `<span class="rcm">${esc(comment)}</span>` : ''}<span class="rmt">${esc(this.metaOf(r, f))}</span></span></div>`;
  }
  render() {
    const v = this.v, rows = this.rows(), f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0);
    this.fi = Math.max(0, Math.min(this.fi, rows.length - 1));
    this.rowsEl.style.height = rows.length * RUN_H + 'px';
    this.rowsEl.innerHTML = rows.map((r, i) => this.rowHtml(r, i, f)).join('');
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
    // (in the dump's time: a slice shown as A has its times from 0, B-65)
    const d = run ? 0 : this.v.runOrigin(this.v.runsA()) || 0;
    const cases = this.v.spans.filter(s => s.label && caseName(s.label)).map(s => ({ label: s.label, from: s.from + d, to: s.to + d }));
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
  // a row chosen: picked as B (a click, Enter, ↑ ↓ Home End PgUp PgDn: nothing compared, Compare does it); the row of A only
  // focused. The Open mode: its waves opened here (when the keys rest: a dump is read), the lit row then the run shown
  pick(i, act = true, settle = false) {
    const v = this.v, rows = this.rows(), open = v.runsMode === 'open';
    this.fi = Math.max(0, Math.min(i, rows.length - 1)); this.render();
    clearTimeout(this.settle); this.pend = null;   // pend: the row whose compare / open waits for the keys to rest
    const id = rows[this.fi].id;
    if (!act) return;
    if (!open) { if (id !== (v.runPickA != null ? v.runPickA : v.runsA())) v.runsPickB(id, true);
      else if (!settle) this.status(`${v.runName(id)} is A: B is another row (c compares)`); return; }
    if (id === v.runsA()) {
      if (!settle) this.status(`${v.runName(id)} is shown: these waves`);
      // Open: the keys back on A while another run is read: A's row waits, opened again over the waves that come
      if (open && v.runsOpening != null && v.runsOpening !== id) this.pend = id;
      return; }
    const go = () => { this.pend = null; return v.runsShow(id, true); };
    if (settle) { this.pend = id; this.settle = setTimeout(go, RUN_OPEN_SETTLE); } else go();
  }
  // no B: the compare dropped, the waves only
  noB() { clearTimeout(this.settle); this.v.runsDrop(); this.v.runPickB = null; if (this.v.runCur != null) this.v.compare(null); else this.v.cmpShow();
    this.render(); this.status('no B: the waves only (]w [w walk the runs)'); }
  // what the Open mode has not got (Δ all, ⟳, no B: the compare's)
  onlyCompare(what) { if (this.v.runsMode !== 'open') return false; this.status(`${what} is the Compare mode's (o)`); return true; }
  events() {
    const v = this.v, el = this.el, sig = { signal: this.ac.signal };
    el.addEventListener('click', e => {
      const b = e.target.closest('button[data-a]'), row = e.target.closest('.rn'), run = row && this.rows()[+row.dataset.i];
      if (b) {
        const a = b.dataset.a;
        if (a === 'x') this.close();
        else if (a === 'keep') this.openForm(null);
        else if (a === 'cancel') this.closeForm();
        else if (a === 'mcmp' || a === 'mopen') { v.runsModeSet(a === 'mopen' ? 'open' : 'compare'); this.focusRow(); }
        else if (a === 'cpd') v.copyText(v.runsDir || '');
        else if (a === 'star') v.runsDirKeep(b.getAttribute('aria-pressed') !== 'true');
        else if (a === 'sp' && run) { this.fi = +row.dataset.i; this.render(); v.runsSpan(run.id, true); }
        else if (a === 'all') this.all();
        else if (a === 'nob') this.noB();
        else if (a === 'go') v.compareGo();
        else if (a === 'ed' && run) this.openForm(run);
        else if (a === 'rm' && run) this.remove(run);
        else if (a === 'ra' && run) { this.fi = +row.dataset.i; if (v.runsMode === 'open') v.runsShow(run.id); else v.runsPickA(run.id, true); }
        else if (a === 'rb' && run) { if (v.runsB() === run.id) this.noB(); else this.pick(+row.dataset.i); }
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
      if (e.ctrlKey || e.metaKey || e.altKey) return;   // the browser's, the viewer's
      if ((e.key === 'Enter' || e.key === ' ') && e.target.closest('button')) { e.stopPropagation(); return; }   // the button's own click
      const rows = this.rows(), run = rows[this.fi], k = e.key;
      const go = { ArrowDown: this.fi + 1, ArrowUp: this.fi - 1, Home: 0, End: rows.length - 1, PageDown: this.fi + 5, PageUp: this.fi - 5 }[k];
      if (go !== undefined) this.pick(go, true, true);
      else if (k === 'Enter' && run) this.pick(this.fi);
      else if (k === 'w' && run) { if (v.runsMode === 'open') v.runsShow(run.id); else v.runsPickA(run.id, true); }
      else if (k === 'c' && this.onlyCompare('Compare')) { /* said */ }
      else if (k === 'c') v.compareGo();
      else if (k === 'o') v.runsModeSet(v.runsMode === 'open' ? 'compare' : 'open');
      else if (k === 's' && run) v.runsSpan(run.id, true);
      else if ((k === 'x' || k === 'a') && this.onlyCompare(k === 'x' ? 'no B' : 'Δ all')) { /* said */ }
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
