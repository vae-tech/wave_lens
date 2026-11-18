#!/usr/bin/env python3
"""guide_shots.py — the pictures of the guides (docs/guides/img/*.png), made the way tests/shots.py makes the README's.

Viewport 1280 px, device scale 1, dark theme unless a shot says otherwise, IBM Plex (shots.py stops without it), a fixed
sequence of calls per shot. Each shot belongs to a guide (--only viewer,gaps,…: those guides). The gaps guide reads a
dump made here: a stream with five rare packets in 10 µs and a slow heartbeat (BUILD/guides/stream.vcd, its config and
page); the others read the examples' pages (make examples demo first), wavelens/viewer.html, docs/index.html and
tests/conformance.html.

  python3 tests/guide_shots.py [--build out] [--out docs/guides/img] [--only gaps,sva]   (no -I: playwright)
"""
import argparse, json, os, pathlib, subprocess, sys, time
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shots  # noqa: E402  (its raster flags, the page opener, settle, js)

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUIDES = ['viewer', 'modules', 'compare', 'commands', 'gaps', 'sva', 'wavedrom', 'pages', 'types', 'buses', 'cocotb', 'mcp']

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

    def quiet(self, page):   # no focus ring, no hover, no toast of the step before
        page.evaluate("document.activeElement && document.activeElement.blur(), document.querySelectorAll('.wv .bar .toast').forEach(t => t.textContent = '')")
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
    js("(v.setGaps({gaps: true, gapView: true, gapIdle: 8, gapSignals: ['valid', 'ready']}), 0)")
    S.quiet(page)
    S.save('gaps-live', v, upto=v.locator('.notes'))
    js('(v.setGaps(null), 0)')
    S.quiet(page)
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
    menu = lambda y: js(f"(v.menu({bb['x'] + 260}, {y}, v.M.rows.find(r => r.name === 'valid')), 0)")
    menu(bb['y'] + 70)   # Gaps ▸ in the lower part of the menu: the menu put up so that its header is at the valid row
    dy = page.evaluate("(m => m.querySelector('.subh').getBoundingClientRect().top - m.getBoundingClientRect().top)(document.querySelector('.wv-menu'))")
    menu(max(4, bb['y'] + 100 - dy)); page.locator('.wv-menu .subh').hover(); shots.settle(page)
    S.save('gaps-menu', clip=union(page.locator('.wv-menu').bounding_box(), page.locator('.wv-menu .subh + .sub').bounding_box()), page=page, pad=6)
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
    # ⚙ (the right button on the bar opens it too) with Tools in the bar ▸ open; File ▾; the short form with the find's ⋯ open
    bar = v.locator('.bar').bounding_box()
    v.locator('.bar .pgear').click(); v.locator('.bar .wv-gear .subtg').click(); shots.settle(page)
    S.save('viewer-bar-tools', clip=union(v.locator('.bar .wv-gear').bounding_box(), v.locator('.bar .wv-gear .subtg + .sub').bounding_box(), bar), page=page, pad=6)
    js('(v.popClose(), 0)')
    v.locator('.bar .pfile').click(); shots.settle(page)
    S.save('viewer-bar-file', clip=union(v.locator('.bar .bpop[data-pop=file]').bounding_box(), bar), page=page, pad=6)
    js('(v.popClose(), 0)')
    js("(v.setToolsCompact(true), 0)"); shots.settle(page); shots.settle(page); S.quiet(page)
    v.locator('.bar .tg.find > .mx').click(); shots.settle(page)
    S.save('viewer-bar-compact', clip=union(v.locator('.bar').bounding_box(), v.locator('.bar .tg.find > .more').bounding_box()), page=page, pad=6)
    js('(v.popClose(), v.setToolsCompact(null), 0)'); shots.settle(page)
    # the cursor over the time axis, unlocked: 🔒 open, ⠿, the dashed outline; the top of the waves under it
    js('(v.stripLock(false), 0)'); shots.settle(page)
    cv = v.locator('canvas').bounding_box()
    S.save('viewer-strip', clip=union(v.locator('.bar .axs').bounding_box(), dict(cv, height=60)), page=page, pad=4)
    js('(v.stripLock(true), 0)'); shots.settle(page)
    # arranging: the mode, MARKS dragged before VIEW (held, then Esc: nothing kept)
    js('(v.arrange(true), 0)'); shots.settle(page)
    e, c = v.locator('.tg[data-tg=marks] > .tl').bounding_box(), v.locator('.tg[data-tg=view] > .tl').bounding_box()
    page.mouse.move(e['x'] + 6, e['y'] + e['height'] / 2); page.mouse.down(); page.mouse.move(c['x'] + 2, c['y'] + c['height'] / 2, steps=8); shots.settle(page)
    S.save('viewer-arrange', v.locator('.bar'))
    page.keyboard.press('Escape'); page.mouse.up(); js('(v.arrange(false), 0)'); shots.settle(page)
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
    # the texts of markers on the lines of signals
    js("""(v.run([{ op: 'marker', t: '60ns', label: 'setup done', signal: 'PENABLE' }, { op: 'marker', t: '100ns', label: 'data read', signal: 'PRDATA', lift: 'below',
        color: '#d6336c' }, { op: 'marker', t: '140ns', label: 'at the top' }]), 0)"""); shots.settle(page)
    S.save('viewer-marker-lines', v, upto=v.locator('.notes'))
    js("(v.run([{ op: 'marker', id: 'all', delete: true }]), 0)"); shots.settle(page)
    # a measured range (ctrl+drag) on PADDR, then two cursors with an analog bus
    js("(v.setRange(45000, 105000, v.M.rows.find(r => r.name === 'PADDR')), v.select('PADDR'), 0)"); shots.settle(page)
    S.save('viewer-range', v, upto=v.locator('.notes'))
    js(f"(v.menu({bb['x'] + 640}, {bb['y'] + y}, v.M.rows.find(r => r.name === 'PADDR'), v.range), 0)")
    page.locator('.wv-menu .subv').hover(); shots.settle(page)   # Show as ▸ open
    S.save('viewer-menu', clip=union(page.locator('.wv-menu').bounding_box(), page.locator('.wv-menu .subv + .sub').bounding_box(),
                                     {'x': bb['x'] - 160, 'y': bb['y'], 'width': 900, 'height': 10}),
           page=page, pad=6)
    js('(v.closeMenu(), v.setRange(null), 0)')
    js('(v.keyHintOn("g"), v.keyHintShow("g"), 0)'); shots.settle(page)
    S.save('viewer-keys', clip=page.locator('.wv-keys').bounding_box(), page=page, pad=6)
    js('(v.keyHintOff(), 0)')
    js("(v.select('PCLK'), v.cursor = 35000, v.setCursor2(115000), 0)"); shots.settle(page)
    S.save('viewer-cursors', v, upto=v.locator('.notes'))
    js("(v.setCycles({ cycles: true, cycleZero: v.cycData(true).ups[4] }), 0)"); shots.settle(page)   # the clock cycles: cycle 0 at the 5th edge
    S.save('viewer-cycles', v, upto=v.locator('.notes'))
    js("(v.setCycles(null), v.run([{ op: 'duplicate', signals: 'PADDR', bits: [7, 2] }]), v.cursor = 30000, v.setCursor2(150000), 0)"); shots.settle(page)
    S.save('viewer-slice', v, upto=v.locator('.notes'))
    js("(v.run([{ op: 'duplicate', signals: 'PADDR[7:2]', delete: true }]), v.cursor = 35000, v.setCursor2(115000), "
       "v.setCycles({ cycles: true, cycleZero: v.cycData(true).ups[4] }), 0)"); shots.settle(page)   # as the shots after it had it
    # the Δ of the markers in cycles, one over its bound (dmax) drawn red, the list saying so
    js("""(v.setCursor2(null), v.setCycles({ cycles: true }), v.run([{ op: 'marker', t: '45ns', label: 'req 1', color: '#d9822b' },
        { op: 'marker', t: '85ns', label: 'req 2', color: '#d9822b' }, { op: 'marker', t: '145ns', label: 'req 3', color: '#d9822b' },
        { op: 'deltas', on: true }, { op: 'deltas', dmax: '50ns' }]), 0)"""); shots.settle(page)
    S.save('viewer-measure', v)
    js("(v.run([{ op: 'marker', id: 'all', delete: true }, { op: 'deltas', on: false }]), 0)")
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
        page.evaluate(f"WaveLens.setTheme('{th}')"); shots.settle(page)
        S.save('theme-' + th, v, upto=v.locator('.notes'))
    page.evaluate("WaveLens.setTheme('dark')")
    page.evaluate("SVA.panels().forEach(p => { p.el.hidden = true; })")   # (shown again by the theme's redraw)
    # the scroll bar under the waves, its thumb held: the window's ends over it
    js("(v.reset(), v.zoomTo(60000, 120000), 0)"); shots.settle(page); S.quiet(page)
    th = v.locator('.hsb .hsbt').first.bounding_box()
    page.mouse.move(th['x'] + th['width'] / 2, th['y'] + th['height'] / 2); page.mouse.down(); shots.settle(page)
    cv, hb = v.locator('canvas').bounding_box(), v.locator('.hsb').first.bounding_box()
    S.save('viewer-scrollbar', clip={'x': v.bounding_box()['x'], 'y': cv['y'], 'width': v.bounding_box()['width'], 'height': hb['y'] + hb['height'] + 4 - cv['y']},
           page=page)
    page.mouse.up(); js("(v.zoomTo(v.M.t0, v.M.t1), 0)"); shots.settle(page)
    # b: a bookmark at the cursor on the selected signal, its label asked in a small box there
    js("(v.select('PSEL'), v.cursor = 85000, v.draw(), 0)"); v.locator('canvas').focus(); page.keyboard.press('b'); shots.settle(page)
    page.keyboard.type('SETUP'); shots.settle(page)
    box, cv = page.locator('.wv-ask').bounding_box(), v.locator('canvas').bounding_box()
    S.save('viewer-bookmark-label', clip={'x': cv['x'] - 170, 'y': box['y'] - 120, 'width': box['x'] + box['width'] + 24 - (cv['x'] - 170),
                                          'height': box['height'] + 200}, page=page)
    page.keyboard.press('Escape'); shots.settle(page)
    # your group renamed in place: a double-click (F2) on its name, the name in a box
    js("(v.run([{ op: 'group', name: 'handshake', signals: ['PSEL', 'PENABLE', 'PREADY'] }]), 0)"); shots.settle(page); S.quiet(page)
    n = v.locator('.names .row', has_text='handshake').first.bounding_box()
    js(f"(v.renameGroup('handshake', {n['x'] + 8}, {n['y'] + n['height'] + 2}), 0)"); shots.settle(page)
    page.keyboard.press('End'); page.keyboard.type(' (APB)'); shots.settle(page)
    S.save('viewer-group-rename', clip=union(page.locator('.wv-ask').bounding_box(), dict(v.locator('.names').bounding_box(), height=10),
                                             {'x': n['x'], 'y': n['y'] - 60, 'width': 620, 'height': 260}), page=page, pad=4)
    page.keyboard.press('Escape'); js("(v.run([{ op: 'group', name: 'handshake', delete: true }]), 0)"); shots.settle(page)
    page.close()

    # your order of the rows: alt+↑ on a signal of a module, twice; the toast says its place
    page = S.page(ex / 'apb' / 'apb_all.html', height=900)
    shots.no_sva(page)
    v = shots.view(page)
    js = lambda e: shots.js(page, 0, e)   # noqa: E731
    js("(v.setOnly({modules: ['apb_tb.u_regs'], open: ['apb_tb.u_regs']}), v.bodyEl.scrollTop = 0, v.draw(), 0)")
    js("(v.select(v.M.rows.find(r => r.type === 'sig' && r.full === 'apb_tb.u_regs.PRDATA')), 0)"); v.locator('canvas').focus()
    page.keyboard.press('Alt+ArrowUp'); page.keyboard.press('Alt+ArrowUp'); shots.settle(page)
    page.evaluate("document.activeElement && document.activeElement.blur()"); page.mouse.move(0, 0); shots.settle(page)
    print('    order:', js("JSON.stringify(v.order)"), js("v.root.querySelector('.toast')?.textContent"))
    v.evaluate('e => e.scrollIntoView()'); shots.settle(page)
    S.save('viewer-order', v, clip=dict(v.bounding_box(), height=560))
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
    # Mask: only the found rows (and the modules on the way to them); Select: the found signals selected, the menu takes them all
    js('(v.expandAll(), 0)')
    v.locator('input.q').fill('ready'); shots.settle(page)
    v.locator('button[data-act=fmask]').evaluate('b => b.click()')   # (behind the find's ⋯ in a tight strip); shots.settle(page)
    S.quiet(page)
    S.save('viewer-find-mask', v, clip=dict(v.bounding_box(), height=520))
    v.locator('button[data-act=fmask]').evaluate('b => b.click()')   # (behind the find's ⋯ in a tight strip); shots.settle(page)
    v.locator('button[data-act=fselect]').evaluate('b => b.click()'); shots.settle(page)
    cb = v.locator('canvas').bounding_box()
    y = js("(o => o ? o.y + o.h / 2 : 60)((v.lay || []).find(o => o.row === v.sel))")
    js(f"(v.menu({cb['x'] + 380}, {cb['y'] + y}, v.sel), 0)"); page.locator('.wv-menu .subg').hover(); shots.settle(page)   # New group of the N
    S.save('viewer-find-select', clip=union(page.locator('.wv-menu').bounding_box(), page.locator('.wv-menu .subg + .sub').bounding_box(),
                                            dict(v.bounding_box(), height=560)), page=page)
    js('(v.closeMenu(), 0)')
    v.locator('canvas').focus(); page.keyboard.press('Escape'); page.keyboard.press('Escape')
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

    # a dump opened in the browser: wavelens/viewer.html, empty, then a VCD read
    page = S.page(ROOT / 'wavelens' / 'viewer.html', height=700)
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


