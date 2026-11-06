"""tools/viewedit.py: the viewer's commands on a state (names, every command, its errors), a page's edits (the block,
revisions), a saved state and the command line. That the browser gets the same state from them as from view.run is
the smoke test's (section edit)."""
import json, os, shutil, re, unittest

from tests.unit import helpers as H
import svabuild
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
        # top: kept as given (a file has no screen to take it from), a row there is (a name: its path); go: the cursor on
        # it, bookmarkLeft of the window from the left, the window within the waves (0 … 80 ns) as view.js clamps it
        e.st.update({'from': 0, 'to': 20000})
        r = self.run_ok(e, {'op': 'bookmark', 'n': 3, 'top': 'tb.dut', 'go': True})[0]
        self.assertEqual((r['t'], r['from'], r['top'], e.st['cursor'], e.st['to']), (60000, 56000, 'tb.dut', 60000, 76000))
        self.assertEqual(e.st['bookmarks'][-1], {'n': 3, 't': 60000, 'color': '#0a0', 'top': 'tb.dut'})
        self.assertEqual(self.run_ok(e, {'op': 'bookmark', 'n': 3, 'top': 'valid'})[0], {'op': 'bookmark', 'n': 3})
        self.assertEqual(e.st['bookmarks'][-1]['top'], 'tb.dut.valid')
        self.assertEqual([self.run_ok(e, {'op': 'bookmark', 'n': 3, 't': t, 'go': True})[0]['from'] for t in (0, 80000, 30000)], [0, 60000, 26000])
        got = []
        for x in (0.5, None, '', 'abc', -1, 5, 'Infinity', '0.5'):   # as view.js goBm: not a number 0.2, else within 0 … 0.9
            e.st['config'] = {'bookmarkLeft': x}
            got.append(self.run_ok(e, {'op': 'bookmark', 'n': 3, 'go': True})[0]['from'])
        self.assertEqual(got, [20000, 26000, 26000, 26000, 30000, 12000, 26000, 20000])
        self.assertIn("top: a row's path", e.run([{'op': 'bookmark', 'n': 3, 'top': 5}])[0]['error'])
        self.assertEqual(e.run([{'op': 'bookmark', 'n': 3, 'top': 'no.such'}])[0]['error'], 'no signal or module "no.such"')
        self.run_ok(e, {'op': 'bookmark', 'n': 'all', 'delete': True})
        self.assertEqual((e.st['bookmarks'], e.st['arrows']), ([], []))

    def test_label_lift_below_spans(self):
        e = ed()
        self.run_ok(e, {'op': 'bookmark', 'n': 1, 'label': 'ok', 'lift': 'below'}, {'op': 'bookmark', 't': '40ns', 'lift': 'below'},
                    {'op': 'span', 'from': '50ns', 'to': '20ns', 'label': 'A', 'color': 'c7'}, {'op': 'span', 'from': 0, 'to': 10000, 'signals': 'valid'},
                    {'op': 'span', 'id': 1, 'label': 'phase'})
        self.assertEqual(e.st['bookmarks'][0], {'n': 1, 't': 20000, 'signal': 'tb.dut.valid', 'label': 'ok', 'text': 'page own', 'lift': 'below'})
        self.assertNotIn('lift', e.st['bookmarks'][1])   # no signal: on the axis, not lifted
        self.assertEqual(e.st['spans'], [{'from': 20000, 'to': 50000, 'label': 'phase', 'color': 'c7'}, {'from': 0, 'to': 10000, 'signals': ['tb.dut.valid']}])
        bad = e.run([{'op': 'bookmark', 'n': 1, 'lift': 'up'}, {'op': 'span', 'from': 1}, {'op': 'span', 'id': 9, 'label': 'x'}, {'op': 'span', 'id': 'all'}])
        self.assertEqual([r['error'] for r in bad], ['lift: true, "above", "below" or false, not "up"', 'span: from and to', 'no span 9 (there are 2)',
                                                     'span: id "all" is for delete (a new one: no id)'])
        self.run_ok(e, {'op': 'span', 'id': 'all', 'delete': True})
        self.assertEqual(e.st['spans'], [])
        # an old bookmark with "to": its label is the arrow's, not the bookmark's
        self.assertEqual([b['label'] for b in V.bm_norm([{'n': 1, 't': 1, 'to': 2, 'label': 'Δ'}, {'n': 2, 't': 2, 'label': 'mine'}])], ['', 'mine'])
        self.assertEqual(V.ar_norm([], [{'n': 1, 't': 1, 'to': 2, 'label': 'Δ'}])[0]['label'], 'Δ')
        self.assertEqual(V.span_norm([{'from': '5ns', 'to': 1000, 'signals': 'x'}, {'from': 'x', 'to': 1}, 3]), [{'from': 1000, 'to': 5000, 'label': '',
                                                                                                           'color': None, 'signals': ['x']}])

    def test_link(self):
        e = ed()
        self.run_ok(e, {'op': 'bookmark', 'n': 1, 'link': 'crc'}, {'op': 'bookmark', 't': 1, 'link': {'view': 'gap', 'bookmark': '2'}})
        self.assertEqual([b.get('link') for b in e.st['bookmarks']], [{'view': 'crc'}, {'view': 'gap', 'bookmark': 2}])
        self.assertIn('link: a view', e.run([{'op': 'bookmark', 'n': 1, 'link': 5}])[0]['error'])
        self.run_ok(e, {'op': 'bookmark', 'n': 1, 'link': None})
        self.assertNotIn('link', e.st['bookmarks'][0])

    def test_bookmark_at_kept_until_moved(self):
        # "at": the event a bookmark's time came from (mkhtml.py): kept by the other edits, dropped when its time moves
        doc = {**DOC, 'bookmarks': [{'n': 1, 't': 20000, 'at': {'signal': 'valid', 'edge': 'rise'}, 'signal': 'tb.dut.valid'}]}
        e = ed(doc=doc)
        self.run_ok(e, {'op': 'bookmark', 'n': 1, 'text': 'rise', 'color': '#0a0'})
        self.assertEqual(e.st['bookmarks'][0]['at'], {'signal': 'valid', 'edge': 'rise'})
        self.run_ok(e, {'op': 'bookmark', 'n': 1, 't': '30ns'})
        self.assertNotIn('at', e.st['bookmarks'][0])
        self.assertEqual(V.bm_norm([{'n': 1, 't': 5, 'at': 5}])[0].get('at'), None)   # an event is a text or an object

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
        self.assertEqual({k: st['config'][k] for k in V.ALL_GAP_KEYS}, V.GAP_DEFAULTS)   # the page's own (no override), not null
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
        st = {'wavelens': 'state', 'version': 3, 'bookmarks': [{'n': 4, 't': 7}], 'paint': {'gone': '#fff'}}
        r = self.run_ok(e, {'op': 'set_state', 'state': st}, {'op': 'state'})
        self.assertEqual((r[0]['missing'], r[1]['state']), (['gone'], {'cursor': 1.5, 'bookmarks': [{'n': 4, 't': 7}], 'paint': {'gone': '#fff'}}))
        self.assertEqual(e.run([{'op': 'set_state', 'state': [1]}])[0]['error'], 'set_state: not a saved viewer state ({"wavelens": "state", …})')
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

    def test_only(self):
        """Only (modules.js setOnly): modules by name (not a signal, not a struct's value), in the model's order, one under
        another picked left out; the way to them as headers, their signals gone; pause, resume, clear; a selection it
        leaves out goes; the state's own names said when they are not modules here."""
        e = ed()
        r = e.run([{'op': 'only', 'modules': ['other', 'tb', 'dut']}])[0]
        self.assertEqual(r['only'], {'modules': ['tb'], 'on': True})                       # dut and other under tb: in it
        r = e.run([{'op': 'only', 'modules': ['other', 'dut']}, {'op': 'select', 'signal': 'clk'}, {'op': 'only'}])
        self.assertEqual(r[0]['only']['modules'], ['tb.dut', 'tb.other'])
        self.assertIsNone(r[1]['select'])                                               # clk: above every module
        self.assertEqual(r[2]['only'], {'modules': ['tb.dut', 'tb.other'], 'on': True})  # none given: as it is
        e.run([{'op': 'only', 'modules': 'dut'}])
        self.assertEqual([x['full'] for x in e.ordered() if x['type'] != 'space'], ['tb', 'tb.dut', 'tb.dut.state', 'tb.dut.valid', 'tb.dut.data'])
        self.assertEqual(len(e.ordered(only=False)), len(e.ordered()) + 6)              # clk, tb.other and its rows: back without it
        self.assertEqual([x['full'] for x in e.found('state')], ['tb.dut.state'])
        self.assertEqual(e.run([{'op': 'only', 'on': False}])[0]['only'], {'modules': ['tb.dut'], 'on': False})
        self.assertEqual([x['full'] for x in e.found('state')], ['tb.dut.state', 'tb.other.state'])
        bad = e.run([{'op': 'only', 'modules': 'reg'}, {'op': 'only', 'modules': 'valid'}, {'op': 'only', 'modules': None}])
        self.assertEqual([x['error'][:22] for x in bad], ['no module "reg"', 'no module "valid"', 'modules: a list of mod'])
        self.assertEqual(e.st['only'], {'modules': ['tb.dut'], 'on': False})            # the bad ones changed nothing
        self.assertEqual(e.run([{'op': 'only', 'modules': []}])[0]['only'], {'modules': [], 'on': True})   # none kept: not every module
        self.assertEqual(e.run([{'op': 'only', 'clear': True}])[0]['only'], None)
        self.assertIn('no set to pause', e.run([{'op': 'only', 'on': True}])[0]['error'])
        e.run([{'op': 'select', 'signal': 'tb.other.state'}])
        miss = e.run([{'op': 'set_state', 'state': {'wavelens': 'state', 'only': {'modules': ['tb.dut', 'tb.nope', 'tb.other.reg']}}}])[0]
        self.assertEqual(miss['missing'], ['tb.nope', 'tb.other.reg'])
        self.assertEqual(e.st['only'], {'modules': ['tb.dut'], 'on': True})            # kept as the viewer keeps it
        self.assertIsNone(e.st['select'])                                               # a selection it leaves out goes
        # the modules named open with the ones above them (nested ones too), open false: the folding as it is
        f = ed()
        f.run([{'op': 'fold', 'all': True}, {'op': 'only', 'modules': ['tb.dut'], 'open': False}])
        self.assertEqual(f.fold(), ['tb', 'tb.dut', 'tb.other', 'tb.other.reg'])
        f.run([{'op': 'find', 'query': 'state', 'open': True}, {'op': 'only', 'modules': ['tb', 'tb.dut']}])
        self.assertEqual(f.fold(), ['tb.other', 'tb.other.reg'])
        self.assertIs(f.st['config']['findOpen'], False)                                # the find's Open off
        f.run([{'op': 'fold', 'all': True}, {'op': 'only', 'on': False}, {'op': 'only', 'on': True}])
        self.assertEqual(len(f.fold()), 4)                                              # pause, resume: no folding
        # many modules: one pass over the rows (not a pass over the modules per row)
        big = {'signal': [['top'] + [[f'm{i}', {'name': 'a', 'wave': '01'}] for i in range(4000)]]}
        b = ed(doc=big)
        b.run([{'op': 'only', 'modules': 'm7'}])
        t0 = __import__('time').perf_counter()
        self.assertEqual([x['full'] for x in b.ordered()], ['top', 'top.m7', 'top.m7.a'])
        self.assertLess(__import__('time').perf_counter() - t0, 1.0)
        # your groups whole under Only (onlyGroups): every signal of them; groups false: by the signal each shows; kept with no set too
        e.run([{'op': 'group', 'name': 'g', 'signals': ['clk', 'tb.dut.valid']}])
        self.assertEqual([x['full'] for x in e.ordered()[:4]], ['@g', 'clk', 'tb.dut.valid', 'tb'])
        r = e.run([{'op': 'only', 'groups': False}])[0]
        self.assertEqual((r['only'], r['groups']), ({'modules': ['tb.dut'], 'on': True, 'groups': False}, False))
        self.assertEqual([x['full'] for x in e.ordered()[:3]], ['@g', 'tb.dut.valid', 'tb'])
        r = e.run([{'op': 'only', 'clear': True}, {'op': 'only', 'modules': 'dut'}])
        self.assertEqual(r[1]['only'], {'modules': ['tb.dut'], 'on': True, 'groups': False})   # cleared: the next set takes it
        self.assertEqual(e.run([{'op': 'only', 'groups': True}])[0]['only'], {'modules': ['tb.dut'], 'on': True})   # the setting's: left out
        p = ed(settings={'onlyGroups': False})
        p.run([{'op': 'group', 'name': 'g', 'signals': ['clk', 'tb.dut.valid']}, {'op': 'only', 'modules': 'dut'}])
        self.assertEqual([x['full'] for x in p.ordered()[:3]], ['@g', 'tb.dut.valid', 'tb'])    # the page's setting off
        self.assertEqual(p.run([{'op': 'only', 'groups': True}])[0]['only'], {'modules': ['tb.dut'], 'on': True, 'groups': True})

    def test_exprs(self):
        """The list of expressions: as sva.js writes it (a text alone only when it draws its row), the page's first; no evaluation here."""
        e = ed()
        self.run_ok(e, {'op': 'expr', 'text': ' a && b; ', 'label': 'one', 'color': '#c00'}, {'op': 'expr', 'text': '@(posedge clk)\n  c', 'row': True, 'mark': 'line'},
                    {'op': 'expr', 'text': 'd', 'on': False, 'row': True, 'scope': 'tb.dut'})
        self.assertEqual(e.st['exprs'], [{'expr': 'a && b', 'label': 'one', 'color': '#c00', 'row': False}, {'expr': '@(posedge clk)\n  c', 'mark': 'line'},
                                         {'expr': 'd', 'scope': 'tb.dut', 'on': False}])
        self.run_ok(e, {'op': 'expr', 'id': 1, 'label': None, 'color': None, 'row': True}, {'op': 'expr', 'id': 2, 'mark': 'band'}, {'op': 'expr', 'id': 3, 'on': True, 'scope': ''})
        self.assertEqual(e.st['exprs'], ['a && b', '@(posedge clk)\n  c', 'd'])   # as the defaults: a text alone
        bad = e.run([{'op': 'expr', 'text': 'a && b'}, {'op': 'expr', 'id': 1, 'text': 'd'}, {'op': 'expr', 'text': ' ; '}, {'op': 'expr', 'id': 9, 'on': False},
                     {'op': 'expr', 'id': 'all', 'on': False}, {'op': 'expr', 'delete': True}, {'op': 'expr', 'text': 'x', 'mark': 'zigzag'}, {'op': 'expr', 'text': 'x', 'nope': 1}])
        self.assertTrue(all('error' in r for r in bad), bad)
        self.assertIn('there already (id 1)', bad[0]['error'])
        self.assertIn('band, line, strip', bad[6]['error'])
        self.assertEqual(len(e.st['exprs']), 3)
        for op in ({'op': 'expr_go', 'id': 1}, {'op': 'expr_matches'}):
            self.assertIn('runs in the page only', e.run([op])[0]['error'])
        self.run_ok(e, {'op': 'expr', 'id': 2, 'delete': True})
        self.assertEqual(e.st['exprs'], ['a && b', 'd'])
        self.run_ok(e, {'op': 'expr', 'id': 'all', 'delete': True})
        self.assertEqual(e.st['exprs'], [])

    def test_expr_new_text_keeps_its_look(self):
        """Review S21-2: a row ƒ's radix and analog go with its expression's new text, as sva.js moves them."""
        e = ed()
        self.run_ok(e, {'op': 'expr', 'text': 'a + b', 'row': True, 'radix': 'bin', 'analog': 3}, {'op': 'expr', 'id': 1, 'text': 'a - b'})
        self.assertEqual((e.st.get('radix'), e.st.get('analog')), ({'ƒ a - b': 'bin'}, {'ƒ a - b': 3}))

    def test_duplicate_bits_refused_makes_none(self):
        """Review S22-2: a bus and a bit sliced together: the page's error, no slice in the state."""
        e = ed()
        r = e.run([{'op': 'duplicate', 'signals': ['tb.dut.data', 'clk'], 'bits': [7, 4]}])[0]
        self.assertEqual((r.get('error'), e.st.get('dups')), ('clk: not a bus', None))

    def test_bounds_spans_dividers(self):
        """Review S16-3, S26-5, S26-6: dmin over dmax refused, two markers at one time no Δ row; a span of no length refused (a reversed one
        swapped); a divider: no signals, kept as one."""
        e = ed()
        r = e.run([{'op': 'marker', 't': '10ns', 'dmin': '100ns', 'dmax': '10ns'}, {'op': 'marker', 't': '10ns'}, {'op': 'marker', 't': '10ns'},
                   {'op': 'measures'}, {'op': 'span', 'from': '20ns', 'to': '20ns'}, {'op': 'span', 'from': '40ns', 'to': '20ns'},
                   {'op': 'group', 'name': '— D —', 'divider': True}, {'op': 'group', 'name': 'x', 'divider': True, 'signals': 'clk'}])
        self.assertIn('over dmax', r[0]['error'])
        self.assertEqual(r[3]['measures'], [])
        self.assertIn('no stretch', r[4]['error'])
        self.assertEqual([(x['from'], x['to']) for x in e.st['spans']], [(20000, 40000)])
        self.assertEqual((e.st['groups'], 'no signals' in r[7].get('error', '')), ([{'name': '— D —', 'signals': [], 'divider': True}], True))

    def test_expr_gap(self):
        """The waves cut to the matches of expressions, as sva.js and look.js setGaps: on while one has gap, your settings apart, the gaps off end it."""
        e = ed()
        self.run_ok(e, {'op': 'expr', 'text': 'a', 'gap': True}, {'op': 'expr', 'text': 'b'}, {'op': 'expr', 'id': 2, 'gap': True}, {'op': 'expr', 'text': 'c', 'gap': False})
        self.assertEqual(e.st['exprs'], [{'expr': 'a', 'row': False, 'gap': True}, {'expr': 'b', 'row': False, 'gap': True}, {'expr': 'c', 'row': False}])
        g = e.run([{'op': 'gaps', 'on': True, 'view': True, 'idle': 4}])[0]['gaps']
        self.assertEqual((g['gaps'], g['gapView'], g['gapBy'], g['gapIdle']), (True, True, [1, 2], 4))
        self.assertNotIn('gaps', e.st['config'])     # on by them, not your setting
        self.assertNotIn('gapView', e.st['config'])
        self.assertEqual(e.run([{'op': 'expr', 'id': 1, 'gap': False}, {'op': 'gaps'}])[1]['gaps']['gapBy'], [2])
        g = e.run([{'op': 'gaps', 'view': False}])[0]['gaps']
        self.assertEqual((g['gaps'], g['gapView'], 'gapBy' in g), (False, False, False))
        self.assertEqual([x if isinstance(x, str) else x.get('gap') for x in e.st['exprs']], [None, None, None])
        self.run_ok(e, {'op': 'expr', 'id': 1, 'gap': True})
        self.assertTrue(e.run([{'op': 'gaps'}])[0]['gaps']['gapView'])
        self.assertNotIn('gapBy', e.run([{'op': 'gaps', 'on': False}])[0]['gaps'])
        self.run_ok(e, {'op': 'expr', 'id': 2, 'gap': True})
        self.assertNotIn('gapBy', e.run([{'op': 'gaps', 'reset': True}])[0]['gaps'])

    def test_marker_lanes(self):
        """A marker's text on the line of a signal: signal, lift, as view.js markList says them; pale by default."""
        e = ed()
        self.run_ok(e, {'op': 'marker', 't': 5, 'label': 'a', 'signal': 'tb.dut.valid'}, 
                    {'op': 'marker', 't': 6, 'signal': 'tb.dut.valid', 'lift': 'below'}, {'op': 'marker', 't': 7})
        self.assertEqual(e.st['markers'], [{'t': 5, 'label': 'a', 'signal': 'tb.dut.valid'}, {'t': 6, 'signal': 'tb.dut.valid', 'lift': 'below'}, {'t': 7}])
        self.run_ok(e, {'op': 'marker', 'id': 2, 'lift': 'above'}, {'op': 'marker', 'id': 1, 'lift': 'below', 'color': 'red'}, {'op': 'marker', 'id': 1, 'color': None})
        self.assertEqual(e.st['markers'][:2], [{'t': 5, 'label': 'a', 'signal': 'tb.dut.valid', 'lift': 'below'}, {'t': 6, 'signal': 'tb.dut.valid'}])
        self.run_ok(e, {'op': 'marker', 'id': 1, 'signal': None})   # at the top again: no lift left behind
        self.assertEqual(e.st['markers'][0], {'t': 5, 'label': 'a'})
        n = len(e.st['markers'])
        bad = e.run([{'op': 'marker', 't': 1, 'lift': 'below'}, {'op': 'marker', 'id': 3, 'lift': 'below'}, {'op': 'marker', 't': 1, 'signal': 'tb.dut.valid', 'lift': 'sideways'},
                     {'op': 'marker', 't': 1, 'signal': 'nosuch'}, {'op': 'marker', 't': 1, 'signal': 'tb.dut.valid', 'lift': False}])
        self.assertTrue(all('error' in r for r in bad), bad)
        self.assertIn('give signal', bad[0]['error'])
        self.assertEqual(len(e.st['markers']), n)   # nothing made of them


