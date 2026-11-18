/* wavelens/src/bar.js — the bar of a viewer: its tooltips and help, its tools (Bar). */

/* ---------------- tooltips and help ---------------- */
// A control's tooltip: [what it does, in a few words, its keys]; found by its data-act / -sv / -x / -bm / -m value or a
// class (".q"); plugins add theirs (WaveLens.tips.add). A control without one shows its title the same way (boot.js).
const TIPS = {
  '.ct': ['Cursor time: 85.12us, c147 (a clock cycle), or a number in the unit; Esc: as it was', ['Enter', 'Esc']],
  '.cs': ['The window\'s span, centred on the cursor: 200ns, or a number in the unit; Esc: as it was', ['Enter', 'Esc']],
  '.cu': ['Unit of the cursor and span fields'],
  'act:out': ['Zoom out', ['o', '-', 'ctrl+wheel']], 'act:in': ['Zoom in', ['i', '+', 'ctrl+wheel']], 'act:fit': ['Show everything', ['f']],
  'act:zlast': ['The window before the last zoom', ['l']], 'act:zcur': ['Zoom in on the cursor', ['c']],
  'act:zrange': ['Zoom to the range, else to the two cursors', ['zz', 'shift+drag', 'middle drag']], 'act:t0': ['The start', ['Home']],
  'act:t1': ['The end', ['End']],
  '.ws': ['Edge style: auto, slanted (WaveDrom), vertical (simulator), square'],
  '.q': ['Fuzzy find: letters in order, a.b for paths', ['/', 'ctrl+F', 'Enter', 'Esc']], 'act:fdock': ['Back into the bar', ['Esc']],
  'act:fcase': ['Match case', ['alt+C']], 'act:fword': ['Full match: the whole name (a.b: the end of the path)', ['alt+W']],
    'act:fre': ['Regular expression (as grep -E; \\< \\> as in vim)', ['alt+R']],
  '.ev': ['The value to find (0x40, \'h40, 64, -3, IDLE)', ['Enter', 'shift+Enter']],
  'act:dopen': ['Open a VCD dump here (or drop it on the viewer)', ['gO']], 'act:dreload': ['Read the dump again, the view kept', ['R']],
  'act:dsrc': ['SystemVerilog sources: the names of "typedef enum" on the state buses of a VCD (it has none), "typedef struct packed" as ' +
    'fields; kept for the next read (⟳)'],
  'act:dcmp': ['Pick a second dump (a VCD of another run) as B; Compare then shows where its values differ over the window in sight: a red band on the ' +
    'row, ≠ on the name', ['gC', 'g=', ']d', '[d']],
  'act:druns': ['The runs kept of this dump (VS Code): keep this one with a name, tags, a comment; show one here (A), compare one with it (B) ' +
    'over the waves in sight or a span of yours', ['gu', ']w', ']r']],
  'act:dcmpx': ['Compare no more (B picked: dropped)'],
  'act:dcmpgo': ['Compare A and B over the window in sight (your span chosen in the Runs panel: that span); zoomed or panned since: Compare again', ['g=']],
  'act:dcmpm': ['▒: the red mask over the differences, on or off (off: d flips between the two runs alone; ≠ and ]d [d stay)',
    ['gb']], 'act:dcmpv': ['Which run the waves show: this one, the second, both over each other', ['d', 'D']],
  'act:fprev': ['Previous match', ['N', 'shift+Enter']], 'act:fnext': ['Next match', ['n', 'Enter']],
  'act:fhl': ['Found rows in front, the rest dimmed'], 'act:fopen': ['Fold the modules without a match'],
  'act:fmask': ['The found rows only (and the modules on the way to them)'],
  'act:fselect': ['Select the found signals: the right button then takes them all (a new group, colour, radix, hide …)', ['ctrl+click: add them']],
  '.subtg': ['Which groups of tools the bar shows: Show all, Hide all, a tick each'], '.subth': ['The theme of the page: auto, light, white, dark'],
  '.subcp': ['The short form of the bar: the groups\' labels hidden, their rarer controls behind ⋯'],
  '.fcol': ['Colour for Paint: at once on the found, highlighted and shift+click selected signals (none of them: the selected one)'],
  'act:fpaint': ['Paint the found, highlighted and shift+click selected signals (none of them: the selected one)'],
  'act:funpaint': ['Their own colours back'],
  'act:fcopy': ['Copy the paths of the found rows'],
  'act:sort': ['Sort: off → A→Z → Z→A', ['s']], '.pfx': ['Name prefixes ignored when sorting: i_,o_'],
  'act:expand': ['Open every module', ['zR']], 'act:collapse': ['Fold every module', ['zM']],
  'act:hl': ['Clear the highlight', ['Esc']], 'act:unhide': ['Show the hidden rows again'],
  'act:prev': ['Previous edge of the selected signal', ['shift+Tab', '[e']], '.edge': ['Edge kind: any, rising, falling, a value, X / Z', ['e']],
  'act:next': ['Next edge of the selected signal', ['Tab', ']e']],
  'act:mark': ['Bookmark at the cursor, on the selected signal: its label asked there, its text in the list', ['b']],
  'act:umark': ['A marker at the cursor: a dashed line across the rows; its label asked', ['m']],
  'act:mprev': ['The previous bookmark or marker in time', ['[b', '[m']], 'act:mnext': ['The next bookmark or marker in time', [']b', ']m']],
  'act:mlist': ['The markers and bookmarks in a list: ↑ ↓ go through them, the waves follow', ['gm']],
  'act:ssave': ['Save the view to a file (.view.json)', ['gs']], 'act:sload': ['Load a saved view', ['gL']],
  'act:sreload': ['The state loaded last, read again', ['r']],
  'act:sforget': ['Forget what is kept of this view (rows, paint, marks, look, edits, assertions bound) and the last state; ' +
    'asked first'], 'act:svload': ['Load SystemVerilog assertion files (.sv, .sva)'],
  'act:spage': ['This page as a file (.view.html) with your view in it — bookmarks, groups, colours, cursor, window, assertions: whoever opens ' +
    'it sees what you see, no other file needed'],
  'act:undo': ['Undo the last change of bookmarks, arrows, markers, your groups, colours, radix, analog, hidden rows, the highlight, the edge ' +
    'style, the gaps or the cycles (not the cursor or the window)', ['ctrl+Z']], 'act:redo': ['Redo what was undone', ['ctrl+shift+Z', 'ctrl+Y']],
  'act:help': ['Keys and mouse', ['?']],
  'act:theme': ['The theme: auto (the system\'s light or dark), light, white, dark; kept in this browser. In VS Code: its list, with VS ' +
    'Code\'s own colours too'],
  'act:scroll': ['Ticked: the rows scroll in a window of their own (the bar above them); else with the page (the bar sticks to the top); kept in ' +
    'this browser'],
  'act:strip': ['Ticked: the strip over the time axis, its groups (the find, the marks, the cursor, the edges) out of the bar\'s lines ' +
    '(stripGroups; Arrange the bar… moves a group in or out)'],
  'act:axlock': ['Unlock the strip: ⠿ moves a box (it snaps to the edges, the middle, the names\' edge; over the other, the two swap); ' +
    'again: lock them there'],
  'act:axgrip': ['Drag this box along the strip; over another, the two swap; ← → Home End move it too (shift: a quarter); kept', ['drag', '←', '→']],
  'act:snap': ['Ticked: a click puts the cursor on an edge of the signal near it (cursorSnap px); alt+click never does'],
  'act:tg': ['Show or leave out this group of tools'], 'act:tgall': ['Every group of tools in the bar'],
  'act:tgnone': ['No group of tools (/ still floats the find)'],
  'act:compact': ['The short form: the groups\' labels hidden, their rarer controls behind ⋯ (auto: when the bar is narrower than 900 px)'],
  'act:tools': ['Fold the tools to this line, or open them (/ floats the find over a folded bar)'], 'jump': ['Go to this marker'],
  'act:arrange': ['Move the groups of the bar: drag one by its label, within a line, to another, to a new one (the keys: a list); kept in this browser'],
  'act:barreset': ['The bar as the settings have it: the order of the groups, the short form, the groups shown'],
  '.pgear': ['The bar and the look: the theme, where the rows scroll, the edge style, the sort prefixes, snap, the tool groups shown, the short ' +
    'form (the right button on the bar opens it too)'],
  '.pfile': ['The files: open a dump, compare one, its sources, the runs kept; save, load, reload the view; save the page; load assertions'],
  '.ppaint': ['Paint: a colour on the found, highlighted and shift+click selected signals (none of them: the selected one); Unpaint'],
  '.pimg': ['More of the picture: all rows (the open modules, top to bottom), save it as PNG or SVG, as WaveDrom'], '.mx': ['The rest of this group'],
  '.chipn': ['The filters on the rows: the highlight, the hidden rows, Only, the FSM layer'],
  '.rx': ['Radix of the selected signal (shift+click a name: of a run of them); "the page\'s": its own again'],
  'act:cycles': ['The clock cycles in a band under the time axis (the right button: Cycles ▸ for the clock, cycle 0)'],
  'act:gaps': ['The waves with the gaps cut out (where nothing changes), or in continuous time; idle and keep beside it', ['gv']],
  'act:svgall': ['Every row of the list as an SVG file (no height limit): the range, else the window; the ones scrolled out of the window too'],
  'act:copyall': ['The range (else the window) of every row of the list as PNG to the clipboard: the ones scrolled out of the window too (the open modules)',
    ['yI']],
  'act:copyimg': ['The range (else the window) as PNG to the clipboard: the highlighted rows, else the ones on the screen', ['yi']],
  'act:png': ['Save the picture as PNG'], 'act:svg': ['Save the picture as SVG'],
  'act:wdjson': ['The range (else the window) as a WaveDrom file (.json), a cell per clock cycle'], 'act:wdcopy': ['The same WaveDrom to the clipboard'],
  'act:dprev': ['The previous difference from the dump compared', ['[d']], 'act:dnext': ['The next difference from the dump compared', [']d']],
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
  'm:svgall': ['Every row of the list as an SVG file (no height limit): the range, else the window; the ones scrolled out of the window too'],
  'm:copyall': ['The range (else the window) of every row of the list as PNG to the clipboard: the ones scrolled out of the window too (the open modules)',
    ['yI']],
  'm:copyimg': ['The range (else the window) as PNG to the clipboard: the highlighted rows, else the ones on the screen', ['yi']],
  'm:png': ['Save the picture as PNG'],
    'm:svg': ['Save the picture as SVG'],
  'm:c2': ['A second cursor: Δ to the cursor in time and clock cycles', ['shift+click']], 'm:c2x': ['No second cursor', ['Esc']],
  'm:analog': ['The bus as a step plot, three rows high (its radix: signed, float, fixed)'],
  'm:dup': ['The same signal again in a row under it, with a radix, an analog form and a colour of its own'],
  'm:undup': ['This copy out of the waves: a bookmark on it goes to its signal'],
  'm:bits': ['The bus bit by bit: a row per bit under it, the highest first (a click on its width [7:0] does it too)', ['B']],
  'm:wdjson': ['The range as a WaveDrom file (.json): the highlighted signals, else the ones on the screen, a cell per clock cycle'],
  'm:slkeep': ['The range of the waves shown (the dump, or the run shown) kept among the runs as a slice of its own: every signal, its times ' +
    'from 0, so slices (of this dump or of others) compare with each other from their first sample: w shows one, B compares it (VS Code)'],
  'm:slfst': ['The range of the waves shown as an FST file of its own, every signal, its times from 0 (a save dialog; sva fst --from --to --zero)'],
  'm:wlpiece': ['The range as waves WaveLens opens on its own (.wavelens.json): the highlighted signals, else the ones on the screen, ' +
    'exact, with your view of them (colours, radix, marks inside it)'],
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
  'm:hl': ['Highlight', ['ctrl+click']], 'm:hide': ['Leave it out of the view (Hidden: N ✕ in the bar shows it again)'], 'm:unhide': ['Show the hidden rows'],
  'm:fold': ['Fold / open this module'], 'm:foldup': ['Fold its module', ['zc']], 'm:zM': ['Fold every module', ['zM']], 'm:zR': ['Open every module', ['zR']],
  'm:types': ['Where its labels or fields come from: the types file and the path in it, the width, why it has none'],
  'm:mark': ['Bookmark on this signal here: its label asked here, its text in the list', ['b']],
  'm:svaed': ['The assertion of these rows in a box of its own: its text, Apply, its bindings'],
  'm:copyname': ['Copy the path', ['yy']], 'm:copylink': ['Copy a link to this moment: the page opened by it goes here', ['yl']],
  'm:clear': ['Clear the range', ['Esc', 'ctrl+click']],
  'm:unpaint': ['Its own colour back'],
  'm:umark': ['A marker here: a dashed line across the rows; its label asked here. Drag the text to a line over or under any signal; the right ' +
    'button on it: its colour', ['m']],
  'm:mlist': ['The markers and bookmarks in a list: ↑ ↓ go through them, the waves follow', ['gm']],
  'm:ugnew': ['A group of your own at the top of the names'],
  'm:ugout': ['Out of your group (the signal stays in its module)'], 'm:ugdel': ['Delete your group; its signals stay where they are'],
  'm:ugren': ['A new name for your group (or a double-click on its name, F2 there)'],
  'm:mvup': ['One place up in your group or its module (a selected run: as a block; a group: among yours; a module: with its rows)',
    ['alt+↑', 'drag the name']],
  'm:mvdn': ['One place down in your group or its module (a selected run: as a block; a group: among yours; a module: with its rows)',
    ['alt+↓', 'drag the name']],
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
TIPS['.subg'] = ['Your groups: the place of this row (or group) among them, into one, out of one, a new one, go to one', ['ctrl+G', 'gl']];
// the submenus of the right button's menu (menuSub) and the items whose tip was their own
Object.assign(TIPS, { '.subr': ['More of the range: bookmarks at its ends, its Δ copied, kept as a span of yours, as waves of their own'],
  '.subv': ['How the signal is drawn: a step plot, bit by bit, some bits as a row of their own; where its type comes from'],
  '.subt': ['The time clicked: a bookmark or a marker there, the second cursor, a link to it; the lists of the marks'],
  '.subp': ['The picture (the range, else the window; the highlighted rows, else the ones on the screen) as a file, WaveDrom, WaveLens'],
  '.subm': ['The rows as a whole: fold the modules, show the hidden, the Modules panel and Only, the state machines'],
  'm:asrange': ['This span measured as the range'], 'm:spdel': ['Delete this span of yours'],
  'm:keepsp': ['A span of yours over this range, its label asked (empty: none); the range stays'],
  'm:copyv': ['The value at each cursor and the change between them, as the value column shows them'],
  'm:dupbits': ['Some bits of the bus as a row of their own: 7:4'],
  'm:clearmarks': ['Every bookmark, arrow and marker of yours deleted (ctrl+Z brings them back)', ['gc']],
  'm:dlown': ['The Δ arrow in the default colour again'], 'm:dlnone': ['No Δ arrow from this marker (the marker stays)'],
  'm:lnown': ['The things on this line (Δ arrows, markers, bookmarks) in their own colours again'] });
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
      [['shift+drag', 'middle drag'], 'zoom into a range'], [['Home', 'End'], 'the start / end'], [['PgUp', 'PgDn'], 'a page of rows'],
    [['the bar under the waves'], 'zoomed in: all of the waves, the window its thumb: drag it, click its track (held: the window\'s ends)']]],
  ['Cursor and edges', [[['click'], 'cursor on a near edge (alt: not) + select the signal'], [['shift+←', 'shift+→'], 'move the cursor'],
    [['Tab', 'shift+Tab'], 'next / previous edge (no signal selected: the focus moves on)'], [[']e', '[e'], 'next / previous edge'], [['e'], 'edge kind']]],
  ['Signals', [[['↑', '↓', 'j', 'k'], 'select the next / previous'], [['shift+click a name'], 'select every signal from the last clicked one'],
    [['gg', 'G'], 'the first / last'], [['ctrl+G', 'gl'], 'your groups: a list, a click goes there, ✎ or F2 renames'],
    [['gv'], 'the waves with the gaps cut out, or in continuous time'],
    [['alt+↑', 'alt+↓'], 'the selected signal up / down in your group or its module (shift: the group, the module; a sort drops your order of the module: '
      + 'that sort again brings it back); or drag it in your group'],
    [['ctrl+click', '○'], 'highlight'], [['ctrl+shift+click'], 'highlight every row from the last one to it'],
    [['zM', 'zR'], 'fold / open every module'], [['t'], 'the modules as a tree: a click goes to one, a box keeps Only those (again: the selected one\'s)'],
    [['T'], 'the state machines in the tree of their modules: go to one, Only them, add them to the view'],
    [['zc', 'zo', 'za'], 'the selected signal\'s module'], [['B', 'click [7:0]'], 'the selected bus bit by bit (again: folded)'],
    [['s'], 'sort'], [['yy', 'ctrl+C'], 'copy the path'], [['yi', 'yI'], 'copy an image of the range (else the window): its rows / all rows'],
    [['zz'], 'zoom to the range (else the two cursors)'],
      [['Esc'], 'reset: search, highlight, selection']]],
  ['Find', [[['/', 'ctrl+F'], 'find (the bar scrolled away: it floats over the waves)'],
    [['alt+C', 'alt+W', 'alt+R'], 'in the field: match case, full match, regular expression'], [['n', 'N', 'Enter'], 'next / previous match'],
    [['*', '#'], 'find the selected name: its next / previous match'],
    [['/ in the assertions panel'], 'find assertions: name* @signal in:scope is:fail (Mask: only them on the waves; Esc empties it)']]],
  ['Measure and mark', [[['shift+click'], 'a second cursor: Δ to the cursor, in cycles of the clock'], [['x'], 'swap the cursors'],
    [['c147'], 'in the cursor field: cycle 147 of the clock (right button: Cycles ▸, a band of them under the axis)'],
    [[']d', '[d'], 'next / previous difference from a dump compared (File ▾ → Compare with…, then Compare)'],
    [['d'], 'a dump compared: flip the waves between the two runs (the time axis names the one shown)'],
    [['D'], 'a dump compared: both runs over each other where they differ, again one'],
    [['gb'], 'a dump compared: the red mask over the differences on or off (off: d blinks between the runs)'],
    [['g='], 'compare A and B (Compare… a file, the Runs panel\'s) over the window in sight; zoomed since: again'],
    [['gu'], 'the runs kept of this dump (VS Code): keep this one, show one (A), compare one with it (B) over the waves in sight or a span'],
    [[']r', '[r'], 'B: pick the next (older) / previous run kept (g= compares it with A over the window in sight)'],
    [[']w', '[w'], 'A: the waves of the next (older) / previous run kept shown here, the view kept (now among them)'],
    [['1', '…', '9'], 'go to bookmark 1 … 9'],
    [['ctrl+drag'], 'measure a range: Δ, the edges or changes of that signal, then of each one you select (↑ ↓, a click on a name)'],
    [['alt+drag'], 'a box: its time and its signals, then the menu (picture, WaveDrom, colour)'], [['ctrl+click'], 'clear the range'],
    [['right button'], 'a range and the menu: colour, radix, hide, Copy image; Show as ▸, Here ▸, Export ▸ …'],
    [['b'], 'bookmark at the cursor: its label asked'],
    [[']b', '[b'], 'next / previous bookmark'], [['m'], 'marker at the cursor: its label asked'], [[']m', '[m'], 'next / previous marker'],
    [['right button + click'], 'the left button while the right one is down: a marker there at once (M1, M2 …; over the signal, else under it)'],
    [['gm'], 'the markers and bookmarks: a list, ↑ ↓ go through them'], [['drag a bookmark'], 'move it'],
    [['drag a marker\'s text'], 'to a line over or under a signal, along the time (alt: the time stays)'],
    [['drag a Δ'], 'between markers (Δ between markers in their list): up and down, to a line over or under a signal; its dot along, to another marker'],
    [['shift+drag a bookmark'], 'an arrow to another one']]],
  ['The bar', [[['⚙', 'right button'], 'on the bar: the theme, scroll, edge style, sort prefixes, snap, the tool groups shown, the short form'],
    [['File ▾'], 'open, compare, sources, runs; save, load, reload the view; save the page'],
    [['⋯'], 'a narrow bar (the short form): the rest of a group'],
    [['⚙ Arrange the bar…'], 'drag a group by its label (Esc: back); the keys: alt+↑ ↓ ← → move a group, Space shows / hides it'],
    [['▴', '▾ tools'], 'fold the tools to the title line / open them'], [['r'], 'the last state loaded, read again (Reload)'],
    [['R'], 'the dump read again from the disk, the view kept (⟳)']]],
  ['Menus', [[['g'], 'a moment after it: a box with what can follow, press the key or click it: go to, markers and bookmarks, the state, the dump'],
    [['z', 'y', '[', ']'], 'the same box: fold, copy, next, previous'], [['Esc'], 'with the box open: closes it, nothing else'],
    [['t', 'T'], 'the panels of the modules, the state machines'], [['gm', 'gl'], 'the lists of the markers and bookmarks, your groups'],
    [['right button', 'Menu key'], 'on the waves or a name: the menu of what is there (↑ ↓ → ← Enter Esc in it, a submenu ▸ by →)']]],
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
    ['=', 'compare A and B over the window in sight', v => v.cmp || v.cmpPend()],
    ['b', v => (v.cmpMask !== false ? 'no red mask on the differences' : 'the differences masked in red'), v => v.cmp],
    ['u', 'the runs kept…', onBar('druns')],
    ['More'], ['v', v => (v.gapLive() ? 'the waves in continuous time' : 'the gaps cut out of the waves')], ['p', 'save the page', onBar('spage')]]],
  z: ['Fold the modules', [['R', 'open every module'], ['M', 'fold every module'], ['o', 'open the selected signal\'s'], ['c', 'fold the selected signal\'s'],
    ['a', 'open or fold it'], ['z', 'zoom to the range', v => !!v.range || v.cursor2 != null]]],
  y: ['Copy', [['y', 'the selected signal\'s path'], ['n', 'its name'], ['t', 'the time of the cursor'], ['l', 'a link to here (the cursor, the signal)'],
    ['i', 'an image of the range (else the window)'], ['I', 'an image of all rows']]],
  ']': ['Next', [['b', 'bookmark'], ['m', 'marker'], ['e', 'edge'], ['d', 'difference', v => v.cmp],
    ['r', 'run kept (picked as B; g= compares)', v => v.runsHost()],
    ['w', 'run kept (A, the waves shown)', v => v.runsHost()]]],
  '[': ['Previous', [['b', 'bookmark'], ['m', 'marker'], ['e', 'edge'], ['d', 'difference', v => v.cmp],
    ['r', 'run kept (picked as B; g= compares)', v => v.runsHost()],

    ['w', 'run kept (A, the waves shown)', v => v.runsHost()]]],
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

