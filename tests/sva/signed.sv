/*
================================================================================
  signed
  Signed values: the engine compares everything as unsigned
  (docs/sva/ENGINE.md, Decisions), so an assertion that reads a signed
  signal or a signed literal gets a warning; unsigned types and plain
  numbers do not.
================================================================================

    The golden holds the three warnings with their source lines, so each
    assertion stays on one line.
    Expected:   tests/sva/golden/signed.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// signed_checks
//==============================================================================

module signed_checks (
    input logic              clk,
    input int                cnt,
    input logic signed [7:0] s,
    input logic        [7:0] u,
    input byte unsigned      ub
);
    default clocking @(posedge clk); endclocking

    // int is signed: a warning
    cnt_positive: assert property (cnt >= 0);
    // a signed literal against an unsigned signal: a warning
    u_not_five:   assert property (u != 8'sd5);
    // unsigned signals (byte unsigned included) and plain numbers: no warning
    plain:        assert property (u == 3 && ub < 2);
    // a signed signal: a warning
    s_above_u:    assert property (s > u);
endmodule
