#!/usr/bin/env python3
"""wavemcp.py — the wavefw tools as an MCP server (Model Context Protocol, JSON-RPC over stdio) for an AI agent.

An agent asks questions of a dump (VCD, or FST through fst2vcd or the sva CLI) and gets short answers instead of reading the dump:
the signals, values at a time, changes in a window, a clock-sampled table, searches by an SV expression or sequence
(the sva engine), aggregates, SystemVerilog assertions checked over the dump with their first failures, and a viewer
page (or the WaveJSON) of a window for a person. The dump is read once per server (the declarations and the change counts); a
signal's transitions when a tool first needs it, then kept. The agent marks a page up for the person with the viewer's
commands (view_edit: bookmarks with a text, arrows, markers, groups, highlight, colours, cursor, window; tools/viewedit.py
has them) and reads what is there (view_get): live in their browser once view_live has connected the page (an HTTP
server of this process on 127.0.0.1, from port 8742 or WAVEFW_LIVE_PORT on, its key in ~/.cache/wavefw/live-token),
else in the page's file. Times are ns in and out (a number), or a text with a unit
("2.5us"); signal names are full paths, paths under "scope", or a unique tail of a path ("PSEL", "u_regs.PSEL").

  claude mcp add wavefw -- python3 -I /path/to/wavefw/tools/wavemcp.py      # Claude Code
  codex mcp add wavefw -- python3 -I /path/to/wavefw/tools/wavemcp.py       # Codex CLI
  wavemcp.py --list                                     # the tools and their input schemas
  wavemcp.py --call wave_info '{"dump": "out/examples/apb/apb.vcd"}'   # one tool from the shell (tests, the benchmark)

Standard library only; the sva CLI as svabuild.py finds it (--sva-bin, $WAVEFW_SVA, the build, bin/<os>/sva, PATH).
docs/USAGE.md § "AI agents (MCP)" has the tools; tests/mcp_bench.py measures what they save.
"""
import argparse, bisect, collections, contextlib, fnmatch, hmac, http.server, json, os, queue, re, secrets, shutil, statistics, subprocess, sys
import tempfile, threading, time, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
import dumpscan, svabuild, vcd2wavedrom, viewedit  # noqa: E402
from common import ROOT, UNIT_PS, WaveError  # noqa: E402

PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')
MAX_TEXT = 60000   # characters of one answer: above it the agent is asked to narrow the request
CLOCK_RE = re.compile(r'clk|clock', re.I)
RESET_RE = re.compile(r'rst|reset', re.I)
INSTRUCTIONS = (
    'Waveform (VCD/FST) analysis. Times are ns (numbers) unless a unit is given ("2.5us"). Signal names: full path, '
    'path under "scope", or a unique tail ("PSEL"). Start with wave_info, then wave_signals to find names; ask for '
    'values (wave_values, wave_changes, wave_sample), search with wave_find (an SV expression or sequence on a clock, '
    'or a value / edge of one signal), count with wave_stats, check SystemVerilog assertions with sva_check. Sampled '
    'values are the ones just before the clock edge, as SVA samples; cycle numbers are the clock\'s rising edges from '
    'the start of the dump (the same as sva_check\'s). Long answers are cut at "limit" ("more", "next_from" / '
    '"next_offset" say how to go on). wave_page writes a viewer page to show a person; view_edit marks it up for them '
    '(bookmarks with a text, arrows, markers, groups, highlight, colours, cursor, window), live in their browser after '
    'view_live, else in the page\'s file (they reload it); view_get reads what is there, their own edits too.')


def version():
    try:
        with open(os.path.join(ROOT, 'VERSION'), encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return '0'


# ---------------- times ----------------
def ps_of(v, what='time'):
    """A time from the agent: a number (ns) or a text with a unit -> ps."""
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) * 1000
    s = str(v).strip()
    if re.fullmatch(r'-?[\d.]+(?:e-?\d+)?', s):
        return float(s) * 1000
    m = re.fullmatch(r'([\d.]+(?:e-?\d+)?)\s*(zs|as|fs|ps|ns|us|ms|s)', s)
    if not m:
        raise WaveError(f'bad {what} "{v}": a number of ns or a text with a unit ("250ns", "2.5us")')
    return float(m.group(1)) * UNIT_PS[m.group(2)]


def ns(ps):
    """ps -> ns as a short number (integers stay integers)."""
    v = round(ps / 1000, 6)
    return int(v) if v == int(v) else v


# ---------------- one dump ----------------
class Wave(vcd2wavedrom.Builtin):
    """A dump read once: the declarations, change counts, start and end; the transitions of a signal read (one pass for
    all the missing ones) when a tool first needs them and kept. stream(), edges() are the converter's built-in reader."""

    def __init__(self, path):
        if not os.path.isfile(path):
            raise WaveError(f'no such dump: {path}')
        if not dumpscan.available(path):
            raise WaveError(f'{os.path.basename(path)}: an FST is read through fst2vcd (GTKWave) or the sva CLI, and neither is there')
        self.waves, self.scope, self.streams = path, '', {}
        self.stamp = (os.path.getmtime(path), os.path.getsize(path))
        self.decl = dumpscan.read(path, 'count')
        self.t_start, self.t_end = self.decl.t_start, self.decl.t_end
        self.d = dumpscan.Dump()
        self.d.unit_ps, self.have = self.decl.unit_ps, set()
        self._clocks = None

    def load(self, paths):
        codes = {c for p in paths for c, _ in self.decl.vars[p].members} - self.have
        if codes:
            got = dumpscan.read(self.waves, 'collect', codes)
            self.d.trans.update(got.trans)
            self.have |= codes

    def find(self, name, scope=''):
        """A signal by its path, its path under scope, or a unique tail of a path; a [msb:lsb] or [bit] select of one
        -> (path, select or None)."""
        name = str(name).strip()
        for q in ([scope.rstrip('.') + '.' + name] if scope else []) + [name]:
            hit = self.decl.find(q)
            if hit:
                return hit, None
        m = re.fullmatch(r'(.+?)\[(\d+)(?::(\d+))?\]', name)
        if m:
            try:
                path, _ = self.find(m.group(1), scope)
            except WaveError:
                path = None
            if path:
                hi = int(m.group(2))
                return path, (hi, int(m.group(3)) if m.group(3) is not None else hi)
        under = [p for p in self.decl.vars if not scope or p.startswith(scope.rstrip('.') + '.')]
        tails = sorted((p for p in under if p.endswith('.' + name)), key=lambda p: (p.count('.'), p))
        if len(tails) == 1:
            return tails[0], None
        if len(tails) > 1 and tails[0].count('.') < tails[1].count('.'):   # one at the shallowest level: that one, said
            NOTES.append(f'{name} = {tails[0]} (+{len(tails) - 1} deeper)')
            return tails[0], None
        if tails:
            raise WaveError(f'"{name}" is ambiguous: {", ".join(tails[:8])}' + (f' (+{len(tails) - 8})' if len(tails) > 8 else '')
                            + ' — give more of its path or a scope')
        low = name.lower().split('.')[-1]
        leaf = lambda p: p.rsplit('.', 1)[-1].lower()
        near = sorted((p for p in under if low in leaf(p) or (len(leaf(p)) > 2 and leaf(p) in low)), key=len)[:6]
        raise WaveError(f'no signal "{name}"' + (f' under {scope}' if scope else '') + (f'; similar: {", ".join(near)}' if near else ''))

    def width(self, path, sl):
        return sl[0] - sl[1] + 1 if sl else self.decl.vars[path].width

    def text(self, path, sl, v, radix=None):
        """A normalised value (stream()) -> what the agent reads: 0 1 x z for a bit, the label of a bus (enum, radix)."""
        if v is None:
            return None
        var = self.decl.vars[path]
        if var.kind in dumpscan.TEXT_KINDS or self.width(path, sl) == 1:
            return v
        return vcd2wavedrom.label(v, self.width(path, sl), None if sl else var.enum, radix)

    def signals(self, names, scope=''):
        """The signals asked for (a list, or a text with commas) -> (the names as given, [(path, select)]), loaded. Of
        several, one not found is left out and named in the answer's "missing" (all of them not found: the error)."""
        if isinstance(names, str):
            names = [n for n in re.split(r'[,\s]+', names) if n]
        if not names:
            raise WaveError('no signals given')
        got, errs = [], []
        for n in names:
            try:
                p, sl = self.find(n, scope)
                if self.decl.vars[p].kind == 'event':
                    raise WaveError(f'"{n}" is an event: it has no value')
                got.append((n, (p, sl)))
            except WaveError as e:
                errs.append(str(e))
        if errs and (len(names) == 1 or not got):
            raise WaveError('; '.join(errs))
        MISSING.extend(errs)
        self.load([p for _, (p, _) in got])
        return [n for n, _ in got], [r for _, r in got]

    def clocks(self):
        """[(path, period ps, first rising edge ps, rising edges)] of the 1-bit *clk* / *clock* signals that toggle, one
        per net (the same clock in several scopes is listed once, at its shortest path)."""
        if self._clocks is None:
            cand = [p for p, v in self.decl.vars.items() if v.width == 1 and v.kind != 'event' and CLOCK_RE.search(p.rsplit('.', 1)[-1])
                    and (self.decl.changes.get(p) or 0) >= 3]
            cand.sort(key=lambda p: (-(self.decl.changes.get(p) or 0), p.count('.'), p))
            cand = cand[:24]
            self.load(cand)
            seen, out = {}, []
            for p in sorted(cand, key=lambda p: (p.count('.'), p)):
                rises = self.edges(p, 'posedge', float('-inf'), float('inf'))
                if len(rises) < 2:
                    continue
                key = (len(rises), rises[0], rises[-1])
                if key in seen:
                    continue
                seen[key] = p
                out.append((p, statistics.median(b - a for a, b in zip(rises, rises[1:])), rises[0], len(rises)))
            self._clocks = out
        return self._clocks

    def clock_for(self, clock, scope, near=()):
        """The clock to sample on: the one named, else the clock nearest to the signals (the longest common scope)."""
        if clock:
            p, sl = self.find(clock, scope)
            if sl or self.decl.vars[p].width != 1:
                raise WaveError(f'the clock "{clock}" is not a 1-bit signal')
            self.load([p])
            return p
        cl = self.clocks()
        if not cl:
            raise WaveError('no clock found (a 1-bit *clk* / *clock* that toggles): give "clock"')
        def common(a, b):
            n = 0
            for x, y in zip(a.split('.'), b.split('.')):
                if x != y:
                    break
                n += 1
            return n
        ref = list(near) or ([scope] if scope else [])
        return max(cl, key=lambda c: (sum(common(c[0], r) for r in ref), c[3]))[0]

    def at(self, st, t, before=False):
        """The value of a stream at t: after the changes at t, or (before) the one just before them."""
        i = (bisect.bisect_left(st, (t, '')) if before else bisect.bisect_right(st, (t, '\uffff'))) - 1
        return st[i][1] if i >= 0 else None


