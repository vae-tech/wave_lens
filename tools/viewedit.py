#!/usr/bin/env python3
"""viewedit.py — the viewer's commands (view.run of wavelens/src/edit.js) on a page's edits or a saved state, from the shell.

What a person does with the buttons of a viewer — bookmarks (numbered circles with a text), arrows between them, markers,
expressions, groups of their own, highlight, colours, the selection, hidden and folded rows, the modules kept (Only), the radix, the
cursor and the window — a
script or an agent does with the same commands by name. In the page they run live (view.run, or tools/wavemcp.py
view_live); here they change the file:

  a page (mkhtml.py, make html, wavemcp.py wave_page): it carries per viewer a state of what the edits touched
     (<script type="application/json" id="wavelens-edits">); the viewer applies a new revision once, when the page is
     opened or reloaded — over what was changed in that browser in the same parts (the rest stays)
  a saved state (.view.json, the viewer's Save): changed in place; Load… in the viewer takes it

  viewedit.py page.html --ops '[{"op": "bookmark", "t": "120ns", "signal": "PSEL", "text": "setup"}]'
  viewedit.py page.html --view transfers --ops @ops.json     # one view of a page of several (default: the only one)
  viewedit.py page.html --get                                # the edits as JSON (--view …: one view)
  viewedit.py page.html --views                              # the views: key, title, signals, edits
  viewedit.py saved.view.json --model page.html --ops '…'    # a state; names checked against the page's signals
  viewedit.py --config x.config.json --view drop --ops '…'   # bookmark, arrow, span on a view of a config: a rebuild keeps them
  viewedit.py --commands                                     # the commands and their arguments

Each command is {"op": name, …arguments}; the list runs in order, a bad one is said (exit 1) and the rest still run.
Times: model units (ps of timed waves, else cycles) or a text with a unit ("2.5us", "100NS"). Numbers of bookmarks,
arrows and markers are whole (2, 2.0, "2"). set_state keeps what the state it is given does not have (null clears).
Signals: a full path, a name,
the end of a path ("u_regs.PSEL") or a * pattern. The commands that need the waves' values, their labels or the screen
({live}) run only in a page (live). docs/USAGE.md § "Commands and edits" has them all; the smoke test checks that a
page with these edits and the same commands run in it give the same state.
"""
import argparse, collections, functools, json, math, os, re, sys, unicodedata

sys.dont_write_bytecode = True   # a shared checkout stays as it is: -I ignores PYTHONDONTWRITEBYTECODE (AU-WL-003)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import UNIT_PS, WaveError, glob_re as path_re, parse_time, pick, run_main  # noqa: E402
import wavepage  # noqa: E402
from wavepage import (AR_HEADS, AR_LINES, AR_SHAPES, CONFIG_OPS, EDITS_RE, LIVE_RE, OLD_PAGE_RE, block_re, cfg_arrow, cfg_bookmark,  # noqa: E402,F401
                      cfg_form, cfg_span, cfg_time, cfg_view, config_time, fail, finite, parse_t, put_block, tidy, whole, write_text)

STATE_VERSION = 3   # wavelens/src/view.js STATE_VERSION
RADIX = ['auto', 'hex', 'dec', 'signed', 'bin', 'oct', 'ascii', 'float']   # model.js RADIX
SORTS = ['none', 'asc', 'desc']
STYLES = ['auto', 'wavedrom', 'questa', 'square']
EDGE_KINDS = ['any', 'rise', 'fall', 'value', 'xz']
EXPR_MARKS = ['band', 'line', 'strip']   # wavelens/sva.js MARK_KINDS
HL_N = 6
GAP_KEYS = {'on': 'gaps', 'idle': 'gapIdle', 'keep': 'gapKeep', 'signals': 'gapSignals', 'clock': 'gapClock', 'aux': 'gapAux', 'only': 'gapOnly',
            'count': 'gapCount', 'view': 'gapView'}
ALL_GAP_KEYS = ['gaps', 'gapIdle', 'gapKeep', 'gapSignals', 'gapClock', 'gapAux', 'gapOnly', 'gapCount', 'gapLine', 'gapView']   # view.js GAP_KEYS
CYC_KEYS = ['cycles', 'cycleClock', 'cycleZero']   # view.js CYC_KEYS
# their defaults, as wavelens/wavelens.config.js has them (tests/unit/test_viewedit.py reads them there)
GAP_DEFAULTS = {'gaps': False, 'gapIdle': 16, 'gapKeep': 2, 'gapSignals': None, 'gapClock': None, 'gapAux': None, 'gapOnly': False,
                'gapCount': 'clock', 'gapLine': 'dashdot', 'gapView': False}
CYC_DEFAULTS = {'cycles': False, 'cycleClock': None, 'cycleZero': None}
# the commands: name -> arguments (? optional), as WaveLens.commands() gives them (the smoke test compares the two)
COMMANDS = {
    'cursor': 't', 'cursor2': 't', 'view': 'from? to? at? span?', 'fit': '', 'range': 'from? to? signal?',
    'bookmark': 'n? t? signal? text? label? color? lift? top? link? go? delete?', 'arrow': 'id? from? to? shape? head? line? color? label? delete?',
    'marker': 'id? t? label? color? signal? lift? hidden? dmin? dmax? delete?', 'deltas': 'on? id? to? signal? lift? color? dmin? dmax?',
    'measures': '', 'goto': 't? sel? view? bm?', 'bus_list': 'port? kind? from? to? limit?', 'span': 'id? from? to? label? color? signals? delete?',
    'expr': 'id? text? scope? label? color? on? row? mark? gap? radix? analog? delete?', 'expr_go': 'id? dir? n?', 'expr_matches': 'id? from? to? limit? offset?',
    'expr_markers': 'id? label? color? signal? limit? deltas? delete?',
    'group': 'name signals? add? remove? color? rename? delete? go? move? divider?',
    'highlight': 'add? remove? set? clear?', 'paint': 'signals? color? clear?', 'select': 'signal? signals?', 'hide': 'signals', 'show': 'signals?',
    'fold': 'groups? all?', 'unfold': 'groups? all?', 'radix': 'signals radix', 'analog': 'signals rows', 'bits': 'signals on?',
    'duplicate': 'signals bits? radix? rows? delete?',
    'sort': 'dir ignore?', 'style': 'name',
    'layout': 'scroll? height? tools?', 'find': 'query case? word? regex? highlight? open? mask?', 'gaps': 'on? idle? keep? signals? clock? aux? only? count? view? reset?',
    'cycles': 'on? clock? zero? reset?', 'only': 'modules? on? clear? open? groups?', 'fsm': 'mode? signals? fields? clear?',
    'fsm_stats': 'signal', 'fsm_panel': 'signal? tab? off?', 'fsm_go': 'signal state? from? to? dir? first?', 'types': 'signals?',
    'edge': 'dir? kind? value? signal?', 'reset': '', 'state': '', 'set_state': 'state', 'rows': 'pattern? limit? offset?',
    'picture': 'format? from? to? rows?', 'compare': 'result? dump? a? map? offset? off? show?',
}
LIVE_ONLY = {'fit': 'the time of the waves', 'edge': 'the values of the signals', 'picture': 'the screen',
             'fsm': 'the enum labels of the signals', 'fsm_stats': 'the transitions of the signals', 'fsm_go': 'the transitions of the signals',
             'fsm_panel': 'the panels of the page',
             'types': 'the types file read in the page', 'expr_go': 'the values of the signals', 'expr_matches': 'the values of the signals',
             'expr_markers': 'the values of the signals', 'goto': 'the page scrolls', 'bus_list': 'the decoders of bus.js'}
# the arguments of each command that are times (wavemcp.py turns its ns into "…ns" for these)
TIME_ARGS = {'cursor': ('t',), 'cursor2': ('t',), 'view': ('from', 'to', 'at', 'span'), 'range': ('from', 'to'), 'bookmark': ('t',), 'goto': ('t',), 'bus_list': ('from', 'to'), 'marker': ('t', 'dmin', 'dmax'), 'deltas': ('dmin', 'dmax'),
             'span': ('from', 'to'),
             'picture': ('from', 'to'), 'cycles': ('zero',), 'compare': ('offset',), 'expr_matches': ('from', 'to')}
# what a saved state has (view.js state(), the plugins' addState): set_state takes these, nothing else
STATE_KEYS = {'from', 'to', 'cursor', 'cursor2', 'range', 'edge', 'paint', 'radix', 'analog', 'hidden', 'dups', 'deltas', 'bits', 'select', 'find',
              'bookmarks', 'arrows', 'markers', 'spans', 'groups', 'only', 'fsm', 'compare', 'compareShow', 'folds', 'exprs', 'sva', 'bus'}
COLOR_FN = re.compile(r'(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\([^;{}()]*\)', re.I)


def color_ok(c):
    """model.js colorOk / edit.js cmdColor: a colour the page takes (a name, #hex, a CSS colour function), None to clear; else an error."""
    if c is None or c == '':
        return None
    if isinstance(c, str) and (re.fullmatch(r'[\w#-]+', c) or COLOR_FN.fullmatch(c.strip())):
        return c
    fail(f'"{c}" is no colour')


def js_str(x):
    """A text as the page's String(x) makes it (true, 1,2, [object Object])."""
    if isinstance(x, bool):
        return 'true' if x else 'false'
    if x is None:
        return 'null'
    if isinstance(x, float) and finite(x) and x.is_integer():
        return str(int(x))
    if isinstance(x, list):
        return ','.join('' if y is None else js_str(y) for y in x)
    if isinstance(x, dict):
        return '[object Object]'
    return str(x)


def prefixes(v):
    """model.js prefixes: a list, or a text with commas -> [trimmed, non-empty]."""
    items = v if isinstance(v, list) else str('' if v is None else v).split(',')
    return [str(s).strip() for s in items if str(s).strip()]


def glob_re(p):
    return path_re(p, one=False)


def flat_text(t):
    if isinstance(t, list):
        return ''.join(flat_text(x) for x in t[2 if len(t) > 1 and isinstance(t[1], dict) else 1:])
    return '' if t is None else str(t)


# ---------------- the page's waves: rows and groups as the viewer's parse() makes them ----------------
def is_vec(r):
    """model.js isVec: a bus of bits (shown bit by bit), not a real or a string."""
    return (r.get('width') or 1) > 1 and r.get('kind') not in ('real', 'string')


def slice_id(d):
    """model.js sliceId: "PADDR[7:4]" -> ("PADDR", 7, 4), a slice copy of a bus; else None."""
    m = re.fullmatch(r'(.+)\[(\d+):(\d+)\]', str(d))
    return (m[1], int(m[2]), int(m[3])) if m else None


def dup_id(d):
    """model.js dupId: "PADDR#2" -> ("PADDR", 2), a copy of a signal; else None."""
    m = re.fullmatch(r'(.+)#([1-9]\d*)', str(d))
    return (m[1], int(m[2])) if m and int(m[2]) > 1 else None


def at(lst, x):
    """A list's indexOf by identity, from 1: the entry itself, not the first one equal to it."""
    return next(i for i, y in enumerate(lst) if y is x) + 1


def copy_base(d):
    """The signal a copy is of (look.js rowBase / dupOf): "PADDR#2" and "PADDR[7:4]" -> "PADDR"; None: no copy's name."""
    c = slice_id(d) or dup_id(d)
    return c[0] if c else None


def copy_order(d):
    """look.js dupPut / dupSlice: the copies of a signal sorted by dupN (a slice's is 0), the slices by their msb, the highest
    first (a stable sort: equal keys keep the order they were made in)."""
    s = slice_id(d)
    return (0, -s[1]) if s else ((dup_id(d) or (None, 0))[1], 0)


def when(t, timed=True):
    """view.js when: a time as the page prints it in a message (model.js fmtExact: every digit down to 1 ps in the unit of the
    value, "10 s", "0 ps", "-5 ns"); cycles as a number (trimNum)."""
    if not timed:
        v = math.floor(t * 1000 + 0.5) / 1000   # Math.round
        return str(int(v)) if float(v).is_integer() else repr(v)
    f, u = next(((f, u) for f, u in ((1e12, 's'), (1e9, 'ms'), (1e6, 'µs'), (1e3, 'ns'), (1, 'ps'), (1e-3, 'fs')) if (abs(t) or 1) >= f),
                (1e-3, 'fs'))
    s = f'{t / f:.{max(0, round(math.log10(f)))}f}'
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return f'{s} {u}'


