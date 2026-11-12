/* wavelens/src/arrange.js — arranging the bar yourself: the mode, a group dragged by its label, the keyboard dialog, the presets. */

// What moves: whole groups, between places and lines (toolLayout, look.js setToolLayout; kept in this browser for every viewer, the
// last one made also as Mine). The mode (⚙ Arrange the bar…): a dashed outline on each group, a ⠿ on its label, a last line "new
// line — drop a group here", a strip Full | Compact | Mine · Reset · Keys · Done; at rest nothing of it is there (no rule of it
// changes a pixel). A drag: the label, 4 px before it starts, an accent bar where it lands; Esc during it: back as it was; Esc
// else, Done: the mode off. The keys: the dialog (opened by the keys, or Keys): a list per line, alt+arrows move the group, Space
// shows or hides it, a live line says what happened
const ARR_TIPS = { 'ar:full': ['The default order of the groups, the short form when the bar is narrow'],
  'ar:compact': ['The short form at any width: no labels, the rarer controls behind each group\'s ⋯'],
  'ar:mine': ['The order you made last (kept when you pick another)'],
  'ar:reset': ['The bar as the settings have it: the order, the short form, the groups shown'],
  'ar:keys': ['The groups in a list: alt+↑ ↓ ← → move the one in focus, Space shows or hides it'], 'ar:done': ['Arranging done', ['Esc']] };
Object.assign(TIPS, ARR_TIPS);
const ARR_PX = 4;   // px the pointer moves before a drag starts
const ARR_PRESETS = ['full', 'compact', 'mine'].map(k => `<button type="button" data-ar="${k}" aria-pressed="false">${k.charAt(0).toUpperCase() + k.slice(1)}` +
  '</button>').join('');