# ---------------------------------------------------------------- the Modules guide
def modules(S, ex, build):
    page = S.page(ex / 'axi_lite' / 'axi_lite_all.html', height=1100)
    shots.no_sva(page)
    v = shots.view(page)
    js = lambda e: shots.js(page, 0, e)   # noqa: E731
    node = lambda p: f"v.mods.nodes.get(v.scopeOf('{p}').id)"   # noqa: E731
    # the panel over the waves, the module of the selected signal (●) found in it
    js("(v.select(v.M.rows.find(r => r.type === 'sig' && r.tr && (r.full || '').startsWith('axi_lite_tb.u_slave.u_regfile.'))), v.modules(true, true), 0)")
    shots.settle(page); S.quiet(page)
    S.save('modules-panel', v, clip=dict(v.bounding_box(), height=640))
    # the filter: fuzzy, as the find
    page.locator('.wv-mods .mq').fill('regf'); shots.settle(page); S.quiet(page)
    S.save('modules-filter', page.locator('.wv-mods'), pad=4)
    page.locator('.wv-mods .mq').fill(''); shots.settle(page)
    # a click goes there: u_master opened, its first signal selected in the middle
    js("(v.collapseAll(), v.goScope('axi_lite_tb.u_master'), 0)"); shots.settle(page); S.quiet(page)
    S.save('modules-goto', v, clip=dict(v.bounding_box(), height=640))
    # Only u_slave: the testbench a header on the way to it, u_master gone
    js("(v.expandAll(), v.setOnly({modules: ['axi_lite_tb.u_slave'], open: ['axi_lite_tb.u_slave']}), v.bodyEl.scrollTop = 0, v.draw(), 0)")
    shots.settle(page); S.quiet(page)
    S.save('modules-only', v, clip=dict(v.bounding_box(), height=640))
    # the right button on a module of the tree
    mb = page.locator('.wv-mods').bounding_box()
    js(f"(v.mods.menu({node('axi_lite_tb.u_master')}, {mb['x'] + 150}, {mb['y'] + 150}), 0)"); shots.settle(page)
    S.save('modules-menu', clip=union(page.locator('.wv-menu').bounding_box(), mb), page=page, pad=6)
    js('(v.closeMenu(), 0)')
    # the find counts what Only leaves out; Only paused: every module again, the set kept (the panel closed: the bar in sight)
    js('(v.modules(false), 0)')
    v.locator('input.q').fill('awvalid'); shots.settle(page); S.quiet(page)
    S.save('modules-outside', v.locator('.bar'))
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    js("(v.setOnly({on: false}), 0)"); shots.settle(page); S.quiet(page)
    S.save('modules-paused', v.locator('.bar'))
    js('(v.setOnly(null), v.modules(false), 0)')
    page.close()


