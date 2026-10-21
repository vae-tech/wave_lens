#!/usr/bin/env python3
"""guide_shots.py — the pictures of the guides (docs/guides/img/*.png), made the way tests/shots.py makes the README's.

Viewport 1280 px, device scale 1, dark theme unless a shot says otherwise, IBM Plex (shots.py stops without it), a fixed
sequence of calls per shot. Each shot belongs to a guide (--only viewer,gaps,…: those guides). The gaps guide reads a
dump made here: a stream with five rare packets in 10 µs and a slow heartbeat (BUILD/guides/stream.vcd, its config and
page); the others read the examples' pages (make examples demo first), wavefw/viewer.html, docs/index.html and
tests/conformance.html.

  python3 tests/guide_shots.py [--build out] [--out docs/guides/img] [--only gaps,sva]   (no -I: playwright)
"""
import argparse, json, os, pathlib, subprocess, sys, time
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shots  # noqa: E402  (its raster flags, the page opener, settle, js)

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUIDES = ['viewer', 'gaps', 'sva', 'wavedrom', 'pages', 'buses', 'mcp']

# the gaps guide's dump: clk 100 MHz for 1000 cycles; packets of a valid / ready stream (start cycle, beats, cycles of
# the packet with ready low), the state of the sender, an irq two cycles after each packet, a packet counter, and a
# heartbeat hb that toggles every 64 cycles (a slow signal that changes in every idle stretch)
CYC, NCYC = 10000, 1000
PACKETS = [(12, [0x11, 0x22, 0x33, 0x44], []), (150, [0xa0, 0xa1], [1]), (162, [0xb0, 0xb1, 0xb2], []),
           (540, [0x5a, 0x5b, 0x5c, 0x5d, 0x5e], [2, 3]), (905, [0xf0, 0xf1, 0xf2], [])]
WIDTH = {'clk': 1, 'rst_n': 1, 'state': 2, 'valid': 1, 'ready': 1, 'data': 8, 'last': 1, 'irq': 1, 'frames': 8, 'hb': 1}
STREAM_CONFIG = {
    'description': 'tests/guide_shots.py: the dump of docs/guides/gaps.html, a stream with five rare packets in 10 us',
    'scope': 'tb', 'enum': {'state': {'0': 'IDLE', '1': 'SEND', '2': 'DONE'}},
    'config': {'radix': 'hex', 'nameWidth': 110},
    'page': {'title': 'A stream with rare packets',
             'intro': 'Five packets of a valid / ready stream in 10 µs of a 100 MHz clock, an irq after each, a slow heartbeat hb.'},
    'views': {
        'run': {'exact': True, 'signals': list(WIDTH), 'title': 'five packets in 10 µs · exact',
                'bookmarks': [{'n': 1, 't': '1500ns', 'signal': 'valid', 'text': 'packet 2'},
                              {'n': 2, 't': '1620ns', 'signal': 'valid', 'text': 'packet 3'},
                              {'n': 3, 't': '5400ns', 'signal': 'valid', 'text': 'packet 4: two stalls'}],
                'arrows': [{'from': 1, 'to': 3, 'shape': '-|-', 'label': 'packet 2 → 4'}]},
        'figure': {'exact': True, 'signals': ['clk', 'state', 'valid', 'ready', 'data', 'last', 'irq'], 'render': 'svg',
                   'title': 'the same run as a static SVG with gaps', 'note': 'the view\'s "config": gaps, gapIdle 16, gapKeep 2 (hscale 0.35: a narrow cycle)',
                   'config': {'gaps': True, 'gapIdle': 16, 'gapKeep': 2, 'hscale': 0.35}},
    },
}


