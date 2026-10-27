#!/usr/bin/env python3
"""pageshot.py — PNG pictures of a WaveLens page's views, made in a headless Chromium (Python playwright), so an agent or a
script sees what a person would see without opening a browser: one PNG per view and theme, and a manifest.

The one tool of tools/ outside the standard library, and optional: it needs playwright and its Chromium (pip install
playwright; python3 -m playwright install chromium), as tests/smoke.py and tests/shots.py do. Run it without -I
(playwright is usually a user-site install). The page is opened as a person opens it (its edits applied, every viewer
drawn, the assertions evaluated), in a fresh context: nothing this browser kept of the page counts.

  pageshot.py page.html                                  # every view, dark and light -> page-shots/<page>-<view>-<theme>.png
  pageshot.py page.html --view crc --theme dark --out shots/ [--width 1280]

stdout: the manifest (JSON: [{"view", "theme", "path", "width", "height"}]), also written as manifest.json in --out.
Exit 1: the page has errors (its console, an error box) or a view is not there; 2: no playwright or Chromium. The MCP
server's view_get with "picture" on a page's file runs it (tools/wavemcp.py).
"""
import argparse, json, os, struct, sys

RASTER = ['--disable-gpu', '--disable-gpu-rasterization', '--disable-partial-raster', '--num-raster-threads=1',
          '--force-color-profile=srgb', '--disable-lcd-text']   # as tests/shots.py: the same pixels every run
SETTLE = 'new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))'


def views(page):
    """The views of the page: [(key, its element's selector)] in page order (mkhtml.py: data-wave="WAVES.<key>")."""
    return page.evaluate("""[...document.querySelectorAll('[data-wave]')].map((e, i) => {
        const k = e.dataset.wave.replace(/^WAVES\\.?/, '').replace(/^\\["|"\\]$/g, '').replace(/\\\\"/g, '"');
        return [k + (e.dataset.mode === 'svg' ? ':svg' : ''), i]; })""")


def shoot(path, want=None, themes=('dark', 'light'), out='.', width=1280, timeout=30000):
    try:
        from playwright.sync_api import sync_playwright, Error as PwError
    except ImportError:
        print('pageshot: no playwright (pip install playwright; python3 -m playwright install chromium)', file=sys.stderr)
        sys.exit(2)
    os.makedirs(out, exist_ok=True)
    stem, made, errors = os.path.splitext(os.path.basename(path))[0], [], []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(args=RASTER)
        except PwError as e:
            print(f'pageshot: Chromium does not start ({str(e).splitlines()[0]}): python3 -m playwright install chromium', file=sys.stderr)
            sys.exit(2)
        for theme in themes:
            ctx = browser.new_context(color_scheme=theme, viewport={'width': width, 'height': 900}, device_scale_factor=1)
            page = ctx.new_page()
            page.set_default_timeout(timeout)
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'fonts.g' not in m.text else None)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto('file://' + os.path.abspath(path))
            try:
                page.wait_for_load_state('networkidle', timeout=timeout)
            except PwError:
                pass   # a font that does not come: the fallback
            page.evaluate('document.fonts.ready')
            page.evaluate("window.SVA && SVA.ready ? SVA.ready() : null")
            page.add_style_tag(content='.wv-tip { display: none !important; }')
            page.evaluate(SETTLE)
            boxes = page.locator('.wvf-err').count()   # (boot.js: a view that did not build)
            if boxes:
                errors.append(f'{boxes} error box(es) on the page')
            have = views(page)
            pick = [(k, i) for k, i in have if want is None or k.split(':')[0] == want]
            if not pick:
                print(f'pageshot: no view "{want}" in {path} (have: {", ".join(k for k, _ in have) or "none"})', file=sys.stderr)
                sys.exit(1)
            for key, i in pick:
                el = page.locator('[data-wave]').nth(i)
                box = el.locator('xpath=..') if el.evaluate("e => e.parentElement && e.parentElement.classList.contains('bench')") else el
                box.scroll_into_view_if_needed()
                page.evaluate(SETTLE)
                name = f'{stem}-{key.replace(":", "-")}-{theme}.png'.replace('/', '_')
                f = os.path.join(out, name)
                box.screenshot(path=f)
                with open(f, 'rb') as fh:   # the PNG's own size (IHDR)
                    w, h = struct.unpack('>II', fh.read(24)[16:24])
                made.append({'view': key.split(':')[0], **({'render': 'svg'} if key.endswith(':svg') else {}), 'theme': theme, 'path': f,
                             'width': w, 'height': h})
            ctx.close()
        browser.close()
    with open(os.path.join(out, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(made, fh, indent=1)
    return made, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('page', help='a WaveLens page (mkhtml.py, wave_page, Save page)')
    ap.add_argument('--view', help='only this view (its key: the id of its section)')
    ap.add_argument('--theme', choices=('dark', 'light', 'both'), default='both', help='the colour scheme (default both)')
    ap.add_argument('--out', help='the directory of the PNGs (default: <page>-shots beside the page)')
    ap.add_argument('--width', type=int, default=1280, help='the browser window\'s width in px (default 1280)')
    a = ap.parse_args()
    if not os.path.isfile(a.page):
        print(f'pageshot: no such page: {a.page}', file=sys.stderr)
        return 1
    out = a.out or os.path.splitext(a.page)[0] + '-shots'
    made, errors = shoot(a.page, a.view, ('dark', 'light') if a.theme == 'both' else (a.theme,), out, a.width)
    print(json.dumps(made, ensure_ascii=False, indent=1))
    for e in dict.fromkeys(errors):
        print(f'pageshot: the page: {e}', file=sys.stderr)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    sys.exit(main())
