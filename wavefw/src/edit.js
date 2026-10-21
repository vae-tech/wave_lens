/* wavefw/src/edit.js — the viewer's commands (view.run: what its buttons, menus and lists do, by name), your groups and
   markers, the edits a page carries (tools/viewedit.py) and the live link to an agent (tools/wavemcp.py view_live). */

/* ---------------- commands ---------------- */
// view.run([{op: 'bookmark', t: '120ns', signal: 'PSEL', text: 'setup'}, …]) -> [{op, …result} | {op, error}]: one command
// after the other (a bad one says why and the rest still run), the names column, the lists and the waves drawn once at the
// end. tools/viewedit.py runs the same commands, by the same names and arguments, on a page's edits or a saved state
// (.view.json); tools/wavemcp.py sends them from an agent (view_edit). Times: model units (ps of timed waves, else
// cycles) or a text with a unit ("2.5us"); signals: a full path, a name, the end of a path ("u_regs.PSEL") or a *
// pattern, alone, in a list or as a text with commas. A name that matches nothing, or several signals where no pattern
// says so, is an error.
const CMDS = {};
// args: "name? other": the arguments (? optional), for the list (WaveFW.commands()) and the check of unknown ones
function command(name, args, doc, run) {
  CMDS[name] = { args, keys: args.split(/\s+/).filter(Boolean).map(k => k.replace(/\?$/, '')), doc, run };
}
const fail = msg => { throw new Error(msg); };
const READ_CMDS = new Set(['state', 'rows', 'picture']);   // they change nothing (no toast in a live page)
// a time of a command: a number (model units) or a text with a unit; untimed waves take cycles only
function cmdTime(v, x, what = 't') {
  if (!v.M.timed && typeof x === 'string' && /[a-zµ]/i.test(x)) fail(`${what}: these waves have no time, give cycles (a number)`);
  const t = typeof x === 'number' ? x : parseT(x);
  if (t == null || !isFinite(t)) fail(`${what}: "${x}" is not a time (a number in ${v.M.timed ? 'ps' : 'cycles'}, or "250ns")`);
  return t;
}
// rows by what a person or an agent writes (see above); o.groups: modules and your groups too; o.one: exactly one
function pickRows(v, spec, o = {}) {
  const list = prefixes(spec), M = v.M;
  if (!list.length) fail(`no ${o.groups ? 'signals or modules' : 'signals'} given`);
  // your groups as they are now (one made by a command before this one in the same run is there too)
  const pool = M.rows.filter(r => r.type === 'sig' && r.tr).concat(o.groups ? Object.values(M.groups).filter(g => g.full && !g.user) : [],
    o.groups ? v.ugRows().filter(r => r.type === 'group') : []);
  const out = [];
  for (const s of list) {
    let hit;
    if (s.includes('*')) { const rx = glob(s); hit = pool.filter(r => rx.test(r.full)); }
    else {
      hit = pool.filter(r => r.full === s);
      if (!hit.length) hit = pool.filter(r => r.name === s);
      if (!hit.length) hit = pool.filter(r => r.full.endsWith('.' + s));
      // the dump's path of a signal the page shows under a shorter one (wave_page: "tb.aclk" for "aclk"): the longest
      if (!hit.length) { const at = pool.filter(r => s.endsWith('.' + r.full)), n = Math.max(0, ...at.map(r => r.full.length));
        hit = at.filter(r => r.full.length === n); }
    }
    if (!hit.length) {
      const low = s.toLowerCase().replace(/\*/g, ''), near = low ? pool.filter(r => r.name.toLowerCase().includes(low)).slice(0, 5).map(r => r.full) : [];
      fail(`no ${o.groups ? 'signal or module' : 'signal'} "${s}"${near.length ? '; similar: ' + near.join(', ') : ''}`);
    }
    let fulls = [...new Set(hit.map(r => r.full))];
    if (!s.includes('*') && fulls.length > 1) {   // one net at several levels: the one nearest the top, when it is one (as wavemcp.py)
      const dots = f => f.split('.').length, top = Math.min(...fulls.map(dots)), near = fulls.filter(f => dots(f) === top);
      if (near.length === 1) { hit = hit.filter(r => r.full === near[0]); fulls = near; }
    }
    if (!s.includes('*') && fulls.length > 1) fail(`"${s}" is ambiguous: ${fulls.slice(0, 6).join(', ')}${fulls.length > 6 ? ` (+${fulls.length - 6})` : ''}` +
      ' — give more of its path, or a * pattern for all of them');
    for (const r of hit) if (!out.includes(r)) out.push(r);
  }
  if (o.one && out.length !== 1) fail(`one signal, not ${out.length} (${out.slice(0, 4).map(r => r.full).join(', ')})`);
  return out;
}
// the signals of rows: a module's below it, your group's in it, a signal itself
const sigsOf = (v, rows) => [...new Set(rows.flatMap(r => (r.type !== 'group' ? [r] : r.user
  ? (v.ugroups.find(g => '@' + g.name === r.full) || { signals: [] }).signals.map(f => v.M.rows.find(x => x.type === 'sig' && x.full === f)).filter(Boolean)
  : v.M.rows.filter(x => x.type === 'sig' && x.tr && x.anc.includes(r.id)))))];