def stream_vcd():
    sig = {}

    def ch(n, t, v):
        lst = sig.setdefault(n, [])
        if not lst or lst[-1][1] != v:
            lst.append((t, v))
    for n in WIDTH:
        if n != 'clk':
            ch(n, 0, 1 if n == 'ready' else 0)
    ch('rst_n', 4 * CYC, 1)
    for k, (c0, beats, stalls) in enumerate(PACKETS):
        c, i = c0, 0
        ch('state', c * CYC, 1)
        while i < len(beats):
            ch('valid', c * CYC, 1); ch('data', c * CYC, beats[i]); ch('last', c * CYC, int(i == len(beats) - 1))
            stall = c - c0 in stalls
            ch('ready', c * CYC, 0 if stall else 1)
            i += 0 if stall else 1
            c += 1
        ch('valid', c * CYC, 0); ch('last', c * CYC, 0); ch('state', c * CYC, 2); ch('frames', c * CYC, k + 1)
        ch('irq', (c + 2) * CYC, 1); ch('irq', (c + 4) * CYC, 0); ch('state', (c + 4) * CYC, 0)
    for c in range(0, NCYC, 64):
        ch('hb', c * CYC, (c // 64) % 2)
    ids = {n: chr(33 + i) for i, n in enumerate(WIDTH)}
    ev = {}
    for c in range(NCYC + 1):
        ev.setdefault(c * CYC, []).append(('clk', 1)); ev.setdefault(c * CYC + CYC // 2, []).append(('clk', 0))
    for n, lst in sig.items():
        for t, v in lst:
            ev.setdefault(t, []).append((n, v))
    out = ['$timescale 1ps $end', '$scope module tb $end']
    out += [f'$var wire {w} {ids[n]} {n}{"" if w == 1 else f" [{w - 1}:0]"} $end' for n, w in WIDTH.items()]
    out += ['$upscope $end', '$enddefinitions $end']
    for t in sorted(ev):
        out.append(f'#{t}')
        out += [f'{v}{ids[n]}' if WIDTH[n] == 1 else f'b{v:b} {ids[n]}' for n, v in ev[t]]
    return '\n'.join(out) + '\n'


def build_stream(build):
    d = build / 'guides'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'stream.vcd').write_text(stream_vcd())
    (d / 'stream.config.json').write_text(json.dumps(STREAM_CONFIG, indent=2) + '\n')
    subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'mkhtml.py'), '--config', str(d / 'stream.config.json'), '--waves',
                    str(d / 'stream.vcd'), '--no-sva', '--reproducible', '--out', str(d / 'stream.html')], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return d / 'stream.html'


class Shots:
    def __init__(self, browser, out, only):
        self.b, self.out, self.only, self.n = browser, out, only, 0

    def page(self, path, scheme='dark', height=900, tips=False, width=1280):
        page = shots.open_page(self.b, path, scheme, height)
        if width != 1280:
            page.set_viewport_size({'width': width, 'height': height})
        if tips:   # shots.py hides the tooltips; some pictures here are of a tooltip
            page.evaluate("document.querySelectorAll('style').forEach(s => { if (s.textContent.trim().startsWith('.wv-tip { display: none')) s.remove(); })")
        return page

    def save(self, name, loc=None, upto=None, clip=None, page=None, pad=0):
        path = os.path.join(self.out, name + '.png')
        pg = page or loc.page
        if upto is not None and (not upto.count() or upto.bounding_box() is None or upto.bounding_box()['height'] == 0):
            upto = None   # no bookmark list under these waves: the whole viewer
        if clip is None and upto is None and pad == 0:
            loc.screenshot(path=path, animations='disabled')
        else:
            if loc is not None:
                loc.scroll_into_view_if_needed()
            box = clip or loc.bounding_box()
            if upto is not None:
                box = {**box, 'height': upto.bounding_box()['y'] - box['y']}
            box = {'x': max(0, box['x'] - pad), 'y': max(0, box['y'] - pad), 'width': box['width'] + 2 * pad, 'height': box['height'] + 2 * pad}
            pg.screenshot(path=path, animations='disabled', clip=box)
        self.n += 1
        print(f'  {name}.png  {os.path.getsize(path) / 1e3:.0f} kB')

    def quiet(self, page):
        page.evaluate('document.activeElement && document.activeElement.blur()')
        page.mouse.move(0, 0)


def union(*boxes):
    x0, y0 = min(b['x'] for b in boxes), min(b['y'] for b in boxes)
    x1, y1 = max(b['x'] + b['width'] for b in boxes), max(b['y'] + b['height'] for b in boxes)
    return {'x': x0, 'y': y0, 'width': x1 - x0, 'height': y1 - y0}


def picture(page, svg, name='pic'):
    """An SVG of the viewer (its picture, toSVG) put at the top of the page on the viewer's background: a locator to shoot."""
    page.evaluate("""([s, id]) => { document.getElementById(id)?.remove(); const d = document.createElement('div'); d.id = id;
        d.style.cssText = 'display:inline-block;padding:10px;background:var(--wave-bg, #1d2026)'; d.innerHTML = s;
        document.body.prepend(d); window.scrollTo(0, 0); }""", [svg, name])
    shots.settle(page)
    return page.locator('#' + name)


