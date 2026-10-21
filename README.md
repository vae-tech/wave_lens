# wavefw — WaveDrom JSON → interactive waves

wavefw draws **WaveDrom JSON** in two ways from one model: as an interactive canvas viewer (zoom, cursor, fold, find,
bookmarks) and as a static WaveDrom-style SVG for documents. A few Python tools turn a simulator dump (VCD or FST) into
one self-contained HTML page that you can mail or archive. One JavaScript file, one stylesheet, no build step, no
dependencies: the pages open from `file://`. SystemVerilog assertions bound to the waves are checked over the dump and
drawn next to the signals.

![The APB example in the dark theme: viewer bar, waves, numbered bookmarks and arrow labels in their own lanes](docs/img/hero.png)

## Quick start

```sh
make examples                   # needs Verilator: APB, AXI-Lite and FSM pages in out/examples/<ex>/<ex>.html
make html WAVES=work/my.vcd     # your dump -> work/my.config.json (every signal, editable) + work/my.html
make html WAVES=work/my.fst SVA="checks/*.sv" BIND="a_req_ack@tb.dut"   # with assertions, evaluated and drawn
```

Open the `.html` in a browser from 2023 on (Chrome / Edge 111, Firefox 113, Safari 16.2: the pages use `color-mix()`,
`overflow: clip` and `WeakRef`). `make html` reads the dump with the built-in reader (Python 3.8+, standard library
only). Optional: GTKWave's `fst2vcd` to read FST dumps, [wavepeek](https://github.com/kleverhq/wavepeek) as a second
reader, cargo for the assertion engine (`make sva-build`), Python playwright for the tests and the screenshots. `make`
alone lists the targets; build products go to `BUILD` (default `out/` in the repository, git-ignored).

**Prerequisites**, by what you do (details in [DEVELOPMENT](docs/DEVELOPMENT.md)): pages and tools — python3 ≥ 3.8
(standard library) and a browser; the examples — Verilator ≥ 5 (`make examples`), GTKWave's `fst2vcd` for FST dumps,
optionally wavepeek; the engine — cargo ≥ 1.82 and `rustup target add wasm32-unknown-unknown` (`make sva-build`), musl
for `make dist-linux`, mingw-w64 for `make dist-windows`; the tests — `pip install playwright` and `python3 -m
playwright install chromium` (`make smoke`, `make check`), `fonts-ibm-plex` for `make shots`; the SystemVerilog style
— verible (`make fmt`) and Verilator (`make lint`).

**Without compiling anything.** A clone works as it is: the pages and `wavefw/` need no build, the tools are Python
(standard library), the assertion engine is committed twice — `wavefw/sva.wasm.js` for the pages and the `sva` CLI for
the tools, `bin/linux-x86_64/sva` (static, any distribution); `tools/*.py` find it by themselves. On Windows the pages
and the tools work as they are; the CLI is built there by `make dist-windows` (needs mingw-w64, see
[DEVELOPMENT](docs/DEVELOPMENT.md)), without it the assertions are evaluated in the page. Without `make`:

```sh
python3 tools/mkconfig.py work/my.vcd --out work/my.config.json   # Windows: py tools\mkconfig.py work\my.vcd --out work\my.config.json
python3 tools/mkhtml.py --config work/my.config.json --out work/my.html --sva checks/my.sva --bind "a_req_ack@tb.dut"
```

## What it does

