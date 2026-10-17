/* wavefw.config.js — global settings for every wave on a page. Load it before wavefw.js:
     <script src="wavefw.config.js"></script> <script src="wavefw.js"></script>
   The same keys work in a WaveJSON "config" object (one diagram), in data-config='{…}' on one element, in the
   "config" section of a vcd2wavedrom.py / mkhtml.py config file, and in WaveFW.configure({…}) at run time
   (null removes a key). Values here are the built-in defaults, except sortIgnore. */
window.WAVEFW_CONFIG = {
  theme: null,                  // 'light' | 'white' | 'dark'; null = auto (prefers-color-scheme)
  colors: {},                   // trace bus x xfill z bg header grid text muted accent page c3…c9, or any --css-var
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
  radix: 'auto',                // bus values: 'auto' (≤6 bits dec, else hex) | 'hex' | 'dec' | 'signed' | 'bin' | 'oct' | 'ascii'
  fold: null,                   // groups folded at start: true | depth (number) | ['group.path', …]
  highlight: null,              // instances highlighted at start: ['tb.dut.u_tx', '*.irq'] (paths, names, * patterns)
  dim: 0.3,                     // opacity of the rows that are not highlighted
  arrowLabels: 'lane',          // bookmark arrow labels: 'lane' (a thin row of their own between signals) | 'overlay' (on the arrow)
  laneHeight: 16,               // px per label in such a lane
  groupOrder: 'file',           // inside every group: 'last' = signals first, then the sub-groups (modules); 'first'; 'file' = as given
  findHighlight: true,          // fuzzy find: found rows in front, the rest dimmed
  findOpen: true,               // fuzzy find: every module folded except the ones with a match
  moduleShading: true,          // signals of neighbouring modules on alternating backgrounds, a line where the module changes
  maxHeight: null,              // e.g. '80vh' or 600: the rows scroll inside the viewer (the bar stays in view); null = page scroll
};
