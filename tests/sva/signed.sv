// Signed values: the engine compares everything as unsigned (docs/sva/ENGINE.md, Decisions), so an assertion that
// reads a signed signal or a signed literal gets a warning; unsigned types and plain numbers do not.
module signed_checks (
  input logic              clk,
  input int                cnt,
  input logic signed [7:0] s,
  input logic        [7:0] u,
  input byte unsigned      ub
);
  default clocking @(posedge clk); endclocking
  cnt_positive: assert property (cnt >= 0);
  u_not_five:   assert property (u != 8'sd5);
  plain:        assert property (u == 3 && ub < 2);
  s_above_u:    assert property (s > u);
endmodule
