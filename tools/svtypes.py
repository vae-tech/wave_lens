#!/usr/bin/env python3
"""svtypes.py — the types of a design's signals for WaveLens, by their path in the hierarchy: FSM states by name and
packed structs as fields on a VCD, which has no types (Questa writes an enum as `reg [2:0]`, a struct as one vector).

  svtypes.py verilator --top tb --out tb.types.json -- rtl/pkg.sv rtl/*.sv +incdir+rtl     (or -- -f files.f)
  svtypes.py check tb.types.json [tb.vcd]          what it gives each path; with a dump: which signals it labels

The types come from whoever elaborated the design, so packages, `include, macros, parameters and generate blocks are
theirs, and two modules' `state` get each its own table:
  Questa     tools/questa/wavelens_types.tcl in vsim writes <dump>.types.json with `describe` of every signal;
  Verilator  `svtypes.py verilator` runs `verilator --json-only` with your arguments and writes the same file.
Name it as the dump (tb.vcd -> tb.types.json): `make html WAVES=tb.vcd` (mkconfig.py) takes it by itself, the viewer
takes it in Sources…, the VS Code tab reads it next to the dump. A signal gets a type only from its own path and only
when its width in the dump is the type's; the rest stays as numbers.

The file: {"wavelens": "types", "version": 1, "producer": {...}, and "describe": {path: Questa's text} (read here and
in the page, wavelens/src/vcd.js svTypes) or "signals": {path: {"width": 3, "enum": {"0": "IDLE"}} | {"width": 16,
"fields": [{"name", "msb", "lsb", "enum"?}]}}}. A nested struct gives dotted fields (in.st), an array of enums or
structs one field per element (pair[1]); a union, an enum wider than 32 bits (Questa's describe keeps 32) or a text
it does not read gives a note instead, and the signal stays as numbers. Verilator's adds a package's variables (p.state),
unpacked arrays of any dimensions (two[1][2] of two) and escaped names as the VCD writes them (u-l.st-x).
"""
import argparse, datetime, json, os, re, shutil, subprocess, sys, tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WaveError, run_main  # noqa: E402

# ---------------- a type: {'kind': 'enum'|'vec'|'record'|'array'|'union'|'unknown', 'width', …} ----------------
INTS = {'int': 32, 'integer': 32, 'shortint': 16, 'longint': 64, 'byte': 8, 'time': 64}
DESC_ENUM = re.compile(r'Verilog enum: \((-?\d+) (?:downto|to) (-?\d+)\) \[(\d+) enumeration values?\]')
DESC_VEC = re.compile(r'(?:Signed )?(?:Register|Net|Wire|reg|wire|logic|bit)(?: \[(-?\d+):(-?\d+)\])?')
DESC_REC = re.compile(r'(Record|Union) \[(\d+) elements?\]')
DESC_ELEM = re.compile(r'Element #\d+ "([^"]*)" =>')
DESC_ARR = re.compile(r'Array\((-?\d+) (downto|to) (-?\d+)\) \[length (\d+)\] of')
DESC_ITEM = re.compile(r'([A-Za-z_][\w$]*)=(-?\d+)')   # a label is an SV identifier: letters, digits, _ and $


def enum_items(body):
    """The (A=0,B=1, …) of describe -> [(label, value)], or the piece it does not read (str)."""
    items = []
    for x in body.strip().removeprefix('(').removesuffix(')').split(','):
        m = DESC_ITEM.fullmatch(x.strip())
        if not m:
            return x.strip() or body
        items.append((m.group(1), int(m.group(2))))
    return items


