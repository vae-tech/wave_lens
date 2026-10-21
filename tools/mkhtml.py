#!/usr/bin/env python3
"""mkhtml.py — build one self-contained HTML page (wavefw.css + wavefw.js + data inlined) that opens anywhere.

  mkhtml.py --config dump.config.json --out dump.html            # run every view of the config -> page
  mkhtml.py --config cfg.json --view exact --waves other.vcd ...  # some views only, another dump
  mkhtml.py cyc=cyc.json exact=exact.json --settings cfg.json --out page.html   # from WaveJSON files
  mkhtml.py --config x.config.json --sva checks.sv --bind a_req_ack@tb.dut --out x.html   # assertions bound (make html SVA= BIND=)

Config keys used here (the rest is vcd2wavedrom.py's, see its --help):
  "config"  global wavefw settings for the page: theme, colors, rowHeight, nameWidth, fontSize, sort, sortIgnore, …
  "page"    {"title": "...", "intro": "..."}
  views[k]  "render": "view" (interactive, default) | "svg" (static figure) | "both"; "note": text under the heading
  "sva"     ["checks.sv", …] (top level or in a view) SystemVerilog assertion files: parsed with the sva CLI (one
            compilation unit), inlined as window.SVA for the assertions panel; parse errors are shown in the page.
            false: no assertion engine in the page (also --no-sva). Without "sva" the page still has it ("Load file…").
  "bind"    [{"assert": "a_req_ack", "scope": "tb.dut"}] (top level: every view; or in a view) evaluated over the
            dump with sva eval, so the page opens with them bound (docs/USAGE.md "Assertions"); the page also gets a printable
            "Assertions" section: the bindings over the whole dump (totals, one row per assertion, the failures)
"""
import argparse, datetime, html, json, os, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # -I drops the script dir from sys.path
import svabuild, vcd2wavedrom, wavejson  # noqa: E402
from common import WaveError, add_sva_bin_arg, check_config, run_main  # noqa: E402

FW = os.path.join(os.path.dirname(HERE), 'wavefw')   # the framework files inlined into the page

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
  .sva-report {{ break-before: page; }} .sva-report table {{ font-size: 9.5px; width: 100%; table-layout: auto; }}
  .sva-report th, .sva-report td {{ white-space: normal; padding: 2px 4px; overflow-wrap: anywhere; }}
}}
.bench {{ background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 12px; margin-block: 10px 18px; min-width: 0; }}
button.theme {{ font: inherit; font-size: 12.5px; border: 1px solid var(--line); background: var(--panel); color: var(--fg); border-radius: 4px; padding: 3px 10px; cursor: pointer; }}
button.theme:hover {{ border-color: var(--accent); color: var(--accent); }}
</style>
</head>
<body>
<header>
  <div class="row1"><h1>{title}</h1><button type="button" class="theme" id="theme">Theme: {theme_name}</button></div>
  {intro}
  <div class="facts">{facts}</div>
