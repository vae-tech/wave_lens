#!/usr/bin/env python3
"""smoke.py — headless Chromium check of example.html and tools/conformance.html (Python playwright).

For each page and colour scheme: no console errors / page errors / wavefw error boxes, every viewer has a
drawn canvas, and on example.html the viewer interaction works (cursor click updates the value column, wheel
zoom changes the view span, Fit restores it, jump buttons move the cursor, group folding hides rows, a lazy
card builds its viewer when opened, Sort with ignored prefixes, settings layers, edge styles and radix). Pages built by
`make html` (/tmp/wavefw_demo.html, dump.html, test_stream_video.html: scope hierarchy, folding, "same") are checked too
when they exist. Full-page PNGs go to --out.

  python3 tools/smoke.py [--out /tmp/wavefw_shots]   (no -I: playwright is usually a user-site install)
"""
import argparse, os, pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = [ROOT / 'example.html', ROOT / 'tools' / 'conformance.html']
BUILT = [pathlib.Path('/tmp/wavefw_demo.html'), ROOT / 'dump.html', ROOT / 'test_stream_video.html']   # from make html, optional
fails = []


def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond:
        fails.append(msg)


def interact(page):
    v = page.locator('#ex-handshake-view')
    cur = v.locator('.cur')
    val = v.locator('.names .row .v').nth(5)          # "state" row
    canvas = v.locator('canvas')
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    before = val.inner_text()
    page.mouse.click(box['x'] + box['width'] * 0.22, box['y'] + 40)
    check(val.inner_text() != before, f'cursor click updates value column ({before!r} -> {val.inner_text()!r})')
    span0 = cur.inner_text()
    page.mouse.move(box['x'] + box['width'] * 0.5, box['y'] + 40)
    page.mouse.wheel(0, -300)
    page.wait_for_timeout(100)
    check(cur.inner_text().split('view')[1] != span0.split('view')[1], f'wheel zoom changes span ({span0.split("·")[1].strip()} -> {cur.inner_text().split("·")[1].strip()})')
    v.locator('button[data-act=fit]').click()
    check(cur.inner_text().split('view')[1] == span0.split('view')[1], 'Fit restores the full span')
    v.locator('button[data-jump="1"]').click()
    check('cycle 8.5' in cur.inner_text(), f'jump button moves cursor ({cur.inner_text()})')
    rows = v.locator('.names .row').count()
    v.locator('.names .row.grp').first.click()
    check(v.locator('.names .row').count() == rows - 2, 'clicking a group folds its 2 rows')
    # exact-time viewer from the VCD
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    check('µs' in ex.locator('.cur').inner_text() or 'ns' in ex.locator('.cur').inner_text(), 'VCD viewer shows a real time axis')
    check(ex.locator('button[data-jump]').count() == 4, 'VCD markers became 4 jump buttons')
    # lazy card
    card = page.locator('#cardlist details').nth(1)
    check(card.locator('canvas').count() == 0, 'closed lazy card has no viewer yet')
    card.locator('summary').click()
    page.wait_for_timeout(100)
    check(card.locator('canvas').count() == 1, 'opening the card builds its viewer')


def sorting(page):
    v = page.locator('#ex-sort-view')
    names = lambda: [x.strip() for x in v.locator('.names .row .n').all_inner_texts()]
    btn = v.locator('button[data-act=sort]')
    check(names() == ['rst_n', 'o_ready', 'i_valid', 'clk', 'o_data', 'i_data'] and btn.inner_text() == 'Sort: off', f'file order at start {names()}')
    btn.click()
    check(names() == ['clk', 'i_data', 'o_data', 'o_ready', 'rst_n', 'i_valid'], f'Sort A→Z skips i_/o_ prefixes {names()}')
    check(v.locator('.names .row .n .pfx').count() == 4, 'ignored prefixes are drawn dimmed')
    val = lambda n: v.locator('.names .row', has_text=n).locator('.v').inner_text()
    canvas = v.locator('canvas')
    canvas.scroll_into_view_if_needed()
    box = canvas.bounding_box()
    page.mouse.click(box['x'] + box['width'] * (2.5 / 16), box['y'] + 40)
    check(val('i_data') == '0x10' and val('o_ready') == '0', f'values follow their rows after sorting (i_data={val("i_data")}, o_ready={val("o_ready")})')
    btn.click()
    check(names() == ['i_valid', 'rst_n', 'o_ready', 'o_data', 'i_data', 'clk'], f'Sort Z→A {names()}')
    v.locator('input.pfx').fill('')
    btn.click(); btn.click()
    check(names() == ['clk', 'i_data', 'i_valid', 'o_data', 'o_ready', 'rst_n'], f'empty prefix field: plain A→Z {names()}')
    canvas.focus(); page.keyboard.press('s')
    check(btn.inner_text() == 'Sort: Z→A', 'key s cycles the sort order')
    btn.click()
    # demo viewer: a group is sorted as a block; the demo config's sortIgnore (rx_, bit_) beats the global i_,o_
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    pfx = ex.locator('input.pfx').input_value()
    check(pfx == 'bit_,rx_', f'JSON config beats wavefw.config.js ({pfx!r})')
    ex.locator('button[data-act=sort]').click()
    en = [x.strip() for x in ex.locator('.names .row .n').all_inner_texts()]
    check(en == ['clk', 'data', '▾ mc_tx', 'busy', 'bit_cnt', 'done', 'state', 'txd', 'rst_n', 'rx_sr', 'start'], f'group sorted as a block, members inside {en}')
    ex.locator('button[data-act=sort]').click(); ex.locator('button[data-act=sort]').click()


