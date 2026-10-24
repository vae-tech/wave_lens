# Changelog

Versions have two numbers, `MAJOR.MINOR`. A version is a merge into `dev` (tagged `dev/vMAJOR.MINOR` there),
published as one commit of the public branch `master` tagged `vMAJOR.MINOR`; the work in between lives on a branch. The version is in `VERSION`, in `wavelens.js` (`WaveLens.version`) and in what the `sva` CLI writes
into a report; `make unit` checks that they agree with the top entry here (DEVELOPMENT.md § Versions). The tags of
0.1–0.8 were put on the commits that ended those stages, after the fact.

## 0.19 — 24 October 2026

The waves in VS Code in its theme and with the dump's log, the names' own menu, state names of a VCD from the
SystemVerilog sources; fixes in the assertions' results, the bus decoders and the tools.

- **VS Code.** `wavelens.theme`: auto, vscode (the colours and fonts of VS Code's theme), light, white, dark, picked
  with a preview on the open tabs (**Choose the theme of the waves**). The dump's log: what the reader noticed (a code
  no `$var` declares, more bits than the variable has, a scope left open, the cut of `dumpBudget` …) by its line in
  the output channel WaveLens and in the Problems panel; an error it cannot read past says its line.
- **State names from the sources.** A VCD has no enum tables (Questa writes none): **Sources…** in the bar's dump
  group reads `typedef enum` / `typedef struct packed` from `.sv` files and names the state buses and the struct
  fields; in VS Code the workspace's sources do it at each read (`wavelens.sources`). No guesses: scoped
  declarations, a table only where its values fit the width.
- An integer / int / shortint / longint / byte variable without an enum table reads as signed decimal (Questa writes
  an enum on int as `integer`).
- **The names' menu.** The right button on a name opens the row's menu, as on the waves; a row of your groups moves
  up, down, to the top or the bottom of its group, a group's header among yours.
- **Fixes.** The assertions' results kept in the browser are of the waves they were evaluated on; AXI3 bursts by
  WID, APB / Wishbone transfers that do not end, an ack in its request's cycle; a failing FST converter is an error;
  MCP extrema by the radix's numbers; a slow Open… no longer lands over a later one, a compare that fails says which
  one stays, a width that is not a number of bits is 1; `make check` builds the fixtures before the unit tests.

## 0.18 — 23 October 2026

The project renamed to WaveLens; the guides for the first public release.

- **WaveLens.** The folder `wavelens/` (`wavelens.js`, `wavelens.css`, `wavelens.config.js`), the JS global `WaveLens`,
  `WAVELENS_*`, the localStorage keys `wavelens.*`, the saved state's marker `{"wavelens": "state"}`, the VS Code
  extension `vae-tech.wavelens` (commands and settings `wavelens.*`), the MCP server `wavelens`. No aliases: a page made
  before is refused by `viewedit.py` (make it again), a saved `.view.json` needs its marker renamed, the MCP client and
  the extension are registered again (uninstall the old `wavefw.wavefw`).
- **Guides.** New: [Modules](docs/guides/modules.html), [Compare two runs](docs/guides/compare.html),
  [Commands and scripts](docs/guides/commands.html), [VS Code](docs/guides/vscode.html). The viewer guide shows the
  bar's tools menu, the find's Mask and Select, the newer menu items and keys; every picture made again. The README
  for a first visit: what it does, a minute to try it, what each part needs.
- **Fixes in the docs.** The edge keys are `[e ]e` (or shift+Tab / Tab), not `[ ]`; the keys that ctrl or alt keep
  (ctrl+G, undo, alt+↑ ↓); a measured range is ctrl+drag; the edge style is in the style group; what a page needs for
  assertions and bus transactions (`sva.wasm.js`, `sva.js`, `bus.js`); the `sva` CLI's path in the repository; the VS
  Code settings' defaults.
- The FSM example reads its FST also without GTKWave's `fst2vcd` (through the `sva` CLI), so its states have names.
- `tools/publish.py`: a version as one commit of the public branch `master`, without the internal `prompts/` and
  `docs/reviews/` (DEVELOPMENT.md § Versions).

## 0.17 — 23 October 2026

The Modules panel (a click goes to a module, a box keeps Only the ones you pick), the waves in VS Code over
Remote-SSH / WSL, the bar's tools to taste, the find's Mask and Select.

