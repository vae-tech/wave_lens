#!/usr/bin/env python3
"""svabuild.py — SystemVerilog assertions for a page (docs/USAGE.md "Assertions"), shared by vcd2wavedrom.py and mkhtml.py.

The "sva" files of a config are parsed with the engine's CLI (`sva parse --json`, one compilation unit in the order
given) and its "bind" list is evaluated over the dump (`sva eval`, one run per scope); the result is the WaveJSON
extension "sva" of a view:
  {"files": [{"name", "path", "source", "parsed"}], "bind": [{"assert", "scope", "results"}], "cycles": {"<clock>": [times]},
   "notes": ["…"]}
(each "results.cycles" names its array in "cycles": one copy per clock, not one per binding; intern_cycles / inflate)
mkhtml.py moves "files" and "notes" of every view into window.SVA (once per page); wavelens/sva.js lists the assertions
and draws the bindings. Parse errors do not stop the build: they are printed and the page shows them. report() is the
page's printable "Assertions" section: the bindings evaluated over the whole dump, `sva report --html`.

The CLI: --sva-bin, else $WAVELENS_SVA, else the Makefile's build (out/sva-target/release/sva), else the prebuilt one of
the repository (bin/linux-x86_64/sva: make dist-linux; bin/windows-x86_64/sva.exe when made by make dist-windows), else
`sva` on PATH.
Without it the sources go into the page unparsed and the page parses and evaluates them (WebAssembly).

  svabuild.py --waves dump.fst --sva checks.sv --bind a_req_ack@tb.dut [--from 0ns --to 2us] [--out sva.json]
"""
import argparse, fnmatch, json, os, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import WaveError, add_sva_bin_arg, run_main  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXE = '.exe' if os.name == 'nt' else ''
BUILD_BIN = os.path.join(ROOT, 'out', 'sva-target', 'release', 'sva' + EXE)
DIST_BIN = {('linux', 'x86_64'): 'linux-x86_64/sva', ('win32', 'amd64'): 'windows-x86_64/sva.exe', ('win32', 'x86_64'): 'windows-x86_64/sva.exe'}


def dist_bin():
    import platform
    d = DIST_BIN.get((sys.platform if sys.platform != 'linux2' else 'linux', platform.machine().lower()))
    return os.path.join(ROOT, 'bin', *d.split('/')) if d else None


def find_bin(explicit=None):
    ok = lambda c: c and os.path.isfile(os.path.expanduser(c)) and os.access(os.path.expanduser(c), os.X_OK)
    if explicit:   # given: that one or an error, never another one
        if not ok(explicit):
            raise WaveError(f'svabuild: no sva binary at {explicit}')
        return os.path.expanduser(explicit)
    return next((os.path.expanduser(c) for c in (os.environ.get('WAVELENS_SVA'), BUILD_BIN, dist_bin(), shutil.which('sva')) if ok(c)), None)


def bind_list(items):
    """config "bind" / --bind values -> [{"assert", "scope"}]: {"assert": NAME, "scope": PATH} or "NAME@PATH"; NAME may
    be a pattern with * and ? ("apb_*", "*": every assertion of the files). An entry with "show": false is skipped
    (mkconfig.py --sva lists every instance that matches, chosen ones "show": true)."""
    out = []
    for b in [items] if isinstance(items, (str, dict)) else items or []:
        if isinstance(b, str):
            name, _, scope = b.partition('@')
            b = {'assert': name.strip(), 'scope': scope.strip()}
        if not isinstance(b, dict) or not b.get('assert'):
            raise WaveError(f'svabuild: bad "bind" entry {b!r} (need {{"assert": NAME, "scope": PATH}} or "NAME@PATH")')
        if b.get('show') is False:   # mkconfig.py --sva: a candidate the user has not chosen
            continue
        out.append({'assert': str(b['assert']), 'scope': str(b.get('scope') or '')})
    return out


# ---------------- names of an assertion in an instance: the rule of docs/sva/ENGINE.md *Name resolution* ----------------
# (the same in wavelens/sva.js lookup() / candidates() and in `sva eval --resolve scope --ignore-prefix`; make smoke compares
# the three on the APB example)
def split_path(p: str) -> list:
    """The parts of a hierarchical name: split at the dots, not inside a select (a[1.2]) nor in an escaped
    identifier (\\esc.x, to the end: a dump drops the space that ends it)."""
    out, start, depth = [], 0, 0
    for i, c in enumerate(p):
        if c == '\\' and i == start:
            break
        depth += (c == '[') - (c == ']')
        if c == '.' and not depth:
            out.append(p[start:i]); start = i + 1
    out.append(p[start:])
    return [x for x in out if x]


