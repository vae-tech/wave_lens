# cocotb: five tests of an APB3 slave, marked up on the waves

**Shows** a cocotb test marking up its own waves with `python/wavelens_cocotb.py`: which test ran when, its phases, what it checked,
PASS or FAIL with the expected value. The testbench has `TEST_CASE` (the running test's number) and `TEST_STEP` (its phase's), written by cocotb and read by nothing but the waves.
**Run:** `python3 run.py` (Verilator ≥ 5.036) or `python3 run.py --sim questa` (`vlog`, `vsim` on PATH), with `pip install cocotb` ≥ 2.0 → `out/cocotb_apb.html`, `out/apb.marks.json`, `out/sim/dump.vcd`. From the repository: `make cocotb`, `make cocotb SIM=questa`. `python3 run.py --help` has the rest.
**To copy:** `run.py`, `test_apb.py`, `cocotb_apb_tb.sv`, `cocotb_apb.config.json` run anywhere with `--wavelens PATH` (or `WAVELENS_HOME`); `HDL`, `TOP`, `MODULE`, `CONFIG` at the top of `run.py` are all it knows of the design. [The guide](../../docs/guides/cocotb.html) walks through your own design.
**Config:** `cocotb_apb.config.json`, one view by hand; the bookmarks, spans, jumps and names come from the run through `mkhtml.py --marks`.
**Each test apart:** the buttons at the top show one test at a time (`--marks-views both`; `tests`: without the whole run, `whole`: all on one waveform).
**Look at:** the green spans of the four tests that pass and the orange one of the last; **go to → TC3** for the two wait states on `PREADY`; bookmark on `PRDATA` at the end, `SCRATCH bit 17: 0, expected 0x20000`, and the row `PWDATA` beside it.
**Without WaveLens:** the tests run as they are, with `WAVELENS_MARKS=off` or with no `wavelens_cocotb` to import (`except ImportError` in `test_apb.py`): `note` and `phase` do nothing, `check` still fails a test.
**The tests** (`test_apb.py`): `test_reset_values`, `test_write_read`, `test_wait_states`, `test_slave_error`, `test_scratch_walking_one`. The last finds the slave's deliberate bug (`SCRATCH_BUG` in `cocotb_apb_tb.sv`) and is `expect_fail`, so the regression stays green with a failure on the page.
