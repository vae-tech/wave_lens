"""tools/viewedit.py: the viewer's commands on a state (names, every command, its errors), a page's edits (the block,
revisions), a saved state and the command line. That the browser gets the same state from them as from view.run is
the smoke test's (section edit)."""
import json, os, re, unittest

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
        # your group's signal: by the signal it shows
        e.run([{'op': 'group', 'name': 'g', 'signals': ['clk', 'tb.dut.valid']}])
        self.assertEqual([x['full'] for x in e.ordered()[:3]], ['@g', 'tb.dut.valid', 'tb'])


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
        self.assertEqual(bad[0]['error'], 'range: 1e+06ns … 2e+06ns is outside the waves (0ns … 80ns)')
        self.assertIn('outside the waves', bad[1]['error'])
        self.assertEqual(e.st['range'], {'from': 0, 'to': 30000, 'signal': None})

    def test_result_shapes(self):
        """layout, find, cycles answer what edit.js answers."""
        e = ed()
        r = e.run([{'op': 'layout', 'height': 400}, {'op': 'layout', 'scroll': 'page', 'tools': 'fold'}, {'op': 'find', 'query': 'dut.st'},
                   {'op': 'find', 'query': 'val|clk', 'regex': True}, {'op': 'find', 'query': 'state', 'word': True, 'regex': False},
                   {'op': 'cycles', 'on': True}])
        self.assertEqual(r[0], {'op': 'layout', 'scroll': 'window', 'height': 400, 'tools': 'open'})
        self.assertEqual(r[1], {'op': 'layout', 'scroll': 'page', 'height': None, 'tools': 'fold'})
        self.assertEqual(r[2], {'op': 'find', 'found': ['tb.dut.state'], 'count': 1})
        self.assertEqual(r[3], {'op': 'find', 'found': ['clk', 'tb.dut.valid'], 'count': 2})
        self.assertEqual(r[4], {'op': 'find', 'found': ['tb.dut.state', 'tb.other.state'], 'count': 2})
        self.assertEqual(r[5], {'op': 'cycles', 'cycles': {'cycles': True, 'cycleClock': None, 'cycleZero': None}, 'clock': 'clk', 'cycle': None})

    def test_rows_order(self):
        """rows in the order the names column shows them (sort, ignored prefixes), your groups first, the hidden at the end."""
        doc = {'signal': [{'name': 'b10', 'wave': '01'}, {'name': 'i_b2', 'wave': '01'}, {'name': 'a', 'wave': '01'}, ['m', {'name': 'z', 'wave': '0'}]]}
        e = ed(doc=doc)
        r = e.run([{'op': 'group', 'name': 'g', 'signals': 'a'}, {'op': 'sort', 'dir': 'asc', 'ignore': 'i_'}, {'op': 'hide', 'signals': 'b10'},
                   {'op': 'rows'}])[-1]
        self.assertEqual(r['rows'], [['@g', 'group'], ['a', 1], ['i_b2', 1], ['m', 'module'], ['m.z', 1], ['b10', 1]])

    def test_times(self):
        """One time parser (model.js parseT) for viewedit.py and wavemcp.py: units in any case, µs, an exponent."""
        for text, ps in (('100NS', 1e5), ('1E2', 100), ('0.1µs', 1e5), (' -5 ns ', -5000), ('2.5us', 2.5e6), ('1e-3ns', 1)):
            self.assertAlmostEqual(V.parse_t(text), ps)
        for text in ('5 parsecs', '1.2.3ns', 'ns', ''):
            self.assertIsNone(V.parse_t(text))
        self.assertEqual(V.parse_time('3', plain=1000), 3000)   # wavemcp.py: a plain number is ns


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


if __name__ == '__main__':
    unittest.main()
