/*
================================================================================
  err_semantic
  Negative cases found when an assertion is expanded: unknown names,
  arguments, clocks, constants, recursion. Each error is annotated under its
  line with a caret at its column (sva/core/tests/corpus.rs);
  tests/sva/golden/err_semantic.txt holds the messages as sva parse prints them.
================================================================================
*/
module err_semantic (
    input logic       clk,
    input logic       clk2,
    input logic       a,
    input logic       b,
    input logic       c,
    input logic [3:0] n
);
    localparam int ONE = 1;
    localparam int NEG = ONE - 3;           // -2: a negative delay below

    //==========================================================================
    // Declarations the assertions use
    //==========================================================================
    sequence s_two(x, y);
        x ##1 y;
    endsequence

    // clocked by another clock than the assertion that uses it
    property p_clk2;
        @(posedge clk2) a |-> b;
    endproperty

    // instantiates itself: the error names the assertion that expands it
    property p_self;
        a |-> p_self;
            //^ recursion is outside the subset (in assertion 'e_recursive', line 82)
    endproperty

    // does not parse: the assertions that use it say so with its line
    property p_bad;
        @(posedge clk) a |-> ;
                           //^ expected an expression, found ';'
    endproperty

    //==========================================================================
    // Names and arguments
    //==========================================================================
    // a sequence or property that is not declared anywhere
    e_unknown:   assert property (@(posedge clk) s_nope(a) |-> b);
                                               //^ no sequence or property 's_nope'
    // an argument without a default left out
    e_missing:   assert property (@(posedge clk) s_two(a) |-> b);
                                               //^ the argument 'y' of 's_two' is missing
    // more arguments than the declaration has
    e_toomany:   assert property (@(posedge clk) s_two(a, b, c));
                                               //^ too many arguments: 's_two' takes 2

    //==========================================================================
    // Clocks
    //==========================================================================
    // no clock in the assertion and no default clocking in the module
    e_noclock:   assert property (a |-> b);
  //^ the assertion has no clock
    // a property clocked by clk2 used under clk
    e_mclock:    assert property (@(posedge clk) p_clk2);
                                               //^ 'p_clk2' is clocked by @(posedge clk2)

    //==========================================================================
    // Constants
    //==========================================================================
    // a delay range bound must be an elaboration-time constant, not a port
    e_nonconst:  assert property (@(posedge clk) a |-> ##[1:n] b);
                                                          //^ repetition count must be a constant
    // a constant delay that evaluates below zero
    e_negative:  assert property (@(posedge clk) a ##NEG b);
                                                   //^ must not be negative, got -2

    //==========================================================================
    // Uses of broken or misplaced declarations
    //==========================================================================
    // the recursive property: annotated at its declaration above
    e_recursive: assert property (@(posedge clk) p_self);
    // a property that did not parse: the error points at the use and names its line
    e_broken:    assert property (p_bad);
                                //^ 'p_bad' did not parse (line 40)
    // a package that is not declared in the compilation unit
    e_package:   assert property (@(posedge clk) a |-> n == no_pkg::IDLE);
                                                          //^ unknown package 'no_pkg'
    // a sequence is not a boolean: it cannot be an operand of &&
    e_seq_expr:  assert property (@(posedge clk) a && s_two);
                                                    //^ 's_two' is used inside an expression
endmodule
