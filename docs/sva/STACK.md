# SVA engine — technology choice (stage 3)

**Decision: C — a Rust core (`sva/core`, no I/O), a native CLI over VCD / FST (`sva/cli`, dumps read with wellen) and a
WebAssembly build of the same core for the page (`sva/wasm`).** The spike confirmed it: the same source parses and
evaluates the spike property natively and in a browser page opened from `file://`, with identical results; the WASM
is 119 kB (158 kB as base64 in a page), a call takes tens of microseconds, and wellen reads the 24 MB dump of this
project in under a tenth of a second. One change against the plan: **no wasm-bindgen** — a plain C ABI with JSON in and
JSON out needs no generated glue and no extra tool, only `rustup target add wasm32-unknown-unknown`.

The fallback (A, pure JavaScript) is not needed; stages 4–5 stay in Rust as planned.

## What the engine has to do

Parse a practical SVA subset (stage 4), evaluate it at clock sampling points over dumped values with attempts, threads
and per-step traces (stage 5), bind an assertion to an instance (stage 6), run both offline over any dump and in the page
when the user binds interactively, and produce a results JSON that the viewer draws and mkhtml can inline (stages 7–8).

## Candidates, with what the spike found

| Stack | Where it runs | For | Against | Spike / verdict |
|---|---|---|---|---|
| **A. Pure JavaScript** (`wavefw/sva.js`) | page; offline only through a browser | no toolchain, one language with the viewer | no Node here: tests and offline runs through playwright; the dump reader would be JS too (or Python → JSON → JS) | not needed: C works without its costs |
| **B. Python** (`tools/sva/`) | offline only | fastest to write, reuses `dumpscan` | no interactive binding without a second engine; the built-in reader needs 4.8 s just to read the 24 MB VCD | rejected: one engine must serve both places |
| **C. Rust core → native CLI + WASM** | both, one implementation | `cargo test`; typed AST; wellen is fast and reads FST enum tables; the user already builds Rust tools | a toolchain to build it; a base64 blob in the page | **chosen** — numbers below |
| **D. C++ with slang** | both (Emscripten) | the most faithful front end | tens of MB, minutes to build, evaluator still to write | rejected (weight) |
| **E. RTL monitors from SVA, re-simulate** | simulator | exact semantics | needs the design, not a dump; no binding in the page | rejected |

## Spike results (October 2026, this machine: WSL2, 16 CPUs)

**Toolchain.** rustc / cargo 1.98.1 (stable, already installed for wavepeek) plus one command:
`rustup target add wasm32-unknown-unknown`. No wasm-bindgen-cli, no wasm-pack, no wasm-opt. Crates: `serde` 1,
`serde_json` 1 (core), `wellen` 0.25.7 (CLI only). Cargo's target directory is `$(BUILD)/sva-target` (the repository sits
on a slow Windows mount). Cold builds: native CLI 16 s (wellen and its dependencies), WASM 5.6 s; incremental about 1 s.

**Sizes.** `sva_wasm.wasm` 118 652 B, base64 158 204 B (`opt-level = "s"`, LTO, one codegen unit, `panic = "abort"`,
stripped). Most of it is `serde_json` and the formatting machinery; the spike parser and evaluator are small. Budget for
the full subset (stages 4–5): under 300 kB raw. The native `sva` binary is 813 kB.

**After stage 4** (the whole front end, docs/sva/LANGUAGE.md): 324 148 B with `opt-level = "z"` (cargo profile `wasm`,
`make sva-build`; 369 kB with `"s"`), one call 87 µs in the spike page; the native binary 1.1 MB. Serialising the tree
is 22 kB of it, the rest is the parser and `format!`. That is over the budget before the evaluator grows: stage 6, which
inlines the module into pages, decides between `wasm-opt -Oz` as an optional step and a hand-written JSON writer
instead of `serde_json` (the two remedies under *Risks*).

**After stage 5** (the evaluator, docs/sva/ENGINE.md): 416 145 B, one spike call about 110 µs; `evaluate()` in the page
over 32 768 clock edges of one assertion 73 ms, over the real `tv` of `test_stream_video` 31–50 ms per assertion.

