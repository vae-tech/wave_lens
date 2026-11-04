/* wavelens/src/names.js — the names column (Names) and the lists under the waves: bookmarks, arrows, markers, groups (Notes). */

// Above this many rows the column holds those near the view only (as the canvas draws its rows in sight), a spacer above and below:
// building 20 000 rows took 1.2 s for each key of a search. rowEls, rowEl and vals have the rows there are; rowBox has any row.
const NAMES_VIRTUAL = 4000, NAMES_MARGIN = 1200;   // px of rows kept beyond the view, either way
class Names {
  constructor(v) {
    this.v = v;
    const toggle = el => { const id = +el.dataset.g; v.collapsed.has(id) ? v.collapsed.delete(id) : v.collapsed.add(id); v.foldTouched = true; this.render();
      v.draw(); };
    const rowOf = el => v.vis[+el.closest('.row').dataset.r];
    v.namesDrag();   // the rows of your groups dragged into another order (edit.js)
    // copying from the names column gives the full paths of the selected rows, one per line (no values, no marks)
    v.namesEl.addEventListener('copy', e => {
      const s = getSelection(); if (!s || s.isCollapsed) return;
      const rows = [...v.namesEl.querySelectorAll('.row[data-r]')].filter(el => s.containsNode(el, true)).map(rowOf).filter(r => r && r.type !== 'space');
      if (!rows.length) return;
      e.preventDefault(); e.clipboardData.setData('text/plain', rows.map(r => r.full || r.name).join('\n')); v.toast(`copied ${rows.length}`);
    });
    v.namesEl.addEventListener('mousedown', e => { if (e.shiftKey) e.preventDefault(); });   // shift(+ctrl)+click: rows, not text
    // the right button on a name: the viewer's menu for its row at the cursor (as on the waves: colour, radix, groups, the
    // moves of your groups' rows …); text selected in the names: the browser's menu (copy)
    v.namesEl.addEventListener('contextmenu', e => {
      const sel = getSelection(); if (!v.S.contextMenu || (sel && !sel.isCollapsed && v.namesEl.contains(sel.anchorNode))) return;
      const row = e.target.closest('.row[data-r]'); e.preventDefault(); v.menu(e.clientX, e.clientY, row ? rowOf(row) : null, v.cursor);
    });
    v.namesEl.addEventListener('click', e => {
      const sel = getSelection(); if (sel && !sel.isCollapsed && v.namesEl.contains(sel.anchorNode)) return;   // selecting text to copy
      const row = e.target.closest('.row'); if (!row || row.classList.contains('space')) return;
      if (e.target.closest('.wd[data-b]')) { v.setBits(rowOf(row)); v.refocus(); return; }   // the bus bit by bit
      if (e.target.closest('.mk') || e.ctrlKey || e.metaKey) {   // mark / ctrl+click: highlight it; ctrl+shift+click: every row from the last one to it
        const r = rowOf(row);
        if (e.shiftKey && v.hlAnchor && v.vis.includes(v.hlAnchor)) v.highlightRun(v.hlAnchor, r); else { v.toggleHighlight(r); v.hlAnchor = r; }
        v.refocus(); return;
      }
      if (row.classList.contains('grp')) toggle(row);
      // shift+click: every signal from the last one clicked to it, selected
      else if (e.shiftKey && v.selAnchor && v.vis.includes(v.selAnchor)) v.selectRun(v.selAnchor, rowOf(row));
      else { const s = rowOf(row); v.select(v.sel === s && !v.selRun.size ? null : s); }   // a signal name: select it (again: unselect)
      v.refocus();   // the keys (Esc, arrows, n, m …) act on this viewer
    });
    v.namesEl.addEventListener('keydown', e => {
      const at = e.target.closest('.row[data-r]');
      if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && e.altKey && !e.ctrlKey && !e.metaKey && !keyLeft(v.S, e)) {   // the row with the focus moves
        e.preventDefault(); const r = at && rowOf(at);
        if (!r || !(r.user || r.ug)) { v.toast('alt+↑ / alt+↓ order the rows of your groups (the right button: Groups ▸)'); return; }   // not the selection's
        v.moveKey(e.key === 'ArrowUp' ? -1 : 1, e.shiftKey, r).then(() => { const i = v.vis.indexOf(r || v.sel);
          const k = i >= 0 && v.namesEl.querySelector(`.row[data-r="${i}"]`); if (k) k.focus({ preventScroll: false }); });
        return;
      }
      if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && at && !e.target.closest('.mk')) {   // the focus walks the rows; a signal is selected
        e.preventDefault();
        const rows = [...v.namesEl.querySelectorAll('.row[data-r]:not(.space)')], k = rows.indexOf(at) + (e.key === 'ArrowDown' ? 1 : -1);
        const to = rows[Math.min(Math.max(k, 0), rows.length - 1)], r = rowOf(to);
        if (r && r.type === 'sig') v.select(r);
        (v.namesEl.querySelector(`.row[data-r="${to.dataset.r}"]`) || to).focus({ preventScroll: false });
        return;
      }
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (at && !at.classList.contains('grp') && !e.target.closest('.mk')) { e.preventDefault(); const r = rowOf(at); v.select(v.sel === r ? null : r); return;
        }
      const mk = e.target.closest('.mk'), g = e.target.closest('.grp');
      if (mk) { e.preventDefault(); v.toggleHighlight(rowOf(mk)); v.namesEl.querySelector(`.row[data-r="${mk.closest('.row').dataset.r}"] .mk`)?.focus(); }
      else if (g) { e.preventDefault(); toggle(g); }
    });
  }
  // the names column: built again only when its rows change (folding, sorting, lanes, plugin rows); a selection,
  // a highlight, a search or a paint toggles classes and texts of the rows that are there
  render() {
    const v = this.v;
    v.vis = v.visible();
    // your own picks keep their colour
    const picks = (v.findPicks && v.findPicks.size) || v.extraPicks.size ? new Map([...v.findPicks, ...v.extraPicks, ...v.picks]) : v.picks;
    const C = compose(v.M, v.S, v.vis, v.bms, v.arrows, picks, v.rowsAll || v.M.rows, v.laneMarks());
    v.lanes = C.lanes; v.rowsL = C.rows; v.band = C.band; v.hl = C.hl;
    v.laneSig = JSON.stringify([...v.lanes]); v.laneKey = laneKey(v.bms, v.arrows, v.laneMarks());
    if (v.hlBtn) { v.hlBtn.hidden = !v.picks.size; v.hlBtn.textContent = `Highlight: ${v.picks.size} ✕`; }
    if (v.unhideBtn) { v.unhideBtn.hidden = !v.hiddenRows.size; v.unhideBtn.textContent = `Hidden: ${v.hiddenRows.size} ✕`; }
    if (v.sortBtn) { v.sortBtn.textContent = 'Sort: ' + { none: 'off', asc: 'A→Z', desc: 'Z→A' }[v.sort];
      v.sortBtn.setAttribute('aria-pressed', v.sort !== 'none'); }
    const shape = [v.sort, v.sortIgnore.join(','), v.hdrH, JSON.stringify(v.rowH), v.S.laneHeight, [...v.analogs].join(), v.S.showWidth].join('|');
    v.labGen = v.q || '';   // the marks of a search are in the labels
    // the lanes of bookmarks and arrows are made anew each time: the same by what they hold
    const lane = (r, o) => r.type === 'lane' && o.type === 'lane' && r.ids.length === o.ids.length && r.ids.every((x, i) => x === o.ids[i]);
    const prev = v.rowsShown, same = prev && v.shape === shape && prev.length === v.rowsL.length && v.rowsL.every((r, k) => r === prev[k] || lane(r, prev[k]));
    if (!same) this.build();
    v.rowsShown = v.rowsL; v.shape = shape;
    v.tabRow = v.sel || v.vis.find(x => x.type === 'sig');
    for (let k = v.rowA; k < v.rowB; k++) this.state(v.rowEls[k], v.rowsL[k]);
    if (v.mods) v.mods.render();   // the Modules panel: Hide, Only, the selected signal's module
    if (v.fsmP) v.fsmP.render();   // the FSM panel: what is in the view, the selected one
  }
  // the name of row r, the letters of a match marked (and the ignored prefix dimmed when sorting)
  label(r) {
    const v = this.v;
    const [p, rest] = v.sort !== 'none' ? stripPfx(r.name, v.sortIgnore) : ['', r.name], m = v.found && v.found.get(r);
    const at = m ? new Set(m.idx) : null, txt = (s, off) => at ? [...s].map((ch, i) =>
      at.has(off + i) ? `<b class="fm">${esc(ch)}</b>` : esc(ch)).join('') : esc(s);
    // a struct, union, interface scope
    const kdTitle = r.partial ? `: ${r.partial[0]} of its ${r.partial[1]} bits shown, no whole value` :
      r.sig ? `, ${r.sig.width} bits: its whole value on this row` : '';
    const kd = r.type === 'group' && hasKey(KIND_MARK, r.kind) ? `<span class="kd" title="${r.kind}${kdTitle}">${KIND_MARK[r.kind]}</span>` : '';
    const name = (p ? `<span class="pfx">${txt(p, 0)}</span>` : '') + txt(rest, p.length), w = this.widthTag(r);
    return kd + (w && r.type === 'sig' ? `<span class="nt">${name}</span>${w}` : name + w);   // a narrow column: the name, its width only whole
  }
  // a bus's width after its name ([7:0]; showWidth): a click on it shows the bus bit by bit (b, the menu's Bits), again folds them
  widthTag(r) {
    const v = this.v, w = v.S.showWidth !== false && widthTag(r); if (!w) return '';
    if (r.type !== 'sig' || (r.same && !r.ug)) return `<span class="wd">${w}</span>`;
    const open = v.bitsOpen.has((r.orig || r).full), n = r.width;
    return `<span class="wd${open ? ' open' : ''}" data-b title="${n} bits: ${open ? 'fold the bits' : 'show them one by one'} (b)">${w}</span>`;
  }
  // the rows of the column as they stand: where each one is, its index in vis; all of them, or those near the view
  build() {
    const v = this.v, n = v.rowsL.length;
    v.rowVi = new Int32Array(n); let vi = -1;
    v.rowY = n > NAMES_VIRTUAL ? new Float64Array(n + 1) : null;
    for (let k = 0; k < n; k++) { const r = v.rowsL[k]; v.rowVi[k] = r.type === 'lane' ? -1 : ++vi;
      if (v.rowY) v.rowY[k + 1] = v.rowY[k] + (r.type === 'lane' ? v.S.laneHeight * r.ids.length : rowHeight(r, v.rowH, v.S.laneHeight)); }
    if (v.rowY) { const [a, b] = this.around(); this.fill(a, b); } else this.fill(0, n);
  }
  // the rows from the margin above the view to the margin below it
  around() {
    const v = this.v, Y = v.rowY, n = v.rowsL.length, oy = (v.oy || 0) - v.hdrH, h = v.hc || innerHeight;
    return [Math.max(0, lastBefore(n + 1, k => Y[k], oy - NAMES_MARGIN)), Math.min(n, 1 + lastBefore(n + 1, k => Y[k], oy + h + NAMES_MARGIN))];
  }
  // the view came near the end of the rows there are: those around it instead (draw); the keys stay on their row
  slide(oy, h) {
    const v = this.v, Y = v.rowY, n = v.rowsL.length; if (!Y) return;
    const y = oy - v.hdrH, near = NAMES_MARGIN / 4;
    if ((v.rowA === 0 || Y[v.rowA] <= y - near) && (v.rowB === n || Y[v.rowB] >= y + h + near)) return;
    const on = document.activeElement, at = on && v.namesEl.contains(on) && on.closest('.row[data-r]'), r = at && at.dataset.r;
    const [a, b] = this.around(); this.fill(a, b);
    for (let k = a; k < b; k++) this.state(v.rowEls[k], v.rowsL[k]);
    if (r != null) v.namesEl.querySelector(`.row[data-r="${r}"]`)?.focus({ preventScroll: true });
  }
  fill(a, b) {
    const v = this.v;
    v.rowA = a; v.rowB = b;
    const alt = r => v.band && v.band.get(r) === 1 ? ' alt' : '', pad = r => `padding-left:${17 + r.depth * 12}px`;
    const mk = '<span class="mk" role="checkbox" tabindex="0" aria-checked="false"></span>';
    v.rowLab = new Map(); v.rowCol = new Map(); v.rowKey = new Map();
    const lab = r => { const t = (r.type === 'group' && r.cls !== 'ugdiv' ? (v.collapsed.has(r.id) ? '▸ ' : '▾ ') : '') + this.label(r); v.rowLab.set(r, t);
      v.rowCol.set(r, v.strokeOf(r) || ''); return t; };
    const col = r => v.strokeOf(r) ? ` style="color:${esc(v.strokeOf(r))}"` : '';
    const spacer = h => (h > 0 ? `<div class="vsp" style="height:${h}px"></div>` : '');
    v.namesEl.setAttribute('role', 'listbox'); v.namesEl.setAttribute('aria-label', 'signals');
    const cy = v.cycData();   // the cycles' band: its clock named in the header of the names
    v.namesEl.innerHTML = `<div class="hdr" style="height:${v.hdrH}px">${cy ? `<span class="cyc" style="height:${CYC_H}px" title="the cycles under the ` +
      `time axis: rising edges of ${esc(cy.clk.full || cy.clk.name)}">cycles ↑ ${esc(cy.clk.name)}</span>` : ''}</div>` +
      (v.rowY ? spacer(v.rowY[a]) : '') + v.rowsL.slice(a, b).map((r, j) => {
      if (r.type === 'lane') return (`<div class="row lane${alt(r)}" style="height:${v.S.laneHeight * r.ids.length}px" title="arrow labels, lifted ` +
          `bookmarks, texts of markers"></div>`);
      const h = rowHeight(r, v.rowH, v.S.laneHeight), i = v.rowVi[a + j], cls = (r.cls ? ' ' + r.cls : '') + (r.bit != null ? ' bit' : '');
      if (r.type === 'space') return `<div class="row space${alt(r)}" data-r="${i}" style="height:${h}px;${pad(r)}"><span
        class="n">${esc(r.name)}</span></div>`;
      if (r.type === 'group') return (`<div class="row grp${cls}" data-r="${i}" style="height:${h}px;${pad(r)}" data-g="${r.id}" tabindex="0" role="button" ` +
          `aria-expanded="true" title="${esc(r.title || r.path)}">${mk}<span ` +
          `class="n"${col(r)}>${lab(r)}</span>${r.sig ? '<span class="v"></span>' : ''}</div>`);
      return (`<div class="row${cls}${alt(r)}" data-r="${i}" role="option" aria-selected="false" tabindex="-1" style="height:${h}px;${pad(r)}">${mk}<span ` +
          `class="n" title="${esc(r.full || r.name)}"${col(r)}>${lab(r)}</span><span class="v"></span></div>`);
    }).join('') + (v.rowY ? spacer(v.rowY[v.rowsL.length] - v.rowY[b]) : '');
    const els = [...v.namesEl.querySelectorAll(':scope > .row')];
    v.rowEls = a ? [] : els; if (a) els.forEach((el, j) => { v.rowEls[a + j] = el; });
    v.rowElOf = new Map();
    for (let k = a; k < b; k++) { const r = v.rowsL[k]; if (r.type !== 'lane' && !v.rowElOf.has(r)) v.rowElOf.set(r, v.rowEls[k]); }   // rowEl: no search
    for (const [r, set] of v.rowMarks) { const el = v.rowEl(r); if (el) el.classList.add(...set); }   // the plugins' marks stay
    for (const [r, t] of v.rowTitles) { const el = v.rowEl(r); if (el) el.title = t; }
    v.vals = [...v.namesEl.querySelectorAll('.row .v')]; v.namesGen = (v.namesGen || 0) + 1;
    v.valRows = v.rowsL.slice(a, b).filter(r => r.type === 'sig' || r.sig);   // vals' rows
  }
  // the classes, colours and texts of one row of the names column that depend on the state, set where they changed
  state(el, r) {
    const v = this.v;
    if (r.type === 'lane') return;
    const hl = v.hl, c = hl ? hl.cover.get(r) : undefined, dim = !!hl && !hl.on.has(r);
    const key = `${+dim}${c ?? '-'}${+v.picks.has(r)}${v.strokeOf(r) || ''}${+v.collapsed.has(r.id)}${+v.isSel(r)}${+(r === v.tabRow)}` +
      `${v.found.has(r) ? 'f' : ''}${v.labGen}${+v.gapRefSet().has(r)}${+(r === v.gapClockRow())}${+v.gapRows().aux.has(r)}` +
      `${+v.bitsOpen.has((r.orig || r).full)}`;
    if (v.rowKey.get(r) === key) return;   // nothing of this row changed
    v.rowKey.set(r, key);
    el.classList.toggle('dim', dim);
    if (r.type === 'space') return;
    el.classList.toggle('hl', c !== undefined); el.classList.toggle('tint', typeof c === 'string');
    const hv = typeof c === 'string' ? tokVar(c) : '';
    if (el.style.getPropertyValue('--hl') !== hv) { if (hv) el.style.setProperty('--hl', hv); else el.style.removeProperty('--hl'); }
    const own = v.picks.has(r), m = el.firstChild;
    if (m.getAttribute('aria-checked') !== String(own)) {
      m.setAttribute('aria-checked', own); m.title = own ? 'Remove the highlight' : 'Highlight (the other rows dim; several at once)';
      m.setAttribute('aria-label', 'highlight ' + (r.full || r.name));
    } else if (!m.title) { m.title = 'Highlight (the other rows dim; several at once)'; m.setAttribute('aria-label', 'highlight ' + (r.full || r.name)); }
    const n = m.nextSibling, open = r.type === 'group' && !v.collapsed.has(r.id);
    const lab = (r.type === 'group' && r.cls !== 'ugdiv' ? (open ? '▾ ' : '▸ ') : '') + this.label(r);   // (a divider: its name alone)
    if (v.rowLab.get(r) !== lab) { v.rowLab.set(r, lab); n.innerHTML = lab; }
    const col = v.strokeOf(r) || '';
    if ((v.rowCol.get(r) || '') !== col) { v.rowCol.set(r, col); n.style.color = col; }
    if (r.type === 'group') { if (el.getAttribute('aria-expanded') !== String(open)) el.setAttribute('aria-expanded', open); return; }
    // the gaps follow it, count its cycles, count its changes
    el.classList.toggle('gref', v.gapRefSet().has(r)); el.classList.toggle('gclk', r === v.gapClockRow()); el.classList.toggle('gaux', v.gapRows().aux.has(r));
    const sel = v.isSel(r);
    if (el.classList.contains('sel') !== sel) { el.classList.toggle('sel', sel); el.setAttribute('aria-selected', sel); }
    const ti = r === v.tabRow ? 0 : -1;   // roving: one row takes the Tab
    if (el.tabIndex !== ti) el.tabIndex = ti;
  }
}
// a marker's bound on its Δ, for the title of the Δ in its list: "\nbound: 40 ns … 3 cycles", or ''
const boundTip = (m, v) => (m.dmin == null && m.dmax == null ? '' : `\nbound: ${m.dmin == null ? '—' : boundText(m.dmin, x => v.when(x))} … ${
  m.dmax == null ? '—' : boundText(m.dmax, x => v.when(x))}`);
