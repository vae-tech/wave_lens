# Developing WaveLens

How the project is laid out, built and tested, what was measured, and where the roadmap and the reviews live. Using
WaveLens is [USAGE.md](USAGE.md).

## Project layout

```
wavelens/                     what a page needs, nothing else
  wavelens.js / wavelens.css  framework (one <script> + one <link>); wavelens.js is made by make wavelens from src/
  src/                        model.js (settings, sorting, find, time, values, the parser), vcd.js (a VCD read in the
                              page), paint.js (the two painters
                              and what they draw), view.js (WaveView and its parts Bar, Names, Notes), edit.js (the
                              viewer's commands view.run, your groups and markers, undo, Save page, the live link),
                              diff.js (a second dump compared), modules.js (the Modules panel and Only), fsm.js (the
                              state machines panel and its layer), svg.js
                              (WaveSVG), boot.js (themes, configure, upgrade, exports): one scope, in this order
  wavelens.config.js          global settings file (all keys, with defaults), loaded before wavelens.js
  sva.js, sva.wasm.js         assertions in the page: the panel, binding, evaluation; the engine (generated, make sva-build)
  bus.js                      bus transactions: ports found by their names, decoders (AXI, AXI-Stream, APB, AHB, Avalon, Wishbone, OBI), rows
vscode/                       the VS Code extension (a workspace extension: Remote-SSH / WSL host): extension.js (the
                              custom editor of .vcd / .fst, FST -> VCD by the bundled sva (and Convert to FST: sva
                              fst), the store, dialogs, the
                              live relay), media/host.js (the tab's half, before wavelens.js: localStorage, downloads,
                              pickers, clipboard, keys, theme, live link to the host), svtypes.js (the twin of
                              svtypes.py verilator: the command Make the types with Verilator; tests/unit compares
                              the two), test/e2e.js (in a real VS Code)
tools/                        what you run: python3 -I tools/<tool>.py
  mkconfig.py vcd2wavedrom.py mkhtml.py embed.py dumpscan.py wavejson.py svabuild.py
  svtypes.py                  the design's types by path (Questa's describe read, Verilator --json-only walked); its
                              twin in the page is wavelens/src/vcd.js svTypes
  questa/wavelens_types.tcl   in vsim: describe of every signal and the module of every instance -> <dump>.types.json
  mkvsix.py                   vscode/ + wavelens/ + the static sva -> one .vsix (a zip: no node, no npm)
  wavemcp.py                  the tools as an MCP server for AI agents (stdio; USAGE § AI agents); the live link to a page
  viewedit.py                 the viewer's commands on a page's edits or a saved state (USAGE § Commands and edits)
  base.config.json            base settings for generated configs (make config / make html WAVES=x.vcd)
examples/                     apb/ axi_lite/ fsm/ demo/: testbench, config, README; *.sva: assertions for each;
                              test_video/: the CoaXPress checkers (cxp_sva.sv) and a demo of the operators with
                              deliberate failures (cxp_sva_demo.sv) over a real dump; the dump and page are not in
                              git: put your test_stream_video.fst there, make html
                              WAVES=examples/test_video/test_stream_video.fst (its config, ~20 s, a 27 MB page)
docs/                         what you look at
  index.html                  the reference page with live examples (opens from file://)
  USAGE.md, DEVELOPMENT.md    the user's guide; this file
  guides/                     the guides as HTML with pictures (index.html first; guide.css, guide.js; img/ by make
                              guide-shots)
  SV_STYLE.md                 the SystemVerilog style of the project
  demo_waves.js, apb_waves.js its data (make demo), tracked
  img/                        the README screenshots (make shots)
  sva/                        the SVA engine: STACK.md (technology), LANGUAGE.md (the subset), ENGINE.md (semantics,
                              results JSON, performance), the JSON schemas
  reviews/                    the reviews of the stages with their findings (on dev only, not in the public branch)
  reference/template.html     the original visual reference (PSI5 datasheet)
tests/
  unit/                       the Python unit tests of the tools (make unit: unittest, standard library); vcd/: small VCDs
                              of what simulators write (real, string, event, escaped names, VHDL values, comments …)
  smoke.py                    behaviour checks in headless Chromium (make smoke)
  vscode_e2e.py               the VS Code extension in a real VS Code (make vscode-e2e; WSL: the Windows one)
  mcp_bench.py                what the MCP server saves an agent: tasks with known answers, agents with and without it
  sva/                        the SVA corpus: *.sv with every construct, err_*.sv with annotated errors, golden/;
                              third_party/: AXI4-Lite, APB, AHB checkers of others (licenses, units.json)
  shots.py                    the screenshots (make shots)
  guide_shots.py              the pictures of docs/guides (make guide-shots; writes the gaps guide's dump into BUILD/guides)
  conformance.html            every feature next to stock WaveDrom 3.5.0 (vendor/, test-only)
work/                         your dumps and their configs: configs tracked, dumps and pages git-ignored
sva/                          the SVA engine (Rust: core, native CLI, WebAssembly); the CLI's sva vcd (cli/src/vcd.rs:
                              a dump as VCD text) and sva fst (cli/src/fst.rs: a VCD as an FST, as vcd2fst writes it)
prompts/                      the roadmap as a series of prompts (on main only)
bin/                          the prebuilt sva CLI, committed: linux-x86_64/sva (static); windows-x86_64/sva.exe by make dist-windows
out/                          build products (make's BUILD, git-ignored): cargo target, example dumps and pages, shots
Makefile                      make help lists the targets; build products go to BUILD (default out/)
```

