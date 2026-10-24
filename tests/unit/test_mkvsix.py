"""tools/mkvsix.py and what it ships: the package's files as the extension needs them, the committed sva CLI the build's."""
import hashlib, json, os, re, subprocess, unittest, zipfile

from tests.unit import helpers as H

SHIPPED = os.path.join(H.ROOT, 'bin', 'linux-x86_64', 'sva')
EXAMPLES = [('apb', 'apb_tb', ['examples/apb/apb_tb.sv', 'examples/apb/apb.sva']),   # the cases of sva/cli/tests/cli.rs
            ('axi_lite', 'axi_lite_tb.u_slave', ['examples/axi_lite/axi_lite.sva']),
            ('fsm', 'fsm_tb.u_rx', ['examples/fsm/uart_pkg.sv', 'examples/fsm/fsm.sva'])]


class Package(unittest.TestCase):
    # review VI T2: the .vsix as VS Code installs it, not only that mkvsix.py ran: every file extension.js requires and
    # media/host.js loads, the viewer's files as they are in wavelens/, bin/sva executable, the version of VERSION and
    # the build of the bar (wavelensBuild: the commit it was packed from), the same bytes twice
    def test_the_files(self):
        with H.tmp() as d:
            outs = [os.path.join(d, n) for n in ('a.vsix', 'b.vsix')]
            for out in outs:
                rc, _, err = H.run_tool('mkvsix', '--out', out, '--sva', SHIPPED)
                self.assertEqual(rc, 0, err)
            with open(outs[0], 'rb') as a, open(outs[1], 'rb') as b:
                self.assertEqual(hashlib.sha256(a.read()).digest(), hashlib.sha256(b.read()).digest(), 'the same input, the same bytes')
            named = [n for n in os.listdir(d) if n.startswith('wavelens-')]   # the copy named by the version, beside OUT
            with open(outs[1], 'rb') as a, open(os.path.join(d, named[0]), 'rb') as b:
                self.assertEqual(a.read(), b.read(), 'the copy named by the version: the same bytes')
            os.makedirs(os.path.join(d, 'one'))
            rc, _, err = H.run_tool('mkvsix', '--out', os.path.join(d, 'one', 'c.vsix'), '--one', '--sva', SHIPPED)
            self.assertEqual((rc, os.listdir(os.path.join(d, 'one'))), (0, ['c.vsix']), f'--one: OUT only {err}')
            with zipfile.ZipFile(outs[0]) as z:
                names = set(z.namelist())
                pkg = json.loads(z.read('extension/package.json'))
                mode = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
                body = {n: z.read(n) for n in names}
        with open(os.path.join(H.ROOT, 'VERSION'), encoding='utf-8') as f:
            ver = f.read().strip()
        self.assertEqual(pkg['version'], ver + '.0' * (2 - ver.count('.')))
        self.assertEqual(named, [f'wavelens-{pkg["version"]}.vsix'])
        self.assertIn(f'Version="{pkg["version"]}"', body['extension.vsixmanifest'].decode())
        main = 'extension/' + re.sub(r'^\./', '', pkg['main'])
        self.assertIn(main, names)
        ext = body['extension/extension.js'].decode()
        for r in re.findall(r"require\('\./([^']+)'\)", ext):   # what the extension loads of its own
            self.assertIn('extension/' + r, names)
        for m in ('wavelens.css', 'wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js'):
            with open(os.path.join(H.ROOT, 'wavelens', m), 'rb') as f:
                self.assertEqual(body['extension/media/' + m], f.read(), m)
        self.assertIn('extension/media/host.js', names)
        self.assertEqual(mode['extension/bin/sva'], 0o755)
        self.assertEqual(body['extension/bin/sva'][:4], b'\x7fELF')
        if subprocess.run(['git', '-C', H.ROOT, 'rev-parse', 'HEAD'], capture_output=True).returncode == 0:
            b = pkg.get('wavelensBuild') or {}
            head = subprocess.run(['git', '-C', H.ROOT, 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()
            self.assertTrue(b.get('commit') and head.startswith(b['commit'][:7]), b)
        for n in names:   # nothing of the tree beside the extension's (a dump, a page of work/)
            self.assertTrue(n in ('[Content_Types].xml', 'extension.vsixmanifest') or n.startswith('extension/'), n)
        self.assertFalse([n for n in names if re.search(r'\.(vcd|fst|html)$', n)])


class Shipped(unittest.TestCase):
    # review VI T2: bin/linux-x86_64/sva is committed and rebuilt in the commit of an engine change: it gives what the
    # CLI built from sva/ now gives (make check builds it: WAVELENS_SVA) over the examples, the evaluation and sva vcd
    def test_the_build(self):
        fresh = os.environ.get('WAVELENS_SVA')
        if not fresh or not os.path.isfile(fresh) or os.path.realpath(fresh) == os.path.realpath(SHIPPED):
            H.skip(self, 'no sva CLI built from sva/ (make sva-build; make unit gives it as WAVELENS_SVA)')
        for ex, scope, files in EXAMPLES:
            fst = os.path.join(H.BUILD, 'examples', ex, ex + '.fst')
            if not os.path.isfile(fst):
                H.skip(self, f'{fst}: make examples')
            args = ['eval', '--waves', fst, '--scope', scope, '--attempts'] + [x for f in files for x in ('--sva', os.path.join(H.ROOT, f))]
            with self.subTest(ex):
                a, b = (subprocess.run([exe, *args], capture_output=True, text=True, timeout=300) for exe in (fresh, SHIPPED))
                self.assertEqual((b.returncode, b.stdout), (a.returncode, a.stdout), f'{ex}: bin/linux-x86_64/sva is not the build of sva/ '
                                 '(make dist-linux and commit it)')
                a, b = (subprocess.run([exe, 'vcd', fst], capture_output=True, timeout=300) for exe in (fresh, SHIPPED))
                self.assertEqual(hashlib.sha256(b.stdout).hexdigest(), hashlib.sha256(a.stdout).hexdigest(), f'{ex}: sva vcd')


if __name__ == '__main__':
    unittest.main()
