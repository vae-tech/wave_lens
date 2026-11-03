"""tools/gtkw.py and mkconfig.py --gtkw (stage 27): a GTKWave save file as a view of a config; dumpscan.py --stats."""
import json, os, unittest
from tests.unit import helpers as H
import dumpscan
import gtkw

SAVE = """[*] GTKWave Analyzer v3.3.104
[dumpfile] "x.vcd"
[dumpfile_mtime] "Mon Nov  3 09:00:00 2026"
[timestart] 20
[size] 1600 900
*-17.000000 85 45 -1 -1
[treeopen] tb.
[sst_width] 233
@28
tb.clk
@800200
-Handshake
@28
tb.req
[color] 1
tb.ack
@1000200
-Handshake
@22
tb.data[7:0]
@24
tb.count[7:0]
@424
tb.delta[7:0]
@8024
tb.level[7:0]
@200
-
@28
tb.gone
#{tb.bits} tb.a tb.b
[pattern_trace] 1
"""


class Parse(unittest.TestCase):
    def test_traces_groups_radix_window_markers(self):
        g = gtkw.parse(SAVE)
        self.assertEqual((g['waves'], g['from']), ('x.vcd', 20))
        self.assertEqual(g['markers'], [{'t': 85, 'label': 'marker'}, {'t': 45, 'label': 'A'}])
        by = {s['path']: s for s in g['signals']}
        self.assertEqual(list(by), ['tb.clk', 'tb.req', 'tb.ack', 'tb.data', 'tb.count', 'tb.delta', 'tb.level', 'tb.gone'])
        self.assertEqual([by[p].get('radix') for p in ('tb.data', 'tb.count', 'tb.delta', 'tb.clk')], ['hex', 'dec', 'signed', 'bin'], '@24 is dec, not hex')
        self.assertEqual((by['tb.ack'].get('color'), by['tb.level'].get('analog'), by['tb.req'].get('group')), ('#e03131', True, 'Handshake'))
        self.assertEqual(g['groups'], [{'name': 'Handshake', 'signals': ['tb.req', 'tb.ack'], 'closed': False}])
        self.assertTrue(any('not read: #{tb.bits}' in n for n in g['notes']))
        v, notes = gtkw.view_of(g, 1000, {'tb.clk', 'tb.req', 'tb.ack', 'tb.data'})
        self.assertEqual((v['signals'], v['from'], v['state']['markers'][0]), ('tb.clk,tb.req,tb.ack,tb.data', '20000ps', {'t': 85000, 'label': 'marker'}))
        self.assertIn('tb.gone: not in the dump, left out', notes)


REAL = os.path.join(H.ROOT, 'docs', 'reviews', 'review-2026-11-03', 'stages-16-28', 'probe', 'd', 'real.gtkw')


class RealSaveFile(unittest.TestCase):
    """Review S27-1..4: what GTKWave 3.3 writes — nested groups, a translate filter, an alias, marker names, a bit, its times."""
    def setUp(self):
        self.g = gtkw.parse(H.text(REAL))
        self.by = {}
        for s in self.g['signals']:
            self.by.setdefault(s['path'], s)

    def test_groups_nest(self):
        grp = {x['name']: x for x in self.g['groups']}
        self.assertEqual((self.by['tb.dut.pwdata']['group'], grp['inner'].get('parent'), grp['inner']['signals']), ('APB', 'APB', ['tb.dut.psel']))
        self.assertNotIn('group', self.by['tb.dut.op'], 'after APB ends: no group')

    def test_filter_alias_marker_names_bits(self):
        self.assertFalse(any(p.startswith(('^', '+')) for p in self.by), list(self.by))
        self.assertTrue(any('translate filter' in n for n in self.g['notes']))
        self.assertEqual(gtkw.aliases_of(self.g), {'tb.dut.pwdata': 'my_alias'})
        self.assertEqual([m['label'] for m in self.g['markers']], ['marker', 'A reset done', 'C first write'])
        v, _ = gtkw.view_of(self.g, 1000)
        self.assertEqual(v['state']['bits'], ['tb.dut.pwdata'])

    def test_times_in_the_dimension(self):
        """A "10 ns" dump: GTKWave's [timestart] 1200 is 1200 ns (the number multiplies ticks, the file keeps the dimension)."""
        self.assertEqual((gtkw.dim_ps(10000), gtkw.dim_ps(1000), gtkw.dim_ps(100), gtkw.dim_ps(1)), (1000, 1000, 1, 1))
        v, _ = gtkw.view_of(self.g, 10000)
        self.assertEqual((v['from'], v['state']['markers'][0]['t']), ('1200000ps', 15300000))

    def test_crlf(self):
        g = gtkw.parse(H.text(REAL).replace('\n', '\r\n'))
        self.assertEqual([s['path'] for s in g['signals']], [s['path'] for s in self.g['signals']])