# ---------------------------------------------------------------- the compare guide
def b_dump(vcd):
    """Run B of the APB example: the data of the first read after 100 ns other, PREADY of the next one 10 ns later,
    PSLVERR left out (a signal B has not got)."""
    lines, ids = vcd.read_text().split('\n'), {}
    for ln in lines:
        w = ln.split()
        if ln.strip().startswith('$var') and len(w) > 4:
            ids.setdefault(w[4], w[3])
    err, rd, rdy = ids['PSLVERR'], ids['PRDATA'], ids['PREADY']
    out = [ln for ln in lines if not (ln.strip().startswith('$var') and ln.split()[3] == err) and ln not in ('0' + err, '1' + err)]
    t, data, k, moved = 0, None, None, None
    for i, ln in enumerate(out):
        if ln.startswith('#'):
            t = int(ln[1:])
        elif data is None and t > 100000 and ln.endswith(' ' + rd) and ln.startswith('b') and int(ln[1:].split()[0], 2):
            out[i], data = f'b{0xdeadbeef:b} {rd}', t
        elif k is None and data is not None and t > data and ln == '1' + rdy:
            k, moved = i, t
    out.pop(k)
    j = next(i for i in range(k, len(out)) if out[i].startswith('#') and int(out[i][1:]) >= moved + 10000)
    out.insert(j + 1, '1' + rdy)
    return '\n'.join(out), data, moved


def compare(S, ex, build):
    d = build / 'guides'
    d.mkdir(parents=True, exist_ok=True)
    text, data, moved = b_dump(ex / 'apb' / 'apb.vcd')
    (d / 'apb_b.vcd').write_text(text)
    page = S.page(ex / 'apb' / 'apb.html', height=1000)
    shots.no_sva(page)
    i = page.evaluate("WaveLens.views().findIndex(v => v.editKey() === 'exact')")
    v = shots.view(page, i)
    js = lambda e: shots.js(page, i, e)   # noqa: E731
    v.scroll_into_view_if_needed()
    v.locator('input.cfile').set_input_files(str(d / 'apb_b.vcd')); page.wait_for_timeout(400); shots.settle(page)   # picks B
    js("(v.zoomTo(40000, 200000), v.cursor = 40000, 0)"); shots.settle(page)
    # B picked, nothing compared: the bar's B: apb_b.vcd ✕ and Compare lit, its toast kept
    page.evaluate("document.activeElement && document.activeElement.blur()"); page.mouse.move(0, 0); shots.settle(page)
    S.save('compare-picked', clip=dict(v.bounding_box(), height=v.locator('canvas').bounding_box()['y'] - v.bounding_box()['y'] + 150), page=page)
    js("v.compareGo().then(() => 0)"); shots.settle(page); S.quiet(page)   # Compare (since 0.62 a pick compares nothing)
    got = js("v.cmp && [v.cmp.differ, v.cmp.missing, v.cmp.first]")
    print('    compare:', got, 'data at', data, 'PREADY moved at', moved)
    if not got or not got[0]:
        raise SystemExit(f'compare: nothing compared or no difference ({got}): the compare pictures would show none')
    S.save('compare-bands', v, upto=v.locator('.notes'))
    js("(v.select(null), v.diffStep(1), 0)"); shots.settle(page); S.quiet(page)
    S.save('compare-next', v, upto=v.locator('.notes'))
    js("(v.compareView('overlay', true), 0)"); shots.settle(page); S.quiet(page)
    S.save('compare-overlay', v, upto=v.locator('.notes'))
    js("(v.compareView('a', true), 0)"); shots.settle(page); S.quiet(page)
    S.save('compare-svg', picture(page, js("v.toSVG({from: 40000, to: 200000, width: 1180})")))
    page.evaluate("document.getElementById('pic')?.remove()")
    # the window compared: zoomed out, the time outside 40–200 ns shaded and Compare lit (the window moved since)
    js("(v.zoomTo(0, 205000), 0)"); shots.settle(page); S.quiet(page)
    print('    zoomed out:', js("[v.cmpStale(), v.root.querySelector('button[data-act=dcmpgo]').hidden]"))
    S.save('compare-window', v, upto=v.locator('.notes'))
    # the mask off (▒, gb) and B shown (d): B's values on the rows, nothing over them
    js("(v.zoomTo(40000, 200000), v.compareMask(false, true), 0)"); js("v.compareView('b', true).then(() => 0)"); shots.settle(page); S.quiet(page)
    S.save('compare-nomask', v, upto=v.locator('.notes'))
    js("(v.compareMask(true, true), 0)"); js("v.compareView('a', true).then(() => 0)")
    page.close()


# ---------------------------------------------------------------- the commands guide
def commands(S, ex, build):
    page = S.page(ex / 'apb' / 'apb.html', height=1000)
    shots.no_sva(page)
    i = page.evaluate("WaveLens.views().findIndex(v => v.editKey() === 'exact')")
    v = shots.view(page, i)
    js = lambda e: shots.js(page, i, e)   # noqa: E731
    v.scroll_into_view_if_needed()
    js("(v.zoomTo(40000, 200000), v.cursor = 40000, v.draw(), 0)"); shots.settle(page); S.quiet(page)
    S.save('commands-before', v, upto=v.locator('.notes'))
    ops = [{'op': 'bookmark', 't': '85ns', 'signal': 'PSEL', 'text': 'read of 0x04: SETUP'},
           {'op': 'bookmark', 't': '95ns', 'signal': 'PENABLE', 'text': 'ACCESS, PREADY low: the slave waits'},
           {'op': 'bookmark', 't': '115ns', 'signal': 'PREADY', 'text': 'PREADY: the read ends at the next edge'},
           {'op': 'arrow', 'from': 2, 'to': 3, 'label': '2 wait states', 'shape': '-|'},
           {'op': 'marker', 't': '125ns', 'label': 'read done', 'color': '#2f9e44'},
           {'op': 'group', 'name': 'handshake', 'signals': ['PSEL', 'PENABLE', 'PREADY'], 'color': '#4dabf7'},
           {'op': 'highlight', 'add': ['handshake', 'PRDATA']}, {'op': 'cursor', 't': '115ns'}]
    page.evaluate(f"(async () => {{ const v = WaveLens.views()[{i}]; window.__r = await v.run({json.dumps(ops)}); }})()")
    shots.settle(page); S.quiet(page)
    print('    run:', page.evaluate("JSON.stringify(window.__r).slice(0, 300)"))
    S.save('commands-after', v)
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
    S.save('sva-panel', v.locator('.sva:not(.xpanel)'))
    # one assertion on the waves, its failing attempt selected
    page.evaluate("(async () => { WaveLens.configure({svaShow: ['apb_demo_no_wait'], svaSignals: false}); await SVA.ready(); })()")
    page.evaluate(f"""(() => {{ const p = {p0}; p.open = false; p.render(); p.v.expandAll();
        const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait');
        p.select(b, b.results.assertions[0].attempts.findIndex(a => a.result === 'fail')); }})()""")
    shots.settle(page)
    S.quiet(page)
    S.save('sva-attempt', v, upto=v.locator('.notes'))
    # with the bound signals repeated in the group
    page.evaluate("(async () => { WaveLens.configure({svaShow: ['apb_demo_no_wait'], svaSignals: true}); await SVA.ready(); })()")
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
    # what $stable reads: apb_addr_stable's first attempt selected, the rings one cycle back on the step and on PADDR, PWRITE
    page.evaluate("(async () => { WaveLens.configure({svaShow: ['apb_addr_stable'], svaSignals: true}); await SVA.ready(); })()")
    page.evaluate(f"""(() => {{ const p = {p0}; p.open = false; p.render(); const b = p.bindings.find(b => b.assert === 'apb_addr_stable');
        p.select(b, 0); }})()""")
    shots.settle(page)
    S.quiet(page)
    S.save('sva-past', v, upto=v.locator('.notes'))
    # the floating editor (Edit the assertion… on its rows) over the waves of apb_demo_no_wait, its failure selected
    page.evaluate("(async () => { WaveLens.configure({svaShow: ['apb_demo_no_wait'], svaSignals: true}); await SVA.ready(); })()")
    page.evaluate(f"""(() => {{ const p = {p0}; const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait');
        p.select(b, b.results.assertions[0].attempts.findIndex(a => a.result === 'fail')); p.floatEdit('apb_demo_no_wait');
        const r = p.v.root.getBoundingClientRect(); p.floatAt(r.left + 420, r.top + 250); }})()""")
    shots.settle(page)
    S.quiet(page)
    S.save('sva-float', v, upto=v.locator('.notes'))
    page.evaluate(f"(() => {{ const p = {p0}; p.floatClose(); p.unselect(); p.open = true; p.render(); }})()"); shots.settle(page)
    # Bind…: the instances where its signals are
    li = v.locator('.sva li[data-a="apb_setup_then_access"]')
    li.locator('button[data-sv=bind]').click(); shots.settle(page)
    S.quiet(page)
    S.save('sva-bind', li)
    page.evaluate("WaveLens.configure({svaShow: null, svaSignals: null})")
    # the search: @PREADY is:fail typed in ⌕, Mask pressed, the failures listed; the waves with its group alone
    page.evaluate(f"(() => {{ const p = {p0}; p.open = true; p.showFails = true; p.render(); p.summary(); }})()")
    v.locator('.sva:not(.xpanel) input.svqf').fill('@PREADY is:fail')
    v.locator('.sva:not(.xpanel) [data-sv=qmask]').click(); page.wait_for_timeout(300); shots.settle(page)
    page.evaluate(f"(() => {{ const p = {p0}; const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait'); p.v.fold(b.draw.gid, false, true); p.v.draw(); }})()")
    shots.settle(page)
    S.quiet(page)
    S.save('sva-find', v, upto=v.locator('.notes'))
    page.evaluate(f"(() => {{ const p = {p0}; p.setFilter({{ query: '', mask: false }}); p.showFails = false; p.open = false; p.render(); }})()")
    # the list of expressions, their marks and a row ƒ (no assertion groups on the waves)
    page.evaluate("(async () => { WaveLens.configure({svaShow: []}); await SVA.ready(); })()")
    page.evaluate(f"(() => {{ const p = {p0}; p.open = false; p.render(); }})()")
    page.evaluate("""(async () => { const v = document.querySelector('.wv').waveView; await v.run([
      { op: 'expr', text: 'PSEL && !PREADY', label: 'wait' }, { op: 'expr', text: '@(posedge PCLK) $rose(PENABLE)', label: 'access', mark: 'line', row: true },
      { op: 'expr', text: 'PSEL && PENABLE && PREADY && PWRITE', label: 'write', mark: 'strip' }, { op: 'expr_go', id: 1, n: 3 }]); })()""")
    shots.settle(page); page.wait_for_timeout(200); shots.settle(page)
    v.locator('.bar [data-x=open]').click(); v.locator('.xpanel ol.xl > li').first.locator('[data-x=list]').click(); shots.settle(page)
    S.quiet(page)
    S.save('sva-expr', v, upto=v.locator('.notes'))
    v.locator('.xpanel ol.xl > li').first.locator('[data-x=list]').click()
    v.locator('.xpanel ol.xl > li').nth(1).locator('[data-x=edit]').click(); page.keyboard.press('Control+End'); page.keyboard.type(' && PSE'); page.wait_for_timeout(400); shots.settle(page)
    S.quiet(page)
    S.save('sva-expr-edit', v.locator('.xpanel'))
    v.locator('.xpanel [data-x=noedit]').click()
    # the waves cut to the matches of the first
    page.evaluate("""document.querySelector('.wv').waveView.run([{ op: 'gaps', idle: 1, keep: 0 }, { op: 'expr', id: 1, gap: true }])"""); shots.settle(page); page.wait_for_timeout(200); shots.settle(page)
    S.quiet(page)
    S.save('sva-expr-gap', v, upto=v.locator('.notes'))
    page.evaluate("document.querySelector('.wv').waveView.run([{ op: 'expr', id: 1, gap: false }, { op: 'gaps', reset: true }])"); shots.settle(page)
    page.evaluate("document.querySelector('.wv').waveView.run([{ op: 'expr', id: 'all', delete: true }])"); shots.settle(page)
    # the printable section of the page
    sec = page.locator('section.sva-report, #assertions, section:has(h2:text("Assertions"))').first
    S.quiet(page)
    S.save('sva-report', sec)
    page.close()
    sva_large(S, ex, build)


