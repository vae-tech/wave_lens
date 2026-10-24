// The corpus design of tools/svtypes.py: every case of tests/unit/types/types.expected.json in
// one simulation (Questa: tools/questa/wavelens_types.tcl; Verilator: svtypes.py verilator).

// An FSM with an enum of its own whose width is a parameter: each instance its own table
module leaf #(
    parameter int W = 2
) (
    input  logic clk,
    input  logic rst_n
);
    typedef enum logic [W-1:0] {
        L_IDLE,
        L_RUN,
        L_LAST = (1 << W) - 1
    } lstate_t;

    lstate_t state;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= L_IDLE;
        end else begin
            case (state)
                L_IDLE: begin
                    state <= L_RUN;
                end
                L_RUN: begin
                    state <= L_LAST;
                end
                default: begin
                    state <= L_IDLE;
                end
            endcase
        end
    end
endmodule

// The same name `state` as a plain vector: no table may land on it
module plain (
    input  logic clk,
    input  logic rst_n
);
    logic [1:0] state;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= '0;
        end else begin
            state <= state + 2'd1;
        end
    end
endmodule

module types_tb;
    import types_pkg::*;

    // verilator lint_off PROCASSINIT
    // the clock starts at 0 from its declaration and is toggled by the always below
    logic clk = 0;
    // verilator lint_on PROCASSINIT
    logic rst_n = 0;

    // verilator lint_off UNUSEDSIGNAL
    // the typed variables exist only to be dumped with their types
    state_t  state;
    onehot_t oh;
    int_e    ie;
    outer_t  o;
    alias_t  al;
    byte_u   bu;
    // verilator lint_on UNUSEDSIGNAL

    // +dump=FILE; Questa writes its VCD through $dumpfile too
    string dump = "types.vcd";

    always #5 clk = ~clk;

    // two instances with different widths of the same typedef, and a generate loop of them
    leaf #(.W(2)) u_l2 (.*);
    leaf #(.W(3)) u_l3 (.*);
    plain u_plain (.*);

    for (genvar g = 0; g < 2; g++) begin : gen
        leaf #(.W(4 + g)) u_l (.*);
    end

    initial begin
        void'($value$plusargs("dump=%s", dump));
        if ($test$plusargs("trace")) begin
            $dumpfile(dump);
            $dumpvars(0, types_tb);
        end
        state = IDLE;
        oh    = OH_A;
        ie    = NEG;
        o     = '{oh: OH_C, in: '{st: DATA, code: 5'd9}, pair: 8'hA5, flag: 1'b1};
        al    = STOP;
        bu    = 8'h3C;
        #12 rst_n = 1;
        repeat (2) @(posedge clk);
        state = ERROR;
        oh    = OH_D;
        ie    = BIG;
        repeat (4) @(posedge clk);
        $finish;
    end
endmodule