WAVES = {}
NOTES = []   # the names a tool resolved by a guess (the shallowest of several): said in its answer
MISSING = []   # the names of several that were not found: said in the answer, the others answered


def wave(path):
    """The cached Wave of a dump (read again when the file changed)."""
    if not path:
        raise WaveError('"dump" is required: the path of a VCD or FST')
    key = os.path.abspath(os.path.expanduser(str(path)))
    w = WAVES.get(key)
    if w is None or w.stamp != (os.path.getmtime(key) if os.path.isfile(key) else None, os.path.getsize(key) if os.path.isfile(key) else None):
        w = WAVES[key] = Wave(key)
    return w


def window(w, a):
    t0 = ps_of(a.get('from'), 'from')
    t1 = ps_of(a.get('to'), 'to')
    t0 = w.t_start if t0 is None else t0
    t1 = w.t_end if t1 is None else t1
    if t1 < t0:
        raise WaveError(f'"to" ({ns(t1)}) is before "from" ({ns(t0)})')
    return t0, t1


def limit(a, default, top=10000):
    n = a.get('limit', default)
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise WaveError('"limit" is a positive number')
    return min(n, top)


# ---------------- the tools ----------------
def t_info(a):
    w = wave(a.get('dump'))
    scopes = collections.Counter()
    for p in w.decl.vars:
        parts = svabuild.split_path(p)[:-1]
        for i in range(1, min(len(parts), 3) + 1):
            scopes['.'.join(parts[:i])] += 1
    top = sorted(scopes.items(), key=lambda kv: kv[0])
    out = {'file': os.path.basename(w.waves), 'unit': 'ns', 'resolution_ns': ns(w.decl.unit_ps),
           'start': ns(w.t_start), 'end': ns(w.t_end), 'signals': len(w.decl.vars),
           'changes': sum(w.decl.changes.values()),
           'scopes': [[s, n] for s, n in top[:40]] + ([['…', len(top) - 40]] if len(top) > 40 else []),
           'clocks': [{'name': p, 'period': ns(per), 'mhz': round(1e6 / per, 3) if per else None, 'first_rise': ns(t0), 'rises': n}
                      for p, per, t0, n in w.clocks()[:8]],
           'resets': sorted((p for p, v in w.decl.vars.items() if v.width == 1 and RESET_RE.search(p.rsplit('.', 1)[-1])),
                            key=lambda p: (p.count('.'), p))[:6]}
    return out


def t_signals(a):
    w = wave(a.get('dump'))
    scope = (a.get('scope') or '').rstrip('.')
    pat = (a.get('pattern') or '').strip()
    rx = None
    if pat and any(c in pat for c in '*?['):
        rx = re.compile(fnmatch.translate(pat), re.I)
    items = []
    for p, v in w.decl.vars.items():
        if scope and not p.startswith(scope + '.'):
            continue
        rel = p[len(scope) + 1:] if scope else p
        if a.get('depth') is not None and rel.count('.') >= int(a['depth']):
            continue
        if rx and not (rx.fullmatch(p) or rx.fullmatch(rel) or rx.fullmatch(p.rsplit('.', 1)[-1])):
            continue
        if pat and not rx and pat.lower() not in p.lower():
            continue
        if a.get('active') and not w.decl.changes.get(p):
            continue
        items.append((rel, v, w.decl.changes.get(p) or 0))
    off = int(a.get('offset') or 0)
    n = limit(a, 200)
    page = items[off:off + n]
    out = {'total': len(items), 'scope': scope or None, 'columns': ['path', 'width', 'changes'],
           'signals': [[rel, v.width, c] + ([{'enum': len(v.enum)}] if v.enum else []) + ([v.kind] if v.kind not in ('wire', 'reg', 'logic') else [])
                       for rel, v, c in page]}
    if off + n < len(items):
        out['next_offset'] = off + n
    return out


def t_values(a):
    w = wave(a.get('dump'))
    scope, radix = a.get('scope') or '', a.get('radix')
    at = a.get('at')
    times = at if isinstance(at, list) else [at]
    if not times or times == [None]:
        raise WaveError('"at" is required: a time or a list of times')
    if len(times) > 200:
        raise WaveError('"at": 200 times at most (wave_sample gives a value per clock cycle)')
    names, res = w.signals(a.get('signals'), scope)
    before = a.get('side') == 'before'
    rows = []
    for t in times:
        tp = ps_of(t)
        rows.append([ns(tp)] + [w.text(p, sl, w.at(w.stream(p, sl), tp, before), radix) for p, sl in res])
    return {'unit': 'ns', 'side': 'before' if before else 'after', 'columns': ['t'] + list(names), 'rows': rows}