class Model:
    """The rows of one WaveJSON (signals with their full path and width, groups with their id and path) and the
    settings the viewer starts from (highlight, fold, sort), for names, the base of a state and the order of folding."""

    def __init__(self, doc=None, settings=None):
        self.doc, self.rows, self.groups = doc or {}, [], []   # groups in id order
        self.timed = 'time' in self.doc
        cfg = dict(settings or {})
        cfg.update({k: v for k, v in (self.doc.get('config') or {}).items() if v is not None})
        self.cfg = cfg
        self.t0 = self.t1 = None   # the time of the waves (model.js M.t0, M.t1), known with the page
        self._tv, self._sigs_raw = [], []
        if doc:
            self._walk(doc.get('signal') or [], 0, [])
            self._span()
            kinds = self.doc.get('scopes') if isinstance(self.doc.get('scopes'), dict) else {}   # model.js: "scopes" says a group's kind
            for g in self.groups:
                k = kinds.get(g['path'])
                if not g.get('kind') and k:
                    g['kind'] = k if isinstance(k, str) else k.get('kind') if isinstance(k, dict) else None

    def _span(self):
        """model.js parse: M.t0 = min(C(0), the first "tv" time), M.t1 = max(C(cycles), time.t1, the last change)."""
        tm = self.doc.get('time') if isinstance(self.doc.get('time'), dict) else None
        num = lambda x, d=0: parse_time(x) if finite(parse_time(x)) else d
        c0, cy = (num(tm.get('t0')), num(tm.get('cycle'), 1) or 1) if tm else (0, 1)
        cyc = max([len(str(s.get('wave') or '')) * (num(s.get('period'), 1) or 1) for s in self._sigs_raw] or [0])
        firsts, lasts = [], []
        for tv in self._tv:
            ts = [parse_time(x[0]) for x in tv if isinstance(x, list) and x]
            ts = [t for t in ts if finite(t)]
            if ts:
                firsts.append(ts[0])
                lasts.append(ts[-1])
        self.t0 = min([c0] + firsts)
        self.t1 = max([c0 + cyc * cy] + ([num(tm['t1'])] if tm and tm.get('t1') is not None else []) + lasts)
        if not self.t1 > self.t0:
            self.t1 = self.t0 + (cy if tm else 1)

    def _walk(self, arr, depth, anc):
        for it in arr:
            if isinstance(it, list):
                named = bool(it) and isinstance(it[0], str)
                if named and it[0]:
                    g = {'type': 'group', 'name': it[0], 'id': len(self.groups), 'anc': anc, 'depth': depth,
                         'path': '.'.join([self.groups[i]['name'] for i in anc] + [it[0]])}
                    g['full'] = g['path']
                    self.groups.append(g)
                    self.rows.append(g)
                    self._walk(it[1:], depth + 1, anc + [g['id']])
                else:
                    self._walk(it[1:] if named else it, depth, anc)
            elif isinstance(it, dict) and (it.get('wave') is not None or it.get('tv') or it.get('same')):
                if it.get('tv'):
                    self._tv.append(it['tv'])
                elif it.get('wave') is not None:
                    self._sigs_raw.append(it)
                name = flat_text(it.get('name'))
                full = it.get('path') or '.'.join([self.groups[i]['name'] for i in anc] + [name])
                tv, text = it.get('tv') or [], it.get('kind') in ('real', 'string')
                try:
                    w = float(it.get('width'))
                except (TypeError, ValueError):
                    w = 0
                if it.get('tv'):
                    width = int(w) if w else (1 if not text and all(re.fullmatch(r'[01xz]', str(v), re.I) for _, v in tv) else 8)
                else:
                    width = int(w) if w > 1 else 1
                sig = {'type': 'sig', 'name': name, 'full': full, 'anc': anc, 'width': width, 'kind': it.get('kind'), 'path': it.get('path')}
                fields = it.get('fields')
                if isinstance(fields, list) and fields and width > 1:   # a packed struct: a group of its fields
                    g = {'type': 'group', 'name': name, 'id': len(self.groups), 'anc': anc, 'depth': depth, 'path': full, 'full': full, 'kind': 'struct'}
                    self.groups.append(g)
                    self.rows.append(g)
                    for f in fields:
                        try:
                            msb = float(f['msb']); lsb = float(f.get('lsb', f['msb']))
                        except (KeyError, TypeError, ValueError):
                            continue
                        if not f.get('name') or msb < lsb or lsb < 0 or msb >= width:
                            continue
                        self.rows.append({'type': 'sig', 'name': str(f['name']), 'full': full + '.' + str(f['name']), 'anc': anc + [g['id']],
                                          'width': int(msb - lsb + 1), 'kind': None})
                else:
                    self.rows.append(sig)
            else:
                self.rows.append({'type': 'space', 'name': flat_text(it.get('name')) if isinstance(it, dict) else '', 'anc': anc})

    def sigs(self):
        return [r for r in self.rows if r['type'] == 'sig']

    def dup_rows(self, state):
        """look.js setDups: the copies a state keeps ("data#2"), of signals of these waves, as rows."""
        by, out = {r['full']: r for r in self.sigs()}, []
        for d in state.get('dups') or []:
            sl = slice_id(d)   # a slice of a bus: "PADDR[7:4]"
            if sl and sl[0] in by and is_vec(by[sl[0]]) and sl[2] <= sl[1] < by[sl[0]]['width']:
                out.append({**by[sl[0]], 'full': str(d), 'name': by[sl[0]]['name'] + str(d)[len(sl[0]):], 'dup': sl[0], 'slice': [sl[1], sl[2]],
                            'width': sl[1] - sl[2] + 1})
                continue
            m = dup_id(d)
            if m and m[0] in by:
                out.append({**by[m[0]], 'full': str(d), 'name': f'{by[m[0]]["name"]} #{m[1]}', 'dup': m[0]})
        return out

    def bit(self, p, state=None):
        """view.js sigByPath: a bit of a bus by its path ("data[3]"), shown or not; None when it is not one."""
        m = re.fullmatch(r'(.+)\[(0|[1-9]\d*)\]', p) if isinstance(p, str) else None
        v = m and next((r for r in self.sigs() + self.dup_rows(state or {}) if r['full'] == m[1] and is_vec(r)), None)
        if not v or int(m[2]) >= v['width']:
            return None
        return {'type': 'sig', 'name': f'[{m[2]}]', 'full': p, 'anc': v['anc'], 'width': 1, 'kind': None, 'bit': int(m[2])}

    def scopes(self):
        """modules.js scopes: the page's groups that are modules (interfaces …), not the value of a struct or a union."""
        return [g for g in self.groups if g.get('kind') not in ('struct', 'union')]

    def only_norm(self, paths):
        """modules.js onlyNorm: the known module paths in id order, none under another one of them."""
        by = {g['path']: g for g in self.scopes()}
        gs = [by[p] for p in dict.fromkeys(paths) if p in by]
        ids = {g['id'] for g in gs}
        return [g['path'] for g in sorted(gs, key=lambda g: g['id']) if not ids & set(g['anc'])]

    def pool(self, state, groups, scopes=False):
        """What a name may be: the signals, then (groups) the modules in id order and your groups (their path "@name");
        scopes: the modules only."""
        if scopes:
            return self.scopes()
        out = self.sigs() + self.dup_rows(state)
        if groups:
            out = out + self.groups + [{'type': 'group', 'user': True, 'name': g['name'], 'full': '@' + g['name'], 'path': '@' + g['name']}
                                       for g in state.get('groups') or []]
        return out

    def pick(self, state, spec, groups=False, one=False, scopes=False):
        """view pickRows: a full path, a name, the end of a path, a * pattern -> rows (common.pick); nothing found or ambiguous:
        an error."""
        items = prefixes(spec)
        what = 'module' if scopes else 'signal or module' if groups else 'signal'
        if not items:
            fail(f'no {"modules" if scopes else "signals or modules" if groups else "signals"} given')
        pool, out = self.pool(state, groups, scopes), []
        if not self.doc:   # a state without its page: names as they are (full paths)
            return [{'type': 'group' if scopes else 'sig', 'name': s.rsplit('.', 1)[-1], 'full': s, 'path': s, 'anc': [], 'width': 2} for s in items]
        bit = None if scopes else (lambda s: self.bit(s, state))   # a bit of a bus: "data[3]"
        for s in items:
            if '*' in s:
                rx = glob_re(s)
                hit = [r for r in pool if rx.match(r['full'])]
            else:   # the one rule of common.pick (wavemcp.py, vcd2wavedrom.py the same): full, name, tail, longer path, bit, nearest top
                hit = pick(pool, s, full=lambda r: r['full'], name=lambda r: r['name'], bit=bit)[0]
            if not hit:
                low = s.lower().replace('*', '')
                near = [r['full'] for r in pool if low and low in r['name'].lower()][:5]
                fail(f'no {what} "{s}"' + (f'; similar: {", ".join(near)}' if near else ''))
            fulls = list(dict.fromkeys(r['full'] for r in hit))
            if '*' not in s and len(fulls) > 1:
                fail(f'"{s}" is ambiguous: {", ".join(fulls[:6])}' + (f' (+{len(fulls) - 6})' if len(fulls) > 6 else '') +
                     ' — give more of its path, or a * pattern for all of them')
            for r in hit:
                if r not in out:
                    out.append(r)
        if one and len(out) != 1:
            fail(f'one signal, not {len(out)} ({", ".join(r["full"] for r in out[:4])})')
        return out

    def sigs_of(self, state, rows):
        """edit.js sigsOf: a module's signals below it, your group's in it, a signal itself."""
        out = []
        for r in rows:
            if r['type'] != 'group':
                got = [r]
            elif r.get('user'):
                g = next((g for g in state.get('groups') or [] if '@' + g['name'] == r['full']), {'signals': []})
                by = {s['full']: s for s in self.sigs() + self.dup_rows(state)}
                got = [by[f] for f in g['signals'] if f in by] if self.doc else [{'full': f} for f in g['signals']]
            else:
                got = [s for s in self.sigs() if r['id'] in s['anc']]
            out += [s for s in got if s not in out]
        return out

    def base_highlight(self):
        """hlPick of the "highlight" setting: the full paths in their order."""
        out = []
        for p in prefixes(self.cfg.get('highlight')):
            rx = glob_re(p) if '*' in p else None
            for r in self.rows:
                if r['type'] != 'space' and r['full'] not in out and (rx.match(r['full']) if rx else r['full'] == p or r['name'] == p):
                    out.append(r['full'])
        return out

    def base_fold(self):
        """foldSet of the "fold" setting: the group paths in id order."""
        f = self.cfg.get('fold')
        if f is None or f is False:
            return []
        names = set(map(str, f)) if isinstance(f, list) else set(prefixes(f)) if isinstance(f, str) else None
        return [g['path'] for g in self.groups if f is True or (isinstance(f, (int, float)) and not isinstance(f, bool) and g['depth'] >= f)
                or (names and (g['path'] in names or g['name'] in names))]

    def base_bookmarks(self):
        return bm_norm(self.doc.get('bookmarks'))

    def base_arrows(self):
        return ar_norm(self.doc.get('arrows'), self.doc.get('bookmarks'))

    def base_spans(self):
        return span_norm(self.doc.get('spans'))

    def base_marks(self):
        return measure_marks(self.doc.get('measures'))


def bm_norm(lst):
    """model.js bmNorm."""
    out = []
    for i, b in enumerate(lst if isinstance(lst, list) else []):
        try:
            n = int(float(b.get('n'))) or i + 1
        except (TypeError, ValueError):
            n = i + 1
        t = parse_t(b.get('t'))
        if t is None or t != t or t in (float('inf'), float('-inf')):
            continue
        out.append({'n': n, 't': t, 'signal': b.get('signal') or None, 'text': b.get('text') or '',
                    'label': str(b['label']) if b.get('to') in (None, '') and b.get('label') is not None else '', 'color': b.get('color') or None,
                    'lift': lift_of(b.get('lift')) if b.get('signal') else False,
                    'top': b['top'] if isinstance(b.get('top'), str) and b['top'] else None,
                    **({'at': b['at']} if isinstance(b.get('at'), (str, dict)) else {}),   # the event its time came from
                    **({'link': link_of(b['link'])} if link_of(b.get('link')) else {})})   # another view of the page
    return out


def link_of(x):
    """model.js linkOf: "crc" or {"view", "bookmark"?} -> {"view", "bookmark"?} | None."""
    if isinstance(x, str) and x:
        return {'view': x}
    if isinstance(x, dict) and isinstance(x.get('view'), str) and x['view']:
        n = whole(x.get('bookmark')) if x.get('bookmark') is not None else None
        return {'view': x['view'], **({'bookmark': n} if n and n > 0 else {})}
    return None


def lift_of(x):
    """model.js liftOf: "below", else true ("above") or false."""
    return 'below' if x == 'below' else x == 'above' or bool(x)


def span_norm(lst):
    """model.js spanNorm."""
    out = []
    for s in lst if isinstance(lst, list) else []:
        if not isinstance(s, dict):
            continue
        a, b = parse_t(s.get('from')), parse_t(s.get('to'))
        if a is None or b is None or not finite(a) or not finite(b):
            continue
        sg = s.get('signals')
        out.append({'from': min(a, b), 'to': max(a, b), 'label': '' if s.get('label') is None else str(s['label']), 'color': s.get('color') or None,
                    'signals': [str(x) for x in sg] if isinstance(sg, list) else [sg] if isinstance(sg, str) and sg else None})
    return out


def span_list(ss):
    """view.spanList()."""
    return [{k: v for k, v in (('from', s['from']), ('to', s['to']), ('label', s['label']), ('color', s['color']),
                                ('signals', list(s['signals']) if s.get('signals') else None)) if v is not None and v != ''} for s in ss]


def ar_norm(lst, bms=None):
    """model.js arNorm: old bookmarks with "to" become arrows; shape, head, line checked."""
    old = []
    for i, b in enumerate(bms if isinstance(bms, list) else []):
        if isinstance(b, dict) and b.get('to') not in (None, ''):
            old.append({'from': b.get('n') or i + 1, 'to': b['to'], 'shape': b.get('shape'), 'label': b.get('label')})
    out = []
    for a in old + (lst if isinstance(lst, list) else []):
        try:
            f, t = int(float(a.get('from'))), int(float(a.get('to')))
        except (TypeError, ValueError):
            continue
        if not f or not t or f == t:
            continue
        out.append({'from': f, 'to': t, 'shape': a.get('shape') if a.get('shape') in AR_SHAPES else '~',
                    'head': a.get('head') if a.get('head') in AR_HEADS else '>', 'line': a.get('line') if a.get('line') in AR_LINES else 'solid',
                    'color': a.get('color') or None, 'label': a.get('label') or ''})
    return out


def bm_list(bms):
    """view.bookmarks(): the JSON form (empty and default left out)."""
    return [{k: v for k, v in (('n', b['n']), ('t', b['t']), ('at', b.get('at')), ('signal', b['signal']), ('label', b.get('label')), ('text', b['text']),
                                ('color', b['color']), ('lift', b['lift'] or None), ('top', b.get('top')), ('link', b.get('link')))
             if v is not None and v != ''} for b in bms]


def ar_list(ars):
    """view.arrowList()."""
    return [{k: v for k, v in (('from', a['from']), ('to', a['to']), ('shape', a['shape']), ('head', None if a['head'] == '>' else a['head']),
                                ('line', None if a['line'] == 'solid' else a['line']), ('color', a['color']), ('label', a['label']))
             if v is not None and (v != '' or k == 'head')} for a in ars]


def mark_list(ms):
    return [{k: v for k, v in (('t', m['t']), ('label', m['label']), ('color', m['color']), ('signal', m['signal']),
                               ('lift', 'below' if m['signal'] and m['lift'] == 'below' else None), ('dsignal', m.get('dsignal')),
                               ('dlift', 'below' if m.get('dsignal') and m.get('dlift') == 'below' else None), ('dto', m.get('dto')),
                               ('dcolor', m.get('dcolor')), ('hidden', m.get('hidden') or None), ('dmin', m.get('dmin')), ('dmax', m.get('dmax')),
                               ('expr', m.get('expr'))) if v is not None and v != ''} for m in ms]


BOUND_RE = re.compile(r'^\s*(\d+(?:\.\d+)?)\s*(?:cycles?|clk)\s*$', re.I)


def bound_of(x):
    """model.js boundOf: a bound of a marker's Δ (dmin, dmax) -> a number (model units), {"cycles": n} or None (none, or not one)."""
    if x is None or x == '' or isinstance(x, bool):
        return None
    if isinstance(x, dict):
        c = x.get('cycles')
        return {'cycles': whole(c) if whole(c) is not None else c} if isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) and c >= 0 else None
    m = BOUND_RE.match(str(x))
    if m:
        c = float(m.group(1))
        return {'cycles': int(c) if c.is_integer() else c}
    t = x if isinstance(x, (int, float)) else parse_t(x)
    return (int(t) if float(t).is_integer() else t) if t is not None and math.isfinite(t) and t >= 0 else None


def bound_ok(m, dt):
    """The Δ dt of marker m kept in its bound: True / False; None: no bound, or one in cycles (the clock's edges are the page's)."""
    lo, hi = m.get('dmin'), m.get('dmax')
    if lo is None and hi is None or isinstance(lo, dict) or isinstance(hi, dict):
        return None
    return not ((lo is not None and dt < lo) or (hi is not None and dt > hi))


