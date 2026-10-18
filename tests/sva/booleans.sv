// Booleans: identifiers with dots and selects, literals in every radix and size, '0 '1, every operator of the subset,
// ?:, concatenation, replication, inside.
module booleans (input logic clk, input logic [7:0] data, addr, input logic [3:0] be, input logic [1:0] st, input logic v, w, x);
  b_eq:       assert property (@(posedge clk) data == 8'hFF |-> addr != 8'd0);
  b_case_eq:  assert property (@(posedge clk) be === 4'b1x0z |-> data !== 'h0);
  b_rel:      assert property (@(posedge clk) data < 10 && addr <= 8'o377 || data > 'd3 && addr >= 8'sd1);
  b_logic:    assert property (@(posedge clk) !v || w && !(x || v));
  b_bitwise:  assert property (@(posedge clk) (data & 8'h0F) == (addr | 8'b1010_0000) ^ ~be);
  b_xnor:     assert property (@(posedge clk) (be ~^ 4'hA) != (be ^~ 4'h5));
  b_reduce:   assert property (@(posedge clk) &be || |data || ^addr || ~&be || ~|st || ~^data);
  b_arith:    assert property (@(posedge clk) data + addr - 1 == data * 2 / 2 % 256);
  b_shift:    assert property (@(posedge clk) (data << 1) >> 1 == data >>> 0 <<< 0);
  b_power:    assert property (@(posedge clk) 2 ** st <= 8);
  b_cond:     assert property (@(posedge clk) (v ? data : addr) != 0);
  b_select:   assert property (@(posedge clk) data[7] |-> data[3:0] == addr[7:4] && be[0+:2] == be[3-:2]);
  b_concat:   assert property (@(posedge clk) {v, w, x} == 3'b101 |-> {2{be}} == {be, be});
  b_inside:   assert property (@(posedge clk) st inside {0, [2:3]} |-> data inside {[8'h10:8'h1F], 8'hFF});
  b_fill:     assert property (@(posedge clk) be == '1 |=> data != '0);
  b_hier:     assert property (@(posedge clk) u_core.u_alu.busy |-> u_core.state != 0);
  b_unary:    assert property (@(posedge clk) -data != +addr);
  b_cast:     assert property (@(posedge clk) 4'(data) == be);
endmodule
