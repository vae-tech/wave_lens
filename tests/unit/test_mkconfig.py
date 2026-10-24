"""tools/mkconfig.py: the catalog of a dump, the rules, --update, the SystemVerilog sources (--sv)."""
import json, os, re, unittest

from tests.unit import helpers as H
import mkconfig as M
import svabuild
from common import WaveError

SIGS = [{'path': 'tb.clk', 'width': 1, 'changes': 40}, {'path': 'tb.rst_n', 'width': 1, 'changes': 1},
        {'path': 'tb.dut.data', 'width': 8, 'changes': 30}, {'path': 'tb.dut.k', 'width': 4, 'changes': 0},
        {'path': 'tb.dut.u.deep', 'width': 1, 'changes': 100}]


class Build(unittest.TestCase):
    def test_depth_constants_hide(self):
        cat = M.build(SIGS, {'select': {'depth': 1, 'hide': ['tb.rst*']}})
        self.assertEqual({p: e['show'] for p, e in cat.items()},
                         {'tb.clk': True, 'tb.rst_n': False, 'tb.dut.data': True, 'tb.dut.k': False, 'tb.dut.u.deep': False})

    def test_budget_drops_the_deepest_first(self):
        with H.stderr() as e:
            cat = M.build(SIGS, {'select': {'depth': 9, 'budget': 100}})
        self.assertEqual([p for p, x in cat.items() if x['show']], ['tb.clk', 'tb.rst_n', 'tb.dut.data'])
        self.assertIn('select.budget 100', e.getvalue())

    def test_rules_width_ops_and_order(self):
        cat = M.build(SIGS, {'rules': [{'match': '*', 'width': '>1', 'radix': 'hex'}, {'match': ['*clk'], 'color': '#00f'},
                                       {'match': 'tb.dut.*', 'width': 8, 'radix': 'dec'}]})
        self.assertEqual((cat['tb.dut.data']['radix'], cat['tb.dut.k']['radix'], cat['tb.clk']['color']), ('dec', 'hex', '#00f'))

    def test_rule_unknown_key_dies(self):
        with self.assertRaisesRegex(WaveError, 'unknown key'):
            M.build(SIGS, {'rules': [{'match': '*', 'colour': 'red'}]})

    def test_bad_rule_width_dies(self):
        with self.assertRaisesRegex(WaveError, 'bad rule width'):
            M.build(SIGS, {'rules': [{'match': '*', 'width': 'wide', 'radix': 'hex'}]})

    def test_select_unknown_key_rejected(self):
        with self.assertRaisesRegex(WaveError, r'"select": unknown key\(s\) dept'):
            M.build(SIGS, {'select': {'dept': 1}})


class Merge(unittest.TestCase):
    def test_keeps_edits_takes_info(self):
        old = {'tb.clk': {'show': False, 'color': '#f00', 'width': 1, 'changes': 1}, 'tb.gone': {'show': True}}
        new = {'tb.clk': {'show': True, 'color': '', 'width': 1, 'changes': 40, 'enum': {'0': 'A'}}, 'tb.new': {'show': True}}
        with H.stderr() as e:
            out = M.merge(old, new)
        self.assertEqual(out['tb.clk'], {'show': False, 'color': '#f00', 'width': 1, 'changes': 40, 'enum': {'0': 'A'}})
        self.assertNotIn('tb.gone', out)
        self.assertIn('1 signal(s) no longer in the dump', e.getvalue())

    def test_enum_not_replaced(self):
        out = M.merge({'s': {'enum': {'0': 'MINE'}}}, {'s': {'enum': {'0': 'DUMP'}}})
        self.assertEqual(out['s']['enum'], {'0': 'MINE'})

    def test_validates_signal_keys(self):
        with self.assertRaisesRegex(WaveError, 'unknown signal setting.*colour'):
            M.merge({'s': {'colour': 'red'}}, {'s': {}})


class Tool(unittest.TestCase):
    def test_catalog_of_a_dump(self):
        with H.tmp() as d:
            out = os.path.join(d, 'c.json')
            rc, _, err = H.run_tool('mkconfig', H.fixture('string_event'), '--out', out)
            self.assertEqual(rc, 0, err)
            cfg = json.load(open(out))
        self.assertEqual(list(cfg['signals']), ['tb.msg', 'tb.clk'])   # the event is left out
        self.assertIn('event variable(s) left out', err)
        self.assertEqual(cfg['waves'], os.path.relpath(H.fixture('string_event'), d))

    def test_exists_without_update_dies(self):
        with H.tmp() as d:
            out = os.path.join(d, 'c.json')
            H.run_tool('mkconfig', H.fixture('crlf'), '--out', out)
            rc, _, err = H.run_tool('mkconfig', H.fixture('crlf'), '--out', out)
        self.assertEqual(rc, 1)
        self.assertIn('exists: --update', err)

    def test_update_refuses_foreign_dump_rewrites_waves(self):
        with H.tmp() as d:
            out = os.path.join(d, 'c.json')
            H.run_tool('mkconfig', H.fixture('crlf'), '--out', out)               # tb.b, tb.s
            rc, _, err = H.run_tool('mkconfig', H.fixture('wide'), '--out', out, '--update')   # tb.w only
            self.assertEqual(rc, 1)
            self.assertIn('2 of the 2 signals', err)
            rc, _, err = H.run_tool('mkconfig', H.fixture('late'), '--out', out, '--update')   # tb.s, tb.b again
            self.assertEqual(rc, 0, err)
            cfg = json.load(open(out))
            rc, _, err = H.run_tool('mkconfig', H.fixture('wide'), '--out', out, '--update', '--force')
            self.assertEqual(rc, 0, err)
            cfg2 = json.load(open(out))
        self.assertEqual(cfg['waves'], os.path.relpath(H.fixture('late'), d))
        self.assertEqual(list(cfg2['signals']), ['tb.w'])

    def test_bad_dump_one_line(self):
        for f in ('backwards', 'noend'):
            with self.subTest(f), H.tmp() as d:
                rc, _, err = H.run_tool('mkconfig', H.fixture(f), '--out', os.path.join(d, 'c.json'))
                self.assertEqual((rc, 'Traceback' in err), (1, False), err)

    def test_dumps_one_line_per_signal_blank_between_scopes(self):
        text = M.dumps({'waves': 'x.vcd', 'signals': {'tb.a': {'show': True}, 'tb.b': {'show': True}, 'tb.u.c': {'show': False}}})
        self.assertIn('"tb.b": {"show": true},\n\n    "tb.u.c"', text)
        self.assertEqual(json.loads(text)['signals']['tb.u.c'], {'show': False})


