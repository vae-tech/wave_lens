/* wavelens/src/modules.js — the Modules panel (t): the page's modules as a tree, without signals. A click goes to a
   module's signals; a box over the tree (ctrl / shift+click, Space, Only matches) keeps Only those modules on the waves. */

/* ---------------- Only: the modules kept on the waves ---------------- */
// Only (state "only": {modules: [paths], on}; the command only): the waves keep the signals of the modules picked and of
// their submodules; the modules on the way to them stay as headers (their own signals go), every other module goes.
// A layer of its own: Hide stays as it is under it, the highlight comes back with the rows; paused (on: false) the set
// is kept and every module shows. Your groups stay (their signals by the signal they show), the rows of plugins follow
// the module they are under; the ones above every module (ƒ expressions) stay. In the saved state, Save page and undo,
// not in this browser's storage: a page opened again starts without it.
Object.assign(WaveView.prototype, {
  // the page's scopes (modules, interfaces …) in the model's order: its own groups, not the value of a struct or a union
  scopes() {
    if (!this.scopeL) this.scopeL = this.M.rows.filter(r => r.type === 'group' && this.M.groups[r.id] === r && r.kind !== 'struct' && r.kind !== 'union');
    return this.scopeL;
  },
  scopeOf(path) { if (!this.scopeBy) this.scopeBy = new Map(this.scopes().map(g => [g.path, g])); return this.scopeBy.get(path) || null; },
  // the scope a row is in (a copy: the one of the signal it shows), the nearest one above it; null: none
  scopeOfRow(r) {
    const s = r && (r.orig || r.of || r), ids = this.scopeIds || (this.scopeIds = new Set(this.scopes().map(g => g.id)));
    if (!s || !s.anc) return null;
    if (s.type === 'group' && ids.has(s.id)) return s;
    for (let i = s.anc.length - 1; i >= 0; i--) if (ids.has(s.anc[i])) return this.M.groups[s.anc[i]];
    return null;
  },
  // module paths as Only keeps them: the known ones, in the model's order, none under another one of them
  onlyNorm(paths) {
    const gs = [...new Set(paths)].map(p => this.scopeOf(p)).filter(Boolean), ids = new Set(gs.map(g => g.id));
    return gs.filter(g => !g.anc.some(id => ids.has(id))).sort((a, b) => a.id - b.id).map(g => g.path);
  },
  onlyOn() { return !!(this.only && this.only.on); },
  onlyState() { return this.only ? { modules: [...this.only.modules], on: this.only.on } : null; },
  // the groups Only keeps: inn — the modules picked and every group under them; path — the modules on the way to them
  onlyIds() {
    const key = this.only ? this.only.modules.join('\n') : '';
    if (this.onlyMemo && this.onlyMemo.key === key) return this.onlyMemo;
    const sel = new Set((this.only ? this.only.modules : []).map(p => this.scopeOf(p)).filter(Boolean).map(g => g.id)), inn = new Set(), path = new Set();
    for (const r of this.M.rows) if (r.type === 'group' && (sel.has(r.id) || r.anc.some(id => sel.has(id)))) inn.add(r.id);
    for (const id of sel) for (const a of this.M.groups[id].anc) if (!inn.has(a)) path.add(a);
    return (this.onlyMemo = { key, sel, inn, path, model: new Set(this.M.rows) });
  },
  // the rows of these (allRows) that Only keeps
  onlyKeep(rows) {
    const { inn, path, model } = this.onlyIds(), G = this.M.groups;
    const test = r => {
      if (r.type === 'group' && (path.has(r.id) || inn.has(r.id))) return true;
      let up = null;   // the nearest group above it of the page's (not a plugin's)
      for (let i = r.anc.length - 1; i >= 0 && up == null; i--) if (G[r.anc[i]] && model.has(G[r.anc[i]])) up = r.anc[i];
      return up != null ? inn.has(up) : !model.has(r);   // above every module: a plugin's rows stay, the page's top signals go
    };
    return rows.filter(r => r.user || (r.ug ? test(r.orig) : test(r) && (!r.of || test(r.of))));
  },
  // whether a row is in the view: not hidden, not left out by Only (folded away it still is)
  shown(r) {
    if (this.rowsStale) this.allRows();   // Hide changed in a run (its drawing held back)
    if (this.shownOf !== this.rowsAll) { this.shownOf = this.rowsAll; this.shownS = new Set(this.rowsAll || []); }
    return !!r && this.shownS.has(r);
  },
  // Only set: {modules: [paths]} (they replace the set and turn it on, unless on says otherwise), {on: bool} (pause /
  // resume the set there is); null: every module again. open: the modules a gesture named (a box: every one it touched,
  // the nested ones too), opened on the waves with the modules on the way to them; Clear, pause and resume fold nothing
  setOnly(o) {
    if (o == null) this.only = null;
    else {
      const mods = o.modules !== undefined ? this.onlyNorm([].concat(o.modules || [])) : this.only && this.only.modules;
      if (!mods) return this;
      this.only = { modules: mods, on: o.on !== undefined ? !!o.on : o.modules !== undefined || this.only.on };
    }
    if (o && o.open && o.open.length) this.onlyOpen(o.open);
    this.onlyMemo = null; this.allRows(); this.onlyFix();
    if (this.q) this.find(this.q, false, null, false); else { this.renderNames(); this.draw(); }   // the matches outside it counted again (no refolding)
    this.onlyShow(); return this;
  },
  // these modules opened in the names column, and the ones above them (the ones under them keep their folding; Hide stays).
  // The find's Open (every module folded but the way to its matches) is switched off first: its next search would fold
  // them again; the query and its highlight stay
  onlyOpen(paths) {
    const gs = [].concat(paths).map(p => this.scopeOf(p)).filter(Boolean); if (!gs.length) return;
    if (this.findOpen && this.q) {   // as its button does: the folding from before the search back, then these opened
      this.findOpen = false; if (this.foldSaved) this.collapsed = this.foldSaved; this.foldSaved = null;
      this.root.querySelector('button[data-act=fopen]')?.setAttribute('aria-pressed', false);
      this.onlyNote = ' · the find\'s Open is off'; this.toast('Only: the modules picked are open' + this.onlyNote); }
    for (const g of gs) [...g.anc, g.id].forEach(id => this.collapsed.delete(id));
    this.foldTouched = true;
  },
  // the selection among the rows that went goes (the highlight stays: it comes back with them)
  onlyFix() {
    const ok = r => this.shown(r);
    if (this.sel && !ok(this.sel)) this.sel = null;
    if (this.selRun.size) this.selRun = new Set([...this.selRun].filter(ok));
    for (const k of ['selAnchor', 'hlAnchor', 'fiRow']) if (this[k] && !ok(this[k])) this[k] = null;
    if (this.rangeRow && !ok(this.rangeRow)) { this.rangeRow = null; this.rangeKey = null; }
  },
  // the bar's Only: N modules ‖ (a click pauses it, ▶ resumes) and its ✕; the panel's marks
  onlyShow() {
    const p = this.root.querySelector('.bar button[data-act=onlyp]'), x = this.root.querySelector('.bar button[data-act=onlyx]'), o = this.only;
    if (p) { p.hidden = x.hidden = !o; if (o) { const n = o.modules.length, m = `${n} module${n === 1 ? '' : 's'}`;
      p.textContent = o.on ? `Only: ${m} ‖` : `Only paused: ${m} ▶`; p.setAttribute('aria-pressed', o.on); } }
    if (this.mods) this.mods.render();
  },
  // the matches of a search among the rows Only leaves out (hidden ones not counted)
  onlyOut(match) { return this.onlyOn() && this.rowsHid ? this.rowsHid.filter(r => r.type !== 'space' && !this.shown(r) && match(r)).length : 0; },
  // a module (its path or row) on the waves: opened with the modules above it, shown when hidden, its first signal (its
  // own, else of a submodule) selected in the middle; outside Only: Only paused (kept) to show it
  goScope(path) {
    const g = typeof path === 'string' ? this.scopeOf(path) : path, M = this.M;
    if (!g) { this.toast(`no module "${path}"`); return this; }
    let why = '';
    if (this.onlyOn()) { const { inn, path: way } = this.onlyIds(); if (!inn.has(g.id) && !way.has(g.id)) { this.only.on = false; this.onlyMemo = null;
      why = ` · Only paused to show it (▶ in the bar)`; this.onlyShow(); } }
    let un = false;
    for (const p of [...g.anc.map(id => M.groups[id].path), g.path]) if (this.hiddenRows.delete(p)) un = true;
    if (un) { this.rowsStale = true; this.saveRows(); }
    if (why && this.q) this.find(this.q);   // the matches Only (and the Hide taken off) left out: found now
    [...g.anc, g.id].forEach(id => this.collapsed.delete(id));
    const rows = this.allRows(), sig = r => r.type === 'sig' && r.tr && !r.ug && r.anc.includes(g.id);
    const first = rows.find(r => sig(r) && r.anc[r.anc.length - 1] === g.id) || rows.find(sig);
    if (first) first.anc.forEach(id => this.collapsed.delete(id));
    this.foldTouched = true; this.onlyFix(); this.renderNamesNow();
    if (first) this.select(first); else this.draw();
    this.centerRow(first || g);
    this.toast((first ? g.path : `${g.path}: no signal in it or below`) + why);
    return this;
  },
  // the Modules panel: open (and the selected signal's module found in it), closed (false), or as it is toggled
  modules(on = !this.mods, locate = false) {
    if (!on) { if (this.mods) this.mods.close(); return this; }
    if (!this.scopes().length) { this.toast('no modules on these waves'); return this; }
    if (!this.mods) this.mods = new Mods(this);
    if (locate) this.mods.locate(); else this.mods.focusRow();
    return this;
  },
});

