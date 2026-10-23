"""tools/dumpscan.py: the VCD reader on what simulators write (tests/unit/vcd/*.vcd, each under 1 kB)."""
import os, shutil, unittest

from tests.unit import helpers as H
import dumpscan
from common import WaveError


def read(name, body='collect'):
    d = dumpscan.read(H.fixture(name), None)
    if body == 'collect':
        return dumpscan.read(H.fixture(name), 'collect', {c for v in d.vars.values() for c, _ in v.members})
    return dumpscan.read(H.fixture(name), body)


class Header(unittest.TestCase):
    def test_timescale_one_line(self):
        self.assertEqual(read('crlf', None).unit_ps, 1000)

    def test_timescale_three_lines(self):
        self.assertEqual(read('ts3', None).unit_ps, 100)

    def test_timescale_spaced_unit(self):
        self.assertEqual(read('ts1', None).unit_ps, 1e7)

    def test_crlf(self):
        d = read('crlf')
        self.assertEqual(set(d.vars), {'tb.b', 'tb.s'})
        self.assertEqual(d.trans[b'!'], [(0, b'1010'), (10, b'0101')])

    def test_comment_with_end(self):
        self.assertEqual(list(read('comment', None).vars), ['tb.s'])

    def test_var_range_alias(self):
        d = read('crlf', None)
        self.assertEqual(d.find('tb.b[3:0]'), 'tb.b')

    def test_range_glued_to_ref(self):
        d = read('range_in_ref', None)
        self.assertIn('tb.data', d.vars)
        self.assertEqual(d.vars['tb.data'].width, 8)
        self.assertEqual(d.find('tb.data[7:0]'), 'tb.data')

    def test_bit_blasted_vector(self):
        d = read('range_in_ref', None)
        self.assertEqual(d.vars['tb.mem'].width, 2)
        self.assertEqual(sorted(b for _, b in d.vars['tb.mem'].members), [(0, 0), (1, 1)])
        self.assertEqual(d.find('tb.mem[1]'), 'tb.mem')

    def test_id_reused_across_scopes(self):
        d = read('idreuse', None)
        self.assertEqual(d.vars['tb.clk'].members, d.vars['tb.dut.clk'].members)

    def test_scope_kinds(self):
        d = read('scopes', None)
        self.assertEqual(d.scopes, {'tb.blk': 'begin', 'tb.fk': 'fork', 'tb.fn': 'function', 'tb.st': 'struct',
                                    'tb.ifc': 'interface', 'tb.pk': 'package', 'tb.tk': 'task'})

    def test_var_kinds(self):
        d = read('string_event', None)
        self.assertEqual({p: v.kind for p, v in d.vars.items()}, {'tb.msg': 'string', 'tb.ev': 'event', 'tb.clk': 'wire'})
        self.assertEqual(read('real', None).vars['tb.volt'].kind, 'real')
        self.assertEqual(read('integer', None).vars['tb.n'].kind, 'integer')

    def test_escaped_id_not_rewritten(self):
        d = read('escaped', None)
        self.assertEqual(list(d.vars), ['tb.\\x[0].y', 'tb.\\a.b', 'tb.\\bus$x'])
        self.assertEqual(d.vars['tb.\\x[0].y'].members, [(b'!', None)])   # not a bit of a vector "\x"
        self.assertEqual(d.vars['tb.\\bus$x'].width, 4)

    def test_duplicate_path_merges_codes(self):
        d = read('dup')
        self.assertEqual(d.vars['tb.s'].members, [(b'!', None), (b'"', None)])

    def test_real_kinds_and_string_size_0(self):
        d = read('realkinds', None)
        self.assertEqual({p: dumpscan.TEXT_KINDS.get(v.kind) for p, v in d.vars.items()},
                         {'tb.r': 'real', 'tb.rt': 'real', 'tb.sr': 'real', 'tb.rp': 'real', 'tb.msg': 'string'})
        self.assertEqual(d.vars['tb.msg'].width, 1)   # declared with size 0 (fst2vcd, sva vcd): one value, as in the page

    def test_ranges_apart_merged_by_bit(self):
        d = read('split', None)
        self.assertEqual({p: v.width for p, v in d.vars.items()}, {'tb.err': 2, 'tb.data': 16, 'tb.e': 2, 'tb.x': 8, 'tb.y': 8, 'tb.q': 3})
        self.assertEqual(d.vars['tb.err'].members, [(b'!', (0, 0)), (b'"', (1, 1))])   # err [0], err [1]: not one bit twice
        self.assertEqual(d.vars['tb.data'].members, [(b'#', (7, 0)), (b'$', (15, 8))])
        self.assertEqual(d.vars['tb.x'].members, [(b"'", (3, 0)), (b'(', (7, 4))])      # [11:8] [15:12]: from bit 8, as wellen
        self.assertEqual(d.vars['tb.y'].members, [(b')', (7, 4)), (b'*', (3, 0))])      # [0:3] [4:7]: index 0 on the left
        self.assertEqual(d.vars['tb.q'].members, [(b'+', (2, 2)), (b',', (0, 0))])      # q[3] q[1]: q[2] not declared
        self.assertEqual((d.find('tb.x[15:8]'), d.find('tb.e[0]'), d.find('tb.data[7:0]')), ('tb.x', 'tb.e', None))   # a part: a slice

    def test_two_bits_one_code(self):
        d = read('blasted', 'count')
        self.assertEqual(d.vars['tb.flags'].members, [(b'!', (0, 0)), (b'!', (1, 1)), (b'"', (2, 2))])
        self.assertEqual(d.changes['tb.flags'], 2)   # the code ! once

    def test_missing_enddefinitions_raises(self):
        with self.assertRaisesRegex(WaveError, 'no \\$enddefinitions'):
            read('noend', None)

    def test_missing_file_one_line(self):
        with self.assertRaisesRegex(WaveError, 'no such dump: .*nope.vcd'):
            dumpscan.read('nope.vcd', None)