## Build and test

What each part needs:

| To | You need |
|---|---|
| open the pages | a browser |
| the tools | python3 ≥ 3.8 (standard library only) |
| the examples | Verilator ≥ 5 (`make examples`) |
| the assertion engine | cargo ≥ 1.82 and `rustup target add wasm32-unknown-unknown` (`make sva-build`); musl for `make dist-linux`, mingw-w64 for `make dist-windows` |
| the tests and the pictures | `pip install playwright`, `python3 -m playwright install chromium` (`make smoke`, `make check`); `fonts-ibm-plex` (or the network) for `make shots`, `make guide-shots`; GTKWave's `vcd2fst` and `fst2vcd` (`apt install gtkwave`) for `make check`: `sva fst` is compared with them (`tests/unit/test_svafst.py`, `sva/cli/tests/cli.rs`) |
| the SystemVerilog style | verible (`make fmt`) and Verilator (`make lint`) |

```sh
make check                  # the gate before a commit: wavelens.js current and its sources ≤ 160 columns, the committed sva.wasm.js the build of sva/, every page smoke needs, sva-test and unit (WAVELENS_STRICT: a test lacking what the gate builds fails, the engine's goldens over the examples too), sva-verify, mcp-bench, smoke STRICT=1, shots-check
make unit                   # tests/unit: the tools on small VCDs of what simulators write (~20 s, standard library)
make unit-bless             # rewrite tests/unit/golden (the bytes wavejson.py and vcd2wavedrom.py write for the fixtures) after a meant change of them: read the diff
make mcp-bench              # tools/wavemcp.py on the benchmark tasks by a script (answers checked); AGENT=claude|codex: agents
make wavelens               # wavelens/wavelens.js from wavelens/src/*.js (after editing them; make html / example do it too; lines ≤ 160 columns)
make demo examples html     # rebuild docs/demo_waves.js, the example pages, the demo page
make smoke                  # tests/smoke.py: every page in light and dark, checks by section (--list), PNGs in BUILD/shots
make smoke ONLY=find,sva_bind   # some sections (python3 tests/smoke.py --list); STRICT=1: a skip fails
make shots                  # tests/shots.py: docs/img/*.png, dark theme, and tests/visual/*.png (--set visual: white, 420 px, an FSM's details, a scale of 2) (after make examples; ~20 s, see below)
make shots-check            # both into BUILD/img and BUILD/visual, compared with the committed ones by tests/pngdiff.py: a picture that changed (more than 48 pixels by more than 32 of 255 from the pixel there and the 8 around it: text a pixel off is the same) or one made and not committed fails, its difference in BUILD/*/diff
make guide-shots            # tests/guide_shots.py: docs/guides/img/*.png (after make examples; ONLY=gaps,sva: those guides)
make vsix                   # tools/mkvsix.py: BUILD/wavelens.vsix, its copy wavelens-<version>.vsix (the extension, the viewer, the static sva)
make vscode-e2e             # tests/vscode_e2e.py: the extension in a real VS Code (INSTALLED: python3 tests/vscode_e2e.py --installed)
make sva-build              # the SVA engine (needs cargo + the wasm32 target): the sva CLI, wavelens/sva.wasm.js
make dist                   # the CLI: bin/linux-x86_64/sva (musl, static, committed) + bin/windows-x86_64/sva.exe (mingw-w64)
make sva-test               # the SVA engine: unit tests, the corpus tests/sva (third_party too), the JSON schema, the CLI
make sva-bless              # rewrite tests/sva/golden/*.txt after a reviewed change of the parser output
make sva-examples sva-spike # sva parse + sva eval of examples/*/*.sva; the WebAssembly build in a page (wasm32 target)
make sva-verify             # the examples' checkers in Verilator --assert against sva eval (sva/ENGINE.md § Tests)
make sva-eval WAVES=work/x.fst SVA="pkg.sv checks.sva" SCOPE=tb.dut OUT=results.json   # assertions over any dump
make fst WAVES=work/x.vcd     # sva fst: work/x.fst beside it, the FSM states of work/x.types.json in it
make fmt lint               # verible-verilog-format (docs/SV_STYLE.md), verilator --lint-only -Wall on the testbenches
make clean                  # the build products under BUILD; clean-all: BUILD entirely, the cargo target included
```

