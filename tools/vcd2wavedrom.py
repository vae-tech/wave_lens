#!/usr/bin/env python3
"""vcd2wavedrom.py — convert a window of a VCD/FST dump into WaveDrom JSON: the built-in reader (one pass over the dump
as VCD text; an FST through GTKWave's fst2vcd, else the sva CLI's `sva vcd`).
Enum labels (FSM states) come from the config ("enum", per-signal "enum") or from the dump's own enum tables (FST).

Modes
  --clock CLK   one WaveDrom cycle per period of CLK. Values are sampled at each rising edge of CLK (the value
                after the edge, i.e. what holds during the cycle). Output is plain WaveDrom (wave strings + data) plus the "time"
                extension, so it renders in stock WaveDrom too.
  --exact       exact transitions per signal in the "tv" extension (every change), which
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
  "raw": the hex value of each label (the page's assertions sample them); "'b" and the bits when hex would lose some.
  Per-signal settings: show (false: left out), alias (displayed name), radix (auto hex dec signed bin oct ascii),
  color (trace / outline / name), fill (bus fill), style (auto wavedrom questa square), enum {"0": "IDLE"}, enumColors
  {"IDLE": "#ffe066"}, analog true / rows (a bus as a step plot, that many rows high), height (the row's px); radix also
  float, q8, sq15; width and changes are information only. A real or string variable of the dump is written with
  "kind": "real" / "string" and its values as texts (null: unknown); an event variable is not a signal to draw.

Examples
  python3 -I tools/vcd2wavedrom.py --waves dump.vcd --scope tb --clock clk --from 0ns --to 400ns \
      --signals clk,state,data=DATA --enum state=0:IDLE,1:RUN --gap 200ns:300ns --out cyc.json
  python3 -I tools/vcd2wavedrom.py --waves dump.vcd --scope tb --exact --from 0ns --to 2us \
      --signals clk,txd,state --group tx=state,txd --marker 'posedge done=done' --out exact.json
  python3 -I tools/vcd2wavedrom.py --config dump.config.json --view exact --out exact.json
"""
import argparse, bisect, decimal, functools, json, math, os, re, statistics, struct, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
import dumpscan, svabuild, wavejson  # noqa: E402
from common import UNIT_PS, WaveError, add_sva_bin_arg, check_config, glob_re, run_main  # noqa: E402

X_TEXT = object()   # an unknown value of a "kind" real / string signal in a clock-sampled row (None there is a "|" gap)


def to_ps(s):
    m = re.fullmatch(r'\s*([\d.]+(?:e-?\d+)?)\s*(zs|as|fs|ps|ns|us|ms|s)\s*', str(s))
    if not m:
        raise WaveError(f'vcd2wavedrom: bad time "{s}" (need a unit, e.g. 250ns)')
    return float(m.group(1)) * UNIT_PS[m.group(2)]