class Body(unittest.TestCase):
    def test_first_change_after_zero(self):
        d = read('late')
        self.assertEqual((d.t_start, d.t_end), (100000, 200000))

    def test_zero_time_only(self):
        d = read('zero')
        self.assertEqual((d.t_start, d.t_end), (0, 0))

    def test_dumpvars_without_time(self):
        d = read('dumpvars_only')
        self.assertEqual(d.trans[b'!'], [(0, b'0')])

    def test_wide_vector(self):
        d = read('wide')
        self.assertEqual(d.vars['tb.w'].width, 96)
        self.assertEqual(len(d.trans[b'!'][0][1]), 96)

    def test_real_and_string_values(self):
        self.assertEqual(read('real').trans[b'!'], [(0, b'r1.5'), (10, b'r2.25'), (20, b'r-3e-2')])
        self.assertEqual(read('string_event').trans[b'!'], [(0, b'sHello'), (10, b'sWorld')])

    def test_several_tokens_per_line(self):
        d = read('oneline')
        self.assertEqual(d.trans[b'!'], [(0, b'0'), (10, b'1')])
        self.assertEqual(d.trans[b'"'], [(0, b'01'), (10, b'10')])
        self.assertEqual(read('oneline', 'count').changes, {'tb.s': 1, 'tb.v': 1})

    def test_tokens_apart_by_any_white_space(self):
        # indented, tabs, a vector's code on the next line, a time inside a line: the page's token rule
        d = read('spaces')
        self.assertEqual(d.trans[b'!'], [(0, b'0'), (5, b'1'), (9, b'0'), (12, b'1')])
        self.assertEqual(d.trans[b'"'], [(0, b'0010'), (5, b'0011'), (7, b'0100'), (12, b'1111')])
        self.assertEqual(d.trans[b'#'], [(0, b'0'), (7, b'1')])
        c = read('spaces', 'count')
        self.assertEqual((c.changes, c.t_end), ({'tb.s': 3, 'tb.bus': 3, 'tb.t': 1}, 12000))

    def test_time_inside_a_change_line(self):
        c = read('inline_time', 'count')
        self.assertEqual((c.changes, c.t_start, c.t_end), ({'tb.s': 2, 'tb.v': 1}, 0, 8000))
        d = read('inline_time')
        self.assertEqual((d.trans[b'!'], d.trans[b'"'], d.t_end), ([(0, b'0'), (5, b'1'), (8, b'0')], [(0, b'00'), (8, b'11')], 8000))

    def test_comment_in_body_skipped(self):
        d = read('body_comment')
        self.assertEqual(d.trans[b'!'], [(0, b'0'), (10, b'1')])
        self.assertEqual((d.t_start, d.t_end), (0, 10000))

    def test_vhdl_values_folded(self):
        d = read('vhdl')
        self.assertEqual(d.trans[b'!'], [(0, b'x'), (10, b'1'), (20, b'0')])
        self.assertEqual([v for _, v in d.trans[b'"']], [b'UUUU', b'01HL', b'1W-0'])   # folded by the converter's bits()

    def test_time_backwards_is_an_error(self):
        for name in ('backwards', 'unsorted'):
            with self.subTest(name), self.assertRaisesRegex(WaveError, 'time goes back'):
                read(name)
            with self.subTest(name + ' count'), self.assertRaisesRegex(WaveError, 'time goes back'):
                read(name, 'count')

    def test_dumpoff_counted(self):
        # $dumpoff writes every value x: counted as changes (documented in mkconfig.py's help)
        self.assertEqual(read('dumpoff', 'count').changes, {'tb.bus': 4, 'tb.clk': 4})

    def test_huge_times_warn(self):
        with H.stderr() as e:
            read('huge2', 'count')
        self.assertIn('above 2^53', e.getvalue())

    def test_fine_timescale_warns(self):
        with H.stderr() as e:
            read('huge', 'count')
        self.assertIn('finer than 1 ps', e.getvalue())

    def test_scan_lists_aliases(self):
        info = dumpscan.scan(H.fixture('crlf'))
        self.assertEqual(info['tb.b[3:0]'], info['tb.b'])
        self.assertEqual(info['tb.b']['changes'], 1)

    def test_enum_tables(self):   # an FST as text (sva vcd, fst2vcd -e): the table, then a reference to it before each $var
        info = dumpscan.scan(H.fixture('enum'), body=False)
        self.assertEqual(info['tb.state']['enum'], {0: 'IDLE', 1: 'RUN', 2: 'DONE'})
        self.assertEqual(info['tb.st.s']['enum'], {0: 'IDLE', 1: 'RUN', 2: 'DONE'})
        self.assertIsNone(info['tb.plain']['enum'])

    @unittest.skipUnless(shutil.which('fst2vcd') and os.path.exists(os.path.join(H.BUILD, 'examples', 'apb', 'apb.fst')), 'fst2vcd and make examples')
    def test_fst_through_fst2vcd(self):
        d = dumpscan.read(os.path.join(H.BUILD, 'examples', 'apb', 'apb.fst'), 'count')
        v = dumpscan.read(os.path.join(H.BUILD, 'examples', 'apb', 'apb.vcd'), 'count')
        self.assertEqual(set(d.vars), set(v.vars))
        self.assertEqual(d.changes, v.changes)


if __name__ == '__main__':
    unittest.main()