class Twin(unittest.TestCase):
    """What edit.js does, the same here (review 2026-10-22: A9/B4, M4, B13, B14, B15)."""

    def test_set_state_merges(self):
        """set_state as view.js setState: a key the state has replaces this one's (config key by key), a key it does not
        have stays, null clears."""
        e = ed()
        r = e.run([{'op': 'bookmark', 't': '60ns', 'signal': 'valid', 'text': 'a'}, {'op': 'style', 'name': 'questa'}, {'op': 'cursor2', 't': 30000},
                   {'op': 'range', 'from': 10000, 'to': 20000},
                   {'op': 'set_state', 'state': {'wavelens': 'state', 'cursor': 70000, 'config': {'sort': 'asc'}, 'range': None, 'cursor2': None}}])
        self.assertEqual(r[-1], {'op': 'set_state', 'missing': []})
        st = e.st
        self.assertEqual([b['n'] for b in st['bookmarks']], [1, 2])   # kept
        self.assertEqual(st['config'], {'style': 'questa', 'sort': 'asc'})
        self.assertEqual((st['cursor'], st['cursor2'], st['range']), (70000, None, None))
        e.run([{'op': 'set_state', 'state': {'wavelens': 'state', 'config': None, 'title': 'x', 'version': 3}}])
        self.assertEqual(st['config'], {'style': 'questa', 'sort': 'asc'})   # config null: nothing (as view.js)
        miss = e.run([{'op': 'set_state', 'state': {'wavelens': 'state', 'groups': [{'name': 'g', 'signals': ['clk', 'gone.a']}], 'hidden': ['gone.b'],
                                                    'select': 'gone.c', 'config': {'highlight': ['gone.d', 'x*']}}}])[0]
        self.assertEqual(miss['missing'], ['gone.a', 'gone.d', 'gone.b', 'gone.c'])   # in view.js's order

    def test_gaps_reset(self):
        """gaps reset: the page's own settings (view.js setGaps(null)), not null for each (null: no clock, no signals)."""
        e = ed(settings={'gapIdle': 8})
        r = e.run([{'op': 'gaps', 'on': True, 'idle': 4, 'signals': 'valid'}, {'op': 'gaps', 'reset': True}])
        self.assertEqual(r[0]['gaps'], dict(V.GAP_DEFAULTS, gaps=True, gapIdle=4, gapSignals=['valid'], gapAux=[]))   # every key, as gapOpt
        self.assertEqual(r[1]['gaps'], dict(V.GAP_DEFAULTS, gapIdle=8, gapSignals=[], gapAux=[]))
        self.assertEqual({k: e.st['config'][k] for k in ('gaps', 'gapIdle', 'gapSignals')}, {'gaps': False, 'gapIdle': 8, 'gapSignals': None})

    def test_gaps_view(self):
        """gaps view: gapView in the state as a boolean, as view.js gapOpt says it."""
        e = ed()
        r = e.run([{'op': 'gaps', 'on': True, 'view': 1}, {'op': 'gaps', 'view': False}])
        self.assertIs(r[0]['gaps']['gapView'], True)
        self.assertIs(r[1]['gaps']['gapView'], False)
        self.assertIs(r[1]['gaps']['gaps'], True)

    def test_gap_defaults_are_the_config_files(self):
        with open(os.path.join(H.ROOT, 'wavelens', 'wavelens.config.js'), encoding='utf-8') as f:
            text = f.read()
        js = lambda k: json.loads(re.search(rf'^ {{2}}{k}: ([^,]+),', text, re.M).group(1).replace("'", '"'))
        self.assertEqual({k: js(k) for k in V.GAP_DEFAULTS}, V.GAP_DEFAULTS)
        self.assertEqual({k: js(k) for k in V.CYC_DEFAULTS}, V.CYC_DEFAULTS)

    def test_ids(self):
        """A bookmark's n, an arrow's or a marker's id and an arrow's ends: a whole number (2, 2.0, "2"); true, 1.5, a name:
        an error, nothing made."""
        e = ed()
        ok = e.run([{'op': 'bookmark', 'n': 2.0, 't': 50000}, {'op': 'bookmark', 'n': '3', 't': 60000}, {'op': 'arrow', 'from': 2.0, 'to': '3'},
                    {'op': 'marker', 't': 5000}, {'op': 'marker', 'id': 1.0, 'label': 'm'}, {'op': 'arrow', 'id': 1.0, 'label': 'x'}])
        self.assertEqual([r.get('n') or r.get('id') for r in ok], [2, 3, 1, 1, 1, 1])
        bad = e.run([{'op': 'bookmark', 'n': True, 't': 1}, {'op': 'bookmark', 'n': 1.5, 't': 1}, {'op': 'arrow', 'from': 1.5, 'to': 2},
                     {'op': 'arrow', 'from': 2, 'to': True}, {'op': 'arrow', 'id': True, 'label': 'y'}, {'op': 'marker', 'id': 1.5},
                     {'op': 'marker', 'id': 'all', 't': '50ns'}])
        self.assertEqual([r['error'] for r in bad], ['n: a bookmark number (1, 2 …)', 'n: a bookmark number (1, 2 …)',
                                                     'from: a bookmark number (1, 2 …), not 1.5', 'to: a bookmark number (1, 2 …), not true',
                                                     'id: the number of the arrow as listed (1, 2 …), not true; a new one: no id',
                                                     'id: the number of the marker as listed (1, 2 …), not 1.5; a new one: no id',
                                                     'marker: id "all" goes with delete (every marker deleted); one to change: its number'])
        self.assertEqual((len(e.st['markers']), len(e.st['arrows']), [b['n'] for b in e.st['bookmarks']]), (1, 1, [1, 2, 3]))
        self.assertEqual(e.run([{'op': 'analog', 'signals': 'data', 'rows': 2.0}])[0], {'op': 'analog', 'signals': 1})
        self.assertEqual(e.st['analog'], {'tb.dut.data': 2})

    def test_range_outside(self):
        """A range is cut to the waves (view.js setRange); one wholly outside them is an error."""
        e = ed()
        self.assertEqual(e.run([{'op': 'range', 'from': '-10ns', 'to': '30ns'}])[0]['range'], [0, 30000])
        bad = e.run([{'op': 'range', 'from': '1ms', 'to': '2ms'}, {'op': 'range', 'from': -5000, 'to': -1000}])
        self.assertEqual(bad[0]['error'], 'range: 1 ms … 2 ms is outside these waves (0 ps … 80 ns)')   # as edit.js (review 2026-11-05 B-21)
        self.assertIn('outside these waves', bad[1]['error'])
        self.assertEqual(e.st['range'], {'from': 0, 'to': 30000, 'signal': None})

    def test_result_shapes(self):
        """layout, find, cycles answer what edit.js answers."""
        e = ed()
        r = e.run([{'op': 'layout', 'height': 400}, {'op': 'layout', 'scroll': 'page', 'tools': 'fold'}, {'op': 'find', 'query': 'dut.st'},
                   {'op': 'find', 'query': 'val|clk', 'regex': True}, {'op': 'find', 'query': 'state', 'word': True, 'regex': False},
                   {'op': 'cycles', 'on': True}])
        self.assertEqual(r[0], {'op': 'layout', 'scroll': 'window', 'height': 400, 'tools': 'open'})
        self.assertEqual(r[1], {'op': 'layout', 'scroll': 'page', 'height': None, 'tools': 'fold'})
        pl = {'plugins': V.Editor(V.Model()).run([{'op': 'find', 'query': 'x'}])[0]['plugins']}   # (the plugins' rows: not counted, B-19)
        self.assertEqual(r[2], {'op': 'find', 'found': ['tb.dut.state'], 'count': 1, **pl})
        self.assertEqual(r[3], {'op': 'find', 'found': ['clk', 'tb.dut.valid'], 'count': 2, **pl})
        self.assertEqual(r[4], {'op': 'find', 'found': ['tb.dut.state', 'tb.other.state'], 'count': 2, **pl})
        self.assertIn('not counted', pl['plugins'])
        self.assertEqual(r[5], {'op': 'cycles', 'cycles': {'cycles': True, 'cycleClock': None, 'cycleZero': None}, 'clock': 'clk', 'cycle': None})

    def test_rows_order(self):
        """rows in the order the names column shows them (sort, ignored prefixes), your groups first, the hidden where they would be (edit.js:
        allRows(true); review 2026-11-03 B-14)."""
        doc = {'signal': [{'name': 'b10', 'wave': '01'}, {'name': 'i_b2', 'wave': '01'}, {'name': 'a', 'wave': '01'}, ['m', {'name': 'z', 'wave': '0'}]]}
        e = ed(doc=doc)
        r = e.run([{'op': 'group', 'name': 'g', 'signals': 'a'}, {'op': 'sort', 'dir': 'asc', 'ignore': 'i_'}, {'op': 'hide', 'signals': 'b10'},
                   {'op': 'rows'}])[-1]
        self.assertEqual(r['rows'], [['@g', 'group'], ['a', 1], ['i_b2', 1], ['b10', 1], ['m', 'module'], ['m.z', 1]])

    def test_times(self):
        """One time parser (model.js parseT) for viewedit.py and wavemcp.py: units in any case, µs, an exponent."""
        for text, ps in (('100NS', 1e5), ('1E2', 100), ('0.1µs', 1e5), (' -5 ns ', -5000), ('2.5us', 2.5e6), ('1e-3ns', 1)):
            self.assertAlmostEqual(V.parse_t(text), ps)
        for text in ('5 parsecs', '1.2.3ns', 'ns', ''):
            self.assertIsNone(V.parse_t(text))
        self.assertEqual(V.parse_time('3', plain=1000), 3000)   # wavemcp.py: a plain number is ns
        self.assertEqual(V.parse_t('3as'), 3e-6)                 # one table: a dump's resolution may be below fs


