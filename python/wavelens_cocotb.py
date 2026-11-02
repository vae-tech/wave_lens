"""wavelens_cocotb.py — a cocotb test marks up its own waves: which test ran when, what it did, what it expected.

    from wavelens_cocotb import Marks
    wl = Marks()                                    # the testbench's TEST_CASE gets the running test's number, TEST_STEP its phase's

    @wl.test()                                      # cocotb.test() with the same arguments
    async def test_read_back(dut):
        '''The register keeps what was written.'''  # its first paragraph goes into the test's first bookmark
        with wl.phase('write'):                     # a stretch of time with a name: a value of TEST_STEP on the waves
            await apb_write(dut, 0x08, 0xCAFE)
        wl.note('the slave stretches this read', signal=dut.PREADY)
        got = await apb_read(dut, 0x08)
        wl.check(got, 0xCAFE, 'DATA reads back', signal=dut.PRDATA)   # a bookmark; a mismatch fails the test

The simulation leaves a dump and, beside it, the marks: WAVELENS_MARKS (default wavelens.marks.json), written after each
test, so a crash keeps the tests before it. The dump is not finished while the test runs, so the page is built after it:

    mkhtml.py --config x.config.json --waves dump.vcd --marks wavelens.marks.json --out x.html

Each test gets a span in the colour of its result, a bookmark at its start and one at its end (PASS or FAIL, what was
expected and what came, the line of the test), a jump button; warnings and errors of the logs during a test are bookmarks
too; the two signals carry the names of the tests and the phases. Nothing here fails a test by itself: only `check` does,
by design. Without TEST_CASE in the design the marks are still made (a warning says so), without TEST_STEP a phase is a
span on the test's row.

`@wl.test(signals=["*fifo_full", "u_x.state"])`: the test's own rows, added to its view with --marks-views tests. `wl.step('…')`: a phase
in one line, until the next step or the test's end. `check(…, why=lambda: …)`: the text of a failure, read only then. `Marks(hide=["my_checks.py"])`:
a file that is not the line of a failure.

With WAVELENS_MARKS=off the test is plain cocotb: no signal written, no file, the logs left alone; `note` and `phase` do nothing,
`check` still compares and fails the test (a check that went quiet would pass anything). The same for a tree without this file: the
few lines of examples/cocotb_apb/test_apb.py (`except ImportError`) give a test the same calls, and it runs as it is.

cocotb itself is imported only inside a running test's module, as this file's first use asks for it. docs/USAGE.md
§ "Marks from a cocotb test".
"""
import fnmatch, functools, inspect, json, logging, os

__all__ = ['Marks']
FORMAT = 1
MAX_MARKS = 200   # a test's bookmarks kept; past it only failures and errors (a check in a loop of thousands stays a page)
SHORT = 40   # a value's text by a circle, in characters
LONG = 4000  # and in the list, where the whole of it goes


def text_of(v):
    """A value as the waves show it: an integer in hex (below 10 as it is), a logic vector the same when it has no x or z."""
    if isinstance(v, bool):
        return str(int(v))
    if not isinstance(v, int):
        try:
            v = v.to_unsigned()   # cocotb's LogicArray
        except (AttributeError, ValueError):
            return str(v)
    return str(v) if -10 < v < 10 else f'-0x{-v:X}' if v < 0 else f'0x{v:X}'


def short_of(v, text):
    """A value's text as a label: a long list "[1, 2, 3, … 256 items]", another long text cut."""
    if len(text) <= SHORT:
        return text
    if isinstance(v, (list, tuple, bytes, bytearray)):
        return f'[{", ".join(text_of(x) for x in v[:3])}, … {len(v)} items]'
    return f'{text[:SHORT - 1]}… ({len(text)} chars)'


def first_diff(got, expected):
    """Where two lists part, as their labels may not say it: " (at [17]: 0, 0x20000)"; "" for anything else."""
    seq = (list, tuple, bytes, bytearray)
    if not isinstance(got, seq) or not isinstance(expected, seq):
        return ''
    at = next((i for i, (a, b) in enumerate(zip(got, expected)) if not same(a, b)), None)
    return f' (lengths {len(got)}, {len(expected)})' if at is None else f' (at [{at}]: {text_of(got[at])}, {text_of(expected[at])})'


