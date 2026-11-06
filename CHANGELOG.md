# Changelog

Versions have two numbers, `MAJOR.MINOR`. A version is a merge into `dev` (tagged `dev/vMAJOR.MINOR` there),
published as one commit of the public branch `master` tagged `vMAJOR.MINOR`; the work in between lives on a branch. The version is in `VERSION`, in `wavelens.js` (`WaveLens.version`) and in what the `sva` CLI writes
into a report; `make unit` checks that they agree with the top entry here (DEVELOPMENT.md § Versions). The tags of
0.1–0.8 were put on the commits that ended those stages, after the fact.

## 0.50 — 6 November 2026

The review of 0.46–0.49 (`docs/reviews/review-2026-11-06-latest/`): a slice compared with the dump at its place, the page
owns A, the snapshot fills the rows a run lacks, a piece of waves carries its own state only.

- **A slice against the dump or a whole run is read at its place** (B-01): a slice made A with now as B (or the dump A, a
  slice B) compared the slice's 0 with the dump's 0 — identical waves said "differ". Now B is offset by the slice's start
  (`sva runs diff`: `(B −20 ns)`, JSON `offset`; the page's status: `B's … : a slice at its place`); two slices still
  compare from their first samples. While a slice is A the view moves by its start only between a slice and a whole one.
- **Edits on a run that lacks a row stay** (A-03): the view taken for the next run filled the missing rows by replacing
  every row's colour, radix, groups with the snapshot's; now only the rows the waves lack are taken from it.
- **The page names A** (A-05, B-04): Compare…, keep with a window, Save as FST… and the runs' compares send the run shown;
  the extension no longer guesses it from its own `shown` (a read that failed left the two apart: a slice of the wrong
  file). A file of Compare… is compared again with a new A (B-03: dropped without a word before).
- **now among the Bs while A is a run** (B-06, B-07): `sva runs diff --against RUN` and Δ all list it, `]r` reaches it;
  Δ all's numbers survive ⟳ (B-08); a slice of a run records its dump's size, time and file name (B-02).
- **A piece of waves** (A-07, B-05): its state is its rows' look and your marks (`PIECE_KEYS`) — no longer the saver's
  style, tools, find, FSM layer applied to whoever opens it; `r` reads a piece Load… opened; Load… of a piece in a VS Code
  tab opens it in a tab of its own instead of replacing the tab's dump.
- The hex fields of the colour pickers without a `MutationObserver` on the viewer (A-06). New checks for each of the above,
  the hex fields, the chord markers' edge snap, the `--zero` writer and the enum tables of slices.

## 0.49 — 6 November 2026

Slices: a range of the waves kept as a run of its own whose times start at 0, or saved as an FST; pieces compared with each
other from their first sample.

- **Slice ▸ in the right button's menu over a range** (VS Code). **Keep as a slice (Runs)** keeps the range of the waves
  shown (the dump, or the run that is A) as a run of its own, every signal, its times from 0: its first sample is 0. Two
  slices (two bursts of one dump, or of two runs) compared as A and B line up on their first samples; `]w` walks through
  them in one window. The row says `slice 120 ns … 145 ns, from 0`, the name by default `tb.vcd 120 ns–145 ns`. While a
  slice is A the view's times (the window, the cursor, your markers, bookmarks, spans) go with its start, and back on now.
  **Save as FST…** writes the range as an FST file of its own, its times from 0, where the save dialog says.
- **The CLI**: `sva vcd --zero` (a cut's times from 0), `sva fst DUMP --from T --to T [--zero] --out PIECE.fst` (a window of a
  VCD or an FST as an FST, the enum tables and the types file's FSM states kept), `sva runs keep DUMP --from T --to T` (a
  slice: `slice {from, to}` in `runs.json`; a run's FST as DUMP: a slice of that run, of its dump at its time there);
  `wave_runs` `keep` takes `from`, `to`. The extension's runs ops: `keep` with `from`, `to`, and `cut`.

## 0.48 — 6 November 2026

Markers at once, with the mouse: the left button clicked while the right one draws a range.

- **A marker at each click of the left button while the right one is down**, asking nothing: its label the next of `M1`,
  `M2` …, its time as the cursor's (on an edge of the signal there; alt: not). On a signal's row its text goes on the line
  over that row, or under it when over it something is drawn there already (a text, a bookmark, a Δ), so the texts do not
  overlap (both taken: over it); on such a line, on it; on the axis, at the top. The right button released then opens no
  menu (the range stays); the labels, colours and Δ bounds are filled in the Markers list. Each marker is one step of undo.

## 0.47 — 6 November 2026

Colours as hex codes beside their pickers; a piece of the waves saved as `x.wavelens.json` and opened on its own.

- **Every colour picker has its hex code beside it** (Paint, the menus, the lists of bookmarks, markers and groups): the
  code of the colour shown (`#c2255c`), to copy; a code typed or pasted in is applied as soon as it is one (`#c25` too), a
  text that is not one is marked and not applied, Esc puts the picker's code back.
- **Save as WaveLens (JSON)** in the menu of a box selected on the waves (the right button): the selected signals' exact
  changes over the box (the value at its start and every change in it), their colours, radix, enums and groups, and the
  markers, bookmarks, spans and arrows inside it, as `name.wavelens.json`. It opens on its own: Open…, a drop or Load… in a
  page; in VS Code *Open in WaveLens* (or as the editor of `*.wavelens.json`), read whole, never lazy.
- `wavelenscat --check` (in `make check`) catches a name declared at the top of two sources: `wavelens.js` is the sources
  in one scope, and one such name stopped every viewer.

## 0.46 — 6 November 2026

Who is compared with whom: the runs kept, A and B on the list; a walk through the runs (review 2026-11-06, the run pick).

- **The Runs panel names A and B.** The list holds the dump of now (the row `now`: its time and size on the disk) and the
  runs; two rows carry a letter, lit where it is and a button on every row: **A**, the waves shown in the tab, and **B**, the
  run compared with A. The two names stand on the time axis (`A · #3 golden`, also with bands only, B-05) and in the status
  (`A #3 golden ≠ B #1 golden: 4 of 40 signals differ over …`). With three runs kept the list read `#3 tb.vcd · tb.vcd`
  three times under `A · tb.vcd` and nothing said which was compared (A-01, U-01, U-02); a run's second line now says when
  it was kept, the dump's time when it was written earlier ("of a dump of 12:03", `source_mtime`), its size.
