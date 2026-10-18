/*
================================================================================
  seq_ops
  Sequence operators: and, or, intersect, throughout, within, first_match,
  parentheses, sequence instances.
================================================================================

    The three sequences are one-line declarations, aligned as a table.
    Expected:   tests/sva/golden/seq_ops.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// seq_ops
//==============================================================================

module seq_ops (
    input logic clk,
    input logic a,
    input logic b,
    input logic c,
    input logic d,
    input logic e,
    input logic en,
    input logic start,
    input logic stop,
    input logic busy,
    input logic burst
);
    // without formals, with two untyped formals, with a formal the body does not use
    sequence s_ab;          a ##1 b;              endsequence
    sequence s_cd(x, y);    x ##[1:2] y;          endsequence
    sequence s_burst(n);    burst[*1:4] ##1 !burst; endsequence

    // and of two parenthesized sequences
    q_and:        assert property (@(posedge clk) start |-> (a ##2 b) and (c ##1 d));
    // or of two sequence instances, one without arguments
    q_or:         assert property (@(posedge clk) start |-> s_ab or s_cd(c, d));
    // intersect with a parenthesized repetition (the parentheses dropped when printed)
    q_intersect:  assert property (@(posedge clk) start |-> (a ##[1:5] b) intersect (c[*3]));
    // throughout over an unbounded repetition followed by a delay
    q_throughout: assert property (
        @(posedge clk)
        $rose(start) |-> en throughout (busy[*1:$] ##1 stop)
    );
    // within: an instance inside a parenthesized sequence
    q_within:     assert property (@(posedge clk) start |-> s_cd(a, b) within (c ##[3:6] d));
    // first_match as an antecedent
    q_first:      assert property (@(posedge clk) first_match(start ##[1:4] busy) |=> stop);
    // nested parentheses: or of sequences, then a delay
    q_nested:     assert property (@(posedge clk) ((a ##1 b) or (c ##1 d)) ##1 e |=> !e);
    // named arguments with an expression actual; an instance as the consequent
    q_inst_args:  assert property (@(posedge clk) s_cd(.x(a), .y(b && c)) |=> s_burst(4));
endmodule
