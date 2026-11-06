#!/usr/bin/env python3
"""mkhtml.py — build one self-contained HTML page (wavelens.css + wavelens.js + data inlined) that opens anywhere.

  mkhtml.py --config dump.config.json --out dump.html            # run every view of the config -> page
  mkhtml.py --config cfg.json --view exact --waves other.vcd ...  # some views only, another dump
  mkhtml.py cyc=cyc.json exact=exact.json --settings cfg.json --out page.html   # from WaveJSON files
  mkhtml.py --config x.config.json --sva checks.sv --bind a_req_ack@tb.dut --out x.html   # assertions bound (make html SVA= BIND=)
  mkhtml.py --config x.config.json --lint [--strict]       # the warnings of every view, no page (--strict: exit 1 on one)
  mkhtml.py --config x.config.json --lint --lint-json -    # the same as JSON: code, where, view, the signal and the rows it may mean
  mkhtml.py --config x.config.json --waves dump.vcd --marks run.marks.json --out x.html   # a cocotb test's marks on the waves
  mkhtml.py … --marks run.marks.json --marks-views tests                                  # each test apart: the page shows one at a time

Lint (printed at every build, "mkhtml: lint: <code>: <JSON path>: <text>"; docs/USAGE.md "Lint"): bookmark-bad, arrow-bad, bookmark-outside-view,
bookmark-signal-missing, bookmark-duplicate, bookmark-time, bookmark-key, bookmark-link-missing, arrow-end-missing, arrow-key, marker-no-match,
marker-key, bind-unknown, svashow-no-match, bookmarks-close (a heuristic), enum-colors-hex, span-outside-view,
span-signal-missing, span-key, span-every-no-match, compare-spans-cut, measure-no-clock, state-signal-missing, state-svg, expr-name-missing, exprs-no-engine, gap-view-off, setting-signal-missing, cycle-zero-window, measure-no-match, measure-empty, also-no-match, also-cut. A marker or a span "every" on a signal the dump has not got
is no warning: the build stops there, as for any name of the config (marker-no-match: the signal is there, the event never happens).

Config keys used here (the rest is vcd2wavedrom.py's, see its --help):
  "config"  global wavelens settings for the page: theme, colors, rowHeight, nameWidth, fontSize, sort, sortIgnore, …
  "page"    {"title": "...", "intro": "..."}
  "marks"   a marks file of a cocotb test (python/wavelens_cocotb.py; --marks): its tests as spans, bookmarks and jumps in every
            view; a view's "marks": false keeps it out (docs/USAGE.md "Marks from a cocotb test")
  "marksViews"  whole (default): all the tests on one waveform; tests: a view of each test and the page shows one at a time, with a
            button per test; both: those and the whole run (--marks-views)
  "marksColors"  the colours of the marks: {"pass", "fail", "xfail", "run", "note", "warning", "log"}: "#2f9e44", a token of the theme
            ("c3", "hl2": it follows dark and light), "--my-var" or a CSS colour name (another word: an error; the rest keep theirs)
  "marksPhases"  true: a labelled marker at the start of each phase of a test (of some time) too, to jump to with ]m [m (--marks-phases)
  views[k]  "render": "view" (interactive, default) | "svg" (static figure) | "both"; "note": text under the heading
  "sva"     ["checks.sv", …] (top level or in a view) SystemVerilog assertion files: parsed with the sva CLI (one
            compilation unit), inlined as window.SVA for the assertions panel; parse errors are shown in the page.
            false: no assertion engine in the page (also --no-sva). Without "sva" the page still has it ("Load file…").
  "bind"    [{"assert": "a_req_ack", "scope": "tb.dut"}] (top level: every view; or in a view) evaluated over the
            dump with sva eval, so the page opens with them bound (docs/USAGE.md "Assertions"); the page also gets a printable
            "Assertions" section: the bindings over the whole dump (totals, one row per assertion, the failures)
  "report"  {"bind": [{"assert": "*", "scope": "tb.dut"}]} (or the list alone; top level) bindings for that printable section
            only: evaluated over the whole dump with the top-level "sva", drawn in no view (a view's own "bind" is drawn and
            reported); false: no printable section. --report NAME@SCOPE (repeatable)
"""
import argparse, datetime, hashlib, html, json, os, re, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # -I drops the script dir from sys.path
import common, dumpscan, svabuild, testmarks, vcd2wavedrom, viewedit, wavejson  # noqa: E402
from common import WaveError, add_sva_bin_arg, check_config, run_main  # noqa: E402

FW = os.path.join(os.path.dirname(HERE), 'wavelens')   # the framework files inlined into the page

