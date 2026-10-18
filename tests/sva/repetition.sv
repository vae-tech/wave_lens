// Repetitions: consecutive [*n] [*m:n] [*m:$] [*] [+], goto [->n] [->m:n], non-consecutive [=n] [=m:$].
module repetition (input logic clk, a, b, c, req, gnt, valid, last);
  r_consec:   assert property (@(posedge clk) a |=> b[*3] ##1 c);
  r_range:    assert property (@(posedge clk) a |=> b[*1:4] ##1 c);
  r_open:     assert property (@(posedge clk) a |-> b[*2:$] ##1 c);
  r_star:     assert property (@(posedge clk) a ##1 b[*] ##1 c |-> ##1 !a);
  r_plus:     assert property (@(posedge clk) a ##1 b[+] ##1 c);
  r_goto:     assert property (@(posedge clk) req |-> gnt[->1]);
  r_goto_rng: assert property (@(posedge clk) $rose(valid) |-> last[->1:8] ##1 !valid);
  r_nonconsec:assert property (@(posedge clk) req |=> gnt[=2] ##1 !req);
  r_nc_open:  assert property (@(posedge clk) a |-> b[=1:$] ##1 c);
  r_seq:      assert property (@(posedge clk) (a ##1 b)[*2] |=> c);
  r_bool:     assert property (@(posedge clk) (a && !b)[*2] |-> c);
endmodule
