/* wavelens/src/view.js — the interactive viewer (WaveView). */

// The short names used here and in paint.js:
//   M      the model (parse): rows, groups, t0 / t1, markers …        S   the settings of all layers (settings())
//   P      a painter (CanvasPainter / SvgPainter)                       X   time -> x on the waves; k: px per time unit
//   t0     the time at the left edge of the view, span: its width       tA / tB: the window drawn, xL / xR: its x range
//   vis    the rows not folded away, in display order                   rowsL: vis with the arrow-label lanes spliced in
//   lay    [{row, y, h}] of rowsL (layoutRows), lay.H: all rows' height  oy: the canvas's offset in that layout; hc: its height
//   hl     the highlight state {cover, on, dim} (hlState)               picks: Map(row -> colour) of what you highlighted
//   bms    the bookmarks [{n, t, signal, text, color}], arrows: [{from, to, shape, head, line, color, label}]
//   sel    the selected signal row; fi / fiRow: the match stepped to   lv / pk / py / pw (paintSig): the open level path, the
//          previous kind, y and width

/* ---------------- the viewer's parts: Bar (bar.js: tools), Names, Notes (names.js) ---------------- */
// Each part takes the viewer v and keeps its state there (v.qEl, v.vis, v.rowEls, v.bms …): a part is where the code of
// a piece of the page lives; the viewer is the one object that plugins and tests talk to.
/* ---------------- interactive viewer ---------------- */
const PNG_MAX = 16384;   // px, a side of a canvas that every browser draws
const VIEWS = new Set(), ACTIVE = { view: null };   // ACTIVE.view: the viewer used last (Esc while the focus is on the page)
const PLUGINS = [];   // WaveLens.plugin(fn): fn(viewer) for every viewer, now and later (wavelens/sva.js: the assertions panel)
const STATE_VERSION = 3;   // a saved viewer state (state()): 2 has range and edge, 3 your markers and groups
// the settings of the gaps (the menu's Gaps rows)
const GAP_KEYS = ['gaps', 'gapIdle', 'gapKeep', 'gapSignals', 'gapClock', 'gapAux', 'gapOnly', 'gapCount', 'gapLine', 'gapView'];
const CYC_KEYS = ['cycles', 'cycleClock', 'cycleZero'], CYC_H = 16;   // the band of clock cycles under the time axis, its height
class WaveView {
  constructor(root, model, opts = {}) {
    this.root = root; this.M = parse(model); this.opts = opts;
    const M = this.M;
    applyLook(root, opts.theme ?? M.theme, Object.assign({}, M.colors, opts.colors));
    this.storeId = this.storeName();
    this.lookKey = 'wavelens.look:' + this.storeId; this.local = this.loadLook();   // the bar's own layer of the settings (the edge style)
    // a large dump read as it is needed (its rows "lazy", opts.loadCodes reads them): the top level open, its modules folded
    this.lazy = M.rows.some(r => r.lazy); this.lazyWait = new Map();
    if (this.lazy && !opts.loadCodes) { M.rows.forEach(r => { r.lazy = false; }); this.lazy = false; }   // nothing to read them with: as they are
    this.restyle(false); this.collapsed = foldSet(M, this.S.fold ?? (this.lazy ? 1 : null));
    this.picks = hlPick(M, this.S.highlight); this.hlFrom = JSON.stringify(this.S.highlight ?? null);
    this.selRun = new Set(); this.selAnchor = null;   // shift+click: a run of selected signals (selectRun)
    this.found = new Map(); this.findPicks = new Map(); this.findHl = this.S.findHighlight; this.findOpen = this.S.findOpen;   // fuzzy find
    this.findMask = this.S.findMask;
    this.only = null;   // Only: {modules: [paths], on} (modules.js)
    for (const [, k] of FIND_OPTS) this[k] = !!this.S[k];   // its options: the case, the whole name, a regular expression
    this.paintKey = 'wavelens.paint:' + this.storeId;
    this.painted = new Map(); this.loadPaint();
    // the menu's radix per signal, hidden rows, the buses shown bit by bit (their bit rows: bitsOf)
    this.rowsKey = 'wavelens.rows:' + this.storeId; this.radixes = new Map(); this.analogs = new Map(); this.hiddenRows = new Set();
    this.bitsOpen = new Set(); this.bitMemo = new WeakMap(); this.loadRows();
    this.t0 = M.t0; this.span = M.t1 - M.t0;
    this.minSpan = opts.minSpan ?? (M.timed ? Math.max(this.span / 1e6, 10) : 0.5);
    this.cursor = opts.cursor ?? M.cursor ?? M.t0;
    this.pageMarks = (opts.markers || []).concat(M.markers);   // the page's markers; yours (umarks, the marker command) after them
    this.jumps = opts.jumps || M.jumps || (this.pageMarks.length && this.pageMarks.length <= 6
      ? this.pageMarks.map(m => ({ label: '→ ' + m.label, t: m.t, span: this.span / 5 })) : []);
    this.sel = null; this.edgeKind = 'any';   // selected signal row (edge search, bookmarks), edge kind
    this.extraJSON = [];   // plugins: () -> '"key": …' lines for the bookmarks JSON (or null)
    this.extraState = [];   // plugins: {key, get() -> a JSON value, set(value) (may be async)}: their part of the saved state
    this.extraRows = [Object.assign(g => (g ? [] : this.ugRows()), { head: true })];   // plugins: rows under a group (withExtra); yours at the top
    this.extraPicks = new Map();   // plugins: rows highlighted, row -> a token ('hl8': --wave-hl8) or a colour index; Esc clears (then wavelens:reset)
    this.keys = {};   // plugins: key -> fn(event) on the waves (addKey)
    this.rowMarks = new Map(); this.rowTitles = new Map();   // plugins: classes and tooltips of name rows (rowClass, rowTitle)
    const hints = this.hints = [];   // plugins: lines of the hint under the waves; hints.push() shows them
    hints.push = (...a) => { const n = Array.prototype.push.apply(hints, a); this.renderHint(); return n; };
    this.bmKey = 'wavelens.bookmarks:' + this.storeId;
    // every listener outside the viewer's own child elements (its root, the window, the document) is registered with
    // this signal: destroy() removes them all (a dump opened again on the same element left the old ones running)
    this.ac = new AbortController();
    Object.assign(this, this.loadBookmarks()); root.waveView = this;   // this.bms, this.arrows, this.umarks
    this.markers = this.pageMarks.concat(this.umarks);
    this.build(); this.fit();
    if (opts.from != null || opts.to != null) { // initial view window (Fit still shows everything)
      const a = opts.from ?? M.t0, b = opts.to ?? M.t1;
      this.span = Math.min(Math.max(b - a, this.minSpan), M.t1 - M.t0); this.t0 = this.clamp(a); this.draw();
    }
    this.ro = new ResizeObserver(() => this.draw()); this.ro.observe(this.wcol); this.ro.observe(this.root.querySelector('.bar'));
    // the canvas is only as tall as the visible part of the rows (sticky in its column): redraw when that part moves
    this.onScroll = () => { if (!this.raf && this.lay && this.lay.H > this.hc + 1) this.raf = requestAnimationFrame(() =>
      { this.raf = 0; if (this.root.isConnected) this.draw(); }); };
    const own = { signal: this.ac.signal };
    window.addEventListener('scroll', this.onScroll, { passive: true, ...own }); window.addEventListener('resize', this.onScroll, own);
    this.bodyEl.addEventListener('scroll', this.onScroll, { passive: true, ...own });
    // the rows in the viewer's own box, the page scrolled past the viewer's top: the wheel over the rows brings the bar and
    // the time axis back in sight first (the box is no taller than the window under the bar)
    this.bodyEl.addEventListener('wheel', e => {
      // not a pan (shift+wheel, a sideways swipe: the canvas's) nor a zoom (ctrl, wheel: "zoom")
      if (!this.root.classList.contains('wv-scroll') || e.ctrlKey || e.shiftKey || Math.abs(e.deltaX) >= Math.abs(e.deltaY) ||
        this.S.wheel === 'zoom') return;
      const bar = this.root.querySelector('.bar'); if (bar.getBoundingClientRect().top < 0) bar.scrollIntoView({ block: 'start' });
    }, { passive: true, ...own });
    VIEWS.add(this);
    for (const p of PLUGINS) try { p(this); } catch (e) { console.error('wavelens plugin:', e); }
    // the page's edits (tools/viewedit.py), then undo starts from the page as it opens; a live page: the agent hears of this viewer
    this.applyEdits().finally(() => this.undoTick(true)); liveHello(); liveShow();
  }
  // what this viewer's bookmarks, paint and bindings are stored under in this browser: the page, then opts.key, the id,
  // the data-wave reference or the title; several viewers of one data-wave (a bench and its lazy cards) are told apart by
  // their place among them in the page (the first keeps the plain name). Two live viewers with one name: a warning.
  storeName() {
    const r = this.root, o = this.opts, ref = r.dataset.wave;
    let id = location.pathname + ':' + (o.key || r.id || ref || this.M.title);
    if (!o.key && !r.id && ref) { const k = [...document.querySelectorAll('[data-wave]')].filter(e => e.dataset.wave === ref).indexOf(r);
      if (k > 0) id += '#' + (k + 1); }
    for (const v of VIEWS) if (v.storeId === id &&
      v.root.isConnected) console.warn(`wavelens: two viewers store their bookmarks as "${id}": give one an id or opts.key`);
    return id;
  }
  // settings from all layers; a global WaveLens.configure() calls this again on every viewer
  restyle(redraw = true) {
    const S = this.S = settings(GLOBAL, this.M.cfg, this.opts, this.local);
    this.groupStroke = groupPaint(this.M, S.groupColors);
    for (const [name, v] of styleVars(Object.assign({}, this.M.cfg, this.opts))) this.root.style.setProperty(name, v);
    this.rowH = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight }; this.cycMemo = null;
    this.hdrH = this.headH(); this.syncGapBar();
    this.sort = S.sort; this.sortIgnore = S.sortIgnore;
    this.root.style.setProperty('--wv-dim', S.dim);
    this.layoutShow();
    const hlFrom = JSON.stringify(S.highlight ?? null);   // a new "highlight" setting (configure) replaces the picks
    if (redraw && hlFrom !== this.hlFrom) { this.hlFrom = hlFrom; this.picks = hlPick(this.M, S.highlight); }
    if (redraw && this.qEl && this.q) this.find(this.q);
    if (this.wsEl) this.wsEl.value = S.style;
    if (redraw) { const i = this.root.querySelector('input.pfx'); if (i) i.value = S.sortIgnore.join(','); this.fitPfx(); this.renderNames(); this.draw();
      this.logRender();   // "log": shown or not
      this.settingsChanged(); }
  }
  build() {
    const r = this.root; r.classList.add('wv');
    r.innerHTML = Bar.html(this);
    this.bar = new Bar(this); this.layoutShow();
    this.names = new Names(this);
    this.wheelInput(this.canvas); this.pointerInput(this.canvas); this.keyInput(this.canvas);
    // Esc anywhere in the viewer (waves, find field, names) except the bookmark fields: back to no search, no highlight,
    // no selected signal; the view (opened modules, scroll, time) stays
    this.onActive = () => { ACTIVE.view = this; };
    r.addEventListener('pointerdown', this.onActive, { capture: true, signal: this.ac.signal });
    r.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || e.target.closest('.notes')) return;
      e.preventDefault(); this.reset(); this.floatFind(false);
      if (e.target === this.qEl) this.refocus();
    }, { signal: this.ac.signal });
    this.notes = new Notes(this); this.logMount();   // the log under it (log.js)
    this.renderNames(); this.renderNotes();
  }
  wheelInput(c) {
    // wheel by its size: a mouse notch (100 px) zooms ×1.22, a trackpad's small steps zoom smoothly, ctrl+wheel (a pinch)
    // zooms faster; a horizontal swipe or shift+wheel pans by the pixels moved. deltaMode: lines (16 px) or pages.
    // the wheel as in Questa: it scrolls the rows (the page, or the viewer's own scroll bar), ctrl+wheel (a pinch) zooms
    // at the pointer by how far it turned, shift+wheel (a sideways swipe) pans; the setting wheel: "zoom" zooms without ctrl
    c.addEventListener('wheel', e => {
      const u = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? c.clientHeight || 400 : 1;
      let dx = e.deltaX * u, dy = e.deltaY * u;
      if (e.shiftKey && !dx) { dx = dy; dy = 0; }
      if (Math.abs(dx) > Math.abs(dy)) { e.preventDefault(); this.panFrom(this.t0, dx); this.invalidate(); }
      else if (dy && (e.ctrlKey || this.S.wheel === 'zoom')) {
        e.preventDefault(); this.markView(true);
        const pinch = e.ctrlKey && e.deltaMode === 0 && Math.abs(dy) < 50;   // a trackpad pinch: small steps, many of them
        this.zoom(Math.exp(dy * (pinch ? 0.01 : 0.002)), this.frac(e), true);
      }
    }, { passive: false });
  }
  // the pointer on the waves: the cursor, a pan, a zoom range, a measured range, a box, a bookmark moved or an arrow drawn
  pointerInput(c) {
    // the middle button (Questa): drag over a time range to zoom into it
    c.addEventListener('mousedown', e => { if (e.button === 1) e.preventDefault(); });   // no autoscroll, no paste
    let drag = null;
    const local = e => { const b = c.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top + (this.oy || 0)]; };   // layout y
    // on a bookmark: drag moves it (time + signal row), shift+drag draws an arrow to another bookmark; elsewhere drag pans
    c.addEventListener('contextmenu', e => { if (this.S.contextMenu) e.preventDefault(); });   // the viewer's menu instead
    c.addEventListener('pointerdown', e => {
      if (e.button === 1) { const [x] = local(e); drag = { zoom: x, x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId); return; }
      const [x, y] = local(e), bm = e.button === 0 && this.bmAt(x, y);
      // shift+drag (not from a bookmark: that draws an arrow): zoom into the range dragged over, as the middle button
      if (e.button === 0 && e.shiftKey && !bm && !e.ctrlKey && !e.metaKey) { drag = { zoom: x, x: e.clientX, y: e.clientY, c2: [x, y, e.altKey] };
        c.setPointerCapture(e.pointerId); return; }
      // a measured range: ctrl+drag or the right button (then the menu), its ends on the edges of the signal under the
      // pointer (alt: not), its Δ counted on that signal
      if ((e.button === 2 && this.S.contextMenu) || (e.button === 0 && (e.ctrlKey || e.metaKey) && !bm)) {
        drag = { range: this.pickTime(x, y, e.altKey), menu: e.button === 2, x: e.clientX, y: e.clientY, moved: false, free: e.altKey, row: this.rowOfY(y) };
        c.setPointerCapture(e.pointerId); return;
      }
      if (e.button !== 0) return;
      // alt+drag: a box over time and rows — its time is the range, its signals the selection; then the menu (the picture,
      // WaveDrom, colour … of those signals); alt+click: the cursor without the snap
      if (e.altKey && !bm && !e.shiftKey && !e.ctrlKey && !e.metaKey) { drag = { box: [x, y], x: e.clientX, y: e.clientY, moved: false };
        c.setPointerCapture(e.pointerId); return; }
      // lay: the rows as they were (a lane coming or going does not move them under the pointer)
      drag = { x: e.clientX, y: e.clientY, t0: this.t0, moved: false, bm, arrow: bm && e.shiftKey, free: e.altKey, lay: this.lay };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove', e => {
      const [x, y] = local(e);
      if (!drag) {
        const bm = this.bmAt(x, y), o = !bm && (this.lay || []).find(o => y >= o.y && y < o.y + o.h), tip = o && o.row.tip ? o.row.tip(x, y - o.y, this) : '';
        // the value under the pointer (a struct's row: its whole value)
        const vr = o && (o.row.sig || o.row), val = !bm && !tip && vr && vr.type === 'sig' && vr.tr ? this.valueTip(vr, this.tOfX(x)) : '';
        c.style.cursor = bm ? 'grab' : tip ? 'pointer' : '';
        const sp = !bm && !tip ? this.spanTip(this.tOfX(x), vr) : '';   // a span under the pointer: its label and length
        c.title = bm ? `Bookmark ${bm.n}${bm.text ? ': ' + bm.text : ''} — drag to move it, shift+drag to another bookmark for an arrow` : tip ||
          [this.gapTip(x), sp, val].filter(Boolean).join('\n'); return;
      }
      if (drag.zoom != null) { this.zband = [drag.zoom, x].map(px => this.tOfX(px)); this.draw(); return; }
      if (drag.box) {
        if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3) drag.moved = true;
        if (drag.moved) this.boxSelect(drag.box[0], drag.box[1], x, y);
        return;
      }
      if (drag.range != null) {
        if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3) drag.moved = true;
        if (drag.moved) { this.setRange(drag.range, this.pickTime(x, y, drag.free), drag.row); }
        return;
      }
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.hypot(dx, dy) > 3) drag.moved = true;
      if (!drag.moved) return;
      if (drag.arrow) { this.rubber = { from: drag.bm.n, x, y }; this.draw(); }
      else if (drag.bm) { c.style.cursor = 'grabbing'; this.moveBookmark(drag.bm, x, y, drag.lay); }
      else { this.panFrom(drag.t0, -dx); this.invalidate(); }   // a pan: one draw per frame, not per move event
    });
    c.addEventListener('pointerup', e => {
      const [x, y] = local(e);
      if (drag && drag.range != null) {   // a range ends; the right button opens the menu (on it, or on the signal under it)
        const d = drag; drag = null;
        if (!d.moved && !d.menu) this.setRange(null);   // ctrl+click: no range
        if (d.menu) this.menu(e.clientX, e.clientY, d.row, d.range);
        return;
      }
      if (drag && drag.box) {   // the box: the menu on its signals; a click: the cursor here, not snapped
        const d = drag; drag = null; this.box = null;
        if (d.moved) { this.draw(); this.menu(e.clientX, e.clientY, this.sel, this.cursor); return; }
        const row = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
        this.cursor = this.pickTime(x, y, true); this.range = null; this.selRun = new Set();
        if (row && row.row.type === 'sig' && row.row.tr) this.sel = this.selAnchor = row.row;
        this.renderNames(); this.draw(); return;
      }
      if (drag && drag.zoom != null) {   // the middle button released: the range dragged over (4 px at least) fills the view
        const b = this.zband, c2 = drag.c2; this.zband = null; drag = null;
        if (b && Math.abs(b[1] - b[0]) * this.pxPerT() >= 4) this.zoomTo(Math.min(...b), Math.max(...b));
        else if (c2) this.setCursor2(this.pickTime(...c2));   // shift+click: the second cursor (on an edge, alt: not)
        else this.draw();
        return;
      }
      if (drag && drag.moved && drag.arrow) {
        const to = this.bmAt(x, y); this.rubber = null;
        if (to && to.n !== drag.bm.n) { this.arrows.push(arNorm([{ from: drag.bm.n, to: to.n }])[0]); this.saveBookmarks(); this.renderNotes(); }
        this.draw();
      } else if (drag && drag.moved && drag.bm) { c.style.cursor = 'grab'; this.saveBookmarks(); this.renderNotes(); }
      else if (drag && !drag.moved) {
        const hit = this.bmAt(x, y), mid = !hit && this.bmGeo && this.bmGeo.mids.find(([, mx, my]) => Math.hypot(mx - x, my - y) <= 10);
        if (hit) { this.cursor = hit.t; this.draw(); this.notesEl.querySelector(`li[data-n="${hit.n}"] input.txt`)?.focus(); }
        else if (mid) this.notesEl.querySelector(`li[data-a="${mid[0]}"] input.lab`)?.focus();
        else {   // cursor here (on an edge of the signal under the pointer within cursorSnap px, alt: not), the signal row
          // under the pointer becomes the selected one (a row of a plugin may take the click)
          const row = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
          if (!(row && row.row.click && row.row.click(x, y - row.y, this))) {
            this.cursor = this.pickTime(x, y, drag.free); this.range = null; this.selRun = new Set();
            if (row && row.row.type === 'sig' && row.row.tr) this.sel = this.selAnchor = row.row;
            this.renderNames(); this.draw();
          }
        }
      }
      drag = null;
    });
    c.addEventListener('pointercancel', () => { drag = null; if (this.rubber || this.zband || this.box) { this.rubber = this.zband = this.box = null;
      this.draw(); } });
  }
  keyInput(c) {
    // The keys on the waves: navigation as in Questa's wave window, the lists and the text as in vim. Two-key sequences
    // (gg, zR, yy, ]f …) start with g z y [ ]: the second key within a second
    c.addEventListener('keydown', e => {
      const k = e.key, ctl = e.ctrlKey || e.metaKey; let h = true;
      if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(k)) return;   // a modifier alone: a sequence goes on (z, shift+M)
      if (keyLeft(this.S, e)) return;   // the host's (keysLeft: VS Code's ctrl+G)
      if (e.altKey && !ctl && (k === 'ArrowUp' || k === 'ArrowDown')) { e.preventDefault(); this.moveKey(k === 'ArrowUp' ? -1 : 1, e.shiftKey); return; }
      if (e.altKey || (ctl && !['c', 'C', 'f', 'F', 'g', 'G'].includes(k))) return;   // ctrl+S, ctrl+M … stay the browser's
      // ctrl+F: find (Questa), ctrl+C: copy (nothing to copy: the browser's), ctrl+G: the list of your groups
      if (ctl && (k === 'g' || k === 'G')) { e.preventDefault(); this.groupsMenu(); return; }
      if (ctl) { if (k === 'f' || k === 'F' ? (this.focusFind(), true) : this.copyKey()) e.preventDefault(); return; }
      const pre = this.kpre && Date.now() - this.kpre.t < 1000 ? this.kpre.k : ''; this.kpre = null;
      if (pre && this.seq(pre + k)) { e.preventDefault(); return; }
      if (!pre && 'gzy[]'.includes(k) && k.length === 1) { this.kpre = { k, t: Date.now() }; e.preventDefault(); return; }
      const sigStep = d => { const sigs = this.vis.filter(r => r.type === 'sig' && r.tr), i = sigs.indexOf(this.sel);
        this.select(sigs[Math.min(Math.max(i < 0 ? 0 : i + d, 0), sigs.length - 1)] || null); };
      if (k === 'i' || k === 'I' || k === '+' || k === '=') { this.markView(); this.zoom(0.5, 0.5); }
      else if (k === 'o' || k === 'O' || k === '-') { this.markView(); this.zoom(2, 0.5); }
      else if (k === 'f' || k === 'F') { this.markView(); this.fit(); }
      else if (k === 'l' || k === 'L') this.zoomLast();
      else if (k === 'c' || k === 'C') { this.markView(); this.showCursor(Math.max(this.span / 2, this.minSpan)); }   // zoom in on the cursor (Questa)
      // the next / previous transition of the selected signal (Questa); none selected (Esc): the focus moves on
      else if (k === 'Tab' && this.sel) this.edge(e.shiftKey ? -1 : 1);
      else if (k === 'e') { const ks = Object.keys(EDGE_KINDS); this.setEdgeKind(ks[(ks.indexOf(this.edgeKind) + 1) % ks.length]); }
      else if (k === 'Home' || k === 'End') { this.markView(); this.center(k === 'Home' ? this.M.t0 : this.M.t1, k === 'Home' ? 0 : 1); this.draw(); }
      else if (k === 'PageDown' || k === 'PageUp') this.pageRows(k === 'PageDown' ? 1 : -1);
      else if (k === 'ArrowDown' || k === 'j') sigStep(1);
      else if (k === 'ArrowUp' || k === 'k') sigStep(-1);
      else if (k === 'G') { const sigs = this.vis.filter(r => r.type === 'sig' && r.tr); this.select(sigs[sigs.length - 1] || null); }
      else if ((k === 'ArrowLeft' || k === 'ArrowRight') && e.shiftKey) this.nudge(k === 'ArrowRight' ? 1 : -1);   // the cursor, a 100th of the view
      else if (k === 'ArrowLeft' || k === 'ArrowRight') { this.panPart(k === 'ArrowRight' ? 0.2 : -0.2); this.invalidate(); }
      else if (k === '/') this.focusFind();
      else if ((k === 'n' || k === 'N') && this.found.size) this.findStep(k === 'n' ? 1 : -1);   // like vim
      // the selected name (vim: the word under the cursor)
      else if (k === '*' || k === '#') { if (this.sel) { this.qEl.value = this.sel.name; this.find(this.sel.name); this.findStep(k === '*' ? 1 : -1); } }
      else if (k === 'm') this.mark();
      // the selected bus bit by bit, again: folded (a bit selected: its bus folded)
      else if (k === 'b') { const s = this.sel && (this.sel.bit != null ? this.sel.of : this.sel);
        if (isVec(s)) this.setBits(s, this.sel.bit != null ? false : undefined); else this.toast('b: select a bus to show it bit by bit'); }
      else if (/^[1-9]$/.test(k)) this.goMark(+k);   // the bookmark of that number
      else if (k === 'x' && this.cursor2 != null) { [this.cursor, this.cursor2] = [this.cursor2, this.cursor]; this.draw(); }   // swap the cursors
      else if (k === '?') this.help();
      else if (k === 's' && this.S.sortButton) this.setSort(SORTS[(SORTS.indexOf(this.sort) + 1) % SORTS.length]);
      else if (k === 't') this.modules(true, !!this.mods || !!this.sel);   // the Modules panel; open: the selected signal's module in it
      else if (k === 'T') this.fsmPanel(true);   // the state machines
      else if (k === 'Escape') h = false;   // handled by the viewer (reset)
      else if (this.keys[k]) this.keys[k](e);
      else h = false;
      if (h) e.preventDefault();
    });
  }
  fitPfx() { const i = this.root.querySelector('input.pfx'); if (i) i.style.width = Math.max(7, i.value.length + 2) + 'ch'; }
  // every row in display order (the model's and the plugins'), and the ones not folded away
  // the ones Hide leaves (rowsHid), then the ones Only keeps (modules.js), then the find's Mask: rowsAll. The FSM layer
  // (fsm.js): "only" — the FSMs of its set after Hide (Only and the Mask not applied under it); "add" — its FSMs and the
  // modules on the way to them kept through Hide, Only and the Mask
  allRows(hidden = false, unmasked = false) {   // hidden: the hidden rows too, where they would be (the command rows); unmasked: no Mask
    const rows = this.withBits(withExtra(orderRows(this.M.rows, this.sort, this.sortIgnore, this.S.groupOrder), this.extraRows, this.M, this));
    if (hidden) return rows;
    const H = this.hiddenRows, ids = H.size && new Set(Object.values(this.M.groups).filter(g => H.has(g.path)).map(g => g.id));   // a hidden module: all of it
    const F = this.fsm ? this.fsmTest() : null, add = !!F && this.fsm.mode === 'add';
    const also = (from, kept) => (add && kept !== from ? (s => from.filter(r => s.has(r) || F(r)))(new Set(kept)) : kept);   // kept, and the FSMs
    // a bus's bits go with it through Hide, Only, the FSM layer and the Mask: under every bus kept (a bit hidden by its path stays out)
    const bits = list => (this.bitsOpen.size ? this.withBits(list.filter(r => r.bit == null), H) : list);
    this.rowsStale = false;
    this.rowsHid = H.size ? rows.filter(r => (add && F(r)) || (!(r.type !== 'space' && r.type !== 'lane' && r.full && !r.ug && H.has(r.full)) &&
      !r.anc.some(id => ids.has(id)))) : rows;
    if (F && !add) { const kept = bits(this.rowsHid.filter(this.fsmKeep())); return unmasked ? kept : (this.rowsAll = kept); }
    const rows2 = also(this.rowsHid, this.onlyOn() ? this.onlyKeep(this.rowsHid) : this.rowsHid);
    if (unmasked) return bits(rows2);
    return (this.rowsAll = bits(also(rows2, this.findMask && this.found.size ? this.maskKeep(rows2) : rows2)));
  }
  // the find's Mask: the found rows, the modules on the way to them, what is inside a found module
  maskKeep(rows) {
    const way = new Set(), inn = new Set();
    for (const r of this.found.keys()) { r.anc.forEach(id => way.add(id)); if (r.type === 'group') inn.add(r.id); }
    return rows.filter(r => this.found.has(r) || (r.type === 'group' && way.has(r.id)) || r.anc.some(id => inn.has(id)));
  }
  visible() { return this.allRows().filter(r => !r.anc.some(id => this.collapsed.has(id))); }
  // Bits: a bus shown bit by bit, its bits as rows under it (MSB first, "[3]", full "data[3]"), kept like the hidden rows;
  // a copy of it in your groups unfolds too (its bits copies of the bus's), a plugin's copy (an assertion's signals) not
  withBits(rows, hid = null) {   // hid: the hidden paths (a bit hidden by its own)
    if (!this.bitsOpen.size) return rows;
    return rows.flatMap(r => (r.type === 'sig' && (!r.same || r.ug) && this.bitsOpen.has((r.orig || r).full) && isVec(r) ?
      [r, ...(hid && hid.size ? this.bitsOf(r).filter(k => !hid.has(k.full)) : this.bitsOf(r))] : [r]));
  }
  bitsOf(r) {   // the same objects while the bus stays (selection, highlight, bookmarks)
    let b = this.bitMemo.get(r);
    if (!b) { const o = r.orig; b = o ? this.bitsOf(o).map(k => Object.assign(Object.create(k), { orig: k, same: true })) : bitRows(r);
      this.bitMemo.set(r, b); }
    for (const k of b) { k.depth = r.depth + 1; k.anc = r.anc; }
    return b;
  }
  // a signal by its full path: a row of the model, else a bit of a bus ("data[3]", shown or not)
  sigByPath(p) {
    const s = this.M.rows.find(r => r.type === 'sig' && r.full === p); if (s || typeof p !== 'string') return s || null;
    const m = /^(.+)\[(0|[1-9]\d*)\]$/.exec(p), v = m && this.M.rows.find(r => r.full === m[1] && isVec(r));
    return v && +m[2] < v.width ? this.bitsOf(v)[v.width - 1 - m[2]] : null;
  }
  // rows: rows or paths of buses; on: true / false, none: each the other way -> the buses changed
  setBits(rows, on, quiet = false) {
    const vs = [].concat(rows).map(r => (typeof r === 'string' ? this.sigByPath(r) : r && (r.orig || r))).filter(isVec);
    for (const r of vs) { if (on ?? !this.bitsOpen.has(r.full)) this.bitsOpen.add(r.full); else this.bitsOpen.delete(r.full); }
    if (this.sel && this.sel.bit != null && !this.bitsOpen.has((this.sel.orig || this.sel).of.full)) this.sel = this.sel.of;   // a bit folded away: its bus
    this.rowsStale = true; if (this.cmp) this.cmpMarks();
    if (!quiet) { this.saveRows(); this.renderNames(); this.draw(); }
    return vs;
  }
  settingsChanged() { this.root.dispatchEvent(new CustomEvent('wavelens:settings')); }   // sort, prefixes, settings
  // dir: none | asc | desc; ignore: prefixes skipped when comparing names ("i_,o_" or an array)
  setSort(dir, ignore) {
    this.sort = sortDir(dir);
    if (ignore !== undefined) this.sortIgnore = prefixes(ignore).sort((a, b) => b.length - a.length);
    this.renderNames(); this.draw(); this.settingsChanged(); return this;
  }
  // highlight: list of full paths / names / "*" patterns (one colour each), or null to clear; returns the viewer
  highlight(list) { this.picks = hlPick(this.M, list); this.renderNames(); this.draw(); return this; }
  toggleHighlight(row) { // row: a model row, a full path or a name
    if (typeof row === 'string') row = this.M.rows.find(r => r.full === row) || this.M.rows.find(r => r.name === row);
    if (!row || row.type === 'space') return this;
    if (this.picks.has(row)) this.picks.delete(row);
    else { const used = new Set(this.picks.values()); let c = 0; while (used.has(c) && c < HL_N) c++; this.picks.set(row, c % HL_N); }
    this.renderNames(); this.draw(); return this;
  }
  highlighted() { return [...this.picks.keys()].map(r => r.full); }
  // every signal and module shown from row a to row b (either way round) highlighted too (ctrl+shift+click a name)
  // shift+click a name: the signals from a (the last one clicked) to b in display order are selected (no dimming, as one
  // selected signal); b is the selected one for the keys; the right button's colour, radix, hide and Paint take them all
  selectRun(a, b) {
    const i = this.vis.indexOf(a), j = this.vis.indexOf(b); if (i < 0 || j < 0) return this.select(b);
    this.selRun = new Set(this.vis.slice(Math.min(i, j), Math.max(i, j) + 1).filter(r => r.type === 'sig' && r.tr));
    this.sel = b && b.type === 'sig' && b.tr ? b : this.sel; this.renderNames(); this.draw(); return this;
  }
  // alt+drag from (x0, y0) to (x1, y1), layout px: the box drawn; its time the range (not snapped), the signal rows it
  // touches the selection (as shift+click), the last one the selected signal
  boxSelect(x0, y0, x1, y1) {
    const T = px => this.tOfX(px), ya = Math.min(y0, y1), yb = Math.max(y0, y1);
    this.box = [Math.min(x0, x1), ya, Math.max(x0, x1), yb];
    const rows = (this.lay || []).filter(o => o.y + o.h > ya && o.y < yb && o.row.type === 'sig' && o.row.tr).map(o => o.row);
    this.selRun = new Set(rows); this.sel = rows[rows.length - 1] || this.sel; if (rows.length) this.selAnchor = rows[0];
    this.setRange(T(Math.min(x0, x1)), T(Math.max(x0, x1)), rows[0] || null);   // draws
    this.renderNames(); return this;
  }
  // the find's Select: the found signals in the view selected (as shift+click), in display order, for the right button
  // (a new group, colour, radix, hide …); add (ctrl+click): to the ones selected already
  selectFound(add = false) {
    const rows = this.allRows().filter(r => this.found.has(r) && r.type === 'sig' && r.tr);
    if (!rows.length) { this.toast(this.found.size ? 'no signal found' : 'nothing found'); return this; }
    this.selRun = new Set([...(add ? [...this.selRun, this.sel].filter(Boolean) : []), ...rows]);
    this.sel = rows[rows.length - 1]; this.selAnchor = rows[0];
    this.renderNames(); this.draw(); this.toast(`${this.selRun.size} selected`); return this;
  }
  isSel(r) { return r === this.sel || (!!this.selRun && this.selRun.has(r)); }
  highlightRun(a, b) {
    if (typeof a === 'string') a = this.vis.find(r => r.full === a); if (typeof b === 'string') b = this.vis.find(r => r.full === b);
    const i = this.vis.indexOf(a), j = this.vis.indexOf(b); if (i < 0 || j < 0) return this;
    for (const r of this.vis.slice(Math.min(i, j), Math.max(i, j) + 1)) if ((r.type === 'sig' || r.type === 'group') && !this.picks.has(r)) this.picks.set(r,
      this.picks.size % HL_N);
    this.renderNames(); this.draw(); return this;
  }
  // fuzzy find: rows matching every word; options: found rows in front (findHl), only their modules open (findOpen)
  // restore: give back the folding from before the search (the Open option switched off); clearing the search keeps the
  // modules it opened, so the view stays where it is
  find(q, restore = false, keep = null, refold = true) {   // refold false: the matches only, the folding as it is (Only changed)
    this.q = q;
    const s = String(q || '').trim(), re = this.findRegex && s ? this.findRe(s) : null, badRe = this.findRegex && !!s && !re;
    const terms = this.findRegex ? (re ? [s] : []) : s.split(/\s+/).filter(w => w.replace(/\./g, ''));   // "." alone is no query
    const o = { cs: this.findCase, full: this.findWord, re };
    this.found = new Map();
    if (terms.length) for (const r of this.allRows(false, true)) {   // what Mask leaves out is searched too
      if (r.type !== 'space') { const m = findRow(r, terms, this.M, o); if (m) this.found.set(r, m); } }
    let moved = null;
    if (terms.length && this.findOpen && refold) {   // fold everything but the way to the matches
      if (!this.foldSaved) { this.foldSaved = new Set(this.collapsed); this.foldTouched = false; }
      const keep = new Set(); for (const r of this.found.keys()) r.anc.forEach(id => keep.add(id));
      this.collapsed = new Set(Object.keys(this.M.groups).map(Number).filter(id => !keep.has(id)));
    } else if (this.foldSaved && refold) {
      // the search ends: the folding from before it is back (unless you folded or opened a module meanwhile), with the
      // way to the row you stepped to kept open, and that row stays where it is on the screen
      if (restore) this.collapsed = this.foldSaved;
      else if (!this.foldTouched) {
        const at = keep && keep.anc ? this.rowTop(keep) : null;
        this.collapsed = new Set([...this.foldSaved].filter(id => !(keep && keep.anc && keep.anc.includes(id))));
        if (at != null) moved = [keep, at];
      }
      this.foldSaved = null;
    }
    this.findPicks = terms.length && this.findHl ? new Map([...this.found.keys()].map(r => [r, 6])) : new Map();
    this.fi = -1; this.fiRow = null;
    if (this.cntEl) { const n = this.found.size, miss = terms.length ? this.omitRows().filter(r => findRow(r, terms, this.M, o)) : [];
      const out = terms.length ? this.onlyOut(r => !!findRow(r, terms, this.M, o)) : 0;   // in the modules Only leaves out
      this.cntEl.textContent = badRe ? 'bad regex' : terms.length ? (n ? `${n} found` : 'no match') + (out ? ` · ${out} outside Only` : '') +
        (miss.length ? ` · ${miss.length} not in the page` : '') : '';
      this.cntEl.classList.toggle('none', badRe || (!!terms.length && !n));
      if (miss.length) { const why = this.M.src.meta.omitted.why === 'dumpBudget' ? `past the dumpBudget (${this.S.dumpBudget} changes) of the page's ` +
          'reader: open the dump with a larger budget' : '"show": false in the config: set it true and make html again';
        this.cntEl.dataset.tip = ''; this.cntEl.dataset.ttl = `In the dump, not in this page (${why}):\n` + miss.slice(0, 12).map(r => r.full).join('\n') +
          (miss.length > 12 ? `\n… ${miss.length - 12} more` : ''); }
      else { delete this.cntEl.dataset.tip; delete this.cntEl.dataset.ttl; } }
    this.renderNames(); this.draw();
    if (moved) { const d = this.rowTop(moved[0]) - moved[1]; if (d) { if (this.root.classList.contains('wv-scroll')) this.bodyEl.scrollTop += d;
      else window.scrollBy(0, d); this.draw(); } }
    return this;
  }
  // the .* option: the query as a JavaScript RegExp, vim's \< \> as \b, anchored with Full, the case as Aa; bad: null
  findRe(s) {
    let src = s.replace(/\\([<>])/g, '\\b'); if (this.findWord) src = `^(?:${src})$`;
    try { return new RegExp(src, this.findCase ? '' : 'i'); } catch (e) { return null; }
  }
  setFindOpt(k, on) {   // findCase, findWord, findRegex: the button and the search again
    if (!FIND_OPTS.some(o => o[1] === k)) return this;
    this[k] = !!on; this.root.querySelector(`button[data-act=${FIND_OPTS.find(o => o[1] === k)[0]}]`)?.setAttribute('aria-pressed', this[k]);
    return this.find(this.q || '');
  }
  // where row r is on the screen, in the column or not (a large one holds the rows near the view: Names)
  rowBox(r) {
    const k = this.vis ? this.vis.indexOf(r) : -1, el = k >= 0 && this.namesEl.querySelector(`.row[data-r="${k}"]`);
    if (el) return el.getBoundingClientRect();
    const i = k >= 0 && this.rowY ? this.rowsL.indexOf(r) : -1; if (i < 0) return null;
    const top = this.namesEl.getBoundingClientRect().top + this.hdrH + this.rowY[i], height = this.rowY[i + 1] - this.rowY[i];
    return { top, height, bottom: top + height };
  }
  rowTop(r) { const q = this.rowBox(r); return q ? q.top : null; }
  reset() { // Esc: search, highlight and the selected signal go; scroll and time stay, the folding from before the search is back
    const keep = this.fiRow || this.sel;
    if (this.qEl) this.qEl.value = '';
    this.picks = new Map(); this.sel = null; this.selRun = new Set(); this.extraPicks = new Map(); this.range = null; this.cursor2 = null; this.closeMenu();
    this.root.dispatchEvent(new CustomEvent('wavelens:reset'));
    return this.find('', false, keep);
  }
  unit() { // the unit the cursor fields start in: the one of a tenth of the whole span
    const ref = (this.M.t1 - this.M.t0) / 10, u = UNITS.find(([f]) => ref >= f) || UNITS[UNITS.length - 1];
    return u[1];
  }
  // "250" in the unit chosen (cycles for an untimed diagram), or "85.12us" with its own unit -> model time
  parseIn(v, sel, at = false) {   // at: a time on the waves (the cursor), where c147 is cycle 147's edge
    v = String(v ?? '').trim();
    if (!v) return undefined;
    if (/^-?[\d.]+(e-?\d+)?$/i.test(v)) return parseFloat(v) * (this.M.timed && sel ? UNIT_PS[sel.value] : 1);
    const c = /^(?:c|cycle\s*)(-?\d+)$/i.exec(v);   // c147: the rising edge of cycle 147 of the cycles' clock (the band off: the clock found)
    if (c) { const d = at && this.cycData(true); return d ? cycTime(d.ups, d.iz, +c[1]) ?? undefined : undefined; }
    return this.M.timed ? parseT(v) : undefined;
  }
  bad(inp) { inp.classList.add('bad'); setTimeout(() => inp.classList.remove('bad'), 900); }
  setCursor(v) { // cursor at a typed time; the view follows when it is outside
    const t = typeof v === 'number' ? v : this.parseIn(v, this.cuEl, true);
    if (t == null || !isFinite(t)) { this.bad(this.ctEl); return this; }
    this.cursor = Math.min(Math.max(t, this.M.t0), this.M.t1);
    if (this.cursor < this.t0 || this.cursor > this.t0 + this.span) this.center(this.cursor);
    this.draw(); this.syncCursorFields(true); return this;
  }
  showCursor(v) { // window of a span (typed, else the current one) centred on the cursor
    const sp = v == null || v === '' ? this.span : typeof v === 'number' ? v : this.parseIn(v, this.suEl);
    if (sp == null || !isFinite(sp) || sp <= 0) { this.bad(this.csEl); return this; }
    this.span = Math.min(Math.max(sp, this.minSpan), this.M.t1 - this.M.t0);
    this.center(this.cursor); this.draw(); this.syncCursorFields(true); return this;
  }
  syncCursorFields(force) { // the fields show the cursor and the span, except while one is being typed in
    if (!this.ctEl) return;
    const show = (inp, sel, t) => { if (force || document.activeElement !== inp) inp.value = String(Number((t / (this.M.timed &&
      sel ? UNIT_PS[sel.value] : 1)).toPrecision(7))); };
    show(this.ctEl, this.cuEl, this.cursor); show(this.csEl, this.suEl, this.span);
  }
  clearFind() { // the search ends; the selection and time stay, the folding from before it (the way to the selection open)
    if (this.qEl) this.qEl.value = '';
    return this.find('', false, this.fiRow || this.sel);
  }
  findStep(dir) { // Enter / shift+Enter: the next / previous match in display order (its modules are opened)
    const order = this.allRows().filter(r => this.found.has(r));
    if (!order.length) return this;
    this.fi = ((this.fi ?? -1) + dir + order.length) % order.length;
    const r = this.fiRow = order[this.fi];
    r.anc.forEach(id => this.collapsed.delete(id));
    if (r.type === 'sig') this.select(r); else { this.renderNames(); this.draw(); }
    this.centerRow(r);
    if (this.cntEl) this.cntEl.textContent = `${this.fi + 1} / ${order.length}`;
    return this;
  }
  // a row in the middle of the waves under the axis (the viewer's own scroll box, else the page), as far as the scroll goes
  centerRow(r) {
    const q = this.rowBox(r); if (!q) return this;
    const own = this.root.classList.contains('wv-scroll'), box = own ? this.bodyEl.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
    const d = q.top + q.height / 2 - (box.top + this.hdrH + box.bottom) / 2;
    if (own) this.bodyEl.scrollTop += d; else window.scrollBy(0, d);
    this.invalidate();
    return this;
  }
  copyRows(rows) { // full paths, one per line, to the clipboard
    const text = rows.map(r => r.full || r.name).join('\n'), done = () => this.toast(`copied ${rows.length}`);
    if (!rows.length) return this.toast('nothing to copy');
    const fallback = () => { const ta = document.createElement('textarea'); ta.value = text; ta.style.cssText = 'position:fixed;opacity:0;top:0';
      document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (e) { /* no clipboard */ } ta.remove();
        this.refocus(); };
    try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
    this.copied = text; return this;
  }
  toast(msg) { const t = this.root.querySelector('.bar .toast'); if (!t) return; t.textContent = msg; clearTimeout(this.toastT);
    this.toastT = setTimeout(() => { t.textContent = ''; }, 1600); }
  // the found and the highlighted signals (a highlighted module: its signals; neither: the selected one) take this colour
  // (trace, outline, name); kept in this browser
  paint(color) {
    this.paintRows().forEach(r => this.painted.set(r.full, color));
    this.savePaint(); this.renderNames(); this.draw(); return this;
  }
  paintRows() {
    const rows = this.M.rows.filter(r => r.type === 'sig' && (this.found.has(r) || this.picks.has(r) || this.selRun.has(r) ||
      r.anc.some(id => this.picks.has(this.M.groups[id]))) && this.shown(r));   // not what you do not see (Hide, Only)
    return rows.length ? rows : this.sel && this.sel.type === 'sig' ? [this.sel] : [];
  }
  unpaint() { this.painted.clear(); this.savePaint(); this.renderNames(); this.draw(); return this; }
  // the radix of a signal (a row or its path; one of RADIX, null: the page's) and hidden rows (signals, modules: all of
  // them), from the right button's menu; kept in this browser and in the saved state
  setRadix(row, radix, quiet = false) {   // quiet: no save / render / draw (a loop that does them once after)
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row); else if (row && row.orig) row = row.orig;
    if (!row || row.type !== 'sig') return this;
    if (!('radix0' in row)) row.radix0 = row.radix;
    if (isRadix(radix)) { row.radix = radix; this.radixes.set(row.full, radix); } else { row.radix = row.radix0; this.radixes.delete(row.full); }
    this.valsAt = null; if (!quiet) { this.saveRows(); this.renderNames(); this.draw(); } return this;
  }
  // a bus drawn analog (a step plot, n rows high; true: 3, 0 / false: as a bus; null: the page's own), kept like the radix
  setAnalog(row, n, quiet = false) {   // a bus only: a 1-bit signal has no values to plot (null: back to its own)
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row); else if (row && row.orig) row = row.orig;
    if (!row || row.type !== 'sig' || (n && (row.width || 1) < 2 && row.kind !== 'real')) return this;
    if (!('analog0' in row)) row.analog0 = row.analog;
    if (n == null) { row.analog = row.analog0; this.analogs.delete(row.full); } else { row.analog = n || false; this.analogs.set(row.full, n || false); }
    if (!quiet) { this.saveRows(); this.renderNames(); this.draw(); } return this;
  }
  hide(rows) {   // rows or paths (a signal of your group: out of the group)
    const out = [].concat(rows).filter(r => r && r.ug);
    for (const g of this.ugroups) { const rm = out.filter(r => r.ug.name === g.name).map(r => r.full);
      if (rm.length) g.signals = g.signals.filter(f => !rm.includes(f)); }
    if (out.length) this.ugMemo = null;
    for (const r of [].concat(rows)) { const p = typeof r === 'string' ? r : r && !r.ug && (r.full || r.path); if (p) this.hiddenRows.add(p); }
    if (this.sel && !this.allRows().includes(this.sel)) this.sel = null;
    this.rowsStale = true; this.saveRows(); this.renderNames(); this.draw(); return this;
  }
  unhide(paths) {   // these paths (none: every hidden row) back
    if (paths) [].concat(paths).forEach(p => this.hiddenRows.delete(p)); else this.hiddenRows.clear();
    this.rowsStale = true; this.saveRows(); this.renderNames(); this.draw(); return this;
  }
  // what you did in this viewer as one JSON object (Save / Load… in the bar): the window, the cursor, the order and its
  // prefixes, the folding, the highlight (in its colours' order), the paint, the selected signal, the search, the
  // bookmarks and arrows, and the plugins' parts (extraState). The keys of "config" are settings: they paste into a
  // config file as they are. Paths are full paths; times are model units.
  state() {
    const M = this.M, folded = this.foldSaved || this.collapsed;   // during a search: the folding from before it
    const st = { wavelens: 'state', version: STATE_VERSION, title: this.opts.title || M.title || '', from: this.t0, to: this.t0 + this.span,
      cursor: this.cursor, config: { style: this.S.style, maxHeight: this.S.maxHeight ?? null, toolsFolded: !!this.S.toolsFolded,
        toolsHidden: toolNames(this.S.toolsHidden), sort: this.sort, sortIgnore: [...this.sortIgnore],
        fold: [...folded].map(id => M.groups[id] && M.groups[id].path).filter(Boolean),
        highlight: [...this.picks].sort((a, b) => a[1] - b[1]).map(([r]) => r.full).filter(Boolean), findHighlight: !!this.findHl, findOpen: !!this.findOpen,
        findMask: !!this.findMask,
          ...Object.fromEntries(FIND_OPTS.map(o => [o[1], !!this[o[1]]])), ...this.gapOpt(), ...this.cycOpt() },
      paint: Object.fromEntries(this.painted), radix: Object.fromEntries(this.radixes), analog: Object.fromEntries(this.analogs), hidden: [...this.hiddenRows],
        bits: [...this.bitsOpen], select: (this.sel && this.sel.full) || null, find: this.q || '', bookmarks: this.bookmarks(), arrows: this.arrowList(),
        markers: this.markList(), spans: this.spanList(),
        groups: this.groupList(), only: this.onlyState(), fsm: this.fsmState(), compare: this.cmpState(), compareShow: this.cmp ? this.cmpRun : null };
    // none is said (null, the kind "any"): a state loaded later clears what is there then (a key left out keeps it)
    st.cursor2 = this.cursor2 ?? null;
    st.range = this.range ? { from: this.range[0], to: this.range[1], signal: (this.rangeRow && this.rangeRow.full) || null } : null;
    st.edge = { kind: this.edgeKind, value: (this.evEl && this.evEl.value) || '' };
    for (const x of this.extraState) { try { const val = x.get(); if (val !== undefined) st[x.key] = val; } catch (e) { console.error('wavelens state:', e); } }
    return st;
  }
  // a state (state()) back: every key it has replaces this viewer's; the plugins' parts first (their rows may come).
  // -> the paths it names that these waves do not have (left out)
  async setState(st) {
    if (!st || typeof st !== 'object' || Array.isArray(st) || st.wavelens !== 'state') throw new Error(st &&
      st.signal ? 'WaveDrom waves, not a saved viewer state (open them as a page)' : 'not a saved viewer state');
    if (!(st.version <= STATE_VERSION)) this.log('warning', `a state of version ${st.version} (this viewer reads ${STATE_VERSION}): what it does not know is ` +
      'left out');
    const M = this.M, C = st.config || {}, miss = new Set();
    for (const x of this.extraState) if (st[x.key] !== undefined) { try { await x.set(st[x.key]); } catch (e) { this.toast(`${x.key}: ${e.message}`); } }
    const sigs = new Set(M.rows.map(r => r.full));
    if (st.groups !== undefined) {   // a group of the same name stays the same object: its rows, folding and selection stay
      // a group found by its uid (undo's, over a rename), else by its name
      const old = new Map(this.ugroups.map(g => [g.name, g])), byUid = new Map(this.ugroups.filter(g => g.uid).map(g => [g.uid, g]));
      this.ugroups = groupNorm(st.groups).map(g => { const o = (g.uid && byUid.get(g.uid)) || old.get(g.name) || g;
        if (o !== g) { if (o.uid && !g.uid) g.uid = o.uid; for (const k of Object.keys(o)) if (!(k in g)) delete o[k]; Object.assign(o, g); }
        o.signals = o.signals.filter(p => sigs.has(p) || (miss.add(p), false)); return o; });
      this.setGroups();
    }
    this.allRows();   // the plugins' groups and yours are there now (their folding)
    const paths = new Set([...M.rows.map(r => r.full), ...Object.values(M.groups).map(g => g.path)]);
    const seen = p => paths.has(p) || !!this.sigByPath(p) || (miss.add(p), false);   // a bit of a bus too ("data[3]")
    if (C.style !== undefined) this.setStyle(C.style);
    if (C.maxHeight !== undefined) this.setScroll(C.maxHeight == null || C.maxHeight === '' ? 'page' : 'window', C.maxHeight || undefined);
    if (C.toolsFolded !== undefined) this.setTools(!!C.toolsFolded);
    if (C.toolsHidden !== undefined) this.setToolsHidden(C.toolsHidden ?? []);
    const gk = GAP_KEYS.filter(k => C[k] !== undefined);
    if (gk.length) this.setGaps(Object.fromEntries(gk.map(k => [k, C[k]])));   // null: the clock found (not the page's)
    const ck = CYC_KEYS.filter(k => C[k] !== undefined);
    if (ck.length) this.setCycles(Object.fromEntries(ck.map(k => [k, C[k]])));   // null: the clock found, the first edge (not the page's)
    if (C.sort !== undefined || C.sortIgnore !== undefined) {
      const pfx = this.root.querySelector('input.pfx');
      this.sort = sortDir(C.sort ?? this.sort); if (C.sortIgnore !== undefined) this.sortIgnore = prefixes(C.sortIgnore).sort((a, b) => b.length - a.length);
      if (pfx) { pfx.value = this.sortIgnore.join(','); this.fitPfx(); }
    }
    for (const [act, [own, k]] of Object.entries(FIND_VIEW)) if (C[k] !== undefined) {
      this[own] = !!C[k]; this.root.querySelector(`button[data-act=${act}]`)?.setAttribute('aria-pressed', this[own]);
    }
    for (const [act, k] of FIND_OPTS) if (C[k] !== undefined) { this[k] = !!C[k];
      this.root.querySelector(`button[data-act=${act}]`)?.setAttribute('aria-pressed', this[k]); }
    if (C.fold !== undefined) { (Array.isArray(C.fold) ? C.fold : []).forEach(p => seen(p)); this.foldSaved = null; this.collapsed = foldSet(M, C.fold);
      this.foldTouched = true; }
    // "folds": {path: true | false, "*": every group}: the groups the page's edits folded or opened (tools/viewedit.py), the rest as they are
    if (st.folds && typeof st.folds === 'object') { this.foldSaved = null; this.foldTouched = true;
      for (const [p, on] of Object.entries(st.folds)) {
        if (p === '*') { this.collapsed = on ? new Set(Object.keys(M.groups).map(Number)) : new Set(); continue; }
        const g = seen(p) && Object.values(M.groups).find(x => x.path === p); if (g) { if (on) this.collapsed.add(g.id); else this.collapsed.delete(g.id); } }
      this.collapsed = new Set([...this.collapsed].sort((x, y) => x - y)); }
    if (C.highlight !== undefined) { prefixes(C.highlight).filter(p => !p.includes('*')).forEach(p => seen(p));
      this.picks = hlPick(M, C.highlight, M.rows.concat(this.ugRows().filter(r => r.type === 'group'))); }
    if (st.paint !== undefined) { this.painted = new Map(Object.entries(st.paint || {}).filter(([p, c]) => colorOk(c) && seen(p))); this.savePaint();
      }
    if (st.radix !== undefined) {
      for (const p of [...this.radixes.keys()]) this.setRadix(p, null, true);
      for (const [p, rx] of Object.entries(st.radix || {})) if (seen(p)) this.setRadix(p, rx, true);
    }
    if (st.analog !== undefined) {
      for (const p of [...this.analogs.keys()]) this.setAnalog(p, null, true);
      for (const [p, n] of Object.entries(st.analog || {})) if (seen(p)) this.setAnalog(p, n, true);
    }
    if (st.radix !== undefined || st.analog !== undefined) this.saveRows();   // once (renderNames and draw: find() below)
    if (st.hidden !== undefined) { this.hiddenRows = new Set((st.hidden || []).filter(p => seen(p))); this.rowsStale = true; this.saveRows(); }
    if (st.bits !== undefined) { this.bitsOpen = new Set((st.bits || []).map(String).filter(p => seen(p) && isVec(this.sigByPath(p)))); this.rowsStale = true;
      this.saveRows(); }
    // "only": {modules: [paths], on} (on left out: on), null: every module; a path not of a module here: left out (said)
    if (st.only !== undefined) { const o = st.only && typeof st.only === 'object' ? st.only : null, ms = o && Array.isArray(o.modules) ? o.modules : [];
      ms.forEach(p => { if (!this.scopeOf(p)) miss.add(String(p)); });
      this.only = o ? { modules: this.onlyNorm(ms), on: o.on !== false } : null; this.onlyMemo = null; this.onlyShow(); }
    // "fsm": {mode: only | add, signals: [paths]}, null: off; a path that is no FSM here: left out (said)
    if (st.fsm !== undefined) { const o = st.fsm && typeof st.fsm === 'object' ? st.fsm : null, ps = o && Array.isArray(o.signals) ? o.signals.map(String) : [];
      const have = new Set(this.fsms().map(r => r.full)); ps.forEach(p => { if (!have.has(p)) miss.add(p); });
      const sigs = ps.filter(p => have.has(p));
      this.fsm = o && sigs.length ? { mode: FSM_MODES.includes(o.mode) ? o.mode : 'only', signals: sigs } : null; this.fsmMemo = null; this.fsmShow(); }
    if (st.bookmarks !== undefined || st.arrows !== undefined) {
      const bms = (st.bookmarks || []).filter(b => !b.signal || seen(b.signal) || (b.signal = null, true));   // on the time axis when its signal is not here
      this.bms = bmNorm(bms); this.arrows = arNorm(st.arrows || [], bms); this.saveBookmarks(); this.renderNotes();
    }
    if (st.markers !== undefined) { this.umarks = markNorm(st.markers); this.setMarks(); }
    if (st.spans !== undefined) { this.spans = spanNorm(st.spans); this.saveBookmarks(); this.draw(); }
    if (st.compare !== undefined && (st.compare || this.cmp)) this.compareResult(st.compare, true);   // a second dump compared (diff.js)
    if (st.compareShow && this.cmp && !this.cmpCant(st.compareShow) && st.compareShow !== this.cmpRun) {
      await this.compareView(st.compareShow, true); }

    if (st.select !== undefined) this.sel = (st.select && seen(st.select) && this.sigByPath(st.select)) || null;
    if (st.from != null && st.to != null && isFinite(st.from) && isFinite(st.to)) { this.span = Math.min(Math.max(st.to - st.from, this.minSpan), M.t1 - M.t0);
      this.t0 = this.clamp(st.from); }
    if (st.cursor != null && isFinite(st.cursor)) this.cursor = Math.min(Math.max(st.cursor, M.t0), M.t1);
    if (st.cursor2 !== undefined) this.cursor2 = st.cursor2 != null && isFinite(st.cursor2) ? Math.min(Math.max(st.cursor2, M.t0), M.t1) : null;
    if (st.range !== undefined) {
      const g = st.range, row = g && g.signal ? (seen(g.signal) && this.sigByPath(g.signal)) || null : null;
      const cl = x => Math.min(Math.max(x, M.t0), M.t1), a = g && cl(Math.min(g.from, g.to)), b = g && cl(Math.max(g.from, g.to));
      if (g && isFinite(g.from) && isFinite(g.to) && b > a) { this.range = [a, b]; this.rangeRow = row; this.rangeKey = null; }
      else this.range = null;   // none, or outside these waves: never one the wrong way round
    }
    if (st.edge !== undefined) { this.setEdgeKind((st.edge && st.edge.kind) || 'any'); if (this.evEl) this.evEl.value = (st.edge && st.edge.value) || ''; }
    if (st.find !== undefined && this.qEl) this.qEl.value = st.find || '';
    if (st.only !== undefined || st.fsm !== undefined) { this.allRows(); this.onlyFix(); }   // a selection the layers left out goes
    this.find(st.find !== undefined ? st.find || '' : this.q || '');   // draws; with Open the folding above is the one from before the search
    this.settingsChanged();
    return [...miss];
  }
  // Save: the state as <title>.view.json (a download); Load…: a file of it (a File, or its text)
  saveState(name) {
    const st = this.state(), a = document.createElement('a');
    a.download = name || (String(st.title || 'waves').replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'waves') + '.view.json';
    a.href = URL.createObjectURL(new Blob([JSON.stringify(st, null, 1)], { type: 'application/json' }));
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    this.toast(`saved ${a.download}`); this.log('ok', `saved the view: ${a.download}`); return st;
  }
  async loadState(file) {
    try {
      const name = file.name || 'state', text = typeof file === 'string' ? file : await file.text(), miss = await this.setState(jsonParse(text, name));
      this.undoTick();   // the load is one step to undo
      this.toast((`${name} ` +
          `loaded${miss.length ? ` · not in these waves: ${miss.length} (${miss.slice(0, 3).join(', ')}${miss.length > 3 ? ', …' : ''})` : ''}`));
      this.log(miss.length ? 'warning' : 'ok', `${name} loaded${miss.length ? `: ${miss.length} not in these waves, left out` : ''}`, { items: miss });
      return miss;
    } catch (e) { const m = e.json ? e.message : `${file.name || 'state'}: ${e.message}`;
      this.toast(m); this.logError(e, `cannot load: ${m}`); return null; }
  }
  // the colour a row is drawn in here: your paint, its own colour, its group's (groupColors); the model is not changed
  strokeOf(r) { return (r.type === 'sig' && this.painted.get(r.full)) || r.stroke || (this.groupStroke && this.groupStroke.get(r.orig || r)) || undefined; }

  /* ---------------- the plugin API (wavelens/sva.js uses only this, the rows of view.extraRows and the events) ---------------- */
  // Open… a dump: picked (with a handle where the browser keeps one: ⟳ reads the file again), a File, or a dropped one
  // (handle: a Promise of its handle) -> this viewer's waves replaced (a new viewer on the same element: the plugins
  // take it as any other); keep: the view of these waves stays (⟳)
  async openDump(file, handle = null, keep = false) {
    if (!VIEWS.has(this) && this.root.waveView && this.root.waveView !== this) return this.root.waveView.openDump(file, handle, keep);   // replaced meanwhile
    try {
      if (!file && G.showOpenFilePicker) { const [h] = await G.showOpenFilePicker({ id: 'wavelens-dump',
        types: [{ description: 'VCD dump', accept: { 'text/plain': ['.vcd'] } }] }); handle = h; file = await h.getFile(); }
      else if (!file) { this.dfile.click(); return this; }
      const gen = this.root.wlOpen = (this.root.wlOpen || 0) + 1;   // the latest Open… on this element wins, whichever reads first
      if (handle && handle.then) handle = await handle.catch(() => null);
      this.toast(`reading ${file.name}…`);
      // a File is read in pieces (a big dump is never all in memory: only the signals within dumpBudget are); something else
      // that has a text() (a plugin's, a test's) as its text
      const pieces = typeof file.stream === 'function' && typeof file.slice === 'function', text = pieces ? null : await file.text();
      const head = pieces ? await file.slice(0, 64).text() : text.slice(0, 64);   // an FST named so but given as VCD text (VS Code converts it): read
      if (gen !== this.root.wlOpen) { this.log('info', `${file.name}: replaced by a later Open…`, { quiet: true }); return this; }
      if (!VIEWS.has(this)) return this.root.waveView && this.root.waveView !== this ? this.root.waveView.openDump(file, handle, keep) : this;   // Sources…
      if (/\.fst$/i.test(file.name) && !/^\s*\$/.test(head)) { const m = 'an FST is binary: sva vcd x.fst --out x.vcd (or fst2vcd), or make html WAVES=x.fst';
        this.toast(m); this.log('warning', `${file.name}: not read: ${m}`); return this; }
      let r; const t0 = performance.now();
      // a large dump given lazy (the VS Code tab): its header, every signal read later through file.wlLoad (need, lazyAsk)
      try { const o = { name: file.name, budget: this.S.dumpBudget, lazy: !!file.wlLazy }; r = pieces ? await vcdToWaveFile(file, o) : vcdToWave(text, o); }
      catch (e) { this.dumpSaid(file.name, { error: e.message, line: e.line }); throw e; }
      if (gen !== this.root.wlOpen || !VIEWS.has(this)) return this;
      const said = [], why = new Map(), nsv = svApply(r.doc, this.opts.sv, said, why);   // the sources' labels (Sources…, the VS Code tab's wavelens.sources)
      const run = this.opts.sv && this.opts.sv.paths ? svFingerprint(this.opts.sv, r.info.date, svScopes(r.doc)).concat(svMissSaid(this.opts.sv, r.doc)) :
        [];   // the types of this run? what of them the dump has not got
      const from = this.opts.sv && this.opts.sv.paths ? 'the types file' : 'the SystemVerilog sources';
      if (nsv) r.log.push({ level: 'info', text: `labels or fields from ${from} for ${nsv} signal${nsv === 1 ? '' : 's'}` });
      const ni = [...why.values()].filter(x => x.int).length; if (ni) r.log.push({ level: 'info', text: svIntSaid(ni) });
      for (const n of ((this.opts.sv && this.opts.sv.notes) || []).concat(said, run)) r.log.push({ level: 'warning', text: 'types: ' + n });
      if (!r.shown) { this.toast(`${file.name}: no signals`); this.dumpSaid(file.name, { error: 'no signals', log: r.log, info: r.info });
        this.log('error', `${file.name}: no signals`, { items: r.log.map(logLine) }); return this; }
      const st = keep ? this.state() : null, root = this.root, opts = Object.assign({}, this.opts,
        { title: file.name, dumpSrc: { name: file.name, handle, file }, dumpDate: r.info.date, svWhy: why, svRun: run, loadCodes: file.wlLoad || null }),
        panel = keep && this.fsmPanelOf();
      this.destroy(); root.innerHTML = '';
      const v = new WaveView(root, r.doc, opts); v.panelBox = this.panelBox;   // the panels open where they were
      if (st) { delete st.title; await v.setState(st); }
      v.fsmPanelAgain(panel);   // the FSM panel stays open (⟳)
      const bad = r.log.filter(x => x.level !== 'info').length;
      v.toast((file.wlLazy ? `${file.name}: ${r.total} signals in ${r.info.scopes} modules, read as you open them` : `${file.name}: ${r.shown} of ${r.total} ` +
          `signals${r.shown < r.total ? ` (dumpBudget ${this.S.dumpBudget} changes: the levels nearest the top)` : ''}`) +
          (bad ? ` · ${bad} warning${bad === 1 ? '' : 's'} (the browser's console)` : ''));
      v.dumpLog = r.log;
      const ms = Math.round(performance.now() - t0), notes = r.log.filter(x => x.level !== 'info');
      v.log('ok', (file.wlLazy ? `${file.name}: ${r.total} signals in ${r.info.scopes} modules (read as you open them)` : `${file.name}: ${r.shown} of ` +
        `${r.total} signals`) + `${r.info.timescale ? ', ' + r.info.timescale : ''} · ${ms} ms`,
        { items: r.log.filter(x => x.level === 'info').map(logLine) });
      if (notes.length) v.log(notes.some(x => x.level === 'error') ? 'error' : 'warning',
        `${file.name}: ${notes.length} warning${notes.length === 1 ? '' : 's'}`, { items: notes.map(logLine), what: 'what the reader noticed' });
      for (const x of r.log) (x.level === 'info' ? console.info : console.warn)(`${file.name}${x.line ? ':' + x.line : ''}: ${x.level}: ${x.text}`);
      root.dispatchEvent(new CustomEvent('wavelens:dump', { detail: { name: file.name, shown: r.shown, total: r.total, log: r.log, info: r.info } }));
      return v;
    } catch (e) { if (e && e.name !== 'AbortError') { this.toast('cannot open: ' + e.message);
      this.logError(e, `cannot open ${(file && file.name) || 'the dump'}${e.line ? ` (line ${e.line})` : ''}: ${e.message}`); } return this; }
  }
  // SystemVerilog sources (Files or texts: Sources… in the bar, the VS Code tab's wavelens.sources): the names of their enums
  // and the fields of their packed structs onto the signals that have none (by name, svApply), kept in opts.sv for the next
  // read; the waves built again from their WaveJSON with the view kept -> the viewer (a new one when anything changed)
  // Two sets: the ones picked here ('manual') and the VS Code workspace's ('workspace', useSources before each read); the
  // picked win a name. Labels a set put there and no longer has go away; the dump's own tables stay.
  useSources(sv, from = 'manual') {
    const any = sv && (Object.keys(sv.enums).length || Object.keys(sv.fields).length || sv.notes.length || sv.paths);   // notes alone go to the log too
    this.opts.svFrom = Object.assign({}, this.opts.svFrom, { [from]: any ? sv : null });
    this.opts.sv = svMerge(this.opts.svFrom.workspace, this.opts.svFrom.manual) || null;
    return this;
  }
  // A types file among them (x.types.json of tools/questa/wavelens_types.tcl or svtypes.py verilator: a File named .json, or a
  // text that is JSON) gives the signals their types by path instead (svTypes): the names of the sources are not used then.
  async setSources(files, quiet = false) {
    files = [...(files || [])];
    const texts = await Promise.all(files.map(f => (typeof f === 'string' ? f : f.text())));
    const isTypes = (f, t) => (typeof f === 'string' ? /^\s*\{/.test(t) : /\.json$/i.test(f.name));
    let ty = null;
    try { for (let i = 0; i < files.length; i++) if (isTypes(files[i], texts[i])) ty = svMerge(ty, svTypes(texts[i], files[i].name || 'types file')); }
    catch (e) { this.toast(e.message); this.logError(e); return this; }
    const rest = texts.filter((t, i) => !isTypes(files[i], t)), np = ty ? Object.keys(ty.paths).length : 0;
    if (ty && rest.length) ty.notes.push(`${rest.length} SystemVerilog source${rest.length === 1 ? '' : 's'} not read: the types file names ` +
      'the signals by path');
    const sv = ty || svTables(rest);
    const ne = Object.keys(sv.enums).length, nf = Object.keys(sv.fields).length;
    this.useSources(sv, 'manual');
    for (const x of sv.notes) console.warn('wavelens: sources: ' + x);
    const names = files.map(f => f.name || (typeof f === 'string' ? 'a text' : '?')).join(', ');
    this.log('ok', ty ? `${names}: ${np} typed paths (${(ty.producer || {}).tool || 'types file'})` :
      `${names}: ${ne} enum and ${nf} struct types (typedef) in ${sv.files} file${sv.files === 1 ? '' : 's'}`);
    if (sv.notes.length) this.log('warning', `${sv.notes.length} note${sv.notes.length === 1 ? '' : 's'} of the ${ty ? 'types' : 'sources'}: not used`,
      { items: sv.notes, what: 'the list' });
    let said = sv.notes.length ? ` · ${sv.notes.length} not used (the console): ${sv.notes[0]}` : '';
    if (!ne && !nf && !np && !quiet) this.toast((sv.notes.length ? 'no labels from these files' : 'no "typedef enum" or "typedef struct packed" in ' +
      `${texts.length} file${texts.length === 1 ? '' : 's'}`) + said);
    const log = [], why = new Map(), before = JSON.stringify(this.M.src.signal), doc = structuredClone(this.M.src), n = svApply(doc, this.opts.sv, log, why);
    const run = ty ? svFingerprint(this.opts.sv, this.opts.dumpDate, svScopes(doc)).concat(this.opts.dumpSrc ? svMissSaid(this.opts.sv, doc) : []) :
      [];   // the types of the run of the dump? what of them a dump opened here has not got
    Object.assign(this.opts, { svWhy: why, svRun: run });
    for (const x of log.concat(run)) console.warn('wavelens: types: ' + x);
    const left = log.filter(x => x.endsWith('left as it is')), ni = [...why.values()].filter(x => x.int).length;
    if (left.length) this.log('warning', `${left.length} signal${left.length === 1 ? '' : 's'} left as ${left.length === 1 ? 'it is' : 'they are'}: ` +
      'another width in the dump', { items: left, what: 'the list' });
    if (ni) this.log('info', svIntSaid(ni));
    for (const x of log.filter(x => !x.endsWith('left as it is'))) this.log('warning', 'types: ' + x);
    for (const x of run) this.log('warning', 'types: ' + x);
    if (run.length && !quiet) said += ` · ${run[0]}`;
    const what = ty ? `${np} typed paths (${(ty.producer || {}).tool || 'types file'})` : `${ne} enum-typed and ${nf} struct-typed names in ${sv.files} files`;
    if (JSON.stringify(doc.signal) === before) { this.log('info', `${what}: no signal of these ${np ? 'paths' : 'names'} without labels`);
      if (!quiet && (ne || nf || np)) this.toast(`${what}: no signal of these ${np ? 'paths' : 'names'} without labels${log.length ? ' · ' + log[0] : said}`);
      return this; }
    const st = this.state(), root = this.root, opts = this.opts, panel = this.fsmPanelOf();
    this.destroy(); root.innerHTML = '';
    const v = new WaveView(root, doc, opts); v.panelBox = this.panelBox; delete st.title; await v.setState(st);
    v.fsmPanelAgain(panel);   // the FSM panel: its new FSMs
    v.toast(`${what}: labels or fields for ${n} signal${n === 1 ? '' : 's'}${said}`); v.log('ok', `labels or fields for ${n} signal${n === 1 ? '' : 's'}`);
    return v;
  }
  // a dump that could not be read: the page hears why (wavelens:dumperror {name, error, line, log}: the VS Code tab's log)
  dumpSaid(name, d) {
    this.root.dispatchEvent(new CustomEvent('wavelens:dumperror', { detail: Object.assign({ name }, d) })); }
  // ⟳: the dump again from the disk (its handle; else the file as picked, if the browser still reads it), the view kept
  async reloadDump() {
    const d = this.opts.dumpSrc; if (!d) return this;
    try { const f = d.handle ? await d.handle.getFile() : d.file; return this.openDump(f, d.handle, true); }
    catch (e) { this.toast('cannot read it again (pick it with Open…): ' + e.message); return this; }
  }
  // a tool group of the bar by its label ("go to", "assertions" …), made at the end of its line when missing (TOOL_LINES;
  // another label: a line of its own at the end); content: HTML or an element, appended to the group; -> the group's element
  addTool(group, content) {
    const tools = this.root.querySelector('.bar .tools');
    let g = [...tools.querySelectorAll('.tg')].find(t => t.dataset.tg === group);
    if (!g) {
      const ln = TOOL_LINES[group] || 'more';   // its line of the bar (a group of its own kind: a line at the end)
      let line = tools.querySelector(`.tln[data-ln="${ln}"]`);
      if (!line) { tools.insertAdjacentHTML('beforeend', toolLine(ln, '')); line = tools.lastElementChild; }
      g = document.createElement('span'); g.className = 'tg'; g.dataset.tg = group; g.innerHTML = `<span class="tl">${esc(group)}</span>`; line.appendChild(g);
      this.layoutShow();   // left out when toolsHidden names it
    }
    if (typeof content === 'string') g.insertAdjacentHTML('beforeend', content); else if (content) g.appendChild(content);
    return g;
  }
  addPanel(el) { this.root.querySelector('.bar').after(el); return el; }   // a panel under the bar (sva.js: the assertions)
  // the row of an element of the names column (an event's target) or at a y of the layout (the waves), else null
  rowAt(x) {
    if (typeof x === 'number') { const o = (this.lay || []).find(o => x >= o.y && x < o.y + o.h); return o ? o.row : null; }
    const el = x && x.closest && x.closest('.row[data-r]'); return el && el.closest('.names') === this.namesEl ? this.vis[+el.dataset.r] || null : null;
  }
  rowEl(r) { return (this.rowElOf && this.rowElOf.get(r)) || null; }   // its name row (as the names column was built last)
  // a class of a row's name (kept while the names column is built again: folding, sorting); on false: removed
  rowClass(r, cls, on = true) {
    const set = this.rowMarks.get(r) || new Set(); if (on) set.add(cls); else set.delete(cls);
    if (set.size) this.rowMarks.set(r, set); else this.rowMarks.delete(r);
    const el = this.rowEl(r); if (el) el.classList.toggle(cls, on);
    return this;
  }
  // the tooltip of a row's name instead of its own (null: its own again)
  rowTitle(r, title) {
    if (title == null) this.rowTitles.delete(r); else this.rowTitles.set(r, title);
    const el = this.rowEl(r); if (el) el.title = title ?? (r.type === 'group' ? r.title || r.path : '');
    return this;
  }
  // an event listener on a part of the viewer: 'names' (the names column), 'waves' (the canvas), 'bar', 'lists'
  listen(part, type, fn, o) { ({ names: this.namesEl, waves: this.canvas, bar: this.root.querySelector('.bar'),
    lists: this.notesEl })[part].addEventListener(type, fn, o); return this; }
  // a key on the waves (without ctrl / alt / meta) and its line in the hint ("f F next / previous failure")
  // the cursor to time t and the window to show it: `left` puts the window's start there, `center` the time in the
  // middle, else the window moves only when t is outside it; "l" goes back to the window before (plugins: ]t ]f …)
  moveTo(t, { left = null, center = false, cursor = true } = {}) {
    this.markView();
    if (left != null) { this.t0 = this.clamp(left); if (this.warpSync() && (t < this.t0 || t > this.t0 + this.span)) this.center(t); }   // t in sight
    else if (center || t < this.t0 || t > this.t0 + this.span) this.center(t);
    if (cursor) this.cursor = Math.min(Math.max(t, this.M.t0), this.M.t1);
    this.draw(); return this;
  }
  // fold (on) or open a group by its id; quiet: no render (a plugin building its rows)
  fold(id, on, quiet = false) {
    if (on) this.collapsed.add(id); else this.collapsed.delete(id);
    if (!quiet) { this.foldTouched = true; this.renderNames(); this.draw(); }
    return this;
  }
  addKey(key, fn, help) { this.keys[key] = fn; if (help) { this.hints.push(help); this.keyHelp = (this.keyHelp || []).concat([help]); } return this; }
  // ? : the keys and the mouse in a box over the viewer (Esc, ? or a click outside closes it)
  help(on = !this.helpEl) {
    const inside = this.helpEl && this.helpEl.contains(document.activeElement);   // its ✕: the keys back on the waves
    if (this.helpEl) { this.helpEl.remove(); this.helpEl = null; document.removeEventListener('pointerdown', this.offHelp, true); }
    if (!on) { if (inside) this.refocus(); return this; }
    const kb = ks => ks.map(x => `<kbd>${esc(x)}</kbd>`).join(' ');
    const plug = (this.keyHelp || []).map(h => { const m = h.match(/^((?:\S{1,3}\s+)+?)([a-z(].*)$/); return m ? [m[1].trim().split(/\s+/), m[2]] : [[], h]; });
    const sec = ([title, rows]) =>
      `<section><h4>${esc(title)}</h4><table>${rows.map(([k, t]) => `<tr><td>${kb(k)}</td><td>${esc(t)}</td></tr>`).join('')}</table></section>`;
    const el = this.helpEl = document.createElement('div'); el.className = 'wv-help'; el.setAttribute('role', 'dialog');
      el.setAttribute('aria-label', 'keys and mouse');
    el.innerHTML =
      (`<div class="hh"><b>Keys and mouse</b><span class="muted">on the waves (a click there gives them the keys); hover a button for what it ` +
        `does</span><button type="button" class="ic" aria-label="close">✕</button></div>`) +
      `<div class="hg">${HELP.concat(plug.length ? [['Plugins', plug]] : []).map(sec).join('')}</div>`;
    this.root.append(el);
    el.querySelector('button').addEventListener('click', () => this.help(false));
    el.addEventListener('keydown', e => { if (e.key === 'Escape' || e.key === '?') { e.preventDefault(); e.stopPropagation(); this.help(false);
      this.refocus(); } });
    this.offHelp = e => { if (!el.contains(e.target) && !e.target.closest('[data-act=help]')) this.help(false); };
    document.addEventListener('pointerdown', this.offHelp, { capture: true, signal: this.ac.signal });   // the click that opened it is on the ? button: ignored
    el.tabIndex = -1; el.focus({ preventScroll: true });
    return this;
  }
  renderHint() { const h = this.root.querySelector('.hint'); if (h) h.textContent = [this.hintBase, ...this.hints].join(' · '); }
  savePaint() {
    try { if (this.painted.size) localStorage.setItem(this.paintKey, JSON.stringify(Object.fromEntries(this.painted)));
      else localStorage.removeItem(this.paintKey); } catch (e) { /* private mode */ }
    if (this.unpaintBtn) this.unpaintBtn.hidden = !this.painted.size;
  }
  expandAll() { this.collapsed = new Set(); this.foldTouched = true; this.renderNames(); this.draw(); return this; }
  collapseAll() { this.collapsed = new Set(Object.keys(this.M.groups).map(Number)); this.foldTouched = true; this.renderNames(); this.draw(); return this; }
  select(row) { // the signal for edge search and bookmarks: a row, a full path / name, or null
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row) || this.M.rows.find(r => r.type === 'sig' && r.name === row);
    const out = row && (this.onlyOn() || this.hiddenRows.size) && !this.shown(row);   // hidden, or left out by Only: not selected
    this.sel = this.selAnchor = row && row.type === 'sig' && row.tr && !out ? row : null; this.selRun = new Set(); this.renderNames(); this.draw();
    const el = this.namesEl.querySelector('.row.sel');
    if (el) el.scrollIntoView({ block: 'nearest' }); else if (this.sel) this.centerRow(this.sel);   // a large column: not among its rows yet
    return this;
  }
  // cursor to the next (dir 1) / previous (-1) edge of the selected signal, or of any shown signal; the view follows
  // the edge kind of ◀ ▶ / Tab (EDGE_KINDS); "value" shows the value field (focus: the field gets the keys)
  setEdgeKind(kind, focus = false) {
    if (!hasKey(EDGE_KINDS, kind)) return this;
    this.edgeKind = kind; if (this.edgeSel) this.edgeSel.value = kind;
    if (this.evEl) { this.evEl.hidden = kind !== 'value'; if (focus && kind === 'value') this.evEl.focus(); }
    return this;
  }
  // the cursor to the next (dir 1) / previous (-1) edge of the kind (a value: becomes it, X / Z: one appears) of the
  // selected signal, or of any shown signal (want: the value, else the field's); the view follows
  edge(dir, kind = this.edgeKind, want = null) {
    let best = null, at = null;
    const w = kind === 'value' ? (want != null ? parseWant(want) : parseWant(this.evEl && this.evEl.value)) : null;
    if (kind === 'value' && !w) { if (this.evEl) { this.evEl.hidden = false; this.bad(this.evEl); this.evEl.focus(); } return this; }
    for (const s of this.sel ? [this.sel] : this.vis.filter(r => r.type === 'sig' && r.tr)) {
      const t = findEdge(s, this.cursor, dir, kind, w, this.S.radix);
      if (t != null && (best == null || (dir > 0 ? t < best : t > best))) { best = t; at = s; }
    }
    if (best == null) { if (kind === 'value' ||
      kind === 'xz') this.toast(`no ${kind === 'xz' ? 'X / Z' : w.text} ${dir > 0 ? 'after' : 'before'} the cursor${this.sel ? ' on ' + this.sel.name : ''}`);
      return this; }
    if ((kind === 'value' || kind === 'xz') && !this.sel && at) this.toast(`${at.name} ${kind === 'xz' ? 'goes X / Z' : '= ' + w.text}`);
    this.cursor = best;
    if (best < this.t0 || best > this.t0 + this.span) this.center(best);
    this.draw(); return this;
  }
  // nearest edge of signal s within px pixels of t (the initial value is not an edge), else t
  snap(s, t, px = 6) {
    if (!s || !s.tr) return t;
    const tol = px / this.pxPerT(), i = lastLE(s.tr, t);
    const near = [i, i + 1].filter(k => k > 0 && k < s.tr.length && Math.abs(s.tr[k].t - t) <= tol).sort((a, b) =>
      Math.abs(s.tr[a].t - t) - Math.abs(s.tr[b].t - t))[0];
    return near != null ? s.tr[near].t : t;
  }
  bmAt(x, y) { const pos = this.bmGeo && this.bmGeo.pos; return pos && this.bms.find(b =>
    { const p = pos.get(b.n); return p && Math.hypot(p[0] - x, p[1] - y) <= 9; }); }
  // drag on the waves: time from x (snapped to an edge of the row), signal from the row under y (the time axis: no signal)
  // dragged: the time (snapped to an edge of its row), the row under the pointer, or the axis; on the top quarter of a
  // signal row, or in the lane above it, lifted into that lane (a leader down to the signal), lower down on the row again
  moveBookmark(b, x, y, lay = this.lay || []) {
    const k = lay.findIndex(o => y >= o.y && y < o.y + o.h), o = lay[k];
    if (y < (this.oy || 0) + this.hdrH) { b.signal = null; b.lift = false; }
    else if (o && o.row.type === 'sig') { b.signal = o.row.full; b.lift = y < o.y + o.h / 4 ? true : y > o.y + o.h * 3 / 4 ? 'below' : false; }
    else if (o && o.row.type === 'lane' && o.row.ids.includes('b:' + b.signal)) b.lift = true;
    else if (o && o.row.type === 'lane' && o.row.ids.includes('b:' + b.signal + ':below')) b.lift = 'below';
    else if (o && o.row.type === 'lane') { const r = lay.slice(k + 1).find(q => q.row.type !== 'lane');
      if (r && r.row.type === 'sig') { b.signal = r.row.full; b.lift = true; } }
    const s = b.signal != null ? this.sigByPath(b.signal) : null;
    b.t = Math.min(Math.max(this.snap(s, this.tOfX(x)), this.M.t0), this.M.t1); delete b.at;   // moved: no longer at its event
    this.draw();
  }
  // bookmark: numbered circle at the cursor on the selected signal (snapped to its edge within 6 px), described below the waves
  mark(text = '') {
    const s = this.sel, t = this.cursor = this.snap(s, this.cursor);
    const n = Math.max(0, ...this.bms.map(b => b.n)) + 1;
    this.bms.push({ n, t, signal: s ? s.full : null, text, color: null, top: this.topNow() });
    this.saveBookmarks(); this.renderNotes(); this.draw();
    if (!text) this.notesEl.querySelector(`li[data-n="${n}"] input.txt`)?.focus();
    return n;
  }
  arrow(from, to, opts = {}) { this.arrows.push(...arNorm([Object.assign({ from, to }, opts)])); this.saveBookmarks(); this.renderNotes(); this.draw();
    return this; }
  // JSON for a config file / WaveJSON (t in model units: ps for timed waves, else cycles); defaults are left out
  bookmarks() { return this.bms.map(b => Object.fromEntries(Object.entries({ n: b.n, t: b.t, at: b.at, signal: b.signal, label: b.label, text: b.text,
    color: b.color, lift: b.lift || null, top: b.top, link: b.link }).filter(([, v]) => v != null && v !== ''))); }
  // a bookmark's link: the section of its view on this page (mkhtml.py: <h2 id=view>) and that view's viewer -> {h, view}
  linkTarget(l) {
    const h = l && document.getElementById(l.view), w = h && [...VIEWS].find(x => x !== this && x.root.dataset.wave &&
      x.root.dataset.wave.replace(/^WAVES\.?/, '').replace(/^\["|"\]$/g, '') === l.view);
    return h ? { h, view: w || null } : null;
  }
  followLink(b) {
    const T = this.linkTarget(b.link); if (!T) { this.toast(`no section "${b.link.view}" on this page`); return null; }
    T.h.scrollIntoView({ block: 'start' });
    const x = T.view && b.link.bookmark && T.view.bms.find(q => q.n === b.link.bookmark);
    if (x) T.view.goBm(x); else if (T.view && b.link.bookmark) T.view.toast(`no bookmark ${b.link.bookmark} here`);
    return T;
  }
  arrowList() {
    return this.arrows.map(a => Object.fromEntries(Object.entries({ from: a.from, to: a.to, shape: a.shape, head: a.head === '>' ? null : a.head,
      line: a.line === 'solid' ? null : a.line,
      color: a.color, label: a.label }).filter(([k, v]) => v != null && (v !== '' || k === 'head'))));   // head "" = no head
  }
  // your markers and groups as a state has them (empty and null left out)
  markList() { return this.umarks.map(m => Object.fromEntries(Object.entries({ t: m.t, label: m.label, color: m.color })
    .filter(([, x]) => x != null && x !== ''))); }
  spanTip(t, row) {
    const on = s => !s.signals || !s.signals.length || (row && (s.signals.includes(row.full) || s.signals.includes(row.name)));
    return this.spans.filter(s => t >= s.from && t <= s.to && on(s)).map(s => `${s.label || 'span'}: ${this.when(s.from)} … ${this.when(s.to)} (Δ ` +
      `${this.M.timed ? fmtExact(s.to - s.from) : trimNum(s.to - s.from) + ' cycles'})`).join('\n');
  }
  spanList() { return this.spans.map(s => Object.fromEntries(Object.entries({ from: s.from, to: s.to, label: s.label, color: s.color,
    signals: s.signals && s.signals.length ? [...s.signals] : null }).filter(([, x]) => x != null && x !== ''))); }
  groupList() { return this.ugroups.map(g => Object.fromEntries(Object.entries({ name: g.name, signals: [...g.signals], color: g.color })
    .filter(([, x]) => x != null))); }
  setBookmarks(list, arrows = []) { this.bms = bmNorm(list); this.arrows = arNorm(arrows, list); this.saveBookmarks(); this.renderNotes(); this.draw();
    return this; }
  loadBookmarks() { // this browser's copy (localStorage) wins over the page's "bookmarks" / "arrows"; a copy of the markers only (Clear): the page's
    const page = { bms: this.M.bookmarks.map(b => Object.assign({}, b)), arrows: this.M.arrows.map(a => Object.assign({}, a)), umarks: [],
      spans: this.M.spans.map(s => Object.assign({}, s)) };
    try {   // the spans: this browser's when it has them (the span command), else the page's
      const v = localStorage.getItem(this.bmKey), o = v == null ? null : JSON.parse(v);
      if (Array.isArray(o)) return { bms: bmNorm(o), arrows: arNorm([], o), umarks: [], spans: page.spans };
      if (o && typeof o === 'object') return Object.assign(o.bookmarks === undefined ? Object.assign(page, { umarks: markNorm(o.markers) }) :
        { bms: bmNorm(o.bookmarks), arrows: arNorm(o.arrows, o.bookmarks), umarks: markNorm(o.markers) }, { spans: o.spans ? spanNorm(o.spans) : page.spans });
    } catch (e) { /* no storage: page bookmarks */ }
    return page;
  }
  // this browser's copy; bms false (Clear): the markers only, so the page's bookmarks come back on reload
  saveBookmarks(bms = true) {
    try {
      const o = bms ? { bookmarks: this.bookmarks(), arrows: this.arrowList(), markers: this.markList(), spans: this.spanList() } :
        { markers: this.markList() };
      if (!bms && !o.markers.length) localStorage.removeItem(this.bmKey); else localStorage.setItem(this.bmKey, JSON.stringify(o));
    } catch (e) { /* private mode */ }
  }
  when(t) { return this.M.timed ? fmtExact(t) : trimNum(t); }
  // typed time: "250ns", "85.12us"; a plain number is in the unit shown (µs for "85.120 µs"), or cycles
  parseWhen(str, ref) {
    const v = String(str).trim().replace(/^cycle\s*/i, '');
    if (this.M.timed && /^-?[\d.]+(e-?\d+)?$/i.test(v)) return parseFloat(v) * (UNITS.find(([f]) => Math.abs(ref) >= f) || UNITS[UNITS.length - 1])[0];
    return parseT(v);
  }
  // the bookmark, arrow, marker and group lists under the waves (Notes), the names column (Names); while view.run
  // works (held), once at its end
  renderNotes() { if (this.held) this.held.notes = true; else this.notes.render(); }
  renderNames() { if (this.held) this.held.names = true; else this.names.render(); }
  renderNamesNow() { this.names.render(); }   // in a run too (going to a row needs the rows laid out)
  // in a run: what it has held back done now (the names, the lists, the layout), the rest of it still held (one step to undo)
  flushHeld() {
    const h = this.held; if (!h || !(h.names || h.notes || h.draw)) return;
    this.held = null;
    try { if (h.names) this.names.render(); if (h.notes) this.notes.render(); this.draw(); } finally { h.names = h.notes = h.draw = false; this.held = h; }
  }
  rowState(el, r) { this.names.state(el, r); }
  changed(list) { this.saveBookmarks(); if (list) this.renderNotes(); this.draw(); }
  layout() { return layoutRows(this.rowsL, this.rowH, this.S.laneHeight, this.hdrH); }
  frac(e) { const r = this.canvas.getBoundingClientRect(); return (e.clientX - r.left) / r.width; }
  pxPerT() { const F = this.warpSync(); return F ? F.k : this.canvas.getBoundingClientRect().width / this.span; }   // with gaps on the waves: in a part
  tOfX(x) { const F = this.warpSync(); return F ? F.T(x) : this.t0 + x / this.pxPerT(); }   // the time at x on the waves
  clamp(t) { return Math.min(Math.max(t, this.M.t0), this.M.t1 - this.span); }
  // the window puts time t at this fraction of its width (the gaps on the waves: on the screen, not in time); a new span set: as it is
  center(t, f = 0.5) {
    const F = this.warpSync();
    if (F && F.span === this.span) this.warpPlace(F, F.X(t) + F.v0 - f * F.W); else this.t0 = this.clamp(t - this.span * f);
  }
  // the window dx px on from where time t is at its left, the scale kept: a pan
  panFrom(t, dx) { const F = this.warpSync(); if (F) this.warpPlace(F, F.X(t) + F.v0 + dx); else this.t0 = this.clamp(t + dx / this.pxPerT()); }
  panPart(f) { const F = this.warpSync(); if (F) this.warpPlace(F, F.v0 + f * F.W); else this.t0 = this.clamp(this.t0 + this.span * f); }   // by a part of it
  zoom(f, at, lazy = false) { // lazy: in the next frame (the wheel: many events per frame)
    const F = this.warpSync();
    if (F) this.warpZoom(F, f, at);
    else { const tAt = this.t0 + at * this.span;
      this.span = Math.min(Math.max(this.span * f, this.minSpan), this.M.t1 - this.M.t0);
      this.t0 = this.clamp(tAt - at * this.span); }
    if (lazy) this.invalidate(); else this.draw();
  }
  fit() { this.t0 = this.M.t0; this.span = this.M.t1 - this.M.t0; this.draw(); }
  // the window to go back to with l (Questa's zoom last): the one before a zoom, fit, a jump; a run of wheel steps is one
  markView(burst = false) {
    const now = Date.now();
    if (!burst || now - (this.viewT || 0) > 500) this.lastView = { t0: this.t0, span: this.span };
    this.viewT = burst ? now : 0;
  }
  zoomLast() { const b = this.lastView; if (!b) return this; this.lastView = { t0: this.t0, span: this.span }; this.span = b.span; this.t0 = this.clamp(b.t0);
    this.draw(); return this; }
  // the window [a, b]
  zoomTo(a, b) { this.markView(); this.span = Math.min(Math.max(b - a, this.minSpan), this.M.t1 - this.M.t0); this.t0 = this.clamp(a); this.draw(); return this;
    }
  // a two-key sequence (vim): gg first signal, zR / zM open / fold every module, zc fold / zo open the selected signal's
  // module, yy copy, ]m [m next / previous bookmark, ]e [e next / previous edge; plugins add theirs (addKey(']f', …)).
  // -> whether it was one
  seq(s) {
    const sigs = () => this.vis.filter(r => r.type === 'sig' && r.tr), up = this.sel && this.sel.anc[this.sel.anc.length - 1];
    if (s === 'gg') this.select(sigs()[0] || null);
    else if (s === 'gv') { const on = !this.gapLive(); this.setGaps(on ? { gaps: true, gapView: true } : { gapView: false });
      this.toast(on ? 'the gaps on the waves' : 'the waves in continuous time'); }
    else if (s === 'zR') this.expandAll();
    else if (s === 'zM') this.collapseAll();
    else if (s === 'zc' || s === 'zo' || s === 'za') {
      if (up == null) return true;
      const shut = s === 'zc' || (s === 'za' && !this.collapsed.has(up));
      if (shut) { this.collapsed.add(up); this.sel = null; } else this.collapsed.delete(up);
      this.foldTouched = true; this.renderNames(); this.draw();
    }
    else if (s === 'yy') this.copyKey();
    else if (s === 'gl') this.groupsMenu();   // your groups (ctrl+G; this one where ctrl+G is the host's)
    else if (s === 'gm') this.marksMenu();   // the markers and the bookmarks: a list to step through
    else if (s === ']m' || s === '[m') this.stepMark(s[0] === ']' ? 1 : -1);
    else if (s === ']e' || s === '[e') this.edge(s[0] === ']' ? 1 : -1);
    else if (this.keys[s]) this.keys[s]();
    else return false;
    return true;
  }
  goMark(n) {   // the cursor to bookmark n (keys 1–9), the view follows, its signal selected
    const b = this.bms.find(x => x.n === n); if (!b) { this.toast(`no bookmark ${n}`); return this; }
    return this.goBm(b);
  }
  // going to a bookmark (1–9, ]m [m, Markers…, its list): the cursor on it, its time bookmarkLeft of the waves from the
  // left (the span kept), its signal selected, and the waves scrolled as they were when it was made: the row that was at
  // their top under the axis there again (the way to it opened); an older bookmark, or that row gone: its signal in sight
  // the bookmark's signal selected, the way to it opened (folded since: open again); then the row of then at the top,
  // else (no top, or that row is gone) the signal in sight; bookmarkLeft not a number (null, '', 'abc'): 0.2, as viewedit.py
  goBm(b) {
    const raw = this.S.bookmarkLeft, n = raw == null || raw === '' ? NaN : Number(raw), f = isFinite(n) ? Math.min(Math.max(n, 0), 0.9) : 0.2;
    this.cursor = b.t; this.center(b.t, f);
    const s = b.signal ? this.sigByPath(b.signal) : null;
    if (s) { if (s.bit != null && !this.bitsOpen.has(s.of.full)) { this.setBits(s.of, true, true); this.saveRows(); }   // a bit of a bus folded: shown
      if (s.anc.some(id => this.collapsed.has(id))) { s.anc.forEach(id => this.collapsed.delete(id)); this.foldTouched = true; }
      this.sel = s; }
    this.renderNamesNow(); this.draw();
    if (!this.topTo(b.top) && s && this.vis.includes(s) && !this.inSight(s)) this.centerRow(s);
    this.draw(); return this;
  }
  // the row at the top of the waves now, under the axis (the first whose middle is in sight; a lane or a group of yours
  // has no path: the next one) -> its full path or module path, null when nothing is drawn yet
  topNow() {
    if (!this.lay || this.oy == null) return null;
    const top = this.oy + this.hdrH;
    for (const o of this.lay) { if (o.y + o.h / 2 < top) continue; const k = o.row.full || o.row.path; if (k && o.row.type !== 'lane') return k; }
    return null;
  }
  // the row of path p at the top of the waves under the axis, the way to it opened, as far as the scroll goes -> whether
  // it is in the view
  topTo(p) {
    if (!p) return false;
    const key = r => r.full || r.path, r = this.vis.find(q => key(q) === p) || this.M.rows.find(q => key(q) === p);
    if (!r) return false;
    if (!this.vis.includes(r)) { if (!r.anc.some(id => this.collapsed.has(id))) return false;   // hidden, or out of Only: not ours to bring back
      r.anc.forEach(id => this.collapsed.delete(id)); this.foldTouched = true; this.renderNamesNow(); this.draw(); if (!this.vis.includes(r)) return false; }
    const own = this.root.classList.contains('wv-scroll');
    for (let i = 0; i < 2; i++) {   // twice: with the page, the canvas sticks under the bar only once the rows reach it
      const y = this.rowTop(r); if (y == null) return false;
      const d = y - (this.canvas.getBoundingClientRect().top + this.hdrH); if (Math.abs(d) < 1) break;
      if (own) this.bodyEl.scrollTop += d; else window.scrollBy(0, d);
    }
    this.invalidate(); return true;
  }
  // a row between the axis and the bottom of the waves on the screen
  inSight(r) {
    const q = this.rowBox(r); if (!q) return false;
    const c = this.canvas.getBoundingClientRect(), bot = this.root.classList.contains('wv-scroll') ?
      this.bodyEl.getBoundingClientRect().bottom : Math.min(window.innerHeight, c.bottom);
    return q.top >= c.top + this.hdrH - 1 && q.bottom <= bot + 1;
  }
  // the second cursor (shift+click; null: none): Δ to the cursor in time and in cycles of a clock (clockFor)
  setCursor2(t) { this.cursor2 = t == null || !isFinite(t) ? null : Math.min(Math.max(t, this.M.t0), this.M.t1); this.draw(); return this; }
  // a clock for counting cycles: the selected signal when it is one, else a 1-bit *clk* / *clock* nearest to the rows
  clockFor(rows = this.sel ? [this.sel] : []) {
    const key = rows.length === 1 ? rows[0] : rows.length ? null : 'none';   // one row or none: remembered (a draw asks twice)
    if (key && this.clkMemo && this.clkMemo[0] === key) return this.clkMemo[1];
    const near = r => rows.length ? Math.max(...rows.map(s => { let k = 0; while (k < r.anc.length && r.anc[k] === s.anc[k]) k++; return k - (r.anc.length - k);
      })) : 0;
    const c = rows.find(isClkRow) || this.M.rows.filter(isClkRow).sort((x, y) => near(y) - near(x))[0] || null;
    if (key) this.clkMemo = [key, c];
    return c;
  }
  // the rising edges of clk in (a, b]: two searches in its (cached) list of rise times, not a pass over all its changes
  cycles(clk, a, b) {
    if (!clk) return null;
    const ups = riseTimes(clk);
    const le = t => { let lo = 0, hi = ups.length; while (lo < hi) { const m = (lo + hi) >> 1; if (ups[m] <= t) lo = m + 1; else hi = m; } return lo; };
    return le(Math.max(a, b)) - le(Math.min(a, b));
  }
  cycText() {   // " · cycle 147 ↑clk": the cursor's cycle when the cycles are shown, or ''
    const d = this.cycData(); return d ? ` · cycle ${cycAt(d.ups, d.iz, this.cursor)} ↑${d.clk.name}` : '';
  }
  delta2() {   // "Δ 40 ns / 25 MHz · 4 clk" between the cursors, or ''
    if (this.cursor2 == null) return '';
    const cy = this.cycData(), d = this.cursor2 - this.cursor, clk = cy ? cy.clk : this.clockFor(), n = this.cycles(clk, this.cursor, this.cursor2);
    return `Δ ${d < 0 ? '−' : ''}${this.fmt(Math.abs(d), Math.abs(d) / 1000 || 1, Math.abs(d) || 1)}` +
      (this.M.timed && d ? ' / ' + fmtFreq(Math.abs(d)) : '') + (clk && n != null ? ` · ${n} ${clk.name}` : '');
  }
  stepMark(dir) {   // the cursor to the next / previous bookmark in time (round the ends)
    const bs = [...this.bms].sort((a, b) => a.t - b.t); if (!bs.length) return this;
    return this.goBm(bs[stepTo(bs.map(x => x.t), this.cursor, dir)]);
  }
  pageRows(dir) {   // PgUp / PgDn: the rows a page (the viewer's own scroll bar, else the page)
    if (this.root.classList.contains('wv-scroll')) this.bodyEl.scrollTop += dir * this.bodyEl.clientHeight * 0.9;
    else window.scrollBy(0, dir * window.innerHeight * 0.9);
  }
  // ctrl+F, /: the find field; with the bar off the screen (a long page scrolled down) the find group floats over the
  // waves where you are, at the top right of what you see of them, until ✕ or Esc puts it back
  focusFind() {
    if (this.S.toolsFolded) this.setTools(false);   // the field is in the tools
    const g = this.qEl.closest('.find'), b = g.getBoundingClientRect();
    // off the screen, or left out of the bar (toolsHidden): it floats
    if (!g.classList.contains('float') && (g.classList.contains('off') || b.top < 0 || b.bottom > innerHeight)) this.floatFind(true);
    this.qEl.focus({ preventScroll: true }); this.qEl.select();
  }
  floatFind(on) {
    const g = this.qEl && this.qEl.closest('.find'); if (!g || g.classList.contains('float') === !!on) return this;
    g.classList.toggle('float', !!on); this.layoutShow();   // its line, when the find is left out of the bar
    if (!on) { g.style.top = g.style.right = ''; return this; }
    const w = this.wcol.getBoundingClientRect(), gb = g.getBoundingClientRect();   // right-anchored: the count grows it leftwards
    g.style.top = Math.min(Math.max(w.top, 0) + 30, innerHeight - gb.height - 6) + 'px';
    g.style.right = Math.max(6, document.documentElement.clientWidth - Math.min(w.right, innerWidth) + 10) + 'px';
    return this;
  }
  rowOfY(y) { const o = (this.lay || []).find(o => y >= o.y && y < o.y + o.h); return o ? o.row : null; }
  // the time at x on the waves (layout y): on an edge of the signal at y within cursorSnap px (free: not), else a round
  // time at the zoom — for the cursor and the ends of a range. In a gap's column (free: not) the side of the gap nearer: a
  // place in the column is no time of the waves, so a Δ neither moves with a pixel there nor shows a time made up
  pickTime(x, y, free = false) {
    const h = !free && this.gapAt(x); if (h) return x - h.x0 < h.x1 - x ? h.p : h.q;
    const r = this.rowOfY(y), sig = r && r.type === 'sig' && r.tr ? r : null, raw = this.tOfX(x);
    const at = sig && this.S.cursorSnap > 0 && !free ? this.snap(sig, raw, this.S.cursorSnap) : raw;
    return at !== raw ? at : this.timeAt(x);
  }
  // the measured range [a, b] (shift+drag, the right button; null: none): drawn over the waves with its Δ, in the readout
  setRange(a, b, row) {
    this.range = a == null || b == null || a === b ? null : [Math.min(a, b), Math.max(a, b)];
    if (row !== undefined) this.rangeRow = row && row.type === 'sig' && row.tr ? row : null;
    this.rangeKey = null;
    this.draw(); this.root.dispatchEvent(new CustomEvent('wavelens:range', { detail: { range: this.range } })); return this;
  }
  // "Δ 20 ns / 50 MHz · 2 ↑ PCLK" / "Δ 80 ns / 12.5 MHz · 7 changes of PADDR (4 values)": the range's length (and its
  // frequency, a period that long) and, on the signal it was
  // measured on (else the selected one), its rising edges (a bit) or its changes and the values it took (a bus). All of the
  // range counts, what gaps on the waves hide too; with them the clock they count is said on any row, " · 11 ↑ PCLK": it is
  // what the band under the axis counts, and the cycles of a gap cannot be seen
  rangeText() {
    if (!this.range) return '';
    const [a, b] = this.range, s = this.rangeRow && this.rangeRow.tr ? this.rangeRow : this.sel, clk = this.gapLive() ? this.liveCuts().clk : null;
    const key = `${a}|${b}|${s ? s.full : ''}|${clk ? clk.full : ''}`;
    if (this.rangeKey === key) return this.rangeTxt;
    let more = '';
    if (s && s.tr && s.tr.length) {
      const tr = s.tr, i0 = lastLE(tr, a) + 1, i1 = lastLE(tr, b), bus = s.width > 1 || tr.some(o => o.k === '=');
      if (!bus) { let n = 0; for (let i = Math.max(i0, 1); i <= i1; i++) if (tr[i].k === '1' && tr[i - 1].k === '0') n++; if (n) more = ` · ${n} ↑ ${s.name}`; }
      else if (i1 >= i0) { const vals = new Set(); for (let i = Math.max(i0 - 1, 0); i <= i1; i++) vals.add(tr[i].bits ?? tr[i].raw ?? tr[i].v ?? tr[i].k);
        const n = i1 - i0 + 1; more = ` · ${n} change${n === 1 ? '' : 's'} of ${s.name} (${vals.size} value${vals.size === 1 ? '' : 's'})`; }
    }
    if (clk && !(s && s.full === clk.full)) { const n = this.cycles(clk, a, b); if (n) more = ` · ${n} ↑ ${clk.name}${more}`; }
    this.rangeKey = key;
    this.rangeTxt = 'Δ ' + (this.M.timed ? fmtExact(b - a) + (b > a ? ' / ' + fmtFreq(b - a) : '') : trimNum(b - a) + ' cycles') + more;
    return this.rangeTxt;
  }
  // the rows shown on the screen now (for a picture of what you see)
  // the highlighted rows as laid out (a highlighted module: it and its rows shown), for the picture and WaveDrom
  // the rows the picture and WaveDrom take: a run of selected signals (shift+click, alt+drag), else the highlighted rows
  // (gaps "only them": the signals the gaps follow)
  // the dump's signals the page left out (meta.omitted: the config's "show": false, the page reader's dumpBudget), as rows find() matches
  omitRows() { if (this.omitL) return this.omitL; const o = ((this.M.src && this.M.src.meta) || {}).omitted, out = [];
    if (o && o.paths) for (const [sc, names] of Object.entries(o.paths)) for (const n of names) out.push({ type: 'sig', name: n, full: sc ? sc + '.' + n : n,
      path: sc ? sc + '.' + n : n, scope: sc, anc: [] });
    return (this.omitL = out); }
  // null: no rows given (the screen's); [] with the gaps' "only them" and none of their signals in the view: none
  exportRows() { const m = this.gapMask(); if (m && m.length) return m;
    if (m && [...this.gapRefSet()].every(r => !this.shown(r))) return [];
    const p = this.selRun.size > 1 ? (this.rowsL || []).filter(r => this.selRun.has(r)) : this.picks.size ? this.pickedRows() : [];
    return p.length ? p : null; }
  pickedRows() { return (this.rowsL || []).filter(r => this.picks.has(r) || (r.anc || []).some(id => this.picks.has(this.M.groups[id]))); }
  // WaveDrom (WaveJSON) of signals over [a, b]: the highlighted ones (else the rows on the screen); one cell per period of
  // a clock — a 1-bit *clk* / *clock* among them, else in their modules —, else of the shortest time between changes;
  // the values at the start of each cell (as vcd2wavedrom.py samples), buses as "=" with their text in the radix shown
  toWaveDrom(a = this.t0, b = this.t0 + this.span, rows = null) {
    const mask = this.gapMask() && [...this.gapRefSet(), ...this.gapRows().aux].filter(r => this.shown(r));   // what is in the view (Hide, Only)
    const picked = mask || (this.selRun.size > 1 ? this.M.rows.filter(r => this.selRun.has(r) && this.shown(r)) : this.picks.size ?
      this.M.rows.filter(r => (this.picks.has(r) || r.anc.some(id => this.picks.has(this.M.groups[id]))) && this.shown(r)) : this.screenRows());
    const sigs = (rows || picked).filter(r => r.type === 'sig' && r.tr && r.tr.length);
    this.wdCut = null;
    const clk = (this.gapOpt().gaps && this.gapClockRow()) || this.clockFor(sigs);
    let cuts = this.cutsOf(a, b, sigs), ng = cuts.length - 1;
    const kept = cuts.reduce((n, [p, q]) => n + q - p, 0);
    let cells = clk ? clk.tr.filter(o => o.k === '1' && o.t >= a && o.t < b).map(o => o.t) : [], cellT = 0;
    if (cells.length < 2) {   // no clock here: a grid of the shortest step between changes, at most 512 cells (a gap: one null)
      const ts = [...new Set(sigs.flatMap(r => r.tr.filter(o => o.t > a && o.t < b).map(o => o.t)))].sort((x, y) => x - y);
      let step = Infinity; for (let i = 1; i < ts.length; i++) step = Math.min(step, ts[i] - ts[i - 1]);
      cellT = step = isFinite(step) ? Math.max(step, kept / 512) : kept / 64;
      cells = []; for (const [p, q] of cuts) { if (cells.length) cells.push(null); for (let t = p; t < q && cells.length < 512; t += step) cells.push(t); }
    } else {   // the cells in a stretch left out (gaps): one null, a '|'
      let j = 0; cells = cells.reduce((out, t) => { while (j < ng && t >= cuts[j + 1][0]) j++;
        if (j < ng && t >= cuts[j][1]) { if (out[out.length - 1] !== null) out.push(null); } else out.push(t); return out; }, []);
      let i = 0; for (let k = 0; i < cells.length && k < WD_CELLS; i++) if (cells[i] !== null) k++;
      const more = cells.slice(i).some(t => t !== null), last = cells[i - 1];
      // the end: the next cycle when it follows at once, else where the stretch of the last cycle ends (a gap after it is not taken in)
      const end = !more ? null : cells[i] != null ? cells[i] : (cuts.find(([p, q]) => last >= p && last < q) || [0, cells.slice(i).find(t => t !== null)])[1];
      if (end != null) {   // the first WD_CELLS cycles: the range ends where the next one starts (its gaps only), said in the foot and this.wdCut
        cells = cells.slice(0, i); this.wdCut = { cells: WD_CELLS, to: end, asked: b }; b = end;
        cuts = cuts.filter(([p]) => p < end).map(([p, q]) => [p, Math.min(q, end)]); ng = cuts.length - 1;
      }
    }
    const one = r => {
      if (r === clk && cells.length > 1 && clk.tr.some(o => o.t === cells[0])) {
        return { name: r.name, wave: 'p' + cells.slice(1).map(t => (t === null ? '|' : '.')).join('') };
      }
      let wave = '', prev = null; const data = [];
      for (const t of cells) {
        if (t === null) { wave += '|'; continue; }   // a gap: the value goes on
        const i = lastLE(r.tr, t), o = i < 0 ? { k: 'x' } : r.tr[i], key = o.k === '=' ? '=' + (o.bits ?? o.raw ?? o.v) : o.k;
        if (key === prev) { wave += '.'; continue; }
        prev = key;
        if (o.k === '=') { wave += '='; data.push(vtext(r, o, this.S.radix)); } else wave += 'udhlHL'.includes(o.k) ? o.k : o.k === '1' || o.k === '0' ||
          o.k === 'z' ? o.k : 'x';
      }
      return data.length ? { name: r.name, wave, data } : { name: r.name, wave };
    };
    const scopes = [...new Set(sigs.map(r => (r.anc.length ? r.anc[r.anc.length - 1] : -1)))], label = id =>
      (id < 0 ? '' : this.M.groups[id].path || this.M.groups[id].name);
    const signal = scopes.length > 1 ? scopes.map(id => [label(id), ...sigs.filter(r =>
      (r.anc.length ? r.anc[r.anc.length - 1] : -1) === id).map(one)]) : sigs.map(one);
    if (clk && !sigs.includes(clk) && cells.length > 1 && this.shown(clk)) signal.unshift(one(clk));   // a clock left out of the view: its cells only
    const title = String(this.opts.title || this.M.title || 'waves');
    return { signal, head: { text: `${title}: ${this.fmt(a, (b - a) / 1000, b - a)} … ${this.fmt(b, (b - a) / 1000, b - a)}` },
      foot: { text: (clk && !cellT ? `one cell per ${clk.full || clk.name} cycle` : `one cell per ${this.fmt(cellT, 1, cellT || 1)}`) +
        (ng ? `, | : ${ng} idle stretch${ng === 1 ? '' : 'es'} left out (` + cuts.slice(1).map(([q], i) => this.fmt(q - cuts[i][1], (q - cuts[i][1]) / 100,
          q - cuts[i][1])).join(', ') + ')' : '') + (this.wdCut ? `; the first ${WD_CELLS} cycles of a range to ${this.fmt(this.wdCut.asked,
          (this.wdCut.asked - a) / 1000, this.wdCut.asked - a)}` : '') }, config: { hscale: 1 } };
  }
  screenRows() {
    const top = this.oy || 0, h = this.hc || 0, hdr = this.hdrH;
    const on = (this.lay || []).filter(o => o.y + o.h > top + hdr && o.y < top + h);
    return (on.length ? on : this.lay || []).map(o => o.row);
  }
  // the waves as a picture: the rows on the screen (rows: "all": every row shown) from the range (else the window), with
  // the names, the axis, the cursor and the bookmarks, as this viewer draws them; the page's colours put in: a standalone SVG
  toSVG(o = {}) {
    const [a, b] = this.range || [this.t0, this.t0 + this.span], cs = getComputedStyle(this.root);
    const rows = Array.isArray(o.rows) ? o.rows : o.rows === 'all' ? this.rowsL : o.rows === 'picked' ? this.pickedRows() : this.screenRows();
    const from = o.from ?? a, to = o.to ?? b, cuts = o.cuts || this.cutsOf(from, to, rows);
    const svg = WaveSVG.toString(null, { view: this, from, to, rows, cuts, width: o.width || Math.max(640, this.root.clientWidth) });
    return svg.replace(/var\((--[\w-]+)\)/g, (m, n) => cs.getPropertyValue(n).trim().replace(/"/g, "'") || m);
  }
  // -> a Promise of a PNG Blob of toSVG at scale × (2: sharp on a high-density screen and in a document)
  toPNG(o = {}, scale = 2) {
    const svg = this.toSVG(o), w = +svg.match(/width="(\d+)"/)[1], h = +svg.match(/height="(\d+)"/)[1];
    if (Math.max(w, h) * scale > PNG_MAX) return Promise.reject(new Error(`${w * scale} × ${h * scale} px: a PNG stops at ${PNG_MAX}: fewer rows, or SVG`));
    return new Promise((ok, no) => {
      const img = new Image(), url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
      img.onload = () => {
        const cv = document.createElement('canvas'); cv.width = w * scale; cv.height = h * scale;
        const g = cv.getContext('2d'); g.scale(scale, scale); g.drawImage(img, 0, 0); URL.revokeObjectURL(url);
        cv.toBlob(bl => (bl ? ok(bl) : no(new Error('no PNG'))), 'image/png');
      };
      img.onerror = () => { URL.revokeObjectURL(url); no(new Error('the picture did not render')); };
      img.src = url;
    });
  }
  download(blob, name) {
    const a = document.createElement('a'); a.download = name; a.href = URL.createObjectURL(blob);
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  picName(ext) { return (String(this.opts.title || this.M.title || 'waves').replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'waves') + '.' + ext; }
  copyText(t) { try { navigator.clipboard.writeText(t).then(() => this.toast('copied: ' + t), () => this.toast(t)); } catch (e) { this.toast(t); } }
  copyKey() {   // ctrl+C / yy: while searching it ends the search; else the selected signal (or the highlighted ones) to the clipboard
    if (this.q) { this.clearFind(); return true; }
    const rows = this.sel ? [this.sel] : [...this.picks.keys()]; if (rows.length) this.copyRows(rows);
    return rows.length > 0;
  }
  goto(t, span) { this.markView(); this.span = Math.min(Math.max(span, this.minSpan), this.M.t1 - this.M.t0); this.center(t, 0.1);
    this.cursor = t; this.draw(); }
  fmt(t, ref, unitRef) { return this.M.timed ? fmtTime(t, ref, unitRef) : 'cycle ' + (t + (this.M.tick || 0)).toFixed(Math.max(0,
    Math.min(2, Math.ceil(-Math.log10(ref))))); }
  // the cursor as typed or clicked: exact (fmtExact), in the unit of the view span
  fmtCursor(t) { return this.M.timed ? fmtExact(t, this.span) : 'cycle ' + trimNum(t + (this.M.tick || 0)); }
  // a time from a click at x: rounded to a 1-2-5 step of about a pixel, so the cursor reads as a short exact number
  timeAt(x) {
    const t = this.tOfX(x), tpp = 1 / this.pxPerT(), e = 10 ** Math.floor(Math.log10(tpp));
    let q = [1, 2, 5, 10].find(m => m * e >= tpp) * e; if (this.M.timed) q = Math.max(1, q);
    return Math.min(Math.max(Math.round(Math.round(t / q) * q * 1e6) / 1e6, this.M.t0), this.M.t1);
  }
  nudge(dir) { // shift+← / →: the cursor a hundredth of the view, the view follows
    const F = this.warpSync(), t = F ? F.T(F.X(this.cursor) + dir * F.W / 100) : this.cursor + dir * this.span / 100;
    this.cursor = Math.min(Math.max(t, this.M.t0), this.M.t1);
    if (this.cursor < this.t0 || this.cursor > this.t0 + this.span) this.center(this.cursor);
    this.draw(); return this;
  }
  // A large dump read as it is needed (the VS Code tab: sva vcd --codes of its FST): the rows on the screen whose changes
  // are not read yet, asked for at once after a frame; their waves drawn when they come
  lazyAsk(lay, oy, h) {
    if (!this.lazy || !this.opts.loadCodes) return;
    const want = new Set();
    for (const o of lay) if (o.y + o.h >= oy && o.y <= oy + h) for (const r of lazyOf(this.M, o.row.orig || o.row)) if (!this.lazyWait.has(r)) want.add(r);
    if (want.size) this.need([...want]);
  }
  // the changes of these rows read (the ones not read yet; a row asked for already: that read) -> a promise, when they are
  // there; the assertions, the FSM panel and the commands ask for theirs this way
  need(rows) {
    const M = this.M, all = new Set(rows.flatMap(r => lazyOf(M, r.orig || r))), ask = [...all].filter(r => !this.lazyWait.has(r));
    if (ask.length && this.opts.loadCodes) {
      const p = (async () => {
        const text = await this.opts.loadCodes([...new Set(ask.flatMap(r => r.src.lazy || []))]);
        const got = fillRows(M, vcdSignals(vcdToWave(text, { name: this.opts.title, budget: Infinity }).doc.signal));
        for (const r of ask) if (r.lazy) this.lazyWait.delete(r);   // not in what came: asked again when it is on the screen
        if (got.length) { this.clkMemo = null; this.cycMemo = null; this.fsmSt = null; this.warpMemo = null; this.invalidate();
          if (this.fsmP) this.fsmP.render(true); }
        return got;
      })().catch(e => { for (const r of ask) this.lazyWait.delete(r); this.toast('reading the signals: ' + e.message);
        this.logError(e, 'reading the signals: ' + e.message); return []; });
      for (const r of ask) this.lazyWait.set(r, p);
    }
    return Promise.all([...all].map(r => this.lazyWait.get(r)).filter(Boolean)).then(() => this);
  }
  invalidate() { // one redraw in the next frame, however many changes ask for it
    if (!this.inv) this.inv = requestAnimationFrame(() => { this.inv = 0; if (this.root.isConnected) this.draw(); });
  }
  // the tooltip of a signal at t: its value there, the change into it and the next change ("prev → value @ t")
  valueTip(r, t) {
    const a = r.tr, i = lastLE(a, t), txt = o => o.k === '=' ? vtext(r, o, this.S.radix) : o.k;
    if (i < 0) return `${r.name}: no value yet${this.cmpTip(r, t)}`;
    const o = a[i], p = a[i - 1], n = a[i + 1];
    return `${r.name} = ${txt(o)}` + (p ? `\n${txt(p)} → ${txt(o)} @ ${this.when(o.t)}` : '') + (n ? `\nnext ${txt(n)} @ ${this.when(n.t)}` : '') +
      this.cmpTip(r, t);
  }
  valueAt(sig, t) {
    if (sig.value) return sig.value(t);
    if (!sig.tr) return '';
    const i = lastLE(sig.tr, t); if (i < 0) return '';
    const o = sig.tr[i]; return o.k === '=' ? vtext(sig, o, this.S.radix) : o.k;
  }
  // The canvas covers only the rows in view (any number of rows; a browser canvas is at most ~32k px tall): it is sticky
  // in a column as tall as all rows, and draws the layout shifted by oy = its offset in that column. The axis stays on top.
  // draw = size (the canvas and its offset) + paintFrame (the pixels) + syncReadouts (the cursor line, fields, values).
  draw() {
    if (this.held) { this.held.draw = true; return; }
    if (this.laneKey !== laneKey(this.bms, this.arrows)) {   // a bookmark or an arrow label changed: its lane?
      this.laneKey = laneKey(this.bms, this.arrows);
      if (this.laneSig !== JSON.stringify([...arrowLanes(this.vis, this.bms, this.S.arrowLabels === 'lane' ? this.arrows : [])])) this.renderNames();
    }
    this.warpSync();
    const lay = this.lay = this.layout();
    if (this.wcol.style.height !== lay.H + 'px') this.wcol.style.height = lay.H + 'px';
    if (this.sel && !this.vis.includes(this.sel)) { this.sel = null; if (this.mods) this.mods.render(); }   // folded away (the panel's ● goes)
    if (this.printing) this.paintPrint(lay);
    else { const f = this.size(lay); this.names.slide(f.oy, f.Hc); this.bmGeo = this.paintFrame(this.canvas, f.W, f.Hc, f.oy, lay, true, f.dpr);
      this.lazyAsk(lay, f.oy, f.Hc); }
    this.syncReadouts();
  }
  size(lay) { // the canvas: as wide as its column, as tall as the rows in view (at least the axis and a little more)
    const c = this.canvas, dpr = window.devicePixelRatio || 1, H = lay.H, hdr = this.hdrH;
    // the bar's height: with the page it sticks over the rows; in the viewer's own scroll box the box leaves room for it in the window
    const own = this.root.classList.contains('wv-scroll'), bar = this.root.querySelector('.bar').offsetHeight, bh = own ? 0 : bar;
    if (this.barH !== bar) { this.barH = bar; this.root.style.setProperty('--wv-bar-h', bar + 'px'); }
    // with the page: no taller than the rows left under the bar, so at their end the canvas gets shorter and its axis
    // stays under the bar while a row is in sight (the bar sticks on over the notes below)
    const W = c.getBoundingClientRect().width || 600, w = !own && this.wcol.getBoundingClientRect();
    const view = own ? this.bodyEl.clientHeight : Math.min(window.innerHeight - bh, w.bottom - Math.max(bh, w.top));
    const Hc = this.hc = Math.max(Math.min(H, hdr + 40), Math.min(H, own ? view || H : view > 0 ? view : window.innerHeight - bh));   // gone above: as before
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(Hc * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(Hc * dpr);
      c.style.height = Hc + 'px'; }
    const oy = this.oy = Math.max(0, Math.min(H - Hc, c.getBoundingClientRect().top - this.wcol.getBoundingClientRect().top));
    return { W, Hc, oy, dpr };
  }
  // one frame on canvas c (W × Hc px) showing the layout from oy down; top: with the time axis (a print page below the
  // first has none). Returns the bookmark geometry for the hit tests.
  paintFrame(c, W, Hc, oy, lay, top, dpr) {
    const hdr = top ? this.hdrH : 0, M = this.M;
    const g = c.getContext('2d'); g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const P = new CanvasPainter(g, getComputedStyle(this.root), this.S, dpr);
    P.rect(0, 0, W, Hc, 'panel');
    const F = this.wf, k = W / this.span, X = F ? F.X : t => (t - this.t0) * k, tB = this.t0 + this.span;
    const ah = this.S.headerHeight, cy = top && this.cycData();   // the time axis, the cycles' band under it
    const WP = F && warpParts(F);   // the gaps on the waves: what of them is in the window
    if (WP) { if (top) this.paintWarpHead(P, F, WP, Hc, ah, cy); }
    else {
      if (top) paintAxis(P, { from: this.t0, span: this.span, xL: 0, xR: W, y: 0, h: ah, yEnd: Hc, X, timed: M.timed, tick: M.tick, every: 1 });
      if (cy) paintCycles(P, { xL: 0, xR: W, y: ah, h: CYC_H, X, from: this.t0, to: tB, ups: cy.ups, iz: cy.iz });
      if (top && this.gapLive() && this.gapBand()) this.paintGapBand(P, null, null, ah + (cy ? CYC_H : 0));
    }
    const shown = lay.filter(o => o.y + o.h > oy + hdr && o.y < oy + Hc);
    g.save(); g.beginPath(); g.rect(0, hdr, W, Hc - hdr); g.clip(); g.translate(0, -oy);   // rows: layout coordinates, under the axis
    const late = [], sel = this.selRun && this.selRun.size ? new Set([...this.selRun, this.sel]) : this.sel;
    const body = (p, q, xa, xb, to, bg = false) => paintBody(P, M, shown, X, p, q, xa, xb, this.hl, sel, lay, this.band, to, r => this.strokeOf(r),
      r => this.collapsed.has(r.id), bg);
    const rowY = WP ? this.paintWarpBody(P, F, WP, body, late, shown, oy, Hc, hdr) : body(this.t0, tB, 0, W, late);
    paintSpans(P, this.spans, X, this.t0, tB, shown, oy + hdr, oy + Hc);
    paintMarkers(P, this.markers, X, this.t0, tB, oy + hdr, oy + Hc);
    if (!WP) this.paintDiff(P, shown, X, this.t0, tB);   // a second dump compared (diff.js): where it differs
    g.restore();
    if (this.cursor >= this.t0 && this.cursor <= tB) P.path([['M', X(this.cursor), 0], ['L', X(this.cursor), Hc]], { stroke: 'acc', w: 1.2 });
    this.paintMeasures(P, X, this.t0, tB, 0, W, 0, Hc, top ? [0, ah] : null);
    if (top) this.paintRunTag(P, W, 0, ah);   // which run of a compare the waves show
    // alt+drag
    if (this.box) { const [a, ya, b, yb] = this.box; P.path([['M', a, ya - oy], ['L', b, ya - oy], ['L', b, yb - oy], ['L', a, yb - oy], ['Z']],
      { stroke: 'acc', w: 1.2, dash: [4, 3] }); }
    // middle-button drag
    if (this.zband) { const [a, b] = this.zband.map(X).sort((p, q) => p - q); P.rect(a, 0, b - a, Hc, 'acc', 0.15);
      P.path([['M', a, 0], ['L', a, Hc], ['M', b, 0], ['L', b, Hc]], { stroke: 'acc', w: 1 }); }
    // plugin overlays over the cursor
    if (late.length) { g.save(); g.beginPath(); g.rect(0, hdr, W, Hc - hdr); g.clip(); g.translate(0, -oy); late.forEach(f => f()); g.restore(); }
    g.save(); g.translate(0, -oy);
    const geo = paintBookmarks(P, this.bms, this.arrows, X, this.t0, tB, rowY, oy + hdr, oy + Hc, oy + this.S.headerHeight / 2, this.rubber,
      laneY(lay, this.S.laneHeight), arrowFill(M, M.rows));
    g.restore();
    return geo;
  }
  // the second cursor (dashed, its Δ on a tag) and the measured range (shaded, its ends dashed, its Δ on a tag): on the
  // screen and in the picture (toSVG); X: time -> x, the waves from xL to xR and yA to yB, tag: [y, h] of the axis band
  paintMeasures(P, X, t0, t1, xL, xR, yA, yB, tag, picture = false) {   // picture: a range that is the whole picture is not shaded
    const box = (lx, tw, t, col, size) => { const [ty, th] = tag; P.rect(lx, ty + 3, tw, th - 6, 'panel');
      P.path([['M', lx, ty + 3], ['L', lx + tw, ty + 3], ['L', lx + tw, ty + th - 3], ['L', lx, ty + th - 3], ['Z']], { stroke: col, w: 1 });
        P.text(lx + tw / 2, ty + th / 2, t, { anchor: 'middle', size, fill: col }); };
    if (this.cursor2 != null && this.cursor2 >= t0 && this.cursor2 <= t1) {
      const x2 = X(this.cursor2), t = this.delta2(), tw = P.measure(t, { size: 10.5 }) + 10;
      P.path([['M', x2, yA], ['L', x2, yB]], { stroke: 'cursor2', w: 1.2, dash: [5, 3] });
      if (tag && !this.range) box(Math.min(Math.max(x2 + 4, xL + 2), xR - tw - 2), tw, t, 'cursor2', 10.5);
    }
    if (this.range && this.range[1] >= t0 && this.range[0] <= t1) {
      const [a, b] = this.range.map(t => Math.min(Math.max(X(t), xL - 1), xR + 1)), t = this.rangeText(), tw = P.measure(t, { size: 11 }) + 10;
      if (!(picture && this.range[0] <= t0 && this.range[1] >= t1)) { P.rect(a, yA, b - a, yB - yA, 'acc', 0.1);
        P.path([['M', a, yA], ['L', a, yB], ['M', b, yA], ['L', b, yB]], { stroke: 'acc', w: 1, dash: [4, 3] }); }
      if (tag) box(Math.min(Math.max((a + b) / 2, xL + tw / 2 + 2), xR - tw / 2 - 2) - tw / 2, tw, t, 'acc', 11);
    }
  }
  // print: every row, not only the ones in view — the layout in pages of canvases (at most 8000 px each) over the
  // column, at twice the screen's resolution; afterprint gives the screen canvas back
  paintPrint(lay) {
    const PAGE = 8000, W = this.canvas.getBoundingClientRect().width || this.wcol.clientWidth || 600, dpr = Math.max(2, window.devicePixelRatio || 1);
    this.wcol.querySelectorAll('canvas.wv-print').forEach(c => c.remove());
    for (let y = 0; y < lay.H; y += PAGE) {
      const h = Math.min(PAGE, lay.H - y), c = document.createElement('canvas');
      c.className = 'wv-print'; c.width = Math.round(W * dpr); c.height = Math.round(h * dpr); c.style.cssText = `top:${y}px;height:${h}px`;
      this.wcol.appendChild(c);
      this.paintFrame(c, W, h, y, lay, y === 0, dpr);
    }
  }
  print(on) { this.printing = on; if (!on) this.wcol.querySelectorAll('canvas.wv-print').forEach(c => c.remove()); this.draw(); }
  syncReadouts() { // the cursor fields, the cursor and span readout, the value column; the events of what changed
    const M = this.M, fire = (name, detail) => this.root.dispatchEvent(new CustomEvent('wavelens:' + name, { detail }));
    if (this.evCursor !== this.cursor) { this.evCursor = this.cursor; fire('cursor', { t: this.cursor }); }
    if (this.evT0 !== this.t0 || this.evSpan !== this.span) { this.evT0 = this.t0; this.evSpan = this.span; fire('view', { t0: this.t0, span: this.span }); }
    if (this.evSel !== this.sel) { this.evSel = this.sel; fire('select', { row: this.sel }); }
    this.syncCursorFields();
    this.curEl.textContent = 'cursor ' + this.fmtCursor(this.cursor) + ' · view ' + (M.timed ? fmtTime(this.span, this.span / 10,
      this.span) : this.span.toFixed(1) + ' cycles') + (this.cursor2 != null ? ' · cursor 2 ' + this.fmtCursor(this.cursor2) + ' · ' + this.delta2() : '') +
      (this.range ? ' · ' + this.rangeText() : '') + this.cycText() + this.gapReadout();
    // the bookmarks' Δ to the cursor; the bookmarks and markers at the cursor marked in their lists, as an assertion's attempt is
    if ((this.bms.length || this.umarks.length) && (this.dtAt !== this.cursor || this.dtGen !== this.notesGen)) {
      this.dtAt = this.cursor; this.dtGen = this.notesGen;
      for (const li of this.notesEl.querySelectorAll('li[data-n]')) { const b = this.bms.find(x => x.n === +li.dataset.n); if (!b) continue;
        const d = b.t - this.cursor, el = li.querySelector('.dt'); li.classList.toggle('here', d === 0);
        el.textContent = d === 0 ? '' : `${d < 0 ? '−' : '+'}${this.fmt(Math.abs(d), Math.abs(d) / 1000 || 1, Math.abs(d) || 1)}`; }
      for (const li of this.notesEl.querySelectorAll('li[data-k]')) {
        const m = this.umarks[+li.dataset.k]; li.classList.toggle('here', !!m && m.t === this.cursor); }
    }
    if (this.fsmP) this.fsmP.values();   // the FSM panel's states at the cursor
    if (this.valsAt !== this.cursor || this.valsGen !== this.namesGen || this.valsRadix !== this.S.radix) {   // value column: only when it changes
      this.valsAt = this.cursor; this.valsGen = this.namesGen; this.valsRadix = this.S.radix;
      let vi = 0;
      for (const r of this.valRows) {   // a struct's row: its whole value
        const el = this.vals[vi++], v = this.valueBoth(r.sig || r, this.cursor), w = v.length > 14 && v.includes(' ≠ ') ? v.split(' ≠ ')[0] : v;
        if (el.textContent !== w) { el.textContent = w; el.title = v.length > 6 ? v : ''; }   // cut to its column: the title has it all
      }
    }
  }
  setTheme(name) { applyLook(this.root, name || 'auto', null); this.draw(); return this; }
  // the bar's ◐: the page's next theme (auto, light, white, dark), kept in this browser; a host takes it instead
  // (wavelens:theme, cancelled: the VS Code tab opens its list of themes)
  themeNext() {
    if (!this.root.dispatchEvent(new CustomEvent('wavelens:theme', { bubbles: true, cancelable: true, detail: { view: this } }))) return this;
    const h = document.documentElement, now = THEMES.includes(h.dataset.theme) ? h.dataset.theme : 'auto';
    const next = THEME_CYCLE[(THEME_CYCLE.indexOf(now) + 1) % THEME_CYCLE.length];
    setTheme(next); try { localStorage.setItem('wavelens-theme', next); } catch (e) { /* not kept */ }
    this.toast(`theme: ${next}${next === 'auto' ? ' (the system\'s light or dark)' : ''}`); return this;
  }
  setColors(map) { applyLook(this.root, undefined, map); this.draw(); return this; }
  // the viewer leaves: observers, window listeners and pending frames go; plugins hear wavelens:destroy and take their part
  destroy() {
    if (!VIEWS.has(this)) return;
    this.ro.disconnect(); this.ac.abort();   // every listener on the root, the window and the document
    this.help(false);
    cancelAnimationFrame(this.raf); cancelAnimationFrame(this.inv); clearTimeout(this.toastT); clearTimeout(this.gapTypeT);
    if (ACTIVE.view === this) ACTIVE.view = null;
    this.closeMenu(); if (this.mods) { this.mods.ac.abort(); this.mods.el.remove(); } if (this.fsmP) { this.fsmP.ac.abort(); this.fsmP.el.remove(); }
    VIEWS.delete(this);
    this.root.dispatchEvent(new CustomEvent('wavelens:destroy'));
    if (this.root.waveView === this) delete this.root.waveView;
  }
}
