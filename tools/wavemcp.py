#!/usr/bin/env python3
"""wavemcp.py — the WaveLens tools as an MCP server (Model Context Protocol, JSON-RPC over stdio) for an AI agent.

An agent asks questions of a dump (VCD, or FST through fst2vcd or the sva CLI) and gets short answers instead of reading the dump:
the signals, values at a time, changes in a window, a clock-sampled table, searches by an SV expression or sequence
(the sva engine), aggregates, SystemVerilog assertions checked over the dump with their first failures, two dumps
compared change by change (wave_diff: sva diff, streamed) or a window of one cut out (wave_cut), and a viewer
page (or the WaveJSON) of a window for a person. The dump is read once per server (the declarations and the change counts); a
signal's transitions when a tool first needs it, then kept. The agent marks a page up for the person with the viewer's
commands (view_edit: bookmarks with a text, arrows, markers, expressions, groups, highlight, colours, cursor, window; tools/viewedit.py
has them) and reads what is there (view_get): live in their browser once view_live has connected the page (an HTTP
server of this process on 127.0.0.1, from port 8742 or WAVELENS_LIVE_PORT on, its key in ~/.cache/wavelens/live-token),
else in the page's file; a .vcd / .fst open in VS Code (the extension in vscode/ connects its tabs to the link that
~/.cache/wavelens/live/<port>.json announces, and opens a dump that view_live asks for) is live only. Times are ns in and out (a number), or a text with a unit as the viewer reads one
("2.5us", "100NS"); signal names are full paths, paths under "scope", or a unique tail of a path ("PSEL", "u_regs.PSEL").
Enum labels come from the dump and from the types file beside it (tb.vcd -> tb.types.json; "types", "no_types"). An
argument a tool does not take is an error; a sibling tool's name is taken for its own ("signal" for "signals", "times" for
"at", "text" for "source").
A request or an argument of a wrong shape gets an error answer and the session goes on; the programs the server starts
get /dev/null as stdin (stdin and stdout are the protocol).

  claude mcp add wavelens -- python3 -I /path/to/wavelens/tools/wavemcp.py      # Claude Code
  codex mcp add wavelens -- python3 -I /path/to/wavelens/tools/wavemcp.py       # Codex CLI
  claude mcp add wavelens -- python3 -I /path/to/wavelens/tools/wavemcp.py --lean   # the short tool list (a third fewer characters)
  wavemcp.py --list                                     # the tools and their input schemas
  wavemcp.py --call wave_info '{"dump": "out/examples/apb/apb.vcd"}'   # one tool from the shell (tests, the benchmark)

Standard library only; the sva CLI as svabuild.py finds it ($WAVELENS_SVA, the build, bin/<os>/sva, PATH).
docs/USAGE.md § "AI agents (MCP)" has the tools; tests/mcp_bench.py measures what they save.
"""
import argparse, atexit, bisect, collections, contextlib, fnmatch, hmac, http.server, json, os, queue, re, secrets, shutil, socket, statistics, subprocess, sys
import tempfile, threading, time, traceback, urllib.parse

sys.dont_write_bytecode = True   # a shared checkout stays as it is: -I ignores PYTHONDONTWRITEBYTECODE (AU-WL-003)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
import dumpscan, svabuild, svtypes, testmarks, vcd2wavedrom, viewedit, wavefind  # noqa: E402
from common import ROOT, UNIT_PS, WaveError, version  # noqa: E402
from wavelive import (BRIDGE, CID_RE, DUMP_RE, LIVE_PORT, MAX_BODY, Bridge, LiveGone, LiveHandler, bridge, cache_dir,  # noqa: E402,F401
                      has_live_block, live_page, live_token, live_view, open_browser, page_arg, same_file, target, vscode_open)

PROTOCOLS = ('2025-06-18', '2025-03-26', '2024-11-05')
MAX_TEXT = 60000   # characters of one answer: above it the agent is asked to narrow the request
CLOCK_RE = re.compile(r'clk|clock', re.I)
RESET_RE = re.compile(r'rst|reset', re.I)
INSTRUCTIONS = (
    'Waveform (VCD/FST) analysis. Times are ns (numbers) unless a unit is given ("2.5us"). Signal names: full path, '
    'path under "scope", or a unique tail ("PSEL"). Start with wave_info, then wave_signals to find names; ask for '
    'values (wave_values, wave_changes, wave_sample), search with wave_find (an SV expression or sequence on a clock, '
    'or a value / edge of one signal), count with wave_stats, check SystemVerilog assertions with sva_check, compare two runs with wave_diff. Sampled '
    'values are the ones just before the clock edge, as SVA samples; cycle numbers are the clock\'s rising edges from '
    'the start of the dump (the same as sva_check\'s). Long answers are cut at "limit" ("more", "next_from" / '
    '"next_offset" say how to go on). wave_tests says which tests of a cocotb run failed, when, and what they expected. wave_page writes a viewer page to show a person; view_edit marks it up for them '
    '(bookmarks with a text, arrows, markers, expressions, groups, highlight, colours, cursor, window), live in their browser after '
    'view_live, else in the page\'s file (they reload it); view_get reads what is there, their own edits too.')


# ---------------- times ----------------
def ps_of(v, what='time'):
    """A time from the agent: a number (ns) or a text with a unit, as the viewer reads one (viewedit.parse_time) -> ps."""
    if v is None or v == '':
        return None
    t = viewedit.parse_time(v, 1000) if isinstance(v, (str, int, float)) else None
    if t is None or not viewedit.finite(t):
        raise WaveError(f'bad {what} {json.dumps(v, ensure_ascii=False)}: a finite number of ns or a text with a unit ("250ns", "2.5us")')
    return float(t)


def ns(ps):
    """ps -> ns as a short number (integers stay integers)."""
    v = round(ps / 1000, 6)
    return int(v) if v == int(v) else v