# a large dump's assertions by the CLI: a clock of 20 000 edges (1 ns), q high from 5 to 15 µs, st counting every 100 ns
def big_vcd():
    out = ['$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 8 " cnt [7:0] $end\n$var wire 1 # q $end\n'
           '$var wire 3 $ st [2:0] $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\nb0 "\n0#\nb0 $\n']
    for i in range(1, 20001):
        out.append(f'#{i}\n{i % 2}!\n' + (f'b{(i // 2) % 256:b} "\n' if i % 2 == 0 else '') + ('1#\n' if i == 5000 else '0#\n' if i == 15000 else '')
                   + (f'b{(i // 100) % 8:b} $\n' if i % 100 == 0 else ''))
    return ''.join(out)


def sva_large(S, ex, build):
    """sva-large: a large dump in a faked VS Code host — its FST read as it is needed (sva vcd --codes) and an assertion
    over a clock too busy to read whole (lazyWhole lowered to 15 000) evaluated by sva eval over the whole dump, the passes
    of the window in sight asked once it is narrow enough (the extension's svaEval: --cycle-runs --no-lane, --no-pass,
    --max-attempts, --from --to)."""
    import tempfile
    exe = next((p for p in (build / 'sva-target' / 'release' / 'sva', ROOT / 'bin' / 'linux-x86_64' / 'sva') if p.exists()), None)
    if exe is None:
        raise SystemExit('sva-large: no sva CLI (make sva-build, or bin/linux-x86_64/sva)')
    d = build / 'guides'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'big.vcd').write_text(big_vcd())
    subprocess.run([str(exe), 'fst', str(d / 'big.vcd'), '--no-types', '-q'], check=True)
    fst = d / 'big.fst'
    head = subprocess.run([str(exe), 'vcd', str(fst), '--header'], capture_output=True, text=True, check=True).stdout

    def codes(cs, win=None):
        flags = [x for k in ('from', 'to', 'lod', 'keep') if (win or {}).get(k) is not None for x in ('--' + k, str(int(win[k])))]
        return subprocess.run([str(exe), 'vcd', str(fst), '--codes', '-', *flags], input='\n'.join(cs), capture_output=True, text=True, check=True).stdout

    def sva_eval(req):   # vscode/extension.js svaEval
        t = pathlib.Path(tempfile.mkdtemp(dir=d)); out = t / 'results.json'
        args = [str(exe), 'eval', '--waves', str(fst), '--resolve', 'scope', '--cycle-runs', '--no-lane', '--out', str(out)]
        args += ['--scope', req['scope']] if req.get('scope') else []
        args += [x for a in req.get('asserts') or [] for x in ('--assert', a)] + (['--no-pass'] if req.get('passes') is False else [])
        args += [x for k, f in (('max', '--max-attempts'), ('from', '--from'), ('to', '--to')) if req.get(k) is not None
                 for x in (f, str(int(req[k])) + ('' if k == 'max' else 'ps'))]
        for i, f in enumerate(req['files']):
            (t / str(i)).mkdir(); (t / str(i) / f['name']).write_text(f['source']); args += ['--sva', str(t / str(i) / f['name'])]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode not in (0, 1):
            raise RuntimeError(r.stderr)
        return out.read_text()
    page = S.page(ex / 'apb' / 'apb.html', height=900)
    page.expose_function('bigCodes', codes)
    page.expose_function('bigEval', sva_eval)
    got = page.evaluate("""async head => { document.querySelectorAll('body > *').forEach(e => { if (e.tagName !== 'SCRIPT') e.hidden = true; });
      const a = document.createElement('div'); a.id = 'big'; document.body.prepend(a); a.style.cssText = 'padding:10px';
      await SVA.loadFiles([{ name: 'big.sv', text: 'module tb;\\n  // q high: st is never 2\\n  a_q: assert property (@(posedge clk) q |-> st != 3\\'d2);\\nendmodule\\n' }]);
      const doc = WaveLens.vcdToWave(head, { name: 'big.fst', lazy: true }).doc;
      const v = new WaveLens.WaveView(a, doc, { loadCodes: (c, w) => window.bigCodes(c, w), evalSva: req => window.bigEval(req), lazyKeep: 256,
        lazyBuckets: 512, lazyWhole: 15000, title: 'big.fst · a large dump in VS Code (a faked host)' });
      await SVA.ready(); await v.need(v.M.rows);
      const b = v.sva.bind('a_q', 'tb'); await v.sva.queue;
      const T = b.results.cycles; v.sva.open = true; v.sva.setFilter({ query: 'a_q' }); v.sva.render(); v.sva.reveal(b); v.sva.unselect();
      v.t0 = T[6100]; v.span = 300000; v.cursor = T[6100] + 150000; v.draw();
      for (let i = 0; i < 200 && !(b.cli && b.cli.win); i++) await new Promise(r => setTimeout(r, 50));
      v.draw(); window.scrollTo(0, 0);
      return [b.via, b.error, b.results.assertions[0].stats, !!(b.cli && b.cli.win)]; }""", head)
    print('    sva-large:', got)
    if got[0] != 'cli' or not got[3]:
        raise SystemExit(f'sva-large: not evaluated by the CLI, or no window asked: {got}')
    shots.settle(page); page.wait_for_timeout(200); shots.settle(page); S.quiet(page)
    S.save('sva-large', page.locator('#big'), upto=page.locator('#big .notes'))
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
    # the facts that change on every build frozen (review 2026-11-18 G-06): the time it was made, the version and the tree
    page.evaluate("""document.querySelectorAll('.facts > div').forEach(d => { const k = d.querySelector('b')?.textContent, t = d.lastChild;
        if (t && t.nodeType === 3 && (k === 'Generated' || k === 'WaveLens')) t.textContent = k === 'Generated' ? '2026-11-18 09:00' : '0.62'; })""")
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


