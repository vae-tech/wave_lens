#!/usr/bin/env python3
"""svaverify.py — the engine against a simulator: the examples' checkers run in Verilator (--assert) and by sva eval.

For each example the testbench with its .sva files (their checker modules and `bind` statements) is built with
`verilator --binary --assert` and run; every "Assertion failed" line of the simulation (the
file and line of the assertion's action, its time) is compared with the failures sva eval finds in the example's
dump (`failed_at` of each failed attempt, as a time). The assertions Verilator does not support (an
%Error in its span: UNSUPPORTED `[*n]` on a boolean, `within`, `[*1:$]`, `##[1:$]` …) are blanked in a copy of the file (the line
numbers kept) and listed, as is one it rejects (`!` in a cover's sequence); the rest must agree, the deliberate failures among them. make sva-verify; needs Verilator
and the example dumps (make examples).

  python3 -I tools/svaverify.py [--build out] [--sva-bin PATH] [--only apb,fsm] [--keep]
"""
import argparse, json, os, re, shutil, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import ROOT, UNIT_PS, WaveError, add_sva_bin_arg, run_main  # noqa: E402
import svabuild  # noqa: E402

# example: the testbench top, the scope of its sva eval run, the files of the sources (packages first) and of sva eval
EXAMPLES = {
    'apb': {'top': 'apb_tb', 'scope': 'apb_tb', 'src': ['apb/apb_tb.sv'], 'sva': ['apb/apb_tb.sv', 'apb/apb.sva']},
    'axi_lite': {'top': 'axi_lite_tb', 'scope': 'axi_lite_tb.u_slave', 'src': ['axi_lite/axi_lite_tb.sv'], 'sva': ['axi_lite/axi_lite.sva']},
    'fsm': {'top': 'fsm_tb', 'scope': 'fsm_tb.u_rx', 'src': ['fsm/uart_pkg.sv', 'fsm/fsm_tb.sv'], 'sva': ['fsm/uart_pkg.sv', 'fsm/fsm.sva']},
}
FAIL_RE = re.compile(r'^\[(\d+(?:\.\d+)?)\] %Error: (\S+?):(\d+): Assertion failed', re.M)
UNSUP_RE = re.compile(r'^%Error(?:-\w+)?: (\S+?):(\d+):\d+:', re.M)   # UNSUPPORTED, or a syntax it does not take
TIME_RE = re.compile(r'^\s*`timescale\s+\d+\s*(?:ns|ps|us|fs|ms|s)\s*/\s*(\d+)\s*(fs|ps|ns|us|ms|s)\b', re.M)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def run(cmd, cwd=None, timeout=900):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def parse(sva, files):
    """sva parse --json of the files -> {path: [item, …]}: the assertions (label, kind, from the label to its ';') and
    the sequence / property declarations (their name, kind "sequence" / "property", to endsequence / endproperty)."""
    r = run([sva, 'parse', '--json', *files], cwd=ROOT)
    if r.returncode:
        raise WaveError(f'sva parse {" ".join(files)}: {r.stderr.strip() or r.stdout.strip()}')
    out = {}
    for f, info in zip(files, json.loads(r.stdout)['files']):
        text = read(os.path.join(ROOT, f))
        lst = []
        for a in info['assertions']:
            s = a['at']['start']
            if not text.startswith(a['label'], s):
                raise WaveError(f'{f}: the span of {a["label"]} is not where its label is (offset {s})')
            e = text.index(';', a['at']['end']) + 1   # with its action block: `else $error(…);`
            lst.append({'label': a['label'], 'kind': a['kind'], 'start': s, 'end': e})
        for kind, key in (('sequence', 'sequences'), ('property', 'properties')):
            for d in info[key]:
                s = d['at']['start']
                lst.append({'label': d['name'], 'kind': kind, 'start': s, 'end': text.index('end' + kind, s) + len('end' + kind)})
        for x in lst:
            x['lines'], x['text'] = range(text.count('\n', 0, x['start']) + 1, text.count('\n', 0, x['end']) + 2), text[x['start']:x['end']]
        out[f] = lst
    return out


def blank(text, spans):
    """The text with the spans put out (every character but a newline a space: the line numbers stay)."""
    for s, e in sorted(spans, reverse=True):
        text = text[:s] + re.sub(r'[^\n]', ' ', text[s:e]) + text[e:]
    return text


