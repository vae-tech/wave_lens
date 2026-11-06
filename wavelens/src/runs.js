/* wavelens/src/runs.js — the runs kept of a dump (gu, Runs… in the bar): the dumps of runs before, kept by hand with a
   name, tags and a comment (VS Code: sva runs keep, into .wavelens-runs beside the dump, as FSTs), and these waves
   compared with one of them over a window — the waves in sight or one of your spans: only that window of the run is read
   (sva diff, then the values of the signals that differ there), so a large run costs the window, not the dump. Keep this
   dump… adds the dump of now; a click on a run (Enter, ↑ ↓ in the list, ]r [r anywhere) compares with it, the compare's
   A B A+B and ]d [d as Compare… has them; Δ all: how many signals of each run differ in the window. The page asks its host
   (window.WAVELENS_RUNS: list, keep, set, rm, diff, compare; the VS Code extension's media/host.js gives it); without
   one (a page in a browser) there are none. */

/* ---------------- the viewer's side ---------------- */
const RUN_SETTLE = 250;   // ms: the list's keys move the row, the compare goes when they stop (Enter at once)
const sameSpan = (s, w) => !!s && !!w && s.from === w.from && s.to === w.to && (s.label || '') === (w.label || '');
Object.assign(WaveView.prototype, {
  // who keeps the runs: the page's host (VS Code), null in a browser
  runsHost() { return this.opts.runsHost || (typeof window !== 'undefined' && window.WAVELENS_RUNS) || null; },
  // the Runs panel: open, closed (false), or as it is toggled
  runsPanel(on = !this.runsP) {
    if (!on) { if (this.runsP) this.runsP.close(); return this; }
    if (!this.runsHost()) { this.toast('the runs kept are VS Code\'s (WaveLens: the Runs panel there), or sva runs keep / diff in a shell'); return this; }
    if (!this.M.timed) { this.toast('runs: these waves are clock-sampled (one cell per cycle): a run is compared on exact waves'); return this; }
    if (!this.runsP) this.runsP = new Runs(this);
    this.runsP.focusRow();
    return this;
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
  // the runs of this dump as the host lists them (newest first), read again when asked (the panel, ]r [r, runs.json changed)
  async runsList(again) {
    const h = this.runsHost(); if (!h) return [];
    if (!this.runsL || again) {
      const m = await h.list(); if (m.error) throw new Error(m.error);
      this.runsL = (m.runs || []).slice().reverse(); this.runsDir = m.dir || ''; this.runsOthers = m.others || 0;
    }
    return this.runsL;
  },
  // these waves compared with a run (its id) over the window: the view shown (A, B, A+B) kept; a later ask wins (the host
  // stops the one before)
  async runCompare(id, quiet) {
    const h = this.runsHost(); if (!h) { this.toast('no runs kept here'); return null; }
    const runs = await this.runsList(), run = runs.find(r => r.id === id);
    if (!run) { this.toast(`no run #${id}`); return null; }
    const w = this.runsWindow(), req = this.runReq = (this.runReq || 0) + 1, show = this.cmp ? this.cmpRun : 'a';
    const f = t => this.fmt(t, (this.M.t1 - this.M.t0) / 1000, this.M.t1 - this.M.t0);
    if (!quiet) this.toast(`#${id} ${run.name}: comparing ${f(w.from)} … ${f(w.to)}…`);
    if (this.runsP) this.runsP.status(`comparing with #${id} ${run.name} over ${f(w.from)} … ${f(w.to)}…`);
    let m;
    try { m = await h.compare({ id, signals: this.runsSignals(), from: w.from, to: w.to }); } catch (e) { m = { error: e.message }; }
    if (req !== this.runReq) return null;   // another run asked meanwhile
    if (m.error || !m.result) { const e = m.error || 'no result'; this.toast(`#${id}: ${e}`); if (this.runsP) this.runsP.status(`#${id} ${run.name}: ${e}`);
      return null; }
    m.result.name = `#${id} ${run.name}`;
    const r = this.compareResult(m.result, quiet);
    if (!r) return null;
    this.runCur = id;   // the run compared: set once it is
    if (show !== 'a' && this.cmpCan()) await this.compareView(show, true);
    if (this.runsP) { this.runsP.got(id, w, r); this.runsP.status(runSaid(`#${id} ${run.name}`, r, m.result, w, f, this.cmpCan())); }
    return r;
  },
  // ]r [r: the next (older) / previous (newer) run of the list (read again: a run kept in a shell is there) over the window
  async runStep(dir) {
    if (!this.runsHost()) { this.toast(']r [r: the runs kept are VS Code\'s (the Runs panel)'); return this; }
    let runs; try { runs = await this.runsList(true); } catch (e) { this.toast('runs: ' + e.message); return this; }
    if (this.runsP) this.runsP.render();
    if (!runs.length) { this.toast('no run kept: Keep this dump… in the Runs panel (gu)'); return this; }
    const i = runs.findIndex(r => r.id === this.runCur), j = i < 0 ? (dir > 0 ? 0 : runs.length - 1) : (i + dir + runs.length) % runs.length;
    await this.runCompare(runs[j].id);
    return this;
  },
  // the runs' part of the view, kept over a dump read again (⟳): the panel, the window, the run compared
  runsOf() { return this.runsP || this.runCur != null || this.runsWin ? { open: !!this.runsP, win: this.runsWin, cur: this.runCur } : null; },
  async runsAgain(o) {
    if (!o || !this.runsHost()) return this;
    this.runsWin = o.win || null;
    if (o.open) this.runsPanel(true);
    if (o.cur != null) await this.runCompare(o.cur, true);   // the dump changed: compared with the run again, over the new waves
    return this;
  },
  // the run removed was the one compared: the compare goes with it
  runGone(id) {
    if (this.runCur !== id) return;
    this.runCur = null; if (this.cmp && /^#\d+ /.test(this.cmp.name || '')) this.compare(null);
  },
});
// what a compare with a run says: equal, or how many differ and the first; the rows the run has not; the run's values not loaded and why
function runSaid(who, r, res, w, f, can) {
  const miss = (res.missing || []).length, over = `over ${f(w.from)} … ${f(w.to)}`;
  const head = r.differ ? `${who}: ${r.differ} of ${r.compared} signals differ ${over}${r.first == null ? '' : `, the first at ${f(r.first)}`}` :
    `${who}: equal ${over} (${r.compared} signals)`;
  return head + (miss ? ` · ${miss} row${miss === 1 ? '' : 's'} the run has not` : '') +
    (r.differ && !can ? ` · the run's values not loaded${res.cutError ? ': ' + res.cutError : ''} (bands only)` : '');
}
PLUGINS.push(v => { v.addKey(']r', () => v.runStep(1)).addKey('[r', () => v.runStep(-1)); });

/* ---------------- the panel ---------------- */
// One per viewer, over it, as the Modules panel (its look, its header moves it, its corner sizes it). Rows: a run each,
// newest first: #id, its name, tags, when kept, its comment; after a compare or Δ all, how many signals differ in the
// window and the first difference. Keys: ↑ ↓ Home End go through the runs and compare, Enter compares, e edits, Delete
// removes (the host asks), k keeps this dump, a Δ all, Esc closes (the form: cancels it).
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
      '<button type="button" data-a="all" title="How many signals of each run differ in the window (a)">Δ all</button>' +
      '<button type="button" data-a="again" title="Compare with the run again over the window as it is now">⟳</button></div>' +
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
  async load(again = true) {
    try { await this.v.runsList(again); } catch (e) { this.status('runs: ' + e.message); return; }
    const o = this.v.runsOthers, mt = this.el.querySelector('.mt');
    mt.textContent = (this.v.runsDir || '') + (o ? ` · ${o} of other dumps` : '');
    mt.title = o ? `${o} run${o === 1 ? '' : 's'} of other dumps in this directory (sva runs list --all)` : '';
    const i = this.v.runsL.findIndex(r => r.id === this.v.runCur); if (i >= 0) this.fi = i;
    this.render();
    if (!this.v.runsL.length) this.status('no run kept yet: Keep this dump… (the dump of now, as an FST in the runs\' directory)');
  }
  // the window choices: the waves in sight, then your spans as they are now (a span chosen and gone: the waves in sight)
  windows() {
    const v = this.v, f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0);
    const i = v.runsWin ? v.spans.findIndex(x => sameSpan(x, v.runsWin)) : -1;
    if (v.runsWin && i < 0) v.runsWin = null;
    this.win.innerHTML = '<option value="view">the waves in sight</option>' + v.spans.map((s, k) =>
      `<option value="${k}">${esc(s.label || 'span')} (${esc(f(s.from))} … ${esc(f(s.to))})</option>`).join('');
    this.win.value = i < 0 ? 'view' : String(i);
  }
  // a compare's numbers for the run, of that window
  got(id, w, r) { if (r) this.deltas.set(id, { from: w.from, to: w.to, differ: r.differ, compared: r.compared, first: r.first }); this.render(); }
  // Δ numbers of another window than the one now: greyed, their window in their text
  stale(d) { const w = this.v.runsWindow(); return Math.abs(d.from - w.from) > 1e-6 || Math.abs(d.to - w.to) > 1e-6; }
  render() {
    const v = this.v, runs = v.runsL || [], f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0);
    this.fi = Math.max(0, Math.min(this.fi, runs.length - 1));
    this.rowsEl.style.height = runs.length * RUN_H + 'px';
    this.rowsEl.innerHTML = runs.map((r, i) => {
      const d = this.deltas.get(r.id), tags = (r.tags || []).map(t => `<span class="rtag">${esc(t)}</span>`).join('');
      const old = d && !d.error && this.stale(d), over = d && !d.error ? `${esc(f(d.from))} … ${esc(f(d.to))}` : '';
      const delta = !d ? '' : d.error ? `<span class="rd bad" title="${esc(d.error)}">${esc(d.error)}</span>` :
        `<span class="rd${d.differ ? ' bad' : ''}${old ? ' old' : ''}" title="over ${over}${old ? ' (not the window of now: ⟳ or Δ all again)' : ''}">` +
        `${d.outside ? 'not in this window' : d.differ ? `≠ ${d.differ} of ${d.compared}${d.first == null ? '' : ` · ${esc(f(d.first))}`}` : '= equal'}` +
        `${old ? ` (${over})` : ''}</span>`;
      return `<div class="mn rn${r.id === v.runCur ? ' on' : ''}${i === this.fi ? ' pv' : ''}" role="option" data-i="${i}" style="top:${i * RUN_H}px" ` +
        `title="${esc(`${r.dump || ''} kept ${(r.kept || '').replace('T', ' ').replace('Z', ' UTC')}${r.comment ? '\n' + r.comment : ''}`)}">` +
        `<span class="r1"><b>#${esc(String(r.id))}</b> <span class="nm">${esc(r.name || '')}</span><span class="rtags">${tags}</span>${delta}` +
        '<button type="button" data-a="ed" title="Name, tags, comment (e)">✎</button>' +
        '<button type="button" data-a="rm" title="Remove the run and its file (Delete)">✕</button></span>' +
        `<span class="r2">${esc((r.kept || '').slice(0, 16).replace('T', ' '))} · ${esc(r.dump || '')}` +
        `${r.comment ? ' · ' + esc(r.comment.split('\n')[0]) : ''}</span></div>`;
    }).join('');
    const cur = this.rowsEl.children[this.fi];
    if (cur) { const t = cur.offsetTop, h = this.list.clientHeight; if (t < this.list.scrollTop) this.list.scrollTop = t;
      else if (t + RUN_H > this.list.scrollTop + h) this.list.scrollTop = t + RUN_H - h; }
  }
  // the form: keep the dump of now (edit null), or a run's name, tags, comment
  openForm(run) {
    const v = this.v; this.edit = run || null; this.form.hidden = false;
    this.form.querySelector('.rfn').value = run ? run.name : (v.opts.title || v.M.title || '');
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
    let m; try { m = run ? await h.set(run.id, body) : await h.keep(body); } catch (e) { m = { error: e.message }; }
    if (m.error) { this.status((run ? 'not saved: ' : 'not kept: ') + m.error); return; }
    await this.load(); if (!run && m.run) { this.fi = Math.max(0, this.v.runsL.findIndex(r => r.id === m.run.id)); this.render(); }
    this.status(run ? `#${run.id} saved` : m.run ? `kept as #${m.run.id} ${m.run.name}` : 'kept');
  }
  async remove(run) {
    let m; try { m = await this.v.runsHost().rm(run.id); } catch (e) { m = { error: e.message }; }
    if (m.error) { this.status('not removed: ' + m.error); return; }
    if (m.cancelled) return;
    const cur = this.v.runCur === run.id; this.v.runGone(run.id);
    this.deltas.delete(run.id); await this.load(); this.status(`#${run.id} ${run.name} removed${cur ? ', the compare with it dropped' : ''}`);
  }
  // Δ all: sva runs diff over the window, each run's numbers on its row
  async all() {
    const v = this.v, w = v.runsWindow(), f = t => v.fmt(t, (v.M.t1 - v.M.t0) / 1000, v.M.t1 - v.M.t0);
    this.status(`each run against these waves over ${f(w.from)} … ${f(w.to)}…`);
    let m; try { m = await v.runsHost().diff({ signals: v.runsSignals(), from: w.from, to: w.to }); } catch (e) { m = { error: e.message }; }
    if (m.error) { this.status('Δ all: ' + m.error); return; }
    let n = 0;
    for (const x of m.runs || []) {
      if (x.error) { this.deltas.set(x.id, { error: x.error }); continue; }
      if (x.signals_differ || x.outside) n++;
      this.deltas.set(x.id, { from: x.from ?? w.from, to: x.to ?? w.to, differ: x.signals_differ || 0, compared: x.signals_compared || 0,
        first: x.first ? x.first.t : null, outside: !!x.outside });
    }
    this.render();
    this.status(`${n} of ${(m.runs || []).length} runs differ over ${f(w.from)} … ${f(w.to)}`);
  }
  // a row chosen: compared at once (a click, Enter) or when the keys stop (settle: ↑ ↓ Home End PgUp PgDn held down
  // compare once, the row they stop on)
  pick(i, compare = true, settle = false) {
    const runs = this.v.runsL || []; if (!runs.length) return;
    this.fi = Math.max(0, Math.min(i, runs.length - 1)); this.render();
    clearTimeout(this.settle);
    if (!compare) return;
    const id = runs[this.fi].id;
    if (settle) this.settle = setTimeout(() => this.v.runCompare(id, true), RUN_SETTLE); else this.v.runCompare(id, true);
  }
  events() {
    const v = this.v, el = this.el, sig = { signal: this.ac.signal };
    el.addEventListener('click', e => {
      const b = e.target.closest('button[data-a]'), row = e.target.closest('.rn'), run = row && (v.runsL || [])[+row.dataset.i];
      if (b) {
        const a = b.dataset.a;
        if (a === 'x') this.close();
        else if (a === 'keep') this.openForm(null);
        else if (a === 'cancel') this.closeForm();
        else if (a === 'all') this.all();
        else if (a === 'again') { if (v.runCur != null) v.runCompare(v.runCur, true); else this.status('click a run first: it is compared over the window'); }
        else if (a === 'ed' && run) this.openForm(run);
        else if (a === 'rm' && run) this.remove(run);
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
      const runs = v.runsL || [], run = runs[this.fi], k = e.key;
      const go = { ArrowDown: this.fi + 1, ArrowUp: this.fi - 1, Home: 0, End: runs.length - 1, PageDown: this.fi + 5, PageUp: this.fi - 5 }[k];
      if (go !== undefined) this.pick(go, true, true);
      else if (k === 'Enter' && run) this.pick(this.fi);
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
