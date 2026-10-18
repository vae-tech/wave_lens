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
      state names.  rx_status_t packs the receiver's outputs (fsm_tb.status)
      for the struct rows of the page.

    Build:  make example EX=fsm (builds both pages: fsm.html from the FST,
            fsm_all.html from the VCD with mkconfig.py --sv)
*/

`timescale 1ns/1ps

//==============================================================================
// Receiver states: IDLE -> START -> DATA (8 bits) -> STOP -> IDLE or ERROR
//==============================================================================

package uart_pkg;
    typedef enum logic [2:0] {IDLE, START, DATA, STOP, ERROR} state_t;

    // The receiver's outputs in one packed word: a dump shows it as a
    // struct scope of fields (FST, Verilator --trace-structs) or as a
    // 16-bit vector that mkconfig.py --sv takes apart (VCD).
    typedef struct packed {
        state_t     state;
        logic [2:0] bit_cnt;
        logic       valid;
        logic       frame_err;
        logic [7:0] data;
    } rx_status_t;
endpackage
