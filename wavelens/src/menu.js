/* wavelens/src/menu.js — the menus of a viewer: the right button's, the tools', your groups', your markers', a text asked for. */

Object.assign(WaveView.prototype, {
  // the right button's menu at (cx, cy) on the screen: the range (zoom, bookmarks at its ends, copy Δ), the picture (copy,
  // PNG, SVG), the signal under the pointer (colour, highlight, copy its path); Esc, a click elsewhere or a choice closes it
  // mk: your marker whose text was clicked (its text, colour); on: the Δ arrow clicked (dl), the line between the rows (line)
  menu(cx, cy, row, at = this.cursor, mk = null, on = {}) {
    this.closeMenu(); this.menuAt = [cx, cy];   // where it was opened: a text asked there after (Bookmark here, Marker here)
    const r = this.range, sig = row && row.type === 'sig' && row.tr ? row : null, grp = row && row.type === 'group' &&
      this.M.groups[row.id] === row ? row : null, it = row && (sig || grp);
    const up = sig && sig.anc.length ? sig.anc[sig.anc.length - 1] : null, nh = this.hiddenRows.size, ng = Object.keys(this.M.groups).length;
    // a row of your groups (its place there) or a header of one (its place among yours): Move up / down, to the top / bottom
    const ugh = row && row.user ? row : null, mine = sig && sig.ug ? sig : null, ugOf = n => this.ugroups.find(g => g.name === n);
    const mvAt = ugh ? [this.ugroups.indexOf(ugOf(ugh.name)), this.ugroups.length] : mine ? [ugOf(mine.ug.name).signals.indexOf(mine.orig.full),
      ugOf(mine.ug.name).signals.length] : null;
    // a highlighted row clicked: colour, radix and hide go to every highlighted one (a highlighted module: its signals)
    const picked = r => this.picks.has(r) || r.anc.some(id => this.picks.has(this.M.groups[id]));
    // or a row of the shift+click run: every row of the run
    const run = !!sig && this.selRun.size > 1 && this.selRun.has(sig);
    const many = run || (it && (this.picks.has(it) || sig && picked(sig)) && this.picks.size > 1);
    const sigs = run ? [...this.selRun] : many ? this.sigPool().filter(r => r.type === 'sig' && r.tr && picked(r) && this.shown(r)) : sig ? [sig] : [];
    const vecs = sigs.map(r => r.orig || r).filter(isVec);   // Bits: the buses bit by bit
    // Duplicate: every signal but a bit, a plugin's copy; a copy's own row goes
    const dupable = sigs.filter(r => rowBase(r).bit == null && !rowBase(r).same), copies = [...new Set(sigs.map(r => r.orig || r).filter(r => r.dupOf))];
    const buses = sigs.filter(r => r.width > 1 && r.tr.some(o => o.raw != null)),
      rows = run ? sigs : many ? [...this.picks.keys()].filter(r => r.full && (r.type === 'sig' || this.M.groups[r.id] === r) && this.shown(r)) : [it];
    const acc = getComputedStyle(this.root).getPropertyValue('--wave-paint').trim(), col = sig && this.painted.get(sig.full) ||
      (/^#[0-9a-f]{6}$/i.test(acc) ? acc : '#d6336c');
    const of = many ? `the ${sigs.length} ${run ? 'selected' : 'highlighted'}` : sig ? sig.name : '', rx = sig &&
      (sig.radix0 !== undefined ? sig.radix0 || this.S.radix : sig.radix || this.S.radix);
    // a fixed-point radix: its kind and fraction bits
    const q0 = /^(s?q)(\d+)$/.exec((sig && this.radixes.get(sig.full)) || ''), qk = q0 ? q0[1] : '', qf = q0 ? +q0[2] : 8;
    // the picture and WaveDrom: the selected run, the highlighted rows, else the screen's
    const ex = this.exportRows(), np = ex ? ex.length : 0, pic = ex ? { rows: ex } : {};
    // the gaps of the picture and WaveDrom (idle stretches left out): on / off, how long idle, how much kept; how many now
    const gp = this.gapOpt(), [ga, gb] = r || [this.t0, this.t0 + this.span], gaps = () => this.cutsOf(ga, gb, pic.rows || this.screenRows()).length - 1;
    const gn = () => (this.gapOpt().gaps ? `Gaps: ${gaps()}` : 'Gaps'), nref = this.gapRefSet().size;
    const gby = gp.gapBy ? gp.gapBy.length : 0;   // the expressions the waves are cut to
    const bases = sigs.map(rowBase), sig0 = sig && rowBase(sig);   // gaps and cycles go by the signal: a copy is its signal there
    const gref = sigs.length && bases.every(x => this.gapRefSet().has(x));   // the signals clicked: the gaps follow them already
    const gck = this.gapClockRow(), isGck = !!sig && sig0 === gck;   // the clock the gaps count cycles of
    const co = this.cycOpt(), cd = this.cycData(), cda = this.cycData(true);
    const isCyc = !!sig && co.cycles && (co.cycleClock === sig0.full || co.cycleClock === (sig.src && sig.src.abs));   // the cycles
    const gaux = sigs.length && bases.every(x => this.gapRows().aux.has(x)), naux = this.gapRows().aux.size;   // the signals counted in the gaps
    // one role per signal: the gaps follow it (gapSignals), count its changes (gapAux) or count its cycles (gapClock)
    const role = (key, on) => { const fs = bases.map(x => x.full).filter(Boolean), g = this.gapOpt(), o = { gaps: true };
      for (const k of ['gapSignals', 'gapAux']) o[k] = g[k].filter(x => !fs.includes(x));
      if (key === 'gapClock') o.gapClock = on ? sig0.full : null; else { if (on) o[key].push(...fs); if (fs.includes(g.gapClock)) o.gapClock = null; }
      if (key === 'gapAux' && on && g.gapCount === 'off') o.gapCount = 'clock';   // counted: its counts in the picture
      this.setGaps(o); };
    const b = (m, label) => { const k = (TIPS['m:' + m] || [])[1];
      return `<button type="button" role="menuitem" data-m="${m}"><span>${esc(label)}</span>${k ? `<span class="kk">${esc(k[0])}</span>` : ''}</button>`; };
    const ugb = (m, i, label) => b(m, label).replace('data-m=', `data-g="${i}" data-m=`);   // an item of your group i
    const mvs = (where) => !mvAt || mvAt[1] < 2 ? '' : (mvAt[0] > 0 ? b('mvup', 'Move up') : '') + (mvAt[0] < mvAt[1] - 1 ? b('mvdn', 'Move down') : '') +
      (mvAt[0] > 0 ? b('mvtop', `To the top of ${where}`) : '') + (mvAt[0] < mvAt[1] - 1 ? b('mvbot', `To the bottom of ${where}`) : '');
    const el = document.createElement('div'); el.className = 'wv-menu'; el.setAttribute('role', 'menu');
    const mkId = mk ? this.umarks.indexOf(mk) + 1 : 0, pale = getComputedStyle(this.root).getPropertyValue('--muted').trim();
    const six = c => /^#[0-9a-f]{6}$/i.test(c || ''), acc6 = getComputedStyle(this.root).getPropertyValue('--accent').trim();
    const dm = on.dl ? on.dl.m : null, dlId = dm ? this.umarks.indexOf(dm) + 1 : 0, dd = dm && this.deltaList().find(d => d.a === dm);
    const ln = on.line && on.line.n > (dm || mk ? 1 : 0) ? on.line : null, pick0 = c => esc(six(c) ? c : six(acc6) ? acc6 : '#808080');
    el.innerHTML = (dm && dd ? `<div class="mh">Δ ${esc(this.deltaText(dd.dt))} · from marker ${dlId}</div>` +
      `<label class="mi">Colour <input type="color" class="dlc" value="${pick0(dm.dcolor)}" aria-label="the colour of this Δ"></label>` +
      (dm.dcolor ? b('dlown', 'Its own colour') : '') +
      b('dlnone', 'No arrow from this marker') + '<hr>' : '') +
      (ln ? `<div class="mh">This line · ${ln.n} thing${ln.n === 1 ? '' : 's'}</div>` +
      `<label class="mi">Colour <input type="color" class="lnc" value="${pick0()}" aria-label="the colour of this line"></label>` +
      b('lnown', 'Their own colours') + '<hr>' : '') +
      (mk ? `<div class="mh">Marker ${mkId}${mk.label ? ' · ' + esc(mk.label) : ''}</div>` + b('mktext', 'Its text…') +
      `<label class="mi">Colour <input type="color" class="mkc" value="${esc(six(mk.color) ? mk.color : six(pale) ? pale : '#808080')}" ` +
      `aria-label="marker ${mkId} colour"></label>` + (mk.color ? b('mkpale', 'Pale again') : '') + b('mkdel', 'Delete the marker') + '<hr>' : '') +
      (r ? `<div class="mh">${esc(this.rangeText())}</div>` + b('zoom', 'Zoom to the range') + b('marks', 'Bookmarks at its ends',
      'Two bookmarks and an arrow with the Δ between them') + b('copyd', 'Copy Δ') + '<hr>' : '') +
      (np ? `<div class="mh">${np} ${this.selRun.size > 1 ? 'selected' : 'highlighted'} rows</div>` : '') + b('copyimg', 'Copy image') + b('png',
        'Save image as PNG') + b('svg', 'Save image as SVG') + b('wdjson', 'Save as WaveDrom') + b('wdcopy', 'Copy WaveDrom') +
      // the gaps: a submenu (its settings, the role of the signals clicked, a reset)
      (`<div class="msub"><button type="button" role="menuitem" class="subh" aria-haspopup="menu" aria-expanded="false"><span class="gh">${gn()}</span>` +
        `<span class="kk">▸</span></button><div class="sub" role="menu" hidden>`) +
      (`<div class="mi gp"><label><input type="checkbox" class="gon"${gp.gaps ? ' checked' : ''}> <span class="gn">${gn()}</span></label>` +
        `<label><input type="checkbox" ` +
        `class="gview"${gp.gapView ? ' checked' : ''}> on the waves</label></div><div class="mi gp"><span>idle ` +
        `<input class="gi" value="${esc(gp.gapIdle)}" aria-label="idle this long: clock cycles or a time"> keep <input class="gk" ` +
        `value="${esc(gp.gapKeep)}" aria-label="kept around a change: clock cycles or a time"></span></div>`) +
      (`<div class="mi gp"><span>${gby ? `✂ ${gby} expression${gby === 1 ? '' : 's'} <button type="button" class="gx" data-m="gbyx" ` +
        `aria-label="the gaps of the expressions off">✕</button>` : nref ? `by ${nref} signal${nref === 1 ? '' : 's'} <button type="button" class="gx" ` +
        `data-m="grefx" aria-label="the gaps by the signals drawn">✕</button>` : 'by the signals drawn'}` +
        `${gck ? ` · ↑ ${esc(gck.name)} <button type="button" class="gx" ` +
        `data-m="gclkx" aria-label="the cycles of the clock found">✕</button>` : ''}${naux ? ` · + ${naux} <button type="button" class="gx" ` +
        `data-m="gauxx" aria-label="count every other signal">✕</button>` : ''}</span><span>` +
        (nref ? `<label><input type="checkbox" class="gonly"${gp.gapOnly ? ' checked' : ''}> only them</label> ` : '') +
        `<select class="gcnt" aria-label="the texts of the gaps">${[['clock', naux ? 'time, cycles, +' : 'time, cycles'],
          ['edges', '+ changes in a gap'], ['off', 'no texts']]
          .map(([v, t]) => `<option value="${v}"${gp.gapCount === v ? ' selected' : ''}>${t}</option>`).join('')}</select></span></div>`) +
      (sigs.length ? `<hr><div class="mh">${esc(many ? of : sig.name)}</div>` +
        b('gref', gref ? 'Not by this signal' : many ? `By the ${sigs.length}: their changes kept` : 'By this signal: its changes kept') +
        b('gaux', gaux ? 'Do not count it' : many ? `Count the changes of the ${sigs.length} in a gap` : 'Count its changes in a gap') +
        (sig && sig.width === 1 ? b('gclk', isGck ? 'Not by its cycles' : 'Count in cycles of this clock') : '') : '') +
      '<hr>' + b('greset', 'Reset the gaps') + '</div></div>' +
      // the clock cycles under the time axis: a submenu (on / off, this clock, cycle 0 here, a reset)
      (`<div class="msub"><button type="button" role="menuitem" class="subc" aria-haspopup="menu" aria-expanded="false"><span>${co.cycles ? 'Cycles: ' +
        (cd ? esc(cd.clk.name) : 'no clock') : 'Cycles'}</span><span class="kk">▸</span></button><div class="sub" role="menu" hidden>`) +
      (cda ? b('cycon', co.cycles ? 'Hide the cycles' : `Show the cycles of ${esc(cda.clk.name)}`) : '<div class="mh">no clock found: pick a 1-bit one</div>') +
      (sig && sig.width === 1 ? b('cyclk', isCyc ? 'Not by this clock' : `Cycles of ${esc(sig.name)}`) : '') +
      (cda ? b('cyc0', at < cda.ups[0] ? `Cycle 0 at the first edge of ${esc(cda.clk.name)}` : `Cycle 0 at this edge of ${esc(cda.clk.name)}`) : '') +
      '<hr>' + b('cycx', 'Reset the cycles') + '</div></div>' +
      (ugh ? `<hr><div class="mh">${esc(ugh.name)} · your group</div>` + mvs('your groups') + b('ugfold', this.collapsed.has(ugh.id) ? 'Open this group' :
        'Fold this group') : '') +
      (it ? `<hr><div class="mh">${esc(it.full || it.name)}${many ? `<br>+ every ${run ? 'selected' : 'highlighted'} row: ${sigs.length} signals` : ''}</div>` +
        (mine ? mvs(`“${mine.ug.name}”`) : '') +   // (b() escapes it)
        (sigs.length ?
          `<label class="mi">${many ? `Colour of ${sigs.length}` : 'Colour'} <input type="color" value="${esc(col)}"
            aria-label="colour of ${esc(of)}"></label>` +
            (sigs.some(r => this.painted.has(r.full)) ? b('unpaint', many ? 'Their own colours' : 'Its own colour') : '') : '') +
        (sig && buses.length ?
          (`<label class="mi">${many ? `Radix of ${buses.length}` : 'Radix'} <span><select aria-label="radix of ${esc(of)}"><option value="">the ` +
            `page's${many ? '' : ` (${esc(rx)})`}</option>` +
            RADIX.map(x => `<option${buses.every(r => this.radixes.get(r.full) === x) ? ' selected' : ''}>${x}</option>`).join('')) +
          (`<option value="q"${qk === 'q' ? ' selected' : ''}>fixed q (unsigned)</option><option value="sq"${qk === 'sq' ? ' selected' : ''}>fixed sq ` +
              `(signed)</option></select>`) +
          (`<input type="number" class="qf" min="0" max="128" value="${qf}" aria-label="fraction bits" title="Fraction bits of the fixed-point ` +
              `value"${qk ? '' : ' hidden'}></span></label>`) : '') +
        (sig && buses.length ? b('analog', buses.every(r => r.analog) ? 'As a bus' : many ? `Analog: ${buses.length}` : 'Analog (step plot)') : '') +
        (vecs.length ? b('bits', vecs.every(r => this.bitsOpen.has(r.full)) ? (many ? `Fold the bits of ${vecs.length}` : 'Fold the bits') :
          many ? `Bits of ${vecs.length}` : `Bits: ${vecs[0].width} rows`) : '') +
        (dupable.length ? b('dup', dupable.length > 1 ? `Duplicate ${dupable.length}` : 'Duplicate') : '') +
        (copies.length ? b('undup', copies.length > 1 ? `Remove the ${copies.length} copies` : 'Remove the copy') : '') +
        b('hl', this.picks.has(it) ? 'Remove the highlight' : 'Highlight') + b('hide',
          many ? `Hide the ${rows.length} ${run ? 'selected' : 'highlighted'}` : grp ? 'Hide this module' : 'Hide',
          'Leave it out of the view (Hidden: N ✕ in the bar shows it again)') +
        (grp && !ugh ? b('fold', this.collapsed.has(grp.id) ? 'Open this module' : 'Fold this module') : up != null ? b('foldup', 'Fold its module') : '') +
        (sig ? b('mark', 'Bookmark here', 'A bookmark on this signal at the time clicked') : '') +
        // your groups: a submenu (into / out of a group, a new one, delete; go to any of them)
        (`<div class="msub"><button type="button" role="menuitem" class="subg" aria-haspopup="menu" aria-expanded="false">` +
          `<span>Groups${this.ugroups.length ? ` (${this.ugroups.length})` : ''}</span><span class="kk">▸</span></button><div class="sub" role="menu" hidden>` +
          (sig && !mine ? '<div class="mh">to move it: into a group of yours, any order there</div>' : '') +
          (sigs.length ? this.ugroups.map((g, i) => (sigs.every(r => g.signals.includes((r.orig || r).full)) ? ugb('ugoff', i, `Out of “${g.name}”`) :
            ugb('ugto', i, `Into “${g.name}”`))).join('') + b('ugnew', many ? `New group of the ${sigs.length}` : 'New group with it') : '') +
          (sig && sig.ug ? b('ugout', `Out of “${sig.ug.name}” (this row)`) : '') + (grp && grp.user ? b('ugdel', 'Delete this group') : '') +
          (this.ugroups.length ? '<hr><div class="mh">Go to</div>' + this.ugroups.map((g, i) => ugb('ugo', i, `${g.name} · ${g.signals.length}`)).join('') :
            '<div class="mh">no groups yet</div>') + '</div></div>') +
        b('umark', 'Marker here') + b('mlist', 'Markers…') + b('c2',
          'Second cursor here') + (this.cursor2 != null ? b('c2x', 'Clear the second cursor') : '') + b('copyname', 'Copy the path') +
        b('types', 'Type…') : '') +
      (ng || nh ? '<hr>' + (ng ? b('zM', 'Fold every module') + b('zR', 'Open every module') : '') + (nh ? b('unhide', `Show the hidden (${nh})`) : '') : '') +
      (this.scopes().length ? '<hr>' + b('mods', 'Modules…') + (it && this.scopeOfRow(it) ? b('locate', 'Locate module in tree') : '') +
        (this.only ? b('onlyp', this.only.on ? 'Pause Only' : 'Resume Only') + b('onlyx', 'Clear Only') : '') : '') +
      (this.fsms().length ? '<hr>' + b('fsms', 'State machines…') + (this.fsm ? b('fsmx', 'Clear the FSM layer') : '') : '') +
      (r ? '<hr>' + b('clear', 'Clear the range') : '') +
      (this.bms.length || this.umarks.length ? '<hr>' + b('clearmarks', 'Clear bookmarks and markers') : '');
    this.root.append(el); this.menuEl = el;
    const box = el.getBoundingClientRect();
    el.style.left = Math.max(4, Math.min(cx, innerWidth - box.width - 4)) + 'px'; el.style.top = Math.max(4, Math.min(cy, innerHeight - box.height - 4)) + 'px';
    const done = () => { this.closeMenu(); this.refocus(); };
    // the submenu: open on the pointer or a click, beside the menu (the left side when the right has no room)
    for (const msub of el.querySelectorAll('.msub')) {   // the gaps, the cycles, your groups
      const sub = msub.querySelector('.sub'), subh = msub.querySelector('.subh, .subc, .subg');
      const subOpen = on => {
        sub.hidden = !on; subh.setAttribute('aria-expanded', on); if (!on) return;
        Object.assign(sub.style, { left: '100%', right: 'auto', top: '-5px' }); const s = sub.getBoundingClientRect();
        if (s.right > innerWidth - 4) Object.assign(sub.style, { left: 'auto', right: '100%' });
        if (s.bottom > innerHeight - 4) sub.style.top = -5 - (s.bottom - innerHeight + 4) + 'px';
      };
      msub.addEventListener('mouseenter', () => subOpen(true));
      msub.addEventListener('mouseleave', () => { if (!sub.contains(document.activeElement)) subOpen(false); });   // not while typing in it
      subh.addEventListener('click', () => subOpen(true));   // (the pointer opened it already: stays open)
    }
    el.addEventListener('click', e => {
      const m = e.target.closest('button[data-m]'); if (!m) return;
      const act = m.dataset.m;
      if (act === 'zoom') this.zoomTo(...r);
      else if (act === 'dlown') this.run({ op: 'deltas', id: dlId, color: null });
      else if (act === 'dlnone') this.run({ op: 'deltas', id: dlId, to: null });
      else if (act === 'lnown') this.run(this.lineOps(ln, null));
      else if (act === 'clearmarks') this.clearMarks();
      else if (act === 'marks') {
        const n = Math.max(0, ...this.bms.map(x => x.n)) + 1, s = sig ? sig.full : null;
        const top = this.topNow(); this.bms.push(...bmNorm([{ n, t: r[0], signal: s, top }, { n: n + 1, t: r[1], signal: s, top }]));
        this.arrows.push(...arNorm([{ from: n, to: n + 1, shape: '-', head: '<>', label: this.rangeText().replace(/^Δ /, '') }])); this.changed(true);
      }
      else if (act === 'copyd') this.copyText(this.rangeText().replace(/^Δ /, '').split(' · ')[0].split(' / ')[0]);
      else if (act === 'copyimg') {
        const png = this.toPNG(pic);
        try { navigator.clipboard.write([new ClipboardItem({ 'image/png': png })]).then(() => this.toast('image copied'), err =>
          this.toast('not copied: ' + err.message)); }
        catch (err) { this.toast('this browser cannot copy an image: Save image as PNG'); }
      }
      else if (act === 'png') this.toPNG(pic).then(bl => { this.download(bl, this.picName('png')); this.toast('saved ' + this.picName('png')); }, err =>
        this.toast(err.message));
      else if (act === 'svg') { this.download(new Blob([this.toSVG(pic)], { type: 'image/svg+xml' }), this.picName('svg'));
        this.toast('saved ' + this.picName('svg')); }
      else if (act === 'wdjson' || act === 'wdcopy') {
        const [ta, tb] = r || [this.t0, this.t0 + this.span], text = wdText(this.toWaveDrom(ta, tb)), cut = this.wdCut ? ` — the first ${WD_CELLS} ` +
          `cycles only, to ${this.fmt(this.wdCut.to, (this.wdCut.to - ta) / 1000, this.wdCut.to - ta)}` : '';
        if (act === 'wdcopy') { try { navigator.clipboard.writeText(text).then(() => this.toast('WaveDrom copied' + cut), () => this.toast('not copied'));
          } catch (e) { this.toast('not copied'); } }
        else { this.download(new Blob([text + '\n'], { type: 'application/json' }), this.picName('wavedrom.json'));
          this.toast('saved ' + this.picName('wavedrom.json') + cut); }
      }
      else if (act === 'unpaint') { sigs.forEach(r => this.painted.delete(r.full)); this.savePaint(); this.renderNames(); this.draw(); }
      else if (act === 'hl') this.toggleHighlight(it);
      else if (act === 'analog') { const on = !buses.every(r => r.analog); buses.forEach(r => this.setAnalog(r, on ? 3 : false)); }
      else if (act === 'bits') this.setBits(vecs, !vecs.every(r => this.bitsOpen.has(r.full)));
      else if (act === 'dup') { const out = dupable.map(r => this.dupAdd(r)).filter(Boolean); this.dupDone();
        if (out.length) { this.select(out[0]);
          this.toast(`${out.length > 1 ? `${out.length} copies: each` : `${out[0].name}:`} its own radix, analog, colour`); } }
      else if (act === 'undup') { copies.forEach(r => this.dupDrop(r)); this.dupDone(); }
      else if (act === 'hide') this.hide(rows);
      else if (act === 'unhide') this.unhide();
      else if (act === 'fold') { if (this.collapsed.has(grp.id)) this.collapsed.delete(grp.id); else this.collapsed.add(grp.id); this.foldTouched = true;
        this.renderNames(); this.draw(); }
      else if (act === 'foldup') { this.collapsed.add(up); if (this.sel && this.sel.anc.includes(up)) this.sel = null; this.foldTouched = true;
        this.renderNames(); this.draw(); }
      else if (act === 'zM' || act === 'zR') this.seq(act);
      else if (act === 'mods' || act === 'locate') { this.closeMenu(); this.modules(true); if (act === 'locate') this.mods.locate(it); return this; }
      else if (act === 'onlyp') this.setOnly({ on: !this.only.on });
      else if (act === 'onlyx') this.setOnly(null);
      else if (act === 'fsms') { this.closeMenu(); this.fsmPanel(true); return this; }
      else if (act === 'fsmx') this.setFsm(null);
      // a bookmark, a marker: its text asked over the waves first, then it goes into its list below them (edited there)
      else if (act === 'mark') { const t = this.snap(sig, at), [x, y] = this.menuAt, top = this.topNow();   // the waves as they are now
        this.askText(x, y, `Bookmark · ${sig.name} · ${this.fmtCursor(t)}`, 'its text', text => {
          const n = Math.max(0, ...this.bms.map(b => b.n)) + 1; this.bms.push({ n, t, signal: sig.full, text, color: null, top }); this.changed(true); });
        return this; }
      else if (act === 'copyname') this.copyRows([it]);
      else if (act === 'types') { const x = this.menuEl.getBoundingClientRect(); this.closeMenu(); this.typesBox(sig0, x.left, x.top); return this; }
      else if (act === 'mlist') { this.closeMenu(); this.marksMenu(); return this; }
      else if (act === 'mktext') { const [x, y] = this.menuAt;
        this.askText(x, y, `Marker ${mkId} · ${this.fmtCursor(mk.t)}`, 'its label', label => this.run({ op: 'marker', id: mkId, label }), mk.label);
        return this; }
      else if (act === 'mkpale') this.run({ op: 'marker', id: mkId, color: null });
      else if (act === 'mkdel') this.run({ op: 'marker', id: mkId, delete: true });
      else if (act === 'umark') { const [x, y] = this.menuAt;
        this.askText(x, y, `Marker · ${this.fmtCursor(at)}`, 'its label',
          label => this.run(Object.assign({ op: 'marker', t: at }, label ? { label } : {})));
        return this; }
      else if (act === 'ugto') this.toGroup(this.ugroups[+m.dataset.g].name, sigs);
      else if (act === 'ugoff') this.run({ op: 'group', name: this.ugroups[+m.dataset.g].name, remove: sigs.map(x => (x.orig || x).full) });
      else if (act === 'ugo') { this.closeMenu(); return this.goGroup(this.ugroups[+m.dataset.g].name); }
      else if (act === 'ugnew') { let k = this.ugroups.length + 1; while (this.ugroups.some(g => g.name === `group ${k}`)) k++;
        this.toGroup(`group ${k}`, sigs); }
      else if (act === 'ugout') this.hide([sig]);
      else if (act === 'ugdel') this.run({ op: 'group', name: (ugh || grp).name, delete: true });
      else if (act === 'mvup' || act === 'mvdn' || act === 'mvtop' || act === 'mvbot') {
        this.moveKey({ mvup: -1, mvdn: 1, mvtop: -Infinity, mvbot: Infinity }[act], false, ugh || mine); }
      else if (act === 'ugfold') { if (this.collapsed.has(ugh.id)) this.collapsed.delete(ugh.id); else this.collapsed.add(ugh.id);
        this.renderNames(); this.draw(); }
      else if (act === 'c2') this.setCursor2(sig ? this.snap(sig, at) : at);
      else if (act === 'gref') role('gapSignals', !gref);
      else if (act === 'gaux') role('gapAux', !gaux);
      else if (act === 'grefx') this.setGaps({ gapSignals: null });
      else if (act === 'gbyx') this.extraKeep.off(true);
      else if (act === 'gauxx') this.setGaps({ gapAux: null });
      else if (act === 'gclk') role('gapClock', !isGck);
      else if (act === 'cycon') this.setCycles({ cycles: !co.cycles });
      else if (act === 'cyclk') this.setCycles(isCyc ? { cycleClock: null } : { cycles: true, cycleClock: sig0.full, cycleZero: null });
      else if (act === 'cyc0') { const u = cda.ups, i = Math.max(0, lastBefore(u.length, j => u[j], at + timeEps(at)));   // the edge at or before
        this.setCycles({ cycles: true, cycleZero: u[i] }); }
      else if (act === 'cycx') this.setCycles(null);
      else if (act === 'greset') { this.setGaps(null); this.toast('the gaps: the settings again'); }
      else if (act === 'gclkx') this.setGaps({ gapClock: null });
      else if (act === 'c2x') this.setCursor2(null);
      else if (act === 'clear') this.setRange(null);
      done();
    });
    const qfEl = el.querySelector('input.qf'), fixed = k => buses.forEach(r => this.setRadix(r, k + Math.max(0, Math.min(128, Math.round(+qfEl.value || 0)))));
    el.addEventListener('change', e => {
      if (e.target.tagName !== 'SELECT' || !buses.length || e.target.closest('.gp')) return;
      // stays open for the fraction bits
      if (e.target.value === 'q' || e.target.value === 'sq') { qfEl.hidden = false; fixed(e.target.value); qfEl.focus(); return; }
      buses.forEach(r => this.setRadix(r, e.target.value || null)); done();
    });
    if (qfEl) qfEl.addEventListener('input', () => { const k = el.querySelector('select:not(.gcnt)').value; if (k === 'q' || k === 'sq') fixed(k); });
    el.addEventListener('input', e => { if (e.target.type === 'color' && sigs.length) { sigs.forEach(r => this.painted.set(r.full, e.target.value));
      this.savePaint(); this.renderNames(); this.draw(); } });
    el.addEventListener('change', e => {   // the gaps: kept for this viewer, the menu stays open
      if (!e.target.closest('.gp')) return;
      const gon = el.querySelector('.gon'), gv = el.querySelector('.gview'), only = el.querySelector('.gonly');
      if (e.target === gv && gv.checked) gon.checked = true;   // on the waves: the gaps on
      clearTimeout(this.gapTypeT);
      this.setGaps({ gaps: gon.checked, gapView: gv.checked, ...this.gapFields(el.querySelector('.gi'), el.querySelector('.gk')),
        ...(only ? { gapOnly: only.checked } : {}), gapCount: el.querySelector('.gcnt').value });
      for (const x of el.querySelectorAll('.gn, .gh')) x.textContent = gn();
    });
    if (dm && dd) {   // as a marker's below
      el.querySelector('.dlc').addEventListener('input', e => { dm.dcolor = e.target.value; this.draw(); });
      el.querySelector('.dlc').addEventListener('change', e => this.run({ op: 'deltas', id: dlId, color: e.target.value }));
    }
    if (ln) {
      el.querySelector('.lnc').addEventListener('input', e => { const c = e.target.value; ln.ds.forEach(m => { m.dcolor = c; });
        [...ln.ms, ...ln.bs, ...ln.as].forEach(x => { x.color = c; }); this.draw(); });
      el.querySelector('.lnc').addEventListener('change', e => this.run(this.lineOps(ln, e.target.value)));
    }
    if (mk) {   // its colour: seen as it is picked, one step of undo when the picker closes
      el.querySelector('.mkc').addEventListener('input', e => { mk.color = e.target.value; this.draw(); });
      el.querySelector('.mkc').addEventListener('change', e => this.run({ op: 'marker', id: mkId, color: e.target.value }));
    }
    el.addEventListener('input', e => {   // idle, keep: as they are typed, on the waves at once
      if (!e.target.matches('.gi, .gk') || !this.gapLive()) return;
      this.gapType(() => this.gapFields(el.querySelector('.gi'), el.querySelector('.gk'), true));
    });
    el.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); done(); } });
    // Windows sends contextmenu on the release of the button: by then this menu is under the pointer (no browser menu over it)
    el.addEventListener('contextmenu', e => e.preventDefault());
    this.menuOff(el);
    (el.querySelector('button') || el).focus({ preventScroll: true });
    return el;
  },
  // the right button on the bar: its tool groups with a tick each (a click shows / hides one), Show all, Hide all; the
  // menu stays open for the next one
  toolsMenu(cx, cy) {
    this.closeMenu();
    const el = document.createElement('div'); el.className = 'wv-menu wv-tools'; el.setAttribute('role', 'menu');
    const item = n => `<button type="button" role="menuitemcheckbox" data-m="tg" data-tg="${esc(n)}"><span><span class="ck"></span>${
      esc(n.charAt(0).toUpperCase() + n.slice(1))}</span></button>`;
    el.innerHTML = '<div class="mh">Tools in the bar</div><button type="button" role="menuitem" data-m="all"><span>Show all</span></button>' +
      '<button type="button" role="menuitem" data-m="none"><span>Hide all</span></button><hr>' + this.toolGroups().map(item).join('');
    const mark = () => { const H = new Set(toolNames(this.S.toolsHidden));
      for (const b of el.querySelectorAll('button[data-tg]')) { const on = !H.has(b.dataset.tg); b.setAttribute('aria-checked', on);
        b.querySelector('.ck').textContent = on ? '✓' : ''; } };
    mark(); this.root.append(el); this.menuEl = el;
    const box = el.getBoundingClientRect();
    el.style.left = Math.max(4, Math.min(cx, innerWidth - box.width - 4)) + 'px'; el.style.top = Math.max(4, Math.min(cy, innerHeight - box.height - 4)) + 'px';
    el.addEventListener('click', e => {
      const m = e.target.closest('button[data-m]'); if (!m) return;
      const H = new Set(toolNames(this.S.toolsHidden));
      if (m.dataset.m === 'all') H.clear(); else if (m.dataset.m === 'none') this.toolGroups().forEach(n => H.add(n));
      else if (!H.delete(m.dataset.tg)) H.add(m.dataset.tg);
      this.setToolsHidden([...H]); mark();
    });
    el.addEventListener('keydown', e => {
      const bs = [...el.querySelectorAll('button')], k = bs.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.stopPropagation(); this.closeMenu(); this.refocus(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault();
        bs[(k + (e.key === 'ArrowDown' ? 1 : -1) + bs.length) % bs.length]?.focus(); }
    });
    el.addEventListener('contextmenu', e => e.preventDefault());
    this.menuOff(el);
    (el.querySelector('button') || el).focus({ preventScroll: true });
    return el;
  },
  // ctrl+G: your groups in a list over the names (as the right button's menu); a click or Enter goes there
  groupsMenu() {
    this.closeMenu();
    const el = document.createElement('div'); el.className = 'wv-menu wv-groups'; el.setAttribute('role', 'menu');
    const item = (g, i) => `<button type="button" role="menuitem" data-m="ugo" data-g="${i}"><span><i class="sw" style="background:${
      esc(g.color || 'var(--accent)')}"></i>${esc(g.name)}</span><span class="kk">${g.signals.length}</span></button>`;
    el.innerHTML = '<div class="mh">Your groups</div>' + (this.ugroups.length ? this.ugroups.map(item).join('') :
      '<div class="mh">none yet: the right button on a signal, Groups ▸ New group</div>');
    this.root.append(el); this.menuEl = el;
    const n = this.namesEl.getBoundingClientRect(), box = el.getBoundingClientRect();
    el.style.left = Math.max(4, Math.min(n.left + 12, innerWidth - box.width - 4)) + 'px';
    el.style.top = Math.max(4, Math.min(Math.max(n.top, 0) + this.hdrH + 8, innerHeight - box.height - 4)) + 'px';
    el.addEventListener('click', e => { const m = e.target.closest('button[data-g]'); if (!m) return; this.closeMenu();
      this.goGroup(this.ugroups[+m.dataset.g].name); });
    el.addEventListener('keydown', e => {
      const bs = [...el.querySelectorAll('button')], k = bs.indexOf(document.activeElement);
      if (e.key === 'Escape') { e.stopPropagation(); this.closeMenu(); this.refocus(); }
      else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault();
        bs[(k + (e.key === 'ArrowDown' ? 1 : -1) + bs.length) % bs.length]?.focus(); }
    });
    this.menuOff(el);
    (el.querySelector('button') || el).focus({ preventScroll: true });
    return el;
  },
  // gm (the right button's Markers…): the markers (the page's and yours) and the bookmarks in a list over the waves, by
  // time; ↓ the first (↑ the last), then ↑ ↓ Home End step through them and a click picks one: the cursor on it, the
  // waves at its time with the span they have — a marker in the middle; a bookmark bookmarkLeft from the left, its signal
  // selected and the rows scrolled as they were when it was made (goBm); Enter or Esc closes it there. Nothing below the
  // waves takes the focus
  marksMenu() {
    this.closeMenu();
    const items = [...this.markers.map((m, i) => ({ t: m.t, label: m.label || '', color: m.color, kind: i < this.pageMarks.length ? 'page' : 'mine' }))
      .sort((a, b) => a.t - b.t), ...this.bms.map(b => ({ t: b.t, label: b.text || '', color: b.color, kind: 'bm', n: b.n, signal: b.signal, b }))
      .sort((a, b) => a.t - b.t)];
    const el = document.createElement('div'); el.className = 'wv-menu wv-marks'; el.setAttribute('role', 'listbox'); el.setAttribute('aria-label', 'markers');
    el.tabIndex = -1;
    const nm = items.filter(x => x.kind !== 'bm').length;
    const item = (x, i) => `<button type="button" role="option" data-i="${i}" aria-selected="false" title="${esc(x.label || this.fmtCursor(x.t))}">` +
      `<span><i class="sw" style="background:${esc(x.color || (x.kind === 'bm' ? 'var(--accent)' : 'var(--muted)'))}"></i>` +
      `<b>${esc(this.fmtCursor(x.t))}</b> ${esc(x.label)}</span><span class="kk">${x.kind === 'bm' ? `${x.n}${x.signal ? ' · ' +
        esc(x.signal.split('.').pop()) : ''}` : x.kind === 'page' ? 'page' : ''}</span></button>`;
    el.innerHTML = '<div class="mh">Markers · ↑ ↓ the waves follow · Enter, Esc close</div>' + (items.length ? (nm ? '' :
      '<div class="mh">no markers: the right button, Marker here</div>') + items.map((x, i) => (i === nm && nm < items.length ?
        '<hr><div class="mh">Bookmarks</div>' : '') + item(x, i)).join('') : '<div class="mh">none yet: the right button, Marker here or Bookmark here</div>');
    this.root.append(el); this.menuEl = el;
    const w = this.wcol.getBoundingClientRect(), box = el.getBoundingClientRect();   // at the right of the waves, under the axis
    el.style.left = Math.max(4, Math.min(w.right - box.width - 12, innerWidth - box.width - 4)) + 'px';
    el.style.top = Math.max(4, Math.min(Math.max(w.top, 0) + this.hdrH + 6, innerHeight - box.height - 4)) + 'px';
    const bs = [...el.querySelectorAll('button[data-i]')];
    let at = -1;
    const pick = i => {
      if (!items.length) return; at = Math.min(Math.max(i, 0), items.length - 1); const x = items[at];
      bs.forEach((b, j) => { b.setAttribute('aria-selected', j === at); b.classList.toggle('on', j === at); });
      bs[at].focus({ preventScroll: true }); bs[at].scrollIntoView({ block: 'nearest' });
      if (x.b) { this.goBm(x.b); return; }   // a bookmark: where it was made (goBm); a marker: in the middle
      this.cursor = x.t; this.center(x.t);
      this.renderNames(); this.draw();
    };
    el.addEventListener('click', e => { const b = e.target.closest('button[data-i]'); if (b) pick(+b.dataset.i); });
    el.addEventListener('keydown', e => {
      const k = e.key;
      if (k === 'Escape' || k === 'Enter') { e.preventDefault(); e.stopPropagation(); this.closeMenu(); this.refocus(); }
      else if (k === 'ArrowDown' || k === 'ArrowUp') {
        e.preventDefault(); pick(at < 0 ? (k === 'ArrowDown' ? 0 : items.length - 1) : at + (k === 'ArrowDown' ? 1 : -1)); }
      else if (k === 'Home' || k === 'End') { e.preventDefault(); pick(k === 'Home' ? 0 : items.length - 1); }
    });
    el.addEventListener('contextmenu', e => e.preventDefault());
    this.menuOff(el, false);
    el.focus({ preventScroll: true });
    return el;
  },
  // your group by its name: opened (and shown when hidden), in the middle of the waves, its first signal selected
  goGroup(name) {
    const g = this.ugRows().find(r => r.type === 'group' && r.name === name); if (!g) { this.toast(`no group "${name}"`); return this; }
    this.collapsed.delete(g.id); if (this.hiddenRows.delete(g.path)) this.saveRows(); this.foldTouched = true; this.renderNamesNow();
    const first = this.vis.find(r => r.ug === g); if (first) this.select(first); else this.draw();
    this.centerRow(g); this.toast(name); return this;
  },
  // a text asked over the waves where the menu was (a bookmark's text, a marker's label): Enter gives it (empty too), Esc
  // or a click elsewhere gives nothing; the waves stay where they are (no field below them takes the focus)
  askText(x, y, title, hint, give, value = '') {
    this.closeMenu();
    const el = document.createElement('div'); el.className = 'wv-menu wv-ask'; el.setAttribute('role', 'dialog'); el.setAttribute('aria-label', title);
    el.innerHTML = `<div class="mh">${esc(title)}</div><input type="text" spellcheck="false" autocomplete="off" placeholder="${esc(hint)}" ` +
      `aria-label="${esc(hint)}"><div class="ak"><span>Enter: add · Esc: cancel</span><button type="button" data-m="ok">Add</button></div>`;
    this.root.append(el); this.menuEl = el;
    const b = el.getBoundingClientRect(), inp = el.querySelector('input'); inp.value = value;
    el.style.left = Math.max(4, Math.min(x, innerWidth - b.width - 4)) + 'px'; el.style.top = Math.max(4, Math.min(y, innerHeight - b.height - 4)) + 'px';
    const done = ok => { const v = inp.value.trim(); this.closeMenu(); this.refocus(); if (ok) give(v); };
    inp.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(e.key === 'Enter'); } });
    el.querySelector('button[data-m=ok]').addEventListener('click', () => done(true));
    el.addEventListener('contextmenu', e => e.preventDefault());
    this.menuOff(el, false);
    inp.focus({ preventScroll: true });
    return el;
  },
  // a menu el opened: a press outside it or the window's blur closes it, the keys back on the waves when nothing took them. After
  // the click that opened it; not for a menu closed meanwhile (its listener would close the next one). blur false: a box to type in stays
  menuOff(el, blur = true) {
    const off = this.offMenu = e => {
      if (el.contains(e.target)) return;
      this.closeMenu();
      if (e.type === 'pointerdown') setTimeout(() => { const a = document.activeElement;
        if (VIEWS.has(this) && (a === document.body || (this.root.contains(a) && !a.matches('input, select, textarea')))) this.refocus(); }, 0);
    };
    setTimeout(() => { if (this.menuEl !== el) return; document.addEventListener('pointerdown', off, { capture: true, signal: this.ac.signal });
      if (blur) window.addEventListener('blur', off, { signal: this.ac.signal }); }, 0);
  },
  refocus() { this.canvas.focus({ preventScroll: true }); return this; },
  // the first key of a sequence: a moment after it (keyHints ms, false: never) a box says what can follow; a key or a click on it goes on,
  // as long as it is open (the keys stay on the waves), Esc or a click elsewhere closes it
  keyHintOn(k) {
    this.kpre = { k, t: Date.now() };
    if (this.S.keyHints !== false) this.keysT = setTimeout(() => this.keyHintShow(k), +this.S.keyHints || 0);
  },
  keyHintOff() {
    clearTimeout(this.keysT); this.kpre = null;
    if (!this.keysEl) return;
    this.keysEl.remove(); this.keysEl = null; document.removeEventListener('pointerdown', this.keysOff, true);
  },
  keyRows(pre) {
    const rows = KEY_MENUS[pre][1].filter(r => r.length === 1 || !r[2] || r[2](this))
      .map(r => (typeof r[1] === 'function' ? [r[0], r[1](this)] : r.slice(0, 2)));
    const own = new Set(KEY_MENUS[pre][1].map(r => r[0]));
    const more = Object.keys(this.keys).filter(s => s.length === 2 && s[0] === pre && !own.has(s[1])).map(s => [s[1],
      (this.keyHelp || []).find(h => h.split(' ').includes(s))]).filter(r => r[1]);
    more.forEach(r => { r[1] = r[1].replace(/^(\S\S )+/, '').replace('next / previous ', ''); });   // ']f [f next / previous …'
    return rows.concat(more.length && pre === 'g' ? [['Plugins']] : [], more).filter((r, i, l) => r.length > 1 || (l[i + 1] && l[i + 1].length > 1));
  },
  keyHintShow(k) {
    if (!this.kpre || this.kpre.k !== k || this.keysEl) return;
    this.kpre.t = Infinity;   // it waits for you
    const el = document.createElement('div'); el.className = 'wv-keys'; el.setAttribute('role', 'menu'); el.setAttribute('aria-label', `after ${k}`);
    const line = r => (r.length === 1 ? `<div class="ks">${esc(r[0])}</div>` :
      `<button type="button" role="menuitem" data-k="${esc(r[0])}"><kbd>${esc(r[0])}</kbd><span>${esc(r[1])}</span></button>`);
    el.innerHTML = `<div class="kh"><kbd>${esc(k)}</kbd><b>${esc(KEY_MENUS[k][0])}</b><span class="muted">Esc</span></div>` +
      `<div class="kg">${this.keyRows(k).map(line).join('')}</div>`;
    el.addEventListener('pointerdown', e => e.preventDefault());
    el.addEventListener('click', e => { const b = e.target.closest('button[data-k]'); if (!b) return; this.keyHintOff(); this.seq(k + b.dataset.k); });
    this.keysOff = e => { if (!el.contains(e.target)) this.keyHintOff(); };
    document.addEventListener('pointerdown', this.keysOff, true);
    this.root.append(el); this.keysEl = el;
  },
  closeMenu() {
    if (!this.menuEl) return;
    this.menuEl.remove(); this.menuEl = null;
    document.removeEventListener('pointerdown', this.offMenu, true); window.removeEventListener('blur', this.offMenu);
  },
});
