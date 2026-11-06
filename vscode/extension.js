'use strict';
/* wavelens for VS Code — the extension host's half. It runs where the files are (extensionKind "workspace": the Linux
   host of Remote-SSH or WSL); the tab's webview runs on the client (Windows). A dump (.vcd, .fst) opens in a custom
   editor: the wavelens viewer (media/, or ../wavelens in the repository) that fetches the dump through its webview URI (an
   FST turned into VCD text first by the bundled sva, kept in the extension's storage). media/host.js brings here what a
   browser would do itself: the downloads (a save dialog on the host), the file pickers, the clipboard, localStorage
   (this dump's store in workspaceState), the agent's live link (tools/wavemcp.py listens on the host's 127.0.0.1, which
   the client cannot reach: this side relays it), the theme (wavelens.theme). Nothing is installed on the host: node is VS Code's, sva is static. */
const vscode = require('vscode'), fs = require('fs'), path = require('path'), os = require('os'), crypto = require('crypto');
const http = require('http'), cp = require('child_process');

const VIEW = 'wavelens.waves';
const MEDIA = ['wavelens.css', 'wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js'];
const TABS = new Set();
const PROTO = require('./protocol.js');   // the messages of a tab's page, checked as they come (A-05)
const EVENTS = new vscode.EventEmitter();   // {type, tab, …} from the webviews (ready, loaded): the tests listen
let CTX, OUT, DIAG;

const log = s => OUT && OUT.appendLine(`[${new Date().toISOString().slice(11, 19)}] ${s}`);
const exists = p => { try { fs.accessSync(p); return true; } catch (e) { return false; } };
const sha = s => crypto.createHash('sha1').update(s).digest('hex').slice(0, 16);
const cacheDir = () => path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'wavelens');

// where the viewer's files are: inside the package (make vsix), else the repository around vscode/ (development)
function roots() {
  const ext = CTX.extensionPath, inside = path.join(ext, 'media');
  return { host: inside, wavelens: exists(path.join(inside, 'wavelens.js')) ? inside : path.join(ext, '..', 'wavelens') };
}
// the CLI: wavelens.sva, else the package's (bin/sva: the .vsix carries the Linux one), else the repository's (make dist-linux:
// bin/linux-x86_64/sva, make dist-windows: bin/windows-x86_64/sva.exe), else sva on the PATH (none: noCli says so)
const OS_DIR = { linux: 'linux', win32: 'windows' };
function svaBin() {
  const set = vscode.workspace.getConfiguration('wavelens').get('sva');
  if (set) return set;
  const ext = CTX.extensionPath, exe = process.platform === 'win32' ? 'sva.exe' : 'sva';
  for (const p of [path.join(ext, 'bin', exe), path.join(ext, '..', 'bin', `${OS_DIR[process.platform] || process.platform}-x86_64`, exe)]) {
    if (!exists(p)) continue;
    try { fs.accessSync(p, fs.constants.X_OK); } catch (e) { try { fs.chmodSync(p, 0o755); } catch (e2) { /* read-only */ } }   // a vsix keeps no mode
    return p;
  }
  return 'sva';   // on the PATH
}
// a CLI that did not start: none bundled for this platform (the .vsix carries the Linux one) and none on the PATH -> wavelens.sva named
const noCli = (bin, e) => (e.code === 'ENOENT' ? `there is no sva CLI on this host (${bin}; none bundled for ${process.platform}): set wavelens.sva ` +
  'to its path (the repository builds one: make dist-linux, make dist-windows)' : `${bin}: ${e.message}`);
// the JSON the CLI wrote on stdout: where sva cannot put fd 1 aside (Windows) wellen's "WARN: …" lines stand before it
const cliJson = s => JSON.parse(s.slice(Math.max(0, s.search(/^[{[]/m))));

// The CLI run with what it reads on stdin -> {code, out, err} (code -1: it did not start; big: its output passed maxOut and it
// was killed). Its stdin guarded: a CLI that exits before node has written (sva runs list reads none) is no EPIPE thrown
// out of the extension. keep(p): the child, to kill with the tab or a newer ask
function spawnRun(bin, args, { input = '', maxOut = Infinity, keep = p => p } = {}) {
  return new Promise(ok => {
    const p = keep(cp.spawn(bin, args, { stdio: ['pipe', 'pipe', 'pipe'] })), out = [], err = [];
    let size = 0, big = false;
    p.stdin.on('error', () => { /* it closed its stdin: what it says comes on stdout, stderr and its exit */ });
    p.stdout.on('data', d => { size += d.length; if (size > maxOut) { big = true; p.kill(); } else out.push(d); });
    p.stderr.on('data', d => err.push(d));
    p.on('error', e => ok({ code: -1, out: '', err: noCli(bin, e) }));
    p.on('close', (code, sig) => ok({ code: code == null ? -1 : code, sig, big, out: Buffer.concat(out).toString('utf8'),
      err: Buffer.concat(err).toString('utf8').trim().replace(/^sva: /, '') }));
    p.stdin.end(input);
  });
}

/* ---------------- an FST as VCD text: sva vcd, kept by path, size, time and the program ---------------- */
// A large dump is read as it is needed (wavelens.lazy; auto: an FST of 4 MB, a VCD of 64 MB or more): the tab gets the
// header of its FST (sva vcd --header: every module and signal, no value), then the signals it shows (sva vcd --codes);
// a VCD becomes an FST once (sva fst --no-types, kept as the text is)
const CONV = new Map();   // the conversions running: their output -> Promise
const LAZY_FST = 4 << 20, LAZY_VCD = 64 << 20;
function lazyFor(file, size) {
  const set = vscode.workspace.getConfiguration('wavelens').get('lazy') || 'auto';
  if (/\.json$/i.test(file)) return false;   // a piece of waves (x.wavelens.json): read whole
  return set === 'always' || (set !== 'never' && size >= (/\.fst$/i.test(file) ? LAZY_FST : LAZY_VCD));
}
const vcdOf = file => (/\.fst$/i.test(file) ? convert(file, 'vcd', 'VCD text', (bin, tmp) => ['vcd', file, '--out', tmp]) : Promise.resolve(file));
const fstOf = file => (/\.fst$/i.test(file) ? Promise.resolve(file) :
  convert(file, 'fst', 'FST', (bin, tmp) => ['fst', file, '--no-types', '--quiet', '--out', tmp]));
const headerOf = fst => convert(fst, 'head.vcd', 'its modules and signals', (bin, tmp) => ['vcd', fst, '--header', '--out', tmp]);
// the file sva makes of `file` (ext: vcd, fst, head.vcd), kept by the file's path, size, time and the program
async function convert(file, ext, what, args) {
  const st = await fs.promises.stat(file), bin = svaBin();
  let tag = bin; try { const b = fs.statSync(bin); tag += b.size + ':' + b.mtimeMs; } catch (e) { /* on the PATH */ }
  const dir = path.join(CTX.globalStorageUri.fsPath, 'fst'), key = sha(file);
  const out = path.join(dir, `${key}-${sha(`${st.size}:${st.mtimeMs}:${tag}`)}.${ext}`);
  if (exists(out)) return out;
  if (CONV.has(out)) return CONV.get(out);
  const job = (async () => {
    await fs.promises.mkdir(dir, { recursive: true });
    const tmp = `${out}.${process.pid}.${Date.now()}.part`;
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `WaveLens: ${path.basename(file)} → ${what}` }, () =>
        new Promise((ok, no) => {
          const p = cp.spawn(bin, args(bin, tmp), { stdio: ['ignore', 'ignore', 'pipe'] });
          let err = ''; p.stderr.on('data', d => { err += d; });
          p.on('error', e => no(new Error(noCli(bin, e))));
          p.on('close', code => (code === 0 ? ok() : no(new Error(err.trim() || `${bin} ${args(bin, tmp)[0]}: exit ${code}`))));
        }));
      await fs.promises.rename(tmp, out);   // a revision's file is whole or not there (other windows share the directory)
    } catch (e) { await fs.promises.unlink(tmp).catch(() => {}); throw e; }
    await evict(dir);
    return out;
  })().finally(() => CONV.delete(out));
  CONV.set(out, job);
  return job;
}

// the newest 16 conversions kept; one an open tab reads, or younger than ten minutes (another window's), stays
async function evict(dir) {
  const used = new Set([...TABS].flatMap(t => [t.src, t.fst])), now = Date.now(), all = [];
  for (const f of await fs.promises.readdir(dir).catch(() => [])) {
    const p = path.join(dir, f);
    try { const st = await fs.promises.stat(p); if (/\.(vcd|fst)$/.test(f) || now - st.mtimeMs > 86400e3) all.push([p, st.mtimeMs]); } catch (e) { /* gone */ }
  }
  all.sort((a, b) => b[1] - a[1]);
  for (const [p, t] of all.slice(16)) if (!used.has(p) && now - t > 600e3) await fs.promises.unlink(p).catch(() => {});
}

