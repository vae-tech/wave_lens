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
  smoke.py                    behaviour checks in headless Chromium (make smoke)
  sva/                        the SVA corpus: *.sv with every construct, err_*.sv with annotated errors, golden/;
                              third_party/: AXI4-Lite, APB, AHB checkers of others (licenses, units.json)
  shots.py                    the screenshots (make shots)
  conformance.html            every feature next to stock WaveDrom 3.5.0 (vendor/, test-only)
work/                         your dumps and their configs: configs tracked, dumps and pages git-ignored
sva/                          the SVA engine (Rust: core, native CLI, WebAssembly)
prompts/                      the roadmap as a series of prompts
bin/                          the prebuilt sva CLI, committed: linux-x86_64/sva (static), windows-x86_64/sva.exe (make dist)
out/                          build products (make's BUILD, git-ignored): cargo target, example dumps and pages, shots
Makefile                      make help lists the targets; build products go to BUILD (default out/)
```

## Build and test

```sh
make check                  # the gate before a commit: wavefw.js current, sva-test, unit, every page smoke needs, smoke STRICT=1
make wavefw                 # wavefw/wavefw.js from wavefw/src/*.js (after editing them; make html / example do it too)
make demo examples html     # rebuild docs/demo_waves.js, the example pages, the demo page
make smoke                  # tests/smoke.py: every page in light and dark, 408 checks on 26 pages, PNGs in BUILD/shots
make smoke ONLY=find,sva_bind   # some sections (python3 tests/smoke.py --list); STRICT=1: a skip fails
make shots                  # tests/shots.py: docs/img/*.png, dark theme (after make examples; ~10 s, see below)
make sva-build              # the SVA engine (needs cargo + the wasm32 target): the sva CLI, wavefw/sva.wasm.js
make dist                   # the committed CLI: bin/linux-x86_64/sva (musl, static) + bin/windows-x86_64/sva.exe (mingw-w64)
make sva-test               # the SVA engine: unit tests, the corpus tests/sva (third_party too), the JSON schema, the CLI
make sva-bless              # rewrite tests/sva/golden/*.txt after a reviewed change of the parser output
make sva-examples sva-spike # sva parse + sva eval of examples/*/*.sva; the WebAssembly build in a page (wasm32 target)
make sva-eval WAVES=work/x.fst SVA="pkg.sv checks.sva" SCOPE=tb.dut OUT=results.json   # assertions over any dump
make fmt lint               # verible-verilog-format (docs/SV_STYLE.md), verilator --lint-only -Wall on the testbenches
make clean                  # the build products under BUILD; clean-all: BUILD entirely, the cargo target included
```

Build products go to `BUILD`, default `out/` in the repository (git-ignored): the cargo target, the Verilator objects,
the example dumps and pages, the smoke screenshots. `make clean` empties it but keeps the cargo target, `make clean-all`
removes it. On a slow mount (this repository on `/mnt/c` under WSL) `make BUILD=/tmp/wavefw …` builds faster; `/tmp`
is emptied on a reboot, and `make smoke` reports what is missing as `SKIPPED n pages / n sections (run make examples, …)`.

**The prebuilt CLI.** `bin/linux-x86_64/sva` (`x86_64-unknown-linux-musl`, statically linked) and
`bin/windows-x86_64/sva.exe` (`x86_64-pc-windows-gnu`, linked by mingw-w64) are committed, so a clone runs the tools
with assertions without Rust; like `wavefw/sva.wasm.js` they are rebuilt (`make dist`) in the commit that changes the
engine. One time: `rustup target add x86_64-unknown-linux-musl x86_64-pc-windows-gnu` and, for Windows,
`sudo apt install mingw-w64`. The tools take the CLI from `--sva-bin`, else `$WAVEFW_SVA`, else `out/sva-target/release/sva`
(`make sva-build`), else `bin/<os>-x86_64/`, else `sva` on PATH.

`make check` is the gate for every change. `make smoke` opens `docs/index.html`, `tests/conformance.html`, every built
page (demo, FST demo, examples) and the user's pages under `work/` when they are there, fails on console errors, and
runs interaction checks per page (cursor, zoom, sort, settings layers, highlight, find, bookmarks and arrows, FSM
names, the assertions). The hierarchy, find and virtualisation checks run on a synthetic page smoke builds itself
(2060 signals in 255 scopes, 8 levels), so a fresh clone runs them. `tests/conformance.html` is compared with stock
WaveDrom: the lanes and the texts of every case. Every check belongs to a section; a FAIL names it. Time limits are for
a desktop machine: `SMOKE_TIME_SCALE=3` allows three times as much on a loaded one. `make shots` checks looks rather than
behaviour: fixed viewport, fixed clicks, two animation frames after each, one element per image; it stops when IBM Plex
is not available (offline without `fonts-ibm-plex`) instead of writing PNGs that differ. The same code gives the same
bytes, except that `hero.png` and `sva.png` (the first shot of their page) now and then differ in a few anti-aliased
pixels at the top left (about one run in five; open, not yet explained): compare with `git diff --stat docs/img` and
run again before you commit a changed picture. Both need Python playwright (a
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

The SVA engine's numbers are in [`sva/ENGINE.md`](sva/ENGINE.md) *Performance*.

## Roadmap and reviews

The stages are prompts in [`prompts/`](../prompts/00-roadmap.md); stages 1–8 are done: the restructure, the examples
and screenshots, and a SystemVerilog Assertion engine (stack: [`sva/STACK.md`](sva/STACK.md) — Rust core,
native CLI over VCD / FST, WebAssembly in the page) that binds assertions to instances of the waveform, evaluates them
over the dump, draws attempts, steps and failures next to the signals and reports the numbers. The global review of
October 2026 ([`reviews/global-review-2026-10.html`](reviews/global-review-2026-10.html)) is worked off by stage 9
(`prompts/09-refactor-cycle.md`, steps 9.1–9.6); what could come after is listed at the end of
`prompts/00-roadmap.md`.

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
assert apb_read_waits in apb_checks, line 83
  clock     @(posedge PCLK) disable iff (!PRESETn)
  expr      PSEL && !PENABLE && !PWRITE && PADDR[7:4] == 0 && PADDR[1:0] == 0 |=> (!PREADY)[*2] ##1 PREADY
  s1        PSEL && !PENABLE && !PWRITE && PADDR[7:4] == 0 && PADDR[1:0] == 0
  s2        (!PREADY)[*2]
  s3        ##1 PREADY
  signals   PCLK:1 PRESETn:1 PSEL:1 PENABLE:1 PWRITE:1 PADDR[>=8]:8 PREADY:1
```

`sva eval` runs them over a dump: signals resolve under `--scope` (then the scopes above it; `--resolve scope`: only the
clock, as when the page binds), values are sampled just before each clock edge with x and z kept, every cycle starts an
attempt, sequences run as threads (ranges, repetitions, `and` / `or` / `intersect` / `within` / `throughout` /
`first_match`), `disable iff` ends the alive attempts. It prints one line per assertion and writes the results JSON the
viewer will draw: per assertion the counts, every non-vacuous attempt with its steps (`[["s1", 52]]`), the cycle and
reason of a failure, and a per-cycle lane. Each example has one deliberately wrong assertion, so the failure trace
shows:

```
$ sva eval --waves BUILD/examples/apb/apb.fst --scope apb_tb --sva examples/apb/apb_tb.sv --sva examples/apb/apb.sva --out apb.json
apb_setup_then_access assert 19 attempts: 3 pass, 0 fail, 16 vacuous, 0 active, 0 disabled
apb_read_waits        assert 19 attempts: 1 pass, 0 fail, 18 vacuous, 0 active, 0 disabled
apb_demo_no_wait      assert 19 attempts: 3 pass, 2 fail, 14 vacuous, 0 active, 0 disabled · first fail at cycle 10 (105 ns): expected PREADY at cycle 10
apb_cov_read_wait     cover  1 match in 19 attempts · first at cycle 12 (125 ns)
…
```

The same engine runs in the page as WebAssembly (`wavefw/sva.js`: `evaluate(parsed, sampler)` over the viewer's rows or
WaveJSON `tv` transitions): one assertion over 32 768 clock edges in about 70 ms.