# ---------------------------------------------------------------- the state names guide
def types(S, ex, build):
    # the FSM's VCD (no enum tables) with fsm.types.json beside it: the states and the struct's fields by path
    page = S.page(ex / 'fsm' / 'fsm_all.html', height=900)
    shots.no_sva(page)
    v = shots.view(page)
    shots.js(page, 0, "(v.cursor = 400000, v.draw(), 0)")
    S.quiet(page)
    S.save('types-fsm', v, upto=v.locator('.notes'))
    # the FSM panel (T) with Only FSMs: the two state buses and the modules on the way, the panel beside them
    shots.js(page, 0, "(v.collapseAll(), v.canvas.focus(), 0)")
    page.keyboard.press('Shift+T'); page.wait_for_timeout(200)
    page.locator('.wv-fsms button[data-a=only]').click(); page.wait_for_timeout(200)
    shots.js(page, 0, "(v.fsmP.el.style.left = (v.root.getBoundingClientRect().right - v.fsmP.el.offsetWidth - 16) + 'px', " +
             "v.fsmP.el.style.top = (v.root.getBoundingClientRect().top + 182) + 'px', v.fsmP.el.style.height = '196px', 0)")
    S.quiet(page)
    S.save('types-fsm-panel', v, upto=v.locator('.notes'))
    # an FSM's details: the diagram of u_rx.state (its states, the changes seen with their counts), START at the cursor
    shots.js(page, 0, "(v.setFsm(null), v.cursor = 50000, v.draw(), v.fsmP.el.style.height = '520px', " +
             "v.fsmP.detail(v.fsms().find(r => r.full === 'fsm_tb.u_rx.state'), 'graph'), 0)")
    S.quiet(page)
    S.save('types-fsm-graph', page.locator('.wv-fsms'))
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
    shots.js(page, 0, "(v.buses.txl.open = true, v.buses.txl.render(), v.buses.txl.mark(), 0)"); shots.settle(page)
    S.save('buses-list', v.locator('.txl'))
    page.close()


# ---------------------------------------------------------------- the AI agents guide: a page made by wave_page
def cocotb(S, ex, build):
    page = S.page(ex / 'cocotb_apb' / 'cocotb_apb.html')
    v = page.locator('section[data-view=run] .wv')
    S.quiet(page)
    S.save('cocotb-whole', v, upto=v.locator('.notes'))
    page.locator('.tests button').nth(5).click()
    v = page.locator('section[data-view=tc5] .wv')
    shots.settle(page)
    S.quiet(page)
    S.save('cocotb-test', v, upto=v.locator('.notes'))
    page.locator('.tests button').nth(3).click()   # the test with a wl.measure: its pair of markers, the Δ between them
    v = page.locator('section[data-view=tc3] .wv')
    shots.settle(page)
    S.quiet(page)
    S.save('cocotb-measure', page.locator('section[data-view=tc3]'))
    page.close()


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


# ---------------------------------------------------------------- a faked VS Code tab (the runs and the large dumps guides)
VSC = 'https://wavelens.test'


def sva_cli(build):
    """The sva CLI: BUILD's (make sva-build), else the one the extension carries (bin/linux-x86_64/sva, make dist)."""
    for exe in (build / 'sva-target' / 'release' / 'sva', ROOT / 'bin' / 'linux-x86_64' / 'sva'):
        if exe.exists():
            return exe
    raise SystemExit('guide_shots: no sva CLI (make sva-build, or bin/linux-x86_64/sva)')