const nums = v => v.bms.map(b => b.n).join(', ') || 'none';
// the id of an arrow or a marker: its number as listed (1, 2 …), not a name
const idOk = (x, what) => { if (x != null && x !== 'all' && !(Number.isInteger(+x) && +x > 0)) fail(`id: the number of the ${what} as listed (1, 2 …), ` +
  `not ${JSON.stringify(x)}; a new one: no id`); };

command('cursor', 't', 'the cursor to t; the window follows', (v, a) => { v.setCursor(cmdTime(v, a.t)); return { t: v.cursor }; });
command('cursor2', 't', 'the second cursor at t (null: none)', (v, a) => { v.setCursor2(a.t == null ? null : cmdTime(v, a.t)); return { t: v.cursor2 }; });
command('view', 'from? to? at? span?', 'the window: from … to, or span around at (default the cursor)', (v, a) => {
  const full = v.M.t1 - v.M.t0;
  if (a.from != null || a.to != null) {
    if (a.from == null || a.to == null) fail('view: from and to, or span (and at)');
    const p = cmdTime(v, a.from, 'from'), q = cmdTime(v, a.to, 'to');
    if (!(q > p)) fail('view: "to" is not after "from"');
    v.zoomTo(p, q);
  } else if (a.span != null || a.at != null) {
    const s = a.span == null ? v.span : cmdTime(v, a.span, 'span'), at = a.at == null ? v.cursor : cmdTime(v, a.at, 'at');
    if (!(s > 0)) fail('view: span is not a length');
    v.markView(); v.span = Math.min(Math.max(s, v.minSpan), full); v.t0 = v.clamp(at - v.span / 2); v.draw();
  } else fail('view: from and to, or span (and at)');
  return { from: v.t0, to: v.t0 + v.span };
});
command('fit', '', 'the whole time in the window', v => { v.markView(); v.fit(); return { from: v.t0, to: v.t0 + v.span }; });
command('range', 'from? to? signal?', 'the measured range (Δ, the edges or changes of the signal); from null: none', (v, a) => {
  if (a.from == null && a.to == null) { v.setRange(null); return { range: null }; }
  const p = cmdTime(v, a.from, 'from'), q = cmdTime(v, a.to, 'to'), row = a.signal ? pickRows(v, a.signal, { one: true })[0] : null;
  v.setRange(Math.max(Math.min(p, q), v.M.t0), Math.min(Math.max(p, q), v.M.t1), row);
  return { range: v.range, text: v.rangeText() };
});
command('bookmark', 'n? t? signal? text? color? lift? delete?', 'a numbered circle on a signal (none: the time axis) with its text: a new one ' +
  '(n free or left out, t default the cursor) or bookmark n changed; lift: above its signal in a lane; delete: n or "all" (their arrows go too)', (v, a) => {
  if (a.n != null && !(a.n === 'all' && a.delete) && !(Number.isInteger(+a.n) && +a.n > 0)) fail('n: a bookmark number (1, 2 …)');
  if (a.delete) {
    if (a.n === 'all') { v.bms = []; v.arrows = []; v.changed(true); return { deleted: 'all' }; }
    const b = v.bms.find(x => x.n === +a.n); if (!b) fail(`no bookmark ${a.n} (there are: ${nums(v)})`);
    v.bms = v.bms.filter(x => x !== b); v.arrows = v.arrows.filter(x => x.from !== b.n && x.to !== b.n); v.changed(true);
    return { n: b.n, deleted: true };
  }
  const t = a.t != null ? cmdTime(v, a.t) : null, sig = a.signal ? pickRows(v, a.signal, { one: true })[0].full : null;
  let b = a.n != null ? v.bms.find(x => x.n === +a.n) : null;
  if (!b) { b = { n: a.n != null ? +a.n : Math.max(0, ...v.bms.map(x => x.n)) + 1, t: v.cursor, signal: null, text: '', color: null, lift: false };
    v.bms.push(b); }
  if (t != null) b.t = t;
  if (a.signal !== undefined) b.signal = sig;
  if (a.text !== undefined) b.text = a.text == null ? '' : String(a.text);
  if (a.color !== undefined) b.color = a.color || null;
  if (a.lift !== undefined) b.lift = !!a.lift;
  b.lift = !!b.lift && !!b.signal;
  v.changed(true); return { n: b.n };
});
command('arrow', 'id? from? to? shape? head? line? color? label? delete?', 'an arrow from bookmark to bookmark with its label: a new one, or ' +
  'arrow id (1, 2 … as listed; or the one from → to) changed; delete', (v, a) => {
  const has = n => v.bms.some(b => b.n === n);
  if (a.id === 'all') fail('arrow: one at a time (bookmark n "all" deletes every arrow)');
  idOk(a.id, 'arrow');
  let i = a.id != null ? +a.id - 1 : a.from != null && a.to != null ? v.arrows.findIndex(x => x.from === +a.from && x.to === +a.to) : -1;
  if (a.id != null && !v.arrows[i]) fail(`no arrow ${a.id} (there are ${v.arrows.length})`);
  if (a.delete) {
    if (i < 0) fail(a.from != null && a.to != null ? `no arrow ${a.from} → ${a.to}` : 'arrow: delete takes id, or from and to');
    v.arrows.splice(i, 1); v.changed(true); return { id: i + 1, deleted: true };
  }
  for (const k of ['from', 'to']) if (a[k] != null && !has(+a[k])) fail(`${k}: no bookmark ${a[k]} (there are: ${nums(v)})`);
  for (const [k, set] of [['shape', AR_SHAPES], ['head', AR_HEADS], ['line', AR_LINES]]) if (a[k] != null && !(a[k] in set)) fail(`${k}: one of ` +
    Object.keys(set).map(x => JSON.stringify(x)).join(' '));
  const from = a.from != null ? +a.from : i >= 0 ? v.arrows[i].from : null, to = a.to != null ? +a.to : i >= 0 ? v.arrows[i].to : null;
  if (from == null || to == null) fail('arrow: from and to (bookmark numbers)');
  if (from === to) fail('arrow: from and to are one bookmark');
  if (i < 0) { v.arrows.push(arNorm([{ from, to }])[0]); i = v.arrows.length - 1; }
  const x = v.arrows[i]; x.from = from; x.to = to;
  for (const k of ['shape', 'head', 'line']) if (a[k] != null) x[k] = a[k];
  if (a.color !== undefined) x.color = a.color || null;
  if (a.label !== undefined) x.label = a.label == null ? '' : String(a.label);
  v.changed(true); return { id: i + 1 };
});
command('marker', 'id? t? label? color? delete?', 'a marker: a dashed line across every row with its label at the top: a new one (t default ' +
  'the cursor), or marker id (1, 2 … as listed) changed; delete: id or "all"', (v, a) => {
  idOk(a.id, 'marker');
  if (a.id != null && a.id !== 'all' && !v.umarks[+a.id - 1]) fail(`no marker ${a.id} (there are ${v.umarks.length})`);
  if (a.delete) {
    if (a.id == null) fail('marker: delete takes id or "all"');
    if (a.id === 'all') v.umarks = []; else v.umarks.splice(+a.id - 1, 1);
    v.setMarks(); return { id: a.id, deleted: true };
  }
  const t = a.t != null ? cmdTime(v, a.t) : null;
  let m = a.id != null ? v.umarks[+a.id - 1] : null;
  if (!m) { m = { t: v.cursor, label: '', color: null }; v.umarks.push(m); }
  if (t != null) m.t = t;
  if (a.label !== undefined) m.label = a.label == null ? '' : String(a.label);
  if (a.color !== undefined) m.color = a.color || null;
  v.setMarks(); return { id: v.umarks.indexOf(m) + 1 };
});
command('group', 'name signals? add? remove? color? rename? delete? go?', 'your group of signals, a folder at the top of the names (the signals ' +
  'stay where they are too): made or changed — signals: its signals in this order, add, remove, color, rename; delete; go: opened, shown, its first ' +
  'signal selected (ctrl+G)', (v, a) => {
  const name = String(a.name ?? '').trim(); if (!name) fail('group: a name');
  let g = v.ugroups.find(x => x.name === name);
  if (a.delete) { if (!g) fail(`no group "${name}"`); v.ugroups = v.ugroups.filter(x => x !== g); v.setGroups(); return { name, deleted: true }; }
  const fulls = spec => sigsOf(v, pickRows(v, spec, { groups: true })).map(r => r.full);
  const set = a.signals != null ? fulls(a.signals) : null, add = a.add != null ? fulls(a.add) : [], rm = a.remove != null ? fulls(a.remove) : [];
  const to = a.rename != null ? String(a.rename).trim() : null;
  if (to === '' || (to && to !== name && v.ugroups.some(x => x.name === to))) fail(`rename: ${to ? `a group "${to}" is there` : 'a name'}`);
  if (!g) { g = { name, signals: [], color: null }; v.ugroups.push(g); }
  if (set) g.signals = set;
  for (const f of add) if (!g.signals.includes(f)) g.signals.push(f);
  if (rm.length) g.signals = g.signals.filter(f => !rm.includes(f));
  if (a.color !== undefined) g.color = a.color || null;
  if (to) g.name = to;
  v.setGroups();
  if (a.go) { v.held.names = false; v.renderNamesNow(); v.goGroup(g.name); }
  return { name: g.name, signals: g.signals.length };
});
command('highlight', 'add? remove? set? clear?', 'signals and modules in front, each in its colour, the rest dimmed: add, remove, set (the ' +
  'list), clear', (v, a) => {
  let list = a.clear ? [] : [...v.picks.keys()];
  if (a.set !== undefined) list = a.set == null ? [] : pickRows(v, a.set, { groups: true });
  for (const r of a.add != null ? pickRows(v, a.add, { groups: true }) : []) if (!list.includes(r)) list.push(r);
  if (a.remove != null) { const rm = pickRows(v, a.remove, { groups: true }); list = list.filter(r => !rm.includes(r)); }
  v.picks = new Map(list.map((r, i) => [r, i % HL_N])); v.renderNames(); v.draw();
  return { highlighted: list.map(r => r.full) };
});
command('paint', 'signals? color? clear?', 'signals (a module: its signals) in a colour, trace, outline and name; color null: their own again; ' +
  'clear: every one', (v, a) => {
  if (a.signals == null && !a.clear) fail('paint: signals and a color, or clear');
  if (a.clear) v.painted.clear();
  const rows = a.signals != null ? sigsOf(v, pickRows(v, a.signals, { groups: true })) : [];
  for (const r of rows) if (a.color) v.painted.set(r.full, String(a.color)); else v.painted.delete(r.full);
  v.savePaint(); v.renderNames(); v.draw(); return { painted: rows.length };
});
command('select', 'signal? signals?', 'the selected signal (edge search, new bookmarks; null: none), or several (the right button and Paint ' +
  'take them all)', (v, a) => {
  if (a.signals != null) { const rows = pickRows(v, a.signals); v.select(rows[rows.length - 1]); v.selRun = new Set(rows); v.selAnchor = rows[0]; }
  else v.select(a.signal ? pickRows(v, a.signal, { one: true })[0] : null);
  return { select: v.sel ? v.sel.full : null };
});
command('hide', 'signals', 'signals, modules or your groups out of the view', (v, a) => { v.hide(pickRows(v, a.signals, { groups: true }));
  return { hidden: v.hiddenRows.size }; });
