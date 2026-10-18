// ============================================
// APB SVA Assertions — 15 Protocol Rules
// Bound to APB interface signals
// Author: Saravana Kumar T J A
// ============================================
module apb_assertions (
    input logic        PCLK,
    input logic        PRESETn,
    input logic [31:0] PADDR,
    input logic        PSEL,
    input logic        PENABLE,
    input logic        PWRITE,
    input logic [31:0] PWDATA,
    input logic [31:0] PRDATA,
    input logic        PREADY,
    input logic        PSLVERR
);

    // ── Rule 1: PENABLE needs PSEL ────────────
    APB_R01_PENABLE_NEEDS_PSEL: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        PENABLE |-> PSEL
    ) else $error("VIOLATION R01: PENABLE=1 but PSEL=0");

    // ── Rule 2: Setup phase → Enable phase ────
    APB_R02_SETUP_TO_ENABLE: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        (PSEL && !PENABLE) |=> PENABLE
    ) else $error("VIOLATION R02: SETUP phase not followed by ENABLE");

    // ── Rule 3: PADDR stable during ENABLE ────
    APB_R03_PADDR_STABLE: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        PENABLE |-> $stable(PADDR)
    ) else $error("VIOLATION R03: PADDR changed during ENABLE phase");

    // ── Rule 4: PWRITE stable during ENABLE ───
    APB_R04_PWRITE_STABLE: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        PENABLE |-> $stable(PWRITE)
    ) else $error("VIOLATION R04: PWRITE changed during ENABLE phase");

    // ── Rule 5: PWDATA stable during ENABLE ───
    APB_R05_PWDATA_STABLE: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        (PENABLE && PWRITE) |-> $stable(PWDATA)
    ) else $error("VIOLATION R05: PWDATA changed during ENABLE phase");

    // ── Rule 6: PSEL stable during ENABLE ─────
    APB_R06_PSEL_STABLE: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        PENABLE |-> PSEL
    ) else $error("VIOLATION R06: PSEL deasserted during ENABLE phase");

    // ── Rule 7: After transfer PENABLE goes low
    APB_R07_PENABLE_CLEARS: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        (PENABLE && PREADY) |=> !PENABLE
    ) else $error("VIOLATION R07: PENABLE did not clear after transfer");

    // ── Rule 8: PSLVERR only when PREADY=1 ───
    APB_R08_PSLVERR_WITH_PREADY: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        PSLVERR |-> PREADY
    ) else $error("VIOLATION R08: PSLVERR=1 without PREADY=1");

    // ── Rule 9: No transfer during reset ──────
    APB_R09_RESET_CLEAR: assert property (
        @(posedge PCLK)
        !PRESETn |-> (!PSEL && !PENABLE)
    ) else $error("VIOLATION R09: Transfer active during reset");

    // ── Rule 10: Word aligned address ─────────
    APB_R10_ADDR_ALIGNED: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        PSEL |-> (PADDR[1:0] == 2'b00)
    ) else $error("VIOLATION R10: PADDR not word-aligned");

    // ── Rule 11: PSEL setup before PENABLE ────
    APB_R11_PSEL_BEFORE_PENABLE: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        $rose(PENABLE) |-> $past(PSEL)
    ) else $error("VIOLATION R11: PENABLE rose without prior PSEL");

    // ── Rule 12: PRDATA valid on read PREADY ──
    APB_R12_PRDATA_VALID: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        (PENABLE && PREADY && !PWRITE) |->
        (PRDATA !== 32'hX)
    ) else $error("VIOLATION R12: PRDATA unknown on read completion");

    // ── Rule 13: PENABLE only one cycle after PSEL
    APB_R13_PENABLE_FOLLOWS_PSEL: assert property (
        @(posedge PCLK) disable iff (!PRESETn)
        $rose(PSEL) |=> PENABLE
    ) else $error("VIOLATION R13: PENABLE not asserted cycle after PSEL");

    // ── Cover: Write transfer completed ───────
    APB_COV_WRITE: cover property (
        @(posedge PCLK) disable iff (!PRESETn)
        (PENABLE && PREADY && PWRITE)
    );

    // ── Cover: Read transfer completed ────────
    APB_COV_READ: cover property (
        @(posedge PCLK) disable iff (!PRESETn)
        (PENABLE && PREADY && !PWRITE)
    );

    // ── Cover: PSLVERR occurred ───────────────
    APB_COV_SLVERR: cover property (
        @(posedge PCLK) disable iff (!PRESETn)
        PSLVERR
    );

    // ── Cover: Wait state occurred ────────────
    APB_COV_WAIT: cover property (
        @(posedge PCLK) disable iff (!PRESETn)
        (PENABLE && !PREADY)
    );

endmodule
