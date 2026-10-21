# Changelog

Versions have two numbers, `MAJOR.MINOR`. A version is a merge into `main` tagged `vMAJOR.MINOR`; the work in between
lives on a branch. The version is in `VERSION`, in `wavefw.js` (`WaveFW.version`) and in what the `sva` CLI writes
into a report; `make unit` checks that they agree with the top entry here (DEVELOPMENT.md § Versions). The tags of
0.1–0.8 were put on the commits that ended those stages, after the fact.

## 0.14 — 21 October 2026

Fixes from a review by Codex: what a page shows is what the dump holds.

- **Known bits among x / z are kept.** A bus value whose nibble mixes x / z with known bits (`10x1`) was x in the
  page: its fields, radix `bin`, the page's assertions (which could disagree with `sva eval`) lost bit 0. It is now
  written in `tv` as `'b` and its bits; every other value stays hex, so the pages of clean dumps are unchanged. The
  value search and `wave_find` take a four-state literal bit for bit (`'b10x1`, `8'hx5`, `4'bx1`).
- **Save / Copy WaveDrom** keep at most 2048 cycles and say where they stop (head, foot, toast; `view.run`'s `cut`).
- **Steps on long runs** (edges, bookmarks, values) no longer skip events next to the cursor: the rounding step was
  1 ps at 1 ms of simulated time.
- **Signals left out of a page are named**: `meta.omitted` lists the dump's signals the config hid (`"show": false`) or
  the `dumpBudget` of a VCD opened in the page cut; the find says `no match · 1 not in the page` and how to add them.

## 0.13 — 21 October 2026

Where the rows scroll, switched on the fly; your groups one key away.

- **Scroll: window / page** in the bar's title line: the rows in a window of their own, or with the page — then the
  bar sticks to the top while its rows go by, the time axis under it; **▴** folds the tools to the title line (setting
  `toolsFolded`). Both kept in this browser, in the saved state, and the command `layout` (`view.run`, `viewedit.py`,
  `view_edit`).
- Your groups: the right button's **Groups ▸** (into a group, a new one, out, delete, go to one); **ctrl+G** lists them
  and goes to one (opened, in the middle, its first signal selected); `group … go` does it by command.
- A name of several signals takes the one nearest the top when that is one (as the MCP tools); switching the scroll no
  longer resets the sort.

## 0.12 — 21 October 2026

The viewer's commands: what its buttons do, a script, a file or an AI agent does by name — live in an open page.

- `view.run([{op, …}])` (`wavefw/src/edit.js`): bookmarks with their texts, arrows, markers, your groups, highlight,
  paint, selection, hidden and folded rows, radix, analog, cursors, window, range, order, style, find, gaps, edges;
  read: state, rows, a picture. Names by path, name, path tail or `*`; a bad command says why, the rest run.
- Your markers (a dashed line with a label) and your groups (a folder of signals at the top of the names) in the menu,
  the lists under the waves and the saved state (version 3).
- `tools/viewedit.py`: the same commands on a page's edits (a revision the viewer applies when it opens) or a
  `.view.json`; the smoke test holds the two to the same state.
- `tools/wavemcp.py`: `view_edit`, `view_get` (a PNG of the screen too), `view_live` — a page connected on 127.0.0.1
  shows the agent's edits at once and the person's go back to the agent; a closed page: its file.

## 0.11 — 21 October 2026

An MCP server: the tools of wavefw for an AI agent.

- `tools/wavemcp.py` (standard library, stdio): `wave_info`, `wave_signals`, `wave_values`, `wave_changes`,
  `wave_sample` (a row per clock cycle, sampled as SVA samples), `wave_find` (an SV expression or sequence per cycle
  through the sva engine, or a signal's edges and values), `wave_stats`, `sva_check` (failures with their cycles and
  times), `wave_page` (a viewer page or WaveJSON to show a person); names by a tail of the path, times in ns, answers
  cut at a limit with how to go on; `--call TOOL JSON` from the shell. Claude Code: `claude mcp add wavefw -- python3
  -I tools/wavemcp.py`; Codex: `codex mcp add …`.
- `tests/mcp_bench.py`, `make mcp-bench`: eight tasks with known answers (the APB and FSM examples, a generated 3.5 MB
  dump) solved through the tools by a script (in `make check`), or by `claude -p` / `codex exec` agents with the server
  and without it, tokens counted: Claude Code (Sonnet 5.5) −24 % tokens and −28 % cost with the server, every answer
  right; Codex +33 % through MCP (it defers MCP tools), −3 % through `wavemcp.py --call` in its shell; the big savings
  on assertions and FST dumps, none on one number a short parser gets.

## 0.10 — 21 October 2026

Gaps: a long range of rare transfers as its transfers side by side.

- The pictures (PNG / SVG) and WaveDrom saved from the viewer's menu, and static SVGs, leave out the idle stretches
  where no signal but a clock changes (`gaps`, `gapIdle`, `gapKeep`; the signals they follow, the clock they count,
  the signals counted in a gap, the texts and the line of a break: `gapSignals`, `gapClock`, `gapAux`, `gapOnly`,
  `gapCount`, `gapLine`); the menu's **Gaps ▸** submenu; kept in the browser and the saved state.
- `vcd2wavedrom.py --auto-gap IDLE[:KEEP]`: the same cut in `--clock` mode, one `|` cell per gap.
- A measured range and the second cursor show the frequency of a period that long (`Δ 40 ns / 25 MHz`);
  `menuTipDelay`.

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
