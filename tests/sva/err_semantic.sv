// Negative cases found when an assertion is expanded: unknown names, arguments, clocks, constants, recursion.
module err_semantic (input logic clk, clk2, a, b, c, input logic [3:0] n);
  localparam int ONE = 1;
  localparam int NEG = ONE - 3;
  sequence s_two(x, y); x ##1 y; endsequence
  property p_clk2; @(posedge clk2) a |-> b; endproperty
  property p_self; a |-> p_self; endproperty
                       //^ the property 'p_self' instantiates itself: recursion is outside the subset (in assertion 'e_recursive', line 26)
  property p_bad; @(posedge clk) a |-> ; endproperty
                                     //^ expected an expression, found ';'

  e_unknown:  assert property (@(posedge clk) s_nope(a) |-> b);
                                            //^ no sequence or property 's_nope'
  e_missing:  assert property (@(posedge clk) s_two(a) |-> b);
                                            //^ the argument 'y' of 's_two' is missing
  e_toomany:  assert property (@(posedge clk) s_two(a, b, c));
                                            //^ too many arguments: 's_two' takes 2
  e_noclock:  assert property (a |-> b);
//^ the assertion has no clock
  e_mclock:   assert property (@(posedge clk) p_clk2);
                                            //^ multi-clock: 'p_clk2' is clocked by @(posedge clk2)
  e_nonconst: assert property (@(posedge clk) a |-> ##[1:n] b);
                                                       //^ a delay or repetition count must be a constant
  e_negative: assert property (@(posedge clk) a ##NEG b);
                                                //^ must not be negative, got -2
  e_recursive:assert property (@(posedge clk) p_self);
  e_broken:   assert property (p_bad);
                             //^ 'p_bad' did not parse (line 9)
  e_package:  assert property (@(posedge clk) a |-> n == no_pkg::IDLE);
                                                       //^ unknown package 'no_pkg'
  e_seq_expr: assert property (@(posedge clk) a && s_two);
                                                 //^ the sequence or property 's_two' is used inside an expression
endmodule