# ---------------- one dump ----------------
class Wave(vcd2wavedrom.Builtin):
    """A dump read once: the declarations, change counts, start and end; the transitions of a signal read (one pass for
    all the missing ones) when a tool first needs them and kept. stream(), edges() are the converter's built-in reader."""

    def __init__(self, path, types=None):
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
        self.types, self.type_notes, self.typed = types, [], set()
        if types:
            self.apply_types(types)

    def apply_types(self, path):
        """The enum labels of a types file (tb.types.json beside tb.vcd: Questa's wavelens_types, svtypes.py verilator)
        onto the dump's variables, as mkconfig.py does: a path's entry of the variable's width, or an enum on a wider integer
        (Questa's int enums); the dump's own tables (an FST's) stay."""
        t = svtypes.load(path)
        sigs = [{'path': p, 'width': v.width, 'kind': v.kind, 'enum': v.enum} for p, v in self.decl.vars.items() if v.kind != 'event']
        ne, _, notes, given = svtypes.apply(t, sigs)
        for s in sigs:
            if s['path'] in given and s.get('enum') and not self.decl.vars[s['path']].enum:
                self.decl.vars[s['path']] = self.decl.vars[s['path']]._replace(enum=s['enum'])   # (a namedtuple)
                self.typed.add(s['path'])
        miss = svtypes.missing(t, list(self.decl.vars), set(getattr(self.decl, 'modules', ())) | set(getattr(self.decl, 'scopes', {})))
        self.type_notes = [f'types {os.path.basename(path)}: {n}' for n in t['notes'] + notes +
                           svtypes.fingerprint(t, getattr(self.decl, 'date', None), getattr(self.decl, 'modules', ())) + svtypes.missing_notes(t, miss)]
        self.type_notes.append(f'types {os.path.basename(path)}: labels for {len(self.typed)} signals')

    def load(self, paths):
        codes = {c for p in paths for c, _ in self.decl.vars[p].members} - self.have
        if codes:
            got = dumpscan.read(self.waves, 'collect', codes)
            self.d.trans.update(got.trans)
            self.have |= codes

    def find(self, name, scope=''):
        """A signal by its path, its path under scope, the end of a path, a [msb:lsb] or [bit] select of one (the rule of
        common.pick: vcd2wavedrom.Builtin.find) -> (path, select or None); the shallowest of several said in the answer."""
        return super().find(name, scope, NOTES.append)

    def width(self, path, sl):
        return sl[0] - sl[1] + 1 if sl else self.decl.vars[path].width

    def stream(self, path, sl=None):
        """The converter's stream with a value that did not change left out: a select of a bus changes when its bits do,
        not when the others do (and a dump that writes a value again has no change there)."""
        key = ('wavemcp', path, sl)
        if key not in self.streams:
            out = []
            for t, v in super().stream(path, sl):
                if not out or out[-1][1] != v:
                    out.append((t, v))
            self.streams[key] = out
        return self.streams[key]

    def edges(self, path, kind, t0, t1, sl=None):
        """The times of the edges (posedge negedge edge) or changes of a signal or a select of it in [t0, t1]."""
        return wavefind.edge_times(self.stream(path, sl), kind, t0, t1)

    def snap(self, t):
        """A time given (ns, rounded) -> the dump's own time when it is one (within a millionth of a step): a page of an
        answer goes on exactly where the last one stopped."""
        u = self.decl.unit_ps
        if t is None or not u:
            return t
        k = round(t / u)
        return k * u if abs(t - k * u) <= u * 1e-6 else t

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
        per net: the same id code in several scopes (one net) is listed once, at its shortest path; two clocks with edges
        alike are two."""
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
                key = tuple(self.decl.vars[p].members)   # the dump's id codes: an alias is the same net
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


def stamp(p):
    return (os.path.getmtime(p), os.path.getsize(p)) if p and os.path.isfile(p) else (None, None)


def wave(path, a=None):
    """The cached Wave of a dump (read again when the file or its types file changed). The enum labels of the types file
    beside it (tb.vcd -> tb.types.json, svtypes.beside) are applied as mkconfig.py does: "types" another file, "no_types"
    none."""
    if not path:
        raise WaveError('"dump" is required: the path of a VCD or FST')
    key = os.path.abspath(os.path.expanduser(str(path)))
    a = a or {}
    types = None if a.get('no_types') else os.path.abspath(os.path.expanduser(str(a['types']))) if a.get('types') else svtypes.beside(key)
    if types and not os.path.isfile(types):
        raise WaveError(f'"types": no such file: {types}')
    w = WAVES.get((key, types))
    if w is None or w.stamp != stamp(key) or w.tstamp != stamp(types):
        w = WAVES[(key, types)] = Wave(key, types)
        w.tstamp = stamp(types)
    return w


def window(w, a):
    t0 = w.snap(ps_of(a.get('from'), 'from'))
    t1 = w.snap(ps_of(a.get('to'), 'to'))
    t0 = w.t_start if t0 is None else t0
    t1 = w.t_end if t1 is None else t1
    if t1 < t0:
        raise WaveError(f'"to" ({ns(t1)}) is before "from" ({ns(t0)})')
    if t0 > w.t_end or t1 < w.t_start:
        raise WaveError(f'the window {ns(t0)} … {ns(t1)} ns is outside the dump ({ns(w.t_start)} … {ns(w.t_end)} ns)')
    return t0, t1


def limit(a, default, top=10000):
    n = a.get('limit', default)
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise WaveError('"limit" is a positive number')
    return min(n, top)


# ---------------- the tools ----------------
def t_info(a):
    w = wave(a.get('dump'), a)
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
    if w.types:
        out['types'] = os.path.basename(w.types)
        NOTES.extend(w.type_notes)
    return out


def t_signals(a):
    w = wave(a.get('dump'), a)
    scope = (a.get('scope') or '').rstrip('.')
    pat = (a.get('pattern') or '').strip()
    # * and ? as wildcards, [ as it is: an array element either way, q[0] / q.[0] (WL-009; review 2026-11-05 B-06)
    G = dumpscan.glued
    gp, rx = G(pat), None
    if pat and any(c in pat for c in '*?'):
        rx = re.compile(''.join('.*' if c == '*' else '.' if c == '?' else re.escape(c) for c in gp), re.I)
    items = []
    for p, v in w.decl.vars.items():
        if scope and not p.startswith(scope + '.'):
            continue
        rel = p[len(scope) + 1:] if scope else p
        if a.get('depth') is not None and rel.count('.') >= int(a['depth']):
            continue
        if rx and not (rx.fullmatch(G(p)) or rx.fullmatch(G(rel)) or rx.fullmatch(G(p).rsplit('.', 1)[-1])):
            continue
        if pat and not rx and gp.lower() not in G(p).lower():
            continue
        if a.get('active') and not w.decl.changes.get(p):
            continue
        items.append((rel, v, w.decl.changes.get(p) or 0))
    off = max(0, a.get('offset') or 0)
    n = limit(a, 200)
    page = items[off:off + n]
    extra = lambda v: ' '.join(([f'enum:{len(v.enum)}'] if v.enum else []) + ([v.kind] if v.kind not in ('wire', 'reg', 'logic') else []))
    out = {'total': len(items), 'scope': scope or None, 'columns': ['path', 'width', 'changes', 'extra'],
           'signals': [[rel, v.width, c, extra(v)] for rel, v, c in page]}
    if off + n < len(items):
        out['next_offset'] = off + n
    return out


def check_radix(radix):
    if radix is not None and radix not in viewedit.RADIX and not re.fullmatch(r's?q\d+', str(radix)):
        raise WaveError(f'"radix": {", ".join(viewedit.RADIX)} or q8 / sq15 (fixed point), not {json.dumps(radix)[:40]}')


def t_values(a):
    w = wave(a.get('dump'), a)
    scope, radix = a.get('scope') or '', a.get('radix')
    at = a.get('at')
    times = at if isinstance(at, list) else [at]
    if not times or times == [None]:
        raise WaveError('"at" is required: a time or a list of times')
    if len(times) > 200:
        raise WaveError('"at": 200 times at most (wave_sample gives a value per clock cycle)')
    check_radix(radix)
    if a.get('side') not in (None, 'before', 'after'):
        raise WaveError(f'"side": before or after, not {json.dumps(a["side"])[:40]}')
    names, res = w.signals(a.get('signals'), scope)
    before = a.get('side') == 'before'
    rows, out = [], []
    for t in times:
        tp = w.snap(ps_of(t))
        rows.append([ns(tp)] + [w.text(p, sl, w.at(w.stream(p, sl), tp, before), radix) for p, sl in res])
        if not w.t_start <= tp <= w.t_end:
            out.append(ns(tp))
    d = {'unit': 'ns', 'side': 'before' if before else 'after', 'columns': ['t'] + list(names), 'rows': rows}
    if out:
        d['notes'] = [f'{", ".join(map(str, out[:5]))}{" …" if len(out) > 5 else ""} ns: outside the dump ({ns(w.t_start)} … {ns(w.t_end)} ns): '
                      'nothing there, past its end the last value held']
    return d


def t_changes(a):
    w = wave(a.get('dump'), a)
    scope, radix = a.get('scope') or '', a.get('radix')
    check_radix(radix)
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
        if len(ch) > n:   # "from" is the value after the changes at that time: the next page from the last change given
            e['more'] = len(ch) - n
            e['next_from'] = ns(ch[n - 1][0])
        out['signals'][name] = e
    return out


def t_sample(a):
    w = wave(a.get('dump'), a)
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
    rows, prev, kept, nxt = [], None, 0, None
    for c in range(lo, hi):
        t = allt[c]
        vals = [w.text(p, sl, w.at(st, t, True), radix) for (p, sl), st in zip(res, sts)]
        if only and vals == prev:
            continue
        prev = vals
        kept += 1
        if len(rows) < n:
            rows.append([c, ns(t)] + vals)
        elif nxt is None:
            nxt = t   # the first row left out: the next page starts with it (it differs from the row before it)
    out = {'unit': 'ns', 'clock': clk, 'edge': edge, 'sampled': 'just before the edge', 'cycles': hi - lo,
           'first_cycle': lo, 'columns': ['cycle', 't'] + list(names), 'rows': rows}
    if only:
        out['only_changes'] = True
    if kept > len(rows):
        out['more'] = kept - len(rows)
        out['next_from'] = ns(nxt)
    return out


bits_value = wavefind.bits_value   # (tests, the bench)


def t_find(a):
    w = wave(a.get('dump'), a)
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
        hits = wavefind.value_times(st, want, width, t0, t1, lambda v: w.text(p, sl, v, a.get('radix')))   # the rules of a bookmark "at"
        rows = []
        for t in hits[:n]:
            j = bisect.bisect_right(st, (t, '\uffff'))
            end = st[j][0] if j < len(st) else None
            rows.append([ns(t), ns(end - t) if end is not None else None])
        out = {'unit': 'ns', 'signal': a['signal'], 'value': want, 'matches': len(hits), 'columns': ['t', 'lasts'], 'rows': rows}
    else:
        edge = wavefind.EDGES.get(a.get('edge') or 'change')
        if not edge:
            raise WaveError('"edge" is rise, fall or change')
        ts = w.edges(p, edge, t0, t1, sl)
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
        defs = a.get('defines') or {}
        for k, v in defs.items() if isinstance(defs, dict) else [(d, None) for d in defs]:   # {"X": 1} or ["X=1", "Y"]
            cmd += ['-D', f'{k}={v}' if v not in (None, '') else str(k)]
        if a.get('resolve'):
            cmd += ['--resolve', a['resolve']]
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)   # stdin is the protocol
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
    exe = svabuild.find_bin(a.get('sva_bin'))
    if not exe:
        raise WaveError('no sva CLI (make sva-build, or bin/<os>-x86_64/sva): the assertions need it')
    defs = a.get('defines') or {}
    args = [x for k, v in (defs.items() if isinstance(defs, dict) else [(d, None) for d in defs]) for x in ('-D', f'{k}={v}' if v not in (None, '') else str(k))]
    args += ['--resolve', a['resolve']] if a.get('resolve') else []
    res, msgs = wavefind.cover(exe, w.waves, expr, cname, scope, t0, t1, edge, args, w.t_start, w.t_end)   # the rules of a bookmark "at"
    hits, r, res = wavefind.cover_hits(res, msgs, scope)
    cyc = res.get('cycles') or []
    rows = [[c, ns(t)] + ([e, ns(te)] if e != c else []) for c, t, e, te in hits[:n]]
    out = {'unit': 'ns', 'expr': expr, 'clock': clk, 'scope': scope or None, 'sampled': 'just before the edge',
           'cycles': len(cyc), 'matches': r.get('stats', {}).get('matches', len(hits)),
           'columns': ['cycle', 't', 'end_cycle', 'end_t'], 'rows': rows}
    if len(hits) > n:
        out['more'] = len(hits) - n
    return out


def t_fsm(a):
    """wave_fsm: an FSM's states in a dump (tools/fsmstats.py, the rule of the page's FSM panel) -> its states, never, invalid, changes in ns."""
    import fsmstats
    w = wave(a.get('dump'), a)
    if not a.get('signal'):
        raise WaveError('"signal": the FSM\'s state signal')
    enum = None
    if a.get('enum') is not None:
        e = a['enum']
        try:
            enum = {int(k, 0) if isinstance(k, str) else int(k): str(x) for k, x in (e.items() if isinstance(e, dict) else [])}
        except ValueError:
            raise WaveError('"enum": {code: label}, the codes numbers ("0", "0x2")') from None
        if not enum:
            raise WaveError('"enum": {code: label} of its states')
    t0, t1 = window(w, a)
    p, s = fsmstats.of_dump(w, a['signal'], enum, t0, t1, a.get('scope') or '')
    t = lambda v: None if v is None else ns(v)
    for x in s['states'] + s['invalid']:
        x['first'], x['time'] = t(x['first']), t(x['time'])
    for c in s['changes']:
        c['first'] = t(c['first'])
    return {'signal': p, 'unit': 'ns', 'from': ns(t0), 'to': ns(t1), **s}


EXPLAIN_SIGS = re.compile(r'(?<![\w$.\'])([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*)')


def t_explain(a):
    """wave_explain: a moment to look at — an expression's nth match, an assertion's nth failure (assert "name@scope" with its sva files), the
    first difference of two dumps (b), or a time t — with its signals -> its window (before / after cycles of the clock; an assertion's from
    the start of the attempt), the values there (wave_sample's table), and with out a page marked there."""
    if a.get('out') and not str(a['out']).lower().endswith('.html'):
        raise WaveError(f'"out": a .html page (the window marked there), not {a["out"]}')
    w = wave(a.get('dump'), a)
    scope = a.get('scope') or ''
    kinds = [k for k in ('expr', 'assert', 'b', 't') if a.get(k) is not None]
    if len(kinds) != 1:
        raise WaveError('one of "expr" (its match), "assert" (its failure), "b" (the first difference with that dump) or "t" (a time)' +
                        (f', not {" and ".join(kinds)}' if kinds else ''))
    kind, nth = kinds[0], a.get('nth') or 1
    if not (isinstance(nth, int) and nth >= 1):
        raise WaveError('"nth": 1, 2 …')
    sigs, why = list(a.get('signals') or []) if not isinstance(a.get('signals'), str) else [x for x in re.split(r'[,\s]+', a['signals']) if x], {}
    if kind == 'expr':
        r = find_expr(w, {**a, 'limit': nth}, scope, w.t_start, w.t_end, nth)
        if len(r['rows']) < nth:
            raise WaveError(f'"{r["expr"]}" matches {r["matches"]} time{"s" if r["matches"] != 1 else ""} in the dump: no match {nth}')
        at, why = r['rows'][nth - 1][1], {'expr': r['expr'], 'match': nth, 'matches': r['matches'], 'clock': r['clock']}
        scope = scope or r.get('scope') or ''
        if not sigs:
            for n in EXPLAIN_SIGS.findall(re.sub(r'\$\w+|\d+\'[sS]?[bBhHdDoO][0-9a-fA-FxXzZ_]+', ' ', r['expr'])):
                try:
                    w.find(n, scope)
                    sigs.append(n)
                except WaveError:
                    pass
    elif kind == 'assert':   # its nth failed attempt (sva_check): from its start to where it failed
        name, _, sc = str(a['assert']).partition('@')
        sc = sc or scope
        files = a.get('sva') or a.get('files')
        if not files:
            raise WaveError('"assert" needs "sva": its assertion files (packages first)')
        r = t_sva({'dump': a.get('dump'), 'types': a.get('types'), 'no_types': a.get('no_types'), 'files': files, 'scope': sc, 'assertions': [name],
                   'max_failures': nth, 'sva_bin': a.get('sva_bin')})
        x = next((f for f in r.get('failed') or [] if f.get('name') == name), None)
        if x is None or len(x.get('failures') or []) < nth:
            raise WaveError(f'{name}@{sc}: no failure {nth}' + (f' (it fails {x["stats"]["fail"]} times)' if x else ' (it does not fail here)'))
        cyc, at, c0, t_start, note = x['failures'][nth - 1][:5]
        why = {'assert': name, 'scope': sc, 'failure': nth, 'failures': x['stats'].get('fail'), 'start': t_start, 'note': note,
               'text': x.get('text'), 'clock': r.get('clock')}
        scope = sc
        if not sigs:
            for n in EXPLAIN_SIGS.findall(re.sub(r'\$\w+|\d+\'[sS]?[bBhHdDoO][0-9a-fA-FxXzZ_]+', ' ', x.get('text') or '')):
                try:
                    w.find(n, scope)
                    sigs.append(n)
                except WaveError:
                    pass
    elif kind == 'b':
        d = t_diff({('a' if k == 'dump' else k): a[k] for k in ('dump', 'b', 'map', 'offset', 'scope', 'sva_bin') if a.get(k) is not None})
        if d.get('first') is None:
            raise WaveError('the two dumps do not differ: nothing to explain')
        at = d['first']['t']
        why = {'first': d['first'], 'rank': d.get('rank', [])}
        sigs = sigs or [x['signal'] for x in d.get('rank', [])][:8] or [d['first']['signal']]
    else:
        at = ns(ps_of(a['t'], 't'))
        if not sigs:
            raise WaveError('"t" needs "signals": the ones to look at')
    if not sigs:
        raise WaveError('no signals found to look at: give "signals"')
    names, res = w.signals(sigs, scope)
    clk = w.clock_for(a.get('clock') or why.get('clock'), scope, [p for p, _ in res])
    rises = w.edges(clk, 'posedge', float('-inf'), float('inf'))
    t_at = ps_of(at, 't')
    i = bisect.bisect_left(rises, t_at)
    before, after = a.get('before', 2), a.get('after', 2 if kind != 'expr' else 4)
    for k, v in (('before', before), ('after', after)):
        if not (isinstance(v, int) and v >= 0):
            raise WaveError(f'"{k}": a number of cycles')
    if kind == 'assert':   # the attempt's start: the window opens before it
        i = bisect.bisect_left(rises, ps_of(why['start'], 'start'))
    i0 = i if i < len(rises) and rises[i] == (ps_of(why['start'], 'start') if kind == 'assert' else t_at) else i - 1   # the last edge at or before it
    lo = rises[max(0, i0 - before)] if rises else w.t_start
    if kind == 'assert':
        i = bisect.bisect_left(rises, t_at)
    hi = rises[i + after] if i + after < len(rises) else w.t_end
    table = t_sample({'dump': a.get('dump'), 'types': a.get('types'), 'no_types': a.get('no_types'), 'signals': names, 'scope': scope, 'clock': clk,
                      'from': f'{lo}ps', 'to': f'{hi}ps', 'limit': a.get('limit') or 40})
    out = {'kind': {'expr': 'match', 'assert': 'assertion', 'b': 'difference', 't': 'time'}[kind], 'at': at, 'unit': 'ns', 'window': {'from': ns(lo), 'to': ns(hi)},
           'clock': clk, 'signals': names, **why, 'table': table}
    if kind == 'b':   # the other run's values in the same window, its clock's cycles (the same names after map)
        bmap = {x: y for x, y in (a.get('map') or {}).items()}
        out['table_b'] = t_sample({'dump': a['b'], 'types': a.get('types'), 'no_types': a.get('no_types'), 'clock': bmap.get(clk, clk),
                                   'signals': [bmap.get(n, n) for n in names], 'scope': scope, 'from': f'{lo}ps', 'to': f'{hi}ps',
                                   'limit': a.get('limit') or 40})
    if a.get('out'):
        page = t_page({'dump': a.get('dump'), 'types': a.get('types'), 'no_types': a.get('no_types'), 'signals': names, 'scope': scope,
                       'from': f'{lo}ps', 'to': f'{hi}ps', 'out': a['out'], 'title': a.get('title') or f'{out["kind"]} at {at} ns'})
        label = {'expr': f'match {nth}', 'assert': f'{why.get("assert")} fails', 'b': 'first difference', 't': 'here'}[kind]
        viewedit.edit_page(page['page'], [{'op': 'marker', 't': f'{at}ns', 'label': label, 'color': '#e03131'}, {'op': 'cursor', 't': f'{at}ns'}])
        out['page'] = page['page']
    return out


def t_stats(a):
    w = wave(a.get('dump'), a)
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
            rises = w.edges(p, 'posedge', t0, t1, sl)
            falls = w.edges(p, 'negedge', t0, t1, sl)
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
                wd = w.width(p, sl)
                hx = lambda n: format(n, 'x').rjust((wd + 3) // 4, '0')
                key = {n: vcd2wavedrom.order_key(n, wd, radix) for n in nums}   # by the number the radix reads (signed: 80 is -128)
                nums = [n for n in nums if key[n] is not None]
                if nums:
                    e['min'], e['max'] = w.text(p, sl, hx(min(nums, key=key.get)), radix), w.text(p, sl, hx(max(nums, key=key.get)), radix)
        out['signals'][name] = e
    return out


def t_sva(a):
    w = wave(a.get('dump'), a)
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
    mf = max(0, a.get('max_failures') if a.get('max_failures') is not None else 3)
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
    for p, sl in res:   # the labels of the types file (the converter reads the dump's own tables itself)
        e = w.decl.vars[p].enum if p in w.typed and not sl else None
        if e and not any(c in str(x) for x in e.values() for c in ',:='):
            argv += ['--enum', f'{p}=' + ','.join(f'{k}:{x}' for k, x in e.items())]
    clk = a.get('clock')
    if clk is True or clk == 'auto':
        clk = w.clock_for(None, scope, [p for p, _ in res])
    elif clk:
        clk = w.clock_for(clk, scope)
    argv += ['--clock', clk] if clk else ['--exact']
    t0, t1 = window(w, a)
    t0, t1 = max(t0, w.t_start), min(t1, w.t_end)   # a window past the dump's ends: the dump's
    argv += [f'--from={ns(t0)}ns', f'--to={ns(t1)}ns']   # with "=": a time below 0 is not an option
    if a.get('auto_gap') and clk:
        argv += ['--auto-gap', str(a['auto_gap'])]
    if a.get('hierarchy'):
        argv += ['--hierarchy']
    return argv


def marks_file(a):
    p = os.path.abspath(os.path.expanduser(str(a.get('marks') or '')))
    if not a.get('marks') or not os.path.isfile(p):
        raise WaveError(f'"marks": no such file {a.get("marks")!r} (what a cocotb test with wavelens_cocotb leaves: WAVELENS_MARKS, default wavelens.marks.json)')
    return p


MARKS_MAX = 64 << 20   # a .json of a directory read to know a marks file: larger ones are skipped (and named)


def marks_files(d):
    """The marks files under a directory (any depth, in name order) -> [(path, its JSON)], the notes on the .json files skipped. A file is one
    by what it holds ("wavelens": "marks"), wherever its keys are (B-14: a file written with sorted keys was skipped by its first bytes)."""
    out, skipped = [], {}
    for root, dirs, files in os.walk(d):
        dirs[:] = sorted(x for x in dirs if not x.startswith('.'))
        for f in sorted(files):
            if not f.endswith('.json'):
                continue
            p = os.path.join(root, f)
            why = None
            try:
                if os.path.getsize(p) > MARKS_MAX:
                    why = f'over {MARKS_MAX >> 20} MB'
                else:
                    with open(p, encoding='utf-8-sig') as fh:   # a BOM: as testmarks.load (B-27)
                        doc = json.load(fh)
            except OSError as e:
                why = e.strerror or 'not readable'
            except ValueError:   # (a UnicodeDecodeError too)
                why = 'not JSON'
            if why is None and not (isinstance(doc, dict) and doc.get('wavelens') == 'marks'):
                why = 'no marks file'
            if why:
                skipped.setdefault(why, []).append(os.path.relpath(p, d))
            else:
                out.append((p, doc))
    notes = [f'skipped, {why}: {", ".join(names[:20])}' + (f' and {len(names) - 20} more' if len(names) > 20 else '') for why, names in skipped.items()]
    return out, notes


def regression(a, d):
    """wave_tests of a directory: every marks file under it as one answer: the totals, the failures first (file, test, message, where), each
    file's line, the failed ones first."""
    if a.get('test') is not None or a.get('steps'):
        raise WaveError('"test" / "steps" are of one marks file; "marks" is a directory here (its failures: the "failures" of this answer)')
    found, notes = marks_files(d)
    if not found:
        raise WaveError(f'"marks": no marks file under {d} (a .json with "wavelens": "marks", what wavelens_cocotb writes)'
                        + (f'; {"; ".join(notes)}' if notes else ''))
    files, fails, tot = [], [], dict.fromkeys(('tests', 'pass', 'fail', 'xfail', 'run', 'checks', 'failed_checks'), 0)
    for p, doc in found:
        try:
            testmarks.check(doc, p)
        except WaveError as e:
            notes.append(str(e))
            continue
        rel, tests = os.path.relpath(p, d), doc.get('tests') or []
        bad = [t for t in tests if t['result'] in ('fail', 'run')]
        for t in tests:
            n, b = testmarks.checks_of(t)
            tot['tests'] += 1
            tot[t['result']] = tot.get(t['result'], 0) + 1
            tot['checks'] += n
            tot['failed_checks'] += b
        fails += [{'file': rel, 'n': t['n'], 'name': t['name'], 'result': t['result'], 'from': ns(t['from']),
                   **{k: t[k] for k in ('message', 'where') if t.get(k)}} for t in bad]
        files.append({'file': rel, 'summary': testmarks.summary(doc), 'tests': len(tests), 'failed': len(bad)})
    files.sort(key=lambda f: (-f['failed'], f['file']))
    limit = a.get('limit') or 50
    out = {'dir': d, 'files': len(files), 'totals': tot,
           'summary': f'{len(files)} file{"s" * (len(files) != 1)}, {tot["tests"]} tests: {tot["pass"]} passed, {tot["fail"]} failed'
                      + (f', {tot["xfail"]} failed as expected' if tot['xfail'] else '') + (f', {tot["run"]} not finished' if tot['run'] else ''),
           'failures': fails[:limit], 'runs': files}
    if len(fails) > limit:
        out['more_failures'] = len(fails) - limit
    if notes:
        out['notes'] = notes
    return out


def t_tests(a):
    """The tests of a cocotb run, from its marks file: what ran when and how it ended; `test`: one, with its phases and marks; a directory: every
    marks file under it (regression)."""
    d = os.path.abspath(os.path.expanduser(str(a.get('marks') or '')))
    if a.get('marks') and os.path.isdir(d):
        return regression(a, d)
    if a.get('steps') and a.get('test') is None:
        raise WaveError('"steps": of one test: give "test" (a number or a name); every test\'s slowest steps: "slowest" in the summary')
    doc = testmarks.load(marks_file(a))
    tests = doc.get('tests') or []
    def row(t):
        n, bad = testmarks.checks_of(t)
        out = {'n': t['n'], 'name': t['name'], 'result': t['result'], 'from': ns(t['from']), 'to': None if t['to'] is None else ns(t['to']), 'checks': n, 'failed_checks': bad}
        k, off = testmarks.measures(t)
        if k:
            out.update(measures=[measure(m) for m in t['measures']], measures_failed=off)
        return {**out, **{k: t[k] for k in ('doc', 'message', 'where') if t.get(k)}}
    def measure(m):   # ns; the bound as the test wrote it; ok: null for a bound in cycles (the page counts them)
        dt = None if m.get('to') is None else ns(m['to'] - m['from'])
        return {'label': m['label'], 'from': ns(m['from']), 'to': None if m.get('to') is None else ns(m['to']), 'dt': dt,
                **{k: m[k] for k in ('min', 'max', 'signal') if m.get(k) is not None}, 'ok': m.get('ok')}
    step = lambda p, t=None: {**({'test': t['name']} if t else {}), 'step': p['label'], 'from': ns(p['from']), 'to': ns(p['to']), 'dt': ns(p['dt'])}
    every = [m for t in tests for m in t.get('measures') or []]
    head = {'summary': testmarks.summary(doc), 'signal': doc.get('signal'), 'step': doc.get('step')}
    if every:
        head.update(measures=len(every), measures_failed=sum(m.get('ok') is False for m in every))
    slow = sorted(((p, t) for t in tests for p in testmarks.steps(t)), key=lambda x: -x[0]['dt'])[:5]
    if slow:
        head['slowest'] = [step(p, t) for p, t in slow]
    if a.get('test') is None:
        return {**head, 'tests': [row(t) for t in tests]}
    t = next((t for t in tests if a['test'] in (t['n'], t['name'], str(t['n']))), None)
    if t is None:
        raise WaveError(f'"test": no test {a["test"]!r} (have: {", ".join(t["name"] for t in tests)})')
    st = testmarks.steps(t)
    took = {'steps': [step(p) for p in st], 'total': ns(sum(p['dt'] for p in st)), 'longest': st[0]['label']} if st else {'steps': []}
    if a.get('steps'):   # the steps' table alone
        return {'test': {'n': t['n'], 'name': t['name'], **took}}
    limit = a.get('limit') or 50
    marks = [{**m, 't': ns(m['t']), **({'from': ns(m['from'])} if m.get('from') is not None else {})} for m in t.get('marks') or []]   # (wl.checks: its first)
    phases = [{**p, 'from': ns(p['from']), 'to': ns(p['to'])} for p in t.get('phases') or []]
    return {**head, 'test': {**row(t), **{k: t[k] for k in ('text', 'signals') if t.get(k)}, 'phases': phases, **took, 'marks': marks[:limit],
                             **({'more': len(marks) - limit} if len(marks) > limit else {})}}


def marks_page(a, argv, out):
    """wave_page with the marks of a cocotb run: a config of one view through mkhtml.py, which puts the tests on it."""
    for k in ('compare', 'auto_gap'):
        if a.get(k):
            raise WaveError(f'"{k}" does not go with "marks": a page with marks has the view mkhtml.py makes of them')
    if out.lower().endswith('.json'):
        raise WaveError('"marks" makes a page: "out" is an .html')
    opt = vcd2wavedrom.parser().parse_args(argv)
    paths = [x for chunk in opt.signals for x in chunk.split(',')]
    view = {'signals': [f'{p}={vcd2wavedrom.svabuild.split_path(p)[-1]}' if '[' not in p else p for p in paths], 'title': a.get('title') or 'The whole run', **({'clock': opt.clock} if opt.clock else {'exact': True})}
    view.update({k: f'{ps_of(a[k], k)}ps' for k in ('from', 'to') if a.get(k) is not None})   # (else the marks' own: past the last test)
    cfg = {'waves': opt.waves, 'views': {'view': view}}
    enum = {}
    for e in opt.enum or []:
        p, _, body = e.partition('=')
        enum[p] = dict(x.split(':', 1) for x in body.split(','))
    if enum:
        cfg['enum'] = enum
    for key, name in (('sva', 'sva'), ('bind', 'bind')):
        if a.get(name):
            cfg[key] = [a[name]] if isinstance(a[name], str) else a[name]
    with tempfile.TemporaryDirectory(prefix='wavemcp-') as d:
        c = os.path.join(d, 'page.config.json')
        with open(c, 'w', encoding='utf-8') as f:
            json.dump(cfg, f)
        cmd = [sys.executable, '-I', os.path.join(ROOT, 'tools', 'mkhtml.py'), '--config', c, '--marks', marks_file(a), '--out', out]
        if a.get('marks_views'):
            cmd += ['--marks-views', str(a['marks_views'])]
        if a.get('title'):
            cmd += ['--title', a['title']]
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise WaveError('mkhtml: ' + r.stderr.strip()[-400:])
    notes = [x.split('lint: ', 1)[1] for x in r.stderr.splitlines() if 'lint: ' in x and 'bookmarks-close' not in x]
    return {'page': out, 'bytes': os.path.getsize(out), 'summary': testmarks.summary(testmarks.load(marks_file(a))), **({'notes': notes} if notes else {})}


def t_page(a):
    w = wave(a.get('dump'), a)
    out = a.get('out')
    if not out:
        raise WaveError('"out" is required: the HTML page (or .json: the WaveJSON) to write')
    out = os.path.abspath(os.path.expanduser(str(out)))
    if not os.path.isdir(os.path.dirname(out)):
        raise WaveError(f'"out": no such directory {os.path.dirname(out)}')
    argv = converter_args(w, a, a.get('scope') or '')
    if a.get('marks'):
        return marks_page(a, argv, out)
    for f in [a['sva']] if isinstance(a.get('sva'), str) else a.get('sva') or []:
        argv += ['--sva', f]
    for b in [a['bind']] if isinstance(a.get('bind'), str) else a.get('bind') or []:
        argv += ['--bind', b]
    if a.get('title'):
        argv += ['--title', a['title']]
    try:
        o = vcd2wavedrom.options(argv)
        c = a.get('compare')   # the config's "compare": sva diff with that dump, the page opens with its bands
        if c is not None:
            c = {'dump': c} if isinstance(c, str) else c
            if not isinstance(c, dict) or not c.get('dump'):
                raise WaveError('"compare": a dump ("b.vcd"), or {"dump", "map"?, "offset"?, "segment"?, "align"?}')
            o.compare = dict(c, dump=os.path.abspath(os.path.expanduser(str(c['dump']))))
        doc = vcd2wavedrom.convert(o)
    except SystemExit as e:   # argparse of the converter in this process: its message is on stderr, the server goes on
        raise WaveError(f'the converter refused its arguments ({e.code}): {" ".join(argv[2:])}') from None
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
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise WaveError('mkhtml: ' + r.stderr.strip()[-400:])
    return {'page': out, 'bytes': os.path.getsize(out)}


# ---------------- the views a person looks at: their edits and the live link ----------------
# view_edit runs the viewer's commands (wavelens/src/edit.js, tools/viewedit.py) on a page: live, when the page is open in a
# browser and connected (view_live), else on the page's file (the edits it carries; the viewer applies them when it is
# opened or reloaded). The live link: an HTTP server of this process on 127.0.0.1 that a page connects to (EventSource);
# it needs the token of this user (~/.cache/wavelens/live-token), which view_live writes into the page; it is
# tools/wavelive.py (Bridge, LiveHandler, target …: imported above under the names it had here).


def ops_in(ops, timed):
    """The agent's commands for a viewer: a time given as a number (ns) as a text in ns for timed waves; the times of a
    state given back (set_state: what view_get full gave, in ns) in the viewer's ps."""
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
            if o.get('op') == 'set_state' and isinstance(o.get('state'), dict):
                o['state'] = state_ps(o['state'])
        out.append(o)
    return out


EXPR_TIMES = ('time', 'first', 'last', 'min', 'max')   # what the expr commands give in the viewer's times


def ns_out(results, timed):
    """The results of the commands with the viewer's model times (ps) as ns: per command, the keys that are times."""
    if not timed or not isinstance(results, list):
        return results
    t = lambda v: ns(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    keys = {'cursor': ('t',), 'cursor2': ('t',), 'edge': ('t',), 'view': ('from', 'to'), 'fit': ('from', 'to'), 'expr_go': ('t',),
            'expr': EXPR_TIMES, 'expr_matches': EXPR_TIMES, 'bookmark': ('t', 'from'), 'fsm_go': ('t',), 'compare': ('first',),
            'goto': ('t',)}   # (review 2026-11-05 B-12)
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
            if r.get('op') == 'bus_list' and isinstance(r.get('transactions'), list):
                r['transactions'] = [dict(x, t0=t(x.get('t0')), t1=t(x.get('t1'))) for x in r['transactions']]
            if r.get('op') == 'measures' and isinstance(r.get('measures'), list):
                r['measures'] = measures_out(r['measures'], t)
            if r.get('op') == 'expr_markers':
                for k in ('from', 'to'):
                    if k in r:
                        r[k] = t(r[k])
            if r.get('op') == 'deltas' and isinstance(r.get('deltas'), list):
                r['deltas'] = [dict(x, dt=t(x.get('dt'))) if isinstance(x, dict) else x for x in r['deltas']]
            if r.get('op') == 'cycles' and isinstance(r.get('cycles'), dict):
                r['cycles'] = dict(r['cycles'], cycleZero=t(r['cycles'].get('cycleZero')))
            if r.get('op') == 'expr_matches':
                if isinstance(r.get('matches'), list):
                    r['matches'] = [[t(a), t(b)] for a, b in r['matches']]
                if isinstance(r.get('exprs'), list):
                    r['exprs'] = [{k: t(v) if k in EXPR_TIMES else v for k, v in x.items()} for x in r['exprs']]
            if r.get('op') in ('gaps', 'expr') and isinstance(r.get('cut'), dict):
                r['cut'] = cut_ns(r['cut'], t)
            if r.get('op') == 'fsm_stats':
                for k, ts in (('states', ('first', 'time')), ('invalid', ('first', 'time')), ('changes', ('first',))):
                    if isinstance(r.get(k), list):
                        r[k] = [{f: t(v) if f in ts else v for f, v in x.items()} for x in r[k]]
        out.append(r)
    return out


def cut_ns(cut, t):
    """What the gaps on the waves leave (the gaps command's cut) with its times through t."""
    return dict(cut, kept=t(cut.get('kept')), total=t(cut.get('total')), parts=[[t(p), t(q)] for p, q in cut.get('parts') or []])


def state_conv(st, f):
    """A state with f applied to each of its times (cursor, cursor2, window, range, bookmarks, markers, the cycles' zero)
    that is there and not null."""
    t = lambda v: v if v is None or isinstance(v, bool) else f(v)
    st = dict(st)
    for k in ('cursor', 'cursor2', 'from', 'to'):
        if k in st:
            st[k] = t(st[k])
    if isinstance(st.get('range'), dict):
        st['range'] = dict(st['range'], **{k: t(st['range'][k]) for k in ('from', 'to') if k in st['range']})
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)   # a span's end may be {"bookmark": n}, a bound {"cycles": n}
    for k in ('bookmarks', 'markers'):
        if isinstance(st.get(k), list):
            st[k] = [dict(x, t=t(x['t']), **{b: t(x[b]) for b in ('dmin', 'dmax') if num(x.get(b))}) if isinstance(x, dict) and 't' in x else x
                     for x in st[k]]
    if isinstance(st.get('spans'), list):
        st['spans'] = [dict(x, **{e: t(x[e]) for e in ('from', 'to') if num(x.get(e))}) if isinstance(x, dict) else x for x in st['spans']]
    if isinstance(st.get('config'), dict) and st['config'].get('cycleZero') is not None:
        st['config'] = dict(st['config'], cycleZero=t(st['config']['cycleZero']))
    return st


def state_ns(st):
    """A state's times as ns (view_get, the state command); a compare's cut of the second dump left out, its size said."""
    st = state_conv(st, lambda v: ns(v) if isinstance(v, (int, float)) else v)
    c = st.get('compare')
    if isinstance(c, dict) and isinstance(c.get('vcd'), str):
        st = dict(st, compare={**{k: x for k, x in c.items() if k != 'vcd'}, 'vcd_bytes': len(c['vcd'])})
    return st


def state_ps(st):
    """A state from the agent (set_state), its times ns or a text with a unit -> the viewer's ps (a text it cannot read: as it is)."""
    def ps(v):
        try:
            return round(ps_of(v), 3) if isinstance(v, (int, float, str)) else v
        except WaveError:
            return v
    return state_conv(st, ps)


def measures_out(rows, t):
    """The measurements (viewedit.measure_list, the measures command) with their times through t."""
    tb = lambda b: t(b) if isinstance(b, (int, float)) and not isinstance(b, bool) else b
    return [dict(r, **{'from': dict(r['from'], t=t(r['from']['t'])), 'to': dict(r['to'], t=t(r['to']['t'])), 'dt': t(r['dt'])},
                 **{k: tb(r[k]) for k in ('dmin', 'dmax') if k in r}) for r in rows]


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
    tb = lambda b: t(b) if isinstance(b, (int, float)) and not isinstance(b, bool) else b   # a bound: a time, or {"cycles": n}
    if ms:
        out['markers'] = [dict(m, id=i + 1, t=t(m.get('t')), **{k: tb(m[k]) for k in ('dmin', 'dmax') if k in m}) for i, m in enumerate(ms)]
    mk = ed.marks()   # the state's markers, else the page's own (its "measures": a cocotb test's wl.measure pairs)
    if mk and 'markers' not in st:
        out['markers'] = [dict({k: v for k, v in m.items() if v is not None and v is not False}, id=i + 1, t=t(m['t']), page=True,
                               **{k: tb(m[k]) for k in ('dmin', 'dmax') if m.get(k) is not None}) for i, m in enumerate(mk)]
    me = measures_out(viewedit.measure_list(mk), t)
    if me:
        out['measures'] = me
    ss = viewedit.span_list(ed.spans())
    if ss:
        out['spans'] = [dict(x, id=i + 1, **{'from': t(x['from']), 'to': t(x['to'])}) for i, x in enumerate(ss)]
    xs = ed.exprs()
    if xs:
        out['exprs'] = [dict({'expr': e} if isinstance(e, str) else e, id=i + 1) for i, e in enumerate(map(viewedit.expr_json, xs))]
    if st.get('groups'):
        out['groups'] = st['groups']
    hl = ed.highlight()
    if hl:
        out['highlight'] = hl
    for k in ('paint', 'radix', 'analog'):
        if st.get(k):
            out[k] = st[k]
    for k in ('hidden', 'dups', 'deltas', 'bits'):
        if st.get(k):
            out[k] = st[k]
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
    g = ed.gap_opt()
    if g['gaps']:   # with the gaps command's names; view: on the waves
        out['gaps'] = {'idle': g['gapIdle'], 'keep': g['gapKeep'], 'view': g['gapView'], **{n: g[k] for n, k in (('signals', 'gapSignals'), ('clock', 'gapClock'),
                       ('aux', 'gapAux'), ('only', 'gapOnly'), ('by', 'gapBy')) if g.get(k)}}
    cmp = st['compare'] if 'compare' in st else ed.compare() if ed.m.doc else None
    if isinstance(cmp, dict):
        s = viewedit.compare_summary(cmp)
        out['compare'] = dict(s, first=t(s['first']) if s['first'] is not None else None, show=st.get('compareShow') or cmp.get('show') or 'a')
    return out


def t_view_live(a):
    b = bridge()
    if a.get('rotate'):
        b.token = live_token(new=True)
    out = {'link': f'http://127.0.0.1:{b.port}'}
    path = page_arg(a)
    if path and DUMP_RE.search(path):
        if not os.path.isfile(path):
            raise WaveError(f'no such dump: {path}')
        out['page'] = path
        if a.get('off'):
            out['note'] = 'a dump in VS Code: close its tab, or turn the setting wavelens.live off there'
        else:
            if a.get('open'):
                out['opened'] = vscode_open(path, b.port)
            wait = a.get('wait', 10 if a.get('open') else max(0.0, 5 - (time.monotonic() - b.started)))
            wait = min(max(float(wait), 0.0), 30.0) if viewedit.finite(wait) else 0.0
            got = live_page({'page': path}, wait=wait)
            out['note'] = ('its tab in VS Code is connected' if got else
                           'not connected: the person opens it in VS Code with the WaveLens extension (open: true asks VS Code to)')
    elif path:
        pg = viewedit.Page(path)
        text = viewedit.put_block(pg.text, 'live', None if a.get('off') else {'port': b.port, 'token': b.token})
        if text != pg.text:
            viewedit.write_text(path, text)
        out['page'] = path
        if a.get('off'):
            out['note'] = 'the page no longer connects (reload it); a copy made while it carried the key still has it: rotate makes a new one'
        else:
            url = 'file://' + urllib.parse.quote(path)
            out['note'] = ('the page connects when opened or reloaded (it carries the key of this link: view_live off before you send it '
                           'to anyone)')
            if a.get('open'):
                out['opened'] = open_browser(path)
            wait = a.get('wait', 3 if a.get('open') else 0)
            wait = min(max(float(wait), 0.0), 30.0) if viewedit.finite(wait) else 0.0
            got = live_page({'page': path}, wait=wait)
            out['url'] = url
            if not got:
                out['note'] += '; not connected yet: ask the person to open or reload it'
    out['pages'] = [{'page': c['path'], 'title': c['title'], 'views': [v.get('key') for v in c['views']]} for c in b.pages()]
    return out


def t_to_fst(a):
    """sva fst: the VCD as an FST beside it (tb.vcd -> tb.fst) or at "out", the FSM states of its types file in it."""
    src = os.path.abspath(os.path.expanduser(str(a.get('dump') or '')))
    if not os.path.isfile(src):
        raise WaveError(f'no such file: {src}')
    exe = svabuild.find_bin(a.get('sva_bin'))
    if not exe:
        raise WaveError('no sva CLI (make sva-build, or bin/<os>-x86_64/sva): the conversion needs it')
    cmd = [exe, 'fst', src]
    if a.get('out'):
        cmd += ['--out', os.path.abspath(os.path.expanduser(str(a['out'])))]
    if a.get('types'):
        cmd += ['--types', os.path.abspath(os.path.expanduser(str(a['types'])))]
    if a.get('no_types'):
        cmd.append('--no-types')
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)   # stdin is the protocol
    notes = fst_notes(r.stderr)
    if r.returncode:
        raise WaveError('; '.join(notes) or f'sva fst: exit {r.returncode}')
    # the FST as the CLI names it (out, else the dump with .fst): its last line is "<that>: N variables …"
    fst = cmd[cmd.index('--out') + 1] if '--out' in cmd else os.path.splitext(src)[0] + '.fst'
    said = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ''
    out = {'fst': fst, 'written': said[len(fst) + 2:] if said.startswith(fst + ': ') else said,
           'bytes': os.path.getsize(fst) if os.path.isfile(fst) else None}
    if notes:
        out['notes'] = notes
    return out


PROGRESS = ': progress: '   # the CLI's lines of how far it is, all of one function (main.rs progress): "sva: <what>: progress: <how far>"


def fst_notes(err):
    """The CLI's notes on stderr, without "sva: "; its lines of progress (PROGRESS: `sva fst`'s "tb.vcd: progress: 40% (line …)",
    `sva diff`'s "a.vcd ~ b.fst: progress: 3/10 (…)"; test_wavemcp pins both as the CLI writes them) are not notes."""
    return [l.removeprefix('sva: ') for l in err.splitlines() if l.strip() and not (l.startswith('sva: ') and PROGRESS in l)]


def cli_json(out):
    """The JSON the CLI wrote on stdout. Where sva cannot put fd 1 aside (Windows: main.rs stdout_aside) wellen's warnings
    ("WARN: time decreased …") stand before it: the text from the first line that opens a JSON value on (svabuild.compare)."""
    m = re.search(r'^[{\[]', out, re.M)
    return json.loads(out[m.start():] if m else out)


def dump_path(a, key='dump'):
    p = os.path.abspath(os.path.expanduser(str(a.get(key) or '')))
    if not os.path.isfile(p):
        raise WaveError(f'no such file: {p}' + (f' ("{key}")' if key != 'dump' else ''))
    return p


def sva_exe(a, what):
    exe = svabuild.find_bin(a.get('sva_bin'))
    if not exe:
        raise WaveError(f'no sva CLI (make sva-build, or bin/<os>-x86_64/sva): {what} needs it')
    return exe


def cli_time(a, k):
    """A time argument of the agent (ns, or a text with a unit) as the CLI takes it: ps, with a sign."""
    t = ps_of(a.get(k), k)
    return None if t is None else f'{round(t)}ps'


def names_arg(v):
    return ','.join(v) if isinstance(v, list) else str(v)


def cli_names(path, names, scope=''):
    """The agent's signals of dump path, by the rules of the wave_ tools (a path, under scope, a unique tail), as the CLI
    takes them: full paths, a * ? pattern as it is."""
    w = wave(path, {})
    items = names if isinstance(names, list) else [x for x in str(names).split(',') if x.strip()]
    return ','.join(x.strip() if re.search(r'[*?]', x) else w.signals([x], scope)[1][0][0] for x in items)


def bits_text(v):
    """A value of sva diff as an agent reads it: a bus of known bits in hex (as the CLI's text), the rest as it is."""
    return f'0x{int(v, 2):0{(len(v) + 3) // 4}x}' if len(v) > 4 and set(v) <= {'0', '1'} else v


def t_diff(a):
    """sva diff: two dumps compared change by change (streamed: neither read here) -> its JSON with the times in ns, the
    signals listed those that differ."""
    if a.get('results_a') or a.get('results_b'):   # the assertions' results of two runs: new, gone, moved failures
        if a.get('a') or a.get('b'):
            raise WaveError('"results_a" / "results_b" or "a" / "b" (dumps): one or the other')
        ra, rb = (os.path.abspath(os.path.expanduser(str(a.get(k) or ''))) for k in ('results_a', 'results_b'))
        for f in (ra, rb):
            if not os.path.isfile(f):
                raise WaveError(f'no such results JSON {f} (sva eval --json, sva_check)')
        cmd = [sva_exe(a, 'wave_diff'), 'diff', '--results', ra, rb, '--json', '-', '--limit', str(limit(a, 20))]
        for x, y in (a.get('map') or {}).items():
            cmd += ['--map', f'{x}={y}']
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if r.returncode not in (0, 1):
            raise WaveError(r.stderr.strip() or f'sva diff --results: exit {r.returncode}')
        d = cli_json(r.stdout)
        tf = lambda f: {k: ns(v) for k, v in f.items()}
        for x in d.get('assertions', []):
            x['new'], x['gone'] = [tf(f) for f in x.get('new', [])], [tf(f) for f in x.get('gone', [])]
            x['moved'] = [{'a': tf(m['a']), 'b': tf(m['b'])} for m in x.get('moved', [])]
            if x.get('first_new') is not None:
                x['first_new'] = ns(x['first_new'])
        d['assertions'] = [x for x in d.get('assertions', []) if x['new'] or x['gone'] or x['moved'] or x.get('lost') or x.get('found')]
        d.update(unit='ns', same=r.returncode == 0)
        d.pop('wavelens', None)
        d.pop('version', None)
        return d
    da, db = dump_path(a, 'a'), dump_path(a, 'b')
    cmd = [sva_exe(a, 'wave_diff'), 'diff', da, db, '--json', '-', '--quiet', '--limit', str(limit(a, 20)), '--rank', '5']
    for k, flag in (('from', '--from'), ('to', '--to'), ('offset', '--offset')):   # the flags written out: test_cli_flags reads them
        t = cli_time(a, k)
        if t is not None:
            cmd += [flag, t]
    if a.get('signals'):
        cmd += ['--signals', cli_names(da, a['signals'], a.get('scope') or '')]
    elif a.get('scope'):
        cmd += ['--scope', a['scope']]
    for x, y in (a.get('map') or {}).items():
        cmd += ['--map', f'{x}={y}']
    if a.get('segment'):
        cmd += ['--segment', a['segment']]
    if a.get('align'):
        cmd.append('--align')
    if a.get('spans'):
        cmd += ['--spans', str(a['spans'])]
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)   # stdin is the protocol
    if r.returncode not in (0, 1):
        raise WaveError('; '.join(fst_notes(r.stderr)) or f'sva diff: exit {r.returncode}')
    d = cli_json(r.stdout)
    t = lambda v: None if v is None else ns(v)
    first = lambda f: f and {**f, 't': ns(f['t']), 'a': bits_text(f['a']), 'b': bits_text(f['b'])}
    for side in ('a', 'b'):
        d[side] = {**d[side], 'start': t(d[side].get('start')), 'end': t(d[side].get('end'))}
    d.update(unit='ns', equal=r.returncode == 0, **{k: t(d.get(k)) for k in ('from', 'to', 'offset')})
    d['first'] = first(d.get('first'))
    d['differences'] = [first(x) for x in d.get('differences', [])]
    n = limit(a, 20)
    sigs = [x for x in d.get('signals', []) if x.get('differ') or x.get('other')]
    for x in sigs:
        x['first'] = first(x.get('first'))
        if 'spans' in x:
            x['spans'] = [[ns(u), ns(v)] for u, v in x['spans']]
    d['signals'] = sigs[:n]
    if len(sigs) > n:
        d['signals_more'] = len(sigs) - n
    d['rank'] = [{**x, 't': ns(x['t']), 'after_first': ns(x.pop('after_first_ps')), 'a': bits_text(x['a']), 'b': bits_text(x['b'])} for x in d.get('rank', [])]
    for g in d.get('segments', []):
        for k in ('from', 'to', 'b_from', 'compared_to'):
            if k in g:
                g[k] = t(g[k])
        g['first'] = first(g.get('first'))
    if not d.get('notes'):
        d.pop('notes', None)
    d.pop('wavelens', None)
    d.pop('version', None)
    return d


