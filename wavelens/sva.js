/* sva.js — SystemVerilog assertions in a wavelens page (docs/USAGE.md "Assertions", docs/sva/ENGINE.md). Loaded after wavelens.js.

   The engine: sva_wasm.wasm over its plain C ABI, JSON in and out (no fetch: the module comes inlined, from
   wavelens/sva.wasm.js = window.WAVELENS_SVA_WASM, deflate-raw + base64).
     const sva = await SVA.load(bytes)                  // or await SVA.engine() for the inlined module
     sva.parse(source) | sva.parse([src1, src2])         // the parsed file(s) (docs/sva/ast.schema.json)
     sva.evaluate(parsed, sampler, options)              // the results document of docs/sva/ENGINE.md
     SVA.tvSampler({name: {tv, width}}), SVA.rowSampler({name: model row})   samplers over WaveJSON "tv" / a viewer's rows
   sampler: { edges(name, edge) -> [time, …] | null, before(name, time) -> value | null, width(name) -> bits }.

   The assertions panel of every viewer (WaveLens.plugin): the loaded assertions, one line each (label, kind, property,
   signals, binding state), binding to an instance of the waveform (drag a line onto a module row, Bind…, the config's
   "bind"), evaluation on demand; each binding keeps its results document in binding.results (view.sva.bindings).
   Page data: window.SVA = { files: [{name, path, source, parsed?}], notes: [...] } (mkhtml.py) and per WaveJSON
   "sva": { files?: [...], bind: [{assert, scope, results?}] } (pre-bound, results from sva eval). Files loaded with
   "Load file…" and the bindings are kept in this browser (localStorage). */
