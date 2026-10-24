'use strict';
/* vscode/svtypes.js — the types of a design by path through `verilator --json-only`, for the command "WaveLens: Make the
   types with Verilator": the twin of tools/svtypes.py verilator (its walk of Verilator's tree, the same entries and notes),
   in the extension so that the host needs no Python. tests/unit/test_svtypes.py runs both on the corpus and compares them.
   As a script (the test): node svtypes.js --top TOP --out x.types.json [--verilator EXE] -- ARGS… */
const cp = require('child_process'), fs = require('fs'), os = require('os'), path = require('path');

/* ---------------- a type: {kind: enum | vec | record | union | array | elements | unknown, …} (svtypes.py's) ---------------- */
const INTS = { int: 32, integer: 32, shortint: 16, longint: 64, byte: 8, time: 64 };
// a CONST of Verilator's JSON ("3'h4", "32'shffffffff", "5") -> a BigInt, null when not a number
function constValue(name) {
  const m = /^(?:(\d+)')?(s?)([hbdo]?)([0-9a-fA-F_]+)$/.exec(name || ''); if (!m) return null;
  const base = { h: 16, b: 2, o: 8, d: 10, '': 10 }[m[3]];
  let v = 0n;
  for (const c of m[4].replace(/_/g, '').toLowerCase()) { const d = parseInt(c, base); if (isNaN(d)) return null; v = v * BigInt(base) + BigInt(d); }
  return v;
}
function width(t) {
  if (t.kind === 'enum' || t.kind === 'vec') return t.width;
  if (t.kind === 'record' || t.kind === 'union') {
    const ws = t.members.map(([, x]) => width(x)); if (ws.includes(null)) return null;
    return t.kind === 'record' ? ws.reduce((a, b) => a + b, 0) : ws.length ? Math.max(...ws) : null;
  }
  if (t.kind === 'array') { const w = width(t.elem); return w == null ? null : w * (Math.abs(t.left - t.right) + 1); }
  return null;
}
// an enum's values -> [{"value": "label"} unsigned on its width, or null and the reason]
function table(t) {
  if (t.items.length !== t.count) return [null, `${t.items.length} of its ${t.count} enum values read`];
  const mask = (1n << BigInt(t.width)) - 1n, u = t.items.map(([n, v]) => [v & mask, n]).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0));
  return [Object.fromEntries(u.map(([v, n]) => [String(v), n])), null];
}
const typed = k => k === 'enum' || k === 'record' || k === 'array';
// the fields of a type that starts at bit lsb, MSB first into out; a reason when it cannot be told
function flat(t, name, lsb, out) {
  const w = width(t);
  if (w == null) return `${name || 'the signal'}: a type it does not read (${t.text || t.kind})`;
  if (t.kind === 'enum') { const [tb, why] = table(t); if (why) return `${name}: ${why}`; out.push({ name, msb: lsb + w - 1, lsb, enum: tb }); }
  else if (t.kind === 'record') {
    let at = lsb + w; const part = [];
    for (const [mn, mt] of t.members) { at -= width(mt); const why = flat(mt, name ? `${name}.${mn}` : mn, at, part); if (why) return why; }
    out.push(...part);
  } else if (t.kind === 'array' && typed(t.elem.kind)) {
    const n = Math.abs(t.left - t.right) + 1, ew = width(t.elem), step = t.left > t.right ? -1 : 1;
    for (let j = 0; j < n; j++) { const why = flat(t.elem, `${name}[${t.left + j * step}]`, lsb + (n - 1 - j) * ew, out); if (why) return why; }
  } else out.push({ name, msb: lsb + w - 1, lsb });   // a vector, an array of vectors, a union inside a struct: one field
  return null;
}
const walkTypes = function* (t) { yield t; for (const [, m] of t.members || []) yield* walkTypes(m); if (t.elem) yield* walkTypes(t.elem); };
// a type -> [entry {width, enum | fields} or null for a plain vector, a note or null]
function lower(t) {
  if (t.kind === 'enum') { const [tb, why] = table(t); return why ? [null, why] : [{ width: t.width, enum: tb }, null]; }
  if (t.kind === 'union') return [null, 'a packed union: which member holds the value is not known'];
  if (t.kind === 'record' || (t.kind === 'array' && typed(t.elem.kind))) {
    const out = [], why = flat(t, '', 0, out);
    if (why) return [null, why];
    if (t.kind === 'array' && ![...walkTypes(t)].some(x => x.kind === 'enum' || x.kind === 'record')) return [null, null];   // plain vectors: a vector
    return [{ width: width(t), fields: out }, null];
  }
  if (t.kind === 'unknown') return [null, `a type it does not read (${t.text})`];
  return [null, null];
}

