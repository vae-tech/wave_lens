"""Shared pieces of the unit tests: the fixtures, a scratch directory, the tools run as a user runs them."""
import contextlib, functools, io, json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, 'tools')
VCD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vcd')
BUILD = os.environ.get('BUILD') or os.path.join(ROOT, 'out')
STRICT = bool(os.environ.get('WAVELENS_STRICT'))   # make check: what the gate builds (the examples, sva) must be there
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
BLESS = bool(os.environ.get('WAVELENS_BLESS'))   # make unit-bless: the goldens written anew (then read the diff)


def skip(case, why, built=True):
    """case.skipTest(why); under make check (WAVELENS_STRICT) a test that lacks what the gate builds (built) fails instead:
    a parity test skipped on a clean tree passed the gate before (review IV B7). Other programs (GTKWave): built=False."""
    if STRICT and built:
        case.fail(f'not there though make check builds it: {why}')
    case.skipTest(why)


def needs(cond, why):
    """@unittest.skipUnless(cond, why), for a test or a class, that fails instead under make check (skip())."""
    if cond or not STRICT:
        return unittest.skipUnless(cond, why)
    def deco(obj):
        if isinstance(obj, type):
            obj.setUp = lambda self: self.fail(f'not there though make check builds it: {why}')
            return obj
        return functools.wraps(obj)(lambda self, *a, **k: self.fail(f'not there though make check builds it: {why}'))
    return deco


def fixture(name):
    """tests/unit/vcd/<name>.vcd"""
    return os.path.join(VCD, name + '.vcd')


def vcd(tmp, body, header='$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n$enddefinitions $end\n', name='t.vcd'):
    """A small VCD written into tmp -> its path."""
    p = os.path.join(tmp, name)
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(header + body)
    return p


def golden(case, name, text):
    """text is tests/unit/golden/<name> byte for byte (the bytes a page or a data file gets, not only what json reads back);
    WAVELENS_BLESS=1: written instead."""
    p = os.path.join(GOLDEN, name)
    if BLESS:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'w', encoding='utf-8', newline='') as f:
            f.write(text)
        return
    if not os.path.exists(p):
        case.fail(f'{p} is missing: make unit-bless writes it')
    with open(p, encoding='utf-8', newline='') as f:
        want = f.read()
    if text != want:
        a, b = text.splitlines(), want.splitlines()
        i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
        case.fail(f'{name}: not the golden bytes (make unit-bless if meant), line {i + 1}:\n  got  {a[i] if i < len(a) else "(end)"}\n'
                  f'  want {b[i] if i < len(b) else "(end)"}')


def until(cond, timeout, what):
    """Wait for cond() up to timeout seconds (review VI T10: no loop that waits for ever) -> its value; else AssertionError."""
    import time
    end = time.monotonic() + timeout
    while True:
        v = cond()
        if v:
            return v
        if time.monotonic() > end:
            raise AssertionError(f'not in {timeout} s: {what}')
        time.sleep(0.01)


def tmp():
    """with tmp() as d: a scratch directory removed afterwards."""
    return tempfile.TemporaryDirectory(prefix='wavelens-unit-')


def run_tool(name, *args, cwd=ROOT):
    """python3 -I tools/<name>.py ARGS -> (return code, stdout, stderr); a tool that hangs fails the test after 10 minutes
    (review VI T10), not the gate."""
    p = subprocess.run([sys.executable, '-I', os.path.join(TOOLS, name + '.py'), *map(str, args)], capture_output=True, text=True, cwd=cwd, timeout=600)
    return p.returncode, p.stdout, p.stderr


def wavejson_of(path, *args):
    """vcd2wavedrom.py --waves path --exact --hierarchy over every variable of the dump (or ARGS) -> {path: signal}."""
    import dumpscan
    if not args:
        d = dumpscan.read(path, None)
        args = ('--exact', '--hierarchy', '--signals', ','.join(p for p, v in d.vars.items() if v.kind != 'event'))
    rc, out, err = run_tool('vcd2wavedrom', '--waves', path, *args)
    if rc:
        raise AssertionError(f'vcd2wavedrom {path}: {err.strip()}')
    doc = json.loads(out)
    sigs = {}
    def walk(items):
        for it in items:
            if isinstance(it, list):
                walk(it[1:] if it and isinstance(it[0], str) else it)
            elif isinstance(it, dict) and ('tv' in it or 'wave' in it or 'same' in it):
                sigs[it.get('path') or it['name']] = it
    walk(doc['signal'])
    for s in sigs.values():
        if 'same' in s:
            s['tv'] = sigs[s['same']]['tv']
    return sigs


@contextlib.contextmanager
def stderr():
    """with stderr() as e: …; e.getvalue(): what the code printed to stderr."""
    buf, old = io.StringIO(), sys.stderr
    sys.stderr = buf
    try:
        yield buf
    finally:
        sys.stderr = old
