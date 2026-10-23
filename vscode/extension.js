'use strict';
/* wavefw for VS Code — the extension host's half. It runs where the files are (extensionKind "workspace": the Linux
   host of Remote-SSH or WSL); the tab's webview runs on the client (Windows). A dump (.vcd, .fst) opens in a custom
   editor: the wavefw viewer (media/, or ../wavefw in the repository) that fetches the dump through its webview URI (an
   FST turned into VCD text first by the bundled sva, kept in the extension's storage). media/host.js brings here what a
   browser would do itself: the downloads (a save dialog on the host), the file pickers, the clipboard, localStorage
   (this dump's store in workspaceState), the agent's live link (tools/wavemcp.py listens on the host's 127.0.0.1, which
   the client cannot reach: this side relays it). Nothing is installed on the host: node is VS Code's, sva is static. */
const vscode = require('vscode'), fs = require('fs'), path = require('path'), os = require('os'), crypto = require('crypto');
const http = require('http'), cp = require('child_process');

const VIEW = 'wavefw.waves';
const MEDIA = ['wavefw.css', 'wavefw.config.js', 'wavefw.js', 'sva.wasm.js', 'bus.js', 'sva.js'];
const TABS = new Set();
const EVENTS = new vscode.EventEmitter();   // {type, tab, …} from the webviews (ready, loaded): the tests listen
let CTX, OUT;

const log = s => OUT && OUT.appendLine(`[${new Date().toISOString().slice(11, 19)}] ${s}`);
const exists = p => { try { fs.accessSync(p); return true; } catch (e) { return false; } };
const sha = s => crypto.createHash('sha1').update(s).digest('hex').slice(0, 16);
const cacheDir = () => path.join(process.env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'wavefw');

// where the viewer's files are: inside the package (make vsix), else the repository around vscode/ (development)
function roots() {
  const ext = CTX.extensionPath, inside = path.join(ext, 'media');
  return { host: inside, wavefw: exists(path.join(inside, 'wavefw.js')) ? inside : path.join(ext, '..', 'wavefw') };
}
function svaBin() {
  const set = vscode.workspace.getConfiguration('wavefw').get('sva');
  if (set) return set;
  const ext = CTX.extensionPath;
  for (const p of [path.join(ext, 'bin', 'sva'), path.join(ext, '..', 'bin', `${process.platform}-x86_64`, 'sva')]) {
    if (!exists(p)) continue;
    try { fs.accessSync(p, fs.constants.X_OK); } catch (e) { try { fs.chmodSync(p, 0o755); } catch (e2) { /* read-only */ } }   // a vsix keeps no mode
    return p;
  }
  return 'sva';   // on the PATH
}

