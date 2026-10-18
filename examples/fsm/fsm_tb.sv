/*
================================================================================
  fsm_tb
  UART receiver (8N1, BIT clocks per bit) and its testbench: the wavefw FSM
  example, a state register of an enum type (uart_pkg::state_t).
================================================================================

    Description:
      uart_rx samples rxd in the middle of the start bit, then once per bit
      (8 data bits LSB first, then the stop bit).  The testbench sends two
      frames:
        - 0xA5 with a high stop bit: a clean byte, valid for one clock;
        - 0x3C with a low stop bit: the receiver goes STOP -> ERROR, raises
          frame_err and waits for the line to go high again.
      fsm.sva (bound into uart_rx) checks the transitions over the dump.

    Build:  make example EX=fsm (Verilator --binary --timing, a VCD with
            --trace and an FST with --trace-fst; +dump=FILE names the dump)
*/

`timescale 1ns/1ps

//==============================================================================
// uart_rx: IDLE -> START (half a bit) -> DATA (8 bits) -> STOP -> IDLE / ERROR
//==============================================================================

module uart_rx import uart_pkg::*; #(
    parameter int BIT = 4
) (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       rxd,
    output logic [7:0] data,
    output logic       valid,
    output logic       frame_err,
    output state_t     state,
    output logic [2:0] bit_cnt
);
    localparam logic [1:0] MID  = 2'(BIT / 2 - 1);  // middle of a bit
    localparam logic [1:0] LAST = 2'(BIT - 1);      // last clock of a bit

    logic [1:0] div;                                // clock within the bit
    logic [7:0] sr;                                 // data bits, shifted in LSB first

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state     <= IDLE;
            div       <= 0;
            bit_cnt   <= 0;
            sr        <= 0;
            data      <= 0;
            valid     <= 0;
            frame_err <= 0;
        end else begin
            // the flags are one-clock strobes; div counts unless a state restarts it
            valid     <= 0;
            frame_err <= 0;
            div       <= div + 1;
            case (state)
                IDLE: begin
                    div <= 0;
                    if (!rxd) begin
                        state <= START;
                    end
                end
                START: begin
                    if (div == MID) begin           // middle of the start bit: still low?
                        div     <= 0;
                        bit_cnt <= 0;
                        state   <= rxd ? IDLE : DATA;
                    end
                end
                DATA: begin
                    if (div == LAST) begin
                        div     <= 0;
                        sr      <= {rxd, sr[7:1]};
                        bit_cnt <= bit_cnt + 1;
                        if (bit_cnt == 7) begin
                            state <= STOP;
                        end
                    end
                end
                STOP: begin
                    if (div == LAST) begin
                        div <= 0;
                        if (rxd) begin              // stop bit high: the byte is good
                            data  <= sr;
                            valid <= 1;
                            state <= IDLE;
                        end else begin              // stop bit low: framing error
                            frame_err <= 1;
                            state     <= ERROR;
                        end
                    end
                end
                ERROR: begin                        // wait for the line to go high again
                    div <= 0;
                    if (rxd) begin
                        state <= IDLE;
                    end
                end
                default: begin
                    state <= IDLE;
                end
            endcase
        end
    end
endmodule

//==============================================================================
// Testbench: reset, a clean frame 0xA5, a frame 0x3C with a low stop bit
//==============================================================================

module fsm_tb;
    localparam int BIT = 4;

    // verilator lint_off PROCASSINIT
    // the clock starts at 0 from its declaration and is toggled by the always below
    logic clk = 0;
    // verilator lint_on PROCASSINIT
    logic rst_n = 0;
    logic rxd = 1;

    // verilator lint_off UNUSEDSIGNAL
    // the receiver's outputs exist only to be dumped (and checked by fsm.sva)
    logic [7:0]       data;
    logic             valid;
    logic             frame_err;
    logic [2:0]       bit_cnt;
    uart_pkg::state_t state;
    uart_pkg::rx_status_t status;                   // the same, packed: a struct row in the page
    // verilator lint_on UNUSEDSIGNAL

    assign status = '{
        state: state, bit_cnt: bit_cnt, valid: valid, frame_err: frame_err, data: data
    };

    // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds
    string dump = "fsm.vcd";

    // the receiver under test, every port on the signal of the same name
    uart_rx #(.BIT(BIT)) u_rx (.*);

    always #5 clk = ~clk;                           // 100 MHz

    initial begin
        void'($value$plusargs("dump=%s", dump));
        if ($test$plusargs("trace")) begin
            $dumpfile(dump);
            $dumpvars(0, fsm_tb);
        end
        // reset, released between clock edges, then a few idle clocks
        #12 rst_n = 1;
        repeat (3) @(posedge clk);
        send(8'hA5, 1);                             // clean frame
        send(8'h3C, 0);                             // stop bit low: framing error
        // let the receiver leave ERROR before the end
        repeat (2 * BIT) @(posedge clk);
        $finish;
    end

    // One 8N1 frame: start bit, 8 data bits LSB first, the stop bit given,
    // then two bits of idle line.  The line changes on the falling edge.
    task automatic send(input logic [7:0] b, input logic stop);
        @(negedge clk) rxd = 0;                     // start bit
        repeat (BIT - 1) @(negedge clk);
        for (int i = 0; i < 8; i++) begin           // data bits
            @(negedge clk) rxd = b[i];
            repeat (BIT - 1) @(negedge clk);
        end
        @(negedge clk) rxd = stop;                  // stop bit
        repeat (BIT - 1) @(negedge clk);
        @(negedge clk) rxd = 1;                     // idle line
        repeat (2 * BIT - 1) @(negedge clk);
    endtask
endmodule
