# Developing wavefw

How the project is laid out, built and tested, what was measured, and where the roadmap and the reviews live. Using
wavefw is [USAGE.md](USAGE.md).

## Project layout

```
wavefw/                       what a page needs, nothing else
  wavefw.js / wavefw.css      framework (one <script> + one <link>); wavefw.js is made by make wavefw from src/
  src/                        model.js (settings, sorting, find, time, values, the parser), vcd.js (a VCD read in the
                              page), paint.js (the two painters
                              and what they draw), view.js (WaveView and its parts Bar, Names, Notes), svg.js (WaveSVG),
                              boot.js (themes, configure, upgrade, exports): one scope, concatenated in this order
  wavefw.config.js            global settings file (all keys, with defaults), loaded before wavefw.js
  sva.js, sva.wasm.js         assertions in the page: the panel, binding, evaluation; the engine (generated, make sva-build)
  bus.js                      bus transactions: ports found by their names, decoders (AXI, AXI-Stream, APB, AHB, Avalon, Wishbone, OBI), rows
tools/                        what you run: python3 -I tools/<tool>.py
  mkconfig.py vcd2wavedrom.py mkhtml.py embed.py dumpscan.py wavejson.py svabuild.py
  wavemcp.py                  the tools as an MCP server for AI agents (stdio; USAGE § AI agents)
  base.config.json            base settings for generated configs (make config / make html WAVES=x.vcd)
examples/                     apb/ axi_lite/ fsm/ demo/: testbench, config, README; *.sva: assertions for each;
                              test_video/: the CoaXPress checkers over a real dump (the dump and page not in git)
docs/                         what you look at
  index.html                  the reference page with live examples (opens from file://)
  USAGE.md, DEVELOPMENT.md    the user's guide; this file
  SV_STYLE.md                 the SystemVerilog style of the project
  demo_waves.js, apb_waves.js its data (make demo), tracked
  img/                        the README screenshots (make shots)
  sva/                        the SVA engine: STACK.md (technology), LANGUAGE.md (the subset), ENGINE.md (semantics,
                              results JSON, performance), the JSON schemas
  reviews/                    the reviews of the stages, each finding with file:line, probe, fix and the closing commit
  reference/template.html     the original visual reference (PSI5 datasheet)
tests/
  unit/                       the Python unit tests of the tools (make unit: unittest, standard library); vcd/: small VCDs
                              of what simulators write (real, string, event, escaped names, VHDL values, comments …)
  smoke.py                    behaviour checks in headless Chromium (make smoke)
  mcp_bench.py                what the MCP server saves an agent: tasks with known answers, agents with and without it
  sva/                        the SVA corpus: *.sv with every construct, err_*.sv with annotated errors, golden/;
                              third_party/: AXI4-Lite, APB, AHB checkers of others (licenses, units.json)
  shots.py                    the screenshots (make shots)
  conformance.html            every feature next to stock WaveDrom 3.5.0 (vendor/, test-only)
work/                         your dumps and their configs: configs tracked, dumps and pages git-ignored
sva/                          the SVA engine (Rust: core, native CLI, WebAssembly)
prompts/                      the roadmap as a series of prompts
bin/                          the prebuilt sva CLI, committed: linux-x86_64/sva (static); windows-x86_64/sva.exe by make dist-windows
out/                          build products (make's BUILD, git-ignored): cargo target, example dumps and pages, shots
Makefile                      make help lists the targets; build products go to BUILD (default out/)
```

## Build and test

