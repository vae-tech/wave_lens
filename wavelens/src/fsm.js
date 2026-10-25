/* wavelens/src/fsm.js — the state machines (T): the signals of the waves with enum labels (an FST's tables, a types file,
   Sources…, a config's "enum") in the tree of the modules above them. A click goes to one; the layer keeps only them on
   the waves, or adds them to the view as the other layers leave it. */

/* ---------------- the FSMs and their layer ---------------- */
// The layer (state "fsm": {mode, signals: [paths]}; the command fsm): mode "only" — the waves keep these FSMs and the
// modules on the way to them; Hide stays, Only and the find's Mask are kept under it and come back when it goes. Mode
// "add" — the view as Hide, Only and the Mask make it, and these FSMs in it too (a hidden one, one Only or the Mask left
// out), with the modules on the way to them. In the saved state, Save page and undo.
const fsmTable = r => { const e = r.enum || ENUMS[r.full] || ENUMS[r.name]; return e && Object.keys(e).length ? e : null; };
const FSM_MODES = ['only', 'add'];
// a name as a state machine's (state, fsm, st_q, cs / ns, phase …): the panel lists these (all enums: the others too,
// a running disparity, a kind of packet; none named so: every one)
const FSM_NAME = /state|fsm|(?:^|_)(?:st|sm|ps|ns|cs|cur|nxt|next|phase|mode)(?:_|\d|$)|_(?:q|r|reg|ff)$/i;
Object.assign(WaveView.prototype, {
  // the FSMs in the model's order: the signals with enum labels (r.fsmField: a field of a struct: a packed vector's, a
  // struct scope's member); fields false: those left out
  fsms(fields = true) {
    if (!this.fsmL) {
      const G = this.M.groups, inStruct = r => !!r.field || r.anc.some(id => G[id] && (G[id].kind === 'struct' || G[id].kind === 'union'));
      this.fsmL = this.M.rows.filter(r => r.type === 'sig' && r.tr && !r.ug && fsmTable(r));
      for (const r of this.fsmL) r.fsmField = inStruct(r);
    }
    return fields ? this.fsmL : this.fsmL.filter(r => !r.fsmField);
  },
  fsmState() { return this.fsm ? { mode: this.fsm.mode, signals: [...this.fsm.signals] } : null; },
  // a test of a row: whether the layer keeps it (one of its FSMs, a group on the way to one)
  fsmTest() {
    const key = this.fsm ? this.fsm.signals.join('\n') : '';
    if (!this.fsmMemo || this.fsmMemo.key !== key) {
      const want = new Set(this.fsm ? this.fsm.signals : []), rows = new Set(), ids = new Set();
      for (const r of this.fsms()) if (want.has(r.full)) { rows.add(r); r.anc.forEach(id => ids.add(id)); }
      const test = r => rows.has(r) || (r.type === 'group' && !r.user && ids.has(r.id)), model = new Set(this.M.rows), G = this.M.groups;
      const above = r => !r.ug && !model.has(r) && !r.anc.some(id => G[id] && model.has(G[id]));   // a plugin's row above every module
      this.fsmMemo = { key, test, keep: r => test(r) || above(r) };
    }
    return this.fsmMemo.test;
  },
  // the rows the layer "only" keeps: its own, and as Only the rows of the plugins above every module (ƒ, buses, assertions)
  fsmKeep() { this.fsmTest(); return this.fsmMemo.keep; },
  // the layer: {mode?, signals?, open?} (signals: FSM paths, in the model's order; left out: the ones it has, none yet: every
  // FSM but the fields), null: off; no FSM left: off. open (unless false): the modules on the way to its FSMs opened
  setFsm(o) {
    if (o == null) this.fsm = null;
    else {
      const all = this.fsms(), want = o.signals != null ? new Set([].concat(o.signals).map(String)) : null;
      const sigs = want ? all.filter(r => want.has(r.full)).map(r => r.full) : this.fsm ? this.fsm.signals : all.filter(r => !r.fsmField).map(r => r.full);
      const mode = FSM_MODES.includes(o.mode) ? o.mode : this.fsm ? this.fsm.mode : 'only';
      this.fsm = sigs.length ? { mode, signals: sigs } : null;
      if (this.fsm && o.open !== false) { const want = new Set(sigs);
        this.fsmNote = this.findOpenOff();   // its next search would fold them again
        for (const r of all) if (want.has(r.full)) r.anc.forEach(id => this.collapsed.delete(id));
        this.foldTouched = true; }
    }
    this.fsmMemo = null; this.allRows(); this.onlyFix();
    if (this.q) this.find(this.q, false, null, false); else { this.renderNames(); this.draw(); }
    this.fsmShow(); return this;
  },
  // the bar's FSMs only: N ✕ / + N FSMs ✕ (a click: off); the panel
  fsmShow() {
    const x = this.root.querySelector('.bar button[data-act=fsmx]'), f = this.fsm;
    if (x) { x.hidden = !f; if (f) { const n = f.signals.length;
      x.textContent = f.mode === 'only' ? `FSMs only: ${n} ✕` : `+ ${n} FSM${n === 1 ? '' : 's'} ✕`; } }
    if (this.fsmP) this.fsmP.render();
  },
  // an FSM (its path or row) on the waves: shown when hidden (it and the modules above it), else joining the layer when the
  // view leaves it out (only: its set; else added to the view); opened, selected, in the middle
  goFsm(r) {
    if (typeof r === 'string') { const p = r; r = this.fsms().find(x => x.full === p); if (!r) { this.toast(`no state machine "${p}"`); return this; } }
    let why = '', un = false;
    for (const p of [...r.anc.map(id => this.M.groups[id] && this.M.groups[id].path), r.full]) if (p && this.hiddenRows.delete(p)) un = true;
    if (un) { this.rowsStale = true; this.saveRows(); this.allRows(); why = ' · shown again (it was hidden)'; }
    if (!this.shown(r)) {
      const mode = this.fsm ? this.fsm.mode : 'add';
      this.setFsm({ mode, signals: (this.fsm ? this.fsm.signals : []).concat(r.full) });
      why += mode === 'add' ? ' · added to the view (✕ in the bar takes the FSMs away)' : ' · one of the FSMs shown now';
    }
    why += this.findOpenOff() + (this.fsmNote || ''); this.fsmNote = '';
    r.anc.forEach(id => this.collapsed.delete(id));
    this.foldTouched = true; this.onlyFix(); this.renderNamesNow(); this.select(r); this.centerRow(r);
    this.toast(r.full + why);
    return this;
  },
  // the FSM panel: open, closed (false), or as it is toggled
  fsmPanel(on = !this.fsmP) {
    if (!on) { if (this.fsmP) this.fsmP.close(); return this; }
    if (!this.fsms().length) {
      this.toast('no state machines on these waves: none has enum labels (an FST\'s, x.types.json or .sv files in Sources…)'); return this; }
    if (!this.fsmP) this.fsmP = new Fsms(this);
    this.need(this.fsms());   // a large dump read as it is needed: the FSMs' changes (their states reached, the details)
    this.fsmP.focusRow();
    return this;
  },
  // the panel as it is ({q, fields, left, top}; null: closed), and again in a new viewer of the same waves (Sources…, ⟳)
  fsmPanelOf() { const p = this.fsmP, b = p && p.el.style; return p ? { q: p.q, fields: p.fields, all: p.all, left: b.left, top: b.top,
    width: b.width, height: b.height, det: p.det && p.det.full, tab: p.tab } : null; },
  fsmPanelAgain(o) {
    if (!o || !this.fsms().length) return this;
    const p = this.fsmP = new Fsms(this); panelPlace(p, 'fsms', o);
    p.q = p.qEl.value = o.q || ''; p.fields = p.el.querySelector('.ff').checked = !!o.fields; p.all = p.el.querySelector('.fa').checked = !!o.all;
    p.build(); p.render(true); const r = o.det && p.mine.find(x => x.full === o.det); p.detail(r || null, o.tab);
    return this;
  },
  // an FSM's states and changes on these waves (fsmStats), memoised per row: the panel's details and diagram, fsm_stats
  fsmStatsOf(r) {
    if (!this.fsmSt || this.fsmSt.M !== this.M) this.fsmSt = { M: this.M, map: new WeakMap() };
    let s = this.fsmSt.map.get(r); if (!s) this.fsmSt.map.set(r, (s = fsmStats(r, this.M.t1))); return s;
  },
  // the cursor to the next (dir 1) or previous (-1) time an FSM enters a state (what: {state: key or label}) or makes a
  // change ({from, to}); past the last: round to the first (said). The FSM shown and selected as goFsm does -> the time
  fsmGo(r, what, dir = 1) {
    if (typeof r === 'string') { const p = r; r = this.fsms().find(x => x.full === p); if (!r) { this.toast(`no state machine "${p}"`); return null; } }
    const st = this.fsmStatsOf(r), key = x => (x == null ? null : st.keyOf(String(x)));
    let times, what2;
    if (what && what.state != null) { const s = st.vals.get(key(what.state)); times = s ? s.entries : []; what2 = st.name(key(what.state)); }
    else if (what && what.from != null && what.to != null) { const x = st.trans.get(key(what.from) + '>' + key(what.to)); times = x ? x.times : [];
      what2 = `${st.name(key(what.from))} → ${st.name(key(what.to))}`; }
    else { this.toast('fsm_go: a state, or from and to'); return null; }
    if (!times.length) { this.toast(`${r.full}: never ${what2}`); return null; }
    const c = this.cursor, eps = timeEps(c);
    let i = what.first ? 0 : dir < 0 ? lastBefore(times.length, j => times[j], c - eps) : times.findIndex(t => t > c + eps), round = '';
    if (i < 0) { i = dir < 0 ? times.length - 1 : 0; round = dir < 0 ? ' (round to the last)' : ' (round to the first)'; }
    if (!this.shown(r) || r.anc.some(id => this.collapsed.has(id))) this.goFsm(r);
    this.select(r); this.setCursor(times[i]);
    this.toast(`${r.full}: ${what2} at ${this.when(times[i])}, ${i + 1} of ${times.length}${round}`);
    if (this.fsmP) this.fsmP.values(true);
    return times[i];
  },
});

