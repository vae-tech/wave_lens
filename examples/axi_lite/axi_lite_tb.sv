/*
================================================================================
  axi_lite_tb
  AXI4-Lite master and a register slave for the WaveLens AXI-Lite example.
================================================================================

    Description:
      One write (AW, then W, then B; the slave raises AWREADY a cycle late)
      and one read (AR, R) of the same register.

        axil_master    one transfer per cmd_wr / cmd_rd pulse; the write
                       data follows the address; always ready for B and R
        axil_regfile   four 32-bit registers, written on we, read
                       combinationally
        axil_regs      the slave: AWREADY and WREADY a cycle after VALID,
                       BVALID the cycle after the register is written,
                       read data two cycles after the address; OKAY always
        axi_lite_tb    clock, reset, the write and the read, the dump

      The assertions are in axi_lite.sva (bound to axil_regs).

    Build:  make example EX=axi_lite (Verilator --binary --timing --trace)
            +trace turns the dump on, +dump=FILE names it; the format
            (VCD / FST) is chosen when Verilator builds (--trace-fst).
*/

`timescale 1ns/1ps

//==============================================================================
// AXI4-Lite master: one transfer per command pulse
//==============================================================================

module axil_master (
    input  logic        ACLK,
    input  logic        ARESETn,
    input  logic        cmd_wr,                 // one transfer per pulse
    input  logic        cmd_rd,                 // one transfer per pulse
    input  logic [7:0]  cmd_addr,
    input  logic [31:0] cmd_data,
    output logic        AWVALID,
    output logic        WVALID,
    output logic        BREADY,
    output logic        ARVALID,
    output logic        RREADY,
    input  logic        AWREADY,
    input  logic        WREADY,
    input  logic        BVALID,
    input  logic        ARREADY,
    input  logic        RVALID,
    output logic [7:0]  AWADDR,
    output logic [7:0]  ARADDR,
    output logic [2:0]  AWPROT,                 // unprivileged, secure, data: 0
    output logic [2:0]  ARPROT,                 // unprivileged, secure, data: 0
    output logic [31:0] WDATA,
    output logic [3:0]  WSTRB,
    /* verilator lint_off UNUSEDSIGNAL */   // the responses are always OKAY; the checker reads them
    input  logic [1:0]  BRESP,
    input  logic [1:0]  RRESP,
    /* verilator lint_on UNUSEDSIGNAL */
    input  logic [31:0] RDATA,
    output logic        done,                   // one cycle after a B or an R handshake
    output logic [31:0] rdata                   // RDATA of the last read
);
    // Always ready for a response, whole-word writes, plain accesses.
    assign BREADY = 1'b1;
    assign RREADY = 1'b1;
    assign WSTRB  = 4'hF;
    assign AWPROT = 3'b000;
    assign ARPROT = 3'b000;

    // The order of the ifs matters: a later nonblocking assignment wins.
    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            AWVALID <= 1'b0;
            WVALID  <= 1'b0;
            ARVALID <= 1'b0;
            AWADDR  <= '0;
            ARADDR  <= '0;
            WDATA   <= '0;
            done    <= 1'b0;
            rdata   <= '0;
        end else begin
            done <= 1'b0;

            // Write: the address first, the data after the AW handshake.
            if (cmd_wr) begin
                AWVALID <= 1'b1;
                AWADDR  <= cmd_addr;
                WDATA   <= cmd_data;
            end
            if (AWVALID && AWREADY) begin       // data after the address
                AWVALID <= 1'b0;
                WVALID  <= 1'b1;
            end
            if (WVALID && WREADY) begin
                WVALID <= 1'b0;
            end
            if (BVALID) begin
                done <= 1'b1;
            end

            // Read: the address, then the data with RVALID.
            if (cmd_rd) begin
                ARVALID <= 1'b1;
                ARADDR  <= cmd_addr;
            end
            if (ARVALID && ARREADY) begin
                ARVALID <= 1'b0;
            end
            if (RVALID) begin
                rdata <= RDATA;
                done  <= 1'b1;
            end
        end
    end
endmodule

//==============================================================================
// Register file of the slave: four words, combinational read
//==============================================================================

module axil_regfile (
    input  logic        clk,
    input  logic        we,
    input  logic [1:0]  waddr,
    input  logic [1:0]  raddr,
    input  logic [31:0] wdata,
    output logic [31:0] rdata
);
    logic [31:0] mem [4];

    assign rdata = mem[raddr];

    always_ff @(posedge clk) begin
        if (we) begin
            mem[waddr] <= wdata;
        end
    end
endmodule

//==============================================================================
// AXI4-Lite slave: four registers at 0x00 ... 0x0C, fixed latencies
//==============================================================================

module axil_regs (
    input  logic        ACLK,
    input  logic        ARESETn,
    input  logic        AWVALID,
    input  logic        WVALID,
    input  logic        BREADY,
    input  logic        ARVALID,
    input  logic        RREADY,
    output logic        AWREADY,
    output logic        WREADY,
    output logic        BVALID,
    output logic        ARREADY,
    output logic        RVALID,
    /* verilator lint_off UNUSEDSIGNAL */   // only the word index [3:2] is decoded
    input  logic [7:0]  AWADDR,
    input  logic [7:0]  ARADDR,
    /* verilator lint_on UNUSEDSIGNAL */
    /* verilator lint_off UNUSEDSIGNAL */   // not used by this slave (no protection checks)
    input  logic [2:0]  AWPROT,
    input  logic [2:0]  ARPROT,
    /* verilator lint_on UNUSEDSIGNAL */
    input  logic [31:0] WDATA,
    /* verilator lint_off UNUSEDSIGNAL */   // not used by this slave (plain whole-word writes)
    input  logic [3:0]  WSTRB,
    /* verilator lint_on UNUSEDSIGNAL */
    output logic [1:0]  BRESP,
    output logic [1:0]  RRESP,
    output logic [31:0] RDATA
);
    logic [1:0]  waddr;                         // register index of the write
    logic [1:0]  raddr;                         // register index of the read
    logic        we;                            // write the register this cycle
    logic        rd_busy;                       // a read is in progress
    logic [31:0] rf_q;                          // the register at raddr

    // The register file.
    axil_regfile u_regfile (
        .clk   (ACLK),
        .we,
        .waddr,
        .raddr,
        .wdata (WDATA),
        .rdata (rf_q)
    );

    // One read at a time; every response is OKAY.
    assign ARREADY = !rd_busy;
    assign BRESP   = 2'b00;
    assign RRESP   = 2'b00;

    always_ff @(posedge ACLK or negedge ARESETn) begin
        if (!ARESETn) begin
            AWREADY <= 1'b0;
            WREADY  <= 1'b0;
            BVALID  <= 1'b0;
            RVALID  <= 1'b0;
            RDATA   <= '0;
            waddr   <= '0;
            raddr   <= '0;
            we      <= 1'b0;
            rd_busy <= 1'b0;
        end else begin
            // Write channel: AWREADY and WREADY a cycle after their VALID.
            AWREADY <= AWVALID && !AWREADY;     // a cycle late
            if (AWVALID && AWREADY) begin
                waddr <= AWADDR[3:2];
            end
            WREADY <= WVALID && !WREADY;
            we     <= WVALID && WREADY;         // write the register, answer the cycle after
            BVALID <= we || (BVALID && !BREADY);

            // Read channel: take the address, answer with the register the cycle
            // after; the order of the ifs matters (a later assignment wins).
            if (ARVALID && ARREADY) begin
                raddr   <= ARADDR[3:2];
                rd_busy <= 1'b1;
            end
            if (rd_busy && !RVALID) begin
                RVALID <= 1'b1;
                RDATA  <= rf_q;
            end
            if (RVALID && RREADY) begin
                RVALID  <= 1'b0;
                RDATA   <= '0;
                rd_busy <= 1'b0;
            end
        end
    end
endmodule

//==============================================================================
// Testbench
//==============================================================================

module axi_lite_tb;
    // Stimulus, driven on the falling edge.
    logic        ACLK;                          // starts at 0, toggled below
    logic        ARESETn  = 1'b0;
    logic        cmd_wr   = 1'b0;
    logic        cmd_rd   = 1'b0;
    logic [7:0]  cmd_addr = '0;
    logic [31:0] cmd_data = '0;

    // The bus.
    logic        AWVALID;
    logic        WVALID;
    logic        BREADY;
    logic        ARVALID;
    logic        RREADY;
    logic        AWREADY;
    logic        WREADY;
    logic        BVALID;
    logic        ARREADY;
    logic        RVALID;
    logic        done;
    logic [7:0]  AWADDR;
    logic [7:0]  ARADDR;
    logic [2:0]  AWPROT;
    logic [2:0]  ARPROT;
    logic [31:0] WDATA;
    logic [31:0] RDATA;
    /* verilator lint_off UNUSEDSIGNAL */   // an output that exists only to be dumped
    logic [31:0] rdata;
    /* verilator lint_on UNUSEDSIGNAL */
    logic [3:0]  WSTRB;
    logic [1:0]  BRESP;
    logic [1:0]  RRESP;

    // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds.
    string dump = "axi_lite.vcd";

    // The master and the slave (.* connects the bus by name).
    axil_master u_master (.*);
    axil_regs   u_slave (.*);

    initial ACLK = 1'b0;
    always #5 ACLK = ~ACLK;                     // 100 MHz

    initial begin
        void'($value$plusargs("dump=%s", dump));
        if ($test$plusargs("trace")) begin
            $dumpfile(dump);
            $dumpvars(0, axi_lite_tb);
        end

        // Reset, released between two clock edges, then two idle cycles.
        #12 ARESETn = 1;
        repeat (2) @(posedge ACLK);

        // Write 0x1234_ABCD to 0x08 (stimulus on the falling edge).
        @(negedge ACLK) begin
            cmd_wr   = 1;
            cmd_addr = 8'h08;
            cmd_data = 32'h1234_ABCD;
        end
        @(negedge ACLK) cmd_wr = 0;
        @(posedge done);
        repeat (2) @(posedge ACLK);

        // Read it back from 0x08.
        @(negedge ACLK) begin
            cmd_rd   = 1;
            cmd_addr = 8'h08;
        end
        @(negedge ACLK) cmd_rd = 0;
        @(posedge done);
        repeat (3) @(posedge ACLK);

        $finish;
    end
endmodule
