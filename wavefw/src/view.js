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
/* ---------------- tooltips and help ---------------- */
// A control's tooltip: [what it does, in a few words, its keys]; found by its data-act / -sv / -x / -bm / -m value or a
// class (".q"); plugins add theirs (WaveFW.tips.add). A control without one shows its title the same way (boot.js).
const TIPS = {
  '.ct': ['Cursor time: 85.12us, or a number in the unit', ['Enter']], 'act:cset': ['Put the cursor at this time', ['Enter']],
  '.cs': ['Window span around the cursor', ['Enter']], 'act:cshow': ['The window of this span at the cursor'],
  '.cu': ['Unit of the cursor field'], '.su': ['Unit of the span field'],
  'act:out': ['Zoom out', ['o', '-', 'ctrl+wheel']], 'act:in': ['Zoom in', ['i', '+', 'ctrl+wheel']], 'act:fit': ['Show everything', ['f']],
  '.ws': ['Edge style: auto, slanted (WaveDrom), vertical (simulator), square'],
  '.q': ['Fuzzy find: letters in order, a.b for paths', ['/', 'ctrl+F', 'Enter', 'Esc']], 'act:fdock': ['Back into the bar', ['Esc']],
  'act:fcase': ['Match case', ['alt+C']], 'act:fword': ['Full match: the whole name (a.b: the end of the path)', ['alt+W']],
    'act:fre': ['Regular expression (as grep -E; \\< \\> as in vim)', ['alt+R']],
  '.ev': ['The value to find (0x40, \'h40, 64, -3, IDLE)', ['Enter', 'shift+Enter']],
  'act:dopen': ['Open a VCD dump here (or drop it on the viewer)'], 'act:dreload': ['Read the dump again, the view kept'],
  'act:fprev': ['Previous match', ['N', 'shift+Enter']], 'act:fnext': ['Next match', ['n', 'Enter']],
  'act:fhl': ['Found rows in front, the rest dimmed'], 'act:fopen': ['Fold the modules without a match'],
  '.fcol': ['Colour for Paint'], 'act:fpaint': ['Paint the found and highlighted signals'], 'act:funpaint': ['Their own colours back'],
  'act:fcopy': ['Copy the paths of the found rows'],
  'act:sort': ['Sort: off → A→Z → Z→A', ['s']], '.pfx': ['Name prefixes ignored when sorting: i_,o_'],
  'act:expand': ['Open every module', ['zR']], 'act:collapse': ['Fold every module', ['zM']],
  'act:hl': ['Clear the highlight', ['Esc']], 'act:unhide': ['Show the hidden rows again'],
  'act:prev': ['Previous edge of the selected signal', ['shift+Tab', '[e']], '.edge': ['Edge kind: any, rising, falling, a value, X / Z', ['e']],
  'act:next': ['Next edge of the selected signal', ['Tab', ']e']], 'act:mark': ['Bookmark at the cursor', ['m']],
  'act:ssave': ['Save the view to a file (.view.json)'], 'act:sload': ['Load a saved view'],
  'act:help': ['Keys and mouse', ['?']], 'jump': ['Go to this marker'],
  '.mk': ['Highlight: in front, the rest dimmed', ['ctrl+click', 'ctrl+shift+click: every row to here']],
  'bm:json': ['The bookmarks and arrows as JSON for a config'], 'bm:clear': ['Remove this browser\'s bookmarks'],
  'bm:go': ['Go to this bookmark', [']m', '[m']], 'bm:here': ['Move it to the cursor'], 'bm:lift': ['Above its signal, in a lane (or drag the circle up)'],
    'bm:del': ['Delete the bookmark and its arrows'],
  'bm:addar': ['Arrow between the last two bookmarks', ['shift+drag a circle']], 'bm:adel': ['Delete the arrow'],
  '.tm': ['Bookmark time: 250ns, 85.12us', ['Enter']], '.sig': ['Its signal (empty: the time axis)', ['Enter']], '.txt': ['What happens here'],
  '.col': ['Colour'], '.lab': ['Arrow label'], '.from': ['From bookmark'], '.to': ['To bookmark'], '.shape': ['Arrow shape'], '.head': ['Arrow head'],
    '.line': ['Line'],
  'm:zoom': ['Zoom to the range', ['shift+drag', 'middle drag']], 'm:marks': ['Bookmarks at its ends, an arrow with Δ'], 'm:copyd': ['Copy Δ'],
  'm:copyimg': ['The range (else the window) as PNG to the clipboard: the highlighted rows, else the ones on the screen'], 'm:png': ['Save the picture as PNG'],
    'm:svg': ['Save the picture as SVG'],
  'm:c2': ['A second cursor: Δ to the cursor in time and clock cycles', ['shift+click']], 'm:c2x': ['No second cursor', ['Esc']],
  'm:analog': ['The bus as a step plot, three rows high (its radix: signed, float, fixed)'],
  'm:wdjson': ['The range as a WaveDrom file (.json): the highlighted signals, else the ones on the screen, a cell per clock cycle'],
    'm:wdcopy': ['The same WaveDrom to the clipboard'],
  'm:hl': ['Highlight', ['ctrl+click']], 'm:hide': ['Leave it out of the view'], 'm:unhide': ['Show the hidden rows'],
  'm:fold': ['Fold / open this module'], 'm:foldup': ['Fold its module', ['zc']], 'm:zM': ['Fold every module', ['zM']], 'm:zR': ['Open every module', ['zR']],
  'm:mark': ['Bookmark on this signal here', ['m']], 'm:copyname': ['Copy the path', ['yy']], 'm:clear': ['Clear the range', ['Esc', 'ctrl+click']],
  'm:unpaint': ['Its own colour back'],
};
// the help (? in the bar, key ?): the keys and the mouse by what they do; plugins' keys come from their addKey help
const HELP = [
  ['Zoom and move', [[['i', '+'], 'zoom in'], [['o', '-'], 'zoom out'], [['f'], 'show everything'], [['l'], 'the window before the last zoom'],
    [['c'], 'zoom in on the cursor'],
    [['ctrl+wheel', 'pinch'], 'zoom at the pointer'], [['wheel'], 'scroll the rows'], [['shift+wheel', 'drag', '←', '→'], 'pan'],
      [['shift+drag', 'middle drag'], 'zoom into a range'], [['Home', 'End'], 'the start / end'], [['PgUp', 'PgDn'], 'a page of rows']]],
  ['Cursor and edges', [[['click'], 'cursor on a near edge (alt: not) + select the signal'], [['shift+←', 'shift+→'], 'move the cursor'],
    [['Tab', 'shift+Tab'], 'next / previous edge (no signal selected: the focus moves on)'], [[']e', '[e'], 'next / previous edge'], [['e'], 'edge kind']]],
  ['Signals', [[['↑', '↓', 'j', 'k'], 'select the next / previous'], [['shift+click a name'], 'select every signal from the last clicked one'],
    [['gg', 'G'], 'the first / last'], [['ctrl+click', '○'], 'highlight'], [['ctrl+shift+click'], 'highlight every row from the last one to it'],
    [['zM', 'zR'], 'fold / open every module'],
    [['zc', 'zo', 'za'], 'the selected signal\'s module'], [['s'], 'sort'], [['yy', 'ctrl+C'], 'copy the path'],
      [['Esc'], 'reset: search, highlight, selection']]],
  ['Find', [[['/', 'ctrl+F'], 'find (the bar scrolled away: it floats over the waves)'],
    [['alt+C', 'alt+W', 'alt+R'], 'in the field: match case, full match, regular expression'], [['n', 'N', 'Enter'], 'next / previous match'],
    [['*', '#'], 'find the selected name: its next / previous match']]],
  ['Measure and mark', [[['shift+click'], 'a second cursor: Δ to the cursor, in cycles of the clock'], [['x'], 'swap the cursors'],
    [['1', '…', '9'], 'go to bookmark 1 … 9'], [['ctrl+drag'], 'measure a range: Δ, the edges or changes of that signal'],
    [['alt+drag'], 'a box: its time and its signals, then the menu (picture, WaveDrom, colour)'], [['ctrl+click'], 'clear the range'],
    [['right button'], 'a range and the menu: picture, colour, radix, hide'], [['m'], 'bookmark at the cursor'],
    [[']m', '[m'], 'next / previous bookmark'], [['drag a bookmark'], 'move it'], [['shift+drag a bookmark'], 'an arrow to another one']]],
  ['Help', [[['?'], 'this box'], [['hover a button'], 'what it does, its keys']]],
];

const KIND_MARK = { struct: '{}', union: '∪', interface: '⊟' };
// the find group's options: [button, viewer property = setting, label, title, alt+ key code]
const FIND_OPTS = [
  ['fcase', 'findCase', 'Aa', 'Match case (alt+C)', 'KeyC'],
  ['fword', 'findWord', 'Full', 'Full match: a word is the whole name, a.b the end of the full path (alt+W)', 'KeyW'],
  ['fre', 'findRegex', '.*', 'Regular expression on the name or the full path, as grep -E (JavaScript RegExp; \\< \\> as in vim; alt+R)', 'KeyR'],
];

// the bar's tools, one line per kind of work: where you are in time (cursor, zoom, edges, jumps), the signals by name
// (find), times by a condition (sva.js: ƒ expression), the rows and the files (list, edge style, state, assertions)
const TOOL_LINES = { cursor: 'time', view: 'time', edges: 'time', 'go to': 'time', find: 'find', expression: 'expr', list: 'rows', style: 'rows', state: 'rows',
  dump: 'rows', assertions: 'rows' };
const toolLine = (ln, html) => `<div class="tln" data-ln="${ln}">${html}</div>`;

// a WaveDrom document as text: a signal (or a group) per line, as hand-written WaveJSON looks
const wdText = d => '{ "signal": [\n' + d.signal.map(s => Array.isArray(s)
  ? `  [${JSON.stringify(s[0])},\n` + s.slice(1).map(x => '    ' + JSON.stringify(x)).join(',\n') + ']' : '  ' + JSON.stringify(s)).join(',\n') +
  '\n],\n' + Object.keys(d).filter(k => k !== 'signal').map(k => `  ${JSON.stringify(k)}: ${JSON.stringify(d[k])}`).join(',\n') + '\n}';

