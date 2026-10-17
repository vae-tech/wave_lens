# Task: HTML waveform framework driven by WaveDrom JSON

Develop a reusable, dependency-free HTML/JS framework that takes waveform descriptions in the
**WaveDrom JSON format** and renders them with the same look, feel and interactivity as the waveform
panels in `template.html` (this directory). `template.html` is the visual and behavioural reference:
read it fully before writing any code (CSS variables, `.wv` viewer markup, the `WaveView` class,
`decode()` enum handling, `#wave-data` JSON embedding, lazy "Load waveform" cards).

## 1. What the framework must do

1. **Input = WaveDrom JSON** (hand-written or generated), e.g.
   ```json
   { "signal": [
       { "name": "clk",  "wave": "p......." },
       { "name": "rxd",  "wave": "0.1.0.1.", "node": ".a...b.." },
       { "name": "data", "wave": "x.3.4.x.", "data": ["0x5A", "0xA5"] },
       {},
       ["decoder",
         { "name": "state", "wave": "2.3.4.2.", "data": ["IDLE","VERIFY","RECV","IDLE"] } ]
     ],
     "edge": ["a~>b 8 µs"],
     "head": { "text": "T1 · frame 2 · 0x5A5A 16C" },
     "config": { "hscale": 1, "skin": "default" } }
   ```
   Support the WaveDrom subset: wave chars `0 1 x z = 2-9 p n P N h l H L u d | . ,`, `data`
   (array or space-separated string), `period`, `phase`, `node`, `edge` (`-> ~> -|> <-> |-> -~>`
   etc. with labels), nested group arrays, blank `{}` spacer, `head`/`foot` (`text`, `tick`,
   `tock`), `config.hscale`.
   Add one **extension** (ignored by stock WaveDrom): `"time": { "t0": <ps>, "cycle": <ps> }`
   so the viewer can show a real time axis (µs) instead of cycle numbers, plus optional
   `"markers": [{ "t": <ps or cycle>, "label": "eof" }]` and `"jumps": [{ "label": "EOF", "t": …, "span": … }]`.

2. **Two renderers, one data model**
   - `WaveView` (interactive, canvas): port/refactor the class from `template.html` so it consumes
     the parsed WaveDrom model. Keep: 200 px name column with live value at cursor, zoom (wheel, +/−,
     buttons), drag-pan, click-cursor, keyboard (`+ − 0 ← →`), nice time steps, dashed markers with
     labels, jump buttons, header time axis, bus hexagons with centred labels, `x`/`z` colouring,
     ResizeObserver redraw, devicePixelRatio handling.
   - `WaveSVG` (static, inline SVG): WaveDrom-style drawing for documents/print (like the
     "frame anatomy" figure in the template) — rounded transitions, bus labels, node/edge arrows,
     groups with brackets, head/foot text. Must look consistent with the canvas viewer and with
     the page's light/dark tokens (`var(--wave-1)`, `var(--wave-bus)`, `var(--wave-x)`, …).

3. **Page integration like the template**
   - Declarative: `<div class="wv" data-wave="#id-of-json-script"></div>` or
     `<script type="application/wavedrom">{…}</script>` blocks auto-upgraded on `DOMContentLoaded`,
     and programmatic: `new WaveView(el, model, opts)`, `WaveSVG.render(el, model)`.
   - Enum decoding map (`ENUMS`) per signal name, as in `decode()` of the template.
   - Lazy instantiation for collapsed `<details>` cards (keep the "Load waveform" pattern).
   - Theme: reuse the template's `:root` tokens, `prefers-color-scheme` dark block guarded by
     `:root:not([data-theme="light"])`, and `:root[data-theme="dark"]`; IBM Plex fonts from Google Fonts.
   - Single-file friendly: everything must work from `file://` with no build step and no bundler.

4. **VCD → WaveDrom converter (Python)** `tools/vcd2wavedrom.py`
   - Uses **wavepeek** (installed: `~/.local/bin/wavepeek`, v3.1.0; source in `~/tools/wavepeek_src`)
     — e.g. `wavepeek change --waves x.vcd --from … --to … --on '*' --sample-mode native
     --row-mode sparse --row-values delta --signals … --json` — to pull transitions and emit
     WaveDrom JSON with the `time` extension (choose `cycle` = one clock period or a user-given
     `--cycle 250ns`; collapse runs of unchanged values with `.`, insert `|` for `--gap`s).
   - Options: `--waves`, `--from/--to`, `--signals` (with optional `name=alias`), `--clock sig`
     (sample on posedge, WaveDrom cycle = one clock), `--cycle`, `--enum sig=0:IDLE,1:VERIFY…`,
     `--out`. Run with `python3 -I`.
   - Optional: note how to cross-check in **Surfer** (`cargo install surfer` / surfer-project.org)
     and how to export the same window there; do not make it a dependency.

5. **Deliverables** (in this directory)
   - `wavefw.js` (framework: parser + `WaveView` + `WaveSVG` + auto-upgrade), `wavefw.css`
   - `example.html`: a datasheet-style page like `template.html` (header, sticky TOC, `.bench`
     panels) demonstrating hand-written WaveDrom blocks (clock/bus/groups/edges/x-z), an interactive
     viewer with markers + jumps, a static SVG figure, and a lazy card.
   - `tools/vcd2wavedrom.py` + a tiny Verilog/SV testbench under `tools/demo/` runnable with
     **Verilator** (installed) that produces a VCD, so `make demo` regenerates `example.html` data
     end-to-end.
   - `README.md`: format reference (supported WaveDrom subset + extensions), API, converter usage.

## 2. Environment facts (do not assume otherwise)

- WSL2 Linux; **no node/npm**. Use vanilla ES2020+ JS; if you want stock `wavedrom.min.js` for a
  conformance comparison, fetch it from cdnjs/jsDelivr into `tools/vendor/` only for tests.
- `python3`, `verilator`, `cargo`, `wavepeek` available. Python **playwright** with Chromium
  (`~/.cache/ms-playwright/chromium-1243`) is available for screenshots/smoke tests.
- Working dir is on `/mnt/c` (slow); put build artefacts (obj_dir, VCD) under `/tmp` or the scratchpad.

## 3. Acceptance criteria

- `example.html` opens from `file://` with zero console errors in light and dark mode.
- Every WaveDrom char listed above renders (write a `tools/conformance.html` showing them side by
  side with stock WaveDrom if vendored).
- `WaveView` matches the template's behaviour: cursor value column updates, zoom clamps to data,
  markers/jumps work, bus labels hide when they don't fit, `x`/`z` drawn in `--wave-x`.
- `vcd2wavedrom.py` round-trip: VCD from the Verilator demo → JSON → page; a playwright script
  (`tools/smoke.py`) loads the page headless, asserts no errors, and saves PNG screenshots.
- No external runtime dependencies; one `<script src="wavefw.js">` + one `<link>` is enough.
- Code style: match `template.html` (compact, commented sections `/* ---- name ---- */`, CSS tokens).

Work incrementally: parser + static SVG first, then the canvas viewer, then the converter and demo,
then README. Report what was verified by actually running it (verilator, converter, playwright).
