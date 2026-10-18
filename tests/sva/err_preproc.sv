/*
================================================================================
  err_preproc
  Negative cases of the preprocessor: an undefined macro, wrong macro
  arguments, an unclosed `ifdef. Each error is annotated under its line: a
  caret comment at the error's column, or an expect-error marker with a
  relative line (sva/core/tests/corpus.rs); tests/sva/golden/err_preproc.txt
  holds the messages as sva parse prints them.
================================================================================
*/
`define DLY(n) ##n

module err_preproc (
    input logic clk,
    input logic a,
    input logic b
);
// expect-error: -5:1 'endmodule' missing: module 'err_preproc' is not closed
    // a macro that was never defined is an error at its use, not an empty text
    e_undef:    assert property (@(posedge clk) a |-> `NOPE b);
                                                    //^ undefined macro `NOPE
    // a macro is called with exactly the arguments it declares
    e_args:     assert property (@(posedge clk) a |-> `DLY(1, 2) b);
                                                    //^ macro `DLY takes 1 argument(s), got 2
    // a macro with arguments cannot be used without them
    e_noargs:   assert property (@(posedge clk) a |-> `DLY b);
                                                    //^ macro `DLY needs arguments

    // the branch of an `ifdef that is not taken is never read, not even lexed
`ifdef NEVER
    e_skipped:  assert property (garbage that is never read (( );
`else
    ok_else:    assert property (@(posedge clk) a |-> b);
`endif

    // an `ifdef still open at the end of the file swallows the endmodule: two errors
`ifdef ALSO_NEVER
// expect-error: -1:1 `ifdef without `endif
endmodule
