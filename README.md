# wavefw — WaveDrom JSON → interactive waves

wavefw draws **WaveDrom JSON** in two ways from one model: as an interactive canvas viewer (zoom, cursor, fold, find,
bookmarks) and as a static WaveDrom-style SVG for documents. A few Python tools turn a simulator dump (VCD or FST) into
one self-contained HTML page that you can mail or archive. One JavaScript file, one stylesheet, no build step, no
dependencies: the pages open from `file://`.

![The APB example in the dark theme: viewer bar, waves, numbered bookmarks and arrow labels in their own lanes](docs/img/hero.png)

## Quick start

```sh
make examples                   # needs Verilator: APB, AXI-Lite and FSM pages in /tmp/wavefw/examples/<ex>/<ex>.html
make html WAVES=work/my.vcd     # your dump -> work/my.config.json (every signal, editable) + work/my.html
```

Open the `.html` in a browser. `make html` reads the dump with the built-in reader (Python 3 standard library only).
Optional: GTKWave's `fst2vcd` to read FST dumps, [wavepeek](https://github.com/kleverhq/wavepeek) as a second reader,
Python playwright for the tests and the screenshots. `make` alone lists the targets; build products go to
`BUILD` (default `/tmp/wavefw`, because this repository lives on a slow Windows mount; `make BUILD=build …` keeps them
in the repository). The full reference with live examples is [`docs/index.html`](docs/index.html).

## Use cases

### WaveDrom JSON in your own page

```html
<link rel="stylesheet" href="wavefw/wavefw.css">
<script src="wavefw/wavefw.js"></script>

<script type="application/wavedrom">          <!-- interactive viewer -->
{ "signal": [ { "name": "clk", "wave": "p....." }, { "name": "d", "wave": "x.34.x", "data": ["A", "B"] } ] }
</script>
<script type="WaveDrom"> {signal: [{name: 'req', wave: '01..0'}]} </script>   <!-- static SVG -->
<div data-wave="DEMO_WAVES.exact" data-lazy></div>                           <!-- from a data .js file, built on demand -->
```

