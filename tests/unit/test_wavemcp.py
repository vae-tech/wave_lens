"""tools/wavemcp.py: the MCP protocol over stdio, the tools against a generated dump whose answers are known
(tests/mcp_bench.py gen_vcd), names, errors."""
import io, json, os, shutil, subprocess, sys, threading, time, unittest

from tests.unit import helpers as H
from tests import mcp_bench as B
import svabuild
import viewedit as E
import wavemcp as W

CACHE = H.tmp()   # the bridges of these tests announce themselves here, not in ~/.cache/wavelens/live (a VS Code there would connect)


def setUpModule():
    os.environ['XDG_CACHE_HOME'] = CACHE.name


def tearDownModule():
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
        while not b.pending:
            time.sleep(0.01)
        rid = next(iter(b.pending))
        self.assertEqual(req(f'/reply?{q}', json.dumps({'rid': rid, 'results': [{'op': 'state', 'state': {'forged': 1}}]}).encode()), 409)
        self.assertEqual(req(f'/reply?token={b.token}&cid=page1aaa', json.dumps({'rid': rid, 'results': [{'op': 'state', 'state': {}}]}).encode()), 200)
        t.join(5)
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
        text, err = W.call('view_edit', {'page': dump, 'ops': [{'op': 'marker', 't': 5}]})
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
        while True:
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
        self.assertEqual([t['name'] for t in r[1]['result']['tools'] if not t['annotations']['readOnlyHint']], ['wave_page', 'view_edit', 'view_live'])
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
                (call(4, 'sva_check', {'dump': short, 'defines': 5}), (True, '"defines": a object/array of string, not 5')),
                (call(5, 'wave_signals', {'dump': short, 'scope': 5}), (True, '"scope": a string, not 5')),
                (call(6, 'wave_values', {'dump': short, 'signals': ['b'], 'at': '1e999'}), (True, 'bad time "1e999"')),
                ('{"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "wave_values", "arguments": '
                 f'{{"dump": {json.dumps(short)}, "signals": ["b"], "at": 1e999}}}}}}', (True, '"at": a number/string/array')),
                ('{"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "wave_values", "arguments": '
                 f'{{"dump": {json.dumps(short)}, "signals": ["b"], "at": NaN}}}}}}', (True, '"at": a number/string/array')),
                (call(9, 'wave_page', {'dump': short, 'signals': ['b'], 'from': -5, 'out': os.path.join(d, 'w.json')}), (False, '"wavejson"')),
                (call(10, 'wave_signals', {'dump': short, 'limit': 2.0}), (False, '"total"')),
                (call(11, 'wave_signals', {'dump': short, 'limit': 'many'}), (True, '"limit": a integer')),
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
            reader.join(15)
            p.stdin.close()
            p.wait(10)
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


if __name__ == '__main__':
    unittest.main()