/* ---------------- a VCD as an FST beside it: sva fst (tb.vcd -> tb.fst, the FSM states of tb.types.json in it) ---------------- */
// From the explorer's menu of a .vcd, the menu of its tab, or the palette (the active tab's VCD). sva writes the FST whole
// or not at all (an older one stays when it fails); its notes (file:line, five of a kind, then their count) go to the log
// as they come, its last line too; a failure opens the log. opts {quiet}: no messages (the tests) -> {ok, fst, said, notes}
async function toFst(file, opts = {}) {
  if (!file || !/\.vcd$/i.test(file)) {
    if (!opts.quiet) vscode.window.showWarningMessage('WaveLens: an FST is made from a .vcd (the explorer\'s menu of one, or its tab)');
    return { ok: false, notes: [] };
  }
  const bin = svaBin(), fst = file.replace(/\.vcd$/i, '.fst'), notes = [];
  log(`${file} → ${path.basename(fst)}: ${bin} fst`);
  let said = '';
  // its lines of progress (sva: tb.vcd: progress: 40% …) in the log and the notification, not counted as notes; a run
  // stopped leaves its part (tb.fst.<pid>.part): removed here
  const run = (token, bar) => new Promise((ok, no) => {
    const p = cp.spawn(bin, ['fst', file], { stdio: ['ignore', 'pipe', 'pipe'] });
    let err = '';
    const lines = d => { err += d; let i; while ((i = err.indexOf('\n')) >= 0) { const l = err.slice(0, i); err = err.slice(i + 1); if (!l) continue;
      log(l); const m = /^sva: .*?: progress: (.*)$/.exec(l); if (!m) notes.push(l); else if (bar) bar.report({ message: m[1] }); } };
    p.stdout.on('data', d => { said += d; });
    p.stderr.on('data', lines);
    if (token) token.onCancellationRequested(() => p.kill());
    p.on('error', e => no(new Error(noCli(bin, e))));
    p.on('close', (code, sig) => { if (err) lines('\n'); said = said.trim(); if (said) log(said);
      if (code !== 0 && p.pid) fs.unlink(`${fst}.${p.pid}.part`, () => {});
      if (code === 0) ok(); else no(new Error(sig ? 'stopped' : notes[notes.length - 1] || `${bin} fst: exit ${code}`)); });
  });
  try {
    if (opts.quiet) await run(null);
    else await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `WaveLens: ${path.basename(file)} → FST`,
      cancellable: true }, (bar, token) => run(token, bar));
  } catch (e) {
    log(`${path.basename(fst)} not written: ${e.message}`);
    if (!opts.quiet) { OUT.show(true); vscode.window.showErrorMessage(`WaveLens: ${e.message.replace(/^sva: /, '')}`); }
    return { ok: false, notes, error: e.message };
  }
  if (!opts.quiet) {
    const what = said.replace(/^.*?\.fst: /, '');
    vscode.window.showInformationMessage(`WaveLens: ${path.basename(fst)} written beside the VCD: ${what}` +
      (notes.length ? ` (${notes.length} note${notes.length === 1 ? '' : 's'} in the log)` : ''), 'Open', 'Show the log').then(a => {
      if (a === 'Open') vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(fst), VIEW);
      else if (a === 'Show the log') OUT.show(true);
    });
  }
  return { ok: true, fst, said, notes };
}

/* ---------------- the workspace's SystemVerilog sources (wavelens.sources) ---------------- */
// The files that declare an enum or a packed struct, and the files that use one of those types (a module's "p::state_t
// state;" with the typedef in a package): their texts for svTables in the tab. Each file's text is kept by its size and
// time (every tab and every read share it: a reload reads only what changed); a file above 8 MB is not read, at most 4000
// files and 64 MB are read (and kept) in all, 32 MB of texts go to a tab; what is left out is said. Calls while one runs
// share it.
const SRC = new Map();   // path -> {size, mtime, text}
const SRC_MAX_FILE = 8 << 20, SRC_MAX_READ = 64 << 20, SRC_MAX_ALL = 32 << 20, SRC_MAX_N = 4000;
const SRC_TYPES = [/\btypedef\s+enum\b[^{;]*\{[^}]*\}\s*(\w+)\s*;/g, /\btypedef\s+struct\s+packed\b[^{;]*\{[^}]*\}\s*(\w+)\s*;/g];
let SRC_JOB = null;
function workspaceSources() {
  if (!SRC_JOB) SRC_JOB = scanSources().finally(() => { SRC_JOB = null; });
  return SRC_JOB;
}
async function scanSources() {
  const globs = vscode.workspace.getConfiguration('wavelens').get('sources') || [];
  const out = { texts: [], files: 0, types: 0, left: 0, why: '' };
  if (!globs.length || !vscode.workspace.workspaceFolders) { SRC.clear(); return out; }
  const paths = new Set(); let many = false;
  for (const g of globs) for (const u of await vscode.workspace.findFiles(g, '**/{node_modules,.git}/**', SRC_MAX_N + 1)) {
    if (paths.size < SRC_MAX_N) paths.add(u.fsPath); else if (!paths.has(u.fsPath)) many = true; }
  const texts = new Map(), big = []; let read = 0, over = 0;
  for (const p of paths) {
    let st; try { st = await fs.promises.stat(p); } catch (e) { continue; }
    if (st.size > SRC_MAX_FILE) { big.push(path.basename(p)); continue; }
    if (read + st.size > SRC_MAX_READ) { over++; continue; }   // before reading it: the bytes in all stay bounded, the cache too
    read += st.size;
    let c = SRC.get(p);
    if (!c || c.size !== st.size || c.mtime !== st.mtimeMs) {
      try { c = { size: st.size, mtime: st.mtimeMs, text: await fs.promises.readFile(p, 'utf8') }; } catch (e) { continue; }
      SRC.set(p, c);
    }
    texts.set(p, c.text);
  }
  for (const p of [...SRC.keys()]) if (!texts.has(p)) SRC.delete(p);   // gone, or out of the globs now
  // the types declared, then every file that declares one or names one (or has an anonymous enum)
  const types = new Set();
  for (const t of texts.values()) for (const re of SRC_TYPES) for (const m of t.matchAll(re)) types.add(m[1]);
  const uses = types.size ? new RegExp(`\\b(?:${[...types].map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\b`) : null;
  let size = 0, cut = 0;
  for (const t of texts.values()) {
    if (!/\benum\b|\bstruct\s+packed\b/.test(t) && !(uses && uses.test(t))) continue;
    if (size + t.length > SRC_MAX_ALL) { cut++; continue; }
    out.texts.push(t); size += t.length;
  }
  Object.assign(out, { files: paths.size, types: types.size, left: big.length + over + cut + (many ? 1 : 0),
    why: [big.length ? `${big.length} above 8 MB: ${big.slice(0, 3).join(', ')}` : '', over ? `${over} past 64 MB read` : '',
      cut ? `${cut} past 32 MB sent` : '', many ? `more than ${SRC_MAX_N} files: the first ${SRC_MAX_N}` : ''].filter(Boolean).join('; ') });
  return out;
}

// the types file of a dump: its name with .types.json (tb.vcd, tb.fst -> tb.types.json)
const typesFile = f => f.replace(/\.(vcd|fst)$/i, '') + '.types.json';

