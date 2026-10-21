/*
================================================================================
  cxp_sva_demo
  Demo checkers for the test_video dump: the operators of the engine on real
  CoaXPress traffic, and deliberate failures.
================================================================================

    Description:
      Not part of the IP's contracts (cxp_sva.sv): these show what the
      assertion panel and the waves do with sequences, on the dump of
      tb_cxp_top (test_stream_video).  Each checker uses the port names of
      a checker already bound in the simulation, so it binds to that scope
      of the dump (config "bind"):

        cxp_demo_framer_sva   ...cxp_tx_stream_pkt_i.cxp_tx_pkt_framer_i
                              .cxp_framer_sva_i  (17 stream packets,
                              17..72 words: SOP K-word, 5 header words,
                              payload with K-word inserts, CRC, EOP)
        cxp_demo_ctrl_sva     ...cxp_ctrl_bus_master_i.cxp_ctrl_exec_sva_i
                              (one control command: start, 3 busy cycles,
                              a response taken 6 cycles later)
        cxp_demo_rxlong_sva   ...cxp_rx_packet_parser_i.cxp_rxlong_sva_i
                              (one uplink long packet: 6 words, 640 cycles
                              apart)

      Operators: ##[m:n], [*n] [*m:n], goto [->n], non-consecutive [=n],
      throughout, within, intersect, first_match, and / or of sequences,
      not, if / else, |-> |=> #-#, s_eventually, $rose $fell $stable $past
      $countones, inside, sequence and property declarations with
      arguments.

      d_fail_* fail on purpose (a wrong bound, a wrong latency, a
      too-strict rule): the fail traces, ]f / [f on the waves, the
      Failures list.  d_cov_* are covers.

    Parse:  sva parse examples/test_video/cxp_sva_demo.sv
*/

//==============================================================================
// Sequences and properties shared by the checkers
//==============================================================================

// A packet: from its SOP word to its EOP word, valid on every word between.
sequence s_packet(sop, eop, valid);
    sop ##0 (valid throughout eop[->1]);
endsequence

// A handshake: req held until ack, then taken on that cycle.
property p_held_until(req, ack);
    req && !ack |=> req;
endproperty

//==============================================================================
// cxp_demo_framer_sva: the stream packet framer (cxp_tx_stream_pkt)
//==============================================================================