class Tab:
    """The VS Code extension's tab as tests/smoke.py's vscode sections fake it: vscode/media/host.js before the viewer, and
    acquireVsCodeApi answered as vscode/extension.js answers — by the real sva CLI here: the dump served (an FST as its VCD
    text; lazy: its FST's header, then the signals shown by sva vcd --codes), assertions over a lazy dump by sva eval, the
    Runs panel by sva runs over a directory of runs (shown under the name shown_dir, as on a host). No CSP (the smoke
    checks it); the fonts from Google Fonts, as the examples' pages have them."""

    def __init__(self, S, build, dump, runs_dir=None, shown_dir='/home/me/apb/.wavelens-runs', lazy=False, note=None, config=None,
                 height=900, width=1280, scheme='dark', now_mtime=1794996000):
        import urllib.parse
        self.exe, self.dump, self.dir, self.shown_dir, self.lazy, self.note = sva_cli(build), pathlib.Path(dump), runs_dir, shown_dir, lazy, note
        self.tmp = build / 'guides' / 'tab'
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.files, self.n, self.fst, self.star, self.now_mtime, self.asked = {}, 0, None, False, now_mtime, []
        files = {'/host.js': ROOT / 'vscode' / 'media' / 'host.js'}
        files.update({'/media/' + f: ROOT / 'wavelens' / f for f in ('wavelens.css', 'wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js')})
        host = {'name': self.dump.name, 'path': '/home/me/apb/' + self.dump.name, 'store': {'wavelens.given': 'yes'}, 'autoReload': False,
                'keysLeft': ['ctrl+G'], 'config': config}
        scripts = ''.join(f'<script src="{VSC}/media/{f}"></script>' for f in ('wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js'))
        html = ('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" '
                'href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@400;600&display=swap">'
                f'<link rel="stylesheet" href="{VSC}/media/wavelens.css"></head><body class="vscode-{"light" if scheme == "light" else "dark"}">'
                f'<script type="application/json" id="wavelens-host">{json.dumps(host)}</script>'
                '<script type="application/wavedrom">{ "signal": [{ "name": "reading…", "wave": "x..." }] }</script>'
                f'<script src="{VSC}/host.js"></script>{scripts}</body></html>')
        fake = """(() => { window.__sent = [];
          const reply = m => setTimeout(() => window.postMessage(m, '*'), 0);
          const here = { save: m => ({ path: '/home/me/apb/' + m.name }), pick: () => ({ files: [] }), 'state-read': () => ({ error: 'none' }),
            compare: () => ({}), open: () => ({ ok: true }), sources: () => ({ texts: [] }), config: () => ({ config: null }), clip: () => ({ ok: true }),
            http: () => ({ status: 0 }), bytes: () => ({ error: 'the fake host serves every file by its URI' }) };
          window.acquireVsCodeApi = () => ({ getState() {}, setState() {}, postMessage(m) {
            window.__sent.push(m && m.type); if (!m || !m.id) return;
            const p = here[m.type] ? Promise.resolve(here[m.type](m)) : window.hostAsk(JSON.stringify(m)).then(JSON.parse);
            p.then(r => reply(Object.assign({ id: m.id }, r)), e => reply({ id: m.id, error: String(e && e.message || e) })); } }); })();"""
        page = S.b.new_page(color_scheme=scheme, viewport={'width': width, 'height': height})
        page.on('console', lambda m: shots.errors.append(f'tab: {m.text}') if m.type == 'error' and 'fonts.g' not in m.text else None)
        page.on('pageerror', lambda e: shots.errors.append(f'tab: {e}'))
        page.add_init_script(fake)
        page.expose_function('hostAsk', self.ask)

        def serve(r):
            path = urllib.parse.urlparse(r.request.url).path
            f = files.get(path) or self.files.get(path)
            r.fulfill(path=str(f)) if f else r.fulfill(status=404)
        page.route(VSC + '/**', serve)
        page.route(VSC + '/', lambda r: r.fulfill(body=html, content_type='text/html'))
        self.page = page
        page.goto(VSC + '/')
        self.until("window.__sent.includes('ready')", 60000)
        page.evaluate('document.fonts.ready')
        page.add_style_tag(content='.wv-tip { display: none !important; } .wv .bar .ver { display: none !important; }')
        shots.settle(page)

    def until(self, expr, timeout=20000):
        end = time.monotonic() + timeout / 1000
        while not self.js(expr):
            if time.monotonic() > end:
                raise SystemExit(f'guide_shots: not true in {timeout / 1000} s: {expr}')
            self.page.wait_for_timeout(50)

    def js(self, e):   # an expression over v, the tab's viewer
        return self.page.evaluate(f"(async () => {{ const v = window.WaveLens && WaveLens.views().find(x => x.root.isConnected); return {e}; }})()")

    def run(self, *args, input=''):
        return subprocess.run([str(self.exe), *map(str, args)], input=input, capture_output=True, text=True)

    def serve(self, file):   # -> its URI in the tab
        self.n += 1
        key = f'/f/{self.n}/{pathlib.Path(file).name}'
        self.files[key] = pathlib.Path(file)
        return VSC + key

    def src(self, file, name, lazy):   # the extension's srcOf -> {src, name, lazy}
        file = pathlib.Path(file)
        if lazy:
            fst = file
            if file.suffix != '.fst':
                fst = self.tmp / f'{file.stem}.{self.n}.fst'
                self.run('fst', file, '--no-types', '--quiet', '--out', fst).check_returncode()
            head = self.tmp / f'{fst.stem}.head.vcd'
            self.run('vcd', fst, '--header', '--out', head).check_returncode()
            self.fst = fst
            return {'src': self.serve(head), 'name': name, 'lazy': True}
        if file.suffix == '.fst':
            text = self.tmp / f'{file.stem}.{self.n}.vcd'
            self.run('vcd', file, '--out', text).check_returncode()
            file = text
        self.fst = None
        return {'src': self.serve(file), 'name': name, 'lazy': False}

    def ask(self, text):
        m = json.loads(text)
        self.asked.append(m['type'] + (' ' + m['op'] if m.get('op') else ''))
        try:
            r = getattr(self, 'on_' + m['type'].replace('-', '_'))(m)
        except Exception as e:   # noqa: BLE001  (the host's error, as the extension answers one)
            r = {'error': f'{type(e).__name__}: {e}'}
        return json.dumps(r)

    def on_source(self, m):
        r = self.src(self.dump, self.dump.name, self.lazy)
        return {**r, 'store': {'wavelens.given': 'yes'}, **({'note': self.note} if self.note else {})}

    def on_codes(self, m):
        if not self.fst:
            return {'error': 'this dump is read whole'}
        flags = [x for k in ('from', 'to', 'lod', 'keep') if m.get(k) is not None for x in ('--' + k, str(int(m[k])))]
        r = self.run('vcd', self.fst, '--codes', '-', *flags, input='\n'.join(map(str, m['codes'])))
        return {'text': r.stdout} if r.returncode == 0 else {'error': r.stderr.strip()}

    def on_sva(self, m):   # the extension's svaEval: sva eval over the dump's FST, the page's files
        import tempfile
        d = pathlib.Path(tempfile.mkdtemp(dir=self.tmp))
        out = d / 'results.json'
        args = ['eval', '--waves', self.fst, '--resolve', 'scope', '--cycle-runs', '--no-lane', '--out', out]
        args += ['--scope', m['scope']] if m.get('scope') else []
        args += ['--ignore-prefix', ','.join(m['ignore'])] if m.get('ignore') else []
        args += [x for a in m.get('asserts') or [] for x in ('--assert', a)] + (['--no-pass'] if m.get('passes') is False else [])
        args += [x for k, f in (('max', '--max-attempts'), ('from', '--from'), ('to', '--to')) if m.get(k) is not None
                 for x in (f, str(int(m[k])) + ('' if k == 'max' else 'ps'))]
        for i, f in enumerate(m['files']):
            (d / str(i)).mkdir()
            (d / str(i) / f['name']).write_text(f['source'])
            args += ['--sva', d / str(i) / f['name']]
        r = self.run(*args)
        return {'text': out.read_text()} if out.exists() else {'error': r.stderr.strip() or f'sva eval: exit {r.returncode}'}

    # the Runs panel (vscode/extension.js runs()): sva runs over self.dir
    def runs_json(self):
        return json.loads(self.run('runs', 'list', '--dir', self.dir, '--json').stdout)

    def on_runs(self, m):
        op, d = m['op'], self.dir
        said = ((['--name', m['name'].strip()] if (m.get('name') or '').strip() else []) +
                (['--tags', ','.join(m['tags'])] if isinstance(m.get('tags'), list) else []) +
                (['--comment', m['comment']] if isinstance(m.get('comment'), str) else []))
        dir_of = {'set': '.wavelens-runs' if self.star else '', 'scope': 'workspace' if self.star else ''}
        win = [f"{round(m['from'])}ps", f"{round(m['to'])}ps"] if m.get('from') is not None and m.get('to') is not None else None
        if op == 'list':
            r = json.loads(self.run('runs', 'list', self.dump, '--dir', d, '--json').stdout)
            return {'dir': self.shown_dir, 'dirOf': dir_of, 'runs': r.get('runs', []), 'others': r.get('others', 0),
                    'now': {'name': self.dump.name, 'mtime': self.now_mtime * 1000, 'bytes': self.dump.stat().st_size}, 'shown': 0}
        if op == 'dir':
            self.star = bool(m.get('keep'))
            return {'dir': self.shown_dir, 'dirOf': {'set': '.wavelens-runs' if self.star else '', 'scope': 'workspace' if self.star else ''}}
        if op == 'open':
            if not m.get('run'):
                return self.on_source(m)
            run = next((x for x in self.runs_json()['runs'] if x['id'] == m['run']), None)
            if not run:
                return {'error': f"no run #{m['run']}"}
            return self.src(pathlib.Path(d) / run['file'], f"#{run['id']} {run['name']}", self.lazy)
        if op == 'keep':
            src = self.dump
            if win and m.get('of'):
                src = pathlib.Path(d) / next(x for x in self.runs_json()['runs'] if x['id'] == m['of'])['file']
            r = self.run('runs', 'keep', src, '--dir', d, *said, *(['--from', win[0], '--to', win[1]] if win else []), '--json')
            if r.returncode:
                return {'error': r.stderr.strip()}
            fix_times(self.dir)
            return {'run': next(x for x in self.runs_json()['runs'] if x['id'] == json.loads(r.stdout)['id'])}
        if op == 'cut':
            return {'path': f"/home/me/apb/{self.dump.stem}.{win[0][:-2]}-{win[1][:-2]}ps.fst"}
        if op == 'set':
            r = self.run('runs', 'set', m['run'], '--dir', d, *said, '--json')
            return {'run': json.loads(r.stdout)} if r.returncode == 0 else {'error': r.stderr.strip()}
        if op == 'rm':
            return {'cancelled': True}
        if op in ('diff', 'compare'):
            args = ['runs', 'diff', self.dump, '--dir', d, '--against', m.get('against') or 'now', '--signals-from', '-']
            args += ['--json'] if op == 'diff' else ['--run', m.get('run') or 'now', '--page', '--quiet']
            args += [x for k in ('from', 'to') if m.get(k) is not None for x in ('--' + k, f'{round(m[k])}ps')]
            args += ['--case', m['case']] if m.get('case') else []
            r = self.run(*args, input='\n'.join(map(str, m.get('signals') or [])) + '\n')
            if r.returncode not in (0, 1):
                return {'error': r.stderr.strip()}
            out = json.loads(r.stdout)
            return out if op == 'diff' else {'result': out}
        if op == 'cancel':
            return {'ok': True}
        return {'error': 'no ' + op}

    def close(self):
        self.page.close()


def tab_clip(page, log=False):
    """The tab as it is in the window: the viewer from its bar down to its log line (sticky at the window's foot), the line
    itself with log (its last message; a read's says how long it took: a picture another on every run)."""
    return page.evaluate("""log => { const v = document.querySelector('.wv').getBoundingClientRect(), l = document.querySelector('.wv .wlog');
        const r = l && !l.hidden ? l.getBoundingClientRect() : null, b = r ? (log ? r.bottom : r.top) : Math.min(v.bottom, innerHeight);
        return { x: v.x, y: v.y, width: v.width, height: Math.min(b, innerHeight) - v.y }; }""", log)


