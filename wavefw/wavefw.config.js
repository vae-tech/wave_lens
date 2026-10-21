/* wavefw.config.js — global settings for every wave on a page. Load it before wavefw.js:
     <script src="wavefw.config.js"></script> <script src="wavefw.js"></script>
   The same keys work in a WaveJSON "config" object (one diagram), in data-config='{…}' on one element, in the
   "config" section of a vcd2wavedrom.py / mkhtml.py config file, and in WaveFW.configure({…}) at run time
   (null removes a key). Values here are the built-in defaults, except sortIgnore. Layers, later wins: these, the
   diagram's "config", the element's data-* / options, and one of the viewer's own: the edge style picked in its bar,
   kept in this browser for that viewer (the bar's "auto" gives the setting back). An unknown key is a console warning
   in the page and an error in the tools. */
window.WAVEFW_CONFIG = {
  theme: null,                  // 'light' | 'white' | 'dark'; null = auto (prefers-color-scheme)
  colors: {},                   // trace bus x xfill z bg header grid text muted accent page c3…c9 band, or any --css-var
  rowHeight: 26,                // px: signal row
  groupHeight: 22,              // px: group header row (static SVG default: 20)
  spaceHeight: 14,              // px: {} spacer row (static SVG default: 12)
  headerHeight: 24,             // px: time axis of the viewer
  nameWidth: 200,               // px: name column of the viewer
  fontSize: 11.5,               // px: signal names
  labelSize: 11,                // px: bus value labels
  fontMono: null,               // CSS font-family list for names/labels (default: IBM Plex Mono, …)
  fontBody: null,               // CSS font-family list for titles (default: IBM Plex Sans, …)
  traceWidth: 1.4,              // px: 1-bit traces and z lines
  busWidth: 1.2,                // px: bus outlines
  sort: 'none',                 // initial order: 'none' (file order) | 'asc' | 'desc'
  sortIgnore: ['i_', 'o_'],     // name prefixes skipped when sorting (i_valid sorts as "valid")
  sortButton: true,             // Sort button + prefix field in the viewer bar
  hint: true,                   // help line under the viewer
  style: 'auto',                // edges: 'auto' | 'wavedrom' (slanted) | 'questa' / 'square' (vertical, like a simulator)
  radix: 'auto',                // bus values: 'auto' (≤6 bits dec, else hex) | 'hex' | 'dec' | 'signed' | 'bin' | 'oct' | 'ascii' | 'float' | fixed point 'q8' / 'sq15'
  enumColors: null,             // the fill of a bus value by its label or number: {"ACCESS": "#d0ebff", "3": "c5"}
  fold: null,                   // groups folded at start: true | depth (number) | ['group.path', …]
  highlight: null,              // instances highlighted at start: ['tb.dut.u_tx', '*.irq'] (paths, names, * patterns)
  dim: 0.3,                     // opacity of the rows that are not highlighted
  groupColors: null,            // one colour per group: {aw: '#339af0', 'tb.dut.u_rx': '#37b24d', '*.fifo*': …} (path, name, * pattern)
  arrowLabels: 'lane',          // bookmark arrow labels: 'lane' (a thin row of their own between signals) | 'overlay' (on the arrow)
  laneHeight: 16,               // px per label in such a lane
  groupOrder: 'file',           // inside every group: 'last' = signals first, then the sub-groups (modules); 'first'; 'file' = as given
  findHighlight: true,          // fuzzy find: found rows in front, the rest dimmed
  findOpen: true,               // fuzzy find: every module folded except the ones with a match
  findCase: false,              // find options (Aa Full .* in the find group): the case matters,
  findWord: false,              //   a word is the whole name (a.b: the end of the full path),
  findRegex: false,             //   the query is a regular expression (grep -E, JavaScript RegExp; \< \> as in vim)
  wheel: 'scroll',              // the wheel scrolls the rows, ctrl+wheel zooms (as in Questa); 'zoom': the wheel zooms
  dumpBudget: 3000000,          // a VCD opened in the page (Open…, dropped): the signals nearest the top up to this many value changes
  svaOpen: false,               // sva.js: the assertion list open at start (false: folded, ▸ Assertions opens it)
  busDetect: true,              // bus.js: the bus ports found by their signal names (AXI, AXI-Stream, APB, AHB, Avalon, Wishbone, OBI) drawn as transactions
  buses: null,                  // bus.js: ports of your own [{protocol, scope, prefix?, map?: {role: name}, clock?, name?}] (busDetect: false: only these)
  menuTipDelay: 2000,           // ms: the wait before a tooltip in that menu (the bar's: 350 ms)
  contextMenu: true,            // the right button on the waves: a range and the viewer's menu (picture, colour, …); false: the browser's
  cursorSnap: 8,                // px: a click on the waves puts the cursor on an edge of that signal this near (alt+click: not); 0 = off
  moduleShading: true,          // signals of neighbouring modules on alternating backgrounds, a line where the module changes
  svaSignals: 'view',           // assertion groups (sva.js): the bound signals again under the steps: 'view' (viewers), true (also static SVGs), false
  svaShow: null,                // assertion groups drawn: null = all, or labels / * patterns ['apb_*']
  gaps: false,                  // the pictures and WaveDrom saved (menu of the right button; static SVGs too): stretches where no signal but a clock
                                //   changes left out, a break "|" in their place (the viewer's menu turns it on and off)
  gapIdle: 16,                  //   a gap where nothing changes this long: clock cycles (16) or a time ('2us')
  gapKeep: 2,                   //   kept after the last change and before the next one: cycles or a time
  gapSignals: null,             //   the signals the gaps follow (paths, names, * patterns; the menu's "Gaps ▸ By this signal"); null: every one drawn
  gapClock: null,               //   the clock whose cycles gapIdle, gapKeep and the texts count ("Gaps ▸ Count in cycles of this clock"); null: the one found
  gapAux: null,                 //   the signals counted in a gap ("Gaps ▸ Count its changes in a gap"); null: every one but the gapSignals and the clock
  gapOnly: false,               //   the viewer's picture and WaveDrom: only the gapSignals, the clock and the gapAux ("only them")
  gapCount: 'clock',            //   texts: 'clock' (under the axis the time left out and the clock cycles), 'edges' (also a thin row under
                                //   each signal counted with its rising / falling edges in the stretch left out, a bus its changes), 'off'
  gapLine: 'dashdot',           //   the line of a gap: 'dashdot' | 'wave' | 'waves' | 'zigzag' | 'double'
  maxHeight: null,              // e.g. '80vh' or 600: the rows scroll inside the viewer (the bar stays in view); null = page scroll
                                //   (the bar sticks to the top while its rows go by); the bar's Scroll button switches on the fly
  toolsFolded: false,           // the bar's tools folded to its title line (▴ / ▾ in the bar)
};
