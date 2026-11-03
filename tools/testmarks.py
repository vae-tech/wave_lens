"""testmarks.py — the marks a cocotb test left (python/wavelens_cocotb.py) -> bookmarks, spans, markers and an enum of a config.

merge(cfg, doc, split) adds them to every view of a config before the build (mkhtml.py --marks, or its top-level "marks"; a view's
"marks": false keeps it out); split "tests" or "both" (--marks-views) makes a view of each test, one shown at a time. The test's signal is what ties the two: its enum names the tests on the waves, and the jump
buttons are its changes in the dump, so a page whose marks and dump are of different runs shows it at once.
"""
import copy, json

from common import WaveError, parse_time

RESULTS = {'pass': ('PASS', '#2f9e44'), 'fail': ('FAIL', '#e03131'), 'xfail': ('FAIL (expected)', '#e8590c'), 'run': ('NOT FINISHED', '#e03131')}
TAIL = 0.12   # of the run, or of a test in its own view: the window past its end, where the last bookmark's text goes
SPLITS = ('whole', 'tests', 'both')
LOG_COLOR = {'WARNING': '#e8590c'}
MARK_COLOR = '#1971c2'


def fmt_ps(ps):
    """A length in ps in its unit: "1.2 us", "40 ns"."""
    for u, k in (('s', 1e12), ('ms', 1e9), ('us', 1e6), ('ns', 1e3)):
        if abs(ps) >= k:
            return f'{ps / k:.4g} {u}'
    return f'{ps:g} ps'


def load(path):
    """The marks file, checked."""
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except OSError as e:
        raise WaveError(f'{path}: {e.strerror}') from None
    except ValueError as e:
        raise WaveError(f'{path}: not JSON: {e}') from None
    if not isinstance(doc, dict) or doc.get('wavelens') != 'marks':
        raise WaveError(f'{path}: not a marks file ({{"wavelens": "marks", …}}, python/wavelens_cocotb.py writes it)')
    if doc.get('version') != 1:
        raise WaveError(f'{path}: marks of version {doc.get("version")}, this build reads version 1')
    return doc


def summary(doc):
    """One line for the page: "5 tests: 3 passed, 1 failed, 1 failed as expected"."""
    tests = doc.get('tests') or []
    n = {k: sum(t['result'] == k for t in tests) for k in RESULTS}
    parts = [f'{n["pass"]} passed']
    if n['fail'] or not n['xfail']:
        parts.append(f'{n["fail"]} failed')
    if n['xfail']:
        parts.append(f'{n["xfail"]} failed as expected')
    if n['run']:
        parts.append(f'{n["run"]} not finished')
    ms = [m for t in tests for m in t.get('measures') or []]
    bad = sum(m.get('ok') is False for m in ms)
    more = f'; {len(ms)} measure{"s" * (len(ms) != 1)}' + (f', {bad} out of bounds' if bad else '') if ms else ''
    return f'{len(tests)} test{"s" * (len(tests) != 1)}: ' + ', '.join(parts) + more


def measures(t):
    """A test's measurements (wl.measure) -> (all, out of their bounds)."""
    ms = t.get('measures') or []
    return len(ms), sum(m.get('ok') is False for m in ms)


def steps(t):
    """A test's phases (wl.phase, wl.step) by their length, the longest first -> [{label, from, to, dt}] in ps."""
    out = [{'label': p['label'], 'from': p['from'], 'to': p['to'], 'dt': p['to'] - p['from']} for p in t.get('phases') or [] if p.get('to') is not None]
    return sorted(out, key=lambda p: -p['dt'])


def measures_of(doc):
    """Every test's measurements as the WaveJSON's "measures" (vcd2wavedrom --measures): in the colour of the test's result, on the line of
    their signal (none: the test's row)."""
    tc, out = doc.get('signal'), []
    for t in doc.get('tests') or []:
        color = RESULTS.get(t['result'], RESULTS['run'])[1]
        for m in t.get('measures') or []:
            x = {'label': m['label'], 'from': m['from'], 'to': m.get('to'), 'color': color, **{k: m[k] for k in ('min', 'max') if m.get(k) is not None}}
            if m.get('signal') or tc:
                x['signal'] = m.get('signal') or tc
            out.append(x)
    return out


def checks_of(t):
    """A test's checks -> (all, failed): what it counted; a file of before these counts: what left a bookmark."""
    if 'passed' in t:
        return t['passed'] + t['failed'], t['failed']
    marks = [m for m in t.get('marks') or [] if m.get('kind') == 'check']
    return len(marks), sum(not m['ok'] for m in marks)


def rows_of(view, cfg):
    """The names the rows of a view answer to -> {path or name: the row's name}."""
    sig = view.get('signals') or cfg.get('signals')
    out = {}
    for chunk in sig if isinstance(sig, list) else [sig or '']:
        if isinstance(chunk, dict):
            out.update({p: (st or {}).get('alias') or p for p, st in chunk.items()})
            continue
        for s in filter(None, (x.strip() for x in chunk.split(','))):
            path, _, alias = s.partition('=')
            out[path] = alias or path
    return out


