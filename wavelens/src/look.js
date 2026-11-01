/* wavelens/src/look.js — what a viewer keeps in this browser (rows, paint, look) and its gaps and cycles. */

Object.assign(WaveView.prototype, {
  loadRows() {
    let o = {};
    try { o = JSON.parse(localStorage.getItem(this.rowsKey) || '{}') || {}; } catch (e) { /* no storage */ }
    this.hiddenRows = new Set(Array.isArray(o.hidden) ? o.hidden : []); this.ugroups = groupNorm(o.groups);
    this.bitsOpen = new Set(Array.isArray(o.bits) ? o.bits.map(String) : []);
    for (const [p, n] of Object.entries(o.analog || {})) { const r = this.M.rows.find(x => x.type === 'sig' && x.full === p);
      if (r) { if (!('analog0' in r)) r.analog0 = r.analog; r.analog = n || false; this.analogs.set(p, n); } }
    for (const [p, rx] of Object.entries(o.radix || {})) { const r = this.M.rows.find(x => x.type === 'sig' && x.full === p);
      if (r && isRadix(rx)) { r.radix0 = r.radix; r.radix = rx; this.radixes.set(p, rx); } }
  },
  saveRows() {
    try {
      if (this.radixes.size || this.hiddenRows.size || this.analogs.size || this.ugroups.length || this.bitsOpen.size) localStorage.setItem(this.rowsKey,
        JSON.stringify({ radix: Object.fromEntries(this.radixes), hidden: [...this.hiddenRows], analog: Object.fromEntries(this.analogs),
          groups: this.groupList(), bits: [...this.bitsOpen] }));
      else localStorage.removeItem(this.rowsKey);
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
      if (o && Array.isArray(o.toolsHidden)) L.toolsHidden = toolNames(o.toolsHidden); return L; } catch (e) { return {}; } },
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
    this.saveLook(); this.S.toolsFolded = 'toolsFolded' in this.local ? this.local.toolsFolded : base;
    this.layoutShow(); this.draw(); return this;
  },
  // the bar's tool groups left out (their labels: "cursor", "find", "go to" …; the right button on the bar); null: the
  // settings' again. Kept in this browser, as the folding of the tools; / and ctrl+F still float the find over the waves
  setToolsHidden(list) {
    const base = toolNames(settings(GLOBAL, this.M.cfg, this.opts).toolsHidden), want = list == null ? base : toolNames(list);
    if (list == null || want.join() === base.join()) delete this.local.toolsHidden; else this.local.toolsHidden = want;
    this.saveLook(); this.S.toolsHidden = want; this.layoutShow(); this.draw(); return this;
  },
  toolGroups() { return [...new Set([...this.root.querySelectorAll('.bar .tools .tg')].map(g => g.dataset.tg).filter(Boolean))]; },
  // the classes and the buttons of the two: the rows' scroll box, the sticky bar's height (the canvas and the names' header under it)
  layoutShow() {
    const S = this.S, r = this.root, win = S.maxHeight != null && S.maxHeight !== '';
    r.classList.toggle('wv-scroll', win); r.classList.toggle('wv-tools-folded', !!S.toolsFolded);
    const sp = r.querySelector('button[data-act=spage]');   // a page that is not all in itself, a dump opened in it: Save keeps the view
    if (sp) sp.hidden = S.savePage === false || !!this.opts.dumpSrc || !!PAGE.why;
    if (win) r.style.setProperty('--wv-max-h', typeof S.maxHeight === 'number' ? S.maxHeight + 'px' : String(S.maxHeight));
    const s = r.querySelector('.bar button[data-act=scroll]'), t = r.querySelector('.bar button[data-act=tools]');
    if (s) { s.textContent = win ? 'Scroll: window' : 'Scroll: page'; s.setAttribute('aria-pressed', win); }
    if (t) { t.textContent = S.toolsFolded ? '▾ tools' : '▴'; t.setAttribute('aria-expanded', !S.toolsFolded);
      t.setAttribute('aria-label', S.toolsFolded ? 'open the tools' : 'fold the tools'); }
    // the tool groups left out (toolsHidden), a line with none left gone (not while the find floats from it), no border after the last one
    const H = new Set(toolNames(S.toolsHidden));
    for (const ln of r.querySelectorAll('.bar .tools .tln')) {
      const gs = [...ln.children].filter(g => g.classList.contains('tg')), on = gs.filter(g => !g.classList.toggle('off', H.has(g.dataset.tg)));
      gs.forEach(g => g.classList.toggle('end', g === on[on.length - 1]));
      ln.hidden = gs.length > 0 && !on.length && !gs.some(g => g.classList.contains('float'));
    }
  },
  saveLook() {
    try { if (Object.keys(this.local).length) localStorage.setItem(this.lookKey, JSON.stringify(this.local)); else localStorage.removeItem(this.lookKey);
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
    this.renderNames(); this.draw(); this.settingsChanged(); return this;
  },
  // the clock the cycles count (cycleClock, else the clock found) and its rising edges, cycle 0 at iz; null: no band (off,
  // or no clock); any: the clock even with the band off (the cursor field's c147)
  cycData(any = false) {
    const o = this.cycOpt(); if (!o.cycles && !any) return null;
    const key = JSON.stringify(o);
    if (!this.cycMemo || this.cycMemo.key !== key) {
      const clk = cycClock(this.M.rows, o.cycleClock), ups = clk ? cycUps(clk) : [];
      if (clk && clk.lazy) this.need([clk]);   // a large dump: the clock read, the band drawn when it is there (need resets the memo)
      this.cycMemo = { key, d: clk && ups.length ? { clk, ups, iz: cycZero(ups, o.cycleZero) } : null };
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
