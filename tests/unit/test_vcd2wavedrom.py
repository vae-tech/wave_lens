"""tools/vcd2wavedrom.py: values, labels, options and the conversion of the fixtures (exact and clock-sampled)."""
import json, os, shutil, unittest

from tests.unit import helpers as H
import vcd2wavedrom as V
from common import WaveError


class Values(unittest.TestCase):
    def test_norm_literals(self):
        self.assertEqual(V.norm("8'ha5", 8), 'a5')
        self.assertEqual(V.norm("1'h1", 1), '1')
        self.assertEqual(V.norm("4'b0x01", 4), 'x')
        self.assertEqual(V.norm("8'b0000x001", 8), '0x')
        self.assertEqual(V.norm("8'd64", 8), '40')
        self.assertEqual(V.norm("6'o17", 6), '0f')

    def test_norm_x_z_as_gtkwave(self):
        self.assertEqual(V.norm("8'bxxxxxxxx", 8), 'x')            # all x: one letter, as the page reads it
        self.assertEqual(V.norm("12'bzzzzzzzzzzzz", 12), 'z')
        self.assertEqual(V.norm("8'bzzzz0000", 8), 'z0')            # a nibble all z: z
        self.assertEqual(V.norm("8'bzz000000", 8), 'x0')            # a partial z: x
        self.assertEqual(V.norm("8'hxx", 8), 'x')                    # wavepeek's spelling, the same

    def test_bits_extension_and_slice(self):
        self.assertEqual(V.bits(b'1', 8, None), '01')
        self.assertEqual(V.bits(b'x1', 8, None), 'xx')               # left-extended with x
        self.assertEqual(V.bits(b'z', 12, None), 'z')
        self.assertEqual(V.bits(b'zz1', 12, None), 'zzx')
        self.assertEqual(V.bits(b'10100101', 8, (5, 2)), '9')
        self.assertEqual(V.bits(b'1u0h', 4, None), 'x')             # VHDL U: unknown
        self.assertEqual(V.bits(b'01hl', 4, None), '6')

    def test_bits_texts(self):
        self.assertEqual(V.bits(b'r1.5', 64, None), '1.5')
        self.assertEqual(V.bits(b'r-3e-2', 64, None), '-0.03')
        self.assertEqual(V.bits(b'sHello', 1, None), 'Hello')

    def test_label_every_radix(self):
        cases = [(('ff', 8, None, 'hex'), '0xFF'), (('ff', 8, None, 'dec'), '255'), (('ff', 8, None, 'signed'), '-1'),
                 (('05', 8, None, 'bin'), '00000101'), (('08', 8, None, 'oct'), '0o10'), (('4142', 16, None, 'ascii'), '"AB"'),
                 (('3c00', 16, None, 'float'), '1'), (('3fc00000', 32, None, 'float'), '1.5'), (('80', 8, None, 'sq4'), '-8'),
                 (('18', 8, None, 'q4'), '1.5'), (('ff', 8, None, 'sq4'), '-0.0625'), (('f' * 15, 60, None, 'q4'), '72057594037927935.9375'), (('05', 4, None, None), '5'),
                 (('5', 4, {5: 'IDLE'}, None), 'IDLE'), (('x1', 8, None, 'hex'), 'x1'), (('ff', 8, None, 'unsigned'), '255')]
        for args, want in cases:
            with self.subTest(args):
                self.assertEqual(V.label(*args), want)

    def test_gfmt_matches_js(self):
        for f, p, want in [(1.5, 7, '1.5'), (0.1, 7, '0.1'), (1e-7, 7, '1e-07'), (123456789.0, 7, '1.234568e+08'), (-0.0, 7, '-0'),
                           (float('inf'), 7, 'inf'), (float('nan'), 7, 'nan'), (2.5, 1, '3'), (0.125, 2, '0.13'),
                           (0.00001234, 7, '1.234e-05'), (0.0001234, 7, '0.0001234')]:
            with self.subTest(f=f, p=p):
                self.assertEqual(V.gfmt(f, p), want)

    def test_wave_of(self):
        self.assertEqual(V.wave_of(['0', '1', '1', None, '0'], 1, None), ('01.|0', [], []))
        self.assertEqual(V.wave_of(['5', '5', '6'], 4, {5: 'A', 6: 'B'}), ('8.9', ['A', 'B'], ['5', '6']))   # enum colour 3 + n % 7
        self.assertEqual(V.wave_of(['x', 'z', '1f'], 8, None), ('xz=', ['0x1F'], ['1f']))
        self.assertEqual(V.wave_of([V.X_TEXT, '1.5', '1.5'], 64, None, kind='real'), ('x=.', ['1.5'], []))
        self.assertEqual(V.wave_of(['0', '1', '0'], 1, None, clock=True), ('p..', [], []))