Build products go to `BUILD`, default `out/` in the repository (git-ignored): the cargo target, the Verilator objects,
the example dumps and pages, the smoke screenshots. `make clean` empties it but keeps the cargo target, `make clean-all`
removes it. On a slow mount (this repository on `/mnt/c` under WSL) `make BUILD=/tmp/wavelens …` builds faster; `/tmp`
is emptied on a reboot, and `make smoke` reports what is missing as `SKIPPED n pages / n sections (run make examples, …)`.

**The prebuilt CLI.** `bin/linux-x86_64/sva` (`x86_64-unknown-linux-musl`, statically linked) is committed, so a
clone runs the tools with assertions without Rust; like `wavelens/sva.wasm.js` it is rebuilt (`make dist-linux`) in the
commit that changes the engine. `bin/windows-x86_64/sva.exe` (`x86_64-pc-windows-gnu`, linked by mingw-w64) is not
committed yet: `make dist-windows` builds it where mingw-w64 is installed (commit it then, with every engine change). One time: `rustup target add x86_64-unknown-linux-musl x86_64-pc-windows-gnu` and, for Windows,
`sudo apt install mingw-w64`. The tools take the CLI from `--sva-bin`, else `$WAVELENS_SVA`, else `out/sva-target/release/sva`
(`make sva-build`), else `bin/<os>-x86_64/`, else `sva` on PATH. `make unit` gives them the CLI of its `BUILD` when
that is built, and `make check` builds it first: an older `out/` build would test stale code.

`make check` is the gate for every change. `make smoke` opens `docs/index.html`, `tests/conformance.html`, every built
page (demo, FST demo, examples) and the user's pages under `work/` when they are there, fails on console errors, and
runs interaction checks per page (cursor, zoom, sort, settings layers, highlight, find, bookmarks and arrows, FSM
names, the assertions). The hierarchy, find and virtualisation checks run on a synthetic page smoke builds itself
(2060 signals in 255 scopes, 8 levels), so a fresh clone runs them. `tests/conformance.html` is compared with stock
WaveDrom: the lanes and the texts of every case. Every check belongs to a section; a FAIL names it. Time limits are for
a desktop machine: `SMOKE_TIME_SCALE=3` allows three times as much on a loaded one. An exception in a section is a FAIL of
that section with a PNG under `BUILD/smoke/<section>-error.png`; the other sections still run. The section `units` is
a table of JavaScript expressions and their values on a blank page (`UNITS` in `tests/smoke.py`, ~200 cases: decode,
bits, struct fields, the value search, times, analog values, edges, the page's VCD reader, the bus decoders, the
expressions of `sva.js`); it calls the pure functions through `WaveLens.internal`, not an API, and the other sections
read the fields of a viewer through `WaveLens.internal.peek(v)` only (`plugin_api` checks it), so a refactoring of
`view.js` changes one place of the tests.