(function (G) {
'use strict';
const SVA = G.SVA = G.SVA || {};
const DATA = { files: Array.isArray(SVA.files) ? SVA.files : [], notes: Array.isArray(SVA.notes) ? SVA.notes : [] };   // mkhtml.py's

/* ---------------- engine ---------------- */
// These four are also the source of the Web Worker (made from their text): they use nothing outside themselves.
function b64bytes(s) {
  const bin = atob(s), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}
async function inflate(u8) {
  const r = new Response(new Blob([u8]).stream().pipeThrough(new DecompressionStream('deflate-raw')));
  return new Uint8Array(await r.arrayBuffer());
}
async function instantiate(bytes) { // -> call(request) -> response, both plain objects
  if (bytes && !(bytes instanceof ArrayBuffer) && !ArrayBuffer.isView(bytes)) bytes = bytes.deflate ? await inflate(b64bytes(bytes.deflate)) :
    b64bytes(bytes.base64);
  const x = (await WebAssembly.instantiate(bytes, {})).instance.exports, enc = new TextEncoder(), dec = new TextDecoder();
  return req => {
    const b = enc.encode(JSON.stringify(req)), p = x.sva_alloc(b.length);
    new Uint8Array(x.memory.buffer, p, b.length).set(b);
    const r = x.sva_run(p, b.length), out = dec.decode(new Uint8Array(x.memory.buffer, r, x.sva_result_len()));
    x.sva_free(p, b.length);
    return JSON.parse(out);
  };
}
function workerMain() {
  let call = null;
  self.onmessage = async e => {
    const m = e.data;
    try {
      if (m.wasm) { call = await instantiate(m.wasm); self.postMessage({ id: m.id }); }
      else self.postMessage({ id: m.id, out: call(m.req) });
    } catch (err) { self.postMessage({ id: m.id, error: String((err && err.message) || err) }); }
  };
}

// An evaluation is one request per clock: the assertions on that clock and the trace sampled at its edges (`plan`);
// `assemble` makes the results document of their answers. The page's panel runs the same requests, some in a worker.
function plan(files, asserts, sampler, unit, opt = {}) {
  const groups = new Map();
  for (const a of asserts) {
    const k = a.clock.edge + ' ' + a.clock.signal;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(a);
  }
  return [...groups.values()].map(as => {
    const clk = as[0].clock, edges = sampler.edges(clk.signal, clk.edge);
    const tr = trace(sampler, edges || [], as.flatMap(a => a.signals.slice(1).map(s => s.name)), unit);
    return { clock: clk.signal, edges, n: as.length, req: { files, trace: tr, options: opt, assert: as.map(a => a.label) } };
  });
}
function assemble(steps, outs, unit) {
  const doc = { clock: '', unit, cycles: [], assertions: [] }, errors = [];
  steps.forEach((p, i) => {
    const r = outs[i];
    if (r.errors) { errors.push(...r.errors); return; }
    const first = !doc.clock;
    if (first) { doc.clock = p.clock; doc.cycles = p.edges || []; }
    for (const o of r.assertions) {
      if (!first) { o.clock = p.clock; o.cycles = p.edges || []; }
      if (!p.edges) o.missing = [p.clock, ...(o.missing || [])];
    }
    doc.assertions.push(...r.assertions);
  });
  if (errors.length) doc.errors = errors;
  return doc;
}

// bytes: an ArrayBuffer / Uint8Array of sva_wasm.wasm, or {deflate: base64} / {base64} (wavelens/sva.wasm.js)
async function load(bytes) {
  const raw = await instantiate(bytes);
  // a trap leaves the instance unusable: the next SVA.engine() makes a new one
  const call = req => { try { return raw(req); } catch (err) { ENGINE = null; throw err; } };
  const parse = src => Array.isArray(src) ? Object.assign(call({ files: src }), { sources: src }) : Object.assign(call({ source: src }), { source: src });
  // every assertion of the parsed file(s) (or the ones in options.assert) over a sampler, one call per clock
  function evaluate(parsed, sampler, options = {}) {
    const { assert: names, unit = 'ps', ...opt } = options, files = parsed.sources || [parsed.source];
    const all = parsed.files ? parsed.files.flatMap(f => f.assertions || []) : parsed.assertions || [];
    const steps = plan(files, all.filter(a => !names || names.includes(a.label)), sampler, unit, opt);
    return assemble(steps, steps.map(p => call(p.req)), unit);
  }
  return { parse, evaluate, call };
}
let ENGINE = null;
SVA.engine = () => ENGINE || (ENGINE = G.WAVELENS_SVA_WASM ? load(G.WAVELENS_SVA_WASM) :
  Promise.reject(new Error('no SVA engine in this page (wavelens/sva.wasm.js)')));
// A request that would take more than ~300 ms in the page goes to a Web Worker: its work is cycles × assertions, the rate
// (work per ms) is measured on the requests run in the page. SVA.syncLimit (work units), when set, decides instead.
SVA.rate = 450;
SVA.syncLimit = null;
const useWorker = work => typeof Worker !== 'undefined' && !!G.WAVELENS_SVA_WASM && (SVA.syncLimit != null ? work > SVA.syncLimit : work / SVA.rate > 300);
const calibrate = (work, ms) => { if (ms > 20) SVA.rate = Math.max(50, (SVA.rate + work / ms) / 2); };
let WORKER = null;
function worker() {
  if (WORKER) return WORKER;
  const src = [b64bytes, inflate, instantiate, workerMain].map(String).join('\n') + '\nworkerMain();\n';
  const url = URL.createObjectURL(new Blob([src], { type: 'text/javascript' })), w = new Worker(url), wait = new Map();
  let n = 0;
  const fail = err => { for (const [, p] of wait) p[1](err); wait.clear(); w.terminate(); URL.revokeObjectURL(url); if (WORKER && WORKER.w === w) WORKER = null;
    };
  w.onmessage = e => { const p = wait.get(e.data.id); if (!p) return; wait.delete(e.data.id); if (e.data.error) p[1](new Error(e.data.error));
    else p[0](e.data.out); };
  w.onerror = e => { e.preventDefault(); fail(new Error(e.message || 'the worker failed')); };
  const send = m => new Promise((ok, no) => { m.id = ++n; wait.set(m.id, [ok, no]); w.postMessage(m); });
  const ready = send({ wasm: G.WAVELENS_SVA_WASM });
  ready.catch(fail);
  WORKER = { w, call: req => ready.then(() => send({ req })) };
  return WORKER;
}

// the trace JSON of ENGINE.md: the value of every signal just before each clock edge
function trace(sampler, times, names, unit) {
  const signals = {}, widths = {};
  for (const n of names) {
    if (n in signals) continue;
    const col = sampler.column ? sampler.column(n, times) : times.map(t => sampler.before(n, t));
    if (!col || (times.length && col[0] == null && sampler.before(n, times[0]) == null)) continue;   // not there: the engine says "missing"
    signals[n] = col;
    const w = sampler.width && sampler.width(n);
    if (w) widths[n] = w;
  }
  return { cycles: times.length, times, unit, signals, widths };
}

// today as yyyy-mm-dd in the viewer's time zone (toISOString is UTC: after 21:00 in UTC+3 it says yesterday)
const localDate = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
// the helpers of wavelens.js (WaveLens.util: model.js); the spike page loads sva.js alone and gets copies of the ones it
// uses here (its tvSampler: isEdge)
const U = (G.WaveLens && G.WaveLens.util) || {
  esc: s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
  glob: p => new RegExp('^' + p.split('*').map(s => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('.*') + '$'),
  lastBefore(n, at, t, strict) { let lo = 0, hi = n - 1, ans = -1; while (lo <= hi) { const m = (lo + hi) >> 1, a = at(m);
    if (strict ? a < t : a <= t) { ans = m; lo = m + 1; } else hi = m - 1; } return ans; },
  isEdge(edge, prev, b) { if (prev === null) return false; const u = v => v === 'x' || v === 'z';
    const rise = (prev === '0' && b !== '0') || (u(prev) && b === '1'), fall = (prev === '1' && b !== '1') || (u(prev) && b === '0');
    return edge === 'posedge' ? rise : edge === 'negedge' ? fall : rise || fall; },
};
// the index of the last item with time < t (-1: none); at(i) gives the time of item i
const lastBefore = (n, at, t) => U.lastBefore(n, at, t, true);
const isEdge = U.isEdge;

// sampler over WaveJSON "tv" transitions: {name: {tv: [[t, v], …], width}} (bit values 0 1 x z, bus values hex)
function tvSampler(sigs) {
  const bit = v => String(v).toLowerCase();
  return {
    edges(name, edge) {
      const s = sigs[name];
      if (!s) return null;
      const out = [];
      let prev = null;
      for (const [t, v0] of s.tv || []) { const v = bit(v0).slice(-1); if (isEdge(edge, prev, v)) out.push(+t); prev = v; }
      return out;
    },
    before(name, t) {
      const s = sigs[name];
      if (!s) return null;
      const tv = s.tv || [], k = lastBefore(tv.length, i => +tv[i][0], t);
      if (k < 0) return 'x';
      const v = bit(tv[k][1]);
      return (s.width || 1) === 1 ? v : v.startsWith("'b") ? v.slice(2) : 'h' + v;   // "'b10x1": its bits (known ones among x / z)
    },
    width: name => sigs[name] && sigs[name].width,
  };
}

// the value of a viewer's transition o of row r for the engine: a bit, 'h' + hex, a number, binary digits
function rowValue(r, o) {
  if (!o) return 'x';
  if (o.k === '0' || o.k === '1') return o.k;
  if (o.k !== '=') return rowWidth(r) > 1 ? 'hx' : 'x';
  if (o.bits) return o.bits;   // known bits among x / z: binary digits (its hex would make them x)
  if (o.raw != null) return 'h' + o.raw;   // "tv": hex
  if (o.hex != null) return 'h' + o.hex;   // a clock-sampled view with its values next to the labels ("raw")
  const v = String(o.v).trim(), e = r.enum || (G.WaveLens && (G.WaveLens.enums[r.full] || G.WaveLens.enums[r.name]));
  if (e) for (const [n, l] of Object.entries(e)) if (l === v) return Number(n);
  return fromLabel(v, r.radix, rowWidth(r));
}
// a bus label as vcd2wavedrom.py writes it (label()), back to a value: 0x.. hex, 0o.. octal, binary digits, signed and
// unsigned decimal, "ascii"; anything else is unknown
function fromLabel(v, radix, w) {
  const big = n => n < 2n ** 53n ? Number(n) : 'h' + n.toString(16);
  if (/^0x[0-9a-f_]+$/i.test(v)) return 'h' + v.slice(2).replace(/_/g, '');
  if (/^0x[0-9a-fxz_]+$/i.test(v)) return 'h' + v.slice(2).replace(/_/g, '');
  if (/^0o[0-7]+$/i.test(v)) return big(BigInt(v));
  if ((radix === 'bin' || /^'b/i.test(v)) && /^('b)?[01xz_]+$/i.test(v)) return v.replace(/^'b/i, '').replace(/_/g, '');
  if (/^-\d+$/.test(v) && w) return big((1n << BigInt(w)) + BigInt(v));
  if (/^\d+$/.test(v)) return big(BigInt(v));
  if (radix === 'ascii' && /^".*"$/.test(v)) return 'h' + ([...v.slice(1, -1)].map(c => c.charCodeAt(0).toString(16).padStart(2, '0')).join('') || '0');
  if (/^'?[01xz]+$/i.test(v)) return v.replace("'", '');
  return 'x';
}
// the width of a row: "tv" rows know it, a wave-string row only from "width" (vcd2wavedrom.py writes it for buses)
const rowWidth = r => (r.src && r.src.tv ? r.width : r.src && r.src.width ? +r.src.width : null);
// sampler over the parsed rows of a viewer (WaveLens model rows: tr = [{t, k, raw | hex | v}]): {name: row}; a label is read
// back with the row's own radix (vcd2wavedrom.py makes the labels with it)
function rowSampler(rows) {
  return {
    edges(name, edge) {
      const r = rows[name];
      if (!r) return null;
      const out = [];
      let prev = null;
      for (const o of r.tr) { const b = o.k === '1' || o.k === '0' ? o.k : 'x'; if (isEdge(edge, prev, b)) out.push(o.t); prev = b; }
      return out;
    },
    before(name, t) {
      const r = rows[name];
      if (!r) return null;
      return rowValue(r, r.tr[lastBefore(r.tr.length, i => r.tr[i].t, t)]);
    },
    column(name, times) { // before() at every time, in one pass
      const r = rows[name];
      if (!r) return null;
      const out = new Array(times.length), a = r.tr;
      let k = -1;
      for (let i = 0; i < times.length; i++) { while (k + 1 < a.length && a[k + 1].t < times[i]) k++; out[i] = rowValue(r, a[k]); }
      return out;
    },
    width: name => rows[name] ? rowWidth(rows[name]) : null,
  };
}
Object.assign(SVA, { load, plan, assemble, tvSampler, rowSampler, fromLabel });

// the tooltips of the panel's and the bar's controls (WaveLens.tips): what each does, its keys
if (G.WaveLens && G.WaveLens.tips) G.WaveLens.tips.add({
  'sv:load': ['Load .sv / .sva files (kept in this browser)'], 'sv:tw': ['Fold / open the assertions'],
  'sv:watch': ['Read the files again when they change on the disk'], 'sv:json': ['The bindings (and files) as JSON for a config'],
  'sv:clear': ['Forget this browser\'s files and bindings'], 'sv:table': ['One row per binding: counts, failures, latency'],
  'sv:fails': ['Every failed attempt by time'], 'sv:xmd': ['Download the report as Markdown'], 'sv:xjson': ['Download the results as JSON'],
  'sv:bind': ['Bind to an instance', ['drag the line onto a module']], 'sv:edit': ['Edit it here', ['ctrl+Enter', 'Esc']],
  'sv:reload': ['Read its file from the disk again'], 'sv:del': ['Remove it from the list'], 'sv:eval': ['Evaluate again'],
  'sv:fail': ['Go to the first failure', [']f']], 'sv:unbind': ['Remove this binding'], 'sv:apply': ['Parse and evaluate', ['ctrl+Enter']],
  'sv:noedit': ['Cancel', ['Esc']], 'sv:revert': ['Back to the page\'s file'], 'sv:nopick': ['Close'], 'sv:to': ['Bind to this instance'],
  'sv:go': ['Go to this attempt'], 'sv:only': ['Only these attempts (again: all)'], 'sv:wt': ['The cursor to this cycle'], 'sv:nowhy': ['Close Why', ['Esc']],
  'x:prev': ['The previous time it becomes true', ['shift+Enter']], 'x:next': ['The next time it becomes true', ['Enter']],
  'x:add': ['Draw it as a row ƒ'], 'x:del': ['Remove the row ƒ'], '.svq': ['An expression of the signals: PSEL && !PREADY', ['Enter', 'shift+Enter']],
});

/* ---------------- the assertion files of the page ---------------- */
// files: the page's (window.SVA.files, WaveJSON "sva".files) and this browser's (Load file…), parsed as one compilation
// unit in that order; byLabel: label -> {a: assertion, file}
const LIB = { files: [], byLabel: new Map(), notes: [], panels: new Set(), parsing: null, svgs: new Set() };
const FILES_KEY = 'wavelens.sva.files:' + (G.location ? G.location.pathname : '');
const esc = U.esc;
const hash = s => { let h = 0x811c9dc5; for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193);
  return (h >>> 0).toString(16).padStart(8, '0'); };
// the waves' fingerprint: every signal's name, width and transitions (time, kind, exact four-state value) and the time
// range, each field ended by a separator (no two waves serialise alike). Results kept in this browser are of these waves
// only: a new simulation under the same name (⟳, a dump dropped again) is evaluated again
const waveId = M => {
  let h = 0x811c9dc5; const mix = s => { s = String(s); for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193);
    h = Math.imul(h ^ 0x1f, 0x01000193); };   // the separator: a code no field holds
  mix(M.t0); mix(M.t1);
  for (const r of M.rows) if (r.type === 'sig' && r.tr) { mix(r.full); mix(r.width || 1);
    for (const o of r.tr) { mix(o.t); mix(o.k); mix(o.bits ?? ''); mix(o.raw ?? ''); mix(o.hex ?? ''); mix(o.v ?? ''); } }   // what valOf reads
  return (h >>> 0).toString(16).padStart(8, '0'); };
SVA.waveId = waveId;   // (the tests)
// set() says whether it was kept (false: private mode or the storage is full)
const store = {
  get(k) { try { const v = localStorage.getItem(k); return v == null ? null : JSON.parse(v); } catch (e) { return null; } },
  set(k, v) { try { if (v == null) localStorage.removeItem(k); else localStorage.setItem(k, JSON.stringify(v)); return true; } catch (e) { return false; } },
};
// a file of this browser replaces the one of the same name; the page's are told apart by their content. The page's files
// come first in the compilation unit (a loaded file may use their packages and macros).
function addFile(f, origin, owner) {
  const file = { name: f.name, path: f.path || f.name, source: f.source || '', parsed: f.parsed || null, hash: f.hash || hash(f.source || ''), origin,
    owners: null };
  if (owner) file.owners = new Set([owner]);   // a diagram's own file ("sva" in its WaveJSON): listed in its viewer only
  const i = LIB.files.findIndex(x => x.name === f.name && x.origin === origin && (origin === 'local' || x.hash === file.hash));
  if (i >= 0) LIB.files[i] = file; else LIB.files.push(file);
  LIB.files.sort((a, b) => (a.origin === 'local') - (b.origin === 'local'));
  return file;
}
function pageFiles(models) {
  for (const f of DATA.files) if (!LIB.files.some(x => x.origin === 'page' && x.name === f.name && x.source === f.source)) addFile(f, 'page');
  for (const M of models) for (const f of (M.src.sva && M.src.sva.files) || []) {
    const same = LIB.files.find(x => x.origin === 'page' && x.name === f.name && x.source === f.source);
    if (!same) addFile(f, 'page', M.src); else if (same.owners) same.owners.add(M.src);
  }
}
function localFiles() { for (const f of store.get(FILES_KEY) || []) addFile(f, 'local'); }
// the files of the compilation unit: a page file is out while this browser has a file of its name (an edit in the page,
// a reload from the disk: ✎ / ⟳ replace it; Revert or Clear bring it back)
const shadowed = f => f.origin === 'page' && LIB.files.some(l => l.origin === 'local' && l.name === f.name);
const active = () => LIB.files.filter(f => !shadowed(f));
SVA.revertFile = async name => { LIB.files = LIB.files.filter(f => !(f.origin === 'local' && f.name === name)); saveLocal();
  LIB.files.forEach(f => { f.parsed = null; }); await reparse(); };
function saveLocal() { const l = LIB.files.filter(f => f.origin === 'local').map(({ name, hash, source }) => ({ name, hash, source }));
  store.set(FILES_KEY, l.length ? l : null); }
// parse the files that need it (every file as one unit with the engine, when one is not parsed yet), then index them
// When the engine stops on the unit (a trap), this browser's files are left out (and not kept) and the page's parse
// alone: the page's assertions still work, the panel says why and keeps its Clear button.
function reparse() {
  const need = active().some(f => !f.parsed);
  LIB.parsing = (!need ? Promise.resolve() : (async () => {
    let out, act = active();
    try { out = (await SVA.engine()).call({ files: act.map(f => f.source) }); }
    catch (err) {
      if (/no SVA engine/.test(err.message)) throw err;
      const gone = LIB.files.filter(f => f.origin === 'local');
      LIB.loadError =
        (`${gone.map(f => f.name).join(', ') || 'the files'}: the assertion engine stopped (${err.message}); ` +
          `${gone.length ? 'left out, not kept' : 'not parsed'}`);
      LIB.files = LIB.files.filter(f => f.origin !== 'local'); saveLocal(); act = active();
      try { out = (await SVA.engine()).call({ files: act.map(f => f.source) }); } catch (err2) { out = { files: [] }; }
    }
    (out.files || []).forEach((p, i) => { if (act[i]) act[i].parsed = p; });
  })().catch(err => { LIB.engineError = err.message; })).then(index);
  return LIB.parsing;
}
function index() {
  LIB.byLabel = new Map(); LIB.notes = DATA.notes.map(t => ({ text: t, err: true })); LIB.src = hash(SOURCES().join('\u0000'));
  if (LIB.engineError && LIB.files.some(f => !f.parsed)) LIB.notes.push({ text: 'assertions not parsed: ' + LIB.engineError, err: true });
  if (LIB.loadError) LIB.notes.push({ text: LIB.loadError, err: true });
  for (const f of active()) {
    const p = f.parsed;
    if (!p) continue;
    const pg = f.origin === 'local' && LIB.files.find(x => x.origin === 'page' && x.name === f.name);
    f.shadows = !!pg; if (pg && pg.owners) f.owners = pg.owners;   // in the viewers of the file it replaces
    for (const e of p.errors || []) LIB.notes.push({ text: `${f.name}:${e.line}:${e.col}: ${e.msg}`, err: true });
    for (const e of p.warnings || []) LIB.notes.push({ text: `${f.name}:${e.line}:${e.col}: ${e.msg}` });
    for (const a of p.assertions || []) {
      if (LIB.byLabel.has(a.label)) { LIB.notes.push({ text:
        `${f.name}:${a.line}: '${a.label}' is also in ${LIB.byLabel.get(a.label).file.name} (that one is used)` }); continue; }
      LIB.byLabel.set(a.label, { a, file: f });
    }
  }
  for (const p of [...LIB.panels]) {
    if (p.v.root.isConnected) p.sync(); else LIB.panels.delete(p);   // a viewer that is gone
    const x = p.v.svaExprs; if (x && x.list.length) x.again();   // package constants may have come
  }
}
SVA.fileList = () => LIB.files.map(({ name, path, origin, hash }) => ({ name, path, origin, hash }));
SVA.assertions = () => [...LIB.byLabel.values()].map(x => x.a);
// Load file…: File objects (or {name, text}) -> parsed and kept in this browser (by name; new content replaces the old)
SVA.loadFiles = async list => {
  for (const f of list) { const source = typeof f.text === 'function' ? await f.text() : f.text; addFile({ name: f.name, source, hash: hash(source) }, 'local');
    }
  LIB.files.filter(f => f.origin === 'local').forEach(f => { f.parsed = null; });
  if (LIB.files.some(f => f.origin === 'page')) LIB.files.forEach(f => { f.parsed = null; });   // one unit: the page's files first
  LIB.loadError = null;
  await reparse();
  saveLocal();   // after parsing: a file the engine stopped on was left out and is not kept
};

/* ---------------- editing an assertion in the page, reading a file from the disk again ---------------- */
// An assertion's statement in its file: from the start of the line of its label to the ';' that ends it (its action
// block too: else $error(…);). The engine gives UTF-8 byte offsets (at.start / at.end): -> string indexes.
function charAt(src, byte) {
  if (!/[^\x00-\x7f]/.test(src)) return byte;
  let b = 0, i = 0;
  while (i < src.length && b < byte) { const c = src.codePointAt(i); b += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; i += c > 0xffff ? 2 : 1; }
  return i;
}
function stmtRange(src, a) {
  let s = charAt(src, a.at.start), depth = 0;
  const e = charAt(src, a.at.end);
  while (s > 0 && src[s - 1] !== '\n') s--;
  for (let i = e; i < src.length; i++) {   // past strings and comments
    const c = src[i];
    if (c === '"') { for (i++; i < src.length && src[i] !== '"'; i++) if (src[i] === '\\') i++; }
    else if (c === '/' && src[i + 1] === '/') { while (i < src.length && src[i] !== '\n') i++; }
    else if (c === '/' && src[i + 1] === '*') { const k = src.indexOf('*/', i + 2); if (k < 0) break; i = k + 1; }
    else if ('([{'.includes(c)) depth++;
    else if (')]}'.includes(c)) depth--;
    else if (c === ';' && depth <= 0) return { s, e: i + 1 };
  }
  return { s, e };
}
// an assertion whose statement is not in the page's file that its file replaces: edited here or changed on the disk
const changedHere = (a, file) => { if (!file.shadows || !a.at) return false; const pg = LIB.files.find(x => x.origin === 'page' && x.name === file.name),
  r = stmtRange(file.source, a); return !!pg && !pg.source.includes(file.source.slice(r.s, r.e)); };
SVA.statement = label => { const x = LIB.byLabel.get(label); if (!x || !x.a.at) return null; const r = stmtRange(x.file.source, x.a);
  return { file: x.file.name, text: x.file.source.slice(r.s, r.e), line: x.a.line }; };
// What an evaluation of an assertion depends on (not where it is in its file): a binding evaluated for another one is
// evaluated again (Panel.sync)
const asig = a => JSON.stringify(a, (k, v) => (k === 'at' || k === 'line' ? undefined : v));
// ✎ Apply: the statement of `label` replaced by `text` in its file, which becomes this browser's copy (it replaces the
// page's file of that name); parsed as one unit. A text that does not parse leaves everything as it was: -> {ok, errors}
SVA.edit = async (label, text) => {
  const x = LIB.byLabel.get(label); if (!x || !x.a.at) return { ok: false, errors: [`no assertion '${label}'`] };
  const f = x.file, r = stmtRange(f.source, x.a), was = LIB.files.find(l => l.origin === 'local' && l.name === f.name);
  const src = f.source.slice(0, r.s) + text.replace(/\s+$/, '') + f.source.slice(r.e);
  const errs = () => LIB.notes.filter(n => n.err && n.text.startsWith(f.name + ':')).map(n => n.text), before = new Set(errs());
  await SVA.loadFiles([{ name: f.name, text: src }]);
  const errors = errs().filter(t => !before.has(t));
  if (errors.length || !LIB.byLabel.has(label)) {   // back to the file as it was
    if (was) await SVA.loadFiles([{ name: f.name, text: was.source }]); else await SVA.revertFile(f.name);
    return { ok: false, errors: errors.length ? errors : [`'${label}' is not in ${f.name} any more`] };
  }
  return { ok: true, errors: [] };
};
// ⟳ and Watch: a file read from the disk again. With the File System Access API (Chromium) the file is picked once and
// its handle kept (here and in IndexedDB, so a reload of the page asks only for the permission); elsewhere ⟳ asks for
// the file every time. The text replaces the file of that name (the page's or this browser's).
const HANDLES = new Map(), MTIME = new Map();
const idb = (mode, fn) => new Promise((ok, no) => {
  if (!G.indexedDB) return no(new Error('no IndexedDB'));
  const rq = G.indexedDB.open('wavelens-sva', 1);
  rq.onupgradeneeded = () => rq.result.createObjectStore('handles');
  rq.onerror = () => no(rq.error);
  rq.onsuccess = () => { try { const t = rq.result.transaction('handles', mode), q = fn(t.objectStore('handles')); t.oncomplete = () => ok(q && q.result);
    t.onerror = () => no(t.error); } catch (e) { no(e); } };
});
const pickFile = name => G.showOpenFilePicker
  ? G.showOpenFilePicker({ multiple: false, id: 'wavelens-sva', types: [{ description: 'SystemVerilog',
    accept: { 'text/plain': ['.sv', '.sva', '.svh', '.v', '.vh'] } }] }).then(([h]) => h)
  : new Promise((ok, no) => {   // no handles in this browser: a file input, the file read once
    const inp = Object.assign(document.createElement('input'), { type: 'file', accept: '.sv,.sva,.svh,.v,.vh,.txt' });
    inp.addEventListener('change', () => inp.files[0] ? ok({ name: inp.files[0].name, getFile: async () => inp.files[0],
      once: true }) : no(new Error('no file chosen')));
    inp.click();
  });
async function handleOf(name, pick) {
  let h = HANDLES.get(name);
  const key = (G.location ? G.location.pathname : '') + ':' + name;   // per page: another project's checks.sv is another file
  if (!h) { try { h = await idb('readonly', st => st.get(key)); } catch (e) { h = null; } }
  if (!h && pick) { h = await pickFile(name); if (!h.once) { try { await idb('readwrite', st => st.put(h, key));
    } catch (e) { /* not kept: picked again after a reload */ } } }
  if (h && h.queryPermission && (await h.queryPermission({ mode: 'read' })) !== 'granted' &&
    (await h.requestPermission({ mode: 'read' })) !== 'granted') throw new Error(`no permission to read ${name}`);
  if (h && !h.once) HANDLES.set(name, h);
  return h;
}
// -> {changed, name}: the text of the file of `name` from the disk (picked when there is no handle yet), loaded when new
SVA.reload = async (name, opt = {}) => {
  const h = await handleOf(name, opt.pick !== false); if (!h) return { changed: false, name };
  const f = await h.getFile(), text = await f.text(), cur = active().find(x => x.name === name);
  MTIME.set(name, f.lastModified);
  if (cur && cur.source === text && !opt.force) return { changed: false, name, picked: h.name };
  await SVA.loadFiles([{ name, text }]);
  return { changed: true, name, picked: h.name };
};
// Watch: every second the files with a handle; a newer one is read, parsed and its bindings evaluated again
SVA.watch = on => {
  clearInterval(LIB.watchT); LIB.watching = !!on;
  if (on) LIB.watchT = setInterval(async () => {
    if (LIB.watchBusy) return; LIB.watchBusy = true;
    try {
      for (const [name, h] of HANDLES) {
        const f = await h.getFile();
        if (MTIME.has(name) && f.lastModified !== MTIME.get(name)) {
          const r = await SVA.reload(name, { pick: false });
          if (r.changed) for (const p of LIB.panels) p.toast(`${name} changed on the disk: parsed and evaluated again`);
        }
        MTIME.set(name, f.lastModified);
      }
    } catch (e) { for (const p of LIB.panels) p.toast('watch: ' + e.message); }
    LIB.watchBusy = false;
  }, SVA.watchMs || 1000);
  for (const p of LIB.panels) p.render();
};
SVA.handles = () => [...HANDLES.keys()];

/* ---------------- scopes of a model and name resolution ---------------- */
// the parts of a hierarchical name: split at the dots, not inside a select (a[1.2]) nor in an escaped identifier
// (\esc.x, to the end: a dump drops the space that ends it); the same in svabuild.py and the CLI
function parts(p) {
  const out = []; let from = 0, depth = 0;
  for (let i = 0; i < (p || '').length; i++) {
    const c = p[i];
    if (c === '\\' && i === from) break;
    if (c === '[') depth++; else if (c === ']') depth--; else if (c === '.' && !depth) { out.push(p.slice(from, i)); from = i + 1; }
  }
  if (p) out.push(p.slice(from));
  return out.filter(Boolean);
}
const join = (a, b) => (a && b ? a + '.' + b : a || b);
const parent = p => parts(p).slice(0, -1).join('.');
// modules = groups that hold dump paths (vcd2wavedrom --hierarchy); every other group is transparent. root: the view's
// scope (WaveJSON meta.scope) or what is above the top modules. -> {root, abs: Map(group -> path), of: Map(row -> scope),
// sigs: Map(scope -> [rows]), scopes: [path] in display order, group(path) -> its group (null: the root or none)}
function scopeInfo(M) {
  if (M.svaScopes) return M.svaScopes;
  const abs = new Map(), of = new Map(), sigs = new Map();
  let root = (M.src.meta && M.src.meta.scope) || null;
  for (const r of M.rows) {
    if (r.type !== 'sig' || !(r.src && r.src.path)) continue;
    let p = r.src.path;
    for (let i = r.anc.length - 1; i >= 0; i--) { p = parent(p); const g = M.groups[r.anc[i]]; if (!abs.has(g)) abs.set(g, p); }
    if (root == null && !r.anc.length) root = parent(r.src.path);
  }
  if (root == null) { const tops = Object.values(M.groups).filter(g => abs.has(g) && !g.anc.length); root = tops.length ? parent(abs.get(tops[0])) : ''; }
  for (const r of M.rows) {
    if (r.type !== 'sig') continue;
    let s = root;
    for (let i = r.anc.length - 1; i >= 0; i--) { const g = M.groups[r.anc[i]]; if (abs.has(g)) { s = abs.get(g); break; } }
    of.set(r, s);
    if (!sigs.has(s)) sigs.set(s, []);
    sigs.get(s).push(r);
  }
  const scopes = [...(sigs.has(root) ? [root] : []), ...M.rows.filter(r => abs.has(r)).map(g => abs.get(g))];
  const byPath = new Map();
  for (const [g, p] of abs) if (!byPath.has(p)) byPath.set(p, g);
  return (M.svaScopes = { root, abs, of, sigs, scopes: [...new Set(scopes)], group: p => (p === root ? null : byPath.get(p) || null) });
}
const leaf = r => (r.src && r.src.path ? parts(r.src.path).pop() : r.name);
const strip = (n, pfx) => { const p = pfx.find(p => n.startsWith(p) && n.length > p.length); return p ? n.slice(p.length) : n; };
// a name of the assertion in scope S: exact name, then the shown name (alias), then without the ignored prefixes;
// a hierarchical name (u_fifo.full) below S -> {row, how?} | null
function lookup(I, S, name, pfx) {
  const ps = parts(name), base = ps.pop(), rows = I.sigs.get(join(S, ps.join('.'))) || [];
  let r = rows.find(r => leaf(r) === base);
  if (r) return { row: r };
  r = rows.find(r => r.name === base);
  if (r) return { row: r, how: `${name} → ${r.full} (shown as ${r.name})` };
  if (pfx.length) {   // several equal without the prefixes (i_valid, o_valid for valid): ambiguous, no guess
    const b = strip(base, pfx), hits = [...new Map(rows.filter(r => strip(leaf(r), pfx) === b || strip(r.name, pfx) === b).map(r => [r.full, r])).values()];
    if (hits.length > 1) return { many: hits };
    if (hits.length) return { row: hits[0], how: `${name} → ${hits[0].full} (prefixes ${pfx.join(' ')} ignored)` };
  }
  return null;
}
// every signal of assertion a in scope S of viewer v -> {ok, map: {name: row}, notes, missing, errors}
function resolve(v, a, S) {
  const I = scopeInfo(v.M), pfx = v.sortIgnore || [], map = {}, notes = [], missing = [], errors = [];
  a.signals.forEach((s, i) => {
    let hit = lookup(I, S, s.name, pfx);
    for (let up = S; !hit && i === 0 && up && up !== I.root; ) {   // the clock: also the nearest one of that name above
      up = parent(up);
      hit = lookup(I, up, s.name, pfx);
      if (hit) hit.how = `${s.name} → ${hit.row.full} (the clock, above the scope)`;
    }
    if (!hit) { missing.push(s.name); return; }
    if (hit.many) { errors.push(`${s.name} (ambiguous: ${hit.many.map(r => r.full).join(' or ')})`); return; }
    map[s.name] = hit.row;
    if (hit.how) notes.push(hit.how);
    const w = rowWidth(hit.row);
    if (s.width && w && s.width > w) errors.push(`${s.name}: a select needs ${s.width} bits, ${hit.row.full} has ${w}`);
  });
  return { ok: !missing.length && !errors.length, map, notes, missing, errors };
}
// the scopes of viewer v in which every signal of a resolves
const candidates = (v, a) => scopeInfo(v.M).scopes.filter(S => resolve(v, a, S).ok);
Object.assign(SVA, { scopeInfo, resolve, candidates });

/* ---------------- bindings: assertion + scope of a viewer, their results ---------------- */
const SOURCES = () => active().map(f => f.source);
const bkey = b => b.assert + '@' + b.scope;
// The page's bindings of a WaveJSON (its "sva.bind"), each "results.cycles" an array: mkhtml.py keeps the sampled times once
// per clock in "sva.cycles" and names them in "results.cycles" (tools/svabuild.py intern_cycles); an array there is read as
// it is (older pages). A name that is not in the table: the binding's error, not empty times. Once per WaveJSON.
const PAGEB = new WeakMap();
function pageBinds(M) {
  const x = M.src.sva;
  if (!x || !Array.isArray(x.bind)) return [];
  if (PAGEB.has(x)) return PAGEB.get(x);
  const T = (x.cycles && typeof x.cycles === 'object') ? x.cycles : {};
  const out = x.bind.map(b => {
    const r = b.results;
    if (!r || typeof r.cycles !== 'string') return b;
    if (!Array.isArray(T[r.cycles])) return { ...b, results: null, error: `no cycles table "${r.cycles}" in the page` };
    return { ...b, results: { ...r, cycles: T[r.cycles] } };
  });
  PAGEB.set(x, out);
  return out;
}
SVA.pageBinds = pageBinds;
// The bindings of one scope in one evaluation: one request per clock with all their assertions (the files are parsed
// once: the engine keeps the last unit). Each binding gets the results document of its assertion; progress(i, n) after
// each request. -> 'page' | 'worker'
async function evaluateScope(v, bs, progress) {
  const asserts = bs.map(b => LIB.byLabel.get(b.assert).a), rows = Object.assign({}, ...bs.map(b => b.res.map));
  if (v.lazy) await v.need(Object.values(rows));   // a large dump read as it is needed: the signals they read first
  const unit = v.M.timed ? 'ps' : 'cycles', steps = plan(SOURCES(), asserts, rowSampler(rows), unit);
  const eng = await SVA.engine(), outs = [];
  let via = 'page';
  for (const [i, p] of steps.entries()) {
    progress(i, steps.length, p);
    const work = (p.edges ? p.edges.length : 0) * p.n;
    let out = null;
    if (useWorker(work)) {
      try { out = await worker().call(p.req); via = 'worker'; } catch (err) { bs.forEach(b => { b.workerError = err.message; }); }
    }
    if (!out) {
      const t = performance.now();
      out = eng.call(p.req);
      calibrate(work, performance.now() - t);
    }
    outs.push(out);
  }
  const doc = assemble(steps, outs, unit);
  const err = (doc.errors || []).map(e => `${e.line}:${e.col}: ${e.msg}`).join('; ');
  for (const b of bs) {
    const o = doc.assertions.find(o => o.name === b.assert);
    if (!o) { b.error = err || 'not evaluated'; continue; }
    const cycles = o.cycles || doc.cycles, clock = o.clock || doc.clock;
    delete o.cycles; delete o.clock;
    o.scope = b.scope; o.signals = Object.fromEntries(Object.entries(b.res.map).map(([n, r]) => [n, r.full]));
    b.results = { clock: b.res.map[clock] ? b.res.map[clock].full : clock, unit: doc.unit, cycles, assertions: [o] };
    b.error = null; b.via = via;
  }
  return via;
}
const outcome = b => b.results && b.results.assertions && b.results.assertions[0];
const RID = new WeakMap(); let ridN = 0;
const resultsId = r => RID.get(r) || (RID.set(r, ++ridN), ridN);
// the counts of a results outcome; with `only` (a binding's filter, null for none) the listed kinds are buttons: a click
// shows only those attempts in the lane and lists them under the line
function counts(o, only) {
  const s = o.stats, btn = only !== undefined;
  const c = (k, text, cls = '') => btn && s[k] && k !== 'vacuous'
    ? (`<button type="button" class="cnum c-${k}${cls}${only === k ? ' on' : ''}" data-sv="only" data-k="${k}" aria-pressed="${only === k}" ` +
        `title="${only === k ? 'Show every attempt again' : `Only the ${k} attempts: in the lane and listed here`}">${text}</button>`)
    : `<span class="c-${k}${cls}">${text}</span>`;
  const n = k => s[k] ? [c(k, `${s[k]} ${k}`)] : [];
  if (o.kind === 'cover') { const m = s.matches ?? s.pass; return `${c('pass', `${m} match${m === 1 ? '' : 'es'}`)} in ${s.attempts} attempts`; }
  return [c('pass', `${s.pass} pass`), c('fail', `${s.fail} fail`, s.fail ? '' : ' zero'), `${s.vacuous} vacuous`, ...n('active'), ...n('disabled'),
    ...n('capped')].join(' · ');
}
const plainCounts = o => counts(o).replace(/<[^>]+>/g, '');

/* ---------------- on the waves: one group of rows per binding (stage 7) ---------------- */
// Under the module of its scope (view.extraRows; the top of the diagram for the view's own scope): "⚑ label · counts",
// the attempts lane (a bar from start to end per attempt, three sub-lanes, the per-cycle strip of `lane` on top), one
// row per step with a numbered circle at every trace point (✕ where an attempt failed), arrows along the trace of the
// selected attempt (of all of them when fewer than 20 are on screen; every one in the static SVG), and the bound signals
// again (svaSignals). `attempts` is the source; times come from the results' own `cycles`, so a build-time result over a
// clock-sampled view draws where the dump has it (a bar that starts before the window is clipped, not dropped).
const COL = { pass: 'sva-pass', fail: 'sva-fail', disabled: 'sva-disabled', active: 'sva-active', capped: 'sva-capped', vacuous: 'muted' };
const RANK = { vacuous: 0, pass: 1, active: 2, capped: 3, disabled: 4, fail: 5 };
const STRIP = { S: 1, P: 2, C: 3, D: 4, F: 5 }, STRIP_COL = [null, 'muted', 'sva-pass', 'sva-capped', 'sva-disabled', 'sva-fail'];
const MANY = 20;   // arrows of every attempt on screen below this many
const globRx = U.glob;
const shown = S => { const l = S.svaShow == null ? null : (Array.isArray(S.svaShow) ? S.svaShow : String(S.svaShow).split(',')).map(s =>
  s.trim()).filter(Boolean).map(globRx); return n => !l || l.some(rx => rx.test(n)); };
// the index of the first item with time >= t (lastBefore + 1)
const firstFrom = (n, at, t) => lastBefore(n, at, t) + 1;
// the hit under (x, y) of a lane's bars [a, b, y0, y1, x] / of a step row's circles [x, p]
const barAt = (hits, x, y) => hits.find(([a, b, y0, y1]) => x >= a - 2 && x <= b + 2 && y >= y0 - 1 && y <= y1 + 1);
const dotAt = (hits, x) => hits.filter(([hx]) => Math.abs(hx - x) <= 8).sort((a, b) => Math.abs(a[0] - x) - Math.abs(b[0] - x))[0];
// the failure arrow's label from reason.kind (the note is the tooltip)
function why(a) {
  const k = a.reason && a.reason.kind, n = String(a.note || '').replace(/ at cycle \d+/, '');
  const t = { unknown: n.replace(/ is unknown \(x\)/, ' is x'), strong_end: 'not before the end', not_held: "'not' held", capped: 'thread limit' }[k] || n ||
    k || 'fail';
  return t.length > 42 ? t.slice(0, 40) + '…' : t;
}
const cut = (t, n) => (t.length > n ? t.slice(0, n - 1) + '…' : t);
// a property in parts that wrap as a whole: a part starts at a sequence or property operator (|-> |=> ## #-# #=#
// intersect throughout within and or iff implies until …); an operator alone joins the part after it
const PROP_OP =
  ('\\|->|\\|=>|#-#|#=#|##\\S*|(?:intersect|throughout|within|and|or|iff|implies|s_until_with|until_with|s_until|until|s_eventually|eventually|s_nexttime|nex' +
    'ttime|s_always|always|not|if|else)\\b');
const PROP_AT = new RegExp(` (?=(?:${PROP_OP}))`), PROP_ONLY = new RegExp(`^(?:${PROP_OP})$`);
function propParts(text) {
  const out = [];
  for (const p of String(text).split(PROP_AT)) {
    const L = out[out.length - 1];
    if (L != null && PROP_ONLY.test(L)) out[out.length - 1] = L + ' ' + p; else out.push(p);
  }
  return out;
}
SVA.propParts = propParts;
// the names of the assertion (a Set) that a step's label reads, in the order they come: strings, based literals and
// system functions are no names; `a.b` is a.b or else a
function stepSignals(label, names) {
  const out = [], src = label.replace(/"(?:[^"\\]|\\.)*"/g, ' ').replace(/\d*'[sS]?[bodhBODH]\s*[\w?]+/g, ' ');
  for (const w of src.matchAll(/\$?[A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*/g)) {
    let t = w[0]; if (t[0] === '$') continue;
    while (t && !names.has(t)) { const i = t.lastIndexOf('.'); t = i < 0 ? '' : t.slice(0, i); }
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}
SVA.stepSignals = stepSignals;
// the attempt a figure without a selection (the static SVG) shows on the signals: the first failure, else the first one
const focusOf = o => { const as = o.attempts || [], f = o.kind !== 'cover' ? as.findIndex(a => a.result === 'fail') : -1;
  return f >= 0 ? f : as.length ? 0 : -1; };
// the end flag of an attempt: did it end, and how
const END = { pass: '✓ pass', fail: '✕ fail', active: '… not ended', disabled: '⊘ disabled', capped: '… capped' };
// one results document -> what the rows draw: attempts with their times and sub-lane, trace points per step
function shape(res, only) {
  const o = res.assertions[0], T = o.cycles || res.cycles || [], at = c => T[Math.min(Math.max(c, 0), T.length - 1)];
  const steps = o.steps || [], num = new Map(steps.map((s, k) => [s.id, k]));
  let lastCons = steps.length - 1;
  while (lastCons > 0 && steps[lastCons].role !== 'cons' && steps[lastCons].role !== 'seq') lastCons--;
  const atts = (o.attempts || []).map((a, i) => ({ a, i, r: a.result, t0: at(a.start), t1: at(Math.max(a.end, a.failed_at ?? a.end)), pts: [] })).filter(x =>
    !only || x.r === only);
  const lanes = [[], []], rest = [], ends = [-1, -1];
  const pts = steps.map(() => []);
  for (const x of atts) {
    const k = x.a.start > ends[0] ? 0 : x.a.start > ends[1] ? 1 : 2;
    if (k < 2) { ends[k] = Math.max(x.a.end, x.a.failed_at ?? x.a.end); lanes[k].push(x); } else rest.push(x);
    (x.a.trace || []).forEach(([id, c, v], j) => {   // a truncated trace keeps steps 0–15 and the last 47: the cut is before 16
      const s = num.get(id); if (s == null) return;
      const p = { t: at(c), c, s, x, v, cut: x.a.truncated && j === 16 }; pts[s].push(p); x.pts.push(p);
    });
    if (x.r === 'fail') {
      const s = num.has(x.a.reason && x.a.reason.step) ? num.get(x.a.reason.step) : Math.max(lastCons, 0), c = x.a.failed_at ?? x.a.end;
      if (steps.length) { x.fail = { t: at(c), c, s, x, fail: true }; pts[s].push(x.fail); }
      x.tf = at(c); x.tok = Math.min(x.pts.length ? x.pts[x.pts.length - 1].t : x.t0, x.tf);   // the last good step: red from there
    }
  }
  // the third sub-lane: the rest, merged where they overlap (a count on the bar)
  const third = [];
  for (const x of rest) {
    const L = third[third.length - 1];
    if (L && x.t0 <= L.t1) { L.t1 = Math.max(L.t1, x.t1); L.n++; if (RANK[x.r] > RANK[L.r]) { L.r = x.r; L.x = x; } }
    else third.push({ t0: x.t0, t1: x.t1, n: 1, r: x.r, x });
  }
  pts.forEach(p => p.sort((a, b) => a.t - b.t));
  let mt1 = -Infinity;
  for (const x of atts) x.mt1 = mt1 = Math.max(mt1, x.t1);   // the latest end so far: how far back an attempt can still cover t
  const one = x => ({ t0: x.t0, t1: x.t1, n: 1, r: x.r, x });
  return { o, T, steps, atts, lanes: [lanes[0].map(one), lanes[1].map(one), third], pts };
}
function hatch(P, x0, y0, w, h, col) {
  P.clip(x0, y0, w, h, () => { const d = []; for (let x = x0 - h; x < x0 + w; x += 4) d.push(['M', x, y0 + h], ['L', x + h, y0]);
    P.path(d, { stroke: col, w: 1, alpha: 0.9 }); });
}
// one attempt with room: a bracket from its start to its end (ticks at both ends; an active or capped one stays open),
// over a light band; a failure green up to its last matched step, red from there to where it failed -> the split x
function bracket(P, x, a, b, y, h, X, cell) {
  const r = x.r, c = COL[r], th = Math.max(2, Math.min(3, Math.round(h / 3))), open = r === 'active' || r === 'capped';
  let split = null;
  if (r === 'fail') {
    split = x.tok < x.tf ? X(x.tok) : X(x.tf) - cell / 2;   // the failing cycle at least: half a cycle before its edge
    split = Math.min(Math.max(split, a), b);
  }
  const seg = (u, v, col) => { if (v - u > 0) { P.rect(u, y, v - u, h, col, 0.14); P.rect(u, y, v - u, th, col, open ? 0.6 : 0.95); } };
  if (split == null) seg(a, b, c); else { seg(a, split, 'sva-pass'); seg(split, b, 'sva-fail'); }
  if (open && b - a >= 6) hatch(P, a, y + th, b - a, h - th, c);
  P.rect(a, y, 2, h, split != null && split <= a ? 'sva-fail' : split != null ? 'sva-pass' : c, 0.95);   // where it starts
  if (!open) P.rect(b - 2, y, 2, h, c, 0.95);   // where it ends: an open one has no end
  return split;
}
function bar(P, r, a, b, y, h) {
  const w = b - a, c = COL[r];
  if (r === 'active' || r === 'capped') { P.rect(a, y, w, h, c, 0.25); if (w >= 6) hatch(P, a, y, w, h, c); else P.rect(a, y, w, h, c, 0.6); }
  else P.rect(a, y, w, h, c, r === 'disabled' ? 0.7 : 0.9);
}
const circlePath = (x, y, r) => G.WaveLens.util.circle(x, y, r);
function dot(P, x, y, p, small, sel) {
  const c = p.fail ? 'sva-fail' : COL[p.x.r];
  if (small) { P.path(circlePath(x, y, p.fail ? 4 : 3), { fill: c }); return; }
  P.path(circlePath(x, y, 7), { fill: c, stroke: sel ? 'hl8' : 'panel', w: sel ? 2 : 1.2 });
  if (p.fail) P.path([['M', x - 3, y - 3], ['L', x + 3, y + 3], ['M', x + 3, y - 3], ['L', x - 3, y + 3]], { stroke: 'panel', w: 1.8 });
  else P.text(x, y + 0.5, String(p.s + 1), { anchor: 'middle', size: 9, weight: 700, fill: 'panel' });
}
// the rows of one binding. st: kept between calls (same row objects while the results stay); opt: {S, label, scope,
// copies: [rows], map: {name: row} of the bound signals, sel() -> attempt index | -1, pick(i), focus: the attempt the
// static SVG shows on the signals, view (null: static SVG), base: {anc, depth} of the place}
function assertionRows(st, res, opt) {
  const S = opt.S, rh = S.rowHeight || 26, svg = !opt.view;
  if (st.res !== res || st.only !== opt.only) { st.res = res; st.only = opt.only; st.m = shape(res, opt.only); st.rows = null; }
  const m = st.m, o = m.o, { anc, depth } = opt.base;
  if (!st.gid) st.gid = G.WaveLens.rowId();
  const s = o.stats || {}, cover = o.kind === 'cover';
  const sc = opt.scope || '(top)', fails = !cover && s.fail > 0, full = opt.scope ? `${opt.label}@${opt.scope}` : opt.label;
  const g = st.g || (st.g = { type: 'group', id: st.gid });
  Object.assign(g, { name: `⚑ ${opt.label} · ${plainCounts(o).replace(/ in \d+ attempts$/, '').replace(/ · \d+ vacuous/, '')}`, full, path: full, anc, depth,
    title: `${opt.label} bound to ${sc}: ${o.text || ''}`, stroke: fails ? 'var(--sva-fail)' : 'var(--accent)', cls: 'sva-g' + (fails ? ' fails' : ''),
      sva: opt.label,
    legend: [{ text: cut(`⚑ ${opt.label} @ ${sc}: ${o.text || ''}`, 110), bold: true },
      ...m.steps.map((x, k) => ({ n: k + 1, text: `${x.label}  (${x.role})`, color: 'muted' }))] });
  const kid = { anc: anc.concat(st.gid), depth: depth + 1 };
  const isSel = x => !svg && opt.sel() === x.i;
  const tip = (x, view, note = true) => {
    const a = x.a, fa = a.failed_at != null && a.failed_at !== a.end ? `, failed at ${view.when(m.T[Math.min(a.failed_at, m.T.length - 1)])}` : '';
    return (`attempt ${x.i + 1}: ${x.r}, ${view.when(x.t0)}${a.start === a.end ? '' : ` → ${view.when(m.T[Math.min(a.end, m.T.length - 1)])}`}${fa} ` +
        `(cycle${a.start === a.end ? ' ' + a.start : `s ${a.start}–${a.end}`})${a.truncated ? ', trace cut' : ''}${a.note && note ? ' — ' + a.note : ''}`);
  };
  // attempts lane
  const lane = st.lane || (st.lane = { type: 'sig' });
  Object.assign(lane, kid, { name: opt.only ? `attempts: ${opt.only}` : 'attempts', full: `${g.full}/attempts`, cls: 'sva-lane', height: Math.max(44, rh + 18),
    hits: [], drawn: 0,
    draw(P, { y, h, X, tA, tB, xL, xR }) {
      const hits = this.hits = [], W = Math.ceil(xR - xL) + 2, cx = x => Math.min(Math.max(x, xL - 4), xR + 4);
      if (o.lane) {   // the per-cycle strip: the strongest event per pixel, failures at least 2 px wide
        const col = new Uint8Array(W), lane = o.lane, T = m.T;
        // one cycle wide, centred on its edge
        for (let k = Math.max(0, firstFrom(T.length, i => T[i], tA) - 1); k < T.length && (k === 0 || T[k - 1] <= tB); k++) {
          const r = STRIP[lane[k]]; if (!r) continue;
          const xe = X(T[k]) - xL, half = (k + 1 < T.length ? X(T[k + 1]) - xL - xe : k > 0 ? xe - X(T[k - 1]) + xL : 2) / 2, x0 = xe - half, x1 = xe + half;
          const c0 = Math.max(0, Math.floor(x0)), c1 = Math.min(W, Math.max(c0 + (r === 5 ? 2 : 1), Math.ceil(x1)));
          for (let c = c0; c < c1; c++) if (col[c] < r) col[c] = r;
        }
        for (let c = 0; c < W;) { const r = col[c]; let e = c + 1; while (e < W && col[e] === r) e++;
          if (r) P.rect(xL + c, y + 2, e - c, 3, STRIP_COL[r], r === 1 ? 0.5 : 0.95); c = e; }
      }
      const lh = Math.floor((h - 9) / 3), cell = m.T.length > 1 ? (X(m.T[m.T.length - 1]) - X(m.T[0])) / (m.T.length - 1) : 8;
      const pad = Math.min(Math.max(cell / 2 - 2, 2), 16);   // a bar covers its first and last cycle (a gap to the next one)
      const marks = this.marks = [];   // what was drawn: [result, a, b, split | null, bracket] (tests)
      let drawn = 0;
      m.lanes.forEach((items, k) => {
        const by = y + 7 + k * lh, bh = lh - 1;
        let run = null;
        const flush = () => {
          if (!run) return;
          const one = run.n === 1 && run.b - run.a >= 6;   // one attempt with room: a bracket; crowded ones: a bar
          marks.push([run.r, run.a, run.b, one ? bracket(P, run.x, run.a, run.b, by, bh, X, cell) : (bar(P, run.r, run.a, run.b, by, bh), null), one]);
          if (run.sel) P.path([['M', run.a - 1, by - 1], ['L', run.b + 1, by - 1], ['L', run.b + 1, by + bh + 1], ['L', run.a - 1, by + bh + 1], ['Z']],
            { stroke: 'hl8', w: 1.5 });
          if (run.n > 1 && k === 2 && run.b - run.a > 16) P.text((run.a + run.b) / 2, by + bh / 2, '×' + run.n,
            { anchor: 'middle', size: 8.5, weight: 700, fill: 'panel' });
          hits.push([run.a, run.b, by - y, by - y + bh, run.x]); drawn += run.n; run = null;
        };
        for (let i = firstFrom(items.length, j => items[j].t1, tA); i < items.length && items[i].t0 <= tB; i++) {
          const it = items[i];
          const a = cx(X(it.t0) - pad), b = cx(X(it.t1) + pad);
          if (run && a <= run.b + 0.5) { run.b = Math.max(run.b, b); run.n += it.n;
            if (RANK[it.r] > RANK[run.r]) { run.r = it.r; run.x = it.x; } run.sel = run.sel || isSel(it.x); continue; }
          flush(); run = { a, b, n: it.n, r: it.r, x: it.x, sel: isSel(it.x) };
        }
        flush();
      });
      this.drawn = drawn;
    },
    click(x, y) { const h = barAt(this.hits, x, y); if (!h) return false; opt.pick(h[4].i); return true; },
    tip(x, y, view) { const h = barAt(this.hits, x, y); return h ? tip(h[4], view) : ''; },
    value(t) {   // the attempts at the cursor: the strongest result (and how many more)
      let best = null, n = 0;
      for (let i = lastBefore(m.atts.length, j => m.atts[j].t0, t + G.WaveLens.util.timeEps(t)); i >= 0 && m.atts[i].mt1 >= t; i--) { const x = m.atts[i];
        if (x.t1 >= t) { n++; if (!best || RANK[x.r] > RANK[best.r]) best = x; } }
      return best ? best.r + (n > 1 ? ` +${n - 1}` : '') : '';
    } });
  // step rows
  st.steps = st.steps || [];
  const steps = m.steps.map((stp, k) => {
    const r = st.steps[k] || (st.steps[k] = { type: 'sig' });
    return Object.assign(r, kid, { name: `${k + 1}. ${cut(stp.label, 40)}`, full: `${g.full}/${stp.id}`, cls: 'sva-step', hits: [], role: stp.role,
      draw(P, { y, h, X, tA, tB, xL }) {
        const ps = m.pts[k], ym = y + h / 2, hits = this.hits = [];
        let i = Math.max(0, firstFrom(ps.length, j => ps[j].t, tA) - 1), last = -1e9;
        for (; i < ps.length && ps[i].t <= tB; i++) {
          const p = ps[i], x = X(p.t);
          p.sm = true;   // small unless drawn with room: the overlay draws it the same way
          if (x < xL - 8) continue;
          if (!p.fail && x - last < 2) continue;
          const room = x - last >= 14 && (i + 1 >= ps.length || X(ps[i + 1].t) - x >= 14);   // dense here: a dot without its number
          p.sm = !room; last = x; dot(P, x, ym, p, !room, isSel(p.x)); hits.push([x, p]);
        }
      },
      click(x) { const h = dotAt(this.hits, x); if (!h) return false; opt.pick(h[1].x.i); return true; },
      tip(px, y, view) {
        const h = dotAt(this.hits, px); if (!h) return '';
        const p = h[1], v = p.v != null ? ` = ${typeof p.v === 'number' ? '0x' + p.v.toString(16) : p.v}` : '';
        return p.fail ? `${stp.label}: ${p.x.a.note || why(p.x.a)} — ${tip(p.x, view, false)}` :
          `step ${k + 1} ${stp.label} at cycle ${p.c}${v} — ${tip(p.x, view)}`;
      },
      value: () => '' });
  });
  // the bound signals again, under the steps (they show the same transitions)
  st.cp = st.cp || new Map();
  const copies = opt.copies.map(src => {
    const r = st.cp.get(src) || { type: 'sig', same: true };
    st.cp.set(src, r);
    return Object.assign(r, kid, { name: src.name, full: src.full, tr: src.tr, gaps: src.gaps, width: src.width, enum: src.enum, radix: src.radix,
      style: src.style,
      stroke: src.stroke, fill: src.fill, tv: src.tv, end: src.end, src: src.src, cls: 'sva-copy', of: src });
  });
  // the rows each step reads, by name in its label: the bound signals (src) and their copies in the group (cp)
  const map = opt.map || {}, names = new Set(Object.keys(map)), cpOf = new Map(copies.map(c => [c.of, c]));
  const reads = m.steps.map(stp => { const rs = stepSignals(stp.label, names).map(n => map[n]);
    return { src: rs, cp: rs.map(r => cpOf.get(r)).filter(Boolean) }; });
  const marked = [...new Set(reads.flatMap(x => x.src))];
  // arrows along the traces: every attempt on screen when there are few (the static SVG: all), the selected one in front;
  // the selected attempt (the static SVG: focusOf) also on the signals its steps read, its start and end as dashed lines
  // across the rows with flags in the group's band: ▶ start, and how it ended (✓ pass, ✕ fail, … not ended)
  st.overlay = g.overlay = (P, { pos, X, tA, tB, xL, xR, yA, yB }) => {
    const ym = r => { const q = pos.get(r); return q ? q.y + q.h / 2 : null; };
    const seen = r => { const q = pos.get(r); return !!q && q.y + q.h > yA && q.y < yB; };
    if (ym(steps[0] || lane) == null) return;
    const sel = svg ? -1 : opt.sel(), fi = svg ? opt.focus ?? -1 : sel, fx = fi >= 0 ? m.atts.find(x => x.i === fi) : null;
    const near = (p, q) => Math.hypot(p[0] - q[0], p[1] - q[1]) < 0.5, labels = [], drawn = g.arrows = [], flow = g.flow = [];   // what was drawn (tests)
    if (fx) {   // start and end: under everything else
      const xs = X(fx.t0), xe = X(fx.t1), vl = (x, c) => { if (x >= xL - 2 && x <= xR + 2) P.path([['M', x, yA], ['L', x, yB]],
        { stroke: c, w: 1, dash: [4, 3] }); };
      vl(xs, 'hl8'); if (xe - xs >= 1) vl(xe, COL[fx.r]);
      const q = pos.get(g);
      if (q) {
        const yf = q.y + q.h / 2, flag = (x, text, col, anchor) => {
          const tw = P.measure(text, { size: 10 }), bx = anchor === 'end' ? x - tw - 6 : x;
          P.rect(bx, yf - 6.5, tw + 6, 13, 'panel'); P.path([['M', bx, yf - 6.5], ['L', bx + tw + 6, yf - 6.5], ['L', bx + tw + 6, yf + 6.5],
            ['L', bx, yf + 6.5], ['Z']], { stroke: col, w: 1 });
          P.text(anchor === 'end' ? x - 3 : x + 3, yf + 0.5, text, { anchor, size: 10, weight: 600, fill: col });
          flow.push({ flag: text });
        };
        const end = END[fx.r] || fx.r, ws = P.measure('▶ start', { size: 10 }) + 6, we = P.measure(end, { size: 10 }) + 6;
        if (xe - xs < 2) flag(xs + 2, `▶ ${end}`, COL[fx.r], 'start');
        else if (xe - xs >= ws + we + 8) { flag(xs + 2, '▶ start', 'hl8', 'start'); flag(xe - 2, end, COL[fx.r], 'end'); }
        else { flag(xs - 2, '▶ start', 'hl8', 'end'); flag(xe + 2, end, COL[fx.r], 'start'); }
      }
    }
    const stepsOn = [lane, ...steps].some(seen), on = [];
    if (stepsOn) for (const x of m.atts) { if (x.t0 > tB) break; if (x.t1 >= tA && x.pts.length + (x.fail ? 1 : 0) > 1) on.push(x); }
    const list = svg || on.length < MANY ? on.filter(x => x.i !== sel) : [];
    const s = stepsOn && m.atts.find(x => x.i === sel); if (s && s.pts.length + (s.fail ? 1 : 0) > 1) list.push(s);
    const arrow = (A, B, col, w, dash, label, front) => {
      const g = G.WaveLens.paint.edgeGeom({ shape: A[1] === B[1] ? '-' : '-|-' }, A[0], A[1], B[0], B[1]);
      P.path(g.d, { stroke: col, w, dash }); drawn.push({ col, label, front: !!front });
      const f = near(g.e, B) ? A : g.e, L = Math.hypot(B[0] - f[0], B[1] - f[1]) || 1, tipP = [B[0] - 8 * (B[0] - f[0]) / L, B[1] - 8 * (B[1] - f[1]) / L];
      if (L > 9) G.WaveLens.paint.arrowHead(P, tipP[0], tipP[1], f[0], f[1], col);
      if (label) labels.push({ m: g.m, label, col, front });
    };
    for (const x of list) {
      const front = x.i === sel, col = front ? 'hl8' : svg ? 'acc' : 'muted', w = front ? 1.6 : 1;
      const at = p => { const y = ym(steps[p.s]); return y == null ? null : [X(p.t), y]; };
      for (let k = 1; k < x.pts.length; k++) {
        const A = at(x.pts[k - 1]), B = at(x.pts[k]); if (!A || !B || near(A, B)) continue;
        const dc = x.pts[k].c - x.pts[k - 1].c;
        if (x.pts[k].cut) arrow(A, B, 'muted', 1, [2, 3], `… ${dc}T (trace cut)`, front);   // the steps between were not kept
        else arrow(A, B, col, w, null, dc ? dc + 'T' : '', front);
      }
      if (x.fail) {
        const A = x.pts.length ? at(x.pts[x.pts.length - 1]) : null, B = at(x.fail);
        if (A && B && !near(A, B)) arrow(A, B, 'sva-fail', front ? 1.6 : 1.2, [4, 3], why(x.a), front);
      }
      // in front of the lines, as the row drew them
      for (const p of x.fail ? x.pts.concat(x.fail) : x.pts) { const q = at(p); if (q && q[0] >= xL - 8 && q[0] <= xR + 8) dot(P, q[0], q[1], p, !front &&
        p.sm !== false, front); }
    }
    // the focused attempt on the signals: a numbered circle on every row its step reads, arrows from the first of one
    // step to the first of the next (the bound signals and their copies in the group, each set on its own)
    if (fx) for (const set of ['src', 'cp']) {
      const pts = fx.fail ? fx.pts.concat(fx.fail) : fx.pts, dots = [];
      let A = null;
      for (const p of pts) {
        const rs = reads[p.s][set].filter(r => pos.has(r)); if (!rs.length) continue;
        const B = [X(p.t), ym(rs[0])];
        if (A && !near(A, B)) {
          if (p.fail) arrow(A, B, 'sva-fail', 1.6, [4, 3], why(fx.a), true);
          else arrow(A, B, 'hl8', 1.6, p.cut ? [2, 3] : null, '', true);
        }
        A = B;
        for (const r of rs) dots.push([B[0], ym(r), p]);
      }
      for (const [x, y, p] of dots) if (x >= xL - 8 && x <= xR + 8) { dot(P, x, y, p, false, true); flow.push({ on: set, s: p.s + 1, fail: !!p.fail, x, y }); }
    }
    // labels last: the selected attempt's first, the others where no label is yet
    const boxes = [];
    for (const l of labels.sort((a, b) => b.front - a.front)) {
      const tw = P.measure(l.label, { size: 10 }), bx = [l.m[0] - tw / 2 - 3, l.m[0] + tw / 2 + 3, l.m[1] - 6.5, l.m[1] + 6.5];
      if (!l.front && boxes.some(q => bx[0] < q[1] && q[0] < bx[1] && bx[2] < q[3] && q[2] < bx[3])) continue;
      boxes.push(bx); P.rect(bx[0], bx[2], tw + 6, 13, 'panel'); P.text(l.m[0], l.m[1], l.label, { anchor: 'middle', size: 10, fill: l.col, weight: 600 });
    }
  };
  for (const r of [lane, ...steps, ...copies]) r.overlay = st.overlay;   // drawn when any of its rows is on screen
  st.overlay.rows = marked;   // or one of the signals it marks
  st.rows = [g, lane, ...steps, ...copies];
  return st.rows;
}

/* ---------------- the panel ---------------- */
class Panel {
  constructor(v) {
    this.v = v; v.sva = this; this.bindings = []; this.pick = null; this.open = !!v.S.svaOpen; this.jsonOpen = false;   // the list folded unless svaOpen
    this.key = 'wavelens.sva:' + (v.storeId || G.location.pathname + ':' + (v.opts.key || v.root.id || v.root.dataset.wave || v.M.title));
    this.el = document.createElement('div'); this.el.className = 'sva'; this.el.hidden = true;
    v.addPanel(this.el);
    if (G.WAVELENS_SVA_WASM) {
      const g = v.addTool('assertions',
        ('<button type="button" data-sv="load" title="Load SystemVerilog assertion files (.sv, .sva): parsed in the page, kept in this browser">Load ' +
          'file…</button><input type="file" class="svfile" multiple accept=".sv,.sva,.svh,.v,.vh,.txt" hidden>'));
      g.classList.add('sv');
      const inp = g.querySelector('input.svfile');
      g.querySelector('button[data-sv=load]').addEventListener('click', () => inp.click());
      inp.addEventListener('change', () => { const fs = [...inp.files]; inp.value = ''; if (fs.length) this.load(fs); });
    }
    this.el.addEventListener('click', e => this.click(e));
    this.el.addEventListener('keydown', e => {   // in the editor: ctrl+Enter applies, Esc cancels
      const ta = e.target.closest && e.target.closest('textarea.src'); if (!ta) return;
      const li = ta.closest('li[data-a]');
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.applyEdit(li.dataset.a); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); this.editing = null; this.editText = this.editErr = null; this.render(); }
    });
    this.el.addEventListener('dragstart', e => this.dragStart(e));
    this.el.addEventListener('mousedown', e => {   // on a property or an instance path the mouse selects text: the line does not drag meanwhile
      const li = e.target.closest && e.target.closest('b.sp, code.at') && e.target.closest('li[data-a]'); if (!li) return;
      li.draggable = false; G.addEventListener('mouseup', () => { li.draggable = true; }, { once: true });
    });
    this.el.addEventListener('dragend', () => this.dragEnd());
    // every module row takes the drop (one without the signals answers "cannot bind: …"), so the user always hears why
    v.listen('names', 'dragover', e => { const t = this.dropTarget(e); if (t) { e.preventDefault(); e.dataTransfer.dropEffect = 'link'; this.hover(t); } });
    v.listen('names', 'dragleave', e => { if (!v.rowAt(e.relatedTarget)) this.hover(null); });
    v.listen('names', 'drop', e => { const t = this.dropTarget(e); if (!t) return; e.preventDefault(); this.dragEnd(); this.drop(t); });
    v.root.addEventListener('wavelens:settings', () => this.sync());   // sortIgnore prefixes: the names resolve again
    if (v.extraJSON) v.extraJSON.push(() => this.bindings.length ? `"bind": [\n${this.bindJSON().map(x => '  ' + JSON.stringify(x)).join(',\n')}\n]` : null);
    if (v.extraState) v.extraState.push({ key: 'sva', get: () => this.snapshot(), set: s => this.restore(s) });
    // on the waves: the rows of the bindings, f / F through the failures, Esc unselects
    this.selA = null; this.dirty = true; this.at = new Map(); this.sumN = 0;
    this.el.addEventListener('change', e => { if (e.target.matches('select[data-sv=ffilter]')) { this.failFilter = e.target.value;
      this.fillSummary(this.el.querySelector('.svr'), 'fails'); } });
    if (v.extraRows) v.extraRows.push(g => this.rowsFor(g));
    v.addKey(']f', () => this.step(1), ']f [f next / previous assertion failure').addKey('[f', () => this.step(-1));
    v.addKey(']a', () => this.stepAssert(1), ']a [a next / previous assertion').addKey('[a', () => this.stepAssert(-1));
    v.root.addEventListener('wavelens:reset', () => this.unselect(false));
    v.root.addEventListener('wavelens:destroy', () => { LIB.panels.delete(this); this.el.remove(); v.sva = null; }, { once: true });
    // this browser's bindings, with the page's that are new since (the ones the user unbound stay away)
    this.saved = store.get(this.key) || {};
    this.hidden = new Set(this.saved.hidden || []);
    this.removed = new Set(this.saved.removed || []);
    const page = pageBinds(v.M);
    const list = (this.saved.bind || []).slice();
    for (const p of page) if (!this.removed.has(bkey(p)) && !list.some(b => bkey(b) === bkey(p))) list.push(p);
    for (const b of list) {
      const pb = page.find(p => bkey(p) === bkey(b));
      this.bindings.push({ assert: b.assert, scope: b.scope, results: pb && pb.results ? pb.results : null, page: !!pb, fromPage: !!(pb && pb.results),
        ...(pb && pb.error ? { error: pb.error } : {}) });
    }
    LIB.panels.add(this);
  }
  // bindings, removed ones, hidden assertions, and the results evaluated here when they are small (with the files they
  // came from: other files, no results)
  save() {
    const results = {};
    for (const b of this.bindings) if (b.results && !b.page) results[bkey(b)] = b.results;
    const rec = { bind: this.bindJSON(), removed: [...this.removed], hidden: [...this.hidden], src: LIB.src, results };
    if (Object.keys(results).length) rec.wave = this.wave();
    if (JSON.stringify(results).length > 200000) delete rec.results;
    if (!store.set(this.key, rec)) this.toast('not kept in this browser: its storage is full or off');
    this.saved = rec;
  }
  bindJSON() { return this.bindings.map(b => ({ assert: b.assert, scope: b.scope })); }
  // the viewer's saved state (Save / Load…): this browser's files (loaded, edited, read from the disk: their text), the
  // bindings and the assertions taken off the list. Loading replaces the bindings; the page's come back with their results
  snapshot() {
    const s = { files: LIB.files.filter(f => f.origin === 'local').map(({ name, source }) => ({ name, source })), bind: this.bindJSON(),
      hidden: [...this.hidden] };
    // what the panel shows: its table and failure list, the selected attempt (its binding and number)
    s.view = { table: !!this.showTable, fails: !!this.showFails, ...(this.selA ? { sel: { assert: this.selA.b.assert, scope: this.selA.b.scope || '',
      i: this.selA.i } } : {}) };
    return s;
  }
  async restore(s) {
    const files = (s.files || []).filter(f => f && f.name && typeof f.source === 'string' && !active().some(x => x.name === f.name && x.source === f.source));
    if (files.length) await SVA.loadFiles(files.map(f => ({ name: f.name, text: f.source }))); else await LIB.parsing;
    if (s.bind !== undefined || s.hidden !== undefined) {
      const list = (s.bind || []).filter(b => b && b.assert).map(b => ({ assert: b.assert, scope: b.scope || '' })), want = new Set(list.map(bkey));
      const old = this.bindings, page = pageBinds(this.v.M);
      for (const b of old) if (!want.has(bkey(b))) { this.dropSel(b); if (b.page) this.removed.add(bkey(b)); }
      this.bindings = list.map(x => {
        const b = old.find(o => bkey(o) === bkey(x)); if (b) return b;
        const pb = page.find(p => bkey(p) === bkey(x)); this.removed.delete(bkey(x));
        return { assert: x.assert, scope: x.scope, results: pb && pb.results ? pb.results : null, page: !!pb, fromPage: !!(pb && pb.results),
          ...(pb && pb.error ? { error: pb.error } : {}) };
      });
      if (s.hidden !== undefined) this.hidden = new Set(s.hidden || []);
      old.filter(b => !this.bindings.includes(b)).forEach(b => this.changed(b, false));
      this.save(); this.sync(); await this.queue;
    }
    if (s.view) {
      this.showTable = !!s.view.table; this.showFails = !!s.view.fails; this.render();
      const w = s.view.sel, b = w && this.bindings.find(x => x.assert === w.assert && (x.scope || '') === w.scope);
      if (b && b.results) this.select(b, w.i);
    }
  }
  toast(m) { this.v.toast(m); }
  // after the files or the settings changed: resolve the bindings again, take kept results, evaluate the others
  wave() { return this.waveMemo || (this.waveMemo = waveId(this.v.M)); }   // the model of a viewer does not change: once
  sync() {
    for (const b of this.bindings) {
      // results of another text of the assertion (an edit, a reload; the page's results of a file this browser replaced): gone
      const x = LIB.byLabel.get(b.assert), sig = x ? asig(x.a) : null;
      if (b.results && ((b.asig !== undefined && b.asig !== sig) || (b.fromPage && x && changedHere(x.a, x.file)))) { b.results = null; b.fromPage = false;
        this.dropSel(b); }
      b.asig = sig;
      this.check(b);
      const kept = this.saved.results && this.saved.src === LIB.src && this.saved.wave === this.wave() && this.saved.results[bkey(b)];
      if (b.state === 'bound' && ((outcome(b) || {}).missing || []).length) b.results = null;   // the build did not find a name the page does: evaluated here
      if (!b.results && b.state === 'bound' && kept && !(outcome({ results: kept }).missing || []).length) b.results = kept;
    }
    this.render(); this.redraw();
    this.evaluateMany(this.bindings.filter(b => b.state === 'bound' && !b.results && !b.error && !b.running));
  }
  check(b) {
    const x = LIB.byLabel.get(b.assert);
    b.res = x ? resolve(this.v, x.a, b.scope) : null;
    const o = outcome(b);
    b.state = !x ? 'unknown' : b.res.ok ? 'bound' : o && !(o.missing || []).length ? 'dump' : 'cannot';
    b.group = scopeInfo(this.v.M).group(b.scope);   // where its rows go (null: the top of the diagram)
  }
  bind(label, scope) {
    if (this.bindings.some(b => b.assert === label && b.scope === scope)) { this.toast(`${label} is already bound to ${scope || '(top)'}`); return null; }
    const b = { assert: label, scope, results: null };
    this.removed.delete(bkey(b));
    this.bindings.push(b); this.check(b); this.save(); this.render();
    if (b.state === 'bound') this.evaluate(b);
    return b;
  }
  unbind(b) {
    this.bindings = this.bindings.filter(x => x !== b);
    this.dropSel(b);
    if (b.page) this.removed.add(bkey(b));
    this.save(); this.render(); this.changed(b);
  }
  evaluate(b) { return this.evaluateMany([b]); }
  // the bindings of each scope in one evaluation; the lines show the progress; queued after the running ones
  evaluateMany(bs) {
    if (!bs.length) return this.queue || Promise.resolve();
    for (const b of bs) { b.error = null; b.workerError = null; b.running = true; b.msg = 'evaluating…'; }
    bs.forEach(b => this.renderB(b));
    const byScope = new Map();
    for (const b of bs) { if (!byScope.has(b.scope)) byScope.set(b.scope, []); byScope.get(b.scope).push(b); }
    const go = async () => {
      for (const group of byScope.values()) {
        const live = group.filter(b => this.bindings.includes(b));
        live.forEach(b => this.check(b));
        const ok = live.filter(b => b.state === 'bound');
        live.filter(b => b.state !== 'bound').forEach(b => { b.running = false; b.msg = null; this.renderB(b); });
        if (!ok.length) continue;
        try {
          await evaluateScope(this.v, ok, (i, n, p) => {
            const w = p.edges ? p.edges.length * p.n : 0;
            for (const b of ok) { b.msg = (n > 1 ? `evaluating ${i + 1} / ${n}` : 'evaluating') + (useWorker(w) ? ` (${p.edges.length} cycles, in a worker)…` :
              '…'); this.renderB(b); }
          });
        } catch (err) { ok.forEach(b => { b.error = err.message; }); }
        for (const b of ok) { b.running = false; b.msg = null; b.fromPage = false; this.dropSel(b); this.renderB(b); this.changed(b, false); }
        this.redraw();
        if (ok.length === 1 && outcome(ok[0])) this.toast(`${ok[0].assert}: ${plainCounts(outcome(ok[0]))}`);
      }
      this.save();
    };
    this.queue = (this.queue || Promise.resolve()).then(go);
    return this.queue;
  }
  // a binding came, went or has new results: wavelens:sva, and the rows on the waves again (redraw: false = the caller does)
  changed(b, redraw = true) {
    if (this.selA && !this.bindings.includes(this.selA.b)) this.dropSel();
    this.v.root.dispatchEvent(new CustomEvent('wavelens:sva', { detail: b }));
    if (redraw) this.redraw();
  }
  redraw() { this.dirty = true; this.v.renderNames(); this.v.draw(); this.jumps(); this.summary(); }
  // the rows under group g (null: the top) for view.extraRows; built again after a change
  rowsFor(g) {
    if (this.dirty) this.place();
    return this.at.get(g ? g.id : -1) || [];
  }
  drawn() { const ok = shown(this.v.S); return this.bindings.filter(b => outcome(b) && (b.state === 'bound' || b.state === 'dump') && ok(b.assert)); }
  place() {
    this.dirty = false; this.at = new Map();
    const v = this.v, S = v.S, list = this.drawn(), n = new Map();
    for (const b of list) { const k = b.group ? b.group.id : -1; n.set(k, (n.get(k) || 0) + 1); }
    for (const b of list) {
      const g = b.group, k = g ? g.id : -1, st = b.draw || (b.draw = {}), first = !st.gid;
      const copies = S.svaSignals === false || !b.res ? [] : [...new Set(Object.values(b.res.map))];
      const rows = assertionRows(st, b.results, { S, label: b.assert, scope: b.scope, copies, map: b.res ? b.res.map : rowsOf(v.M, outcome(b)), view: v,
        base: { anc: g ? g.anc.concat(g.id) : [], depth: g ? g.depth + 1 : 0 },
        sel: () => (this.selA && this.selA.b === b ? this.selA.i : -1), pick: i => this.select(b, i), only: b.only || null });
      // many at one place: the passing ones folded
      if (first && n.get(k) > 3 && !(outcome(b).stats.fail > 0 && outcome(b).kind !== 'cover')) v.fold(st.gid, true, true);
      if (!this.at.has(k)) this.at.set(k, []);
      this.at.get(k).push(...rows);
    }
  }
  // every failing attempt of the drawn bindings, by time: [{b, i, t}]
  failures() {
    const out = [];
    for (const b of this.drawn()) {
      const o = outcome(b); if (o.kind === 'cover') continue;
      const T = o.cycles || b.results.cycles;
      o.attempts.forEach((a, i) => { if (a.result === 'fail') out.push({ b, i, t: T[a.start], a }); });
    }
    return out.sort((x, y) => x.t - y.t || this.bindings.indexOf(x.b) - this.bindings.indexOf(y.b));
  }
  // f / F: the next / previous failure from the selected one (or from the cursor), round the end
  // the attempt of b to go to from attempt `from` on (round the end): a failure when it has failures, else one that is
  // not vacuous (a cover: a match) -> index | -1
  attemptOf(b, from = 0, dir = 1) {
    const o = outcome(b); if (!o || !o.attempts.length) return -1;
    const fails = o.kind !== 'cover' && o.stats.fail > 0, want = a => (fails ? a.result === 'fail' : a.result !== 'vacuous'), n = o.attempts.length;
    for (let k = 0; k < n; k++) { const i = ((from + dir * k) % n + n) % n; if (want(o.attempts[i])) return i; }
    return -1;
  }
  // a click on an assertion's line (or one of its bindings): its group on the waves with an attempt in the middle of the
  // window; clicked again, the next such attempt
  reveal(b) {
    const v = this.v;
    if (!outcome(b) || !this.drawn().includes(b)) {
      this.toast(`${b.assert}: ${b.state === 'cannot' ? 'cannot bind here' : b.running ? 'evaluating…' : 'not drawn in this view'}`); return; }
    if (!this.inView(b)) { this.outOfView(b); return; }
    const i = this.attemptOf(b, this.selA && this.selA.b === b ? this.selA.i + 1 : 0);
    if (i >= 0) { this.select(b, i); return; }
    // nothing but vacuous attempts: the group, the time as it is
    const st = b.draw; if (st && st.g) [...st.g.anc, st.g.id].forEach(id => v.fold(id, false, true));
    this.dropSel(); this.dirty = true; v.renderNames(); v.draw(); this.mark(b);
    if (st && st.g) v.centerRow(st.g);
    this.toast(`${b.assert}: only vacuous attempts`);
  }
  // a A: the next / previous drawn binding, in the panel's order
  stepAssert(dir) {
    const bs = this.drawn(); if (!bs.length) { this.toast('no assertion on the waves'); return; }
    const k = this.selA ? bs.indexOf(this.selA.b) : this.cur ? bs.indexOf(this.cur) : -1;
    const b = bs[k < 0 ? (dir > 0 ? 0 : bs.length - 1) : (k + dir + bs.length) % bs.length];
    if (this.selA && this.selA.b === b) this.selA = null;
    this.reveal(b);
  }
  // the panel's line of the binding the waves show (and kept in sight in the list)
  mark(b) {
    this.cur = b;
    for (const e of this.el.querySelectorAll('.here')) e.classList.remove('here');
    const el = this.el.querySelector(`ol.asv [data-b="${this.bindings.indexOf(b)}"]`), li = el && (el.closest('ul.bnd') ? el : el.closest('li[data-a]'));
    if (!li) return;
    li.classList.add('here');
    const ol = li.closest('ol.asv'), r = li.getBoundingClientRect(), q = ol.getBoundingClientRect();
    if (r.top < q.top || r.bottom > q.bottom) ol.scrollTop += r.top - q.top - ol.clientHeight / 3;
  }
  // whether the group of b is in the view: its module not hidden, not left out by Only (folded away it is)
  inView(b) { const g = b.draw && b.draw.g, v = this.v; return !g || !v.shown || v.shown(g); }
  outOfView(b) { const v = this.v;
    this.toast(`${b.assert}: its module is out of the view (${v.onlyOn && v.onlyOn() ? 'Only ‖ in the bar pauses it' : 'Hidden ✕ in the bar'})`); }
  step(dir) {   // the failures of the assertions in the view
    const all = this.failures(), fs = all.filter(f => this.inView(f.b)), v = this.v;
    if (!fs.length) { this.toast(all.length ? `no assertion failure in the view (${all.length} out of it)` : 'no assertion failure'); return; }
    let k = this.selA ? fs.findIndex(f => f.b === this.selA.b && f.i === this.selA.i) : -1;
    if (k >= 0) k = (k + dir + fs.length) % fs.length;
    else k = U.stepTo(fs.map(f => f.t), v.cursor, dir);
    this.select(fs[k].b, fs[k].i);
  }
  // select attempt i of binding b: the cursor at its start, the view around it, its rows open and in front, the bound
  // signals highlighted; the panel's line says which one
  select(b, i) {
    const o = outcome(b), a = o && o.attempts[i], v = this.v; if (!a) return;
    if (!this.inView(b)) { this.outOfView(b); return; }   // the list's attempts too
    const prev = this.selA && this.selA.b; this.selA = { b, i };
    const T = o.cycles || b.results.cycles, ts = T[a.start], te = T[Math.max(a.end, a.failed_at ?? a.end)] ?? ts;
    const per = T.length > 1 ? (T[T.length - 1] - T[0]) / (T.length - 1) : (v.M.t1 - v.M.t0) / 20;
    // the zoom stays: the attempt (its bar reaches half a cycle past its edges) in the middle of the window, or its start
    // near the left edge when it is longer than the window
    const w = te - ts + per;
    const st = b.draw;
    if (st && st.g) [...st.g.anc, st.g.id].forEach(id => v.fold(id, false, true));
    v.moveTo(ts, { left: w <= v.span ? ts - per / 2 - (v.span - w) / 2 : ts - per / 2 - v.span * 0.1 });
    v.extraPicks = new Map([...Object.values((b.res && b.res.map) || {}), ...(st && st.g ? [st.g] : [])].map(r => [r, 'hl8']));   // the group covers its rows
    this.dirty = true; v.renderNames(); v.draw();
    if (st && st.lane) v.centerRow(st.lane);   // the attempts lane in the middle of the waves
    if (prev && prev !== b) this.renderB(prev);
    this.renderB(b);
    this.mark(b);
    this.toast(`${b.assert}: ${a.result} at ${v.fmt(ts, v.span / 1000, v.span)}${a.note ? ' — ' + a.note : ''}`);
    this.explain();
    v.root.dispatchEvent(new CustomEvent('wavelens:sva-select', { detail: { binding: b, attempt: a } }));
  }
  // Why: the selected attempt's booleans taken apart (the engine's explain), one column per cycle of the attempt; a
  // cell where a step matched is ringed, the one where it failed red; a cycle's header puts the cursor there
  async explain() {
    const sel = this.selA, key = sel ? `${resultsId(sel.b.results)}:${bkey(sel.b)}:${sel.i}` : '';
    if (key === this.whyKey) return;
    this.whyKey = key;
    if (!sel) { this.why = ''; this.fillWhy(); return; }
    const { b, i } = sel, o = outcome(b), a = o.attempts[i], x = LIB.byLabel.get(b.assert), v = this.v;
    const head =
      (`<div class="wh"><b>Why</b> · ${esc(b.assert)} · attempt ${i + 1}: <span ` +
        `class="c-${a.result}">${esc(a.result)}</span>${a.note ? ' — ' + esc(a.note) : ''}<button type="button" class="ic" data-sv="nowhy" ` +
        `aria-label="close" title="Close (Esc on the waves)">✕</button></div>`);
    const say = m => { if (this.whyKey === key) { this.why = head + `<p class="muted">${esc(m)}</p>`; this.fillWhy(); } };
    if (!x || !b.res || !b.res.ok) { say('the signals of this binding are not in this view: nothing to take apart'); return; }
    try {
      const p = plan(SOURCES(), [x.a], rowSampler(b.res.map), v.M.timed ? 'ps' : 'cycles')[0], E = p.edges || [], T = o.cycles || b.results.cycles;
      const last = Math.max(a.end, a.failed_at ?? a.end), t0 = T[a.start], from = E.indexOf(t0);
      if (from < 0) { say('this attempt is outside the waves of this view'); return; }
      const n = Math.min(last - a.start + 1, Panel.WHY_CYCLES), to = from + n - 1;
      const req = { files: p.req.files, trace: p.req.trace, explain: { assert: x.a.label, from, to } };
      const out = (await SVA.engine()).call(req);
      if (this.whyKey !== key) return;
      if (out.errors) { say(out.errors.map(e => e.msg).join('; ')); return; }
      const num = new Map((o.steps || []).map((s, k) => [s.id, [k + 1, s.role]])), hit = new Set((a.trace || []).map(([id, c]) => `${id}@${c}`));
      const miss = a.result === 'fail' && a.reason ? `${a.reason.step}@${a.failed_at ?? a.end}` : '';
      const cell = (val, w, id, c) => {
        const t = w === 1 ? (val === 1 ? 't' : val === 0 ? 'f' : 'x') : (typeof val === 'number' || /^h/.test(val) ? 'n' : 'x');
        const txt = w === 1 ? String(val) : typeof val === 'number' ? (val < 10 ? String(val) : '0x' + val.toString(16)) : /^h/.test(val) ? '0x' +
          val.slice(1) : val;
        const k = id ? `${id}@${c}` : '';
        return `<td class="${t}${k && hit.has(k) ? ' hit' : ''}${k && k === miss ? ' miss' : ''}"
          title="${esc(String(txt))}">${esc(cut(String(txt), 10))}</td>`;
      };
      const rows = [];
      const walk = (nd, depth, top) => {
        const lab = top ? `${top.id && num.has(top.id) ? num.get(top.id)[0] + '. ' : ''}${nd.text}` : nd.text;
        const role = top ? (top.id && num.has(top.id) ? num.get(top.id)[1] : top.what) : '';
        rows.push((`<tr class="${top ? 'top' : ''}"><th scope="row" style="padding-left:${0.4 + depth * 1.1}em" ` +
            `title="${esc(nd.text)}">${esc(cut(lab, 60))}${role ? ` <span
              class="muted">${esc(role)}</span>` : ''}</th>${nd.values.map((val, k) => cell(val, nd.w, top && top.id, a.start + k)).join('')}</tr>`));
        for (const kid of nd.kids || []) walk(kid, depth + 1, null);
      };
      for (const bl of out.explain) walk(bl.tree, 0, bl);
      const cols = Array.from({ length: n }, (_, k) =>
        (`<th scope="col"><button type="button" data-sv="wt" data-t="${E[from + k]}" title="${esc(v.when(E[from + k]))}: the cursor ` +
          `there">${a.start + k}</button></th>`)).join('');
      this.why = head +
        (`<div class="ww"><table class="svw-t"><thead><tr><th scope="col" ` +
          `class="muted">cycle</th>${cols}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`) +
        (last - a.start + 1 > n ? `<p class="muted">the first ${n} of ${last - a.start + 1} cycles</p>` : '');
      this.fillWhy();
    } catch (err) { say(err.message); }
  }
  fillWhy() { const el = this.el.querySelector('.svw'); if (el) { el.innerHTML = this.why || ''; el.hidden = !this.why; } }
  // the selection is gone with its binding (b: only if it is b's): no attempt, no highlighted rows; the caller redraws
  dropSel(b) {
    if (!this.selA || (b && this.selA.b !== b)) return;
    this.selA = null; this.v.extraPicks = new Map(); this.explain();
  }
  unselect(redraw = true) {
    const b = this.selA && this.selA.b; if (!b) return;
    this.selA = null; this.renderB(b); this.explain();
    if (redraw) { this.v.extraPicks = new Map(); this.v.renderNames(); this.v.draw(); }
  }
  firstFail(b) {
    const o = outcome(b), i = o ? o.attempts.findIndex(x => x.result === 'fail') : -1;
    if (i < 0) { this.toast('no failure'); return; }
    this.select(b, i);
  }
  // at most six failures: jump buttons in the bar's "go to" group
  jumps() {
    let el = this.jumpEl;
    const fs = this.failures(), show = fs.length > 0 && fs.length <= 6;
    // a "go to" of its own goes too
    if (!show) { if (el) { const g = el.parentElement; el.remove(); this.jumpEl = null; if (g && g.children.length === 1) g.remove(); } return; }
    if (!el) {
      el = this.jumpEl = document.createElement('span'); el.className = 'svj';
      this.v.addTool('go to', el);
      el.addEventListener('click', e => { const btn = e.target.closest('button[data-svj]'); if (!btn) return; const f = this.failures()[+btn.dataset.svj];
        if (f) this.select(f.b, f.i); });
    }
    el.innerHTML = fs.map((f, k) =>
      (`<button type="button" class="fail" data-svj="${k}" title="${esc(`${f.b.assert}: ${f.a.note || 'fail'} (cycle ${f.a.start})`)}">✕ ${esc(f.b.assert)} ` +
        `${esc(this.v.fmt(f.t, (this.v.M.t1 - this.v.M.t0) / 1000, this.v.M.t1 - this.v.M.t0))}</button>`)).join('');
  }
  async load(files) {
    this.toast('parsing…');
    try { await SVA.loadFiles(files); } catch (err) { this.toast('cannot load: ' + err.message); return; }
    if (LIB.loadError) { this.open = true; this.render(); this.toast(LIB.loadError); return; }
    if (!store.get(FILES_KEY) && LIB.files.some(f => f.origin === 'local')) this.toast('loaded, but not kept in this browser: its storage is full or off');
    const n = files.map(f => { const lf = LIB.files.find(x => x.origin === 'local' && x.name === f.name); return lf &&
      lf.parsed ? (lf.parsed.assertions || []).length : 0; }).reduce((a, b) => a + b, 0);
    this.open = true; this.render(); this.toast(`${files.map(f => f.name).join(', ')}: ${n} assertion${n === 1 ? '' : 's'}`);
  }
  label(S) { return S || '(top)'; }
  // a binding's two cells: where (the instance path, on the assertion's first line) and how it went (status, counts, the
  // selected attempt; on the second line)
  state(b) {
    const sc = esc(this.label(b.scope)), path = sc.replace(/\./g, '.<wbr>'), o = outcome(b);
    const how = [...((b.res && b.res.notes) || []), ...((b.res && b.res.errors) || [])];
    if (b.workerError) how.push(`the worker failed (${b.workerError}): evaluated in the page`);
    const info = how.length ?
      ` <button type="button" class="how" data-sv="how" aria-label="how ${esc(b.assert)} was bound" title="${esc(how.join('\n'))}">ⓘ</button>` : '';
    const two = (cls, tip, msg, cn) => `<span class="st bp ${cls}" title="${esc(tip)}"><b class="sp">${path}</b>${info}</span>` +
      (`<span ` +
          `class="bs">${msg ? `<span class="st ${cls}">${msg}</span>` : ''}${cn && o ? `<span
            class="cn">${counts(o, b.only || null)}</span>` : ''}${cn ? this.selHTML(b) : ''}</span>`);
    if (b.running) return two('run', 'bound to ' + this.label(b.scope), esc(b.msg || 'evaluating…'));
    if (b.error) return two('no', 'bound to ' + this.label(b.scope), esc(b.error));
    if (b.state === 'cannot') return two('no', 'cannot bind to ' + this.label(b.scope),
      `cannot bind: ${esc([...(b.res.missing.length ? ['missing ' + b.res.missing.join(', ')] : []), ...b.res.errors].join('; '))}`);
    if (b.state === 'dump') {
      const not = [...b.res.missing, ...b.res.errors].join(', ');
      return two('dump', 'bound to ' + this.label(b.scope) + '; results of sva eval at build time; this view does not show ' + not,
        `from the dump, not in this view: ${esc(not)}`, true);
    }
    return two('ok', 'bound to ' + this.label(b.scope), '', true);
  }
  selHTML(b) {
    const a = this.selA && this.selA.b === b && outcome(b) && outcome(b).attempts[this.selA.i];
    const T = a && (outcome(b).cycles || b.results.cycles);
    return a ?
      (`<span class="sel">attempt ${this.selA.i + 1}: ${esc(a.result)}, ${esc(this.v.when(T[a.start]))} ` +
        `(cycle${a.start === a.end ? ' ' + a.start : `s ${a.start}–${a.end}`})</span>`) : '';
  }
  // the attempts of a count the user clicked (b.only), each a link to it on the waves
  onlyHTML(b) {
    const o = outcome(b); if (!o || !b.only) return '';
    const T = o.cycles || b.results.cycles, v = this.v, list = o.attempts.map((a, i) => [a, i]).filter(([a]) => a.result === b.only), max = 200;
    return (`<ol ` +
        `class="atl">${list.slice(0, max).map(([a, i]) => `<li><button type="button" data-sv="go"
          data-i="${i}">#${i + 1}` +
            `</button> cycle${a.start === a.end ? ' ' + a.start : `s ${a.start}–${a.end}`}` +
            ` · ${esc(v.when(T[a.start]))}${a.note ? ' — ' + esc(a.note) : ''}</li>`).join('')}` +
            `${list.length > max ? `<li class="muted">… ${list.length - max} more</li>` : ''}</ol>`);
  }
  bindHTML(b) {
    const o = outcome(b);
    return (`${this.state(b)}<span class="bb"><button type="button" data-sv="eval"${b.state === 'bound' && !b.running ? '' : ' disabled'} title="Run the ` +
        `assertion again over the waves of this view">Evaluate</button><button type="button" ` +
        `data-sv="fail"${o && o.stats.fail && o.kind !== 'cover' ? '' : ' disabled'} title="Show the first failing attempt">Go to first ` +
        `failure</button><button type="button" data-sv="unbind" title="Remove this binding">Unbind</button></span>${this.onlyHTML(b)}`);
  }
  // ✎: the editor of an assertion under its line: its statement, Apply / Cancel / Revert, what went wrong
  editHTML(a, file) {
    const st = this.editText != null ? this.editText : (SVA.statement(a.label) || {}).text || '';
    return `<div class="sve"><textarea class="src" spellcheck="false" rows="${Math.min(14, st.split('\n').length + 1)}"
      aria-label="the statement of ${esc(a.label)}">${esc(st)}</textarea>
      <span class="eb"><button type="button" data-sv="apply"
        title="Parse it and evaluate its bindings again (ctrl+Enter); kept in this browser">Apply</button><button type="button"
          data-sv="noedit">Cancel</button>${file.shadows ? `<button type="button" data-sv="revert"
            title="Forget this browser's ${esc(file.name)}: the page's file comes back">Revert to the page's</button>` : ''}
      <span class="muted">${esc(file.name)}:${a.line}</span><span class="em" role="alert">${esc(this.editErr || '')}</span></span></div>`;
  }
  async applyEdit(label) {
    const ta = this.el.querySelector(`li[data-a="${CSS.escape(label)}"] textarea.src`); if (!ta) return;
    const text = ta.value; this.toast('parsing…');
    const r = await SVA.edit(label, text), x = LIB.byLabel.get(label);
    if (!r.ok) { this.editText = text; this.editErr = r.errors.join(' · '); this.editing = label; this.render(); this.toast(`not applied: ${r.errors[0]}`);
      return; }
    if (x) x.file.edited = true;
    this.editing = null; this.editText = this.editErr = null; this.render();
    const bs = this.bindings.filter(b => b.assert === label);
    await this.queue;
    this.toast(bs.length ? `${label}: ${bs.map(b => outcome(b) ? plainCounts(outcome(b)) : b.state).join(' · ')}` : `${label}: applied (not bound)`);
  }
  async reloadFile(name) {
    try {
      const r = await SVA.reload(name);
      if (!r.changed) { this.toast(`${name}: no change on the disk`); return; }
      const f = active().find(x => x.name === name); if (f) f.edited = false;
      await this.queue; this.toast(`${name}: read again${r.picked && r.picked !== name ? ` (from ${r.picked})` : ''}, parsed and evaluated`);
    } catch (e) { if (e.name !== 'AbortError') this.toast(`${name}: ${e.message}`); }
  }
  // one binding's line in place (status, counts); the whole list only when it changes
  renderB(b) {
    const el = this.el.querySelector(`ol.asv [data-b="${this.bindings.indexOf(b)}"]`);
    if (el) el.innerHTML = this.bindHTML(b); else this.render();
  }
  render() {
    const list = [...LIB.byLabel.values()].filter(x => !this.hidden.has(x.a.label) && (!x.file.owners || x.file.owners.has(this.v.M.src))), el = this.el;
    const orphans = this.bindings.filter(b => !LIB.byLabel.has(b.assert));
    el.hidden = !list.length && !LIB.notes.length && !orphans.length;
    if (el.hidden) { el.innerHTML = ''; return; }
    const ol = el.querySelector('ol.asv'), keep = ol ? { top: ol.scrollTop, h: ol.style.height } : null;
    // a table, two lines per assertion: #, its name, the instance it is bound to, its buttons; under them its kind and
    // property, the results, the binding's buttons. Several bindings: one line each under it (instance, results, buttons)
    const line = ({ a, file }, k) => {
      const bs = this.bindings.filter(b => b.assert === a.label), sigs = a.signals.map(s => s.name);
      const pick = this.pick === a.label ? this.pickHTML(a) : '';
      return `<li data-a="${esc(a.label)}" draggable="true"
        title="click: go to it on the waves (again: its next attempt) · drag onto a module in the names column to bind it">
        <span class="an"><span class="grip" aria-hidden="true">⠿</span>${k + 1}</span>
        <span class="nm"><b class="al">${esc(a.label)}</b>${changedHere(a, file) ? `<span class="ed"
          title="its text differs from the page's ${esc(file.name)}: this browser's copy (${file.edited ? 'edited here' : 'read from the disk'})` +
            ` replaces the page's file; Revert in the editor (✎) brings the page's back` +
            `">${file.edited ? 'edited' : 'changed'}</span>` : ''}</span>
        <span class="pr"><span class="ak k-${a.kind}">${a.kind}</span><code class="at"
          title="${esc(a.text || '')}\n— ${esc(file.name)}:${a.line}` +
            `\nsignals (the clock first): ${esc(sigs.join(' '))}` +
            `">${propParts(a.text || '').map(t => `<span class="pp">${esc(t)}</span>`).join(' ')}</code></span>
        ${bs.length === 1 ? `<span class="b1" data-b="${this.bindings.indexOf(bs[0])}" aria-live="polite">${this.bindHTML(bs[0])}</span>` : `<span
          class="b1"><span class="st bp">${bs.length ? `${bs.length} bindings ↓` : 'unbound'}</span></span>`}
        <span class="ab"><button type="button" data-sv="bind" title="Bind to an instance: the modules where all its signals are">Bind…</button><button
          type="button" class="ic" data-sv="edit" aria-label="edit ${esc(a.label)}"
            title="Edit this assertion here: Apply parses it and evaluates its bindings again (ctrl+Enter)"${a.at ? '' : ' disabled'}>✎</button><button
              type="button" class="ic" data-sv="reload" aria-label="read ${esc(file.name)} again"
                title="Read ${esc(file.name)}` +
                  ` from the disk again: its assertions are parsed and evaluated again (the first time: pick the file)` +
                  `">⟳</button><button type="button" class="ic" data-sv="del"` +
                  ` aria-label="remove ${esc(a.label)}"` +
                  ` title="Remove this assertion from the list (and its bindings)">✕</button></span>
        ${pick}${this.editing === a.label ? this.editHTML(a, file) : ''}${bs.length > 1 ? `<ul class="bnd">${bs.map(b => `<li
          data-b="${this.bindings.indexOf(b)}" aria-live="polite">${this.bindHTML(b)}</li>`).join('')}</ul>` : ''}</li>`;
    };
    el.innerHTML = `<div class="nh"><button type="button" class="tw" data-sv="tw" aria-expanded="${this.open}"
      aria-label="${this.open ? 'fold' : 'open'} the assertions">${this.open ? '▾' : '▸'} <b>Assertions</b></button><span
        class="muted">${list.length} loaded${this.v.S.svaShow != null ? ` · ${this.drawn().length} shown on the waves` : ''}` +
          ` · click a line to go to it on the waves` +
          ` · drag a line onto a module in the names to bind it, or Bind…` +
          ` · kept in this browser</span>
      <button type="button" data-sv="watch" aria-pressed="${!!LIB.watching}"
        title="Watch the files read with ⟳: when one changes on the disk it is read, parsed and evaluated again` +
          ` (every second)${G.showOpenFilePicker ? '' : '; this browser cannot keep a file to watch'}` +
          `"${G.showOpenFilePicker ? '' : ' disabled'}` +
          `>Watch${LIB.watching && HANDLES.size ? ` (${HANDLES.size})` : ''}</button>
      <button type="button" data-sv="json" title="The bindings (and files) for the config file">JSON</button><button type="button" data-sv="clear"
        title="Forget this browser's files and bindings for this page (every viewer of it); the page's own come back">Clear</button>
      <span class="svx"><button type="button" data-sv="table" aria-pressed="${!!this.showTable}"
        title="One row per binding: counts, first and last failure, longest attempt, antecedent → consequent latency">Table</button><button type="button"
          data-sv="fails" aria-pressed="${!!this.showFails}" title="Every failed attempt by time; a row selects it on the waves">Failures</button><button
            type="button" data-sv="xmd" title="Download the report of this view's bindings as Markdown (the tables)">report.md</button><button type="button"
              data-sv="xjson" title="Download the results of this view's bindings with the page's meta` +
                ` (sva report reads it)">report.json</button></span></div>` +
      (this.open ? `<div class="svr" aria-live="polite"></div><div class="svw"${this.why ? '' : ' hidden'}>${this.why || ''}</div>` + (LIB.notes.length ?
        `<ul class="svn">${LIB.notes.map(n => `<li class="${n.err ? 'err' : 'warn'}">${esc(n.text)}</li>`).join('')}</ul>` : '') +
      (`<ol class="asv"><li class="hd" aria-hidden="true"><span>#</span><span>Assertion · property</span><span>Bound to · ` +
          `results</span><span></span></li>${list.map(line).join('')}</ol>`) +
      (orphans.length ?
        (`<ul ` +
          `class="svn">${orphans.map(b => `<li
            class="warn">bind: no assertion '${esc(b.assert)}' is loaded (${esc(this.label(b.scope))})</li>`).join('')}</ul>`) : '') +
      `<textarea class="json" readonly${this.jsonOpen ? '' : ' hidden'} aria-label="assertion bindings as JSON"></textarea>` : '');
    const nol = el.querySelector('ol.asv');
    if (nol && keep) { nol.style.height = keep.h; nol.scrollTop = keep.top; }
    if (this.jsonOpen) this.fillJSON();
    if (this.cur && this.bindings.includes(this.cur)) this.mark(this.cur);
    this.fillSummary(el.querySelector('.svr'));   // the last numbers until the new ones come
    this.summary();
  }
  // the report of this view's bindings (summary.rs through the engine): {meta, results} and the bindings in that order
  reportInput() {
    const bs = this.bindings.filter(b => outcome(b)), M = this.v.M;
    const meta = { title: `Assertions · ${this.v.opts.title || M.title || document.title || 'waveform'}`, dump: (M.src.meta && M.src.meta.waves) || '',
      page: G.location ? G.location.pathname.split('/').pop() : '',
      tool: `wavelens sva.js ${(G.WaveLens && G.WaveLens.version) || ''}`, date: localDate() };
    return { bs, input: { meta, results: bs.map(b => b.results) } };
  }
  async report(format) {
    const { bs, input } = this.reportInput(), e = await SVA.engine();
    return Object.assign(e.call({ report: input, format }), { bs, input });
  }
  // totals, the table and the failure list (in place, after the list or the results changed)
  // once per task however many changes asked for it, and only when the results changed (resultsKey)
  summary() {
    if (this.sumQ) return;
    this.sumQ = true;
    queueMicrotask(() => {
      this.sumQ = false;
      const el = this.el.querySelector('.svr'); if (!el) return;
      const key = this.resultsKey();
      if (this.sum && key === this.sumKey) return;   // render() has filled it from this.sum already
      const n = ++this.sumN;
      this.report().then(r => {
        if (n !== this.sumN || !r.summary) return;
        this.sum = r; this.sumKey = key; this.fillSummary(this.el.querySelector('.svr'));
      }, () => {});
    });
  }
  // what the report depends on: the bindings with results, in order (a results document's identity is its version)
  resultsKey() { return this.bindings.length + ':' + this.bindings.filter(b => outcome(b)).map(b => resultsId(b.results)).join(','); }
  // totals always; the table and the failure list each in a box of its own (which: 'table' | 'fails' refills that one)
  fillSummary(el, which) {
    if (!el) return;
    if (!el.querySelector(':scope > .tot')) { el.innerHTML = '<p class="tot"></p><div class="svx-t"></div><div class="svx-f"></div>'; which = undefined; }
    const r = this.sum, v = this.v, bs = this.bindings;
    const loaded = [...LIB.byLabel.values()].filter(x => !this.hidden.has(x.a.label) && (!x.file.owners || x.file.owners.has(v.M.src))).length;
    const ev = bs.filter(b => outcome(b) && (b.state === 'bound' || b.state === 'dump')).length, cannot = bs.filter(b => b.state === 'cannot').length,
      bad = bs.filter(b => b.error).length;
    const not = [cannot && `${cannot} cannot bind`, bad && `${bad} error${bad === 1 ? '' : 's'}`].filter(Boolean).join(', ');
    let tot = `${loaded} loaded · ${ev} bound${not ? ` (${not})` : ''}`;
    if (v.S.svaShow != null) tot += ` · ${this.drawn().length} shown on the waves (svaShow)`;   // the totals stay over every binding
    const t = r && r.summary.assertions.length ? r.summary.totals : null;
    if (t) tot += (` · <b class="${t.with_failures ? 'c-fail' : ''}">${t.with_failures} with failures</b> · ${t.attempts} attempts: ${t.pass} pass, <span ` +
        `class="c-fail${t.fail ? '' : ' zero'}">${t.fail} fail</span>, ${t.vacuous} ` +
        `vacuous${t.disabled ? `, ${t.disabled} disabled` : ''}` +
          `${t.active ? `, ${t.active} active` : ''}${t.capped ? `, ${t.capped} capped (no verdict)` : ''}` +
          `${t.covers ? ` · ${t.covered} of ${t.covers} covers hit` : ''}`);
    el.querySelector(':scope > .tot').innerHTML = tot;
    const rows = t ? r.summary.assertions : [];
    const bi = k => bs.indexOf(r.bs[k]);
    // the attempt of a failure by its start: one map per binding, made when asked
    const at = new Map(), att = (k, start) => {
      if (!at.has(k)) { const m = new Map(); outcome(r.bs[k]).attempts.forEach((a, i) => { if (a.result === 'fail' && !m.has(a.start)) m.set(a.start, i); });
        at.set(k, m); }
      return at.get(k).get(start) ?? -1;
    };
    if (which !== 'fails') {
      const box = el.querySelector(':scope > .svx-t');
      if (!this.showTable || !rows.length) box.innerHTML = '';
      else {
        const go = (k, e) => e ?
          (`<button type="button" class="lnk" data-sv="go" data-b="${bi(k)}" data-i="${att(k, e.start)}" ` +
            `title="${esc(e.note)}">${esc(e.time_fail || '')}</button>`) : '—';
        const notes = rows.flatMap(a => (a.notes || []).map(n => `<li class="warn"><code>${esc(a.name)}</code> ${esc(this.label(a.scope))}: ${esc(n)}</li>`));
        box.innerHTML =
          (`<div class="twr"><table ` +
            `class="svt"><thead><tr><th>Assertion</th><th>Scope</th><th>Attempts</th><th>Pass</th><th>Fail</th>` +
              `<th>Vacuous</th><th>Disabled</th><th>Active</th><th>Capped</th>` +
              `<th>First failure</th><th>Last failure</th><th>Longest</th>` +
              `<th title="antecedent → consequent, cycles, passing attempts">Latency min / avg / max</th></tr></thead><tbody>`) +
          rows.map((a, k) => {
            const s = a.stats, b = r.bs[k], cover = a.kind === 'cover', num = key => s[key] &&
              key !== 'vacuous' ? `<button type="button" class="cnum${b.only === key ? ' on' : ''}" data-sv="only" data-k="${key}">${s[key]}</button>` :
              String(s[key] ?? 0);
            return (`<tr data-b="${bi(k)}" class="${!cover && s.fail ? 'bad' : ''}"><td><code ` +
                `title="${esc(a.text)}">${esc(a.name)}</code>${cover ? ` <span
                  class="ak k-cover">cover: ${a.covered}</span>` : ''}</td><td>${esc(this.label(a.scope))}</td>` +
                    `<td>${s.attempts}</td><td>${num('pass')}</td><td>${cover ? '—' : num('fail')}</td>` +
                    `<td>${s.vacuous}</td><td>${num('disabled')}</td><td>${num('active')}</td><td>${num('capped')}</td>` +
                    `<td>${go(k, a.first_fail)}</td><td>${go(k, a.last_fail)}</td>` +
                    `<td>${a.longest ? a.longest.cycles : '—'}</td><td>${a.latency ? esc(a.latency.text) : '—'}</td></tr>`);
          }).join('') + `</tbody></table></div>${notes.length ? `<ul class="svn">${notes.join('')}</ul>` : ''}`;
      }
    }
    if (which !== 'table') {
      const box = el.querySelector(':scope > .svx-f');
      if (!this.showFails || !t) { box.innerHTML = ''; return; }
      const fs = r.summary.failures, names = [...new Set(fs.map(f => f.name))], keep = this.failFilter || '';
      const shown = keep ? fs.filter(f => f.name === keep) : fs, max = Panel.MAX_FAILS, list = shown.slice(0, max);
      box.innerHTML = `<div class="svf"><b>Failures</b> <span
        class="muted">${shown.length}${keep ? ` of ${fs.length}` : ''}, by the time they were found · a row selects the attempt</span>
        <select data-sv="ffilter" aria-label="failures of"><option
          value="">every assertion</option>${names.map(n => `<option${n === keep ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select><button
            type="button" data-sv="fcopy" title="The rows as text, one per line (tab-separated)">Copy</button>` +
        (list.length ? `<div class="twr"><table
          class="svt"><thead><tr><th>#</th><th>Assertion</th>` +
            `<th>Scope</th><th>Failed at</th><th>Start</th>` +
            `<th>Reason</th><th>Note</th></tr></thead><tbody>` +
            `${list.map((f, j) =>
          `<tr data-b="${bi(f.row)}"><td>${j + 1}</td><td><button type="button" class="lnk" data-sv="go"
            data-i="${att(f.row, f.start)}">${esc(f.name)}</button></td><td>${esc(this.label(f.scope))}</td><td>${esc(f.time_fail || '')} <span
              class="muted">(cycle ${f.failed_at})</span></td><td>${esc(f.time || '')} <span
                class="muted">(cycle ${f.start})</span></td>` +
                  `<td>${esc(f.kind)}</td><td>${esc(f.note)}</td></tr>`).join('')}` +
                  `</tbody></table></div>` : '<p class="muted">none</p>') +
        (shown.length > max ? `<p class="muted more">… ${shown.length - max} more · narrow the list with the filter, or download report.md / report.json</p>` :
          '') + '</div>';
    }
  }
  failText() {
    const fs = (this.sum ? this.sum.summary.failures : []).filter(f => !this.failFilter || f.name === this.failFilter);
    return ['assertion\tscope\tfailed at\tstart\treason\tnote', ...fs.map(f => [f.name, f.scope || '(top)', `${f.time_fail} (cycle ${f.failed_at})`,
      `${f.time} (cycle ${f.start})`, f.kind, f.note].join('\t'))].join('\n');
  }
  async download(kind) {
    try {
      const r = await this.report(kind === 'md' ? 'md' : undefined);
      const text = kind === 'md' ? r.text : JSON.stringify(r.input, null, 1);
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([text], { type: kind === 'md' ? 'text/markdown' : 'application/json' }));
      a.download = kind === 'md' ? 'report.md' : 'report.json';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      this.toast(`${a.download}: ${r.bs.length} binding${r.bs.length === 1 ? '' : 's'}`);
    } catch (err) { this.toast('no report: ' + err.message); }
  }
  jsonText() {
    const rows = l => l.map(x => '  ' + JSON.stringify(x)).join(',\n'), files = [...new Set(LIB.files.map(f => f.path))];
    return `"sva": ${JSON.stringify(files)},\n"bind": [\n${rows(this.bindJSON())}\n]`;
  }
  fillJSON() { const ta = this.el.querySelector('textarea.json'); if (ta) { ta.value = this.jsonText(); ta.rows = this.bindings.length + 4; } }
  pickHTML(a) {
    const cs = candidates(this.v, a);
    return `<div class="pick">${cs.length ? '<span class="muted">bind to</span>' + cs.map(S => `<button type="button" data-sv="to"
      data-scope="${esc(S)}">${esc(this.label(S))}</button>`).join('')
      : `<span class="no">no instance has ${esc(a.signals.map(s => s.name).join(', '))}</span>`}<button type="button" class="ic" data-sv="nopick"
        aria-label="close" title="Close">✕</button></div>`;
  }
  click(e) {
    const btn = e.target.closest('button[data-sv]');
    if (!btn) {   // a click on an assertion's line, not on its controls: go to it on the waves
      if (e.target.closest('button, input, select, textarea, a, .pick')) return;
      if (e.target.closest('b.sp, code.at') && String(G.getSelection && G.getSelection()).length) return;   // text selected to copy
      const li = e.target.closest('ol.asv li[data-a]'), one = e.target.closest('ul.bnd li[data-b]');
      if (!li) return;
      const b = one ? this.bindings[+one.dataset.b] : this.bindings.find(x => x.assert === li.dataset.a && outcome(x) && this.drawn().includes(x)) ||
        this.bindings.find(x => x.assert === li.dataset.a);
      if (b) this.reveal(b); else this.toast(`${li.dataset.a} is not bound: drag it onto a module, or Bind…`);
      return;
    }
    const act = btn.dataset.sv, li = btn.closest('li[data-a]'), label = li && li.dataset.a, bl = btn.closest('[data-b]'), b = bl &&
      this.bindings[+bl.dataset.b];
    if (act === 'tw') { this.open = !this.open; this.render(); }
    else if (act === 'bind') { this.pick = this.pick === label ? null : label; this.render(); }
    else if (act === 'nopick') { this.pick = null; this.render(); }
    else if (act === 'nowhy') this.unselect();
    else if (act === 'wt') this.v.setCursor(+btn.dataset.t);
    else if (act === 'to') { this.pick = null; this.bind(label, btn.dataset.scope); }
    else if (act === 'del') {
      const gone = this.bindings.filter(x => x.assert === label);
      this.hidden.add(label); this.bindings = this.bindings.filter(x => x.assert !== label);
      gone.filter(x => x.page).forEach(x => this.removed.add(bkey(x)));
      this.save(); this.render(); gone.forEach(x => this.changed(x, false)); this.redraw();
    }
    else if (act === 'edit') { this.editing = this.editing === label ? null : label; this.editText = this.editErr = null; this.render();
      if (this.editing) this.el.querySelector(`li[data-a="${CSS.escape(label)}"] textarea.src`)?.focus(); }
    else if (act === 'noedit') { this.editing = null; this.editText = this.editErr = null; this.render(); }
    else if (act === 'apply') this.applyEdit(label);
    else if (act === 'revert') { const x = LIB.byLabel.get(label); this.editing = null; this.editText = this.editErr = null;
      if (x) SVA.revertFile(x.file.name).then(() => this.toast(`${x.file.name}: the page's file again`)); }
    else if (act === 'reload') { const x = LIB.byLabel.get(label); if (x) this.reloadFile(x.file.name); }
    else if (act === 'watch') { SVA.watch(!LIB.watching); this.toast(LIB.watching ?
      `watching ${HANDLES.size ? [...HANDLES.keys()].join(', ') : 'the files you read with ⟳'}` : 'not watching'); }
    else if (act === 'unbind' && b) this.unbind(b);
    else if (act === 'eval' && b) this.evaluate(b);
    else if (act === 'fail' && b) this.firstFail(b);
    else if (act === 'how' && b) this.toast(btn.title.replace(/\n/g, ' · '));
    else if (act === 'clear') clearAll();
    else if (act === 'table' || act === 'fails') { const k = act === 'table' ? 'showTable' : 'showFails'; this[k] = !this[k];
      btn.setAttribute('aria-pressed', this[k]); this.fillSummary(this.el.querySelector('.svr'), act); if (!this.sum) this.summary(); }
    else if (act === 'only' && b) { b.only = b.only === btn.dataset.k ? null : btn.dataset.k; this.renderB(b); this.redraw();
      this.fillSummary(this.el.querySelector('.svr'), 'table'); }
    else if (act === 'go' && b) this.select(b, +btn.dataset.i);
    else if (act === 'fcopy') { const t = this.failText(); try { navigator.clipboard.writeText(t).then(() => this.toast('failures copied'), () => {});
      } catch (err) { /* no clipboard */ } this.copied = t; }
    else if (act === 'xmd' || act === 'xjson') this.download(act === 'xmd' ? 'md' : 'json');
    else if (act === 'json') {
      this.jsonOpen = !this.jsonOpen;
      const ta = this.el.querySelector('textarea.json');
      ta.hidden = !this.jsonOpen; this.fillJSON();
      if (this.jsonOpen) { ta.select(); try { navigator.clipboard.writeText(ta.value).then(() => this.toast('JSON copied'), () => {});
        } catch (err) { /* select only */ } }
    }
  }
  // drag and drop: an assertion line onto a module row (or a signal row: its module) of the names column
  dragStart(e) {
    if (e.target.closest && e.target.closest('.sve')) return;   // text dragged in the editor
    const li = e.target.closest && e.target.closest('li[data-a]'); if (!li) return;
    const x = LIB.byLabel.get(li.dataset.a); if (!x) return;
    this.drag = { a: x.a, ok: new Map() };
    e.dataTransfer.setData('text/plain', x.a.label); e.dataTransfer.effectAllowed = 'link';
    const I = scopeInfo(this.v.M);
    for (const S of I.scopes) this.drag.ok.set(S, resolve(this.v, x.a, S));
    this.marked = [];
    for (const g of this.v.vis) {
      if (g.type !== 'group') continue;
      const S = I.abs.get(g); if (S == null) continue;
      const r = this.drag.ok.get(S) || resolve(this.v, x.a, S);
      this.v.rowClass(g, r.ok ? 'sva-ok' : 'sva-no').rowTitle(g, r.ok ? `drop: bind ${x.a.label} to ${S}` :
        `cannot bind: ${[...r.missing, ...r.errors].join(', ')}`);
      this.marked.push(g);
    }
    this.v.root.classList.add('sva-drag');
  }
  dragEnd() {
    if (!this.drag) return;
    for (const g of this.marked || []) this.v.rowClass(g, 'sva-ok', false).rowClass(g, 'sva-no', false).rowClass(g, 'sva-over', false).rowTitle(g, null);
    this.marked = null; this.v.root.classList.remove('sva-drag'); this.hoverRow = null;
    setTimeout(() => { this.drag = null; }, 0);
  }
  dropTarget(e) {
    if (!this.drag) return null;
    const r = this.v.rowAt(e.target); if (!r || r.type === 'space') return null;
    const I = scopeInfo(this.v.M);
    const S = r.type === 'group' ? I.abs.get(r) : I.of.get(r);
    if (S == null) return null;
    const res = this.drag.ok.get(S) || resolve(this.v, this.drag.a, S);
    return { row: r, scope: S, ok: res.ok, res };
  }
  hover(t) { if (this.hoverRow) this.v.rowClass(this.hoverRow, 'sva-over', false); this.hoverRow = t && t.row; if (t) this.v.rowClass(t.row, 'sva-over'); }
  drop(t) {
    const a = this.drag ? this.drag.a : null; if (!a) return;
    if (!t.ok) { this.toast(`cannot bind ${a.label} to ${this.label(t.scope)}: ${[...t.res.missing, ...t.res.errors].join(', ')}`); return; }
    if (this.bind(a.label, t.scope)) this.toast(`${a.label} bound to ${this.label(t.scope)}`);
  }
}
// Clear: this browser forgets its files and the bindings of every viewer of the page; the page's own come back
function clearAll() {
  store.set(FILES_KEY, null);
  LIB.files = LIB.files.filter(f => f.origin !== 'local');
  LIB.files.forEach(f => { if (!DATA.files.some(p => p.name === f.name && p.parsed) && !f.owners) f.parsed = null; });
  for (const p of LIB.panels) {
    store.set(p.key, null);
    p.saved = {}; p.hidden.clear(); p.removed.clear();
    const old = p.bindings, page = pageBinds(p.v.M);
    p.bindings = page.map(x => ({ assert: x.assert, scope: x.scope, results: x.results || null, page: true, ...(x.error ? { error: x.error } : {}) }));
    old.forEach(b => p.changed(b, false)); p.redraw();
  }
  reparse();
}
Panel.WHY_CYCLES = 64;   // columns of Why at most (a longer attempt: its first cycles)
Panel.MAX_FAILS = 500;   // rows of the Failures list (the rest: the filter, report.md, report.json)
SVA.panels = () => [...LIB.panels];

