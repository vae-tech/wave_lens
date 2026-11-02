// APB3 register slave under a cocotb test (test_apb.py). The testbench only holds the wires:
// cocotb drives them through VPI, and writes the running test's number into TEST_CASE and its
// phase's into TEST_STEP.
//
//   0x00  CTRL     read / write
//   0x04  ID       read only
//   0x08  DATA     read / write, two wait states on a read
//   0x0C  SCRATCH  read / write, bit 17 is lost: the bug the last test finds
//   else  PSLVERR
`timescale 1ns / 1ps

module apb_slave (
    input logic PCLK,
    input logic PRESETn,
    input logic PSEL,
    input logic PENABLE,
    input logic PWRITE,
    input logic [7:0] PADDR,
    input logic [31:0] PWDATA,
    output logic [31:0] PRDATA,
    output logic PREADY,
    output logic PSLVERR
);
    localparam logic [31:0] ID_VALUE = 32'hA5B0_0035;
    localparam int WAIT_STATES = 2;
    localparam logic [31:0] SCRATCH_BUG = 32'h0002_0000;

    logic [31:0] ctrl;
    logic [31:0] data;
    logic [31:0] scratch;
    logic [1:0] waited;

    logic access;
    logic mapped;
    logic slow;

    assign access = PSEL && PENABLE;
    assign mapped = PADDR[7:4] == 4'h0 && PADDR[1:0] == 2'b00;
    assign slow = !PWRITE && mapped && PADDR[3:2] == 2'd2;
    assign PREADY = !slow || int'(waited) == WAIT_STATES;
    assign PSLVERR = access && PREADY && !mapped;

    always_comb begin
        unique case (PADDR[3:2])
            2'd0: PRDATA = ctrl;
            2'd1: PRDATA = ID_VALUE;
            2'd2: PRDATA = data;
            default: PRDATA = scratch;
        endcase
        if (!mapped || PWRITE) begin
            PRDATA = '0;
        end
    end

    always_ff @(posedge PCLK or negedge PRESETn) begin
        if (!PRESETn) begin
            ctrl <= '0;
            data <= '0;
            scratch <= '0;
            waited <= '0;
        end else begin
            waited <= (access && !PREADY) ? waited + 2'd1 : '0;
            if (access && PREADY && PWRITE && mapped) begin
                unique case (PADDR[3:2])
                    2'd0: ctrl <= PWDATA;
                    2'd2: data <= PWDATA;
                    2'd3: scratch <= PWDATA & ~SCRATCH_BUG;
                    default: ;
                endcase
            end
        end
    end
endmodule

module cocotb_apb_tb (
    input logic PCLK,
    input logic PRESETn,
    input logic PSEL,
    input logic PENABLE,
    input logic PWRITE,
    input logic [7:0] PADDR,
    input logic [31:0] PWDATA,
    output logic [31:0] PRDATA,
    output logic PREADY,
    output logic PSLVERR
);
    // The running test and its phase: written by cocotb, read by nothing but the waves.
    // verilator lint_off UNUSEDSIGNAL
    logic [15:0] TEST_CASE /* verilator public_flat_rw */;
    logic [15:0] TEST_STEP /* verilator public_flat_rw */;
    // verilator lint_on UNUSEDSIGNAL

`ifndef VERILATOR
    // Verilator traces by itself (--trace); another simulator writes the VCD here
    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, cocotb_apb_tb);
    end
`endif

    apb_slave u_slave (.*);
endmodule