- **Your own page**: a `<script type="application/wavedrom">` block becomes a viewer, `<script type="WaveDrom">` a
  static SVG; `data-*` attributes set the window, the mode and any setting
  ([USAGE § WaveDrom JSON in your own page](docs/USAGE.md#wavedrom-json-in-your-own-page)).
- **A dump to a page in one command**: `mkconfig.py` lists every signal of the dump in an editable config (show,
  radix, colour, style, enum, alias per signal; views with their own signals, window, bookmarks and arrows), `mkhtml.py`
  builds the page; run `make config` again after the dump changed and your edits stay
  ([USAGE § The generated config](docs/USAGE.md#the-generated-config-and-what-you-edit-in-it)).
- **FSM state names** from the FST's enum tables, or from `typedef enum` in the sources for a VCD; **colours** per
  signal, per protocol channel and per module; **settings** in three layers (global file, config, element);
  three **themes** ([USAGE § Use cases](docs/USAGE.md#use-cases)).
- **Large dumps**: 3520 signals in 214 scopes, 4.9 M value changes — the config in 2.7 s, a page with the 1526 changing
  signals in 25 s, it opens in 2 s and redraws in 4 ms; scopes are foldable groups with module shading
  ([USAGE § Large dumps](docs/USAGE.md#large-dumps)).
- **A dump in the browser**: `wavefw/viewer.html` (or **Open…** in any viewer) reads a VCD dropped on it, ⟳ reads it
  again after a new simulation with the view kept ([USAGE § Use cases](docs/USAGE.md#a-dump-straight-in-the-browser)).
- **The viewer**: cursor and span fields, a second cursor (Δ in time and clock cycles), zoom and pan by wheel and keys,
  find (fuzzy, whole name, regular expression) with highlight / open / paint, edge, value and X / Z search, highlight
  of instances, selection of runs and boxes, bookmarks and arrows that go back into the config, sorting with ignored
  prefixes, a tooltip with the keys on every control and a **?** box of all the keys, a measured range (ctrl+drag, edges
  snapped) and the right button's menu (zoom, bookmarks, the picture as PNG / SVG and WaveDrom — with the idle stretches
  of a long range cut out as breaks if you like —, a signal's colour, radix —
  float and fixed point too —, analog step plot); packed structs as a row of fields (an FST's struct scopes, or
  `mkconfig --sv`); **Save / Load…** puts all of it (with the assertions and ƒ rows) in a file and back
  ([USAGE § The viewer](docs/USAGE.md#the-viewer)).
- **Bus transactions**: the ports of AXI4 / AXI4-Lite / AXI3, AXI4-Stream, APB, AHB, Avalon-MM / ST, Wishbone and OBI
  found by their names and drawn as transfers (address to response, bursts, packets, errors) with a row per channel
  where every beat shows its stall ([USAGE § The viewer](docs/USAGE.md#the-viewer)).

![AXI-Lite: the bus port found by its names, the first write selected](docs/img/buses.png)

![A measured range and the right button's menu](docs/img/range.png)
- **Assertions (SVA)**: bind an assertion to an instance of the waveform and it is evaluated over the dump (in the
  page as WebAssembly, or when the page is built by the Rust CLI); every attempt is a bar under that instance, every
  sequence step a numbered circle — on its own row and, for the selected attempt, on the signals it reads, with
  start and end flags (`▶ start`, `✓ pass` / `✕ fail` / `… not ended`) — failures red with their reason; totals, a table, a failure list, and reports as
  Markdown, JSON, JUnit XML or HTML for CI ([USAGE § Assertions](docs/USAGE.md#assertions-sva)). **Why** takes the
  selected attempt apart (every operand, cycle by cycle, the one that failed in red); **expressions** of the signals
  (`PSEL && !PREADY`, `@(posedge clk) $rose(req)`) are searched (next / previous time true) and drawn as rows.

![An APB check bound to the testbench: the failing attempt selected, its steps, arrows and the signals it read](docs/img/sva.png)

A WaveDrom diagram in your own page:

```html
<link rel="stylesheet" href="wavefw/wavefw.css">
<script src="wavefw/wavefw.js"></script>

<script type="application/wavedrom">          <!-- interactive viewer -->
{ "signal": [ { "name": "clk", "wave": "p....." }, { "name": "d", "wave": "x.34.x", "data": ["A", "B"] } ] }
</script>
<script type="WaveDrom"> {signal: [{name: 'req', wave: '01..0'}]} </script>   <!-- static SVG -->
```

Assertions from the command line, for CI:

```sh
sva eval --waves x.fst --scope tb.dut --sva checks.sva --report report.md --junit report.xml   # exit 1 on a failure
make sva-eval WAVES=x.fst SVA="pkg.sv checks.sva" SCOPE=tb.dut ARGS="--junit report.xml"
```

![The generated AXI-Lite page: u_master folded, u_slave and u_regfile open, one colour per module](docs/img/hierarchy.png)

## Examples

[`apb`](examples/apb), [`axi_lite`](examples/axi_lite) and [`fsm`](examples/fsm) each have a testbench, a
hand-written config, assertions and a README; `make example EX=<ex>` (or `make examples`, all three) builds its VCD,
FST and two pages: `<ex>.html` from the config and `<ex>_all.html` from a config that `mkconfig.py` makes
from the dump (the whole hierarchy).

| Example | What it shows | Picture |
|---|---|---|
| [`apb`](examples/apb) | APB3 write, read with two wait states, `PSLVERR` on an unmapped address; enum `phase`; a static-SVG view | [hero](docs/img/hero.png), [light](docs/img/light.png), [svg](docs/img/svg.png), [range](docs/img/range.png), [cursors](docs/img/cursors.png), [why](docs/img/why.png) |
| [`axi_lite`](examples/axi_lite) | AXI4-Lite write (`AWREADY` a cycle late) and read; channel groups with a colour each, highlight from the config, latency arrows; three module levels in `_all` | [axi](docs/img/axi.png), [hierarchy](docs/img/hierarchy.png), [buses](docs/img/buses.png) |
| [`fsm`](examples/fsm) | UART receiver with `typedef enum` states in a package: names from the FST and, for the VCD, from the sources; questa edges | [fsm](docs/img/fsm.png), [struct](docs/img/struct.png) |
| [`demo`](examples/demo) | the Manchester transmitter behind [`docs/index.html`](docs/index.html) (`make demo`; a testbench and a config, no README) | [cursor](docs/img/cursor.png) |
| [`test_video`](examples/test_video) | a real design: the CoaXPress device's bound checkers (12 modules, 26 assertions) over its stream-video dump (the dump is not in git) | — |

Every example has its assertions (`*.sva`) with one deliberately wrong, so a failure trace shows.

## Documentation

| Document | What is in it |
|---|---|
| [`docs/USAGE.md`](docs/USAGE.md) | the user's guide: use cases, the config, settings, themes, static SVG, assertions, the viewer and its keys, the tools, the formats |
| [`docs/index.html`](docs/index.html) | the reference with live examples (open from `file://`): every attribute, setting and API function |
| [`docs/sva/LANGUAGE.md`](docs/sva/LANGUAGE.md), [`ENGINE.md`](docs/sva/ENGINE.md), [`STACK.md`](docs/sva/STACK.md) | the SVA subset, the evaluator's semantics and results JSON, the technology choice |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | the project layout, build and test (`make check`), measurements, the roadmap |
| [`docs/SV_STYLE.md`](docs/SV_STYLE.md) | the SystemVerilog style of the project |
| [`docs/reviews/`](docs/reviews) | the reviews of the stages with their findings and the commits that closed them |
| [`prompts/`](prompts/00-roadmap.md) | the roadmap as a series of prompts |

## Development

```sh
make check                  # the gate: the engine's tests, the unit tests, every page, smoke with nothing skipped
make smoke ONLY=find        # one section of the browser checks (python3 tests/smoke.py --list)
make shots                  # the screenshots of docs/img (after make examples)
```

Layout, tools, measurements and conventions: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Versions

0.10 — [`CHANGELOG.md`](CHANGELOG.md) lists every version (two numbers; each a tagged merge into `main`, `v0.1` …
`v0.10`).

## License

MIT. The third-party checkers in `tests/sva/third_party/` and stock WaveDrom in `tests/vendor/`
keep their own licences.
