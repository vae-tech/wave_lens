"""wavepage.py — the files viewedit.py edits: a page's text (its waves, settings and edits blocks) and a config's views.

A page made by mkhtml.py carries per viewer the state of its edits (<script type="application/json" id="wavelens-edits">)
and, while an agent's live link has it, the link's key (id="wavelens-live"); Page reads a page, gives a view's state and
writes a new revision of it. The cfg_* functions are the commands bookmark, arrow, span and view on a view of a config
file (mkhtml.py's), as written there (viewedit.py edit_config runs them, the rest of a view's look through its Editor).
The values as the page's JSON has them (whole, tidy, finite) are here too. Standard library only; the names are
viewedit.py's too (viewedit.Page is this Page with the rows of a view, model()).
"""
import datetime, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I drops the script dir from sys.path
from common import WaveError, parse_time  # noqa: E402

AR_SHAPES = ['~', '-', '-~', '~-', '-|', '|-', '-|-']
AR_HEADS = ['>', '<>', '<', '']
AR_LINES = ['solid', 'dashed', 'dotted']


def block_re(name):
    """A JSON block of the page (<script type="application/json" id="wavelens-…">), at a line's start: not the text of it in
    the comments of the inlined wavelens.js."""
    return re.compile(r'^<script type="application/json" id="wavelens-' + name + r'">(.*?)</script>\n?', re.S | re.M)


EDITS_RE, LIVE_RE = block_re('edits'), block_re('live')


