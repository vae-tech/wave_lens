"""common.py — what the tools share: time units, * / ? patterns, the wavepeek and sva command-line options, the settings
keys of wavefw/wavefw.config.js, and WaveError.

A library function raises WaveError with a one-line message; each tool's main() catches it once (run_main) and exits
with that message, so a mistake in a config or a missing file is one line, not a traceback. Python >= 3.8.
"""
import os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIT_PS = {'zs': 1e-9, 'as': 1e-6, 'fs': 1e-3, 'ps': 1, 'ns': 1e3, 'us': 1e6, 'ms': 1e9, 's': 1e12}
TS_RE = re.compile(rb'(\d+)\s*(zs|as|fs|ps|ns|us|ms|s)\b')   # the value of a $timescale command
CONFIG_JS = os.path.join(ROOT, 'wavefw', 'wavefw.config.js')
# keys of a "config" object that are not in wavefw.config.js: WaveDrom's own, and an older name the viewer still reads
CONFIG_EXTRA = ('hscale', 'skin', 'groupsFirst')
SELECT_KEYS = ('depth', 'constants', 'hide', 'budget')   # mkconfig.py's "select" in a base file


class WaveError(Exception):
    """A user's mistake or a dump the tools cannot read: the message is the whole story (no traceback)."""


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


def wavepeek(explicit=None):
    """The wavepeek executable: the given one, else on PATH, else ~/.local/bin/wavepeek (may not exist)."""
    return os.path.expanduser(explicit or shutil.which('wavepeek') or '~/.local/bin/wavepeek')


def add_reader_args(ap, default=None):
    ap.add_argument('--reader', choices=('builtin', 'wavepeek'), default=default, help='how the dump is read: builtin (default: one pass in '
                    'Python; an FST through fst2vcd) or wavepeek (any --marker expression)')
    ap.add_argument('--wavepeek', help='wavepeek executable (default: on PATH or ~/.local/bin)')


def add_sva_bin_arg(ap):
    ap.add_argument('--sva-bin', help='the sva CLI (default: $WAVEFW_SVA, out/sva-target/release/sva, the prebuilt '
                    'bin/<os>-x86_64/sva, sva on PATH)')


def config_keys():
    """The settings a "config" object may hold: the keys of wavefw/wavefw.config.js (read now, so a new setting needs no
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
        raise WaveError(f'{where}: unknown setting(s) {hint} — the settings are the keys of wavefw/wavefw.config.js')
