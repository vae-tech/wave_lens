"""dumpscan.py — read a dump as VCD text: a VCD directly, an FST through GTKWave's `fst2vcd -e` (which also writes the FST
enum tables as `$attrbegin misc 07 …`). Used by vcd2wavedrom.py (the built-in reader, enum labels) and mkconfig.py
(signal list, declaration order, change counts, enums).

read(path, body=…, want=…) -> Dump with
  vars   {path: Var}  every signal under the path wavepeek uses: "mem[1] [7:0]" is "mem.[1]", bit-blasted 1-bit
                      "err[0]".."err[3]" are one vector "err"; Var = width, members [(id code, bit or None)], enum,
                      order, kind (the $var type: wire reg integer … real string event)
  alias  {other spelling: path}  ("mem[1]", "sig[7:0]")
  unit_ps, t_start, t_end (ps; t_* need body), changes {path: value changes} (body='count'),
  trans  {id code: [(time in dump units, raw value bytes)]} for the id codes in `want` (body='collect')
scan(path, body=True) -> {path or alias: {'order', 'changes', 'enum', 'width', 'kind'}} (mkconfig.py, enum lookup).

The reference of a $var (parse_ref, the same rule as the page's wavefw/src/vcd.js): an escaped identifier (\\a.b) is a
name as it is, to its end; a range glued to the name (data[7:0]) or given apart (data [7:0]) is the vector's, not a
child; a 1-bit "err[3]" is a bit of the vector "err"; another "mem[1]" an element of the array "mem" (path "mem.[1]").
The same path under two id codes (a simulator declares some nets twice) is one signal whose changes are merged.

The value changes: one per line as simulators write them, or several on a line (#0 0! b01 "); $comment … $end is
skipped (also over lines); VHDL's nine values are folded into four (U W - X: x, H: 1, L: 0, Z: z). Time must not go
back (a WaveError). A $dumpoff block (every value x) counts as changes in `changes`. Times above 2^53 ps and a
timescale finer than 1 ps get a warning: the page holds times as JavaScript numbers (ps).
"""
import collections, os, re, shutil, subprocess, sys
from typing import Dict, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import TS_RE, UNIT_PS, WaveError  # noqa: E402

Var = collections.namedtuple('Var', 'width members enum order kind', defaults=('wire',))
TEXT_KINDS = ('real', 'string')   # a value that is a text, not bits: "kind" in the WaveJSON, labelled as written
SCALAR = b'01xzXZuUwWhHlL-'
VHDL = bytes.maketrans(b'XZUWHL-uwhl', b'xzxx10xxx10')   # VHDL std_logic -> 0 1 x z


class Dump:
    def __init__(self):
        self.vars, self.alias, self.unit_ps, self.t_start, self.t_end = {}, {}, 1, None, None
        self.changes, self.trans = {}, {}
        self.scopes = {}   # path -> scope type other than module ($scope struct / union / interface …: an FST through fst2vcd)

    def find(self, path):
        return path if path in self.vars else self.alias.get(path)


def available(path):
    return path.lower().endswith('.vcd') or bool(shutil.which('fst2vcd'))


