/*
================================================================================
  scopes
  Scopes: a package with an enum and a sequence, an import in a module
  header, an interface, a checker, a program, default clocking (named, by
  reference) and default disable, typedefs, module code the parser skips,
  bind.
================================================================================

    The procedural code (always_ff without begin / end, a one-line case, an
    initial block) is there to be skipped, not checked.
    Expected:   tests/sva/golden/scopes.txt (sva/core/tests/corpus.rs)
*/

//==============================================================================
// bus_pkg: an enum, a constant and a sequence for the modules below
//==============================================================================

package bus_pkg;
    typedef enum logic [1:0] {IDLE, REQ, WAIT, DONE} phase_t;
    localparam int TIMEOUT = 16;
    // a sequence in a package, instantiated by its qualified name in bus_master
    sequence s_req_done(r, d); r ##[1:TIMEOUT] d; endsequence
endpackage

//==============================================================================
// bus_if: an assertion inside an interface, the enum through an import
//==============================================================================

interface bus_if (input logic clk);
    import bus_pkg::*;
    logic req;
    logic gnt;
    phase_t phase;
    modport master (output req, input gnt);
    // an interface signal compared with an imported enum value
    i_gnt: assert property (@(posedge clk) gnt |-> phase != IDLE);
endinterface

//==============================================================================
// bus_master: an import in the header, an interface port, a named clocking
//==============================================================================

module bus_master import bus_pkg::*; #(
    parameter int ID = 0
) (
    input  logic       clk,
    input  logic       rst_n,
    bus_if.master      bus,
    output phase_t     phase,
    output logic [3:0] tag
);
    typedef logic [7:0] byte_t;
    byte_t last;
    // a named clocking block, made the default by reference
    clocking cb @(posedge clk); input phase; endclocking
    default clocking cb;
    default disable iff (!rst_n);

    // code the parser skips: no begin / end around the if / else and the case
    always_ff @(posedge clk or negedge rst_n)
        if (!rst_n) phase <= IDLE;
        else case (phase)
            IDLE: if (bus.req) phase <= REQ;
            REQ:  phase <= bus.gnt ? DONE : WAIT;
            default: phase <= IDLE;
        endcase

    // enum values from the package, inside with an enum set
    m_phase: assert property (phase == REQ |=> phase inside {WAIT, DONE});
    // a package sequence by its qualified name: TIMEOUT resolves to 16
    m_done:  assert property (phase == REQ |-> bus_pkg::s_req_done(1'b1, phase == DONE));
    // a parameter in a size cast, a signal of a local typedef (last:8)
    m_tag:   assert property (phase == IDLE |-> tag[3:0] == 4'(ID) && last != 8'hFF);
endmodule

//==============================================================================
// bus_checker: a checker with typed formals and a default, bound below
//==============================================================================

checker bus_checker (
    logic clk,
    logic req,
    logic gnt,
    int   max_wait = 4
);
    // a checker formal with a default as the bound of a range: ##[0:4]
    c_wait: assert property (@(posedge clk) req |-> ##[0:max_wait] gnt);
endchecker

//==============================================================================
// bus_test: a cover in a program
//==============================================================================

program bus_test (
    input  logic clk,
    output logic start
);
    // a cover on an output port of a program
    t_start: cover property (@(posedge clk) $rose(start));
endprogram

//==============================================================================
// tb: instances only, the parser skips them
//==============================================================================

module tb;
    logic clk;
    logic rst_n;
    bus_if bus (.clk(clk));
    // the master with .name connections and empty ones
    bus_master #(.ID(3)) u_master (.clk, .rst_n, .bus(bus.master), .phase(), .tag());
    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end
endmodule

//==============================================================================
// bind: into every bus_master (named ports), into one instance (positional)
//==============================================================================

bind bus_master bus_checker u_chk (.clk(clk), .req(bus.req), .gnt(bus.gnt));
bind bus_master: tb.u_master bus_checker u_chk2 (clk, bus.req, bus.gnt);
