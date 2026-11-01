/* wavelens/src/warp.js — the gaps on the waves (setting gapView): the viewer's time axis with the idle stretches cut out. */

const GAP_H = 14;   // px: the band of the gaps' texts under the axis
const WARP_RUNS = 48;   // the most parts painted one by one in a frame; more: together, the gaps over them
// The screen of a window with gaps: the parts kept (cuts) side by side, a gap's column g px wide between them. v is a place
// on the whole cut-out axis (k px per unit of time kept); a window is the stretch [v0, v0 + W] of it, and its ends are the
// real times t0 and t0 + span, as without gaps: the cursor, the bookmarks and every jump stay in time.
function warpOf(cuts) {
  const cum = [0]; for (const [p, q] of cuts) cum.push(cum[cum.length - 1] + q - p);
  return { cuts, cum, n: cuts.length, kept: cum[cuts.length] };
}
// time -> place: in a part by k, in a gap by the part of it passed
function warpV(w, t, k, g) {
  const c = w.cuts, i = Math.max(0, lastBefore(w.n, j => c[j][0], t)), [p, q] = c[i];
  if (t <= q || i === w.n - 1) return k * (w.cum[i] + t - p) + g * i;
  return k * w.cum[i + 1] + g * (i + (t - q) / (c[i + 1][0] - q));
}
// place -> time
function warpT(w, v, k, g) {
  const c = w.cuts, i = Math.max(0, lastBefore(w.n, j => k * w.cum[j] + g * j, v)), [p, q] = c[i], x = v - (k * w.cum[i] + g * i), len = (q - p) * k;
  if (x <= len || i === w.n - 1) return p + x / k;
  return q + (g > 0 ? Math.min((x - len) / g, 1) : 0) * (c[i + 1][0] - q);
}
// the scale that shows the times [a, b] on W px: a gap GAP px wide, narrower when so many that they would take over the waves
function warpFit(w, a, b, W) {
  const kept = warpV(w, b, 1, 0) - warpV(w, a, 1, 0), holes = warpV(w, b, 0, 1) - warpV(w, a, 0, 1), g = Math.min(GAP, 0.35 * W / Math.max(1, holes));
  return { k: kept > 0 ? (W - g * holes) / kept : 0, g };
}
// the parts of [a, b] among the parts kept; none: [a, b]
function clipCuts(cuts, a, b) {
  const out = cuts.filter(([p, q]) => q > a && p < b).map(([p, q]) => [Math.max(p, a), Math.min(q, b)]);
  return out.length ? out : [[a, b]];
}
// the frame's parts in the window, its gaps (p, q: all of the gap; x0, x1: its column) and the runs painted together
function warpParts(F) {
  const c = F.w.cuts, a = F.t0, b = F.t0 + F.span, parts = [], holes = [];
  for (let i = Math.max(0, lastBefore(F.w.n, j => c[j][0], a)); i < F.w.n && c[i][0] <= b; i++) {
    const p = Math.max(c[i][0], a), q = Math.min(c[i][1], b);
    if (q > p) parts.push([p, q]);
    if (i + 1 < F.w.n && c[i + 1][0] > a && c[i][1] < b) holes.push({ p: c[i][1], q: c[i + 1][0], x0: F.X(c[i][1]), x1: F.X(c[i + 1][0]) });
  }
  const step = Math.ceil(parts.length / WARP_RUNS), runs = [];
  for (let i = 0; i < parts.length; i += step) runs.push([parts[i][0], parts[Math.min(i + step, parts.length) - 1][1]]);
  return { parts, holes, runs };
}
// the time axis over the parts: one step for all, a part without a tick says where it starts; no label over another
function paintWarpAxis(P, o) {   // o: { parts, k, W, y, h, yEnd, X, timed, tick }
  P.rect(0, o.y, o.W, o.h, 'panel2');
  const step = o.timed ? niceStep(90 / o.k) : Math.max(niceStep(60 / o.k, true), 1), d = [], lab = [];
  const txt = t => (o.timed ? fmtTime(t, step) : String(Math.round((t + (o.tick || 0)) * 100) / 100));
  for (const [p, q] of o.parts) {
    const n = lab.length;
    for (let t = Math.ceil(p / step) * step; t <= q + 1e-9; t += step) {
      const x = o.X(t); d.push(['M', x, o.y + o.h - 6], ['L', x, o.yEnd]); lab.push([x, txt(t)]);
    }
    if (lab.length === n) lab.push([o.X(p) + 2, txt(p), true]);
  }
  P.path(d, { stroke: 'line', w: 1, alpha: 0.6 });
  let end = -Infinity;
  for (const [x, s, left] of lab) {
    const hw = P.measure(s, { size: 10.5 }) / 2 + 2, xm = Math.min(Math.max(left ? x + hw : x, hw), o.W - hw);
    if (xm - hw < end) continue;
    P.text(xm, o.y + o.h / 2, s, { anchor: 'middle', size: 10.5, fill: 'muted' }); end = xm + hw + 4;
  }
}

