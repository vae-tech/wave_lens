/* wavelens/src/bar.js — the bar of a viewer: its tooltips and help, its tools (Bar). */

/* ---------------- tooltips and help ---------------- */
// A control's tooltip: [what it does, in a few words, its keys]; found by its data-act / -sv / -x / -bm / -m value or a
// class (".q"); plugins add theirs (WaveLens.tips.add). A control without one shows its title the same way (boot.js).
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
  'act:dsrc': ['SystemVerilog sources: the names of "typedef enum" on the state buses of a VCD (it has none), "typedef struct packed" as ' +
    'fields; kept for the next read (⟳)'],
  'act:dcmp': ['Compare with a second dump (a VCD of another run): where its values differ, a red band on the row, ≠ on the name', [']d', '[d']],
  'act:dcmpx': ['Compare no more'], 'act:dcmpv': ['Which run the waves show: this one, the second, both over each other', ['d', 'D']],
  'act:fprev': ['Previous match', ['N', 'shift+Enter']], 'act:fnext': ['Next match', ['n', 'Enter']],
  'act:fhl': ['Found rows in front, the rest dimmed'], 'act:fopen': ['Fold the modules without a match'],
  '.fcol': ['Colour for Paint'], 'act:fpaint': ['Paint the found and highlighted signals'], 'act:funpaint': ['Their own colours back'],
  'act:fcopy': ['Copy the paths of the found rows'],
  'act:sort': ['Sort: off → A→Z → Z→A', ['s']], '.pfx': ['Name prefixes ignored when sorting: i_,o_'],
  'act:expand': ['Open every module', ['zR']], 'act:collapse': ['Fold every module', ['zM']],
  'act:hl': ['Clear the highlight', ['Esc']], 'act:unhide': ['Show the hidden rows again'],
  'act:prev': ['Previous edge of the selected signal', ['shift+Tab', '[e']], '.edge': ['Edge kind: any, rising, falling, a value, X / Z', ['e']],
  'act:next': ['Next edge of the selected signal', ['Tab', ']e']], 'act:mark': ['Bookmark at the cursor', ['b']],
  'act:ssave': ['Save the view to a file (.view.json)'], 'act:sload': ['Load a saved view'],
  'act:spage': ['This page as a file (.view.html) with your view in it — bookmarks, groups, colours, cursor, window, assertions: whoever opens ' +
    'it sees what you see, no other file needed'],
  'act:undo': ['Undo the last change of bookmarks, arrows, markers, your groups, colours, radix, analog, hidden rows, the highlight, the edge ' +
    'style, the gaps or the cycles (not the cursor or the window)', ['ctrl+Z']], 'act:redo': ['Redo what was undone', ['ctrl+shift+Z', 'ctrl+Y']],
  'act:help': ['Keys and mouse', ['?']],
  'act:theme': ['The theme: auto (the system\'s light or dark), light, white, dark; kept in this browser. In VS Code: its list, with VS ' +
    'Code\'s own colours too'],
  'act:scroll': ['The rows scroll in a window of their own (the bar above them), or with the page (the bar sticks to the top); kept in this browser'],
  'act:tools': ['Fold the tools to this line, or open them (/ opens them for the find field)'], 'jump': ['Go to this marker'],
  '.mk': ['Highlight: in front, the rest dimmed', ['ctrl+click', 'ctrl+shift+click: every row to here']],
  'bm:json': ['The bookmarks and arrows as JSON for a config'], 'bm:clear': ['Remove this browser\'s bookmarks'],
  'bm:go': ['Go to this bookmark', [']b', '[b']], 'bm:here': ['Move it to the cursor'],
  'bm:lift': ['Into a lane of its own: over its signal, then under it, then on the row again (or drag the circle to the top or the bottom of its row)'],
    'bm:del': ['Delete the bookmark and its arrows'],
  'bm:addar': ['Arrow between the last two bookmarks', ['shift+drag a circle']], 'bm:adel': ['Delete the arrow'],
  '.tm': ['Bookmark time: 250ns, 85.12us', ['Enter']], '.sig': ['Its signal (empty: the time axis)', ['Enter']], '.txt': ['What happens here'],
  '.lbl': ['A short label by the circle on the waves'],
  '.col': ['Colour'], '.lab': ['Arrow label: {dt} the time between its ends, {cycles} the clock cycles, {cycles:CLK} the rising edges of CLK'],
  '.from': ['From bookmark'], '.to': ['To bookmark'], '.shape': ['Arrow shape'], '.head': ['Arrow head'],
    '.line': ['Line'],
  'm:zoom': ['Zoom to the range', ['shift+drag', 'middle drag']], 'm:marks': ['Bookmarks at its ends, an arrow with Δ'], 'm:copyd': ['Copy Δ'],
  'm:copyimg': ['The range (else the window) as PNG to the clipboard: the highlighted rows, else the ones on the screen'], 'm:png': ['Save the picture as PNG'],
    'm:svg': ['Save the picture as SVG'],
  'm:c2': ['A second cursor: Δ to the cursor in time and clock cycles', ['shift+click']], 'm:c2x': ['No second cursor', ['Esc']],
  'm:analog': ['The bus as a step plot, three rows high (its radix: signed, float, fixed)'],
  'm:dup': ['The same signal again in a row under it, with a radix, an analog form and a colour of its own'],
  'm:undup': ['This copy out of the waves: a bookmark on it goes to its signal'],
  'm:bits': ['The bus bit by bit: a row per bit under it, the highest first (a click on its width [7:0] does it too)', ['B']],
  'm:wdjson': ['The range as a WaveDrom file (.json): the highlighted signals, else the ones on the screen, a cell per clock cycle'],
    'm:wdcopy': ['The same WaveDrom to the clipboard'],
  '.gon': ['Gaps: the picture and WaveDrom leave out the stretches where the signals (the clocks aside) do not change, a break "|" there'],
  '.gview': ['The waves themselves with the gaps cut out: scroll and zoom them, every change of a gap setting shows at once; a picture saved is what ' +
    'you see', ['gv']],
  '.bgi': ['A gap where nothing changes this long: clock cycles (16) or a time (2us); the waves follow as you type'],
  '.bgk': ['Kept after a change and before the next one: cycles or a time'], 'act:gapvx': ['The waves in continuous time again', ['gv']],
  '.gi': ['A gap where nothing changes this long: clock cycles (16) or a time (2us)'], '.gk': ['Kept after a change and before the next one: cycles or a time'],
  'm:gref': ['The gaps follow the changes of these signals only (marked // in the names); none: of every signal in the picture'],
  'm:grefx': ['The gaps by every signal in the picture again'],
  'm:gbyx': ['The waves no more cut to the matches of expressions (✂ off in their list)'],
  'm:gclk': ['The gaps count in cycles of this clock (idle, keep, the cycles of a gap; marked ↑ in the names); its edges are no change'],
  'm:gclkx': ['The cycles of the clock found again (the selected one, else the nearest *clk*)'],
  'm:greset': ['Every gap setting of this viewer back to the settings (the roles, the counts, idle, keep; by default no gaps)'],
  '.subh': ['The gaps of the picture and WaveDrom: on / off, idle, keep, the signals they follow and count, the texts'],
  'm:gaux': ['Count what this signal did in the stretches left out (marked + in the names): its edges, a bus its changes, in a thin row under it ' +
    'over each gap'],
  'm:gauxx': ['Count every signal but the ones the gaps follow again'],
  '.gonly': ['The picture and WaveDrom: only the signals the gaps follow'],
  '.gcnt': ['The texts of the gaps: under the axis the time left out and the clock cycles; under each signal marked + what it did there (its ' +
    'edges, its changes); none marked, "+ changes in a gap": under every one but the ones the gaps follow; or no texts'],
  'm:hl': ['Highlight', ['ctrl+click']], 'm:hide': ['Leave it out of the view'], 'm:unhide': ['Show the hidden rows'],
  'm:fold': ['Fold / open this module'], 'm:foldup': ['Fold its module', ['zc']], 'm:zM': ['Fold every module', ['zM']], 'm:zR': ['Open every module', ['zR']],
  'm:types': ['Where its labels or fields come from: the types file and the path in it, the width, why it has none'],
  'm:mark': ['Bookmark on this signal here: its text asked here, then in the list', ['b']],
  'm:copyname': ['Copy the path', ['yy']], 'm:copylink': ['Copy a link to this moment: the page opened by it goes here', ['yl']],
  'm:clear': ['Clear the range', ['Esc', 'ctrl+click']],
  'm:unpaint': ['Its own colour back'],
  'm:umark': ['A marker here: a dashed line across the rows; its label asked here. Drag the text to a line over or under any signal; the right ' +
    'button on it: its colour', ['m']],
  'm:mlist': ['The markers and bookmarks in a list: ↑ ↓ go through them, the waves follow', ['gm']],
  'm:ugnew': ['A group of your own at the top of the names'],
  'm:ugout': ['Out of your group (the signal stays in its module)'], 'm:ugdel': ['Delete your group; its signals stay where they are'],
  'm:mvup': ['One place up in your group (a selected run: as a block; a group: among yours)', ['alt+↑', 'drag the name']],
  'm:mvdn': ['One place down in your group (a selected run: as a block; a group: among yours)', ['alt+↓', 'drag the name']],
  'm:mvtop': ['First in your group (a group: the first of yours)'], 'm:mvbot': ['Last in your group (a group: the last of yours)'],
  'm:ugfold': ['Fold / open your group'],
  'bm:mdel': ['Delete the marker'], 'bm:gdel': ['Delete your group; its signals stay where they are'], '.mt': ['Marker time: 250ns, 85.12us', ['Enter']],
  '.ml': ['Marker label'],
  '.msig': ['The signal whose line, over or under it, has the text of the marker; empty: at the top of the rows', ['Enter']],
  'bm:mlift': ['The text over its signal or under it'], 'bm:mpale': ['The pale colour of a marker again'],
  'm:mktext': ['Change the text of this marker'], 'm:mkpale': ['The pale colour of a marker again'], 'm:mkdel': ['Delete this marker'],
  '.ugn': ['Group name', ['Enter']],
  'act:live': ['Driven by an agent (tools/wavemcp.py view_live): its edits come in as you watch; click: disconnect'],
};
TIPS['.subg'] = ['Your groups: put the signals into one, a new one, go to one', ['ctrl+G', 'gl']];
Object.assign(TIPS, { '.subc': ['The clock cycles in a band under the time axis: numbered from cycle 0, the cursor\'s in the title, Δ in them; ' +
  'c147 in the cursor field goes to cycle 147'], 'm:cycon': ['The band of cycle numbers under the time axis'],
  'm:cyclk': ['Count the cycles of this clock (its rising edges)'], 'm:cyc0': ['The rising edge at or before the time clicked is cycle 0'],
  'm:cycx': ['The cycles as the page sets them (cycles, cycleClock, cycleZero)'] });
