"""tools/wavemcp.py: the MCP protocol over stdio, the tools against a generated dump whose answers are known
(tests/mcp_bench.py gen_vcd), names, errors."""
import io, json, os, shutil, subprocess, sys, threading, time, unittest

from tests.unit import helpers as H
from tests import mcp_bench as B
import dumpscan
import svabuild
import viewedit as E
import wavemcp as W

CACHE = None   # the bridges of these tests announce themselves here, not in ~/.cache/wavelens/live (a VS Code there would connect)
WAS = None   # XDG_CACHE_HOME before: back after these tests (review VI T10: the other modules' see their own)


def setUpModule():
    global CACHE, WAS
    CACHE, WAS = H.tmp(), os.environ.get('XDG_CACHE_HOME')
    os.environ['XDG_CACHE_HOME'] = CACHE.name


def tearDownModule():
    if WAS is None:
        os.environ.pop('XDG_CACHE_HOME', None)
    else:
        os.environ['XDG_CACHE_HOME'] = WAS
    CACHE.cleanup()


class Dump(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = H.tmp()
        cls.vcd = os.path.join(cls.d.name, 'bench.vcd')
        cls.truth = B.gen_vcd(cls.vcd, cycles=4000)

    @classmethod
    def tearDownClass(cls):
        cls.d.cleanup()

    def call(self, tool, **a):
        text, err = W.call(tool, {'dump': self.vcd, **a})
        self.assertFalse(err, text)
        return json.loads(text)

    def error(self, tool, **a):
        text, err = W.call(tool, {'dump': self.vcd, **a})
        self.assertTrue(err, text)
        return text

    def test_info(self):
        i = self.call('wave_info')
        self.assertEqual((i['unit'], i['start'], i['end'], i['signals']), ('ns', 0, 40000, 167))
        self.assertEqual([(c['name'], c['period'], c['mhz'], c['first_rise']) for c in i['clocks']], [('tb.clk', 10, 100.0, 5)])
        self.assertEqual(i['resets'], ['tb.rst_n'])
        self.assertIn(['tb.dut.regs', 150], i['scopes'])

    def test_names_as_the_other_tools_take_them(self):   # review 0.31 M2, T10: a tail of a path in wave_diff and wave_cut
        self.assertEqual(self.call('wave_diff', b=self.vcd, signals=['s_tvalid', 'tb.dut.s_t*'])['signals_compared'], 4)
        self.assertEqual(self.call('wave_diff', b=self.vcd, scope='tb.dut', signals=['s_tdata'])['signals_compared'], 1)
        out = os.path.join(self.d.name, 'tail.vcd')
        self.assertEqual(self.call('wave_cut', out=out, signals=['s_tvalid', 's_tready'], to=100)['variables'], 2)
        self.assertIn('no signal', self.error('wave_cut', out=out, signals=['zz_nope']))

    def test_times_outside_the_dump(self):   # review 0.31 M3, T11
        r = self.call('wave_values', signals=['s_tvalid'], at=[10, 1e9, -5])
        self.assertEqual(len(r['notes']), 1)
        self.assertIn('outside the dump (0 … 40000 ns)', r['notes'][0])
        self.assertIn('1000000000', r['notes'][0])
        self.assertNotIn('notes', self.call('wave_values', signals=['s_tvalid'], at=[10]))
        self.assertIn('outside the dump', self.error('wave_changes', signals=['s_tvalid'], **{'from': '1ms', 'to': '2ms'}))
        self.assertIn('outside the dump', self.error('wave_cut', out=os.path.join(self.d.name, 'out.vcd'), **{'from': '1ms', 'to': '2ms'}))

    def test_rows_of_one_length(self):   # review 0.31 M7, T9
        s = self.call('wave_signals', limit=200)
        self.assertEqual(s['columns'], ['path', 'width', 'changes', 'extra'])
        self.assertEqual({len(x) for x in s['signals']}, {4})
        q = W.call('wave_signals', {'dump': H.fixture('realkinds')})
        self.assertIn('real', {x[3] for x in json.loads(q[0])['signals']})

    def test_page_out_in_no_directory(self):   # review 0.31 M8
        self.assertIn('"out": no such directory', self.error('wave_page', signals=['s_tvalid'], out='/nope/dir/x.html'))

    def test_signals(self):
        s = self.call('wave_signals', scope='tb.dut', depth=1, pattern='s_t*')
        self.assertEqual([x[0] for x in s['signals']], ['s_tvalid', 's_tready', 's_tlast', 's_tdata'])
        p = self.call('wave_signals', pattern='regs', limit=100)
        self.assertEqual((p['total'], len(p['signals']), p['next_offset']), (150, 100, 100))
        self.assertEqual(len(self.call('wave_signals', pattern='regs', offset=100)['signals']), 50)

    def test_values_changes_find(self):
        t = self.truth
        rise = self.call('wave_find', signal='rst_n', edge='rise')
        self.assertEqual(rise['times'], [t['reset_release_ns']])
        self.assertTrue(any('rst_n' in n for n in rise.get('notes', [])) or rise['signal'] == 'rst_n')
        v = self.call('wave_values', signals=['tb.rst_n', 'tb.dut.fifo.count'], at=[t['reset_release_ns'], '10us'], side='before', radix='dec')
        self.assertEqual(v['rows'][0][:2], [t['reset_release_ns'], '0'])
        self.assertEqual(v['rows'][1][0], 10000)
        c = self.call('wave_changes', signals=['tb.dut.perf.cyc_cnt'], to=100, limit=3)['signals']['tb.dut.perf.cyc_cnt']
        self.assertEqual((c['initial'], c['changes'], c['more']), ('0x0000', [[15, '0x0001'], [25, '0x0002'], [35, '0x0003']], c['count'] - 3))
        s = self.call('wave_stats', signals=['tb.dut.fifo.count', 'tb.clk'], radix='dec')['signals']
        self.assertEqual(int(s['tb.dut.fifo.count']['max']), t['fifo_max'])
        self.assertEqual(s['tb.clk']['period'], {'median': 10, 'min': 10, 'max': 10})
        mx = self.call('wave_find', signal='tb.dut.fifo.count', value=t['fifo_max'], limit=1)
        self.assertEqual(mx['rows'][0][0], t['fifo_max_ns'])

    def test_sample(self):
        s = self.call('wave_sample', signals=['tb.rst_n'], clock='tb.clk', to=200, only_changes=False)
        self.assertEqual(s['columns'], ['cycle', 't', 'tb.rst_n'])
        self.assertEqual(s['rows'][:2], [[0, 5, '0'], [1, 15, '0']])
        self.assertEqual([r for r in s['rows'] if r[2] == '1'][0][:2], [11, 115])   # rises at the edge of cycle 10: seen at the next one
        ch = self.call('wave_sample', signals=['tb.rst_n'])
        self.assertEqual([r[0] for r in ch['rows']], [0, 11])
        self.assertEqual(ch['clock'], 'tb.clk')

    def test_names(self):
        names = H.fixture('names')
        amb = W.call('wave_values', {'dump': names, 'signals': ['state'], 'at': 0})
        self.assertEqual(amb, ('"state" is ambiguous: tb.dut.state, tb.other.state — give more of its path or a scope', True))
        self.assertEqual(json.loads(W.call('wave_values', {'dump': names, 'signals': ['state'], 'scope': 'tb.other', 'at': 0})[0])['rows'], [[0, '0']])
        self.assertIn('no signal "nosuch"', self.error('wave_values', signals=['nosuch'], at=0))
        self.assertIn('similar: tb.dut.fifo.count', self.error('wave_values', signals=['fifo_count'], at=0))
        v = self.call('wave_values', signals=['fifo.count', 'perf.cyc_cnt[3:0]', 'perf.cyc_cnt[0]'], at=35, radix='dec')
        self.assertEqual(v['rows'][0][2:], ['3', '1'])
        part = self.call('wave_values', signals=['tb.rst_n', 'fifo.wr_en'], at=0)   # of several, one not found: the others
        self.assertEqual((part['columns'], part['missing']), (['t', 'tb.rst_n'], ['no signal "fifo.wr_en"']))
        self.assertIn('bad time', self.error('wave_values', signals=['tb.clk'], at='5 parsecs'))
        self.assertIn('no such dump', W.call('wave_info', {'dump': '/nonexist.vcd'})[0])
        self.assertIn('"to" (1) is before "from" (2)', self.error('wave_changes', signals=['tb.clk'], **{'from': 2, 'to': 1}))

    def test_wavejson(self):
        out = os.path.join(self.d.name, 'w.json')
        r = self.call('wave_page', signals=['tb.rst_n', 'fifo.count'], clock='auto', to=300, out=out)
        self.assertEqual(r['wavejson'], out)
        with open(out) as f:
            doc = json.load(f)
        self.assertEqual([s['name'] for s in doc['signal']], ['rst_n', 'count'])
        self.assertEqual(doc['meta']['mode'], 'clock')

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_to_fst(self):
        """wave_to_fst: the FST beside the VCD (or at out) that the tools read as the VCD; an error names the line."""
        out = os.path.join(self.d.name, 'b.fst')
        r = self.call('wave_to_fst', out=out)
        self.assertEqual(r['fst'], out)
        self.assertRegex(r['written'], r'^167 variables \(\d+ signals\), \d+ value changes, 0 enum tables$')
        a, b = self.call('wave_info'), json.loads(W.call('wave_info', {'dump': out})[0])
        self.assertEqual((a['signals'], a['end'], a['clocks']), (b['signals'], b['end'], b['clocks']))
        with H.tmp() as d:
            bad = H.vcd(d, '#0\n0!\n#20\n1!\n#5\n0!\n', name='back.vcd')
            text, err = W.call('wave_to_fst', {'dump': bad})
            self.assertTrue(err)
            self.assertIn('back.vcd:10: #5 after #20: the time goes back', text)
            self.assertFalse(os.path.exists(os.path.join(d, 'back.fst')))
            # the FST named as the CLI names it, not read from its line ("job: one" has ": " in it); progress is no note
            os.mkdir(os.path.join(d, 'job: one'))
            out = os.path.join(d, 'job: one', 'o.fst')
            r = self.call('wave_to_fst', out=out)
            self.assertEqual((r['fst'], r['bytes'] > 0), (out, True))
            self.assertRegex(r['written'], r'^167 variables ')
        self.assertEqual(W.fst_notes('sva: tb.vcd: progress: 9 variables (9 signals) in 2 scopes, 0 enum tables; the values next (70 MB)\n'
                                     'sva: tb.vcd: progress: 10% (line 9, #5)\nsva: tb.vcd:12: a value of "%", which no $var declares: left out\n'),
                         ['tb.vcd:12: a value of "%", which no $var declares: left out'])

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_progress_is_no_note(self):
        """Review of the runs T-08 b: the CLI's lines of how far it is, as `sva fst` and `sva diff` write them (one function of
        main.rs, its marker W.PROGRESS; --large-bytes: a small dump says them), are no note; a note between them stays."""
        exe = svabuild.find_bin()
        with H.tmp() as d:
            v = H.vcd(d, ''.join(f'#{t}\n{t // 10 % 2}!\n' for t in range(0, 100, 10)) + '#100\n0', name='p.vcd')   # a value cut off at the end: a note
            f = os.path.join(d, 'p.fst')
            a = subprocess.run([exe, 'fst', v, '--out', f, '--large-bytes', '1'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            b = subprocess.run([exe, 'diff', f, f, '--json', '-', '--large-bytes', '1'], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            self.assertEqual((a.returncode, b.returncode), (0, 0), a.stderr + b.stderr)
            fst = [x for x in a.stderr.splitlines() if 'progress' in x]
            diff = [x for x in b.stderr.splitlines() if 'progress' in x]
            self.assertTrue(len(fst) >= 2 and all(x.startswith(f'sva: {v}: progress: ') for x in fst), a.stderr)   # the declarations, a tenth
            self.assertTrue(diff and all(x.startswith(f'sva: {f} ~ {f}: progress: ') for x in diff), b.stderr)
            notes = W.fst_notes(a.stderr + b.stderr)
            self.assertEqual(len(notes), 1, notes)
            self.assertTrue(notes[0].startswith(v + ':') and 'left out' in notes[0], notes)

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_json_after_the_warnings_of_wellen(self):
        """Review of the runs T-08 c: where sva cannot put wellen's "WARN: …" aside (fd 1 on Windows) they stand on stdout before
        the JSON: wave_diff and wave_runs read the JSON after them (the CLI wrapped to say one first)."""
        with H.tmp() as d:
            stub = os.path.join(d, 'sva')
            with open(stub, 'w', encoding='utf-8') as f:
                f.write(f'#!/bin/sh\necho "WARN: time decreased from 20 to 5"\nexec \'{svabuild.find_bin()}\' "$@"\n')
            os.chmod(stub, 0o755)
            r = self.call('wave_diff', b=self.vcd, signals=['s_tvalid'], sva_bin=stub)
            self.assertEqual((r['equal'], r['signals_compared']), (True, 1))
            v, runs = H.vcd(d, '#0\n0!\n#10\n1!\n', name='r.vcd'), os.path.join(d, 'runs')
            text, err = W.call('wave_runs', {'action': 'keep', 'dump': v, 'dir': runs, 'sva_bin': stub})
            self.assertFalse(err, text)
            text, err = W.call('wave_runs', {'action': 'list', 'dir': runs, 'sva_bin': stub})
            self.assertFalse(err, text)
            self.assertEqual([x['id'] for x in json.loads(text)['runs']], [1])

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_diff(self):
        """wave_diff (stage 14.2): the dump against itself, one value other, a signal taken out, the scope renamed (map),
        the run 5 ns later (offset), counts per state (segment), dump for a; times in ns, a bus in hex."""
        with open(self.vcd, encoding='utf-8') as f:
            text = f.read()
        head, body = text.split('$enddefinitions $end\n', 1)
        code = {l.split()[4]: l.split()[3] for l in head.splitlines() if l.startswith('$var')}
        cnt, data = code['count'], code['s_tdata']
        lines, orig = body.split('\n'), body.split('\n')
        # B: the first value of s_tdata after 1000 ns other; err not in it
        at, k = 0, None
        for i, l in enumerate(lines):
            if l.startswith('#'):
                at = int(l[1:])
            elif at > 1000 and l.endswith(' ' + data) and k is None:
                k, t_k = i, at
                lines[i] = f'b{0xdeadbeef:b} {data}'
        err = code['err']
        b_head = '\n'.join(l for l in head.splitlines() if not (l.startswith('$var') and l.split()[3] == err)) + '\n'
        b_lines = [l for l in lines if l not in ('0' + err, '1' + err)]
        b = os.path.join(self.d.name, 'b.vcd')
        with open(b, 'w', encoding='utf-8') as f:
            f.write(b_head + '$enddefinitions $end\n' + '\n'.join(b_lines))
        same = self.call('wave_diff', b=self.vcd)
        self.assertEqual((same['equal'], same['differ'], same['signals'], same['unit']), (True, 0, [], 'ns'))
        self.assertEqual((same['from'], same['to'], same['signals_compared']), (0, 40000, 167))
        r = W.call('wave_diff', {'dump': self.vcd, 'b': b, 'limit': 5})
        r = json.loads(r[0])
        self.assertFalse(r['equal'])
        self.assertEqual((r['first']['t'], r['first']['signal'], r['first']['b']), (t_k, 'tb.dut.s_tdata', '0xdeadbeef'))
        self.assertEqual(r['only_a'], ['tb.dut.err'])
        self.assertEqual([x['path'] for x in r['signals']], ['tb.dut.s_tdata'])
        # the scope renamed in B: paired by the map
        moved = os.path.join(self.d.name, 'moved.vcd')
        with open(moved, 'w', encoding='utf-8') as f:
            f.write(text.replace('$scope module dut $end', '$scope module core $end'))
        self.assertEqual(self.call('wave_diff', b=moved)['signals_compared'], 2, 'without the map: tb.clk, tb.rst_n')
        m = self.call('wave_diff', b=moved, map={'tb.dut': 'tb.core'})
        self.assertEqual((m['equal'], m['signals_compared'], m['map']), (True, 167, [{'a': 'tb.dut', 'b': 'tb.core', 'signals': 165}]))
        # 5 ns later
        late = os.path.join(self.d.name, 'late.vcd')
        with open(late, 'w', encoding='utf-8') as f:
            f.write(head + '$enddefinitions $end\n' + '\n'.join(f'#{int(l[1:]) + 5}' if l.startswith('#') else l for l in orig))
        self.assertFalse(self.call('wave_diff', b=late, signals=['tb.dut.s_t*'])['equal'])
        o = self.call('wave_diff', b=late, offset='5ns', signals='tb.dut.s_t*')
        self.assertEqual((o['equal'], o['offset'], o['from'], o['signals_compared']), (True, 5, 0, 4))
        g = self.call('wave_diff', b=self.vcd, segment='tb.dut.ctl.state', signals=['count'])
        self.assertTrue(len(g['segments']) > 2 and all(x['differ'] == 0 for x in g['segments']), g['segments'][:3])
        self.assertEqual(sum(x['changes'] for x in g['segments']), g['compared'])
        self.assertIn('no such file', self.error('wave_diff', b='/nope.vcd'))
        self.assertIn('no argument "nope"', self.error('wave_diff', b=b, nope=1))
        self.assertEqual([x['signal'] for x in r['rank']][:1], ['tb.dut.s_tdata'], 'who differed first')
        # stage 23: the assertions' results of two runs
        doc = lambda fails: {'unit': 'ps', 'cycles': [k * 10000 for k in range(10)], 'assertions': [{'name': 'p', 'scope': 'tb', 'stats': {},
                             'attempts': [{'start': s, 'end': f, 'result': 'fail', 'failed_at': f} for s, f in fails]}]}
        ra, rb = os.path.join(self.d.name, 'ra.json'), os.path.join(self.d.name, 'rb.json')
        for f, x in ((ra, doc([(1, 2)])), (rb, doc([(1, 3), (5, 6)]))):
            with open(f, 'w', encoding='utf-8') as h:
                json.dump(x, h)
        d = W.call('wave_diff', {'results_a': ra, 'results_b': rb})
        d = json.loads(d[0])
        self.assertEqual((d['same'], d['new'], d['moved'], d['assertions'][0]['new'], d['assertions'][0]['moved'][0]['b']['failed_at']),
                         (False, 1, 1, [{'start': 50, 'failed_at': 60}], 30), d)
        self.assertIn('one or the other', self.error('wave_diff', results_a=ra, results_b=rb, a=self.vcd))
        self.assertIn('no signal', self.error('wave_diff', b=b, signals=['zz_nope']))

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_compare_on_a_page(self):
        """view_edit compare (stage 14.3.3) on a page's file: sva diff of its dump beside it and dump; view_get says it."""
        page, b = os.path.join(self.d.name, 'cmp.html'), os.path.join(self.d.name, 'cmpb.vcd')
        with open(self.vcd, encoding='utf-8') as f:
            text = f.read()
        code = next(l.split()[3] for l in text.splitlines() if l.startswith('$var') and l.split()[4] == 'err')
        with open(b, 'w', encoding='utf-8') as f:
            f.write(text.replace(f'\n1{code}\n', f'\n0{code}\n', 1))
        self.call('wave_page', signals=['tb.dut.err', 'tb.dut.s_tvalid'], out=page)
        r = json.loads(W.call('view_edit', {'page': page, 'ops': [{'op': 'compare', 'dump': b}]})[0])
        self.assertEqual((r['results'][0]['name'], r['results'][0]['compared'], r['results'][0]['differ']), ('cmpb.vcd', 2, 1), r)
        g = json.loads(W.call('view_get', {'page': page, 'rows': ''})[0])
        self.assertEqual((g['compare']['differ'], g['compare']['missing']), (1, 0), g)
        self.assertIn(['err', 1, '≠'], g['rows']['rows'])
        r = json.loads(W.call('view_edit', {'page': page, 'ops': [{'op': 'compare', 'off': True}]})[0])
        self.assertNotIn('compare', json.loads(W.call('view_get', {'page': page})[0]))
        made = os.path.join(self.d.name, 'cmp.json')
        doc = self.call('wave_page', signals=['tb.dut.err'], out=made, compare=b)
        with open(made) as f:
            self.assertEqual(json.load(f)['compare']['differ'], 1, doc)

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_cut(self):
        """wave_cut: a window of some signals as a small VCD the tools read: its span, its values at "from"."""
        out = os.path.join(self.d.name, 'cut.vcd')
        r = self.call('wave_cut', out=out, signals=['tb.dut.fifo.*', 'cyc_cnt'], **{'from': 1000, 'to': '2us'})
        self.assertEqual((r['out'], r['variables'], r['from'], r['to']), (out, 4, 1000, 2000))
        i = json.loads(W.call('wave_info', {'dump': out})[0])
        self.assertEqual((i['start'], i['end'], i['signals']), (1000, 2000, 4))
        full = self.call('wave_values', signals=['tb.dut.perf.cyc_cnt'], at=1000)
        cut = json.loads(W.call('wave_values', {'dump': out, 'signals': ['tb.dut.perf.cyc_cnt'], 'at': 1000})[0])
        self.assertEqual(full['rows'], cut['rows'])
        self.assertIn('"out"', self.error('wave_cut', out=self.vcd))
        self.assertIn('no signal "zz_nope"', self.error('wave_cut', out=out, signals=['zz_nope']))

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_cut_of_an_array_element(self):
        """WL-009: an element of an unpacked array (Verilator's FST: "ptr[0]", wave_signals: "ptr.[0]") by either name,
        of the FST, of its VCD and of a cut."""
        import subprocess
        vcd = os.path.join(self.d.name, 'arr.vcd')
        with open(vcd, 'w') as f:
            f.write('$timescale 1ns $end\n$scope module tb $end\n$var logic 32 ! ptr[0] [31:0] $end\n$var logic 32 " ptr[1] [31:0] $end\n'
                    '$upscope $end\n$enddefinitions $end\n#0\nb0 !\nb1 "\n#10\nb101 !\n#20\n')
        subprocess.run([svabuild.find_bin(), 'fst', vcd, '-q'], check=True)
        fst, cut, again = vcd[:-4] + '.fst', os.path.join(self.d.name, 'arr.cut.vcd'), os.path.join(self.d.name, 'arr.again.vcd')
        listed = [r[0] for r in json.loads(W.call('wave_signals', {'dump': fst})[0])['signals']]
        self.assertEqual(listed, ['tb.ptr.[0]', 'tb.ptr.[1]'])
        for src in (fst, vcd):
            for name in ('tb.ptr.[0]', 'tb.ptr[0]', 'ptr[0]', 'ptr.[0]'):
                with self.subTest(src=src[-3:], name=name):
                    text, err = W.call('wave_cut', {'dump': src, 'out': cut, 'to': 15, 'signals': [name]})
                    self.assertFalse(err, text)
                    text, err = W.call('wave_cut', {'dump': cut, 'out': again, 'signals': [name]})
                    self.assertFalse(err, text)
                    self.assertEqual(json.loads(W.call('wave_values', {'dump': again, 'signals': [name], 'at': 12})[0])['rows'], [[12, '0x00000005']])

    def test_signals_of_an_array_by_pattern(self):
        """Review 2026-11-05 B-06: wave_signals takes [ as it is, an element either way (q[0], q.[0]); * and ? stay wildcards."""
        vcd = os.path.join(self.d.name, 'arr2.vcd')
        with open(vcd, 'w') as f:
            f.write('$timescale 1ns $end\n$scope module top $end\n$var logic 8 ! q[0] [7:0] $end\n$var logic 8 " q[1] [7:0] $end\n'
                    '$var logic 4 # m[1][2] [3:0] $end\n$var wire 1 $ qx $end\n$upscope $end\n$enddefinitions $end\n#0\nb0 !\nb0 "\nb0 #\n0$\n#10\n')
        got = lambda pat: [r[0] for r in json.loads(W.call('wave_signals', {'dump': vcd, 'pattern': pat})[0])['signals']]
        for pat, want in (('q[0]', ['top.q.[0]']), ('q.[0]', ['top.q.[0]']), ('[0]', ['top.q.[0]']), ('m[1]', ['top.m.[1][2]']),
                          ('top.q[*', ['top.q.[0]', 'top.q.[1]']), ('q?1]', ['top.q.[1]']), ('q*', ['top.q.[0]', 'top.q.[1]', 'top.qx'])):
            with self.subTest(pat=pat):
                self.assertEqual(sorted(got(pat)), want)

    def test_an_array_element_in_the_scope_form(self):
        """Review 2026-11-05 (runs) B-24: an element written as a scope of its own ($scope module ptr + $var … [0]) is
        top.ptr.[0] (not top.ptr..[0]) and found by every spelling, by wave_signals, wave_values and sva vcd --signals,
        of the VCD and of its FST."""
        vcd = os.path.join(self.d.name, 'scoped.vcd')
        with open(vcd, 'w') as f:
            f.write('$timescale 1ns $end\n$scope module top $end\n$var logic 8 ! q[0] [7:0] $end\n$scope module ptr $end\n'
                    '$var wire 1 $ [0] $end\n$var wire 1 % [1] $end\n$upscope $end\n$upscope $end\n$enddefinitions $end\n'
                    '#0\nb0 !\n0$\n0%\n#10\n1$\n#20\n')
        self.assertEqual(sorted(dumpscan.read(vcd, 'count').vars), ['top.ptr.[0]', 'top.ptr.[1]', 'top.q.[0]'])
        self.assertEqual([dumpscan.glued(p) for p in ('top.ptr..[0]', 'm.[1].[2]', 'q[0]')], ['top.ptr[0]', 'm[1][2]', 'q[0]'])
        sva = svabuild.find_bin()
        if sva:
            subprocess.run([sva, 'fst', vcd, '-q'], check=True)
        for src in [vcd] + ([vcd[:-4] + '.fst'] if sva else []):
            sig = lambda pat: [r[0] for r in json.loads(W.call('wave_signals', {'dump': src, 'pattern': pat})[0])['signals']]
            for name in ('top.ptr.[0]', 'top.ptr[0]', 'ptr[0]', 'ptr.[0]', 'top.ptr..[0]'):
                with self.subTest(src=src[-3:], name=name):
                    self.assertEqual(sig(name), ['top.ptr.[0]'])
                    text, err = W.call('wave_values', {'dump': src, 'signals': [name], 'at': 12})
                    self.assertFalse(err, text)
                    self.assertEqual(json.loads(text)['rows'], [[12, '1']])
                    if sva:
                        r = subprocess.run([sva, 'vcd', src, '--signals', name], capture_output=True, text=True)
                        self.assertEqual((r.returncode, r.stdout.count('$var'), '[0] $end' in r.stdout), (0, 1, True), r.stderr)

    def test_goto_time_in_ns(self):   # review 2026-11-05 B-12: a live goto's t in ns, as the cursor's
        self.assertEqual(W.ns_out([{'op': 'goto', 't': 100000, 'view': 'v', 'sel': None}], True)[0]['t'], 100)

    @H.needs(svabuild.find_bin(), 'no sva CLI')
    def test_sva(self):
        t = self.truth
        r = self.call('sva_check', scope='tb.dut.ctl', source='req_ack: assert property (@(posedge clk) req |-> ##[1:4] ack);\n'
                      'never: assert property (@(posedge clk) 1 |-> 1);\nmiss: assert property (@(posedge clk) nosuch);')
        if t['violations']:
            f = r['failed'][0]
            self.assertEqual((f['name'], f['stats']['fail']), ('req_ack', t['violations']))
            self.assertEqual(f['failures'][0][3] - 10, t['first_req_ns'])
        else:
            self.assertIn('req_ack', r['passed'])
        self.assertIn('never', r['passed'])
        code = self.call('sva_check', scope='tb.dut.ctl', assertions=['assert property (@(posedge clk) req |-> ##[1:4] ack);'])
        self.assertEqual(len(code.get('failed', [])) + len(code.get('passed', [])), 1)   # the text where the names go: evaluated
        self.assertEqual(r['not_evaluated'], [['miss', 'no nosuch']])
        f = self.call('wave_find', expr='s_tvalid && s_tready && s_tlast', scope='tb.dut', limit=2)
        self.assertEqual((f['matches'], len(f['rows']), f['more']), (t['frames'], 2, t['frames'] - 2))
        self.assertIn('did not evaluate', self.error('wave_find', expr='s_tvalid &&', scope='tb.dut'))


class Values(unittest.TestCase):
    def test_bits_value_four_state(self):
        """A literal with x / z: the stream's form of those bits (hex when no nibble mixes them), as the converter writes it."""
        self.assertEqual(W.bits_value("'b10x1", 4), "'b10x1")
        self.assertEqual(W.bits_value("4'b10z1", 4), "'b10z1")
        self.assertEqual(W.bits_value("8'hx5", 8), 'x5')
        self.assertEqual(W.bits_value("'bx1", 4), "'bxxx1")
        self.assertEqual(W.bits_value("'h1f", 8), '1f')
        self.assertIsNone(W.bits_value("'b10q1", 4))
        self.assertEqual(W.bits_value("4'bx1", 8), "'b0000xxx1")   # sized: x to its size, then 0s

    def test_cycles_zero_in_ns(self):
        """The cycles' zero: a command's answer and a state's config in ns, as every other time the agent reads."""
        got = W.ns_out([{'op': 'cycles', 'cycles': {'cycles': True, 'cycleClock': 'clk', 'cycleZero': 50000}}], True)
        self.assertEqual(got[0]['cycles']['cycleZero'], 50)
        self.assertEqual(W.state_ns({'config': {'cycleZero': 50000, 'cycles': True}})['config']['cycleZero'], 50)

    @H.needs(W.svabuild.find_bin(), 'the sva CLI (make sva-build)')
    def test_live_compare_keeps_show(self):
        """view_edit compare {dump, show} on a live dump's tab: sva diff here, the page gets the result with its cut, and show."""
        head = '$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! v $end\n$upscope $end\n$enddefinitions $end\n'
        with H.tmp() as d:
            a, b = H.vcd(d, '#0\n0!\n#10\n1!\n#30\n', header=head, name='a.vcd'), H.vcd(d, '#0\n0!\n#15\n1!\n#30\n', header=head, name='b.vcd')
            got = W.live_compare({'op': 'compare', 'dump': 'b.vcd', 'show': 'overlay'}, {'path': a}, {}, {})
            self.assertEqual((got['show'], got['result']['differ'], got['result']['shift']), ('overlay', 1, 0), b)
            self.assertIn('#15\n1!', got['result']['vcd'])
            self.assertNotIn('show', W.live_compare({'op': 'compare', 'dump': 'b.vcd'}, {'path': a}, {}, {}))

    def test_state_without_the_cut(self):
        """A compare's cut of the second dump: what the page carries, not what an agent reads; its size said, the rest kept."""
        st = {'compare': {'name': 'b.vcd', 'vcd': 'x' * 100, 'signals': {}}, 'compareShow': 'b'}
        got = W.state_ns(st)
        self.assertEqual(got['compare'], {'name': 'b.vcd', 'signals': {}, 'vcd_bytes': 100})
        self.assertEqual((got['compareShow'], len(st['compare']['vcd'])), ('b', 100), 'the state given stays as it was')


class Views(unittest.TestCase):
    """view_edit / view_get on a page's file, and live through the bridge with a page played here (its stream, hello,
    replies): the token, the Origin, a page that goes."""

    @classmethod
    def setUpClass(cls):
        cls.d = H.tmp()
        cls.page = os.path.join(cls.d.name, 'p.html')
        j = os.path.join(cls.d.name, 'v.json')
        with open(j, 'w', encoding='utf-8') as f:
            json.dump({'signal': [{'name': 'clk', 'wave': 'p.......'}, ['tb', {'name': 'valid', 'wave': '0.1.0...'}]],
                       'time': {'t0': 0, 't1': 80000, 'cycle': 10000, 'unit': 'ps'}}, f)
        rc, _, err = H.run_tool('mkhtml', f'one={j}', '--no-sva', '--out', cls.page)
        assert rc == 0, err

    @classmethod
    def tearDownClass(cls):
        cls.d.cleanup()

    def tearDown(self):
        for b in W.BRIDGE:
            b.close()
        W.BRIDGE.clear()

    def call(self, tool, **a):
        text, err = W.call(tool, a)
        self.assertFalse(err, text)
        return json.loads(text)

    def test_file(self):
        r = self.call('view_edit', page=self.page, ops=[{'op': 'bookmark', 't': 25, 'signal': 'valid', 'text': 'see'},
                                                        {'op': 'view', 'from': 10, 'to': '0.05us'}, {'op': 'cursor', 't': 'x'}])
        self.assertEqual((r['view'], r['results'][:2], r['errors']), ('one', [{'op': 'bookmark', 'n': 1}, {'op': 'view', 'from': 10, 'to': 50}], 1))
        g = self.call('view_get', page=self.page, rows='')
        self.assertEqual((g['bookmarks'], g['window'], g['rows']['total']), ([{'n': 1, 't': 25, 'signal': 'tb.valid', 'text': 'see'}], [10, 50], 3))
        self.assertTrue(g['edits'].startswith('r1@'))
        self.assertIn('"page" is required', W.call('view_edit', {'ops': [{'op': 'fit'}]})[0])
        self.assertIn('"ops": a list of commands', W.call('view_edit', {'page': self.page, 'ops': []})[0])

    def test_marker_lanes(self):
        """A marker's text on a line over or under a signal in the agent's words: the path resolved, view_get in ns."""
        r = self.call('view_edit', page=self.page, ops=[{'op': 'marker', 'id': 'all', 'delete': True},
                                                        {'op': 'marker', 't': 35, 'label': 'here', 'signal': 'valid', 'lift': 'below', 'color': '#2f9e44'},
                                                        {'op': 'marker', 't': 45, 'signal': 'valid'}, {'op': 'marker', 'id': 2, 'color': None, 'signal': None}])
        self.assertEqual([x.get('id') for x in r['results']], ['all', 1, 2, 2], r)
        ms = self.call('view_get', page=self.page)['markers']
        self.assertEqual(ms[0]['signal'], 'tb.valid')
        self.assertEqual((ms[0]['id'], ms[0]['t'], ms[0]['label'], ms[0]['lift'], ms[0]['color']), (1, 35, 'here', 'below', '#2f9e44'))
        self.assertEqual(ms[1], {'id': 2, 't': 45})   # at the top, pale
        self.assertIn('marker(id? t? label? color? signal? lift? hidden? dmin? dmax? delete?)', next(t for t in W.TOOLS if t['name'] == 'view_edit')['description'])

    def test_view_exprs(self):   # after test_file: it counts the revisions of the page
        """The expressions in the agent's words: into a page's file, what they found in ns, go and matches only live."""
        r = self.call('view_edit', page=self.page, ops=[{'op': 'expr', 'text': 'valid && ready', 'label': 'beat', 'color': '#c00'},
                                                        {'op': 'expr', 'text': 'valid', 'row': True, 'mark': 'line'}, {'op': 'expr_go', 'id': 1}, {'op': 'expr_matches'}])
        self.assertEqual([x.get('id') for x in r['results'][:2]], [1, 2], r)
        self.assertTrue(all('page only' in x['error'] for x in r['results'][2:]), r)
        self.assertEqual(self.call('view_get', page=self.page)['exprs'], [{'expr': 'valid && ready', 'label': 'beat', 'color': '#c00', 'row': False, 'id': 1},
                                                                          {'expr': 'valid', 'mark': 'line', 'id': 2}])
        self.call('view_edit', page=self.page, ops=[{'op': 'expr', 'id': 2, 'gap': True}, {'op': 'gaps', 'idle': 3, 'keep': 0}])
        got = self.call('view_get', page=self.page)
        self.assertEqual((got['exprs'][1]['gap'], got['gaps']['by'], got['gaps']['view'], got['gaps']['idle']), (True, [2], True, 3))
        self.call('view_edit', page=self.page, ops=[{'op': 'expr', 'id': 2, 'gap': False}])
        self.assertNotIn('by', self.call('view_get', page=self.page).get('gaps', {}))
        self.call('view_edit', page=self.page, ops=[{'op': 'expr', 'id': 'all', 'delete': True}, {'op': 'gaps', 'reset': True}])
        self.assertNotIn('exprs', self.call('view_get', page=self.page))
        out = W.ns_out([{'op': 'expr_go', 't': 5000, 'k': 1, 'n': 3}, {'op': 'expr', 'n': 2, 'time': 3000, 'first': 1000, 'last': 2000, 'min': 1000, 'max': 2000, 'share': 0.5},
                        {'op': 'expr_matches', 'first': 1000, 'matches': [[1000, 2000]]}, {'op': 'expr_matches', 'exprs': [{'id': 1, 'n': 1, 'first': 4000, 'share': 0.25}]}], True)
        self.assertEqual((out[0]['t'], out[0]['k'], out[1]['time'], out[1]['n'], out[1]['share'], out[2]['first'], out[2]['matches'], out[3]['exprs']),
                         (5, 1, 3, 2, 0.5, 1, [[1, 2]], [{'id': 1, 'n': 1, 'first': 4, 'share': 0.25}]))
        self.assertEqual(W.ns_out([{'op': 'expr', 'cut': {'gaps': 2, 'kept': 5000, 'total': 20000, 'parts': [[2000, 7000]]}}], True)[0]['cut'], {'gaps': 2, 'kept': 5, 'total': 20, 'parts': [[2, 7]]})
        self.assertIn('expr(id? text? scope? label? color? on? row? mark? gap? radix? analog? delete?)', next(t for t in W.TOOLS if t['name'] == 'view_edit')['description'])

    def test_gaps_view(self):
        """The gaps on the waves in the agent's words: view_get says them, a cut (the page's) in ns."""
        r = self.call('view_edit', page=self.page, ops=[{'op': 'gaps', 'on': True, 'view': True, 'idle': 8, 'signals': 'PSEL'}])
        self.assertTrue(r['results'][0]['gaps']['gapView'])
        self.assertNotIn('cut', r['results'][0])   # a file: the waves are the browser's
        self.assertEqual(self.call('view_get', page=self.page)['gaps'], {'idle': 8, 'keep': 2, 'view': True, 'signals': ['PSEL']})
        self.assertNotIn('gaps', self.call('view_edit', page=self.page, ops=[{'op': 'gaps', 'on': False}]) and self.call('view_get', page=self.page))
        out = W.ns_out([{'op': 'gaps', 'cut': {'gaps': 1, 'kept': 5000, 'total': 20000, 'parts': [[0, 2000], [17000, 20000]]}}], True)
        self.assertEqual(out[0]['cut'], {'gaps': 1, 'kept': 5, 'total': 20, 'parts': [[0, 2], [17, 20]]})
        self.assertEqual(W.ns_out([{'op': 'gaps', 'cut': {'kept': 5}}], False)[0]['cut'], {'kept': 5})   # cycles

    def test_times_in_ns(self):
        """Every time a command answers is in ns: the ones the agent's text promises and an answer could miss."""
        out = W.ns_out([{'op': 'bookmark', 'n': 1, 't': 85000, 'from': 40000, 'top': None}, {'op': 'fsm_go', 'signal': 's', 't': 7000},
                        {'op': 'compare', 'differ': 2, 'first': 115000},
                        {'op': 'fsm_stats', 'states': [{'state': 'A', 'entries': 2, 'first': 1000, 'time': 3000, 'share': 0.5}],
                         'invalid': [], 'changes': [{'from': 'A', 'to': 'B', 'count': 1, 'first': 2000}]}], True)
        self.assertEqual((out[0]['t'], out[0]['from'], out[0]['n'], out[1]['t'], out[2]['first'], out[2]['differ']), (85, 40, 1, 7, 115, 2))
        self.assertEqual(out[3]['states'], [{'state': 'A', 'entries': 2, 'first': 1, 'time': 3, 'share': 0.5}])
        self.assertEqual(out[3]['changes'], [{'from': 'A', 'to': 'B', 'count': 1, 'first': 2}])

    def test_rows_pages(self):
        """view_get rows goes on from its next_offset."""
        a = self.call('view_get', page=self.page, rows='', limit=2)['rows']
        b = self.call('view_get', page=self.page, rows='', limit=2, offset=a['next_offset'])['rows']
        self.assertEqual((len(a['rows']), a['next_offset'], len(b['rows']), a['total']), (2, 2, 1, 3))
        self.assertNotIn('next_offset', b)

    def fake_page(self, b, path, cid='abcd1234', answer=True):
        """A page as a browser has it: the stream of commands, its hello, an answer (the ops echoed) to each command."""
        import threading, urllib.request
        base, q = f'http://127.0.0.1:{b.port}', f'token={b.token}&cid={cid}'
        stream = urllib.request.urlopen(f'{base}/events?{q}', timeout=10)
        post = lambda where, body: urllib.request.urlopen(urllib.request.Request(f'{base}/{where}?{q}', data=json.dumps(body).encode()), timeout=5).read()
        post('hello', {'path': path, 'title': 't', 'views': [{'key': 'one', 'timed': True}]})
        def run():
            for line in stream:
                if line.startswith(b'data: ') and answer:
                    m = json.loads(line[6:])
                    post('reply', {'rid': m['rid'], 'results': [dict(o, seen=True) for o in m['ops']]})
        threading.Thread(target=run, daemon=True).start()
        return post

    def test_rotate(self):   # review 0.31 M9, T13: a copy of a page with the old key no longer connects
        import urllib.error, urllib.request
        b = W.Bridge(port=0, token='t' * 20)
        W.BRIDGE.append(b)
        old = b.token
        self.call('view_live', rotate=True)
        self.assertNotEqual(b.token, old)
        with open(os.path.join(CACHE.name, 'wavelens', 'live-token'), encoding='utf-8') as f:
            self.assertEqual(f.read().strip(), b.token)
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f'http://127.0.0.1:{b.port}/events?token={old}&cid=abcd', timeout=5)
        self.assertEqual(e.exception.code, 403)

    def test_headers(self):   # review 0.31 M11, T13: the answer readable by an Origin of this link only, no banner, a verb it has not: JSON
        import http.client
        b = W.Bridge(port=0, token='t' * 20)
        W.BRIDGE.append(b)
        def req(method, origin=None):
            c = http.client.HTTPConnection('127.0.0.1', b.port, timeout=5)
            c.request(method, '/', headers={'Origin': origin} if origin else {})
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, r.getheader('Access-Control-Allow-Origin'), r.getheader('Server'), body
        self.assertEqual(req('GET', 'null')[:2], (200, 'null'))
        self.assertEqual(req('GET', 'http://localhost:9000')[1], 'http://localhost:9000')
        self.assertIsNone(req('GET', 'https://evil.example')[1])
        self.assertEqual(req('OPTIONS', 'https://evil.example')[0], 403)
        self.assertEqual(req('OPTIONS', 'null')[:2], (204, 'null'))
        self.assertEqual(req('PUT')[0], 405)
        self.assertIn(b'GET or POST', req('DELETE')[3])
        self.assertNotIn('Python', req('GET')[2])

    def test_save_writes_the_file_named(self):   # review 0.31 M10, T13: a page does not choose the file that is written
        b = W.Bridge(port=0, token='t' * 20)
        W.BRIDGE.append(b)
        other = os.path.join(self.d.name, 'other.html')
        shutil.copy(self.page, other)
        self.fake_page(b, other)   # this page says it is other.html
        before = H.text(self.page)
        c = b.pages()[0]
        r = W.live_edit({'page': self.page, 'save': True, 'ops': [{'op': 'marker', 't': 5}]}, dict(c), {'key': 'one', 'timed': True})
        self.assertIsNone(r['saved'])
        self.assertIn('is not this page', r['note'])
        self.assertEqual(H.text(self.page), before)
        r = W.live_edit({'save': True, 'ops': [{'op': 'marker', 't': 6}]}, dict(c), {'key': 'one', 'timed': True})
        self.assertIn('give "page"', r['note'])

    def test_live(self):
        import urllib.error, urllib.request
        b = W.Bridge(port=0, token='t' * 20)
        W.BRIDGE.append(b)
        post = self.fake_page(b, self.page)
        r = self.call('view_edit', page=self.page, ops=[{'op': 'cursor', 't': 30}, {'op': 'arrow', 'from': 1, 'to': 2}])
        self.assertEqual(r['results'], [{'op': 'cursor', 't': '30ns', 'seen': True}, {'op': 'arrow', 'from': 1, 'to': 2, 'seen': True}])   # ns as text
        self.assertEqual(r['live'], self.page)
        self.assertEqual(self.call('view_live')['pages'], [{'page': self.page, 'title': 't', 'views': ['one']}])
        for url, hdr in ((f'http://127.0.0.1:{b.port}/events?token=wrong&cid=abcd', {}),
                         (f'http://127.0.0.1:{b.port}/events?token={b.token}&cid=abcd', {'Origin': 'https://evil.example'})):
            with self.assertRaises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=5)
            self.assertEqual(e.exception.code, 403)
        post('bye', {})   # the page leaves: the file again
        self.assertEqual(self.call('view_live')['pages'], [])
        r = self.call('view_edit', page=self.page, ops=[{'op': 'marker', 't': 5}])
        self.assertEqual((r['page'], r['results']), (self.page, [{'op': 'marker', 'id': 1}]))

    def test_live_gone(self):
        b = W.Bridge(port=0, token='t' * 20)
        W.BRIDGE.append(b)
        self.fake_page(b, self.page, answer=False)
        with self.assertRaisesRegex(W.LiveGone, 'did not answer in 0.3 s'):
            b.send('abcd1234', 'one', [{'op': 'state'}], timeout=0.3)
        self.assertEqual(b.pages(), [])   # taken for gone

    def test_state_times_both_ways(self):
        """M5: a state the agent read (view_get full: ns) and gives back (set_state) is in ns too: the same times again."""
        page = os.path.join(self.d.name, 'times.html')
        shutil.copy(self.page, page)
        r = self.call('view_edit', page=page, ops=[{'op': 'set_state', 'state': {
            'wavelens': 'state', 'cursor': 30, 'cursor2': '0.04us', 'from': 10, 'to': 70, 'range': {'from': 20, 'to': 50, 'signal': None},
            'bookmarks': [{'n': 1, 't': 25}], 'markers': [{'t': 35, 'label': 'm'}], 'config': {'cycleZero': 5}}}])
        self.assertNotIn('errors', r)
        self.assertEqual(E.Page(page).state('one')['cursor'], 30000)   # the viewer's ps in the page
        g = self.call('view_get', page=page, full=True)
        self.assertEqual((g['cursor'], g['cursor2'], g['from'], g['to'], g['range'], g['bookmarks'], g['markers'], g['config']['cycleZero']),
                         (30, 40, 10, 70, {'from': 20, 'to': 50, 'signal': None}, [{'n': 1, 't': 25}], [{'t': 35, 'label': 'm'}], 5))
        st = {k: v for k, v in g.items() if k not in ('page', 'view', 'views', 'edits')}
        again = self.call('view_edit', page=page, ops=[{'op': 'set_state', 'state': dict(st, wavelens='state')}])
        self.assertEqual(again['note'], 'nothing changed')   # given back as read: the same state

    def test_no_replay_after_ack(self):
        """A11: the page answered the edit, the state for "save" did not come: applied live, not saved, the file as it was."""
        class Late:
            def __init__(self):
                self.calls = 0

            def send(self, cid, view, ops):
                self.calls += 1
                if self.calls == 1:
                    return [{'op': 'bookmark', 'n': 2}]
                raise W.LiveGone('the live page did not answer in 10 s')
        before = E.Page(self.page).text
        W.BRIDGE[:] = [Late()]
        r = W.live_edit({'page': self.page, 'view': 'one', 'save': True, 'ops': [{'op': 'bookmark', 'n': 2, 't': 2}]},
                        {'cid': 'demo', 'path': self.page}, {'key': 'one', 'timed': True})
        W.BRIDGE.clear()
        self.assertEqual((r['results'], r['saved']), ([{'op': 'bookmark', 'n': 2}], None))
        self.assertIn('applied live, not saved', r['note'])
        self.assertEqual(E.Page(self.page).text, before)

    def test_bridge_guards(self):
        """M8: the Host must be this server; an answer counts for the command sent to that page only; a body that is not one
        JSON object, or of a wrong length, is refused; the link goes on."""
        import http.client
        b = W.Bridge(port=0, token='t' * 20)
        W.BRIDGE.append(b)
        self.fake_page(b, self.page, cid='page1aaa', answer=False)
        def req(path, body=b'{}', host=None, length=None):
            c = http.client.HTTPConnection('127.0.0.1', b.port, timeout=5)
            c.putrequest('POST' if body is not None else 'GET', path, skip_host=True)
            c.putheader('Host', host or f'127.0.0.1:{b.port}')
            if body is not None:
                c.putheader('Content-Length', str(len(body) if length is None else length))
            c.endheaders(body if body is not None and length is None else None)
            r = c.getresponse()
            r.read()
            c.close()
            return r.status
        q = f'token={b.token}&cid=other111'
        self.assertEqual(req('/', None, host=f'evil.example:{b.port}'), 403)
        self.assertEqual(req(f'/hello?{q}', host=f'evil.example:{b.port}'), 403)   # DNS rebinding: a name of another site
        self.assertEqual(req(f'/hello?{q}', b'[1, 2]'), 400)
        self.assertEqual(req(f'/reply?{q}', b'"x"'), 400)
        self.assertEqual(req(f'/reply?{q}', b'{"rid": 1}', length=-5), 400)
        self.assertEqual(req(f'/reply?token={b.token}&cid=BAD!'), 403)
        got = {}
        t = threading.Thread(target=lambda: got.update(r=b.send('page1aaa', 'one', [{'op': 'state'}], timeout=5)))
        t.start()
        H.until(lambda: b.pending, 5, 'the bridge holds the request')
        rid = next(iter(b.pending))
        self.assertEqual(req(f'/reply?{q}', json.dumps({'rid': rid, 'results': [{'op': 'state', 'state': {'forged': 1}}]}).encode()), 409)
        self.assertEqual(req(f'/reply?token={b.token}&cid=page1aaa', json.dumps({'rid': rid, 'results': [{'op': 'state', 'state': {}}]}).encode()), 200)
        t.join(5)
        self.assertFalse(t.is_alive(), 'the send returns once the page replied')
        self.assertEqual(got['r'], [{'op': 'state', 'state': {}}])
        self.assertEqual(req(f'/reply?token={b.token}&cid=page1aaa', json.dumps({'rid': rid, 'results': []}).encode()), 409)   # once
        self.assertEqual(req('/', None), 200)

    def test_paths(self):
        self.assertTrue(W.same_file('/mnt/c/Users/x/p.html', '/C:/Users/x/p.html'))
        self.assertTrue(W.same_file('/mnt/c/Users/x/p.html', 'C:\\Users\\x\\p.html'))
        self.assertTrue(W.same_file('/tmp/a b.html', '/tmp/a%20b.html'))
        self.assertFalse(W.same_file('/tmp/a.html', '/tmp/b.html'))
        self.assertFalse(W.same_file('/home/x/A.vcd', '/home/x/a.vcd'))   # Linux tells the case apart, a Windows drive does not
        self.assertTrue(W.same_file('/mnt/c/Users/X/a.vcd', '/mnt/c/users/x/A.vcd'))

    def test_dump_in_vscode(self):
        """A dump's tab in VS Code (vscode/): the bridge's note for the extension, view_live with open asks it to open
        the dump, view_edit works on the tab live and never on the dump's file."""
        dump = H.fixture('enum')
        b = W.Bridge(port=0, token='t' * 20)
        W.BRIDGE.append(b)
        live = os.path.join(CACHE.name, 'wavelens', 'live')
        with open(os.path.join(live, f'{b.port}.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['pid'], os.getpid())
        r = self.call('view_live', page=dump, open=True, wait=0)
        self.assertTrue(r['opened'])
        self.assertIn('not connected', r['note'])
        asks = [x for x in os.listdir(live) if x.startswith('open-')]
        with open(os.path.join(live, asks[0]), encoding='utf-8') as f:
            ask = json.load(f)
        self.assertEqual((ask['path'], ask['port']), (dump, b.port))
        post = self.fake_page(b, dump)
        r = self.call('view_edit', page=dump, ops=[{'op': 'marker', 't': 5}])
        self.assertEqual((r['live'], r['results']), (dump, [{'op': 'marker', 't': '5ns', 'seen': True}]))
        text, err = W.call('view_edit', {'page': dump, 'save': True, 'ops': [{'op': 'marker', 't': 6}]})
        self.assertTrue(err)
        self.assertIn('no page file', text)   # refused before the edit is done
        post('bye', {})
        t0 = time.monotonic()
        text, err = W.call('view_edit', {'page': dump, 'ops': [{'op': 'marker', 't': 5}]})
        self.assertLess(time.monotonic() - t0, 1, 'a dump not open in VS Code: waited for once (review 0.31 M4)')
        self.assertTrue(err)
        self.assertIn('not open in VS Code', text)
        b.close()
        self.assertFalse(os.path.exists(os.path.join(live, f'{b.port}.json')))


class Review(unittest.TestCase):
    """The findings of the review of 2026-10-22 on the dump tools (M3, A6, A7/B11, B15)."""

    @classmethod
    def setUpClass(cls):
        cls.d = H.tmp()
        # 1 fs steps: a clock every 2 fs, d and a 4-bit bus that changes (sometimes to the value it had) at known times
        body, bus = ['#0', '0!', '0"', 'b0000 #'], {3: '0001', 7: '0011', 8: '0011', 11: '0111', 15: '0100', 19: '0100', 22: '1100', 27: '0000'}
        d = {4: '1', 9: '0', 13: '1', 21: '0', 30: '1', 31: '1'}
        for t in range(1, 41):
            body.append(f'#{t}')
            body.append(f'{t % 2}!')
            if t in d:
                body.append(f'{d[t]}"')
            if t in bus:
                body.append(f'b{bus[t]} #')
        cls.fs = H.vcd(cls.d.name, '\n'.join(body) + '\n', header='$timescale 1fs $end\n$scope module tb $end\n$var wire 1 ! clk $end\n'
                       '$var wire 1 " d $end\n$var wire 4 # bus [3:0] $end\n$upscope $end\n$enddefinitions $end\n', name='fs.vcd')

    @classmethod
    def tearDownClass(cls):
        cls.d.cleanup()

    def call(self, tool, **a):
        text, err = W.call(tool, a)
        self.assertFalse(err, text)
        return json.loads(text)

    def test_bit_select(self):
        """M3: a select of a bus changes when its bits do: edges, changes, stats of the select; one outside the bus said."""
        p = H.vcd(self.d.name, '#0\nb000 !\n#1\nb001 !\n#2\nb010 !\n#3\nb011 !\n#4\nb000 !\n#5\n',
                  header='$timescale 1ns $end\n$scope module tb $end\n$var wire 3 ! data [2:0] $end\n$upscope $end\n$enddefinitions $end\n', name='sel.vcd')
        self.assertEqual(self.call('wave_find', dump=p, signal='data[1]', edge='change')['times'], [2, 4])
        self.assertEqual(self.call('wave_find', dump=p, signal='data[1]', edge='rise')['times'], [2])
        self.assertEqual(self.call('wave_changes', dump=p, signals=['data[1]'])['signals']['data[1]']['changes'], [[2, '1'], [4, '0']])
        s = self.call('wave_stats', dump=p, signals=['data[1]'])['signals']['data[1]']
        self.assertEqual((s['changes'], s['rises'], s['falls']), (2, 1, 1))
        self.assertEqual(self.call('wave_changes', dump=p, signals=['data[2:1]'])['signals']['data[2:1]']['count'], 2)
        for bad in ('data[3]', 'data[40:33]', 'data[0:1]'):
            text, err = W.call('wave_values', {'dump': p, 'signals': [bad], 'at': 1})
            self.assertTrue(err)
            self.assertIn('has bits [2:0]', text)

    def test_stats_extrema_by_the_radix(self):
        """review IV B21: min / max are the numbers the radix reads (signed: 80 is -128, 7f is 127; float: by value)."""
        p = H.vcd(self.d.name, '#0\nb10000000 !\nb00111111100000000000000000000000 "\n#1\nb01111111 !\n'
                  'b10111111100000000000000000000000 "\n#2\nb00000001 !\n#3\n',
                  header='$timescale 1ns $end\n$scope module tb $end\n$var wire 8 ! b [7:0] $end\n$var wire 32 " f [31:0] $end\n$upscope $end\n'
                  '$enddefinitions $end\n', name='ext.vcd')
        s = self.call('wave_stats', dump=p, signals=['b'], radix='signed')['signals']['b']
        self.assertEqual((s['min'], s['max']), ('-128', '127'))
        s = self.call('wave_stats', dump=p, signals=['b'], radix='dec')['signals']['b']
        self.assertEqual((s['min'], s['max']), ('1', '128'))
        s = self.call('wave_stats', dump=p, signals=['f'], radix='float')['signals']['f']
        self.assertEqual((s['min'], s['max']), ('-1', '1'))

    def test_clock_domains(self):
        """A6: two clocks whose edges are alike in count, first and last are two clocks; one net under two scopes is one."""
        clocks = os.path.join(self.d.name, 'clocks.vcd')
        H.vcd(self.d.name, '#0\n0!\n0"\n#1\n1!\n1"\n#2\n0!\n0"\n#3\n1!\n#4\n0!\n1"\n#5\n0"\n#6\n1!\n1"\n#7\n0!\n0"\n#10\n',
              header='$timescale 1ns $end\n$scope module tb $end\n$scope module a $end\n$var wire 1 ! clk $end\n$upscope $end\n'
              '$scope module b $end\n$var wire 1 " clk $end\n$upscope $end\n$scope module c $end\n$var wire 1 ! clk $end\n$upscope $end\n'
              '$upscope $end\n$enddefinitions $end\n', name='clocks.vcd')
        self.assertEqual([c['name'] for c in self.call('wave_info', dump=clocks)['clocks']], ['tb.a.clk', 'tb.b.clk'])

    def pages(self, tool, key, **a):
        """Every page of an answer, each from the "next_from" / "next_offset" of the one before."""
        out, more = [], {}
        for _ in range(1000):   # (a page that names itself as the next: not for ever)
            r = self.call(tool, dump=self.fs, **a, **more)
            if tool == 'wave_changes':
                e = r['signals'][a['signals'][0]]
                out += e['changes']
                if 'next_from' not in e:
                    return out
                more = {'from': e['next_from']}
            else:
                out += r[key]
                if tool == 'wave_signals':
                    if 'next_offset' not in r:
                        return out
                    more = {'offset': r['next_offset']}
                elif 'next_from' not in r:
                    return out
                else:
                    more = {'from': r['next_from']}
            self.assertLess(len(out), 1000)
        self.fail(f'{tool}: more than 1000 pages')

    def test_pages(self):
        """A7/B11: the pages of an answer (limit 1, 2, 3, all) put together are the answer without a limit."""
        with H.stderr():   # dumpscan's word on the fs timescale
            self.pages_of_each()

    def pages_of_each(self):
        for sig in ('tb.d', 'tb.bus'):
            whole = self.call('wave_changes', dump=self.fs, signals=[sig])['signals'][sig]['changes']
            self.assertEqual(len(whole), 5 if sig == 'tb.d' else 6)   # the bus written with its value again: no change
            for n in (1, 2, 3):
                self.assertEqual(self.pages('wave_changes', None, signals=[sig], limit=n), whole, (sig, n))
        for only in (True, False):
            whole = self.call('wave_sample', dump=self.fs, signals=['tb.d', 'tb.bus'], clock='tb.clk', only_changes=only, limit=1000)['rows']
            for n in (1, 2, 3):
                got = self.pages('wave_sample', 'rows', signals=['tb.d', 'tb.bus'], clock='tb.clk', only_changes=only, limit=n)
                self.assertEqual(got, whole, (only, n))
        whole = self.call('wave_signals', dump=self.fs)['signals']
        for n in (1, 2):
            self.assertEqual(self.pages('wave_signals', 'signals', limit=n), whole)

    def test_times(self):
        """B15: the times the viewer reads, read here too."""
        for text, ps in (('100NS', 1e5), ('1E2', 1e5), ('0.1µs', 1e5), ('2 us', 2e6), ('5', 5000), ('3fs', 3e-3), ('-5ns', -5000)):
            self.assertAlmostEqual(W.ps_of(text), ps)
        for bad in ('1e999', 'nan', '5 parsecs', [1], {'t': 1}, True, float('inf')):
            with self.assertRaises(W.WaveError):
                W.ps_of(bad)


class Tests(unittest.TestCase):
    """wave_tests and wave_page over the marks of a cocotb run."""
    DOC = {'wavelens': 'marks', 'version': 1, 'signal': 'TEST_CASE', 'tests': [
        {'n': 1, 'name': 'a', 'doc': 'first', 'text': 'first\n\nthe rest', 'signals': ['*fifo_full'], 'passed': 189, 'failed': 0,
         'from': 0, 'to': 100000, 'result': 'pass', 'message': '', 'where': '', 'dropped': 0, 'phases': [],
         'marks': [{'t': 50000, 'kind': 'check', 'ok': True, 'got': '5', 'expected': '5', 'text': 'five', 'signal': 'PSEL',
                    'got_all': '[5, 5]', 'expected_all': '[5, 6]', 'at': 'at [1]: 5, 6'}]},
        {'n': 2, 'name': 'b', 'doc': '', 'from': 100001, 'to': 300000, 'result': 'fail', 'message': 'got 0, expected 1', 'where': 't.py:9', 'dropped': 0,
         'phases': [{'label': 'p', 'from': 100001, 'to': 200000}],
         'marks': [{'t': 300000, 'kind': 'check', 'ok': False, 'got': '0', 'expected': '1', 'text': '', 'signal': 'PSEL'}, {'t': 150000, 'kind': 'note', 'text': 'n'}]}]}

    def setUp(self):
        d = H.tmp()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.marks, self.vcd = os.path.join(d.name, 'x.marks.json'), os.path.join(d.name, 'x.vcd')
        with open(self.marks, 'w', encoding='utf-8') as f:
            json.dump(self.DOC, f)
        with open(self.vcd, 'w', encoding='utf-8') as f:
            f.write('$timescale 1ps $end\n$scope module tb $end\n$var wire 8 ! TEST_CASE [7:0] $end\n$var wire 1 " PSEL $end\n$upscope $end\n'
                    '$enddefinitions $end\n#0\nb1 !\n0"\n#50000\n1"\n#100001\nb10 !\n#300000\n0"\n')

    def call(self, tool, **a):
        text, err = W.call(tool, a)
        self.assertFalse(err, text)
        return json.loads(text)

    def test_measures_and_steps(self):
        """Stage 17: a test's measures (ns, ok), the run's measures_failed and slowest steps; a test's steps by length, steps: true alone."""
        doc = json.loads(json.dumps(self.DOC))
        doc['tests'][0]['measures'] = [{'label': 'r', 'from': 10000, 'to': 40000, 'max': '20ns', 'ok': False}, {'label': 'c', 'from': 50000, 'to': 60000, 'max': '3 cycles'}]
        doc['tests'][1]['phases'].append({'label': 'q', 'from': 200000, 'to': 290000})
        with open(self.marks, 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        r = self.call('wave_tests', marks=self.marks)
        self.assertEqual((r['measures'], r['measures_failed']), (2, 1))
        self.assertIn('2 measures, 1 out of bounds', r['summary'])
        self.assertEqual(r['tests'][0]['measures'], [{'label': 'r', 'from': 10, 'to': 40, 'dt': 30, 'max': '20ns', 'ok': False},
                                                     {'label': 'c', 'from': 50, 'to': 60, 'dt': 10, 'max': '3 cycles', 'ok': None}])
        self.assertNotIn('measures', r['tests'][1])
        self.assertEqual([(x['test'], x['step'], x['dt']) for x in r['slowest']], [('b', 'p', 99.999), ('b', 'q', 90)])
        t = self.call('wave_tests', marks=self.marks, test='b', steps=True)['test']
        self.assertEqual(([p['step'] for p in t['steps']], t['total'], t['longest'], set(t)), (['p', 'q'], 189.999, 'p', {'n', 'name', 'steps', 'total', 'longest'}))

    def test_a_regression_of_a_directory(self):
        """P-19: wave_tests of a directory: every marks file under it, the totals, the failures first, the failed files first."""
        good = {**self.DOC, 'tests': [self.DOC['tests'][0]]}
        for sub, doc in (('a_bench', good), ('z_bench', self.DOC), ('m_bench/deep', good)):
            os.makedirs(os.path.join(self.dir, 'reg', sub))
            with open(os.path.join(self.dir, 'reg', sub, 'wavelens.marks.json'), 'w', encoding='utf-8') as f:
                json.dump(doc, f)
        with open(os.path.join(self.dir, 'reg', 'other.json'), 'w', encoding='utf-8') as f:
            json.dump({'not': 'marks'}, f)
        with open(os.path.join(self.dir, 'reg', 'old.marks.json'), 'w', encoding='utf-8') as f:
            json.dump({**self.DOC, 'version': 9}, f)
        # B-14: a marks file is one by what it holds: "wavelens" last (sorted keys) is one; a cut one, an empty one are named as skipped
        os.makedirs(os.path.join(self.dir, 'reg', 's_bench'))
        with open(os.path.join(self.dir, 'reg', 's_bench', 'run.json'), 'w', encoding='utf-8') as f:
            json.dump({**good, 'zz': 'x' * 300}, f, sort_keys=True)
        with open(os.path.join(self.dir, 'reg', 'cut.json'), 'w', encoding='utf-8') as f:
            f.write(json.dumps(good)[:150])
        open(os.path.join(self.dir, 'reg', 'empty.json'), 'w', encoding='utf-8').close()
        r = self.call('wave_tests', marks=os.path.join(self.dir, 'reg'))
        self.assertEqual(r['summary'], '4 files, 5 tests: 4 passed, 1 failed')
        self.assertEqual(r['totals'], {'tests': 5, 'pass': 4, 'fail': 1, 'xfail': 0, 'run': 0, 'checks': 189 * 4 + 1, 'failed_checks': 1})
        self.assertEqual(r['failures'], [{'file': os.path.join('z_bench', 'wavelens.marks.json'), 'n': 2, 'name': 'b', 'result': 'fail', 'from': 100.001,
                                          'message': 'got 0, expected 1', 'where': 't.py:9'}])
        self.assertEqual([(x['file'].split(os.sep)[0], x['failed']) for x in r['runs']], [('z_bench', 1), ('a_bench', 0), ('m_bench', 0), ('s_bench', 0)])
        self.assertEqual(r['notes'][:2], ['skipped, not JSON: cut.json, empty.json', 'skipped, no marks file: other.json'])
        self.assertEqual(len(r['notes']), 3)
        self.assertIn('version 9', r['notes'][2])
        self.assertEqual(len(self.call('wave_tests', marks=os.path.join(self.dir, 'reg'), limit=0)['failures']), 1, 'limit 0: the default, not none')
        text, err = W.call('wave_tests', {'marks': os.path.join(self.dir, 'reg'), 'test': 'b'})
        self.assertTrue(err)
        self.assertIn('directory', text)
        os.makedirs(os.path.join(self.dir, 'empty'))
        text, err = W.call('wave_tests', {'marks': os.path.join(self.dir, 'empty')})
        self.assertTrue(err)
        self.assertIn('no marks file', text)

    def test_marks_with_a_bom(self):
        """Review 2026-11-05 (runs) B-27: a marks file saved again by a Windows editor (a BOM before it) is one, of a directory and alone."""
        os.makedirs(os.path.join(self.dir, 'bom'))
        bom = os.path.join(self.dir, 'bom', 'bom.json')
        with open(bom, 'w', encoding='utf-8-sig') as f:
            json.dump(self.DOC, f)
        r = self.call('wave_tests', marks=os.path.join(self.dir, 'bom'))
        self.assertEqual((r['files'], r.get('notes')), (1, None), r)
        self.assertEqual(self.call('wave_tests', marks=bom)['summary'], self.call('wave_tests', marks=self.marks)['summary'])

    def test_the_tests_of_a_run(self):
        r = self.call('wave_tests', marks=self.marks)
        self.assertEqual(r['summary'], '2 tests: 1 passed, 1 failed')
        a, b = r['tests']
        self.assertEqual((a['name'], a['result'], a['from'], a['to'], a['checks'], a['failed_checks'], a['doc']), ('a', 'pass', 0, 100, 189, 0, 'first'))
        self.assertEqual((a['checks'], b['checks']), (189, 1), 'the counts of the run, in a loop with no bookmark too')
        self.assertEqual((b['from'], b['to'], b['failed_checks'], b['message'], b['where']), (100.001, 300, 1, 'got 0, expected 1', 't.py:9'))
        self.assertNotIn('marks', a, 'the list is short')
        self.assertNotIn('text', a)
        self.assertNotIn('signals', a)

    def test_one_test(self):
        for key in (2, '2', 'b'):
            t = self.call('wave_tests', marks=self.marks, test=key)['test']
            self.assertEqual(t['name'], 'b')
        self.assertEqual((t['marks'][0]['t'], t['marks'][0]['got'], t['marks'][0]['expected']), (300, '0', '1'))
        self.assertEqual((t['phases'][0]['from'], t['phases'][0]['to']), (100.001, 200))
        t = self.call('wave_tests', marks=self.marks, test='b', limit=1)['test']
        self.assertEqual((len(t['marks']), t['more']), (1, 1))

    def test_one_test_says_all_it_left(self):
        t = self.call('wave_tests', marks=self.marks, test='a')['test']
        self.assertEqual((t['doc'], t['text'], t['signals']), ('first', 'first\n\nthe rest', ['*fifo_full']))
        m = t['marks'][0]
        self.assertEqual((m['got'], m['got_all'], m['expected_all'], m['at']), ('5', '[5, 5]', '[5, 6]', 'at [1]: 5, 6'))

    def test_errors(self):
        text, err = W.call('wave_tests', {'marks': self.marks, 'test': 'nope'})
        self.assertTrue(err)
        self.assertIn('have: a, b', text)
        text, err = W.call('wave_tests', {'marks': self.marks + '.no'})
        self.assertTrue(err)
        self.assertIn('no such file', text)
        with open(self.marks, 'w', encoding='utf-8') as f:
            f.write('{}')
        self.assertIn('not a marks file', W.call('wave_tests', {'marks': self.marks})[0])

    def page(self, **a):
        out = os.path.join(self.dir, 'x.html')
        r = self.call('wave_page', dump=self.vcd, signals=['TEST_CASE', 'PSEL'], marks=self.marks, out=out, **a)
        with open(out, encoding='utf-8') as f:
            return r, f.read()

    def test_a_page_with_the_marks(self):
        r, text = self.page()
        self.assertEqual(r['summary'], '2 tests: 1 passed, 1 failed')
        self.assertNotIn('notes', r, 'the marks found their rows')
        self.assertIn('TC2 b · FAIL', text)
        self.assertNotIn('<nav class="tests">', text)
        doc = json.loads(text[text.index('window.WAVES = ') + 15:text.index('};\n</script>', text.index('window.WAVES = ')) + 1])
        rows = {x['name']: x for x in doc['view']['signal']}
        self.assertEqual(rows['TEST_CASE']['enum'], {'1': 'a', '2': 'b'})
        self.assertEqual(sorted({b.get('signal') for b in doc['view']['bookmarks']}), ['PSEL', 'TEST_CASE'], 'on the rows, by the names they have')
        self.assertEqual([m['label'] for m in doc['view']['markers']], ['TC1', 'TC2'])

    def test_each_test_apart(self):
        _, text = self.page(marks_views='tests')
        self.assertIn('<nav class="tests">', text)
        self.assertEqual(text.count('<section data-view='), 2)

    def test_not_with_what_a_page_of_marks_has_not(self):
        out = os.path.join(self.dir, 'x.html')
        text, err = W.call('wave_page', {'dump': self.vcd, 'signals': ['PSEL'], 'marks': self.marks, 'out': out, 'compare': self.vcd})
        self.assertTrue(err)
        self.assertIn('"compare" does not go with "marks"', text)
        text, err = W.call('wave_page', {'dump': self.vcd, 'signals': ['PSEL'], 'marks': self.marks, 'out': out + '.json'})
        self.assertTrue(err)
        self.assertIn('makes a page', text)


class Protocol(unittest.TestCase):
    def talk(self, *msgs):
        out = io.StringIO()
        W.serve(io.StringIO(''.join((m if isinstance(m, str) else json.dumps(m)) + '\n' for m in msgs)), out)
        return [json.loads(l) for l in out.getvalue().splitlines()]

    def test_session(self):
        r = self.talk({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}},
                      {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                      {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                      {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'wave_info', 'arguments': {'dump': H.fixture('short')}}},
                      {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'nope', 'arguments': {}}},
                      'not json', {'jsonrpc': '2.0', 'id': 5, 'method': 'resources/list'}, {'jsonrpc': '2.0', 'id': 6, 'method': 'ping'})
        self.assertEqual([m.get('id') for m in r], [1, 2, 3, 4, None, 5, 6])   # no answer to the notification
        self.assertEqual(r[0]['result']['protocolVersion'], '2025-03-26')
        self.assertEqual(r[0]['result']['serverInfo']['name'], 'wavelens')
        names = [t['name'] for t in r[1]['result']['tools']]
        self.assertEqual(names[0], 'wave_info')
        self.assertTrue(all('fn' not in t and t['inputSchema']['type'] == 'object' for t in r[1]['result']['tools']))
        # codex exec calls a tool without approval only when it says it reads: every tool but the ones that write a file
        self.assertEqual([t['name'] for t in r[1]['result']['tools'] if not t['annotations']['readOnlyHint']],
                         ['wave_explain', 'wave_page', 'wave_to_fst', 'wave_runs', 'wave_cut', 'view_edit', 'view_live'])
        arrays = [(t['name'], k) for t in r[1]['result']['tools'] for k, v in t['inputSchema']['properties'].items()
                  if 'array' in str(v.get('type')) and 'items' not in v]
        self.assertEqual(arrays, [])   # an array without items is refused by OpenAI's function schemas
        self.assertFalse(r[2]['result']['isError'])
        self.assertIn('"unit":"ns"', r[2]['result']['content'][0]['text'])
        self.assertTrue(r[3]['result']['isError'])
        self.assertEqual((r[4]['error']['code'], r[5]['error']['code']), (-32700, -32601))
        self.assertEqual(r[6]['result'], {})

    def test_malformed(self):
        """M1, M2: a request of a wrong shape, arguments of a wrong kind, a tool that fails as nobody foresaw: each gets an
        answer (an error of JSON-RPC or of the tool), and the session goes on (the ping at the end is answered)."""
        short = H.fixture('short')
        call = lambda i, name, args: {'jsonrpc': '2.0', 'id': i, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}
        with H.tmp() as d:
            table = [   # (request, JSON-RPC error code or (isError, a piece of the text))
                (call(1, 'wave_info', 'x'), -32602),
                ({'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': [1]}, -32602),
                (call(3, 'sva_check', {'dump': short, 'defines': ['X=1'], 'source': 'a: assert property (@(posedge b[0]) 1);',
                                       'sva_bin': '/nonexistent/sva'}), (True, 'no sva binary')),
                (call(4, 'sva_check', {'dump': short, 'defines': 5}), (True, '"defines": an object/array of string, not 5')),
                (call(5, 'wave_signals', {'dump': short, 'scope': 5}), (True, '"scope": a string, not 5')),
                (call(6, 'wave_values', {'dump': short, 'signals': ['b'], 'at': '1e999'}), (True, 'bad time "1e999"')),
                ('{"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "wave_values", "arguments": '
                 f'{{"dump": {json.dumps(short)}, "signals": ["b"], "at": 1e999}}}}}}', (True, '"at": a number/string/array')),
                ('{"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "wave_values", "arguments": '
                 f'{{"dump": {json.dumps(short)}, "signals": ["b"], "at": NaN}}}}}}', (True, '"at": a number/string/array')),
                (call(9, 'wave_page', {'dump': short, 'signals': ['b'], 'from': -5, 'out': os.path.join(d, 'w.json')}), (False, '"wavejson"')),
                (call(10, 'wave_signals', {'dump': short, 'limit': 2.0}), (False, '"total"')),
                (call(11, 'wave_signals', {'dump': short, 'limit': 'many'}), (True, '"limit": an integer')),
                (call(12, 5, {}), -32602),
                ({'jsonrpc': '2.0', 'id': {'a': 1}, 'method': 'ping'}, -32600),
                ({'jsonrpc': '2.0', 'id': 14, 'method': 5}, -32600),
                ({'jsonrpc': '2.0', 'id': 15, 'method': 'tools/list', 'params': 'x'}, -32602),
                ([], -32600),
                ('[' * 100000, -32700),
                (call(18, 'boom', {}), (True, 'ZeroDivisionError')),
                (call(19, 'quit', {}), (True, 'quit stopped (3)')),
                (call(20, 'view_live', {'wait': 'x'}), (False, '"link"')),
            ]
            tools = dict(W.BY_NAME)
            W.BY_NAME['boom'] = dict(W.BY_NAME['wave_info'], fn=lambda a: 1 / 0)
            W.BY_NAME['quit'] = dict(W.BY_NAME['wave_info'], fn=lambda a: sys.exit(3))
            try:
                with H.stderr():
                    r = self.talk(*[m for m, _ in table], {'jsonrpc': '2.0', 'id': 99, 'method': 'ping'})
            finally:
                W.BY_NAME.clear()
                W.BY_NAME.update(tools)
                for b in W.BRIDGE:
                    b.close()
                W.BRIDGE.clear()
        self.assertEqual(len(r), len(table) + 1)
        for (msg, want), got in zip(table, r):
            if isinstance(want, int):
                self.assertEqual(got.get('error', {}).get('code'), want, (msg if len(str(msg)) < 300 else str(msg)[:80], got))
            else:
                self.assertEqual(got['result']['isError'], want[0], got)
                self.assertIn(want[1], got['result']['content'][0]['text'])
        self.assertEqual(r[-1], {'jsonrpc': '2.0', 'id': 99, 'result': {}})

    def test_stdin_is_not_lent(self):
        """M9: a program the server starts (here a "sva" that reads its stdin) does not read the protocol's requests."""
        with H.tmp() as d:
            fake = os.path.join(d, 'sva')
            with open(fake, 'w') as f:
                f.write('#!/bin/sh\ncat > /dev/null\necho "sva: read" >&2\nexit 1\n')
            os.chmod(fake, 0o755)
            p = subprocess.Popen([sys.executable, '-I', os.path.join(H.TOOLS, 'wavemcp.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, env=dict(os.environ, WAVELENS_SVA=fake))
            got = []
            reader = threading.Thread(target=lambda: got.extend(json.loads(p.stdout.readline()) for _ in range(2)), daemon=True)
            reader.start()
            p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {
                'name': 'sva_check', 'arguments': {'dump': H.fixture('short'), 'source': 'a: assert property (@(posedge b[0]) 1);'}}}) + '\n')
            p.stdin.flush()
            time.sleep(0.5)
            p.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}) + '\n')
            p.stdin.flush()
            try:
                reader.join(15)
                self.assertFalse(reader.is_alive(), 'two answers in 15 s')
            finally:
                p.stdin.close()
                try:
                    p.wait(10)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                p.stdout.close()
        self.assertEqual([m.get('id') for m in got], [1, 2])
        self.assertEqual(got[1]['result'], {})

    def test_unknown_version_gets_ours(self):
        r = self.talk({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '1999-01-01'}})
        self.assertEqual(r[0]['result']['protocolVersion'], W.PROTOCOLS[0])

    def test_cli(self):
        rc, out, err = H.run_tool('wavemcp', '--call', 'wave_info', json.dumps({'dump': H.fixture('short')}))
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)['file'], 'short.vcd')
        rc, out, _ = H.run_tool('wavemcp', '--list')
        self.assertEqual(rc, 0)
        self.assertEqual(len(json.loads(out)), len(W.TOOLS))