RUN_ACTIONS = ('list', 'keep', 'set', 'rm', 'diff')


def t_runs(a):
    """sva runs: the runs kept of a dump (.wavelens-runs beside it, as the VS Code Runs panel keeps them) -> list: dir, runs
    (newest first); keep: the run kept; set: the run changed; rm: removed; diff: the dump against each run (or "run") over a
    window, times in ns; "case" NAME: each run over its test case of that name against the dump's (cocotb's marks);
    "against" RUN: that run is A instead of the dump (run "now": the dump as a B), the answer's "against" names it."""
    act = a.get('action') or 'list'
    if act not in RUN_ACTIONS:
        raise WaveError(f'"action": one of {", ".join(RUN_ACTIONS)}')
    exe = sva_exe(a, 'wave_runs')
    cmd = [exe, 'runs', act]
    d = os.path.abspath(os.path.expanduser(str(a['dir']))) if a.get('dir') else None
    dump = dump_path(a) if act in ('keep', 'diff') or (a.get('dump') and not d) else None
    if not d and not dump:
        raise WaveError('"dump" (the runs beside it) or "dir" (the directory of runs)')
    # no dir: the CLI's rule, as the VS Code panel's (the workspace's wavelens.runsDir, else .wavelens-runs beside the dump)
    if act in ('set', 'rm') and a.get('run') in (None, ''):
        raise WaveError('"run": its number or name')
    runs = a.get('run') if isinstance(a.get('run'), list) else [] if a.get('run') in (None, '') else [a['run']]
    if act in ('keep', 'diff') or (act == 'list' and dump):
        cmd.append(dump)
    if act in ('set', 'rm'):
        cmd += [str(x) for x in runs]
    if act in ('set', 'rm', 'path') and dump and not d:
        cmd.append(dump)
    cmd += (['--dir', d] if d else []) + (['--json'] if act != 'path' else [])
    if a.get('all') and act in ('list', 'diff'):
        cmd.append('--all')
    if act in ('keep', 'set'):
        if a.get('name'):
            cmd += ['--name', str(a['name'])]
        if a.get('tags') is not None:
            tags = a['tags'] if isinstance(a['tags'], list) else str(a['tags']).split(',')
            cmd += ['--tags', ','.join(str(t).strip() for t in tags)]
        if a.get('comment') is not None:
            cmd += ['--comment', str(a['comment'])]
    if act == 'keep':   # from and to: a slice, that window alone, its times from 0
        for k, flag in (('from', '--from'), ('to', '--to')):
            t = cli_time(a, k)
            if t is not None:
                cmd += [flag, t]
    # cases: a file (a marks file, a list), "none", or a list [{name, from, to}] (times in ns or with a unit) on stdin
    feed = None
    cases = a.get('cases')
    if cases is not None and act in ('keep', 'set', 'diff'):
        if isinstance(cases, list):
            ps = lambda v: v * 1000 if isinstance(v, (int, float)) and not isinstance(v, bool) else v
            feed = json.dumps([{**c, 'from': ps(c.get('from')), 'to': ps(c.get('to'))} for c in cases if isinstance(c, dict)])
            cmd += ['--cases', '-']
        else:
            cmd += ['--cases', str(cases) if str(cases) == 'none' else os.path.abspath(os.path.expanduser(str(cases)))]
    if act == 'diff' and a.get('case'):
        cmd += ['--case', str(a['case'])]
    if act == 'diff':
        if a.get('against') not in (None, ''):
            cmd += ['--against', str(a['against'])]
        for x in runs:
            cmd += ['--run', str(x)]
        for k, flag in (('from', '--from'), ('to', '--to')):
            t = cli_time(a, k)
            if t is not None:
                cmd += [flag, t]
        if a.get('signals'):
            cmd += ['--signals', cli_names(dump, a['signals'], a.get('scope') or '')]
        elif a.get('scope'):
            cmd += ['--scope', a['scope']]
        for x, y in (a.get('map') or {}).items():
            cmd += ['--map', f'{x}={y}']
        cmd += ['--limit', str(limit(a, 20))]
    r = subprocess.run(cmd, capture_output=True, text=True, **({'input': feed} if feed is not None else {'stdin': subprocess.DEVNULL}))
    try:
        out = cli_json(r.stdout) if r.stdout.strip() else None
    except ValueError:
        out = None
    if out is None or (r.returncode not in (0, 1) and act != 'diff'):
        raise WaveError('; '.join(fst_notes(r.stderr)) or f'sva runs {act}: exit {r.returncode}')
    t = lambda v: None if v is None else ns(v)
    case = lambda c: c and {**c, 'from': t(c.get('from')), 'to': t(c.get('to')), **({'offset': t(c['offset'])} if 'offset' in c else {})}
    run = lambda x: {**x, 'start': t(x.get('start')), 'end': t(x.get('end')), **({'cases': [case(c) for c in x['cases']]} if x.get('cases') else {}),
                     **({'slice': {'from': t(x['slice'].get('from')), 'to': t(x['slice'].get('to'))}} if x.get('slice') else {})} \
        if 'start' in x else x
    if act == 'list':
        return {'dir': out.get('dir', d), 'unit': 'ns', 'runs': [run(x) for x in reversed(out.get('runs', []))], 'others': out.get('others', 0)}
    if act in ('keep', 'set'):
        return {'unit': 'ns', **run(out)}
    if act == 'rm':
        return {'unit': 'ns', 'removed': [run(x) for x in out.get('removed', [])]}
    first = lambda f: f and {**f, 't': ns(f['t']), 'a': bits_text(f['a']), 'b': bits_text(f['b'])}
    for x in out.get('runs', []):
        for k in ('from', 'to'):
            if k in x:
                x[k] = t(x[k])
        if 'first' in x:
            x['first'] = first(x['first'])
        for s in x.get('signals', []):
            s['first'] = first(s.get('first'))
        if x.get('case'):
            x['case'] = case(x['case'])
    if out.get('case'):
        out['case'] = case(out['case'])
    if out.get('against'):   # A, a run: {id, name, file} (null: the dump)
        out['against'] = run(out['against'])
    out.update(unit='ns', **{k: t(out.get(k)) for k in ('from', 'to')})
    out.pop('wavelens', None)
    out.pop('version', None)
    return out


