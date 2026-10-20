# SVA subset of wavefw (v1) — the single source of truth

This is the part of SystemVerilog Assertions (IEEE 1800-2017 clause 16) that `sva-core` reads. The parser
(`sva/core/src/`: `lex.rs`, `pre.rs`, `parse.rs`, `expr.rs`, `prop.rs`, `expand.rs`) follows this file; the corpus
`tests/sva/*.sv` has an example of the constructs of the table below (its second column names the file; `restrict`,
`cover sequence`, packed-struct ports, token pasting and `` `__LINE__ `` are tested in the unit tests of `sva/core`
instead), and the negative files `tests/sva/err_*.sv` show the errors. A construct outside the subset is an error that
names it, its position and this file (`… is outside the subset (docs/sva/LANGUAGE.md)`); the few that are skipped
without a word, or taken beyond the table, are listed under *Skipped, accepted, limited*. The rest of the file still
loads.

```sh
sva parse [--json] [--expand] [-D NAME[=VALUE]] FILE...   # one compilation unit: earlier files' macros, packages
                                                          # and declarations are seen by later ones
make sva-test                                             # unit tests + corpus + schema + CLI
```

## Files

A file holds any SystemVerilog. The parser reads what assertions need and skips the rest of a module without errors:
always blocks, assign, functions, tasks, instances, generate blocks, initial blocks, classes.

| Read | How |
|---|---|
| `module` / `macromodule` / `interface` / `program` / `checker` / `package` ... `end...` | scopes; the assertion's `scope` is the name of the one it is in |
| ANSI and non-ANSI ports, `logic [7:0] a, b;`, `wire`, `int`, typedef names (`input wire pkg::rsp_t rsp`) | signal widths (`declared`) |
| `localparam` / `parameter` (also `#(parameter ...)` in a header) | constants, evaluated in order |
| `typedef enum [type] {A, B = 5, C} t;` | the labels are constants, `t` is a type of that width |
| `typedef logic [7:0] byte_t;`, `typedef struct packed { logic [7:0] a; logic b; } s_t;` | a type of width 8, 9 (the sum of the members; an unpacked `struct`, a `union`: unknown width) |
| the same label in two modules (`a_hold` in two checkers) | the second module's is `module.label`; the first keeps `a_hold` |
| a struct port read whole (`$stable(rsp)`) | parses; in a dump a struct is a scope of fields, so the name does not resolve: read its fields (`rsp.code`) |
| `import p::*;` / `import p::name;` (also in a module header) | the names of a loaded package; an unknown package is a warning, its names are then read as signals |
| `p::NAME`, `p::seq(...)` | a name of a loaded package |
| `[default] clocking [cb] @(event); ... endclocking`, `default clocking cb;` | the clock of assertions without their own |
| `default disable iff (expr);` | the reset of assertions without their own |
| `property` / `sequence` declarations | below |
| `[label:] assert / assume / cover property (...) action_block` | below; `assume` is checked like `assert` (a flag says so) |
| `cover sequence (...)` | a cover; every match counts (flag) |
| `restrict property (...);` | skipped with a warning |
| `bind target[: inst, ...] module [#(...)] inst (ports);` | recorded for stage 6 (`binds`: target, module, instance, port connections as text) |

A checker port with a constant default (`checker c(..., int max_wait = 4)`) is also a constant of that value, so it
can bound a range.

## Grammar

EBNF-ish: `[x]` optional, `{x}` zero or more, `|` choice, `'x'` a token. Names are SystemVerilog identifiers (also
`\escaped ` ones); `hier` is `name {'.' name}` with constant indices allowed in the middle (`gen[0].u.x`).

```ebnf
property_decl  = 'property' name ['(' ports ')'] ';' property_spec [';'] 'endproperty' [':' name] ;
sequence_decl  = 'sequence' name ['(' ports ')'] ';' [clock] seq_expr [';'] 'endsequence' [':' name] ;
ports          = port {',' port} ;
port           = [type] name ['=' property_expr] ;      (* no type: untyped, or the type of the port before *)
type           = 'untyped' | 'sequence' | 'property' | data_type ;
assertion      = [name ':'] ('assert' | 'assume') 'property' '(' property_spec ')' action_block
               | [name ':'] 'cover' ('property' | 'sequence') '(' property_spec ')' action_block ;
action_block   = ';' | statement | [statement] 'else' statement ;
property_spec  = [clock] ['disable' 'iff' '(' expr ')'] property_expr ;
clock          = '@' '(' ['posedge' | 'negedge' | 'edge'] hier ')' | '@' name ;   (* a signal or a clocking block *)

property_expr  = 'always' ['[' range ']'] property_expr          (* weak; the range may be open *)
               | 's_always' '[' range ']' property_expr          (* bounded *)
               | 'eventually' '[' range ']' property_expr        (* weak, bounded *)
               | 's_eventually' ['[' range ']'] property_expr
               | 'if' '(' expr ')' property_expr ['else' property_expr]
               | implication ;
implication    = or_expr [('|->' | '|=>' | '#-#' | '#=#') property_expr] ;   (* left side: a sequence *)
or_expr        = and_expr {'or' and_expr} ;
and_expr       = not_expr {'and' not_expr} ;
not_expr       = 'not' not_expr | ('nexttime' | 's_nexttime') ['[' const ']'] not_expr | intersect ;
intersect      = within {'intersect' within} ;
within         = throughout {'within' throughout} ;
throughout     = delay ['throughout' throughout] ;             (* left side: a boolean *)
delay          = ['##' cycle_delay] repetition {'##' cycle_delay repetition} ;
cycle_delay    = number | name | pkg '::' name | '(' const ')' | '[' range ']' | '[*]' | '[+]' ;
repetition     = primary ['[*' range_or_n ']' | '[*]' | '[+]' | '[->' range_or_n ']' | '[=' range_or_n ']'] ;
primary        = expr                                         (* a boolean: matches at one tick *)
               | '(' property_expr ')'
               | 'first_match' '(' seq_expr ')'
               | [pkg '::'] name ['(' args ')'] ;             (* a sequence or property instance *)
args           = arg {',' arg} ;
arg            = [property_expr] | '.' name '(' [property_expr] ')' ;   (* positional ones first *)
range          = const ':' (const | '$') ;
range_or_n     = const [':' (const | '$')] ;
const          = expr ;                                       (* folded: numbers, parameters, constant arguments *)

expr           = cond ;
cond           = binary ['?' expr ':' expr] ;
binary         = unary {binop unary} | binary 'inside' '{' set {',' set} '}' ;
set            = expr | '[' expr ':' expr ']' ;
unary          = unop unary | operand {'[' expr [(':' | '+:' | '-:') expr] ']'} ;
operand        = number | ''0' | ''1' | ''x' | ''z' | hier | pkg '::' name | '(' expr ')'
               | '{' expr {',' expr} '}' | '{' expr '{' expr {',' expr} '}' '}'
               | sysfunc '(' [expr {',' expr}] ')' | decimal ''(' expr ')' | ident ''(' expr ')' ;   (* size casts; ident: a constant *)
```

Numbers: `12`, `1_000`, `8'hFF`, `4'b10x1`, `6'o17`, `10'd1023`, `'hDEAD_BEEF`, `8'sd5`, with `x` / `z` / `?` digits;
at most 64 bits. A size cast `N'(expr)` is in, also with a constant name for `N` (`p_PTR_W'(p_DEPTH)`, a parameter); type
casts `int'(x)` are not.

## Constructs, one example each

| Construct | Example (corpus file) |
|---|---|
| boolean | `req && !busy` (booleans.sv) |
| `##n`, `##0`, `##N` (constant) | `req |-> ##2 ack`, `req ##0 gnt`, `req |-> ##LAT gnt` (delays.sv) |
| `##[m:n]`, `##[m:$]` | `req |-> ##[1:3] ack`, `req |-> ##[1:$] done` |
| `##[*]` = `##[0:$]`, `##[+]` = `##[1:$]` | `start |-> ##[*] done`, `start |-> ##[+] done` |
| leading delay | `##1 req ##1 gnt` |
| `[*n]` `[*m:n]` `[*m:$]` `[*]` `[+]` | `a |=> b[*3] ##1 c`, `b[*1:4]`, `b[*2:$]`, `b[*]` = `[*0:$]`, `b[+]` = `[*1:$]` (repetition.sv) |
| goto `[->n]` `[->m:n]` | `req |-> gnt[->1]`, `last[->1:8]` |
| non-consecutive `[=n]` `[=m:$]` | `gnt[=2]`, `b[=1:$]` |
| repetition of a sequence | `(a ##1 b)[*2]` |
| `and` `or` (sequences) | `(a ##2 b) and (c ##1 d)`, `s_ab or s_cd(c, d)` (seq_ops.sv) |
| `intersect` | `(a ##[1:5] b) intersect (c[*3])` |
| `throughout` | `en throughout (busy[*1:$] ##1 stop)` |
| `within` | `s_cd(a, b) within (c ##[3:6] d)` |
| `first_match` | `first_match(start ##[1:4] busy) |=> stop` |
| sequence instance | `s_cd(.x(a), .y(b && c))` |
| `|->` `|=>` | `req |-> ack`, `req |=> ack` (prop_ops.sv) |
| `#-#` `#=#` | `req ##1 gnt #-# ack`, `req #=# ##[0:2] ack` |
| `not` | `not (req ##1 err)` |
| `and` `or` (properties) | `p_handshake(req, ack) and p_never(err)`, `(req |-> gnt) or (req |-> ##1 ack)` |
| `if` / `else` | `start |-> if (mode) ##1 a else ##2 b` |
| `nexttime`, `s_nexttime [n]` | `req |-> nexttime ack`, `req |-> s_nexttime [2] ack` |
| `always`, `always [m:n]`, `s_always [m:n]` | `$fell(rst_n) |-> always !start`, `always [1:3] !done`, `s_always [0:2] x` |
| `s_eventually`, `eventually [m:n]` | `start |-> s_eventually done`, `eventually [1:8] done` |
| property instance | `assert property (p_handshake(start, done));` |
| `== != === !== < <= > >=` | `be === 4'b1x0z`, `data < 10` (booleans.sv) |
| `&& || !` | `!v || w && !(x || v)` |
| `& | ^ ~ ~^ ^~` | `(data & 8'h0F) == (addr | 8'b1010_0000) ^ ~be` |
| reductions `& | ^ ~& ~| ~^` | `&be || |data || ^addr` |
| `+ - * / % **`, shifts `<< >> <<< >>>` | `data + addr - 1`, `2 ** st`, `(data << 1) >> 1` |
| `?:` | `(v ? data : addr) != 0` |
| selects `[i]` `[m:l]` `[b+:w]` `[b-:w]` | `data[7]`, `data[3:0]`, `be[0+:2]` |
| concatenation, replication | `{v, w, x} == 3'b101`, `{2{be}}` |
| `inside` | `st inside {0, [2:3]}` |
| `'0` `'1` | `be == '1` |
| hierarchical names | `u_core.u_alu.busy` |
| `$rose $fell $stable $changed` | `$rose(valid) |-> ...` (sysfuncs.sv) |
| `$past(x)`, `$past(x, n)` | `data == $past(data, 2)` |
| `$onehot $onehot0 $countones $isunknown` | `$onehot0(grant)`, `!$isunknown(data)` |
| `$sampled $bits $clog2` | `$sampled(valid)`, `$bits(grant)`, `localparam AW = $clog2(DEPTH)` |
| `` `define `` (with arguments and defaults), `` `ifdef `` / `` `ifndef `` / `` `elsif `` / `` `else `` / `` `endif ``, `` `undef ``, `\` continuation | preproc.sv |
| `localparam` / `parameter` / enum labels | preproc.sv, scopes.sv |
| default clocking / disable, packages, interface, checker, program, bind | scopes.sv |

## Precedence

High to low (IEEE 1800-2017 tables 11-2, 16-1, 16-3). A boolean operand is read as far as the expression goes, so
`a && b ##1 c` is `(a && b) ##1 c` and `a && b[*2]` repeats `a && b`.

| Level | Operators | Associativity |
|---|---|---|
| expression | `()` `[]` `.` `::` > unary `! ~ & | ^ ~& ~| ~^ - +` > `**` > `* / %` > `+ -` > `<< >> <<< >>>` > `< <= > >= inside` > `== != === !==` > `&` > `^ ~^` > `|` > `&&` > `||` > `?:` | left (`?:` right) |
| sequence | `[* ] [-> ] [= ]` | — |
| | `##` | left |
| | `throughout` | right |
| | `within` | left |
| | `intersect` | left |
| property | `not`, `nexttime`, `s_nexttime` | — |
| | `and` | left |
| | `or` | left |
| | `|->` `|=>` `#-#` `#=#` | right |
| | `always` `s_always` `eventually` `s_eventually` `if` / `else` | — (extend to the right) |

`and` / `or` of two sequences is a sequence; with a property on either side it is a property (also when a name turns
out to be a property instance during expansion). `else` goes with the nearest `if`.

## Names, instances and expansion

Each assertion is expanded before it is output (`assertions[].prop`). What remains are the signal names
(`assertions[].signals`, the clock first, with the width a select needs); how they find the variables of a dump when the
assertion is bound to an instance is one rule for the page, `mkconfig.py --sva` and `sva eval` (ENGINE.md *Name
resolution*).

- A name in a sequence position is, in this order: a formal argument (replaced by the actual, which was expanded where
  the instance is written), a sequence or property declaration (an instance without arguments), a constant (a
  `Const` node with its value), or a signal. Declarations may come after their use in the file.
- Actual arguments: positional, then named (`.x(a)`); an empty one (`s(a, , c)`) takes the default; a missing one
  without a default, an extra one, an unknown name or one given twice is an error. A formal typed `sequence` takes a
  sequence; a formal with a data type (`logic`, `int`, ...) takes an expression; `untyped` and `property` take anything.
- A sequence or property used where it does not fit is an error: a property where a sequence is needed, a sequence
  name inside a boolean (`s && x`: use the sequence as an operand of `and` or `##`), `.triggered` / `.matched`.
- Recursion (an instance of a declaration inside itself) is an error.
- Range bounds, `##N`, `nexttime [N]`, the depth of `$past` and replication counts must fold to constants:
  numbers, parameters, enum labels, constant actual arguments, with `+ - * / % ** << >> & | ^ ~ ! ?: == < ...`,
  `$clog2` and size casts, in 64-bit integer arithmetic. Negative counts and ranges that end before they start are
  errors.
- **Clock**: the assertion's own `@(...)`, else that of the property or sequence it is an instance of, else the
  scope's default clocking (searched outwards). A declaration inside with a different clock is a multi-clock error;
  none at all is an error. `@(clk)` and `@(edge clk)` mean both edges.
- **disable iff**: the assertion's own, else that of the property it is an instance of (only when that instance is
  the whole assertion), else the scope's `default disable iff`. Both the assertion and the property: an error.
