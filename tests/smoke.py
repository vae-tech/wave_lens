#!/usr/bin/env python3
"""smoke.py — headless Chromium check of docs/index.html and tests/conformance.html (Python playwright).

For each page and colour scheme: no console errors / page errors / wavefw error boxes, every viewer has a
drawn canvas, and on docs/index.html the viewer interaction works (cursor click updates the value column, wheel
zoom changes the view span, Fit restores it, jump buttons move the cursor, group folding hides rows, a lazy
card builds its viewer when opened, Sort with ignored prefixes, settings layers, edge styles and radix). Pages built by
`make html` / `make demo-fst` / `make examples` (BUILD/demo.html, BUILD/demo_fst.html, BUILD/examples/<ex>/<ex>.html and
<ex>_all.html, work/dump.html, work/test_stream_video.html: scope hierarchy, folding, "same", bookmarks and arrows of the
examples, FSM state names) and BUILD/sva/spike.html (make sva-spike: the WebAssembly engine, evaluate() over a synthetic
32k-edge "tv" model in under a second) are checked too when they exist, and `sva eval` over the example dumps (only the
deliberate failures fail). Assertions in pages (wavefw/sva.js): the section of docs/index.html, the example pages (bound from
their configs; evaluated again in the page they give the native counts, also through the Web Worker), the binding flow on
apb_all.html (Load file…, Bind…, "cannot bind", drag and drop, several instances, reload, the JSON through a config and
mkhtml.py), wavefw/sva.wasm.js against the build, and the third-party checkers of tests/sva/third_party over the example
dumps. Full-page PNGs go to --out.

  python3 tests/smoke.py [--build /tmp/wavefw] [--out /tmp/wavefw/shots]   (no -I: playwright is usually a user-site install)
"""
import argparse, os, pathlib, re, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = [ROOT / 'docs' / 'index.html', ROOT / 'tests' / 'conformance.html']
BUILT = []   # pages from make html / make demo-fst, checked when they exist (set in main from --build)
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


def highlight(page):
    v = page.locator('#ex-hl-view')
    rows = v.locator('.names .row')
    n = lambda cls: v.locator(f'.names .row.{cls}').count()
    btn = v.locator('button[data-act=hl]')
    check(n('hl') == 4 and n('dim') == 5 and btn.is_visible() and btn.inner_text() == 'Highlight: 1 ✕',
          f'config highlight "tx": group + 3 members in front, 5 rows dimmed ({n("hl")}/{n("dim")}, {btn.inner_text()!r})')
    irq = rows.filter(has_text='irq')
    irq.hover(); irq.locator('.mk').click()
    colors = set(v.locator('.names .row.hl').evaluate_all("els => els.map(e => e.style.getPropertyValue('--hl'))"))
    check(n('hl') == 5 and len(colors) == 2, f'a second instance gets its own colour {sorted(colors)}')
    rows.filter(has_text='clk').locator('.n').click(modifiers=['Control'])
    check(n('hl') == 6 and btn.inner_text() == 'Highlight: 3 ✕', 'ctrl+click a name highlights it too')
    rx = v.locator('.names .row.grp', has_text='rx')
    rx.locator('.mk').click()
    check(n('dim') == 0 and rx.get_attribute('aria-expanded') == 'true', 'the mark on a group highlights it without folding it')
    rx.locator('.mk').click()
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    check(n('hl') == 0 and n('dim') == 0 and not btn.is_visible(), 'Esc clears the highlight')
    svg = page.evaluate("WaveFW.WaveSVG.toString(document.getElementById('ex-hl').textContent, {highlight: 'rx'})")
    check('opacity:0.3' in svg and 'var(--wave-hl1)' in svg, 'static SVG dims and tints from the highlight setting')
    page.evaluate("WaveFW.configure({highlight: ['state']})")
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    check(ex.locator('.names .row.hl').count() == 1 and v.locator('.names .row.hl').count() == 0,
          'configure({highlight}) picks in every viewer without its own setting')
    page.evaluate("WaveFW.configure({highlight: null})")
    check(ex.locator('.names .row.hl').count() == 0, 'highlight null clears it')


def cursor(page):
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.bench > div.wv[data-wave=\"DEMO_WAVES.exact\"]').waveView; return {e}; }})()")
    ct, cs = ex.locator('input.ct'), ex.locator('input.cs')
    ex.locator('select.cu').select_option('ns'); ct.fill('250'); ct.press('Enter')
    a = js('v.cursor'); ct.fill('1.2us'); ex.locator('button[data-act=cset]').click(); b = js('v.cursor')
    ct.fill('soon'); ct.press('Enter'); c = js('v.cursor')
    check((a, b, c) == (250000, 1200000, 1200000), f'cursor time field: 250 ns, 1.2us with its own unit, bad input refused ({a}, {b}, {c})')
    ex.locator('select.su').select_option('ns'); cs.fill('100'); ex.locator('button[data-act=cshow]').click()
    check(js('[v.span, v.t0]') == [100000, 1150000], f'span 100 ns + Show: the window around the cursor {js("[v.span, v.t0]")}')
    ex.locator('select.cu').select_option('µs')
    check(ct.input_value() == '1.2' and cs.input_value() == '100', f'another unit converts the shown cursor ({ct.input_value()} µs)')
    js('(v.zoom(4, 0.5), 0)'); ex.locator('canvas').evaluate('c => c.focus({ preventScroll: true })'); page.keyboard.press('c')
    check(abs(js('v.t0 + v.span / 2') - 1200000) < 1 and cs.input_value() == '400', f'key c centres the window on the cursor, span kept ({cs.input_value()} ns)')
    bm = page.locator('#ex-bm')
    bm.locator('input.ct').fill('5'); bm.locator('input.ct').press('Enter')
    check(bm.locator('.cyc').count() == 2 and page.evaluate("document.getElementById('ex-bm').waveView.cursor") == 5, 'cycle diagrams: the fields are in cycles')
    js('(v.fit(), v.cursor = 0, v.draw(), 0)')
    page.evaluate("(v => { v.cursor = 0; v.draw(); })(document.getElementById('ex-bm').waveView)")   # the next tests start at 0


def bookmarks(page):
    v = page.locator('#ex-bm')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.getElementById('ex-bm').waveView; return {e}; }})()")
    bl, al = v.locator('.notes ol.bms > li'), v.locator('.notes ol.ars > li')
    check(bl.count() == 3 and al.count() == 2 and v.locator('.notes').is_visible(), f'bookmarks and arrows from the JSON listed below the waves ({bl.count()}, {al.count()})')
    svg = page.locator('#ex-bm-svg svg').inner_html()
    check('request raised with data A1' in svg and '#1c7ed6' in svg, 'static SVG draws the legend, bookmark and arrow colours')
    rows = v.locator('.names .row:not(.lane)')
    n0 = rows.count()
    v.locator('button[data-act=collapse]').click()
    n1 = rows.count()
    v.locator('button[data-act=expand]').click()
    check(n1 == n0 - 3 and rows.count() == n0, f'Collapse / Expand fold and open every group ({n0} -> {n1} -> {n0})')
    lanes = v.locator('.names .row.lane')
    order = v.locator('.names .row').evaluate_all("els => els.map(e => e.classList.contains('lane') ? '|' : e.querySelector('.n').textContent.trim())")
    check(order == ['clk', '▾ bus', 'req', '|', 'ack', '|', 'data', 'irq'], f'arrow labels get lanes under the upper end of their arrows {order}')
    ly, ry = js("[v.bmGeo.mids[0][2], ...(o => [o.y, o.y + o.h])(v.lay.find(o => o.row.type === 'lane'))]"), None
    check(ly[1] <= ly[0] <= ly[2] and lanes.first.bounding_box()['height'] == 16, f'label 2T is drawn inside its 16 px lane ({ly})')
    page.evaluate("WaveFW.configure({laneHeight: 24})")
    h24 = lanes.first.bounding_box()['height']
    page.evaluate("WaveFW.configure({arrowLabels: 'overlay'})")
    check(h24 == 24 and lanes.count() == 0, f'laneHeight sets the lane height ({h24}); arrowLabels "overlay" removes the lanes')
    page.evaluate("WaveFW.configure({laneHeight: null, arrowLabels: null})")
    svg = page.locator('#ex-bm-svg svg').get_attribute('height')
    check(int(svg) == int(page.evaluate("WaveFW.WaveSVG.toString(document.getElementById('ex-bm-src').textContent, {arrowLabels: 'overlay'})").split('height="')[1].split('"')[0]) + 32, 'static SVG adds the same lanes (2 × 16 px)')
    v.locator('.names .row', has_text='req').locator('.n').click()
    check(v.locator('.names .row.sel').inner_text().startswith('req'), 'clicking a name selects the signal')
    v.locator('select.edge').select_option('rise')
    nxt, prv = v.locator('button[data-act=next]'), v.locator('button[data-act=prev]')
    nxt.click(); a = js('v.cursor'); nxt.click(); b = js('v.cursor'); prv.click(); c = js('v.cursor')
    check((a, b, c) == (2, 9, 2), f'▶ ▶ ◀ walk the rising edges of req (cursor {a}, {b}, {c})')
    v.locator('select.edge').select_option('fall'); nxt.click()
    check(js('v.cursor') == 6, f'falling edge of req at cycle 6 ({js("v.cursor")})')
    v.locator('button[data-act=mark]').click()
    b4 = bl.nth(3)
    check(bl.count() == 4 and b4.locator('.eg').inner_text() == '↓', f'+ Mark adds bookmark 4 on the falling edge ({b4.locator(".eg").inner_text()!r})')
    page.keyboard.type('req drops')
    tm = b4.locator('input.tm'); tm.fill('7'); tm.press('Enter')
    t7 = js('v.bms[3].t')
    b4.locator('input.tm').fill('soon'); b4.locator('input.tm').press('Enter')
    check(t7 == 7 and js('v.bms[3].t') == 7 and b4.locator('input.tm').input_value() == '7', f'the time field moves the bookmark ({t7}); bad input is refused')
    b4.locator('select.sig').select_option('irq')
    js('(v.cursor = 8, v.draw(), 0)'); b4.locator('button[data-bm=here]').click()
    check(js('[v.bms[3].signal, v.bms[3].t]') == ['irq', 8] and b4.locator('.eg').inner_text() == '↓', 'signal list and the cursor button change signal and time')
    b4.locator('input.col').fill('#2f9e44')
    check(js('v.bms[3].color') == '#2f9e44' and 'rgb(47, 158, 68)' in b4.locator('.bn').get_attribute('style').replace('#2f9e44', 'rgb(47, 158, 68)'), 'colour picker colours the bookmark')
    box = v.locator('canvas').bounding_box()
    pos = lambda n: js(f'v.bmGeo.pos.get({n})')
    rowy = lambda name: js(f"(o => o.y + o.h / 2)(v.lay.find(o => o.row.name === '{name}'))")
    xof = lambda t: js(f'({t} - v.t0) * v.canvas.getBoundingClientRect().width / v.span')
    p2 = pos(2); page.mouse.move(box['x'] + p2[0], box['y'] + p2[1]); page.mouse.down()
    page.mouse.move(box['x'] + xof(9.05), box['y'] + rowy('data'), steps=6); page.mouse.up()
    check(js('[v.bms[1].t, v.bms[1].signal]') == [9, 'bus.data'], f'dragging circle 2 moves it to another row and time, snapped to the edge ({js("[v.bms[1].t, v.bms[1].signal]")})')
    p1, p4 = pos(1), pos(4)
    page.keyboard.down('Shift'); page.mouse.move(box['x'] + p1[0], box['y'] + p1[1]); page.mouse.down()
    page.mouse.move(box['x'] + p4[0], box['y'] + p4[1], steps=6); page.mouse.up(); page.keyboard.up('Shift')
    check(al.count() == 3 and js('v.arrowList()[2]') == {'from': 1, 'to': 4, 'shape': '~'}, f'shift+drag from 1 to 4 draws an arrow ({js("v.arrowList()[2]")})')
    a3 = al.nth(2)
    a3.locator('select.shape').select_option('-|-'); a3.locator('select.head').select_option(''); a3.locator('select.line').select_option('dotted'); a3.locator('input.lab').fill('back')
    check(js('v.arrowList()[2]') == {'from': 1, 'to': 4, 'shape': '-|-', 'head': '', 'line': 'dotted', 'label': 'back'}, 'arrow shape, head, line and label')
    v.locator('button[data-bm=addar]').click()
    check(al.count() == 4 and js('v.arrowList()[3]') == {'from': 3, 'to': 4, 'shape': '~'}, '+ Arrow joins the last two bookmarks')
    b4.locator('button[data-bm=del]').click()
    check(bl.count() == 3 and al.count() == 2 and lanes.count() == 2, 'deleting a bookmark removes its arrows (and their lanes)')
    v.locator('.notes button[data-bm=json]').click()
    txt = v.locator('.notes textarea.json').input_value()
    check(txt.startswith('"bookmarks": [\n  {"n":1,') and '"arrows": [\n  {"from":1,"to":2,"shape":"-|-","label":"2T"}' in txt, 'JSON shows both lists for a config file')
    leg = page.evaluate("WaveFW.parse({signal: [{name: 'a', wave: '01'}], bookmarks: [{n: 1, t: 0}, {n: 2, t: 1, to: 1, label: 'x'}]}).arrows")
    check(leg == [{'from': 2, 'to': 1, 'shape': '~', 'head': '>', 'line': 'solid', 'color': None, 'label': 'x'}], 'an old bookmark "to" still becomes an arrow')
    o = rowy('ack'); v.locator('canvas').scroll_into_view_if_needed(); box = v.locator('canvas').bounding_box()
    page.mouse.click(box['x'] + box['width'] * 0.97, box['y'] + o)
    check(v.locator('.names .row.sel').inner_text().startswith('ack'), 'clicking a row on the waves selects that signal')
    v.locator('canvas').focus(); page.keyboard.press('ArrowDown')
    check(v.locator('.names .row.sel').inner_text().startswith('data'), 'ArrowDown moves the selection')
    page.keyboard.press('m')
    check(bl.count() == 4, 'key m bookmarks too')
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    ex.locator('.names .row', has_text='txd').locator('.n').click()
    ex.locator('select.edge').select_option('rise'); ex.locator('button[data-act=next]').click()
    check(ex.locator('.names .row.sel .v').inner_text() == '1', 'edge search on exact "tv" transitions')
    ex.locator('button[data-act=mark]').click()
    t = ex.locator('.notes ol.bms > li input.tm'); t.fill('250ns'); t.press('Enter')
    check(page.evaluate("document.querySelector('.bench > div.wv[data-wave=\"DEMO_WAVES.exact\"]').waveView.bms[0].t") == 250000, 'a time with a unit on a timed wave (250ns)')
    page.reload(); page.wait_for_timeout(300)
    check(bl.count() == 4 and al.count() == 2, 'bookmarks and arrows are kept in the browser over a reload')
    v.locator('.notes button[data-bm=clear]').click()
    check(bl.count() == 0 and not v.locator('.notes').is_visible(), 'Clear removes them')
    page.reload(); page.wait_for_timeout(300)
    check(bl.count() == 3 and al.count() == 2, "after a reload the page's own bookmarks are back")


