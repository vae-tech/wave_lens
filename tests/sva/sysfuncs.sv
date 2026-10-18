// Sampled value and bit functions: $rose $fell $stable $changed $past(x) $past(x, n) $onehot $onehot0 $countones
// $isunknown $sampled $bits $clog2.
module sysfuncs #(parameter int DEPTH = 16) (input logic clk, rst_n, valid, ready, input logic [3:0] grant, input logic [7:0] data, cnt);
  localparam int AW = $clog2(DEPTH);
  f_rose:      assert property (@(posedge clk) $rose(valid) |-> !$past(valid));
  f_fell:      assert property (@(posedge clk) $fell(rst_n) |=> grant == 0);
  f_stable:    assert property (@(posedge clk) valid && !ready |=> $stable(data));
  f_changed:   assert property (@(posedge clk) $changed(data) |-> valid);
  f_past_n:    assert property (@(posedge clk) valid ##1 ready |-> data == $past(data, 2));
  f_onehot:    assert property (@(posedge clk) |grant |-> $onehot(grant));
  f_onehot0:   assert property (@(posedge clk) $onehot0(grant));
  f_count:     assert property (@(posedge clk) $countones(grant) <= 1);
  f_unknown:   assert property (@(posedge clk) disable iff (!rst_n) valid |-> !$isunknown(data));
  f_sampled:   assert property (@(posedge clk) $sampled(valid) |-> ready);
  f_bits:      assert property (@(posedge clk) cnt < 2 ** $bits(grant) + AW);
endmodule