/* ---------------- a tab: one dump in a webview ---------------- */
const LAST_STATE = 'lastState';   // workspaceState: the path of the state loaded last
class Tab {
  constructor(uri, panel) {
    this.uri = uri; this.file = uri.fsPath; this.panel = panel; this.wait = new Map(); this.rid = 0; this.streams = new Map(); this.procs = new Set();
    this.storeKey = 'store:' + uri.toString(); this.changed = new Map();
    const r = roots();
    panel.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.file(r.host), vscode.Uri.file(r.wavelens),
      vscode.Uri.file(path.dirname(this.file)), vscode.Uri.file(path.join(CTX.globalStorageUri.fsPath, 'fst'))] };
    panel.webview.onDidReceiveMessage(m => this.message(m).catch(e => { log(`${path.basename(this.file)}: ${e.stack || e}`);
      if (m && m.id) this.post({ id: m.id, error: e.message }); }));
    panel.onDidDispose(() => this.dispose());
    panel.webview.html = this.html(r);
    this.watch();
    TABS.add(this);
  }
  post(m) { return this.panel.webview.postMessage(m); }
  html(r) {
    const w = this.panel.webview, nonce = crypto.randomBytes(16).toString('base64'), src = w.cspSource;
    const u = (root, f) => w.asWebviewUri(vscode.Uri.file(path.join(root, f))).toString();
    const name = path.basename(this.file), esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
    const json = s => JSON.stringify(s).replace(/</g, '\\u003c');
    const host = { name, path: this.file, store: this.storeNow(), autoReload: !!vscode.workspace.getConfiguration('wavelens').get('autoReload'),
      theme: themeOf(), build: buildOf(), keysLeft: vscode.workspace.getConfiguration('wavelens').get('keysToVSCode') || [],
      lastState: CTX.workspaceState.get(LAST_STATE) || null, openLastState: !!vscode.workspace.getConfiguration('wavelens').get('openLastState'),
      config: cfgNow() };
    const scripts = MEDIA.filter(f => f.endsWith('.js')).map(f => `<script nonce="${nonce}" src="${u(r.wavelens, f)}"></script>`).join('\n');
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${src} blob: data:; style-src ${src} 'unsafe-inline';
  font-src ${src}; script-src 'nonce-${nonce}' 'wasm-unsafe-eval'; worker-src blob:; connect-src ${src} blob: data:;">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(name)}</title>
<link rel="stylesheet" href="${u(r.wavelens, 'wavelens.css')}">
<style>
  body { margin: 0; padding: 8px 10px; background: var(--bg); color: var(--fg); font-family: var(--font-body); }
</style>
</head>
<body>
<script type="application/json" id="wavelens-host">${json(host)}</script>
<script type="application/wavedrom" data-title="${esc(name)}">
{ "signal": [{ "name": "reading…", "wave": "x..." }], "head": { "text": ${json('reading ' + name + '…')} } }
</script>
<script nonce="${nonce}" src="${u(r.host, 'host.js')}"></script>
${scripts}
</body>
</html>`;
  }
  // the dump's store as it is now: the kept keys and this tab's changes not written yet. The page of a webview VS Code made
  // again (the tab moved to a window of its own) has the html of when the tab opened: source() gives it the keys of now
  storeNow() {
    const cur = Object.assign({}, CTX.workspaceState.get(this.storeKey) || {});
    for (const [k, v] of this.changed) if (v == null) delete cur[k]; else cur[k] = v;
    return cur;
  }
  // -> {src, name, lazy, store}: the URI the webview fetches now (an FST: its VCD text, converted when it changed; a large dump:
  // the header of its FST, lazy), the dump's store. The dump of now: a run shown (runs open) is A no more
  async source() {
    this.shown = null;
    let o;
    try { o = await this.srcOf(this.file, path.basename(this.file)); } catch (e) { this.report({ error: e.message }); throw e; }
    return Object.assign(o, { store: this.storeNow() });
  }
  // the file the tab shows (the dump, or a run kept) served: this.src the text the webview reads (bytes()), this.fst the FST
  // its signals are read from when lazy (codes()) -> {src, name, lazy}
  async srcOf(file, name) {
    const lazy = lazyFor(file, (await fs.promises.stat(file)).size), fst = lazy ? await fstOf(file) : null;
    const f = lazy ? await headerOf(fst) : await vcdOf(file);
    this.fst = fst; this.src = f;
    if (lazy) log(`${name}: large: its modules and signals first, the values of the ones shown as they are needed`);
    return { src: this.panel.webview.asWebviewUri(vscode.Uri.file(f)).toString(), name, lazy };
  }
  // the bytes of what source() named, for a webview that could not fetch its URI (a tab moved to a window of its own over a
  // remote connection: its resource loads answer 404) -> {data: Uint8Array}
  async bytes() {
    if (!this.src) return { error: 'no dump read yet' };
    const b = await fs.promises.readFile(this.src);
    return { data: new Uint8Array(b.buffer, b.byteOffset, b.length) };
  }
  proc(p) { this.procs.add(p); p.on('close', () => this.procs.delete(p)); p.on('error', () => this.procs.delete(p)); return p; }   // killed with the tab
  // the VCD text of some signals of the large dump (their id codes in its header): sva vcd --codes of its FST -> {text}
  async codes(list) {
    const bin = svaBin(), fst = this.fst;
    if (!fst) return { error: 'this dump is read whole' };
    const r = await spawnRun(bin, ['vcd', fst, '--codes', '-'], { input: list.map(String).join('\n'), keep: p => this.proc(p) });
    return r.code === 0 ? { text: r.out } : { error: r.err || `${bin} vcd --codes: exit ${r.code}` };
  }
  async message(m) {
    // vscode/protocol.js: a message that is none of the page's (its type unknown, a key it needs not there) is said in the
    // log and, asked with an id, answered with the error; nothing below sees it
    const bad = PROTO.check(m);
    if (bad) { log(`${path.basename(this.file)}: ${bad}`); if (m && typeof m === 'object' && m.id) this.post({ id: m.id, error: bad }); return; }
    const reply = o => this.post(Object.assign({ id: m.id }, o));
    switch (m.type) {
      case 'source': return reply(await this.source());
      case 'bytes': return reply(await this.bytes());
      case 'codes': return reply(await this.codes(Array.isArray(m.codes) ? m.codes : []));
      case 'store': {   // a localStorage key of this dump (null: removed), kept in the workspace: the keys changed, not a snapshot
        if (typeof m.key !== 'string') return;
        this.changed.set(m.key, m.value == null ? null : String(m.value));
        clearTimeout(this.storeT); this.storeT = setTimeout(() => this.flush(), 300);
        return;
      }
      case 'save': return reply(await this.save(String(m.name || 'wavelens.out'), Buffer.from(String(m.b64 || ''), 'base64')));
      case 'pick': return reply(await this.pick(String(m.accept || ''), !!m.multiple, !!m.state));
      case 'state-kept': return this.stateKept();
      case 'state-read': return reply(await this.stateRead());
      case 'compare': return reply(await this.compare(Array.isArray(m.signals) ? m.signals.map(String) : [], +m.from, +m.to));
      case 'runs': return reply(await this.runs(m));
      case 'sources': return reply(await this.sources());
      case 'config': return reply({ config: cfgNow() });   // the tab loaded: the configuration now (one saved since its HTML was made)
      case 'clip': await vscode.env.clipboard.writeText(String(m.text ?? '')); return reply({ ok: true });
      case 'theme': chooseTheme(); return;   // the bar's ◐: the list of themes, as the command
      case 'result': { const w = this.wait.get(m.rid); if (w) { this.wait.delete(m.rid); w(m.results); } return; }
      case 'ready': case 'loaded':
        this.info = { shown: m.shown, total: m.total, title: m.title };
        if (m.type === 'ready') { this.ready = true; liveTo(this); }
        if (m.type === 'loaded') this.report(m);
        EVENTS.fire(Object.assign({}, m, { tab: this }));
        return;
      case 'dumperror': this.report(m); EVENTS.fire(Object.assign({}, m, { tab: this })); return;
      case 'log': log(`${path.basename(this.file)}: ${m.text}`); return;
      case 'configerror':   // your configuration broke the viewer: the tab went back to the defaults
        log(`${path.basename(this.file)}: the configuration: ${m.text}`);
        vscode.window.showErrorMessage(`WaveLens: the configuration does not work in the viewer (${m.text}): the defaults are applied; ` +
          'WaveLens: Open the configuration to mend it, or Reset it', 'Open', 'Reset')
          .then(a => (a === 'Open' ? cfgOpen() : a === 'Reset' ? cfgReset() : null));
        return;
      case 'page': for (const x of this.streams.values()) x.close(); this.streams.clear(); return;   // a page (again): its own streams
      case 'es-open': { const old = this.streams.get(m.sid); if (old) old.close(); return this.esOpen(m.sid, String(m.url)); }
      case 'es-close': { const s = this.streams.get(m.sid); this.streams.delete(m.sid); if (s) s.close(); return; }
      case 'http': return reply(await relay(this, String(m.url), m.body == null ? '' : String(m.body)));
    }
  }
  /* A read of the dump -> the output channel (its parameters, then each note as "path:line: level: text", a link there) and
     the Problems panel (a note on its line: a click opens the dump there). An FST's notes are about its VCD text: on the
     FST's first line, the line of the text with them. One it could not read: also a message with the way to the line. */
  report(m) {
    const fst = /\.fst$/i.test(this.file), text = fst && this.src ? this.src : this.file, name = path.basename(this.file);
    if (this.shown) {   // a run kept read as the waves (A): said in the log; the Problems panel stays the dump's
      log(`${this.shown.name} (${path.basename(this.shown.file)}) shown in ${name}'s tab` +
        (m.info ? `: ${dumpInfo(m.info, m.shown)}` : m.error ? `: ${m.error}` : ''));
      return;
    }
    const notes = (m.log || []).concat(m.error ? [{ level: 'error', text: m.error, line: m.line }] : []);
    if (m.info) log(`${name}: ${dumpInfo(m.info, m.shown)}`);
    else if (m.error) log(`${name}: not read`);
    for (const x of notes) OUT.appendLine(`  ${text}${x.line ? ':' + x.line : ''}: ${x.level}: ${x.text}`);
    const SEV = { error: vscode.DiagnosticSeverity.Error, warning: vscode.DiagnosticSeverity.Warning, info: vscode.DiagnosticSeverity.Information };
    DIAG.set(this.uri, notes.map(x => {
      const at = x.line && !fst ? x.line - 1 : 0, d = new vscode.Diagnostic(new vscode.Range(at, 0, at, 4096),
        x.text + (fst && x.line ? ` (line ${x.line} of its VCD text)` : ''), SEV[x.level] ?? vscode.DiagnosticSeverity.Warning);
      d.source = 'WaveLens';
      if (fst && x.line && this.src) d.relatedInformation = [new vscode.DiagnosticRelatedInformation(
        new vscode.Location(vscode.Uri.file(this.src), new vscode.Position(x.line - 1, 0)), 'the line in the VCD text of the FST')];
      return d;
    }));
    if (!m.error) { this.lastErr = null; return; }
    if (m.error === this.lastErr) return;   // the same error again (autoReload of a dump written broken again): the log and Problems say it
    this.lastErr = m.error;
    const go = m.line ? 'Open at the line' : null;
    vscode.window.showErrorMessage(`WaveLens: ${name}: ${m.error}`, ...[go, 'Show the log'].filter(Boolean)).then(c => {
      if (c === 'Show the log') OUT.show(true);
      else if (c === go) vscode.window.showTextDocument(vscode.Uri.file(text), { selection: new vscode.Range(m.line - 1, 0, m.line - 1, 0) });
    });
  }
  flush() {   // the keys this tab changed onto what is kept now (another window of the workspace may have written others)
    clearTimeout(this.storeT); this.storeT = null;
    if (!this.changed.size) return;
    const cur = Object.assign({}, CTX.workspaceState.get(this.storeKey) || {});
    for (const [k, v] of this.changed) if (v == null) delete cur[k]; else cur[k] = v;
    this.changed.clear();
    Promise.resolve(CTX.workspaceState.update(this.storeKey, cur)).catch(e => log(`the store of ${this.file}: ${e.message}`));
  }
  async save(name, data) {
    const to = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file(path.join(path.dirname(this.file), path.basename(name))),
      saveLabel: 'Save', title: `WaveLens: save ${name} on ${vscode.env.remoteName ? 'the host' : 'this machine'}` });
    if (!to) return { cancel: true };
    await vscode.workspace.fs.writeFile(to, data);
    return { path: to.fsPath };
  }
  // the last state of this workspace, whichever dump it was loaded on: Load… opens there, Reload (r) reads it, a new dump takes it
  stateUri() {
    const p = CTX.workspaceState.get(LAST_STATE);
    for (const x of p ? [p, path.dirname(p)] : []) if (fs.existsSync(x)) return vscode.Uri.file(x);
    return vscode.Uri.file(path.dirname(this.file));
  }
  async stateKept() {   // the file picked is loaded
    if (!this.picked) return;
    await CTX.workspaceState.update(LAST_STATE, this.picked);
    for (const tab of TABS) tab.post({ type: 'laststate', path: this.picked });
  }
  async stateRead() {
    const p = CTX.workspaceState.get(LAST_STATE);
    if (!p) return { error: 'no state loaded yet' };
    try { const st = await fs.promises.stat(p);
      return { name: path.basename(p), mtime: st.mtimeMs, b64: (await fs.promises.readFile(p)).toString('base64') }; }
    catch (e) { return { error: e.message }; }
  }
  async pick(accept, multiple, state = false) {
    const exts = [...new Set(accept.split(',').map(s => s.trim()).filter(s => s.startsWith('.')).map(s => s.slice(1)))];
    if (exts.includes('vcd')) exts.push('fst');
    const got = await vscode.window.showOpenDialog({ defaultUri: state ? this.stateUri() : vscode.Uri.file(path.dirname(this.file)), canSelectMany: multiple,
      filters: exts.length ? { [exts.join(', ')]: [...new Set(exts)], 'every file': ['*'] } : undefined });
    if (!got || !got.length) return { files: [] };
    if (state) this.picked = got[0].fsPath;
    if (exts.includes('fst') && /\.fst\b/.test(accept)) {   // Open… a dump: a tab of its own
      for (const u of got) await vscode.commands.executeCommand('vscode.openWith', u, VIEW);
      return { files: [] };
    }
    const files = [];
    for (const u of got) {
      const f = await vcdOf(u.fsPath), st = await fs.promises.stat(u.fsPath);
      files.push({ name: path.basename(u.fsPath), path: u.fsPath, mtime: st.mtimeMs, b64: (await fs.promises.readFile(f)).toString('base64') });
    }
    return { files };
  }
  // Compare…: a second dump picked on the host, sva diff of this one and it over the tab's signals and window (neither read
  // here: the CLI streams both) -> {result}: the WaveJSON extension "compare" the viewer takes (compareResult), as the
  // build makes it of a config's "compare" (tools/svabuild.py compare)
  async compare(signals, from, to) {
    const a = this.shown ? this.shown.file : this.file;   // A: the waves shown (a run kept, or the dump)
    const got = await vscode.window.showOpenDialog({ defaultUri: vscode.Uri.file(path.dirname(this.file)), canSelectMany: false,
      title: `Compare ${path.basename(a)} with`, filters: { 'vcd, fst': ['vcd', 'fst'], 'every file': ['*'] } });
    if (!got || !got.length) return {};
    const b = got[0].fsPath, bin = svaBin();
    // sva diff --page: the compare as the tab takes it, the run's values of the signals that differ in it (at most 32 MiB:
    // else cutError says why), the same shape as a config's "compare" (tools/svabuild.py)
    const args = ['diff', a, b, '--page', '--quiet', '--signals-from', '-'];
    if (isFinite(from)) args.push('--from', `${Math.round(from)}ps`);
    if (isFinite(to)) args.push('--to', `${Math.round(to)}ps`);
    log(`${path.basename(this.file)}: compare ${path.basename(a)} with ${b}`);
    const x = await spawnRun(bin, args, { input: signals.join('\n') + '\n', keep: p => this.proc(p) });
    const r = x.code === 0 || x.code === 1 ? { text: x.out } : { error: x.sig ? 'stopped' : x.err || `${bin} diff: exit ${x.code}` };
    if (r.error) { log(`${path.basename(this.file)}: compare: ${r.error}`); return { error: `compare: ${r.error}` }; }
    let d;
    try { d = cliJson(r.text); } catch (e) { return { error: `compare: sva diff wrote no JSON (${e.message})` }; }
    if (d.cutError) log(`${path.basename(this.file)}: the values of ${path.basename(b)} are not in the tab: ${d.cutError}`);
    return { result: d };
  }
  // the runs kept of this dump (the Runs panel): sva runs over .wavelens-runs beside it (wavelens.runsDir: another directory).
  // list -> {dir, runs, others, now: the dump's {name, mtime, bytes}, shown: the run shown (0: the dump)}; keep {name, tags,
  // comment} -> {run} (the dump as it is on the disk, an FST in the directory); set {run, …}; rm {run} (asked first) ->
  // {removed | cancelled}; open {run} -> {src, name, lazy}: a run's FST served as the tab's waves (A; 0: the dump of now);
  // diff {signals, from, to, case, against} -> sva runs diff's JSON (each run against A); compare {run, signals, from, to, case,
  // against} -> {result}: A (against: a run's id, 0 the dump; none: the waves shown) with B (run; 0: the dump) over that window
  // only, B's values of the signals that differ there (sva runs diff --page). keep {cases}: the page's spans with a label,
  // the run's test cases (none sent: the marks beside the dump, sva runs keep); case: the window's name, a run's case of that
  // name compared, wherever it is in the run (B offset to it, the shorter length)
  runsDir() {
    const set = vscode.workspace.getConfiguration('wavelens').get('runsDir');
    if (!set) return path.join(path.dirname(this.file), '.wavelens-runs');
    const ws = vscode.workspace.getWorkspaceFolder(vscode.Uri.file(this.file));
    return path.isAbsolute(set) ? set : path.join(ws ? ws.uri.fsPath : path.dirname(this.file), set);
  }
  // a window [from, to] of a dump as an FST of its own at out, its times from 0 (the runs' cut)
  cutOf(src, [from, to], out) { return this.sva(['fst', src, '--from', from, '--to', to, '--zero', '--out', out, '--quiet']); }
  sva(args, input, keep = p => p) { return spawnRun(svaBin(), args, { input: input || '', keep: p => this.proc(keep(p)) }); }
  async runs(m) {
    const dir = this.runsDir(), name = path.basename(this.file), json = r => { try { return cliJson(r.out); } catch (e) { return null; } };
    const fail = (r, what) => ({ error: r.err || `sva runs ${what}: exit ${r.code}` });
    const said = b => [...(typeof b.name === 'string' && b.name.trim() ? ['--name', b.name.trim()] : []),
      ...(Array.isArray(b.tags) ? ['--tags', b.tags.map(String).join(',')] : []), ...(typeof b.comment === 'string' ? ['--comment', b.comment] : [])];
    // a window of the page (ps): from before to -> ['Nps', 'Nps'], else null
    const win = x => (isFinite(x.from) && isFinite(x.to) && Math.round(x.from) >= 0 && Math.round(x.to) > Math.round(x.from) ?
      [`${Math.round(x.from)}ps`, `${Math.round(x.to)}ps`] : null);
    const id = String(parseInt(m.run, 10)), nowOr = x => (x === 'now' || !(parseInt(x, 10) > 0) ? 'now' : String(parseInt(x, 10)));
    // A: the run asked (against), else the one shown
    const against = () => (m.against != null ? nowOr(m.against) : this.shown ? String(this.shown.id) : 'now');
    this.watchRuns(dir);
    // a compare (or Δ all) asked while another runs: the older one's processes killed, its answer "stopped"
    const own = () => { if (this.runsBusy) this.runsBusy.forEach(p => p.kill()); const set = this.runsBusy = new Set();
      return p => { set.add(p); p.on('close', () => set.delete(p)); return p; }; };
    switch (m.op) {
      case 'list': {   // this dump's runs (by its file name), the ones of other dumps counted
        const r = await this.sva(['runs', 'list', this.file, '--dir', dir, '--json']), d = json(r);
        let st = null; try { st = await fs.promises.stat(this.file); } catch (e) { /* gone meanwhile */ }
        const now = { name, mtime: st ? st.mtimeMs : null, bytes: st ? st.size : null };
        return r.code === 0 && d ? { dir, runs: d.runs || [], others: d.others || 0, now, shown: this.shown ? this.shown.id : 0 } : fail(r, 'list');
      }
      case 'open': {   // A: a run's waves served as the dump's are (converted once: its FST does not change); 0 the dump of now
        if (!(parseInt(m.run, 10) > 0)) return this.source();
        const l = json(await this.sva(['runs', 'list', '--dir', dir, '--json'])), run = l && (l.runs || []).find(x => String(x.id) === id);
        if (!run) return { error: `no run #${id} in ${dir}` };
        const file = path.join(dir, run.file), nm = `#${run.id} ${run.name}`;
        let o; try { o = await this.srcOf(file, nm); } catch (e) { return { error: `${nm}: ${e.message}` }; }
        this.shown = { id: run.id, file, name: nm };
        log(`${name}: ${nm} (${run.file}) shown in the tab`);
        return o;
      }
      case 'cancel': if (this.runsBusy) this.runsBusy.forEach(p => p.kill()); return { ok: true };
      case 'keep': {   // the dump of now; with from, to: a slice of the waves shown (the dump or a run), its times from 0
        const sl = win(m), src = sl && this.shown ? this.shown.file : this.file;
        if (!sl && (m.from != null || m.to != null)) return { error: 'a slice: from and to, from before to' };
        log(`${name}: ${sl ? `a slice ${sl.join(' … ')} of ${this.shown ? this.shown.name : 'the dump'}` : 'the dump'} kept as a run in ${dir}`);
        const cases = !sl && Array.isArray(m.cases) && m.cases.length ? m.cases.filter(c => c && typeof c.label === 'string' && isFinite(c.from) &&
          isFinite(c.to)).map(c => ({ label: c.label, from: Math.round(c.from), to: Math.round(c.to) })) : null;
        const r = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
          title: `WaveLens: keeping ${sl ? 'a slice of ' : ''}${name} as a run…` },
        () => this.sva(['runs', 'keep', src, '--dir', dir, ...said(m), ...(sl ? ['--from', sl[0], '--to', sl[1]] : []), ...(cases ? ['--cases', '-'] : []),
          '--json'], cases ? JSON.stringify(cases) : '')), d = json(r);
        return r.code === 0 && d ? { run: d } : fail(r, 'keep');
      }
      case 'cut': {   // a window of the waves shown as an FST of its own, its times from 0, where the save dialog says
        const sl = win(m); if (!sl) return { error: 'cut: from and to, from before to' };
        const src = this.shown ? this.shown.file : this.file, stem = path.basename(this.file).replace(/\.[^.]*$/, '');
        const nm = `${stem}.${sl.map(t => t.replace(/ps$/, '')).join('-')}ps.fst`;
        const to = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file(path.join(path.dirname(this.file), nm)), saveLabel: 'Save',
          filters: { FST: ['fst'] }, title: `WaveLens: the window ${sl.join(' … ')} as an FST (its times from 0)` });
        if (!to) return { cancel: true };
        const r = await this.cutOf(src, sl, to.fsPath);
        if (r.code !== 0) return fail(r, 'fst');
        log(`${name}: ${sl.join(' … ')} saved as ${to.fsPath}`);
        return { path: to.fsPath };
      }
      case 'set': {
        const r = await this.sva(['runs', 'set', id, '--dir', dir, ...said(m), '--json']), d = json(r);
        return r.code === 0 && d ? { run: d } : fail(r, 'set');
      }
      case 'rm': {
        const l = json(await this.sva(['runs', 'list', '--dir', dir, '--json'])), run = l && (l.runs || []).find(x => String(x.id) === id);
        if (!run) return { error: `no run #${id}` };
        const yes = await vscode.window.showWarningMessage(`Remove the run #${id} ${run.name} and its file ${run.file}?`, { modal: true }, 'Remove');
        if (yes !== 'Remove') return { cancelled: true };
        const r = await this.sva(['runs', 'rm', id, '--dir', dir, '--json']);
        return r.code === 0 ? { removed: run } : fail(r, 'rm');
      }
      case 'diff': {
        const args = ['runs', 'diff', this.file, '--dir', dir, '--json', '--against', against(), '--signals-from', '-'];
        if (isFinite(m.from)) args.push('--from', `${Math.round(m.from)}ps`);
        if (isFinite(m.to)) args.push('--to', `${Math.round(m.to)}ps`);
        if (typeof m.case === 'string' && m.case) args.push('--case', m.case);
        const r = await this.sva(args, (Array.isArray(m.signals) ? m.signals.map(String) : []).join('\n') + '\n', own()), d = json(r);
        return d && d.runs ? d : r.sig ? { error: 'stopped' } : fail(r, 'diff');
      }
      case 'compare': {   // A with B over the window in one sva runs diff --page (a case: B's of that name, offset to it)
        const b = nowOr(m.run), a = against();
        if (a === b) return { error: 'A and B are the same run' };
        const args = ['runs', 'diff', this.file, '--dir', dir, '--run', b, '--against', a, '--page', '--quiet', '--signals-from', '-'];
        if (isFinite(m.from)) args.push('--from', `${Math.round(m.from)}ps`);
        if (isFinite(m.to)) args.push('--to', `${Math.round(m.to)}ps`);
        if (typeof m.case === 'string' && m.case) args.push('--case', m.case);
        log(`${name}: compare ${a === 'now' ? 'the dump' : '#' + a} with ${b === 'now' ? 'the dump' : '#' + b}`);
        const r = await this.sva(args, (Array.isArray(m.signals) ? m.signals.map(String) : []).join('\n') + '\n', own());
        if (r.sig) return { error: 'stopped' };
        if (r.code !== 0 && r.code !== 1) return fail(r, 'diff --page');
        const d = json(r);
        if (!d) return { error: 'sva runs diff --page wrote no JSON' };
        if (d.cutError) log(`${name}: the values of B are not in the tab: ${d.cutError}`);
        return { result: d };
      }
    }
    return { error: `runs: no operation ${m.op}` };
  }
  // runs.json of the runs' directory watched once asked (a keep in a shell, an agent's wave_runs): the tab told (runs-changed)
  watchRuns(dir) {
    const f = path.join(dir, 'runs.json');
    if (this.runsWatched === f) return;
    if (this.runsWatched) fs.unwatchFile(this.runsWatched, this.onRuns);
    this.runsWatched = f;
    this.onRuns = (cur, prev) => { if (cur.mtimeMs !== prev.mtimeMs || cur.size !== prev.size) this.post({ type: 'runs-changed' }); };
    fs.watchFile(f, { interval: 1000 }, this.onRuns);
  }
  // the design's types beside the dump (tb.vcd -> tb.types.json: tools/questa/wavelens_types.tcl, svtypes.py verilator), by
  // path; without them the workspace's SystemVerilog sources (wavelens.sources): their enum names label a VCD's state buses
  async sources() {
    const tf = typesFile(this.file);
    let types = null;
    try { types = await fs.promises.readFile(tf, 'utf8'); } catch (e) { /* none */ }
    if (types != null) {
      const say = `the types of ${path.basename(tf)} (by path; wavelens.sources not used)`;
      if (say !== this.srcSaid) log(`${path.basename(this.file)}: ${say}`);
      this.srcSaid = say;
      return { types, typesName: path.basename(tf), texts: [] };
    }
    const s = await workspaceSources();
    const say = `${s.texts.length} of ${s.files} SystemVerilog sources: ${s.types} enum / packed-struct types` + (s.left ? `, ${s.left} left out (${s.why})` : '');
    if (say !== this.srcSaid) log(`${path.basename(this.file)}: ${say} (wavelens.sources)`);
    this.srcSaid = say;
    return { texts: s.texts };
  }
  // the dump changed on the disk: once its size and time have stood still for a second (the simulator done writing)
  watch() {
    let last = null;
    const quiet = cur => {   // the size and time as they were a moment ago: still writing when they moved
      clearTimeout(this.changeT);
      this.changeT = setTimeout(() => fs.stat(this.file, (err, now) => {
        if (err || !now.size) return;
        if (now.size !== cur.size || now.mtimeMs !== cur.mtimeMs) { quiet(now); return; }
        const sig = `${now.size}:${now.mtimeMs}`; if (sig === last) return; last = sig;
        this.post({ type: 'changed', auto: !!vscode.workspace.getConfiguration('wavelens').get('autoReload') });
      }), 1200);
    };
    this.onStat = (cur, prev) => { if (cur.mtimeMs !== prev.mtimeMs || cur.size !== prev.size) quiet(cur); };
    fs.watchFile(this.file, { interval: 1000 }, this.onStat);   // polling: NFS homes of a Remote-SSH host send no events
    this.onTypes = (cur, prev) => {   // the types beside it written (or made, or removed): a read again, as for the dump
      if (cur.mtimeMs === prev.mtimeMs && cur.size === prev.size) return;
      clearTimeout(this.typesT);
      this.typesT = setTimeout(() => this.post({ type: 'changed', auto: !!vscode.workspace.getConfiguration('wavelens').get('autoReload') }), 1200);
    };
    fs.watchFile(typesFile(this.file), { interval: 1000 }, this.onTypes);
  }
  run(ops, timeout = 20000) {   // the viewer's commands (view.run) -> their results (the tests; later the agent without a bridge)
    const rid = ++this.rid;
    return new Promise((ok, no) => {
      const t = setTimeout(() => { this.wait.delete(rid); no(new Error('the tab did not answer')); }, timeout);
      this.wait.set(rid, r => { clearTimeout(t); ok(r); });
      this.post({ type: 'run', rid, ops });
    });
  }
  // an EventSource of the page, opened here: its events posted to the page, reconnected as a browser does; only to the
  // bridge this tab was given (its port and key), only GET /events
  esOpen(sid, url) {
    if (!liveUrlOk(this, url, 'events')) { this.post({ type: 'es', sid, event: 'error' }); return; }
    const s = { closed: false, req: null, close() { this.closed = true; if (this.req) this.req.destroy(); } };
    this.streams.set(sid, s);
    const go = () => {
      if (s.closed) return;
      let done = false;
      const again = () => { if (done || s.closed) return; done = true; this.post({ type: 'es', sid, event: 'error' }); setTimeout(go, 2000); };
      s.req = http.get(url, { headers: { Accept: 'text/event-stream' } }, res => {
        if (res.statusCode !== 200) { res.resume(); again(); return; }
        this.post({ type: 'es', sid, event: 'open' });
        let buf = '', ev = 'message', data = [];
        res.setEncoding('utf8');
        res.on('data', chunk => {
          buf += chunk; let i;
          while ((i = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, i).replace(/\r$/, ''); buf = buf.slice(i + 1);
            if (line === '') { if (data.length) this.post({ type: 'es', sid, event: ev, data: data.join('\n') }); ev = 'message'; data = []; }
            else if (line.startsWith('event:')) ev = line.slice(6).trim();
            else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
          }
          if (buf.length > 64 << 20) res.destroy();   // no line end in 64 MB: not the bridge
        });
        res.on('end', again); res.on('error', again); res.on('close', again); res.on('aborted', again);
      });
      s.req.on('error', again);
    };
    go();
  }
  dispose() {
    TABS.delete(this); fs.unwatchFile(this.file, this.onStat); fs.unwatchFile(typesFile(this.file), this.onTypes);
    if (this.runsWatched) fs.unwatchFile(this.runsWatched, this.onRuns);
    clearTimeout(this.changeT); clearTimeout(this.typesT);
    try { DIAG.delete(this.uri); } catch (e) { /* disposed: the window closes */ }
    this.flush();
    for (const s of this.streams.values()) s.close();
    this.streams.clear();
    for (const p of this.procs) p.kill();
  }
}