/* ---------------- expressions: virtual signals and search (stage 10) ---------------- */
// An expression of the waves ("PSEL && !PREADY", "@(posedge PCLK) $rose(req)") is parsed and valued by the engine
// (`exprs` request): names from the scope it was written in up to the top (a full path too); with a clock it is
// sampled at the clock's edges like an assertion, without one it is valued after every change of its signals.
const CLOCKED = /^\s*@\s*\(\s*(posedge|negedge|edge)?\s*([A-Za-z_][\w$.]*)\s*\)\s*([\s\S]+)$/;
function splitClock(text) {
  const m = CLOCKED.exec(text);
  return m ? { clock: { edge: m[1] || 'posedge', signal: m[2] }, body: m[3].trim() } : { clock: null, body: String(text).trim() };
}
// names in scope S of model M, each from S up to the root, else as a path from the top -> {map: {name: row}, missing, errors}
function resolveUp(M, pfx, names, S) {
  const I = scopeInfo(M), map = {}, missing = [], errors = [];
  for (const n of names) {
    let hit = null;
    for (let s = S; ; s = parent(s)) { hit = lookup(I, s, n, pfx); if (hit || !s || s === I.root) break; }
    hit = hit || lookup(I, I.root, n, pfx) || lookup(I, '', n, pfx);
    if (!hit) missing.push(n);
    else if (hit.many) errors.push(`${n} (ambiguous: ${hit.many.map(r => r.full).join(' or ')})`);
    else map[n] = hit.row;
  }
  return { map, missing, errors };
}
// the value of row r after the changes at each time (the engine's columns: values just before are for a clock)
function atColumn(r, times) {
  const out = new Array(times.length), a = r.tr;
  let k = -1;
  for (let i = 0; i < times.length; i++) { while (k + 1 < a.length && a[k + 1].t <= times[i]) k++; out[i] = rowValue(r, a[k]); }
  return out;
}
// an engine value (a number, "h…", binary digits with x) as a "tv" value of width w
function tvValue(v, w) {
  if (w === 1) return v === 1 || v === '1' ? '1' : v === 0 || v === '0' ? '0' : 'x';
  if (typeof v === 'number') return v.toString(16);
  const s = String(v);
  if (/^h/i.test(s)) return s.slice(1).toLowerCase();
  const b = s.padStart(Math.ceil(s.length / 4) * 4, s[0] === 'x' || s[0] === 'z' ? s[0] : '0');
  let h = '';
  // a nibble all z is z, one with an x or a partial z is x (hexOf of wavelens.js, as GTKWave)
  for (let i = 0; i < b.length; i += 4) { const n = b.slice(i, i + 4); h += /^z{4}$/i.test(n) ? 'z' : /[xz]/i.test(n) ? 'x' : parseInt(n, 2).toString(16); }
  // a nibble of known bits and x / z: "'b" and the w bits, as the readers write it (vcdHex), so no known bit becomes x
  const bw = (s.length >= w ? s.slice(s.length - w) : s.padStart(w, b[0])).toLowerCase(), I = G.WaveLens && G.WaveLens.internal;
  return w > 1 && !/^x+$|^z+$/.test(bw) && I && I.mixedBits(bw) ? "'b" + bw : h;
}
const truthy = v => (typeof v === 'number' ? v !== 0 : /^h/i.test(v) ? /[1-9a-f]/i.test(v) : /1/.test(String(v)));
const MAX_TIMES = 2e6;
// expression {text, scope} of model M -> {text, times, values, width, map} | {err}
async function valueOf(M, pfx, x) {
  const { clock, body } = splitClock(x.text), eng = await SVA.engine(), files = SOURCES();
  const info = eng.call({ files, exprs: [body] });
  const e = info.exprs ? info.exprs[0] : { errors: (info.errors || []).map(r => r.msg) };
  if (e.errors) return { err: e.errors[0] };
  const names = e.signals.map(s => s.name).concat(clock ? [clock.signal] : []);
  const res = resolveUp(M, pfx, names, x.scope || '');
  if (res.missing.length || res.errors.length) return { err: res.errors.concat(res.missing.length ? [`not found: ${res.missing.join(', ')}`] : []).join('; ') };
  const rows = res.map, sm = rowSampler(rows);
  let times, col;
  if (clock) { times = sm.edges(clock.signal, clock.edge) || []; col = n => sm.column(n, times); }
  else {
    const all = new Set([M.t0]);
    for (const s of e.signals) for (const o of rows[s.name].tr) all.add(o.t);
    times = [...all].sort((a, b) => a - b); col = n => atColumn(rows[n], times);
  }
  if (times.length > MAX_TIMES) return { err: `${times.length} changes: give it a clock, @(posedge clk) …` };
  const trace = { cycles: times.length, times: [], signals: {}, widths: {} };
  for (const s of e.signals) { trace.signals[s.name] = col(s.name); const w = rowWidth(rows[s.name]); if (w) trace.widths[s.name] = w; }
  const out = eng.call({ files, exprs: [body], trace }).exprs[0];
  if (out.errors) return { err: out.errors[0] };
  return { text: (clock ? `@(${clock.edge} ${clock.signal}) ` : '') + out.text, times, values: out.values, width: out.width || 1, map: rows };
}
// the times where it becomes true (a match of the search)
function matches(res) {
  const out = [];
  let was = false;
  res.values.forEach((v, i) => { const t = truthy(v); if (t && !was) out.push(res.times[i]); was = t; });
  return out;
}
// a row that draws the values like a signal ("tv")
function fillRow(row, res) {
  const w = res.width, tv = res.values.map((v, i) => [res.times[i], tvValue(v, w)]);
  const r0 = G.WaveLens.parse({ signal: [{ name: row.name, tv, width: w }] }).rows.find(r => r.type === 'sig');
  Object.assign(row, { tr: r0.tr, gaps: r0.gaps, width: r0.width, tv: true });
}
// rows of a list of expressions under one group ("ƒ expressions"); st keeps the row objects between calls
function exprRows(st, list, base = { anc: [], depth: 0 }) {
  if (!list.length) return [];
  const g = st.g || (st.g = { type: 'group', id: G.WaveLens.rowId() });
  Object.assign(g, { name: `ƒ expressions (${list.length})`, full: 'ƒ', path: 'ƒ', anc: base.anc, depth: base.depth, cls: 'sva-xg',
    title: 'Expressions of the waves (a name in the bar: ƒ); click one to put it in the field' });
  st.rows = st.rows || new Map();
  const rows = list.map(x => {
    const r = st.rows.get(x) || { type: 'sig', tr: [], gaps: [], width: 1, x };
    st.rows.set(x, r);
    const err = x.res && x.res.err;
    if (x.res && !err && r.res !== x.res) { fillRow(r, x.res); r.res = x.res; }
    return Object.assign(r, { anc: base.anc.concat(g.id), depth: base.depth + 1, name: `ƒ ${x.text}${err ? '  ⚠ ' + err : ''}`, full: `ƒ ${x.text}`,
      cls: 'sva-expr' + (err ? ' bad' : ''), title:
        `${x.res && x.res.text ? x.res.text : x.text}${x.scope ? '\nnames from ' + x.scope + ' up' : ''}${err ? '\n' + err : ''}` });
  });
  return [g, ...rows];
}
SVA.expressions = { splitClock, valueOf, matches, tvValue };