def parse_describe(text):
    """Questa's `describe` of one signal -> a type (see the grammar in the guide: enum, Register / Net, int, Record,
    Union, Array … of)."""
    lines = [x.strip() for x in str(text).splitlines() if x.strip()]
    pos = [0]

    def one():
        if pos[0] >= len(lines):
            return {'kind': 'unknown', 'text': '(nothing)'}
        s = lines[pos[0]]
        pos[0] += 1
        m = DESC_ENUM.fullmatch(s)
        if m:
            body = ''
            while pos[0] < len(lines):   # (A=0,B=1, … wraps onto the next lines)
                body += lines[pos[0]]
                pos[0] += 1
                if '(' in body and body.count('(') <= body.count(')'):
                    break
            items = enum_items(body)
            if isinstance(items, str):
                return {'kind': 'unknown', 'text': f'enum values "{items}"'}
            return {'kind': 'enum', 'width': abs(int(m.group(1)) - int(m.group(2))) + 1, 'count': int(m.group(3)),
                    'items': items}
        m = DESC_REC.fullmatch(s)
        if m:
            members = []
            for _ in range(int(m.group(2))):
                e = DESC_ELEM.fullmatch(lines[pos[0]]) if pos[0] < len(lines) else None
                if not e:
                    return {'kind': 'unknown', 'text': s}
                pos[0] += 1
                members.append((e.group(1), one()))
            return {'kind': 'record' if m.group(1) == 'Record' else 'union', 'members': members}
        m = DESC_ARR.fullmatch(s)
        if m:
            lo, hi = int(m.group(1)), int(m.group(3))
            return {'kind': 'array', 'left': lo, 'right': hi, 'elem': one()}
        if s in INTS:
            return {'kind': 'vec', 'width': INTS[s]}
        m = DESC_VEC.fullmatch(s)
        if m:
            return {'kind': 'vec', 'width': abs(int(m.group(1)) - int(m.group(2))) + 1 if m.group(1) else 1}
        return {'kind': 'unknown', 'text': s}
    return one()


def width(t):
    k = t['kind']
    if k in ('enum', 'vec'):
        return t['width']
    if k == 'record':
        ws = [width(x) for _, x in t['members']]
        return None if None in ws else sum(ws)
    if k == 'union':
        ws = [width(x) for _, x in t['members']]
        return None if None in ws or not ws else max(ws)
    if k == 'array':
        w = width(t['elem'])
        return None if w is None else w * (abs(t['left'] - t['right']) + 1)
    return None


def table(t):
    """An enum's values -> {"value": "label"} (unsigned, on its width), or a reason it is not given."""
    if t['width'] > 32 and t.get('describe'):
        return None, f'an enum of {t["width"]} bits: Questa\'s describe keeps 32 bits of each value'
    if len(t['items']) != t['count']:
        return None, f'{len(t["items"])} of its {t["count"]} enum values read'
    mask = (1 << t['width']) - 1
    return {str(v & mask): n for n, v in sorted(t['items'], key=lambda x: x[1] & mask)}, None


def flat(t, name, lsb, out):
    """The fields of a type that starts at bit lsb, MSB first in out; a reason when it cannot be told."""
    k, w = t['kind'], width(t)
    if w is None:
        return f'{name or "the signal"}: a type it does not read ({t.get("text", k)})'
    if k == 'enum':
        tb, why = table(t)
        if why:
            return f'{name}: {why}'
        out.append({'name': name, 'msb': lsb + w - 1, 'lsb': lsb, 'enum': tb})
    elif k == 'record':
        at, part = lsb + w, []
        for mn, mt in t['members']:   # the first member holds the top bits
            at -= width(mt)
            why = flat(mt, f'{name}.{mn}' if name else mn, at, part)
            if why:
                return why
        out.extend(part)
    elif k == 'array' and t['elem']['kind'] in ('enum', 'record', 'array'):
        n, ew = abs(t['left'] - t['right']) + 1, width(t['elem'])
        step = -1 if t['left'] > t['right'] else 1
        for j in range(n):   # the left index holds the top bits
            why = flat(t['elem'], f'{name}[{t["left"] + j * step}]', lsb + (n - 1 - j) * ew, out)
            if why:
                return why
    else:   # a vector, an array of vectors, a union inside a struct: one field
        out.append({'name': name, 'msb': lsb + w - 1, 'lsb': lsb})
    return None


