# Changelog

Versions have two numbers, `MAJOR.MINOR`. A version is a merge into `main` tagged `vMAJOR.MINOR`; the work in between
lives on a branch. The version is in `VERSION`, in `wavefw.js` (`WaveFW.version`) and in what the `sva` CLI writes
into a report; `make unit` checks that they agree with the top entry here (DEVELOPMENT.md § Versions). The tags of
0.1–0.8 were put on the commits that ended those stages, after the fact.

## 0.9 — 20 October 2026

The second global review and its cycle (stage 12): 71 of its 75 findings fixed.

- Gates that hold: a failing smoke section is a FAIL with a picture, not a traceback; `make shots` deterministic and
  `shots-check` in `make check`; the Windows CLI described as it is.
- The Python tools: one VCD reader rule for the tools and the page (time order, duplicate paths, escaped names, VHDL
  values, `$comment` in the body, real / string / event variables); `WaveError` instead of tracebacks; settings
  validated; 117 unit tests (`make unit`).
- The SVA engine: no panic on any input (UTF-8 lexer, a fuzz test, a macro budget), clock edges as IEEE 1800 9.4.2
  per time step, nullable repetition, checked requests, the term arena collected; `engine.rs` and `parse.rs` split;
  evaluation goldens; an error outside the subset names `docs/sva/LANGUAGE.md`; `sva report -h`.
- The viewer: listeners per viewer, Tab leaves the canvas, the second cursor by an edge index (draw 8 → 0.9 ms on
  400 000 clock changes), exact fixed point, the saved state checked and complete, the plugin API (`moveTo`, `fold`,
  `registerDefaults`) used by `bus.js` and `sva.js`, one `isEdge` and `stepTo`, ranges and Δ in the SVG; JS lines
  ≤ 160 columns.
- Tests: a smoke table of 206 unit cases (`WaveFW.internal`), `make sva-verify` (the examples' checkers in Verilator
  `--assert` against `sva eval`: 26 assertions agree).
- Docs: the SVA subset's skipped, accepted and limited constructs; ENGINE.md by the code; prerequisites; licences.
- `VERSION` and this changelog; `WaveFW.version` follows the project (it counted 1.x on its own before).

## 0.8 — 18 October 2026

The viewer as a wave window (`wavefw.js` 1.9 at the time): find options (Aa, Full, `.*`), ctrl+F, the menu on the
highlighted rows; the bar's tools one line per kind of work and a grey light theme; Save as WaveDrom; a run of
signals and a box of time and signals; a second cursor, value and X / Z search, float and fixed-point radixes, enum
colours; the analog style; packed structs as rows; a VCD opened in the page (Open…, drop, ⟳) and `wavefw/viewer.html`.

## 0.7 — 18 October 2026

Bus transactions (stage 11): AXI4, AXI4-Lite, AXI-Stream, APB, AHB, Avalon-MM / ST, Wishbone, OBI decoded from the
dump and drawn as rows. The viewer's state saved to a file and loaded; highlight tones; keys as in Questa's wave window
(vim for the lists); the edge style in the bar and a cursor that snaps to edges; a measured range and the right
button's menu (picture, radix, hide, fold, bookmark); tooltips with the keys on every control and a ? box.

## 0.6 — 18 October 2026

Expressions and Why (stage 10): an expression in the bar finds the times it becomes true and draws as a row (ƒ); the
selected attempt of an assertion taken apart into its booleans, cycle by cycle. Assertions edited in the page (✎) and
read again from the disk (⟳, Watch); the assertions as a table with attempts as brackets; build products in `out/`
and the prebuilt `sva` CLI in `bin/` (`make dist`).

## 0.5 — 18 October 2026

The first refactoring cycle (stage 9.1, 9.4) after the first global review: repository hygiene, LICENSE,
`make check / clean-all / fmt / lint`; smoke with skip accounting, `--strict`, `--only` and a synthetic big page;
conformance against stock WaveDrom; the SystemVerilog style guide; README split into USAGE and DEVELOPMENT;
`wavefw.js` split into `src/*.js`; the viewer's plugin API (tokens, tools, events) with `sva.js` on it only.

## 0.4 — 18 October 2026

SystemVerilog assertions (stages 3–8): a Rust engine for a subset of IEEE 1800 SVA (parser, expansion, evaluation by
threads, results JSON with a schema), the `sva` CLI (`sva parse`, `sva eval`, `sva report` with Markdown, HTML, JUnit),
the same engine as WebAssembly in the page: the assertion list, binding to instances, evaluation on demand, attempts,
steps and failures drawn on the waves, statistics, the failure list, reports; two reviews and their hardening.

## 0.3 — 17 October 2026

The project's shape (stages 1–2): `wavefw/ tools/ examples/ docs/ tests/ work/`; the APB, AXI-Lite and FSM examples
with Verilator testbenches (`make examples`); README with screenshots (`make shots`); colours per group.

## 0.2 — 17 October 2026

An interactive viewer: highlight of instances, expand / collapse, edge search, bookmarks with notes and arrows (in
lanes), FST dumps and FSM enum labels, the built-in dump reader (wavepeek optional), modules shaded, fuzzy find with
highlight / open / paint, Esc everywhere, the cursor group (a time, a span around it).

## 0.1 — 17 October 2026

The first version: `wavefw.js`, a WaveDrom-format canvas viewer and static SVG, the VCD → WaveJSON tools and config
files.
