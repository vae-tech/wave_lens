/*
================================================================================
  arbiter
  A round-robin arbiter with four requesters: one grant at a time, only to a
  requester, every request served.
================================================================================

    Exercises:  a parameter computed from another one (MAX_WAIT = 3 * N),
                properties with an untyped formal used as a bit index, their
                instances with constant actuals, the "and" of property
                instances, throughout, an unbounded cover (##[1:$]).
    Expected:   tests/sva/golden/arbiter.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// arbiter_checker
//==============================================================================

module arbiter_checker #(
    parameter int N        = 4,
    parameter int MAX_WAIT = 3 * N
) (
    input logic         clk,
    input logic         rst_n,
    input logic [N-1:0] req,
    input logic [N-1:0] gnt,
    input logic         lock
);
    default clocking @(posedge clk); endclocking
    default disable iff (!rst_n);

    // a request of requester i is granted within MAX_WAIT cycles (a formal as an index)
    property p_served(i);
        req[i] |-> ##[0:MAX_WAIT] gnt[i];
    endproperty

    // a grant under lock stays with its owner on the next cycle
    property p_held(i);
        gnt[i] && lock |=> gnt[i];
    endproperty

    // mutual exclusion: at most one grant at a time
    arb_onehot:    assert property ($onehot0(gnt));
    // a grant goes only to a requester: a bitwise mask compared with 0
    arb_only_req:  assert property ((gnt & ~req) == 0);
    // every request is served: p_served with the constant index 0 (signals req[>=1])
    arb_served0:   assert property (p_served(0));
    // the same for requester 1: the index widens the signals to req[>=2]
    arb_served1:   assert property (p_served(1));
    // the same for requester 2
    arb_served2:   assert property (p_served(2));
    // the same for requester 3, the highest bit of the vectors
    arb_served3:   assert property (p_served(3));
    // a locked grant is held for every requester: four property instances joined by and
    arb_lock:      assert property (p_held(0) and p_held(1) and p_held(2) and p_held(3));
    // no request, no grant
    arb_idle:      assert property (req == 0 |-> gnt == 0);
    // requester 0 left waiting while requester 1 asks twice is still served within N cycles
    arb_no_starve: assert property (req[0] && !gnt[0] throughout req[1][*2] |-> ##[0:N] gnt[0]);
    // fairness shown: the grant visits the four requesters in order
    arb_fair:      cover  property (gnt[0] ##[1:$] gnt[1] ##[1:$] gnt[2] ##[1:$] gnt[3]);
endmodule