def lower(t):
    """A type -> (entry {"width", "enum" | "fields"} or None for a plain vector, a note or None)."""
    if t['kind'] == 'enum':
        tb, why = table(t)
        return (None, why) if why else ({'width': t['width'], 'enum': tb}, None)
    if t['kind'] == 'union':
        return None, 'a packed union: which member holds the value is not known'
    if t['kind'] == 'record' or (t['kind'] == 'array' and t['elem']['kind'] in ('enum', 'record', 'array')):
        out = []
        why = flat(t, '', 0, out)
        if why:
            return None, why
        if t['kind'] == 'array' and not any(x['kind'] in ('enum', 'record') for x in walk_types(t)):
            return None, None   # an array of plain vectors: a vector
        return {'width': width(t), 'fields': out}, None
    if t['kind'] == 'unknown':
        return None, f'a type it does not read ({t["text"]})'
    return None, None


def from_describe(desc):
    """Questa's {path: describe text} -> ({path: entry}, [notes])."""
    sigs, notes = {}, []
    for p, text in desc.items():
        if str(text).startswith('describe failed'):
            notes.append(f'{p}: {text}')
            continue
        t = parse_describe(text)
        if t['kind'] == 'enum':
            t['describe'] = True
        for x in walk_types(t):
            if x['kind'] == 'enum':
                x['describe'] = True
        e, why = lower(t)
        if e:
            sigs[p] = e
        if why:
            notes.append(f'{p}: {why}')
    return sigs, notes


def walk_types(t):
    yield t
    for _, m in t.get('members', ()):
        yield from walk_types(m)
    if 'elem' in t:
        yield from walk_types(t['elem'])


# ---------------- Verilator: --json-only, its tree of modules, cells and types ----------------
def const_value(name):
    """A CONST of Verilator's JSON ("3'h4", "32'shffffffff", "5") -> an int, None when not a number."""
    m = re.fullmatch(r"(?:(\d+)')?(s?)([hbdo]?)([0-9a-fA-F_]+)", name or '')
    if not m:
        return None
    try:
        return int(m.group(4).replace('_', ''), {'h': 16, 'b': 2, 'o': 8, 'd': 10, '': 10}[m.group(3)])
    except ValueError:
        return None