def measure_list(ms):
    """edit.js measureList without the cycles: every Δ of the markers (shown or not) as a table."""
    out = []
    for i, j in mark_deltas(ms):
        a, b, end = ms[i], ms[j], lambda k: {'id': k + 1, 'label': ms[k]['label'], 't': ms[k]['t']}
        dt = abs(b['t'] - a['t'])
        if not dt > 0:   # two markers at one time: no Δ (as the page draws it)
            continue
        out.append({k: v for k, v in (('from', end(i)), ('to', end(j)), ('dt', dt), ('dmin', a.get('dmin')), ('dmax', a.get('dmax')),
                                      ('ok', bound_ok(a, dt)), ('signal', a.get('dsignal'))) if v is not None})
    return out


def measure_marks(lst):
    """model.js measureMarks: the WaveJSON's "measures" (a cocotb test's wl.measure) -> markers, a pair each: the first with its Δ to the
    second and the bound on the line of its signal (their texts at the top); one not ended: a marker alone."""
    out = []
    for x in lst if isinstance(lst, list) else []:
        a = parse_t(x.get('from')) if isinstance(x, dict) else None
        if a is None:
            continue
        b = parse_t(x['to']) if x.get('to') is not None else None
        at = {'color': x.get('color'), 'dsignal': x.get('signal')}
        if b is not None:
            out += [{**at, 't': a, 'label': x.get('label') or '', 'dto': len(out) + 2, 'dmin': x.get('dmin', x.get('min')), 'dmax': x.get('dmax', x.get('max'))},
                    {**at, 't': b, 'label': '', 'dto': 0}]
        else:
            out.append({**at, 't': a, 'label': x.get('label') or '', 'dto': 0})
    return out


def mark_deltas(ms):
    """model.js markDeltas -> [(index from, index to)]."""
    s, out = sorted((i for i, m in enumerate(ms) if not m.get('hidden')), key=lambda i: ms[i]['t']), []
    for k, i in enumerate(s):
        d = ms[i].get('dto')
        if d == 0:
            continue
        if d and d - 1 < len(ms) and d - 1 != i:
            if not ms[d - 1].get('hidden'):
                out.append((i, d - 1))
        elif k + 1 < len(s):
            out.append((i, s[k + 1]))
    return out


def mark_gone(ms, mid):
    """Marker mid deleted: the numbers after it move (model.js markGone)."""
    for m in ms:
        if m.get('dto') == mid:
            m['dto'] = None
        elif (m.get('dto') or 0) > mid:
            m['dto'] -= 1


def expr_norm(x):
    """An item of "exprs" as sva.js exprNorm: a text alone draws its row."""
    o = {'expr': x} if isinstance(x, str) else x if isinstance(x, dict) else {}
    return {'text': expr_text(o.get('expr') if o.get('expr') is not None else o.get('text')), 'scope': o.get('scope') or '',
            'label': str(o['label']) if o.get('label') is not None else '', 'color': o.get('color') or None, 'on': o.get('on') is not False,
            'row': o.get('row') is not False, 'mark': o['mark'] if o.get('mark') in EXPR_MARKS else 'band', 'gap': bool(o.get('gap'))}


def expr_text(t):
    return '' if t is None else str(t).strip().rstrip('; \t\r\n')


def expr_json(x):
    """An expression as a state has it (sva.js exprJSON): what is as the defaults left out, a text alone when nothing else is said."""
    o = {k: v for k, v in (('expr', x['text']), ('scope', x['scope']), ('label', x['label']), ('color', x['color']), ('on', None if x['on'] else False),
                           ('row', None if x['row'] else False), ('mark', None if x['mark'] == 'band' else x['mark']), ('gap', True if x['gap'] else None)) if v is not None and v != ''}
    return x['text'] if len(o) == 1 else o


def group_list(gs):
    return [{k: v for k, v in (('name', g['name']), ('signals', list(g['signals'])), ('color', g['color']), ('divider', g.get('divider') or None))
             if v is not None} for g in gs]


# ---------------- the commands on a state ----------------
def clean_state(state):
    """A state as the viewer takes one on loading it: a key of another kind (a block edited by hand) is left out, not a traceback
    in a command that reads it."""
    st = dict(state or {})
    for k in ('bookmarks', 'arrows', 'markers', 'groups', 'spans'):
        if isinstance(st.get(k), list):
            st[k] = [x for x in st[k] if isinstance(x, dict)]
        elif k in st:
            st.pop(k)
    for k in ('hidden', 'dups', 'bits', 'exprs'):
        if k in st and not isinstance(st[k], list):
            st.pop(k)
    for k in ('config', 'paint', 'radix', 'analog', 'folds'):
        if k in st and not isinstance(st[k], dict):
            st.pop(k)
    for k in ('from', 'to', 'cursor', 'cursor2'):
        if k in st and st[k] is not None and not finite(st[k]):
            st.pop(k)
    return st


