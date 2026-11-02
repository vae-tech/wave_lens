"""The last state in vscode/extension.js, run in node over a fake vscode: the workspace keeps the path of the state loaded, whichever tab,
Load… opens on it, the state is read on the host, the other tabs are told; the path comes from the dialog, never from the webview."""
import glob, json, os, shutil, subprocess, unittest

from . import helpers as H

NODE = os.environ.get('WAVELENS_NODE') or shutil.which('node') or next(iter(sorted(glob.glob(os.path.expanduser('~/.vscode-server/bin/*/node')))), None)
SCRIPT = r'''
const Module = require('module'), fs = require('fs'), path = require('path');
const [ext, dir] = process.argv.slice(1);
const fake = (name, over = {}) => new Proxy(function () {}, {
  get: (t, k) => (k in over ? over[k] : k === 'then' || typeof k === 'symbol' ? undefined : fake(`${name}.${String(k)}`)),
  apply: () => fake(`${name}()`), construct: () => fake(`new ${name}`),
});
let picked = null, asked = null, provider = null;
const Uri = { file: p => ({ fsPath: p, toString: () => 'file://' + p, scheme: 'file' }), parse: s => ({ fsPath: s.replace('file://', '') }), joinPath: () => ({ fsPath: dir }) };
const vscode = fake('vscode', { Uri,
  window: fake('window', { registerCustomEditorProvider: (id, p) => { provider = p; return { dispose() {} }; },
    showOpenDialog: async o => { asked = o; return picked ? [Uri.file(picked)] : undefined; },
    createOutputChannel: () => fake('out') }),
  workspace: fake('workspace', { getConfiguration: () => ({ get: k => ({ keysToVSCode: [], openLastState: true })[k] }) }) });
const load = Module._load; Module._load = (r, ...a) => (r === 'vscode' ? vscode : load(r, ...a));
const stored = new Map();
const ctx = { subscriptions: [], extensionUri: Uri.file(dir), extensionPath: dir, globalStorageUri: Uri.file(dir), storageUri: Uri.file(dir), extension: { packageJSON: {} }, globalState: { get() {}, update() {} },
  workspaceState: { get: k => stored.get(k), update: async (k, v) => { stored.set(k, v); }, keys: () => [...stored.keys()] } };
require(ext).activate(ctx);
const tab = async file => { const said = [], on = {}; const webview = { options: {}, html: '', cspSource: 'x', asWebviewUri: u => u, postMessage: async m => { said.push(m); return true; },
    onDidReceiveMessage: f => { on.message = f; return { dispose() {} }; } };
  await provider.resolveCustomEditor({ uri: Uri.file(file) }, { webview, onDidDispose: () => ({ dispose() {} }), onDidChangeViewState: () => ({ dispose() {} }), reveal() {}, active: true, title: '' });
  return { said, send: m => on.message(m), html: () => webview.html, reply: id => said.find(x => x.id === id) }; };
(async () => {
  const a = path.join(dir, 'a', 'a.vcd'), b = path.join(dir, 'b', 'b.vcd'), s = path.join(dir, 'states', 's.view.json'), out = {};
  const A = await tab(a), B = await tab(b);
  picked = s; await A.send({ type: 'pick', id: 1, accept: '.json,application/json', state: true });
  out.first = asked.defaultUri.fsPath; out.pickedPath = A.reply(1).files[0].path;
  out.noneYet = (await A.send({ type: 'state-read', id: 2 }), A.reply(2));
  await A.send({ type: 'state-kept' });
  out.told = B.said.filter(m => m.type === 'laststate').map(m => m.path);
  await B.send({ type: 'pick', id: 3, accept: '.json', state: true }); out.second = asked.defaultUri.fsPath;
  await B.send({ type: 'state-kept' });
  await B.send({ type: 'state-read', id: 4, path: '/etc/passwd' }); const r = B.reply(4); out.read = [r.name, Buffer.from(r.b64, 'base64').toString()];
  const C = await tab(path.join(dir, 'b', 'c.vcd'));
  out.host = JSON.parse(/id="wavelens-host">(.*?)<\/script>/s.exec(C.html())[1].replace(/\\u003c/g, '<')).lastState;
  await A.send({ type: 'pick', id: 5, accept: '.sv', multiple: true }); out.sources = asked.defaultUri.fsPath;
  fs.unlinkSync(s);
  await A.send({ type: 'pick', id: 6, accept: '.json', state: true }); out.fileGone = asked.defaultUri.fsPath;
  await A.send({ type: 'state-read', id: 7 }); out.gone = !!A.reply(7).error;
  fs.rmSync(path.dirname(s), { recursive: true });
  await A.send({ type: 'pick', id: 8, accept: '.json', state: true }); out.folderGone = asked.defaultUri.fsPath;
  console.log('RESULT' + JSON.stringify(out)); process.exit(0);
})().catch(e => { console.error(e.stack); process.exit(1); });
'''


class LastState(unittest.TestCase):
    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_the_workspace_keeps_it(self):
        with H.tmp() as d:
            for sub in ('a', 'b', 'states'):
                os.makedirs(os.path.join(d, sub))
            for p in ('a/a.vcd', 'b/b.vcd', 'b/c.vcd'):
                with open(os.path.join(d, p), 'w', encoding='utf-8') as f:
                    f.write('$enddefinitions $end\n')
            s = os.path.join(d, 'states', 's.view.json')
            with open(s, 'w', encoding='utf-8') as f:
                f.write('{"state": 1}')
            r = subprocess.run([NODE, '-e', SCRIPT, os.path.join(H.ROOT, 'vscode', 'extension.js'), d], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            o = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
            self.assertEqual(o['first'], os.path.join(d, 'a'), 'the first Load…: the folder of the dump')
            self.assertEqual(o['pickedPath'], s)
            self.assertIn('error', o['noneYet'], 'picked, not yet loaded: nothing kept')
            self.assertEqual(o['told'], [s], 'the other tabs are told')
            self.assertEqual(o['second'], s, 'Load… in another tab, on another dump: on that file')
            self.assertEqual(o['read'], ['s.view.json', '{"state": 1}'], 'read on the host, the workspace\'s path whatever the webview says')
            self.assertEqual(o['host'], s, 'a tab opened after it knows it')
            self.assertEqual(o['sources'], os.path.join(d, 'a'), 'the other pickers stay at the dump')
            self.assertEqual(o['fileGone'], os.path.dirname(s), 'the file gone: its folder')
            self.assertTrue(o['gone'], 'the file gone: read says so')
            self.assertEqual(o['folderGone'], os.path.join(d, 'a'), 'the folder gone too: the dump\'s')
