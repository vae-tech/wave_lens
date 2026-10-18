// Examples adapted from IEEE 1800-2017 clause 16 (concurrent assertions).
module ieee16 (input logic clk, a, b, c, d, e, te1, te2, te3, te4, te5, req, ack, rst, start_transfer, end_transfer,
               trdy, irdy, frame, burst_mode, write_en, data_end, ready, enable, done);
  // 16.7 sequences
  e16_7a: cover  property (@(posedge clk) a ##1 b ##1 c);
  e16_7b: assert property (@(posedge clk) req ##[4:32] ack);
  // 16.9.2 repetition
  e16_9a: cover  property (@(posedge clk) a ##1 b[*3:4] ##1 c);
  e16_9b: cover  property (@(posedge clk) (a ##2 b)[*5]);
  e16_9c: cover  property (@(posedge clk) a ##1 b[->2] ##1 c);
  e16_9d: cover  property (@(posedge clk) a ##1 b[=2] ##1 c);
  // 16.9.5 and, 16.9.6 intersect, 16.9.7 or
  e16_9e: cover  property (@(posedge clk) (te1 ##2 te2) and (te3 ##2 te4 ##2 te5));
  e16_9f: cover  property (@(posedge clk) (te1 ##[1:5] te2) intersect (te3 ##2 te4 ##2 te5));
  e16_9g: cover  property (@(posedge clk) (te1 ##2 te2) or (te3 ##2 te4 ##2 te5));
  // 16.9.8 first_match
  e16_9h: cover  property (@(posedge clk) first_match(te1 ##[2:5] te2));
  // 16.9.9 throughout: a burst keeps burst_mode high
  e16_9i: assert property (@(posedge clk) $fell(burst_mode) ##0 ((!burst_mode) throughout (##2 ((trdy == 0) && (irdy == 0)) [*7])));
  // 16.9.10 within
  e16_9j: assert property (@(posedge clk) $fell(frame) |-> (!trdy[*7]) within ($fell(irdy) ##1 !irdy[*8]));
  // 16.12 implication
  e16_12a: assert property (@(posedge clk) disable iff (rst) req |-> ##[1:3] ack);
  e16_12b: assert property (@(posedge clk) start_transfer |=> !end_transfer[*0:$] ##1 end_transfer);
  e16_12c: assert property (@(posedge clk) write_en |-> ##1 (data_end[->1]) ##1 ready);
  // 16.12.8 if-else
  e16_12d: assert property (@(posedge clk) a |-> if (b) ##1 c else ##2 d);
  // 16.12.11 always, 16.12.13 eventually
  e16_12e: assert property (@(posedge clk) enable |-> always [1:3] !done);
  e16_12f: assert property (@(posedge clk) enable |-> s_eventually done);
endmodule