/* ---------------- expressions in a viewer: the field in the bar, the rows, the search ---------------- */
class Exprs {
  constructor(v) {
    this.v = v; v.svaExprs = this; this.list = []; this.st = {};
    this.key = 'wavelens.sva-exprs:' + (v.storeId || G.location.pathname + ':' + (v.opts.key || v.root.id || v.root.dataset.wave || v.M.title));
    const g = v.addTool('expression', `<input type="text" class="svq" spellcheck="false" placeholder="ƒ  PSEL && !PREADY"
      aria-label="an expression of the signals: Enter finds the next time it becomes true"
      title="An expression of the signals (SystemVerilog, as in an assertion: && || ! == $rose(a) $past(a) a[3:0]` +
        ` pkg::NAME …); @(posedge clk) … samples it at the clock's edges` +
        `.&#10;Names: from the selected signal's module up to the top, or a full path` +
        `.&#10;Enter / shift+Enter: the next / previous time it becomes true.` +
        ` + Row: draw it as a signal (ƒ expressions).">` +
      ('<button type="button" data-x="prev" title="The previous time it becomes true (shift+Enter)">◀</button><button type="button" data-x="next" title="The ' +
          'next time it becomes true (Enter)">▶</button>') +
      ('<span class="svqn" aria-live="polite"></span><button type="button" data-x="add" title="Draw the expression as a signal in ƒ expressions (kept in ' +
          'this browser)">+ Row</button>') +
      '<button type="button" data-x="del" title="Remove the expression in the field (or the selected ƒ row) from the rows">− Row</button>');
    g.classList.add('svx-tool');
    this.inp = g.querySelector('input.svq'); this.cnt = g.querySelector('.svqn');
    this.inp.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); this.find(e.shiftKey ? -1 : 1);
      } else if (e.key === 'Escape') this.inp.blur(); });
    this.inp.addEventListener('input', () => { this.cnt.textContent = ''; });
    g.addEventListener('click', e => { const b = e.target.closest('button[data-x]'); if (!b) return;
      ({ prev: () => this.find(-1), next: () => this.find(1), add: () => this.add(), del: () => this.del() })[b.dataset.x](); });
    // before the names are drawn again
    v.listen('names', 'click', e => { const r = v.rowAt(e.target); if (r && r.x && this.list.includes(r.x)) { this.inp.value = r.x.text;
      this.cnt.textContent = ''; } }, { capture: true });
    if (v.extraRows) v.extraRows.push(grp => (grp ? [] : exprRows(this.st, this.list)));
    if (v.extraState) v.extraState.push({ key: 'exprs', get: () => this.json(), set: l => this.setList(l) });
    if (v.extraJSON) v.extraJSON.push(() => this.list.length ?
      `"exprs": [\n${this.list.map(x => '  ' + JSON.stringify(x.scope ? { expr: x.text, scope: x.scope } : x.text)).join(',\n')}\n]` : null);
    v.root.addEventListener('wavelens:settings', () => this.again());
    const page = (v.M.src.sva && v.M.src.sva.exprs) || [], kept = store.get(this.key);
    this.list = (kept || page).map(x => (typeof x === 'string' ? { text: x, scope: '' } : { text: x.expr || x.text, scope: x.scope || '' })).filter(x =>
      x.text);
    this.cache = new Map();
    if (this.list.length) this.again();
  }
  // the scope a new expression is written in: the selected signal's module, else the view's top ('')
  scope() { const I = scopeInfo(this.v.M), r = this.v.sel, s = r && I.of.get(r); return s && s !== I.root ? s : ''; }   // '': the view's top
  async value(x) {
    const k = x.text + '\n' + x.scope;
    if (!this.cache.has(k)) this.cache.set(k, valueOf(this.v.M, this.v.sortIgnore || [], x).catch(err => ({ err: err.message })));
    return this.cache.get(k);
  }
  // every row again (the files or the name settings changed)
  async again() {
    this.cache.clear();
    await Promise.all(this.list.map(async x => { x.res = await this.value(x); }));
    this.v.renderNames(); this.v.draw();
  }
  json() { return this.list.map(x => (x.scope ? { expr: x.text, scope: x.scope } : x.text)); }
  save() { if (!store.set(this.key, this.json())) this.v.toast('not kept in this browser'); }
  // a saved list (Load… of the viewer's state): the rows of these expressions
  async setList(l) {
    this.list = (Array.isArray(l) ? l : []).map(x => (typeof x === 'string' ? { text: x, scope: '' } : { text: x.expr || x.text, scope: x.scope ||
      '' })).filter(x => x.text);
    if (this.v.sel && this.v.sel.x && !this.list.includes(this.v.sel.x)) this.v.select(null);
    this.save(); await this.again();
  }
  text() { const t = this.inp.value.trim(); if (!t) { this.v.toast('type an expression of the signals, e.g. PSEL && !PREADY'); this.inp.focus(); } return t; }
  async add() {
    const t = this.text(); if (!t) return;
    if (this.list.some(x => x.text === t)) { this.v.toast(`ƒ ${t} is there already`); return; }
    const x = { text: t, scope: this.scope() };
    x.res = await this.value(x);
    if (x.res.err) { this.v.toast(`ƒ ${t}: ${x.res.err}`); this.inp.classList.add('bad'); setTimeout(() => this.inp.classList.remove('bad'), 900); return; }
    this.list.push(x); this.save();
    this.v.renderNames(); this.v.draw(); this.v.centerRow(this.st.rows.get(x));
    this.v.root.dispatchEvent(new CustomEvent('wavelens:sva-exprs', { detail: { added: x.text } }));
  }
  del() {
    const sel = this.v.sel && this.v.sel.x, t = this.inp.value.trim();
    const x = this.list.find(x => x.text === t) || (this.list.includes(sel) ? sel : null);
    if (!x) { this.v.toast(t ? `no ƒ row ${t}` : 'put a ƒ row in the field (click its name) to remove it'); return; }
    this.list.splice(this.list.indexOf(x), 1); this.st.rows.delete(x); this.save();
    if (this.v.sel === sel) this.v.select(null);
    this.v.renderNames(); this.v.draw();
  }
  // the next / previous time the expression in the field becomes true, from the cursor (round the ends)
  async find(dir) {
    const t = this.text(); if (!t) return;
    const x = this.list.find(x => x.text === t) || { text: t, scope: this.scope() }, res = await this.value(x), v = this.v;
    if (res.err) { this.cnt.textContent = ''; v.toast(`ƒ ${t}: ${res.err}`); return; }
    const ms = matches(res);
    if (!ms.length) { this.cnt.textContent = '0'; v.toast(`ƒ ${t}: never true`); return; }
    const k = U.stepTo(ms, v.cursor, dir);
    v.setCursor(ms[k]);
    this.cnt.textContent = `${k + 1}/${ms.length}`;
    this.last = { text: t, k, n: ms.length, t: ms[k] };
  }
}