/* ---------------- Verilator: --json-only, its tree of modules, cells and types ---------------- */
// the tree -> [{path: entry}, [notes]]: from each top module down its cells and generate blocks, every variable's type
// followed through its references; a package's variables under its name
function verilatorTypes(tree) {
  const idx = new Map();
  const index = n => { if (Array.isArray(n)) n.forEach(index); else if (n && typeof n === 'object') {
    if ('addr' in n && !idx.has(n.addr)) idx.set(n.addr, n); for (const v of Object.values(n)) index(v); } };
  index(tree);
  const memo = new Map();
  const rng = r => { const m = /^\[?(-?\d+):(-?\d+)\]?$/.exec(r || ''); return m ? [+m[1], +m[2]] : null; };
  const typ = (addr, depth = 0) => {
    if (memo.has(addr)) return memo.get(addr);
    const n = idx.get(addr); if (!n || depth > 64) return { kind: 'unknown', text: `type ${addr}` };
    const k = n.type; let t;
    if (k === 'REFDTYPE') t = typ(n.refDTypep, depth + 1);
    else if (k === 'BASICDTYPE') {
      const kw = n.keyword || n.name, r = rng(n.range);
      t = ['logic', 'bit', 'reg', 'wire'].includes(kw) || kw in INTS ? { kind: 'vec', width: r ? Math.abs(r[0] - r[1]) + 1 : INTS[kw] || 1 } :
        { kind: 'unknown', text: kw };
    } else if (k === 'ENUMDTYPE') {
      const base = typ(n.refDTypep, depth + 1), items = (n.itemsp || []).map(i => [i.name, i.valuep && i.valuep.length ? constValue(i.valuep[0].name) : null]);
      t = base.kind !== 'vec' || items.some(([, v]) => v == null) ? { kind: 'unknown', text: `enum ${n.name}` } :
        { kind: 'enum', width: base.width, count: items.length, items, name: n.name };
    } else if (k === 'STRUCTDTYPE' || k === 'UNIONDTYPE') {
      t = !n.packed ? { kind: 'unknown', text: `unpacked ${n.name}` } :
        { kind: k === 'STRUCTDTYPE' ? 'record' : 'union', members: (n.membersp || []).map(m => [m.name, typ(m.dtypep || m.refDTypep, depth + 1)]) };
    } else if (k === 'PACKARRAYDTYPE') {
      const r = rng(n.declRange);
      t = r ? { kind: 'array', left: r[0], right: r[1], elem: typ(n.refDTypep, depth + 1) } : { kind: 'unknown', text: 'packed array' };
    } else if (k === 'UNPACKARRAYDTYPE') t = { kind: 'elements', elem: typ(n.refDTypep, depth + 1) };   // x[0], x[1] … of the dump
    else t = { kind: 'unknown', text: k.toLowerCase() };
    memo.set(addr, t); return t;
  };
  const sigs = {}, notes = [];
  const scope = (node, p) => {
    for (const st of [...(node.stmtsp || []), ...(node.itemsp || [])]) {   // (a generate block's are itemsp)
      const k = st.type;
      if (k === 'VAR' && !st.isParam && !['GENVAR', 'LPARAM', 'GPARAM'].includes(st.varType)) {
        let t = typ(st.dtypep); const q = [...p, st.name].join('.');   // as written (st-x of \st-x ; origName is Verilator's st__02dx)
        while (t.kind === 'elements') t = t.elem;   // unpacked, of any dimensions: the element's type, matched to x[1][2] by the lookup
        const [e, why] = lower(t);
        if (e) sigs[q] = e;
        if (why && t.kind !== 'unknown') notes.push(`${q}: ${why}`);
      } else if (k === 'CELL') { const m = idx.get(st.modp); if (m) scope(m, [...p, st.name]); }
      else if (k === 'GENBLOCK' || k === 'BEGIN') scope(st, st.implied || !st.name ? p : [...p, st.name]);
    }
  };
  const mods = tree.modulesp || [];
  for (const m of mods) if (m.type === 'MODULE' && m.level === 1) scope(m, [m.origName || m.name]);
  for (const m of mods) if (m.type === 'PACKAGE' && !/^(@|\$|__0)/.test(m.name)) scope(m, [m.name]);   // a package's variables (p.state)
  return [sigs, notes];
}