Every element is upgraded when the page loads. `data-mode="svg"` picks the static renderer, `data-from` / `data-to` /
`data-cursor` / `data-title` set the window, `data-lazy` builds the viewer when its `<details>` opens (*lazy cards*, for
pages with many diagrams), `data-config='{"rowHeight": 30}'` sets any setting. JSON from files goes into a data script
with `tools/embed.py` (a page from `file://` cannot `fetch()` it). Attributes and the JavaScript API:
[`docs/index.html` § API](docs/index.html#api).

### A dump to a page in one command

```sh
make html WAVES=work/my.vcd               # makes work/my.config.json if missing, then work/my.html
make html WAVES=work/my.fst               # FST (through fst2vcd): FSM states named from the dump
make config WAVES=work/my.vcd             # after the dump changed: new signals added, gone ones dropped, edits kept
make html CONFIG=work/dump.config.json    # a config written by hand -> work/dump.html
```

Keep your dumps and configs under `work/`: the configs are tracked, the dumps and pages are ignored by git. The page has
every view of the config, each as a viewer or a static SVG; scopes become foldable groups.

### The generated config, and what you edit in it

`tools/mkconfig.py` lists every signal of the dump under its full path, one line each:

```json
"signals": {
    "tb_cxp_top.app_clk":    {"show": true,  "radix": "", "color": "#2f9e44", "style": "", "width": 1,  "changes": 32123},
    "tb_cxp_top.s_pix_data": {"show": true,  "radix": "", "color": "",        "style": "", "width": 16, "changes": 2189},
    "tb_cxp_top.cxp_device_top_i.cfg.run": {"show": false, "radix": "", "color": "", "style": "", "width": 1, "changes": 2}
}
```

Edit `show` (false = left out), `radix` (`auto hex dec signed bin oct ascii`), `color`, `style`
(`auto wavedrom questa square`), and add `alias`, `fill` or `enum` (`{"0": "IDLE"}`); `""` takes the global value from
`"config"`. `width` and `changes` are information. Next to `signals`: `"config"` (page settings, below), `"page"` (title,
intro), and `"views"` — named variants, each with its own `signals` (patterns such as `"tb.*_valid"`), `from` / `to`,
`clock` (one cell per clock) or `exact`, `group`, `marker`, `bookmarks`, `arrows` and `render` (`view`, `svg`, `both`).
The starting values come from `tools/base.config.json` (`BASE=`): which scope depth starts shown, which paths are hidden,
how many value changes fit on a page, and rules by path pattern and width (`python3 -I tools/mkconfig.py --help`).
The example configs in [`examples/`](examples) are written by hand and show every key.

### FSM state names: FST, or VCD + sources

An FST written by Verilator (`--trace-fst`) carries the enum tables of the design, so state buses show `IDLE`, `START`, …
straight from the dump. A VCD has none: `make html WAVES=x.vcd SV="rtl/*.sv"` (`mkconfig.py --sv`) reads
`typedef enum {…} name_t;` from the sources and labels the signals declared with those types; or write `"enum"` into an
entry. The FSM example builds both pages.

![The FSM example: state names from the FST, questa edges, -|- arrows between the state changes](docs/img/fsm.png)

### Colours per signal, per group, per module

Colour is the quickest way to read a bus. Give every **channel** of a protocol its own colour — for AXI4-Lite the
address-write, write-data, write-response, address-read and read-data channels, for AXI4 the same plus the IDs and
bursts, for AXI-Stream the `TVALID TREADY TDATA TLAST` group of each port — or one colour per **module** of a generated
page. A group's colour goes to its signals (trace, bus outline, name) and to its name; a signal with its own colour keeps
it.

```json
"group":  { "aw": ["AWVALID", "AWREADY", "AWADDR"], "w": ["WVALID", "WREADY", "WDATA", "WSTRB"], "b": ["BVALID", "BREADY", "BRESP"],
            "ar": ["ARVALID", "ARREADY", "ARADDR"], "r": ["RVALID", "RREADY", "RDATA", "RRESP"] },
"config": { "groupColors": { "aw": "#339af0", "w": "#37b24d", "b": "#f59f00", "ar": "#ae3ec9", "r": "#1098ad" } }
```

![AXI-Lite: one colour per channel, a bookmark on every VALID & READY, arrows AW → W → B and AR → R with the latency](docs/img/axi.png)

`groupColors` keys are group names, full paths or `*` patterns, and the nearest matching group wins:
`{"s_axis": "#339af0", "m_axis": "#37b24d"}` for two stream ports, `{"tb.dut.u_rx": "#37b24d", "*fifo*": "#f59f00"}`
for modules of a generated config (the hierarchy picture below). One signal: `"color"` in its entry of a generated config,
`"color"` / `"stroke"` and `"fill"` in WaveJSON. Many signals by name: a rule in `tools/base.config.json`, e.g.
`{"match": ["*_valid", "*_ready"], "width": 1, "color": "#f59f00"}`, colours them in every config `mkconfig.py` writes.
Interactively: find the signals and **Paint** them (see *Fuzzy find*).

### Settings

Colours, sizes, fonts, line widths, sorting, folding and highlight are *settings*, merged in this order (later wins):

1. built-in defaults (`WaveFW.defaults`)
2. global: [`wavefw/wavefw.config.js`](wavefw/wavefw.config.js) loaded before `wavefw.js` (every key with its default),
   or `WaveFW.configure({…})` at run time; for a generated page, the top-level `"config"` of the config file
3. the diagram's `"config"` object in the WaveJSON (a view's `"config"`)
4. the element: `data-config='{…}'`, `data-sort`, `data-theme`, `data-colors`, …, or the constructor options

| Key | Default | Meaning |
|---|---|---|
| `theme`, `colors` | auto, `{}` | `light`, `white`, `dark`; colour tokens (see *Themes*) |
| `rowHeight`, `groupHeight`, `spaceHeight`, `headerHeight` | 26, 22, 14, 24 | row heights, px |
| `nameWidth`, `fontSize`, `labelSize` | 200, 11.5, 11 | name column, name text, bus labels, px |
| `fontMono`, `fontBody` | IBM Plex | CSS font-family lists |
| `traceWidth`, `busWidth` | 1.4, 1.2 | line widths, px |
| `sort`, `sortIgnore` | `none`, `[]` | `none \| asc \| desc`; name prefixes skipped when sorting (`["i_", "o_"]`) |
| `sortButton`, `hint` | true, true | show the Sort controls / the help line |
| `style` | `auto` | edges: `wavedrom` (slanted), `questa` (vertical, narrow bus crossings), `square`; `auto` slants wave strings and draws exact `tv` transitions vertically |
| `radix` | `auto` | bus values from `tv`: `auto` (≤ 6 bits decimal, else hex) `hex dec signed bin oct ascii` |
| `fold` | none | groups folded at start: `true`, a nesting depth (`2`), or group paths |
| `groupOrder` | `file` | inside a group: `last` = signals first, then sub-modules; `first`; `file` |
| `moduleShading` | true | neighbouring modules alternate between two backgrounds; module rows bold |
| `maxHeight` | none | e.g. `"80vh"`: the rows scroll inside the viewer (any number of rows) |
| `groupColors` | none | one colour per group: `{"aw": "#339af0", "tb.dut.u_rx": "#37b24d"}` (names, paths, `*` patterns) |
| `highlight`, `dim` | none, 0.3 | instances in front at start (paths, names, `*` patterns) and the opacity of the rest |
| `findHighlight`, `findOpen` | true, true | starting state of the find options |
| `arrowLabels`, `laneHeight` | `lane`, 16 | arrow labels in a lane of their own between the signals, or `overlay` |

