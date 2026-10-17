// Tiny Manchester transmitter + testbench for the wavefw demo.
// Sends a byte LSB first: 2 start bits (1), 8 data bits, even parity, then idle gap.
// Manchester: first half of the cell = bit, second half = ~bit (edge mid-cell).
`timescale 1ns/1ps
package mc_pkg;
  typedef enum logic [1:0] {IDLE, START, DATA, PARITY} state_t;   // FST dumps carry these labels
endpackage

module mc_tx import mc_pkg::*; (
  input  logic       clk, rst_n, start,
  input  logic [7:0] data,
  output logic       txd, busy, done,
  output state_t     state,
  output logic [3:0] bit_cnt
);
  localparam int HALF = 4;                 // clocks per half bit
  logic [2:0] div;  logic half;  logic [7:0] sr;  logic par;
  assign busy = state != IDLE;
  wire cur = (state == START) ? 1'b1 : (state == DATA) ? sr[0] : par;
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) begin
      state <= IDLE; div <= 0; half <= 0; sr <= 0; par <= 0; bit_cnt <= 0; txd <= 0; done <= 0;
    end else begin
      done <= 0;
      if (state == IDLE) begin
        txd <= 0;
        if (start) begin state <= START; sr <= data; par <= ^data; bit_cnt <= 0; div <= 0; half <= 0; end
      end else begin
        txd <= half ? ~cur : cur;
        div <= div + 1;
        if (div == HALF - 1) begin
          div <= 0; half <= ~half;
          if (half) begin                    // end of bit cell
            bit_cnt <= bit_cnt + 1;
            case (state)
              START: if (bit_cnt == 1) begin state <= DATA; bit_cnt <= 0; end
              DATA:  begin sr <= sr >> 1; if (bit_cnt == 7) begin state <= PARITY; bit_cnt <= 0; end end
              PARITY:   begin state <= IDLE; done <= 1; end
              default: state <= IDLE;
            endcase
          end
        end
      end
    end
endmodule

module demo_tb;
  logic clk = 0, rst_n = 0, start = 0;
  logic [7:0] data = 8'h00;
  logic txd, busy, done;  mc_pkg::state_t state;  logic [3:0] bit_cnt;
  string dump = "demo.vcd";               // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds
  logic [7:0] rx_sr = 8'h00;              // last byte the TB saw completed (done strobe)
  mc_tx u_tx (.*);
  always #5 clk = ~clk;                    // 100 MHz
  initial begin
    void'($value$plusargs("dump=%s", dump));
    if ($test$plusargs("trace")) begin $dumpfile(dump); $dumpvars(0, demo_tb); end
    #22 rst_n = 1;
    send(8'hA5); send(8'h3C);
    #200 $finish;
  end
  task automatic send(input logic [7:0] b);
    @(posedge clk) begin data <= b; start <= 1; end
    @(posedge clk) start <= 0;
    @(posedge done) rx_sr <= b;
    repeat (12) @(posedge clk);
  endtask
endmodule
