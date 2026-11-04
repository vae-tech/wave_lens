"""The repository's promises: one version (VERSION, wavelens.js, CHANGELOG.md, the CLI), make help lists every target, the docs' settings table is the settings file's keys, the
tools answer --help, the converter's per-signal keys are documented and read by the page."""
import json, os, re, subprocess, unittest, zipfile

from tests.unit import helpers as H
import common
import vcd2wavedrom
import viewedit


def read(*p):
    with open(os.path.join(H.ROOT, *p), encoding='utf-8') as f:
        return f.read()


class Makefile(unittest.TestCase):
    def targets(self):
        return set(re.findall(r'^([a-z][\w-]*):(?!=)', read('Makefile'), re.M))

    def test_help_lists_every_target(self):
        helped = set(re.findall(r"@echo 'make ([a-z][\w-]*)", read('Makefile')))
        self.assertEqual(self.targets() - helped - {'help'}, set())

    def test_phony_complete(self):
        phony = set(re.search(r'^\.PHONY:(.*)$', read('Makefile'), re.M).group(1).split())
        self.assertEqual(self.targets() - phony, set())

    def test_help_runs(self):
        p = subprocess.run(['make', '-s', 'help'], cwd=H.ROOT, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(re.findall(r'\$\((?!BUILD\))[^)]*\)', p.stdout), [])   # $(BUILD) is the variable's name; nothing else unexpanded


class PublicNames(unittest.TestCase):
    """review 0.31 S7, T18: the names others build on, pinned: a name removed or renamed fails here and needs make unit-bless,
    not only a test that reads the code and the docs from the same commit."""
    def test_the_api_golden(self):
        boot = read('wavelens', 'src', 'boot.js')
        api = boot[boot.index('G.WaveLens = {'):boot.index('// unstable:', boot.index('G.WaveLens = {'))]
        api = re.sub(r'//.*', '', api[api.index('{') + 1:])
        keys, depth, top = [], 0, ''
        for c in api:   # the top level of the object: what is inside brackets or an arrow's call stays out
            depth += c in '{([' and 1 or c in '})]' and -1 or 0
            if c == ',' and depth == 0:
                keys.append(top)
                top = ''
            elif depth == 0 and c not in '})]':
                top += c
        keys.append(top)
        names = sorted({re.match(r'\s*(\w+)', k).group(1) for k in keys if k.strip()})
        H.golden(self, 'api.txt', ''.join(f'WaveLens.{n}\n' for n in names) + ''.join(f'command {k}: {v}\n' for k, v in sorted(viewedit.COMMANDS.items())))


class Tables(unittest.TestCase):
    """review 0.31 D1-D12, T19: the tables of the docs against the code they describe: what was added to one and not the other."""
    @staticmethod
    def src(*names):
        return ''.join(read('wavelens', *n.split('/')) for n in names)

    def test_python_floor(self):
        import ast
        said = {re.search(r'[Pp]ython3? ≥ (\d\.\d+)', read(*f)).group(1) for f in (['README.md'], ['docs', 'DEVELOPMENT.md'])}
        said.add(re.search(r'Python >= (\d\.\d+)', read('tools', 'common.py')).group(1))
        self.assertEqual(len(said), 1, said)
        floor = tuple(int(x) for x in said.pop().split('.'))
        for f in sorted(os.listdir(H.TOOLS)):
            if f.endswith('.py'):
                text = read('tools', f)
                ast.parse(text, feature_version=floor)
                if floor < (3, 9):
                    self.assertNotIn('.removeprefix(', text, f)

    def keys(self):
        """The keys the viewer takes: the key handler, the sequences, the plugins' addKey."""
        view = read('wavelens', 'src', 'view.js')
        h = view[view.index('  keyInput(c) {'):view.index('  maskKeep(rows)')]
        one = set(re.findall(r"k === '([^']+)'", h))
        seq = set(re.findall(r"s === '([^']+)'", view[view.index('  seq(s) {'):view.index('  goBm(b)')]))
        plug = {k for f in ('src/diff.js', 'sva.js', 'bus.js', 'src/modules.js', 'src/fsm.js', 'src/edit.js') for k in re.findall(r"addKey\('([^']+)'", self.src(f))}
        names = {'Escape': 'Esc', 'PageDown': 'PgDn', 'PageUp': 'PgUp', 'ArrowDown': '↓', 'ArrowUp': '↑', 'ArrowLeft': '←', 'ArrowRight': '→'}
        return {names.get(k, k) for k in one | seq | plug} - {'Shift', 'Control', 'Alt', 'Meta', 'CapsLock', '=', 'I', 'O', 'F', 'L', 'C', 'g'}   # g: the first of gg, or a shift's spelling

    def test_keys(self):
        usage = read('docs', 'USAGE.md')
        table = usage[usage.index('| Key | Action | Key | Action |'):usage.index('**Bus widths and bits.**')]
        guide = read('docs', 'guides', 'viewer.html')
        guide = guide[guide.index('id="keys"'):]
        word = lambda k, t: re.search(r'(?<![\w\[\]])' + re.escape(k) + r'(?![\w\[\]])', t) or (len(k) > 1 and k in t)
        for k in sorted(self.keys()):
            with self.subTest(k):
                self.assertTrue(word(k, table), f'{k}: not in USAGE\'s table of keys')
                self.assertTrue(word(k, guide), f'{k}: not in guides/viewer.html § All the keys')

    def test_settings_values(self):
        look = self.src('src/look.js')
        count = re.search(r"\[('off', 'clock', [^\]]+)\]\.includes\(o\.gapCount\)", look).group(1)
        enums = {'gapCount': re.findall(r"'(\w+)'", count), 'groupOrder': ['first', 'last', 'file'], 'wheel': ['zoom'], 'themeButton': ['auto'], 'log': ['auto'],
                 'arrowLabels': ['lane']}
        html, usage = read('docs', 'index.html'), read('docs', 'USAGE.md')
        rows = [x for x in html.split('</tr>') if '<td class="mono">' in x] + [x for x in usage.splitlines() if x.startswith('| `')]
        for k, vals in enums.items():
            for doc in (r'<td class="mono">[^<]*\b', r'^\| [^|]*`'):
                got = [x for x in rows if re.search(doc + k + r'\b', x)]
                with self.subTest(k=k, doc=doc):
                    self.assertTrue(got, k)
                    self.assertEqual([v for v in vals if v not in ''.join(got)], [])

    def test_events(self):
        fired = set(re.findall(r"CustomEvent\('(wavelens:[\w-]+)'", ''.join(self.src(f'src/{n}') for n in os.listdir(os.path.join(H.ROOT, 'wavelens', 'src'))) + self.src('sva.js', 'bus.js')))
        html = read('docs', 'index.html')
        table = html[html.index('const VIEW_EVENTS = {'):html.index('const MODEL_API = {')]
        self.assertEqual(sorted(e for e in fired if f"'{e}'" not in table), [])

    def test_extensions(self):
        usage, html = read('docs', 'USAGE.md'), read('docs', 'index.html')
        table = usage[usage.index('### Extensions (stock WaveDrom ignores them)'):]
        table = table[:table.index('\n## ')] if '\n## ' in table else table
        ext = html[html.index('<h3>Extensions to WaveJSON</h3>'):]
        ext = ext[:ext.index('</table>')]
        for k in ('compare', 'spans', 'bookmarks', 'markers'):
            with self.subTest(k):
                self.assertIn(f'| `{k}', table)
                self.assertRegex(ext, rf'class="mono">{k}\b')

    def test_commands(self):
        usage = read('docs', 'USAGE.md')
        at = usage.index('| Command | Arguments (`?` optional) | Does |')
        got = {}
        for line in usage[at:].splitlines()[2:]:
            if not line.startswith('|'):
                break
            cells = [c.strip() for c in re.split(r'(?<!\\)\|', line)[1:-1]]
            names, args = re.findall(r'`(\w+)`', cells[0]), [a.strip().strip('`—') for a in re.split(r'\s*/\s*', cells[1])]
            for i, n in enumerate(names):
                got[n] = args[i] if len(args) == len(names) else args[0]
        self.assertEqual(set(got) ^ set(viewedit.COMMANDS), set())
        self.assertEqual({k: v for k, v in got.items() if v != viewedit.COMMANDS[k]}, {})

    def test_mcp_tools(self):
        import wavemcp
        names = [t['name'] for t in wavemcp.TOOLS]
        usage, guide, html = read('docs', 'USAGE.md'), read('docs', 'guides', 'mcp.html'), read('docs', 'index.html')
        html = html[html.index('serves the same reader'):html.index('</p>', html.index('serves the same reader'))]
        for n in names:
            with self.subTest(n):
                self.assertIn(f'| `{n}` |', usage)
                self.assertIn(f'<td><code>{n}</code></td>', guide)
                self.assertIn(f'<code>{n}</code>', html)

    def test_vscode_commands_and_settings(self):
        import json
        pk = json.loads(read('vscode', 'package.json'))['contributes']
        readme, guide = read('vscode', 'README.md'), read('docs', 'guides', 'vscode.html')
        for c in pk['commands']:
            short = re.sub(r'\s*\(.*', '', c['title'])
            with self.subTest(c['command']):
                self.assertTrue(f'WaveLens: {short}' in readme or short in readme, short)
                self.assertTrue(f'WaveLens: {short}' in guide or short in guide, short)
        for k in pk['configuration']['properties']:
            with self.subTest(k):
                self.assertIn(k, readme)
                self.assertIn(k, guide)


class Version(unittest.TestCase):
    def test_one_version_everywhere(self):
        v = read('VERSION').strip()
        self.assertRegex(v, r'^\d+\.\d+$')                                          # two numbers: MAJOR.MINOR
        self.assertEqual(re.search(r"version: '([^']+)'", read('wavelens', 'src', 'boot.js')).group(1), v)
        self.assertEqual(re.search(r'^## (\S+)', read('CHANGELOG.md'), re.M).group(1), v)   # the top entry
        self.assertIn('include_str!("../../../VERSION")', read('sva', 'cli', 'src', 'main.rs'))
        with zipfile.ZipFile(os.path.join(H.ROOT, 'bin', 'wavelens.vsix')) as z:   # the package committed with the version
            self.assertEqual(json.loads(z.read('extension/package.json'))['version'], v + '.0', 'bin/wavelens.vsix: make dist-linux')
        guides = os.path.join(H.ROOT, 'docs', 'guides')
        for f in sorted(os.listdir(guides)):   # the guides' footers (and the index's kicker) name the version
            if f.endswith('.html'):
                said = set(re.findall(r'WaveLens (\d+\.\d+)', read('docs', 'guides', f)))
                self.assertEqual(said, {v}, f'docs/guides/{f}')


class Docs(unittest.TestCase):
    def test_settings_table_is_the_settings_file(self):
        html = read('docs', 'index.html')
        a = html.index('<h3>Settings (config file)</h3>')
        rows = re.findall(r'<tr><td class="mono">([^<]+)</td>', html[a:html.index('</table>', a)])
        documented = {k.strip() for r in rows for k in r.split(',')}
        self.assertEqual(documented ^ (common.config_keys() - set(common.CONFIG_EXTRA)), set())

    def test_model_defaults_are_the_settings_file(self):
        js = read('wavelens', 'wavelens.config.js')
        model = read('wavelens', 'src', 'model.js')
        body = re.search(r'const DEFAULTS = \{(.*?)\};', model, re.S).group(1)
        for k, v in re.findall(r'(\w+): ([^,]+?)(?=, \w+:|\s*$)', body.replace('\n', ' ')):
            with self.subTest(k):
                m = re.search(r'^ {2}%s: ([^,]+),' % k, js, re.M)
                self.assertIsNotNone(m, f'{k} of DEFAULTS is not in wavelens.config.js')
                if k != 'sortIgnore':   # the settings file sets i_, o_ (said in its header)
                    self.assertEqual(m.group(1).strip(), v.strip())

    def test_usage_lists_the_signal_keys(self):
        usage = read('docs', 'USAGE.md')
        self.assertEqual([k for k in vcd2wavedrom.SIG_KEYS if f'`{k}`' not in usage], [])

    def test_page_reads_the_signal_keys(self):
        model = read('wavelens', 'src', 'model.js')
        info = {'show', 'alias', 'changes'}   # the converter's own: a row left out, its name, information
        self.assertEqual([k for k in vcd2wavedrom.SIG_KEYS if k not in info and f'it.{k}' not in model], [])

    def test_tools_help(self):
        for f in sorted(os.listdir(H.TOOLS)):
            t = f[:-3]
            if not f.endswith('.py') or 'argparse' not in read('tools', f) or t == 'pageshot':   # pageshot: playwright, not under -I
                continue
            with self.subTest(t):
                rc, out, _ = H.run_tool(t, '--help')
                self.assertEqual(rc, 0)
                self.assertIn('usage:', out)

    def test_tools_write_no_bytecode(self):
        """AU-WL-003: a tool run as python3 -I (PYTHONDONTWRITEBYTECODE ignored) writes no tools/__pycache__ into a shared
        checkout: each script that imports a module of tools/ sets sys.dont_write_bytecode before that import."""
        mods = {f[:-3] for f in os.listdir(H.TOOLS) if f.endswith('.py')}
        late = []
        for f in sorted(os.listdir(H.TOOLS)):
            src = read('tools', f) if f.endswith('.py') else ''
            if "__name__ == '__main__'" not in src:
                continue
            imp = [m.start() for m in re.finditer(r'^\s*(?:import ([\w, ]+)|from (\w+) import)', src, re.M)
                   if mods & {x.strip() for x in (m.group(1) or m.group(2)).split(',')}]
            flag = src.find('sys.dont_write_bytecode = True')
            if imp and not 0 <= flag < imp[0]:
                late.append(f)
        self.assertEqual(late, [])

    def test_no_version_in_prose(self):   # review 0.31 D8: a number of now is wrong by the next release
        self.assertEqual(re.findall(r'\(\d+\.\d+ now', read('docs', 'DEVELOPMENT.md')), [])


if __name__ == '__main__':
    unittest.main()
