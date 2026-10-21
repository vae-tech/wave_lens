"""tools/viewedit.py: the viewer's commands on a state (names, every command, its errors), a page's edits (the block,
revisions), a saved state and the command line. That the browser gets the same state from them as from view.run is
the smoke test's (section edit)."""
import json, os, unittest

from tests.unit import helpers as H
import viewedit as V

DOC = {'signal': [
    {'name': 'clk', 'wave': 'p.......'},
    ['tb',
     ['dut', {'name': 'state', 'wave': '=.=.=.=.', 'data': ['A', 'B', 'C', 'D'], 'width': 2}, {'name': 'valid', 'wave': '0.1.0...'},
      {'name': 'data', 'wave': '=.=.....', 'data': ['0', '1'], 'width': 8}],
     ['other', {'name': 'state', 'wave': '0.1.....'}, {'name': 'reg', 'wave': '=.......', 'data': ['5'], 'width': 8,
                                                      'fields': [{'name': 'lo', 'msb': 3, 'lsb': 0}, {'name': 'hi', 'msb': 7, 'lsb': 4}]}]]],
    'time': {'t0': 0, 't1': 80000, 'cycle': 10000, 'unit': 'ps'},
    'config': {'highlight': 'valid', 'fold': 'tb.other'},
    'bookmarks': [{'n': 1, 't': '20ns', 'signal': 'tb.dut.valid', 'text': 'page own'}],
    'arrows': []}


def ed(state=None, doc=DOC, settings=None):
    return V.Editor(V.Model(doc, settings), state)


class Names(unittest.TestCase):
    def setUp(self):
        self.m = V.Model(DOC)

    def full(self, spec, **o):
        return [r['full'] for r in self.m.pick({}, spec, **o)]

    def test_model(self):
        self.assertEqual([r['full'] for r in self.m.sigs()], ['clk', 'tb.dut.state', 'tb.dut.valid', 'tb.dut.data', 'tb.other.state',
                                                               'tb.other.reg.lo', 'tb.other.reg.hi'])
        self.assertEqual([(g['id'], g['path']) for g in self.m.groups], [(0, 'tb'), (1, 'tb.dut'), (2, 'tb.other'), (3, 'tb.other.reg')])
        self.assertTrue(self.m.timed)

    def test_pick(self):
        self.assertEqual(self.full('tb.dut.state'), ['tb.dut.state'])   # a full path
        self.assertEqual(self.full('valid'), ['tb.dut.valid'])           # a name
        self.assertEqual(self.full('other.state'), ['tb.other.state'])   # the end of a path
        self.assertEqual(self.full('top.tb.dut.valid'), ['tb.dut.valid'])   # a longer path (the dump's) of a row the page names shorter
        net = V.Model({'signal': [{'name': 'clk', 'wave': 'p.'}, ['u', {'name': 'clk', 'wave': 'p.'}]]})
        self.assertEqual([r['full'] for r in net.pick({}, 'clk')], ['clk'])   # one net at several levels: the one nearest the top
        self.assertEqual(self.full('tb.dut.*'), ['tb.dut.state', 'tb.dut.valid', 'tb.dut.data'])
        self.assertEqual(self.full('clk, valid'), ['clk', 'tb.dut.valid'])
        self.assertEqual(self.full('dut', groups=True), ['tb.dut'])
        with self.assertRaisesRegex(V.WaveError, r'"state" is ambiguous: tb.dut.state, tb.other.state'):
            self.full('state')
        with self.assertRaisesRegex(V.WaveError, r'no signal "vali"; similar: tb.dut.valid'):
            self.full('vali')
        with self.assertRaisesRegex(V.WaveError, 'no signal "dut"'):
            self.full('dut')   # a module is not a signal
        with self.assertRaisesRegex(V.WaveError, 'one signal, not 2'):
            self.m.pick({}, 'clk, valid', one=True)

    def test_bases(self):
        self.assertEqual(self.m.base_highlight(), ['tb.dut.valid'])
        self.assertEqual(self.m.base_fold(), ['tb.other'])
        own = dict(DOC, config={})   # the global settings' fold (the diagram's own wins over them)
        self.assertEqual(V.Model(own, {'fold': 1}).base_fold(), ['tb.dut', 'tb.other', 'tb.other.reg'])
        self.assertEqual(V.bm_list(self.m.base_bookmarks()), [{'n': 1, 't': 20000.0, 'signal': 'tb.dut.valid', 'text': 'page own'}])