# ---------------------------------------------------------------- the gaps guide
def gaps(S, ex, build):
    page = S.page(build_stream(build), height=1000)
    v = shots.view(page)
    js = lambda e: shots.js(page, 0, e)   # noqa: E731
    js('(v.setGaps(null), 0)')
    S.quiet(page)
    S.save('gaps-viewer', v, upto=v.locator('.notes'))
    whole = "v.toSVG({from: v.M.t0, to: v.M.t1, rows: 'all', width: 1180})"
    S.save('gaps-off', picture(page, js(whole)))
    js("(v.setGaps({gaps: true}), 0)")
    S.save('gaps-on-all', picture(page, js(whole)))
    sig = "['state', 'valid', 'ready', 'data', 'last', 'irq', 'frames']"
    js(f"(v.setGaps({{gaps: true, gapSignals: {sig}}}), 0)")
    S.save('gaps-by-signals', picture(page, js(whole)))
    js("(v.setGaps({gapIdle: 200}), 0)")
    S.save('gaps-idle200', picture(page, js(whole)))
    js("(v.setGaps({gapIdle: 16, gapKeep: 0}), 0)")
    S.save('gaps-keep0', picture(page, js(whole)))
    js("(v.setGaps({gapKeep: 8}), 0)")
    S.save('gaps-keep8', picture(page, js(whole)))
    js("(v.setGaps({gapKeep: '200ns', gapIdle: '1us'}), 0)")
    S.save('gaps-times', picture(page, js(whole)))
    js("(v.setGaps({gapKeep: 2, gapIdle: 16, gapSignals: ['valid', 'ready', 'data', 'last'], gapOnly: true}), 0)")
    S.save('gaps-only', picture(page, js("v.toSVG({from: v.M.t0, to: v.M.t1, rows: v.exportRows(), width: 1180})")))
    js(f"(v.setGaps({{gapOnly: false, gapSignals: {sig}}}), 0)")
    js("(v.setGaps({gapAux: ['hb'], gapCount: 'edges'}), 0)")
    S.save('gaps-aux', picture(page, js(whole)))
    js("(v.setGaps({gapAux: null, gapCount: 'off'}), 0)")
    S.save('gaps-notext', picture(page, js(whole)))
    js("(v.setGaps({gapCount: 'clock'}), 0)")
    for line in ['dashdot', 'wave', 'waves', 'zigzag', 'double']:
        js(f"(v.setGaps({{gapLine: '{line}'}}), 0)")
        pic = picture(page, js("v.toSVG({from: 1300000, to: 2000000, rows: v.rowsL.filter(r => ['clk', 'valid', 'data'].includes(r.name)), width: 560})"))
        S.save('gaps-line-' + line, pic)
    js("(v.setGaps({gapLine: null}), 0)")
    # the bookmarks and the arrow across the gaps
    js("(v.setGaps({gapIdle: 16, gapKeep: 2}), 0)")
    js("(v.setBookmarks([...v.bookmarks(), {n: 4, t: 3500000, signal: 'tb.hb', text: 'a bookmark where nothing happens: its time is kept'}], "
       "v.arrowList()), 0)")
    S.save('gaps-bookmark', picture(page, js(whole)))
    js("(v.setBookmarks(v.bookmarks().filter(b => b.n !== 4), v.arrowList()), 0)")
    page.evaluate("document.getElementById('pic')?.remove()")
    # the menu: the Gaps submenu open on the valid row, the viewer around it
    S.quiet(page)
    v.scroll_into_view_if_needed()
    bb = v.locator('canvas').bounding_box()
    js("(v.select('valid'), 0)")
    js(f"(v.menu({bb['x'] + 260}, {bb['y'] + 70}, v.M.rows.find(r => r.name === 'valid')), 0)")
    page.locator('.wv-menu .subh').hover(); shots.settle(page)
    S.save('gaps-menu', clip=union(page.locator('.wv-menu').bounding_box(), page.locator('.wv-menu .sub').first.bounding_box()), page=page, pad=6)
    S.save('gaps-menu-viewer', v, upto=v.locator('.notes'))
    js("(v.closeMenu(), 0)")
    # roles in the names column: // the gaps follow, ↑ the clock counted, + counted in a gap
    js("(v.setGaps({gapClock: 'clk', gapAux: ['hb'], gapCount: 'edges'}), 0)")
    S.quiet(page)
    S.save('gaps-roles', v.locator('.names'))
    # WaveDrom of the whole run with the gaps: the "|" cells, drawn by this page's static SVG
    wd = js("JSON.stringify(v.toWaveDrom(v.M.t0, v.M.t1, v.rowsL.filter(r => ['clk', 'valid', 'ready', 'data', 'last'].includes(r.name))))")
    (pathlib.Path(S.out) / 'gaps-wavedrom.json').write_text(json.dumps(json.loads(wd), indent=1) + '\n')
    wd2 = js("JSON.stringify(v.toWaveDrom(v.M.t0, 2300000, v.rowsL.filter(r => ['clk', 'valid', 'ready', 'data', 'last'].includes(r.name))))")
    page.evaluate("""s => { document.getElementById('pic')?.remove(); const d = document.createElement('div'); d.id = 'pic';
        d.style.cssText = 'display:inline-block;padding:10px;background:var(--wave-bg, #1d2026)'; document.body.prepend(d);
        WaveSVG.render(d, JSON.parse(s), {cyclePx: 14}); window.scrollTo(0, 0); }""", wd)
    shots.settle(page)
    S.save('gaps-wavedrom', page.locator('#pic'))
    page.close()
    # the static SVG view of the page (its config: gaps)
    page = S.page(build / 'guides' / 'stream.html', height=1000)
    S.save('gaps-static', page.locator('.bench [data-mode=svg] svg').first)
    page.close()
    # stock WaveDrom on the exported WaveJSON
    vendor = ROOT / 'tests' / 'vendor'
    html = build / 'guides' / 'stock.html'
    html.write_text('<!doctype html><meta charset="utf-8"><body style="background:#fff;margin:0">'
                    f'<script src="{(vendor / "default.js").as_uri()}"></script><script src="{(vendor / "wavedrom.min.js").as_uri()}"></script>'
                    f'<div id="pic" style="display:inline-block;padding:10px"><script type="WaveDrom">{wd2}</script></div>'
                    '<script>WaveDrom.ProcessAll()</script>')
    page = S.b.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=1)
    page.goto(html.as_uri()); page.wait_for_load_state('networkidle'); shots.settle(page)
    S.save('gaps-stock', page.locator('#pic'))
    page.close()