TIPS['m:ugto'] = ['Into your group (a folder at the top of the names)']; TIPS['m:ugoff'] = ['Out of this group of yours'];
TIPS['m:ugo'] = ['Go to the group: opened, in the middle, its first signal selected', ['ctrl+G', 'gl']];
// the Modules panel (modules.js) and Only
Object.assign(TIPS, { 'act:mods': ['The modules as a tree: a click goes to one, a box over names keeps Only those on the waves', ['t']],
  'act:onlyp': ['Only these modules on the waves (with their submodules): a click pauses it (every module), again resumes it'],
  'act:onlyx': ['Every module on the waves again (Only cleared)'], 'm:mods': ['The modules as a tree: go to one, keep Only some', ['t']],
  'm:locate': ['The module of this row in the tree of the modules', ['t']], 'm:onlyp': ['Only paused: every module; resumed: the set again'],
  'm:onlyx': ['Every module on the waves again (Only cleared)'] });
// the FSM panel (fsm.js) and its layer
Object.assign(TIPS, { 'act:fsms': ['The state machines (signals with enum labels) in the tree of their modules: go to one, Only them, add them to the view',
  ['T']], 'act:fsmx': ['The view without the FSM layer (Only FSMs / the FSMs added)'], 'm:fsms': ['The state machines in the tree of their modules', ['T']],
  'm:fsmx': ['The view without the FSM layer'] });