class Editor:
    """The commands on a state (the keys the edits touched) of one viewer: each reads what it changes from the state,
    else from the page (its bookmarks, the highlight and fold settings), and writes it back in the form state() has."""

    def __init__(self, model, state=None):
        self.m, self.st = model, clean_state(state)

    # what the state has, else the page's
    def bms(self):
        return bm_norm(self.st['bookmarks']) if 'bookmarks' in self.st else self.m.base_bookmarks()

    def ars(self):
        return ar_norm(self.st['arrows']) if 'arrows' in self.st else self.m.base_arrows()

    def spans(self):
        return span_norm(self.st['spans']) if 'spans' in self.st else self.m.base_spans()

    def marks(self):
        return [{'t': parse_t(x.get('t')), 'label': str(x.get('label') or ''), 'color': x.get('color') or None, 'signal': x.get('signal') or None,
                 'lift': x.get('lift'), 'dsignal': x.get('dsignal') or None, 'dlift': x.get('dlift'), 'dto': x.get('dto'),
                 'dcolor': x.get('dcolor') or None, 'hidden': bool(x.get('hidden')), 'dmin': bound_of(x.get('dmin')), 'dmax': bound_of(x.get('dmax')),
                 'expr': str(x['expr']) if x.get('expr') else None} for x in (self.st.get('markers') or [] if 'markers' in self.st else self.m.base_marks())]

    def exprs(self):
        """The list of expressions: the state's, else the page's "sva".exprs."""
        l = self.st['exprs'] if 'exprs' in self.st else ((self.m.doc or {}).get('sva') or {}).get('exprs') or []
        return [x for x in map(expr_norm, l) if x['text']]

    def groups(self):
        return [{'name': g['name'], 'signals': list(g.get('signals') or []), 'color': g.get('color') or None, **({'divider': True} if g.get('divider') else {})}
                for g in self.st.get('groups') or []]

    def config(self):
        return self.st.setdefault('config', {})

    def cfg_num(self, k, default, lo, hi):
        """A number of the settings (the state's, then the page's), clamped as view.js clamps it."""
        v = (self.st.get('config') or {}).get(k, self.m.cfg.get(k, default))
        try:
            v = float(v)
        except (TypeError, ValueError):
            return default
        return min(max(v, lo), hi) if math.isfinite(v) else default   # NaN, inf: Number() of view.js, isFinite

    def highlight(self):
        c = self.st.get('config') or {}
        return prefixes(c['highlight']) if 'highlight' in c else self.m.base_highlight()   # a text "a,b" too, as hlPick

    def fold(self):
        """The folded groups as far as known here: the state's "fold", else the page's setting, then "folds"."""
        c = self.st.get('config') or {}
        cur = list(c['fold']) if 'fold' in c else self.m.base_fold()
        order = [g['path'] for g in self.m.groups] + ['@' + g['name'] for g in self.st.get('groups') or []]
        for p, on in (self.st.get('folds') or {}).items():
            if p == '*':
                cur = list(order) if on else []
            elif on and p not in cur:
                cur.append(p)
            elif not on and p in cur:
                cur.remove(p)
        return cur

    def put_marks(self, bms=None, ars=None):
        if bms is not None:
            self.st['bookmarks'] = bm_list(bms)
        self.st['arrows'] = ar_list(ars if ars is not None else self.ars())
        if bms is None:
            self.st.setdefault('bookmarks', bm_list(self.bms()))

    def put_map(self, key, m):
        """A map of signals (paint, radix, analog) into the state: an empty one only when the state had the key."""
        if m or key in self.st:
            self.st[key] = m

    def time(self, x, what='t'):
        if not self.m.timed and isinstance(x, str) and re.search(r'[a-zµ]', x, re.I) and self.m.doc:
            fail(f'{what}: these waves have no time, give cycles (a number)')
        t = parse_t(x)
        if t is None or t != t or t in (float('inf'), float('-inf')):
            fail(f'{what}: "{x}" is not a time (a number in {"ps" if self.m.timed or not self.m.doc else "cycles"}, or "250ns")')
        return t

    def when(self, t):
        """view.js when: a time in a message as the page prints it."""
        return when(t, self.m.timed or not self.m.doc)

    def time_in(self, x, what='t'):
        """edit.js cmdIn: a time something is put at, inside the waves (when they are known)."""
        t = self.time(x, what)
        lo = min(0, self.m.t0 or 0)   # from 0 when they start later, as edit.js cmdIn
        if self.m.doc and self.m.t1 is not None and not lo <= t <= self.m.t1:
            fail(f'{what}: {self.when(t)} is outside these waves ({self.when(lo)} … {self.when(self.m.t1)})')
        return t

    def run(self, ops):
        """The commands in order -> [{op, …result} | {op, error}] (view.run)."""
        out = []
        for o in ops if isinstance(ops, list) else [ops]:
            try:
                if not isinstance(o, dict) or o.get('op') not in COMMANDS:
                    fail(f'no command "{o.get("op")}"; the commands: {" ".join(COMMANDS)}' if isinstance(o, dict) and o.get('op')
                         else 'a command is {"op": name, …arguments}')
                keys = [k.rstrip('?') for k in COMMANDS[o['op']].split()]
                bad = [k for k in o if k != 'op' and k not in keys]
                if bad:
                    fail(f'{o["op"]} takes {COMMANDS[o["op"]] or "no arguments"}, not {", ".join(bad)}')
                if o['op'] in LIVE_ONLY:
                    fail(f'{o["op"]} needs {LIVE_ONLY[o["op"]]}: it runs in the page only (live)')
                r = getattr(self, 'c_' + o['op'])(o) or {}
                out.append(tidy({'op': o['op'], **r}))
            except WaveError as e:
                out.append({'op': o.get('op') if isinstance(o, dict) else None, 'error': str(e)})
            except (ValueError, TypeError, KeyError, AttributeError) as e:   # an argument of a kind not foreseen: this command only
                out.append({'op': o.get('op') if isinstance(o, dict) else None, 'error': f'{type(e).__name__}: {e}'})
        return out

    # the commands, as edit.js has them
    def c_cursor(self, a):
        self.st['cursor'] = self.time(a.get('t'))
        return {'t': self.st['cursor']}

    def c_cursor2(self, a):
        self.st['cursor2'] = None if a.get('t') is None else self.time(a['t'])
        return {'t': self.st['cursor2']}

    def c_view(self, a):
        if a.get('from') is not None or a.get('to') is not None:
            if a.get('from') is None or a.get('to') is None:
                fail('view: from and to, or span (and at)')
            p, q = self.time(a['from'], 'from'), self.time(a['to'], 'to')
            if not q > p:
                fail('view: "to" is not after "from"')
        elif a.get('span') is not None or a.get('at') is not None:
            have = self.st.get('from') is not None and self.st.get('to') is not None
            if a.get('span') is None and not have:
                fail('view: span (the window here is not known)')
            if a.get('at') is None and self.st.get('cursor') is None:
                fail('view: at (the cursor here is not known)')
            s = self.time(a['span'], 'span') if a.get('span') is not None else self.st['to'] - self.st['from']
            at = self.time(a['at'], 'at') if a.get('at') is not None else self.st['cursor']
            if not s > 0:
                fail('view: span is not a length')
            p, q = at - s / 2, at + s / 2
        else:
            fail('view: from and to, or span (and at)')
        if self.m.doc and self.m.t1 is not None and a.get('from') is None:   # edit.js: the span within the waves, centred, clamped
            full = self.m.t1 - self.m.t0
            s = min(q - p, full) if full > 0 else q - p
            p = min(max(p + (q - p - s) / 2, self.m.t0), self.m.t1 - s)
            q = p + s
        self.st['from'], self.st['to'] = p, q
        return {'from': p, 'to': q}

    def c_range(self, a):
        if a.get('from') is None and a.get('to') is None:
            self.st['range'] = None
            return {'range': None}
        p, q = self.time(a.get('from'), 'from'), self.time(a.get('to'), 'to')
        sig = self.m.pick(self.st, a['signal'], one=True)[0]['full'] if a.get('signal') else None
        lo, hi = min(p, q), max(p, q)
        if self.m.t0 is not None:   # edit.js range: wholly outside the waves said, else cut to them (view.js setRange)
            if hi < self.m.t0 or lo > self.m.t1:
                fail(f'range: {self.when(lo)} … {self.when(hi)} is outside these waves ({self.when(self.m.t0)} … {self.when(self.m.t1)})')
            lo, hi = max(lo, self.m.t0), min(hi, self.m.t1)
        self.st['range'] = None if lo == hi else {'from': lo, 'to': hi, 'signal': sig}
        return {'range': None if lo == hi else [lo, hi]}

    def c_bookmark(self, a):
        n = a.get('n')
        if n is not None and not (n == 'all' and a.get('delete')):
            n = whole(n)
            if n is None or n < 1:
                fail('n: a bookmark number (1, 2 …)')
        bms = self.bms()
        nums = ', '.join(str(b['n']) for b in bms) or 'none'
        if a.get('delete'):
            if n == 'all':
                self.put_marks([], [])
                return {'deleted': 'all'}
            b = next((b for b in bms if b['n'] == (n or 0)), None)
            if not b:
                fail(f'no bookmark {n} (there are: {nums})')
            self.put_marks([x for x in bms if x is not b], [x for x in self.ars() if b['n'] not in (x['from'], x['to'])])
            return {'n': b['n'], 'deleted': True}
        t = self.time_in(a['t']) if a.get('t') is not None else None
        sig = self.m.pick(self.st, a['signal'], one=True)[0]['full'] if a.get('signal') else None
        b = next((b for b in bms if n is not None and b['n'] == n), None)
        touch = not b or any(k in a for k in ('t', 'signal', 'text', 'label', 'color', 'lift', 'top', 'link'))   # go alone changes nothing of it
        if a.get('link') is not None and not link_of(a['link']):
            fail(f'link: a view\'s key ("crc") or {{view, bookmark}}, not {json.dumps(a["link"])}')
        if a.get('lift') is not None and a['lift'] not in (True, False, 'above', 'below'):
            fail(f'lift: true, "above", "below" or false, not {json.dumps(a["lift"])}')
        if a.get('top') is not None and not isinstance(a['top'], str):
            fail(f"top: a row's path (a signal or a module), not {json.dumps(a['top'])}")
        top = self.m.pick(self.st, a['top'], groups=True, one=True)[0]['full'] if a.get('top') else None   # a row there is, as signal
        if not b:
            if t is None and self.st.get('cursor') is None:
                fail('bookmark: t (the cursor here is not known)')
            b = {'n': n if n is not None else max([0] + [x['n'] for x in bms]) + 1, 't': self.st.get('cursor'), 'signal': None, 'text': '',
                 'label': '', 'color': None, 'lift': False, 'top': None}
            bms.append(b)
        if t is not None:
            b['t'] = t
            b.pop('at', None)   # the event its time came from no longer says it
        if 'signal' in a:
            b['signal'] = sig
        if 'text' in a:
            b['text'] = '' if a['text'] is None else js_str(a['text'])
        if 'label' in a:
            b['label'] = '' if a['label'] is None else js_str(a['label'])
        if 'color' in a:
            b['color'] = color_ok(a['color'])
        if 'lift' in a:
            b['lift'] = lift_of(a['lift'])
        if 'top' in a:
            b['top'] = top
        if 'link' in a:
            if a['link']:
                b['link'] = link_of(a['link'])
            else:
                b.pop('link', None)
        b['lift'] = lift_of(b['lift']) if b['signal'] else False
        if touch:
            self.put_marks(bms)
        if a.get('go'):   # view.js goBm: the cursor on it, bookmarkLeft of the window from the left (its span kept), its signal selected
            self.st['cursor'] = b['t']
            if self.st.get('from') is not None and self.st.get('to') is not None:
                f = self.cfg_num('bookmarkLeft', 0.2, 0, 0.9)
                span = self.st['to'] - self.st['from']
                x = b['t'] - span * f
                if self.m.t0 is not None and self.m.t1 is not None:   # view.js clamp: the window within the waves
                    x = min(max(x, self.m.t0), self.m.t1 - span)
                self.st['from'], self.st['to'] = x, x + span
            if b['signal']:
                self.st['select'] = b['signal']
            return {'n': b['n'], 't': b['t'], 'from': self.st.get('from'), 'top': b['top']}
        return {'n': b['n']}

    @staticmethod
    def id_ok(x, what):
        """The id of an arrow or a marker: its number as listed (1, 1.0, "1"; not true, 1.5, a name) -> the int, None or "all"."""
        if x is None or x == 'all':
            return x
        i = whole(x)
        if i is None or i < 1:
            fail(f'id: the number of the {what} as listed (1, 2 …), not {json.dumps(x, ensure_ascii=False)}; a new one: no id')
        return i

    def c_arrow(self, a):
        if a.get('id') == 'all':
            fail('arrow: one at a time (bookmark n "all" deletes every arrow)')
        aid = self.id_ok(a.get('id'), 'arrow')
        bms, ars = self.bms(), self.ars()
        has = lambda n: any(b['n'] == n for b in bms)
        nums = ', '.join(str(b['n']) for b in bms) or 'none'
        def num(k):
            n = whole(a[k])
            if n is None:
                fail(f'{k}: a bookmark number (1, 2 …), not {json.dumps(a[k], ensure_ascii=False)}')
            return n
        if aid is not None:
            i = aid - 1
            if not 0 <= i < len(ars):
                fail(f'no arrow {a["id"]} (there are {len(ars)})')
        elif a.get('from') is not None and a.get('to') is not None:
            i = next((k for k, x in enumerate(ars) if x['from'] == num('from') and x['to'] == num('to')), -1)
        else:
            i = -1
        if a.get('delete'):
            if i < 0:
                fail(f'no arrow {a["from"]} → {a["to"]}' if a.get('from') is not None and a.get('to') is not None else 'arrow: delete takes id, or from and to')
            del ars[i]
            self.put_marks(None, ars)
            return {'id': i + 1, 'deleted': True}
        for k in ('from', 'to'):
            if a.get(k) is not None and not has(num(k)):
                fail(f'{k}: no bookmark {a[k]} (there are: {nums})')
        for k, ok in (('shape', AR_SHAPES), ('head', AR_HEADS), ('line', AR_LINES)):
            if a.get(k) is not None and a[k] not in ok:
                fail(f'{k}: one of ' + ' '.join(json.dumps(x) for x in ok))
        f = num('from') if a.get('from') is not None else ars[i]['from'] if i >= 0 else None
        t = num('to') if a.get('to') is not None else ars[i]['to'] if i >= 0 else None
        if f is None or t is None:
            fail('arrow: from and to (bookmark numbers)')
        if f == t:
            fail('arrow: from and to are one bookmark')
        if i < 0:
            ars.append(ar_norm([{'from': f, 'to': t}])[0])
            i = len(ars) - 1
        x = ars[i]
        x['from'], x['to'] = f, t
        for k in ('shape', 'head', 'line'):
            if a.get(k) is not None:
                x[k] = a[k]
        if 'color' in a:
            x['color'] = color_ok(a['color'])
        if 'label' in a:
            x['label'] = '' if a['label'] is None else js_str(a['label'])
        self.put_marks(None, ars)
        return {'id': i + 1}

    def c_marker(self, a):
        mid, ms = self.id_ok(a.get('id'), 'marker'), self.marks()
        if mid not in (None, 'all') and not mid <= len(ms):
            fail(f'no marker {a["id"]} (there are {len(ms)})')
        if a.get('delete'):
            if mid is None:
                fail('marker: delete takes id or "all"')
            ms = [] if mid == 'all' else ms[:mid - 1] + ms[mid:]
            if mid != 'all':
                mark_gone(ms, mid)
            self.st['markers'] = mark_list(ms)
            return {'id': mid, 'deleted': True}
        if mid == 'all':
            fail('marker: id "all" goes with delete (every marker deleted); one to change: its number')
        t = self.time_in(a['t']) if a.get('t') is not None else None
        sig = self.m.pick(self.st, a['signal'], one=True)[0]['full'] if a.get('signal') else None
        if a.get('lift') is not None and a['lift'] not in (True, 'above', 'below'):
            fail(f'lift: true, "above" or "below", not {json.dumps(a["lift"])}')
        m = ms[mid - 1] if mid is not None else None
        if a.get('lift') is not None and not (sig if 'signal' in a else m and m['signal']):
            fail('marker: lift is the lane of a signal: give signal')
        bd = {k: self.bound(a[k], k) for k in ('dmin', 'dmax') if k in a}
        self.bounds_ok(bd, [m or {}])
        if not m:
            if t is None and self.st.get('cursor') is None:
                fail('marker: t (the cursor here is not known)')
            m = {'t': self.st.get('cursor'), 'label': '', 'color': None, 'signal': None, 'lift': None}
            ms.append(m)
        if t is not None:
            m['t'] = t
        if 'label' in a:
            m['label'] = '' if a['label'] is None else js_str(a['label'])
        if 'color' in a:
            m['color'] = color_ok(a['color'])
        if 'signal' in a:
            m['signal'] = sig
        if a.get('lift') is not None:
            m['lift'] = a['lift']
        if a.get('hidden') is not None:
            m['hidden'] = bool(a['hidden'])
        m.update(bd)
        self.st['markers'] = mark_list(ms)
        return {'id': at(ms, m)}   # the one made or changed, not the first equal to it (view.umarks.indexOf)

    @staticmethod
    def bounds_ok(bd, ms):
        """edit.js boundsOk: dmin over dmax of one kind is refused."""
        for x in ms:
            lo, hi = bd.get('dmin', x.get('dmin')), bd.get('dmax', x.get('dmax'))
            if lo is not None and hi is not None and isinstance(lo, dict) == isinstance(hi, dict) and \
                    ((lo['cycles'] > hi['cycles']) if isinstance(lo, dict) else lo > hi):
                fail(f'dmin {json.dumps(lo)} is over dmax {json.dumps(hi)}: no Δ keeps it')

    @staticmethod
    def bound(x, what):
        """edit.js cmdBound."""
        if x is None:
            return None
        b = bound_of(x)
        if b is None:
            fail(f'{what}: a time ("150ns", a number in the units of t) or cycles ("3 cycles"), not {json.dumps(x)}')
        return b

    def c_measures(self, a):
        return {'measures': measure_list(self.marks())}

    def c_expr(self, a):
        xid, xs = self.id_ok(a.get('id'), 'expression'), self.exprs()
        if xid not in (None, 'all') and not xid <= len(xs):
            fail(f'no expression {a["id"]} (there are {len(xs)})')
        if xid == 'all' and not a.get('delete'):
            fail('expr: id "all" is for delete (a new one: no id)')
        if a.get('delete'):
            if xid is None:
                fail('expr: delete takes id or "all"')
            xs = [] if xid == 'all' else xs[:xid - 1] + xs[xid:]
            self.st['exprs'] = [expr_json(x) for x in xs]
            return {'id': xid, 'deleted': True}
        was = xs[xid - 1] if xid is not None else None
        if a.get('mark') is not None and a['mark'] not in EXPR_MARKS:
            fail(f'expr: mark is {", ".join(EXPR_MARKS)}, not {json.dumps(a["mark"])}')
        text = expr_text(a['text']) if 'text' in a else was['text'] if was else ''
        if not text:
            fail('expr: text (an expression of the signals: PSEL && !PREADY)')
        scope = expr_text(a['scope']) if 'scope' in a else was['scope'] if was else ''
        same = [i for i, y in enumerate(xs) if y is not was and y['text'] == text and y['scope'] == scope]
        if same:
            fail(f'expr: it is there already (id {same[0] + 1})')
        x = was or expr_norm({'expr': text, 'row': False})
        old = was['text'] if was else None
        x.update(text=text, scope=scope)
        if 'label' in a:
            x['label'] = '' if a['label'] is None else js_str(a['label'])
        if 'color' in a:
            x['color'] = color_ok(a['color'])
        for k in ('on', 'row', 'gap'):
            if k in a:
                x[k] = bool(a[k])
        if a.get('mark') is not None:
            x['mark'] = a['mark']
        if a.get('radix') is not None and not (a['radix'] in RADIX or re.fullmatch(r's?q\d{1,3}', str(a['radix']))):
            fail(f'radix: one of {", ".join(RADIX)}, q8, sq15 …, not {json.dumps(a["radix"])}')
        if ('radix' in a or 'analog' in a) and not x['row']:
            fail('expr: radix and analog are of its row: give row: true')
        for k in ('radix', 'analog'):   # of its row ƒ, by its name, as the menu keeps a signal's
            if old is not None and old != text and 'ƒ ' + old in (self.st.get(k) or {}):   # its text changed: its row's look goes with it
                m = dict(self.st[k])
                m['ƒ ' + text] = m.pop('ƒ ' + old)
                self.put_map(k, m)
            if k in a:
                m = dict(self.st.get(k) or {})
                if a[k] is None:
                    m.pop('ƒ ' + text, None)
                else:
                    m['ƒ ' + text] = a[k] if k == 'radix' else (int(a[k]) if whole(a[k]) else False)
                self.put_map(k, m)
        if not was:
            xs.append(x)
        self.st['exprs'] = [expr_json(y) for y in xs]
        return {'id': at(xs, x)}

    def c_span(self, a):
        sid, ss = self.id_ok(a.get('id'), 'span'), self.spans()
        if sid == 'all' and not a.get('delete'):
            fail('span: id "all" is for delete (a new one: no id)')
        if sid not in (None, 'all') and not sid <= len(ss):
            fail(f'no span {a["id"]} (there are {len(ss)})')
        if a.get('delete'):
            if sid is None:
                fail('span: delete takes id or "all"')
            self.st['spans'] = span_list([] if sid == 'all' else ss[:sid - 1] + ss[sid:])
            return {'id': sid, 'deleted': True}
        t0 = self.time_in(a['from'], 'from') if a.get('from') is not None else None
        t1 = self.time_in(a['to'], 'to') if a.get('to') is not None else None
        given = a.get('signals')
        sigs = None if given is None else [self.m.pick(self.st, x, one=True)[0]['full'] for x in (given if isinstance(given, list) else [given])]
        s = ss[sid - 1] if sid is not None else None
        if (t0 is not None or t1 is not None) and (t0 if t0 is not None else s and s['from']) == (t1 if t1 is not None else s and s['to']):
            fail('span: from and to at one time: no stretch')
        if not s:
            if t0 is None or t1 is None:
                fail('span: from and to')
            s = {'from': t0, 'to': t1, 'label': '', 'color': None, 'signals': None}
            ss.append(s)
        if t0 is not None:
            s['from'] = t0
        if t1 is not None:
            s['to'] = t1
        if s['from'] > s['to']:
            s['from'], s['to'] = s['to'], s['from']
        if 'label' in a:
            s['label'] = '' if a['label'] is None else js_str(a['label'])
        if 'color' in a:
            s['color'] = color_ok(a['color'])
        if a.get('signals') is not None:
            s['signals'] = sigs or None
        self.st['spans'] = span_list(ss)
        return {'id': at(ss, s)}   # (two equal spans: the second is the new one, B-11)

    def c_group(self, a):
        name = str(a.get('name') if a.get('name') is not None else '').strip()
        if not name:
            fail('group: a name')
        gs = self.groups()
        g = next((x for x in gs if x['name'] == name), None)
        if a.get('delete'):
            if not g:
                fail(f'no group "{name}"')
            self.st['groups'] = group_list([x for x in gs if x is not g])
            return {'name': name, 'deleted': True}
        fulls = lambda spec: [r['full'] for r in self.m.sigs_of(self.st, self.m.pick(self.st, spec, groups=True))]
        new = fulls(a['signals']) if a.get('signals') is not None else None
        add = fulls(a['add']) if a.get('add') is not None else []
        rm = fulls(a['remove']) if a.get('remove') is not None else []
        to = str(a['rename']).strip() if a.get('rename') is not None else None
        if to == '' or (to and to != name and any(x['name'] == to for x in gs)):
            fail(f'rename: a group "{to}" is there' if to else 'rename: a name')
        mv = a.get('move')
        if isinstance(mv, float) and mv.is_integer():   # 1.0, 1e0: a number as JavaScript has it
            mv = int(mv)
        if mv is not None and mv not in ('up', 'down', 'top', 'bottom') and not (isinstance(mv, int) and not isinstance(mv, bool) and mv >= 1):
            fail('move: up, down, top, bottom or a number (1: the first)')
        if a.get('divider') is not None and not isinstance(a['divider'], bool):
            fail('divider: true or false')
        if (a.get('divider') or (g and g.get('divider') and a.get('divider') is not False)) and (new or add):
            fail('a divider has no signals')
        if not g:
            g = {'name': name, 'signals': [], 'color': None}
            gs.append(g)
        if a.get('divider') is not None:   # a line with its name between your groups
            if a['divider']:
                g.update(divider=True, signals=[])
            else:
                g.pop('divider', None)
        if mv is not None:   # its place among your groups (edit.js)
            i, n = gs.index(g), len(gs)
            j = i - 1 if mv == 'up' else i + 1 if mv == 'down' else 0 if mv == 'top' else n - 1 if mv == 'bottom' else mv - 1
            gs.remove(g)
            gs.insert(min(max(j, 0), n - 1), g)
        if new is not None:
            g['signals'] = new
        for f in add:
            if f not in g['signals']:
                g['signals'].append(f)
        if rm:
            g['signals'] = [f for f in g['signals'] if f not in rm]
        if 'color' in a:
            g['color'] = color_ok(a['color'])
        if to:
            g['name'] = to
        self.st['groups'] = group_list(gs)
        if a.get('go'):   # opened, shown, its first signal selected (view.js goGroup)
            path = '@' + g['name']
            f = dict(self.st.get('folds') or {})
            f.pop(path, None)
            f[path] = False
            self.st['folds'] = f
            if path in (self.st.get('hidden') or []):
                self.st['hidden'] = [p for p in self.st['hidden'] if p != path]
            if g['signals']:
                self.st['select'] = g['signals'][0]
        return {'name': g['name'], 'signals': len(g['signals']), 'at': gs.index(g) + 1}

    def c_highlight(self, a):
        lst = [] if a.get('clear') else self.highlight()
        if 'set' in a:
            lst = [] if a['set'] is None else [r['full'] for r in self.m.pick(self.st, a['set'], groups=True)]
        if a.get('add') is not None:
            for r in self.m.pick(self.st, a['add'], groups=True):
                if r['full'] not in lst:
                    lst.append(r['full'])
        if a.get('remove') is not None:
            rm = {r['full'] for r in self.m.pick(self.st, a['remove'], groups=True)}
            lst = [f for f in lst if f not in rm]
        self.config()['highlight'] = lst
        return {'highlighted': lst}

    def c_paint(self, a):
        if a.get('signals') is None and not a.get('clear'):
            fail('paint: signals and a color, or clear')
        p = {} if a.get('clear') else dict(self.st.get('paint') or {})
        rows = self.m.sigs_of(self.st, self.m.pick(self.st, a['signals'], groups=True)) if a.get('signals') is not None else []
        for r in rows:
            if a.get('color'):
                p[r['full']] = str(color_ok(a['color']))
            else:
                p.pop(r['full'], None)
        if a.get('clear'):   # every colour off, the browser's own too
            self.st['paint'] = p
        self.put_map('paint', p)
        return {'painted': len(rows)}

    def in_view(self, r):
        """modules.js shown: a signal not hidden (nor its module) and kept by Only (folded away it still is)."""
        h = set(self.st.get('hidden') or [])
        return r['full'] not in h and not {self.m.groups[i]['path'] for i in r['anc'] if i < len(self.m.groups)} & h and self.only_keeps(r)

    def c_select(self, a):
        if a.get('signals') is not None:   # the last of the ones in the view (edit.js: the run of them)
            rows = [r for r in self.m.pick(self.st, a['signals']) if not self.m.doc or self.in_view(r)]
            self.st['select'] = rows[-1]['full'] if rows else None
        else:
            self.st['select'] = self.m.pick(self.st, a['signal'], one=True)[0]['full'] if a.get('signal') else None
        self.unselect_gone()
        return {'select': self.st['select']}

    def unselect_gone(self):
        """view.draw: the selected signal folded or hidden away is no longer selected."""
        sel = self.st.get('select')
        if not sel or not self.m.doc:
            return
        r = next((r for r in self.m.sigs() if r['full'] == sel), None)
        if not r:
            return
        hidden, folded = set(self.st.get('hidden') or []), set(self.fold())
        paths = {self.m.groups[i]['path'] for i in r['anc']}
        if sel in hidden or paths & hidden or paths & folded or not self.only_keeps(r):
            self.st['select'] = None

    def c_hide(self, a):
        rows = self.m.pick(self.st, a.get('signals'), groups=True)
        h = list(self.st.get('hidden') or [])
        for r in rows:
            if r['full'] not in h:
                h.append(r['full'])
        self.st['hidden'] = h
        self.unselect_gone()
        return {'hidden': len(h)}

    def c_show(self, a):
        h = list(self.st.get('hidden') or [])
        if a.get('signals') is None:
            h = []
        else:
            rm = {r['full'] for r in self.m.pick(self.st, a['signals'], groups=True)}
            h = [p for p in h if p not in rm]
        self.st['hidden'] = h
        return {'hidden': len(h)}

    def _fold(self, a, on):
        """Folding as a change ("folds": path -> on, "*": every group): the groups of plugins (assertions, buses), which
        are not known here, keep theirs."""
        f = dict(self.st.get('folds') or {})
        if a.get('all'):
            f = {'*': on}
        else:
            gs = [r for r in self.m.pick(self.st, a.get('groups'), groups=True) if r['type'] == 'group']
            if not gs:
                fail(f'{"fold" if on else "unfold"}: no module in {json.dumps(a.get("groups"))}')
            for g in gs:
                f.pop(g['path'], None)
                f[g['path']] = on
        self.st['folds'] = f
        self.unselect_gone()
        return {'folded': len(self.fold())}

    def c_fold(self, a):
        return self._fold(a, True)

    def c_unfold(self, a):
        return self._fold(a, False)

    def only(self):
        """The state's Only as the viewer keeps it ({modules, on, groups?}: groups when not the page's onlyGroups; None:
        every module)."""
        o = self.st.get('only')
        if not isinstance(o, dict):
            return None
        ms = [p for p in o.get('modules') or [] if isinstance(p, str)]
        out = {'modules': self.m.only_norm(ms) if self.m.doc else list(dict.fromkeys(ms)), 'on': o.get('on') is not False}
        g = o.get('groups')
        return dict(out, groups=g) if isinstance(g, bool) and g != self.only_groups_default() else out

    def only_groups_default(self):
        return self.m.cfg.get('onlyGroups', True) is not False

    def only_groups(self):
        """modules.js onlyGroups: your groups whole under Only (the state's, else the page's setting onlyGroups)."""
        o = self.st.get('only')
        g = o.get('groups') if isinstance(o, dict) else getattr(self, 'grp_next', None)
        return g if isinstance(g, bool) else self.only_groups_default()

    def only_filter(self):
        """modules.js onlyKeep: a test of a row of the page (your group's signal: by the signal it shows) — whether Only
        keeps it; None: Only is off (every row)."""
        o = self.only()
        if not o or not o['on'] or not self.m.doc:
            return None
        sel = {g['id'] for g in self.m.groups if g['path'] in o['modules']}   # onlyIds: inn (picked, under them), way (above them)
        inn = {g['id'] for g in self.m.groups if g['id'] in sel or sel & set(g['anc'])}
        way = {a for i in sel for a in self.m.groups[i]['anc']} - inn
        whole = self.only_groups()   # your groups whole: every signal of them

        def keep(r):
            if r.get('user') or (whole and r.get('ug')) or (r['type'] == 'group' and (r['id'] in way or r['id'] in inn)):
                return True
            anc = r.get('oanc', r['anc'])
            return bool(anc) and anc[-1] in inn
        return keep

    def only_keeps(self, r):
        f = self.only_filter()
        return f is None or f(r)

    def c_only(self, a):
        # groups: in the set; with no set (or cleared) the viewer keeps it for the next one (onlyGrp): so does this session
        cur = self.st.get('only') if isinstance(self.st.get('only'), dict) else None
        if a.get('groups') is not None:
            self.grp_next = bool(a['groups'])
            if cur:
                self.st['only'] = dict(cur, groups=self.grp_next)
        elif cur and isinstance(cur.get('groups'), bool):
            self.grp_next = cur['groups']
        if a.get('clear'):
            self.st['only'] = None
        elif 'modules' in a:
            if a['modules'] is None:
                fail('modules: a list of modules (clear: every module again)')
            ms = [] if isinstance(a['modules'], list) and not a['modules'] else [g['path'] for g in self.m.pick(self.st, a['modules'], scopes=True)]
            g = getattr(self, 'grp_next', None)
            self.st['only'] = {'modules': self.m.only_norm(ms) if self.m.doc else list(dict.fromkeys(ms)), 'on': True if a.get('on') is None else bool(a['on']),
                               **({'groups': g} if isinstance(g, bool) else {})}
            if a.get('open') is not False and a.get('on') is not False and ms:   # modules.js onlyOpen: the modules named and the ones above them
                by, f = {g['path']: g for g in self.m.groups}, dict(self.st.get('folds') or {})
                for p in dict.fromkeys(q for m in ms if m in by for q in [self.m.groups[i]['path'] for i in by[m]['anc']] + [m]):
                    f.pop(p, None)
                    f[p] = False
                self.st['folds'] = f
                if self.st.get('find') and self.opt('findOpen'):   # the find's Open off (its next search would fold them again)
                    self.config()['findOpen'] = False
        elif a.get('on') is not None:
            o = self.only()
            if not o:
                fail('only: no set to pause or resume (modules: […] first)')
            self.st['only'] = dict(o, on=bool(a['on']))
        if 'only' in self.st and self.st['only'] is not None:
            self.st['only'] = self.only()
        self.unselect_gone()
        return {'only': self.only(), 'groups': self.only_groups()}

    def c_radix(self, a):
        rx = a.get('radix')
        if rx is not None and not (rx in RADIX or re.fullmatch(r's?q\d{1,3}', str(rx))):
            fail(f'radix: one of {" ".join(RADIX)}, q<F> or sq<F> (fixed point), or null')
        rows = self.m.pick(self.st, a.get('signals'))
        p = dict(self.st.get('radix') or {})
        for r in rows:
            if rx is None:
                p.pop(r['full'], None)
            else:
                p[r['full']] = rx
        self.put_map('radix', p)
        return {'signals': len(rows)}

    def c_analog(self, a):
        rows = self.m.pick(self.st, a.get('signals'))
        n = 3 if a.get('rows') is True else a.get('rows')
        if isinstance(n, float) and finite(n) and n.is_integer():   # 2.0: a number as JavaScript has it
            n = int(n)
        bad = [r['full'] for r in rows if (r.get('width') or 1) < 2 and r.get('kind') != 'real']
        if bad and n:
            fail(f'not a bus: {", ".join(bad)}')
        if n is not None and n is not False and not (isinstance(n, int) and n >= 0):
            fail('rows: a number of rows, true, false or null')
        p = dict(self.st.get('analog') or {})
        for r in rows:
            if n is None:
                p.pop(r['full'], None)
            else:
                p[r['full']] = n or False
        self.put_map('analog', p)
        return {'signals': len(rows)}

    def c_deltas(self, a):
        if a.get('on') is not None and not isinstance(a['on'], bool):
            fail('on: true or false')
        mid = self.id_ok(a.get('id'), 'marker')
        if mid == 'all':
            fail('deltas: id is one marker')
        if a.get('lift') is not None and a['lift'] not in (True, 'above', 'below'):
            fail(f'lift: true, "above" or "below", not {json.dumps(a["lift"])}')
        if ('signal' in a or a.get('lift') is not None or 'to' in a or 'color' in a) and mid is None:
            fail('deltas: to, signal, lift and color go with id')
        ms = self.marks()
        if mid is not None and not mid <= len(ms):
            fail(f'no marker {a["id"]} (there are {len(ms)})')
        m = ms[mid - 1] if mid is not None else None
        to = a.get('to')
        if to not in (None, 'next') and whole(to) is not None and not isinstance(to, str):   # 3.0: 3, as Number.isInteger
            to = whole(to)
        if to is not None and to != 'next' and not (isinstance(to, int) and not isinstance(to, bool) and 1 <= to <= len(ms)):
            fail(f'to: a marker as listed (there are {len(ms)}), "next" or null, not {json.dumps(to)}')
        if to is not None and to == mid:
            fail('deltas: to is the marker it starts from')
        if m and 'to' not in a and not any(i == mid - 1 for i, _ in mark_deltas(ms)):
            fail(f'marker {a["id"]}: no Δ from it (the last in time, hidden, or none set)')
        sig = self.m.pick(self.st, a['signal'], one=True)[0]['full'] if a.get('signal') else None
        if a.get('lift') is not None and not (sig if 'signal' in a else m and m['dsignal']):
            fail('deltas: lift is the lane of a signal: give signal')
        bd = {k: self.bound(a[k], k) for k in ('dmin', 'dmax') if k in a}
        self.bounds_ok(bd, [m] if m else ms)
        if a.get('on') is not None:
            self.st['deltas'] = a['on']
        for x in [m] if m else ms:
            x.update(bd)
        if bd and not m:
            self.st['markers'] = mark_list(ms)
        if m:
            if 'signal' in a:
                m['dsignal'] = sig
            if a.get('lift') is not None:
                m['dlift'] = 'below' if a['lift'] == 'below' else None
            if not m['dsignal']:
                m['dlift'] = None
            if 'to' in a:
                m['dto'] = 0 if to is None else None if to == 'next' else to
            if 'color' in a:
                m['dcolor'] = color_ok(a['color'])
            self.st['markers'] = mark_list(ms)
        return {'on': bool(self.st.get('deltas')), 'deltas': [{'from': i + 1, 'to': j + 1, 'dt': abs(ms[j]['t'] - ms[i]['t'])} for i, j in mark_deltas(ms)]}

    def c_duplicate(self, a):
        rx = a.get('radix')
        if rx is not None and not (rx in RADIX or re.fullmatch(r's?q\d{1,3}', str(rx))):
            fail(f'radix: one of {" ".join(RADIX)}, q<F> or sq<F> (fixed point), or null')
        n = 3 if a.get('rows') is True else a.get('rows')
        if isinstance(n, float) and finite(n) and n.is_integer():   # 2.0: a number as JavaScript has it
            n = int(n)
        if n is not None and n is not False and not (isinstance(n, int) and n >= 0):
            fail('rows: a number of rows, true, false or null')
        rows = self.m.pick(self.st, a.get('signals'))
        have = [str(d) for d in self.st.get('dups') or []]
        if a.get('delete'):   # a copy named, or every copy of a signal named (its slices too), in the page's order (dupsBy)
            mine = lambda f: sorted((d for d in have if copy_base(d) == f), key=copy_order)
            gone = list(dict.fromkeys(x for r in rows for x in ([r['full']] if r.get('dup') else mine(r['full']))))
            if not gone:
                fail(f'no copies of {", ".join(r["full"] for r in rows)}')
            for d in gone:
                self.dup_drop(d)
            return {'deleted': gone}
        bad = [r['full'] for r in rows if r.get('bit') is not None]
        if bad:
            fail(f'a bit has no copy: {", ".join(bad)}')
        if a.get('bits') is not None:   # edit.js: a slice of the bus as a row
            b = a['bits']
            sl = b if isinstance(b, list) else [p.strip() for p in b.split(':')] if isinstance(b, str) and re.fullmatch(r'\s*\d+\s*:\s*\d+\s*', b) else None
            if not (isinstance(sl, list) and len(sl) == 2 and all(whole(x) is not None and whole(x) >= 0 for x in sl)):
                fail(f'bits: [msb, lsb] or "7:4", not {json.dumps(b)}')
            msb, lsb = (whole(x) for x in sl)
            out = []
            for r in rows:
                if r.get('slice'):
                    fail(f'{r["full"]}: slice the bus, not a slice')
                base = r.get('dup') or r['full']
                if not is_vec(r):
                    fail(f'{r["full"]}: not a bus')
                if not (lsb <= msb < r['width']):
                    fail(f'{r["full"]}: [{msb}:{lsb}] is not in its {r["width"]} bits (msb first, lsb 0)')
                d = f'{base}[{msb}:{lsb}]'
                if d not in have:
                    have.append(d)
                out.append(d)
            self.st['dups'] = have
            if rx is not None:
                self.c_radix({'signals': out, 'radix': rx})
            if n is not None:
                self.c_analog({'signals': out, 'rows': n})
            return {'copies': out}
        flat = [r['full'] for r in rows if (r.get('width') or 1) < 2 and r.get('kind') != 'real']
        if flat and n:
            fail(f'not a bus: {", ".join(flat)}')
        out = []
        for r in rows:
            base = r.get('dup') or r['full']
            d = f'{base}#{max([1] + [c[1] for c in map(dup_id, have) if c and c[0] == base]) + 1}'   # (a slice's dupN is 0)
            have.append(d)
            out.append(d)
            for k in ('radix', 'analog', 'paint'):   # as that row looks now
                m = self.st.get(k)
                if isinstance(m, dict) and r['full'] in m:
                    m[d] = m[r['full']]
        self.st['dups'] = have
        if rx is not None:
            self.c_radix({'signals': out, 'radix': rx})
        if n is not None:
            self.c_analog({'signals': out, 'rows': n})
        return {'copies': out}

    def dup_drop(self, d):
        """look.js dupDrop: a copy gone ("PADDR#2", a slice "PADDR[7:4]"), and what was its; what stood on it goes to its signal."""
        base = copy_base(d) or d
        to = lambda p: base if p == d else base + p[len(d):] if isinstance(p, str) and p.startswith(d + '[') else p
        self.st['dups'] = [x for x in self.st.get('dups') or [] if x != d]
        for k in ('radix', 'analog', 'paint'):
            if isinstance(self.st.get(k), dict):
                self.st[k].pop(d, None)
        for k in ('hidden', 'bits'):   # its bits hidden too
            if k in self.st:
                self.st[k] = [x for x in self.st[k] if not (x == d or (k == 'hidden' and isinstance(x, str) and x.startswith(d + '[')))]
        c = self.st.get('config')
        if isinstance(c, dict) and 'highlight' in c:   # look.js: picks.delete
            c['highlight'] = [x for x in prefixes(c['highlight']) if x != d]
        for g in self.st.get('groups') or []:
            g['signals'] = [x for x in g.get('signals') or [] if x != d]
        for b in (self.st.get('bookmarks') or []) + (self.st.get('markers') or []):
            for k in ('signal', 'dsignal'):
                if b.get(k):
                    b[k] = to(b[k])
        for s in self.st.get('spans') or []:
            if s.get('signals'):
                s['signals'] = [to(x) for x in s['signals']]
        if self.st.get('select') == d or (isinstance(self.st.get('select'), str) and self.st['select'].startswith(d + '[')):
            self.st['select'] = base   # the copy or a bit of it selected: its signal (look.js: sel.of === d)
        if isinstance(self.st.get('range'), dict) and self.st['range'].get('signal') == d:
            self.st['range']['signal'] = base

    def c_bits(self, a):
        on = a.get('on')
        if on is not None and not isinstance(on, bool):
            fail('on: true or false')
        rows = self.m.pick(self.st, a.get('signals'))
        bad = [r['full'] for r in rows if not is_vec(r)]
        if bad:
            fail(f'not a bus: {", ".join(bad)}')
        b = list(self.st.get('bits') or [])
        for r in rows:
            if on is False:
                b = [p for p in b if p != r['full']]
            elif r['full'] not in b:
                b.append(r['full'])
        self.st['bits'] = b
        return {'signals': len(rows)}

    def c_sort(self, a):
        if a.get('dir') not in SORTS:
            fail(f'dir: one of {" ".join(SORTS)}')
        c = self.config()
        c['sort'] = a['dir']
        if a.get('ignore') is not None:
            c['sortIgnore'] = sorted(prefixes(a['ignore']), key=lambda s: -len(s))
        return {'sort': c['sort'], 'ignore': c.get('sortIgnore')}

    def c_style(self, a):
        if a.get('name') is not None and a['name'] not in STYLES:
            fail(f'name: one of {" ".join(STYLES)}')
        base = self.m.cfg.get('style') if self.m.cfg.get('style') in STYLES else 'auto'   # look.js setStyle: null is the settings' style
        self.config()['style'] = a['name'] if a.get('name') is not None else base   # (as state() has it: never null)
        return {'style': self.config()['style']}

    def c_layout(self, a):
        """Where the rows scroll and the bar's tools folded (view.js setScroll, setTools): as the state's maxHeight, toolsFolded."""
        if a.get('scroll') is not None and a['scroll'] not in ('window', 'page'):
            fail('scroll: window or page')
        if a.get('tools') is not None and a['tools'] not in ('fold', 'open'):
            fail('tools: fold or open')
        h = a.get('height')
        if h is not None and not (h > 0 if isinstance(h, (int, float)) and not isinstance(h, bool) else
                                  isinstance(h, str) and re.fullmatch(r'\s*[\d.]+\s*(px|vh|em|rem|%)?\s*', h)):
            fail('height: 600 (px) or "80vh"')
        c, base = self.config(), self.m.cfg.get('maxHeight')
        win = base is not None and base != ''
        if a.get('scroll') is not None or h is not None:
            c['maxHeight'] = ('' if win else None) if a.get('scroll') == 'page' else h if h is not None else base if win else '80vh'
        if a.get('tools') is not None:
            c['toolsFolded'] = a['tools'] == 'fold'
        mh = c['maxHeight'] if 'maxHeight' in c else base
        tf = c['toolsFolded'] if 'toolsFolded' in c else self.m.cfg.get('toolsFolded')
        return {'scroll': 'window' if mh is not None and mh != '' else 'page', 'height': mh or None, 'tools': 'fold' if tf else 'open'}

    def opt(self, k, default=None):
        """A setting as the viewer has it: the state's config, else the page's, else the default (wavelens.config.js)."""
        c = self.st.get('config') or {}
        return c[k] if k in c else self.m.cfg.get(k, default)

    def c_find(self, a):
        c = self.config()
        for k, key in (('case', 'findCase'), ('word', 'findWord'), ('regex', 'findRegex'), ('highlight', 'findHighlight'), ('open', 'findOpen'),
                       ('mask', 'findMask')):
            if a.get(k) is not None:
                c[key] = bool(a[k])
        self.st['find'] = str(a.get('query') if a.get('query') is not None else '')
        found = self.found(self.st['find'])   # (no "fold" written: the page folds what the find leaves out when it opens, B-19)
        return {'found': [r['full'] or r['name'] for r in found][:50], 'count': len(found),
                'plugins': "not counted: a plugin's rows (the assertions) are the page's only"}

    def found(self, q):
        """view.js find: the rows the query matches, in display order (the rows of plugins, not known here, left out)."""
        s, rx = str(q or '').strip(), None
        if self.opt('findRegex'):
            try:
                src = re.sub(r'\\([<>])', r'\\b', s)
                rx = re.compile(f'^(?:{src})$' if self.opt('findWord') else src, 0 if self.opt('findCase') else re.I) if s else None
            except re.error:
                rx = None
            terms = [s] if rx else []
        else:
            terms = [w for w in s.split() if w.replace('.', '')]
        if not terms:
            return []
        groups = {g['id']: g for g in self.m.groups}
        groups.update({r['id']: r for r in self.user_rows() if r['type'] == 'group'})
        cs, word = bool(self.opt('findCase')), bool(self.opt('findWord'))
        return [r for r in self.ordered() if r['type'] != 'space' and find_row(r, terms, groups, cs, word, rx)]

    def c_gaps(self, a):
        c, xs = self.config(), self.exprs()
        by = any(x['gap'] for x in xs)
        if by and (a.get('reset') or a.get('on') is False or a.get('view') is False):   # look.js setGaps: the gaps off end the expressions'
            for x in xs:
                x['gap'] = False
            self.st['exprs'] = [expr_json(x) for x in xs]
        if a.get('reset'):   # the page's own again (view.js setGaps(null)): a value equal to the page's setting is no override
            c.update({k: self.m.cfg.get(k, GAP_DEFAULTS[k]) for k in ALL_GAP_KEYS})
        for k, g in GAP_KEYS.items():
            if k in a and not (by and a[k] is True and k in ('on', 'view')):   # on already, by them: not your setting
                c[g] = a[k]
        return {'gaps': self.gap_opt()}

    def gap_opt(self):
        """view.js gapOpt: the gaps' settings as they are now."""
        o = {k: self.opt(k, GAP_DEFAULTS[k]) for k in ALL_GAP_KEYS}
        o['gaps'], o['gapOnly'], o['gapView'] = bool(o['gaps']), bool(o['gapOnly']), bool(o['gapView'])
        o['gapSignals'], o['gapAux'], o['gapClock'] = prefixes(o['gapSignals']), prefixes(o['gapAux']), o['gapClock'] or None
        if o['gapCount'] not in ('off', 'clock', 'edges', 'rise', 'fall', 'any'):
            o['gapCount'] = 'clock'
        by = [i + 1 for i, x in enumerate(self.exprs()) if x['gap']]
        if by:   # expressions with gap have them on, on the waves
            o.update(gaps=True, gapView=True, gapBy=by)
        return o

    def c_cycles(self, a):
        """The clock cycles under the time axis (view.js setCycles): as the state's cycles, cycleClock (a full path), cycleZero."""
        o = {}   # every argument checked before anything changes
        if a.get('on') is not None:
            o['cycles'] = bool(a['on'])
        if 'clock' in a:
            r = None if a['clock'] is None else self.m.pick(self.st, a['clock'], one=True)[0]
            if r and self.m.doc and r.get('width', 1) != 1:   # a state without its page: the width is not known
                fail(f'clock: {r["full"]} is not a 1-bit signal')
            o['cycleClock'] = r['full'] if r else None
        if 'zero' in a:
            o['cycleZero'] = None if a['zero'] is None else self.time(a['zero'], 'zero')
        c = self.config()
        if a.get('reset'):   # the page's settings again (null in a state is the clock found, the first edge)
            c.update({k: self.m.cfg.get(k, CYC_DEFAULTS[k]) for k in CYC_KEYS})
            c['cycles'] = bool(c['cycles'])
        c.update(o)
        cy = {k: self.opt(k, CYC_DEFAULTS[k]) for k in CYC_KEYS}
        z = parse_t(cy['cycleZero'])
        cy.update(cycles=bool(cy['cycles']), cycleClock=cy['cycleClock'] or None, cycleZero=z if finite(z) else None)
        clk = cy['cycleClock'] or next((r['full'] for r in self.m.sigs() if r['width'] == 1 and re.search('clk|clock', r['name'], re.I)), None)
        return {'cycles': cy, 'clock': clk, 'cycle': None}   # the cursor's cycle: from the clock's edges, in the page (live) only

    def c_reset(self, a):
        self.config()['highlight'] = []
        self.st.update({'select': None, 'find': '', 'range': None, 'cursor2': None})
        return {}

    def c_state(self, a):
        return {'state': self.st}

    def c_set_state(self, a):
        """A state back (Load…): every key it has replaces this one's, the keys of its config one by one; a key it does not
        have stays (null: none, or the page's own)."""
        s = a.get('state')
        if not isinstance(s, dict) or s.get('wavelens') != 'state':
            fail('set_state: not a saved viewer state ({"wavelens": "state", …})')
        for k, v in s.items():
            if k == 'config':
                if isinstance(v, dict):
                    self.config().update(v)
            elif k in STATE_KEYS:   # what a state has (view.js state()); another key is not the viewer's
                self.st[k] = v
        for k in ('bookmarks', 'markers', 'arrows', 'spans', 'groups'):   # an entry that is no object: left out, as the page does
            if isinstance(self.st.get(k), list):
                self.st[k] = [x for x in self.st[k] if isinstance(x, dict)]
        if 'dups' in s and self.m.doc:   # as the viewer keeps them: the copies of signals of these waves
            self.st['dups'] = [r['full'] for r in self.m.dup_rows(s)]
        if 'bits' in s and self.m.doc:   # as the viewer keeps them: the buses of these waves
            vec = {r['full'] for r in self.m.sigs() if is_vec(r)}
            self.st['bits'] = [p for p in dict.fromkeys(map(str, s['bits'] if isinstance(s['bits'], list) else [])) if p in vec]
        if 'only' in s:   # as the viewer keeps it: its known modules, on unless false; a selection it leaves out goes
            if isinstance(s['only'], dict):   # view.js setState: its groups, else the setting's, for the next set too (onlyGrp)
                self.grp_next = s['only']['groups'] if isinstance(s['only'].get('groups'), bool) else None
            self.st['only'] = self.only()
            self.unselect_gone()
        return {'missing': self.missing(s)}

    def missing(self, s):
        """view.js setState: the paths a state names that these waves do not have."""
        if not self.m.doc:
            return []
        sigs = {r['full'] for r in self.m.sigs() + self.m.dup_rows(self.st)}
        paths, out = sigs | {g['path'] for g in self.m.groups}, []
        c = s['config'] if isinstance(s.get('config'), dict) else {}
        lst = lambda x: x if isinstance(x, list) else []
        def see(p, pool=paths):
            if isinstance(p, str) and p and not p.startswith('@') and p not in pool and p not in out and not (pool is paths and self.m.bit(p, self.st)):
                out.append(p)
        for p in lst(s.get('dups')):
            see(p, {r['full'] for r in self.m.dup_rows(self.st)})
        for g in lst(s.get('groups')):
            for p in lst(g.get('signals')) if isinstance(g, dict) else []:
                see(p, sigs)
        for p in lst(c.get('fold')) + [p for p in (s['folds'] if isinstance(s.get('folds'), dict) else {}) if p != '*']:
            see(p)
        for p in prefixes(c['highlight']) if c.get('highlight') is not None else []:
            if '*' not in p:
                see(p)
        for k in ('paint', 'radix', 'analog'):
            for p in s[k] if isinstance(s.get(k), dict) else {}:
                see(p)
        for p in lst(s.get('hidden')) + lst(s.get('bits')):
            see(p)
        mods = {g['path'] for g in self.m.scopes()}
        for p in lst(s['only'].get('modules')) if isinstance(s.get('only'), dict) else []:
            see(p, mods)
        for b in lst(s.get('bookmarks')):
            see(b.get('signal') if isinstance(b, dict) else None)
        see(s.get('select'))
        see(s['range'].get('signal') if isinstance(s.get('range'), dict) else None)
        return out

    def user_rows(self):
        """Your groups as the viewer shows them (edit.js ugRows): a header "@name", then its signals."""
        by, out = {r['full']: r for r in self.m.sigs() + self.m.dup_rows(self.st)}, []
        for i, g in enumerate(self.groups()):
            gid = -1 - i
            out.append({'type': 'group', 'user': True, 'id': gid, 'name': g['name'], 'full': '@' + g['name'], 'path': '@' + g['name'], 'anc': []})
            out += [dict(by[f], anc=[gid], ug=True, oanc=by[f]['anc']) for f in g['signals'] if f in by]
        return out

    def ordered(self, only=True, hidden=False):
        """view.js allRows: your groups at the top, then the rows in the order of "sort"; hidden rows and what is under a
        hidden module left out, then (only) the rows Only leaves out."""
        sort, ign = self.opt('sort', 'none'), sorted(prefixes(self.opt('sortIgnore')), key=lambda p: -len(p))
        rows = order_rows(self.m.rows, sort, ign, self.m.cfg.get('groupOrder', 'file'))
        copies = self.m.dup_rows(self.st)
        if copies:   # (look.js withDups) under their signal, in their order
            copies.sort(key=lambda d: copy_order(d['full']))   # the slices first, the highest msb first, then #2, #3 … (B-02)
            rows = [x for r in rows for x in [r] + (([d for d in copies if d['dup'] == r['full']]) if r['type'] == 'sig' else [])]
        rows = self.user_rows() + rows
        h = set(self.st.get('hidden') or [])
        ids = {g['id'] for g in self.m.groups if g['path'] in h}
        out = rows if hidden else [r for r in rows if not (r['type'] != 'space' and r.get('full') and not r.get('ug') and r['full'] in h) and
                                   not ids & set(r['anc'])]
        keep = self.only_filter() if only else None
        return [r for r in out if keep(r)] if keep else out

    def compare(self):
        """The compare of the view: the state's, else the page's own (WaveJSON "compare")."""
        c = self.st['compare'] if 'compare' in self.st else self.m.doc.get('compare') if self.m.doc and self.m.timed else None
        return c if isinstance(c, dict) else None

    def c_compare(self, a):
        """A second dump over these waves (diff.js compareResult): result (sva diff's, as the WaveJSON "compare"), dump (a VCD or
        FST: sva diff of the view's dump, a, and it, over the view's window and rows; the page's file only), off: none; show: which
        run the page opens with (a, b, overlay; compareView), alone or with result or dump."""
        if a.get('off'):
            self.st['compare'] = None
            self.st.pop('compareShow', None)
            return {'off': True}
        show = a.get('show')
        if show is not None and show not in ('a', 'b', 'overlay'):
            fail(f'compare: show is a, b, overlay, not "{show}"')
        if show is not None and a.get('result') is None and not a.get('dump'):
            c = self.compare()
            if c is None:
                fail(f'compare {show}: compare with a second dump first (Compare… in the bar)')
            self.compare_show(show, c)
            return {'show': show, 'name': c.get('name') or 'B'}
        if a.get('result') is not None:
            c = a['result']
            if not isinstance(c, dict) or not isinstance(c.get('signals'), dict):
                fail('compare: a result {name, from, to, signals: {path: {spans}}} (sva diff\'s, as the page\'s "compare")')
        elif a.get('dump'):
            c = compare_dump(self.m, getattr(self, 'base', None), a)
        else:
            fail('compare: result, show, dump or off')
        if not self.m.timed and self.m.doc:
            fail('compare: these waves are clock-sampled (one cell per cycle): a compare is of exact waves')
        self.st['compare'] = c
        self.st.pop('compareShow', None)
        if show is not None:
            self.compare_show(show, c)
            return dict(compare_summary(c), show=show)
        return compare_summary(c)

    def compare_show(self, show, c):
        """The page's run on opening: B's needs its values in the result (diff.js cmpCant)."""
        if show != 'a' and not c.get('vcd'):
            fail(f'compare {show}: this compare has the differences only, not the values of {c.get("name") or "B"} '
                 '(a saved one, a cut too large for the page, one of --align): compare again')
        self.st['compareShow'] = show

    def c_rows(self, a):
        """edit.js rows: in display order, the hidden ones where they would be."""
        pat = str(a.get('pattern') or '')
        rx = glob_re(pat) if '*' in pat else None
        h = set(self.st.get('hidden') or [])
        shown = [r for r in self.ordered(only=False, hidden=True) if (r['type'] == 'sig' and not r.get('ug')) or (r['type'] == 'group' and r.get('full'))]
        c = self.compare() or {}
        sigs, miss = c.get('signals') or {}, set(c.get('missing') or [])
        mark = lambda r: (['≠'] if ((sigs.get(r.get('path') or r['full']) or {}).get('spans')) else
                          ['missing'] if (r.get('path') or r['full']) in miss else []) if r['type'] == 'sig' else []
        bits = set(self.st.get('bits') or [])   # a bus shown bit by bit: its bits under it, MSB first (edit.js rows; B-20)
        vec = lambda r: is_vec(r) and r['full'] in bits
        rows = [x for r in shown for x in [[r['full'], 'group' if r.get('user') else 'module' if r['type'] == 'group' else r['width'], *mark(r)]] +
                ([[f"{r['full']}[{i}]", 1, 'bit'] for i in range(r['width'] - 1, -1, -1)] if vec(r) else [])]
        rows = [r for r in rows if not pat or (rx.match(r[0]) if rx else pat.lower() in r[0].lower())]
        def num(x, d):   # the page's +x || d
            try:
                f = float(x) if not isinstance(x, bool) else float(x)
            except (TypeError, ValueError):
                return d
            return int(f) if finite(f) and f else d
        off, n = max(0, num(a.get('offset'), 0)), max(1, num(a.get('limit'), 200) or 200)
        out = {'total': len(rows), 'rows': rows[off:off + n]}
        if off + n < len(rows):
            out['next_offset'] = off + n
        return out


