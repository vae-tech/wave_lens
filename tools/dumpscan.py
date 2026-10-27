"""dumpscan.py — read a dump as VCD text: a VCD directly, an FST through GTKWave's `fst2vcd -e`, else through the sva
CLI's `sva vcd` (the same text; both write the FST enum tables as `$attrbegin misc 07 …`). WAVELENS_FST=sva or fst2vcd
picks one. Used by vcd2wavedrom.py (the built-in reader, enum labels) and mkconfig.py
(signal list, declaration order, change counts, enums).

read(path, body=…, want=…) -> Dump with
  vars   {path: Var}  every signal under its full path: "mem[1] [7:0]" is "mem.[1]", bit-blasted 1-bit
                      "err[0]".."err[3]" are one vector "err"; Var = width, members [(id code, None: the whole value,
                      or (msb, lsb): its bits in the vector, bit 0 the vector's last)], enum, order, kind (the $var
                      type: wire reg integer … real realtime shortreal string event)
  alias  {other spelling: path}  ("mem[1]", "sig[7:0]")
  unit_ps, t_start, t_end (ps; t_* need body), changes {path: value changes} (body='count'),
  trans  {id code: [(time in dump units, raw value bytes)]} for the id codes in `want` (body='collect')
scan(path, body=True) -> {path or alias: {'order', 'changes', 'enum', 'width', 'kind'}} (mkconfig.py, enum lookup).

The reference of a $var (parse_ref, the same rule as the page's wavelens/src/vcd.js): an escaped identifier (\\a.b) is a
name as it is, to its end; a range glued to the name (data[7:0]) or given apart (data [7:0]) is the vector's, not a
child; a 1-bit "err[3]" is a bit of the vector "err"; another "mem[1]" an element of the array "mem" (path "mem.[1]").
The same path under two id codes with the same range (a simulator declares some nets twice) is one signal whose changes
are merged. A path declared in parts (the bits "err[0]" "err[1]", or ranges apart "err [0]" "err [1]", "data [7:0]"
"data [15:8]") is one vector from its lowest declared index to its highest (bits not declared: x), merged bit by bit;
an ascending range ([0:3] [4:7]) keeps index 0 on the left. real, realtime, shortreal, real_parameter and string are
texts (TEXT_KINDS: their "kind" real / string); a size 0 (a string as fst2vcd writes it) is 1.

The value changes: tokens apart by any white space, as the page reads them — one per line as simulators write them,
several on a line (#0 0! b01 "), indented, a vector's id code on the next line; $comment … $end is skipped (also over
lines); VHDL's nine values are folded into four (U W - X: x, H: 1, L: 0, Z: z). Time must not go
back (a WaveError). A $dumpoff block (every value x) counts as changes in `changes`. Times above 2^53 ps and a
timescale finer than 1 ps get a warning: the page holds times as JavaScript numbers (ps).
"""
import collections, os, re, shutil, subprocess, sys, tempfile
from typing import Dict, Iterable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import TS_RE, UNIT_PS, WaveError  # noqa: E402

Var = collections.namedtuple('Var', 'width members enum order kind', defaults=('wire',))
TEXT_KINDS = {'real': 'real', 'realtime': 'real', 'shortreal': 'real', 'real_parameter': 'real', 'string': 'string'}
# ^ a $var type whose value is a text, not bits -> its "kind" in the WaveJSON (labelled as written)
SCALAR = b'01xzXZuUwWhHlL-'
VHDL = bytes.maketrans(b'XZUWHL-uwhl', b'xzxx10xxx10')   # VHDL std_logic -> 0 1 x z


class Dump:
    def __init__(self):
        self.vars, self.alias, self.unit_ps, self.t_start, self.t_end = {}, {}, 1, None, None
        self.changes, self.trans = {}, {}
        self.scopes = {}   # path -> scope type other than module ($scope struct / union / interface …: an FST as VCD text)
        self.modules = set()   # the paths of every $scope module (the instances the dump has)
        self.date = None   # its $date, as written

    def find(self, path):
        return path if path in self.vars else self.alias.get(path)


