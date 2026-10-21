#!/usr/bin/env python3
"""wavemcp.py — the wavefw tools as an MCP server (Model Context Protocol, JSON-RPC over stdio) for an AI agent.

An agent asks questions of a dump (VCD, or FST through fst2vcd) and gets short answers instead of reading the dump:
the signals, values at a time, changes in a window, a clock-sampled table, searches by an SV expression or sequence
(the sva engine), aggregates, SystemVerilog assertions checked over the dump with their first failures, and a viewer
page (or the WaveJSON) of a window for a person. The dump is read once per server (the declarations and the change counts); a
signal's transitions when a tool first needs it, then kept. Times are ns in and out (a number), or a text with a unit
("2.5us"); signal names are full paths, paths under "scope", or a unique tail of a path ("PSEL", "u_regs.PSEL").

  claude mcp add wavefw -- python3 -I /path/to/wavefw/tools/wavemcp.py      # Claude Code
  codex mcp add wavefw -- python3 -I /path/to/wavefw/tools/wavemcp.py       # Codex CLI
  wavemcp.py --list                                     # the tools and their input schemas
  wavemcp.py --call wave_info '{"dump": "out/examples/apb/apb.vcd"}'   # one tool from the shell (tests, the benchmark)

Standard library only; the sva CLI as svabuild.py finds it (--sva-bin, $WAVEFW_SVA, the build, bin/<os>/sva, PATH).
docs/USAGE.md § "AI agents (MCP)" has the tools; tests/mcp_bench.py measures what they save.
"""
import argparse, bisect, collections, contextlib, fnmatch, json, os, re, statistics, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
import dumpscan, svabuild, vcd2wavedrom  # noqa: E402
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
    '"next_offset" say how to go on). wave_page writes a viewer page to show a person.')


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
            raise WaveError(f'{os.path.basename(path)}: an FST is read through fst2vcd (GTKWave), which is not on PATH')
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
]
BY_NAME = {t['name']: t for t in TOOLS}


def listing():
    return [{k: v for k, v in t.items() if k != 'fn'} for t in TOOLS]


def compact(obj):
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False)


def call(name, args):
    """A tool by name -> (text, is error). Everything the libraries print goes to stderr (stdout is the protocol)."""
    t = BY_NAME.get(name)
    if not t:
        return f'unknown tool {name}; the tools: {", ".join(BY_NAME)}', True
    NOTES.clear()
    MISSING.clear()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            got = t['fn'](args or {})
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
        text, err = call(p.get('name'), p.get('arguments'))
        return ok({'content': [{'type': 'text', 'text': text}], 'isError': err})
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
