"""tools/vcd2wavedrom.py: values, labels, options and the conversion of the fixtures (exact and clock-sampled)."""
import json, os, shutil, subprocess, unittest

from tests.unit import helpers as H
import vcd2wavedrom as V
from common import WaveError


class Values(unittest.TestCase):
    def test_norm_literals(self):
        self.assertEqual(V.norm("8'ha5", 8), 'a5')
        self.assertEqual(V.norm("1'h1", 1), '1')
        self.assertEqual(V.norm("4'b0x01", 4), "'b0x01")          # a nibble of known bits and x: its binary digits
        self.assertEqual(V.norm("8'b0000x001", 8), "'b0000x001")
        self.assertEqual(V.norm("8'b1010xxxx", 8), 'ax')            # whole nibbles x: hex loses nothing
        self.assertEqual(V.norm("8'd64", 8), '40')
        self.assertEqual(V.norm("6'o17", 6), '0f')

    def test_norm_x_z_as_gtkwave(self):
        self.assertEqual(V.norm("8'bxxxxxxxx", 8), 'x')            # all x: one letter, as the page reads it
        self.assertEqual(V.norm("12'bzzzzzzzzzzzz", 12), 'z')
        self.assertEqual(V.norm("8'bzzzz0000", 8), 'z0')            # a nibble all z: z
        self.assertEqual(V.norm("8'bzz000000", 8), "'bzz000000")   # a partial z: the bits (GTKWave's hex: x0)
        self.assertEqual(V.norm("8'hxx", 8), 'x')                    # in hex, the same

    def test_bits_extension_and_slice(self):
        self.assertEqual(V.bits(b'1', 8, None), '01')
        self.assertEqual(V.bits(b'x1', 8, None), "'bxxxxxxx1")       # left-extended with x; bit 0 known
        self.assertEqual(V.bits(b'z', 12, None), 'z')
        self.assertEqual(V.bits(b'zz1', 12, None), "'bzzzzzzzzzzz1")
        self.assertEqual(V.bits(b'10100101', 8, (5, 2)), '9')
        self.assertEqual(V.bits(b'1u0h', 4, None), "'b1x01")         # VHDL U: unknown
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
                 (('5', 4, {5: 'IDLE'}, None), 'IDLE'), (('x1', 8, None, 'hex'), 'x1'), (('ff', 8, None, 'unsigned'), '255'),
                 (("'b10x1", 4, None, None), 'x'), (("'b10x1", 4, None, 'bin'), '10x1'), (("'b1x0101", 6, None, 'hex'), 'x5'),
                 (('xz', 8, None, 'bin'), 'xxxxzzzz'), (('x1', 6, None, 'bin'), 'xx0001')]
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

    def test_real_kinds_and_non_finite(self):
        s = H.wavejson_of(H.fixture('realkinds'))
        self.assertEqual({p: x.get('kind') for p, x in s.items()}, {'tb.r': 'real', 'tb.rt': 'real', 'tb.sr': 'real', 'tb.rp': 'real', 'tb.msg': 'string'})
        self.assertEqual(s['tb.r']['tv'], [[0, '1.25'], [10000, 'inf'], [20000, '-inf'], [30000, 'nan'], [40000, '0']])
        self.assertEqual(s['tb.rt']['tv'], [[0, '7'], [10000, '2.5e-09']])
        self.assertEqual(s['tb.sr']['tv'], [[0, '0.5'], [30000, '-inf']])

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

    def test_vector_in_parts(self):
        s = H.wavejson_of(H.fixture('split'))
        self.assertEqual({p: (x.get('width', 1), x['tv']) for p, x in s.items()}, {
            'tb.err': (2, [[0, '1'], [5000, '0'], [6000, '2']]), 'tb.data': (16, [[0, '0201'], [5000, '0203']]),
            'tb.e': (2, [[0, '1']]), 'tb.x': (8, [[0, '3a']]), 'tb.y': (8, [[0, '81']]), 'tb.q': (3, [[0, "'b1x0"], [5000, "'b1x1"]])})
        part = H.wavejson_of(H.fixture('split'), '--exact', '--signals', 'tb.data[15:8]')['data[15:8]']   # a part's own slice
        self.assertEqual(part['tv'], [[0, '02']])

    def test_bit_blasted_shared_code_and_vector_value(self):
        s = H.wavejson_of(H.fixture('blasted'))
        self.assertEqual(s['tb.flags']['tv'], [[0, '4'], [5000, '7'], [7000, '3']])   # flags[0] flags[1] both !
        self.assertEqual(s['tb.e']['tv'], [[0, '1'], [5000, '0'], [7000, '2']])       # b01 for one bit: its last digit

    def test_tokens_apart_by_any_white_space(self):
        s = H.wavejson_of(H.fixture('spaces'))
        self.assertEqual((s['tb.s']['tv'], s['tb.bus']['tv']), ([[0, '0'], [5000, '1'], [9000, '0'], [12000, '1']],
                                                               [[0, '2'], [5000, '3'], [7000, '4'], [12000, 'f']]))

    def test_several_tokens_per_line(self):
        sigs = H.wavejson_of(H.fixture('oneline'))
        self.assertEqual((sigs['tb.s']['tv'], sigs['tb.v']['tv']), ([[0, '0'], [10000, '1']], [[0, '1'], [10000, '2']]))

    def test_vhdl_and_body_comment(self):
        v = H.wavejson_of(H.fixture('vhdl'))
        self.assertEqual(v['top.v']['tv'], [[0, 'x'], [10000, '6'], [20000, "'b1xx0"]])   # VHDL U W - unknown, the rest kept
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

    def test_omitted_signals_in_meta(self):
        """A catalog's "show": false: in the dump, not in the page; meta.omitted names them by scope (the page's find says so)."""
        with H.tmp() as d:
            cfg = os.path.join(d, 'c.json')
            with open(cfg, 'w') as f:
                json.dump({'waves': H.fixture('scopes'), 'exact': True, 'signals': {'tb.blk.a': {}, 'tb.fk.b': {'show': False},
                                                                                    'tb.fn.c': {'show': False}}}, f)
            rc, out, err = H.run_tool('vcd2wavedrom', '--config', cfg)
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)['meta']['omitted'], {'why': 'config', 'paths': {'tb.fk': ['b'], 'tb.fn': ['c']}})
        with H.tmp() as d:   # paths under --scope: the dump's own; one the dump does not have is not said to be in it
            cfg = os.path.join(d, 'c.json')
            with open(cfg, 'w') as f:
                json.dump({'waves': H.fixture('scopes'), 'exact': True, 'scope': 'tb', 'hierarchy': True,
                           'signals': {'blk.a': {}, 'fk.b': {'show': False}, 'not_in_dump': {'show': False}}}, f)
            rc, out, err = H.run_tool('vcd2wavedrom', '--config', cfg)
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)['meta']['omitted'], {'why': 'config', 'paths': {'tb.fk': ['b']}})

    def test_wide_vector(self):
        self.assertEqual(H.wavejson_of(H.fixture('wide'))['tb.w']['tv'][0][1], 'f' * 24)

    def readers(self):
        """The FST readers here: fst2vcd (GTKWave) and the sva CLI's `sva vcd` (WAVELENS_FST picks one)."""
        import svabuild
        return [r for r, ok in (('fst2vcd', shutil.which('fst2vcd')), ('sva', svabuild.find_bin())) if ok]

    def convert(self, reader, cfg, view, waves):
        old = os.environ.get('WAVELENS_FST')
        os.environ['WAVELENS_FST'] = reader
        try:
            rc, out, err = H.run_tool('vcd2wavedrom', '--config', cfg, '--view', view, '--waves', waves)
        finally:
            os.environ.pop('WAVELENS_FST') if old is None else os.environ.__setitem__('WAVELENS_FST', old)
        self.assertEqual(rc, 0, err)
        d = json.loads(out)
        return d, d['meta'].pop('tool'), d['meta'].pop('waves')

    def test_vcd_vs_fst_identical(self):
        """The APB example's VCD and its FST, the FST read by each reader there is: the same WaveJSON."""
        ex = os.path.join(H.BUILD, 'examples', 'apb')
        if not os.path.exists(os.path.join(ex, 'apb.fst')):
            self.skipTest('make examples')
        if not self.readers():
            self.skipTest('neither fst2vcd nor the sva CLI')
        cfg = os.path.join(H.ROOT, 'examples', 'apb', 'apb.config.json')
        vcd = self.convert('', cfg, 'transfers', os.path.join(ex, 'apb.vcd'))[0]
        for r in self.readers():
            with self.subTest(r):
                doc, tool, _ = self.convert(r, cfg, 'transfers', os.path.join(ex, 'apb.fst'))
                self.assertEqual(tool, 'wavelens reader (' + ('fst2vcd' if r == 'fst2vcd' else 'sva vcd') + ')')
                self.assertEqual(doc, vcd)

    def test_fst_readers_identical(self):
        """The FSM example's FST (enum tables, a struct scope) through fst2vcd and through sva vcd: the same WaveJSON."""
        fst = os.path.join(H.BUILD, 'examples', 'fsm', 'fsm.fst')
        if not os.path.exists(fst) or len(self.readers()) < 2:
            self.skipTest('make examples, fst2vcd and the sva CLI')
        cfg = os.path.join(H.ROOT, 'examples', 'fsm', 'fsm.config.json')
        for view in ('run', 'status'):
            with self.subTest(view):
                self.assertEqual(self.convert('fst2vcd', cfg, view, fst)[0], self.convert('sva', cfg, view, fst)[0])

    # small dumps made FST by vcd2fst: what the two FST readers once told apart
    FST_PROBES = {
        # bit selects glued and apart: not adjacent (err[0], err[2]), a lone one, a vector bit by bit, a range in two
        # parts, escaped names with brackets (wellen merges \e[0] \e[1]: sva vcd reads the FST's names itself)
        'selects': ('$var wire 1 ! err[0] $end\n$var wire 1 " err[2] $end\n$var wire 1 # mem[3] $end\n'
                    '$var wire 1 $ d[4] $end\n$var wire 1 % d[5] $end\n$var wire 1 & d[6] $end\n$var wire 1 \' d[7] $end\n'
                    '$var wire 8 ( data [7:0] $end\n$var wire 8 ) data [15:8] $end\n$var wire 1 * q [3] $end\n'
                    '$var wire 1 + \\e[0] $end\n$var wire 1 , \\e[1] $end\n',
                    '#0\n1!\n0"\n1#\n0$\n1%\n0&\n1\'\nb1 (\nb10 )\n1*\n0+\n1,\n#5\n0!\n1"\nb11 (\n0,\n#7\n1$\n0#\n'),
        # strings with a tab, a newline, a space, quotes, a backslash, a byte above 127: one token each in the text, no
        # change of another signal made up from what follows a raw newline
        'strings': ('$var string 1 ! s $end\n$var wire 1 " a $end\n',
                    '#0\nsx !\n0"\n#1\nsa\\x09b\\x20c !\n#2\nsq\\x0a1"\\x3f\\x27\\x5c\\x01\\xc3\\xa9 !\n#3\n1"\n#4\ns\\x5c040 !\n'),
        # changes at 0 and 5, the dump ends at 10: the idle stretch is part of the dump
        'idle_tail': ('$var wire 1 ! a $end\n$var wire 4 " b $end\n', '#0\n0!\nb0 "\n#5\n1!\nb101 "\n#10\n'),
    }

    def read_all(self, reader, fst):
        """The FST through `reader` (WAVELENS_FST): every variable, exact, with the hierarchy -> the WaveJSON, the reader's
        name and the dump's path left out of its meta."""
        import dumpscan
        old = os.environ.get('WAVELENS_FST')
        os.environ['WAVELENS_FST'] = reader
        try:
            d = dumpscan.read(fst, None)
            sigs = ','.join(p for p, v in d.vars.items() if v.kind != 'event')
            rc, out, err = H.run_tool('vcd2wavedrom', '--waves', fst, '--exact', '--hierarchy', '--signals', sigs)
        finally:
            os.environ.pop('WAVELENS_FST') if old is None else os.environ.__setitem__('WAVELENS_FST', old)
        self.assertEqual(rc, 0, err)
        doc = json.loads(out)
        doc['meta'].pop('tool')
        doc['meta'].pop('waves')
        return sorted(d.vars), doc

    def test_fst_readers_identical_on_probes(self):
        """FST_PROBES through fst2vcd and through sva vcd: the same variables, the same WaveJSON."""
        if not shutil.which('vcd2fst') or len(self.readers()) < 2:
            self.skipTest('vcd2fst, fst2vcd and the sva CLI')
        with H.tmp() as d:
            for name, (decl, body) in self.FST_PROBES.items():
                with self.subTest(name):
                    vcd = H.vcd(d, body, '$timescale 1ns $end\n$scope module tb $end\n' + decl + '$upscope $end\n$enddefinitions $end\n',
                                name + '.vcd')
                    fst = os.path.join(d, name + '.fst')
                    subprocess.run(['vcd2fst', vcd, fst], capture_output=True, check=True)
                    self.assertEqual(self.read_all('sva', fst), self.read_all('fst2vcd', fst))

if __name__ == '__main__':
    unittest.main()