// the help (? in the bar, key ?): the keys and the mouse by what they do; plugins' keys come from their addKey help
const HELP = [
  ['Zoom and move', [[['i', '+'], 'zoom in'], [['o', '-'], 'zoom out'], [['f'], 'show everything'], [['l'], 'the window before the last zoom'],
    [['c'], 'zoom in on the cursor'],
    [['ctrl+wheel', 'pinch'], 'zoom at the pointer'], [['wheel'], 'scroll the rows'], [['shift+wheel', 'drag', '←', '→'], 'pan'],
      [['shift+drag', 'middle drag'], 'zoom into a range'], [['Home', 'End'], 'the start / end'], [['PgUp', 'PgDn'], 'a page of rows']]],
  ['Cursor and edges', [[['click'], 'cursor on a near edge (alt: not) + select the signal'], [['shift+←', 'shift+→'], 'move the cursor'],
    [['Tab', 'shift+Tab'], 'next / previous edge (no signal selected: the focus moves on)'], [[']e', '[e'], 'next / previous edge'], [['e'], 'edge kind']]],
  ['Signals', [[['↑', '↓', 'j', 'k'], 'select the next / previous'], [['shift+click a name'], 'select every signal from the last clicked one'],
    [['gg', 'G'], 'the first / last'], [['ctrl+G', 'gl'], 'your groups: a list, a click goes there'],
    [['gv'], 'the waves with the gaps cut out, or in continuous time'],
    [['alt+↑', 'alt+↓'], 'the selected signal up / down in your group (shift: the group); or drag it in the names'],
    [['ctrl+click', '○'], 'highlight'], [['ctrl+shift+click'], 'highlight every row from the last one to it'],
    [['zM', 'zR'], 'fold / open every module'], [['t'], 'the modules as a tree: a click goes to one, a box keeps Only those (again: the selected one\'s)'],
    [['T'], 'the state machines in the tree of their modules: go to one, Only them, add them to the view'],
    [['zc', 'zo', 'za'], 'the selected signal\'s module'], [['B', 'click [7:0]'], 'the selected bus bit by bit (again: folded)'],
    [['s'], 'sort'], [['yy', 'ctrl+C'], 'copy the path'],
      [['Esc'], 'reset: search, highlight, selection']]],
  ['Find', [[['/', 'ctrl+F'], 'find (the bar scrolled away: it floats over the waves)'],
    [['alt+C', 'alt+W', 'alt+R'], 'in the field: match case, full match, regular expression'], [['n', 'N', 'Enter'], 'next / previous match'],
    [['*', '#'], 'find the selected name: its next / previous match']]],
  ['Measure and mark', [[['shift+click'], 'a second cursor: Δ to the cursor, in cycles of the clock'], [['x'], 'swap the cursors'],
    [['c147'], 'in the cursor field: cycle 147 of the clock (right button: Cycles ▸, a band of them under the axis)'],
    [[']d', '[d'], 'next / previous difference from a dump compared (Compare… in the bar)'],
    [['d'], 'a dump compared: flip the waves between the two runs (the time axis names the one shown)'],
    [['D'], 'a dump compared: both runs over each other where they differ, again one'],
    [['1', '…', '9'], 'go to bookmark 1 … 9'], [['ctrl+drag'], 'measure a range: Δ, the edges or changes of that signal'],
    [['alt+drag'], 'a box: its time and its signals, then the menu (picture, WaveDrom, colour)'], [['ctrl+click'], 'clear the range'],
    [['right button'], 'a range and the menu: picture, colour, radix, duplicate, hide'], [['b'], 'bookmark at the cursor'],
    [[']b', '[b'], 'next / previous bookmark'], [['m'], 'marker at the cursor: its label asked'], [[']m', '[m'], 'next / previous marker'],
    [['gm'], 'the markers and bookmarks: a list, ↑ ↓ go through them'], [['drag a bookmark'], 'move it'],
    [['drag a marker\'s text'], 'to a line over or under a signal, along the time (alt: the time stays)'],
    [['drag a Δ'], 'between markers (Δ between markers in their list): up and down, to a line over or under a signal; its dot along, to another marker'],
    [['shift+drag a bookmark'], 'an arrow to another one']]],
  ['The bar', [[['right button'], 'on the bar: which of its tool groups it shows (Show all, Hide all, a tick each)'],
    [['▴', '▾ tools'], 'fold the tools to the title line / open them'], [['r'], 'the last state loaded, read again (Reload)'],
    [['R'], 'the dump read again from the disk, the view kept (⟳)']]],
  ['Menus', [[['g'], 'a moment after it: a box with what can follow, press the key or click it: go to, markers and bookmarks, the state, the dump'],
    [['z', 'y', '[', ']'], 'the same box: fold, copy, next, previous'], [['Esc'], 'with the box open: closes it, nothing else'],
    [['t', 'T'], 'the panels of the modules, the state machines'], [['gm', 'gl'], 'the lists of the markers and bookmarks, your groups'],
    [['right button'], 'on the waves or a name: the menu of what is there']]],
  ['Undo', [[['ctrl+Z'], 'undo the last change of bookmarks, arrows, groups, colours, radix, hidden rows, highlight'],
    [['ctrl+shift+Z', 'ctrl+Y'], 'redo']]],
  ['Help', [[['?'], 'this box'], [['hover a button'], 'what it does, its keys']]],
];

