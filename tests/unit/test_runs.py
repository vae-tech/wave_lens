"""The runs kept of a dump: `sva runs` (keep, list, set, rm, path, diff over a window), wave_runs of the MCP server over it, and
the VS Code extension's half of the Runs panel (vscode/extension.js over a fake vscode, the real CLI): keep, list, set, a run
compared over a window only, Δ all, rm asked first."""
import json, os, subprocess, unittest

from . import helpers as H
from .test_vscode_state import FAKE, NODE

SVA = os.environ.get('WAVELENS_SVA')
HEAD = ('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 4 " cnt [3:0] $end\n$var wire 1 # ok $end\n'
        '$upscope $end\n$enddefinitions $end\n')


def body(bad_at=None):
    """40 ns of a counter: cnt counts each rising edge of clk; from bad_at on, ok goes 0 (a run that broke there)."""
    out = ['#0', '0!', 'b0 "', '1#']
    for t in range(5, 41, 5):
        out += [f'#{t}', f'{t // 5 % 2}!']
        if t % 10 == 5:
            out.append(f'b{bin(t // 10)[2:]} "')
        if bad_at is not None and t == bad_at:
            out.append('0#')
    return '\n'.join(out) + '\n'


def cases(longer=0):
    """Two test cases: t_a holds cnt at 0 for 20 ns (+ longer), t_b counts it up every 5 ns for 20 ns -> (the VCD's body, t_b's start
    in ns)."""
    b, out = 20 + longer, ['#0', '0!', 'b0 "', '1#']
    for t in range(5, b + 21, 5):
        out += [f'#{t}', f'{t // 5 % 2}!'] + ([f'b{bin((t - b) // 5)[2:]} "'] if t > b else [])
    return '\n'.join(out) + '\n', b


def sva(*args, stdin=None):
    r = subprocess.run([SVA, *args], capture_output=True, text=True, input=stdin)
    return r.returncode, r.stdout, r.stderr


@H.needs(SVA, 'the sva CLI ($WAVELENS_SVA, make unit sets it)')
class Cli(unittest.TestCase):
    def test_keep_list_set_rm(self):
        with H.tmp() as d:
            p = H.vcd(d, body(), HEAD, name='waves.vcd')
            code, out, err = sva('runs', 'keep', p, '--name', 'golden', '--tags', 'base, seed1', '--comment', 'before the fix', '--json')
            self.assertEqual(code, 0, err)
            r = json.loads(out)
            runs = os.path.join(d, '.wavelens-runs')
            self.assertEqual((r['id'], r['name'], r['tags'], r['comment'], r['dump'], r['end']), (1, 'golden', ['base', 'seed1'], 'before the fix', 'waves.vcd', 40000))
            self.assertTrue(os.path.isfile(os.path.join(runs, '1-waves.fst')), 'kept as an FST in .wavelens-runs beside the dump')
            self.assertIn('*', H.text(os.path.join(runs, '.gitignore')), 'the directory ignores itself in git')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(HEAD + body(25))
            self.assertEqual(sva('runs', 'keep', p)[0], 0)
            code, out, _ = sva('runs', 'list', p, '--json')
            v = json.loads(out)
            self.assertEqual([(x['id'], x['name']) for x in v['runs']], [(1, 'golden'), (2, 'waves.vcd')], 'the name by default: the dump\'s')
            code, out, _ = sva('runs', '--dir', runs)
            self.assertLess(out.index('#2'), out.index('#1'), f'the text: newest first\n{out}')
            self.assertEqual(sva('runs', 'set', '#2', '--dir', runs, '--name', 'broken', '--tags', '')[0], 0)
            self.assertEqual(json.loads(sva('runs', 'set', 'broken', '--dir', runs, '--comment', 'ok falls', '--json')[1])['tags'], [], 'tags emptied')
            self.assertEqual(sva('runs', 'path', 'golden', '--dir', runs)[1].strip(), os.path.join(runs, '1-waves.fst'))
            code, _, err = sva('runs', 'set', '9', '--dir', runs, '--name', 'x')
            self.assertEqual((code, 'no run 9' in err), (2, True), err)
            self.assertEqual(sva('runs', 'rm', 'broken', '--dir', runs)[0], 0)
            self.assertFalse(os.path.exists(os.path.join(runs, '2-waves.fst')), 'rm: its FST gone too')
            self.assertEqual(sva('runs', 'keep', p, '--json')[0], 0)
            self.assertEqual([x['id'] for x in json.loads(sva('runs', 'list', '--dir', runs, '--json')[1])['runs']], [1, 3], 'a number never taken again')
            self.assertEqual(sva('runs', 'keep', os.path.join(runs, '1-waves.fst'), '--dir', runs, '--name', 'copy', '--json')[0], 0, 'an FST: copied')

    def test_diff_over_a_window(self):
        with H.tmp() as d:
            p = H.vcd(d, body(), HEAD, name='waves.vcd')
            sva('runs', 'keep', p, '--name', 'golden')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(HEAD + body(25))
            sva('runs', 'keep', p, '--name', 'broken')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(HEAD + body())
            code, out, err = sva('runs', 'diff', p, '--json')
            self.assertEqual(code, 1, err)
            v = json.loads(out)
            by = {x['name']: x for x in v['runs']}
            self.assertEqual([x['name'] for x in v['runs']], ['broken', 'golden'], 'newest first')
            self.assertTrue(by['golden']['equal'])
            self.assertEqual((by['broken']['signals_differ'], by['broken']['first']['t'], by['broken']['first']['signal'], by['broken']['signals'][0]['path']),
                             (1, 25000, 'tb.ok', 'tb.ok'))
            code, out, _ = sva('runs', 'diff', p, '--from', '0', '--to', '20ns', '--json')
            self.assertEqual(code, 0, 'before 25 ns: every run equal')
            self.assertEqual(json.loads(out)['to'], 20000)
            code, out, _ = sva('runs', 'diff', p, '--run', 'broken', '--signals-from', '-', '--json', stdin='tb.cnt\n')
            self.assertEqual((code, [x['signals_compared'] for x in json.loads(out)['runs']]), (0, [1]), 'the signals of stdin, one run')
            code, out, _ = sva('runs', 'diff', p)
            self.assertIn('#2 broken: 1 of 3 signals differ, first at 25 ns (tb.ok)', out)