class Builtin:
    """The built-in reader: one pass over the dump as VCD text (an FST through fst2vcd or sva vcd), keeping only the requested
    signals; the window, clock sampling and markers are then computed in memory."""
    EVENT = re.compile(r'\s*(?:(posedge|negedge|edge)\s+)?([^\s()|&!=<>~^*]+)\s*')

    def __init__(self, waves, scope):
        self.waves, self.scope = waves, scope
        self.decl = dumpscan.read(waves, None)
        self.tool = 'wavefw reader' + ('' if waves.lower().endswith('.vcd') else f' ({dumpscan.fst_tool()})')
        self.streams = {}

    def resolve(self, p):
        q = p if not self.scope or p.startswith(self.scope + '.') else self.scope + '.' + p
        hit = self.decl.find(q)
        if hit:
            return hit, None
        m = re.fullmatch(r'(.+)\[(\d+):(\d+)\]', q)
        if m and self.decl.find(m.group(1)):
            return self.decl.find(m.group(1)), (int(m.group(2)), int(m.group(3)))
        raise WaveError(f'vcd2wavedrom: no signal "{p}" in {os.path.basename(self.waves)}' + (f' (scope {self.scope})' if self.scope else ''))

    def event_signal(self, expr):
        m = self.EVENT.fullmatch(expr)
        if not m:
            raise WaveError(f'vcd2wavedrom: a marker is "posedge X", "negedge X", "edge X" or "X" (any change), not "{expr}"')
        return m.group(1) or 'change', m.group(2)

    def prepare(self, paths, clock=None, events=()):
        self.res = [self.resolve(p) for p in paths]
        for p, (path, _) in zip(paths, self.res):
            if self.decl.vars[path].kind == 'event':
                raise WaveError(f'vcd2wavedrom: "{p}" is an event: it has no value to draw (leave it out)')
        extra = ([self.resolve(clock)] if clock else []) + [self.resolve(self.event_signal(e)[1]) for e in events]
        codes = {c for path, _ in self.res + extra for c, _ in self.decl.vars[path].members}
        self.d = dumpscan.read(self.waves, 'collect', codes)
        self.t_start, self.t_end = self.d.t_start, self.d.t_end
        self.specs = [(path + (f'[{sl[0]}:{sl[1]}]' if sl else ''), sl[0] - sl[1] + 1 if sl else self.decl.vars[path].width) for path, sl in self.res]
        self.kinds = [self.decl.vars[path].kind if self.decl.vars[path].kind in dumpscan.TEXT_KINDS else None for path, _ in self.res]
        return self.specs

    def stream(self, path, sl=None):
        """[(t ps, normalised value)] over the whole dump, one entry per timestamp with a change."""
        key = (path, sl)
        if key not in self.streams:
            v, u, out = self.decl.vars[path], self.d.unit_ps, []
            w = v.width
            if all(b is None for _, b in v.members):   # one id code, or the same path under several: their changes merged
                ev = self.d.trans[v.members[0][0]] if len(v.members) == 1 else sorted((x for c, _ in v.members for x in self.d.trans[c]), key=lambda x: x[0])
                for t, raw in ev:
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

    def base(self, t):   # an unknown value: x, or None for a real / string (its text could be "x")
        return [self._at(self.stream(*r), t) or (None if k else bits(b'x', w, None)) for r, (_, w), k in zip(self.res, self.specs, self.kinds)]

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


VHDL = str.maketrans('uwhl-', 'xx10x')   # VHDL std_logic in a vector: U W - unknown, H L weak 1 / 0


@functools.lru_cache(maxsize=1 << 18)
def bits(raw, width, sl):
    """VCD value bytes (vector digits "10x1", a bit "1", "r1.5", "sHello") -> the normalised form of norm(); VCD
    left-extends with 0, or x / z. A real -> its number as wavefw.js prints it (gfmt, 15 digits), a string -> its text."""
    if raw[:1] == b'r':
        try:
            return gfmt(float(raw[1:].decode()), 15)
        except ValueError:
            return raw[1:].decode(errors='replace')
    if raw[:1] == b's':
        return raw[1:].decode(errors='replace')
    b = raw.decode().lower().translate(VHDL)
    b = b.rjust(width, b[0] if b[0] in 'xz' else '0')[-width:]
    if sl:
        b, width = b[len(b) - 1 - sl[0]:len(b) - sl[1]], sl[0] - sl[1] + 1
    return norm(f"{width}'b{b}", width)


def open_reader(a):
    if not os.path.isfile(a.waves):
        raise WaveError(f'vcd2wavedrom: no such dump: {a.waves}')
    if not dumpscan.available(a.waves):
        raise WaveError(f'vcd2wavedrom: cannot read {a.waves}: an FST is read through fst2vcd (GTKWave) or the sva CLI, and neither is there')
    return Builtin(a.waves, a.scope)