- **A: a run's waves shown in the tab** (`w` on a row, its `A`; `]w` `[w` anywhere: now, then the runs, wrapping). The run's
  FST is read on the host as the dump is (converted once; a large one lazy), the view kept — the window, the rows, hidden,
  radix, paint, groups, Only, markers, spans, the panels — and B, if any, compared with the new A: two runs kept are compared
  with each other. With no B (`x`, *no B*) `]w` is the walk through the runs, each one's waves in the same window, nothing
  compared. A run that has not got a row of yours says which, and the row is back on the next run that has it (the view
  taken on now and on each run that had every row of it). ⟳ and a new simulation read the dump of now: A is now again.
- **B is the compare's** (B-01, B-02, B-03): the bar's ✕, `compare off` and Compare… with a file dropped the compare but left
  the run "compared" — its row lit, ⟳ in the panel and a new simulation compared with it again; a saved state did not
  carry it; `]r` `[r` lit one row and left the focus on another. B is now read from the compare (`compare.run` in the saved
  state, the window `runsOver` too) and `]r` moves the focus with it.
- **One compare made by the CLI.** The extension compares A with B by one `sva runs diff DUMP --run B --against A --page`
  (the test-case arithmetic was written twice, in the extension and in the CLI: A-02); `sva runs diff --against RUN` (every
  run, or the ones of `--run`, against a run kept; `--run now` the dump itself), `wave_runs` `against`; Δ all is against A.
- The panel lists once on a reload (B-06); a run asked by its number that the list has not yet is read again (B-07).

## 0.45 — 6 November 2026

A late window of a run read from its block, a run compared by test case, one compare made by the CLI; the leftovers of the
review of the runs (the page ↔ extension protocol in one table, the tests that hold the parts together, what breaks for a
reason other than a code change); a VS Code tab moved to a window of its own reads its dump, a VCD whose codes start with
`s` is read to its end.

- **VS Code: a tab moved to a window of its own reads its dump.** VS Code makes a moved tab's webview again, with the page
  of when the tab opened; over a remote connection (SSH, WSL) its loads from the dump's folder or the converted FST then
  answered 404 ("cannot read x.vcd"). The page now takes the dump from the extension as bytes when its URI does not come
  (said in the log), and the dump's store (the rows, the markers, the look) as it is now, not as it was when the tab opened.

- **The Modules panel's "Your groups whole" is a step of undo with no Only set too**: ctrl+Z undid the change before it.

- **A menu closes when the window loses the focus.** Its listener read the blur's target, the window, as a node: "Failed to
  execute 'contains' on 'Node'" in VS Code's log each time the focus left a tab with a menu open, the menu left open.

