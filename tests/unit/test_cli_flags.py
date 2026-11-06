"""What the tools ask of the sva CLI against what it takes (review of the runs T-04, T-08 c, e): every flag the argument lists of
`sva diff`, `sva runs`, `sva vcd`, `sva fst` give (tools/svabuild.py, tools/wavemcp.py, vscode/extension.js) is one the
CLI's usage names (the USAGE of sva/cli/src/*.rs, what `sva <cmd> --help` prints); the extension finds the CLI of its
platform, says to set wavelens.sva when there is none, and reads the CLI's JSON after wellen's warnings."""
import json, os, re, subprocess, unittest

from . import helpers as H
from .test_vscode_state import FAKE, NODE

# the usage of each command: its source file under sva/cli/src
USAGE_OF = {'diff': 'diff.rs', 'diff --results': 'resdiff.rs', 'runs': 'runs.rs', 'vcd': 'vcd.rs', 'fst': 'fst.rs'}

# the argument lists of the CLI: (file, the line the builder starts at, the text it ends before (None: the next line indented
# no deeper than the first), the command whose usage it is checked against, may hold no flag)
BUILDERS = [
    ('tools/svabuild.py', 'def compare(exe,', None, 'diff', False),
    ('tools/wavemcp.py', 'def t_to_fst(a):', None, 'fst', False),
    ('tools/wavemcp.py', 'def t_diff(a):', "    da, db = dump_path(a, 'a')", 'diff --results', False),
    ('tools/wavemcp.py', "    da, db = dump_path(a, 'a')", '\ndef ', 'diff', False),
    ('tools/wavemcp.py', 'def t_runs(a):', None, 'runs', False),
    ('tools/wavemcp.py', 'def t_cut(a):', None, 'vcd', False),
    ('tools/dumpscan.py', 'def fst_reader():', None, 'vcd', True),
    ('vscode/extension.js', 'const vcdOf = ', None, 'vcd', False),
    ('vscode/extension.js', 'const fstOf = ', None, 'fst', False),
    ('vscode/extension.js', 'const headerOf = ', None, 'vcd', False),
    ('vscode/extension.js', '  async codes(list) {', None, 'vcd', False),
    ('vscode/extension.js', '  async compare(signals,', None, 'diff', False),
    ('vscode/extension.js', '  async runs(m) {', None, 'runs', False),
    ('vscode/extension.js', 'async function toFst(', None, 'fst', True),
]
FLAG = re.compile(r'''['"`](--?[A-Za-z][\w-]*)''')   # a string that starts with a flag ('--from', '--from=…', '-q')
BUILT = re.compile(r'''['"`]--?(\{|\$\{)''')   # a flag made of a variable (f'--{k}'): not readable here
ARGV = re.compile(r'''\[\s*(exe|sva|bin|sva_exe\([^)]*\))\s*,\s*'(diff|runs|vcd|fst)'|\[\s*'(diff|vcd|fst)'\s*,\s*[^'\s]|\[\s*'runs'\s*,''')   # sva's argv
LONG = re.compile(r'''['"`]--[A-Za-z]''')   # a long flag: in the extension, of sva or of git only


def usage(cmd):
    """The flags the usage of a command names."""
    src = H.text(os.path.join(H.ROOT, 'sva', 'cli', 'src', USAGE_OF[cmd]))
    m = re.search(r'const USAGE: &str = "(.*?)(?<!\\)";', src, re.S)
    assert m, f'no USAGE in {USAGE_OF[cmd]}'
    return set(re.findall(r'(?<![\w-])--?[A-Za-z][\w-]*', m.group(1)))


def region(file, begin, end):
    """(first line number, the lines) of a builder."""
    text = H.text(os.path.join(H.ROOT, file))
    i = text.find(begin)
    assert i >= 0, f'{file}: no "{begin.strip()}" (moved? the table BUILDERS of test_cli_flags.py)'
    i = text.rfind('\n', 0, i) + 1
    first = text.count('\n', 0, i) + 1
    if end is not None:
        j = text.find(end, i + len(begin))
        return first, text[i:j if j >= 0 else len(text)].splitlines()
    lines = text[i:].splitlines()
    deep = len(lines[0]) - len(lines[0].lstrip())
    n = next((k for k, l in enumerate(lines[1:], 1) if l.strip() and len(l) - len(l.lstrip()) <= deep), len(lines))
    return first, lines[:n]