PAGE = '''<!doctype html>
<html lang="en"{theme}>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap">
<style>
{css}
/* ---------------- page ---------------- */
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; }}
body {{ background: var(--bg); color: var(--fg); font-family: var(--font-body); font-size: 15px; line-height: 1.5; padding: 0 clamp(16px, 3vw, 40px) 48px; }}
header {{ padding-block: 28px 16px; border-bottom: 1px solid var(--line); display: grid; gap: 10px; }}
header .row1 {{ display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; justify-content: space-between; }}
h1 {{ font-size: clamp(22px, 3.5vw, 32px); margin: 0; line-height: 1.2; }}
h2 {{ font-size: 19px; font-weight: 600; margin: 36px 0 6px; padding-top: 10px; border-top: 2px solid var(--accent); }}
p {{ max-width: 80ch; margin: 0 0 10px; }}
.muted {{ color: var(--muted); }}
.facts {{ display: flex; flex-wrap: wrap; gap: 6px 26px; font-size: 13.5px; }}
.facts b {{ display: block; font-weight: 600; }}
.sva-report table {{ border-collapse: collapse; font-size: 12.5px; margin: 6px 0 14px; }}
.sva-report th, .sva-report td {{ border: 1px solid var(--line); padding: 3px 8px; text-align: left; white-space: nowrap; }}
.sva-report th {{ background: var(--panel-2); font-weight: 600; }}
.sva-report td.n {{ text-align: right; font-family: var(--font-mono); }}
.sva-report tr.bad code {{ color: var(--sva-fail); font-weight: 600; }}
.sva-report h3 {{ font-size: 16px; margin: 14px 0 4px; }}
.sva-report .meta {{ font-size: 12.5px; color: var(--muted); }}
.sva-report .notes, .sva-report .more {{ font-size: 12.5px; color: var(--muted); }}
@media print {{
  h2, .note {{ break-after: avoid; }} button.theme, .wv .bar .tools, .wv .sva {{ display: none; }}   /* a tall viewer breaks over pages; its title and cursor stay */
  section[data-view][hidden] {{ display: block; }} .tests {{ display: none; }}
  .sva-report {{ break-before: page; }} .sva-report table {{ font-size: 9.5px; width: 100%; table-layout: auto; }}
  .sva-report th, .sva-report td {{ white-space: normal; padding: 2px 4px; overflow-wrap: anywhere; }}
}}
.bench {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; margin-block: 10px 18px; min-width: 0; }}
.tests {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 16px; }}
.tests button {{ font: inherit; font-size: 13px; text-align: left; border: 1px solid var(--line); border-left: 4px solid var(--tc, var(--line)); background: var(--panel); color: var(--fg);
  border-radius: 4px; padding: 4px 10px; cursor: pointer; }}
.tests button small {{ color: var(--tc, var(--muted)); font-weight: 600; margin-left: 6px; font-size: inherit; }}
.tests button:hover {{ border-color: var(--accent); }}
.tests button.on {{ background: var(--panel-2); font-weight: 600; box-shadow: inset 0 -2px 0 var(--tc, var(--accent)); }}
button.theme {{ font: inherit; font-size: 12.5px; border: 1px solid var(--line); background: var(--panel); color: var(--fg); border-radius: 4px; padding: 3px 10px; cursor: pointer; }}
button.theme:hover {{ border-color: var(--accent); color: var(--accent); }}
</style>
</head>
<body>
<header>
  <div class="row1"><h1>{title}</h1><button type="button" class="theme" id="theme">Theme: {theme_name}</button></div>
  {intro}
  <div class="facts">{facts}</div>
{nav}</header>
{sections}
<script>window.WAVELENS_CONFIG = {settings};</script>{build}
<script>
window.WAVES = {data};
</script>
<script>
{js}
</script>
{bus}{sva}{nav_js}<script>
(function () {{ // page theme button: auto -> light -> white -> dark
  const b = document.getElementById('theme'), modes = ['auto', 'light', 'white', 'dark'];
  let i = Math.max(0, modes.indexOf(document.documentElement.dataset.theme || 'auto'));
  b.addEventListener('click', () => {{ i = (i + 1) % modes.length; WaveLens.setTheme(modes[i]); b.textContent = 'Theme: ' + modes[i]; }});
}})();
</script>
</body>
</html>
'''


NAV_JS = '''<script>
(function () { // the tests' buttons: one view of the page at a time; #tc3 in the address opens that one
  const secs = [...document.querySelectorAll('section[data-view]')], btns = [...document.querySelectorAll('.tests button')];
  const show = k => { secs.forEach(s => { s.hidden = s.dataset.view !== k; }); btns.forEach(b => b.classList.toggle('on', b.dataset.view === k)); };
  btns.forEach(b => b.addEventListener('click', () => {
    show(b.dataset.view);
    try { history.replaceState(null, '', '#' + b.dataset.view); } catch (e) { /* a file: page that may not */ }
  }));
  const v = /[#&]view=([^&]*)/.exec(location.hash), k = decodeURIComponent(v ? v[1] : location.hash.slice(1));   // #tc3, or a link's &view=tc3
  show(secs.some(s => s.dataset.view === k) ? k : secs[0].dataset.view);
})();
</script>
'''


def nav_html(nav):
    """The buttons of a page with a view per test."""
    def one(e):
        style = f' style="--tc: {html.escape(css_color(e["color"]), quote=True)}"' if e.get('color') else ''
        return (f'<button type="button" data-view="{html.escape(e["key"], quote=True)}"{style}>{html.escape(e["label"])}'
                f'<small>{html.escape(e["word"])}</small></button>')
    return f'<nav class="tests">{"".join(one(e) for e in nav)}</nav>\n'