def find(page):
    v = page.locator('.wv').first
    q, cnt = v.locator('input.q'), v.locator('.find .cnt')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    q.fill('pxvd'); page.wait_for_timeout(150)
    names = js("[...v.found.keys()].map(r => r.name)")
    sub = lambda n: re.search('p.*x.*v.*d', n) is not None
    check('s_pix_valid' in names and all(sub(n) for n in names) and cnt.inner_text() == f'{len(names)} found',
          f'fuzzy "pxvd": letters in order, not contiguous {sorted(set(names))} ({cnt.inner_text()})')
    marks = v.locator('.names .row .n b.fm').first.evaluate("b => b.closest('.n').innerHTML")
    check('<b class="fm">p</b>' in marks and '<b class="fm">v</b>' in marks, 'matched letters are marked in the names')
    folded = js("Object.keys(v.M.groups).length - v.collapsed.size")
    need = js("new Set([...v.found.keys()].flatMap(r => r.anc)).size")
    check(folded == need and v.locator('.names .row.hl').count() >= len(names) and v.locator('.names .row.dim').count() > 0,
          f'Open: only the {need} modules on the way to a match are open; Highlight: found rows in front')
    q.press('Enter'); sel = js('v.sel && v.sel.full'); q.press('Enter'); sel2 = js('v.sel && v.sel.full')
    check(sel and sel2 and sel != sel2 and cnt.inner_text().startswith('2 / '), f'Enter steps through the matches ({sel} -> {sel2})')
    nxt, prv = v.locator('button[data-act=fnext]'), v.locator('button[data-act=fprev]')
    nxt.click(); a1 = cnt.inner_text(); prv.click(); prv.click(); a2 = cnt.inner_text()
    v.locator('canvas').evaluate('c => c.focus({ preventScroll: true })')
    page.keyboard.press('n'); a3 = cnt.inner_text(); page.keyboard.press('Shift+N'); a4 = cnt.inner_text()
    check([a1, a2, a3, a4] == ['3 / 9', '1 / 9', '2 / 9', '1 / 9'], f'‹ › buttons and n / N (vim) step through the matches {[a1, a2, a3, a4]}')
    # each match lands in the middle of the waves (unless the scroll ends first)
    mid = []
    for _ in range(4):
        page.keyboard.press('n')
        mid.append(js("""(() => { const q = v.namesEl.querySelector('.row.sel').getBoundingClientRect(), own = v.root.classList.contains('wv-scroll'),
            box = own ? v.bodyEl.getBoundingClientRect() : { top: 0, bottom: innerHeight }, d = q.top + q.height / 2 - (box.top + v.hdrH + box.bottom) / 2,
            end = own ? (v.bodyEl.scrollTop <= 0 || v.bodyEl.scrollTop + v.bodyEl.clientHeight >= v.bodyEl.scrollHeight - 1) : (scrollY <= 0 || scrollY + innerHeight >= document.documentElement.scrollHeight - 1);
            return [Math.round(d), end]; })()"""))
    check(all(abs(d) <= 2 or end for d, end in mid) and sum(abs(d) <= 2 for d, _ in mid) >= 2, f'n: the match in the middle of the waves (offset px, at the scroll end) {mid}')
    q.fill('dev.fifo_s_val'); page.wait_for_timeout(150)
    fp = js("[...v.found.keys()].map(r => r.full)")
    check(fp and all('fifo_s_val' in p.rsplit('.', 1)[1] and 'dev' in p for p in fp), f'"a.b": a below a module path, b in the name {fp}')
    v.locator('input.fcol').fill('#2f9e44'); v.locator('button[data-act=fpaint]').click()
    painted = js("[...v.found.keys()].every(r => r.stroke === '#2f9e44')")
    check(painted and v.locator('button[data-act=funpaint]').is_visible(), 'Paint recolours the found signals')
    v.locator('button[data-act=fopen]').click()
    check(js('v.collapsed.size') < js("Object.keys(v.M.groups).length") - 5, 'Open off: the folding from before the search is back')
    v.locator('button[data-act=fopen]').click()
    page.evaluate("window.__c = null; navigator.clipboard.writeText = t => (window.__c = t, Promise.resolve())")
    v.locator('button[data-act=fcopy]').click()
    lines = (page.evaluate('window.__c') or '').split('\n')
    check(len(lines) == js('v.found.size') and all(l.startswith('tb_cxp_top.') for l in lines), f'Copy puts the full paths of the found rows on the clipboard ({len(lines)} lines)')
    q.press('Enter'); q.press('Enter')
    body = v.locator('.body')
    picked = js('v.sel && v.sel.full')
    js('(v.toggleHighlight("tb_cxp_top"), 0)')
    before = [js('v.collapsed.size'), body.evaluate('e => e.scrollTop'), js('v.t0')]
    q.press('Escape'); page.wait_for_timeout(100)
    after = [js('v.collapsed.size'), body.evaluate('e => e.scrollTop'), js('v.t0')]
    check(js('[v.found.size, v.picks.size, v.sel]') == [0, 0, None] and v.locator('.names .row.dim, .names .row.hl, .names .row.sel').count() == 0 and before == after,
          f'Esc resets search, highlight and selection; the view stays: folding, scroll, time ({after})')
    js('(v.toggleHighlight("tb_cxp_top"), 0)'); js(f'(v.select("{picked}"), 0)')
    v.locator('canvas').evaluate('c => c.focus({ preventScroll: true })'); page.keyboard.press('Escape')
    check(js('[v.picks.size, v.sel]') == [0, None] and v.locator('.names .row.hl').count() == 0, 'Esc on the waves clears highlighted and selected signals')
    v.locator('.names .row:not(.grp)').nth(2).locator('.n').click()
    focus, s1 = page.evaluate('document.activeElement.tagName'), js('v.sel && v.sel.name')
    page.keyboard.press('Escape')
    check(focus == 'CANVAS' and s1 and js('v.sel') is None, f'a click on a name gives the waves the keys: Esc right after it clears the selection ({s1})')
    page.evaluate('document.activeElement.blur()'); js(f'(v.select("{picked}"), 0)'); page.keyboard.press('Escape')
    check(js('v.sel') is None, 'Esc with the focus on the page resets the viewer used last')
    for key in ('Escape', 'Control+c'):   # on the waves (canvas focused) Esc and ctrl+C end the search too
        q.fill('pxvd'); page.wait_for_timeout(100)
        v.locator('canvas').evaluate('c => c.focus({ preventScroll: true })')
        page.evaluate('window.__c = null'); st = body.evaluate('e => e.scrollTop'); page.keyboard.press(key)
        check(js('v.found.size') == 0 and q.input_value() == '' and page.evaluate('window.__c') is None and body.evaluate('e => e.scrollTop') == st,
              f'{key} on the waves ends the search (view kept, nothing copied)')
    js(f'(v.select("{picked}"), 0)'); v.locator('canvas').evaluate('c => c.focus({ preventScroll: true })')
    page.keyboard.press('Control+c')
    check(page.evaluate('window.__c') == picked, f'without a search, ctrl+c on the waves copies the selected signal ({page.evaluate("window.__c")})')
    got = page.evaluate("""(() => { const rows = [...document.querySelectorAll('.wv .names .row[data-r]:not(.grp)')].slice(0, 3), r = document.createRange();
        r.setStartBefore(rows[0].querySelector('.n')); r.setEndAfter(rows[2].querySelector('.n')); getSelection().removeAllRanges(); getSelection().addRange(r);
        const dt = new DataTransfer(); document.querySelector('.wv .names').dispatchEvent(new ClipboardEvent('copy', { clipboardData: dt, bubbles: true, cancelable: true }));
        getSelection().removeAllRanges(); return [dt.getData('text/plain'), rows.map(e => e.querySelector('.n').title)]; })()""")
    check(got[0].split('\n') == got[1], f'selecting names and copying gives clean full paths {got[0].splitlines()}')
    v.locator('button[data-act=funpaint]').click()
    check(js("v.M.rows.every(r => !('stroke0' in r))") and not v.locator('button[data-act=funpaint]').is_visible(), 'Unpaint gives the signals their own colours back')