**Stage 6 decision on size:** neither `wasm-opt` nor a hand-written JSON writer. The module (423 kB after stage 6) goes
into a page deflate-raw compressed and base64 encoded, `wavefw/sva.wasm.js`: 206 kB, inside the budget for what a page
carries (`DecompressionStream`, in every current browser, unpacks it in a few ms; `sva/wasm/pack.py`, Python's zlib).
`serde_json` stays: replacing it would save about 100 kB raw for a rewrite of every serialised type. With `wavefw/sva.js`
(~30 kB) a page grows by about 240 kB; `mkhtml.py --no-sva` leaves both out. After stage 5.1 (merged attempts, reasons,
step roles, the nesting limit) the module is 451 kB, 220 kB in a page.

**In the page** (headless Chromium, `sva/spike/spike.html` built by `make sva-spike`): the module is decoded from base64
and instantiated from bytes — no `fetch()`, so it works from `file://` — in 15 ms. One call (parse the property, evaluate
a 12-cycle trace, JSON both ways) took 38 µs. The attempts equal the native unit test (since stage 5, on a trace with a
reset pulse: `@1 pass s1@1 s2@3`, `@4 fail (no ack within [1:3])`, `@8 disabled`, `@11 active`; 6 vacuous). `make smoke`
checks this.

**Natively over dumps** (the spike: `sva FILE.sva --waves DUMP --scope SCOPE [--json]`, now `sva eval`, values sampled
just before each clock edge, as in the preponed region; stage-5 numbers in docs/sva/ENGINE.md):

| Dump | Assertions | Result | Time |
|---|---|---|---|
| demo VCD (`examples/demo`, 224 cycles) | `start \|-> ##[1:3] busy`, `start \|-> ##[1:3] done` | 2 pass; 2 fail (done comes ~100 clocks later), as expected | 4 ms |
| `test_stream_video.vcd` (24 MB, 3520 signals, 32 681 time points) | `s_pix_sof \|-> ##[1:2000] s_pix_eof`, `s_pix_valid && !s_pix_ready \|=> s_pix_valid` over 16 061 cycles | 11 and 183 pass, 0 fail | 0.08 s, 38 MB |
| `test_stream_video.fst` (266 kB) | the same | the same | 0.02 s, 4.5 MB |

**wellen on Verilator dumps** (`sva --waves DUMP --info`):

- FST enum tables: yes — `state [2] enum mc_pkg::state_t: 00=IDLE 01=START 10=DATA 11=PARITY`; 49 enum-typed variables in
  `test_stream_video.fst`. A VCD has none (as with our Python reader); stage 6 can take names from the page's `enum`.
- `$rootio`: a normal top-level scope named `$rootio`, like in our reader (mkconfig hides it by default).
- Unpacked arrays: one scope per array with the elements as variables `[0]`, `[1]` — the path `mem.[0]`, the same
  spelling as wavepeek and `dumpscan.py`.
- Bit-blasted vectors: Verilator writes whole vectors, so not exercised; other simulators' dumps are still unchecked.
- Timescale and time table are exposed; times are converted to ps for the report.

## Layout

```
sva/                    Cargo workspace (make sva-build / sva-test / sva-bless / sva-examples / sva-spike)
  core/                 sva-core: parser, AST, evaluator, results JSON; no I/O, the only code with SVA semantics
    src/                lex pre (preprocessor) parse expr prop (parser) expand (instances, clock, ids, signals)
                        consts print report ast; engine (attempts, threads, results) value (4-state expressions);
                        summary (the report: numbers per assertion, totals, failures; Markdown, JUnit, HTML);
                        tests.rs, engine_tests.rs: unit tests
    tests/              corpus.rs (tests/sva/*.sv: annotations, golden files, round trips), schema.rs
  cli/                  sva: native CLI — sva parse FILE...; sva eval --waves DUMP --sva FILE... [--report --junit] (dumps
                        through wellen); sva report RESULTS.json...; tests/
  wasm/                 sva-wasm: cdylib, C ABI — sva_alloc / sva_run / sva_result_len / sva_free, JSON in and out
  wasm/pack.py          the module for pages: wavefw/sva.wasm.js (deflate-raw + base64), written by make sva-build
  spike/                the stage-3 property, the demo properties, the spike page and its generator
  bench/                the performance checks of docs/sva/ENGINE.md (test_stream_video's arbiter, the page bench)
tests/sva/              the corpus: one file per group of constructs and per protocol, err_*.sv, golden/;
                        third_party/: checkers of others (YosysHQ AXI4 FVIP library, OpenTitan macros, APB / AHB / AXI-Lite)
wavefw/sva.js           the engine in a page (SVA.load -> parse / evaluate(parsed, sampler); tvSampler, rowSampler), the
                        assertions panel (list, binding, evaluation, numbers, failures, exports: stages 6, 8) and the
                        assertion groups on the waves and in static SVGs (stage 7)
wavefw/sva.wasm.js      the generated module, committed (pages build without Rust)
tools/svabuild.py       a config's "sva" / "bind" through the CLI, for mkhtml.py and vcd2wavedrom.py; the name rule
                        (Names) for mkconfig.py --sva; the page's printable report (sva report --html)
docs/sva/               STACK.md (this), LANGUAGE.md (the subset), ENGINE.md (evaluation, results JSON),
                        ast.schema.json (the parsed file as JSON)
```

The page loads the module from `wavefw/sva.wasm.js` (`window.WAVEFW_SVA_WASM = {size, deflate}`), inlined by mkhtml or
loaded with `<script src>` (`docs/index.html`); it is committed, so pages and `docs/index.html` work without Rust, and
`make sva-build` rewrites it (`make smoke` checks that it is the module of the current build).

## Interfaces

Request (page → WASM, `run_json`): `{"source": "..."}` gives the parsed file of docs/sva/ast.schema.json (assertions,
declarations, scopes, errors with line, column, byte offsets, found / expected); with `"trace"` (4-state values per
cycle), `"options"` and `"assert"` it gives the results document of docs/sva/ENGINE.md (`clock`, `unit`, `cycles`,
per assertion `steps`, `stats`, `attempts` with `[id, cycle]` traces, `lane`), or `{"errors": [{line, col, msg}]}`.
`sva eval --out` writes the same document from a dump, `wavefw/sva.js` builds it in the page from a sampler. `{"files":
["…", "…"]}` parses (and evaluates) several sources as one compilation unit. `{"report": {"meta", "results": [...]},
"format": "md" | "junit" | "html"}` gives the report's summary and text (ENGINE.md *Report*).

## Risks and how the next stages meet them

- **Semantics.** Unbounded ranges (`##[1:$]`, `[*]`, `[->n]`), `intersect`, `first_match` and nested implications make
  the thread sets grow. Stage 5 hash-conses the residual sequences (one thread per distinct state), caps a set at 256
  with a note, and tests every construct against hand-computed traces (docs/sva/ENGINE.md); a comparison with a
  simulator's own assertion results is still to do.
- **Four-state values.** Since stage 5 every sample carries its unknown bits; an unknown boolean fails the attempt with a
  note (or reads as false).
- **`disable iff`.** Checked at the sampling points (stage 5, ENGINE.md *Decisions*); the standard checks it
  asynchronously, so a reset pulse between two edges is missed. Evaluating it on every change in between needs the
  transitions in the core, not samples: possible later if a real case needs it.
- **Sampling in the page.** The page has `tv` transitions, not a dump. Stage 5 put the sampling behind a sampler
  (`edges`, `before`) on each side — wellen's changes natively, `SVA.tvSampler` in the page — with the same rule (the
  value before the edge; the first value is no edge); the spike page and `page_bench.py` check that both agree.
- **Size.** The module is 546 kB (265 kB in a page) after stage 8 (`make smoke` prints the bytes). If it matters,
  drop `serde_json` for a small hand-written JSON writer and run `wasm-opt -Oz` (binaryen) as an optional step.
- **Toolchain on other machines.** Building needs cargo and the wasm32 target; using does not, once the generated module
  is committed (see *Layout*). Python-only users keep every current feature.
