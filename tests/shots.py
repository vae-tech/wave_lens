#!/usr/bin/env python3
"""shots.py — the README screenshots (docs/img/*.png), built the same way every run (Python playwright).

Viewport 1280 px, device scale 1, dark theme (light only for light.png and the static SVG), fonts loaded, then a fixed
sequence of clicks and fields per shot, each followed by two animation frames (no sleeps), so an image only changes when
the code or an example changes. Each image is one element of a page (a viewer, its bar, its bookmark list), not the page
with its "Generated" time. The pictures use IBM Plex (Google Fonts, or a local install such as the Debian / Ubuntu
package fonts-ibm-plex when offline): without it every PNG would differ, so shots.py stops with a message instead.
Needs `make examples` first (pages in BUILD/examples/) and docs/index.html with docs/demo_waves.js. A shot that
cannot be made (a locator that matches nothing or two elements) stops the run with its name: make check runs this
after smoke, so a picture that no longer builds fails the gate.

  python3 tests/shots.py [--build out] [--out docs/img] [--only hero,bar]   (no -I: playwright)
  python3 tests/shots.py --set visual [--out tests/visual]

--set visual: the pictures of the visual regression (review VI T13; not in the docs): the white theme, a viewer 420 px
wide, an FSM's details (its states, its diagram), a viewer at a device scale of 2. make shots-check compares both sets
with the committed ones (tests/pngdiff.py: a picture that changed fails the gate); make shots writes both.
"""
import argparse, os, pathlib, sys, time
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
errors = []
# software raster, one thread, no partial raster: the anti-aliasing of the form controls' borders is the same every run
RASTER = ['--disable-gpu', '--disable-gpu-rasterization', '--disable-partial-raster', '--num-raster-threads=1',
          '--force-color-profile=srgb', '--disable-lcd-text']
# IBM Plex is there (from Google Fonts or installed) when its widths differ from the fallback's
PLEX = '''(() => { const c = document.createElement('canvas').getContext('2d'), w = f => (c.font = f, c.measureText('mmmwwwiil 0O').width);
    return ['IBM Plex Sans', 'IBM Plex Mono'].filter(n => w(`16px "${n}", serif`) === w('16px serif')); })()'''


def settle(page):
    """Two animation frames: the viewers draw in requestAnimationFrame, the shot comes after it."""
    page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


def open_page(browser, path, scheme='dark', height=900, width=1280, scale=1):
    if not path.exists():
        sys.exit(f'shots: {path} is missing (make examples)')
    page = browser.new_page(color_scheme=scheme, viewport={'width': width, 'height': height}, device_scale_factor=scale)
    page.on('console', lambda m: errors.append(f'{path.name}: {m.text}') if m.type == 'error' and 'fonts.g' not in m.text else None)
    page.on('pageerror', lambda e: errors.append(f'{path.name}: {e}'))
    page.goto(path.as_uri())
    page.wait_for_load_state('networkidle')
    page.evaluate('document.fonts.ready')
    missing = page.evaluate(PLEX)
    if missing:
        sys.exit(f'shots: {", ".join(missing)} not available (offline?): the PNGs would differ from the committed ones. '
                 'Connect to the network (Google Fonts) or install the font (fonts-ibm-plex) and run again.')
    page.add_style_tag(content='.wv-tip { display: none !important; }')   # a tooltip shows 350 ms after a hover: never in a shot
    page.add_style_tag(content='.wv .bar .ver { display: none !important; }')   # the version and commit: a picture the same at every commit
    settle(page)
    return page


def no_sva(page):
    """The shots of the viewer itself: no assertion groups, no assertions panel (sva.png and sva-table.png have them)."""
    page.evaluate("(async () => { await SVA.ready(); WaveLens.configure({svaShow: []}); await SVA.ready(); SVA.panels().forEach(p => { p.el.hidden = true; }); })()")
    settle(page)


def view(page, i=0):
    """The i-th interactive viewer of the page and its waveView, ready for a shot."""
    v = page.locator('.wv').nth(i)
    v.scroll_into_view_if_needed()
    return v


def js(page, i, expr):
    return page.evaluate(f"(() => {{ const v = document.querySelectorAll('.wv')[{i}].waveView; return {expr}; }})()")