def script_json(text):
    """JSON text to put inside a <script>: no "<" in it (\\u003c is the same string to JSON and JavaScript), so a value with
    "</script>" or "<!--<script>" (a signal's text, an enum label, a title, an assertion's source) cannot end the script or
    make the HTML parser swallow the rest of the page."""
    return text.replace('<', '\\u003c')


def fmt_ps(ps):
    for f, u in ((1e12, 's'), (1e9, 'ms'), (1e6, 'µs'), (1e3, 'ns')):
        if abs(ps) >= f:
            return f'{ps / f:.4g} {u}'
    return f'{ps:g} ps'


def section(key, doc, render, note):
    title = (doc.get('head') or {}).get('text') or key
    ref = html.escape(f'WAVES[{json.dumps(key)}]' if not key.isidentifier() else f'WAVES.{key}', quote=True)   # boot.js resolveSrc reads both
    out = [f'<h2 id="{html.escape(key, quote=True)}">{html.escape(str(title))}</h2>']
    m = doc.get('meta') or {}
    sub = [f'{m["mode"]} mode' if 'mode' in m else '', f'{fmt_ps(m["to_ps"] - m["from_ps"])} window from {fmt_ps(m["from_ps"])}' if 'from_ps' in m else '',
           f'{wavejson.count(doc["signal"])} signals']
    out.append(f'<p class="muted">{html.escape(" · ".join(filter(None, sub)))}{(" — " + html.escape(note)) if note else ""}</p>')
    if render in ('view', 'both'):
        out.append(f'<div class="bench"><div data-wave="{ref}"></div></div>')
    if render in ('svg', 'both'):
        out.append(f'<div class="bench"><div data-wave="{ref}" data-mode="svg"></div></div>')
    return '\n'.join(out)


def generated(reproducible):
    """The "Generated" fact: now, SOURCE_DATE_EPOCH (reproducible builds, UTC) or None (--reproducible: left out)."""
    if reproducible:
        return None
    epoch = os.environ.get('SOURCE_DATE_EPOCH')
    if epoch:
        return datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M')


STATS_MAX = 64e6   # a dump read once more for its statistics up to this size (bytes)
_STATS = {}


def dump_stats(path):
    """A dump's statistics (dumpscan.stats) as the page's meta.stats: counts and the ten busiest; None for a large dump (a second pass)."""
    if path in _STATS:
        return _STATS[path]
    s = None
    try:
        if os.path.getsize(path) > STATS_MAX:   # said once: the page's log has no line of the dump's statistics
            print(f'mkhtml: {os.path.basename(path)}: {os.path.getsize(path) / 1e6:.0f} MB, over {STATS_MAX / 1e6:.0f} MB: no statistics of the dump '
                  '(dumpscan.py --stats gives them)', file=sys.stderr)
        else:
            d = dumpscan.read(path, 'count')
            if d is not None:
                x = dumpscan.stats(d, 10)
                s = {'signals': x['signals'], 'changing': x['changing'], 'dead': len(x['dead']), 'busiest': [[b['path'], b['changes']] for b in x['busiest']],
                     'never': x['dead'][:20]}
    except (OSError, WaveError):
        s = None
    _STATS[path] = s
    return s


def build_views(a, cfg, base):
    """Every view of the config converted (vcd2wavedrom.convert), or the WaveJSON files read -> (docs, renders,
    sva_views: the views with bindings, for the printable section)."""
    docs, renders, sva_views = {}, {}, []   # the views with bindings (for the printable section)
    if a.config:
        views = cfg.get('views') or {}
        keys = a.view or list(views) or [None]
        for key in keys:
            vcfg = vcd2wavedrom.view_config(cfg, key)
            own = (views.get(key) or {}) if key else {}
            vcfg['config'] = own.get('config') or {}   # the top-level "config" is the page's global setting
            argv = (['--waves', a.waves] if a.waves else []) + (['--sva-bin', a.sva_bin] if a.sva_bin else [])
            if vcfg.get('sva') is False:
                vcfg.pop('sva')
            o = vcd2wavedrom.resolve(vcd2wavedrom.parser().parse_args(argv), vcfg, base)
            o.sva_prefixes = vcfg['config'].get('sortIgnore', (cfg.get('config') or {}).get('sortIgnore'))   # the page's, for the names
            o.page_config = {**(cfg.get('config') or {}), **vcfg['config']}   # what lint reads of the settings
            o.no_engine = a.no_sva or cfg.get('sva') is False
            o.lint_at, o.prog, o.views_known = f'views.{key}' if key else None, 'mkhtml', list(views)   # (a bookmark's link: one of them)
            if a.no_sva:   # no engine in the page: nothing to evaluate either
                o.sva, o.bind = [], []
            name = key or 'wave'
            if o.sva and o.bind and vcfg.get('sva') is not False:
                sva_views.append((name, o))
            print(f'mkhtml: view {name}: {o.waves} ({"clock " + o.clock if o.clock else "exact"})', file=sys.stderr)
            docs[name] = vcd2wavedrom.convert(o)
            st = dump_stats(o.waves)   # what the dump has, for the page's log: its signals that change, never change, the busiest
            if st:
                docs[name].setdefault('meta', {})['stats'] = st
            a.lint_count = getattr(a, 'lint_count', 0) + len(o.lint)
            a.lint_items = getattr(a, 'lint_items', []) + [vcd2wavedrom.lint_item(w, name) for w in o.lint]
            renders[name] = (a.render or own.get('render') or cfg.get('render') or 'view', own.get('note'))
            st = own.get('state')   # the view's state as the page opens (viewedit.py --config): into the page's edits
            if st is not None:
                bad = [k for k in st if k not in viewedit.STATE_KEYS | {'config'}] if isinstance(st, dict) else None
                if bad is None or bad:
                    raise WaveError(f'mkhtml: views.{key}.state: a viewer\'s state {{"groups", "radix", "markers", …}}' + (f', not {", ".join(bad)}' if bad else ''))
                rd = renders[name][0]
                if rd == 'svg':   # the static figure draws its WaveJSON: a viewer's state is the viewer's (review S19-3)
                    raise WaveError(f'mkhtml: views.{key}.state: a view rendered as "svg" draws its WaveJSON only, no viewer\'s state: '
                                    '"render": "view" or "both", or no "state"')
                more = [f'state-svg: views.{key}.state: the viewer opens with it, the static figure beside it draws the WaveJSON as it is'] if rd == 'both' else []
                a.view_states = {**getattr(a, 'view_states', {}), name: st}
                for w in more + state_lint(st, docs[name], f'views.{key}.state'):   # a name of the state the view has not got: the page leaves it out
                    print(f'mkhtml: lint: {w}', file=sys.stderr)
                    a.lint_count += 1
                    a.lint_items.append(vcd2wavedrom.lint_item(w, name))
    for spec in a.files:
        key, _, path = spec.rpartition('=')
        key = key or os.path.splitext(os.path.basename(path))[0]
        docs[key] = vcd2wavedrom.load_config(path)
        renders[key] = (a.render or 'view', None)
    return docs, renders, sva_views


