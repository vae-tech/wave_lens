'use strict';
/* The extension end to end in a real VS Code: run by tests/vscode_e2e.py (VS Code of Windows connected to WSL, or a local
   one) as --extensionTestsPath, told what to do by ~/.cache/wavelens/e2e.json {out, dumps} (paths on the host). Every dump
   opens in a wavelens tab: it answers ready with its signals, a picture of it (PNG) is written to out; then a bookmark
   is kept over closing and opening the tab again (the store), and a new write of a copy of the first dump is read again
   by itself (wavelens.autoReload); a dump with a stranger code and one whose time goes back put their notes in the
   Problems panel on their lines; a VCD as Questa writes it is named from a source of the workspace, another by the types
   file beside it, read again when it is written; a dump in a folder with a space in its name; the Verilator command with
   a file's name of * ? (expanded). The results: out/result.json {run: the runner's id, done, results}; the process exits 0
   when all passed (review VI T11: the runner takes only its own run's results, every check it names, the run done). */
const vscode = require('vscode'), fs = require('fs'), path = require('path');

const os = require('os');
const CFG = JSON.parse(fs.readFileSync(path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'wavelens', 'e2e.json'), 'utf8'));
const OUT = CFG.out, DUMPS = CFG.dumps, RUN = CFG.run || null;
const results = [], ok = (name, pass, info) => { results.push({ name, pass: !!pass, info }); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

function waitEvent(api, test, ms) {
  return new Promise((res, rej) => {
    const t = setTimeout(() => { d.dispose(); rej(new Error(`no event in ${ms / 1000} s`)); }, ms);
    const d = api.events(e => { if (test(e)) { clearTimeout(t); d.dispose(); res(e); } });
  });
}
async function open(api, file) {
  const uri = vscode.Uri.file(file), t0 = Date.now();
  const got = waitEvent(api, e => e.type === 'ready' && e.tab.file === file, 180000);
  await vscode.commands.executeCommand('vscode.openWith', uri, 'wavelens.waves');
  const e = await got;
  return { tab: e.tab, ms: Date.now() - t0, shown: e.shown, total: e.total };
}
async function closeAll() { await vscode.commands.executeCommand('workbench.action.closeAllEditors'); await sleep(500); }

// an agent: tools/wavemcp.py of the repository as an MCP server over stdio; view_live with the dump and open: VS Code opens
// its tab, which connects; view_edit puts a bookmark there; view_get reads it; the link's note in ~/.cache/wavelens/live goes
async function agent(api, file) {
  const cp = require('child_process'), root = path.join(__dirname, '..', '..'), live = path.join(os.homedir(), '.cache', 'wavelens', 'live');
  const notes = () => { try { return fs.readdirSync(live).filter(f => /^\d+\.json$/.test(f)); } catch (e) { return []; } };
  const before = new Set(notes());   // another bridge's (an agent of yours): not this run's
  const p = cp.spawn('python3', ['-I', path.join(root, 'tools', 'wavemcp.py')], { stdio: ['pipe', 'pipe', 'inherit'] });
  let buf = '', id = 0; const wait = new Map();
  p.stdout.setEncoding('utf8');
  p.stdout.on('data', d => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { const m = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
    if (wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); } } });
  const rpc = (method, params, ms = 60000) => new Promise((ok, no) => { const n = ++id, t = setTimeout(() => { wait.delete(n);
    no(new Error(`${method}: no answer in ${ms / 1000} s`)); }, ms); wait.set(n, m => { clearTimeout(t); ok(m); });
    p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: n, method, params }) + '\n'); });
  const tool = async (name, args) => { const m = await rpc('tools/call', { name, arguments: args });
    const t = m.result && m.result.content && m.result.content[0].text;
    return { error: m.error || (m.result && m.result.isError && t), out: t && !(m.result && m.result.isError) ? JSON.parse(t) : null }; };
  try {
    await closeAll();
    await rpc('initialize', { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'e2e', version: '1' } });
    const opened = waitEvent(api, e => e.type === 'ready' && e.tab.file === file, 60000);
    const lv = await tool('view_live', { page: file, open: true, wait: 20 });
    await opened;
    ok('agent: view_live opens the dump', lv.out && /connected/.test(lv.out.note) && !/not connected/.test(lv.out.note), lv.out || lv.error);
    const ed = await tool('view_edit', { page: file, ops: [{ op: 'bookmark', n: 9, t: 100, text: 'from the agent' }] });
    const got = await tool('view_get', { page: file, full: true });
    const bms = (got.out && got.out.bookmarks) || [];
    ok('agent: view_edit / view_get on the tab', ed.out && ed.out.live === file && bms.some(b => b.n === 9 && b.text === 'from the agent'),
      { edit: ed.out || ed.error, bookmarks: bms.length });
    const tab = api.tabs().find(t => t.file === file);
    if (tab) await tab.run([{ op: 'bookmark', n: 9, delete: true }]);
  } catch (e) { ok('agent', false, { error: e.message }); }
  p.stdin.end();
  await Promise.race([new Promise(r => p.on('close', r)), sleep(20000).then(() => p.kill())]);
  const left = notes().filter(f => !before.has(f));
  ok('agent: its link note removed on exit', !left.length, { left, others: before.size });
  await closeAll();
}