def _strip(n, pfx):
    p = next((p for p in pfx if n.startswith(p) and len(n) > len(p)), None)
    return n[len(p):] if p else n


class Names:
    """The variables of a dump, {full path: width}, with the shown names ("alias") of a config and the ignored
    prefixes (the page's sortIgnore)."""
    def __init__(self, widths: dict, aliases: dict = None, prefixes=()):
        self.widths, self.aliases = widths, aliases or {}
        self.pfx = sorted(prefixes or [], key=len, reverse=True)
        self.by = {}
        for path in widths:
            *sc, leaf = split_path(path)
            self.by.setdefault('.'.join(sc), []).append((leaf, path))
        self.scopes = list(dict.fromkeys('.'.join(split_path(p)[:k]) for p in widths for k in range(1, len(split_path(p)))))

    def lookup(self, scope, name):
        """name (maybe u_fifo.full) in scope: the variable, else the one shown under that name, else the one equal
        without the ignored prefixes -> path | [paths] (several equal without the prefixes: ambiguous) | None"""
        *sub, base = split_path(name)
        rows = self.by.get('.'.join(x for x in [scope, *sub] if x), [])
        hit = next((p for leaf, p in rows if leaf == base), None) or next((p for leaf, p in rows if self.aliases.get(p) == base), None)
        if hit or not self.pfx:
            return hit
        b = _strip(base, self.pfx)
        hits = [p for leaf, p in rows if _strip(leaf, self.pfx) == b or _strip(self.aliases.get(p, ''), self.pfx) == b]
        return hits if len(hits) > 1 else hits[0] if hits else None

    def resolve(self, scope: str, signals: list) -> tuple:
        """signals [{name, width?}] (the clock first) -> ({name: path}, [problems]); the clock also above the scope"""
        got, bad = {}, []
        for i, s in enumerate(signals):
            hit, up = self.lookup(scope, s['name']), scope
            while not hit and i == 0 and up:
                up = '.'.join(split_path(up)[:-1])
                hit = self.lookup(up, s['name'])
            if not hit:
                bad.append(s['name'])
            elif isinstance(hit, list):
                bad.append(f'{s["name"]} (ambiguous: {" or ".join(hit)})')
            elif s.get('width') and self.widths.get(hit) and s['width'] > self.widths[hit]:
                bad.append(f'{s["name"]}: a select needs {s["width"]} bits, {hit} has {self.widths[hit]}')
            else:
                got[s['name']] = hit
        return got, bad

    def candidates(self, signals):
        """the instances (scopes of the dump, in its order) in which every signal resolves"""
        return [sc for sc in self.scopes if not self.resolve(sc, signals)[1]]


def parse_files(files, exe, quiet=False):
    """files: [(path on disk, path as written)] -> [{name, path, source, parsed | None}]; errors go to stderr."""
    out = []
    for p, shown in files:
        try:
            with open(p, encoding='utf-8', errors='replace') as f:
                src = f.read()
        except OSError as e:
            raise WaveError(f'svabuild: {e}')
        out.append({'name': os.path.basename(p), 'path': shown, 'source': src, 'parsed': None})
    if exe and out:
        r = subprocess.run([exe, 'parse', '--json', *[p for p, _ in files]], capture_output=True, text=True)
        try:
            doc = json.loads(r.stdout)
        except json.JSONDecodeError:
            print(f'svabuild: sva parse failed: {(r.stderr or r.stdout).strip()[:400]}', file=sys.stderr)
            return out
        if len(doc.get('files', [])) != len(out):
            raise WaveError(f'svabuild: sva parse gave {len(doc.get("files", []))} results for {len(out)} files ({", ".join(f["path"] for f in out)})')
        for f, p in zip(out, doc.get('files', [])):
            p.pop('file', None)
            f['parsed'] = p
            for e in [] if quiet else p.get('errors', []):
                print(f'svabuild: {f["path"]}:{e["line"]}:{e["col"]}: {e["msg"]} (the page shows it)', file=sys.stderr)
    return out


