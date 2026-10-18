# SVA evaluation engine (stage 5)

The evaluator of `sva-core` (`sva/core/src/engine.rs`, 4-state values and expressions in `value.rs`). It takes the
expanded assertions of docs/sva/LANGUAGE.md and the values of their signals at the sampling points of the clock, and
gives every assertion's attempts with their results and step traces. The same code runs natively (`sva eval` over a
VCD / FST) and in the page (the WebAssembly build behind `wavefw/sva.js`). The semantics follow IEEE 1800-2017 §16
for the subset; where this document makes a choice, the choice is listed under *Decisions*.

## Entry points

| Where | Call | Input |
|---|---|---|
| Rust | `sva_core::evaluate(&Assertion, &Trace, &Options) -> Outcome`, `evaluate_all`, `run(source, …) -> Results` | a `Trace`: one `Column` (4-state values) per signal name, one value per cycle |
| JSON / WASM | `run_json({"source" \| "files": [...], "trace", "options"?, "assert"?})` -> the results document; `run_json({"report": {meta, results}, "format"?})` -> `{summary, text}` (*Report*) | the trace as JSON (below); `files`: several sources as one compilation unit |
| page | `SVA.load(wasmBytes)` -> `{parse, evaluate}`; `evaluate(parsed, sampler, options)` | a *sampler*: `edges(name, edge)` -> clock edge times, `before(name, t)` -> the value just before `t`; `SVA.tvSampler({name: {tv, width}})` builds one from WaveJSON `tv` arrays |
| shell | `sva eval --waves dump.vcd\|fst --scope tb.dut --sva checks.sv [--sva …] [--assert NAME …] [--from T --to T] [--out results.json] [--json] [--attempts] [--x fail\|false] [--vacuous] [--no-lane] [--resolve up\|scope] [--ignore-prefix i_,o_] [--alias NAME=PATH …] [--max-threads N] [--report r.md\|.html\|.xml\|.json] [--junit r.xml] [--max-failures N] [-D NAME[=V]]`; `sva report RESULTS.json… [--title T] [--md F] [--junit F] [--html F] [--json F] [--max-failures N]` | the dump, read with wellen |
| make | `make sva-eval WAVES=… SVA="pkg.sv checks.sva" SCOPE=… [OUT=…] [ARGS=…]`, `make sva-examples`, `make sva-test` | |