### Themes

Three themes — `light` (warm paper), `white` (black traces, for print and slides) and `dark` — chosen by
`prefers-color-scheme` or set with `<html data-theme="white">`, `WaveFW.setTheme('dark')`, the page's theme button, or
`"config": {"theme": …}`. Every colour is a CSS custom property: `WaveFW.setColors({trace: '#c00', bus: 'navy'})` for all
waves, `data-colors` / `"config": {"colors": …}` for one wave, `"color"` / `"fill"` for one signal. Details:
[`docs/index.html` § Themes](docs/index.html#themes). The pictures in this README are dark; the same APB view in `light`:

![The APB example in the light theme](docs/img/light.png)

### Static SVG for documents

A view with `"render": "svg"` (or `data-mode="svg"`, `<script type="WaveDrom">`, `WaveSVG.toString(model)` for a file)
is drawn as an inline SVG in the WaveDrom look, with the same bookmarks and arrows and a legend of the bookmark texts.
It follows the page theme, or paints its own background when it has one.

![The APB write as a static SVG with its bookmark legend](docs/img/svg.png)

### Large dumps

`test_stream_video.vcd` (24 MB, 3520 signals in 214 scopes, 4.9 M value changes): the config in 5 s, a page with every
changing signal (1526 signals, all 9 scope levels) in 25 s and 6.3 MB; it opens in 2 s and redraws in 4 ms. The viewer's
canvas only covers the visible rows, so any number of rows scrolls smoothly. Above `select.budget` value changes
(6 M) `mkconfig.py` hides the deepest levels first and says which depth it kept.

## The viewer

![The viewer bar with its groups](docs/img/bar.png)

The bar has a title line (title, short messages, cursor and view span) and the tools in groups: **cursor** (a time and
its unit, **Set**; a span, **Show** = that window around the cursor), **view** (− + Fit), **find** (field, count, ‹ ›,
Highlight / Open, colour + Paint, Copy), **list** (Sort and the ignored prefixes, Expand / Collapse, clear highlight),
**edges** (◀ edge kind ▶, + Mark) and **go to** (marker jumps). Keys work once the waves have the focus (a click on the
waves or on a name):

| Key | Action | Key | Action |
|---|---|---|---|
| wheel, `+ − 0` | zoom, fit | shift+wheel, drag, `← →` | pan |
| click | cursor + select the signal | `↑ ↓` | select the previous / next signal |
| `c` | window of the current span at the cursor | `[ ]`, `e` | previous / next edge, edge kind |
| `/`, `n N` | find, next / previous match | `m` | bookmark at the cursor |
| `s` | sort off → A→Z → Z→A | ctrl+C | copy the selected / found / highlighted paths |
| ○ or ctrl+click a name | highlight the signal or instance | Esc | reset: no search, highlight or selection |

**Hierarchy and module shading.** With `"hierarchy": true` (generated configs) every scope is a group: module rows are
bold on a darker band, the signals of neighbouring modules alternate between two backgrounds, a click on a module folds
it, **Expand** / **Collapse** open or fold all. Hover a name for its full path. With `groupColors` each module has its
own colour (here `u_master`, `u_slave`, `u_regfile`; the clocks keep the green of a `*clk` rule).

![The generated AXI-Lite page: u_master folded, u_slave and u_regfile open, one colour per module](docs/img/hierarchy.png)

**Highlight.** The ○ mark in front of a name (or ctrl+click) puts that signal or whole instance in front in its own
colour; the rest is dimmed but stays visible. Several instances at once; **Highlight: N ✕** or Esc clears it.
`"highlight": ["tb.dut.u_tx"]` in `"config"` starts a page that way.

![Two instances highlighted in two colours](docs/img/highlight.png)

**Fuzzy find.** The find field (`/`) matches the typed letters in order anywhere in a name, as fzf does: `awvd` finds
`AWVALID`. A word with a `.` runs over the full path (`dev.fifo`), words separated by spaces must all match. Matched
letters are underlined; Enter, ‹ › or `n N` step through the matches. **Highlight** dims the rest, **Open** folds every
module without a match, **Paint** colours the found signals (kept in the browser), **Copy** copies their paths.

![Fuzzy find "awvd" with Highlight and Open](docs/img/find.png)

**Edges and the cursor fields.** Select a signal (click its name or its row), then ◀ ▶ (`[ ]`) jump to its previous /
next edge of the kind chosen between them (any, rising, falling; every value change on a bus). The cursor field takes a
time (`1.2us` wins over the unit list) and **Set** moves the cursor there; the span field and **Show** give a window of
that width around the cursor. Cycle diagrams count in cycles.

![Cursor at 1.2 µs, a 100 ns window around it](docs/img/cursor.png)

**Bookmarks and arrows.** **+ Mark** (`m`) puts a numbered bookmark on the selected signal at the cursor, snapped to an
edge. Below the waves each bookmark has a time, a signal, a colour and a text; drag a circle to move it, shift+drag from
one circle to another to draw an arrow (shape `- ~ -~ ~- -| |- -|-`, head, line, colour, label). Labels get a thin
lane of their own between the signals. Bookmarks are kept in the browser; **JSON** gives the `"bookmarks"` and
`"arrows"` lists to paste into a config, so the built page (and its static SVG) carries them. The AXI-Lite picture
above shows arrows between handshakes with the latency as the label.

![The bookmark and arrow lists under the waves](docs/img/bookmarks.png)

**Sorting.** **Sort** (`s`) cycles off → A→Z → Z→A; the prefixes in the field next to it (`i_,o_`) are skipped when
names are compared and drawn dimmed. Groups move as a block and are sorted inside.

![Sort A→Z with i_ and o_ ignored](docs/img/sorting.png)

**Copying names and Esc.** Names selected with the mouse copy as full paths, one per line. With no search running,
ctrl+C on the waves copies the selected signal (or the highlighted ones). Esc anywhere in the viewer clears the search,
the highlight and the selection and leaves the view as it is: opened modules, scroll position, time window.

## Examples

Each directory in [`examples/`](examples) has a testbench, a hand-written config and a README; `make example EX=<ex>`
builds its VCD, FST and two pages: `<ex>.html` from the config and `<ex>_all.html` from a config that `mkconfig.py` makes
from the dump (the whole hierarchy).

| Example | What it shows | Picture |
|---|---|---|
| [`apb`](examples/apb) | APB3 write, read with two wait states, `PSLVERR` on an unmapped address; enum `phase`; a static-SVG view | [hero](docs/img/hero.png), [light](docs/img/light.png), [svg](docs/img/svg.png) |
| [`axi_lite`](examples/axi_lite) | AXI4-Lite write (`AWREADY` a cycle late) and read; channel groups with a colour each, highlight from the config, latency arrows; three module levels in `_all` | [axi](docs/img/axi.png), [hierarchy](docs/img/hierarchy.png) |
| [`fsm`](examples/fsm) | UART receiver with `typedef enum` states in a package: names from the FST and, for the VCD, from the sources; questa edges | [fsm](docs/img/fsm.png) |
| [`demo`](examples/demo) | the Manchester transmitter behind [`docs/index.html`](docs/index.html) (`make demo`) | [cursor](docs/img/cursor.png) |

## Tools

All tools are `python3 -I tools/<tool>.py --help`; the Makefile calls them for you.

| Tool | Does | Main options |
|---|---|---|
| `mkconfig.py` | dump → editable config with every signal | `DUMP`, `--out`, `--update`, `--force`, `--base`, `--depth`, `--sv FILES` |
| `mkhtml.py` | config (every view) or WaveJSON files → one self-contained page | `--config`, `--view`, `--waves`, `--render`, `--out` |
| `vcd2wavedrom.py` | one window of a dump → WaveJSON | `--config` + `--view`, or `--waves --scope --signals --clock/--exact --from --to --marker --group --enum` |
| `embed.py` | WaveJSON → `data.js` for `file://` pages, or into an HTML placeholder | `--var NAME key=file.json`, `--html --placeholder` |
| `dumpscan.py`, `wavejson.py` | the built-in dump reader (VCD text, FST via `fst2vcd -e`) and the readable JSON writer | modules |

`vcd2wavedrom.py` has two readers with byte-identical output: the built-in one (default) and wavepeek
(`--reader wavepeek`, `READER=wavepeek`), which also takes any wavepeek `--on` expression as a marker.

## Formats

### WaveDrom subset

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
characters are treated as `.`. [`tests/conformance.html`](tests/conformance.html) draws every case next to stock
WaveDrom 3.5.0.

### Extensions (stock WaveDrom ignores them)

| Key | Meaning |
|---|---|
| `time: {t0, cycle, t1?, skip?}` | cycle *c* starts at `t0 + c·cycle` ps, so the axis shows real time; `skip: [[k, n]]` = the `\|` cell at index *k* stands for *n* cycles |
| `signal[i].tv: [[t, v], …]` | exact transitions in model time (ps when `time` is set). 1-bit: `0 1 x z`; bus: hex. Takes precedence over `wave` |
| `signal[i].width / enum / radix / style / color / fill` | bus width, value labels (`{"0": "IDLE"}`), radix, edge style, colours |
| `signal[i].path`, `same` | full hierarchical path (the name's tooltip); `"same": "tb.clk"` = the `tv` of the signal with that `path` (one net seen at several levels is stored once) |
| `config: {…}` | the settings of this diagram (see *Settings*) |
| `bookmarks: [{n, t, signal, text, color}]` | numbered events on signal rows (`signal` = full path, `group.name` without one; `t` in model units or `"85.12us"`) |
| `arrows: [{from, to, shape, head, line, color, label}]` | arrows between bookmarks: shape `- ~ -~ ~- -\| \|- -\|-`, head `> <> <` or `""`, line `solid dashed dotted` |
| `markers: [{t \| cycle, label}]` | dashed markers; they become jump buttons when there are ≤ 6 and no `jumps` |
| `jumps: [{t \| cycle, span, label}]`, `cursor` | jump buttons and the initial cursor |

## Project layout

```
wavefw/                       what a page needs, nothing else
  wavefw.js / wavefw.css      framework (one <script> + one <link>)
  wavefw.config.js            global settings file (all keys, with defaults), loaded before wavefw.js
tools/                        what you run: python3 -I tools/<tool>.py
  mkconfig.py vcd2wavedrom.py mkhtml.py embed.py dumpscan.py wavejson.py
  base.config.json            base settings for generated configs (make config / make html WAVES=x.vcd)
examples/                     apb/ axi_lite/ fsm/ demo/: testbench, config, README
docs/                         what you look at
  index.html                  the reference page with live examples (opens from file://)
  demo_waves.js               its data (make demo), tracked
  img/                        the README screenshots (make shots)
  reference/template.html     the original visual reference (PSI5 datasheet)
tests/
  smoke.py                    behaviour checks in headless Chromium (make smoke)
  shots.py                    the screenshots (make shots)
  conformance.html            every feature next to stock WaveDrom 3.5.0 (vendor/, test-only)
work/                         your dumps and their configs: configs tracked, dumps and pages git-ignored
prompts/                      the roadmap as a series of prompts
Makefile                      make help lists the targets; build products go to BUILD (default /tmp/wavefw)
```

## Development

```sh
make demo examples html     # rebuild docs/demo_waves.js, the example pages, the demo page
make smoke                  # tests/smoke.py: every page in light and dark, ~200 behaviour checks, PNGs in BUILD/shots
make shots                  # tests/shots.py: docs/img/*.png, dark theme (after make examples; ~10 s, same bytes every run)
```

`make smoke` is the gate for every change: it opens `docs/index.html`, `tests/conformance.html` and every built page
that exists (demo, FST demo, examples, `work/*.html`), fails on console errors, and runs interaction checks per page
(cursor, zoom, sort, settings layers, highlight, find, bookmarks and arrows, FSM names). `make shots` checks looks rather
than behaviour: fixed viewport, fixed clicks, one element per image. Both need Python playwright (a user-site install,
so they run without `-I`). Environment used: Verilator 5.046, wavepeek 3.1.0, GTKWave fst2vcd.

The two dump readers, measured on this machine (16 CPUs), output byte-identical:

| Job | builtin | wavepeek |
|---|---|---|
| `test_stream_video.vcd` (24 MB), every changing signal: 1526 signals, 4.8 M changes | 25 s, 1.5 GB | 45 s, 2.9 GB |
| `mkconfig.py test_stream_video.vcd` (3520 signals listed, changes counted) | 5.4 s | 12 s |
| `dump.vcd` (14 MB), view `full` (15 signals, exact, markers) | 2.0 s | 7.0 s |
| demo (25 signals) | 0.15 s | 0.19 s |

## Roadmap

The next stages are prompts in [`prompts/`](prompts/00-roadmap.md); next is a SystemVerilog Assertion engine: parse
`property` / `sequence` / `assert property`, bind an assertion to an instance of the waveform, evaluate it over the dump,
and draw the attempts, steps and failures next to the signals, with statistics.