def visual(b, shot, apb, fsm, fsm_all):
    """The visual regression's pictures (--set visual)."""
    page = open_page(b, apb)                                       # the white theme
    no_sva(page)
    page.evaluate("WaveLens.setTheme('white')"); settle(page)
    shot('white', page.locator('.bench').first, upto=view(page).locator('.notes'))
    page.close()
    page = open_page(b, apb, width=420, height=900)                # a phone's width: the bar wraps, the names narrow
    no_sva(page)
    shot('narrow', view(page))
    page.close()
    page = open_page(b, fsm_all, height=1000)                      # an FSM's details: its states, its diagram
    no_sva(page)
    js(page, 0, "(v.fsmPanel(true), v.cursor = 400000, v.draw(), 0)"); settle(page)
    page.locator('.wv-fsms .mn.fs').nth(1).click(); settle(page)
    page.evaluate("(() => { const p = document.querySelector('.wv-fsms'); p.style.left = '20px'; p.style.top = '20px'; })()"); settle(page)
    shot('fsm-states', page.locator('.wv-fsms'))
    page.locator('.wv-fsms .fdt button[data-t=graph]').click(); settle(page)
    shot('fsm-graph', page.locator('.wv-fsms'))
    page.close()
    page = open_page(b, fsm, scale=2)                              # a device scale of 2: the canvas drawn at its pixels
    no_sva(page)
    shot('scale2', view(page).locator('canvas').first)
    page.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default=str(pathlib.Path(__file__).resolve().parent.parent / 'out'), help='the Makefile BUILD directory (examples/<ex>/<ex>.html)')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'img'))
    ap.add_argument('--only', help='comma-separated shot names')
    ap.add_argument('--set', choices=['docs', 'visual'], default='docs', help='docs/img (default) or the visual regression\'s tests/visual')
    a = ap.parse_args()
    if a.set == 'visual' and a.out == str(ROOT / 'docs' / 'img'):
        a.out = str(ROOT / 'tests' / 'visual')
    ex = pathlib.Path(a.build).resolve() / 'examples'   # as_uri() needs an absolute path
    apb, axi, axi_all, fsm = ex / 'apb' / 'apb.html', ex / 'axi_lite' / 'axi_lite.html', ex / 'axi_lite' / 'axi_lite_all.html', ex / 'fsm' / 'fsm.html'
    fsm_all = ex / 'fsm' / 'fsm_all.html'
    index = ROOT / 'docs' / 'index.html'
    os.makedirs(a.out, exist_ok=True)
    only = set(a.only.split(',')) if a.only else None
    t0 = time.time()

    def shot(name, loc, upto=None):
        if only and name not in only:
            return
        path = os.path.join(a.out, name + '.png')
        loc.page.evaluate('document.activeElement && document.activeElement.blur()')   # no focus ring in the picture
        loc.page.mouse.move(0, 0)                                                         # no hover
        # a face the page asks for only when its text shows (a <select>'s): loaded before the picture, not half way
        loc.page.evaluate('document.fonts.ready'); settle(loc.page)
        if upto:   # from the top of loc down to the top of another element (the waves without the lists under them)
            loc.scroll_into_view_if_needed()
            box, end = loc.bounding_box(), upto.bounding_box()
            loc.page.screenshot(path=path, animations='disabled', clip={**box, 'height': end['y'] - box['y']})
        else:
            loc.screenshot(path=path, animations='disabled')
        print(f'  {name}.png  {os.path.getsize(path) / 1e3:.0f} kB')

    with sync_playwright() as p:
        b = p.chromium.launch(args=RASTER)
        if a.set == 'visual':
            visual(b, shot, apb, fsm, fsm_all)
            b.close()
            print(f'shots: {time.time() - t0:.1f} s -> {a.out}')
            sys.exit(1 if errors else 0)

        page = open_page(b, apb, height=1100)                      # APB, dark: an assertion failure selected, the panel's numbers
        page.evaluate("(async () => { await SVA.ready(); WaveLens.configure({svaShow: ['apb_demo_no_wait'], svaSignals: false}); await SVA.ready(); })()")
        p0 = 'SVA.panels()[0]'
        page.evaluate(f"(() => {{ const p = {p0}; p.open = false; p.render(); p.v.expandAll(); p.v.canvas.focus(); }})()")
        page.keyboard.press('f'); settle(page)
        page.evaluate("window.scrollTo(0, 0)")
        shot('sva', page.locator('.bench').first, upto=view(page).locator('.notes'))
        page.evaluate(f"(async () => {{ const p = {p0}; p.open = true; p.showTable = true; p.showFails = true; p.render(); p.el.querySelector('ol.asv').style.display = 'none'; }})()")
        settle(page)
        shot('sva-table', view(page).locator('.sva'))
        page.evaluate('WaveLens.configure({svaShow: null, svaSignals: null})')
        page.close()

        page = open_page(b, apb)                                   # APB, dark: hero, bar, bookmarks
        no_sva(page)
        shot('hero', page.locator('.bench').first, upto=view(page).locator('.notes'))
        shot('bar', view(page).locator('.bar'))
        shot('bookmarks', view(page).locator('.notes'))
        page.close()

        page = open_page(b, apb)                                   # APB, dark: measuring — a range and its menu, two cursors, a bus as a step plot
        no_sva(page)
        v = view(page)
        js(page, 0, "(v.setRange(45000, 105000, v.M.rows.find(r => r.name === 'PADDR')), v.select('PADDR'), 0)")
        bb = v.locator('canvas').bounding_box()
        js(page, 0, f"(v.menu({bb['x'] + 640}, {bb['y'] + 30}, v.sel, v.range), 0)"); settle(page)
        shot('range', v, upto=v.locator('.notes'))
        js(page, 0, "(v.closeMenu(), v.setRange(null), v.select('PCLK'), v.cursor = 35000, v.setCursor2(115000), v.setAnalog(v.M.rows.find(r => r.name === 'PADDR'), 3), 0)")
        settle(page)
        shot('cursors', v, upto=v.locator('.notes'))
        js(page, 0, "(v.setCursor2(null), v.setAnalog(v.M.rows.find(r => r.name === 'PADDR'), null), 0)")
        page.close()

        page = open_page(b, apb, height=1100)                      # APB: Why of the failed attempt, cycle by cycle
        page.evaluate("(async () => { await SVA.ready(); WaveLens.configure({svaShow: ['apb_demo_no_wait'], svaSignals: false}); await SVA.ready(); })()")
        page.evaluate(f"""(() => {{ const p = {p0}; p.open = true; p.render(); p.v.expandAll();
            const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait'); p.select(b, b.results.assertions[0].attempts.findIndex(a => a.result === 'fail')); }})()""")
        page.locator('.wv .sva .svw table').first.wait_for()
        shot('why', view(page).locator('.sva .svw'))
        page.evaluate('WaveLens.configure({svaShow: null, svaSignals: null})')
        page.close()

        page = open_page(b, apb, 'light')                          # the light ones: the same view, the static SVG
        no_sva(page)
        shot('light', page.locator('.bench').first, upto=view(page).locator('.notes'))
        shot('svg', page.locator('.bench [data-mode=svg] svg').first)
        page.close()

        page = open_page(b, axi)                                   # AXI-Lite: a colour per channel, latency arrows
        no_sva(page)
        view(page).locator('canvas').focus(); page.keyboard.press('Escape')   # without the start highlight
        shot('axi', page.locator('.bench').first, upto=view(page).locator('.notes'))
        page.close()

        page = open_page(b, axi_all, height=1500)                  # generated page: hierarchy, highlight, find (80vh rows)
        no_sva(page)
        v = view(page)
        page.evaluate("WaveLens.configure({groupColors: {u_master: '#339af0', u_slave: '#37b24d', u_regfile: '#f59f00'}})")
        js(page, 0, '(v.expandAll(), 0)')
        v.locator('.names .row.grp[title="axi_lite_tb.u_master"]').click()      # one module folded, the rest open (not its bus port)
        shot('hierarchy', v)
        page.evaluate('WaveLens.configure({groupColors: null})')
        js(page, 0, '(v.expandAll(), 0)')
        js(page, 0, "(v.toggleHighlight('axi_lite_tb.u_master'), v.toggleHighlight('axi_lite_tb.u_slave'), 0)")
        shot('highlight', v)
        v.locator('canvas').focus(); page.keyboard.press('Escape')
        v.locator('input.q').fill('awvd'); settle(page)
        shot('find', v)
        page.close()

        page = open_page(b, axi)                                   # AXI-Lite: its bus port found, one write selected
        no_sva(page)
        v = view(page)
        js(page, 0, "(p => (v.buses.select(p, p.D.tx[0]), 0))(v.buses.list()[0])"); settle(page)
        shot('buses', v, upto=v.locator('.notes'))
        page.close()

        page = open_page(b, fsm_all)                               # FSM, generated page: the packed struct status, its fields
        no_sva(page)
        v = view(page)
        js(page, 0, "(v.collapseAll(), Object.entries(v.M.groups).forEach(([id, g]) => ['fsm_tb', 'fsm_tb.status'].includes(g.path) && v.collapsed.delete(+id)), v.cursor = 300000, v.renderNames(), v.draw(), 0)")
        settle(page)
        shot('struct', v)
        page.close()

        page = open_page(b, fsm)                                   # FSM: names from the FST, questa edges
        no_sva(page)
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
        settle(page)
        shot('cursor', cv)
        page.close()
        b.close()

    print(f'shots: {time.time() - t0:.1f} s -> {a.out}')
    if errors:
        print('page errors:\n  ' + '\n  '.join(errors))
        sys.exit(1)


if __name__ == '__main__':
    main()
