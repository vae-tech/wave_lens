// Preprocessor and constants: comments of both kinds, `define with and without arguments, line continuation,
// `ifdef / `ifndef / `elsif / `else / `endif, `undef, `timescale, localparam / parameter values, $clog2, size casts.
`timescale 1ns/1ps
`define CLK   @(posedge clk)
`define RST   disable iff (!rst_n)
`define WIN(lo, hi = 4) ##[lo:hi]
`define HANDSHAKE(v, r) \
    v && !r |=> v
`define CHECK_LEN 8

module preproc #(parameter int W = 8, parameter int N = W / 2) (input logic clk, rst_n, valid, ready, start, done, input logic [W-1:0] data);
  localparam int DEPTH = 2 ** N;
  localparam int AW = $clog2(DEPTH);
  localparam logic [1:0] TWO = 2'(N - 2);

  /* a block comment
     over several lines with a `define inside: `NOT_A_MACRO */
  m_simple:  assert property (`CLK `RST start |-> `WIN(1) done);
  m_args:    assert property (`CLK `RST start |-> `WIN(2, `CHECK_LEN) done);
  m_cont:    assert property (`CLK `RST `HANDSHAKE(valid, ready));
  m_consts:  assert property (`CLK start |-> ##AW done ##TWO !done ##[1:N] data != 0);

`ifdef FORMAL
  m_formal:  assume property (`CLK !start);
`elsif SIM_FAST
  m_fast:    assert property (`CLK start |-> ##1 done);
`else
  m_default: assert property (`CLK start |-> ##[1:DEPTH] done);
`endif
`ifndef NO_X_CHECKS
  m_x:       assert property (`CLK valid |-> !$isunknown(data));
`endif
`undef WIN
`ifdef WIN
  m_never:   assert property (`CLK 0);
`endif
endmodule