command('show', 'signals?', 'hidden ones back (none given: every one)', (v, a) => {
  v.unhide(a.signals == null ? undefined : pickRows(v, a.signals, { groups: true }).map(r => r.full)); return { hidden: v.hiddenRows.size };
});
for (const [name, on] of [['fold', true], ['unfold', false]]) {
  command(name, 'groups? all?', `modules (and your groups) ${on ? 'folded' : 'opened'}; all: every one`, (v, a) => {
    if (a.all) v.collapsed = on ? new Set(Object.keys(v.M.groups).map(Number)) : new Set();
    else {
      const gs = pickRows(v, a.groups, { groups: true }).filter(r => r.type === 'group');
      if (!gs.length) fail(`${name}: no module in ${JSON.stringify(a.groups)}`);
      gs.forEach(g => (on ? v.collapsed.add(g.id) : v.collapsed.delete(g.id)));
    }
    v.collapsed = new Set([...v.collapsed].sort((x, y) => x - y));   // in the model's order, as a state gives it back
    if (v.sel && v.sel.anc.some(id => v.collapsed.has(id))) v.sel = null;
    v.foldTouched = true; v.renderNames(); v.draw(); return { folded: v.collapsed.size };
  });
}
command('radix', 'signals radix', `the radix of buses: ${RADIX.join(' ')}, q8 / sq15 (fixed point); null: the page's`, (v, a) => {
  if (a.radix != null && !isRadix(a.radix)) fail(`radix: one of ${RADIX.join(' ')}, q<F> or sq<F> (fixed point), or null`);
  const rows = pickRows(v, a.signals);
  rows.forEach(r => v.setRadix(r, a.radix ?? null, true)); v.saveRows(); v.renderNames(); v.draw(); return { signals: rows.length };
});
command('analog', 'signals rows', 'buses drawn as a step plot that many rows high (true: 3, false: a bus again, null: as the page has it)', (v, a) => {
  const rows = pickRows(v, a.signals), n = a.rows === true ? 3 : a.rows;
  const bad = rows.filter(r => (r.width || 1) < 2 && r.kind !== 'real'); if (bad.length && n) fail(`not a bus: ${bad.map(r => r.full).join(', ')}`);
  if (n != null && n !== false && !(Number.isInteger(n) && n >= 0)) fail('rows: a number of rows, true, false or null');
  rows.forEach(r => v.setAnalog(r, n == null ? null : n || false, true)); v.saveRows(); v.renderNames(); v.draw(); return { signals: rows.length };
});
command('sort', 'dir ignore?', 'the order of the names: none, asc, desc; ignore: prefixes left out when comparing ("i_,o_")', (v, a) => {
  if (!SORTS.includes(a.dir)) fail(`dir: one of ${SORTS.join(' ')}`);
  v.setSort(a.dir, a.ignore ?? undefined); return { sort: v.sort, ignore: v.sortIgnore };
});
command('style', 'name', `the edge style: ${Object.keys(EDGES).join(' ')} (null: the settings')`, (v, a) => {
  if (a.name != null && !EDGES[a.name]) fail(`name: one of ${Object.keys(EDGES).join(' ')}`);
  v.setStyle(a.name); return { style: v.S.style };
});
command('layout', 'scroll? height? tools?', 'where the rows scroll: window (in the viewer, height: "80vh", 600) or page (with the page, the ' +
  'bar sticking to the top); tools: fold or open (the bar\'s tools to its title line)', (v, a) => {
  if (a.scroll != null && !['window', 'page'].includes(a.scroll)) fail('scroll: window or page');
  if (a.tools != null && !['fold', 'open'].includes(a.tools)) fail('tools: fold or open');
  const hOk = h => (typeof h === 'number' ? h > 0 : /^\s*[\d.]+\s*(px|vh|em|rem|%)?\s*$/.test(h));
  if (a.height != null && !hOk(a.height)) fail('height: 600 (px) or "80vh"');
  if (a.scroll != null || a.height != null) v.setScroll(a.scroll || 'window', a.height ?? undefined);
  if (a.tools != null) v.setTools(a.tools === 'fold');
  return { scroll: v.S.maxHeight != null && v.S.maxHeight !== '' ? 'window' : 'page', height: v.S.maxHeight || null, tools: v.S.toolsFolded ? 'fold' : 'open' };
});
command('find', 'query case? word? regex? highlight? open?', 'the find field: rows by a fuzzy query ("" ends it); its options as the bar\'s buttons',
  (v, a) => {
    for (const [k, own] of [['case', 'findCase'], ['word', 'findWord'], ['regex', 'findRegex']]) if (a[k] != null) { v[own] = !!a[k];
      v.root.querySelector(`button[data-act=${FIND_OPTS.find(o => o[1] === own)[0]}]`)?.setAttribute('aria-pressed', v[own]); }
    for (const [k, own, act] of [['highlight', 'findHl', 'fhl'], ['open', 'findOpen', 'fopen']]) if (a[k] != null) { v[own] = !!a[k];
      v.root.querySelector(`button[data-act=${act}]`)?.setAttribute('aria-pressed', v[own]); }
    if (v.qEl) v.qEl.value = String(a.query ?? '');
    v.find(String(a.query ?? '')); return { found: [...v.found.keys()].map(r => r.full || r.name).slice(0, 50), count: v.found.size };
  });
