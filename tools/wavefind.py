#!/usr/bin/env python3
"""wavefind.py — the times of an event in a dump, one set of rules for the page's build (a bookmark "at", a marker "on",
vcd2wavedrom.py) and the MCP server's wave_find (wavemcp.py).

An event ("at" of a bookmark, "on" of a marker; docs/USAGE.md "Bookmarks at an event"), the keys of wave_find and "bind":
  "posedge X" | "negedge X" | "edge X" | "X"                  a marker's grammar (X: any change)
  {"signal": "r_state", "value": "FRAME_ERROR"}               the signal becomes that value (an enum label, a number,
                                                              'h.., 'b..); a value already there at "from" is a match
  {"signal": "x", "edge": "rise|fall|change|posedge|negedge|edge"}
  {"expr": "eof && err[1]", "clock"?: "clk", "scope"?: "…"}   an SV expression or sequence sampled before each edge of the
                                                              clock (the sva engine): each attempt that matches, at its start
  {"assert": "a_x", "scope"?: "…", "result": "fail"|"pass", "point"?: "failed_at"|"start"|"end"}   an attempt of a binding
                                                              over the whole dump (point: failed_at, else end, for a fail;
                                                              end for a pass)
  with "nth": k (from 1; default 1), "from", "to": the window searched (default: the view's; the whole dump for "assert").
"""
import bisect, json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import UNIT_PS, WaveError  # noqa: E402

EVENT = re.compile(r'\s*(?:(posedge|negedge|edge)\s+)?([^\s()|&!=<>~^*]+)\s*')
EDGES = {'rise': 'posedge', 'fall': 'negedge', 'any': 'change', 'change': 'change', 'posedge': 'posedge', 'negedge': 'negedge', 'edge': 'edge'}
KEYS = {'signal': ('signal', 'value', 'edge'), 'expr': ('expr', 'clock', 'scope', 'edge'), 'assert': ('assert', 'scope', 'result', 'point')}
COMMON = ('nth', 'from', 'to')


def spec(x):
    """An event as written -> {"kind": "signal" | "expr" | "assert", its keys, "nth", "from", "to"}; a shape it is not is a
    WaveError that says the forms."""
    if isinstance(x, str):
        m = EVENT.fullmatch(x)
        if not m:
            raise WaveError(f'"{x}" is "posedge X", "negedge X", "edge X" or "X" (any change); an SV expression is {{"expr": "…"}}')
        return {'kind': 'signal', 'signal': m.group(2), 'edge': m.group(1) or 'change', 'nth': 1}
    if not isinstance(x, dict):
        raise WaveError(f'an event is a text ("posedge X") or an object ({{"signal", "value" | "edge"}}, {{"expr"}}, {{"assert"}}), not {json.dumps(x)[:60]}')
    kinds = [k for k in KEYS if k in x]
    if len(kinds) != 1:
        raise WaveError(f'an event has one of "signal", "expr", "assert"' + (f', not {" and ".join(kinds)}' if kinds else f': {json.dumps(x)[:80]}'))
    kind = kinds[0]
    bad = sorted(set(x) - set(KEYS[kind]) - set(COMMON))
    if bad:
        raise WaveError(f'an event {{"{kind}"}}: unknown key(s) {", ".join(bad)} (have: {", ".join(KEYS[kind] + COMMON)})')
    out = {'kind': kind, **{k: x[k] for k in KEYS[kind] + COMMON if k in x}}
    n = out.get('nth', 1)
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise WaveError(f'"nth" is 1, 2, …, not {json.dumps(n)}')
    out['nth'] = n
    if kind == 'signal':
        if ('value' in x) == ('edge' in x):
            raise WaveError('an event {"signal"} has "value" or "edge" (rise, fall, change)')
        if 'edge' in x and x['edge'] not in EDGES:
            raise WaveError(f'"edge" is rise, fall, change, posedge, negedge or edge, not {json.dumps(x["edge"])}')
        if 'edge' in x:
            out['edge'] = EDGES[x['edge']]
    elif kind == 'assert':
        if out.get('result', 'fail') not in ('fail', 'pass'):
            raise WaveError(f'"result" is fail or pass, not {json.dumps(out["result"])}')
        out['result'] = out.get('result', 'fail')
        if out.get('point') not in (None, 'failed_at', 'start', 'end'):
            raise WaveError(f'"point" is failed_at, start or end, not {json.dumps(out["point"])}')
    elif kind == 'expr' and out.get('edge') not in (None, 'posedge', 'negedge', 'edge'):
        raise WaveError(f'"edge" of an expression\'s clock is posedge, negedge or edge, not {json.dumps(out["edge"])}')
    return out


def signals_of(x):
    """The signals an event reads from the dump itself (to read them in the same pass as the view's): [name]."""
    try:
        s = spec(x)
    except WaveError:
        return []
    return [s['signal']] if s['kind'] == 'signal' else []


def edge_times(st, kind, t0, t1):
    """The times of the edges (posedge negedge edge) or changes of a stream [(t, value)] in [t0, t1]."""
    out, prev = [], None
    for t, v in st:
        if prev is not None and t0 <= t <= t1:
            rise = (prev == '0' and v in '1xz') or (prev in 'xz' and v == '1')
            fall = (prev == '1' and v in '0xz') or (prev in 'xz' and v == '0')
            if (kind == 'posedge' and rise) or (kind == 'negedge' and fall) or (kind == 'edge' and (rise or fall)) or (kind == 'change' and v != prev):
                out.append(t)
        prev = v
    return out


