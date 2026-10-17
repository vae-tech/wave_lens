// UART receiver (8N1, BIT clocks per bit) + testbench for the wavefw FSM example.
// The first byte arrives clean; the second has a low stop bit, so the receiver goes STOP -> ERROR and waits for the
// line to go high again.
`timescale 1ns/1ps
module uart_rx import uart_pkg::*; #(parameter int BIT = 4) (
  input  logic       clk, rst_n, rxd,
  output logic [7:0] data,
  output logic       valid, frame_err,
  output state_t     state,
  output logic [2:0] bit_cnt
);
  localparam logic [1:0] MID = 2'(BIT / 2 - 1), LAST = 2'(BIT - 1);
  logic [1:0] div;  logic [7:0] sr;
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) begin
      state <= IDLE; div <= 0; bit_cnt <= 0; sr <= 0; data <= 0; valid <= 0; frame_err <= 0;
    end else begin
      valid <= 0; frame_err <= 0;
      div <= div + 1;
      case (state)
        IDLE:  begin div <= 0; if (!rxd) state <= START; end
        START: if (div == MID) begin          // middle of the start bit: still low?
                 div <= 0; bit_cnt <= 0; state <= rxd ? IDLE : DATA;
               end
        DATA:  if (div == LAST) begin
                 div <= 0; sr <= {rxd, sr[7:1]}; bit_cnt <= bit_cnt + 1;
                 if (bit_cnt == 7) state <= STOP;
               end
        STOP:  if (div == LAST) begin
                 div <= 0;
                 if (rxd) begin data <= sr; valid <= 1; state <= IDLE; end
                 else begin frame_err <= 1; state <= ERROR; end
               end
        ERROR: begin div <= 0; if (rxd) state <= IDLE; end
        default: state <= IDLE;
      endcase
    end
endmodule

module fsm_tb;
  localparam int BIT = 4;
  logic clk = 0, rst_n = 0, rxd = 1;
  logic [7:0] data;  logic valid, frame_err;  logic [2:0] bit_cnt;
  uart_pkg::state_t state;
  string dump = "fsm.vcd";                     // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds
  uart_rx #(.BIT(BIT)) u_rx (.*);
  always #5 clk = ~clk;                         // 100 MHz
  initial begin
    void'($value$plusargs("dump=%s", dump));
    if ($test$plusargs("trace")) begin $dumpfile(dump); $dumpvars(0, fsm_tb); end
    #12 rst_n = 1;
    repeat (3) @(posedge clk);
    send(8'hA5, 1);                             // clean frame
    send(8'h3C, 0);                             // stop bit low: framing error
    repeat (2 * BIT) @(posedge clk);
    $finish;
  end
  task automatic send(input logic [7:0] b, input logic stop);   // the line changes on the falling edge
    @(negedge clk) rxd = 0;      repeat (BIT - 1) @(negedge clk);
    for (int i = 0; i < 8; i++) begin @(negedge clk) rxd = b[i]; repeat (BIT - 1) @(negedge clk); end
    @(negedge clk) rxd = stop;   repeat (BIT - 1) @(negedge clk);
    @(negedge clk) rxd = 1;      repeat (2 * BIT - 1) @(negedge clk);
  endtask
endmodule