- **Elements**: every boolean that can match at a tick gets an id `s1`, `s2`, ... in source order of the expanded
  tree, unique in the assertion (two instances of one sequence give different ids). Its label is its text with the
  delay that leads to it and the repetition on it: `##[1:3] ack`, `b[->2]`, `##1 (d && e)[*2]`. The condition of
  `throughout` is an element too.
- **Signals**: every signal the assertion reads, the clock first, then the reset, then in source order; `width` is
  the least width the constant selects imply (`a[7:0]` gives 8, `a[3]` gives 4, `a[b+:w]` gives b + w),
  `declared` the width from a port or declaration in the assertion's scope. Constants are not signals.
- **Label**: the statement label, else `assert_<line>` / `assume_<line>` / `cover_<line>`. **Message**: the text and
  severity of the first `$error` / `$fatal` / `$warning` / `$info` / `$display` in the fail branch of the action block
  (the pass branch for `cover`).

An error inside a declaration that an assertion led to says which: `... (in assertion 'a_x', line 12)`.

## Preprocessor

Token-based, before parsing: `` `define NAME body`` (to the end of the line, `\` continues it, also at the end of a
`//` comment line inside the body; a comment without it ends the body; directives in a body act where it is used),
`` `define NAME(a, b = 1) body `` (arguments split at top-level commas, defaults, empty arguments), uses `` `NAME `` /
`` `NAME(x, y) `` expanded and scanned again (32 levels at most), `` `undef ``, `` `ifdef `` / `` `ifndef `` /
`` `elsif `` / `` `else `` / `` `endif `` (nested), `sva parse -D NAME[=VALUE]`. `` `timescale ``,
`` `default_nettype ``, `` `resetall ``, `` `celldefine `` and the like are ignored. `` `include `` is not followed (a
warning: give the file to `sva parse` too). In a macro body, ` `` ` pastes two tokens into one (`` name``_A ``) and
`` `"text`" `` makes a string of the text between (arguments substituted); outside a body both are errors.
`` `__LINE__ `` is the line of the (outermost) use, `` `__FILE__ `` an empty string. Expanded tokens carry the
position of the macro use, so an error in an expansion points at the use. Tested on OpenTitan's `prim_assert` macro
library (tests/sva/third_party).