class Deltas(unittest.TestCase):
    """The Δ between markers on a page that is not open: neighbours in time, the place on the one it starts from."""
    def three(self):
        e = ed()
        for t in ('30ns', '10ns', '60ns'):
            self.assertNotIn('error', e.run([{'op': 'marker', 't': t}])[0])
        return e

    def test_neighbours_in_time(self):
        r = self.three().run([{'op': 'deltas', 'on': True}])[0]
        self.assertEqual((r['on'], r['deltas']), (True, [{'from': 2, 'to': 1, 'dt': 20000}, {'from': 1, 'to': 3, 'dt': 30000}]))

    def pairs(self, e):
        return [(d['from'], d['to'], d['dt']) for d in e.run([{'op': 'deltas'}])[0]['deltas']]

    def test_to_any_marker(self):
        e = self.three()     # 1 at 30, 2 at 10, 3 at 60: in time 2, 1, 3
        self.assertNotIn('error', e.run([{'op': 'deltas', 'id': 2, 'to': 3}])[0])
        self.assertEqual(e.st['markers'][1]['dto'], 3)
        self.assertEqual(self.pairs(e), [(2, 3, 50000), (1, 3, 30000)])
        self.assertNotIn('error', e.run([{'op': 'deltas', 'id': 3, 'to': 2}])[0])
        self.assertEqual(self.pairs(e), [(2, 3, 50000), (1, 3, 30000), (3, 2, 50000)])
        e.run([{'op': 'deltas', 'id': 1, 'to': None}])
        self.assertEqual(e.st['markers'][0]['dto'], 0)
        self.assertEqual(self.pairs(e), [(2, 3, 50000), (3, 2, 50000)])
        e.run([{'op': 'deltas', 'id': 1, 'to': 'next'}, {'op': 'deltas', 'id': 2, 'to': 'next'}, {'op': 'deltas', 'id': 3, 'to': 'next'}])
        self.assertTrue(all('dto' not in m for m in e.st['markers']))

    def test_a_delete_moves_the_numbers(self):
        e = self.three()
        e.run([{'op': 'marker', 't': '70ns'}, {'op': 'deltas', 'id': 1, 'to': 4}, {'op': 'deltas', 'id': 3, 'to': 2}, {'op': 'marker', 'id': 2, 'delete': True}])
        self.assertEqual([m.get('dto') for m in e.st['markers']], [3, None, None])

    def test_hidden_goes_through(self):
        e = self.three()
        self.assertNotIn('error', e.run([{'op': 'marker', 'id': 1, 'hidden': True}])[0])
        self.assertIs(e.st['markers'][0]['hidden'], True)
        self.assertEqual(self.pairs(e), [(2, 3, 50000)])
        self.assertIn('no Δ', e.run([{'op': 'deltas', 'id': 1, 'signal': 'tb.dut.data'}])[0]['error'])
        e.run([{'op': 'deltas', 'id': 2, 'to': 1}])
        self.assertEqual(self.pairs(e), [])
        e.run([{'op': 'marker', 'id': 1, 'hidden': False}])
        self.assertNotIn('hidden', e.st['markers'][0])
        self.assertEqual(self.pairs(e), [(2, 1, 20000), (1, 3, 30000)])

    def test_a_colour(self):
        e = self.three()
        e.run([{'op': 'deltas', 'id': 1, 'color': '#112233'}])
        self.assertEqual(e.st['markers'][0]['dcolor'], '#112233')
        e.run([{'op': 'deltas', 'id': 1, 'color': None}])
        self.assertNotIn('dcolor', e.st['markers'][0])

    def test_a_place_on_a_line(self):
        e = self.three()
        self.assertNotIn('error', e.run([{'op': 'deltas', 'id': 1, 'signal': 'tb.dut.data', 'lift': 'below'}])[0])
        self.assertEqual((e.st['markers'][0]['dsignal'], e.st['markers'][0]['dlift']), ('tb.dut.data', 'below'))
        self.assertNotIn('error', e.run([{'op': 'deltas', 'id': 1, 'signal': None}])[0])
        self.assertNotIn('dsignal', e.st['markers'][0])
        self.assertNotIn('dlift', e.st['markers'][0])

    def test_what_it_refuses(self):
        e = self.three()
        err = lambda **a: e.run([{'op': 'deltas', **a}])[0]['error']
        self.assertEqual(err(on='yes'), 'on: true or false')
        self.assertEqual(err(signal='clk'), 'deltas: to, signal, lift and color go with id')
        self.assertTrue(err(id=9).startswith('no marker 9'))
        self.assertEqual(err(id=3), 'marker 3: no Δ from it (the last in time, hidden, or none set)')
        self.assertEqual(err(id=1, to=1), 'deltas: to is the marker it starts from')
        self.assertTrue(err(id=1, to=9).startswith('to: a marker as listed'))
        self.assertTrue(err(id=1, to=True).startswith('to: a marker as listed'))
        self.assertEqual(err(to=1), 'deltas: to, signal, lift and color go with id')
        self.assertEqual(err(id=1, lift='below'), 'deltas: lift is the lane of a signal: give signal')

    def test_a_copy_gone_leaves_the_line_to_its_signal(self):
        e = self.three()
        e.run([{'op': 'duplicate', 'signals': 'tb.dut.data'}, {'op': 'deltas', 'id': 1, 'signal': 'tb.dut.data#2'}, {'op': 'duplicate', 'signals': 'tb.dut.data', 'delete': True}])
        self.assertEqual(e.st['markers'][0]['dsignal'], 'tb.dut.data')


