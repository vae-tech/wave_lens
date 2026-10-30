#!/usr/bin/env python3
"""mkconfig.py — make an editable config file for vcd2wavedrom.py / mkhtml.py from a dump: every signal of the dump
under its full hierarchical path, one line each, with per-signal settings to fill in by hand.

  mkconfig.py test_stream_video.vcd                    -> test_stream_video.config.json (next to the dump)
  mkconfig.py dump.vcd --base my.base.json --out my.config.json
  mkconfig.py dump.vcd --out dump.config.json --update # dump changed: add new signals, drop gone ones, keep all edits
  mkconfig.py dump.fst                                 # FST: read through GTKWave's fst2vcd (or sva vcd), FSM enum labels included
  mkconfig.py dump.vcd                                 # dump.types.json beside it (Questa / Verilator): states and structs by path
  mkconfig.py dump.vcd --types other.types.json        # the types of the design from another file (tools/svtypes.py)
  mkconfig.py dump.vcd --sv rtl/*.sv                   # no types file: enum labels by the variable's name from the sources
  mkconfig.py dump.fst --sva checks/*.sva              # assertions: "sva" and a "bind" line per matching instance

Per-signal entry ("" = the global setting from "config"):
  "tb.dut.state": {"show": true, "radix": "", "color": "", "style": "", "width": 3, "changes": 120}
  show   true/false (false: left out of the page)        radix  auto hex dec signed bin oct ascii float q8 sq15
  color  trace / outline / name colour, e.g. "#e03131"   style  auto wavedrom questa square
  also   "alias": "name shown", "fill": "#ffe066" (bus fill), "enum": {"0": "IDLE", "1": "RUN"}
  width and changes (value changes in the dump) are information only. "enum" is filled from the dump (FST enum tables),
  from a types file (--types, or <dump>.types.json beside the dump: tools/svtypes.py) or from --sv sources, so FSM
  states show by name; what the types declare that the dump has not got is said (unpacked arrays, generate scopes). A $dumpoff block (every value x) counts as changes; event
  variables are left out (no value to draw), real and string ones are labelled with their texts.

Base file (--base, default tools/base.config.json beside this script): copied into the new config, except two generator keys
  "select" {"depth": 2, "constants": false, "hide": ["$rootio.*"], "budget": 1500000}  which signals start with
           "show": true — scope depth <= depth below the top, not constant, not hidden, at most `budget` value changes
           in total (the deepest levels are dropped first)
  "rules"  [{"match": ["*clk", "*clk_i"], "width": 1, "color": "#2f9e44"}, …]  starting settings by full-path pattern
           ("*" and "?"; optional "width": 8 / ">1" / ">=32"); later rules win, and they may set "show" too.

--sva FILE...: the files are parsed with the sva CLI and every assertion is matched against the instances of the dump
with the page's rule for names (docs/sva/ENGINE.md *Name resolution*; the "sortIgnore" prefixes of "config"): "bind"
gets one line per assertion and instance where all its signals resolve, "show": true when that instance is the only
one (else false, with the number of candidates in "comment": set "show": true on the ones you want). --update keeps
the "show" choices.

--update refuses a dump that lost more than half of the config's signals (another design?) unless --force, and points
"waves" at the dump it read. What a types file gave is listed in "typed" ({path: mark}): --update replaces those "enum" /
"fields" with the types' of now (or takes them away), unless you edited them; an "enum" of your own stays.
"""
import argparse, hashlib, json, os, re, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # -I drops the script dir from sys.path
import dumpscan, svabuild, svtypes, vcd2wavedrom  # noqa: E402
from common import SELECT_KEYS, WaveError, add_sva_bin_arg, check_config, glob_re, run_main  # noqa: E402

ROOT = os.path.dirname(HERE)
BASE = os.path.join(HERE, 'base.config.json')
OLD_BASE = os.path.join(ROOT, 'wavelens.base.json')   # name before the restructure, read with a warning
ENTRY = ('show', 'radix', 'color', 'style')          # keys every entry gets (empty = global setting)
INFO = ('width', 'changes')
GENERATOR_KEYS = ('select', 'rules')


def die(msg):
    raise WaveError('mkconfig: ' + msg)


pattern = glob_re


def width_ok(rule, w):
    if rule is None:
        return True
    m = re.fullmatch(r'\s*(>=|<=|>|<|=)?\s*(\d+)\s*', str(rule))
    if not m:
        die(f'bad rule width "{rule}" (use 8, ">1", ">=32")')
    op, n = m.group(1) or '=', int(m.group(2))
    return {'=': w == n, '>': w > n, '<': w < n, '>=': w >= n, '<=': w <= n}[op]


