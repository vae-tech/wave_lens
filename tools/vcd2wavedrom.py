#!/usr/bin/env python3
"""vcd2wavedrom.py — convert a window of a VCD/FST dump into WaveDrom JSON, using wavepeek for every query.
Enum labels (FSM states) come from the config ("enum", per-signal "enum") or from the dump's own enum tables (FST).

Modes
  --clock CLK   one WaveDrom cycle per period of CLK. Values are sampled with
                `wavepeek change --on 'posedge CLK' --sample-mode native` (the value after the edge, i.e. what
                holds during the cycle). Output is plain WaveDrom (wave strings + data) plus the "time"
                extension, so it renders in stock WaveDrom too.
  --exact       exact transitions per signal in the "tv" extension (`--on '*' --row-mode sparse`), which
                wavefw.js draws at their real timestamps. A wave string quantised to a --cycle grid is added
                as a fallback for stock WaveDrom.

Config file (--config cfg.json): every option can be a key (dashes or underscores), command-line options win.
  "signals" list or comma string, or a catalog {full.path: {per-signal settings}} (what mkconfig.py writes),
  "enum" {sig: {"0": "IDLE"}}, "group" {name: [sigs]}, "hierarchy" true (nest signals in groups by scope),
  "gap" ["A:B"], "marker" ["EXPR=label"], "bookmarks" [{"n": 1, "t": 85120000, "signal": "tb.x", "text": "…"}], "arrows" [{"from": 1, "to": 2}],
  "config" {...} (copied into the WaveJSON "config": theme, colors,
  style, radix, fold, rowHeight, sort, …), "views" {key: {...}} named variants of the top-level settings (pick one
  with --view; mkhtml.py builds them all). With a catalog, a view's "signals" list selects from it ("*" and "?"
  patterns match full paths). Relative "waves" paths are relative to the config file.
  "sva" ["checks.sv", …] SystemVerilog assertion files (parsed with the sva CLI, inlined for the page's assertions
  panel), "bind" [{"assert": "a_req_ack", "scope": "tb.dut"}] or ["a_req_ack@tb.dut"] (evaluated over the dump with
  sva eval; the page opens with them bound): the WaveJSON extension "sva" (tools/svabuild.py, docs/USAGE.md "Assertions").
  "exprs" ["PSEL && !PREADY", "@(posedge PCLK) $rose(req)", {"expr": "…", "scope": "tb.dut"}] expressions of the signals the
  page draws as rows "ƒ expressions" (valued in the page: names from the scope up, or full paths).
  Clock-sampled buses get "width" and, when their labels do not read back as values (bin signed oct ascii, x digits),
  "raw": the hex value of each label (the page's assertions sample them).
  Per-signal settings: show (false: left out), alias (displayed name), radix (auto hex dec signed bin oct ascii),
  color (trace / outline / name), fill (bus fill), style (auto wavedrom questa square), enum {"0": "IDLE"}, enumColors
  {"IDLE": "#ffe066"}, analog true / rows (a bus as a step plot, that many rows high); radix also float, q8, sq15;
  width and changes are information only.

Examples
  python3 -I tools/vcd2wavedrom.py --waves dump.vcd --scope tb --clock clk --from 0ns --to 400ns \
      --signals clk,state,data=DATA --enum state=0:IDLE,1:RUN --gap 200ns:300ns --out cyc.json
  python3 -I tools/vcd2wavedrom.py --waves dump.vcd --scope tb --exact --from 0ns --to 2us \
      --signals clk,txd,state --group tx=state,txd --marker 'posedge done=done' --out exact.json
  python3 -I tools/vcd2wavedrom.py --config dump.config.json --view exact --out exact.json
"""
import argparse, bisect, concurrent.futures, decimal, functools, heapq, json, math, os, re, shutil, statistics, struct, subprocess, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
import dumpscan, svabuild, wavejson  # noqa: E402

UNIT_PS = {'zs': 1e-9, 'as': 1e-6, 'fs': 1e-3, 'ps': 1, 'ns': 1e3, 'us': 1e6, 'ms': 1e9, 's': 1e12}


@functools.lru_cache(maxsize=1 << 16)   # wavepeek repeats the same time strings in every chunk
def to_ps(s):
    m = re.fullmatch(r'\s*([\d.]+(?:e-?\d+)?)\s*(zs|as|fs|ps|ns|us|ms|s)\s*', str(s))
    if not m:
        raise SystemExit(f'vcd2wavedrom: bad time "{s}" (need a unit, e.g. 250ns)')
    return float(m.group(1)) * UNIT_PS[m.group(2)]