def settings(page):
    js = page.evaluate
    v = '#ex-handshake-view'
    canvas_h = lambda: js(f"document.querySelector('{v} canvas').getBoundingClientRect().height")
    check(js("WaveFW.configure({}).sortIgnore.join(',')") == 'i_,o_', 'wavefw.config.js loaded as global settings')
    h0, svg_h = canvas_h(), js("document.querySelector('.wvs svg').getAttribute('height')")
    js("WaveFW.configure({rowHeight: 34, nameWidth: 260, traceWidth: 2})")
    h1, w = canvas_h(), js(f"document.querySelector('{v} .names').getBoundingClientRect().width")
    check(h1 > h0 + 20 and abs(w - 260) < 2, f'configure(rowHeight, nameWidth) restyles viewers (canvas {h0:.0f}->{h1:.0f}px, names {w:.0f}px)')
    check(js("document.querySelector('.wvs svg').getAttribute('height')") != svg_h, 'static SVGs are re-rendered by configure()')
    js("WaveFW.configure({rowHeight: null, nameWidth: 200, traceWidth: null})")
    check(canvas_h() == h0, 'null restores the default')


def styles(page):
    svg = lambda st: page.locator(f'#ex-style-{st} svg')
    texts = svg('square').locator('text').all_text_contents()
    check(all(t in texts for t in ('0x41', '-128', '01000001', '"A"')), f'per-signal radix hex/signed/bin/ascii {texts}')
    html = {st: svg(st).inner_html() for st in ('wavedrom', 'questa', 'square')}
    check(len(set(html.values())) == 3, 'styles wavedrom / questa / square draw different edges')
    dec = page.evaluate("[WaveFW.decode({width: 8}, 'a5', 'signed'), WaveFW.decode({width: 12}, 'a5', 'oct'), WaveFW.decode({width: 4, enum: {5: 'RUN'}}, '5', 'bin')]")
    check(dec == ['-91', '0o245', 'RUN'], f'decode radixes, enum first {dec}')
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    data = ex.locator('.names .row', has_text='data').first.locator('.v')
    page.evaluate("WaveFW.configure({radix: 'bin'})")
    check(data.inner_text() == '00000000', f'configure({{radix: "bin"}}) changes the value column ({data.inner_text()!r})')
    page.evaluate("WaveFW.configure({radix: null})")
    check(data.inner_text() == '0x00', 'radix null restores auto')


def hierarchy(page):
    v = page.locator('.wv').first
    grp = v.locator('.names .row.grp')
    check(grp.first.inner_text().strip().endswith('tb_cxp_top'), f'scopes are groups, top first ({grp.first.inner_text().strip()!r})')
    check(v.locator('.names .row.grp[aria-expanded=false]').count() > 0, 'fold: 2 starts deep scopes folded')
    t = v.locator('.names .row:not(.grp) .n').nth(0).get_attribute('title')
    check(t and t.startswith('tb_cxp_top.'), f'names carry the full path as tooltip ({t})')
    same = page.evaluate("(() => { const M = WaveFW.parse(WAVES.all), s = M.rows.filter(r => r.src && r.src.same); return [s.length, s.filter(r => r.tr.length > 2).length]; })()")
    check(same[0] > 0 and same[0] == same[1], f'"same" signals take the transitions of their net ({same[1]}/{same[0]})')