# ---------------- enum labels from SystemVerilog sources (VCD has none; FST carries its own tables) ----------------
# The rules are wavelens/src/vcd.js svTables' (the twin; tests/unit/sv/sources.sv with its expected tables for both).
SV_WORDS = {'input', 'output', 'inout', 'ref', 'var', 'const', 'static', 'automatic', 'logic', 'wire', 'reg', 'bit', 'signed', 'unsigned'}
SV_BASE = {'logic': 1, 'bit': 1, 'reg': 1, 'wire': 1, 'byte': 8, 'shortint': 16, 'int': 32, 'integer': 32, 'longint': 64}
SV_ENUM = re.compile(r'\btypedef\s+enum\b\s*([^{;]*)\{([^}]*)\}\s*(\w+)\s*;')
SV_STRUCT = re.compile(r'\btypedef\s+struct\s+packed\b[^{;]*\{([^}]*)\}\s*(\w+)\s*;')
SV_ANON = re.compile(r'(?<!typedef)\s\benum\b[^{;]*\{([^}]*)\}\s*(\w+(?:\s*,\s*\w+)*)\s*;')
# not declarations of signals: functions and tasks (their arguments, results), the members of a struct or union (nested:
# the innermost body first, until none is left); strings and comments are blanked before anything is read
SV_SKIP = re.compile(r'\bfunction\b.*?\bendfunction\b|\btask\b.*?\bendtask\b', re.S)
SV_BODY = re.compile(r'\b(?:struct|union)\b[^{};]*\{[^{}]*\}')
SV_BLANK = re.compile(r'"(?:[^"\\\n]|\\.)*"|//[^\n]*|/\*.*?\*/', re.S)
# a plain vector or integer variable ("logic [1:0] state;", a port): a name it has besides a type's is not labelled
SV_PLAIN = re.compile(r'\b(?:logic|reg|wire|bit|byte|shortint|int|longint|integer)\b\s*(?:signed|unsigned)?\s*(?:\[[^\]]*\]\s*)*'
                      r'(\w+(?:\s*(?:\[[^\]]*\]\s*)*,\s*\w+)*)\s*(?:\[[^\]]*\]\s*)*[;=,)]')


SV_ONE = re.compile(r'\s*(\w+)\s*(?:\[[^\]]*\]\s*)*(?:=[\s\S]*)?')


def sv_names(t, at):
    """The names a declaration declares, its list read from offset at: "a [3:0] = f(x, y), b, c;" -> [a, b, c]; it ends
    at the ; (or the ) of a port list), and a part that is not "name [dims] = value" (the next port's type) is none."""
    parts, depth, cur = [], 0, []
    for ch in t[at:]:
        if ch in '([{':
            depth += 1
        elif ch in ')]}':
            if not depth:
                break
            depth -= 1
        elif not depth and ch in ',;':
            parts.append(''.join(cur))
            cur = []
            if ch == ';':
                break
            continue
        cur.append(ch)
    parts.append(''.join(cur))
    return [m.group(1) for m in map(SV_ONE.fullmatch, parts) if m]


def sv_signals_text(t):
    """A source with what holds no signal declarations blanked: function / task bodies, struct / union bodies."""
    t = SV_SKIP.sub(' ', t)
    while True:
        u = SV_BODY.sub(' ', t)
        if u == t:
            return t
        t = u


def sv_value(v, prev):
    """An enum label's value: its initializer v ('' none: prev + 1) -> int; None when it is not a literal (an expression,
    a parameter, a negative number): the table is left out rather than guessed."""
    if not v.strip():
        return prev + 1
    v = v.strip().replace('_', '')   # (after: "_" alone is an identifier, not an omitted value)
    m = re.fullmatch(r"(?:\d+)?'[sS]?([bodhBODH])([0-9a-fA-F]+)", v)
    if m:
        try:
            return int(m.group(2), {'b': 2, 'o': 8, 'd': 10, 'h': 16}[m.group(1).lower()])
        except ValueError:
            return None
    if re.fullmatch(r'\d+', v):
        return int(v, 10)   # 08: decimal, as SystemVerilog reads it
    return int(v, 16) if re.fullmatch(r'0[xX][0-9a-fA-F]+', v) else None