class Flags(unittest.TestCase):
    def test_every_flag_is_one_the_cli_takes(self):
        """T-04: a flag the CLI does not know (a renamed option, a typo, a flag of another command) fails here, not at a user's."""
        bad, seen = [], {}
        for file, begin, end, cmd, empty in BUILDERS:
            first, lines = region(file, begin, end)
            known, got = usage(cmd), []
            for k, line in enumerate(lines):
                for m in BUILT.finditer(line):
                    bad.append(f'{file}:{first + k}: a flag made of a variable ({line.strip()[:80]}): write it out')
                for f in FLAG.findall(line):
                    got.append(f)
                    if f.split('=')[0] not in known:
                        bad.append(f'{file}:{first + k}: {f} is not in the usage of sva {cmd}')
            self.assertTrue(got or empty, f'{file}: {begin.strip()}: no flag found (the table BUILDERS of test_cli_flags.py)')
            seen.setdefault(cmd, set()).update(got)
        self.assertEqual(bad, [])
        # the table reads what it should: the flags each command is known to get
        self.assertLessEqual({'--page', '--signals-from', '--from', '--to', '--offset', '--map', '--segment', '--limit', '--json'}, seen['diff'])
        self.assertLessEqual({'--dir', '--json', '--name', '--tags', '--comment', '--cases', '--case', '--run', '--signals-from'}, seen['runs'])
        self.assertLessEqual({'--out', '--header', '--codes', '--from', '--signals'}, seen['vcd'])

    def test_every_argument_list_of_sva_is_in_the_table(self):
        """A new argument list of sva diff / runs / vcd / fst (or one moved out of its function) is checked too: it is in BUILDERS."""
        lists = {}
        for file in sorted({b[0] for b in BUILDERS}):
            lists[file] = [(first, len(lines)) for f, begin, end, _, _ in BUILDERS if f == file for first, lines in [region(f, begin, end)]]
        out = []
        for file in [os.path.join('tools', x) for x in sorted(os.listdir(os.path.join(H.ROOT, 'tools'))) if x.endswith('.py')] + ['vscode/extension.js']:
            for n, line in enumerate(H.text(os.path.join(H.ROOT, file)).splitlines(), 1):
                js = file.endswith('.js') and LONG.search(line) and 'git([' not in line
                if (ARGV.search(line) or js) and not any(a <= n < a + k for a, k in lists.get(file, ())):
                    out.append(f'{file}:{n}: {line.strip()[:100]}')
        self.assertEqual(out, [], 'argument lists of sva outside BUILDERS: add them to the table')

    def test_the_check_fails_on_an_unknown_flag(self):
        """The check itself: a flag of no usage is found in a line as the builders write it."""
        self.assertEqual(FLAG.findall("cmd += ['--no-such', x, '--from=1ns'] + ['-q']"), ['--no-such', '--from', '-q'])
        self.assertNotIn('--no-such', usage('diff'))
        self.assertTrue(BUILT.search("cmd += [f'--{k}', t]") and BUILT.search('args.push(`--${k}`)'))
        self.assertLessEqual({'--page', '--signals-from', '--cut-bytes', '--quiet'}, usage('diff'))
        # the runs' compare of one run as the extension asks it (the run pick, review 2026-11-06)
        self.assertLessEqual({'--against', '--run', '--page', '--cut-bytes', '--quiet', '--signals-from'}, usage('runs'))
        self.assertTrue(ARGV.search("cmd = [exe, 'runs', act]") and ARGV.search("spawnRun(bin, ['vcd', fst, '--codes', '-'])"))
        self.assertFalse(ARGV.search("filters: { dumps: ['vcd', 'fst'] }"))


SCRIPT = r'''
const [F, ext, dir, dump] = process.argv.slice(1).map((x, i) => (i ? x : require(x)));
const fs = require('fs'), path = require('path');
Object.defineProperty(process, 'platform', { value: 'win32' });   // a Windows-local host (path stays posix: node chose it)
const h = F.host({ ext, dir, extensionPath: path.join(dir, 'vscode'), vscode: { ProgressLocation: { Notification: 15 } },
  window: { withProgress: async (o, f) => f() }, workspace: { getWorkspaceFolder: () => undefined } });
(async () => {
  const A = await h.tab(dump);
  let n = 100; const ask = async m => { const id = ++n; await A.send(Object.assign({ type: 'runs', id }, m)); return A.reply(id); };
  const out = {}, PATH = process.env.PATH;
  process.env.PATH = '';
  out.none = await ask({ op: 'list' });   // nothing bundled for win32, nothing on the PATH
  process.env.PATH = PATH;
  const exe = path.join(dir, 'bin', 'windows-x86_64', 'sva.exe');   // where make dist-windows writes it
  fs.mkdirSync(path.dirname(exe), { recursive: true });
  fs.writeFileSync(exe, '#!/bin/sh\n[ -n "$SAY_WARN" ] && echo "WARN: time decreased from 20 to 5"\necho \'{"dir": "x", "runs": [{"id": 7}], "others": 0}\'\n');
  fs.chmodSync(exe, 0o755);
  out.found = await ask({ op: 'list' });
  process.env.SAY_WARN = '1';
  out.warned = await ask({ op: 'list' });
  console.log('RESULT' + JSON.stringify(out)); process.exit(0);
})().catch(e => { console.error(e.stack); process.exit(1); });
'''


@H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
class Extension(unittest.TestCase):
    def test_the_cli_of_a_windows_host(self):
        """T-08 e: on win32 the extension runs bin/windows-x86_64/sva.exe (make dist-windows), and without one names
        wavelens.sva; T-08 c: the runs' JSON read after a "WARN: …" line on stdout (Windows: sva cannot move wellen's aside)."""
        with H.tmp() as d:
            p = H.vcd(d, '#0\n0!\n#10\n1!\n', name='t.vcd')
            r = subprocess.run([NODE, '-e', SCRIPT, FAKE, os.path.join(H.ROOT, 'vscode', 'extension.js'), d, p], capture_output=True, text=True,
                               timeout=60, cwd=d, env={k: v for k, v in os.environ.items() if k != 'SAY_WARN'})   # cwd: no sva/ there
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            o = json.loads(next(x for x in r.stdout.splitlines() if x.startswith('RESULT'))[6:])
            self.assertIn('wavelens.sva', o['none'].get('error', ''), o['none'])
            self.assertIn('win32', o['none']['error'])
            self.assertEqual([x['id'] for x in o['found'].get('runs', [])], [7], o['found'])
            self.assertEqual([x['id'] for x in o['warned'].get('runs', [])], [7], o['warned'])
