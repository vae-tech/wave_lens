/*
================================================================================
  demo_tb
  A tiny Manchester transmitter and its testbench: the WaveLens demo
  (docs/index.html) and the dump of the SVA spike (sva/spike/demo.sva).
================================================================================

    Description:
      mc_tx sends a byte LSB first: 2 start bits (1), 8 data bits, even
      parity, then an idle gap.  Manchester code: the first half of a bit
      cell is the bit, the second half ~bit (an edge in the middle of every
      cell).  The testbench sends 0xA5 and 0x3C and records each byte when
      done strobes.

    Build:  make demo (Verilator --binary --timing --trace -> demo.vcd ->
            docs/demo_waves.js); make demo-fst for the FST (state names from
            the dump); make sva-spike evaluates sva/spike/demo.sva over the VCD
*/

`timescale 1ns/1ps

//==============================================================================
// Transmitter states
//==============================================================================

package mc_pkg;
    typedef enum logic [1:0] {IDLE, START, DATA, PARITY} state_t;  // FST dumps carry these labels
endpackage

//==============================================================================
// mc_tx: IDLE -> START (2 bits) -> DATA (8 bits) -> PARITY -> IDLE
//==============================================================================

module mc_tx import mc_pkg::*; (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       start,
    input  logic [7:0] data,
    output logic       txd,
    output logic       busy,
    output logic       done,
    output state_t     state,
    output logic [3:0] bit_cnt
);
    localparam int HALF = 4;                        // clocks per half bit

    logic [2:0] div;                                // clock within the half bit
    logic       half;                               // second half of the cell
    logic [7:0] sr;                                 // data bits, shifted out LSB first
    logic       par;                                // even parity of the byte

    assign busy = state != IDLE;

    // the bit of the current cell
    wire cur = (state == START) ? 1'b1 : (state == DATA) ? sr[0] : par;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state   <= IDLE;
            div     <= 0;
            half    <= 0;
            sr      <= 0;
            par     <= 0;
            bit_cnt <= 0;
            txd     <= 0;
            done    <= 0;
        end else begin
            done <= 0;
            if (state == IDLE) begin
                // the line rests low; start loads the byte and its parity
                txd <= 0;
                if (start) begin
                    state   <= START;
                    sr      <= data;
                    par     <= ^data;
                    bit_cnt <= 0;
                    div     <= 0;
                    half    <= 0;
                end
            end else begin
                // first half of the cell: the bit; second half: its inverse
                txd <= half ? ~cur : cur;
                div <= div + 1;
                if (div == 3'(HALF - 1)) begin
                    div  <= 0;
                    half <= ~half;
                    if (half) begin                 // end of bit cell
                        bit_cnt <= bit_cnt + 1;
                        case (state)
                            START: begin
                                if (bit_cnt == 1) begin
                                    state   <= DATA;
                                    bit_cnt <= 0;
                                end
                            end
                            DATA: begin
                                sr <= sr >> 1;
                                if (bit_cnt == 7) begin
                                    state   <= PARITY;
                                    bit_cnt <= 0;
                                end
                            end
                            PARITY: begin
                                state <= IDLE;
                                done  <= 1;
                            end
                            default: begin
                                state <= IDLE;
                            end
                        endcase
                    end
                end
            end
        end
    end
endmodule

//==============================================================================
// Testbench: reset, then the bytes 0xA5 and 0x3C
//==============================================================================

module demo_tb;
    // verilator lint_off PROCASSINIT
    // the clock starts at 0 from its declaration and is toggled by the always below
    logic clk = 0;
    // verilator lint_on PROCASSINIT
    logic rst_n = 0;
    logic start = 0;
    logic [7:0] data = 8'h00;

    // verilator lint_off UNUSEDSIGNAL
    // the transmitter's outputs exist only to be dumped (done is waited on)
    logic           txd;
    logic           busy;
    logic           done;
    mc_pkg::state_t state;
    logic [3:0]     bit_cnt;
    // verilator lint_on UNUSEDSIGNAL

    // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds
    string dump = "demo.vcd";

    // verilator lint_off UNUSEDSIGNAL
    // last byte the TB saw completed (done strobe): only for the dump
    logic [7:0] rx_sr = 8'h00;
    // verilator lint_on UNUSEDSIGNAL

    // the transmitter under test, every port on the signal of the same name
    mc_tx u_tx (.*);

    always #5 clk = ~clk;                           // 100 MHz

    initial begin
        void'($value$plusargs("dump=%s", dump));
        if ($test$plusargs("trace")) begin
            $dumpfile(dump);
            $dumpvars(0, demo_tb);
        end
        // reset, released between clock edges
        #22 rst_n = 1;
        // two bytes back to back, then an idle line to the end
        send(8'hA5);
        send(8'h3C);
        #200 $finish;
    end

    // One byte: data and a one-clock start pulse, then wait for done and a
    // gap of 12 clocks.
    // verilator lint_off INITIALDLY
    // non-blocking on purpose: the inputs change after the DUT sampled this edge
    task automatic send(input logic [7:0] b);
        @(posedge clk) begin
            data  <= b;
            start <= 1;
        end
        @(posedge clk) start <= 0;
        @(posedge done) rx_sr <= b;
        repeat (12) @(posedge clk);
    endtask
    // verilator lint_on INITIALDLY
endmodule