class Duplicate(unittest.TestCase):
    """A signal's copy without a browser: the commands of the viewer on a page that is not open."""
    def run_ok(self, e, *ops):
        out = e.run(list(ops))
        for o in out:
            self.assertNotIn('error', o, o)
        return out

    def test_a_copy_is_a_row_under_its_signal(self):
        e = ed()
        r = self.run_ok(e, {'op': 'duplicate', 'signals': 'tb.dut.data'})[0]
        self.assertEqual(r['copies'], ['tb.dut.data#2'])
        self.assertEqual(e.st['dups'], ['tb.dut.data#2'])
        rows = [x[0] for x in e.run([{'op': 'rows', 'limit': 100}])[0]['rows']]
        self.assertEqual(rows[rows.index('tb.dut.data') + 1], 'tb.dut.data#2')

    def test_every_command_names_it(self):
        e = ed()
        self.run_ok(e, {'op': 'duplicate', 'signals': 'tb.dut.data', 'radix': 'dec', 'rows': 2}, {'op': 'radix', 'signals': 'tb.dut.data#2', 'radix': 'bin'},
                    {'op': 'paint', 'signals': 'tb.dut.data#2', 'color': '#123456'}, {'op': 'hide', 'signals': 'tb.dut.data#2'}, {'op': 'show', 'signals': 'tb.dut.data#2'},
                    {'op': 'bookmark', 't': '5ns', 'signal': 'tb.dut.data#2'}, {'op': 'group', 'name': 'g', 'signals': ['tb.dut.data#2']})
        self.assertEqual((e.st['radix'], e.st['analog']), ({'tb.dut.data#2': 'bin'}, {'tb.dut.data#2': 2}))
        self.assertEqual(e.missing(e.st), [])

    def test_it_starts_as_that_row_looks(self):
        e = ed()
        self.run_ok(e, {'op': 'radix', 'signals': 'tb.dut.data', 'radix': 'dec'}, {'op': 'duplicate', 'signals': 'tb.dut.data'}, {'op': 'radix', 'signals': 'tb.dut.data#2', 'radix': 'bin'},
                    {'op': 'duplicate', 'signals': 'tb.dut.data#2'})
        self.assertEqual(e.st['radix'], {'tb.dut.data': 'dec', 'tb.dut.data#2': 'bin', 'tb.dut.data#3': 'bin'})

    def test_gone_with_what_was_its(self):
        e = ed()
        self.run_ok(e, {'op': 'duplicate', 'signals': 'tb.dut.data', 'radix': 'dec'}, {'op': 'bookmark', 't': '5ns', 'signal': 'tb.dut.data#2'},
                    {'op': 'marker', 't': '6ns', 'signal': 'tb.dut.data#2'}, {'op': 'select', 'signal': 'tb.dut.data#2'})
        r = self.run_ok(e, {'op': 'duplicate', 'signals': 'tb.dut.data', 'delete': True})[0]
        self.assertEqual(r['deleted'], ['tb.dut.data#2'])
        self.assertEqual((e.st['dups'], e.st['radix'], e.st['bookmarks'][-1]['signal'], e.st['markers'][-1]['signal'], e.st['select']),
                         ([], {}, 'tb.dut.data', 'tb.dut.data', 'tb.dut.data'))

    def test_what_it_refuses(self):
        e = ed()
        self.assertEqual(e.run([{'op': 'duplicate', 'signals': 'tb.dut.data', 'delete': True}])[0]['error'], 'no copies of tb.dut.data')
        self.assertEqual(e.run([{'op': 'duplicate', 'signals': 'clk', 'rows': 3}])[0]['error'], 'not a bus: clk')
        self.assertIn('a bit has no copy', e.run([{'op': 'duplicate', 'signals': 'tb.dut.data[1]'}])[0]['error'])
        self.assertIn('radix: one of', e.run([{'op': 'duplicate', 'signals': 'tb.dut.data', 'radix': 'nope'}])[0]['error'])
        self.assertIn('rows:', e.run([{'op': 'duplicate', 'signals': 'tb.dut.data', 'rows': 'x'}])[0]['error'])
        self.assertFalse(e.st.get('dups'))

    def test_a_state_of_other_waves(self):
        e = ed()
        r = e.run([{'op': 'set_state', 'state': {'wavelens': 'state', 'dups': ['tb.dut.data#2', 'gone#2', 'clk']}}])[0]
        self.assertEqual(e.st['dups'], ['tb.dut.data#2'])
        self.assertEqual(r['missing'], ['gone#2', 'clk'])


class Bits(unittest.TestCase):
    """review 0.31 S1, T1: `bits` without a browser: only a bus, in the order given, off by name, once each."""
    def bits(self, e, signals, **a):
        r = e.run([{'op': 'bits', 'signals': signals, **a}])[0]
        self.assertNotIn('error', r, r)
        return e.st['bits']

    def test_a_scalar_is_not_a_bus(self):
        e = ed()
        self.assertEqual(e.run([{'op': 'bits', 'signals': 'tb.dut.valid'}])[0]['error'], 'not a bus: tb.dut.valid')
        self.assertEqual(e.run([{'op': 'bits', 'signals': 'clk, tb.dut.data'}])[0]['error'], 'not a bus: clk')
        self.assertFalse(e.st.get('bits'))   # none of a list with a scalar in it

    def test_the_order_they_came_in(self):
        e = ed()
        self.bits(e, 'tb.dut.data')
        self.assertEqual(self.bits(e, 'tb.dut.state'), ['tb.dut.data', 'tb.dut.state'])

    def test_off_leaves_the_others(self):
        e = ed()
        self.bits(e, 'tb.dut.data, tb.dut.state')
        self.assertEqual(self.bits(e, 'tb.dut.state', on=False), ['tb.dut.data'])
        self.assertEqual(self.bits(e, 'tb.dut.state', on=False), ['tb.dut.data'])   # off of one that is off: nothing

    def test_repeated_not_doubled(self):
        e = ed()
        self.bits(e, 'tb.dut.data')
        self.assertEqual(self.bits(e, 'tb.dut.data', on=True), ['tb.dut.data'])

    def test_a_field_of_a_struct(self):
        e = ed()
        self.assertEqual(self.bits(e, 'tb.other.reg.hi'), ['tb.other.reg.hi'])   # [7:4] of reg: 4 bits, a bus of its own

    def test_on_is_a_boolean(self):
        self.assertEqual(ed().run([{'op': 'bits', 'signals': 'tb.dut.data', 'on': 'no'}])[0]['error'], 'on: true or false')


