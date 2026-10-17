# APB3: write, read with wait states, slave error

**Shows** an APB3 master (`apb_master`, its `phase` is an enum `IDLE SETUP ACCESS`) and a four-register slave (`apb_regs`): a write to 0x04, a read of 0x04 stretched by two wait states (`PREADY` low), a write to the unmapped 0x40 answered with `PSLVERR`.
**Build:** `make example EX=apb` → `$(BUILD)/examples/apb/apb.html` (from `apb.config.json`) and `apb_all.html` (the whole hierarchy, config made by `mkconfig.py`).
**Config:** written by hand — views with `"signals"` lists, `enum` for `phase`, `bookmarks` and `arrows` per view; the Makefile passes the dump with `--waves`.
**Look at:** bookmarks 1–2 and the *setup → access* arrow (SETUP and ACCESS of the write), 3–4 (wait states, read data), 5–6 and *unmapped* (PADDR → PSLVERR); the static SVG of the write with its legend; the exact view with markers at `done` and `PSLVERR`.
