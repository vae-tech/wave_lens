"""tools/wavemcp.py: the MCP protocol over stdio, the tools against a generated dump whose answers are known
(tests/mcp_bench.py gen_vcd), names, errors."""
import io, json, os, unittest

from tests.unit import helpers as H
from tests import mcp_bench as B
import svabuild
import wavemcp as W


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

    @unittest.skipUnless(svabuild.find_bin(), 'no sva CLI')
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
        self.assertEqual(r[0]['result']['serverInfo']['name'], 'wavefw')
        names = [t['name'] for t in r[1]['result']['tools']]
        self.assertEqual(names[0], 'wave_info')
        self.assertTrue(all('fn' not in t and t['inputSchema']['type'] == 'object' for t in r[1]['result']['tools']))
        # codex exec calls a tool without approval only when it says it reads: every tool but wave_page (it writes a file)
        self.assertEqual([t['name'] for t in r[1]['result']['tools'] if not t['annotations']['readOnlyHint']], ['wave_page'])
        arrays = [(t['name'], k) for t in r[1]['result']['tools'] for k, v in t['inputSchema']['properties'].items()
                  if 'array' in str(v.get('type')) and 'items' not in v]
        self.assertEqual(arrays, [])   # an array without items is refused by OpenAI's function schemas
        self.assertFalse(r[2]['result']['isError'])
        self.assertIn('"unit":"ns"', r[2]['result']['content'][0]['text'])
        self.assertTrue(r[3]['result']['isError'])
        self.assertEqual((r[4]['error']['code'], r[5]['error']['code']), (-32700, -32601))
        self.assertEqual(r[6]['result'], {})

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