# ---------------------------------------------------------------- the viewer guide
def viewer(S, ex, build):
    apb, axi_all, fsm_all = ex / 'apb' / 'apb.html', ex / 'axi_lite' / 'axi_lite_all.html', ex / 'fsm' / 'fsm_all.html'
    page = S.page(apb, height=1000, tips=True)
    shots.no_sva(page)
    v = shots.view(page)
    js = lambda e: shots.js(page, 0, e)   # noqa: E731
    S.quiet(page)
    S.save('viewer-overview', v)
    S.save('viewer-bar', v.locator('.bar'))
    S.save('viewer-notes', v.locator('.notes'))
    # the box of the keys (?)
    js('(v.help(true), 0)'); shots.settle(page)
    S.save('viewer-help', page.locator('.wv-help'))
    js('(v.help(false), 0)')
    # the cursor on an edge, the value tooltip of PADDR
    js("(v.select('PADDR'), v.cursor = 105000, v.draw(), 0)")
    bb, lay = v.locator('canvas').bounding_box(), js("(v.lay || []).map(o => [o.row.name, o.y, o.h])")
    y = next(o[1] + o[2] / 2 for o in lay if o[0] == 'PADDR')
    page.mouse.move(bb['x'] + bb['width'] * 0.55, bb['y'] + y)
    print('    the value tooltip of PADDR:', repr(v.locator('canvas').get_attribute('title')))
    v.locator('.bar button[data-act=next]').hover()
    page.locator('.wv-tip').wait_for(state='visible'); shots.settle(page)
    S.save('viewer-tip', clip=union(page.locator('.wv-tip').bounding_box(), v.locator('.bar').bounding_box()), page=page)
    page.add_style_tag(content='.wv-tip { display: none !important; }')   # no more tooltips in this page's shots
    S.quiet(page)
    # a measured range (ctrl+drag) on PADDR, then two cursors with an analog bus
    js("(v.setRange(45000, 105000, v.M.rows.find(r => r.name === 'PADDR')), v.select('PADDR'), 0)"); shots.settle(page)
    S.save('viewer-range', v, upto=v.locator('.notes'))
    js(f"(v.menu({bb['x'] + 640}, {bb['y'] + y}, v.M.rows.find(r => r.name === 'PADDR'), v.range), 0)"); shots.settle(page)
    S.save('viewer-menu', clip=union(page.locator('.wv-menu').bounding_box(), {'x': bb['x'] - 160, 'y': bb['y'], 'width': 900, 'height': 10}),
           page=page, pad=6)
    js('(v.closeMenu(), v.setRange(null), 0)')
    js("(v.select('PCLK'), v.cursor = 35000, v.setCursor2(115000), 0)"); shots.settle(page)
    S.save('viewer-cursors', v, upto=v.locator('.notes'))
    js("(v.setCycles({ cycles: true, cycleZero: v.cycData(true).ups[4] }), 0)"); shots.settle(page)   # the clock cycles: cycle 0 at the 5th edge
    S.save('viewer-cycles', v, upto=v.locator('.notes'))
    js("(v.setCycles(null), 0)")
    js("(v.setCursor2(null), v.setAnalog(v.M.rows.find(r => r.name === 'PADDR'), 3), v.setAnalog(v.M.rows.find(r => r.name === 'PWDATA'), 3), 0)")
    S.save('viewer-analog', v, upto=v.locator('.notes'))
    js("(v.setAnalog(v.M.rows.find(r => r.name === 'PADDR'), null), v.setAnalog(v.M.rows.find(r => r.name === 'PWDATA'), null), 0)")
    # radix: on the exact view (the dump's values): PWDATA in dec, PRDATA in ascii, rdata float
    v1 = shots.view(page, 1)
    shots.js(page, 1, "(v.setRadix(v.M.rows.find(r => r.name === 'PWDATA'), 'dec'), v.setRadix(v.M.rows.find(r => r.name === 'PRDATA'), 'bin'), "
                      "v.setRadix(v.M.rows.find(r => r.name === 'PADDR'), 'dec'), 0)")
    S.quiet(page)
    S.save('viewer-radix', v1)
    v.scroll_into_view_if_needed()
    # the edge kind "= value" and its field
    js("(v.setEdgeKind('value'), v.select('PADDR'), 0)")
    v.locator('.bar input.ev').fill('0x40')
    S.quiet(page)
    S.save('viewer-edges', v.locator('.bar'))
    js("(v.setEdgeKind('any'), 0)")
    # a selected run (shift+click a name) and the highlighted rows (ctrl+click)
    js("(v.selectRun(v.M.rows.find(r => r.name === 'PSEL'), v.M.rows.find(r => r.name === 'PWRITE')), 0)"); shots.settle(page)
    S.save('viewer-run', v, upto=v.locator('.notes'))
    js("(v.reset(), v.toggleHighlight('PADDR'), v.toggleHighlight('PWDATA'), v.toggleHighlight('PRDATA'), 0)"); shots.settle(page)
    S.save('viewer-highlight-rows', v, upto=v.locator('.notes'))
    js('(v.reset(), 0)')
    # themes: the same viewer in light, white and dark
    for th in ['light', 'white', 'dark']:
        page.evaluate(f"WaveFW.setTheme('{th}')"); shots.settle(page)
        S.save('theme-' + th, v, upto=v.locator('.notes'))
    page.evaluate("WaveFW.setTheme('dark')")
    page.close()

    # a generated page: hierarchy, module shading, highlight, find, paint
    page = S.page(axi_all, height=1500)
    shots.no_sva(page)
    v = shots.view(page)
    js = lambda e: shots.js(page, 0, e)   # noqa: E731
    js('(v.expandAll(), 0)')
    v.locator('.names .row.grp[title="axi_lite_tb.u_master"]').click()
    S.quiet(page)
    S.save('viewer-hierarchy', v)
    js('(v.expandAll(), 0)')
    js("(v.toggleHighlight('axi_lite_tb.u_master'), v.toggleHighlight('axi_lite_tb.u_slave'), 0)")
    S.quiet(page)
    S.save('viewer-highlight', v, clip=dict(v.bounding_box(), height=720))
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    v.locator('input.q').fill('awvd'); shots.settle(page)
    S.quiet(page)
    S.save('viewer-find', v, clip=dict(v.bounding_box(), height=720))
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    js("(v.setFindOpt('findRegex', true), 0)")
    v.locator('input.q').fill('^[aw].*valid$'); shots.settle(page)
    S.quiet(page)
    S.save('viewer-find-regex', v, clip=dict(v.bounding_box(), height=720))
    js("(v.paint('#f59f00'), 0)"); shots.settle(page)
    v.locator('canvas').focus(); page.keyboard.press('Escape'); js("(v.setFindOpt('findRegex', false), 0)")
    S.quiet(page)
    S.save('viewer-paint', v, clip=dict(v.bounding_box(), height=720))
    js('(v.unpaint(), 0)')
    page.close()

    # a packed struct as a row of fields
    page = S.page(fsm_all)
    shots.no_sva(page)
    v = shots.view(page)
    shots.js(page, 0, "(v.collapseAll(), Object.entries(v.M.groups).forEach(([id, g]) => ['fsm_tb', 'fsm_tb.status'].includes(g.path) && "
                      "v.collapsed.delete(+id)), v.cursor = 300000, v.renderNames(), v.draw(), 0)")
    S.quiet(page)
    S.save('viewer-struct', v)
    page.close()

    # sorting with ignored prefixes, the cursor fields (docs/index.html)
    page = S.page(ROOT / 'docs' / 'index.html')
    sv = page.locator('#ex-sort-view')
    sv.scroll_into_view_if_needed(); sv.locator('button[data-act=sort]').click()
    S.quiet(page)
    S.save('viewer-sort', sv)
    page.close()

    # a dump opened in the browser: wavefw/viewer.html, empty, then a VCD read
    page = S.page(ROOT / 'wavefw' / 'viewer.html', height=700)
    S.quiet(page)
    S.save('viewer-open-empty', page.locator('body'), clip={'x': 0, 'y': 0, 'width': 1280, 'height': 420}, page=page)
    vcd = ex / 'apb' / 'apb.vcd'
    inp = page.locator('.wv input.dfile').first
    inp.set_input_files(str(vcd))
    page.locator('.wv canvas').first.wait_for(); shots.settle(page)
    page.wait_for_timeout(300); shots.settle(page)
    S.quiet(page)
    page.evaluate('window.scrollTo(0, 0)')
    S.save('viewer-open-vcd', clip=dict(page.locator('.wv').first.bounding_box(), height=640), page=page)
    page.close()