def verilator_types(tree):
    """Verilator's --json-only tree -> ({path: entry}, [notes]): from each top module down its cells and generate
    blocks, every variable's type followed through its references (a parameterised module is one module per set of
    parameters, so each instance gets its own table)."""
    idx = {}

    def index(n):
        if isinstance(n, dict):
            if 'addr' in n:
                idx.setdefault(n['addr'], n)
            for v in n.values():
                index(v)
        elif isinstance(n, list):
            for v in n:
                index(v)
    index(tree)
    memo = {}

    def rng(r):
        if not r:
            return None
        m = re.fullmatch(r'\[?(-?\d+):(-?\d+)\]?', r)
        return (int(m.group(1)), int(m.group(2))) if m else None

    def typ(addr, depth=0):
        if addr in memo:
            return memo[addr]
        n = idx.get(addr)
        if n is None or depth > 64:
            return {'kind': 'unknown', 'text': f'type {addr}'}
        k = n['type']
        if k == 'REFDTYPE':
            t = typ(n.get('refDTypep'), depth + 1)
        elif k == 'BASICDTYPE':
            kw = n.get('keyword') or n.get('name')
            r = rng(n.get('range'))
            if kw in ('logic', 'bit', 'reg', 'wire') or kw in INTS:
                t = {'kind': 'vec', 'width': abs(r[0] - r[1]) + 1 if r else INTS.get(kw, 1)}
            else:
                t = {'kind': 'unknown', 'text': kw}
        elif k == 'ENUMDTYPE':
            base = typ(n.get('refDTypep'), depth + 1)
            items = [(i['name'], const_value(i['valuep'][0]['name']) if i.get('valuep') else None) for i in n.get('itemsp') or []]
            if base.get('kind') != 'vec' or any(v is None for _, v in items):
                t = {'kind': 'unknown', 'text': f'enum {n.get("name")}'}
            else:
                t = {'kind': 'enum', 'width': base['width'], 'count': len(items), 'items': items, 'name': n.get('name')}
        elif k in ('STRUCTDTYPE', 'UNIONDTYPE'):
            if not n.get('packed'):
                t = {'kind': 'unknown', 'text': f'unpacked {n.get("name")}'}
            else:
                ms = [(m['name'], typ(m.get('dtypep') or m.get('refDTypep'), depth + 1)) for m in n.get('membersp') or []]
                t = {'kind': 'record' if k == 'STRUCTDTYPE' else 'union', 'members': ms}
        elif k == 'PACKARRAYDTYPE':
            r = rng(n.get('declRange'))
            t = {'kind': 'array', 'left': r[0], 'right': r[1], 'elem': typ(n.get('refDTypep'), depth + 1)} if r else \
                {'kind': 'unknown', 'text': 'packed array'}
        elif k == 'UNPACKARRAYDTYPE':   # an array of variables: each element is a signal of the dump (x[0], x[1] …)
            t = {'kind': 'elements', 'elem': typ(n.get('refDTypep'), depth + 1)}
        else:
            t = {'kind': 'unknown', 'text': k.lower()}
        memo[addr] = t
        return t
    sigs, notes = {}, []

    def scope(node, path):
        for st in (node.get('stmtsp') or []) + (node.get('itemsp') or []):   # (a generate block's are itemsp)
            k = st.get('type')
            if k == 'VAR' and not st.get('isParam') and st.get('varType') not in ('GENVAR', 'LPARAM', 'GPARAM'):
                t = typ(st.get('dtypep'))
                p = path + [st['name']]   # as written (st-x of \\st-x ; origName is Verilator's st__02dx)
                while t['kind'] == 'elements':   # unpacked, of any dimensions: the element's type, matched to x[1][2] by lookup
                    t = t['elem']
                e, why = lower(t)
                if e:
                    sigs['.'.join(p)] = e
                if why and t['kind'] != 'unknown':
                    notes.append(f'{".".join(p)}: {why}')
            elif k == 'CELL':
                m = idx.get(st.get('modp'))
                if m is not None:
                    scope(m, path + [st['name']])
            elif k in ('GENBLOCK', 'BEGIN'):
                scope(st, path if st.get('implied') or not st.get('name') else path + [st['name']])
    tops = [m for m in tree.get('modulesp') or [] if m.get('type') == 'MODULE' and m.get('level') == 1]
    for m in tops:
        scope(m, [m.get('origName') or m['name']])
    for m in tree.get('modulesp') or []:   # a package's variables: a scope of its own at the top of the dump (p.state)
        if m.get('type') == 'PACKAGE' and not m['name'].startswith(('@', '$', '__0')):
            scope(m, [m['name']])
    return sigs, notes


def run_verilator(args, top=None, exe='verilator'):
    """verilator --json-only with the user's arguments (files, -f, +incdir+, +define+, -G…) -> its JSON tree."""
    if not shutil.which(exe):
        raise WaveError(f'{exe} is not on PATH (Verilator 5: https://verilator.org)')
    with tempfile.TemporaryDirectory(prefix='svtypes-') as d:
        out = os.path.join(d, 'tree.json')
        cmd = [exe, '--json-only', '--timing', '-Wno-fatal', '-Wno-lint', '-Wno-style', '--Mdir', d,
               '--json-only-output', out, '--json-only-meta-output', os.path.join(d, 'meta.json'),
               *(['--top-module', top] if top else []), *args]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode or not os.path.exists(out):
            err = '\n'.join(x for x in (r.stderr or r.stdout).splitlines() if x.startswith('%Error'))[:2000]
            raise WaveError(f'verilator --json-only failed ({r.returncode}):\n{err or r.stderr[-2000:]}')
        ver = subprocess.run([exe, '--version'], capture_output=True, text=True).stdout.strip()
        with open(out, encoding='utf-8') as f:
            return json.load(f), ver


