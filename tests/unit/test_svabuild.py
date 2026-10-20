"""tools/svabuild.py: the name rule (the same in Python, the sva CLI and wavefw/sva.js), bindings, the CLI driver."""
import json, os, subprocess, unittest

from tests.unit import helpers as H
import dumpscan
import svabuild as SB
from common import WaveError

SV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sv', 'names.sv')
ALIASES, PREFIXES = {'tb.dut.data_q': 'data'}, ['i_', 'o_']


def names():
    d = dumpscan.read(H.fixture('names'), None)
    return SB.Names({p: v.width for p, v in d.vars.items()}, ALIASES, PREFIXES)


class Paths(unittest.TestCase):
    def test_split_path(self):
        self.assertEqual(SB.split_path('tb.dut.u_x.sig'), ['tb', 'dut', 'u_x', 'sig'])
        self.assertEqual(SB.split_path('tb.mem.[1]'), ['tb', 'mem', '[1]'])
        self.assertEqual(SB.split_path('tb.a[1.2].b'), ['tb', 'a[1.2]', 'b'])
        self.assertEqual(SB.split_path('tb.\\esc.x.y'), ['tb', '\\esc.x.y'])   # an escaped name runs to the end


class Rule(unittest.TestCase):
    """The eight cases of the rule (docs/sva/ENGINE.md *Name resolution*) in the scope tb.dut."""
    def test_cases(self):
        n = names()
        cases = {'state': 'tb.dut.state', 'u_fifo.full': 'tb.dut.u_fifo.full', 'data': 'tb.dut.data_q', 'ready': 'tb.dut.i_ready'}
        for name, want in cases.items():
            with self.subTest(name):
                self.assertEqual(n.lookup('tb.dut', name), want)
        self.assertEqual(n.lookup('tb.dut', 'valid'), ['tb.dut.i_valid', 'tb.dut.o_valid'])   # ambiguous without the prefixes
        self.assertIsNone(n.lookup('tb.dut', 'nope'))

    def test_resolve_clock_climbs_only(self):
        got, bad = names().resolve('tb.dut', [{'name': 'clk'}, {'name': 'state'}])
        self.assertEqual((got, bad), ({'clk': 'tb.clk', 'state': 'tb.dut.state'}, []))
        got, bad = names().resolve('tb.dut', [{'name': 'state'}, {'name': 'clk'}])   # not the clock: not looked up above
        self.assertEqual(bad, ['clk'])

    def test_select_wider_than_the_variable(self):
        _, bad = names().resolve('tb.dut', [{'name': 'clk'}, {'name': 'state', 'width': 8}])
        self.assertEqual(bad, ['state: a select needs 8 bits, tb.dut.state has 2'])

    def test_candidates_in_dump_order(self):
        self.assertEqual(names().candidates([{'name': 'clk'}, {'name': 'state'}]), ['tb.dut', 'tb.other'])

    @unittest.skipUnless(SB.find_bin(), 'the sva CLI (make sva-build)')
    def test_cross_check_cli(self):
        """sva eval --resolve scope gives the same names and the same problems as Names.resolve (T8: three implementations
        of one rule; wavefw/sva.js is compared with them in make smoke)."""
        exe = SB.find_bin()
        parsed = json.loads(subprocess.run([exe, 'parse', '--json', SV], capture_output=True, text=True).stdout)['files'][0]['assertions']
        with H.tmp() as d:
            out = os.path.join(d, 'r.json')
            subprocess.run([exe, 'eval', '--waves', H.fixture('names'), '--resolve', 'scope', '--scope', 'tb.dut', '--ignore-prefix', ','.join(PREFIXES),
                            '--alias', 'data=tb.dut.data_q', '--sva', SV, '--out', out], capture_output=True, text=True)
            cli = {a['name']: (a['signals'], a.get('missing') or []) for a in json.load(open(out))['assertions']}
        n = names()
        for a in parsed:
            with self.subTest(a['label']):
                got, bad = n.resolve('tb.dut', a['signals'])
                want_got, want_bad = cli[a['label']]
                self.assertEqual(got, want_got)
                self.assertEqual([b.replace(': ', ' (', 1) + ')' if ': a select' in b else b for b in bad], want_bad)


class Binds(unittest.TestCase):
    def test_bind_list_forms(self):
        self.assertEqual(SB.bind_list(['a@tb.dut', {'assert': 'b', 'scope': 'tb'}, {'assert': 'c', 'show': False}, 'd']),
                         [{'assert': 'a', 'scope': 'tb.dut'}, {'assert': 'b', 'scope': 'tb'}, {'assert': 'd', 'scope': ''}])
        with self.assertRaisesRegex(WaveError, 'bad "bind" entry'):
            SB.bind_list([{'scope': 'tb'}])

    def test_find_bin_explicit_missing(self):
        with self.assertRaisesRegex(WaveError, 'no sva binary at /no/such/sva'):
            SB.find_bin('/no/such/sva')

    def test_parse_files_count_mismatch(self):
        with H.tmp() as d:
            fake = os.path.join(d, 'sva')
            with open(fake, 'w') as f:
                f.write('#!/bin/sh\necho \'{"files": [{"assertions": []}]}\'\n')
            os.chmod(fake, 0o755)
            with self.assertRaisesRegex(WaveError, '1 results for 2 files'):
                SB.parse_files([(SV, 'a.sv'), (SV, 'b.sv')], fake)

    @unittest.skipUnless(SB.find_bin(), 'the sva CLI (make sva-build)')
    def test_bind_to_a_scope_not_in_the_dump_is_an_error(self):
        files = [(SV, 'names.sv')]
        with self.assertRaisesRegex(WaveError, 'a_state@tb.nowhere: the dump has no scope tb.nowhere'):
            SB.evaluate([{'assert': 'a_state', 'scope': 'tb.nowhere'}], files, H.fixture('names'), SB.find_bin(), parsed=SB.parse_files(files, SB.find_bin()), quiet=True)

    @unittest.skipUnless(SB.find_bin(), 'the sva CLI (make sva-build)')
    def test_evaluate_a_binding(self):
        files = [(SV, 'names.sv')]
        bs, notes = SB.evaluate([{'assert': 'a_*', 'scope': 'tb.dut'}], files, H.fixture('names'), SB.find_bin(), parsed=SB.parse_files(files, SB.find_bin(), quiet=True),
                                quiet=True, prefixes=PREFIXES, aliases={'tb.dut.data_q': 'data'})
        got = {b['assert']: b['results']['assertions'][0]['stats']['pass'] for b in bs}
        self.assertEqual(got, {'a_state': 2, 'a_nested': 2, 'a_alias': 2, 'a_prefix': 2, 'a_ambiguous': 0, 'a_missing': 0, 'a_wide': 0})
        self.assertEqual(notes, [])


if __name__ == '__main__':
    unittest.main()