command('gaps', 'on? idle? keep? signals? clock? aux? only? count? reset?', 'the gaps of the picture and WaveDrom (the menu\'s Gaps): on, idle ' +
  'and keep (cycles or a time), the signals they follow, the clock they count, aux (changes counted), only, count (clock edges off); reset', (v, a) => {
  if (a.reset) v.setGaps(null);
  const map = { on: 'gaps', idle: 'gapIdle', keep: 'gapKeep', signals: 'gapSignals', clock: 'gapClock', aux: 'gapAux', only: 'gapOnly', count: 'gapCount' };
  const o = Object.fromEntries(Object.entries(map).filter(([k]) => a[k] !== undefined).map(([k, g]) => [g, a[k]]));
  if (Object.keys(o).length) v.setGaps(o);
  return { gaps: v.gapOpt() };
});
command('edge', 'dir? kind? value? signal?', 'the cursor to the next (dir 1) or previous (-1) edge of the selected signal (signal: that one, ' +
  `selected), kind: ${Object.keys(EDGE_KINDS).join(' ')}; value: the value to become`, (v, a) => {
  if (a.kind != null && !EDGE_KINDS[a.kind]) fail(`kind: one of ${Object.keys(EDGE_KINDS).join(' ')}`);
  if (a.signal) v.select(pickRows(v, a.signal, { one: true })[0]);
  const at = v.cursor; v.edge(a.dir === -1 || a.dir === '-1' ? -1 : 1, a.kind || (a.value != null ? 'value' : v.edgeKind), a.value ?? null);
  return { t: v.cursor, moved: v.cursor !== at };
});
command('reset', '', 'what Esc does: no search, highlight, selection, range or second cursor', v => { v.reset(); return {}; });
command('state', '', 'the viewer\'s state (what Save writes)', v => ({ state: v.state() }));
command('set_state', 'state', 'a state back (what Load… does); every key it has replaces this viewer\'s', async (v, a) =>
  ({ missing: await v.setState(a.state) }));