def collate(s):
    """A sort key as Intl.Collator(numeric, sensitivity base) gives the order: marks, then numbers by value, then letters
    without case or accents."""
    out = []
    for part in re.findall(r'\d+|\D', unicodedata.normalize('NFKD', s)):
        if part.isdigit():
            out.append((1, int(part), ''))
        elif not unicodedata.combining(part):
            out.append((2, 0, part.lower()) if part.isalpha() else (0, 0, part))
    return out


def order_rows(rows, sort, pfx, group_order):
    """model.js orderRows: siblings (between spacers) sorted by name without the ignored prefixes; groups move as a block."""
    sorting, gs = sort in ('asc', 'desc'), -1 if group_order == 'first' else 1 if group_order == 'last' else 0
    if not sorting and not gs:
        return list(rows)
    kids = {None: []}
    for r in rows:
        kids.setdefault(r['anc'][-1] if r['anc'] else None, []).append(r)
        if r['type'] == 'group':
            kids.setdefault(r['id'], [])
    strip = lambda n: next((n[len(p):] for p in pfx if n.startswith(p) and len(n) > len(p)), n)
    c = lambda x, y: (collate(x) > collate(y)) - (collate(x) < collate(y))
    sgn = -1 if sort == 'desc' else 1
    def cmp(a, b):
        g = gs * ((a['type'] == 'group') - (b['type'] == 'group'))
        return g or (sgn * (c(strip(a['name']), strip(b['name'])) or c(a['name'], b['name'])) if sorting else 0)
    out = []
    def emit(lst):
        run = []
        def flush():
            for r in sorted(run, key=functools.cmp_to_key(cmp)):
                out.append(r)
                if r['type'] == 'group':
                    emit(kids.get(r['id'], []))
            run.clear()
        for r in lst:
            if r['type'] == 'space':
                flush()
                out.append(r)
            else:
                run.append(r)
        flush()
    emit(kids[None])
    return out


