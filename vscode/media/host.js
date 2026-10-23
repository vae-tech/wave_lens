/* wavelens for VS Code — the webview's half, loaded before wavelens.js. The viewer stays as it is in a browser; what a
   browser does by itself and a webview cannot (or does on the wrong machine) goes to the extension host by postMessage:
   - localStorage: this dump's store, given in the page (#wavelens-host) and kept by the extension (workspaceState);
   - a download (an <a download> clicked: Save state, PNG, SVG, WaveDrom, the report) -> a save dialog on the host;
   - a file picker (an <input type=file> clicked: Load state, the .sv files, Compare, Open…) -> an open dialog on the
     host (Open… a dump: a tab of its own); no showOpenFilePicker (a handle of the client's disk);
   - navigator.clipboard.writeText -> the client's clipboard through VS Code;
   - the live link's EventSource / fetch / sendBeacon to 127.0.0.1 -> the host's 127.0.0.1 (the agent's wavemcp.py);
   - the theme: VS Code's light / dark;
   - a key the viewer took does not go on to VS Code (its webview forwards every keydown to the workbench).
   Then it opens the dump (fetched by its webview URI) in the viewer: ⟳ fetches it again, the view kept. */
(() => {
  'use strict';
  const vscode = acquireVsCodeApi(), G = window;
  const H = JSON.parse(document.getElementById('wavelens-host').textContent);
  G.WAVELENS_PATH = H.path;   // the page's path for the live link (edit.js liveHello): the dump's, as the agent names it

  /* ---- messages: a request and its answer by id, or a message of the host ---- */
  let seq = 0; const wait = new Map(), on = {};
  const call = (type, body) => new Promise(ok => { const id = ++seq; wait.set(id, ok); vscode.postMessage(Object.assign({}, body, { type, id })); });
  G.addEventListener('message', e => {
    const m = e.data || {};
    if (m.id && wait.has(m.id)) { const ok = wait.get(m.id); wait.delete(m.id); ok(m); return; }
    if (on[m.type]) on[m.type](m);
  });
  const view = () => (G.WaveLens ? WaveLens.views().find(v => v.root.isConnected) : null);
  const toast = s => { const v = view(); if (v) v.toast(s); };
  const b64 = buf => { const u = new Uint8Array(buf); let s = '';
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
    return btoa(s); };
  const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));

  /* ---- localStorage: this dump's keys ---- */
  const data = new Map(Object.entries(H.store || {}));
  const store = {
    getItem: k => (data.has(String(k)) ? data.get(String(k)) : null),
    setItem(k, v) { k = String(k); v = String(v); if (data.get(k) === v) return; data.set(k, v); vscode.postMessage({ type: 'store', key: k, value: v }); },
    removeItem(k) { k = String(k); if (data.delete(k)) vscode.postMessage({ type: 'store', key: k, value: null }); },
    clear() { for (const k of [...data.keys()]) this.removeItem(k); },
    key: i => [...data.keys()][i] ?? null,
    get length() { return data.size; },
  };
  try { Object.defineProperty(G, 'localStorage', { value: store, configurable: true }); }
  catch (e) { vscode.postMessage({ type: 'log', text: 'localStorage: ' + e }); }
  try { Object.defineProperty(G, 'showOpenFilePicker', { value: undefined, configurable: true }); } catch (e) { /* none */ }

  /* ---- downloads ---- */
  const aclick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (!this.hasAttribute('download')) return aclick.call(this);
    const name = this.download || 'wavelens.out';
    fetch(this.href).then(r => r.arrayBuffer()).then(buf => call('save', { name, b64: b64(buf) }))
      .then(m => toast(m.path ? 'saved ' + m.path : m.error ? 'not saved: ' + m.error : 'not saved'), e => toast('not saved: ' + e.message));
  };

  /* ---- file pickers ---- */
  const iclick = HTMLInputElement.prototype.click;
  HTMLInputElement.prototype.click = function () {
    if (this.type !== 'file') return iclick.call(this);
    call('pick', { accept: this.accept, multiple: this.multiple }).then(m => {
      if (m.error) { toast(m.error); return; }
      if (!m.files || !m.files.length) return;
      const dt = new DataTransfer();
      for (const f of m.files) dt.items.add(new File([unb64(f.b64)], f.name, { lastModified: f.mtime }));
      this.files = dt.files; this.dispatchEvent(new Event('change', { bubbles: true }));
    });
  };

  /* ---- clipboard ---- */
  if (navigator.clipboard) {
    const writeText = text => call('clip', { text: String(text) }).then(m => { if (m.error) throw new Error(m.error); });
    try { Object.defineProperty(navigator.clipboard, 'writeText', { value: writeText, configurable: true }); } catch (e) { /* the browser's own */ }
  }

  /* ---- the live link: to the host's 127.0.0.1 ---- */
  const LOCAL = /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//;
  const NativeES = G.EventSource, nativeFetch = G.fetch.bind(G), streams = new Map();
  class RelayedSource extends EventTarget {
    constructor(url) {
      super(); this.url = String(url); this.readyState = 0; this.sid = ++seq; streams.set(this.sid, this);
      vscode.postMessage({ type: 'es-open', sid: this.sid, url: this.url });
    }
    close() { this.readyState = 2; if (streams.delete(this.sid)) vscode.postMessage({ type: 'es-close', sid: this.sid }); }
  }
  G.EventSource = function (url, opts) { return LOCAL.test(String(url)) ? new RelayedSource(url) : new NativeES(url, opts); };
  on.es = m => {
    const s = streams.get(m.sid); if (!s) return;
    s.readyState = m.event === 'open' ? 1 : m.event === 'error' ? 0 : s.readyState;
    s.dispatchEvent(m.event === 'open' || m.event === 'error' ? new Event(m.event) : new MessageEvent(m.event, { data: m.data }));
  };
  G.fetch = (input, init = {}) => {
    const url = typeof input === 'string' ? input : input.url;
    if (!LOCAL.test(url)) return nativeFetch(input, init);
    return call('http', { url, method: init.method || 'GET', body: init.body == null ? null : String(init.body) })
      .then(m => { if (!m.status) throw new TypeError('the agent\'s server is not there'); return new Response(m.text, { status: m.status }); });
  };
  if (navigator.sendBeacon) {
    const beacon = navigator.sendBeacon.bind(navigator);
    navigator.sendBeacon = (url, body) => (LOCAL.test(String(url)) ? (vscode.postMessage({ type: 'http', id: 0, url: String(url), method: 'POST',
      body: body == null ? null : String(body) }), true) : beacon(url, body));
  }
  let link = null;
  on.live = m => { if (m.link === link || !G.WaveLens) return; link = m.link;
    try { WaveLens.live(link); } catch (e) { vscode.postMessage({ type: 'log', text: 'live: ' + e.message }); } };

  /* ---- the theme ---- */
  const theme = () => { const c = document.body.classList;
    document.documentElement.dataset.theme = c.contains('vscode-light') || c.contains('vscode-high-contrast-light') ? 'light' : 'dark'; };
  theme(); new MutationObserver(theme).observe(document.body, { attributes: true, attributeFilter: ['class'] });

  /* ---- the dump ---- */
  const fetchDump = async () => {
    const s = await call('source', {});
    if (s.error) throw new Error(s.error);
    const r = await nativeFetch(s.src, { cache: 'no-store' });
    if (!r.ok) throw new Error(`${s.name}: ${r.status} ${r.statusText}`);
    return new File([await r.blob()], s.name);
  };
  const handle = { kind: 'file', name: H.name, getFile: fetchDump };   // what reloadDump (⟳) reads again
  let last = {};   // the last dump read: {name, shown, total}
  document.addEventListener('wavelens:dump', e => { last = e.detail || {}; vscode.postMessage(Object.assign({ type: 'loaded' }, last)); },
    true);   // capture: it does not bubble
  // one read again at a time, of the viewer that is there then (the one before is gone once it read); one asked meanwhile: once more after
  let busy = null, again = false;
  const reload = () => {
    if (busy) { again = true; return busy; }
    busy = (async () => { do { again = false; const v = view(); if (v) await RELOAD.call(v); } while (again); })().finally(() => { busy = null; });
    return busy;
  };
  let RELOAD = null;
  on.changed = m => { const v = view(); if (!v) return;
    if (m.auto) reload(); else v.toast(`${H.name} changed on the disk: ⟳ (or wavelens: Read the dump again) reads it, the view kept`); };
  on.reload = () => reload();
  on.run = async m => { let results; const v = view();
    try { results = v ? await v.run(m.ops || []) : { error: 'no viewer' }; } catch (e) { results = { error: e.message }; }
    vscode.postMessage({ type: 'result', rid: m.rid, results }); };
  G.addEventListener('load', async () => {
    theme();   // again: wavelens.config.js (its "theme") came after
    // VS Code's webview sends every keydown that reaches its window to the workbench (ctrl+G would open Go to Line too):
    // a key the viewer took (preventDefault) stops here, after the viewer's own listeners on the document
    // (the viewer's ctrl keys do not look at shift: ctrl+shift+F / G / C stay VS Code's, ctrl+shift+Z is the viewer's redo)
    document.addEventListener('keydown', e => {
      if (e.defaultPrevented && !((e.ctrlKey || e.metaKey) && e.shiftKey && e.code !== 'KeyZ')) e.stopPropagation(); });
    const P = WaveLens.WaveView.prototype; RELOAD = P.reloadDump; P.reloadDump = function () { return reload(); };   // ⟳ of the bar too
    const v = view(); let nv = v;
    try { nv = await v.openDump(await fetchDump(), handle); }
    catch (e) { if (v) v.toast('cannot read ' + H.name + ': ' + e.message); vscode.postMessage({ type: 'log', text: String(e.stack || e) }); }
    vscode.postMessage(Object.assign({ type: 'ready', title: nv && nv.opts.title }, last));
  });
  // a dump dropped on the tab would replace its waves under this tab's name, store and watcher: a tab of its own instead
  document.addEventListener('drop', e => {
    const fs = [...((e.dataTransfer && e.dataTransfer.files) || [])];
    if (!fs.some(f => /\.(vcd|fst)$/i.test(f.name))) return;
    e.preventDefault(); e.stopPropagation(); toast('open a dump from the Explorer: Open in WaveLens (a tab of its own)');
  }, true);
  G.addEventListener('error', e => vscode.postMessage({ type: 'log', text: `${e.message} (${e.filename}:${e.lineno})` }));
})();