def css_color(c):
    """A colour as the page takes it (model.js tokVar) as CSS: a token of the theme ("c3", "hl2", "fg") its variable, "--x" var(--x)."""
    if c in testmarks.TOKENS:
        return f'var({testmarks.TOKENS[c]})'
    return f'var({c})' if c.startswith('--') else c


def state_lint(st, doc, at):
    """The names of a view's "state" that are no row of its WaveJSON (hidden, radix, analog, paint, groups, dups, the markers' and bookmarks'
    signals) -> lint lines "state-signal-missing": the page leaves them out (its toast and log say it too). A copy ("data#2"), a slice or a bit
    ("data[7:4]") by its bus; a row of an expression ("ƒ …") or a group ("@g") is not checked."""
    rows = vcd2wavedrom.row_walk(doc.get('signal') or [])
    have = {f for f, _ in rows} | {x for _, it in rows for x in (it.get('abs'), it.get('path')) if x}
    base = lambda n: re.sub(r'(#\d+)?(\[\d+(:\d+)?\])*$', '', str(n))
    names = [('hidden', n) for n in st.get('hidden') or []] + [(k, n) for k in ('radix', 'analog', 'paint') for n in (st.get(k) or {})]
    names += [(f'groups[{i}].signals', n) for i, g in enumerate(st.get('groups') or []) if isinstance(g, dict) for n in g.get('signals') or []]
    names += [('dups', n) for n in st.get('dups') or []]
    names += [(f'{k}[{i}].{f}', m[f]) for k in ('markers', 'bookmarks') for i, m in enumerate(st.get(k) or []) if isinstance(m, dict)
              for f in ('signal', 'dsignal') if m.get(f)]
    out = []
    for where, n in names:
        if not isinstance(n, str) or n.startswith(('ƒ ', '@')) or n in have or base(n) in have:
            continue
        out.append(f'state-signal-missing: {at}.{where}: "{n}" is no row of the view: the page leaves it out')
    return out


def collect_sva(a, cfg, docs):
    """The assertion files and notes of every view, once for the page (window.SVA); each view keeps its bindings ->
    (with_sva, files, notes)."""
    # assertions: the files and notes of every view once in window.SVA, each view keeps its bindings (WaveJSON "sva")
    with_sva = not a.no_sva and cfg.get('sva') is not False
    sva_files, sva_notes = [], []
    for d in docs.values():
        x = d.get('sva')
        if not x:
            continue
        for f in x.pop('files', []):
            if not any(g['path'] == f['path'] and g['source'] == f['source'] for g in sva_files):
                sva_files.append(f)
        sva_notes += [n for n in x.pop('notes', []) if n not in sva_notes]
        if not x.get('bind') and not x.get('exprs'):
            del d['sva']
    return with_sva, sva_files, sva_notes


