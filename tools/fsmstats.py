#!/usr/bin/env python3
"""fsmstats.py — the states of an FSM in a dump, from the shell and in CI: how often each state is entered, how long it is held,
the share of the time, the first entry; the states of its table never reached; the values that are no state (x, z, a code
without a label); its changes by how often. The rule of the page's FSM panel (wavelens/src/fsm.js fsmStats): an entry is a
change of the value, a state is held until the next change (the last one to the end of the window).

    python3 -I tools/fsmstats.py tb.vcd --signal u_ctl.state                 # the table of the FST, or tb.types.json beside it
    python3 -I tools/fsmstats.py tb.vcd --signal state --enum tb.u.state=0:IDLE,1:RUN,2:DONE --json
    python3 -I tools/fsmstats.py tb.fst --signal u_ctl.state --strict         # exit 1 when a state is never reached (CI)

The table of states: the dump's (an FST's enum), --types FILE (svtypes.py / Questa's), the types file beside the dump, or
--enum PATH=K:LABEL,…; none: an error. --from / --to: the window (a time with a unit). Exit 0; 1 with --strict when a state is
never reached; 2 an error.
"""
import argparse, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WaveError, run_main  # noqa: E402


def key_of(v, width):
    """A value of a stream (hex, "'b" bits with x / z, a nibble x / z, a bit 0 1 x z) -> its key: the decimal of its code, 'x', 'z'."""
    if v is None:
        return 'x'
    v = str(v).lower()
    bits = v[2:] if v.startswith("'b") else v if width == 1 else None
    if bits is not None:
        if 'x' in bits:
            return 'x'
        if 'z' in bits:
            return 'z'
        return str(int(bits, 2)) if width > 1 or v.startswith("'b") else bits
    if re.search('[xz]', v):
        return 'x' if 'x' in v else 'z'
    return str(int(v, 16))


def stats(stream, width, table, t0, t1):
    """The states of a stream [(t, value)] in [t0, t1] with a table {code: label} -> {states, never, invalid, changes}: each state of the
    table with its entries, first entry, time held and share; the values of no state; the changes, the most frequent first (fsm.js)."""
    tab = {str(k): str(x) for k, x in (table or {}).items()}
    seq = []
    before = None
    for t, v in stream:
        k = key_of(v, width)
        if t <= t0:
            before = k
            continue
        if t > t1:
            break
        if not seq and before is None and t > t0:
            seq.append((t0, 'x'))   # no value yet when the window starts: x until the first one (as the page counts it)
        if seq and seq[-1][1] == k:
            continue
        if not seq and before is not None and t > t0:
            seq.append((t0, before))   # the value the window starts with
            if before == k:
                continue
        seq.append((t, k))
    if not seq and before is not None:
        seq.append((t0, before))
    vals, trans = {}, {}
    for i, (t, k) in enumerate(seq):
        s = vals.setdefault(k, {'entries': 0, 'first': t, 'time': 0})
        s['entries'] += 1
        s['time'] += max(0, (seq[i + 1][0] if i + 1 < len(seq) else t1) - t)
        if i:
            x = trans.setdefault((seq[i - 1][1], k), {'count': 0, 'first': t})
            x['count'] += 1
    whole = max(t1 - t0, 0)
    name = lambda k: tab.get(k, 'X' if k == 'x' else 'Z' if k == 'z' else f'{k} (no label)')
    row = lambda k, s: {'state': name(k), 'value': k, 'entries': s['entries'], 'first': s['first'], 'time': s['time'],
                        'share': round(s['time'] / whole, 6) if whole else 0}
    return {'states': [row(k, vals[k]) if k in vals else {'state': x, 'value': k, 'entries': 0, 'first': None, 'time': 0, 'share': 0}
                       for k, x in tab.items()],
            'never': [x for k, x in tab.items() if k not in vals],
            'invalid': [row(k, s) for k, s in vals.items() if k not in tab],
            'changes': sorted(({'from': name(a), 'to': name(b), 'count': x['count'], 'first': x['first']} for (a, b), x in trans.items()),
                              key=lambda x: (-x['count'], x['first']))}


def parse_enum(text):
    """--enum PATH=K:LABEL,… -> (path, {int: label})."""
    path, _, body = str(text).partition('=')
    if not body:
        raise WaveError(f'--enum {text}: PATH=K:LABEL,… (0:IDLE,1:RUN)')
    out = {}
    for item in body.split(','):
        k, _, x = item.partition(':')
        try:
            out[int(k, 0)] = x.strip()
        except ValueError:
            raise WaveError(f'--enum: "{item}" is no K:LABEL') from None
    return path.strip(), out