class Arguments(unittest.TestCase):
    """The types file beside a dump (its enum labels, as mkconfig.py takes them), the synonyms of sibling tools' names,
    an argument a tool does not take."""
    TYPES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'types')
    QV = os.path.join(TYPES, 'questa.vcd')

    def value(self, **a):
        text, err = W.call('wave_values', {'dump': self.QV, 'signals': 'types_tb.al', 'at': 0, **a})
        self.assertFalse(err, text)
        return json.loads(text)['rows'][0][1]

    def test_types_beside_the_dump(self):
        self.assertEqual(self.value(), 'STOP')                 # questa.types.json beside questa.vcd (it was "3")
        self.assertEqual(self.value(no_types=True), '3')
        info = json.loads(W.call('wave_info', {'dump': self.QV})[0])
        self.assertEqual(info['types'], 'questa.types.json')
        self.assertTrue(any(n.startswith('types questa.types.json: labels for ') for n in info['notes']), info.get('notes'))
        miss = json.loads(W.call('wave_info', {'dump': os.path.join(self.TYPES, 'missing.vcd')})[0])   # stage 14.4: what it lacks
        self.assertIn('types missing.types.json: 7 signals of the types are not in the dump: unpacked arrays 2, under generate scopes 5', miss['notes'])
        with H.tmp() as d:   # another types file by name; none beside a copy of the dump
            v, t = os.path.join(d, 'q.vcd'), os.path.join(d, 'other.json')
            shutil.copy(self.QV, v)
            shutil.copy(os.path.join(self.TYPES, 'questa.types.json'), t)
            self.assertEqual(self.value(dump=v), '3')
            self.assertEqual(self.value(dump=v, types=t), 'STOP')
            text, err = W.call('wave_values', {'dump': v, 'signals': 'types_tb.al', 'at': 0, 'types': os.path.join(d, 'nope.json')})
            self.assertTrue(err)
            self.assertIn('"types": no such file', text)
            shutil.copy(t, os.path.join(d, 'q.types.json'))   # a types file that appears: the cached dump reads it
            self.assertEqual(self.value(dump=v), 'STOP')

    def test_synonyms(self):
        self.assertEqual(self.value(at=None, times=[0]), 'STOP')
        text, err = W.call('wave_values', {'dump': self.QV, 'signal': 'types_tb.al', 't': 0})
        self.assertFalse(err, text)
        text, err = W.call('wave_find', {'dump': self.QV, 'signals': ['types_tb.al'], 'edge': 'change'})
        self.assertFalse(err, text)
        self.assertEqual(json.loads(text)['signal'], 'types_tb.al')
        text, err = W.call('wave_find', {'dump': self.QV, 'signals': ['a', 'b'], 'edge': 'change'})
        self.assertTrue(err)
        self.assertIn('searches one "signal", not 2', text)
        text, err = W.call('wave_values', {'dump': self.QV, 'signals': 'types_tb.al', 'at': 0, 't': 5})
        self.assertEqual((text, err), ('"t" is "at" here, and both are given with other values', True))
        text, err = W.call('sva_check', {'dump': self.QV, 'text': 'module m; endmodule'})
        self.assertNotIn('no argument', text)

    def test_lean_list(self):
        full, lean = W.listing(False), W.listing(True)
        size = lambda x: len(json.dumps(x, separators=(',', ':')))
        self.assertEqual([t['name'] for t in lean], [t['name'] for t in full])
        self.assertLess(size(lean), size(full) * 0.7)   # (measured: 9649 -> 6474 characters)
        self.assertNotIn('types', next(t for t in lean if t['name'] == 'wave_values')['inputSchema']['properties'])
        self.assertEqual(self.value(types=os.path.join(self.TYPES, 'questa.types.json')), 'STOP')   # still taken

    def test_view_edit_says_what_needs_a_page(self):   # review 0.31 M5
        d = next(t for t in W.listing(False) if t['name'] == 'view_edit')['description']
        for k in W.viewedit.LIVE_ONLY:
            if k != 'picture':
                self.assertIn(f'{k}({W.viewedit.COMMANDS[k]})·live', d)
        self.assertNotIn('cursor(t)·live', d)

    def test_a_name_and_a_side_checked(self):   # review 0.31 M6, M12
        text, err = W.call('wave_values', {'dump': self.QV, 'signals': 'types_tb.al', 'at': 0, 'side': 'middle'})
        self.assertTrue(err)
        self.assertIn('"side": before or after', text)
        for r in ('roman', 'q'):
            text, err = W.call('wave_values', {'dump': self.QV, 'signals': 'types_tb.al', 'at': 0, 'radix': r})
            self.assertTrue(err)
            self.assertIn('"radix": auto, hex', text)
        text, err = W.call('wave_values', {'dump': self.QV, 'signals': 'types_tb.al', 'at': 0, 'radix': 'sq15'})
        self.assertFalse(err, text)
        text, err = W.call('wave_signals', {'dump': self.QV, 'limit': 'ten'})
        self.assertIn('"limit": an integer, not "ten"', text)

    def test_unknown_argument(self):
        text, err = W.call('wave_values', {'dump': self.QV, 'signals': 'types_tb.al', 'at': 0, 'colour': 'red'})
        self.assertTrue(err)
        self.assertTrue(text.startswith('wave_values: no argument "colour" (it takes: dump, '), text)


