/*
================================================================================
  delays
  Cycle delays: ##n, ##[m:n], ##[m:$], ##[*], ##[+], a leading delay, ##0, a
  parameter as the delay.
================================================================================

    Expected:   tests/sva/golden/delays.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// delays
//==============================================================================

module delays (
    input logic clk,
    input logic rst_n,
    input logic req,
    input logic gnt,
    input logic ack,
    input logic done,
    input logic start,
    input logic busy
);
    localparam int LAT = 2;
    localparam int MAX = LAT + 3;           // a localparam computed from another one

    // a fixed delay ##2
    d_fixed:    assert property (@(posedge clk) req |-> ##2 ack);
    // a bounded range ##[1:3]
    d_range:    assert property (@(posedge clk) req |-> ##[1:3] ack);
    // an unbounded range ##[1:$]
    d_open:     assert property (@(posedge clk) req |-> ##[1:$] done);
    // ##[*], the shorthand of ##[0:$]
    d_star:     assert property (@(posedge clk) start |-> ##[*] done);
    // ##[+], the shorthand of ##[1:$]
    d_plus:     assert property (@(posedge clk) start |-> ##[+] done);
    // a sequence that starts with a delay
    d_leading:  assert property (@(posedge clk) ##1 req ##1 gnt);
    // ##0: the fusion of two expressions in the same cycle
    d_zero:     assert property (@(posedge clk) req ##0 gnt |-> ack);
    // localparams as the delay and as the bound of a range (##2, ##[1:5])
    d_param:    assert property (@(posedge clk) req |-> ##LAT gnt ##[1:MAX] ack);
    // a chain of delays and a repetition under disable iff
    d_chain: assert property (
        @(posedge clk) disable iff (!rst_n)
        start ##1 busy[*2] ##1 done |=> !busy
    );
endmodule
