"""tools/wavefind.py: the times of an event, the same for a bookmark "at", a marker "on" (vcd2wavedrom.py) and wave_find
(wavemcp.py): each form on a VCD made here, whose stimulus moves by a shift (the config stays, the times follow)."""
import json, os, re, subprocess, unittest

from tests.unit import helpers as H
import svabuild
import vcd2wavedrom as V
import wavefind as F
import wavemcp as W
from common import WaveError

SVA = svabuild.find_bin()


def fsm_vcd(d, shift=0, name='t.vcd'):
    """tb.clk (10 ns), tb.u.state 0 1 2 5 0 … (IDLE RUN GAP ERR), tb.u.eof a pulse, tb.v.state too (a second scope with the
    same leaf names): every change but the clock's later by shift ns."""
    body, st, t = ['#0', '0!', 'b0 "', '0#', 'b0 $'], [(30, 1), (60, 2), (90, 5), (120, 0), (150, 1), (180, 2), (210, 5)], 0
    ev = {}
    for at, v in st:
        ev.setdefault(at + shift, []).append(f'b{v:b} "')
    for at in (95, 215):
        ev.setdefault(at + shift, []).append('1#')
        ev.setdefault(at + shift + 10, []).append('0#')
    ev.setdefault(40 + shift, []).append('b11 $')
    for t in range(5, 300, 5):
        ev.setdefault(t, []).insert(0, '1!' if t % 10 == 5 else '0!')
    for t in sorted(ev):
        body += [f'#{t}'] + ev[t]
    head = ('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$scope module u $end\n$var reg 3 " state [2:0] $end\n'
            '$var wire 1 # eof $end\n$upscope $end\n$scope module v $end\n$var reg 3 $ state [2:0] $end\n$upscope $end\n$upscope $end\n'
            '$enddefinitions $end\n')
    return H.vcd(d, '\n'.join(body) + '\n', header=head, name=name)


ENUM = {'tb.u.state': {'0': 'IDLE', '1': 'RUN', '2': 'GAP', '5': 'ERR'}}


