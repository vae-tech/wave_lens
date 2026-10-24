"""tools/svaverify.py: the parts that need no Verilator (the blanking that keeps the line numbers, the spans, the audit)."""
import os, types, unittest

from tests.unit import helpers as H
import svabuild
import svaverify as V


class Blank(unittest.TestCase):
    def test_keeps_lines_and_columns(self):
        text = 'a: assert property (x |-> y)\n    else $error("m");\nb: assert property (z);\n'
        out = V.blank(text, [(0, text.index(';') + 1)])
        self.assertEqual(out.count('\n'), text.count('\n'))
        self.assertEqual(out.splitlines()[2], 'b: assert property (z);')
        self.assertEqual(set(''.join(out.splitlines()[:2])), {' '})


class Audit(unittest.TestCase):
    """review VI T3: what makes an agreement hollow is an error, not a smaller comparison."""
    EX = {'unsupported': {'a_within', 'c_cov'}}

    @staticmethod
    def sim(out='- fsm_tb.sv:159: Verilog $finish\n', rc=0):
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr='')

    @staticmethod
    def res(**stats):
        base = {'pass': 3, 'fail': 0, 'vacuous': 1, 'capped': 0}
        return {'assertions': [{'name': n, 'stats': dict(base, **st)} for n, st in stats.items()]}

    def test_all_good(self):
        self.assertEqual(V.audit('x', self.EX, ['a', 'b'], ['a_within', 'c_cov'], self.sim(), 1, self.res(a={}, b={'pass': 0, 'fail': 2})), ([], []))

    def test_put_out_beyond_the_list(self):   # a syntax error of the source inside an assertion: blanked, it would not be compared
        err, _ = V.audit('x', self.EX, ['a'], ['a_within', 'b_typo', 'c_cov'], self.sim(), 0, self.res(a={}))
        self.assertTrue(any('b_typo' in e and 'unsupported' in e for e in err), err)

    def test_supported_now_is_a_note(self):
        err, notes = V.audit('x', self.EX, ['a', 'a_within'], ['c_cov'], self.sim(), 0, self.res(a={}, a_within={}))
        self.assertEqual(err, [])
        self.assertIn('a_within', notes[0])

    def test_nothing_compared(self):
        self.assertIn('no assertion compared', V.audit('x', self.EX, [], ['a_within', 'c_cov'], self.sim(), 0, self.res())[0][0])

    def test_the_simulation_cut_short(self):
        for sim in (self.sim('%Error: killed'), self.sim(rc=1), self.sim('')):
            err, _ = V.audit('x', self.EX, ['a'], ['a_within', 'c_cov'], sim, 0, self.res(a={}))
            self.assertTrue(any('$finish' in e for e in err), err)

    def test_the_engine_did_not_say(self):
        cases = [(2, None, 'did not evaluate'), (0, self.res(), 'not in the results'), (0, self.res(a={'capped': 4}), 'capped'),
                 (0, self.res(a={'pass': 0, 'fail': 0, 'vacuous': 9}), 'vacuous')]
        for rc, res, want in cases:
            with self.subTest(want):
                err, _ = V.audit('x', self.EX, ['a'], ['a_within', 'c_cov'], self.sim(), rc, res)
                self.assertTrue(any(want in e for e in err), err)

    def test_the_lists_are_the_examples(self):
        for name, ex in V.EXAMPLES.items():
            self.assertTrue(ex['unsupported'], name)


@H.needs(svabuild.find_bin(), 'the sva CLI (make sva-build)')
class Spans(unittest.TestCase):
    def test_assertions_with_actions_and_declarations(self):
        f = 'examples/axi_lite/axi_lite.sva'
        items = {x['label']: x for x in V.parse(svabuild.find_bin(), [f])[f]}
        self.assertTrue(items['s_hs']['text'].startswith('sequence s_hs') and items['s_hs']['text'].endswith('endsequence'))
        a = next(x for x in items.values() if x['kind'] == 'assert')
        self.assertTrue(a['text'].startswith(a['label']) and a['text'].endswith(';'))
        self.assertTrue(os.path.exists(os.path.join(H.ROOT, f)))


if __name__ == '__main__':
    unittest.main()