def same(got, expected):
    """got == expected, a logic vector with x or z being equal to nothing but itself (cocotb raises on some of these)."""
    try:
        return bool(got == expected)
    except (TypeError, ValueError):
        return False


def where_of(exc, hide=()):
    """The line of the test that raised: the last frame outside this file, "test_apb.py:88", past the files of `hide` (names or patterns: a
    project's own check function) and the frames that set __tracebackhide__ (pytest's mark)."""
    own = where_of.__code__.co_filename   # not __file__: a cached compile keeps the path it was made under (cocotb's assertion rewriting, a symlink)
    last, tb = '', exc.__traceback__
    while tb is not None:
        name = tb.tb_frame.f_code.co_filename
        base = os.path.basename(name)
        if name != own and not tb.tb_frame.f_locals.get('__tracebackhide__') and not any(fnmatch.fnmatch(base, h) or fnmatch.fnmatch(name, h) for h in hide):
            last = f'{base}:{tb.tb_lineno}'
        tb = tb.tb_next
    return last


def verdict(exc, expect_fail=False, expect_error=()):
    """What cocotb will say of a test that raised exc (regression.py _score_test, in the same order) -> pass, xfail or fail."""
    if exc is None or type(exc).__name__ == 'TestSuccess':   # cocotb.pass_test()
        return 'fail' if expect_error or expect_fail else 'pass'
    if expect_fail:
        return 'xfail' if isinstance(exc, AssertionError) or type(exc).__name__ == 'Failed' else 'fail'
    return 'pass' if expect_error and isinstance(exc, expect_error) else 'fail'


def said(exc, last_log):
    """A test's exception in a line: an assertion's own text; a cancelled test (a timeout, a failed task) what the log said last."""
    if type(exc).__name__ in ('CancelledError', 'GeneratorExit'):
        return f'stopped: {last_log}' if last_log else 'stopped: a timeout or a failed task'
    text = str(exc)
    if isinstance(exc, AssertionError) and text:
        return text
    return f'{type(exc).__name__}: {text}' if text else type(exc).__name__


class LogTap(logging.Handler):
    """The warnings and errors logged during a test -> bookmarks."""

    def __init__(self, marks):
        super().__init__(logging.WARNING)
        self.marks = marks

    def emit(self, record):
        self.marks.logged(record)


