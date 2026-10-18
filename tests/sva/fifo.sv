/*
================================================================================
  fifo
  A synchronous FIFO: no push when full, no pop when empty, the count follows
  push and pop, flags agree with the count.
================================================================================

    Exercises:  default clocking and default disable iff, $clog2 in a port
                width, $past, $stable, $rose, s_eventually, a parameter as a
                repetition count, $bits against a localparam.
    Expected:   tests/sva/golden/fifo.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// fifo_checker
//==============================================================================

module fifo_checker #(
    parameter int DEPTH = 8,
    parameter int W     = 16
) (
    input logic                   clk,
    input logic                   rst_n,
    input logic                   push,
    input logic                   pop,
    input logic                   full,
    input logic                   empty,
    input logic [$clog2(DEPTH):0] count,
    input logic [W-1:0]           wdata,
    input logic [W-1:0]           rdata
);
    localparam int CW = $clog2(DEPTH) + 1;  // the width of count
    default clocking @(posedge clk); endclocking
    default disable iff (!rst_n);

    // no write into a full FIFO
    fifo_no_overflow:  assert property (full |-> !push) else $error("push into a full FIFO");
    // no read from an empty FIFO
    fifo_no_underflow: assert property (empty |-> !pop) else $error("pop from an empty FIFO");
    // full is exactly count == DEPTH
    fifo_full_flag:    assert property (full == (count == DEPTH));
    // empty is exactly count == 0
    fifo_empty_flag:   assert property (empty == (count == 0));
    // a push alone adds one ($past)
    fifo_count_push:   assert property (push && !pop |=> count == $past(count) + 1);
    // a pop alone removes one
    fifo_count_pop:    assert property (pop && !push |=> count == $past(count) - 1);
    // a push with a pop, or neither, keeps the count
    fifo_count_hold:   assert property (push == pop |=> $stable(count));
    // the FIFO leaves reset empty
    fifo_reset:        assert property ($rose(rst_n) |-> empty && count == 0);
    // everything pushed is popped some time (a strong eventually)
    fifo_eventually:   assert property (push |-> s_eventually pop);
    // filled from empty to full: DEPTH pushes in a row, [*DEPTH]
    fifo_fill:         cover  property (empty ##1 (push && !pop)[*DEPTH] ##1 full);
    // the count port is as wide as the localparam says
    fifo_count_width:  assert property ($bits(count) == CW);
endmodule
