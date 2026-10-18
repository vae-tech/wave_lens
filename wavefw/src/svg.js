/* wavefw/src/svg.js — the static SVG figure (WaveSVG). */

/* ---------------- static SVG ---------------- */
const WaveSVG = {
  // opts: from/to (model units or "12us"), width (px, fits the wave area), cyclePx (default 40·hscale), axis (force), bg, markers
  toString(model, opts = {}) {
    const M = parse(model), S = settings(SVG_DEFAULTS, GLOBAL, M.cfg, opts), P = new SvgPainter(S);
    const gp = groupPaint(M, S.groupColors), strokeOf = r => r.stroke ?? gp.get(r);
    const from = parseT(opts.from) ?? M.t0, to = parseT(opts.to) ?? M.t1, fs = S.fontSize;
    const sorted = orderRows(M.rows, S.sort, S.sortIgnore, S.groupOrder), rh = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight };
    const all = withExtra(sorted, (opts.extraRows || []).concat(...SVG_PLUGINS.map(f => f(M, S, opts) || [])), M, opts.owner || M);
    const C = compose(M, S, all, M.bookmarks, M.arrows, hlPick(M, S.highlight)), rows = C.rows, hl = C.hl;
    const nameW = Math.ceil(Math.max(40, ...rows.map(r => P.measure(r.name || '', { size: fs, weight: r.type === 'group' ? 600 : 400 }) + 22 + r.depth * 12)));
    let k = ((opts.cyclePx || 40) * M.hscale) / M.cycle;
    if (opts.width) k = (opts.width - nameW - 8) / (to - from);
    const waveW = (to - from) * k, Wt = Math.ceil(nameW + waveW + 8);
    const showAxis = opts.axis ?? (M.timed || M.tick != null), showTock = M.tock != null;
    let y = 4;
    const titleY = y; if (M.title) y += 22;
    const axisY = y; if (showAxis) y += 20;
    const lay = layoutRows(rows, rh, S.laneHeight, y); y = lay.H;
    const bodyEnd = y, tockY = y; if (showTock) y += 20;
    const footY = y; if (M.foot) y += 20;
    const notes = M.bookmarks.filter(b => b.text), notesY = y + 6; if (notes.length) y += 8 + notes.length * 20;   // bookmark legend
    const legend = rows.flatMap(r => r.legend || []), legendY = y + 6; if (legend.length) y += 8 + legend.length * 18;   // rows of plugins
    const Ht = Math.ceil(y + 4), xL = nameW, xR = nameW + waveW, X = t => xL + (t - from) * k;
    const theme = opts.theme ?? M.theme, colors = Object.assign({}, M.colors, opts.colors);
    const bg = opts.bg || (theme && theme !== 'auto') || colors.bg ? opts.bg || 'panel' : null;
    if (bg) P.rect(0, 0, Wt, Ht, bg);
    if (M.title) P.text(nameW + waveW / 2, titleY + 9, M.title, { anchor: 'middle', size: 13, weight: 600, body: true });
    if (M.foot) P.text(nameW + waveW / 2, footY + 9, M.foot, { anchor: 'middle', size: 12, fill: 'muted', body: true });
    // names and group brackets (a group spans down to its last member in display order)
    const last = {};
    rows.forEach((r, i) => r.anc.forEach(id => { last[id] = i; }));
    lay.forEach(({ row, y: ry, h }, i) => {
      const c = hl ? hl.cover.get(row) : undefined;
      P.fade = hl && !hl.on.has(row) ? hl.dim : 1;
      if (c !== undefined) { P.rect(0, ry, xL, h, hlTok(c), 0.1); P.rect(0, ry, 3, h, hlTok(c)); }
      if (!row.name) return;
      const g = row.type === 'group';
      P.text(6 + row.depth * 12 + (g ? 0 : 8), ry + h / 2, row.name, { size: fs, weight: g ? 700 : 400, fill: strokeOf(row) || 'fg' });
      if (g && last[row.id] > i) {
        const end = lay[last[row.id]], bx = 3 + row.depth * 12;
        P.path([['M', bx + 4, ry + h], ['L', bx, ry + h], ['L', bx, end.y + end.h - 3], ['L', bx + 4, end.y + end.h - 3]], { stroke: 'muted', w: 1 });
      }
    });
    P.fade = 1;
    P.clip(xL, 0, waveW, Ht, () => {
      const step = M.timed ? null : Math.max(1, M.every);
      if (showAxis) paintAxis(P, { from, span: to - from, xL, xR, y: axisY, h: 20, yEnd: bodyEnd, X, timed: M.timed, tick: M.tick, every: M.every, step });
      if (showTock) paintAxis(P, { from, span: to - from, xL, xR, y: tockY, h: 20, yEnd: tockY, X, timed: M.timed, tick: M.tock, every: M.every, step, mid: true });
      const rowY = paintBody(P, M, lay, X, from, to, xL, xR, hl, null, null, C.band, null, strokeOf), top = showAxis ? axisY + 20 : lay.length ? lay[0].y : y;
      paintMarkers(P, (opts.markers || []).concat(M.markers), X, from, to, top, bodyEnd);
      paintBookmarks(P, M.bookmarks, M.arrows, X, from, to, rowY, top, bodyEnd, showAxis ? axisY + 10 : top + 10, null, laneY(lay, S.laneHeight));
    });
    notes.forEach((b, i) => {
      const cy = notesY + i * 20 + 10;
      P.path(circle(14, cy, 8), { fill: b.color || 'acc' }); P.text(14, cy + 0.5, String(b.n), { anchor: 'middle', size: b.n > 9 ? 9 : 10.5, weight: 700, fill: 'panel' });
      P.text(28, cy, b.text, { size: 12, body: true });
    });
    legend.forEach((l, i) => {
      const cy = legendY + i * 18 + 9;
      if (l.n != null) { P.path(circle(14, cy, 7), { fill: l.color || 'acc' }); P.text(14, cy + 0.5, String(l.n), { anchor: 'middle', size: 9, weight: 700, fill: 'panel' }); }
      P.text(l.n != null ? 28 : 6, cy, l.text, { size: l.bold ? 12 : 11.5, weight: l.bold ? 600 : 400, body: !l.mono, fill: l.fill || 'fg' });
    });
    const css = [lookCss(colors), ...styleVars(Object.assign({}, M.cfg, opts)).map(([n, v]) => `${n}:${v}`)].filter(Boolean).join(';');
    const look = (THEMES.includes(theme) ? ` data-theme="${theme}"` : '') + (css ? ` style="${esc(css)}"` : '');
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${Wt} ${Ht}" width="${Wt}" height="${Ht}" role="img" aria-label="${esc(M.title || 'waveform')}"${look}>${P.out.join('')}</svg>`;
  },
  render(el, model, opts = {}) {
    el.classList.add('wvs'); if (opts.fit) el.classList.add('fit'); el.innerHTML = this.toString(model, Object.assign({ owner: el }, opts));
    if (!SVGS.has(el)) SVG_HOSTS.add(new WeakRef(el));
    SVGS.set(el, [model, opts]); return el;
  },
};
