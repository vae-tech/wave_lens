#!/usr/bin/env python3
"""viewedit.py — the viewer's commands (view.run of wavefw/src/edit.js) on a page's edits or a saved state, from the shell.

What a person does with the buttons of a viewer — bookmarks (numbered circles with a text), arrows between them, markers,
groups of their own, highlight, colours, the selection, hidden and folded rows, the radix, the cursor and the window — a
script or an agent does with the same commands by name. In the page they run live (view.run, or tools/wavemcp.py
view_live); here they change the file:

  a page (mkhtml.py, make html, wavemcp.py wave_page): it carries per viewer a state of what the edits touched
     (<script type="application/json" id="wavefw-edits">); the viewer applies a new revision once, when the page is
     opened or reloaded — over what was changed in that browser in the same parts (the rest stays)
  a saved state (.view.json, the viewer's Save): changed in place; Load… in the viewer takes it

  viewedit.py page.html --ops '[{"op": "bookmark", "t": "120ns", "signal": "PSEL", "text": "setup"}]'
  viewedit.py page.html --view transfers --ops @ops.json     # one view of a page of several (default: the only one)
  viewedit.py page.html --get                                # the edits as JSON (--view …: one view)
  viewedit.py page.html --views                              # the views: key, title, signals, edits
  viewedit.py saved.view.json --model page.html --ops '…'    # a state; names checked against the page's signals
  viewedit.py --commands                                     # the commands and their arguments

Each command is {"op": name, …arguments}; the list runs in order, a bad one is said (exit 1) and the rest still run.
Times: model units (ps of timed waves, else cycles) or a text with a unit ("2.5us"). Signals: a full path, a name,
the end of a path ("u_regs.PSEL") or a * pattern. The commands that need the waves' values or the screen (edge,
picture, fit) run only in a page (live). docs/USAGE.md § "Editing the views" has them all; the smoke test checks that a
page with these edits and the same commands run in it give the same state.
"""
import argparse, datetime, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import WaveError, run_main  # noqa: E402

STATE_VERSION = 3   # wavefw/src/view.js STATE_VERSION
UNIT_PS = {'fs': 1e-3, 'ps': 1, 'ns': 1e3, 'us': 1e6, 'µs': 1e6, 'ms': 1e9, 's': 1e12}
RADIX = ['auto', 'hex', 'dec', 'signed', 'bin', 'oct', 'ascii', 'float']   # model.js RADIX
SORTS = ['none', 'asc', 'desc']
STYLES = ['auto', 'wavedrom', 'questa', 'square']
AR_SHAPES = ['~', '-', '-~', '~-', '-|', '|-', '-|-']
AR_HEADS = ['>', '<>', '<', '']
AR_LINES = ['solid', 'dashed', 'dotted']
EDGE_KINDS = ['any', 'rise', 'fall', 'value', 'xz']
HL_N = 6
GAP_KEYS = {'on': 'gaps', 'idle': 'gapIdle', 'keep': 'gapKeep', 'signals': 'gapSignals', 'clock': 'gapClock', 'aux': 'gapAux', 'only': 'gapOnly',
            'count': 'gapCount'}
ALL_GAP_KEYS = ['gaps', 'gapIdle', 'gapKeep', 'gapSignals', 'gapClock', 'gapAux', 'gapOnly', 'gapCount', 'gapLine']   # view.js GAP_KEYS
# the commands: name -> arguments (? optional), as WaveFW.commands() gives them (the smoke test compares the two)
COMMANDS = {
    'cursor': 't', 'cursor2': 't', 'view': 'from? to? at? span?', 'fit': '', 'range': 'from? to? signal?',
    'bookmark': 'n? t? signal? text? color? lift? delete?', 'arrow': 'id? from? to? shape? head? line? color? label? delete?',
    'marker': 'id? t? label? color? delete?', 'group': 'name signals? add? remove? color? rename? delete? go?',
    'highlight': 'add? remove? set? clear?', 'paint': 'signals? color? clear?', 'select': 'signal? signals?', 'hide': 'signals', 'show': 'signals?',
    'fold': 'groups? all?', 'unfold': 'groups? all?', 'radix': 'signals radix', 'analog': 'signals rows', 'sort': 'dir ignore?', 'style': 'name',
    'layout': 'scroll? height? tools?', 'find': 'query case? word? regex? highlight? open?', 'gaps': 'on? idle? keep? signals? clock? aux? only? count? reset?',
    'edge': 'dir? kind? value? signal?', 'reset': '', 'state': '', 'set_state': 'state', 'rows': 'pattern? limit? offset?',
    'picture': 'format? from? to? rows?',
}
LIVE_ONLY = {'fit': 'the time of the waves', 'edge': 'the values of the signals', 'picture': 'the screen'}
# the arguments of each command that are times (wavemcp.py turns its ns into "…ns" for these)
TIME_ARGS = {'cursor': ('t',), 'cursor2': ('t',), 'view': ('from', 'to', 'at', 'span'), 'range': ('from', 'to'), 'bookmark': ('t',), 'marker': ('t',),
             'picture': ('from', 'to')}
