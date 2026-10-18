/* wavefw/src/view.js — the interactive viewer (WaveView). */

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

/* ---------------- the viewer's parts: Bar (tools), Names (the names column), Notes (bookmarks and arrows) ---------------- */
// Each part takes the viewer v and keeps its state there (v.qEl, v.vis, v.rowEls, v.bms …): a part is where the code of
// a piece of the page lives; the viewer is the one object that plugins and tests talk to.
class Bar {
  // the viewer's markup: the bar (title line, tool groups), the names column and the waves, the lists, the hint
  static html(v) {
    const r = v.root, S = v.S, groups = Object.keys(v.M.groups).length > 0;
    const paint = getComputedStyle(r).getPropertyValue('--wave-paint').trim();   // a token, so a theme may change it
    const jumps = v.jumps.map((j, i) => `<button type="button" data-jump="${i}">${esc(j.label)}</button>`).join('');
    const sort = S.sortButton ? `<button type="button" data-act="sort" title="Sort signals by name (key: s)"></button><input type="text" class="pfx" spellcheck="false" size="8" value="${esc(v.sortIgnore.join(','))}" placeholder="i_,o_" title="Name prefixes ignored when sorting (comma-separated)" aria-label="prefixes ignored when sorting">` : '';
    const seg = (...parts) => `<span class="seg">${parts.join('')}</span>`, grp = (label, ...parts) => `<span class="tg" data-tg="${label}"><span class="tl">${label}</span>${parts.join('')}</span>`;
    const find = grp('find',
      seg(`<input type="search" class="q" spellcheck="false" autocomplete="off" placeholder="find  /" aria-label="fuzzy find signals" title="Fuzzy find: the letters in order (pxvd finds s_pix_valid); a word with '.' searches full paths (dev.fifo); words separated by spaces must all match. Enter / n: next, shift+Enter / N: previous, Esc: reset">`,
        '<span class="cnt"></span><button type="button" data-act="fprev" title="Previous match (N, shift+Enter)">‹</button><button type="button" data-act="fnext" title="Next match (n, Enter)">›</button>'),
      seg(`<button type="button" data-act="fhl" aria-pressed="${!!S.findHighlight}" title="Found rows in front, the rest dimmed">Highlight</button>`, `<button type="button" data-act="fopen" aria-pressed="${!!S.findOpen}" title="Every module folded except the ones with a match">Open</button>`),
      seg(`<input type="color" class="fcol" value="${/^#[0-9a-f]{6}$/i.test(paint) ? paint : '#d6336c'}" aria-label="paint colour" title="Colour for Paint">`, '<button type="button" data-act="fpaint" title="Paint the found signals in this colour (kept in this browser)">Paint</button>'),
      `<button type="button" data-act="funpaint" title="Back to the signals' own colours" hidden>Unpaint</button><button type="button" data-act="fcopy" title="Copy the full paths of the found rows, one per line">Copy</button>`).replace('class="tg"', 'class="tg find"');
    // cursor: type a time (in the unit chosen, or with its own: 85.12us) and Set; a span and Show: the window around the cursor
    const units = v.M.timed ? `<select class="cu" aria-label="time unit" title="Unit of the two fields">${['ps', 'ns', 'µs', 'ms', 's'].map(u => `<option${u === v.unit() ? ' selected' : ''}>${u}</option>`).join('')}</select>` : '<span class="cyc">cyc</span>';
    const cursor = seg('<input type="text" class="ct" inputmode="decimal" spellcheck="false" aria-label="cursor time" title="Cursor time: a number in the unit shown, or with a unit (85.12us); Enter or Set">',
        units, '<button type="button" data-act="cset" title="Put the cursor at this time">Set</button>') +
      seg('<span class="lbl">span</span><input type="text" class="cs" inputmode="decimal" spellcheck="false" aria-label="view span" title="Width of the window; Enter or Show">',
        units.replace('class="cu"', 'class="su"'), '<button type="button" data-act="cshow" title="Window of this span centred on the cursor (key: c)">Show</button>');
    const list = grp('list', sort ? seg(sort) : '', groups ? seg('<button type="button" data-act="expand" title="Expand all groups">Expand</button>', '<button type="button" data-act="collapse" title="Collapse all groups">Collapse</button>') : '',
      '<button type="button" data-act="hl" title="Clear the highlight (Esc)" hidden></button>');
    const edges = grp('edges', seg('<button type="button" data-act="prev" title="Previous edge of the selected signal, or of any shown signal ([)">◀</button>',
      `<select class="edge" aria-label="edge kind" title="Edge kind (e)">${Object.entries(EDGE_KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>`,
      '<button type="button" data-act="next" title="Next edge (])">▶</button>'), '<button type="button" data-act="mark" title="Bookmark at the cursor, on the selected signal (m)">+ Mark</button>');
    return `<div class="bar"><div class="head"><span class="eyebrow">${esc(v.opts.title || v.M.title || 'Waveform').replace(/µ/g, '<span class="mu">µ</span>')}</span><span class="toast" role="status" aria-live="polite"></span><span class="cur"></span></div>
      <div class="tools">${grp('cursor', cursor)}${grp('view', seg('<button type="button" data-act="out" title="Zoom out (−)">−</button>', '<button type="button" data-act="in" title="Zoom in (+)">+</button>', '<button type="button" data-act="fit" title="Show everything (0)">Fit</button>'))}${find}${list}${edges}${jumps ? grp('go to', jumps) : ''}</div></div>
      <div class="body"><div class="names"></div><div class="wcol"><canvas tabindex="0" role="application" aria-roledescription="waveform" aria-label="waveform: + − zoom, ← → pan, shift+← → move the cursor, ↑ ↓ select a signal, [ ] edges"></canvas></div></div>
      <div class="notes" hidden></div>
      ${S.hint ? `<div class="hint">${esc(v.hintBase = `Wheel: zoom · shift+wheel / drag: pan · click: cursor + select a signal · keys on the waves: + − 0 zoom · ← → pan · shift+← → cursor · c window at the cursor · ↑ ↓ select · / find, n N next / previous match · [ ] edges, e edge kind · m bookmark${S.sortButton ? ' · s sort' : ''} · Esc reset${groups ? ' · click a module to fold it' : ''} · ○ or ctrl+click a name: highlight`)}</div>` : ''}`;
  }
  constructor(v) {
    this.v = v; const r = v.root;
    v.canvas = r.querySelector('canvas'); v.wcol = r.querySelector('.wcol'); v.bodyEl = r.querySelector('.body'); v.namesEl = r.querySelector('.names'); v.curEl = r.querySelector('.cur');
    v.sortBtn = r.querySelector('button[data-act=sort]'); v.hlBtn = r.querySelector('button[data-act=hl]');
    v.notesEl = r.querySelector('.notes'); v.edgeSel = r.querySelector('select.edge');
    v.ctEl = r.querySelector('input.ct'); v.csEl = r.querySelector('input.cs');
    v.cuEl = r.querySelector('select.cu'); v.suEl = r.querySelector('select.su');
    for (const [inp, fn] of [[v.ctEl, x => v.setCursor(x)], [v.csEl, x => v.showCursor(x)]])
      inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); fn(inp.value); } });
    for (const sel of [v.cuEl, v.suEl]) if (sel) sel.addEventListener('change', () => { v.syncCursorFields(true); });
    v.qEl = r.querySelector('input.q'); v.cntEl = r.querySelector('.find .cnt'); v.fcol = r.querySelector('input.fcol');
    v.unpaintBtn = r.querySelector('button[data-act=funpaint]'); v.unpaintBtn.hidden = !v.painted.size;
    let qt = 0;
    v.qEl.addEventListener('input', () => { cancelAnimationFrame(qt); qt = requestAnimationFrame(() => v.find(v.qEl.value)); });   // live, while typing
    v.qEl.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); v.findStep(e.shiftKey ? -1 : 1); }

    });
    v.edgeSel.addEventListener('change', () => { v.edgeKind = v.edgeSel.value; });
    r.querySelector('.bar').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.act === 'in') v.zoom(0.5, 0.5);
      else if (b.dataset.act === 'out') v.zoom(2, 0.5);
      else if (b.dataset.act === 'fit') v.fit();
      else if (b.dataset.act === 'sort') v.setSort(SORTS[(SORTS.indexOf(v.sort) + 1) % SORTS.length]);
      else if (b.dataset.act === 'hl') v.highlight(null);
      else if (b.dataset.act === 'expand') v.expandAll();
      else if (b.dataset.act === 'collapse') v.collapseAll();
      else if (b.dataset.act === 'prev' || b.dataset.act === 'next') v.edge(b.dataset.act === 'next' ? 1 : -1);
      else if (b.dataset.act === 'mark') v.mark();
      else if (b.dataset.act === 'fhl' || b.dataset.act === 'fopen') {
        const k = b.dataset.act === 'fhl' ? 'findHl' : 'findOpen'; v[k] = !v[k]; b.setAttribute('aria-pressed', v[k]); v.find(v.q || '', k === 'findOpen');
      }
      else if (b.dataset.act === 'fpaint') v.paint(v.fcol.value);
      else if (b.dataset.act === 'funpaint') v.unpaint();
      else if (b.dataset.act === 'cset') v.setCursor(v.ctEl.value);
      else if (b.dataset.act === 'cshow') v.showCursor(v.csEl.value);
      else if (b.dataset.act === 'fnext' || b.dataset.act === 'fprev') v.findStep(b.dataset.act === 'fnext' ? 1 : -1);
      else if (b.dataset.act === 'fcopy') v.copyRows(v.allRows().filter(r => v.found.has(r)));
      else if (b.dataset.jump !== undefined) { const j = v.jumps[b.dataset.jump]; v.goto(j.t, j.span); }
    });
    const pfx = r.querySelector('input.pfx');
    if (pfx) pfx.addEventListener('input', () => { v.fitPfx(); v.setSort(v.sort, pfx.value); });
    v.fitPfx();
  }
}
class Names {
  constructor(v) {
    this.v = v;
    const toggle = el => { const id = +el.dataset.g; v.collapsed.has(id) ? v.collapsed.delete(id) : v.collapsed.add(id); v.foldTouched = true; this.render(); v.draw(); };
    const rowOf = el => v.vis[+el.closest('.row').dataset.r];
    // copying from the names column gives the full paths of the selected rows, one per line (no values, no marks)
    v.namesEl.addEventListener('copy', e => {
      const s = getSelection(); if (!s || s.isCollapsed) return;
      const rows = [...v.namesEl.querySelectorAll('.row[data-r]')].filter(el => s.containsNode(el, true)).map(rowOf).filter(r => r && r.type !== 'space');
      if (!rows.length) return;
      e.preventDefault(); e.clipboardData.setData('text/plain', rows.map(r => r.full || r.name).join('\n')); v.toast(`copied ${rows.length}`);
    });
    v.namesEl.addEventListener('click', e => {
      const sel = getSelection(); if (sel && !sel.isCollapsed && v.namesEl.contains(sel.anchorNode)) return;   // selecting text to copy
      const row = e.target.closest('.row'); if (!row || row.classList.contains('space')) return;
      if (e.target.closest('.mk') || e.ctrlKey || e.metaKey) { v.toggleHighlight(rowOf(row)); v.canvas.focus({ preventScroll: true }); return; }   // mark / ctrl+click: highlight
      if (row.classList.contains('grp')) toggle(row);
      else { const s = rowOf(row); v.select(v.sel === s ? null : s); }   // a signal name: select it (again: unselect)
      v.canvas.focus({ preventScroll: true });   // the keys (Esc, arrows, n, m …) act on this viewer
    });
    v.namesEl.addEventListener('keydown', e => {
      const at = e.target.closest('.row[data-r]');
      if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && at && !e.target.closest('.mk')) {   // the focus walks the rows; a signal is selected
        e.preventDefault();
        const rows = [...v.namesEl.querySelectorAll('.row[data-r]:not(.space)')], k = rows.indexOf(at) + (e.key === 'ArrowDown' ? 1 : -1);
        const to = rows[Math.min(Math.max(k, 0), rows.length - 1)], r = rowOf(to);
        if (r && r.type === 'sig') v.select(r);
        (v.namesEl.querySelector(`.row[data-r="${to.dataset.r}"]`) || to).focus({ preventScroll: false });
        return;
      }
      if (e.key !== 'Enter' && e.key !== ' ') return;
      if (at && !at.classList.contains('grp') && !e.target.closest('.mk')) { e.preventDefault(); const r = rowOf(at); v.select(v.sel === r ? null : r); return; }
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
    const picks = (v.findPicks && v.findPicks.size) || v.extraPicks.size ? new Map([...v.findPicks, ...v.extraPicks, ...v.picks]) : v.picks;   // your own picks keep their colour
    const C = compose(v.M, v.S, v.vis, v.bms, v.arrows, picks, v.rowsAll || v.M.rows);
    v.lanes = C.lanes; v.rowsL = C.rows; v.band = C.band; v.hl = C.hl;
    v.laneSig = JSON.stringify([...v.lanes]); v.laneKey = laneKey(v.bms, v.arrows);
    if (v.hlBtn) { v.hlBtn.hidden = !v.picks.size; v.hlBtn.textContent = `Highlight: ${v.picks.size} ✕`; }
    if (v.sortBtn) { v.sortBtn.textContent = 'Sort: ' + { none: 'off', asc: 'A→Z', desc: 'Z→A' }[v.sort]; v.sortBtn.setAttribute('aria-pressed', v.sort !== 'none'); }
    const shape = [v.sort, v.sortIgnore.join(','), v.hdrH, JSON.stringify(v.rowH), v.S.laneHeight].join('|');
    v.labGen = v.q || '';   // the marks of a search are in the labels
    const prev = v.rowsShown, same = prev && v.shape === shape && prev.length === v.rowsL.length && v.rowsL.every((r, k) => r === prev[k]);
    if (!same) this.build();
    v.rowsShown = v.rowsL; v.shape = shape;
    v.tabRow = v.sel || v.vis.find(x => x.type === 'sig');
    for (let k = 0; k < v.rowsL.length; k++) this.state(v.rowEls[k], v.rowsL[k]);
  }
  // the name of row r, the letters of a match marked (and the ignored prefix dimmed when sorting)
  label(r) {
    const v = this.v;
    const [p, rest] = v.sort !== 'none' ? stripPfx(r.name, v.sortIgnore) : ['', r.name], m = v.found && v.found.get(r);
    const at = m ? new Set(m.idx) : null, txt = (s, off) => at ? [...s].map((ch, i) => at.has(off + i) ? `<b class="fm">${esc(ch)}</b>` : esc(ch)).join('') : esc(s);
    return (p ? `<span class="pfx">${txt(p, 0)}</span>` : '') + txt(rest, p.length);
  }
  build() {
    const v = this.v;
    const alt = r => v.band && v.band.get(r) === 1 ? ' alt' : '', pad = r => `padding-left:${17 + r.depth * 12}px`;
    const mk = '<span class="mk" role="checkbox" tabindex="0" aria-checked="false"></span>';
    v.rowLab = new Map(); v.rowCol = new Map(); v.rowKey = new Map();
    const lab = r => { const t = (r.type === 'group' ? (v.collapsed.has(r.id) ? '▸ ' : '▾ ') : '') + this.label(r); v.rowLab.set(r, t); v.rowCol.set(r, v.strokeOf(r) || ''); return t; };
    const col = r => v.strokeOf(r) ? ` style="color:${esc(v.strokeOf(r))}"` : '';
    let vi = -1;
    v.namesEl.setAttribute('role', 'listbox'); v.namesEl.setAttribute('aria-label', 'signals');
    v.namesEl.innerHTML = `<div class="hdr" style="height:${v.hdrH}px"></div>` + v.rowsL.map(r => {
      if (r.type === 'lane') return `<div class="row lane${alt(r)}" style="height:${v.S.laneHeight * r.ids.length}px" title="arrow labels"></div>`;
      const h = r.height || v.rowH[r.type], i = ++vi, cls = r.cls ? ' ' + r.cls : '';
      if (r.type === 'space') return `<div class="row space${alt(r)}" data-r="${i}" style="height:${h}px;${pad(r)}"><span class="n">${esc(r.name)}</span></div>`;
      if (r.type === 'group') return `<div class="row grp${cls}" data-r="${i}" style="height:${h}px;${pad(r)}" data-g="${r.id}" tabindex="0" role="button" aria-expanded="true" title="${esc(r.title || r.path)}">${mk}<span class="n"${col(r)}>${lab(r)}</span></div>`;
      return `<div class="row${cls}${alt(r)}" data-r="${i}" role="option" aria-selected="false" tabindex="-1" style="height:${h}px;${pad(r)}">${mk}<span class="n" title="${esc(r.full || r.name)}"${col(r)}>${lab(r)}</span><span class="v"></span></div>`;
    }).join('');
    v.rowEls = [...v.namesEl.children].slice(1);
    for (const [r, set] of v.rowMarks) { const el = v.rowEl(r); if (el) el.classList.add(...set); }   // the plugins' marks stay
    for (const [r, t] of v.rowTitles) { const el = v.rowEl(r); if (el) el.title = t; }
    v.vals = [...v.namesEl.querySelectorAll('.row .v')]; v.namesGen = (v.namesGen || 0) + 1;
  }
  // the classes, colours and texts of one row of the names column that depend on the state, set where they changed
  state(el, r) {
    const v = this.v;
    if (r.type === 'lane') return;
    const hl = v.hl, c = hl ? hl.cover.get(r) : undefined, dim = !!hl && !hl.on.has(r);
    const key = `${+dim}${c ?? '-'}${+v.picks.has(r)}${v.strokeOf(r) || ''}${+v.collapsed.has(r.id)}${+(r === v.sel)}${+(r === v.tabRow)}${v.found.has(r) ? 'f' : ''}${v.labGen}`;
    if (v.rowKey.get(r) === key) return;   // nothing of this row changed
    v.rowKey.set(r, key);
    el.classList.toggle('dim', dim);
    if (r.type === 'space') return;
    el.classList.toggle('hl', c !== undefined);
    const hv = c !== undefined ? tokVar(hlTok(c)) : '';
    if (el.style.getPropertyValue('--hl') !== hv) { if (hv) el.style.setProperty('--hl', hv); else el.style.removeProperty('--hl'); }
    const own = v.picks.has(r), m = el.firstChild;
    if (m.getAttribute('aria-checked') !== String(own)) {
      m.setAttribute('aria-checked', own); m.title = own ? 'Remove the highlight' : 'Highlight (the other rows dim; several at once)';
      m.setAttribute('aria-label', 'highlight ' + (r.full || r.name));
    } else if (!m.title) { m.title = 'Highlight (the other rows dim; several at once)'; m.setAttribute('aria-label', 'highlight ' + (r.full || r.name)); }
    const n = m.nextSibling, open = r.type === 'group' && !v.collapsed.has(r.id);
    const lab = (r.type === 'group' ? (open ? '▾ ' : '▸ ') : '') + this.label(r);
    if (v.rowLab.get(r) !== lab) { v.rowLab.set(r, lab); n.innerHTML = lab; }
    const col = v.strokeOf(r) || '';
    if ((v.rowCol.get(r) || '') !== col) { v.rowCol.set(r, col); n.style.color = col; }
    if (r.type === 'group') { if (el.getAttribute('aria-expanded') !== String(open)) el.setAttribute('aria-expanded', open); return; }
    const sel = r === v.sel;
    if (el.classList.contains('sel') !== sel) { el.classList.toggle('sel', sel); el.setAttribute('aria-selected', sel); }
    const ti = r === v.tabRow ? 0 : -1;   // roving: one row takes the Tab
    if (el.tabIndex !== ti) el.tabIndex = ti;
  }
}
class Notes {
  constructor(v) {
    this.v = v;
    v.notesEl.addEventListener('click', e => this.click(e));
    v.notesEl.addEventListener('input', e => this.input(e));
    v.notesEl.addEventListener('change', e => this.change(e));
    v.notesEl.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault(); v.canvas.focus({ preventScroll: true }); } });
  }
  render() {
    const v = this.v;
    const el = v.notesEl, M = v.M; el.hidden = !v.bms.length;
    if (!v.bms.length) { el.innerHTML = ''; return; }
    const sigs = M.rows.filter(r => r.type === 'sig'), byFull = new Map(sigs.map(r => [r.full, r]));
    v.sigList = v.sigList || 'wvf-sigs-' + (++LIST_ID);   // one list of the signals for every bookmark's field
    const acc = getComputedStyle(v.root).getPropertyValue('--accent').trim(), hex = c => /^#[0-9a-f]{6}$/i.test(c || '') ? c : /^#[0-9a-f]{6}$/i.test(acc) ? acc : '#b5551b';
    const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
    const nums = cur => v.bms.map(o => opt(String(o.n), String(o.n), String(cur))).join('');
    el.innerHTML = `<div class="nh"><b>Bookmarks</b><span class="muted">click a number to go there · drag a circle on the waves to move it, shift+drag to another one for an arrow · kept in this browser</span>
      <button type="button" data-bm="json">JSON</button><button type="button" data-bm="clear" title="Remove the bookmarks of this browser (the page's own come back on reload)">Clear</button></div><ol class="bms">` +
      v.bms.map(b => { const s = byFull.get(b.signal);
        return `<li data-n="${b.n}"><button type="button" class="bn" data-bm="go" title="Go to bookmark ${b.n}"${b.color ? ` style="background:${esc(b.color)}"` : ''}>${b.n}</button>
        <input type="text" class="tm" value="${esc(v.when(b.t))}" spellcheck="false" aria-label="bookmark ${b.n} time" title="Time: 250ns, 85.12us, or a number in the unit shown">
        <button type="button" class="ic" data-bm="here" title="Move the bookmark to the cursor">cursor</button>
        <input type="text" class="sig" list="${v.sigList}" value="${esc(b.signal || '')}" placeholder="— axis" spellcheck="false" aria-label="bookmark ${b.n} signal" title="${esc(b.signal || 'time axis')}: a full path or a name (the list has them all), empty for the time axis">
        <span class="eg">${esc(edgeGlyph(s, b.t))}</span>
        <input type="color" class="col" value="${hex(b.color)}" aria-label="bookmark ${b.n} colour" title="Colour">
        <input type="text" class="txt" value="${esc(b.text)}" placeholder="describe the event" aria-label="bookmark ${b.n} text">
        <button type="button" class="ic" data-bm="del" title="Delete bookmark ${b.n} (and its arrows)">✕</button></li>`; }).join('') +
      `</ol><div class="nh"><b>Arrows</b><span class="muted">from → to · shape · head · line · colour · label</span><button type="button" data-bm="addar"${v.bms.length < 2 ? ' disabled' : ''}>+ Arrow</button></div><ol class="ars">` +
      v.arrows.map((a, i) => `<li data-a="${i}"><select class="from" aria-label="arrow ${i + 1} from">${nums(a.from)}</select>→<select class="to" aria-label="arrow ${i + 1} to">${nums(a.to)}</select>
        <select class="shape" aria-label="arrow shape">${Object.entries(AR_SHAPES).map(([k, v]) => opt(k, `${k}  ${v}`, a.shape)).join('')}</select>
        <select class="head" aria-label="arrow head">${Object.entries(AR_HEADS).map(([k, v]) => opt(k, v, a.head)).join('')}</select>
        <select class="line" aria-label="arrow line">${Object.keys(AR_LINES).map(k => opt(k, k, a.line)).join('')}</select>
        <input type="color" class="col" value="${hex(a.color)}" aria-label="arrow colour" title="Colour">
        <input type="text" class="lab" value="${esc(a.label)}" placeholder="label" aria-label="arrow label">
        <button type="button" class="ic" data-bm="adel" title="Delete this arrow">✕</button></li>`).join('') +
      '</ol><textarea class="json" readonly hidden aria-label="bookmarks as JSON"></textarea>' +
      `<datalist id="${v.sigList}">${sigs.map(r => `<option value="${esc(r.full)}">`).join('')}</datalist>`;
  }
  click(e) {
    const v = this.v;
    const b = e.target.closest('button[data-bm]'); if (!b) return;
    const li = b.closest('li'), n = li ? +li.dataset.n : NaN, bm = v.bms.find(x => x.n === n), act = b.dataset.bm;
    if (act === 'go' && bm) { v.cursor = bm.t; if (bm.t < v.t0 || bm.t > v.t0 + v.span) v.t0 = v.clamp(bm.t - v.span / 2); if (bm.signal) v.sel = v.M.rows.find(r => r.full === bm.signal) || v.sel; v.renderNames(); v.draw(); }
    else if (act === 'here' && bm) { bm.t = v.cursor; v.changed(true); }
    else if (act === 'del') { v.bms = v.bms.filter(x => x.n !== n); v.arrows = v.arrows.filter(a => a.from !== n && a.to !== n); v.changed(true); }
    else if (act === 'adel') { v.arrows.splice(+li.dataset.a, 1); v.changed(true); }
    else if (act === 'addar') { const k = v.bms.length; v.arrows.push(arNorm([{ from: v.bms[k - 2].n, to: v.bms[k - 1].n }])[0]); v.changed(true); }
    else if (act === 'clear') { v.bms = []; v.arrows = []; try { localStorage.removeItem(v.bmKey); } catch (err) { /* ignore */ } this.render(); v.draw(); }
    else if (act === 'json') {
      const ta = v.notesEl.querySelector('textarea.json'), rows = l => l.map(x => '  ' + JSON.stringify(x)).join(',\n');
      const txt = [`"bookmarks": [\n${rows(v.bookmarks())}\n]`, `"arrows": [\n${rows(v.arrowList())}\n]`, ...v.extraJSON.map(f => f()).filter(Boolean)].join(',\n');
      ta.hidden = !ta.hidden; ta.value = txt; ta.rows = txt.split('\n').length + 1;
      if (!ta.hidden) { ta.select(); try { navigator.clipboard.writeText(txt).then(() => { b.textContent = 'JSON (copied)'; }, () => {}); } catch (err) { /* select only */ } }
    }
  }
  input(e) {
    const v = this.v; // text, colours, arrow settings: live
    const T = e.target, li = T.closest('li'); if (!li) return;
    if (li.dataset.a != null) {
      const a = v.arrows[+li.dataset.a]; if (!a) return;
      if (T.matches('select.from, select.to')) { a[T.className] = +T.value; }
      else if (T.matches('select.shape, select.head, select.line')) a[T.className] = T.value;
      else if (T.matches('input.col')) a.color = T.value;
      else if (T.matches('input.lab')) a.label = T.value;
      return v.changed(false);
    }
    const bm = v.bms.find(x => x.n === +li.dataset.n); if (!bm) return;
    if (T.matches('input.txt')) { bm.text = T.value; v.saveBookmarks(); }
    else if (T.matches('input.col')) { bm.color = T.value; li.querySelector('.bn').style.background = T.value; v.changed(false); }
  }
  change(e) {
    const v = this.v; // time and signal of a bookmark: on Enter / leaving the field
    const T = e.target, li = T.closest('li'), bm = li && v.bms.find(x => x.n === +li.dataset.n); if (!bm) return;
    if (T.matches('input.tm')) {
      const t = v.parseWhen(T.value, bm.t);
      if (t == null || !isFinite(t)) { T.value = v.when(bm.t); T.classList.add('bad'); setTimeout(() => T.classList.remove('bad'), 900); return; }
      bm.t = Math.min(Math.max(t, v.M.t0), v.M.t1);
      if (bm.t < v.t0 || bm.t > v.t0 + v.span) v.t0 = v.clamp(bm.t - v.span / 2);
      v.changed(true);
    } else if (T.matches('input.sig')) {   // a full path or a name; empty: the time axis
      const val = T.value.trim(), r = val && (v.M.rows.find(x => x.type === 'sig' && x.full === val) || v.M.rows.find(x => x.type === 'sig' && x.name === val));
      if (val && !r) { T.value = bm.signal || ''; v.bad(T); return; }
      bm.signal = r ? r.full : null; v.changed(true);
    }
  }
}

