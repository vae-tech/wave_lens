"""dumpscan.py — read a dump as VCD text: a VCD directly, an FST through GTKWave's `fst2vcd -e` (which also writes the FST
enum tables as `$attrbegin misc 07 …`). Used by vcd2wavedrom.py (the built-in reader, enum labels) and mkconfig.py
(signal list, declaration order, change counts, enums).

read(path, body=…, want=…) -> Dump with
  vars   {path: Var}  every signal under the path wavepeek uses: "mem[1] [7:0]" is "mem.[1]", bit-blasted 1-bit
                      "err[0]".."err[3]" are one vector "err"; Var = width, members [(id code, bit or None)], enum, order
  alias  {other spelling: path}  ("mem[1]", "sig[7:0]")
  unit_ps, t_start, t_end (ps; t_* need body), changes {path: value changes} (body='count'),
  trans  {id code: [(time in dump units, raw value bytes)]} for the id codes in `want` (body='collect')
scan(path, body=True) -> {path or alias: {'order', 'changes', 'enum'}} (mkconfig.py, enum lookup).
"""
import collections, os, re, shutil, subprocess, sys

UNIT_PS = {'zs': 1e-9, 'as': 1e-6, 'fs': 1e-3, 'ps': 1, 'ns': 1e3, 'us': 1e6, 'ms': 1e9, 's': 1e12}
Var = collections.namedtuple('Var', 'width members enum order')


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


def _commands(lines):
    """The header one command per item (`$scope module tb $end`), however the lines break it: several on one line
    (`$upscope $end $upscope $end`), one over several lines. Stops after $enddefinitions."""
    buf = []
    for line in lines:
        for t in line.split():
            buf.append(t)
            if t == b'$end':
                yield b' '.join(buf)
                if buf[0] == b'$enddefinitions':
                    return
                buf = []


def _header(lines, d):
    """Declarations up to $enddefinitions -> d.vars / d.alias / d.unit_ps."""
    scope, n, tables, pending, blasted, ts = [], 0, {}, None, {}, None
    for line in _commands(lines):
        tok = line.split()
        if not tok:
            continue
        t0 = tok[0]
        if ts is not None:                   # $timescale spread over lines
            ts += b' ' + line.strip()
            if b'$end' in line:
                m = re.search(rb'(\d+)\s*(zs|as|fs|ps|ns|us|ms|s)\b', ts)
                d.unit_ps = int(m.group(1)) * UNIT_PS[m.group(2).decode()] if m else 1
                ts = None
            continue
        if t0 == b'$enddefinitions':
            break
        if t0 == b'$timescale':
            ts = b''
            rest = line.strip()[len(b'$timescale'):]
            if rest:
                ts = rest
                if b'$end' in rest:
                    m = re.search(rb'(\d+)\s*(zs|as|fs|ps|ns|us|ms|s)\b', ts)
                    d.unit_ps = int(m.group(1)) * UNIT_PS[m.group(2).decode()] if m else 1
                    ts = None
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
            size, code, ref = int(tok[2]), tok[3], tok[4].decode(errors='replace')
            rng = tok[5].decode() if len(tok) > 6 and tok[5].startswith(b'[') else ''
            enum, pending = tables.get(pending), None
            pre = '.'.join(scope) + '.' if scope else ''
            m = re.fullmatch(r'(.+)\[(\d+)\]', ref)
            if m and not rng and size == 1:  # one bit of a bit-blasted vector
                base = pre + m.group(1)
                blasted.setdefault(base, (n, []))[1].append((code, int(m.group(2))))
                d.alias.setdefault(pre + ref, base)
            else:
                path = pre + ref.replace('[', '.[', 1) if m or '[' in ref else pre + ref
                if path not in d.vars:
                    d.vars[path] = Var(size, [(code, None)], enum, n)
                for a in {pre + ref, pre + ref + rng, path + rng} - {path}:
                    d.alias.setdefault(a, path)
            n += 1
    for base, (order, bits) in blasted.items():
        if base not in d.vars:
            d.vars[base] = Var(max(b for _, b in bits) + 1, bits, None, order)


def read(path, body='count', want=None):
    """body: None (declarations only), 'count' (value changes per signal), 'collect' (transitions of the id codes in want)."""
    src = _lines(path)
    if src is None:
        return None
    lines, close = src
    d = Dump()
    try:
        _header(lines, d)
        if body == 'count':
            cnt = collections.Counter()
            t_first = t_last = None
            for l in lines:
                c = l[:1]
                if c == b'#':
                    t_last = int(l[1:])
                    if t_first is None:
                        t_first = t_last
                elif c and c in b'01xzXZ':
                    cnt[l[1:].strip()] += 1
                elif c and c in b'bBrR':
                    cnt[l.rpartition(b' ')[2].strip()] += 1
            for p, v in d.vars.items():
                d.changes[p] = sum(max(0, cnt[code] - 1) for code, _ in v.members)
            d.t_start, d.t_end = (t_first or 0) * d.unit_ps, (t_last or 0) * d.unit_ps
        elif body == 'collect':
            want = set(want or ())
            tr = d.trans = {code: [] for code in want}
            t, t_first, scalar, vector = 0, None, b'01xzXZ', b'bBrR'
            for l in lines:
                c = l[:1]
                if c == b'#':
                    t = int(l[1:])
                    if t_first is None:
                        t_first = t
                elif not c:
                    continue
                elif c in scalar:
                    q = tr.get(l[1:].rstrip())
                    if q is not None:
                        q.append((t, c))
                elif c in vector:
                    v, _, code = l[1:].partition(b' ')
                    q = tr.get(code.rstrip())
                    if q is not None:
                        q.append((t, v if c in b'bB' else b'r' + v))
            d.t_start, d.t_end = (t_first or 0) * d.unit_ps, t * d.unit_ps
    finally:
        close()
    return d


def scan(path, body=True):
    d = read(path, 'count' if body else None)
    if d is None:
        return {}
    info = {p: {'order': v.order, 'changes': d.changes.get(p) if body else None, 'enum': v.enum, 'width': v.width} for p, v in d.vars.items()}
    for a, p in d.alias.items():
        info.setdefault(a, info[p])
    return info
