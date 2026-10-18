// Scopes: package with an enum and a sequence, import in a module header, interface, checker, program, default
// clocking (named, by reference) and default disable, typedefs, module code the parser skips, bind.
package bus_pkg;
  typedef enum logic [1:0] {IDLE, REQ, WAIT, DONE} phase_t;
  localparam int TIMEOUT = 16;
  sequence s_req_done(r, d); r ##[1:TIMEOUT] d; endsequence
endpackage

interface bus_if (input logic clk);
  import bus_pkg::*;
  logic req, gnt;
  phase_t phase;
  modport master (output req, input gnt);
  i_gnt: assert property (@(posedge clk) gnt |-> phase != IDLE);
endinterface

module bus_master import bus_pkg::*; #(parameter int ID = 0) (
  input  logic   clk, rst_n,
  bus_if.master  bus,
  output phase_t phase,
  output logic [3:0] tag
);
  typedef logic [7:0] byte_t;
  byte_t last;
  clocking cb @(posedge clk); input phase; endclocking
  default clocking cb;
  default disable iff (!rst_n);

  always_ff @(posedge clk or negedge rst_n)
    if (!rst_n) phase <= IDLE;
    else case (phase)
      IDLE: if (bus.req) phase <= REQ;
      REQ:  phase <= bus.gnt ? DONE : WAIT;
      default: phase <= IDLE;
    endcase

  m_phase: assert property (phase == REQ |=> phase inside {WAIT, DONE});
  m_done:  assert property (phase == REQ |-> bus_pkg::s_req_done(1'b1, phase == DONE));
  m_tag:   assert property (phase == IDLE |-> tag[3:0] == 4'(ID) && last != 8'hFF);
endmodule

checker bus_checker (logic clk, logic req, logic gnt, int max_wait = 4);
  c_wait: assert property (@(posedge clk) req |-> ##[0:max_wait] gnt);
endchecker

program bus_test (input logic clk, output logic start);
  t_start: cover property (@(posedge clk) $rose(start));
endprogram

module tb;
  logic clk, rst_n;
  bus_if bus (.clk(clk));
  bus_master #(.ID(3)) u_master (.clk, .rst_n, .bus(bus.master), .phase(), .tag());
  initial begin clk = 0; forever #5 clk = ~clk; end
endmodule

bind bus_master bus_checker u_chk (.clk(clk), .req(bus.req), .gnt(bus.gnt));
bind bus_master: tb.u_master bus_checker u_chk2 (clk, bus.req, bus.gnt);
