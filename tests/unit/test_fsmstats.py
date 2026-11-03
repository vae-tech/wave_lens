"""tools/fsmstats.py: an FSM's states in a dump (stage 25), the rule of the page's FSM panel (smoke fsm_shell compares the two)."""
import json, os, unittest
from tests.unit import helpers as H
import fsmstats as F
import wavemcp as W

TABLE = {0: 'IDLE', 1: 'RUN', 2: 'DONE', 3: 'ERR'}


class Stats(unittest.TestCase):
    def test_entries_time_never_invalid_changes(self):
        st = [(0, 'x'), (10, '0'), (20, '1'), (25, '1'), (40, '2'), (50, '1'), (60, '2'), (70, '5'), (80, '0')]
        s = F.stats(st, 3, TABLE, 0, 100)
        by = {x['state']: (x['entries'], x['first'], x['time']) for x in s['states']}
        self.assertEqual(by, {'IDLE': (2, 10, 30), 'RUN': (2, 20, 30), 'DONE': (2, 40, 20), 'ERR': (0, None, 0)})
        self.assertEqual(s['never'], ['ERR'])
        self.assertEqual([(x['state'], x['time']) for x in s['invalid']], [('X', 10), ('5 (no label)', 10)])
        self.assertEqual([(c['from'], c['to'], c['count']) for c in s['changes']][:2], [('RUN', 'DONE', 2), ('X', 'IDLE', 1)], 'the most frequent first')
        self.assertEqual(sum(x['time'] for x in s['states'] + s['invalid']), 100, 'held until the next change, the last to the end')

    def test_a_window(self):
        st = [(0, '0'), (20, '1'), (40, '2')]
        s = F.stats(st, 2, TABLE, 30, 50)
        self.assertEqual([(x['state'], x['entries'], x['first'], x['time']) for x in s['states'] if x['entries']],
                         [('RUN', 1, 30, 10), ('DONE', 1, 40, 10)], 'the value the window starts with is its first entry')

    def test_no_value_when_the_window_starts(self):
        """Review S25-4: a state first written after the window's start is x until then, as the page counts it."""
        s = F.stats([(10, '1'), (30, '2')], 2, TABLE, 0, 50)
        self.assertEqual([(x['state'], x['entries'], x['first'], x['time']) for x in s['invalid']], [('X', 1, 0, 10)])
        self.assertEqual([(c['from'], c['to']) for c in s['changes']], [('X', 'RUN'), ('RUN', 'DONE')])
        self.assertEqual(sum(x['time'] for x in s['states'] + s['invalid']), 50)

    def test_keys_and_enum(self):
        self.assertEqual([F.key_of(v, w) for v, w in (('a', 4), ("'b1x0", 3), ('z', 1), ('1', 1), ('x', 4))], ['10', 'x', 'z', '1', 'x'])
        self.assertEqual(F.parse_enum('tb.s=0:IDLE,0x2:DONE'), ('tb.s', {0: 'IDLE', 2: 'DONE'}))
        with self.assertRaises(F.WaveError):
            F.parse_enum('tb.s')