def t_cut(a):
    """sva vcd --from --to --signals: a window of a dump as a small VCD (the values at "from" as $dumpvars)."""
    src = dump_path(a)
    out = os.path.abspath(os.path.expanduser(str(a.get('out') or '')))
    if not a.get('out') or out == src:
        raise WaveError('"out": the VCD to write (not the dump itself)')
    cmd = [sva_exe(a, 'wave_cut'), 'vcd', src, '--out', out]
    window(wave(src, {}), a)
    for k, flag in (('from', '--from'), ('to', '--to')):
        t = cli_time(a, k)
        if t is not None:
            cmd += [flag, t]
    if a.get('signals'):
        cmd += ['--signals', cli_names(src, a['signals'])]
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise WaveError('; '.join(fst_notes(r.stderr)) or f'sva vcd: exit {r.returncode}')
    # what the cut holds: its declarations and its first and last time, read off its text
    head, times, nvar = True, [], 0
    with open(out, encoding='utf-8', errors='replace') as f:
        for line in f:
            if head:
                nvar += line.lstrip().startswith('$var ')
                head = '$enddefinitions' not in line
            elif line.startswith('#'):
                times.append(line[1:].strip())
    d = dumpscan.read(out, body=None)
    unit = d.unit_ps if d else None
    res = {'out': out, 'bytes': os.path.getsize(out), 'variables': nvar}
    if times and unit:
        res.update(unit='ns', **{'from': ns(int(times[0]) * unit), 'to': ns(int(times[-1]) * unit)})
    return res


