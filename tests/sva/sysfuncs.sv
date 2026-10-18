/*
================================================================================
  sysfuncs
  Sampled value and bit functions: $rose $fell $stable $changed $past(x)
  $past(x, n) $onehot $onehot0 $countones $isunknown $sampled $bits $clog2.
================================================================================

    Expected:   tests/sva/golden/sysfuncs.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// sysfuncs
//==============================================================================

module sysfuncs #(
    parameter int DEPTH = 16
) (
    input logic       clk,
    input logic       rst_n,
    input logic       valid,
    input logic       ready,
    input logic [3:0] grant,
    input logic [7:0] data,
    input logic [7:0] cnt
);
    localparam int AW = $clog2(DEPTH);      // $clog2 of a parameter

    // $rose, and $past with the default of one cycle
    f_rose:      assert property (@(posedge clk) $rose(valid) |-> !$past(valid));
    // $fell
    f_fell:      assert property (@(posedge clk) $fell(rst_n) |=> grant == 0);
    // $stable of a vector
    f_stable:    assert property (@(posedge clk) valid && !ready |=> $stable(data));
    // $changed
    f_changed:   assert property (@(posedge clk) $changed(data) |-> valid);
    // $past with a cycle count
    f_past_n:    assert property (@(posedge clk) valid ##1 ready |-> data == $past(data, 2));
    // $onehot behind a reduction or
    f_onehot:    assert property (@(posedge clk) |grant |-> $onehot(grant));
    // $onehot0
    f_onehot0:   assert property (@(posedge clk) $onehot0(grant));
    // $countones in a comparison
    f_count:     assert property (@(posedge clk) $countones(grant) <= 1);
    // $isunknown under disable iff
    f_unknown:   assert property (@(posedge clk) disable iff (!rst_n) valid |-> !$isunknown(data));
    // $sampled
    f_sampled:   assert property (@(posedge clk) $sampled(valid) |-> ready);
    // $bits as an exponent, plus the $clog2 localparam
    f_bits:      assert property (@(posedge clk) cnt < 2 ** $bits(grant) + AW);
endmodule