def report_binds(a, cfg):
    """The top-level "report" ({"bind": [...]} or a list of bindings; --report): bindings for the printable section only,
    evaluated over the whole dump with the top-level "sva" files, in no view -> (None, options) or None."""
    rep = cfg.get('report')
    if not rep:
        return None
    binds = rep.get('bind') if isinstance(rep, dict) else rep
    if isinstance(rep, dict) and set(rep) - {'bind'}:
        raise WaveError(f'mkhtml: "report": unknown key(s) {", ".join(sorted(set(rep) - {"bind"}))} (have: bind)')
    binds = svabuild.bind_list(binds)
    sva = cfg.get('sva')
    if not sva or not isinstance(sva, (list, str)):
        raise WaveError('mkhtml: "report" needs the assertion files: a top-level "sva" (or --sva)')
    base = os.path.dirname(os.path.abspath(a.config or a.settings or '.'))
    waves = a.waves or (cfg.get('waves') and os.path.join(base, os.path.expanduser(cfg['waves'])))   # as a view's (vcd2wavedrom.resolve)
    if not waves:
        raise WaveError('mkhtml: "report" needs the dump: a top-level "waves" (or --waves)')
    pfx = (cfg.get('config') or {}).get('sortIgnore')
    o = argparse.Namespace(sva=[(os.path.join(base, os.path.expanduser(x)), x) for x in ([sva] if isinstance(sva, str) else sva)], bind=binds,
                           waves=waves, sva_prefixes=[pfx] if isinstance(pfx, str) else pfx)
    return None, o