def t_view_edit(a):
    if a.get('config'):   # the config file a page is built from: the marks a rebuild keeps
        if a.get('page') or a.get('save'):
            raise WaveError('"config" or "page": one of them (a config: its views\' bookmarks, arrows, spans)')
        path = os.path.abspath(os.path.expanduser(str(a['config'])))
        fp = a.get('from_page')
        keys = a.get('keys') if isinstance(a.get('keys'), list) or a.get('keys') is None else str(a['keys']).split(',')
        res, key, changed = viewedit.edit_config(path, ops_in(a.get('ops') or [], True) if a.get('ops') or not fp else [], a.get('view'),
                                                 os.path.abspath(os.path.expanduser(str(fp))) if fp else None, keys)
        errs = sum(1 for r in res if 'error' in r)
        out = {'config': path, 'view': key, 'results': res, 'changed': changed,
               'note': 'nothing written: a command failed' if errs else 'written into the config: mkhtml.py builds the page with them' if changed else
               'nothing changed'}
        if errs:
            out['errors'] = errs
        return out
    if a.get('save') and page_arg(a) and DUMP_RE.search(page_arg(a)):   # before anything is done: no edit twice on a retry
        raise WaveError('save: a dump has no page file to write into (VS Code keeps the view of its tab; Save in the tab writes a .view.json)')
    mode, where, v = target(a)
    note = ''
    if mode == 'live':
        try:
            return live_edit(a, where, v)
        except LiveGone as e:   # the tab went before it answered the edit: the file, when there is one
            if not page_arg(a) or DUMP_RE.search(page_arg(a)):
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