// the parameters of a dump read: "12.4 MB · Icarus Verilog · 1ps · 0 … 1.2 ms · 3 scopes · 120 of 140 signals · 51 230 changes"
function dumpInfo(i, shown) {
  const mb = i.size >= 1 << 20 ? `${(i.size / (1 << 20)).toFixed(1)} MB` : `${Math.ceil(i.size / 1024)} kB`;
  const t = ps => { if (!ps) return '0'; const u = [['s', 1e12], ['ms', 1e9], ['us', 1e6], ['ns', 1e3], ['ps', 1], ['fs', 1e-3]].find(x => Math.abs(ps) >= x[1]) ||
    ['fs', 1e-3]; return `${+(ps / u[1]).toPrecision(4)} ${u[0]}`; };
  return [mb, i.version, i.date, i.timescale ? `timescale ${i.timescale}` : 'no $timescale (1 ps)', `${t(i.t0)} … ${t(i.t1)}`,
    `${i.scopes} scope${i.scopes === 1 ? '' : 's'}`, `${i.shown ?? shown} of ${i.signals} signals`, `${i.changes} value changes`].filter(Boolean).join(' · ');
}

/* ---------------- the theme: wavelens.theme, chosen with a preview on the open tabs ---------------- */
const THEMES = [
  ['auto', 'Follow VS Code', 'the viewer\'s light or dark by the kind of VS Code\'s theme'],
  ['vscode', 'VS Code\'s colours', 'the background, text, lines and accent of VS Code\'s theme'],
  ['light', 'Light', 'grey paper that does not glare'],
  ['white', 'White', 'pure white, black traces: for print and slides'],
  ['dark', 'Dark', 'the viewer\'s dark'],
];
const themeOf = () => vscode.workspace.getConfiguration('wavelens').get('theme') || 'auto';
// the build of this extension for the bar's version line (WAVELENS_BUILD): a VSIX's from its package.json (mkvsix.py),
// else its checkout's branch and commit (vscode/ of the repository, make vscode-e2e), asked once
let BUILD;
function buildOf() {
  if (BUILD !== undefined) return BUILD;
  const own = CTX.extension && CTX.extension.packageJSON && CTX.extension.packageJSON.wavelensBuild;
  if (own) return (BUILD = own);
  const git = a => { try { return cp.execFileSync('git', ['-C', CTX.extensionPath, ...a], { encoding: 'utf8', timeout: 5000,
    stdio: ['ignore', 'pipe', 'ignore'] }).trim(); } catch (e) { return ''; } };
  const commit = git(['rev-parse', '--short', 'HEAD']);
  BUILD = commit ? { branch: git(['rev-parse', '--abbrev-ref', 'HEAD']), commit, dirty: !!git(['status', '--porcelain', '--untracked-files=no']),
    tag: git(['describe', '--tags', '--exact-match']) || undefined, by: 'the extension of the repository' } : null;
  return BUILD;
}
const themeAll = t => { for (const tab of TABS) tab.post({ type: 'theme', theme: t }); };
async function chooseTheme() {
  const now = themeOf(), qp = vscode.window.createQuickPick();
  qp.title = 'WaveLens: the theme of the waves'; qp.placeholder = 'the open tabs show it as you move';
  qp.items = THEMES.map(([id, label, detail]) => ({ id, label: label + (id === now ? '  ✓' : ''), detail }));
  qp.activeItems = qp.items.filter(i => i.id === now);
  let picked = null;
  qp.onDidChangeActive(a => a[0] && themeAll(a[0].id));
  qp.onDidAccept(() => { picked = qp.selectedItems[0] || qp.activeItems[0]; qp.hide(); });
  const hidden = new Promise(ok => qp.onDidHide(ok));
  qp.show();
  try { await hidden; } finally { qp.dispose(); }
  if (!picked) { themeAll(now); return; }   // Esc: as it was
  // the workspace's own setting when it has one, else the user's
  const inspect = vscode.workspace.getConfiguration('wavelens').inspect('theme');
  const where = inspect && inspect.workspaceValue !== undefined ? vscode.ConfigurationTarget.Workspace : vscode.ConfigurationTarget.Global;
  await vscode.workspace.getConfiguration('wavelens').update('theme', picked.id, where);
}