# ---------------- the file, and what it gives the signals of a dump ----------------
def load(path):
    """A types file -> {'signals': {path: entry}, 'notes': [...], 'producer': {...}} (Questa's describe read here)."""
    try:
        with open(path, encoding='utf-8') as f:
            text = f.read()
        if not text.strip():
            raise WaveError(f'{path}: not a types file: the file is empty')
        d = json.loads(text)
    except json.JSONDecodeError as e:   # where: the line, a caret under the column (the page's log: the same)
        line = e.doc.splitlines()[e.lineno - 1] if e.lineno <= len(e.doc.splitlines()) else ''
        a = max(0, e.colno - 61)
        cut = ('…' if a else '') + line[a:a + 100] + ('…' if a + 100 < len(line) else '')
        pad = ' ' * (len('…' if a else '') + e.colno - 1 - a)
        raise WaveError(f'{path}: not a types file at line {e.lineno}, column {e.colno}: {e.msg}' +
                        (f'\n    {cut}\n    {pad}^' if line else '')) from None
    except (OSError, ValueError) as e:
        raise WaveError(f'{path}: not a types file ({e})')
    return read(d, path)


def read(d, where='types'):
    if not isinstance(d, dict) or d.get('wavelens') != 'types':
        raise WaveError(f'{where}: not a WaveLens types file (no "wavelens": "types"; made by tools/questa/wavelens_types.tcl '
                        'or svtypes.py verilator)')
    sigs, notes = dict(d.get('signals') or {}), list(d.get('notes') or [])
    if isinstance(d.get('describe'), dict):
        s, n = from_describe(d['describe'])
        sigs.update(s)
        notes += n
    m = {} if d.get('map') is None else d['map']   # none or null: no map ([] or "" an error, as in the page)
    if not isinstance(m, dict) or not all(isinstance(k, str) and isinstance(x, str) for k, x in m.items()):
        raise WaveError(f'{where}: "map" is {{"dump.prefix": "types.prefix"}}, the dump\'s scopes as the types name them')
    return {'signals': sigs, 'notes': notes, 'producer': d.get('producer') or {}, 'map': dict(m),
            'instances': d.get('instances') if isinstance(d.get('instances'), dict) else {}}


def remap(path, m):
    """A dump's path as the types name it, by the longest prefix of the map ({"top.dut_i": "dut"}: top.dut_i.state -> dut.state)."""
    for k in sorted(m or (), key=len, reverse=True):
        if path == k or path.startswith(k + '.'):
            return m[k] + path[len(k):]
    return path


def map_arg(items):
    """--map DUMP=TYPES, given again for more -> {dump prefix: types prefix}."""
    out = {}
    for it in items or ():
        a, eq, b = it.partition('=')
        if not eq or not a or not b:
            raise WaveError(f'--map {it}: DUMP=TYPES, a scope of the dump and the one of the types file (top.dut_i=dut)')
        out[a] = b
    return out


