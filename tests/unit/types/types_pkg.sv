// Types of the corpus of tools/svtypes.py (tests/unit/test_svtypes.py): what Questa's describe
// and Verilator's --json-only give for each dumped path, compared with types.expected.json.
`include "types_defs.svh"

package types_pkg;
    localparam int OH_W = 4;

    // values by macro width and by literal: the plain case
    typedef enum logic [`ST_W-1:0] {
        IDLE,
        START,
        DATA,
        STOP,
        ERROR
    } state_t;

    // one-hot by expressions: a reader of the text alone cannot tell the values
    typedef enum logic [OH_W-1:0] {
        OH_A = 4'b0001,
        OH_B = 4'b0001 << 1,
        OH_C = 1 << 2,
        OH_D = 8
    } onehot_t;

    // an enum on int with a negative value: two's complement on 32 bits
    typedef enum int {
        NEG  = -1,
        ZERO = 0,
        BIG  = 32'h0010_0000
    } int_e;

    // a struct inside a struct, an enum member, a packed array member
    typedef struct packed {
        state_t             st;
        logic [`CODE_W-1:0] code;
    } inner_t;

    typedef struct packed {
        onehot_t        oh;
        inner_t         in;
        logic [1:0][3:0] pair;
        logic           flag;
    } outer_t;

    // a typedef of a typedef: the same enum under another name
    typedef state_t alias_t;

    // a packed union: its members overlap, which member holds the value is not known
    typedef union packed {
        logic [7:0] raw;
        struct packed {
            logic [3:0] hi;
            logic [3:0] lo;
        } nib;
    } byte_u;
endpackage