</header>
{sections}
<script>window.WAVEFW_CONFIG = {settings};</script>
<script>
window.WAVES = {data};
</script>
<script>
{js}
</script>
{bus}{sva}<script>
(function () {{ // page theme button: auto -> light -> white -> dark
  const b = document.getElementById('theme'), modes = ['auto', 'light', 'white', 'dark'];
  let i = Math.max(0, modes.indexOf(document.documentElement.dataset.theme || 'auto'));
  b.addEventListener('click', () => {{ i = (i + 1) % modes.length; WaveFW.setTheme(modes[i]); b.textContent = 'Theme: ' + modes[i]; }});
}})();
</script>
</body>
</html>
'''


def fmt_ps(ps):
    for f, u in ((1e12, 's'), (1e9, 'ms'), (1e6, 'µs'), (1e3, 'ns')):
        if abs(ps) >= f:
            return f'{ps / f:.4g} {u}'
    return f'{ps:g} ps'


def section(key, doc, render, note):
    title = (doc.get('head') or {}).get('text') or key
    ref = html.escape(f'WAVES.{json.dumps(key) if not key.isidentifier() else key}', quote=True)
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
            if a.no_sva:   # no engine in the page: nothing to evaluate either
                o.sva, o.bind = [], []
            name = key or 'wave'
            if o.sva and o.bind and vcfg.get('sva') is not False:
                sva_views.append((name, o))
            print(f'mkhtml: view {name}: {o.waves} ({"clock " + o.clock if o.clock else "exact"})', file=sys.stderr)
            docs[name] = vcd2wavedrom.convert(o)
            renders[name] = (a.render or own.get('render') or cfg.get('render') or 'view', own.get('note'))
    for spec in a.files:
        key, _, path = spec.rpartition('=')
        key = key or os.path.splitext(os.path.basename(path))[0]
        docs[key] = vcd2wavedrom.load_config(path)
        renders[key] = (a.render or 'view', None)
    return docs, renders, sva_views


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
        if not x.get('bind'):
            del d['sva']
    return with_sva, sva_files, sva_notes


def render_page(a, cfg, docs, renders, sva_views, with_sva, sva_files, sva_notes):
    """The page: the framework and the data inlined, the facts, the sections, the printable assertions section."""
    page, settings = cfg.get('page') or {}, cfg.get('config') or {}
    title = a.title or page.get('title') or ', '.join(sorted({(d.get('meta') or {}).get('waves', k) for k, d in docs.items()}))
    metas = [d.get('meta') or {} for d in docs.values()]
    facts = [('Dump', ', '.join(sorted({m['waves'] for m in metas if 'waves' in m})) or '—'),
             ('Wave tool', ', '.join(sorted({m['tool'] for m in metas if 'tool' in m})) or '—'),
             ('Views', str(len(docs))), ('Generated', generated(a.reproducible))]
    facts = [f for f in facts if f[1] is not None]
    if sva_files:
        n = sum(len((f.get('parsed') or {}).get('assertions', [])) for f in sva_files)
        facts.insert(3, ('Assertions', f'{n} in {", ".join(f["name"] for f in sva_files)}' if n else ', '.join(f['name'] for f in sva_files)))
    theme = settings.get('theme')
    with open(os.path.join(FW, 'wavefw.css'), encoding='utf-8') as f:
        css = f.read()
    with open(os.path.join(FW, 'wavefw.js'), encoding='utf-8') as f:
        js = f.read()
    safe = lambda t: t.replace('</', '<\\/')
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
    if sva_views:   # the printable section: every binding of every view over the whole dump, each once
        results, seen, dumps = [], set(), []
        for name, o in sva_views:
            if o.t_from or o.t_to:   # a window: the bindings again over the whole dump, with the view's files and names
                pfx = o.sva_prefixes
                rs = svabuild.whole(o.sva, o.bind, o.waves, a.sva_bin, [pfx] if isinstance(pfx, str) else pfx, getattr(o, 'sva_aliases', None))
            else:   # the view's own results are the whole dump's
                rs = [b['results'] for b in (docs[name].get('sva') or {}).get('bind', []) if b.get('results')]
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
        sections='\n\n'.join([section(k, d, *renders[k]) for k, d in docs.items()] + ([report] if report else [])),
        settings=safe(json.dumps({k: v for k, v in settings.items() if k != 'theme'}, ensure_ascii=False)), sva=sva, bus=bus,
        data=safe(wavejson.dumps_many(docs)))
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(text)
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
    ap.add_argument('--no-sva', action='store_true', help='leave the assertion engine (wavefw/sva.js + sva.wasm.js, ~410 kB) out of the page, and evaluate nothing')
    ap.add_argument('--reproducible', action='store_true', help='no "Generated" time in the page: the same inputs give the same bytes '
                    '(or set SOURCE_DATE_EPOCH: that time, in UTC)')
    ap.add_argument('--out', required=True, help='output .html')
    a = ap.parse_args()
    if not a.config and not a.files:
        ap.error('need --config or WaveJSON files')

    cfg = vcd2wavedrom.load_config(a.config or a.settings) if (a.config or a.settings) else {}
    check_config(cfg.get('config'), f'mkhtml: {a.config or a.settings}: "config"')
    base = os.path.dirname(os.path.abspath(a.config or a.settings or '.'))
    if a.sva:
        cfg['sva'] = [os.path.abspath(f) for f in a.sva]
    if a.bind:
        cfg['bind'] = a.bind
    docs, renders, sva_views = build_views(a, cfg, base)
    with_sva, sva_files, sva_notes = collect_sva(a, cfg, docs)
    render_page(a, cfg, docs, renders, sva_views, with_sva, sva_files, sva_notes)

if __name__ == '__main__':
    run_main(main, 'mkhtml')
