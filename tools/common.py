"""common.py — what the tools share: time units, * / ? patterns, the sva command-line option, the settings
keys of wavelens/wavelens.config.js, and WaveError.

A library function raises WaveError with a one-line message; each tool's main() catches it once (run_main) and exits
with that message, so a mistake in a config or a missing file is one line, not a traceback. Python >= 3.8.
"""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIT_PS = {'zs': 1e-9, 'as': 1e-6, 'fs': 1e-3, 'ps': 1, 'ns': 1e3, 'us': 1e6, 'ms': 1e9, 's': 1e12}
TS_RE = re.compile(rb'(\d+)\s*(zs|as|fs|ps|ns|us|ms|s)\b')   # the value of a $timescale command
CONFIG_JS = os.path.join(ROOT, 'wavelens', 'wavelens.config.js')
# keys of a "config" object that are not in wavelens.config.js: WaveDrom's own, and an older name the viewer still reads
CONFIG_EXTRA = ('hscale', 'skin', 'groupsFirst')
SELECT_KEYS = ('depth', 'constants', 'hide', 'budget')   # mkconfig.py's "select" in a base file


class WaveError(Exception):
    """A user's mistake or a dump the tools cannot read: the message is the whole story (no traceback)."""


def version():
    """The project's version (VERSION at the top of the checkout)."""
    with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
        return f.read().strip()


def build_info(by, date=None):
    """The checkout these tools run from, for a page's WAVELENS_BUILD (the bar shows it beside the version): {branch, commit,
    dirty (tracked files changed), tag (one on this commit), date, by}; None outside git (a copy of a release)."""
    def git(*a):
        try:
            r = subprocess.run(['git', '-C', ROOT, *a], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None
    commit = git('rev-parse', '--short', 'HEAD')
    if not commit:
        return None
    out = {'branch': git('rev-parse', '--abbrev-ref', 'HEAD'), 'commit': commit,
           'dirty': bool(git('status', '--porcelain', '--untracked-files=no')), 'tag': git('describe', '--tags', '--exact-match'),
           'date': date, 'by': by}
    return {k: v for k, v in out.items() if v not in (None, '')}


def run_main(main, tool):
    """Run a tool's main(); a WaveError ends it with its message (exit 1), as SystemExit(msg) did."""
    try:
        return main()
    except WaveError as e:
        msg = str(e)
        sys.exit(msg if msg.startswith(tool + ':') else f'{tool}: {msg}')


def glob_re(pattern):
    """A full-path pattern with * (any run) and ? (one character) -> compiled regex that must match the whole path."""
    return re.compile(''.join('.*' if c == '*' else '.' if c == '?' else re.escape(c) for c in pattern) + r'\Z')


def add_sva_bin_arg(ap):
    ap.add_argument('--sva-bin', help='the sva CLI (default: $WAVELENS_SVA, out/sva-target/release/sva, the prebuilt '
                    'bin/<os>-x86_64/sva, sva on PATH)')


def config_keys():
    """The settings a "config" object may hold: the keys of wavelens/wavelens.config.js (read now, so a new setting needs no
    change here) and CONFIG_EXTRA."""
    try:
        with open(CONFIG_JS, encoding='utf-8') as f:
            keys = re.findall(r'^ {2}(\w+):', f.read(), re.M)
    except OSError:
        return None   # the tools without the framework next to them: nothing to check against
    return set(keys) | set(CONFIG_EXTRA)


def check_config(cfg, where):
    """A "config" object's keys against config_keys(): an unknown one (a typo) is an error naming the close ones."""
    keys = config_keys()
    if not keys or not isinstance(cfg, dict):
        return
    bad = sorted(set(cfg) - keys)
    if bad:
        near = lambda k: [x for x in sorted(keys) if x.lower() == k.lower() or (len(k) > 3 and (x.lower().startswith(k.lower()[:4])))]
        hint = '; '.join(f'{k} (did you mean {" or ".join(near(k)[:3])}?)' if near(k) else k for k in bad)
        raise WaveError(f'{where}: unknown setting(s) {hint} — the settings are the keys of wavelens/wavelens.config.js')
