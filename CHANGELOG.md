# Changelog

Versions have two numbers, `MAJOR.MINOR`. A version is a merge into `dev` (tagged `dev/vMAJOR.MINOR` there),
published as one commit of the public branch `master` tagged `vMAJOR.MINOR`; the work in between lives on a branch. The version is in `VERSION`, in `wavelens.js` (`WaveLens.version`) and in what the `sva` CLI writes
into a report; `make unit` checks that they agree with the top entry here (DEVELOPMENT.md § Versions). The tags of
0.1–0.8 were put on the commits that ended those stages, after the fact.

## 0.27 — 27 October 2026

A Questa 2023 VCD as the user's simulation writes it: its enums at their own width, and the dump cut off at its end.

- **A glued vector of any declared code.** Questa writes an enum declared `reg [2:0]` in 32 digits glued to its code
  all the same: read as the digits before a declared code, cut to its width (0.26 took only the code of that width).
- **A dump cut off at its end** (the simulator still writing it) is read up to the cut: a last value without its code,
  or a last time cut short (`#1` after `#10`), is left out with a note — the page, the tools and `sva fst`, which wrote
  no FST of it before (the VS Code tab had nothing). A time that goes back before the end stays an error.
- `tests/unit/vcd/cut.vcd`, `cut_time.vcd`; `glued.vcd` with an enum at its own width.

## 0.26 — 27 October 2026

The values of a Questa 2023 VCD's integers: written without their `b`, glued to their id codes.