// what the box shows after the first key of a sequence (keyHintOn): prefix -> [title, rows]; a row: [heading], or [second key, its text
// (or fn(view)), shown? (fn(view))]. The keys are seq()'s; a plugin's sequences with a help text come after them
const barBtn = (v, a) => { const b = v.root.querySelector(`.bar [data-act=${a}]`); return b && !b.hidden ? b : null; };
const onBar = a => v => !!barBtn(v, a), anyMark = v => v.bms.length || v.umarks.length;
const KEY_MENUS = {
  g: ['Menu', [['Go to'], ['g', 'the first signal'], ['l', 'your groups…'], ['t', 'the modules…', v => v.scopes().length],
    ['T', 'the state machines…', v => v.fsms().length],
    ['Markers and bookmarks'], ['m', 'the list of them…', anyMark], ['M', 'a marker at the cursor'], ['B', 'a bookmark at the cursor'],
    ['d', v => (v.deltas ? 'hide the Δ between markers' : 'show the Δ between markers'), v => v.umarks.length], ['c', 'clear them all', anyMark],
    ['The state'], ['s', 'save…', onBar('ssave')], ['L', 'load…', onBar('sload')], ['r', 'reload', v => v.root.wlState],
    ['The dump'], ['O', 'open…', onBar('dopen')], ['R', 'reload', v => v.opts.dumpSrc], ['C', 'compare…', onBar('dcmp')],
    ['More'], ['v', v => (v.gapLive() ? 'the waves in continuous time' : 'the gaps cut out of the waves')], ['p', 'save the page', onBar('spage')]]],
  z: ['Fold the modules', [['R', 'open every module'], ['M', 'fold every module'], ['o', 'open the selected signal\'s'], ['c', 'fold the selected signal\'s'],
    ['a', 'open or fold it']]],
  y: ['Copy', [['y', 'the selected signal\'s path'], ['n', 'its name'], ['t', 'the time of the cursor'], ['l', 'a link to here (the cursor, the signal)']]],
  ']': ['Next', [['b', 'bookmark'], ['m', 'marker'], ['e', 'edge'], ['d', 'difference', v => v.cmp]]],
  '[': ['Previous', [['b', 'bookmark'], ['m', 'marker'], ['e', 'edge'], ['d', 'difference', v => v.cmp]]],
};

