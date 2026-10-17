// Tiny Manchester transmitter + testbench for the wavefw demo.
// Sends a byte LSB first: 2 start bits (1), 8 data bits, even parity, then idle gap.
// Manchester: first half of the cell = bit, second half = ~bit (edge mid-cell).
`timescale 1ns/1ps
module mc_tx (
  input  logic       clk, rst_n, start,
  input  logic [7:0] data,
  output logic       txd, busy, done,
  output logic [1:0] state,
  output logic [3:0] bit_cnt
);
  localparam logic [1:0] S_IDLE = 0, S_START = 1, S_DATA = 2, S_PAR = 3;
  localparam int HALF = 4;                 // clocks per half bit
  logic [2:0] div;  logic half;  logic [7:0] sr;  logic par;
  assign busy = state != S_IDLE;
  wire cur = (state == S_START) ? 1'b1 : (state == S_DATA) ? sr[0] : par;
  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) begin
      state <= S_IDLE; div <= 0; half <= 0; sr <= 0; par <= 0; bit_cnt <= 0; txd <= 0; done <= 0;
    end else begin
      done <= 0;
      if (state == S_IDLE) begin
        txd <= 0;
        if (start) begin state <= S_START; sr <= data; par <= ^data; bit_cnt <= 0; div <= 0; half <= 0; end
      end else begin
        txd <= half ? ~cur : cur;
        div <= div + 1;
        if (div == HALF - 1) begin
          div <= 0; half <= ~half;
          if (half) begin                    // end of bit cell
            bit_cnt <= bit_cnt + 1;
            case (state)
              S_START: if (bit_cnt == 1) begin state <= S_DATA; bit_cnt <= 0; end
              S_DATA:  begin sr <= sr >> 1; if (bit_cnt == 7) begin state <= S_PAR; bit_cnt <= 0; end end
              S_PAR:   begin state <= S_IDLE; done <= 1; end
              default: state <= S_IDLE;
            endcase
          end
        end
      end
    end
endmodule

module demo_tb;
  logic clk = 0, rst_n = 0, start = 0;
  logic [7:0] data = 8'h00;
  logic txd, busy, done;  logic [1:0] state;  logic [3:0] bit_cnt;
  logic [7:0] rx_sr = 8'h00;              // last byte the TB saw completed (done strobe)
  mc_tx u_tx (.*);
  always #5 clk = ~clk;                    // 100 MHz
  initial begin
    if ($test$plusargs("trace")) begin $dumpfile("demo.vcd"); $dumpvars(0, demo_tb); end
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