command('rows', 'pattern? limit? offset?', 'the signals and modules of the page in display order: [full path, width | "module" | "group"], ' +
  'hidden and folded ones too', (v, a) => {
  const rx = a.pattern ? (String(a.pattern).includes('*') ? glob(String(a.pattern)) : null) : null, low = String(a.pattern || '').toLowerCase();
  const all = v.allRows().concat(v.M.rows.filter(r => r.full && v.hiddenRows.has(r.full)))
    .filter(r => (r.type === 'sig' && r.tr && !r.ug) || (r.type === 'group' && r.full))
    .filter(r => !a.pattern || (rx ? rx.test(r.full) : r.full.toLowerCase().includes(low)));
  const off = Math.max(0, +a.offset || 0), n = Math.max(1, +a.limit || 200), page = all.slice(off, off + n);
  return { total: all.length, rows: page.map(r => [r.full, r.type === 'group' ? (r.user ? 'group' : 'module') : r.width || 1]),
    ...(off + n < all.length ? { next_offset: off + n } : {}) };
});
command('picture', 'format? from? to? rows?', 'the waves as a picture: png (base64), svg or wavedrom (WaveJSON); rows: screen (default), all, ' +
  'picked (highlighted) or signals', async (v, a) => {
  const f = a.format || 'png', o = {};
  if (a.from != null) o.from = cmdTime(v, a.from, 'from');
  if (a.to != null) o.to = cmdTime(v, a.to, 'to');
  if (a.rows != null) o.rows = ['screen', 'all', 'picked'].includes(a.rows) ? (a.rows === 'screen' ? undefined : a.rows) : sigsOf(v, pickRows(v, a.rows,
    { groups: true })).map(r => v.rowsL.find(x => x === r) || r);
  if (f === 'wavedrom') { const wavedrom = v.toWaveDrom(o.from, o.to, Array.isArray(o.rows) ? o.rows : null);   // cut: the first cycles only
    return v.wdCut ? { wavedrom, cut: { cycles: v.wdCut.cells, to: v.wdCut.to } } : { wavedrom }; }
  if (f === 'svg') return { svg: v.toSVG(o) };
  if (f !== 'png') fail('format: png, svg or wavedrom');
  const bl = await v.toPNG(o, 1), buf = new Uint8Array(await bl.arrayBuffer());
  let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return { png: btoa(bin), bytes: buf.length };
});