def hierarchy(page):
    v = page.locator('.wv').first
    grp = v.locator('.names .row.grp')
    check(grp.first.inner_text().strip().endswith('tb_cxp_top'), f'scopes are groups, top first ({grp.first.inner_text().strip()!r})')
    check(v.locator('.names .row.grp[aria-expanded=false]').count() > 0, 'fold: 2 starts deep scopes folded')
    late = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, seen = new Set(), bad = [];
        for (const r of v.vis) { const p = r.anc.length ? r.anc[r.anc.length - 1] : -1;
          if (r.type === 'group') seen.add(p); else if (r.type === 'sig' && seen.has(p)) bad.push(r.full); }
        return bad; })()""")
    check(late == [], f'groupOrder "last": in every module its signals come before its sub-modules {late[:3]}')
    check(v.locator('.names .row.alt').count() > 0 and page.evaluate("document.querySelector('.wv').waveView.band.size") > 0, 'moduleShading: alternate backgrounds per module')
    t = v.locator('.names .row:not(.grp) .n').nth(0).get_attribute('title')
    check(t and t.startswith('tb_cxp_top.'), f'names carry the full path as tooltip ({t})')
    dev = v.locator('.names .row.grp', has_text='cxp_device_top_i').first
    dev.hover(); dev.locator('.mk').click()
    covered = page.evaluate("(() => { const M = WaveFW.parse(WAVES.all); return M.rows.filter(r => r.type === 'sig' && r.full.startsWith('tb_cxp_top.cxp_device_top_i.')).length; })()")
    check(v.locator('.names .row.hl').count() > 10 and v.locator('.names .row.dim').count() > 10, f'highlighting the instance cxp_device_top_i ({covered} signals in it) dims the testbench rows')
    dev.locator('.mk').click()
    n0 = v.locator('.names .row').count()
    v.locator('button[data-act=collapse]').click()
    n1 = v.locator('.names .row').count()
    v.locator('button[data-act=expand]').click()
    n2 = v.locator('.names .row').count()
    check(n1 == 1 and n2 > n0, f'Collapse folds every instance, Expand opens all ({n0} -> {n1} -> {n2} rows)')
    same = page.evaluate("(() => { const M = WaveFW.parse(WAVES.all), s = M.rows.filter(r => r.src && r.src.same); return [s.length, s.filter(r => r.tr.length > 2).length]; })()")
    check(same[0] > 0 and same[0] == same[1], f'"same" signals take the transitions of their net ({same[1]}/{same[0]})')


def fst(page):
    v = page.locator('.wv').first
    st = v.locator('.names .row', has_text='state').first
    st.locator('.n').click()
    vals = []
    for _ in range(4):
        v.locator('button[data-act=next]').click(); vals.append(st.locator('.v').inner_text())
    check(vals == ['START', 'DATA', 'PARITY', 'IDLE'], f'FST enum table: FSM states by name {vals}')
    g = [x.strip() for x in v.locator('.names .row.grp').all_inner_texts()]
    check(g == ['▾ demo_tb', '▾ u_tx'], f'FST hierarchy as groups {g}')


EXAMPLES = {'apb': (6, 3), 'axi_lite': (5, 3), 'fsm': (4, 3)}   # bookmarks and arrows of the first view


def example(page, ex):
    v = page.locator('.wv').first
    bms, ars = EXAMPLES[ex]
    bl, al = v.locator('.notes ol.bms > li'), v.locator('.notes ol.ars > li')
    check(bl.count() == bms and al.count() == ars, f'{ex}: the bookmarks and arrows of the config are listed ({bl.count()}/{bms}, {al.count()}/{ars})')
    check(v.locator('.names .row.lane').count() > 0, f'{ex}: arrow labels have their lanes')
    if ex == 'axi_lite':
        check(v.locator('.names .row.grp.hl').count() == 3 and v.locator('.names .row.dim').count() > 0, 'axi_lite: highlight of the write channels from the config')
        col = lambda n: v.locator('.names .row:not(.sva-g):not(.sva-step):not(.sva-copy)', has_text=n).first.locator('.n').evaluate('e => getComputedStyle(e).color')
        check([col('AWVALID'), col('WDATA'), col('RRESP')] == ['rgb(51, 154, 240)', 'rgb(55, 178, 77)', 'rgb(16, 152, 173)'],
              f'axi_lite: groupColors give every channel its colour ({col("AWVALID")}, {col("WDATA")}, {col("RRESP")})')
        svg = page.evaluate("""WaveFW.WaveSVG.toString({signal: [['g', {name: 'a', wave: '01'}, {name: 'b', wave: '10', color: '#ff0000'}], {name: 'c', wave: '01'}]},
            {groupColors: {g: '#00ff00'}})""")
        check(svg.count('#00ff00') >= 2 and '#ff0000' in svg, 'groupColors in the static SVG; a signal with its own colour keeps it')
    if ex == 'fsm':
        st = v.locator('.names .row', has_text='state').first
        st.locator('.n').click()
        vals = []
        for _ in range(4):
            v.locator('button[data-act=next]').click(); vals.append(st.locator('.v').inner_text())
        check(vals == ['START', 'DATA', 'STOP', 'IDLE'], f'fsm: state names in the value column {vals}')


def fsm_vcd(page):
    v = page.locator('.wv').first
    st = v.locator('.names .row:not(.grp)', has_text='state').first
    st.locator('.n').click()
    v.locator('button[data-act=next]').click()
    check(st.locator('.v').inner_text() == 'START', f'fsm_all (VCD + mkconfig --sv): state names from the SV package ({st.locator(".v").inner_text()})')


def deep(page):
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    check(js('Math.max(...v.M.rows.map(r => r.depth))') >= 8 and js('Object.keys(v.M.groups).length') > 200, 'every level of the hierarchy is on the page')
    js('(v.expandAll(), 0)')
    n, H, hc, ch = js('[v.vis.length, v.lay.H, v.hc, v.canvas.getBoundingClientRect().height]')
    check(n > 1700 and H > 32767 and hc == ch and hc < 1000, f'Expand: {n} rows, {H} px of rows, canvas only {ch:.0f} px (the visible part)')
    page.locator('.wv .body').first.evaluate('e => e.scrollTop = 20000'); page.wait_for_timeout(150)
    oy = js('v.oy')
    row = js(f"v.lay.find(o => o.row.type === 'sig' && o.y > {oy} + 100).row.full")
    check(oy == 20000 and js("document.querySelector('.wv canvas').getBoundingClientRect().top - document.querySelector('.wv .body').getBoundingClientRect().top") == 0,
          f'rows scroll under a canvas that stays in view (offset {oy}, first row {row})')
    js('(v.collapseAll(), 0)')


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


def sva_docs(page):
    v = page.locator('#ex-sva')
    page.evaluate('SVA.ready()')
    got = page.evaluate("document.querySelector('#ex-sva').waveView.sva.bindings.map(b => [b.assert, b.scope, b.state, b.results && b.results.assertions[0].attempts.map(a => [a.start, a.end, a.result])])")
    want = [['a_req_ack', '', 'bound', [[2, 3, 'pass'], [6, 9, 'fail'], [11, 13, 'pass']]], ['c_req', '', 'bound', [[2, 3, 'pass']]]]
    check(got == want, f'docs: the assertion bound in the WaveJSON is evaluated in the page {got}')
    shown = page.evaluate("SVA.panels().filter(p => !p.el.hidden).map(p => p.v.root.id)")
    check(shown == ['ex-sva', 'ex-apb'] and page.locator('.wv .tg.sv button[data-sv=load]').count() == page.locator('.wv').count(),
          f'docs: only the viewers with assertions list them ({shown}); every viewer has Load file…')
    apb = page.evaluate("(() => { const v = document.querySelector('#ex-apb').waveView; return [v.sva.bindings.filter(b => b.state === 'bound' && b.results).length, v.vis.filter(r => r.sva).length]; })()")
    leg = page.locator('#ex-apb-svg svg').inner_html() if page.locator('#ex-apb-svg svg').count() else ''
    check(apb == [14, 14] and '(!PREADY)[*2]  (cons)' in leg and '##1 PREADY  (cons)' in leg and '(ante)' in leg,
          f'docs: the APB example with its 14 checks bound and drawn {apb}; the SVG of apb_read_waits with the legend of its steps')
    v.locator('li[data-a="a_req_ack"] button[data-sv=fail]').click()
    check('cycle 7.00' in v.locator('.cur').inner_text() and 'no ack within [1:3]' in v.locator('.bar .toast').inner_text() and 'attempt 2: fail' in v.locator('li[data-a="a_req_ack"]').inner_text(),
          f'docs: Go to first failure selects the attempt, the cursor at its start ({v.locator(".cur").inner_text()}, {v.locator(".bar .toast").inner_text()})')
    page.keyboard.press('Escape')
    rows = page.evaluate("document.querySelector('#ex-sva').waveView.vis.filter(r => r.cls).map(r => [r.cls, r.name])")
    check(rows[:4] == [['sva-g fails', '⚑ a_req_ack · 2 pass · 1 fail'], ['sva-lane', 'attempts'], ['sva-step', '1. req'], ['sva-step', '2. ##[1:3] ack']]
          and [r[1] for r in rows if r[0] == 'sva-copy'][:4] == ['clk', 'rst_n', 'req', 'ack'], f'docs: the assertion group under the top: lane, steps, the bound signals {rows[:6]}')
    svg = page.locator('#ex-sva-svg svg')
    txt = svg.inner_html() if svg.count() else ''
    check('⚑ a_req_ack · 2 pass · 1 fail' in txt and '##[1:3] ack  (cons)' in txt and 'no ack within [1:3]' in txt and '>1T<' in txt,
          'docs: the static SVG of the same JSON, evaluated in the page: the group, the arrows with their labels, the legend of the steps')


def sva_units(page):
    """wavefw/sva.js on hand-made models: scopes, the name rules, samplers."""
    r = page.evaluate("""(() => {
      const tv = (...p) => p.map(([t, v]) => [t, v]);
      const M = WaveFW.parse({ signal: [['tb', { name: 'clk', path: 'tb.clk', tv: tv([0, '0'], [5, '1'], [10, '0'], [15, '1']) },
        ['dut', { name: 'VALID', path: 'tb.dut.s_valid', tv: tv([0, '0']) }, { name: 'data', path: 'tb.dut.data', width: 8, tv: tv([0, '00'], [7, 'ab']) },
          { name: 'ready', path: 'tb.dut.ready', tv: tv([0, '1']) }, ['u_fifo', { name: 'full', path: 'tb.dut.u_fifo.full', tv: tv([0, '0']) }]]]] });
      const v = { M, sortIgnore: ['s_', 'i_'] }, I = SVA.scopeInfo(M);
      const a = { signals: [{ name: 'clk' }, { name: 'valid' }, { name: 'u_fifo.full' }, { name: 'data', width: 16 }, { name: 'VALID' }] };
      const res = SVA.resolve(v, a, 'tb.dut');
      const map = Object.fromEntries(Object.entries(res.map).map(([n, r]) => [n, r.full]));
      const cand = SVA.candidates(v, { signals: [{ name: 'clk' }, { name: 'ready' }] });
      const strict = SVA.resolve({ M, sortIgnore: [] }, { signals: [{ name: 'clk' }, { name: 'valid' }] }, 'tb.dut');
      const W = WaveFW.parse({ signal: [{ name: 'clk', wave: 'p...' }, { name: 'st', wave: '3.4.', data: ['IDLE', 'RUN'], enum: { 0: 'IDLE', 1: 'RUN' } },
        { name: 'b', wave: '01x0' }], time: { t0: 0, cycle: 10 } });
      const rows = Object.fromEntries(W.rows.map(r => [r.name, r])), ws = SVA.rowSampler(rows);
      const ts = SVA.tvSampler({ a: { tv: tv([0, '0'], [10, '1'], [20, 'x'], [30, '1']) }, d: { tv: tv([0, 'ff']), width: 8 } });
      return { root: I.root, scopes: I.scopes, ok: res.ok, map, notes: res.notes, errors: res.errors, missing: res.missing, cand,
        strict: strict.missing, wedges: ws.edges('clk', 'posedge'), wneg: ws.edges('clk', 'negedge'), wcol: ws.column('st', [10, 20, 30]), wb: ws.column('b', [10, 20, 30]),
        tedges: ts.edges('a', 'posedge'), tany: ts.edges('a', 'edge'), tb: [ts.before('a', 10), ts.before('a', 11), ts.before('d', 5), ts.before('nope', 5)] };
    })()""")
    check(r['root'] == '' and r['scopes'] == ['tb', 'tb.dut', 'tb.dut.u_fifo'], f'sva.js: the modules of a --hierarchy model are scopes {r["scopes"]}')
    check(r['map'] == {'clk': 'tb.clk', 'valid': 'tb.dut.s_valid', 'u_fifo.full': 'tb.dut.u_fifo.full', 'data': 'tb.dut.data', 'VALID': 'tb.dut.s_valid'}
          and not r['missing'], f'sva.js: names resolve exactly, by prefix, below the scope, by alias, the clock from above {r["map"]}')
    check(r['notes'] == ['clk → tb.clk (the clock, above the scope)', 'valid → tb.dut.s_valid (prefixes s_ i_ ignored)', 'VALID → tb.dut.s_valid (shown as VALID)']
          and r['errors'] == ['data: a select needs 16 bits, tb.dut.data has 8'] and r['ok'] is False, f'sva.js: the mappings are reported, a too wide select is a bind error {r["notes"]} {r["errors"]}')
    check(r['cand'] == ['tb.dut'] and r['strict'] == ['valid'], f'sva.js: candidates {r["cand"]}; without the prefix setting valid is missing {r["strict"]}')
    check(r['wedges'] == [10, 20, 30] and r['wneg'] == [5, 15, 25, 35] and r['wcol'] == [0, 0, 1] and r['wb'] == ['0', '1', 'x'],
          f'sva.js: rows of a clock-sampled view: edges (the first cell is no edge), enum labels read back {r["wedges"]} {r["wneg"]} {r["wcol"]} {r["wb"]}')
    check(r['tedges'] == [10, 30] and r['tany'] == [10, 30] and r['tb'] == ['0', '1', 'hff', None], f'sva.js: tvSampler edges (x → 1 is a rising edge) and values {r["tedges"]} {r["tany"]} {r["tb"]}')
    # the labels of a clock-sampled view read back (vcd2wavedrom's label(): the row's radix), and "raw" next to them
    lb = page.evaluate("""[SVA.fromLabel('0x1F'), SVA.fromLabel('0101', 'bin'), SVA.fromLabel('-3', 'signed', 8), SVA.fromLabel('0o17'),
        SVA.fromLabel('"AB"', 'ascii'), SVA.fromLabel('12'), SVA.fromLabel('0x1x'), SVA.fromLabel('IDLE')]""")
    check(lb == ['h1F', '0101', 253, 15, 'h4142', 12, 'h1x', 'x'], f'sva.js: bus labels back to values (hex, bin, signed, oct, ascii, dec, x) {lb}')
    raw = page.evaluate("""(() => { const W = WaveFW.parse({ signal: [{ name: 'clk', wave: 'p...' }, { name: 'd', wave: '=.=.', data: ['0101', '0011'], radix: 'bin', width: 4 },
        { name: 'e', wave: '=.=.', data: ['?', '?'], raw: ['a', '5'], width: 4 }], time: { t0: 0, cycle: 10 } });
      const rows = Object.fromEntries(W.rows.map(r => [r.name, r])), s = SVA.rowSampler(rows); return [s.column('d', [15, 25]), s.column('e', [15, 25]), s.width('e')]; })()""")
    check(raw == [['0101', '0011'], ['ha', 'h5'], 4], f'sva.js: a clock-sampled bus: its label by radix, or its "raw" value; "width" {raw}')


def sva_hardening(browser, build):
    """Stage 6.1 on the example pages: evaluation cost, results kept, panel updates in place, the dump state, storage
    rules, prefixes at run time, the rows hook."""
    import json
    apb_all, apb, axi = (build / 'examples' / x for x in ('apb/apb_all.html', 'apb/apb.html', 'axi_lite/axi_lite.html'))
    if not apb_all.exists():
        return
    print('assertions: stage 6.1')
    ctx = browser.new_context(viewport={'width': 1360, 'height': 1400})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb_all.as_uri()); page.wait_for_load_state('networkidle')
    # 100 assertions bound to u_regs: one evaluation per clock, the unit parsed once
    src = 'module many (input logic PCLK, PRESETn, PSEL, PENABLE, PREADY);\n' + ''.join(
        f'  m{k}: assert property (@(posedge PCLK) disable iff (!PRESETn) PSEL && !PENABLE |-> ##[1:{1 + k % 3}] PENABLE);\n' for k in range(100)) + 'endmodule\n'
    t = page.evaluate("""async src => { await SVA.loadFiles([{ name: 'many.sva', text: src }]); await SVA.ready(); const p = SVA.panels()[0], t0 = performance.now();
        for (let k = 0; k < 100; k++) p.bindings.push({ assert: 'm' + k, scope: 'apb_tb.u_regs', results: null });
        p.sync(); await SVA.ready(); return [performance.now() - t0, p.bindings.filter(b => b.results && b.results.assertions[0].stats.pass === 3).length]; }""", src)
    check(t[0] < 1000 and t[1] == 100, f'100 bindings of one instance evaluated in {t[0]:.0f} ms (< 1 s), all with their counts ({t[1]})')
    page.reload(); page.wait_for_load_state('networkidle')
    t = page.evaluate("""async () => { const t0 = performance.now(); await SVA.ready(); const p = SVA.panels()[0];
        return [performance.now() - t0, p.bindings.length, p.bindings.filter(b => b.results).length, p.bindings.filter(b => b.via).length]; }""")
    check(t[1] == 100 and t[2] == 100 and t[3] == 0 and t[0] < 500, f'after a reload the results come from this browser, not evaluated again ({t[2]} of {t[1]}, {t[0]:.0f} ms)')
    # a binding's line is updated in place: the list keeps its scroll position
    v = page.locator('.wv').first
    page.evaluate("document.querySelector('.wv .sva ol.asv').scrollTop = 300")
    top0 = page.evaluate("document.querySelector('.wv .sva ol.asv').scrollTop")
    page.evaluate("(async () => { const p = SVA.panels()[0]; await p.evaluate(p.bindings[50]); })()")
    page.evaluate('SVA.ready()')
    top1 = page.evaluate("document.querySelector('.wv .sva ol.asv').scrollTop")
    check(top0 > 0 and top1 == top0, f'evaluating a binding keeps the list where it was (scrollTop {top0} -> {top1})')
    # ✕ fires wavefw:sva for the bindings it removes
    n = page.evaluate("""(() => { let n = 0; const r = document.querySelector('.wv'); r.addEventListener('wavefw:sva', () => n++);
        document.querySelector('.wv .sva li[data-a="m7"] button[data-sv=del]').click(); return n; })()""")
    check(n == 1, f'✕ on a bound assertion fires wavefw:sva ({n})')
    # the sort prefixes are re-read: x_PSEL resolves once "x_" is ignored
    page.evaluate("""async () => { await SVA.loadFiles([{ name: 'pfx.sva', text: 'module pfx (input logic PCLK, x_PSEL, PENABLE); a_pfx: assert property (@(posedge PCLK) PENABLE |-> x_PSEL); endmodule' }]); }""")
    page.evaluate('SVA.ready()')
    st0 = page.evaluate("(() => { const p = SVA.panels()[0]; const b = p.bind('a_pfx', 'apb_tb.u_regs'); return b && b.state; })()")
    pfx = v.locator('input.pfx')
    pfx.fill('x_'); page.evaluate('SVA.ready()'); page.wait_for_timeout(100)
    st1 = page.evaluate("(() => { const b = SVA.panels()[0].bindings.find(b => b.assert === 'a_pfx'); return [b.state, b.results && b.results.assertions[0].stats.pass]; })()")
    check(st0 == 'cannot' and st1 == ['bound', 5], f'a new prefix in the sort field binds x_PSEL to PSEL ({st0} -> {st1})')
    pfx.fill('i_,o_,s_,m_')
    # the rows hook: a row of a plugin under u_regs folds, sorts and is found with it
    hook = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, g = Object.values(v.M.groups).find(g => g.name === 'u_regs');
        const src = v.M.rows.find(r => r.full === 'apb_tb.u_regs.PSEL'), row = { type: 'sig', name: 'probe_row', full: 'apb_tb.u_regs.probe_row', tr: src.tr, width: 1 };
        v.extraRows.push(x => (x === g ? [row] : [])); v.expandAll();
        const at = () => v.vis.indexOf(row), kids = () => v.vis.filter(r => r.anc.includes(g.id));
        const H0 = v.lay.H, pos = [at(), kids().indexOf(row), kids().length];
        const own = () => kids().filter(r => r.anc[r.anc.length - 1] === g.id && r.type === 'sig' && !r.cls && r !== row);
        v.setSort('desc'); const sorted = kids().indexOf(row) > Math.max(...own().map(r => kids().indexOf(r)));
        v.setSort('none'); v.find('probe'); const found = v.found.has(row); v.clearFind();
        v.collapsed.add(g.id); v.renderNames(); v.draw(); const folded = at() === -1;
        v.collapsed.delete(g.id); v.renderNames(); v.draw();
        const shown = at() >= 0 && H0 > 0; v.extraRows.length = 0; v.renderNames(); v.draw();
        return { pos, sorted, found, folded, shown }; })()""")
    check(hook['pos'][0] > 0 and hook['sorted'] and hook['found'] and hook['folded'] and hook['shown'],
          f'view.extraRows: a row under u_regs after its signals, kept there when sorted, found, folded with it {hook}')
    check(not errs, 'no page errors (stage 6.1 checks)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    page.evaluate('localStorage.clear()')
    # the dump state on the AXI-Lite page: done is not in the views, its results come from sva eval
    page.goto(axi.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    d = page.locator('.wv').first.locator('.sva li[data-a="axi_done"]').inner_text()
    check('from the dump, not in this view: done' in d and 'pass' in d, f'build-time results of a signal the view lacks are marked ({d[:120]!r})')
    # storage rules on the APB page: the config's bindings join the stored ones, an unbound one stays away
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    key = page.evaluate("SVA.panels()[0].key")
    page.evaluate(f"""localStorage.setItem({json.dumps(key)}, JSON.stringify({{ bind: [{{ assert: 'apb_phase_order', scope: 'apb_tb' }}], removed: ['apb_demo_no_wait@apb_tb'] }}))""")
    page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    b = page.evaluate("SVA.panels()[0].bindings.map(b => b.assert)")
    check(len(b) == 13 and 'apb_demo_no_wait' not in b and b[0] == 'apb_phase_order', f'stored bindings first, the config\'s new ones join, the unbound one stays away ({len(b)})')
    page.evaluate('localStorage.clear()')
    ctx.close()


SVA_PAGE = {'apb': 14, 'axi_lite': 19, 'fsm': 15}   # assertions in the config's files; all bound to the view's scope


def sva_waves(browser, build):
    """Stage 7 on the APB pages: the assertion groups, bars, circles, arrows, selection, f / F, SVG, sorting, folding."""
    import json
    apb, apb_all = build / 'examples' / 'apb' / 'apb.html', build / 'examples' / 'apb' / 'apb_all.html'
    if not apb.exists():
        return
    print('assertions: on the waves')
    ctx = browser.new_context(viewport={'width': 1360, 'height': 1400})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    js = lambda e, *a: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView, p = v.sva; {e} }})()", *a)
    js('v.expandAll(); v.fit();')
    # every drawn binding: its group with the counts, as many bars as listed attempts (pass + fail here)
    g = js("""return p.bindings.map(b => { const o = b.results.assertions[0], st = b.draw;
        v.namesEl.querySelector(`.row[data-r="${v.vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
        return [b.assert, st.g.name, st.lane.drawn, o.kind === 'cover' ? o.attempts.length : o.stats.pass + o.stats.fail + o.stats.active + o.stats.disabled + o.stats.capped, v.vis.includes(st.lane), st.g.anc.length]; });""")
    bad = [x for x in g if x[2] != x[3] or not x[4] or x[5] != 0]
    check(len(g) == 14 and not bad and g[10][1] == '⚑ apb_demo_no_wait · 3 pass · 2 fail', f'apb: 14 assertion groups at the top of the view with their counts, bars = attempts listed {bad[:3]} {g[10][:2]}')
    # a click on the first failing bar: the attempt is selected, the cursor at its start, a red arrow with the reason
    hit = js("""const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait'), st = b.draw;
        v.namesEl.querySelector(`.row[data-r="${v.vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
        const o = v.lay.find(o => o.row === st.lane), h = st.lane.hits.find(h => h[4].r === 'fail'), r = v.canvas.getBoundingClientRect();
        return [r.left + (h[0] + h[1]) / 2, r.top + o.y - v.oy + (h[2] + h[3]) / 2, b.results.cycles[h[4].a.start]];""")
    page.mouse.click(hit[0], hit[1])
    sel = js("""const st = p.selA.b.draw; return [p.selA.b.assert, p.selA.i, v.cursor, (st.g.arrows || []).filter(a => a.col === 'sva-fail').map(a => [a.label, a.front]),
        v.extraPicks.size, document.querySelectorAll('.wv .names .row.hl').length, p.el.querySelector('li[data-a="apb_demo_no_wait"]').innerText];""")
    check(sel[:3] == ['apb_demo_no_wait', 1, hit[2]] and ['expected PREADY', True] in sel[3] and sel[4] >= 5 and sel[5] >= 5 and 'attempt 2: fail' in sel[6],
          f'click on a failing bar: the attempt selected, the cursor at its start, a red arrow "expected PREADY", the bound signals highlighted, the panel line says so {sel[:6]}')
    # f / F: next / previous failure (round the end); the go-to buttons; Esc
    v = page.locator('.wv').first
    v.locator('canvas').focus()
    seq = []
    for k in ('f', 'f', 'F'):
        page.keyboard.press(k); seq.append(js('return [p.selA.i, v.cursor];'))
    btns = v.locator('.bar .svj button.fail')
    check([x[0] for x in seq] == [2, 1, 2] and seq[0][1] == 115000 and btns.count() == 2, f'f / F step through the two failures, round the end {seq}; {btns.count()} failure buttons in go to')
    page.keyboard.press('Escape')
    esc = js("return [p.selA, v.extraPicks.size, p.el.querySelector('li[data-a=\"apb_demo_no_wait\"]').innerText.includes('attempt')];")
    btns.nth(1).click()
    check(esc == [None, 0, False] and js('return p.selA && p.selA.i;') == 2, f'Esc clears the selection {esc}; the second failure button selects that attempt')
    # tooltips: a circle names its step, the ✕ its reason once; a bar gives start → end
    tips = js("""const st = p.bindings.find(b => b.assert === 'apb_demo_no_wait').draw;
        v.namesEl.querySelector(`.row[data-r="${v.vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'start' }); v.draw();
        const r = st.steps.find(r => r.hits.some(h => !h[1].fail)), c = r.hits.find(h => !h[1].fail), f = st.steps.map(r => r.hits.find(h => h[1].fail)).find(Boolean);
        const bar = Object.values(p.bindings).map(b => b.draw && b.draw.lane).filter(Boolean).flatMap(l => l.hits.map(h => [l, h])).find(([l, h]) => h[4].a.start !== h[4].a.end);
        return [r.tip(c[0], 0, v), f ? st.steps.find(r => r.hits.includes(f)).tip(f[0], 0, v) : '', bar ? bar[0].tip((bar[1][0] + bar[1][1]) / 2, (bar[1][2] + bar[1][3]) / 2, v) : 'no bar'];""")
    check(not any('undefined' in t for t in tips) and tips[0].startswith('step ') and tips[1].count('expected PREADY') == 1 and '→' in tips[2],
          f'tooltips: the step label on a circle, the reason once on the ✕, start → end on a bar {tips}')
    # the circle digits: at least 4.5:1 on their colour in every theme
    con = page.evaluate("""(() => { const e = document.querySelector('.wv'), out = [], L = h => { const c = h.match(/\\w\\w/g).map(x => parseInt(x, 16) / 255).map(x => x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
        const hex = c => c.startsWith('#') ? c.slice(1).padEnd(6, '0') : c.match(/\\d+/g).slice(0, 3).map(x => (+x).toString(16).padStart(2, '0')).join('');
        for (const th of ['light', 'white', 'dark']) { e.dataset.theme = th; const cs = getComputedStyle(e), bg = L(hex(cs.getPropertyValue('--panel').trim()));
          for (const k of ['pass', 'fail', 'disabled', 'active', 'capped']) { const f = L(hex(cs.getPropertyValue('--sva-' + k).trim())); out.push([th, k, Math.round((Math.max(f, bg) + 0.05) / (Math.min(f, bg) + 0.05) * 100) / 100]); } }
        delete e.dataset.theme; return out; })()""")
    check(all(x[2] >= 4.5 for x in con), f'the digits in the step circles: contrast >= 4.5 in every theme {[x for x in con if x[2] < 4.5] or "ok"}')
    # navigation: a click on an assertion's line goes to its first failure at the zoom of the view, the attempt in the
    # middle; again: the next failure; a passing one: its first pass; a / A: the next / previous assertion
    nav = []
    span0 = js('v.span = 40000; v.draw(); return v.span;')
    ln = lambda name: v.locator(f'.sva li[data-a="{name}"] code.at')
    geo = """const s = p.selA, o = s.b.results.assertions[0], a = o.attempts[s.i], T = o.cycles || s.b.results.cycles, per = (T[T.length - 1] - T[0]) / (T.length - 1);
        const ts = T[a.start], te = T[Math.max(a.end, a.failed_at ?? a.end)], mid = (ts + te) / 2;
        return [s.b.assert, s.i, a.result, v.span, Math.round(((mid - v.t0) / v.span) * 100) / 100, v.cursor === ts,
          !!p.el.querySelector('li.here[data-a="' + s.b.assert + '"]')];"""
    page.keyboard.press('Escape')
    ln('apb_demo_no_wait').click(); nav.append(js(geo))
    ln('apb_demo_no_wait').click(); nav.append(js(geo))
    ln('apb_setup_then_access').click(); nav.append(js(geo))
    v.locator('canvas').focus(); page.keyboard.press('a'); nav.append(js(geo)[0]); page.keyboard.press('A'); nav.append(js(geo)[0])
    order = js("return p.drawn().map(b => b.assert);")
    k = order.index('apb_setup_then_access')
    check(nav[0][:3] == ['apb_demo_no_wait', 1, 'fail'] and nav[1][:3] == ['apb_demo_no_wait', 2, 'fail'] and nav[2][2] == 'pass'
          and all(x[3] == span0 and abs(x[4] - 0.5) < 0.1 and x[5] and x[6] for x in nav[:3]) and nav[3] == order[(k + 1) % len(order)] and nav[4] == 'apb_setup_then_access',
          f'a click on an assertion: its first failure at the same zoom ({span0} ps), the attempt in the middle {nav[0][4]}; again: the next failure; a passing one: a pass; a / A: the next / previous assertion {nav}')
    page.keyboard.press('Escape')
    # sorting, find, Expand / Collapse keep the groups where they are
    js("v.setSort('desc');")
    pos = js("""const top = v.vis.filter(r => r.type === 'sig' && !r.anc.length && !r.cls), gs = v.vis.filter(r => r.sva);
        return [Math.max(...top.map(r => v.vis.indexOf(r))) < Math.min(...gs.map(r => v.vis.indexOf(r))), gs.length];""")
    js("v.setSort('none'); v.find('demo_no_wait');")
    found = js("return [...v.found.keys()].filter(r => r.sva).map(r => r.sva);")
    js("v.find('PREADY');")
    found += js("return [...v.found.keys()].filter(r => r.cls === 'sva-step').map(r => r.name);")
    js('v.clearFind(); v.collapseAll();')
    col = js("return [v.vis.filter(r => r.sva).length, v.vis.filter(r => r.cls === 'sva-lane').length];")
    js('v.expandAll();')
    exp = js("return v.vis.filter(r => r.cls === 'sva-lane').length;")
    check(pos == [True, 14] and found[0] == 'apb_demo_no_wait' and '2. PREADY' in found and col == [14, 0] and exp == 14, f'sorted: the groups stay after the signals {pos}; found by step label {found}; Collapse / Expand {col} {exp}')
    # the static SVG view: two assertions (svaShow), arrows of every attempt, the legend of the steps
    svg = page.locator('.wvs svg').first.inner_html()
    check('⚑ apb_setup_then_access' in svg and '⚑ apb_end_of_transfer' in svg and 'apb_demo_no_wait' not in svg and 'PSEL &amp;&amp; !PENABLE  (ante)' in svg and '>1T<' in svg,
          'the "write" SVG view: the two assertions of its svaShow with arrows and the legend of their steps')
    # dark theme: the tokens change
    dark = page.evaluate("(() => { const e = document.querySelector('.wv'); e.dataset.theme = 'dark'; const c = getComputedStyle(e).getPropertyValue('--sva-fail').trim(); delete e.dataset.theme; return [c, getComputedStyle(e).getPropertyValue('--sva-fail').trim()]; })()")
    check(dark[0] != dark[1] and all(dark), f'--sva-fail differs in the dark theme {dark}')
    # 1200 attempts: one redraw under 20 ms
    t = js("""const T = [], n = 1200, at = [], d = (v.M.t1 - v.M.t0) / (n + 4);
        for (let k = 0; k < n + 3; k++) T.push(v.M.t0 + d * k);
        for (let k = 0; k < n; k++) at.push({ start: k, end: k + (k % 3), result: k % 7 ? 'pass' : 'fail', trace: [['s1', k], ['s2', k + (k % 3)]], ...(k % 7 ? {} : { failed_at: k + 2, note: 'x', reason: { kind: 'expected', step: 's2', cycle: k + 2 } }) });
        p.bindings.push({ assert: 'perf', scope: 'apb_tb', state: 'dump', results: { clock: 'PCLK', unit: 'ps', cycles: T, assertions: [{ name: 'perf', kind: 'assert', text: 'a |-> ##[0:2] b',
          steps: [{ id: 's1', label: 'a', role: 'ante' }, { id: 's2', label: '##[0:2] b', role: 'cons' }], stats: { attempts: n, pass: n - 172, fail: 172, vacuous: 0, active: 0, disabled: 0, capped: 0 }, attempts: at, lane: 'S'.repeat(n) }] } });
        p.redraw(); v.expandAll(); v.fit();
        const b = p.bindings[p.bindings.length - 1]; v.namesEl.querySelector(`.row[data-r="${v.vis.indexOf(b.draw.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
        const t0 = performance.now(); for (let i = 0; i < 5; i++) v.draw(); const ms = (performance.now() - t0) / 5;
        p.bindings.pop(); p.redraw(); return [ms, b.draw.lane.drawn];""")
    check(t[0] < 20 and 0 < t[1] <= 1200, f'1200 attempts on screen: a redraw in {t[0]:.1f} ms (< 20 ms), bars binned by pixel ({t[1]} attempts drawn)')
    # a long active attempt behind 70 short ones (the value column), a truncated trace (the cut drawn as such), the top scope
    inj = js("""const T = [], d = (v.M.t1 - v.M.t0) / 200; for (let k = 0; k < 190; k++) T.push(v.M.t0 + d * k);
        const at = [{ start: 0, end: 150, result: 'active', trace: [['s1', 0]] }];
        for (let k = 1; k <= 70; k++) at.push({ start: k, end: k, result: 'pass', trace: [['s1', k], ['s2', k]] });
        const tr = []; for (let k = 0; k < 63; k++) tr.push([k ? 's2' : 's1', k < 16 ? 100 + k : 120 + k]);
        at.push({ start: 100, end: 182, result: 'pass', trace: tr, truncated: true });
        p.bindings.push({ assert: 'probe', scope: '', state: 'dump', results: { clock: 'PCLK', unit: 'ps', cycles: T, assertions: [{ name: 'probe', kind: 'assert', text: 'a |-> b',
          steps: [{ id: 's1', label: 'a', role: 'ante' }, { id: 's2', label: 'b', role: 'cons' }], stats: { attempts: 72, pass: 71, fail: 0, vacuous: 0, active: 1, disabled: 0, capped: 0 }, attempts: at }] } });
        p.redraw(); v.expandAll();
        const b = p.bindings[p.bindings.length - 1], st = b.draw, val = st.lane.value(T[75]);
        p.select(b, 71); const arrows = (st.g.arrows || []).filter(a => a.front).map(a => a.label), tip = st.lane.tip;
        p.unselect(); p.bindings.pop(); p.redraw(); return [val, arrows.filter(l => l.includes('trace cut')), st.g.full, st.g.name];""")
    check(inj[0].startswith('active') and len(inj[1]) == 1 and '… 21T (trace cut)' in inj[1] and inj[2] == 'probe' and inj[3] == '⚑ probe · 71 pass · 0 fail · 1 active',
          f'a long active attempt behind 70 later ones shows in the value column; a truncated trace draws its cut; a top-scope name without "@" {inj}')
    # the whole hierarchy: bound to the slave, the group under u_regs, after its signals, also when sorted and folded
    page.goto(apb_all.as_uri()); page.wait_for_load_state('networkidle')
    page.evaluate("async () => { localStorage.clear(); await SVA.loadFiles([{ name: 'apb.sv', text: %s }]); await SVA.ready(); SVA.panels()[0].bind('apb_setup_access', 'apb_tb.u_regs'); await SVA.ready(); }" % json.dumps((ROOT / 'tests' / 'sva' / 'apb.sv').read_text()))
    u = js("""const g = Object.values(v.M.groups).find(g => g.name === 'u_regs'), b = p.bindings[0], st = b.draw;
        v.expandAll(); const kids = () => v.vis.filter(r => r.anc.includes(g.id)), own = () => kids().filter(r => r.anc[r.anc.length - 1] === g.id && r.type === 'sig' && !r.cls);
        const after = () => kids().indexOf(st.g) > Math.max(...own().map(r => kids().indexOf(r)));
        const a = [st.g.anc[st.g.anc.length - 1] === g.id, after(), st.g.name]; v.setSort('asc'); a.push(after()); v.setSort('none');
        v.collapsed.add(g.id); v.renderNames(); a.push(v.vis.includes(st.g)); v.collapsed.delete(g.id); v.renderNames(); v.draw(); return a;""")
    check(u == [True, True, '⚑ apb_setup_access · 3 pass · 0 fail', True, False], f'apb_all: bound to u_regs, the group directly under the slave after its signals, also sorted; folded with it {u}')
    # the selection goes with its binding (no highlighted rows left), the group leaves the model; Clear redraws once
    gone = js("""const b = p.bindings[0], n0 = Object.keys(v.M.groups).length; p.select(b, 0); const on = v.extraPicks.size;
        p.unbind(b); v.renderNames(); return [on, v.extraPicks.size, p.selA, n0 - Object.keys(v.M.groups).length];""")
    page.evaluate("async () => { SVA.panels()[0].bind('apb_setup_access', 'apb_tb.u_regs'); SVA.panels()[0].bind('apb_setup_access', 'apb_tb.u_master'); await SVA.ready(); await SVA.panels()[0].queue; }")
    clr = js("""const n = { names: 0, report: 0 }, rn = v.renderNames.bind(v), rp = p.report.bind(p);
        v.renderNames = () => { n.names++; rn(); }; p.report = f => { n.report++; return rp(f); };
        const t0 = performance.now(); p.el.querySelector('button[data-sv=clear]').click(); const ms = performance.now() - t0;
        return new Promise(r => setTimeout(() => { v.renderNames = rn; p.report = rp; r([n.names, n.report, Math.round(ms), p.bindings.length]); }, 50));""")
    check(gone[0] > 0 and gone[1:] == [0, None, 1] and clr[0] <= 2 and clr[1] <= 1, f'unbind of the selected binding: no picks left, its group gone from the model {gone}; Clear of 2 bindings: {clr[0]} renderNames, {clr[1]} report, {clr[2]} ms')
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (assertions on the waves)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def sva_report(browser, build):
    """Stage 8 in the APB page: totals and table against sva eval's report, the count filter, the failure list, exports."""
    import json, subprocess
    apb, sva = build / 'examples' / 'apb' / 'apb.html', build / 'sva-target' / 'release' / 'sva'
    if not apb.exists() or not sva.exists():
        return
    print('assertions: report')
    out, summ = build / 'sva' / 'apb.report.json', build / 'sva' / 'apb.summary.json'   # --report .json: the results with the meta
    subprocess.run([str(sva), 'eval', '--waves', str(build / 'examples' / 'apb' / 'apb.fst'), *SVA_EXAMPLES['apb'][0], '--report', str(out)], cwd=ROOT, capture_output=True)
    subprocess.run([str(sva), 'report', '--json', str(summ), str(out)], capture_output=True)
    native = json.loads(summ.read_text())
    ctx = browser.new_context(viewport={'width': 1360, 'height': 1400}, accept_downloads=True)
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    # the exact view covers the whole dump: its numbers are sva eval's
    k = page.evaluate("SVA.panels().findIndex(p => p.v.M.rows.some(r => r.src && r.src.tv))")
    v = page.locator('.wv').nth(k)
    got = page.evaluate("async k => { const p = SVA.panels()[k], r = await p.report(); return r.summary; }", k)
    pick = lambda r: [(a['name'], a['stats'], a['latency'], (a['first_fail'] or {}).get('start'), (a['longest'] or {}).get('cycles')) for a in r['assertions']]
    tk = ['attempts', 'pass', 'fail', 'vacuous', 'disabled', 'active', 'capped', 'with_failures', 'covered']
    check(pick(got) == pick(native) and [got['totals'][x] for x in tk] == [native['totals'][x] for x in tk],
          f'apb exact view: totals and the per-assertion numbers (latency, first failure, longest) equal sva eval --report {[got["totals"][x] for x in tk]}')
    v.locator('.sva button[data-sv=table]').click(); v.locator('.sva button[data-sv=fails]').click()
    page.wait_for_function(f"SVA.panels()[{k}].el.querySelectorAll('.svr table.svt').length === 2")
    tot = v.locator('.svr .tot').inner_text()
    rows = v.locator('.svr table.svt').first.locator('tbody tr').count()
    check('14 bound · 1 with failures' in tot and '2 fail' in tot and rows == 14, f'the totals line ({tot}) and one table row per binding ({rows})')
    # a failure row selects its attempt; a count filters the lane and lists the attempts
    v.locator('.svr table.svt').nth(1).locator('tbody tr').nth(1).locator('button[data-sv=go]').click()
    sel = page.evaluate(f"(p => [p.selA.b.assert, p.selA.i, p.v.cursor])(SVA.panels()[{k}])")
    check(sel == ['apb_demo_no_wait', 2, 115000], f'the second row of the failure list selects that attempt on the waves {sel}')
    v.locator('.sva li[data-a="apb_demo_no_wait"] button[data-sv=only][data-k=pass]').click()
    flt = page.evaluate("""k => { const p = SVA.panels()[k], b = p.bindings.find(b => b.assert === 'apb_demo_no_wait'); p.v.expandAll(); p.v.fit();
        p.v.namesEl.querySelector(`.row[data-r="${p.v.vis.indexOf(b.draw.lane)}"]`).scrollIntoView({ block: 'center' }); p.v.draw();
        return [b.draw.lane.name, b.draw.lane.drawn, p.el.querySelectorAll('li[data-a="apb_demo_no_wait"] ol.atl li').length]; }""", k)
    check(flt == ['attempts: pass', 3, 3], f'a click on "3 pass": the lane shows only those attempts, listed under the line {flt}')
    v.locator('.sva li[data-a="apb_demo_no_wait"] button[data-sv=only][data-k=pass]').click()
    v.locator('.svf select').select_option('apb_demo_no_wait')
    page.evaluate(f"SVA.panels()[{k}].el.querySelector('button[data-sv=fcopy]').click()")
    txt = page.evaluate(f"SVA.panels()[{k}].copied")
    check(txt.count('\n') == 2 and 'apb_demo_no_wait\tapb_tb\t105 ns (cycle 10)' in txt, f'failure list filtered and copied as text ({txt.splitlines()[1:2]})')
    # exports through the browser's download
    with page.expect_download() as d:
        v.locator('.sva button[data-sv=xmd]').click()
    md = pathlib.Path(d.value.path()).read_text()
    with page.expect_download() as d:
        v.locator('.sva button[data-sv=xjson]').click()
    js = json.loads(pathlib.Path(d.value.path()).read_text())
    rr = build / 'sva' / 'page.report.md'
    r = subprocess.run([str(sva), 'report', '--md', str(rr), d.value.path()], capture_output=True, text=True)
    check('## Failures (2)' in md and '| `apb_demo_no_wait` | apb_tb | assert | 19 | 3 | 2 |' in md and len(js['results']) == 14 and js['meta']['dump'] == 'apb.vcd'
          and r.returncode == 1 and '## Failures (2)' in rr.read_text(), f'report.md and report.json downloaded; sva report reads report.json (exit {r.returncode}) {js["meta"]} {[l for l in md.splitlines() if "no_wait" in l][:1]}')
    # the printable section of the mkhtml page: every binding over the whole dump
    page.emulate_media(media='print')
    st = page.evaluate("""(() => { const s = document.querySelector('section.sva-report'); if (!s) return null;
        return [s.querySelectorAll('table.per tbody tr').length, s.querySelectorAll('table.fails tbody tr').length, s.querySelector('.tot').textContent, getComputedStyle(s).display]; })()""")
    page.emulate_media(media='screen')
    check(st and st[:2] == [14, 2] and st[2].startswith('14 assertions (14 evaluated, 1 with failures): 209 attempts') and st[3] != 'none',
          f'the static "Assertions" section of the page (printed too): one row per binding, the failure list {st}')
    check(not errs, 'no page errors (report)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    page.evaluate('localStorage.clear()')
    ctx.close()


def sva_report_hardening(browser, build):
    """Stage 8.1: the name rule on ambiguous prefixes and shown names (page, Names, CLI), an alias binding evaluated,
    the page after a file the engine cannot read, the capped failure list, totals without results, the printable
    section at A4, mkconfig --update keeping hand entries, make html with a mistyped SVA=."""
    import json, subprocess, time
    sva, apb, apb_all = build / 'sva-target' / 'release' / 'sva', build / 'examples' / 'apb' / 'apb.html', build / 'examples' / 'apb' / 'apb_all.html'
    if not sva.exists() or not apb.exists():
        return
    print('assertions: report hardening (8.1)')
    d = build / 'sva' / 'h81'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'n.vcd').write_text('$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 " i_valid $end\n$var wire 1 # o_valid $end\n'
                             '$var wire 1 $ ack $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n1"\n1#\n1$\n#5\n1!\n#10\n0!\n#15\n1!\n#20\n0!\n')
    (d / 'n.sv').write_text('module chk(input clk);\n  a_amb: assert property (@(posedge clk) valid |-> ack);\n  a_alias: assert property (@(posedge clk) rdy |-> ack);\nendmodule\n')
    py = lambda *a: subprocess.run([sys.executable, '-I', *map(str, a)], capture_output=True, text=True, cwd=ROOT)
    py(ROOT / 'tools' / 'mkconfig.py', d / 'n.vcd', '--out', d / 'n.config.json', '--force')
    cfg = json.loads((d / 'n.config.json').read_text())
    for e in cfg['signals'].values():
        e['show'] = True   # constant signals start hidden
    cfg['signals']['tb.ack']['alias'] = 'rdy'
    cfg.setdefault('config', {})['sortIgnore'] = ['i_', 'o_']
    cfg['sva'], cfg['bind'] = ['n.sv'], ['a_alias@tb']
    (d / 'n.config.json').write_text(json.dumps(cfg, indent=1))
    r = py(ROOT / 'tools' / 'mkhtml.py', '--config', d / 'n.config.json', '--sva-bin', sva, '--out', d / 'n.html')
    sys.path.insert(0, str(ROOT / 'tools'))
    import svabuild
    names = svabuild.Names({'tb.clk': 1, 'tb.i_valid': 1, 'tb.o_valid': 1, 'tb.ack': 1}, {'tb.ack': 'rdy'}, ['i_', 'o_'])
    pyr = [names.resolve('tb', [{'name': 'clk'}, {'name': 'valid'}, {'name': 'ack'}])[1], names.resolve('tb', [{'name': 'clk'}, {'name': 'rdy'}, {'name': 'ack'}])[0].get('rdy')]
    cli = subprocess.run([str(sva), 'eval', '--waves', str(d / 'n.vcd'), '--scope', 'tb', '--resolve', 'scope', '--ignore-prefix', 'i_,o_', '--alias', 'rdy=tb.ack', '--sva', str(d / 'n.sv'), '--json'], capture_output=True, text=True)
    doc = json.loads(cli.stdout or '{}')
    clir = [cli.stderr, next((a['signals'].get('rdy') for a in doc.get('assertions', []) if a['name'] == 'a_alias'), None)]
    ctx = browser.new_context(viewport={'width': 1360, 'height': 1200})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto((d / 'n.html').as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    pg = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, p = v.sva, A = l => SVA.assertions().find(a => a.label === l);
        const amb = SVA.resolve(v, A('a_amb'), 'tb'), al = SVA.resolve(v, A('a_alias'), 'tb'), b = p.bindings.find(b => b.assert === 'a_alias'), o = b && b.results && b.results.assertions[0];
        return [amb.errors, al.map.rdy && al.map.rdy.full, b && b.state, o && (o.missing || []).length, o && o.stats.attempts]; })()""")
    amb = ['valid (ambiguous: tb.i_valid or tb.o_valid)']
    check(r.returncode == 0 and pyr[0] == amb and pg[0] == amb and 'valid (ambiguous: tb.i_valid or tb.o_valid)' in clir[0] and pyr[1] == pg[1] == clir[1] == 'tb.ack' and pg[2:] == ['bound', 0, 2],
          f'names: an ambiguous match without the prefixes is an error in all three {pyr[0]} {pg[0]}; the shown name rdy is tb.ack everywhere {[pyr[1], pg[1], clir[1]]}; the alias binding is evaluated {pg[2:]} {r.stderr[-200:] if r.returncode else ""}')
    # a file the parser cannot read used to stop the engine for good: now an error line, and after a reload the page's own assertions
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    page.evaluate("async () => { localStorage.clear(); await SVA.loadFiles([{ name: 'bad.sv', text: 'a\\n' }]); await SVA.ready(); }")
    notes = page.evaluate("[...document.querySelectorAll('.wv .sva .svn li')].map(l => l.textContent)")
    page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    back = page.evaluate("SVA.panels().map(p => [p.el.hidden, p.bindings.filter(b => b.results).length])")
    check(any('bad.sv' in n for n in notes) and all(x == [False, 14] for x in back), f'a stray identifier in a loaded file is an error line {notes[:1]}; after a reload every viewer still evaluates the 14 ({back})')
    page.evaluate('localStorage.clear()')
    # 1200 failures: the list shows 500 and says how many more
    t = page.evaluate("""async () => { const p = SVA.panels().find(p => p.v.M.rows.some(r => r.src && r.src.tv)), v = p.v, T = [], n = 1200;
        for (let k = 0; k < n + 2; k++) T.push(v.M.t0 + (v.M.t1 - v.M.t0) * k / (n + 2));
        const at = []; for (let k = 0; k < n; k++) at.push({ start: k, end: k, result: 'fail', failed_at: k, note: 'x', reason: { kind: 'expected', cycle: k } });
        p.bindings.push({ assert: 'many', scope: 'apb_tb', state: 'dump', results: { clock: 'PCLK', unit: 'ps', cycles: T, assertions: [{ name: 'many', kind: 'assert', text: 'a',
          steps: [], stats: { attempts: n, pass: 0, fail: n, vacuous: 0, active: 0, disabled: 0, capped: 0 }, attempts: at }] } });
        p.redraw(); await new Promise(r => setTimeout(r, 0)); await SVA.ready(); await new Promise(r => setTimeout(r, 50));
        const a = performance.now(); p.el.querySelector('button[data-sv=fails]').click(); const ms = performance.now() - a;
        const rows = p.el.querySelectorAll('.svx-f tbody tr').length, more = (p.el.querySelector('.svx-f .more') || {}).textContent || '';
        const b = performance.now(); p.el.querySelector('button[data-sv=table]').click(); const ms2 = performance.now() - b;
        const kept = p.el.querySelectorAll('.svx-f tbody tr').length;
        p.bindings.pop(); p.redraw(); return [rows, more, kept, Math.round(ms), Math.round(ms2)]; }""")
    check(t[0] == 500 and '702 more' in t[1] and t[2] == 500, f'1202 failures: the list shows 500 and "{t[1][:40]}"; the table opens without rebuilding it ({t[2]} rows kept); Failures {t[3]} ms, Table {t[4]} ms')
    # totals without results; the printable section fits an A4 page
    page.goto(apb_all.as_uri()); page.wait_for_load_state('networkidle')
    page.evaluate("async () => { localStorage.clear(); await SVA.ready(); await SVA.loadFiles([{ name: 'apb.sv', text: %s }]); await SVA.ready(); }" % json.dumps((ROOT / 'tests' / 'sva' / 'apb.sv').read_text()))
    tot = page.evaluate("(() => { const e = document.querySelector('.wv .sva .svr .tot'); return e ? e.textContent : null; })()")
    page.evaluate('localStorage.clear()')
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle')
    page.set_viewport_size({'width': 720, 'height': 1000}); page.emulate_media(media='print')
    fit = page.evaluate("[...document.querySelectorAll('section.sva-report table')].map(t => [t.scrollWidth, t.parentElement.clientWidth])")
    page.emulate_media(media='screen')
    check(tot and tot.endswith('loaded · 0 bound') and fit and all(w <= c + 1 for w, c in fit), f'totals with nothing bound "{tot}"; the printable tables fit a 720 px (A4) page {fit}')
    check(not errs, 'no page errors (8.1)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()
    # mkconfig --update --sva keeps what the user wrote
    c = d / 'apb.config.json'
    py(ROOT / 'tools' / 'mkconfig.py', build / 'examples' / 'apb' / 'apb.vcd', '--out', c, '--force', '--sva', ROOT / 'tests' / 'sva' / 'apb.sv', '--sva-bin', sva)
    if c.exists():
        x = json.loads(c.read_text())
        x['bind'] += ['apb_known@apb_tb', {'assert': 'apb_cov_*', 'scope': 'apb_tb'}, {'assert': 'nope', 'scope': 'apb_tb', 'note': 'mine'}]
        x['bind'][0]['note'] = 'kept'
        x['sva'] = ['../other.sv'] + x['sva']
        c.write_text(json.dumps(x, indent=1))
        r = py(ROOT / 'tools' / 'mkconfig.py', build / 'examples' / 'apb' / 'apb.vcd', '--out', c, '--update', '--sva', ROOT / 'tests' / 'sva' / 'apb.sv', '--sva-bin', sva)
        y = json.loads(c.read_text())
        kept = ['apb_known@apb_tb' in y['bind'], {'assert': 'apb_cov_*', 'scope': 'apb_tb'} in y['bind'], {'assert': 'nope', 'scope': 'apb_tb', 'note': 'mine'} in y['bind'],
                y['bind'][0].get('note'), y['sva'][0], len([b for b in y['bind'] if isinstance(b, dict) and b.get('assert') == 'apb_setup_access'])]
        check(r.returncode == 0 and kept == [True, True, True, 'kept', '../other.sv', 3], f'mkconfig --update --sva keeps hand-written bind entries, extra keys and files {kept} {r.stderr[-160:]}')
    # make: a mistyped SVA= is an error, not a page without checks; an explicit --sva-bin that is not there too
    m = subprocess.run(['make', '-n', 'html', 'SVA=nonexist.sva', 'BIND=a@tb'], capture_output=True, text=True, cwd=ROOT)
    try:
        svabuild.find_bin('/nonexist/sva'); fb = 'found'
    except SystemExit as e:
        fb = str(e)
    check(m.returncode != 0 and 'no file matches SVA=nonexist.sva' in m.stderr and 'no sva binary at /nonexist/sva' in fb, f'make html SVA=nonexist.sva stops ({m.stderr.strip()[-60:]}); --sva-bin /nonexist/sva: {fb}')


def sva_page(page, ex):
    page.evaluate('SVA.ready()')
    p = page.evaluate("""SVA.panels().map(p => ({ key: p.v.root.dataset.wave, n: p.el.querySelectorAll('ol.asv > li').length, tv: p.v.M.rows.some(r => r.src && r.src.tv),
        binds: p.bindings.map(b => [b.assert, b.state, b.results ? b.results.assertions[0].kind : null, b.results ? b.results.assertions[0].stats.fail : null]) }))""")
    n = SVA_PAGE[ex]
    check(all(x['n'] == n and len(x['binds']) == n for x in p), f'{ex}: every viewer lists the {n} assertions of the config, all bound ({[(x["n"], len(x["binds"])) for x in p]})')
    deliberate = SVA_EXAMPLES[ex][2]
    fails = sorted({b[0] for x in p for b in x['binds'] if b[2] != 'cover' and b[3]})
    states = {b[1] for x in p for b in x['binds']}
    check(fails == sorted(deliberate) and states <= {'bound', 'dump'}, f'{ex}: results from sva eval at build time, only {fails} fails ({states})')
    # the exact view again in the page: the native counts (sva eval), also through the Web Worker
    diff = page.evaluate("""async () => { const out = [], key = o => JSON.stringify(Object.keys(o).sort().map(k => [k, o[k]]));
        for (const p of SVA.panels()) { if (!p.v.M.rows.some(r => r.src && r.src.tv)) continue;
          for (const [i, b] of p.bindings.entries()) { if (b.state !== 'bound') continue;
            const nat = key(b.results.assertions[0].stats); SVA.syncLimit = i === 0 ? 0 : 100000;
            await p.evaluate(b); const pag = key(b.results.assertions[0].stats);
            out.push([b.assert, b.via, nat === pag && !b.error]); } }
        SVA.syncLimit = 100000; return out; }""")
    bad = [d for d in diff if not d[2]]
    check(len(diff) >= n - 2 and not bad and diff[0][1] == 'worker', f'{ex}: {len(diff)} bindings evaluated again in the page give the sva eval counts (first through a worker: {diff[0][1] if diff else None}) {bad[:3]}')


def sva_names(build, page_cands):
    """One rule for the names of an assertion in an instance (docs/sva/ENGINE.md): the page's candidates, mkconfig.py
    --sva (tools/svabuild.py Names) and sva eval --resolve scope agree on the APB example."""
    import json, subprocess
    sva = build / 'sva-target' / 'release' / 'sva'
    if not sva.exists():
        return
    cfg = build / 'sva' / 'apb_names.config.json'
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'mkconfig.py'), str(build / 'examples' / 'apb' / 'apb.vcd'), '--out', str(cfg), '--force',
                        '--sva', str(ROOT / 'tests' / 'sva' / 'apb.sv'), '--sva-bin', str(sva)], capture_output=True, text=True)
    py = [b['scope'] for b in json.loads(cfg.read_text())['bind'] if b['assert'] == 'apb_setup_access'] if r.returncode == 0 else r.stderr[-200:]
    rust = [sc for sc in ('apb_tb', 'apb_tb.u_master', 'apb_tb.u_regs', 'apb_tb.u_count')
            if subprocess.run([str(sva), 'eval', '--waves', str(build / 'examples' / 'apb' / 'apb.vcd'), '--scope', sc, '--resolve', 'scope',
                               '--sva', str(ROOT / 'tests' / 'sva' / 'apb.sv'), '--assert', 'apb_setup_access'], capture_output=True).returncode != 2]
    want = ['apb_tb', 'apb_tb.u_master', 'apb_tb.u_regs']
    check(sorted(page_cands) == py == rust == want, f'one name rule: the page {page_cands}, mkconfig.py --sva {py}, sva eval --resolve scope {rust} (not u_count)')


def sva_bind(browser, build):
    """The binding flow on the page of the whole APB hierarchy (scopes apb_tb, u_master, u_regs, u_count)."""
    import json, subprocess
    path = build / 'examples' / 'apb' / 'apb_all.html'
    if not path.exists():
        return
    print('assertions: binding on ' + path.name)
    ctx = browser.new_context(viewport={'width': 1360, 'height': 2400})   # the panel and the module rows on one screen (drag)
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(path.as_uri()); page.wait_for_load_state('networkidle')
    v = page.locator('.wv').first
    check(v.locator('.sva').is_hidden() and v.locator('button[data-sv=load]').count() == 1, 'apb_all: no assertion loaded: the panel is hidden, Load file… is in the bar')
    v.locator('input.svfile').set_input_files([str(ROOT / 'tests' / 'sva' / 'apb.sv'), str(ROOT / 'tests' / 'sva' / 'third_party' / 'saravana_apb_ahb' / 'apb_assertions.sv')])
    page.wait_for_function("SVA.panels()[0].el.querySelectorAll('ol.asv > li').length > 0")
    page.evaluate('SVA.ready()')
    n = v.locator('.sva ol.asv > li').count()
    check(n == 12 + 17 and 'apb.sv, apb_assertions.sv: 29 assertions' in v.locator('.bar .toast').inner_text(), f'Load file…: two files parsed in the page, {n} assertions ({v.locator(".bar .toast").inner_text()})')
    li = v.locator('.sva li[data-a="apb_setup_access"]')
    li.locator('button[data-sv=bind]').click()
    cands = li.locator('.pick button[data-sv=to]').all_inner_texts()
    check(cands == ['apb_tb', 'apb_tb.u_master', 'apb_tb.u_regs'], f'Bind… lists the instances that have every signal (the slave u_regs among them, not u_count) {cands}')
    sva_names(build, cands)
    li.locator('.pick button[data-sv=to]', has_text='u_regs').click()
    page.evaluate('SVA.ready()')
    st = page.evaluate("SVA.panels()[0].bindings.map(b => [b.assert, b.scope, b.state, b.via, b.results && b.results.assertions[0].stats])")
    sva = build / 'sva-target' / 'release' / 'sva'
    native = None
    if sva.exists():
        out = build / 'sva' / 'apb_regs.smoke.json'
        subprocess.run([str(sva), 'eval', '--waves', str(build / 'examples' / 'apb' / 'apb.vcd'), '--scope', 'apb_tb.u_regs', '--resolve', 'scope', '--sva', str(ROOT / 'tests' / 'sva' / 'apb.sv'),
                        '--assert', 'apb_setup_access', '--out', str(out)], capture_output=True)
        native = json.loads(out.read_text())['assertions'][0]['stats']
    check(st[:1] == [['apb_setup_access', 'apb_tb.u_regs', 'bound', 'page', native or st[0][4]]] and 'bound to apb_tb.u_regs' in li.inner_text() and '3 pass' in li.inner_text(),
          f'Bind… → u_regs: evaluated in the page, counts shown, equal to sva eval at that instance ({st[:1]}, native {native})')
    # dragging: the module rows that have the signals are drop targets, the others say what they miss
    marks = page.evaluate("""(() => { const li = document.querySelector('.wv .sva li[data-a="apb_enable_sel"]'), dt = new DataTransfer();
        li.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
        const rows = [...document.querySelectorAll('.wv .names .row.grp')].map(r => [r.textContent.trim().slice(2), r.classList.contains('sva-ok') ? 'ok' : r.classList.contains('sva-no') ? 'no' : '', r.title]);
        li.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt })); return rows; })()""")
    ok = sorted(m[0] for m in marks if m[1] == 'ok')
    no = {m[0]: m[2] for m in marks if m[1] == 'no'}
    check(ok == ['apb_tb', 'u_master', 'u_regs'] and no.get('u_count') == 'cannot bind: PENABLE, PSEL',
          f'while dragging: green drop targets {ok}, the others dimmed with what they miss {no}')
    page.wait_for_timeout(50)
    li2 = v.locator('.sva li[data-a="apb_enable_sel"]')
    li2.drag_to(v.locator('.names .row.grp', has_text='u_master'))
    page.evaluate('SVA.ready()')
    check('bound to apb_tb.u_master' in li2.inner_text() and '5 pass' in li2.inner_text(), f'drop on the u_master row binds it there ({li2.inner_text()[:160]!r})')
    li2.drag_to(v.locator('.names .row.grp', has_text='u_count'))
    page.wait_for_timeout(50)
    toast = v.locator('.bar .toast').inner_text()
    check('cannot bind apb_enable_sel to apb_tb.u_count: PENABLE, PSEL' in toast and page.evaluate("SVA.panels()[0].bindings.length") == 2, f'drop on u_count: not bound ({toast})')
    li2.drag_to(v.locator('.names .row:not(.grp)', has_text='PREADY').nth(2))   # a signal row: its module (u_regs)
    page.evaluate('SVA.ready()')
    check(li2.locator('ul.bnd > li').count() == 2 and 'bound to apb_tb.u_regs' in li2.inner_text(), 'drop on a signal row binds to its module; two instances: one line each')
    li2.locator('ul.bnd > li', has_text='u_master').locator('button[data-sv=unbind]').click()
    check(li2.locator('ul.bnd > li').count() == 0 and 'bound to apb_tb.u_regs' in li2.inner_text(), 'Unbind removes that binding only')
    v.locator('.sva button[data-sv=json]').click()
    js = v.locator('.sva textarea.json').input_value()
    binds = json.loads('{' + js + '}')['bind']
    check(binds == [{'assert': 'apb_setup_access', 'scope': 'apb_tb.u_regs'}, {'assert': 'apb_enable_sel', 'scope': 'apb_tb.u_regs'}], f'JSON: the bindings for the config {binds}')
    page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    st = page.evaluate("SVA.panels()[0].bindings.map(b => [b.assert, b.scope, b.state, b.results && b.results.assertions[0].stats.pass])")
    check(st == [['apb_setup_access', 'apb_tb.u_regs', 'bound', 3], ['apb_enable_sel', 'apb_tb.u_regs', 'bound', 5]] and v.locator('.sva ol.asv > li').count() == 29,
          f'after a reload: the files and the bindings come back from this browser, evaluated again {st}')
    # the exported list through a config file and mkhtml.py: the page opens with them bound (results of sva eval)
    cfg = json.loads((build / 'examples' / 'apb' / 'apb_all.config.json').read_text())
    cfg['sva'] = [str(ROOT / 'tests' / 'sva' / 'apb.sv')]
    cfg['bind'] = binds
    rt = build / 'examples' / 'apb' / 'apb_rt.config.json'
    rt.write_text(json.dumps(cfg))
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'mkhtml.py'), '--config', str(rt), '--out', str(rt.with_suffix('').with_suffix('.html'))]
                       + (['--sva-bin', str(sva)] if sva.exists() else []), capture_output=True, text=True)
    page2 = ctx.new_page()
    page2.goto(rt.with_suffix('').with_suffix('.html').as_uri()); page2.wait_for_load_state('networkidle')
    page2.evaluate("localStorage.clear()"); page2.reload(); page2.wait_for_load_state('networkidle'); page2.evaluate('SVA.ready()')
    st2 = page2.evaluate("SVA.panels()[0].bindings.map(b => [b.assert, b.scope, b.state, b.page, b.results && b.results.assertions[0].stats.pass])")
    check(r.returncode == 0 and st2 == [['apb_setup_access', 'apb_tb.u_regs', 'bound', True, 3], ['apb_enable_sel', 'apb_tb.u_regs', 'bound', True, 5]],
          f'the JSON through a config: mkhtml.py binds them at build time {st2} {r.stderr.strip()[-200:] if r.returncode else ""}')
    page2.close()
    v.locator('.sva button[data-sv=clear]').click()
    page.evaluate('SVA.ready()')
    check(v.locator('.sva').is_hidden() and page.evaluate("localStorage.length") == 0, 'Clear: this browser forgets the files and bindings, the panel hides')
    check(not errs, 'no page errors while binding' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def sva_wasm(build):
    """wavefw/sva.wasm.js (committed) is the packed module of the current build."""
    import base64, zlib
    wasm = build / 'sva-target' / 'wasm32-unknown-unknown' / 'wasm' / 'sva_wasm.wasm'
    js = (ROOT / 'wavefw' / 'sva.wasm.js').read_text()
    m = re.search(r'"size": (\d+), "deflate": "([^"]+)"', js)
    raw = zlib.decompress(base64.b64decode(m.group(2)), -15) if m else b''
    check(m and len(raw) == int(m.group(1)) and raw[:4] == b'\0asm', f'wavefw/sva.wasm.js: a WebAssembly module, {len(raw)} B ({len(js)} B in the page)')
    if wasm.exists():
        check(raw == wasm.read_bytes(), 'wavefw/sva.wasm.js is the module of the current build (make sva-build writes it)')


# sva eval over the example dumps (make sva-build, make examples): (pass, fail) per assertion where they are not
# (n, 0); every testbench has one deliberately wrong assertion
SVA_EXAMPLES = {
    'apb': (['--scope', 'apb_tb', '--sva', 'examples/apb/apb_tb.sv', '--sva', 'examples/apb/apb.sva'], 14, {'apb_demo_no_wait': (3, 2)}),
    'axi_lite': (['--scope', 'axi_lite_tb.u_slave', '--sva', 'examples/axi_lite/axi_lite.sva'], 19, {'axi_demo_aw_at_once': (0, 1)}),
    'fsm': (['--scope', 'fsm_tb.u_rx', '--sva', 'examples/fsm/uart_pkg.sv', '--sva', 'examples/fsm/fsm.sva'], 15, {'fsm_demo_short_data': (0, 2)}),
}


def sva_third_party(build, sva):
    """tests/sva/third_party/units.json: every evaluation over an example dump, no failure but the listed ones."""
    import json, subprocess
    tp = ROOT / 'tests' / 'sva' / 'third_party'
    for u in json.loads((tp / 'units.json').read_text())['units']:
        for e in u.get('eval', []):
            dump = build / 'examples' / e['example'] / f'{e["example"]}.fst'
            if not dump.exists():
                continue
            out = build / 'sva' / f'{u["name"]}.{e["scope"]}.json'
            files = [x for f in u['files'] for x in ('--sva', str(tp / f))]
            r = subprocess.run([str(sva), 'eval', '--waves', str(dump), '--scope', e['scope'], *files, '--out', str(out)], capture_output=True, text=True)
            doc = json.loads(out.read_text()) if out.exists() else {'assertions': []}
            fails = {a['name']: [a['stats']['pass'], a['stats']['fail']] for a in doc['assertions'] if a['kind'] != 'cover' and a['stats']['fail']}
            missing = [a['name'] for a in doc['assertions'] if a.get('missing')]
            ok = len(doc['assertions']) == u['assertions'] and not missing and fails == e.get('fail', {}) and r.returncode == (1 if fails else 0)
            passes = sum(a['stats']['pass'] for a in doc['assertions'] if a['kind'] != 'cover')
            check(ok, f'third party {u["name"]} at {e["scope"]}: {len(doc["assertions"])} assertions, {passes} passing attempts, failures {fails}, missing {missing}, exit {r.returncode}')


def sva_examples(build):
    import json, subprocess
    sva = build / 'sva-target' / 'release' / 'sva'
    sva_wasm(build)
    if not sva.exists():
        return
    sva_third_party(build, sva)
    print('sva eval')
    for ex, (args, n, fails_) in SVA_EXAMPLES.items():
        dump = build / 'examples' / ex / f'{ex}.fst'
        if not dump.exists():
            continue
        out = build / 'sva' / f'{ex}.smoke.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([str(sva), 'eval', '--waves', str(dump), *args, '--out', str(out)], cwd=ROOT, capture_output=True, text=True)
        doc = json.loads(out.read_text()) if out.exists() else {'assertions': []}
        got = {a['name']: (a['stats']['pass'], a['stats']['fail']) for a in doc['assertions'] if a['kind'] != 'cover' and a['stats']['fail']}
        traces = all(a['trace'] for o in doc['assertions'] for a in o['attempts'] if a['result'] == 'fail')
        check(r.returncode == 1 and len(doc['assertions']) == n and got == fails_ and traces,
              f'sva eval {ex}: {len(doc["assertions"])} assertions, only the deliberate failures {got} (with traces), exit {r.returncode}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default='/tmp/wavefw', help='the Makefile BUILD directory (demo.html, demo_fst.html)')
    ap.add_argument('--out', help='screenshots (default: BUILD/shots)')
    a = ap.parse_args()
    a.out = a.out or os.path.join(a.build, 'shots')
    build = pathlib.Path(a.build)
    BUILT[:] = [build / 'demo.html', ROOT / 'work' / 'dump.html', ROOT / 'work' / 'test_stream_video.html', build / 'demo_fst.html']
    BUILT.extend(build / 'examples' / ex / f'{ex}{s}.html' for ex in EXAMPLES for s in ('', '_all'))
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
                if path == PAGES[0] and scheme == 'light':
                    interact(page)
                    sorting(page)
                    settings(page)
                    styles(page)
                    highlight(page)
                    cursor(page)
                    themes(page)
                    bookmarks(page)
                    sva_docs(page)
                    sva_units(page)
                if path in BUILT and scheme == 'light':
                    if path.name == 'test_stream_video.html':
                        hierarchy(page)
                        find(page)
                        deep(page)
                    if path.name == 'demo_fst.html':
                        fst(page)
                    if path.stem in EXAMPLES:
                        example(page, path.stem)
                        sva_page(page, path.stem)
                    if path.stem == 'fsm_all':
                        fsm_vcd(page)
                    big(page)
                shot = os.path.join(a.out, f'{path.stem}_{scheme}.png')
                page.screenshot(path=shot, full_page=True)
                print('  shot ' + shot)
                page.close()
        spike = pathlib.Path(a.build) / 'sva' / 'spike.html'   # make sva-spike: sva-core as WebAssembly in a page
        if spike.exists():
            print(spike.name)
            page = b.new_page()
            errs = []
            page.on('pageerror', lambda e: errs.append(str(e)))
            page.goto(spike.as_uri())
            page.wait_for_function('window.SPIKE', timeout=10000)
            s = page.evaluate('window.SPIKE')
            got = [(x['start'], x['result'], x['end']) for x in s['report']['attempts']]
            check(not errs and got == [(1, 'pass', 3), (4, 'fail', 7), (8, 'disabled', 9), (11, 'active', 11)],
                  f'sva spike: the WebAssembly build gives the native results {got} ({s["wasm"]} B, one call {s["callUs"]:.0f} µs)')
            tv = s['tv']
            want = {'attempts': 32764, 'pass': 2016, 'fail': 32, 'vacuous': 30716, 'disabled': 0, 'active': 0, 'capped': 0}
            check(tv['cycles'] == 32768 and tv['stats'] == want and tv['ms'] < 1000,
                  f'sva spike: evaluate(parsed, tvSampler) over 32768 clock edges in {tv["ms"]:.0f} ms (< 1 s): {tv["stats"]}')
            page.close()
        sva_bind(b, build)
        sva_hardening(b, build)
        sva_waves(b, build)
        sva_report(b, build)
        sva_report_hardening(b, build)
        b.close()
    sva_examples(build)
    print('\nFAILED: ' + str(len(fails)) if fails else '\nall checks passed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
