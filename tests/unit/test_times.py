"""One table of times (tests/unit/times.json) against every reader of one (review 2026-11-05 runs A-08): tools/common.py parse_time with
its callers' plain-number conventions (viewedit, testmarks, wavemcp, vcd2wavedrom), the page's parseT (wavelens/src/model.js) and
vscode/links.js through node, the cocotb library's bound_ps, the sva CLI's time() through `sva diff --from`. A reader that reads a
case otherwise says so in the case's "except"; a new reader or a change of one is a row here, not a drift found by a user."""
import json, math, os, re, subprocess, sys, unittest

from . import helpers as H
from .test_vscode_state import NODE

sys.path.insert(0, os.path.join(H.ROOT, 'python'))
import common, testmarks, vcd2wavedrom, viewedit, wavemcp  # noqa: E402
import wavelens_cocotb  # noqa: E402

TABLE = H.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'times.json'))
SVA = os.environ.get('WAVELENS_SVA')

# parseT and its table cut out of model.js (the page's sources are one scope, not modules), linksOf of links.js as the extension
# requires it; each case -> its ps or null
NODE_SCRIPT = r'''
const fs = require('fs'), [model, links, cases] = process.argv.slice(1), src = fs.readFileSync(model, 'utf8');
const unit = /^const UNIT_PS = .*;$/m.exec(src)[0], fn = /^function parseT\(v\) \{[\s\S]*?\n\}$/m.exec(src)[0];
const parseT = new Function(`${unit}\n${fn}\nreturn parseT;`)(), L = require(links);
const link = t => { const s = '@ ' + t, l = L.linksOf(s).find(x => x.start === 0 && x.end === s.trimEnd().length && x.ps != null);
  return l ? l.ps : null; };
const out = JSON.parse(cases).map(t => ({ parseT: parseT(t) ?? null, links: link(t) }));
console.log('RESULT' + JSON.stringify(out));
'''


def none_on_error(f):
    def g(t):
        try:
            return f(t)
        except (ValueError, common.WaveError):
            return None
    return g


PY_READERS = {
    'common': common.parse_time,
    'wavemcp': none_on_error(wavemcp.ps_of),
    'vcd2wavedrom': none_on_error(vcd2wavedrom.to_ps),
    'cocotb': none_on_error(wavelens_cocotb.bound_ps),
}


class Times(unittest.TestCase):
    def want(self, case, reader):
        return case.get('except', {}).get(reader, case['ps'])

    def same(self, got, want, msg):
        if want is None or got is None:
            self.assertEqual(got, want, msg)
        else:
            self.assertTrue(math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-12), f'{msg}: {got!r}, want {want!r}')

    def test_table(self):
        self.assertEqual(sorted(TABLE['readers']), sorted([*PY_READERS, 'parseT', 'links', 'cli']), 'a reader of the table without a runner')
        for c in TABLE['cases']:
            self.assertFalse(set(c.get('except', {})) - set(TABLE['readers']), c)
        self.assertTrue(any('µ' in c['t'] for c in TABLE['cases']) and any('μ' in c['t'] for c in TABLE['cases']),
                        'the micro sign read, the Greek mu not (one table of units)')

    def test_python_readers(self):
        for c in TABLE['cases']:
            for name, f in PY_READERS.items():
                with self.subTest(t=c['t'], reader=name):
                    self.same(f(c['t']), self.want(c, name), f'{name}({c["t"]!r})')
            with self.subTest(t=c['t'], reader='viewedit / testmarks'):
                self.same(viewedit.parse_t(c['t']), self.want(c, 'common'), f'viewedit.parse_t({c["t"]!r})')
                self.same(testmarks.window({'from': c['t']})[0], self.want(c, 'common'), f'testmarks.window({c["t"]!r})')

    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_page_and_links(self):
        texts = [c['t'] for c in TABLE['cases']]
        r = subprocess.run([NODE, '-e', NODE_SCRIPT, os.path.join(H.ROOT, 'wavelens', 'src', 'model.js'), os.path.join(H.ROOT, 'vscode', 'links.js'),
                            json.dumps(texts)], capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
        for c, g in zip(TABLE['cases'], got):
            for name in ('parseT', 'links'):
                with self.subTest(t=c['t'], reader=name):
                    self.same(g[name], self.want(c, name), f'{name}({c["t"]!r})')

    @H.needs(SVA, 'the sva CLI ($WAVELENS_SVA, make unit sets it)')
    def test_cli(self):
        """The window's start of `sva diff A A --from T --json` is T in whole ps; a time it refuses: exit 2."""
        with H.tmp() as d:
            p = H.vcd(d, '#0\n0!\n#100000000000000\n1!\n', '$timescale 1ps $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n'
                      '$enddefinitions $end\n')
            for c in TABLE['cases']:
                with self.subTest(t=c['t']):
                    r = subprocess.run([SVA, 'diff', p, p, '--from', c['t'], '--json'], capture_output=True, text=True, encoding='utf-8')
                    want = self.want(c, 'cli')
                    if want is None:
                        self.assertEqual(r.returncode, 2, f'{c["t"]!r}: {r.stdout}{r.stderr}')
                        self.assertTrue(re.search(r'time', r.stderr), r.stderr)
                    else:
                        self.assertEqual(r.returncode, 0, f'{c["t"]!r}: {r.stderr}')
                        self.assertEqual(json.loads(r.stdout)['from'], round(want), c['t'])


if __name__ == '__main__':
    unittest.main()
