/*
================================================================================
  apb_tb
  APB3 master and a four-register slave for the WaveLens APB example.
================================================================================

    Description:
      Three transfers: a write, a read with two wait states (the slave holds
      PREADY low), a write to an unmapped address that the slave answers
      with PSLVERR.  A passive counter (u_count) counts the finished and the
      failed transfers.

        apb_pkg      the phase enum of the master (FST dumps carry its labels)
        apb_master   IDLE -> SETUP -> ACCESS, one transfer per req pulse
        apb_regs     four registers at 0x00 ... 0x0C; reads take two wait
                     states, an unmapped address is answered with PSLVERR
        apb_count    passive: counts the finished and the failed transfers
        apb_tb       clock, reset, the three transfers, the dump

      The assertions are in apb.sva (bound to apb_tb).

    Build:  make example EX=apb (Verilator --binary --timing --trace)
            +trace turns the dump on, +dump=FILE names it; the format
            (VCD / FST) is chosen when Verilator builds (--trace-fst).
*/

`timescale 1ns/1ps

//==============================================================================
// Package: the phase of the master's FSM
//==============================================================================

package apb_pkg;
    typedef enum logic [1:0] {IDLE, SETUP, ACCESS} phase_t;   // FST dumps carry these labels
endpackage

//==============================================================================
// APB3 master: IDLE -> SETUP (one cycle) -> ACCESS (until PREADY) -> IDLE
//==============================================================================

module apb_master import apb_pkg::*; (
    input  logic        PCLK,
    input  logic        PRESETn,
    input  logic        req,                    // one transfer per req pulse
    input  logic        wr,                     // 1: write, 0: read
    input  logic [7:0]  addr,
    input  logic [31:0] wdata,
    output logic        PSEL,
    output logic        PENABLE,
    output logic        PWRITE,
    output logic [7:0]  PADDR,
    output logic [31:0] PWDATA,
    input  logic        PREADY,
    input  logic        PSLVERR,
    input  logic [31:0] PRDATA,
    output logic        done,                   // one cycle at the end of a transfer
    output logic        err,                    // PSLVERR of the last transfer
    output logic [31:0] rdata,                  // PRDATA of the last read
    output phase_t      phase
);
    // The bus controls follow from the phase alone.
    assign PSEL    = phase != IDLE;
    assign PENABLE = phase == ACCESS;

    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            phase  <= IDLE;
            PWRITE <= 1'b0;
            PADDR  <= '0;
            PWDATA <= '0;
            done   <= 1'b0;
            err    <= 1'b0;
            rdata  <= '0;
        end else begin
            done <= 1'b0;
            case (phase)
                // A request latches the address, the direction and (for a write) the data.
                IDLE: begin
                    if (req) begin
                        phase  <= SETUP;
                        PWRITE <= wr;
                        PADDR  <= addr;
                        PWDATA <= wr ? wdata : 0;
                    end
                end
                // SETUP lasts exactly one cycle.
                SETUP: begin
                    phase <= ACCESS;
                end
                // ACCESS lasts until the slave raises PREADY.
                ACCESS: begin
                    if (PREADY) begin
                        phase <= IDLE;
                        done  <= 1'b1;
                        err   <= PSLVERR;
                        if (!PWRITE) begin
                            rdata <= PRDATA;
                        end
                    end
                end
                default: begin
                    phase <= IDLE;
                end
            endcase
        end
    end
endmodule

//==============================================================================
// APB3 slave: four registers at 0x00 ... 0x0C; reads take two wait states
//==============================================================================

module apb_regs (
    input  logic        PCLK,
    input  logic        PRESETn,
    input  logic        PSEL,
    input  logic        PENABLE,
    input  logic        PWRITE,
    input  logic [7:0]  PADDR,
    input  logic [31:0] PWDATA,
    output logic        PREADY,
    output logic        PSLVERR,
    output logic [31:0] PRDATA
);
    logic [31:0] regs [4];
    logic [1:0]  wait_cnt;                      // wait states of the current read

    // Mapped: 0x00 ... 0x0C, word aligned.  Anything else is answered with PSLVERR.
    wire mapped = PADDR[7:4] == 0 && PADDR[1:0] == 0;
    wire access = PSEL && PENABLE;

    // A write and an unmapped access end at once; a mapped read after two wait states.
    assign PREADY  = access && (PWRITE || !mapped || wait_cnt == 2);
    assign PSLVERR = access && PREADY && !mapped;
    assign PRDATA  = access && PREADY && !PWRITE && mapped ? regs[PADDR[3:2]] : 32'h0;

    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            wait_cnt <= '0;
            for (int i = 0; i < 4; i++) begin
                regs[i] <= 32'h0;
            end
        end else begin
            wait_cnt <= access && !PREADY ? wait_cnt + 1 : 0;
            if (access && PREADY && PWRITE && mapped) begin
                regs[PADDR[3:2]] <= PWDATA;
            end
        end
    end
endmodule

//==============================================================================
// Passive counter: the finished transfers and the failed ones
//==============================================================================

module apb_count (
    input  logic       PCLK,
    input  logic       PRESETn,
    input  logic       done,
    input  logic       err,
    output logic [7:0] n_done,
    output logic [7:0] n_err
);
    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            n_done <= '0;
            n_err  <= '0;
        end else begin
            n_done <= n_done + 8'(done);
            n_err  <= n_err + 8'(done && err);
        end
    end
endmodule

//==============================================================================
// Testbench
//==============================================================================

module apb_tb;
    // Stimulus, driven on the falling edge (see transfer).
    logic        PCLK;                          // starts at 0, toggled below
    logic        PRESETn = 1'b0;
    logic        req     = 1'b0;
    logic        wr      = 1'b0;
    logic [7:0]  addr    = '0;
    logic [31:0] wdata   = '0;

    // The bus.
    logic        PSEL;
    logic        PENABLE;
    logic        PWRITE;
    logic        PREADY;
    logic        PSLVERR;
    logic        done;
    logic        err;
    logic [7:0]  PADDR;
    logic [31:0] PWDATA;
    logic [31:0] PRDATA;
    /* verilator lint_off UNUSEDSIGNAL */   // outputs that exist only to be dumped
    logic [31:0] rdata;
    apb_pkg::phase_t phase;
    /* verilator lint_on UNUSEDSIGNAL */

    // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds.
    string dump = "apb.vcd";

    // The master, the slave (.* connects the bus by name).
    apb_master u_master (.*);
    apb_regs   u_regs (.*);

    /* verilator lint_off UNUSEDSIGNAL */   // the counter's outputs are only dumped
    logic [7:0] n_done;
    logic [7:0] n_err;
    /* verilator lint_on UNUSEDSIGNAL */

    // The passive counter, on done / err of the master.
    apb_count  u_count (.*);

    initial PCLK = 1'b0;
    always #5 PCLK = ~PCLK;                     // 100 MHz

    initial begin
        void'($value$plusargs("dump=%s", dump));
        if ($test$plusargs("trace")) begin
            $dumpfile(dump);
            $dumpvars(0, apb_tb);
        end

        // Reset, released between two clock edges, then two idle cycles.
        #22 PRESETn = 1;
        repeat (2) @(posedge PCLK);

        transfer(1, 8'h04, 32'hCAFE_0001);      // write
        transfer(0, 8'h04, 32'h0);              // read: two wait states
        transfer(1, 8'h40, 32'hDEAD_BEEF);      // unmapped: PSLVERR

        repeat (3) @(posedge PCLK);
        $finish;
    end

    // One transfer: req for one cycle, stimulus on the falling edge; returns one
    // cycle after the master's done.
    task automatic transfer(
        input logic        w,
        input logic [7:0]  a,
        input logic [31:0] d
    );
        @(negedge PCLK) begin
            req   = 1;
            wr    = w;
            addr  = a;
            wdata = d;
        end
        @(negedge PCLK) req = 0;
        @(posedge done);
        @(posedge PCLK);
    endtask
endmodule