/* ---------------- the design's types through Verilator (vscode/svtypes.js): <dump>.types.json beside the dump ---------------- */
// The arguments Verilator takes (a .f file of the workspace, or typed: files, -f, +incdir+, +define+, -G…) and the top
// module (the dump's top scope by default), asked once per dump and kept; the file written next to the dump, which the
// tab reads at once (its watcher). opts {args, top}: no questions (the tests)
const SVT = require('./svtypes.js');
function topOf(file) {   // the dump's first $scope module (a VCD's head), '' for an FST
  try { const fd = fs.openSync(file, 'r'), b = Buffer.alloc(65536), n = fs.readSync(fd, b, 0, b.length, 0); fs.closeSync(fd);
    const m = /\$scope\s+module\s+(\S+)/.exec(b.toString('latin1', 0, n)); return m ? m[1] : ''; } catch (e) { return ''; }
}
async function verilatorTypes(tab, opts = {}) {
  if (!tab) { vscode.window.showInformationMessage('WaveLens: open a dump first (its types go beside it)'); return null; }
  const key = 'verilator:' + tab.file, was = CTX.workspaceState.get(key) || {};
  let args = opts.args, top = opts.top;
  if (!args) {
    const fl = (await vscode.workspace.findFiles('**/*.f', '**/node_modules/**', 50)).map(u => u.fsPath).sort();
    const items = [...(was.args ? [{ label: was.args.join(' '), description: 'as the last time', args: was.args }] : []),
      ...fl.map(f => ({ label: '-f ' + vscode.workspace.asRelativePath(f), description: 'a file list of the workspace', args: ['-f', f] })),
      { label: 'Type the arguments…', description: 'files, -f list.f, +incdir+…, +define+…, -GNAME=…', typed: true }];
    const pick = await vscode.window.showQuickPick(items, { title: 'WaveLens: the design for Verilator (its types by path)',
      placeHolder: 'the arguments you give Verilator for this design' });
    if (!pick) return null;
    if (pick.typed) {
      const t = await vscode.window.showInputBox({ title: 'WaveLens: the arguments for verilator --json-only', value: (was.args || []).join(' '),
        prompt: 'as on its command line: rtl/pkg.sv rtl/*.sv +incdir+rtl -GDEPTH=16 (paths from the workspace\'s folder; * ? in a file\'s name)' });
      if (!t || !t.trim()) return null;
      args = t.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g).map(x => x.replace(/^(["'])(.*)\1$/, '$2'));
    } else args = pick.args;
  }
  if (top == null) {
    top = await vscode.window.showInputBox({ title: 'WaveLens: the top module', value: was.top || topOf(tab.file),
      prompt: 'the module the dump starts at (verilator --top-module); empty: Verilator\'s choice' });
    if (top == null) return null;
  }
  await CTX.workspaceState.update(key, { args, top });
  const out = typesFile(tab.file), exe = vscode.workspace.getConfiguration('wavelens').get('verilator') || 'verilator';
  // Verilator runs in the workspace's folder: the paths of the arguments and of a .f file's lines are from there
  const cwd = (vscode.workspace.workspaceFolders || [])[0] ? vscode.workspace.workspaceFolders[0].uri.fsPath : path.dirname(tab.file);
  try {
    const doc = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification,
      title: `WaveLens: verilator --json-only (${path.basename(out)})` }, () => SVT.make(args, top || null, exe, undefined, cwd));
    fs.writeFileSync(out, SVT.text(doc));
    const ne = Object.values(doc.signals).filter(e => e.enum).length;
    log(`${path.basename(out)}: ${ne} enum and ${Object.keys(doc.signals).length - ne} struct signals (${doc.producer.tool})`);
    for (const n of doc.notes) log(`${path.basename(out)}: ${n}`);
    if (!opts.args) vscode.window.showInformationMessage(`WaveLens: ${path.basename(out)}: ${ne} enum and ${Object.keys(doc.signals).length - ne} struct ` +
      'signals by path; the tab reads it');
    tab.post({ type: 'changed', auto: true });   // read at once (asked for: whatever wavelens.autoReload says)
    return { out, signals: Object.keys(doc.signals).length, notes: doc.notes };
  } catch (e) { log(`verilator types: ${e.message}`); if (!opts.args) vscode.window.showErrorMessage('WaveLens: ' + e.message.split('\n')[0]); throw e; }
}

/* ---------------- the agent's live link (tools/wavemcp.py) ---------------- */
// The bridge of an agent's wavemcp.py listens on 127.0.0.1 of this host and writes ~/.cache/wavelens/live/<port>.json
// (port, pid, host) while it runs; the key is the user's ~/.cache/wavelens/live-token. A tab is given "port:key"
// (WaveLens.live): the newest bridge, or the one that asked to open it; its EventSource and POSTs to that bridge, and to
// nothing else, come here (media/host.js). view_live with a dump writes open-*.json there: the window that has the file
// in its folders opens it first, another after a few seconds; the request goes once its tab is open.
const LIVE_PATHS = { events: 'GET', hello: 'POST', reply: 'POST', bye: 'POST' };
const liveOn = () => !!vscode.workspace.getConfiguration('wavelens').get('live');
function liveUrlOk(tab, url, want) {
  try {
    const u = new URL(url), name = u.pathname.slice(1), [port, token] = (tab.link || '').split(/:(.*)/s);
    return liveOn() && u.protocol === 'http:' && /^(127\.0\.0\.1|localhost)$/.test(u.hostname) && !u.username && !u.password &&
      u.port === port && BRIDGES.has(+port) && u.searchParams.get('token') === token && LIVE_PATHS[name] && (!want || name === want);
  } catch (e) { return false; }
}
function relay(tab, url, body) {   // a POST of the page (hello, reply, bye) to its bridge -> {status, text}
  if (!liveUrlOk(tab, url) || LIVE_PATHS[new URL(url).pathname.slice(1)] !== 'POST') return Promise.resolve({ status: 0 });
  return new Promise(ok => {
    const data = Buffer.from(body, 'utf8');   // a length, not chunks: the bridge reads Content-Length
    const rq = http.request(url, { method: 'POST', headers: { 'Content-Type': 'text/plain', 'Content-Length': data.length } }, res => {
      let text = ''; res.setEncoding('utf8');
      res.on('data', d => { text += d; if (text.length > 1 << 20) res.destroy(); });
      res.on('end', () => ok({ status: res.statusCode, text })); res.on('error', () => ok({ status: 0 }));
    });
    rq.on('error', () => ok({ status: 0 })); rq.setTimeout(15000, () => rq.destroy());
    rq.end(data);
  });
}
let BRIDGES = new Map(), TOKEN = null, LIVE_NOW = null;   // port -> its note; the key; "port:key" of the newest
function liveScan() {   // the bridges of this user on this host that run
  const dir = path.join(cacheDir(), 'live'), got = new Map();
  if (liveOn()) {
    for (const f of (() => { try { return fs.readdirSync(dir); } catch (e) { return []; } })()) {
      if (!/^\d+\.json$/.test(f)) continue;
      try {
        const b = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
        if (b.host && b.host !== os.hostname()) continue;   // a home shared by several hosts
        process.kill(b.pid, 0);   // alive (else it throws)
        got.set(+b.port, b);
      } catch (e) { /* gone */ }
    }
  }
  BRIDGES = got;
  try { TOKEN = got.size ? fs.readFileSync(path.join(cacheDir(), 'live-token'), 'utf8').trim() || null : null; } catch (e) { TOKEN = null; }
  const best = [...got.values()].sort((a, b) => (b.started || 0) - (a.started || 0))[0];
  return best && TOKEN ? `${best.port}:${TOKEN}` : null;
}
function linkOf(tab) {   // the bridge that opened the tab while it runs, else the newest
  return tab.pin && BRIDGES.has(+tab.pin) && TOKEN ? `${tab.pin}:${TOKEN}` : LIVE_NOW;
}
function liveTo(tab) {
  const link = linkOf(tab);
  if (link === tab.link && tab.sent) return;
  tab.link = link; tab.sent = true;
  if (!link) for (const st of tab.streams.values()) st.close();
  tab.post({ type: 'live', link });
}
function liveCheck() {
  const now = liveScan();
  if (now !== LIVE_NOW) { LIVE_NOW = now; log(now ? `the agent's live link: 127.0.0.1:${now.split(':')[0]}` : 'no agent\'s live link'); }
  for (const t of TABS) if (t.ready) liveTo(t);
  if (liveOn()) liveOpens().catch(e => log('open: ' + e.message));
}
let OPENING = false;
async function liveOpens() {   // view_live {page: a dump, open: true}: the tab opened here
  if (OPENING) return;
  OPENING = true;
  try {
    const dir = path.join(cacheDir(), 'live');
    let fsx; try { fsx = fs.readdirSync(dir).filter(f => /^open-[\w.-]+\.json$/.test(f)); } catch (e) { return; }
    for (const f of fsx) {
      const p = path.join(dir, f);
      let req; try { req = JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { continue; }
      if (!req || typeof req.path !== 'string') continue;
      const age = Date.now() - (req.at || 0);
      if (age > 120e3) { fs.unlink(p, () => {}); continue; }   // nobody took it
      if (req.host && req.host !== os.hostname()) continue;
      const mine = (vscode.workspace.workspaceFolders || []).some(w => (req.path + '/').startsWith(w.uri.fsPath.replace(/\/?$/, '/')));
      if (!mine && age < 4000) continue;   // a window with the file in its folders first
      const claimed = `${p}.${process.pid}`;
      try { fs.renameSync(p, claimed); } catch (e) { continue; }   // another window took it
      log(`the agent opens ${req.path}`);
      try {
        await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(req.path), VIEW);
        const tab = [...TABS].find(t => t.file === req.path);
        if (tab && req.port) { tab.pin = String(req.port); if (tab.ready) liveTo(tab); }
        fs.unlink(claimed, () => {});
      } catch (e) {
        log(`cannot open ${req.path}: ${e.message}`);
        fs.rename(claimed, p, () => {});   // for another window
      }
    }
  } finally { OPENING = false; }
}

/* ---------------- links from a log or the terminal (links.js): a time and a signal -> the dump's tab, goto ---------------- */
const LINKS = require('./links.js');

/* ---------------- your configuration of the viewer (userconfig.js): a JSONC file, checked and applied when saved ---------------- */
const UCFG = require('./userconfig.js');
const configFile = () => path.join(CTX.globalStorageUri.fsPath, 'wavelens.config.jsonc');
let cfgGood = null;   // the configuration the tabs have: the last one that read (a file that does not read leaves it)
// wavelens.config.js of the viewer the tabs load: its values (the defaults here) and its comments
function cfgDefaults() {
  const js = fs.readFileSync(path.join(roots().wavelens, 'wavelens.config.js'), 'utf8'), win = {};
  require('vm').runInNewContext(js, { window: win }, { timeout: 1000 });
  return { values: win.WAVELENS_CONFIG || {}, notes: UCFG.notesOf(js) };
}
// the file read and checked -> {config} (what applies) and the marks in the editor (Problems); a file that does not read: null
function cfgRead(text) {
  const d = cfgDefaults(), r = UCFG.parse(text), uri = vscode.Uri.file(configFile());
  const at = (line, col, len) => new vscode.Range(line, col, line, col + Math.max(1, len));
  if (r.error) {
    DIAG.set(uri, [Object.assign(new vscode.Diagnostic(at(r.line - 1, r.col - 1, 1), `not JSON: ${r.error} — not applied, the tabs keep the last one that read`,
      vscode.DiagnosticSeverity.Error), { source: 'WaveLens' })]);
    return null;
  }
  const c = UCFG.check(r.value, d.values);
  // a key's mark where the parser found it (the last of a key given twice: its value is the one read), not a comment naming it
  DIAG.set(uri, c.problems.map(p => { const k = p.key == null ? null : r.keys.filter(x => x.key === p.key).pop();
    const line = k ? k.line - 1 : 0, col = k ? k.col - 1 : 0;
    return Object.assign(new vscode.Diagnostic(at(line, col, p.key ? p.key.length + 2 : 1), `${p.message} — left out`, vscode.DiagnosticSeverity.Warning),
      { source: 'WaveLens' }); }));
  return { config: UCFG.effective(d.values, c.config), problems: c.problems, own: Object.keys(c.config).length };
}
// the configuration every tab starts with: the file's when it reads, else none (the viewer's own)
function cfgNow() {
  if (cfgGood) return cfgGood;
  try { const r = cfgRead(fs.readFileSync(configFile(), 'utf8')); if (r) cfgGood = r.config; } catch (e) { /* no file yet: the defaults */ }
  return cfgGood;
}
// saved: checked, applied to every tab (what is wrong said, the rest applied)
function cfgApply(text, quiet = false) {
  let r;
  try { r = cfgRead(text); } catch (e) {
    log(`the configuration: ${e.message}`); vscode.window.showErrorMessage(`WaveLens: the configuration: ${e.message}`); return; }
  if (!r) { if (!quiet) vscode.window.showErrorMessage('WaveLens: the configuration is not JSON (see the mark in it): not applied, the tabs keep the last one');
    return; }
  cfgGood = r.config;
  for (const tab of TABS) tab.post({ type: 'config', config: r.config });
  const said = `WaveLens: the configuration applied to ${TABS.size} tab${TABS.size === 1 ? '' : 's'} (${r.own} of your values)` +
    (r.problems.length ? `; ${r.problems.length} left out: ${r.problems.map(p => p.key || 'the file').join(', ')} (marked in the file)` : '');
  log(said.replace(/^WaveLens: /, ''));
  if (!quiet) (r.problems.length ? vscode.window.showWarningMessage : vscode.window.showInformationMessage)(said);
}
// Open the configuration: the file (made of the defaults the first time) in an editor beside the tab
async function cfgOpen() {
  const f = configFile();
  if (!exists(f)) {
    const d = cfgDefaults(); await fs.promises.mkdir(path.dirname(f), { recursive: true }); await fs.promises.writeFile(f, UCFG.template(d.values, d.notes)); }
  const doc = await vscode.workspace.openTextDocument(f);
  await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.Beside, preview: false });
  try { cfgRead(doc.getText()); } catch (e) { /* marks only */ }
}
// Reset to the defaults: the file written anew (asked first), applied
async function cfgReset() {
  const yes = 'Reset';
  const ask = 'WaveLens: the configuration back to the defaults? Your values in it are lost.';
  if (await vscode.window.showWarningMessage(ask, { modal: true }, yes) !== yes) return;
  const d = cfgDefaults(), text = UCFG.template(d.values, d.notes), f = configFile();
  await fs.promises.mkdir(path.dirname(f), { recursive: true }); await fs.promises.writeFile(f, text);
  cfgApply(text, true);
  vscode.window.showInformationMessage('WaveLens: the configuration is the defaults again (applied to every tab)');
}
let linksSaid = '';   // the bad patterns of wavelens.logLinks said once (again when they change)
const ownLinks = () => { const l = vscode.workspace.getConfiguration('wavelens').get('logLinks'), list = Array.isArray(l) ? l : [];
  const bad = LINKS.badPatterns(list), key = bad.join('\n');
  if (key && key !== linksSaid) log(`wavelens.logLinks: left out: ${bad.join('; ')}`);
  linksSaid = key; return list; };