// the bar's tools, one line per kind of work: where you are in time (cursor, zoom, edges, marks, jumps), the signals by
// name and the times by a condition (find; sva.js: expression, assertions), the rows, the signals' look, the files and a
// compare (list, signal, file, compare)
const TOOL_LINES = { cursor: 'time', view: 'time', edges: 'time', marks: 'time', 'go to': 'time', find: 'find', expression: 'find', assertions: 'find',
  list: 'rows', prefixes: 'rows', signal: 'rows', file: 'rows', compare: 'rows' };
// the strip over the time axis, a band of its own under the bar's lines: a box per group of it (stripGroups), each at its place
// (toolAt; else these: the find and the marks at the left, the cursor and the edges at the right)
const STRIP_AT0 = { find: 0, marks: 0, cursor: 1, edges: 1 };
const TOOL_GRID = 16;    // px: the grid a group dropped in a line or in the strip snaps to (Arrange the bar…)
const STRIP_SNAP = 14;   // px: a dragged box snaps to the left, the middle, the right of the strip and the names' edge this near
const STRIP_GAP = 12;    // px between two boxes of the strip
const LOCK_SVG = (open) => '<svg viewBox="0 0 12 14" width="10" height="12" aria-hidden="true"><rect x="1.5" y="6" width="9" height="7" rx="1.2" ' +
  `fill="currentColor"/><path d="${open ? 'M3.5 6V3.5a2.5 2.5 0 0 1 5 0' : 'M3.5 6V4a2.5 2.5 0 0 1 5 0V6'}" fill="none" stroke="currentColor" ` +
  'stroke-width="1.4"/></svg>';
