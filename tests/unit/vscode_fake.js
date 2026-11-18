// The one fake `vscode` of the extension's unit tests (test_vscode_state.py, test_vscode_config.py, test_runs.py; review
// 2026-11-05 runs A-05): the real vscode/extension.js activated over it in node, a tab of the custom editor opened as VS Code
// opens one, the page's messages sent to the host and its replies kept. Whatever a test does not give is a Proxy that
// answers every name and call with another (a disposable, a no-op), so the extension runs whole; a test gives what it reads.
//   const F = require(FAKE), h = F.host({ ext, dir, config: { openLastState: true }, window: {...}, workspace: {...} });
//   const A = await h.tab(file); await A.send({ type: 'pick', id: 1 }); A.reply(1); A.said; A.html()
'use strict';
const Module = require('module');

// a name -> a function-shaped Proxy: every key another fake (but `then`: not a promise), every call and new another fake
const fake = (name, over = {}) => new Proxy(function () {}, {
  get: (t, k) => (k in over ? over[k] : k === 'then' || typeof k === 'symbol' ? undefined : fake(`${name}.${String(k)}`)),
  apply: () => fake(`${name}()`), construct: () => fake(`new ${name}`),
});

const disposable = () => ({ dispose() {} });

// o: ext (the path of extension.js), dir (the scratch directory: joinPath, the storages), extensionPath (default dir),
// config (wavelens.* settings of the user over { keysToVSCode: [] }), workspaceConfig / folderConfig (the workspace's and a
// workspace folder's: they win in that order, as VS Code reads them), window / workspace / languages (members over the
// defaults), vscode (more top-level names: Range, Diagnostic, ProgressLocation …), workspaceState (a Map kept, default none kept)
function host(o) {
  let provider = null;
  const Uri = { file: p => ({ fsPath: p, toString: () => 'file://' + p, scheme: 'file' }), parse: s => ({ fsPath: s.replace('file://', '') }),
    joinPath: () => ({ fsPath: o.dir }) };
  // the settings at their three levels (review 2026-11-18 T-04): 1 the user's, 2 the workspace's, 3 a workspace folder's; read
  // the nearest, inspected each, written to the target asked (none: the user's), the change told to onDidChangeConfiguration
  const levels = { 1: Object.assign({ keysToVSCode: [] }, o.config), 2: Object.assign({}, o.workspaceConfig), 3: Object.assign({}, o.folderConfig) };
  const settings = levels[1], updates = [], changed = [];
  const value = k => [3, 2, 1].map(t => levels[t][k]).find(v => v !== undefined);
  const config = () => ({ get: value,
    inspect: k => ({ globalValue: levels[1][k], workspaceValue: levels[2][k], workspaceFolderValue: levels[3][k] }),
    update: async (k, v, target) => {
      const t = target === 2 || target === 3 ? target : 1;
      if (o.updateThrows) throw new Error(o.updateThrows);
      updates.push([k, v, target]); if (v === undefined) delete levels[t][k]; else levels[t][k] = v;
      for (const f of changed) f({ affectsConfiguration: s => s === 'wavelens' || s === `wavelens.${k}` });
    } });
  const vscode = fake('vscode', Object.assign({ Uri,
    window: fake('window', Object.assign({ registerCustomEditorProvider: (id, p) => { provider = p; return disposable(); },
      createOutputChannel: () => fake('out') }, o.window)),
    ConfigurationTarget: { Global: 1, Workspace: 2, WorkspaceFolder: 3 },
    workspace: fake('workspace', Object.assign({ getConfiguration: config,
      onDidChangeConfiguration: f => { changed.push(f); return disposable(); } }, o.workspace)) },
  o.languages ? { languages: fake('languages', o.languages) } : {}, o.vscode));
  const load = Module._load;
  Module._load = (r, ...a) => (r === 'vscode' ? vscode : load(r, ...a));
  const stored = o.workspaceState;
  const where = o.extensionPath || o.dir;
  const ctx = { subscriptions: [], extensionUri: Uri.file(where), extensionPath: where, globalStorageUri: Uri.file(o.dir), storageUri: Uri.file(o.dir),
    extension: { packageJSON: {} }, globalState: { get() {}, update() {} },
    workspaceState: stored ? { get: k => stored.get(k), update: async (k, v) => { stored.set(k, v); }, keys: () => [...stored.keys()] }
      : { get() {}, update: async () => {}, keys: () => [] } };
  const api = require(o.ext).activate(ctx);   // tabs(), events, vcdOf, problems (as vscode/test reads them)
  // a tab of the custom editor on file: what the host posted (said), the page's message sent (send), the reply to an id
  const tab = async file => {
    const said = [], on = {};
    const webview = { options: {}, html: '', cspSource: 'x', asWebviewUri: u => u, postMessage: async m => { said.push(m); return true; },
      onDidReceiveMessage: f => { on.message = f; return disposable(); } };
    await provider.resolveCustomEditor({ uri: Uri.file(file) }, { webview, onDidDispose: f => { on.dispose = f; return disposable(); },
      onDidChangeViewState: disposable, reveal() {}, active: true, title: '' });
    // close(): the tab closed by the user (the panel's onDidDispose)
    return { said, send: m => on.message(m), html: () => webview.html, reply: id => said.find(x => x.id === id), close: () => on.dispose && on.dispose(),
      // the host's data in the page (<script id="wavelens-host">)
      host: () => JSON.parse(/id="wavelens-host">(.*?)<\/script>/s.exec(webview.html)[1].replace(/\\u003c/g, '<')) };
  };
  return { vscode, ctx, Uri, tab, api, updates, settings, levels };
}

// the test's body: its result printed on one line RESULT{…} (read by the Python side), a throw: the stack, exit 1
const run = body => body().then(out => { console.log('RESULT' + JSON.stringify(out)); process.exit(0); },
  e => { console.error(e.stack); process.exit(1); });

module.exports = { fake, host, run };