/* ---------------- your groups and markers, the batch ---------------- */
Object.assign(WaveView.prototype, {
  // the commands (see CMDS): one or a list -> a Promise of their results, in order
  async run(ops) {
    const list = Array.isArray(ops) ? ops : [ops], out = [], own = !this.held;
    if (own) this.held = {};
    try {
      for (const o of list) {
        const c = o && typeof o === 'object' && CMDS[o.op];
        try {
          if (!c) fail(o && o.op ? `no command "${o.op}"; the commands: ${Object.keys(CMDS).join(' ')}` : 'a command is {op: name, …arguments}');
          const bad = Object.keys(o).filter(k => k !== 'op' && !c.keys.includes(k));
          if (bad.length) fail(`${o.op} takes ${c.args || 'no arguments'}, not ${bad.join(', ')}`);
          out.push(Object.assign({ op: o.op }, await c.run(this, o)));
        } catch (e) { out.push({ op: o && o.op, error: e.message }); }
      }
    } finally {
      if (own) { const h = this.held; this.held = null; if (h.names) this.renderNames(); if (h.notes) this.renderNotes(); if (h.draw || h.names) this.draw(); }
    }
    this.root.dispatchEvent(new CustomEvent('wavefw:edit', { detail: { ops: list, results: out } }));
    return out;
  },
  // your markers (the marker command, the menu's Marker here, the Markers list) over the page's own: drawn, kept in this browser
  setMarks() { this.markers = this.pageMarks.concat(this.umarks); this.saveBookmarks(); this.renderNotes(); this.draw(); return this; },
  // your groups: a folder per group at the top of the names, its signals (the model's rows under them, live: radix,
  // values) in your order; the same objects while the group stays (its folding, a highlight)
  setGroups() { this.ugMemo = null; this.saveRows(); this.renderNames(); this.draw(); return this; },
  ugRows() {
    if (this.ugMemo) return this.ugMemo;
    const by = new Map(this.M.rows.filter(r => r.type === 'sig' && r.tr).map(r => [r.full, r])), cache = this.ugCache = this.ugCache || new Map(), out = [];
    for (const g of this.ugroups) {
      let c = cache.get(g);
      if (!c) { c = { row: { type: 'group', id: ++XID, user: true }, kids: new Map() }; cache.set(g, c); }
      const gr = c.row, kids = g.signals.map(f => by.get(f)).filter(Boolean);
      Object.assign(gr, { name: g.name, path: '@' + g.name, full: '@' + g.name, title: `your group: ${kids.length} signal${kids.length === 1 ? '' : 's'}` });
      if (g.color) gr.stroke = g.color; else delete gr.stroke;
      out.push(gr);
      for (const s of kids) {
        let k = c.kids.get(s);
        if (!k) { k = Object.create(s); k.orig = s; k.same = true; k.ug = gr; c.kids.set(s, k); }   // reads through to the signal
        k.anc = [gr.id]; k.depth = 1;
        if (g.color) k.stroke = g.color; else delete k.stroke;
        out.push(k);
      }
    }
    for (const g of cache.keys()) if (!this.ugroups.includes(g)) cache.delete(g);
    return (this.ugMemo = out);
  },
  // the right button's "Add to a group": a group by its name (made when missing) gets these signals
  toGroup(name, rows) { return this.run({ op: 'group', name, add: rows.map(r => (r.orig || r).full) }); },
});