# ---------------------------------------------------------------- the assertions guide
def sva(S, ex, build):
    apb = ex / 'apb' / 'apb.html'
    p0 = 'SVA.panels()[0]'
    page = S.page(apb, height=1200)
    v = shots.view(page)
    page.evaluate("(async () => { await SVA.ready(); })()")
    S.quiet(page)
    S.save('sva-page', v, upto=v.locator('.names'))
    # the panel open: the list of assertions
    page.evaluate(f"(() => {{ const p = {p0}; p.open = true; p.render(); }})()"); shots.settle(page)
    S.quiet(page)
    S.save('sva-panel', v.locator('.sva'))
    # one assertion on the waves, its failing attempt selected
    page.evaluate("(async () => { WaveFW.configure({svaShow: ['apb_demo_no_wait'], svaSignals: false}); await SVA.ready(); })()")
    page.evaluate(f"""(() => {{ const p = {p0}; p.open = false; p.render(); p.v.expandAll();
        const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait');
        p.select(b, b.results.assertions[0].attempts.findIndex(a => a.result === 'fail')); }})()""")
    shots.settle(page)
    S.quiet(page)
    S.save('sva-attempt', v, upto=v.locator('.notes'))
    # with the bound signals repeated in the group
    page.evaluate("(async () => { WaveFW.configure({svaShow: ['apb_demo_no_wait'], svaSignals: true}); await SVA.ready(); })()")
    shots.settle(page)
    S.quiet(page)
    S.save('sva-group', v.locator('.wrap, .body').first if v.locator('.wrap').count() else v, upto=v.locator('.notes'))
    # Why of the selected attempt
    page.evaluate(f"(() => {{ const p = {p0}; p.open = true; p.render(); }})()")
    page.evaluate(f"""(() => {{ const p = {p0}; const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait');
        p.select(b, b.results.assertions[0].attempts.findIndex(a => a.result === 'fail')); }})()""")
    page.locator('.wv .sva .svw table').first.wait_for(); shots.settle(page)
    S.quiet(page)
    S.save('sva-why', v.locator('.sva .svw'))
    # the table and the failures
    page.evaluate(f"(() => {{ const p = {p0}; p.unselect(); p.showTable = true; p.showFails = true; p.render(); }})()"); shots.settle(page)
    S.quiet(page)
    S.save('sva-table', v.locator('.sva .svr'))
    page.evaluate(f"(() => {{ const p = {p0}; p.showTable = false; p.showFails = false; p.render(); }})()")
    # ✎: the editor of an assertion
    li = v.locator('.sva li[data-a="apb_demo_no_wait"]')
    li.locator('button[data-sv=edit]').click(); shots.settle(page)
    S.quiet(page)
    S.save('sva-edit', li)
    li.locator('button[data-sv=noedit]').click()
    # Bind…: the instances where its signals are
    li = v.locator('.sva li[data-a="apb_setup_then_access"]')
    li.locator('button[data-sv=bind]').click(); shots.settle(page)
    S.quiet(page)
    S.save('sva-bind', li)
    page.evaluate("WaveFW.configure({svaShow: null, svaSignals: null})")
    # the expression field and a row ƒ (no assertion groups on the waves)
    page.evaluate("(async () => { WaveFW.configure({svaShow: []}); await SVA.ready(); })()")
    page.evaluate(f"(() => {{ const p = {p0}; p.open = false; p.render(); }})()")
    q = v.locator('input.svq')
    q.fill('PSEL && !PREADY'); v.locator('button[data-x=add]').click(); shots.settle(page)
    q.fill('@(posedge PCLK) $rose(PENABLE)'); v.locator('button[data-x=add]').click(); shots.settle(page)
    q.fill('PSEL && !PREADY'); q.press('Enter'); shots.settle(page)
    page.wait_for_timeout(200); shots.settle(page)
    S.quiet(page)
    S.save('sva-expr', v, upto=v.locator('.notes'))
    v.locator('button[data-x=del]').click(); q.fill('@(posedge PCLK) $rose(PENABLE)'); v.locator('button[data-x=del]').click()
    # the printable section of the page
    sec = page.locator('section.sva-report, #assertions, section:has(h2:text("Assertions"))').first
    S.quiet(page)
    S.save('sva-report', sec)
    page.close()