if __name__ == '__main__':
    unittest.main()


class Measures(unittest.TestCase):
    """Stage 16: view_get's measures (the Δ of the markers as a table, in ns), a bound given in ns, the measures command."""
    def test_measures_in_ns(self):
        with H.tmp() as d:
            page, j = os.path.join(d, 'p.html'), os.path.join(d, 'v.json')
            with open(j, 'w', encoding='utf-8') as f:
                json.dump({'signal': [{'name': 'clk', 'wave': 'p.......'}], 'time': {'t0': 0, 't1': 80000, 'cycle': 10000, 'unit': 'ps'}}, f)
            self.assertEqual(H.run_tool('mkhtml', f'one={j}', '--no-sva', '--out', page)[0], 0)
            text, bad = W.call('view_edit', {'page': page, 'ops': [{'op': 'marker', 't': 10, 'label': 'req'}, {'op': 'marker', 't': 40, 'label': 'ack', 'dmin': 5},
                                                                    {'op': 'marker', 't': 50}, {'op': 'marker', 'id': 1, 'dmax': 20}, {'op': 'measures'}]})
            self.assertFalse(bad, text)
            m = json.loads(text)['results'][-1]['measures']
            self.assertEqual([(r['from']['t'], r['to']['t'], r['dt'], r.get('dmax'), r.get('ok')) for r in m], [(10, 40, 30, 20, False), (40, 50, 10, None, True)])
            g = json.loads(W.call('view_get', {'page': page})[0])
            self.assertEqual(g['measures'], m)
            self.assertEqual([x.get('dmin') for x in g['markers']], [None, 5, None])

    def test_the_page_own_measures(self):
        """Review S16-2: a page whose markers are its own "measures" (a cocotb test's wl.measure): view_get and viewedit --measure give
        them before any marker by hand; S16-1: a bound in cycles on a view with no clock -> the lint measure-no-clock."""
        with H.tmp() as d:
            page, j = os.path.join(d, 'p.html'), os.path.join(d, 'v.json')
            with open(j, 'w', encoding='utf-8') as f:
                json.dump({'signal': [{'name': 'data', 'wave': '01.0.1..'}], 'time': {'t0': 0, 't1': 80000, 'cycle': 10000, 'unit': 'ps'},
                           'measures': [{'label': 'r', 'from': 10000, 'to': 40000, 'max': '20ns'}, {'label': 'c', 'from': 40000, 'to': 60000, 'max': '1 cycle'}]}, f)
            rc, _, err = H.run_tool('mkhtml', f'one={j}', '--no-sva', '--out', page)
            self.assertEqual(rc, 0, err)
            import types, vcd2wavedrom
            doc = json.loads(H.text(j))
            self.assertEqual([x.split(':')[0] for x in vcd2wavedrom.lint(doc, types.SimpleNamespace(marker=[]), 'views.one')], ['measure-no-clock'])
            doc['signal'].append({'name': 'clk', 'wave': 'p.......'})
            self.assertEqual(vcd2wavedrom.lint(doc, types.SimpleNamespace(marker=[]), 'views.one'), [], 'a clock in the view: no warning')
            g = json.loads(W.call('view_get', {'page': page})[0])
            self.assertEqual([(r['dt'], r.get('ok')) for r in g.get('measures', [])], [(30, False), (20, None)], g)
            self.assertTrue(g['markers'] and all(x.get('page') for x in g['markers']), g.get('markers'))
            rc, out, err = H.run_tool('viewedit', page, '--measure')
            self.assertEqual(rc, 0, err)
            self.assertIn('2 measurements', out)
            rc, out, _ = H.run_tool('viewedit', page, '--measure', '--csv')
            self.assertEqual(len(out.splitlines()), 3)


