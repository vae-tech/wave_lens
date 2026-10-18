/*
================================================================================
  repetition
  Repetitions: consecutive [*n] [*m:n] [*m:$] [*] [+], goto [->n] [->m:n],
  non-consecutive [=n] [=m:$].
================================================================================

    Expected:   tests/sva/golden/repetition.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// repetition
//==============================================================================

module repetition (
    input logic clk,
    input logic a,
    input logic b,
    input logic c,
    input logic req,
    input logic gnt,
    input logic valid,
    input logic last
);
    // a fixed consecutive repetition [*3]
    r_consec:    assert property (@(posedge clk) a |=> b[*3] ##1 c);
    // a bounded consecutive range [*1:4]
    r_range:     assert property (@(posedge clk) a |=> b[*1:4] ##1 c);
    // an unbounded consecutive range [*2:$]
    r_open:      assert property (@(posedge clk) a |-> b[*2:$] ##1 c);
    // [*], the shorthand of [*0:$], inside an antecedent
    r_star:      assert property (@(posedge clk) a ##1 b[*] ##1 c |-> ##1 !a);
    // [+], the shorthand of [*1:$]
    r_plus:      assert property (@(posedge clk) a ##1 b[+] ##1 c);
    // goto repetition [->1]: the next grant
    r_goto:      assert property (@(posedge clk) req |-> gnt[->1]);
    // goto repetition with a range [->1:8]
    r_goto_rng:  assert property (@(posedge clk) $rose(valid) |-> last[->1:8] ##1 !valid);
    // non-consecutive repetition [=2]
    r_nonconsec: assert property (@(posedge clk) req |=> gnt[=2] ##1 !req);
    // non-consecutive repetition with an unbounded range [=1:$]
    r_nc_open:   assert property (@(posedge clk) a |-> b[=1:$] ##1 c);
    // the repetition of a parenthesized sequence
    r_seq:       assert property (@(posedge clk) (a ##1 b)[*2] |=> c);
    // the repetition of a parenthesized boolean: one step, not a sequence
    r_bool:      assert property (@(posedge clk) (a && !b)[*2] |-> c);
endmodule