const toolLine = (ln, html) => `<div class="tln" data-ln="${ln}">${html}</div>`;
const BAR_SHORT = 900;   // px: a bar narrower than this takes its short form (toolsCompact 'auto'): no labels, the rest of a group behind ⋯

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

// a menu of the bar: its header (a button, ▾; its data-own, the controls in its box, set by layoutShow) and its box (.bpop in the
// bar, hidden until the header opens it, a .wv-menu while it is open: look.js popOpen); the box's items are the bar's own buttons (data-act),
// one each, so the bar's click and the g menu's keys reach them as they reach the others
const popHead = (id, label, cls, aria = '') => `<button type="button" class="pop ${cls}" data-pop="${id}" aria-haspopup="menu" aria-expanded="false"` +
  `${aria ? ` aria-label="${aria}"` : ''}>${label}</button>`;
const popBox = (id, html, cls = '') => `<div class="bpop${cls ? ' ' + cls : ''}" data-pop="${id}" role="menu" hidden>${html}</div>`;
const mItem = (act, label, kk = '', more = '') => `<button type="button" role="menuitem" data-act="${act}"${more}><span>${label}</span>` +
  `${kk ? `<span class="kk">${kk}</span>` : ''}</button>`;
const mTick = (act, label, more = '') => `<button type="button" role="menuitemcheckbox" aria-checked="false" data-act="${act}"${more}><span><span ` +
  `class="ck"></span>${label}</span></button>`;
