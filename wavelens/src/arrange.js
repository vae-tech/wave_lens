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
      this.arrAc.abort(); this.barFit(); return this;
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
      // Esc: a drag cancelled, else the mode off (before the viewer's Esc: the window and the search stay)
      G.addEventListener('keydown', e => {
        if (e.key !== 'Escape' || !this.arranging || (this.arrDlg && this.arrDlg.contains(e.target)) || (!this.arrDrag && (this.pops || []).length)) return;
        e.preventDefault(); e.stopPropagation(); if (this.arrDrag) this.arrCancel(); else this.arrange(false);
      }, { capture: true, ...own });
      this.arrMark();
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
    if (k === 'full') { this.setToolLayout(null); this.setToolsCompact('auto'); }
    else if (k === 'compact') this.setToolsCompact(true);
    else if (k === 'mine') { const m = barKept().mine; if (m) { this.setToolLayout(m); this.setToolsCompact('auto'); } }
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
    this.setCursorStrip(null, { only: true }); this.setStripAt(null, { only: true });
    for (const w of VIEWS) if (w !== this && w.root.isConnected) w.barReload();
    this.toast('the bar as the settings have it'); return this;
  },
  // a drag by a label: pointer capture; past ARR_PX the group goes with the pointer, an accent bar where it lands
  arrDown(e) {
    const tl = e.button === 0 && e.target.closest('.tg > .tl'); if (!tl || this.arrDrag) return;
    e.preventDefault(); const g = tl.parentElement; tl.setPointerCapture(e.pointerId);
    const d = this.arrDrag = { g, tl, x: e.clientX, y: e.clientY, on: false, id: e.pointerId, from: [g.parentElement, g.nextElementSibling] };
    const move = ev => {
      if (!d.on && Math.hypot(ev.clientX - d.x, ev.clientY - d.y) < ARR_PX) return;
      if (!d.on) { d.on = true; g.classList.add('drag'); d.mark = document.createElement('span'); d.mark.className = 'arm'; }
      this.arrOver(ev.clientX, ev.clientY);
    };
    const up = () => { end(); if (d.on) this.arrDrop(); else this.arrDrag = null; };
    const end = () => { for (const [t, f] of [['pointermove', move], ['pointerup', up], ['pointercancel', cancel]]) tl.removeEventListener(t, f); };
    const cancel = () => { end(); this.arrCancel(); };
    d.end = end;
    tl.addEventListener('pointermove', move); tl.addEventListener('pointerup', up); tl.addEventListener('pointercancel', cancel);
  },
  // where the group would land at (x, y): the line under the pointer (or the new line), before the first group of its visual row
  // whose middle is right of x, else after the last one of that row
  arrOver(x, y) {
    const d = this.arrDrag, tools = this.root.querySelector('.bar .tools');
    const lines = [...tools.querySelectorAll(':scope > .tln')].filter(l => !l.hidden && l.getClientRects().length);
    const ln = lines.find(l => { const r = l.getBoundingClientRect(); return y >= r.top - 3 && y <= r.bottom + 3; }) ||
      (y < lines[0].getBoundingClientRect().top ? lines[0] : lines[lines.length - 1]);
    const gs = [...ln.children].filter(c => c.classList.contains('tg') && c !== d.g && c.getClientRects().length);
    const row = gs.filter(c => { const r = c.getBoundingClientRect(); return y >= r.top - 3 && y <= r.bottom + 3; });
    const pick = (row.length ? row : gs).find(c => { const r = c.getBoundingClientRect(); return x < r.left + r.width / 2; });
    const after = !pick && row.length ? row[row.length - 1].nextElementSibling : null;
    const before = pick || (after && after !== d.mark ? after : null);
    if (d.mark.parentElement !== ln || d.mark.nextElementSibling !== before) ln.insertBefore(d.mark, before);
    d.to = [ln, before];
  },
  arrDrop() {
    const d = this.arrDrag; this.arrDrag = null; d.g.classList.remove('drag');
    if (d.mark && d.mark.parentElement) { d.mark.parentElement.insertBefore(d.g, d.mark); d.mark.remove(); }
    this.setToolLayout(this.barLines(), { mine: true }); this.arrMark();
    if (this.arrDlg) this.arrRender();
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
  arrRender() {
    const el = this.arrDlg, H = new Set(toolNames(this.S.toolsHidden)), lines = this.barLines();
    const name = g => esc(g === 'assertions' ? 'SVA (assertions)' : g);
    const f = this.arrFocus && lines.flat().includes(this.arrFocus) ? this.arrFocus : lines[0][0];
    const row = g => `<div class="ari" role="checkbox" aria-checked="${!H.has(g)}" tabindex="${g === f ? 0 : -1}" data-tg="${esc(g)}"><span class="ck">${
      H.has(g) ? '' : '✓'}</span>${name(g)}</div>`;
    el.innerHTML = '<div class="arht">Arrange the bar</div><div class="arhint">↑ ↓ ← → a group · alt+↑ ↓ within its line · alt+← → to the line before ' +
      '/ after (past the last: a new one) · Space: shown or not · Esc: done</div>' +
      lines.map((l, i) => `<div class="arl" role="group" aria-label="line ${i + 1}"><div class="arln">line ${i + 1}</div>${l.map(row).join('')}</div>`)
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
    const lines = this.barLines(), g = row.dataset.tg, li = lines.findIndex(l => l.includes(g)), gi = lines[li].indexOf(g);
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
    const L = lines.map(l => l.slice());
    if (k === 'ArrowUp' || k === 'ArrowDown') {
      const j = gi + (k === 'ArrowUp' ? -1 : 1);
      if (j < 0 || j >= L[li].length) { say(`${g}: already at the ${j < 0 ? 'start' : 'end'} of line ${li + 1}`); return; }
      [L[li][gi], L[li][j]] = [L[li][j], L[li][gi]];
    } else {
      const lj = li + (k === 'ArrowLeft' ? -1 : 1);
      if (lj < 0) { say(`${g}: already on the first line`); return; }
      if (lj >= L.length && (L.length >= TOOL_LINES_MAX || L[li].length === 1)) { say(`${g}: already on the last line`); return; }
      L[li].splice(gi, 1); if (lj >= L.length) L.push([]);
      L[lj].splice(Math.min(gi, L[lj].length), 0, g);
    }
    const N = L.filter(l => l.length); this.setToolLayout(N, { mine: true }); this.arrFocus = g;
    const nl = this.barLines(), nli = nl.findIndex(l => l.includes(g));
    this.arrSaid = `${g} moved to line ${nli + 1}, place ${nl[nli].indexOf(g) + 1}`; this.arrRender(); this.arrFocusRow();
  },
  // the strip over the time axis, its 🔒 open: ⠿ dragged along the waves (snapping to the left, the middle, the right within
  // STRIP_SNAP px), put where it is let go and kept (setStripAt); Esc during it: back as it was
  stripDown(e) {
    if (e.button !== 0 || !this.stripOpen) return;
    const g = e.currentTarget, ax = g.closest('.axs'), w = ax.querySelector('.axw'), b = w.querySelector('.axb');
    e.preventDefault(); g.focus({ preventScroll: true }); try { g.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic event */ }
    const free = Math.max(0, w.clientWidth - b.offsetWidth), x0 = e.clientX, from = stripAt(this.S.cursorStripAt) * free;
    let p = stripAt(this.S.cursorStripAt); ax.classList.add('drag');
    const ac = new AbortController(), own = { signal: ac.signal };
    const end = keep => { ac.abort(); ax.classList.remove('drag'); if (keep) this.setStripAt(p); else this.stripShow(); };
    g.addEventListener('pointermove', ev => {
      let x = Math.min(free, Math.max(0, from + ev.clientX - x0)); const s = [0, free / 2, free].find(t => Math.abs(x - t) <= STRIP_SNAP);
      if (s != null) x = s;
      p = free ? x / free : 0; ax.style.setProperty('--axp', p);
    }, own);
    g.addEventListener('pointerup', () => end(true), own); g.addEventListener('pointercancel', () => end(false), own);
    G.addEventListener('keydown', ev => { if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); end(false); } }, { capture: true, ...own });
  },
  // ⠿ by the keys: ← → a twentieth of the way (shift: a quarter; the middle on the way a stop), Home End the ends
  stripKey(e) {
    const p = stripAt(this.S.cursorStripAt), d = e.shiftKey ? 0.25 : 0.05;
    let to = e.key === 'Home' ? 0 : e.key === 'End' ? 1 : e.key === 'ArrowLeft' ? p - d : e.key === 'ArrowRight' ? p + d : null;
    if (to == null) return;
    e.preventDefault(); e.stopPropagation();
    if (e.key.startsWith('Arrow') && ((p < 0.5 && to > 0.5) || (p > 0.5 && to < 0.5))) to = 0.5;
    this.setStripAt(Math.round(to * 100) / 100);
  },
});
