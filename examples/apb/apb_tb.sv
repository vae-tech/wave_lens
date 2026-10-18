// APB3 master + register-file slave for the wavefw APB example.
// Three transfers: a write, a read with two wait states (the slave holds PREADY low), a write to an unmapped
// address that the slave answers with PSLVERR. A passive counter (u_count) counts the finished and the failed transfers.
`timescale 1ns/1ps
package apb_pkg;
  typedef enum logic [1:0] {IDLE, SETUP, ACCESS} phase_t;   // FST dumps carry these labels
endpackage

module apb_master import apb_pkg::*; (
  input  logic        PCLK, PRESETn,
  input  logic        req, wr,                 // one transfer per req pulse
  input  logic [7:0]  addr,
  input  logic [31:0] wdata,
  output logic        PSEL, PENABLE, PWRITE,
  output logic [7:0]  PADDR,
  output logic [31:0] PWDATA,
  input  logic        PREADY, PSLVERR,
  input  logic [31:0] PRDATA,
  output logic        done, err,
  output logic [31:0] rdata,
  output phase_t      phase
);
  assign PSEL = phase != IDLE;
  assign PENABLE = phase == ACCESS;
  always_ff @(posedge PCLK or negedge PRESETn)
    if (!PRESETn) begin
      phase <= IDLE; PWRITE <= 0; PADDR <= 0; PWDATA <= 0; done <= 0; err <= 0; rdata <= 0;
    end else begin
      done <= 0;
      case (phase)
        IDLE:   if (req) begin phase <= SETUP; PWRITE <= wr; PADDR <= addr; PWDATA <= wr ? wdata : 0; end
        SETUP:  phase <= ACCESS;
        ACCESS: if (PREADY) begin
                  phase <= IDLE; done <= 1; err <= PSLVERR;
                  if (!PWRITE) rdata <= PRDATA;
                end
        default: phase <= IDLE;
      endcase
    end
endmodule

module apb_regs (                              // four registers at 0x00 … 0x0C; reads take two wait states
  input  logic        PCLK, PRESETn, PSEL, PENABLE, PWRITE,
  input  logic [7:0]  PADDR,
  input  logic [31:0] PWDATA,
  output logic        PREADY, PSLVERR,
  output logic [31:0] PRDATA
);
  logic [31:0] regs [4];
  logic [1:0]  wait_cnt;
  wire mapped = PADDR[7:4] == 0 && PADDR[1:0] == 0;
  wire access = PSEL && PENABLE;
  assign PREADY  = access && (PWRITE || !mapped || wait_cnt == 2);
  assign PSLVERR = access && PREADY && !mapped;
  assign PRDATA  = access && PREADY && !PWRITE && mapped ? regs[PADDR[3:2]] : 32'h0;
  always_ff @(posedge PCLK or negedge PRESETn)
    if (!PRESETn) begin
      wait_cnt <= 0;
      for (int i = 0; i < 4; i++) regs[i] <= 32'h0;
    end else begin
      wait_cnt <= access && !PREADY ? wait_cnt + 1 : 0;
      if (access && PREADY && PWRITE && mapped) regs[PADDR[3:2]] <= PWDATA;
    end
endmodule

module apb_count (                             // passive: counts the finished transfers and the failed ones
  input  logic       PCLK, PRESETn, done, err,
  output logic [7:0] n_done, n_err
);
  always_ff @(posedge PCLK or negedge PRESETn)
    if (!PRESETn) begin n_done <= 0; n_err <= 0; end
    else begin n_done <= n_done + 8'(done); n_err <= n_err + 8'(done && err); end
endmodule

module apb_tb;
  logic PCLK = 0, PRESETn = 0, req = 0, wr = 0;
  logic [7:0] addr = 0;  logic [31:0] wdata = 0;
  logic PSEL, PENABLE, PWRITE, PREADY, PSLVERR, done, err;
  logic [7:0] PADDR;  logic [31:0] PWDATA, PRDATA, rdata;
  apb_pkg::phase_t phase;
  string dump = "apb.vcd";                     // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds
  apb_master u_master (.*);
  apb_regs   u_regs (.*);
  logic [7:0] n_done, n_err;
  apb_count  u_count (.*);
  always #5 PCLK = ~PCLK;                      // 100 MHz
  initial begin
    void'($value$plusargs("dump=%s", dump));
    if ($test$plusargs("trace")) begin $dumpfile(dump); $dumpvars(0, apb_tb); end
    #22 PRESETn = 1;
    repeat (2) @(posedge PCLK);
    transfer(1, 8'h04, 32'hCAFE_0001);         // write
    transfer(0, 8'h04, 32'h0);                 // read: two wait states
    transfer(1, 8'h40, 32'hDEAD_BEEF);         // unmapped: PSLVERR
    repeat (3) @(posedge PCLK);
    $finish;
  end
  task automatic transfer(input logic w, input logic [7:0] a, input logic [31:0] d);   // stimulus on the falling edge
    @(negedge PCLK) begin req = 1; wr = w; addr = a; wdata = d; end
    @(negedge PCLK) req = 0;
    @(posedge done);
    @(posedge PCLK);
  endtask
endmodule