const WD_CELLS = 2048;   // the cycles a WaveDrom export keeps at most (the rest of the range is said, not dropped silently)
const KIND_MARK = { struct: '{}', union: '∪', interface: '⊟' };
// the find group's options: [button, viewer property = setting, label, title, alt+ key code]
// the find's view buttons: data-act -> the viewer's flag, its setting
const FIND_VIEW = { fhl: ['findHl', 'findHighlight'], fopen: ['findOpen', 'findOpen'], fmask: ['findMask', 'findMask'] };
const FIND_OPTS = [
  ['fcase', 'findCase', 'Aa', 'Match case (alt+C)', 'KeyC'],
  ['fword', 'findWord', 'Full', 'Full match: a word is the whole name, a.b the end of the full path (alt+W)', 'KeyW'],
  ['fre', 'findRegex', '.*', 'Regular expression on the name or the full path, as grep -E (JavaScript RegExp; \\< \\> as in vim; alt+R)', 'KeyR'],
];

// the bar's tools, one line per kind of work: where you are in time (cursor, zoom, edges, jumps), the signals by name
// and the times by a condition (find; sva.js: expression), the rows and the files (list, edge style, state, assertions)
const TOOL_LINES = { cursor: 'time', view: 'time', edges: 'time', 'go to': 'time', find: 'find', expression: 'find', list: 'rows', style: 'rows', state: 'rows',
  dump: 'rows', assertions: 'rows' };
const toolLine = (ln, html) => `<div class="tln" data-ln="${ln}">${html}</div>`;

// a WaveDrom document as text: a signal (or a group) per line, as hand-written WaveJSON looks
const wdText = d => '{ "signal": [\n' + d.signal.map(s => Array.isArray(s)
  ? `  [${JSON.stringify(s[0])},\n` + s.slice(1).map(x => '    ' + JSON.stringify(x)).join(',\n') + ']' : '  ' + JSON.stringify(s)).join(',\n') +
  '\n],\n' + Object.keys(d).filter(k => k !== 'signal').map(k => `  ${JSON.stringify(k)}: ${JSON.stringify(d[k])}`).join(',\n') + '\n}';