def live_compare(op, where, v, a):
    """compare {dump} for a live viewer (it reads no file by itself): sva diff here, the page gets {result}. The page's file
    gives the rows and the dump beside it; a dump's tab in VS Code is that dump, every signal of it."""
    if not (isinstance(op, dict) and op.get('op') == 'compare' and op.get('dump') and op.get('result') is None):
        return op
    path = page_arg(a) or (where['path'] if os.path.isfile(where['path']) else None)
    args = {k: x for k, x in op.items() if k != 'op'}
    if path and DUMP_RE.search(path):
        exe = svabuild.find_bin(a.get('sva_bin'))
        if not exe:
            raise WaveError('compare dump: needs the sva CLI (make sva-build, or bin/<os>-x86_64/sva)')
        b = os.path.join(os.path.dirname(path), os.path.expanduser(str(args['dump'])))
        res = svabuild.compare(exe, args.get('a') or path, b, None, None, None, args.get('map'), args.get('offset'))
    elif path:
        pg = viewedit.Page(path)
        res = viewedit.compare_dump(pg.model(pg.view(v.get('key'))), os.path.dirname(os.path.abspath(path)), args)
    else:
        raise WaveError('compare dump: the live page has no file here to find its dump beside: give "page", or "a" with the dump of its waves')
    return {'op': 'compare', 'result': res, **({'show': op['show']} if op.get('show') is not None else {})}


def live_edit(a, where, v):
    ops = [live_compare(o, where, v, a) for o in ops_in(a.get('ops'), v.get('timed'))]   # before any is sent: none done twice
    res = BRIDGE[0].send(where['cid'], v.get('key'), ops)
    out = {'live': where['path'], 'view': v.get('key'), 'results': ns_out(res, v.get('timed'))}
    if a.get('save'):   # the page answered: the edit is done there; never done again on the file (the person's own would go)
        try:
            path = page_arg(a)   # the file the agent named, the page's word for its path checked against it: a page does not choose what is written
            if not path or not same_file(path, where['path']):
                raise WaveError('give "page", the file of this page' if not path else f'{path} is not this page ({where["path"]})')
            st = BRIDGE[0].send(where['cid'], v.get('key'), [{'op': 'state'}])[0]
            st = st.get('state') if isinstance(st, dict) else None
            if not isinstance(st, dict):
                raise WaveError(f'the live page gave no state ({json.dumps(st)[:100]})')
        except WaveError as e:
            out['saved'] = None
            out['note'] = f'applied live, not saved into the page\'s file: {e}'
        else:
            pg = viewedit.Page(path)
            key = pg.view(v.get('key'))
            pg.put(key, {k: x for k, x in st.items() if k not in ('wavelens', 'version', 'title')})
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
            if not page_arg(a) or DUMP_RE.search(page_arg(a)):
                raise
            where = page_arg(a)
    pg = viewedit.Page(where)
    key = pg.view(a.get('view'))
    m = pg.model(key)
    ed = viewedit.Editor(m, pg.state(key))
    out = {'page': where, 'view': key, 'views': list(pg.waves), 'edits': pg.rev(key)}
    out.update((state_ns(ed.st) if m.timed else ed.st) if a.get('full') else summary(ed.st, m.timed, ed))
    if a.get('rows') is not None:
        out['rows'] = ed.c_rows({'pattern': a['rows'] or '', 'limit': a.get('limit') or 200, 'offset': a.get('offset') or 0})
    if a.get('picture'):   # the page's file in a headless Chromium (tools/pageshot.py, playwright: optional)
        png, why = page_picture(where, key)
        if png:
            return Image(png, out)
        out['note'] = f'no picture: {why}; live: view_live'
    return out


def page_picture(path, key, theme='dark'):
    """A PNG (base64) of one view of a page's file, made by tools/pageshot.py -> (png | None, why not)."""
    import base64
    exe = [sys.executable, os.path.join(ROOT, 'tools', 'pageshot.py')]
    with tempfile.TemporaryDirectory(prefix='wavemcp-shot-') as d:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        try:
            r = subprocess.run(exe + [path, '--view', key, '--theme', theme, '--out', d], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               timeout=120, env=env)
        except subprocess.TimeoutExpired:
            return None, 'pageshot.py took more than 2 minutes'
        try:
            made = json.loads(r.stdout or '[]')
        except json.JSONDecodeError:
            made = []
        if r.returncode == 2 or not made:
            return None, (r.stderr.strip().splitlines() or ['pageshot.py failed'])[-1].replace('pageshot: ', '')
        with open(made[0]['path'], 'rb') as f:
            return base64.b64encode(f.read()).decode(), None


