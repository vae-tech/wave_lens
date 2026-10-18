# CoaXPress device: the user's checkers over a real dump

**Shows** the project on real code: the bound SVA contracts of a CoaXPress device IP (`cxp_sva.sv`: 12 checker
modules, 26 assertions, each checker bound into the module it watches) over the dump of its stream-video testbench
(`tb_cxp_top`, 3520 signals in 214 scopes, 16 000 cycles of each clock).
**Files:** `cxp_util_pkg.sv`, `cxp_pkg.sv` (the IP's packages: constants and the packed structs), `cxp_sva.sv` (the
checkers), `test_stream_video.config.json` (made by `mkconfig.py --sva`: every signal, one `bind` line per checker
instance), `cxp_pkg_stub.sv` (the constants of `cxp_pkg` the checkers read, the struct cut to 40 bits: what the engine
reads today; stage 9.6 binds the real package and deletes the stub).
**Not in git:** the dump `test_stream_video.fst` (266 kB, `*.fst` is ignored) and the page (26 MB, `examples/*/*.html`
is ignored). Put the FST of your run next to the config (Verilator `--trace-fst`; the same file as
`work/test_stream_video.fst`).
**Build:**

```sh
make html WAVES=examples/test_video/test_stream_video.fst \
    SVA="examples/test_video/cxp_util_pkg.sv examples/test_video/cxp_pkg.sv examples/test_video/cxp_sva.sv"
```

→ `examples/test_video/test_stream_video.html` (the config exists, so `make html` uses it; `SVA=` replaces its `"sva"`
list; without `SVA=` the config's own list, with the stub, is used). `make sva-build` first, so the bindings are
evaluated while the page is built (about 20 s for the 32 bindings, a 26 MB page: the results list every passing
attempt; stage 9.6 makes them compact). `make config WAVES=examples/test_video/test_stream_video.fst SVA="…"` updates
the config after a new dump and keeps your edits.
**Look at:** the assertions panel (32 bindings, no failure); `a_owner_valid` under `…cxp_tx_owner_sva_i`; the
assertions that never leave vacuity in this bench (backpressure, trigger, I/O acknowledgment, Wait, resync are not
exercised). `docs/reviews/global-review-2026-10.html` lists what the engine cannot read yet here (`$stable(rsp)` on the
82-bit struct, the signed `bad_q`, binding by the `bind` statements).
