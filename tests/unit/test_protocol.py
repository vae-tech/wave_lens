"""The messages between a tab's page and the extension, one table (vscode/protocol.js; review 2026-11-05 runs A-05, T-09):
the two sources name its types and no other, every type of it walked through the real vscode/extension.js (over the fake
vscode, the real CLI) answered as the table says, a message that is none of it answered with an error; the large dump's
source / codes over the CLI, and an FST's VCD text made (convert) of the FSM example."""
import json, os, re, subprocess, unittest

from . import helpers as H
from .test_vscode_state import FAKE, NODE

SVA = os.environ.get('WAVELENS_SVA')
EXT = os.path.join(H.ROOT, 'vscode', 'extension.js')
PROTO = os.path.join(H.ROOT, 'vscode', 'protocol.js')
HEAD = ('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! s $end\n$var wire 4 " cnt [3:0] $end\n$upscope $end\n'
        '$enddefinitions $end\n')
BODY = '#0\n0!\nb0 "\n#10\n1!\nb11 "\n#20\n0!\n#30\n'

SCRIPT = r'''
const fs = require('fs'), path = require('path');
const [F, ext, dir, protoPath, dump, mode] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
const P = require(protoPath);
process.on('uncaughtException', e => { console.error('UNCAUGHT ' + e.stack); process.exit(3); });
process.on('unhandledRejection', e => { console.error('UNHANDLED ' + (e && e.stack)); process.exit(3); });
const other = path.join(dir, 'other.vcd'), saved = path.join(dir, 'saved.bin'), state = path.join(dir, 's.view.json');
let dialog = other, clip = null;
const h = F.host({ ext, dir, workspaceState: new Map(),
  config: { sva: process.env.WAVELENS_SVA, lazy: mode === 'fsm' ? 'never' : 'always' },
  vscode: { ProgressLocation: { Notification: 15 }, env: { clipboard: { writeText: async t => { clip = t; } } } },
  window: { withProgress: async (o, f) => f(), showWarningMessage: async () => 'Remove', showErrorMessage: async () => undefined,
    showSaveDialog: async () => h.Uri.file(saved), showOpenDialog: async () => [h.Uri.file(dialog)] },
  workspace: { getWorkspaceFolder: () => undefined, fs: { writeFile: async (u, d) => fs.writeFileSync(u.fsPath, d) } } });
let n = 0;
F.run(async () => {
  const A = await h.tab(dump), out = {};
  const ask = async m => { const id = ++n; await A.send(Object.assign({ id }, m)); await new Promise(r => setImmediate(r)); return A.reply(id); };
  const fileOf = src => src.replace(/^file:\/\//, '');
  if (mode === 'fsm') {   // an FST read whole: its VCD text made by sva vcd (convert), kept, made once
    const a = await ask({ type: 'source' }), t1 = fs.statSync(fileOf(a.src)).mtimeMs;
    const b = await ask({ type: 'source' });
    const text = fs.readFileSync(fileOf(a.src), 'utf8');
    return { a, b, same: a.src === b.src && fs.statSync(fileOf(b.src)).mtimeMs === t1, inStore: fileOf(a.src).startsWith(path.join(dir, 'fst')),
      head: text.slice(0, text.indexOf('$enddefinitions')), changes: (text.match(/^#\d+/gm) || []).length,
      left: fs.readdirSync(path.join(dir, 'fst')).filter(f => f.endsWith('.part')) };
  }
  if (mode === 'lazy') {   // a large dump: its FST's header first, then the signals asked by their codes
    const s = await ask({ type: 'source' }), head = fs.readFileSync(fileOf(s.src), 'utf8');
    const code = /\$var \S+ 4 (\S+) cnt/.exec(head)[1];
    return { s, head, code, codes: await ask({ type: 'codes', codes: [code] }), none: await ask({ type: 'codes', codes: [] }),
      fst: fs.readdirSync(path.join(dir, 'fst')).filter(f => f.endsWith('.fst')).length };
  }
  // every type of the table, in its order; the runs' operations in the order that keeps, changes and removes a run
  fs.writeFileSync(state, JSON.stringify({ wavelens: 'state', version: 3 }));
  const REQ = {
    page: {}, source: {}, bytes: {}, codes: { codes: [] }, store: { key: 'k', value: 'v' }, save: { name: 'x.txt', b64: Buffer.from('hi').toString('base64') },
    pick: { accept: '.json', multiple: false, state: true }, 'state-kept': {}, 'state-read': {},
    compare: { signals: ['tb.s', 'tb.cnt'], from: 0, to: 30000 }, sources: {}, config: {}, clip: { text: 'PSEL' }, theme: {},
    result: { rid: 99, results: [] }, ready: { title: 't' }, loaded: { name: 't.vcd', shown: 2, total: 2 },
    dumperror: { name: 't.vcd', error: 'the time goes back', line: 9 }, log: { text: 'a line' }, configerror: { text: 'boom' },
    'es-open': { sid: 1, url: 'http://127.0.0.1:1/events?token=x' }, 'es-close': { sid: 1 },
    http: { url: 'http://127.0.0.1:1/hello?token=x', method: 'POST', body: '{}' },
  };
  const OPS = [['list', {}], ['keep', { name: 'golden', tags: ['base'], comment: 'before' }], ['set', { run: 1, name: 'gold' }],
    ['open', { run: 1 }], ['open', { run: 0 }], ['diff', { signals: ['tb.s'], from: 0, to: 30000, against: 0 }],
    ['compare', { run: 1, signals: ['tb.s', 'tb.cnt'], from: 0, to: 30000 }], ['compare', { run: 1, against: 0, signals: ['tb.s'], from: 0, to: 30000 }],
    ['cancel', {}], ['rm', { run: 1 }]];
  const walked = [];
  for (const type of Object.keys(P.PAGE)) {
    const p = P.PAGE[type];
    const each = p.ops ? OPS.map(([op, b]) => Object.assign({ op }, b)) : [REQ[type]];
    if (p.ops) walked.push({ type, ops: Object.keys(p.ops), walkedOps: OPS.map(o => o[0]) });
    for (const b of each) {
      if (!b) { walked.push({ type, error: 'no request for it in this test' }); continue; }
      dialog = type === 'pick' ? state : other;
      const m = Object.assign({ type }, b), r = await ask(m), spec = P.spec(m);
      walked.push({ type, op: m.op, reply: r ? Object.keys(r).filter(k => k !== 'id') : null, wanted: !!spec.reply,
        ok: spec.reply ? !!r && !r.error && P.answers(m, r) : !r, error: r && r.error });
    }
  }
  // none of the table: an error answered (to a request with an id), nothing thrown
  out.bad = [];
  for (const m of [{ type: 'nope' }, { type: 'codes' }, { type: 'runs', op: 'zap' }, { type: 'runs', op: 'rm' }, { type: 'store', key: 'k' },
    { type: 'runs', op: 'compare', run: 1, signals: [] }, { type: 7 }]) out.bad.push([m, await ask(m)]);
  await A.send(null); await A.send('text'); await A.send([1]);
  out.walked = walked; out.clip = clip; out.saved = fs.existsSync(saved);
  out.said = A.said.filter(m => !m.id).map(m => m.type);
  out.unknownSaid = out.said.filter(t => !(t in P.HOST));
  return out;
});
'''


