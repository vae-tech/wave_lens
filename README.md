# WaveLens — interactive waveforms in one HTML file

By [vae-tech](https://github.com/vae-tech) · MIT · [changes](CHANGELOG.md)

WaveLens opens a simulation dump (VCD or FST) or a [WaveDrom](https://wavedrom.com) diagram as an interactive wave
viewer, checks SystemVerilog assertions over it, and saves the lot as one self-contained HTML page that you can mail,
archive or attach to a review. The viewer is one JavaScript file and one stylesheet (the assertions and the bus
transactions are three plugin scripts more, inlined into a page): no build step, no server, the pages open from `file://`.

![The APB example in the dark theme: viewer bar, waves, numbered bookmarks and arrow labels in their own lanes](docs/img/hero.png)

- **A wave window in the browser**: zoom, two cursors, measured ranges, fuzzy find, the hierarchy, a Modules tree that
  keeps only the modules you pick, your groups and order, clock cycles, undo, bookmarks and arrows with notes.
- **SystemVerilog assertions** bound to instances, evaluated over the dump (in the page and by a CLI for CI), every
  attempt drawn on the waves, a failure taken apart step by step.
- **Bus transactions**: AXI, AXI-Stream, APB, AHB, Avalon, Wishbone and OBI ports found by their names and drawn as
  transfers; **two runs compared** signal by signal.
- **Pictures for documents**: PNG, SVG and WaveDrom out of any window, long idle stretches cut out, a static
  WaveDrom-style SVG next to the viewer.
- **VS Code over Remote-SSH or WSL**: a dump on the Linux host opens in a tab, nothing else installed there
  ([installing it](#the-vs-code-extension)).
- **Scripts and AI agents**: whatever the buttons do, a command does by name — from the console, `tools/viewedit.py`
  or an MCP server, live in an open page.

## Try it in a minute

Clone or download the repository; the commands run from its root.

1. **Nothing to install**: open [`wavelens/viewer.html`](wavelens/viewer.html) in a browser and drop a `.vcd` on it.
2. **A page to keep or send** (Python ≥ 3.8, standard library only):

   ```sh
   python3 tools/mkconfig.py work/my.vcd --out work/my.config.json   # every signal of the dump, a file you can edit
   python3 tools/mkhtml.py --config work/my.config.json --out work/my.html
   ```

   Open `work/my.html`: it is the whole viewer and the waves in one file. With `make`: `make html WAVES=work/my.vcd`.
3. **The examples** (Verilator ≥ 5): `make examples`, then open `out/examples/apb/apb.html` — an APB, an AXI-Lite and
   a UART FSM testbench with their assertions, one of them deliberately wrong.

A WaveDrom diagram in your own page needs the two files of `wavelens/` ([the WaveDrom guide](docs/guides/wavedrom.html)):

```html
<link rel="stylesheet" href="wavelens/wavelens.css">
<script src="wavelens/wavelens.js"></script>
<script type="application/wavedrom">
{ "signal": [ { "name": "clk", "wave": "p....." }, { "name": "d", "wave": "x.34.x", "data": ["A", "B"] } ] }
</script>
```

## The VS Code extension

For dumps on a Linux machine you reach from VS Code over **Remote-SSH** or **WSL** (VS Code ≥ 1.80 on your side, a
Linux x86-64 host). The extension is installed on the host; nothing else is needed there.

1. Build the package in a clone, on the host or anywhere (Python only, no node / npm):

   ```sh
   make vsix                       # -> out/wavelens-<version>.vsix; without make: python3 -I tools/mkvsix.py
   ```

2. Connect VS Code to the host (*Remote-SSH: Connect to Host…* or *WSL: Connect to WSL*) and open the folder of
   your dumps.
3. In a terminal of that **remote** window (where the `.vsix` is, or copy it there):

   ```sh
   code --install-extension out/wavelens-*.vsix --force   # --force: over an older version
   ```

   or Extensions → `…` → *Install from VSIX…* while connected. Then *Developer: Reload Window*.
4. Check: the Extensions view lists **WaveLens** under the host's name (*SSH: …* / *WSL: …*), not under *Local*.
   A right click on a `.vcd` / `.fst` in the Explorer → **Open in WaveLens**.

The extension of before the rename goes with `code --uninstall-extension wavefw.wavefw`. Settings, what the tab does
and an agent live in the tab: [the VS Code guide](docs/guides/vscode.html).

## Requirements

| To | You need |
|---|---|
| open a page, or a VCD in `wavelens/viewer.html` | a browser from 2023 on (Chrome / Edge 111, Firefox 113, Safari 16.2) |
| make pages from dumps (`tools/*.py`) | Python ≥ 3.8, standard library only |
| read an FST with the tools | GTKWave's `fst2vcd`, or the `sva` CLI committed in `bin/linux-x86_64/` (static, any Linux x86-64; the tools find it) |
| check assertions from the tools or in CI (`mkhtml.py --sva`, `mkconfig.py --sva`, `sva eval`) | the `sva` CLI: `bin/linux-x86_64/sva`; on Windows `make dist-windows` builds it (mingw-w64). Without it a page still evaluates its assertions in the browser |
| build the examples | Make and Verilator ≥ 5 |
| the VS Code extension | VS Code ≥ 1.80; the package (`make vsix`) is for a Linux x86-64 host of Remote-SSH / WSL |
| change the code | [DEVELOPMENT.md](docs/DEVELOPMENT.md): Rust for the assertion engine, Playwright for the tests |

## Documentation

**Guides** with pictures (HTML: open [`docs/guides/index.html`](docs/guides/index.html) from a clone):

| Guide | |
|---|---|
| [From a dump to a page](docs/guides/pages.html) | `make html`, the generated config and what to edit in it, views, FSM names, structs, themes |
| [The viewer](docs/guides/viewer.html) | the bar, zoom, cursors, edges, ranges, find, hierarchy, groups, cycles, bookmarks, undo, save |
| [Modules](docs/guides/modules.html) | the tree of the modules: go to one, keep Only the ones you pick |
| [Compare two runs](docs/guides/compare.html) | a second dump over the first: where they differ, step by step |
| [Gaps](docs/guides/gaps.html) | the idle stretches cut out of a picture or WaveDrom |
| [Assertions (SVA)](docs/guides/sva.html) | bind, read the attempts, why one failed, edit and run again, reports for CI |
| [Bus transactions](docs/guides/buses.html) | the ports found by their names, drawn as transfers |
| [WaveDrom](docs/guides/wavedrom.html) | diagrams in your own page, the supported subset and the extensions |
| [VS Code](docs/guides/vscode.html) | the extension over Remote-SSH or WSL |
| [Commands and scripts](docs/guides/commands.html) | the viewer's commands from the console, a script or a live page |
| [AI agents (MCP)](docs/guides/mcp.html) | the MCP server: questions about a dump, a page marked up for a person |

**Reference**: [`docs/USAGE.md`](docs/USAGE.md) has every setting, key, option and format;
[`docs/index.html`](docs/index.html) the attributes, settings and API with live examples;
[`docs/sva/LANGUAGE.md`](docs/sva/LANGUAGE.md) and [`ENGINE.md`](docs/sva/ENGINE.md) the SVA subset and the evaluator;
[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) the layout, the build and the tests.

## Examples

[`apb`](examples/apb), [`axi_lite`](examples/axi_lite) and [`fsm`](examples/fsm) each have a testbench, a
hand-written config, assertions (one deliberately wrong, so a failure trace shows) and a README; `make example EX=<ex>`
builds its VCD, FST and two pages: `<ex>.html` from the config and `<ex>_all.html` from the whole hierarchy.
[`demo`](examples/demo) is the Manchester transmitter behind [`docs/index.html`](docs/index.html) (`make demo`).
[`test_video`](examples/test_video) binds the checkers of a CoaXPress device IP
([CoaxPress-RTL-core](https://github.com/vae-tech/CoaxPress-RTL-core), its PyUVM test `test_stream_video`) to its
stream-video dump, which is not in git: with your `test_stream_video.fst` next to the config,
`make html WAVES=examples/test_video/test_stream_video.fst`.

## Building

`make` alone lists the targets; build products go to `BUILD` (default `out/`, git-ignored).

```sh
make wavelens        # wavelens/wavelens.js from wavelens/src/*.js (after editing them)
make sva-build       # the SVA engine: the native CLI and wavelens/sva.wasm.js
make vsix            # the VS Code extension: out/wavelens-<version>.vsix (no node / npm needed)
make check           # the gate before a commit: the engine's tests, the unit tests, every page in a browser
```

## License

MIT. The third-party checkers in `tests/sva/third_party/` and stock WaveDrom in `tests/vendor/`
keep their own licences.