class NoBrowser(unittest.TestCase):
    """review 0.31 S1, T2, T3, S8: what smoke's section edit holds through a browser, held by make unit too."""
    def test_the_commands_are_those_of_edit_js(self):
        with open(os.path.join(H.ROOT, 'wavelens', 'src', 'edit.js'), encoding='utf-8') as f:
            text = f.read()
        js = dict(re.findall(r"^command\('(\w+)', '([^']*)'", text, re.M))
        names, args = re.search(r"for \(const \[?name.*?\n\s*command\(name, '([^']*)'()", text).group(0, 1)   # fold, unfold: one call in a loop
        js.update((n, args) for n in re.findall(r"\['(\w+)'", names))
        self.assertEqual(js, V.COMMANDS)

    def test_live_only_are_commands(self):
        self.assertEqual(set(V.LIVE_ONLY) - set(V.COMMANDS), set())
        self.assertEqual(ed().run([{'op': 'fit'}])[0]['error'], 'fit needs the time of the waves: it runs in the page only (live)')

    def test_reset(self):
        e = ed()
        e.run([{'op': 'highlight', 'add': 'tb.dut.data'}, {'op': 'select', 'signal': 'tb.dut.data'}, {'op': 'find', 'query': 'data'},
               {'op': 'range', 'from': '10ns', 'to': '20ns'}, {'op': 'cursor2', 't': '30ns'}, {'op': 'reset'}])
        self.assertEqual((e.st['config']['highlight'], e.st['select'], e.st['find'], e.st['range'], e.st['cursor2']), ([], None, '', None, None))

    def test_unfold_undoes_fold(self):
        e = ed()
        e.run([{'op': 'unfold', 'groups': 'tb.other'}])
        self.assertNotIn('tb.other', e.fold())
        e.run([{'op': 'fold', 'groups': 'tb.other'}])
        self.assertIn('tb.other', e.fold())

    def test_state_round_trip(self):
        e = ed()
        e.run([{'op': 'bookmark', 't': '50ns', 'text': 'here'}, {'op': 'bits', 'signals': 'tb.dut.data'}, {'op': 'hide', 'signals': 'clk'},
               {'op': 'marker', 't': '40ns', 'label': 'm'}, {'op': 'cursor', 't': '30ns'}, {'op': 'radix', 'signals': 'tb.dut.data', 'radix': 'dec'}])
        saved = json.loads(json.dumps(e.run([{'op': 'state'}])[0]['state']))
        saved['wavelens'] = 'state'
        back = ed()
        r = back.run([{'op': 'set_state', 'state': saved}])[0]
        self.assertNotIn('error', r, r)
        self.assertEqual(back.run([{'op': 'state'}])[0]['state'], {k: v for k, v in saved.items() if k != 'wavelens'})


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

    def test_hand_edited_block(self):   # review 0.31 M1, T4
        text = V.put_block(self.text(), 'edits', {'hand': 1})
        put = lambda block: V.write_text(self.page, text.replace('{"hand":1}', block))
        for block in ('null', '{"views": []}', '{"views": {"one": 5}}', '{"views": {"one": {"state": 5}}}'):
            with self.subTest(block):
                put(block)
                with self.assertRaisesRegex(V.WaveError, 'make it again or remove'):
                    V.Page(self.page)
        # a state with a key of another kind: left out, as the viewer does on loading it
        put('{"views": {"one": {"rev": "hand", "state": {"groups": 5, "hidden": "clk", "cursor": "45ns", "config": [], "bookmarks": [{"n": 1, "t": 5}, 7]}}}}')
        res, _, _ = V.edit_page(self.page, [{'op': 'state'}, {'op': 'group', 'name': 'g', 'signals': 'clk'}, {'op': 'unfold', 'all': True}])
        self.assertEqual([r for r in res if 'error' in r], [])
        self.assertEqual(res[0]['state'], {'bookmarks': [{'n': 1, 't': 5}]})

    def test_edits(self):
        res, key, rev = V.edit_page(self.page, [{'op': 'bookmark', 't': '30ns', 'text': 'a </script> b'}])
        self.assertEqual((res, key, rev[:3]), ([{'op': 'bookmark', 'n': 2}], 'one', 'r1@'))
        t = self.text()
        self.assertEqual(t.count('<script type="application/json" id="wavelens-edits">'), 2)   # the block, and the comment in wavelens.js
        self.assertIn('a \\u003c/script> b', t)   # no < in the block: </script> and <!--<script> do not end or swallow it
        self.assertLess(t.index('id="wavelens-edits">{'), t.index('<script>window.WAVELENS_CONFIG'))
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
            json.dump({'wavelens': 'state', 'version': 2, 'title': 't', 'bookmarks': []}, f)
        rc, out, err = H.run_tool('viewedit', st, '--model', self.page, '--ops', '{"op": "bookmark", "t": 5, "signal": "valid"}')
        self.assertEqual(rc, 0, err)
        with open(st, encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'wavelens': 'state', 'version': 3, 'title': 't', 'bookmarks': [{'n': 1, 't': 5, 'signal': 'tb.dut.valid'}],
                                            'arrows': []})
        rc, _, err = H.run_tool('viewedit', os.path.join(H.ROOT, 'docs', 'index.html'), '--get')
        self.assertIn('not a page of mkhtml.py', err)
        old = os.path.join(self.d.name, 'old.html')   # a page from before the rename: refused, not read with no settings
        with open(self.page, encoding='utf-8') as f, open(old, 'w', encoding='utf-8') as g:
            g.write(f.read().replace('window.WAVELENS_CONFIG', 'window.WAVEFW_CONFIG'))
        rc, _, err = H.run_tool('viewedit', old, '--get')
        self.assertNotEqual(rc, 0)
        self.assertIn('before the rename to WaveLens', err)


class Compare(unittest.TestCase):
    def test_row_in_a_dump_as_the_page_finds_it(self):   # review 0.31 C9: one table with cmpFind of diff.js (smoke units)
        for c in H.load(os.path.join(H.ROOT, 'tests', 'unit', 'cmpfind.json')):
            with self.subTest(c['why']):
                tails = {}
                for p in c['paths']:
                    tails.setdefault(p.rsplit('.', 1)[-1], []).append(p)
                self.assertEqual(V.row_hits(c['row'], set(c['paths']), tails, c['scope']), c['hits'])

    """The command compare (stage 14.3.3): a result kept in the edits as the page's state has it, off, refused on clock
    waves; dump on a page's file: sva diff of the page's dump beside it (rows named without their prefix found by it)."""

    def test_result_and_off(self):
        res = {'name': 'b.vcd', 'from': 0, 'to': 80000, 'signals': {'tb.dut.valid': {'spans': [[20000, 40000]]}, 'clk': {'spans': []}}, 'missing': ['tb.dut.data']}
        e = ed()
        self.assertEqual(e.run([{'op': 'compare', 'result': res}])[0], {'op': 'compare', 'name': 'b.vcd', 'compared': 2, 'differ': 1, 'first': None, 'missing': 1})
        self.assertEqual(e.st['compare'], res)
        self.assertEqual(dict(zip(*zip(*[(r[0], r[2:]) for r in e.c_rows({})['rows']])))['tb.dut.valid'], ['≠'])
        self.assertEqual(e.run([{'op': 'compare', 'off': True}])[0], {'op': 'compare', 'off': True})
        self.assertIsNone(e.st['compare'])
        self.assertIn('result, show, dump or off', e.run([{'op': 'compare'}])[0]['error'])
        self.assertIn('compare with a second dump first', e.run([{'op': 'compare', 'show': 'b'}])[0]['error'])
        e.run([{'op': 'compare', 'result': res}])
        self.assertIn('differences only', e.run([{'op': 'compare', 'show': 'b'}])[0]['error'], 'no "vcd" in this result')
        self.assertEqual(e.run([{'op': 'compare', 'show': 'a'}])[0]['show'], 'a')
        self.assertEqual(e.run([{'op': 'compare', 'result': dict(res, vcd='$end'), 'show': 'overlay'}])[0]['show'], 'overlay')
        e.run([{'op': 'compare', 'off': True}])
        self.assertNotIn('compareShow', e.st)
        self.assertIn('a result {name', e.run([{'op': 'compare', 'result': {'signals': []}}])[0]['error'])
        clocked = dict(DOC)
        clocked.pop('time')
        self.assertIn('clock-sampled', ed(doc=clocked).run([{'op': 'compare', 'result': res}])[0]['error'])

    @H.needs(svabuild.find_bin(), 'the sva CLI (make sva-build)')
    def test_dump_on_a_page(self):
        with H.tmp() as d:
            head = '$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 " v $end\n$scope module u $end\n$var wire 1 # v $end\n' \
                   '$upscope $end\n$upscope $end\n$enddefinitions $end\n'
            H.vcd(d, '#0\n0!\n0"\n0#\n#10\n1!\n1"\n#20\n0!\n#30\n', header=head, name='a.vcd')
            H.vcd(d, '#0\n0!\n0"\n0#\n#10\n1!\n#15\n1"\n#20\n0!\n#30\n', header=head, name='b.vcd')
            c, page = os.path.join(d, 'c.json'), os.path.join(d, 'a.html')
            with open(c, 'w', encoding='utf-8') as f:
                json.dump({'waves': 'a.vcd', 'exact': True, 'signals': ['tb.clk', 'tb.v']}, f)
            rc, _, err = H.run_tool('mkhtml', '--config', c, '--out', page, '--no-sva')
            self.assertEqual(rc, 0, err)
            res, key, rev = V.edit_page(page, [{'op': 'compare', 'dump': 'b.vcd'}])
            self.assertEqual(res[0], {'op': 'compare', 'name': 'b.vcd', 'compared': 2, 'differ': 1, 'first': 10000, 'missing': 0}, res)
            st = V.Page(page).state(key)['compare']
            self.assertEqual(st['signals']['v'], {'spans': [[10000, 15000]], 'b': 'tb.v'}, 'v of the page is tb.v, not tb.u.v')
            # the cut of B for the page's A B A+B: the signals that differ only, their values, over the page's window
            self.assertEqual((st['shift'], st['show'] if 'show' in st else None), (0, None))
            self.assertIn('$var wire 1 " v $end', st['vcd'])
            self.assertNotIn('clk', st['vcd'])
            self.assertIn('#15\n1"', st['vcd'])
            res, key, rev = V.edit_page(page, [{'op': 'compare', 'show': 'overlay'}])
            self.assertEqual(res[0], {'op': 'compare', 'show': 'overlay', 'name': 'b.vcd'}, res)
            self.assertEqual(V.Page(page).state(key)['compareShow'], 'overlay')
            self.assertIn('show is a, b, overlay', V.edit_page(page, [{'op': 'compare', 'show': 'c'}])[0][0]['error'])
            self.assertIn('no such file', V.edit_page(page, [{'op': 'compare', 'dump': 'nope.vcd'}])[0][0]['error'])


