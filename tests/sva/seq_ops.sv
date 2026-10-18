// Sequence operators: and, or, intersect, throughout, within, first_match, parentheses, sequence instances.
module seq_ops (input logic clk, a, b, c, d, e, en, start, stop, busy, burst);
  sequence s_ab;          a ##1 b;              endsequence
  sequence s_cd(x, y);    x ##[1:2] y;          endsequence
  sequence s_burst(n);    burst[*1:4] ##1 !burst; endsequence

  q_and:        assert property (@(posedge clk) start |-> (a ##2 b) and (c ##1 d));
  q_or:         assert property (@(posedge clk) start |-> s_ab or s_cd(c, d));
  q_intersect:  assert property (@(posedge clk) start |-> (a ##[1:5] b) intersect (c[*3]));
  q_throughout: assert property (@(posedge clk) $rose(start) |-> en throughout (busy[*1:$] ##1 stop));
  q_within:     assert property (@(posedge clk) start |-> s_cd(a, b) within (c ##[3:6] d));
  q_first:      assert property (@(posedge clk) first_match(start ##[1:4] busy) |=> stop);
  q_nested:     assert property (@(posedge clk) ((a ##1 b) or (c ##1 d)) ##1 e |=> !e);
  q_inst_args:  assert property (@(posedge clk) s_cd(.x(a), .y(b && c)) |=> s_burst(4));
endmodule
