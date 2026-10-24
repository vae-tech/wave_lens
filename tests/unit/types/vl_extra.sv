// For tools/svtypes.py verilator only: what Questa's VCD does not have — a package's variable, unpacked arrays
// of two and three dimensions, escaped identifiers. Its VCD: p.pstate, vl_extra.two[1][2], vl_extra.u-l.st-x.
package p;
    typedef enum logic [1:0] {A, B, C} e_t;
    e_t pstate;
endpackage

module leaf (
    input logic clk
);
    p::e_t \st-x ;
    always_ff @(posedge clk) \st-x <= p::B;
endmodule

module vl_extra;
    logic clk = 0;
    p::e_t two[2][3];
    p::e_t three[2][2][2];
    leaf \u-l (.clk(clk));
endmodule