def verify(name, ex, sva, build, keep):
    out = os.path.join(build, 'sva-verify', name)
    os.makedirs(out, exist_ok=True)
    dump = os.path.join(build, 'examples', name, name + '.vcd')
    if not os.path.exists(dump):
        raise WaveError(f'no {dump}: make examples')
    files = ['examples/' + f for f in ex['sva']]
    asserts = parse(sva, files)
    # the checker files as Verilator takes them: the unsupported assertions blanked, found by lint until none is left
    dropped, copies = {f: set() for f in files}, {}
    sources = ['examples/' + f for f in ex['src']]
    for _ in range(20):
        for f in files:
            if f.endswith('.sva'):
                copies[f] = os.path.join(out, os.path.basename(f))
                with open(copies[f], 'w', encoding='utf-8') as g:
                    g.write(blank(read(os.path.join(ROOT, f)),
                                  [(a['start'], a['end']) for a in asserts[f] if a['label'] in dropped[f]]))
        argv = [os.path.join(ROOT, s) for s in sources] + list(copies.values())
        r = run(['verilator', '--lint-only', '--timing', '--assert', '-Wno-fatal', '--top-module', ex['top'], *argv])
        bad = UNSUP_RE.findall(r.stderr)
        if not bad:
            if r.returncode:
                raise WaveError(f'{name}: verilator --lint-only: {r.stderr.strip()[:2000]}')
            break
        for path, line in bad:
            f = next((f for f, c in copies.items() if os.path.samefile(c, path)), None)
            a = f and next((a for a in asserts[f] if int(line) in a['lines']), None)
            if not a:
                raise WaveError(f'{name}: verilator: an error outside an assertion: {path}:{line}: {r.stderr.strip()[:2000]}')
            dropped[f].add(a['label'])
            # a declaration Verilator does not take: every item that uses it goes too
            more = True
            while more:
                use = [x for x in asserts[f] if x['label'] not in dropped[f] and any(
                    re.search(r'\b' + re.escape(d) + r'\b', x['text']) for d in dropped[f] if d != x['label'])]
                more = bool(use)
                dropped[f].update(x['label'] for x in use)
    r = run(['verilator', '--binary', '--timing', '--assert', '-Wno-fatal', '--top-module', ex['top'], '-Mdir', os.path.join(out, 'obj'), *argv])
    if r.returncode:
        raise WaveError(f'{name}: verilator --binary: {r.stderr.strip()[-2000:]}')
    sim = run([os.path.join(out, 'obj', 'V' + ex['top']), '+verilator+error+limit+1000000'], cwd=out)
    # Verilator prints $time in the precision of the timescale; sva eval's times are cycles of the dump
    m = TIME_RE.search(read(os.path.join(ROOT, sources[-1])))
    prec = int(m.group(1)) * UNIT_PS[m.group(2)] if m else 1
    by_line = {}
    for f in files:
        for a in asserts[f]:
            for ln in a['lines']:
                by_line[(os.path.basename(f), ln)] = a['label']
    ver = {}
    for t, path, line in FAIL_RE.findall(sim.stdout + sim.stderr):
        label = by_line.get((os.path.basename(path), int(line)))
        if label:
            ver.setdefault(label, []).append(round(float(t) * prec))
    args = [sva, 'eval', '--waves', dump, '--scope', ex['scope'], *[x for f in files for x in ('--sva', f)], '--json']
    res = json.loads(run(args, cwd=ROOT).stdout)
    unit = UNIT_PS[res['unit']] if isinstance(res.get('unit'), str) else 1
    eng = {}
    for a in res['assertions']:
        times = [round(res['cycles'][x['failed_at']] * unit) for x in a.get('attempts', []) if x['result'] == 'fail' and 'failed_at' in x]
        if times:
            eng[a['name']] = times
    compared = [a['label'] for f in files for a in asserts[f] if a['kind'] == 'assert' and a['label'] not in dropped[f]]
    diff = [(n, ver.get(n, []), eng.get(n, [])) for n in compared if sorted(ver.get(n, [])) != sorted(eng.get(n, []))]
    skipped = sorted(x['label'] for f in files for x in asserts[f] if x['label'] in dropped[f] and x['kind'] not in ('sequence', 'property'))
    if not keep:
        shutil.rmtree(os.path.join(out, 'obj'), ignore_errors=True)
    return compared, skipped, diff, {n: eng[n] for n in compared if n in eng}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default=os.path.join(ROOT, 'out'), help='the Makefile BUILD (the example dumps; the work goes to BUILD/sva-verify)')
    ap.add_argument('--only', help='comma-separated examples (default: ' + ', '.join(EXAMPLES) + ')')
    ap.add_argument('--keep', action='store_true', help='keep the Verilator builds')
    add_sva_bin_arg(ap)
    a = ap.parse_args()
    if not shutil.which('verilator'):
        print('svaverify: skipped: no verilator on PATH', file=sys.stderr)
        return
    sva = svabuild.find_bin(a.sva_bin)
    if not sva:
        raise WaveError('no sva CLI: make sva-build')
    names = [x for x in (a.only or ','.join(EXAMPLES)).split(',') if x]
    if set(names) - set(EXAMPLES):
        raise WaveError(f'unknown example(s) {", ".join(sorted(set(names) - set(EXAMPLES)))}')
    bad = 0
    for name in names:
        compared, skipped, diff, fails = verify(name, EXAMPLES[name], sva, os.path.abspath(a.build), a.keep)
        print(f'svaverify: {name}: {len(compared) - len(diff)} of {len(compared)} assertions agree with Verilator --assert'
              + (f' (failing in both: {", ".join(f"{n} ×{len(t)}" for n, t in fails.items())})' if fails else '')
              + (f'; not supported by Verilator, not compared: {", ".join(skipped)}' if skipped else ''))
        for n, v, e in diff:
            print(f'  DIFF {n}: Verilator fails at {v or "never"} ps, sva eval at {e or "never"} ps')
        bad += len(diff)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    run_main(main, 'svaverify')