## Outside the subset (errors that name the construct)

`until` `s_until` `until_with` `s_until_with` `implies` `iff` `accept_on` `reject_on` `sync_accept_on`
`sync_reject_on` `case` (in properties) `strong(...)` `weak(...)` `dist` `matches` `expect`; local variables in
sequences and properties and sequence match items `(a, v = b)`; `local` / directional / `event` formals; clocks inside a
property (multi-clock), `@(... iff ...)`, events with several signals; `$past` with a gating or clock argument and other
system functions; clock arguments of sampled value functions; immediate assertions `assert (x)` / `assert final`;
concurrent assertions inside procedural code or generate blocks (written at module level they are in); `==?` `!=?`
`->` `<->` `++` `--`; strings outside messages; real numbers; type casts; assignment patterns `'{...}`; function calls
in expressions; literals wider than 64 bits; more than 500 levels of operators and parentheses in one item (an error
where it happens, instead of a stack overflow).

## Skipped, accepted, limited

**Skipped without a word** (no error, nothing in the output): `let` declarations; `parameter type` (a type
parameter); `sequence` / `property` declarations inside `generate` blocks and procedural code (an assertion there is
an error). `restrict property` is skipped with a warning (it only constrains formal tools).

**Accepted beyond the table**: `` `undefineall ``; `$write` in action blocks (its text an `info` message);
`modport` and `ref` ports (their names are signals); `^~` (read as `~^`); `a[b-:w]`; `@posedge clk` without
parentheses (not SystemVerilog, taken for `@(posedge clk)`); `##0`, `[*0]`, `[->0]` and `[=0]` (empty matches,
*Semantics*); `macromodule` (a module).