def fuzzy(q, s, cs=False):
    """model.js fuzzy: the letters of q in order in s -> a score, or None."""
    t, q = (s, q) if cs else (s.lower(), q.lower())
    j, score, prev = 0, 0, -2
    for i, ch in enumerate(t):
        if j >= len(q):
            break
        if ch == q[j]:
            score += (6 if i == prev + 1 else 1) + (4 if i == 0 or t[i - 1] in '._[/ ' else 0)
            prev, j = i, j + 1
    return score - len(t) / 100 if j == len(q) else None


def find_row(r, terms, groups, cs, word, rx):
    """model.js findRow: a row against the query's words (every one), or against the regex -> whether it matches."""
    name, path = r['name'], r.get('full') or r['name']
    scope = '.'.join((groups.get(i) or {}).get('name', '') for i in r['anc']) if r['anc'] else path.rsplit('.', 1)[0] if '.' in path else ''
    leaf = r['path'].rsplit('.', 1)[-1] if r.get('path') else ''
    if rx:
        return bool(rx.search(name) or (leaf and rx.search(leaf)) or rx.search(path))
    eq = (lambda x, y: x == y) if cs else (lambda x, y: x.lower() == y.lower())
    for w in terms:
        if word:
            hit = (eq(path, w) or (len(path) > len(w) and eq(path[-len(w) - 1:], '.' + w))) if '.' in w else (eq(name, w) or (leaf and eq(leaf, w)))
            if not hit:
                return False
            continue
        k = w.rfind('.')
        sq, nq = (w[:k].replace('.', ''), w[k + 1:]) if k >= 0 else ('', w)
        ms = fuzzy(sq, scope, cs) if sq else 0
        mn = fuzzy(nq, name, cs) if nq else 0
        if mn is None and leaf and leaf != name:
            mn = fuzzy(nq, leaf, cs)
        if ms is None or mn is None:
            return False
    return True


