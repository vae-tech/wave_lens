/* wavefw/src/paint.js — drawing: the canvas and SVG painters, signals, axis, edges, rows, markers, bookmarks and
   arrows, the arrow-label lanes and module bands. */

/* ---------------- painters: one drawing routine, two back-ends ---------------- */
class CanvasPainter {
  constructor(g, cs, S, dpr = 1) { this.g = g; this.cs = cs; this.S = S; this.dpr = dpr; this.cache = {}; this.fade = 1;
    this.mono = cs.getPropertyValue('--font-mono').trim() || 'monospace'; this.body = cs.getPropertyValue('--font-body').trim() || 'sans-serif'; }
  // a thin vertical segment (an axis tick, the cursor, a bus edge, a level change) on the middle of a device pixel: sharp
  snap(cmds, w) {
    if (w > 1.2) return cmds;
    const d = this.dpr, sx = x => (Math.round(x * d - 0.5) + 0.5) / d, line = c => c && (c[0] === 'M' || c[0] === 'L');
    return cmds.map((c, i) => line(c) && ((cmds[i + 1] && cmds[i + 1][0] === 'L' && Math.abs(cmds[i + 1][1] - c[1]) < 1e-6) ||
      (c[0] === 'L' && line(cmds[i - 1]) && Math.abs(cmds[i - 1][1] - c[1]) < 1e-6)) ? [c[0], sx(c[1]), c[2]] : c);
  }
  col(n) { // a token, "--x" / "var(--x)" (any custom property of the page), or a colour
    if (this.cache[n]) return this.cache[n];
    const p = TOK[n] || (/^--[\w-]+$/.test(n) ? n : (/^var\((--[\w-]+)\)$/.exec(n) || [])[1]);
    return (this.cache[n] = p ? this.cs.getPropertyValue(p).trim() || '#888' : n);
  }
  path(cmds, st) {
    const g = this.g; g.beginPath();
    if (st.stroke && !st.fill) cmds = this.snap(cmds, st.w || 1);
    for (const c of cmds) {
      if (c[0] === 'M') g.moveTo(c[1], c[2]); else if (c[0] === 'L') g.lineTo(c[1], c[2]);
      else if (c[0] === 'C') g.bezierCurveTo(c[1], c[2], c[3], c[4], c[5], c[6]); else g.closePath();
    }
    g.globalAlpha = (st.alpha ?? 1) * this.fade;
    if (st.fill) { g.fillStyle = this.col(st.fill); g.fill(); }
    if (st.stroke) { g.strokeStyle = this.col(st.stroke); g.lineWidth = st.w || 1; g.setLineDash(st.dash || []); g.stroke(); g.setLineDash([]); }
    g.globalAlpha = 1;
  }
  rect(x, y, w, h, fill, alpha = 1) { const g = this.g; g.globalAlpha = alpha * this.fade; g.fillStyle = this.col(fill); g.fillRect(x, y, w, h);
    g.globalAlpha = 1; }
  font(st) { return `${st.weight || 400} ${st.size || 11}px ${st.body ? this.body : this.mono}`; }
  text(x, y, s, st = {}) {
    const g = this.g; g.font = this.font(st); g.fillStyle = this.col(st.fill || 'fg');
    g.textAlign = { start: 'left', middle: 'center', end: 'right' }[st.anchor || 'start']; g.textBaseline = 'middle';
    g.globalAlpha = this.fade; g.fillText(s, x, y); g.globalAlpha = 1;
  }
  measure(s, st = {}) { this.g.font = this.font(st); return this.g.measureText(s).width; }
  clip(x, y, w, h, fn) { const g = this.g; g.save(); g.beginPath(); g.rect(x, y, w, h); g.clip(); fn(); g.restore(); }
}
let clipId = 0, measureCtx = null, LIST_ID = 0;
class SvgPainter {
  constructor(S) {
    this.out = []; this.S = S; this.fade = 1;
    const cs = getComputedStyle(document.documentElement);
    this.monoF = S.fontMono || cs.getPropertyValue('--font-mono').trim() || 'monospace'; this.bodyF = S.fontBody || cs.getPropertyValue('--font-body').trim() ||
      'sans-serif';
    measureCtx = measureCtx || document.createElement('canvas').getContext('2d');
  }
  col(n) { return !n ? 'none' : TOK[n] ? `var(${TOK[n]})` : /^--[\w-]+$/.test(n) ? `var(${n})` : esc(n); }
  path(cmds, st) {
    const f = v => Math.round(v * 100) / 100;
    const d = cmds.map(c => c[0] + c.slice(1).map(f).join(' ')).join('');
    let css = `fill:${st.fill ? this.col(st.fill) : 'none'}`;
    if (st.stroke) css += `;stroke:${this.col(st.stroke)};stroke-width:${st.w || 1}` + (st.dash ? `;stroke-dasharray:${st.dash.join(' ')}` : '');
    const op = (st.alpha ?? 1) * this.fade;
    if (op !== 1) css += `;opacity:${op}`;
    this.out.push(`<path d="${d}" style="${css}"/>`);
  }
  rect(x, y, w, h, fill, alpha = 1) { const op = alpha * this.fade;
    this.out.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" style="fill:${this.col(fill)}${op !== 1 ? ';opacity:' + op : ''}"/>`); }
  text(x, y, s, st = {}) {
    this.out.push((`<text x="${Math.round(x * 100) / 100}" y="${Math.round(y * 100) / 100}" dominant-baseline="central" ` +
        `text-anchor="${st.anchor || 'start'}" ` +
        `style="font-family:var(${st.body ? '--font-body' : '--font-mono'});font-size:${st.size || 11}px;font-weight:${st.weight || 400};` +
        `fill:${this.col(st.fill || 'fg')}${this.fade !== 1 ? ';opacity:' + this.fade : ''}">${esc(s)}</text>`));
  }
  measure(s, st = {}) { measureCtx.font = `${st.weight || 400} ${st.size || 11}px ${st.body ? this.bodyF : this.monoF}`; return measureCtx.measureText(s).width;
    }
  clip(x, y, w, h, fn) { const id = 'wvfclip' + (++clipId);
    this.out.push(`<clipPath id="${id}"><rect x="${x}" y="${y}" width="${w}" height="${h}"/></clipPath><g clip-path="url(#${id})">`); fn();
    this.out.push('</g>'); }
}

/* ---------------- shared drawing ---------------- */
function arrowHead(P, x, y, fx, fy, fill) { // filled arrow with its tip at (x, y), coming from (fx, fy)
  let dx = x - fx, dy = y - fy; const L = Math.hypot(dx, dy) || 1; dx /= L; dy /= L;
  P.path([['M', x, y], ['L', x - 7 * dx + 3 * dy, y - 7 * dy - 3 * dx], ['L', x - 7 * dx - 3 * dy, y - 7 * dy + 3 * dx], ['Z']], { fill });
}
// the colour of a value by its label or number: the signal's "enumColors", else the setting's ({"IDLE": "#ffe066",
// "3": "c5"}: a colour, a token or c3..c9), else null
function enumColor(s, o, S) {
  const m = s.enumColors || S.enumColors; if (!m || o.k !== '=') return null;
  const n = o.raw != null && /^[0-9a-f]+$/i.test(o.raw) ? String(parseInt(o.raw, 16)) : null, c = m[o.v] ?? (n != null ? m[n] : undefined);
  return c == null || c === '' ? null : /^[2-9]$/.test(String(c)) ? 'c' + c : String(c);
}
// a bus value as a number for the analog style (its radix: signed, float, fixed point; else unsigned), NaN for x / z
function analogValue(s, o, radix) {
  if (s.kind === 'real' && o.k === '=') return parseFloat(o.v);   // its number as text (inf, nan: a gap)
  if (o.k === '=' && o.raw == null) {   // a WaveDrom cell: its hex ("raw" of the converter), else its label as a number
    const h = o.hex ?? (/^0x[0-9a-f_]+$/i.test(o.v) ? o.v.slice(2).replace(/_/g, '') : null);
    if (h != null) return /^[0-9a-f]+$/i.test(h) ? Number(BigInt('0x' + h)) : NaN;
    return /^-?\d+(\.\d+)?(e[-+]?\d+)?$/i.test(o.v) ? Number(o.v) : NaN;
  }
  if (o.k !== '=' || o.raw == null || /[xz]/i.test(o.raw)) return o.k === '0' ? 0 : o.k === '1' ? 1 : NaN;
  const r = s.radix || radix || 'auto';
  if (r === 'signed' || r === 'float' || /^s?q\d+$/.test(r)) return parseFloat(decode(s, o.raw, r));
  return Number(BigInt('0x' + (o.raw || '0')));
}
// analog: a step plot between the signal's smallest and largest value (over the whole dump), the area under it shaded,
// x / z as a gap with an x mark; its range at the left
function paintAnalog(P, s, y, h, X, tA, tB, xL, xR, tEnd, sk) {
  const a = s.tr, S = P.S, r = s.radix || S.radix || 'auto';
  if (!s.an || s.an.r !== r) { let lo = Infinity, hi = -Infinity; for (const o of a) { const v = analogValue(s, o, S.radix);
    if (isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } } s.an = { r, lo, hi }; }
  const { lo, hi } = s.an, yh = y + 6, yl = y + h - 6, span = hi > lo ? hi - lo : 1, Y = v => (hi > lo ? yl - (v - lo) / span * (yl - yh) : (yh + yl) / 2);
  const cl = x => Math.min(Math.max(x, xL - 8), xR + 8), col = sk || 'bus', line = [], fill = [];
  let pv = null;
  for (let i = Math.max(lastLE(a, tA), 0); i < a.length && a[i].t <= tB; i++) {
    const o = a[i], x0 = cl(X(o.t)), x1 = cl(X(i + 1 < a.length ? a[i + 1].t : tEnd)), v = analogValue(s, o, S.radix);
    if (!isFinite(v)) { pv = null; P.path([['M', x0, (yh + yl) / 2], ['L', x1, (yh + yl) / 2]], { stroke: 'x', w: 1, dash: [3, 3] }); continue; }
    const yv = Y(v);
    line.push(pv == null ? ['M', x0, yv] : ['L', x0, yv], ['L', x1, yv]); pv = yv;
    fill.push(['M', x0, yl], ['L', x0, yv], ['L', x1, yv], ['L', x1, yl], ['Z']);
  }
  if (fill.length) P.path(fill, { fill: col, alpha: 0.14 });
  if (line.length) P.path(line, { stroke: col, w: S.traceWidth });
  if (isFinite(lo)) { const f = v => (Math.abs(v) >= 1e6 || (v && Math.abs(v) < 1e-3) ? v.toExponential(2) : String(Number(v.toPrecision(6)))),
    lab = { size: S.labelSize - 1, fill: 'muted' };
    P.text(xL + 4, yh + 2, f(hi), lab); P.text(xL + 4, yl - 2, f(lo), lab); }
}
// sk: its colour (a viewer's paint), bg: the row's background (the module band), tint: selected (the bus values too)
function paintSig(P, s, y, h, X, tA, tB, xL, xR, tEnd, sk = s.stroke, bg = 'panel', tint = false) {
  const a = s.tr; if (!a.length) return;
  if (s.analog && s.width > 1) return paintAnalog(P, s, y, h, X, tA, tB, xL, xR, tEnd, sk);
  const yh = y + 4, yl = y + h - 5, ym = (yh + yl) / 2;
  const cl = x => Math.min(Math.max(x, xL - 8), xR + 8);
  let lv = null, lvDash = null, pk = null, py = ym, pw = Infinity, xe = 0;
  const trace = sk || 'one', S = P.S, lab = { anchor: 'middle', size: S.labelSize };
  const E = EDGES[s.style] || EDGES[S.style] || EDGES.auto, slope = E.slope ?? (s.tv ? 0 : 2.5);
  const flush = x => { if (lv) { lv.push(['L', cl(x), py]); P.path(lv, { stroke: trace, w: S.traceWidth, dash: lvDash }); lv = null; } };
  for (let i = Math.max(lastLE(a, tA), 0); i < a.length && a[i].t <= tB; i++) {
    const o = a[i], xs = X(o.t);
    // burst: transitions less than 1 px apart (a clock or busy bus far zoomed out) -> one solid bar, not thousands of edges
    if (i + 2 < a.length && X(a[i + 1].t) - xs < 1 && X(a[i + 2].t) - X(a[i + 1].t) < 1) {
      let j = i + 2;
      while (j + 1 < a.length && a[j + 1].t <= tB && X(a[j + 1].t) - X(a[j].t) < 1) j++;
      const x0 = cl(xs), x1 = cl(X(a[j].t)), bit = s.width === 1 && o.k !== '=';
      flush(xs);
      P.path([['M', x0, yh], ['L', x1, yh], ['L', x1, yl], ['L', x0, yl], ['Z']], { fill: bit ? trace : sk || 'bus', alpha: bit ? 0.85 : 0.55 });
      pk = null; pw = 1; i = j - 1; continue;
    }
    xe = X(i + 1 < a.length ? a[i + 1].t : (s.end ?? tEnd));
    const w = xe - xs, sl = o.s ? 0 : Math.max(0, Math.min(slope, w / 3, pw / 3));
    if (o.k === '0' || o.k === '1' || o.k === 'u' || o.k === 'd') {
      const yv = (o.k === '1' || o.k === 'u') ? yh : yl, dash = (o.k === 'u' || o.k === 'd') ? [3, 2] : null;
      if (lv && String(dash) !== String(lvDash)) flush(xs - sl);
      if (!lv) {
        lvDash = dash;
        lv = pk === 'L' ? [['M', cl(xs - sl), py], ['L', cl(xs + sl), yv]] : pk ? [['M', cl(xs), ym], ['L', cl(xs + sl), yv]] : [['M', cl(xs), yv]];
      } else if (py !== yv) lv.push(['L', cl(xs - sl), py], ['L', cl(xs + sl), yv]);
      if (o.a && pk === 'L' && py !== yv) arrowHead(P, xs, yv < py ? ym - 4 : ym + 4, xs, yv < py ? ym + 4 : ym - 4, trace);
      pk = 'L'; py = yv;
    } else {
      flush(xs);
      if (o.k === 'z') P.path([['M', cl(xs), ym], ['L', cl(xe), ym]], { stroke: sk || 'z', w: S.traceWidth });
      else if (w < 2) P.path([['M', xs, yh], ['L', xs, yl]], { stroke: o.k === 'x' || o.bad ? 'x' : sk || 'bus', w: 1 });
      else {
        const sb = Math.min(E.bevel, w / 2), x0 = cl(xs), x1 = cl(xe);
        const hex = [['M', x0, ym], ['L', x0 + sb, yh], ['L', x1 - sb, yh], ['L', x1, ym], ['L', x1 - sb, yl], ['L', x0 + sb, yl], ['Z']];
        const isx = o.k === 'x';
        P.path(hex, { fill: isx ? 'xsoft' : s.fill || enumColor(s, o, S) || (o.c >= 3 && o.c <= 9 ? 'c' + o.c : bg) });
        if (tint && !isx) P.path(hex, { fill: 'acc', alpha: SEL_ALPHA });   // the selection shows inside the value too
        if (isx && w > 4) P.clip(x0 + sb, yh, x1 - x0 - 2 * sb, yl - yh, () => {
          const hh = yl - yh, d = []; for (let x = x0 - hh; x < x1; x += 6) d.push(['M', x, yl], ['L', x + hh, yh]);
          P.path(d, { stroke: 'x', w: 0.8, alpha: 0.7 });
        });
        P.path(hex, { stroke: isx || o.bad ? 'x' : sk || 'bus', w: S.busWidth });
        if (o.k === '=' && o.v !== '') {
          const vx0 = Math.max(x0, xL), vx1 = Math.min(x1, xR);
          if (vx1 - vx0 > 14) { const t = vtext(s, o, S.radix), tw = P.measure(t, lab); if (vx1 - vx0 > tw + 8) P.text((vx0 + vx1) / 2, ym, t, lab); }
        }
      }
      pk = o.k; py = ym;
    }
    pw = w;
  }
  flush(xe);
  for (const g of s.gaps || []) { // WaveDrom '|' gap mark: a slanted break through the row
    if (g < tA || g > tB) continue;
    const x = X(g), y0 = y + 2, y1 = y + h - 2;
    P.path([['M', x - 5, y1], ['L', x - 1, y0], ['L', x + 3, y0], ['L', x - 1, y1], ['Z']], { fill: bg });
    P.path([['M', x - 5, y1], ['L', x - 1, y0], ['M', x - 1, y1], ['L', x + 3, y0]], { stroke: 'one', w: 1 });
  }
}
function paintAxis(P, o) { // o: { from, span, xL, xR, y, h, yEnd, X, timed, tick, every, cycles, mid }; mid: labels in the cycles (foot.tock)
  const W = o.xR - o.xL;
  P.rect(o.xL, o.y, W, o.h, 'panel2');
  const step = o.step || (o.timed ? niceStep(90 * o.span / W) : Math.max(niceStep(60 * o.span / W, true), o.every || 1));
  const first = Math.ceil(o.from / step) * step, d = [], lab = [];
  const off = o.mid ? step / 2 : 0;
  for (let t = first; t + off <= o.from + o.span + 1e-9; t += step) {
    const x = o.X(t + off); if (!o.mid) d.push(['M', x, o.y + o.h - 6], ['L', x, o.yEnd]);
    lab.push([x, o.timed ? fmtTime(t, step) : String(Math.round((t + (o.tick || 0)) * 100) / 100)]);
  }
  P.path(d, { stroke: 'line', w: 1, alpha: 0.6 });
  for (const [x, s] of lab) { // keep edge labels inside the axis band
    const hw = P.measure(s, { size: 10.5 }) / 2 + 2;
    P.text(Math.min(Math.max(x, o.xL + hw), o.xR - hw), o.y + o.h / 2, s, { anchor: 'middle', size: 10.5, fill: 'muted' });
  }
}
function edgeGeom(e, x1, y1, x2, y2) { // WaveDrom edge shapes -> path, label point, arrow "from" points
  const dx = x2 - x1, dy = y2 - y1;
  switch (e.shape) {
    case '~': return { d: [['M', x1, y1], ['C', x1 + 0.7 * dx, y1, x1 + 0.3 * dx, y2, x2, y2]], m: [x1 + dx / 2, y1 + dy / 2], s: [x1 + 0.7 * dx, y1],
      e: [x1 + 0.3 * dx, y2] };
    case '-~': return { d: [['M', x1, y1], ['C', x1 + 0.7 * dx, y1, x2, y2, x2, y2]], m: [x1 + 0.66 * dx, y1 + 0.3 * dy], s: [x1 + 0.7 * dx, y1],
      e: [x1 + 0.7 * dx, y1] };
    case '~-': return { d: [['M', x1, y1], ['C', x1, y1, x1 + 0.3 * dx, y2, x2, y2]], m: [x1 + 0.34 * dx, y1 + 0.7 * dy], s: [x1 + 0.3 * dx, y2],
      e: [x1 + 0.3 * dx, y2] };
    case '-|': return { d: [['M', x1, y1], ['L', x2, y1], ['L', x2, y2]], m: [x1 + dx / 2, y1], s: [x2, y1], e: [x2, y1] };
    case '|-': return { d: [['M', x1, y1], ['L', x1, y2], ['L', x2, y2]], m: [x1 + dx / 2, y2], s: [x1, y2], e: [x1, y2] };
    case '-|-': return { d: [['M', x1, y1], ['L', x1 + dx / 2, y1], ['L', x1 + dx / 2, y2], ['L', x2, y2]], m: [x1 + dx / 2, y1 + dy / 2], s: [x1 + dx / 2, y1],
      e: [x1 + dx / 2, y2] };
    default: return { d: [['M', x1, y1], ['L', x2, y2]], m: [x1 + dx / 2, y1 + dy / 2], s: [x2, y2], e: [x1, y1] };
  }
}
function paintEdges(P, M, rowY, X) {
  for (const e of M.edges) {
    const A = M.nodes[e.from], B = M.nodes[e.to];
    if (!A || !B || !rowY.has(A.row) || !rowY.has(B.row)) continue;
    const x1 = X(A.t), y1 = rowY.get(A.row), x2 = X(B.t), y2 = rowY.get(B.row), g = edgeGeom(e, x1, y1, x2, y2);
    P.path(g.d, { stroke: 'acc', w: 1.2 });
    const near = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5;
    if (e.ae) { const f = near(g.e, [x2, y2]) ? [x1, y1] : g.e; arrowHead(P, x2, y2, f[0], f[1], 'acc'); }
    if (e.as) { const f = near(g.s, [x1, y1]) ? [x2, y2] : g.s; arrowHead(P, x1, y1, f[0], f[1], 'acc'); }
    if (e.label) {
      const tw = P.measure(e.label, { size: 10.5 });
      P.rect(g.m[0] - tw / 2 - 3, g.m[1] - 7, tw + 6, 14, 'panel');
      P.text(g.m[0], g.m[1], e.label, { anchor: 'middle', size: 10.5, fill: 'acc', weight: 600 });
    }
  }
  for (const [ch, n] of Object.entries(M.nodes)) { // lowercase nodes are labelled, as in stock WaveDrom
    if (!/^[a-z]$/.test(ch) || !rowY.has(n.row)) continue;
    const x = X(n.t), y = rowY.get(n.row);
    P.rect(x - 4, y - 6, 8, 12, 'panel'); P.text(x, y, ch, { anchor: 'middle', size: 10, fill: 'muted' });
  }
}
const SEL_ALPHA = 0.12;   // the accent over a selected row, its bus values included
// rows (signals, group bands, separators), gaps, edges and markers inside [xL, xR]
// late: an array that takes the plugin overlays instead of drawing them (the viewer draws them over its cursor)
// strokeOf: row -> its colour where a viewer or a figure changes it (paint, groupColors); default row.stroke
// allLay: every row (edges may end off screen); folded(group row): no header shade
// bgOnly: the backgrounds, the selection and the separators only (the column of a gap in a figure)
function paintBody(P, M, lay, X, tA, tB, xL, xR, hl, sel, allLay, band, late, strokeOf = r => r.stroke, folded = () => false, bgOnly = false) {
  const rowY = new Map(), sep = [], edge = [], over = new Set();
  let pb;
  if (allLay) for (const o of allLay) if (o.row.type === 'sig') rowY.set(o.row, o.y + o.h / 2);
  for (const { row, y, h } of lay) {
    const c = hl ? hl.cover.get(row) : undefined;
    P.fade = 1;   // the module band does not dim with the rows: the modules stay apart while something is highlighted
    const b = band ? band.get(row) : undefined;
    if (b !== undefined) { if (pb !== undefined && b !== pb) edge.push(['M', xL, y + 0.5], ['L', xR, y + 0.5]); pb = b; }
    if (b === 1) P.rect(xL, y, xR - xL, h, 'band');
    P.fade = hl && row.type !== 'lane' && !hl.on.has(row) ? hl.dim : 1;
    if (row.type === 'lane') { P.rect(xL, y, xR - xL, h, 'panel2', 0.45); continue; }
    // a folded module: the plain background
    if (row.type === 'group') { if (!folded(row)) { P.rect(xL, y, xR - xL, h, 'panel2'); P.rect(xL, y, xR - xL, h, 'fg', 0.08); } edge.push(['M', xL, y + 0.5],
      ['L', xR, y + 0.5]); pb = undefined; }
    // a struct: its whole value
    if (row.type === 'group' && row.sig && row.sig.tr.length && !bgOnly) {
      paintSig(P, row.sig, y, h, X, tA, tB, xL, xR, M.t1, strokeOf(row.sig) || 'bus', 'panel');
    }
    if (typeof c === 'string') P.rect(xL, y, xR - xL, h, c, 0.1);   // a plugin's highlight
    const isSel = sel instanceof Set ? sel.has(row) : row === sel;   // sel: the selected row, or a Set (shift+click: a run)
    if (isSel) P.rect(xL, y, xR - xL, h, 'acc', SEL_ALPHA);
    if (row.type !== 'space') sep.push(['M', xL, y + h - 0.5], ['L', xR, y + h - 0.5]);
    if (bgOnly) continue;
    if (row.draw) row.draw(P, { y, h, X, tA, tB, xL, xR });
    if (row.overlay) over.add(row.overlay);
    if (row.type === 'sig') { if (row.tr) paintSig(P, row, y, h, X, tA, tB, xL, xR, M.t1, strokeOf(row), b === 1 ? 'band' : 'panel', isSel);
      rowY.set(row, y + h / 2); }
  }
  P.fade = 1;
  P.path(sep, { stroke: 'line', w: 1, alpha: 0.5 });
  P.path(edge, { stroke: 'line', w: 1 });   // module borders
  if (bgOnly) return rowY;
  if (allLay) {   // an overlay that also draws on other rows (f.rows: the signals it marks) runs when one of those is shown
    const on = new Set(lay.map(o => o.row));
    for (const o of allLay) { const f = o.row.overlay; if (f && f.rows && !over.has(f) && f.rows.some(r => on.has(r))) over.add(f); }
  }
  if (over.size) {
    const yA = lay.length ? lay[0].y : 0, yB = lay.length ? lay[lay.length - 1].y + lay[lay.length - 1].h : 0;   // the rows drawn: from, to
    const pos = new Map((allLay || lay).map(o => [o.row, o])), go = () => { for (const f of over) f(P, { pos, X, tA, tB, xL, xR, yA, yB }); };
    if (late) late.push(go); else go();
  }
  paintEdges(P, M, rowY, X);
  return rowY;
}
const GAP = 8;   // px: the column of a gap in a figure
// the line of a gap at xm from y0 to y1 (setting gapLine): "dashdot" a thin straight dash-dot line (unlike a bookmark's
// dotted one), "wave" a wavy one, "waves" two thin wavy lines, "zigzag", "double" two straight dashed lines
function paintGapLine(P, xm, y0, y1, style) {
  const wavy = (x, a, h) => { const d = [['M', x, y0]]; let k = 0;
    for (let y = y0; y < y1; y += h, k++) {
      const s = k % 2 ? -a : a, ye = Math.min(y + h, y1);
      d.push(['C', x + s, y + (ye - y) / 3, x + s, y + 2 * (ye - y) / 3, x, ye]);
    }
    return d; };
  if (style === 'double') return P.path([['M', xm - 1.5, y0], ['L', xm - 1.5, y1], ['M', xm + 1.5, y0], ['L', xm + 1.5, y1]], { stroke: 'muted', w: 1,
    dash: [6, 3] });
  if (style === 'zigzag') { const d = [['M', xm, y0]]; let k = 0; for (let y = y0 + 3; y < y1; y += 3, k++) d.push(['L', xm + (k % 2 ? -1.8 : 1.8), y]);
    return P.path(d, { stroke: 'muted', w: 0.8 }); }
  if (style === 'waves') return P.path([...wavy(xm - 1.6, 1.6, 5), ...wavy(xm + 1.6, 1.6, 5)], { stroke: 'muted', w: 0.8 });
  if (style === 'wave') return P.path(wavy(xm, 2, 6), { stroke: 'muted', w: 0.9, dash: [5, 2, 1.5, 2] });
  return P.path([['M', xm, y0], ['L', xm, y1]], { stroke: 'muted', w: 0.9, dash: [6, 2, 1.5, 2] });
}
function paintMarkers(P, markers, X, tA, tB, y0, y1) {
  for (const m of markers) {
    if (m.t < tA || m.t > tB) continue;
    const x = X(m.t); P.path([['M', x, y0], ['L', x, y1]], { stroke: 'muted', w: 1, dash: [3, 3] });
    if (m.label) { P.rect(x + 1, y0 + 2, P.measure(m.label, { size: 10 }) + 4, 12, 'panel'); P.text(x + 3, y0 + 8, m.label, { size: 10, fill: 'muted' }); }
  }
}

const circle = (x, y, r) => { const k = 0.5523 * r; return [['M', x - r, y], ['C', x - r, y - k, x - k, y - r, x, y - r],
  ['C', x + k, y - r, x + r, y - k, x + r, y],
  ['C', x + r, y + k, x + k, y + r, x, y + r], ['C', x - k, y + r, x - r, y + k, x - r, y], ['Z']]; };
// arrow labels in lanes: a thin row inserted under the upper end of a labelled arrow (above the row when both ends share
// it; the top when an end is on the time axis), so the text never covers a signal; and the lifted bookmarks of a signal
// ("lift"), in one lane line above it ("b:" + its path), the nearest to the row.
// -> Map(row index it follows -> [arrow index | "b:" + path])
function arrowLanes(rows, bms, arrows) {
  const idx = new Map(), lanes = new Map(), has = n => bms.some(b => b.n === n);
  rows.forEach((r, i) => { if (r.type === 'sig' && !r.same) idx.set(r.full, i); });
  rows.forEach((r, i) => { if (r.type === 'sig' && r.same && !idx.has(r.full)) idx.set(r.full, i); });   // copies: when the original is not shown
  const rowOf = n => { const b = bms.find(x => x.n === n); return b && b.signal != null && idx.has(b.signal) ? idx.get(b.signal) : -1; };
  arrows.forEach((a, i) => {
    if (!a.label || !has(a.from) || !has(a.to)) return;
    const r1 = rowOf(a.from), r2 = rowOf(a.to), at = Math.max(-1, r1 === r2 ? r1 - 1 : Math.min(r1, r2));
    if (!lanes.has(at)) lanes.set(at, []);
    lanes.get(at).push(i);
  });
  for (const b of bms) {
    const r = b.lift ? rowOf(b.n) : -1, id = 'b:' + b.signal; if (r < 0) continue;
    if (!lanes.has(r - 1)) lanes.set(r - 1, []);
    if (!lanes.get(r - 1).includes(id)) lanes.get(r - 1).push(id);
  }
  return lanes;
}
function withLanes(rows, lanes) { // rows with {type: 'lane', ids: [arrow index]} rows spliced in
  const out = [], lane = i => { if (lanes.has(i)) out.push({ type: 'lane', ids: lanes.get(i), name: '', depth: 0, anc: [] }); };
  lane(-1); rows.forEach((r, i) => { out.push(r); lane(i); });
  return out;
}
// module shading: signal rows alternate between two backgrounds each time their module (enclosing group) changes, so
// the border between two modules' waves shows. -> Map(row -> 0 | 1); lanes and spacers take the band of the row before.
function bands(rows) {
  const out = new Map(); let band = 0, prev;
  for (const r of rows) {
    if (r.type === 'sig') { const k = r.anc.length ? r.anc[r.anc.length - 1] : -1; if (prev !== undefined && k !== prev) band ^= 1; prev = k; }
    if (r.type !== 'group') out.set(r, band);
  }
  return out;
}
// What the viewer and the static SVG both draw from the rows in display order: the rows with the arrow-label lanes,
// the module bands and the highlight state (picks: Map(row -> colour), all: the rows the highlight covers).
function compose(M, S, rows, bms, arrows, picks, all) {
  const lanes = S.arrowLabels === 'lane' ? arrowLanes(rows, bms || [], arrows || []) : new Map(), out = withLanes(rows, lanes);
  return { rows: out, lanes, band: S.moduleShading && Object.keys(M.groups).length ? bands(out) : null, hl: hlState(M, picks, S.dim, all || out) };
}
// rows -> [{row, y, h}] from y down (rh: the height of a sig / group / space row, laneH: of one arrow label); .H: the end
// a row's height: a lane of n labels, a plugin row's own, an analog signal "analog" rows high (true: 3), else its type's
const analogRows = r => (r.analog === true ? 3 : Math.max(1, Math.min(12, +r.analog || 0)));
const rowHeight = (row, rh, laneH) => (row.type === 'lane' ? laneH * row.ids.length : row.height ||
  (row.type === 'sig' && row.analog ? rh.sig * analogRows(row) : rh[row.type]));
function layoutRows(rows, rh, laneH, y = 0) {
  const lay = rows.map(row => { const h = rowHeight(row, rh, laneH), o = { row, y, h }; y += h; return o; });
  lay.H = y; return lay;
}
// the bookmarks and arrows as far as the lanes depend on them: the lanes are worked out again only when this changes
const laneKey = (bms, arrows) => JSON.stringify([(bms || []).map(b => [b.n, b.signal, !!b.lift]), (arrows || []).map(a => [a.from, a.to, !!a.label])]);
const laneY = (lay, h) => { const m = new Map(); for (const o of lay) if (o.row.type === 'lane') o.row.ids.forEach((a, k) => m.set(a, o.y + h * k + h / 2));
  return m; };
// numbered circles on their signal rows (on the axis when the row is not shown), guide lines, arrows between bookmarks;
// rubber: {from, x, y} = an arrow being drawn. Returns {pos: n -> [x, y], mids: [[arrow index, x, y]]} for hit tests.
function paintBookmarks(P, bms, arrows, X, tA, tB, rowY, y0, y1, yAxis, rubber, lanes) {
  const at = new Map(), pos = new Map(), mids = [];
  for (const [r, y] of rowY) if (!r.same) at.set(r.full, y);
  for (const [r, y] of rowY) if (r.same && !at.has(r.full)) at.set(r.full, y);
  const lifted = new Map();   // n -> the y of its signal row, under the circle in the lane
  for (const b of bms) {
    const y = b.signal != null && at.has(b.signal) ? at.get(b.signal) : yAxis, ly = b.lift && lanes && y !== yAxis ? lanes.get('b:' + b.signal) : null;
    pos.set(b.n, [X(b.t), ly ?? y]); if (ly != null) lifted.set(b.n, y);
  }
  for (const b of bms) if (b.t >= tA && b.t <= tB) { const x = X(b.t); P.path([['M', x, y0], ['L', x, y1]],
    { stroke: b.color || 'acc', w: 1, dash: [2, 3], alpha: 0.45 }); }
  const near = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5;
  // on the circle
  const tip = (p, f) => { const L = Math.hypot(p[0] - f[0], p[1] - f[1]) || 1; return [p[0] - 9 * (p[0] - f[0]) / L, p[1] - 9 * (p[1] - f[1]) / L]; };
  arrows.forEach((a, i) => {
    const A = pos.get(a.from), B = pos.get(a.to); if (!A || !B) return;
    const col = a.color || 'acc', ly0 = lanes && lanes.get(i);
    // both ends on one row: a dimension line in its lane above the row, not through the signal
    if (ly0 != null && Math.abs(A[1] - B[1]) < 0.5 && Math.abs(ly0 - A[1]) > 9) {
      const up = ly0 < A[1] ? -1 : 1;
      P.path([['M', A[0], A[1] + up * 9], ['L', A[0], ly0 - up * 4], ['M', B[0], B[1] + up * 9], ['L', B[0], ly0 - up * 4]],
        { stroke: col, w: 1, dash: [2, 2], alpha: 0.8 });
      P.path([['M', A[0], ly0], ['L', B[0], ly0]], { stroke: col, w: 1.4, dash: AR_LINES[a.line] });
      if (a.head.includes('>')) arrowHead(P, B[0], ly0, A[0], ly0, col);
      if (a.head.includes('<')) arrowHead(P, A[0], ly0, B[0], ly0, col);
      const mx = (A[0] + B[0]) / 2;
      if (a.label) { const tw = P.measure(a.label, { size: 10.5 }); P.rect(mx - tw / 2 - 3, ly0 - 7, tw + 6, 14, 'panel');
        P.text(mx, ly0, a.label, { anchor: 'middle', size: 10.5, fill: col, weight: 600 }); }
      mids.push([i, mx, ly0]); return;
    }
    const g = edgeGeom({ shape: a.shape }, A[0], A[1], B[0], B[1]);
    P.path(g.d, { stroke: col, w: 1.4, dash: AR_LINES[a.line] });
    if (a.head.includes('>')) { const f = near(g.e, B) ? A : g.e, p = tip(B, f); arrowHead(P, p[0], p[1], f[0], f[1], col); }
    if (a.head.includes('<')) { const f = near(g.s, A) ? B : g.s, p = tip(A, f); arrowHead(P, p[0], p[1], f[0], f[1], col); }
    const ly = lanes && lanes.get(i), m = ly != null ? [g.m[0], ly] : g.m;   // in its lane, else on the arrow
    if (a.label) {
      const tw = P.measure(a.label, { size: 10.5 });
      if (ly != null && Math.abs(g.m[1] - ly) > 9) P.path([['M', m[0], ly + (g.m[1] > ly ? 6 : -6)], ['L', g.m[0], g.m[1]]],
        { stroke: col, w: 1, dash: [1.5, 2.5], alpha: 0.7 });
      P.rect(m[0] - tw / 2 - 3, m[1] - 7, tw + 6, 14, 'panel'); P.text(m[0], m[1], a.label, { anchor: 'middle', size: 10.5, fill: col, weight: 600 });
    }
    mids.push([i, m[0], m[1]]);
  });
  const R = rubber && pos.get(rubber.from);
  if (R) { P.path([['M', R[0], R[1]], ['L', rubber.x, rubber.y]], { stroke: 'acc', w: 1.4, dash: [4, 3] }); arrowHead(P, rubber.x, rubber.y, R[0], R[1], 'acc');
    }
  for (const b of bms) {
    if (b.t < tA || b.t > tB) continue;
    const [x, y] = pos.get(b.n);
    if (lifted.has(b.n)) P.path([['M', x, y + 8], ['L', x, lifted.get(b.n)]], { stroke: b.color || 'acc', w: 1.2 });   // a leader down to its signal
    P.path(circle(x, y, 8), { fill: b.color || 'acc', stroke: 'panel', w: 1.5 });
    P.text(x, y + 0.5, String(b.n), { anchor: 'middle', size: b.n > 9 ? 9 : 10.5, weight: 700, fill: 'panel' });
  }
  return { pos, mids };
}