def block_re(name):
    """A JSON block of the page (<script type="application/json" id="wavefw-…">), at a line's start: not the text of it in
    the comments of the inlined wavefw.js."""
    return re.compile(r'^<script type="application/json" id="wavefw-' + name + r'">(.*?)</script>\n?', re.S | re.M)


EDITS_RE, LIVE_RE = block_re('edits'), block_re('live')


def put_block(text, name, obj):
    """The page's text with its block `name` set to obj (None: removed); a new one goes before the settings and the
    framework, so it is there when the viewers are built."""
    rx = block_re(name)
    block = '' if obj is None else (f'<script type="application/json" id="wavefw-{name}">' +
                                    json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + '</script>\n')
    if rx.search(text):
        return rx.sub(lambda _: block, text, count=1)
    if obj is None:
        return text
    at = text.find('<script>window.WAVEFW_CONFIG')
    at = at if at >= 0 else text.rfind('</body>')
    if at < 0:
        fail('no place for it in the page (no </body>)')
    return text[:at] + block + text[at:]


def write_text(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def fail(msg):
    raise WaveError(msg)


def parse_t(v):
    """model.js parseT: "1.5us" -> 1.5e6 (ps); a plain number is in model units; else None."""
    if v is None or v == '':
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    m = re.fullmatch(r'\s*(-?[\d.]+(?:e-?\d+)?)\s*(fs|ps|ns|us|µs|ms|s)?\s*', str(v), re.I)
    if not m:
        return None
    try:
        x = float(m.group(1))
    except ValueError:
        return None
    return x * (UNIT_PS[m.group(2).lower()] if m.group(2) else 1)


def tidy(x):
    """Integral floats as ints (the JSON a browser writes)."""
    if isinstance(x, float) and x.is_integer() and abs(x) < 2 ** 53:
        return int(x)
    if isinstance(x, dict):
        return {k: tidy(v) for k, v in x.items()}
    if isinstance(x, list):
        return [tidy(v) for v in x]
    return x


def prefixes(v):
    """model.js prefixes: a list, or a text with commas -> [trimmed, non-empty]."""
    items = v if isinstance(v, list) else str('' if v is None else v).split(',')
    return [str(s).strip() for s in items if str(s).strip()]


def glob_re(p):
    return re.compile('^' + '.*'.join(re.escape(s) for s in p.split('*')) + '$')


def flat_text(t):
    if isinstance(t, list):
        return ''.join(flat_text(x) for x in t[2 if len(t) > 1 and isinstance(t[1], dict) else 1:])
    return '' if t is None else str(t)


# ---------------- the page's waves: rows and groups as the viewer's parse() makes them ----------------
class Model:
    """The rows of one WaveJSON (signals with their full path and width, groups with their id and path) and the
    settings the viewer starts from (highlight, fold, sort), for names, the base of a state and the order of folding."""

    def __init__(self, doc=None, settings=None):
        self.doc, self.rows, self.groups = doc or {}, [], []   # groups in id order
        self.timed = 'time' in self.doc
        cfg = dict(settings or {})
        cfg.update({k: v for k, v in (self.doc.get('config') or {}).items() if v is not None})
        self.cfg = cfg
        if doc:
            self._walk(doc.get('signal') or [], 0, [])

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
                sig = {'type': 'sig', 'name': name, 'full': full, 'anc': anc, 'width': width, 'kind': it.get('kind')}
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

    def pool(self, state, groups):
        """What a name may be: the signals, then (groups) the modules in id order and your groups (their path "@name")."""
        out = self.sigs()
        if groups:
            out = out + self.groups + [{'type': 'group', 'user': True, 'name': g['name'], 'full': '@' + g['name'], 'path': '@' + g['name']}
                                       for g in state.get('groups') or []]
        return out

    def pick(self, state, spec, groups=False, one=False):
        """view pickRows: a full path, a name, the end of a path, a * pattern -> rows; nothing found or ambiguous: an error."""
        items = prefixes(spec)
        if not items:
            fail(f'no {"signals or modules" if groups else "signals"} given')
        pool, out = self.pool(state, groups), []
        if not self.doc:   # a state without its page: names as they are (full paths)
            return [{'type': 'sig', 'name': s.rsplit('.', 1)[-1], 'full': s, 'anc': [], 'width': 2} for s in items]
        for s in items:
            if '*' in s:
                rx = glob_re(s)
                hit = [r for r in pool if rx.match(r['full'])]
            else:
                hit = [r for r in pool if r['full'] == s] or [r for r in pool if r['name'] == s] or [r for r in pool if r['full'].endswith('.' + s)]
                if not hit:   # the dump's path of a signal the page shows under a shorter one (wave_page: "tb.aclk" for "aclk")
                    at = [r for r in pool if s.endswith('.' + r['full'])]
                    hit = [r for r in at if len(r['full']) == max(len(x['full']) for x in at)]
            if not hit:
                low = s.lower().replace('*', '')
                near = [r['full'] for r in pool if low and low in r['name'].lower()][:5]
                fail(f'no {"signal or module" if groups else "signal"} "{s}"' + (f'; similar: {", ".join(near)}' if near else ''))
            fulls = list(dict.fromkeys(r['full'] for r in hit))
            if '*' not in s and len(fulls) > 1:   # one net at several levels: the one nearest the top, when it is one (as wavemcp.py)
                top = min(f.count('.') for f in fulls)
                near = [f for f in fulls if f.count('.') == top]
                if len(near) == 1:
                    hit, fulls = [r for r in hit if r['full'] == near[0]], near
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
                by = {s['full']: s for s in self.sigs()}
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
        out.append({'n': n, 't': t, 'signal': b.get('signal') or None, 'text': b.get('text') or '', 'color': b.get('color') or None,
                    'lift': bool(b.get('lift')) and bool(b.get('signal'))})
    return out


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
    return [{k: v for k, v in (('n', b['n']), ('t', b['t']), ('signal', b['signal']), ('text', b['text']), ('color', b['color']),
                                ('lift', b['lift'] or None)) if v is not None and v != ''} for b in bms]


def ar_list(ars):
    """view.arrowList()."""
    return [{k: v for k, v in (('from', a['from']), ('to', a['to']), ('shape', a['shape']), ('head', None if a['head'] == '>' else a['head']),
                                ('line', None if a['line'] == 'solid' else a['line']), ('color', a['color']), ('label', a['label']))
             if v is not None and (v != '' or k == 'head')} for a in ars]


def mark_list(ms):
    return [{k: v for k, v in (('t', m['t']), ('label', m['label']), ('color', m['color'])) if v is not None and v != ''} for m in ms]


def group_list(gs):
    return [{k: v for k, v in (('name', g['name']), ('signals', list(g['signals'])), ('color', g['color'])) if v is not None} for g in gs]


# ---------------- the commands on a state ----------------
class Editor:
    """The commands on a state (the keys the edits touched) of one viewer: each reads what it changes from the state,
    else from the page (its bookmarks, the highlight and fold settings), and writes it back in the form state() has."""

    def __init__(self, model, state=None):
        self.m, self.st = model, dict(state or {})

    # what the state has, else the page's
    def bms(self):
        return bm_norm(self.st['bookmarks']) if 'bookmarks' in self.st else self.m.base_bookmarks()

    def ars(self):
        return ar_norm(self.st['arrows']) if 'arrows' in self.st else self.m.base_arrows()

    def marks(self):
        return [{'t': parse_t(x.get('t')), 'label': str(x.get('label') or ''), 'color': x.get('color') or None} for x in self.st.get('markers') or []]

    def groups(self):
        return [{'name': g['name'], 'signals': list(g.get('signals') or []), 'color': g.get('color') or None} for g in self.st.get('groups') or []]

    def config(self):
        return self.st.setdefault('config', {})

    def highlight(self):
        c = self.st.get('config') or {}
        return list(c['highlight']) if 'highlight' in c else self.m.base_highlight()

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
        self.st['from'], self.st['to'] = p, q
        return {'from': p, 'to': q}

    def c_range(self, a):
        if a.get('from') is None and a.get('to') is None:
            self.st['range'] = None
            return {'range': None}
        p, q = self.time(a.get('from'), 'from'), self.time(a.get('to'), 'to')
        sig = self.m.pick(self.st, a['signal'], one=True)[0]['full'] if a.get('signal') else None
        self.st['range'] = None if p == q else {'from': min(p, q), 'to': max(p, q), 'signal': sig}
        return {'range': None if p == q else [min(p, q), max(p, q)]}

    def c_bookmark(self, a):
        n = a.get('n')
        if n is not None and not (n == 'all' and a.get('delete')) and not (isinstance(n, int) and not isinstance(n, bool) and n > 0 or
                                                                           isinstance(n, str) and n.isdigit() and int(n) > 0):
            fail('n: a bookmark number (1, 2 …)')
        bms = self.bms()
        nums = ', '.join(str(b['n']) for b in bms) or 'none'
        if a.get('delete'):
            if n == 'all':
                self.put_marks([], [])
                return {'deleted': 'all'}
            b = next((b for b in bms if b['n'] == int(n or 0)), None)
            if not b:
                fail(f'no bookmark {n} (there are: {nums})')
            self.put_marks([x for x in bms if x is not b], [x for x in self.ars() if b['n'] not in (x['from'], x['to'])])
            return {'n': b['n'], 'deleted': True}
        t = self.time(a['t']) if a.get('t') is not None else None
        sig = self.m.pick(self.st, a['signal'], one=True)[0]['full'] if a.get('signal') else None
        b = next((b for b in bms if n is not None and b['n'] == int(n)), None)
        if not b:
            if t is None and self.st.get('cursor') is None:
                fail('bookmark: t (the cursor here is not known)')
            b = {'n': int(n) if n is not None else max([0] + [x['n'] for x in bms]) + 1, 't': self.st.get('cursor'), 'signal': None, 'text': '',
                 'color': None, 'lift': False}
            bms.append(b)
        if t is not None:
            b['t'] = t
        if 'signal' in a:
            b['signal'] = sig
        if 'text' in a:
            b['text'] = '' if a['text'] is None else str(a['text'])
        if 'color' in a:
            b['color'] = a['color'] or None
        if 'lift' in a:
            b['lift'] = bool(a['lift'])
        b['lift'] = bool(b['lift']) and bool(b['signal'])
        self.put_marks(bms)
        return {'n': b['n']}

    @staticmethod
    def id_ok(x, what):
        """The id of an arrow or a marker: its number as listed, not a name."""
        if x is not None and x != 'all' and not (isinstance(x, int) and not isinstance(x, bool) and x > 0 or isinstance(x, str) and x.isdigit() and int(x) > 0):
            fail(f'id: the number of the {what} as listed (1, 2 …), not {json.dumps(x, ensure_ascii=False)}; a new one: no id')

    def c_arrow(self, a):
        if a.get('id') == 'all':
            fail('arrow: one at a time (bookmark n "all" deletes every arrow)')
        self.id_ok(a.get('id'), 'arrow')
        bms, ars = self.bms(), self.ars()
        has = lambda n: any(b['n'] == n for b in bms)
        nums = ', '.join(str(b['n']) for b in bms) or 'none'
        def num(k):
            try:
                return int(float(a[k]))
            except (TypeError, ValueError):
                fail(f'{k}: a bookmark number, not {json.dumps(a[k])}')
        if a.get('id') is not None:
            i = int(a['id']) - 1
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
            x['color'] = a['color'] or None
        if 'label' in a:
            x['label'] = '' if a['label'] is None else str(a['label'])
        self.put_marks(None, ars)
        return {'id': i + 1}

    def c_marker(self, a):
        self.id_ok(a.get('id'), 'marker')
        ms, mid = self.marks(), a.get('id')
        if mid is not None and mid != 'all' and not (str(mid).isdigit() and 0 < int(mid) <= len(ms)):
            fail(f'no marker {mid} (there are {len(ms)})')
        if a.get('delete'):
            if mid is None:
                fail('marker: delete takes id or "all"')
            ms = [] if mid == 'all' else ms[:int(mid) - 1] + ms[int(mid):]
            self.st['markers'] = mark_list(ms)
            return {'id': mid, 'deleted': True}
        t = self.time(a['t']) if a.get('t') is not None else None
        m = ms[int(mid) - 1] if mid is not None else None
        if not m:
            if t is None and self.st.get('cursor') is None:
                fail('marker: t (the cursor here is not known)')
            m = {'t': self.st.get('cursor'), 'label': '', 'color': None}
            ms.append(m)
        if t is not None:
            m['t'] = t
        if 'label' in a:
            m['label'] = '' if a['label'] is None else str(a['label'])
        if 'color' in a:
            m['color'] = a['color'] or None
        self.st['markers'] = mark_list(ms)
        return {'id': ms.index(m) + 1}

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
        if not g:
            g = {'name': name, 'signals': [], 'color': None}
            gs.append(g)
        if new is not None:
            g['signals'] = new
        for f in add:
            if f not in g['signals']:
                g['signals'].append(f)
        if rm:
            g['signals'] = [f for f in g['signals'] if f not in rm]
        if 'color' in a:
            g['color'] = a['color'] or None
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
        return {'name': g['name'], 'signals': len(g['signals'])}

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
                p[r['full']] = str(a['color'])
            else:
                p.pop(r['full'], None)
        if a.get('clear'):   # every colour off, the browser's own too
            self.st['paint'] = p
        self.put_map('paint', p)
        return {'painted': len(rows)}

    def c_select(self, a):
        if a.get('signals') is not None:
            self.st['select'] = self.m.pick(self.st, a['signals'])[-1]['full']
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
        if sel in hidden or paths & hidden or paths & folded:
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
        self.config()['style'] = a.get('name')
        return {'style': a.get('name')}

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
        return {}

    def c_find(self, a):
        c = self.config()
        for k, key in (('case', 'findCase'), ('word', 'findWord'), ('regex', 'findRegex'), ('highlight', 'findHighlight'), ('open', 'findOpen')):
            if a.get(k) is not None:
                c[key] = bool(a[k])
        self.st['find'] = str(a.get('query') if a.get('query') is not None else '')
        return {'find': self.st['find']}

    def c_gaps(self, a):
        c = self.config()
        if a.get('reset'):
            for k in ALL_GAP_KEYS:
                c[k] = None
        for k, g in GAP_KEYS.items():
            if k in a:
                c[g] = a[k]
        return {'gaps': {k: c[k] for k in ALL_GAP_KEYS if k in c}}

    def c_reset(self, a):
        self.config()['highlight'] = []
        self.st.update({'select': None, 'find': '', 'range': None, 'cursor2': None})
        return {}

    def c_state(self, a):
        return {'state': self.st}

    def c_set_state(self, a):
        s = a.get('state')
        if not isinstance(s, dict) or s.get('wavefw') != 'state':
            fail('set_state: not a saved viewer state ({"wavefw": "state", …})')
        self.st = {k: v for k, v in s.items() if k not in ('wavefw', 'version', 'title')}
        sigs = {r['full'] for r in self.m.sigs()} | {g['path'] for g in self.m.groups}
        return {'missing': sorted({p for p in list((s.get('paint') or {}).keys()) + list(s.get('hidden') or []) if self.m.doc and p not in sigs})}

    def c_rows(self, a):
        pat = str(a.get('pattern') or '')
        rx = glob_re(pat) if '*' in pat else None
        rows = [['@' + g['name'], 'group'] for g in self.st.get('groups') or []] + \
            [[r['full'], 'module' if r['type'] == 'group' else r['width']] for r in self.m.rows if r['type'] != 'space']
        rows = [r for r in rows if not pat or (rx.match(r[0]) if rx else pat.lower() in r[0].lower())]
        off, n = max(0, int(a.get('offset') or 0)), max(1, int(a.get('limit') or 200))
        out = {'total': len(rows), 'rows': rows[off:off + n]}
        if off + n < len(rows):
            out['next_offset'] = off + n
        return out


# ---------------- pages and state files ----------------
class Page:
    """A page made by mkhtml.py: its views (window.WAVES), its settings (window.WAVEFW_CONFIG) and its edits."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, encoding='utf-8') as f:
                self.text = f.read()
        except OSError as e:
            fail(f'cannot read {path}: {e.strerror}')
        m = re.search(r'<script>\s*window\.WAVES = (.*?);\s*</script>', self.text, re.S)
        if not m:
            fail(f'{path}: not a page of mkhtml.py (no window.WAVES): make it with make html, mkhtml.py or wavemcp.py wave_page')
        try:
            self.waves = json.loads(m.group(1))
        except ValueError as e:
            fail(f'{path}: its waves are not JSON ({e})')
        s = re.search(r'<script>window\.WAVEFW_CONFIG = (.*?);</script>', self.text, re.S)
        self.settings = json.loads(s.group(1)) if s else {}
        e = EDITS_RE.search(self.text)
        try:
            self.edits = json.loads(e.group(1)) if e else {}
        except ValueError:
            fail(f'{path}: its edits are not JSON (the wavefw-edits script)')
        self.edits.setdefault('views', {})

    def view(self, key=None):
        """The key of a view: the one named, else the only one (an interactive one first)."""
        keys = list(self.waves)
        if key is None or key == '':
            if len(keys) == 1:
                return keys[0]
            fail(f'{os.path.basename(self.path)} has {len(keys)} views: give one ({", ".join(keys)})')
        if key not in self.waves:
            fail(f'no view "{key}" in {os.path.basename(self.path)} ({", ".join(keys)})')
        return key

    def model(self, key):
        return Model(self.waves[key], self.settings)

    def state(self, key):
        return dict((self.edits['views'].get(key) or {}).get('state') or {})

    def rev(self, key):
        return (self.edits['views'].get(key) or {}).get('rev')

    def put(self, key, state):
        """The view's edits replaced, a new revision (the viewer applies it once): -> the revision."""
        old = str(self.rev(key) or '')
        n = int(old.split('@')[0].lstrip('r')) + 1 if re.match(r'r\d+@', old) else 1
        rev = f'r{n}@{datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")}'
        self.edits['views'][key] = {'rev': rev, 'state': tidy(state)}
        return rev

    def save(self):
        self.text = put_block(self.text, 'edits', self.edits)
        write_text(self.path, self.text)


def edit_page(path, ops, view=None):
    """The commands on a page's edits of one view -> (results, view key, revision or None when nothing changed)."""
    p = Page(path)
    key = p.view(view)
    ed = Editor(p.model(key), p.state(key))
    before = json.dumps(ed.st, sort_keys=True)
    res = ed.run(ops)
    rev = None
    if json.dumps(ed.st, sort_keys=True) != before:
        rev = p.put(key, ed.st)
        p.save()
    return res, key, rev


def edit_state(path, ops, model=None):
    """The commands on a saved state (.view.json) -> results; the file written when it changed."""
    try:
        with open(path, encoding='utf-8') as f:
            st = json.load(f)
    except OSError as e:
        fail(f'cannot read {path}: {e.strerror}')
    except ValueError as e:
        fail(f'{path}: not JSON ({e})')
    if not isinstance(st, dict) or st.get('wavefw') != 'state':
        fail(f'{path}: not a saved viewer state (the viewer\'s Save writes one)')
    head = {k: st[k] for k in ('wavefw', 'version', 'title') if k in st}
    ed = Editor(model or Model(), {k: v for k, v in st.items() if k not in head})
    res = ed.run(ops)
    out = dict(head, **tidy(ed.st))
    out['version'] = max(STATE_VERSION, st.get('version') or 0)
    if out != st:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
    return res


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('file', nargs='?', help='a page (.html) or a saved state (.view.json)')
    ap.add_argument('--ops', help='the commands: JSON (one {"op": …} or a list), @file.json, or - for stdin')
    ap.add_argument('--view', help='the view of a page of several (its key: WAVES.<key>)')
    ap.add_argument('--model', help='with a .view.json: the page whose signals the names are checked against')
    ap.add_argument('--get', action='store_true', help='print the edits (a page: of every view, or --view) as JSON')
    ap.add_argument('--views', action='store_true', help='print the views of a page: key, title, signals, revision of its edits')
    ap.add_argument('--commands', action='store_true', help='print the commands and their arguments')
    a = ap.parse_args()
    if a.commands:
        for k, v in COMMANDS.items():
            print(f'{k:10} {v}' + (f'   (in a page only: {LIVE_ONLY[k]})' if k in LIVE_ONLY else ''))
        return 0
    if not a.file:
        ap.error('a page or a .view.json')
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
