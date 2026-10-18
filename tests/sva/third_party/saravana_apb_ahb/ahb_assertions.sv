// ============================================
// AHB SVA Assertions — 15 Protocol Rules
// Author: Saravana Kumar T J A
// ============================================
module ahb_assertions (
    input logic        HCLK,
    input logic        HRESETn,
    input logic [31:0] HADDR,
    input logic [1:0]  HTRANS,
    input logic        HWRITE,
    input logic [2:0]  HSIZE,
    input logic [2:0]  HBURST,
    input logic        HSEL,
    input logic [31:0] HWDATA,
    input logic [31:0] HRDATA,
    input logic        HREADY,
    input logic [1:0]  HRESP
);

    // HTRANS encoding
    localparam IDLE   = 2'b00;
    localparam BUSY   = 2'b01;
    localparam NONSEQ = 2'b10;
    localparam SEQ    = 2'b11;

    // ── Rule 1: SEQ needs prior NONSEQ/SEQ ───
    AHB_R01_SEQ_AFTER_NONSEQ: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HTRANS == SEQ) |->
        ($past(HTRANS) == NONSEQ || $past(HTRANS) == SEQ)
    ) else $error("VIOLATION R01: SEQ without prior NONSEQ/SEQ");

    // ── Rule 2: HTRANS stable during wait ────
    AHB_R02_HTRANS_STABLE_WAIT: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        !HREADY |=> $stable(HTRANS)
    ) else $error("VIOLATION R02: HTRANS changed during wait state");

    // ── Rule 3: HADDR stable during wait ─────
    AHB_R03_HADDR_STABLE_WAIT: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        !HREADY |=> $stable(HADDR)
    ) else $error("VIOLATION R03: HADDR changed during wait state");

    // ── Rule 4: HWDATA stable during wait ────
    AHB_R04_HWDATA_STABLE_WAIT: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HWRITE && !HREADY) |=> $stable(HWDATA)
    ) else $error("VIOLATION R04: HWDATA changed during wait state");

    // ── Rule 5: HWRITE stable during burst ───
    AHB_R05_HWRITE_STABLE_BURST: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HTRANS == SEQ) |-> $stable(HWRITE)
    ) else $error("VIOLATION R05: HWRITE changed during burst");

    // ── Rule 6: HSIZE stable during burst ────
    AHB_R06_HSIZE_STABLE_BURST: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HTRANS == SEQ) |-> $stable(HSIZE)
    ) else $error("VIOLATION R06: HSIZE changed during burst");

    // ── Rule 7: Reset clears HTRANS ──────────
    AHB_R07_RESET_IDLE: assert property (
        @(posedge HCLK)
        !HRESETn |-> (HTRANS == IDLE)
    ) else $error("VIOLATION R07: HTRANS not IDLE during reset");

    // ── Rule 8: HSEL during active transfer ──
    AHB_R08_HSEL_ACTIVE: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HTRANS == NONSEQ || HTRANS == SEQ) |-> HSEL
    ) else $error("VIOLATION R08: HSEL=0 during active transfer");

    // ── Rule 9: HADDR increment in SEQ ───────
    AHB_R09_ADDR_INCREMENT: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HTRANS == SEQ && HREADY && HBURST == 3'b011) |->
        (HADDR == $past(HADDR) + 32'd4)
    ) else $error("VIOLATION R09: HADDR not incrementing in INCR4 burst");

    // ── Rule 10: No SEQ in IDLE state ────────
    AHB_R10_NO_SEQ_IN_IDLE: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HTRANS == IDLE) |=> (HTRANS != SEQ)
    ) else $error("VIOLATION R10: SEQ follows IDLE");

    // ── Rule 11: HRESP stable for 2 cycles ───
    AHB_R11_HRESP_ERROR_2CYC: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HRESP == 2'b01 && !HREADY) |=> (HRESP == 2'b01)
    ) else $error("VIOLATION R11: HRESP ERROR not held 2 cycles");

    // ── Rule 12: HBURST stable during burst ──
    AHB_R12_HBURST_STABLE: assert property (
        @(posedge HCLK) disable iff (!HRESETn)
        (HTRANS == SEQ) |-> $stable(HBURST)
    ) else $error("VIOLATION R12: HBURST changed during burst");

    // ── Cover: NONSEQ occurred ────────────────
    AHB_COV_NONSEQ: cover property (
        @(posedge HCLK) (HTRANS == NONSEQ)
    );

    // ── Cover: SEQ burst occurred ─────────────
    AHB_COV_SEQ: cover property (
        @(posedge HCLK) (HTRANS == SEQ)
    );

    // ── Cover: Wait state occurred ────────────
    AHB_COV_WAIT: cover property (
        @(posedge HCLK) !HREADY
    );

    // ── Cover: ERROR response occurred ────────
    AHB_COV_ERROR: cover property (
        @(posedge HCLK) (HRESP == 2'b01)
    );

endmodule