@H.needs(SVA, 'the sva CLI ($WAVELENS_SVA)')
class Mcp(unittest.TestCase):
    def test_wave_runs(self):
        os.environ.setdefault('WAVELENS_SVA', SVA)
        from tools import wavemcp as W
        call = lambda **a: (lambda r: json.loads(r[0]) if not r[1] else self.fail(r[0]))(W.call('wave_runs', a))
        with H.tmp() as d:
            p = H.vcd(d, body(), HEAD, name='waves.vcd')
            k = call(action='keep', dump=p, name='golden', tags='a,b')
            self.assertEqual((k['id'], k['tags'], k['end'], k['unit']), (1, ['a', 'b'], 40, 'ns'))
            with open(p, 'w', encoding='utf-8') as f:
                f.write(HEAD + body(25))
            r = call(action='diff', dump=p, **{'from': 20, 'to': 40})
            x = r['runs'][0]
            self.assertEqual((r['from'], r['to'], x['signals_differ'], x['first']['t'], x['first']['signal']), (20, 40, 1, 25, 'tb.ok'), r)
            self.assertEqual(call(action='set', dump=p, run=1, comment='c')['comment'], 'c')
            self.assertEqual([x['name'] for x in call(dump=p)['runs']], ['golden'])
            q = H.vcd(d, body(25), HEAD, name='other.vcd')
            call(action='keep', dump=q, name='other')
            self.assertEqual(([x['name'] for x in call(dump=p)['runs']], call(dump=p)['others']), (['golden'], 1), 'the runs of this dump, the others counted')
            self.assertEqual(len(call(dump=p, all=True)['runs']), 2)
            rm = call(action='rm', dir=os.path.join(d, '.wavelens-runs'), run='golden')
            self.assertEqual((rm['removed'][0]['id'], rm['removed'][0]['end'], rm['unit']), (1, 40, 'ns'), 'rm answers in ns (B-23)')
            bad = W.call('wave_runs', {'action': 'set', 'dump': p})
            self.assertTrue(bad[1] and '"run"' in bad[0], bad)

    def test_wave_runs_by_test_case(self):
        os.environ.setdefault('WAVELENS_SVA', SVA)
        from tools import wavemcp as W
        call = lambda **a: (lambda r: json.loads(r[0]) if not r[1] else self.fail(r[0]))(W.call('wave_runs', a))
        with H.tmp() as d:
            text, b = cases()
            p = H.vcd(d, text, HEAD, name='waves.vcd')
            k = call(action='keep', dump=p, name='before', cases=[{'name': 't_a', 'from': 0, 'to': b}, {'name': 't_b', 'from': b, 'to': b + 20}])
            self.assertEqual(k['cases'][1], {'name': 't_b', 'from': 20, 'to': 40}, 'cases in ns, as every time of the tool')
            text, b = cases(10)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(HEAD + text)
            r = call(action='diff', dump=p, case='t_b', **{'from': b, 'to': b + 20})
            x = r['runs'][0]
            self.assertEqual((r['case']['name'], x['equal'], x['case']['offset'], x['case']['from']), ('t_b', True, -10, 20), r)
            self.assertFalse(call(action='diff', dump=p, **{'from': b, 'to': b + 20})['runs'][0]['equal'], 'the same window without the case differs')