/* ---------------- static SVG (WaveSVG): the same rows from the WaveJSON's "sva".bind[].results ---------------- */
// A binding without results (a page built without the sva binary, a hand-made figure) is evaluated in the page through
// the panel's path (evaluateScope) and the figure drawn again. The bound signals are not repeated unless svaSignals is
// true (the figure shows them already).
const SVGST = new WeakMap();
// the rows of the results' own signals (name -> path in the dump): {name: row}; a figure without the hierarchy (a
// clock-sampled view) has the path below the scope
function rowsOf(M, o) {
  const out = {}, pre = o && o.scope ? o.scope + '.' : null;
  for (const [n, p] of Object.entries((o && o.signals) || {})) {
    const rel = pre && p.startsWith(pre) ? p.slice(pre.length) : null;
    const r = M.rows.find(r => r.type === 'sig' && !r.same && (r.full === p || (r.src && r.src.path === p))) ||
      (rel && M.rows.find(r => r.type === 'sig' && !r.same && r.full === rel));
    if (r) out[n] = r;
  }
  return out;
}   // WaveJSON -> {binds: [{assert, scope, results, draw}], wait}
function svgRows(M, S) {
  const x = M.src.sva, binds = pageBinds(M), exprs = (x && Array.isArray(x.exprs) && x.exprs) || [];
  if (!binds.length && !exprs.length) return null;
  let k = SVGST.get(M.src);
  if (!k) SVGST.set(M.src, k = { binds: binds.map(b => ({ assert: b.assert, scope: b.scope || '', results: b.results || null, draw: {} })), xst: {},
    exprs: exprs.map(e => (typeof e === 'string' ? { text: e, scope: '' } : { text: e.expr || e.text, scope: e.scope || '' })).filter(e => e.text) });
  if (!k.wait && G.WAVELENS_SVA_WASM && k.binds.some(b => !b.results)) k.wait = svgEvaluate(M, S, k);
  if (!k.xwait && G.WAVELENS_SVA_WASM && k.exprs.length) k.xwait = svgExprs(M, S, k);
  const ok = shown(S), I = scopeInfo(M), at = new Map([[-1, exprRows(k.xst, k.exprs.filter(e => e.res && !e.res.err))]]);
  for (const b of k.binds) {
    const o = outcome(b);
    if (!o || !ok(b.assert) || (o.missing || []).length) continue;
    const g = I.group(b.scope), key = g ? g.id : -1, map = rowsOf(M, o);
    const copies = S.svaSignals === true ? [...new Set(Object.values(map))] : [];
    const rows = assertionRows(b.draw, b.results, { S, label: b.assert, scope: b.scope, copies, map, view: null, focus: focusOf(o),
      base: { anc: g ? g.anc.concat(g.id) : [], depth: g ? g.depth + 1 : 0 }, sel: () => -1, pick: () => {} });
    if (!at.has(key)) at.set(key, []);
    at.get(key).push(...rows);
  }
  return [g => at.get(g ? g.id : -1) || []];
}
// the expressions of a figure, valued in the page (the files of its "sva" for package constants), then drawn again
function svgExprs(M, S, k) {
  pageFiles([M]);
  const p = (LIB.files.some(f => !f.parsed) ? reparse() : LIB.parsing || reparse()).then(async () => {
    for (const e of k.exprs) { try { e.res = await valueOf(M, S.sortIgnore || [], e); } catch (err) { e.res = { err: err.message }; } }
    G.WaveLens.redrawSvgs();
  });
  LIB.svgs.add(p);
  return p;
}
function svgEvaluate(M, S, k) {
  pageFiles([M]);
  const fake = { M, sortIgnore: S.sortIgnore || [] };
  const p = (LIB.files.some(f => !f.parsed) ? reparse() : LIB.parsing || reparse()).then(async () => {
    const by = new Map();
    for (const b of k.binds) {
      const x = !b.results && LIB.byLabel.get(b.assert); if (!x) continue;
      b.res = resolve(fake, x.a, b.scope);
      if (!b.res.ok) continue;
      if (!by.has(b.scope)) by.set(b.scope, []);
      by.get(b.scope).push(b);
    }
    for (const bs of by.values()) { try { await evaluateScope(fake, bs, () => {}); } catch (err) { /* the figure stays without them */ } }
    G.WaveLens.redrawSvgs();
  });
  LIB.svgs.add(p);
  return p;
}

