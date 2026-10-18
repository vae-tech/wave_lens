// Property operators: |-> |=> not and or if/else #-# #=# nexttime s_nexttime always s_always eventually s_eventually.
module prop_ops (input logic clk, rst_n, req, ack, gnt, err, mode, start, done, a, b);
  property p_handshake(r, k); r |-> ##[1:4] k; endproperty
  property p_never(x);        not x;           endproperty

  p_overlap:   assert property (@(posedge clk) req |-> ack);
  p_next:      assert property (@(posedge clk) req |=> ack);
  p_not:       assert property (@(posedge clk) not (req ##1 err));
  p_and:       assert property (@(posedge clk) p_handshake(req, ack) and p_never(err));
  p_or:        assert property (@(posedge clk) (req |-> gnt) or (req |-> ##1 ack));
  p_if:        assert property (@(posedge clk) start |-> if (mode) ##1 a else ##2 b);
  p_if_noelse: assert property (@(posedge clk) if (mode) req |=> ack);
  p_followed:  cover property  (@(posedge clk) req ##1 gnt #-# ack);
  p_followed2: cover property  (@(posedge clk) req #=# ##[0:2] ack);
  p_nexttime:  assert property (@(posedge clk) req |-> nexttime ack);
  p_nexttime2: assert property (@(posedge clk) req |-> s_nexttime [2] ack);
  p_always:    assert property (@(posedge clk) $fell(rst_n) |-> always !start);
  p_always_r:  assert property (@(posedge clk) start |-> always [1:3] !done);
  p_s_always:  assert property (@(posedge clk) start |-> s_always [0:2] busy_ok(a));
  p_eventual:  assert property (@(posedge clk) start |-> s_eventually done);
  p_eventual2: assert property (@(posedge clk) start |-> eventually [1:8] done);
  p_inst:      assert property (p_handshake(start, done));

  sequence busy_ok(x); x || b; endsequence
  default clocking @(posedge clk); endclocking
  default disable iff (!rst_n);
endmodule
