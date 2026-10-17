// States of the UART receiver in examples/fsm. An FST dump carries this table (state names straight from the dump);
// for a VCD, mkconfig.py --sv reads it from here (make example EX=fsm builds both pages).
`timescale 1ns/1ps
package uart_pkg;
  typedef enum logic [2:0] {IDLE, START, DATA, STOP, ERROR} state_t;
endpackage
