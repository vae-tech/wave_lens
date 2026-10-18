/*
================================================================================
  preproc
  Preprocessor and constants: comments of both kinds, `define with and
  without arguments, line continuation, `ifdef / `ifndef / `elsif / `else /
  `endif, `undef, `timescale, localparam / parameter values, $clog2, size
  casts.
================================================================================

    Parsed with no -D: FORMAL and SIM_FAST are undefined, so only the `else
    branch (m_default) and the `ifndef branch (m_x) count; m_never sits in an
    `ifdef of a macro just undefined.
    Expected:   tests/sva/golden/preproc.txt (sva/core/tests/corpus.rs)
*/

`timescale 1ns/1ps
// a clock and a reset as macros without arguments, used side by side in a property
`define CLK   @(posedge clk)
`define RST   disable iff (!rst_n)
// arguments, the second with a default value
`define WIN(lo, hi = 4) ##[lo:hi]
// a body continued on the next line with a backslash
`define HANDSHAKE(v, r) \
    v && !r |=> v
// a plain number, used as the actual of another macro
`define CHECK_LEN 8

//==============================================================================
// preproc
//==============================================================================

module preproc #(
    parameter int W = 8,
    parameter int N = W / 2
) (
    input logic         clk,
    input logic         rst_n,
    input logic         valid,
    input logic         ready,
    input logic         start,
    input logic         done,
    input logic [W-1:0] data
);
    // constants computed from the parameters: a power, $clog2, a size cast
    localparam int DEPTH = 2 ** N;
    localparam int AW = $clog2(DEPTH);
    localparam logic [1:0] TWO = 2'(N - 2);

    /* a block comment
       over several lines with a `define inside: `NOT_A_MACRO */
    // macros for the clock and reset, WIN with its default upper bound: ##[1:4]
    m_simple:  assert property (`CLK `RST start |-> `WIN(1) done);
    // both arguments given, the second a macro itself: ##[2:8]
    m_args:    assert property (`CLK `RST start |-> `WIN(2, `CHECK_LEN) done);
    // the continued macro HANDSHAKE expands to the whole property body
    m_cont:    assert property (`CLK `RST `HANDSHAKE(valid, ready));
    // localparams as delays and as a range bound: ##4, ##2, ##[1:4]
    m_consts:  assert property (`CLK start |-> ##AW done ##TWO !done ##[1:N] data != 0);

`ifdef FORMAL
    // not parsed: FORMAL is undefined (with -D FORMAL, an assume)
    m_formal:  assume property (`CLK !start);
`elsif SIM_FAST
    // not parsed: SIM_FAST is undefined
    m_fast:    assert property (`CLK start |-> ##1 done);
`else
    // the else branch is the one parsed: DEPTH as the bound, ##[1:16]
    m_default: assert property (`CLK start |-> ##[1:DEPTH] done);
`endif
`ifndef NO_X_CHECKS
    // parsed: NO_X_CHECKS is undefined
    m_x:       assert property (`CLK valid |-> !$isunknown(data));
`endif
`undef WIN
`ifdef WIN
    // not parsed: WIN was undefined just above
    m_never:   assert property (`CLK 0);
`endif
endmodule