```sh
make check                  # the gate before a commit: wavefw.js current and its sources ≤ 160 columns, sva-test, unit, every page smoke needs, sva-verify, mcp-bench, smoke STRICT=1, shots-check
make unit                   # tests/unit: the tools on small VCDs of what simulators write (130 tests, ~10 s, standard library)
make mcp-bench              # tools/wavemcp.py on the benchmark tasks by a script (answers checked); AGENT=claude|codex: agents
make wavefw                 # wavefw/wavefw.js from wavefw/src/*.js (after editing them; make html / example do it too; lines ≤ 160 columns)
make demo examples html     # rebuild docs/demo_waves.js, the example pages, the demo page
make smoke                  # tests/smoke.py: every page in light and dark, 470 checks on 26 pages, PNGs in BUILD/shots
make smoke ONLY=find,sva_bind   # some sections (python3 tests/smoke.py --list); STRICT=1: a skip fails
make shots                  # tests/shots.py: docs/img/*.png, dark theme (after make examples; ~20 s, see below)
make shots-check            # the same into BUILD/img, compared with docs/img: a shot that no longer builds fails
make sva-build              # the SVA engine (needs cargo + the wasm32 target): the sva CLI, wavefw/sva.wasm.js
make dist                   # the CLI: bin/linux-x86_64/sva (musl, static, committed) + bin/windows-x86_64/sva.exe (mingw-w64)
make sva-test               # the SVA engine: unit tests, the corpus tests/sva (third_party too), the JSON schema, the CLI
make sva-bless              # rewrite tests/sva/golden/*.txt after a reviewed change of the parser output
make sva-examples sva-spike # sva parse + sva eval of examples/*/*.sva; the WebAssembly build in a page (wasm32 target)
make sva-verify             # the examples' checkers in Verilator --assert against sva eval (sva/ENGINE.md § Tests)
make sva-eval WAVES=work/x.fst SVA="pkg.sv checks.sva" SCOPE=tb.dut OUT=results.json   # assertions over any dump
make fmt lint               # verible-verilog-format (docs/SV_STYLE.md), verilator --lint-only -Wall on the testbenches
make clean                  # the build products under BUILD; clean-all: BUILD entirely, the cargo target included
```

Build products go to `BUILD`, default `out/` in the repository (git-ignored): the cargo target, the Verilator objects,
the example dumps and pages, the smoke screenshots. `make clean` empties it but keeps the cargo target, `make clean-all`
removes it. On a slow mount (this repository on `/mnt/c` under WSL) `make BUILD=/tmp/wavefw …` builds faster; `/tmp`
is emptied on a reboot, and `make smoke` reports what is missing as `SKIPPED n pages / n sections (run make examples, …)`.

**The prebuilt CLI.** `bin/linux-x86_64/sva` (`x86_64-unknown-linux-musl`, statically linked) is committed, so a
clone runs the tools with assertions without Rust; like `wavefw/sva.wasm.js` it is rebuilt (`make dist-linux`) in the
commit that changes the engine. `bin/windows-x86_64/sva.exe` (`x86_64-pc-windows-gnu`, linked by mingw-w64) is not
committed yet: `make dist-windows` builds it where mingw-w64 is installed (commit it then, with every engine change). One time: `rustup target add x86_64-unknown-linux-musl x86_64-pc-windows-gnu` and, for Windows,
`sudo apt install mingw-w64`. The tools take the CLI from `--sva-bin`, else `$WAVEFW_SVA`, else `out/sva-target/release/sva`
(`make sva-build`), else `bin/<os>-x86_64/`, else `sva` on PATH.

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
expressions of `sva.js`); it calls the pure functions through `WaveFW.internal`, not an API, and the other sections
read the fields of a viewer through `WaveFW.internal.peek(v)` only (`plugin_api` checks it), so a refactoring of
`view.js` changes one place of the tests.