def path_for(rows, sig):
    """The path a name the test gave stands for: itself, or the one that ends with it, the nearest the top (a test names a signal from its
    top, the rows of a whole dump's config from the dump's; the top's port and the same one further down are two rows); none: sig."""
    if sig is None or sig in rows or not rows:
        return sig
    ends = sorted((p.count('.'), p) for p in rows if p.endswith('.' + sig) and '$' not in p)   # ($rootio: Verilator's copy of the top's ports)
    return ends[0][1] if ends and (len(ends) == 1 or ends[0][0] < ends[1][0]) else sig


def row_for(rows, sig):
    """The row of that name, as a bookmark calls it: an alias, or the path."""
    return rows.get(path_for(rows, sig), sig)


def window(view):
    """The view's window in ps; an end that is an event or none: open."""
    def ps(k):
        v = view.get(k)
        return None if v is None or isinstance(v, dict) else parse_time(v)
    return ps('from'), ps('to')


def bookmark(m, tc):
    """One mark of a test -> a bookmark, without its number."""
    kind = m.get('kind')
    if kind == 'check':
        ok = m['ok']
        head = f'{m["text"]}: ' if m.get('text') else ''
        return {'t': m['t'], 'signal': m.get('signal') or tc, 'color': RESULTS['pass' if ok else 'fail'][1],
                'label': f'✓ {m["got"]}' if ok else f'✗ {m["got"]} ≠ {m["expected"]}',
                'text': f'{head}{m.get("got_all", m["got"])}' + (' as expected' if ok else f', expected {m.get("expected_all", m["expected"])}{m.get("at", "")}')}
    if kind == 'log':
        return {'t': m['t'], 'signal': tc, 'color': LOG_COLOR.get(m.get('level'), RESULTS['fail'][1]), 'label': m.get('level', 'log').lower(),
                'text': f'{m.get("level", "LOG")}: {m.get("text", "")}'}
    b = {'t': m['t'], 'text': m.get('text', ''), 'color': m.get('color') or MARK_COLOR}
    if m.get('signal') or tc:
        b['signal'] = m.get('signal') or tc
    if m.get('label'):
        b['label'] = m['label']
    return b


def marks_of(doc):
    """Every test's bookmarks and spans, whichever view takes them -> (bookmarks, spans, markers, enum table)."""
    tc = doc.get('signal')
    bms, spans, markers, enum = [], [], [], {}
    for t in doc.get('tests') or []:
        word, color = RESULTS.get(t['result'], RESULTS['run'])
        name, end = f'TC{t["n"]}', t['to'] if t['to'] is not None else t['from']
        enum[str(t['n'])] = t['name']
        spans.append({'from': t['from'], 'to': end, 'label': f'{name} {t["name"]} · {word}', 'color': color})
        for p in t['phases']:
            if 'step' not in p:   # on its value of the step signal the row says it (none: it began where no signal can be written, ReadOnly)
                row = doc.get('step') or tc
                spans.append({'from': p['from'], 'to': p['to'], 'label': p['label'], 'signals': p.get('signals') or ([row] if row else []), 'color': 'c7'})
        start = {'t': t['from'], 'label': name, 'color': MARK_COLOR, 'lift': 'below', 'text': f'{name} {t["name"]} starts' + (f': {" ".join(t.get("text", t["doc"]).split())}' if t['doc'] else '')}
        bms.append({**start, 'signal': tc} if tc else start)
        bms += [bookmark(m, tc) for m in t['marks']]
        said = t['message'] + (f' ({t["where"]})' if t['where'] else '')
        more = f'; {t["dropped"]} marks past the limit left out' if t.get('dropped') else ''
        last = {'t': end, 'label': word, 'color': color, 'lift': 'above', 'text': f'{name} {t["name"]}: {word}' + (f': {said}' if said else '') + more}
        row = doc.get('step') or tc   # over the next row: the next test's start is at the same place, on the test's row
        bms.append({**last, 'signal': row} if row else last)
        if tc:
            markers.append({'on': {'signal': tc, 'value': str(t['n'])}, 'label': name})
    return bms, spans, markers, enum


def mark_view(view, cfg, doc, jumps=True):
    """A view with the marks of doc's tests: what is in its window, after its own bookmarks."""
    bms, spans, markers, _ = marks_of(doc)
    tc = doc.get('signal')
    t0, t1 = window(view)
    rows = rows_of(view, cfg)
    inside = lambda t: (t0 is None or t >= t0) and (t1 is None or t <= t1)
    fresh = [b for b in bms if inside(b['t'])]
    n = max([b.get('n', 0) for b in view.get('bookmarks') or []] + [len(view.get('bookmarks') or [])])
    view['bookmarks'] = (view.get('bookmarks') or []) + [
        {**b, 'n': n + i + 1, **({'signal': row_for(rows, b['signal'])} if 'signal' in b else {})} for i, b in enumerate(fresh)]
    view['spans'] = (view.get('spans') or []) + [
        {**s, **({'signals': [row_for(rows, x) for x in s['signals']]} if s.get('signals') else {})} for s in spans
        if (t0 is None or s['to'] >= t0) and (t1 is None or s['from'] <= t1)]
    ms = [{**m, **({'signal': row_for(rows, m['signal'])} if m.get('signal') else {})} for m in measures_of(doc) if inside(m['from'])]
    if ms:
        view['measures'] = (view.get('measures') or []) + ms
    if tc and jumps:
        old = view.get('marker') or []
        view['marker'] = (old if isinstance(old, list) else [old]) + [{**m, 'on': {**m['on'], 'signal': path_for(rows, tc)}} for m in markers]   # (an event is of the dump: a path)