class Marks:
    """What one simulation marks. `signal`: the testbench's test number (None: no such signal); `step`: its phase's; `path`: the
    marks file (default the environment's WAVELENS_MARKS, else wavelens.marks.json; "off": plain cocotb); `logs`: False leaves the logs out;
    `hide`: files (names or patterns) that are not the line of a failure: a project's own check functions."""

    def __init__(self, signal='TEST_CASE', step='TEST_STEP', path=None, logs=True, hide=()):
        self.signal, self.step_name, self.logs, self.hide = signal, step, logs, tuple(hide)
        self.step_open = None   # the phase of wl.step(): until the next one, or the test's end
        self.steps, self.step_now, self.step_handle, self.step_late = {}, 0, None, None   # label -> its number on the waves; 0: no phase
        self.path = path or os.environ.get('WAVELENS_MARKS') or 'wavelens.marks.json'
        self.tests, self.now_test, self.dut = [], None, None
        self.warned, self.last_log = False, ''
        self.tap = LogTap(self)

    # ---------------- inside a test ----------------
    def note(self, text, signal=None, label=None, color=None):
        """A bookmark now: on `signal` (a handle or a row's name; none: the test's row, or the time axis), `label` the short text
        beside the circle, `text` the long one of the list."""
        self.add({'kind': 'note', 'text': str(text), 'signal': self.row(signal), 'label': label, 'color': color})

    def phase(self, label, signals=None):
        """`with wl.phase('write'): …`: a stretch of time with a name: a value of TEST_STEP (`signals`, or no such signal: a span on
        those rows, or on the test's). Not awaited."""
        return Phase(self, label, signals)

    def step(self, label, signals=None):
        """`wl.step('the leader goes out')`: a phase in one line, until the next step or the end of the test: nothing to re-indent. Inside a `with
        wl.phase`, the `with` ends it on the row."""
        self.step_end()
        if self.now_test is not None:
            self.step_open = Phase(self, label, signals).__enter__()

    def step_end(self):
        p, self.step_open = self.step_open, None
        if p is not None:
            p.__exit__()

    def check(self, got, expected, text='', signal=None, show='all', why=None):
        """got == expected: a bookmark with both (`show='fail'`: only when they differ, for a check in a loop; the test still counts it); else
        AssertionError, which fails the test. `why`: the text of a failure in place of `text`, a string or a function called only then, for what can be
        read only when it failed."""
        self.step_catch_up()
        ok = same(got, expected)
        got_all, want_all = text_of(got), text_of(expected)
        g, e = short_of(got, got_all), short_of(expected, want_all)
        if self.now_test is not None:
            self.now_test['passed' if ok else 'failed'] += 1
        if not ok and why is not None:
            try:
                text = why() if callable(why) else why
            except Exception as err:   # (a description must not change what the test says)
                text = f'{text} (why: {err!r})'
        at = '' if ok else first_diff(got, expected)
        if not ok or show == 'all':
            self.add({'kind': 'check', 'ok': ok, 'got': g, 'expected': e, 'text': str(text), 'signal': self.row(signal),
                      'got_all': got_all[:LONG] if g != got_all else None, 'expected_all': want_all[:LONG] if e != want_all else None, 'at': at or None}, keep=not ok)
        if not ok:
            raise AssertionError(f'{str(text) + ": " if text else ""}got {g}, expected {e}{at}')

    # ---------------- the test decorator ----------------
    def test(self, *args, **kw):
        """`@wl.test()` over an `async def test_x(dut)`: cocotb.test() with the same arguments, and the test's marks around it
        (WAVELENS_MARKS=off: cocotb.test() alone)."""
        import cocotb
        rows = kw.pop('signals', None)   # the test's own rows in its view: `signals=["*fifo_full", "u_x.state"]`, names or patterns
        if self.path == 'off':
            return cocotb.test(*args, **kw)
        if len(args) == 1 and callable(args[0]) and not kw:
            return self.test()(args[0])

        def wrap(fn):
            @functools.wraps(fn)
            async def run(dut, *a, **k):
                self.begin(dut, fn, rows)
                try:
                    await fn(dut, *a, **k)
                except BaseException as e:   # also the cancelling of a timed-out test: said, and raised on
                    self.end(e, kw)
                    raise
                self.end(None, kw)
            return cocotb.test(*args, **kw)(run)
        return wrap

    # ---------------- the rest ----------------
    def now(self):
        """The simulation's time in ps."""
        from cocotb.utils import get_sim_time
        t = get_sim_time('ps')
        return int(t) if float(t).is_integer() else t

    def row(self, signal):
        """A row's name: a handle's path under the top (`dut.u_x.sig`: "u_x.sig"), or the name given."""
        if signal is None or isinstance(signal, str):
            return signal
        path, top = str(signal._path), str(self.dut._path) if self.dut is not None else ''
        return path[len(top) + 1:] if top and path.startswith(top + '.') else path

    def begin(self, dut, fn, rows=None):
        self.dut, self.last_log = dut, ''
        text = inspect.cleandoc(fn.__doc__ or '')
        doc = ' '.join(text.split('\n\n')[0].split())   # its first paragraph, a line however it is wrapped
        n = len(self.tests) + 1
        self.now_test = {'n': n, 'name': fn.__name__, 'doc': doc, 'from': self.now(), 'to': None, 'result': 'run', 'message': '', 'where': '',
                         'phases': [], 'marks': [], 'dropped': 0, 'passed': 0, 'failed': 0}
        if text != doc:
            self.now_test['text'] = text
        if rows:
            one = rows.split(',') if isinstance(rows, str) else rows
            self.now_test['signals'] = [s.strip() if isinstance(s, str) else self.row(s) for s in one]
        self.tests.append(self.now_test)
        self.save()   # a crash inside the test leaves it, result "run"
        handle = self.signal and getattr(dut, self.signal, None)
        self.step_handle, self.step_late = self.step_name and getattr(dut, self.step_name, None), None
        self.set_step(0)
        if handle is not None:
            handle.value = n
        elif self.signal and not self.warned:
            self.warned = True
            logging.getLogger('wavelens').warning('no signal %s in %s: its number is not in the dump (the marks are)', self.signal, dut._path)
        if self.logs:
            logging.getLogger().addHandler(self.tap)

    def end(self, exc, opts):
        """The test's end: its result from what it raised, what cocotb will say of it (`expect_fail`, `expect_error`)."""
        self.step_end()
        logging.getLogger().removeHandler(self.tap)
        t, self.now_test = self.now_test, None
        if t is None:
            return
        t['to'] = self.now()
        t['result'] = verdict(exc, opts.get('expect_fail', False), opts.get('expect_error', ()))
        if exc is None or type(exc).__name__ == 'TestSuccess':
            if t['result'] == 'fail':
                t['message'] = 'passed, but the test expects a failure'
        else:
            t['message'] = said(exc, self.last_log)
            if type(exc).__name__ not in ('CancelledError', 'GeneratorExit'):   # (else the line is cocotb's)
                t['where'] = where_of(exc, self.hide)
        self.save()

    def set_step(self, n, wait=True):
        """The step signal to n -> False in cocotb's ReadOnly, where nothing can be written, and a description must not fail a test: with `wait` the
        value goes at the test's next call. Never a task that writes later: a task primed in ReadOnly and cancelled at the test's end crashes Verilator 5."""
        if self.step_handle is None:
            self.step_now = n
            return True
        try:
            self.step_handle.value = n
        except RuntimeError as e:
            if 'ReadOnly' not in str(e):
                raise
            if wait:
                self.step_now, self.step_late = n, n
            return False
        self.step_now, self.step_late = n, None
        return True

    def step_catch_up(self):
        if self.step_late is not None:
            self.set_step(self.step_late)

    def add(self, mark, keep=False):
        t = self.now_test
        if t is None:   # outside a test: nothing to hang it on, and no reason to fail
            return
        self.step_catch_up()
        if len(t['marks']) >= MAX_MARKS and not keep:
            t['dropped'] += 1
            return
        t['marks'].append({'t': self.now(), **{k: v for k, v in mark.items() if v is not None}})

    def logged(self, record):
        if self.now_test is not None and not getattr(self, 'in_log', False):
            self.in_log = True   # a handler that logged would come back here
            try:
                exc = record.exc_info[1] if record.exc_info else None
                text = record.getMessage() or (said(exc, '') if exc else '')
                if exc is not None or record.levelno >= logging.ERROR:   # (cocotb says a task's exception as a warning)
                    self.last_log = text
                self.add({'kind': 'log', 'level': record.levelname, 'text': text}, keep=record.levelno >= logging.ERROR)
            finally:
                self.in_log = False

    def save(self):
        doc = {'wavelens': 'marks', 'version': FORMAT, 'signal': self.signal, 'tests': self.tests}
        if self.steps:
            doc.update(step=self.step_name, steps={str(n): label for label, n in self.steps.items()})
        tmp = f'{self.path}.tmp'
        try:
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError as e:
            logging.getLogger('wavelens').warning('marks not written: %s', e)


class Phase:
    """wl.phase(): the stretch between entering and leaving, ended also by a failure inside it."""

    def __init__(self, marks, label, signals):
        self.marks, self.label, self.signals = marks, str(label), signals

    def __enter__(self):
        m = self.marks
        self.t, self.start, self.before, self.number = m.now_test, m.now(), m.step_now, None
        if self.t is not None and m.step_handle is not None and not self.signals:
            n = m.steps.setdefault(self.label, len(m.steps) + 1)
            self.number = n if m.set_step(n, wait=False) else None   # in ReadOnly: no value on the row, its span says the phase
        return self

    def __exit__(self, *exc):
        if self.t is not None:
            one = [self.signals] if isinstance(self.signals, str) or hasattr(self.signals, '_path') else self.signals
            p = {'label': self.label, 'from': self.start, 'to': self.marks.now()}
            if self.number is not None:
                p['step'] = self.number
                self.marks.set_step(self.before)
            elif one:
                p['signals'] = [self.marks.row(s) for s in one]
            self.t['phases'].append(p)
        return False
