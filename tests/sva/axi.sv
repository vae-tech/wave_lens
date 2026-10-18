/*
================================================================================
  axi
  AXI4-Lite handshake checks: VALID stays high until READY, the payload is
  stable while waiting, responses follow requests, no response without a
  request.  For examples/axi_lite.
================================================================================

    Exercises:  properties with their own clock and disable iff, instances
                with signal and concatenation actuals, localparam constants
                in inside sets, goto repetition joined by and, assertions
                with and without disable iff, a cover.
    Expected:   tests/sva/golden/axi.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// axi_lite_checker
//==============================================================================

module axi_lite_checker (
    input logic        ACLK,
    input logic        ARESETn,
    input logic        AWVALID,
    input logic        AWREADY,
    input logic        WVALID,
    input logic        WREADY,
    input logic        BVALID,
    input logic        BREADY,
    input logic        ARVALID,
    input logic        ARREADY,
    input logic        RVALID,
    input logic        RREADY,
    input logic [7:0]  AWADDR,
    input logic [7:0]  ARADDR,
    input logic [31:0] WDATA,
    input logic [31:0] RDATA,
    input logic [3:0]  WSTRB,
    input logic [1:0]  BRESP,
    input logic [1:0]  RRESP
);
    localparam int MAX_LAT = 16;            // cycles a response may take
    localparam logic [1:0] OKAY   = 2'b00;
    localparam logic [1:0] SLVERR = 2'b10;

    //==========================================================================
    // Channel handshake, one property per rule, an instance per channel
    //==========================================================================

    // AXI A3.2.1: once VALID rises it stays until READY
    property p_hold(valid, ready);
        @(posedge ACLK) disable iff (!ARESETn)
        valid && !ready |=> valid;
    endproperty

    // AXI A3.2.1: while VALID waits for READY the payload does not move
    property p_stable(valid, ready, payload);
        @(posedge ACLK) disable iff (!ARESETn)
        valid && !ready |=> $stable(payload);
    endproperty

    // the write address channel holds its VALID
    axi_aw_hold:   assert property (p_hold(AWVALID, AWREADY));
    // the write data channel holds its VALID
    axi_w_hold:    assert property (p_hold(WVALID, WREADY));
    // the write response channel holds its VALID (the slave side)
    axi_b_hold:    assert property (p_hold(BVALID, BREADY));
    // the read address channel holds its VALID
    axi_ar_hold:   assert property (p_hold(ARVALID, ARREADY));
    // the read data channel holds its VALID (the slave side)
    axi_r_hold:    assert property (p_hold(RVALID, RREADY));
    // the write address is stable while it waits
    axi_aw_stable: assert property (p_stable(AWVALID, AWREADY, AWADDR));
    // data and strobes are stable while they wait: a concatenation as the actual
    axi_w_stable:  assert property (p_stable(WVALID, WREADY, {WDATA, WSTRB}));
    // the read address is stable while it waits
    axi_ar_stable: assert property (p_stable(ARVALID, ARREADY, ARADDR));

    //==========================================================================
    // Responses
    //==========================================================================

    // AXI A3.3.1: a write response comes after both the address and the data handshake
    axi_b_after_w: assert property (
        @(posedge ACLK) disable iff (!ARESETn)
        (AWVALID && AWREADY)[->1] and (WVALID && WREADY)[->1] |->
            ##[1:MAX_LAT] BVALID
    );
    // a read response follows the address handshake within MAX_LAT cycles
    axi_r_latency: assert property (
        @(posedge ACLK) disable iff (!ARESETn)
        ARVALID && ARREADY |=> ##[0:MAX_LAT] RVALID
    );
    // write responses are OKAY or SLVERR (AXI-Lite has no EXOKAY): no disable iff
    axi_bresp:     assert property (@(posedge ACLK) BVALID |-> BRESP inside {OKAY, SLVERR});
    // read responses are OKAY or SLVERR as well
    axi_rresp:     assert property (@(posedge ACLK) RVALID |-> RRESP inside {OKAY, SLVERR});
    // AXI A3.1.2: the master's VALID signals are low during reset
    axi_reset:     assert property (@(posedge ACLK) !ARESETn |-> !AWVALID && !WVALID && !ARVALID);
    // the write data strobe is never empty (a rule of this checker, not of AXI)
    axi_wstrb:     assert property (@(posedge ACLK) WVALID |-> WSTRB != 4'b0000);
    // a read whose address waits one cycle, then data within four
    axi_cov_wait:  cover property (
        @(posedge ACLK)
        ARVALID && !ARREADY ##1 ARVALID && ARREADY ##[1:4] RVALID && RREADY
    );
endmodule