def put_block(text, name, obj):
    """The page's text with its block `name` set to obj (None: removed); a new one goes before the settings and the
    framework, so it is there when the viewers are built."""
    rx = block_re(name)
    block = '' if obj is None else (f'<script type="application/json" id="wavelens-{name}">' +
                                    json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c') + '</script>\n')   # no < in it
    if rx.search(text):
        return rx.sub(lambda _: block, text, count=1)
    if obj is None:
        return text
    at = text.find('<script>window.WAVELENS_CONFIG')
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
    return parse_time(v)


def finite(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float('inf'), float('-inf'))


def whole(x):
    """A number as JavaScript's Number.isInteger takes it (1, 1.0, "1"; not true, 1.5, "x") -> the int, or None."""
    if isinstance(x, bool):
        return None
    if isinstance(x, str) and re.fullmatch(r'\d+', x):   # edit.js isNum: digits only
        return int(x)
    if isinstance(x, float) and finite(x) and x.is_integer():
        return int(x)
    return x if isinstance(x, int) else None


def tidy(x):
    """Integral floats as ints (the JSON a browser writes)."""
    if isinstance(x, float) and x.is_integer() and abs(x) < 2 ** 53:
        return int(x)
    if isinstance(x, dict):
        return {k: tidy(v) for k, v in x.items()}
    if isinstance(x, list):
        return [tidy(v) for v in x]
    return x


# ---------------- pages ----------------
OLD_PAGE_RE = re.compile(r'window\.WAVEFW_CONFIG|id="wavefw-edits"|\bWaveFW\.')


class Page:
    """A page made by mkhtml.py: its views (window.WAVES), its settings (window.WAVELENS_CONFIG) and its edits."""

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
        if OLD_PAGE_RE.search(self.text):   # the project's name before 0.18: its settings and edits are not read here
            fail(f'{path}: a page made before the rename to WaveLens (0.18): make it again with make html or mkhtml.py')
        try:
            self.waves = json.loads(m.group(1))
        except ValueError as e:
            fail(f'{path}: its waves are not JSON ({e})')
        s = re.search(r'<script>window\.WAVELENS_CONFIG = (.*?);</script>', self.text, re.S)
        self.settings = json.loads(s.group(1)) if s else {}
        e = EDITS_RE.search(self.text)
        try:
            self.edits = json.loads(e.group(1)) if e else {}
        except ValueError:
            fail(f'{path}: its edits are not JSON (the wavelens-edits script)')
        views = self.edits.get('views', {}) if isinstance(self.edits, dict) else None
        if not isinstance(views, dict) or not all(isinstance(x, dict) and isinstance(x.get('state', {}), dict) for x in views.values()):
            fail(f'{path}: its edits are not {{"views": {{view: {{"rev", "state"}}}}}}: make it again or remove the wavelens-edits block')
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


# ---------------- the commands on a config file (mkhtml.py's): a rebuild keeps them ----------------
CONFIG_OPS = {'bookmark': ('n', 't', 'at', 'signal', 'text', 'label', 'color', 'lift', 'top', 'link', 'delete'),
              'arrow': ('id', 'from', 'to', 'shape', 'head', 'line', 'color', 'label', 'delete'),
              'span': ('id', 'from', 'to', 'label', 'color', 'signals', 'delete')}


def config_time(x, what):
    """A time for a config: a text with a unit as it is ("825.654us", the converter reads it), a number in ps."""
    if isinstance(x, str) and parse_t(x) is not None:
        return x.strip()
    if isinstance(x, (int, float)) and not isinstance(x, bool) and finite(x):
        return int(x) if float(x).is_integer() else x
    fail(f'{what}: "{x}" is not a time (ps, or a text with a unit: "250ns")')


def cfg_view(view, a):
    """view on a config: its window, "from" and "to" (a time with a unit; a number: ps)."""
    bad = sorted(set(a) - {'from', 'to'})
    if bad or a.get('from') is None or a.get('to') is None:
        fail('view: from and to in a config (its window)' + (f', not {", ".join(bad)}' if bad else ''))
    p, q = (parse_t(a[k]) for k in ('from', 'to'))
    if p is None or q is None or not q > p:
        fail('view: from and to are times, to after from')
    for k, t in (('from', p), ('to', q)):
        view[k] = f'{t / 1000:g}ns'
    return {'from': view['from'], 'to': view['to']}


def cfg_bookmark(view, a):
    bms = view.setdefault('bookmarks', [])
    n = a.get('n')
    if n is not None and not (n == 'all' and a.get('delete')):
        n = whole(n)
        if n is None or n < 1:
            fail('n: a bookmark number (1, 2 …)')
    if a.get('delete'):
        if n == 'all':
            view['bookmarks'], view['arrows'] = [], []
            return {'deleted': 'all'}
        b = next((b for b in bms if isinstance(b, dict) and b.get('n') == n), None)
        if b is None:
            fail(f'no bookmark {n} (there are: {", ".join(str(x.get("n")) for x in bms if isinstance(x, dict)) or "none"})')
        bms.remove(b)
        view['arrows'] = [x for x in view.get('arrows') or [] if n not in (x.get('from'), x.get('to'))]
        return {'n': n, 'deleted': True}
    b = next((b for b in bms if isinstance(b, dict) and n is not None and b.get('n') == n), None)
    if b is None:
        if a.get('t') is None and a.get('at') is None:
            fail('bookmark: t or at (a new one in a config)')
        b = {'n': n if n is not None else max([0] + [x.get('n') or 0 for x in bms if isinstance(x, dict)]) + 1}
        bms.append(b)
    if 't' in a and 'at' in a:
        fail('bookmark: t or at, not both')
    if a.get('t') is not None:
        b['t'] = config_time(a['t'], 't')
        b.pop('at', None)   # its time given: no longer at the event
    if a.get('at') is not None:
        b['at'] = a['at']
        b.pop('t', None)
    if a.get('lift') is not None and a['lift'] not in (True, False, 'above', 'below'):
        fail(f'lift: true, "above", "below" or false, not {json.dumps(a["lift"])}')
    for k in ('signal', 'text', 'label', 'color', 'lift', 'top', 'link'):
        if k in a:
            if a[k] in (None, '', False):
                b.pop(k, None)
            else:
                b[k] = a[k]
    return {'n': b['n']}


def cfg_arrow(view, a):
    ars = view.setdefault('arrows', [])
    i = given = a.get('id')
    if i is not None:
        i = whole(i)
        if i is None or not 1 <= i <= len(ars):
            fail(f'no arrow {given} (there are {len(ars)})')
        i -= 1
    elif a.get('from') is not None and a.get('to') is not None:
        i = next((k for k, x in enumerate(ars) if x.get('from') == a['from'] and x.get('to') == a['to']), None)
    if a.get('delete'):
        if i is None:
            fail('arrow: delete takes id, or from and to')
        ars.pop(i)
        return {'id': i + 1, 'deleted': True}
    nums = {b.get('n') for b in view.get('bookmarks') or [] if isinstance(b, dict)}
    for k in ('from', 'to'):
        if a.get(k) is not None and a[k] not in nums:
            fail(f'{k}: no bookmark {a[k]} in the view (there are: {", ".join(map(str, sorted(x for x in nums if x is not None))) or "none"})')
    for k, table in (('shape', AR_SHAPES), ('head', AR_HEADS), ('line', AR_LINES)):
        if a.get(k) is not None and a[k] not in table:
            fail(f'{k}: one of ' + ' '.join(json.dumps(x) for x in table))
    if i is None:
        if a.get('from') is None or a.get('to') is None:
            fail('arrow: from and to (bookmark numbers)')
        ars.append({})
        i = len(ars) - 1
    x = ars[i]
    for k in ('from', 'to', 'shape', 'head', 'line', 'color', 'label'):
        if k in a:
            if a[k] is None or (a[k] == '' and k != 'head'):
                x.pop(k, None)
            else:
                x[k] = a[k]
    if x.get('from') == x.get('to'):
        fail('arrow: from and to are one bookmark')
    return {'id': i + 1}


def cfg_span(view, a):
    ss = view.setdefault('spans', [])
    sid = a.get('id')
    if sid not in (None, 'all'):
        sid = whole(sid)
        if sid is None or not 1 <= sid <= len(ss):
            fail(f'no span {a["id"]} (there are {len(ss)})')
    if a.get('delete'):
        if sid is None:
            fail('span: delete takes id or "all"')
        if sid == 'all':
            ss.clear()
        else:
            ss.pop(sid - 1)
        return {'id': sid, 'deleted': True}
    if sid == 'all':
        fail('span: id "all" is for delete')
    if sid is None:
        if a.get('from') is None or a.get('to') is None:
            fail('span: from and to')
        ss.append({})
        sid = len(ss)
    x = ss[sid - 1]
    for k in ('from', 'to'):   # a time, an event, {"bookmark": n}: as the converter takes them
        if a.get(k) is not None:
            x[k] = config_time(a[k], k) if isinstance(a[k], (int, float)) or (isinstance(a[k], str) and parse_t(a[k]) is not None) else a[k]
    for k in ('label', 'color', 'signals'):
        if k in a:
            if a[k] in (None, '', []):
                x.pop(k, None)
            else:
                x[k] = a[k]
    return {'id': sid}


def cfg_time(t):
    """A time of a page's state (ps) as a config writes it: "50ns", else "12500ps"."""
    t = whole(t) if whole(t) is not None else t
    return f'{t // 1000}ns' if isinstance(t, int) and t % 1000 == 0 else f'{t}ps'


def cfg_form(kind, page_list, orig):
    """--from-page: the page's bookmarks / arrows / spans in a config's form: an entry the config had and the page did not change stays as it
    was written ("at": an event, "t": "50ns", "link": "exact"); a new or changed one gets its times as "…ns" and its link as a view's name."""
    times = {'bookmarks': ('t',), 'spans': ('from', 'to'), 'arrows': ()}[kind]
    def norm(x):   # its fields but the times, the link as a name
        o = {k: v for k, v in x.items() if k not in times + ('at', 'n') and v is not None}
        if isinstance(o.get('link'), dict) and set(o['link']) == {'view'}:
            o['link'] = o['link']['view']
        return o
    def same_t(a, b):   # a time of the config (an event: the same as long as the rest is) and the page's
        return not isinstance(a, (int, float, str)) or (parse_t(a) is not None and parse_t(a) == parse_t(b))
    by = {}
    for i, o in enumerate(orig or []):
        if isinstance(o, dict):
            by.setdefault(o.get('n', i + 1) if kind == 'bookmarks' else i, o)
    out = []
    for i, x in enumerate(page_list or []):
        o = by.get(x.get('n', i + 1) if kind == 'bookmarks' else i)
        if o is not None and norm(o) == norm(x) and ('at' in o or all(same_t(o.get(k), x.get(k)) for k in times)):
            out.append(o)
            continue
        y = norm(x)
        if kind == 'bookmarks':
            y = {'n': x.get('n', i + 1), **y}
        out.append({**y, **{k: cfg_time(x[k]) for k in times if isinstance(x.get(k), (int, float))}})
    return out