/* ---------------- the panel ---------------- */
// One per viewer, over it (on a narrow screen a drawer at the side; not printed): its header moves it, its corner sizes
// it. The tree has its own folding (the waves keep theirs), a fuzzy filter (the find's), the counts of signals (its own /
// with its submodules; a packed struct one signal), ● at the module of the selected signal. A click on a name goes there
// (goScope); a box drawn over names (4 px), ctrl+click / Space (one module in or out), shift+click (a run) set Only at
// once; the right button: a menu of the module. Keys: ↑ ↓ Home End, ← → fold / open (the parent / the first child),
// Enter go, Space, shift+↑ ↓, / the filter, t the selected signal's module, Esc closes it (a box: cancels it).
const MOD_H = 22;   // a row of the tree, px (the box and the keys count rows by it)
class Mods {
  constructor(v) {
    this.v = v; this.q = ''; this.fi = 0; this.anchor = null; this.key = ''; this.ac = new AbortController();   // a box's Esc on the document
    const sc = v.scopes(), ids = new Set(sc.map(g => g.id)), G = v.M.groups;
    // the tree: per module its parent module, its children, the signals of its own and with its submodules
    this.nodes = new Map(sc.map(g => [g.id, { g, up: null, kids: [], own: 0, all: 0 }]));
    for (const n of this.nodes.values()) { const a = n.g.anc.filter(id => ids.has(id)); n.up = a.length ? this.nodes.get(a[a.length - 1]) : null;
      if (n.up) n.up.kids.push(n); }
    const struct = id => G[id] && (G[id].kind === 'struct' || G[id].kind === 'union');
    for (const r of v.M.rows) {
      if (!((r.type === 'sig' && r.tr) || (r.type === 'group' && struct(r.id))) || r.anc.some(struct)) continue;   // a struct: one signal
      const up = r.anc.length && this.nodes.get(r.anc[r.anc.length - 1]); if (up) up.own++;
    }
    const sum = n => (n.all = n.own + n.kids.reduce((s, k) => s + sum(k), 0));
    this.roots = [...this.nodes.values()].filter(n => !n.up); this.roots.forEach(sum);
    this.open = new Set(sc.filter(g => !this.nodes.get(g.id).up || !this.nodes.get(g.id).up.up).map(g => g.id));   // two levels open
    const el = this.el = document.createElement('div'); el.className = 'wv-mods'; el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'modules');
    el.innerHTML = (`<div class="mh"><b>Modules</b><span class="mt">${esc(v.opts.title || v.M.title || '')}</span><button type="button" data-a="loc" ` +
        'title="The selected signal\'s module in the tree (t)">Locate</button><button type="button" data-a="x" aria-label="close" ' +
        'title="Close (Esc)">✕</button></div><div class="mf"><input type="search" class="mq" spellcheck="false" autocomplete="off" ' +
        'placeholder="Filter modules…" aria-label="filter modules" ' +
        'title="Fuzzy, as the find: Enter goes to the first, shift+Enter keeps Only the matches, ↓ into the tree"><button type="button" data-a="om" ' +
        'title="Only the modules that match (shift+Enter)">Only matches</button></div><div class="ms"></div>' +
        '<div class="mtr" role="tree" aria-label="modules" aria-multiselectable="true"><div class="mbox" hidden></div><div class="mrows"></div></div>');
    v.root.append(el);
    this.tree = el.querySelector('.mtr'); this.rowsEl = el.querySelector('.mrows'); this.box = el.querySelector('.mbox');
    this.qEl = el.querySelector('.mq'); this.stEl = el.querySelector('.ms');
    const w = v.wcol.getBoundingClientRect(), pw = el.offsetWidth;   // at the right of the waves (the names stay in sight), under the axis
    el.style.left = Math.max(6, Math.min(w.right - pw - 12, innerWidth - pw - 6)) + 'px';
    el.style.top = Math.max(6, Math.min(Math.max(w.top, 0) + v.hdrH + 6, innerHeight - 240)) + 'px';
    this.events(); this.render(true);   // drawn again with the names column (Names.render): Hide, Only, the selection
  }
  close() { this.ac.abort(); this.el.remove(); this.v.closeMenu(); if (this.v.mods === this) this.v.mods = null; this.v.canvas.focus({ preventScroll: true }); }
  // the rows of the tree as shown: the open ones (a filter: the matches and the way to them)
  list() {
    const out = [], terms = this.q.trim().split(/\s+/).filter(w => w.replace(/\./g, ''));
    let keep = null;
    if (terms.length) {
      keep = new Set(); this.hits = [];
      for (const nd of this.nodes.values()) if (findRow(nd.g, terms, this.v.M)) { this.hits.push(nd); for (let u = nd; u; u = u.up) keep.add(u); }
    } else this.hits = null;
    const walk = (nd, d) => { if (keep && !keep.has(nd)) return; out.push([nd, d]);
      if (keep || this.open.has(nd.g.id)) nd.kids.forEach(k => walk(k, d + 1)); };
    this.roots.forEach(nd => walk(nd, 0));
    return out;
  }
  // the panel drawn again when what it shows changed (force: anyway)
  render(force = false) {
    const v = this.v, o = v.only, cur = v.scopeOfRow(v.sel);
    const key = JSON.stringify([o, [...v.hiddenRows].join('\n'), cur && cur.id, this.q, [...this.open].length, this.openGen || 0, this.fi, this.pv || null]);
    if (!force && key === this.key) return;
    this.key = key;
    const L = this.rows = this.list(), { sel, inn, path } = v.onlyIds(), H = v.hiddenRows;
    this.fi = Math.min(Math.max(this.fi, 0), Math.max(0, L.length - 1));
    const pv = this.pv ? new Set(L.slice(this.pv[0], this.pv[1] + 1).map(([nd]) => nd)) : null;
    const hid = g => H.has(g.path) || g.anc.some(id => H.has((v.M.groups[id] || {}).path));
    this.rowsEl.style.height = L.length * MOD_H + 'px';
    const had = this.rowsEl.contains(document.activeElement);   // the rows made again: the focus stays on the row
    this.rowsEl.innerHTML = L.map(([nd, d], i) => {
      const g = nd.g, open = this.hits || this.open.has(g.id), on = o && sel.has(g.id), via = o && !on && inn.has(g.id), way = o && path.has(g.id);
      const cls = (on ? ' on' : via ? ' inc' : way ? ' way' : '') + (cur === g ? ' cur' : '') + (hid(g) ? ' hid' : '') + (pv && pv.has(nd) ? ' pv' : '') +
        (this.hits && this.hits.includes(nd) ? ' hit' : '');
      const kd = hasKey(KIND_MARK, g.kind) ? `<span class="kd" title="${esc(g.kind)}">${KIND_MARK[g.kind]}</span>` : '';
      const tip = `${g.path}: ${nd.own} signal${nd.own === 1 ? '' : 's'} of its own, ${nd.all} with its submodules` + (on ? ' · Only keeps it' : via ?
        ' · Only keeps it (its module is picked)' : way ? ' · on the way to the modules Only keeps: its header only' : '') +
        (hid(g) ? ' · hidden (Hidden: N ✕ in the bar shows it)' : '');
      return `<div class="mn${cls}" role="treeitem" data-i="${i}" aria-level="${d + 1}"${nd.kids.length ? ` aria-expanded="${!!open}"` : ''} ` +
        `aria-selected="${!!on}" tabindex="${i === this.fi ? 0 : -1}" style="top:${i * MOD_H}px;padding-left:${4 + d * 14}px" title="${esc(tip)}">` +
        `<span class="tw">${nd.kids.length ? (open ? '▾' : '▸') : ''}</span>${kd}<span class="nm">${esc(g.name)}</span>` +
        `<span class="ct">${nd.kids.length ? `${nd.own} / ${nd.all}` : nd.own}</span></div>`;
    }).join('');
    if (had) this.rowAt(this.fi)?.focus({ preventScroll: true });
    const n = o ? o.modules.length : 0, out = o && this.hits ? o.modules.filter(p => !L.some(([nd]) => nd.g.path === p)).length : 0;
    const tip = 'with their submodules; the modules on the way to them: their headers';
    this.stEl.innerHTML = o ? (`<span title="${tip}">${o.on ? 'Only' : 'Only paused'}: ${n} module${n === 1 ? '' : 's'}` +
        `${out ? ` (${out} not in the filter)` : ''}</span><button type="button" data-a="op">${o.on ? '‖ Pause' : '▶ Resume'}</button>` +
        '<button type="button" data-a="ox">Clear</button>') : '<span>Click: go there · drag over names: Only those (with submodules)</span>';
    this.el.classList.toggle('paused', !!o && !o.on);
    const om = this.el.querySelector('button[data-a=om]'); om.disabled = !this.hits || !this.hits.length;
    om.textContent = this.hits ? `Only matches (${this.hits.length})` : 'Only matches';
  }
  rowAt(i) { return this.rowsEl.querySelector(`.mn[data-i="${i}"]`); }
  focusRow(i = this.fi) {
    this.fi = Math.min(Math.max(i, 0), Math.max(0, this.rows.length - 1)); this.render();
    const el = this.rowAt(this.fi); if (el) { el.focus({ preventScroll: true }); el.scrollIntoView({ block: 'nearest' }); } else this.qEl.focus();
  }
  // the module of a row (the selected signal's): the way to it opened in the tree, in sight, with the focus (the waves as they are)
  locate(row = this.v.sel) {
    const g = this.v.scopeOfRow(row);
    if (!g) { this.v.toast('select a signal: t finds its module in the tree'); this.focusRow(); return; }
    if (this.hits && !this.hits.some(nd => nd.g === g)) { this.q = this.qEl.value = ''; }
    for (let u = this.nodes.get(g.id).up; u; u = u.up) this.open.add(u.g.id);
    this.openGen = (this.openGen || 0) + 1; this.render();
    this.focusRow(this.rows.findIndex(([nd]) => nd.g === g));
  }
  fold(nd, on) { if (on) this.open.delete(nd.g.id); else this.open.add(nd.g.id); this.openGen = (this.openGen || 0) + 1; this.render(); }
  subtree(nd, on) { const all = n => [n, ...n.kids.flatMap(all)]; for (const k of all(nd)) if (on) this.open.add(k.g.id); else this.open.delete(k.g.id);
    this.openGen = (this.openGen || 0) + 1; this.render(); }
  // Only: these modules (replacing the set), or one in / out of it (ctrl+click, Space); the toast says what is kept
  // the modules named are opened on the waves (all of them: a box's nested ones too), the set keeps the outermost
  only(nds) { const ps = nds.map(nd => nd.g.path); this.v.setOnly({ modules: ps, open: ps }); this.said(); }
  toggle(nd) {   // in: it opens; out: the folding stays; under a picked one: it opens, the set as it is
    const v = this.v, o = v.only, cur = o ? [...o.modules] : [], { sel, inn } = v.onlyIds();
    if (o && !sel.has(nd.g.id) && inn.has(nd.g.id)) { const up = nd.g.anc.map(id => v.M.groups[id]).find(g => sel.has(g.id));
      v.setOnly({ on: true, open: [nd.g.path] });
      v.toast(`${nd.g.name}: opened, in Only by ${up ? up.path : 'its module'} (Only this subtree: the right button)${v.onlyNote || ''}`); v.onlyNote = '';
      return; }
    const out = sel.has(nd.g.id);
    v.setOnly({ modules: out ? cur.filter(p => p !== nd.g.path) : cur.concat(nd.g.path), on: true, open: out ? null : [nd.g.path] }); this.said();
  }
  said() { const v = this.v, o = v.only, n = o ? o.modules.length : 0, note = v.onlyNote || ''; v.onlyNote = '';
    v.toast((n ? `Only: ${o.modules.slice(0, 3).join(', ')}${n > 3 ? ` +${n - 3}` : ''} (✕ in the bar: every module)` : 'Only: no module') + note); }
  // the rows of the tree from y0 to y1 (client px): their first and last index
  span(y0, y1) {
    const t = this.rowsEl.getBoundingClientRect().top, a = Math.floor((Math.min(y0, y1) - t) / MOD_H), b = Math.floor((Math.max(y0, y1) - t) / MOD_H);
    const n = this.rows.length; return n && b >= 0 && a < n ? [Math.max(a, 0), Math.min(b, n - 1)] : null;   // over no name: none
  }
  events() {
    const v = this.v, el = this.el, T = this.tree;
    el.addEventListener('click', e => {
      const b = e.target.closest('button[data-a]'); if (!b) return;
      const a = b.dataset.a;
      if (a === 'x') this.close();
      else if (a === 'loc') this.locate();
      else if (a === 'om') this.matches();
      else if (a === 'op') v.setOnly({ on: !v.only.on });
      else if (a === 'ox') { v.setOnly(null); v.toast('Only: every module again'); }
    });
    this.qEl.addEventListener('input', () => { this.q = this.qEl.value; this.fi = 0; this.render(); });
    this.qEl.addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.shiftKey) { e.preventDefault(); this.matches(); }
      else if (e.key === 'Enter') { e.preventDefault(); const h = this.hits && this.hits[0];
        if (h) { v.goScope(h.g); this.focusRow(this.rows.findIndex(([nd]) => nd === h)); } }
      else if (e.key === 'ArrowDown') { e.preventDefault(); this.focusRow(0); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation();   // not the viewer's reset
        if (this.qEl.value) { this.qEl.value = this.q = ''; this.render(); } else this.close(); }
    });
    // the header moves the panel (the narrow screen's drawer stays where it is)
    const head = el.querySelector('.mh');
    head.addEventListener('pointerdown', e => {
      if (e.button !== 0 || e.target.closest('button') || getComputedStyle(el).position !== 'fixed' || matchMedia('(max-width: 600px)').matches) return;
      const b = el.getBoundingClientRect(), dx = e.clientX - b.left, dy = e.clientY - b.top; head.setPointerCapture(e.pointerId);
      const mv = ev => { el.style.left = Math.min(Math.max(ev.clientX - dx, 0), innerWidth - 60) + 'px';
        el.style.top = Math.min(Math.max(ev.clientY - dy, 0), innerHeight - 30) + 'px'; };
      const up = () => { for (const [t, f] of [['pointermove', mv], ['pointerup', up], ['pointercancel', up]]) head.removeEventListener(t, f); };
      head.addEventListener('pointermove', mv); head.addEventListener('pointerup', up); head.addEventListener('pointercancel', up);
    });
    // the tree: a click (go, ctrl: in / out, shift: a run, ▸: fold), a box (Only), the right button (the menu)
    let d = null;
    // Esc while the box is drawn (the focus may be in the filter or on the waves): the box goes, nothing else
    const esc = e => { if (e.key !== 'Escape' || !d) return; e.preventDefault(); e.stopPropagation(); end(e, false); };
    const end = (e, apply) => {
      if (!d) return; const x = d; d = null; this.box.hidden = true; this.pv = null; document.removeEventListener('keydown', esc, true);
      try { if (T.hasPointerCapture(x.id)) T.releasePointerCapture(x.id); } catch (err) { /* gone */ }
      if (!apply) { this.render(); return; }
      if (x.on) { const s = this.span(x.y, e.clientY); if (!s) { this.render(); return; }
        this.only(this.rows.slice(s[0], s[1] + 1).map(([nd]) => nd)); this.anchor = s[0]; this.focusRow(s[1]); return; }
      const i = x.i, nd = i != null && this.rows[i] && this.rows[i][0]; if (!nd) return;
      this.fi = i;
      if (x.tw) this.fold(nd, this.open.has(nd.g.id));
      else if (x.ctrl) { this.toggle(nd); this.anchor = i; }
      else if (x.shift && this.anchor != null) this.only(this.rows.slice(Math.min(this.anchor, i), Math.max(this.anchor, i) + 1).map(r => r[0]));
      else { this.anchor = i; v.goScope(nd.g); }
      this.focusRow(i);
    };
    T.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      const row = e.target.closest('.mn'), i = row ? +row.dataset.i : null;
      d = { y: e.clientY, x: e.clientX, i, on: false, tw: !!e.target.closest('.tw'), ctrl: e.ctrlKey || e.metaKey, shift: e.shiftKey, id: e.pointerId };
      if (!d.tw) e.preventDefault();   // no text selection while drawing the box; the focus is set at the end
    });
    T.addEventListener('pointermove', e => {
      if (!d || e.pointerId !== d.id) return;
      if (!(e.buttons & 1)) { end(e, false); return; }
      if (!d.on && (d.tw || d.ctrl || d.shift || Math.hypot(e.clientX - d.x, e.clientY - d.y) < 4)) return;
      if (!d.on) { d.on = true; try { T.setPointerCapture(e.pointerId); } catch (err) { /* no capture */ }
        document.addEventListener('keydown', esc, { capture: true, signal: this.ac.signal }); }
      const tb = T.getBoundingClientRect();   // near the top or the bottom: the tree scrolls (the start of the box moves with its content)
      const dy = e.clientY < tb.top + 16 ? -MOD_H : e.clientY > tb.bottom - 16 ? MOD_H : 0;
      if (dy) { const s0 = T.scrollTop; T.scrollTop += dy; d.y -= T.scrollTop - s0; }
      const r = this.rowsEl.getBoundingClientRect(), y0 = Math.min(d.y, e.clientY), y1 = Math.max(d.y, e.clientY);
      Object.assign(this.box.style, { top: y0 - r.top + 'px', height: Math.max(2, y1 - y0) + 'px' }); this.box.hidden = false;
      const s = this.span(d.y, e.clientY); this.pv = s; this.render();
    });
    T.addEventListener('pointerup', e => end(e, true));
    T.addEventListener('pointercancel', e => end(e, false));
    T.addEventListener('lostpointercapture', e => { if (d && d.on) end(e, false); });
    T.addEventListener('contextmenu', e => { const row = e.target.closest('.mn'); if (!row) return; e.preventDefault();
      this.fi = +row.dataset.i; this.menu(this.rows[this.fi][0], e.clientX, e.clientY); });
    el.addEventListener('keydown', e => {
      if (e.target === this.qEl) return;
      const k = e.key, nd = this.rows[this.fi] && this.rows[this.fi][0];
      if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); if (d) { end(e, false); return; } if (v.menuEl) { v.closeMenu(); this.focusRow(); return; }
        this.close(); return; }
      if (!e.target.closest('.mtr') || e.ctrlKey || e.metaKey || e.altKey) { if (k === 'Escape') e.stopPropagation(); return; }
      let h = true;
      if (k === 'ArrowDown' || k === 'ArrowUp' || k === 'Home' || k === 'End') {
        const to = k === 'Home' ? 0 : k === 'End' ? this.rows.length - 1 : this.fi + (k === 'ArrowDown' ? 1 : -1);
        if (e.shiftKey && (k === 'ArrowDown' || k === 'ArrowUp')) {
          if (this.anchor == null) this.anchor = this.fi;
          const i = Math.min(Math.max(to, 0), this.rows.length - 1);
          this.only(this.rows.slice(Math.min(this.anchor, i), Math.max(this.anchor, i) + 1).map(r => r[0])); this.focusRow(i); }
        else { this.anchor = null; this.focusRow(to); }
      } else if (k === 'ArrowRight' && nd) {   // open it; open: its first child
        if (nd.kids.length && !this.hits && !this.open.has(nd.g.id)) this.fold(nd, false); else if (nd.kids.length) this.fi++;
        this.focusRow(); }
      else if (k === 'ArrowLeft' && nd) { if (nd.kids.length && !this.hits && this.open.has(nd.g.id)) this.fold(nd, true);
        else if (nd.up) this.fi = this.rows.findIndex(([x]) => x === nd.up); this.focusRow(); }
      else if (k === 'Enter' && nd) v.goScope(nd.g);
      else if (k === ' ' && nd) { this.toggle(nd); this.focusRow(); }
      else if (k === '/') this.qEl.focus();
      else if (k === 't') this.locate();
      else if (k === 'ContextMenu' && nd) { const b = this.rowAt(this.fi).getBoundingClientRect(); this.menu(nd, b.left + 20, b.bottom); }
      else h = false;
      if (h) e.preventDefault();
    });
  }
  matches() {
    if (!this.hits || !this.hits.length) {
      this.v.toast(this.q.trim() ? `no module matches "${this.q.trim()}"` : 'type a part of a module\'s name first'); return; }
    this.only(this.hits);
  }
  // the right button on a module: go there, Only it (or with it, or without it), fold its subtree in the tree, copy the path
  menu(nd, cx, cy) {
    const v = this.v, o = v.only, { sel, inn } = v.onlyIds(), g = nd.g, on = !!o && sel.has(g.id), via = !!o && !on && inn.has(g.id);
    v.closeMenu();
    const b = (m, label, key) => `<button type="button" role="menuitem" data-mm="${m}"><span>${esc(label)}</span>` +
      `${key ? `<span class="kk">${key}</span>` : ''}</button>`;
    const up = via && g.anc.map(id => v.M.groups[id]).find(x => sel.has(x.id));
    const el = document.createElement('div'); el.className = 'wv-menu'; el.setAttribute('role', 'menu');
    el.innerHTML = `<div class="mh">${esc(g.path)}</div>` + b('go', 'Go to waves', 'Enter') + '<hr>' + b('only', 'Only this subtree') +
      (o && !on && !via ? b('add', 'Also include this subtree', 'ctrl+click') : '') + (on ? b('rm', 'Remove this subtree from Only', 'Space') : '') +
      (via ? `<div class="mh">included by ${esc(up ? up.path : 'its module')}</div>` : '') + '<hr>' +
      (nd.kids.length ? b('open', 'Expand subtree') + b('shut', 'Collapse subtree') : '') + b('copy', 'Copy scope path');
    v.root.append(el); v.menuEl = el;
    const box = el.getBoundingClientRect();
    el.style.left = Math.max(4, Math.min(cx, innerWidth - box.width - 4)) + 'px'; el.style.top = Math.max(4, Math.min(cy, innerHeight - box.height - 4)) + 'px';
    el.addEventListener('click', e => {
      const m = e.target.closest('button[data-mm]'); if (!m) return; const a = m.dataset.mm; v.closeMenu();
      if (a === 'go') v.goScope(g);
      else if (a === 'only') this.only([nd]);
      else if (a === 'add' || a === 'rm') this.toggle(nd);
      else if (a === 'open' || a === 'shut') this.subtree(nd, a === 'open');
      else if (a === 'copy') v.copyText(g.path);
      this.focusRow();
    });
    el.addEventListener('keydown', e => {
      const bs = [...el.querySelectorAll('button')], k = bs.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); v.closeMenu(); this.focusRow(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault();
        bs[(k + (e.key === 'ArrowDown' ? 1 : -1) + bs.length) % bs.length]?.focus(); }
    });
    el.addEventListener('contextmenu', e => e.preventDefault());
    const off = v.offMenu = e => { if (!el.contains(e.target)) v.closeMenu(); };
    setTimeout(() => { if (v.menuEl !== el) return; document.addEventListener('pointerdown', off, { capture: true, signal: v.ac.signal });
      window.addEventListener('blur', off, { signal: v.ac.signal }); }, 0);
    (el.querySelector('button') || el).focus({ preventScroll: true });
  }
}
