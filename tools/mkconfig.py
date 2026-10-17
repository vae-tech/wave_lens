#!/usr/bin/env python3
"""mkconfig.py — make an editable config file for vcd2wavedrom.py / mkhtml.py from a dump: every signal of the dump
under its full hierarchical path, one line each, with per-signal settings to fill in by hand.

  mkconfig.py test_stream_video.vcd                    -> test_stream_video.config.json (next to the dump)
  mkconfig.py dump.vcd --base my.base.json --out my.config.json
  mkconfig.py dump.vcd --out dump.config.json --update # dump changed: add new signals, drop gone ones, keep all edits

Per-signal entry ("" = the global setting from "config"):
  "tb.dut.state": {"show": true, "radix": "", "color": "", "style": "", "width": 3, "changes": 120}
  show   true/false (false: left out of the page)        radix  auto hex dec signed bin oct ascii
  color  trace / outline / name colour, e.g. "#e03131"   style  auto wavedrom questa square
  also   "alias": "name shown", "fill": "#ffe066" (bus fill), "enum": {"0": "IDLE", "1": "RUN"}
  width and changes (value changes in the dump) are information only.

Base file (--base, default wavefw.base.json in the project root): copied into the new config, except two generator keys
  "select" {"depth": 2, "constants": false, "hide": ["$rootio.*"], "budget": 1500000}  which signals start with
           "show": true — scope depth <= depth below the top, not constant, not hidden, at most `budget` value changes
           in total (the deepest levels are dropped first)
  "rules"  [{"match": ["*clk", "*clk_i"], "width": 1, "color": "#2f9e44"}, …]  starting settings by full-path pattern
           ("*" and "?"; optional "width": 8 / ">1" / ">=32"); later rules win, and they may set "show" too.
"""
import argparse, collections, json, os, re, shutil, subprocess, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # -I drops the script dir from sys.path
import vcd2wavedrom  # noqa: E402

ROOT = os.path.dirname(HERE)
ENTRY = ('show', 'radix', 'color', 'style')          # keys every entry gets (empty = global setting)
INFO = ('width', 'changes')
GENERATOR_KEYS = ('select', 'rules')
SPLIT = re.compile(r'\.(?![^\[]*\])')               # path separators, not dots inside [..]


def die(msg):
    raise SystemExit('mkconfig: ' + msg)


def pattern(p):
    return re.compile(''.join('.*' if c == '*' else '.' if c == '?' else re.escape(c) for c in p) + r'\Z')


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


def scan_vcd(path):
    """VCD -> {signal path: (declaration index, value changes)}; the $dumpvars initial value is not a change.
    wavepeek names differ for arrays: "mem[1] [7:0]" is "mem.[1]", bit-blasted "err[0]".."err[3]" is one vector "err"."""
    with open(path, 'rb') as f:
        data = f.read()
    end = data.find(b'$enddefinitions')
    if end < 0:
        return {}
    ids, info, scope, n = collections.defaultdict(list), {}, [], 0
    for tok in (line.split() for line in data[:end].split(b'\n')):
        if not tok:
            continue
        if tok[0] == b'$scope' and len(tok) > 2:
            scope.append(tok[2].decode(errors='replace'))
        elif tok[0] == b'$upscope' and scope:
            scope.pop()
        elif tok[0] == b'$var' and len(tok) > 4:
            ref = tok[4].decode(errors='replace')
            p = '.'.join(scope + [ref])
            keys = [p] + ([p + tok[5].decode()] if len(tok) > 6 and tok[5].startswith(b'[') else [])
            if '[' in ref and not ref.startswith('['):
                keys.append('.'.join(scope + [ref.replace('[', '.[')]))
                keys.append(('+', '.'.join(scope + [ref[:ref.index('[')]])))   # bits of a blasted vector
            ids[tok[3]].append((n, keys)); n += 1
    cnt = collections.Counter(l[1:].strip() if l[0] in b'01xzXZ' else l.rpartition(b' ')[2].strip()
                              for l in data[end:].split(b'\n') if l and l[0] in b'01xzXZbBrR')
    vec = {}
    for code, decls in ids.items():
        for i, keys in decls:
            for k in keys:
                if isinstance(k, tuple):
                    o, c = vec.get(k[1], (i, 0)); vec[k[1]] = (min(o, i), c + max(0, cnt[code] - 1))
                else:
                    info.setdefault(k, (i, max(0, cnt[code] - 1)))
    return {**vec, **info}