EXT = r'''
const [F, ext, dir, dump, mode] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
let warned = null, answer = 'Remove';
const h = F.host({ ext, dir, config: { sva: process.env.WAVELENS_SVA }, vscode: { ProgressLocation: { Notification: 15 } },
  window: { withProgress: async (o, f) => f(), showWarningMessage: async (m) => { warned = m; return answer; } },
  workspace: { getWorkspaceFolder: () => undefined } });
process.on('uncaughtException', e => { console.error('UNCAUGHT ' + e.message); process.exit(3); });
(async () => {
  const A = await h.tab(dump);
  let n = 100; const ask = async m => { const id = ++n; await A.send(Object.assign({ type: 'runs', id }, m)); return A.reply(id); };
  const out = {};
  if (mode === 'stress') {   // a CLI that exits before it reads: 50 asks with a large stdin each, every one answered
    const big = Array.from({ length: 20000 }, (_, i) => 'tb.s' + i), got = await Promise.all(Array.from({ length: 50 }, (_, i) =>
      ask({ op: i % 2 ? 'diff' : 'compare', run: 1, signals: big, from: 0, to: 1000 })));
    console.log('RESULT' + JSON.stringify({ answered: got.filter(Boolean).length })); process.exit(0);
  }
  if (mode === 'cases') {   // a run's test cases: kept from the page's spans, then its case compared wherever it is in the run
    out.keep = await ask({ op: 'keep', name: 'before', cases: [{ label: 'TC1 t_a \u00b7 PASS', from: 0, to: 20000 }, { label: 'TC2 t_b \u00b7 PASS', from: 20000, to: 40000 }] });
    require('fs').writeFileSync(dump, process.env.LATER);
    out.compare = await ask({ op: 'compare', run: 1, case: 't_b', signals: ['tb.cnt'], from: 30000, to: 50000 });
    out.plain = await ask({ op: 'compare', run: 1, signals: ['tb.cnt'], from: 30000, to: 50000 });
    out.diff = await ask({ op: 'diff', case: 't_b', signals: ['tb.cnt'], from: 30000, to: 50000 });
    out.none = await ask({ op: 'compare', run: 1, case: 't_z', signals: ['tb.cnt'], from: 30000, to: 50000 });
    console.log('RESULT' + JSON.stringify(out)); process.exit(0);
  }
  out.empty = await ask({ op: 'list' });
  out.keep = await ask({ op: 'keep', name: 'golden', tags: ['base'], comment: 'before' });
  require('fs').writeFileSync(dump, process.env.BROKEN);
  out.keep2 = await ask({ op: 'keep', name: '' });
  out.set = await ask({ op: 'set', run: 2, name: 'broken', tags: [] });
  out.list = await ask({ op: 'list' });
  require('fs').writeFileSync(dump, process.env.GOOD);
  out.diff = await ask({ op: 'diff', signals: ['tb.ok', 'tb.cnt'], from: 20000, to: 40000 });
  out.compare = await ask({ op: 'compare', run: 2, signals: ['tb.ok', 'tb.cnt'], from: 20000, to: 40000 });
  answer = undefined; out.kept = await ask({ op: 'rm', run: 2 }); out.warned = warned;
  answer = 'Remove'; out.rm = await ask({ op: 'rm', run: 2 });
  out.after = await ask({ op: 'list' });
  console.log('RESULT' + JSON.stringify(out)); process.exit(0);
})().catch(e => { console.error(e.stack); process.exit(1); });
'''