/* ---------------- start ---------------- */
function start() {
  if (!G.WaveLens || !G.WaveLens.plugin) return;
  // the settings of this plugin (wavelens.config.js lists them): the list open at start, which groups, the signals again
  if (G.WaveLens.registerDefaults) G.WaveLens.registerDefaults({ svaOpen: false, svaShow: null, svaSignals: 'view' });
  G.WaveLens.registerTokens({ 'sva-pass': '--sva-pass', 'sva-fail': '--sva-fail', 'sva-disabled': '--sva-disabled', 'sva-active': '--sva-active',
    'sva-capped': '--sva-capped' });
  localFiles();
  let pending = null;
  G.WaveLens.plugin(v => {
    if (v.sva) return;
    pageFiles([v.M]);
    if (G.WAVELENS_SVA_WASM) new Exprs(v);   // its rows first under the top, before the assertion groups
    new Panel(v);
    // one parse for all the viewers built in this task
    if (!pending) pending = Promise.resolve().then(() => { pending = null; return reparse(); });
  });
  if (G.WaveLens.svgPlugin) G.WaveLens.svgPlugin(svgRows);
  SVA.ready = () => (pending || Promise.resolve()).then(() => LIB.parsing).then(() => Promise.all([...LIB.panels].map(p => p.queue).concat([...LIB.svgs])));
}
start();
})(window);