def fst_reader():
    """The command that writes an FST as VCD text: [fst2vcd, -e], else [sva, vcd] (the CLI of this repository), or None.
    WAVELENS_FST=sva / fst2vcd: that one only."""
    want = os.environ.get('WAVELENS_FST', '')
    exe = shutil.which('fst2vcd') if want in ('', 'fst2vcd') else None
    if exe:
        return [exe, '-e']
    if want in ('', 'sva'):
        import svabuild   # here: svabuild imports this module
        sva = svabuild.find_bin()
        if sva:
            return [sva, 'vcd']
    return None


def fst_tool():
    """The name of fst_reader() for the WaveJSON's "meta": 'fst2vcd', 'sva vcd' or ''."""
    r = fst_reader()
    return '' if not r else 'fst2vcd' if os.path.basename(r[0]).startswith('fst2vcd') else 'sva vcd'


def available(path):
    return path.lower().endswith('.vcd') or fst_reader() is not None


def _lines(path):
    """(line iterator, close function, done function) over the dump as VCD text; None if not possible. done() after the
    text was read to its end: an FST's converter that failed (a partial text, then an error) raises WaveError with the
    end of what it said; a read that stops early (the declarations only) does not call it."""
    if not os.path.isfile(path):
        raise WaveError(f'no such dump: {path}')
    if path.lower().endswith('.vcd'):
        f = open(path, 'rb', buffering=1 << 20)
        return f, f.close, lambda: None
    argv = fst_reader()
    if not argv:
        print('dumpscan: neither fst2vcd (GTKWave) nor the sva CLI found: cannot read ' + os.path.basename(path) + ' as text', file=sys.stderr)
        return None
    err = tempfile.TemporaryFile()   # a file, not a pipe: a converter that says much cannot block on it
    p = subprocess.Popen(argv + [path], stdout=subprocess.PIPE, stderr=err, bufsize=1 << 20)

    def close():
        p.stdout.close(); p.kill(); p.wait(); err.close()

    def done():
        if p.wait() != 0:
            err.seek(0, os.SEEK_END)
            err.seek(max(0, err.tell() - 2000))   # its end only: a converter may say a great deal
            said = err.read().decode(errors='replace').strip()
            raise WaveError(f'{os.path.basename(argv[0])} {os.path.basename(path)}: exit {p.returncode}' + (f': {said}' if said else '') +
                            ' (the dump is cut off, or not an FST it reads)')
    return p.stdout, close, done


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
    scope, n, tables, pending, rest, done = [], 0, {}, None, [b''], False
    decls = {}   # path -> [(code, (msb, lsb) or None, size, kind, enum, order, a bit glued to the name, aliases)]
    for line in _commands(lines, rest):
        tok = line.split()
        t0 = tok[0]
        if t0 == b'$enddefinitions':
            done = True
            break
        if t0 == b'$timescale':   # one command: _commands joined its lines
            m = TS_RE.search(line)
            d.unit_ps = int(m.group(1)) * UNIT_PS[m.group(2).decode()] if m else 1
        elif t0 == b'$date':
            d.date = b' '.join(tok[1:-1] if tok[-1] == b'$end' else tok[1:]).decode(errors='replace') or None
        elif t0 == b'$scope' and len(tok) > 2:
            scope.append(tok[2].decode(errors='replace'))
            kind = tok[1].decode(errors='replace').lower()
            if kind not in ('module', '$end'):
                d.scopes['.'.join(scope)] = kind
            else:
                d.modules.add('.'.join(scope))
        elif t0 == b'$upscope' and scope:
            scope.pop()
        elif t0 == b'$attrbegin' and len(tok) > 4 and tok[1] == b'misc' and tok[2] in (b'07', b'7'):
            handle, table = _enum_table(tok)
            if table is None:
                pending = handle
            elif handle is not None:
                tables[handle] = table
        elif t0 == b'$var' and len(tok) > 4:
            kind, code = tok[1].decode(errors='replace').lower(), tok[3]
            size = int(tok[2]) if tok[2].isdigit() else 0
            size = size or 1   # a string's size 0 (fst2vcd, sva vcd): one value, as the page reads it
            ref, rng = parse_ref([t.decode(errors='replace') for t in tok[4:-1]])
            enum, pending = tables.get(pending), None
            pre = '.'.join(scope) + '.' if scope else ''
            esc = ref.startswith('\\')
            m = None if esc else re.fullmatch(r'(.+)\[(\d+)\]', ref)
            if m and not rng and size == 1 and kind not in TEXT_KINDS and kind != 'event':  # one bit of a bit-blasted vector
                decls.setdefault(pre + m.group(1), []).append((code, (int(m.group(2)),) * 2, 1, kind, None, n, True, {pre + ref}))
            else:
                path = pre + ref.replace('[', '.[', 1) if not esc and '[' in ref else pre + ref
                r = re.fullmatch(r'\[(\d+)(?::(\d+))?\]', rng)
                part = (int(r.group(1)), int(r.group(2) or r.group(1))) if r else None
                decls.setdefault(path, []).append((code, part, size, kind, enum, n, False, {pre + ref, pre + ref + rng, path + rng} - {path}))
            n += 1
    if not done:
        raise WaveError(f'{os.path.basename(path)}: no $enddefinitions: not a VCD, or its header is cut off')
    for p, ds in decls.items():
        _, part0, size0, kind0, enum0, order0 = ds[0][:6]
        if not any(x[6] for x in ds) and all(x[1] == part0 for x in ds):   # one range (or none): the other codes alias it
            members = list(dict.fromkeys((x[0], None) for x in ds))
            d.vars[p] = Var(size0, members, enum0, order0, kind0)
            for x in ds:
                for a in sorted(x[7]):
                    d.alias.setdefault(a, p)
            continue
        # a vector in parts (bits glued "err[0]" "err[1]", ranges apart "data [7:0]" "data [15:8]"): one vector from the
        # lowest index to the highest (as wellen merges them), bits not declared x; ascending ranges ([0:3] [4:7]) keep
        # their direction; members (code, (msb, lsb)) count from bit 0 of the vector
        parts = [(x[0], x[1] or (x[2] - 1, 0)) for x in ds]
        lo, hi = min(min(q) for _, q in parts), max(max(q) for _, q in parts)
        asc = any(q[0] < q[1] for _, q in parts)
        pos = (lambda i: hi - i) if asc else (lambda i: i - lo)
        members = list(dict.fromkeys((c, (pos(q[0]), pos(q[1]))) for c, q in parts))
        d.vars[p] = Var(hi - lo + 1, members, enum0, order0, kind0)
        for x in ds:
            if x[6]:
                d.alias.setdefault(next(iter(x[7])), p)
        d.alias.setdefault(p + (f'[{lo}:{hi}]' if asc else f'[{hi}:{lo}]'), p)
    return rest[0]


