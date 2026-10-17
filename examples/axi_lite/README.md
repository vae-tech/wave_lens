# AXI4-Lite: one write, one read

**Shows** an AXI4-Lite master (`axil_master`) and a register slave (`axil_regs` with `u_regfile`): a write (AW, then W, then B; `AWREADY` comes a cycle late) and a read (AR, R).
**Build:** `make example EX=axi_lite` → `$(BUILD)/examples/axi_lite/axi_lite.html` (from `axi_lite.config.json`) and `axi_lite_all.html` (three levels of modules, config made by `mkconfig.py`).
**Config:** written by hand — `"group"` puts the signals into the channels `aw w b ar r` and `config.groupColors` gives each its colour, `config.highlight` opens the page with the write channels in front (Esc clears it), `enum` names `BRESP`/`RRESP`.
**Look at:** a bookmark on every `VALID & READY` cycle, the arrows AW → W → B and AR → R labelled with the latency (`2T`) in their own lanes; in `axi_lite_all.html` module rows, shading per module, highlight and fuzzy find (`awvd`).