// a file's name with * or ? (rtl/*.sv: no shell expands it for execFile) -> the files of its folder it names, sorted, from
// cwd; an option (-f, +incdir+ …) and a name without them as it is; none: an error (Verilator would say less)
function expand(args, cwd = process.cwd()) {
  const out = [];
  for (const a of args) {
    if (/^[-+]/.test(a) || !/[*?]/.test(a)) { out.push(a); continue; }
    const dir = path.dirname(a), base = path.basename(a);
    if (/[*?]/.test(dir)) throw new Error(`${a}: * and ? only in a file's name, not in its folders`);
    const re = new RegExp('^' + base.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.') + '$');
    let names = []; try { names = fs.readdirSync(path.resolve(cwd, dir)); } catch (e) { /* none */ }
    const got = names.filter(n => re.test(n)).sort().map(n => (dir === '.' && !a.startsWith('.') ? n : path.join(dir, n)));
    if (!got.length) throw new Error(`${a}: no file of ${path.resolve(cwd, dir)} has such a name`);
    out.push(...got);
  }
  return out;
}

// verilator --json-only with the user's arguments (files, -f, +incdir+, +define+, -G…; rtl/*.sv expanded) -> {tree, version}
function runVerilator(args, top, exe = 'verilator', cwd = undefined) {
  args = expand(args, cwd);
  return new Promise((ok, no) => {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), 'svtypes-')), out = path.join(d, 'tree.json');
    const argv = ['--json-only', '--timing', '-Wno-fatal', '-Wno-lint', '-Wno-style', '--Mdir', d, '--json-only-output', out,
      '--json-only-meta-output', path.join(d, 'meta.json'), ...(top ? ['--top-module', top] : []), ...args];
    cp.execFile(exe, argv, { maxBuffer: 64 << 20, cwd }, (err, stdout, stderr) => {
      const done = r => { fs.rmSync(d, { recursive: true, force: true }); r(); };
      if (err && err.code === 'ENOENT') {
        return done(() => no(new Error(`${exe} is not on PATH (Verilator 5: https://verilator.org; the setting wavelens.verilator)`))); }
      let tree = null; try { tree = JSON.parse(fs.readFileSync(out, 'utf8')); } catch (e) { /* none */ }
      if (err || !tree) { const lines = String(stderr || stdout).split('\n').filter(x => x.startsWith('%Error')).join('\n').slice(0, 2000);
        const why = `verilator --json-only failed${err && err.code != null ? ` (${err.code})` : ''}:\n${lines || String(stderr).slice(-2000)}`;
        return done(() => no(new Error(why))); }
      cp.execFile(exe, ['--version'], (e2, ver) => done(() => ok({ tree, version: String(ver || '').trim() || exe })));
    });
  });
}

// the types file of a design: {wavelens: "types", version, producer, signals, notes}, as svtypes.py verilator writes it
async function make(args, top, exe = 'verilator', by = 'the VS Code extension (vscode/svtypes.js)', cwd = undefined) {
  const { tree, version } = await runVerilator(args, top, exe, cwd), [sigs, notes] = verilatorTypes(tree), now = new Date();
  const p2 = x => String(x).padStart(2, '0'), date = `${now.getFullYear()}-${p2(now.getMonth() + 1)}-${p2(now.getDate())}T${p2(now.getHours())}:` +
    `${p2(now.getMinutes())}:${p2(now.getSeconds())}`;
  const signals = Object.fromEntries(Object.keys(sigs).sort().map(k => [k, sigs[k]]));
  return { wavelens: 'types', version: 1, producer: { tool: version, by, top: top || null, args, date }, signals, notes };
}
// the file's text: a signal per line (as svtypes.py writes it)
const text = doc => '{\n' + Object.entries(doc).map(([k, x]) => k !== 'signals' ? `  ${JSON.stringify(k)}: ${JSON.stringify(x)}` :
  '  "signals": {\n' + Object.entries(x).map(([p, e]) => `    ${JSON.stringify(p)}: ${JSON.stringify(e)}`).join(',\n') + '\n  }').join(',\n') + '\n}\n';

module.exports = { constValue, verilatorTypes, expand, runVerilator, make, text };

if (require.main === module) {   // the test's: node svtypes.js --top TOP --out FILE [--verilator EXE] -- ARGS…
  const a = process.argv.slice(2), sep = a.indexOf('--'), opt = k => { const i = a.indexOf(k); return i >= 0 && (sep < 0 || i < sep) ? a[i + 1] : null; };
  make(sep >= 0 ? a.slice(sep + 1) : [], opt('--top'), opt('--verilator') || 'verilator', 'vscode/svtypes.js').then(doc => {
    fs.writeFileSync(opt('--out'), text(doc));
    const ne = Object.values(doc.signals).filter(e => e.enum).length;
    process.stderr.write(`svtypes.js: ${ne} enum and ${Object.keys(doc.signals).length - ne} struct signals -> ${opt('--out')}\n`);
  }, e => { process.stderr.write(`svtypes.js: ${e.message}\n`); process.exit(1); });
}
