#!/usr/bin/env python3
"""mkconfig.py — make an editable config file for vcd2wavedrom.py / mkhtml.py from a dump: every signal of the dump
under its full hierarchical path, one line each, with per-signal settings to fill in by hand.

  mkconfig.py test_stream_video.vcd                    -> test_stream_video.config.json (next to the dump)
  mkconfig.py dump.vcd --base my.base.json --out my.config.json
  mkconfig.py dump.vcd --out dump.config.json --update # dump changed: add new signals, drop gone ones, keep all edits
  mkconfig.py dump.fst                                 # FST: read through GTKWave's fst2vcd, FSM enum labels included
  mkconfig.py dump.vcd --sv rtl/*.sv                   # VCD: enum labels from "typedef enum", fields of "typedef struct packed"
  mkconfig.py dump.fst --sva checks/*.sva              # assertions: "sva" and a "bind" line per matching instance

Per-signal entry ("" = the global setting from "config"):
  "tb.dut.state": {"show": true, "radix": "", "color": "", "style": "", "width": 3, "changes": 120}
  show   true/false (false: left out of the page)        radix  auto hex dec signed bin oct ascii float q8 sq15
  color  trace / outline / name colour, e.g. "#e03131"   style  auto wavedrom questa square
  also   "alias": "name shown", "fill": "#ffe066" (bus fill), "enum": {"0": "IDLE", "1": "RUN"}
  width and changes (value changes in the dump) are information only. "enum" is filled from the dump (FST enum tables)
  or from --sv sources, so FSM states show by name. A $dumpoff block (every value x) counts as changes; event
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
"waves" at the dump it read.
"""
import argparse, json, os, re, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # -I drops the script dir from sys.path
import dumpscan, svabuild, vcd2wavedrom  # noqa: E402
from common import SELECT_KEYS, WaveError, add_reader_args, add_sva_bin_arg, check_config, glob_re, run_main, wavepeek  # noqa: E402

ROOT = os.path.dirname(HERE)
BASE = os.path.join(HERE, 'base.config.json')
OLD_BASE = os.path.join(ROOT, 'wavefw.base.json')   # name before the restructure, read with a warning
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


# ---------------- the dump: signals (wavepeek) + declaration order and change counts (VCD text) ----------------
def list_signals(exe, waves):
    """[{'path', 'width'}] for every signal of the dump (wavepeek: works for VCD and FST)."""
    run = vcd2wavedrom.Peek(exe, waves, None).run
    scopes = [s['path'] for s in run('scope', '--max-depth', '0', '--max', 'unlimited')['data']]
    out = []
    for sc in scopes:
        out += [{'path': s['path'], 'width': s.get('width') or 1}
                for s in run('signal', '--scope', sc, '--recursive', '--max-depth', 'unlimited', '--max', 'unlimited', '--abs')['data']]
    return out


# ---------------- enum labels from SystemVerilog sources (VCD has none; FST carries its own tables) ----------------
SV_WORDS = {'input', 'output', 'inout', 'ref', 'var', 'const', 'static', 'automatic', 'logic', 'wire', 'reg', 'bit', 'signed', 'unsigned'}


def sv_value(v, prev):
    v = v.strip().replace('_', '')
    if not v:
        return prev + 1
    m = re.fullmatch(r"(?:\d+)?'[sS]?([bodhBODH])([0-9a-fA-F]+)", v)
    if m:
        return int(m.group(2), {'b': 2, 'o': 8, 'd': 10, 'h': 16}[m.group(1).lower()])
    return int(v, 0) if re.fullmatch(r'\d+|0[xX][0-9a-fA-F]+', v) else prev + 1


SV_BASE = {'logic': 1, 'bit': 1, 'reg': 1, 'wire': 1, 'byte': 8, 'shortint': 16, 'int': 32, 'integer': 32, 'longint': 64}


def sv_dims(s):
    """Packed dimensions "[7:0][1:0]" -> the number of bits they hold (1 for none), None when a bound is not a number."""
    n = 1
    for d in re.findall(r'\[([^\]]*)\]', s):
        m = re.fullmatch(r'\s*(\d+)\s*:\s*(\d+)\s*', d)
        if not m:
            return None
        n *= abs(int(m.group(1)) - int(m.group(2))) + 1
    return n


