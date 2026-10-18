/*
================================================================================
  prop_ops
  Property operators: |-> |=> not and or if/else #-# #=# nexttime s_nexttime
  always s_always eventually s_eventually.
================================================================================

    The sequence busy_ok, the default clocking and the default disable iff
    come after the assertions that use them, at the end of the module: they
    still apply to every assertion (the golden shows the clock and the
    disable iff on each).  The two properties are one-line declarations.
    Expected:   tests/sva/golden/prop_ops.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// prop_ops
//==============================================================================

module prop_ops (
    input logic clk,
    input logic rst_n,
    input logic req,
    input logic ack,
    input logic gnt,
    input logic err,
    input logic mode,
    input logic start,
    input logic done,
    input logic a,
    input logic b
);
    // a property and a negated property, each declared on one line
    property p_handshake(r, k); r |-> ##[1:4] k; endproperty
    property p_never(x);        not x;           endproperty

    // overlapped implication
    p_overlap:   assert property (@(posedge clk) req |-> ack);
    // non-overlapped implication
    p_next:      assert property (@(posedge clk) req |=> ack);
    // not of a sequence
    p_not:       assert property (@(posedge clk) not (req ##1 err));
    // and of two property instances
    p_and:       assert property (@(posedge clk) p_handshake(req, ack) and p_never(err));
    // or of two implications
    p_or:        assert property (@(posedge clk) (req |-> gnt) or (req |-> ##1 ack));
    // if-else as the consequent of an implication
    p_if:        assert property (@(posedge clk) start |-> if (mode) ##1 a else ##2 b);
    // if without else around an implication
    p_if_noelse: assert property (@(posedge clk) if (mode) req |=> ack);
    // followed-by, overlapped #-#
    p_followed:  cover property  (@(posedge clk) req ##1 gnt #-# ack);
    // followed-by, non-overlapped #=#, with a leading delay range
    p_followed2: cover property  (@(posedge clk) req #=# ##[0:2] ack);
    // nexttime, the weak form, one cycle
    p_nexttime:  assert property (@(posedge clk) req |-> nexttime ack);
    // s_nexttime with a cycle count [2]
    p_nexttime2: assert property (@(posedge clk) req |-> s_nexttime [2] ack);
    // always without a range
    p_always:    assert property (@(posedge clk) $fell(rst_n) |-> always !start);
    // always with a cycle range
    p_always_r:  assert property (@(posedge clk) start |-> always [1:3] !done);
    // s_always over a sequence instance declared below (busy_ok)
    p_s_always:  assert property (@(posedge clk) start |-> s_always [0:2] busy_ok(a));
    // s_eventually without a range
    p_eventual:  assert property (@(posedge clk) start |-> s_eventually done);
    // eventually with a cycle range
    p_eventual2: assert property (@(posedge clk) start |-> eventually [1:8] done);
    // no clock of its own: the default clocking declared below gives it one
    p_inst:      assert property (p_handshake(start, done));

    // declarations after their use (busy_ok in p_s_always; the defaults for all)
    sequence busy_ok(x); x || b; endsequence
    default clocking @(posedge clk); endclocking
    default disable iff (!rst_n);
endmodule