class Notes {
  constructor(v) {
    this.v = v;
    v.notesEl.addEventListener('click', e => this.click(e));
    v.notesEl.addEventListener('input', e => this.input(e));
    v.notesEl.addEventListener('change', e => this.change(e));
    v.notesEl.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault();
      v.refocus(); } });
  }
  render() {
    const v = this.v;
    const el = v.notesEl, M = v.M, any = v.bms.length || v.umarks.length || v.ugroups.length; el.hidden = !any; v.notesGen = (v.notesGen || 0) + 1;
    if (!any) { el.innerHTML = ''; return; }
    const deltas = v.deltaList();
    const sigs = M.rows.filter(r => r.type === 'sig'), byFull = new Map(sigs.map(r => [r.full, r]));
    v.sigList = v.sigList || 'wvf-sigs-' + (++LIST_ID);   // one list of the signals for every bookmark's field
    const acc = getComputedStyle(v.root).getPropertyValue('--accent').trim(), six = c => String(c || '').replace(/^#([0-9a-f])([0-9a-f])([0-9a-f])$/i,
      '#$1$1$2$2$3$3'), hex = (c, d = acc) => /^#[0-9a-f]{6}$/i.test(six(c)) ? six(c) : /^#[0-9a-f]{6}$/i.test(six(d)) ? six(d) : '#b5551b';
    const pale = getComputedStyle(v.root).getPropertyValue('--muted').trim();   // a marker without a colour is drawn in it
    const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
    const nums = cur => v.bms.map(o => opt(String(o.n), String(o.n), String(cur))).join('');
    const head = v.opts.title || v.M.title;   // several viewers on a page: whose list this is
    el.innerHTML = (v.bms.length ? `<div class="nh"><b>Bookmarks${head ? ` · ${esc(head)}` : ''}</b><span
      class="muted">click a number to go there · drag a circle on the waves to move it, shift+drag to another one for an arrow · kept in this browser</span>
      <button type="button" data-bm="json">JSON</button><button type="button" data-bm="clear"
        title="Remove the bookmarks and arrows of this browser (the page's own come back on reload; your markers stay)">Clear</button></div><ol class="bms">` +
      v.bms.map(b => { const s = byFull.get(b.signal) || (b.signal && v.sigByPath(b.signal));
        return `<li data-n="${b.n}"><button type="button" class="bn" data-bm="go"
          title="Go to bookmark ${b.n}"${b.color ? ` style="background:${esc(b.color)}"` : ''}>${b.n}</button>
        <input type="text" class="tm" value="${esc(v.when(b.t))}" spellcheck="false" aria-label="bookmark ${b.n} time"
          title="Time: 250ns, 85.12us, or a number in the unit shown">
        <button type="button" class="ic" data-bm="here" title="Move the bookmark to the cursor">cursor</button>
        <input type="text" class="sig" list="${v.sigList}" value="${esc(b.signal || '')}" placeholder="— axis" spellcheck="false"
          aria-label="bookmark ${b.n} signal" title="${esc(b.signal || 'time axis')}: a full path or a name (the list has them all), empty for the time axis">
        <span class="eg">${esc(edgeGlyph(s, b.t))}</span>
        <span class="dt" title="Δ from the cursor (keys 1–9: go to the bookmark)"></span>
        <button type="button" class="ic up" data-bm="lift" aria-pressed="${!!b.lift}"
          title="In a lane of its own: over its signal, then under it, then on the row again (or drag the circle to the top or the bottom)"${b.signal ?
            '' : ' disabled'}>${b.lift === 'below' ? '↧' : '↥'}</button>
        <input type="color" class="col" value="${hex(b.color)}" aria-label="bookmark ${b.n} colour" title="Colour">
        <input type="text" class="lbl" value="${esc(b.label || '')}" placeholder="label" aria-label="bookmark ${b.n} label" spellcheck="false"
          title="A short label by the circle on the waves">
        <input type="text" class="txt" value="${esc(b.text)}" placeholder="describe the event" aria-label="bookmark ${b.n} text"${b.text ?
          ` title="${esc(b.text)}"` : ''}>
        ${b.link ? `<button type="button" class="ic lk" data-bm="link"${v.linkTarget(b.link) ? '' : ' disabled'} title="${v.linkTarget(b.link) ?
          `Open the view ${esc(b.link.view)} of this page${b.link.bookmark ? ` at its bookmark ${b.link.bookmark}` : ''}` :
          `No section ${esc(b.link.view)} on this page`}">→ ${esc(b.link.view)}</button>` : ''}
        <button type="button" class="ic" data-bm="blink" title="Copy a link to bookmark ${b.n}: the page opened by it goes there">#</button>
        <button type="button" class="ic" data-bm="del" title="Delete bookmark ${b.n} (and its arrows)">✕</button></li>`; }).join('') +
      (`</ol><div class="nh"><b>Arrows</b><span class="muted">from → to · shape · head · line · colour · label</span><button type="button" ` +
          `data-bm="addar"${v.bms.length < 2 ? ' disabled' : ''}>+ Arrow</button></div><ol class="ars">`) +
      v.arrows.map((a, i) => `<li data-a="${i}"><select class="from" aria-label="arrow ${i + 1} from">${nums(a.from)}</select>→<select class="to"
        aria-label="arrow ${i + 1} to">${nums(a.to)}</select>
        <select class="shape" aria-label="arrow shape">${Object.entries(AR_SHAPES).map(([k, v]) => opt(k, `${k}  ${v}`, a.shape)).join('')}</select>
        <select class="head" aria-label="arrow head">${Object.entries(AR_HEADS).map(([k, v]) => opt(k, v, a.head)).join('')}</select>
        <select class="line" aria-label="arrow line">${Object.keys(AR_LINES).map(k => opt(k, k, a.line)).join('')}</select>
        <input type="color" class="col" value="${hex(a.color)}" aria-label="arrow colour" title="Colour">
        <input type="text" class="lab" value="${esc(a.label)}" placeholder="label" aria-label="arrow label">
        <button type="button" class="ic" data-bm="adel" title="Delete this arrow">✕</button></li>`).join('') +
      '</ol><textarea class="json" readonly hidden aria-label="bookmarks as JSON"></textarea>' : '') +
      // your markers: a dashed line across the rows with its label; your groups: a folder of signals at the top of the names
      (v.umarks.length ? `<div class="nh"><b>Markers</b><span class="muted">time · signal · label · colour · drag a text on the waves to a line ` +
        `over or under a signal, along the time</span><label class="mdl" title="An arrow between neighbouring markers with the time between them, at the top ` +
        `of the rows: drag it up and down to the line over or under a signal, its dot along to another marker"><input type="checkbox" class="mdeltas" ` +
        `aria-label="the Δ between markers"${v.deltas ? ' checked' : ''}> Δ between markers</label><button type="button" data-bm="clearall" ` +
        `title="Delete every bookmark, arrow and marker of yours (undo brings them back)">Clear all</button></div><ol class="mks">` +
        v.umarks.map((m, i) => `<li data-k="${i}"><span class="mn">${i + 1}</span>
        <input type="text" class="mt" value="${esc(v.when(m.t))}" spellcheck="false" aria-label="marker ${i + 1} time" title="Time: 250ns, 85.12us">
        <input type="text" class="msig" list="${v.sigList}" value="${esc(m.signal || '')}" placeholder="— top" spellcheck="false"
          aria-label="marker ${i + 1} signal" title="${esc(m.signal || 'at the top of the rows')}: the signal whose line has its text, empty for the top">
        <button type="button" class="ic up" data-bm="mlift" aria-pressed="${m.lift === 'below'}" title="Over its signal or under it"${m.signal ? '' :
          ' disabled'}>${m.lift === 'below' ? '↧' : '↥'}</button>
        <input type="text" class="ml" value="${esc(m.label)}" placeholder="label" aria-label="marker ${i + 1} label">
        <input type="color" class="col" value="${hex(m.color, pale)}" aria-label="marker ${i + 1} colour" title="Colour">
        <button type="button" class="ic" data-bm="mpale" title="The pale colour again"${m.color ? '' : ' disabled'}>pale</button>
        <label class="mhl" title="Kept in this list, not on the waves; the Δ goes through it"><input type="checkbox" class="mhid"
          aria-label="marker ${i + 1} hidden"${m.hidden ? ' checked' : ''}> hidden</label>
        ${v.deltas ? `<select class="mto" aria-label="marker ${i + 1}: the Δ goes to" title="The marker its Δ goes to, through the ones between">` +
          opt('next', '→ next', m.dto == null ? 'next' : m.dto === 0 ? 'none' : String(m.dto)) + opt('none', '→ none', m.dto === 0 ? 'none' : '') +
          v.umarks.map((o, k) => (k === i ? '' : opt(String(k + 1), `→ ${k + 1}${o.label ? ' ' + o.label : ''}`, String(m.dto)))).join('') + '</select>' : ''}
        ${(d => (d && d.dt > 0 ? `<span class="md${d.bad ? ' bad' : ''}" title="The time to the marker it goes to${boundTip(m, v)}">Δ ${
          esc(v.deltaText(d))}${d.bad ? ' ' + esc(v.deltaBound(d)) : ''}</span>` : ''))(
          deltas.find(d => d.a === m))}
        <button type="button" class="ic" data-bm="mdel" title="Delete marker ${i + 1}">✕</button></li>`).join('') + '</ol>' : '') +
      (v.ugroups.length ? `<div class="nh"><b>Groups</b><span class="muted">yours, at the top of the names · name · colour</span></div><ol class="ugs">` +
        v.ugroups.map((g, i) => `<li data-g="${i}"><input type="text" class="ugn" value="${esc(g.name)}" spellcheck="false" aria-label="group ${i + 1} name"
          title="The group's name (Enter)"><span class="muted">${g.signals.length} signal${g.signals.length === 1 ? '' : 's'}</span>
        <input type="color" class="col" value="${hex(g.color)}" aria-label="group ${i + 1} colour" title="Colour of its signals">
        <button type="button" class="ic" data-bm="gdel" title="Delete the group (its signals stay where they are)">✕</button></li>`).join('') + '</ol>' : '') +
      `<datalist id="${v.sigList}">${sigs.map(r => `<option value="${esc(r.full)}">`).join('')}</datalist>`;
  }
  click(e) {
    const v = this.v;
    const b = e.target.closest('button[data-bm]'); if (!b) return;
    const li = b.closest('li'), n = li ? +li.dataset.n : NaN, bm = v.bms.find(x => x.n === n), act = b.dataset.bm;
    if (act === 'mdel') return v.run({ op: 'marker', id: +li.dataset.k + 1, delete: true });
    if (act === 'clearall') return v.clearMarks();
    if (act === 'mlift') return v.run({ op: 'marker', id: +li.dataset.k + 1, lift: v.umarks[+li.dataset.k].lift === 'below' ? 'above' : 'below' });
    if (act === 'mpale') return v.run({ op: 'marker', id: +li.dataset.k + 1, color: null });
    if (act === 'gdel') return v.run({ op: 'group', name: v.ugroups[+li.dataset.g].name, delete: true });
    if (act === 'go' && bm) v.goBm(bm);
    else if (act === 'link' && bm && bm.link) v.followLink(bm);
    else if (act === 'blink' && bm) v.copyText(v.linkTo({ t: bm.t, sel: bm.signal, bm: bm.n }));
    else if (act === 'here' && bm) { bm.t = v.cursor; delete bm.at; bm.top = v.topNow(); v.changed(true); }   // the screen of now, as a new one
    else if (act === 'lift' && bm && bm.signal) { bm.lift = !bm.lift ? true : bm.lift === true ? 'below' : false; v.changed(true); }   // off, above, under
    else if (act === 'del') { v.bms = v.bms.filter(x => x.n !== n); v.arrows = v.arrows.filter(a => a.from !== n && a.to !== n); v.changed(true); }
    else if (act === 'adel') { v.arrows.splice(+li.dataset.a, 1); v.changed(true); }
    else if (act === 'addar') { const k = v.bms.length; v.arrows.push(arNorm([{ from: v.bms[k - 2].n, to: v.bms[k - 1].n }])[0]); v.changed(true); }
    else if (act === 'clear') { v.bms = []; v.arrows = []; v.saveBookmarks(false); this.render(); v.draw(); }   // your markers stay
    else if (act === 'json') {
      const ta = v.notesEl.querySelector('textarea.json'), rows = l => l.map(x => '  ' + JSON.stringify(x)).join(',\n');
      const txt = [`"bookmarks": [\n${rows(v.bookmarks())}\n]`, `"arrows": [\n${rows(v.arrowList())}\n]`,
        ...v.extraJSON.map(f => f()).filter(Boolean)].join(',\n');
      ta.hidden = !ta.hidden; ta.value = txt; ta.rows = txt.split('\n').length + 1;
      if (!ta.hidden) { ta.select(); try { navigator.clipboard.writeText(txt).then(() => { b.textContent = 'JSON (copied)'; }, () => {});
        } catch (err) { /* select only */ } }
    }
  }
  input(e) {
    const v = this.v; // text, colours, arrow settings: live
    const T = e.target, li = T.closest('li');
    if (T.matches('input.mdeltas')) return v.run({ op: 'deltas', on: T.checked });
    if (!li) return;
    if (li.dataset.k != null) { const k = +li.dataset.k, m = v.umarks[k]; if (!m) return;
      if (T.matches('select.mto')) return v.run({ op: 'deltas', id: k + 1, to: T.value === 'next' ? 'next' : T.value === 'none' ? null : +T.value });
      if (T.matches('input.mhid')) return v.run({ op: 'marker', id: k + 1, hidden: T.checked });
      if (T.matches('input.ml')) { m.label = T.value;
        v.notesEl.querySelectorAll(`select.mto option[value="${k + 1}"]`).forEach(o => { o.textContent = `→ ${k + 1}${m.label ? ' ' + m.label : ''}`; }); }
      else if (T.matches('input.col')) { m.color = T.value; li.querySelector('[data-bm=mpale]').disabled = false; } else return;
      v.markers = v.pageMarks.concat(v.umarks); v.saveBookmarks(); return v.draw(); }
    if (li.dataset.g != null) { const g = v.ugroups[+li.dataset.g]; if (g && T.matches('input.col')) { g.color = T.value; v.setGroups(); } return; }
    if (li.dataset.a != null) {
      const a = v.arrows[+li.dataset.a]; if (!a) return;
      if (T.matches('select.from, select.to')) { a[T.className] = +T.value; }
      else if (T.matches('select.shape, select.head, select.line')) a[T.className] = T.value;
      else if (T.matches('input.col')) a.color = T.value;
      else if (T.matches('input.lab')) a.label = T.value;
      return v.changed(false);
    }
    const bm = v.bms.find(x => x.n === +li.dataset.n); if (!bm) return;
    if (T.matches('input.txt')) { bm.text = T.title = T.value; v.saveBookmarks(); }   // the whole text on hover too (AU-WL-002)
    if (T.matches('input.lbl')) { bm.label = T.value; v.saveBookmarks(); v.draw(); }
    else if (T.matches('input.col')) { bm.color = T.value; li.querySelector('.bn').style.background = T.value; v.changed(false); }
  }
  change(e) {
    const v = this.v; // time and signal of a bookmark (a marker's time, a group's name): on Enter / leaving the field
    const T = e.target, li = T.closest('li'), bm = li && v.bms.find(x => x.n === +li.dataset.n);
    if (li && li.dataset.k != null && T.matches('input.mt')) { const m = v.umarks[+li.dataset.k], t = m && v.parseWhen(T.value, m.t);
      if (!m) return; if (t == null || !isFinite(t)) { T.value = v.when(m.t); v.bad(T); return; } m.t = t; v.setMarks(); return; }
    if (li && li.dataset.k != null && T.matches('input.msig')) { const k = +li.dataset.k;
      v.run({ op: 'marker', id: k + 1, signal: T.value.trim() || null }).then(r => { if (!r[0].error) return;
        T.value = v.umarks[k].signal || ''; v.bad(T); v.toast(r[0].error); }); return; }
    if (li && li.dataset.g != null && T.matches('input.ugn')) { const g = v.ugroups[+li.dataset.g]; if (!g) return;
      v.run({ op: 'group', name: g.name, rename: T.value }).then(r => { if (r[0].error) { T.value = g.name; v.bad(T); v.toast(r[0].error); } }); return; }
    if (!bm) return;
    if (T.matches('input.tm')) {
      const t = v.parseWhen(T.value, bm.t);
      if (t == null || !isFinite(t)) { T.value = v.when(bm.t); T.classList.add('bad'); setTimeout(() => T.classList.remove('bad'), 900); return; }
      bm.t = Math.min(Math.max(t, v.M.t0), v.M.t1); delete bm.at;
      if (bm.t < v.t0 || bm.t > v.t0 + v.span) v.center(bm.t);
      v.changed(true);
    } else if (T.matches('input.sig')) {   // a full path or a name; empty: the time axis
      const val = T.value.trim(), r = val && (v.sigByPath(val) || v.M.rows.find(x => x.type === 'sig' && x.name === val));
      if (val && !r) { T.value = bm.signal || ''; v.bad(T); return; }
      bm.signal = r ? r.full : null; v.changed(true);
    }
  }
}
