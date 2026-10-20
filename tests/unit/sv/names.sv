// The name rule of docs/sva/ENGINE.md *Name resolution* case by case (tests/unit/test_svabuild.py: Python and the CLI agree)
module chk (input clk);
    a_state: assert property (@(posedge clk) state == 0);
    a_nested: assert property (@(posedge clk) !u_fifo.full);
    a_alias: assert property (@(posedge clk) data == 0);
    a_prefix: assert property (@(posedge clk) !ready);
    a_ambiguous: assert property (@(posedge clk) !valid);
    a_missing: assert property (@(posedge clk) !nope);
    a_wide: assert property (@(posedge clk) state[7:4] == 0);
endmodule