@H.needs(SVA, 'the sva CLI ($WAVELENS_SVA)')
@H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
class VsCode(unittest.TestCase):
    def test_the_runs_panel_host(self):
        with H.tmp() as d:
            p = H.vcd(d, body(), HEAD, name='waves.vcd')
            env = dict(os.environ, WAVELENS_SVA=SVA, GOOD=HEAD + body(), BROKEN=HEAD + body(25))
            r = subprocess.run([NODE, '-e', EXT, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d, p], capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            o = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
            runs = os.path.join(d, '.wavelens-runs')
            self.assertEqual((o['empty']['dir'], o['empty']['runs']), (runs, []), 'none yet: an empty list, beside the dump')
            self.assertEqual((o['keep']['run']['id'], o['keep']['run']['tags']), (1, ['base']))
            self.assertEqual(o['keep2']['run']['name'], 'waves.vcd', 'no name: the dump\'s')
            self.assertEqual([(x['id'], x['name'], x['tags']) for x in o['list']['runs']], [(1, 'golden', ['base']), (2, 'broken', [])])
            by = {x['id']: x for x in o['diff']['runs']}
            self.assertEqual((by[1]['equal'], by[2]['signals_differ'], by[2]['from'], by[2]['to']), (True, 1, 20000, 40000), o['diff'])
            c = o['compare']['result']
            self.assertEqual((c['from'], c['to'], c['differ'], c['first']), (20000, 40000, 1, 25000), 'compared over the window only')
            self.assertEqual(c['signals']['tb.ok']['spans'], [[25000, 40000]])
            self.assertIn('$var', c.get('vcd', ''), 'the run\'s values of the window, for B and A+B')
            self.assertTrue(o['kept'].get('cancelled') and '#2 broken' in o['warned'], 'rm asks first; no answer: kept')
            self.assertEqual(o['rm']['removed']['id'], 2)
            self.assertEqual([x['id'] for x in o['after']['runs']], [1])

    def test_a_run_compared_by_its_test_case(self):
        with H.tmp() as d:
            (early, _), (later, _) = cases(), cases(10)
            p = H.vcd(d, early, HEAD, name='waves.vcd')
            env = dict(os.environ, WAVELENS_SVA=SVA, LATER=HEAD + later)
            r = subprocess.run([NODE, '-e', EXT, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d, p, 'cases'], capture_output=True, text=True, timeout=60, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            o = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
            self.assertEqual([c['name'] for c in o['keep']['run']['cases']], ['t_a', 't_b'], 'the page\'s span labels as the cases\' names')
            c = o['compare']['result']
            self.assertEqual((c['differ'], c['case']['offset'], c['case']['from']), (0, -10000, 20000), o['compare'])
            self.assertGreater(o['plain']['result']['differ'], 0, 'the same window, not by the case: it differs')
            self.assertEqual((o['diff']['runs'][0]['equal'], o['diff']['runs'][0]['case']['offset']), (True, -10000), o['diff'])
            self.assertIn('no case t_z', o['none']['error'])

    def test_a_cli_that_exits_before_reading(self):
        """B-02 of the review of the runs: the CLI's stdin guarded — a CLI that exits at once (here a stub) with a large
        stdin to write is no EPIPE thrown out of the extension; every ask is answered."""
        with H.tmp() as d:
            stub = os.path.join(d, 'sva')
            with open(stub, 'w', encoding='utf-8') as f:
                f.write('#!/bin/sh\nexit 2\n')
            os.chmod(stub, 0o755)
            os.makedirs(os.path.join(d, '.wavelens-runs'))
            with open(os.path.join(d, '.wavelens-runs', 'runs.json'), 'w', encoding='utf-8') as f:
                json.dump({'wavelens': 'runs', 'version': 1, 'runs': [{'id': 1, 'name': 'a', 'file': '1-t.fst'}]}, f)
            p = H.vcd(d, body(), HEAD, name='t.vcd')
            r = subprocess.run([NODE, '-e', EXT, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d, p, 'stress'], capture_output=True, text=True,
                               timeout=120, env=dict(os.environ, WAVELENS_SVA=stub))
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            self.assertEqual(json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])['answered'], 50)
