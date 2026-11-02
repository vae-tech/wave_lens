"""python/wavelens_cocotb.py under a stand-in for cocotb (the real one runs in make cocotb, checked by smoke) and
tools/testmarks.py on what it writes: a test's result as cocotb says it, the marks file, the marks in a config and a page."""
import ast, asyncio, contextlib, inspect, json, logging, os, sys, tempfile, types, unittest

from . import helpers as H

sys.path.insert(0, os.path.join(H.ROOT, 'python'))
sys.path.insert(0, H.TOOLS)
import testmarks  # noqa: E402
import wavelens_cocotb as wc  # noqa: E402


class TestSuccess(BaseException):   # cocotb.pass_test()
    pass


class Sig:
    def __init__(self, path):
        self._path, self.values = path, []

    @property
    def value(self):
        return self.values[-1]

    @value.setter
    def value(self, v):
        self.values.append(v)


class Dut:
    _path = 'tb'

    def __init__(self, *names):
        for n in names:
            setattr(self, n, Sig(f'tb.{n}'))
        self.sub = Sig('tb.u_x.sig')


class Vector:   # a value like cocotb's LogicArray
    def __init__(self, n):
        self.n = n

    def to_unsigned(self):
        if self.n is None:
            raise ValueError('x')
        return self.n

    def __str__(self):
        return 'xxxx'


class Harness(unittest.TestCase):
    def setUp(self):
        self.t = 0
        stub, utils = types.ModuleType('cocotb'), types.ModuleType('cocotb.utils')
        stub.test = lambda *a, **k: (lambda f: f)
        utils.get_sim_time = lambda unit: float(self.t)
        self.addCleanup(sys.modules.pop, 'cocotb', None)
        self.addCleanup(sys.modules.pop, 'cocotb.utils', None)
        sys.modules.update({'cocotb': stub, 'cocotb.utils': utils})
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.path = os.path.join(self.dir, 'x.marks.json')

    def marks(self, **kw):
        return wc.Marks(path=self.path, **kw)

    def run_test(self, wl, fn, dut=None, **opts):
        """One test run as cocotb would; what it raises is not this harness's business."""
        go = wl.test(**opts)(fn)
        try:
            asyncio.run(go(dut or Dut('TEST_CASE', 'TEST_STEP')))
        except BaseException:   # noqa: B902 (what cocotb itself catches)
            pass
        with open(self.path, encoding='utf-8') as f:
            return json.load(f)


class Verdict(unittest.TestCase):
    """The same answers as cocotb's regression.py _score_test."""

    def test_table(self):
        boom, key = AssertionError('x'), KeyError('k')
        for exc, opts, want in ((None, {}, 'pass'), (TestSuccess(), {}, 'pass'), (boom, {}, 'fail'), (key, {}, 'fail'),
                                (boom, {'expect_fail': True}, 'xfail'), (key, {'expect_fail': True}, 'fail'),   # only a check is a failure
                                (None, {'expect_fail': True}, 'fail'), (TestSuccess(), {'expect_fail': True}, 'fail'),
                                (key, {'expect_error': (KeyError,)}, 'pass'), (boom, {'expect_error': (KeyError,)}, 'fail'),
                                (None, {'expect_error': (KeyError,)}, 'fail')):
            with self.subTest(exc=exc, opts=opts):
                self.assertEqual(wc.verdict(exc, **opts), want)


class Where(unittest.TestCase):
    def test_the_line_of_the_test_under_a_stale_compile(self):
        # compiled under another path than the module's __file__, as a cached compile reached through a symlink: its frames are still its own
        with open(wc.__file__, encoding='utf-8') as f:
            code = compile(f.read(), '/elsewhere/link/python/wavelens_cocotb.py', 'exec')
        lib = types.ModuleType('wavelens_stale')
        lib.__file__ = wc.__file__
        sys.modules['wavelens_stale'] = lib   # (a dataclass or a decorator may look its module up)
        self.addCleanup(sys.modules.pop, 'wavelens_stale')
        exec(code, lib.__dict__)
        try:
            lib.Marks(path='off').check(1, 2, 'a value')
        except AssertionError as e:
            self.assertRegex(lib.where_of(e), r'^test_cocotb_marks\.py:\d+$')
        else:
            self.fail('check did not raise')