DUMP_KW = (b'$dumpvars', b'$dumpall', b'$dumpon', b'$dumpoff', b'$end')


def _widths(d):
    """id code -> its widest size (a text 0), as the page's reader keeps them: for _glued."""
    out = {}
    for v in d.vars.values():
        for code, part in v.members:
            w = 0 if v.kind in TEXT_KINDS else abs(part[0] - part[1]) + 1 if part else v.width
            out[code] = max(out.get(code, 0), w)
    return out


def _glued(tok, widths):
    """A vector without its b, glued to its id code (Questa 2023 writes an integer so: 0000…0001A& is 1 of A&): when the
    token is no bit of a declared code, the length of the digits of a code declared that wide (the longest first), else
    of any declared code (an enum at its own width: the value cut to it) -> where its code starts; 0: a bit and its
    code as usual (sva fst glued and the page's reader: the same)."""
    if len(tok) < 3 or tok[1:] in widths:
        return 0
    run = 0
    while run < len(tok) - 1 and tok[run] in b'01xzXZ':
        run += 1
    return next((j for j in range(run, 1, -1) if widths.get(tok[j:]) == j), 0) or next((j for j in range(run, 1, -1) if tok[j:] in widths), 0)


def read(path: str, body: Optional[str] = 'count', want: Optional[Iterable[bytes]] = None) -> Optional[Dump]:
    """body: None (declarations only), 'count' (value changes per signal), 'collect' (transitions of the id codes in want)."""
    src = _lines(path)
    if src is None:
        return None
    lines, close, done = src
    d = Dump()
    name = os.path.basename(path)
    try:
        first = _header(lines, d, path)
        widths, last = _widths(d), _last_word(path)
        if body == 'count':
            cnt = collections.Counter()
            span = _scan(lines, first, name, cnt, None, widths=widths, last=last)
            if span is None:   # a change line with more on it: the dump again, every line token by token
                close()
                lines, close, done = _lines(path)
                first, cnt = _header(lines, Dump(), path), collections.Counter()
                span = _scan(lines, first, name, cnt, None, fast=False, widths=widths, last=last)
            done()
            for k in [k for k in cnt if k not in widths]:   # a glued vector counted under its bit's code: its own
                j = _glued(b'0' + k, widths)
                if j:
                    cnt[(b'0' + k)[j:]] += cnt.pop(k)
            t_first, t_last = span
            for p, v in d.vars.items():
                d.changes[p] = sum(max(0, cnt[code] - 1) for code in dict.fromkeys(c for c, _ in v.members))
            d.t_start, d.t_end = (t_first or 0) * d.unit_ps, (t_last or 0) * d.unit_ps
        elif body == 'collect':
            tr = d.trans = {code: [] for code in set(want or ())}
            t_first, t_last = _scan(lines, first, name, None, tr, widths=widths, last=last)
            done()
            d.t_start, d.t_end = (t_first or 0) * d.unit_ps, (t_last or 0) * d.unit_ps
    finally:
        close()
    if body and d.t_end and d.t_end > 2 ** 53:
        print(f'dumpscan: {name}: times above 2^53 ps ({d.t_end:.0f}): the page holds times as JavaScript numbers, '
              'they are rounded there', file=sys.stderr)
    if body and d.unit_ps < 1:
        print(f'dumpscan: {name}: timescale finer than 1 ps: the page and the sva CLI count in ps, times are rounded there', file=sys.stderr)
    return d


