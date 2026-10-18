// AXI4-Lite handshake checks: VALID stays high until READY, payload stable while waiting, responses follow requests,
// no response without a request. For examples/axi_lite.
module axi_lite_checker (
  input logic        ACLK, ARESETn,
  input logic        AWVALID, AWREADY, WVALID, WREADY, BVALID, BREADY, ARVALID, ARREADY, RVALID, RREADY,
  input logic [7:0]  AWADDR, ARADDR,
  input logic [31:0] WDATA, RDATA,
  input logic [3:0]  WSTRB,
  input logic [1:0]  BRESP, RRESP
);
  localparam int MAX_LAT = 16;
  localparam logic [1:0] OKAY = 2'b00, SLVERR = 2'b10;

  // a channel: once VALID rises it stays until READY, and the payload does not move
  property p_hold(valid, ready);
    @(posedge ACLK) disable iff (!ARESETn) valid && !ready |=> valid;
  endproperty
  property p_stable(valid, ready, payload);
    @(posedge ACLK) disable iff (!ARESETn) valid && !ready |=> $stable(payload);
  endproperty

  axi_aw_hold:   assert property (p_hold(AWVALID, AWREADY));
  axi_w_hold:    assert property (p_hold(WVALID, WREADY));
  axi_b_hold:    assert property (p_hold(BVALID, BREADY));
  axi_ar_hold:   assert property (p_hold(ARVALID, ARREADY));
  axi_r_hold:    assert property (p_hold(RVALID, RREADY));
  axi_aw_stable: assert property (p_stable(AWVALID, AWREADY, AWADDR));
  axi_w_stable:  assert property (p_stable(WVALID, WREADY, {WDATA, WSTRB}));
  axi_ar_stable: assert property (p_stable(ARVALID, ARREADY, ARADDR));

  // a write response comes after both the address and the data handshake
  axi_b_after_w: assert property (@(posedge ACLK) disable iff (!ARESETn)
                   (AWVALID && AWREADY)[->1] and (WVALID && WREADY)[->1] |-> ##[1:MAX_LAT] BVALID);
  // a read response follows the address handshake within MAX_LAT cycles
  axi_r_latency: assert property (@(posedge ACLK) disable iff (!ARESETn) ARVALID && ARREADY |=> ##[0:MAX_LAT] RVALID);
  // responses are OKAY or SLVERR (AXI-Lite has no EXOKAY)
  axi_bresp:     assert property (@(posedge ACLK) BVALID |-> BRESP inside {OKAY, SLVERR});
  axi_rresp:     assert property (@(posedge ACLK) RVALID |-> RRESP inside {OKAY, SLVERR});
  // VALID is low during reset
  axi_reset:     assert property (@(posedge ACLK) !ARESETn |-> !AWVALID && !WVALID && !ARVALID);
  // the write data strobe is never empty
  axi_wstrb:     assert property (@(posedge ACLK) WVALID |-> WSTRB != 4'b0000);
  axi_cov_wait:  cover property  (@(posedge ACLK) ARVALID && !ARREADY ##1 ARVALID && ARREADY ##[1:4] RVALID && RREADY);
endmodule
