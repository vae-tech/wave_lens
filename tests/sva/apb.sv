// APB3 protocol checks (AMBA 3 APB): the setup / access phases, stable signals during a transfer, wait states.
// Written for examples/apb (apb_regs): bind it to the slave or the master, the port names are the APB names.
module apb_checker #(parameter int MAX_WAIT = 8) (
  input logic        PCLK, PRESETn,
  input logic        PSEL, PENABLE, PWRITE, PREADY, PSLVERR,
  input logic [7:0]  PADDR,
  input logic [31:0] PWDATA, PRDATA
);
  default clocking @(posedge PCLK); endclocking
  default disable iff (!PRESETn);

  // the phases as macros: a sequence name cannot be an operand of && (IEEE 1800-2017 16.6)
`define SETUP  (PSEL && !PENABLE)
`define ACCESS (PSEL && PENABLE)

  // a setup phase lasts one cycle and is followed by an access phase
  apb_setup_access:  assert property (`SETUP |=> `ACCESS) else $error("APB: SETUP not followed by ACCESS");
  // PENABLE only with PSEL
  apb_enable_sel:    assert property (PENABLE |-> PSEL) else $error("APB: PENABLE without PSEL");
  // the access phase holds until PREADY
  apb_wait:          assert property (`ACCESS && !PREADY |=> `ACCESS);
  // address, direction and write data stay stable from setup to the end of the access phase
  apb_stable_addr:   assert property (PSEL && !(PENABLE && PREADY) |=> $stable(PADDR) && $stable(PWRITE));
  apb_stable_wdata:  assert property (PSEL && PWRITE && !(PENABLE && PREADY) |=> $stable(PWDATA));
  // PENABLE drops after the transfer completes
  apb_enable_drop:   assert property (`ACCESS && PREADY |=> !PENABLE);
  // a slave answers within MAX_WAIT wait states
  apb_timeout:       assert property ($rose(PENABLE) |-> ##[0:MAX_WAIT] PREADY) else $error("APB: no PREADY after %0d cycles", MAX_WAIT);
  // PSLVERR only in the last cycle of a transfer
  apb_slverr:        assert property (PSLVERR |-> `ACCESS && PREADY);
  // no unknown control values out of reset
  apb_known:         assert property (!$isunknown({PSEL, PENABLE, PWRITE}));
  // coverage: a write, a read with wait states, an error response
  apb_cov_write:     cover property (`SETUP && PWRITE ##1 `ACCESS && PREADY);
  apb_cov_wait_read: cover property (`SETUP && !PWRITE ##1 (`ACCESS && !PREADY)[*2] ##1 PREADY);
  apb_cov_error:     cover property (`ACCESS && PREADY && PSLVERR);
endmodule
