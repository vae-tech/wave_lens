// ---- AW channel ----


// (1) Payload stable while stalled (including the cycle that completes the handshake)
property p_AW_payload_stable_while_stalled;
  @(posedge ACLK) disable iff(!ARESETn)
    (AWVALID && !AWREADY) |=>
    $stable({ AWADDR, AWPROT });

endproperty
a_AW_payload_stable_while_stalled: assert property(p_AW_payload_stable_while_stalled);



// (2) VALID sticky until handshake (if still stalled next cycle, VALID must still be 1)
property p_AW_valid_sticky_until_handshake;
  @(posedge ACLK) disable iff(!ARESETn)
    (AWVALID && !AWREADY) |=>
    AWVALID;
endproperty
a_AW_valid_sticky_until_handshake: assert property(p_AW_valid_sticky_until_handshake);




// ---- W channel ----


// (1) Payload stable while stalled (including the cycle that completes the handshake)
property p_W_payload_stable_while_stalled;
  @(posedge ACLK) disable iff(!ARESETn)
    (WVALID && !WREADY) |=>
    $stable({ WDATA, WSTRB });

endproperty
a_W_payload_stable_while_stalled: assert property(p_W_payload_stable_while_stalled);



// (2) VALID sticky until handshake (if still stalled next cycle, VALID must still be 1)
property p_W_valid_sticky_until_handshake;
  @(posedge ACLK) disable iff(!ARESETn)
    (WVALID && !WREADY) |=>
    WVALID;
endproperty
a_W_valid_sticky_until_handshake: assert property(p_W_valid_sticky_until_handshake);




// ---- B channel ----


// (1) Payload stable while stalled (including the cycle that completes the handshake)
property p_B_payload_stable_while_stalled;
  @(posedge ACLK) disable iff(!ARESETn)
    (BVALID && !BREADY) |=>
    $stable({ BRESP });

endproperty
a_B_payload_stable_while_stalled: assert property(p_B_payload_stable_while_stalled);



// (2) VALID sticky until handshake (if still stalled next cycle, VALID must still be 1)
property p_B_valid_sticky_until_handshake;
  @(posedge ACLK) disable iff(!ARESETn)
    (BVALID && !BREADY) |=>
    BVALID;
endproperty
a_B_valid_sticky_until_handshake: assert property(p_B_valid_sticky_until_handshake);




// ---- AR channel ----


// (1) Payload stable while stalled (including the cycle that completes the handshake)
property p_AR_payload_stable_while_stalled;
  @(posedge ACLK) disable iff(!ARESETn)
    (ARVALID && !ARREADY) |=>
    $stable({ ARADDR, ARPROT });

endproperty
a_AR_payload_stable_while_stalled: assert property(p_AR_payload_stable_while_stalled);



// (2) VALID sticky until handshake (if still stalled next cycle, VALID must still be 1)
property p_AR_valid_sticky_until_handshake;
  @(posedge ACLK) disable iff(!ARESETn)
    (ARVALID && !ARREADY) |=>
    ARVALID;
endproperty
a_AR_valid_sticky_until_handshake: assert property(p_AR_valid_sticky_until_handshake);




// ---- R channel ----


// (1) Payload stable while stalled (including the cycle that completes the handshake)
property p_R_payload_stable_while_stalled;
  @(posedge ACLK) disable iff(!ARESETn)
    (RVALID && !RREADY) |=>
    $stable({ RDATA, RRESP });

endproperty
a_R_payload_stable_while_stalled: assert property(p_R_payload_stable_while_stalled);



// (2) VALID sticky until handshake (if still stalled next cycle, VALID must still be 1)
property p_R_valid_sticky_until_handshake;
  @(posedge ACLK) disable iff(!ARESETn)
    (RVALID && !RREADY) |=>
    RVALID;
endproperty
a_R_valid_sticky_until_handshake: assert property(p_R_valid_sticky_until_handshake);




