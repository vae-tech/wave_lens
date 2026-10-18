// The constants of cxp_pkg that cxp_sva.sv reads (values from the dump's cxp_pkg scope).
package cxp_pkg;
  localparam int unsigned IDLE_MAX_INTERVAL = 100;
  localparam int unsigned TX_PORTS          = 3;
  localparam logic [3:0]  KMASK_IDLE        = 4'b0111;
  localparam logic [31:0] IDLE_WORD         = 32'hB53C3CBC;
  typedef struct packed { logic [7:0] status; logic [31:0] data; } cxp_ctrl_rsp_t;
endpackage