class Commands(unittest.TestCase):
    def run_ok(self, e, *ops):
        res = e.run(list(ops))
        for r in res:
            self.assertNotIn('error', r, r)
        return res

    def test_bookmarks_and_arrows(self):
        e = ed()
        res = self.run_ok(e, {'op': 'bookmark', 't': '50ns', 'signal': 'data', 'text': 'here'}, {'op': 'bookmark', 't': 60000, 'color': '#0a0'},
                          {'op': 'bookmark', 'n': 2, 'signal': 'clk', 'lift': True}, {'op': 'arrow', 'from': 1, 'to': 2, 'label': 'Δ'},
                          {'op': 'arrow', 'from': 2, 'to': 3, 'shape': '-|', 'head': ''}, {'op': 'arrow', 'from': 1, 'to': 2, 'color': '#f00'})
        self.assertEqual([r.get('n') or r.get('id') for r in res], [2, 3, 2, 1, 2, 1])   # the page has bookmark 1; the third arrow is the first again
        self.assertEqual(e.st['bookmarks'], [{'n': 1, 't': 20000, 'signal': 'tb.dut.valid', 'text': 'page own'},
                                             {'n': 2, 't': 50000, 'signal': 'clk', 'text': 'here', 'lift': True},
                                             {'n': 3, 't': 60000, 'color': '#0a0'}])
        self.assertEqual(e.st['arrows'], [{'from': 1, 'to': 2, 'shape': '~', 'color': '#f00', 'label': 'Δ'}, {'from': 2, 'to': 3, 'shape': '-|', 'head': ''}])
        self.run_ok(e, {'op': 'bookmark', 'n': 2, 'delete': True})   # its arrows go too
        self.assertEqual(([b['n'] for b in e.st['bookmarks']], e.st['arrows']), ([1, 3], []))
        bad = e.run([{'op': 'bookmark', 'n': 9, 'delete': True}, {'op': 'arrow', 'from': 1, 'to': 7}, {'op': 'arrow', 'from': 1, 'to': 1},
                     {'op': 'arrow', 'id': 5, 'label': 'x'}, {'op': 'arrow', 'from': 1, 'to': 3, 'shape': '?'}, {'op': 'bookmark', 'n': 'all'},
                     {'op': 'bookmark', 'signal': 'clk'}])
        self.assertEqual([r['error'] for r in bad], ['no bookmark 9 (there are: 1, 3)', 'to: no bookmark 7 (there are: 1, 3)',
                                                     'arrow: from and to are one bookmark', 'no arrow 5 (there are 0)',
                                                     'shape: one of "~" "-" "-~" "~-" "-|" "|-" "-|-"', 'n: a bookmark number (1, 2 …)',
                                                     'bookmark: t (the cursor here is not known)'])
        self.run_ok(e, {'op': 'bookmark', 'n': 'all', 'delete': True})
        self.assertEqual((e.st['bookmarks'], e.st['arrows']), ([], []))

    def test_markers_groups(self):
        e = ed()
        self.run_ok(e, {'op': 'marker', 't': '10ns', 'label': 'a'}, {'op': 'marker', 't': '30ns'}, {'op': 'marker', 'id': 2, 'label': 'b', 'color': 'red'},
                    {'op': 'group', 'name': 'mine', 'signals': ['valid', 'clk']}, {'op': 'group', 'name': 'mine', 'add': 'dut', 'remove': 'clk'},
                    {'op': 'group', 'name': 'regs', 'signals': 'tb.other.reg', 'color': '#08f'}, {'op': 'group', 'name': 'regs', 'rename': 'fields'},
                    {'op': 'highlight', 'add': ['mine', '@fields']}, {'op': 'paint', 'signals': 'fields', 'color': '#123'})
        self.assertEqual(e.st['markers'], [{'t': 10000, 'label': 'a'}, {'t': 30000, 'label': 'b', 'color': 'red'}])
        self.assertEqual(e.st['groups'], [{'name': 'mine', 'signals': ['tb.dut.valid', 'tb.dut.state', 'tb.dut.data']},
                                          {'name': 'fields', 'signals': ['tb.other.reg.lo', 'tb.other.reg.hi'], 'color': '#08f'}])
        self.assertEqual(e.st['config']['highlight'], ['tb.dut.valid', '@mine', '@fields'])   # after the page's own
        self.assertEqual(e.st['paint'], {'tb.other.reg.lo': '#123', 'tb.other.reg.hi': '#123'})
        self.run_ok(e, {'op': 'fold', 'groups': 'fields'}, {'op': 'group', 'name': 'fields', 'go': True}, {'op': 'layout', 'scroll': 'page', 'tools': 'fold'})
        self.assertEqual((e.st['folds'], e.st['select'], e.st['config']['maxHeight'], e.st['config']['toolsFolded']),
                         ({'@fields': False}, 'tb.other.reg.lo', None, True))   # the page's maxHeight is none: "page" is none
        self.run_ok(e, {'op': 'layout', 'scroll': 'window'})
        self.assertEqual(e.st['config']['maxHeight'], '80vh')
        self.assertEqual(e.run([{'op': 'layout', 'height': 'tall'}])[0]['error'], 'height: 600 (px) or "80vh"')
        self.run_ok(e, {'op': 'marker', 'id': 1, 'delete': True}, {'op': 'group', 'name': 'mine', 'delete': True})
        self.assertEqual((len(e.st['markers']), [g['name'] for g in e.st['groups']]), (1, ['fields']))
        bad = e.run([{'op': 'group', 'name': 'fields', 'rename': ''}, {'op': 'group', 'name': 'x', 'delete': True}, {'op': 'marker', 'id': 4},
                     {'op': 'marker', 'id': 'case-1', 't': 5}, {'op': 'arrow', 'id': 'w-before-aw', 'from': 1, 'to': 2}, {'op': 'paint', 'signals': 5}])
        self.assertEqual([r['error'] for r in bad][:5], ['rename: a name', 'no group "x"', 'no marker 4 (there are 1)',
                                                         'id: the number of the marker as listed (1, 2 …), not "case-1"; a new one: no id',
                                                         'id: the number of the arrow as listed (1, 2 …), not "w-before-aw"; a new one: no id'])
        self.assertIn('error', bad[5])   # an argument of a kind not foreseen: an error of that command, not of the call

    def test_rows_view_state(self):
        e = ed()
        self.run_ok(e, {'op': 'highlight', 'remove': 'valid', 'add': 'clk'}, {'op': 'hide', 'signals': ['tb.other']}, {'op': 'select', 'signal': 'data'},
                    {'op': 'fold', 'groups': 'dut'}, {'op': 'unfold', 'groups': 'tb.other'}, {'op': 'radix', 'signals': 'data', 'radix': 'sq4'},
                    {'op': 'analog', 'signals': 'data', 'rows': True}, {'op': 'sort', 'dir': 'desc', 'ignore': 'i_,in_'}, {'op': 'style', 'name': 'questa'},
                    {'op': 'find', 'query': 'val', 'case': True}, {'op': 'cursor', 't': '25ns'}, {'op': 'cursor2', 't': 45000},
                    {'op': 'view', 'from': '10ns', 'to': '70ns'}, {'op': 'range', 'from': '40ns', 'to': '20ns', 'signal': 'clk'})
        st = e.st
        self.assertEqual(st['config'], {'highlight': ['clk'], 'sort': 'desc', 'sortIgnore': ['in_', 'i_'], 'style': 'questa', 'findCase': True})
        self.assertEqual((st['hidden'], st['select'], st['folds'], st['radix'], st['analog']),
                         (['tb.other'], None, {'tb.dut': True, 'tb.other': False}, {'tb.dut.data': 'sq4'}, {'tb.dut.data': 3}))   # data folded away
        self.assertEqual((st['cursor'], st['cursor2'], st['from'], st['to'], st['range']), (25000, 45000, 10000, 70000,
                                                                                            {'from': 20000, 'to': 40000, 'signal': 'clk'}))
        self.assertEqual(e.fold(), ['tb.dut'])
        self.run_ok(e, {'op': 'view', 'span': '20ns'}, {'op': 'show'}, {'op': 'fold', 'all': True}, {'op': 'reset'},
                    {'op': 'gaps', 'on': True, 'idle': 8}, {'op': 'gaps', 'reset': True})
        self.assertEqual((st['from'], st['to'], st['hidden'], st['folds'], st['select'], st['find'], st['range']),
                         (15000, 35000, [], {'*': True}, None, '', None))
        self.assertTrue(all(st['config'][k] is None for k in V.ALL_GAP_KEYS))
        bad = e.run([{'op': 'radix', 'signals': 'data', 'radix': 'roman'}, {'op': 'analog', 'signals': 'clk', 'rows': 2}, {'op': 'sort', 'dir': 'up'},
                     {'op': 'fold', 'groups': 'clk'}, {'op': 'cursor', 't': 'soon'}, {'op': 'edge'}, {'op': 'nope'}, {'op': 'cursor', 'at': 1},
                     {'op': 'view', 'from': 5}])
        self.assertEqual([r['error'] for r in bad][:5], ['radix: one of auto hex dec signed bin oct ascii float, q<F> or sq<F> (fixed point), or null',
                                                         'not a bus: clk', 'dir: one of none asc desc', 'fold: no module in "clk"',
                                                         't: "soon" is not a time (a number in ps, or "250ns")'])
        self.assertIn('runs in the page only', bad[5]['error'])
        self.assertTrue(bad[6]['error'].startswith('no command "nope"; the commands: cursor cursor2 view'))
        self.assertEqual(bad[7]['error'], 'cursor takes t, not at')
        self.assertEqual(bad[8]['error'], 'view: from and to, or span (and at)')

    def test_untimed_and_state(self):
        doc = {'signal': [{'name': 'a', 'wave': '01'}]}
        e = ed(doc=doc)
        self.assertEqual(e.run([{'op': 'cursor', 't': '5ns'}])[0]['error'], 't: these waves have no time, give cycles (a number)')
        self.run_ok(e, {'op': 'cursor', 't': 1.5})
        st = {'wavefw': 'state', 'version': 3, 'bookmarks': [{'n': 4, 't': 7}], 'paint': {'gone': '#fff'}}
        r = self.run_ok(e, {'op': 'set_state', 'state': st}, {'op': 'state'})
        self.assertEqual((r[0]['missing'], r[1]['state']), (['gone'], {'bookmarks': [{'n': 4, 't': 7}], 'paint': {'gone': '#fff'}}))
        self.assertEqual(e.run([{'op': 'set_state', 'state': [1]}])[0]['error'], 'set_state: not a saved viewer state ({"wavefw": "state", …})')
        rows = self.run_ok(ed(), {'op': 'group', 'name': 'g', 'signals': 'clk'}, {'op': 'rows', 'pattern': 'st', 'limit': 1})[1]
        self.assertEqual(rows, {'op': 'rows', 'total': 2, 'rows': [['tb.dut.state', 2]], 'next_offset': 1})

    def test_commands_list(self):
        self.assertEqual(set(V.TIME_ARGS) - set(V.COMMANDS), set())
        rc, out, _ = H.run_tool('viewedit', '--commands')
        self.assertEqual((rc, out.split()[0]), (0, 'cursor'))

    def test_group_move(self):
        """A group's place among yours (edit.js): up, down, top, bottom, a number; a bad one said, nothing changed."""
        e = ed()
        self.run_ok(e, {'op': 'group', 'name': 'a', 'signals': 'clk'}, {'op': 'group', 'name': 'b', 'signals': 'valid'},
                    {'op': 'group', 'name': 'c', 'signals': 'data'})
        self.assertEqual(e.run([{'op': 'group', 'name': 'c', 'move': 1}])[0]['at'], 1)
        self.run_ok(e, {'op': 'group', 'name': 'a', 'move': 'down'}, {'op': 'group', 'name': 'b', 'move': 'top'})
        self.assertEqual([g['name'] for g in e.st['groups']], ['b', 'c', 'a'])
        for bad in (0, 1.5, True, 'left'):   # as edit.js: a whole number from 1, or a word
            self.assertIn('move: up, down', e.run([{'op': 'group', 'name': 'a', 'move': bad}])[0]['error'])
        self.assertEqual([g['name'] for g in e.st['groups']], ['b', 'c', 'a'])
        self.assertEqual(e.run([{'op': 'group', 'name': 'a', 'move': 1.0}, {'op': 'group', 'name': 'c', 'move': 'bottom'},
                                {'op': 'group', 'name': 'b', 'move': 'up'}])[0]['at'], 1)   # 1.0: JSON's 1 in JavaScript
        self.assertEqual([g['name'] for g in e.st['groups']], ['b', 'a', 'c'])

    def test_cycles(self):
        """The clock cycles (view.js setCycles): the clock by its path, a time for cycle 0, a bad argument changes nothing,
        reset gives the page's settings back (null in a state: the clock found), a saved state alone keeps the name."""
        e = ed(settings={'cycleClock': 'tb.dut.valid', 'cycleZero': 20000})
        self.assertEqual(e.run([{'op': 'cycles', 'on': True, 'clock': 'clk', 'zero': '30ns'}])[0]['cycles'],
                         {'cycles': True, 'cycleClock': 'clk', 'cycleZero': 30000})
        bad = e.run([{'op': 'cycles', 'on': False, 'clock': 'data'}])[0]
        self.assertIn('not a 1-bit signal', bad['error'])
        self.assertTrue(e.st['config']['cycles'])                              # nothing changed by the bad command
        self.assertEqual(e.run([{'op': 'cycles', 'clock': None, 'zero': None}])[0]['cycles'], {'cycles': True, 'cycleClock': None, 'cycleZero': None})
        self.assertEqual(e.run([{'op': 'cycles', 'reset': True}])[0]['cycles'], {'cycles': False, 'cycleClock': 'tb.dut.valid', 'cycleZero': 20000})
        alone = V.Editor(V.Model(), {})
        self.assertEqual(alone.run([{'op': 'cycles', 'clock': 'tb.clk'}])[0]['cycles']['cycleClock'], 'tb.clk')   # no page: the width unknown