/* ---------------- interactive viewer ---------------- */
const VIEWS = new Set(), ACTIVE = { view: null };   // ACTIVE.view: the viewer used last (Esc while the focus is on the page)
const PLUGINS = [];   // WaveFW.plugin(fn): fn(viewer) for every viewer, now and later (wavefw/sva.js: the assertions panel)
class WaveView {
  constructor(root, model, opts = {}) {
    this.root = root; this.M = parse(model); this.opts = opts;
    const M = this.M;
    applyLook(root, opts.theme ?? M.theme, Object.assign({}, M.colors, opts.colors));
    this.restyle(false); this.collapsed = foldSet(M, this.S.fold);
    this.picks = hlPick(M, this.S.highlight); this.hlFrom = JSON.stringify(this.S.highlight ?? null);
    this.found = new Map(); this.findPicks = new Map(); this.findHl = this.S.findHighlight; this.findOpen = this.S.findOpen;   // fuzzy find
    this.storeId = this.storeName();
    this.paintKey = 'wavefw.paint:' + this.storeId;
    this.painted = new Map(); this.loadPaint();
    this.t0 = M.t0; this.span = M.t1 - M.t0;
    this.minSpan = opts.minSpan ?? (M.timed ? Math.max(this.span / 1e6, 10) : 0.5);
    this.cursor = opts.cursor ?? M.cursor ?? M.t0;
    this.markers = (opts.markers || []).concat(M.markers);
    this.jumps = opts.jumps || M.jumps || (this.markers.length && this.markers.length <= 6
      ? this.markers.map(m => ({ label: '→ ' + m.label, t: m.t, span: this.span / 5 })) : []);
    this.sel = null; this.edgeKind = 'any';   // selected signal row (edge search, bookmarks), edge kind
    this.extraJSON = [];   // plugins: () -> '"key": …' lines for the bookmarks JSON (or null)
    this.extraRows = [];   // plugins: rows under a group (withExtra)
    this.extraPicks = new Map();   // plugins: rows highlighted, row -> a token ('hl8': --wave-hl8) or a colour index; Esc clears (then wavefw:reset)
    this.keys = {};   // plugins: key -> fn(event) on the waves (addKey)
    this.rowMarks = new Map(); this.rowTitles = new Map();   // plugins: classes and tooltips of name rows (rowClass, rowTitle)
    const hints = this.hints = [];   // plugins: lines of the hint under the waves; hints.push() shows them
    hints.push = (...a) => { const n = Array.prototype.push.apply(hints, a); this.renderHint(); return n; };
    this.bmKey = 'wavefw.bookmarks:' + this.storeId;
    Object.assign(this, this.loadBookmarks()); root.waveView = this;   // this.bms, this.arrows
    this.build(); this.fit();
    if (opts.from != null || opts.to != null) { // initial view window (Fit still shows everything)
      const a = opts.from ?? M.t0, b = opts.to ?? M.t1;
      this.span = Math.min(Math.max(b - a, this.minSpan), M.t1 - M.t0); this.t0 = this.clamp(a); this.draw();
    }
    this.ro = new ResizeObserver(() => this.draw()); this.ro.observe(this.wcol);
    // the canvas is only as tall as the visible part of the rows (sticky in its column): redraw when that part moves
    this.onScroll = () => { if (!this.raf && this.lay && this.lay.H > this.hc + 1) this.raf = requestAnimationFrame(() => { this.raf = 0; if (this.root.isConnected) this.draw(); }); };
    window.addEventListener('scroll', this.onScroll, { passive: true }); window.addEventListener('resize', this.onScroll);
    this.bodyEl.addEventListener('scroll', this.onScroll, { passive: true });
    VIEWS.add(this);
    for (const p of PLUGINS) try { p(this); } catch (e) { console.error('wavefw plugin:', e); }
  }
  // what this viewer's bookmarks, paint and bindings are stored under in this browser: the page, then opts.key, the id,
  // the data-wave reference or the title; several viewers of one data-wave (a bench and its lazy cards) are told apart by
  // their place among them in the page (the first keeps the plain name). Two live viewers with one name: a warning.
  storeName() {
    const r = this.root, o = this.opts, ref = r.dataset.wave;
    let id = location.pathname + ':' + (o.key || r.id || ref || this.M.title);
    if (!o.key && !r.id && ref) { const k = [...document.querySelectorAll('[data-wave]')].filter(e => e.dataset.wave === ref).indexOf(r); if (k > 0) id += '#' + (k + 1); }
    for (const v of VIEWS) if (v.storeId === id && v.root.isConnected) console.warn(`wavefw: two viewers store their bookmarks as "${id}": give one an id or opts.key`);
    return id;
  }
  // settings from all layers; a global WaveFW.configure() calls this again on every viewer
  restyle(redraw = true) {
    const S = this.S = settings(GLOBAL, this.M.cfg, this.opts);
    this.groupStroke = groupPaint(this.M, S.groupColors);
    for (const [name, v] of styleVars(Object.assign({}, this.M.cfg, this.opts))) this.root.style.setProperty(name, v);
    this.rowH = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight }; this.hdrH = S.headerHeight;
    this.sort = S.sort; this.sortIgnore = S.sortIgnore;
    this.root.style.setProperty('--wv-dim', S.dim);
    this.root.classList.toggle('wv-scroll', S.maxHeight != null && S.maxHeight !== '');   // own scroll bar, bar stays in view
    const hlFrom = JSON.stringify(S.highlight ?? null);   // a new "highlight" setting (configure) replaces the picks
    if (redraw && hlFrom !== this.hlFrom) { this.hlFrom = hlFrom; this.picks = hlPick(this.M, S.highlight); }
    if (redraw && this.qEl && this.q) this.find(this.q);
    if (redraw) { const i = this.root.querySelector('input.pfx'); if (i) i.value = S.sortIgnore.join(','); this.fitPfx(); this.renderNames(); this.draw(); this.settingsChanged(); }
  }
  build() {
    const r = this.root; r.classList.add('wv');
    r.innerHTML = Bar.html(this);
    this.bar = new Bar(this);
    this.names = new Names(this);
    const c = this.canvas;
    // wheel by its size: a mouse notch (100 px) zooms ×1.22, a trackpad's small steps zoom smoothly, ctrl+wheel (a pinch)
    // zooms faster; a horizontal swipe or shift+wheel pans by the pixels moved. deltaMode: lines (16 px) or pages.
    c.addEventListener('wheel', e => {
      e.preventDefault();
      const u = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? c.clientHeight || 400 : 1;
      let dx = e.deltaX * u, dy = e.deltaY * u;
      if (e.shiftKey && !dx) { dx = dy; dy = 0; }
      if (Math.abs(dx) > Math.abs(dy)) { this.t0 = this.clamp(this.t0 + dx / this.pxPerT()); this.invalidate(); }
      else if (dy) this.zoom(Math.exp(dy * (e.ctrlKey ? 0.01 : 0.002)), this.frac(e), true);
    }, { passive: false });
    let drag = null;
    const local = e => { const b = c.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top + (this.oy || 0)]; };   // layout y
    // on a bookmark: drag moves it (time + signal row), shift+drag draws an arrow to another bookmark; elsewhere drag pans
    c.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;   // right / middle button: not a cursor, not a pan (the context menu comes in 9.5)
      const [x, y] = local(e), bm = this.bmAt(x, y);
      drag = { x: e.clientX, y: e.clientY, t0: this.t0, moved: false, bm, arrow: bm && e.shiftKey };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove', e => {
      const [x, y] = local(e);
      if (!drag) {
        const bm = this.bmAt(x, y), o = !bm && (this.lay || []).find(o => y >= o.y && y < o.y + o.h), tip = o && o.row.tip ? o.row.tip(x, y - o.y, this) : '';
        const val = !bm && !tip && o && o.row.type === 'sig' && o.row.tr ? this.valueTip(o.row, this.t0 + x / this.pxPerT()) : '';   // the value under the pointer
        c.style.cursor = bm ? 'grab' : tip ? 'pointer' : ''; c.title = bm ? `Bookmark ${bm.n}: drag to move it, shift+drag to another bookmark for an arrow` : tip || val; return;
      }
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.hypot(dx, dy) > 3) drag.moved = true;
      if (!drag.moved) return;
      if (drag.arrow) { this.rubber = { from: drag.bm.n, x, y }; this.draw(); }
      else if (drag.bm) { c.style.cursor = 'grabbing'; this.moveBookmark(drag.bm, x, y); }
      else { this.t0 = this.clamp(drag.t0 - dx / this.pxPerT()); this.draw(); }
    });
    c.addEventListener('pointerup', e => {
      const [x, y] = local(e);
      if (drag && drag.moved && drag.arrow) {
        const to = this.bmAt(x, y); this.rubber = null;
        if (to && to.n !== drag.bm.n) { this.arrows.push(arNorm([{ from: drag.bm.n, to: to.n }])[0]); this.saveBookmarks(); this.renderNotes(); }
        this.draw();
      } else if (drag && drag.moved && drag.bm) { c.style.cursor = 'grab'; this.saveBookmarks(); this.renderNotes(); }
      else if (drag && !drag.moved) {
        const hit = this.bmAt(x, y), mid = !hit && this.bmGeo && this.bmGeo.mids.find(([, mx, my]) => Math.hypot(mx - x, my - y) <= 10);
        if (hit) { this.cursor = hit.t; this.draw(); this.notesEl.querySelector(`li[data-n="${hit.n}"] input.txt`)?.focus(); }
        else if (mid) this.notesEl.querySelector(`li[data-a="${mid[0]}"] input.lab`)?.focus();
        else {   // cursor here; the signal row under the pointer becomes the selected one (a row of a plugin may take the click)
          const row = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
          if (!(row && row.row.click && row.row.click(x, y - row.y, this))) {
            this.cursor = this.timeAt(x);
            if (row && row.row.type === 'sig' && row.row.tr) this.sel = row.row;
            this.renderNames(); this.draw();
          }
        }
      }
      drag = null;
    });
    c.addEventListener('pointercancel', () => { drag = null; if (this.rubber) { this.rubber = null; this.draw(); } });
    c.addEventListener('keydown', e => {
      const k = e.key, copy = (k === 'c' || k === 'C') && (e.ctrlKey || e.metaKey) && !e.altKey; let h = true;
      if ((e.ctrlKey || e.metaKey || e.altKey) && !copy) return;   // ctrl+S, ctrl+M … stay the browser's
      if (k === '+' || k === '=') this.zoom(0.5, 0.5); else if (k === '-') this.zoom(2, 0.5); else if (k === '0') this.fit();
      else if (k === 's' && this.S.sortButton) this.setSort(SORTS[(SORTS.indexOf(this.sort) + 1) % SORTS.length]);
      else if (this.q && (k === 'c' || k === 'C') && (e.ctrlKey || e.metaKey)) this.clearFind();   // on the waves: ctrl+C ends the search
      else if (k === 'Escape') h = false;   // handled by the viewer (reset)
      else if (k === ']' || k === '[') this.edge(k === ']' ? 1 : -1);
      else if (k === 'e') { const ks = Object.keys(EDGE_KINDS); this.edgeKind = ks[(ks.indexOf(this.edgeKind) + 1) % ks.length]; this.edgeSel.value = this.edgeKind; }
      else if (k === 'm') this.mark();
      else if (k === '/') { this.qEl.focus(); this.qEl.select(); }
      else if (k === 'c' && !e.ctrlKey && !e.metaKey) this.showCursor();   // the window around the cursor
      else if ((k === 'n' || k === 'N') && !e.ctrlKey && !e.metaKey && this.found.size) this.findStep(k === 'n' ? 1 : -1);   // like vim
      else if ((k === 'c' || k === 'C') && (e.ctrlKey || e.metaKey)) {   // copy: the selected signal, else the highlighted rows
        const rows = this.sel ? [this.sel] : [...this.picks.keys()]; if (rows.length) this.copyRows(rows); else h = false;
      }
      else if (k === 'ArrowDown' || k === 'ArrowUp') {
        const sigs = this.vis.filter(r => r.type === 'sig' && r.tr), i = sigs.indexOf(this.sel);
        this.select(sigs[Math.min(Math.max(i < 0 ? 0 : i + (k === 'ArrowDown' ? 1 : -1), 0), sigs.length - 1)] || null);
      }
      else if ((k === 'ArrowLeft' || k === 'ArrowRight') && e.shiftKey) this.nudge(k === 'ArrowRight' ? 1 : -1);   // the cursor, a 100th of the view
      else if (k === 'ArrowLeft') { this.t0 = this.clamp(this.t0 - this.span * 0.2); this.invalidate(); }
      else if (k === 'ArrowRight') { this.t0 = this.clamp(this.t0 + this.span * 0.2); this.invalidate(); }
      else if (this.keys[k] && !e.ctrlKey && !e.metaKey && !e.altKey) this.keys[k](e);
      else h = false;
      if (h) e.preventDefault();
    });
    // Esc anywhere in the viewer (waves, find field, names) except the bookmark fields: back to no search, no highlight,
    // no selected signal; the view (opened modules, scroll, time) stays
    this.onActive = () => { ACTIVE.view = this; };
    r.addEventListener('pointerdown', this.onActive, true);
    r.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || e.target.closest('.notes')) return;
      e.preventDefault(); this.reset();
      if (e.target === this.qEl) this.canvas.focus({ preventScroll: true });
    });
    this.notes = new Notes(this);
    this.renderNames(); this.renderNotes();
  }
  fitPfx() { const i = this.root.querySelector('input.pfx'); if (i) i.style.width = Math.max(7, i.value.length + 2) + 'ch'; }
  // every row in display order (the model's and the plugins'), and the ones not folded away
  allRows() { return (this.rowsAll = withExtra(orderRows(this.M.rows, this.sort, this.sortIgnore, this.S.groupOrder), this.extraRows, this.M, this)); }
  visible() { return this.allRows().filter(r => !r.anc.some(id => this.collapsed.has(id))); }
  settingsChanged() { this.root.dispatchEvent(new CustomEvent('wavefw:settings')); }   // sort, prefixes, settings
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
  // fuzzy find: rows matching every word; options: found rows in front (findHl), only their modules open (findOpen)
  // restore: give back the folding from before the search (the Open option switched off); clearing the search keeps the
  // modules it opened, so the view stays where it is
  find(q, restore = false, keep = null) {
    this.q = q;
    const terms = String(q || '').trim().split(/\s+/).filter(w => w.replace(/\./g, ''));   // "." alone is no query
    this.found = new Map();
    if (terms.length) for (const r of this.allRows()) { if (r.type !== 'space') { const m = findRow(r, terms, this.M); if (m) this.found.set(r, m); } }
    let moved = null;
    if (terms.length && this.findOpen) {   // fold everything but the way to the matches
      if (!this.foldSaved) { this.foldSaved = new Set(this.collapsed); this.foldTouched = false; }
      const keep = new Set(); for (const r of this.found.keys()) r.anc.forEach(id => keep.add(id));
      this.collapsed = new Set(Object.keys(this.M.groups).map(Number).filter(id => !keep.has(id)));
    } else if (this.foldSaved) {
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
    if (this.cntEl) { const n = this.found.size; this.cntEl.textContent = terms.length ? (n ? `${n} found` : 'no match') : ''; this.cntEl.classList.toggle('none', !!terms.length && !n); }
    this.renderNames(); this.draw();
    if (moved) { const d = this.rowTop(moved[0]) - moved[1]; if (d) { if (this.root.classList.contains('wv-scroll')) this.bodyEl.scrollTop += d; else window.scrollBy(0, d); this.draw(); } }
    return this;
  }
  rowTop(r) { const k = this.vis ? this.vis.indexOf(r) : -1, el = k >= 0 && this.namesEl.querySelector(`.row[data-r="${k}"]`); return el ? el.getBoundingClientRect().top : null; }
  reset() { // Esc: search, highlight and the selected signal go; scroll and time stay, the folding from before the search is back
    const keep = this.fiRow || this.sel;
    if (this.qEl) this.qEl.value = '';
    this.picks = new Map(); this.sel = null; this.extraPicks = new Map();
    this.root.dispatchEvent(new CustomEvent('wavefw:reset'));
    return this.find('', false, keep);
  }
  unit() { // the unit the cursor fields start in: the one of a tenth of the whole span
    const ref = (this.M.t1 - this.M.t0) / 10, u = UNITS.find(([f]) => ref >= f) || UNITS[UNITS.length - 1];
    return u[1];
  }
  // "250" in the unit chosen (cycles for an untimed diagram), or "85.12us" with its own unit -> model time
  parseIn(v, sel) {
    v = String(v ?? '').trim();
    if (!v) return undefined;
    if (/^-?[\d.]+(e-?\d+)?$/i.test(v)) return parseFloat(v) * (this.M.timed && sel ? UNIT_PS[sel.value] : 1);
    return this.M.timed ? parseT(v) : undefined;
  }
  bad(inp) { inp.classList.add('bad'); setTimeout(() => inp.classList.remove('bad'), 900); }
  setCursor(v) { // cursor at a typed time; the view follows when it is outside
    const t = typeof v === 'number' ? v : this.parseIn(v, this.cuEl);
    if (t == null || !isFinite(t)) { this.bad(this.ctEl); return this; }
    this.cursor = Math.min(Math.max(t, this.M.t0), this.M.t1);
    if (this.cursor < this.t0 || this.cursor > this.t0 + this.span) this.t0 = this.clamp(this.cursor - this.span / 2);
    this.draw(); this.syncCursorFields(true); return this;
  }
  showCursor(v) { // window of a span (typed, else the current one) centred on the cursor
    const sp = v == null || v === '' ? this.span : typeof v === 'number' ? v : this.parseIn(v, this.suEl);
    if (sp == null || !isFinite(sp) || sp <= 0) { this.bad(this.csEl); return this; }
    this.span = Math.min(Math.max(sp, this.minSpan), this.M.t1 - this.M.t0);
    this.t0 = this.clamp(this.cursor - this.span / 2); this.draw(); this.syncCursorFields(true); return this;
  }
  syncCursorFields(force) { // the fields show the cursor and the span, except while one is being typed in
    if (!this.ctEl) return;
    const show = (inp, sel, t) => { if (force || document.activeElement !== inp) inp.value = String(Number((t / (this.M.timed && sel ? UNIT_PS[sel.value] : 1)).toPrecision(7))); };
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
    const el = this.namesEl.querySelector(`.row[data-r="${this.vis.indexOf(r)}"]`); if (!el) return this;
    const own = this.root.classList.contains('wv-scroll'), box = own ? this.bodyEl.getBoundingClientRect() : { top: 0, bottom: window.innerHeight };
    const q = el.getBoundingClientRect(), d = q.top + q.height / 2 - (box.top + this.hdrH + box.bottom) / 2;
    if (own) this.bodyEl.scrollTop += d; else window.scrollBy(0, d);
    this.invalidate();
    return this;
  }
  copyRows(rows) { // full paths, one per line, to the clipboard
    const text = rows.map(r => r.full || r.name).join('\n'), done = () => this.toast(`copied ${rows.length}`);
    if (!rows.length) return this.toast('nothing to copy');
    const fallback = () => { const ta = document.createElement('textarea'); ta.value = text; ta.style.cssText = 'position:fixed;opacity:0;top:0';
      document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (e) { /* no clipboard */ } ta.remove(); this.canvas.focus({ preventScroll: true }); };
    try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
    this.copied = text; return this;
  }
  toast(msg) { const t = this.root.querySelector('.bar .toast'); if (!t) return; t.textContent = msg; clearTimeout(this.toastT); this.toastT = setTimeout(() => { t.textContent = ''; }, 1600); }
  paint(color) { // the found signals take this colour (trace, outline, name); kept in this browser
    for (const r of this.found.keys()) if (r.type === 'sig') this.painted.set(r.full, color);
    this.savePaint(); this.renderNames(); this.draw(); return this;
  }
  unpaint() { this.painted.clear(); this.savePaint(); this.renderNames(); this.draw(); return this; }
  loadPaint() {
    try { for (const [k, c] of Object.entries(JSON.parse(localStorage.getItem(this.paintKey) || '{}'))) this.painted.set(k, c); }
    catch (e) { /* no storage */ }
  }
  // the colour a row is drawn in here: your paint, its own colour, its group's (groupColors); the model is not changed
  strokeOf(r) { return (r.type === 'sig' && this.painted.get(r.full)) || r.stroke || (this.groupStroke && this.groupStroke.get(r)) || undefined; }

  /* ---------------- the plugin API (wavefw/sva.js uses only this, the rows of view.extraRows and the events) ---------------- */
  // a tool group of the bar by its label ("go to", "assertions" …), made at the end when missing; content: HTML or an
  // element, appended to the group; -> the group's element
  addTool(group, content) {
    const tools = this.root.querySelector('.bar .tools');
    let g = [...tools.children].find(t => t.dataset.tg === group);
    if (!g) { g = document.createElement('span'); g.className = 'tg'; g.dataset.tg = group; g.innerHTML = `<span class="tl">${esc(group)}</span>`; tools.appendChild(g); }
    if (typeof content === 'string') g.insertAdjacentHTML('beforeend', content); else if (content) g.appendChild(content);
    return g;
  }
  addPanel(el) { this.root.querySelector('.bar').after(el); return el; }   // a panel under the bar (sva.js: the assertions)
  // the row of an element of the names column (an event's target) or at a y of the layout (the waves), else null
  rowAt(x) {
    if (typeof x === 'number') { const o = (this.lay || []).find(o => x >= o.y && x < o.y + o.h); return o ? o.row : null; }
    const el = x && x.closest && x.closest('.row[data-r]'); return el && el.closest('.names') === this.namesEl ? this.vis[+el.dataset.r] || null : null;
  }
  rowEl(r) { const k = this.vis ? this.vis.indexOf(r) : -1; return k < 0 ? null : this.namesEl.querySelector(`.row[data-r="${k}"]`); }   // its name row
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
  listen(part, type, fn, o) { ({ names: this.namesEl, waves: this.canvas, bar: this.root.querySelector('.bar'), lists: this.notesEl })[part].addEventListener(type, fn, o); return this; }
  // a key on the waves (without ctrl / alt / meta) and its line in the hint ("f F next / previous failure")
  addKey(key, fn, help) { this.keys[key] = fn; if (help) this.hints.push(help); return this; }
  renderHint() { const h = this.root.querySelector('.hint'); if (h) h.textContent = [this.hintBase, ...this.hints].join(' · '); }
  savePaint() {
    try { if (this.painted.size) localStorage.setItem(this.paintKey, JSON.stringify(Object.fromEntries(this.painted))); else localStorage.removeItem(this.paintKey); } catch (e) { /* private mode */ }
    if (this.unpaintBtn) this.unpaintBtn.hidden = !this.painted.size;
  }
  expandAll() { this.collapsed = new Set(); this.foldTouched = true; this.renderNames(); this.draw(); return this; }
  collapseAll() { this.collapsed = new Set(Object.keys(this.M.groups).map(Number)); this.foldTouched = true; this.renderNames(); this.draw(); return this; }
  select(row) { // the signal for edge search and bookmarks: a row, a full path / name, or null
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row) || this.M.rows.find(r => r.type === 'sig' && r.name === row);
    this.sel = row && row.type === 'sig' && row.tr ? row : null; this.renderNames(); this.draw();
    this.namesEl.querySelector('.row.sel')?.scrollIntoView({ block: 'nearest' });
    return this;
  }
  // cursor to the next (dir 1) / previous (-1) edge of the selected signal, or of any shown signal; the view follows
  edge(dir, kind = this.edgeKind) {
    let best = null;
    for (const s of this.sel ? [this.sel] : this.vis.filter(r => r.type === 'sig' && r.tr)) {
      const t = findEdge(s, this.cursor, dir, kind);
      if (t != null && (best == null || (dir > 0 ? t < best : t > best))) best = t;
    }
    if (best == null) return this;
    this.cursor = best;
    if (best < this.t0 || best > this.t0 + this.span) this.t0 = this.clamp(best - this.span / 2);
    this.draw(); return this;
  }
  // nearest edge of signal s within px pixels of t (the initial value is not an edge), else t
  snap(s, t, px = 6) {
    if (!s || !s.tr) return t;
    const tol = px / this.pxPerT(), i = lastLE(s.tr, t);
    const near = [i, i + 1].filter(k => k > 0 && k < s.tr.length && Math.abs(s.tr[k].t - t) <= tol).sort((a, b) => Math.abs(s.tr[a].t - t) - Math.abs(s.tr[b].t - t))[0];
    return near != null ? s.tr[near].t : t;
  }
  bmAt(x, y) { const pos = this.bmGeo && this.bmGeo.pos; return pos && this.bms.find(b => { const p = pos.get(b.n); return p && Math.hypot(p[0] - x, p[1] - y) <= 9; }); }
  // drag on the waves: time from x (snapped to an edge of the row), signal from the row under y (the time axis: no signal)
  moveBookmark(b, x, y) {
    const o = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
    if (y < (this.oy || 0) + this.hdrH) b.signal = null; else if (o && o.row.type === 'sig') b.signal = o.row.full;
    const s = b.signal != null ? this.M.rows.find(r => r.type === 'sig' && r.full === b.signal) : null;
    b.t = Math.min(Math.max(this.snap(s, this.t0 + x / this.pxPerT()), this.M.t0), this.M.t1);
    this.draw();
  }
  // bookmark: numbered circle at the cursor on the selected signal (snapped to its edge within 6 px), described below the waves
  mark(text = '') {
    const s = this.sel, t = this.cursor = this.snap(s, this.cursor);
    const n = Math.max(0, ...this.bms.map(b => b.n)) + 1;
    this.bms.push({ n, t, signal: s ? s.full : null, text, color: null });
    this.saveBookmarks(); this.renderNotes(); this.draw();
    if (!text) this.notesEl.querySelector(`li[data-n="${n}"] input.txt`)?.focus();
    return n;
  }
  arrow(from, to, opts = {}) { this.arrows.push(...arNorm([Object.assign({ from, to }, opts)])); this.saveBookmarks(); this.renderNotes(); this.draw(); return this; }
  // JSON for a config file / WaveJSON (t in model units: ps for timed waves, else cycles); defaults are left out
  bookmarks() { return this.bms.map(b => Object.fromEntries(Object.entries({ n: b.n, t: b.t, signal: b.signal, text: b.text, color: b.color }).filter(([, v]) => v != null && v !== ''))); }
  arrowList() {
    return this.arrows.map(a => Object.fromEntries(Object.entries({ from: a.from, to: a.to, shape: a.shape, head: a.head === '>' ? null : a.head, line: a.line === 'solid' ? null : a.line,
      color: a.color, label: a.label }).filter(([k, v]) => v != null && (v !== '' || k === 'head'))));   // head "" = no head
  }
  setBookmarks(list, arrows = []) { this.bms = bmNorm(list); this.arrows = arNorm(arrows, list); this.saveBookmarks(); this.renderNotes(); this.draw(); return this; }
  loadBookmarks() { // this browser's copy (localStorage) wins over the page's "bookmarks" / "arrows"
    try {
      const v = localStorage.getItem(this.bmKey);
      if (v != null) { const o = JSON.parse(v), list = Array.isArray(o) ? o : o.bookmarks; return { bms: bmNorm(list), arrows: arNorm(o.arrows, list) }; }
    } catch (e) { /* no storage: page bookmarks */ }
    return { bms: this.M.bookmarks.map(b => Object.assign({}, b)), arrows: this.M.arrows.map(a => Object.assign({}, a)) };
  }
  saveBookmarks() { try { localStorage.setItem(this.bmKey, JSON.stringify({ bookmarks: this.bookmarks(), arrows: this.arrowList() })); } catch (e) { /* private mode */ } }
  when(t) { return this.M.timed ? fmtExact(t) : trimNum(t); }
  // typed time: "250ns", "85.12us"; a plain number is in the unit shown (µs for "85.120 µs"), or cycles
  parseWhen(str, ref) {
    const v = String(str).trim().replace(/^cycle\s*/i, '');
    if (this.M.timed && /^-?[\d.]+(e-?\d+)?$/i.test(v)) return parseFloat(v) * (UNITS.find(([f]) => Math.abs(ref) >= f) || UNITS[UNITS.length - 1])[0];
    return parseT(v);
  }
  renderNotes() { this.notes.render(); }   // the bookmark and arrow lists under the waves (Notes)
  renderNames() { this.names.render(); }   // the names column (Names)
  rowState(el, r) { this.names.state(el, r); }
  changed(list) { this.saveBookmarks(); if (list) this.renderNotes(); this.draw(); }
  layout() { return layoutRows(this.rowsL, this.rowH, this.S.laneHeight, this.hdrH); }
  frac(e) { const r = this.canvas.getBoundingClientRect(); return (e.clientX - r.left) / r.width; }
  pxPerT() { return this.canvas.getBoundingClientRect().width / this.span; }
  clamp(t) { return Math.min(Math.max(t, this.M.t0), this.M.t1 - this.span); }
  zoom(f, at, lazy = false) { // lazy: in the next frame (the wheel: many events per frame)
    const tAt = this.t0 + at * this.span;
    this.span = Math.min(Math.max(this.span * f, this.minSpan), this.M.t1 - this.M.t0);
    this.t0 = this.clamp(tAt - at * this.span); if (lazy) this.invalidate(); else this.draw();
  }
  fit() { this.t0 = this.M.t0; this.span = this.M.t1 - this.M.t0; this.draw(); }
  goto(t, span) { this.span = Math.min(Math.max(span, this.minSpan), this.M.t1 - this.M.t0); this.t0 = this.clamp(t - this.span * 0.1); this.cursor = t; this.draw(); }
  fmt(t, ref, unitRef) { return this.M.timed ? fmtTime(t, ref, unitRef) : 'cycle ' + (t + (this.M.tick || 0)).toFixed(Math.max(0, Math.min(2, Math.ceil(-Math.log10(ref))))); }
  // the cursor as typed or clicked: exact (fmtExact), in the unit of the view span
  fmtCursor(t) { return this.M.timed ? fmtExact(t, this.span) : 'cycle ' + trimNum(t + (this.M.tick || 0)); }
  // a time from a click at x: rounded to a 1-2-5 step of about a pixel, so the cursor reads as a short exact number
  timeAt(x) {
    const t = this.t0 + x / this.pxPerT(), tpp = 1 / this.pxPerT(), e = 10 ** Math.floor(Math.log10(tpp));
    let q = [1, 2, 5, 10].find(m => m * e >= tpp) * e; if (this.M.timed) q = Math.max(1, q);
    return Math.min(Math.max(Math.round(Math.round(t / q) * q * 1e6) / 1e6, this.M.t0), this.M.t1);
  }
  nudge(dir) { // shift+← / →: the cursor a hundredth of the view, the view follows
    this.cursor = Math.min(Math.max(this.cursor + dir * this.span / 100, this.M.t0), this.M.t1);
    if (this.cursor < this.t0 || this.cursor > this.t0 + this.span) this.t0 = this.clamp(this.cursor - this.span / 2);
    this.draw(); return this;
  }
  invalidate() { // one redraw in the next frame, however many changes ask for it
    if (!this.inv) this.inv = requestAnimationFrame(() => { this.inv = 0; if (this.root.isConnected) this.draw(); });
  }
  // the tooltip of a signal at t: its value there, the change into it and the next change ("prev → value @ t")
  valueTip(r, t) {
    const a = r.tr, i = lastLE(a, t), txt = o => o.k === '=' ? vtext(r, o, this.S.radix) : o.k;
    if (i < 0) return `${r.name}: no value yet`;
    const o = a[i], p = a[i - 1], n = a[i + 1];
    return `${r.name} = ${txt(o)}` + (p ? `\n${txt(p)} → ${txt(o)} @ ${this.when(o.t)}` : '') + (n ? `\nnext ${txt(n)} @ ${this.when(n.t)}` : '');
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
    if (this.S.arrowLabels === 'lane' && this.laneKey !== laneKey(this.bms, this.arrows)) {   // a bookmark or an arrow label changed: its lane?
      this.laneKey = laneKey(this.bms, this.arrows);
      if (this.laneSig !== JSON.stringify([...arrowLanes(this.vis, this.bms, this.arrows)])) this.renderNames();
    }
    const lay = this.lay = this.layout();
    if (this.wcol.style.height !== lay.H + 'px') this.wcol.style.height = lay.H + 'px';
    if (this.sel && !this.vis.includes(this.sel)) this.sel = null;   // folded away
    if (this.printing) this.paintPrint(lay);
    else { const f = this.size(lay); this.bmGeo = this.paintFrame(this.canvas, f.W, f.Hc, f.oy, lay, true, f.dpr); }
    this.syncReadouts();
  }
  size(lay) { // the canvas: as wide as its column, as tall as the rows in view (at least the axis and a little more)
    const c = this.canvas, dpr = window.devicePixelRatio || 1, H = lay.H, hdr = this.hdrH;
    const W = c.getBoundingClientRect().width || 600, view = this.root.classList.contains('wv-scroll') ? this.bodyEl.clientHeight : window.innerHeight;
    const Hc = this.hc = Math.max(Math.min(H, hdr + 40), Math.min(H, view || H));
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(Hc * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(Hc * dpr); c.style.height = Hc + 'px'; }
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
    const k = W / this.span, X = t => (t - this.t0) * k, tB = this.t0 + this.span;
    if (top) paintAxis(P, { from: this.t0, span: this.span, xL: 0, xR: W, y: 0, h: hdr, yEnd: Hc, X, timed: M.timed, tick: M.tick, every: 1 });
    const shown = lay.filter(o => o.y + o.h > oy + hdr && o.y < oy + Hc);
    g.save(); g.beginPath(); g.rect(0, hdr, W, Hc - hdr); g.clip(); g.translate(0, -oy);   // rows: layout coordinates, under the axis
    const late = [], rowY = paintBody(P, M, shown, X, this.t0, tB, 0, W, this.hl, this.sel, lay, this.band, late, r => this.strokeOf(r));
    paintMarkers(P, this.markers, X, this.t0, tB, oy + hdr, oy + Hc);
    g.restore();
    if (this.cursor >= this.t0 && this.cursor <= tB) P.path([['M', X(this.cursor), 0], ['L', X(this.cursor), Hc]], { stroke: 'acc', w: 1.2 });
    if (late.length) { g.save(); g.beginPath(); g.rect(0, hdr, W, Hc - hdr); g.clip(); g.translate(0, -oy); late.forEach(f => f()); g.restore(); }   // plugin overlays over the cursor
    g.save(); g.translate(0, -oy);
    const geo = paintBookmarks(P, this.bms, this.arrows, X, this.t0, tB, rowY, oy + hdr, oy + Hc, oy + this.hdrH / 2, this.rubber, laneY(lay, this.S.laneHeight));
    g.restore();
    return geo;
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
    const M = this.M, fire = (name, detail) => this.root.dispatchEvent(new CustomEvent('wavefw:' + name, { detail }));
    if (this.evCursor !== this.cursor) { this.evCursor = this.cursor; fire('cursor', { t: this.cursor }); }
    if (this.evT0 !== this.t0 || this.evSpan !== this.span) { this.evT0 = this.t0; this.evSpan = this.span; fire('view', { t0: this.t0, span: this.span }); }
    if (this.evSel !== this.sel) { this.evSel = this.sel; fire('select', { row: this.sel }); }
    this.syncCursorFields();
    this.curEl.textContent = 'cursor ' + this.fmtCursor(this.cursor) + ' · view ' + (M.timed ? fmtTime(this.span, this.span / 10, this.span) : this.span.toFixed(1) + ' cycles');
    if (this.valsAt !== this.cursor || this.valsGen !== this.namesGen || this.valsRadix !== this.S.radix) {   // value column: only when it changes
      this.valsAt = this.cursor; this.valsGen = this.namesGen; this.valsRadix = this.S.radix;
      let vi = 0;
      for (const r of this.vis) if (r.type === 'sig') {
        const el = this.vals[vi++], v = String(this.valueAt(r, this.cursor));
        if (el.textContent !== v) { el.textContent = v; el.title = v.length > 6 ? v : ''; }   // cut to its column: the title has it all
      }
    }
  }
  setTheme(name) { applyLook(this.root, name || 'auto', null); this.draw(); return this; }
  setColors(map) { applyLook(this.root, undefined, map); this.draw(); return this; }
  // the viewer leaves: observers, window listeners and pending frames go; plugins hear wavefw:destroy and take their part
  destroy() {
    if (!VIEWS.has(this)) return;
    this.ro.disconnect(); window.removeEventListener('scroll', this.onScroll); window.removeEventListener('resize', this.onScroll);
    this.bodyEl.removeEventListener('scroll', this.onScroll); this.root.removeEventListener('pointerdown', this.onActive, true);
    cancelAnimationFrame(this.raf); cancelAnimationFrame(this.inv); clearTimeout(this.toastT);
    if (ACTIVE.view === this) ACTIVE.view = null;
    VIEWS.delete(this);
    this.root.dispatchEvent(new CustomEvent('wavefw:destroy'));
    if (this.root.waveView === this) delete this.root.waveView;
  }
}