class Texts(unittest.TestCase):
    def test_values_as_the_waves_show_them(self):
        for v, want in ((0, '0'), (9, '9'), (10, '0xA'), (0xCAFE, '0xCAFE'), (-16, '-0x10'), (True, '1'), (Vector(255), '0xFF'), (Vector(None), 'xxxx'), ('abc', 'abc')):
            self.assertEqual(wc.text_of(v), want)

    def test_a_vector_with_x_is_no_crash(self):
        class Raises:
            def __eq__(self, other):
                raise ValueError('x')
            __hash__ = None
        self.assertFalse(wc.same(Raises(), 1))

    def test_said(self):
        self.assertEqual(wc.said(AssertionError('got 1'), ''), 'got 1')
        self.assertEqual(wc.said(KeyError('k'), ''), "KeyError: 'k'")
        self.assertEqual(wc.said(asyncio.CancelledError(), 'from a task'), 'stopped: from a task')
        self.assertIn('timeout', wc.said(asyncio.CancelledError(), ''))


class Library(Harness):
    def test_a_test_marked_up(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')

        async def first(dut):
            """What it does.

            More lines."""
            self.t = 100
            with wl.phase('write'):
                self.t = 200
                wl.note('here', signal=dut.sub, label='l')
                with wl.phase('inner'):
                    self.t = 250
                self.t = 300
            wl.check(5, 5, 'five', signal=dut.TEST_CASE)
            with wl.phase('write'):
                self.t = 400
        d = self.run_test(wl, first, dut)
        t = d['tests'][0]
        self.assertEqual((t['n'], t['name'], t['doc'], t['from'], t['to'], t['result']), (1, 'first', 'What it does.', 0, 400, 'pass'))
        self.assertEqual(dut.TEST_CASE.values, [1], 'the number goes into the signal')
        self.assertEqual(dut.TEST_STEP.values, [0, 1, 2, 1, 0, 1, 0], 'phases by number, a phase inside one and back, one label one number')
        self.assertEqual(d['step'], 'TEST_STEP')
        self.assertEqual(d['steps'], {'1': 'write', '2': 'inner'})
        self.assertEqual(t['marks'][0], {'t': 200, 'kind': 'note', 'text': 'here', 'signal': 'u_x.sig', 'label': 'l'}, 'a handle: its path under the top')
        self.assertEqual(t['marks'][1]['got'], '5')
        self.assertEqual([p['step'] for p in t['phases']], [2, 1, 1])

    def test_numbers_run_on(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')

        async def one(dut):
            pass
        self.run_test(wl, one, dut)
        d = self.run_test(wl, one, dut)
        self.assertEqual([t['n'] for t in d['tests']], [1, 2])
        self.assertEqual(dut.TEST_CASE.values, [1, 2])

    def test_check_fails_the_test_with_both_values(self):
        wl = self.marks()

        async def bad(dut):
            self.t = 50
            wl.check(0, 0x20000, 'bit 17')
        with self.assertRaisesRegex(AssertionError, r'bit 17: got 0, expected 0x20000'):
            asyncio.run(wl.test()(bad)(Dut('TEST_CASE', 'TEST_STEP')))
        with open(self.path, encoding='utf-8') as f:
            t = json.load(f)['tests'][0]
        self.assertEqual((t['result'], t['message'], t['to']), ('fail', 'bit 17: got 0, expected 0x20000', 50))
        self.assertRegex(t['where'], r'test_cocotb_marks\.py:\d+', 'the line of the test')
        self.assertEqual((t['marks'][0]['ok'], t['marks'][0]['got'], t['marks'][0]['expected']), (False, '0', '0x20000'))

    def test_a_phase_ended_by_a_failure_is_kept(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')

        async def bad(dut):
            with wl.phase('p'):
                self.t = 30
                raise KeyError('k')
        t = self.run_test(wl, bad, dut)['tests'][0]
        self.assertEqual(t['phases'], [{'label': 'p', 'from': 0, 'to': 30, 'step': 1}])
        self.assertEqual(dut.TEST_STEP.values[-1], 0)

    def test_expect_fail_and_cancel(self):
        wl = self.marks()

        async def bad(dut):
            assert False, 'no'

        async def stopped(dut):
            raise asyncio.CancelledError()
        self.assertEqual(self.run_test(wl, bad, expect_fail=True)['tests'][-1]['result'], 'xfail')
        t = self.run_test(wl, stopped)['tests'][-1]
        self.assertEqual((t['result'], t['where']), ('fail', ''), 'a cancelled test has no line of its own')

    def test_no_signals_in_the_design(self):
        wl = self.marks()

        async def one(dut):
            with wl.phase('p', signals=None):
                pass
        with self.assertLogs('wavelens', 'WARNING') as logs:
            d = self.run_test(wl, one, Dut())
            self.run_test(wl, one, Dut())
        self.assertEqual(len(logs.records), 1, 'said once')
        self.assertNotIn('step', d['tests'][0]['phases'][0])
        self.assertNotIn('step', d)

    def test_a_phase_on_rows_stays_a_span(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')

        async def one(dut):
            with wl.phase('p', signals=dut.sub):
                pass
        d = self.run_test(wl, one, dut)
        self.assertEqual(d['tests'][0]['phases'][0]['signals'], ['u_x.sig'])
        self.assertEqual(dut.TEST_STEP.values, [0])

    def test_logs_only_inside_a_test(self):
        wl = self.marks()
        log = logging.getLogger('tb.quiet')
        quiet = logging.NullHandler()
        log.addHandler(quiet)   # (not assertLogs: it stops the record on its way to the root, where the marks listen)
        self.addCleanup(log.removeHandler, quiet)
        log.warning('before')

        async def one(dut):
            log.info('nothing')
            log.warning('a warning')
            log.error('an error')
        d = self.run_test(wl, one)
        log.warning('after')
        with open(self.path, encoding='utf-8') as f:
            d = json.load(f)
        self.assertEqual([(m['level'], m['text']) for m in d['tests'][0]['marks']], [('WARNING', 'a warning'), ('ERROR', 'an error')])
        self.assertNotIn(wl.tap, logging.getLogger().handlers)

    def test_marks_outside_a_test_are_nothing(self):
        wl = self.marks()
        wl.note('x')
        with wl.phase('y'):
            pass
        wl.check(1, 1)
        self.assertFalse(os.path.exists(self.path))

    def test_limit_keeps_the_failures(self):
        wl = self.marks()

        async def many(dut):
            for i in range(wc.MAX_MARKS + 5):
                wl.check(i, i)
            wl.check(1, 2, 'last')
        t = self.run_test(wl, many)['tests'][0]
        self.assertEqual((len(t['marks']), t['dropped']), (wc.MAX_MARKS + 1, 5))
        self.assertFalse(t['marks'][-1]['ok'])

    def test_show_fail(self):
        wl = self.marks()

        async def one(dut):
            wl.check(1, 1, show='fail')
        self.assertEqual(self.run_test(wl, one)['tests'][0]['marks'], [])

    def test_a_crash_leaves_the_tests_before(self):
        wl = self.marks()

        async def hangs(dut):
            with open(self.path, encoding='utf-8') as f:
                self.seen = json.load(f)['tests'][-1]['result']
        self.run_test(wl, hangs)
        self.assertEqual(self.seen, 'run', 'written when the test starts')

    def test_off_is_plain_cocotb(self):
        wl = wc.Marks(path='off')
        dut = Dut('TEST_CASE', 'TEST_STEP')
        ran = []

        async def one(dut):
            ran.append(1)
            with wl.phase('p'):
                wl.note('n')
                wl.check(1, 1)
        go = wl.test()(one)
        self.assertIs(go, one, 'cocotb.test() alone, nothing around the test')
        asyncio.run(go(dut))
        self.assertEqual(ran, [1])
        self.assertEqual((dut.TEST_CASE.values, dut.TEST_STEP.values), ([], []), 'no signal written')
        self.assertFalse(os.path.exists('off'))
        self.assertEqual(wl.tests, [])
        self.assertNotIn(wl.tap, logging.getLogger().handlers)

    def test_off_still_checks(self):
        wl = wc.Marks(path='off')
        with self.assertRaisesRegex(AssertionError, 'got 1, expected 2'):
            wl.check(1, 2)


class WithoutTheLibrary(Harness):
    """The class a test falls back on when wavelens_cocotb is not there (examples/cocotb_apb/test_apb.py, except ImportError)."""

    def fallback(self):
        with open(os.path.join(H.ROOT, 'examples', 'cocotb_apb', 'test_apb.py'), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        tries = [n for n in tree.body if isinstance(n, ast.Try)]
        self.assertEqual(len(tries), 1)
        names = {'cocotb': sys.modules['cocotb'], 'contextlib': contextlib}
        exec(compile(ast.Module(tries[0].handlers[0].body, []), 'test_apb.py', 'exec'), names)   # noqa: S102
        return names['Marks']

    def test_the_same_calls(self):
        Off = self.fallback()
        real = {n for n in ('test', 'phase', 'note', 'check')}
        self.assertEqual({n for n in vars(Off) if not n.startswith('_')}, real)
        public = {n for n in vars(wc.Marks) if n in real or n == 'note'}
        self.assertEqual(public, real, 'a call of the library the fallback has not')
        wl = Off()
        for name in real - {'test'}:   # every argument the library takes, by name
            params = inspect.signature(getattr(wc.Marks, name)).parameters
            required = [p for n, p in params.items() if n != 'self' and p.default is p.empty]
            kw = {n: None for n, p in params.items() if n != 'self' and p.default is not p.empty and n != 'show'}
            getattr(wl, name)(*[1] * len(required), **kw)
        self.assertEqual(wl.check(1, 1, 'text', signal=None, show='fail'), None)

    def test_it_runs_a_test(self):
        Off = self.fallback()
        wl = Off(signal='TEST_CASE', path='x')
        ran = []

        @wl.test(timeout_time=5)
        async def one(dut):
            with wl.phase('p', signals=None):
                wl.note('n', signal=None, label='l', color='#000')
                ran.append(1)
        asyncio.run(one(Dut()))
        self.assertEqual(ran, [1])

    def test_a_check_still_checks(self):
        wl = self.fallback()()
        with self.assertRaisesRegex(AssertionError, 'bit 17: got 0, expected 2'):
            wl.check(0, 2, 'bit 17')


DOC = {'wavelens': 'marks', 'version': 1, 'signal': 'TEST_CASE', 'step': 'TEST_STEP', 'steps': {'1': 'reset'}, 'tests': [
    {'n': 1, 'name': 'a', 'doc': 'first', 'from': 0, 'to': 100, 'result': 'pass', 'message': '', 'where': '', 'dropped': 0,
     'phases': [{'label': 'reset', 'from': 0, 'to': 10, 'step': 1}, {'label': 'on', 'from': 10, 'to': 20, 'signals': ['PSEL']}],
     'marks': [{'t': 50, 'kind': 'check', 'ok': True, 'got': '5', 'expected': '5', 'text': 'five', 'signal': 'PSEL'}]},
    {'n': 2, 'name': 'b', 'doc': '', 'from': 101, 'to': 300, 'result': 'fail', 'message': 'got 0, expected 1', 'where': 't.py:9', 'dropped': 3,
     'phases': [], 'marks': [{'t': 300, 'kind': 'check', 'ok': False, 'got': '0', 'expected': '1', 'text': ''},
                             {'t': 200, 'kind': 'log', 'level': 'WARNING', 'text': 'careful'}, {'t': 210, 'kind': 'note', 'text': 'here'}]}]}


class Merge(unittest.TestCase):
    def cfg(self, **view):
        return {'views': {'v': {'signals': ['TEST_CASE', 'TEST_STEP', 'PSEL'], **view}}}

    def test_bookmarks(self):
        c = self.cfg(bookmarks=[{'n': 7, 't': '5ns', 'text': 'mine'}])
        testmarks.merge(c, DOC)
        b = c['views']['v']['bookmarks']
        self.assertEqual(b[0]['text'], 'mine')
        self.assertEqual([x['n'] for x in b], list(range(7, 7 + len(b))), 'after the view\'s own')
        self.assertEqual((b[1]['t'], b[1]['signal'], b[1]['label']), (0, 'TEST_CASE', 'TC1'))
        self.assertIn('first', b[1]['text'])
        self.assertEqual((b[2]['label'], b[2]['signal'], b[2]['text']), ('✓ 5', 'PSEL', 'five: 5 as expected'))
        self.assertEqual(b[3]['label'], 'PASS')
        self.assertEqual(b[3]['signal'], 'TEST_STEP', 'the end over the next row: the next test starts at the same place')
        last = b[-1]
        self.assertEqual(last['label'], 'FAIL')
        self.assertIn('got 0, expected 1 (t.py:9)', last['text'])
        self.assertIn('3 marks past the limit', last['text'])
        fail = next(x for x in b if x.get('label', '').startswith('✗'))
        self.assertEqual((fail['label'], fail['signal'], fail['color']), ('✗ 0 ≠ 1', 'TEST_CASE', testmarks.RESULTS['fail'][1]))
        self.assertIn('warning', [x.get('label') for x in b])

    def test_spans_markers_enum_note(self):
        c = self.cfg(note='mine')
        testmarks.merge(c, DOC)
        v = c['views']['v']
        self.assertEqual([s['label'] for s in v['spans']], ['TC1 a · PASS', 'on', 'TC2 b · FAIL'], 'a phase on a step is the row\'s value, no span')
        self.assertEqual(v['spans'][1]['signals'], ['PSEL'])
        self.assertEqual(v['marker'][1], {'on': {'signal': 'TEST_CASE', 'value': '2'}, 'label': 'TC2'}, 'the jumps are the signal in the dump')
        self.assertEqual(c['enum'], {'TEST_CASE': {'1': 'a', '2': 'b'}, 'TEST_STEP': {'0': '·', '1': 'reset'}})
        self.assertEqual(v['note'], '2 tests: 1 passed, 1 failed. mine')
        self.assertEqual(v['to'], '336ps', 'past the last test: a failure at the end of the dump stays in sight')

    def test_a_window_and_a_view_without(self):
        c = {'views': {'a': {'signals': 'TEST_CASE', 'from': '50ps', 'to': '150ps'}, 'b': {'signals': 'TEST_CASE', 'marks': False}}}
        testmarks.merge(c, DOC)
        self.assertEqual({b['t'] for b in c['views']['a']['bookmarks']}, {50, 100, 101}, 'only what is in the window')
        self.assertEqual(c['views']['a']['to'], '150ps')
        self.assertEqual(c['views']['b'], {'signals': 'TEST_CASE'})

    def test_rows_of_a_whole_dump(self):
        rows = {p: p for p in ('$rootio.PSEL', 'tb.PSEL', 'tb.u_x.PSEL', 'tb.TEST_CASE')}
        self.assertEqual(testmarks.row_for(rows, 'PSEL'), 'tb.PSEL', 'the nearest the top, not Verilator\'s copy of the port')
        self.assertEqual(testmarks.row_for(rows, 'u_x.PSEL'), 'tb.u_x.PSEL')
        self.assertEqual(testmarks.row_for(rows, 'nothing'), 'nothing', 'lint says it')
        self.assertEqual(testmarks.row_for({'a.x.s': 'a.x.s', 'a.y.s': 'a.y.s'}, 's'), 's', 'two as near: no guess')
        c = {'signals': {'tb.TEST_CASE': {}, 'tb.PSEL': {}}, 'views': {'all': {}}}
        testmarks.merge(c, DOC)
        self.assertEqual(c['views']['all']['bookmarks'][0]['signal'], 'tb.TEST_CASE')
        self.assertIn('tb.TEST_CASE', c['enum'])

    def test_no_test_signal(self):
        doc = {**DOC, 'signal': None, 'step': None, 'steps': {}}
        c = self.cfg()
        testmarks.merge(c, doc)
        v = c['views']['v']
        self.assertNotIn('signal', v['bookmarks'][0], 'the time axis')
        self.assertNotIn('marker', v)
        self.assertNotIn('enum', c)

    def test_summary(self):
        tests = [{'result': r} for r in ('pass', 'xfail', 'run')]
        self.assertEqual(testmarks.summary({'tests': tests}), '3 tests: 1 passed, 1 failed as expected, 1 not finished')
        self.assertEqual(testmarks.summary({'tests': [{'result': 'pass'}]}), '1 test: 1 passed, 0 failed')

    def test_config_without_views(self):
        with self.assertRaisesRegex(testmarks.WaveError, 'views'):
            testmarks.merge({}, DOC)


class Split(unittest.TestCase):
    def cfg(self):
        return {'views': {'v': {'signals': ['TEST_CASE', 'TEST_STEP', 'PSEL'], 'title': 'all', 'note': 'n', 'config': {'radix': 'hex'},
                                'bookmarks': [{'n': 1, 't': 5, 'text': 'by hand'}], 'spans': [{'from': 1, 'to': 2}], 'from': '0ps', 'to': '999ps'}}}

    def test_whole_is_as_before(self):
        c = self.cfg()
        self.assertEqual(testmarks.merge(c, DOC), [])
        self.assertEqual(list(c['views']), ['v'])

    def test_a_view_of_each_test(self):
        c = self.cfg()
        nav = testmarks.merge(c, DOC, 'tests')
        self.assertEqual(list(c['views']), ['tc1', 'tc2'], 'the template gives way')
        a, b = c['views']['tc1'], c['views']['tc2']
        self.assertEqual((a['from'], a['to'], a['title']), ('0ps', '112ps', 'TC1 a · PASS'))
        self.assertEqual((b['from'], b['to']), ('101ps', '323ps'))
        self.assertEqual(a['config'], {'radix': 'hex'}, 'the signals and settings of the template')
        self.assertEqual({x['t'] for x in a['bookmarks']}, {0, 50, 100}, 'its own marks, also what the next test does in the tail is out')
        self.assertEqual({x['t'] for x in b['bookmarks']}, {101, 200, 210, 300})
        self.assertEqual([x['label'] for x in a['spans']], ['TC1 a · PASS', 'on'], 'not the template\'s, of the whole run')
        self.assertNotIn('marker', a)
        self.assertEqual(a['note'], 'first')
        self.assertEqual(b['note'], 'got 0, expected 1 (t.py:9)')
        self.assertEqual([(e['key'], e['label'], e['word']) for e in nav], [('tc1', 'TC1 a', 'PASS'), ('tc2', 'TC2 b', 'FAIL')])
        self.assertEqual(c['enum']['TEST_CASE'], {'1': 'a', '2': 'b'})

    def test_both(self):
        c = self.cfg()
        nav = testmarks.merge(c, DOC, 'both')
        self.assertEqual(list(c['views']), ['v', 'tc1', 'tc2'])
        self.assertEqual((nav[0]['key'], nav[0]['label'], nav[0]['word']), ('v', 'All tests', '1 passed, 1 failed'))
        self.assertEqual(c['views']['v']['bookmarks'][0]['text'], 'by hand', 'the whole run keeps its own')

    def test_a_key_taken_and_a_view_without(self):
        c = {'views': {'tc1': {'signals': 'PSEL', 'marks': False}, 'v': {'signals': 'PSEL'}}}
        nav = testmarks.merge(c, DOC, 'both')
        self.assertEqual(nav[1]['key'], 'tc1_')
        self.assertEqual(c['views']['tc1'], {'signals': 'PSEL'})

    def test_not_finished_goes_to_the_end_of_the_dump(self):
        doc = {**DOC, 'tests': [{**DOC['tests'][0], 'to': None, 'result': 'run'}]}
        c = self.cfg()
        testmarks.merge(c, doc, 'tests')
        self.assertNotIn('to', c['views']['tc1'])

    def test_bad_word(self):
        with self.assertRaisesRegex(testmarks.WaveError, 'marksViews'):
            testmarks.merge(self.cfg(), DOC, 'each')


class Page(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.vcd = os.path.join(self.dir, 'x.vcd')
        with open(self.vcd, 'w', encoding='utf-8') as f:
            f.write('$timescale 1ps $end\n$scope module tb $end\n$var wire 8 ! TEST_CASE [7:0] $end\n$var wire 1 " PSEL $end\n$upscope $end\n'
                    '$enddefinitions $end\n#0\nb1 !\n0"\n#50\n1"\n#101\nb10 !\n#300\n0"\n')
        self.cfg, self.marks, self.out = (os.path.join(self.dir, n) for n in ('x.config.json', 'x.marks.json', 'x.html'))
        with open(self.cfg, 'w', encoding='utf-8') as f:
            json.dump({'scope': 'tb', 'views': {'v': {'exact': True, 'signals': ['TEST_CASE', 'PSEL']}, 'w': {'exact': True, 'signals': ['PSEL'], 'marks': False}}}, f)
        with open(self.marks, 'w', encoding='utf-8') as f:
            json.dump({**DOC, 'step': None, 'steps': {}}, f)

    def build(self, *extra):
        return H.run_tool('mkhtml', '--config', self.cfg, '--waves', self.vcd, '--no-sva', '--out', self.out, *extra)

    def page(self):
        with open(self.out, encoding='utf-8') as f:
            return f.read()

    def test_marks_in_the_page(self):
        rc, _, err = self.build('--marks', self.marks)
        self.assertEqual(rc, 0, err)
        self.assertIn('mkhtml: marks: 2 tests: 1 passed, 1 failed', err)
        self.assertNotIn('lint:', err.replace('bookmarks-close', ''))
        text = self.page()
        self.assertIn('TC2 b · FAIL', text)
        self.assertIn('got 0, expected 1 (t.py:9)', text)

    def test_a_page_of_tests(self):
        rc, _, err = self.build('--marks', self.marks, '--marks-views', 'tests')
        self.assertEqual(rc, 0, err)
        self.assertNotIn('lint:', err.replace('bookmarks-close', ''))
        text = self.page()
        self.assertIn('<nav class="tests">', text)
        self.assertEqual(text.count('<section data-view='), 2, 'the view with "marks": false is not one of them')
        self.assertIn('data-view="tc2" style="--tc: #e03131">TC2 b<small>FAIL</small>', text)

    def test_a_whole_page_has_no_buttons(self):
        self.build('--marks', self.marks)
        self.assertNotIn('<nav class="tests">', self.page())

    def test_marks_views_of_a_config(self):
        with open(self.cfg, encoding='utf-8') as f:
            c = json.load(f)
        with open(self.cfg, 'w', encoding='utf-8') as f:
            json.dump({**c, 'marks': 'x.marks.json', 'marksViews': 'both'}, f)
        rc, _, err = self.build()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.page().count('<section data-view='), 3)

    def test_marks_key_of_a_config(self):
        with open(self.cfg, encoding='utf-8') as f:
            c = json.load(f)
        with open(self.cfg, 'w', encoding='utf-8') as f:
            json.dump({**c, 'marks': 'x.marks.json'}, f)
        rc, _, err = self.build()
        self.assertEqual(rc, 0, err)
        self.assertIn('TC2 b · FAIL', self.page())

    def test_a_config_with_marks_false_builds_without_marks(self):
        rc, _, err = self.build()
        self.assertEqual(rc, 0, err)
        self.assertNotIn('TC2', self.page())

    def test_bad_marks_file(self):
        with open(self.marks, 'w', encoding='utf-8') as f:
            f.write('{"a": 1}')
        rc, _, err = self.build('--marks', self.marks)
        self.assertEqual(rc, 1)
        self.assertIn('not a marks file', err)
        with open(self.marks, 'w', encoding='utf-8') as f:
            f.write('{"wavelens": "marks", "version": 9}')
        self.assertIn('version 9', self.build('--marks', self.marks)[2])
        self.assertEqual(self.build('--marks', self.marks + '.none')[0], 1)


if __name__ == '__main__':
    unittest.main()
