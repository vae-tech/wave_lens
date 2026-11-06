"""One rule of naming a signal (review 2026-11-05 runs A-07): tools/common.py pick and every reader built on it give one
answer per spelling — viewedit.py Model.pick (a page's rows), vcd2wavedrom.py Builtin.resolve (a config's signals),
wavemcp.py Wave.find (an agent's names), svabuild.py Names.lookup (an assertion's names: the full path only, then its
aliases). The page's twin, wavelens/src/edit.js pickRows, is compared with viewedit.py in make smoke (section edit)."""
import unittest

from tests.unit import helpers as H
import common, dumpscan, svabuild, vcd2wavedrom, viewedit, wavemcp

HEAD = ('$timescale 1ns $end\n$scope module top $end\n$var wire 1 ! clk $end\n'
        '$scope module u $end\n$var wire 1 " clk $end\n$upscope $end\n'
        '$scope module dut $end\n$var logic 2 # state [1:0] $end\n$var logic 8 $ data [7:0] $end\n'
        '$scope module fifo $end\n$var logic 8 % count [7:0] $end\n$upscope $end\n$upscope $end\n'
        '$scope module other $end\n$var wire 1 & state $end\n$upscope $end\n'
        "$var logic 8 ' mem[1] [7:0] $end\n$upscope $end\n$enddefinitions $end\n")
BODY = "#0\n0!\n0\"\nb0 #\nb0 $\nb0 %\n0&\nb0 '\n#10\n1!\n1\"\nb1 #\nb101 $\n#20\n"
# the same rows as a page shows them (mkhtml.py of that dump: an array element is a row [1] under a group mem)
PAGE = {'signal': [['top', {'name': 'clk', 'wave': 'p.'}, ['u', {'name': 'clk', 'wave': 'p.'}],
                    ['dut', {'name': 'state', 'wave': '==', 'data': ['0', '1'], 'width': 2}, {'name': 'data', 'wave': '==', 'data': ['0', '5'], 'width': 8},
                     ['fifo', {'name': 'count', 'wave': '=.', 'data': ['0'], 'width': 8}]],
                    ['other', {'name': 'state', 'wave': '0.'}], ['mem', {'name': '[1]', 'wave': '=.', 'data': ['0'], 'width': 8}]]]}

AMB, NONE = 'ambiguous', 'no signal'
# name -> what the page (viewedit.py), a config (vcd2wavedrom.py) and an agent (wavemcp.py) take; one value: all three alike
TABLE = [
    ('top.dut.state', 'top.dut.state'),                 # 1. the full path
    ('dut.state', 'top.dut.state'),                     # 3. the end of a path
    ('fifo.count', 'top.dut.fifo.count'),
    ('count', 'top.dut.fifo.count'),
    ('clk', 'top.clk'),                                 # one net at several levels: the one nearest the top (a config: was "no signal")
    ('u.clk', 'top.u.clk'),
    ('state', AMB),                                     # two at one level
    ('x.top.dut.state', 'top.dut.state'),               # 4. a longer path ending with one (a config, an agent: was "no signal")
    ('mem[1]', 'top.mem.[1]'),                          # an array element either way (the page: was "no signal")
    ('mem.[1]', 'top.mem.[1]'),
    ('top.mem[1]', 'top.mem.[1]'),
    ('top.mem..[1]', 'top.mem.[1]'),
    ('top.dut.data[3]', 'top.dut.data[3]'),             # 5. a bit of a bus (a config: was "no signal")
    ('nosuch', NONE),
    # the step "bit" is each reader's own: a page's bits of a shown bus by its full path (view.js sigByPath); a dump's
    # select of a vector found by the whole rule, a range too, its bits checked
    ('data[3]', (NONE, 'top.dut.data[3]', 'top.dut.data[3]')),
    ('dut.data[7:4]', (NONE, 'top.dut.data[7:4]', 'top.dut.data[7:4]')),
    ('top.dut.data[9]', (NONE, 'has bits [7:0]', 'has bits [7:0]')),
]


def said(f, name):
    """A reader's answer: the path ("…[msb:lsb]" of a select, "…[bit]" of one bit), else the error."""
    try:
        got = f(name)
    except common.WaveError as e:
        return str(e)
    if isinstance(got, tuple):
        path, sl = got
        return path if not sl else f'{path}[{sl[0]}]' if sl[0] == sl[1] else f'{path}[{sl[0]}:{sl[1]}]'
    return got


