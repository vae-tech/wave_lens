// Negative cases, syntax: the line after a faulty line has a caret under the expected error column and a part of the
// message. Every error ends only its own item: ok_* assertions around them still load.
module err_syntax (input logic clk, a, b, c);
  ok_first:   assert property (@(posedge clk) a |-> b);
  e_rhs:      assert property (@(posedge clk) a |-> );
                                                  //^ expected an expression, found ')'
  e_range:    assert property (@(posedge clk) a |-> ##[3:1] b);
                                                       //^ the range ends before it starts (3:1)
  e_paren:    assert property (@(posedge clk) (a |-> b);
                                                     //^ expected ')', found ';'
  e_bracket:  assert property (@(posedge clk) a ##[1:2 b);
                                                     //^ expected ']', found 'b'
  e_rep_rep:  assert property (@(posedge clk) a[*2][*3] |-> b);
                                                 //^ a repetition of a repetition needs parentheses
  e_char:     assert property (@(posedge clk) a § b);
                                              //^ unexpected character '§'
  e_ante:     assert property (@(posedge clk) (a |-> b) |=> c);
                                                      //^ the left side of |=> must be a sequence
  e_through:  assert property (@(posedge clk) a ##1 b throughout c);
                                            //^ the left side of throughout must be a boolean expression
  e_semi:     assert property (@(posedge clk) a |-> b)
  ok_kept:    assert property (@(posedge clk) b |-> c);
//^ expected ';' or an action block, found 'ok_kept'
  ok_last:    assert property (@(posedge clk) c |-> a);
endmodule

property p_open;
  @(posedge clk) a |-> b;
sequence s_next; a ##1 b; endsequence
// expect-error: -1:1 expected 'endproperty', found 'sequence'

// a stray identifier at the end of the file: an error, not a crash (it read past the last token)
garbage
// expect-error: -1:1 expected a declaration or an assertion