- **A VCD whose id codes start with `s` (or `b`, `r`) is cut to its end.** `sva vcd --signals`, `--from`, `sva diff` and
  the runs took the last `#time` of such a VCD for an id code (`b101 s0` then `#50`: `s0` read as a string's value) and
  stopped at its first time; the tail is now read forwards from a line's start, the header's codes no times.

- **`wavelenscat --check` finds a name declared nowhere** (A-09 of the review of the runs): a name read in `wavelens.js`,
  the plugins or the extension's files that nothing declares and no browser or node has (`tools/jsnames.py`, no eslint).

- **One compare, made by the CLI** (A-01, A-02, A-03 of the review of the runs). `sva diff --page` writes the compare in the
  shape a page takes, B's values of the signals that differ in it (at most 32 MiB, else `cutError`): a config's `"compare"`
  (svabuild), VS Code's Compare… and the Runs panel are one call each, the shape and the cut made in one place (the panel's
  compare now carries the notes and segments a config's has). `sva runs` calls the comparison and the FST writer as
  functions, not through argument lists (the signals read once, a case's window set on the options). `sva runs` and
  `wave_runs` find VS Code's `wavelens.runsDir` in the workspace's `.vscode/settings.json` above the dump: the shell, an
  agent and the panel keep and list the same directory.

- **A run compared by test case** (F-02 of the review of the runs, the phase 2 of the runs kept). A run keeps its test cases,
  a name and a window each: cocotb's `wavelens.marks.json` beside the dump (not older than it by ten minutes), `--cases FILE`
  (marks, a list, spans) or, in VS Code, your spans with a label when Keep this dump… keeps it. A span whose name is a case of a
  run (`TC3 ` and ` · PASS` left out, as cocotb's spans are labelled) is compared with that case of the run, wherever it is in
  the run: B offset to it, over the shorter of the two — a click, `]r [r`, Δ all; the window's choice says "· a case", a run's
  row its cases. `sva runs diff DUMP --case NAME` (`--from/--to` the dump's window, else its cases), `sva runs set RUN --cases`,
  `wave_runs` `case` and `cases`; a run without the case is an error on its row.

- **A late window of a run as fast as an early one** (F-01 of the review of the runs). `sva diff --from` and `sva vcd
  --from` read an FST written in several blocks from the block that holds the window on, with every signal's value at that
  block's start (the blocks before it not unpacked; fst-reader skips that frame, so `sva` reads it); `sva runs keep` writes
  a VCD's FST in blocks of 1 MiB (+0.2 %). A window at 1.9 ms of a 2 ms run of a 37 MB VCD: 0.12 s, not 1.3 s, 10 MB, not
  27. `sva diff --json` says `read_from` for each dump. A VCD is still read from its start; so is an FST when a real or a
  string is among the signals (no frame of theirs) or with `--segment`.

- **Tests that hold the readers together** (A-05 part, A-08, A-09 of the review of the runs). One table of times
  (`tests/unit/times.json`) run against the seven readers of a time (the tools, the page's `parseT`, `links.js`, the cocotb
  library, the CLI), each one's own rule for a plain number or a sign written in the table; `wl.measure` refuses a bound
  of `inf` / `nan` / `1e400ns` (taken before: a number NaN went into the marks as JSON's NaN, a text one judged nothing). The extension's unit tests share one fake `vscode`
  (`tests/unit/vscode_fake.js`). `wavelenscat --check` (so `make check`) fails on a key of `WaveView.prototype` defined twice.
- **One rule of naming a signal** (A-07 of the review of the runs). A name means the same row in the viewer's commands (the
  page and `viewedit.py`), a config's `signals` (`vcd2wavedrom.py`, under `--scope` first) and an agent's `wave_*` tools:
  the full path, the row's name, the end of a path, a longer path ending with one, a bit, of several the one nearest the
  top (`tools/common.py` `pick`). Where they differed: a config takes the end of a path (`fifo.count`), a bit (`data[3]`)
  and the nearest of one net (`clk`), and refuses bits a bus has not got; the commands take an array element either way
  (`mem[1]`, `mem.[1]`); an agent takes a longer path ending with one. `wavemcp.py`'s live link is `tools/wavelive.py`,
  `viewedit.py`'s page and config files `tools/wavepage.py` (A-10; every name where it was).
- **One table of the messages between a VS Code tab and the extension** (A-05, T-03, T-05, T-09 of the review of the runs).
  `vscode/protocol.js`: each message of the page, the keys it sends and the answers it gets (the Runs panel's per
  operation). The extension answers a message none of it (an unknown type, a key missing) with an error and goes on; the
  smoke's fake host answers by the table and fails on a message or an answer it does not name; a unit test walks every
  type through the real extension and the CLI. The smoke drives the Runs panel's keys (`k` `e` `a` Delete, Esc in the form
  and in the list, ⟳), the host's errors and a removal not confirmed, each runs message read back with its keys; a run step
  in `vscode/test/e2e.js`; your groups under Only with a copy and a bus's bits in them, the panel's box undone and redone.

- **What breaks for a reason other than a code change** (T-04, T-06, T-07, T-08 of the review of the runs). A flag the
  tools or the extension give `sva diff` / `runs` / `vcd` / `fst` that the CLI's usage does not name fails `make unit`
  (`test_cli_flags.py`). The VS Code extension on a Windows host runs `bin/windows-x86_64/sva.exe` (`make dist-windows`) and,
  with none, says to set `wavelens.sva`; it and `wave_diff` / `wave_runs` read the CLI's JSON after wellen's `WARN:` lines
  (Windows, where sva cannot put them aside). The CLI's lines of progress come from one function (`sva diff --large-bytes`
  shows them on a small dump, for the tests); the next `sva fst` / `sva vcd` removes the part or temporary FST a killed run
  left (its process gone, 10 minutes old). `make unit` says its 10 slowest tests and every skip with its reason; under
  `make check` (or `STRICT=1`) a skip fails unless it is of a program the gate does not build. The smoke's last line counts
  the pages a section opens and says "FAILED: n skipped with --strict" or "all checks passed, n skipped"; `--only` skips
  only the pages its sections read. `rows` after `bits` has its unit test.

## 0.44 — 6 November 2026

The runs kept of a dump: keep a run by hand, compare the run of now with it over one window, in VS Code, the shell and for an
agent; and the fixes of the review of the runs.

- **The runs kept of a dump.** A simulator writes its dump over the last one; now you keep the runs you want to look back at,
  by hand, and compare the run of now with them over one window. In VS Code **Runs…** (`gu`, *WaveLens: The runs kept of this
  dump*): **Keep this dump…** with a name, tags and a comment — the dump as an FST in `.wavelens-runs` beside it (`runs.json`,
  a `.gitignore` of its own; `wavelens.runsDir` elsewhere); a click on a run (↑ ↓, `]r` `[r` anywhere) compares these waves
  with it over the waves in sight or a span of yours, only that window of the run read (`sva diff`, then its values of the
  signals that differ there): the compare's bands, ≠, `]d [d`, A / B / A+B, the view kept from run to run; **Δ all**: every
  run's differences in the window on its row. In the shell `sva runs keep | list | set | rm | path | diff` (a line per run:
  how many signals differ, the first difference); for an agent `wave_runs`.
- **The fixes of the review of the runs** (`docs/reviews/review-2026-11-05-runs`). B-01: `sva runs diff` holds the first
  difference of a run, not every one (`sva diff --limit` bounds the differences held; `only_a`, `only_b` whole whatever it
  is): its memory is `sva diff`'s. B-02: VS Code's tab no longer throws EPIPE when the CLI exits before reading its input (one
  way to run it, its stdin guarded). B-03: a `.gitignore` of `*` only in a directory of runs of its own; a folder of yours gets
  one of the runs' files. B-04: `rm` finds every run first. B-05 … B-12, B-19 … B-21: the panel follows your span by what it is,
  comes back with the dump read again and compares with the run again, lists the runs of this dump (the others counted; `--all`),
  reads the list again for `]r [r` and when `runs.json` changes, compares once the list's keys stop (the compare before
  stopped), says equal or why the run's values are not shown, drops the compare of a run removed, keeps ✎ ✕ in reach of a long
  name, greys Δ numbers of another window. B-10, B-13 … B-18, B-22, B-23: `sva runs` takes DUMP for set, rm, path, keeps a
  run's FST kept again in its directory, checks `runs.json` (a file a plain name, a newer version refused), refuses an empty
  name and the options of another verb, takes `--opt=value`, says a wrong window once, a run that does not cover the window
  "not in this window", the signals of one side and a kind change in its text; old `.part` files swept; `wave_runs` `rm` in ns.