class OneRule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = H.tmp()
        cls.vcd = H.vcd(cls.d.name, BODY, HEAD)

    @classmethod
    def tearDownClass(cls):
        cls.d.cleanup()

    def readers(self, scope=''):
        conv = vcd2wavedrom.Builtin(self.vcd, scope)
        agent = wavemcp.Wave(self.vcd)
        page = viewedit.Model(PAGE)
        return {'page': lambda n: page.pick({}, n, one=True)[0]['full'], 'config': conv.resolve, 'agent': lambda n: agent.find(n, scope)}

    def test_table(self):
        rd = self.readers()
        for name, want in TABLE:
            for (who, f), w in zip(rd.items(), want if isinstance(want, tuple) else (want,) * 3):
                with self.subTest(name=name, reader=who):
                    got = said(f, name)
                    if w in (AMB, NONE) or w.startswith('has bits'):
                        self.assertIn(w, got)
                    else:
                        self.assertEqual(got, w)

    def test_scope(self):
        """A config's --scope and an agent's "scope": the path under it first, the ends of paths under it only."""
        rd = self.readers('top.other')
        for who in ('config', 'agent'):
            with self.subTest(reader=who):
                self.assertEqual(said(rd[who], 'state'), 'top.other.state')
                self.assertEqual(said(rd[who], 'top.dut.state'), 'top.dut.state')   # a full path as it is
                self.assertIn(NONE, said(rd[who], 'count'))                        # not under the scope

    def test_the_nearest_is_said(self):
        wavemcp.NOTES.clear()
        self.assertEqual(wavemcp.Wave(self.vcd).find('clk'), ('top.clk', None))
        self.assertEqual(wavemcp.NOTES, ['clk = top.clk (+1 deeper)'])
        wavemcp.NOTES.clear()

    def test_pick(self):
        """common.pick itself: the steps in order, the rows as given, how many deeper paths were left out."""
        pool = [{'p': 'a.x', 'n': 'X'}, {'p': 'a.b.x', 'n': 'x'}, {'p': 'a.q.[0]', 'n': '[0]'}, {'p': 'a.b.q[0]', 'n': 'q[0]'}]
        P = lambda s, **o: [(r['p'] if isinstance(r, dict) else r) for r in common.pick(pool, s, full=lambda r: r['p'], **o)[0]]
        self.assertEqual(common.pick(pool, 'x', full=lambda r: r['p'])[1], 1)
        self.assertEqual(P('x'), ['a.x'])
        self.assertEqual(P('x', name=lambda r: r['n']), ['a.b.x'])            # a row's own name before the end of a path
        self.assertEqual(P('q[0]'), ['a.q.[0]'])                                # an element at its array's level: the nearest
        self.assertEqual(P('a.b.q.[0]'), ['a.b.q[0]'])                          # either spelling of a full path
        self.assertEqual(P('x', scope='a.b'), ['a.b.x'])
        self.assertEqual(P('z.a.x'), ['a.x'])
        self.assertEqual(P('b.q[0]', bit=lambda s: 'BIT'), ['a.b.q[0]'])        # an element's path first ...
        self.assertEqual(P('y[1]', bit=lambda s: 'BIT'), ['BIT'])               # ... a bit last
        self.assertEqual(P('x', tails=False), [])                               # the full path only
        self.assertEqual(common.depth('a.q.[0]'), 1)

    def test_assertion_names(self):
        """svabuild.py Names.lookup: an assertion's name in its instance, by the full path of the rule (an element either
        way), then the shown names; no end of a path (an instance has its own names: candidates() would take any)."""
        widths = {p: v.width for p, v in dumpscan.read(self.vcd, None).vars.items()}
        n = svabuild.Names(widths, {'top.dut.data': 'DATA'})
        self.assertEqual(n.lookup('top', 'dut.state'), 'top.dut.state')
        self.assertEqual(n.lookup('top.dut', 'state'), 'top.dut.state')
        self.assertEqual(n.lookup('top', 'mem[1]'), 'top.mem.[1]')
        self.assertEqual(n.lookup('top.dut', 'DATA'), 'top.dut.data')
        self.assertIsNone(n.lookup('top', 'state'))
        self.assertIsNone(n.lookup('top', 'count'))
        self.assertEqual(n.candidates([{'name': 'clk'}, {'name': 'state'}]), ['top.dut', 'top.other'])   # the clock also above


if __name__ == '__main__':
    unittest.main()
