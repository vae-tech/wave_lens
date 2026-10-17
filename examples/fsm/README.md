# FSM: UART receiver, state names from the dump or from the sources

**Shows** an 8N1 receiver (`uart_rx`, 4 clocks per bit) whose `state` is `uart_pkg::state_t` (`IDLE START DATA STOP ERROR`): a clean frame 0xA5, then a frame with a low stop bit that ends in `ERROR`.
**Build:** `make example EX=fsm` → `$(BUILD)/examples/fsm/fsm.html` from the **FST** (Verilator `--trace-fst` writes the enum table, so the names come from the dump; needs GTKWave's `fst2vcd`, else the VCD is used and states show as numbers) and `fsm_all.html` from the **VCD** with `mkconfig.py --sv uart_pkg.sv fsm_tb.sv` (names from the `typedef enum`; for your own dump: `make html WAVES=x.vcd SV="rtl/*.sv"`).
**Config:** written by hand, without any `enum`; `config.style: "questa"` draws vertical edges and narrow bus crossings.
**Look at:** a bookmark at every state change (on the signal that shows why), `-|-` arrows between consecutive changes labelled with the time spent in the state; the `run` view with the framing error.