class Tools(unittest.TestCase):
    def setUp(self):
        self.d = H.tmp()
        self.addCleanup(self.d.cleanup)
        self.vcd = os.path.join(self.d.name, 'f.vcd')
        with open(self.vcd, 'w', encoding='utf-8') as f:
            f.write('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 2 " state [1:0] $end\n$upscope $end\n$enddefinitions $end\n'
                    + ''.join(f'#{t}\n{"1" if t % 10 == 0 else "0"}!\n' + (f'b{v:b} "\n' if v is not None else '') for t, v in
                              ((0, 0), (5, None), (10, 1), (15, None), (20, 1), (25, None), (30, 2), (35, None), (40, 0), (45, None), (50, None))))

    def test_cli(self):
        rc, out, err = H.run_tool('fsmstats', self.vcd, '--signal', 'state', '--enum', 'tb.state=0:IDLE,1:RUN,2:DONE,3:ERR', '--json')
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        self.assertEqual((d['signal'], d['never'], [x['entries'] for x in d['states']]), ('tb.state', ['ERR'], [2, 1, 1, 0]))
        rc, _, err = H.run_tool('fsmstats', self.vcd, '--signal', 'state', '--enum', 'tb.state=0:IDLE,1:RUN,2:DONE,3:ERR', '--strict')
        self.assertEqual(rc, 1)
        self.assertIn('never enters ERR', err)
        rc, _, err = H.run_tool('fsmstats', self.vcd, '--signal', 'state')
        self.assertEqual(rc, 2, 'an error is 2, apart from --strict\'s 1 (review S25-5)')
        self.assertIn('no state table for tb.state', err)
        rc, _, err = H.run_tool('fsmstats', self.vcd, '--signal', 'nope', '--strict', '--enum', 'tb.state=0:IDLE')
        self.assertEqual(rc, 2, err)

    def test_mcp(self):
        r, bad = W.call('wave_fsm', {'dump': self.vcd, 'signal': 'state', 'enum': {'0': 'IDLE', '1': 'RUN', '2': 'DONE'}})
        self.assertFalse(bad, r)
        d = json.loads(r)
        self.assertEqual(([x['time'] for x in d['states']], d['changes'][0]['first'], d['unit']), ([20, 20, 10], 10, 'ns'), 'IDLE 0-10 and 40-50')
        r, bad = W.call('wave_explain', {'dump': self.vcd, 't': 20, 'signals': ['state'], 'before': 1, 'after': 1})
        self.assertFalse(bad, r)
        d = json.loads(r)
        self.assertEqual((d['kind'], d['at'], d['window'], d['clock']), ('time', 20, {'from': 10, 'to': 30}, 'tb.clk'))
        self.assertEqual(d['table']['columns'], ['cycle', 't', 'state'])
        r, bad = W.call('wave_explain', {'dump': self.vcd, 't': 20, 'signals': ['state'], 'before': 0, 'after': 0})
        self.assertEqual(json.loads(r)['window'], {'from': 20, 'to': 20}, 'a moment on an edge, before 0: the window starts there (S25-2)')
        r, bad = W.call('wave_explain', {'dump': self.vcd, 't': 23, 'signals': ['state'], 'before': 0, 'after': 0})
        self.assertEqual(json.loads(r)['window'], {'from': 20, 'to': 30}, 'between edges: the one before and the one after')
        r, bad = W.call('wave_explain', {'dump': self.vcd, 't': 20, 'signals': ['state'], 'out': os.path.join(self.d.name, 'x.json')})
        self.assertTrue(bad)
        self.assertIn('a .html page', r, 'S25-3: no traceback')
        r, bad = W.call('wave_explain', {'dump': self.vcd, 't': 20, 'b': self.vcd})
        self.assertTrue(bad)
        self.assertIn('one of', r)
        r, bad = W.call('wave_explain', {'dump': self.vcd, 't': 20})
        self.assertIn('needs "signals"', r)
        b = os.path.join(self.d.name, 'g.vcd')   # the same run, the state 3 instead of 0 at 40 ns
        with open(self.vcd, encoding='utf-8') as f, open(b, 'w', encoding='utf-8') as g:
            g.write(f.read().replace('#40\n1!\nb0 "', '#40\n1!\nb11 "'))
        r, bad = W.call('wave_explain', {'dump': self.vcd, 'b': b})
        self.assertFalse(bad, r)
        d = json.loads(r)
        self.assertEqual((d['kind'], d['at'], d['first']['signal'], d['window']), ('difference', 40, 'tb.state', {'from': 20, 'to': 50}), d)
        col = d['table']['columns'].index('tb.state')
        at40 = lambda t: next(r[col] for r in t['rows'] if r[1] == 50)   # sampled at an edge: the value before it
        self.assertEqual((at40(d['table']), at40(d['table_b'])), ('0', '3'), 'both runs\' values at the difference')
        out = os.path.join(self.d.name, 'x.html')
        r, bad = W.call('wave_explain', {'dump': self.vcd, 't': 20, 'signals': 'state', 'out': out})
        self.assertFalse(bad, r)
        import viewedit
        p = viewedit.Page(out)
        st = p.state(p.view())
        self.assertEqual((st['cursor'], [m['label'] for m in st['markers']]), (20000, ['here']))


class ExplainAssert(unittest.TestCase):
    @H.needs(__import__('svabuild').find_bin(), 'the sva CLI (make sva-build)')
    def test_an_assertion_failure(self):
        """Spec 25.1 (left out at stage 25): wave_explain {assert} -> the attempt's window, its signals from the property, its note."""
        vcd = os.path.join(os.environ.get('BUILD', os.path.join(H.ROOT, 'out')), 'examples', 'apb', 'apb.vcd')
        if not os.path.isfile(vcd):
            self.skipTest('make examples')
        sva = [os.path.join(H.ROOT, 'examples', 'apb', f) for f in ('apb_tb.sv', 'apb.sva')]
        r, bad = W.call('wave_explain', {'dump': vcd, 'sva': sva, 'assert': 'apb_demo_no_wait@apb_tb', 'before': 1, 'after': 0})
        self.assertFalse(bad, r)
        d = json.loads(r)
        self.assertEqual((d['kind'], d['at'], d['start'], d['signals'], d['window']), ('assertion', 105, 105, ['PSEL', 'PENABLE', 'PREADY'], {'from': 95, 'to': 105}))
        self.assertIn('expected PREADY', d['note'])
        r, bad = W.call('wave_explain', {'dump': vcd, 'sva': sva, 'assert': 'apb_demo_no_wait@apb_tb', 'nth': 2})
        self.assertEqual(json.loads(r)['at'], 115)
        r, bad = W.call('wave_explain', {'dump': vcd, 'sva': sva, 'assert': 'apb_demo_no_wait@apb_tb', 'nth': 9})
        self.assertTrue(bad)
        self.assertIn('no failure 9', r)
        r, bad = W.call('wave_explain', {'dump': vcd, 'assert': 'apb_demo_no_wait@apb_tb'})
        self.assertIn('needs "sva"', r)


if __name__ == '__main__':
    unittest.main()