/* ---------------- the edits a page carries (tools/viewedit.py; wavemcp.py view_edit on a page that is not live) ---------------- */
// <script type="application/json" id="wavefw-edits">{"views": {"<key>": {"rev": "…", "state": {…}}}}</script>: per viewer
// (its key: the data-wave name under WAVES, else its id or title) a state of the keys the edits touched ("folds": the
// groups they folded or opened). What this browser keeps of a viewer (bookmarks, arrows, markers, groups, colours,
// radix, hidden rows, the edge style, the gaps) a revision replaces once: the browser keeps the revision it applied
// (wavefw.edits:<page>), so what you change here afterwards stays until a newer one (Save keeps yours in a file). The
// rest (cursor, window, highlight, selection, folding, order, search), which a page opened again starts from anyway,
// is applied every time, as the page's own settings are.
const KEPT = ['bookmarks', 'arrows', 'markers', 'groups', 'paint', 'radix', 'analog', 'hidden'], KEPT_CFG = ['style', 'maxHeight', 'toolsFolded', ...GAP_KEYS];
let EDITS;
function pageEdits() {
  if (EDITS !== undefined) return EDITS;
  const el = typeof document !== 'undefined' && document.getElementById('wavefw-edits');
  try { EDITS = el ? JSON.parse(el.textContent).views || {} : null; }
  catch (e) { console.error('wavefw: the page\'s edits are not JSON: ' + e.message); EDITS = null; }
  return EDITS;
}
Object.assign(WaveView.prototype, {
  editKey() {
    const ref = this.root.dataset.wave;
    return ref ? ref.replace(/^WAVES\[(".*")\]$/, (m, s) => JSON.parse(s)).replace(/^WAVES\./, '') : this.opts.key || this.root.id || this.M.title || '';
  },
  async applyEdits() {
    const E = pageEdits(), e = E && E[this.editKey()], key = 'wavefw.edits:' + this.storeId;
    if (!e || !e.state) return null;
    let st = e.state, seen = false;
    try { seen = localStorage.getItem(key) === String(e.rev); } catch (err) { /* no storage: all of it every time */ }
    if (seen) {   // applied before: only what this browser does not keep
      st = Object.fromEntries(Object.entries(st).filter(([k]) => !KEPT.includes(k)));
      if (st.config) st.config = Object.fromEntries(Object.entries(st.config).filter(([k]) => !KEPT_CFG.includes(k)));
      if (!Object.keys(st).length) return null;
    }
    try {
      const miss = await this.setState(Object.assign({ wavefw: 'state', version: STATE_VERSION }, st));
      const c = st.cursor;   // a cursor the edits put outside the window: the window follows (as the cursor command)
      if (c != null && st.from == null && (this.cursor < this.t0 || this.cursor > this.t0 + this.span)) {
        this.t0 = this.clamp(this.cursor - this.span / 2); this.draw(); }
      try { localStorage.setItem(key, String(e.rev)); } catch (err) { /* private mode */ }
      if (!seen) this.toast(`the page's edits applied (${String(e.rev).split('@')[0]})` +
        (miss.length ? ` · not in these waves: ${miss.slice(0, 3).join(', ')}` : ''));
      return miss;
    } catch (err) { this.toast('the page\'s edits: ' + err.message); return null; }
  },
});