def evaluate(binds, files, waves, exe, t_from=None, t_to=None, parsed=(), quiet=False, prefixes=None, aliases=None):
    """Each binding with its results document (docs/sva/ENGINE.md, one assertion) from `sva eval` over the dump, with
    the page's rules for names (--resolve scope: in the scope, below it, the clock also above; the view's shown names
    `aliases` {path: name} and ignored prefixes). -> (bindings, notes)"""
    out, notes = [dict(b) for b in binds], []
    if not out:
        return out, notes
    out = [b for b in out if b['assert']]
    if not exe:
        notes.append('bind: no sva binary at build time (make sva-build): the page evaluates the bindings itself')
        return out, notes
    labels = [a['label'] for f in parsed for a in (f.get('parsed') or {}).get('assertions', [])]
    wild = [b for b in out if any(c in b['assert'] for c in '*?')]   # "assert": "apb_*" binds every match
    if wild and not labels:
        notes.append('bind: patterns ("' + '", "'.join(b['assert'] for b in wild) + '") need the parsed files (no sva binary)')
    for b in wild:
        k = out.index(b)
        hits = [{'assert': n, 'scope': b['scope']} for n in labels if fnmatch.fnmatchcase(n, b['assert'])
                and not any(x['assert'] == n and x['scope'] == b['scope'] for x in out)]
        if labels and not hits:
            notes.append(f"bind: '{b['assert']}' matches no assertion")
        out[k:k + 1] = hits
    by_scope = {}
    for b in out:
        if labels and b['assert'] not in labels:
            notes.append(f"bind: no assertion '{b['assert']}' in {', '.join(f['path'] for f in parsed)}")
            continue
        by_scope.setdefault(b['scope'], []).append(b)
    for scope, bs in by_scope.items():
        with tempfile.TemporaryDirectory() as d:
            res = os.path.join(d, 'results.json')
            argv = [exe, 'eval', '--waves', waves, '--resolve', 'scope'] + (['--scope', scope] if scope else []) + (['--ignore-prefix', ','.join(prefixes)] if prefixes else [])
            for path, name in (aliases or {}).items():
                argv += ['--alias', f'{name}={path}']
            for p, _ in files:
                argv += ['--sva', p]
            for b in bs:
                argv += ['--assert', b['assert']]
            if t_from is not None:
                argv += ['--from', f'{t_from:.0f}ps']
            if t_to is not None:
                argv += ['--to', f'{t_to:.0f}ps']
            r = subprocess.run(argv + ['--out', res], capture_output=True, text=True)
            doc = None
            if os.path.exists(res):
                with open(res, encoding='utf-8') as f:
                    doc = json.load(f)
        if doc is None:   # exit 2 without results: nothing was checked (a syntax error, a dump that does not read)
            raise WaveError(f'svabuild: bind {scope or "(top)"}: sva eval failed (exit {r.returncode}): {(r.stderr or r.stdout).strip()[:300]}')
        for b in bs:
            o = next((o for o in doc['assertions'] if o['name'] == b['assert']), None)
            if o is None:
                notes.append(f"bind: no assertion '{b['assert']}' in the sva files")
                continue
            if o.get('missing') and scope and not _has_scope(waves, scope):   # a typo in the scope: an error, not a note in the page
                raise WaveError(f"svabuild: bind {b['assert']}@{scope}: the dump has no scope {scope} "
                                f"(missing {', '.join(o['missing'])})")
            b['results'] = {'clock': o.pop('clock', None) or doc['clock'], 'unit': doc['unit'], 'cycles': o.pop('cycles', None) or doc['cycles'], 'assertions': [o]}
            s = o['stats']
            if not quiet:
                print(f'svabuild: {b["assert"]} @ {scope or "(top)"}: ' + (f'missing {", ".join(o["missing"])}' if o.get('missing') else
                      f'{s["attempts"]} attempts, {s["pass"]} pass, {s["fail"]} fail'), file=sys.stderr)
    return out, notes


_SCOPES = {}


def _has_scope(waves, scope):
    """Is scope a scope of the dump (a variable under it)? True when the dump's header cannot be read here (an FST
    without fst2vcd or sva vcd): the CLI's note then stands."""
    if waves not in _SCOPES:
        import dumpscan
        try:
            d = dumpscan.read(waves, None)
        except WaveError:
            d = None
        _SCOPES[waves] = None if d is None else {'.'.join(split_path(p)[:k]) for p in d.vars for k in range(1, len(split_path(p)))}
    return _SCOPES[waves] is None or scope in _SCOPES[waves]