def live_get(a, where, v):
    ops = [{'op': 'state'}]
    if a.get('rows') is not None:
        ops.append({'op': 'rows', 'pattern': a['rows'] or '', 'limit': a.get('limit') or 200, 'offset': a.get('offset') or 0})
    res = BRIDGE[0].send(where['cid'], v.get('key'), ops)
    got = lambda r, k: r[k] if isinstance(r, dict) and isinstance(r.get(k), (dict, str)) else fail_live(r)
    st = got(res[0], 'state')
    out = {'live': where['path'], 'view': v.get('key'), 'views': [x.get('key') for x in where['views']]}
    out.update((state_ns(st) if v.get('timed') else st) if a.get('full') else summary(st, v.get('timed')))
    if a.get('rows') is not None:
        out['rows'] = {k: x for k, x in res[1].items() if k != 'op'} if isinstance(res[1], dict) and 'error' not in res[1] else fail_live(res[1])
    if (out.get('gaps') or {}).get('view'):   # the gaps on the waves: what they leave
        cut = ns_out(BRIDGE[0].send(where['cid'], v.get('key'), [{'op': 'gaps'}]), v.get('timed'))[0]
        if isinstance(cut, dict) and isinstance(cut.get('cut'), dict):
            out['gaps'] = dict(out['gaps'], cut=cut['cut'])
    if a.get('picture'):
        pic = BRIDGE[0].send(where['cid'], v.get('key'), [{'op': 'picture', 'format': 'png'}])[0]
        return Image(got(pic, 'png'), out)
    return out


def fail_live(r):
    raise WaveError(str(r['error']) if isinstance(r, dict) and r.get('error') else f'the live page answered {json.dumps(r)[:200]}')


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
          'limit': N, 'types': {'type': 'string', 'description': 'types file (default: <dump>.types.json beside it)'}, 'no_types': B}


def tool(name, fn, desc, props, required=('dump',), ro=True):
    """readOnlyHint: a client may call the tool without asking (codex exec calls no other tool without approval)."""
    props = {k: COMMON.get(k, v) if v is None else v for k, v in props.items()}
    return {'name': name, 'fn': fn, 'description': desc,
            'inputSchema': {'type': 'object', 'properties': props, 'required': list(required)},
            'annotations': {'readOnlyHint': True} if ro else {'readOnlyHint': False, 'destructiveHint': False}}


TOOLS = [
    tool('wave_info', t_info, 'A dump at a glance: time span, signal count, scopes, clocks with period, resets.', {'dump': None, 'types': None, 'no_types': None}),
    tool('wave_signals', t_signals, 'Find signals -> [path, width, changes, extra]. pattern: substring or glob (* ?); depth: levels under scope.',
         {'dump': None, 'pattern': S, 'scope': None, 'depth': N, 'active': B, 'limit': None, 'offset': N}),
    tool('wave_values', t_values, 'Values of signals at one or more times (side "before": just before the changes at that time).',
         {'dump': None, 'types': None, 'no_types': None, 'signals': None, 'at': {'type': ['number', 'string', 'array'], 'items': T}, 'side': S, 'scope': None, 'radix': None},
         ('dump', 'signals', 'at')),
    tool('wave_changes', t_changes, 'Value changes of signals in a window: value at "from", then [t, value], limit per signal.',
         {'dump': None, 'types': None, 'no_types': None, 'signals': None, 'from': None, 'to': None, 'scope': None, 'radix': None, 'limit': None}, ('dump', 'signals')),
    tool('wave_sample', t_sample, 'Table per clock cycle [cycle, t, values], sampled before the edge; only_changes (default true) '
         'drops rows equal to the one before; clock: default the nearest.',
         {'dump': None, 'types': None, 'no_types': None, 'signals': None, 'clock': S, 'edge': S, 'only_changes': B, 'from': None, 'to': None, 'scope': None,
          'radix': None, 'limit': None}, ('dump', 'signals')),
    tool('wave_find', t_find, 'Search -> match count and first matches. expr: SV expression or sequence per clock cycle (sva engine; '
         '"req && !ack", "req ##[1:3] ack", "$rose(x)"; names under scope). Or signal + edge (rise fall change) or value: exact times.',
         {'dump': None, 'types': None, 'no_types': None, 'expr': S, 'clock': S, 'signal': S, 'edge': S, 'value': T, 'from': None, 'to': None, 'scope': None,
          'limit': None, 'radix': None, 'defines': {'type': ['object', 'array'], 'items': S}}),
    tool('wave_explain', t_explain, 'One call from a moment to what to look at: expr (its nth match), assert ("name@scope" with sva: its files; its '
         'nth failure, the window from the attempt\'s start), b (the first difference with that dump, '
         'and who differed next) or t (a time, with signals) -> at, its window (before / after cycles of the clock), its signals and their values '
         'there (a wave_sample table; with b, table_b: the other run\'s); out (.html): a page of that window with a marker and the cursor there.',
         {'dump': None, 'types': None, 'no_types': None, 'expr': S, 'assert': S, 'sva': L, 'clock': S, 'nth': N, 'b': S, 'map': {'type': 'object'}, 'offset': T, 't': T,
          'signals': None, 'scope': None, 'before': N, 'after': N, 'limit': None, 'out': S, 'title': S}, ('dump',), ro=False),
    tool('wave_fsm', t_fsm, 'An FSM\'s states in a dump: each state\'s entries, first entry, time held and share, the states never reached, '
         'the values of no state (x, z, a code without a label), its changes by count. Its table: the dump\'s (FST), the types file, or enum {code: label}.',
         {'dump': None, 'types': None, 'no_types': None, 'signal': S, 'enum': {'type': 'object'}, 'from': None, 'to': None, 'scope': None}, ('dump', 'signal')),
    tool('wave_stats', t_stats, 'Aggregates over a window. Bit: rises, falls, high %, pulse widths, period. Bus: changes, distinct, '
         'longest-held values, min, max.', {'dump': None, 'types': None, 'no_types': None, 'signals': None, 'from': None, 'to': None, 'scope': None, 'radix': None},
         ('dump', 'signals')),
    tool('sva_check', t_sva, 'Evaluate SystemVerilog assertions (files, packages first, and/or source text) over the dump in scope -> '
         'failed with first failures [cycle, t, start_cycle, start_t, note], passed, vacuous, not_evaluated, covers.',
         {'dump': None, 'files': L, 'source': S, 'scope': None, 'assertions': L, 'from': None, 'to': None, 'max_failures': N,
          'details': B, 'defines': {'type': ['object', 'array'], 'items': S}}),
    tool('wave_page', t_page, 'Write a WaveLens viewer page (out .html) or WaveJSON (out .json) of signals to show a person; clock '
         '(name or "auto"): a cell per cycle, auto_gap "16:2" folds idle cycles; sva files + bind ["name@scope"]; compare: a second dump '
         '(or {dump, map, offset, segment, align, show}: show the run it opens with, a, b or overlay) whose differences the page shows; '
         'marks: the marks file of a cocotb run, its tests as spans and bookmarks (marks_views "tests": each test apart, "both": and the whole run).',
         {'dump': None, 'types': None, 'no_types': None, 'signals': None, 'out': S, 'clock': S, 'from': None, 'to': None, 'scope': None, 'auto_gap': S, 'sva': L,
          'bind': L, 'title': S, 'compare': {'type': ['string', 'object']}, 'marks': S, 'marks_views': {'type': 'string', 'enum': list(testmarks.SPLITS)}},
         ('dump', 'signals', 'out'), ro=False),
    tool('wave_tests', t_tests, 'The tests of a cocotb run from the marks file it left (wavelens_cocotb, the same times as its dump) -> summary, '
         'tests [n, name, result pass/fail/xfail/run, from, to, checks, failed_checks, message, where]; test (a number or name): one, with '
         'its whole docstring (text), its own rows (signals), phases and marks, each check with got and expected (got_all, expected_all, at where a long value was cut); '
         'its steps by length, the longest first (steps, total, longest; steps: true: only them). A test\'s measures (wl.measure: label, from, to, dt, min, max, ok; '
         'ok null: a bound in cycles), measures_failed; slowest: the five longest steps of the run. from / to are a test\'s window for wave_changes, wave_find, wave_sample. '
         'marks a directory: a regression, every marks file under it -> summary, totals, failures first [file, n, name, result, from, message, where], '
         'runs [file, summary, tests, failed] the failed first.',
         {'marks': S, 'test': {'type': ['integer', 'string']}, 'limit': None, 'steps': B}, ('marks',)),
    tool('wave_to_fst', t_to_fst, 'Convert a VCD to an FST beside it (tb.vcd -> tb.fst; out: another file), as GTKWave\'s vcd2fst, '
         'keeping the enum tables (FSM states) and attributes; the states of tb.types.json beside it go in too (types: another file, '
         'no_types: none) -> fst, what was written, notes (file:line).',
         {'dump': None, 'out': S, 'types': S, 'no_types': B}, ('dump',), ro=False),
    tool('wave_diff', t_diff, 'Compare two dumps a and b (VCD/FST, streamed: hundreds of MB) change by change, as the viewer\'s Compare… '
         'does -> compared, differ, first [t, signal, a, b], the signals that differ, only_a, only_b, segments. map {"tb_a.if": "tb_b.if"}: '
         'a\'s scope or path -> b\'s; offset: b later by that much; segment: a signal (a test case number), counts per value; align: '
         'segment k of b on segment k of a; rank: the first five signals by their first difference (who differed first, what followed). '
         'results_a, results_b (instead of a, b): the assertions\' results of two runs (sva eval --json) -> new, gone, moved failures per assertion.',
         {'a': S, 'b': S, 'signals': None, 'scope': None, 'from': None, 'to': None, 'offset': T, 'map': {'type': 'object'}, 'segment': S,
          'align': B, 'limit': None, 'spans': N, 'results_a': S, 'results_b': S}, ()),
    tool('wave_runs', t_runs, 'The runs kept of a dump (.wavelens-runs beside it, FSTs with a name, tags, a comment: the ones the VS Code '
         'Runs panel keeps) -> action list: dir, runs of this dump [id, name, tags, comment, kept, dump, start, end] newest first '
         '(others: of other dumps, all: true lists them); keep: the dump as a '
         'run (name, tags, comment); set: a run\'s name, tags, comment; rm: runs removed; diff: the dump against each run (run: a number, '
         'a name or a list of them) over a window (from, to; signals, scope, map) -> per run signals_compared, signals_differ, first '
         '[t, signal, a, b], the signals that differ (limit). Which run before broke it: diff over the test\'s window. '
         'Test cases: keep stores a run\'s cases (cocotb\'s wavelens.marks.json beside the dump, or cases: a file, "none", or '
         '[{name, from, to}]; set changes them); diff case: NAME compares each run\'s case NAME with the dump\'s (from/to: the '
         'dump\'s window of it, else its cases), wherever it is in the run (case.offset), over the shorter. '
         'keep from, to: a slice, that window of the dump alone as a run, its times from 0 (slice: its window in the dump), so slices '
         'compare with each other from their first sample (diff against: one slice, run: another). '
         'diff against: a run (number or name) compared with the others instead of the dump (run: "now" adds the dump), '
         'the window in its time, the answer\'s against: {id, name, file}. '
         'Then wave_diff with b = dir/file of a run for the details.',
         {'action': {'type': 'string', 'enum': list(RUN_ACTIONS)}, 'dump': S, 'dir': S, 'run': {'type': ['integer', 'string', 'array'], 'items': {'type': ['integer', 'string']}},
          'all': B, 'name': S, 'tags': {'type': ['string', 'array'], 'items': S}, 'comment': S, 'from': None, 'to': None, 'signals': None, 'scope': None,
          'map': {'type': 'object'}, 'limit': None, 'case': S, 'against': {'type': ['integer', 'string']},
          'cases': {'type': ['string', 'array'], 'items': {'type': 'object'}}}, (), ro=False),
    tool('wave_cut', t_cut, 'Cut a window (and some signals) out of a dump into a small VCD (out): the values at "from" first, '
         'then the changes up to "to" -> out, bytes, variables, from, to. For Compare… on a page, a fixture, sending one test case.',
         {'dump': None, 'out': S, 'from': None, 'to': None, 'signals': None}, ('dump', 'out'), ro=False),
    tool('view_edit', t_view_edit, 'Mark up a WaveLens page for a person (live in their browser when connected by view_live, else in the '
         'page file: they reload it). ops in order, each {op, …}: ' +
         ' '.join(f'{k}({v})' + ('·live' if k in viewedit.LIVE_ONLY else '') for k, v in viewedit.COMMANDS.items()
                  if k not in ('state', 'set_state', 'rows', 'picture')) +
         ' (·live: in a connected page only). t/from/to in ns; signals: path, name, path tail or * pattern; bookmark: a numbered circle with a text (no signal: on the time '
         'axis); arrow from/to: bookmark numbers; group: a folder of signals at the top; only: just these modules on the waves (with their '
         'submodules); edge: the cursor to the next edge. config (instead of page): a mkhtml config file, bookmark / arrow / span '
         'on its view, kept by a rebuild (a bookmark\'s "at" event stays until a t replaces it), the rest of its look (group, radix, marker, '
         'deltas, hide, paint, expr …) its "state" the page opens with, view its window; from_page: a page\'s whole view into it (keys: some). '
         'gaps with on and view true: the waves themselves '
         'with the idle stretches cut out, as the person scrolls them (live: its answer has cut, what is left). marker: pale unless it has a '
         'color (null: pale again), its label at the top of the rows, with signal in a thin line over that row (lift "below": under it, the lines '
         'lifted bookmarks use; signal null: at the top again); the person drags it from line to line. expr: a condition in the page\'s list '
         '(text), marked band, line or strip, gap: the waves cut to its matches with the others that have it, answers n, time, share, first, '
         'last, min, max, on a file only id.',
         {'page': S, 'config': S, 'view': S, 'ops': {'type': 'array', 'items': {'type': 'object'}}, 'save': B, 'from_page': S,
          'keys': {'type': 'array', 'items': S}}, (), ro=False),
    tool('view_get', t_view_get, 'What a page shows: bookmarks, arrows, markers (measures: the Δ between them, ok of a bound), expressions, groups, highlight, colours, hidden, cursor, window (live: '
         'with the person\'s own edits), the gaps (live, on the waves: cut, the gaps and the parts kept). rows: list its signals (a pattern, "" all; limit, '
         'offset); full: the whole state; picture: a PNG of the view (live: the screen; a file: '
         'made in a headless Chromium, tools/pageshot.py).',
         {'page': S, 'view': S, 'rows': S, 'limit': N, 'offset': N, 'picture': B, 'full': B}, ()),
    tool('view_live', t_view_live, 'Connect a page to this server: it is written into the page (open or reload it), then view_edit and '
         'view_get work on it live; open: open it in the browser; off: disconnect; rotate: a new key, so a copy of a page that carried '
         'the old one no longer connects (the pages linked before need view_live again). page a .vcd / .fst: its tab in VS Code (the '
         'WaveLens extension connects by itself; open: VS Code opens it). Without page: the pages connected.',
         {'page': S, 'open': B, 'off': B, 'rotate': B}, (), ro=False),
]
BY_NAME = {t['name']: t for t in TOOLS}


