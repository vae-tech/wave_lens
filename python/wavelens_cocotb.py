"""wavelens_cocotb.py — a cocotb test marks up its own waves: which test ran when, what it did, what it expected.

    from wavelens_cocotb import Marks
    wl = Marks()                                    # the testbench's TEST_CASE gets the running test's number, TEST_STEP its phase's

    @wl.test()                                      # cocotb.test() with the same arguments
    async def test_read_back(dut):
        '''The register keeps what was written.'''  # the first line goes into the test's first bookmark
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

With WAVELENS_MARKS=off the test is plain cocotb: no signal written, no file, the logs left alone; `note` and `phase` do nothing,
`check` still compares and fails the test (a check that went quiet would pass anything). The same for a tree without this file: the
few lines of examples/cocotb_apb/test_apb.py (`except ImportError`) give a test the same calls, and it runs as it is.

cocotb itself is imported only inside a running test's module, as this file's first use asks for it. docs/USAGE.md
§ "Marks from a cocotb test".
"""
import functools, json, logging, os, traceback

__all__ = ['Marks']
FORMAT = 1
MAX_MARKS = 200   # a test's bookmarks kept; past it only failures and errors (a check in a loop of thousands stays a page)


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


def same(got, expected):
    """got == expected, a logic vector with x or z being equal to nothing but itself (cocotb raises on some of these)."""
    try:
        return bool(got == expected)
    except (TypeError, ValueError):
        return False


def where_of(exc):
    """The line of the test that raised: the last frame outside this file, "test_apb.py:88"."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename != __file__]
    return f'{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}' if frames else ''


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
    marks file (default the environment's WAVELENS_MARKS, else wavelens.marks.json; "off": plain cocotb); `logs`: False leaves the logs out."""

    def __init__(self, signal='TEST_CASE', step='TEST_STEP', path=None, logs=True):
        self.signal, self.step, self.logs = signal, step, logs
        self.steps, self.step_now, self.step_handle = {}, 0, None   # label -> its number on the waves; 0: no phase
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

    def check(self, got, expected, text='', signal=None, show='all'):
        """got == expected: a bookmark with both (`show='fail'`: only when they differ, for a check in a loop); else AssertionError,
        which fails the test."""
        ok = same(got, expected)
        g, e = text_of(got), text_of(expected)
        if not ok or show == 'all':
            self.add({'kind': 'check', 'ok': ok, 'got': g, 'expected': e, 'text': str(text), 'signal': self.row(signal)}, keep=not ok)
        if not ok:
            raise AssertionError(f'{text + ": " if text else ""}got {g}, expected {e}')

    # ---------------- the test decorator ----------------
    def test(self, *args, **kw):
        """`@wl.test()` over an `async def test_x(dut)`: cocotb.test() with the same arguments, and the test's marks around it
        (WAVELENS_MARKS=off: cocotb.test() alone)."""
        import cocotb
        if self.path == 'off':
            return cocotb.test(*args, **kw)
        if len(args) == 1 and callable(args[0]) and not kw:
            return self.test()(args[0])

        def wrap(fn):
            @functools.wraps(fn)
            async def run(dut, *a, **k):
                self.begin(dut, fn)
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

    def begin(self, dut, fn):
        self.dut, self.last_log = dut, ''
        doc = (fn.__doc__ or '').strip().split('\n')[0].strip()
        n = len(self.tests) + 1
        self.now_test = {'n': n, 'name': fn.__name__, 'doc': doc, 'from': self.now(), 'to': None, 'result': 'run', 'message': '', 'where': '',
                         'phases': [], 'marks': [], 'dropped': 0}
        self.tests.append(self.now_test)
        self.save()   # a crash inside the test leaves it, result "run"
        handle = self.signal and getattr(dut, self.signal, None)
        self.step_handle = self.step and getattr(dut, self.step, None)
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
                t['where'] = where_of(exc)
        self.save()

    def set_step(self, n):
        self.step_now = n
        if self.step_handle is not None:
            self.step_handle.value = n

    def add(self, mark, keep=False):
        t = self.now_test
        if t is None:   # outside a test: nothing to hang it on, and no reason to fail
            return
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
            doc.update(step=self.step, steps={str(n): label for label, n in self.steps.items()})
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
            self.number = m.steps.setdefault(self.label, len(m.steps) + 1)
            m.set_step(self.number)
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