def big(page):
    t = page.evaluate('() => { const t0 = performance.now(); WaveFW.redrawAll(); return performance.now() - t0; }')
    check(t < 1500, f'redraw of all viewers takes {t:.0f} ms')
    v = page.locator('.wv').last
    v.locator('button[data-act=sort]').click()
    check(v.locator('button[data-act=sort]').inner_text() == 'Sort: A→Z', 'Sort works on the generated page')


def themes(page):
    css = lambda sel, var: page.evaluate(f'''getComputedStyle(document.querySelector('{sel}')).getPropertyValue('{var}').trim()''')
    px = lambda sel, x, y: page.evaluate(f'''(() => {{ const c = document.querySelector('{sel} canvas'), d = window.devicePixelRatio || 1;
        return [...c.getContext('2d').getImageData({x} * d, {y} * d, 1, 1).data.slice(0, 3)]; }})()''')
    check(css('#wv-white', '--wave-bus') == '#000000', 'per-element data-theme="white" sets its own tokens')
    check(px('#wv-white', 5, 5) == [243, 244, 246], f'white viewer header drawn white-theme grey {px("#wv-white", 5, 5)}')
    check(px('#ex-palette-view', 5, 40) == [13, 17, 23], f'config.colors bg drawn in the canvas {px("#ex-palette-view", 5, 40)}')
    check(page.locator('svg path[style*="#d6336c"]').count() > 0, 'per-signal stroke reaches the SVG')
    check(page.locator('svg[data-theme="dark"]').count() == 1, 'per-element dark SVG carries data-theme')
    ex = 'div.wv[data-wave="DEMO_WAVES.exact"]'
    page.evaluate("WaveFW.setTheme('white')")
    check(css('html', '--bg') == '#ffffff' and css(ex, '--wave-bus') == '#000000', 'WaveFW.setTheme("white") themes the page and all waves')
    check(px(ex, 5, 5) == [243, 244, 246], 'global white theme redraws existing viewers')
    page.evaluate("WaveFW.setColors({trace: '#ff0000'})")
    check(css(ex, '--wave-1') == '#ff0000', 'WaveFW.setColors applies to all waves')
    check(css('#ex-palette-view', '--wave-1') == '#7ee787', 'a wave with its own palette keeps it')
    page.evaluate("WaveFW.setColors({trace: null}); WaveFW.setTheme('auto')")
    check(css(ex, '--wave-1') == '#1d1f24', 'null colour and theme "auto" restore the defaults')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='/tmp/wavefw_shots')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        for path in PAGES + [p for p in BUILT if p.exists()]:
            for scheme in ('light', 'dark'):
                print(f'{path.name} [{scheme}]')
                page = b.new_page(color_scheme=scheme, viewport={'width': 1360, 'height': 900})
                errs = []
                page.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
                page.on('pageerror', lambda e: errs.append(str(e)))
                page.goto(path.as_uri())
                page.wait_for_load_state('networkidle')
                page.evaluate('document.fonts.ready')
                page.wait_for_timeout(300)
                errs = [e for e in errs if 'fonts.g' not in e]   # offline Google Fonts is not a page error
                check(not errs, 'no console/page errors' + (': ' + ' | '.join(errs[:3]) if errs else ''))
                check(page.locator('.wvf-err').count() == 0, 'no wavefw error boxes')
                n = page.locator('.wv canvas').count()
                blank = page.evaluate('''() => [...document.querySelectorAll('.wv canvas')].filter(c => c.width === 0 || c.height === 0).length''')
                check(n > 0 and blank == 0, f'{n} viewers, all canvases drawn')
                if path not in BUILT:
                    check(page.locator('.wvs svg').count() > 0, f'{page.locator(".wvs svg").count()} static SVGs')
                if path.name == 'example.html' and scheme == 'light':
                    interact(page)
                    sorting(page)
                    settings(page)
                    styles(page)
                    themes(page)
                if path in BUILT and scheme == 'light':
                    if path.name == 'test_stream_video.html':
                        hierarchy(page)
                    big(page)
                shot = os.path.join(a.out, f'{path.stem}_{scheme}.png')
                page.screenshot(path=shot, full_page=True)
                print('  shot ' + shot)
                page.close()
        b.close()
    print('\nFAILED: ' + str(len(fails)) if fails else '\nall checks passed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
