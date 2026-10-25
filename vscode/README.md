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
- **A new simulation**: the tab says when the dump changed; ⟳ (the bar, or the editor's title) reads it again with the
  view kept. `wavelens.autoReload`: at once.
- **Saving** (state, PNG, SVG, WaveDrom, the report) asks where on the host; **Load…**, the `.sv` files and Compare
  pick on the host too. Bookmarks, groups, colours are kept per dump in the workspace.
- **An agent** (Claude Code, Codex with `tools/wavemcp.py`) on the same host: when it starts its live link
  (`view_live`), the open tabs connect (● live in the bar); `view_live` with a dump and `open` opens it here, and
  `view_edit` / `view_get` with `page` = the dump's path work on its tab. On by default; `"wavelens.live": false`
  keeps the tabs off the link.

- **State names**: a VCD carries no enum names (Questa writes none). The design's types next to the dump
  (`tb.types.json` by `tb.vcd`, from Questa's `tools/questa/wavelens_types.tcl` or `tools/svtypes.py verilator`) name every
  state bus and struct by its path, read again when the file changes. Without them the tab reads the workspace's
  SystemVerilog sources (`wavelens.sources`, default `**/*.sv`, `**/*.svh`) and names the state buses declared with a
  `typedef enum` there, by name; **Sources…** in the bar picks other files. *WaveLens: Make the types with Verilator*
  writes `tb.types.json` from a `.f` file of the workspace (or the arguments you type) with `verilator --json-only`: no
  Python needed (`wavelens.verilator`).
- **Convert to FST**: a `.vcd` in the Explorer → right click → *WaveLens: Convert to FST* (or the tab's title menu)
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
- **The version** in the bar: `0.23 · dev@5470d89*`, the extension's branch and commit (`*`: changes not committed).

The keys are the viewer's (`?` in the tab): the plain ones, and the ctrl / alt ones that mean what they mean in VS Code
(ctrl+F, ctrl+C, ctrl+Z, alt+C W R); `wavelens.keysToVSCode` (`ctrl+G`: Go to Line) go to VS Code — the list of your
groups is `gl` then. Settings: `wavelens.theme` (auto), `wavelens.keysToVSCode` (`["ctrl+G"]`), `wavelens.verilator` (verilator), `wavelens.sources` (`**/*.sv`, `**/*.svh`), `wavelens.lazy` (auto: a large dump read as it is needed; always, never), `wavelens.autoReload` (false: the tab offers ⟳ after a new
simulation; true: it reads the dump at once), `wavelens.live` (true), `wavelens.sva` (another sva program).

**Install.** Build the package from the repository (`make vsix`: `out/wavelens.vsix`, a copy as `wavelens-<version>.vsix`, for a Linux x86-64 host;
VS Code ≥ 1.80), then in a terminal of the **remote** window `code --install-extension out/wavelens.vsix` (or
Extensions → … → *Install from VSIX…* while connected): the Extensions view lists it under the host's name.
