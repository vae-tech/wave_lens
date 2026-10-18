// Declarations and instances: untyped / typed / sequence / property formals, defaults, positional and named
// arguments, a formal without a type taking the one before it, nested instances, a declaration after its use, labels.
module decls (input logic clk, rst_n, req, ack, gnt, err, input logic [7:0] data);
  sequence s_req_ack(r, a, int lo = 1, int hi = 3);
    r ##[lo:hi] a;
  endsequence : s_req_ack

  sequence s_twice(sequence s);
    s ##1 s;
  endsequence

  property p_resp(logic r, k, property after = 1'b1);
    @(posedge clk) disable iff (!rst_n)
    r |-> s_req_ack(r, k) and after;
  endproperty : p_resp

  property p_seq_arg(sequence trig, untyped v);
    trig |=> v;
  endproperty

  i_positional: assert property (p_resp(req, ack));
  i_named:      assert property (p_resp(.k(gnt), .r(req), .after(!err)));
  i_defaults:   assert property (@(posedge clk) s_req_ack(req, ack, , 5) |-> 1);
  i_seq_arg:    assert property (@(posedge clk) p_seq_arg(s_twice(req ##1 gnt), data != 0));
  i_later:      assert property (@(posedge clk) s_after_use |-> ack);
  i_nested:     assert property (@(posedge clk) s_twice(s_req_ack(req, gnt, 0, 1)) |=> !req);

  sequence s_after_use; req ##2 gnt; endsequence
endmodule
