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


PIECE = r'''
const path = require('path');
const [F, ext, dir] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
const h = F.host({ ext, dir, workspaceState: new Map(), config: { lazy: 'always' } });
F.run(async () => {
  const A = await h.tab(path.join(dir, 'p.wavelens.json'));
  await A.send({ type: 'source', id: 1 }); return A.reply(1);
});
'''


class Piece(unittest.TestCase):
    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_a_piece_of_waves_served_as_it_is(self):
        """A piece of waves (x.wavelens.json, the box's Save as WaveLens) in a tab: served as it is, read whole (no FST, never
        lazy, wavelens.lazy "always" or not); package.json opens it with WaveLens."""
        with H.tmp() as d:
            with open(os.path.join(d, 'p.wavelens.json'), 'w', encoding='utf-8') as f:
                json.dump({'wavelens': 'waves', 'version': 1, 'signal': [{'name': 'a', 'path': 't.a', 'tv': [[0, '1']]}], 'time': {'t0': 0, 't1': 10}}, f)
            r = subprocess.run([NODE, '-e', PIECE, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            o = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
            self.assertTrue(o['src'].endswith('p.wavelens.json') and o['lazy'] is False, o)
        pk = json.loads(H.text(os.path.join(H.ROOT, 'vscode', 'package.json')))
        self.assertIn({'filenamePattern': '*.wavelens.json'}, pk['contributes']['customEditors'][0]['selector'])


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


LAZY = r'''
const fs = require('fs'), path = require('path');
const [F, ext, dir] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
const diags = new Map();
class Range { constructor(a, b, c, d) { Object.assign(this, { line: a }); } }
class Position { constructor(line) { this.line = line; } }
class Location { constructor(uri, at) { Object.assign(this, { file: uri.fsPath, line: at.line }); } }
class Diagnostic { constructor(range, message) { Object.assign(this, { line: range.line, message }); } }
class DiagnosticRelatedInformation { constructor(at, message) { Object.assign(this, { at, message }); } }
const h = F.host({ ext, dir, workspaceState: new Map(), config: { sva: process.env.WAVELENS_SVA, lazy: 'always' },
  window: { withProgress: async (o, f) => f(), showErrorMessage: async () => undefined },
  vscode: { Range, Position, Location, Diagnostic, DiagnosticRelatedInformation, DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2 } },
  languages: { createDiagnosticCollection: () => ({ set: (u, d) => diags.set(u.fsPath, d), get: u => diags.get(u.fsPath), delete() {}, dispose() {} }) } });
F.run(async () => {
  const f = path.join(dir, 'dump.fst'), out = {};
  const A = await h.tab(f);
  await A.send({ type: 'source', id: 1 }); out.lazy = A.reply(1).lazy;
  await A.send({ type: 'codes', id: 2, codes: ['"'] }); out.before = A.reply(2);
  fs.copyFileSync(path.join(dir, 'other.fst'), f);   // another run written over it, the tab not read again
  await A.send({ type: 'codes', id: 3, codes: ['"'] }); out.after = A.reply(3);
  await A.send({ type: 'source', id: 4 });   // read again (R, ⟳, autoReload): its codes again
  await A.send({ type: 'codes', id: 5, codes: ['"'] }); out.again = A.reply(5);
  // a large VCD read lazy: the page reads the header made of it, its notes' lines are that text's
  const v = path.join(dir, 'big.vcd'), B = await h.tab(v);
  await B.send({ type: 'source', id: 6 }); out.vlazy = B.reply(6).lazy;
  await B.send({ type: 'loaded', log: [{ level: 'warning', text: 'odd', line: 3 }] });
  out.notes = (diags.get(v) || []).map(d => [d.line, d.message, (d.relatedInformation || []).map(x => [x.at.file !== v, x.at.line])]);
  return out;
});
'''


class LazyDump(unittest.TestCase):
    """A large dump read lazy in the VS Code tab: its signals read later (codes) from the FST of when the tab read it, never
    from another run written over it since (bughunt B-17); the notes of a lazy VCD (the page read the header made of it) on
    its first line, the line of that text beside them (B-23)."""
    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    @H.needs(os.environ.get('WAVELENS_SVA'), 'the sva CLI ($WAVELENS_SVA)')
    def test_codes_of_the_dump_read(self):
        sva = os.environ['WAVELENS_SVA']
        one = ('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 4 " cnt [3:0] $end\n$upscope $end\n'
               '$enddefinitions $end\n#0\n0!\nb0 "\n#5\n1!\nb1 "\n#10\n0!\n')
        two = ('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! a $end\n$var wire 1 " s $end\n$var wire 1 # z $end\n$upscope $end\n'
               '$enddefinitions $end\n#0\n0!\n1"\n0#\n#7\n1!\n0"\n#9\n1#\n')
        with H.tmp() as d:
            for name, text in (('dump', one), ('other', two), ('big', one)):
                with open(os.path.join(d, name + '.vcd'), 'w', encoding='utf-8') as f:
                    f.write(text)
                if name != 'big':
                    subprocess.run([sva, 'fst', os.path.join(d, name + '.vcd'), '--no-types', '-q'], check=True)
            r = subprocess.run([NODE, '-e', LAZY, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            o = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
            self.assertTrue(o.get("lazy") and o.get("vlazy"), o)
            self.assertIn('cnt', o['before'].get('text', ''), o['before'])
            self.assertNotIn('text', o['after'], f'another run on the disk: not its signals as this header\'s {o["after"]}')
            self.assertIn('changed', o['after'].get('error', ''), o['after'])
            self.assertIn('$var wire 1 " s', o['again'].get('text', ''), 'read again: the codes of the new file')
            self.assertEqual(len(o['notes']), 1, o['notes'])
            line, msg, rel = o['notes'][0]
            self.assertEqual(line, 0, 'not the header\'s line 3 on the user\'s VCD')
            self.assertIn('line 3', msg)
            self.assertEqual(rel, [[True, 2]], 'the line in the text read beside it')


WP8 = r'''
const fs = require('fs'), path = require('path');
const [F, ext, dir, mode] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
if (mode === 'arm64') Object.defineProperty(process, 'arch', { value: 'arm64' });
// the tab's 20 s for a run and the link's 100 ms polls made short (a run never answered times out at once)
const st = setTimeout; global.setTimeout = (f, ms, ...a) => st(f, ms >= 20000 ? 50 : ms === 100 ? 5 : ms, ...a);
const out = { warned: [] }, cmds = {};
process.on('unhandledRejection', e => { out.unhandled = String(e && e.message); });
// VS Code's fsPath is normalized (on Windows: the drive letter lower case); a link's path may not be
const Uri = { file: p => ({ fsPath: p.replace(/\/\/+/g, '/'), toString: () => 'file://' + p, scheme: 'file' }), parse: s => ({ fsPath: s.replace('file://', '') }),
  joinPath: () => ({ fsPath: dir }) };
const h = F.host({ ext, dir, extensionPath: path.join(dir, 'ext'), workspaceState: new Map([['lastState', '/s/now.view.json']]),
  config: mode === 'eacces' ? { sva: path.join(dir, 'ext', 'bin', 'sva') } : {},
  vscode: { Uri, commands: { registerCommand: (id, f) => { cmds[id] = f; return { dispose() {} }; }, executeCommand: async () => {} } },
  window: { showWarningMessage: async s => { out.warned.push(s); }, showInformationMessage: async () => {} } });
const until = async f => { for (let i = 0; i < 400 && !f(); i++) await new Promise(r => st(r, 5)); return f(); };
F.run(async () => {
  const f = path.join(dir, 'd.vcd'), A = await h.tab(f);
  // B-66: the first page of a tab is fresh (its store empty), a page made again after it was ready is not; the last state of now
  await A.send({ type: 'source', id: 1 }); const s1 = A.reply(1);
  await A.send({ type: 'ready', title: 'd.vcd' });
  await A.send({ type: 'source', id: 2 }); const s2 = A.reply(2);
  out.source = [s1.fresh, s1.lastState, s2.fresh, s2.lastState];
  // B-67: the CLI's error with the bundled one (or a wavelens.sva) that cannot run here
  await A.send({ type: 'runs', op: 'list', id: 3 }); out.cli = A.reply(3).error || '';
  if (mode) return out;
  // B-68: a link naming the dump by another spelling of its path reaches the open tab
  const runs = () => A.said.filter(m => m.type === 'run');
  const go = cmds['wavelens.goto']({ dump: dir + '//d.vcd', ps: 1000 }, dir);
  out.found = await until(() => runs().length === 1);
  // B-69: the page's {error} answered to the run: said
  if (out.found) await A.send({ type: 'result', rid: runs()[0].rid, results: { error: 'no viewer' } });
  await go;
  // a run the page never answers: its timeout said, not thrown
  await cmds['wavelens.goto']({ dump: f, ps: 2000 }, dir).catch(e => { out.thrown = e.message; });
  await new Promise(r => st(r, 20));
  return out;
});
'''


class Wp8(unittest.TestCase):
    """bughunt WP8: a page made again (a tab moved to a window of its own) asks the extension whether it is the tab's first
    (B-66); the bundled sva only where it runs, a CLI that does not run explained (B-67); a link reaches the open tab by the
    URI's path (B-68), the page's error and a run's timeout said (B-69)."""
    def node(self, d, mode=''):
        r = subprocess.run([NODE, '-e', WP8, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d, mode], capture_output=True, text=True,
                           timeout=60, env=dict(os.environ, PATH='/usr/bin:/bin'))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])

    def tree(self, d, mode=0o755):
        os.makedirs(os.path.join(d, 'ext', 'bin'))
        sva = os.path.join(d, 'ext', 'bin', 'sva')
        with open(sva, 'w', encoding='utf-8') as f:
            f.write('#!/bin/sh\necho "the bundled sva ran" >&2\nexit 2\n')
        os.chmod(sva, mode)
        with open(os.path.join(d, 'd.vcd'), 'w', encoding='utf-8') as f:
            f.write('$timescale 1ns $end\n$scope module t $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n#0\n1!\n')
        return sva

    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_the_page_again_and_links(self):
        with H.tmp() as d:
            self.tree(d)
            o = self.node(d)
        self.assertEqual(o['source'], [True, '/s/now.view.json', False, '/s/now.view.json'],
                         'the tab\'s first page fresh, a page made again not; the last state of now with both (B-66)')
        self.assertIn('the bundled sva ran', o['cli'], 'linux x64: the bundled sva')
        self.assertTrue(o['found'], 'a link with another spelling of the open dump\'s path: run in its tab (B-68)')
        self.assertFalse('unhandled' in o or 'thrown' in o, f'a run never answered: nothing thrown (B-69) {o}')
        self.assertEqual(o['warned'], ['WaveLens: no viewer', 'WaveLens: the tab did not answer'], 'the page\'s error and the timeout said (B-69)')

    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_the_bundled_cli_only_where_it_runs(self):
        with H.tmp() as d:
            self.tree(d)
            o = self.node(d, 'arm64')
        self.assertNotIn('the bundled sva ran', o['cli'], 'linux arm64: not the bundled linux x86_64 one (B-67)')
        self.assertIn('wavelens.sva', o['cli'])
        self.assertIn('linux arm64', o['cli'], o['cli'])

    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_a_cli_that_does_not_run_explained(self):
        with H.tmp() as d:
            sva = self.tree(d, 0o644)
            o = self.node(d, 'eacces')
        self.assertIn(sva, o['cli'])
        self.assertIn('cannot run', o['cli'], f'EACCES / ENOEXEC: said what to do (B-67) {o["cli"]}')
        self.assertIn('wavelens.sva', o['cli'])