class Pages(unittest.TestCase):
    def setUp(self):
        self.d = H.tmp()
        self.page = os.path.join(self.d.name, 'p.html')
        j = os.path.join(self.d.name, 'v.json')
        with open(j, 'w', encoding='utf-8') as f:
            json.dump(DOC, f)
        rc, _, err = H.run_tool('mkhtml', f'one={j}', '--no-sva', '--out', self.page)
        self.assertEqual(rc, 0, err)

    def tearDown(self):
        self.d.cleanup()

    def text(self):
        with open(self.page, encoding='utf-8') as f:
            return f.read()

    def test_edits(self):
        res, key, rev = V.edit_page(self.page, [{'op': 'bookmark', 't': '30ns', 'text': 'a </script> b'}])
        self.assertEqual((res, key, rev[:3]), ([{'op': 'bookmark', 'n': 2}], 'one', 'r1@'))
        t = self.text()
        self.assertEqual(t.count('<script type="application/json" id="wavefw-edits">'), 2)   # the block, and the comment in wavefw.js
        self.assertIn('a \\u003c/script> b', t)   # no < in the block: </script> and <!--<script> do not end or swallow it
        self.assertLess(t.index('id="wavefw-edits">{'), t.index('<script>window.WAVEFW_CONFIG'))
        _, _, rev2 = V.edit_page(self.page, [{'op': 'marker', 't': 1000}])
        self.assertTrue(rev2.startswith('r2@'))
        _, _, rev3 = V.edit_page(self.page, [{'op': 'paint', 'signals': 'clk', 'color': None}])
        self.assertIsNone(rev3)   # nothing changed: no revision
        p = V.Page(self.page)
        self.assertEqual((p.rev('one'), p.state('one')['markers'], p.state('one')['bookmarks'][1]['text']), (rev2, [{'t': 1000}], 'a </script> b'))
        self.assertEqual(V.put_block(V.put_block(p.text, 'live', {'port': 1}), 'live', None), p.text)
        with self.assertRaisesRegex(V.WaveError, 'no view "two" in p.html'):
            p.view('two')

    def test_cli(self):
        ops = os.path.join(self.d.name, 'ops.json')
        with open(ops, 'w', encoding='utf-8') as f:
            json.dump([{'op': 'group', 'name': 'g', 'signals': 'dut'}, {'op': 'hide', 'signals': 'nosuch'}], f)
        rc, out, err = H.run_tool('viewedit', self.page, '--ops', '@' + ops)
        self.assertEqual(rc, 1)   # one failed: said, the other done
        self.assertEqual(json.loads(out)[0], {'op': 'group', 'name': 'g', 'signals': 3, 'at': 1})
        self.assertIn('one: revision r1@', err)
        rc, out, _ = H.run_tool('viewedit', self.page, '--get')
        self.assertEqual(json.loads(out)['one']['state']['groups'][0]['name'], 'g')
        rc, out, _ = H.run_tool('viewedit', self.page, '--views')
        self.assertRegex(out, r'^one\s+7 signals\s+—\s+edits r1@')
        st = os.path.join(self.d.name, 's.view.json')
        with open(st, 'w', encoding='utf-8') as f:
            json.dump({'wavefw': 'state', 'version': 2, 'title': 't', 'bookmarks': []}, f)
        rc, out, err = H.run_tool('viewedit', st, '--model', self.page, '--ops', '{"op": "bookmark", "t": 5, "signal": "valid"}')
        self.assertEqual(rc, 0, err)
        with open(st, encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'wavefw': 'state', 'version': 3, 'title': 't', 'bookmarks': [{'n': 1, 't': 5, 'signal': 'tb.dut.valid'}],
                                            'arrows': []})
        rc, _, err = H.run_tool('viewedit', os.path.join(H.ROOT, 'docs', 'index.html'), '--get')
        self.assertIn('not a page of mkhtml.py', err)


if __name__ == '__main__':
    unittest.main()