class Peek:
    """Thin wrapper around the wavepeek CLI (--json output)."""
    def __init__(self, exe, waves, scope):
        self.exe, self.waves, self.scope = exe, waves, scope
        info = self.run('info')['data'][0]
        m = re.fullmatch(r'(\d+)(zs|as|fs|ps|ns|us|ms|s)', info['time_unit'])
        self.unit = (int(m.group(1)), m.group(2))
        self.unit_ps = int(m.group(1)) * UNIT_PS[m.group(2)]
        self.t_start, self.t_end = to_ps(info['time_start']), to_ps(info['time_end'])
        self.version = subprocess.run([exe, '-V'], capture_output=True, text=True).stdout.strip()

    def t(self, ps):  # ps -> wavepeek time literal in dump units (times must align with the dump resolution)
        n = round(ps / self.unit_ps)
        return f'{n * self.unit[0]}{self.unit[1]}'

    def chunks(self, paths, parts=1, limit=100000):   # one argv string must stay below the OS limit (128 KiB on Linux)
        out, cur, n, size = [], [], 0, max(1, -(-len(paths) // parts))
        for p in paths:
            if cur and (n + len(p) + 1 > limit or len(cur) >= size):
                out.append(cur); cur, n = [], 0
            cur.append(p); n += len(p) + 1
        return out + [cur] if cur else out

    def run_signals(self, cmd, paths, *args):
        """`wavepeek cmd ... --signals paths`, split into several calls for long lists (run in parallel: each call reads
        the whole dump, so a long "change" query is spread over the CPUs); results merged per row."""
        parts = min(os.cpu_count() or 1, 8, max(1, len(paths) // 40)) if cmd == 'change' else 1
        cs = self.chunks(paths, parts)
        with concurrent.futures.ThreadPoolExecutor(len(cs)) as ex:
            docs = list(ex.map(lambda c: self.run(cmd, *args, '--signals', ','.join(c), scoped=True)['data'], cs))
        if len(docs) == 1:
            return docs[0]
        if cmd == 'value' or '--row-mode' in args and args[args.index('--row-mode') + 1] == 'dense':
            rows = docs[0]
            for d in docs[1:]:
                for r, r2 in zip(rows, d):
                    r['signals'] += r2['signals']
            return rows
        return list(heapq.merge(*docs, key=lambda r: to_ps(r['time'])))   # sparse rows, each chunk already in time order

    def run(self, cmd, *args, scoped=False):
        argv = [self.exe, cmd, '--waves', self.waves, *args, '--json']
        if scoped and self.scope:
            argv += ['--scope', self.scope]
        p = subprocess.run(argv, capture_output=True, text=True)
        try:
            doc = json.loads(p.stdout)
        except json.JSONDecodeError:
            raise SystemExit(f'vcd2wavedrom: wavepeek {cmd} failed:\n{p.stderr or p.stdout}')
        if p.returncode or doc.get('type') != 'result':
            raise SystemExit(f'vcd2wavedrom: wavepeek {cmd} failed: {json.dumps(doc.get("error", doc))}')
        for d in doc.get('diagnostics', []):
            print(f'wavepeek {d.get("kind")}: {d.get("message")}', file=sys.stderr)
        return doc


    # ---- reader interface (shared with Builtin): prepare, base, changes, sampled, events ----
    tool = property(lambda self: 'wavepeek ' + self.version)

    def prepare(self, paths, clock=None, events=()):
        """-> [(canonical path, width)]; the width comes from the value literal ("7'h00"), so bit selects work too."""
        self.paths = paths
        b = self.run_signals('value', paths, '--at', self.t(self.t_start))[0]['signals']
        self.specs = []
        for p, x in zip(paths, b):
            lit, sel = re.match(r"(\d+)'", x['value']), re.search(r'\[(\d+):(\d+)\]$', p)
            self.specs.append((x['path'], int(lit.group(1)) if lit else abs(int(sel.group(1)) - int(sel.group(2))) + 1 if sel else 1))
        return self.specs

    def base(self, t):
        b = self.run_signals('value', self.paths, '--at', self.t(t))[0]['signals']
        return [norm(x['value'], w) for x, (_, w) in zip(b, self.specs)]

    def changes(self, t0, t1):   # -> per path [(t, value)] in [t0, t1]
        rows = self.run_signals('change', self.paths, '--from', self.t(t0), '--to', self.t(t1), '--on', '*', '--sample-mode', 'native',
                                '--row-mode', 'sparse', '--row-values', 'delta', '--max', 'unlimited')
        idx = {pa: i for i, (pa, _) in enumerate(self.specs)}
        out = [[] for _ in self.specs]
        for r in rows:
            t = to_ps(r['time'])
            for v in r['signals']:
                i = idx[v['path']]; out[i].append((t, norm(v['value'], self.specs[i][1])))
        return out

    def sampled(self, clock, t0, t1):   # -> (posedge times, per path [value after each edge])
        rows = self.run_signals('change', self.paths, '--from', self.t(t0), '--to', self.t(t1), '--on', f'posedge {clock}',
                                '--sample-mode', 'native', '--row-mode', 'dense', '--row-values', 'full', '--max', 'unlimited')
        return [to_ps(r['time']) for r in rows], [[norm(r['signals'][j]['value'], w) for r in rows] for j, (_, w) in enumerate(self.specs)]

    def events(self, expr, t0, t1):   # any wavepeek --on expression
        return [to_ps(r['time']) for r in self.run('change', '--from', self.t(t0), '--to', self.t(t1), '--on', expr, '--sample-mode', 'native',
                                                    '--max', 'unlimited', '--signals', self.paths[0], scoped=True)['data']]


class Builtin:
    """The built-in reader: one pass over the dump as VCD text (an FST through fst2vcd), keeping only the requested
    signals; the window, clock sampling and markers are then computed in memory. Paths as wavepeek spells them."""
    EVENT = re.compile(r'\s*(?:(posedge|negedge|edge)\s+)?([^\s()|&!=<>~^*]+)\s*')

    def __init__(self, waves, scope):
        self.waves, self.scope = waves, scope
        self.decl = dumpscan.read(waves, None)
        self.tool = 'wavefw reader' + ('' if waves.lower().endswith('.vcd') else ' (fst2vcd)')
        self.streams = {}

    def resolve(self, p):
        q = p if not self.scope or p.startswith(self.scope + '.') else self.scope + '.' + p
        hit = self.decl.find(q)
        if hit:
            return hit, None
        m = re.fullmatch(r'(.+)\[(\d+):(\d+)\]', q)
        if m and self.decl.find(m.group(1)):
            return self.decl.find(m.group(1)), (int(m.group(2)), int(m.group(3)))
        raise SystemExit(f'vcd2wavedrom: no signal "{p}" in {os.path.basename(self.waves)}' + (f' (scope {self.scope})' if self.scope else ''))

    def event_signal(self, expr):
        m = self.EVENT.fullmatch(expr)
        if not m:
            raise SystemExit(f'vcd2wavedrom: the built-in reader takes markers "posedge X", "negedge X", "edge X" or "X" (any change); '
                             f'for "{expr}" use --reader wavepeek')
        return m.group(1) or 'change', m.group(2)

    def prepare(self, paths, clock=None, events=()):
        self.res = [self.resolve(p) for p in paths]
        extra = ([self.resolve(clock)] if clock else []) + [self.resolve(self.event_signal(e)[1]) for e in events]
        codes = {c for path, _ in self.res + extra for c, _ in self.decl.vars[path].members}
        self.d = dumpscan.read(self.waves, 'collect', codes)
        self.t_start, self.t_end = self.d.t_start, self.d.t_end
        self.specs = [(path + (f'[{sl[0]}:{sl[1]}]' if sl else ''), sl[0] - sl[1] + 1 if sl else self.decl.vars[path].width) for path, sl in self.res]
        return self.specs

    def stream(self, path, sl=None):
        """[(t ps, normalised value)] over the whole dump, one entry per timestamp with a change."""
        key = (path, sl)
        if key not in self.streams:
            v, u, out = self.decl.vars[path], self.d.unit_ps, []
            w = v.width
            if len(v.members) == 1 and v.members[0][1] is None:
                for t, raw in self.d.trans[v.members[0][0]]:
                    val = bits(raw, w, sl)
                    if out and out[-1][0] == t * u:
                        out[-1] = (t * u, val)
                    else:
                        out.append((t * u, val))
            else:   # bit-blasted vector: rebuild it from its 1-bit members
                state = ['x'] * w
                ev = sorted((t, b, raw) for code, b in v.members for t, raw in self.d.trans[code])
                for i, (t, b, raw) in enumerate(ev):
                    state[b] = raw.decode().lower()
                    if i + 1 == len(ev) or ev[i + 1][0] != t:
                        out.append((t * u, bits(''.join(reversed(state)).encode(), w, sl)))
            self.streams[key] = out
        return self.streams[key]

    def _at(self, st, t):   # value at t (after the changes at t)
        i = bisect.bisect_right(st, (t, '\uffff')) - 1
        return st[i][1] if i >= 0 else None

    def base(self, t):
        return [self._at(self.stream(*r), t) or bits(b'x', w, None) for r, (_, w) in zip(self.res, self.specs)]

    def changes(self, t0, t1):
        out = []
        for r in self.res:
            st = self.stream(*r)
            out.append(st[bisect.bisect_left(st, (t0, '')):bisect.bisect_right(st, (t1, '\uffff'))])
        return out

    def edges(self, path, kind, t0, t1):
        st, out, prev = self.stream(path), [], None
        for t, v in st:
            if prev is not None and t0 <= t <= t1:
                rise = (prev == '0' and v in '1xz') or (prev in 'xz' and v == '1')
                fall = (prev == '1' and v in '0xz') or (prev in 'xz' and v == '0')
                if (kind == 'posedge' and rise) or (kind == 'negedge' and fall) or (kind == 'edge' and (rise or fall)) or (kind == 'change' and v != prev):
                    out.append(t)
            prev = v
        return out

    def sampled(self, clock, t0, t1):
        times = self.edges(self.resolve(clock)[0], 'posedge', t0, t1)
        return times, [[self._at(self.stream(*r), t) for t in times] for r in self.res]

    def events(self, expr, t0, t1):
        kind, sig = self.event_signal(expr)
        return self.edges(self.resolve(sig)[0], kind, t0, t1)


@functools.lru_cache(maxsize=1 << 18)
def bits(raw, width, sl):
    """VCD value bytes ("b10x1", "1", "r1.5") -> the normalised form of norm(); VCD left-extends with 0, or x / z."""
    if raw[:1] == b'r':
        return raw[1:].decode()
    b = raw.decode().lower()
    b = b.rjust(width, b[0] if b[0] in 'xz' else '0')[-width:]
    if sl:
        b, width = b[len(b) - 1 - sl[0]:len(b) - sl[1]], sl[0] - sl[1] + 1
    return norm(f"{width}'b{b}", width)


def open_reader(a):
    if a.reader == 'wavepeek':
        return Peek(a.wavepeek, a.waves, a.scope)
    if not dumpscan.available(a.waves):
        print('vcd2wavedrom: cannot read the FST as text (no fst2vcd): using wavepeek', file=sys.stderr)
        return Peek(a.wavepeek, a.waves, a.scope)
    return Builtin(a.waves, a.scope)


@functools.lru_cache(maxsize=1 << 18)   # values repeat a lot (clocks, flags)
def norm(value, width):
    """Verilog literal from wavepeek ("8'ha5", "1'h1", "4'bxx01") -> '0'/'1'/'x'/'z' (1 bit) or lower-case hex."""
    m = re.fullmatch(r"(\d+)'([hbdo])([0-9a-fA-FxXzZ_]+)", value)
    if not m:
        return value.lower()
    radix, digits = m.group(2), m.group(3).lower().replace('_', '')
    if radix == 'b':
        bits = digits.rjust(width, '0')
        if width == 1:
            return bits[-1]
        bits = bits.rjust((width + 3) // 4 * 4, '0')
        out = ''
        for i in range(0, len(bits), 4):
            nib = bits[i:i + 4]
            out += 'x' if 'x' in nib else 'z' if 'z' in nib else format(int(nib, 2), 'x')
        return out
    if radix == 'd':
        digits = format(int(digits), 'x') if digits.isdigit() else digits
    if radix == 'o':
        digits = format(int(digits, 8), 'x') if digits.isdigit() else digits
    if width == 1:
        return digits[-1] if digits[-1] in '01xz' else '1'
    return digits.rjust((width + 3) // 4, '0')


def jsfmt(f, spec):
    """format() of the exact binary value with JavaScript's ties (away from zero: toFixed, toExponential), not Python's."""
    with decimal.localcontext() as c:
        c.rounding = decimal.ROUND_HALF_UP
        return format(decimal.Decimal(f), spec)


def gfmt(f, p=7):
    """A float as wavefw.js gfmt (C's %.<p>g with a two-digit exponent)."""
    if f != f:
        return 'nan'
    if f in (float('inf'), float('-inf')):
        return '-inf' if f < 0 else 'inf'
    if f == 0:
        return '-0' if math.copysign(1, f) < 0 else '0'
    e = math.floor(math.log10(abs(float(jsfmt(f, f'.{p - 1}e')))))
    trim = lambda s: s.rstrip('0').rstrip('.') if '.' in s else s
    if -5 <= e < p:
        return trim(jsfmt(f, f'.{max(0, p - 1 - e)}f'))
    m, x = jsfmt(f, f'.{p - 1}e').lower().split('e')
    return trim(m) + 'e' + ('-' if x[0] == '-' else '+') + x.lstrip('+-').rjust(2, '0')


def label(v, width, enum=None, radix=None):
    """Bus label, the same radixes as wavefw.js: auto (<=6 bits dec, else hex) hex dec signed bin oct ascii float, fixed
    point q<F> / sq<F>."""
    if enum is not None and re.fullmatch('[0-9a-f]+', v) and int(v, 16) in enum:
        return enum[int(v, 16)]
    if re.search('[xz]', v):
        return v
    n, r = int(v, 16), {'unsigned': 'dec', 'sdec': 'signed'}.get(radix, radix)
    q = re.fullmatch(r'(s?)q(\d+)', r or '')
    if q:
        if q[1] and width > 1 and n >= 1 << (width - 1):
            n -= 1 << width
        d = min(math.ceil(int(q[2]) * 0.30103), 12)
        s = jsfmt(n / 2 ** int(q[2]), f'.{d}f')
        return s.rstrip('0').rstrip('.') if d else s
    if r == 'float' and width in (16, 32, 64):
        return gfmt(struct.unpack({16: '>e', 32: '>f', 64: '>d'}[width], n.to_bytes(width // 8, 'big'))[0], {16: 4, 32: 7, 64: 15}[width])
    if r == 'dec':
        return str(n)
    if r == 'signed':
        return str(n - (1 << width) if width > 1 and n >= 1 << (width - 1) else n)
    if r == 'bin':
        return format(n, 'b').rjust(width, '0')
    if r == 'oct':
        return '0o' + format(n, 'o')
    if r == 'ascii':
        b = n.to_bytes(max(1, (width + 7) // 8), 'big').lstrip(b'\0') or b'\0'
        return '"' + ''.join(chr(c) if 32 <= c < 127 else '.' for c in b) + '"'
    if r == 'hex':
        return '0x' + v.upper()
    return str(n) if width <= 6 else '0x' + v.upper()


def wave_of(items, width, enum, clock=False, radix=None):
    """items: per-cycle normalised values, or None for a '|' gap cell -> (wave, data, the hex value of each label)."""
    if clock:
        return ''.join('|' if v is None else ('p' if i == 0 else '.') for i, v in enumerate(items)), [], []
    out, data, raw, prev = [], [], [], object()
    for v in items:
        if v is None:
            out.append('|'); continue
        if v == prev:
            out.append('.'); continue
        prev = v
        if width == 1:
            out.append(v if v in ('0', '1', 'x', 'z') else 'x')
        elif set(v) == {'x'}:
            out.append('x')
        elif set(v) == {'z'}:
            out.append('z')
        else:
            n = int(v, 16) if re.fullmatch('[0-9a-f]+', v) else None
            out.append(str(3 + n % 7) if enum is not None and n is not None else '=')
            data.append(label(v, width, enum, radix))
            raw.append(v)
    return ''.join(out), data, raw


def nice_ceil(x):
    e = 10 ** int(f'{x:e}'.split('e')[1])
    return next(m * e for m in (1, 2, 5, 10) if m * e >= x)


def nice_floor(x):
    e = 10 ** int(f'{x:e}'.split('e')[1])
    return max(m * e for m in (1, 2, 5, 10) if m * e <= x)


# ---------------- options: command line + config file ----------------
LIST_KEYS = ('signals', 'gap', 'enum', 'group', 'marker', 'sva', 'bind', 'exprs')
SKIP_KEYS = ('views', 'page', 'config', 'description', 'comment', 'render', 'note', 'select', 'rules')   # not converter options
SIG_KEYS = ('show', 'alias', 'radix', 'color', 'fill', 'style', 'enum', 'width', 'changes', 'enumColors', 'analog', 'height', 'fields')   # catalog entry keys


def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', dest='config_file', help='JSON settings file (options, WaveJSON "config", views)')
    ap.add_argument('--view', help='use the "views" entry KEY of the config file')
    ap.add_argument('--waves', help='VCD or FST file')
    ap.add_argument('--scope', help='scope for relative signal names (e.g. tb.u_dut)')
    ap.add_argument('--signals', action='append', help='comma-separated paths, each optionally path=alias')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--clock', help='sample on posedge of this signal: one WaveDrom cycle per clock period')
    mode.add_argument('--exact', action='store_true', default=None, help='exact transitions ("tv" extension)')
    ap.add_argument('--from', dest='t_from', help='window start, e.g. 120ns (default: dump start)')
    ap.add_argument('--to', dest='t_to', help='window end (default: dump end)')
    ap.add_argument('--cycle', help='grid for the quantised wave string in --exact mode (default: finest change spacing, at most ~2000 cells)')
    ap.add_argument('--gap', action='append', help='FROM:TO window collapsed into one "|" cell (--clock mode)')
    ap.add_argument('--enum', action='append', help='sig=0:IDLE,1:RUN (sig = path or alias)')
    ap.add_argument('--group', action='append', help='name=sig1,sig2: nest these signals in a WaveDrom group')
    ap.add_argument('--hierarchy', action='store_true', default=None, help='nest signals in groups by their scope path (instead of --group)')
    ap.add_argument('--marker', action='append', help="'EVENT=label', EVENT is a wavepeek --on expression")
    ap.add_argument('--title', help='head.text')
    ap.add_argument('--bookmarks', help='JSON list [{"n", "t", "signal", "text", "color"}] (usually in the config file; the viewer\'s JSON button writes it)')
    ap.add_argument('--arrows', help='JSON list [{"from", "to", "shape", "head", "line", "color", "label"}] between bookmarks')
    ap.add_argument('--sva', action='append', help='SystemVerilog assertion file for the page (repeatable; one compilation unit, in order)')
    ap.add_argument('--bind', action='append', help='NAME@SCOPE: bind assertion NAME to instance SCOPE, evaluated over the dump (repeatable)')
    ap.add_argument('--expr', dest='exprs', action='append', help='an expression of the signals the page draws as a row (ƒ expressions; repeatable), e.g. "PSEL && !PREADY"')
    ap.add_argument('--sva-bin', help='the sva CLI (default: $WAVEFW_SVA, out/sva-target/release/sva, the prebuilt bin/<os>-x86_64/sva, sva on PATH)')
    ap.add_argument('--hscale', type=float)
    ap.add_argument('--reader', choices=('builtin', 'wavepeek'), help='how the dump is read: builtin (default: one pass in Python; '
                    'an FST through fst2vcd) or wavepeek (any --marker expression)')
    ap.add_argument('--wavepeek', help='wavepeek executable (default: on PATH or ~/.local/bin)')
    ap.add_argument('--out', help='output file (default: stdout)')
    return ap


def load_config(path):
    with open(path, encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f'vcd2wavedrom: {path}: {e}')


def view_config(cfg, view=None):
    """Top-level settings of a config file with one "views" entry laid over them ("config" and "enum" merge)."""
    top = {k: v for k, v in cfg.items() if k != 'views'}
    if view is None:
        return top
    views = cfg.get('views') or {}
    if view not in views:
        raise SystemExit(f'vcd2wavedrom: no view "{view}" in the config (have: {", ".join(views) or "none"})')
    out = dict(top)
    if views[view].get('clock'):        # a view's mode replaces the top-level one
        out.pop('exact', None)
    if views[view].get('exact'):
        out.pop('clock', None)
    for k, v in views[view].items():
        if k == 'signals' and isinstance(out.get(k), dict) and isinstance(v, (list, str)):
            v = select(out[k], v)
        out[k] = {**out[k], **v} if k in ('config', 'enum') and isinstance(out.get(k), dict) and isinstance(v, dict) else v
    return out


def select(catalog, items):
    """A view's signal list against a catalog {path: settings}: "*"/"?" patterns match full paths (in catalog order),
    other entries ("path" or "path=alias") are taken as they are. -> {path: settings} with show forced on."""
    out = {}
    for it in [items] if isinstance(items, str) else items:
        for s in filter(None, (x.strip() for x in it.split(','))):
            path, _, alias = s.partition('=')
            if '*' in path or '?' in path:
                rx = re.compile(''.join('.*' if c == '*' else '.' if c == '?' else re.escape(c) for c in path) + r'\Z')
                hits = [p for p in catalog if rx.match(p)]
                if not hits:
                    print(f'vcd2wavedrom: pattern "{path}" matches no signal', file=sys.stderr)
                out.update((p, {**catalog[p], 'show': True}) for p in hits)
            else:
                out[path] = {**catalog.get(path, {}), 'show': True, **({'alias': alias} if alias else {})}
    return out


def resolve(a, cfg, base='.'):
    """Fill options not given on the command line from a config dict; then check and default them."""
    cli_mode = a.clock is not None or a.exact
    a.wave_config = dict(cfg.get('config') or {})
    for k, v in cfg.items():
        k = {'from': 't_from', 'to': 't_to'}.get(k, k.replace('-', '_'))
        if k in SKIP_KEYS or (k in ('clock', 'exact') and cli_mode):
            continue
        if not hasattr(a, k) or k in ('config_file', 'view', 'out'):
            raise SystemExit(f'vcd2wavedrom: unknown config key "{k}"')
        if getattr(a, k) not in (None, []) or (k == 'sva' and v is False):
            continue                                   # the command line wins; "sva": false is mkhtml.py's
        if k in LIST_KEYS:
            v = [v] if isinstance(v, (str, dict)) else list(v)
        elif k == 'waves':
            v = os.path.join(base, os.path.expanduser(v))
        if k == 'sva':   # (path on disk, path as written); "sva": false is mkhtml.py's (no assertion engine)
            v = [(os.path.join(base, os.path.expanduser(x)), x) for x in v if isinstance(x, str)]
        setattr(a, k, v)
    for k in LIST_KEYS:
        setattr(a, k, getattr(a, k) or [])
    a.sva = [x if isinstance(x, tuple) else (x, x) for x in a.sva]
    if not a.waves or not a.signals:
        raise SystemExit('vcd2wavedrom: need --waves and --signals (on the command line or in the config)')
    if bool(a.clock) == bool(a.exact):
        raise SystemExit('vcd2wavedrom: need exactly one of --clock CLK / --exact')
    a.hscale = a.hscale or 1
    a.reader = a.reader or 'builtin'
    a.wavepeek = os.path.expanduser(a.wavepeek or shutil.which('wavepeek') or '~/.local/bin/wavepeek')
    if (a.reader == 'wavepeek' or not dumpscan.available(a.waves)) and not os.path.exists(a.wavepeek):
        raise SystemExit('vcd2wavedrom: wavepeek not found (cargo build it, see README.md)')
    return a


def options(argv=None, cfg=None, base='.'):
    """argv (+ optional config dict) -> resolved options; also loads --config/--view from argv."""
    a = parser().parse_args(argv)
    if a.config_file:
        file_cfg = load_config(a.config_file)
        if a.view is None and file_cfg.get('views') and not (file_cfg.get('clock') or file_cfg.get('exact')):
            raise SystemExit(f'vcd2wavedrom: pick a view with --view ({", ".join(file_cfg["views"])})')
        cfg, base = view_config(file_cfg, a.view), os.path.dirname(os.path.abspath(a.config_file))
    return resolve(a, cfg or {}, base)


def parse_enums(items):
    out = {}
    for e in items:
        pairs = e.items() if isinstance(e, dict) else [e.partition('=')[::2]]
        for sig, body in pairs:
            kv = body.items() if isinstance(body, dict) else (x.split(':', 1) for x in body.split(','))
            out[sig] = {int(str(k), 0) if not re.fullmatch(r'0\d+', str(k)) else int(k): str(v) for k, v in kv}
    return out


def parse_groups(items):  # -> [(name, [members])]
    out = []
    for g in items:
        if isinstance(g, dict):
            out += [(n, m.split(',') if isinstance(m, str) else list(m)) for n, m in g.items()]
        else:
            n, _, body = g.partition('=')
            out.append((n, body.split(',')))
    return out


def parse_markers(items):  # -> [(expr, label)]
    out = []
    for mk in items:
        if isinstance(mk, dict):
            out.append((mk['on'], mk.get('label', mk['on'])))
        else:
            expr, _, lab = mk.rpartition('=')
            out.append((expr, lab) if expr else (lab, lab))
    return out


# ---------------- conversion ----------------
def convert(a):
    """Resolved options -> WaveJSON dict."""
    rd = open_reader(a)

    # ---- signal list, widths (from the value literal, e.g. "7'h00", so nested scopes and bit selects work) ----
    specs = []
    chunks = a.signals if isinstance(a.signals, list) else [a.signals]
    leaf = lambda p: p if a.scope and not a.hierarchy else re.split(r'\.(?![^\[]*\])', p)[-1]
    for chunk in chunks:
        if isinstance(chunk, dict):   # catalog {path: {show, alias, radix, color, fill, style, enum, …}}
            for path, st in chunk.items():
                st = st or {}
                bad = set(st) - set(SIG_KEYS)
                if bad:
                    raise SystemExit(f'vcd2wavedrom: {path}: unknown signal setting(s) {", ".join(sorted(bad))} (have: {", ".join(SIG_KEYS)})')
                if st.get('show', True) is not False:
                    specs.append({'path': path, 'name': st.get('alias') or leaf(path), 'set': st})
            continue
        for s in filter(None, (x.strip() for x in chunk.split(','))):
            path, _, alias = s.partition('=')
            specs.append({'path': path, 'name': alias or leaf(path), 'set': {}})
    if not specs:
        raise SystemExit('vcd2wavedrom: no signals to show (all "show": false?)')
    paths = [s['path'] for s in specs]
    marks = parse_markers(a.marker)
    for s, (absp, w) in zip(specs, rd.prepare(paths, a.clock, [e for e, _ in marks])):
        s['abs'], s['width'] = absp, w
    t_from = to_ps(a.t_from) if a.t_from else rd.t_start
    t_to = to_ps(a.t_to) if a.t_to else rd.t_end
    for s, b in zip(specs, rd.base(t_from)):
        s['base'] = b
    enums = parse_enums(a.enum)
    for s in specs:
        e = s['set'].get('enum')
        s['enum'] = parse_enums([{s['path']: e}])[s['path']] if e else enums.get(s['name'], enums.get(s['path']))
        s['radix'] = s['set'].get('radix') or None
    if any(not s['enum'] for s in specs):   # FSM states by name: enum tables of the dump (FST; VCD written by fst2vcd -e)
        decl = dumpscan.scan(a.waves, body=False)
        for s in specs:
            e = (decl.get(s['abs']) or {}).get('enum')
            if not s['enum'] and e:
                s['enum'] = e

    doc = {}
    sig_json = {}
    if a.clock:
        times, cols = rd.sampled(a.clock, t_from, t_to)
        if len(times) < 2:
            raise SystemExit('vcd2wavedrom: fewer than two clock edges in the window')
        cycle = statistics.median(b - a_ for a_, b in zip(times, times[1:]))
        gaps = [tuple(map(to_ps, g.split(':') if isinstance(g, str) else g)) for g in a.gap]
        cells, skip = [], []   # cells: row index or None ('|'); skip: [[cell index, cycles it stands for]]
        for i, t in enumerate(times):
            g = next((g for g in gaps if g[0] <= t <= g[1]), None)
            if g is None:
                cells.append(i)
            elif cells and cells[-1] is None and skip and skip[-1][2] is g:
                skip[-1][1] += 1
            else:
                cells.append(None); skip.append([len(cells) - 1, 1, g])
        vals = {s['abs']: cols[j] for j, s in enumerate(specs)}
        clk_abs = next((s['abs'] for s in specs if s['path'] == a.clock or s['name'] == a.clock), None)
        for s in specs:
            items = [None if c is None else vals[s['abs']][c] for c in cells]
            wave, data, raw = wave_of(items, s['width'], s['enum'], clock=s['abs'] == clk_abs, radix=s['radix'])
            j = {'name': s['name'], 'wave': wave}
            if data:
                j['data'] = data
            if s['width'] > 1:
                j['width'] = s['width']
            # the values next to labels that do not read back (the page's assertions sample them): binary, signed,
            # octal and ascii labels, values with x / z digits
            if data and (s['radix'] in ('bin', 'signed', 'sdec', 'oct', 'ascii', 'float') or re.fullmatch(r's?q\d+', s['radix'] or '') or any(re.search('[xz]', v) for v in raw)):
                j['raw'] = raw
            sig_json[s['abs']] = j
        doc['head'] = {'text': a.title or f'{os.path.basename(a.waves)} @ posedge {a.clock}', 'tick': 0}
        doc['time'] = {'t0': times[0], 't1': times[0] + len(times) * cycle, 'cycle': cycle, 'unit': 'ps'}
        if skip:
            doc['time']['skip'] = [[k, n] for k, n, _ in skip]
    else:
        tv = {s['abs']: [[t_from, s['base']]] for s in specs}
        for s, ch in zip(specs, rd.changes(t_from, t_to)):
            for t, val in ch:
                q = tv[s['abs']]
                if q[-1][0] == t:          # same timestamp (e.g. the baseline): keep the last value
                    q[-1][1] = val
                    if len(q) > 1 and q[-2][1] == val:
                        q.pop()
                elif q[-1][1] != val:      # dumps may repeat a value (initial $dumpvars, glitches): drop it
                    q.append([t, val])
        if a.cycle:
            cycle = to_ps(a.cycle)
        else:  # finest spacing between changes (so clocks don't alias), but at most ~2000 cells
            dts = [b[0] - a_[0] for q in tv.values() for a_, b in zip(q, q[1:]) if b[0] > a_[0]]
            cycle = max(nice_floor(min(dts)) if dts else t_to - t_from, nice_ceil((t_to - t_from) / 2000))
        n = max(1, round((t_to - t_from) / cycle))
        for s in specs:
            seq, k, items = tv[s['abs']], 0, []
            for i in range(n):          # quantised fallback: value at the start of each grid cell
                g = t_from + i * cycle
                while k + 1 < len(seq) and seq[k + 1][0] <= g:
                    k += 1
                items.append(seq[k][1])
            wave, data, _ = wave_of(items, s['width'], s['enum'], radix=s['radix'])
            j = {'name': s['name'], 'width': s['width'], 'wave': wave}
            if data:
                j['data'] = data
            j['tv'] = seq
            sig_json[s['abs']] = j
        # the same net seen at several levels (tb.clk, tb.dut.clk, …): store its transitions once, the copies say "same"
        first = {}
        for s in specs:
            j = sig_json[s['abs']]
            key = (s['width'], json.dumps(j['tv']))
            if key in first and len(j['tv']) > 2:
                del j['tv']; j['same'] = first[key]
                sig_json[first[key]]['path'] = first[key]
            else:
                first.setdefault(key, s['abs'])
        doc['head'] = {'text': a.title or os.path.basename(a.waves)}
        doc['time'] = {'t0': t_from, 't1': t_to, 'cycle': cycle, 'unit': 'ps'}
    for s in specs:
        j = sig_json[s['abs']]
        if s['enum']:
            j['enum'] = {str(k): v for k, v in s['enum'].items()}
        for k in ('radix', 'color', 'fill', 'style', 'enumColors', 'analog', 'height', 'fields'):
            if s['set'].get(k) not in (None, ''):   # "" = the global setting
                j[k] = s['set'][k]
        if a.hierarchy:
            j['path'] = s['abs']

    out = []
    if a.hierarchy:   # ---- groups = scopes: tb.dut.u_x.sig -> ["tb", ["dut", ["u_x", sig]]], in signal order ----
        root = (a.scope + '.') if a.scope else ''
        node, kinds = {(): out}, {}
        decl = getattr(rd, 'decl', None) or dumpscan.read(a.waves, None)
        types = decl.scopes if decl else {}   # struct / union / interface scopes (an FST through fst2vcd; a VCD that says so)
        for s in specs:
            parts = re.split(r'\.(?![^\[]*\])', s['abs'][len(root):] if s['abs'].startswith(root) else s['abs'])[:-1]
            for i in range(len(parts)):
                key = tuple(parts[:i + 1])
                if key not in node:
                    node[key] = [parts[i]]; node[key[:-1]].append(node[key])
                    t, at = types.get(root + '.'.join(key)), root + '.'.join(key)
                    if t in ('struct', 'union', 'interface'):   # with its width in the dump: the page puts a whole value together only from all of it
                        kinds['.'.join(key)] = {'kind': t, 'width': sum(v.width for p, v in decl.vars.items() if p.startswith(at + '.'))} if t != 'interface' else t
            node[tuple(parts)].append(sig_json[s['abs']])
        if kinds:
            doc['scopes'] = kinds
    else:   # ---- groups: nest members at the position of the first one ----
        member = {}
        for gname, members in parse_groups(a.group):
            for m in members:
                member[m.strip()] = gname
        placed = {}
        for s in specs:
            g = member.get(s['name']) or member.get(s['path'])
            if g is None:
                out.append(sig_json[s['abs']])
            elif g in placed:
                placed[g].append(sig_json[s['abs']])
            else:
                placed[g] = [g, sig_json[s['abs']]]; out.append(placed[g])
    doc = {'signal': out, **doc, 'config': {'hscale': a.hscale, **a.wave_config}}

    # ---- markers from wavepeek event expressions ----
    markers = []
    for expr, lab in marks:
        hits = rd.events(expr, t_from, t_to)
        for i, t in enumerate(hits):
            markers.append({'t': t, 'label': lab if len(hits) == 1 else f'{lab} {i + 1}'})
    if markers:
        doc['markers'] = sorted(markers, key=lambda m: m['t'])
    for k in ('bookmarks', 'arrows'):
        v = getattr(a, k)
        if v:
            doc[k] = json.loads(v) if isinstance(v, str) else v
    a.sva_aliases = {s['abs']: s['name'] for s in specs if s.get('abs') and s['name'] != leaf(s['path'])}   # shown names, for the assertions
    if a.sva or a.bind:
        pfx = getattr(a, 'sva_prefixes', None)
        pfx = (a.wave_config or {}).get('sortIgnore') if pfx is None else pfx   # names resolve as in the page
        doc['sva'] = svabuild.build(a.sva, a.bind, a.waves, a.sva_bin, t_from, t_to, [pfx] if isinstance(pfx, str) else pfx, a.sva_aliases)
    if a.exprs:   # the page values them (the rows "ƒ expressions"); a scope: {"expr", "scope"}
        doc.setdefault('sva', {})['exprs'] = a.exprs
    doc['meta'] = {'waves': os.path.basename(a.waves), 'tool': rd.tool, 'mode': 'clock' if a.clock else 'exact',
                   'from_ps': t_from, 'to_ps': t_to, **({'scope': a.scope} if a.scope else {})}
    return doc


def main():
    a = options()
    doc = convert(a)
    text = wavejson.dumps(doc) + '\n'
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'vcd2wavedrom: {wavejson.count(doc["signal"])} signals -> {a.out}', file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == '__main__':
    main()
