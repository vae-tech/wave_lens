"""The repository's promises: one version (VERSION, wavefw.js, CHANGELOG.md, the CLI), make help lists every target, the docs' settings table is the settings file's keys, the
tools answer --help, the converter's per-signal keys are documented and read by the page."""
import os, re, subprocess, unittest

from tests.unit import helpers as H
import common
import vcd2wavedrom


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


class Version(unittest.TestCase):
    def test_one_version_everywhere(self):
        v = read('VERSION').strip()
        self.assertRegex(v, r'^\d+\.\d+$')                                          # two numbers: MAJOR.MINOR
        self.assertEqual(re.search(r"version: '([^']+)'", read('wavefw', 'src', 'boot.js')).group(1), v)
        self.assertEqual(re.search(r'^## (\S+)', read('CHANGELOG.md'), re.M).group(1), v)   # the top entry
        self.assertIn('include_str!("../../../VERSION")', read('sva', 'cli', 'src', 'main.rs'))


class Docs(unittest.TestCase):
    def test_settings_table_is_the_settings_file(self):
        html = read('docs', 'index.html')
        a = html.index('<h3>Settings (config file)</h3>')
        rows = re.findall(r'<tr><td class="mono">([^<]+)</td>', html[a:html.index('</table>', a)])
        documented = {k.strip() for r in rows for k in r.split(',')}
        self.assertEqual(documented ^ (common.config_keys() - set(common.CONFIG_EXTRA)), set())

    def test_model_defaults_are_the_settings_file(self):
        js = read('wavefw', 'wavefw.config.js')
        model = read('wavefw', 'src', 'model.js')
        body = re.search(r'const DEFAULTS = \{(.*?)\};', model, re.S).group(1)
        for k, v in re.findall(r'(\w+): ([^,]+?)(?=, \w+:|\s*$)', body.replace('\n', ' ')):
            with self.subTest(k):
                m = re.search(r'^ {2}%s: ([^,]+),' % k, js, re.M)
                self.assertIsNotNone(m, f'{k} of DEFAULTS is not in wavefw.config.js')
                if k != 'sortIgnore':   # the settings file sets i_, o_ (said in its header)
                    self.assertEqual(m.group(1).strip(), v.strip())

    def test_usage_lists_the_signal_keys(self):
        usage = read('docs', 'USAGE.md')
        self.assertEqual([k for k in vcd2wavedrom.SIG_KEYS if f'`{k}`' not in usage], [])

    def test_page_reads_the_signal_keys(self):
        model = read('wavefw', 'src', 'model.js')
        info = {'show', 'alias', 'changes'}   # the converter's own: a row left out, its name, information
        self.assertEqual([k for k in vcd2wavedrom.SIG_KEYS if k not in info and f'it.{k}' not in model], [])

    def test_tools_help(self):
        for t in ('vcd2wavedrom', 'mkconfig', 'mkhtml', 'embed', 'svabuild', 'wavefwcat'):
            with self.subTest(t):
                rc, out, _ = H.run_tool(t, '--help')
                self.assertEqual(rc, 0)
                self.assertIn('usage:', out)


if __name__ == '__main__':
    unittest.main()