class Config(unittest.TestCase):
    """bookmark, arrow and span on a view of a config (mkhtml.py's): written into its "views", a rebuild keeps them."""
    CFG = {'waves': H.fixture('names'), 'clock': 'tb.clk', 'signals': 'tb.clk,tb.dut.state', 'note_key': 1,
           'bookmarks': [{'n': 1, 't': '5ns', 'signal': 'tb.clk', 'text': 'top level'}],
           'views': {'a': {'from': '0ns'}, 'b': {'bookmarks': [{'n': 1, 'at': 'posedge tb.clk', 'text': 'first edge'}]}}}

    def test_edits_written_and_built(self):
        with H.tmp() as d:
            c = os.path.join(d, 'c.config.json')
            cfg = {k: v for k, v in self.CFG.items() if k != 'note_key'}
            H.dump(cfg, c, indent=2)
            ops = [{'op': 'bookmark', 'n': 1, 'text': 'the first edge', 'label': 'go'}, {'op': 'bookmark', 't': '25ns', 'signal': 'tb.dut.state'},
                   {'op': 'arrow', 'from': 1, 'to': 2, 'label': '{dt}'}, {'op': 'span', 'from': {'bookmark': 1}, 'to': {'bookmark': 2}, 'label': 'x'}]
            res, view, changed = V.edit_config(c, ops, 'b')
            self.assertEqual((view, changed), ('b', ['views.b.bookmarks', 'views.b.arrows', 'views.b.spans']))
            got = H.load(c)
            self.assertEqual(got['views']['b']['bookmarks'][0], {'n': 1, 'at': 'posedge tb.clk', 'text': 'the first edge', 'label': 'go'})   # its event kept
            self.assertEqual(got['views']['a'], {'from': '0ns'})   # the other view as it was
            self.assertEqual(list(got), list(cfg))
            res, _, changed = V.edit_config(c, [{'op': 'bookmark', 'n': 1, 't': '15ns'}], 'b')   # a t replaces the event
            self.assertNotIn('at', H.load(c)['views']['b']['bookmarks'][0])
            res, _, changed = V.edit_config(c, [{'op': 'bookmark', 'n': 3, 't': '5ns'}, {'op': 'cursor', 't': 1}], 'a')
            self.assertEqual(changed, [])   # a bad command: nothing written
            self.assertIn('give "page"', res[1]['error'])
            self.assertNotIn('bookmarks', H.load(c)['views']['a'])
            V.edit_config(c, [{'op': 'bookmark', 'n': 2, 't': '15ns', 'text': 'mine'}], 'a')   # the top level's become the view's own
            self.assertEqual([b['n'] for b in H.load(c)['views']['a']['bookmarks']], [1, 2])
            for _ in range(2):   # built, and built again: the marks are the config's
                out = os.path.join(d, 'p.html')
                rc, _, err = H.run_tool('mkhtml', '--config', c, '--out', out, '--no-sva', '--reproducible')
                self.assertEqual(rc, 0, err)
                waves = json.loads(re.search(r'window\.WAVES = (\{.*?\n\});', H.text(out), re.S).group(1))
                self.assertEqual(waves['b']['bookmarks'][1]['t'], '25ns')   # as written (the page reads it)
                self.assertEqual(waves['b']['spans'], [{'label': 'x', 'from': 15000, 'to': 25000}])
                self.assertEqual(waves['a']['bookmarks'][1]['text'], 'mine')

    def test_the_look_of_a_view(self):
        """Stage 19: group, radix, hide, marker, deltas, paint … on a config's view: its "state", the page built opens with it (its edits,
        rev cfg-…); view: its window; a bad command in the list: the file as it was, byte for byte."""
        with H.tmp() as d:
            c, out = os.path.join(d, 'c.config.json'), os.path.join(d, 'p.html')
            H.dump({k: v for k, v in self.CFG.items() if k != 'note_key'}, c, indent=2)
            ops = [{'op': 'group', 'name': 'g', 'signals': ['tb.dut.state']}, {'op': 'radix', 'signals': 'tb.dut.state', 'radix': 'dec'},
                   {'op': 'marker', 't': '15ns', 'label': 'm', 'dmax': '5ns'}, {'op': 'deltas', 'on': True}, {'op': 'hide', 'signals': 'tb.clk'},
                   {'op': 'view', 'from': '5ns', 'to': '35ns'}]
            res, view, changed = V.edit_config(c, ops, 'a')
            self.assertFalse([r for r in res if 'error' in r], res)
            self.assertEqual(changed, ['views.a.state', 'views.a.from', 'views.a.to'])
            st = H.load(c)['views']['a']['state']
            self.assertEqual((st['groups'], st['radix'], st['hidden'], st['deltas'], st['markers']),
                             ([{'name': 'g', 'signals': ['tb.dut.state']}], {'tb.dut.state': 'dec'}, ['tb.clk'], True, [{'t': 15000, 'label': 'm', 'dmax': 5000}]))
            before = open(c, 'rb').read()
            res, _, changed = V.edit_config(c, [{'op': 'radix', 'signals': 'tb.clk', 'radix': 'hex'}, {'op': 'radix', 'signals': 'x', 'radix': 'nope'}], 'a')
            self.assertEqual((changed, open(c, 'rb').read() == before), ([], True), 'a bad command: nothing written')
            rc, _, err = H.run_tool('mkhtml', '--config', c, '--out', out, '--no-sva', '--reproducible')
            self.assertEqual(rc, 0, err)
            p = V.Page(out)
            self.assertTrue(str(p.rev('a')).startswith('cfg-'))
            self.assertEqual(p.state('a')['radix'], {'tb.dut.state': 'dec'})
            self.assertEqual(V.Editor(p.model('a'), p.state('a')).run([{'op': 'measures'}])[0]['measures'], [], 'one marker: no Δ')
            # the page's view back into a config: --from-page, --keys
            V.edit_page(out, [{'op': 'paint', 'signals': 'tb.clk', 'color': '#123456'}, {'op': 'marker', 't': '25ns'}], 'a')
            c2 = os.path.join(d, 'c2.config.json')
            H.dump({k: v for k, v in self.CFG.items() if k != 'note_key'}, c2, indent=2)
            res, _, changed = V.edit_config(c2, [], 'a', out, ['markers', 'paint'])
            self.assertEqual((res[0]['taken'], changed), (['markers', 'paint'], ['views.a.state']))
            st = H.load(c2)['views']['a']['state']
            self.assertEqual((sorted(st), [m['t'] for m in st['markers']]), (['markers', 'paint'], [15000, 25000]))
            with self.assertRaisesRegex(V.WaveError, 'no key of a page'):
                V.edit_config(c2, [], 'a', out, ['cursor'])
            with self.assertRaisesRegex(V.WaveError, 'no view "nope"'):   # review S19-1: a view the page has not got is said, not another taken
                V.page_into({}, out, 'nope')

    def test_from_page_keeps_the_config_form(self):
        """Review S19-4: --from-page writes the config's bookmarks / arrows / spans as they were written, a new one with a time "…ns"."""
        apb = os.path.join(os.environ.get('BUILD', os.path.join(H.ROOT, 'out')), 'examples', 'apb', 'apb.html')
        if not os.path.isfile(apb):
            self.skipTest('make examples')
        with H.tmp() as d:
            page, c = os.path.join(d, 'apb.html'), os.path.join(d, 'apb.config.json')
            shutil.copy(apb, page)
            shutil.copy(os.path.join(H.ROOT, 'examples', 'apb', 'apb.config.json'), c)
            before = H.load(c)['views']['transfers']
            V.edit_page(page, [{'op': 'bookmark', 't': '170ns', 'text': 'new one'}], 'transfers')
            V.edit_config(c, [], 'transfers', page, ['bookmarks', 'arrows', 'spans'])
            after = H.load(c)['views']['transfers']
        self.assertEqual(after['bookmarks'][:-1], before['bookmarks'])
        self.assertEqual(after['bookmarks'][-1], {'n': 7, 'text': 'new one', 't': '170ns'})
        self.assertEqual((after['arrows'], after.get('spans')), (before['arrows'], before.get('spans')))

    def test_mcp_view_edit_config(self):
        import wavemcp
        with H.tmp() as d:
            c = os.path.join(d, 'c.config.json')
            H.dump({k: v for k, v in self.CFG.items() if k != 'note_key'}, c)
            text, err = wavemcp.call('view_edit', {'config': c, 'view': 'b', 'ops': [{'op': 'bookmark', 't': 35, 'text': 'ns from the agent'}]})
            self.assertFalse(err, text)
            self.assertEqual(H.load(c)['views']['b']['bookmarks'][1]['t'], '35ns')   # its ns as a time with a unit
            text, err = wavemcp.call('view_edit', {'config': c, 'page': c, 'ops': [{'op': 'bookmark', 't': 1}]})
            self.assertTrue(err)

class Slices(unittest.TestCase):
    """Stage 22: duplicate bits: a slice of a bus as a row, "data[7:4]"; its radix; the forms and what is refused."""
    def test_slices(self):
        e = ed()
        r = e.run([{'op': 'duplicate', 'signals': 'tb.dut.data', 'bits': [7, 4], 'radix': 'bin'}, {'op': 'duplicate', 'signals': 'tb.dut.data', 'bits': ' 3 : 0 '},
                   {'op': 'duplicate', 'signals': 'tb.dut.data', 'bits': [7, 4]}])
        self.assertEqual([x.get('copies') for x in r], [['tb.dut.data[7:4]'], ['tb.dut.data[3:0]'], ['tb.dut.data[7:4]']])
        self.assertEqual((e.st['dups'], e.st['radix']), (['tb.dut.data[7:4]', 'tb.dut.data[3:0]'], {'tb.dut.data[7:4]': 'bin'}))
        bad = e.run([{'op': 'duplicate', 'signals': 'tb.dut.data', 'bits': [8, 0]}, {'op': 'duplicate', 'signals': 'tb.dut.data', 'bits': [2, 5]},
                     {'op': 'duplicate', 'signals': 'tb.dut.valid', 'bits': [0, 0]}, {'op': 'duplicate', 'signals': 'tb.dut.data[7:4]', 'bits': [1, 0]},
                     {'op': 'duplicate', 'signals': 'tb.dut.data', 'bits': 'x'}])
        self.assertEqual([('not in its 8 bits' in b.get('error', ''), 'not in' in b.get('error', ''), 'not a bus' in b.get('error', ''),
                           'not a slice' in b.get('error', ''), 'msb, lsb' in b.get('error', ''))[i] for i, b in enumerate(bad)], [True] * 5)
        self.assertEqual(e.run([{'op': 'duplicate', 'signals': 'tb.dut.data[7:4]', 'delete': True}])[0]['deleted'], ['tb.dut.data[7:4]'])
        self.assertEqual(e.st['dups'], ['tb.dut.data[3:0]'])


