// The enum names and packed-struct fields a VCD gets from its sources: the expected tables are in sources.json; the
// page (WaveLens.svTables, the smoke) and mkconfig.py --sv (tests/unit) read this file against it.
package p;
    typedef enum logic [1:0] {IDLE, RUN = 2'd2, DONE} st_t;
    typedef enum logic [2:0] {A0 = 3'b001, A1 = 3'b010, A2 = 3'b100} onehot_t;
    typedef enum logic [3:0] {D8 = 08, D9} dec_t;               // a leading zero: decimal
    typedef enum {NEG = -1, ZERO} signed_t;                       // a value it does not read: left out
    typedef enum logic [3:0] {S0, S4 = 1 << 2, S5} shift_t;       // an expression: left out
    typedef enum logic [1:0] {`M_A, `M_B} macro_t;                // labels by macro: left out
    typedef struct packed { st_t state; logic [3:0] cnt; logic v; } stat_t;
endpackage

module a;
    p::st_t state;                  // also in module b with another type: not labelled
    p::st_t state_q, state_d;
    p::onehot_t sel [4];            // an array
    p::dec_t d;
    p::shift_t sh;
    p::stat_t status;
    p::st_t lone;                   // a plain vector of the same name in module f: not labelled
    p::st_t init_a = p::IDLE, init_b;   // review V A10: a name after an initialiser is declared too
    p::st_t lone2;                  // in module f after an initialiser: a plain vector too
    enum {GO, STOP} inline_e;
    function automatic p::st_t next(input p::st_t x);   // a function: next and x are no signals
        return x;
    endfunction
endmodule

module b (input p::onehot_t port_i);
    p::onehot_t state;
endmodule

// review IV, Codex C2 / C4 / C5: what must not be guessed
package q;
    typedef enum logic [1:0] {C0, C1} dup_t;                      // dup_t also in package r, with other labels: no labels
    typedef struct packed { struct packed {logic b;} sub; logic [1:0] inner; } nest_t;   // a nested body: inner is no signal
endpackage
package r;
    typedef enum logic [1:0] {D0, D1} dup_t;
endpackage

module c;
    q::dup_t u;
    initial $display("function");   // a keyword in a string does not start a function
    p::st_t after_str;
    localparam int _ = 4;
    typedef enum {U0 = _, U1} us_t;                               // "_" is an identifier: not read
    us_t uvar;
    enum {V0 = 1 << 2, V1} anon_bad;                              // not read, and the name stays taken
    p::stat_t mix;                                                // a struct here, an enum in module d: no fields, no labels
    function automatic int f();
        enum {X0, X1} fstate;                                     // inside a function: no signal
        return 0;
    endfunction
endmodule

module d;
    p::st_t anon_bad;
    p::st_t mix;
endmodule

// review IV, Codex D2 / D6: one typedef name as an enum and as a struct; a string continued after a backslash
package s1;
    typedef enum logic {K0, K1} kind_t;
endpackage
package s2;
    typedef struct packed { logic z; } kind_t;
endpackage
module e;
    s1::kind_t kx;
    s2::kind_t ky;
    initial $display("continued\
function");
    p::st_t after_cont;
endmodule

// review V: a name typed in one module and a plain vector in another gets no labels (a table of
// the right width would land on the plain one)
module f;
    logic [1:0] lone;
    logic [1:0] other = f(2'd1, 2'd2), lone2;
endmodule
