// Cycle delays: ##n, ##[m:n], ##[m:$], ##[*], ##[+], a leading delay, ##0, a parameter as the delay.
module delays (input logic clk, rst_n, req, gnt, ack, done, start, busy);
  localparam int LAT = 2;
  localparam int MAX = LAT + 3;

  d_fixed:    assert property (@(posedge clk) req |-> ##2 ack);
  d_range:    assert property (@(posedge clk) req |-> ##[1:3] ack);
  d_open:     assert property (@(posedge clk) req |-> ##[1:$] done);
  d_star:     assert property (@(posedge clk) start |-> ##[*] done);
  d_plus:     assert property (@(posedge clk) start |-> ##[+] done);
  d_leading:  assert property (@(posedge clk) ##1 req ##1 gnt);
  d_zero:     assert property (@(posedge clk) req ##0 gnt |-> ack);
  d_param:    assert property (@(posedge clk) req |-> ##LAT gnt ##[1:MAX] ack);
  d_chain:    assert property (@(posedge clk) disable iff (!rst_n) start ##1 busy[*2] ##1 done |=> !busy);
endmodule