class Bar {
  // the viewer's markup: the bar (title line, tool groups), the names column and the waves, the lists, the hint
  static html(v) {
    const r = v.root, S = v.S, groups = Object.keys(v.M.groups).length > 0;
    const paint = getComputedStyle(r).getPropertyValue('--wave-paint').trim();   // a token, so a theme may change it
    const jumps = v.jumps.map((j, i) => `<button type="button" data-jump="${i}">${esc(j.label)}</button>`).join('');
    const sort = S.sortButton ?
      (`<button type="button" data-act="sort" title="Sort signals by name (key: s)"></button><input type="text" class="pfx" spellcheck="false" size="8" ` +
        `value="${esc(v.sortIgnore.join(','))}" placeholder="i_,o_" title="Name prefixes ignored when sorting (comma-separated)" aria-label="prefixes ` +
        `ignored when sorting">`) : '';
    const seg = (...parts) => `<span class="seg">${parts.join('')}</span>`, grp = (label, ...parts) =>
      `<span class="tg" data-tg="${label}"><span class="tl">${label}</span>${parts.join('')}</span>`;
    const find = grp('find',
      seg((`<input type="search" class="q" spellcheck="false" autocomplete="off" placeholder="find  /" aria-label="fuzzy find signals" title="Fuzzy find: ` +
          `the letters in order (pxvd finds s_pix_valid); a word with '.' searches full paths (dev.fifo); words separated by spaces must all match. Enter ` +
          `/ n: next, shift+Enter / N: previous, Esc: reset">`),
        ('<span class="cnt"></span><button type="button" data-act="fprev" title="Previous match (N, shift+Enter)">‹</button><button type="button" ' +
            'data-act="fnext" title="Next match (n, Enter)">›</button>')),
      seg(...FIND_OPTS.map(([act, k, label, t]) =>
        `<button type="button" class="fo" data-act="${act}" aria-pressed="${!!S[k]}" title="${esc(t)}">${esc(label)}</button>`)),
      seg(`<button type="button" data-act="fhl" aria-pressed="${!!S.findHighlight}" title="Found rows in front, the rest dimmed">Highlight</button>`,
        `<button type="button" data-act="fopen" aria-pressed="${!!S.findOpen}" title="Every module folded except the ones with a match">Open</button>`),
      seg(`<input type="color" class="fcol" value="${/^#[0-9a-f]{6}$/i.test(paint) ? paint : '#d6336c'}" aria-label="paint colour" title="Colour for Paint">`,
        ('<button type="button" data-act="fpaint" title="Paint the found and the highlighted signals in this colour (none: the selected one; kept in this ' +
          'browser)">Paint</button>')),
      (`<button type="button" data-act="funpaint" title="Back to the signals' own colours" hidden>Unpaint</button><button type="button" data-act="fcopy" ` +
          `title="Copy the full paths of the found rows, one per line">Copy</button><button type="button" class="fx" data-act="fdock" title="Back into the ` +
          `bar (Esc: and reset the search)" aria-label="close">✕</button>`)).replace('class="tg"', 'class="tg find"');
    // cursor: type a time (in the unit chosen, or with its own: 85.12us) and Set; a span and Show: the window around the cursor
    // the edge style of the waves (the "style" setting): kept in this browser; a signal with a style of its own keeps it
    const wstyle =
      (`<select class="ws" aria-label="edge style" title="Edges: auto (wave strings slanted, exact transitions vertical) · slanted (WaveDrom) · vertical (a ` +
        `simulator: narrow bus crossings) · square (no bevel). Kept in this browser; a signal with its own style keeps ` +
        `it">${Object.entries(STYLE_NAMES).map(([k, n]) => `<option value="${k}"${k === S.style ? ' selected' : ''}>${n}</option>`).join('')}</select>`);
    const units = v.M.timed ?
      (`<select class="cu" aria-label="time unit" title="Unit of the two ` +
        `fields">${['ps', 'ns', 'µs', 'ms', 's'].map(u => `<option${u === v.unit() ? ' selected' : ''}>${u}</option>`).join('')}</select>`) :
      '<span class="cyc">cyc</span>';
    const cursor =
      seg(('<input type="text" class="ct" inputmode="decimal" spellcheck="false" aria-label="cursor time" title="Cursor time: a number in the unit shown, or ' +
        'with a unit (85.12us); Enter or Set">'),
        units, '<button type="button" data-act="cset" title="Put the cursor at this time">Set</button>') +
      seg(('<span class="lbl">span</span><input type="text" class="cs" inputmode="decimal" spellcheck="false" aria-label="view span" title="Width of the ' +
          'window; Enter or Show">'),
        units.replace('class="cu"', 'class="su"'),
          '<button type="button" data-act="cshow" title="Window of this span centred on the cursor (key: c)">Show</button>');
    const list = grp('list', sort ? seg(sort) : '', groups ? seg('<button type="button" data-act="expand" title="Expand all groups">Expand</button>',
      '<button type="button" data-act="collapse" title="Collapse all groups">Collapse</button>') : '',
      '<button type="button" data-act="hl" title="Clear the highlight (Esc)" hidden></button>',
        '<button type="button" data-act="unhide" title="Show the rows hidden with the right button\'s menu again" hidden></button>');
    const edges = grp('edges', seg('<button type="button" data-act="prev" title="Previous edge of the selected signal, or of any shown signal ([)">◀</button>',
      (`<select class="edge" aria-label="edge kind" title="Edge kind (e): any, rise, fall, a value, X / ` +
          `Z">${Object.entries(EDGE_KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>`),
      ('<input type="text" class="ev" spellcheck="false" hidden placeholder="0x40, \'h40, 64, IDLE" aria-label="value to find" title="The value to find: ' +
          ('0x40, \'h40, 8\'d64, 64, -3, \'b101, or a text (an enum label); Enter / shift+Enter: the next / previous time the selected signal (none: any ' +
          'shown) becomes it">')),
      '<button type="button" data-act="next" title="Next edge (])">▶</button>'),
        '<button type="button" data-act="mark" title="Bookmark at the cursor, on the selected signal (m)">+ Mark</button>');
    const state = grp('state',
      ('<button type="button" data-act="ssave" title="Save what you did in this viewer to a file: the window, the cursor, the order, the folding, the ' +
        'highlight, the paint, the bookmarks and arrows, the search, the assertions and the ƒ rows">Save</button>'),
      ('<button type="button" data-act="sload" title="Load a saved file into this viewer (what is not in these waves is left out)">Load…</button><input ' +
          'type="file" class="sfile" accept=".json,application/json" hidden>'));
    // dump: a VCD read in the page (Open…, or a file dropped on the viewer), ⟳ reads it again from the disk keeping the view
    const dump = grp('dump',
      ('<button type="button" data-act="dopen" title="Open a VCD dump in this viewer (or drop one on it): its signals by scope, exact ' +
        'transitions">Open…</button>'),
      ('<button type="button" data-act="dreload" title="Read the dump again from the disk; the view, the folding and the bookmarks stay" ' +
          'hidden>⟳</button><input type="file" class="dfile" accept=".vcd,.fst" hidden>'));
    const zoom = seg('<button type="button" data-act="out" title="Zoom out (−)">−</button>',
      '<button type="button" data-act="in" title="Zoom in (+)">+</button>', '<button type="button" data-act="fit" title="Show everything (0)">Fit</button>');
    const hint = 'Wheel: scroll · ctrl+wheel: zoom · shift+wheel / drag: pan · shift or middle drag: zoom to a range · ctrl+drag: measure · ' +
      'alt+drag: a box of time and signals · click: cursor (on a near edge; alt: not) + select a signal · keys on the waves (as in Questa): ' +
      'i o zoom in / out, f full, l last, c in on the cursor · ← → pan, Home End · shift+← → cursor · ↑ ↓ (j k) select, gg G first / last · ' +
      'Tab shift+Tab next / previous edge, e edge kind · / ctrl+F find, n N next / previous match, * # the selected name · ' +
      `m bookmark, ]m [m next / previous · zM zR fold / open all, zc zo the selected module · yy ctrl+C copy${S.sortButton ? ' · s sort' : ''} · ` +
      `Esc reset${groups ? ' · click a module to fold it' : ''} · shift+click a name: select every signal to it · ` +
      '○ or ctrl+click a name: highlight, ctrl+shift+click: every row to it';
    return `<div class="bar"><div class="head"><span
      class="eyebrow">${esc(v.opts.title || v.M.title || 'Waveform').replace(/µ/g, '<span class="mu">µ</span>')}</span><span class="toast" role="status"
        aria-live="polite"></span><span class="cur"></span><button type="button" class="hb" data-act="help" aria-label="keys and mouse">?</button></div>
      <div class="tools">${toolLine('time', grp('cursor', cursor) + grp('view', zoom) + edges + (jumps ? grp('go to', jumps) : ''))}${toolLine('find', find)}${
        toolLine('expr', '')}${toolLine('rows', list + grp('style', wstyle) + state + dump)}</div></div>
      <div class="body"><div class="names"></div><div class="wcol"><canvas tabindex="0" role="application" aria-roledescription="waveform"
        aria-label="waveform: + − zoom, ← → pan, shift+← → move the cursor, ↑ ↓ select a signal, [ ] edges"></canvas></div></div>
      <div class="notes" hidden></div>
      ${S.hint ? `<div class="hint">${esc(v.hintBase = hint)}</div>` : ''}`;
  }
  constructor(v) {
    this.v = v; const r = v.root;
    v.canvas = r.querySelector('canvas'); v.wcol = r.querySelector('.wcol'); v.bodyEl = r.querySelector('.body'); v.namesEl = r.querySelector('.names');
      v.curEl = r.querySelector('.cur');
    v.sortBtn = r.querySelector('button[data-act=sort]'); v.hlBtn = r.querySelector('button[data-act=hl]');
      v.unhideBtn = r.querySelector('button[data-act=unhide]');
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
      const opt = e.altKey && FIND_OPTS.find(o => o[4] === e.code);   // alt+C W R, as in VS Code (by the key's place: any layout)
      if (opt) { e.preventDefault(); v.setFindOpt(opt[1], !v[opt[1]]); }

    });
    v.evEl = r.querySelector('input.ev');
    v.edgeSel.addEventListener('change', () => v.setEdgeKind(v.edgeSel.value, true));
    v.evEl.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); v.edge(e.shiftKey ? -1 : 1); } });
    v.wsEl = r.querySelector('select.ws'); v.wsEl.addEventListener('change', () => v.setStyle(v.wsEl.value));
    r.querySelector('.bar').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.act === 'in') v.zoom(0.5, 0.5);
      else if (b.dataset.act === 'out') v.zoom(2, 0.5);
      else if (b.dataset.act === 'fit') v.fit();
      else if (b.dataset.act === 'sort') v.setSort(SORTS[(SORTS.indexOf(v.sort) + 1) % SORTS.length]);
      else if (b.dataset.act === 'hl') v.highlight(null);
      else if (b.dataset.act === 'unhide') v.unhide();
      else if (b.dataset.act === 'expand') v.expandAll();
      else if (b.dataset.act === 'collapse') v.collapseAll();
      else if (b.dataset.act === 'prev' || b.dataset.act === 'next') v.edge(b.dataset.act === 'next' ? 1 : -1);
      else if (b.dataset.act === 'mark') v.mark();
      else if (b.dataset.act === 'fhl' || b.dataset.act === 'fopen') {
        const k = b.dataset.act === 'fhl' ? 'findHl' : 'findOpen'; v[k] = !v[k]; b.setAttribute('aria-pressed', v[k]); v.find(v.q || '', k === 'findOpen');
      }
      else if (FIND_OPTS.some(o => o[0] === b.dataset.act)) { const k = FIND_OPTS.find(o => o[0] === b.dataset.act)[1]; v.setFindOpt(k, !v[k]); }
      else if (b.dataset.act === 'fpaint') v.paint(v.fcol.value);
      else if (b.dataset.act === 'funpaint') v.unpaint();
      else if (b.dataset.act === 'cset') v.setCursor(v.ctEl.value);
      else if (b.dataset.act === 'cshow') v.showCursor(v.csEl.value);
      else if (b.dataset.act === 'fnext' || b.dataset.act === 'fprev') v.findStep(b.dataset.act === 'fnext' ? 1 : -1);
      else if (b.dataset.act === 'fdock') { v.floatFind(false); v.canvas.focus({ preventScroll: true }); }
      else if (b.dataset.act === 'fcopy') v.copyRows(v.allRows().filter(r => v.found.has(r)));
      else if (b.dataset.act === 'ssave') v.saveState();
      else if (b.dataset.act === 'help') v.help();
      else if (b.dataset.act === 'sload') v.sfile.click();
      else if (b.dataset.act === 'dopen') v.openDump();
      else if (b.dataset.act === 'dreload') v.reloadDump();
      else if (b.dataset.jump !== undefined) { const j = v.jumps[b.dataset.jump]; v.goto(j.t, j.span); }
    });
    v.dfile = r.querySelector('input.dfile');
    v.dfile.addEventListener('change', () => { const f = v.dfile.files[0]; v.dfile.value = ''; if (f) v.openDump(f); });
    v.reloadBtn = r.querySelector('button[data-act=dreload]'); v.reloadBtn.hidden = !v.opts.dumpSrc;
    // a file dropped on the viewer: a VCD replaces its waves, a saved state (.json) is loaded
    // (on the viewer's element, which outlives this viewer when a dump replaces it: removed by destroy() through v.ac)
    const own = { signal: v.ac.signal };
    r.addEventListener('dragover', e => { if ([...(e.dataTransfer.items || [])].some(it => it.kind === 'file') &&
      !e.target.closest('.names, .sva')) { e.preventDefault(); r.classList.add('wv-drop'); } }, own);
    r.addEventListener('dragleave', e => { if (!r.contains(e.relatedTarget)) r.classList.remove('wv-drop'); }, own);
    r.addEventListener('drop', e => {
      r.classList.remove('wv-drop'); const it = [...(e.dataTransfer.items || [])].find(x => x.kind === 'file');
        if (!it || e.target.closest('.names, .sva')) return;
      e.preventDefault(); const f = it.getAsFile(), h = it.getAsFileSystemHandle ? it.getAsFileSystemHandle() : null;
      if (f && /\.json$/i.test(f.name)) v.loadState(f); else if (f) v.openDump(f, h);
    }, own);
    v.sfile = r.querySelector('input.sfile');
    v.sfile.addEventListener('change', () => { const f = v.sfile.files[0]; v.sfile.value = ''; if (f) v.loadState(f); });
    const pfx = r.querySelector('input.pfx');
    if (pfx) pfx.addEventListener('input', () => { v.fitPfx(); v.setSort(v.sort, pfx.value); });
    v.fitPfx();
  }
}
class Names {
  constructor(v) {
    this.v = v;
    const toggle = el => { const id = +el.dataset.g; v.collapsed.has(id) ? v.collapsed.delete(id) : v.collapsed.add(id); v.foldTouched = true; this.render();
      v.draw(); };
    const rowOf = el => v.vis[+el.closest('.row').dataset.r];
    // copying from the names column gives the full paths of the selected rows, one per line (no values, no marks)
    v.namesEl.addEventListener('copy', e => {
      const s = getSelection(); if (!s || s.isCollapsed) return;
      const rows = [...v.namesEl.querySelectorAll('.row[data-r]')].filter(el => s.containsNode(el, true)).map(rowOf).filter(r => r && r.type !== 'space');
      if (!rows.length) return;
      e.preventDefault(); e.clipboardData.setData('text/plain', rows.map(r => r.full || r.name).join('\n')); v.toast(`copied ${rows.length}`);
    });
    v.namesEl.addEventListener('mousedown', e => { if (e.shiftKey) e.preventDefault(); });   // shift(+ctrl)+click: rows, not text
    v.namesEl.addEventListener('click', e => {
      const sel = getSelection(); if (sel && !sel.isCollapsed && v.namesEl.contains(sel.anchorNode)) return;   // selecting text to copy
      const row = e.target.closest('.row'); if (!row || row.classList.contains('space')) return;
      if (e.target.closest('.mk') || e.ctrlKey || e.metaKey) {   // mark / ctrl+click: highlight it; ctrl+shift+click: every row from the last one to it
        const r = rowOf(row);
        if (e.shiftKey && v.hlAnchor && v.vis.includes(v.hlAnchor)) v.highlightRun(v.hlAnchor, r); else { v.toggleHighlight(r); v.hlAnchor = r; }
        v.canvas.focus({ preventScroll: true }); return;
      }
      if (row.classList.contains('grp')) toggle(row);
      // shift+click: every signal from the last one clicked to it, selected
      else if (e.shiftKey && v.selAnchor && v.vis.includes(v.selAnchor)) v.selectRun(v.selAnchor, rowOf(row));
      else { const s = rowOf(row); v.select(v.sel === s && !v.selRun.size ? null : s); }   // a signal name: select it (again: unselect)
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
    const C = compose(v.M, v.S, v.vis, v.bms, v.arrows, picks, v.rowsAll || v.M.rows);
    v.lanes = C.lanes; v.rowsL = C.rows; v.band = C.band; v.hl = C.hl;
    v.laneSig = JSON.stringify([...v.lanes]); v.laneKey = laneKey(v.bms, v.arrows);
    if (v.hlBtn) { v.hlBtn.hidden = !v.picks.size; v.hlBtn.textContent = `Highlight: ${v.picks.size} ✕`; }
    if (v.unhideBtn) { v.unhideBtn.hidden = !v.hiddenRows.size; v.unhideBtn.textContent = `Hidden: ${v.hiddenRows.size} ✕`; }
    if (v.sortBtn) { v.sortBtn.textContent = 'Sort: ' + { none: 'off', asc: 'A→Z', desc: 'Z→A' }[v.sort];
      v.sortBtn.setAttribute('aria-pressed', v.sort !== 'none'); }
    const shape = [v.sort, v.sortIgnore.join(','), v.hdrH, JSON.stringify(v.rowH), v.S.laneHeight, [...v.analogs].join()].join('|');
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
    const at = m ? new Set(m.idx) : null, txt = (s, off) => at ? [...s].map((ch, i) =>
      at.has(off + i) ? `<b class="fm">${esc(ch)}</b>` : esc(ch)).join('') : esc(s);
    // a struct, union, interface scope
    const kdTitle = r.partial ? `: ${r.partial[0]} of its ${r.partial[1]} bits shown, no whole value` :
      r.sig ? `, ${r.sig.width} bits: its whole value on this row` : '';
    const kd = r.type === 'group' && KIND_MARK[r.kind] ? `<span class="kd" title="${r.kind}${kdTitle}">${KIND_MARK[r.kind]}</span>` : '';
    return kd + (p ? `<span class="pfx">${txt(p, 0)}</span>` : '') + txt(rest, p.length);
  }
  build() {
    const v = this.v;
    const alt = r => v.band && v.band.get(r) === 1 ? ' alt' : '', pad = r => `padding-left:${17 + r.depth * 12}px`;
    const mk = '<span class="mk" role="checkbox" tabindex="0" aria-checked="false"></span>';
    v.rowLab = new Map(); v.rowCol = new Map(); v.rowKey = new Map();
    const lab = r => { const t = (r.type === 'group' ? (v.collapsed.has(r.id) ? '▸ ' : '▾ ') : '') + this.label(r); v.rowLab.set(r, t);
      v.rowCol.set(r, v.strokeOf(r) || ''); return t; };
    const col = r => v.strokeOf(r) ? ` style="color:${esc(v.strokeOf(r))}"` : '';
    let vi = -1;
    v.namesEl.setAttribute('role', 'listbox'); v.namesEl.setAttribute('aria-label', 'signals');
    v.namesEl.innerHTML = `<div class="hdr" style="height:${v.hdrH}px"></div>` + v.rowsL.map(r => {
      if (r.type === 'lane') return (`<div class="row lane${alt(r)}" style="height:${v.S.laneHeight * r.ids.length}px" title="arrow labels, lifted ` +
          `bookmarks"></div>`);
      const h = rowHeight(r, v.rowH, v.S.laneHeight), i = ++vi, cls = r.cls ? ' ' + r.cls : '';
      if (r.type === 'space') return `<div class="row space${alt(r)}" data-r="${i}" style="height:${h}px;${pad(r)}"><span
        class="n">${esc(r.name)}</span></div>`;
      if (r.type === 'group') return (`<div class="row grp${cls}" data-r="${i}" style="height:${h}px;${pad(r)}" data-g="${r.id}" tabindex="0" role="button" ` +
          `aria-expanded="true" title="${esc(r.title || r.path)}">${mk}<span ` +
          `class="n"${col(r)}>${lab(r)}</span>${r.sig ? '<span class="v"></span>' : ''}</div>`);
      return (`<div class="row${cls}${alt(r)}" data-r="${i}" role="option" aria-selected="false" tabindex="-1" style="height:${h}px;${pad(r)}">${mk}<span ` +
          `class="n" title="${esc(r.full || r.name)}"${col(r)}>${lab(r)}</span><span class="v"></span></div>`);
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
    const key = `${+dim}${c ?? '-'}${+v.picks.has(r)}${v.strokeOf(r) || ''}${+v.collapsed.has(r.id)}${+v.isSel(r)}${+(r === v.tabRow)}` +
      `${v.found.has(r) ? 'f' : ''}${v.labGen}`;
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
    const lab = (r.type === 'group' ? (open ? '▾ ' : '▸ ') : '') + this.label(r);
    if (v.rowLab.get(r) !== lab) { v.rowLab.set(r, lab); n.innerHTML = lab; }
    const col = v.strokeOf(r) || '';
    if ((v.rowCol.get(r) || '') !== col) { v.rowCol.set(r, col); n.style.color = col; }
    if (r.type === 'group') { if (el.getAttribute('aria-expanded') !== String(open)) el.setAttribute('aria-expanded', open); return; }
    const sel = v.isSel(r);
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
    v.notesEl.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('input')) { e.preventDefault();
      v.canvas.focus({ preventScroll: true }); } });
  }
  render() {
    const v = this.v;
    const el = v.notesEl, M = v.M; el.hidden = !v.bms.length; v.notesGen = (v.notesGen || 0) + 1;
    if (!v.bms.length) { el.innerHTML = ''; return; }
    const sigs = M.rows.filter(r => r.type === 'sig'), byFull = new Map(sigs.map(r => [r.full, r]));
    v.sigList = v.sigList || 'wvf-sigs-' + (++LIST_ID);   // one list of the signals for every bookmark's field
    const acc = getComputedStyle(v.root).getPropertyValue('--accent').trim(), hex = c =>
      /^#[0-9a-f]{6}$/i.test(c || '') ? c : /^#[0-9a-f]{6}$/i.test(acc) ? acc : '#b5551b';
    const opt = (v, label, cur) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(label)}</option>`;
    const nums = cur => v.bms.map(o => opt(String(o.n), String(o.n), String(cur))).join('');
    el.innerHTML = `<div class="nh"><b>Bookmarks</b><span
      class="muted">click a number to go there · drag a circle on the waves to move it, shift+drag to another one for an arrow · kept in this browser</span>
      <button type="button" data-bm="json">JSON</button><button type="button" data-bm="clear"
        title="Remove the bookmarks of this browser (the page's own come back on reload)">Clear</button></div><ol class="bms">` +
      v.bms.map(b => { const s = byFull.get(b.signal);
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
          title="Above the signal, in the lane over its row (or drag the circle up there)"${b.signal ? '' : ' disabled'}>↥</button>
        <input type="color" class="col" value="${hex(b.color)}" aria-label="bookmark ${b.n} colour" title="Colour">
        <input type="text" class="txt" value="${esc(b.text)}" placeholder="describe the event" aria-label="bookmark ${b.n} text">
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
      '</ol><textarea class="json" readonly hidden aria-label="bookmarks as JSON"></textarea>' +
      `<datalist id="${v.sigList}">${sigs.map(r => `<option value="${esc(r.full)}">`).join('')}</datalist>`;
  }
  click(e) {
    const v = this.v;
    const b = e.target.closest('button[data-bm]'); if (!b) return;
    const li = b.closest('li'), n = li ? +li.dataset.n : NaN, bm = v.bms.find(x => x.n === n), act = b.dataset.bm;
    if (act === 'go' && bm) { v.cursor = bm.t; if (bm.t < v.t0 || bm.t > v.t0 + v.span) v.t0 = v.clamp(bm.t - v.span / 2);
      if (bm.signal) v.sel = v.M.rows.find(r => r.full === bm.signal) || v.sel; v.renderNames(); v.draw(); }
    else if (act === 'here' && bm) { bm.t = v.cursor; v.changed(true); }
    else if (act === 'lift' && bm) { bm.lift = !bm.lift && !!bm.signal; v.changed(true); }
    else if (act === 'del') { v.bms = v.bms.filter(x => x.n !== n); v.arrows = v.arrows.filter(a => a.from !== n && a.to !== n); v.changed(true); }
    else if (act === 'adel') { v.arrows.splice(+li.dataset.a, 1); v.changed(true); }
    else if (act === 'addar') { const k = v.bms.length; v.arrows.push(arNorm([{ from: v.bms[k - 2].n, to: v.bms[k - 1].n }])[0]); v.changed(true); }
    else if (act === 'clear') { v.bms = []; v.arrows = []; try { localStorage.removeItem(v.bmKey); } catch (err) { /* ignore */ } this.render(); v.draw(); }
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
const STATE_VERSION = 2;   // a saved viewer state (state()): 2 has range and edge
const RISES = new WeakMap();   // a clock row -> the times it rises (the second cursor counts cycles with it)
class WaveView {
  constructor(root, model, opts = {}) {
    this.root = root; this.M = parse(model); this.opts = opts;
    const M = this.M;
    applyLook(root, opts.theme ?? M.theme, Object.assign({}, M.colors, opts.colors));
    this.storeId = this.storeName();
    this.lookKey = 'wavefw.look:' + this.storeId; this.local = this.loadLook();   // the bar's own layer of the settings (the edge style)
    this.restyle(false); this.collapsed = foldSet(M, this.S.fold);
    this.picks = hlPick(M, this.S.highlight); this.hlFrom = JSON.stringify(this.S.highlight ?? null);
    this.selRun = new Set(); this.selAnchor = null;   // shift+click: a run of selected signals (selectRun)
    this.found = new Map(); this.findPicks = new Map(); this.findHl = this.S.findHighlight; this.findOpen = this.S.findOpen;   // fuzzy find
    for (const [, k] of FIND_OPTS) this[k] = !!this.S[k];   // its options: the case, the whole name, a regular expression
    this.paintKey = 'wavefw.paint:' + this.storeId;
    this.painted = new Map(); this.loadPaint();
    // the menu's radix per signal, hidden rows
    this.rowsKey = 'wavefw.rows:' + this.storeId; this.radixes = new Map(); this.analogs = new Map(); this.hiddenRows = new Set(); this.loadRows();
    this.t0 = M.t0; this.span = M.t1 - M.t0;
    this.minSpan = opts.minSpan ?? (M.timed ? Math.max(this.span / 1e6, 10) : 0.5);
    this.cursor = opts.cursor ?? M.cursor ?? M.t0;
    this.markers = (opts.markers || []).concat(M.markers);
    this.jumps = opts.jumps || M.jumps || (this.markers.length && this.markers.length <= 6
      ? this.markers.map(m => ({ label: '→ ' + m.label, t: m.t, span: this.span / 5 })) : []);
    this.sel = null; this.edgeKind = 'any';   // selected signal row (edge search, bookmarks), edge kind
    this.extraJSON = [];   // plugins: () -> '"key": …' lines for the bookmarks JSON (or null)
    this.extraState = [];   // plugins: {key, get() -> a JSON value, set(value) (may be async)}: their part of the saved state
    this.extraRows = [];   // plugins: rows under a group (withExtra)
    this.extraPicks = new Map();   // plugins: rows highlighted, row -> a token ('hl8': --wave-hl8) or a colour index; Esc clears (then wavefw:reset)
    this.keys = {};   // plugins: key -> fn(event) on the waves (addKey)
    this.rowMarks = new Map(); this.rowTitles = new Map();   // plugins: classes and tooltips of name rows (rowClass, rowTitle)
    const hints = this.hints = [];   // plugins: lines of the hint under the waves; hints.push() shows them
    hints.push = (...a) => { const n = Array.prototype.push.apply(hints, a); this.renderHint(); return n; };
    this.bmKey = 'wavefw.bookmarks:' + this.storeId;
    // every listener outside the viewer's own child elements (its root, the window, the document) is registered with
    // this signal: destroy() removes them all (a dump opened again on the same element left the old ones running)
    this.ac = new AbortController();
    Object.assign(this, this.loadBookmarks()); root.waveView = this;   // this.bms, this.arrows
    this.build(); this.fit();
    if (opts.from != null || opts.to != null) { // initial view window (Fit still shows everything)
      const a = opts.from ?? M.t0, b = opts.to ?? M.t1;
      this.span = Math.min(Math.max(b - a, this.minSpan), M.t1 - M.t0); this.t0 = this.clamp(a); this.draw();
    }
    this.ro = new ResizeObserver(() => this.draw()); this.ro.observe(this.wcol);
    // the canvas is only as tall as the visible part of the rows (sticky in its column): redraw when that part moves
    this.onScroll = () => { if (!this.raf && this.lay && this.lay.H > this.hc + 1) this.raf = requestAnimationFrame(() =>
      { this.raf = 0; if (this.root.isConnected) this.draw(); }); };
    const own = { signal: this.ac.signal };
    window.addEventListener('scroll', this.onScroll, { passive: true, ...own }); window.addEventListener('resize', this.onScroll, own);
    this.bodyEl.addEventListener('scroll', this.onScroll, { passive: true, ...own });
    VIEWS.add(this);
    for (const p of PLUGINS) try { p(this); } catch (e) { console.error('wavefw plugin:', e); }
  }
  // what this viewer's bookmarks, paint and bindings are stored under in this browser: the page, then opts.key, the id,
  // the data-wave reference or the title; several viewers of one data-wave (a bench and its lazy cards) are told apart by
  // their place among them in the page (the first keeps the plain name). Two live viewers with one name: a warning.
  storeName() {
    const r = this.root, o = this.opts, ref = r.dataset.wave;
    let id = location.pathname + ':' + (o.key || r.id || ref || this.M.title);
    if (!o.key && !r.id && ref) { const k = [...document.querySelectorAll('[data-wave]')].filter(e => e.dataset.wave === ref).indexOf(r);
      if (k > 0) id += '#' + (k + 1); }
    for (const v of VIEWS) if (v.storeId === id &&
      v.root.isConnected) console.warn(`wavefw: two viewers store their bookmarks as "${id}": give one an id or opts.key`);
    return id;
  }
  // settings from all layers; a global WaveFW.configure() calls this again on every viewer
  restyle(redraw = true) {
    const S = this.S = settings(GLOBAL, this.M.cfg, this.opts, this.local);
    this.groupStroke = groupPaint(this.M, S.groupColors);
    for (const [name, v] of styleVars(Object.assign({}, this.M.cfg, this.opts))) this.root.style.setProperty(name, v);
    this.rowH = { sig: S.rowHeight, group: S.groupHeight, space: S.spaceHeight }; this.hdrH = S.headerHeight;
    this.sort = S.sort; this.sortIgnore = S.sortIgnore;
    this.root.style.setProperty('--wv-dim', S.dim);
    this.root.classList.toggle('wv-scroll', S.maxHeight != null && S.maxHeight !== '');   // own scroll bar, bar stays in view
    const hlFrom = JSON.stringify(S.highlight ?? null);   // a new "highlight" setting (configure) replaces the picks
    if (redraw && hlFrom !== this.hlFrom) { this.hlFrom = hlFrom; this.picks = hlPick(this.M, S.highlight); }
    if (redraw && this.qEl && this.q) this.find(this.q);
    if (this.wsEl) this.wsEl.value = S.style;
    if (redraw) { const i = this.root.querySelector('input.pfx'); if (i) i.value = S.sortIgnore.join(','); this.fitPfx(); this.renderNames(); this.draw();
      this.settingsChanged(); }
  }
  build() {
    const r = this.root; r.classList.add('wv');
    r.innerHTML = Bar.html(this);
    this.bar = new Bar(this);
    this.names = new Names(this);
    this.wheelInput(this.canvas); this.pointerInput(this.canvas); this.keyInput(this.canvas);
    // Esc anywhere in the viewer (waves, find field, names) except the bookmark fields: back to no search, no highlight,
    // no selected signal; the view (opened modules, scroll, time) stays
    this.onActive = () => { ACTIVE.view = this; };
    r.addEventListener('pointerdown', this.onActive, { capture: true, signal: this.ac.signal });
    r.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || e.target.closest('.notes')) return;
      e.preventDefault(); this.reset(); this.floatFind(false);
      if (e.target === this.qEl) this.canvas.focus({ preventScroll: true });
    }, { signal: this.ac.signal });
    this.notes = new Notes(this);
    this.renderNames(); this.renderNotes();
  }
  wheelInput(c) {
    // wheel by its size: a mouse notch (100 px) zooms ×1.22, a trackpad's small steps zoom smoothly, ctrl+wheel (a pinch)
    // zooms faster; a horizontal swipe or shift+wheel pans by the pixels moved. deltaMode: lines (16 px) or pages.
    // the wheel as in Questa: it scrolls the rows (the page, or the viewer's own scroll bar), ctrl+wheel (a pinch) zooms
    // at the pointer by how far it turned, shift+wheel (a sideways swipe) pans; the setting wheel: "zoom" zooms without ctrl
    c.addEventListener('wheel', e => {
      const u = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? c.clientHeight || 400 : 1;
      let dx = e.deltaX * u, dy = e.deltaY * u;
      if (e.shiftKey && !dx) { dx = dy; dy = 0; }
      if (Math.abs(dx) > Math.abs(dy)) { e.preventDefault(); this.t0 = this.clamp(this.t0 + dx / this.pxPerT()); this.invalidate(); }
      else if (dy && (e.ctrlKey || this.S.wheel === 'zoom')) {
        e.preventDefault(); this.markView(true);
        const pinch = e.ctrlKey && e.deltaMode === 0 && Math.abs(dy) < 50;   // a trackpad pinch: small steps, many of them
        this.zoom(Math.exp(dy * (pinch ? 0.01 : 0.002)), this.frac(e), true);
      }
    }, { passive: false });
  }
  // the pointer on the waves: the cursor, a pan, a zoom range, a measured range, a box, a bookmark moved or an arrow drawn
  pointerInput(c) {
    // the middle button (Questa): drag over a time range to zoom into it
    c.addEventListener('mousedown', e => { if (e.button === 1) e.preventDefault(); });   // no autoscroll, no paste
    let drag = null;
    const local = e => { const b = c.getBoundingClientRect(); return [e.clientX - b.left, e.clientY - b.top + (this.oy || 0)]; };   // layout y
    // on a bookmark: drag moves it (time + signal row), shift+drag draws an arrow to another bookmark; elsewhere drag pans
    c.addEventListener('contextmenu', e => { if (this.S.contextMenu) e.preventDefault(); });   // the viewer's menu instead
    c.addEventListener('pointerdown', e => {
      if (e.button === 1) { const [x] = local(e); drag = { zoom: x, x: e.clientX, y: e.clientY }; c.setPointerCapture(e.pointerId); return; }
      const [x, y] = local(e), bm = e.button === 0 && this.bmAt(x, y);
      // shift+drag (not from a bookmark: that draws an arrow): zoom into the range dragged over, as the middle button
      if (e.button === 0 && e.shiftKey && !bm && !e.ctrlKey && !e.metaKey) { drag = { zoom: x, x: e.clientX, y: e.clientY, c2: [x, y, e.altKey] };
        c.setPointerCapture(e.pointerId); return; }
      // a measured range: ctrl+drag or the right button (then the menu), its ends on the edges of the signal under the
      // pointer (alt: not), its Δ counted on that signal
      if ((e.button === 2 && this.S.contextMenu) || (e.button === 0 && (e.ctrlKey || e.metaKey) && !bm)) {
        drag = { range: this.pickTime(x, y, e.altKey), menu: e.button === 2, x: e.clientX, y: e.clientY, moved: false, free: e.altKey, row: this.rowOfY(y) };
        c.setPointerCapture(e.pointerId); return;
      }
      if (e.button !== 0) return;
      // alt+drag: a box over time and rows — its time is the range, its signals the selection; then the menu (the picture,
      // WaveDrom, colour … of those signals); alt+click: the cursor without the snap
      if (e.altKey && !bm && !e.shiftKey && !e.ctrlKey && !e.metaKey) { drag = { box: [x, y], x: e.clientX, y: e.clientY, moved: false };
        c.setPointerCapture(e.pointerId); return; }
      // lay: the rows as they were (a lane coming or going does not move them under the pointer)
      drag = { x: e.clientX, y: e.clientY, t0: this.t0, moved: false, bm, arrow: bm && e.shiftKey, free: e.altKey, lay: this.lay };
      c.setPointerCapture(e.pointerId);
    });
    c.addEventListener('pointermove', e => {
      const [x, y] = local(e);
      if (!drag) {
        const bm = this.bmAt(x, y), o = !bm && (this.lay || []).find(o => y >= o.y && y < o.y + o.h), tip = o && o.row.tip ? o.row.tip(x, y - o.y, this) : '';
        // the value under the pointer (a struct's row: its whole value)
        const vr = o && (o.row.sig || o.row), val = !bm && !tip && vr && vr.type === 'sig' && vr.tr ? this.valueTip(vr, this.t0 + x / this.pxPerT()) : '';
        c.style.cursor = bm ? 'grab' : tip ? 'pointer' : ''; c.title = bm ? `Bookmark ${bm.n}: drag to move it, shift+drag to another bookmark for an arrow` :
          tip || val; return;
      }
      if (drag.zoom != null) { this.zband = [drag.zoom, x].map(px => this.t0 + px / this.pxPerT()); this.draw(); return; }
      if (drag.box) {
        if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3) drag.moved = true;
        if (drag.moved) this.boxSelect(drag.box[0], drag.box[1], x, y);
        return;
      }
      if (drag.range != null) {
        if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 3) drag.moved = true;
        if (drag.moved) { this.setRange(drag.range, this.pickTime(x, y, drag.free), drag.row); }
        return;
      }
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (Math.hypot(dx, dy) > 3) drag.moved = true;
      if (!drag.moved) return;
      if (drag.arrow) { this.rubber = { from: drag.bm.n, x, y }; this.draw(); }
      else if (drag.bm) { c.style.cursor = 'grabbing'; this.moveBookmark(drag.bm, x, y, drag.lay); }
      else { this.t0 = this.clamp(drag.t0 - dx / this.pxPerT()); this.invalidate(); }   // a pan: one draw per frame, not per move event
    });
    c.addEventListener('pointerup', e => {
      const [x, y] = local(e);
      if (drag && drag.range != null) {   // a range ends; the right button opens the menu (on it, or on the signal under it)
        const d = drag; drag = null;
        if (!d.moved && !d.menu) this.setRange(null);   // ctrl+click: no range
        if (d.menu) this.menu(e.clientX, e.clientY, d.row, d.range);
        return;
      }
      if (drag && drag.box) {   // the box: the menu on its signals; a click: the cursor here, not snapped
        const d = drag; drag = null; this.box = null;
        if (d.moved) { this.draw(); this.menu(e.clientX, e.clientY, this.sel, this.cursor); return; }
        const row = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
        this.cursor = this.pickTime(x, y, true); this.range = null; this.selRun = new Set();
        if (row && row.row.type === 'sig' && row.row.tr) this.sel = this.selAnchor = row.row;
        this.renderNames(); this.draw(); return;
      }
      if (drag && drag.zoom != null) {   // the middle button released: the range dragged over (4 px at least) fills the view
        const b = this.zband, c2 = drag.c2; this.zband = null; drag = null;
        if (b && Math.abs(b[1] - b[0]) * this.pxPerT() >= 4) this.zoomTo(Math.min(...b), Math.max(...b));
        else if (c2) this.setCursor2(this.pickTime(...c2));   // shift+click: the second cursor (on an edge, alt: not)
        else this.draw();
        return;
      }
      if (drag && drag.moved && drag.arrow) {
        const to = this.bmAt(x, y); this.rubber = null;
        if (to && to.n !== drag.bm.n) { this.arrows.push(arNorm([{ from: drag.bm.n, to: to.n }])[0]); this.saveBookmarks(); this.renderNotes(); }
        this.draw();
      } else if (drag && drag.moved && drag.bm) { c.style.cursor = 'grab'; this.saveBookmarks(); this.renderNotes(); }
      else if (drag && !drag.moved) {
        const hit = this.bmAt(x, y), mid = !hit && this.bmGeo && this.bmGeo.mids.find(([, mx, my]) => Math.hypot(mx - x, my - y) <= 10);
        if (hit) { this.cursor = hit.t; this.draw(); this.notesEl.querySelector(`li[data-n="${hit.n}"] input.txt`)?.focus(); }
        else if (mid) this.notesEl.querySelector(`li[data-a="${mid[0]}"] input.lab`)?.focus();
        else {   // cursor here (on an edge of the signal under the pointer within cursorSnap px, alt: not), the signal row
          // under the pointer becomes the selected one (a row of a plugin may take the click)
          const row = (this.lay || []).find(o => y >= o.y && y < o.y + o.h);
          if (!(row && row.row.click && row.row.click(x, y - row.y, this))) {
            this.cursor = this.pickTime(x, y, drag.free); this.range = null; this.selRun = new Set();
            if (row && row.row.type === 'sig' && row.row.tr) this.sel = this.selAnchor = row.row;
            this.renderNames(); this.draw();
          }
        }
      }
      drag = null;
    });
    c.addEventListener('pointercancel', () => { drag = null; if (this.rubber || this.zband || this.box) { this.rubber = this.zband = this.box = null;
      this.draw(); } });
  }
  keyInput(c) {
    // The keys on the waves: navigation as in Questa's wave window, the lists and the text as in vim. Two-key sequences
    // (gg, zR, yy, ]f …) start with g z y [ ]: the second key within a second
    c.addEventListener('keydown', e => {
      const k = e.key, ctl = e.ctrlKey || e.metaKey; let h = true;
      if (['Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(k)) return;   // a modifier alone: a sequence goes on (z, shift+M)
      if (e.altKey || (ctl && !['c', 'C', 'f', 'F'].includes(k))) return;   // ctrl+S, ctrl+M … stay the browser's
      // ctrl+F: find (Questa), ctrl+C: copy (nothing to copy: the browser's)
      if (ctl) { if (k === 'f' || k === 'F' ? (this.focusFind(), true) : this.copyKey()) e.preventDefault(); return; }
      const pre = this.kpre && Date.now() - this.kpre.t < 1000 ? this.kpre.k : ''; this.kpre = null;
      if (pre && this.seq(pre + k)) { e.preventDefault(); return; }
      if (!pre && 'gzy[]'.includes(k) && k.length === 1) { this.kpre = { k, t: Date.now() }; e.preventDefault(); return; }
      const sigStep = d => { const sigs = this.vis.filter(r => r.type === 'sig' && r.tr), i = sigs.indexOf(this.sel);
        this.select(sigs[Math.min(Math.max(i < 0 ? 0 : i + d, 0), sigs.length - 1)] || null); };
      if (k === 'i' || k === 'I' || k === '+' || k === '=') { this.markView(); this.zoom(0.5, 0.5); }
      else if (k === 'o' || k === 'O' || k === '-') { this.markView(); this.zoom(2, 0.5); }
      else if (k === 'f' || k === 'F') { this.markView(); this.fit(); }
      else if (k === 'l' || k === 'L') this.zoomLast();
      else if (k === 'c' || k === 'C') { this.markView(); this.showCursor(Math.max(this.span / 2, this.minSpan)); }   // zoom in on the cursor (Questa)
      // the next / previous transition of the selected signal (Questa); none selected (Esc): the focus moves on
      else if (k === 'Tab' && this.sel) this.edge(e.shiftKey ? -1 : 1);
      else if (k === 'e') { const ks = Object.keys(EDGE_KINDS); this.setEdgeKind(ks[(ks.indexOf(this.edgeKind) + 1) % ks.length]); }
      else if (k === 'Home' || k === 'End') { this.markView(); this.t0 = this.clamp(k === 'Home' ? this.M.t0 : this.M.t1); this.draw(); }
      else if (k === 'PageDown' || k === 'PageUp') this.pageRows(k === 'PageDown' ? 1 : -1);
      else if (k === 'ArrowDown' || k === 'j') sigStep(1);
      else if (k === 'ArrowUp' || k === 'k') sigStep(-1);
      else if (k === 'G') { const sigs = this.vis.filter(r => r.type === 'sig' && r.tr); this.select(sigs[sigs.length - 1] || null); }
      else if ((k === 'ArrowLeft' || k === 'ArrowRight') && e.shiftKey) this.nudge(k === 'ArrowRight' ? 1 : -1);   // the cursor, a 100th of the view
      else if (k === 'ArrowLeft' || k === 'ArrowRight') { this.t0 = this.clamp(this.t0 + this.span * (k === 'ArrowRight' ? 0.2 : -0.2)); this.invalidate(); }
      else if (k === '/') this.focusFind();
      else if ((k === 'n' || k === 'N') && this.found.size) this.findStep(k === 'n' ? 1 : -1);   // like vim
      // the selected name (vim: the word under the cursor)
      else if (k === '*' || k === '#') { if (this.sel) { this.qEl.value = this.sel.name; this.find(this.sel.name); this.findStep(k === '*' ? 1 : -1); } }
      else if (k === 'm') this.mark();
      else if (/^[1-9]$/.test(k)) this.goMark(+k);   // the bookmark of that number
      else if (k === 'x' && this.cursor2 != null) { [this.cursor, this.cursor2] = [this.cursor2, this.cursor]; this.draw(); }   // swap the cursors
      else if (k === '?') this.help();
      else if (k === 's' && this.S.sortButton) this.setSort(SORTS[(SORTS.indexOf(this.sort) + 1) % SORTS.length]);
      else if (k === 'Escape') h = false;   // handled by the viewer (reset)
      else if (this.keys[k]) this.keys[k](e);
      else h = false;
      if (h) e.preventDefault();
    });
  }
  fitPfx() { const i = this.root.querySelector('input.pfx'); if (i) i.style.width = Math.max(7, i.value.length + 2) + 'ch'; }
  // every row in display order (the model's and the plugins'), and the ones not folded away
  allRows() {
    const rows = withExtra(orderRows(this.M.rows, this.sort, this.sortIgnore, this.S.groupOrder), this.extraRows, this.M, this);
    if (!this.hiddenRows.size) return (this.rowsAll = rows);
    const H = this.hiddenRows, ids = new Set(Object.values(this.M.groups).filter(g => H.has(g.path)).map(g => g.id));   // a hidden module: all of it
    return (this.rowsAll = rows.filter(r => !(r.type !== 'space' && r.type !== 'lane' && r.full && H.has(r.full)) && !r.anc.some(id => ids.has(id))));
  }
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
  // every signal and module shown from row a to row b (either way round) highlighted too (ctrl+shift+click a name)
  // shift+click a name: the signals from a (the last one clicked) to b in display order are selected (no dimming, as one
  // selected signal); b is the selected one for the keys; the right button's colour, radix, hide and Paint take them all
  selectRun(a, b) {
    const i = this.vis.indexOf(a), j = this.vis.indexOf(b); if (i < 0 || j < 0) return this.select(b);
    this.selRun = new Set(this.vis.slice(Math.min(i, j), Math.max(i, j) + 1).filter(r => r.type === 'sig' && r.tr));
    this.sel = b && b.type === 'sig' && b.tr ? b : this.sel; this.renderNames(); this.draw(); return this;
  }
  // alt+drag from (x0, y0) to (x1, y1), layout px: the box drawn; its time the range (not snapped), the signal rows it
  // touches the selection (as shift+click), the last one the selected signal
  boxSelect(x0, y0, x1, y1) {
    const T = px => this.t0 + px / this.pxPerT(), ya = Math.min(y0, y1), yb = Math.max(y0, y1);
    this.box = [Math.min(x0, x1), ya, Math.max(x0, x1), yb];
    const rows = (this.lay || []).filter(o => o.y + o.h > ya && o.y < yb && o.row.type === 'sig' && o.row.tr).map(o => o.row);
    this.selRun = new Set(rows); this.sel = rows[rows.length - 1] || this.sel; if (rows.length) this.selAnchor = rows[0];
    this.setRange(T(Math.min(x0, x1)), T(Math.max(x0, x1)), rows[0] || null);   // draws
    this.renderNames(); return this;
  }
  isSel(r) { return r === this.sel || (!!this.selRun && this.selRun.has(r)); }
  highlightRun(a, b) {
    if (typeof a === 'string') a = this.vis.find(r => r.full === a); if (typeof b === 'string') b = this.vis.find(r => r.full === b);
    const i = this.vis.indexOf(a), j = this.vis.indexOf(b); if (i < 0 || j < 0) return this;
    for (const r of this.vis.slice(Math.min(i, j), Math.max(i, j) + 1)) if ((r.type === 'sig' || r.type === 'group') && !this.picks.has(r)) this.picks.set(r,
      this.picks.size % HL_N);
    this.renderNames(); this.draw(); return this;
  }
  // fuzzy find: rows matching every word; options: found rows in front (findHl), only their modules open (findOpen)
  // restore: give back the folding from before the search (the Open option switched off); clearing the search keeps the
  // modules it opened, so the view stays where it is
  find(q, restore = false, keep = null) {
    this.q = q;
    const s = String(q || '').trim(), re = this.findRegex && s ? this.findRe(s) : null, badRe = this.findRegex && !!s && !re;
    const terms = this.findRegex ? (re ? [s] : []) : s.split(/\s+/).filter(w => w.replace(/\./g, ''));   // "." alone is no query
    const o = { cs: this.findCase, full: this.findWord, re };
    this.found = new Map();
    if (terms.length) for (const r of this.allRows()) { if (r.type !== 'space') { const m = findRow(r, terms, this.M, o); if (m) this.found.set(r, m); } }
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
    if (this.cntEl) { const n = this.found.size; this.cntEl.textContent = badRe ? 'bad regex' : terms.length ? (n ? `${n} found` : 'no match') : '';
      this.cntEl.classList.toggle('none', badRe || (!!terms.length && !n)); }
    this.renderNames(); this.draw();
    if (moved) { const d = this.rowTop(moved[0]) - moved[1]; if (d) { if (this.root.classList.contains('wv-scroll')) this.bodyEl.scrollTop += d;
      else window.scrollBy(0, d); this.draw(); } }
    return this;
  }
  // the .* option: the query as a JavaScript RegExp, vim's \< \> as \b, anchored with Full, the case as Aa; bad: null
  findRe(s) {
    let src = s.replace(/\\([<>])/g, '\\b'); if (this.findWord) src = `^(?:${src})$`;
    try { return new RegExp(src, this.findCase ? '' : 'i'); } catch (e) { return null; }
  }
  setFindOpt(k, on) {   // findCase, findWord, findRegex: the button and the search again
    if (!FIND_OPTS.some(o => o[1] === k)) return this;
    this[k] = !!on; this.root.querySelector(`button[data-act=${FIND_OPTS.find(o => o[1] === k)[0]}]`)?.setAttribute('aria-pressed', this[k]);
    return this.find(this.q || '');
  }
  rowTop(r) { const k = this.vis ? this.vis.indexOf(r) : -1, el = k >= 0 && this.namesEl.querySelector(`.row[data-r="${k}"]`);
    return el ? el.getBoundingClientRect().top : null; }
  reset() { // Esc: search, highlight and the selected signal go; scroll and time stay, the folding from before the search is back
    const keep = this.fiRow || this.sel;
    if (this.qEl) this.qEl.value = '';
    this.picks = new Map(); this.sel = null; this.selRun = new Set(); this.extraPicks = new Map(); this.range = null; this.cursor2 = null; this.closeMenu();
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
    const show = (inp, sel, t) => { if (force || document.activeElement !== inp) inp.value = String(Number((t / (this.M.timed &&
      sel ? UNIT_PS[sel.value] : 1)).toPrecision(7))); };
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
      document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); done(); } catch (e) { /* no clipboard */ } ta.remove();
        this.canvas.focus({ preventScroll: true }); };
    try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
    this.copied = text; return this;
  }
  toast(msg) { const t = this.root.querySelector('.bar .toast'); if (!t) return; t.textContent = msg; clearTimeout(this.toastT);
    this.toastT = setTimeout(() => { t.textContent = ''; }, 1600); }
  // the found and the highlighted signals (a highlighted module: its signals; neither: the selected one) take this colour
  // (trace, outline, name); kept in this browser
  paint(color) {
    this.paintRows().forEach(r => this.painted.set(r.full, color));
    this.savePaint(); this.renderNames(); this.draw(); return this;
  }
  paintRows() {
    const rows = this.M.rows.filter(r => r.type === 'sig' && (this.found.has(r) || this.picks.has(r) || this.selRun.has(r) ||
      r.anc.some(id => this.picks.has(this.M.groups[id]))));
    return rows.length ? rows : this.sel && this.sel.type === 'sig' ? [this.sel] : [];
  }
  unpaint() { this.painted.clear(); this.savePaint(); this.renderNames(); this.draw(); return this; }
  // the radix of a signal (a row or its path; one of RADIX, null: the page's) and hidden rows (signals, modules: all of
  // them), from the right button's menu; kept in this browser and in the saved state
  setRadix(row, radix, quiet = false) {   // quiet: no save / render / draw (a loop that does them once after)
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row);
    if (!row || row.type !== 'sig') return this;
    if (!('radix0' in row)) row.radix0 = row.radix;
    if (isRadix(radix)) { row.radix = radix; this.radixes.set(row.full, radix); } else { row.radix = row.radix0; this.radixes.delete(row.full); }
    this.valsAt = null; if (!quiet) { this.saveRows(); this.renderNames(); this.draw(); } return this;
  }
  // a bus drawn analog (a step plot, n rows high; true: 3, 0 / false: as a bus; null: the page's own), kept like the radix
  setAnalog(row, n, quiet = false) {   // a bus only: a 1-bit signal has no values to plot (null: back to its own)
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row);
    if (!row || row.type !== 'sig' || (n && (row.width || 1) < 2 && row.kind !== 'real')) return this;
    if (!('analog0' in row)) row.analog0 = row.analog;
    if (n == null) { row.analog = row.analog0; this.analogs.delete(row.full); } else { row.analog = n || false; this.analogs.set(row.full, n || false); }
    if (!quiet) { this.saveRows(); this.renderNames(); this.draw(); } return this;
  }
  hide(rows) {   // rows or paths
    for (const r of [].concat(rows)) { const p = typeof r === 'string' ? r : r && (r.full || r.path); if (p) this.hiddenRows.add(p); }
    if (this.sel && !this.allRows().includes(this.sel)) this.sel = null;
    this.saveRows(); this.renderNames(); this.draw(); return this;
  }
  unhide(paths) {   // these paths (none: every hidden row) back
    if (paths) [].concat(paths).forEach(p => this.hiddenRows.delete(p)); else this.hiddenRows.clear();
    this.saveRows(); this.renderNames(); this.draw(); return this;
  }
  loadRows() {
    let o = {};
    try { o = JSON.parse(localStorage.getItem(this.rowsKey) || '{}') || {}; } catch (e) { /* no storage */ }
    this.hiddenRows = new Set(Array.isArray(o.hidden) ? o.hidden : []);
    for (const [p, n] of Object.entries(o.analog || {})) { const r = this.M.rows.find(x => x.type === 'sig' && x.full === p);
      if (r) { if (!('analog0' in r)) r.analog0 = r.analog; r.analog = n || false; this.analogs.set(p, n); } }
    for (const [p, rx] of Object.entries(o.radix || {})) { const r = this.M.rows.find(x => x.type === 'sig' && x.full === p);
      if (r && isRadix(rx)) { r.radix0 = r.radix; r.radix = rx; this.radixes.set(p, rx); } }
  }
  saveRows() {
    try {
      if (this.radixes.size || this.hiddenRows.size || this.analogs.size) localStorage.setItem(this.rowsKey,
        JSON.stringify({ radix: Object.fromEntries(this.radixes), hidden: [...this.hiddenRows], analog: Object.fromEntries(this.analogs) }));
      else localStorage.removeItem(this.rowsKey);
    } catch (e) { /* private mode */ }
  }
  loadPaint() {
    try { for (const [k, c] of Object.entries(JSON.parse(localStorage.getItem(this.paintKey) || '{}'))) this.painted.set(k, c); }
    catch (e) { /* no storage */ }
  }
  // the edge style of the waves ("auto" | "wavedrom" | "questa" | "square"; null: the settings' again), from the bar's list;
  // kept in this browser. Signals with a style of their own keep it
  setStyle(name) {   // the bar's own layer: kept only when it differs from the settings (their style comes back with them)
    const base = settings(GLOBAL, this.M.cfg, this.opts).style;
    if (EDGES[name] && name !== base) this.local.style = name; else delete this.local.style;
    try { if (this.local.style) localStorage.setItem(this.lookKey, JSON.stringify(this.local)); else localStorage.removeItem(this.lookKey);
      } catch (e) { /* private mode */ }
    this.S.style = this.local.style || settings(GLOBAL, this.M.cfg, this.opts).style;
    if (this.wsEl) this.wsEl.value = this.S.style;
    this.draw(); this.settingsChanged(); return this;
  }
  loadLook() { try { const o = JSON.parse(localStorage.getItem(this.lookKey) || '{}'); return o && EDGES[o.style] ? { style: o.style } : {};
    } catch (e) { return {}; } }
  // what you did in this viewer as one JSON object (Save / Load… in the bar): the window, the cursor, the order and its
  // prefixes, the folding, the highlight (in its colours' order), the paint, the selected signal, the search, the
  // bookmarks and arrows, and the plugins' parts (extraState). The keys of "config" are settings: they paste into a
  // config file as they are. Paths are full paths; times are model units.
  state() {
    const M = this.M, folded = this.foldSaved || this.collapsed;   // during a search: the folding from before it
    const st = { wavefw: 'state', version: STATE_VERSION, title: this.opts.title || M.title || '', from: this.t0, to: this.t0 + this.span, cursor: this.cursor,
      config: { style: this.S.style, sort: this.sort, sortIgnore: [...this.sortIgnore],
        fold: [...folded].map(id => M.groups[id] && M.groups[id].path).filter(Boolean),
        highlight: [...this.picks].sort((a, b) => a[1] - b[1]).map(([r]) => r.full).filter(Boolean), findHighlight: !!this.findHl, findOpen: !!this.findOpen,
          ...Object.fromEntries(FIND_OPTS.map(o => [o[1], !!this[o[1]]])) },
      paint: Object.fromEntries(this.painted), radix: Object.fromEntries(this.radixes), analog: Object.fromEntries(this.analogs), hidden: [...this.hiddenRows],
        select: (this.sel && this.sel.full) || null, find: this.q || '', bookmarks: this.bookmarks(), arrows: this.arrowList() };
    if (this.cursor2 != null) st.cursor2 = this.cursor2;
    if (this.range) st.range = { from: this.range[0], to: this.range[1], signal: (this.rangeRow && this.rangeRow.full) || null };
    if (this.edgeKind !== 'any' || (this.evEl && this.evEl.value)) st.edge = { kind: this.edgeKind, value: (this.evEl && this.evEl.value) || '' };
    for (const x of this.extraState) { try { const val = x.get(); if (val !== undefined) st[x.key] = val; } catch (e) { console.error('wavefw state:', e); } }
    return st;
  }
  // a state (state()) back: every key it has replaces this viewer's; the plugins' parts first (their rows may come).
  // -> the paths it names that these waves do not have (left out)
  async setState(st) {
    if (!st || typeof st !== 'object' || Array.isArray(st) || st.wavefw !== 'state') throw new Error(st &&
      st.signal ? 'WaveDrom waves, not a saved viewer state (open them as a page)' : 'not a saved viewer state');
    if (!(st.version <= STATE_VERSION)) console.warn((`wavefw: a state of version ${st.version} (this viewer reads ${STATE_VERSION}): what it does not know ` +
        `is left out`));
    const M = this.M, C = st.config || {}, miss = new Set();
    for (const x of this.extraState) if (st[x.key] !== undefined) { try { await x.set(st[x.key]); } catch (e) { this.toast(`${x.key}: ${e.message}`); } }
    this.allRows();   // the plugins' groups are there now (their folding)
    const paths = new Set([...M.rows.map(r => r.full), ...Object.values(M.groups).map(g => g.path)]), seen = p => paths.has(p) || (miss.add(p), false);
    if (C.style !== undefined) this.setStyle(C.style);
    if (C.sort !== undefined || C.sortIgnore !== undefined) {
      const pfx = this.root.querySelector('input.pfx');
      this.sort = sortDir(C.sort ?? this.sort); if (C.sortIgnore !== undefined) this.sortIgnore = prefixes(C.sortIgnore).sort((a, b) => b.length - a.length);
      if (pfx) { pfx.value = this.sortIgnore.join(','); this.fitPfx(); }
    }
    for (const [k, own] of [['findHighlight', 'findHl'], ['findOpen', 'findOpen']]) if (C[k] !== undefined) {
      this[own] = !!C[k]; this.root.querySelector(`button[data-act=${k === 'findOpen' ? 'fopen' : 'fhl'}]`)?.setAttribute('aria-pressed', this[own]);
    }
    for (const [act, k] of FIND_OPTS) if (C[k] !== undefined) { this[k] = !!C[k];
      this.root.querySelector(`button[data-act=${act}]`)?.setAttribute('aria-pressed', this[k]); }
    if (C.fold !== undefined) { (Array.isArray(C.fold) ? C.fold : []).forEach(p => seen(p)); this.foldSaved = null; this.collapsed = foldSet(M, C.fold);
      this.foldTouched = true; }
    if (C.highlight !== undefined) { prefixes(C.highlight).filter(p => !p.includes('*')).forEach(p => seen(p)); this.picks = hlPick(M, C.highlight); }
    if (st.paint !== undefined) { this.painted = new Map(Object.entries(st.paint || {}).filter(([p, c]) => typeof c === 'string' && seen(p))); this.savePaint();
      }
    if (st.radix !== undefined) {
      for (const p of [...this.radixes.keys()]) this.setRadix(p, null, true);
      for (const [p, rx] of Object.entries(st.radix || {})) if (seen(p)) this.setRadix(p, rx, true);
    }
    if (st.analog !== undefined) {
      for (const p of [...this.analogs.keys()]) this.setAnalog(p, null, true);
      for (const [p, n] of Object.entries(st.analog || {})) if (seen(p)) this.setAnalog(p, n, true);
    }
    if (st.radix !== undefined || st.analog !== undefined) this.saveRows();   // once (renderNames and draw: find() below)
    if (st.hidden !== undefined) { this.hiddenRows = new Set((st.hidden || []).filter(p => seen(p))); this.saveRows(); }
    if (st.bookmarks !== undefined || st.arrows !== undefined) {
      const bms = (st.bookmarks || []).filter(b => !b.signal || seen(b.signal) || (b.signal = null, true));   // on the time axis when its signal is not here
      this.bms = bmNorm(bms); this.arrows = arNorm(st.arrows || [], bms); this.saveBookmarks(); this.renderNotes();
    }
    if (st.select !== undefined) this.sel = (st.select && seen(st.select) && M.rows.find(r => r.type === 'sig' && r.tr && r.full === st.select)) || null;
    if (st.from != null && st.to != null && isFinite(st.from) && isFinite(st.to)) { this.span = Math.min(Math.max(st.to - st.from, this.minSpan), M.t1 - M.t0);
      this.t0 = this.clamp(st.from); }
    if (st.cursor != null && isFinite(st.cursor)) this.cursor = Math.min(Math.max(st.cursor, M.t0), M.t1);
    if (st.cursor2 !== undefined) this.cursor2 = st.cursor2 != null && isFinite(st.cursor2) ? Math.min(Math.max(st.cursor2, M.t0), M.t1) : null;
    if (st.range !== undefined) {
      const g = st.range, row = g && g.signal ? (seen(g.signal) && M.rows.find(r => r.type === 'sig' && r.full === g.signal)) || null : null;
      if (g && isFinite(g.from) && isFinite(g.to)) { this.range = [Math.max(Math.min(g.from, g.to), M.t0), Math.min(Math.max(g.from, g.to), M.t1)];
        this.rangeRow = row; this.rangeKey = null; } else this.range = null;
    }
    if (st.edge !== undefined) { this.setEdgeKind((st.edge && st.edge.kind) || 'any'); if (this.evEl) this.evEl.value = (st.edge && st.edge.value) || ''; }
    if (st.find !== undefined && this.qEl) this.qEl.value = st.find || '';
    this.find(st.find !== undefined ? st.find || '' : this.q || '');   // draws; with Open the folding above is the one from before the search
    this.settingsChanged();
    return [...miss];
  }
  // Save: the state as <title>.view.json (a download); Load…: a file of it (a File, or its text)
  saveState(name) {
    const st = this.state(), a = document.createElement('a');
    a.download = name || (String(st.title || 'waves').replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'waves') + '.view.json';
    a.href = URL.createObjectURL(new Blob([JSON.stringify(st, null, 1)], { type: 'application/json' }));
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    this.toast(`saved ${a.download}`); return st;
  }
  async loadState(file) {
    try {
      const text = typeof file === 'string' ? file : await file.text(), miss = await this.setState(JSON.parse(text));
      this.toast((`${file.name || 'state'} ` +
          `loaded${miss.length ? ` · not in these waves: ${miss.length} (${miss.slice(0, 3).join(', ')}${miss.length > 3 ? ', …' : ''})` : ''}`));
      return miss;
    } catch (e) { this.toast(`${file.name || 'state'}: ${e.message}`); return null; }
  }
  // the colour a row is drawn in here: your paint, its own colour, its group's (groupColors); the model is not changed
  strokeOf(r) { return (r.type === 'sig' && this.painted.get(r.full)) || r.stroke || (this.groupStroke && this.groupStroke.get(r)) || undefined; }

  /* ---------------- the plugin API (wavefw/sva.js uses only this, the rows of view.extraRows and the events) ---------------- */
  // Open… a dump: picked (with a handle where the browser keeps one: ⟳ reads the file again), a File, or a dropped one
  // (handle: a Promise of its handle) -> this viewer's waves replaced (a new viewer on the same element: the plugins
  // take it as any other); keep: the view of these waves stays (⟳)
  async openDump(file, handle = null, keep = false) {
    try {
      if (!file && G.showOpenFilePicker) { const [h] = await G.showOpenFilePicker({ id: 'wavefw-dump',
        types: [{ description: 'VCD dump', accept: { 'text/plain': ['.vcd'] } }] }); handle = h; file = await h.getFile(); }
      else if (!file) { this.dfile.click(); return this; }
      if (handle && handle.then) handle = await handle.catch(() => null);
      if (/\.fst$/i.test(file.name)) { this.toast('an FST is binary: fst2vcd x.fst > x.vcd, or make html WAVES=x.fst'); return this; }
      this.toast(`reading ${file.name}…`);
      const text = await file.text(), r = vcdToWave(text, { name: file.name, budget: this.S.dumpBudget });
      if (!r.shown) { this.toast(`${file.name}: no signals`); return this; }
      const st = keep ? this.state() : null, root = this.root, opts = Object.assign({}, this.opts,
        { title: file.name, dumpSrc: { name: file.name, handle, file } });
      this.destroy(); root.innerHTML = '';
      const v = new WaveView(root, r.doc, opts);
      if (st) { delete st.title; await v.setState(st); }
      v.toast((`${file.name}: ${r.shown} of ${r.total} ` +
          `signals${r.shown < r.total ? ` (dumpBudget ${this.S.dumpBudget} changes: the levels nearest the top)` : ''}`));
      root.dispatchEvent(new CustomEvent('wavefw:dump', { detail: { name: file.name, shown: r.shown, total: r.total } }));
      return v;
    } catch (e) { if (e && e.name !== 'AbortError') this.toast('cannot open: ' + e.message); return this; }
  }
  // ⟳: the dump again from the disk (its handle; else the file as picked, if the browser still reads it), the view kept
  async reloadDump() {
    const d = this.opts.dumpSrc; if (!d) return this;
    try { const f = d.handle ? await d.handle.getFile() : d.file; return this.openDump(f, d.handle, true); }
    catch (e) { this.toast('cannot read it again (pick it with Open…): ' + e.message); return this; }
  }
  // a tool group of the bar by its label ("go to", "assertions" …), made at the end of its line when missing (TOOL_LINES;
  // another label: a line of its own at the end); content: HTML or an element, appended to the group; -> the group's element
  addTool(group, content) {
    const tools = this.root.querySelector('.bar .tools');
    let g = [...tools.querySelectorAll('.tg')].find(t => t.dataset.tg === group);
    if (!g) {
      const ln = TOOL_LINES[group] || 'more';   // its line of the bar (a group of its own kind: a line at the end)
      let line = tools.querySelector(`.tln[data-ln="${ln}"]`);
      if (!line) { tools.insertAdjacentHTML('beforeend', toolLine(ln, '')); line = tools.lastElementChild; }
      g = document.createElement('span'); g.className = 'tg'; g.dataset.tg = group; g.innerHTML = `<span class="tl">${esc(group)}</span>`; line.appendChild(g);
    }
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
  listen(part, type, fn, o) { ({ names: this.namesEl, waves: this.canvas, bar: this.root.querySelector('.bar'),
    lists: this.notesEl })[part].addEventListener(type, fn, o); return this; }
  // a key on the waves (without ctrl / alt / meta) and its line in the hint ("f F next / previous failure")
  // the cursor to time t and the window to show it: `left` puts the window's start there, `center` the time in the
  // middle, else the window moves only when t is outside it; "l" goes back to the window before (plugins: ]t ]f …)
  moveTo(t, { left = null, center = false, cursor = true } = {}) {
    this.markView();
    if (left != null) this.t0 = this.clamp(left);
    else if (center || t < this.t0 || t > this.t0 + this.span) this.t0 = this.clamp(t - this.span / 2);
    if (cursor) this.cursor = Math.min(Math.max(t, this.M.t0), this.M.t1);
    this.draw(); return this;
  }
  // fold (on) or open a group by its id; quiet: no render (a plugin building its rows)
  fold(id, on, quiet = false) {
    if (on) this.collapsed.add(id); else this.collapsed.delete(id);
    if (!quiet) { this.foldTouched = true; this.renderNames(); this.draw(); }
    return this;
  }
  addKey(key, fn, help) { this.keys[key] = fn; if (help) { this.hints.push(help); this.keyHelp = (this.keyHelp || []).concat([help]); } return this; }
  // ? : the keys and the mouse in a box over the viewer (Esc, ? or a click outside closes it)
  help(on = !this.helpEl) {
    if (this.helpEl) { this.helpEl.remove(); this.helpEl = null; document.removeEventListener('pointerdown', this.offHelp, true); }
    if (!on) return this;
    const kb = ks => ks.map(x => `<kbd>${esc(x)}</kbd>`).join(' ');
    const plug = (this.keyHelp || []).map(h => { const m = h.match(/^((?:\S{1,3}\s+)+?)([a-z(].*)$/); return m ? [m[1].trim().split(/\s+/), m[2]] : [[], h]; });
    const sec = ([title, rows]) =>
      `<section><h4>${esc(title)}</h4><table>${rows.map(([k, t]) => `<tr><td>${kb(k)}</td><td>${esc(t)}</td></tr>`).join('')}</table></section>`;
    const el = this.helpEl = document.createElement('div'); el.className = 'wv-help'; el.setAttribute('role', 'dialog');
      el.setAttribute('aria-label', 'keys and mouse');
    el.innerHTML =
      (`<div class="hh"><b>Keys and mouse</b><span class="muted">on the waves (a click there gives them the keys); hover a button for what it ` +
        `does</span><button type="button" class="ic" aria-label="close">✕</button></div>`) +
      `<div class="hg">${HELP.concat(plug.length ? [['Plugins', plug]] : []).map(sec).join('')}</div>`;
    this.root.append(el);
    el.querySelector('button').addEventListener('click', () => this.help(false));
    el.addEventListener('keydown', e => { if (e.key === 'Escape' || e.key === '?') { e.preventDefault(); e.stopPropagation(); this.help(false);
      this.canvas.focus({ preventScroll: true }); } });
    this.offHelp = e => { if (!el.contains(e.target) && !e.target.closest('[data-act=help]')) this.help(false); };
    document.addEventListener('pointerdown', this.offHelp, { capture: true, signal: this.ac.signal });   // the click that opened it is on the ? button: ignored
    el.tabIndex = -1; el.focus({ preventScroll: true });
    return this;
  }
  renderHint() { const h = this.root.querySelector('.hint'); if (h) h.textContent = [this.hintBase, ...this.hints].join(' · '); }
  savePaint() {
    try { if (this.painted.size) localStorage.setItem(this.paintKey, JSON.stringify(Object.fromEntries(this.painted)));
      else localStorage.removeItem(this.paintKey); } catch (e) { /* private mode */ }
    if (this.unpaintBtn) this.unpaintBtn.hidden = !this.painted.size;
  }
  expandAll() { this.collapsed = new Set(); this.foldTouched = true; this.renderNames(); this.draw(); return this; }
  collapseAll() { this.collapsed = new Set(Object.keys(this.M.groups).map(Number)); this.foldTouched = true; this.renderNames(); this.draw(); return this; }
  select(row) { // the signal for edge search and bookmarks: a row, a full path / name, or null
    if (typeof row === 'string') row = this.M.rows.find(r => r.type === 'sig' && r.full === row) || this.M.rows.find(r => r.type === 'sig' && r.name === row);
    this.sel = this.selAnchor = row && row.type === 'sig' && row.tr ? row : null; this.selRun = new Set(); this.renderNames(); this.draw();
    this.namesEl.querySelector('.row.sel')?.scrollIntoView({ block: 'nearest' });
    return this;
  }
  // cursor to the next (dir 1) / previous (-1) edge of the selected signal, or of any shown signal; the view follows
  // the edge kind of ◀ ▶ / Tab (EDGE_KINDS); "value" shows the value field (focus: the field gets the keys)
  setEdgeKind(kind, focus = false) {
    if (!EDGE_KINDS[kind]) return this;
    this.edgeKind = kind; if (this.edgeSel) this.edgeSel.value = kind;
    if (this.evEl) { this.evEl.hidden = kind !== 'value'; if (focus && kind === 'value') this.evEl.focus(); }
    return this;
  }
  // the cursor to the next (dir 1) / previous (-1) edge of the kind (a value: becomes it, X / Z: one appears) of the
  // selected signal, or of any shown signal (want: the value, else the field's); the view follows
  edge(dir, kind = this.edgeKind, want = null) {
    let best = null, at = null;
    const w = kind === 'value' ? (want != null ? parseWant(want) : parseWant(this.evEl && this.evEl.value)) : null;
    if (kind === 'value' && !w) { if (this.evEl) { this.evEl.hidden = false; this.bad(this.evEl); this.evEl.focus(); } return this; }
    for (const s of this.sel ? [this.sel] : this.vis.filter(r => r.type === 'sig' && r.tr)) {
      const t = findEdge(s, this.cursor, dir, kind, w, this.S.radix);
      if (t != null && (best == null || (dir > 0 ? t < best : t > best))) { best = t; at = s; }
    }
    if (best == null) { if (kind === 'value' ||
      kind === 'xz') this.toast(`no ${kind === 'xz' ? 'X / Z' : w.text} ${dir > 0 ? 'after' : 'before'} the cursor${this.sel ? ' on ' + this.sel.name : ''}`);
      return this; }
    if ((kind === 'value' || kind === 'xz') && !this.sel && at) this.toast(`${at.name} ${kind === 'xz' ? 'goes X / Z' : '= ' + w.text}`);
    this.cursor = best;
    if (best < this.t0 || best > this.t0 + this.span) this.t0 = this.clamp(best - this.span / 2);
    this.draw(); return this;
  }
  // nearest edge of signal s within px pixels of t (the initial value is not an edge), else t
  snap(s, t, px = 6) {
    if (!s || !s.tr) return t;
    const tol = px / this.pxPerT(), i = lastLE(s.tr, t);
    const near = [i, i + 1].filter(k => k > 0 && k < s.tr.length && Math.abs(s.tr[k].t - t) <= tol).sort((a, b) =>
      Math.abs(s.tr[a].t - t) - Math.abs(s.tr[b].t - t))[0];
    return near != null ? s.tr[near].t : t;
  }
  bmAt(x, y) { const pos = this.bmGeo && this.bmGeo.pos; return pos && this.bms.find(b =>
    { const p = pos.get(b.n); return p && Math.hypot(p[0] - x, p[1] - y) <= 9; }); }
  // drag on the waves: time from x (snapped to an edge of the row), signal from the row under y (the time axis: no signal)
  // dragged: the time (snapped to an edge of its row), the row under the pointer, or the axis; on the top quarter of a
  // signal row, or in the lane above it, lifted into that lane (a leader down to the signal), lower down on the row again
  moveBookmark(b, x, y, lay = this.lay || []) {
    const k = lay.findIndex(o => y >= o.y && y < o.y + o.h), o = lay[k];
    if (y < (this.oy || 0) + this.hdrH) { b.signal = null; b.lift = false; }
    else if (o && o.row.type === 'sig') { b.signal = o.row.full; b.lift = this.S.arrowLabels === 'lane' && y < o.y + o.h / 4; }
    else if (o && o.row.type === 'lane' && o.row.ids.includes('b:' + b.signal)) b.lift = true;
    else if (o && o.row.type === 'lane') { const r = lay.slice(k + 1).find(q => q.row.type !== 'lane');
      if (r && r.row.type === 'sig') { b.signal = r.row.full; b.lift = this.S.arrowLabels === 'lane'; } }
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
  arrow(from, to, opts = {}) { this.arrows.push(...arNorm([Object.assign({ from, to }, opts)])); this.saveBookmarks(); this.renderNotes(); this.draw();
    return this; }
  // JSON for a config file / WaveJSON (t in model units: ps for timed waves, else cycles); defaults are left out
  bookmarks() { return this.bms.map(b => Object.fromEntries(Object.entries({ n: b.n, t: b.t, signal: b.signal, text: b.text, color: b.color, lift: b.lift ||
    null }).filter(([, v]) => v != null && v !== ''))); }
  arrowList() {
    return this.arrows.map(a => Object.fromEntries(Object.entries({ from: a.from, to: a.to, shape: a.shape, head: a.head === '>' ? null : a.head,
      line: a.line === 'solid' ? null : a.line,
      color: a.color, label: a.label }).filter(([k, v]) => v != null && (v !== '' || k === 'head'))));   // head "" = no head
  }
  setBookmarks(list, arrows = []) { this.bms = bmNorm(list); this.arrows = arNorm(arrows, list); this.saveBookmarks(); this.renderNotes(); this.draw();
    return this; }
  loadBookmarks() { // this browser's copy (localStorage) wins over the page's "bookmarks" / "arrows"
    try {
      const v = localStorage.getItem(this.bmKey);
      if (v != null) { const o = JSON.parse(v), list = Array.isArray(o) ? o : o.bookmarks; return { bms: bmNorm(list), arrows: arNorm(o.arrows, list) }; }
    } catch (e) { /* no storage: page bookmarks */ }
    return { bms: this.M.bookmarks.map(b => Object.assign({}, b)), arrows: this.M.arrows.map(a => Object.assign({}, a)) };
  }
  saveBookmarks() { try { localStorage.setItem(this.bmKey, JSON.stringify({ bookmarks: this.bookmarks(), arrows: this.arrowList() }));
    } catch (e) { /* private mode */ } }
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
  // the window to go back to with l (Questa's zoom last): the one before a zoom, fit, a jump; a run of wheel steps is one
  markView(burst = false) {
    const now = Date.now();
    if (!burst || now - (this.viewT || 0) > 500) this.lastView = { t0: this.t0, span: this.span };
    this.viewT = burst ? now : 0;
  }
  zoomLast() { const b = this.lastView; if (!b) return this; this.lastView = { t0: this.t0, span: this.span }; this.span = b.span; this.t0 = this.clamp(b.t0);
    this.draw(); return this; }
  // the window [a, b]
  zoomTo(a, b) { this.markView(); this.span = Math.min(Math.max(b - a, this.minSpan), this.M.t1 - this.M.t0); this.t0 = this.clamp(a); this.draw(); return this;
    }
  // a two-key sequence (vim): gg first signal, zR / zM open / fold every module, zc fold / zo open the selected signal's
  // module, yy copy, ]m [m next / previous bookmark, ]e [e next / previous edge; plugins add theirs (addKey(']f', …)).
  // -> whether it was one
  seq(s) {
    const sigs = () => this.vis.filter(r => r.type === 'sig' && r.tr), up = this.sel && this.sel.anc[this.sel.anc.length - 1];
    if (s === 'gg') this.select(sigs()[0] || null);
    else if (s === 'zR') this.expandAll();
    else if (s === 'zM') this.collapseAll();
    else if (s === 'zc' || s === 'zo' || s === 'za') {
      if (up == null) return true;
      const shut = s === 'zc' || (s === 'za' && !this.collapsed.has(up));
      if (shut) { this.collapsed.add(up); this.sel = null; } else this.collapsed.delete(up);
      this.foldTouched = true; this.renderNames(); this.draw();
    }
    else if (s === 'yy') this.copyKey();
    else if (s === ']m' || s === '[m') this.stepMark(s[0] === ']' ? 1 : -1);
    else if (s === ']e' || s === '[e') this.edge(s[0] === ']' ? 1 : -1);
    else if (this.keys[s]) this.keys[s]();
    else return false;
    return true;
  }
  goMark(n) {   // the cursor to bookmark n (keys 1–9), the view follows, its signal selected
    const b = this.bms.find(x => x.n === n); if (!b) { this.toast(`no bookmark ${n}`); return this; }
    this.cursor = b.t; if (b.t < this.t0 || b.t > this.t0 + this.span) this.t0 = this.clamp(b.t - this.span / 2);
    if (b.signal) this.sel = this.M.rows.find(r => r.full === b.signal) || this.sel;
    this.renderNames(); this.draw(); return this;
  }
  // the second cursor (shift+click; null: none): Δ to the cursor in time and in cycles of a clock (clockFor)
  setCursor2(t) { this.cursor2 = t == null || !isFinite(t) ? null : Math.min(Math.max(t, this.M.t0), this.M.t1); this.draw(); return this; }
  // a clock for counting cycles: the selected signal when it is one, else a 1-bit *clk* / *clock* nearest to the rows
  clockFor(rows = this.sel ? [this.sel] : []) {
    const key = rows.length === 1 ? rows[0] : rows.length ? null : 'none';   // one row or none: remembered (a draw asks twice)
    if (key && this.clkMemo && this.clkMemo[0] === key) return this.clkMemo[1];
    const isClk = r => r.type === 'sig' && r.width === 1 && r.tr && r.tr.length > 4 && /clk|clock/i.test(r.name);
    const near = r => rows.length ? Math.max(...rows.map(s => { let k = 0; while (k < r.anc.length && r.anc[k] === s.anc[k]) k++; return k - (r.anc.length - k);
      })) : 0;
    const c = rows.find(isClk) || this.M.rows.filter(isClk).sort((x, y) => near(y) - near(x))[0] || null;
    if (key) this.clkMemo = [key, c];
    return c;
  }
  // the rising edges of clk in (a, b]: two searches in its (cached) list of rise times, not a pass over all its changes
  cycles(clk, a, b) {
    if (!clk) return null;
    const ups = RISES.get(clk) || (RISES.set(clk, clk.tr.filter(o => o.k === '1').map(o => o.t)), RISES.get(clk));
    const le = t => { let lo = 0, hi = ups.length; while (lo < hi) { const m = (lo + hi) >> 1; if (ups[m] <= t) lo = m + 1; else hi = m; } return lo; };
    return le(Math.max(a, b)) - le(Math.min(a, b));
  }
  delta2() {   // "Δ 40 ns · 4 clk" between the cursors, or ''
    if (this.cursor2 == null) return '';
    const d = this.cursor2 - this.cursor, clk = this.clockFor(), n = this.cycles(clk, this.cursor, this.cursor2);
    return `Δ ${d < 0 ? '−' : ''}${this.fmt(Math.abs(d), Math.abs(d) / 1000 || 1, Math.abs(d) || 1)}` + (clk && n != null ? ` · ${n} ${clk.name}` : '');
  }
  stepMark(dir) {   // the cursor to the next / previous bookmark in time (round the ends)
    const bs = [...this.bms].sort((a, b) => a.t - b.t); if (!bs.length) return this;
    const b = bs[stepTo(bs.map(x => x.t), this.cursor, dir)];
    this.cursor = b.t; if (b.t < this.t0 || b.t > this.t0 + this.span) this.t0 = this.clamp(b.t - this.span / 2);
    if (b.signal) this.sel = this.M.rows.find(r => r.full === b.signal) || this.sel;
    this.renderNames(); this.draw(); return this;
  }
  pageRows(dir) {   // PgUp / PgDn: the rows a page (the viewer's own scroll bar, else the page)
    if (this.root.classList.contains('wv-scroll')) this.bodyEl.scrollTop += dir * this.bodyEl.clientHeight * 0.9;
    else window.scrollBy(0, dir * window.innerHeight * 0.9);
  }
  // ctrl+F, /: the find field; with the bar off the screen (a long page scrolled down) the find group floats over the
  // waves where you are, at the top right of what you see of them, until ✕ or Esc puts it back
  focusFind() {
    const g = this.qEl.closest('.find'), b = g.getBoundingClientRect();
    if (!g.classList.contains('float') && (b.top < 0 || b.bottom > innerHeight)) this.floatFind(true);
    this.qEl.focus({ preventScroll: true }); this.qEl.select();
  }
  floatFind(on) {
    const g = this.qEl && this.qEl.closest('.find'); if (!g || g.classList.contains('float') === !!on) return this;
    g.classList.toggle('float', !!on);
    if (!on) { g.style.top = g.style.right = ''; return this; }
    const w = this.wcol.getBoundingClientRect(), gb = g.getBoundingClientRect();   // right-anchored: the count grows it leftwards
    g.style.top = Math.min(Math.max(w.top, 0) + 30, innerHeight - gb.height - 6) + 'px';
    g.style.right = Math.max(6, document.documentElement.clientWidth - Math.min(w.right, innerWidth) + 10) + 'px';
    return this;
  }
  rowOfY(y) { const o = (this.lay || []).find(o => y >= o.y && y < o.y + o.h); return o ? o.row : null; }
  // the time at x on the waves (layout y): on an edge of the signal at y within cursorSnap px (free: not), else a round
  // time at the zoom — for the cursor and the ends of a range
  pickTime(x, y, free = false) {
    const r = this.rowOfY(y), sig = r && r.type === 'sig' && r.tr ? r : null, raw = this.t0 + x / this.pxPerT();
    const at = sig && this.S.cursorSnap > 0 && !free ? this.snap(sig, raw, this.S.cursorSnap) : raw;
    return at !== raw ? at : this.timeAt(x);
  }
  // the measured range [a, b] (shift+drag, the right button; null: none): drawn over the waves with its Δ, in the readout
  setRange(a, b, row) {
    this.range = a == null || b == null || a === b ? null : [Math.min(a, b), Math.max(a, b)];
    if (row !== undefined) this.rangeRow = row && row.type === 'sig' && row.tr ? row : null;
    this.rangeKey = null;
    this.draw(); this.root.dispatchEvent(new CustomEvent('wavefw:range', { detail: { range: this.range } })); return this;
  }
  // "Δ 25 ns · 5 ↑ clk": the range's length, and the rising edges of the selected 1-bit signal in it (its cycles)
  // "Δ 20 ns · 2 ↑ PCLK" / "Δ 80 ns · 7 changes of PADDR (4 values)": the range's length and, on the signal it was
  // measured on (else the selected one), its rising edges (a bit) or its changes and the values it took (a bus)
  rangeText() {
    if (!this.range) return '';
    const [a, b] = this.range, s = this.rangeRow && this.rangeRow.tr ? this.rangeRow : this.sel, key = `${a}|${b}|${s ? s.full : ''}`;
    if (this.rangeKey === key) return this.rangeTxt;
    let more = '';
    if (s && s.tr && s.tr.length) {
      const tr = s.tr, i0 = lastLE(tr, a) + 1, i1 = lastLE(tr, b), bus = s.width > 1 || tr.some(o => o.k === '=');
      if (!bus) { let n = 0; for (let i = Math.max(i0, 1); i <= i1; i++) if (tr[i].k === '1' && tr[i - 1].k === '0') n++; if (n) more = ` · ${n} ↑ ${s.name}`; }
      else if (i1 >= i0) { const vals = new Set(); for (let i = Math.max(i0 - 1, 0); i <= i1; i++) vals.add(tr[i].raw ?? tr[i].v ?? tr[i].k);
        const n = i1 - i0 + 1; more = ` · ${n} change${n === 1 ? '' : 's'} of ${s.name} (${vals.size} value${vals.size === 1 ? '' : 's'})`; }
    }
    this.rangeKey = key; this.rangeTxt = 'Δ ' + (this.M.timed ? fmtExact(b - a) : trimNum(b - a) + ' cycles') + more;
    return this.rangeTxt;
  }
  // the rows shown on the screen now (for a picture of what you see)
  // the highlighted rows as laid out (a highlighted module: it and its rows shown), for the picture and WaveDrom
  // the rows the picture and WaveDrom take: a run of selected signals (shift+click, alt+drag), else the highlighted rows
  exportRows() { return this.selRun.size > 1 ? (this.rowsL || []).filter(r => this.selRun.has(r)) : this.picks.size ? this.pickedRows() : []; }
  pickedRows() { return (this.rowsL || []).filter(r => this.picks.has(r) || (r.anc || []).some(id => this.picks.has(this.M.groups[id]))); }
  // WaveDrom (WaveJSON) of signals over [a, b]: the highlighted ones (else the rows on the screen); one cell per period of
  // a clock — a 1-bit *clk* / *clock* among them, else in their modules —, else of the shortest time between changes;
  // the values at the start of each cell (as vcd2wavedrom.py samples), buses as "=" with their text in the radix shown
  toWaveDrom(a = this.t0, b = this.t0 + this.span, rows = null) {
    const picked = this.selRun.size > 1 ? this.M.rows.filter(r => this.selRun.has(r)) : this.picks.size ? this.M.rows.filter(r => this.picks.has(r) ||
      r.anc.some(id => this.picks.has(this.M.groups[id]))) : this.screenRows();
    const sigs = (rows || picked).filter(r => r.type === 'sig' && r.tr && r.tr.length);
    const clk = this.clockFor(sigs);
    let cells = clk ? clk.tr.filter(o => o.k === '1' && o.t >= a && o.t < b).map(o => o.t) : [];
    if (cells.length < 2) {   // no clock here: a grid of the shortest step between changes, at most 512 cells
      const ts = [...new Set(sigs.flatMap(r => r.tr.filter(o => o.t > a && o.t < b).map(o => o.t)))].sort((x, y) => x - y);
      let step = Infinity; for (let i = 1; i < ts.length; i++) step = Math.min(step, ts[i] - ts[i - 1]);
      step = isFinite(step) ? Math.max(step, (b - a) / 512) : (b - a) / 64;
      cells = []; for (let t = a; t < b && cells.length < 512; t += step) cells.push(t);
    } else if (cells.length > 2048) cells = cells.slice(0, 2048);
    const one = r => {
      if (r === clk && cells.length > 1 && clk.tr.some(o => o.t === cells[0])) return { name: r.name, wave: 'p' + '.'.repeat(cells.length - 1) };
      let wave = '', prev = null; const data = [];
      for (const t of cells) {
        const i = lastLE(r.tr, t), o = i < 0 ? { k: 'x' } : r.tr[i], key = o.k === '=' ? '=' + (o.raw ?? o.v) : o.k;
        if (key === prev) { wave += '.'; continue; }
        prev = key;
        if (o.k === '=') { wave += '='; data.push(vtext(r, o, this.S.radix)); } else wave += 'udhlHL'.includes(o.k) ? o.k : o.k === '1' || o.k === '0' ||
          o.k === 'z' ? o.k : 'x';
      }
      return data.length ? { name: r.name, wave, data } : { name: r.name, wave };
    };
    const scopes = [...new Set(sigs.map(r => (r.anc.length ? r.anc[r.anc.length - 1] : -1)))], label = id =>
      (id < 0 ? '' : this.M.groups[id].path || this.M.groups[id].name);
    const signal = scopes.length > 1 ? scopes.map(id => [label(id), ...sigs.filter(r =>
      (r.anc.length ? r.anc[r.anc.length - 1] : -1) === id).map(one)]) : sigs.map(one);
    if (clk && !sigs.includes(clk) && cells.length > 1) signal.unshift(one(clk));
    const title = String(this.opts.title || this.M.title || 'waves');
    return { signal, head: { text: `${title}: ${this.fmt(a, (b - a) / 1000, b - a)} … ${this.fmt(b, (b - a) / 1000, b - a)}` },
      foot: { text: clk && cells.length > 1 ? `one cell per ${clk.full || clk.name} cycle` :
      `one cell per ${this.fmt(cells[1] - cells[0] || 0, 1, cells[1] - cells[0] || 1)}` }, config: { hscale: 1 } };
  }
  screenRows() {
    const top = this.oy || 0, h = this.hc || 0, hdr = this.hdrH;
    const on = (this.lay || []).filter(o => o.y + o.h > top + hdr && o.y < top + h);
    return (on.length ? on : this.lay || []).map(o => o.row);
  }
  // the waves as a picture: the rows on the screen (rows: "all": every row shown) from the range (else the window), with
  // the names, the axis, the cursor and the bookmarks, as this viewer draws them; the page's colours put in: a standalone SVG
  toSVG(o = {}) {
    const [a, b] = this.range || [this.t0, this.t0 + this.span], cs = getComputedStyle(this.root);
    const rows = Array.isArray(o.rows) ? o.rows : o.rows === 'all' ? this.rowsL : o.rows === 'picked' ? this.pickedRows() : this.screenRows();
    const svg = WaveSVG.toString(null, { view: this, from: o.from ?? a, to: o.to ?? b, rows, width: o.width || Math.max(640, this.root.clientWidth) });
    return svg.replace(/var\((--[\w-]+)\)/g, (m, n) => cs.getPropertyValue(n).trim().replace(/"/g, "'") || m);
  }
  // -> a Promise of a PNG Blob of toSVG at scale × (2: sharp on a high-density screen and in a document)
  toPNG(o = {}, scale = 2) {
    const svg = this.toSVG(o), w = +svg.match(/width="(\d+)"/)[1], h = +svg.match(/height="(\d+)"/)[1];
    return new Promise((ok, no) => {
      const img = new Image(), url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
      img.onload = () => {
        const cv = document.createElement('canvas'); cv.width = w * scale; cv.height = h * scale;
        const g = cv.getContext('2d'); g.scale(scale, scale); g.drawImage(img, 0, 0); URL.revokeObjectURL(url);
        cv.toBlob(bl => (bl ? ok(bl) : no(new Error('no PNG'))), 'image/png');
      };
      img.onerror = () => { URL.revokeObjectURL(url); no(new Error('the picture did not render')); };
      img.src = url;
    });
  }
  download(blob, name) {
    const a = document.createElement('a'); a.download = name; a.href = URL.createObjectURL(blob);
    document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  picName(ext) { return (String(this.opts.title || this.M.title || 'waves').replace(/[^\w.-]+/g, '_').replace(/^_+|_+$/g, '') || 'waves') + '.' + ext; }
  // the right button's menu at (cx, cy) on the screen: the range (zoom, bookmarks at its ends, copy Δ), the picture (copy,
  // PNG, SVG), the signal under the pointer (colour, highlight, copy its path); Esc, a click elsewhere or a choice closes it
  menu(cx, cy, row, at = this.cursor) {
    this.closeMenu();
    const r = this.range, sig = row && row.type === 'sig' && row.tr ? row : null, grp = row && row.type === 'group' &&
      this.M.groups[row.id] === row ? row : null, it = row && (sig || grp);
    const up = sig && sig.anc.length ? sig.anc[sig.anc.length - 1] : null, nh = this.hiddenRows.size, ng = Object.keys(this.M.groups).length;
    // a highlighted row clicked: colour, radix and hide go to every highlighted one (a highlighted module: its signals)
    const picked = r => this.picks.has(r) || r.anc.some(id => this.picks.has(this.M.groups[id]));
    // or a row of the shift+click run: every row of the run
    const run = !!sig && this.selRun.size > 1 && this.selRun.has(sig);
    const many = run || (it && (this.picks.has(it) || sig && picked(sig)) && this.picks.size > 1);
    const sigs = run ? [...this.selRun] : many ? this.M.rows.filter(r => r.type === 'sig' && r.tr && picked(r)) : sig ? [sig] : [];
    const buses = sigs.filter(r => r.width > 1 && r.tr.some(o => o.raw != null)),
      rows = run ? sigs : many ? [...this.picks.keys()].filter(r => r.full && (r.type === 'sig' || this.M.groups[r.id] === r)) : [it];
    const acc = getComputedStyle(this.root).getPropertyValue('--wave-paint').trim(), col = sig && this.painted.get(sig.full) ||
      (/^#[0-9a-f]{6}$/i.test(acc) ? acc : '#d6336c');
    const of = many ? `the ${sigs.length} ${run ? 'selected' : 'highlighted'}` : sig ? sig.name : '', rx = sig &&
      (sig.radix0 !== undefined ? sig.radix0 || this.S.radix : sig.radix || this.S.radix);
    // a fixed-point radix: its kind and fraction bits
    const q0 = /^(s?q)(\d+)$/.exec((sig && this.radixes.get(sig.full)) || ''), qk = q0 ? q0[1] : '', qf = q0 ? +q0[2] : 8;
    // the picture and WaveDrom: the selected run, the highlighted rows, else the screen's
    const np = this.exportRows().length, pic = np ? { rows: this.exportRows() } : {};
    const b = (m, label) => { const k = (TIPS['m:' + m] || [])[1];
      return `<button type="button" role="menuitem" data-m="${m}"><span>${label}</span>${k ? `<span class="kk">${esc(k[0])}</span>` : ''}</button>`; };
    const el = document.createElement('div'); el.className = 'wv-menu'; el.setAttribute('role', 'menu');
    el.innerHTML = (r ? `<div class="mh">${esc(this.rangeText())}</div>` + b('zoom', 'Zoom to the range') + b('marks', 'Bookmarks at its ends',
      'Two bookmarks and an arrow with the Δ between them') + b('copyd', 'Copy Δ') + '<hr>' : '') +
      (np ? `<div class="mh">${np} ${this.selRun.size > 1 ? 'selected' : 'highlighted'} rows</div>` : '') + b('copyimg', 'Copy image') + b('png',
        'Save image as PNG') + b('svg', 'Save image as SVG') + b('wdjson', 'Save as WaveDrom') + b('wdcopy', 'Copy WaveDrom') +
      (it ? `<hr><div class="mh">${esc(it.full || it.name)}${many ? `<br>+ every ${run ? 'selected' : 'highlighted'} row: ${sigs.length} signals` : ''}</div>` +
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
        b('hl', this.picks.has(it) ? 'Remove the highlight' : 'Highlight') + b('hide',
          many ? `Hide the ${rows.length} ${run ? 'selected' : 'highlighted'}` : grp ? 'Hide this module' : 'Hide',
          'Leave it out of the view (Hidden: N ✕ in the bar shows it again)') +
        (grp ? b('fold', this.collapsed.has(grp.id) ? 'Open this module' : 'Fold this module') : up != null ? b('foldup', 'Fold its module') : '') +
        (sig ? b('mark', 'Bookmark here', 'A bookmark on this signal at the time clicked') : '') + b('c2',
          'Second cursor here') + (this.cursor2 != null ? b('c2x', 'Clear the second cursor') : '') + b('copyname', 'Copy the path') : '') +
      (ng || nh ? '<hr>' + (ng ? b('zM', 'Fold every module') + b('zR', 'Open every module') : '') + (nh ? b('unhide', `Show the hidden (${nh})`) : '') : '') +
      (r ? '<hr>' + b('clear', 'Clear the range') : '');
    this.root.append(el); this.menuEl = el;
    const box = el.getBoundingClientRect();
    el.style.left = Math.max(4, Math.min(cx, innerWidth - box.width - 4)) + 'px'; el.style.top = Math.max(4, Math.min(cy, innerHeight - box.height - 4)) + 'px';
    const done = () => { this.closeMenu(); this.canvas.focus({ preventScroll: true }); };
    el.addEventListener('click', e => {
      const m = e.target.closest('button[data-m]'); if (!m) return;
      const act = m.dataset.m;
      if (act === 'zoom') this.zoomTo(...r);
      else if (act === 'marks') {
        const n = Math.max(0, ...this.bms.map(x => x.n)) + 1, s = sig ? sig.full : null;
        this.bms.push(...bmNorm([{ n, t: r[0], signal: s }, { n: n + 1, t: r[1], signal: s }]));
        this.arrows.push(...arNorm([{ from: n, to: n + 1, shape: '-', head: '<>', label: this.rangeText().replace(/^Δ /, '') }])); this.changed(true);
      }
      else if (act === 'copyd') this.copyText(this.rangeText().replace(/^Δ /, '').split(' · ')[0]);
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
        const [ta, tb] = r || [this.t0, this.t0 + this.span], text = wdText(this.toWaveDrom(ta, tb));
        if (act === 'wdcopy') { try { navigator.clipboard.writeText(text).then(() => this.toast('WaveDrom copied'), () => this.toast('not copied'));
          } catch (e) { this.toast('not copied'); } }
        else { this.download(new Blob([text + '\n'], { type: 'application/json' }), this.picName('wavedrom.json'));
          this.toast('saved ' + this.picName('wavedrom.json')); }
      }
      else if (act === 'unpaint') { sigs.forEach(r => this.painted.delete(r.full)); this.savePaint(); this.renderNames(); this.draw(); }
      else if (act === 'hl') this.toggleHighlight(it);
      else if (act === 'analog') { const on = !buses.every(r => r.analog); buses.forEach(r => this.setAnalog(r, on ? 3 : false)); }
      else if (act === 'hide') this.hide(rows);
      else if (act === 'unhide') this.unhide();
      else if (act === 'fold') { if (this.collapsed.has(grp.id)) this.collapsed.delete(grp.id); else this.collapsed.add(grp.id); this.foldTouched = true;
        this.renderNames(); this.draw(); }
      else if (act === 'foldup') { this.collapsed.add(up); if (this.sel && this.sel.anc.includes(up)) this.sel = null; this.foldTouched = true;
        this.renderNames(); this.draw(); }
      else if (act === 'zM' || act === 'zR') this.seq(act);
      else if (act === 'mark') { const t = this.snap(sig, at), n = Math.max(0, ...this.bms.map(x => x.n)) + 1;
        this.bms.push({ n, t, signal: sig.full, text: '', color: null }); this.changed(true);
        this.notesEl.querySelector(`li[data-n="${n}"] input.txt`)?.focus(); return this.closeMenu(); }
      else if (act === 'copyname') this.copyRows([it]);
      else if (act === 'c2') this.setCursor2(sig ? this.snap(sig, at) : at);
      else if (act === 'c2x') this.setCursor2(null);
      else if (act === 'clear') this.setRange(null);
      done();
    });
    const qfEl = el.querySelector('input.qf'), fixed = k => buses.forEach(r => this.setRadix(r, k + Math.max(0, Math.min(128, Math.round(+qfEl.value || 0)))));
    el.addEventListener('change', e => {
      if (e.target.tagName !== 'SELECT' || !buses.length) return;
      // stays open for the fraction bits
      if (e.target.value === 'q' || e.target.value === 'sq') { qfEl.hidden = false; fixed(e.target.value); qfEl.focus(); return; }
      buses.forEach(r => this.setRadix(r, e.target.value || null)); done();
    });
    if (qfEl) qfEl.addEventListener('input', () => { const k = el.querySelector('select').value; if (k === 'q' || k === 'sq') fixed(k); });
    el.addEventListener('input', e => { if (e.target.type === 'color' && sigs.length) { sigs.forEach(r => this.painted.set(r.full, e.target.value));
      this.savePaint(); this.renderNames(); this.draw(); } });
    el.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); done(); } });
    const off = this.offMenu = e => { if (!el.contains(e.target)) this.closeMenu(); };
    // after the click that opened it; not for a menu closed meanwhile (its listener would close the next one)
    setTimeout(() => { if (this.menuEl !== el) return; document.addEventListener('pointerdown', off, { capture: true, signal: this.ac.signal });
      window.addEventListener('blur', off, { signal: this.ac.signal }); }, 0);
    (el.querySelector('button') || el).focus({ preventScroll: true });
    return el;
  }
  closeMenu() {
    if (!this.menuEl) return;
    this.menuEl.remove(); this.menuEl = null;
    document.removeEventListener('pointerdown', this.offMenu, true); window.removeEventListener('blur', this.offMenu);
  }
  copyText(t) { try { navigator.clipboard.writeText(t).then(() => this.toast('copied: ' + t), () => this.toast(t)); } catch (e) { this.toast(t); } }
  copyKey() {   // ctrl+C / yy: while searching it ends the search; else the selected signal (or the highlighted ones) to the clipboard
    if (this.q) { this.clearFind(); return true; }
    const rows = this.sel ? [this.sel] : [...this.picks.keys()]; if (rows.length) this.copyRows(rows);
    return rows.length > 0;
  }
  goto(t, span) { this.markView(); this.span = Math.min(Math.max(span, this.minSpan), this.M.t1 - this.M.t0); this.t0 = this.clamp(t - this.span * 0.1);
    this.cursor = t; this.draw(); }
  fmt(t, ref, unitRef) { return this.M.timed ? fmtTime(t, ref, unitRef) : 'cycle ' + (t + (this.M.tick || 0)).toFixed(Math.max(0,
    Math.min(2, Math.ceil(-Math.log10(ref))))); }
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
    if (c.width !== Math.round(W * dpr) || c.height !== Math.round(Hc * dpr)) { c.width = Math.round(W * dpr); c.height = Math.round(Hc * dpr);
      c.style.height = Hc + 'px'; }
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
    const late = [], rowY = paintBody(P, M, shown, X, this.t0, tB, 0, W, this.hl, this.selRun &&
      this.selRun.size ? new Set([...this.selRun, this.sel]) : this.sel, lay, this.band, late, r => this.strokeOf(r), r => this.collapsed.has(r.id));
    paintMarkers(P, this.markers, X, this.t0, tB, oy + hdr, oy + Hc);
    g.restore();
    if (this.cursor >= this.t0 && this.cursor <= tB) P.path([['M', X(this.cursor), 0], ['L', X(this.cursor), Hc]], { stroke: 'acc', w: 1.2 });
    this.paintMeasures(P, X, this.t0, tB, 0, W, 0, Hc, top ? [0, hdr] : null);
    // alt+drag
    if (this.box) { const [a, ya, b, yb] = this.box; P.path([['M', a, ya - oy], ['L', b, ya - oy], ['L', b, yb - oy], ['L', a, yb - oy], ['Z']],
      { stroke: 'acc', w: 1.2, dash: [4, 3] }); }
    // middle-button drag
    if (this.zband) { const [a, b] = this.zband.map(X).sort((p, q) => p - q); P.rect(a, 0, b - a, Hc, 'acc', 0.15);
      P.path([['M', a, 0], ['L', a, Hc], ['M', b, 0], ['L', b, Hc]], { stroke: 'acc', w: 1 }); }
    // plugin overlays over the cursor
    if (late.length) { g.save(); g.beginPath(); g.rect(0, hdr, W, Hc - hdr); g.clip(); g.translate(0, -oy); late.forEach(f => f()); g.restore(); }
    g.save(); g.translate(0, -oy);
    const geo = paintBookmarks(P, this.bms, this.arrows, X, this.t0, tB, rowY, oy + hdr, oy + Hc, oy + this.hdrH / 2, this.rubber,
      laneY(lay, this.S.laneHeight));
    g.restore();
    return geo;
  }
  // the second cursor (dashed, its Δ on a tag) and the measured range (shaded, its ends dashed, its Δ on a tag): on the
  // screen and in the picture (toSVG); X: time -> x, the waves from xL to xR and yA to yB, tag: [y, h] of the axis band
  paintMeasures(P, X, t0, t1, xL, xR, yA, yB, tag, picture = false) {   // picture: a range that is the whole picture is not shaded
    const box = (lx, tw, t, col, size) => { const [ty, th] = tag; P.rect(lx, ty + 3, tw, th - 6, 'panel');
      P.path([['M', lx, ty + 3], ['L', lx + tw, ty + 3], ['L', lx + tw, ty + th - 3], ['L', lx, ty + th - 3], ['Z']], { stroke: col, w: 1 });
        P.text(lx + tw / 2, ty + th / 2, t, { anchor: 'middle', size, fill: col }); };
    if (this.cursor2 != null && this.cursor2 >= t0 && this.cursor2 <= t1) {
      const x2 = X(this.cursor2), t = this.delta2(), tw = P.measure(t, { size: 10.5 }) + 10;
      P.path([['M', x2, yA], ['L', x2, yB]], { stroke: 'cursor2', w: 1.2, dash: [5, 3] });
      if (tag && !this.range) box(Math.min(Math.max(x2 + 4, xL + 2), xR - tw - 2), tw, t, 'cursor2', 10.5);
    }
    if (this.range && this.range[1] >= t0 && this.range[0] <= t1) {
      const [a, b] = this.range.map(t => Math.min(Math.max(X(t), xL - 1), xR + 1)), t = this.rangeText(), tw = P.measure(t, { size: 11 }) + 10;
      if (!(picture && this.range[0] <= t0 && this.range[1] >= t1)) { P.rect(a, yA, b - a, yB - yA, 'acc', 0.1);
        P.path([['M', a, yA], ['L', a, yB], ['M', b, yA], ['L', b, yB]], { stroke: 'acc', w: 1, dash: [4, 3] }); }
      if (tag) box(Math.min(Math.max((a + b) / 2, xL + tw / 2 + 2), xR - tw / 2 - 2) - tw / 2, tw, t, 'acc', 11);
    }
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
    this.curEl.textContent = 'cursor ' + this.fmtCursor(this.cursor) + ' · view ' + (M.timed ? fmtTime(this.span, this.span / 10,
      this.span) : this.span.toFixed(1) + ' cycles') + (this.cursor2 != null ? ' · cursor 2 ' + this.fmtCursor(this.cursor2) + ' · ' + this.delta2() : '') +
      (this.range ? ' · ' + this.rangeText() : '');
    if (this.bms.length && (this.dtAt !== this.cursor || this.dtGen !== this.notesGen)) {   // the bookmarks' Δ to the cursor
      this.dtAt = this.cursor; this.dtGen = this.notesGen;
      for (const el of this.notesEl.querySelectorAll('li[data-n] .dt')) { const b = this.bms.find(x => x.n === +el.closest('li').dataset.n); if (!b) continue;
        const d = b.t - this.cursor;
        el.textContent = d === 0 ? 'at the cursor' : `${d < 0 ? '−' : '+'}${this.fmt(Math.abs(d), Math.abs(d) / 1000 || 1, Math.abs(d) || 1)}`; }
    }
    if (this.valsAt !== this.cursor || this.valsGen !== this.namesGen || this.valsRadix !== this.S.radix) {   // value column: only when it changes
      this.valsAt = this.cursor; this.valsGen = this.namesGen; this.valsRadix = this.S.radix;
      let vi = 0;
      for (const r of this.vis) if (r.type === 'sig' || r.sig) {   // a struct's row: its whole value
        const el = this.vals[vi++], v = String(this.valueAt(r.sig || r, this.cursor));
        if (el.textContent !== v) { el.textContent = v; el.title = v.length > 6 ? v : ''; }   // cut to its column: the title has it all
      }
    }
  }
  setTheme(name) { applyLook(this.root, name || 'auto', null); this.draw(); return this; }
  setColors(map) { applyLook(this.root, undefined, map); this.draw(); return this; }
  // the viewer leaves: observers, window listeners and pending frames go; plugins hear wavefw:destroy and take their part
  destroy() {
    if (!VIEWS.has(this)) return;
    this.ro.disconnect(); this.ac.abort();   // every listener on the root, the window and the document
    this.help(false);
    cancelAnimationFrame(this.raf); cancelAnimationFrame(this.inv); clearTimeout(this.toastT);
    if (ACTIVE.view === this) ACTIVE.view = null;
    this.closeMenu(); VIEWS.delete(this);
    this.root.dispatchEvent(new CustomEvent('wavefw:destroy'));
    if (this.root.waveView === this) delete this.root.waveView;
  }
}