# ---------------- pages and state files ----------------
class Page(wavepage.Page):
    """A page made by mkhtml.py (wavepage.Page) with the rows of its views."""

    def model(self, key):
        return Model(self.waves[key], self.settings)


def edit_page(path, ops, view=None):
    """The commands on a page's edits of one view -> (results, view key, revision or None when nothing changed)."""
    p = Page(path)
    key = p.view(view)
    ed = Editor(p.model(key), p.state(key))
    ed.base = os.path.dirname(os.path.abspath(path))   # compare dump: the page's dump is beside it
    before = json.dumps(tidy(ed.st), sort_keys=True)   # 30000.0 is 30000
    res = ed.run(ops)
    rev = None
    if json.dumps(tidy(ed.st), sort_keys=True) != before:
        rev = p.put(key, ed.st)
        p.save()
    return res, key, rev


def compare_summary(c):
    """What the command compare answers (as the page's): {name, compared, differ, first, missing}; compared: the signals of the
    result (the page counts its rows among them: a row it does not show is not compared there)."""
    sigs = c.get('signals') or {}
    return {'name': c.get('name') or 'B', 'compared': len(sigs), 'differ': sum(1 for x in sigs.values() if (x or {}).get('spans')),
            'first': c.get('first'), 'missing': len(c.get('missing') or [])}


def row_hits(r, paths, tails, scope):
    """Row r in a dump (paths, tails: paths by their last part), diff.js cmpFind's rules: its path; else its name, full then short,
    under the view's scope or as it is, else the paths ending with it -> the paths found (several: the caller chooses)."""
    if r.get('path') in paths:
        return [r['path']]
    for n in dict.fromkeys(x for x in (r.get('full'), r.get('name')) if x):
        hit = next((p for p in (scope and f'{scope}.{n}', n) if p and p in paths), None)
        if hit:
            return [hit]
        hit = [p for p in tails.get(n.rsplit('.', 1)[-1], []) if p.endswith('.' + n)]
        if hit:
            return hit
    return []


def compare_dump(model, base, a):
    """sva diff of the view's dump (a's "a", else the page's meta.waves beside it) and a's "dump" over the view's window and
    rows -> the result (svabuild.compare). A row's path in the dump: its own, else its name under the view's scope, else the
    one path that ends with it (diff.js cmpFind's rules)."""
    import dumpscan, svabuild
    meta = model.doc.get('meta') or {}
    if not base and not a.get('a'):
        fail('compare dump: on a page\'s file (its dump is beside it), or give "a", the dump of these waves')
    here = lambda p: os.path.abspath(os.path.join(base or '.', os.path.expanduser(str(p))))
    dump_a, dump_b = here(a.get('a') or meta.get('waves') or ''), here(a['dump'])
    for p, what in ((dump_a, 'the dump of these waves (a)'), (dump_b, 'dump')):
        if not os.path.isfile(p):
            fail(f'compare: no such file {p} ({what})')
    exe = svabuild.find_bin()
    if not exe:
        fail('compare dump: needs the sva CLI (make sva-build, or bin/<os>-x86_64/sva)')
    d = dumpscan.read(dump_a, body=None)
    paths = set(d.vars) if d else set()
    scope = meta.get('scope') or ''
    tails = {}
    for p in paths:
        tails.setdefault(p.rsplit('.', 1)[-1], []).append(p)
    found, votes = [], collections.Counter()
    for r in model.sigs():
        if r.get('bit') is not None:
            continue
        hit = row_hits(r, paths, tails, scope)
        found.append((r['full'], hit))
        if len(hit) == 1:
            votes[hit[0][:len(hit[0]) - len(r['full']) - 1]] += 1
    # a name several paths end with (the converter left out the prefix the signals share): the prefix most rows have
    pick = lambda full, hit: max(hit, key=lambda p: (votes[p[:len(p) - len(full) - 1]], -p.count('.')))
    rows = [(full, pick(full, hit) if hit else full) for full, hit in found]
    t0, t1 = meta.get('from_ps', model.t0), meta.get('to_ps', model.t1)
    off = a.get('offset')
    if off not in (None, ''):
        t = parse_t(off) if isinstance(off, str) else off
        if not finite(t):
            fail(f'compare: offset "{off}" is not a time')
        off = f'{round(t)}ps'
    return svabuild.compare(exe, dump_a, dump_b, rows, t0, t1, a.get('map'), off)


def edit_state(path, ops, model=None):
    """The commands on a saved state (.view.json) -> results; the file written when it changed."""
    try:
        with open(path, encoding='utf-8') as f:
            st = json.load(f)
    except OSError as e:
        fail(f'cannot read {path}: {e.strerror}')
    except ValueError as e:
        fail(f'{path}: not JSON ({e})')
    if not isinstance(st, dict) or st.get('wavelens') != 'state':
        fail(f'{path}: not a saved viewer state (the viewer\'s Save writes one)')
    head = {k: st[k] for k in ('wavelens', 'version', 'title') if k in st}
    ed = Editor(model or Model(), {k: v for k, v in st.items() if k not in head})
    res = ed.run(ops)
    out = dict(head, **tidy(ed.st))
    out['version'] = max(STATE_VERSION, st.get('version') or 0)
    if out != st:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    return res