**The VS Code extension** (`vscode/`) keeps the viewer as it is in a browser: `media/host.js`, loaded before
`wavelens.js` in the tab, replaces what a webview cannot do or does on the wrong machine (the tab runs on the client,
the extension and the files on the host) — `localStorage` (the dump's store in `workspaceState`, given in the page),
an `<a download>` clicked (a save dialog on the host), an `<input type=file>` clicked (an open dialog on the host),
`navigator.clipboard.writeText`, `EventSource` / `fetch` / `sendBeacon` to `127.0.0.1` (relayed to the host's: the
agent's `wavemcp.py`), the theme; and it stops a key the viewer took (`preventDefault`) before VS Code's webview
forwards it to the workbench (every keydown that reaches its window). The smoke section `vscode` runs that half under the
extension's CSP with a fake `acquireVsCodeApi`; `make vscode-e2e` (`tests/vscode_e2e.py`) the whole extension in a
real VS Code — in WSL the Windows VS Code connected to the distribution by Remote - WSL (its own user data under
`BUILD/vscode-e2e`): the FSM example's VCD and FST and `test_stream_video.fst` opened (a picture of each), the store
over reopening, a new write read again, an agent's `wavemcp.py` opening a dump with `view_live` and marking it up, a
dump in a folder with a space, the Verilator command with `?` in a file's name. The runner gives each run an id and takes
only that run's `result.json` when it says it ended, and every check of its list must be there (a run that stops early
fails, it does not pass with fewer); the agent's check counts only the live notes of its own bridge.
`--installed` runs the `.vsix` installed into the host (`code --install-extension`) instead of `vscode/`. Not
automated: the save / open dialogs themselves and keys through Windows (checked by hand).

The viewer's commands live twice: in the page (`wavelens/src/edit.js`, `view.run`) and in `tools/viewedit.py`, which
writes a page's edits without a browser. The section `edit` holds them together: the two lists of commands and their
arguments are one (`WaveLens.commands()` against `COMMANDS`), and a list of every command that changes a state
(`EDIT_OPS`), written into a page by `viewedit.py`, opens with the state that the same list run in the page gives —
a command added to one side only, or one that differs, fails there. It also runs `wavemcp.py` as an agent's MCP
server with a page connected live (`WAVELENS_LIVE_PORT=0`: a free port; its key in a scratch `XDG_CACHE_HOME`).

`make unit` (`tests/unit/`, unittest, standard library only) tests the tools function by function on the fixtures in
`tests/unit/vcd/` — each a few lines of what a simulator writes: `real` (`realtime`, `shortreal`, `inf`, `nan`), `string`
and `event` variables, escaped names, a range glued to the name, the same path under two id codes, a vector in parts
(bits, ranges apart, two bits under one code), several changes on one line, tabs, indents and a time inside a line,
`$comment` in the body, VHDL values, time going back, a header without `$enddefinitions`, times above 2^53 ps. The smoke section `readers` feeds the
same files to the page's own VCD reader (`wavelens/src/vcd.js`) and demands the transitions of the tools; `test_svabuild`
compares the name rule of `svabuild.Names` with `sva eval --resolve` case by case.

Beside the fixtures, generated input (review VI): `readers` reads 40 VCDs made from a seed (`gen_vcd`: aliases, a vector
bit by bit, escaped and UTF-8 names, comments naming `$enddefinitions`, enum tables, changes on one line) against what
the generator wrote down (the enum table too), against the tools, and as a File in pieces of 1–64 bytes (the parser
given pieces of as many characters), three of them cut in two at every byte;
`tests/unit/types/contract.json` is what `svtypes.py` and the page's `svTypes` / `svApply` / `svFingerprint` must both
give (`test_svtypes` Contract, smoke `readers`; `sva fst` too: `cli.rs` `fst_gives_the_enum_tables_the_twins_give`, a
case's `ref` its `$var` as a VCD writes it), and 200 generated types files and dumps hold the two side by side.
`test_svafst` holds `sva fst` to GTKWave's `vcd2fst`: 40 VCDs from a seed (widths 1 to 1000, x and z, reals, strings,
aliases, small blocks) and every fixture, both FSTs read back by `fst2vcd` and `sva vcd`, the same variables and
changes; the fixtures where `vcd2fst` writes another FST are listed with the reason (`DIFFERS`).
`tests/unit/golden` keeps the bytes `wavejson.py` and `vcd2wavedrom.py` write (`make unit-bless`). `svaverify.py` does
not let the comparison with Verilator shrink: only the assertions of an example's `unsupported` list may be put out,
the simulation must reach `$finish`, every compared assertion must be evaluated (not capped, not vacuous only). The
smoke section `examples` evaluates the exact views' bindings again in the page (WebAssembly, a worker for the first) and
compares them attempt by attempt with `sva eval`'s, and `sva_third_party` pins the totals of each third-party
evaluation (`THIRD_PARTY`). Budgets (`tests/unit/test_perf.py`, smoke `readers` and `fsm`): the converter on two sizes of
a generated dump (time, peak memory, both growing with the dump), the page's reader of 18 MB in pieces, the FSM panel
over 1500 FSMs (`WAVELENS_TIME_SCALE` and `SMOKE_TIME_SCALE` multiply their times on a loaded machine). `make unit-shuffle SEED=n` runs the unit tests one by one in another order.

`make shots` checks looks rather than
behaviour: fixed viewport, fixed clicks, two animation frames after each, one element per image; it stops when IBM Plex
is not available (offline without `fonts-ibm-plex`) instead of writing PNGs that differ. The same code gives the same
bytes: Chromium rasterises in software, in one thread (`RASTER` in `tests/shots.py`: the borders of the form controls
were anti-aliased differently run after run), tooltips are hidden and the pointer moved away before a shot. `make
shots-check` (in the gate) makes `docs/img` and `tests/visual` (the white theme, 420 px wide, an FSM's details, a device
scale of 2) again, none left from a run before, and compares them pixel by pixel (`tests/pngdiff.py`): a picture that
changed (more than 48 pixels), or one made that is not committed, fails, its difference
in `BUILD/img/diff` / `BUILD/visual/diff`; a look changed on purpose: `make shots` and commit the PNGs. Both need
Python playwright (a
user-site install, so they run without `-I`, with `PYTHONDONTWRITEBYTECODE=1`). Environment used: Verilator 5.046,
GTKWave fst2vcd, cargo 1.98 (the engine needs Rust ≥ 1.82).

SystemVerilog follows [SV_STYLE.md](SV_STYLE.md). Reformatting `tests/sva/*.sv` moves the line numbers in the golden
files: `make sva-bless`, then the diff must show nothing but `line N`; the carets of `tests/sva/err_*.sv` move by hand.

## CI on the local machine

`.github/workflows/check.yml` runs the gate on GitHub's side of a push, but on the maintainer's machine: a
[self-hosted runner](https://docs.github.com/en/actions/hosting-your-own-runners) there, registered for this
repository with the label `wavelens`, takes the job. It runs on every push to `master` (that is every release
`tools/publish.py` wrote) and by hand (Actions → check → Run workflow): a fresh checkout of the public tree,
`make clean` and `make check` in one `BUILD` kept beside the runner's work folder (the cargo target stays, so the
engine builds incrementally), then `cargo clippy --all-targets -D warnings`. A failed run uploads `BUILD/smoke`,
`BUILD/shots` and the shots' diffs as an artifact (7 days). The machine needs what `make check` needs (§ Build and
test); the runner inherits the `PATH` of the shell that configured it. A push while the machine is off waits in the
queue (GitHub keeps a job 24 hours) and runs when the runner is back. What the gate does not run: the VS Code
extension's end-to-end test (`make vscode-e2e`: VS Code itself in a window, Convert to FST among its checks), run by
hand before a release that changes `vscode/`.