def sv_structs(files):
    """typedef struct packed {…} name_t; + declarations "name_t status;" -> {variable name: [{name, msb, lsb, enum?}]}, the
    fields MSB first. A member's type: logic / bit / reg [m:n] … int / byte …, or a typedef enum / struct of these files
    (an enum's base type gives its width: "typedef enum logic [2:0]"; none: 32). A struct with a member of an unknown
    width is left out."""
    texts = []
    for f in files:
        with open(f, encoding='utf-8', errors='replace') as fh:
            texts.append(re.sub(r'//[^\n]*|/\*.*?\*/', ' ', fh.read(), flags=re.S))
    widths, labels, bodies = {}, {}, {}
    for t in texts:
        for m in re.finditer(r'\btypedef\s+enum\b\s*([^{;]*)\{([^}]*)\}\s*(\w+)\s*;', t):
            base = m.group(1).strip()
            bm = re.fullmatch(r'(\w+)?\s*(?:signed|unsigned)?\s*((?:\[[^\]]*\]\s*)*)', base)
            w = (SV_BASE.get(bm.group(1), None) if bm and bm.group(1) else 32) if bm else None
            d = sv_dims(bm.group(2)) if bm else None
            if w is not None and d is not None:
                widths[m.group(3)] = w * d
            table, v = {}, -1
            for it in m.group(2).split(','):
                name, _, val = it.partition('=')
                if re.fullmatch(r'\w+', name.strip()):
                    v = sv_value(val, v); table[v] = name.strip()
            labels[m.group(3)] = table
        for m in re.finditer(r'\btypedef\s+struct\s+packed\b[^{;]*\{([^}]*)\}\s*(\w+)\s*;', t):
            bodies[m.group(2)] = m.group(1)
    fields = {}
    for _ in range(len(bodies) + 1):   # nested typedefs: until nothing new resolves
        for name, body in bodies.items():
            if name in fields:
                continue
            members = []
            for decl in filter(None, (x.strip() for x in body.split(';'))):
                m = re.fullmatch(r'(?:\w+::)?(\w+)\s*(?:signed|unsigned)?\s*((?:\[[^\]]*\]\s*)*)(\w+(?:\s*,\s*\w+)*)', decl)
                base = m and (SV_BASE.get(m.group(1)) or widths.get(m.group(1)))
                d = m and sv_dims(m.group(2))
                if not base or d is None:
                    members = None
                    break
                members += [(n.strip(), base * d, labels.get(m.group(1))) for n in m.group(3).split(',')]
            if members:
                lsb, out = sum(w for _, w, _ in members), []
                for n, w, e in members:
                    lsb -= w
                    out.append({'name': n, 'msb': lsb + w - 1, 'lsb': lsb, **({'enum': {str(k): v for k, v in sorted(e.items())}} if e else {})})
                fields[name] = out; widths[name] = sum(w for _, w, _ in members)
    out = {}
    for t in texts:
        for name, fl in fields.items():
            for m in re.finditer(r'\b(?:\w+::)?' + re.escape(name) + r'\b\s+(\w+(?:\s*,\s*\w+)*)\s*[;=,)]', t):
                for n in m.group(1).split(','):
                    if n.strip() and n.strip() not in SV_WORDS:
                        out[n.strip()] = fl
    return out


def sv_enums(files):
    """typedef enum … {A, B = 2'd3, …} name_t; + declarations "name_t state_q, state_d;" / "enum {…} st;" ->
    {variable name: {value: label}} (by name only: a variable with that name in any scope gets the labels)."""
    out, types = {}, {}
    def items(body):
        table, v = {}, -1
        for it in body.split(','):
            name, _, val = it.partition('=')
            name = name.strip()
            if re.fullmatch(r'\w+', name):
                v = sv_value(val, v); table[v] = name
        return table
    texts = []
    for f in files:
        with open(f, encoding='utf-8', errors='replace') as fh:
            texts.append(re.sub(r'//[^\n]*|/\*.*?\*/', ' ', fh.read(), flags=re.S))
    for t in texts:
        for m in re.finditer(r'\btypedef\s+enum\b[^{;]*\{([^}]*)\}\s*(\w+)\s*;', t):
            types[m.group(2)] = items(m.group(1))
        for m in re.finditer(r'(?<!typedef)\s\benum\b[^{;]*\{([^}]*)\}\s*(\w+(?:\s*,\s*\w+)*)\s*;', t):
            for n in m.group(2).split(','):
                out[n.strip()] = items(m.group(1))
    for t in texts:
        for name, table in types.items():
            for m in re.finditer(r'\b(?:\w+::)?' + re.escape(name) + r'\b\s+(?:\[[^\]]*\]\s*)*(\w+(?:\s*(?:\[[^\]]*\]\s*)*,\s*\w+)*)', t):
                for n in re.split(r'\s*(?:\[[^\]]*\]\s*)*,\s*', m.group(1)):
                    if n and n not in SV_WORDS and n not in types:
                        out[n] = table
    return out


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


