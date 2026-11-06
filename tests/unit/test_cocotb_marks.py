"""python/wavelens_cocotb.py under a stand-in for cocotb (the real one runs in make cocotb, checked by smoke) and
tools/testmarks.py on what it writes: a test's result as cocotb says it, the marks file, the marks in a config and a page."""
import ast, asyncio, contextlib, inspect, json, logging, os, re, sys, tempfile, textwrap, types, unittest

from . import helpers as H

sys.path.insert(0, os.path.join(H.ROOT, 'python'))
sys.path.insert(0, H.TOOLS)
import common, testmarks, vcd2wavedrom  # noqa: E402
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


class ReadOnlySig(Sig):   # as cocotb 2.0 in ReadOnly: a write raises
    frozen, error = False, 'Attempting settings a value during the ReadOnly phase.'

    @property
    def value(self):
        return self.values[-1]

    @value.setter
    def value(self, v):
        if self.frozen:
            raise RuntimeError(self.error)
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


def helper_that_checks(wl, a, b):   # a project's own check: not the line of a failure when hidden
    wl.check(a, b)


def helper_that_hides(wl, a, b):
    __tracebackhide__ = True  # noqa: F841
    wl.check(a, b)


class Where(unittest.TestCase):
    def where(self, fn, *hide):
        try:
            fn(wc.Marks(path='off'), 1, 2)
        except AssertionError as e:
            return wc.where_of(e, hide)
        return self.fail('no failure')

    def test_past_what_a_project_hides(self):
        self.assertEqual(self.where(helper_that_checks), f'test_cocotb_marks.py:{helper_that_checks.__code__.co_firstlineno + 1}', 'a helper of no mark: its own line')
        self.assertEqual(self.where(helper_that_hides), f'test_cocotb_marks.py:{Where.where.__code__.co_firstlineno + 2}', '__tracebackhide__: the caller\'s line')

    def test_all_hidden_says_nothing(self):
        self.assertEqual(self.where(helper_that_checks, 'test_cocotb_*.py'), '')

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

    def test_measure(self):
        """Stage 17: wl.measure as a context and by start / stop: the pairs in the test, their bound checked when it is a time."""
        wl = self.marks()

        async def one(dut):
            self.t = 100
            async with wl.measure('req→ack', max='30ns', signal='PREADY'):
                self.t = 120
            m = wl.measure('beat', min=50000)
            for a, b in ((200, 300), (400, 410)):
                self.t = a; m.start(); self.t = b; m.stop()
            with wl.measure('in cycles', max='3 cycles'):
                self.t = 500
            with wl.measure('plain'):
                self.t = 600
            wl.measure('left open').start()
            self.t = 700
        t = self.run_test(wl, one)['tests'][0]
        self.assertEqual([(m['label'], m['from'], m['to'], m.get('ok')) for m in t['measures']],
                         [('req→ack', 100, 120, True), ('beat 1', 200, 300, False), ('beat 2', 400, 410, False), ('in cycles', 410, 500, None),
                          ('plain', 500, 600, None), ('left open', 600, None, None)])
        self.assertEqual((t['measures'][0]['max'], t['measures'][0]['signal'], t['measures'][1]['min']), ('30ns', 'PREADY', 50000))
        self.assertEqual(t['result'], 'pass', 'a measure out of its bound fails nothing by itself')
        self.assertEqual((t['passed'], t['failed']), (0, 0))

    def test_checks_in_a_group_leave_one_bookmark(self):   # P-05b
        wl = self.marks()

        async def one(dut):
            self.t = 100
            with wl.checks('every word of the frame'):
                for i in range(188):
                    wl.check(i, i)
                    self.t += 1
            wl.check(1, 1, 'alone')
            async with wl.checks('the tail', signal='PREADY'):
                wl.check(2, 2, show='all')   # said: its own bookmark too
            with wl.checks('nothing'):
                pass
            with wl.checks('the next frame'):
                self.t = 400
                wl.check(5, 5)
                wl.check(6, 7, 'word 1')
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        got = [(m['kind'], m.get('text'), m.get('n'), m.get('failed'), m['t'], m.get('from')) for m in t['marks'] if m['kind'] in ('check', 'checks')]
        self.assertEqual(got, [('checks', 'every word of the frame', 188, 0, 288, 100), ('check', 'alone', None, None, 288, None),
                               ('check', '', None, None, 288, None), ('checks', 'the tail', 1, 0, 288, 288),
                               ('check', 'word 1', None, None, 400, None), ('checks', 'the next frame', 2, 1, 400, 400)],
                         'B-22: a group with no check inside leaves no "0 checks passed"')
        self.assertEqual((t['result'], t['passed'], t['failed']), ('fail', 191, 1), 'every check counted, the group or not')
        self.assertEqual(t['marks'][3]['signal'], 'PREADY')
        import testmarks
        b = [testmarks.bookmark(m, 'TEST_CASE') for m in t['marks'] if m['kind'] == 'checks']
        self.assertEqual([(x['label'], x['text'], x['color']) for x in b],
                         [('✓ 188 checks', 'every word of the frame: 188 checks passed', '#2f9e44'), ('✓ 1 check', 'the tail: 1 check passed', '#2f9e44'),
                          ('✗ 1 of 2 failed', 'the next frame: 1 of 2 checks passed', '#e03131')])

    def test_measure_check_and_misuse(self):
        wl = self.marks()

        async def one(dut):
            with wl.measure('slow', max='10ps', check=True):
                self.t = 50
        t = self.run_test(wl, one)['tests'][0]
        self.assertEqual((t['result'], t['failed'], t['measures'][0]['ok']), ('fail', 1, False))
        self.assertIn('slow: 0.05 ns, outside', t['message'])
        with self.assertRaisesRegex(RuntimeError, 'stop\\(\\) without start'):
            wl.measure('x').stop()
        with self.assertRaisesRegex(ValueError, 'no bound'):
            wl.measure('x', max='soon')

    def test_a_label_that_is_no_text(self):
        """B-19 of the review of 2026-11-03: a label or colour that is no JSON text does not take the test's verdict."""
        wl = self.marks()

        async def odd(dut):
            wl.note('odd', label=b'bytes', color=7)
            wl.check(1, 1, 'one')
        t = self.run_test(wl, odd)['tests'][0]
        self.assertEqual((t['result'], t['marks'][0]['label'], t['marks'][0]['color']), ('pass', "b'bytes'", '7'))
        self.assertFalse(os.path.exists(self.path + '.tmp'))

    def test_a_test_awaited_inside_another(self):
        """B-20: one test awaited by another is a part of it: the outer keeps its marks and its verdict."""
        wl = self.marks()

        async def inner(dut):
            wl.note('in')
        go_inner = wl.test()(inner)

        async def outer(dut):
            await go_inner(dut)
            wl.check(2, 2, 'after')
        t = self.run_test(wl, outer)['tests']
        self.assertEqual([(x['name'], x['result'], x['passed']) for x in t], [('outer', 'pass', 1)])
        self.assertEqual([m['text'] for m in t[0]['marks'] if m['kind'] == 'note'], ['in'])

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

    def test_a_step_lasts_to_the_next_and_the_test_s_end(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')

        async def one(dut):
            wl.step('first')
            self.t = 10
            wl.step('second')
            self.t = 30
        t = self.run_test(wl, one, dut)['tests'][0]
        self.assertEqual(t['phases'], [{'label': 'first', 'from': 0, 'to': 10, 'step': 1}, {'label': 'second', 'from': 10, 'to': 30, 'step': 2}])
        self.assertEqual(dut.TEST_STEP.values[-1], 0, 'the row back at the end')
        self.assertIsNone(wl.step_open)

    def test_a_step_ended_by_a_failure_is_kept(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')

        async def one(dut):
            wl.step('it')
            self.t = 7
            raise AssertionError('no')
        self.assertEqual(self.run_test(wl, one, dut)['tests'][0]['phases'], [{'label': 'it', 'from': 0, 'to': 7, 'step': 1}])

    def test_a_step_outside_a_test_does_nothing(self):
        wl = self.marks()
        wl.step('nowhere')
        self.assertIsNone(wl.step_open)

    def test_the_whole_docstring(self):
        wl = self.marks()

        async def one(dut):
            """After reset both FSMs idle with no start
            and no resend update, data alone.

            The second paragraph
            says more.
            """
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        self.assertEqual(t['doc'], 'After reset both FSMs idle with no start and no resend update, data alone.')
        self.assertTrue(t['text'].endswith('The second paragraph\nsays more.'), t['text'])

    def test_a_one_line_docstring_needs_no_text(self):
        wl = self.marks()

        async def one(dut):
            """One line."""
        self.assertNotIn('text', self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0])

    def test_checks_are_counted_with_no_bookmark(self):
        wl = self.marks()

        async def one(dut):
            for i in range(188):
                wl.check(i, i, show='fail')
            wl.check(1, 2)
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        self.assertEqual((t['passed'], t['failed'], len(t['marks'])), (188, 1, 1))

    def test_why_is_read_only_on_a_failure(self):
        wl = self.marks()
        read = []

        async def one(dut):
            wl.check(1, 1, 'the frame', why=lambda: read.append(1) or 'never')
            wl.check(1, 2, 'the frame', why=lambda: read.append(2) or f'word {[][1:] or "none"}')
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        self.assertEqual(read, [2])
        self.assertEqual(t['marks'][0]['text'], 'the frame', 'the green one keeps its text')
        self.assertEqual(t['marks'][1]['text'], 'word none')
        self.assertEqual(t['message'], 'word none: got 1, expected 2')

    def test_a_why_that_raises_changes_nothing(self):
        wl = self.marks()

        async def one(dut):
            wl.check(1, 2, 'the frame', why=lambda: [][3])
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        self.assertEqual(t['result'], 'fail')
        self.assertIn('the frame (why: IndexError', t['message'])
        self.assertIn('got 1, expected 2', t['message'])

    def test_a_long_list(self):
        wl = self.marks()
        a, b = list(range(256)), list(range(256))
        b[17] = 0xFF

        async def one(dut):
            wl.check(a, b, 'every word')
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        m = t['marks'][0]
        self.assertEqual(m['got'], '[0, 1, 2, … 256 items]')
        self.assertEqual(m['at'], ' (at [17]: 0x11, 0xFF)')
        self.assertTrue(m['got_all'].startswith('[0, 1, 2, 3, 4'))
        self.assertEqual(t['message'], 'every word: got [0, 1, 2, … 256 items], expected [0, 1, 2, … 256 items] (at [17]: 0x11, 0xFF)')

    def test_a_list_in_one_radix_short_or_long(self):   # WL-008
        for v in ([0x10000000] * 4, [0x10000000], 0x10000000):
            self.assertNotIn('268435456', wc.short_of(v, wc.text_of(v)))
        self.assertEqual(wc.text_of([0x10000000]), '[0x10000000]')
        self.assertEqual(wc.short_of([0x10000000] * 4, wc.text_of([0x10000000] * 4)), '[0x10000000, 0x10000000, 0x10000000, … 4 items]')
        self.assertEqual(wc.text_of([1, [16, -16], (255,), (1, 2), b'\x10', True, 'ok']), "[1, [0x10, -0x10], (0xFF,), (1, 2), [0x10], 1, ok]")
        self.assertEqual(wc.text_of([Vector(255), Vector(None)]), '[0xFF, xxxx]')
        # B-15: every container item by item in the radix of the waves, a dict's keys as they are, a cut tuple in its own brackets
        for v, want in (({'a': 255, 'b': [16, 17], 3: Vector(16)}, "{'a': 0xFF, 'b': [0x10, 0x11], 3: 0x10}"), ({}, '{}'), ({255, 16, 1}, '{1, 0x10, 0xFF}'),
                        (set(), 'set()'), (frozenset({32, 1}), 'frozenset({1, 0x20})'), (frozenset(), 'frozenset()'), ({'x', 'y'}, '{x, y}'),
                        (range(16, 32), 'range(0x10, 0x20)'), (range(0, 256, 16), 'range(0, 0x100, 0x10)'), (255.0, '255.0'), (-255, '-0xFF'),
                        ([{'w': 4096}], "[{'w': 0x1000}]"), ((), '()')):
            self.assertEqual(wc.text_of(v), want)
        long = tuple(range(100))
        self.assertEqual(wc.short_of(long, wc.text_of(long)), '(0, 1, 2, … 100 items)')
        self.assertEqual(wc.short_of(set(range(100)), wc.text_of(set(range(100)))), '{0, 1, 2, … 100 items}')
        d = {f'k{i}': 4096 + i for i in range(20)}
        self.assertEqual(wc.short_of(d, wc.text_of(d)), "{'k0': 0x1000, 'k1': 0x1001, 'k2': 0x1002, … 20 items}")
        wl = self.marks()

        async def one(dut):
            wl.check([0x10000000] * 4, [0x10000000], 'words')
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        self.assertEqual(t['message'], 'words: got [0x10000000, 0x10000000, 0x10000000, … 4 items], expected [0x10000000] (lengths 4, 1)')

    def test_one_radix_in_one_message(self):   # B-15: a dict beside a list, of different lengths: no decimal anywhere in the failure
        wl = self.marks()

        async def one(dut):
            wl.check({'a': 255, 'b': [16, 17, 18]}, {'a': 0xFF, 'b': [0x10, 0x11]}, 'regs')
        t = self.run_test(wl, one, Dut('TEST_CASE', 'TEST_STEP'))['tests'][0]
        self.assertTrue(t['message'].startswith("regs: got {'a': 0xFF, 'b': [0x10, 0x11, 0x12]}"), t['message'])
        self.assertIsNone(re.search(r'\b(255|16|17|18)\b', t['message']), t['message'])

    def test_a_long_text_is_cut_a_short_one_is_not(self):
        self.assertEqual(wc.short_of('abc', 'abc'), 'abc')
        self.assertEqual(wc.short_of(None, 'x' * 100), 'x' * 39 + '… (100 chars)')

    def test_lists_of_other_lengths(self):
        self.assertEqual(wc.first_diff([1, 2], [1, 2, 3]), ' (lengths 2, 3)')
        self.assertEqual(wc.first_diff(1, 2), '')

    def test_the_test_s_own_rows(self):
        wl = self.marks()

        async def one(dut):
            pass
        wl.begin(Dut('TEST_CASE', 'TEST_STEP'), one, ['*fifo_full', ' u_x.state'])
        self.assertEqual(wl.now_test['signals'], ['*fifo_full', 'u_x.state'])
        wl.end(None, {})
        wl.begin(Dut('TEST_CASE', 'TEST_STEP'), one, 'a, b')
        self.assertEqual(wl.now_test['signals'], ['a', 'b'])
        wl.end(None, {})

    def test_a_phase_in_readonly_fails_nothing(self):   # WL-004: cocotb refuses a write in ReadOnly; a description must not fail a test
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')
        dut.TEST_STEP = ReadOnlySig('dut.TEST_STEP')

        async def one(dut):
            dut.TEST_STEP.frozen = True
            self.t = 10
            with wl.phase('look'):
                self.t = 20
            wl.note('seen')
        t = self.run_test(wl, one, dut)['tests'][0]
        self.assertEqual(t['result'], 'pass')
        self.assertEqual(t['phases'], [{'label': 'look', 'from': 10, 'to': 20}], 'its time exact; no number: the row never had it')
        self.assertEqual(dut.TEST_STEP.values, [0], 'nothing written, nothing to restore')

    def test_a_phase_left_in_readonly_catches_up(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')
        dut.TEST_STEP = ReadOnlySig('dut.TEST_STEP')

        async def one(dut):
            with wl.phase('look'):
                self.t = 20
                dut.TEST_STEP.frozen = True
            self.t = 30
            dut.TEST_STEP.frozen = False
            wl.check(1, 1, show='fail')   # (a check leaves no bookmark: it is still the test's next call)
        t = self.run_test(wl, one, dut)['tests'][0]
        self.assertEqual(t['result'], 'pass')
        self.assertEqual(t['phases'], [{'label': 'look', 'from': 0, 'to': 20, 'step': 1}])
        self.assertEqual(dut.TEST_STEP.values, [0, 1, 0], 'the value back at the next call')

    def test_a_late_step_goes_with_the_test(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')
        dut.TEST_STEP = ReadOnlySig('dut.TEST_STEP')

        async def one(dut):
            with wl.phase('look'):
                dut.TEST_STEP.frozen = True

        async def two(dut):
            dut.TEST_STEP.frozen = False
            wl.note('here')
        self.run_test(wl, one, dut)
        dut.TEST_STEP.frozen = False
        self.run_test(wl, two, dut)
        self.assertEqual(dut.TEST_STEP.values, [0, 1, 0], 'the next test begins at 0, nothing left over')

    def test_another_error_of_a_write_is_not_hidden(self):
        wl = self.marks()
        dut = Dut('TEST_CASE', 'TEST_STEP')
        dut.TEST_STEP = ReadOnlySig('dut.TEST_STEP')
        dut.TEST_STEP.error = 'the simulator is gone'

        async def one(dut):
            dut.TEST_STEP.frozen = True
            with wl.phase('look'):
                pass
        t = self.run_test(wl, one, dut)['tests'][0]
        self.assertEqual((t['result'], t['message']), ('fail', 'RuntimeError: the simulator is gone'))

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
        real = {n for n in ('test', 'phase', 'step', 'note', 'check', 'measure')}
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

    def test_the_docs_copy_it(self):
        """The lines the docs give to copy take what the library takes: a copy made from an old one fails on `signals=`."""
        for name in ('docs/USAGE.md', 'docs/guides/cocotb.html'):
            with open(os.path.join(H.ROOT, name), encoding='utf-8') as f:
                text = re.search(r'    class Marks:\n(.*?assert got == expected[^\n<]*)', f.read(), re.S).group(0)
            cocotb = types.SimpleNamespace(test=lambda *a, **kw: kw)
            space = {'cocotb': cocotb, 'contextlib': contextlib}
            exec(textwrap.dedent(text), space)
            wl = space['Marks']()
            self.assertEqual(wl.test(timeout_time=5, signals=['x']), {'timeout_time': 5}, name)
            self.assertEqual(wl.step('s', signals=None), None, name)
            with wl.phase('p'):
                wl.note('n', signal=None)
            with wl.measure('m', max='3 cycles', signal=None, check=True) as m:
                m.stop()
            with self.assertRaises(AssertionError):
                wl.check(1, 2, 'text', why=None)

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


class Report(unittest.TestCase):   # what the marks of a test give the page and the agents
    DOC = {'signal': 'TEST_CASE', 'tests': [{'n': 1, 'name': 'a', 'doc': 'One line.', 'text': 'One line.\n\nThe rest.', 'from': 0, 'to': 100, 'result': 'pass', 'message': '',
           'where': '', 'phases': [], 'passed': 188, 'failed': 0, 'signals': ['*fifo_full', 'u_x.state'],
           'marks': [{'t': 5, 'kind': 'check', 'ok': False, 'got': '[1, 2, 3, … 256 items]', 'expected': '[1, 2, 3, … 256 items]', 'got_all': '[1, 2, 3, 4]',
                      'expected_all': '[1, 2, 3, 5]', 'at': ' (at [3]: 4, 5)', 'text': 'words'}]}]}

    def test_a_long_value_short_by_its_circle_whole_in_the_list(self):
        b = testmarks.bookmark(self.DOC['tests'][0]['marks'][0], None)
        self.assertEqual(b['label'], '✗ [1, 2, 3, … 256 items] ≠ [1, 2, 3, … 256 items]')
        self.assertEqual(b['text'], 'words: [1, 2, 3, 4], expected [1, 2, 3, 5] (at [3]: 4, 5)')

    def test_the_whole_text_in_the_first_bookmark(self):
        self.assertIn('starts: One line. The rest.', testmarks.marks_of(self.DOC)[0][0]['text'])

    def test_the_count_under_the_title_and_the_rows_of_the_test(self):
        cfg = {'signals': ['clk'], 'views': {'run': {'exact': True}}}
        nav = testmarks.merge(cfg, json.loads(json.dumps(self.DOC)), 'tests')
        v = cfg['views'][nav[0]['key']]
        self.assertEqual(v['note'], 'One line. · 188 checks passed')
        self.assertEqual(v['also'], ['*fifo_full', 'u_x.state'])

    def test_checks_of_a_file_of_before(self):
        t = {'marks': [{'kind': 'check', 'ok': True}, {'kind': 'check', 'ok': False}, {'kind': 'note'}]}
        self.assertEqual(testmarks.checks_of(t), (2, 1))
        self.assertEqual(testmarks.checks_of({'passed': 188, 'failed': 1, 'marks': []}), (189, 1))


class ReadOnlyPhase(unittest.TestCase):
    def test_its_span_goes_on_the_step_row(self):   # no value on TEST_STEP says it, and the test's row keeps the test's name
        doc = {'signal': 'TEST_CASE', 'step': 'TEST_STEP', 'steps': {'1': 'a'}, 'tests': [{'n': 1, 'name': 't', 'doc': '', 'from': 0, 'to': 30, 'result': 'pass',
               'message': '', 'where': '', 'marks': [], 'phases': [{'label': 'look', 'from': 10, 'to': 20}, {'label': 'a', 'from': 20, 'to': 30, 'step': 1}]}]}
        spans = testmarks.marks_of(doc)[1]
        self.assertEqual([s['signals'] for s in spans if s.get('label') == 'look'], [['TEST_STEP']])
        self.assertFalse([s for s in spans if s.get('label') == 'a'], 'one the row says needs no span')


class Split(unittest.TestCase):
    def cfg(self):
        return {'views': {'v': {'signals': ['TEST_CASE', 'TEST_STEP', 'PSEL'], 'title': 'all', 'note': 'n', 'config': {'radix': 'hex'},
                                'bookmarks': [{'n': 1, 't': 5, 'text': 'by hand'}], 'spans': [{'from': 1, 'to': 2}], 'from': '0ps', 'to': '999ps'}}}

    def test_whole_is_as_before(self):
        c = self.cfg()
        self.assertEqual(testmarks.merge(c, DOC), [])
        self.assertEqual(list(c['views']), ['v'])

    def test_bookmarks_of_one_moment_apart(self):   # P-15
        ok, bad = testmarks.RESULTS['pass'][1], testmarks.RESULTS['fail'][1]
        b = [{'t': 5, 'signal': 'A', 'text': f'c{i}', 'color': ok} for i in range(4)] + [{'t': 5, 'signal': 'A', 'text': 'end', 'lift': 'above'},
             {'t': 5, 'signal': 'A', 'text': 'x', 'color': bad}, {'t': 6, 'signal': 'A', 'text': 'later'}, {'t': 5, 'signal': 'B', 'text': 'b1'},
             {'t': 5, 'signal': 'B', 'text': 'b2'}, {'t': 9, 'text': 'axis 1'}, {'t': 9, 'text': 'axis 2'}]
        got = testmarks.one_moment(b)
        self.assertEqual([(x['signal'] if 'signal' in x else None, x.get('lift'), x.get('label'), x['text']) for x in got],
                         [('A', None, None, 'c0'), ('A', 'below', '+4', '4 more at this time: c1 · c2 · c3 · x'), ('A', 'above', None, 'end'),
                          ('A', None, None, 'later'), ('B', None, None, 'b1'), ('B', 'above', None, 'b2'), (None, None, '+2', '2 at this time: axis 1 · axis 2')])
        self.assertEqual(got[1]['color'], bad, 'a failure among them: the circle is red')
        self.assertEqual(testmarks.one_moment(b[6:7]), b[6:7])
        c = Split.cfg(self)
        doc = json.loads(json.dumps(DOC))
        doc['tests'][0]['marks'] = [{'t': 7, 'kind': 'check', 'ok': True, 'got': str(i), 'expected': str(i), 'text': '', 'signal': 'PSEL'} for i in range(6)]
        testmarks.merge(c, doc)
        on = [x for x in c['views']['v']['bookmarks'] if x['t'] == 7]
        self.assertEqual([(x.get('lift'), x.get('label')) for x in on], [(None, '✓ 0'), ('above', '✓ 1'), ('below', '+4')])

    def test_one_row_of_two_spellings_is_one_moment(self):   # B-17: grouped by the row the page uses, after row_for
        c = Split.cfg(self)
        c['views']['v']['signals'] = ['TEST_CASE', 'TEST_STEP', 'tb.PSEL']
        doc = json.loads(json.dumps(DOC))
        doc['tests'][0]['marks'] = [{'t': 7, 'kind': 'check', 'ok': True, 'got': str(i), 'expected': str(i), 'text': '', 'signal': s}
                                    for i, s in enumerate(('PSEL', 'tb.PSEL', 'PSEL', 'tb.PSEL'))]
        testmarks.merge(c, doc)
        on = [x for x in c['views']['v']['bookmarks'] if x['t'] == 7]
        self.assertEqual([(x['signal'], x.get('lift'), x.get('label')) for x in on],
                         [('tb.PSEL', None, '✓ 0'), ('tb.PSEL', 'above', '✓ 1'), ('tb.PSEL', 'below', '+2')], 'one group, not two circles on one spot')

    def test_a_pattern_of_a_row_is_its_moment(self):   # review 2026-11-05 (runs) B-29: a pattern resolved before grouping
        c = Split.cfg(self)
        doc = json.loads(json.dumps(DOC))
        doc['tests'][0]['marks'] = [{'t': 7, 'kind': 'check', 'ok': True, 'got': str(i), 'expected': str(i), 'text': '', 'signal': s}
                                    for i, s in enumerate(('PSEL', '*PSEL', 'PSEL', 'PS?L'))]
        testmarks.merge(c, doc)
        on = [x for x in c['views']['v']['bookmarks'] if x['t'] == 7]
        self.assertEqual([(x['signal'], x.get('lift'), x.get('label')) for x in on],
                         [('PSEL', None, '✓ 0'), ('PSEL', 'above', '✓ 1'), ('PSEL', 'below', '+2')], 'one group of PSEL\'s row')
        rows = {p: p for p in ('$rootio.PSEL', 'tb.PSEL', 'tb.u_x.PSEL', 'tb.TEST_CASE')}
        self.assertEqual([testmarks.row_for(rows, p) for p in ('*TEST_*', 'tb.u_*.PSEL', '*PSEL', '*nothing*')],
                         ['tb.TEST_CASE', 'tb.u_x.PSEL', '*PSEL', '*nothing*'], 'the one row it matches; several or none: as it is (the page decides)')

    def test_many_marks_of_one_moment(self):   # more than the lanes hold: one "+k", red when one of them failed
        c = Split.cfg(self)
        doc = json.loads(json.dumps(DOC))
        doc['tests'][0]['marks'] = [{'t': 7, 'kind': 'check', 'ok': i != 9, 'got': str(i), 'expected': '0' if i == 9 else str(i), 'text': '',
                                     'signal': 'PSEL'} for i in range(14)]
        testmarks.merge(c, doc)
        on = [x for x in c['views']['v']['bookmarks'] if x['t'] == 7]
        self.assertEqual([(x.get('lift'), x.get('label')) for x in on], [(None, '✓ 0'), ('above', '✓ 1'), ('below', '+12')])
        self.assertEqual(on[2]['color'], testmarks.COLORS0['fail'])
        self.assertTrue(on[2]['text'].startswith('12 more at this time: '), on[2]['text'])
        self.assertIn('9, expected 0', on[2]['text'])

    def test_colours_of_the_marks(self):   # P-13: "marksColors"
        doc = json.loads(json.dumps(DOC))
        doc['tests'][0]['marks'] = [{'t': 7, 'kind': 'note', 'text': 'n'}, {'t': 8, 'kind': 'log', 'level': 'WARNING', 'text': 'w'},
                                    {'t': 9, 'kind': 'log', 'level': 'ERROR', 'text': 'e'}, {'t': 10, 'kind': 'check', 'ok': True, 'got': '1', 'expected': '1', 'text': ''}]
        plain, c = self.cfg(), self.cfg()
        testmarks.merge(plain, doc)
        testmarks.merge(c, doc, 'both', colors={'pass': 'c3', 'fail': '#aa0000', 'note': '--my-note', 'warning': 'orange'})
        by = lambda v, t: next(b['color'] for b in v['bookmarks'] if b['t'] == t and b.get('text') != 'by hand' and not b.get('label', '').startswith('TC'))
        v, p = c['views']['v'], plain['views']['v']
        self.assertEqual([by(v, t) for t in (7, 8, 9, 10)], ['--my-note', 'orange', '#e03131', 'c3'], 'a key not given keeps its colour (log)')
        self.assertEqual([by(p, t) for t in (7, 8, 9, 10)], ['#1971c2', '#e8590c', '#e03131', '#2f9e44'])
        self.assertEqual([s['color'] for s in v['spans'] if s.get('label', '').startswith('TC')], ['c3', '#aa0000'])
        self.assertEqual(c['views']['tc2']['title'], 'TC2 b · FAIL')
        self.assertEqual(testmarks.COLORS, testmarks.COLORS0, 'the defaults again after the merge')
        for bad, msg in (({'pass': 'red; x'}, 'marksColors".pass'), ({'ok': '#fff'}, 'unknown key'), ('red', 'an object'),
                         ({'pass': 'foo'}, '"foo" is no token of the theme'), ({'fail': 'c99'}, '"c99" is no token'), ({'note': 'c1'}, '"c1" is no token')):
            with self.assertRaisesRegex(common.WaveError, msg):
                testmarks.merge(self.cfg(), doc, colors=bad)
        import mkhtml
        self.assertEqual([mkhtml.css_color(x) for x in ('c3', 'hl2', 'fg', '--mine', '#abc', 'orange', 'one', 'hl7', 'panel2')],
                         ['var(--wave-c3)', 'var(--wave-hl2)', 'var(--fg)', 'var(--mine)', '#abc', 'orange', 'var(--wave-1)', 'var(--accent)', 'var(--panel-2)'])
        testmarks.merge(self.cfg(), doc, colors={k: w for k, w in zip(testmarks.COLORS0, ('hl7', 'RebeccaPurple', 'paint', 'xsoft', 'acc', 'one', 'c9'))})
        css = H.text(os.path.join(H.ROOT, 'wavelens', 'wavelens.css'))
        for tok, var in testmarks.TOKENS.items():   # each token a variable the theme defines
            self.assertIn(f'{var}:', css, tok)
        js = H.text(os.path.join(H.ROOT, 'wavelens', 'src', 'model.js'))
        tok = re.search(r'const TOK = \{(.*?)\};', js, re.S).group(1)
        self.assertEqual(dict(re.findall(r"(\w+): '(--[\w-]+)'", tok)), testmarks.TOKENS, 'the tokens of the page (model.js TOK)')

    def test_phases_as_markers(self):   # P-14
        doc = json.loads(json.dumps(DOC))
        doc['tests'][0]['phases'].append({'label': 'none', 'from': 20, 'to': 20})   # of no time: no marker
        c = self.cfg()
        testmarks.merge(c, doc)
        self.assertFalse([m for m in c['views']['v']['marker'] if 't' in m], 'off by default')
        c = self.cfg()
        testmarks.merge(c, doc, phases=True)
        self.assertEqual([m for m in c['views']['v']['marker'] if 't' in m], [{'t': '0ps', 'label': 'reset'}, {'t': '10ps', 'label': 'on'}])
        c = self.cfg()
        testmarks.merge(c, doc, 'tests', phases=True)
        self.assertEqual(c['views']['tc1']['marker'], [{'t': '0ps', 'label': 'reset'}, {'t': '10ps', 'label': 'on'}])
        self.assertNotIn('marker', c['views']['tc2'])
        self.assertEqual(vcd2wavedrom.parse_markers([{'t': '10ns', 'label': 'x'}]), [({'t': 10000}, 'x', None)])
        with self.assertRaisesRegex(common.WaveError, '"t": TIME'):
            vcd2wavedrom.parse_markers([{'t': 'soon'}])
        with self.assertRaisesRegex(common.WaveError, '"t": TIME'):
            vcd2wavedrom.parse_markers([{'t': 5, 'on': 'clk'}])

    def test_measures_into_the_views(self):
        """Stage 17: a test's measurements -> the view's "measures" (vcd2wavedrom: the WaveJSON's) in the test's colour, on its row; the
        summary and the test's view say them; its steps by length."""
        doc = json.loads(json.dumps(DOC))
        doc['tests'][0]['measures'] = [{'label': 'r', 'from': 10, 'to': 40, 'max': '20ps', 'ok': False}, {'label': 'q', 'from': 50, 'to': 60, 'signal': 'PSEL'}]
        c = self.cfg()
        testmarks.merge(c, doc)
        self.assertEqual(c['views']['v']['measures'], [{'label': 'r', 'from': 10, 'to': 40, 'color': '#2f9e44', 'max': '20ps', 'signal': 'TEST_CASE'},
                                                      {'label': 'q', 'from': 50, 'to': 60, 'color': '#2f9e44', 'signal': 'PSEL'}])
        self.assertIn('2 measures, 1 out of bounds', testmarks.summary(doc))
        c = self.cfg()
        testmarks.merge(c, doc, 'tests')
        self.assertIn('2 measures, 1 out of bounds', c['views']['tc1']['note'])
        self.assertEqual(c['views']['tc2']['measures'], c['views']['tc1']['measures'], 'stage 24: every view of the tests has them all (shared markers)')
        self.assertIs(c.get('config', {}).get('sharedMarkers'), None, 'testmarks leaves the setting to mkhtml.py')
        self.assertEqual([p['label'] for p in testmarks.steps({'phases': [{'label': 'a', 'from': 0, 'to': 5}, {'label': 'b', 'from': 5, 'to': 30}]})], ['b', 'a'])
        a = vcd2wavedrom.parser().parse_args(['--measures', json.dumps([{'label': 'r', 'from': '10ns', 'to': 40000}])])
        self.assertEqual(vcd2wavedrom.measures_of(a), [{'label': 'r', 'from': 10000, 'to': 40000}])
        a = vcd2wavedrom.parser().parse_args(['--measures', '[{"from": "soon"}]'])
        with self.assertRaisesRegex(common.WaveError, 'measures\\[0\\]'):
            vcd2wavedrom.measures_of(a)

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
        self.assertEqual(a['note'], 'first · 1 check passed · 2 steps, longest reset 10 ps')
        self.assertEqual(b['note'], 'got 0, expected 1 (t.py:9) · 0 of 1 checks passed')
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

    def test_a_note_on_a_pattern(self):   # P-10
        doc = {**DOC, 'step': None, 'steps': {}}
        doc = json.loads(json.dumps(doc))
        doc['tests'][0]['marks'].append({'t': 60, 'kind': 'note', 'text': 'pattern', 'signal': '*SEL'})
        with open(self.marks, 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        rc, _, err = self.build('--marks', self.marks)
        self.assertEqual(rc, 0, err)
        self.assertNotIn('bookmark-signal-missing', err)
        waves = json.loads(re.search(r'window\.WAVES = (\{.*?\n\});', self.page(), re.S).group(1).replace('<\\/', '</'))
        self.assertEqual([b['signal'] for b in waves['v']['bookmarks'] if b.get('text') == 'pattern'], ['PSEL'])

    def test_colours_of_the_marks_on_the_page(self):   # P-13
        with open(self.cfg, encoding='utf-8') as f:
            c = json.load(f)
        with open(self.cfg, 'w', encoding='utf-8') as f:
            json.dump({**c, 'marksColors': {'pass': 'c3', 'fail': '#aa0000'}}, f)
        rc, _, err = self.build('--marks', self.marks, '--marks-views', 'tests')
        self.assertEqual(rc, 0, err)
        text = self.page()
        self.assertIn('data-view="tc1" style="--tc: var(--wave-c3)"', text)
        self.assertIn('data-view="tc2" style="--tc: #aa0000"', text)
        self.assertNotIn('marksColors', text, 'a key of the build, not of the page')

    def test_phases_as_markers_on_the_page(self):   # P-14: --marks-phases, the config's "marksPhases"
        rc, _, err = self.build('--marks', self.marks, '--marks-phases')
        self.assertEqual(rc, 0, err)
        self.assertNotIn('lint:', err.replace('bookmarks-close', ''))
        waves = json.loads(re.search(r'window\.WAVES = (\{.*?\n\});', self.page(), re.S).group(1).replace('<\\/', '</'))
        self.assertEqual([(m['t'], m['label']) for m in waves['v']['markers'] if not m['label'].startswith('TC')], [(0, 'reset'), (10, 'on')])
        rc, _, err = self.build('--marks', self.marks)
        waves = json.loads(re.search(r'window\.WAVES = (\{.*?\n\});', self.page(), re.S).group(1).replace('<\\/', '</'))
        self.assertEqual([m['label'] for m in waves['v']['markers']], ['TC1', 'TC2'])
        with open(self.cfg, encoding='utf-8') as f:
            c = json.load(f)
        with open(self.cfg, 'w', encoding='utf-8') as f:
            json.dump({**c, 'marksPhases': True}, f)
        rc, _, err = self.build('--marks', self.marks)
        self.assertEqual(rc, 0, err)
        self.assertIn('"label": "reset"', self.page())
        for bad in ('yes', 1, None):   # B-18: not a boolean was silently nothing
            with open(self.cfg, 'w', encoding='utf-8') as f:
                json.dump({**c, 'marksPhases': bad}, f)
            rc, _, err = self.build('--marks', self.marks)
            self.assertEqual(rc, 1, err)
            self.assertIn(f'mkhtml: "marksPhases": true or false, not {json.dumps(bad)}', err)

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

    def test_a_marks_file_with_a_bom(self):   # review 2026-11-05 (runs) B-27: saved again by a Windows editor, a BOM before it
        with open(self.marks, 'w', encoding='utf-8-sig') as f:
            json.dump({**DOC, 'step': None, 'steps': {}}, f)
        self.assertEqual(testmarks.load(self.marks)['wavelens'], 'marks')
        rc, _, err = self.build('--marks', self.marks)
        self.assertEqual(rc, 0, err)
        self.assertIn('mkhtml: marks: 2 tests: 1 passed, 1 failed', err)


if __name__ == '__main__':
    unittest.main()