def fix_times(runs_dir, day='2026-11-17'):
    """The runs' times fixed, so a picture is the same on every run: run k kept at 08:00 + k hours of that day."""
    f = pathlib.Path(runs_dir) / 'runs.json'
    j = json.loads(f.read_text())
    for r in j['runs']:
        r['kept'] = r['source_mtime'] = f"{day}T{8 + r['id']:02d}:{10 * r['id'] % 60:02d}:00Z"
    f.write_text(json.dumps(j, indent=2) + '\n')


def keep_run(build, dump, runs_dir, text, name, tags=(), comment=''):
    """A run kept from a dump's text, as Keep this dump… keeps it (the text written as the dump, the dump put back after)."""
    dump = pathlib.Path(dump)
    was = dump.read_bytes() if dump.exists() else None
    dump.write_text(text)
    r = subprocess.run([str(sva_cli(build)), 'runs', 'keep', str(dump), '--dir', str(runs_dir), '--name', name, '--tags', ','.join(tags),
                        '--comment', comment, '--json'], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'guide_shots: sva runs keep: {r.stderr}')
    if was is not None:
        dump.write_bytes(was)


# ---------------------------------------------------------------- the runs guide
# the Runs panel wider than its default, at the foot of the waves' left part (the differences at 115 ns and 155 ns in sight)
PLACE = ("(w => Object.assign(v.runsP.el.style, { width: '560px', height: '360px', left: (w.left + 8) + 'px', "
         "top: (Math.min(w.bottom, innerHeight - 30) - 366) + 'px' }))(v.wcol.getBoundingClientRect())")


def runs(S, ex, build):
    """The Runs panel of a VS Code tab of the APB example: three runs kept (golden and nightly: the example's dump; slave
    rework: run B of the compare guide), the dump of now the rework's."""
    import shutil
    d = build / 'guides' / 'runs'
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    a = (ex / 'apb' / 'apb.vcd').read_text()
    b = b_dump(ex / 'apb' / 'apb.vcd')[0]
    dump, rd = d / 'apb.vcd', d / '.wavelens-runs'
    keep_run(build, dump, rd, a, 'golden', ['base'], 'before the slave change')
    keep_run(build, dump, rd, a, 'nightly', ['ci'], 'the same RTL, run by CI')
    keep_run(build, dump, rd, b, 'slave rework', ['wip'], 'PREADY from the new slave FSM')
    fix_times(rd)
    dump.write_text(b)   # the dump of now: the simulation after the change
    T = Tab(S, build, dump, rd, height=780, width=1560)
    page, js = T.page, T.js
    v = page.locator('.wv').first
    # the modules folded but the top: the testbench's signals and the panel over the right of the waves
    js("(v.collapseAll(), v.fold(+Object.keys(v.M.groups).find(k => v.M.groups[k].name === 'apb_tb'), false), 0)")
    shot = lambda name, log=False: (shots.settle(page), S.quiet(page), S.save(name, page=page, clip=tab_clip(page, log)))   # noqa: E731
    panel = lambda name: (shots.settle(page), S.quiet(page), S.save(name, v.locator('.wv-runs')))   # noqa: E731
    js("(v.runsPanel(true), 0)")
    T.until("v.runsP && v.runsL && v.runsP.rowsEl.children.length === 4")
    js(f"({PLACE}, 0)")
    shot('runs-panel')
    # Keep this dump…: the form, filled (cancelled: nothing kept)
    v.locator('.wv-runs [data-a=keep]').click()
    v.locator('.wv-runs .rfn').fill('slave rework 2')
    v.locator('.wv-runs .rft').fill('wip, seed7')
    v.locator('.wv-runs .rfc').fill('PREADY one cycle earlier')
    panel('runs-keep')
    v.locator('.wv-runs [data-a=cancel]').click()
    # #1 golden picked as B: its B in a dashed box, Compare lit in the panel and the bar, nothing read
    v.locator('.wv-runs .rn[data-i="3"] .nm').click()
    T.until("v.runPickB === 1")
    shot('runs-picked')
    # Compare: A (now) with B (#1) over the window in sight
    js("(v.zoomTo(40000, 200000), 0)")
    v.locator('.wv-runs [data-a=go]').click()
    T.until("v.cmp && v.runCur === 1")
    shot('runs-compared', log=True)   # (its log line the compare's: no time of a read in it)
    # Δ all: every run against A over the same window
    v.locator('.wv-runs [data-a=all]').click()
    T.until("v.runsP.deltas.size >= 3")
    panel('runs-delta-all')
    # the Open mode: a row chosen opens its waves (A), nothing compared
    v.locator('.wv-runs [data-a=mopen]').click()
    v.locator('.wv-runs .rn[data-i="2"] .nm').click()
    T.until("v.runsA() === 2 && v.runsP && v.runsP.rowsEl.children.length === 4")
    shot('runs-open')
    # slices: the dump of now again, the range over the read at 115 ns kept as a slice from Range ▸ (the panel closed for the menu)
    v.locator('.wv-runs [data-a=mcmp]').click()
    js("v.runsShow(0).then(() => 0)")
    T.until("v.runsA() === 0 && v.runsP && v.runsP.rowsEl.children.length === 4 && v.M.rows.length > 20")
    js("(v.runsPanel(false), v.zoomTo(40000, 200000), v.setRange(110000, 130000, v.M.rows.find(r => r.name === 'PRDATA')), v.select('PRDATA'), 0)")
    shots.settle(page)
    bb = page.locator('.wv canvas').first.bounding_box()
    js(f"(v.menu({bb['x'] + 420}, {bb['y'] + 330}, v.M.rows.find(r => r.name === 'PRDATA'), v.range), 0)")
    page.locator('.wv-menu .subr').hover()
    shots.settle(page)
    S.save('runs-slice-menu', clip=union(page.locator('.wv-menu').bounding_box(), page.locator('.wv-menu .subr + .sub').bounding_box()), page=page, pad=6)
    page.locator('.wv-menu [data-m=slkeep]').click()
    T.until("v.runsL && v.runsL.length === 4 && v.runsP && v.runsP.rowsEl.children.length === 5")
    # golden shown (A), the slice's span on it: ↔ on the slice's row
    js("v.runsShow(1).then(() => 0)")
    T.until("v.runsA() === 1 && v.runsP && v.runsP.rowsEl.children.length === 5")
    js(f"({PLACE}, v.zoomTo(40000, 200000), 0)")
    v.locator('.wv-runs .rn[data-i="1"] [data-a=sp]').click()
    T.until("!!v.range")
    shot('runs-slice-span')
    # ★: this directory the permanent one (the setting wavelens.runsDir written)
    v.locator('.wv-runs [data-a=star]').click()
    T.until("v.runsP && v.runsP.el.querySelector('.rstar.on')")
    panel('runs-dir')
    print('    asked:', ', '.join(sorted(set(T.asked))))
    T.close()


# ---------------------------------------------------------------- the large dumps guide
SOC_CYC, SOC_N = 10000, 520000   # a 100 MHz clock for 5.2 ms: 1 040 000 changes, more than lazyWhole
SOC_SV = '''module bus_checks (input logic clk, rst_n, valid, ready);
    // why: a beat offered stays offered until the slave takes it
    a_hold: assert property (@(posedge clk) disable iff (!rst_n) valid && !ready |=> valid);
endmodule
'''


