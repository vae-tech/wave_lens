/* wavelens/src/svg.js — the static SVG figure (WaveSVG). */

/* ---------------- static SVG ---------------- */
const WaveSVG = {
  // opts: from/to (model units or "12us"), width (px, fits the wave area), cyclePx (default 40·hscale), axis (force), bg, markers;
  // view: a viewer, drawn as it shows its waves (its rows — opts.rows, a part of them —, folding, colours, highlight,
  // bookmarks, cursor; the model is the viewer's): its picture (view.toSVG)
  toString(model, opts = {}) {
    const V = opts.view, M = V ? V.M : parse(model), S = V ? V.S : settings(SVG_DEFAULTS, GLOBAL, M.cfg, opts), P = new SvgPainter(S);
    const gp = groupPaint(M, S.groupColors), strokeOf = V ? r => V.strokeOf(r) : r => r.stroke ?? gp.get(r);
    const from = parseT(opts.from) ?? M.t0, to = parseT(opts.to) ?? M.t1, fs = S.fontSize;
    const rh = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight }, bms = V ? V.bms : M.bookmarks, ars = V ? V.arrows : M.arrows;
    let C;
    if (V) C = { rows: opts.rows || V.rowsL, band: V.band, hl: V.hl };
    else {
      const sorted = orderRows(M.rows, S.sort, S.sortIgnore, S.groupOrder);
      const all = withExtra(sorted, (opts.extraRows || []).concat(...SVG_PLUGINS.map(f => f(M, S, opts) || [])), M, opts.owner || M);
      C = compose(M, S, all, M.bookmarks, M.arrows, hlPick(M, S.highlight));
    }
    const hl = C.hl;
    // gaps (opts.cuts, else the settings gaps, gapIdle, gapKeep, gapSignals): the parts of [from, to] kept, side by side, a
    // narrow column GAP px wide between; their texts (gapCount) in thin rows over each gap: under the axis the time it
    // leaves out and the cycles of the clock in it; under each signal counted (gapAux, with any texts; none marked: with
    // "edges" every one but the ones the gaps follow and the clock) what it did in the stretch left out (its rising and
    // falling edges, a bus its changes; "rise", "fall", "any": those)
    const G = V ? V.gapOpt() : S, ref = gapRefs(M.rows, G.gapSignals);
    const clk = V ? V.gapClockFor(C.rows) : gapRefs(M.rows, G.gapClock)[0] || M.rows.find(isClkRow);   // the cycles counted: gapClock, else a clock
    const cuts = opts.cuts || (V ? [[from, to]] : gapCuts(ref.length ? ref : C.rows, from, to, S, clk, M.cycle, bms.map(b => b.t), ref.length > 0));
    const ng = cuts.length - 1, kept = cuts.reduce((n, [p, q]) => n + q - p, 0), gapLab = { size: 9.5 }, gc = G.gapCount || 'clock';
    const aux = new Set(V ? V.gapRows().aux : gapRefs(M.rows, G.gapAux)), refs = new Set(V ? V.gapRefSet() : ref);
    const kind = ['edges', 'rise', 'fall', 'any'].includes(gc) ? gc : 'edges', each = gc !== 'off' && (aux.size > 0 || kind === gc);
    const counted = r => r.type === 'sig' && r.tr && r !== clk && (aux.size ? aux.has(r) : !refs.has(r));
    const ups = clk ? riseTimes(clk) : [], cyc = (p, q) => lastBefore(ups.length, j => ups[j], q, true) - lastBefore(ups.length, j => ups[j], p, true);
    const holes = cuts.slice(1).map(([q], i) => {   // cyc: the clock's cycles that start in [p, q)
      const p = cuts[i][1], d = q - p, nc = cyc(p, q), text = new Map();
      if (each) for (const r of C.rows) if (counted(r)) { const t = gapText(r, p, q, kind); if (t) text.set(r, t); }
      return { p, q, w: GAP, text, info: '+' + (M.timed ? fmtTime(d, d / 100, d) : trimNum(d)) + (nc ? ` · ${nc} ${clk.name}` : '') };
    });
    // a thin row under each signal with a text, on its module's background
    const band = ng && each ? new Map(C.band || []) : C.band;
    const rows = band === C.band ? C.rows : C.rows.flatMap(r => { if (!holes.some(h => h.text.has(r))) return [r];
      const sub = { type: 'space', name: '', depth: r.depth, anc: r.anc, height: 14, gapOf: r };
      if (band.has(r)) band.set(sub, band.get(r));
      return [r, sub]; });
    // the clock cycles under the axis (the viewer's Cycles, else the settings cycles, cycleClock, cycleZero); its clock under the names
    const cy = V ? V.cycData() : S.cycles ? (c => { const ups = c ? cycUps(c) : []; return ups.length ? { clk: c, ups, iz: cycZero(ups,
      zeroTime(S.cycleZero)) } : null; })(cycClock(M.rows, S.cycleClock)) : null, cyLab = cy && `cycles ↑ ${cy.clk.name}`;
    // a bus's width after its name (showWidth: [7:0], a field's [msb:lsb]), a little smaller and muted, as in the viewer
    const wTag = r => (S.showWidth !== false && r.name ? widthTag(r) : ''), wSt = { size: fs - 1, fill: 'muted' };
    const nameOf = r => P.measure(r.name || '', { size: fs, weight: r.type === 'group' ? 600 : 400 }), tagW = r => (wTag(r) ? 5 + P.measure(wTag(r), wSt) : 0);
    const nameW = Math.ceil(Math.max(40, cy ? P.measure(cyLab, { size: 10 }) + 12 : 0, ...rows.map(r => nameOf(r) + tagW(r) + 22 + r.depth * 12)));
    let k = ((opts.cyclePx || 40) * M.hscale) / M.cycle;
    if (opts.width) k = (opts.width - nameW - 8 - ng * GAP) / kept;
    const waveW = kept * k + ng * GAP, Wt = Math.ceil(nameW + waveW + 8);
    const showAxis = opts.axis ?? (M.timed || M.tick != null), showTock = M.tock != null;
    let y = 4;
    const titleY = y; if (V ? V.opts.title || M.title : M.title) y += 22;
    const axisY = y; if (showAxis) y += 20;
    // the clock cycles under the axis (the viewer's Cycles, else the settings cycles, cycleClock, cycleZero)
    const cycY = y; if (cy) y += CYC_H;
    const infoY = y; if (ng && gc !== 'off') y += 14;   // the gaps' times and cycles
    const lay = layoutRows(rows, rh, S.laneHeight, y); y = lay.H;
    const bodyEnd = y, tockY = y; if (showTock) y += 20;
    const footY = y; if (M.foot) y += 20;
    const notes = bms.filter(b => b.text && b.t >= from && b.t <= to), notesY = y + 6; if (notes.length) y += 8 + notes.length * 20;   // bookmark legend
    // rows of plugins
    const legend = rows.flatMap(r => (V && r.type === 'group' && V.collapsed.has(r.id) ? [] : r.legend || [])), legendY = y + 6;
      if (legend.length) y += 8 + legend.length * 18;
    const Ht = Math.ceil(y + 4), xL = nameW, xR = nameW + waveW;
    const segX = cuts.map((c, i) => xL + cuts.slice(0, i).reduce((x, [p, q], j) => x + (q - p) * k + holes[j].w, 0));   // where each part starts
    const X = !ng ? t => xL + (t - from) * k : t => {
      const i = Math.max(0, lastBefore(cuts.length, j => cuts[j][0], t)), [p, q] = cuts[i];
      return t <= q || i === ng ? segX[i] + (t - p) * k : segX[i] + (q - p) * k + (t - q) / (cuts[i + 1][0] - q) * holes[i].w;   // in a part, in a gap
    };
    const theme = V ? null : opts.theme ?? M.theme, colors = V ? {} : Object.assign({}, M.colors, opts.colors);
    const bg = V || opts.bg || (theme && theme !== 'auto') || colors.bg ? opts.bg || 'panel' : null;
    if (bg) P.rect(0, 0, Wt, Ht, bg);
    const title = V ? V.opts.title || M.title : M.title;
    if (title) P.text(nameW + waveW / 2, titleY + 9, title, { anchor: 'middle', size: 13, weight: 600, body: true });
    if (M.foot) P.text(nameW + waveW / 2, footY + 9, M.foot, { anchor: 'middle', size: 12, fill: 'muted', body: true });
    // names and group brackets (a group spans down to its last member in display order)
    const last = {};
    rows.forEach((r, i) => r.anc.forEach(id => { last[id] = i; }));
    lay.forEach(({ row, y: ry, h }, i) => {
      const c = hl ? hl.cover.get(row) : undefined;
      P.fade = hl && !hl.on.has(row) ? hl.dim : 1;
      if (typeof c === 'string') { P.rect(0, ry, xL, h, c, 0.1); P.rect(0, ry, 3, h, c); }   // a plugin's highlight
      if (!row.name) return;
      const g = row.type === 'group';
      const nx = 6 + row.depth * 12 + (g ? 0 : 8), nst = { size: fs, weight: g ? 700 : 400, fill: strokeOf(row) || 'fg' };
      P.text(nx, ry + h / 2, row.name, nst);
      if (wTag(row)) P.text(nx + P.measure(row.name, nst) + 5, ry + h / 2, wTag(row), wSt);
      if (g && last[row.id] > i) {
        const end = lay[last[row.id]], bx = 3 + row.depth * 12;
        P.path([['M', bx + 4, ry + h], ['L', bx, ry + h], ['L', bx, end.y + end.h - 3], ['L', bx + 4, end.y + end.h - 3]], { stroke: 'muted', w: 1 });
      }
    });
    P.fade = 1;
    if (cy) P.text(6, cycY + CYC_H / 2, cyLab, { size: 10, fill: 'muted' });   // the band's clock, under the names
    P.clip(xL, 0, waveW, Ht, () => {
      const step = M.timed ? null : Math.max(1, M.every);
      const sel = V ? (V.selRun && V.selRun.size ? new Set([...V.selRun, V.sel]) : V.sel) : null;   // the viewer's selection: tinted as on the screen
      let rowY;
      cuts.forEach(([p, q], i) => {   // each part: its axis and rows, inside it
        const xa = segX[i], xb = xa + (q - p) * k, go = () => {
          if (showAxis) paintAxis(P, { from: p, span: q - p, xL: xa, xR: xb, y: axisY, h: 20, yEnd: bodyEnd, X, timed: M.timed, tick: M.tick, every: M.every,
            step });
          if (showTock) paintAxis(P, { from: p, span: q - p, xL: xa, xR: xb, y: tockY, h: 20, yEnd: tockY, X, timed: M.timed, tick: M.tock, every: M.every,
            step, mid: true });
          if (cy) paintCycles(P, { xL: xa, xR: xb, y: cycY, h: CYC_H, X, from: p, to: q, ups: cy.ups, iz: cy.iz });
          rowY = paintBody(P, M, lay, X, p, q, xa, xb, hl, sel, null, band, null, strokeOf, r => !(last[r.id] > rows.indexOf(r)));
          if (V) V.paintDiff(P, lay, X, p, q);   // the viewer's picture: a dump compared, where it differs
          else if (M.compare) paintCmp(P, lay, X, p, q, cmpOfDoc(M.compare));   // the page's compare result (WaveJSON "compare")
        };
        if (ng) P.clip(xa, 0, xb - xa, Ht, go); else go();
        if (i < ng) P.clip(xb, 0, GAP, Ht, () => {   // the gap: the rows' backgrounds go on, no waves; a double dashed line
          const x0 = xb, x1 = xb + GAP, yA = gc !== 'off' ? infoY + 14 : showAxis ? axisY : lay.length ? lay[0].y : y;
          for (const ya of [showAxis && axisY, showTock && tockY]) if (ya !== false) P.rect(x0, ya, GAP, 20, 'panel2');
          if (cy) P.rect(x0, cycY, GAP, CYC_H, 'panel2');
          paintBody(P, M, lay, X, holes[i].p, holes[i].q, x0, x1, hl, sel, null, band, null, strokeOf, r => !(last[r.id] > rows.indexOf(r)), true);
          paintGapLine(P, (x0 + x1) / 2, yA, bodyEnd, G.gapLine);
        });
      });
      // the texts over each gap: the time and the cycles under the axis, a counted signal's under it
      const lab = Object.assign({ anchor: 'middle', fill: 'muted' }, gapLab), cnt = Object.assign({}, lab, { size: 10, fill: 'fg' });
      if (ng && gc !== 'off') { P.rect(xL, infoY, waveW, 14, 'panel2', 0.6); for (const o of lay) if (o.row.gapOf) P.rect(xL, o.y, waveW, o.h, 'panel2', 0.6); }
      // in the middle of each part its cycles (from the gap before to the gap after), where the gaps' texts leave room
      const used = holes.map((h, i) => { const w = P.measure(h.info, gapLab) / 2 + 6, x = segX[i + 1] - GAP / 2; return [x - w, x + w]; });
      if (ng && gc !== 'off') cuts.forEach(([p, q], i) => {
        const nc = cyc(p, q), t = nc ? `${nc} ${clk.name}` : M.timed ? fmtTime(q - p, (q - p) / 100, q - p) : trimNum(q - p);
        const x = segX[i] + (q - p) * k / 2, w = P.measure(t, gapLab) / 2;
        if (x - w > segX[i] + 2 && x + w < segX[i] + (q - p) * k - 2 && !used.some(([a, b]) => x + w > a && x - w < b)) P.text(x, infoY + 7, t, lab);
      });
      if (ng && gc !== 'off') holes.forEach((h, i) => { const xm = segX[i + 1] - GAP / 2;
        P.text(xm, infoY + 7, h.info, lab);
        for (const { row, y: ry, h: rh } of lay) { const t = row.gapOf && h.text.get(row.gapOf), tw = t && P.measure(t, cnt) + 6;
          if (t) { P.rect(xm - tw / 2, ry + 1, tw, rh - 2, 'panel2'); P.text(xm, ry + rh / 2, t, cnt); } }   // over the gap's line
      });
      const top = showAxis ? axisY + 20 : lay.length ? lay[0].y : y;
      paintSpans(P, V ? V.spans : M.spans, X, from, to, lay, top, bodyEnd);
      paintMarkers(P, V ? V.markers : (opts.markers || []).concat(M.markers), X, from, to, top, bodyEnd);
      paintBookmarks(P, bms, ars, X, from, to, rowY, top, bodyEnd, showAxis ? axisY + 10 : top + 10, null, laneY(lay, S.laneHeight), arrowFill(M, M.rows));
      if (V && V.cursor >= from && V.cursor <= to) P.path([['M', X(V.cursor), top], ['L', X(V.cursor), bodyEnd]], { stroke: 'acc', w: 1.2 });
      if (V) V.paintMeasures(P, X, from, to, xL, xR, top, bodyEnd, showAxis ? [axisY, 20] : null, true);   // the second cursor, the measured range
    });
    notes.forEach((b, i) => {
      const cy = notesY + i * 20 + 10;
      P.path(circle(14, cy, 8), { fill: b.color || 'acc' }); P.text(14, cy + 0.5, String(b.n),
        { anchor: 'middle', size: b.n > 9 ? 9 : 10.5, weight: 700, fill: 'panel' });
      P.text(28, cy, b.text, { size: 12, body: true });
    });
    legend.forEach((l, i) => {
      const cy = legendY + i * 18 + 9;
      if (l.n != null) { P.path(circle(14, cy, 7), { fill: l.color || 'acc' }); P.text(14, cy + 0.5, String(l.n),
        { anchor: 'middle', size: 9, weight: 700, fill: 'panel' }); }
      P.text(l.n != null ? 28 : 6, cy, l.text, { size: l.bold ? 12 : 11.5, weight: l.bold ? 600 : 400, body: !l.mono, fill: l.fill || 'fg' });
    });
    const css = [lookCss(colors), ...styleVars(V ? {} : Object.assign({}, M.cfg, opts)).map(([n, v]) => `${n}:${v}`)].filter(Boolean).join(';');
    const look = (THEMES.includes(theme) ? ` data-theme="${theme}"` : '') + (css ? ` style="${esc(css)}"` : '');
    return (`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${Wt} ${Ht}" width="${Wt}" height="${Ht}" role="img" ` +
        `aria-label="${esc(M.title || 'waveform')}"${look}>${P.out.join('')}</svg>`);
  },
  render(el, model, opts = {}) {
    el.classList.add('wvs'); if (opts.fit) el.classList.add('fit'); el.innerHTML = this.toString(model, Object.assign({ owner: el }, opts));
    if (!SVGS.has(el)) SVG_HOSTS.add(new WeakRef(el));
    SVGS.set(el, [model, opts]); return el;
  },
};
