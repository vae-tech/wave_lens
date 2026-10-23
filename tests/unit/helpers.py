"""Shared pieces of the unit tests: the fixtures, a scratch directory, the tools run as a user runs them."""
import contextlib, io, json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, 'tools')
VCD = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vcd')
BUILD = os.environ.get('BUILD') or os.path.join(ROOT, 'out')


def fixture(name):
    """tests/unit/vcd/<name>.vcd"""
    return os.path.join(VCD, name + '.vcd')


def vcd(tmp, body, header='$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! s $end\n$upscope $end\n$enddefinitions $end\n', name='t.vcd'):
    """A small VCD written into tmp -> its path."""
    p = os.path.join(tmp, name)
    with open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(header + body)
    return p


def tmp():
    """with tmp() as d: a scratch directory removed afterwards."""
    return tempfile.TemporaryDirectory(prefix='wavelens-unit-')


def run_tool(name, *args, cwd=ROOT):
    """python3 -I tools/<name>.py ARGS -> (return code, stdout, stderr)."""
    p = subprocess.run([sys.executable, '-I', os.path.join(TOOLS, name + '.py'), *map(str, args)], capture_output=True, text=True, cwd=cwd)
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