def test_views(cfg, doc, template):
    """A view of each test, made from the view `template`: only that test's window and marks; what the template marks by hand is of the
    whole run and stays there -> {key: view}, the buttons of the page [{key, label, word, color}]."""
    tmpl = {k: v for k, v in template.items() if k not in ('bookmarks', 'arrows', 'spans', 'marker', 'from', 'to', 'note')}
    out, nav = {}, []
    for t in doc.get('tests') or []:
        key = f'tc{t["n"]}'
        while key in (cfg.get('views') or {}):
            key += '_'
        word, color = RESULTS.get(t['result'], RESULTS['run'])
        view = {**copy.deepcopy(tmpl), 'from': f'{t["from"]}ps', 'title': f'TC{t["n"]} {t["name"]} · {word}'}
        if t.get('signals'):   # the test's own rows, after the ones every test shares
            view['also'] = (view.get('also') or []) + t['signals']
        if t['to'] is not None:   # (not finished: to the end of the dump)
            view['to'] = f'{int(t["to"] + max((t["to"] - t["from"]) * TAIL, 1))}ps'
        mark_view(view, cfg, {**doc, 'tests': [t]}, jumps=False)
        rows = rows_of(view, cfg)   # every measure of the run in each test's view: the markers of yours they share (sharedMarkers) are one list
        ms = [{**m, **({'signal': row_for(rows, m['signal'])} if m.get('signal') else {})} for m in measures_of(doc)]
        if ms:
            view['measures'] = ms
        said = t['message'] + (f' ({t["where"]})' if t['where'] else '')
        n, bad = checks_of(t)
        count = '' if not n else f'{n - bad} of {n} checks passed' if bad else f'{n} check{"s" * (n != 1)} passed'
        k, off = measures(t)
        meas = '' if not k else f'{k} measure{"s" * (k != 1)}' + (f', {off} out of bounds' if off else '')
        st = steps(t)
        took = '' if not st else f'{len(st)} step{"s" * (len(st) != 1)}, longest {st[0]["label"]} {fmt_ps(st[0]["dt"])}'
        note = ' · '.join(x for x in (t['doc'], said, count, meas, took) if x)
        if note:
            view['note'] = note
        out[key] = view
        nav.append({'key': key, 'label': f'TC{t["n"]} {t["name"]}', 'word': word, 'color': color})
    return out, nav


def merge(cfg, doc, split='whole'):
    """The marks into a config. `split`: whole: into every view that takes them (its own bookmarks keep their numbers); tests: the first
    such view gives way to a view per test; both: it stays beside them -> the page's buttons, one per view ([] with whole)."""
    views = cfg.get('views') or {}
    if not views:
        raise WaveError('testmarks: the marks go into the views of a config: it has none')
    if split not in SPLITS:
        raise WaveError(f'testmarks: "marksViews": {split!r} (have: {", ".join(SPLITS)})')
    taking = [k for k, v in views.items() if v.get('marks') is not False]
    apart, nav = {}, []
    if split != 'whole' and taking and doc.get('tests'):
        apart, nav = test_views(cfg, doc, views[taking[0]])
        if split == 'tests':
            del views[taking.pop(0)]
        else:
            nav.insert(0, {'key': taking[0], 'label': 'All tests', 'word': summary(doc).split(': ', 1)[1], 'color': None})
    last = max((t['to'] or t['from'] for t in doc.get('tests') or []), default=0)
    for key, view in views.items():
        if view.pop('marks', None) is False:
            continue
        mark_view(view, cfg, doc)
        if window(view)[1] is None and last and 'to' not in view:   # the dump ends where the last test failed: its bookmark and text stay in sight
            view['to'] = f'{int(last + max(last * TAIL, 1))}ps'
        note = summary(doc)
        view['note'] = f'{note}. {view["note"]}' if view.get('note') else note
    views.update(apart)
    tc = doc.get('signal')
    table = cfg.get('enum') if isinstance(cfg.get('enum'), dict) else {}
    rows = rows_of(cfg, cfg)
    enum = marks_of(doc)[3]
    for sig, names in ((tc, enum), (doc.get('step'), {'0': '·', **(doc.get('steps') or {})})):
        if sig and names:
            key = row_for(rows, sig)
            table = {**table, key: {**names, **table.get(key, {})}}
    if table:
        cfg['enum'] = table
    return nav