def of_dump(w, signal, enum=None, frm=None, to=None, scope=''):
    """The statistics of signal in a dump read (wavemcp.Wave) -> (path, its stats, times in ps)."""
    p, sl = w.find(signal, scope)
    width = w.width(p, sl)
    table = enum if enum is not None else (None if sl else w.decl.vars[p].enum)
    if not table:
        raise WaveError(f'no state table for {p}: give --types (svtypes.py) or --enum {p}=0:IDLE,1:RUN')
    w.load([p])
    whole = lambda t: int(t) if float(t).is_integer() else t
    t0 = whole(w.t_start if frm is None else frm)
    t1 = whole(w.t_end if to is None else to)
    return p, stats(w.stream(p, sl), width, table, t0, t1)


def text(p, s, ns):
    out = [f'{p}: {len(s["states"])} states, {len(s["never"])} never reached' + (f', {len(s["invalid"])} values of no state' if s['invalid'] else '')]
    w = max([len(x['state']) for x in s['states'] + s['invalid']] + [5])
    for x in s['states'] + s['invalid']:
        out.append(f'  {x["state"]:<{w}}  {x["entries"]:>6} entries  {ns(x["time"]):>14}  {x["share"] * 100:5.1f}%  ' +
                   (f'first {ns(x["first"])}' if x['first'] is not None else 'never'))
    for c in s['changes'][:20]:
        out.append(f'  {c["from"]} → {c["to"]}: {c["count"]}, first {ns(c["first"])}')
    return '\n'.join(out)


def main():
    try:
        return run()
    except WaveError as e:   # a wrong name, no table, a dump that does not read: 2, apart from --strict's 1
        print(f'fsmstats: {e}', file=sys.stderr)
        return 2


def run():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('dump', help='a VCD or FST')
    ap.add_argument('--signal', required=True, help='the FSM\'s state signal: a path, a name, the end of a path')
    ap.add_argument('--scope', default='', help='the names under this scope')
    ap.add_argument('--types', help='a types file (svtypes.py, Questa\'s wavelens_types): the state names (default: the one beside the dump)')
    ap.add_argument('--enum', help='PATH=K:LABEL,…: the state names given here')
    ap.add_argument('--from', dest='frm', help='the window\'s start (a time with a unit)')
    ap.add_argument('--to', help='the window\'s end')
    ap.add_argument('--json', action='store_true', help='the statistics as JSON (times in ps)')
    ap.add_argument('--strict', action='store_true', help='exit 1 when a state of the table is never reached (a CI gate of FSM coverage)')
    a = ap.parse_args()
    import wavemcp   # the dump's reader with its types (the MCP server's, read once)
    w = wavemcp.wave(a.dump, {'types': a.types} if a.types else {})
    enum = None
    if a.enum:
        ep, enum = parse_enum(a.enum)
        if w.find(ep, a.scope)[0] != w.find(a.signal, a.scope)[0]:
            raise WaveError(f'--enum is of {ep}, --signal {a.signal}: one signal')
    def ps(x, what):   # a time with its unit (a bare number is not one here: "10" would be ns to MCP, ticks to a reader)
        if x is None:
            return None
        if re.fullmatch(r'\s*-?\d+(\.\d+)?\s*', str(x)):
            raise WaveError(f'--{what} {x}: a time with a unit (10ns, 2.5us)')
        return wavemcp.ps_of(x, what)
    t0, t1 = ps(a.frm, 'from'), ps(a.to, 'to')
    if t0 is not None and t1 is not None and t1 <= t0:
        raise WaveError(f'--from {a.frm} --to {a.to}: the window ends before it starts')
    p, s = of_dump(w, a.signal, enum, t0, t1, a.scope)
    if a.json:   # times as whole ps where they are whole (the page's)
        whole = lambda v: int(v) if isinstance(v, float) and v.is_integer() else v
        for x in s['states'] + s['invalid'] + s['changes']:
            for k in ('first', 'time'):
                if k in x:
                    x[k] = whole(x[k])
        print(json.dumps({'signal': p, 'unit': 'ps', **s}, ensure_ascii=False, indent=1))
    else:
        print(text(p, s, lambda t: f'{wavemcp.ns(t):g} ns'))
    if s['never']:
        print(f'fsmstats: {p} never enters {", ".join(s["never"])}', file=sys.stderr)
    return 1 if a.strict and s['never'] else 0


if __name__ == '__main__':
    sys.exit(run_main(main, 'fsmstats'))