def _lines(path):
    """(line iterator, close function) over the dump as VCD text; None if not possible."""
    if not os.path.isfile(path):
        raise WaveError(f'no such dump: {path}')
    if path.lower().endswith('.vcd'):
        f = open(path, 'rb', buffering=1 << 20)
        return f, f.close
    exe = shutil.which('fst2vcd')
    if not exe:
        print('dumpscan: fst2vcd (GTKWave) not on PATH: cannot read ' + os.path.basename(path) + ' as text', file=sys.stderr)
        return None
    p = subprocess.Popen([exe, '-e', path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=1 << 20)
    return p.stdout, lambda: (p.stdout.close(), p.kill(), p.wait())


def _enum_table(tok):
    """$attrbegin misc 07 NAME COUNT LABEL… VALUE… HANDLE $end -> (handle, {int value: label}); reference form -> (handle, None)."""
    body = [t.decode(errors='replace') for t in tok[3:-1]]
    if len(body) == 2:                       # "" HANDLE: the next $var uses table HANDLE
        return body[1], None
    try:
        n = int(body[1])
    except (IndexError, ValueError):
        return None, None
    labels, values, handle = body[2:2 + n], body[2 + n:2 + 2 * n], body[2 + 2 * n] if len(body) > 2 + 2 * n else None
    table = {}
    for lab, v in zip(labels, values):
        try:
            table[int(v, 2)] = lab
        except ValueError:                   # x/z in an enum value: no label for it
            pass
    return handle, table


def _commands(lines, rest):
    """The header one command per item (`$scope module tb $end`), however the lines break it: several on one line
    (`$upscope $end $upscope $end`), one over several lines. Stops after $enddefinitions; what follows it on the same
    line (`$enddefinitions $end #0 0!`) goes to rest[0]."""
    buf = []
    for line in lines:
        toks = line.split()
        for i, t in enumerate(toks):
            buf.append(t)
            if t == b'$end':
                yield b' '.join(buf)
                if buf[0] == b'$enddefinitions':
                    rest[0] = b' '.join(toks[i + 1:])
                    return
                buf = []


def parse_ref(tok: list) -> tuple:
    """The tokens of a $var after its id code (up to $end) -> (name, range): '\\a.b' -> ('\\a.b', ''), 'data[7:0]' ->
    ('data', '[7:0]'), 'data [7:0]' -> ('data', '[7:0]'), 'mem[1]' -> ('mem[1]', '')."""
    ref = tok[0] if tok else ''
    rng = tok[1] if len(tok) > 1 and tok[1].startswith('[') else ''
    if not ref.startswith('\\') and not rng:
        m = re.fullmatch(r'(.+?)(\[\d+:\d+\])', ref)
        if m:
            ref, rng = m.group(1), m.group(2)
    return ref, rng


def _header(lines, d, path):
    """Declarations up to $enddefinitions -> d.vars / d.alias / d.unit_ps; -> what follows $enddefinitions on its line."""
    scope, n, tables, pending, blasted, rest, done = [], 0, {}, None, {}, [b''], False
    for line in _commands(lines, rest):
        tok = line.split()
        t0 = tok[0]
        if t0 == b'$enddefinitions':
            done = True
            break
        if t0 == b'$timescale':   # one command: _commands joined its lines
            m = TS_RE.search(line)
            d.unit_ps = int(m.group(1)) * UNIT_PS[m.group(2).decode()] if m else 1
        elif t0 == b'$scope' and len(tok) > 2:
            scope.append(tok[2].decode(errors='replace'))
            kind = tok[1].decode(errors='replace').lower()
            if kind not in ('module', '$end'):
                d.scopes['.'.join(scope)] = kind
        elif t0 == b'$upscope' and scope:
            scope.pop()
        elif t0 == b'$attrbegin' and len(tok) > 4 and tok[1] == b'misc' and tok[2] in (b'07', b'7'):
            handle, table = _enum_table(tok)
            if table is None:
                pending = handle
            elif handle is not None:
                tables[handle] = table
        elif t0 == b'$var' and len(tok) > 4:
            kind, size, code = tok[1].decode(errors='replace').lower(), int(tok[2]), tok[3]
            ref, rng = parse_ref([t.decode(errors='replace') for t in tok[4:-1]])
            enum, pending = tables.get(pending), None
            pre = '.'.join(scope) + '.' if scope else ''
            esc = ref.startswith('\\')
            m = None if esc else re.fullmatch(r'(.+)\[(\d+)\]', ref)
            if m and not rng and size == 1 and kind not in TEXT_KINDS + ('event',):  # one bit of a bit-blasted vector
                base = pre + m.group(1)
                blasted.setdefault(base, (n, []))[1].append((code, int(m.group(2))))
                d.alias.setdefault(pre + ref, base)
            else:
                path = pre + ref.replace('[', '.[', 1) if not esc and '[' in ref else pre + ref
                if path not in d.vars:
                    d.vars[path] = Var(size, [(code, None)], enum, n, kind)
                elif all(c != code for c, _ in d.vars[path].members):   # the same path under another code: merged
                    d.vars[path] = d.vars[path]._replace(members=d.vars[path].members + [(code, None)])
                for a in {pre + ref, pre + ref + rng, path + rng} - {path}:
                    d.alias.setdefault(a, path)
            n += 1
    if not done:
        raise WaveError(f'{os.path.basename(path)}: no $enddefinitions: not a VCD, or its header is cut off')
    for base, (order, bits) in blasted.items():
        if base not in d.vars:
            d.vars[base] = Var(max(b for _, b in bits) + 1, bits, None, order)
    return rest[0]


def _tokens(toks, state):
    """The changes of one line token by token (the slow path: a line that is not one change of the usual form) ->
    (b'#', time digits) | (code, value bytes as written); state[0]: inside a $comment (its $end may be lines later)."""
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if state[0]:
            state[0] = t != b'$end'
        elif t[:1] == b'#':
            yield b'#', t[1:]
        elif t[:1] == b'$':
            state[0] = t not in (b'$dumpvars', b'$dumpall', b'$dumpon', b'$dumpoff', b'$end')   # $comment and the like: to $end
        elif t[:1] in b'bBrRsS':
            if i + 1 < n:
                yield toks[i + 1], t
                i += 1
        elif t[:1] and t[:1] in SCALAR:
            yield t[1:], t[:1]
        i += 1


def read(path: str, body: Optional[str] = 'count', want: Optional[Iterable[bytes]] = None) -> Optional[Dump]:
    """body: None (declarations only), 'count' (value changes per signal), 'collect' (transitions of the id codes in want)."""
    src = _lines(path)
    if src is None:
        return None
    lines, close = src
    d = Dump()
    name = os.path.basename(path)
    try:
        first = _header(lines, d, path)
        if body == 'count':
            cnt = collections.Counter()
            t_first, t_last = _scan(lines, first, name, cnt, None)
            for p, v in d.vars.items():
                d.changes[p] = sum(max(0, cnt[code] - 1) for code, _ in v.members)
            d.t_start, d.t_end = (t_first or 0) * d.unit_ps, (t_last or 0) * d.unit_ps
        elif body == 'collect':
            tr = d.trans = {code: [] for code in set(want or ())}
            t_first, t_last = _scan(lines, first, name, None, tr)
            d.t_start, d.t_end = (t_first or 0) * d.unit_ps, (t_last or 0) * d.unit_ps
    finally:
        close()
    if body and d.t_end and d.t_end > 2 ** 53:
        print(f'dumpscan: {name}: times above 2^53 ps ({d.t_end:.0f}): the page holds times as JavaScript numbers, '
              'they are rounded there', file=sys.stderr)
    if body and d.unit_ps < 1:
        print(f'dumpscan: {name}: timescale finer than 1 ps: the page and the sva CLI count in ps, times are rounded there', file=sys.stderr)
    return d


def _scan(lines, first, name, cnt, tr):
    """The value changes: counted per id code into cnt, or kept as (time in dump units, value bytes) in tr[code] for
    the codes tr has; -> (first time, last time). Values as stored: b'0' / b'1' / b'x' / b'z' (a bit), the digits of a
    vector without its b (b'0101'), b'r1.5' (a real), b'sHello' (a string). The usual one change per line is read
    here directly, one loop for counting and one for collecting (2-3 s on a 24 MB dump); a line of another form goes
    through _tokens."""
    st = {'t': 0, 'first': None}
    def at(v):
        tn = int(v)
        if tn < st['t']:
            raise WaveError(f'{name}: time goes back: #{tn} after #{st["t"]} (a VCD lists its times in order)')
        st['t'] = tn
        if st['first'] is None:   # values before the first time (a $dumpvars block): the dump starts at 0
            st['first'] = 0 if (cnt if cnt is not None else any(tr.values())) else tn
    def slow(line):
        state = [False]
        for code, v in _tokens(line.split(), state):
            if code == b'#':
                at(v)
                continue
            c = v[:1]
            v = v[1:] if c in b'bB' else c.lower() + v[1:] if c in b'rRsS' else c.translate(VHDL)
            if cnt is not None:
                cnt[code] += 1
            else:
                q = tr.get(code)
                if q is not None:
                    q.append((st['t'], v))
        if state[0]:   # a $comment that goes on: up to its $end
            for l2 in lines:
                if b'$end' in l2:
                    slow(l2[l2.index(b'$end') + 4:])
                    break
    def odd(l):   # a line the loops do not read directly; the time may have moved
        slow(l)
        return st['t']
    if first:
        slow(first)
    t = st['t']
    if cnt is not None:   # a change line with more after it is counted under a key with spaces: taken apart below
        for l in lines:
            c = l[:1]
            if c in b'01xzXZ' and c:
                cnt[l[1:].rstrip()] += 1
            elif c == b'#':
                s = l.strip()
                if b' ' in s or b'\t' in s:
                    t = odd(s)
                else:
                    at(s[1:])
            elif c in b'bBrRsS' and c:
                cnt[l.partition(b' ')[2].rstrip()] += 1
            elif c == b'$':   # $dumpvars / $end alone, or a $comment, or "$dumpvars 0! $end"
                if l.strip() not in (b'$dumpvars', b'$dumpall', b'$dumpon', b'$dumpoff', b'$end'):
                    t = odd(l)
            elif c and c in SCALAR:
                t = odd(l)   # VHDL's U W H L -
        for key in [k for k in cnt if b' ' in k or b'\t' in k or not k]:
            n, toks = cnt.pop(key), key.split()
            if toks:
                cnt[toks[0]] += n
                for code, v in _tokens(toks[1:], [False]):
                    if code != b'#':   # (a time inside such a line only moves the counts' window: left out)
                        cnt[code] += n
    else:
        for l in lines:
            c = l[:1]
            if c == b'#':
                s = l.strip()
                if b' ' in s or b'\t' in s:
                    t = odd(s)
                else:
                    at(s[1:])
                    t = st['t']
            elif c in b'01xzXZ':
                code = l[1:].rstrip()
                q = tr.get(code)
                if q is not None:
                    q.append((t, c))
                elif b' ' in code:   # more on this line: the slow path
                    t = odd(l)
            elif c in b'bBrRsS':
                v, _, code = l[1:].partition(b' ')
                code = code.rstrip()
                q = tr.get(code)
                if q is not None:
                    q.append((t, v if c in b'bB' else c.lower() + v))
                elif not code or b' ' in code:
                    t = odd(l)
            elif c == b'$':
                if l.strip() not in (b'$dumpvars', b'$dumpall', b'$dumpon', b'$dumpoff', b'$end'):
                    t = odd(l)
            elif c and c in SCALAR:
                t = odd(l)
    return st['first'], (st['t'] if st['first'] is not None else None)


def scan(path: str, body: bool = True) -> Dict[str, dict]:
    """{path or alias: {order, changes, enum, width, kind}} of every variable ({} when the dump cannot be read as text)."""
    d = read(path, 'count' if body else None)
    if d is None:
        return {}
    info = {p: {'order': v.order, 'changes': d.changes.get(p) if body else None, 'enum': v.enum, 'width': v.width, 'kind': v.kind} for p, v in d.vars.items()}
    for a, p in d.alias.items():
        info.setdefault(a, info[p])
    return info
