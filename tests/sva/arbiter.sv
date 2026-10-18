// A round-robin arbiter with four requesters: one grant at a time, only to a requester, every request served.
module arbiter_checker #(parameter int N = 4, parameter int MAX_WAIT = 3 * N) (
  input logic clk, rst_n,
  input logic [N-1:0] req, gnt,
  input logic lock
);
  default clocking @(posedge clk); endclocking
  default disable iff (!rst_n);

  property p_served(i);
    req[i] |-> ##[0:MAX_WAIT] gnt[i];
  endproperty
  property p_held(i);
    gnt[i] && lock |=> gnt[i];
  endproperty

  arb_onehot:   assert property ($onehot0(gnt));
  arb_only_req: assert property ((gnt & ~req) == 0);
  arb_served0:  assert property (p_served(0));
  arb_served1:  assert property (p_served(1));
  arb_served2:  assert property (p_served(2));
  arb_served3:  assert property (p_served(3));
  arb_lock:     assert property (p_held(0) and p_held(1) and p_held(2) and p_held(3));
  arb_idle:     assert property (req == 0 |-> gnt == 0);
  arb_no_starve:assert property (req[0] && !gnt[0] throughout req[1][*2] |-> ##[0:N] gnt[0]);
  arb_fair:     cover  property (gnt[0] ##[1:$] gnt[1] ##[1:$] gnt[2] ##[1:$] gnt[3]);
endmodule
