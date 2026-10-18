/*
================================================================================
  err_subset
  Negative cases: constructs outside the subset of docs/sva/LANGUAGE.md. Each
  is named in its error, annotated under its line with a caret at its column
  (sva/core/tests/corpus.rs); tests/sva/golden/err_subset.txt holds the
  messages as sva parse prints them.
================================================================================
*/
module err_subset (
    input logic       clk,
    input logic       clk2,
    input logic       a,
    input logic       b,
    input logic       en,
    input logic [3:0] v
);
    // the until family is not implemented (roadmap "What is left out" 1)
    e_until:    assert property (@(posedge clk) a until b);
                                                //^ until is outside the subset
    // only the system functions of LANGUAGE.md are known
    e_sysfunc:  assert property (@(posedge clk) $countbits(v, 1) == 2);
                                              //^ $countbits is outside the subset
    // a gated clock event
    e_gated:    assert property (@(posedge clk iff en) a);
                                             //^ @(... iff ...) clock gating is outside the subset
    // a second clock inside the property
    e_mclock:   assert property (@(posedge clk) a ##1 @(posedge clk2) b);
                                                    //^ (multi-clock) is outside
    // strong / weak sequence operators
    e_strong:   assert property (@(posedge clk) a |-> strong(b ##1 a));
                                                    //^ strong(...) is outside the subset
    // $past with a gating expression
    e_past:     assert property (@(posedge clk) a |-> $past(b, 1, en));
                                                    //^ gating and clock arguments of $past
    // immediate assertions
    e_immed:    assert (a || b);
              //^ immediate assertions (assert (expr)) are outside the subset
    // the abort operators
    e_accept:   assert property (@(posedge clk) accept_on (en) a |=> b);
                                              //^ accept_on is outside the subset

    // a concurrent assertion inside a procedural block
    always @(posedge clk) begin
        if (en) assert property (a |-> b);
              //^ assert property inside a procedural block or generate is outside
    end
endmodule

// a local variable of a property
property p_local;
    int x;
  //^ local variables in sequences and properties are outside the subset
    @(posedge clk) a |-> b;
endproperty