def sv_items(body):
    """'A, B = 2'd3, C' -> {0: 'A', 3: 'B', 4: 'C'}; None when a label or a value is not read (a macro, a range, an
    expression) or there is none."""
    table, v = {}, -1
    for it in body.split(','):
        name, eq, val = it.partition('=')
        name = name.strip()
        if not name and not eq:
            continue
        if not re.fullmatch(r'\w+', name):
            return None
        v = sv_value(val if eq else '', v)
        if v is None:
            return None
        table[v] = name
    return table or None


def sv_dims(s):
    """Packed dimensions "[7:0][1:0]" -> the number of bits they hold (1 for none), None when a bound is not a number."""
    n = 1
    for d in re.findall(r'\[([^\]]*)\]', s):
        m = re.fullmatch(r'\s*(\d+)\s*:\s*(\d+)\s*', d)
        if not m:
            return None
        n *= abs(int(m.group(1)) - int(m.group(2))) + 1
    return n


def sv_texts(files):
    out = []
    for f in files:
        with open(f, encoding='utf-8', errors='replace') as fh:
            out.append(fh.read())
    return out


def sv_tables(texts):
    """SystemVerilog sources -> ({variable: {value: label}}, {variable: [{name, msb, lsb, enum?}]}, [notes]).
    "typedef enum … {A, B = 2'd3} name_t;" and "typedef struct packed {…} name_t;" (fields MSB first; a member of a width
    it cannot tell leaves the struct out), then the declarations of signals with those types ("p::name_t a, b;", ports,
    arrays "name_t a [4];"; not function arguments, not struct members) and "enum {…} st;". By the variable's name only:
    a name declared with two different types (two modules; one a plain vector) gets nothing, and a note says so; so does
    an enum it does not read."""
    texts = [SV_BLANK.sub(lambda m: '""' if m.group(0)[0] == '"' else ' ', t) for t in texts]
    types, widths, bodies, anon, notes, twice = {}, {}, {}, [], [], set()
    for t in texts:
        for m in SV_ENUM.finditer(t):
            table, name = sv_items(m.group(2)), m.group(3)
            if table is None:
                notes.append(f'enum {name}: a label or value it does not read (an expression, a parameter, a macro): no labels')
            if name in types and types[name] != table and name not in twice:   # p::t_t and q::t_t: which one a signal has is not known
                twice.add(name); notes.append(f'enum {name}: defined twice with different labels (two packages?): no labels')
            types[name] = None if name in twice else table
            bm = re.fullmatch(r'(\w+)?\s*(?:signed|unsigned)?\s*((?:\[[^\]]*\]\s*)*)', m.group(1).strip())
            w = (SV_BASE.get(bm.group(1)) if bm.group(1) else 32) if bm else None
            d = sv_dims(bm.group(2)) if bm else None
            if w is not None and d is not None:
                widths[name] = w * d
        for m in SV_STRUCT.finditer(t):
            if m.group(2) in bodies and bodies[m.group(2)] != m.group(1):
                twice.add(m.group(2)); notes.append(f'struct {m.group(2)}: defined twice with different members: no fields')
            bodies[m.group(2)] = m.group(1)
        for m in SV_ANON.finditer(sv_signals_text(t)):
            table = sv_items(m.group(1))
            if table is None:
                notes.append(f'enum {m.group(2).strip()}: a label or value it does not read (an expression, a parameter, a macro): no labels')
            anon += [(n.strip(), table) for n in m.group(2).split(',')]
    for name in set(types) & set(bodies):   # an enum in one package, a struct in another: which one a signal has is not known
        if name not in twice:
            twice.add(name); notes.append(f'{name}: defined as an enum and as a struct (two packages?): no labels, no fields')
        types[name] = None
    fields = {}
    for _ in range(len(bodies) + 1):   # nested typedefs: until nothing new resolves
        new = False
        for name, body in bodies.items():
            if name in fields or name in twice:
                continue
            members = []
            for decl in filter(None, (x.strip() for x in body.split(';'))):
                m = re.fullmatch(r'(?:\w+::)?(\w+)\s*(?:signed|unsigned)?\s*((?:\[[^\]]*\]\s*)*)(\w+(?:\s*,\s*\w+)*)', decl)
                base = m and (SV_BASE.get(m.group(1)) or widths.get(m.group(1)))
                d = m and sv_dims(m.group(2))
                if not base or d is None:
                    members = None
                    break
                members += [(n.strip(), base * d, types.get(m.group(1))) for n in m.group(3).split(',')]
            if members:
                lsb, out = sum(w for _, w, _ in members), []
                for n, w, e in members:
                    lsb -= w
                    out.append({'name': n, 'msb': lsb + w - 1, 'lsb': lsb, **({'enum': {str(k): v for k, v in sorted(e.items())}} if e else {})})
                fields[name] = out; widths[name] = sum(w for _, w, _ in members); new = True
        if not new:
            break
    cand, clash = {}, set()   # one name, one candidate: ('e', table) or ('s', fields); None for an enum not read (it takes the name)
    def put(name, val):
        if name in clash:
            return
        if name in cand and cand[name] != val:
            clash.add(name); del cand[name]
            return
        cand[name] = val
    for n, table in anon:
        put(n, ('e', table))
    known = sorted(set(types) | set(fields) | set(bodies), key=len, reverse=True)
    if known:
        decl = re.compile(r'\b(?:\w+::)?(' + '|'.join(map(re.escape, known)) + r')\b\s+(?:\[[^\]]*\]\s*)*'
                          r'(\w+(?:\s*(?:\[[^\]]*\]\s*)*,\s*\w+)*)\s*(?:\[[^\]]*\]\s*)*[;=,)]')
        for t in texts:
            st = sv_signals_text(t)
            for m in decl.finditer(st):
                ty = m.group(1)
                for n in sv_names(st, m.start(2)):   # (each name past an initialiser too)
                    if not n or n in SV_WORDS or n in types or n in fields:
                        continue
                    if ty in fields:
                        put(n, ('s', fields[ty]))
                    elif ty in types:   # an enum it did not read too: the name is taken, another table does not land on it
                        put(n, ('e', types[ty]))
                    elif ty in bodies:   # a struct whose fields it cannot tell (or defined twice): the name is taken
                        put(n, ('s', None))
    for t in texts:   # the same name as a plain vector somewhere (another module's state): which one a signal is is not known
        st = sv_signals_text(t)
        for m in SV_PLAIN.finditer(st):
            for n in sv_names(st, m.start(1)):
                if n and n not in SV_WORDS:
                    put(n, ('p', None))
    enums = {k: v[1] for k, v in cand.items() if v[0] == 'e' and v[1]}
    structs = {k: v[1] for k, v in cand.items() if v[0] == 's' and v[1]}
    notes += [f'{n}: declared with different types (in different modules?): no labels' for n in sorted(clash)]
    return enums, structs, notes