async function run() {
  fs.mkdirSync(OUT, { recursive: true });
  const ext = vscode.extensions.getExtension('vae-tech.wavelens');
  for (let i = 0; i < 100 && !ext.isActive; i++) await sleep(100);   // onStartupFinished: an agent's open works in a fresh window
  ok('active at startup', ext.isActive, {});
  const api = await ext.activate();
  ok('activate', !!api, { remote: vscode.env.remoteName || null, vscode: vscode.version, platform: process.platform, at: ext.extensionPath,
    version: ext.packageJSON.version });
  for (const f of DUMPS) {
    const name = path.basename(f);
    try {
      const o = await open(api, f);
      const res = await o.tab.run([{ op: 'fit' }, { op: 'rows', limit: 400 }, { op: 'picture', format: 'png' }]);
      const rows = res[1] && res[1].rows, png = res[2] && res[2].png;
      if (png) fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(png, 'base64'));
      ok('open ' + name, o.shown > 0 && png, { ms: o.ms, shown: o.shown, total: o.total, rows: rows && rows.length, png: !!png,
        error: res.error || (res[2] && res[2].error) });
    } catch (e) { ok('open ' + name, false, { error: e.message }); }
    await closeAll();
  }
  // the store: a bookmark survives closing the tab
  if (DUMPS.length) {
    const f = DUMPS[0];
    try {
      let o = await open(api, f);
      await o.tab.run([{ op: 'bookmark', n: 7, text: 'e2e kept' }]);
      await closeAll(); await sleep(800);
      o = await open(api, f);
      const st = await o.tab.run([{ op: 'state' }]), bms = (st[0] && st[0].state && st[0].state.bookmarks) || [];
      ok('store over reopening', bms.some(b => b.n === 7 && b.text === 'e2e kept'), { bookmarks: bms.length });
      await o.tab.run([{ op: 'bookmark', n: 7, delete: true }]);
      await closeAll();
    } catch (e) { ok('store over reopening', false, { error: e.message }); }
    // a new simulation: a copy of the first dump written again is read by itself
    const cfg = vscode.workspace.getConfiguration('wavelens');
    try {
      await cfg.update('autoReload', true, vscode.ConfigurationTarget.Global);
      const copy = path.join(OUT, 'reload' + path.extname(f));
      fs.copyFileSync(f, copy);
      const o = await open(api, copy);
      const again = waitEvent(api, e => e.type === 'loaded' && e.tab === o.tab, 30000);
      await sleep(1500);
      fs.appendFileSync(copy, path.extname(f) === '.vcd' ? '\n' : '');
      if (path.extname(f) !== '.vcd') fs.utimesSync(copy, new Date(), new Date());
      const e = await again;
      ok('reload on a new write', e.shown > 0, { shown: e.shown });
      await closeAll();
      // a new simulation with other values (review IV B1): the watcher reads it, the tab has the new ones
      const small = path.join(OUT, 'values.vcd'), dump = t => '$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$upscope $end\n' +
        `$enddefinitions $end\n#0\n0!\n#${t}\n1!\n#100\n`;
      fs.writeFileSync(small, dump(10));
      const s = await open(api, small), r1 = await s.tab.run([{ op: 'cursor', t: 0 }, { op: 'edge', kind: 'rise', signal: 'tb.a' }]);
      const read = waitEvent(api, e => e.type === 'loaded' && e.tab === s.tab, 30000);
      await sleep(1500); fs.writeFileSync(small, dump(30)); await read;
      const r2 = await s.tab.run([{ op: 'cursor', t: 0 }, { op: 'edge', kind: 'rise', signal: 'tb.a' }]);
      ok('reload: the new values', r1[1].t === 10000 && r2[1].t === 30000, { before: r1[1], after: r2[1] });
      await closeAll();
    } catch (e) { ok('reload on a new write', false, { error: e.message }); }
    await cfg.update('autoReload', undefined, vscode.ConfigurationTarget.Global);
  }
  // the log: what the reader noticed in a dump goes to the Problems panel on its line; one it cannot read, an error there
  try {
    const head = '$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n';
    const odd = path.join(OUT, 'odd.vcd'), bad = path.join(OUT, 'bad.vcd');
    fs.writeFileSync(odd, head + '#0\n0!\n1?\n#5\n1!\n');   // line 8: a code no $var declares
    fs.writeFileSync(bad, head + '#10\n0!\n#5\n1!\n');      // line 8: the time goes back
    await open(api, odd);
    const p1 = api.problems(vscode.Uri.file(odd)).map(d => [d.severity, d.range.start.line + 1]);
    const failed = waitEvent(api, e => e.type === 'dumperror' && e.tab.file === bad, 60000);
    await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(bad), 'wavelens.waves');
    await failed;
    const p2 = api.problems(vscode.Uri.file(bad)).map(d => [d.severity, d.range.start.line + 1]);
    ok('the log: Problems on the lines', JSON.stringify(p1) === '[[1,8]]' && JSON.stringify(p2) === '[[0,8]]', { odd: p1, bad: p2 });
    await closeAll();
    ok('the log: cleared with the tab', !api.problems(vscode.Uri.file(odd)).length, {});
  } catch (e) { ok('the log', false, { error: e.message }); }
  // the theme command: its list opens, a move previews, Enter keeps the choice in the setting (the command itself, not a message)
  if (DUMPS.length) {
    const cfg = vscode.workspace.getConfiguration('wavelens');
    try {
      await open(api, DUMPS[0]);
      const done = vscode.commands.executeCommand('wavelens.theme');
      await sleep(800);
      await vscode.commands.executeCommand('workbench.action.quickOpenSelectNext');   // auto -> vscode
      await sleep(300);
      await vscode.commands.executeCommand('workbench.action.acceptSelectedQuickOpenItem');
      await Promise.race([done, sleep(5000)]);
      const got = vscode.workspace.getConfiguration('wavelens').get('theme');
      ok('theme: the command\'s list picks one', got === 'vscode', { theme: got });
    } catch (e) { ok('theme', false, { error: e.message }); }
    await cfg.update('theme', undefined, vscode.ConfigurationTarget.Global);
    await closeAll();
  }
  // a VCD as Questa writes it (no enum tables) next to its SystemVerilog source in the workspace: the tab names the states
  // from the source by itself (wavelens.sources)
  if (DUMPS.length) {
    const dir = path.join(path.dirname(DUMPS[0]), 'wavelens-e2e-src');
    try {
      fs.mkdirSync(dir, { recursive: true });
      // the typedef in a package, the variable in a module of another file (review IV A2: that file has no "enum" in it)
      fs.writeFileSync(path.join(dir, 'pkg.sv'), 'package p;\n    typedef enum logic [1:0] {IDLE, START, DATA, STOP} state_t;\nendpackage\n');
      fs.writeFileSync(path.join(dir, 'tb.sv'), 'module tb;\n    p::state_t state;\nendmodule\n');
      const q = path.join(dir, 'questa.vcd');
      fs.writeFileSync(q, '$timescale 1ns $end\n$scope module tb $end\n$var reg 2 " state [1:0] $end\n$upscope $end\n$enddefinitions $end\n' +
        '#0\nb0 "\n#10\nb1 "\n#20\nb10 "\n');
      const o = await open(api, q);
      const r = await o.tab.run([{ op: 'cursor', t: 0 }, { op: 'edge', value: 'DATA', signal: 'tb.state' }]);   // a label only the source knows
      ok('sources: a Questa VCD named from the workspace', r[1] && r[1].moved && r[1].t === 20000, { edge: r[1] });
      await closeAll();
    } catch (e) { ok('sources', false, { error: e.message }); }
    // its types file beside it (review V C9): the labels of its path, not the workspace's by name; written again, read again
    const cfg = vscode.workspace.getConfiguration('wavelens');
    try {
      await cfg.update('autoReload', true, vscode.ConfigurationTarget.Global);
      const q = path.join(dir, 'typed.vcd'), ty = path.join(dir, 'typed.types.json');
      const types = names => JSON.stringify({ wavelens: 'types', version: 1, producer: { tool: 'e2e' },
        signals: { 'tb.state': { width: 2, enum: Object.fromEntries(names.map((n, i) => [String(i), n])) } } });
      fs.writeFileSync(q, '$timescale 1ns $end\n$scope module tb $end\n$var reg 2 " state [1:0] $end\n$upscope $end\n$enddefinitions $end\n' +
        '#0\nb0 "\n#10\nb1 "\n#20\nb10 "\n');
      fs.writeFileSync(ty, types(['T0', 'T1', 'T2']));
      const o = await open(api, q);
      const a = await o.tab.run([{ op: 'cursor', t: 0 }, { op: 'edge', value: 'T2', signal: 'tb.state' }, { op: 'cursor', t: 0 },
        { op: 'edge', value: 'DATA', signal: 'tb.state' }]);
      const again = waitEvent(api, e => e.type === 'loaded' && e.tab === o.tab, 30000);
      await sleep(1500); fs.writeFileSync(ty, types(['U0', 'U1', 'U2'])); await again;
      const b = await o.tab.run([{ op: 'cursor', t: 0 }, { op: 'edge', value: 'U2', signal: 'tb.state' }]);
      ok('types: the file beside the dump wins over the sources, read again when written', a[1] && a[1].t === 20000 && !(a[3] && a[3].moved) &&
        b[1] && b[1].t === 20000, { t2: a[1], data: a[3], u2: b[1] });
      await closeAll();
    } catch (e) { ok('types', false, { error: e.message }); }
    // the command Make the types with Verilator (vscode/svtypes.js): the FSM example's VCD copied, its sources given; the
    // types file beside the copy, the tab reads it: the states by name
    try {
      const fsmVcd = DUMPS.find(f => /fsm\.vcd$/.test(f)), src = path.join(__dirname, '..', '..', 'examples', 'fsm');
      if (fsmVcd) {
        const q = path.join(dir, 'fsm_copy.vcd'); fs.copyFileSync(fsmVcd, q);
        const o = await open(api, q);
        const again = waitEvent(api, e => e.type === 'loaded' && e.tab === o.tab, 120000);
        const res = await vscode.commands.executeCommand('wavelens.verilatorTypes', { args: [path.join(src, 'uart_pkg.sv'), path.join(src, 'fsm_tb.sv')],
          top: 'fsm_tb' });
        await again;
        const r = await o.tab.run([{ op: 'cursor', t: 0 }, { op: 'edge', value: 'STOP', signal: 'fsm_tb.u_rx.state' }]);
        ok('types: the command makes them with Verilator, the tab reads them', res && res.signals === 3 && fs.existsSync(path.join(dir, 'fsm_copy.types.json')) &&
          r[1] && r[1].moved, { res, edge: r[1] });
        await closeAll();
      }
    } catch (e) { ok('types: Verilator', false, { error: e.message }); }
    // the arguments as typed (review VI A5): a file's name with ? expanded from the workspace's folder, no shell
    try {
      const fsmVcd = DUMPS.find(f => /fsm\.vcd$/.test(f)), src = path.join(__dirname, '..', '..', 'examples', 'fsm');
      if (fsmVcd) {
        const q = path.join(dir, 'fsm_glob.vcd'); fs.copyFileSync(fsmVcd, q);
        const o = await open(api, q);
        const res = await vscode.commands.executeCommand('wavelens.verilatorTypes', { args: [path.join(src, 'uart_pk?.sv'), path.join(src, 'fsm_tb.sv')],
          top: 'fsm_tb' });
        ok('types: Verilator, a file\'s name of ? expanded', res && res.signals === 3, { res });
        await closeAll();
      }
    } catch (e) { ok('types: Verilator, a file\'s name of ? expanded', false, { error: e.message }); }
    await cfg.update('autoReload', undefined, vscode.ConfigurationTarget.Global);
    fs.rmSync(dir, { recursive: true, force: true });
    // a dump in a folder with a space (a Windows user's): its URI and its path to the host as they are
    const sp = path.join(path.dirname(DUMPS[0]), 'wavelens e2e space');
    try {
      fs.mkdirSync(sp, { recursive: true });
      const q = path.join(sp, 'a b.vcd');
      fs.writeFileSync(q, '$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n#10\n1!\n');
      const o = await open(api, q), r = await o.tab.run([{ op: 'cursor', t: 0 }, { op: 'edge', kind: 'rise', signal: 'tb.a' }]);
      ok('a dump in a folder with a space', o.shown === 1 && r[1] && r[1].t === 10000, { shown: o.shown, edge: r[1] });
      await closeAll();
    } catch (e) { ok('a dump in a folder with a space', false, { error: e.message }); }
    fs.rmSync(sp, { recursive: true, force: true });
  }
  if (DUMPS.length) await agent(api, DUMPS[0]);
  fs.writeFileSync(path.join(OUT, 'result.json'), JSON.stringify({ run: RUN, done: true, results }, null, 1));
  const bad = results.filter(r => !r.pass);
  if (bad.length) throw new Error(`${bad.length} of ${results.length} failed: ${bad.map(r => r.name).join(', ')}`);
}
module.exports = { run };