Object.assign(WaveView.prototype, {
  gapLive() { const g = this.gapOpt(); return g.gaps && g.gapView; },
  gapBand() { return this.gapOpt().gapCount !== 'off'; },
  // the height of the header: the axis, the cycles, the gaps' texts
  headH() { return this.S.headerHeight + (this.cycData() ? CYC_H : 0) + (this.gapLive() && this.gapBand() ? GAP_H : 0); },
  // the gaps on the waves: the signals they look at, the changes of those and the parts kept. The parts are worked out over
  // the whole dump from every row drawn, not from those on the screen: the scroll of the rows moves no gap. idle and keep
  // changed: only the parts again, so a value being typed shows at once on a long dump
  liveCuts() {
    if (!this.gapLive()) return null;
    const G = this.gapRows(), M = this.M, ref = [...G.ref], g = this.gapOpt();
    const rows = (this.rowsL || []).filter(r => r.type === 'sig' || (r.type === 'group' && r.sig));
    const same = (a, b) => a.length === b.length && a.every((r, i) => r === b[i]);
    let m = this.warpMemo;
    if (!m || m.gck !== G.clk || m.run !== this.cmpRun || !same(m.rows, rows) || !same(m.ref, ref)) {
      const sigs = ref.length ? ref : rows, clk = this.gapClockFor(rows), un = [...(clk ? [clk] : []), ...sigs].filter(r => lazyOf(M, r.orig || r).length);
      if (un.length) this.need(un);   // a large dump: read, then worked out again (need resets the memo)
      m = this.warpMemo = { rows, ref, sigs, clk, gck: G.clk, run: this.cmpRun, ts: gapTimes(sigs, M.t0, M.t1, clk, ref.length > 0) };
    }
    const bm = this.bms.map(x => x.t), key = JSON.stringify([g.gapIdle, g.gapKeep, bm]);
    if (m.key !== key) { m.key = key; m.w = warpOf(gapCuts(m.sigs, M.t0, M.t1, g, m.clk, M.cycle, bm, m.ref.length > 0, m.ts)); }
    return m;
  },
  // what the gaps on the waves leave: their number, the time kept, of the whole, the parts kept over the whole dump (the
  // first limit of them; more: partsAll says how many; a gap up to the end leaves no part after it); null: not on the waves
  gapParts(limit = Infinity) {
    const live = this.liveCuts(), M = this.M; if (!live) return null;
    const w = live.w, all = w.cuts.filter(([p, q]) => q > p);
    const o = { gaps: w.n - 1, kept: w.kept, total: M.t1 - M.t0, parts: all.slice(0, limit).map(p => [...p]) };
    if (o.parts.length < all.length) o.partsAll = all.length;
    return o;
  },
  // the frame of this window (null: no gaps on the waves). The same span and a new t0: the window moved, the scale kept;
  // anything else (a zoom, the gaps changed, the width changed): the same times fill the width again
  warpSync() {
    const live = this.liveCuts(), w = live && live.w, M = this.M;
    if (!w || w.n < 2) return (this.wf = null);
    const W = this.canvas.getBoundingClientRect().width || 600, L = this.wf, same = !!L && L.w === w && L.W === W && L.span === this.span;
    if (same && L.t0 === this.t0) return L;
    const a = this.t0, b = this.t0 + this.span;
    let { k, g } = same ? L : warpFit(w, a, b, W), v0 = warpV(w, a, k, g);
    if (!same && (k <= 0 || k > W / this.minSpan)) {   // inside a gap, or next to nothing kept: as near as the scale goes, around it
      if (k <= 0) ({ k } = L && L.w === w && L.W === W ? L : warpFit(w, M.t0, M.t1, W));
      k = Math.min(k, W / this.minSpan); v0 = warpV(w, (a + b) / 2, k, g) - W / 2;
    } else if (!same) return this.warpFrame(w, W, k, g, v0, a, this.span);
    return this.warpPlace(this.warpFrame(w, W, k, g, v0, a, this.span), v0);
  },
  warpFrame(w, W, k, g, v0, t0, span) {
    return (this.wf = { w, W, k, g, v0, t0, span, X: t => warpV(w, t, k, g) - v0, T: x => warpT(w, v0 + x, k, g) });
  },
  // the window of this frame's scale at place v (in the waves' ends; shorter than the window: all of it, the scale anew)
  warpPlace(F, v) {
    const { w, W, k, g } = F, M = this.M, end = warpV(w, M.t1, k, g);
    if (end <= W) { const f = warpFit(w, M.t0, M.t1, W); this.t0 = M.t0; this.span = M.t1 - M.t0;
      return this.warpFrame(w, W, f.k, f.g, warpV(w, M.t0, f.k, f.g), this.t0, this.span); }
    const v0 = Math.min(Math.max(v, 0), end - W), t0 = warpT(w, v0, k, g), span = warpT(w, v0 + W, k, g) - t0;
    this.t0 = t0; this.span = span;
    return this.warpFrame(w, W, k, g, v0, t0, span);
  },
  // zoom by f at the place at (0…1) of the window; the next frame fits the scale to the new times
  warpZoom(F, f, at) {
    const { w, W, g } = F, M = this.M, k = Math.min(F.k / f, W / this.minSpan), end = warpV(w, M.t1, k, g);
    if (end <= W) { this.t0 = M.t0; this.span = M.t1 - M.t0; return; }
    const v0 = Math.min(Math.max(warpV(w, F.T(at * W), k, g) - at * W, 0), end - W), t0 = warpT(w, v0, k, g);
    this.t0 = t0; this.span = warpT(w, v0 + W, k, g) - t0;
  },
  // what a text of the gaps needs: the frame's clock and the signals counted
  gapTextsNow() {
    const G = this.gapRows();
    return gapTexts(this.M, this.gapOpt().gapCount, this.liveCuts().clk, G.aux, G.ref);
  },
  // the header with gaps: the axis, the cycles and the gaps' texts over the parts; a gap goes on through them
  paintWarpHead(P, F, WP, Hc, ah, cy) {
    const M = this.M, X = F.X;
    paintWarpAxis(P, { parts: WP.parts, k: F.k, W: F.W, y: 0, h: ah, yEnd: Hc, X, timed: M.timed, tick: M.tick });
    if (cy) { P.rect(0, ah, F.W, CYC_H, 'panel2');
      for (const [p, q] of WP.parts) { const xa = X(p), xb = X(q);
        P.clip(xa, ah, xb - xa, CYC_H, () => paintCycles(P, { xL: xa, xR: xb, y: ah, h: CYC_H, X, from: p, to: q, ups: cy.ups, iz: cy.iz })); } }
    if (this.gapBand()) this.paintGapBand(P, F, WP, ah + (cy ? CYC_H : 0));
  },
  // the band under the axis: over a gap the time it leaves out and its cycles, in a part its cycles where there is room
  paintGapBand(P, F, WP, y) {
    P.rect(0, y, this.canvas.getBoundingClientRect().width || 600, GAP_H, 'panel2', 0.6);
    if (!F) return;
    const T = this.gapTextsNow(), lab = { size: 9.5, anchor: 'middle', fill: 'muted' }, used = [];
    let end = -Infinity;
    for (const h of WP.holes) {
      const xm = (h.x0 + h.x1) / 2, t = xm - end > 24 ? T.hole(h.p, h.q) : '', w = t ? P.measure(t, lab) / 2 + 4 : 0;
      if (!t || xm - w < end || xm - w < 0 || xm + w > F.W) continue;
      P.text(xm, y + GAP_H / 2, t, lab); used.push([xm - w, xm + w]); end = xm + w;
    }
    if (WP.parts.length > WARP_RUNS) return;
    for (const [p, q] of WP.parts) {
      const xa = F.X(p), xb = F.X(q), xm = (xa + xb) / 2, t = xb - xa > 24 ? T.part(p, q) : '', w = t ? P.measure(t, lab) / 2 + 2 : 0;
      if (t && xm - w > xa && xm + w < xb && !used.some(([a, b]) => xm + w > a && xm - w < b)) P.text(xm, y + GAP_H / 2, t, lab);
    }
  },
  // the rows with gaps (in layout coordinates): the parts, each in its own clip as in a picture, then the gaps' columns over
  // them, their lines and what the signals counted did there -> the rows' y
  paintWarpBody(P, F, WP, body, late, shown, oy, Hc, hdr) {
    const X = F.X, y0 = oy + hdr, Y1 = oy + Hc, G = this.gapOpt(), wide = WP.holes.length <= WARP_RUNS * 4;
    let rowY = new Map();
    for (const [p, q] of WP.runs) {
      const xa = X(p), xb = X(q), own = [];
      P.clip(xa, y0, xb - xa, Y1 - y0, () => { rowY = body(p, q, xa, xb, own); this.paintDiff(P, shown, X, p, q); });
      if (own.length) late.push(() => P.clip(xa, y0, xb - xa, Y1 - y0, () => own.forEach(f => f())));
    }
    let last = -Infinity;
    const T = this.gapTextsNow(), cnt = { size: 10, anchor: 'middle', fill: 'fg' }, ends = new Map();
    for (const h of WP.holes) {
      const x0 = Math.max(h.x0, 0), x1 = Math.min(h.x1, F.W), xm = (h.x0 + h.x1) / 2, w = x1 - x0;
      if (w > 0) P.rect(x0, y0, w, Y1 - y0, 'panel');
      if (w >= 2 && wide) P.clip(x0, y0, w, Y1 - y0, () => body(h.p, h.q, x0, x1, null, true));
      if (xm - last < 3 || xm < 0 || xm > F.W) continue;
      last = xm; paintGapLine(P, xm, y0, Y1, G.gapLine);
    }
    if (T.each && wide) for (const { row, y, h } of shown) {
      if (!T.counted(row)) continue;
      for (const o of WP.holes) {
        const xm = (o.x0 + o.x1) / 2, e = ends.get(row) ?? -Infinity;
        if (xm - e < 30) continue;
        const t = gapText(row, o.p, o.q, T.kind), tw = t ? P.measure(t, cnt) + 6 : 0;
        if (!t || xm - tw / 2 < e) continue;
        P.rect(xm - tw / 2, y + 2, tw, h - 4, 'panel2'); P.text(xm, y + h / 2, t, cnt); ends.set(row, xm + tw / 2 + 2);
      }
    }
    return rowY;
  },
  // the gap whose column is at x (m: px more on each side)
  gapAt(x, m = 0) { const F = this.warpSync(); return F ? warpParts(F).holes.find(o => x > o.x0 - m && x < o.x1 + m) : null; },
  // the tooltip of a gap's column
  gapTip(x) { const h = this.gapAt(x, 1); return h ? `gap: ${this.gapTextsNow().hole(h.p, h.q)} left out` : ''; },
  gapReadout() {
    if (!this.wf) return '';
    const w = this.wf.w, m = this.M, len = d => (m.timed ? fmtTime(d, d / 10, d) : d.toFixed(1) + ' cycles');
    return ` · ${w.n - 1} gap${w.n === 2 ? '' : 's'}, ${len(w.kept)} of ${len(m.t1 - m.t0)} kept`;
  },
  // the bar's idle and keep, in sight with the gaps on the waves: they change the waves while the waves stay in reach
  syncGapBar() {
    const el = this.root.querySelector('.gapv'); if (!el) return;
    const g = this.gapOpt(), on = g.gaps && g.gapView; el.hidden = !on;
    for (const [c, v] of [['.bgi', g.gapIdle], ['.bgk', g.gapKeep]]) { const i = el.querySelector(c); if (i !== document.activeElement) i.value = v ?? ''; }
  },
  // idle and keep as typed, in the menu or on the bar: as a number where it reads as one; quiet: a value not done yet leaves them
  gapFields(gi, gk, quiet) {
    const val = inp => { const v = inp.value.trim(); return /^[\d.]+(e[-+]?\d+)?$/i.test(v) ? +v : v; };
    const idle = val(gi), keep = val(gk), ok = [gapLen(idle, 1) > 0, gapLen(keep, 1) >= 0];
    if (!quiet) { if (!ok[0]) this.bad(gi); if (!ok[1]) this.bad(gk); }
    return { ...(ok[0] ? { gapIdle: idle } : {}), ...(ok[1] ? { gapKeep: keep } : {}) };
  },
  // one setGaps a little after the last key
  gapType(o) { clearTimeout(this.gapTypeT); this.gapTypeT = setTimeout(() => this.setGaps(o()), 120); },
});