/* ---------------- an FSM's states and changes ---------------- */
// From a row's transitions: each value it takes — a state of its table, or one that is not (x, z, a code without a
// label) — with the times it entered it and how long it held it in all; each change from one value to another with its
// times; the table's states it never takes. Values by their table key (decimal); a clock-sampled row's label as written.
function fsmStats(r, t1) {
  const e = fsmTable(r) || {}, by = new Map(Object.entries(e).map(([k, n]) => [n, k])), seq = [], vals = new Map(), trans = new Map();
  for (const o of r.tr) {
    let k;
    if (o.k === 'z') k = 'z';
    else if (o.k !== '=' && o.k !== '0' && o.k !== '1') k = 'x';
    // a clock-sampled row's value is its label (no bits of it): by the table first, a label "1" is the key of "1"
    else if (o.k === '=' && o.bits == null && o.raw == null && o.hex == null && by.has(String(o.v))) k = by.get(String(o.v));
    else { const b = bitsOf(o, r.width || 1); k = /[xz]/.test(b) ? by.get(String(o.v)) ?? (/x/.test(b) ? 'x' : 'z') : BigInt('0b' + b).toString(); }
    if (seq.length && seq[seq.length - 1][1] === k) continue;
    seq.push([o.t, k]);
  }
  seq.forEach(([t, k], i) => {
    let s = vals.get(k); if (!s) vals.set(k, (s = { key: k, label: e[k], entries: [], time: 0 }));
    s.entries.push(t); s.time += Math.max(0, (i + 1 < seq.length ? seq[i + 1][0] : t1) - t);
    if (!i) return;
    const id = seq[i - 1][1] + '>' + k; let x = trans.get(id); if (!x) trans.set(id, (x = { from: seq[i - 1][1], to: k, times: [] })); x.times.push(t);
  });
  const name = k => (k == null ? '?' : e[k] !== undefined ? e[k] : k === 'x' ? 'X' : k === 'z' ? 'Z' : `${k} (no label)`);
  return { table: e, vals, trans, seq, name,
    states: Object.keys(e).map(k => vals.get(k) || { key: k, label: e[k], entries: [], time: 0 }),   // the table's, in its order
    bad: [...vals.values()].filter(s => e[s.key] === undefined),   // x, z, a code it has no label for
    unseen: Object.keys(e).filter(k => !vals.has(k)),
    // a state by its key or its label (a command's "state": "DATA" or "2") -> its key
    keyOf: x => (hasKey(e, x) || vals.has(x) ? x : by.has(x) ? by.get(x) : /^x$/i.test(x) ? 'x' : /^z$/i.test(x) ? 'z' : x) };
}
/* ---------------- the panel ---------------- */
// One per viewer, over it, as the Modules panel (its look, its header moves it, its corner sizes it): the modules with an
// FSM in them or below them, each FSM under its module with its state at the cursor and how many of its states the waves
// reach (the ones FSM_NAME names; all enums: every signal with labels). A click on an FSM goes there (goFsm) and shows its
// details below the tree: its states (entries, time held, the first entry; never reached; values not in its table), its
// changes and a diagram of them; a click there takes the cursor to the next entry or change (shift: the previous). A click
// on a module goes there (goScope); ctrl+click / Space picks an FSM, shift+click a run, a box drawn over the tree picks the
// FSMs in it. Only FSMs / Add to view take the picked ones (none picked: every one the filter lists); the right button: a
// menu of an FSM or a module. Keys: ↑ ↓ Home End, ← → fold / open, Enter go, d details, Space pick, / the filter, Esc; in
// the details (a click there, Tab): ↑ ↓ their rows, Enter the next time (shift: the previous), ← → the tabs, Esc the tree.
const FSM_TABS = [['states', 'States'], ['changes', 'Changes'], ['graph', 'Diagram']];
class Fsms {
  constructor(v) {
    this.v = v; this.q = ''; this.fi = 0; this.anchor = null; this.key = ''; this.fields = false; this.all = false;
    this.pick = new Set(); this.det = null; this.tab = 'states';
    this.ac = new AbortController(); this.build();
    const el = this.el = document.createElement('div'); el.className = 'wv-mods wv-fsms'; el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'state machines');
    el.innerHTML = (`<div class="mh"><b>State machines</b><span class="mt">${esc(v.opts.title || v.M.title || '')}</span><button type="button" ` +
        'data-a="x" aria-label="close" title="Close (Esc)">✕</button></div><div class="mf"><input type="search" class="mq" spellcheck="false" ' +
        'autocomplete="off" placeholder="Filter state machines…" aria-label="filter state machines" title="Fuzzy, as the find, over the FSMs and ' +
        'their modules: Enter goes to the first, ↓ into the list"><label title="The fields of structs with enum labels too (a packed struct\'s ' +
        'state field)"><input type="checkbox" class="ff"> fields</label><label title="Every signal with enum labels, not only the ones named as ' +
        'a state machine (state, fsm, cs / ns, …_q)"><input type="checkbox" class="fa"> all enums</label></div><div class="ms"></div>' +
        '<div class="mtr" role="tree" aria-label="state machines" aria-multiselectable="true"><div class="mbox" hidden></div><div class="mrows"></div></div>' +
        '<div class="fd" hidden><div class="fdh"><b class="fdn"></b><span class="fdm"></span><span class="fdt" role="tablist">' +
        FSM_TABS.map(([t, n]) => `<button type="button" role="tab" data-t="${t}">${n}</button>`).join('') +
        '</span><button type="button" data-a="fdx" aria-label="close the details" title="Close the details (d)">✕</button></div>' +
        '<div class="fdb" tabindex="-1"></div></div>');
    v.root.append(el);
    this.tree = el.querySelector('.mtr'); this.rowsEl = el.querySelector('.mrows'); this.qEl = el.querySelector('.mq'); this.stEl = el.querySelector('.ms');
    this.box = el.querySelector('.mbox'); this.fdEl = el.querySelector('.fd'); this.fdb = el.querySelector('.fdb');
    panelPlace(this, 'fsms');   // where it was last, its size too (first: at the right of the waves, under the axis)
    this.events(); this.render(true);
    if (v.sel && this.mine.includes(v.sel)) this.detail(v.sel);   // the selected signal's details, when it is one of them
  }
  // the tree: the modules on the way to the FSMs (the page's scopes), each with its FSMs; the FSMs above every module apart
  build() {
    const v = this.v, ids = new Set(v.scopes().map(g => g.id)), G = v.M.groups;
    this.nodes = new Map(); this.roots = []; this.top = [];
    const node = g => {
      let n = this.nodes.get(g.id); if (n) return n;
      n = { g, up: null, kids: [], fsms: [], all: 0 }; this.nodes.set(g.id, n);
      const a = g.anc.filter(id => ids.has(id));
      if (a.length) { n.up = node(G[a[a.length - 1]]); n.up.kids.push(n); } else this.roots.push(n);
      return n;
    };
    const fs = v.fsms(this.fields), named = fs.filter(r => FSM_NAME.test(r.fsmField ? r.full.slice(r.full.lastIndexOf('.') + 1) : r.name));
    this.mine = this.all || !named.length ? fs : named; this.others = fs.length - this.mine.length;
    for (const r of this.mine) {
      const a = r.anc.filter(id => ids.has(id)); if (a.length) node(G[a[a.length - 1]]).fsms.push(r); else this.top.push(r); }
    const sum = n => (n.all = n.fsms.length + n.kids.reduce((s, k) => s + sum(k), 0)); this.roots.forEach(sum);
    this.open = new Set(this.nodes.keys());   // all open: the tree is only the way to the FSMs
    const mine = new Set(this.mine); this.pick = new Set([...this.pick].filter(r => mine.has(r)));
  }
  close() { panelKeep(this, 'fsms'); this.v.closeMenu(); this.ac.abort(); this.el.remove();
    if (this.v.fsmP === this) this.v.fsmP = null; this.v.canvas.focus({ preventScroll: true }); }
  // an FSM's states the waves reach, of its table's
  seenOf(r) { const st = this.v.fsmStatsOf(r); return [st.states.length - st.unseen.length, st.states.length]; }
  // its name under its module (a struct's field: struct.field)
  label(r) { const up = r.anc.map(id => this.v.M.groups[id]).filter(g => this.nodes.has(g.id)).pop(); return up ? r.full.slice(up.path.length + 1) : r.full; }
  // the FSMs under a module of the tree, all its levels
  under(nd) { return [...nd.fsms, ...nd.kids.flatMap(k => this.under(k))]; }
  // the rows as shown: ['m', node, depth] and ['f', row, depth] (a filter: the matches and the way to them)
  list() {
    const out = [], terms = this.q.trim().split(/\s+/).filter(w => w.replace(/\./g, ''));
    let hit = null, keep = null;
    if (terms.length) {
      hit = new Set(); keep = new Set();
      for (const r of this.mine) if (findRow(r, terms, this.v.M)) hit.add(r);
      for (const n of this.nodes.values()) if (n.fsms.some(r => hit.has(r))) for (let u = n; u; u = u.up) keep.add(u);
    }
    this.hits = hit ? [...hit] : null;
    for (const r of this.top) if (!hit || hit.has(r)) out.push(['f', r, 0]);
    const walk = (n, d) => {
      if (keep && !keep.has(n)) return; out.push(['m', n, d]);
      if (!keep && !this.open.has(n.g.id)) return;
      for (const r of n.fsms) if (!hit || hit.has(r)) out.push(['f', r, d + 1]);
      n.kids.forEach(k => walk(k, d + 1));
    };
    this.roots.forEach(n => walk(n, 0));
    return out;
  }
  // the FSMs Only FSMs / Add to view take: the picked ones, else every one listed
  targets() { return this.pick.size ? [...this.pick] : this.hits || this.mine; }
  render(force = false) {
    const v = this.v, f = v.fsm, key = JSON.stringify([f, this.q, this.open.size, this.openGen || 0, this.pickGen || 0, this.pv,
      this.fields, this.all, [...v.hiddenRows].length, v.onlyState(), v.findMask && v.q, v.rowsAll && v.rowsAll.length]);
    if (!force && key === this.key) { this.marks(); this.values(); return; }
    this.key = key;
    const L = this.rows = this.list(), inL = f ? new Set(f.signals) : null, hits = new Set(this.hits || []);
    this.fi = Math.min(Math.max(this.fi, 0), Math.max(0, L.length - 1));
    this.rowsEl.style.height = L.length * MOD_H + 'px';
    const had = this.rowsEl.contains(document.activeElement), pv = this.pv;
    this.rowsEl.innerHTML = L.map(([k, x, d], i) => {
      const at = `role="treeitem" data-i="${i}" aria-level="${d + 1}" tabindex="-1" ` +
        `style="top:${i * MOD_H}px;padding-left:${4 + d * 14}px"`;
      if (k === 'm') {
        const open = this.hits || this.open.has(x.g.id);
        return `<div class="mn mm" ${at} aria-expanded="${!!open}" title="${esc(`${x.g.path}: ${x.all} state machine${x.all === 1 ? '' : 's'}`)}">` +
          `<span class="tw">${open ? '▾' : '▸'}</span><span class="nm">${esc(x.g.name)}</span><span class="ct">${x.all}</span></div>`;
      }
      const [n, of] = this.seenOf(x), on = inL && inL.has(x.full), out = !v.shown(x);
      const cls = (on ? ' on' : '') + (this.pick.has(x) ? ' pk' : '') + (out ? ' out' : '') + (hits.has(x) ? ' hit' : '') +
        (pv && i >= pv[0] && i <= pv[1] ? ' pv' : '');
      const tip = `${x.full}: ${n} of its ${of} states on the waves` + (on ? (f.mode === 'only' ? ' · one of the FSMs shown' : ' · added to the view') : '') +
        (out ? ' · not in the view now (a click shows it)' : '') + ' · a click: go there, its details below · ctrl+click: pick';
      return `<div class="mn fs${cls}" ${at} aria-selected="${this.pick.has(x)}" title="${esc(tip)}"><span class="tw">${this.pick.has(x) ? '☑' : '◇'}</span>` +
        `<span class="nm">${esc(this.label(x))}</span><span class="st"></span><span class="ct">${n}/${of}</span></div>`;
    }).join('');
    this.marks(); if (had) this.rowAt(this.fi)?.focus({ preventScroll: true });
    this.valsAt = null; this.values();
    const all = this.mine.length, t = this.targets().length, what = this.pick.size ? `${t} picked` : this.hits ? `${t} listed` : `all ${t}`;
    this.stEl.innerHTML = (f ? `<span>${f.mode === 'only' ? 'Only' : 'Added to the view'}: ${f.signals.length} FSM${f.signals.length === 1 ? '' : 's'}</span>` :
        `<span>${all} state machine${all === 1 ? '' : 's'}${this.others ? ` (${this.others} more: all enums)` : ''} · click: go there</span>`) +
      `<button type="button" data-a="only" title="Only these FSMs on the waves (the modules on the way to them as headers)"${t ? '' : ' disabled'}>` +
        `Only FSMs (${what})</button><button type="button" data-a="add" title="These FSMs added to the view as it is (Hide, Only, the find's Mask)"` +
        `${t ? '' : ' disabled'}>+ Add to view</button>` +
      (f ? '<button type="button" data-a="off" title="The view without the FSM layer (✕ in the bar)">Clear</button>' : '') +
      (this.pick.size ? '<button type="button" data-a="unpick" title="Pick none">Unpick</button>' : '');
  }
  // the row with the focus (tabindex 0) and the selected signal's (cur): no new rows for them
  marks() {
    const sel = this.v.sel;
    for (const el of this.rowsEl.children) { const i = +el.dataset.i, x = this.rows[i];
      el.tabIndex = i === this.fi ? 0 : -1; el.classList.toggle('cur', !!x && x[1] === sel); }
  }
  // the states at the cursor (each render, and when only the cursor moved); the details' state at the cursor too
  values(force = false) {
    const v = this.v; if (!force && this.valsAt === v.cursor) return; this.valsAt = v.cursor;
    for (const el of this.rowsEl.querySelectorAll('.mn.fs')) { const r = this.rows[+el.dataset.i][1], s = el.querySelector('.st');
      const x = String(v.valueAt(r, v.cursor)); if (s.textContent !== x) s.textContent = x; }
    if (this.det && this.nowKey() !== this.detNow) this.detail(this.det, this.tab);
  }
  rowAt(i) { return this.rowsEl.querySelector(`.mn[data-i="${i}"]`); }
  focusRow(i = this.fi) {
    this.fi = Math.min(Math.max(i, 0), Math.max(0, this.rows.length - 1)); this.render();
    const el = this.rowAt(this.fi); if (el) { el.focus({ preventScroll: true }); el.scrollIntoView({ block: 'nearest' }); } else this.qEl.focus();
  }
  fold(nd, on) { if (on) this.open.delete(nd.g.id); else this.open.add(nd.g.id); this.openGen = (this.openGen || 0) + 1; this.render(); }
  toggle(r) { if (this.pick.has(r)) this.pick.delete(r); else this.pick.add(r); this.pickGen = (this.pickGen || 0) + 1; this.render(); }
  picked(rows, add = false) { this.pick = new Set([...(add ? this.pick : []), ...rows]); this.pickGen = (this.pickGen || 0) + 1; this.render(); }
  run(i) {   // the FSMs from the anchor to row i picked
    const a = Math.min(this.anchor ?? i, i), b = Math.max(this.anchor ?? i, i);
    this.picked(this.rows.slice(a, b + 1).filter(x => x[0] === 'f').map(x => x[1]));
  }
  apply(mode, rows = this.targets()) {
    const v = this.v; if (!rows.length) return;
    v.setFsm({ mode, signals: rows.map(r => r.full) });
    v.toast((mode === 'only' ? `Only ${rows.length} state machine${rows.length === 1 ? '' : 's'} on the waves (✕ in the bar: the view as it was)` :
      `${rows.length} state machine${rows.length === 1 ? '' : 's'} added to the view (✕ in the bar takes them away)`) + (v.fsmNote || '')); v.fsmNote = '';
  }
  go(i) {
    const x = this.rows[i]; if (!x) return;
    if (x[0] === 'f') { this.v.goFsm(x[1]); this.detail(x[1]); } else this.v.goScope(x[1].g);
    this.focusRow(i);
  }
  // the rows of the tree from y0 to y1 (client px), [first, last] or null
  span(y0, y1) {
    const t = this.rowsEl.getBoundingClientRect().top, a = Math.floor((Math.min(y0, y1) - t) / MOD_H), b = Math.floor((Math.max(y0, y1) - t) / MOD_H);
    const n = this.rows.length; return n && b >= 0 && a < n ? [Math.max(a, 0), Math.min(b, n - 1)] : null;
  }

  /* ---- an FSM's details: its states, its changes, the diagram of them ---- */
  nowKey() {
    const st = this.det && this.v.fsmStatsOf(this.det), i = st ? lastBefore(st.seq.length, j => st.seq[j][0], this.v.cursor) : -1;
    return i >= 0 ? st.seq[i][1] : null;
  }
  // the details of FSM r (null: closed) on a tab (states | changes | graph)
  detail(r, tab = this.tab) {
    const was = this.fdEl.hidden;
    this.det = r || null; this.tab = FSM_TABS.some(t => t[0] === tab) ? tab : 'states'; this.fdEl.hidden = !r;
    if (!r) { this.fdb.innerHTML = ''; return this; }
    if (was) { const b = this.el.getBoundingClientRect();   // the details just opened: the panel all in sight
      if (b.bottom > innerHeight - 4 && getComputedStyle(this.el).position === 'fixed') this.el.style.top = Math.max(4, innerHeight - b.height - 6) + 'px'; }
    const v = this.v, st = v.fsmStatsOf(r), now = this.detNow = this.nowKey(), span = Math.max(1e-30, v.M.t1 - v.M.t0);
    if (r !== this.dsFor) { this.dsel = {}; this.dsFor = r; }   // the row with the keys in each tab (another FSM: the first)
    const had = this.fdb.contains(document.activeElement), di = this.dsel[this.tab] || 0;
    const row = i => ` data-r="${i}" tabindex="${i === di ? 0 : -1}"`;
    const reached = st.states.length - st.unseen.length, nch = Math.max(0, st.seq.length - 1);
    const up = r.anc.map(id => v.M.groups[id]).filter(g => g && this.nodes.has(g.id)).pop();
    this.el.querySelector('.fdn').textContent = (up ? up.name + '.' : '') + this.label(r);   // u_rx.state: which state it is
    this.el.querySelector('.fdm').textContent = `${reached}/${st.states.length} states · ${nch} change${nch === 1 ? '' : 's'}` +
      (st.bad.length ? ` · ${st.bad.length} not in the table` : '');
    for (const b of this.el.querySelectorAll('.fdt button')) b.setAttribute('aria-selected', b.dataset.t === this.tab);
    const when = t => esc(v.when(t));
    const cls = s => (!s.entries.length ? 'never' : '') + (st.table[s.key] === undefined ? ' bad' : '') + (s.key === now ? ' now' : '');
    if (this.tab === 'states') {
      const tip = s => `${st.name(s.key)}: ` + (s.entries.length ? `entered ${s.entries.length}× · a click: the next entry after the cursor, shift: ` +
        'the previous; the first one: its time' : 'never reached on these waves') + (st.table[s.key] === undefined ? ' · not a state of its table' : '');
      this.fdb.innerHTML = '<table class="fst"><tr><th>state</th><th>value</th><th title="how many times it entered it">in</th>' +
        '<th title="of the whole time">time</th><th>first</th></tr>' + [...st.states, ...st.bad].map((s, i) =>
        `<tr class="${cls(s)}" data-k="${esc(s.key)}"${row(i)} title="${esc(tip(s))}"><td>${esc(st.name(s.key))}</td><td>${esc(s.key)}</td>` +
        `<td>${s.entries.length}</td><td>${s.entries.length ? (100 * s.time / span).toFixed(1) + '%' : ''}</td>` +
        `<td${s.entries.length ? ' class="fi" data-first="1"' : ''}>${s.entries.length ? when(s.entries[0]) : 'never'}</td></tr>`).join('') + '</table>';
    } else if (this.tab === 'changes') {
      const ch = [...st.trans.values()].sort((a, b) => b.times.length - a.times.length);
      const bad = x => st.table[x.from] === undefined || st.table[x.to] === undefined;
      this.fdb.innerHTML = ch.length ? '<table class="fst"><tr><th>from</th><th></th><th>to</th><th>×</th><th>first</th></tr>' + ch.map((x, i) =>
        `<tr data-f="${esc(x.from)}" data-t="${esc(x.to)}"${row(i)} class="${bad(x) ? 'bad' : ''}${x.from === now ? ' now' : ''}" ` +
        'title="a click: the next time ' +
        `after the cursor, shift: the previous"><td>${esc(st.name(x.from))}</td><td>→</td><td>${esc(st.name(x.to))}</td><td>${x.times.length}</td>` +
        `<td class="fi" data-first="1">${when(x.times[0])}</td></tr>`).join('') + '</table>' : '<p class="fdz">no change on these waves</p>';
    } else this.fdb.innerHTML = this.graph(st, now);
    if (had) this.focusDet();   // drawn again (the cursor moved): the keys stay on its row
    return this;
  }
  // the details' row with the keys (i: another one, kept per tab), in sight; no rows (the diagram): the details themselves
  focusDet(i = (this.dsel || {})[this.tab] || 0) {
    const rows = this.fdb.querySelectorAll('tr[data-r]');
    if (!rows.length) { this.fdb.focus({ preventScroll: true }); return; }
    i = Math.min(Math.max(i, 0), rows.length - 1); this.dsel[this.tab] = i;
    rows.forEach((x, j) => { x.tabIndex = j === i ? 0 : -1; x.classList.toggle('fk', j === i); });
    rows[i].focus({ preventScroll: true }); rows[i].scrollIntoView({ block: 'nearest' });
  }
  // a key in the details: ↑ ↓ Home End its rows, Enter (shift: back) the cursor to the next time as a click, ← → the tabs,
  // Esc back to the tree -> handled
  detKey(e) {
    const k = e.key, rows = [...this.fdb.querySelectorAll('tr[data-r]')], i = this.dsel[this.tab] || 0;
    if (/^(ArrowUp|ArrowDown|Home|End)$/.test(k)) {
      if (rows.length) this.focusDet(k === 'Home' ? 0 : k === 'End' ? rows.length - 1 : i + (k === 'ArrowDown' ? 1 : -1)); return true; }
    if (k === 'Enter' && rows[i]) { rows[i].dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey: e.shiftKey })); return true; }
    if (k === 'ArrowLeft' || k === 'ArrowRight') {
      const t = FSM_TABS.findIndex(x => x[0] === this.tab) + (k === 'ArrowRight' ? 1 : -1);
      if (t >= 0 && t < FSM_TABS.length) { this.detail(this.det, FSM_TABS[t][0]); this.focusDet(); } return true; }
    if (k === 'Escape') { this.focusRow(); return true; }
    return false;
  }
  // the diagram: the states on a circle (the table's order, then the values not in it), an arrow per change seen, as thick
  // as it is frequent; never reached: dashed; not in the table: red; at the cursor: filled. A click: the next entry / change
  graph(st, now) {
    const ns = [...st.states, ...st.bad], n = ns.length; if (!n) return '<p class="fdz">no states</p>';
    const W = 300, H = 250, cx = W / 2, cy = H / 2, R = n === 1 ? 0 : Math.min(W, H) / 2 - 34, nr = n > 12 ? 13 : 17;
    const at = i => [cx + R * Math.cos(-Math.PI / 2 + 2 * Math.PI * i / n), cy + R * Math.sin(-Math.PI / 2 + 2 * Math.PI * i / n)];
    const pos = new Map(ns.map((s, i) => [s.key, at(i)])), f = x => x.toFixed(1), arcs = [];
    // a point on the way from (px, py) towards (ox, oy), by px off it
    const cut = (px, py, ox, oy, by) => { const l = Math.hypot(ox - px, oy - py) || 1; return [px + (ox - px) / l * by, py + (oy - py) / l * by]; };
    for (const x of st.trans.values()) {
      const [x1, y1] = pos.get(x.from), [x2, y2] = pos.get(x.to), dx = x2 - x1, dy = y2 - y1, d = Math.hypot(dx, dy) || 1;
      const qx = (x1 + x2) / 2 - dy / d * 22, qy = (y1 + y2) / 2 + dx / d * 22;   // bent to its left: a → b and b → a apart
      const [ax, ay] = cut(x1, y1, qx, qy, nr), [bx, by] = cut(x2, y2, qx, qy, nr + 3), c = x.times.length;
      const p = `M${f(ax)} ${f(ay)} Q${f(qx)} ${f(qy)} ${f(bx)} ${f(by)}`, lx = (ax + 2 * qx + bx) / 4, ly = (ay + 2 * qy + by) / 4;
      const bad = st.table[x.from] === undefined || st.table[x.to] === undefined;
      arcs.push(`<g class="fa${bad ? ' bad' : ''}" data-f="${esc(x.from)}" data-t="${esc(x.to)}"><title>${esc(`${st.name(x.from)} → ${st.name(x.to)}: ` +
        `${c}× · a click: the next time`)}</title><path class="hit" d="${p}"/><path d="${p}" style="stroke-width:${f(Math.min(4, 1 + Math.log2(c) * 0.5))}" ` +
        `marker-end="url(#fsm-ah)"/><text x="${f(lx)}" y="${f(ly)}">${c}</text></g>`);
    }
    const nodes = ns.map(s => {
      const [x, y] = pos.get(s.key), nm = st.name(s.key), cl = (!s.entries.length ? ' never' : '') + (st.table[s.key] === undefined ? ' bad' : '') +
        (s.key === now ? ' now' : '');
      return `<g class="fn${cl}" data-k="${esc(s.key)}"><title>${esc(`${nm} (${s.key}): ${s.entries.length ? `entered ${s.entries.length}× · a click: ` +
        'the next entry' : 'never reached'}`)}</title><circle cx="${f(x)}" cy="${f(y)}" r="${nr}"/><text x="${f(x)}" y="${f(y + 3.5)}">${
        esc(nm.length > 8 ? nm.slice(0, 7) + '…' : nm)}</text></g>`;
    });
    return `<svg class="fsg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`the states and changes of ${this.label(this.det)}`)}"><defs><marker ` +
      'id="fsm-ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/>' +
      '</marker></defs>' + arcs.join('') + nodes.join('') + '</svg>';
  }
  // the right button on a row: an FSM's (go, details, Only it, add it, pick, copy) or a module's (its FSMs: Only, add, pick)
  menu(x, cx, cy) {
    const v = this.v; v.closeMenu();
    const b = (m, label, key) => `<button type="button" role="menuitem" data-mm="${m}"><span>${esc(label)}</span>${key ? `<span class="kk">${key}</span>` :
      ''}</button>`;
    const el = document.createElement('div'); el.className = 'wv-menu'; el.setAttribute('role', 'menu');
    const [k, it] = x, rows = k === 'f' ? [it] : this.under(it);
    el.innerHTML = k === 'f' ? `<div class="mh">${esc(it.full)}</div>` + b('go', 'Go to the waves', 'Enter') + b('det', 'States and changes', 'd') + '<hr>' +
        b('only', 'Only this FSM') + b('add', 'Add it to the view') + b('pick', this.pick.has(it) ? 'Unpick' : 'Pick', 'Space') + '<hr>' +
        b('copy', 'Copy path') :
      `<div class="mh">${esc(it.g.path)}: ${rows.length} FSM${rows.length === 1 ? '' : 's'}</div>` + b('go', 'Go to the module', 'Enter') + '<hr>' +
        b('only', 'Only its FSMs') + b('add', 'Add its FSMs to the view') + b('pick', 'Pick its FSMs') + '<hr>' + b('copy', 'Copy scope path');
    v.root.append(el); v.menuEl = el;
    const box = el.getBoundingClientRect();
    el.style.left = Math.max(4, Math.min(cx, innerWidth - box.width - 4)) + 'px'; el.style.top = Math.max(4, Math.min(cy, innerHeight - box.height - 4)) + 'px';
    el.addEventListener('click', e => {
      const m = e.target.closest('button[data-mm]'); if (!m) return; const a = m.dataset.mm; v.closeMenu();
      if (a === 'go') { if (k === 'f') { v.goFsm(it); this.detail(it); } else v.goScope(it.g); }
      else if (a === 'det') this.detail(it);
      else if (a === 'only' || a === 'add') this.apply(a, rows);
      else if (a === 'pick') { if (k === 'f') this.toggle(it); else this.picked(rows, true); }
      else if (a === 'copy') v.copyText(k === 'f' ? it.full : it.g.path);
      this.focusRow();
    });
    el.addEventListener('keydown', e => {
      const bs = [...el.querySelectorAll('button')], j = bs.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); v.closeMenu(); this.focusRow(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault(); bs[(j + (e.key === 'ArrowDown' ? 1 : -1) + bs.length) % bs.length]?.focus(); }
    });
    el.addEventListener('contextmenu', e => e.preventDefault());
    const off = v.offMenu = e => { if (!el.contains(e.target)) v.closeMenu(); };
    setTimeout(() => { if (v.menuEl !== el) return; document.addEventListener('pointerdown', off, { capture: true, signal: v.ac.signal });
      window.addEventListener('blur', off, { signal: v.ac.signal }); }, 0);
    (el.querySelector('button') || el).focus({ preventScroll: true });
  }
  events() {
    const v = this.v, el = this.el, T = this.tree;
    el.addEventListener('click', e => {
      const b = e.target.closest('button[data-a]');
      if (b) {
        const a = b.dataset.a;
        if (a === 'x') this.close();
        else if (a === 'only' || a === 'add') this.apply(a);
        else if (a === 'off') { v.setFsm(null); v.toast('the view without the FSM layer'); }
        else if (a === 'unpick') this.picked([]);
        else if (a === 'fdx') this.detail(null);
        return;
      }
      const tb = e.target.closest('.fdt button[data-t]'); if (tb) { this.detail(this.det, tb.dataset.t); return; }
      if (e.target.closest('.fdb')) {   // the details: a state (its next entry), a change (its next time), the first one
        const s = e.target.closest('[data-k]'), c = e.target.closest('[data-f]'), first = !!e.target.closest('[data-first]'), dir = e.shiftKey ? -1 : 1;
        const tr = e.target.closest('tr[data-r]'); if (tr) { this.dsel[this.tab] = +tr.dataset.r; this.focusDet(); }   // the keys on it
        if (s) v.fsmGo(this.det, { state: s.dataset.k, first }, dir); else if (c) v.fsmGo(this.det, { from: c.dataset.f, to: c.dataset.t, first }, dir);
        return;
      }
      if (this.noClick) { this.noClick = false; return; }   // the end of a box drawn over the tree
      const row = e.target.closest('.mn'); if (!row) return;
      const i = +row.dataset.i, x = this.rows[i]; this.fi = i;
      if (x[0] === 'm' && (e.target.closest('.tw') || e.ctrlKey || e.metaKey)) { this.fold(x[1], this.open.has(x[1].g.id)); this.focusRow(i); }
      else if (x[0] === 'f' && (e.ctrlKey || e.metaKey || e.target.closest('.tw'))) { this.toggle(x[1]); this.anchor = i; this.focusRow(i); }
      else if (x[0] === 'f' && e.shiftKey) { this.run(i); this.focusRow(i); }
      else { this.anchor = i; this.go(i); }
    });
    // a box drawn over the tree (from a row or the space below them): the FSMs in it picked (ctrl: added to the picked)
    let d = null;
    const end = (e, apply) => {
      if (!d) return; const x = d; d = null; this.box.hidden = true; this.pv = null;
      try { if (T.hasPointerCapture(x.id)) T.releasePointerCapture(x.id); } catch (err) { /* gone */ }
      if (!x.on) return;
      this.noClick = true; setTimeout(() => { this.noClick = false; }, 0);
      const s = apply && this.span(x.y, e.clientY);
      if (s) this.picked(this.rows.slice(s[0], s[1] + 1).filter(r => r[0] === 'f').map(r => r[1]), x.ctrl); else this.render();
    };
    T.addEventListener('pointerdown', e => { if (e.button !== 0 || e.target.closest('.tw')) return;
      d = { y: e.clientY, x: e.clientX, on: false, ctrl: e.ctrlKey || e.metaKey, id: e.pointerId }; });
    T.addEventListener('pointermove', e => {
      if (!d || e.pointerId !== d.id) return;
      if (!(e.buttons & 1)) { end(e, false); return; }
      if (!d.on && Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) return;
      if (!d.on) { d.on = true; try { T.setPointerCapture(e.pointerId); } catch (err) { /* no capture */ } }
      const r = this.rowsEl.getBoundingClientRect(), y0 = Math.min(d.y, e.clientY), y1 = Math.max(d.y, e.clientY);
      Object.assign(this.box.style, { top: y0 - r.top + 'px', height: Math.max(2, y1 - y0) + 'px' }); this.box.hidden = false;
      this.pv = this.span(d.y, e.clientY); this.render();
    });
    T.addEventListener('pointerup', e => end(e, true));
    T.addEventListener('pointercancel', e => end(e, false));
    T.addEventListener('contextmenu', e => { const row = e.target.closest('.mn'); if (!row) return; e.preventDefault();
      this.fi = +row.dataset.i; this.menu(this.rows[this.fi], e.clientX, e.clientY); });
    el.querySelector('.ff').addEventListener('change', e => { this.fields = e.target.checked; this.build(); this.render(true); });
    el.querySelector('.fa').addEventListener('change', e => { this.all = e.target.checked; this.build(); this.render(true); });
    this.qEl.addEventListener('input', () => { this.q = this.qEl.value; this.fi = 0; this.render(); });
    this.qEl.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); const h = this.hits && this.hits[0];
        if (h) { v.goFsm(h); this.detail(h); this.focusRow(this.rows.findIndex(x => x[1] === h)); } }
      else if (e.key === 'ArrowDown') { e.preventDefault(); this.focusRow(0); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation();   // not the viewer's reset
        if (this.qEl.value) { this.qEl.value = this.q = ''; this.render(); } else this.close(); }
    });
    panelFrame(this, 'fsms');   // the header moves it, its edges and corners size it (modules.js)
    el.addEventListener('keydown', e => {
      if (e.target === this.qEl) return;
      if (e.target.closest('.fdb') && !e.ctrlKey && !e.metaKey && !e.altKey && this.detKey(e)) { e.preventDefault(); e.stopPropagation(); return; }
      const k = e.key, x = this.rows[this.fi];
      if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); if (d) { end(e, false); return; }
        if (v.menuEl) { v.closeMenu(); this.focusRow(); return; } this.close(); return; }
      if (!treeKey(e, el) || e.ctrlKey || e.metaKey || e.altKey) return;
      let h = true;
      if (k === 'ArrowDown' || k === 'ArrowUp' || k === 'Home' || k === 'End') {
        const to = Math.min(Math.max(k === 'Home' ? 0 : k === 'End' ? this.rows.length - 1 : this.fi + (k === 'ArrowDown' ? 1 : -1), 0), this.rows.length - 1);
        if (e.shiftKey && (k === 'ArrowDown' || k === 'ArrowUp')) { if (this.anchor == null) this.anchor = this.fi; this.run(to); } else this.anchor = null;
        this.focusRow(to);
      } else if (k === 'ArrowRight' && x && x[0] === 'm') {
        if (!this.hits && !this.open.has(x[1].g.id)) this.fold(x[1], false); else this.fi++;
        this.focusRow(); }
      else if (k === 'ArrowLeft' && x) {
        if (x[0] === 'm' && !this.hits && this.open.has(x[1].g.id)) this.fold(x[1], true);
        else { for (let j = this.fi - 1; j >= 0; j--) if (this.rows[j][0] === 'm' && this.rows[j][2] < x[2]) { this.fi = j; break; } }
        this.focusRow();
      } else if (k === 'Enter' && x) this.go(this.fi);
      else if (k === ' ' && x && x[0] === 'f') { this.toggle(x[1]); this.anchor = this.fi; this.focusRow(); }
      else if (k === 'd' && x && x[0] === 'f') this.detail(this.det === x[1] ? null : x[1]);
      else if (k === 'ContextMenu' && x) { const b = this.rowAt(this.fi).getBoundingClientRect(); this.menu(x, b.left + 20, b.bottom); }
      else if (k === '/') this.qEl.focus();
      else h = false;
      if (h) e.preventDefault();
    });
  }
}