class Measures(unittest.TestCase):
    """Stage 16: a bound on a marker's Δ (dmin, dmax: a time or cycles), the measures table, --measure / --csv."""
    def three(self):
        e = ed()
        for t in ('10ns', '30ns', '60ns'):
            e.run([{'op': 'marker', 't': t, 'label': 'm' + t}])
        return e

    def test_bound_forms(self):
        for x, want in (('150ns', 150000), (2000, 2000), ('3 cycles', {'cycles': 3}), ('1 cycle', {'cycles': 1}), ({'cycles': 4}, {'cycles': 4}),
                        ('fast', None), (True, None), (-5, None), ({'cycles': -1}, None), (None, None)):
            self.assertEqual(V.bound_of(x), want, x)

    def test_marker_and_deltas_bounds(self):
        e = self.three()
        self.assertNotIn('error', e.run([{'op': 'marker', 'id': 1, 'dmax': '15ns'}])[0])
        self.assertEqual(e.st['markers'][0]['dmax'], 15000)
        self.assertIn('not "fast"', e.run([{'op': 'marker', 'id': 1, 'dmin': 'fast'}])[0]['error'])
        self.assertIn('error', e.run([{'op': 'marker', 'dmin': 'fast'}])[0])
        self.assertEqual(len(e.st['markers']), 3, 'a bad bound makes no marker')
        self.assertIn('over dmax', e.run([{'op': 'deltas', 'dmin': '25ns'}])[0]['error'], 'marker 1 keeps dmax 15ns: no Δ could keep both')
        e.run([{'op': 'marker', 'id': 1, 'dmax': None}, {'op': 'deltas', 'dmin': '25ns'}])   # without id: every marker
        self.assertEqual([m.get('dmin') for m in e.st['markers']], [25000] * 3)
        m = e.run([{'op': 'measures'}])[0]['measures']
        self.assertEqual([(r['from']['id'], r['to']['id'], r['dt'], r.get('ok')) for r in m], [(1, 2, 20000, False), (2, 3, 30000, True)])
        e.run([{'op': 'deltas', 'id': 2, 'dmin': '3 cycles'}, {'op': 'deltas', 'dmin': None, 'dmax': None}])
        self.assertTrue(all('dmin' not in m and 'dmax' not in m for m in e.st['markers']))
        e.run([{'op': 'marker', 'id': 2, 'dmax': '3 cycles'}])
        self.assertNotIn('ok', e.run([{'op': 'measures'}])[0]['measures'][1], 'a bound in cycles: the page counts them')

    def test_measure_cli(self):
        e = self.three()
        e.run([{'op': 'marker', 'id': 2, 'dmax': '20ns'}])
        rows = V.measure_list(e.marks())
        text = V.measure_text(rows)
        self.assertIn('2 measurements', text)
        self.assertIn('Δ 30 ns', text)
        self.assertIn('✗', text)
        csv = V.measure_text(rows, csv_out=True).splitlines()
        self.assertEqual(csv[0], ','.join(V.MEASURE_CSV))
        self.assertEqual(csv[1:], ['1,m10ns,10,2,m30ns,30,20,,,,,', '2,m30ns,30,3,m60ns,60,30,,,20,false,'])

    def test_expr_markers_live_only(self):
        r = ed().run([{'op': 'expr_markers', 'id': 1}])[0]
        self.assertIn('runs in the page only', r['error'])


if __name__ == '__main__':
    unittest.main()


class Review1103(unittest.TestCase):
    """What the review of 2026-11-03 found the file's side doing apart from the page (B-05, B-07, B-09, B-10, B-11, B-15, B-23)."""
    def err(self, e, *ops):
        return e.run(list(ops))[-1].get('error') or ''

    def test_colours_the_page_refuses(self):
        e = ed()
        for op in ({'op': 'bookmark', 't': '10ns', 'color': 'red; x'}, {'op': 'marker', 't': '10ns', 'color': 'not a colour!'},
                   {'op': 'paint', 'signals': 'clk', 'color': 'a b'}, {'op': 'group', 'name': 'g', 'signals': 'clk', 'color': '{}'}):
            self.assertIn('is no colour', self.err(e, op), op)
        for c in ('#a0b0c0', 'teal', 'rgb(1, 2, 3)', 'hsl(10 50% 50%)'):
            self.assertEqual(self.err(e, {'op': 'marker', 't': '10ns', 'color': c}), '', c)

    def test_times_outside_the_waves(self):
        e = ed()
        for op in ({'op': 'bookmark', 't': '5s'}, {'op': 'marker', 't': -5}, {'op': 'span', 'from': 0, 'to': '5s'}):
            self.assertIn('outside these waves (0 ps … 80 ns)', self.err(e, op), op)   # (view.js when: review 2026-11-05 B-21)
        self.assertEqual(self.err(e, {'op': 'marker', 't': '80ns'}), '')

    def test_set_state_takes_a_state_only(self):
        e = ed()
        r = e.run([{'op': 'set_state', 'state': {'wavelens': 'state', 'foo': 1, 'bookmarks': [None, {'n': 1, 't': 5000}],
                                                  'config': {'highlight': 'clk,tb.dut.valid'}}},
                   {'op': 'bookmark', 't': '10ns'}, {'op': 'highlight', 'add': 'tb.dut.data'}])
        self.assertEqual([x.get('error') for x in r], [None] * 3)
        self.assertNotIn('foo', e.st)
        self.assertEqual([b['n'] for b in e.st['bookmarks']], [1, 2])
        self.assertEqual(e.st['config']['highlight'][:2], ['clk', 'tb.dut.valid'])

    def test_a_copy_gone_leaves_no_highlight_nor_hidden_bit(self):
        e = ed()
        r = e.run([{'op': 'duplicate', 'signals': 'tb.dut.data'}, {'op': 'highlight', 'set': 'tb.dut.data#2'}, {'op': 'bits', 'signals': 'tb.dut.data#2'},
                   {'op': 'hide', 'signals': 'tb.dut.data#2[3]'}, {'op': 'duplicate', 'signals': 'tb.dut.data#2', 'delete': True}])
        self.assertEqual([x.get('error') for x in r], [None] * 5)
        self.assertEqual((e.st['config']['highlight'], e.st.get('hidden')), ([], []))

    def test_the_window_within_the_waves(self):
        e = ed()
        e.run([{'op': 'cursor', 't': '5ns'}, {'op': 'view', 'span': '40ns'}])
        self.assertEqual((e.st['from'], e.st['to']), (0, 40000))
        e.run([{'op': 'view', 'at': '79ns', 'span': '500ns'}])
        self.assertEqual((e.st['from'], e.st['to']), (0, 80000))

    def test_texts_and_numbers_as_the_page(self):
        e = ed()
        self.assertEqual(e.run([{'op': 'bookmark', 't': '10ns', 'text': [1, 2.0, None], 'label': True}])[0].get('error'), None)
        b = e.st['bookmarks'][-1]
        self.assertEqual((b['text'], b['label']), ('1,2,', 'true'))
        self.assertIn('a bookmark number', self.err(e, {'op': 'bookmark', 'n': ' 3', 't': '10ns'}))
        e.run([{'op': 'marker', 't': '10ns'}, {'op': 'marker', 't': '30ns'}, {'op': 'marker', 't': '50ns'}])
        self.assertEqual(self.err(e, {'op': 'deltas', 'id': 1, 'to': 3.0}), '')
        self.assertEqual(e.st['markers'][0]['dto'], 3)
        self.assertEqual(e.run([{'op': 'rows', 'offset': 'abc', 'limit': 2}])[0]['rows'][:1], e.run([{'op': 'rows', 'limit': 1}])[0]['rows'])   # +"abc" || 0

    def test_arrows_deleted_and_a_window_not_known(self):
        """M-13 of the review: what no test ran: an arrow deleted (by id, by its ends), view span / at on a file whose window is not known."""
        e = ed()
        e.run([{'op': 'bookmark', 't': '30ns'}, {'op': 'arrow', 'from': 1, 'to': 2}, {'op': 'arrow', 'from': 2, 'to': 1}])
        self.assertEqual(e.run([{'op': 'arrow', 'id': 1, 'delete': True}])[0], {'op': 'arrow', 'id': 1, 'deleted': True})
        self.assertEqual(e.run([{'op': 'arrow', 'from': 2, 'to': 1, 'delete': True}])[0].get('deleted'), True)
        self.assertEqual(self.err(e, {'op': 'arrow', 'from': 1, 'to': 2, 'delete': True}), 'no arrow 1 → 2')
        self.assertEqual(self.err(ed(), {'op': 'view', 'span': '10ns'}), 'view: at (the cursor here is not known)')
        self.assertEqual(self.err(ed(), {'op': 'view', 'at': '10ns'}), 'view: span (the window here is not known)')
        self.assertEqual(self.err(ed(), {'op': 'view', 'from': '20ns', 'to': '10ns'}), 'view: "to" is not after "from"')


