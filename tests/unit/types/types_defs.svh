// The widths of types_pkg by macro, in an include file: a reader of the sources has to follow
// `include and `define to get them (Questa and Verilator do; the leaf-name reader does not).
`ifndef TYPES_DEFS_SVH
`define TYPES_DEFS_SVH
`define ST_W 3
`define CODE_W (`ST_W + 2)
`endif