class Sources(unittest.TestCase):
    SV = '''package p;
  typedef enum logic [1:0] {IDLE, RUN = 2'd2, DONE} st_t;   // a comment
  typedef struct packed { st_t state; logic [3:0] cnt; logic v; } stat_t;
  typedef struct packed { stat_t s; logic [1:0] tag; } outer_t;
endpackage
module m; p::st_t state_q, state_d; stat_t status; outer_t o; enum {A, B} inline_e; endmodule
'''

    def setUp(self):
        self.d = H.tmp()
        self.path = os.path.join(self.d.name, 'p.sv')
        with open(self.path, 'w') as f:
            f.write(self.SV)

    def tearDown(self):
        self.d.cleanup()

    def test_sv_enums_typedef_and_inline(self):
        e = M.sv_enums([self.path])
        self.assertEqual(e['state_q'], {0: 'IDLE', 2: 'RUN', 3: 'DONE'})
        self.assertEqual(e['state_d'], e['state_q'])
        self.assertEqual(e['inline_e'], {0: 'A', 1: 'B'})

    def test_sv_values(self):
        # a value that is not a literal (a parameter, an expression, a negative number) is not guessed; 08 is decimal
        self.assertEqual([M.sv_value(v, p) for v, p in (("4'hA", 0), ('', 3), ('0x10', 0), ("'b11", 0), ('X', 5), ('1 << 2', 0), ('-1', 0),
                                                        ('08', 0), ("4'd1A", 0))], [10, 4, 16, 3, None, None, None, 8, None])

    def test_sources_fixture_expected_tables(self):
        # tests/unit/sv/sources.sv against the tables it should give (the page reads it against the same file: smoke readers):
        # a type used in another module, an array, a port, an inline enum; not a function's names, not struct members; a
        # name of two types and the enums it does not read left out with a note each
        want = json.load(open(os.path.join(H.ROOT, 'tests', 'unit', 'sv', 'sources.json')))
        e, f, notes = M.sv_tables(M.sv_texts([os.path.join(H.ROOT, 'tests', 'unit', 'sv', 'sources.sv')]))
        self.assertEqual({k: {str(a): b for a, b in v.items()} for k, v in e.items()}, want['enums'])
        self.assertEqual(f, want['fields'])
        self.assertEqual([re.match(r'(?:enum |struct )?(\w+)', n).group(1) for n in notes], want['notes'])

    def test_sv_structs_nested_fields_msb_first(self):
        st = M.sv_structs([self.path])
        self.assertEqual(st['status'], [{'name': 'state', 'msb': 6, 'lsb': 5, 'enum': {'0': 'IDLE', '2': 'RUN', '3': 'DONE'}},
                                        {'name': 'cnt', 'msb': 4, 'lsb': 1}, {'name': 'v', 'msb': 0, 'lsb': 0}])
        self.assertEqual([f['msb'] for f in st['o']], [8, 1])


@H.needs(svabuild.find_bin(), 'the sva CLI (make sva-build)')
class SvaBinds(unittest.TestCase):
    def test_binds_only_chosen_open_none(self):
        with H.tmp() as d:
            sv = os.path.join(d, 'c.sv')
            with open(sv, 'w') as f:
                f.write('module c(input clk);\n  a_one: assert property (@(posedge clk) s);\n  a_none: assert property (@(posedge clk) nope);\nendmodule\n')
            dump = H.vcd(d, '#0\n0!\n0"\n#5\n1!\n1"\n', header='$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n'
                         '$var wire 1 " s $end\n$scope module u $end\n$var wire 1 ! clk $end\n$upscope $end\n$upscope $end\n$enddefinitions $end\n')
            out = os.path.join(d, 'c.json')
            rc, _, err = H.run_tool('mkconfig', dump, '--out', out, '--sva', sv)
            self.assertEqual(rc, 0, err)
            bind = json.load(open(out))['bind']
        self.assertEqual([(b['assert'], b['scope'], b['show']) for b in bind], [('a_one', 'tb', True), ('a_none', '', False)])
        self.assertIn('1 bound to their only instance', err)


if __name__ == '__main__':
    unittest.main()