Once, in WSL (systemd on: `/etc/wsl.conf` `[boot] systemd=true`), on the Linux file system — the token from GitHub,
repository → Settings → Actions → Runners → New self-hosted runner (it is valid one hour):

```sh
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -fsSLO https://github.com/actions/runner/releases/download/v2.338.1/actions-runner-linux-x64-2.338.1.tar.gz
tar xzf actions-runner-linux-x64-2.338.1.tar.gz        # the sha256 is on the release page
./config.sh --url https://github.com/vae-tech/wave_lens --token TOKEN --name "$(hostname)-wsl" --labels wavelens --unattended
sudo ./svc.sh install "$USER" && sudo ./svc.sh start   # a systemd service: it starts with the distribution
```

`./run.sh` instead of the service runs it in a terminal for one session. After a change of the toolchain's paths,
`./env.sh` in `~/actions-runner` and `sudo ./svc.sh stop && sudo ./svc.sh start`. To remove it: `sudo ./svc.sh
uninstall`, then `./config.sh remove --token TOKEN` (a removal token from the same page).

**Safety.** The repository is public and a self-hosted runner runs what a workflow tells it, as the runner's user.
`check.yml` has no `pull_request` trigger, but a fork's pull request could bring a workflow of its own aimed at the
label: keep Settings → Actions → General → *Approval for running fork pull request workflows from contributors* at
**Require approval for all external contributors**, and approve nothing you have not read. WSL may stop the distribution
some time after its last terminal closed; while it is down the jobs wait.