# ---------------- the commands on a config file (mkhtml.py's): a rebuild keeps them ----------------
# the commands a config's "state" of a view takes (the view's state as the page opens: the Editor of a page's edits on it); not what a
# session is (the cursors, the range, the selection, the find, Only, the FSM layer, the order) nor what reads the page
STATE_OPS = [k for k in COMMANDS if k not in LIVE_ONLY and k not in CONFIG_OPS and k not in
             ('cursor', 'cursor2', 'range', 'select', 'find', 'only', 'fsm', 'sort', 'reset', 'state', 'rows', 'picture', 'compare', 'view', 'fold', 'unfold')]
# what --from-page takes of a page's state into its config: what this browser keeps of a viewer, the expressions
FROM_PAGE = ['groups', 'paint', 'radix', 'analog', 'hidden', 'dups', 'bits', 'markers', 'deltas', 'spans', 'bookmarks', 'arrows', 'exprs']


def config_ops(view, ops):
    """The commands on a view of a config: bookmark, arrow and span on its "bookmarks", "arrows", "spans", as written (a
    bookmark's "at" stays until a "t" replaces it, and the other way); the rest of a view's look (group, radix, analog, hide,
    duplicate, bits, paint, highlight, marker, deltas, expr, gaps, cycles, style …) on its "state", the state the page opens
    with (mkhtml.py puts it in the page's edits), by the commands of a page's edits; view: the window ("from", "to") ->
    results; view changed in place."""
    res = []
    for o in ops:
        try:
            if isinstance(o, dict) and o.get('op') == 'view':
                res.append({'op': 'view', **cfg_view(view, {k: v for k, v in o.items() if k != 'op'})})
                continue
            if isinstance(o, dict) and o.get('op') in STATE_OPS:
                e = Editor(Model(), view.get('state') if isinstance(view.get('state'), dict) else {})
                r = e.run([o])[0]
                if 'error' in r:
                    fail(r['error'])
                view['state'] = tidy({k: v for k, v in e.st.items() if v is not None})
                res.append(r)
                continue
            if not isinstance(o, dict) or o.get('op') not in CONFIG_OPS:
                fail(f'{json.dumps((o or {}).get("op") if isinstance(o, dict) else o)}: in a config {", ".join(list(CONFIG_OPS) + ["view"] + STATE_OPS)} '
                     '(the rest is a page\'s session or reads the page: give "page")')
            op, a = o['op'], {k: v for k, v in o.items() if k != 'op'}
            bad = sorted(set(a) - set(CONFIG_OPS[op]))
            if bad:
                fail(f'{op}: no argument {", ".join(bad)} in a config (it takes: {", ".join(CONFIG_OPS[op])})')
            res.append({'op': op, **getattr(wavepage, 'cfg_' + op)(view, a)})
        except WaveError as e:
            res.append({'op': o.get('op') if isinstance(o, dict) else None, 'error': str(e)})
    return res


def edit_config(path, ops, view=None, from_page=None, keys=None):
    """The commands on a view of a config file (mkhtml.py's, its "views"; none: the top level) -> (results, view, the
    JSON paths changed). The whole list is checked first: a bad command writes nothing. The file is written atomically,
    its keys and the other views as they were; bookmarks a view takes from the top level become its own. from_page: a
    page made of it, whose state (its edits: viewedit.py, Save page) goes into the view first (keys: only those of FROM_PAGE)."""
    try:
        with open(path, encoding='utf-8') as f:
            cfg = json.load(f)
    except OSError as e:
        fail(f'cannot read {path}: {e.strerror}')
    except ValueError as e:
        fail(f'{path}: not JSON ({e})')
    if not isinstance(cfg, dict):
        fail(f'{path}: a config is a JSON object')
    views = cfg.get('views') if isinstance(cfg.get('views'), dict) else None
    if views:
        if view is None and len(views) == 1:
            view = next(iter(views))
        if view not in views:
            fail(f'view: one of {", ".join(views)} (the config\'s "views")' if view is None else f'no view "{view}" in {path} (have: {", ".join(views)})')
        target, at = views[view], f'views.{view}'
    else:
        target, at = cfg, ''
    import copy
    work = copy.deepcopy(target)
    marks = (from_page and (keys is None or any(k in keys for k in ('bookmarks', 'arrows', 'spans')))) or \
        any(isinstance(o, dict) and o.get('op') in CONFIG_OPS for o in ops)
    for k in ('bookmarks', 'arrows', 'spans'):   # the top level's, made the view's own (when it is given its own)
        if marks and views and k not in work and isinstance(cfg.get(k), list):
            work[k] = copy.deepcopy(cfg[k])
    res = []
    if from_page:
        res.append(page_into(work, from_page, view, keys, cfg.get('waves')))
    res += config_ops(work, ops)
    if any('error' in r for r in res):
        return res, view, []
    same = lambda a, b: (a or None) == (b or None)   # (none and [] alike)
    changed_keys = [k for k in ('bookmarks', 'arrows', 'spans', 'state', 'from', 'to') if not same(work.get(k), target.get(k))]
    for k in changed_keys:
        if k in ('state', 'from', 'to') and not work.get(k):
            target.pop(k, None)
        else:
            target[k] = work.get(k) or ([] if k in ('bookmarks', 'arrows', 'spans') else work.get(k))
    changed = [f'{at}.{k}' if at else k for k in changed_keys]
    if not changed:
        return res, view, []
    tmp = path + '.part'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, path)
    return res, view, changed


PAGE_CFG = ['style', 'maxHeight', *ALL_GAP_KEYS, *CYC_KEYS]   # the settings of a page's state a config keeps (edit.js KEPT_CFG)


def page_into(work, page, view, keys=None, waves=None):
    """--from-page: the state of a page's view (its edits) into a config's view: bookmarks, arrows, spans as its own keys, the
    rest (FROM_PAGE, the settings of PAGE_CFG) into its "state" -> a result {op: "from_page", taken, note}."""
    p = Page(page)
    key = p.view(view or None)   # a view the page has not got: said, with the page's views
    st = clean_state(p.state(key))
    want = FROM_PAGE + ['config'] if keys is None else list(keys)
    bad = [k for k in want if k not in FROM_PAGE + ['config']]
    if bad:
        fail(f'--keys: {", ".join(bad)} is no key of a page\'s view here (have: {", ".join(FROM_PAGE + ["config"])})')
    out, taken = dict(work['state']) if isinstance(work.get('state'), dict) else {}, []
    for k in want:
        if k == 'config':
            c = {n: v for n, v in (st.get('config') or {}).items() if n in PAGE_CFG}
            if c:
                out['config'] = {**(out.get('config') or {}), **c}; taken.append('config')
        elif k in st:
            if k in ('bookmarks', 'arrows', 'spans'):   # the config's own keys, in its form
                work[k] = cfg_form(k, st[k], work.get(k))
            else:
                out[k] = st[k]
            taken.append(k)
    if out:
        work['state'] = out
    else:
        work.pop('state', None)
    n = lambda k: len(st.get(k) or [])
    note = ', '.join(x for x in (f'{n("markers")} markers' if 'markers' in taken else '', f'{n("groups")} groups' if 'groups' in taken else '',
                                  f'radix on {len(st.get("radix") or {})}' if 'radix' in taken else '', f'{n("bookmarks")} bookmarks' if 'bookmarks' in taken else '',
                                  f'{n("exprs")} expressions' if 'exprs' in taken else '') if x)
    meta = (p.waves[key].get('meta') or {}).get('waves')
    other = waves and meta and os.path.basename(str(waves)) != meta
    return {'op': 'from_page', 'view': key, 'taken': taken, **({'note': note} if note else {}),
            **({'warning': f'the page is of {meta}, the config of {os.path.basename(str(waves))}'} if other else {})}


def read_ops(text):
    """--ops: JSON (a command or a list), @file, or - (stdin)."""
    if text == '-':
        text = sys.stdin.read()
    elif text.startswith('@'):
        with open(text[1:], encoding='utf-8') as f:
            text = f.read()
    try:
        ops = json.loads(text)
    except ValueError as e:
        fail(f'the commands are not JSON: {e}')
    return ops if isinstance(ops, list) else [ops]


MEASURE_CSV = ('n_from', 'label_from', 't_from_ns', 'n_to', 'label_to', 't_to_ns', 'dt_ns', 'cycles', 'dmin', 'dmax', 'ok', 'signal')


def measure_text(rows, timed=True, csv_out=False):
    """The table of measure_list as text lines (--measure) or CSV (--csv): times in ns (timed waves), else in cycles."""
    ns = (lambda t: f'{t / 1000:g}') if timed else (lambda t: f'{t:g}')
    bd = lambda b: '' if b is None else f'{b["cycles"]:g} cycles' if isinstance(b, dict) else ns(b) + (' ns' if timed and not csv_out else '')
    if csv_out:
        import csv, io
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator='\n')
        w.writerow(MEASURE_CSV)
        for r in rows:
            w.writerow([r['from']['id'], r['from']['label'], ns(r['from']['t']), r['to']['id'], r['to']['label'], ns(r['to']['t']), ns(r['dt']),
                        r.get('cycles', ''), bd(r.get('dmin')), bd(r.get('dmax')), '' if r.get('ok') is None else str(r['ok']).lower(), r.get('signal') or ''])
        return buf.getvalue()
    u = ' ns' if timed else ' cycles'
    out = [f'{len(rows)} measurement{"" if len(rows) == 1 else "s"} (the Δ between the markers)']
    for r in rows:
        a, b = r['from'], r['to']
        lim = ' … '.join([bd(r.get('dmin')) or '—', bd(r.get('dmax')) or '—']) if r.get('dmin') is not None or r.get('dmax') is not None else ''
        out.append(f'{a["id"]:>3} → {b["id"]:<3} {ns(a["t"]) + u:>14} → {ns(b["t"]) + u:<14} Δ {ns(r["dt"]) + u:<12}' +
                   (f' {r["cycles"]} cycles' if 'cycles' in r else '') + (f'  [{lim}] {"ok" if r.get("ok") else "✗" if r.get("ok") is False else "?"}' if lim else '') +
                   (f'  {a["label"]} → {b["label"]}' if a['label'] or b['label'] else ''))
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.replace('{live}', ', '.join(LIVE_ONLY)), formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file', nargs='?', help='a page (.html) or a saved state (.view.json)')
    ap.add_argument('--ops', help='the commands: JSON (one {"op": …} or a list), @file.json, or - for stdin')
    ap.add_argument('--view', help='the view of a page of several (its key: WAVES.<key>)')
    ap.add_argument('--model', help='with a .view.json: the page whose signals the names are checked against')
    ap.add_argument('--get', action='store_true', help='print the edits (a page: of every view, or --view) as JSON')
    ap.add_argument('--views', action='store_true', help='print the views of a page: key, title, signals, revision of its edits')
    ap.add_argument('--commands', action='store_true', help='print the commands and their arguments')
    ap.add_argument('--config', metavar='FILE', help='a config file (mkhtml.py\'s): bookmark, arrow and span on its view --view, and the look '
                    '(group, radix, paint, hide, marker, deltas, duplicate, expr, … into its "state"): a rebuild keeps them; a bookmark\'s "at" stays '
                    'until a "t" replaces it')
    ap.add_argument('--from-page', metavar='PAGE', help='with --config: the view of a page made of it (its edits: viewedit.py, Save page) into '
                    'the config: groups, colours, radix, analog, hidden, copies, bits, markers, the Δ, bookmarks, arrows, spans, expressions, the '
                    'look (its "state"; mkhtml.py opens the page with it)')
    ap.add_argument('--keys', help='with --from-page: only these (' + ','.join(FROM_PAGE + ['config']) + ')')
    ap.add_argument('--measure', action='store_true', help='print the Δ between the markers of the view as a table (the bound kept or not: ok; '
                    'cycles: in the page, view_edit measures live)')
    ap.add_argument('--csv', action='store_true', help='with --measure: CSV (' + ','.join(MEASURE_CSV) + ')')
    a = ap.parse_args()
    if a.csv and not a.measure:
        ap.error('--csv goes with --measure')
    if a.config:
        res, key, changed = edit_config(a.config, read_ops(a.ops or '[]'), a.view, a.from_page, a.keys.split(',') if a.keys else None)
        print(json.dumps(res, ensure_ascii=False))
        bad = any('error' in r for r in res)
        print(f'viewedit: {a.config}: ' + (f'{key}: ' if key else '') + ('nothing written: a command failed' if bad else ', '.join(changed) or 'nothing changed'),
              file=sys.stderr)
        return 1 if any('error' in r for r in res) else 0
    if a.commands:
        for k, v in COMMANDS.items():
            print(f'{k:10} {v}' + (f'   (in a page only: {LIVE_ONLY[k]})' if k in LIVE_ONLY else ''))
        return 0
    if not a.file:
        ap.error('a page or a .view.json')
    if a.measure:
        if a.file.endswith('.json'):
            with open(a.file, encoding='utf-8') as f:
                st, timed, md = json.load(f), True, Model(None)
        else:   # a page: its own measures (a cocotb test's wl.measure) when the state has no markers
            p = Page(a.file)
            k = p.view(a.view)
            md = p.model(k)
            st, timed = p.state(k), md.timed
        sys.stdout.write(measure_text(measure_list(Editor(md, st if isinstance(st, dict) else {}).marks()), timed, a.csv))
        return 0
    if a.file.endswith('.json'):
        if a.views or a.get and not a.ops:
            with open(a.file, encoding='utf-8') as f:
                print(f.read())
            return 0
        model = None
        if a.model:
            mp = Page(a.model)
            model = mp.model(mp.view(a.view))
        res = edit_state(a.file, read_ops(a.ops or '[]'), model)
        print(json.dumps(res, ensure_ascii=False))
        return 1 if any('error' in r for r in res) else 0
    p = Page(a.file)
    if a.views:
        for k, d in p.waves.items():
            m = Model(d)
            print(f'{k:16} {len(m.sigs()):5} signals  {flat_text((d.get("head") or {}).get("text")) or "—"}' +
                  (f'  edits {p.rev(k)}' if p.rev(k) else ''))
        return 0
    if a.ops:
        res, key, rev = edit_page(a.file, read_ops(a.ops), a.view)
        print(json.dumps(res, ensure_ascii=False))
        print(f'viewedit: {key}: ' + (f'revision {rev}' if rev else 'nothing changed'), file=sys.stderr)
        return 1 if any('error' in r for r in res) else 0
    if a.get:
        print(json.dumps({p.view(a.view): p.edits['views'].get(p.view(a.view))} if a.view else p.edits['views'], ensure_ascii=False, indent=1))
        return 0
    ap.error('--ops, --get or --views')


if __name__ == '__main__':
    sys.exit(run_main(main, 'viewedit'))