def render_page(a, cfg, docs, renders, sva_views, with_sva, sva_files, sva_notes):
    """The page: the framework and the data inlined, the facts, the sections, the printable assertions section."""
    page, settings = cfg.get('page') or {}, cfg.get('config') or {}
    title = a.title or page.get('title') or ', '.join(sorted({(d.get('meta') or {}).get('waves', k) for k, d in docs.items()}))
    metas = [d.get('meta') or {} for d in docs.values()]
    facts = [('Dump', ', '.join(sorted({m['waves'] for m in metas if 'waves' in m})) or '—'),
             ('Wave tool', ', '.join(sorted({m['tool'] for m in metas if 'tool' in m})) or '—'),
             ('Views', str(len(docs))), ('Generated', generated(a.reproducible))]
    build = None if a.reproducible else common.build_info('mkhtml.py', generated(False))   # the bar's version line: this checkout's commit
    at = build and (build['branch'] + '@' if build.get('branch', 'HEAD') != 'HEAD' else '') + build['commit'] + ('*' if build.get('dirty') else '')
    facts.append(('WaveLens', common.version() + (f' · {at}' if at else '')))
    facts = [f for f in facts if f[1] is not None]
    if sva_files:
        n = sum(len((f.get('parsed') or {}).get('assertions', [])) for f in sva_files)
        facts.insert(3, ('Assertions', f'{n} in {", ".join(f["name"] for f in sva_files)}' if n else ', '.join(f['name'] for f in sva_files)))
    nav = [e for e in getattr(a, 'nav', None) or [] if e['key'] in docs]
    nav = nav if len(nav) > 1 else []   # (--view left one: nothing to choose)
    shown = {e['key'] for e in nav}
    wrap = lambda k, text: f'<section data-view="{html.escape(k, quote=True)}">\n{text}\n</section>' if k in shown else text
    theme = settings.get('theme')
    with open(os.path.join(FW, 'wavelens.css'), encoding='utf-8') as f:
        css = f.read()
    with open(os.path.join(FW, 'wavelens.js'), encoding='utf-8') as f:
        js = f.read()
    safe = script_json   # every "<" of the data as <: "</script>" and "<!--<script>" in a value do not end or swallow the page
    with open(os.path.join(FW, 'bus.js'), encoding='utf-8') as f:   # bus transactions: always (a few kB)
        bus = '<script>\n' + f.read().replace('</script', '<\\/script') + '\n</script>\n'
    sva = ''
    if with_sva:
        parts = []
        for name in ('sva.wasm.js', 'sva.js'):
            with open(os.path.join(FW, name), encoding='utf-8') as f:
                parts.append(f.read().replace('</script', '<\\/script'))
        data = {'files': sva_files, 'notes': sva_notes}
        sva = (f'<script>window.SVA = {safe(json.dumps(data, ensure_ascii=False))};</script>\n' +
               ''.join(f'<script>\n{p}\n</script>\n' for p in parts))
    elif sva_files or sva_notes:
        print('mkhtml: --no-sva: the "sva" files and bindings are left out', file=sys.stderr)
        for d in docs.values():
            d.pop('sva', None)
    report = ''
    extra = report_binds(a, cfg) if with_sva and cfg.get('report') is not False else None
    if cfg.get('report') is False:   # a page without the printable section
        sva_views = []
    if sva_views or extra:   # the printable section: every binding of every view, and of "report", over the whole dump, each once
        results, seen, dumps = [], set(), []
        for name, o in sva_views + ([extra] if extra else []):
            if name is None:   # "report": evaluated over the whole dump, in no view
                rs = svabuild.whole(o.sva, o.bind, o.waves, a.sva_bin, o.sva_prefixes)
            elif o.t_from or o.t_to:   # a window: the bindings again over the whole dump, with the view's files and names
                pfx = o.sva_prefixes
                rs = svabuild.whole(o.sva, o.bind, o.waves, a.sva_bin, [pfx] if isinstance(pfx, str) else pfx, getattr(o, 'sva_aliases', None))
            else:   # the view's own results are the whole dump's
                rs = [b['results'] for b in svabuild.inflate(docs[name].get('sva')) if b.get('results')]
            for r in rs:
                x = r['assertions'][0]
                if (x['name'], x.get('scope') or '', o.waves) not in seen:
                    seen.add((x['name'], x.get('scope') or '', o.waves)); results.append(r)
            if os.path.basename(o.waves) not in dumps:
                dumps.append(os.path.basename(o.waves))
        h, summ = svabuild.report(results, a.sva_bin, {'title': 'Assertions', 'dump': ', '.join(dumps)})
        if h:
            t = summ['totals']
            report = h.replace('<h2>', '<h2 id="assertions">', 1) if 'id="assertions"' not in h else h
            facts.insert(4, ('Checks', f'{t["evaluated"]} assertions, {t["with_failures"]} failing'))
            print(f'mkhtml: assertions section: {t["assertions"]} bindings over the whole dump, {t["fail"]} failing attempts', file=sys.stderr)
    text = PAGE.format(
        title=html.escape(title), theme=f' data-theme="{html.escape(theme)}"' if theme in ('light', 'white', 'dark') else '',
        theme_name=theme if theme in ('light', 'white', 'dark') else 'auto', css=css.replace('</style', '<\\/style'), js=js.replace('</script', '<\\/script'),
        intro=f'<p class="muted">{html.escape(page["intro"])}</p>' if page.get('intro') else '',
        facts=''.join(f'<div><b>{html.escape(k)}</b>{html.escape(v)}</div>' for k, v in facts),
        sections='\n\n'.join([wrap(k, section(k, d, *renders[k])) for k, d in docs.items()] + ([report] if report else [])),
        nav=nav_html(nav) if nav else '', nav_js=NAV_JS if nav else '',
        settings=safe(json.dumps({k: v for k, v in settings.items() if k != 'theme'}, ensure_ascii=False)), sva=sva, bus=bus,
        build=f'\n<script>window.WAVELENS_BUILD = {safe(json.dumps(build, ensure_ascii=False))};</script>' if build else '',
        data=safe(wavejson.dumps_many(docs)))
    states = getattr(a, 'view_states', None)
    if states:   # the views' state from the config: the page's edits, a revision of what they say (applied once, as viewedit.py's)
        text = viewedit.put_block(text, 'edits', {'views': {k: {'rev': 'cfg-' + hashlib.sha1(json.dumps(st, sort_keys=True).encode()).hexdigest()[:10],
                                                                'state': st} for k, st in states.items()}})
    try:
        with open(a.out, 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError as e:
        raise WaveError(f'cannot write {a.out}: {e.strerror}') from None
    print(f'mkhtml: {len(docs)} views -> {a.out} ({len(text.encode()) / 1e6:.2f} MB)', file=sys.stderr)


def main():
    """The command line: every view converted (or the WaveJSON files read), the assertions, one page written."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*', help='key=file.json WaveJSON inputs (instead of --config views)')
    ap.add_argument('--config', help='settings file with "views" (each is converted with vcd2wavedrom.py)')
    ap.add_argument('--settings', help='settings file used only for "config"/"page" (with WaveJSON inputs)')
    ap.add_argument('--view', action='append', help='only these views (repeatable)')
    ap.add_argument('--waves', help='override the dump file of every view')
    ap.add_argument('--title', help='page title')
    ap.add_argument('--render', choices=('view', 'svg', 'both'), help='renderer for every section')
    add_sva_bin_arg(ap)
    ap.add_argument('--sva', action='append', metavar='FILE', help='assertion file for every view (repeatable; replaces the config\'s top-level "sva")')
    ap.add_argument('--bind', action='append', metavar='NAME@SCOPE', help='binding for every view (repeatable, NAME may be a pattern; replaces the top-level "bind")')
    ap.add_argument('--report', action='append', metavar='NAME@SCOPE', help='binding for the printable "Assertions" section only, over the whole '
                    'dump, in no view (repeatable, NAME may be a pattern; replaces the top-level "report")')
    ap.add_argument('--marks-views', choices=testmarks.SPLITS, help='whole (default): all the tests on one waveform; tests: a view of each test, the '
                    'page shows one at a time; both: that and the whole run (replaces the top-level "marksViews")')
    ap.add_argument('--marks-phases', action='store_true', help='with marks: a labelled marker at the start of each phase of a test too '
                    '(the top-level "marksPhases": true), the phases to jump to with ]m [m')
    ap.add_argument('--no-sva', action='store_true', help='leave the assertion engine (wavelens/sva.js + sva.wasm.js, ~440 kB) out of the page, and evaluate nothing')
    ap.add_argument('--reproducible', action='store_true', help='no "Generated" time in the page: the same inputs give the same bytes '
                    '(or set SOURCE_DATE_EPOCH: that time, in UTC)')
    ap.add_argument('--lint', action='store_true', help='check the config: the views are converted and their warnings printed '
                    '(they are printed at every build too); without --out no page is written')
    ap.add_argument('--strict', action='store_true', help='a lint warning is an error (exit 1, no page)')
    ap.add_argument('--lint-json', metavar='FILE', help='the lint warnings as JSON into FILE (- stdout): {"count", "warnings": [{"code", "where", '
                    '"message", "view", and what it is about: "signal" / "name", "rows" it may mean}]}, written at every build, '
                    'a failed one too with "error": its message (exit 1) and the warnings of the views built before it')
    ap.add_argument('--marks', metavar='FILE', help='the marks of a cocotb test (python/wavelens_cocotb.py): its tests as spans, bookmarks and jumps '
                    'in every view (a view\'s "marks": false keeps it out; replaces the top-level "marks")')
    ap.add_argument('--junit', metavar='FILE', help='the assertions of every view as JUnit XML (a testsuite per view, a testcase per binding, '
                    'a failure for one that failed, an error for one that could not run: its signals not in the dump, or capped; skipped: not '
                    'evaluated or 0 attempts): CI gets the page and the report from one build; the exit stays 0 (the page is written)')
    ap.add_argument('--png', metavar='DIR', help='a PNG of every view of the page into DIR (tools/pageshot.py: needs playwright), a test view each '
                    'with --marks-views tests: the CI artifacts')
    ap.add_argument('--png-theme', choices=('dark', 'light', 'both'), default='light', help='with --png: the colour scheme (default light)')
    ap.add_argument('--png-width', type=int, default=1280, metavar='PX', help='with --png: the browser window\'s width in px (default 1280)')
    ap.add_argument('--out', help='output .html (required unless --lint)')
    a = ap.parse_args()
    if (a.junit or a.png) and not a.out:
        ap.error('--junit and --png go with --out (the page they are of)')
    if a.junit and a.no_sva:
        ap.error('--junit is of the assertions: not with --no-sva')
    if not a.config and not a.files:
        ap.error('need --config or WaveJSON files')
    if not a.out and not a.lint:
        ap.error('need --out (or --lint: the check alone)')
    try:
        build(a)
    except WaveError as e:   # B-13: a script reading --lint-json gets an object on a failed build too (the text on stderr, exit 1)
        if a.lint_json:
            msg = str(e)
            write_lint_json(a, {**lint_obj(a), 'error': msg if msg.startswith('mkhtml:') else f'mkhtml: {msg}'})
        raise
    if a.lint_json:
        write_lint_json(a, lint_obj(a))


def lint_obj(a):
    """--lint-json: the warnings of the views built so far (build_views collects them view by view: a later view that fails
    keeps the earlier ones' warnings, review 2026-11-05 runs B-26)."""
    return {'count': getattr(a, 'lint_count', 0), 'warnings': getattr(a, 'lint_items', [])}


def write_lint_json(a, obj):
    """--lint-json: obj as JSON into the file (- stdout)."""
    text = json.dumps(obj, ensure_ascii=False, indent=1) + '\n'
    if a.lint_json == '-':
        sys.stdout.write(text)
        return
    try:
        with open(a.lint_json, 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError as e:
        sys.exit(f'mkhtml: cannot write {a.lint_json}: {e.strerror}')


def build(a):
    """main() after the arguments: the config read, the views built, the lint, the page (WaveError on a failure)."""
    cfg = vcd2wavedrom.load_config(a.config or a.settings) if (a.config or a.settings) else {}
    check_config(cfg.get('config'), f'mkhtml: {a.config or a.settings}: "config"')
    base = os.path.dirname(os.path.abspath(a.config or a.settings or '.'))
    if a.sva:
        cfg['sva'] = [os.path.abspath(f) for f in a.sva]
    if a.bind:
        cfg['bind'] = a.bind
    if a.report:
        cfg['report'] = {'bind': a.report}
    marks = a.marks or (cfg.get('marks') and os.path.join(base, os.path.expanduser(cfg['marks'])))
    split = a.marks_views or cfg.get('marksViews') or 'whole'
    if 'marksPhases' in cfg and not isinstance(cfg['marksPhases'], bool):   # B-18: "yes" was silently nothing
        raise WaveError(f'mkhtml: "marksPhases": true or false, not {json.dumps(cfg["marksPhases"], ensure_ascii=False)}')
    phases, colors = a.marks_phases or cfg.get('marksPhases') is True, cfg.get('marksColors')
    cfg.pop('marks', None), cfg.pop('marksViews', None), cfg.pop('marksPhases', None), cfg.pop('marksColors', None)
    if marks:
        doc = testmarks.load(marks)
        a.nav = testmarks.merge(cfg, doc, split, phases, colors)
        if split != 'whole':   # the views of the tests are of one dump: a marker of yours in one is in each (the setting sharedMarkers)
            cfg.setdefault('config', {}).setdefault('sharedMarkers', True)
        print(f'mkhtml: marks: {testmarks.summary(doc)}', file=sys.stderr)
    for view in (cfg.get('views') or {}).values():
        view.pop('marks', None)   # (false, and no marks to keep it from)
    docs, renders, sva_views = build_views(a, cfg, base)
    n = getattr(a, 'lint_count', 0)   # --lint-json: written by main() at the end, an "error" with it on a failure (lint_obj)
    if a.lint or a.strict:
        print(f'mkhtml: lint: {n} warning{"s" if n != 1 else ""}' + (' (--strict: no page)' if n and a.strict and a.out else ''), file=sys.stderr)
    if n and a.strict:
        if a.lint_json:
            write_lint_json(a, lint_obj(a))
        sys.exit(1)
    if not a.out:   # --lint alone: the check, no page
        return
    with_sva, sva_files, sva_notes = collect_sva(a, cfg, docs)
    render_page(a, cfg, docs, renders, sva_views, with_sva, sva_files, sva_notes)
    if a.junit:
        write_junit(a, docs)
    if a.png:
        page_pngs(a)


def junit_cases(page, key, binds):
    """The testcases of a view's bindings -> [(xml, outcome)], outcome one of pass / failure / error / skipped. A check that did not
    run is never a pass: its signals not in the dump -> an error "missing"; an attempt without verdict (the thread limit) -> an error
    "capped"; a binding without results (no such assertion in the sva files) or with no attempt -> skipped."""
    from xml.sax.saxutils import escape, quoteattr
    out = []
    cls = quoteattr(f'{page}.{key}')
    for b in binds:
        r = b.get('results') or {}
        xs = r.get('assertions') or []
        if not xs:
            name = f'{b.get("assert") or ""}@{b.get("scope") or ""}'
            out.append((f'  <testcase classname={cls} name={quoteattr(name)} time="0"><skipped message="not evaluated: no such assertion '
                        f'in the sva files, or no results"/></testcase>', 'skipped'))
        for x in xs:
            if x.get('kind') == 'cover':   # a cover that did not match is no failure
                continue
            st, cyc = x.get('stats') or {}, x.get('cycles') or r.get('cycles') or []
            fails = [t for t in x.get('attempts') or [] if t.get('result') == 'fail']
            nfail = max(len(fails), int(st.get('fail') or 0))
            at = lambda c: f'{cyc[c] / 1000:g} ns' if isinstance(c, int) and 0 <= c < len(cyc) else f'cycle {c}'
            name = (x.get('name') or b.get('assert') or '') + '@' + (x.get('scope') or b.get('scope') or '')
            end = lambda t: t.get('failed_at', t.get('end'))
            if x.get('missing'):
                msg = 'missing: ' + ', '.join(x['missing'])
                body, how = f'<error type="missing" message={quoteattr(msg)}>{escape(msg)}: not in the dump, the check did not run</error>', 'error'
            elif nfail:
                msg = f'{nfail} failed attempts' + (f', the first at {at(end(fails[0]))}' if fails else '')
                lines = '\n'.join(f'{at(t.get("start"))} -> {at(end(t))}: {t.get("note", "")}' for t in fails[:20])
                body, how = f'<failure type="fail" message={quoteattr(msg)}>{escape(lines)}</failure>', 'failure'
            elif st.get('capped'):
                msg = f'{st["capped"]} attempts without verdict (the thread limit)'
                body, how = f'<error type="capped" message={quoteattr(msg)}/>', 'error'
            elif not st.get('attempts'):
                body, how = '<skipped message="0 attempts: the antecedent never started one"/>', 'skipped'
            else:
                body, how = '', 'pass'
            stats = ', '.join(f'{k} {st[k]}' for k in ('attempts', 'pass', 'fail', 'vacuous', 'capped') if k in st)
            out.append((f'  <testcase classname={cls} name={quoteattr(name)} time="0">{body}<system-out>{escape(stats)}</system-out></testcase>', how))
    return out


def write_junit(a, docs):
    """--junit: the bindings of every view (their results evaluated at the build) as JUnit XML, a testsuite per view: a failure per
    assertion that failed, an error per one that could not run (signals missing, capped), skipped when it was not evaluated."""
    from xml.sax.saxutils import quoteattr
    page = os.path.splitext(os.path.basename(a.out))[0]
    suites, total = [], {'tests': 0, 'failure': 0, 'error': 0, 'skipped': 0}
    for key, doc in docs.items():
        cases = junit_cases(page, key, svabuild.inflate(doc.get('sva')))
        if cases:
            n = {k: sum(h == k for _, h in cases) for k in ('failure', 'error', 'skipped')}
            total['tests'] += len(cases)
            for k in n:
                total[k] += n[k]
            suites.append(f' <testsuite name={quoteattr(f"{page} · {key}")} tests="{len(cases)}" failures="{n["failure"]}" errors="{n["error"]}" '
                          f'skipped="{n["skipped"]}" time="0">\n' + '\n'.join(c for c, _ in cases) + '\n </testsuite>')
    text = '<?xml version="1.0" encoding="UTF-8"?>\n<testsuites>\n' + '\n'.join(suites) + '\n</testsuites>\n'
    try:
        with open(a.junit, 'w', encoding='utf-8') as f:
            f.write(text)
    except OSError as e:
        raise WaveError(f'cannot write {a.junit}: {e.strerror}') from None
    print(f'mkhtml: JUnit: {total["tests"]} bindings in {len(suites)} views, {total["failure"]} failing, {total["error"]} not run (errors), '
          f'{total["skipped"]} skipped -> {a.junit}', file=sys.stderr)


def page_pngs(a):
    """--png: tools/pageshot.py over the page written (a PNG per view; playwright is the one tool outside the standard library)."""
    import subprocess
    tool = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pageshot.py')
    r = subprocess.run([sys.executable, tool, a.out, '--out', a.png, '--theme', a.png_theme, '--width', str(a.png_width)], capture_output=True, text=True,
                       env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    if r.returncode:
        err = r.stderr.strip()
        raise WaveError('--png: ' + (err.splitlines()[-1] if err else f'pageshot.py: exit {r.returncode}') +
                        (' (pip install playwright; playwright install chromium)' if 'playwright' in err.lower() else ''))
    sys.stderr.write(r.stderr)

if __name__ == '__main__':
    run_main(main, 'mkhtml')
