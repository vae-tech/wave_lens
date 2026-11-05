"""Your configuration of the viewer in VS Code (vscode/userconfig.js, run in node; review 2026-11-05 T-03): the kinds each key of
wavelens/wavelens.config.js takes (B-05), a byte order mark, CRLF, inherited names as keys (B-09), the file of the defaults read back
clean; and vscode/extension.js over a fake vscode: the file with a BOM applied at start, a key's mark on its line, not on a comment
naming it, the configuration now given to a tab that asks at its load (B-10)."""
import json, os, re, subprocess, unittest

from . import helpers as H
from .test_vscode_state import NODE

UCFG = os.path.join(H.ROOT, 'vscode', 'userconfig.js')
CFG_JS = os.path.join(H.ROOT, 'wavelens', 'wavelens.config.js')

PURE = r'''
const [ucfg, cfgjs, cases] = process.argv.slice(1), fs = require('fs'), U = require(ucfg), js = fs.readFileSync(cfgjs, 'utf8'), win = {};
require('vm').runInNewContext(js, { window: win });
const D = win.WAVELENS_CONFIG, out = {};
for (const [name, text] of Object.entries(JSON.parse(cases))) {
  const r = U.parse(text);
  out[name] = r.error ? { error: r.error, line: r.line, col: r.col } : Object.assign({ value: r.value, keys: r.keys }, U.check(r.value, D));
}
const t = U.parse(U.template(D, U.notesOf(js)));
out.template = Object.assign({ error: t.error || null }, t.value ? U.check(t.value, D) : {});
out.defaults = D; out.kinds = U.KINDS; out.own = Object.keys(U.VSCODE_OWN);
out.effective = Object.keys(U.effective(D, { rowHeight: 30 }));
console.log('RESULT' + JSON.stringify(out));
'''

EXT = r'''
const Module = require('module'), fs = require('fs'), path = require('path');
const [ext, dir] = process.argv.slice(1);
const fake = (name, over = {}) => new Proxy(function () {}, {
  get: (t, k) => (k in over ? over[k] : k === 'then' || typeof k === 'symbol' ? undefined : fake(`${name}.${String(k)}`)),
  apply: () => fake(`${name}()`), construct: () => fake(`new ${name}`),
});
let provider = null, saved = null;
const diags = new Map();
class Range { constructor(l0, c0, l1, c1) { Object.assign(this, { line: l0, col: c0, endLine: l1, endCol: c1 }); } }
class Diagnostic { constructor(range, message, severity) { Object.assign(this, { range, message, severity }); } }
const Uri = { file: p => ({ fsPath: p, toString: () => 'file://' + p, scheme: 'file' }), parse: s => ({ fsPath: s.replace('file://', '') }), joinPath: () => ({ fsPath: dir }) };
const vscode = fake('vscode', { Uri, Range, Diagnostic, DiagnosticSeverity: { Error: 0, Warning: 1 },
  languages: fake('languages', { createDiagnosticCollection: () => ({ set: (u, d) => diags.set(u.fsPath, d), get: u => diags.get(u.fsPath), delete() {},
    dispose() {} }) }),
  window: fake('window', { registerCustomEditorProvider: (id, p) => { provider = p; return { dispose() {} }; }, createOutputChannel: () => fake('out') }),
  workspace: fake('workspace', { getConfiguration: () => ({ get: k => ({ keysToVSCode: [], openLastState: false })[k] }),
    onDidSaveTextDocument: f => { saved = f; return { dispose() {} }; } }) });
const load = Module._load; Module._load = (r, ...a) => (r === 'vscode' ? vscode : load(r, ...a));
const ctx = { subscriptions: [], extensionUri: Uri.file(path.dirname(ext)), extensionPath: path.dirname(ext), globalStorageUri: Uri.file(dir),
  storageUri: Uri.file(dir), extension: { packageJSON: {} }, globalState: { get() {}, update() {} },
  workspaceState: { get() {}, update: async () => {}, keys: () => [] } };
require(ext).activate(ctx);
const file = path.join(dir, 'wavelens.config.jsonc');
const tab = async f => { const said = [], on = {}; const webview = { options: {}, html: '', cspSource: 'x', asWebviewUri: u => u,
    postMessage: async m => { said.push(m); return true; }, onDidReceiveMessage: g => { on.message = g; return { dispose() {} }; } };
  await provider.resolveCustomEditor({ uri: Uri.file(f) }, { webview, onDidDispose: () => ({ dispose() {} }), onDidChangeViewState: () => ({ dispose() {} }),
    reveal() {}, active: true, title: '' });
  return { said, send: m => on.message(m), html: () => webview.html, reply: id => said.find(x => x.id === id) }; };
(async () => {
  const out = {}, A = await tab(path.join(dir, 'a.vcd'));
  out.host = JSON.parse(/id="wavelens-host">(.*?)<\/script>/s.exec(A.html())[1].replace(/\\u003c/g, '<')).config;
  out.marks = (diags.get(file) || []).map(d => [d.range.line, d.range.col, d.message]);
  saved({ uri: Uri.file(file), getText: () => '{"rowHeight": 33}' });
  out.pushed = A.said.filter(m => m.type === 'config').map(m => m.config.rowHeight);
  await A.send({ type: 'config', id: 7 }); const r = A.reply(7);
  out.asked = r && r.config ? r.config.rowHeight : null;
  console.log('RESULT' + JSON.stringify(out)); process.exit(0);
})().catch(e => { console.error(e.stack); process.exit(1); });
'''


