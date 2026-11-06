"""The last state in vscode/extension.js, run in node over a fake vscode: the workspace keeps the path of the state loaded, whichever tab,
Load… opens on it, the state is read on the host, the other tabs are told; the path comes from the dialog, never from the webview."""
import glob, json, os, shutil, subprocess, unittest

from . import helpers as H

NODE = os.environ.get('WAVELENS_NODE') or shutil.which('node') or next(iter(sorted(glob.glob(os.path.expanduser('~/.vscode-server/bin/*/node')))), None)
# the one fake vscode of the extension's unit tests (test_vscode_config.py and test_runs.py use it too; review 2026-11-05 runs A-05)
FAKE = os.path.join(H.ROOT, 'tests', 'unit', 'vscode_fake.js')
SCRIPT = r'''
const fs = require('fs'), path = require('path');
const [F, ext, dir] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
let picked = null, asked = null;
const h = F.host({ ext, dir, config: { openLastState: true }, workspaceState: new Map(),
  window: { showOpenDialog: async o => { asked = o; return picked ? [h.Uri.file(picked)] : undefined; } } });
const tab = h.tab;
F.run(async () => {
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
  out.host = C.host().lastState;
  await A.send({ type: 'pick', id: 5, accept: '.sv', multiple: true }); out.sources = asked.defaultUri.fsPath;
  fs.unlinkSync(s);
  await A.send({ type: 'pick', id: 6, accept: '.json', state: true }); out.fileGone = asked.defaultUri.fsPath;
  await A.send({ type: 'state-read', id: 7 }); out.gone = !!A.reply(7).error;
  fs.rmSync(path.dirname(s), { recursive: true });
  await A.send({ type: 'pick', id: 8, accept: '.json', state: true }); out.folderGone = asked.defaultUri.fsPath;
  return out;
});
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
            r = subprocess.run([NODE, '-e', SCRIPT, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d], capture_output=True, text=True, timeout=30)
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


MOVED = r'''
const fs = require('fs'), path = require('path');
const [F, ext, dir] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
const h = F.host({ ext, dir, workspaceState: new Map() });
F.run(async () => {
  const f = path.join(dir, 'd.vcd'), out = {};
  const A = await h.tab(f);
  out.first = A.host().store;
  await A.send({ type: 'bytes', id: 1 }); out.before = A.reply(1);
  await A.send({ type: 'store', key: 'k', value: '1' });
  await A.send({ type: 'store', key: 'gone', value: null });
  await A.send({ type: 'source', id: 2 }); const s = A.reply(2);
  out.store = s.store; out.src = s.src;
  await A.send({ type: 'bytes', id: 3 }); const b = A.reply(3);
  out.typed = b.data instanceof Uint8Array; out.text = Buffer.from(b.data).toString();
  // the page made again: the streams of the page before are closed
  const T = h.api.tabs()[0]; let closed = 0; T.streams.set(1, { close() { closed++; } }); T.streams.set(2, { close() { closed++; } });
  await A.send({ type: 'page' }); out.streams = [closed, T.streams.size];
  return out;
});
'''


class MovedTab(unittest.TestCase):
    """A tab moved to a window of its own: VS Code makes its webview again with the html of when the tab opened; over a remote
    connection its resource loads answer 404. source() gives the store of now, bytes the dump the page could not fetch; the
    new page's first message closes the streams the page before had opened."""
    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_the_store_of_now_and_the_dump_as_bytes(self):
        with H.tmp() as d:
            text = '$timescale 1ns $end\n$scope module t $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n#0\n1!\n'
            with open(os.path.join(d, 'd.vcd'), 'w', encoding='utf-8') as f:
                f.write(text)
            r = subprocess.run([NODE, '-e', MOVED, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            o = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
            self.assertEqual(o['first'], {})
            self.assertIn('error', o['before'], 'no dump named yet: nothing to read')
            self.assertEqual(o['store'], {'k': '1'}, 'the keys of now, those not written yet too')
            self.assertTrue(o['src'].endswith('d.vcd'))
            self.assertTrue(o['typed'], 'bytes as a typed array (VS Code posts it as one)')
            self.assertEqual(o['text'], text)
            self.assertEqual(o['streams'], [2, 0], 'a page again: the live link\'s streams of the page before closed')