Object.assign(WaveView.prototype, {
  // the lines of groups the bar shows now (its DOM, in order: every group, the ones hidden and left out too, the new line last)
  barLines() {
    const tools = this.root.querySelector('.bar .tools');
    return [...tools.querySelectorAll(':scope > .tln')].map(ln => [...ln.children].filter(g => g.classList.contains('tg')).map(g => g.dataset.tg))
      .filter(l => l.length);
  },
  // the mode on (kbd: the dialog too) or off; the tools opened for it (not kept, as / does), the menus closed
  arrange(on = true, kbd = false) {
    const bar = this.root.querySelector('.bar'), tools = bar.querySelector('.tools');
    if (!on) {
      if (!this.arranging) return this;
      this.arrDrag && this.arrCancel(); this.arranging = false; bar.classList.remove('arranging');
      for (const x of tools.querySelectorAll('.arr, .tln.newln')) x.remove();
      if (this.arrDlg) { this.arrDlg.remove(); this.arrDlg = null; }
      if (this.toolsPeek) { this.toolsPeek = false; this.layoutShow(); }
      this.arrAc.abort(); this.barFit(); this.stripFit(); return this;
    }
    if (!this.arranging) {
      this.popClose(); this.closeMenu(); this.arranging = true; bar.classList.add('arranging');
      if (this.S.toolsFolded) { this.toolsPeek = true; this.layoutShow(); }
      tools.insertAdjacentHTML('beforeend', '<div class="tln newln" data-ln="new" aria-hidden="true">new line — drop a group here</div>' +
        '<div class="arr" role="toolbar" aria-label="arranging the bar"><span class="arh">Drag a group by its label</span>' +
        ARR_PRESETS + '<button type="button" data-ar="reset">Reset</button><button type="button" data-ar="keys">Keys…</button>' +
        '<button type="button" data-ar="done">Done</button></div>');
      const ac = this.arrAc = new AbortController(), own = { signal: ac.signal };
      tools.querySelector('.arr').addEventListener('click', e => { const b = e.target.closest('button[data-ar]'); if (b) this.arrAct(b.dataset.ar, e); }, own);
      // nothing of the groups works meanwhile: a click (a key's too) on one of their controls is swallowed before it gets there
      tools.addEventListener('click', e => { if (e.target.closest('.tg')) { e.preventDefault(); e.stopPropagation(); } }, { capture: true, ...own });
      tools.addEventListener('pointerdown', e => this.arrDown(e), own);
      const axs = bar.querySelector('.axs');   // the strip over the time axis: a line too (shown with no box: a place to drop a group)
      if (axs) { axs.addEventListener('click', e => { if (e.target.closest('.tg')) { e.preventDefault(); e.stopPropagation(); } }, { capture: true, ...own });
        axs.addEventListener('pointerdown', e => this.arrDown(e), own); }
      // Esc: a drag cancelled, else the mode off (before the viewer's Esc: the window and the search stay)
      G.addEventListener('keydown', e => {
        if (e.key !== 'Escape' || !this.arranging || (this.arrDlg && this.arrDlg.contains(e.target)) || (!this.arrDrag && (this.pops || []).length)) return;
        e.preventDefault(); e.stopPropagation(); if (this.arrDrag) this.arrCancel(); else this.arrange(false);
      }, { capture: true, ...own });
      this.arrMark(); this.stripFit();
    }
    if (kbd) this.arrDialog();
    return this;
  },
  // the strip's presets pressed by what the bar is now; the new line gone when there are TOOL_LINES_MAX lines already
  arrMark() {
    const bar = this.root.querySelector('.bar'), L = toolLines(this.S.toolLayout), B = barKept(), cp = compactOf(this.S.toolsCompact);
    const on = { full: !L && cp === 'auto', compact: cp === true, mine: !!L && !!B.mine && JSON.stringify(L) === JSON.stringify(B.mine) };
    for (const b of bar.querySelectorAll('.arr [data-ar], .wv-arrd [data-ar]')) if (b.dataset.ar in on) b.setAttribute('aria-pressed', on[b.dataset.ar]);
    for (const b of bar.querySelectorAll('[data-ar=mine]')) b.disabled = !B.mine;
    const nl = bar.querySelector('.tln.newln'); if (nl) nl.hidden = this.barLines().length >= TOOL_LINES_MAX;
  },
  arrAct(k, e = {}) {
    if (k === 'full') { this.setToolLayout(null); this.setStripGroups(null); this.setToolAt(null); this.setToolsCompact('auto'); }
    else if (k === 'compact') this.setToolsCompact(true);
    else if (k === 'mine') { const B = barKept(); if (B.mine) { this.setToolLayout(B.mine);
      if (B.msg) this.setStripGroups(B.msg); if (B.mat) this.setToolAt(B.mat); this.setToolsCompact('auto'); } }
    else if (k === 'reset') this.barReset();
    else if (k === 'keys') this.arrDialog();
    else if (k === 'done') { this.arrange(false); const g = this.root.querySelector('.bar .pgear'); if (g && e.detail === 0) g.focus({ preventScroll: true }); }
    if (this.arranging) { this.arrMark(); if (this.arrDlg) this.arrRender(); }
    return this;
  },
  // ⚙ Reset the bar: the order, the short form and the groups shown as the settings have them; this browser keeps none of it
  barReset() {
    try { localStorage.removeItem(BARKEY); } catch (e) { /* none */ }
    this.setToolLayout(undefined, { only: true }); this.setToolsCompact(null, { only: true }); this.setToolsHidden(null);
    this.setStripGroups(null, { only: true }); this.setToolAt(null, { only: true }); this.setCursorStrip(null, { only: true });
    for (const w of VIEWS) if (w !== this && w.root.isConnected) w.barReload();
    this.toast('the bar as the settings have it'); return this;
  },
  // a drag by a label: pointer capture; past ARR_PX the group goes with the pointer, an accent bar where it lands
  arrDown(e) {
    const tl = e.button === 0 && e.target.closest('.tg > .tl'); if (!tl || this.arrDrag) return;
    e.preventDefault(); const g = tl.parentElement; tl.setPointerCapture(e.pointerId);
    const d = this.arrDrag = { g, tl, x: e.clientX, y: e.clientY, on: false, id: e.pointerId, grab: e.clientX - g.getBoundingClientRect().left };
    const move = ev => {
      if (!d.on && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) < ARR_PX) return;
      if (!d.on) { d.on = true; g.classList.add('drag'); d.mark = document.createElement('span'); d.mark.className = 'arx';
        this.root.querySelector('.bar').append(d.mark); }
      this.arrOver(ev.clientX, ev.clientY);
    };
    const up = () => { end(); if (d.on && d.to) this.arrDrop(); else this.arrCancel(); };
    const end = () => { for (const [t, f] of [['pointermove', move], ['pointerup', up], ['pointercancel', cancel]]) tl.removeEventListener(t, f); };
    const cancel = () => { end(); this.arrCancel(); };
    d.end = end;
    tl.addEventListener('pointermove', move); tl.addEventListener('pointerup', up); tl.addEventListener('pointercancel', cancel);
  },
  // where the group would land at (x, y): the line under the pointer (or the new line, or the strip over the time axis). Over a group
  // of it: before it or after it (by its middle), in the flow; in the free room of the line (right of its groups, or between two
  // apart): placed there, its left on the grid (TOOL_GRID px from the line's left), at the place its left gives (0 .. 1 of the room);
  // in the strip: always placed. The accent bar shows where its left edge goes
  arrOver(x, y) {
    const d = this.arrDrag, bar = this.root.querySelector('.bar'), tools = bar.querySelector('.tools'), room = bar.querySelector('.axs:not([hidden]) .axr');
    const lines = [...tools.querySelectorAll(':scope > .tln')].filter(l => !l.hidden && l.getClientRects().length);
    if (room) lines.push(room);
    const near = l => { const r = l.getBoundingClientRect(); return Math.max(r.top - y, y - r.bottom, 0); };
    const ln = lines.reduce((b, l) => (near(l) < near(b) ? l : b), lines[0]);
    const R = ln.getBoundingClientRect(), w = d.g.getBoundingClientRect().width, strip = ln === room;
    const gs = strip ? [] : [...ln.children].filter(c => c.classList.contains('tg') && c !== d.g && c.getClientRects().length);
    const row = gs.filter(c => { const r = c.getBoundingClientRect(); return y >= r.top - 3 && y <= r.bottom + 3; });
    const over = row.find(c => { const r = c.getBoundingClientRect(); return x >= r.left - 2 && x <= r.right + 2; });
    let left, at = null, before;
    if (over) {   // in the flow: before it or after it
      const r = over.getBoundingClientRect(), aft = x > r.left + r.width / 2;
      before = aft ? over.nextElementSibling : over; left = aft ? r.right + 4 : r.left - 4;
    } else {      // placed: on the grid, before the first group of the row right of it
      const free = Math.max(0, R.width - w);
      left = Math.min(free, Math.max(0, Math.round((x - d.grab - R.left) / TOOL_GRID) * TOOL_GRID));
      at = free ? Math.round(left / free * 1000) / 1000 : 0;
      before = strip ? null : (row.length ? row : gs).find(c => c.getBoundingClientRect().left > R.left + left) || null;
      if (before && before.classList.contains('arx')) before = null;
      d.px = left; left += R.left;
    }
    const top = row.length ? Math.min(...row.map(c => c.getBoundingClientRect().top)) : R.top;
    const bot = row.length ? Math.max(...row.map(c => c.getBoundingClientRect().bottom)) : Math.max(R.bottom, R.top + 20);
    Object.assign(d.mark.style, { left: Math.round(left - 1) + 'px', top: Math.round(top) + 'px', height: Math.round(bot - top) + 'px' });
    d.mark.classList.toggle('placed', at != null);
    d.to = { ln, before, at, strip };
  },
  // the drop: the group in its line (DOM, then the arrangement of the lines), in the strip or out of it, placed or in the flow; one step
  arrDrop() {
    const d = this.arrDrag; this.arrDrag = null; d.g.classList.remove('drag'); if (d.mark) d.mark.remove();
    const n = d.g.dataset.tg, to = d.to, A = toolAts(this.S.toolAt), SG = this.stripGroups();
    if (to.at == null) delete A[n]; else A[n] = to.at;
    if (to.strip) { if (!SG.includes(n)) SG.push(n); }
    else { const i = SG.indexOf(n); if (i >= 0) SG.splice(i, 1); to.ln.insertBefore(d.g, to.before && to.before.parentElement === to.ln ? to.before : null); }
    const L = this.barLines();   // (the lines as the drop left them, before anything arranges the groups again)
    this.setToolLayout(L, { mine: true }); this.setStripGroups(SG, { mine: true }); this.setToolAt(A, { mine: true });
    // placed: its left on the grid as the mark showed it, whatever width it has there (a box of the strip, a group of a line)
    const el = to.strip ? [...this.root.querySelectorAll('.bar .axs .axb')].find(b => b.dataset.tg === n) : d.g;
    const box = to.strip ? this.root.querySelector('.bar .axs .axr') : d.g.parentElement;
    if (to.at != null && el && box) { const f = box.clientWidth - el.offsetWidth, at = f > 0 ? Math.min(1, Math.max(0, d.px / f)) : 0;
      if (Math.abs(at - A[n]) > 0.0005) { A[n] = at; this.setToolAt(A, { mine: true }); } }
    this.arrMark(); if (this.arrDlg) this.arrRender();
  },
  arrCancel() {
    const d = this.arrDrag; if (!d) return this; this.arrDrag = null; if (d.end) d.end();
    d.g.classList.remove('drag'); if (d.mark) d.mark.remove();
    try { d.tl.releasePointerCapture(d.id); } catch (e) { /* gone */ }
    return this;
  },
  // the keyboard's way: a dialog under the bar, a list per line, each row a tick (shown) and the group's label
  arrDialog() {
    if (!this.arranging) this.arrange(true);
    if (!this.arrDlg) {
      const el = this.arrDlg = document.createElement('div'); el.className = 'wv-arrd';
      el.setAttribute('role', 'dialog'); el.setAttribute('aria-modal', 'true'); el.setAttribute('aria-label', 'arrange the bar');
      this.root.querySelector('.bar').append(el);
      el.addEventListener('keydown', e => this.arrKey(e));
      el.addEventListener('click', e => { const b = e.target.closest('button[data-ar]'); if (b) { this.arrAct(b.dataset.ar, e); return; }
        const r = e.target.closest('[data-tg]'); if (r) { this.arrFocus = r.dataset.tg; this.arrToggle(r.dataset.tg); } });
    }
    this.arrRender();
    const f = this.arrDlg.querySelector('.ari[tabindex="0"]') || this.arrDlg.querySelector('.ari'); if (f) f.focus({ preventScroll: true });
    return this;
  },
  // the strip's groups in the dialog: left to right as it shows them
  arrStrip() {
    const SG = this.stripGroups(), o = this.stripOrder || [];
    return SG.slice().sort((a, b) => (o.indexOf(a) + 1 || 99) - (o.indexOf(b) + 1 || 99));
  },
  arrRender() {
    const el = this.arrDlg, H = new Set(toolNames(this.S.toolsHidden)), lines = [...this.barLines(), this.arrStrip()], si = lines.length - 1;
    const name = g => esc(g === 'assertions' ? 'SVA (assertions)' : g);
    const f = this.arrFocus && lines.flat().includes(this.arrFocus) ? this.arrFocus : lines.flat()[0];
    const row = g => `<div class="ari" role="checkbox" aria-checked="${!H.has(g)}" tabindex="${g === f ? 0 : -1}" data-tg="${esc(g)}"><span class="ck">${
      H.has(g) ? '' : '✓'}</span>${name(g)}</div>`;
    el.innerHTML = '<div class="arht">Arrange the bar</div><div class="arhint">↑ ↓ ← → a group · alt+↑ ↓ within its line · alt+← → to the line before ' +
      '/ after (past the last: a new one, then the strip over the time axis) · Space: shown or not · Esc: done</div>' +
      lines.map((l, i) => { const t = i === si ? 'over the time axis' : `line ${i + 1}`;
        return `<div class="arl" role="group" aria-label="${t}"><div class="arln">${t}</div>${l.map(row).join('') || '<div class="are">—</div>'}</div>`; })
        .join('') +
      '<div class="arlive" aria-live="polite"></div><div class="arb">' + ARR_PRESETS +
      '<button type="button" data-ar="reset">Reset</button><button type="button" data-ar="done">Done</button></div>';
    this.arrPlace();
    this.arrMark(); if (this.arrSaid) el.querySelector('.arlive').textContent = this.arrSaid;
  },
  // under the bar, not over it (again when the bar changes its height: barFit)
  arrPlace() {
    const el = this.arrDlg; if (!el) return;
    const b = this.root.querySelector('.bar').getBoundingClientRect();
    Object.assign(el.style, { left: Math.max(4, b.left + 10) + 'px', top: Math.min(Math.max(4, b.bottom + 4), innerHeight - 60) + 'px' });
  },
  arrToggle(g) {
    const H = new Set(toolNames(this.S.toolsHidden)), off = !H.delete(g); if (off) H.add(g);
    this.setToolsHidden([...H]); this.arrSaid = `${g} ${off ? 'hidden' : 'shown'}`; this.arrRender(); this.arrFocusRow();
  },
  arrFocusRow() {
    const r = this.arrDlg && [...this.arrDlg.querySelectorAll('.ari')].find(x => x.dataset.tg === this.arrFocus); if (r) r.focus({ preventScroll: true });
  },
  // the dialog's keys: ↑ ↓ ← → the focus; alt+↑ ↓ the group within its line, alt+← → to the line before / after (a new one past the
  // last); Space shows / hides it; Esc: the mode off, the focus on ⚙
  arrKey(e) {
    const k = e.key, row = e.target.closest && e.target.closest('.ari');
    if (k === 'Escape') { e.preventDefault(); e.stopPropagation(); this.arrange(false);
      const g = this.root.querySelector('.bar .pgear'); if (g) g.focus({ preventScroll: true }); return; }
    if (!row) return;
    const bl = this.barLines(), lines = [...bl, this.arrStrip()], si = lines.length - 1, g = row.dataset.tg;
    const li = lines.findIndex(l => l.includes(g)), gi = lines[li].indexOf(g);
    const say = t => { this.arrSaid = t; const lv = this.arrDlg.querySelector('.arlive'); if (lv) lv.textContent = t; };
    if (k === ' ' || k === 'Spacebar') { e.preventDefault(); this.arrFocus = g; this.arrToggle(g); return; }
    if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(k)) return;
    e.preventDefault(); e.stopPropagation();
    if (!e.altKey) {
      const flat = lines.flat(), i = flat.indexOf(g);
      const other = lines[li + (k === 'ArrowLeft' ? -1 : 1)] || [];
      const to = k === 'ArrowUp' ? flat[Math.max(0, i - 1)] : k === 'ArrowDown' ? flat[Math.min(flat.length - 1, i + 1)] :
        other[Math.min(gi, other.length - 1)] || g;
      this.arrFocus = to; for (const r of this.arrDlg.querySelectorAll('.ari')) r.tabIndex = r.dataset.tg === to ? 0 : -1;
      this.arrFocusRow(); return;
    }
    const L = bl.map(l => l.slice()), A = toolAts(this.S.toolAt), SG = this.stripGroups(), done = t => { this.arrFocus = g; this.arrSaid = t;
      this.arrRender(); this.arrFocusRow(); };
    if (li === si) {   // in the strip: ↑ ↓ trade places with the box beside it; ← to the last line, in its flow
      const S = lines[si];
      if (k === 'ArrowUp' || k === 'ArrowDown') { const j = gi + (k === 'ArrowUp' ? -1 : 1), o = S[j];
        if (!o) { say(`${g}: already at the ${j < 0 ? 'start' : 'end'} of the strip`); return; }
        const ag = this.toolAtOf(g), ao = this.toolAtOf(o); A[g] = ao; A[o] = ag; if (ag === ao) A[k === 'ArrowUp' ? g : o] = Math.max(0, ag - 0.001);
        this.setToolAt(A, { mine: true }); this.stripFit(); done(`${g} moved to place ${this.arrStrip().indexOf(g) + 1} of the strip`); return; }
      if (k === 'ArrowRight') { say(`${g}: already in the strip`); return; }
      SG.splice(SG.indexOf(g), 1); delete A[g]; if (!L.length) L.push([]); L[L.length - 1].push(g);
      this.setStripGroups(SG, { mine: true }); this.setToolAt(A, { mine: true }); this.setToolLayout(L, { mine: true });
      done(`${g} moved to line ${L.length}, out of the strip`); return;
    }
    if (k === 'ArrowUp' || k === 'ArrowDown') {
      const j = gi + (k === 'ArrowUp' ? -1 : 1);
      if (j < 0 || j >= L[li].length) { say(`${g}: already at the ${j < 0 ? 'start' : 'end'} of line ${li + 1}`); return; }
      [L[li][gi], L[li][j]] = [L[li][j], L[li][gi]];
    } else {
      const lj = li + (k === 'ArrowLeft' ? -1 : 1);
      if (lj < 0) { say(`${g}: already on the first line`); return; }
      if (lj >= L.length && (L.length >= TOOL_LINES_MAX || L[li].length === 1)) {   // no new line: into the strip
        L[li].splice(gi, 1); SG.push(g); delete A[g];
        this.setStripGroups(SG, { mine: true }); this.setToolAt(A, { mine: true }); this.setToolLayout(L.filter(l => l.length), { mine: true });
        done(`${g} moved to the strip over the time axis`); return;
      }
      L[li].splice(gi, 1); if (lj >= L.length) L.push([]);
      L[lj].splice(Math.min(gi, L[lj].length), 0, g);
    }
    const N = L.filter(l => l.length); this.setToolLayout(N, { mine: true });
    const nl = this.barLines(), nli = nl.findIndex(l => l.includes(g));
    done(`${g} moved to line ${nli + 1}, place ${nl[nli].indexOf(g) + 1}`);
  },
  // the strip over the time axis, its 🔒 open: a box's ⠿ dragged along its row (snapping to the grid, and to the left, the middle,
  // the right of the room and the names' edge within STRIP_SNAP px), put where it is let go and kept (toolAt). Its front edge past
  // the middle of another box of the row (a wide box at the end of the room cannot get its middle there): the order of the row
  // changes, the boxes it passed each go to the left edge of the place one over (the places of the row stay; the first passed
  // goes where this one started); Esc during it: back as it was
  stripDown(e, g) {
    if (e.button !== 0 || !this.stripOpen) return;
    const ax = g.closest('.axs'), room = ax.querySelector('.axr'), b = g.closest('.axb'), n = b.dataset.tg;
    e.preventDefault(); g.focus({ preventScroll: true }); try { g.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic event */ }
    const W = room.clientWidth, w = b.offsetWidth, free = Math.max(0, W - w), x0 = e.clientX, from = b.offsetLeft, top = b.offsetTop;
    const nx = this.namesEl.getBoundingClientRect().right - room.getBoundingClientRect().left;   // the names' edge in the room
    const snaps = [0, free / 2, free, nx, nx - w].filter(t => t >= 0 && t <= free);
    const row = [...room.querySelectorAll(':scope > .axb')].filter(o => !o.hidden && Math.abs(o.offsetTop - top) < 2)
      .map(o => ({ n: o.dataset.tg, left: o.offsetLeft, w: o.offsetWidth, mid: o.offsetLeft + o.offsetWidth / 2 })).sort((p, q) => p.left - q.left);
    const slots = row.map(o => o.left), others = row.filter(o => o.n !== n);   // (the places of the row: the lefts its boxes have now)
    const drag = this.stripDrag = { at: { [n]: this.toolAtOf(n) ?? 0 } }; ax.classList.add('drag');
    const ac = new AbortController(), own = { signal: ac.signal };
    const end = keep => {
      ac.abort(); ax.classList.remove('drag'); this.stripDrag = null;
      if (keep) { const A = toolAts(this.S.toolAt); for (const [k, v] of Object.entries(drag.at)) if (v != null) A[k] = stripAt(v); this.setToolAt(A); }
      else this.stripFit();
    };
    g.addEventListener('pointermove', ev => {
      let x = Math.min(free, Math.max(0, from + ev.clientX - x0));
      const s = snaps.find(t => Math.abs(x - t) <= STRIP_SNAP); x = s != null ? s : Math.min(free, Math.round(x / TOOL_GRID) * TOOL_GRID);
      drag.at[n] = free ? Math.round(x / free * 1000) / 1000 : 0;
      // the new order of the row: the boxes it passed move one place towards where it started, each to the place of that slot
      const passed = others.filter(o => (o.left < from ? x < o.mid : x + w > o.mid));
      const lefts = others.filter(o => o.left < from && !passed.includes(o)), rights = others.filter(o => o.left > from && !passed.includes(o));
      const pl = others.filter(o => o.left < from && passed.includes(o)), pr = others.filter(o => o.left > from && passed.includes(o));
      const now = [...lefts, ...pr, { n }, ...pl, ...rights];
      now.forEach((o, k) => { if (o.n === n) return; const f = Math.max(0, W - o.w);
        drag.at[o.n] = row[k].n === o.n ? null : f ? Math.min(1, Math.round(slots[k] / f * 1000) / 1000) : 0; });
      this.stripFit();
    }, own);
    g.addEventListener('pointerup', () => end(true), own); g.addEventListener('pointercancel', () => end(false), own);
    G.addEventListener('keydown', ev => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); end(false); } }, { capture: true, ...own });
  },
  // a box's ⠿ by the keys: ← → a twentieth of the way (shift: a quarter; the middle on the way a stop), Home End the ends
  stripKey(e, g) {
    const n = g.closest('.axb').dataset.tg, p = this.toolAtOf(n) ?? 0, d = e.shiftKey ? 0.25 : 0.05;
    let to = e.key === 'Home' ? 0 : e.key === 'End' ? 1 : e.key === 'ArrowLeft' ? p - d : e.key === 'ArrowRight' ? p + d : null;
    if (to == null) return;
    e.preventDefault(); e.stopPropagation();
    if (e.key.startsWith('Arrow') && ((p < 0.5 && to > 0.5) || (p > 0.5 && to < 0.5))) to = 0.5;
    this.placeTool(n, Math.round(to * 100) / 100);
  },
});
