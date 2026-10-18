/*
================================================================================
  uart_pkg
  The states of the UART receiver uart_rx of examples/fsm (fsm_tb.sv).
================================================================================

    Description:
      The state register of uart_rx is a typedef enum, so a waveform can
      show it by name:
        - an FST dump carries this table itself (Verilator --trace-fst
          writes the enum), so the page takes the names from the dump;
        - a VCD has none: mkconfig.py --sv reads the typedef from here.
      sva parse / sva eval read this file before fsm.sva, which uses the
      state names.

    Build:  make example EX=fsm (builds both pages: fsm.html from the FST,
            fsm_all.html from the VCD with mkconfig.py --sv)
*/

`timescale 1ns/1ps

//==============================================================================
// Receiver states: IDLE -> START -> DATA (8 bits) -> STOP -> IDLE or ERROR
//==============================================================================

package uart_pkg;
    typedef enum logic [2:0] {IDLE, START, DATA, STOP, ERROR} state_t;
endpackage