class Options(unittest.TestCase):
    CAT = {'tb.a': {'show': False}, 'tb.b_valid': {}, 'tb.c_valid': {'alias': 'cv'}, 'tb.u.d': {}}

    def test_select_patterns_and_alias(self):
        got = V.select(self.CAT, ['tb.*_valid', 'tb.a=A'])
        self.assertEqual(list(got), ['tb.b_valid', 'tb.c_valid', 'tb.a'])
        self.assertEqual(got['tb.a'], {'show': True, 'alias': 'A'})
        self.assertEqual(got['tb.c_valid']['alias'], 'cv')

    def test_select_pattern_without_match_warns(self):
        with H.stderr() as e:
            self.assertEqual(V.select(self.CAT, ['tb.zz*']), {})
        self.assertIn('matches no signal', e.getvalue())

    def test_view_config_merges(self):
        cfg = {'exact': True, 'config': {'sort': 'asc', 'dim': 0.5}, 'enum': {'s': {'0': 'A'}},
               'views': {'v': {'clock': 'clk', 'config': {'dim': 0.2}, 'enum': {'t': {'1': 'B'}}}}}
        v = V.view_config(cfg, 'v')
        self.assertNotIn('exact', v)                                   # a view's mode replaces the top-level one
        self.assertEqual(v['config'], {'sort': 'asc', 'dim': 0.2})
        self.assertEqual(set(v['enum']), {'s', 't'})
        with self.assertRaisesRegex(WaveError, 'no view "w"'):
            V.view_config(cfg, 'w')

    def resolve(self, cfg, argv=()):
        return V.resolve(V.parser().parse_args(list(argv)), cfg)

    def test_unknown_key_is_an_error(self):
        with self.assertRaisesRegex(WaveError, 'unknown config key "wavez"'):
            self.resolve({'wavez': 'x.vcd'})

    def test_unknown_config_setting_is_an_error(self):
        with self.assertRaisesRegex(WaveError, r'rowHeigth \(did you mean rowHeight'):
            self.resolve({'waves': H.fixture('zero'), 'signals': 'tb.s', 'exact': True, 'config': {'rowHeigth': 30}})

    def test_needs_one_mode(self):
        with self.assertRaisesRegex(WaveError, 'exactly one of'):
            self.resolve({'waves': H.fixture('zero'), 'signals': 'tb.s'})

    def test_command_line_wins(self):
        a = self.resolve({'waves': H.fixture('zero'), 'signals': 'tb.s', 'exact': True, 'title': 'cfg'}, ['--title', 'cli'])
        self.assertEqual(a.title, 'cli')

    def test_parse_enums_markers_groups(self):
        self.assertEqual(V.parse_enums(['st=0:IDLE,1:RUN', {'q': {'0x2': 'B', '010': 'T'}}]), {'st': {0: 'IDLE', 1: 'RUN'}, 'q': {2: 'B', 10: 'T'}})
        self.assertEqual(V.parse_markers(['posedge done=done', {'on': 'x'}]), [('posedge done', 'done'), ('x', 'x')])
        self.assertEqual(V.parse_groups(['tx=a,b', {'rx': ['c']}]), [('tx', ['a', 'b']), ('rx', ['c'])])

    def test_bad_time_is_an_error(self):
        with self.assertRaisesRegex(WaveError, 'bad time "12"'):
            V.to_ps('12')