def merge(old: dict, new: dict) -> dict:
    """Keep every edit of an existing catalog; take paths, order, width and changes from the dump. A per-signal key
    the converter does not know (a typo) is an error now, not when the page is built."""
    for p, e in old.items():
        bad = set(e or {}) - set(vcd2wavedrom.SIG_KEYS)
        if bad:
            die(f'{p}: unknown signal setting(s) {", ".join(sorted(bad))} (have: {", ".join(vcd2wavedrom.SIG_KEYS)})')
    out = {}
    for p, e in new.items():
        if p in old:
            e = {**old[p], **{k: e[k] for k in INFO if k in e}, **{k: e[k] for k in ('enum', 'fields') if k in e and k not in old[p]}}
        out[p] = e
    gone = [p for p in old if p not in new]
    if gone:
        print(f'mkconfig: {len(gone)} signal(s) no longer in the dump, removed: {", ".join(gone[:5])}{" …" if len(gone) > 5 else ""}', file=sys.stderr)
    added = [p for p in new if p not in old]
    print(f'mkconfig: {len(added)} new signal(s) added, {len(out) - len(added)} kept with their settings', file=sys.stderr)
    return out


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
    'config: page-wide wavefw settings — style (edges: auto | wavedrom slanted | questa / square vertical), radix, theme, colors,',
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
    """The variables of the dump -> [{path, width, order, changes, enum}] (the built-in reader, or wavepeek)."""
    info = dumpscan.scan(a.waves)   # VCD text, or FST through fst2vcd: signals, order, change counts, FST enum tables
    if a.reader == 'wavepeek' or not info:
        exe = wavepeek(a.wavepeek)
        if not os.path.exists(exe):
            die('wavepeek not found (cargo build it, see README.md)' if info else 'cannot read the dump: no fst2vcd for an FST and no wavepeek')
        sigs = list_signals(exe, a.waves)
    else:   # the same paths and widths as wavepeek lists them
        decl = dumpscan.read(a.waves, None)
        events = [p for p, v in decl.vars.items() if v.kind == 'event']
        if events:
            print(f'mkconfig: {len(events)} event variable(s) left out (no value to draw): {", ".join(events[:5])}{" …" if len(events) > 5 else ""}', file=sys.stderr)
        sigs = [{'path': p, 'width': v.width} for p, v in decl.vars.items() if v.kind != 'event']
    for i, s in enumerate(sigs):
        d = info.get(s['path']) or {'order': len(info) + i, 'changes': None, 'enum': None}
        s.update(order=d['order'], changes=d['changes'], enum=d['enum'])
    return sigs


def apply_sv(files, sigs):
    """--sv: enum labels and packed-struct fields from the SystemVerilog sources onto the signals of their names."""
    labels, n = sv_enums(files), 0
    for s in sigs:
        leaf = re.sub(r'\[\d+\]$', '', svabuild.split_path(s['path'])[-1])
        t = labels.get(leaf)
        if not s['enum'] and t and max(t) < 2 ** s['width']:
            s['enum'] = t; n += 1
    print(f'mkconfig: --sv: {len(labels)} enum-typed names, labels for {n} signals', file=sys.stderr)
    structs, n = sv_structs(files), 0
    for s in sigs:   # a packed struct dumped as one vector (a VCD; an FST without --trace-structs): its fields
        fl = structs.get(re.sub(r'\[\d+\]$', '', svabuild.split_path(s['path'])[-1]))
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
    ap.add_argument('--sv', nargs='+', metavar='FILE', help='SystemVerilog sources: enum labels for signals declared with an enum type (a VCD has none; an FST brings its own), "fields" for a packed struct dumped as one vector')
    add_reader_args(ap, 'builtin')
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
    if a.sv:
        apply_sv(a.sv, sigs)
    found = sum(1 for s in sigs if s['enum'])
    if found:
        print(f'mkconfig: {found} signals with enum labels (FSM states shown by name)', file=sys.stderr)
    sigs.sort(key=lambda s: s['order'])   # declaration order of the dump (wavepeek lists alphabetically)
    cat = build(sigs, base)
    if old is not None:
        gone = [p for p in old['signals'] if p not in cat]
        if len(gone) * 2 > len(old['signals']) and not a.force:
            die(f'{len(gone)} of the {len(old["signals"])} signals of {out} are not in {a.waves}: another design? '
                '(--force updates it anyway, keeping the edits of the signals that are still there)')
        cat = merge(old['signals'], cat)

    rel = os.path.relpath(os.path.abspath(a.waves), os.path.dirname(os.path.abspath(out)))
    name = os.path.basename(a.waves)
    if old is not None:
        cfg = {**old, 'signals': cat}
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