/* ---------------- live: this page's viewers driven by an agent (tools/wavemcp.py view_live) ---------------- */
// WaveFW.live('8742:<token>' or 'http://127.0.0.1:8742/?token=…'); a page that carries the link (view_live writes
// <script type="application/json" id="wavefw-live">{"port", "token"}</script>) or is opened with #wavefw-live=8742:<token>
// connects by itself. The page says which viewers it has (POST /hello), takes commands as server-sent events (GET
// /events: {rid, view, ops}) and answers each with the results of view.run (POST /reply). Plain-text bodies (no CORS
// preflight), the token in every request; the server listens on 127.0.0.1 only. No agent there: five tries, then the
// button in the bar (○ live) tries again. WaveFW.live(null): off.
const LIVE = { es: null, base: '', q: '', on: false, url: null, fails: 0 };
function liveUrl(s) {
  const m = /^(\d+):(.+)$/.exec(String(s).trim());
  const u = new URL(m ? `http://127.0.0.1:${m[1]}/?token=${encodeURIComponent(m[2])}` : String(s).trim());
  if (!/^(127\.0\.0\.1|localhost|\[::1\])$/.test(u.hostname)) fail('live: the agent\'s server is on this machine (127.0.0.1)');
  return u;
}
function livePost(path, body) {
  return fetch(`${LIVE.base}/${path}?${LIVE.q}`, { method: 'POST', body: JSON.stringify(body) }).catch(() => null);
}
function liveViews() {
  return [...VIEWS].filter(v => v.root.isConnected).map(v => ({ key: v.editKey(), title: v.opts.title || v.M.title || '', timed: v.M.timed,
    t0: v.M.t0, t1: v.M.t1 }));
}
let liveT = 0;
function liveHello() {   // the viewers again (a lazy one built, a dump opened): once per frame
  if (!LIVE.es || liveT) return;
  liveT = setTimeout(() => { liveT = 0; if (LIVE.es) livePost('hello', { path: decodeURIComponent(location.pathname), url: location.href.split('#')[0],
    title: document.title, views: liveViews() }); }, 0);
}
function liveShow() {
  for (const v of VIEWS) {
    const b = v.root.querySelector('button[data-act=live]'); if (!b) continue;
    b.hidden = !LIVE.url; b.classList.toggle('on', LIVE.on);
    b.textContent = LIVE.on ? '● live' : LIVE.es ? '○ live…' : '○ live';
    b.title = LIVE.on ? `Driven by an agent (${LIVE.base}); click: disconnect` : LIVE.es ? `Waiting for the agent at ${LIVE.base}; click: give up` :
      `No agent at ${LIVE.base} (tools/wavemcp.py view_live); click: try again`;
  }
}
function liveClick() { if (LIVE.es) live(null); else if (LIVE.url) live(LIVE.url); }
function live(url) {
  if (LIVE.es) { LIVE.es.close(); LIVE.es = null; LIVE.on = false; }
  LIVE.url = url || null; LIVE.fails = 0;
  if (url) {
    const u = liveUrl(url), cid = Math.random().toString(36).slice(2, 10);
    LIVE.base = u.origin; LIVE.q = `token=${encodeURIComponent(u.searchParams.get('token') || '')}&cid=${cid}`;
    const es = LIVE.es = new EventSource(`${LIVE.base}/events?${LIVE.q}`);
    es.addEventListener('open', () => { LIVE.on = true; LIVE.fails = 0; liveHello(); liveShow(); });
    es.addEventListener('error', () => { LIVE.on = false;
      if (++LIVE.fails >= 5 && LIVE.es === es) { es.close(); LIVE.es = null; }   // no agent there: the button tries again
      liveShow(); });
    if (!LIVE.bye) {   // the page leaves (closed, reloaded): the server forgets it at once
      LIVE.bye = true; G.addEventListener('pagehide', () => { if (LIVE.es && navigator.sendBeacon) navigator.sendBeacon(`${LIVE.base}/bye?${LIVE.q}`, '{}'); });
    }
    es.addEventListener('cmd', async e => {
      let m = {}, results;
      try {
        m = JSON.parse(e.data);
        const vs = [...VIEWS].filter(v => v.root.isConnected);
        const v = m.view != null && m.view !== '' ? vs.find(x => x.editKey() === m.view) : vs.length === 1 ? vs[0] : null;
        if (!v) fail(m.view ? `no viewer "${m.view}" here (${vs.map(x => x.editKey()).join(', ')})` : `${vs.length} viewers here: give view (${vs.map(x =>
          x.editKey()).join(', ')})`);
        results = await v.run(m.ops || []);
        const n = (m.ops || []).filter(o => o && !READ_CMDS.has(o.op)).length;
        if (n) v.toast(`the agent: ${n} change${n === 1 ? '' : 's'}`);
      } catch (err) { results = { error: err.message }; }
      livePost('reply', { rid: m.rid, results });
    });
  }
  liveShow();
  return url ? LIVE.base : null;
}