**Limits**: the operand of `not`, `nexttime`, `and`, `or` and the like cannot start with `always`, `eventually`,
`s_eventually` or `if` without parentheses (`not (always a)`); a clock with an index (`@(posedge g[0].clk)`) is not
read; a `clocking` block is a default only for what comes after it; at most 256 threads per attempt
(`--max-threads`, then `capped`), about 65 534 booleans in one assertion, 500 levels of operators and parentheses.

## Semantics the evaluator relies on

docs/sva/ENGINE.md has the evaluator, its results and every decision in full; in short:

- **Sampling.** Every signal is sampled in the preponed region: the value just before the clock edge. A value written
  at an edge counts from the next sampling point, as in a simulator. Cycle `k` is the k-th edge of the clock in the
  dump (or in the page's transitions).
- **Attempts.** An evaluation attempt starts at every cycle where `disable iff` is not true. Results per attempt:
  `pass`, `fail` (with the cycle and a note), `vacuous` (the antecedent of `|->` / `|=>` / `if` did not match: counted,
  not drawn), `active` (still waiting when the dump ends), `disabled` (`disable iff` became true at a sampling point
  while it was alive), `capped` (the thread limit dropped some of its threads: no verdict).
- **Before the first cycle.** `$past(x, n)` before cycle `n`, and the previous value `$rose` / `$fell` / `$stable` /
  `$changed` compare with at cycle 0, is the initial value of the signal's type: x for 4-state signals, 0 for 2-state
  ones (`bit`, `int`, ...). So `$rose(a)` holds at cycle 0 when `a` is 1 there (x -> 1 is a rise).
- **Unknown values.** Values are 4-state (x and z alike) and operators follow the IEEE rules (`0 && x` is 0, `x == 1`
  is x, `===` compares exactly, `$isunknown`; `inside` is `==?`: x bits of a set item match anything). A boolean
  that is unknown as a whole reads as false; an attempt that read one and does not pass for real (non-vacuously)
  fails with a note naming it (`--x false`: the IEEE result). Everything is unsigned: a signed type or literal in an
  assertion gives a warning.
- **Open-ended ranges** `##[m:$]`, `[*m:$]`, `[->m:$]`, `[=m:$]`, `always`, `s_eventually`: a thread waits until the
  end of the dump. An attempt still waiting there is `active`. For a weak operator (`##[m:$]`, `[*m:$]`, `always`,
  `nexttime`) that is the end of it: nothing failed. A strong one (`s_eventually`, `s_always`, `s_nexttime`) still
  waiting at the end is a `fail` with the reason "not seen before the end of the dump".
- **Empty matches.** `[*0]`, `[*0:n]`, `##[0:n]` before an element, `[->0]` and `[=0]` can match the empty
  sequence: `a ##1 b[*0] ##1 c` is `a ##1 c`. An empty match is not a match of an antecedent (no attempt follows from
  it) nor of a sequence used as a property (IEEE 1800-2017 16.12.2, 16.12.6). `##0` is fusion: the next element is
  checked at the tick where the previous one matched.
- **Several matches.** A sequence with a range can match in several ways; an implication passes only when every match
  of the antecedent has a matching consequent (each match is its own thread); `first_match` keeps the earliest;
  `intersect` needs both to end at the same tick; `and` ends at the later of the two ends; `or` at either; `within`
  needs the left one to start and end inside the right one.
- **Covers** count every attempt that matches (`cover sequence`: every match, also several from one attempt).
- **Widths.** Values are unsigned, at most 64 bits; operators size their operands as IEEE 1800-2017 11.6 does for
  unsigned operands (the context width for arithmetic and bitwise operators, the larger side for comparisons).

## JSON

`sva parse --json` and the WebAssembly call `run_json({"source": ...})` give the parsed file: `docs/sva/ast.schema.json`
(checked against the whole corpus by `sva/core/tests/schema.rs`). Node kinds: expressions `ident const number fill
unary binary cond select concat repl inside call cast`; sequences `bool delay repeat binary throughout first_match
instance`; properties `seq implies not binary if nexttime always eventually instance`. Every node has `at` (line, col,
byte offsets); `bool` nodes of an assertion have their element `id`.