module cxp_demo_framer_sva (
    input logic       clk,
    input logic       rst_n,
    input logic       valid,
    input logic       sop,
    input logic       eop,
    input logic       ready,
    input logic       in_data,
    input logic       in_pkt_q,
    input logic [3:0] kmask
);
    default clocking @(posedge clk); endclocking
    default disable iff (!rst_n);

    //==========================================================================
    // Holds on the dump
    //==========================================================================

    // throughout: a packet keeps valid from its SOP to its EOP, no gaps.
    d_valid_through_packet: assert property (sop |-> valid throughout eop[->1]);

    // intersect: every stream packet is 16..80 words long (17..72 in the dump).
    d_packet_length: assert property (
        sop |-> eop[->1] intersect (1'b1 [*16:80])
    );

    // [*n]: SOP and 5 header words, then the payload starts.
    d_header_words: assert property (sop |-> !in_data [*6] ##1 in_data);

    // within: the payload rises and falls inside its packet (valid to EOP).
    d_payload_inside: assert property (
        sop |-> ($rose(in_data) [->1] ##1 $fell(in_data) [->1])
            within (valid [*1:$] ##0 eop)
    );

    // first_match: the first word after the payload is the CRC, then EOP.
    d_crc_then_eop: assert property (
        sop |-> first_match(##[1:$] $fell(in_data)) ##1 eop
    );

    // $countones, inside: a word is all data or all K codes, never mixed.
    d_kmask_whole: assert property (valid |-> $countones(kmask) inside {0, 4});

    // if / else: SOP and EOP are K words; a header or CRC word is data.
    d_k_words: assert property (
        valid |-> if (sop || eop) kmask == 4'hF else if (!in_data) kmask == 4'h0
    );

    // not: no data word between packets (after EOP only IDLE or a new SOP).
    d_gap_after_eop: assert property (not (eop ##1 valid && !sop));

    // #-# (followed by): a new valid burst is a SOP word, taken on that cycle.
    d_ready_with_sop: assert property ($rose(valid) |-> (sop #-# ready));

    // s_eventually: every packet ends (strong: open at the end of the dump fails).
    d_packet_ends: assert property (sop |-> s_eventually eop);

    // A sequence instance with arguments.
    d_packet_seq: assert property (sop |-> s_packet(sop, eop, valid));

    // A property instance: a word waits for ready (vacuous here: this bench
    // never back-pressures the framer).
    d_ready_held: assert property (p_held_until(valid, ready));

    //==========================================================================
    // Deliberate failures
    //==========================================================================

    // Too strict a bound: the long packets (72 words) break it.
    d_fail_short_packets: assert property (
        sop |-> eop[->1] intersect (1'b1 [*1:40])
    ) else $error("demo: a packet longer than 40 words");

    // Wrong: packets are not back to back (only 3 gaps of 2 cycles).
    d_fail_back_to_back: assert property (eop |-> ##[1:3] sop)
        else $error("demo: no SOP within 3 cycles of EOP");

    // Wrong: the payload has K-word inserts (kmask 4'hF inside in_data).
    d_fail_no_k_in_payload: assert property (in_data |-> kmask == 4'h0)
        else $error("demo: a K word inside the payload");

    //==========================================================================
    // Coverage
    //==========================================================================

    // A long packet: more than 60 words.
    d_cov_long_packet: cover property (sop ##1 (valid && !eop) [*60:$] ##1 eop);

    // Two packets back to back: a SOP two cycles after an EOP.
    d_cov_back_to_back: cover property (eop ##[1:2] sop);

    // A K-word insert in the payload: data, K, data.
    d_cov_k_insert: cover property (
        in_data && kmask == 0 ##1 in_data && kmask == 4'hF ##1 in_data && kmask == 0
    );
endmodule

//==============================================================================
// cxp_demo_ctrl_sva: the control executor (cxp_ctrl_bus_master)
//==============================================================================

module cxp_demo_ctrl_sva (
    input logic clk,
    input logic rst_n,
    input logic start,
    input logic busy,
    input logic idle,
    input logic free,
    input logic pending,
    input logic rsp_valid,
    input logic rsp_ready
);
    default clocking @(posedge clk); endclocking
    default disable iff (!rst_n);

    // goto + intersect: a command is answered within 2..20 cycles (5 here).
    d_rsp_latency: assert property (start |-> rsp_valid [->1] intersect (1'b1 [*2:20]));

    // [*m:n] then the response: busy for 1..16 cycles, then idle, then rsp.
    d_busy_then_rsp: assert property (
        start |=> busy [*1:16] ##1 idle ##[0:2] rsp_valid
    );

    // throughout: no new command starts while a response waits to be taken.
    d_no_start_while_rsp: assert property (
        $rose(rsp_valid) |-> !start throughout rsp_ready [->1]
    );

    // A property instance: the response holds until it is taken.
    d_rsp_held: assert property (p_held_until(rsp_valid, rsp_ready));

    // $past: a command starts only from idle, the cycle after it was pending.
    d_start_from_idle: assert property ($rose(busy) |-> $past(idle) && $past(start));

    // and of sequences: busy ends and the response comes, both within 8 cycles.
    d_both_within_8: assert property (
        start |-> (##[1:8] $fell(busy)) and (##[1:8] $rose(rsp_valid))
    );

    // Wrong: the response is not taken at once (rsp_ready 6 cycles later).
    d_fail_rsp_at_once: assert property ($rose(rsp_valid) |-> rsp_ready)
        else $error("demo: the response waited for rsp_ready");

    // Wrong: the executor is busy 3 cycles, not 1.
    d_fail_busy_one_cycle: assert property (start |=> busy ##1 !busy)
        else $error("demo: busy for more than one cycle");

    // A command from start to its response taken.
    d_cov_command: cover property (start ##[1:$] rsp_valid && rsp_ready);
endmodule

//==============================================================================
// cxp_demo_rxlong_sva: uplink long packets (cxp_rx_packet_parser)
//==============================================================================

module cxp_demo_rxlong_sva (
    input logic clk,
    input logic rst_n,
    input logic valid,
    input logic sop,
    input logic eop,
    input logic err,
    input logic in_pkt_q
);
    default clocking @(posedge clk); endclocking
    default disable iff (!rst_n);

    // [=n] (non-consecutive): this command packet has 4 middle words, then
    // its EOP word (the testbench's one read command).
    d_four_middle_words: assert property (
        sop |=> (valid && !eop) [=4] ##1 (valid && eop)
    );

    // within: the EOP comes while the parser is inside the packet.
    d_eop_inside: assert property (
        sop |-> eop [->1] within (##1 in_pkt_q [*1:$] ##1 !in_pkt_q)
    );

    // or of sequences: after a word, either the next word or the end.
    d_next_or_end: assert property (
        valid && !eop |=> (in_pkt_q [*1:$] ##0 valid) or (##[0:$] !in_pkt_q)
    );

    // $stable, $past: the parser's state changes only on a word.
    d_state_between_words: assert property (!$past(valid) |-> $stable(in_pkt_q));

    // Wrong: the uplink is slow (a word every 640 cycles), not every 100.
    d_fail_word_gap: assert property (valid && !eop |-> ##[1:100] valid)
        else $error("demo: more than 100 cycles between uplink words");
endmodule