- **A vector glued to its code.** Questa 2023.3 writes the value of an integer (an enum variable's code) as its digits
  glued to its id code, `00000000000000000000000000000001A&`, no `b`, no space; every reader left it out as a bit of a
  code no `$var` declares, and the FSMs of such a dump stayed `x`. The page, the tools and `sva fst` now read it as the
  digits of a code declared that wide (a note says it once); `sva eval` and `sva vcd`, which read a VCD through
  wellen (it stops at the first one), read an FST of it written in the temporary directory.
- `tests/unit/vcd/glued.vcd`: such a VCD.

## 0.25 — 27 October 2026

The FSMs of a Questa 2023 VCD by name: an enum the simulator wrote as `integer 32`.

- **An enum on an integer of the dump.** Questa 2023.3 dumps a variable of an enum type as `integer 32`, its code the
  value (2021.1 writes `reg [2:0]`); every FSM of such a VCD was left a number ("32 bits in the dump, 3 in the types").
  An integer wider than the enum its types give it now takes the enum's labels by the codes and is an FSM — in the
  viewer and the VS Code tab, `svtypes.py check`, `make html` and `sva fst` (its enum table on the integer's width). A
  `reg` of another width stays a number. The log says how many, a value that is no code of the enum (a number then),
  and only `x` in the dump (a VCD of `wlf2vcd`, which loses the values of enums); **Type…** says it of a signal.
- **No note for a real of the design** (`Floating point type`: an analog model's parameters, hundreds of notes).
- `tests/unit/types/int_enum.vcd` with its types: such a VCD to try it on.

## 0.24 — 27 October 2026

A log under the waves: what the page read and did, and what went wrong, a JSON file's error at its line and column.

- **The log** (the setting `log`): a strip under the viewer, at the window's foot while it is in sight, folded to its
  last entry with the errors and warnings counted, opened by a click or by an error; **Problems**, **Copy**, **Clear**.
  A dump read (signals, timescale, time; the reader's notes with their lines), the types or sources taken (typed paths,
  notes, signals left as numbers for another width, another run), Load… / Save / Save page, Compare…, the signals of a
  large dump read later. A dump opened again or Sources… keep it; in VS Code its errors go to *WaveLens: Show the log*.
- **A file that is not JSON says where**: a types file or a saved state, `name:line:column`, the line and a caret under
  the column; an empty file said so. `svtypes.py` and `mkconfig.py` say the same on the terminal. In VS Code a types
  file beside the dump that is not JSON was a toast only.

## 0.23 — 25 October 2026

A large dump opens at once in VS Code: every module and signal, the values of the ones you open read then.

- **A large dump read as it is needed** (VS Code, `wavelens.lazy`; auto: an FST of 4 MB, a VCD of 64 MB and more): the
  tab gets the header of the dump's FST — every module and signal, the top level open, its modules folded — and reads
  the signals on the screen from it as you open them (`reading…` for a moment); a VCD is made an FST once. A dump of
  643 MB: its modules in 0.3 s instead of its whole text read twice and cut to `dumpBudget` (which left modules out of
  the tree). Assertions, the FSM panel and `fsm_stats`, edge search, pictures read what they need first; the values
  are the ones the whole dump gives.
- **`sva vcd --header`, `--codes FILE`**: of an FST its declarations only, or the variables of some id codes with
  their changes.

## 0.22 — 25 October 2026

A VCD as an FST of our own with its FSM states kept, bookmarks that bring back the screen where they were made, the
markers and bookmarks in a list to step through.

- **`sva fst`: a VCD as an FST** beside it (`tb.vcd` → `tb.fst`), the way GTKWave's `vcd2fst` writes it, and with what
  `vcd2fst` drops: the enum tables of FSM states and their references, the other attributes, the header's comments,
  VHDL's 1-bit values; the FSM states of the design's types file (`tb.types.json`) written as the FST's enum tables, so
  GTKWave and Surfer show the state names. VCD and FST give one WaveJSON: no `$timescale` is 1 ps, an id code at another
  width a signal of its own, a `$var port` a wire. A log at the line (`tb.vcd:120: …`, five of a kind then a count,
  progress on large dumps), a part file of each run's own. VS Code **Convert to FST** (the explorer's menu, the tab),
  the MCP tool `wave_to_fst`, `make fst WAVES=…`. Tested against `vcd2fst` on generated VCDs and every fixture.
- **A bookmark keeps the screen.** Made with `m`, **Bookmark here** or a range, it remembers the row at the top of the
  waves; going to it (`1`–`9`, `]m [m`, the list, the command's `go`) scrolls that row to the top again (the way to it
  and to its signal opened), its time `bookmarkLeft` (0.2) from the left, the span you have; the list's cursor button
  takes the screen of now.
- **gm / Markers…** lists the markers and the bookmarks over the waves: ↑ ↓ step through them, the waves follow.
  **Bookmark here / Marker here** ask their text in a small box where you clicked; the FSM panel's details take the keys.
- **CI on this machine:** `.github/workflows/check.yml` runs `make check` on a self-hosted runner.
- **Review 2026-10-25** (Codex Astra, Fable, a verdict): its findings closed before this version
  (`docs/reviews/review-2026-10-25`).

## 0.21 — 24 October 2026

The panels and the scroll made firm, and the tests of review VI: what the gate checks now fails when the code is wrong.

- **The panels.** Modules and State machines keep the keys wherever you click in them (↑ ↓ Home End go on in the
  tree from a button too); any edge or corner sizes them, never past the window; they open again where they were, at
  their size, also after Sources… or ⟳; the narrow screen's drawer keeps its own size.
- **The time axis stays in sight.** With the page, down to the last rows under the sticky bar; in the rows' own box,
  the box is no taller than the window under the bar (120 px at least) and its end does not scroll the page on; the
  wheel over the rows brings the bar back when the page is past the viewer's top; shift+wheel is a pan only.
- **make vsix** writes `wavelens.vsix` (the same install line each time) and its copy `wavelens-<version>.vsix`.
- **Tests.** `svaverify.py` fails on an assertion left out beyond each example's list; the page's assertions against
  `sva eval` attempt by attempt; 40 generated VCDs against a model and the tools, read in byte pieces and cut at
  every byte; a contract of the types for the Python and page twins and 200 generated cases (it found Python taking
  an enum whose keys do not fit the width: fixed); the FSM panel's `fsm_go` and its Only / Add / undo / Save
  sequence; `make shots-check` fails on a picture that changed or was not committed (`tests/pngdiff.py`, the visual
  set `tests/visual`); time and memory budgets; `make unit-shuffle`; the VS Code e2e takes the results of its own run
  only, every check named.
- **Docs.** The FSM panel on docs/index.html and in the VS Code README, the guides' pictures made again (their bar had
  no Sources…).

## 0.20 — 24 October 2026

FSM states and structs of a VCD from the design's own types (Questa or Verilator), the state machines panel with each
FSM's states, changes and diagram; the theme and the version in the bar; tests that hold the bytes the tools write.

- **Types by path.** `<dump>.types.json` beside a VCD — Questa's `describe` (`tools/questa/wavelens_types.tcl`,
  `make questa`) or `verilator --json-only` (`svtypes.py verilator`; in VS Code **Make the types with Verilator**, no
  Python needed) — gives each signal the enum or struct of its own path, only where the width fits: packages,
  includes, arrays, nested structs, enums up to 64 bits. `mkconfig.py --types` (`--update` follows the file),
  `svtypes.py check`, a `"map"` of roots (`--types-map`, `--map`), the run's fingerprint (a file of another day, an
  instance the dump does not have). **Type…** on a name says where its labels come from.
- **State machines.** A panel of the FSMs in the tree of their modules with the state at the cursor: go to one, Only
  FSMs or add them to the view; its details — the states (entries, time held, never reached, values not in the
  table), the changes, a diagram — and a click takes the cursor to the next entry (shift: the previous); the right
  button and a box to pick them; the commands `fsm`, `fsm_stats`, `fsm_go`, `types`.
- **The bar.** ◐ switches the theme (in VS Code: its list of themes); the version with the branch and the commit the
  page was made from. VS Code keeps ctrl+G (`wavelens.keysToVSCode`); `gl` opens the groups list.
- **Big dumps.** Open… and Compare… read a VCD in pieces, never all of it in memory; `vcd2wavedrom.py` and
  `mkhtml.py` take less time and half the memory on a big dump, the bytes the same.
- **Tests.** Goldens of the bytes the converter writes (`make unit-bless`); `make check` builds the examples before
  the engine's tests and fails on a missing dump, and checks that the committed `sva.wasm.js` and
  `bin/linux-x86_64/sva` are the build of `sva/`; the VSIX's files; the reload in VS Code by its new values.
- **Fixes.** A `$comment` naming `$enddefinitions` in a header, 64-bit enum tables of an FST, labels that look like
  numbers in an FSM's states, a types file's own labels kept before the file's (and said so), `rtl/*.sv` typed in VS
  Code expanded, a bad `"map"` an error in the page as in Python.

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