def _last_word(path):
    """The last word of a VCD's text (None for an FST, read through a converter): a time there that goes back is the
    dump cut off, not an error (_scan)."""
    if not path.lower().endswith('.vcd'):
        return None
    with open(path, 'rb') as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 256))
        words = f.read().split()
    return words[-1] if words else None


def _scan(lines, first, name, cnt, tr, fast=True, widths=None, last=None):
    """The value changes: counted per id code into cnt, or kept as (time in dump units, value bytes) in tr[code] for
    the codes tr has; -> (first time, last time). Values as stored: b'0' / b'1' / b'x' / b'z' (a bit), the digits of a
    vector without its b (b'0101'), b'r1.5' (a real), b'sHello' (a string). The usual line, one change or one time
    alone, is read here directly, one loop for counting and one for collecting (3 s on a 24 MB dump); any other line
    (indented, several changes, a $comment, VHDL's U W H L -) goes through slow(): the same tokens, also over the next
    lines while a vector waits for its id code (b0101 then " on the next line) or a $comment for its $end. Counting
    looks for white space in a code only at the end (a test per line costs a third more): a code with white space
    (a line "0! #5 1!") -> None, read() counts again with fast=False, every line through slow(). widths: the codes'
    sizes, for a vector glued to its code (_glued; counting puts it right afterwards, in read()). last: the file's last
    word (_last_word)."""
    widths = widths or {}
    st = {'t': 0, 'first': None}
    def at(v):
        tn = int(v)
        if tn < st['t']:
            if last == b'#' + v:   # the last word of the file: a time cut short (still being written), left out
                print(f'dumpscan: {name}: #{tn} after #{st["t"]} at the end of the file (cut off: still being written? vcd flush, '
                      'or quit vsim): left out', file=sys.stderr)
                return
            raise WaveError(f'{name}: time goes back: #{tn} after #{st["t"]} (a VCD lists its times in order)')
        st['t'] = tn
        if st['first'] is None:   # values before the first time (a $dumpvars block): the dump starts at 0
            st['first'] = 0 if (cnt if cnt is not None else any(tr.values())) else tn
    def put(code, v):   # v as written: b'0', b'U', b'b0101', b'r1.5', b'sHello'
        if cnt is not None:
            cnt[code] += 1
            return
        q = tr.get(code)
        if q is not None:
            c = v[:1]
            q.append((st['t'], v[1:] if c in b'bB' else c.lower() + v[1:] if c in b'rRsS' else c.translate(VHDL)))
    def slow(line):
        toks, i, val, com = line.split(), 0, None, False
        while True:
            if i == len(toks):
                if val is None and not com:
                    return
                line = next(lines, None)
                if line is None:
                    return
                toks, i = line.split(), 0
                continue
            tk = toks[i]
            i += 1
            if com:
                com = tk != b'$end'
            elif val is not None:   # the id code of a vector, a real, a string
                put(tk, val)
                val = None
            else:
                c = tk[:1]
                if c == b'#':
                    at(tk[1:])
                elif c == b'$':
                    com = tk not in DUMP_KW   # $comment and the like: to their $end
                elif c in b'bBrRsS':
                    val = tk
                elif c in SCALAR:
                    j = _glued(tk, widths) if cnt is None else 0
                    if j:
                        put(tk[j:], b'b' + tk[:j])
                    else:
                        put(tk[1:], c)
    if first:
        slow(first)
    if not fast:
        for l in lines:
            slow(l)
    elif cnt is not None:
        for l in lines:
            c = l[:1]
            if c in b'01xzXZ':
                cnt[l[1:].rstrip()] += 1
            elif c == b'#':
                s = l.rstrip()
                if b' ' in s or b'\t' in s:
                    slow(l)
                else:
                    at(s[1:])
            elif c in b'bBrRsS':
                v, _, k = l.partition(b' ')
                k = k.rstrip()
                if k and b'\t' not in v:
                    cnt[k] += 1
                else:   # b0101\t" or its code on the next line
                    slow(l)
            elif c != b'$' or l.strip() not in DUMP_KW:
                slow(l)
        if any(b' ' in k or b'\t' in k for k in cnt):
            return None
    else:
        t = st['t']
        for l in lines:
            c = l[:1]
            if c in b'01xzXZ':
                code = l[1:].rstrip()
                q = tr.get(code)
                if q is not None:
                    q.append((t, c))
                elif b' ' in code or b'\t' in code:
                    slow(l)
                    t = st['t']
                elif code not in widths:   # a vector glued to its code (_glued)
                    j = _glued(c + code, widths)
                    q = tr.get(code[j - 1:]) if j else None
                    if q is not None:
                        q.append((t, (c + code)[:j]))
            elif c == b'#':
                s = l.rstrip()
                if b' ' in s or b'\t' in s:
                    slow(l)
                else:
                    at(s[1:])
                t = st['t']
            elif c in b'bBrRsS':
                v, _, code = l[1:].partition(b' ')
                code = code.rstrip()
                if not code or b' ' in code or b'\t' in code or b'\t' in v:
                    slow(l)
                    t = st['t']
                else:
                    q = tr.get(code)
                    if q is not None:
                        q.append((t, v if c in b'bB' else c.lower() + v))
            elif c != b'$' or l.strip() not in DUMP_KW:
                slow(l)
                t = st['t']
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