class Review1105(unittest.TestCase):
    """What the review of 2026-11-05 found the file's side doing apart from the page (B-02, B-03, B-11, B-19, B-21, B-23; T-01, T-10)."""
    D = 'tb.dut.data'

    def err(self, e, *ops):
        return e.run(list(ops))[-1].get('error') or ''

    def test_rows_with_a_slice_copy(self):
        """B-02: rows after duplicate bits: no traceback; the copies under their bus in the page's order (look.js dupsBy: the slices,
        the highest msb first, then #2, #3)."""
        e = ed()
        r = e.run([{'op': 'duplicate', 'signals': self.D}, {'op': 'duplicate', 'signals': self.D, 'bits': [3, 0]},
                   {'op': 'duplicate', 'signals': self.D, 'bits': [7, 4]}, {'op': 'duplicate', 'signals': self.D}, {'op': 'rows', 'pattern': 'tb.dut.d*'}])
        self.assertEqual([x.get('error') for x in r], [None] * 5)
        self.assertEqual(r[-1]['rows'], [[self.D, 8], [self.D + '[7:4]', 4], [self.D + '[3:0]', 4], [self.D + '#2', 8], [self.D + '#3', 8]])
        self.assertEqual([V.copy_base(x) for x in (self.D + '#2', self.D + '[7:4]', self.D, 'x#1', 'x[1]')], [self.D, self.D, None, None, None])

    def test_rows_after_bits(self):
        """B-20 (review of the runs T-06): rows lists the bits of a bus shown bit by bit under it, MSB first, [path[i], 1, "bit"] (edit.js
        rows), a copy's bits under the copy; a pattern finds one bit; bits off: the bus alone again."""
        e, bit = ed(), lambda p, i: [f'{p}[{i}]', 1, 'bit']
        r = e.run([{'op': 'bits', 'signals': self.D}, {'op': 'rows', 'pattern': 'tb.dut.d*'}])
        self.assertEqual(r[-1]['rows'], [[self.D, 8]] + [bit(self.D, i) for i in range(7, -1, -1)])
        self.assertEqual(r[-1]['total'], 9)
        self.assertEqual(e.run([{'op': 'rows', 'pattern': self.D + '[3]'}])[0]['rows'], [bit(self.D, 3)])
        r = e.run([{'op': 'duplicate', 'signals': self.D}, {'op': 'bits', 'signals': self.D + '#2'}, {'op': 'bits', 'signals': self.D, 'on': False},
                   {'op': 'rows', 'pattern': 'tb.dut.d*'}])
        self.assertEqual(r[-1]['rows'], [[self.D, 8], [self.D + '#2', 8]] + [bit(self.D + '#2', i) for i in range(7, -1, -1)])
        self.assertEqual(e.run([{'op': 'rows', 'pattern': 'tb.dut.d*', 'offset': 2, 'limit': 2}])[0],
                         {'op': 'rows', 'total': 10, 'rows': [bit(self.D + '#2', 7), bit(self.D + '#2', 6)], 'next_offset': 4})

    def test_a_signal_deleted_with_its_slices(self):
        """B-03, scenario 1: duplicate delete of a signal takes its slices too, in the page's order."""
        e = ed()
        r = e.run([{'op': 'duplicate', 'signals': self.D, 'bits': [7, 4]}, {'op': 'duplicate', 'signals': self.D},
                   {'op': 'duplicate', 'signals': self.D, 'delete': True}])
        self.assertEqual(r[-1].get('deleted'), [self.D + '[7:4]', self.D + '#2'])
        self.assertEqual(e.st['dups'], [])
        self.assertEqual(e.run([{'op': 'duplicate', 'signals': self.D, 'bits': [7, 4]}, {'op': 'duplicate', 'signals': self.D}])[1]['copies'],
                         [self.D + '#2'])   # a slice is no #n: the first copy is #2 again

    def test_what_stood_on_a_slice_goes_to_its_bus(self):
        """B-03, scenario 2: a bookmark, a marker (its Δ lane too), a span, the selection, a highlight, a colour on a slice deleted: as
        look.js dupDrop (the bus; the highlight and the colour gone)."""
        e, s = ed(), self.D + '[7:4]'
        r = e.run([{'op': 'duplicate', 'signals': self.D, 'bits': [7, 4]}, {'op': 'bookmark', 't': '20ns', 'signal': s, 'text': 'b'},
                   {'op': 'marker', 't': '30ns', 'signal': s}, {'op': 'marker', 't': '60ns'}, {'op': 'deltas', 'id': 1, 'signal': s},
                   {'op': 'span', 'from': '10ns', 'to': '30ns', 'signals': s}, {'op': 'highlight', 'set': s}, {'op': 'paint', 'signals': s, 'color': '#123456'},
                   {'op': 'select', 'signal': s}, {'op': 'duplicate', 'signals': s, 'delete': True}])
        self.assertEqual([x.get('error') for x in r], [None] * len(r))
        st = e.st
        self.assertEqual((st['bookmarks'][-1]['signal'], st['markers'][0]['signal'], st['markers'][0].get('dsignal'), st['spans'][0]['signals'],
                          st['select'], st['config']['highlight'], st.get('paint') or {}, st['dups']),
                         (self.D, self.D, self.D, [self.D], self.D, [], {}, []))
        e = ed()
        e.run([{'op': 'duplicate', 'signals': self.D}, {'op': 'bits', 'signals': self.D + '#2'}, {'op': 'select', 'signal': self.D + '#2[3]'},
               {'op': 'duplicate', 'signals': self.D + '#2', 'delete': True}])
        self.assertEqual(e.st['select'], self.D)   # a bit of a copy selected: its signal (look.js: sel.of === d)

    def test_the_id_answered_is_the_one_made(self):
        """B-11, T-10: two equal spans, two markers at one time, a copy of a copy: the id answered, edited by the next command,
        changes the entry just made."""
        e = ed()
        r = e.run([{'op': 'span', 'from': '10ns', 'to': '30ns'}, {'op': 'span', 'from': '10ns', 'to': '30ns'}])
        self.assertEqual([x['id'] for x in r], [1, 2])
        e.run([{'op': 'span', 'id': r[1]['id'], 'label': 'second'}])
        self.assertEqual([x.get('label') for x in e.st['spans']], [None, 'second'])
        r = e.run([{'op': 'marker', 't': '50ns'}, {'op': 'marker', 't': '50ns'}])
        self.assertEqual([x['id'] for x in r], [1, 2])
        e.run([{'op': 'marker', 'id': r[1]['id'], 'label': 'second'}])
        self.assertEqual([x.get('label') for x in e.st['markers']], [None, 'second'])
        r = e.run([{'op': 'duplicate', 'signals': self.D}, {'op': 'duplicate', 'signals': self.D + '#2'}])
        self.assertEqual([x['copies'] for x in r], [[self.D + '#2'], [self.D + '#3']])
        e.run([{'op': 'radix', 'signals': r[1]['copies'][0], 'radix': 'bin'}])
        self.assertEqual(e.st['radix'], {self.D + '#3': 'bin'})

    def test_times_as_the_page_says_them(self):
        """B-21: view.js when (fmtExact): the unit of the value, every digit to 1 ps; cycles as numbers."""
        self.assertEqual([V.when(t) for t in (0, 1e13, -5000, 205000, 1234567, 0.5, 1500, 1e9)],
                         ['0 ps', '10 s', '-5 ns', '205 ns', '1.234567 µs', '500 fs', '1.5 ns', '1 ms'])
        self.assertEqual([V.when(t, False) for t in (3, 2.5, 1 / 3)], ['3', '2.5', '0.333'])
        e = ed()
        self.assertEqual(self.err(e, {'op': 'marker', 't': '10s'}), 't: 10 s is outside these waves (0 ps … 80 ns)')
        self.assertEqual(self.err(e, {'op': 'range', 'from': '1s', 'to': '2s'}), 'range: 1 s … 2 s is outside these waves (0 ps … 80 ns)')
        cyc = ed(doc={'signal': [{'name': 'a', 'wave': '0101'}]})
        self.assertEqual(self.err(cyc, {'op': 'marker', 't': 9}), 't: 9 is outside these waves (0 … 4)')
        self.assertEqual(ed().run([{'op': 'range', 'from': '80ns', 'to': '90ns'}])[0], {'op': 'range', 'range': None})   # touching: none (edit.js)

    def test_style_null_is_the_settings(self):
        """B-23 of 2026-11-03: style null is the settings' style (look.js setStyle), in the answer and the state, never null."""
        e = ed()
        r = e.run([{'op': 'style', 'name': 'questa'}, {'op': 'style', 'name': None}])
        self.assertEqual(([x['style'] for x in r], e.st['config']['style']), (['questa', 'auto'], 'auto'))
        e = ed(settings={'style': 'square'})
        self.assertEqual(e.run([{'op': 'style', 'name': None}])[0]['style'], 'square')

    def test_find_says_what_it_counts(self):
        """B-19: the file does not know a plugin's rows (the assertions): its answer says so, and no folding is written."""
        e = ed()
        r = e.run([{'op': 'find', 'query': 'state'}])[0]
        self.assertEqual((r['count'], 'not counted' in r['plugins']), (2, True))
        self.assertNotIn('fold', e.st.get('config') or {})

    def test_only_groups_after_a_state(self):
        """B-30 of the review of 2026-11-05 (runs): a state with only and no groups sets the next set's groups to the setting's,
        as view.js setState (onlyGrp undefined); with groups: that one; a state without only: the one before stays."""
        e = ed()
        r = e.run([{'op': 'group', 'name': 'mix', 'signals': ['clk', 'tb.dut.valid']}, {'op': 'only', 'groups': False},
                   {'op': 'set_state', 'state': {'wavelens': 'state', 'only': {'modules': ['tb.dut'], 'on': True}}},
                   {'op': 'only', 'clear': True}, {'op': 'only', 'modules': ['tb.dut']}])
        self.assertEqual((r[-1]['only'], r[-1]['groups']), ({'modules': ['tb.dut'], 'on': True}, True))
        self.assertEqual(e.st['only'], {'modules': ['tb.dut'], 'on': True})
        r = e.run([{'op': 'set_state', 'state': {'wavelens': 'state', 'only': {'modules': ['tb.dut'], 'groups': False}}},
                   {'op': 'only', 'clear': True}, {'op': 'set_state', 'state': {'wavelens': 'state', 'only': None}},
                   {'op': 'only', 'modules': ['tb.dut']}])
        self.assertEqual(r[-1]['only'], {'modules': ['tb.dut'], 'on': True, 'groups': False})   # only null: the groups kept

    def test_only_groups_with_a_copy_in_a_group(self):
        """T-05 of the review of 2026-11-05 (runs): a copy (data#2) in your group stays with it under Only when the groups are
        whole, goes with its module's signal when not; a set_state of only with groups puts the next set's groups (the smoke
        modules: the page alike, with a bus's bits)."""
        e = ed()
        e.run([{'op': 'group', 'name': 'g', 'signals': ['tb.dut.data', 'tb.dut.valid']}, {'op': 'duplicate', 'signals': 'tb.dut.data'},
               {'op': 'group', 'name': 'g', 'add': ['tb.dut.data#2']}, {'op': 'only', 'modules': 'tb.other'}])
        ug = lambda: [r['full'] for r in e.ordered() if r.get('ug')]
        self.assertEqual(ug(), ['tb.dut.data', 'tb.dut.valid', 'tb.dut.data#2'])
        e.run([{'op': 'only', 'groups': False}])
        self.assertEqual(ug(), [])
        self.assertNotIn('tb.dut.data#2', [r['full'] for r in e.ordered()], 'the copy goes with its module')
        r = e.run([{'op': 'set_state', 'state': {'wavelens': 'state', 'only': {'modules': ['tb.other'], 'on': True, 'groups': True}}},
                   {'op': 'only', 'clear': True}, {'op': 'only', 'modules': ['tb.dut']}])
        self.assertEqual((r[-1]['only'], r[-1]['groups']), ({'modules': ['tb.dut'], 'on': True}, True))
        self.assertEqual(ug(), ['tb.dut.data', 'tb.dut.valid', 'tb.dut.data#2'])