const btn = (act, label, more = '') => `<button type="button" data-act="${act}"${more}>${label}</button>`;
// the bar's state the buttons show (disabled, pressed): worked out when a viewer draws, the DOM touched when it changed
const barState = v => {
  const run = v.selRun.size > 1 ? [...v.selRun] : v.sel ? [v.sel] : [], bus = run.map(r => r.orig || r).filter(r => r.type === 'sig' && r.width > 1);
  const rx = !bus.length ? '' : bus.every(r => !v.radixes.has(r.full)) ? '-' : bus.every(r => v.radixes.get(r.full) === v.radixes.get(bus[0].full)) ?
    v.radixes.get(bus[0].full) : '';
  const co = v.cycOpt(), m = v.clkMemo;   // a clock to count: looked for once per model and clock setting (not on every draw)
  if (!m || m[0] !== v.M.rows || m[1] !== co.cycleClock) v.clkMemo = [v.M.rows, co.cycleClock, !cycClock(v.M.rows, co.cycleClock)];
  return { zlast: !v.lastView, zrange: !v.range && v.cursor2 == null, marks: !anyMark(v), rx, rxOff: !bus.length, cyc: co.cycles,
    cycOff: v.clkMemo[2], gaps: v.gapLive() };
};

class Bar {
  // the viewer's markup: the bar (title line, tool groups), the names column and the waves, the lists, the hint
  static html(v) {
    const S = v.S, groups = Object.keys(v.M.groups).length > 0;
    const paint = getComputedStyle(v.root).getPropertyValue('--wave-paint').trim();   // a token, so a theme may change it
    const jumps = v.jumps.map((j, i) => `<button type="button" data-jump="${i}">${esc(j.label)}</button>`).join('');
    const seg = (...parts) => `<span class="seg">${parts.join('')}</span>`, more = (...parts) => `<span class="more">${parts.join('')}</span>`;
    // a group: its label, its controls; the rarer ones in .more (the short form: behind its ⋯)
    const grp = (label, ...parts) => { const h = parts.join(''); return `<span class="tg" data-tg="${label}"><span class="tl">${label}</span>${h}${
      h.includes('class="more"') ? '<button type="button" class="mx" data-act="more" aria-haspopup="true" aria-expanded="false" aria-label="more of ' +
        `${label}">⋯</button>` : ''}</span>`; };
    // cursor: a time typed (in the unit chosen, or with its own: 85.12us; c147 a cycle), Enter; the span of the window around it, Enter
    const units = v.M.timed ? `<select class="cu" aria-label="time unit">${['ps', 'ns', 'µs', 'ms', 's'].map(u => `<option${u === v.unit() ? ' selected' :
      ''}>${u}</option>`).join('')}</select>` : '<span class="cyc">cyc</span>';
    const cursor = grp('cursor', seg('<input type="text" class="ct" inputmode="decimal" spellcheck="false" aria-label="cursor time">', units),
      more(seg('<span class="lbl">span</span><input type="text" class="cs" spellcheck="false" aria-label="view span">')));
    const view = grp('view', seg(btn('out', '−', ' aria-label="zoom out"'), btn('in', '+', ' aria-label="zoom in"'), btn('fit', 'Fit')),
      more(seg(btn('zlast', 'Last', ' disabled'), btn('zcur', '⊙', ' aria-label="zoom in on the cursor"'),
        btn('zrange', '⇔', ' aria-label="zoom to the range" disabled')),
      seg(btn('t0', '|◀', ' aria-label="the start"'), btn('t1', '▶|', ' aria-label="the end"'))));
    const edges = grp('edges', seg(btn('prev', '◀', ' aria-label="previous edge"'),
      `<select class="edge" aria-label="edge kind">${Object.entries(EDGE_KINDS).map(([k, n]) => `<option value="${k}">${n}</option>`).join('')}</select>`,
      '<input type="text" class="ev" spellcheck="false" hidden placeholder="0x40, \'h40, 64, IDLE" aria-label="value to find" title="The value to find: ' +
        '0x40, \'h40, 8\'d64, 64, -3, \'b101, or a text (an enum label); Enter / shift+Enter: the next / previous time the selected signal (none: any ' +
        'shown) becomes it">', btn('next', '▶', ' aria-label="next edge"')));
    const marks = grp('marks', btn('mark', '+ Bookmark'), btn('umark', '+ Marker'),
      seg(btn('mprev', '◀', ' aria-label="previous mark" disabled'), btn('mnext', '▶', ' aria-label="next mark" disabled')),
      more(btn('mlist', 'Marks…', ' disabled')));
    // find: the field with its count at its right end, ‹ › through the matches; its options, the view of the found, Select, Copy, Paint ▾
    const fcol = `<input type="color" class="fcol" value="${/^#[0-9a-f]{6}$/i.test(paint) ? paint : '#d6336c'}" aria-label="paint colour">`;
    const find = grp('find', `<span class="qw"><input type="search" class="q" spellcheck="false" autocomplete="off" placeholder="find  /" ` +
      'aria-label="fuzzy find signals"><span class="cnt"></span></span>', seg(btn('fprev', '‹', ' aria-label="previous match"'),
        btn('fnext', '›', ' aria-label="next match"')),
      more(seg(...FIND_OPTS.map(([act, k, label]) => `<button type="button" class="fo" data-act="${act}" aria-pressed="${!!S[k]}">${esc(label)}</button>`)),
        seg(`<button type="button" data-act="fhl" aria-pressed="${!!S.findHighlight}">Highlight</button>`,
          `<button type="button" data-act="fopen" aria-pressed="${!!S.findOpen}">Open</button>`,
          `<button type="button" data-act="fmask" aria-pressed="${!!S.findMask}">Mask</button>`),
        btn('fselect', 'Select'), btn('fcopy', 'Copy'), popHead('paint', 'Paint ▾', 'ppaint'),
        popBox('paint', `<label class="mi">Colour ${fcol}</label>` + mItem('fpaint', 'Paint') + mItem('funpaint', 'Unpaint', '', ' hidden'))),
      '<button type="button" class="fx" data-act="fdock" aria-label="close">✕</button>').replace('class="tg"', 'class="tg find"');
    const list = grp('list', S.sortButton ? btn('sort', '') : '', groups ? more(seg(btn('expand', '⊞', ' aria-label="open every module"'),
      btn('collapse', '⊟', ' aria-label="fold every module"'))) + btn('mods', 'Modules') + (v.fsms().length ? btn('fsms', 'FSMs') : '') : '');
    // the sort prefixes, a group of their own (in ⚙ too): the names sorted without them, live as they are typed
    const pfxIn = () => `<input type="text" class="pfx" spellcheck="false" value="${esc(v.sortIgnore.join(','))}" placeholder="i_,o_" ` +
      'aria-label="prefixes ignored when sorting">';
    const pfxGrp = S.sortButton ? grp('prefixes', pfxIn()) : '';
    const signal = grp('signal', `<select class="rx" aria-label="radix of the selected signals" disabled><option value="">radix</option><option ` +
      `value="-">the page's</option>${RADIX.map(x => `<option>${x}</option>`).join('')}</select>`,
      more(btn('cycles', 'Cycles', ' aria-pressed="false"'), btn('gaps', 'Gaps', ' aria-pressed="false"'),
        '<span class="gapv" hidden>idle <input type="text" class="bgi" spellcheck="false" aria-label="gaps: idle this long"> keep <input type="text" ' +
          'class="bgk" spellcheck="false" aria-label="gaps: kept around a change"><button type="button" data-act="gapvx" aria-label="the gaps off the ' +
          'waves">✕</button></span>'));
    // the files: a dump read in the page (Open…, or a file dropped on the viewer; ⟳ reads it again from the disk keeping the view), a
    // second one compared, the sources; the view saved, loaded, read again; the page saved; assertions loaded (sva.js)
    const file = grp('file', popHead('file', 'File ▾', 'pfile'), popBox('file',
      mItem('dopen', 'Open dump…', 'g O') + mItem('dcmp', 'Compare with…', 'g C') + mItem('dsrc', 'Sources…') +
        mItem('druns', 'Runs…', 'g u', v.runsHost() ? '' : ' hidden') + '<hr>' + mItem('ssave', 'Save view…', 'g s') + mItem('sload', 'Load view…', 'g L') +
        mItem('sreload', 'Reload view', 'r', ' hidden') + mItem('sforget', 'Forget the kept view…') + mItem('spage', 'Save page', 'g p', ' class="spage"') +
        mItem('svload', 'Load assertions…', '', ' hidden')),
      btn('dreload', '⟳', ' aria-label="read the dump again" hidden'),
      more(seg(btn('copyimg', 'Copy image'), popHead('img', '▾', 'pimg', 'more of the picture')),
        popBox('img', mItem('copyall', 'Copy image of all rows') + mItem('svgall', 'Save image of all rows as SVG') + '<hr>' +
          mItem('png', 'Save image as PNG') + mItem('svg', 'Save image as SVG') + '<hr>' + mItem('wdjson', 'Save as WaveDrom') +
          mItem('wdcopy', 'Copy WaveDrom'))),
      '<button type="button" class="live" data-act="live" hidden></button><input type="file" class="sfile" accept=".json,application/json" hidden>' +
        '<input type="file" class="dfile" accept=".vcd,.fst,.json" hidden><input type="file" class="cfile" accept=".vcd" hidden>' +
        '<input type="file" class="srcfile" accept=".sv,.svh,.v,.vh,.json" multiple hidden>');
    // a second dump compared (diff.js cmpShow: the group only while there is one, or one is being read)
    const compare = grp('compare', `<span class="seg cmpv" hidden>${btn('dcmpv', 'A', ' data-run="a" aria-pressed="true"')}${
      btn('dcmpv', 'B', ' data-run="b" aria-pressed="false"')}${btn('dcmpv', 'A+B', ' data-run="overlay" aria-pressed="false"')}</span>` +
      btn('dcmpgo', 'Compare', ' class="cgo" hidden') + btn('dcmpm', '▒', ' aria-pressed="true" aria-label="the red mask of the differences"'),
      seg(btn('dprev', '◀', ' aria-label="previous difference"'), btn('dnext', '▶', ' aria-label="next difference"')),
      btn('dcmpx', '', ' class="cmpx" hidden')).replace('class="tg"', 'class="tg" hidden');
    // ⚙: the bar and the look (the right button on the bar opens it too); Tools in the bar: its groups, ticked when the box opens
    const gear = popBox('gear', '<div class="mh">The bar and the look</div>' +
      (themeButtonOn(S) ? menuSub('subth', 'Theme', THEME_CYCLE.map(t => mTick('theme', t, ` data-v="${t}"`)).join('')) : '') +
      mTick('scroll', 'Scroll in the window') +
      `<label class="mi">Edge style <select class="ws" aria-label="edge style">${Object.entries(STYLE_NAMES).map(([k, n]) =>
        `<option value="${k}"${k === S.style ? ' selected' : ''}>${n}</option>`).join('')}</select></label>` +
      (S.sortButton ? `<label class="mi">Sort prefixes ${pfxIn()}</label>` : '') +
      mTick('snap', 'Snap to edges') + mTick('strip', 'Strip over the axis') + '<hr>' +
      menuSub('subtg', 'Tools in the bar', mItem('tgall', 'Show all') + mItem('tgnone', 'Hide all')) +
      menuSub('subcp', 'Short form', [['auto', 'auto: under 900 px'], ['on', 'always'], ['off', 'never']].map(([k, n]) =>
        mTick('compact', n, ` data-v="${k}"`)).join('')) + '<hr>' + mItem('arrange', 'Arrange the bar…') + mItem('barreset', 'Reset the bar'),
      'wv-tools wv-gear');
    const hint = 'Wheel: scroll · ctrl+wheel: zoom · shift+wheel / drag: pan · shift or middle drag: zoom to a range · ctrl+drag: measure · ' +
      'alt+drag: a box of time and signals · click: cursor (on a near edge; alt: not) + select a signal · keys on the waves (as in Questa): ' +
      'i o zoom in / out, f full, l last, c in on the cursor · ← → pan, Home End · shift+← → cursor · ↑ ↓ (j k) select, gg G first / last · ' +
      'Tab shift+Tab next / previous edge, e edge kind · / ctrl+F find, n N next / previous match, * # the selected name · ' +
      `b bookmark, ]b [b next / previous, m marker, ]m [m · zM zR fold / open all, zc zo the selected module${groups ? ' · t modules' : ''} · ` +
      `yy ctrl+C copy${S.sortButton ? ' · s sort' : ''} · ` +
      `Esc reset${groups ? ' · click a module to fold it' : ''} · shift+click a name: select every signal to it · ` +
      '○ or ctrl+click a name: highlight, ctrl+shift+click: every row to it';
    const [ver, verTip] = buildText();
    // the head: the title, the filters on the rows (chips: each ✕ clears its own; folded into one when the readout would be cut short),
    // the toast and the readout, the version, undo / redo, ⚙, the fold, ?
    const chips = '<span class="chips">' + btn('hl', '', ' hidden') + btn('unhide', '', ' hidden') + btn('onlyp', '', ' hidden') +
      btn('onlyx', '✕', ' aria-label="clear Only" hidden') + btn('fsmx', '', ' hidden') + '</span>';
    // (the folded chips' button in the readout's box: on a narrow head it floats on the readout's first line, no row of its own)
    const chipn = '<button type="button" class="chipn" aria-haspopup="true" aria-expanded="false" hidden></button>';
    return `<div class="bar"><div class="head"><span
      class="eyebrow">${esc(v.opts.title || v.M.title || 'Waveform').replace(/µ/g, '<span class="mu">µ</span>')}</span>${chips}<span class="rd">${chipn}<span
        class="toast" role="status" aria-live="polite"></span><span class="cur"></span></span>${
        S.version ? `<span class="ver" title="${esc(verTip)}">${esc(ver)}</span>` : ''}<span class="hbs"><span class="seg ur">${
        btn('undo', '↶', ' class="undo" disabled ' +
        'aria-label="undo"')}${btn('redo', '↷', ' class="undo" disabled aria-label="redo"')}</span>${popHead('gear', '⚙ ▾', 'pgear', 'the bar and the look')}${
        btn('tools', '', ' class="lay" aria-label="fold the tools"')}${btn('help', '?', ' class="hb" aria-label="keys and mouse"')}</span></div>
      <div class="tools">${toolLine('time', cursor + view + edges + marks + (jumps ? grp('go to', jumps) : ''))}${toolLine('find', find)}${
        toolLine('rows', list + pfxGrp + signal + file + compare)}</div>${gear}<div class="axs" role="toolbar" aria-label="the strip over the time axis"
        hidden><div class="axw">${btn('axlock', LOCK_SVG(false) + LOCK_SVG(true), ' class="axl" aria-pressed="false" aria-label="unlock the strip: ⠿ ' +
        'moves a box"')}<div class="axr"></div><span class="axe" aria-hidden="true">the strip over the time axis — drop a group here</span></div>` +
        `</div></div>
      <div class="body"><div class="names"></div><div class="wcol"><canvas tabindex="0" role="application" aria-roledescription="waveform"
        aria-label="waveform: + − zoom, ← → pan, shift+← → move the cursor, ↑ ↓ select a signal, [e ]e or Tab edges"></canvas>` +
        `<div class="hsb" hidden title="All of the waves: drag the window, click to bring it there (held: its ends)">` +
        '<div class="hsbt"></div><div class="hsbk"></div>' +
        `<span class="hsbtip" hidden></span></div></div></div>
      <div class="notes" hidden></div>
      <div class="wlog" hidden></div>
      ${S.hint ? `<div class="hint">${esc(v.hintBase = hint)}</div>` : ''}`;
  }
  constructor(v) {
    this.v = v; const r = v.root, bar = r.querySelector('.bar');
    v.canvas = r.querySelector('canvas'); v.hsbEl = r.querySelector('.hsb');
    v.wcol = r.querySelector('.wcol'); v.bodyEl = r.querySelector('.body'); v.namesEl = r.querySelector('.names');
      v.curEl = r.querySelector('.cur');
    v.sortBtn = r.querySelector('button[data-act=sort]'); v.hlBtn = r.querySelector('button[data-act=hl]');
      v.unhideBtn = r.querySelector('button[data-act=unhide]');
    v.notesEl = r.querySelector('.notes'); v.edgeSel = r.querySelector('select.edge');
    v.ctEl = r.querySelector('input.ct'); v.csEl = r.querySelector('input.cs'); v.cuEl = r.querySelector('select.cu');
    // Enter: the cursor there, the window of that span; Esc: the field as it was, the keys on the waves again (T-07)
    for (const [inp, fn] of [[v.ctEl, x => v.setCursor(x)], [v.csEl, x => v.showCursor(x)]]) {
      inp.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); fn(inp.value); }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); v.syncCursorFields(true); inp.classList.remove('bad'); v.refocus(); }
      });
    }
    if (v.cuEl) v.cuEl.addEventListener('change', () => { v.syncCursorFields(true); });
    v.qEl = r.querySelector('input.q'); v.cntEl = r.querySelector('.find .cnt'); v.fcol = r.querySelector('input.fcol');
    v.unpaintBtn = r.querySelector('button[data-act=funpaint]'); v.unpaintBtn.hidden = !v.painted.size;
    // the colour picked (or typed in its hex field) goes on at once to what Paint would take, as the right button's colour
    // does; nothing found, highlighted or selected: only kept for Paint
    v.fcol.addEventListener('input', () => { if (v.paintRows().length) v.paint(v.fcol.value); });
    let qt = 0;
    v.qEl.addEventListener('input', () => { cancelAnimationFrame(qt); qt = requestAnimationFrame(() => v.find(v.qEl.value)); });   // live, while typing
    v.qEl.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); v.findStep(e.shiftKey ? -1 : 1); }
      const opt = e.altKey && !keyLeft(v.S, e) && FIND_OPTS.find(o => o[4] === e.code);   // alt+C W R, as in VS Code (by the key's place: any layout)
      if (opt) { e.preventDefault(); v.setFindOpt(opt[1], !v[opt[1]]); }
    });
    // / on a folded bar opened the tools for the find (not kept, T-06): the find left empty folds them again
    r.querySelector('.tg.find').addEventListener('focusout', e => { if (v.toolsPeek && !v.qEl.value && !e.currentTarget.contains(e.relatedTarget)) {
      v.toolsPeek = false; v.layoutShow(); } });
    v.evEl = r.querySelector('input.ev');
    const axs = r.querySelector('.axs');   // the strip over the time axis, unlocked: a box's ⠿ dragged, or ← → Home End on it
    axs.addEventListener('pointerdown', e => { const g = e.target.closest('.axg'); if (g) v.stripDown(e, g); });
    axs.addEventListener('keydown', e => { const g = e.target.closest('.axg'); if (g) v.stripKey(e, g); });
    v.edgeSel.addEventListener('change', () => v.setEdgeKind(v.edgeSel.value, true));
    const gv = r.querySelector('.gapv'), bgi = gv.querySelector('.bgi'), bgk = gv.querySelector('.bgk');   // idle, keep: the waves follow as they are typed
    gv.addEventListener('input', () => v.gapType(() => v.gapFields(bgi, bgk, true)));
    gv.addEventListener('change', e => { if (e.target.matches('input')) { clearTimeout(v.gapTypeT); v.setGaps(v.gapFields(bgi, bgk)); } });
    v.syncGapBar();
    v.evEl.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); v.edge(e.shiftKey ? -1 : 1); } });
    v.wsEl = r.querySelector('select.ws'); v.wsEl.addEventListener('change', () => v.setStyle(v.wsEl.value));
    const rx = r.querySelector('select.rx');   // the radix of the selected signals (a run of them: every one)
    rx.addEventListener('change', () => { const rows = v.selRun.size > 1 ? [...v.selRun] : v.sel ? [v.sel] : [], to = rx.value === '-' ? null : rx.value;
      if (rx.value) { rows.forEach(x => v.setRadix(x, to, true)); v.saveRows(); v.renderNames(); v.draw(); } v.barSync(true); });
    bar.addEventListener('contextmenu', e => {   // the right button on the bar: the ⚙ menu there (a field: the browser's)
      if (!v.S.contextMenu || e.target.closest('input, select, textarea')) return; e.preventDefault();
      if (!e.target.closest('.bpop')) v.toolsMenu(e.clientX, e.clientY); });
    bar.addEventListener('click', e => {
      const b = e.target.closest('button'); if (!b || b.disabled) return;
      if (b.dataset.pop) { v.popToggle(b); return; }
      if (b.classList.contains('chipn')) { v.popToggle(b, r.querySelector('.bar .chips')); return; }
      const box = b.closest('.bpop'), keep = b.dataset.act === 'tg' || b.dataset.act === 'tgall' || b.dataset.act === 'tgnone';
      if (b.dataset.act) this.act(b.dataset.act, b, e);
      else if (b.dataset.jump !== undefined) { const j = v.jumps[b.dataset.jump]; v.goto(j.t, j.span); }
      if (box && !keep && !b.closest('.msub > button') && v.root.contains(b)) v.popClose(box);
    });
    v.dfile = r.querySelector('input.dfile');
    v.dfile.addEventListener('change', () => { const f = v.dfile.files[0]; v.dfile.value = ''; if (f) v.openDump(f); });
    v.cfile = r.querySelector('input.cfile');
    v.cfile.addEventListener('change', () => { const f = v.cfile.files[0]; v.cfile.value = '';   // B picked: Compare compares
      if (f) v.comparePick({ file: f, name: f.name }); });
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
    // the sort prefixes (their group, ⚙): live as they are typed, the other field the same; Esc: as they were when the field was
    // entered (T-07)
    const pfxs = [...r.querySelectorAll('input.pfx')], same = (from, t) => { for (const x of pfxs) if (x !== from) x.value = t; };
    for (const pfx of pfxs) { let was = pfx.value;
      pfx.addEventListener('focus', () => { was = pfx.value; });
      pfx.addEventListener('input', () => { same(pfx, pfx.value); v.fitPfx(); v.setSort(v.sort, pfx.value); });
      pfx.addEventListener('keydown', e => {
        if (e.key === 'Escape' && pfx.value !== was) { pfx.value = was; same(pfx, was); v.fitPfx(); v.setSort(v.sort, was); }
        // ↑ ↓ in ⚙: on to the item before / after (the field has no use for them; the menu's keys leave a field its own)
        const box = pfx.closest('.bpop'); if (!box || (e.key !== 'ArrowDown' && e.key !== 'ArrowUp')) return;
        const its = [...box.querySelectorAll(':scope > button, :scope > .msub > button, :scope > label.mi input, :scope > label.mi select')]
          .filter(x => !x.hidden && x.getClientRects().length), i = its.indexOf(pfx);
        const to = its[(i + (e.key === 'ArrowDown' ? 1 : -1) + its.length) % its.length];
        if (to) { e.preventDefault(); e.stopPropagation(); to.focus({ preventScroll: true }); } }); }
    v.fitPfx();
  }
  // what a control of the bar does, by its data-act (a button in the bar or in one of its menus; a g key through it): el the
  // control, e the click
  act(a, b, e = {}) {
    const v = this.v;
    if (a === 'in' || a === 'out') { v.markView(); v.zoom(a === 'in' ? 0.5 : 2, 0.5); }
    else if (a === 'fit') { v.markView(); v.fit(); }
    else if (a === 'zlast') v.zoomLast();
    else if (a === 'zcur') { v.markView(); v.showCursor(Math.max(v.span / 2, v.minSpan)); }
    else if (a === 'zrange') { const z = v.range || (v.cursor2 != null ? [Math.min(v.cursor, v.cursor2), Math.max(v.cursor, v.cursor2)] : null);
      if (z) v.zoomTo(...z); }
    else if (a === 't0' || a === 't1') { v.markView(); v.center(a === 't0' ? v.M.t0 : v.M.t1, a === 't0' ? 0 : 1); v.draw(); }
    else if (a === 'sort') v.setSort(SORTS[(SORTS.indexOf(v.sort) + 1) % SORTS.length]);
    else if (a === 'hl') v.highlight(null);
    else if (a === 'unhide') v.unhide();
    else if (a === 'mods') v.modules();
    else if (a === 'fsms') v.fsmPanel();
    else if (a === 'theme') v.themeNext(b && b.dataset.v);
    else if (a === 'fsmx') { v.setFsm(null); v.toast('the view without the FSM layer'); }
    else if (a === 'onlyp') v.setOnly({ on: !v.only.on });
    else if (a === 'onlyx') { v.setOnly(null); v.toast('Only: every module again'); }
    else if (a === 'expand') v.expandAll();
    else if (a === 'collapse') v.collapseAll();
    else if (a === 'prev' || a === 'next') v.edge(a === 'next' ? 1 : -1);
    else if (a === 'mark') v.bookmarkKey();
    else if (a === 'umark') v.markerKey();
    else if (a === 'mprev' || a === 'mnext') v.stepMarks(a === 'mnext' ? 1 : -1);
    else if (a === 'mlist') v.marksMenu();
    else if (FIND_VIEW[a]) { const k = FIND_VIEW[a][0]; v[k] = !v[k]; b.setAttribute('aria-pressed', v[k]); v.find(v.q || '', k === 'findOpen'); }
    else if (FIND_OPTS.some(o => o[0] === a)) { const k = FIND_OPTS.find(o => o[0] === a)[1]; v.setFindOpt(k, !v[k]); }
    else if (a === 'fpaint') v.paint(v.fcol.value);
    else if (a === 'funpaint') v.unpaint();
    else if (a === 'fnext' || a === 'fprev') v.findStep(a === 'fnext' ? 1 : -1);
    else if (a === 'fdock') { v.floatFind(false); v.refocus(); }
    else if (a === 'fselect') v.selectFound(e.ctrlKey || e.metaKey);
    else if (a === 'fcopy') v.copyRows(v.allRows().filter(r => v.found.has(r)));
    else if (a === 'ssave') v.saveState();
    else if (a === 'spage') { try { const n = savePage(); v.toast('saved ' + n); v.log('ok', 'saved the page: ' + n); }
      catch (err) { v.toast(err.message); v.logError(err, 'cannot save the page: ' + err.message); } }
    else if (a === 'undo' || a === 'redo') { v.undo(a === 'undo' ? -1 : 1); v.refocus(); }   // the button may go disabled: the keys stay on the waves (T-08)
    else if (a === 'help') v.help();
    else if (a === 'scroll') v.setScroll(v.S.maxHeight != null && v.S.maxHeight !== '' ? 'page' : 'window');
    else if (a === 'snap') v.setSnap(!(v.S.cursorSnap > 0));
    else if (a === 'strip') { const base = stripNames(settings(GLOBAL, v.M.cfg, v.opts).stripGroups);   // off: none; on: the settings' (none: these)
      v.setStripGroups(v.stripGroups().length ? [] : base.length ? null : Object.keys(STRIP_AT0)); }
    else if (a === 'axlock') v.stripLock(!!v.stripOpen);
    else if (a === 'tools') v.setTools(!v.S.toolsFolded);
    else if (a === 'tg' || a === 'tgall' || a === 'tgnone') { const H = new Set(toolNames(v.S.toolsHidden));
      if (a === 'tgall') H.clear(); else if (a === 'tgnone') v.toolGroups().forEach(n => H.add(n)); else if (!H.delete(b.dataset.tg)) H.add(b.dataset.tg);
      if (v.S.toolsFolded) v.setTools(false);   // on a folded bar a tick would change nothing seen (T-12)
      v.setToolsHidden([...H]); }
    else if (a === 'compact') v.setToolsCompact({ on: true, off: false }[b.dataset.v] ?? 'auto');
    else if (a === 'arrange') v.arrange(true, e.detail === 0);   // by the keys: the dialog too
    else if (a === 'barreset') v.barReset();
    else if (a === 'sload') v.pickState();
    else if (a === 'sreload') v.reloadState();
    else if (a === 'sforget') { const h = v.root.querySelector('.bar .pfile').getBoundingClientRect();
      v.askYes(h.left, h.bottom + 4, 'Forget the kept view?', 'What this browser keeps of this view goes: the rows hidden and grouped, the paint, the ' +
        'bookmarks and markers, the look, the assertions bound; and the state loaded last (Reload). The waves come back as they came. ' +
        'Undo cannot bring it back.', () => v.forgetView(), 'Forget'); }
    else if (a === 'dopen') v.openDump();
    else if (a === 'gapvx') v.setGaps({ gapView: false });
    else if (a === 'gaps') v.seq('gv');
    else if (a === 'cycles') { const co = v.cycOpt(); if (!co.cycles && !cycClock(v.M.rows, co.cycleClock)) v.toast('no clock found: the right button on ' +
      'a 1-bit signal, Cycles ▸'); else v.setCycles({ cycles: !co.cycles }); }
    else if (['copyimg', 'copyall', 'svgall', 'png', 'svg', 'wdjson', 'wdcopy'].includes(a)) {
      const ex = v.exportRows(); v.picAct(a, v.range, ex ? { rows: ex } : {}); }
    else if (a === 'dcmp') v.cfile.click();
    else if (a === 'druns') v.runsPanel();
    else if (a === 'dcmpx') { if (v.cmpReading) v.compareStop(); else v.compareOff(); }
    else if (a === 'dcmpgo') v.compareGo();
    else if (a === 'dcmpv') v.compareView(b.dataset.run);
    else if (a === 'dcmpm') v.seq('gb');
    else if (a === 'dprev' || a === 'dnext') v.diffStep(a === 'dnext' ? 1 : -1);
    else if (a === 'dsrc') v.srcfile.click();
    else if (a === 'svload') { const s = v.root.querySelector('button[data-sv=load]'); if (s) s.click(); }
    else if (a === 'dreload') v.reloadDump();
    else if (a === 'live') liveClick();
    else if (a === 'more') v.popToggle(b, b.closest('.tg').querySelector(':scope > .more'));
    v.barSync();
  }
}
