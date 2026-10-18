// A synchronous FIFO: no push when full, no pop when empty, the count follows push and pop, flags agree with the count.
module fifo_checker #(parameter int DEPTH = 8, parameter int W = 16) (
  input logic clk, rst_n, push, pop, full, empty,
  input logic [$clog2(DEPTH):0] count,
  input logic [W-1:0] wdata, rdata
);
  localparam int CW = $clog2(DEPTH) + 1;
  default clocking @(posedge clk); endclocking
  default disable iff (!rst_n);

  fifo_no_overflow:  assert property (full |-> !push) else $error("push into a full FIFO");
  fifo_no_underflow: assert property (empty |-> !pop) else $error("pop from an empty FIFO");
  fifo_full_flag:    assert property (full == (count == DEPTH));
  fifo_empty_flag:   assert property (empty == (count == 0));
  fifo_count_push:   assert property (push && !pop |=> count == $past(count) + 1);
  fifo_count_pop:    assert property (pop && !push |=> count == $past(count) - 1);
  fifo_count_hold:   assert property (push == pop |=> $stable(count));
  fifo_reset:        assert property ($rose(rst_n) |-> empty && count == 0);
  fifo_eventually:   assert property (push |-> s_eventually pop);
  fifo_fill:         cover  property (empty ##1 (push && !pop)[*DEPTH] ##1 full);
  fifo_count_width:  assert property ($bits(count) == CW);
endmodule
