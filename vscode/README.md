# WaveLens — waves in VS Code

A VCD or FST dump in a tab with the WaveLens viewer: zoom, cursors, find, the Modules panel, bus
transactions, assertions (SVA) checked in the page, bookmarks, compare with a second dump — and an AI agent's live
link (`tools/wavemcp.py`).

Made for **Remote-SSH and WSL**: the extension runs on the machine that has the dumps (it is a *workspace* extension),
the tab on yours. Nothing else is needed on the host: the extension carries the viewer and a static `sva` program (an FST
is turned into VCD text with it, kept in the extension's storage).

- **Open**: right click on a `.vcd` / `.fst` in the Explorer → *Open in WaveLens*, or *Open With… → WaveLens* (make it the
  default there for these files if you like).
- **A large dump** (`wavelens.lazy`, auto: an FST of 4 MB, a VCD of 64 MB and more) opens with every module and signal
  at once, the top level open and its modules folded; the signals you open are read from its FST then (a VCD becomes an
  FST once, kept). Assertions, the FSM panel and pictures read what they need first.
- **A tab in a window of its own** (*Move into New Window*, *Copy into New Window*): VS Code makes its page again; the dump is
  read again as it is (through the extension when the window's webview cannot load it, as over a remote connection: the
  log says so), with the view as you left it.
- **A new simulation**: the tab says when the dump changed; ⟳ (the bar, or *WaveLens: Read the dump again* in the editor's title) reads it again with the
  view kept. `wavelens.autoReload`: at once.
- **The last state**, the workspace's whichever dump it was: Load… opens on that file, **Reload** (`r`) reads it in every tab, a dump seen for
  the first time takes it at once (`wavelens.openLastState`), a dump with a view of its own keeps it.
- **Saving** (state, PNG, SVG, WaveDrom, the report) asks where on the host; **Load…**, the `.sv` files and Compare
  pick on the host too. Bookmarks, groups, colours are kept per dump in the workspace (the store of a dump that no longer exists goes at the next start).
- **A piece of the waves** (the right button on a range: *Save as WaveLens (JSON)*): `x.wavelens.json` opens in a tab
  of its own (*Open in WaveLens*), its view with it. *Slice ▸* keeps the range as a run of its own whose times start at 0
  (pieces compared with each other from their first sample in the Runs panel), or saves it as an FST.
- **The runs kept** (Runs…, `gu`, *WaveLens: The runs kept of this dump*): keep the dump of now with a name, tags and a comment
  (an FST in `.wavelens-runs` beside it). The list holds the dump of now and the runs; two rows carry a letter: **A**, the
  waves shown in the tab (`w`: a run's waves read here, the window and rows kept; `]w` `[w` walk through the runs), and **B**,
  the run compared with A (a click, `]r` `[r`; `x`: none, the waves only) — or Δ all of them against A — over the waves in
  sight or a span of yours (a test case: each run's case of that name, wherever it is in the run): only that window of a run
  is read, by `sva` on the host.
- **An agent** (Claude Code, Codex with `tools/wavemcp.py`) on the same host: when it starts its live link
  (`view_live`), the open tabs connect (● live in the bar); `view_live` with a dump and `open` opens it here, and
  `view_edit` / `view_get` with `page` = the dump's path work on its tab. *WaveLens: Connect to the agent* connects the tab now. On by default; `"wavelens.live": false`
  keeps the tabs off the link.

- **State names**: a VCD carries no enum names (Questa writes none). The design's types next to the dump
  (`tb.types.json` by `tb.vcd`, from Questa's `tools/questa/wavelens_types.tcl` or `tools/svtypes.py verilator`) name every
  state bus and struct by its path, read again when the file changes. Without them the tab reads the workspace's
  SystemVerilog sources (`wavelens.sources`, default `**/*.sv`, `**/*.svh`) and names the state buses declared with a
  `typedef enum` there, by name, the fields of a `typedef struct packed` too; **Sources…** in the bar picks other files. *WaveLens: Make the types with Verilator (FSM states, structs)*
  writes `tb.types.json` from a `.f` file of the workspace (or the arguments you type) with `verilator --json-only`: no
  Python needed (`wavelens.verilator`).
- **Convert to FST**: a `.vcd` in the Explorer → right click → *WaveLens: Convert to FST (beside the VCD, FSM states kept)* (or the tab's title menu)
  writes `tb.fst` beside it with the bundled `sva fst`: the VCD's enum tables and the FSM states of `tb.types.json` in it,
  so any FST reader names the states. Its notes (with their lines, five of a kind) go to the log; a failure opens it.
- **State machines**: `T` (or **FSMs** in the bar) lists every signal with state names in the tree of its modules, its
  state at the cursor: go to one, **Only FSMs**, **Add to view**, its states, changes and a diagram (a click: the cursor
  to the next time). The right button's **Type…** on a name says where its names come from.
- **The log**: each read writes the dump's parameters and what the reader noticed (a stranger code, a word that is no
  value, a `$timescale` it cannot read, …) to the output channel *WaveLens* and to the **Problems** panel on their
  lines; a dump it cannot read is an error there with its line. *WaveLens: Show the log* (the editor's title).
- **Theme**: `wavelens.theme` — `auto` (light or dark by VS Code's), `vscode` (the colours of VS Code's theme),
  `light`, `white`, `dark`; **◐** in the bar (or *WaveLens: Choose the theme of the waves* in the editor's title) previews
  each on the open tabs.
- **The version** in the bar: `0.35 · dev@5470d89*`, the extension's branch and commit (`*`: changes not committed).

**Links from a log.** A time in the terminal, a `.log` / `.txt` / `.out` file or a task's output — `@ 1234 ns`, `at 1.2 us`, `time=5ns`, a bare `1234 ns` (fs, ps, ns, us: "3 s" or "100 ms" in a log is no time of a dump) — is a link (ctrl+click): the dump's WaveLens tab (the one in sight, else the one used last, else a dump opened in this workspace before, picked) puts the cursor there and selects the line's `a.b.c` signal after the time (else the first; `top.gen[2].u.req` too; a logger's name — `cocotb.…`, `uvm_…` — is none; a name the dump has not got moves nothing); `dump.vcd#t=…&sel=…` (Copy link in the tab) opens that dump (the command *WaveLens: Go to a moment of the dump*, which the links run). `wavelens.logLinks`: more patterns, regular expressions with the groups `t`, `unit`, `sig`, tried first (no `unit`: ps; one that is no regex or has no `t` is said once in the WaveLens output).

**Your configuration of the viewer.** *WaveLens: Open the configuration* (⚙ in the tab's title) opens a JSONC file of the extension
(`wavelens.config.jsonc`, its global storage) made of the viewer's defaults: every key of `wavelens.config.js` with its value and comment —
colours, sizes, radix, edges, sort, your keys. Saved: checked and applied to every tab at once. Not JSON: marked, nothing applied (the last
one that read stays); a value of the wrong kind or a key that is none: marked, left out, the rest applies; a key taken out: its default; one
that breaks the viewer: the defaults again, said. *WaveLens: Reset the configuration to the defaults* writes it anew.

The keys are the viewer's (`?` in the tab): the plain ones, and the ctrl / alt ones that mean what they mean in VS Code
(ctrl+F, ctrl+C, ctrl+Z, alt+C W R); `wavelens.keysToVSCode` (`ctrl+G`: Go to Line) go to VS Code — the list of your
groups is `gl` then. Settings: `wavelens.logLinks` (`[]`: more patterns of a log's links), `wavelens.theme` (auto), `wavelens.keysToVSCode` (`["ctrl+G"]`), `wavelens.openLastState` (true), `wavelens.verilator` (verilator), `wavelens.sources` (`**/*.sv`, `**/*.svh`), `wavelens.lazy` (auto: a large dump read as it is needed; always, never), `wavelens.autoReload` (false: the tab offers ⟳ after a new
simulation; true: it reads the dump at once), `wavelens.live` (true), `wavelens.runsDir` (empty: `.wavelens-runs` beside the dump), `wavelens.sva` (another sva program; the package carries the Linux one: on a Windows host the path of `sva.exe`, `make dist-windows`).

**Install.** Build the package from the repository (`make vsix`: `out/wavelens.vsix`, a copy as `wavelens-<version>.vsix`, for a Linux x86-64 host;
VS Code ≥ 1.80), then in a terminal of the **remote** window `code --install-extension out/wavelens.vsix` (or
Extensions → … → *Install from VSIX…* while connected): the Extensions view lists it under the host's name.