const linkTip = l => (l.hash ? `WaveLens: open ${path.basename(l.dump)} at ${l.hash}` :
  `WaveLens: go to ${+(l.ps / 1000).toPrecision(12)} ns${l.sig ? ' · ' + l.sig : ''}`);
// the tab a link goes to: the dump it names (opened if it is not), else the tab in sight, else the one used last, else one of the
// dumps opened in this workspace before, picked
async function linkTab(l, base) {
  const wait = async file => { for (let i = 0; i < 100; i++) { const t = [...TABS].find(x => x.file === file); if (t && t.ready) return t;
    await new Promise(r => setTimeout(r, 100)); } return null; };
  let file = l.dump ? (path.isAbsolute(l.dump) ? l.dump : path.resolve(base || ((vscode.workspace.workspaceFolders || [])[0] || { uri: { fsPath: os.homedir() } }).uri.fsPath, l.dump)) : null;
  if (file && !fs.existsSync(file)) { const w = (vscode.workspace.workspaceFolders || []).map(f => path.join(f.uri.fsPath, l.dump)).find(f => fs.existsSync(f));
    if (!w) { vscode.window.showWarningMessage(`WaveLens: no dump ${l.dump}`); return null; } file = w; }
  if (!file) {
    const t = [...TABS].find(x => x.panel.active) || [...TABS].find(x => x.panel.visible) || [...TABS].pop();
    if (t) return t;
    const seen = CTX.workspaceState.keys().filter(k => k.startsWith('store:')).map(k => vscode.Uri.parse(k.slice(6)).fsPath).filter(f => fs.existsSync(f));
    if (!seen.length) { vscode.window.showInformationMessage('WaveLens: no dump open: open one in WaveLens first'); return null; }
    file = seen.length === 1 ? seen[0] : await vscode.window.showQuickPick(seen, { placeHolder: `Open which dump at ${linkTip(l).slice(10)}?` });
    if (!file) return null;
  }
  const open = [...TABS].find(x => x.file === file);
  if (!open) await vscode.commands.executeCommand('vscode.openWith', vscode.Uri.file(file), VIEW);
  return wait(file);
}
async function followLink(l, base) {
  const t = await linkTab(l, base); if (!t) return;
  t.panel.reveal();
  const r = (await t.run([{ op: 'goto', ...LINKS.gotoOf(l) }]))[0] || {};
  if (r.error) vscode.window.showWarningMessage(`WaveLens: ${r.error}`);
}

