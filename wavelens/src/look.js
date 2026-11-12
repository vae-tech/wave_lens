/* wavelens/src/look.js — what a viewer keeps in this browser (rows, paint, look) and its gaps and cycles. */

// the bar as this browser keeps it (localStorage wavelens.bar, one for every viewer of every page here; VS Code: one for every tab):
// {v: 1, layout, compact, mine, strip, stripAt}. barKept: what of it is good ({} for nothing, or nothing good); barKeep(v, part): a part changed
// (undefined: taken out), the rest kept, the other viewers of this page follow at once (other pages: the storage event)
const BARKEY = 'wavelens.bar';
const barRaw = () => { try { const o = JSON.parse(localStorage.getItem(BARKEY) || 'null'); return o && typeof o === 'object' && o.v === 1 ? o : null; }
  catch (e) { return null; } };
const barKept = () => { const o = barRaw(), out = {}; if (!o) return out;
  if ('layout' in o) out.layout = toolLines(o.layout);
  if ('compact' in o) out.compact = compactOf(o.compact);
  if (typeof o.strip === 'boolean') out.strip = o.strip;
  if ('stripAt' in o) out.stripAt = stripAt(o.stripAt);
  out.mine = toolLines(o.mine); return out; };
const barKeep = (v, part) => {
  const o = Object.assign({}, barRaw() || {}, { v: 1 });
  for (const [k, x] of Object.entries(part)) { if (x === undefined) delete o[k]; else o[k] = x; }
  try { if (Object.keys(o).length > 1) localStorage.setItem(BARKEY, JSON.stringify(o)); else localStorage.removeItem(BARKEY); } catch (e) { /* not kept */ }
  for (const w of VIEWS) if (w !== v && w.root.isConnected) w.barReload();
};
G.addEventListener('storage', e => { if (e.key === BARKEY || e.key === null) for (const w of VIEWS) if (w.root.isConnected) w.barReload(); });
Object.assign(WaveView.prototype, {
  loadRows() {
    let o = {};
    try { o = JSON.parse(localStorage.getItem(this.rowsKey) || '{}') || {}; } catch (e) { /* no storage */ }
    this.hiddenRows = new Set(Array.isArray(o.hidden) ? o.hidden : []); this.ugroups = groupNorm(o.groups);
    this.bitsOpen = new Set(Array.isArray(o.bits) ? o.bits.map(String) : []);
    if (Array.isArray(o.dups)) this.setDups(o.dups);
    this.deltas = o.deltas !== undefined ? !!o.deltas : (this.M.measures || []).length > 0;   // a page with measurements: their Δ shown
    for (const [p, n] of Object.entries(o.analog || {})) { const r = this.sigPool().find(x => x.type === 'sig' && x.full === p);
      if (r) { if (!('analog0' in r)) r.analog0 = r.analog; r.analog = n || false; this.analogs.set(p, n); }
      else if (p.startsWith('ƒ ')) this.analogs.set(p, n); }
    for (const [p, rx] of Object.entries(o.radix || {})) { const r = this.sigPool().find(x => x.type === 'sig' && x.full === p);
      if (r && isRadix(rx)) { r.radix0 = r.radix; r.radix = rx; if (r.dupOf) r.enum = undefined; this.radixes.set(p, rx); }
      else if (!r && p.startsWith('ƒ ') && isRadix(rx)) this.radixes.set(p, rx); }   // an expression's row (sva.js): it takes it when it is made
    // a colour of a copy not here (a copy's bits removed before B-31 left theirs: the next copy of that name took them): out, quietly
    const stale = [...this.painted.keys()].filter(k => { const c = this.copyOfKey(k); return c && !this.dups.has(c); });
    if (stale.length) { stale.forEach(k => this.painted.delete(k)); this.savePaint(); }
  },
  // Duplicate: the rows of the model and the copies: where a name, a highlight or a run of selected rows is looked for
  sigPool() { return this.dups.size ? [...this.M.rows, ...this.dups.values()] : this.M.rows; },
  // and the bits of the buses shown bit by bit: where a highlight, Paint and the menu's rows are looked for (a bit highlighted is one)
  rowPool() {
    const p = this.sigPool();
    return this.bitsOpen.size ? p.flatMap(r => (r.type === 'sig' && this.bitsOpen.has(r.full) && isVec(r) ? [r, ...this.bitsOf(r)] : [r])) : p;
  },
  // the copy a key of the colours names ("PADDR#2", "PADDR[7:4]", a bit of one: "PADDR#2[3]"), or null: none (a signal, a bit of one)
  copyOfKey(k) {
    for (const c of [k, typeof k === 'string' && /\[\d+\]$/.test(k) ? k.replace(/\[\d+\]$/, '') : null]) {
      const id = c && (dupId(c) || sliceId(c));
      if (id && this.M.rows.some(r => r.type === 'sig' && r.full === id.of) && !this.M.rows.some(r => r.full === c)) return c; }
    return null;
  },
  withDups(rows) { return this.dups.size ? rows.flatMap(r => (this.dupsBy.has(r) ? [r, ...this.dupsBy.get(r)] : [r])) : rows; },
  dupPut(base, n) {
    const d = dupRow(base, n), list = this.dupsBy.get(base) || [];
    this.dupsBy.set(base, [...list, d].sort((a, b) => a.dupN - b.dupN)); this.dups.set(d.full, d); this.rowsStale = true; this.ugMemo = null; return d;
  },
  // a copy of a row (a signal, its row in your group, a copy), as that row looks now; made from a row of your group it stays beside it
  // -> the copy, null: not a signal
  dupAdd(r) {
    const from = r.orig || r, base = rowBase(r); if (base.type !== 'sig' || !base.tr || base.bit != null || base.same) return null;
    const d = this.dupPut(base, Math.max(1, ...(this.dupsBy.get(base) || []).map(x => x.dupN)) + 1);
    if (this.radixes.has(from.full)) this.setRadix(d, this.radixes.get(from.full), true);
    if (this.analogs.has(from.full)) this.setAnalog(d, this.analogs.get(from.full), true);
    if (this.painted.has(from.full)) { this.painted.set(d.full, this.painted.get(from.full)); this.savePaint(); }
    const g = r.ug && this.ugroups.find(x => x.name === r.ug.name);
    if (g) g.signals.splice(g.signals.indexOf(from.full) + 1, 0, d.full);
    return d;
  },
  // a slice [msb:lsb] of a bus (a signal, a copy's, its row in your group) as a row of its own under it; the one there is again -> the row,
  // or why not
  // why bits [msb:lsb] of row r make no slice (a text), or null: they do
  sliceWhy(r, msb, lsb) {
    const o = r.orig || r, base = rowBase(r);
    if (o.slice) return 'slice the bus, not a slice';
    if (!isVec(base) || base.bit != null || base.same) return 'not a bus';
    if (!(msb >= lsb && msb < base.width)) return `[${msb}:${lsb}] is not in its ${base.width} bits (msb first, lsb 0)`;
    return null;
  },
  dupSlice(r, msb, lsb) {
    const why = this.sliceWhy(r, msb, lsb); if (why) return why;
    const base = rowBase(r), id = `${base.full}[${msb}:${lsb}]`; if (this.dups.has(id)) return this.dups.get(id);
    const d = sliceRow(base, msb, lsb), list = this.dupsBy.get(base) || [];
    this.dupsBy.set(base, [...list, d].sort((a, b) => a.dupN - b.dupN || (b.slice ? b.slice[0] : 0) - (a.slice ? a.slice[0] : 0)));
    this.dups.set(d.full, d); this.rowsStale = true; this.ugMemo = null; return d;
  },
  // a copy gone, and what was its (its bits' too): its colour, its radix; a bookmark on it goes to its signal, on its bit i to the bus's
  // bit i (a slice's: lsb + i). What still names its rows (the highlight, the run …): onlyFix in dupDone
  dupDrop(d) {
    const base = d.dupOf, f = d.full, list = this.dupsBy.get(base).filter(x => x !== d);
    const mine = p => typeof p === 'string' && (p === f || p.startsWith(f + '['));
    const bit = p => { const i = /^\[(\d+)\]$/.exec(p.slice(f.length)); return i && d.slice ? `[${d.slice[1] + +i[1]}]` : p.slice(f.length); };
    const to = p => (p === f ? base.full : mine(p) ? base.full + bit(p) : p);
    if (list.length) this.dupsBy.set(base, list); else this.dupsBy.delete(base);
    this.dups.delete(f); this.bitsOpen.delete(f);
    for (const m of [this.radixes, this.analogs, this.painted]) for (const p of [...m.keys()]) if (mine(p)) m.delete(p);
    for (const p of [...this.hiddenRows]) if (mine(p)) this.hiddenRows.delete(p);   // its bits hidden too
    for (const g of this.ugroups) g.signals = g.signals.filter(p => p !== f);
    for (const b of this.bms) b.signal = to(b.signal);
    for (const m of this.umarks) { m.signal = to(m.signal); m.dsignal = to(m.dsignal); }
    for (const s of this.spans) if (s.signals) s.signals = s.signals.map(to);
    this.picks.delete(d); this.selRun.delete(d);
    if (this.sel && (this.sel === d || this.sel.of === d || (this.sel.orig && this.sel.orig === d))) this.sel = base;
    if (this.rangeRow === d) this.rangeRow = base;
    this.rowsStale = true; this.ugMemo = null;
  },
  dupDone() { this.allRows(); this.onlyFix(); this.savePaint(); this.saveBookmarks(); this.saveRows(); if (this.cmp) this.cmpMarks(); this.renderNames();
    this.renderNotes(); this.draw(); },
  // the copies a state names, none other -> the ones of signals these waves have not got
  setDups(ids) {
    const want = (Array.isArray(ids) ? ids : []).map(String), bad = [];
    for (const d of [...this.dups.values()]) if (!want.includes(d.full)) this.dupDrop(d);
    for (const id of want) {
      const sl = !this.dups.has(id) && sliceId(id), sb = sl && this.M.rows.find(r => r.type === 'sig' && r.tr && r.full === sl.of);
      if (sl) { if (!(sb && typeof this.dupSlice(sb, sl.msb, sl.lsb) === 'object')) bad.push(id); continue; }
      const p = dupId(id), base = p && !this.dups.has(id) && this.M.rows.find(r => r.type === 'sig' && r.tr && r.full === p.of);
      if (base) this.dupPut(base, p.n); else if (!this.dups.has(id)) bad.push(id); }
    return bad;
  },
  saveRows() {
    try {
      if (this.radixes.size || this.hiddenRows.size || this.analogs.size || this.ugroups.length || this.bitsOpen.size || this.dups.size || this.deltas ||
        (this.M.measures || []).length) {   // (the Δ off on a page with measurements: kept off)
        localStorage.setItem(this.rowsKey,
        JSON.stringify({ radix: Object.fromEntries(this.radixes), hidden: [...this.hiddenRows], analog: Object.fromEntries(this.analogs),
          groups: this.groupList(), bits: [...this.bitsOpen], dups: [...this.dups.keys()], deltas: this.deltas }));
      } else localStorage.removeItem(this.rowsKey);
    } catch (e) { /* private mode */ }
  },
  loadPaint() {
    try { for (const [k, c] of Object.entries(JSON.parse(localStorage.getItem(this.paintKey) || '{}'))) if (colorOk(c)) this.painted.set(k, c); }
    catch (e) { /* no storage */ }
  },
  // the edge style of the waves ("auto" | "wavedrom" | "questa" | "square"; null: the settings' again), from the bar's list;
  // kept in this browser. Signals with a style of their own keep it
  setStyle(name) {   // the bar's own layer: kept only when it differs from the settings (their style comes back with them)
    const base = settings(GLOBAL, this.M.cfg, this.opts).style;
    if (hasKey(EDGES, name) && name !== base) this.local.style = name; else delete this.local.style;
    this.saveLook();
    this.S.style = this.local.style || settings(GLOBAL, this.M.cfg, this.opts).style;
    if (this.wsEl) this.wsEl.value = this.S.style;
    this.draw(); this.settingsChanged(); return this;
  },
  loadLook() { try { const o = JSON.parse(localStorage.getItem(this.lookKey) || '{}'), L = {}; if (o && hasKey(EDGES, o.style)) L.style = o.style;
      if (o && o.gap && typeof o.gap === 'object') L.gap = o.gap;
      if (o && o.cyc && typeof o.cyc === 'object') L.cyc = o.cyc;
      if (o && (typeof o.maxHeight === 'string' || typeof o.maxHeight === 'number')) L.maxHeight = o.maxHeight;
      if (o && typeof o.toolsFolded === 'boolean') L.toolsFolded = o.toolsFolded;
      if (o && typeof o.cursorSnap === 'number' && o.cursorSnap >= 0) L.cursorSnap = o.cursorSnap;
      if (o && Array.isArray(o.toolsHidden)) L.toolsHidden = toolNames(o.toolsHidden);
      const B = barKept();   // the bar's arrangement and its short form: this browser's, one for every viewer of it
      if (B.layout !== undefined) L.toolLayout = B.layout;
      if (B.compact !== undefined) L.toolsCompact = B.compact;
      if (B.strip !== undefined) L.cursorStrip = B.strip;
      if (B.stripAt !== undefined) L.cursorStripAt = B.stripAt;
      return L; } catch (e) { return {}; } },
  // where the rows scroll: 'window' (in the viewer, maxHeight high: height, else the settings', else 80vh; the bar above
  // them) or 'page' (with the page; the bar sticks to the top while the rows go by); null: the settings' again. Kept in
  // this browser (the bar's own layer), as the edge style
  setScroll(mode, height) {
    const base = settings(GLOBAL, this.M.cfg, this.opts).maxHeight, win = base != null && base !== '';
    if (mode === 'page') { if (win) this.local.maxHeight = ''; else delete this.local.maxHeight; }
    else if (mode === 'window') { const h = height ?? (win ? base : '80vh');
      if (win && h === base) delete this.local.maxHeight; else this.local.maxHeight = h; }
    else delete this.local.maxHeight;
    this.saveLook(); this.S.maxHeight = 'maxHeight' in this.local ? this.local.maxHeight : base;   // this setting only (restyle: the sort too)
    this.layoutShow(); this.draw(); this.settingsChanged(); return this;
  },
  // the bar's tools folded to its title line (true) or open; null: the settings' again
  setTools(fold) {
    const base = !!settings(GLOBAL, this.M.cfg, this.opts).toolsFolded;
    if (fold == null || !!fold === base) delete this.local.toolsFolded; else this.local.toolsFolded = !!fold;
    this.toolsPeek = false;   // (/ had opened them for the find)
    this.saveLook(); this.S.toolsFolded = 'toolsFolded' in this.local ? this.local.toolsFolded : base;
    this.layoutShow(); this.draw(); return this;
  },
  // the bar's short form (toolsCompact): 'auto' (when the bar is narrower than BAR_SHORT px), true (always), false (never); null: the
  // settings' again. Kept in this browser for every viewer of it (wavelens.bar), as the arrangement; o.only: this viewer only (a
  // state loaded, a command)
  setToolsCompact(c, o = {}) {
    const base = compactOf(settings(GLOBAL, this.M.cfg, this.opts).toolsCompact), want = c == null ? base : compactOf(c);
    if (want === base) delete this.local.toolsCompact; else this.local.toolsCompact = want;
    if (!o.only) barKeep(this, { compact: want === base ? undefined : want });
    this.S.toolsCompact = want; this.layoutShow(); this.draw(); this.settingsChanged(); return this;
  },
  // the bar's arrangement (toolLayout, toolLines: lines of group labels; null: the default order) put on the bar. Kept in this
  // browser for every viewer of it (wavelens.bar; o.mine: as Mine, the user's own); o.only: this viewer only (a state loaded, a
  // command, a page's edits: the browser's stays as it is)
  setToolLayout(L, o = {}) {
    const base = toolLines(settings(GLOBAL, this.M.cfg, this.opts).toolLayout), want = L === undefined ? base : toolLines(L);
    if (JSON.stringify(want) === JSON.stringify(base)) delete this.local.toolLayout; else this.local.toolLayout = want;
    if (!o.only) barKeep(this, Object.assign({ layout: 'toolLayout' in this.local ? want : undefined }, o.mine && want ? { mine: want } : {}));
    this.S.toolLayout = 'toolLayout' in this.local ? this.local.toolLayout : base;
    this.arrangeTools(); this.layoutShow(); this.draw(); this.settingsChanged(); return this;
  },
  // the cursor and the edges in the strip over the time axis (cursorStrip) or in the bar's lines; null: the settings' again. Kept
  // in this browser for every viewer of it (wavelens.bar), as the arrangement; o.only: this viewer only
  setCursorStrip(on, o = {}) {
    const base = settings(GLOBAL, this.M.cfg, this.opts).cursorStrip !== false, want = on == null ? base : !!on;
    if (want === base) delete this.local.cursorStrip; else this.local.cursorStrip = want;
    if (!o.only) barKeep(this, { strip: want === base ? undefined : want });
    this.S.cursorStrip = want; if (!want) this.stripLock(true);
    this.arrangeTools(); this.layoutShow(); this.draw(); this.settingsChanged(); return this;
  },
  // where the strip stands over the waves (cursorStripAt: 0 left .. 1 right, "center" …); null: the settings' again. Kept as above
  setStripAt(p, o = {}) {
    const base = stripAt(settings(GLOBAL, this.M.cfg, this.opts).cursorStripAt), want = p == null ? base : stripAt(p);
    if (want === base) delete this.local.cursorStripAt; else this.local.cursorStripAt = want;
    if (!o.only) barKeep(this, { stripAt: want === base ? undefined : want });
    this.S.cursorStripAt = want; this.stripShow(); this.settingsChanged(); return this;
  },
  // the strip's 🔒: locked (true: ⠿ gone, nothing moves it) or not; not kept (a page opened again: locked)
  stripLock(lock) {
    this.stripOpen = !lock; const a = this.root.querySelector('.bar .axs'); if (!a) return this;
    a.classList.toggle('open', !lock); const b = a.querySelector('[data-act=axlock]');
    if (b) { b.setAttribute('aria-pressed', !lock); b.setAttribute('aria-label', lock ? 'unlock the strip: ⠿ moves it' : 'lock the strip where it is'); }
    const g = a.querySelector('.axg');   // (⠿ in focus when it goes: the focus to 🔒)
    if (g) { if (lock && document.activeElement === g && b) b.focus(); g.hidden = lock; }
    return this;
  },
  // the strip shown (on, a group of it shown) or not, where it stands
  stripShow() {
    const a = this.root.querySelector('.bar .axs'); if (!a) return this;
    const gs = [...a.querySelectorAll('.axb > .tg')].filter(g => !g.hidden && !g.classList.contains('off'));
    a.hidden = !this.S.cursorStrip || !gs.length; a.style.setProperty('--axp', stripAt(this.S.cursorStripAt)); return this;
  },
  // wavelens.bar changed (another viewer of this page, another page of this browser, another tab of VS Code): its arrangement,
  // short form and the tools' folding and groups again, nothing written; undo starts from it (no step of its own)
  barReload() {
    const L = this.loadLook(), base = settings(GLOBAL, this.M.cfg, this.opts);
    for (const k of ['toolLayout', 'toolsCompact', 'toolsHidden', 'toolsFolded', 'cursorStrip', 'cursorStripAt']) {
      if (k in L) this.local[k] = L[k]; else delete this.local[k]; }
    this.S.cursorStrip = 'cursorStrip' in this.local ? this.local.cursorStrip : base.cursorStrip !== false;
    this.S.cursorStripAt = 'cursorStripAt' in this.local ? this.local.cursorStripAt : stripAt(base.cursorStripAt);
    this.S.toolLayout = 'toolLayout' in this.local ? this.local.toolLayout : toolLines(base.toolLayout);
    this.S.toolsCompact = 'toolsCompact' in this.local ? this.local.toolsCompact : compactOf(base.toolsCompact);
    this.S.toolsHidden = 'toolsHidden' in this.local ? this.local.toolsHidden : toolNames(base.toolsHidden);
    this.S.toolsFolded = 'toolsFolded' in this.local ? this.local.toolsFolded : !!base.toolsFolded;
    this.arrangeTools(); this.layoutShow(); this.draw();
    if (this.undoCur != null && !this.undoing) this.undoCur = this.undoPart();
    return this;
  },
  // where a group goes (its line element, the group to go before; null: the end of it): the line of the arrangement that names it
  // (made when missing), before the next one it names there; a group it does not name (or no arrangement): its line of TOOL_LINES
  // (else "more"), after the last of the groups before it there
  toolSlot(group) {
    const tools = this.root.querySelector('.bar .tools'), L = toolLines(this.S.toolLayout), K = Object.keys(TOOL_LINES);
    const lnOf = i => ['time', 'find', 'rows'][i] || 'l' + i;
    const line = name => { let ln = tools.querySelector(`:scope > .tln[data-ln="${name}"]`);
      if (!ln) { const order = ['time', 'find', 'rows', 'l3', 'l4', 'l5', 'more'], i = order.indexOf(name), at = [...tools.querySelectorAll(':scope > .tln')]
        .find(x => order.indexOf(x.dataset.ln) > i || order.indexOf(x.dataset.ln) < 0);
        tools.insertAdjacentHTML('beforeend', toolLine(name, '')); ln = tools.lastElementChild; if (at) tools.insertBefore(ln, at); }
      return ln; };
    const li = L ? L.findIndex(l => l.includes(group)) : -1;
    const here = g => [...this.root.querySelectorAll('.bar .tools .tg')].find(x => x.dataset.tg === g);
    if (li >= 0) { const after = L[li].slice(L[li].indexOf(group) + 1).map(here).find(x => x && x.parentElement === line(lnOf(li))) || null;
      return [line(lnOf(li)), after]; }
    const ln = line(TOOL_LINES[group] || 'more'), i = K.indexOf(group);
    const kids = [...ln.children].filter(x => x.classList.contains('tg') && x.dataset.tg !== group);
    if (i < 0) return [ln, null];
    const prev = kids.filter(x => { const j = K.indexOf(x.dataset.tg); return j >= 0 && j < i && TOOL_LINES[x.dataset.tg] === TOOL_LINES[group]; }).pop();
    return [ln, prev ? prev.nextElementSibling : kids.find(x => K.indexOf(x.dataset.tg) > i) || null];
  },
  // every group to its place of the arrangement (none: the default order); a group moves only when it is not there already (the
  // focus in it stays), the floating find stays where it floats; the lines the arrangement added and left empty go
  arrangeTools() {
    const tools = this.root.querySelector('.bar .tools'); if (!tools) return this;
    // the strip over the time axis: the cursor and the edges in it (in that order) out of the lines, or back in them below
    const ax = this.root.querySelector('.bar .axs .axb');
    if (ax) {
      if (this.S.cursorStrip) for (const n of STRIP_GROUPS) { const g = [...tools.querySelectorAll(':scope > .tln > .tg')].find(x => x.dataset.tg === n);
        if (g) { g.classList.remove('rs', 're', 'end'); ax.appendChild(g); } }
      else for (const g of [...ax.querySelectorAll(':scope > .tg')]) tools.querySelector(':scope > .tln').appendChild(g);
    }
    const gs = [...tools.querySelectorAll(':scope > .tln > .tg')].filter(g => !g.classList.contains('float')), L = toolLines(this.S.toolLayout) || [];
    const named = L.flat(), by = new Map(gs.map(g => [g.dataset.tg, g]));
    for (const l of L) { let prev = null;   // the lines of the arrangement, each in its order
      for (const n of l) { const g = by.get(n); if (!g) continue;
        const ln = this.toolSlot(n)[0], before = prev ? prev.nextElementSibling : ln.firstElementChild;
        if (before !== g) ln.insertBefore(g, before);
        prev = g; } }
    const rest = [...Object.keys(TOOL_LINES).filter(n => by.has(n) && !named.includes(n)),   // the others where TOOL_LINES has them
      ...gs.map(g => g.dataset.tg).filter(n => !named.includes(n) && !hasKey(TOOL_LINES, n))];
    for (const n of rest) { const g = by.get(n), [ln, before] = this.toolSlot(n);
      if (before !== g && !(g.parentElement === ln && g.nextElementSibling === before)) ln.insertBefore(g, before); }
    for (const ln of tools.querySelectorAll(':scope > .tln')) if (/^l\d$/.test(ln.dataset.ln) && !ln.children.length) ln.remove();
    return this.stripShow();
  },
  // ⚙ Snap to edges: a click puts the cursor on a near edge (cursorSnap px: the settings', else 8) or never (0). Kept in this browser
  setSnap(on) {
    const base = settings(GLOBAL, this.M.cfg, this.opts).cursorSnap, want = on ? (base > 0 ? base : 8) : 0;
    if (want === base) delete this.local.cursorSnap; else this.local.cursorSnap = want;
    this.saveLook(); this.S.cursorSnap = want; this.barSync(true); return this;
  },
  // the bar's tool groups left out (their labels: "cursor", "find", "go to" …; ⚙ Tools in the bar, the right button on the bar); null:
  // the settings' again. Kept in this browser, as the folding of the tools; / and ctrl+F still float the find over the waves
  setToolsHidden(list) {
    const base = toolNames(settings(GLOBAL, this.M.cfg, this.opts).toolsHidden), want = list == null ? base : toolNames(list);
    if (list == null || want.join() === base.join()) delete this.local.toolsHidden; else this.local.toolsHidden = want;
    this.saveLook(); this.S.toolsHidden = want; this.layoutShow(); this.draw(); return this;
  },
  // the bar's tool groups there now (a group made only while it has something: compare), in their order
  toolGroups() {
    return [...new Set([...this.root.querySelectorAll('.bar .tools .tg, .bar .axs .tg')].filter(g => !g.hidden).map(g => g.dataset.tg).filter(Boolean))];
  },
  // the classes and the buttons of the two: the rows' scroll box, the sticky bar's height (the canvas and the names' header under it)
  layoutShow() {
    const S = this.S, r = this.root, win = S.maxHeight != null && S.maxHeight !== '', fold = !!S.toolsFolded && !this.toolsPeek;
    r.classList.toggle('wv-scroll', win); r.classList.toggle('wv-tools-folded', fold);
    const sp = r.querySelector('.bar [data-act=spage]');   // a page that is not all in itself, a dump opened in it: Save keeps the view
    if (sp) sp.hidden = S.savePage === false || !!this.opts.dumpSrc || !!PAGE.why;
    const sv = r.querySelector('.bar [data-act=svload]'); if (sv) sv.hidden = !r.querySelector('.bar button[data-sv=load]');
    if (win) r.style.setProperty('--wv-max-h', typeof S.maxHeight === 'number' ? S.maxHeight + 'px' : String(S.maxHeight));
    const t = r.querySelector('.bar button[data-act=tools]');
    if (t) { t.textContent = fold ? '▾ tools' : '▴'; t.setAttribute('aria-expanded', !fold);
      t.setAttribute('aria-label', fold ? 'open the tools' : 'fold the tools'); }
    // the tool groups left out (toolsHidden); a line with none left gone; one whose only group floats (the find) out of the flow (T-19)
    const H = new Set(toolNames(S.toolsHidden));
    for (const ln of r.querySelectorAll('.bar .tools .tln')) {
      const gs = [...ln.children].filter(g => g.classList.contains('tg') && !g.hidden);
      const on = gs.filter(g => !g.classList.toggle('off', H.has(g.dataset.tg)));
      const fl = gs.some(g => g.classList.contains('float')), still = on.filter(g => !g.classList.contains('float'));
      ln.hidden = !still.length && !fl; ln.classList.toggle('fl', !still.length && fl);
    }
    for (const g of r.querySelectorAll('.bar .axs .tg')) g.classList.toggle('off', H.has(g.dataset.tg));
    this.stripShow();
    // a group's ⋯ (a plugin's group with a .more gets one) and the menus' headers: data-own, the controls they hold (the tests open them)
    for (const g of r.querySelectorAll('.bar .tg')) { const m = g.querySelector(':scope > .more');
      if (m && !g.querySelector(':scope > .mx')) g.insertAdjacentHTML('beforeend', '<button type="button" class="mx" data-act="more" aria-haspopup="true" ' +
        `aria-expanded="false" aria-label="more of ${esc(g.dataset.tg || '')}">⋯</button>`); }
    const owns = box => [...new Set([...box.querySelectorAll('[data-act], [data-svj], input:not([type=file]), select')].map(x => x.dataset.act ||
      (x.dataset.svj != null ? 'svj' : x.classList[0])).filter(Boolean))].join(' ');
    for (const h of r.querySelectorAll('.bar [data-pop]:not(.bpop)')) { const box = r.querySelector(`.bar .bpop[data-pop="${h.dataset.pop}"]`);
      if (box) h.dataset.own = owns(box); }
    for (const x of r.querySelectorAll('.bar .tg > .mx')) x.dataset.own = owns(x.parentElement.querySelector(':scope > .more'));
    this.barSync(true); this.barFit();
  },
  // the short form (toolsCompact; 'auto': a bar narrower than BAR_SHORT px), the rows of the tools marked (rs: the first group of a
  // visual row, re: the last; T-15) and the filters of the head folded into one when the readout would be cut short; on a
  // resize of the bar too (the observer, a frame later: its own changes are not a loop)
  barFit() {
    const bar = this.root.querySelector('.bar'); if (!bar || !bar.clientWidth) return;   // not laid out (a closed card): when it is
    const c = compactOf(this.S.toolsCompact), short = c === true || (c === 'auto' && bar.clientWidth < BAR_SHORT);
    if (bar.classList.contains('short') !== short) { this.popClose(); bar.classList.toggle('short', short); }
    for (let pass = 0; pass < 3; pass++) {   // the marks change the groups' widths: again until the rows stand
      let moved = false;
      for (const ln of bar.querySelectorAll('.tools .tln')) {
        const gs = [...ln.children].filter(g => g.classList.contains('tg') && g.offsetParent && !g.classList.contains('float'));
        gs.forEach((g, i) => {
          const rs = i === 0 || g.offsetTop > gs[i - 1].offsetTop + 2, re = i === gs.length - 1 || gs[i + 1].offsetTop > g.offsetTop + 2;
          if (g.classList.contains('rs') !== rs || g.classList.contains('re') !== re) moved = true;
          g.classList.toggle('rs', rs); g.classList.toggle('re', re); g.classList.toggle('end', re); });
      }
      if (!moved) break;
    }
    // the chips: folded into "N filters ▾" when, beside them, the readout would have less than 260 px and be cut (or not fit at all:
    // the head would wrap); the room worked out from the widths of the rest of the head, so folding does not undo itself; a narrow
    // head (the readout on a row of its own) always folds them
    const chips = bar.querySelector('.chips'), cn = bar.querySelector('.chipn'), rd = bar.querySelector('.rd'), cur = bar.querySelector('.cur');
    if (chips && cn && rd && cur) {
      const head = rd.parentElement, hs = getComputedStyle(head), n = [...chips.children].filter(x => !x.hidden).length;
      const folded = chips.classList.contains('fold');
      const wide = getComputedStyle(rd).flexBasis !== '100%', gap = parseFloat(hs.columnGap) || 0, ext = e => { const c = getComputedStyle(e);
        return e.getBoundingClientRect().width + parseFloat(c.marginLeft) + parseFloat(c.marginRight) + gap; };
      const rest = [...head.children].filter(e => e !== rd && e !== chips && e !== cn && e.getClientRects().length).reduce((t, e) => t + ext(e), 0);
      const room = head.clientWidth - parseFloat(hs.paddingLeft) - parseFloat(hs.paddingRight) - rest - (n ? chips.offsetWidth + gap : 0);
      // (a narrow head: always folded, so the head keeps its rows with or without filters)
      const fold = wide ? n > 1 && room < 260 && (cur.scrollWidth > room || room < parseFloat(getComputedStyle(rd).flexBasis)) : n > 0;
      if (fold !== folded) { if (!fold) this.popClose(chips); chips.classList.toggle('fold', fold); }
      cn.hidden = !fold; if (fold) cn.textContent = `${n} filter${n === 1 ? '' : 's'} ▾`;
    }
    if (this.arrDlg) this.arrPlace();
  },
  // the bar's buttons by the viewer's state (disabled, pressed, the radix of the selection), when it changed (force: anyway)
  barSync(force) {
    if (!this.bar) return;
    const st = barState(this), key = JSON.stringify(st); if (!force && key === this.barKey) return; this.barKey = key;
    const q = s => this.root.querySelector('.bar ' + s), set = (s, k, val) => { const b = q(s); if (b) { if (k === 'disabled') b.disabled = val;
      else b.setAttribute(k, val); } };
    set('[data-act=zlast]', 'disabled', st.zlast); set('[data-act=zrange]', 'disabled', st.zrange);
    for (const a of ['mprev', 'mnext', 'mlist']) set(`[data-act=${a}]`, 'disabled', st.marks);
    set('[data-act=cycles]', 'aria-pressed', st.cyc); set('[data-act=cycles]', 'disabled', st.cycOff && !st.cyc);
    set('[data-act=gaps]', 'aria-pressed', st.gaps);
    const rx = q('select.rx'); if (rx && document.activeElement !== rx) { rx.disabled = st.rxOff; rx.value = st.rx; }
    const m = q('.bpop.wv-gear'); if (!m) return;   // ⚙: its ticks
    const tick = (b, on) => { b.setAttribute('aria-checked', on); const c = b.querySelector('.ck'); if (c) c.textContent = on ? '✓' : ''; };
    const h = document.documentElement, th = THEMES.includes(h.dataset.theme) ? h.dataset.theme : 'auto', cp = compactOf(this.S.toolsCompact);
    for (const b of m.querySelectorAll('[data-act=theme]')) tick(b, b.dataset.v === th);
    for (const b of m.querySelectorAll('[data-act=compact]')) tick(b, b.dataset.v === (cp === true ? 'on' : cp === false ? 'off' : 'auto'));
    tick(m.querySelector('[data-act=scroll]'), this.S.maxHeight != null && this.S.maxHeight !== '');
    tick(m.querySelector('[data-act=snap]'), this.S.cursorSnap > 0); tick(m.querySelector('[data-act=strip]'), !!this.S.cursorStrip);
    const H = new Set(toolNames(this.S.toolsHidden)), tl = m.querySelector('.subtg').nextElementSibling, gs = this.toolGroups();   // Tools in the bar ▸
    if (tl.dataset.g !== gs.join()) { tl.dataset.g = gs.join(); tl.innerHTML = mItem('tgall', 'Show all') + mItem('tgnone', 'Hide all') + '<hr>' +
      gs.map(g => mTick('tg', esc(g.charAt(0).toUpperCase() + g.slice(1)), ` data-tg="${esc(g)}"`)).join(''); }
    for (const b of tl.querySelectorAll('[data-act=tg]')) tick(b, !H.has(b.dataset.tg));
  },
  // a menu of the bar (its header: a button with data-pop; ⋯: the group's .more; the filters' chips) opened under its header (at, [x, y]:
  // there, the right button on the bar) or closed; one at a time but a menu inside the ⋯ of a group; Esc, a click elsewhere close them
  popToggle(head, box) {
    box = box || this.root.querySelector(`.bar .bpop[data-pop="${head.dataset.pop}"]`); if (!box) return this;
    return (this.pops || []).some(p => p.box === box) ? this.popClose(box) : this.popOpen(head, box);
  },
  popOpen(head, box, at = null) {
    box = box || this.root.querySelector(`.bar .bpop[data-pop="${head.dataset.pop}"]`); if (!box) return this;
    this.closeMenu();
    const keep = (this.pops || []).findIndex(q => !q.box.contains(head));   // the ones it is opened from stay
    if (keep >= 0) this.popClose(this.pops[keep].box);
    const p = { head, box }; this.pops = [...(this.pops || []), p];
    this.barSync(true);
    if (box.classList.contains('more')) box.parentElement.classList.add('open'); else if (box.classList.contains('chips')) box.classList.add('open');
    else { box.hidden = false; box.classList.add('wv-menu'); }
    head.setAttribute('aria-expanded', 'true');
    // fixed under its header (or at the pointer), inside the bar's width and the window
    p.place = () => {
      const bar = this.root.querySelector('.bar').getBoundingClientRect(), h = at ? { left: at[0], right: at[0], bottom: at[1] } : head.getBoundingClientRect();
      box.style.maxWidth = Math.max(160, Math.min(bar.width, innerWidth) - 8) + 'px'; box.style.left = box.style.top = '0px';
      const w = box.offsetWidth, hh = box.offsetHeight, lo = Math.max(4, bar.left + 4), hi = Math.min(innerWidth, bar.right) - 4;
      box.style.left = Math.max(lo, Math.min(at ? h.left : h.right - w, hi - w)) + 'px';
      box.style.top = Math.max(4, Math.min(h.bottom + 3, innerHeight - hh - 4)) + 'px';
    };
    p.place();
    const back = () => { const q = (this.pops || []).find(x => x.box === box); this.popClose(box); if (q) q.head.focus({ preventScroll: true }); };
    if (box.classList.contains('bpop')) {   // ↑ ↓ Home End, its submenus, Esc: closed, back on its header
      if (!box.wlSubs) { box.wlSubs = menuSubs(box); menuKeys(box, back, box.wlSubs); }
      const f = [...box.querySelectorAll(':scope > button, :scope > .msub > button, :scope > label.mi input, :scope > label.mi select')]
        .find(x => !x.hidden && x.getClientRects().length);
      if (f) f.focus({ preventScroll: true });
    } else if (!box.wlEsc) {   // ⋯, the chips: Esc closes them (not a menu of theirs: its own Esc)
      box.wlEsc = true;
      box.addEventListener('keydown', e => { if (e.key === 'Escape' && (this.pops || []).some(q => q.box === box) && !e.target.closest('.bpop')) {
        e.preventDefault(); e.stopPropagation(); back(); } });
    }
    if (!this.popOff) {   // a click outside every one closes them; the page scrolled: they follow their headers
      this.popOff = e => { if (!(this.pops || []).length || (e.target instanceof Node && this.pops.some(q => q.box.contains(e.target) ||
        q.head.contains(e.target)))) return; this.popClose(); };
      document.addEventListener('pointerdown', this.popOff, { capture: true, signal: this.ac.signal });
      window.addEventListener('scroll', () => (this.pops || []).forEach(q => q.place()), { capture: true, passive: true, signal: this.ac.signal });
    }
    return this;
  },
  // a menu of the bar closed, and the ones opened from it; none named: every one
  popClose(box) {
    const all = this.pops || [], i = box ? all.findIndex(p => p.box === box) : 0; if (i < 0 || !all.length) return this;
    for (const p of all.slice(i).reverse()) {
      const x = p.box; if (x.wlSubs) x.wlSubs.set(null);
      if (x.classList.contains('more')) x.parentElement.classList.remove('open'); else if (x.classList.contains('chips')) x.classList.remove('open');
      else { x.hidden = true; x.classList.remove('wv-menu', 'kb'); }
      x.style.left = x.style.top = x.style.maxWidth = ''; p.head.setAttribute('aria-expanded', 'false');
    }
    this.pops = all.slice(0, i); return this;
  },
  // the right button on the bar: the ⚙ menu at the pointer
  toolsMenu(cx, cy) { const h = this.root.querySelector('.bar .pgear'); this.popClose(); return this.popOpen(h, null, [cx, cy]); },
  saveLook() {
    const own = Object.fromEntries(Object.entries(this.local).filter(([k]) => k !== 'toolLayout' && k !== 'toolsCompact'));   // (those: wavelens.bar)
    try { if (Object.keys(own).length) localStorage.setItem(this.lookKey, JSON.stringify(own)); else localStorage.removeItem(this.lookKey);
      } catch (e) { /* private mode */ }
  },
  // the gaps of the pictures and WaveDrom saved from this viewer (settings gaps, gapIdle, gapKeep; the menu's own over them,
  // kept in this browser where they differ from the settings; null: the settings' again). A plugin keeping stretches
  // (view.extraKeep: expressions with ✂) has them on, on the waves, for as long as it does; gapBy: which ones say so; own: as
  // the settings and the menu have them, without that
  gapOpt(own) {
    const S = this.S, L = this.local.gap || {}, o = {}, by = !own && this.extraKeep ? this.extraKeep.by() : [];
    for (const k of GAP_KEYS) o[k] = L[k] !== undefined ? L[k] : S[k];
    o.gaps = !!o.gaps; o.gapOnly = !!o.gapOnly; o.gapView = !!o.gapView; o.gapSignals = prefixes(o.gapSignals); o.gapAux = prefixes(o.gapAux);
    o.gapClock = o.gapClock || null;
    if (!['off', 'clock', 'edges', 'rise', 'fall', 'any'].includes(o.gapCount)) o.gapCount = 'clock';
    if (by.length) { o.gaps = o.gapView = true; o.gapBy = by; }
    return o;
  },
  // kept: a state's own values (its plugins' parts, which came first, stay); else the gaps said off, or reset, end extraKeep's
  setGaps(o, kept) {
    const K = this.extraKeep;
    if (!kept && K && K.by().length) {
      if (!o || o.gaps === false || o.gapView === false) K.off();
      if (o) o = Object.fromEntries(Object.entries(o).filter(([k, v]) => !(v === true && (k === 'gaps' || k === 'gapView'))));
    }
    const list = k => k === 'gapSignals' || k === 'gapAux', same = (k, v) => JSON.stringify(list(k) ? prefixes(v) : v) ===
      JSON.stringify(list(k) ? prefixes(this.S[k]) : this.S[k]);
    const own = Object.entries(Object.assign({}, this.local.gap, o)).filter(([k, v]) => o && GAP_KEYS.includes(k) && !same(k, v));
    if (own.length) this.local.gap = Object.fromEntries(own); else delete this.local.gap;
    this.saveLook(); return this.gapsChanged();
  },
  gapsChanged() { this.gapMemo = null; this.hdrH = this.headH(); this.syncGapBar(); this.renderNames(); this.draw(); this.settingsChanged(); return this; },
  // the gaps' rows, worked out again when the settings, the rows or the menu's gaps change (the names column asks per row)
  gapRows() {
    const m = this.gapMemo;
    if (m && m.S === this.S && m.rows === this.rowsAll) return m;
    const g = this.gapOpt(), all = [...this.M.rows, ...(this.rowsAll || this.allRows())];   // the model's rows first (a plugin may draw one again)
    const clk = g.gapClock ? gapRefs(all, g.gapClock)[0] || null : null;
    return (this.gapMemo = { S: this.S, rows: this.rowsAll, ref: new Set(gapRefs(all, g.gapSignals)), aux: new Set(gapRefs(all, g.gapAux)), clk });
  },
  // the signals the gaps follow (gapSignals: the menu's Gaps by this signal; none: the signals of the picture), a Set
  gapRefSet() { return this.gapRows().ref; },
  // the clock the gaps count cycles of: gapClock (the menu's "Gaps: cycles of this clock"), else clockFor(rows)
  gapClockRow() { return this.gapRows().clk; },
  gapClockFor(rows) { return this.gapClockRow() || this.clockFor(rows.filter(r => r.type === 'sig')); },
  // the clock cycles (settings cycles, cycleClock, cycleZero; the menu's Cycles over them, kept in this browser where they
  // differ from the settings; null: the settings' again)
  cycOpt() {
    const L = this.local.cyc || {}, o = {};
    for (const k of CYC_KEYS) o[k] = L[k] !== undefined ? L[k] : this.S[k];
    o.cycles = !!o.cycles; o.cycleClock = o.cycleClock || null; o.cycleZero = zeroTime(o.cycleZero);
    if (o.cycleZero != null && !isFinite(o.cycleZero)) o.cycleZero = null;
    return o;
  },
  setCycles(o) {
    const own = Object.entries(Object.assign({}, this.local.cyc, o)).filter(([k, v]) => o && CYC_KEYS.includes(k) && JSON.stringify(v ?? null) !==
      JSON.stringify(this.S[k] ?? null));
    if (own.length) this.local.cyc = Object.fromEntries(own); else delete this.local.cyc;
    this.saveLook(); this.cycMemo = null; this.hdrH = this.headH();
    this.renderNames(); if (this.umarks.length) this.renderNotes(); this.draw(); this.settingsChanged(); return this;   // the Δ of the markers in cycles
  },
  // the clock the cycles count (cycleClock, else the clock found) and its rising edges, cycle 0 at iz; null: no band (off,
  // or no clock); any: the clock even with the band off (the cursor field's c147)
  cycData(any = false) {
    const o = this.cycOpt(); if (!o.cycles && !any) return null;
    const key = JSON.stringify(o);
    if (!this.cycMemo || this.cycMemo.key !== key) {
      const clk = cycClock(this.M.rows, o.cycleClock), ups = clk ? cycUps(clk) : [];
      if (clk && clk.lazy) this.need([clk]);   // a large dump: the clock read, the band drawn when it is there (need resets the memo)
      this.cycMemo = { key, d: clk && ups.length ? { clk, ups, iz: cycZero(ups, o.cycleZero, this.M.t0) } : null };
    }
    return this.cycMemo.d;
  },
  // the rows a picture takes with gapOnly ("only them"): the signals the gaps follow, as laid out; null: not so
  // (and the clock they count, the signals counted in them)
  gapMask() {
    const g = this.gapOpt(), G = this.gapRows();
    if (!g.gaps || !g.gapOnly || !G.ref.size) return null;
    const L = this.rowsL || [], on = r => G.ref.has(r) || G.aux.has(r) || r === G.clk;
    return L.filter((r, i) => on(r) || (r.type === 'lane' && L[i + 1] && on(L[i + 1])));   // an arrows' lane over a row kept: kept
  },
  // the parts of [a, b] a picture or WaveDrom of these rows keeps (gapCuts): the idle stretches of the signals the gaps
  // follow (else of these rows) left out, in cycles of their clock (clockFor), the bookmarks' times kept; [[a, b]]: no gap
  cutsOf(a, b, rows) {
    const live = this.liveCuts(); if (live) return clipCuts(live.w.cuts, a, b);   // the gaps on the waves: what you see is what you save
    const ref = [...this.gapRefSet()], sigs = ref.length ? ref : rows.filter(r => r.type === 'sig' || (r.type === 'group' && r.sig));
    return gapCuts(sigs, a, b, this.gapOpt(), this.gapClockFor(ref.length ? rows : sigs), this.M.cycle, this.bms.map(x => x.t), ref.length > 0);
  },
});
