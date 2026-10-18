# SystemVerilog style

The style of the project's own SystemVerilog: the example testbenches and checkers (`examples/`), the engine's corpus
(`tests/sva/*.sv`), the benches and spikes (`sva/bench`, `sva/spike`). It is the style of the CoaXPress checkers in
`examples/test_video/cxp_*.sv`. `tests/sva/third_party/` is other people's code and keeps its own style.

`.editorconfig` carries the indentation and the column limit; `make fmt` runs verible-verilog-format with the same
options when it is installed; `make lint` runs `verilator --lint-only -Wall` over the testbenches.

## Layout

- Indent 4 spaces, no tabs. A continuation line is indented 4 more, or lined up under the opening parenthesis.
- At most 100 columns, comments included.
- One statement per line. No `a <= 0; b <= 0;` and no `begin stmt; stmt; end` on one line. `begin` / `end` on their
  own lines as soon as a body has more than one statement, and around every `if` / `case` arm of an `always_ff`.
- `always_ff`:

  ```systemverilog
  always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) begin
          state_q <= IDLE;              // one reset assignment per line
          cnt_q   <= '0;
      end else begin
          case (state_q)
              IDLE: begin
                  if (start) begin
                      state_q <= RUN;
                  end
              end
              default: begin
                  state_q <= IDLE;
              end
          endcase
      end
  end
  ```

  The `case` label on its own line, the body indented, `default:` always.
- Declarations: one signal per line; in a port list the directions, types, widths and names are aligned
  (`input  logic [31:0] WDATA,`); ANSI ports one per line. `.*` is fine in a testbench, with a comment that says what
  the instance is.
- Spaces around binary operators and after commas; none inside parentheses. Literals with their width where it
  matters (`1'b0`, `'0`, `8'h40`).

## Comments

- A file header:

  ```systemverilog
  /*
  ================================================================================
    apb_tb
    APB3 master and a four-register slave: a write, a read with wait states, a
    write to an unmapped address answered with PSLVERR.
  ================================================================================

      Build:  make example EX=apb (Verilator --binary --timing --trace)
  */
  ```

  Name, purpose, what it checks or produces, how to build it. Author / Created / Versions as you like.
- A banner between modules, checkers and the larger parts of a module:

  ```systemverilog
  //==============================================================================
  // Phase FSM: IDLE -> SETUP (one cycle) -> ACCESS (until PREADY) -> IDLE
  //==============================================================================
  ```

- Before every assertion and cover a line that says **why** it holds or what it shows — the rule of the protocol with
  its section where there is one (`// APB3 3.1: the address holds from SETUP to the end of ACCESS`), not a
  restatement of the expression.
- At least a fifth of the lines are comments in a checker; a testbench says what each phase of its stimulus shows.

## Assertions

```systemverilog
// AXI4 A3.2.1: once VALID is high it stays high until the handshake
a_aw_valid_held: assert property (
    @(posedge ACLK) disable iff (!ARESETn)
    AWVALID && !AWREADY |=> AWVALID
) else $error("axi: AWVALID dropped before AWREADY");
```

- `label: assert property (`, then the clock and `disable iff`, then the body, then `) else $error("module: what",
  args);` — the layout of `a_trig_contiguous` in `cxp_sva.sv`. A long body breaks after `|->` / `|=>` / `##N`, the
  continuation indented 4.
- A short checker may use `default clocking` / `default disable iff` and one-line assertions that fit in 100 columns.
- Names: `a_*` assert, `c_*` cover, `s_*` sequence, `p_*` property (and parameters: `p_DEPTH`), `u_*` instances,
  `*_q` registers, `*_t` types — as in `cxp_*.sv`. Files whose labels a test or a config names keep those labels
  (the examples' `apb_*`, `axi_*`, `fsm_*`; the corpus' goldens): rename only with the configs and expectations.

## The corpus

`tests/sva/*.sv` feed the golden files `tests/sva/golden/*.txt`, which print the line of every assertion: after a
change of layout `make sva-bless` rewrites them and the diff must show nothing but `line N`. In `tests/sva/err_*.sv`
an expected error is a caret comment `//      ^ message` under the line, at the error's **column**, or
`// expect-error: -1:5 message` (a line relative to the comment, a column): moving code moves its marker with it, and
an indent moves the caret by the same number of columns (`sva/core/tests/corpus.rs`).
