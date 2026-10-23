# wavefw — waves in VS Code

A VCD or FST dump in a tab with the wavefw viewer: zoom, cursors, find, the Modules panel, bus
transactions, assertions (SVA) checked in the page, bookmarks, compare with a second dump — and an AI agent's live
link (`tools/wavemcp.py`).

Made for **Remote-SSH and WSL**: the extension runs on the machine that has the dumps (it is a *workspace* extension),
the tab on yours. Nothing is installed on the host: the extension carries the viewer and a static `sva` program (an FST
is turned into VCD text with it, kept in the extension's storage).

- **Open**: right click on a `.vcd` / `.fst` in the Explorer → *Open in wavefw*, or *Open With… → wavefw* (make it the
  default there for these files if you like).
- **A new simulation**: the tab says when the dump changed; ⟳ (the bar, or the editor's title) reads it again with the
  view kept. `wavefw.autoReload`: at once.
- **Saving** (state, PNG, SVG, WaveDrom, the report) asks where on the host; **Load…**, the `.sv` files and Compare
  pick on the host too. Bookmarks, groups, colours are kept per dump in the workspace.
- **An agent** (Claude Code, Codex with `tools/wavemcp.py`) on the same host: when it starts its live link
  (`view_live`), the open tabs connect (● live in the bar); `view_live` with a dump and `open` opens it here, and
  `view_edit` / `view_get` with `page` = the dump's path work on its tab. `wavefw.live`: off.

The keys are the viewer's (`?` in the tab). Build the package from the repository: `make vsix`.