`sva eval` resolves every signal name in `--scope`, then in the scopes above it (so a checker bound into `tb.dut` can
read `tb.clk`; `--resolve scope` is the page's binding rule of *Name resolution* below, which `mkhtml.py` uses for a
config's `"bind"`), samples at the clock edges of the dump, prints one line
per assertion and writes the results JSON:

```
apb_demo_no_wait      assert 19 attempts: 3 pass, 2 fail, 14 vacuous, 0 active, 0 disabled · first fail at cycle 10 (105 ns): expected PREADY at cycle 10
apb_cov_write         cover  2 matches in 19 attempts · first at cycle 6 (65 ns)
```

A signal that is not in the dump is listed (`sva: a: no nope, gone in scope 'tb' (not evaluated)`), that assertion is
not evaluated (it is in the results JSON with `missing` and a `stats` object of zeros). Exit status, the same for
`sva eval` and `sva report`: 2 when something was not checked as asked (a usage error, a syntax error, no assertion in
the files, a missing signal, a dump or results file that does not read: 2 wins over a verdict); else 1 when an
`assert` / `assume` failed or an attempt has no verdict (`capped`: the thread limit, raised with `--max-threads`;
covers never fail); 0 else.
The old form `sva FILE... --waves DUMP` is the same command. `--attempts` prints every listed attempt with its trace.

The page builds its sampler from the WaveJSON it already has (`tv`: `[[time, value], …]`, bit values `0 1 x z`, bus
values hex); `evaluate` groups the assertions by clock, asks the sampler for the edges and for each signal's value before
each edge, and calls the WebAssembly module once per clock.

## Name resolution (one rule: the page, `mkconfig.py --sva`, `sva eval --resolve scope`)

A name `p.q.n` of an assertion bound to the instance `S` (a scope path of the dump; `""` the top) resolves to the first
of, in the scope `S.p.q`:

1. the variable named `n`;
2. the signal shown as `n` (an `"alias"` of the config; `sva eval --alias n=PATH`, which the build passes from the
   view's signals);
3. the variable whose name (or shown name) without the ignored prefixes (the page's `sortIgnore`, longest first;
   `--ignore-prefix`) equals `n` without them (`valid` finds `s_valid`, `i_valid` finds `o_valid` when both prefixes
   are ignored). When that is several variables (`i_valid` and `o_valid` for `valid`), the name is ambiguous: an error
   naming them (`valid (ambiguous: tb.i_valid or tb.o_valid)`), not the first one.

The clock (the first signal of the assertion) may also come from the scopes above `S`, nearest first, by the same three
steps. A name that a select reads wider than the variable (`data[15:8]` of an 8-bit `data`) does not resolve (with
`--resolve up` too). A path splits at its dots, not inside a select nor in an escaped identifier: `\esc.x` (the parser
keeps the backslash of an escaped name that holds a dot) is one name to the end of the path. An
instance is a *candidate* for an assertion when all its names resolve. The three implementations: `lookup()` /
`resolve()` / `candidates()` in `wavefw/sva.js`, `svabuild.Names` in `tools/svabuild.py` (used by `mkconfig.py --sva`),
`lookup()` with `--resolve scope` in `sva/cli/src/main.rs`; `make smoke` checks that they give the same candidates for
`apb_setup_access` on the APB example (`apb_tb`, `apb_tb.u_master`, `apb_tb.u_regs`, not `apb_tb.u_count`), and the
build passes the page's `sortIgnore` to `sva eval`, so a binding resolves in the build as in the page.

## In the page (stage 6)

`wavefw/sva.js` (after `wavefw.js`; the module comes from `wavefw/sva.wasm.js`, deflate-raw + base64, unpacked with
`DecompressionStream`) adds the assertions panel to every viewer (docs/USAGE.md *Assertions (SVA)*). A binding is an
assertion and an instance path of the viewer's model: the *modules* are the groups that hold dump paths (`--hierarchy`
pages), the top of a view is `meta.scope` (the converter's `--scope`). Each name of the assertion resolves in the
instance by *Name resolution* above (a select wider than the row is a bind error). `SVA.rowSampler({name: row})`
samples the bound rows (their transitions `tr`: `tv` values; in a clock-sampled view the `raw` hex values that
`vcd2wavedrom.py` writes next to labels that do not read back, else the labels read back through the enum or the row's
radix), and the results document of each assertion is stored on its binding (`view.sva.bindings[i].results`, with
`scope` and `signals` the bound paths); the viewer fires `wavefw:sva`.

The bindings of one scope are evaluated together through the same `plan` / `assemble` as `SVA.evaluate`: one request
per clock with all their assertions and every file of the page as one unit (the engine keeps the last parsed unit, so the
files are parsed once). A request whose work (cycles × assertions) at the measured rate (`SVA.rate`, about 450 per ms)
would take more than ~300 ms goes to a Web Worker made from the same functions and the inlined module (`SVA.syncLimit`,
in work units, forces the choice); the line says "evaluating 2 / 3 (16061 cycles, in a worker)…". 100 assertions bound
to one instance of the APB example evaluate in about 0.2 s (stage 6: 4.9 s).

Over a view of exact transitions the page gives the counts of `sva eval --resolve scope` (`make smoke` compares every
binding of the examples). In a clock-sampled view the first cell has no value before it, so its edge is not a sampling
point: one attempt less than the dump.

Kept in this browser (`localStorage`): the loaded files (one per name; the page's files come first in the unit; a file of
this browser with the name of a page's file replaces it in the unit — an edit with ✎ or a reload from the disk with ⟳ —
until Revert or Clear), and per
viewer its bindings, the ones of the config the user unbound, the assertions removed with ✕, and the results evaluated
in the page when they are under 200 kB (with a hash of the files: other files, evaluated again). The config's bindings
that are new since join the stored ones. **Clear** forgets this browser's files and the bindings of every viewer of the
page. Bindings whose signals the view does not show keep their build-time results and say "from the dump, not in this
view". A label is unique in its module (as in SystemVerilog): the same label in another module of the unit is named
`module.label` (`cxp_short_pkt_sva.a_hold_until_ready`; the first keeps the plain label) — in the page, the CLI's
`--assert` and `mkconfig.py --sva` alike. A second assertion with the same label in the same module (a file loaded
twice) is listed as a note and cannot be bound. A change of the sort prefixes binds again (`wavefw:settings`).
After the files change (✎ Apply, ⟳, Watch, Load file…) a binding keeps its results only while its assertion is the
same: the parsed assertion without its position (`asig`) is compared, and the page's build-time results of an assertion
whose statement differs from the page's file are dropped; the others are evaluated again. ✎ replaces the statement
from the start of the label's line to the `;` that ends it (`at.start` / `at.end` are UTF-8 byte offsets); a text with
a new parse error in that file is not applied.

`view.extraRows` (wavefw.js) lets a plugin put rows under a group: they fold, sort as a block after the group's
signals, are found and highlighted, may draw themselves, and reach the static SVG through `opts.extraRows`.

On the waves (stage 7) every binding with results is such a block under the group of its scope (`b.group`; the top
for the view's own scope): a group row with the counts of `stats`, the attempts lane, one row per `steps[]` entry, and
copies of the bound rows (`same: true`, `svaSignals`). The drawing reads `attempts` (the source of truth; `lane` only
for the thin per-cycle strip) and places every cycle at `cycles[k]` of the results, so build-time results over a
clock-sampled view, which have one more cycle, still land on their edges (a bar that starts left of the window is
clipped). Attempts take three sub-lanes in start order (first fit); the rest share the third, merged where they
overlap, with a count. An attempt alone in its pixels is a bracket over its cycles (ticks at both ends, open at the
end when active or capped; a failure green to the last trace point before `failed_at`, red from there, at least the
failing cycle); merged ones are a bar. Bars, strip marks and circles are binned by pixel, so a redraw with 1200 attempts on screen
takes about 3 ms. A failure is a red ✕ on the step of `reason.step` (else the last consequent step) at `failed_at`,
joined to the last matched step by a dashed arrow labelled from `reason.kind` and `note`; `capped` attempts are hatched
grey, never failures. Arrows follow the trace of the selected attempt, or of every attempt when fewer than 20 are on
screen (all of them in the static SVG); their labels sit at the arrow's middle and skip places another label holds,
the selected attempt's always show — a deliberate difference from the label lanes of bookmark arrows, which would add
rows per binding and move the layout on every pan. Plugin overlays (these arrows) are drawn over the cursor line, so a
same-cycle failure arrow under the cursor stays visible. A circle is drawn small, without its number, where its
neighbour is closer than 14 px. The selected attempt (the static SVG: the first failure, else the first attempt) is
drawn on the signals too: the rows a step reads are the names of the assertion's `signals` found in the step's label
(`sva.js` `stepSignals`: system functions, based literals and strings skipped, `a.b.c` read as the longest known name),
each matched step a numbered circle on every such row, arrows from the first row of one step to the first of the next
(on the bound rows and on their copies, each set on its own); its start and end are dashed lines over the rows drawn,
with flags in the group's band (`▶ start`, then `✓ pass`, `✕ fail`, `… not ended` for an active attempt, `⊘ disabled`,
`… capped`). The overlay carries `overlay.rows` (the bound rows), so the viewer draws it when one of them is on screen
even with the group out of view. A truncated trace (`"truncated": true`) draws the step across its cut as a grey dashed
arrow "… nT (trace cut)", and the bar's tooltip says "trace cut". Tooltips give times first (start → end, failed at),
cycle numbers in brackets: cycle numbers count from the first edge of the evaluated window (`sva eval --from`, or the
view's start for an in-page Evaluate), so the same failure can carry another number after an in-page Evaluate;
`sva eval --to` lists no edge after the window in `cycles`. Selecting an attempt (a click on a bar or circle, Go to
first failure, the failure buttons, `f` / `F`, a click on the assertion's line, `a` / `A`) sets `view.sva.selA`, moves
the window to the attempt at the current zoom (the attempt in the middle; a longer one starts near the left edge),
scrolls its attempts row to the middle of the waves (`view.centerRow`), marks the binding's line (`li.here`), highlights the bound rows through
`view.extraPicks` and updates the binding's line only; unbinding, re-evaluating or removing the selected binding (and
Clear) drop the selection and the highlight. Changes to several bindings (Clear, ✕) redraw once; the panel's report
runs at most once per task and only when the bindings' results changed (`resultsKey`). The groups a plugin added to
the model through `extraRows` leave `M.groups` when the plugin no longer returns them.

## Expressions and Why (stage 10)

Two more requests of `run_json` (`sva-core/src/explain.rs`), both in the unit of the page's files:

- `{"files"?, "exprs": ["a && !b", ...], "trace"?}` → `{"exprs": [{"text", "signals": [{name, width?}], "width"?,
  "values"?} | {"text", "errors"}]}`. An expression is parsed and expanded in `$unit` (macros, `pkg::NAME` constants);
  without a trace the answer is its signals (the page resolves them and samples them), with one its width and its value
  at every cycle (the forms of the results: a number, `"h…"` past 2^53, binary digits with x; at most 4 M values).
  `sva.js` builds the trace itself: with a clock prefix `@(edge clk)` (cut off in the page) the values just before each
  edge, as for an assertion; without one, the value after the changes at each time any of its signals changes. Names
  resolve from the scope the expression was written in up to the top, then as a path from the top. A match of the
  search is a time where the value becomes true (a nonzero known bit). Rows are plugin `sig` rows made through
  `WaveFW.parse` of a `tv` list, so they draw, sort and show values like signals.
- `{"files", "trace", "explain": {"assert", "from", "to"}}` → `{"explain": [{"id"?, "what", "tree"}]}`: the booleans
  of the assertion in source order (sequence elements with their `steps` id, `if` conditions, `disable iff`), each a
  tree `{text, w, values, kids?}` of its sub-expressions (operands; a chain of `&&` / `||` as one list; the arguments of
  a system function; constants left out; at most 64 nodes per boolean), valued at cycles `from..=to` (at most 512). The
  page asks for the selected attempt with the trace of its binding (`plan` of that one assertion) and maps the attempt's
  cycles through their times, so build-time results over a window still find their columns.

## Report (stage 8)

`sva-core/src/summary.rs` makes the report of a set of results documents, once for every user: `sva eval --report /
--junit`, `sva report`, the page (`run_json({"report": …})`) and `mkhtml.py`'s printable section (`sva report --html`).
Input `{"meta": {title, dump, tool, date, …}, "results": [results document, …], "sources"?: [file per document],
"max_failures"?: n}` (checked first: anything that is not results — `{}`, a number, a count that is not a number, a
summary — is an error, exit 2 in `sva report`); the summary `{meta, totals, assertions, failures, max_failures,
sources}`:

- `assertions`, one row per assertion of every document: `row` (its index), `source` (its file when several), `name`,
  `kind`, `scope`, `file`, `line`, `text`, `unit`, `stats`; `first_fail` / `last_fail` — the earliest and the latest
  *found* (by `failed_at`, the simulator's `$error` time), each `{row, source, name, scope, start, failed_at, unit,
  t_start, t_fail, time, time_fail, note, kind}` (`kind` = `reason.kind`); `longest` (`{cycles, start, time}`: `end -
  start` of the longest decided attempt — active and capped ones have no end of their own); `latency` (`{min, avg, max,
  n, text}`: over the passing attempts of an implication, the last step of the outer consequent (`role: cons`, group 0)
  minus the latest `ante_end` before it; an attempt without such a step uses its `end` — a nested `a |=> (b |=> c)`
  gives 2 —, one without `ante_end` (a top-level `and` of two implications) none; `ante_end` keeps the first 32 and
  the latest 32 matches of a long antecedent, the latest is what counts; `text` = `1 / 2.0 / 3`); `covered` (cover
  hits, else null), `missing`, `notes`;
- `totals`: assertions, evaluated, with_failures, not_proven (rows with capped attempts), attempts, pass, fail,
  vacuous, disabled, active, capped (apart from failures), covers, covered;
- `failures`: every failed attempt with its `row`, by the time it was found (times in ps before cycles), then start.

Times are exact words (`time_text`, also the CLI's): `400 ps`, `15 ns`, `1.0004 us`, `81.7164 us`, `2 ms`. Texts:
Markdown (totals, a table per assertion — a Source column when the documents come from several files —, Notes, the
failure list), JUnit XML (a test case per assertion, `classname` the scope (`[file]` added over several files);
failure = its own fails with the first note; error = attempts without verdict (capped); skipped = not evaluated, or a
cover never hit; the notes in `system-out`; `time="0"`), and an HTML section. The texts list at most `max_failures`
failures per assertion (20; `--max-failures`, 0 = all) and say how many more; the JSON keeps every one. The page's
panel shows the same summary (totals line, **Table** with the notes, **Failures** — the first 500 rows) and downloads
`report.md` and `report.json` (`{meta, results}`: `sva report` reads it; `sva eval --report x.json` writes the same
form). `sva eval` and `sva report` exit 1 on a failure or a capped attempt and 2 when something was not checked, so
either gates a CI flow.

## Trace and options (JSON)

```json
{ "cycles": 6, "times": [5000, 15000, 25000, 35000, 45000, 55000], "unit": "ps",
  "signals": { "rst_n": [0, 1, 1, 1, 1, 1], "req": ["0", "1", "0", "0", "1", "0"], "data": ["h1f", "hx0", null, 3, 4, 5] },
  "widths": { "data": 8 }, "two_state": ["cnt"] }
```

A value is a number, `null` (x), a string of binary digits (`"10x1"`, `"z"` reads as x) or of hex digits after `h`. A
value with fewer digits than the width is zero-extended unless its top digit is unknown, which fills the width (`"hx"`
of an 8-bit bus is 8 unknown bits, as `'hx` would be). Without `widths` the widest value gives the width.

Options (all optional): `vacuous` (list vacuous attempts too; default false), `lane` (default true), `x` (`"fail"`,
default, or `"false"`), `max_threads` (per sequence of one attempt, default 256), `cover_traces` (matches of a cover
listed with their traces, default 100; all are counted), `from` / `to` (attempts start at cycles `from .. to`, the
evaluation ends at `to`; `sva eval --from 2us --to 5us` maps times to cycles), `merge` (default true: attempts in the
same state are stepped once; false steps each one, for tests).

A signal with fewer values than `cycles` reads its initial value after its last one, and a value wider than 64 bits
keeps its low 64 bits; both give a note on the assertions that read the signal.

## Results JSON

```json
{ "clock": "tb.clk", "unit": "ps", "cycles": [5000, 15000, 25000, …],
  "assertions": [
    { "name": "a_req_ack", "kind": "assert", "file": "checks.sv", "line": 12, "text": "req |-> ##[1:3] ack",
      "scope": "tb.dut", "signals": { "ack": "tb.dut.ack", "clk": "tb.clk", "req": "tb.dut.req" },
      "steps": [ { "id": "s1", "label": "req", "role": "ante", "group": 0 }, { "id": "s2", "label": "##[1:3] ack", "role": "cons", "group": 0 } ],
      "stats": { "attempts": 1203, "pass": 40, "fail": 2, "vacuous": 1160, "disabled": 1, "active": 0, "capped": 0 },
      "attempts": [
        { "start": 17, "end": 19, "result": "pass", "trace": [["s1", 17], ["s2", 19]], "ante_end": [17] },
        { "start": 52, "end": 55, "result": "fail", "trace": [["s1", 52]], "failed_at": 55, "note": "no ack within [1:3]",
          "reason": { "kind": "range", "step": "s2", "cycle": 55 }, "ante_end": [52] } ],
      "lane": "…S.P…S..F…" } ] }
```

`docs/sva/results.schema.json` is the schema of this document (`sva/core/tests/schema.rs` validates evaluations that
give every result, reason and field against it).

- `cycles[k]` is the time of cycle k (the k-th clock edge); attempts and traces refer to cycles. An assertion on another
  clock than the document's first one carries its own `clock` and `cycles`.
- `steps`: the sequence elements, each with its `role`: `ante` / `cons` (the antecedent / consequent of the implication
  `group`, 0, 1, … in source order), `cond` (the condition of a `throughout`), `seq` (a sequence property, a cover).
- `attempts` lists every attempt that is not vacuous, by start cycle (vacuous ones are counted in `stats`; option
  `vacuous` lists them). `result` is `pass`, `fail`, `active` (the dump ended first), `disabled`, `vacuous`, or
  `capped` (the thread limit dropped some of its threads: no verdict; `stats.capped`). The attempts are the source of
  truth; `lane` is derived from them.
- `ante_end` (implications): the cycles at which the antecedent matched; with the `cons` steps of the trace they give
  the latency antecedent → consequent. Of more than 64 matches the first 32 and the latest 32 are kept, and
  `ante_truncated: true` says so.
- `trace` is the steps in match order, `[id, cycle]`, with a third item when the step compares a bus (`==`, `!=`, `<`,
  …, `inside`): the value of its left side (a number; a string of binary digits with x when unknown). A passing
  attempt shows the steps of every consequent (sorted by cycle, then element), so the trace covers `start..end`; a
  failed one the steps that matched, a disabled or active one how far it got, one failed by an unknown value ends with
  the step that read it. A trace is cut when its path grows past 96 steps: it keeps its first 16 and last 47
  (`"truncated": true`); a trace of up to 96 steps is kept whole.
- `failed_at` is the cycle where the attempt failed (for an unknown value: where it was read; `end` is where the
  attempt was decided), `note` says why in words: `no ack within [1:3]`, `expected ack at cycle 7`, `ack is unknown
  (x) at cycle 7`, `not seen before the end of the dump`, `the property under 'not' held`; `reason` says it for
  grouping: `{kind, step?, cycle}` with `kind` one of `no_match`, `expected`, `range`, `unknown`, `not_held`,
  `strong_end`, `capped`.
- `lane` has one character per cycle for the waveform: `.` nothing, `S` a non-vacuous attempt starts, `P` one passes,
  `C` one is capped, `D` one is disabled, `F` one fails (several at one cycle: F over D over C over P over S).
- Covers: `attempts` lists the matches (only the first `cover_traces`, so a drawing has fewer bars than
  `stats.matches` when there are more), `stats.matches` counts them all; `pass` counts the attempts that matched,
  `fail` the ones that did not (not an error), `vacuous` the vacuous ones (which do not cover).
- `missing` (signals not in the trace: not evaluated) and `notes` (a thread limit was reached, a short column, values
  cut to 64 bits) appear when not empty.

## How it evaluates

**Attempts.** At every cycle where `disable iff` is not true, a new attempt of the assertion starts; every alive attempt
is stepped once per cycle (its first step is its start cycle) until it is decided. The property is a tree of states:

| property | state | decided |
|---|---|---|
| sequence | its thread set | pass at the first match; fail when no thread is left |
| `a \|-> p`, `a \|=> p` | the antecedent's threads; one consequent instance per antecedent match end cycle (`\|=>`: started a cycle later) | fail at the first consequent that fails; pass when the antecedent can match no more and every consequent passed; vacuous when the antecedent never matched |
| `a #-# p`, `a #=# p` | the same | pass at the first consequent that passes; fail when none can |
| `not p` | p | inverted (a vacuous pass of p is a fail) |
| `p and q`, `p or q` | both | `and`: fail at the first fail, pass when both passed (vacuous when both were); `or`: pass at the first non-vacuous pass, vacuous when one side passed vacuously and the other did not pass, fail when both failed (the order of the operands does not matter) |
| `if (c) p else q` | — | `c` sampled at the start chooses; no `else` and `c` false: vacuous |
| `nexttime [n] p` | a count | p from n cycles later |
| `always [m:n] p` | instances of p started at offsets m..n | fail at the first fail; pass after offset n with the steps of every instance (never for `always p`: active at the end) |
| `eventually [m:n] p`, `s_eventually p` | the same | pass at the first pass; fail when every instance failed after offset n |

**Sequences** are threads: a thread is a residual sequence (what is left to match from the next cycle) and the path of
the booleans it matched (the trace). Stepping a residual at a cycle gives the residuals for the next cycle and whether
it matched here: `l ##[m:n] r` steps `l` and, when `l` matches, starts `r` 0 (fusion) to n cycles later; `[*m:n]`
repeats; `[->m:n]` counts hits and ends at one; `[=m:n]` also ends at the cycles without a hit after enough hits; `and`
runs both sides and matches when both have (at the later end); `intersect` when both match at the same cycle;
`within` is `(1[*0:$] ##1 a ##1 1[*0:$]) intersect b`; `throughout` stops the inner threads at a cycle where its
boolean is false; `first_match` keeps the threads of one start together and ends them all at the first match.
Residuals are hash-consed, so threads that reach the same state merge (the first path is kept) and the set of one
sequence is bounded by its distinct states; `##[1:$]` is one thread, not one per cycle.

**Booleans** are evaluated at most once per cycle (a cache shared by all attempts) on the sampled 4-state values.

**Attempts in the same state step as one.** After every cycle the pending attempts are grouped by what decides their
future: the residual terms of their threads, the consequents they wait for, the sides already decided, the offsets of
`always` / `eventually` (up to the end of their range), the unknown they read, whether they were capped — with cycles
relative to now and without paths. A group is stepped once per cycle and decides for all its attempts at the same
cycle, with the same result and note. Each attempt keeps its own steps up to the cycle it joined the group and shares
the group's after it (exact unless a thread set held several paths before the merge: the trace then shows the longest
one). Attempts that never end — `req |-> s_eventually ack` without the ack, `a |-> b[*1:$] ##1 c` — cost one group,
not one attempt per cycle. Paths are linked lists of steps in an arena; a path that reaches 96 steps is cut to its first
16 and last 47 (it grows to 96 again before the next cut), and the arena is collected from the live groups when it doubles, so memory follows the live attempts.

## Decisions

- **Sampling.** Cycle k is the k-th clock edge in the dump (`posedge`: a change to 1 from 0, x or z; the dump's first
  value is not an edge). Every value is the one holding just before the edge time (the preponed region); a value
  written at the edge counts from the next cycle. The page's sampler does the same over `tv`.
- **Before the first cycle** (`$past(x, n)` at cycle k < n, and the previous value of `$rose` … at cycle 0) every
  signal has the initial value of its type: x for 4-state signals (logic, reg, wire: everything a VCD has), 0 for
  2-state ones (`bit`, `int`, `byte`, `shortint`, `longint`: from the FST's variable types, `two_state` in the trace
  JSON). So `$rose(a)` is true at cycle 0 when `a` is 1 there (x -> 1 is a rise), and `$past(a) == 0` is unknown at
  cycle 0.
- **`$rose` / `$fell`** look at the least significant bit: a rise is a change to a known 1 from 0, x or z; `$stable` /
  `$changed` compare the whole value exactly (x == x is stable).
- **4-state values** (at most 64 bits; wider dump signals use their low 64 bits, with a warning; x and z are one
  unknown state). Logical operators, `==` / `!=`, comparisons, bitwise operators, reductions, `?:` follow IEEE 4-state
  rules (`0 && x` is 0, `1 || x` is 1, `==` is 0 when known bits differ and x when unknown bits could decide, `===` /
  `!==` compare exactly); arithmetic and shifts by an unknown amount give all x; division by 0 gives x; a select outside
  the vector reads x. Widths: context-determined operators take the larger of their operands and the context (so
  `a + b == 9'h100` keeps the carry and `a + b == 8'h00` drops it), comparisons extend both sides, everything is
  unsigned, selects assume `[N-1:0]` vectors.
- **An unknown boolean** (one that is x as a whole: no bit known 1 and some unknown) reads as false (the IEEE rule)
  and the attempt remembers the first one it read. When the attempt is decided, a non-vacuous pass stands (the unknown
  was in a branch that did not decide: `(b ##1 b) or (d ##1 e)` with `d` x, `b[->1]` with one x cycle before the
  hit); a fail or a vacuous pass becomes a **fail** naming the unknown (`failed_at` the cycle it was read); an attempt
  still pending at the end is `active` with the note. With x after reset and no `disable iff`, the first attempts so
  fail visibly instead of passing vacuously. Option `x: "false"` (`--x false`) keeps the IEEE results. An unknown
  `disable iff` condition does not disable (as in IEEE), so before reset, with `rst_n` itself x, attempts that read x
  fail by this rule: write the reset into `disable iff` as `!rst_n` and dump from time 0, or evaluate `--from` after
  reset. The rule judges the attempt as a whole: an unknown that decided a `not` (`not (a ##1 b)` with `a` x) gives a
  pass, as in IEEE.
- **Signed values.** Everything is compared and shifted as unsigned. A signal of a signed type (`int`, `byte`,
  `logic signed`, …) or a signed literal (`8'sd5`) read by an assertion gives a parse warning and a note
  ("compared as unsigned"); plain numbers and unsigned types do not.
- **`disable iff`** is checked at the sampling points with the sampled value: when true, every alive attempt ends as
  `disabled` (counted on its own, not as pass or fail) and no attempt starts at that cycle. A reset pulse that starts
  and ends between two edges is not seen (the standard evaluates `disable iff` asynchronously).
- **End of the dump.** An attempt still undecided is `active` for weak operators (sequences, `##[m:$]`, `[*m:$]`,
  `always`, `nexttime`, `eventually [m:n]`, implications waiting for consequents); a strong one (`s_eventually`,
  `s_always`, `s_nexttime`) fails there with "not seen before the end of the dump" (`s_always [m:n]` names its range
  only while the dump ends inside it). An `or`, `and` or implication still open at the end that already has its
  result (an `or` with a vacuous side, …) reports it. An implication whose antecedent can still match
  (`a ##[1:$] b |-> c`) is never decided before the end: write `first_match(a ##[1:$] b) |-> c`.
- **Empty matches** (`[*0]`, `[*0:n]`, `[->0]`, `[=0]`): `empty ##n s` is `##(n-1) s`, `s ##n empty` is
  `s ##(n-1) 1`, `empty ##0 s` and `s ##0 empty` do not match; an empty match is no match of an antecedent or of a
  sequence property; inside `[*n]` an empty match of the repeated sequence is ignored; `and` / `intersect` /
  `within` need both operands to match at least one cycle. This deviates from the letter of IEEE 1800-2017 for an
  antecedent that can match empty: by 16.12.7 (`s |=> p` is `s ##1 1 |-> p`) and 16.9.2 (`empty ##1 s` is `s`),
  `a[*0:1] |=> b` would check `b` at the start cycle when `a` is false; here that attempt is vacuous. Nobody writes it
  on purpose; the choice keeps "the antecedent matched" meaning "a cycle of it matched".
- **Several antecedent matches ending at the same cycle** share one consequent instance (the first path is shown).
- **`first_match`**: the trace of its match shows the steps of every thread it ran (they share the start).
- **Thread limit.** One sequence of one attempt keeps at most `max_threads` (256) distinct residuals; more are dropped,
  the assertion gets a note `thread limit 256 reached at cycle C (attempt S): some matches were not followed`, and the
  attempt ends as `capped` whatever it would have given (a fail or a pass found without the dropped threads may be
  wrong). With hash-consing the limit is reached only by genuinely different states (e.g. long `intersect`s of ranges).
- **`inside`** compares like `==?` (IEEE 11.4.13): x / z bits of a set item match anything (`2'b10 inside {2'b1x}`),
  unknown bits of the tested value make the result unknown where they matter.
- **Nesting.** More than 500 levels of operators and parentheses is a parse error (no stage can overflow its stack);
  499 levels of each form (`##0` chains, parentheses, `not`, `&&`, implications) evaluate in the WebAssembly build
  with its 1 MB stack.
- **Covers** count every attempt that matches non-vacuously (`cover property`), or every match (`cover sequence`).

## Performance (October 2026, this machine: WSL2, 16 CPUs)

| run | data | result | time |
|---|---|---|---|
| `sva eval`, `sva/bench/cxp_tx_arbiter.sva` (3 assertions over `cxp_tx_arbiter_i`: `$onehot0`, a hold with `$stable`, a packet `s_eventually`) | `work/test_stream_video.fst` (266 kB), 16 061 edges of `tx_clk` | 16 050 / 0 / 18 pass, 0 fail; 1.2 MB results JSON | 0.035 s (read 0.010 s) |
| the same | `work/test_stream_video.vcd` (24 MB) | the same | 0.10 s (read 0.08 s) |
| page: `evaluate(parsed, tvSampler)` per assertion (`sva/bench/page_bench.py`, headless Chromium) | the `tv` of those signals from `vcd2wavedrom.py --exact` (32 124 clock transitions) | the same counts as native | 50 / 35 / 31 ms; all three 77 ms |
| page: one assertion (`make smoke`, the spike page) | a synthetic `tv` model, 32 768 clock edges | 2016 pass, 32 fail, 30 716 vacuous | 73 ms |
| `sva eval` over the examples (`make sva-examples`) | APB 21, AXI-Lite 19, FSM 107 cycles | only the deliberate failures fail | 4–6 ms each |
| `sva eval`, `sva/bench/open_ended.sva`: `m_ready_i \|-> m_ready_i[*1:$] ##1 never` and `m_ready_i \|-> s_eventually never` (stage 5.1) | the same FST, 16 061 edges | 990 fails each (every attempt open until it breaks / the end) | 0.02 s and 0.02 s, 7–12 MB (before 5.1: 2.9 s for the `s_eventually`) |
| `make html WAVES=work/test_stream_video.vcd` (1 view, 1526 signals) with the three arbiter assertions bound (`mkhtml.py --sva sva/bench/cxp_tx_arbiter.sva --bind '*@…cxp_tx_arbiter_i'`, stage 8) | the VCD, 16 061 edges; the views' results plus the whole-dump report | 16 050 / 0 / 18 pass; page 6.7 → 8.5 MB (the results JSON of the invariant's passes), 1.5 GB peak either way | 14.9 s → 16.2 s (+1.3 s); stage 8.1 (the printable section reuses the view's whole-dump results): 14.5 s → 15.6 s (+1.0 s); the page draws the three groups under `cxp_tx_arbiter_i`, a redraw 74 ms with everything expanded |
| the user's checkers `cxp_sva.sv` (12 checker modules, 22 assertions; `cxp_pkg` stubbed with the dump's values), each bound to its checker instance in the dump (`…cxp_tx_owner_sva_i` etc., 15 instances, 32 bindings) | `test_stream_video.fst`, 16 050 – 16 061 edges per clock | no failure; `a_owner_valid` 16 050 attempts, 972 pass, 15 078 vacuous — the same counted by hand from the VCD (posedges of `tx_clk` with `rst_n` high, `owner != 0`, the owner's `valid`); 8 assertions never leave vacuity in this bench (backpressure, trigger, I/O-ack, Wait, resync are not exercised) | one binding 0.02 s / 8 MB; `make html` with all 32: 18 s, page 26 MB |
| the arbiter page with 16 061 failures (5 bindings, `many.sva`), stage 8.1 | 2 views, 13.2 MB (17.6 before: the printable section lists 20 failures per assertion) | Failures shows 500 rows (16 066 before) | Failures 3.2 s → 83 ms, Table 2.5 s → 21 ms, a redraw with the summary 2.8 s → 10 ms (report cached by results) |
| a deliberately wrong check on the same dump (`m_o.valid && m_o.sop && m_ready_i \|=> m_o.eop`) | the FST | 18 fails; the first, at 81.71 µs → 81.72 µs, checked by hand in the dump: `sop`, `valid`, `m_ready_i` high before the edge at 81.71 µs, `eop` low until 81.73 µs (3-beat packets) | 0.02 s |
| unit test: 20 000 attempts that never end (`a \|-> b[*1:$] ##1 c`, `c` never) | hand-made | 20 000 active | well under 1 s; before 5.1, 4000 cycles took 3.3 s and 1.0 GB |

The WebAssembly module is 546 kB, 265 kB in a page (546 051 B / 265 228 B, as `make smoke` prints them; stage 8: the
report code and `serde_json::Value`; stage 5.1: 451 kB) (`wavefw/sva.wasm.js`, deflate-raw + base64; STACK.md). A call of
the spike page (parse, evaluate 12 cycles, JSON both ways) takes about 110 µs.

Most of the results JSON of a long dump is the passes of invariants (one per cycle); the counts are complete either
way. Attempts that never decide are grouped (*How it evaluates*), so an assertion costs its distinct states per cycle,
not cycles × alive attempts; a JSON of 16 000 open attempts still lists each with its (truncated) trace.

## Tests

`make sva-test`: `sva/core/src/engine_tests.rs` has one test per construct over hand-made traces, each with the expected
attempts (`0-3F 3-4P`: start, end, result) — the operators, the examples of LANGUAGE.md, vacuity, `disable iff`, open
ranges at the end of the dump, strong operators, 4-state values in both x modes (x in branches that do not decide),
covers, lanes, options, the thread limit (capped attempts), full pass traces, step roles, antecedent matches, reasons,
the trace and results JSON; merged attempts against unmerged ones (results, stats, lanes over 20 properties × 6 random
traces), long truncated traces, 20 000 open attempts, the arena under load; `tests/schema.rs` validates the results
against `docs/sva/results.schema.json`; `value.rs` tests widths, unknown bits and the sampled-value functions;
`sva/cli/tests/cli.rs` runs `sva eval` over a small VCD (summaries, JSON, `--out`, `--assert`, `--from/--to`, missing
signals in the JSON, upward name resolution and `--resolve scope`, x, exit codes). `tests/sva/third_party` (checkers of
others for AXI4-Lite, APB and AHB) is parsed by `make sva-test` and evaluated over the example dumps by `make smoke`. `make smoke` checks the spike page (the WebAssembly results equal the
native ones; `evaluate()` over 32 768 edges in under a second) and `sva eval` over the three example dumps (each
testbench has one deliberately wrong assertion, which must be the only failure, with a trace).