- **onlyGroups and 0.43's leftovers** (the same review). B-08: `]d [d` step to the differences of a group's row that Only keeps
  whole (the rows drawn, not the model's). B-30: `viewedit.py` sets the next Only set's `groups` from a state's `only` as the
  page does. B-24: an array element declared in its own scope (`$scope module ptr` + `$var … [0]`) is `top.ptr.[0]`, found as
  `ptr[0]`, `ptr.[0]`, `top.ptr[0]` by `wave_signals`, `wave_values` and `sva vcd --signals` (one `glued()` rule in the tools
  and the CLI). B-25: a window whose clock starts inside it numbers its first edge 0, as `wave_sample`; the period count with
  `cycleZero` before the window only for a clock running at its start. B-26: `mkhtml --lint-json` of a build that fails in a
  later view keeps the warnings of the views built. B-27: a marks file with a BOM is read (`--marks`, `wave_tests`). B-28: the
  lint `measure-empty` for a measure whose two ends are one time. B-29: a pattern spelling of a row (`wl.note(signal="*PSEL")`)
  at one moment shares that row's lanes.

## 0.43 — 5 November 2026

Your groups whole under Only, and the fixes of the review of 5 November: measures and cycles in a cut window, array
elements either way, the VS Code configuration, the tools of a test run and `viewedit.py` as the page.

- **Your groups whole under Only.** Only (the Modules panel's box, the command `only`) keeps your groups with every signal of
  them, whatever module it is of, folded or open as you left them: a group of signals of several modules stays in full while
  Only keeps a few modules. **Your groups whole** in the panel (the setting `onlyGroups`, true; `only {groups}`) turns it off:
  a group keeps the signals of the modules Only keeps, as before. In the saved state when not the page's setting.
- **The fixes of the review of 5 November** (`docs/reviews/review-2026-11-05`). B-04: `cycleZero` before the clock's
  first edge counts the edges before it at the clock's period only in a window cut out of a dump (the waves begin after the
  zero); a whole dump whose clock starts late numbers its first edge 0 again, as 0.41 and `wave_sample`. B-01: a measure's
  event on a signal that is no row builds (the signal read). B-16: a measure's ends in order; an event that never happens is
  the lint `measure-no-match` (a `to`: an open pair; a `from`: no measure), not a stopped build. B-06: `wave_signals` takes
  `[` as it is (`q[0]`, `q.[0]`, `top.q[*`). B-07: a view's signals, bookmarks and spans name an array element either way,
  two-dimensional ones too (`m[1].[2]`). B-12: a live `goto`'s `t` in ns. shift+← → never leaves the cursor inside a gap
  on the waves (B-16 of 3 November, half). B-20: `rows` lists the bits of a bus shown bit by bit, `["PADDR[7]", 1, "bit"]`.
  The VS Code configuration: a key takes every kind its comment names (`"log": false`, `"gapIdle": "2us"`), a colour taken
  out goes back, a configuration that breaks the viewer keeps VS Code's theme and keys, a file with a BOM is read, a save
  while a tab opens wins, a mark lands on its key's line (B-05, B-08, B-09, B-10). The tools of a test run: `--lint-json`
  prints `{"error"}` on a failed build (B-13); `wave_tests` of a directory reads every marks file by its content and names
  the files skipped (B-14); `wl.check` texts of dicts, sets and ranges in one radix (B-15); two spellings of one row at
  one time are one moment (B-17); a `marksColors` word that is no theme token or CSS colour and a `marksPhases` that is no
  boolean are refused (B-18); `with wl.checks()` with no check writes no bookmark (B-22). `viewedit.py` as the page: slice
  copies in `rows`, deleted with their signal's copies, what stood on one goes to its bus (B-02, B-03); the id answered is
  the new span's, marker's, expression's (B-11); times in refusals as the page writes them (B-21); `style name: null` the
  settings' style (B-23 of 3 November); `find` says the plugins' rows are not counted, and a plugin's group folded during a
  search stays folded in the state (B-19).

## 0.42 — 4 November 2026

Your configuration in VS Code, and the fixes and small requests of the cl_gev_eval_offload and au_psi5 reports: the cycles
of a window, the FSM panel by a command, checks in one radix, array elements under one name.

- **Your configuration in VS Code.** *WaveLens: Open the configuration* (⚙ in the tab's title): a JSONC file of the viewer's defaults,
  every key with its comment; saved, it is checked (not JSON, a wrong kind, a key that is none: marked in the file) and applied to every tab
  at once; one that breaks the viewer gives the defaults back; *Reset the configuration to the defaults*.
- **The bugs of the cl_gev_eval_offload report of 3 November.** WL-008: a check's list is in one radix, short or long
  (`expected [0x10000000]`, not `[268435456]`). WL-009: an element of an unpacked array has one name for every tool:
  `sva vcd --signals`, `sva diff --signals`, `wave_cut` and the `wave_` tools take `mem[1]` (Verilator's FST) and
  `mem.[1]` (what `wave_signals` lists) of an FST, a VCD and a cut. WL-010: a span's `signals` find their rows by the
  rule of the bookmarks (a row's name, a config's name, the dump's path), no `span-signal-missing` for a phase begun in
  ReadOnly.
- **The small requests of the cl_gev_eval_offload report.** `with wl.checks("…")`: one bookmark for the checks inside, "188 checks
  passed" (P-05b). A view's `"measures"` by events, as a span's ends (P-21). `mkhtml.py --lint-json`: the warnings with their fields
  and the rows they may mean (P-20). `wave_tests` of a directory: a regression in one answer, the failures first (P-19).
  `--marks-phases` / `"marksPhases"`: a marker at each phase; a config's marker at a time, `{"t", "label"}` (P-14). The marks of one
  time take a lane each, the rest one circle `+k` (P-15). A bookmark's `signal` by pattern, `wl.note(text, signal="*full")` (P-10).
  `"marksColors"`: the colours of the marks, hex or the theme's tokens (P-13).
- **The au_psi5 report of 4 November.** AU-WL-001: a window cut out of a long dump with `cycleZero` before it numbers its
  cycles as the whole dump does (the edges before it counted at the clock's period), not from 0. AU-WL-006: an FSM row with a
  `path` of its own in a group has its name in the FSM panel, not a slice of its path. AU-WL-005: the command
  `fsm_panel {signal?, tab?, off?}` opens the panel on an FSM's States, Changes or Diagram. AU-WL-002: a bookmark's text field
  shows the whole text on hover. AU-WL-003: every tool run as `python3 -I` writes no `tools/__pycache__` into the checkout.
- **Paint on the rows of your groups.** Paint (the find bar) and the menu's colour take every row selected with
  shift+click or highlighted with ctrl+click in your groups, not only the current one.

## 0.41 — 3 November 2026

Measurements, links to a moment, your own keys, tools for CI, and the fixes of the review of all of them.

- **Measurements.** The matches of an expression as markers; the Δ between markers in cycles and against a bound
  (`dmin` / `dmax`, a time or `"3 cycles"`; red when it is not kept, `? no clock` when it cannot be counted); the
  `measures` table (`view_get`, `viewedit.py --measure [--csv]`); `wl.measure` in a cocotb test, its pairs on the page
  (a rebuilt page shows its new ones, yours kept); `sharedMarkers` on a page of a view per test.
- **Links.** `page.html#t=…&sel=…&view=…&bm=…`, Copy link, `yl`, the `goto` command; times in a VS Code log or terminal
  as links to the dump's tab (`wavelens.logLinks`).
- **The page.** A config's view keeps its look (`"state"`, `viewedit.py --config`, `--from-page`); the library of
  expressions (`exprLibrary`); the transfers of the buses as a list (CSV, `bus_list`); a slice of a bus as a row
  (`duplicate bits`), the values at two cursors with the change in the row's radix (Copy A · B · Δ); undo of
  expressions and bindings; a filter in the menus' lists, Keep as span, a divider among your groups; the dump's
  statistics in the log; your own keys (`keys`, `data-keys`).
- **Tools.** `sva diff --results [--rank]` (two runs' assertion results), `mkhtml.py --junit --png [--png-width]`
  (`make html PNG= JUNIT=`), `wave_explain` (an expression's match, an assertion's failure, a difference, a time),
  `tools/fsmstats.py` / `wave_fsm` (`make fsm-stats`), `mkconfig.py --gtkw` (a GTKWave save file), `dumpscan.py --stats`,
  `make diff-results`.
- **The review of stages 16–28** (`docs/reviews/review-2026-11-03/stages-16-28/`): a check that did not run is no pass in
  the JUnit; a cover that stops matching fails `sva diff --results`; a refused command leaves nothing; what the SVG
  draws (a divider), what GTKWave writes (nested groups, aliases, marker names), the keys' corners.

## 0.40 — 3 November 2026

Keys that say what can follow them, and the bugs of an independent review fixed. `R` reads the dump again; a moment after `g` a box lists the menu.

- **The box of what can follow.** A moment after the first key of a sequence (`g`, `z`, `y`, `[`, `]`) a box lists what can come next, as LazyVim
  does: press the key or click it; it waits as long as it is open; Esc closes it and only it. Typed fast it never shows. `keyHints` sets the moment
  (200 ms; `false`: never). A key it does not list does nothing and says so; another first key starts its own box.
- **`g` is a menu of nearly everything**, listing what the page can do now: go to (`gg gl gt gT`), the markers and bookmarks (`gm`, `gM` a marker,
  `gB` a bookmark, `gd` the Δ on / off, `gc` clear them), the state (`gs gL gr`), the dump (`gO gR gC`), `gv`, `gp`. `yn` and `yt` copy the
  selected signal's name and the cursor's time. Help has a section Menus.
- **`r` the state again, `R` the dump again** (⟳). With a second dump compared, ⟳ reads it again too and shows the run it showed.
- **From the review of 2026-11-03** (`docs/reviews` on dev): a view key that is no name (`my-view`) builds a page that opens; a highlight of more
  than six rows keeps its colours through a state; Esc in the expression editor's fields no longer resets the viewer; Clear all leaves the page's
  own bookmarks for the next load; a marker on a signal not in these waves goes to the top and is said; no "Δ 0"; Set on the cursor field as it
  shows the cursor keeps it exact; a copy gone takes its hidden bits.
- **A time outside the waves is refused** for a bookmark, a marker or a span's end (from 0 when the waves start later), in the page and in
  `viewedit.py`; going to a bookmark made for other waves stops at their end.
- **`viewedit.py` answers as the page:** colours the page refuses are refused, `set_state` takes a state's keys only, `rows` gives the hidden rows
  where they would be (they came last), `view span / at` keeps the window within the waves, texts and numbers as the page reads them. The smoke
  test now compares the two sides' answers command by command.
- **`wavemcp.py`:** spans and the Δ of `deltas` in ns, as every other time. **`dumpscan.py`:** a byte order mark before `$timescale` no longer
  loses the unit; a scope with no name. **`wavelens_cocotb`:** a label or colour that is no text no longer takes the test's verdict; a test awaited
  inside another is a part of it.

## 0.39 — 2 November 2026

One signal in two forms, markers that measure, and marks that ask less of a test. Two keys changed: `b` is a bookmark now and the bits are on `B`.

- **Duplicate.** The right button on a name or on the waves shows a signal again in a row under it, `PADDR #2`, with its own radix, analog form and colour: a bus in hex
  and as a step plot at once, an enum's numbers beside its names. **Remove the copy** leaves its bookmarks and markers on the signal. Kept in a state, a reload, your groups and undo; `data#2` names it in
  the commands, and the command `duplicate` works on a page that is not open too.
- **Keys.** `m` a marker at the cursor, with its label asked; `b` a bookmark; `B` a bus bit by bit (it was `b`). `]b [b` step through the bookmarks, `]m [m` through the markers (`]m` was the bookmarks).
- **The time between markers.** **Δ between markers** in the head of their list draws an arrow with the time in its middle on a line of its own over the rows. Drag it up and
  down to the line over or under a signal. Each marker's arrow goes to the next in time or to any other, through the ones between: the **→** choice in the list, or the dot at its
  far end dragged to a marker. One arrow per marker: A → C takes the place of A → B, and the last marker can go back. The command `deltas`.
- **Colour on the lines between the rows.** The right button there paints what is on the line: Δ arrows, markers' texts, bookmarks, an arrow's label. On a Δ arrow: its colour.
- **Hidden markers.** **hidden** keeps a marker in its list, off the waves, the pictures and `]m [m`; the Δ goes through it.
- **Clear all** in the Markers list, **Clear bookmarks and markers** in the right button's menu: every bookmark, arrow and marker of yours; undo brings them back.
- **Cocotb marks.** `@wl.test(signals=[...])` adds a test's rows to its view (the view key `"also"`, a missing name is a lint warning, not an error); `wl.step` is a phase in one line; every
  check is counted, in a loop too; the docstring's first paragraph is the test's line and all of it is in the first bookmark; a long value is short by its circle and whole in the list, and two lists say
  where they part; `check(why=)` is read only on a failure; `Marks(hide=)` and `__tracebackhide__` pass a project's own check functions. A marker with `"on"` keeps its `"color"`.
  The attribute `step` of the marks is `step_name` now: `step` is the method. Old marks files still read.
- **The docs' fallback** for a run without the library failed on `@wl.test(signals=...)`: fixed, and a test runs what the docs print.

## 0.38 — 2 November 2026

The bugs found by moving 42 cocotb benches to the marks: a description no longer fails a test, a row keeps its name, and names find rows by one rule.

- **A phase in `ReadOnly`** no longer fails a correct test. It keeps its exact time: begun there it is a span on the `TEST_STEP` row, ended there the row goes
  back at the test's next call. No task writes later: one primed in `ReadOnly` and cancelled at the test's end crashes Verilator 5.
- **A row's name** no longer depends on the waves of another row: the first of two rows with equal transitions took its full path as its name. Every row of a
  view without `"hierarchy"` says where it is in the dump in a new key `"abs"`, which names nothing; `"same"` finds its net by it.
- **Paths of the dump find rows.** An expression by a path below the scope or a full path, an alias too; `cycleClock`, `gapClock`, `gapSignals`, `gapAux`.
- **Marks and bookmarks in a group.** A bookmark's `signal` as the config said it, or the path in the dump, lands on its row, in a group too.
- **A view's `"exprs"`** stay on the page without a `"bind"`.
- **Lint says what was silent:** `expr-name-missing`, `exprs-no-engine`, `gap-view-off` (`gapView` needs `gaps`, USAGE says so now), `setting-signal-missing`.
  A config that built with `--strict` may stop on one of them.

## 0.37 — 2 November 2026

The last state stays at hand, and every build gives the VS Code package.

- **The last state.** Load… remembers what it loaded: **Reload** in the bar and the key `r` read that file again with no dialog, after a dump
  opened in the viewer too; Load… opens in its folder. Where the browser keeps a file's handle (Chrome, Edge) it stays for the next page.
- **In VS Code** the state loaded last is the workspace's, whichever dump it was: Load… opens on that file, Reload works in every tab, and a dump seen for
  the first time takes it at once (`wavelens.openLastState`, on by default; ctrl+Z undoes it). A dump with a view of its own keeps it.
- **The package with every build.** `make check` builds `out/wavelens.vsix`; `make dist-linux` ends with `bin/wavelens.vsix`, committed with a version, so a clone
  installs the extension with nothing built. `mkvsix.py --plain` leaves out the checkout's commit: the tree alone decides the package's bytes, and `publish.py`
  refuses a version whose package is not the build of its tree.
- **cocotb: fixed.** After a run through a symlink a test's failure named `wavelens_cocotb.py` instead of the test's line: cocotb's assertion rewriting caches a
  compile with the path it was made under.

## 0.36 — 2 November 2026

A cocotb test marks up its own waves, on Verilator and on Questa, and each test can stand apart on the page.

- **Marks from a cocotb test.** `python/wavelens_cocotb.py`: `@wl.test()` writes each test's number into the testbench's `TEST_CASE`,
  `wl.phase` its phase's into `TEST_STEP`, `wl.note` and `wl.check` leave bookmarks, warnings and errors of the logs too. The run leaves a
  marks file beside the dump. A test's result is what cocotb says of it, `expect_fail` and `expect_error` counted the same way.
- **The page of a run.** `mkhtml.py --marks` (the config's `"marks"`): a span per test in the colour of its result, bookmarks at its start and
  end, PASS or FAIL with the expected value and the line of the test, names on `TEST_CASE` and `TEST_STEP`, jumps made of the changes of
  `TEST_CASE` in the dump. The window goes past the last test, so a failure where the dump ends stays in sight.
- **Each test apart.** `--marks-views` (`"marksViews"`): `whole`, all the tests on one waveform; `tests`, a view of each with a button per test
  and its result, one shown at a time, `page.html#tc3` opens that one; `both`, that and the whole run.
- **Without WaveLens.** `WAVELENS_MARKS=off` is plain cocotb; a tree without the library takes the same calls from a few lines under
  `except ImportError`. Either way `note` and `phase` do nothing and `check` still compares and fails the test.
- **Verilator and Questa.** `examples/cocotb_apb`: an APB3 slave under five tests, one finding a deliberate bug. `run.py [--sim questa]` (`make cocotb
  [SIM=questa]`) runs them and builds the page; its directory can be copied to a design of your own. Over the example the marks of the two
  simulators are identical (Verilator 5.046, Questa 2021.1).
- **MCP.** `wave_tests` reads a marks file: which tests failed, their windows, what they expected. `wave_page` takes `marks` and `marks_views`.
- **Docs.** The guide *cocotb tests*, with USAGE, the README, DEVELOPMENT, the reference and the MCP guide.

## 0.35 — 1 November 2026

The expressions as a list like the assertions', the waves cut to what they find, and the docs read against the code.

- **Expressions as a list.** The one-line field of the bar is gone: **ƒ Expressions** (`gx`) opens a panel under the bar. An editor
  of several lines offers the names as you type and checks the text. Each line says what it found (matches, the share of the time,
  first, last, shortest, longest), goes through its matches (a click, ◀ ▶, `]x [x`, `]X [X`, the keys of the list) and has a tick, a
  colour, a label, how it marks (band, line, strip) and **ƒ row**. On the waves every expression has a strip of its own at the top
  of the rows and a band or a line over them, in a saved picture and the static SVG too. Names also resolve in the one module at
  the top of a dump; a lazy dump reads what an expression needs first.
- **The waves cut to the expressions.** ✂ on one line or several has the gaps on the waves keep what those expressions find in
  place of the changes of signals: what lies between two matches for idle or longer goes, from keep after one to keep before the
  next, with the ends before the first and after the last. The gaps' frame, texts, jumps, ranges, saved pictures and WaveDrom all
  follow; your own gap settings come back with the last ✂ off.
- **API and MCP.** The commands `expr`, `expr_go`, `expr_matches` in the page and `view_edit`, `expr` in `viewedit.py`; `expr` takes
  `gap` and answers with `cut`, `gaps` answers with `gapBy`, `view_get` lists the expressions and says `gaps.by`. The setting
  `exprsOpen`. `"exprs"` keeps working: a text alone, or an object without `"row"`, still draws its row; new keys `label`, `color`,
  `on`, `row`, `mark`, `gap`.
- **The docs against the code.** USAGE, the guides, the reference, DEVELOPMENT, the SVA documents, the README and the tools' texts
  corrected: keys, labels, menus, sizes, stale statements; the parameters of the MCP tools and the tools' options described.
- **Fixes.** Every time in an MCP answer is in ns (`bookmark` go, `fsm_go`, `fsm_stats`, `compare`); a span is undone with the rest;
  `view_get rows` takes the `offset` its `next_offset` names; ≠ stays on a bus whose width wraps out of sight.

## 0.34 — 1 November 2026

The texts of markers on the lines of signals: dragged by the mouse, pale until a colour is picked, in the API and MCP.

- **A marker's text on any line.** Dragged onto a signal it sits on the thin line over that row (the upper half) or under it (the
  lower half), the line lifted bookmarks use. The drag also moves it along the time, on the edges of that signal; straight up or
  down, or with alt, the time stays. Up to the axis it is back at the top of the rows. A marker without a text is taken by the top
  of its dashed line and has a dot on the line.
- **Colour.** Pale by default, as before. The right button on a text: **Its text…**, **Colour**, **Pale again**, **Delete the
  marker**. A click puts the cursor on it with its label ready in the list; the list has its signal, ↥ ↧ and **pale** too.
- **API and MCP.** The command `marker` takes `signal` and `lift` (`signal: null`: the top, `color: null`: pale) in the page, in
  `viewedit.py` and in `view_edit`; `view_get` says them. A document's `markers` take `color`, `signal` and `lift`, the picture and
  the static SVG draw the line.

## 0.33 — 1 November 2026

The gaps on the waves: the viewer's own waves cut by the gap settings, tuned live, scrolled and measured through.

- **Gaps on the waves.** **Gaps ▸ on the waves** (`gv`, the setting `gapView`) cuts the waves in the viewer, not only the
  pictures: a change of idle, keep or the signals followed shows at once, also with idle and keep on the bar while it is on. A
  long dump pans at the same scale from gap to gap, up to the ends, and zooms at the pointer. The window, the cursor, the
  bookmarks and every jump stay in real time. A band under the axis says what each gap leaves out, a signal counted gets a tag
  over the gap, and a picture or WaveDrom saved cuts where the waves do.
- **Measuring through gaps.** A range or the cursors count the hidden time and clocks. With gaps on the waves a range says the
  cycles of their clock on any row, and an end on a gap's column takes the side of the gap nearer (alt: inside it), so a drag
  over a column measures that gap.
- **API and MCP.** `view.gapParts()` says what the waves keep; the command `gaps` takes `view` and answers with `cut`, `view_edit`
  gives it in ns, `view_get` tells the gaps' settings and, on a live page, `cut`.

## 0.32 — 31 October 2026

The fixes of the global review of 0.31: the gate catches what it missed, compare agrees with `sva diff` at its edges, the
tools say when the data is not there, the viewer holds 20 000 rows, every table of the docs is checked against the code.

- **Compare.** A result from anywhere (a saved state, an agent, another window) is cut to the page's time, and `]d` stays on
  the waves. The bits of a bus compare by their own values: bands, ≠, `]d`, overlay, B's view. The static SVG names the run it
  draws. A row of another width or kind is empty in B's view and is not the first difference, as in `sva diff`. A dump with
  no signal in common compares nothing and keeps the compare before it.
- **`sva`.** wellen's warning goes to stderr on Unix, so `--json -` and a cut stay clean (on Windows `svabuild.py` reads past it).
  A cut of a VCD with a last step over 64 KB ends at its time, not at 2^64−1. `--align` counts B's segments past A's last.
  `sva eval` with a window without an edge exits 2: it was a green run that checked nothing. `--from` / `--to` take any case,
  `µs` and an exponent, as the tools do. One line for a dump that does not read; "1 bit".
- **Tools.** `svtypes.py` checks a types file on load, `check` no longer falls over an entry without labels. One table of time units
  and one `parse_time`, so a config's `"100NS"` or `"0.1µs"` reads. `mkconfig.py --update` says when a scope looks renamed, `--map
  OLD=NEW` keeps its settings. A page whose edits block was edited by hand is refused with what to do. Python ≥ 3.9 is what the
  docs say now: it was what the tools needed.
- **MCP.** `wave_diff` and `wave_cut` take a tail of a path as the other tools. A time outside the dump is said in `notes`, a window
  wholly outside it is an error. `side` and `radix` are checked. `wave_signals` rows have one length, with `extra`. `view_edit`'s
  list marks what runs live only. `view_live rotate` makes a new key. `save` writes the file the agent named, not the one the
  page says; `Access-Control-Allow-Origin` is the allowed Origin, not `*`.
- **The viewer.** Above 4000 rows the names column holds those near the view: a find keystroke on 20 000 signals goes from 1.2 s
  to 54–159 ms. A group's name is text in the menu, a colour is checked before it goes into a style. A day of Open… leaves no
  listeners behind, and of two at once the later one stays. The open log appends a row. `picture` refuses above 5000 rows, a PNG
  above 16384 px. Sort is undone. A selection no longer rebuilds the column on a page with bookmark lanes. The keys come back to
  the waves after a click outside a menu. `view.js` is split into `bar.js`, `names.js`, `menu.js`, `look.js`.
- **VS Code.** A tab's `sva` processes go with it; the store of a dump that no longer exists goes at the next start.
- **Tests.** `make unit` holds `bits`, `compare.show`, the options of `sva diff` and the commands without a browser;
  `tests/unit/golden/api.txt` pins the public names. The budgets of smoke come from what it measures. The mutations that survived
  the review are all caught. cargo 312, unit 335, smoke 805.

## 0.31 — 31 October 2026

Two runs compared by looking at them: a key that flips the waves between the two, both over each other, the run shown
named all the time.

- **A, B, A+B** (the bar, once a dump is compared): **B** puts the second dump's values on these rows in place, so the
  cursor's values, the edges, the find, the FSM panel and the picture are of B and only what differs moves (the
  assertions stay A's, the time B does not cover is shaded); **A+B** draws both on the stretches that differ, a bit's B
  over its A in B's colour, a bus's row in two lanes with both values, `1 ≠ 0` in the value column.
- **Keys:** `d` flips A and B, `D` the overlay and back; `]d [d` work in all three. The time axis names the run shown, in
  its colour (`--wave-run-b`), and so does the picture.
- **Commands and agents:** the command `compare` takes `show` (`a`, `b`, `overlay`), alone or with `result` or `dump`, in
  `viewedit.py` and `view_edit`, live too; `compareView()` and the event `wavelens:compare` on a viewer; the config's
  `"compare": {"dump": "b.vcd", "show": "overlay"}` opens that way, the static SVG draws it; `"compareShow"` in the saved state.
- **B's values on the page:** only of the signals that differ, as the result's `"vcd"` and `"shift"` (at most 32 MB, none
  with `--align`: then bands only), read at its first use; the VS Code tab gets them too. An agent's view of a state
  leaves them out and says their size. **`sva vcd --signals-from FILE`** (`-`: stdin): a list too long for a command line.

## 0.30 — 30 October 2026

Two runs of one test compared without a page and without either dump in memory, the result on a page, and what a
Questa VCD leaves out of the design said.

- **`sva diff A B`** (`make diff REF= WAVES=`): two dumps (VCD or FST) compared change by change, each streamed by a
  thread of its own and merged by time — two VCDs of 214 MB in 7 s, 1.5 MB of heap. Values as Compare… compares them;
  `--map` renames a scope or a signal of A for B (one top each, named apart: paired by themselves); `--from --to`,
  `--offset`; `--segment tb_test` the counts per test case, `--align` case k of B on case k of A; text, `--json`,
  `--junit` (a test case per segment); exit 0 equal, 1 they differ, 2 a usage error. **`sva vcd --from --to
  --signals`** cuts a window: the values at `--from` as `$dumpvars`, the changes to `--to`.
- **MCP:** `wave_diff` and `wave_cut`; `wave_page` takes `compare`.
- **On the page:** a compare result as the WaveJSON extension `"compare"` (made by the build from the config's
  `"compare": {"dump": "b.vcd", "map", "offset"}`): the page opens with its bands, the static SVG draws them; the command
  `compare` (`result`, `off`; `dump` in `viewedit.py` and `view_edit`, live too); the compare is in the saved state
  (Save page, Save, Load…); `rows` and `view_get` say it. **Compare…** reads B once, only what the page shows (13 MB of
  2000 signals in 0.6 s), its progress said, ≠ … ✕ stops it; in VS Code through `sva diff` on the host.
- **`"spans": [{"every": "tb_test", "label": "case {value}"}]`**: a span per test case.
- **What the dump lacks:** the types declare every signal (`wavelens_types.tcl`: arrays and parameters too); the ones
  the dump has not got are counted by why — unpacked arrays, under generate scopes (`vcd add` without `-r`), other scopes,
  not dumped — by `svtypes.py check`, `mkconfig.py`, `wave_info` and the viewer's log. USAGE § What a Questa VCD lacks:
  what Questa 2021.1 writes, and a module of wires for an array.

## 0.29 — 28 October 2026

A bus read bit by bit, and the gaps' marks and counts where they were lost.

- **Bus widths on the names** (`PADDR [7:0]`; a packed struct's field its `[msb:lsb]`), in the viewer and the static
  SVG; `showWidth: false` leaves them out. In a narrow names column the name stays whole, the width whole or not at all.
- **A bus bit by bit:** a click on the width, `b`, or the menu's **Bits: N rows** — a row per bit under the bus
  (`PADDR[7]` … `PADDR[0]`), a signal like any other (selected, its edges, a bookmark, the picture); kept in the browser,
  the saved state (`bits`), undo and a page's edits; the command `bits` in the page and in `tools/viewedit.py`.
- **Gaps:** the marks `//`, `↑`, `+` are the row's, between the name and the value (a bus's width or a long name hid
  them); a signal marked `+` is counted with the default texts too (**time, cycles, +**; before only with **+ changes
  in a gap**), **Count its changes in a gap** turns the texts on; `gapCount` `rise` / `fall` / `any` draw their counts;
  the count over a gap more legible.

## 0.28 — 27 October 2026

What an agent missed while it built an annotated page of a real test (six views, 32 bookmarks, 19 assertions): times
found in the dump instead of by hand, markup on the waves, warnings for what the page would not show, a page a third
of the size, and tools to see and keep its work.

- **A bookmark at an event.** In a config `"at"` instead of `"t"`: `"posedge X"`, `{"signal", "value"}` (an enum label,
  a number), `{"expr", "clock"}` (an SV expression, the sva engine), `{"assert", "result"}` (an attempt of a binding),
  with `nth`, `from`, `to`; a marker `"on"` the same. The build finds the time; no match is an error naming the bookmark.
  One resolver with the MCP `wave_find` (`tools/wavefind.py`).
- **Markup on the waves** (the viewer and the static SVG): `"lift": "below"` (a lane under the signal), a bookmark's
  `"label"` by its circle, `{dt}` / `{cycles}` / `{cycles:CLK}` in arrow labels (filled where they are drawn), `"spans"`:
  coloured stretches of time over every row or some, their ends a time, an event or a bookmark (the `span` command);
  a bookmark's `"link"` opens another view of the page.
- **Lint** at every build (`mkhtml.py --lint`, `--strict`): a bookmark outside its window or on no row, arrows to no
  bookmark, markers that match nothing, bindings to no assertion, `svaShow` names of none, overlapping circles, unknown
  keys, hex enum fills in a theme that may be dark.
- **Assertions:** the sampled times once per view and clock (`sva.cycles`): six windows with 19 bindings 6.8 → 2.8 MB;
  a top-level `"report"` puts bindings into the printable section only. The panel says how many `svaShow` draws.
- **Agents:** MCP enum labels from the types file beside the dump, argument synonyms, an unknown argument an error;
  `view_edit {config}` (a rebuild keeps the marks); `view_get` with `picture` on a page's file through
  `tools/pageshot.py` (headless Chromium: PNGs of a page's views; the one tool outside the standard library, optional);
  `wavemcp.py --lean` (a third fewer characters per request).
- **Questa:** `wavelens_types` before `run` (a batch vsim ends at `$finish`), `wavelens_vcd FILE [ROOT]`.
- The APB example shows the new keys; README and guide pictures made again.

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