# ---------------------------------------------------------------- the WaveDrom guide
def wavedrom(S, ex, build):
    page = S.b.new_page(color_scheme='light', viewport={'width': 1280, 'height': 1000}, device_scale_factor=1)   # no IBM Plex there
    page.goto((ROOT / 'tests' / 'conformance.html').as_uri()); page.wait_for_load_state('networkidle'); shots.settle(page)
    S.quiet(page)
    S.save('wavedrom-conformance', page.locator('body'), clip={'x': 0, 'y': 0, 'width': 1280, 'height': 900}, page=page)
    page.close()
    apb = ex / 'apb' / 'apb.html'
    page = S.page(apb, height=1000)
    shots.no_sva(page)
    S.quiet(page)
    S.save('wavedrom-svg', page.locator('.bench [data-mode=svg] svg').first)
    v = shots.view(page, 1)
    S.save('wavedrom-exact', v, upto=v.locator('.notes'))
    # the viewer's export: Save as WaveDrom over the transfers, drawn by stock WaveDrom
    names = "['PCLK', 'PSEL', 'PENABLE', 'PWRITE', 'PADDR', 'PWDATA', 'PREADY']"
    wd = shots.js(page, 0, f"JSON.stringify(v.toWaveDrom(30000, 200000, v.rowsL.filter(r => {names}.includes(r.name))))")
    (pathlib.Path(S.out) / 'wavedrom-export.json').write_text(json.dumps(json.loads(wd), indent=1) + '\n')
    page.close()
    vendor = ROOT / 'tests' / 'vendor'
    html = build / 'guides' / 'stock-apb.html'
    html.parent.mkdir(parents=True, exist_ok=True)
    html.write_text('<!doctype html><meta charset="utf-8"><body style="background:#fff;margin:0">'
                    f'<script src="{(vendor / "default.js").as_uri()}"></script><script src="{(vendor / "wavedrom.min.js").as_uri()}"></script>'
                    f'<div id="pic" style="display:inline-block;padding:10px"><script type="WaveDrom">{wd}</script></div>'
                    '<script>WaveDrom.ProcessAll()</script>')
    page = S.b.new_page(viewport={'width': 1280, 'height': 900}, device_scale_factor=1)
    page.goto(html.as_uri()); page.wait_for_load_state('networkidle'); shots.settle(page)
    S.save('wavedrom-stock', page.locator('#pic'))
    page.close()