def soc_vcd(path):
    """A dump of a design's shape, busy enough to be read by the window: tb (clk, rst_n, irq), tb.u_bus (a valid / ready
    stream: a burst of 16 beats every 20 µs, a stall in every seventh, one beat dropped while stalled at 2.721 ms), tb.u_dma
    (a count of the beats), tb.u_cpu.core0 / core1 (a pc every 4 and 3 cycles: busy rows). The clock is aliased into the
    modules, as simulators write it."""
    sig = [('tb', 'clk', '!', 1), ('tb', 'rst_n', '"', 1), ('tb', 'irq', '#', 1),
           ('tb.u_bus', 'clk', '!', 1), ('tb.u_bus', 'rst_n', '"', 1), ('tb.u_bus', 'valid', '$', 1), ('tb.u_bus', 'ready', '%', 1),
           ('tb.u_bus', 'data', '&', 32), ('tb.u_bus', 'state', "'", 2),
           ('tb.u_dma', 'clk', '!', 1), ('tb.u_dma', 'count', '(', 16), ('tb.u_dma', 'done', ')', 1),
           ('tb.u_cpu', 'stall', '-', 1), ('tb.u_cpu.core0', 'pc', '*', 32), ('tb.u_cpu.core1', 'pc', '+', 32)]
    out = ['$timescale 1ps $end']
    scope = []
    for s, n, c, w in sig:
        want = s.split('.')
        while scope and scope != want[:len(scope)]:
            out.append('$upscope $end'); scope.pop()
        while len(scope) < len(want):
            scope.append(want[len(scope)]); out.append(f'$scope module {scope[-1]} $end')
        out.append(f'$var wire {w} {c} {n}' + (f' [{w - 1}:0]' if w > 1 else '') + ' $end')
    out += ['$upscope $end'] * len(scope) + ['$enddefinitions $end', '#0', '$dumpvars', '0!', '0"', '0#', '0$', '1%', 'b0 &', "b0 '", 'b0 (', '0)',
                                             '0-', 'b0 *', 'b0 +', '$end']
    ch = {}   # cycle -> the changes at its rising edge

    def at(c, line):
        ch.setdefault(c, []).append(line)
    at(5, '1"')
    count, word = 0, 0x1000
    for k, c0 in enumerate(range(100, SOC_N - 100, 2000)):
        stall = k % 7 == 3
        drop = k == 136   # (a stalled burst: k % 7 == 3)
        at(c0, "b1 '")
        c = c0
        for beat in range(16):
            word += 1
            at(c, '1$'); at(c, f'b{word:b} &')
            if stall and beat == 5:
                at(c, '0%'); c += 1
                if drop:
                    at(c, '0$')   # the beat dropped while the slave stalls: a_hold fails here
                    c += 1; at(c, '1$')
                at(c, '1%')
            count += 1
            at(c + 1, f'b{count:b} (')
            c += 1
        at(c, '0$'); at(c, "b10 '"); at(c, '1)')
        at(c + 1, '0)'); at(c + 1, "b0 '")
        at(c + 2, '1#'); at(c + 4, '0#')
        if k % 5 == 2:
            at(c + 6, '1-'); at(c + 30, '0-')
    with open(path, 'w') as f:
        f.write('\n'.join(out) + '\n')
        for c in range(1, SOC_N + 1):
            t = c * SOC_CYC
            f.write(f'#{t}\n1!\n')
            if c % 4 == 0:
                f.write(f'b{0x400000 + 4 * c:b} *\n')
            if c % 3 == 0:
                f.write(f'b{0x800000 + 4 * c:b} +\n')
            if c in ch:
                f.write('\n'.join(ch[c]) + '\n')
            f.write(f'#{t + SOC_CYC // 2}\n0!\n')
    return path


def large(S, ex, build):
    """A VS Code tab of a large dump: its FST's header first, then the rows shown by the window (sva vcd --codes), an
    assertion over the busy clock by sva eval; and a VCD read whole for want of the CLI (its note)."""
    d = build / 'guides' / 'large'
    d.mkdir(parents=True, exist_ok=True)
    dump = d / 'soc.vcd'
    if not dump.exists() or dump.stat().st_mtime < pathlib.Path(__file__).stat().st_mtime:
        soc_vcd(dump)
    T = Tab(S, build, dump, lazy=True, height=760, width=1280)
    page, js = T.page, T.js
    v = page.locator('.wv').first
    shot = lambda name: (shots.settle(page), S.quiet(page), S.save(name, page=page, clip=tab_clip(page)))   # noqa: E731
    read = "v.lazy && !WaveLens.internal.peek(v).vis.some(r => r.lazy) && !v.winAsk"
    T.until(read, 60000)
    shot('large-open')
    # the modules opened: their rows read, the busy ones (the clock, the pcs) as their summary; the cursor's values '…' there
    js("(['u_bus', 'u_cpu', 'core0', 'core1'].forEach(n => v.fold(+Object.keys(v.M.groups).find(k => v.M.groups[k].name === n), false)), "
       "v.cursor = 1000e6, v.select('tb.u_cpu.core0.pc'), v.draw(), 0)")
    T.until(read, 60000)
    shot('large-summary')
    # zoomed in on the dropped beat: the busy rows read again for the window, exact
    js("(v.zoomTo(2720.8e6, 2721.6e6), v.cursor = 2721.06e6, v.select('tb.u_bus.valid'), 0)")
    page.wait_for_timeout(400)
    T.until(read + " && !WaveLens.internal.peek(v).vis.some(r => r.full === 'tb.clk' && r.sum && !r.tr.length)", 60000)
    page.wait_for_timeout(300)
    shot('large-window')
    # an assertion over the busy clock: evaluated over the whole dump by sva eval (the extension's svaEval), its failure
    # selected, the passes of the time shown asked as a window
    page.evaluate("""async sv => { await SVA.ready(); await SVA.loadFiles([{ name: 'bus_checks.sv', text: sv }]);
        const p = SVA.panels()[0]; p.bind('a_hold', 'tb.u_bus'); await p.queue; }""", SOC_SV)
    T.until("(b => b && b.results && !b.running && b.cli && b.cli.win)(SVA.panels()[0].bindings.find(b => b.assert === 'a_hold'))", 120000)
    js("""(p => { const b = p.bindings.find(b => b.assert === 'a_hold'); p.open = true; p.render();
        p.select(b, b.results.assertions[0].attempts.findIndex(a => a.result === 'fail')); return 0; })(SVA.panels()[0])""")
    page.wait_for_timeout(400)
    shot('large-sva')
    li = page.locator('.wv .sva:not(.xpanel) li[data-a="a_hold"]').first
    li.evaluate("e => e.scrollIntoView({ block: 'center' })")   # (not under the bar, sticky at the window's top)
    S.quiet(page)
    S.save('large-sva-line', li)
    print('    asked:', ', '.join(sorted(set(T.asked))))
    T.close()
    # no sva on the host: the VCD read whole, the extension's note in the toast
    T = Tab(S, build, dump, lazy=False, height=400, width=1280,
            note='soc.vcd: read whole (not lazy): there is no sva CLI on this host (sva; none bundled for darwin-arm64): set wavelens.sva '
                 'to its path (WaveLens: Set the sva program…; the repository builds one: make dist)')
    T.until("!!v && v.root.querySelector('.bar .toast').textContent.includes('read whole')", 60000)
    shots.settle(T.page)
    T.page.mouse.move(0, 0)
    box = T.page.locator('.wv').first.bounding_box()
    S.save('large-nocli', page=T.page, clip={'x': box['x'], 'y': box['y'], 'width': box['width'], 'height': 52})
    T.close()


# ---------------------------------------------------------------- the keys guide
def keys(S, ex, build):
    """The boxes after z and ], and the right button's menu with Range ▸ open, on the APB example (the viewer guide has the
    box after g, the keys box, Show as ▸, the bar's menus)."""
    page = S.page(ex / 'apb' / 'apb.html', height=1000)
    shots.no_sva(page)
    v = shots.view(page)
    js = lambda e: shots.js(page, 0, e)   # noqa: E731
    S.quiet(page)
    for k, name in (('z', 'keys-z'), (']', 'keys-bracket')):
        js(f"(v.keyHintOn({json.dumps(k)}), v.keyHintShow({json.dumps(k)}), 0)"); shots.settle(page)
        S.save(name, clip=page.locator('.wv-keys').bounding_box(), page=page, pad=6)
        js('(v.keyHintOff(), 0)')
    bb = v.locator('canvas').bounding_box()
    js("(v.setRange(45000, 105000, v.M.rows.find(r => r.name === 'PADDR')), v.select('PADDR'), 0)"); shots.settle(page)
    js(f"(v.menu({bb['x'] + 300}, {bb['y'] + 200}, v.M.rows.find(r => r.name === 'PADDR'), v.range), 0)")
    page.locator('.wv-menu .subr').hover(); shots.settle(page)   # Range ▸ open
    S.save('keys-menu-range', clip=union(page.locator('.wv-menu').bounding_box(), page.locator('.wv-menu .subr + .sub').bounding_box()), page=page, pad=6)
    js('(v.closeMenu(), v.setRange(null), 0)')
    page.close()


GUIDES += ['runs', 'large', 'keys']   # the guides of these last sections (their own line: the list above is the other guides')


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
