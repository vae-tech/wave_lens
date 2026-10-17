#!/usr/bin/env python3
"""shots.py — the README screenshots (docs/img/*.png), built the same way every run (Python playwright).

Viewport 1280 px, device scale 1, dark theme (light only for light.png and the static SVG), fonts loaded, then a fixed
sequence of clicks and fields per shot, so an image only changes when the code or an example changes. Each image is
one element of a page (a viewer, its bar, its bookmark list), not the page with its "Generated" time.
Needs `make examples` first (pages in BUILD/examples/) and docs/index.html with docs/demo_waves.js.

  python3 tests/shots.py [--build /tmp/wavefw] [--out docs/img] [--only hero,bar]   (no -I: playwright)
"""
import argparse, os, pathlib, sys, time
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
errors = []


def open_page(browser, path, scheme='dark', height=900):
    if not path.exists():
        sys.exit(f'shots: {path} is missing (make examples)')
    page = browser.new_page(color_scheme=scheme, viewport={'width': 1280, 'height': height}, device_scale_factor=1)
    page.on('console', lambda m: errors.append(f'{path.name}: {m.text}') if m.type == 'error' and 'fonts.g' not in m.text else None)
    page.on('pageerror', lambda e: errors.append(f'{path.name}: {e}'))
    page.goto(path.as_uri())
    page.wait_for_load_state('networkidle')
    page.evaluate('document.fonts.ready')
    page.wait_for_timeout(300)
    return page


def view(page, i=0):
    """The i-th interactive viewer of the page and its waveView, ready for a shot."""
    v = page.locator('.wv').nth(i)
    v.scroll_into_view_if_needed()
    return v


def js(page, i, expr):
    return page.evaluate(f"(() => {{ const v = document.querySelectorAll('.wv')[{i}].waveView; return {expr}; }})()")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default='/tmp/wavefw', help='the Makefile BUILD directory (examples/<ex>/<ex>.html)')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'img'))
    ap.add_argument('--only', help='comma-separated shot names')
    a = ap.parse_args()
    ex = pathlib.Path(a.build) / 'examples'
    apb, axi, axi_all, fsm = ex / 'apb' / 'apb.html', ex / 'axi_lite' / 'axi_lite.html', ex / 'axi_lite' / 'axi_lite_all.html', ex / 'fsm' / 'fsm.html'
    index = ROOT / 'docs' / 'index.html'
    os.makedirs(a.out, exist_ok=True)
    only = set(a.only.split(',')) if a.only else None
    t0 = time.time()

    def shot(name, loc, upto=None):
        if only and name not in only:
            return
        path = os.path.join(a.out, name + '.png')
        loc.page.evaluate('document.activeElement && document.activeElement.blur()')   # no focus ring in the picture
        if upto:   # from the top of loc down to the top of another element (the waves without the lists under them)
            loc.scroll_into_view_if_needed()
            box, end = loc.bounding_box(), upto.bounding_box()
            loc.page.screenshot(path=path, animations='disabled', clip={**box, 'height': end['y'] - box['y']})
        else:
            loc.screenshot(path=path, animations='disabled')
        print(f'  {name}.png  {os.path.getsize(path) / 1e3:.0f} kB')

    with sync_playwright() as p:
        b = p.chromium.launch()

        page = open_page(b, apb)                                   # APB, dark: hero, bar, bookmarks
        shot('hero', page.locator('.bench').first, upto=view(page).locator('.notes'))
        shot('bar', view(page).locator('.bar'))
        shot('bookmarks', view(page).locator('.notes'))
        page.close()

        page = open_page(b, apb, 'light')                          # the light ones: the same view, the static SVG
        shot('light', page.locator('.bench').first, upto=view(page).locator('.notes'))
        shot('svg', page.locator('.bench [data-mode=svg] svg').first)
        page.close()

        page = open_page(b, axi)                                   # AXI-Lite: a colour per channel, latency arrows
        view(page).locator('canvas').focus(); page.keyboard.press('Escape')   # without the start highlight
        shot('axi', page.locator('.bench').first, upto=view(page).locator('.notes'))
        page.close()

        page = open_page(b, axi_all, height=1500)                  # generated page: hierarchy, highlight, find (80vh rows)
        v = view(page)
        page.evaluate("WaveFW.configure({groupColors: {u_master: '#339af0', u_slave: '#37b24d', u_regfile: '#f59f00'}})")
        js(page, 0, '(v.expandAll(), 0)')
        v.locator('.names .row.grp', has_text='u_master').click()                 # one module folded, the rest open
        shot('hierarchy', v)
        page.evaluate('WaveFW.configure({groupColors: null})')
        js(page, 0, '(v.expandAll(), 0)')
        js(page, 0, "(v.toggleHighlight('axi_lite_tb.u_master'), v.toggleHighlight('axi_lite_tb.u_slave'), 0)")
        shot('highlight', v)
        v.locator('canvas').focus(); page.keyboard.press('Escape')
        v.locator('input.q').fill('awvd'); page.wait_for_timeout(150)
        shot('find', v)
        page.close()

        page = open_page(b, fsm)                                   # FSM: names from the FST, questa edges
        shot('fsm', page.locator('.bench').first)
        page.close()

        page = open_page(b, index)                                 # docs/index.html: sorting, cursor fields
        sv = page.locator('#ex-sort-view')
        sv.scroll_into_view_if_needed(); sv.locator('button[data-act=sort]').click()
        shot('sorting', sv)
        cv = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
        cv.scroll_into_view_if_needed()
        cv.locator('input.ct').fill('1.2us'); cv.locator('button[data-act=cset]').click()
        cv.locator('select.su').select_option('ns'); cv.locator('input.cs').fill('100'); cv.locator('button[data-act=cshow]').click()
        shot('cursor', cv)
        page.close()
        b.close()

    print(f'shots: {time.time() - t0:.1f} s -> {a.out}')
    if errors:
        print('page errors:\n  ' + '\n  '.join(errors))
        sys.exit(1)


if __name__ == '__main__':
    main()