# ---------------------------------------------------------------- the guide from a dump to a page
def pages(S, ex, build):
    apb, axi, fsm = ex / 'apb' / 'apb.html', ex / 'axi_lite' / 'axi_lite.html', ex / 'fsm' / 'fsm.html'
    page = S.page(apb, height=900)
    shots.no_sva(page)
    S.quiet(page)
    S.save('pages-head', page.locator('body'), clip={'x': 0, 'y': 0, 'width': 1280, 'height': 560}, page=page)
    page.close()
    page = S.page(axi)
    shots.no_sva(page)
    v = shots.view(page)
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    S.quiet(page)
    S.save('pages-groups', v, upto=v.locator('.notes'))
    page.close()
    page = S.page(fsm)
    shots.no_sva(page)
    v = shots.view(page)
    S.quiet(page)
    S.save('pages-fsm', v, upto=v.locator('.notes'))
    page.close()
    page = S.page(ex / 'apb' / 'apb_all.html', height=1100)
    shots.no_sva(page)
    v = shots.view(page)
    shots.js(page, 0, '(v.expandAll(), 0)')
    S.quiet(page)
    S.save('pages-all', v)
    page.close()


# ---------------------------------------------------------------- the bus transactions guide
def buses(S, ex, build):
    axi, apb = ex / 'axi_lite' / 'axi_lite.html', ex / 'apb' / 'apb.html'
    page = S.page(axi, tips=True)
    shots.no_sva(page)
    v = shots.view(page)
    js = lambda e: shots.js(page, 0, e)   # noqa: E731
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    S.quiet(page)
    S.save('buses-folded', v, upto=v.locator('.notes'))
    js('(v.expandAll(), 0)')
    S.quiet(page)
    S.save('buses-open', v, upto=v.locator('.notes'))
    js("(p => (v.buses.select(p, p.D.tx[0]), 0))(v.buses.list()[0])"); shots.settle(page)
    S.quiet(page)
    S.save('buses-selected', v, upto=v.locator('.notes'))
    page.close()
    page = S.page(apb)
    shots.no_sva(page)
    v = shots.view(page)
    shots.js(page, 0, '(v.expandAll(), 0)')
    shots.js(page, 0, "(p => (p && v.buses.select(p, p.D.tx[2]), 0))(v.buses.list()[0])"); shots.settle(page)
    S.quiet(page)
    S.save('buses-apb', v, upto=v.locator('.notes'))
    page.close()


