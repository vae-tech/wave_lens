/*
================================================================================
  ieee16
  Examples adapted from IEEE 1800-2017 clause 16 (concurrent assertions):
  sequences, repetitions, sequence operators, implication, if-else, always
  and eventually, each tagged with its subclause.
================================================================================

    The expressions keep the standard's spelling (its redundant parentheses
    included), so the parser meets them as a reader of the standard writes them.
    Expected:   tests/sva/golden/ieee16.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// ieee16
//==============================================================================

module ieee16 (
    input logic clk,
    input logic a,
    input logic b,
    input logic c,
    input logic d,
    input logic e,
    input logic te1,
    input logic te2,
    input logic te3,
    input logic te4,
    input logic te5,
    input logic req,
    input logic ack,
    input logic rst,
    input logic start_transfer,
    input logic end_transfer,
    input logic trdy,
    input logic irdy,
    input logic frame,
    input logic burst_mode,
    input logic write_en,
    input logic data_end,
    input logic ready,
    input logic enable,
    input logic done
);
    //==========================================================================
    // 16.7 sequences
    //==========================================================================

    // 16.7: a simple sequence of three expressions one cycle apart
    e16_7a: cover  property (@(posedge clk) a ##1 b ##1 c);
    // 16.7: a delay range between two expressions
    e16_7b: assert property (@(posedge clk) req ##[4:32] ack);

    //==========================================================================
    // 16.9.2 repetition
    //==========================================================================

    // 16.9.2: a consecutive repetition with a range [*3:4]
    e16_9a: cover  property (@(posedge clk) a ##1 b[*3:4] ##1 c);
    // 16.9.2: the repetition of a parenthesized sequence
    e16_9b: cover  property (@(posedge clk) (a ##2 b)[*5]);
    // 16.9.2: goto repetition [->2]
    e16_9c: cover  property (@(posedge clk) a ##1 b[->2] ##1 c);
    // 16.9.2: non-consecutive repetition [=2]
    e16_9d: cover  property (@(posedge clk) a ##1 b[=2] ##1 c);

    //==========================================================================
    // 16.9.5 and, 16.9.6 intersect, 16.9.7 or
    //==========================================================================

    // 16.9.5: and of two sequences of different lengths
    e16_9e: cover  property (@(posedge clk) (te1 ##2 te2) and (te3 ##2 te4 ##2 te5));
    // 16.9.6: intersect, both sequences of the same length
    e16_9f: cover  property (@(posedge clk) (te1 ##[1:5] te2) intersect (te3 ##2 te4 ##2 te5));
    // 16.9.7: or of two sequences
    e16_9g: cover  property (@(posedge clk) (te1 ##2 te2) or (te3 ##2 te4 ##2 te5));

    //==========================================================================
    // 16.9.8 first_match, 16.9.9 throughout, 16.9.10 within
    //==========================================================================

    // 16.9.8: first_match of a sequence with a delay range
    e16_9h: cover  property (@(posedge clk) first_match(te1 ##[2:5] te2));
    // 16.9.9: a burst, started by the fall of burst_mode, keeps it low: throughout over a
    // leading delay and a repetition written with a space before [*7]
    e16_9i: assert property (
        @(posedge clk)
        $fell(burst_mode) ##0
            ((!burst_mode) throughout (##2 ((trdy == 0) && (irdy == 0)) [*7]))
    );
    // 16.9.10: within, the repetition of a negation (!trdy[*7] binds as (!trdy)[*7])
    e16_9j: assert property (
        @(posedge clk)
        $fell(frame) |-> (!trdy[*7]) within ($fell(irdy) ##1 !irdy[*8])
    );

    //==========================================================================
    // 16.12 implication
    //==========================================================================

    // 16.12: overlapped implication under disable iff with an active-high reset
    e16_12a: assert property (@(posedge clk) disable iff (rst) req |-> ##[1:3] ack);
    // 16.12: non-overlapped implication, a zero-or-more repetition [*0:$]
    e16_12b: assert property (
        @(posedge clk)
        start_transfer |=> !end_transfer[*0:$] ##1 end_transfer
    );
    // 16.12: a parenthesized goto repetition between delays
    e16_12c: assert property (@(posedge clk) write_en |-> ##1 (data_end[->1]) ##1 ready);

    //==========================================================================
    // 16.12.8 if-else, 16.12.11 always, 16.12.13 eventually
    //==========================================================================

    // 16.12.8: if-else with a sequence in each branch
    e16_12d: assert property (@(posedge clk) a |-> if (b) ##1 c else ##2 d);
    // 16.12.11: always with a cycle range
    e16_12e: assert property (@(posedge clk) enable |-> always [1:3] !done);
    // 16.12.13: s_eventually, the strong form
    e16_12f: assert property (@(posedge clk) enable |-> s_eventually done);
endmodule