def node(*args, mode='walk', env=None):
    r = subprocess.run([NODE, '-e', SCRIPT, FAKE, EXT, *args, mode], capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, WAVELENS_SVA=SVA or '', **(env or {})))
    if r.returncode:
        raise AssertionError(f'node exit {r.returncode}\n{r.stderr[-3000:]}')
    return json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])


def table():
    r = subprocess.run([NODE, '-e', 'const P = require(process.argv[1]); console.log(JSON.stringify({ page: P.PAGE, host: P.HOST }))', PROTO],
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return json.loads(r.stdout)


@H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
class Table(unittest.TestCase):
    def test_the_sources_name_its_types(self):
        """extension.js answers the page's types of the table and no other, its runs() the table's operations, it posts the
        host's; host.js sends the page's types and its WAVELENS_RUNS the table's operations, it listens to the host's."""
        t = table()
        page, host, ops = set(t['page']), set(t['host']), set(t['page']['runs']['ops'])
        ext, hjs = H.text(EXT), H.text(os.path.join(H.ROOT, 'vscode', 'media', 'host.js'))
        sw = ext[ext.index('  async message(m) {'):ext.index('  /* A read of the dump')]
        self.assertEqual(set(re.findall(r"case '([a-z-]+)':", sw)), page, 'the types extension.js answers')
        rn = ext[ext.index('  async runs(m) {'):ext.index('  watchRuns(dir)')]
        self.assertEqual(set(re.findall(r"case '([a-z-]+)':", rn)), ops, 'the operations of its runs()')
        posted = set(re.findall(r"post\(\{ type: '([a-z-]+)'", ext))
        self.assertTrue(posted and posted <= host, f'extension.js posts {posted - host} the table has not')
        sent = set(re.findall(r"call\('([a-z-]+)'", hjs)) | set(re.findall(r"\{ type: '([a-z-]+)'", hjs))
        self.assertTrue(sent and sent <= page, f'host.js sends {sent - page} the table has not')
        self.assertEqual(set(re.findall(r"on(?:\.|\[')([a-z-]+)'?\]? = ", hjs)), host, 'the host\'s types host.js listens to')
        runs = hjs[hjs.index('G.WAVELENS_RUNS = {'):hjs.index('/* ---- clipboard')]
        self.assertTrue(set(re.findall(r"op: '([a-z]+)'", runs)) <= ops)


@H.needs(SVA, 'the sva CLI ($WAVELENS_SVA, make unit sets it)')
@H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
class Walk(unittest.TestCase):
    def test_every_type_through_the_extension(self):
        with H.tmp() as d:
            p = H.vcd(d, BODY, HEAD, name='t.vcd')
            H.vcd(d, BODY.replace('#10\n1!', '#15\n1!'), HEAD, name='other.vcd')
            o = node(d, PROTO, p)
        walked = o['walked']
        runs = next(w for w in walked if 'walkedOps' in w)
        self.assertEqual(sorted(runs['ops']), sorted(set(runs['walkedOps'])), 'every operation of runs walked')
        bad = [w for w in walked if 'walkedOps' not in w and not w.get('ok')]
        self.assertFalse(bad, 'answered as the table says (an answer where it names one, none where not)')
        self.assertEqual({w['type'] for w in walked}, set(table()['page']), 'every type of the table walked')
        self.assertEqual((o['clip'], o['saved']), ('PSEL', True))
        errs = [(m, r and r.get('error')) for m, r in o['bad']]
        self.assertTrue(all(e for _, e in errs), f'a message none of the table\'s: an error answered {errs}')
        self.assertEqual([e for _, e in errs][:6], ['no message nope', 'codes: without codes', 'runs: no operation zap', 'runs rm: without run',
                                                   'store: without value', 'runs compare: without from, to'])
        self.assertEqual(o['unknownSaid'], [], 'what the extension posted by itself is of the host\'s table')


@H.needs(SVA, 'the sva CLI ($WAVELENS_SVA, make unit sets it)')
@H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
class Dump(unittest.TestCase):
    def test_a_large_dump_source_then_codes(self):
        """T-09: wavelens.lazy always: the source is the header of the dump's FST (sva fst, then sva vcd --header: no value),
        a signal's values come by its code (sva vcd --codes), the others not."""
        with H.tmp() as d:
            p = H.vcd(d, BODY, HEAD, name='t.vcd')
            o = node(d, PROTO, p, mode='lazy')
        self.assertEqual((o['s']['lazy'], o['s']['name'], o['fst']), (True, 't.vcd', 1), o['s'])
        self.assertIn('$var wire 1 ! s $end', o['head'])
        self.assertEqual(o['head'].split('$enddefinitions $end')[1].split(), ['#0', '#30'], 'the header: no value')
        text = o['codes']['text']
        self.assertIn('cnt [3:0]', text)
        self.assertNotIn(' s $end', text, 'only the signal asked')
        self.assertEqual(re.findall(r'^b(\d+) ', text, re.M), ['0000', '0011'], text)
        self.assertNotIn('$var', o['none']['text'], 'no code: no signal')

    def test_the_fsm_examples_fst_as_vcd_text(self):
        """T-09: an FST read whole: its VCD text made by the CLI (convert) into the extension's storage, kept and made once,
        no part file left; the FSM example's (built by make examples)."""
        fst = os.path.join(H.BUILD, 'examples', 'fsm', 'fsm.fst')
        if not os.path.isfile(fst):
            H.skip(self, f'{fst}: make example EX=fsm')
        with H.tmp() as d:
            o = node(d, PROTO, fst, mode='fsm')
        self.assertEqual((o['a']['lazy'], o['a']['name']), (False, 'fsm.fst'))
        self.assertTrue(o['same'] and o['inStore'], 'made once, in the extension\'s storage')
        self.assertIn('$scope module fsm_tb $end', o['head'])
        self.assertRegex(o['head'], r'\$var \S+ \d+ \S+ state ')
        self.assertGreater(o['changes'], 10)
        self.assertEqual(o['left'], [])


if __name__ == '__main__':
    unittest.main()