class Review1103(unittest.TestCase):
    """B-02 of the review of 2026-11-03: every time of the server in ns, the spans and the Δ of the markers too."""
    def test_spans_and_deltas_in_ns(self):
        with H.tmp() as d:
            page, j = os.path.join(d, 'p.html'), os.path.join(d, 'v.json')
            with open(j, 'w', encoding='utf-8') as f:
                json.dump({'signal': [{'name': 'clk', 'wave': 'p.......'}], 'time': {'t0': 0, 't1': 80000, 'cycle': 10000, 'unit': 'ps'}}, f)
            rc, _, err = H.run_tool('mkhtml', f'one={j}', '--no-sva', '--out', page)
            self.assertEqual(rc, 0, err)
            text, bad = W.call('view_edit', {'page': page, 'ops': [{'op': 'span', 'from': 10, 'to': 20}, {'op': 'marker', 't': 10},
                                                                    {'op': 'marker', 't': 30}, {'op': 'deltas', 'on': True}]})
            self.assertFalse(bad, text)
            self.assertEqual(json.loads(text)['results'][-1]['deltas'], [{'from': 1, 'to': 2, 'dt': 20}])
            text, bad = W.call('view_get', {'page': page, 'full': True})
            g = json.loads(text)   # full: the state's keys in the answer
            self.assertEqual([(s['from'], s['to']) for s in g['spans']], [(10, 20)])
            st = {'wavelens': 'state', 'spans': g['spans'], 'markers': g['markers']}   # read, given back: where it was
            text, bad = W.call('view_edit', {'page': page, 'ops': [{'op': 'set_state', 'state': st}]})
            self.assertFalse(bad, text)
            st2 = json.loads(W.call('view_get', {'page': page, 'full': True})[0])
            self.assertEqual(([(s['from'], s['to']) for s in st2['spans']], [m['t'] for m in st2['markers']]), ([(10, 20)], [10, 30]))

    def test_what_an_agent_reads_of_a_state(self):
        """T-04 of the review (M-04): view_get's summary of a state: the second cursor, the range, spans, groups, highlight, sort, style."""
        with H.tmp() as d:
            page, j = os.path.join(d, 'p.html'), os.path.join(d, 'v.json')
            with open(j, 'w', encoding='utf-8') as f:
                json.dump({'signal': [{'name': 'clk', 'wave': 'p.......'}, ['tb', {'name': 'valid', 'wave': '0.1.0...'}]],
                           'time': {'t0': 0, 't1': 80000, 'cycle': 10000, 'unit': 'ps'}}, f)
            self.assertEqual(H.run_tool('mkhtml', f'one={j}', '--no-sva', '--out', page)[0], 0)
            st = {'wavelens': 'state', 'cursor': 15, 'cursor2': 40, 'range': {'from': 20, 'to': 50, 'signal': 'tb.valid'},
                  'spans': [{'from': 10, 'to': 30, 'label': 's'}], 'groups': [{'name': 'g', 'signals': ['clk']}],
                  'config': {'sort': 'asc', 'style': 'questa', 'highlight': ['tb.valid']}}
            text, bad = W.call('view_edit', {'page': page, 'ops': [{'op': 'set_state', 'state': st}]})
            self.assertFalse(bad, text)
            g = json.loads(W.call('view_get', {'page': page})[0])
            self.assertEqual({k: g.get(k) for k in ('cursor', 'cursor2', 'range', 'sort', 'style', 'highlight')},
                             {'cursor': 15, 'cursor2': 40, 'range': [20, 50, 'tb.valid'], 'sort': 'asc', 'style': 'questa', 'highlight': ['tb.valid']})
            self.assertEqual([(x['id'], x['from'], x['to'], x['label']) for x in g['spans']], [(1, 10, 30, 's')])
            self.assertEqual(g['groups'], [{'name': 'g', 'signals': ['clk']}])
