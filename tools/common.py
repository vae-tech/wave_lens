"""common.py — what the tools share: time units, * / ? patterns, the one rule of naming a signal (pick), the sva
command-line option, the settings keys of wavelens/wavelens.config.js, and WaveError.

A library function raises WaveError with a one-line message; each tool's main() catches it once (run_main) and exits
with that message, so a mistake in a config or a missing file is one line, not a traceback. Python >= 3.9.
"""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UNIT_PS = {'zs': 1e-9, 'as': 1e-6, 'fs': 1e-3, 'ps': 1, 'ns': 1e3, 'us': 1e6, 'µs': 1e6, 'ms': 1e9, 's': 1e12}
TS_RE = re.compile(rb'(\d+)\s*(zs|as|fs|ps|ns|us|ms|s)\b')   # the value of a $timescale command
CONFIG_JS = os.path.join(ROOT, 'wavelens', 'wavelens.config.js')
# keys of a "config" object that are not in wavelens.config.js: WaveDrom's own, and an older name the viewer still reads
CONFIG_EXTRA = ('hscale', 'skin', 'groupsFirst')
SELECT_KEYS = ('depth', 'constants', 'hide', 'budget')   # mkconfig.py's "select" in a base file


class WaveError(Exception):
    """A user's mistake or a dump the tools cannot read: the message is the whole story (no traceback)."""


def version():
    """The project's version (VERSION at the top of the checkout)."""
    try:
        with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return '0'


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


def parse_time(v, plain=1):
    """A time as a person writes it -> a number in ps, or None: a number is in plain units (model units in viewedit.py, ns for
    wavemcp.py), a text a number with a unit or none ("1.5us", "100NS", "1E2", "0.1µs", "-5ns"), case-insensitive as the
    viewer's parseT; plain None: a text without a unit is no time."""
    if v is None or v == '' or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return None if plain is None else v * plain
    m = re.fullmatch(r'\s*(-?[\d.]+(?:e-?\d+)?)\s*([a-zµ]+)?\s*', str(v), re.I)
    if not m or (m.group(2) and m.group(2).lower() not in UNIT_PS) or (plain is None and not m.group(2)):
        return None
    try:
        x = float(m.group(1))
    except ValueError:
        return None
    t = x * (UNIT_PS[m.group(2).lower()] if m.group(2) else plain)
    return t if abs(t) != float('inf') else None


def glob_re(pattern, one=True):
    """A full-path pattern with * (any run) and ? (one character; one False: a ? as it is, the viewer's rows) -> compiled
    regex that must match the whole path."""
    return re.compile(''.join('.*' if c == '*' else '.' if c == '?' and one else re.escape(c) for c in pattern) + r'\Z')


def glued(path):
    """A path with no dot before a [: one spelling of an array element (q.[0] and q[0] -> q[0]; every dot, as a path of the
    scope form by wellen, ptr..[0]). One rule with sva/cli/src/vcd.rs glued()."""
    return re.sub(r'\.+\[', '[', path)


def depth(path):
    """How deep a path is: its dots, an array element at its array's level (glued)."""
    return glued(path).count('.')


def nearest(hits, full):
    """Of the rows found for a name: one net at several levels -> the one nearest the top, when it is one -> (rows, how many
    deeper paths were left out)."""
    fulls = list(dict.fromkeys(full(r) for r in hits))
    if len(fulls) < 2:
        return hits, 0
    top = min(depth(f) for f in fulls)
    near = [f for f in fulls if depth(f) == top]
    if len(near) != 1:
        return hits, 0
    return [r for r in hits if full(r) == near[0]], len(fulls) - 1


def pick(pool, s, full=None, name=None, exact=None, bit=None, scope='', tails=True):
    """The one rule of naming a signal on the Python side (tools/viewedit.py Model.pick over a page's rows, vcd2wavedrom.py
    Builtin.find / resolve and wavemcp.py Wave.find over a dump's paths, svabuild.py Names.lookup; the page's twin is
    wavelens/src/edit.js pickRows): one name s (not a pattern) -> (the rows it means, how many deeper paths were left out).
    The first of these that finds any:
      1. the full path: under the scope (scope.s), then s as it is;
      2. a row's own name (name(r): the page's shown name);
      3. the end of a path (… .s), under the scope;
      4. the longest path s ends with (s = … .path: the dump's path of a row the page shows under a shorter one);
      5. a bit of a bus or a select of it (bit(s): the caller's, None when s is none);
    an array element by either spelling at each step (glued: mem.[1] = mem[1]); of several, one net at several levels:
    the one nearest the top when it is one (nearest). pool: the rows; full(r): a row's path (default: the row is its path);
    exact(q): the row of path q or None (a dump's index: its aliases too), else the pool is searched; tails False: step 1
    only (an assertion's names are its instance's own). Several rows left: the caller says it is ambiguous."""
    F = full or (lambda r: r)
    sc = scope.rstrip('.') if scope else ''
    for q in dict.fromkeys(([s if s.startswith(sc + '.') else f'{sc}.{s}'] if sc else []) + [s]):
        if exact:
            r = exact(q)
            hit = [] if r is None else [r]
        else:
            hit = [r for r in pool if F(r) == q]
            if not hit and '[' in q:
                g = glued(q)
                hit = [r for r in pool if glued(F(r)) == g]
        if hit:
            return nearest(hit, F)
    if not tails:
        return [], 0
    under = [r for r in pool if F(r).startswith(sc + '.')] if sc else list(pool)
    hit = [r for r in under if name(r) == s] if name else []
    if not hit:
        tail = '.' + glued(s)
        hit = [r for r in under if glued(F(r)).endswith(tail)]
    if not hit:
        g = glued(s)
        at = [r for r in under if g.endswith('.' + glued(F(r)))]
        n = max((len(glued(F(r))) for r in at), default=0)
        hit = [r for r in at if len(glued(F(r))) == n]
    if not hit and bit:
        b = bit(s)
        if b is not None:
            return [b], 0
    return nearest(hit, F)


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
