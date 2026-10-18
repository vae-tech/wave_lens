/*
================================================================================
  decls
  Declarations and instances: untyped / typed / sequence / property formals,
  defaults, positional and named arguments, a formal without a type taking
  the one before it, nested instances, a declaration after its use, labels.
================================================================================

    Expected:   tests/sva/golden/decls.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// decls
//==============================================================================

module decls (
    input logic       clk,
    input logic       rst_n,
    input logic       req,
    input logic       ack,
    input logic       gnt,
    input logic       err,
    input logic [7:0] data
);
    // untyped formals, then int formals with defaults; an end label repeats the name
    sequence s_req_ack(r, a, int lo = 1, int hi = 3);
        r ##[lo:hi] a;
    endsequence : s_req_ack

    // a sequence formal, used twice in the body
    sequence s_twice(sequence s);
        s ##1 s;
    endsequence

    // k has no type and takes logic from r; a property formal with a default;
    // the clock and disable iff inside the declaration
    property p_resp(logic r, k, property after = 1'b1);
        @(posedge clk) disable iff (!rst_n)
        r |-> s_req_ack(r, k) and after;
    endproperty : p_resp

    // a sequence formal as the antecedent, an untyped formal as the consequent
    property p_seq_arg(sequence trig, untyped v);
        trig |=> v;
    endproperty

    // positional actuals; after takes its default 1'b1
    i_positional: assert property (p_resp(req, ack));
    // named actuals in another order than the formals, a property actual
    i_named:      assert property (p_resp(.k(gnt), .r(req), .after(!err)));
    // an empty actual keeps the default of lo, hi is given: ##[1:5]
    i_defaults:   assert property (@(posedge clk) s_req_ack(req, ack, , 5) |-> 1);
    // a property instance whose sequence actual is an instance with a sequence actual
    i_seq_arg:    assert property (@(posedge clk) p_seq_arg(s_twice(req ##1 gnt), data != 0));
    // s_after_use is declared below, after this assertion
    i_later:      assert property (@(posedge clk) s_after_use |-> ack);
    // an instance as the actual of another instance
    i_nested:     assert property (@(posedge clk) s_twice(s_req_ack(req, gnt, 0, 1)) |=> !req);

    // the declaration after its use (i_later)
    sequence s_after_use;
        req ##2 gnt;
    endsequence
endmodule