def sv_enums(files):
    """{variable name: {value: label}} of the sources (sv_tables)."""
    return sv_tables(sv_texts(files))[0]


def sv_structs(files):
    """{variable name: [{name, msb, lsb, enum?}]} of the sources (sv_tables)."""
    return sv_tables(sv_texts(files))[1]


# ---------------- catalog ----------------
def build(sigs: list, base: dict) -> dict:
    """The signals of a dump [{path, width, changes, enum?, fields?}] and a base file -> the catalog {path: entry}:
    "show" by select (depth, constants, hide, budget), then the rules in order."""
    bad = set(base.get('select') or {}) - set(SELECT_KEYS)
    if bad:
        die(f'"select": unknown key(s) {", ".join(sorted(bad))} (have: {", ".join(SELECT_KEYS)})')
    sel = {'depth': 2, 'constants': False, 'hide': [], 'budget': 1500000, **(base.get('select') or {})}
    hide = [pattern(p) for p in ([sel['hide']] if isinstance(sel['hide'], str) else sel['hide'] or [])]
    depth = lambda p: len(svabuild.split_path(p)) - 2
    cat = {}
    for s in sigs:
        e = {k: '' for k in ENTRY}
        e['show'] = (depth(s['path']) <= sel['depth'] and (sel['constants'] or s['changes'] != 0)
                     and not any(h.match(s['path']) for h in hide))
        e['width'] = s['width']
        if s['changes'] is not None:
            e['changes'] = s['changes']
        if s.get('enum'):
            e['enum'] = {str(k): v for k, v in sorted(s['enum'].items())}
        if s.get('fields'):
            e['fields'] = s['fields']
        cat[s['path']] = e
    total = lambda: sum(e.get('changes') or 0 for e in cat.values() if e['show'])
    budget, cut = sel.get('budget'), sel['depth']
    while budget and total() > budget and cut > 0:   # too much data for one page: drop the deepest shown level
        for p, e in cat.items():
            if e['show'] and depth(p) >= cut:
                e['show'] = False
        cut -= 1
    if cut < sel['depth']:
        print(f'mkconfig: select.budget {budget}: showing scope depth <= {cut} only (was {sel["depth"]})', file=sys.stderr)
    for r in base.get('rules') or []:
        pats = [pattern(p) for p in ([r['match']] if isinstance(r.get('match', '*'), str) else r['match'])] if 'match' in r else [pattern('*')]
        bad = set(r) - {'match', 'width'} - set(vcd2wavedrom.SIG_KEYS)
        if bad:
            die(f'rule {r}: unknown key(s) {", ".join(sorted(bad))}')
        for p, e in cat.items():
            if any(x.match(p) for x in pats) and width_ok(r.get('width'), e['width']):
                e.update({k: v for k, v in r.items() if k not in ('match', 'width')})
    return cat