LEAN = [False]   # --lean: the short tool list


def listing(lean=None):
    """The tools as the protocol lists them. lean (--lean): each description its first sentence, the properties without
    theirs, types / no_types not listed (still taken), view_edit without its list of commands: a third fewer characters,
    sent with every request; the same tools and answers."""
    out = [{k: v for k, v in t.items() if k != 'fn'} for t in TOOLS]
    if not (LEAN[0] if lean is None else lean):
        return out
    short = []
    for t in json.loads(json.dumps(out)):
        t['description'] = ("Mark up a WaveLens page (or its config) for a person: ops [{op, …}] of the viewer's commands (wavemcp.py --list: their "
                            'arguments).' if t['name'] == 'view_edit' else re.split(r'(?<=\.)\s', t['description'])[0])
        props = t['inputSchema']['properties']
        for k in [k for k in ('types', 'no_types') if t['name'] != 'wave_to_fst' and k in props]:   # the types file beside the dump: taken anyway
            del props[k]
        for p in props.values():
            p.pop('description', None)
        short.append(t)
    return short


def compact(obj):
    return json.dumps(obj, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def fits(v, sch):
    """A value against a property's schema (the types of TOOLS: string, integer, number, boolean, array, object); an
    array takes one item alone too ("signals": "PSEL"), an integer 5.0."""
    for ty in sch['type'] if isinstance(sch['type'], list) else [sch['type']]:
        if ty == 'string' and isinstance(v, str) or ty == 'boolean' and isinstance(v, bool) or ty == 'object' and isinstance(v, dict):
            return True
        if ty in ('number', 'integer') and isinstance(v, (int, float)) and not isinstance(v, bool) and viewedit.finite(v) and (
                ty == 'number' or float(v).is_integer()):
            return True
        if ty == 'array' and (all(fits(x, sch['items']) for x in v) if isinstance(v, list) else fits(v, sch['items'])):
            return True
    return False


# another name an agent gives an argument (the one of a sibling tool): taken for the schema's own, one way
SYNONYMS = {'signals': ('signal',), 'signal': ('signals',), 'at': ('times', 't'), 'source': ('text',), 'a': ('dump',)}
HIDDEN = {'sva_bin', 'resolve', 'wait', 'hierarchy'}   # for the tests and the VS Code extension: not in the schemas


def check_args(t, a):
    """A tool's arguments against its schema -> them (an integer as an int); one of a wrong kind, one the tool does not
    take, a synonym (SYNONYMS: "signal" for "signals", "times" for "at", "text" for "source") given with its own name and
    another value are errors that say what it takes."""
    props, a = t['inputSchema']['properties'], dict(a)
    for main, alts in SYNONYMS.items():
        for alt in alts:
            if main not in props or alt in props or alt not in a:
                continue
            v = a.pop(alt)
            if main == 'signal':   # wave_find: one signal
                if isinstance(v, list) and len(v) == 1:
                    v = v[0]
                elif isinstance(v, list):
                    raise WaveError(f'{t["name"]} searches one "signal", not {len(v)} ({json.dumps(v, ensure_ascii=False)[:80]})')
            if a.get(main) is not None and a[main] != v:
                raise WaveError(f'"{alt}" is "{main}" here, and both are given with other values')
            a[main] = v
    bad = [k for k in a if k not in props and k not in HIDDEN]
    if bad:
        raise WaveError(f'{t["name"]}: no argument {", ".join(json.dumps(k) for k in bad)} (it takes: {", ".join(props)})')
    out = dict(a)
    for k, v in a.items():
        sch = props.get(k)
        if sch is None or v is None:
            continue
        if not fits(v, sch):
            want = '/'.join(sch['type'] if isinstance(sch['type'], list) else [sch['type']])
            want += f' of {sch["items"]["type"] if isinstance(sch["items"]["type"], str) else "/".join(sch["items"]["type"])}' if 'items' in sch else ''
            raise WaveError(f'"{k}": {"an" if want[0] in "aeiou" else "a"} {want}, not {json.dumps(v, ensure_ascii=False)[:80]}')
        if sch.get('type') == 'integer':
            out[k] = int(v)
    return out


def call(name, args, images=None):
    """A tool by name -> (text, is error); a picture it gives goes to images (a list; none: left out). Everything the
    libraries print goes to stderr (stdout is the protocol)."""
    t = BY_NAME.get(name) if isinstance(name, str) else None
    if not t:
        return f'unknown tool {json.dumps(name, ensure_ascii=False)[:80]}; the tools: {", ".join(BY_NAME)}', True
    if args is not None and not isinstance(args, dict):
        return f'the arguments of {name} are an object ({{"dump": …}}), not {json.dumps(args, ensure_ascii=False)[:80]}', True
    NOTES.clear()
    MISSING.clear()
    try:
        with contextlib.redirect_stdout(sys.stderr):
            got = t['fn'](check_args(t, args or {}))
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
    except SystemExit as e:   # a library that meant to end a program of its own: this tool's error, the server goes on
        return f'{name} stopped ({e.code})', True
    except Exception as e:   # noqa: BLE001 — anything else: this call's error (and its trace in the agent's log), not the session's end
        print(f'wavemcp: {name}: ' + ''.join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip(), file=sys.stderr)
        return f'{type(e).__name__}: {e}', True
    if len(text) > MAX_TEXT:
        return (f'the answer is {len(text)} characters (more than {MAX_TEXT}): narrow the window (from / to), the signals, '
                'or lower "limit"'), True
    return text, False


# ---------------- JSON-RPC over stdio ----------------
def rpc_error(mid, code, message):
    return {'jsonrpc': '2.0', 'id': mid, 'error': {'code': code, 'message': message}}


def handle(msg):
    """One JSON-RPC message -> the response dict, or None for a notification. A message of a wrong shape gets its error
    (-32600 invalid request, -32602 invalid params), anything that goes wrong in it -32603: the session goes on."""
    if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0':
        return rpc_error(None, -32600, 'invalid request: a JSON-RPC 2.0 object')
    mid, method, p = msg.get('id'), msg.get('method'), msg.get('params')
    if mid is not None and (isinstance(mid, bool) or not isinstance(mid, (str, int, float))):
        return rpc_error(None, -32600, 'invalid request: "id" is a string or a number')
    if not isinstance(method, str):
        return rpc_error(mid, -32600, 'invalid request: "method" is a string')
    if mid is None:   # a notification (initialized, cancelled): nothing to answer
        return None
    if p is not None and not isinstance(p, dict):
        return rpc_error(mid, -32602, f'invalid params: an object, not {json.dumps(p)[:60]}')
    p = p or {}
    ok = lambda r: {'jsonrpc': '2.0', 'id': mid, 'result': r}
    try:
        if method == 'initialize':
            want = p.get('protocolVersion')
            return ok({'protocolVersion': want if isinstance(want, str) and want in PROTOCOLS else PROTOCOLS[0],
                       'capabilities': {'tools': {'listChanged': False}},
                       'serverInfo': {'name': 'wavelens', 'version': version()}, 'instructions': INSTRUCTIONS})
        if method == 'ping':
            return ok({})
        if method == 'tools/list':
            return ok({'tools': listing()})
        if method == 'tools/call':
            if not isinstance(p.get('name'), str):
                return rpc_error(mid, -32602, 'invalid params: "name", the tool, is a string')
            if p.get('arguments') is not None and not isinstance(p['arguments'], dict):
                return rpc_error(mid, -32602, f'invalid params: "arguments" is an object, not {json.dumps(p["arguments"])[:60]}')
            png = []
            text, err = call(p['name'], p.get('arguments'), png)
            return ok({'content': [{'type': 'text', 'text': text}] + [{'type': 'image', 'data': x, 'mimeType': 'image/png'} for x in png],
                       'isError': err})
    except Exception as e:   # noqa: BLE001 — the request's error, not the server's end
        print('wavemcp: ' + ''.join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip(), file=sys.stderr)
        return rpc_error(mid, -32603, f'internal error: {type(e).__name__}: {e}')
    return rpc_error(mid, -32601, f'method not found: {method}')


def respond(line):
    """One line of the protocol -> the text of its answer ('' for none)."""
    try:
        msg = json.loads(line)
    except (ValueError, RecursionError):
        return compact(rpc_error(None, -32700, 'parse error'))
    try:
        if isinstance(msg, list):
            resp = [r for r in map(handle, msg) if r] if msg else rpc_error(None, -32600, 'invalid request: an empty batch')
        else:
            resp = handle(msg)
        return compact(resp) if resp else ''
    except Exception as e:   # noqa: BLE001 — an answer that is not JSON (or anything not foreseen): said, the session goes on
        print(f'wavemcp: {type(e).__name__}: {e}', file=sys.stderr)
        mid = msg.get('id') if isinstance(msg, dict) and isinstance(msg.get('id'), (str, int)) else None
        return compact(rpc_error(mid, -32603, f'internal error: {type(e).__name__}: {e}'))


def serve(inp=None, out=None):
    inp = inp or sys.stdin
    out = out or sys.stdout
    for line in inp:
        if not line.strip():
            continue
        text = respond(line)
        if text:
            out.write(text + '\n')
            out.flush()


def protocol_streams():
    """stdin and stdout are the protocol: this process keeps them as its own, and the descriptors 0 and 1 every program
    it starts inherits become /dev/null and stderr (a browser, fst2vcd, the sva CLI never read a request or write into an
    answer) -> (input, output)."""
    inp = os.fdopen(os.dup(0), 'r', encoding='utf-8', errors='replace')
    out = os.fdopen(os.dup(1), 'w', encoding='utf-8')
    nul = os.open(os.devnull, os.O_RDONLY)
    os.dup2(nul, 0)
    os.close(nul)
    os.dup2(2, 1)
    return inp, out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--list', action='store_true', help='print the tools (name, description, input schema) and exit')
    ap.add_argument('--call', nargs=2, metavar=('TOOL', 'JSON'), help='run one tool with these arguments, print its answer and exit')
    ap.add_argument('--lean', action='store_true', help='the short tool list: first sentences, no property descriptions (a third fewer characters '
                    'with every request; the same tools and answers)')
    a = ap.parse_args()
    LEAN[0] = a.lean
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
    serve(*protocol_streams())
    return 0


if __name__ == '__main__':
    sys.exit(main())