class Convert(unittest.TestCase):
    def test_real_signal_is_labelled(self):
        s = H.wavejson_of(H.fixture('real'))['tb.volt']
        self.assertEqual(s['kind'], 'real')
        self.assertEqual(s['tv'], [[0, '1.5'], [10000, '2.25'], [20000, '-0.03']])

    def test_real_clock_sampled(self):
        with H.tmp() as d:
            body = ''.join(f'#{t}\n{t // 5 % 2}"\nr{t / 10} !\n' for t in range(0, 40, 5))
            p = H.vcd(d, body, header=open(H.fixture('real')).read().split('#0')[0])
            rc, out, err = H.run_tool('vcd2wavedrom', '--waves', p, '--clock', 'tb.clk', '--signals', 'tb.clk,tb.volt')
        self.assertEqual(rc, 0, err)
        volt = json.loads(out)['signal'][1]
        self.assertEqual((volt['kind'], volt['wave'], volt['data']), ('real', '====', ['0.5', '1.5', '2.5', '3.5']))
        self.assertNotIn('raw', volt)

    def test_string_signal_event_refused(self):
        sigs = H.wavejson_of(H.fixture('string_event'))
        self.assertEqual(sigs['tb.msg']['tv'], [[0, 'Hello'], [10000, 'World']])
        rc, _, err = H.run_tool('vcd2wavedrom', '--waves', H.fixture('string_event'), '--exact', '--signals', 'tb.ev')
        self.assertEqual(rc, 1)
        self.assertIn('is an event', err)

    def test_merged_duplicate_codes(self):
        self.assertEqual(H.wavejson_of(H.fixture('dup'))['tb.s']['tv'], [[0, '0'], [10000, '1'], [30000, '0']])

    def test_several_tokens_per_line(self):
        sigs = H.wavejson_of(H.fixture('oneline'))
        self.assertEqual((sigs['tb.s']['tv'], sigs['tb.v']['tv']), ([[0, '0'], [10000, '1']], [[0, '1'], [10000, '2']]))

    def test_vhdl_and_body_comment(self):
        v = H.wavejson_of(H.fixture('vhdl'))
        self.assertEqual(v['top.v']['tv'], [[0, 'x'], [10000, '6'], [20000, 'x']])
        c = H.wavejson_of(H.fixture('body_comment'))
        self.assertEqual(c['tb.s']['tv'], [[0, '0'], [10000, '1']])

    def test_escaped_names_in_the_hierarchy(self):
        rc, out, err = H.run_tool('vcd2wavedrom', '--waves', H.fixture('escaped'), '--exact', '--hierarchy', '--signals', 'tb.\\a.b,tb.\\bus$x')
        sig = json.loads(out)['signal']
        self.assertEqual(sig[0][0], 'tb')
        self.assertEqual([s['name'] for s in sig[0][1:]], ['\\a.b', '\\bus$x'])

    def test_time_backwards_one_line(self):
        rc, _, err = H.run_tool('vcd2wavedrom', '--waves', H.fixture('backwards'), '--exact', '--signals', 'tb.s')
        self.assertEqual((rc, err.count('\n')), (1, 1))
        self.assertIn('time goes back: #5 after #20', err)

    def test_missing_files_one_line(self):
        for args in (['--waves', 'nope.vcd', '--exact', '--signals', 'a'], ['--config', 'nope.json']):
            with self.subTest(args):
                rc, _, err = H.run_tool('vcd2wavedrom', *args)
                self.assertEqual(rc, 1)
                self.assertNotIn('Traceback', err)
                self.assertIn('nope', err)

    def test_unknown_signal_one_line(self):
        rc, _, err = H.run_tool('vcd2wavedrom', '--waves', H.fixture('zero'), '--exact', '--signals', 'tb.nope')
        self.assertEqual((rc, err.strip()), (1, 'vcd2wavedrom: no signal "tb.nope" in zero.vcd'))

    def test_exact_same_dedup(self):
        sigs = H.wavejson_of(H.fixture('idreuse'))
        self.assertEqual(sigs['tb.dut.clk']['tv'], sigs['tb.clk']['tv'])

    def test_exact_window(self):
        sigs = H.wavejson_of(H.fixture('crlf'), '--exact', '--from', '5ns', '--to', '15ns', '--signals', 'tb.s')
        self.assertEqual(sigs['s']['tv'], [[5000, '0'], [10000, '1']])

    def test_clock_skip_cells(self):
        with H.tmp() as d:
            body = ''.join(f'#{t}\n{t // 5 % 2}!\n' for t in range(0, 105, 5))
            p = H.vcd(d, body, header='$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$upscope $end\n$enddefinitions $end\n')
            rc, out, err = H.run_tool('vcd2wavedrom', '--waves', p, '--clock', 'tb.clk', '--signals', 'tb.clk', '--gap', '30ns:60ns')
            doc = json.loads(out)
        self.assertEqual(rc, 0, err)
        self.assertIn('|', doc['signal'][0]['wave'])
        self.assertEqual(doc['time']['skip'], [[3, 3]])   # the edges at 35, 45 and 55 ns in one "|" cell

    def test_auto_gaps(self):
        times = list(range(0, 200, 10))
        col = ['a'] * 5 + ['b'] * 15            # a change in cycle 5, none after: cycles 6 … 7 kept, 8 … 17 one gap, 18 19 kept
        self.assertEqual(V.auto_gaps('8:2', times, [col]), [(80, 170)])
        self.assertEqual(V.auto_gaps('16', times, [col]), [])            # 15 cycles idle: no gap
        self.assertEqual(V.auto_gaps('3:0', times, [['a'] * 20]), [(10, 190)])   # the first cycle stays
        for bad in ('0', 'x', '4:'):
            with self.assertRaises(WaveError):
                V.auto_gaps(bad, times, [col])

    def test_clock_auto_gap(self):
        with H.tmp() as d:
            ev = sorted([(t, f'{t // 5 % 2}!') for t in range(0, 205, 5)] + [(0, '0"'), (52, '1"')])
            body = ''.join(f'#{t}\n{v}\n' for t, v in ev)
            hdr = '$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 " en $end\n$upscope $end\n$enddefinitions $end\n'
            p = H.vcd(d, body, header=hdr)
            rc, out, err = H.run_tool('vcd2wavedrom', '--waves', p, '--clock', 'tb.clk', '--signals', 'tb.clk,tb.en', '--auto-gap', '6:1')
            doc = json.loads(out)
        self.assertEqual(rc, 0, err)
        self.assertEqual([s['wave'] for s in doc['signal']], ['p......|.', '0....1.|.'])   # en rises in cycle 5; cycles 7 … 18 left out
        self.assertEqual(doc['time']['skip'], [[7, 12]])

    def test_hierarchy_scopes_struct_width(self):
        _, out, _ = H.run_tool('vcd2wavedrom', '--waves', H.fixture('scopes'), '--exact', '--hierarchy', '--signals', 'tb.st.f0,tb.st.f1,tb.ifc.d')
        self.assertEqual(json.loads(out)['scopes'], {'tb.st': {'kind': 'struct', 'width': 3}, 'tb.ifc': 'interface'})

    def test_huge_time_written_as_int(self):
        s = H.wavejson_of(H.fixture('huge2'))['tb.s']
        self.assertEqual(s['tv'][1][0], 9007199254740993)

    def test_wide_vector(self):
        self.assertEqual(H.wavejson_of(H.fixture('wide'))['tb.w']['tv'][0][1], 'f' * 24)

    @unittest.skipUnless(shutil.which('wavepeek') or os.path.exists(os.path.expanduser('~/.local/bin/wavepeek')), 'wavepeek')
    def test_builtin_vs_wavepeek_identical(self):
        dump = os.path.join(H.BUILD, 'demo.vcd')
        if not os.path.exists(dump):
            self.skipTest('make demo')
        cfg = os.path.join(H.ROOT, 'examples', 'demo', 'demo.config.json')
        for view in ('cycle', 'exact'):
            with self.subTest(view):
                docs = []
                for reader in ('builtin', 'wavepeek'):
                    rc, out, err = H.run_tool('vcd2wavedrom', '--config', cfg, '--view', view, '--waves', dump, '--reader', reader)
                    self.assertEqual(rc, 0, err)
                    d = json.loads(out); d['meta'].pop('tool')
                    docs.append(d)
                self.assertEqual(docs[0], docs[1])

    @unittest.skipUnless(shutil.which('fst2vcd'), 'fst2vcd')
    def test_vcd_vs_fst_identical(self):
        ex = os.path.join(H.BUILD, 'examples', 'apb')
        if not os.path.exists(os.path.join(ex, 'apb.fst')):
            self.skipTest('make examples')
        cfg = os.path.join(H.ROOT, 'examples', 'apb', 'apb.config.json')
        docs = []
        for ext in ('vcd', 'fst'):
            rc, out, err = H.run_tool('vcd2wavedrom', '--config', cfg, '--view', 'transfers', '--waves', os.path.join(ex, 'apb.' + ext))
            self.assertEqual(rc, 0, err)
            d = json.loads(out); d['meta'].pop('tool'); d['meta'].pop('waves')
            docs.append(d)
        self.assertEqual(docs[0], docs[1])


if __name__ == '__main__':
    unittest.main()
