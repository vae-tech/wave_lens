"""Budgets of time and memory (review VI T15): vcd2wavedrom.py over a generated dump of two sizes — the bigger one in its
time and its peak memory, and both growing with the dump, not faster (a quadratic step, a copy of every change kept, the
reader's raw changes not freed: review V C6). Limits are generous (WAVELENS_TIME_SCALE multiplies the times); the
ratios catch what a machine's speed would hide."""
import os, random, subprocess, sys, unittest

from tests.unit import helpers as H

SCALE = float(os.environ.get('WAVELENS_TIME_SCALE', '1'))
MEASURE = ('import resource, subprocess, sys, time; t = time.monotonic(); r = subprocess.run(sys.argv[1:], capture_output=True); '
           'print(time.monotonic() - t, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, r.returncode)')


def gen(path, changes, nsig=64, seed=1):
    """A VCD of nsig signals (every other one 32 bits) and about that many changes, 8 at each time."""
    rnd = random.Random(seed)
    codes = [chr(33 + i % 90) + (chr(33 + i // 90) if i >= 90 else '') for i in range(nsig)]
    with open(path, 'w') as f:
        f.write('$timescale 1ns $end\n$scope module tb $end\n')
        for i, c in enumerate(codes):
            f.write(f'$var wire {1 if i % 2 else 32} {c} s{i}{"" if i % 2 else " [31:0]"} $end\n')
        f.write('$upscope $end\n$enddefinitions $end\n')
        t = n = 0
        while n < changes:
            t += 1
            f.write(f'#{t}\n')
            for i in rnd.sample(range(nsig), 8):
                f.write(f'{rnd.choice("01")}{codes[i]}\n' if i % 2 else f'b{rnd.getrandbits(32):b} {codes[i]}\n')
                n += 1


def run(*argv):
    """A program in a process of its own -> (seconds, peak memory in MB)."""
    r = subprocess.run([sys.executable, '-I', '-c', MEASURE, *argv], capture_output=True, text=True, timeout=600)
    t, rss, rc = r.stdout.split()
    if rc != '0':
        raise AssertionError(f'{argv[:4]}: exit {rc}')
    return float(t), int(rss) / 1024


class Converter(unittest.TestCase):
    def test_grows_with_the_dump(self):
        sigs = ','.join(f'tb.s{i}' for i in range(64))
        with H.tmp() as d:
            got = {}
            for n in (100000, 400000):
                p = os.path.join(d, f'p{n}.vcd')
                gen(p, n)
                got[n] = run(sys.executable, '-I', os.path.join(H.TOOLS, 'vcd2wavedrom.py'), '--waves', p, '--exact', '--signals', sigs,
                             '--out', os.path.join(d, f'p{n}.json'))
            base = run(sys.executable, '-I', '-c', 'import json, re, zlib')[1]   # an interpreter's own memory
        (t1, m1), (t4, m4) = got[100000], got[400000]
        say = f'100 000 changes: {t1:.1f} s {m1:.0f} MB; 400 000: {t4:.1f} s {m4:.0f} MB (an interpreter: {base:.0f} MB)'
        self.assertLess(t4, 30 * SCALE, say)
        self.assertLess(m4, 400, say)
        self.assertLess(t4 / max(t1, 0.05), 6, 'time grows faster than the dump: ' + say)
        self.assertLess((m4 - base) / max(m1 - base, 1), 6, 'memory grows faster than the dump: ' + say)


if __name__ == '__main__':
    unittest.main()