# ---------------------------------------------------------------- the AI agents guide: a page made by wave_page
def mcp(S, ex, build):
    d = build / 'guides'
    d.mkdir(parents=True, exist_ok=True)
    arg = {'dump': str(ex / 'apb' / 'apb.vcd'), 'signals': ['PCLK', 'PSEL', 'PENABLE', 'PWRITE', 'PADDR', 'PWDATA', 'PRDATA', 'PREADY', 'PSLVERR'],
           'from': '30ns', 'to': '200ns', 'out': str(d / 'mcp_page.html'), 'title': 'APB transfers (wave_page)'}
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'wavemcp.py'), '--call', 'wave_page', json.dumps(arg)], capture_output=True, text=True)
    print('   ', r.stdout.strip()[:200], r.stderr.strip()[:200])
    page = S.page(d / 'mcp_page.html')
    shots.no_sva(page)
    v = shots.view(page)
    S.quiet(page)
    S.save('mcp-page', v, upto=v.locator('.notes'))
    page.close()
    # the same page marked up by the agent (view_edit on its file: what a live page shows as it comes)
    ops = [{'op': 'bookmark', 't': 85, 'signal': 'PSEL', 'text': 'read of 0x04: SETUP'},
           {'op': 'bookmark', 't': 95, 'signal': 'PENABLE', 'text': 'ACCESS, but PREADY is low: the slave waits'},
           {'op': 'bookmark', 't': 115, 'signal': 'PREADY', 'text': 'PREADY: the read ends at the next edge (125 ns)'},
           {'op': 'arrow', 'from': 2, 'to': 3, 'label': '2 wait states', 'shape': '-|'},
           {'op': 'bookmark', 't': 155, 'signal': 'PSLVERR', 'text': 'write to an unmapped address: PSLVERR'},
           {'op': 'marker', 't': 125, 'label': 'read done', 'color': '#2f9e44'},
           {'op': 'group', 'name': 'handshake', 'signals': ['PSEL', 'PENABLE', 'PREADY', 'PSLVERR'], 'color': '#4dabf7'},
           {'op': 'highlight', 'add': ['handshake', 'PADDR', 'PRDATA']}, {'op': 'cursor', 't': 115}]
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'wavemcp.py'), '--call', 'view_edit',
                        json.dumps({'page': str(d / 'mcp_page.html'), 'ops': ops})], capture_output=True, text=True)
    print('   ', r.stdout.strip()[:300], r.stderr.strip()[:200])
    page = S.page(d / 'mcp_page.html')
    shots.no_sva(page)
    v = shots.view(page)
    S.quiet(page)
    S.save('mcp-markup', v)
    page.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', default=str(ROOT / 'out'), help='the Makefile BUILD directory (examples/<ex>/<ex>.html)')
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'guides' / 'img'))
    ap.add_argument('--only', help='comma-separated guides: ' + ' '.join(GUIDES))
    a = ap.parse_args()
    build = pathlib.Path(a.build).resolve()
    ex = build / 'examples'
    only = a.only.split(',') if a.only else GUIDES
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch(args=shots.RASTER)
        S = Shots(b, a.out, only)
        for g in only:
            print(g)
            globals()[g](S, ex, build)
        b.close()
    print(f'guide_shots: {S.n} pictures in {time.time() - t0:.1f} s -> {a.out}')
    if shots.errors:
        print('page errors:\n  ' + '\n  '.join(shots.errors))
        sys.exit(1)


if __name__ == '__main__':
    main()