// the version, and the build the page carries (WAVELENS_BUILD {branch, commit, dirty, tag, date, by}: mkhtml.py writes the
// one of its checkout, the VS Code extension its own) -> [text, tooltip]; a page without one: the version alone
function buildText() {
  const b = G.WAVELENS_BUILD, ver = (G.WaveLens && G.WaveLens.version) || '';
  if (!b || !b.commit) return [ver, `WaveLens ${ver}`];
  const br = b.branch && b.branch !== 'HEAD' ? b.branch : '';
  return [`${ver} · ${br ? br + '@' : ''}${b.commit}${b.dirty ? '*' : ''}`, `WaveLens ${ver} · ${br ? `branch ${br}, ` : ''}commit ${b.commit}` +
    (b.dirty ? ' with changes not committed (*)' : '') + (b.tag ? ` (${b.tag})` : '') + (b.date ? ` · made ${b.date}` : '') + (b.by ? ` by ${b.by}` : '')];
}
// the bar's ◐: themeButton true, or 'auto' and the page has no theme button of its own (viewer.html, the VS Code tab)
const themeButtonOn = S => S.themeButton === true || (S.themeButton === 'auto' && !document.querySelector('button#theme'));
const THEME_CYCLE = ['auto', 'light', 'white', 'dark'];

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
        `<button type="button" data-act="fopen" aria-pressed="${!!S.findOpen}" title="Every module folded except the ones with a match">Open</button>`,
        `<button type="button" data-act="fmask" aria-pressed="${!!S.findMask}" title="The found rows only (and the modules on the way to them)">Mask</button>`),
      seg(`<input type="color" class="fcol" value="${/^#[0-9a-f]{6}$/i.test(paint) ? paint : '#d6336c'}" aria-label="paint colour" title="Colour for Paint">`,
        ('<button type="button" data-act="fpaint" title="Paint the found and the highlighted signals in this colour (none: the selected one; kept in this ' +
          'browser)">Paint</button>')),
      (`<button type="button" data-act="funpaint" title="Back to the signals' own colours" hidden>Unpaint</button><button type="button" data-act="fselect" ` +
          `title="Select the found signals: the right button then takes them all (a new group, colour, radix, hide …); ctrl+click: add them to the ` +
          `selection">Select</button><button type="button" data-act="fcopy" ` +
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
      '<button type="button" data-act="collapse" title="Collapse all groups">Collapse</button>',
      '<button type="button" data-act="mods" title="The modules as a tree (t)">Modules</button>' +
        (v.fsms().length ? '<button type="button" data-act="fsms" title="The state machines as a tree (T)">FSMs</button>' : '')) : '',
      '<button type="button" data-act="hl" title="Clear the highlight (Esc)" hidden></button>',
        '<button type="button" data-act="unhide" title="Show the rows hidden with the right button\'s menu again" hidden></button>',
      '<button type="button" data-act="onlyp" title="Only these modules: a click pauses it" hidden></button><button type="button" data-act="onlyx" ' +
        'title="Every module again" aria-label="clear Only" hidden>✕</button>',
      '<button type="button" data-act="fsmx" title="The view without the FSM layer" hidden></button>');
    const edges = grp('edges', seg('<button type="button" data-act="prev" title="Previous edge of the selected signal, or of any shown signal ([e)">◀</button>',
      (`<select class="edge" aria-label="edge kind" title="Edge kind (e): any, rise, fall, a value, X / ` +
          `Z">${Object.entries(EDGE_KINDS).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select>`),
      ('<input type="text" class="ev" spellcheck="false" hidden placeholder="0x40, \'h40, 64, IDLE" aria-label="value to find" title="The value to find: ' +
          ('0x40, \'h40, 8\'d64, 64, -3, \'b101, or a text (an enum label); Enter / shift+Enter: the next / previous time the selected signal (none: any ' +
          'shown) becomes it">')),
      '<button type="button" data-act="next" title="Next edge (]e)">▶</button>'),
        '<button type="button" data-act="mark" title="Bookmark at the cursor, on the selected signal (b)">+ Mark</button>');
    const state = grp('state',
      ('<button type="button" data-act="ssave" title="Save what you did in this viewer to a file: the window, the cursor, the order, the folding, the ' +
        'highlight, the paint, the bookmarks and arrows, the search, the assertions and the expressions">Save</button>'),
      ('<button type="button" data-act="sload" title="Load a saved file into this viewer (what is not in these waves is left out)">Load…</button><input ' +
          'type="file" class="sfile" accept=".json,application/json" hidden>'),
      '<button type="button" data-act="sreload" title="Read the state loaded last again (r)" hidden>Reload</button>',
      '<button type="button" data-act="spage" class="spage">Save page</button>',
      '<button type="button" class="live" data-act="live" hidden></button>');
    // dump: a VCD read in the page (Open…, or a file dropped on the viewer), ⟳ reads it again from the disk keeping the view
    const dump = grp('dump',
      ('<button type="button" data-act="dopen" title="Open a VCD dump in this viewer (or drop one on it): its signals by scope, exact ' +
        'transitions">Open…</button>'),
      ('<button type="button" data-act="dreload" title="Read the dump again from the disk; the view, the folding and the bookmarks stay (R)" ' +
          'hidden>⟳</button><input type="file" class="dfile" accept=".vcd,.fst" hidden>'),
      ('<button type="button" data-act="dcmp">Compare…</button><button type="button" data-act="dcmpx" class="cmpx" hidden></button>' +
        '<span class="seg cmpv" hidden><button type="button" data-act="dcmpv" data-run="a" aria-pressed="true">A</button>' +
        '<button type="button" data-act="dcmpv" data-run="b" aria-pressed="false">B</button>' +
        '<button type="button" data-act="dcmpv" data-run="overlay" aria-pressed="false">A+B</button></span>' +
        '<input type="file" class="cfile" accept=".vcd" hidden>'),
      '<button type="button" data-act="dsrc" title="SystemVerilog sources, or the design\'s types (x.types.json: Questa, Verilator)">Sources…</button>' +
      '<input type="file" class="srcfile" accept=".sv,.svh,.v,.vh,.json" multiple hidden>');
    const zoom = seg('<button type="button" data-act="out" title="Zoom out (−)">−</button>',
      '<button type="button" data-act="in" title="Zoom in (+)">+</button>', '<button type="button" data-act="fit" title="Show everything (0)">Fit</button>') +
      ('<span class="gapv" hidden>gaps idle <input type="text" class="bgi" spellcheck="false" aria-label="gaps: idle this long"> keep <input type="text" ' +
        'class="bgk" spellcheck="false" aria-label="gaps: kept around a change"><button type="button" data-act="gapvx" aria-label="the gaps off the ' +
        'waves">✕</button></span>');
    const hint = 'Wheel: scroll · ctrl+wheel: zoom · shift+wheel / drag: pan · shift or middle drag: zoom to a range · ctrl+drag: measure · ' +
      'alt+drag: a box of time and signals · click: cursor (on a near edge; alt: not) + select a signal · keys on the waves (as in Questa): ' +
      'i o zoom in / out, f full, l last, c in on the cursor · ← → pan, Home End · shift+← → cursor · ↑ ↓ (j k) select, gg G first / last · ' +
      'Tab shift+Tab next / previous edge, e edge kind · / ctrl+F find, n N next / previous match, * # the selected name · ' +
      `b bookmark, ]b [b next / previous, m marker, ]m [m · zM zR fold / open all, zc zo the selected module${groups ? ' · t modules' : ''} · ` +
      `yy ctrl+C copy${S.sortButton ? ' · s sort' : ''} · ` +
      `Esc reset${groups ? ' · click a module to fold it' : ''} · shift+click a name: select every signal to it · ` +
      '○ or ctrl+click a name: highlight, ctrl+shift+click: every row to it';
    const [ver, verTip] = buildText();
    return `<div class="bar"><div class="head"><span
      class="eyebrow">${esc(v.opts.title || v.M.title || 'Waveform').replace(/µ/g, '<span class="mu">µ</span>')}</span><span class="toast" role="status"
        aria-live="polite"></span><span class="cur"></span>${S.version ? `<span class="ver" title="${esc(verTip)}">${esc(ver)}</span>` : ''}${
        themeButtonOn(S) ? '<button type="button" data-act="theme" class="lay" aria-label="theme">◐</button>' : ''}<button type="button"
        data-act="undo" class="lay undo" disabled aria-label="undo">↶</button><button
        type="button" data-act="redo" class="lay undo" disabled aria-label="redo">↷</button><button type="button" class="lay" data-act="scroll"></button><button
        type="button" class="lay" data-act="tools" aria-label="fold the tools"></button><button type="button" class="hb" data-act="help"
        aria-label="keys and mouse">?</button></div>
      <div class="tools">${toolLine('time', grp('cursor', cursor) + grp('view', zoom) + edges + (jumps ? grp('go to', jumps) : ''))}${toolLine('find', find)}${
        toolLine('rows', list + grp('style', wstyle) + state + dump)}</div></div>
      <div class="body"><div class="names"></div><div class="wcol"><canvas tabindex="0" role="application" aria-roledescription="waveform"
        aria-label="waveform: + − zoom, ← → pan, shift+← → move the cursor, ↑ ↓ select a signal, [e ]e or Tab edges"></canvas></div></div>
      <div class="notes" hidden></div>
      <div class="wlog" hidden></div>
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
      const opt = e.altKey && !keyLeft(v.S, e) && FIND_OPTS.find(o => o[4] === e.code);   // alt+C W R, as in VS Code (by the key's place: any layout)
      if (opt) { e.preventDefault(); v.setFindOpt(opt[1], !v[opt[1]]); }

    });
    v.evEl = r.querySelector('input.ev');
    v.edgeSel.addEventListener('change', () => v.setEdgeKind(v.edgeSel.value, true));
    const gv = r.querySelector('.gapv'), bgi = gv.querySelector('.bgi'), bgk = gv.querySelector('.bgk');   // idle, keep: the waves follow as they are typed
    gv.addEventListener('input', () => v.gapType(() => v.gapFields(bgi, bgk, true)));
    gv.addEventListener('change', e => { if (e.target.matches('input')) { clearTimeout(v.gapTypeT); v.setGaps(v.gapFields(bgi, bgk)); } });
    v.syncGapBar();
    v.evEl.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); v.edge(e.shiftKey ? -1 : 1); } });
    v.wsEl = r.querySelector('select.ws'); v.wsEl.addEventListener('change', () => v.setStyle(v.wsEl.value));
    r.querySelector('.bar').addEventListener('contextmenu', e => {   // the right button on the bar: which tool groups it shows (a field: the browser's)
      if (!v.S.contextMenu || e.target.closest('input, select, textarea')) return; e.preventDefault(); v.toolsMenu(e.clientX, e.clientY); });
    r.querySelector('.bar').addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b) return;
      if (b.dataset.act === 'in') v.zoom(0.5, 0.5);
      else if (b.dataset.act === 'out') v.zoom(2, 0.5);
      else if (b.dataset.act === 'fit') v.fit();
      else if (b.dataset.act === 'sort') v.setSort(SORTS[(SORTS.indexOf(v.sort) + 1) % SORTS.length]);
      else if (b.dataset.act === 'hl') v.highlight(null);
      else if (b.dataset.act === 'unhide') v.unhide();
      else if (b.dataset.act === 'mods') v.modules();
      else if (b.dataset.act === 'fsms') v.fsmPanel();
      else if (b.dataset.act === 'theme') v.themeNext();
      else if (b.dataset.act === 'fsmx') { v.setFsm(null); v.toast('the view without the FSM layer'); }
      else if (b.dataset.act === 'onlyp') v.setOnly({ on: !v.only.on });
      else if (b.dataset.act === 'onlyx') { v.setOnly(null); v.toast('Only: every module again'); }
      else if (b.dataset.act === 'expand') v.expandAll();
      else if (b.dataset.act === 'collapse') v.collapseAll();
      else if (b.dataset.act === 'prev' || b.dataset.act === 'next') v.edge(b.dataset.act === 'next' ? 1 : -1);
      else if (b.dataset.act === 'mark') v.mark();
      else if (FIND_VIEW[b.dataset.act]) {
        const k = FIND_VIEW[b.dataset.act][0]; v[k] = !v[k]; b.setAttribute('aria-pressed', v[k]); v.find(v.q || '', k === 'findOpen');
      }
      else if (FIND_OPTS.some(o => o[0] === b.dataset.act)) { const k = FIND_OPTS.find(o => o[0] === b.dataset.act)[1]; v.setFindOpt(k, !v[k]); }
      else if (b.dataset.act === 'fpaint') v.paint(v.fcol.value);
      else if (b.dataset.act === 'funpaint') v.unpaint();
      else if (b.dataset.act === 'cset') v.setCursor(v.ctEl.value);
      else if (b.dataset.act === 'cshow') v.showCursor(v.csEl.value);
      else if (b.dataset.act === 'fnext' || b.dataset.act === 'fprev') v.findStep(b.dataset.act === 'fnext' ? 1 : -1);
      else if (b.dataset.act === 'fdock') { v.floatFind(false); v.refocus(); }
      else if (b.dataset.act === 'fselect') v.selectFound(e.ctrlKey || e.metaKey);
      else if (b.dataset.act === 'fcopy') v.copyRows(v.allRows().filter(r => v.found.has(r)));
      else if (b.dataset.act === 'ssave') v.saveState();
      else if (b.dataset.act === 'spage') { try { const n = savePage(); v.toast('saved ' + n); v.log('ok', 'saved the page: ' + n); }
        catch (e) { v.toast(e.message); v.logError(e, 'cannot save the page: ' + e.message); } }
      else if (b.dataset.act === 'undo' || b.dataset.act === 'redo') v.undo(b.dataset.act === 'undo' ? -1 : 1);
      else if (b.dataset.act === 'help') v.help();
      else if (b.dataset.act === 'scroll') v.setScroll(v.S.maxHeight != null && v.S.maxHeight !== '' ? 'page' : 'window');
      else if (b.dataset.act === 'tools') v.setTools(!v.S.toolsFolded);
      else if (b.dataset.act === 'sload') v.pickState();
      else if (b.dataset.act === 'sreload') v.reloadState();
      else if (b.dataset.act === 'dopen') v.openDump();
      else if (b.dataset.act === 'gapvx') v.setGaps({ gapView: false });
      else if (b.dataset.act === 'dcmp') v.cfile.click();
      else if (b.dataset.act === 'dcmpx') { if (v.cmpReading) v.compareStop(); else v.compare(null); }
      else if (b.dataset.act === 'dcmpv') v.compareView(b.dataset.run);
      else if (b.dataset.act === 'dsrc') v.srcfile.click();
      else if (b.dataset.act === 'dreload') v.reloadDump();
      else if (b.dataset.act === 'live') liveClick();
      else if (b.dataset.jump !== undefined) { const j = v.jumps[b.dataset.jump]; v.goto(j.t, j.span); }
    });
    v.dfile = r.querySelector('input.dfile');
    v.dfile.addEventListener('change', () => { const f = v.dfile.files[0]; v.dfile.value = ''; if (f) v.openDump(f); });
    v.cfile = r.querySelector('input.cfile');
    v.cfile.addEventListener('change', () => { const f = v.cfile.files[0]; v.cfile.value = ''; if (f) v.compare(f); });
    v.srcfile = r.querySelector('input.srcfile');
    v.srcfile.addEventListener('change', () => { const fs = [...v.srcfile.files]; v.srcfile.value = ''; if (fs.length) v.setSources(fs); });
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
      if (f && /\.json$/i.test(f.name)) v.loadState(f, h); else if (f) v.openDump(f, h);
    }, own);
    v.sfile = r.querySelector('input.sfile');
    v.sfile.addEventListener('change', () => { const f = v.sfile.files[0]; v.sfile.value = ''; if (f) v.loadState(f); });
    v.stateBtn = r.querySelector('button[data-act=sreload]'); v.stateShow();
    if (!r.wlState && G.showOpenFilePicker) stateDb('readonly', s => s.get('last')).then(h => { if (h && !r.wlState) { r.wlState = h;
      if (r.waveView) r.waveView.stateShow(); } }).catch(() => { /* no database here */ });
    const pfx = r.querySelector('input.pfx');
    if (pfx) pfx.addEventListener('input', () => { v.fitPfx(); v.setSort(v.sort, pfx.value); });
    v.fitPfx();
  }
}