def t_changes(a):
    w = wave(a.get('dump'))
    scope, radix = a.get('scope') or '', a.get('radix')
    t0, t1 = window(w, a)
    n = limit(a, 50)
    names, res = w.signals(a.get('signals'), scope)
    out = {'unit': 'ns', 'from': ns(t0), 'to': ns(t1), 'signals': {}}
    for name, (p, sl) in zip(names, res):
        st = w.stream(p, sl)
        lo, hi = bisect.bisect_right(st, (t0, '\uffff')), bisect.bisect_right(st, (t1, '\uffff'))
        ch = st[lo:hi]
        e = {'initial': w.text(p, sl, w.at(st, t0), radix), 'count': len(ch),
             'changes': [[ns(t), w.text(p, sl, v, radix)] for t, v in ch[:n]]}
        if len(ch) > n:
            e['more'] = len(ch) - n
            e['next_from'] = ns(ch[n][0])
        out['signals'][name] = e
    return out


def t_sample(a):
    w = wave(a.get('dump'))
    scope, radix = a.get('scope') or '', a.get('radix')
    t0, t1 = window(w, a)
    n = limit(a, 100)
    names, res = w.signals(a.get('signals'), scope)
    clk = w.clock_for(a.get('clock'), scope, [p for p, _ in res])
    edge = a.get('edge') or 'posedge'
    if edge not in ('posedge', 'negedge', 'edge'):
        raise WaveError('"edge" is posedge, negedge or edge')
    allt = w.edges(clk, edge, float('-inf'), float('inf'))
    lo, hi = bisect.bisect_left(allt, t0), bisect.bisect_right(allt, t1)
    only = a.get('only_changes', True)
    sts = [w.stream(p, sl) for p, sl in res]
    rows, prev, kept = [], None, 0
    for c in range(lo, hi):
        t = allt[c]
        vals = [w.text(p, sl, w.at(st, t, True), radix) for (p, sl), st in zip(res, sts)]
        if only and vals == prev:
            continue
        prev = vals
        kept += 1
        if len(rows) < n:
            rows.append([c, ns(t)] + vals)
    out = {'unit': 'ns', 'clock': clk, 'edge': edge, 'sampled': 'just before the edge', 'cycles': hi - lo,
           'first_cycle': lo, 'columns': ['cycle', 't'] + list(names), 'rows': rows}
    if only:
        out['only_changes'] = True
    if kept > len(rows):
        out['more'] = kept - len(rows)
        out['next_from'] = rows[-1][1] + 1e-3 if rows else None
    return out


