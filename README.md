# wavefw — WaveDrom JSON → interactive waves

A dependency-free HTML/JS framework that renders **WaveDrom JSON** with the look and interaction of the
waveform panels in `template.html`. Two renderers share one model:

- `WaveView`: an interactive canvas viewer. It has a name column with values at the cursor, wheel zoom, drag pan, cursor, `+ − 0 ← → s` keys, markers, jump buttons, foldable groups and signal sorting (with name prefixes such as `i_`, `o_` ignored).
- `WaveSVG`: a static, WaveDrom-style inline SVG for documents and print. It follows the page's light/dark tokens.

No build step, no bundler: open the page from `file://`.

```
wavefw.js / wavefw.css      framework (one <script> + one <link>)
wavefw.config.js            global settings file (all keys, with defaults), loaded before wavefw.js
example.html                datasheet-style demo and reference page
demo_waves.js               generated demo data (make demo)
dump.config.json            converter + page settings for dump.vcd (make html CONFIG=dump.config.json HTML=dump.html)
wavefw.base.json            base settings for generated configs (make config / make html WAVES=x.vcd)
test_stream_video.config.json  generated from test_stream_video.vcd by mkconfig.py: every signal, editable
tools/mkconfig.py           VCD/FST -> editable config: every signal under its full path, per-signal settings
tools/dumpscan.py           the built-in reader: a dump as VCD text (FST via fst2vcd -e): signals, changes, enum tables
tools/vcd2wavedrom.py       VCD/FST -> WaveDrom JSON, via wavepeek (options on the command line or in a config file)
tools/mkhtml.py             config views or WaveJSON files -> one self-contained HTML page (make html)
tools/embed.py              JSON -> data.js (file:// pages) or into an HTML placeholder
tools/wavejson.py           readable JSON output shared by the tools (one signal per line, wrapped "tv" lists)
tools/demo/demo.config.json settings of the demo (make demo, make html)
tools/demo/demo_tb.sv       Manchester transmitter + testbench (Verilator)
tools/conformance.html      every feature next to stock WaveDrom 3.5.0 (tools/vendor/, test-only)
tools/smoke.py              headless Chromium check + screenshots (playwright)
```

## Use

```html
<link rel="stylesheet" href="wavefw.css">
<script src="wavefw.js"></script>

<script type="application/wavedrom">          <!-- interactive viewer -->
{ "signal": [ { "name": "clk", "wave": "p....." }, { "name": "d", "wave": "x.34.x", "data": ["A", "B"] } ] }
</script>
<script type="WaveDrom"> {signal: [{name: 'req', wave: '01..0'}]} </script>   <!-- static SVG -->
<div data-wave="DEMO_WAVES.exact" data-lazy></div>                           <!-- from a data file, lazy -->
```

| Attribute | Meaning |
|---|---|
| `data-wave="#id"` / `"VAR.key"` | model from a script element or a global (data `.js` loaded with `<script src>`) |
| `data-mode="view"` / `"svg"` | renderer (default: `view`; `svg` for `type="WaveDrom"`) |
| `data-from`, `data-to` | viewer: initial window; SVG: drawn window. Numbers are model units; `120ns` / `1.5us` are times |
| `data-cursor`, `data-title`, `data-width`, `data-fit` | cursor, bar title, SVG width px, scale SVG to container |
| `data-sort="asc"`, `data-sort-ignore="i_,o_"` | initial signal order and the prefixes skipped when sorting |
| `data-config='{"rowHeight": 30}'` | any setting (see *Settings*) for this wave |
| `data-lazy` | build on button click, or when the enclosing `<details>` opens |
| `<script src="wavefw.js" data-manual>` | no automatic upgrade; call `WaveFW.upgrade(root)` |