## Measured

The dump reader (`tools/dumpscan.py`, `vcd2wavedrom.py`), measured on this machine (16 CPUs):

| Job | time, memory |
|---|---|
| `test_stream_video.vcd` (24 MB), every changing signal: 1526 signals, 4.8 M changes | 25 s, 1.5 GB |
| `mkconfig.py test_stream_video.vcd` (3520 signals listed, changes counted) | 2.7 s, 26 MB |
| `dump.vcd` (14 MB), view `full` (15 signals, exact, markers) | 2.0 s |
| demo (25 signals) | 0.15 s |

The viewer on the page of `test_stream_video` (1526 signals, every group open: 1731 rows; median of 5 in headless
Chromium, before / after stage 9.4; the arbiter page: the same dump with five bindings, 16 068 failures):

| Job | before 9.4 | after |
|---|---|---|
| `renderNames()` (the names column) | 13.2 ms | 1.4 ms (built again only when its rows change) |
| a click on a name (select, draw) | 70.9 ms | 4.8–5.6 ms |
| ArrowDown on the waves | 67.5 ms | 4.6–5.1 ms |
| a find keystroke (`p`, `px`, `pxv`, `pxvd`) | 29 ms | 38–43 ms: the rows shown change with every letter, so the DOM of the names column is built again (1488 rows 69 ms, 309 rows 15 ms); a virtual names column would help |
| 20 wheel events and the frame after them | 66.7 ms | 35 ms (one draw per frame; most of it is the two frames waited for) |
| Clear on the arbiter page | 28.4 ms | 22.5–30.8 ms |

The second cursor (step 12.4: the rising edges of a clock indexed once, the cycles between the cursors by two binary
searches): a clock of 400 000 changes and 20 buses, 100 ns of 2 ms shown, `draw()` 0.89 ms without the second cursor
and 0.93 ms with it (8000 cycles between them); before, 1.55 → 8.14 ms.

A second dump compared and a busy bus drawn analog (the review of 0.15; smoke section `view_review` keeps a check of
each): 6000 signals, the names' ≠ marks 941 → 10 ms (each row's element from a map built with the names column, not a
search per row), compared no more 1068 → 84 ms, alt+↓ in a group of yours 2.3 → 0.33 s; a clock of a million toggles
a picosecond late in B, a redraw at Fit 2.6 s → 37 ms and `]d` 2.5 s → 36 ms (the stretches less than a pixel apart one
band, the next one by a binary search: a band per pixel at most; the SVG the same); a 16-bit bus of 20 000 changes as a
step plot, a redraw at Fit 1050 → 9 ms and its SVG 1.5 MB → 120 KB (one bar per pixel column, its smallest and largest
value), 500 000 changes 97 ms (before: the page did not open in 30 s).