def bits_value(want, width):
    """A value to look for -> the normalised form of a stream (hex digits, 0 1 x z), or None for a label."""
    s = str(want).strip().lower().replace('_', '')
    m = re.fullmatch(r"(?:(\d*)')?(?:([hdbo])|0([xbo]))?([0-9a-fxz]+)", s)
    if not m:
        return None
    base = (m.group(2) or {'x': 'h', 'b': 'b', 'o': 'o'}.get(m.group(3) or '', 'd'))
    digits = m.group(4)
    if digits in ('x', 'z'):
        return digits
    if re.search('[xz]', digits) and base in ('b', 'h'):   # four-state: the stream's form of those bits ("'b10x1", or hex)
        bits = digits if base == 'b' else ''.join(c * 4 if c in 'xz' else format(int(c, 16), '04b') for c in digits)
        if not re.fullmatch('[01xz]+', bits):
            return None
        if m.group(1):   # sized (4'bx1): x / z extended to its size, then 0s to the signal's width
            n = int(m.group(1))
            bits = bits.rjust(n, bits[0] if bits[0] in 'xz' else '0')[-n:].rjust(width, '0')
        return vcd2wavedrom.norm(f"{width}'b{bits.rjust(width, bits[0] if bits[0] in 'xz' else '0')[-width:]}", width)
    try:
        n = int(digits, {'h': 16, 'd': 10, 'b': 2, 'o': 8}[base])
    except ValueError:
        return None
    if width == 1:
        return str(n & 1) if n in (0, 1) else None
    return format(n, 'x').rjust((width + 3) // 4, '0')


def t_find(a):
    w = wave(a.get('dump'))
    scope = a.get('scope') or ''
    t0, t1 = window(w, a)
    n = limit(a, 20)
    if a.get('expr'):
        return find_expr(w, a, scope, t0, t1, n)
    if not a.get('signal'):
        raise WaveError('give "expr" (an SV expression or sequence, sampled on a clock) or "signal" with "edge" or "value"')
    _, ((p, sl),) = w.signals([a['signal']], scope)
    st, width = w.stream(p, sl), w.width(p, sl)
    if a.get('value') is not None:
        want = str(a['value'])
        raw = bits_value(want, width)
        hits = []
        prev = w.at(st, t0)
        if prev is not None and (prev == raw or w.text(p, sl, prev, a.get('radix')) == want):
            hits.append(t0)
        lo = bisect.bisect_right(st, (t0, '\uffff'))
        for t, v in st[lo:]:
            if t > t1:
                break
            hit = v == raw or w.text(p, sl, v, a.get('radix')) == want
            if hit and not (prev == v):
                hits.append(t)
            prev = v
        rows = []
        for t in hits[:n]:
            j = bisect.bisect_right(st, (t, '\uffff'))
            end = st[j][0] if j < len(st) else None
            rows.append([ns(t), ns(end - t) if end is not None else None])
        out = {'unit': 'ns', 'signal': a['signal'], 'value': want, 'matches': len(hits), 'columns': ['t', 'lasts'], 'rows': rows}
    else:
        edge = {'rise': 'posedge', 'fall': 'negedge', 'any': 'change', 'change': 'change', 'posedge': 'posedge',
                'negedge': 'negedge', 'edge': 'edge'}.get(a.get('edge') or 'change')
        if not edge:
            raise WaveError('"edge" is rise, fall or change')
        ts = w.edges(p, edge, t0, t1)
        out = {'unit': 'ns', 'signal': a['signal'], 'edge': a.get('edge') or 'change', 'matches': len(ts), 'times': [ns(t) for t in ts[:n]]}
        hits = ts
    if len(hits) > n:
        out['more'] = len(hits) - n
    return out


def run_sva(w, files, extra, scope, a, t0=None, t1=None):
    """sva eval of the files (+ a text) in scope -> (results dict or None, stderr lines)."""
    exe = svabuild.find_bin(a.get('sva_bin'))
    if not exe:
        raise WaveError('no sva CLI (make sva-build, or bin/<os>-x86_64/sva): the assertions need it')
    with tempfile.TemporaryDirectory(prefix='wavemcp-') as d:
        srcs = []
        for f in files:
            f = os.path.expanduser(str(f))
            if not os.path.isfile(f):
                raise WaveError(f'no such file: {f}')
            srcs.append(f)
        if extra:
            q = os.path.join(d, 'inline.sv')
            with open(q, 'w', encoding='utf-8') as fh:
                fh.write(extra if extra.endswith('\n') else extra + '\n')
            srcs.append(q)
        if not srcs:
            raise WaveError('give "files" (SystemVerilog files with assertions) or "source" (assertions as text)')
        out = os.path.join(d, 'r.json')
        cmd = [exe, 'eval', '--waves', w.waves, '--out', out]
        if scope:
            cmd += ['--scope', scope]
        for s in srcs:
            cmd += ['--sva', s]
        if t0 is not None and t0 > w.t_start:
            cmd += ['--from', f'{ns(t0)}ns']
        if t1 is not None and t1 < w.t_end:
            cmd += ['--to', f'{ns(t1)}ns']
        for k, v in (a.get('defines') or {}).items():
            cmd += ['-D', f'{k}={v}' if v not in (None, '') else str(k)]
        if a.get('resolve'):
            cmd += ['--resolve', a['resolve']]
        r = subprocess.run(cmd, capture_output=True, text=True)
        msgs = [l.replace(d + os.sep, '') for l in r.stderr.splitlines() if l.strip() and not re.match(r'sva: \d+ assertions over', l)]
        res = None
        if os.path.isfile(out):
            with open(out, encoding='utf-8') as fh:
                res = json.load(fh)
        return res, msgs


def default_scope(w, near=()):
    """The scope for SVA names: the common scope of the signals given, else the top module."""
    paths = [svabuild.split_path(p)[:-1] for p in near]
    if paths:
        common = paths[0]
        for q in paths[1:]:
            common = [x for x, y in zip(common, q) if x == y][:len(common)]
        if common:
            return '.'.join(common)
    tops = sorted({svabuild.split_path(p)[0] for p in w.decl.vars})
    return tops[0] if len(tops) == 1 else ''


def find_expr(w, a, scope, t0, t1, n):
    expr = str(a['expr']).strip().rstrip(';')
    clk = w.clock_for(a.get('clock'), scope)
    if not scope:
        scope = default_scope(w, [clk])
    cname = clk[len(scope) + 1:] if scope and clk.startswith(scope + '.') else clk
    edge = a.get('edge') if a.get('edge') in ('posedge', 'negedge', 'edge') else 'posedge'
    src = f'wavemcp_find: cover property (@({edge} {cname}) {expr});\n'
    res, msgs = run_sva(w, [], src, scope, a, t0, t1)
    if not res or not res.get('assertions'):
        raise WaveError('the expression did not evaluate: ' + ' | '.join(msgs[:6]))
    r = res['assertions'][0]
    if r.get('missing'):
        raise WaveError(f'no {", ".join(r["missing"])} in scope {scope or "(top)"} — give "scope" or full names')
    cyc = res.get('cycles') or []
    tm = lambda c: ns(cyc[c] * UNIT_PS.get(res.get('unit', 'ps'), 1)) if 0 <= c < len(cyc) else None
    hits = [x for x in r.get('attempts', []) if x.get('result') == 'pass']
    rows = [[x['start'], tm(x['start'])] + ([x['end'], tm(x['end'])] if x['end'] != x['start'] else []) for x in hits[:n]]
    out = {'unit': 'ns', 'expr': expr, 'clock': clk, 'scope': scope or None, 'sampled': 'just before the edge',
           'cycles': len(cyc), 'matches': r.get('stats', {}).get('matches', len(hits)),
           'columns': ['cycle', 't', 'end_cycle', 'end_t'], 'rows': rows}
    if len(hits) > n:
        out['more'] = len(hits) - n
    return out


def t_stats(a):
    w = wave(a.get('dump'))
    scope, radix = a.get('scope') or '', a.get('radix')
    t0, t1 = window(w, a)
    names, res = w.signals(a.get('signals'), scope)
    out = {'unit': 'ns', 'from': ns(t0), 'to': ns(t1), 'signals': {}}
    span = max(t1 - t0, 1e-9)
    for name, (p, sl) in zip(names, res):
        st = w.stream(p, sl)
        segs = []   # (value, start, end) clipped to the window
        cur, start = w.at(st, t0), t0
        for t, v in st[bisect.bisect_right(st, (t0, '\uffff')):]:
            if t > t1:
                break
            if v != cur:
                segs.append((cur, start, t))
                cur, start = v, t
        segs.append((cur, start, t1))
        changes = len(segs) - 1
        e = {'changes': changes}
        if w.width(p, sl) == 1 and w.decl.vars[p].kind not in dumpscan.TEXT_KINDS:
            rises = w.edges(p, 'posedge', t0, t1)
            falls = w.edges(p, 'negedge', t0, t1)
            dur = collections.Counter()
            for v, s, t in segs:
                dur[v] += t - s
            e.update(rises=len(rises), falls=len(falls), high_pct=round(100 * dur['1'] / span, 2))
            if dur['x'] or dur['z'] or dur[None]:
                e['unknown_pct'] = round(100 * (dur['x'] + dur['z'] + dur[None]) / span, 2)
            for lvl, key in (('1', 'high'), ('0', 'low')):
                full = [t - s for v, s, t in segs[1:-1] if v == lvl]   # whole pulses: not cut by the window
                if full:
                    e[key] = {'min': ns(min(full)), 'max': ns(max(full)), 'count': len(full)}
            if len(rises) > 1:
                gaps = [b - x for x, b in zip(rises, rises[1:])]
                e['period'] = {'median': ns(statistics.median(gaps)), 'min': ns(min(gaps)), 'max': ns(max(gaps))}
        else:
            by = collections.defaultdict(lambda: [0, 0.0])
            for v, s, t in segs:
                by[v][0] += 1
                by[v][1] += t - s
            top = sorted(by.items(), key=lambda kv: -kv[1][1])
            e['distinct'] = len(by)
            e['values'] = [[w.text(p, sl, v, radix), c, round(100 * d / span, 2)] for v, (c, d) in top[:10]]
            e['values_columns'] = ['value', 'times', 'pct_of_time']
            nums = [int(v, 16) for v in by if v and re.fullmatch('[0-9a-f]+', v)]
            if nums and w.decl.vars[p].kind not in dumpscan.TEXT_KINDS:
                hx = lambda n: format(n, 'x').rjust((w.width(p, sl) + 3) // 4, '0')
                e['min'], e['max'] = w.text(p, sl, hx(min(nums)), radix), w.text(p, sl, hx(max(nums)), radix)
        out['signals'][name] = e
    return out


def t_sva(a):
    w = wave(a.get('dump'))
    t0, t1 = window(w, a)
    scope = a.get('scope') or default_scope(w)
    files = a.get('files') or []
    files = [files] if isinstance(files, str) else files
    pats = a.get('assertions') or []
    pats = [pats] if isinstance(pats, str) else pats
    code = [x for x in pats if re.search(r'\bproperty\b|\|[-=]>|##|\(', x)]
    if code:   # assertion text where the names to report go: evaluated as source (and every result reported)
        a = dict(a, source='\n'.join(filter(None, [a.get('source')] + [x if ':' in x.split('(')[0] or not x.lstrip().startswith(
            ('assert', 'cover', 'assume')) else f'wavemcp_{i}: {x}' for i, x in enumerate(code)])))
        pats = [x for x in pats if x not in code]
    res, msgs = run_sva(w, files, a.get('source'), scope, a, t0, t1)
    if not res:
        raise WaveError('nothing evaluated: ' + ' | '.join(msgs[:10]))
    cyc = res.get('cycles') or []
    tm = lambda c: ns(cyc[c] * UNIT_PS.get(res.get('unit', 'ps'), 1)) if isinstance(c, int) and 0 <= c < len(cyc) else None
    mf = a.get('max_failures', 3)
    out = {'unit': 'ns', 'scope': scope or None, 'clock': res.get('clock'), 'cycles': len(cyc), 'failed': [], 'passed': [],
           'vacuous': [], 'not_evaluated': [], 'covered': [], 'not_covered': []}
    for r in res.get('assertions', []):
        if pats and not any(fnmatch.fnmatchcase(r['name'], p) for p in pats):
            continue
        s = r.get('stats', {})
        if r.get('missing'):
            out['not_evaluated'].append([r['name'], 'no ' + ', '.join(r['missing'])])
        elif r.get('kind') == 'cover':
            m = s.get('matches', s.get('pass', 0))
            first = next((x['start'] for x in r.get('attempts', []) if x.get('result') == 'pass'), None)
            (out['covered'] if m else out['not_covered']).append([r['name'], m, tm(first)] if m else r['name'])
        elif s.get('fail'):
            fails = [x for x in r.get('attempts', []) if x.get('result') == 'fail']
            e = {'name': r['name'], 'line': r.get('line'), 'text': r.get('text'),
                 'stats': {k: s[k] for k in ('attempts', 'pass', 'fail', 'vacuous') if k in s},
                 'failures': [[x.get('failed_at', x['end']), tm(x.get('failed_at', x['end'])), x['start'], tm(x['start']), x.get('note')]
                              for x in fails[:mf]],
                 'columns': ['cycle', 't', 'start_cycle', 'start_t', 'note']}
            if len(fails) > mf:
                e['more'] = len(fails) - mf
            out['failed'].append(e)
        elif s.get('pass'):
            out['passed'].append([r['name'], s.get('pass'), s.get('vacuous', 0)] if a.get('details') else r['name'])
        else:
            out['vacuous'].append(r['name'])
        for k in ('active', 'capped'):
            if s.get(k):
                out.setdefault('no_verdict', []).append([r['name'], k, s[k]])
    for k in [k for k, v in out.items() if v == []]:
        del out[k]
    if msgs:
        out['messages'] = msgs[:12] + ([f'… {len(msgs) - 12} more'] if len(msgs) > 12 else [])
    return out


def converter_args(w, a, scope):
    _, res = w.signals(a.get('signals'), scope)
    argv = ['--waves', w.waves, '--signals', ','.join(p + (f'[{sl[0]}:{sl[1]}]' if sl else '') for p, sl in res)]
    clk = a.get('clock')
    if clk is True or clk == 'auto':
        clk = w.clock_for(None, scope, [p for p, _ in res])
    elif clk:
        clk = w.clock_for(clk, scope)
    argv += ['--clock', clk] if clk else ['--exact']
    t0, t1 = window(w, a)
    argv += ['--from', f'{ns(t0)}ns', '--to', f'{ns(t1)}ns']
    if a.get('auto_gap') and clk:
        argv += ['--auto-gap', str(a['auto_gap'])]
    if a.get('hierarchy'):
        argv += ['--hierarchy']
    return argv


def t_page(a):
    w = wave(a.get('dump'))
    out = a.get('out')
    if not out:
        raise WaveError('"out" is required: the HTML page (or .json: the WaveJSON) to write')
    out = os.path.abspath(os.path.expanduser(str(out)))
    argv = converter_args(w, a, a.get('scope') or '')
    for f in [a['sva']] if isinstance(a.get('sva'), str) else a.get('sva') or []:
        argv += ['--sva', f]
    for b in [a['bind']] if isinstance(a.get('bind'), str) else a.get('bind') or []:
        argv += ['--bind', b]
    if a.get('title'):
        argv += ['--title', a['title']]
    doc = vcd2wavedrom.convert(vcd2wavedrom.options(argv))
    if out.lower().endswith('.json'):   # the WaveJSON itself (WaveDrom, mkhtml.py, embed.py)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False)
        return {'wavejson': out, 'bytes': os.path.getsize(out)}
    with tempfile.TemporaryDirectory(prefix='wavemcp-') as d:
        j = os.path.join(d, 'view.json')
        with open(j, 'w', encoding='utf-8') as f:
            json.dump(doc, f)
        cmd = [sys.executable, '-I', os.path.join(ROOT, 'tools', 'mkhtml.py'), f'view={j}', '--out', out]
        if a.get('title'):
            cmd += ['--title', a['title']]
        r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise WaveError('mkhtml: ' + r.stderr.strip()[-400:])
    return {'page': out, 'bytes': os.path.getsize(out)}


# ---------------- the views a person looks at: their edits and the live link ----------------
# view_edit runs the viewer's commands (wavefw/src/edit.js, tools/viewedit.py) on a page: live, when the page is open in a
# browser and connected (view_live), else on the page's file (the edits it carries; the viewer applies them when it is
# opened or reloaded). The live link: an HTTP server of this process on 127.0.0.1 that a page connects to (EventSource);
# it needs the token of this user (~/.cache/wavefw/live-token), which view_live writes into the page.
LIVE_PORT = 8742   # the first port tried (WAVEFW_LIVE_PORT), then the next nine
BRIDGE = []   # the one Bridge of this process, once a view tool started it


def live_token():
    """This user's token of the live link (made once, kept: a page that has it reconnects after a restart)."""
    d = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'wavefw')
    p = os.path.join(d, 'live-token')
    try:
        with open(p, encoding='utf-8') as f:
            t = f.read().strip()
        if len(t) >= 16:
            return t
    except OSError:
        pass
    os.makedirs(d, exist_ok=True)
    t = secrets.token_urlsafe(18)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(t + '\n')
    return t


class LiveHandler(http.server.BaseHTTPRequestHandler):
    """GET /events (server-sent events: the commands for the page), POST /hello (its viewers), POST /reply (the results);
    the token in every request, an Origin of a file:// page ("null") or this machine only."""
    bridge = None

    def log_message(self, *a):   # stdout is the protocol, stderr is the agent's log: quiet
        pass

    def head(self, code, ctype='application/json', length=None):
        self.send_response(code)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Type', ctype)
        if length is not None:
            self.send_header('Content-Length', str(length))
        self.end_headers()

    def answer(self, code, obj):
        body = json.dumps(obj).encode()
        self.head(code, length=len(body))
        self.wfile.write(body)

    def query(self):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

    def allowed(self):
        o = self.headers.get('Origin')
        if o not in (None, 'null') and not re.fullmatch(r'https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?', o):
            return False
        return hmac.compare_digest((self.query().get('token') or [''])[0].encode(), self.bridge.token.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == '/':
            return self.answer(200, {'wavefw': 'live'})
        if path != '/events':
            return self.answer(404, {'error': 'no such place'})
        cid = (self.query().get('cid') or [''])[0]
        if not self.allowed() or not re.fullmatch(r'[0-9a-z]{4,32}', cid):
            return self.answer(403, {'error': 'not allowed'})
        q = self.bridge.attach(cid)
        self.head(200, 'text/event-stream')
        try:
            self.wfile.write(b'retry: 2000\n\n')
            self.wfile.flush()
            while not self.bridge.closed:
                try:
                    m = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b': ping\n\n')
                    self.wfile.flush()
                    continue
                if m is None:
                    break
                self.wfile.write(('event: cmd\ndata: ' + json.dumps(m, ensure_ascii=False) + '\n\n').encode())
                self.wfile.flush()
        except OSError:   # the page went (closed, reloaded)
            pass
        finally:
            self.bridge.detach(cid, q)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        cid = (self.query().get('cid') or [''])[0]
        if not self.allowed():
            return self.answer(403, {'error': 'not allowed'})
        try:
            data = json.loads(self.rfile.read(min(int(self.headers.get('Content-Length') or 0), 64 << 20)) or b'{}')
        except ValueError:
            return self.answer(400, {'error': 'not JSON'})
        if path == '/hello':
            self.bridge.hello(cid, data)
        elif path == '/bye':   # the page leaves (closed, reloaded)
            self.bridge.drop(cid)
        elif path == '/reply':
            self.bridge.resolve(data.get('rid'), data.get('results'))
        else:
            return self.answer(404, {'error': 'no such place'})
        self.answer(200, {})


class Bridge:
    """The live link of this process: the pages connected (by their cid: path, title, viewers, a queue of commands) and
    the commands waiting for their answer."""

    def __init__(self, port=None, token=None):
        self.token, self.closed, self.clients, self.pending, self.rid = token or live_token(), False, {}, {}, 0
        self.lock, self.changed = threading.Lock(), threading.Condition()
        handler = type('Handler', (LiveHandler,), {'bridge': self})
        first = port if port is not None else int(os.environ.get('WAVEFW_LIVE_PORT') or LIVE_PORT)
        for p in [first] if port is not None else range(first, first + 10):
            try:
                self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', p), handler)
                break
            except OSError:
                continue
        else:
            raise WaveError(f'the live link: no free port from {first} on (WAVEFW_LIVE_PORT)')
        self.httpd.daemon_threads = True
        self.port, self.started = self.httpd.server_address[1], time.monotonic()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.closed = True
        for c in list(self.clients.values()):
            c['q'].put(None)
        self.httpd.shutdown()
        self.httpd.server_close()

    def attach(self, cid):
        with self.lock:
            old = self.clients.get(cid)
            if old:
                old['q'].put(None)
            self.clients[cid] = {'cid': cid, 'q': queue.Queue(), 'path': (old or {}).get('path'), 'title': (old or {}).get('title', ''),
                                 'url': (old or {}).get('url', ''), 'views': (old or {}).get('views', []), 'at': time.monotonic()}
            return self.clients[cid]['q']

    def detach(self, cid, q):
        with self.lock:
            if cid in self.clients and self.clients[cid]['q'] is q:
                del self.clients[cid]
        with self.changed:
            self.changed.notify_all()

    def drop(self, cid):
        with self.lock:
            c = self.clients.pop(cid, None)
        if c:
            c['q'].put(None)
        with self.changed:
            self.changed.notify_all()

    def hello(self, cid, data):
        with self.lock:
            c = self.clients.get(cid)
            if c:
                c.update(path=str(data.get('path') or ''), url=str(data.get('url') or ''), title=str(data.get('title') or ''),
                         views=[v for v in data.get('views') or [] if isinstance(v, dict)], at=time.monotonic())
        with self.changed:
            self.changed.notify_all()

    def pages(self):
        """The connected pages that said who they are, the latest first."""
        with self.lock:
            return sorted((dict(c) for c in self.clients.values() if c.get('path') is not None), key=lambda c: -c['at'])

    def wait(self, test, timeout):
        """Until test() is true (a page connected), at most timeout s -> its value."""
        end = time.monotonic() + timeout
        with self.changed:
            while True:
                got = test()
                left = end - time.monotonic()
                if got or left <= 0:
                    return got
                self.changed.wait(left)

    def send(self, cid, view, ops, timeout=10):
        """The commands to a page's viewer -> their results (view.run), or a WaveError (LiveGone: no answer, the page is
        taken for gone)."""
        with self.lock:
            c = self.clients.get(cid)
            if not c:
                raise WaveError('the page went (closed or reloaded): view_get lists the pages connected')
            self.rid += 1
            rid, ev = self.rid, threading.Event()
            self.pending[rid] = [ev, None]
            c['q'].put({'rid': rid, 'view': view, 'ops': ops})
        if not ev.wait(timeout):
            self.pending.pop(rid, None)
            self.drop(cid)
            raise LiveGone(f'the live page did not answer in {timeout} s (its tab closed?)')
        got = self.pending.pop(rid)[1]
        if isinstance(got, dict) and got.get('error'):
            raise WaveError(got['error'])
        return got

    def resolve(self, rid, results):
        p = self.pending.get(rid)
        if p:
            p[1] = results
            p[0].set()


class LiveGone(WaveError):
    pass


def bridge():
    if not BRIDGE:
        BRIDGE.append(Bridge())
    return BRIDGE[0]


def same_file(page_path, browser_path):
    """A page's path here and the path a browser has of it (file:///C:/…, /mnt/c/…, //wsl.localhost/<distro>/…)."""
    def norm(p):
        p = urllib.parse.unquote(str(p)).replace('\\', '/')
        m = re.match(r'^/?([a-zA-Z]):/(.*)$', p)
        if m:
            p = f'/mnt/{m.group(1).lower()}/{m.group(2)}'
        d = os.environ.get('WSL_DISTRO_NAME')
        if d and p.lower().startswith(f'/{d.lower()}/'):
            p = p[len(d) + 1:]
        return os.path.normcase(os.path.normpath(p)).lower()
    return norm(page_path) == norm(browser_path)


def page_arg(a):
    p = a.get('page')
    return os.path.abspath(os.path.expanduser(str(p))) if p else None


def live_page(a, wait=0.0):
    """The connected page the arguments name (page: its file; none: the only one) -> its client, or None."""
    if not BRIDGE:
        return None
    path = page_arg(a)
    pick = lambda: [c for c in BRIDGE[0].pages() if same_file(path, c['path'])] if path else BRIDGE[0].pages()
    got = BRIDGE[0].wait(pick, wait) if wait else pick()
    if not got:
        return None
    if not path and len({c['path'] for c in got}) > 1:
        raise WaveError('several pages are live: give "page" (' + ', '.join(sorted({os.path.basename(c['path']) for c in got})) + ')')
    return got[0]


def live_view(c, view):
    """The viewer of a live page: the one named, else the only one -> its {key, timed, …}."""
    vs = c.get('views') or []
    if view:
        v = next((v for v in vs if v.get('key') == view), None)
        if not v:
            raise WaveError(f'no view "{view}" in the live page ({", ".join(x.get("key", "") for x in vs)})')
        return v
    if len(vs) != 1:
        raise WaveError(f'the live page has {len(vs)} views: give "view" (' + ', '.join(x.get('key', '') for x in vs) + ')')
    return vs[0]


def ops_in(ops, timed):
    """The agent's commands for a viewer: a time given as a number (ns) as a text in ns for timed waves."""
    if isinstance(ops, dict):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        raise WaveError('"ops": a list of commands, each {"op": name, …} (the list is in the tool\'s description)')
    out = []
    for o in ops:
        if isinstance(o, dict) and timed:
            o = dict(o)
            for k in viewedit.TIME_ARGS.get(o.get('op'), ()):
                if isinstance(o.get(k), (int, float)) and not isinstance(o.get(k), bool):
                    o[k] = f'{o[k]}ns'
        out.append(o)
    return out


def ns_out(results, timed):
    """The results of the commands with the viewer's model times (ps) as ns: per command, the keys that are times."""
    if not timed or not isinstance(results, list):
        return results
    t = lambda v: ns(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    keys = {'cursor': ('t',), 'cursor2': ('t',), 'edge': ('t',), 'view': ('from', 'to'), 'fit': ('from', 'to')}
    out = []
    for r in results:
        if isinstance(r, dict) and 'error' not in r:
            r = dict(r)
            for k in keys.get(r.get('op'), ()):
                if k in r:
                    r[k] = t(r[k])
            if r.get('op') == 'range' and isinstance(r.get('range'), list):
                r['range'] = [t(x) for x in r['range']]
            if r.get('op') == 'state' and isinstance(r.get('state'), dict):
                r['state'] = state_ns(r['state'])
            if r.get('op') == 'cycles' and isinstance(r.get('cycles'), dict):
                r['cycles'] = dict(r['cycles'], cycleZero=t(r['cycles'].get('cycleZero')))
        out.append(r)
    return out


def state_ns(st):
    """A state's times (cursor, window, range, bookmarks, markers) as ns."""
    t = lambda v: ns(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    st = dict(st)
    for k in ('cursor', 'cursor2', 'from', 'to'):
        if k in st:
            st[k] = t(st[k])
    if isinstance(st.get('range'), dict):
        st['range'] = dict(st['range'], **{k: t(st['range'].get(k)) for k in ('from', 'to')})
    for k in ('bookmarks', 'markers'):
        if isinstance(st.get(k), list):
            st[k] = [dict(x, t=t(x.get('t'))) if isinstance(x, dict) else x for x in st[k]]
    if isinstance(st.get('config'), dict) and st['config'].get('cycleZero') is not None:
        st['config'] = dict(st['config'], cycleZero=t(st['config']['cycleZero']))
    return st


def summary(st, timed, base=None):
    """A viewer's state (a page's edits over its own, or a live viewer's) as the agent reads it: times in ns, what is
    empty or default left out."""
    ed = base or viewedit.Editor(viewedit.Model(), st)
    t = (lambda v: ns(v) if isinstance(v, (int, float)) else v) if timed else (lambda v: v)
    out, c = {}, st.get('config') or {}
    if st.get('cursor') is not None:
        out['cursor'] = t(st['cursor'])
    if st.get('from') is not None and st.get('to') is not None:
        out['window'] = [t(st['from']), t(st['to'])]
    if st.get('cursor2') is not None:
        out['cursor2'] = t(st['cursor2'])
    if st.get('range'):
        out['range'] = [t(st['range'].get('from')), t(st['range'].get('to'))] + ([st['range']['signal']] if st['range'].get('signal') else [])
    bms = viewedit.bm_list(ed.bms())
    if bms:
        out['bookmarks'] = [dict(b, t=t(b['t'])) for b in bms]
    ars = viewedit.ar_list(ed.ars())
    if ars:
        out['arrows'] = [dict(a, id=i + 1) for i, a in enumerate(ars)]
    ms = st.get('markers') or []
    if ms:
        out['markers'] = [dict(m, id=i + 1, t=t(m.get('t'))) for i, m in enumerate(ms)]
    if st.get('groups'):
        out['groups'] = st['groups']
    hl = ed.highlight()
    if hl:
        out['highlight'] = hl
    for k in ('paint', 'radix', 'analog'):
        if st.get(k):
            out[k] = st[k]
    if st.get('hidden'):
        out['hidden'] = st['hidden']
    fold = ed.fold()
    if fold:
        out['folded'] = fold
    for k in ('select', 'find'):
        if st.get(k):
            out[k] = st[k]
    if c.get('sort') not in (None, 'none'):
        out['sort'] = c['sort']
    if c.get('style') not in (None, 'auto'):
        out['style'] = c['style']
    if c.get('cycles'):
        out['cycles'] = {'clock': c.get('cycleClock'), 'zero': t(c['cycleZero']) if c.get('cycleZero') is not None else None}
    return out


def t_view_live(a):
    b = bridge()
    out = {'link': f'http://127.0.0.1:{b.port}'}
    path = page_arg(a)
    if path:
        pg = viewedit.Page(path)
        text = viewedit.put_block(pg.text, 'live', None if a.get('off') else {'port': b.port, 'token': b.token})
        if text != pg.text:
            viewedit.write_text(path, text)
        out['page'] = path
        if a.get('off'):
            out['note'] = 'the page no longer connects (reload it)'
        else:
            url = 'file://' + urllib.parse.quote(path)
            out['note'] = ('the page connects when opened or reloaded (it carries the key of this link: view_live off before you send it '
                           'to anyone)')
            if a.get('open'):
                out['opened'] = open_browser(path)
            got = live_page({'page': path}, wait=float(a.get('wait', 3 if a.get('open') else 0) or 0))
            out['url'] = url
            if not got:
                out['note'] += '; not connected yet: ask the person to open or reload it'
    out['pages'] = [{'page': c['path'], 'title': c['title'], 'views': [v.get('key') for v in c['views']]} for c in b.pages()]
    return out


def open_browser(path):
    """The page in the person's browser (WSL: the Windows one) -> whether it was handed over."""
    cands = []
    if shutil.which('wslview'):
        cands.append(['wslview', path])
    if shutil.which('explorer.exe') and shutil.which('wslpath'):
        try:
            cands.append(['explorer.exe', subprocess.run(['wslpath', '-w', path], capture_output=True, text=True, timeout=5).stdout.strip()])
        except (OSError, subprocess.SubprocessError):
            pass
    for opener in ('xdg-open', 'open'):
        if shutil.which(opener):
            cands.append([opener, path])
    for cmd in cands:
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            continue
    return False


def has_live_block(path):
    try:
        with open(path, encoding='utf-8') as f:
            return bool(viewedit.LIVE_RE.search(f.read()))
    except OSError:
        return False


def target(a):
    """Where the view tools work: ('live', client, viewer) or ('file', path, None). A page that carries the live link
    gets a moment to connect when the link has just started (with the first view tool of this server)."""
    path = page_arg(a)
    if path and not os.path.isfile(path):
        raise WaveError(f'no such page: {path}')
    linked = bool(path) and has_live_block(path)
    if linked and not BRIDGE:
        bridge()
    c = live_page(a, wait=max(0.0, 3 - (time.monotonic() - BRIDGE[0].started)) if linked else 0)
    if c:
        return 'live', c, live_view(c, a.get('view'))
    if not path:
        raise WaveError('"page" is required: the .html (wave_page, make html) — no page is live (view_live connects one)')
    return 'file', path, None


def t_view_edit(a):
    mode, where, v = target(a)
    note = ''
    if mode == 'live':
        try:
            return live_edit(a, where, v)
        except LiveGone as e:   # the tab went: the file, when there is one
            if not page_arg(a):
                raise
            where, note = page_arg(a), f' ({e})'
    pg = viewedit.Page(where)
    key = pg.view(a.get('view'))
    timed = 'time' in pg.waves[key]
    res, key, rev = viewedit.edit_page(where, ops_in(a.get('ops'), timed), key)
    out = {'page': where, 'view': key, 'results': ns_out(res, timed),
           'note': ('written into the page: the person sees it when they open or reload it' if rev else 'nothing changed') + note}
    errs = sum(1 for r in out['results'] if isinstance(r, dict) and 'error' in r)
    if errs:
        out['errors'] = errs
    return out


def live_edit(a, where, v):
    res = BRIDGE[0].send(where['cid'], v.get('key'), ops_in(a.get('ops'), v.get('timed')))
    out = {'live': where['path'], 'view': v.get('key'), 'results': ns_out(res, v.get('timed'))}
    if a.get('save'):
        st = BRIDGE[0].send(where['cid'], v.get('key'), [{'op': 'state'}])[0]['state']
        pg = viewedit.Page(where['path'] if os.path.isfile(where['path']) else page_arg(a))
        key = pg.view(v.get('key'))
        pg.put(key, {k: x for k, x in st.items() if k not in ('wavefw', 'version', 'title')})
        pg.save()
        out['saved'] = pg.path
    errs = sum(1 for r in out['results'] if isinstance(r, dict) and 'error' in r)
    if errs:
        out['errors'] = errs
    return out


def t_view_get(a):
    mode, where, v = target(a)
    if mode == 'live':
        try:
            return live_get(a, where, v)
        except LiveGone:
            if not page_arg(a):
                raise
            where = page_arg(a)
    pg = viewedit.Page(where)
    key = pg.view(a.get('view'))
    m = pg.model(key)
    ed = viewedit.Editor(m, pg.state(key))
    out = {'page': where, 'view': key, 'views': list(pg.waves), 'edits': pg.rev(key)}
    out.update((state_ns(ed.st) if m.timed else ed.st) if a.get('full') else summary(ed.st, m.timed, ed))
    if a.get('rows') is not None:
        out['rows'] = ed.c_rows({'pattern': a['rows'] or '', 'limit': a.get('limit') or 200})
    if a.get('picture'):
        out['note'] = 'a picture needs the page live (view_live)'
    return out


def live_get(a, where, v):
    ops = [{'op': 'state'}]
    if a.get('rows') is not None:
        ops.append({'op': 'rows', 'pattern': a['rows'] or '', 'limit': a.get('limit') or 200})
    res = BRIDGE[0].send(where['cid'], v.get('key'), ops)
    st = res[0]['state']
    out = {'live': where['path'], 'view': v.get('key'), 'views': [x.get('key') for x in where['views']]}
    out.update((state_ns(st) if v.get('timed') else st) if a.get('full') else summary(st, v.get('timed')))
    if a.get('rows') is not None:
        out['rows'] = {k: x for k, x in res[1].items() if k != 'op'}
    if a.get('picture'):
        pic = BRIDGE[0].send(where['cid'], v.get('key'), [{'op': 'picture', 'format': 'png'}])[0]
        if pic.get('error'):
            raise WaveError(pic['error'])
        return Image(pic['png'], out)
    return out


class Image:
    """A tool's answer with a picture (MCP image content) and its JSON."""

    def __init__(self, png, data):
        self.png, self.data = png, data


# ---------------- the tool list ----------------
# The schemas go into the agent's context on every request: short, the conventions (names, times, sampling) once in
# INSTRUCTIONS; a parameter described only where its name does not say it (tests/mcp_bench.py measures the cost).
S, N, B = {'type': 'string'}, {'type': 'integer'}, {'type': 'boolean'}
L = {'type': 'array', 'items': S}
T = {'type': ['number', 'string']}
COMMON = {'dump': S, 'signals': L, 'scope': S, 'from': T, 'to': T, 'radix': {'type': 'string', 'description': 'hex dec signed bin …'},
          'limit': N}


def tool(name, fn, desc, props, required=('dump',), ro=True):
    """readOnlyHint: a client may call the tool without asking (codex exec calls no other tool without approval)."""
    props = {k: COMMON.get(k, v) if v is None else v for k, v in props.items()}
    return {'name': name, 'fn': fn, 'description': desc,
            'inputSchema': {'type': 'object', 'properties': props, 'required': list(required)},
            'annotations': {'readOnlyHint': True} if ro else {'readOnlyHint': False, 'destructiveHint': False}}


TOOLS = [
    tool('wave_info', t_info, 'A dump at a glance: time span, signal count, scopes, clocks with period, resets.', {'dump': None}),
    tool('wave_signals', t_signals, 'Find signals -> [path, width, changes]. pattern: substring or glob (* ?); depth: levels under scope.',
         {'dump': None, 'pattern': S, 'scope': None, 'depth': N, 'active': B, 'limit': None, 'offset': N}),
    tool('wave_values', t_values, 'Values of signals at one or more times (side "before": just before the changes at that time).',
         {'dump': None, 'signals': None, 'at': {'type': ['number', 'string', 'array'], 'items': T}, 'side': S, 'scope': None, 'radix': None},
         ('dump', 'signals', 'at')),
    tool('wave_changes', t_changes, 'Value changes of signals in a window: value at "from", then [t, value], limit per signal.',
         {'dump': None, 'signals': None, 'from': None, 'to': None, 'scope': None, 'radix': None, 'limit': None}, ('dump', 'signals')),
    tool('wave_sample', t_sample, 'Table per clock cycle [cycle, t, values], sampled before the edge; only_changes (default true) '
         'drops rows equal to the one before; clock: default the nearest.',
         {'dump': None, 'signals': None, 'clock': S, 'edge': S, 'only_changes': B, 'from': None, 'to': None, 'scope': None,
          'radix': None, 'limit': None}, ('dump', 'signals')),
    tool('wave_find', t_find, 'Search -> match count and first matches. expr: SV expression or sequence per clock cycle (sva engine; '
         '"req && !ack", "req ##[1:3] ack", "$rose(x)"; names under scope). Or signal + edge (rise fall change) or value: exact times.',
         {'dump': None, 'expr': S, 'clock': S, 'signal': S, 'edge': S, 'value': T, 'from': None, 'to': None, 'scope': None, 'limit': None}),
    tool('wave_stats', t_stats, 'Aggregates over a window. Bit: rises, falls, high %, pulse widths, period. Bus: changes, distinct, '
         'longest-held values, min, max.', {'dump': None, 'signals': None, 'from': None, 'to': None, 'scope': None, 'radix': None},
         ('dump', 'signals')),
    tool('sva_check', t_sva, 'Evaluate SystemVerilog assertions (files, packages first, and/or source text) over the dump in scope -> '
         'failed with first failures [cycle, t, start_cycle, start_t, note], passed, vacuous, not_evaluated, covers.',
         {'dump': None, 'files': L, 'source': S, 'scope': None, 'assertions': L, 'from': None, 'to': None, 'max_failures': N,
          'details': B, 'defines': {'type': 'object'}}),
    tool('wave_page', t_page, 'Write a wavefw viewer page (out .html) or WaveJSON (out .json) of signals to show a person; clock '
         '(name or "auto"): a cell per cycle, auto_gap "16:2" folds idle cycles; sva files + bind ["name@scope"].',
         {'dump': None, 'signals': None, 'out': S, 'clock': S, 'from': None, 'to': None, 'scope': None, 'auto_gap': S, 'sva': L,
          'bind': L, 'title': S}, ('dump', 'signals', 'out'), ro=False),
    tool('view_edit', t_view_edit, 'Mark up a wavefw page for a person (live in their browser when connected by view_live, else in the '
         'page file: they reload it). ops in order, each {op, …}: ' + ' '.join(f'{k}({v})' for k, v in viewedit.COMMANDS.items()
                                                                                  if k not in ('state', 'set_state', 'rows', 'picture')) +
         '. t/from/to in ns; signals: path, name, path tail or * pattern; bookmark: a numbered circle with a text (no signal: on the time '
         'axis); arrow from/to: bookmark numbers; group: a folder of signals at the top; edge (live): the cursor to the next edge.',
         {'page': S, 'view': S, 'ops': {'type': 'array', 'items': {'type': 'object'}}, 'save': B}, ('ops',), ro=False),
    tool('view_get', t_view_get, 'What a page shows: bookmarks, arrows, markers, groups, highlight, colours, hidden, cursor, window (live: '
         'with the person\'s own edits). rows: list its signals (a pattern, "" all); picture: a PNG of the screen (live).',
         {'page': S, 'view': S, 'rows': S, 'limit': N, 'picture': B, 'full': B}, ()),
    tool('view_live', t_view_live, 'Connect a page to this server: it is written into the page (open or reload it), then view_edit and '
         'view_get work on it live; open: open it in the browser; off: disconnect. Without page: the pages connected.',
         {'page': S, 'open': B, 'off': B}, (), ro=False),
]
BY_NAME = {t['name']: t for t in TOOLS}


def listing():
    return [{k: v for k, v in t.items() if k != 'fn'} for t in TOOLS]


def compact(obj):
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False)


def call(name, args, images=None):
    """A tool by name -> (text, is error); a picture it gives goes to images (a list; none: left out). Everything the
    libraries print goes to stderr (stdout is the protocol)."""
    t = BY_NAME.get(name)
    if not t:
        return f'unknown tool {name}; the tools: {", ".join(BY_NAME)}', True
    NOTES.clear()
    MISSING.clear()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            got = t['fn'](args or {})
            if isinstance(got, Image):
                if images is not None:
                    images.append(got.png)
                got = got.data
            if NOTES and isinstance(got, dict):
                got['notes'] = sorted(set(NOTES))
            if MISSING and isinstance(got, dict):
                got['missing'] = MISSING[:]
            text = compact(got)
    except WaveError as e:
        return str(e), True
    except (OSError, ValueError, KeyError, TypeError) as e:
        return f'{type(e).__name__}: {e}', True
    if len(text) > MAX_TEXT:
        return (f'the answer is {len(text)} characters (more than {MAX_TEXT}): narrow the window (from / to), the signals, '
                'or lower "limit"'), True
    return text, False


# ---------------- JSON-RPC over stdio ----------------
def handle(msg):
    """One JSON-RPC message -> the response dict, or None for a notification."""
    if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0':
        return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'invalid request'}}
    mid, method, p = msg.get('id'), msg.get('method'), msg.get('params') or {}
    if mid is None:   # a notification (initialized, cancelled): nothing to answer
        return None
    ok = lambda r: {'jsonrpc': '2.0', 'id': mid, 'result': r}
    if method == 'initialize':
        want = p.get('protocolVersion')
        return ok({'protocolVersion': want if want in PROTOCOLS else PROTOCOLS[0],
                   'capabilities': {'tools': {'listChanged': False}},
                   'serverInfo': {'name': 'wavefw', 'version': version()}, 'instructions': INSTRUCTIONS})
    if method == 'ping':
        return ok({})
    if method == 'tools/list':
        return ok({'tools': listing()})
    if method == 'tools/call':
        png = []
        text, err = call(p.get('name'), p.get('arguments'), png)
        return ok({'content': [{'type': 'text', 'text': text}] + [{'type': 'image', 'data': x, 'mimeType': 'image/png'} for x in png], 'isError': err})
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': f'method not found: {method}'}}


def serve(inp=None, out=None):
    inp = inp or sys.stdin
    out = out or sys.stdout
    for line in inp:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'parse error'}}
        else:
            resp = [r for r in map(handle, msg) if r] if isinstance(msg, list) else handle(msg)
        if resp:
            out.write(compact(resp) + '\n')
            out.flush()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true', help='print the tools (name, description, input schema) and exit')
    ap.add_argument('--call', nargs=2, metavar=('TOOL', 'JSON'), help='run one tool with these arguments, print its answer and exit')
    a = ap.parse_args()
    if a.list:
        print(json.dumps(listing(), indent=1, ensure_ascii=False))
        return 0
    if a.call:
        try:
            args = json.loads(a.call[1])
        except ValueError as e:
            sys.exit(f'wavemcp: the arguments are not JSON: {e}')
        text, err = call(a.call[0], args)
        print(text)
        return 1 if err else 0
    serve()
    return 0


if __name__ == '__main__':
    sys.exit(main())