class Stats(unittest.TestCase):
    def test_a_value_written_again_is_no_change(self):
        """Review S27-5: a register the simulator writes on every assignment, its value the same: dead, not busy."""
        with H.tmp() as d:
            vcd = os.path.join(d, 's.vcd')
            with open(vcd, 'w', encoding='utf-8') as f:
                f.write('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 " same $end\n$var wire 4 # v [3:0] $end\n'
                        '$upscope $end\n$enddefinitions $end\n#0\n0!\n0"\nb0 #\n#10\n1!\n0"\nb0 #\n#20\n0!\n0"\nb1 #\n#30\n1!\n')
            s = dumpscan.stats(dumpscan.read(vcd, 'count'))
            self.assertEqual((s['dead'], {b['path']: b['changes'] for b in s['busiest']}), (['tb.same'], {'tb.clk': 3, 'tb.v': 1}))

    def test_over_the_cap_said(self):
        """Review S27-6: a dump over STATS_MAX: no statistics, a note."""
        import contextlib, io, mkhtml
        with H.tmp() as d:
            vcd = os.path.join(d, 's.vcd')
            with open(vcd, 'w', encoding='utf-8') as f:
                f.write('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n#10\n1!\n')
            old, mkhtml.STATS_MAX = mkhtml.STATS_MAX, 10
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    self.assertIsNone(mkhtml.dump_stats(vcd))
            finally:
                mkhtml.STATS_MAX = old
            self.assertIn('no statistics of the dump', err.getvalue())


class MkConfig(unittest.TestCase):
    def test_a_view_of_the_save_file(self):
        with H.tmp() as d:
            vcd = os.path.join(d, 'x.vcd')
            with open(vcd, 'w', encoding='utf-8') as f:
                f.write('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 " req $end\n$var wire 1 # ack $end\n'
                        '$var wire 8 $ data [7:0] $end\n$var wire 8 % count [7:0] $end\n$var wire 8 & delta [7:0] $end\n$var wire 8 ( level [7:0] $end\n'
                        '$var wire 1 ) dead $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n0"\n0#\nb0 $\nb0 %\nb0 &\nb0 (\n0)\n#10\n1!\n1"\n#20\n0!\nb1 $\n#30\n1!\n1#\n#40\n')
            g = os.path.join(d, 'x.gtkw')
            with open(g, 'w', encoding='utf-8') as f:
                f.write(SAVE)
            out = os.path.join(d, 'x.config.json')
            rc, _, err = H.run_tool('mkconfig', '--gtkw', g, '--out', out)
            self.assertEqual(rc, 0, err)
            self.assertIn('tb.gone: not in the dump, left out', err)
            v = H.load(out)['views']['gtkw']
            self.assertEqual((v['signals'].split(',')[:3], v['from'], v['state']['radix']['tb.count']), (['tb.clk', 'tb.req', 'tb.ack'], '20000ps', 'dec'))
            c = H.load(out)
            c['views']['mine'] = {'signals': 'tb.clk'}
            H.dump(c, out)
            with open(g, 'w', encoding='utf-8') as f:
                f.write(SAVE.replace('tb.req\n', '+{request} tb.req\n'))
            rc, _, err = H.run_tool('mkconfig', '--gtkw', g, '--out', out, '--update')
            c = H.load(out)
            self.assertEqual((rc, sorted(c['views']), c['signals']['tb.req'].get('alias')), (0, ['all', 'gtkw', 'mine'], 'request'), err)
            rc, _, err = H.run_tool('mkconfig', '--gtkw', g, '--out', os.path.join(d, 'y.config.json'), '--strict')
            self.assertNotEqual(rc, 0)
            rc, _, err = H.run_tool('mkhtml', '--config', out, '--no-sva', '--out', os.path.join(d, 'x.html'))
            self.assertEqual(rc, 0, err)
            self.assertIn('"stats":{"signals":8,"changing":4,"dead":4', H.text(os.path.join(d, 'x.html')).replace(' ', ''))
            s = dumpscan.stats(dumpscan.read(vcd, 'count'))
            self.assertEqual((s['signals'], s['changing'], s['dead'], s['busiest'][0]['path']), (8, 4, ['tb.count', 'tb.dead', 'tb.delta', 'tb.level'], 'tb.clk'))
            rc, out_, err = H.run_tool('dumpscan', vcd, '--stats', '--json')
            self.assertEqual((rc, json.loads(out_)['changing']), (0, 4), err)


if __name__ == '__main__':
    unittest.main()
