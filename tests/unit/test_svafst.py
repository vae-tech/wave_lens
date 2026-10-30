"""`sva fst` against GTKWave's vcd2fst (review 2026-10-25 CT1/BT1, BT4): VCDs made from seeds (widths about 8, 32, 64 and
1000 bits, x and z, reals, strings, aliases, small blocks) and the fixtures, each made an FST by both, both read back by
fst2vcd and by `sva vcd`: the same variables and the same changes of each at each time. The fixtures where vcd2fst
writes another FST (and sva fst follows the VCD, as the tools read it) are listed with the reason. Needs vcd2fst and
fst2vcd (GTKWave): make check fails without them (the gate compares the FST writer with GTKWave's)."""
import os, random, re, shutil, subprocess, unittest

from tests.unit import helpers as H

# fixture -> why vcd2fst's FST is another (USAGE.md § A VCD as an FST)
DIFFERS = {
    'blasted': 'a value wider than its $var (vcd2fst cuts it on the left of the width it read)',
    'body_comment': 'a # inside a $comment of the body (vcd2fst reads it as a time)',
    'dumpoff': 'the values of $dumpoff (vcd2fst writes none)',
    'inline_time': '#5 1! on one line',
    'oneline': 'a dump on one line',
    'spaces': 'upper-case X Z',
    'vhdl': 'VHDL\'s 1-bit U H L (vcd2fst writes x)',
    'reuse_width': 'a code declared again at another width (vcd2fst gives both the first one\'s width)',
    'port': 'a $var port (vcd2fst keeps EVCD\'s 3n+2 bits)',
    'glued': 'a vector without its b, glued to its code (Questa 2023\'s integer: vcd2fst reads a bit of a code it does not know)',
    'backwards': 'a time that goes back (an error here, merged by vcd2fst)',
    'unsorted': 'a time that goes back (an error here, merged by vcd2fst)',
    'noend': 'a header cut off (an error here)',
}


TEXTS = ['idle', 'go\\040on', 'x\\x41']   # strings as a VCD writes them: an escaped space, a hex escape


def gen(seed):
    """A VCD from a seed: scopes, variables of many widths (some sharing a code: an alias), reals, strings; values
    with x and z, a time now and then without changes."""
    rnd = random.Random(seed)
    W = [1, 1, 1, 2, 7, 8, 9, 31, 32, 33, 64, 65, 1000]
    out = ['$timescale 1ps $end', '$scope module tb $end']
    sigs, code, depth = [], 0, 1
    def new_code():
        nonlocal code
        code += 1
        c, n = '', code
        while n:
            c, n = chr(33 + n % 94) + c, n // 94
        return c
    for k in range(rnd.randint(3, 25)):
        if k and rnd.random() < 0.2:
            if rnd.random() < 0.6:
                out.append(f'$scope module u{k} $end')
                depth += 1
            elif depth > 1:
                out.append('$upscope $end')
                depth -= 1
        kind = rnd.random()
        if kind < 0.1:
            c = new_code()
            sigs.append(('r', 64, c))
            out.append(f'$var real 64 {c} r{k} $end')
        elif kind < 0.15:
            c = new_code()
            sigs.append(('s', 1, c))
            out.append(f'$var string 1 {c} s{k} $end')
        else:
            w = rnd.choice(W)
            same = [s for s in sigs if s[0] == 'b' and s[1] == w]
            c = same[0][2] if same and rnd.random() < 0.3 else new_code()   # an alias of the same width
            if c not in [s[2] for s in sigs]:
                sigs.append(('b', w, c))
            out.append(f'$var wire {w} {c} v{k}' + (f' [{w - 1}:0]' if w > 1 else '') + ' $end')
    out += ['$upscope $end'] * depth + ['$enddefinitions $end']
    def val(s):
        t, w, c = s
        if t == 'r':
            return f'r{rnd.choice([0, 1.5, -2.25, 1e-9, 123456.75])} {c}'
        if t == 's':
            return f's{rnd.choice(TEXTS)} {c}'
        bits = ''.join(rnd.choice('0101xz' if rnd.random() < 0.2 else '01') for _ in range(w))
        return f'{bits}{c}' if w == 1 else f'b{bits.lstrip("0") or "0"} {c}'
    out += ['#0', '$dumpvars'] + [val(s) for s in sigs] + ['$end']   # #0 first: vcd2fst times a $dumpvars before it otherwise
    t = 0
    for _ in range(rnd.randint(5, 120)):
        t += rnd.choice([1, 1, 5, 10, 1000])
        out.append(f'#{t}')
        out += [val(s) for s in rnd.sample(sigs, rnd.randint(0, len(sigs)))]
    return '\n'.join(out) + '\n'


def readback(cmd, fst):
    """A VCD text of the FST (fst2vcd or sva vcd) -> ({path: (type, width)}, {time: {path: [values in order]}})."""
    p = subprocess.run(cmd + [fst], capture_output=True, text=True)
    if p.returncode:
        raise AssertionError(f'{cmd[0]} {fst}: {p.stderr[-300:]}')
    head, body = re.split(r'^\$enddefinitions\b', p.stdout, maxsplit=1, flags=re.M)   # not the word in a $comment
    scope, names, decl = [], {}, {}
    for l in head.splitlines():
        w = l.split()
        if w[:1] == ['$scope']:
            scope.append(w[2])
        elif w[:1] == ['$upscope']:
            scope.pop()
        elif w[:1] == ['$var']:
            path = '.'.join(scope + [' '.join(w[4:-1])])
            names.setdefault(w[3], []).append(path)
            decl[path] = (w[1], w[2])
    ch, now, pending = {}, None, None
    put = lambda code, v: [ch.setdefault(now, {}).setdefault(path, []).append(v) for path in names.get(code, [])]
    for tok in body.split()[1:]:   # [0]: the $end of $enddefinitions
        if pending is not None:
            put(tok, pending)
            pending = None
        elif tok.startswith('#'):
            now = int(tok[1:])
        elif tok.startswith('$'):
            pass
        elif tok[0] in 'bBrRsS':
            pending = tok.lower() if tok[0] in 'bB' else tok
        else:
            put(tok[1:], tok[0].lower())
    return decl, ch