def node(script, *args):
    r = subprocess.run([NODE, '-e', script, *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(r.stderr)
    return json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])


def notes():
    """wavelens.config.js -> {key: its whole comment} (the continuation lines too, where notesOf takes the first)"""
    out, last = {}, None
    with open(CFG_JS, encoding='utf-8') as f:
        for line in f:
            m = re.match(r'^ {2}(\w+):.*?//\s?(.*)$', line)
            if m:
                last = m.group(1)
                out[last] = m.group(2)
            elif last and re.match(r'^\s{4,}//', line):
                out[last] += ' ' + line.split('//', 1)[1].strip()
            else:
                last = None
    return out


@H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
class UserConfig(unittest.TestCase):
    CASES = {
        'documented': json.dumps({'log': False, 'keyHints': False, 'gapIdle': '2us', 'gapKeep': '1us', 'themeButton': True, 'svaSignals': True,
                                  'fold': 'tb.dut', 'maxHeight': '80vh', 'cycleZero': '20ns', 'highlight': '*.irq'}),
        'also': json.dumps({'log': 'auto', 'keyHints': 300, 'gapIdle': 16, 'themeButton': 'auto', 'svaSignals': 'view', 'fold': 2, 'maxHeight': 600}),
        'wrong': json.dumps({'rowHeight': 'x', 'colors': [], 'log': 5, 'keyHints': 'soon', 'fold': {}, 'enumColors': [], 'gapClock': 1,
                             'buses': {}, 'sort': True}),
        'bom': '﻿// mine\n{"rowHeight": 30}\n',
        'crlf': '// mine\r\n{\r\n  // "sort": "asc"\r\n  "rowHeight": 30, /* a block */\r\n  "sort": "desc",\r\n}\r\n',
        'inherited': '{"constructor": 1, "__proto__": {"rowHeight": 1}, "toString": "x", "hasOwnProperty": 2, "rowHeight": 28}',
        'vscode_own': '{"theme": "dark", "keysLeft": []}',
        'broken': '{\n  "rowHeight": 30\n  /* not closed\n',
    }

    @classmethod
    def setUpClass(cls):
        cls.r = node(PURE, UCFG, CFG_JS, json.dumps(cls.CASES))

    def test_documented_kinds_taken(self):
        """B-05: the values the comments of wavelens.config.js name, whatever the kind of the default"""
        for case in ('documented', 'also'):
            r = self.r[case]
            self.assertEqual(r['problems'], [], case)
            self.assertEqual(r['config'], json.loads(self.CASES[case]))

    def test_wrong_kinds_refused(self):
        r = self.r['wrong']
        self.assertEqual(r['config'], {})
        self.assertEqual([p['key'] for p in r['problems']], list(json.loads(self.CASES['wrong'])))
        said = {p['key']: p['message'] for p in r['problems']}
        self.assertIn('a string or true / false', said['log'])
        self.assertIn('an object {…}, not a list', said['colors'])

    def test_every_key_its_kinds(self):
        """the kinds table against wavelens.config.js: its keys only; every key of no kind of its own (null) in it; a comment that
        names true / false (not another key's) or a time ('2us') beside another kind: those kinds taken"""
        d, kinds = self.r['defaults'], self.r['kinds']
        self.assertEqual(sorted(set(kinds) - set(d)), [], 'a key of the table that is no setting')
        self.assertEqual(sorted(k for k, v in d.items() if v is None and k not in kinds and k not in self.r['own']), [],
                         'a key whose default (null) says no kind, not in the table: anything would pass')
        kind = lambda v: 'boolean' if isinstance(v, bool) else 'number' if isinstance(v, (int, float)) else 'string' if isinstance(v, str) else \
            'array' if isinstance(v, list) else 'object'
        for k, note in notes().items():
            if k in self.r['own'] or k not in d:
                continue
            have = kinds.get(k, [kind(d[k])])
            if re.search(r'(?<!\w: )\b(true|false)\b', note) and kind(d[k]) != 'boolean':
                self.assertIn('boolean', have, f'{k}: its comment names true / false ({note})')
            if re.search(r"'\d+(\.\d+)?[munpf]?s'", note):
                self.assertIn('string', have, f'{k}: its comment names a time ({note})')

    def test_bom_crlf_comments(self):
        """B-09: a byte order mark read as VS Code shows the file; CRLF, comments, a trailing comma; the keys where they are"""
        self.assertEqual(self.r['bom']['value'], {'rowHeight': 30})
        self.assertEqual(self.r['bom']['keys'], [{'key': 'rowHeight', 'line': 2, 'col': 2}])
        c = self.r['crlf']
        self.assertEqual((c['value'], c['problems']), ({'rowHeight': 30, 'sort': 'desc'}, []))
        self.assertEqual(c['keys'], [{'key': 'rowHeight', 'line': 4, 'col': 3}, {'key': 'sort', 'line': 5, 'col': 3}], 'not the comment naming "sort"')
        b = self.r['broken']
        self.assertTrue(b['error'])
        self.assertEqual((b['line'], b['col']), (4, 1), 'a comment not closed: the end of the file')

    def test_inherited_names_unknown(self):
        """B-09: constructor, __proto__, toString are no settings (not "VS Code's here: function Object()")"""
        r = self.r['inherited']
        self.assertEqual(r['config'], {'rowHeight': 28})
        said = {p['key']: p['message'] for p in r['problems']}
        self.assertEqual(sorted(said), sorted(['constructor', '__proto__', 'toString', 'hasOwnProperty']))
        self.assertTrue(all('is no setting of the viewer' in m for m in said.values()), said)
        self.assertEqual(sorted(p['key'] for p in self.r['vscode_own']['problems']), ['keysLeft', 'theme'])
        self.assertTrue(all("VS Code's here: the setting" in p['message'] for p in self.r['vscode_own']['problems']))

    def test_template_reads_back_clean(self):
        t = self.r['template']
        self.assertIsNone(t['error'])
        self.assertEqual(t['problems'], [])
        self.assertEqual(t['config'], {k: v for k, v in self.r['defaults'].items() if k not in self.r['own']})
        self.assertFalse(set(self.r['effective']) & set(self.r['own']), 'effective: no theme, no keysLeft (VS Code\'s)')


