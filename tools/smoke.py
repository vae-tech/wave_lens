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
import argparse, os, pathlib, re, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = [ROOT / 'example.html', ROOT / 'tools' / 'conformance.html']
BUILT = [pathlib.Path('/tmp/wavefw_demo.html'), ROOT / 'dump.html', ROOT / 'test_stream_video.html',   # from make html, optional
         pathlib.Path('/tmp/wavefw_demo_fst.html')]                                                      # make demo-fst
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
                    highlight(page)
                    cursor(page)
                    themes(page)
                    bookmarks(page)
                if path in BUILT and scheme == 'light':
                    if path.name == 'test_stream_video.html':
                        hierarchy(page)
                        find(page)
                        deep(page)
                    if path.name == 'wavefw_demo_fst.html':
                        fst(page)
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