/* ---------------- the types inspector (the right button's Type…, the command types) ---------------- */
Object.assign(WaveView.prototype, {
  // where a signal's labels or fields come from: the types file read for these waves (Sources…, x.types.json beside the
  // dump: opts.svWhy of svApply) and its path there, its own labels kept before the file's (own), a width that does not fit,
  // no entry (with the paths of its name the file has); else the page's own (an FST, the config, mkconfig --types) or none
  // -> {signal, labels, fields, status (typed own width plain none, null: no file), key, why, run}
  typesOf(r) {
    const why = this.opts.svWhy, sv = this.opts.sv, p = String(r.path || r.full);
    let at = p, w = why && why.get(p);
    for (let q = p; !w && why && r.field && q.includes('.');) { q = q.slice(0, q.lastIndexOf('.')); w = why.get(q); if (w) at = q; }   // a field: its vector's
    const out = { signal: r.full, labels: !!fsmTable(r), fields: !!r.field || !!(r.src && r.src.fields), status: w ? w.status : null, key: w ? w.key : null,
      why: '' };
    const file = sv && sv.paths ? (sv.names || ['the types file']).join(', ') + (sv.producer && sv.producer.tool ? ` (${sv.producer.tool})` : '') : '';
    // its own labels (an FST's table, the config's) stay before the file's: then the file's are not the ones it shows
    const own = w && (w.labels === 'own' || w.fields === 'own') && w.labels !== 'types' && w.fields !== 'types';
    const named = w ? `${w.key}${w.as !== at ? ` (the dump's ${at} as the types name it)` : ''}` : '';
    if (w && w.status === 'typed' && own) { out.status = 'own';
      out.why = `its own labels (an FST's table, the config's "enum" / "fields") stay: ${file} has ${named} too, ${w.width} bits, not used`; }
    else if (w && w.status === 'typed') out.why = `its type from ${file}: ${named}, ${w.width} bits`;
    else if (w && w.status === 'width') out.why = `${file} has ${w.key} of ${w.width} bits, the dump ${r.width || 1}: not used, ` +
      `${out.labels || out.fields ? 'its own labels stay' : 'left as numbers'} (another run, other parameters?)`;
    else if (w && sv.plain && hasKey(sv.plain, w.as)) { out.status = 'plain'; out.why = `${file}: ${w.as} is ${sv.plain[w.as]}, no enum or struct` }
    else if (w) {   // not in the file: the ones of its name it has; another root (no root of the file's): its "map"
      const leaf = w.as.replace(/(\.?\[-?\d+\])+$/, '').split('.').pop(), near = Object.keys(sv.paths).filter(k => k.split('.').pop() === leaf);
      const roots = new Set(Object.keys(sv.paths).map(k => k.split('.')[0])), other = !roots.has(w.as.split('.')[0]);
      out.why = `${file} has no ${w.as}` + (near.length ? `; of its name it has ${near.slice(0, 3).join(', ')}${near.length > 3 ? ' …' : ''}` : '') +
        (other ? ` · the file's top scopes are ${[...roots].slice(0, 3).join(', ')}: a "map" in it ({"${w.as.split('.')[0]}": "${[...roots][0]}"}) ` +
          'names this one as it does' : ''); }
    else out.why = out.labels || out.fields ? 'its labels come with the page: an FST\'s tables, the config\'s "enum" / "fields" (mkconfig --types, --sv)' :
      'no labels: no types file read for these waves (x.types.json beside the dump, or Sources…)';
    if (this.opts.svRun && this.opts.svRun.length) out.run = this.opts.svRun.slice();
    return out;
  },
  // the same over the menu (x, y: where), with Copy
  typesBox(r, x, y) {
    const o = this.typesOf(r); this.closeMenu();
    const el = document.createElement('div'); el.className = 'wv-menu wv-types'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', 'its type');
    const text = [o.signal, o.why, ...(o.run || []).map(n => 'run: ' + n)].join('\n');
    el.innerHTML = `<div class="mh">${esc(o.signal)}</div><p>${esc(o.why)}</p>${(o.run || []).map(n => `<p class="run">${esc(n)}</p>`).join('')}` +
      '<button type="button" data-m="copy">Copy</button><button type="button" data-m="x">Close</button>';
    this.root.append(el); this.menuEl = el;
    const b = el.getBoundingClientRect();
    el.style.left = Math.max(4, Math.min(x, innerWidth - b.width - 4)) + 'px'; el.style.top = Math.max(4, Math.min(y, innerHeight - b.height - 4)) + 'px';
    el.addEventListener('click', e => { const m = e.target.closest('button[data-m]'); if (!m) return; if (m.dataset.m === 'copy') this.copyText(text);
      this.closeMenu(); this.canvas.focus({ preventScroll: true }); });
    el.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.closeMenu(); this.canvas.focus(); } });
    const off = this.offMenu = e => { if (!el.contains(e.target)) this.closeMenu(); };
    setTimeout(() => { if (this.menuEl === el) document.addEventListener('pointerdown', off, { capture: true, signal: this.ac.signal }); }, 0);
    el.querySelector('button').focus({ preventScroll: true });
    return o;
  },
});