def hex_of(bits):
    """Binary digits -> lower-case hex, as GTKWave: a nibble all z is z, one with an x or a partial z is x."""
    bits = bits.rjust((len(bits) + 3) // 4 * 4, '0')
    out = ''
    for i in range(0, len(bits), 4):
        nib = bits[i:i + 4]
        out += 'z' if nib == 'zzzz' else 'x' if 'x' in nib or 'z' in nib else format(int(nib, 2), 'x')
    return out


def mixed(bits):
    """True when hex would lose bits: a nibble with an x or z that is not all x or all z ("10x1")."""
    bits = bits.rjust((len(bits) + 3) // 4 * 4, '0')
    return any(set(n) & {'x', 'z'} and n not in ('xxxx', 'zzzz') for n in (bits[i:i + 4] for i in range(0, len(bits), 4)))


@functools.lru_cache(maxsize=1 << 18)   # values repeat a lot (clocks, flags)
def norm(value, width):
    """Verilog literal ("8'ha5", "1'h1", "4'bxx01") -> '0'/'1'/'x'/'z' (1 bit), lower-case hex, or "'b" and the
    width's binary digits when a nibble mixes x / z with known bits ("4'b10x1" -> "'b10x1": hex would make it x)."""
    m = re.fullmatch(r"(\d+)'([hbdo])([0-9a-fA-FxXzZ_]+)", value)
    if not m:
        return value.lower()
    radix, digits = m.group(2), m.group(3).lower().replace('_', '')
    if radix == 'b':
        bits = digits.rjust(width, '0')
        if width == 1:
            return bits[-1]
        if set(bits) <= {'x'} or set(bits) <= {'z'}:   # all x / all z: one letter, as the page reads it
            return bits[0]
        return "'b" + bits[-width:] if mixed(bits) else hex_of(bits)
    if radix == 'd':
        digits = format(int(digits), 'x') if digits.isdigit() else digits
    if radix == 'o':
        digits = format(int(digits, 8), 'x') if digits.isdigit() else digits
    if width == 1:
        return digits[-1] if digits[-1] in '01xz' else '1'
    if set(digits) <= {'x'} or set(digits) <= {'z'}:
        return digits[0]
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
    if -4 <= e < p:   # C's %g: exponential below 1e-4
        return trim(jsfmt(f, f'.{max(0, p - 1 - e)}f'))
    m, x = jsfmt(f, f'.{p - 1}e').lower().split('e')
    return trim(m) + 'e' + ('-' if x[0] == '-' else '+') + x.lstrip('+-').rjust(2, '0')


def label(v, width, enum=None, radix=None):
    """Bus label, the same radixes as wavefw.js: auto (<=6 bits dec, else hex) hex dec signed bin oct ascii float, fixed
    point q<F> / sq<F>."""
    if enum is not None and re.fullmatch('[0-9a-f]+', v) and int(v, 16) in enum:
        return enum[int(v, 16)]
    if v[:2] == "'b":   # known bits among x / z: binary digits in bin, else the hex of GTKWave (x for a mixed nibble)
        return v[2:] if radix == 'bin' else hex_of(v[2:])
    if re.search('[xz]', v):   # whole nibbles x / z: bin spells them out
        return ''.join(c * 4 if c in 'xz' else format(int(c, 16), '04b') for c in v)[-width:] if radix == 'bin' else v
    n, r = int(v, 16), {'unsigned': 'dec', 'sdec': 'signed'}.get(radix, radix)
    q = re.fullmatch(r'(s?)q(\d+)', r or '')
    if q:   # fixed point: the value / 2^F exactly, as wavefw.js (the F decimals of 1/2^F: the fraction times 5^F)
        if q[1] and width > 1 and n >= 1 << (width - 1):
            n -= 1 << width
        f, a = int(q[2]), abs(n)
        ip, fp = a >> f, a & ((1 << f) - 1)
        return ('-' if n < 0 else '') + str(ip) + ('.' + str(fp * 5 ** f).rjust(f, '0').rstrip('0') if fp else '')
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


def wave_of(items, width, enum, clock=False, radix=None, kind=None):
    """items: per-cycle normalised values, or None for a '|' gap cell -> (wave, data, the hex value of each label).
    kind real / string: the values are texts, labelled as they are (X_TEXT: unknown)."""
    if clock:
        return ''.join('|' if v is None else ('p' if i == 0 else '.') for i, v in enumerate(items)), [], []
    out, data, raw, prev = [], [], [], object()
    for v in items:
        if v is None:
            out.append('|'); continue
        if v == prev:
            out.append('.'); continue
        prev = v
        if kind:
            out.append('x' if v is X_TEXT else '=')
            if v is not X_TEXT:
                data.append(v)
            continue
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
    ap.add_argument('--auto-gap', help='IDLE[:KEEP] clock cycles: where no signal but a clock changes for IDLE cycles, all but KEEP (default 2) '
                    'after the last change and before the next one collapsed into one "|" cell (--clock mode)')
    ap.add_argument('--enum', action='append', help='sig=0:IDLE,1:RUN (sig = path or alias)')
    ap.add_argument('--group', action='append', help='name=sig1,sig2: nest these signals in a WaveDrom group')
    ap.add_argument('--hierarchy', action='store_true', default=None, help='nest signals in groups by their scope path (instead of --group)')
    ap.add_argument('--marker', action='append', help="'EVENT=label', EVENT is 'posedge X', 'negedge X', 'edge X' or 'X' (any change)")
    ap.add_argument('--title', help='head.text')
    ap.add_argument('--bookmarks', help='JSON list [{"n", "t", "signal", "text", "color"}] (usually in the config file; the viewer\'s JSON button writes it)')
    ap.add_argument('--arrows', help='JSON list [{"from", "to", "shape", "head", "line", "color", "label"}] between bookmarks')
    ap.add_argument('--sva', action='append', help='SystemVerilog assertion file for the page (repeatable; one compilation unit, in order)')
    ap.add_argument('--bind', action='append', help='NAME@SCOPE: bind assertion NAME to instance SCOPE, evaluated over the dump (repeatable)')
    ap.add_argument('--expr', dest='exprs', action='append', help='an expression of the signals the page draws as a row (ƒ expressions; repeatable), e.g. "PSEL && !PREADY"')
    add_sva_bin_arg(ap)
    ap.add_argument('--hscale', type=float)
    ap.add_argument('--out', help='output file (default: stdout)')
    return ap


def load_config(path):
    """A JSON config file -> dict; a missing file or bad JSON is a WaveError (one line)."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        raise WaveError(f'no such file: {path}') from None
    except json.JSONDecodeError as e:
        raise WaveError(f'{path}: {e}') from None


def view_config(cfg, view=None):
    """Top-level settings of a config file with one "views" entry laid over them ("config" and "enum" merge)."""
    top = {k: v for k, v in cfg.items() if k != 'views'}
    if view is None:
        return top
    views = cfg.get('views') or {}
    if view not in views:
        raise WaveError(f'vcd2wavedrom: no view "{view}" in the config (have: {", ".join(views) or "none"})')
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
                rx = glob_re(path)
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
    check_config(cfg.get('config'), 'vcd2wavedrom: "config"')
    a.wave_config = dict(cfg.get('config') or {})
    for k, v in cfg.items():
        k = {'from': 't_from', 'to': 't_to'}.get(k, k.replace('-', '_'))
        if k in SKIP_KEYS or (k in ('clock', 'exact') and cli_mode):
            continue
        if not hasattr(a, k) or k in ('config_file', 'view', 'out'):
            raise WaveError(f'vcd2wavedrom: unknown config key "{k}"')
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
        raise WaveError('vcd2wavedrom: need --waves and --signals (on the command line or in the config)')
    if bool(a.clock) == bool(a.exact):
        raise WaveError('vcd2wavedrom: need exactly one of --clock CLK / --exact')
    a.hscale = a.hscale or 1
    return a


def options(argv=None, cfg=None, base='.'):
    """argv (+ optional config dict) -> resolved options; also loads --config/--view from argv."""
    a = parser().parse_args(argv)
    if a.config_file:
        file_cfg = load_config(a.config_file)
        if a.view is None and file_cfg.get('views') and not (file_cfg.get('clock') or file_cfg.get('exact')):
            raise WaveError(f'vcd2wavedrom: pick a view with --view ({", ".join(file_cfg["views"])})')
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
def leaf_name(a, path):
    """The name a signal is shown under: the path as given with --scope (and no hierarchy), else its last part."""
    return path if a.scope and not a.hierarchy else (svabuild.split_path(path) or [path])[-1]


def collect_specs(a, rd):
    """The signals of the options (a list, or a catalog {path: settings}) -> (specs, markers, t_from, t_to): each spec
    {path, name, set, abs, width, kind, base, enum, radix}, read through the reader rd."""
    # ---- signal list, widths (from the value literal, e.g. "7'h00", so nested scopes and bit selects work) ----
    specs = []
    chunks = a.signals if isinstance(a.signals, list) else [a.signals]
    leaf = lambda p: leaf_name(a, p)
    for chunk in chunks:
        if isinstance(chunk, dict):   # catalog {path: {show, alias, radix, color, fill, style, enum, …}}
            for path, st in chunk.items():
                st = st or {}
                bad = set(st) - set(SIG_KEYS)
                if bad:
                    raise WaveError(f'vcd2wavedrom: {path}: unknown signal setting(s) {", ".join(sorted(bad))} (have: {", ".join(SIG_KEYS)})')
                if st.get('show', True) is not False:
                    specs.append({'path': path, 'name': st.get('alias') or leaf(path), 'set': st})
            continue
        for s in filter(None, (x.strip() for x in chunk.split(','))):
            path, _, alias = s.partition('=')
            specs.append({'path': path, 'name': alias or leaf(path), 'set': {}})
    if not specs:
        raise WaveError('vcd2wavedrom: no signals to show (all "show": false?)')
    paths = [s['path'] for s in specs]
    marks = parse_markers(a.marker)
    for s, (absp, w), k in zip(specs, rd.prepare(paths, a.clock, [e for e, _ in marks]), getattr(rd, 'kinds', None) or [None] * len(specs)):
        s['abs'], s['width'], s['kind'] = absp, w, k
    t_from = to_ps(a.t_from) if a.t_from else rd.t_start
    t_to = to_ps(a.t_to) if a.t_to else rd.t_end
    for s, b in zip(specs, rd.base(t_from)):
        s['base'] = b
    enums = parse_enums(a.enum)
    for s in specs:
        e = s['set'].get('enum')
        s['enum'] = parse_enums([{s['path']: e}])[s['path']] if e else enums.get(s['name'], enums.get(s['path']))
        s['radix'] = s['set'].get('radix') or None
    if any(not s['enum'] for s in specs):   # FSM states by name: enum tables of the dump (FST; VCD written by fst2vcd -e or sva vcd)
        decl = dumpscan.scan(a.waves, body=False)
        for s in specs:
            e = (decl.get(s['abs']) or {}).get('enum')
            if not s['enum'] and e:
                s['enum'] = e
    return specs, marks, t_from, t_to


def is_clock(s):
    """A clock by its name, as the page's isClkRow: a 1-bit *clk* / *clock*."""
    return s['width'] == 1 and re.search('clk|clock', s['name'], re.I) is not None


def auto_gaps(spec, times, cols):
    """--auto-gap IDLE[:KEEP] over the sampled columns: where none changes for IDLE cycles or more (between two changes,
    or a change and an end of the window), the cycles between them but the first one and KEEP after it and KEEP before
    the other, two at least -> [(from, to)] times of the --gap kind. The page's gaps (wavefw.js gapCuts) cut the same way."""
    m = re.fullmatch(r'\s*(\d+)\s*(?::\s*(\d+)\s*)?', str(spec))
    if not m or int(m.group(1)) < 1:
        raise WaveError(f'vcd2wavedrom: --auto-gap {spec}: IDLE[:KEEP] in clock cycles, IDLE 1 at least (16:2)')
    idle, keep, n = int(m.group(1)), int(m.group(2) or 2), len(times)
    pts = [0] + [i for i in range(1, n) if any(c[i] != c[i - 1] for c in cols)] + [n]
    return [(times[p + 1 + keep], times[q - keep - 1]) for p, q in zip(pts, pts[1:]) if q - p >= idle and q - p - 1 - 2 * keep >= 2]


def clock_mode(a, rd, specs, t_from, t_to):
    """--clock: one WaveDrom cell per period of the clock -> ({abs path: signal JSON}, {head, time})."""
    doc, sig_json = {}, {}
    times, cols = rd.sampled(a.clock, t_from, t_to)
    if len(times) < 2:
        raise WaveError('vcd2wavedrom: fewer than two clock edges in the window')
    cycle = statistics.median(b - a_ for a_, b in zip(times, times[1:]))
    gaps = [tuple(map(to_ps, g.split(':') if isinstance(g, str) else g)) for g in a.gap]
    clk_abs = next((s['abs'] for s in specs if s['path'] == a.clock or s['name'] == a.clock), None)
    if a.auto_gap:
        gaps += auto_gaps(a.auto_gap, times, [cols[j] for j, s in enumerate(specs) if s['abs'] != clk_abs and not is_clock(s)])
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
    for s in specs:
        col = vals[s['abs']] if not s['kind'] else [X_TEXT if v is None else v for v in vals[s['abs']]]
        items = [None if c is None else col[c] for c in cells]
        wave, data, raw = wave_of(items, s['width'], s['enum'], clock=s['abs'] == clk_abs, radix=s['radix'], kind=s['kind'])
        j = {'name': s['name'], 'wave': wave}
        if data:
            j['data'] = data
        if s['width'] > 1:
            j['width'] = s['width']
        # the values next to labels that do not read back (the page's assertions sample them): binary, signed,
        # octal and ascii labels, values with x / z digits
        if data and not s['kind'] and (s['radix'] in ('bin', 'signed', 'sdec', 'oct', 'ascii', 'float') or re.fullmatch(r's?q\d+', s['radix'] or '') or any(re.search('[xz]', v) for v in raw)):
            j['raw'] = raw
        sig_json[s['abs']] = j
    doc['head'] = {'text': a.title or f'{os.path.basename(a.waves)} @ posedge {a.clock}', 'tick': 0}
    doc['time'] = {'t0': times[0], 't1': times[0] + len(times) * cycle, 'cycle': cycle, 'unit': 'ps'}
    if skip:
        doc['time']['skip'] = [[k, n] for k, n, _ in skip]
    return sig_json, doc


def exact_mode(a, rd, specs, t_from, t_to):
    """--exact: the transitions of each signal ("tv") and a quantised wave string for stock WaveDrom -> ({abs path:
    signal JSON}, {head, time})."""
    doc, sig_json = {}, {}
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
            items.append(X_TEXT if s['kind'] and seq[k][1] is None else seq[k][1])
        wave, data, _ = wave_of(items, s['width'], s['enum'], radix=s['radix'], kind=s['kind'])
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
    return sig_json, doc


def signal_settings(a, specs, sig_json):
    """The per-signal settings of the config onto each signal's JSON (kind, enum, radix, colours, …, path)."""
    for s in specs:
        j = sig_json[s['abs']]
        if s['kind']:
            j['kind'] = s['kind']   # its values are texts (a real's number, a string), null: unknown
        if s['enum']:
            j['enum'] = {str(k): v for k, v in s['enum'].items()}
        for k in ('radix', 'color', 'fill', 'style', 'enumColors', 'analog', 'height', 'fields'):
            if s['set'].get(k) not in (None, ''):   # "" = the global setting
                j[k] = s['set'][k]
        if a.hierarchy:
            j['path'] = s['abs']


def group(a, rd, specs, sig_json):
    """The signals in groups -> (the WaveJSON "signal" list, {scope path: struct / union / interface}): the scopes with
    --hierarchy, else the --group lists (members at the place of the first one)."""
    kinds = {}
    out = []
    if a.hierarchy:   # ---- groups = scopes: tb.dut.u_x.sig -> ["tb", ["dut", ["u_x", sig]]], in signal order ----
        root = (a.scope + '.') if a.scope else ''
        node = {(): out}
        decl = getattr(rd, 'decl', None) or dumpscan.read(a.waves, None)
        types = decl.scopes if decl else {}   # struct / union / interface scopes (an FST through fst2vcd or sva vcd; a VCD that says so)
        for s in specs:
            parts = svabuild.split_path(s['abs'][len(root):] if s['abs'].startswith(root) else s['abs'])[:-1]
            for i in range(len(parts)):
                key = tuple(parts[:i + 1])
                if key not in node:
                    node[key] = [parts[i]]; node[key[:-1]].append(node[key])
                    t, at = types.get(root + '.'.join(key)), root + '.'.join(key)
                    if t in ('struct', 'union', 'interface'):   # with its width in the dump: the page puts a whole value together only from all of it
                        kinds['.'.join(key)] = {'kind': t, 'width': sum(v.width for p, v in decl.vars.items() if p.startswith(at + '.'))} if t != 'interface' else t
            node[tuple(parts)].append(sig_json[s['abs']])
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
    return out, kinds


def finish(a, rd, doc, specs, marks, t_from, t_to):
    """Markers, bookmarks, arrows, the assertions ("sva"), the expressions and "meta" onto the document."""

    # ---- markers from event expressions (posedge / negedge / edge / any change of a signal) ----
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
    a.sva_aliases = {s['abs']: s['name'] for s in specs if s.get('abs') and s['name'] != leaf_name(a, s['path'])}   # shown names, for the assertions
    if a.sva or a.bind:
        pfx = getattr(a, 'sva_prefixes', None)
        pfx = (a.wave_config or {}).get('sortIgnore') if pfx is None else pfx   # names resolve as in the page
        doc['sva'] = svabuild.build(a.sva, a.bind, a.waves, a.sva_bin, t_from, t_to, [pfx] if isinstance(pfx, str) else pfx, a.sva_aliases)
    if a.exprs:   # the page values them (the rows "ƒ expressions"); a scope: {"expr", "scope"}
        doc.setdefault('sva', {})['exprs'] = a.exprs
    doc['meta'] = {'waves': os.path.basename(a.waves), 'tool': rd.tool, 'mode': 'clock' if a.clock else 'exact',
                   'from_ps': t_from, 'to_ps': t_to, **({'scope': a.scope} if a.scope else {})}
    omitted = {}   # the catalog's "show": false: in the dump, not in the page (its find says so), by scope
    for chunk in (a.signals if isinstance(a.signals, list) else [a.signals]):
        for path, st in (chunk.items() if isinstance(chunk, dict) else ()):
            if (st or {}).get('show', True) is False:
                try:
                    path = rd.resolve(path)[0]   # the dump's own path (a --scope put in front); one not in the dump is not said to be
                except WaveError:
                    continue
                lf = (svabuild.split_path(path) or [path])[-1]
                omitted.setdefault(path[:max(0, len(path) - len(lf) - 1)], []).append(lf)
    if omitted:
        doc['meta']['omitted'] = {'why': 'config', 'paths': omitted}


def convert(a: argparse.Namespace) -> dict:
    """Resolved options -> WaveJSON dict: the signals read, clock-sampled or exact, grouped, then the extensions."""
    rd = open_reader(a)
    specs, marks, t_from, t_to = collect_specs(a, rd)
    sig_json, doc = (clock_mode if a.clock else exact_mode)(a, rd, specs, t_from, t_to)
    signal_settings(a, specs, sig_json)
    out, scopes = group(a, rd, specs, sig_json)
    if scopes:
        doc['scopes'] = scopes
    doc = {'signal': out, **doc, 'config': {'hscale': a.hscale, **a.wave_config}}
    finish(a, rd, doc, specs, marks, t_from, t_to)
    return doc


def main():
    """The command line: options, conversion, the WaveJSON text to --out or stdout."""
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
    run_main(main, 'vcd2wavedrom')