def typed_mark(e):
    """What a types file gave a signal ("enum" / "fields" as the config has them) -> a short mark, kept in the config's
    "typed" {path: mark}: --update tells the types' own from an edit by it."""
    v = json.dumps({k: e[k] for k in ('enum', 'fields') if k in e}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(v.encode()).hexdigest()[:10]


def merge(old: dict, new: dict, typed=None, was=None):
    """Keep every edit of an existing catalog; take paths, order, width and changes from the dump. "enum" / "fields" of
    a path the types file gave before (was: the config's "typed") and nobody edited since are the types' now (typed:
    {path: mark}, None without a types file): replaced, or gone when it gives none (the type changed, the width no
    longer fits); an edited one and the user's own stay. -> (catalog, "typed" of the new config). A per-signal key the
    converter does not know (a typo) is an error now, not when the page is built."""
    for p, e in old.items():
        bad = set(e or {}) - set(vcd2wavedrom.SIG_KEYS)
        if bad:
            die(f'{p}: unknown signal setting(s) {", ".join(sorted(bad))} (have: {", ".join(vcd2wavedrom.SIG_KEYS)})')
    typed, was = dict(typed or {}), dict(was or {})
    out, kept = {}, []
    for p, e in new.items():
        if p in old:
            mine = {k: old[p][k] for k in ('enum', 'fields') if k in old[p]}
            if p in was and typed_mark(mine) == was[p]:   # the types' before, untouched: the types' (or the dump's) now
                e = {**{k: x for k, x in old[p].items() if k not in mine}, **{k: e[k] for k in INFO if k in e},
                     **{k: e[k] for k in ('enum', 'fields') if k in e}}
            else:
                if mine and p in typed and typed_mark(mine) != typed[p]:
                    kept.append(p)
                    typed.pop(p)   # yours: not the types' any more
                e = {**old[p], **{k: e[k] for k in INFO if k in e}, **{k: e[k] for k in ('enum', 'fields') if k in e and k not in old[p]}}
        out[p] = e
    gone = [p for p in old if p not in new]
    if gone:
        print(f'mkconfig: {len(gone)} signal(s) no longer in the dump, removed: {", ".join(gone[:5])}{" …" if len(gone) > 5 else ""}', file=sys.stderr)
    added = [p for p in new if p not in old]
    print(f'mkconfig: {len(added)} new signal(s) added, {len(out) - len(added)} kept with their settings', file=sys.stderr)
    if kept:
        print(f'mkconfig: --types: {len(kept)} signal(s) keep the "enum" / "fields" written here instead of the types\' '
              f'(take them out of the config to get the types\'): {", ".join(kept[:5])}{" …" if len(kept) > 5 else ""}', file=sys.stderr)
    return out, {p: m for p, m in typed.items() if p in out}


# ---------------- output: readable JSON, one signal per line, a blank line between scopes ----------------
def pretty(v, ind='  '):
    flat = json.dumps(v, ensure_ascii=False)
    if not isinstance(v, (dict, list)) or len(flat) + len(ind) < 110 or not v:
        return flat
    if isinstance(v, list):
        return '[\n' + ',\n'.join(ind + '  ' + pretty(x, ind + '  ') for x in v) + '\n' + ind + ']'
    return '{\n' + ',\n'.join(f'{ind}  {json.dumps(k, ensure_ascii=False)}: {pretty(x, ind + "  ")}' for k, x in v.items()) + '\n' + ind + '}'


def dumps(cfg):
    parts = []
    for k, v in cfg.items():
        if k == 'signals' and isinstance(v, dict):
            rows, prev = [], None
            for p, e in v.items():
                sc = svabuild.split_path(p)[:-1]
                if prev is not None and sc != prev:
                    rows.append('')
                prev = sc
                rows.append(f'    {json.dumps(p, ensure_ascii=False)}: {json.dumps(e, ensure_ascii=False)}')
            body = ',\n'.join(rows).replace('\n,\n', '\n\n')   # blank lines stay blank
            parts.append(f'  "signals": {{\n{body}\n  }}')
        else:
            parts.append(f'  {json.dumps(k)}: {pretty(v)}')
    return '{\n' + ',\n'.join(parts) + '\n}\n'


HELP = [
    'Made by tools/mkconfig.py from {waves} ({n} signals, {shown} shown). Edit freely: make html WAVES={waves} builds the page,',
    'make config WAVES={waves} later adds new signals of the dump and keeps every edit here.',
    'signals: one entry per signal under its full path. "" = the global setting from "config".',
    '  show true/false · radix auto hex dec signed bin oct ascii float q8 sq15 · color "#e03131" (trace, outline, name) · style auto wavedrom questa square',
    '  optional: "alias": "shown name", "fill": "#ffe066" (bus fill), "enum": {"0": "IDLE"}; width/changes are information only.',
    'typed: the signals whose "enum" / "fields" came from the types file (x.types.json): make config takes them from it again unless edited.',
    'config: page-wide WaveLens settings — style (edges: auto | wavedrom slanted | questa / square vertical), radix, theme, colors,',
    '  fold (group depth folded at start, true/false or scope paths), highlight (instances in front at start, e.g. ["tb.dut.u_x"]),',
    '  dim (opacity of the other rows), rowHeight, nameWidth, fontSize, sort, sortIgnore …',
    'views: one section of the page each; a view may set "signals": ["tb.dut.*", "tb.clk"] (patterns over the paths below),',
    '  "from"/"to" ("10us"), "clock": "tb.clk" (clock-sampled instead of exact), "title", "render": view | svg | both,',
    '  "bookmarks": [...], "arrows": [...] (numbered events with text, arrows between them: the viewer\'s Bookmarks › JSON button writes both).',
]


def sva_binds(files, sigs, cat, prefixes, exe, old=()):
    """--sva: the "bind" lines (see the module doc) -> (list, counts) | None when the files do not parse. A generated
    line keeps the user's "show" and keys; what the user wrote that --sva does not make (a "NAME@PATH" string, a
    pattern, an assertion of another file, another instance) stays as it is."""
    fs = svabuild.parse_files([(f, f) for f in files], exe)
    if any(f.get('parsed') is None for f in fs):
        return None
    names = svabuild.Names({s['path']: s['width'] for s in sigs}, {p: e['alias'] for p, e in cat.items() if e.get('alias')}, prefixes)
    prev = {(b.get('assert'), b.get('scope') or ''): b for b in old if isinstance(b, dict)}
    out, made, n = [], set(), {'assertions': 0, 'only': 0, 'chosen': 0, 'open': 0, 'none': 0}
    for f in fs:
        for x in (f.get('parsed') or {}).get('assertions', []):
            n['assertions'] += 1
            cands = names.candidates(x.get('signals') or [])
            if not cands:
                made.add((x['label'], ''))
                out.append({'assert': x['label'], 'scope': '', 'show': False, 'comment': 'no instance of the dump has every signal: ' + ' '.join(s['name'] for s in x.get('signals') or [])})
                n['none'] += 1
            lines = []
            for c in cands:
                p = prev.get((x['label'], c), {})
                made.add((x['label'], c))
                b = {'assert': x['label'], 'scope': c, 'show': p.get('show', len(cands) == 1), **{k: v for k, v in p.items() if k not in ('assert', 'scope', 'show', 'comment')}}
                if len(cands) > 1:
                    b['comment'] = f'one of {len(cands)} instances'
                lines.append(b)
            out += lines
            if cands:
                n['only' if len(cands) == 1 and lines[0]['show'] else 'chosen' if any(b['show'] for b in lines) else 'open'] += 1
    out += [b for b in old if not (isinstance(b, dict) and (b.get('assert'), b.get('scope') or '') in made)]
    return out, n


def read_signals(a):
    """The variables of the dump -> [{path, width, order, changes, enum}] (the built-in reader)."""
    info = dumpscan.scan(a.waves)   # VCD text, or FST through fst2vcd / sva vcd: signals, order, change counts, FST enum tables
    if not info:
        die(f'cannot read {a.waves}: an FST is read through fst2vcd (GTKWave) or the sva CLI, and neither is there')
    decl = a.decl = dumpscan.read(a.waves, None)   # (its $date and modules: the types' fingerprint)
    events = [p for p, v in decl.vars.items() if v.kind == 'event']
    if events:
        print(f'mkconfig: {len(events)} event variable(s) left out (no value to draw): {", ".join(events[:5])}{" …" if len(events) > 5 else ""}', file=sys.stderr)
    sigs = [{'path': p, 'width': v.width, 'kind': v.kind} for p, v in decl.vars.items() if v.kind != 'event']   # (kind: an enum on an integer)
    for i, s in enumerate(sigs):
        d = info.get(s['path']) or {'order': len(info) + i, 'changes': None, 'enum': None}
        s.update(order=d['order'], changes=d['changes'], enum=d['enum'])
    return sigs


def apply_types(a, sigs):
    """--types FILE, or <dump>.types.json beside the dump: enum labels and struct fields by path (tools/svtypes.py) ->
    the paths it gave them, None without a types file."""
    path = a.types or svtypes.beside(a.waves)
    if not path:
        return None
    if not os.path.exists(path):
        die(f'--types: no such file: {path}')
    t = svtypes.load(path)
    m = {**t['map'], **svtypes.map_arg(a.types_map)}
    ne, nf, notes, given = svtypes.apply(t, sigs, m)
    decl = getattr(a, 'decl', None)
    run = svtypes.fingerprint(t, decl and decl.date, decl.modules if decl else (), m)
    if decl:   # what the types declare that the dump has not got (Questa's VCD: unpacked arrays; generate scopes without -r)
        run += svtypes.missing_notes(t, svtypes.missing(t, list(decl.vars), set(decl.modules) | set(decl.scopes), m))
    for n in t['notes'] + notes + run:
        print(f'mkconfig: --types: {n}', file=sys.stderr)
    print(f'mkconfig: --types: {os.path.basename(path)} ({t["producer"].get("tool", "?")}): {len(t["signals"])} typed paths, '
          f'labels for {ne} signals, fields for {nf}', file=sys.stderr)
    return given


def apply_sv(files, sigs):
    """--sv: enum labels and packed-struct fields from the SystemVerilog sources onto the signals of their names."""
    labels, structs, notes = sv_tables(sv_texts(files))
    for note in notes:
        print(f'mkconfig: --sv: {note}', file=sys.stderr)
    leaf = lambda p: svabuild.split_path(re.sub(r'(\.?\[-?\d+\])+$', '', p))[-1]   # an element of an array: the array's name
    n = 0
    for s in sigs:
        t = labels.get(leaf(s['path']))
        if not s['enum'] and t and max(t) < 2 ** s['width']:
            s['enum'] = t; n += 1
    print(f'mkconfig: --sv: {len(labels)} enum-typed names, labels for {n} signals', file=sys.stderr)
    n = 0
    for s in sigs:   # a packed struct dumped as one vector (a VCD; an FST without --trace-structs): its fields
        fl = structs.get(leaf(s['path']))
        if fl and fl[0]['msb'] + 1 == s['width']:
            s['fields'] = fl; n += 1
    if structs:
        print(f'mkconfig: --sv: {len(structs)} struct-typed names, fields for {n} signals', file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('waves', help='VCD or FST dump')
    ap.add_argument('--base', help='base settings (default: tools/base.config.json, if present)')
    ap.add_argument('--out', help='config file to write (default: <dump>.config.json next to the dump)')
    ap.add_argument('--update', action='store_true', help='the output exists: sync its signals with the dump, keep all edits')
    ap.add_argument('--force', action='store_true', help='overwrite an existing output (edits are lost); with --update: update even when most signals are gone')
    ap.add_argument('--depth', type=int, help='override select.depth of the base file')
    ap.add_argument('--types', metavar='FILE', help='the types of the design by path (tools/questa/wavelens_types.tcl, svtypes.py verilator): enum labels and '
                    'struct fields; default: <dump>.types.json beside the dump, when there is one')
    ap.add_argument('--types-map', action='append', metavar='DUMP=TYPES', help='a scope of the dump as the types file names it (top.dut_i=dut; '
                    'again for more; the file\'s own "map" too)')
    ap.add_argument('--sv', nargs='+', metavar='FILE', help='SystemVerilog sources, without a types file: enum labels for signals declared with an enum type, by the variable\'s name (a VCD has none; an FST brings its own), "fields" for a packed struct dumped as one vector')
    ap.add_argument('--sva', nargs='+', action='extend', metavar='FILE', help='SystemVerilog assertion files: "sva" and a "bind" line per instance that has every signal of an assertion')
    add_sva_bin_arg(ap)
    a = ap.parse_args()
    if not os.path.exists(a.waves):
        die(f'no such dump: {a.waves}')
    out = a.out or re.sub(r'\.(vcd|fst|fsdb)$', '', a.waves, flags=re.I) + '.config.json'
    old = None
    if os.path.exists(out) and (a.update or not a.force):   # --update --force: an update past the guard below
        if not a.update:
            die(f'{out} exists: --update keeps your edits and syncs the signals, --force overwrites it')
        old = vcd2wavedrom.load_config(out)
        if not isinstance(old.get('signals'), dict):
            die(f'{out} has no "signals" catalog (not made by mkconfig.py); use another --out or --force')
    base_path = a.base or BASE
    if not a.base and os.path.exists(OLD_BASE):
        print(f'mkconfig: {OLD_BASE} is deprecated and used instead of {BASE}: move it there', file=sys.stderr)
        base_path = OLD_BASE
    base = vcd2wavedrom.load_config(base_path) if (a.base or os.path.exists(base_path)) else {}
    check_config(base.get('config'), f'mkconfig: {base_path}: "config"')
    if a.depth is not None:
        base['select'] = {**(base.get('select') or {}), 'depth': a.depth}

    sigs = read_signals(a)
    typed = apply_types(a, sigs)
    if a.sv and typed is None:
        apply_sv(a.sv, sigs)
    elif a.sv:
        print('mkconfig: --sv is not used: the types file gives the signals their types by path', file=sys.stderr)
    found = sum(1 for s in sigs if s['enum'])
    if found:
        print(f'mkconfig: {found} signals with enum labels (FSM states shown by name)', file=sys.stderr)
    sigs.sort(key=lambda s: s['order'])   # declaration order of the dump
    cat = build(sigs, base)
    if old is not None:
        gone = [p for p in old['signals'] if p not in cat]
        if len(gone) * 2 > len(old['signals']) and not a.force:
            die(f'{len(gone)} of the {len(old["signals"])} signals of {out} are not in {a.waves}: another design? '
                '(--force updates it anyway, keeping the edits of the signals that are still there)')
        cat, marks = merge(old['signals'], cat, typed and {p: typed_mark(cat[p]) for p in typed if p in cat}, old.get('typed'))
    else:
        marks = {p: typed_mark(cat[p]) for p in typed or () if p in cat}

    rel = os.path.relpath(os.path.abspath(a.waves), os.path.dirname(os.path.abspath(out)))
    name = os.path.basename(a.waves)
    if old is not None:
        cfg = {**old, 'signals': cat}
        cfg.pop('typed', None)
        if cfg.get('waves') != rel:   # the config points at the dump it was updated from
            print(f'mkconfig: "waves": {cfg.get("waves")} -> {rel}', file=sys.stderr)
            cfg['waves'] = rel
    else:
        shown = sum(1 for e in cat.values() if e['show'])
        cfg = {'comment': [h.replace('{waves}', a.waves).replace('{n}', str(len(cat))).replace('{shown}', str(shown)) for h in HELP], 'waves': rel}
        for k, v in base.items():
            if k not in GENERATOR_KEYS and k not in ('comment', 'description', 'signals', 'waves'):
                cfg[k] = v
        cfg['page'] = {'title': name, **(cfg.get('page') or {})}
        cfg['signals'] = cat
    if marks:   # what the types file gave: --update replaces it when nobody edited it
        cfg['typed'] = marks
    if a.sva:
        exe = svabuild.find_bin(a.sva_bin)
        if not exe:
            die('--sva needs the sva CLI (make sva-build, or --sva-bin)')
        here = os.path.dirname(os.path.abspath(out))
        pfx = (cfg.get('config') or {}).get('sortIgnore') or []
        got = sva_binds(a.sva, sigs, cat, [pfx] if isinstance(pfx, str) else pfx, exe, cfg.get('bind') or [])
        had = cfg.get('sva') or []
        cfg['sva'] = list(dict.fromkeys([*([had] if isinstance(had, str) else had), *(os.path.relpath(os.path.abspath(f), here) for f in a.sva)]))   # the files it had stay
        if got is None:
            print('mkconfig: --sva: the files do not parse (sva parse failed): "bind" is left as it was', file=sys.stderr)
        else:
            cfg['bind'], n = got
            print(f'mkconfig: --sva: {n["assertions"]} assertions: {n["only"]} bound to their only instance, {n["chosen"]} chosen among several, '
                  f'{n["open"]} with several candidates to choose ("show": false), {n["none"]} without an instance', file=sys.stderr)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(dumps(cfg))
    shown = [e for e in cat.values() if e.get('show')]
    print(f'mkconfig: {len(cat)} signals ({len(shown)} shown, {sum(e.get("changes") or 0 for e in shown)} value changes) -> {out}', file=sys.stderr)


if __name__ == '__main__':
    run_main(main, 'mkconfig')