@H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
class ExtensionConfig(unittest.TestCase):
    def test_start_marks_and_ask(self):
        with H.tmp() as d:
            with open(os.path.join(d, 'a.vcd'), 'w', encoding='utf-8') as f:
                f.write('$enddefinitions $end\n')
            with open(os.path.join(d, 'wavelens.config.jsonc'), 'w', encoding='utf-8', newline='') as f:   # saved by a Windows tool
                f.write('﻿// mine\r\n{\r\n  // "sort": "asc" names it\r\n  "rowHeight": 30,\r\n  "sort": 5,\r\n  "constructor": 1\r\n}\r\n')
            o = node(EXT, os.path.join(H.ROOT, 'vscode', 'extension.js'), d)
        self.assertEqual((o['host'] or {}).get('rowHeight'), 30, 'B-09: the file with a BOM applied at start')
        self.assertEqual([m[:2] for m in o['marks']], [[4, 2], [5, 2]], f'B-10: the marks on the keys\' lines, not the comment {o["marks"]}')
        self.assertIn('no setting', o['marks'][1][2])
        self.assertEqual(o['pushed'], [33], 'saved: the tab told')
        self.assertEqual(o['asked'], 33, 'B-10: a tab asking at its load gets the configuration now, not its page\'s copy')


if __name__ == '__main__':
    unittest.main()
