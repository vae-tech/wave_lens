/*
================================================================================
  err_syntax
  Negative cases, syntax: the line after a faulty line has a caret under the
  expected error column and a part of the message (sva/core/tests/corpus.rs).
  Every error ends only its own item: the ok_* assertions around them still
  load. tests/sva/golden/err_syntax.txt holds the messages as sva parse prints
  them.
================================================================================
*/
module err_syntax (
    input logic clk,
    input logic a,
    input logic b,
    input logic c
);
    // a good assertion before the errors: still loaded
    ok_first:   assert property (@(posedge clk) a |-> b);
    // an implication without its right side
    e_rhs:      assert property (@(posedge clk) a |-> );
                                                    //^ expected an expression, found ')'
    // a delay range must not end before it starts
    e_range:    assert property (@(posedge clk) a |-> ##[3:1] b);
                                                         //^ the range ends before it starts (3:1)
    // an unclosed parenthesis
    e_paren:    assert property (@(posedge clk) (a |-> b);
                                                       //^ expected ')', found ';'
    // an unclosed bracket
    e_bracket:  assert property (@(posedge clk) a ##[1:2 b);
                                                       //^ expected ']', found 'b'
    // [*2][*3] is not a repetition of a repetition without parentheses
    e_rep_rep:  assert property (@(posedge clk) a[*2][*3] |-> b);
                                                   //^ repetition of a repetition needs parentheses
    // a character that is not SystemVerilog
    e_char:     assert property (@(posedge clk) a § b);
                                                //^ unexpected character '§'
    // the antecedent of an implication is a sequence, not a property
    e_ante:     assert property (@(posedge clk) (a |-> b) |=> c);
                                                        //^ the left side of |=> must be a sequence
    // throughout takes a boolean on its left
    e_through:  assert property (@(posedge clk) a ##1 b throughout c);
                                              //^ left side of throughout must be a boolean
    // a missing ';': the error is at the next item, which is still read
    e_semi:     assert property (@(posedge clk) a |-> b)
    ok_kept:    assert property (@(posedge clk) b |-> c);
  //^ expected ';' or an action block, found 'ok_kept'
    // a good assertion after the errors: still loaded
    ok_last:    assert property (@(posedge clk) c |-> a);
endmodule

// a property without its endproperty: the next declaration ends it
property p_open;
    @(posedge clk) a |-> b;
sequence s_next; a ##1 b; endsequence
// expect-error: -1:1 expected 'endproperty', found 'sequence'

// a stray identifier at the end of the file: an error, not a crash (it read past the last token)
garbage
// expect-error: -1:1 expected a declaration or an assertion
