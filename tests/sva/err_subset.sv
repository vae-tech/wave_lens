// Negative cases, constructs outside the subset (docs/sva/LANGUAGE.md): each is named in its error.
module err_subset (input logic clk, clk2, a, b, en, input logic [3:0] v);
  e_until:    assert property (@(posedge clk) a until b);
                                              //^ until is outside the subset
  e_sysfunc:  assert property (@(posedge clk) $countbits(v, 1) == 2);
                                            //^ the system function $countbits is outside the subset
  e_gated:    assert property (@(posedge clk iff en) a);
                                           //^ @(... iff ...) clock gating is outside the subset
  e_mclock:   assert property (@(posedge clk) a ##1 @(posedge clk2) b);
                                                  //^ a clock inside a property (multi-clock) is outside the subset
  e_strong:   assert property (@(posedge clk) a |-> strong(b ##1 a));
                                                  //^ strong(...) is outside the subset
  e_past:     assert property (@(posedge clk) a |-> $past(b, 1, en));
                                                  //^ the gating and clock arguments of $past are outside the subset
  e_immed:    assert (a || b);
            //^ immediate assertions (assert (expr)) are outside the subset
  e_accept:   assert property (@(posedge clk) accept_on (en) a |=> b);
                                            //^ accept_on is outside the subset
  always @(posedge clk) begin
    if (en) assert property (a |-> b);
          //^ assert property inside a procedural block or generate is outside the subset
  end
endmodule

property p_local;
  int x;
//^ local variables in sequences and properties are outside the subset
  @(posedge clk) a |-> b;
endproperty