# ---------------- catalog ----------------
def build(sigs, base):
    sel = {'depth': 2, 'constants': False, 'hide': [], 'budget': 1500000, **(base.get('select') or {})}
    hide = [pattern(p) for p in ([sel['hide']] if isinstance(sel['hide'], str) else sel['hide'] or [])]
    depth = lambda p: len(SPLIT.split(p)) - 2
    cat = {}
    for s in sigs:
        e = {k: '' for k in ENTRY}
        e['show'] = (depth(s['path']) <= sel['depth'] and (sel['constants'] or s['changes'] != 0)
                     and not any(h.match(s['path']) for h in hide))
        e['width'] = s['width']
        if s['changes'] is not None:
            e['changes'] = s['changes']
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


def merge(old, new):
    """Keep every edit of an existing catalog; take paths, order, width and changes from the dump."""
    out = {}
    for p, e in new.items():
        if p in old:
            e = {**old[p], **{k: e[k] for k in INFO if k in e}}
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
                sc = SPLIT.split(p)[:-1]
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
    '  show true/false · radix auto hex dec signed bin oct ascii · color "#e03131" (trace, outline, name) · style auto wavedrom questa square',
    '  optional: "alias": "shown name", "fill": "#ffe066" (bus fill), "enum": {"0": "IDLE"}; width/changes are information only.',
    'config: page-wide wavefw settings — style (edges: auto | wavedrom slanted | questa / square vertical), radix, theme, colors,',
    '  fold (group depth folded at start, true/false or scope paths), rowHeight, nameWidth, fontSize, sort, sortIgnore …',
    'views: one section of the page each; a view may set "signals": ["tb.dut.*", "tb.clk"] (patterns over the paths below),',
    '  "from"/"to" ("10us"), "clock": "tb.clk" (clock-sampled instead of exact), "title", "render": view | svg | both.',
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('waves', help='VCD or FST dump')
    ap.add_argument('--base', help='base settings (default: wavefw.base.json in the project root, if present)')
    ap.add_argument('--out', help='config file to write (default: <dump>.config.json next to the dump)')
    ap.add_argument('--update', action='store_true', help='the output exists: sync its signals with the dump, keep all edits')
    ap.add_argument('--force', action='store_true', help='overwrite an existing output (edits are lost)')
    ap.add_argument('--depth', type=int, help='override select.depth of the base file')
    ap.add_argument('--wavepeek', help='wavepeek executable (default: on PATH or ~/.local/bin)')
    a = ap.parse_args()
    if not os.path.exists(a.waves):
        die(f'no such dump: {a.waves}')
    out = a.out or re.sub(r'\.(vcd|fst|fsdb)$', '', a.waves, flags=re.I) + '.config.json'
    old = None
    if os.path.exists(out) and not a.force:
        if not a.update:
            die(f'{out} exists: --update keeps your edits and syncs the signals, --force overwrites it')
        old = vcd2wavedrom.load_config(out)
        if not isinstance(old.get('signals'), dict):
            die(f'{out} has no "signals" catalog (not made by mkconfig.py); use another --out or --force')
    base_path = a.base or os.path.join(ROOT, 'wavefw.base.json')
    base = vcd2wavedrom.load_config(base_path) if (a.base or os.path.exists(base_path)) else {}
    if a.depth is not None:
        base['select'] = {**(base.get('select') or {}), 'depth': a.depth}

    exe = os.path.expanduser(a.wavepeek or shutil.which('wavepeek') or '~/.local/bin/wavepeek')
    if not os.path.exists(exe):
        die('wavepeek not found (cargo build it, see README.md)')
    sigs = list_signals(exe, a.waves)
    info = scan_vcd(a.waves) if a.waves.lower().endswith('.vcd') else {}
    for i, s in enumerate(sigs):
        s['order'], s['changes'] = info.get(s['path'], (len(info) + i, None))
    sigs.sort(key=lambda s: s['order'])   # declaration order of the dump (wavepeek lists alphabetically)
    cat = build(sigs, base)
    if old is not None:
        cat = merge(old['signals'], cat)

    rel = os.path.relpath(os.path.abspath(a.waves), os.path.dirname(os.path.abspath(out)))
    name = os.path.basename(a.waves)
    if old is not None:
        cfg = {**old, 'signals': cat}
    else:
        shown = sum(1 for e in cat.values() if e['show'])
        cfg = {'comment': [h.replace('{waves}', a.waves).replace('{n}', str(len(cat))).replace('{shown}', str(shown)) for h in HELP], 'waves': rel}
        for k, v in base.items():
            if k not in GENERATOR_KEYS and k not in ('comment', 'description', 'signals', 'waves'):
                cfg[k] = v
        cfg['page'] = {'title': name, **(cfg.get('page') or {})}
        cfg['signals'] = cat
    with open(out, 'w', encoding='utf-8') as f:
        f.write(dumps(cfg))
    shown = [e for e in cat.values() if e.get('show')]
    print(f'mkconfig: {len(cat)} signals ({len(shown)} shown, {sum(e.get("changes") or 0 for e in shown)} value changes) -> {out}', file=sys.stderr)


if __name__ == '__main__':
    main()
