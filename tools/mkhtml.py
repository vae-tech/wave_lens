#!/usr/bin/env python3
"""mkhtml.py — build one self-contained HTML page (wavefw.css + wavefw.js + data inlined) that opens anywhere.

  mkhtml.py --config dump.config.json --out dump.html            # run every view of the config (wavepeek) -> page
  mkhtml.py --config cfg.json --view exact --waves other.vcd ...  # some views only, another dump
  mkhtml.py cyc=cyc.json exact=exact.json --settings cfg.json --out page.html   # from WaveJSON files

Config keys used here (the rest is vcd2wavedrom.py's, see its --help):
  "config"  global wavefw settings for the page: theme, colors, rowHeight, nameWidth, fontSize, sort, sortIgnore, …
  "page"    {"title": "...", "intro": "..."}
  views[k]  "render": "view" (interactive, default) | "svg" (static figure) | "both"; "note": text under the heading
"""
import argparse, datetime, html, json, os, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)   # -I drops the script dir from sys.path
import vcd2wavedrom, wavejson  # noqa: E402

ROOT = os.path.dirname(HERE)

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
<script>
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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='*', help='key=file.json WaveJSON inputs (instead of --config views)')
    ap.add_argument('--config', help='settings file with "views" (each is converted with vcd2wavedrom.py)')
    ap.add_argument('--settings', help='settings file used only for "config"/"page" (with WaveJSON inputs)')
    ap.add_argument('--view', action='append', help='only these views (repeatable)')
    ap.add_argument('--waves', help='override the dump file of every view')
    ap.add_argument('--reader', choices=('builtin', 'wavepeek'), help='how the dumps are read (default: the config\'s "reader", else builtin)')
    ap.add_argument('--title', help='page title')
    ap.add_argument('--render', choices=('view', 'svg', 'both'), help='renderer for every section')
    ap.add_argument('--out', required=True, help='output .html')
    a = ap.parse_args()
    if not a.config and not a.files:
        ap.error('need --config or WaveJSON files')

    cfg = vcd2wavedrom.load_config(a.config or a.settings) if (a.config or a.settings) else {}
    base = os.path.dirname(os.path.abspath(a.config or a.settings or '.'))
    docs, renders = {}, {}
    if a.config:
        views = cfg.get('views') or {}
        keys = a.view or list(views) or [None]
        for key in keys:
            vcfg = vcd2wavedrom.view_config(cfg, key)
            own = (views.get(key) or {}) if key else {}
            vcfg['config'] = own.get('config') or {}   # the top-level "config" is the page's global setting
            argv = (['--waves', a.waves] if a.waves else []) + (['--reader', a.reader] if a.reader else [])
            o = vcd2wavedrom.resolve(vcd2wavedrom.parser().parse_args(argv), vcfg, base)
            name = key or 'wave'
            print(f'mkhtml: view {name}: {o.waves} ({"clock " + o.clock if o.clock else "exact"})', file=sys.stderr)
            docs[name] = vcd2wavedrom.convert(o)
            renders[name] = (a.render or own.get('render') or cfg.get('render') or 'view', own.get('note'))
    for spec in a.files:
        key, _, path = spec.rpartition('=')
        key = key or os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding='utf-8') as f:
            docs[key] = json.load(f)
        renders[key] = (a.render or 'view', None)

    page, settings = cfg.get('page') or {}, cfg.get('config') or {}
    title = a.title or page.get('title') or ', '.join(sorted({(d.get('meta') or {}).get('waves', k) for k, d in docs.items()}))
    metas = [d.get('meta') or {} for d in docs.values()]
    facts = [('Dump', ', '.join(sorted({m['waves'] for m in metas if 'waves' in m})) or '—'),
             ('Wave tool', ', '.join(sorted({m['tool'] for m in metas if 'tool' in m})) or '—'),
             ('Views', str(len(docs))), ('Generated', datetime.datetime.now().strftime('%Y-%m-%d %H:%M'))]
    theme = settings.get('theme')
    with open(os.path.join(ROOT, 'wavefw.css'), encoding='utf-8') as f:
        css = f.read()
    with open(os.path.join(ROOT, 'wavefw.js'), encoding='utf-8') as f:
        js = f.read()
    safe = lambda t: t.replace('</', '<\\/')
    text = PAGE.format(
        title=html.escape(title), theme=f' data-theme="{html.escape(theme)}"' if theme in ('light', 'white', 'dark') else '',
        theme_name=theme if theme in ('light', 'white', 'dark') else 'auto', css=css.replace('</style', '<\\/style'), js=js.replace('</script', '<\\/script'),
        intro=f'<p class="muted">{html.escape(page["intro"])}</p>' if page.get('intro') else '',
        facts=''.join(f'<div><b>{html.escape(k)}</b>{html.escape(v)}</div>' for k, v in facts),
        sections='\n\n'.join(section(k, d, *renders[k]) for k, d in docs.items()),
        settings=safe(json.dumps({k: v for k, v in settings.items() if k != 'theme'}, ensure_ascii=False)),
        data=safe(wavejson.dumps_many(docs)))
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'mkhtml: {len(docs)} views -> {a.out} ({len(text.encode()) / 1e6:.2f} MB)', file=sys.stderr)


if __name__ == '__main__':
    main()
