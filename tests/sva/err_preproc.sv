// Negative cases of the preprocessor: an undefined macro, wrong macro arguments, an unclosed `ifdef.
`define DLY(n) ##n
module err_preproc (input logic clk, a, b);
// expect-error: -1:1 'endmodule' missing: module 'err_preproc' is not closed
  e_undef:    assert property (@(posedge clk) a |-> `NOPE b);
                                                  //^ undefined macro `NOPE
  e_args:     assert property (@(posedge clk) a |-> `DLY(1, 2) b);
                                                  //^ macro `DLY takes 1 argument(s), got 2
  e_noargs:   assert property (@(posedge clk) a |-> `DLY b);
                                                  //^ macro `DLY needs arguments
`ifdef NEVER
  e_skipped:  assert property (garbage that is never read (( );
`else
  ok_else:    assert property (@(posedge clk) a |-> b);
`endif
`ifdef ALSO_NEVER
// expect-error: -1:1 `ifdef without `endif
endmodule