@H.needs(shutil.which('vcd2fst') and shutil.which('fst2vcd'), 'GTKWave (vcd2fst, fst2vcd): the gate compares sva fst with it')
class AgainstVcd2fst(unittest.TestCase):
    def setUp(self):
        import svabuild
        self.sva = svabuild.find_bin()
        if not self.sva:
            H.skip(self, 'the sva CLI')

    def both(self, d, name, text=None, src=None, args=()):
        vcd = os.path.join(d, name + '.vcd')
        if src:
            shutil.copy(src, vcd)
        else:
            with open(vcd, 'w', newline='') as f:
                f.write(text)
        ours, theirs = os.path.join(d, name + '.fst'), os.path.join(d, name + '.g.fst')
        p = subprocess.run([self.sva, 'fst', vcd, '-q', *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, f'{name}: {p.stderr}')
        g = subprocess.run(['vcd2fst', vcd, theirs], capture_output=True, text=True)
        self.assertEqual(g.returncode, 0, f'{name}: vcd2fst: {g.stderr}')
        return ours, theirs

    def same(self, ours, theirs, what):
        for cmd in (['fst2vcd'], [self.sva, 'vcd']):
            a, b = readback(cmd, ours), readback(cmd, theirs)
            self.assertEqual(a[0], b[0], f'{what}: the variables through {cmd[-1]}')
            self.assertEqual(a[1], b[1], f'{what}: the changes through {cmd[-1]}')

    def test_generated(self):
        with H.tmp() as d:
            for seed in range(40):
                with self.subTest(seed=seed):
                    text = gen(seed)
                    ours, theirs = self.both(d, f'g{seed}', text, args=['--block-bytes', '200'] if seed % 3 == 0 else [])
                    self.same(ours, theirs, f'seed {seed}')

    def test_fixtures(self):
        with H.tmp() as d:
            for f in sorted(os.listdir(H.VCD)):
                name = f[:-4]
                if name in DIFFERS:
                    continue
                with self.subTest(name):
                    ours, theirs = self.both(d, name, src=os.path.join(H.VCD, f), args=['--no-types'])
                    self.same(ours, theirs, name)

    def test_blackout(self):
        # $dumpoff / $dumpon as the FST's blackout block: fst2vcd writes them back at their times
        with H.tmp() as d:
            vcd = os.path.join(d, 'off.vcd')
            shutil.copy(H.fixture('dumpoff'), vcd)
            subprocess.run([self.sva, 'fst', vcd, '-q'], check=True)
            t = subprocess.run(['fst2vcd', os.path.join(d, 'off.fst')], capture_output=True, text=True).stdout
            self.assertRegex(t, r'#20\n\$dumpoff \$end\nx"\nbxxxxxxxx !\n#40\n\$dumpon \$end\n', t)


class Cuts(unittest.TestCase):
    """`sva vcd --from --to` (stage 14.1.6): the cut of a VCD and the cut of its FST (sva fst) read back the same, the
    values at --from as $dumpvars, the changes up to --to; dumpscan reads them as one dump."""

    def setUp(self):
        import svabuild
        self.sva = svabuild.find_bin()
        if not self.sva:
            H.skip(self, 'the sva CLI')

    def test_cut_of_a_vcd_is_the_cut_of_its_fst(self):
        import dumpscan
        with H.tmp() as d:
            for seed in range(20):
                with self.subTest(seed=seed):
                    text = gen(seed)
                    vcd = os.path.join(d, f'c{seed}.vcd')
                    with open(vcd, 'w', newline='') as f:
                        f.write(text)
                    subprocess.run([self.sva, 'fst', vcd, '-q'], check=True)
                    times = [int(t) for t in re.findall(r'^#(\d+)$', text, re.M)]
                    rnd = random.Random(seed)
                    a = rnd.choice(times)
                    b = min(max(times), a + rnd.choice([0, 1, 7, 100, 5000]))
                    win = ['--from', f'{a}ps', '--to', f'{b}ps']
                    x, y = readback([self.sva, 'vcd', *win], vcd), readback([self.sva, 'vcd', *win], vcd[:-4] + '.fst')
                    self.assertEqual(x[0], y[0], f'seed {seed}: the variables')
                    self.assertEqual(x[1], y[1], f'seed {seed}: the changes')
                    self.assertEqual(min(x[1]), a, 'the values at --from first')
                    cuts = []
                    for src in (vcd, vcd[:-4] + '.fst'):
                        out = os.path.join(d, f'c{seed}.cut.{src[-3:]}.vcd')
                        subprocess.run([self.sva, 'vcd', *win, src, '--out', out], check=True)
                        cuts.append(dumpscan.scan(out))
                    self.assertEqual(cuts[0], cuts[1], f'seed {seed}: dumpscan of the two cuts')


if __name__ == '__main__':
    unittest.main()