/* ---------------- an FST as VCD text: sva vcd, kept by path, size, time and the program ---------------- */
const CONV = new Map();   // the conversions running: their output -> Promise
async function vcdOf(file) {
  if (!/\.fst$/i.test(file)) return file;
  const st = await fs.promises.stat(file), bin = svaBin();
  let tag = bin; try { const b = fs.statSync(bin); tag += b.size + ':' + b.mtimeMs; } catch (e) { /* on the PATH */ }
  const dir = path.join(CTX.globalStorageUri.fsPath, 'fst'), key = sha(file);
  const out = path.join(dir, `${key}-${sha(`${st.size}:${st.mtimeMs}:${tag}`)}.vcd`);
  if (exists(out)) return out;
  if (CONV.has(out)) return CONV.get(out);
  const job = (async () => {
    await fs.promises.mkdir(dir, { recursive: true });
    const tmp = `${out}.${process.pid}.${Date.now()}.part`;
    try {
      await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `wavefw: ${path.basename(file)} → VCD text` }, () =>
        new Promise((ok, no) => {
          const p = cp.spawn(bin, ['vcd', file, '--out', tmp], { stdio: ['ignore', 'ignore', 'pipe'] });
          let err = ''; p.stderr.on('data', d => { err += d; });
          p.on('error', e => no(new Error(`${bin}: ${e.message}`)));
          p.on('close', code => (code === 0 ? ok() : no(new Error(err.trim() || `${bin} vcd: exit ${code}`))));
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
  const used = new Set([...TABS].map(t => t.src)), now = Date.now(), all = [];
  for (const f of await fs.promises.readdir(dir).catch(() => [])) {
    const p = path.join(dir, f);
    try { const st = await fs.promises.stat(p); if (f.endsWith('.vcd') || now - st.mtimeMs > 86400e3) all.push([p, st.mtimeMs]); } catch (e) { /* gone */ }
  }
  all.sort((a, b) => b[1] - a[1]);
  for (const [p, t] of all.slice(16)) if (!used.has(p) && now - t > 600e3) await fs.promises.unlink(p).catch(() => {});
}

/* ---------------- a tab: one dump in a webview ---------------- */
class Tab {
  constructor(uri, panel) {
    this.uri = uri; this.file = uri.fsPath; this.panel = panel; this.wait = new Map(); this.rid = 0; this.streams = new Map();
    this.storeKey = 'store:' + uri.toString(); this.store = Object.assign({}, CTX.workspaceState.get(this.storeKey) || {}); this.changed = new Map();
    const r = roots();
    panel.webview.options = { enableScripts: true, localResourceRoots: [vscode.Uri.file(r.host), vscode.Uri.file(r.wavefw),
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
    const host = { name, path: this.file, store: this.store, autoReload: !!vscode.workspace.getConfiguration('wavefw').get('autoReload') };
    const scripts = MEDIA.filter(f => f.endsWith('.js')).map(f => `<script nonce="${nonce}" src="${u(r.wavefw, f)}"></script>`).join('\n');
    return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${src} blob: data:; style-src ${src} 'unsafe-inline';
  font-src ${src}; script-src 'nonce-${nonce}' 'wasm-unsafe-eval'; worker-src blob:; connect-src ${src} blob: data:;">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(name)}</title>
<link rel="stylesheet" href="${u(r.wavefw, 'wavefw.css')}">
<style>
  body { margin: 0; padding: 8px 10px; background: var(--bg); color: var(--fg); font-family: var(--font-body); }
</style>
</head>
<body>
<script type="application/json" id="wavefw-host">${json(host)}</script>
<script type="application/wavedrom" data-title="${esc(name)}">
{ "signal": [{ "name": "reading…", "wave": "x..." }], "head": { "text": ${json('reading ' + name + '…')} } }
</script>
<script nonce="${nonce}" src="${u(r.host, 'host.js')}"></script>
${scripts}
</body>
</html>`;
  }
  async source() {   // -> {src, name}: the URI the webview fetches now (an FST: its VCD text, converted when it changed)
    const f = this.src = await vcdOf(this.file);
    return { src: this.panel.webview.asWebviewUri(vscode.Uri.file(f)).toString(), name: path.basename(this.file) };
  }
  async message(m) {
    if (!m || typeof m.type !== 'string') return;
    const reply = o => this.post(Object.assign({ id: m.id }, o));
    switch (m.type) {
      case 'source': return reply(await this.source());
      case 'store': {   // a localStorage key of this dump (null: removed), kept in the workspace: the keys changed, not a snapshot
        if (typeof m.key !== 'string') return;
        this.changed.set(m.key, m.value == null ? null : String(m.value));
        clearTimeout(this.storeT); this.storeT = setTimeout(() => this.flush(), 300);
        return;
      }
      case 'save': return reply(await this.save(String(m.name || 'wavefw.out'), Buffer.from(String(m.b64 || ''), 'base64')));
      case 'pick': return reply(await this.pick(String(m.accept || ''), !!m.multiple));
      case 'clip': await vscode.env.clipboard.writeText(String(m.text ?? '')); return reply({ ok: true });
      case 'result': { const w = this.wait.get(m.rid); if (w) { this.wait.delete(m.rid); w(m.results); } return; }
      case 'ready': case 'loaded':
        this.info = { shown: m.shown, total: m.total, title: m.title };
        if (m.type === 'ready') { this.ready = true; liveTo(this); }
        EVENTS.fire(Object.assign({}, m, { tab: this }));
        return;
      case 'log': log(`${path.basename(this.file)}: ${m.text}`); return;
      case 'es-open': return this.esOpen(m.sid, String(m.url));
      case 'es-close': { const s = this.streams.get(m.sid); this.streams.delete(m.sid); if (s) s.close(); return; }
      case 'http': return reply(await relay(this, String(m.url), m.body == null ? '' : String(m.body)));
    }
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
      saveLabel: 'Save', title: `wavefw: save ${name} on ${vscode.env.remoteName ? 'the host' : 'this machine'}` });
    if (!to) return { cancel: true };
    await vscode.workspace.fs.writeFile(to, data);
    return { path: to.fsPath };
  }
  async pick(accept, multiple) {
    const exts = [...new Set(accept.split(',').map(s => s.trim()).filter(s => s.startsWith('.')).map(s => s.slice(1)))];
    if (exts.includes('vcd')) exts.push('fst');
    const got = await vscode.window.showOpenDialog({ defaultUri: vscode.Uri.file(path.dirname(this.file)), canSelectMany: multiple,
      filters: exts.length ? { [exts.join(', ')]: [...new Set(exts)], 'every file': ['*'] } : undefined });
    if (!got || !got.length) return { files: [] };
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
  // the dump changed on the disk: once its size and time have stood still for a second (the simulator done writing)
  watch() {
    let last = null;
    const quiet = cur => {   // the size and time as they were a moment ago: still writing when they moved
      clearTimeout(this.changeT);
      this.changeT = setTimeout(() => fs.stat(this.file, (err, now) => {
        if (err || !now.size) return;
        if (now.size !== cur.size || now.mtimeMs !== cur.mtimeMs) { quiet(now); return; }
        const sig = `${now.size}:${now.mtimeMs}`; if (sig === last) return; last = sig;
        this.post({ type: 'changed', auto: !!vscode.workspace.getConfiguration('wavefw').get('autoReload') });
      }), 1200);
    };
    this.onStat = (cur, prev) => { if (cur.mtimeMs !== prev.mtimeMs || cur.size !== prev.size) quiet(cur); };
    fs.watchFile(this.file, { interval: 1000 }, this.onStat);   // polling: NFS homes of a Remote-SSH host send no events
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
    TABS.delete(this); fs.unwatchFile(this.file, this.onStat); clearTimeout(this.changeT);
    this.flush();
    for (const s of this.streams.values()) s.close();
    this.streams.clear();
  }
}

/* ---------------- the agent's live link (tools/wavemcp.py) ---------------- */
// The bridge of an agent's wavemcp.py listens on 127.0.0.1 of this host and writes ~/.cache/wavefw/live/<port>.json
// (port, pid, host) while it runs; the key is the user's ~/.cache/wavefw/live-token. A tab is given "port:key"
// (WaveFW.live): the newest bridge, or the one that asked to open it; its EventSource and POSTs to that bridge, and to
// nothing else, come here (media/host.js). view_live with a dump writes open-*.json there: the window that has the file
// in its folders opens it first, another after a few seconds; the request goes once its tab is open.
const LIVE_PATHS = { events: 'GET', hello: 'POST', reply: 'POST', bye: 'POST' };
const liveOn = () => !!vscode.workspace.getConfiguration('wavefw').get('live');
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

/* ---------------- activation ---------------- */
function activate(ctx) {
  CTX = ctx; OUT = vscode.window.createOutputChannel('wavefw'); ctx.subscriptions.push(OUT, EVENTS);
  ctx.subscriptions.push(vscode.window.registerCustomEditorProvider(VIEW, {
    openCustomDocument: uri => ({ uri, dispose() {} }),
    resolveCustomEditor: (doc, panel) => { new Tab(doc.uri, panel); },
  }, { webviewOptions: { retainContextWhenHidden: true }, supportsMultipleEditorsPerDocument: false }));
  const active = () => [...TABS].find(t => t.panel.active) || [...TABS].find(t => t.panel.visible);
  ctx.subscriptions.push(
    vscode.commands.registerCommand('wavefw.open', uri => {
      uri = uri || (vscode.window.activeTextEditor && vscode.window.activeTextEditor.document.uri);
      if (uri) return vscode.commands.executeCommand('vscode.openWith', uri, VIEW);
      return vscode.window.showOpenDialog({ filters: { dumps: ['vcd', 'fst'] } })
        .then(u => u && u[0] && vscode.commands.executeCommand('vscode.openWith', u[0], VIEW));
    }),
    vscode.commands.registerCommand('wavefw.reload', () => { const t = active(); if (t) t.post({ type: 'reload' }); }),
    vscode.commands.registerCommand('wavefw.live', () => {
      liveCheck(); const t = active();
      if (!liveOn()) vscode.window.showInformationMessage('wavefw: the setting wavefw.live is off');
      else if (!LIVE_NOW) vscode.window.showInformationMessage('wavefw: no agent\'s live link on this host (the agent starts it with view_live)');
      else if (t) { t.sent = false; liveTo(t); }
    }));
  const timer = setInterval(liveCheck, 1500); ctx.subscriptions.push({ dispose: () => clearInterval(timer) });
  liveCheck();
  return { events: EVENTS.event, tabs: () => [...TABS], vcdOf };   // for the tests (vscode/test)
}
function deactivate() { for (const t of TABS) t.dispose(); }
module.exports = { activate, deactivate };