def build(files, binds, waves, exe=None, t_from=None, t_to=None, prefixes=None, aliases=None):
    """The WaveJSON "sva" extension of one view (see the module doc); prefixes: the page's sortIgnore; aliases: the
    view's shown names {path: name}."""
    exe = find_bin(exe)
    fs = parse_files(files, exe)
    bs, notes = evaluate(bind_list(binds), files, waves, exe, t_from, t_to, fs, prefixes=prefixes, aliases=aliases)
    doc = {'files': fs, 'bind': bs}
    tables = intern_cycles(bs)
    if tables:
        doc['cycles'] = tables
    if notes:
        doc['notes'] = notes
        for n in notes:
            print('svabuild: ' + n, file=sys.stderr)
    return doc


def intern_cycles(binds):
    """The sampled times of the bindings once per view: each "results.cycles" array becomes a key of the returned table
    {clock path: [times]} (an equal array of the same clock shares it; another one of that clock: "<clock>#2", …). The
    times start at the dump's start (the attempts index them), so a window's arrays are nearly the whole dump's: one
    copy per binding was most of a page's bytes. wavelens/sva.js inflates them back (pageBinds); an array in
    "results.cycles" is still read (older pages, `sva eval --out` given as it is)."""
    tables, ids = {}, {}
    for b in binds:
        r = b.get('results')
        if not r or not isinstance(r.get('cycles'), list):
            continue
        arr = r['cycles']
        key = ids.get(id(arr))
        if key is None:
            base = str(r.get('clock') or 'cycles')
            key = next((k for k, t in tables.items() if k.split('#')[0] == base and t == arr), None)
            if key is None:
                n = sum(k.split('#')[0] == base for k in tables)
                key = base if not n else f'{base}#{n + 1}'
                tables[key] = arr
            ids[id(arr)] = key
        r['cycles'] = key
    return tables


def inflate(doc):
    """The inverse of intern_cycles on a view's "sva" extension (a copy: each binding's "results.cycles" an array again)."""
    tables = (doc or {}).get('cycles') or {}
    out = []
    for b in (doc or {}).get('bind') or []:
        r = b.get('results')
        if r and isinstance(r.get('cycles'), str):
            if r['cycles'] not in tables:
                raise WaveError(f'svabuild: bind {b.get("assert")}@{b.get("scope")}: no cycles table "{r["cycles"]}"')
            b = {**b, 'results': {**r, 'cycles': tables[r['cycles']]}}
        out.append(b)
    return out


def whole(files, binds, waves, exe=None, prefixes=None, aliases=None):
    """The bindings evaluated over the whole dump (a view with a window): their results documents; notes printed."""
    exe = find_bin(exe)
    if not exe or not binds:
        return []
    fs = parse_files(files, exe, quiet=True)
    bs, notes = evaluate(bind_list(binds), files, waves, exe, parsed=fs, quiet=True, prefixes=prefixes, aliases=aliases)
    for n in notes:
        print('svabuild: report: ' + n, file=sys.stderr)
    return [b['results'] for b in bs if b.get('results')]


def report(results, exe=None, meta=None):
    """Results documents (one per binding, over the whole dump) -> (HTML section, summary JSON) of `sva report`, or
    (None, None) without the sva binary or results."""
    exe = find_bin(exe)
    if not exe or not results:
        return None, None
    with tempfile.TemporaryDirectory() as d:
        inp, h, j = (os.path.join(d, n) for n in ('in.json', 'r.html', 'r.json'))
        with open(inp, 'w', encoding='utf-8') as f:
            json.dump({'meta': meta or {}, 'results': results}, f)
        r = subprocess.run([exe, 'report', '--html', h, '--json', j, inp], capture_output=True, text=True)
        if not os.path.exists(h):
            print(f'svabuild: sva report failed: {(r.stderr or r.stdout).strip()[:300]}', file=sys.stderr)
            return None, None
        with open(h, encoding='utf-8') as f, open(j, encoding='utf-8') as g:
            return f.read(), json.load(g)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--waves', required=True, help='VCD or FST')
    ap.add_argument('--sva', action='append', default=[], help='assertion file (repeatable; one compilation unit)')
    ap.add_argument('--bind', action='append', default=[], help='NAME@SCOPE (repeatable)')
    ap.add_argument('--from', dest='t_from', type=float, help='window start in ps')
    ap.add_argument('--to', dest='t_to', type=float, help='window end in ps')
    add_sva_bin_arg(ap)
    ap.add_argument('--out', help='output JSON (default: stdout)')
    a = ap.parse_args()
    doc = build([(p, p) for p in a.sva], a.bind, a.waves, a.sva_bin, a.t_from, a.t_to)
    text = json.dumps(doc, indent=1) + '\n'
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(text)
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    run_main(main, 'svabuild')