- **Modules (`t`).** The modules as a tree over the viewer, without signals: per module its own signals and with its
  submodules, ● at the selected signal's module, a fuzzy filter, its own folding; moved by its header, sized by its
  corner, a drawer on a narrow screen. A click (Enter) goes to a module: opened, shown again when hidden, its first
  signal in the middle.
- **Only.** A box over names (ctrl+click / Space, shift+click, Only matches) keeps only those modules on the waves,
  with their submodules; the modules between them stay as headers, every other module goes. The modules the box
  names open (the nested ones too), the ones under them keep their folding. **Only: N modules ‖** in the bar pauses it,
  ▶ resumes, ✕ clears; a click on a module outside it pauses it. A layer over Hide: the find counts what it leaves
  out, the picture, WaveDrom, Paint, `]d` and the assertions' steps take only what is in the view; in the saved state,
  Save page and undo. The command `only modules? on? clear? open?` (page, `viewedit.py`, MCP `view_edit`).
- Designed and reviewed with Codex in six rounds.
- **VS Code over Remote-SSH / WSL** (`vscode/`, `make vsix`): a `.vcd` / `.fst` on the Linux host opens in a tab with
  the viewer (Open in WaveLens / Open With); nothing installed on the host (the static sva turns an FST into VCD text).
  Saving and picking files on the host, the view kept per dump, ⟳ after a new simulation (or at once), VS Code's
  theme, the viewer's keys kept from VS Code, the clipboard; an agent's `wavemcp.py` connects the tabs, `view_live`
  with a dump opens it in VS Code. The page's VCD reader reads the FST enum tables (FSM states by name). Tested in a
  real VS Code of Windows connected to WSL (`make vscode-e2e`); the plan reviewed with Codex.
- **The bar's tools to taste.** The right button on the bar: its tool groups (cursor, find, expression, list …) with
  a tick each, **Show all**, **Hide all**; a line with none left goes, `/` still floats the find (`toolsHidden`, kept
  in this browser and in the state).
- **Find: Mask and Select.** **Mask** keeps only the found rows on the waves with the modules on the way (`findMask`;
  the command `find … mask?`); **Select** selects the found signals (ctrl+click: adds them), so the right button takes
  them all (a new group, colour, radix, hide). The second background of neighbouring modules is 40% lighter. In VS
  Code the keys in a tooltip are readable again (its webview gave `kbd` and `code` its own colours).

## 0.16 — 22 October 2026

Fixes from the third review with Codex: the dumps read as a simulator wrote them, the SVA core, the viewer at scale, MCP.

- **Dump readers.** A value change on an indented line, after a tab or on the next line is no longer lost; `realtime`,
  `shortreal` and `real_parameter` are reals; a vector declared in parts (`data [7:0]` + `data [15:8]`, bit selects)
  is one vector merged bit by bit; two bits under one id code both follow it.
- **FST as fst2vcd writes it.** `sva vcd` reads an FST with fst-reader: the FST's names (bit selects glued, ranges
  apart, escaped names), every time of its table to the end of the dump, strings escaped as fstapi does. A VCD and
  its FST give the same WaveJSON again.
- **SVA:** `$past(e)` and `$sampled(e)` take the width of their argument, as a simulator does (`$past(a + b)` of two
  8-bit signals no longer keeps the carry).
- **Viewer:** compare, analog and the ≠ marks fast on thousands of signals and million-toggle clocks; Clear of the
  bookmarks keeps your markers; a batch of commands lays out what it hid before a picture; `cycleZero` a time.
- **MCP and tools:** `wavemcp.py` answers every request and checks the arguments against the schemas; a bus select
  has its own edges; pagination keeps every change; `view_get` → `set_state` keeps the times. A value saying
  `<!--<script>` no longer swallows the page.

## 0.15 — 21 October 2026

Five features from a review by Codex, each reviewed again by it: cycles, undo, your order, a page to send, two runs side by side.

- **Clock cycles.** The right button's **Cycles ▸**: a clock's rising edges numbered from cycle 0 in a band under the time
  axis; the cursor's cycle in the title (`cycle 147 ↑clk`), the second cursor's Δ in that clock, `c147` in the cursor
  field; cycle 0 at any edge. Settings `cycles`, `cycleClock`, `cycleZero`; the command `cycles`; drawn in the pictures.
- **Undo and redo** of what you edit — bookmarks, arrows, markers, groups, colours, radix, analog, hidden rows,
  highlight, gaps, cycles: **ctrl+Z**, **ctrl+shift+Z** / **ctrl+Y** (ctrl+Я on a Russian layout), **↶ ↷** in the
  bar's title line. A step is one action (a batch of commands, a drag, a field left); the cursor and the window are not
  steps.