class Spec(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(F.spec('posedge clk'), {'kind': 'signal', 'signal': 'clk', 'edge': 'posedge', 'nth': 1})
        self.assertEqual(F.spec('x')['edge'], 'change')
        self.assertEqual(F.spec({'signal': 'x', 'edge': 'rise', 'nth': 2}), {'kind': 'signal', 'signal': 'x', 'edge': 'posedge', 'nth': 2})
        self.assertEqual(F.spec({'assert': 'a'})['result'], 'fail')

    def test_errors(self):
        for bad, msg in ((' a && b', 'an SV expression is {"expr"'), ({'signal': 'x', 'expr': 'y'}, 'not signal and expr'),
                         ({'signal': 'x'}, 'has "value" or "edge"'), ({'signal': 'x', 'value': 1, 'nth': 0}, '"nth" is 1, 2'),
                         ({'assert': 'a', 'result': 'maybe'}, '"result" is fail or pass'), ({'signal': 'x', 'edge': 'up'}, '"edge" is rise'),
                         ({'expr': 'a', 'lable': 1}, 'unknown key(s) lable'), (5, 'an event is a text')):
            with self.subTest(bad), self.assertRaisesRegex(WaveError, re.escape(msg)):
                F.spec(bad)


class Times(unittest.TestCase):
    def test_value_and_edges(self):
        st = [(0, '0'), (30, '1'), (60, '2'), (90, '5'), (120, '0'), (150, '1')]
        lab = {'0': 'IDLE', '1': 'RUN', '2': 'GAP', '5': 'ERR'}.get
        self.assertEqual(F.value_times(st, 'RUN', 3, 0, 200, lab), [30, 150])
        self.assertEqual(F.value_times(st, 5, 3, 0, 200, lab), [90])
        self.assertEqual(F.value_times(st, "3'b101", 3, 0, 200, lab), [90])
        self.assertEqual(F.value_times(st, 'RUN', 3, 70, 200, lab), [150])
        self.assertEqual(F.value_times(st, 'RUN', 3, 35, 200, lab), [35, 150])   # already there at "from": a match
        bit = [(0, '0'), (5, '1'), (10, '0'), (15, '1')]
        self.assertEqual(F.edge_times(bit, 'posedge', 0, 20), [5, 15])
        self.assertEqual(F.edge_times(bit, 'negedge', 0, 20), [10])
        self.assertEqual(F.edge_times(bit, 'change', 6, 20), [10, 15])


class Bookmarks(unittest.TestCase):
    """A bookmark "at" an event and a marker "on" one, through the converter (vcd2wavedrom.py, as mkhtml.py runs it)."""
    def convert(self, d, vcd, view, *args):
        cfg = os.path.join(d, 'c.json')
        json.dump({'waves': vcd, 'scope': 'tb.u', 'clock': 'tb.clk', 'signals': 'state,eof', 'enum': {'state': ENUM['tb.u.state']}, **view}, open(cfg, 'w'))
        rc, out, err = H.run_tool('vcd2wavedrom', '--config', cfg, *args)
        return rc, (json.loads(out) if rc == 0 else None), err

    def test_at_follows_the_stimulus(self):
        bm = [{'n': 1, 'at': {'signal': 'state', 'value': 'ERR'}, 'signal': 'state', 'text': 'error'},
              {'n': 2, 'at': {'signal': 'state', 'value': 'RUN', 'nth': 2}, 'signal': 'state'},
              {'n': 3, 'at': 'posedge eof', 'signal': 'eof'},
              {'n': 4, 'at': {'signal': 'state', 'value': 'ERR', 'from': '150ns'}}]
        got = {}
        for shift in (0, 20):
            with H.tmp() as d:
                rc, doc, err = self.convert(d, fsm_vcd(d, shift), {'bookmarks': bm})
                self.assertEqual(rc, 0, err)
                got[shift] = [b['t'] for b in doc['bookmarks']]
                self.assertEqual(doc['bookmarks'][0]['at'], bm[0]['at'])   # the event as written goes along (view_edit {config})
        self.assertEqual(got[0], [90000, 150000, 95000, 210000])
        self.assertEqual(got[20], [t + 20000 for t in got[0]])

    def test_markers_on(self):
        with H.tmp() as d:
            rc, doc, err = self.convert(d, fsm_vcd(d), {'marker': [{'on': {'signal': 'state', 'value': 'ERR'}, 'label': 'err'},
                                                                   {'on': {'signal': 'state', 'value': 'RUN', 'nth': 2}, 'label': 'run2'}, 'posedge eof=eof']})
            self.assertEqual(rc, 0, err)
        self.assertEqual([(m['t'], m['label']) for m in doc['markers']],
                         [(90000, 'err 1'), (95000, 'eof 1'), (150000, 'run2'), (210000, 'err 2'), (215000, 'eof 2')])

    def test_errors_say_where(self):
        with H.tmp() as d:
            vcd = fsm_vcd(d)
            rc, _, err = self.convert(d, vcd, {'views': {'w': {'from': '0ns', 'to': '80ns', 'bookmarks': [{'n': 4, 'at': {'signal': 'state', 'value': 'ERR'}}]}}}, '--view', 'w')
            self.assertEqual(rc, 1)
            self.assertIn('views.w.bookmarks[0] (n 4): no match for {"signal": "state", "value": "ERR"} in 0ps…80ns', err)
            rc, _, err = self.convert(d, vcd, {'bookmarks': [{'n': 1, 't': '5ns', 'at': 'posedge eof'}]})
            self.assertEqual(rc, 1)
            self.assertIn('bookmarks[0] (n 1): "t" and "at" both', err)
            rc, _, err = self.convert(d, vcd, {'bookmarks': [{'n': 1, 'at': {'signal': 'state', 'value': 'RUN', 'nth': 9}}]})
            self.assertIn('2 match(es), no number 9', err)

    def test_spans_ends(self):
        # a span's ends: a time, a bookmark's time, an event (a bookmark's "at"); label, color, signals as written
        sp = [{'from': {'bookmark': 1}, 'to': {'signal': 'state', 'value': 'GAP'}, 'label': 'run'}, {'from': '100ns', 'to': 140000, 'signals': ['state']},
              {'from': 'posedge eof', 'to': {'signal': 'state', 'value': 'IDLE', 'from': '100ns'}}]
        with H.tmp() as d:
            rc, doc, err = self.convert(d, fsm_vcd(d), {'bookmarks': [{'n': 1, 'at': {'signal': 'state', 'value': 'RUN'}}], 'spans': sp})
            self.assertEqual(rc, 0, err)
            self.assertEqual(doc['spans'], [{'label': 'run', 'from': 30000, 'to': 60000}, {'signals': ['state'], 'from': 100000, 'to': 140000},
                                            {'from': 95000, 'to': 120000}])
            rc, _, err = self.convert(d, fsm_vcd(d), {'spans': [{'from': {'bookmark': 7}, 'to': '5ns'}]})
            self.assertIn('spans[0]: "from": no bookmark 7', err)

    def test_two_scopes_with_one_leaf(self):
        with H.tmp() as d:
            rc, doc, err = self.convert(d, fsm_vcd(d), {'bookmarks': [{'n': 1, 'at': {'signal': 'tb.v.state', 'value': 3}}, {'n': 2, 'at': 'state'}]})
            self.assertEqual(rc, 0, err)
        self.assertEqual([b['t'] for b in doc['bookmarks']], [40000, 30000])   # tb.v.state by its path; "state" is tb.u's (the scope)

    @H.needs(SVA, 'the sva CLI (make sva-build)')
    def test_expr_and_assert(self):
        with H.tmp() as d:
            vcd = fsm_vcd(d)
            sv = os.path.join(d, 'c.sv')
            open(sv, 'w').write('module c; a_no_err: assert property (@(posedge clk) state != 5); endmodule\n')
            bm = [{'n': 1, 'at': {'expr': 'eof && state == 5'}}, {'n': 2, 'at': {'expr': '$rose(eof)', 'nth': 2}},
                  {'n': 3, 'at': {'assert': 'a_no_err'}}, {'n': 4, 'at': {'assert': 'a_no_err', 'nth': 2, 'point': 'start'}},
                  {'n': 5, 'at': {'assert': 'a_no_err', 'result': 'pass'}}]
            rc, doc, err = self.convert(d, vcd, {'bookmarks': bm, 'sva': [sv], 'bind': ['a_no_err@tb.u']})
            self.assertEqual(rc, 0, err)
        t = [b['t'] for b in doc['bookmarks']]
        self.assertEqual(t[:4], [105000, 225000, 95000, 105000])   # sampled before the edge: eof rises at 95 ns, seen at 105 ns
        self.assertLess(t[4], 95000)
        with H.tmp() as d:
            rc, _, err = self.convert(d, fsm_vcd(d), {'bookmarks': [{'n': 1, 'at': {'assert': 'a_x'}}]})
            self.assertEqual(rc, 1)
            self.assertIn('needs the "sva" files', err)

    @H.needs(SVA, 'the sva CLI (make sva-build)')
    def test_fst_gives_the_same(self):
        with H.tmp() as d:
            vcd = fsm_vcd(d)
            fst = os.path.join(d, 't.fst')
            r = subprocess.run([SVA, 'fst', vcd, '--out', fst, '-q'], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            bm = {'bookmarks': [{'n': 1, 'at': {'signal': 'state', 'value': 'ERR', 'nth': 2}}, {'n': 2, 'at': 'negedge eof'}]}
            a, b = self.convert(d, vcd, bm)[1], self.convert(d, fst, bm)[1]
        self.assertEqual([x['t'] for x in a['bookmarks']], [x['t'] for x in b['bookmarks']])


class Mcp(unittest.TestCase):
    """wave_find goes through the same functions: its answers as before."""
    def test_value_and_edge(self):
        with H.tmp() as d:
            vcd = fsm_vcd(d)
            text, err = W.call('wave_find', {'dump': vcd, 'signal': 'tb.u.state', 'value': 5})
            self.assertFalse(err, text)
            self.assertEqual(json.loads(text)['rows'], [[90, 30], [210, None]])
            text, err = W.call('wave_find', {'dump': vcd, 'signal': 'tb.u.eof', 'edge': 'rise'})
            self.assertEqual(json.loads(text)['times'], [95, 215])

    @H.needs(SVA, 'the sva CLI (make sva-build)')
    def test_expr(self):
        with H.tmp() as d:
            text, err = W.call('wave_find', {'dump': fsm_vcd(d), 'expr': '$rose(eof)', 'clock': 'tb.clk', 'scope': 'tb.u'})
            self.assertFalse(err, text)
            self.assertEqual([r[1] for r in json.loads(text)['rows']], [105, 225])


if __name__ == '__main__':
    unittest.main()
