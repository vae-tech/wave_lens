/*
================================================================================
  booleans
  Boolean expressions: identifiers with dots and selects, literals in every
  radix and size, '0 '1, every operator of the subset, ?:, concatenation,
  replication, inside, a size cast.
================================================================================

    One operator family per assertion, each with its own clock, no reset.
    b_rel's signed literal (8'sd1) draws the "compared as unsigned" warning.
    Expected:   tests/sva/golden/booleans.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// booleans
//==============================================================================

module booleans (
    input logic       clk,
    input logic [7:0] data,
    input logic [7:0] addr,
    input logic [3:0] be,
    input logic [1:0] st,
    input logic       v,
    input logic       w,
    input logic       x
);
    // equality with sized hex and decimal literals
    b_eq:       assert property (@(posedge clk) data == 8'hFF |-> addr != 8'd0);
    // case equality === / !== with x and z digits, an unsized based literal
    b_case_eq:  assert property (@(posedge clk) be === 4'b1x0z |-> data !== 'h0);
    // relational operators, octal and unsized decimal literals, a signed literal (a warning)
    b_rel: assert property (
        @(posedge clk)
        data < 10 && addr <= 8'o377 || data > 'd3 && addr >= 8'sd1
    );
    // logical operators: precedence of && over ||, negation of a parenthesized term
    b_logic:    assert property (@(posedge clk) !v || w && !(x || v));
    // bitwise & | ^ ~ and a binary literal with an underscore
    b_bitwise:  assert property (@(posedge clk) (data & 8'h0F) == (addr | 8'b1010_0000) ^ ~be);
    // both spellings of xnor, ~^ and ^~, print as ~^
    b_xnor:     assert property (@(posedge clk) (be ~^ 4'hA) != (be ^~ 4'h5));
    // every reduction operator: & | ^ ~& ~| ~^
    b_reduce:   assert property (@(posedge clk) &be || |data || ^addr || ~&be || ~|st || ~^data);
    // arithmetic + - * / % and their precedence
    b_arith:    assert property (@(posedge clk) data + addr - 1 == data * 2 / 2 % 256);
    // logical and arithmetic shifts (the parentheses are dropped when printed)
    b_shift:    assert property (@(posedge clk) (data << 1) >> 1 == data >>> 0 <<< 0);
    // power with a signal exponent
    b_power:    assert property (@(posedge clk) 2 ** st <= 8);
    // the conditional operator ?: in parentheses
    b_cond:     assert property (@(posedge clk) (v ? data : addr) != 0);
    // bit, part and indexed part selects (+: and -:), which widen the signals to [>=N]
    b_select: assert property (
        @(posedge clk)
        data[7] |-> data[3:0] == addr[7:4] && be[0+:2] == be[3-:2]
    );
    // concatenation and replication
    b_concat:   assert property (@(posedge clk) {v, w, x} == 3'b101 |-> {2{be}} == {be, be});
    // inside with values, ranges and a mix of both
    b_inside: assert property (
        @(posedge clk)
        st inside {0, [2:3]} |-> data inside {[8'h10:8'h1F], 8'hFF}
    );
    // the fill literals '1 and '0
    b_fill:     assert property (@(posedge clk) be == '1 |=> data != '0);
    // hierarchical names with dots, signals that are not ports (no width)
    b_hier:     assert property (@(posedge clk) u_core.u_alu.busy |-> u_core.state != 0);
    // unary minus and plus
    b_unary:    assert property (@(posedge clk) -data != +addr);
    // a size cast 4'(...)
    b_cast:     assert property (@(posedge clk) 4'(data) == be);
endmodule