The SVA engine's numbers are in [`sva/ENGINE.md`](sva/ENGINE.md) *Performance*.

The MCP server (`make mcp-bench AGENT=claude MODEL=sonnet REPS=2`, `AGENT=codex`; 21 October 2026, the tool list of
5036 characters): every token per task, the median of two runs without the tools → with them (saved). Every one of the
128 answers was right. The tasks: a1 the APB checkers (which fails, when), a2 APB wait states, read data and the
error, b1–b5 the generated dump (clock and reset, frames, a req / ack rule with one late ack, the error pulse and the
FIFO level then, the FIFO's maximum), c1 the FSM's states by name from the FST.

| Task | Claude, MCP | Claude, `--call` | Codex, MCP | Codex, `--call` |
|---|---|---|---|---|
| a1 | 72k → 21k (+71%) | 72k → 77k (−8%) | 102k → 94k (+9%) | 102k → 61k (+41%) |
| a2 | 40k → 36k (+10%) | 40k → 29k (+28%) | 66k → 99k (−50%) | 66k → 54k (+18%) |
| b1 | 30k → 31k (−5%) | 30k → 30k (−2%) | 58k → 75k (−29%) | 58k → 82k (−40%) |
| b2 | 48k → 41k (+16%) | 48k → 57k (−18%) | 67k → 87k (−31%) | 67k → 53k (+20%) |
| b3 | 39k → 28k (+27%) | 39k → 51k (−31%) | 67k → 109k (−63%) | 67k → 83k (−24%) |
| b4 | 44k → 50k (−14%) | 44k → 40k (+9%) | 50k → 97k (−93%) | 50k → 72k (−43%) |
| b5 | 28k → 32k (−13%) | 28k → 33k (−19%) | 47k → 103k (−121%) | 47k → 72k (−54%) |
| c1 | 43k → 22k (+49%) | 43k → 22k (+49%) | 101k → 77k (+24%) | 101k → 64k (+37%) |
| sum | 343k → 261k (+24%) | 343k → 339k (+1%) | 558k → 741k (−33%) | 558k → 540k (+3%) |

What changed the numbers on the way: the first tool list (8354 characters, ten tools) cost Claude about 3.7 k tokens
more per request (a request of "OK" with and without it); cut to 5036 (the conventions once in the server's
instructions, `wave_wavedrom` folded into `wave_page`), Claude's tokens saved stayed at 24 % while its cost per run went
from 7 % more than without the tools to 28 % less (the first round: one run per task, without c1). Without `readOnlyHint` on the tools `codex exec` refuses to call them ("requires
approval"): the agent falls back to its shell. The runs, their transcripts and answers: `BUILD/mcp_bench/runs.jsonl`,
`BUILD/mcp_bench/runs/*/transcript.jsonl`.

## Versions

Two numbers, `MAJOR.MINOR` (0.19 now; [`CHANGELOG.md`](../CHANGELOG.md) lists them all). The work goes on a branch;
a version is a merge into the development branch `dev` (`git merge --no-ff`) tagged `dev/vMAJOR.MINOR` (an annotated
tag, its message the changelog entry; `dev` and its tags were `main` and `main/v*` up to 0.18). The public branch `master` then gets the version as one commit: `python3 -I tools/publish.py
MAJOR.MINOR "what it brings"` writes the tree of `dev/vMAJOR.MINOR` less the internal files (`INTERNAL` there)
with that one line as its message, and tags it `vMAJOR.MINOR`. Only `master` and the `v*` tags go to GitHub (a local
`.git/hooks/pre-push` refuses the rest; deleting a branch there it lets through). One commit on the branch before the merge raises the version in four places: `VERSION`,
`version:` in `wavelens/src/boot.js` (then `make wavelens`), a new top entry in `CHANGELOG.md`, and the committed builds
that carry it (`make sva-build dist-linux`: the `sva` CLI writes the version into a report's meta through
`include_str!` of `VERSION`); `make unit` fails when they disagree. The Rust crates keep their own semver in
`sva/Cargo.toml`. A page tells its version in `WaveLens.version`; `make smoke` names a page under `work/` built with
another one.

## Where it stands

The viewer, the tools, the SystemVerilog Assertion engine (stack: [`sva/STACK.md`](sva/STACK.md) — Rust core, native
CLI over VCD / FST, WebAssembly in the page), expressions and Why, bus transactions, gaps, the MCP server, the viewer's
commands, the Modules panel and the VS Code extension are done; [`CHANGELOG.md`](../CHANGELOG.md) says what came in
each version. The work was planned as a series of stage prompts and checked by reviews with their findings and the
commits that closed them; both live on the development branch `dev` only (`prompts/`, `docs/reviews/`), not in the
public branch.

Done so far: the language front end ([`sva/LANGUAGE.md`](sva/LANGUAGE.md)), the evaluator
([`sva/ENGINE.md`](sva/ENGINE.md)) and the assertions in the page ([USAGE.md § Assertions](USAGE.md#assertions-sva):
list, binding to instances, evaluation on demand; attempts, steps, arrows and failures drawn on the waves; statistics,
the failure list and reports). Besides its own corpus, the engine is tested on checkers written by others for
AXI4-Lite, APB and AHB (YosysHQ's AXI4 FVIP property library, OpenTitan's assertion macros and more:
[`tests/sva/third_party`](../tests/sva/third_party/README.md)), evaluated over the example dumps by `make smoke`.
`sva parse FILE...` reads `property` / `sequence` declarations and `assert` / `assume` / `cover property` statements in
modules, checkers, interfaces, programs and packages, with macros, `` `ifdef ``, parameters and enums, and prints each
assertion expanded: its clock and reset, its sequence elements (the steps the viewer will draw), the signals it reads
with their widths. Errors give line:column with the source line, and the rest of the file still loads:

```
$ sva parse examples/apb/apb_tb.sv examples/apb/apb.sva
…
assert apb_read_waits in apb_checks, line 83
  clock     @(posedge PCLK) disable iff (!PRESETn)
  expr      PSEL && !PENABLE && !PWRITE && PADDR[7:4] == 0 && PADDR[1:0] == 0 |=> (!PREADY)[*2] ##1 PREADY
  s1        PSEL && !PENABLE && !PWRITE && PADDR[7:4] == 0 && PADDR[1:0] == 0
  s2        (!PREADY)[*2]
  s3        ##1 PREADY
  signals   PCLK:1 PRESETn:1 PSEL:1 PENABLE:1 PWRITE:1 PADDR[>=8]:8 PREADY:1
…
```

`sva eval` runs them over a dump: signals resolve under `--scope` (then the scopes above it; `--resolve scope`: only the
clock, as when the page binds), values are sampled just before each clock edge with x and z kept, every cycle starts an
attempt, sequences run as threads (ranges, repetitions, `and` / `or` / `intersect` / `within` / `throughout` /
`first_match`), `disable iff` ends the alive attempts. It prints one line per assertion and writes the results JSON the
viewer will draw: per assertion the counts, every non-vacuous attempt with its steps (`[["s1", 52]]`), the cycle and
reason of a failure, and a per-cycle lane. Each example has one deliberately wrong assertion, so the failure trace
shows (`…`: lines left out; `--attempts` adds a line per attempt, USAGE.md § Tools):

```
$ sva eval --waves BUILD/examples/apb/apb.fst --scope apb_tb --sva examples/apb/apb_tb.sv --sva examples/apb/apb.sva --out apb.json
apb_setup_then_access assert 19 attempts: 3 pass, 0 fail, 16 vacuous, 0 active, 0 disabled
…
apb_read_waits        assert 19 attempts: 1 pass, 0 fail, 18 vacuous, 0 active, 0 disabled
apb_demo_no_wait      assert 19 attempts: 3 pass, 2 fail, 14 vacuous, 0 active, 0 disabled · first fail at cycle 10 (105 ns): expected PREADY at cycle 10
…
apb_cov_read_wait     cover  1 match in 19 attempts · first at cycle 12 (125 ns)
…
```

The same engine runs in the page as WebAssembly (`wavelens/sva.js`: `evaluate(parsed, sampler)` over the viewer's rows or
WaveJSON `tv` transitions): one assertion over 32 768 clock edges in about 73 ms.
