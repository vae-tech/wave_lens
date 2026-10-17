// AXI4-Lite master + register slave for the wavefw AXI-Lite example.
// One write (AW, then W, then B; the slave raises AWREADY a cycle late) and one read (AR, R).
`timescale 1ns/1ps
module axil_master (
  input  logic        ACLK, ARESETn,
  input  logic        cmd_wr, cmd_rd,           // one transfer per pulse
  input  logic [7:0]  cmd_addr,
  input  logic [31:0] cmd_data,
  output logic        AWVALID, WVALID, BREADY, ARVALID, RREADY,
  input  logic        AWREADY, WREADY, BVALID, ARREADY, RVALID,
  output logic [7:0]  AWADDR, ARADDR,
  output logic [31:0] WDATA,
  output logic [3:0]  WSTRB,
  input  logic [1:0]  BRESP, RRESP,
  input  logic [31:0] RDATA,
  output logic        done,
  output logic [31:0] rdata
);
  assign BREADY = 1;  assign RREADY = 1;  assign WSTRB = 4'hF;
  always_ff @(posedge ACLK or negedge ARESETn)
    if (!ARESETn) begin
      AWVALID <= 0; WVALID <= 0; ARVALID <= 0; AWADDR <= 0; ARADDR <= 0; WDATA <= 0; done <= 0; rdata <= 0;
    end else begin
      done <= 0;
      if (cmd_wr) begin AWVALID <= 1; AWADDR <= cmd_addr; WDATA <= cmd_data; end
      if (AWVALID && AWREADY) begin AWVALID <= 0; WVALID <= 1; end   // data after the address
      if (WVALID && WREADY) WVALID <= 0;
      if (BVALID) done <= 1;
      if (cmd_rd) begin ARVALID <= 1; ARADDR <= cmd_addr; end
      if (ARVALID && ARREADY) ARVALID <= 0;
      if (RVALID) begin rdata <= RDATA; done <= 1; end
    end
endmodule

module axil_regfile (input logic clk, we, input logic [1:0] waddr, raddr, input logic [31:0] wdata, output logic [31:0] rdata);
  logic [31:0] mem [4];
  assign rdata = mem[raddr];
  always_ff @(posedge clk) if (we) mem[waddr] <= wdata;
endmodule

module axil_regs (
  input  logic        ACLK, ARESETn,
  input  logic        AWVALID, WVALID, BREADY, ARVALID, RREADY,
  output logic        AWREADY, WREADY, BVALID, ARREADY, RVALID,
  input  logic [7:0]  AWADDR, ARADDR,
  input  logic [31:0] WDATA,
  input  logic [3:0]  WSTRB,
  output logic [1:0]  BRESP, RRESP,
  output logic [31:0] RDATA
);
  logic [1:0] waddr, raddr;  logic we, rd_busy;  logic [31:0] rf_q;
  axil_regfile u_regfile (.clk(ACLK), .we, .waddr, .raddr, .wdata(WDATA), .rdata(rf_q));
  assign ARREADY = !rd_busy;  assign BRESP = 2'b00;  assign RRESP = 2'b00;
  always_ff @(posedge ACLK or negedge ARESETn)
    if (!ARESETn) begin
      AWREADY <= 0; WREADY <= 0; BVALID <= 0; RVALID <= 0; RDATA <= 0; waddr <= 0; raddr <= 0; we <= 0; rd_busy <= 0;
    end else begin
      AWREADY <= AWVALID && !AWREADY;              // a cycle late
      if (AWVALID && AWREADY) waddr <= AWADDR[3:2];
      WREADY <= WVALID && !WREADY;
      we <= WVALID && WREADY;                      // write the register, answer the cycle after
      BVALID <= we || (BVALID && !BREADY);
      if (ARVALID && ARREADY) begin raddr <= ARADDR[3:2]; rd_busy <= 1; end
      if (rd_busy && !RVALID) begin RVALID <= 1; RDATA <= rf_q; end
      if (RVALID && RREADY) begin RVALID <= 0; RDATA <= 0; rd_busy <= 0; end
    end
endmodule

module axi_lite_tb;
  logic ACLK = 0, ARESETn = 0, cmd_wr = 0, cmd_rd = 0;
  logic [7:0] cmd_addr = 0;  logic [31:0] cmd_data = 0;
  logic AWVALID, WVALID, BREADY, ARVALID, RREADY, AWREADY, WREADY, BVALID, ARREADY, RVALID, done;
  logic [7:0] AWADDR, ARADDR;  logic [31:0] WDATA, RDATA, rdata;  logic [3:0] WSTRB;  logic [1:0] BRESP, RRESP;
  string dump = "axi_lite.vcd";                 // +dump=FILE; the format (VCD / FST) is chosen when Verilator builds
  axil_master u_master (.*);
  axil_regs   u_slave (.*);
  always #5 ACLK = ~ACLK;                       // 100 MHz
  initial begin
    void'($value$plusargs("dump=%s", dump));
    if ($test$plusargs("trace")) begin $dumpfile(dump); $dumpvars(0, axi_lite_tb); end
    #12 ARESETn = 1;
    repeat (2) @(posedge ACLK);
    @(negedge ACLK) begin cmd_wr = 1; cmd_addr = 8'h08; cmd_data = 32'h1234_ABCD; end   // stimulus on the falling edge
    @(negedge ACLK) cmd_wr = 0;
    @(posedge done) repeat (2) @(posedge ACLK);
    @(negedge ACLK) begin cmd_rd = 1; cmd_addr = 8'h08; end
    @(negedge ACLK) cmd_rd = 0;
    @(posedge done) repeat (3) @(posedge ACLK);
    $finish;
  end
endmodule
