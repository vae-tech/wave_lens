// What a Questa VCD leaves out (stage 14.4, tools/svtypes.py missing): an unpacked array of
// vectors and one of bytes, signals under a named generate loop and an unnamed generate
// block. make missing-fixture dumps it with `vcd add /missing_tb/*` (no -r, as the user did):
// the generate scopes go too; the types file (wavelens_types.tcl) declares every one of them.

module missing_tb;
    // verilator lint_off PROCASSINIT
    // the clock starts at 0 from its declaration and is toggled by the always below
    logic clk = 0;
    // verilator lint_on PROCASSINIT

    // verilator lint_off UNUSEDSIGNAL
    // the variables exist only to be dumped (or not)
    logic [3:0] arr  [1:4];
    logic [7:0] bytes[2];
    int         cnt;
    // verilator lint_on UNUSEDSIGNAL

    always #5 clk = ~clk;

    for (genvar g = 0; g < 2; g++) begin : gen
        logic [1:0] gv = '0;

        always_ff @(posedge clk) begin
            gv <= gv + 2'(g + 1);
        end
    end

    if (1) begin
        logic ug = 1'b0;

        always_ff @(posedge clk) begin
            ug <= ~ug;
        end
    end

    initial begin
        for (int i = 1; i <= 4; i++) begin
            arr[i] = 4'(i);
        end
        bytes[0] = 8'h11;
        bytes[1] = 8'h22;
        cnt      = 0;
        repeat (3) @(posedge clk) begin
            cnt <= cnt + 1;
        end
        $finish;
    end
endmodule
