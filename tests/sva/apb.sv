/*
================================================================================
  apb
  APB3 protocol checks (AMBA 3 APB): the setup / access phases, stable
  signals during a transfer, wait states, the error response.
================================================================================

    Written for examples/apb (apb_regs): bind it to the slave or the master,
    the port names are the APB names.  The browser smoke test reads this file
    too (its nine assertions and three covers, their names and instances).

    Exercises:  default clocking and default disable iff, argument-less
                macros as operands, a parameter in a delay range, $error with
                and without arguments, covers with a repetition.
    Expected:   tests/sva/golden/apb.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// apb_checker
//==============================================================================

module apb_checker #(
    parameter int MAX_WAIT = 8
) (
    input logic        PCLK,
    input logic        PRESETn,
    input logic        PSEL,
    input logic        PENABLE,
    input logic        PWRITE,
    input logic        PREADY,
    input logic        PSLVERR,
    input logic [7:0]  PADDR,
    input logic [31:0] PWDATA,
    input logic [31:0] PRDATA
);
    default clocking @(posedge PCLK); endclocking
    default disable iff (!PRESETn);

    // the phases as macros: a sequence name cannot be an operand of && (IEEE 1800-2017 16.6)
`define SETUP  (PSEL && !PENABLE)
`define ACCESS (PSEL && PENABLE)

    //==========================================================================
    // Phases: IDLE -> SETUP (one cycle) -> ACCESS (until PREADY)
    //==========================================================================

    // APB3 3.1: a setup phase lasts one cycle and is followed by an access phase
    apb_setup_access:  assert property (`SETUP |=> `ACCESS)
        else $error("APB: SETUP not followed by ACCESS");
    // APB3 3.1: PENABLE only with PSEL
    apb_enable_sel:    assert property (PENABLE |-> PSEL)
        else $error("APB: PENABLE without PSEL");
    // APB3 2.1: the access phase holds until PREADY (wait states)
    apb_wait:          assert property (`ACCESS && !PREADY |=> `ACCESS);

    //==========================================================================
    // Stability: address, direction and write data from setup to the end of access
    //==========================================================================

    // APB3 3.1: address and direction stay stable until the transfer completes
    apb_stable_addr:   assert property (PSEL && !(PENABLE && PREADY) |=>
        $stable(PADDR) && $stable(PWRITE));
    // APB3 2.1: the write data stays stable until the write completes
    apb_stable_wdata:  assert property (PSEL && PWRITE && !(PENABLE && PREADY) |=> $stable(PWDATA));

    //==========================================================================
    // Completion and response
    //==========================================================================

    // APB3 3.1: PENABLE drops after the transfer completes
    apb_enable_drop:   assert property (`ACCESS && PREADY |=> !PENABLE);
    // a slave answers within MAX_WAIT wait states: a parameter as the bound of ##[0:N]
    apb_timeout:       assert property ($rose(PENABLE) |-> ##[0:MAX_WAIT] PREADY)
        else $error("APB: no PREADY after %0d cycles", MAX_WAIT);
    // APB3 2.3: PSLVERR is only valid in the last cycle of a transfer
    apb_slverr:        assert property (PSLVERR |-> `ACCESS && PREADY);
    // no unknown control values out of reset ($isunknown of a concatenation)
    apb_known:         assert property (!$isunknown({PSEL, PENABLE, PWRITE}));

    //==========================================================================
    // Coverage: a write, a read with wait states, an error response
    //==========================================================================

    // a write transfer without wait states
    apb_cov_write:     cover property (`SETUP && PWRITE ##1 `ACCESS && PREADY);
    // a read with two wait states: a repeated macro operand, [*2]
    apb_cov_wait_read: cover property (`SETUP && !PWRITE ##1 (`ACCESS && !PREADY)[*2] ##1 PREADY);
    // a transfer that ends with an error response
    apb_cov_error:     cover property (`ACCESS && PREADY && PSLVERR);
endmodule