- **Your groups in your order**: **alt+↑ / alt+↓** move a signal in its group (alt+shift: the group), a drag in the
  names moves signals and groups; `group … move`.
- **Save page**: the page as one file with your view in it (every viewer's state in its edits, the live link left
  out): whoever opens it sees what you saw. On a page that is all in itself (`make html`); setting `savePage`.
- **Compare two runs**: **Compare…** reads a second VCD over the waves; where it differs a red band and ≠, a signal it
  lacks struck; **]d / [d** to the differences.

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

- `view.run([{op, …}])` (`wavelens/src/edit.js`): bookmarks with their texts, arrows, markers, your groups, highlight,
  paint, selection, hidden and folded rows, radix, analog, cursors, window, range, order, style, find, gaps, edges;
  read: state, rows, a picture. Names by path, name, path tail or `*`; a bad command says why, the rest run.
- Your markers (a dashed line with a label) and your groups (a folder of signals at the top of the names) in the menu,
  the lists under the waves and the saved state (version 3).
- `tools/viewedit.py`: the same commands on a page's edits (a revision the viewer applies when it opens) or a
  `.view.json`; the smoke test holds the two to the same state.
- `tools/wavemcp.py`: `view_edit`, `view_get` (a PNG of the screen too), `view_live` — a page connected on 127.0.0.1
  shows the agent's edits at once and the person's go back to the agent; a closed page: its file.

## 0.11 — 21 October 2026

An MCP server: the tools of WaveLens for an AI agent.

- `tools/wavemcp.py` (standard library, stdio): `wave_info`, `wave_signals`, `wave_values`, `wave_changes`,
  `wave_sample` (a row per clock cycle, sampled as SVA samples), `wave_find` (an SV expression or sequence per cycle
  through the sva engine, or a signal's edges and values), `wave_stats`, `sva_check` (failures with their cycles and
  times), `wave_page` (a viewer page or WaveJSON to show a person); names by a tail of the path, times in ns, answers
  cut at a limit with how to go on; `--call TOOL JSON` from the shell. Claude Code: `claude mcp add wavelens -- python3
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
- Tests: a smoke table of 206 unit cases (`WaveLens.internal`), `make sva-verify` (the examples' checkers in Verilator
  `--assert` against `sva eval`: 26 assertions agree).
- Docs: the SVA subset's skipped, accepted and limited constructs; ENGINE.md by the code; prerequisites; licences.
- `VERSION` and this changelog; `WaveLens.version` follows the project (it counted 1.x on its own before).

## 0.8 — 18 October 2026

The viewer as a wave window (`wavelens.js` 1.9 at the time): find options (Aa, Full, `.*`), ctrl+F, the menu on the
highlighted rows; the bar's tools one line per kind of work and a grey light theme; Save as WaveDrom; a run of
signals and a box of time and signals; a second cursor, value and X / Z search, float and fixed-point radixes, enum
colours; the analog style; packed structs as rows; a VCD opened in the page (Open…, drop, ⟳) and `wavelens/viewer.html`.

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
`wavelens.js` split into `src/*.js`; the viewer's plugin API (tokens, tools, events) with `sva.js` on it only.

## 0.4 — 18 October 2026

SystemVerilog assertions (stages 3–8): a Rust engine for a subset of IEEE 1800 SVA (parser, expansion, evaluation by
threads, results JSON with a schema), the `sva` CLI (`sva parse`, `sva eval`, `sva report` with Markdown, HTML, JUnit),
the same engine as WebAssembly in the page: the assertion list, binding to instances, evaluation on demand, attempts,
steps and failures drawn on the waves, statistics, the failure list, reports; two reviews and their hardening.

## 0.3 — 17 October 2026

The project's shape (stages 1–2): `wavelens/ tools/ examples/ docs/ tests/ work/`; the APB, AXI-Lite and FSM examples
with Verilator testbenches (`make examples`); README with screenshots (`make shots`); colours per group.

## 0.2 — 17 October 2026

An interactive viewer: highlight of instances, expand / collapse, edge search, bookmarks with notes and arrows (in
lanes), FST dumps and FSM enum labels, the built-in dump reader (wavepeek optional), modules shaded, fuzzy find with
highlight / open / paint, Esc everywhere, the cursor group (a time, a span around it).

## 0.1 — 17 October 2026

The first version: `wavelens.js`, a WaveDrom-format canvas viewer and static SVG, the VCD → WaveJSON tools and config
files.