`make unit` (`tests/unit/`, unittest, standard library only) tests the tools function by function on the fixtures in
`tests/unit/vcd/` — each a few lines of what a simulator writes: `real`, `string` and `event` variables, escaped names,
a range glued to the name, the same path under two id codes, several changes on one line, `$comment` in the body, VHDL
values, time going back, a header without `$enddefinitions`, times above 2^53 ps. The smoke section `readers` feeds the
same files to the page's own VCD reader (`wavefw/src/vcd.js`) and demands the transitions of the tools; `test_svabuild`
compares the name rule of `svabuild.Names` with `sva eval --resolve` case by case. `make shots` checks looks rather than
behaviour: fixed viewport, fixed clicks, two animation frames after each, one element per image; it stops when IBM Plex
is not available (offline without `fonts-ibm-plex`) instead of writing PNGs that differ. The same code gives the same
bytes: Chromium rasterises in software, in one thread (`RASTER` in `tests/shots.py`: the borders of the form controls
were anti-aliased differently run after run), tooltips are hidden and the pointer moved away before a shot. Both need
Python playwright (a
user-site install, so they run without `-I`, with `PYTHONDONTWRITEBYTECODE=1`). Environment used: Verilator 5.046,
wavepeek 3.1.0, GTKWave fst2vcd, cargo 1.98 (the engine needs Rust ≥ 1.82).

SystemVerilog follows [SV_STYLE.md](SV_STYLE.md). Reformatting `tests/sva/*.sv` moves the line numbers in the golden
files: `make sva-bless`, then the diff must show nothing but `line N`; the carets of `tests/sva/err_*.sv` move by hand.

## Measured

The two dump readers, measured on this machine (16 CPUs), output byte-identical:

| Job | builtin | wavepeek |
|---|---|---|
| `test_stream_video.vcd` (24 MB), every changing signal: 1526 signals, 4.8 M changes | 25 s, 1.5 GB | 45 s, 2.9 GB |
| `mkconfig.py test_stream_video.vcd` (3520 signals listed, changes counted) | 2.7 s, 26 MB | 12 s |
| `dump.vcd` (14 MB), view `full` (15 signals, exact, markers) | 2.0 s | 7.0 s |
| demo (25 signals) | 0.15 s | 0.19 s |

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

Two numbers, `MAJOR.MINOR` (0.11 now; [`CHANGELOG.md`](../CHANGELOG.md) lists them all). The work goes on a branch;
a version is a merge into `main` (`git merge --no-ff`) tagged `vMAJOR.MINOR` (an annotated tag, its message the
changelog entry). One commit on the branch before the merge raises the version in four places: `VERSION`,
`version:` in `wavefw/src/boot.js` (then `make wavefw`), a new top entry in `CHANGELOG.md`, and the committed builds
that carry it (`make sva-build dist-linux`: the `sva` CLI writes the version into a report's meta through
`include_str!` of `VERSION`); `make unit` fails when they disagree. The Rust crates keep their own semver in
`sva/Cargo.toml`. A page tells its version in `WaveFW.version`; `make smoke` names a page under `work/` built with
another one.

## Roadmap and reviews

The stages are prompts in [`prompts/`](../prompts/00-roadmap.md); stages 1–8 are done: the restructure, the examples
and screenshots, and a SystemVerilog Assertion engine (stack: [`sva/STACK.md`](sva/STACK.md) — Rust core,
native CLI over VCD / FST, WebAssembly in the page) that binds assertions to instances of the waveform, evaluates them
over the dump, draws attempts, steps and failures next to the signals and reports the numbers. The global review of
October 2026 ([`reviews/global-review-2026-10.html`](reviews/global-review-2026-10.html)) drove stage 9
(`prompts/09-refactor-cycle.md`: 9.1 hygiene and 9.4 the viewer done, the viewer features of 9.5 landed); stages 10
(expressions, Why) and 11 (bus transactions) followed. The second review
([`reviews/global-review-2026-10-19.html`](reviews/global-review-2026-10-19.html)) drives stage 12
(`prompts/12-review-cycle.md`, steps 12.1–12.6: gates, the Python unit layer — the former 9.2 —, the engine's
robustness — the former 9.3 —, the viewer, tests, docs); 9.6 (the real project) comes after it. What could come later
is listed at the end of `prompts/00-roadmap.md`.

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

The same engine runs in the page as WebAssembly (`wavefw/sva.js`: `evaluate(parsed, sampler)` over the viewer's rows or
WaveJSON `tv` transitions): one assertion over 32 768 clock edges in about 73 ms.