DATE_FORMATS = ('%a %b %d %H:%M:%S %Y', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%b %d, %Y %H:%M:%S')


def when(text):
    """A $date or a producer's date -> datetime, None when it is not one of the usual forms."""
    t = ' '.join(str(text or '').split())
    for f in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(t, f)
        except ValueError:
            pass
    return None


def fingerprint(types, date=None, modules=(), m=None):
    """Whether the types are of the run that wrote the dump, as far as both tell: the dates (Questa's types and VCD come
    from one vsim: the same day), the instances (Questa's types list them: one under a module of the dump that the dump
    does not have) -> [notes]."""
    notes, p = [], types.get('producer') or {}
    a, b = when(p.get('date')), when(date)
    if a and b and abs((a - b).total_seconds()) > 86400:
        d = abs(a - b).days
        notes.append(f'the types were written {d} day{"" if d == 1 else "s"} {"after" if a > b else "before"} the dump ({p.get("date")}; '
                     f'the dump: {date}): another run? (the labels of another design or other parameters may not fit)')
    m = {**types.get('map', {}), **(m or {})}
    mods = {remap(x, m) for x in modules}
    if mods and types.get('instances'):
        miss = sorted(i for i in types['instances'] if i not in mods and i.rsplit('.', 1)[0] in mods)
        if miss:
            notes.append(f'{len(miss)} instance{"" if len(miss) == 1 else "s"} of the types not in the dump, under modules it has: '
                         f'{", ".join(miss[:3])}{" …" if len(miss) > 3 else ""} (none of its signals dumped, or another design)')
    return notes


def added_tops(sigs, paths):
    """The top scopes a dump adds above the design's (TOP of Verilator's FST, a wrapper of the testbench): the dump's
    roots that are none of the types' roots but have one as a child; none when a root of the dump is one of the types':
    then every path is taken as it is (other.tb.state is not tb.state)."""
    mine = {p.split('.', 1)[0] for p in sigs}
    roots = {p.split('.', 1)[0] for p in paths}
    if roots & mine:
        return frozenset()
    return frozenset(q[0] for q in (p.split('.', 2) for p in paths) if len(q) > 1 and q[1] in mine)


def lookup(sigs, path, tops=frozenset()):
    """The entry of a dump's path: its own; else without a top scope the dump adds (tops: added_tops); an element of an
    unpacked array (x[3], x.[3]) the array's."""
    k = lookup_key(sigs, path, tops)
    return sigs[k] if k else None


def lookup_key(sigs, path, tops=frozenset()):   # (path: as the types name it, remap)
    if path in sigs:
        return path
    parts = path.split('.', 1)
    if len(parts) == 2 and parts[0] in tops and parts[1] in sigs:
        return parts[1]
    base = re.sub(r'(\.?\[-?\d+\])+$', '', path)
    return lookup_key(sigs, base, tops) if base != path else None


def apply(types, sigs, m=None):
    """The types onto the signals of a dump ([{path, width, enum, fields}], mkconfig's): a path's entry when its width
    is the signal's; the dump's own tables (an FST's) stay -> (labelled, with fields, [notes], {paths given}). m: the
    dump's scopes as the types name them, over the file's "map" (remap)."""
    ne = nf = 0
    notes, given = [], set()
    m = {**types.get('map', {}), **(m or {})}
    tops = added_tops(types['signals'], [remap(s['path'], m) for s in sigs])
    for s in sigs:
        e = lookup(types['signals'], remap(s['path'], m), tops)
        if not e:
            continue
        if e['width'] != s['width']:
            notes.append(f'{s["path"]}: {s["width"]} bits in the dump, {e["width"]} in the types: left as it is')
            continue
        # a table whose values do not all fit the width is not this signal's (the page's svApply: the same)
        fits = all(re.fullmatch(r'\d+', str(k)) and int(k) < 1 << s['width'] for k in e.get('enum') or ())
        if e.get('enum') and not s.get('enum') and fits:
            s['enum'] = {int(k): v for k, v in e['enum'].items()}
            ne += 1
            given.add(s['path'])
        if e.get('fields') and not s.get('fields'):
            s['fields'] = e['fields']
            nf += 1
            given.add(s['path'])
    return ne, nf, notes, given


def beside(dump):
    """The types file named as the dump (tb.vcd -> tb.types.json), when there is one."""
    p = re.sub(r'\.(vcd|fst|fsdb)$', '', dump, flags=re.I) + '.types.json'
    return p if os.path.exists(p) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0], epilog=__doc__.split('\n\n', 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    v = sub.add_parser('verilator', help='the types of a design through verilator --json-only')
    v.add_argument('--top', help='the top module (verilator --top-module)')
    v.add_argument('--out', '-o', required=True, help='the types file to write (name it as the dump: tb.types.json)')
    v.add_argument('--verilator', default='verilator', help='the verilator executable')
    v.add_argument('args', nargs=argparse.REMAINDER, help='after --: what you give verilator (files, -f list.f, +incdir+…, +define+…)')
    c = sub.add_parser('check', help='what a types file gives each path, and with a dump which of its signals')
    c.add_argument('types')
    c.add_argument('dump', nargs='?')
    c.add_argument('--map', action='append', metavar='DUMP=TYPES', help='a scope of the dump as the types name it (top.dut_i=dut; again for more)')
    a = ap.parse_args()
    if a.cmd == 'verilator':
        args = a.args[1:] if a.args[:1] == ['--'] else a.args
        if not args:
            raise WaveError('svtypes.py verilator: the design after -- (files, -f list.f, +incdir+…)')
        tree, ver = run_verilator(args, a.top, a.verilator)
        sigs, notes = verilator_types(tree)
        doc = {'wavelens': 'types', 'version': 1, 'producer': {'tool': ver, 'by': 'tools/svtypes.py verilator', 'top': a.top,
                                                               'args': args, 'date': datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')},
               'signals': dict(sorted(sigs.items())), 'notes': notes}
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write('{\n' + ',\n'.join(f'  {json.dumps(k)}: {json.dumps(x, ensure_ascii=False)}' if k != 'signals' else
                                       '  "signals": {\n' + ',\n'.join(f'    {json.dumps(p)}: {json.dumps(e, ensure_ascii=False)}'
                                                                   for p, e in x.items()) + '\n  }'
                                       for k, x in doc.items()) + '\n}\n')
        for n in notes:
            print(f'svtypes: {n}', file=sys.stderr)
        ne = sum(1 for e in sigs.values() if 'enum' in e)
        print(f'svtypes: {ne} enum and {len(sigs) - ne} struct signals -> {a.out}', file=sys.stderr)
        return 0
    t = load(a.types)
    print(f'{a.types}: {t["producer"].get("tool", "?")}: {len(t["signals"])} typed signals, {len(t["notes"])} notes')
    for p, e in t['signals'].items():
        if 'enum' in e:
            print(f'  {p} [{e["width"]}]: ' + ' '.join(f'{v}={k}' for k, v in e['enum'].items()))
        else:
            star = any('enum' in f for f in e['fields'])
            print(f'  {p} [{e["width"]}]: ' + ', '.join(f'{f["name"]}[{f["msb"]}:{f["lsb"]}]' + ('*' if 'enum' in f else '')
                                                       for f in e['fields']) + ('   (* an enum)' if star else ''))
    for n in t['notes']:
        print(f'  note: {n}')
    if a.dump:
        import dumpscan
        decl = dumpscan.read(a.dump, None)
        sigs = [{'path': p, 'width': x.width, 'enum': {}, 'fields': None} for p, x in decl.vars.items() if x.kind != 'event']
        mp = {**t['map'], **map_arg(a.map)}
        ne, nf, notes, _ = apply(t, sigs, mp)
        tops = added_tops(t['signals'], [remap(s['path'], mp) for s in sigs])
        hit = {lookup_key(t['signals'], remap(s['path'], mp), tops) for s in sigs}
        for n in fingerprint(t, decl.date, decl.modules, mp):
            print(f'  run: {n}')
        miss = [p for p in t['signals'] if p not in hit]
        print(f'{a.dump}: {len(sigs)} signals: {ne} get enum labels, {nf} get fields; '
              f'{len(notes)} width differs, {len(miss)} typed paths not in the dump')
        for n in notes:
            print(f'  {n}')
        for p in miss[:20]:
            print(f'  not in the dump: {p}')
        return 1 if notes else 0
    return 0


if __name__ == '__main__':
    run_main(main, 'svtypes')