/* ---------------- activation ---------------- */
function activate(ctx) {
  CTX = ctx; OUT = vscode.window.createOutputChannel('WaveLens'); DIAG = vscode.languages.createDiagnosticCollection('wavelens');
  ctx.subscriptions.push(OUT, EVENTS, DIAG);
  ctx.subscriptions.push(vscode.window.registerCustomEditorProvider(VIEW, {
    openCustomDocument: uri => ({ uri, dispose() {} }),
    resolveCustomEditor: (doc, panel) => { new Tab(doc.uri, panel); },
  }, { webviewOptions: { retainContextWhenHidden: true }, supportsMultipleEditorsPerDocument: false }));
  const active = () => [...TABS].find(t => t.panel.active) || [...TABS].find(t => t.panel.visible);
  ctx.subscriptions.push(
    vscode.commands.registerCommand('wavelens.open', uri => {
      uri = uri || (vscode.window.activeTextEditor && vscode.window.activeTextEditor.document.uri);
      if (uri) return vscode.commands.executeCommand('vscode.openWith', uri, VIEW);
      return vscode.window.showOpenDialog({ filters: { dumps: ['vcd', 'fst'], 'pieces of waves': ['wavelens.json'] } })
        .then(u => u && u[0] && vscode.commands.executeCommand('vscode.openWith', u[0], VIEW));
    }),
    vscode.commands.registerCommand('wavelens.reload', () => { const t = active(); if (t) t.post({ type: 'reload' }); }),
    vscode.commands.registerCommand('wavelens.runs', () => { const t = active(); if (t) t.post({ type: 'runs-panel' });
      else vscode.window.showInformationMessage('WaveLens: open a dump first (its tab has the runs kept of it)'); }),
    vscode.commands.registerCommand('wavelens.theme', chooseTheme),
    vscode.commands.registerCommand('wavelens.log', () => OUT.show(true)),
    vscode.commands.registerCommand('wavelens.openConfig', cfgOpen),
    vscode.commands.registerCommand('wavelens.resetConfig', cfgReset),
    vscode.workspace.onDidSaveTextDocument(doc => { if (CTX && doc.uri.fsPath === configFile()) cfgApply(doc.getText()); }),
    vscode.commands.registerCommand('wavelens.verilatorTypes', opts => verilatorTypes(active(), opts || {})),
    vscode.commands.registerCommand('wavelens.toFst', (uri, opts) => {   // the explorer's file, else the active tab's dump
      const t = active();
      return toFst(uri && uri.fsPath ? uri.fsPath : t && t.file, opts || {});
    }),
    vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('wavelens.theme')) themeAll(themeOf());
      if (e.affectsConfiguration('wavelens.keysToVSCode')) {
        const keysLeft = vscode.workspace.getConfiguration('wavelens').get('keysToVSCode') || [];
        for (const tab of TABS) tab.post({ type: 'keys', keysLeft }); } }),
    vscode.commands.registerCommand('wavelens.goto', (l, base) => (l ? followLink(l, base) : null)),
    vscode.window.registerTerminalLinkProvider({
      provideTerminalLinks: c => LINKS.linksOf(c.line, ownLinks()).map(l => ({ startIndex: l.start, length: l.end - l.start, tooltip: linkTip(l), data: l })),
      handleTerminalLink: link => followLink(link.data),
    }),
    vscode.languages.registerDocumentLinkProvider([{ scheme: 'file', pattern: '**/*.{log,txt,out}' }, { language: 'log' }], {
      provideDocumentLinks: doc => {
        const out = [], own = ownLinks(), base = path.dirname(doc.uri.fsPath);
        for (let i = 0; i < Math.min(doc.lineCount, 200000); i++) {
          for (const l of LINKS.linksOf(doc.lineAt(i).text, own)) {
            const a = vscode.Uri.parse(`command:wavelens.goto?${encodeURIComponent(JSON.stringify([l, base]))}`);
            const d = new vscode.DocumentLink(new vscode.Range(i, l.start, i, l.end), a); d.tooltip = linkTip(l); out.push(d);
          }
        }
        return out;
      },
    }),
    vscode.commands.registerCommand('wavelens.live', () => {
      liveCheck(); const t = active();
      if (!liveOn()) vscode.window.showInformationMessage('WaveLens: the setting wavelens.live is off');
      else if (!LIVE_NOW) vscode.window.showInformationMessage('WaveLens: no agent\'s live link on this host (the agent starts it with view_live)');
      else if (t) { t.sent = false; liveTo(t); }
    }));
  // the stores of dumps that are no more (each dump opened keeps one in the workspace's state)
  for (const k of ctx.workspaceState.keys()) { if (!k.startsWith('store:')) continue;
    try { if (!fs.existsSync(vscode.Uri.parse(k.slice(6)).fsPath)) ctx.workspaceState.update(k, undefined); } catch (e) { log(`the store of ${k}: ${e.message}`); } }
  const timer = setInterval(liveCheck, 1500); ctx.subscriptions.push({ dispose: () => clearInterval(timer) });
  liveCheck();
  return { events: EVENTS.event, tabs: () => [...TABS], vcdOf, problems: uri => DIAG.get(uri) || [] };   // for the tests (vscode/test)
}
function deactivate() { for (const t of TABS) t.dispose(); }
module.exports = { activate, deactivate };