JavaScript: `WaveFW.parse(jsonOrText)`, `new WaveView(el, model, {title, cursor, markers, jumps, from, to, minSpan})`,
`WaveSVG.render(el, model, {from, to, width, cyclePx, axis, bg, fit, markers})`, `WaveSVG.toString(model, opts)`,
`WaveFW.enums[name] = {0: 'IDLE'}`, `WaveFW.fromTV(wave)` (converts `template.html`'s `{t0, t1, signals: [{name, w, t}]}`),
`WaveFW.configure(settings)`, `view.setSort('asc' | 'desc' | 'none', 'i_,o_')`, `WaveFW.sortRows(model, dir, ignore)`.
Viewers redraw when the theme changes (`prefers-color-scheme`, `data-theme`/`style` on `<html>`, `setTheme`/`setColors`), when the size changes and once web fonts have loaded.

## Themes and colours

Three themes: `light` (warm paper, as in `template.html`), `white` (pure white, black traces and stock-WaveDrom bus
colours, for print and slides) and `dark`. Every colour is a CSS custom property, so a theme or palette can be applied at three levels:

| Level | How |
|---|---|
| page + all waves | `<html data-theme="white">`, `WaveFW.setTheme('white')`, `WaveFW.setColors({trace: '#c00', bus: 'navy'})`. No theme = auto (`prefers-color-scheme`) |
| one wave | `data-theme="dark"` / `data-colors='{"trace":"#7ee787"}'` on the element or its `<script>`; `"config": {"theme": "white", "colors": {…}}` in the JSON; `view.setTheme()` / `view.setColors()`; `WaveFW.setTheme(name, el)` |
| one signal | `"stroke": "#d6336c"` (trace, bus outline, name), `"fill": "#e5dbff"` (bus fill); a colour string in `"color"` acts like `stroke` |

Colour keys: `trace bus x xfill z bg header grid text muted accent page c3…c9`, or any CSS custom property name
(`--wave-1` …). A `null` value removes the override, and `setTheme('auto')` drops the theme. A wave with its own theme or palette is not changed by
the global calls. A themed static SVG paints its own background.

## Settings (config file)

Colours, sizes, fonts, line widths and sorting are *settings*. Layers, later wins:

1. built-in defaults (`WaveFW.defaults`)
2. global: `wavefw.config.js` loaded before `wavefw.js` (it sets `window.WAVEFW_CONFIG`), or `WaveFW.configure({…})` at run time (viewers and SVGs are redrawn, `null` removes a key)
3. the diagram's `"config"` object in the WaveJSON
4. the element: `data-config='{…}'`, `data-sort`, `data-sort-ignore`, `data-theme`, `data-colors`, or constructor options

| Key | Default | Meaning |
|---|---|---|
| `theme`, `colors` | auto, `{}` | as in *Themes and colours*; globally they go to `<html>` |
| `rowHeight`, `groupHeight`, `spaceHeight`, `headerHeight` | 26, 22, 14, 24 | row heights, px (static SVG: group 20, spacer 12) |
| `nameWidth`, `fontSize`, `labelSize` | 200, 11.5, 11 | name column, name text, bus labels, px |
| `fontMono`, `fontBody` | IBM Plex | CSS font-family lists (`--font-mono`, `--font-body`) |
| `traceWidth`, `busWidth` | 1.4, 1.2 | line widths, px |
| `sort`, `sortIgnore` | `none`, `[]` | `none \| asc \| desc`; prefixes skipped when comparing names (array or `"i_,o_"`) |
| `sortButton`, `hint` | true, true | show the Sort controls / the help line |
| `style` | `auto` | edges: `wavedrom` (slanted 1-bit edges, `<>` bus ends), `questa` (vertical edges, narrow bus crossings), `square` (vertical, square bus ends); `auto` slants wave strings and draws exact `tv` transitions vertically |
| `radix` | `auto` | bus values from `tv`: `auto` (≤ 6 bits decimal, else hex) `hex dec signed bin oct ascii` |
| `fold` | none | groups folded when a viewer opens: `true`, a nesting depth (`2`), or group paths (`["tb.dut"]`) |
| `arrowLabels`, `laneHeight` | `lane`, 16 | bookmark arrow labels in a thin row of their own between the signals (px per label), or `overlay` on the arrow |
| `groupOrder` | `file` | inside every group: `last` = its signals first, then the sub-groups (modules); `first` = the other way round; `file` = as given (also when sorted). Generated configs use `last` |
| `findHighlight`, `findOpen` | true, true | starting state of the fuzzy-find options (see *Fuzzy find*) |
| `moduleShading` | true | the signals of neighbouring modules alternate between two backgrounds, with a line where the module changes; module rows are bold on a darker band |
| `maxHeight` | none | e.g. `"80vh"`: rows scroll inside the viewer; any number of rows (the canvas covers only the visible part) |
| `highlight`, `dim` | none, 0.3 | instances highlighted at start (full paths, names, `*` patterns; one colour each) and the opacity of the other rows |

A signal's own `"style"` and `"radix"` override the settings.

The converter config file (below) has a `"config"` section with the same keys. `vcd2wavedrom.py` writes it into the
WaveJSON `config`, and `mkhtml.py` uses the top-level one as the page's global settings.

### Highlighting instances

Every name row has a mark ○ in its left gutter (visible on hover). Clicking it, or ctrl/⌘+clicking the name, highlights
that signal or group; a group covers all its members, so one click picks a whole instance (`tb_cxp_top ▸ cxp_device_top_i`).
Highlighted rows stay in front with a colour bar and tint; all other rows fade to `dim` opacity but stay visible, and the
headers of groups that contain a highlighted row stay in front. Several instances can be highlighted at once, each in its
own colour (`--wave-hl1…6`, `colors: {hl1: …}`). **Highlight: N ✕** in the bar or Esc clears. From JSON / config files:
`"highlight": ["tb.dut.u_tx", "*.irq"]`; on an element: `data-highlight="tx"`; in code: `view.highlight([...])`,
`view.toggleHighlight('tb.dut')`, `view.highlighted()`. Static SVGs follow the setting.

### Viewer bar

The bar has a title line (title, short messages such as "copied 3", cursor and view span) and the tools in labelled
groups: **cursor** (a time and its unit ps … s, **Set** puts the cursor there; a span and **Show** gives a window of that
width centred on the cursor, key `c` does it with the current width; a typed unit such as `85.12us` wins over the list;
cycle diagrams count in cycles; the fields follow the cursor and the view), **view** (− + Fit), **find** (field, count, ‹ ›, Highlight / Open, colour + Paint, Unpaint, Copy), **list**
(Sort with the ignored prefixes, Expand / Collapse, clear highlight), **edges** (◀ edge kind ▶, + Mark) and **go to**
(marker jumps). Keys work while the waves have the focus, which a click on the waves or on a name gives them:
`+ − 0` zoom, `← →` pan, `c` window at the cursor, `↑ ↓` select a signal, `/` find, `n N` next / previous match, `[ ]` edges, `e` edge kind,
`m` bookmark, `s` sort, ctrl+C copy, Esc reset.

### Fuzzy find

The **find** field in the viewer bar (key `/`) searches the way fzf / telescope do in nvim: the typed letters must appear
in that order anywhere in a name, not necessarily next to each other (`pxvd` finds `s_pix_valid`, `txarb` finds
`cxp_tx_arbiter_i`). A word with a `.` runs over the full path (`dev.fifo` = a `fifo…` somewhere below a `…dev…`
module), and words separated by spaces must all match. Matched letters are underlined in the names, the count is shown,
Enter / shift+Enter, the ‹ › buttons, or `n` / `N` on the waves (as in vim) go to the next / previous match (opening
its modules). Esc clears the search but leaves the view as
it is (the modules it opened, the scroll position, the selected signal), so you stay at what you found; switching **Open**
off is what brings the earlier folding back. On the waves (canvas focused), ctrl+C ends the search the same way.

**Esc resets.** Esc anywhere in the viewer (waves, find field, names; not in the bookmark fields) brings back the plain
state: no search, no highlighted rows (also those from the `highlight` setting), no selected signal. The view stays as it
is: opened modules, scroll position, time window. Paint colours are kept (Unpaint removes them). Options, applied live while typing:

- **Highlight**: found rows (signals and modules) in front, everything else dimmed (like a highlight, in the accent colour)
- **Open**: every module folded except the ones that contain a match; clearing the search brings the previous folding back
- **colour + Paint**: give the found signals that colour (trace, outline, name); kept in the browser, **Unpaint** undoes it
- **Copy**: the full paths of the found rows, one per line

**Copying signal names.** Select names in the names column with the mouse and copy (ctrl+C): the clipboard gets the full
paths of those rows, one per line, without values. With a signal selected and no search running, ctrl+C on the waves copies its
path (with nothing selected: the highlighted rows). A short "copied N" shows in the bar.

### Edge search and bookmarks

Click a signal name or its row on the waves to select it (↑ ↓ move the selection). **◀ ▶** (`[` `]`) move the cursor to the
previous / next edge of the selected signal, of the kind chosen between them (`e`): any edge, rising or falling. On buses
every value change counts. With nothing selected, the nearest change of any shown signal is used. **+ Mark** (`m`) puts
a numbered bookmark (a circle on the signal row) at the cursor, snapped to an edge within 6 px. Below the waves each bookmark
has an editable time (`250ns`, `85.12us`, or a number in the unit shown; the cursor button moves it to the cursor), a signal (or the time axis), the
edge found there, a colour (default: the accent) and a text field for the event. On the waves, drag a circle to move it
(time snapped to an edge of the row under the pointer, row = signal), and shift+drag from one circle to another to draw an
arrow. Arrows have from → to, shape (WaveDrom edge shapes `- ~ -~ ~- -| |- -|-`), head (end, both, start, none), line
(solid, dashed, dotted), colour and label; any number per bookmark. A label is written into a thin lane inserted between
the signals under the arrow's upper end (above the row when both ends share it), never over a wave; `laneHeight` sets its
height, `arrowLabels: "overlay"` draws labels on the arrows instead. Click a number to go there, an arrow to edit its label.
Bookmarks are kept in the browser (`localStorage`); **JSON** gives `"bookmarks"` and `"arrows"` lists to paste into a config
file or a view, so a page built by `make html` and its static SVG (with a legend of the texts) carry them. **Expand** /
**Collapse** open or fold all groups. In code: `el.waveView` (`select`, `edge`, `mark`, `arrow`, `bookmarks`, `arrowList`,
`setBookmarks`, `expandAll`, `collapseAll`).

### Sorting

The viewer's **Sort** button cycles *off → A→Z → Z→A* (key `s`). The field next to it lists prefixes that are ignored
when names are compared, so with `i_,o_` the signal `i_valid` sorts as `valid`; the skipped prefix is drawn dimmed. Names compare
naturally (`d2` before `d10`, ties broken by the full name). Groups move as a block and are sorted inside, and `{}`
spacers split the list into runs that are sorted separately.

## Supported WaveDrom subset

| Feature | Notes |
|---|---|
| `0 1` | levels with soft (slanted) edges |
| `h l` / `H L` | levels with sharp edges / plus an edge arrow |
| `p n` / `P N` | clocks (rising / falling at cell start) / plus an arrow |
| `x` | hatched, drawn in `--wave-x` (stock WaveDrom uses black) |
| `z` | mid-level line in `--wave-z` |
| `u d` | pull-up / pull-down, dashed |
| `=` `2`–`9` | bus segments with `data` labels (array or space-separated string); 3–9 use fill tokens `--wave-c3…c9` |
| `.` `\|` | extend; extend + gap mark |
| `period`, `phase` | per signal; a positive phase is clipped at cycle 0 like stock |
| `node`, `edge` | shapes `- ~ -~ ~- -\| \|- -\|-`, arrows `<` `>`, `+`; labels; lowercase nodes are labelled |
| groups `["name", …]`, `{}` | nested groups are header rows (foldable in the viewer, bracketed in SVG) rather than stock's rotated labels |
| `head.text/tick/every`, `foot.text/tock`, `config.hscale` | |

Not supported: `<…>` sub-cycles, `reg` diagrams, skins, JsonML styling inside text (only the text is used). Unknown wave
characters are treated as `.` (note: `,` is not a WaveDrom character).

### Extensions (stock WaveDrom ignores them)

| Key | Meaning |
|---|---|
| `time: {t0, cycle, t1?, skip?}` | cycle *c* starts at `t0 + c·cycle` ps, so the axis shows real time; `skip: [[k, n]]` = the `\|` cell at index *k* stands for *n* cycles |
| `signal[i].tv: [[t, v], …]` | exact transitions in model time (ps when `time` is set). 1-bit: `0 1 x z`; bus: hex. Takes precedence over `wave` |
| `signal[i].width / enum / radix / style / color` | bus width, value labels (`{"0": "IDLE"}`), value radix (`fmt` is an alias), edge style, fixed fill 3–9 |
| `signal[i].path`, `same` | full hierarchical path (the name's tooltip); `"same": "tb.clk"` = the `tv` of the signal with that `path` (one net seen at several levels is stored once) |
| `bookmarks: [{n, t, signal, text, color}]` | numbered events on signal rows (`signal` = full path, `t` in model units or `"85.12us"`); static SVGs add a legend of the texts |
| `arrows: [{from, to, shape, head, line, color, label}]` | arrows between bookmarks: shape `- ~ -~ ~- -\| \|- -\|-`, head `> <> <` or `""`, line `solid dashed dotted` |
| `markers: [{t \| cycle, label}]` | dashed markers. They become jump buttons when there are ≤ 6 and no `jumps` are given |
| `jumps: [{t \| cycle, span, label}]`, `cursor` | jump buttons and the initial cursor |

## VCD / FST → WaveDrom

`tools/vcd2wavedrom.py` writes WaveJSON. Two readers give the same output:

- **builtin** (default): `tools/dumpscan.py` reads the dump once as VCD text (an FST through GTKWave's `fst2vcd -e`),
  keeps only the requested signals, and computes the window, clock sampling and markers in memory. Paths are spelled as
  wavepeek spells them (`mem.[1]`, bit-blasted vectors joined, `sig[7:4]` bit selects). Markers: `posedge X`,
  `negedge X`, `edge X`, or `X` (any change).
- **wavepeek** (`--reader wavepeek`, `"reader": "wavepeek"` in a config, `make … READER=wavepeek`): runs
  [wavepeek](https://github.com/kleverhq/wavepeek) (`info`, `value`, `change`); markers may be any wavepeek `--on`
  expression. It needs wavepeek on `PATH` or in `~/.local/bin`
  (`cargo build --release --manifest-path ~/tools/wavepeek_src/Cargo.toml`); it is also used when an FST cannot be read
  as text (no fst2vcd).

Measured on this machine (16 CPUs), output byte-identical between the readers:

| Job | builtin | wavepeek |
|---|---|---|
| `test_stream_video.vcd` (24 MB), every changing signal: 1526 signals, 4.8 M changes | 25 s, 1.5 GB | 45 s, 2.9 GB |
| `mkconfig.py test_stream_video.vcd` (3520 signals listed, changes counted) | 5.4 s | 12 s |
| `dump.vcd` (14 MB), view `full` (15 signals, exact, markers) | 2.0 s | 7.0 s |
| `dump.vcd`, view `start` (clock-sampled 2 µs) | 1.2 s | 2.6 s |
| demo (25 signals) | 0.15 s | 0.19 s |

In the first row the builtin reader spends 4.8 s reading the dump; the rest is building the JSON, which both share.

```sh
# clock-sampled: one cycle per clock period, plain WaveDrom wave strings + "time"
python3 -I tools/vcd2wavedrom.py --waves dump.vcd --scope tb --clock clk --from 20ns --to 370ns \
    --signals clk,start,data,state,txd=TXD --enum state=0:IDLE,1:START,2:DATA,3:PARITY \
    --group tx=state,TXD --gap 100ns:250ns --out cyc.json

# exact: per-signal "tv" transitions (+ a quantised wave string as a fallback for stock WaveDrom)
python3 -I tools/vcd2wavedrom.py --waves dump.vcd --scope tb.u_dut --exact --from 896us --to 1155us \
    --signals i_sat_rxd_comp,r_state,o_sat_data --marker 'posedge o_sat_data_eof=eof' --out frame.json

python3 -I tools/embed.py --var WAVES frame=frame.json --out waves.js        # <div data-wave="WAVES.frame">
python3 -I tools/embed.py --html template.html --placeholder '/*WAVE_DATA*/' frame.json --out page.html

# all options from a config file; --view picks one entry of "views"; command-line options win
python3 -I tools/vcd2wavedrom.py --config dump.config.json --view full --out full.json
```

The generated JSON has line breaks: one key per line, one signal per line, a group opens a block, and long `tv` lists
are wrapped at 16 transitions per line. `embed.py` writes the same layout (`--compact` gives one line).

### From the VCD or FST alone (make config)

```sh
make html WAVES=test_stream_video.vcd     # makes test_stream_video.config.json (if missing), then test_stream_video.html
make config WAVES=test_stream_video.vcd   # after the dump changed: adds new signals, drops gone ones, keeps your edits
python3 -I tools/mkconfig.py dump.vcd [--base my.base.json] [--depth 3] [--out x.config.json] [--update | --force]
```

`tools/mkconfig.py` lists every signal of the dump (wavepeek; declaration order, value-change counts and enum tables read
from the VCD text, or from an FST through GTKWave's `fst2vcd -e`) and writes one line per signal under its full
hierarchical path:

```json
"signals": {
    "tb_cxp_top.app_clk":    {"show": true,  "radix": "", "color": "#2f9e44", "style": "", "width": 1,  "changes": 32123},
    "tb_cxp_top.s_pix_data": {"show": true,  "radix": "", "color": "",        "style": "", "width": 16, "changes": 2189},

    "tb_cxp_top.cxp_device_top_i.cfg.run": {"show": false, "radix": "", "color": "", "style": "", "width": 1, "changes": 2}
}
```

Edit it by hand: `show` (false = left out), `radix` (`auto hex dec signed bin oct ascii`), `color` (trace, outline and
name), `style` (`auto wavedrom questa square`); optional `alias`, `fill`, `enum`. `""` means the global value from `"config"`
(`style`, `radix`, `fold`, `theme`, `colors`, …). `width` and `changes` are information only. With `"hierarchy": true` the
page nests the signals in groups by scope (`tb_cxp_top ▸ cxp_device_top_i ▸ …`); hover a name for its full path.
A view may select from the catalog with patterns: `"signals": ["tb_cxp_top.s_pix_*", "tb_cxp_top.app_clk"]`, and may be
clock-sampled (`"clock": "tb_cxp_top.app_clk", "from": "84us", "to": "85us"`).

The starting values come from the base file `wavefw.base.json` (`BASE=` in make, `--base`): its `config`, `page`,
`views`, `exact`, `hierarchy` are copied, and two generator keys decide the per-signal defaults:

- `select`: `depth` (scope levels below the top that start shown, 2), `constants` (show signals that never change, false),
  `hide` (path patterns, `$rootio.*` — Verilator's copy of the top ports), `budget` (most value changes on one page,
  1.5 M; deeper levels are dropped first)
- `rules`: `[{"match": ["*clk", "*clk_i"], "width": 1, "color": "#2f9e44"}, …]` — any per-signal key by path pattern
  (`*`, `?`) and optional width (`8`, `">1"`, `">=32"`); later rules win

`make html WAVES=x.vcd` never overwrites an existing `x.config.json`.

**Hierarchy depth.** `select.depth` is 99 (every level), so the page has the whole scope tree of the dump down to the last
level (`test_stream_video.vcd`: 205 scopes, 9 levels, 1526 changing signals); `fold: 2` only folds the deeper groups at
start (**Expand** opens all). Only when the shown signals have more than `budget` value changes (6 M) are the deepest
levels left out (`show: false`, the message says which depth was kept); `--depth N` or the base file changes this.
Constant signals (parameters, package constants) start hidden. The viewer draws any number of rows: the canvas covers
only the visible part (it stays in view while the rows scroll, the time axis on top), and `maxHeight: "80vh"` in the
base file gives the rows their own scroll bar so the viewer bar stays in view.

**FSM states by name.** An FST (Verilator `--trace-fst`) carries the enum tables of the design; `mkconfig.py` writes them
into the signal entries (`"enum": {"0": "IDLE", …}`) and `vcd2wavedrom.py` uses them directly, so state buses show
`IDLE`, `START`, … (`make demo-fst` shows it). A VCD has no enum information: `--sv rtl/*.sv` (make: `SV="rtl/*.sv"`)
reads `typedef enum … {…} name_t;` and inline `enum {…} var;` from the sources and labels the signals declared with those
types (by signal name), or write `"enum"` into an entry by hand.

### Config file

Every option is a key (`from`, `to`, `signals`, `clock` / `exact`, `scope`, …). Relative `waves` paths are relative to the config file.

```json
{
  "waves": "dump.vcd", "scope": "tb_top",
  "enum": { "state": { "0": "IDLE", "1": "RUN" } },
  "config": { "theme": "white", "colors": { "bus": "navy" }, "rowHeight": 24, "sort": "asc", "sortIgnore": ["i_", "o_"] },
  "page": { "title": "my dump", "intro": "text under the title" },
  "views": {
    "start": { "clock": "clk", "from": "0ns", "to": "2us", "signals": ["clk", "state", "i_data"],
               "group": { "core": ["state", "i_data"] }, "gap": ["1us:1.5us"], "render": "svg" },
    "full":  { "exact": true, "signals": "clk,state,i_data", "marker": ["posedge done=done"], "note": "whole run" }
  }
}
```

A view overrides the top-level keys (`config` and `enum` are merged). `render` (`view` | `svg` | `both`) and `note`
are used by `mkhtml.py` only.

### HTML page (make html)

```sh
make html                                           # demo config -> /tmp/wavefw_demo.html
make html CONFIG=dump.config.json HTML=dump.html    # any dump; WAVES=other.vcd overrides the config's dump
python3 -I tools/mkhtml.py --config cfg.json --view full --out page.html
python3 -I tools/mkhtml.py a=a.json b=b.json --settings cfg.json --out page.html   # from WaveJSON files
```

The page is one file: `wavefw.css`, `wavefw.js` and the data are inlined, so it can be mailed or archived. It has a theme button.

### Large dumps

`test_stream_video.vcd` (24 MB, 3520 signals in 214 scopes, 160 µs, 4.9 M value changes): `mkconfig.py` takes about
12 s; with every changing signal on every level (1526 signals, 4.8 M value changes) `make html` writes a 6.3 MB page in
about 55 s, which opens in about 2 s; Expand (1731 rows, 41 000 px) takes 0.1 s and a redraw 4 ms. Identical
transitions of one net seen at several levels are stored once (`"same"`). Long signal lists are split over several
wavepeek calls run in parallel (each call reads the whole dump; one argument is limited to 128 KiB).

Checked with `dump.vcd`: 14 MB, 355 signals, 226 µs. A full-range exact view of 15 signals (56 k clock edges,
25 k bus values) converts in about 2 s, a clock-sampled 2 µs window in 0.5 s, and `make html` writes a 2.3 MB page.
Transitions closer than 1 px are drawn as one solid bar, so a full-range redraw takes about 6 ms instead of 400 ms.
Widths come from wavepeek's value literals, so signals in child scopes (`u_core.state`) are buses, not bits.
Repeated values (for example the initial `$dumpvars`) are dropped from `tv`.

- `--clock` samples with `--on 'posedge CLK' --sample-mode native`, so each cell shows the value after the edge.
- `--exact` uses `--on '*' --row-mode sparse --row-values delta`, with a `value --at FROM` baseline.
- `--marker 'EXPR=label'` takes any wavepeek `--on` expression.
- Signals may be `path=alias` and may use bit selects (`status[7:4]`).

To check a window by eye, open the same dump in [Surfer](https://surfer-project.org)
(`cargo install --git https://gitlab.com/surfer-project/surfer surfer`) and compare the edges at the marker times.
Surfer is not a dependency.

## Demo and tests

```sh
make demo     # Verilator VCD (/tmp) -> vcd2wavedrom.py --config tools/demo/demo.config.json -> demo_waves.js
make html     # tools/mkhtml.py: the demo config's views -> /tmp/wavefw_demo.html
make html WAVES=x.vcd   # tools/mkconfig.py (x.config.json, if missing) + mkhtml.py -> x.html (x.fst works too)
make demo-fst # the demo dumped as FST -> /tmp/wavefw_demo_fst.html, FSM states named from the FST enum tables
make smoke    # tools/smoke.py: example.html + conformance.html (+ pages from make html), light & dark,
              # interaction, sorting and settings checks, PNGs in /tmp/wavefw_shots
```

Environment used: Verilator 5.046, wavepeek 3.1.0, Python 3 with playwright (Chromium). There is no node/npm.
`smoke.py` runs without `-I` because playwright is a user-site install.
