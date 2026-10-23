'use strict';
/* The extension end to end in a real VS Code: run by tests/vscode_e2e.py (VS Code of Windows connected to WSL, or a local
   one) as --extensionTestsPath, told what to do by ~/.cache/wavelens/e2e.json {out, dumps} (paths on the host). Every dump
   opens in a wavelens tab: it answers ready with its signals, a picture of it (PNG) is written to out; then a bookmark
   is kept over closing and opening the tab again (the store), and a new write of a copy of the first dump is read again
   by itself (wavelens.autoReload). The results: out/result.json; the process exits 0 when all passed. */
const vscode = require('vscode'), fs = require('fs'), path = require('path');

const os = require('os');
const CFG = JSON.parse(fs.readFileSync(path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'wavelens', 'e2e.json'), 'utf8'));
const OUT = CFG.out, DUMPS = CFG.dumps;
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
  const cp = require('child_process'), root = path.join(__dirname, '..', '..');
  const p = cp.spawn('python3', ['-I', path.join(root, 'tools', 'wavemcp.py')], { stdio: ['pipe', 'pipe', 'inherit'] });
  let buf = '', id = 0; const wait = new Map();
  p.stdout.setEncoding('utf8');
  p.stdout.on('data', d => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { const m = JSON.parse(buf.slice(0, i)); buf = buf.slice(i + 1);
    if (wait.has(m.id)) { wait.get(m.id)(m); wait.delete(m.id); } } });
  const rpc = (method, params) => new Promise(ok => { wait.set(++id, ok); p.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); });
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
  await new Promise(r => p.on('close', r));
  let left = [];
  try { left = fs.readdirSync(path.join(os.homedir(), '.cache', 'wavelens', 'live')).filter(f => /^\d+\.json$/.test(f)); } catch (e) { /* none */ }
  ok('agent: its link note removed on exit', !left.length, { left });
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
    } catch (e) { ok('reload on a new write', false, { error: e.message }); }
    await cfg.update('autoReload', undefined, vscode.ConfigurationTarget.Global);
  }
  if (DUMPS.length) await agent(api, DUMPS[0]);
  fs.writeFileSync(path.join(OUT, 'result.json'), JSON.stringify(results, null, 1));
  const bad = results.filter(r => !r.pass);
  if (bad.length) throw new Error(`${bad.length} of ${results.length} failed: ${bad.map(r => r.name).join(', ')}`);
}
module.exports = { run };
