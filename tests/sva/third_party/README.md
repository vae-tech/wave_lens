# Third-party assertions (regression inputs)

Assertion files written by others for standard buses, used to test the SVA engine on code it was not written for:
the parser (`make sva-test`: each unit parses with no error into the listed number of assertions, its description
equals `../golden/third_party/<unit>.txt`) and the evaluator (`make smoke`: `sva eval` over the dumps of
`examples/`, every assertion evaluated, no failure). The units are listed in [`units.json`](units.json).

The files are copied unchanged from the upstream commits below, with their license files next to them; the files
ending in `.sva` are WaveLens's own adapters (they say so in their first lines). The licenses permit the copies; the
copyright stays with the authors.

| folder | upstream (commit) | license | files | used for |
|---|---|---|---|---|
| `saravana_apb_ahb/` | [saravana-kumar-T-J-A/APB-AHB-Bus-Protocol-Checker](https://github.com/saravana-kumar-T-J-A/APB-AHB-Bus-Protocol-Checker) (`c59b70a`) | MIT | `tb/apb_assertions.sv`, `tb/ahb_assertions.sv` | APB3 rules with the APB names of `examples/apb`, evaluated at the slave and at the master; AHB parse only (no AHB example) |
| `yosyshq_axi4/` | [YosysHQ-GmbH/SVA-AXI4-FVIP](https://github.com/YosysHQ-GmbH/SVA-AXI4-FVIP) (`250f1ff`) | ISC | `AXI4/src/axi4_spec/amba_axi4_single_interface_requirements.sv` (the property library: a package of parameterised properties) | `axi4_lite_monitor.sva` (wavelens) instantiates the library for `examples/axi_lite`, with the FVIP's labels: reset, handshake, stability, X, deadlock, covers |
| `opentitan/` | [lowRISC/opentitan](https://github.com/lowRISC/opentitan) (`e404f57`) | Apache-2.0 | `hw/ip/prim/rtl/prim_assert.sv`, `prim_assert_standard_macros.svh` (the `ASSERT(name, prop, clk, rst)` macro family) | `apb_prim_assert.sva` (wavelens) writes APB rules with the macros: default macro arguments, macros in macros, `` `ifndef `` in a macro body, token pasting, `` `__FILE__ `` / `` `__LINE__ `` |
| `sindhugd_axi4lite/` | [Sindhugd6472/axi4lite-sva-demo](https://github.com/Sindhugd6472/axi4lite-sva-demo) (`ef262b3`) | MIT | `axi4lite_props.sv` (generated properties, `` `include ``d by its module upstream) | AXI4-Lite VALID / payload stability on the five channels of `examples/axi_lite` |

What they found in the engine (fixed in stage 6): a `//` comment line ending in `\` inside a multi-line macro ended
the macro; `` `__FILE__ `` and `` `__LINE__ `` were unknown; token pasting ` `` ` and stringification `` `" `` were
outside the subset. The AXI-Lite example got the `AWPROT` / `ARPROT` signals that AXI4-Lite requires.

Searched but not taken: files without a license or under the GPL; checkers that are immediate assertions in
`always` blocks (ZipCPU's formal properties); checkers that need what the subset leaves out — generate blocks and
configuration structs (the FVIP's channel files), struct ports and local variables (OpenTitan's `tlul_assert.sv`),
interface ports (`axi.AWVALID`), package functions in widths.