def norm(value, width):
    import vcd2wavedrom
    return vcd2wavedrom.norm(value, width)


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
        return norm(f"{width}'b{bits.rjust(width, bits[0] if bits[0] in 'xz' else '0')[-width:]}", width)
    try:
        n = int(digits, {'h': 16, 'd': 10, 'b': 2, 'o': 8}[base])
    except ValueError:
        return None
    if width == 1:
        return str(n & 1) if n in (0, 1) else None
    return format(n, 'x').rjust((width + 3) // 4, '0')


def value_at(st, t):
    """The value of a stream at t, after the changes at t."""
    i = bisect.bisect_right(st, (t, '￿')) - 1
    return st[i][1] if i >= 0 else None


def value_times(st, want, width, t0, t1, text):
    """The times a stream becomes want in [t0, t1] (the value itself, or its label: text(v)); already that value at t0:
    t0 is the first match."""
    want = str(want)
    raw = bits_value(want, width)
    hit = lambda v: v is not None and (v == raw or text(v) == want)
    hits, prev = [], value_at(st, t0)
    if hit(prev):
        hits.append(t0)
    for t, v in st[bisect.bisect_right(st, (t0, '￿')):]:
        if t > t1:
            break
        if hit(v) and prev != v:
            hits.append(t)
        prev = v
    return hits


def cover(exe, waves, expr, clock, scope, t0=None, t1=None, edge='posedge', args=(), t_start=None, t_end=None):
    """An SV expression or sequence as `cover property (@(edge clock) expr)` over the dump (sva eval in a temporary
    directory) -> (results document or None, stderr lines). clock: its name under scope."""
    if not exe:
        raise WaveError('an expression needs the sva CLI (make sva-build, or bin/<os>-x86_64/sva)')
    expr = str(expr).strip().rstrip(';')
    with tempfile.TemporaryDirectory(prefix='wavefind-') as d:
        src, out = os.path.join(d, 'find.sv'), os.path.join(d, 'r.json')
        with open(src, 'w', encoding='utf-8') as f:
            f.write(f'wavelens_find: cover property (@({edge} {clock}) {expr});\n')
        cmd = [exe, 'eval', '--waves', waves, '--out', out, '--sva', src] + (['--scope', scope] if scope else [])
        if t0 is not None and (t_start is None or t0 > t_start):
            cmd += ['--from', f'{t0:.0f}ps']
        if t1 is not None and (t_end is None or t1 < t_end):
            cmd += ['--to', f'{t1:.0f}ps']
        r = subprocess.run(cmd + list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL)
        msgs = [l.replace(d + os.sep, '') for l in r.stderr.splitlines() if l.strip() and not re.match(r'sva: \d+ assertions over', l)]
        res = None
        if os.path.isfile(out):
            with open(out, encoding='utf-8') as f:
                res = json.load(f)
    return res, msgs


def cover_hits(res, msgs, scope=''):
    """cover()'s results -> [(start cycle, start ps, end cycle, end ps)] of the matching attempts; an expression that did
    not evaluate, or names it did not find, is a WaveError."""
    if not res or not res.get('assertions'):
        raise WaveError('the expression did not evaluate: ' + ' | '.join(msgs[:6]))
    r = res['assertions'][0]
    if r.get('missing'):
        raise WaveError(f'no {", ".join(r["missing"])} in scope {scope or "(top)"} — give "scope" or full names')
    cyc, u = res.get('cycles') or [], UNIT_PS.get(res.get('unit', 'ps'), 1)
    tm = lambda c: cyc[c] * u if 0 <= c < len(cyc) else None
    return [(x['start'], tm(x['start']), x['end'], tm(x['end'])) for x in r.get('attempts', []) if x.get('result') == 'pass'], r, res


def attempt_times(results, result='fail', point=None):
    """A binding's results document (one assertion) -> the times of its attempts of that result, in order: a fail at its
    failed_at (else its end), a pass at its end; point "start" / "end" / "failed_at" says which."""
    o = results['assertions'][0]
    cyc, u = o.get('cycles') or results.get('cycles') or [], UNIT_PS.get(results.get('unit', 'ps'), 1)
    out = []
    for x in o.get('attempts', []):
        if x.get('result') != result:
            continue
        p = point or ('failed_at' if result == 'fail' else 'end')
        c = x.get(p) if p != 'failed_at' else x.get('failed_at', x.get('end'))
        if c is None:
            c = x.get('end')
        if c is not None and 0 <= c < len(cyc):
            out.append(cyc[c] * u)
    return out


def pick(times, s, where, window=''):
    """The nth of the times (s["nth"]) -> ps; none: a WaveError that names where, what was looked for and where."""
    if len(times) >= s['nth']:
        return times[s['nth'] - 1]
    shown = {k: v for k, v in s.items() if k != 'kind' and not (k == 'nth' and v == 1) and not (k == 'edge' and v == 'change' and 'value' in s)}
    raise WaveError(f'{where}: ' + (f'{len(times)} match(es), no number {s["nth"]}' if times else 'no match') +
                    f' for {json.dumps(shown, ensure_ascii=False)}' + (f' in {window}' if window else ''))
