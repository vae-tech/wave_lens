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

The hierarchy, find and virtualisation checks run on a synthetic page (BUILD/smoke/synth.html: a VCD of 2060 signals
in 255 scopes, 8 levels deep, made here and built with mkconfig.py + mkhtml.py), so they need nothing but a clone;
work/test_stream_video.html gets them too when it is there. Every check belongs to a section (--list); a FAIL names
it, --only runs some of them. A section or a page whose build product is missing is SKIPPED with the make target that
builds it, and the summary counts them: --strict (make smoke STRICT=1, make check) fails on any skip. An exception in a
section (a timeout, a locator that matches two elements) is a FAIL of that section with a PNG of its pages under
BUILD/smoke/<section>-error.png, and the other sections still run. An action or a wait without its own timeout gives
up after 15 s. Time limits are for a desktop machine; SMOKE_TIME_SCALE=3 allows three times as much (the 15 s too) on
a slow or loaded one.

  python3 tests/smoke.py [--build out] [--out out/shots] [--strict] [--only find,sva_bind] [--list]
  (no -I: playwright is usually a user-site install)
"""
import argparse, json, os, pathlib, re, subprocess, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGES = [ROOT / 'docs' / 'index.html', ROOT / 'tests' / 'conformance.html']
BUILT = []   # pages from make html / make demo-fst, checked when they exist (set in main from --build)
fails = []
skips = []   # (section, what is missing, the make target that builds it)
SECTION = ['pages']   # the section the checks belong to (run() sets it)
ONLY = set()
SCALE = float(os.environ.get('SMOKE_TIME_SCALE', '1'))   # time limits × SCALE


COUNT = [0, 0]   # checks, pages opened
ERRDIR = ['.']   # where a failed section's PNGs go (BUILD/smoke, set in main)
TIMEOUT = 15000 * SCALE   # ms: an action or a wait without its own timeout (playwright's default is 30 s)


def check(cond, msg):
    COUNT[0] += 1
    print(('  ok   ' if cond else f'  FAIL [{SECTION[0]}] ') + msg)
    if not cond:
        fails.append(f'[{SECTION[0]}] {msg}')


def skip(what, how):
    """A build product the current section needs is not there: counted, printed with the target that makes it."""
    skips.append((SECTION[0], str(what), how))
    print(f'  SKIP [{SECTION[0]}] {what} is missing ({how})')


def need(*paths, how):
    """True when every path exists, else a skip of the current section."""
    missing = [x for x in paths if not pathlib.Path(x).exists()]
    for x in missing:
        skip(x, how)
    return not missing


def want(name):
    return not ONLY or name in ONLY


def run(name, fn, *args):
    """One section: skipped by --only, named in its FAIL lines. An exception in it (a playwright timeout, a locator
    that matches two elements, a KeyError) is one FAIL of that section with a PNG of its pages, and the run goes on."""
    if not want(name):
        return
    SECTION[0], prev = name, SECTION[0]
    try:
        fn(*args)
    except Exception as e:   # noqa: BLE001 — any error of a section is its failure, not the end of the run
        first = (str(e).strip().splitlines() or [''])[0][:200]
        COUNT[0] += 1
        print(f'  FAIL [{name}] {type(e).__name__} in {fn.__name__}: {first}')
        fails.append(f'[{name}] {type(e).__name__} in {fn.__name__}: {first}')
        error_shots(name, args)
    finally:
        SECTION[0] = prev


def error_shots(name, args):
    """PNGs of what a failed section had open (BUILD/smoke/<section>-error*.png); its own pages are closed after."""
    own = args and hasattr(args[0], 'contexts')   # a browser: the section opened its pages and leaked them
    pages = [pg for c in args[0].contexts for pg in c.pages] if own else [args[0]] if args and hasattr(args[0], 'screenshot') else []
    os.makedirs(ERRDIR[0], exist_ok=True)
    for i, pg in enumerate(pages):
        try:
            path = os.path.join(ERRDIR[0], f'{name}-error{i or ""}.png')
            pg.screenshot(path=path, full_page=True, timeout=10000)
            print(f'  shot {path}')
        except Exception:   # noqa: BLE001 — a page that cannot be shot (crashed, closed) is not a second failure
            pass
        if own:
            try:
                pg.close()
            except Exception:   # noqa: BLE001
                pass


def until(page, expr, timeout=3000):
    """Wait until a page expression is true; False (not an exception) when it does not become true in time."""
    try:
        page.wait_for_function(expr, timeout=timeout * SCALE)
        return True
    except Exception:   # noqa: BLE001 — the check after it says what is wrong
        return False


def settle(page):
    """Two animation frames: the viewers redraw in requestAnimationFrame, the next check reads what they drew."""
    page.evaluate('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


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
    page.keyboard.down('Control'); page.mouse.wheel(0, -300); page.keyboard.up('Control')
    settle(page)
    check(cur.inner_text().split('view')[1] != span0.split('view')[1], f'ctrl+wheel zoom changes span ({span0.split("·")[1].strip()} -> {cur.inner_text().split("·")[1].strip()})')
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
    settle(page)
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
    # float (IEEE 754 of 16 / 32 / 64 bits) and fixed point q<F> / sq<F>: the page and vcd2wavedrom.py write the same text
    cases = [('3f800000', 32, 'float'), ('c0490fdb', 32, 'float'), ('3c00', 16, 'float'), ('400921fb54442d18', 64, 'float'), ('00000001', 32, 'float'),
             ('cafe0001', 32, 'float'), ('7f800000', 32, 'float'), ('4b189680', 32, 'float'), ('0180', 16, 'q8'), ('ff80', 16, 'sq8'), ('0001', 16, 'sq15'), ('fffe', 16, 'q1'), ('12', 8, 'float')]
    jsv = page.evaluate("cs => cs.map(([v, w, r]) => WaveFW.decode({ width: w }, v, r))", cases)
    sys.path.insert(0, str(ROOT / 'tools')); import vcd2wavedrom as v2w
    pyv = [v2w.label(v, w, None, r) for v, w, r in cases]
    check(jsv == pyv and jsv[:4] == ['1', '-3.141593', '1', '3.14159265358979'] and jsv[8:11] == ['1.5', '-0.5', '0.000030517578125'] and jsv[-1] == '0x12',
          f'radix float and fixed point (q8, sq15, exact): the page and vcd2wavedrom.py agree {jsv}')
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
    look = v.locator('.names').evaluate("""n => { const hl = [...n.querySelectorAll('.row.hl')], cs = e => getComputedStyle(e);
        return [[...new Set(hl.map(e => cs(e).boxShadow))], n.querySelectorAll('.row.tint').length,
            [...new Set([...n.querySelectorAll('.mk[aria-checked="true"]')].map(m => cs(m).backgroundColor))]]; }""")
    check(n('hl') == 5 and look[0] == ['none'] and look[1] == 0 and len(look[2]) == 1,
          f'a second instance: no tint, no bar, no colour per instance: the marks of both in one colour {look}')
    rows.filter(has_text='clk').locator('.n').click(modifiers=['Control'])
    check(n('hl') == 6 and btn.inner_text() == 'Highlight: 3 ✕', 'ctrl+click a name highlights it too')
    run0 = page.evaluate("(() => { const v = document.getElementById('ex-hl-view').waveView; return [v.picks.size, WaveFW.internal.peek(v).vis.filter(r => r.type === 'sig').map(r => r.name)]; })()")
    sig = run0[1]; first, last = sig[0], sig[3]
    page.evaluate("(() => { document.getElementById('ex-hl-view').waveView.highlight(null); })()")
    rows.filter(has_text=first).first.locator('.n').click(modifiers=['Control']); rows.filter(has_text=last).first.locator('.n').click(modifiers=['Control', 'Shift'])
    run = page.evaluate(f"""(() => {{ const v = document.getElementById('ex-hl-view').waveView, i = WaveFW.internal.peek(v).vis.findIndex(r => r.name === {json.dumps(first)}), j = WaveFW.internal.peek(v).vis.findIndex(r => r.name === {json.dumps(last)});
        return [WaveFW.internal.peek(v).vis.slice(i, j + 1).filter(r => r.type === 'sig').every(r => v.picks.has(r)), v.picks.size, String(getSelection())]; }})()""")
    check(run[0] and run[1] >= 4 and run[2] == '', f'ctrl+shift+click: every row from the last ctrl+clicked name to this one highlighted, no text selected ({first} … {last}: {run})')
    page.evaluate("(() => { const v = document.getElementById('ex-hl-view').waveView; v.highlight(null); ['tx', 'irq', 'clk'].forEach(n => v.toggleHighlight(n)); })()")
    rx = v.locator('.names .row.grp', has_text='rx')
    rx.locator('.mk').click()
    check(n('dim') == 0 and rx.get_attribute('aria-expanded') == 'true', 'the mark on a group highlights it without folding it')
    rx.locator('.mk').click()
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    check(n('hl') == 0 and n('dim') == 0 and not btn.is_visible(), 'Esc clears the highlight')
    svg = page.evaluate("WaveFW.WaveSVG.toString(document.getElementById('ex-hl').textContent, {highlight: 'rx'})")
    check('opacity:0.3' in svg and 'var(--wave-hl1)' not in svg, 'static SVG dims the rows the highlight setting leaves out, no tint')
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
    check(abs(js('v.t0 + v.span / 2') - 1200000) < 1 and cs.input_value() == '200', f'key c zooms in on the cursor (Questa): centred, half the span ({cs.input_value()} ns)')
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
    ly, ry = js("[v.bmGeo.mids[0][2], ...(o => [o.y, o.y + o.h])(WaveFW.internal.peek(v).lay.find(o => o.row.type === 'lane'))]"), None
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
    sig = b4.locator('input.sig'); was = sig.input_value(); sig.fill('nope'); sig.press('Enter'); bad = sig.input_value()
    sig.fill('irq'); sig.press('Enter')
    js('(v.cursor = 8, v.draw(), 0)'); b4.locator('button[data-bm=here]').click()
    check(bad == was == 'bus.req' and js('[v.bms[3].signal, v.bms[3].t]') == ['irq', 8] and b4.locator('.eg').inner_text() == '↓' and v.locator('.notes datalist option').count() == js('v.M.rows.filter(r => r.type === "sig").length'),
          f'the signal field (one datalist of the signals, an unknown name refused {bad!r}) and the cursor button change signal and time {js("[v.bms[3].signal, v.bms[3].t]")} {b4.locator(".eg").inner_text()!r}')
    b4.locator('input.col').fill('#2f9e44')
    check(js('v.bms[3].color') == '#2f9e44' and 'rgb(47, 158, 68)' in b4.locator('.bn').get_attribute('style').replace('#2f9e44', 'rgb(47, 158, 68)'), 'colour picker colours the bookmark')
    box = v.locator('canvas').bounding_box()
    pos = lambda n: js(f'v.bmGeo.pos.get({n})')
    rowy = lambda name: js(f"(o => o.y + o.h / 2)(WaveFW.internal.peek(v).lay.find(o => o.row.name === '{name}'))")
    xof = lambda t: js(f'({t} - v.t0) * v.canvas.getBoundingClientRect().width / v.span')
    p2 = pos(2); page.mouse.move(box['x'] + p2[0], box['y'] + p2[1]); page.mouse.down()
    page.mouse.move(box['x'] + xof(9.05), box['y'] + rowy('data'), steps=6); page.mouse.up()
    check(js('[v.bms[1].t, v.bms[1].signal]') == [9, 'bus.data'], f'dragging circle 2 moves it to another row and time, snapped to the edge ({js("[v.bms[1].t, v.bms[1].signal]")})')
    # lifted: dragged onto the top quarter of its row, the circle goes into a lane above the signal (a leader down to it)
    top = js("(o => o.y + 2)(WaveFW.internal.peek(v).lay.find(o => o.row.name === 'data'))"); p2 = pos(2)
    page.mouse.move(box['x'] + p2[0], box['y'] + p2[1]); page.mouse.down(); page.mouse.move(box['x'] + p2[0], box['y'] + top, steps=6); page.mouse.up()
    up = js("[v.bms[1].lift, v.bmGeo.pos.get(2)[1], (o => [o.y, o.y + o.h / 2])(WaveFW.internal.peek(v).lay.find(o => o.row.name === 'data')), v.rowsL.some(r => r.type === 'lane' && r.ids.includes('b:bus.data')), v.bookmarks()[1].lift]")
    p2 = pos(2); page.mouse.move(box['x'] + p2[0], box['y'] + p2[1]); page.mouse.down(); page.mouse.move(box['x'] + p2[0], box['y'] + rowy('data') + 4, steps=6); page.mouse.up()
    down = js("[v.bms[1].lift, v.rowsL.some(r => r.type === 'lane' && r.ids.includes('b:bus.data'))]")
    bl.nth(1).locator('button[data-bm=lift]').click(); btn = js("[v.bms[1].lift, v.bmGeo.pos.get(2)[1] < (o => o.y)(WaveFW.internal.peek(v).lay.find(o => o.row.name === 'data'))]")
    bl.nth(1).locator('button[data-bm=lift]').click()
    check(up[0] is True and up[1] < up[2][0] and up[3] and up[4] is True and down == [False, False] and btn == [True, True] and not js('v.bms[1].lift'),
          f'a circle dragged to the top of its row goes into a lane above the signal (kept in the JSON), lower down back on the row; ↥ does the same {up} {down} {btn}')
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
    page.reload(); settle(page)
    check(bl.count() == 4 and al.count() == 2, 'bookmarks and arrows are kept in the browser over a reload')
    v.locator('.notes button[data-bm=clear]').click()
    check(bl.count() == 0 and not v.locator('.notes').is_visible(), 'Clear removes them')
    page.reload(); settle(page)
    check(bl.count() == 3 and al.count() == 2, "after a reload the page's own bookmarks are back")


# the hierarchy / find / virtualisation checks: the synthetic page of synth_page() and the user's test_stream_video page
SYNTH = {'top': 'tb_top', 'inst': 'dut_i', 'fuzzy': 'pxvd', 'hit': 's_pix_valid', 'path': 'dev.fifo_s_val', 'mod': 'dev', 'leaf': 'fifo_s_val', 'view': 'all'}
TSV = {'top': 'tb_cxp_top', 'inst': 'cxp_device_top_i', 'fuzzy': 'pxvd', 'hit': 's_pix_valid', 'path': 'dev.fifo_s_val', 'mod': 'dev', 'leaf': 'fifo_s_val', 'view': 'all'}


def find(page, P):
    v = page.locator('.wv').first
    q, cnt = v.locator('input.q'), v.locator('.find .cnt')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    pre = js('[...WaveFW.internal.peek(v).collapsed].sort((a, b) => a - b)')   # the folding before the search
    q.fill(P['fuzzy']); settle(page)
    names = js("[...v.found.keys()].map(r => r.name)")
    sub = lambda n: re.search('.*'.join(P['fuzzy']), n) is not None
    check(P['hit'] in names and all(sub(n) for n in names) and cnt.inner_text() == f'{len(names)} found',
          f'fuzzy "{P["fuzzy"]}": letters in order, not contiguous {sorted(set(names))[:8]} ({cnt.inner_text()})')
    nf = len(names)
    marks = v.locator('.names .row .n b.fm').first.evaluate("b => b.closest('.n').innerHTML")
    check('<b class="fm">p</b>' in marks and '<b class="fm">v</b>' in marks, 'matched letters are marked in the names')
    folded = js("Object.keys(v.M.groups).length - WaveFW.internal.peek(v).collapsed.size")
    need = js("new Set([...v.found.keys()].flatMap(r => r.anc)).size")
    check(folded == need and v.locator('.names .row.hl').count() >= len(names) and v.locator('.names .row.dim').count() > 0,
          f'Open: only the {need} modules on the way to a match are open; Highlight: found rows in front')
    q.press('Enter'); sel = js('v.sel && v.sel.full'); q.press('Enter'); sel2 = js('v.sel && v.sel.full')
    check(sel and sel2 and sel != sel2 and cnt.inner_text().startswith('2 / '), f'Enter steps through the matches ({sel} -> {sel2})')
    nxt, prv = v.locator('button[data-act=fnext]'), v.locator('button[data-act=fprev]')
    nxt.click(); a1 = cnt.inner_text(); prv.click(); prv.click(); a2 = cnt.inner_text()
    v.locator('canvas').evaluate('c => c.focus({ preventScroll: true })')
    page.keyboard.press('n'); a3 = cnt.inner_text(); page.keyboard.press('Shift+N'); a4 = cnt.inner_text()
    check(nf >= 3 and [a1, a2, a3, a4] == [f'{k} / {nf}' for k in (3, 1, 2, 1)], f'‹ › buttons and n / N (vim) step through the matches {[a1, a2, a3, a4]}')
    # each match lands in the middle of the waves (unless the scroll ends first)
    mid = []
    for _ in range(4):
        page.keyboard.press('n')
        mid.append(js("""(() => { const q = WaveFW.internal.peek(v).namesEl.querySelector('.row.sel').getBoundingClientRect(), own = v.root.classList.contains('wv-scroll'),
            box = own ? v.bodyEl.getBoundingClientRect() : { top: 0, bottom: innerHeight }, d = q.top + q.height / 2 - (box.top + v.hdrH + box.bottom) / 2,
            end = own ? (v.bodyEl.scrollTop <= 0 || v.bodyEl.scrollTop + v.bodyEl.clientHeight >= v.bodyEl.scrollHeight - 1) : (scrollY <= 0 || scrollY + innerHeight >= document.documentElement.scrollHeight - 1);
            return [Math.round(d), end]; })()"""))
    check(all(abs(d) <= 2 or end for d, end in mid) and sum(abs(d) <= 2 for d, _ in mid) >= 2, f'n: the match in the middle of the waves (offset px, at the scroll end) {mid}')
    q.fill(P['path']); settle(page)
    fp = js("[...v.found.keys()].map(r => r.full)")
    check(fp and all(P['leaf'] in p.rsplit('.', 1)[1] and P['mod'] in p for p in fp), f'"a.b": a below a module path, b in the name {fp[:6]} ({len(fp)})')
    v.locator('input.fcol').fill('#2f9e44'); v.locator('button[data-act=fpaint]').click()
    painted = js("[[...v.found.keys()].every(r => v.strokeOf(r) === '#2f9e44'), [...v.found.keys()].some(r => r.stroke === '#2f9e44')]")
    check(painted == [True, False] and v.locator('button[data-act=funpaint]').is_visible(), f'Paint recolours the found signals in this viewer, the model rows stay as they are {painted}')
    hp = js("""(() => { const was = v.picks, r = v.M.rows.find(r => r.type === 'sig' && !v.found.has(r) && v.strokeOf(r) !== '#2f9e44'); v.picks = new Map([[r, 0]]);
        v.paint('#1971c2'); const out = [v.strokeOf(r), [...v.found.keys()].every(f => v.strokeOf(f) === '#1971c2')]; v.picks = was; return out; })()""")
    check(hp == ['#1971c2', True], f'Paint recolours the highlighted signals too (ctrl+click, the mark), not only the found ones {hp}')
    v.locator('button[data-act=fopen]').click()
    check(js('[...WaveFW.internal.peek(v).collapsed].sort((a, b) => a - b)') == pre, f'Open off: the folding from before the search is back ({len(pre)} folded)')
    v.locator('button[data-act=fopen]').click()
    page.evaluate("window.__c = null; navigator.clipboard.writeText = t => (window.__c = t, Promise.resolve())")
    v.locator('button[data-act=fcopy]').click()
    lines = (page.evaluate('window.__c') or '').split('\n')
    check(len(lines) == js('v.found.size') and all(l.startswith(P['top'] + '.') for l in lines), f'Copy puts the full paths of the found rows on the clipboard ({len(lines)} lines)')
    q.press('Enter'); q.press('Enter')
    body = v.locator('.body')
    picked = js('v.sel && v.sel.full')
    js(f'(v.toggleHighlight("{P["top"]}"), 0)')
    way = js('v.fiRow.anc'); y0, t0 = js('v.rowTop(v.fiRow)'), js('v.t0'); row = js('v.fiRow.full')
    q.press('Escape'); settle(page)
    want = sorted(set(pre) - set(way)); y1 = js(f"v.rowTop(v.M.rows.find(r => r.full === '{row}'))")
    end = js("(() => { const own = v.root.classList.contains('wv-scroll'), e = own ? v.bodyEl : document.documentElement, top = own ? e.scrollTop : scrollY; return top <= 0 || top + e.clientHeight >= e.scrollHeight - 1; })()")
    check(js('[v.found.size, v.picks.size, v.sel]') == [0, 0, None] and v.locator('.names .row.dim, .names .row.hl, .names .row.sel').count() == 0
          and js('[...WaveFW.internal.peek(v).collapsed].sort((a, b) => a - b)') == want and js('v.t0') == t0 and y1 is not None and (abs(y1 - y0) <= 1 or end),
          f'Esc resets search, highlight and selection; the folding from before the search is back but the way to {row} ({len(want)} folded), the time stays, the row as far as the scroll goes ({y0:.0f} -> {y1:.0f} px)')
    js(f'(v.toggleHighlight("{P["top"]}"), 0)'); js(f'(v.select("{picked}"), 0)')
    v.locator('canvas').evaluate('c => c.focus({ preventScroll: true })'); page.keyboard.press('Escape')
    check(js('[v.picks.size, v.sel]') == [0, None] and v.locator('.names .row.hl').count() == 0, 'Esc on the waves clears highlighted and selected signals')
    v.locator('.names .row:not(.grp)').nth(2).locator('.n').click()
    focus, s1 = page.evaluate('document.activeElement.tagName'), js('v.sel && v.sel.name')
    page.keyboard.press('Escape')
    check(focus == 'CANVAS' and s1 and js('v.sel') is None, f'a click on a name gives the waves the keys: Esc right after it clears the selection ({s1})')
    page.evaluate('document.activeElement.blur()'); js(f'(v.select("{picked}"), 0)'); page.keyboard.press('Escape')
    check(js('v.sel') is None, 'Esc with the focus on the page resets the viewer used last')
    for key in ('Escape', 'Control+c'):   # on the waves (canvas focused) Esc and ctrl+C end the search too
        q.fill(P['fuzzy']); settle(page)
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
    check(js("v.painted.size === 0 && v.M.rows.every(r => v.strokeOf(r) === (r.stroke || v.groupStroke.get(r)))") and not v.locator('button[data-act=funpaint]').is_visible(), 'Unpaint gives the signals their own colours back')
    # the options, as in grep / VS Code: Full (the whole name), Aa (the case), .* (a regular expression; alt+C W R in the field)
    hit = P['hit']; opt = lambda a: v.locator(f'button[data-act={a}]')
    opt('fword').click(); q.fill(hit.upper()); settle(page); full = js("[...v.found.keys()].map(r => r.name)")
    opt('fcase').click(); settle(page); cased = js('v.found.size')
    q.fill(hit); settle(page); cased2 = js("[...v.found.keys()].map(r => r.name)")
    opt('fword').click(); opt('fcase').click(); q.focus(); page.keyboard.press('Alt+r')
    rx = '^' + re.escape(hit[:2]) + '.*' + re.escape(hit[-2:]) + '$'; q.fill(rx); settle(page)
    rn = js("[...v.found.keys()].map(r => r.name)"); rmark = v.locator('.names .row .n b.fm').count()
    q.fill('a('); settle(page); bad = [cnt.inner_text(), js('v.found.size')]
    q.fill('\\<' + hit + '\\>'); settle(page); vim = js("[...v.found.keys()].map(r => r.name)")
    st = js('v.state().config'); page.keyboard.press('Alt+r'); off = js('[v.findCase, v.findWord, v.findRegex]')
    check(full and all(n.lower() == hit.lower() for n in full) and cased == 0 and cased2 and all(n == hit for n in cased2)
          and rn and all(re.search(rx, n, re.I) for n in rn) and rmark > 0 and bad == ['bad regex', 0] and hit in vim
          and st.get('findRegex') is True and off == [False, False, False],
          f'Full: the whole name; Aa: the case; .* a regular expression (alt+R), a bad one said, \\< \\> as in vim; kept in the state {full[:3]} {cased} {rn[:4]} {bad} {vim[:3]}')
    q.fill(''); settle(page)


def hierarchy(page, P):
    v = page.locator('.wv').first
    grp = v.locator('.names .row.grp')
    check(grp.first.inner_text().strip().endswith(P['top']), f'scopes are groups, top first ({grp.first.inner_text().strip()!r})')
    check(v.locator('.names .row.grp[aria-expanded=false]').count() > 0, 'fold: 2 starts deep scopes folded')
    bgs = v.locator('.names').evaluate("""n => { const bg = e => e && getComputedStyle(e).backgroundColor;
        return [bg(n.querySelector('.row.grp[aria-expanded=false]:not(.sel)')), bg(n.querySelector('.row.grp[aria-expanded=true]')), getComputedStyle(n.closest('.wv')).backgroundColor]; }""")
    check(bgs[0] == bgs[2] and bgs[1] != bgs[2], f'a folded module on the plain background, an open one shaded {bgs}')
    late = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, seen = new Set(), bad = [];
        for (const r of WaveFW.internal.peek(v).vis) { const p = r.anc.length ? r.anc[r.anc.length - 1] : -1;
          if (r.type === 'group') seen.add(p); else if (r.type === 'sig' && seen.has(p)) bad.push(r.full); }
        return bad; })()""")
    check(late == [], f'groupOrder "last": in every module its signals come before its sub-modules {late[:3]}')
    bg = page.evaluate("""(() => { const n = document.querySelector('.wv .names'), c = s => n.querySelector('.row:not(.grp)' + s), b = e => e && getComputedStyle(e).backgroundColor;
        return [b(c('.alt')), b(c(':not(.alt)'))]; })()""")
    check(v.locator('.names .row.alt').count() > 0 and page.evaluate("document.querySelector('.wv').waveView.band.size") > 0 and bg[0] and bg[0] != bg[1],
          f'moduleShading: neighbouring instances on two backgrounds {bg}')
    t = v.locator('.names .row:not(.grp) .n').nth(0).get_attribute('title')
    check(t and t.startswith(P['top'] + '.'), f'names carry the full path as tooltip ({t})')
    dev = v.locator('.names .row.grp', has_text=P['inst']).first
    dev.hover(); dev.locator('.mk').click()
    covered = page.evaluate(f"(() => {{ const M = WaveFW.parse(WAVES.{P['view']}); return M.rows.filter(r => r.type === 'sig' && r.full.includes('.{P['inst']}.')).length; }})()")
    check(v.locator('.names .row.hl').count() > 10 and v.locator('.names .row.dim').count() > 10, f'highlighting the instance {P["inst"]} ({covered} signals in it) dims the other rows')
    dev.locator('.mk').click()
    n0 = v.locator('.names .row').count()
    v.locator('button[data-act=collapse]').click()
    n1 = v.locator('.names .row').count()
    v.locator('button[data-act=expand]').click()
    n2 = v.locator('.names .row').count()
    check(n1 == 1 and n2 > n0, f'Collapse folds every instance, Expand opens all ({n0} -> {n1} -> {n2} rows)')
    same = page.evaluate(f"(() => {{ const M = WaveFW.parse(WAVES.{P['view']}), s = M.rows.filter(r => r.src && r.src.same); return [s.length, s.filter(r => r.tr.length > 2).length]; }})()")
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
        # the FST written with --trace-structs: status (uart_pkg::rx_status_t) is a struct scope; its row the whole value
        stv = page.evaluate("""(() => { const e = [...document.querySelectorAll('.wv')].find(e => e.waveView && Object.values(e.waveView.M.groups).some(g => g.kind === 'struct'));
            if (!e) return null; const v = e.waveView, g = Object.values(v.M.groups).find(g => g.kind === 'struct');
            return [g.path, g.sig.width, v.M.rows.filter(r => r.anc.includes(g.id)).map(r => r.name), [100000, 420000, 905000].map(t => v.valueAt(g.sig, t)),
              e.querySelector('.names .row.grp .kd') && e.querySelector('.names .row.grp .kd').textContent]; })()""")
        check(stv and stv[:3] == ['status', 16, ['state', 'bit_cnt', 'valid', 'frame_err', 'data']] and stv[4] == '{}',
              f'fsm (FST, --trace-structs): the struct scope status, {{}} in the names, its row the whole 16-bit value {stv}')
        STRUCT_VALS[:] = stv[3] if stv else []


STRUCT_VALS = []   # fsm.html's struct values, for fsm_all.html


def fsm_vcd(page):
    v = page.locator('.wv').first
    st = v.locator('.names .row:not(.grp)', has_text='state').first
    st.locator('.n').click()
    v.locator('button[data-act=next]').click()
    check(st.locator('.v').inner_text() == 'START', f'fsm_all (VCD + mkconfig --sv): state names from the SV package ({st.locator(".v").inner_text()})')
    # the VCD has status as one 16-bit vector: mkconfig --sv gave it the fields of uart_pkg::rx_status_t
    fv = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, g = Object.values(v.M.groups).find(g => g.kind === 'struct');
        if (g) { g.anc.forEach(id => WaveFW.internal.peek(v).collapsed.delete(id)); v.renderNames(); v.cursor = 420000; v.draw(); }
        return g && [g.path, g.sig.width, v.M.rows.filter(r => r.anc.includes(g.id)).map(r => [r.name, r.width]), [100000, 420000, 905000].map(t => v.valueAt(g.sig, t)),
          v.valueAt(v.M.rows.find(r => r.full === 'fsm_tb.status.state'), 420000), v.vals && v.rowEl(g).querySelector('.v').textContent]; })()""")
    check(fv and fv[0] == 'fsm_tb.status' and fv[1] == 16 and [n for n, _ in fv[2]] == ['state', 'bit_cnt', 'valid', 'frame_err', 'data'] and [w for _, w in fv[2]] == [3, 3, 1, 1, 8]
          and fv[4] == 'STOP' and fv[5] == fv[3][1] and (not STRUCT_VALS or fv[3] == STRUCT_VALS),
          f'fsm_all (VCD + mkconfig --sv): the 16-bit status taken apart into its fields (state by name), the same whole values as the FST\'s struct scope {fv} {STRUCT_VALS}')


def deep(page, P):
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    check(js('Math.max(...v.M.rows.map(r => r.depth))') >= 8 and js('Object.keys(v.M.groups).length') > 200, 'every level of the hierarchy is on the page')
    js('(v.expandAll(), 0)')
    n, H, hc, ch = js('[WaveFW.internal.peek(v).vis.length, WaveFW.internal.peek(v).lay.H, v.hc, v.canvas.getBoundingClientRect().height]')
    check(n > 1700 and H > 32767 and hc == ch and hc < 1000, f'Expand: {n} rows, {H} px of rows, canvas only {ch:.0f} px (the visible part)')
    page.locator('.wv .body').first.evaluate('e => e.scrollTop = 20000'); settle(page)
    oy = js('WaveFW.internal.peek(v).oy')
    row = js(f"WaveFW.internal.peek(v).lay.find(o => o.row.type === 'sig' && o.y > {oy} + 100).row.full")
    check(oy == 20000 and js("document.querySelector('.wv canvas').getBoundingClientRect().top - document.querySelector('.wv .body').getBoundingClientRect().top") == 0,
          f'rows scroll under a canvas that stays in view (offset {oy}, first row {row})')
    js('(v.collapseAll(), 0)')


def big(page):
    t = page.evaluate('() => { const t0 = performance.now(); WaveFW.redrawAll(); return performance.now() - t0; }')
    check(t < 1500 * SCALE, f'redraw of all viewers takes {t:.0f} ms (< {1500 * SCALE:.0f})')
    v = page.locator('.wv').last
    v.locator('button[data-act=sort]').click()
    check(v.locator('button[data-act=sort]').inner_text() == 'Sort: A→Z', 'Sort works on the generated page')


def viewer(page):
    """Stage 9.4 on docs/index.html: modifier keys, the wheel by its size, the exact cursor, the mouse buttons, the value
    under the pointer, storage keys, data-theme on an element, a long value, find edge cases, destroy, the keyboard."""
    ex = '.bench > div.wv[data-wave="DEMO_WAVES.exact"]'
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('{ex}').waveView; return {e}; }})()")
    v = page.locator(ex); c = v.locator('canvas'); c.scroll_into_view_if_needed()
    js('(v.fit(), v.setSort("none"), 0)'); c.focus(); nb = js('v.bms.length')
    page.keyboard.press('Control+s'); page.keyboard.press('Control+m'); page.keyboard.press('Alt+0')
    check(js('[v.sort, v.bms.length]') == ['none', nb], f'ctrl+S, ctrl+M, alt+0 on the waves stay the browser\'s: no sort, no bookmark {js("[v.sort, v.bms.length]")}')
    page.keyboard.press('s')
    check(js('v.sort') == 'asc', 'the plain key s still sorts'); js('(v.setSort("none"), 0)')
    # the wheel by the size of its delta
    wheel = lambda **o: page.evaluate(f"""(() => {{ const v = document.querySelector('{ex}').waveView, b = v.canvas.getBoundingClientRect();
        v.canvas.dispatchEvent(new WheelEvent('wheel', Object.assign({{clientX: b.left + b.width / 2, clientY: b.top + 40, bubbles: true, cancelable: true}}, {json.dumps(o)}))); }})()""")
    zoom_in = lambda: js('(v.span = (v.M.t1 - v.M.t0) / 4, v.t0 = v.clamp(v.M.t0 + v.span), v.draw(), 0)')
    zoom_in(); s0 = js('v.span')
    wheel(deltaY=100); settle(page); r0 = js('v.span') / s0
    for _ in range(10): wheel(deltaY=-3, ctrlKey=True)
    settle(page); r1 = js('v.span') / s0
    zoom_in(); wheel(deltaY=100, ctrlKey=True); settle(page); r2 = js('v.span') / s0
    zoom_in(); wheel(deltaY=3, deltaMode=1, ctrlKey=True); settle(page); r3 = js('v.span') / s0
    zoom_in(); t0, ppt = js('v.t0'), js('v.pxPerT()'); wheel(deltaX=50); settle(page); dt = (js('v.t0') - t0) * ppt
    zoom_in(); t0b = js('v.t0'); wheel(deltaY=50, shiftKey=True); settle(page); dt2 = (js('v.t0') - t0b) * ppt
    check(r0 == 1 and abs(r1 - 0.7408) < 0.01 and abs(r2 - 1.2214) < 0.01 and abs(r3 - 1.1008) < 0.01 and abs(dt - 50) < 0.5 and abs(dt2 - 50) < 0.5,
          f'the wheel as in Questa: a notch scrolls (x{r0:.3f}); ctrl+wheel zooms by its size: ten pinch steps of -3 x{r1:.3f}, a notch x{r2:.3f}, 3 lines x{r3:.3f}; a swipe or shift+wheel of 50 px pans {dt:.1f} / {dt2:.1f} px')
    # the cursor reads exactly, at any zoom; a click puts it on a short time; bookmarks show the same
    js('(v.fit(), v.setCursor(1234567), 0)'); a = v.locator('.cur').inner_text()
    js('(v.span = 50000, v.t0 = v.clamp(1200000), v.draw(), 0)'); b = v.locator('.cur').inner_text()
    check('cursor 1.234567 µs' in a and 'cursor 1234.567 ns' in b, f'the cursor reads 1234567 ps whatever the zoom ({a.split("·")[0].strip()} / {b.split("·")[0].strip()})')
    box = c.bounding_box(); page.keyboard.down('Alt'); page.mouse.click(box['x'] + box['width'] * 0.371, box['y'] + 60); page.keyboard.up('Alt'); cur = js('v.cursor')
    q = js('(() => { const tpp = 1 / v.pxPerT(), e = 10 ** Math.floor(Math.log10(tpp)); return [1, 2, 5, 10].find(m => m * e >= tpp) * e; })()')
    check(abs(cur / q - round(cur / q)) < 1e-6, f'alt+click puts the cursor on a 1-2-5 step of a pixel ({cur} ps, step {q} ps)')
    # a click near an edge of a signal: the cursor on that edge (cursorSnap px); farther, or alt+click: a round time
    near = js("""(() => { const k = v.pxPerT(), o = WaveFW.internal.peek(v).lay.find(o => o.row.type === 'sig' && o.row.tr && o.row.tr.some((e, i) => i && e.t > v.t0 + v.span * 0.1 && e.t < v.t0 + v.span * 0.9));
        const e = o.row.tr.find((e, i) => i && e.t > v.t0 + v.span * 0.1 && e.t < v.t0 + v.span * 0.9); return [(e.t - v.t0) * k, o.y + o.h / 2, e.t, v.S.cursorSnap]; })()""")
    got = []
    for dx, alt in ((5, False), (5, True), (near[3] + 6, False)):
        if alt: page.keyboard.down('Alt')
        page.mouse.click(box['x'] + near[0] + dx, box['y'] + near[1])
        if alt: page.keyboard.up('Alt')
        got.append(js('v.cursor') == near[2])
    check(got == [True, False, False], f'a click 5 px from an edge puts the cursor on it; alt+click, or {near[3] + 6} px away, does not {got}')
    # the edge style from the bar: the waves drawn again, kept over a reload, in the saved state
    ws = v.locator('select.ws')
    sty = [ws.input_value()]; ws.select_option('questa')
    sty += [js('v.S.style'), js("JSON.parse(localStorage.getItem(v.lookKey)).style"), js('v.state().config.style')]
    page.reload(); page.wait_for_load_state('networkidle')
    sty += [ws.input_value(), js('v.S.style')]; ws.select_option('auto'); js('(v.setStyle(null), 0)'); sty.append(js('localStorage.getItem(v.lookKey)'))
    check(sty == ['auto', 'questa', 'questa', 'questa', 'questa', 'questa', None], f'the edge style list: vertical (questa) drawn, kept in this browser and in the state, back to the settings\' {sty}')
    keep = js('[v.bookmarks(), v.arrowList()]'); js('(v.setBookmarks([{n: 1, t: 1234567}]), 0)')
    check(v.locator('.notes input.tm').input_value() == '1.234567 µs', f'a bookmark shows its exact time ({v.locator(".notes input.tm").input_value()})')
    page.evaluate(f"document.querySelector('{ex}').waveView.setBookmarks(...{json.dumps(keep)})")
    # the right button: no cursor, no pan; the middle one (Questa): a drag zooms into the range, l the window before
    t0, cur = js('v.t0'), js('v.cursor')
    page.mouse.move(box['x'] + 100, box['y'] + 60); page.mouse.down(button='right'); page.mouse.move(box['x'] + 300, box['y'] + 60); page.mouse.up(button='right')
    check(js('[v.t0, v.cursor]') == [t0, cur], 'the right button neither pans nor moves the cursor')
    w0 = js('[v.t0, v.span]'); want = js('[v.t0 + 100 / v.pxPerT(), 200 / v.pxPerT()]')
    page.mouse.move(box['x'] + 100, box['y'] + 60); page.mouse.down(button='middle'); page.mouse.move(box['x'] + 200, box['y'] + 60, steps=3)
    band = js('!!v.zband'); page.mouse.move(box['x'] + 300, box['y'] + 60, steps=3); page.mouse.up(button='middle')
    w1 = js('[v.t0, v.span, v.cursor]'); c.focus(); page.keyboard.press('l'); w2 = js('[v.t0, v.span]')
    check(band and abs(w1[0] - want[0]) <= want[1] * 0.02 and abs(w1[1] - want[1]) <= want[1] * 0.02 and w1[2] == cur and w2 == w0,
          f'a middle-button drag over 200 px zooms into that range (the band shown while dragging, the cursor stays); l: the window before {w0} -> {w1} -> {w2}')
    # the keys as in Questa (i o f l, Tab, Home / End, PgDn) and vim (j k gg G zM zR, ]m, *)
    keys = []
    def press(*ks):
        for k in ks: page.keyboard.press(k)
    js('(v.fit(), v.select(null), 0)'); c.focus(); s1 = js('v.span')
    press('i'); keys.append(round(js('v.span') / s1, 3)); press('i', 'o'); keys.append(round(js('v.span') / s1, 3)); press('f'); keys.append(js('v.span') == s1)
    press('i', 'i', 'l'); keys.append(round(js('v.span') / s1, 3)); press('l')
    press('End'); keys.append(abs(js('v.t0 + v.span') - js('v.M.t1')) < 1e-6); press('Home'); keys.append(js('v.t0') == js('v.M.t0'))
    press('j', 'j'); a = js('v.sel && v.sel.full'); press('k'); b = js('v.sel && v.sel.full'); press('g', 'g'); g1 = js('v.sel && v.sel.full'); press('Shift+G'); g2 = js('v.sel && v.sel.full')
    sigs = js("WaveFW.internal.peek(v).vis.filter(r => r.type === 'sig' && r.tr).map(r => r.full)"); keys.append([a == sigs[1], b == sigs[0], g1 == sigs[0], g2 == sigs[-1]])
    js('(v.select(WaveFW.internal.peek(v).vis.filter(r => r.type === "sig" && r.tr && r.tr.length > 3)[0]), v.cursor = v.M.t0, v.draw(), 0)')
    press('Tab'); e1 = js('v.cursor'); press('Tab'); e2 = js('v.cursor'); press('Shift+Tab'); keys.append([e1 > js('v.M.t0'), e2 > e1, js('v.cursor') == e1])
    keys.append(js('document.activeElement === v.canvas'))
    press('Escape'); press('Tab'); keys.append(js('document.activeElement !== v.canvas'))   # nothing selected: Tab leaves the waves (no focus trap)
    c.focus()
    print('  keys ' + str(keys))
    vk = []
    keep = js('[v.bookmarks(), v.arrowList()]'); bt = js('[v.M.t0 + v.span * 0.3, v.M.t0 + v.span * 0.6]')
    js(f'(v.setBookmarks([{{n: 1, t: {bt[0]}}}, {{n: 2, t: {bt[1]}}}]), v.cursor = v.M.t0, 0)')
    press(']', 'm'); vk.append(js('v.cursor') == bt[0]); press(']', 'm'); vk.append(js('v.cursor') == bt[1]); press(']', 'm'); vk.append(js('v.cursor') == bt[0])
    press('[', 'm'); vk.append(js('v.cursor') == bt[1])
    page.evaluate(f"document.querySelector('{ex}').waveView.setBookmarks(...{json.dumps(keep)})")
    press('g', 'g', '*'); vk.append(js('[v.q, v.found.size > 0]') == [js('v.sel ? v.sel.name : v.q'), True]); press('Escape'); c.focus()
    page.evaluate("window.__c = null; navigator.clipboard.writeText = t => (window.__c = t, Promise.resolve())")
    press('g', 'g', 'y', 'y'); vk.append(page.evaluate('window.__c') == js('v.sel && v.sel.full'))
    ng = js('Object.keys(v.M.groups).length')
    press('z', 'Shift+M'); vk.append(js('WaveFW.internal.peek(v).collapsed.size') == ng); press('z', 'Shift+R'); vk.append(js('WaveFW.internal.peek(v).collapsed.size') == 0)
    press('g', 'x'); vk.append(js('WaveFW.internal.peek(v).collapsed.size') == 0)   # an unknown sequence does nothing
    check(all(vk), f'vim: ]m [m next / previous bookmark round the ends, * finds the selected name, yy copies it, zM / zR fold / open every group ({ng}) {vk}')
    check(keys[:6] == [0.5, 0.5, True, 0.5, True, True] and all(keys[6]) and all(keys[7]) and keys[8] and keys[9],
          f'keys as in Questa: i o zoom in / out, f full, l the window before the last zoom (i i l: x0.5), End / Home, Tab / shift+Tab the next / previous edge (the focus stays; nothing selected: Tab leaves the waves); vim: j k, gg, G {keys}')
    # the value under the pointer
    c.scroll_into_view_if_needed(); box = c.bounding_box()
    y = js("(o => o.y + o.h / 2 - WaveFW.internal.peek(v).oy)(WaveFW.internal.peek(v).lay.find(o => o.row.name === 'state'))")
    page.mouse.move(box['x'] + box['width'] * 0.5, box['y'] + y); tip = c.get_attribute('title') or ''
    check(tip.startswith('state = ') and '→' in tip and '@' in tip, f'the value under the pointer: {tip!r}')
    # storage keys: the bench and its lazy cards of one data-wave are told apart
    keys = page.evaluate("""[...document.querySelectorAll('[data-wave="DEMO_WAVES.exact"]')].filter(e => e.waveView).map(e => e.waveView.storeId)""")
    check(len(keys) >= 2 and len(set(keys)) == len(keys) and not keys[0].split(':')[-1].count('#'), f'viewers of one data-wave store apart {keys[:3]}')
    # a test viewer: data-theme on its element, a 32-bit binary value, find with "." and an alias, destroy
    page.evaluate("""(() => { const d = document.createElement('div'); d.id = 'wv-t94'; document.body.appendChild(d);
        window.__t94 = new WaveView(d, { signal: [['tb', { name: 'sel', path: 'tb.u.PSEL', tv: [[0, '0'], [10, '1']] },
          { name: 'a_rather_long_name', width: 32, radix: 'bin', tv: [[0, '0'], [10, 'deadbeef']] }]], time: { t0: 0, cycle: 10, t1: 40 } }, { cursor: 20 }); })()""")
    t = lambda e: page.evaluate(f'(() => {{ const v = window.__t94; return {e}; }})()')
    px = lambda: page.evaluate("(() => { const c = document.querySelector('#wv-t94 canvas'), d = window.devicePixelRatio || 1; return [...c.getContext('2d').getImageData(c.width - 4 * d, (40) * d, 1, 1).data].slice(0, 3); })()")
    p0 = px(); page.evaluate("document.querySelector('#wv-t94').dataset.theme = 'dark'"); settle(page); p1 = px()
    check(p0 != p1 and sum(p1) < sum(p0), f'data-theme on the element of the viewer redraws it in that theme ({p0} -> {p1})')
    w = page.evaluate("""(() => { const r = [...document.querySelectorAll('#wv-t94 .names .row')].find(e => e.textContent.includes('a_rather'));
        return [r.querySelector('.n').getBoundingClientRect().width, r.getBoundingClientRect().width, r.querySelector('.v').title]; })()""")
    check(w[0] >= 0.35 * w[1] and w[2] == '11011110101011011011111011101111', f'a 32-bit binary value leaves the name {w[0]:.0f} of {w[1]:.0f} px; its title has all the bits')
    f1 = t("(v.find('.'), [v.found.size, v.cntEl.textContent])"); f2 = t("(v.find('PSEL'), [...v.found.keys()].map(r => r.full))"); f3 = t("(v.find('u.sel'), v.found.size)")
    check(f1 == [0, ''] and f2 == ['tb.u.PSEL'] and f3 == 0 and t("(v.find('tb.sel'), v.found.size)") == 1,
          f'find: "." alone is no query {f1}, a signal shown as an alias is found by its leaf {f2}, the scope is the groups above (u.sel {f3})')
    n = page.evaluate("""(() => { let n = 0; const d = document.querySelector('#wv-t94'); d.addEventListener('wavefw:destroy', () => n++); d.remove(); WaveFW.upgrade(); return [n, WaveFW.views().includes(window.__t94)]; })()""")
    check(n == [1, False], f'a viewer whose element left the page is destroyed by the next upgrade (wavefw:destroy once, out of WaveFW.views()) {n}')
    # the keyboard: roles, one tab stop in the names, arrows walk and select, shift+→ moves the cursor
    roles = page.evaluate(f"""(() => {{ const r = document.querySelector('{ex}'); return [r.querySelector('canvas').getAttribute('role'), r.querySelector('.names').getAttribute('role'),
        r.querySelectorAll('.names .row[role=option]').length, r.querySelectorAll('.names .row[role=option][tabindex="0"]').length]; }})()""")
    js('(v.select(null), 0)'); v.locator('.names .row[role=option][tabindex="0"]').focus(); page.keyboard.press('ArrowDown'); page.keyboard.press('ArrowDown')
    walked = page.evaluate(f"[document.activeElement.textContent, document.querySelector('{ex}').waveView.sel && document.querySelector('{ex}').waveView.sel.name, document.activeElement.getAttribute('aria-selected')]")
    check(roles[:2] == ['application', 'listbox'] and roles[2] > 5 and roles[3] == 1 and walked[1] and walked[2] == 'true' and walked[1] in walked[0],
          f'keyboard: canvas role=application, names a listbox with one tab stop {roles}; ↓ ↓ walks the rows and selects {walked[1]!r}')
    c.focus(); cur0, sp = js('v.cursor'), js('v.span'); page.keyboard.press('Shift+ArrowRight')
    check(abs(js('v.cursor') - cur0 - sp / 100) < 1e-6, 'shift+→ moves the cursor a hundredth of the view')
    js('(v.select(null), v.fit(), 0)')


def viewer_big(page, P):
    """Stage 9.4 on a big page: a click under 10 ms without building the names again, Esc after a search gives back the
    folding from before it with the stepped row in place, print draws every row."""
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    js('(v.expandAll(), 0)'); settle(page)
    el0 = js('WaveFW.internal.peek(v).namesEl.children[5] === WaveFW.internal.peek(v).rowEls[4]')
    t = page.evaluate("""(async () => { const v = document.querySelector('.wv').waveView, t = [], keep = WaveFW.internal.peek(v).rowEls[10];
        for (let i = 0; i < 5; i++) { const n = WaveFW.internal.peek(v).namesEl.querySelectorAll('.row:not(.grp) .n')[3 + i], t0 = performance.now(); n.click(); t.push(performance.now() - t0);
          await new Promise(r => requestAnimationFrame(r)); }
        t.sort((a, b) => a - b); return [t[2], WaveFW.internal.peek(v).rowEls[10] === keep, WaveFW.internal.peek(v).vis.length]; })()""")
    check(el0 and t[1] and t[0] < 10 * SCALE, f'a click on a name with {t[2]} rows takes {t[0]:.1f} ms (< {10 * SCALE:.0f}) and keeps the rows of the names column')
    q, body = page.locator('.wv').first.locator('input.q'), page.locator('.wv .body').first
    q.fill(P['fuzzy']); settle(page); q.press('Enter'); q.press('Enter'); settle(page)
    row = js('v.fiRow && v.fiRow.full'); y0 = js('v.rowTop(v.fiRow)')
    q.press('Escape'); settle(page)
    after = js('[WaveFW.internal.peek(v).collapsed.size, v.found.size]'); r = js(f"v.M.rows.find(x => x.full === '{row}')"); y1 = js(f"v.rowTop(v.M.rows.find(x => x.full === '{row}'))")
    check(after == [0, 0] and y0 is not None and y1 is not None and abs(y1 - y0) <= 1, f'Esc after find + Open: every module open again as before the search {after}; the row stepped to stays in place ({y0:.0f} -> {y1:.0f} px)')
    page.emulate_media(media='print'); page.evaluate("dispatchEvent(new Event('beforeprint'))")
    pr = js("[[...v.wcol.querySelectorAll('canvas.wv-print')].reduce((s, c) => s + c.getBoundingClientRect().height, 0), WaveFW.internal.peek(v).lay.H, getComputedStyle(v.bodyEl).overflowY, v.wcol.querySelectorAll('canvas.wv-print').length]")
    page.evaluate("dispatchEvent(new Event('afterprint'))"); page.emulate_media(media='screen'); settle(page)
    check(abs(pr[0] - pr[1]) < 1 and pr[2] == 'visible' and pr[3] >= 2 and js("v.wcol.querySelectorAll('canvas.wv-print').length") == 0,
          f'print: every row on {pr[3]} canvases ({pr[0]:.0f} of {pr[1]} px), no scroll box; afterprint gives the screen canvas back')
    wd = page.evaluate("""(() => { const ck = [], d8 = []; for (let c = 0; c < 3000; c++) { ck.push([10 * c, '0'], [10 * c + 5, '1']); d8.push([10 * c, (c % 256).toString(16)]); }
        const el = document.body.appendChild(document.createElement('div')), w = new WaveFW.WaveView(el, { signal: [{ name: 'clk', tv: ck },
          { name: 'd', width: 8, tv: d8 }], time: { t0: 0, unit: 'ps' }, meta: { omitted: { why: 'config', paths: { 'tb.u': ['rd_ptr', 'wr_ptr'] } } } }, {}), d = w.toWaveDrom(0, 30000, w.M.rows.filter(r => r.type === 'sig'));
        const out = [Math.max(...d.signal.map(s => s.wave.length)), w.wdCut && w.wdCut.cells, w.wdCut && w.wdCut.to, d.foot.text, d.head.text];
        w.find('rd_ptr'); out.push(w.cntEl ? [w.cntEl.textContent, w.cntEl.dataset.ttl] : null); w.find('');
        out.push([20470, 20480, 20490].map(b => { const x = w.toWaveDrom(0, b, w.M.rows.filter(r => r.type === 'sig')); return [x.signal[1].wave.length, !!w.wdCut]; }));
        w.destroy(); el.remove(); return out; })()""")
    check(wd[0] == 2048 and wd[6] == [[2047, False], [2048, False], [2048, True]] and wd[1] == 2048 and wd[2] == 20485 and 'the first 2048 cycles of a range to 30' in wd[3] and wd[4].endswith('20.48 ns') and wd[5] and
          wd[5][0] == 'no match · 1 not in the page' and 'tb.u.rd_ptr' in wd[5][1] and '"show": false' in wd[5][1],
          f'WaveDrom of 3000 cycles: 2048 kept, the cut said in the foot and v.wdCut, the head ends where the cycles end {wd[3]!r} {wd[4]!r}; find: a name the config left out is said {wd[5]}; 2047 / 2048 / 2049 cycles {wd[6]}')
    g = page.evaluate("""(() => [2040, 2047].map(last => { const ck = [], d8 = [];   // the data idle from cycle last to 2900: a gap
        for (let c = 0; c < 3000; c++) { ck.push([10 * c, '0'], [10 * c + 5, '1']); if (c < last || c > 2900) d8.push([10 * c, (c % 256).toString(16)]); }
        const el = document.body.appendChild(document.createElement('div')), w = new WaveFW.WaveView(el, { signal: [{ name: 'clk', tv: ck },
          { name: 'd', width: 8, tv: d8 }], time: { t0: 0, unit: 'ps' } }, {});
        w.setGaps({ gaps: true }); const x = w.toWaveDrom(0, 30000, w.M.rows.filter(r => r.type === 'sig')), wv = x.signal[1].wave;
        const out = [wv.replace(/[|]/g, '').length, (wv.match(/[|]/g) || []).length, w.wdCut && w.wdCut.to, /idle/.test(x.foot.text)];
        w.setGaps(null); w.destroy(); el.remove(); return out; }))()""")
    check(g == [[2048, 1, 29055, True], [2048, 0, 20485, False]], f'WaveDrom cut by cycles next to a gap: one inside the 2048 cycles is kept and said; '
          f'one right after them is not taken in, the range ends at the last cycle {g}')
    js('(v.collapseAll(), 0)')


def viewer_fixes(page):
    """Review II, step 12.4: decode masks to the width, an empty ASCII value, a field outside its vector, analog refused
    on a bit, moveTo and l, the measured range and the second cursor in the picture (toSVG)."""
    r = page.evaluate("""(() => { const F = WaveFW, D = F.decode, warn = console.warn, warned = [];
      console.warn = (...a) => warned.push(a.join(' '));
      const M = F.parse({ signal: [{ name: 'v', width: 8, tv: [[0, 'ff']], fields: [{ name: 'hi', msb: 11, lsb: 8 }, { name: 'lo', msb: 3, lsb: 0 }] }] });
      console.warn = warn;
      const dec = [D({ width: 8 }, '1ff', 'signed'), D({ width: 8 }, '', 'ascii'), D({ width: 32 }, '1ffffffff', 'float'), D({ width: 8 }, 'ff', 'sq4')];
      const v = document.querySelector('#ex-handshake-view').waveView, bit = v.M.rows.find(r => r.type === 'sig' && r.width === 1 && r.tr.length > 2);
      v.setAnalog(bit, 3); const analogBit = !!bit.analog; v.setAnalog(bit, null);
      v.fit(); const w0 = [v.t0, v.span], t = v.M.t0 + (v.M.t1 - v.M.t0) * 0.9;
      v.zoom(0.25, 0); v.moveTo(t); const moved = [v.cursor === t, v.t0 <= t && t <= v.t0 + v.span]; v.zoomLast(); const back = v.t0 !== w0[0] || true;
      v.fit(); v.setRange(v.t0 + v.span * 0.2, v.t0 + v.span * 0.4); v.setCursor2(v.t0 + v.span * 0.3);   // inside the range: the picture is the range
      const svg = v.toSVG(), dTxt = v.rangeText().replace(/ /g, ' ');
      v.setRange(null); v.setCursor2(null);
      return { fields: M.rows.map(r => r.name), warned: warned.filter(w => w.includes('not inside')).length, dec, analogBit, moved, svgRange: svg.includes(dTxt.slice(0, 6)), svgDash: svg.includes('stroke-dasharray') };
    })()""")
    check(r['fields'] == ['v', 'lo'] and r['warned'] == 1, f'a field outside its vector is left out with a warning, not drawn as NaN {r["fields"]}')
    check(r['dec'] == ['-1', '""', 'nan', '-0.0625'], f'decode: a value wider than the signal keeps its low bits, an empty ASCII value, exact fixed point {r["dec"]}')
    check(not r['analogBit'] and r['moved'] == [True, True], f'analog is refused on a 1-bit row; moveTo puts the cursor at t with t in the window {r}')
    check(r['svgRange'] and r['svgDash'], f'the picture (toSVG) has the measured range with its Δ and the dashed second cursor {r}')


def wavefw_units(page):
    """wavefw/wavefw.js is the concatenation of wavefw/src/*.js (make wavefw), and the pure functions of the model."""
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'wavefwcat.py'), '--check'], capture_output=True, text=True)
    check(r.returncode == 0, 'wavefw/wavefw.js is the concatenation of wavefw/src/*.js' + (': ' + r.stderr.strip() if r.returncode else ''))
    got = page.evaluate("""(() => { const F = WaveFW, M = F.parse({ signal: [{ name: 'clk', wave: 'p..' }, ['g', { name: 'b', wave: '=.=', data: 'A B' }, {}, { name: 'a', tv: [[0, '0'], [5, '1']] }]],
        time: { t0: 0, cycle: 10 } });
      return { rows: M.rows.map(r => r.type + ':' + r.name), groups: Object.values(M.groups).map(g => g.path), t: [M.t0, M.t1, M.cycle], btr: M.rows[2].tr.map(o => [o.t, o.v]),
        fuzzy: [F.fuzzy('pxvd', 's_pix_valid') && F.fuzzy('pxvd', 's_pix_valid').idx, F.fuzzy('dvp', 's_pix_valid')],
        decode: [F.decode({ width: 8 }, 'ff', 'signed'), F.decode({ width: 4 }, 'a', 'bin'), F.decode({ width: 8 }, '41', 'ascii'), F.decode({ width: 3 }, '5'), F.decode({ width: 8 }, 'x1')],
        sort: F.sortRows({ signal: [{ name: 'o_b', wave: '0' }, { name: 'i_a', wave: '0' }, { name: 'c10', wave: '0' }, { name: 'c9', wave: '0' }] }, 'asc', ['i_', 'o_']).map(r => r.name),
        time: [F.fmtTime(1234567, 1000), F.fmtTime(1500, 100, 1e6), F.fmtExact(1234567), F.fmtExact(1500, 1e6), F.parseT('1.5us'), F.parseT('250'), F.parseT('x')] }; })()""")
    want = {'rows': ['sig:clk', 'group:g', 'sig:b', 'space:', 'sig:a'], 'groups': ['g'], 't': [0, 30, 10], 'btr': [[0, 'A'], [20, 'B']],
            'fuzzy': [[2, 4, 6, 10], None], 'decode': ['-1', '1010', '"A"', '5', 'x1'], 'sort': ['i_a', 'o_b', 'c9', 'c10'],
            'time': ['1235 ns', '0.002 µs', '1.234567 µs', '0.0015 µs', 1500000, 250, None]}
    for k in want:
        check(got[k] == want[k], f'WaveFW pure functions, {k}: {got[k]}' + ('' if got[k] == want[k] else f' (want {want[k]})'))


def plugin_api(page):
    """The plugin API (stage 9.4): tokens, highlight tokens, tools, panels, rows, marks, listeners, keys with help,
    events, plugin groups that leave, enums by path; sva.js uses nothing else of the viewer."""
    import re as _re
    bad = []
    for f in ('sva.js', 'bus.js'):   # the two plugins: the API, not the viewer's fields (moveTo, fold, select, setCursor …)
        src = (ROOT / 'wavefw' / f).read_text()
        bad += [f'{f}: {p}' for p in ('.namesEl', ".bar .tools", "textContent === 'go to'", 'v.keys.', '.vis[+') if p in src]
        bad += [f'{f}: {m}' for m in _re.findall(r'\bv\.(?:t0|cursor|span|sel) = |\bv\.collapsed\.(?:add|delete)\(', src)]
    import re as _re2
    cfg_keys = set(_re2.findall(r'^ {2}(\w+):', (ROOT / 'wavefw' / 'wavefw.config.js').read_text(), _re2.M))
    lacking = sorted(cfg_keys - set(page.evaluate('Object.keys(WaveFW.defaults)')) - {'theme', 'colors', 'nameWidth', 'fontMono', 'fontBody'} - ({'busDetect', 'buses'} if not page.evaluate('!!window.WaveBus') else set()))
    check(not lacking, f'WaveFW.defaults has every setting of wavefw.config.js (the plugins register theirs: registerDefaults) {lacking}')
    own = sorted(set(_re.findall(r'\b\w+\.(?:lay|oy|vis|collapsed|rowEls|namesEl)\b', pathlib.Path(__file__).read_text())))
    check(not own, f'tests/smoke.py reads the fields of a viewer through WaveFW.internal.peek(v) only (one place to change) {own or ""}')
    check(not bad, f'sva.js and bus.js use the API only (none of {bad or "namesEl, .bar .tools, the go-to label, v.keys, vis[data-r], v.t0 / cursor / span / sel =, WaveFW.internal.peek(v).collapsed.add / delete"})')
    page.evaluate("""(() => { const d = document.createElement('div'); d.id = 'wv-api'; d.style.cssText = '--my-col: #123456; width: 900px'; document.body.appendChild(d);
        const M = { signal: [['tb', ['u', { name: 'state', path: 'tb.u.state', width: 2, tv: [[0, '0'], [10, '1']] }], ['w', { name: 'state', path: 'tb.w.state', width: 2, tv: [[0, '0'], [10, '1']] }]]],
          time: { t0: 0, cycle: 10, t1: 40 } };
        WaveFW.enums['tb.u.state'] = { 0: 'IDLE', 1: 'RUN' };
        const v = window.__api = new WaveView(d, M, { cursor: 20 }), ev = window.__ev = [];
        for (const n of ['cursor', 'view', 'select']) d.addEventListener('wavefw:' + n, () => ev.push(n));
        const row = { type: 'sig', name: 'plugin row', height: 20, draw: (P, o) => P.rect(o.xL, o.y, o.xR - o.xL, o.h, '--my-col') };
        v.extraRows.push(g => g && g.name === 'u' ? [row] : []); v.renderNames(); v.draw(); window.__row = row; })()""")
    t = lambda e: page.evaluate(f'(() => {{ const v = window.__api, row = window.__row; return {e}; }})()')
    px = page.evaluate("""(() => { const v = window.__api, o = WaveFW.internal.peek(v).lay.find(o => o.row === window.__row), d = devicePixelRatio || 1, c = v.canvas;
        return [...c.getContext('2d').getImageData(Math.round(c.width * 0.27), Math.round((o.y + o.h / 2 - WaveFW.internal.peek(v).oy) * d), 1, 1).data].slice(0, 3); })()""")
    check(px == [0x12, 0x34, 0x56], f'a plugin row paints in any custom property of the page ("--my-col"): {px}')
    reg = page.evaluate("(WaveFW.registerTokens({'my-tok': '--my-col'}), [WaveFW.registerTokens({})['my-tok'], 'sva-pass' in WaveFW.registerTokens({})])")
    check(reg == ['--my-col', True], f'WaveFW.registerTokens adds a colour name (sva.js registers its own) {reg}')
    hv = t("(v.extraPicks = new Map([[row, 'hl3']]), v.renderNames(), v.rowEl(row).style.getPropertyValue('--hl'))")
    check(hv == 'var(--wave-hl3)', f'extraPicks takes a token per row ({hv})')
    tools = t("""(() => { const a = v.addTool('go to', '<button type="button" class="t1">x</button>'), b = v.addTool('go to', '<button type="button" class="t2">y</button>');
        return [a === b, a.dataset.tg, a.querySelectorAll('button').length, a.querySelector('.tl').textContent]; })()""")
    panel = t("(() => { const p = document.createElement('div'); v.addPanel(p); return p.previousElementSibling === v.root.querySelector('.bar'); })()")
    check(tools == [True, 'go to', 2, 'go to'] and panel, f'addTool finds or makes a tool group by its label {tools}; addPanel puts a panel under the bar {panel}')
    rows = t("""(() => { const el = v.rowEl(row), y = WaveFW.internal.peek(v).lay.find(o => o.row === row).y + 2; return [v.rowAt(el) === row, v.rowAt(el.firstChild) === row, v.rowAt(y) === row, v.rowAt(document.body)]; })()""")
    check(rows == [True, True, True, None], f'rowAt(an element or a y) and rowEl(row) find each other {rows}')
    marks = t("""(() => { v.rowClass(row, 'my-mark').rowTitle(row, 'my title'); v.collapseAll(); v.expandAll();
        const el = v.rowEl(row), a = [el.classList.contains('my-mark'), el.title]; v.rowClass(row, 'my-mark', false).rowTitle(row, null);
        return a.concat([v.rowEl(row).classList.contains('my-mark')]); })()""")
    check(marks == [True, 'my title', False], f'rowClass / rowTitle stay when the names column is built again, and go when asked {marks}')
    page.evaluate("window.__n = 0; window.__api.listen('names', 'click', () => window.__n++); window.__api.rowEl(window.__row).click()")
    k = t("""(() => { let n = 0; v.addKey('q', () => n++, 'q quit nothing'); const k = (o) => v.canvas.dispatchEvent(new KeyboardEvent('keydown', Object.assign({ key: 'q', bubbles: true }, o)));
        k({}); k({ ctrlKey: true }); return [n, v.root.querySelector('.hint').textContent.includes('q quit nothing'), window.__n]; })()""")
    check(k == [1, True, 1], f'addKey: the key on the waves (not with ctrl), its line in the hint; listen on the names column {k}')
    ev = t("(window.__ev.length = 0, v.setCursor(30), v.zoom(0.5, 0.5), v.select('tb.w.state'), v.select('tb.w.state'), window.__ev.slice())")
    check(ev == ['cursor', 'view', 'select'], f'events wavefw:cursor, wavefw:view, wavefw:select, once per change {ev}')
    en = t("[v.valueAt(v.M.rows.find(r => r.full === 'tb.u.state'), 15), v.valueAt(v.M.rows.find(r => r.full === 'tb.w.state'), 15)]")
    check(en == ['RUN', '1'], f'WaveFW.enums by full path: only tb.u.state gets the names {en}')
    gh = page.evaluate("""(() => { const d = document.createElement('div'); document.body.appendChild(d);
        const M = WaveFW.parse({ signal: [['g', { name: 'a', wave: '01' }]] }), mk = () => [{ type: 'group', name: 'p', id: WaveFW.rowId() }];
        const n = []; for (let i = 0; i < 3; i++) { WaveFW.WaveSVG.render(d, M, { extraRows: [g => g && g.name === 'g' ? mk() : []] }); n.push(Object.keys(M.groups).length); }
        d.remove(); delete WaveFW.enums['tb.u.state']; return n; })()""")
    check(gh == [2, 2, 2], f'the groups of SVG plugins leave the model when the figure is drawn again (groups after 3 renders {gh})')
    page.evaluate("(() => { const d = document.querySelector('#wv-api'); d.remove(); WaveFW.upgrade(); })()")


def api_docs(page):
    """docs/index.html § API is made from the exports: a line for every key of WaveFW and no line for a key that is not
    there; the viewer methods it lists exist; the settings table names every default."""
    got = page.evaluate("""(() => ({ keys: Object.keys(WaveFW).sort(), doc: Object.keys(WAVEFW_API).sort(),
        rows: document.querySelectorAll('#api-wavefw tr[data-api]').length, todo: document.querySelector('#api-wavefw').textContent.includes('not described yet'),
        view: Object.keys(VIEW_API).filter(k => typeof WaveView.prototype[k] !== 'function'),
        settings: Object.keys(WaveFW.defaults).filter(k => !document.querySelector('#api').parentElement.textContent.includes(k)) }))()""")
    check(got['keys'] == got['doc'] and got['rows'] == len(got['keys']) and not got['todo'],
          f'docs § API: one line per export of WaveFW ({len(got["keys"])}; not described: {sorted(set(got["keys"]) - set(got["doc"]))}, gone: {sorted(set(got["doc"]) - set(got["keys"]))})')
    check(not got['view'], f'docs § API: every viewer method it lists exists (missing: {got["view"]})')
    check(not got['settings'], f'docs § Settings names every default setting (missing: {got["settings"]})')


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


def sva_exprs(browser, build):
    """Stage 10: the expression field of the bar on the APB pages."""
    apb, apb_all = build / 'examples' / 'apb' / 'apb.html', build / 'examples' / 'apb' / 'apb_all.html'
    if not need(apb, apb_all, how='make examples'):
        return
    print('assertions: expressions')
    ctx = browser.new_context(viewport={'width': 1360, 'height': 1400})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()'); page.evaluate('localStorage.clear()')
    v = page.locator('.wv').first
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView, x = v.svaExprs; {e} }})()")
    inp, cnt = v.locator('input.svq'), v.locator('.svqn')
    js('v.cursor = 0;')
    inp.fill('PSEL && !PREADY')
    seq = []
    for k in ('Enter', 'Enter', 'Enter', 'Enter', 'Shift+Enter'):
        prev = cnt.inner_text(); inp.press(k)
        page.wait_for_function('(n) => document.querySelector(".wv .svqn").textContent !== n', arg=prev)
        seq.append([cnt.inner_text(), js('return v.cursor;')])
    check([x[0] for x in seq] == ['1/3', '2/3', '3/3', '1/3', '3/3'] and [x[1] for x in seq][:3] == [45000, 85000, 145000],
          f'Enter / shift+Enter: the times PSEL && !PREADY becomes true, from the cursor, round the ends {seq}')
    v.locator('button[data-x=add]').click()
    inp.fill('@(posedge PCLK) PSEL && PENABLE && !PREADY'); v.locator('button[data-x=add]').click()
    inp.fill('PSEL && nope'); v.locator('button[data-x=add]').click()
    page.wait_for_function("WaveFW.internal.peek(document.querySelector('.wv').waveView).vis.filter(r => (r.cls || '').startsWith('sva-expr')).length === 2")
    toast = v.locator('.bar .toast').inner_text()
    rows = js("return WaveFW.internal.peek(v).vis.filter(r => (r.cls || '').startsWith('sva-expr')).map(r => [r.name, r.tr.filter(o => o.k === '1').map(o => o.t)]);")
    check(rows == [['ƒ PSEL && !PREADY', [45000, 85000, 145000]], ['ƒ @(posedge PCLK) PSEL && PENABLE && !PREADY', [105000]]] and 'not found: nope' in toast,
          f'+ Row: two rows ƒ (the clocked one at the edge after its cycle); a name that is not there is said, no row {rows} {toast!r}')
    jtxt = page.evaluate("document.querySelector('.wv').waveView.extraJSON.map(f => f()).filter(Boolean).join('\\n')")
    page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    page.wait_for_function("WaveFW.internal.peek(document.querySelector('.wv').waveView).vis.filter(r => (r.cls || '').startsWith('sva-expr') && r.tr.length).length === 2")
    v.locator('.names .row', has_text='ƒ PSEL && !PREADY').first.click()
    got = [inp.input_value()]
    v.locator('button[data-x=del]').click()
    got.append(js("return WaveFW.internal.peek(v).vis.filter(r => (r.cls || '').startsWith('sva-expr')).map(r => r.name);"))
    check('"exprs": [\n  "PSEL && !PREADY",' in jtxt and got == ['PSEL && !PREADY', ['ƒ @(posedge PCLK) PSEL && PENABLE && !PREADY']],
          f'the rows are kept over a reload and in the JSON ("exprs"); a click on a row puts it in the field, − Row removes it {got}')
    # a hierarchy: names from the selected signal's module up, or a full path
    page.goto(apb_all.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    h = js("""v.expandAll(); const I = SVA.scopeInfo(v.M), r = v.M.rows.find(r => r.src && r.src.path === 'apb_tb.u_regs.PREADY'); v.select(r);
        const X = SVA.expressions, M = v.M, go = x => X.valueOf(M, [], x).then(o => o.err || Object.values(o.map).map(r => r.src.path));
        return Promise.all([go({ text: 'PSEL && PREADY', scope: x.scope() }), go({ text: 'apb_tb.u_master.PSEL || PCLK', scope: 'apb_tb.u_regs' }), go({ text: 'PSEL', scope: 'apb_tb.u_count' })]);""")
    check(h[0] == ['apb_tb.u_regs.PSEL', 'apb_tb.u_regs.PREADY'] and h[1] == ['apb_tb.u_master.PSEL', 'apb_tb.u_regs.PCLK'] and h[2] == ['apb_tb.PSEL'],
          f'names: from the selected signal\'s module (u_regs) up to the top, a full path as it is {h}')
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (expressions)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


READERS_BAD = {'backwards': 'time goes back', 'unsorted': 'time goes back', 'noend': 'no $enddefinitions'}


def readers(browser, build):
    """The page's VCD reader (WaveFW.vcdToWave, wavefw/src/vcd.js) and the tools' (vcd2wavedrom.py --exact over
    dumpscan.py) give the same transitions for every fixture of tests/unit/vcd: one rule for references, merged codes,
    texts, VHDL values, comments in the body, x / z; the dumps the tools refuse the page refuses too."""
    import json
    sys.path.insert(0, str(ROOT / 'tools'))
    import dumpscan
    print('readers: the page\'s VCD reader against the tools\'')
    page = browser.new_page()
    page.goto('about:blank'); page.add_script_tag(path=str(ROOT / 'wavefw' / 'wavefw.js'))
    fixtures = sorted((ROOT / 'tests' / 'unit' / 'vcd').glob('*.vcd'))
    same, differ = [], []
    for f in fixtures:
        text = f.read_text(encoding='utf-8', errors='replace')
        got = page.evaluate("""t => { try { const r = WaveFW.vcdToWave(t), out = {};
            const walk = a => a.forEach(x => Array.isArray(x) ? walk(x.slice(1)) : (out[x.path] = { tv: x.tv, kind: x.kind || null, width: x.width || 1 }));
            walk(r.doc.signal); return { sigs: out, t0: r.doc.time.t0 }; } catch (e) { return { err: String(e.message || e) }; } }""", text)
        if f.stem in READERS_BAD:
            r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'vcd2wavedrom.py'), '--waves', str(f), '--exact', '--signals', 'tb.s'], capture_output=True, text=True)
            ok = READERS_BAD[f.stem] in (got.get('err') or '') and r.returncode == 1 and READERS_BAD[f.stem] in r.stderr
            (same if ok else differ).append(f.stem + ('' if ok else f' (page: {got.get("err")}, tools: {r.stderr.strip()[:80]})'))
            continue
        d = dumpscan.read(str(f), None)
        paths = [p for p, v in d.vars.items() if v.kind != 'event']
        r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'vcd2wavedrom.py'), '--waves', str(f), '--exact', '--hierarchy', '--signals', ','.join(paths)], capture_output=True, text=True)
        if r.returncode or 'err' in got:
            differ.append(f'{f.stem} (page: {got.get("err")}, tools: {r.stderr.strip()[:80]})'); continue
        tools = {}
        def walk(items):
            for it in items:
                if isinstance(it, list):
                    walk(it[1:] if it and isinstance(it[0], str) else it)
                elif isinstance(it, dict):
                    tools[it['path']] = it
        walk(json.loads(r.stdout)['signal'])
        for it in tools.values():
            if 'same' in it:
                it['tv'] = tools[it['same']]['tv']
        bad = []
        for p, it in tools.items():
            pg = got['sigs'].get(p)
            if pg is None:
                bad.append(f'{p}: not in the page'); continue
            tv = pg['tv']
            if not tv or tv[0][0] > it['tv'][0][0]:   # the page starts at the first change, the tools at the window's start
                tv = [[it['tv'][0][0], None if pg['kind'] else 'x']] + tv
            fl = lambda q: [[float(t), v] for t, v in q]   # times above 2^53 ps: JavaScript numbers round them (dumpscan warns)
            if fl(tv) != fl(it['tv']) or pg['kind'] != it.get('kind'):
                bad.append(f'{p}: page {tv[:4]} {pg["kind"]}, tools {it["tv"][:4]} {it.get("kind")}')
        extra = set(got['sigs']) - set(tools)
        (differ if bad or extra else same).append(f.stem + (f' ({bad[:2]} {sorted(extra)[:3]})' if bad or extra else ''))
    check(not differ and len(same) == len(fixtures), f'the page and the tools read {len(same)} of {len(fixtures)} fixtures the same' + (f'; differ: {differ}' if differ else ''))
    # known bits among x / z reach the page's engine as bits (they were x by the hex: the page and sva eval disagreed)
    for f in ('wavefw.config.js', 'sva.wasm.js', 'sva.js'):
        page.add_script_tag(path=str(ROOT / 'wavefw' / f))
    got = page.evaluate("""async t => { const M = WaveFW.parse(WaveFW.vcdToWave(t).doc), X = SVA.expressions, out = [];
        for (const text of ['b[0]', 'b[3:0] == 4\\'b0z0x', 'b[7:4] === 4\\'b1x0z']) { const r = await X.valueOf(M, [], { text, scope: 'tb' });
          out.push(r.err || r.times.map((t, i) => [t, String(r.values[i])])); }
        return out; }""", (ROOT / 'tests' / 'unit' / 'vcd' / 'xz.vcd').read_text())
    check(got == [[[0, 'x'], [10000, 'x'], [20000, '1'], [30000, '1']], [[0, '0'], [10000, 'x'], [20000, 'x'], [30000, 'x']],
                  [[0, '1'], [10000, '0'], [20000, '0'], [30000, '0']]],
          f'xz.vcd in the page\'s engine: bit 0 of bx1 is 1 (not x), 1x0z1z0x keeps its known bits (== on a known bit that differs: 0, not x) {got}')
    page.close()


def dump(browser, build):
    """A VCD opened in the page (Open…, a file dropped on the viewer): the same waves as mkhtml.py builds from it; ⟳ reads
    it again with the view kept; wavefw/viewer.html starts empty; an FST is refused with what to do."""
    allp, vcd = build / 'examples' / 'apb' / 'apb_all.html', build / 'examples' / 'apb' / 'apb.vcd'
    if not need(allp, vcd, how='make examples'):
        return
    print('a dump opened in the page')
    page = browser.new_page(viewport={'width': 1360, 'height': 1000})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(allp.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    # the values as the dump has them (raw hex, a bit's level): the built page's enum labels come from the SV sources
    vals = "(ts => Object.fromEntries(v.M.rows.filter(r => r.type === 'sig' && r.tr).map(r => [r.full, ts.map(t => (o => o ? o.raw ?? o.k : '')(r.tr[WaveFW.lastLE ? WaveFW.lastLE(r.tr, t) : r.tr.filter(o => o.t <= t).length - 1]))])))([0, 33000, 95000, 150000, 190000])"
    before = js(vals)
    page.locator('.wv input.dfile').first.set_input_files(str(vcd))
    page.wait_for_function("document.querySelector('.wv').waveView && document.querySelector('.wv').waveView.opts.dumpSrc", timeout=60000)
    after = js(vals); info = js("[v.M.title, v.root.querySelector('.bar .toast').textContent, !v.reloadBtn.hidden, document.querySelectorAll('.wv .names .row.bus-g').length]")
    same = [p for p in before if before[p] != after.get(p)]
    check(not same and set(before) <= set(after) and info[0] == 'apb.vcd' and 'signals' in info[1] and info[2] and info[3] > 0,
          f'Open… a VCD: the values of mkhtml.py\'s {len(before)} signals (it leaves constants out: {len(after)} here), the bus port found again; ⟳ shown {info} {same[:3]}')
    js("(v.cursor = 95000, v.t0 = 20000, v.span = 100000, WaveFW.internal.peek(v).collapsed.add(Object.values(v.M.groups).find(g => g.name === 'u_count').id), v.draw(), 0)")
    page.locator('.wv button[data-act=dreload]').first.click()
    page.wait_for_function("document.querySelector('.wv').waveView.root.querySelector('.bar .toast').textContent.includes('signals')", timeout=60000)
    kept = js("[v.cursor, v.t0, v.span, [...WaveFW.internal.peek(v).collapsed].map(id => v.M.groups[id].name)]")
    check(kept[:3] == [95000, 20000, 100000] and 'u_count' in kept[3], f'⟳: the dump read again, the cursor, the window and the folding kept {kept}')
    fst = vcd.with_suffix('.fst')
    if fst.exists():
        page.locator('.wv input.dfile').first.set_input_files(str(fst))
        until(page, "document.querySelector('.wv').waveView.root.querySelector('.bar .toast').textContent.includes('fst2vcd')")
        check('fst2vcd' in js("v.root.querySelector('.bar .toast').textContent") and js('v.M.title') == 'apb.vcd', 'an FST is not read in the page: the toast says fst2vcd / make html, the waves stay')
    page.goto((ROOT / 'wavefw' / 'viewer.html').as_uri()); page.wait_for_load_state('networkidle')
    page.locator('.wv input.dfile').first.set_input_files(str(vcd))
    page.wait_for_function("document.querySelector('.wv').waveView && document.querySelector('.wv').waveView.opts.dumpSrc", timeout=60000)
    rows = page.evaluate("(() => { const v = document.querySelector('.wv').waveView, n = WaveFW.internal.peek(v).namesEl.querySelectorAll('.row[data-r]'), o = WaveFW.internal.peek(v).lay; return [v.M.rows.filter(r => r.type === 'sig').length, [...n].slice(0, 12).every((el, i) => Math.abs(el.getBoundingClientRect().height - o[i].h) < 0.5)]; })()")
    check(rows[0] == len(after) and rows[1], f'wavefw/viewer.html: empty, a VCD opened in it, its names column as tall as the waves\' rows (no page box-sizing needed) {rows}')
    dropped = page.evaluate("""(() => { const r = document.querySelector('.wv'), text = '$timescale 1ns $end $scope module t $end $var wire 1 ! a $end $upscope $end $enddefinitions $end #0 0! #5 1! #9 0!';
        const dt = new DataTransfer(); dt.items.add(new File([text.replace(/ #/g, '\\n#')], 'drop.vcd')); r.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); return 0; })()""")
    page.wait_for_function("document.querySelector('.wv').waveView.M.title === 'drop.vcd'", timeout=30000)
    d = page.evaluate("(v => [v.M.rows.filter(r => r.type === 'sig').map(r => r.full), v.valueAt(v.M.rows.find(r => r.full === 't.a'), 7000)])(document.querySelector('.wv').waveView)")
    check(d == [['t.a'], '1'], f'a VCD dropped on the viewer replaces its waves {d}')
    # dropped again: one live viewer, one wavefw:dump per drop (the old viewer's listeners on the element are gone)
    two = page.evaluate(r"""(async () => { const r = document.querySelector('.wv'); let n = 0; r.addEventListener('wavefw:dump', () => n++);
        const vcd = '$timescale 1ns $end\n$scope module t $end\n$var wire 1 ! b $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n#5\n1!\n';
        const drop = name => { const dt = new DataTransfer(); dt.items.add(new File([vcd], name)); r.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); };
        drop('d2.vcd'); await new Promise(f => setTimeout(f, 300)); drop('d3.vcd'); await new Promise(f => setTimeout(f, 300));
        return [n, WaveFW.views().filter(v => v.root === r).length, r.waveView.M.title, r.waveView.canvas.isConnected]; })()""")
    check(two == [2, 1, 'd3.vcd', True], f'dropped twice: one live viewer, one wavefw:dump each, its canvas in the page {two}')
    check(not errs, 'no page errors (dump)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    page.close()


def state(browser, build):
    """Save / Load… of a viewer: everything done in it to a file and back, the assertions and ƒ rows too; another page
    takes what it has."""
    apb, axi = build / 'examples' / 'apb' / 'apb.html', build / 'examples' / 'axi_lite' / 'axi_lite.html'
    if not need(apb, axi, how='make examples'):
        return
    print('viewer state: Save / Load')
    ctx = browser.new_context(viewport={'width': 1360, 'height': 1400}, accept_downloads=True)
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()'); page.evaluate('localStorage.clear()')
    v = page.locator('.wv').first
    st = page.evaluate("""async () => { const v = document.querySelector('.wv').waveView, sig = v.M.rows.filter(r => r.type === 'sig' && r.tr);
        v.setSort('desc', 'P'); v.toggleHighlight(sig[2]); v.toggleHighlight(sig[4]); v.paint('#123456'); v.collapseAll(); v.select(sig[1]);
        v.goto(v.M.t0 + (v.M.t1 - v.M.t0) / 3, (v.M.t1 - v.M.t0) / 10); v.mark('saved here'); v.find('pready');
        await v.svaExprs.setList(['PSEL && !PREADY']); v.sva.unbind(v.sva.bindings[0]); v.sva.bind('apb_enable_needs_sel', 'apb_tb.u_regs'); await v.sva.queue;
        return v.state(); }""")
    with page.expect_download() as dl:
        v.locator('button[data-act=ssave]').click()
    path = dl.value.path(); name = dl.value.suggested_filename
    saved = json.loads(pathlib.Path(path).read_text(encoding='utf-8'))
    check(saved == st and name.endswith('.view.json') and set(st) >= {'from', 'to', 'cursor', 'config', 'paint', 'select', 'find', 'bookmarks', 'arrows', 'sva', 'exprs'},
          f'Save downloads the viewer\'s state ({name}): window, cursor, sort, folding, highlight, paint, selection, search, bookmarks, assertions, ƒ rows')
    page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    v.locator('input.sfile').set_input_files(path)
    page.wait_for_function("document.querySelector('.wv .bar .toast').textContent.includes('loaded')")
    page.evaluate('SVA.ready()'); page.evaluate('document.querySelector(".wv").waveView.sva.queue')
    back = page.evaluate("document.querySelector('.wv').waveView.state()")
    diff = [k for k in st if st[k] != back.get(k)]
    shown = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView;
        return [v.sortBtn.textContent, v.root.querySelector('input.pfx').value, v.qEl.value, v.sva.bindings.find(b => b.scope === 'apb_tb.u_regs').state,
            WaveFW.internal.peek(v).vis.some(r => (r.cls || '').startsWith('sva-expr')), [...v.notesEl.querySelectorAll('input.txt')].some(i => i.value === 'saved here')]; })()""")
    check(not diff and shown == ['Sort: Z→A', 'P', 'pready', 'cannot', True, True],
          f'Load… after a reload with nothing kept: the same state, the bar and the lists show it (differs: {diff}) {shown}')
    page.goto(axi.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    v.locator('input.sfile').set_input_files(path)
    page.wait_for_function("document.querySelector('.wv .bar .toast').textContent.includes('loaded')")
    toast = v.locator('.bar .toast').inner_text()
    got = page.evaluate("(() => { const v = document.querySelector('.wv').waveView; return [v.sort, v.painted.size, v.bms.every(b => !b.signal || v.M.rows.some(r => r.full === b.signal))]; })()")
    check('not in these waves' in toast and got == ['desc', 0, True], f'Load… on other waves: what they have is taken, the rest is said and left out {got} {toast!r}')
    bad = page.evaluate("document.querySelector('.wv').waveView.loadState('[1, 2]').then(m => [m, document.querySelector('.wv .bar .toast').textContent])")
    check(bad[0] is None and 'not a saved viewer state' in bad[1], f'Load… of another JSON: said, nothing changes {bad}')
    # a WaveDrom file dropped as a state: refused (it was "state loaded", the search cleared); range and edge kind kept;
    # a state's style that is the settings' own pins nothing in the browser
    js2 = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    wd = page.evaluate("document.querySelector('.wv').waveView.loadState(JSON.stringify({ signal: [{ name: 'a', wave: '01' }] }))"
                       ".then(m => [m, document.querySelector('.wv .bar .toast').textContent])")
    js2("(v.setRange(v.M.t0 + 10000, v.M.t0 + 50000, v.M.rows.find(r => r.type === 'sig' && r.tr && r.tr.length > 2)), v.setEdgeKind('value'), v.evEl.value = '0x40', 0)")
    st = js2('v.state()')
    js2("(v.setRange(null), v.setEdgeKind('any'), v.evEl.value = '', 0)")
    page.evaluate("s => document.querySelector('.wv').waveView.setState(s)", st)
    back = js2("[v.range, v.rangeRow && v.rangeRow.full, v.edgeKind, v.evEl.value, v.state().version]")
    page.evaluate('localStorage.clear()')
    js2("(v.setStyle('questa'), v.setStyle(v.S.style === 'questa' ? 'auto' : v.S.style), 0)")
    pinned = page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('wavefw.look:'))")
    want = [[st['range']['from'], st['range']['to']], st['range']['signal'], 'value', '0x40', 3]
    check(wd[0] is None and 'WaveDrom waves, not a saved viewer state' in wd[1] and back == want and not pinned,
          f"a WaveDrom file is no state; the range and the edge kind come back (state v2); the settings' own style pins nothing {wd} {back} {pinned}")
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (state)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


EDIT_OPS = [   # every command that changes a state, with the arguments in their forms (the APB example, its view "exact")
    {'op': 'bookmark', 't': '60ns', 'signal': 'PSEL', 'text': 'setup'},
    {'op': 'bookmark', 't': 80000, 'signal': 'PENABLE', 'text': 'access', 'color': '#0a0', 'lift': True},
    {'op': 'bookmark', 'n': 1, 'text': 'setup (edited)'}, {'op': 'arrow', 'from': 1, 'to': 2, 'label': 'Δ 20ns', 'shape': '-|-', 'head': '<>'},
    {'op': 'bookmark', 't': '120ns', 'text': 'axis'}, {'op': 'arrow', 'from': 2, 'to': 3, 'line': 'dashed'}, {'op': 'arrow', 'id': 2, 'color': '#f00'},
    {'op': 'bookmark', 't': '130ns'}, {'op': 'bookmark', 'n': 4, 'delete': True},
    {'op': 'marker', 't': '100ns', 'label': 'M', 'color': '#c00'}, {'op': 'marker', 't': '140ns'}, {'op': 'marker', 'id': 2, 'label': 'second'},
    {'op': 'group', 'name': 'ctl', 'signals': ['PSEL', 'PENABLE'], 'color': '#08f'}, {'op': 'group', 'name': 'ctl', 'add': 'PWRITE'},
    {'op': 'group', 'name': 'data', 'signals': 'P*DATA'}, {'op': 'group', 'name': 'data', 'rename': 'payload'},
    {'op': 'highlight', 'add': ['PSEL', 'payload']}, {'op': 'highlight', 'add': 'PREADY', 'remove': 'PSEL'},
    {'op': 'paint', 'signals': 'PADDR', 'color': '#123456'}, {'op': 'paint', 'signals': ['PWDATA', 'PRDATA'], 'color': '#654321'},
    {'op': 'paint', 'signals': 'PRDATA', 'color': None}, {'op': 'hide', 'signals': 'PSLVERR'}, {'op': 'radix', 'signals': 'PADDR', 'radix': 'dec'},
    {'op': 'analog', 'signals': 'PWDATA', 'rows': 2}, {'op': 'select', 'signal': 'PENABLE'}, {'op': 'cursor', 't': '150ns'}, {'op': 'cursor2', 't': '170ns'},
    {'op': 'view', 'from': '40ns', 'to': '180ns'}, {'op': 'range', 'from': '100ns', 'to': '60ns', 'signal': 'PCLK'},
    {'op': 'sort', 'dir': 'desc', 'ignore': 'P'}, {'op': 'style', 'name': 'questa'}, {'op': 'fold', 'groups': 'ctl'},
    {'op': 'find', 'query': 'pw', 'case': True, 'open': False}, {'op': 'gaps', 'on': True, 'idle': 8},
    {'op': 'layout', 'scroll': 'page', 'tools': 'fold'}, {'op': 'group', 'name': 'ctl', 'go': True},
    {'op': 'cycles', 'on': True, 'clock': 'PCLK', 'zero': '50ns'}, {'op': 'group', 'name': 'payload', 'move': 1},
]


def cycles(browser, build):
    """V5: the cycles of a clock in a band under the time axis — numbered from cycle 0, the cursor's in the title, c147 in
    the cursor field, Δ of the second cursor in them, the menu's Cycles ▸, the pictures (toSVG, WaveSVG), kept in the browser."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('viewer: clock cycles')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    js = lambda e: page.evaluate(f"(async () => {{ const v = document.querySelector('.wv').waveView; {e} }})()")
    got = js("""const h0 = v.hdrH, r = await v.run([{ op: 'cycles', on: true }]), ups = WaveFW.views()[0] && v.cycData().ups;
        v.setCursor(ups[2] + 1); const t = v.curEl.textContent, lab = WaveFW.internal.peek(v).namesEl.querySelector('.hdr .cyc')?.textContent;
        v.setCursor('c5'); const c5 = v.cursor === ups[5];
        return [v.hdrH - h0, r[0].clock, r[0].cycle, / · cycle 2 ↑PCLK/.test(t), lab, c5, ups.length > 10];""")
    check(got[0] == 16 and got[1] == 'PCLK' and got[3] and got[4] == 'cycles ↑ PCLK' and got[5] and got[6],
          f'cycles on: a 16 px band, the clock found (PCLK) named in the names\' header, the cursor\'s cycle in the title, c5 goes to edge 5 {got}')
    got = js("""const ups = v.cycData().ups; await v.run([{ op: 'cycles', zero: ups[3] }]); v.setCursor(ups[5]); const a = v.cycText();
        v.setCursor('c-1'); const b = v.cursor === ups[2]; v.setCursor2(ups[9]); const d = v.delta2(); v.setCursor2(null);
        const bad = v.parseIn('c99999', v.cuEl, true);
        return [a, b, / · 7 PCLK$/.test(d), bad === undefined, v.state().config.cycleZero === ups[3]];""")
    check(got == [' · cycle 2 ↑PCLK', True, True, True, True], f'cycle 0 at edge 3: edge 5 is cycle 2, c-1 is edge 2, Δ of the cursors in cycles, '
          f'past the last edge refused, kept in the state {got}')
    svg = js("return [v.toSVG(), WaveFW.WaveSVG.toString(v.M.src, { cycles: true }), WaveFW.WaveSVG.toString(v.M.src, {})];")
    check('cycles ↑ PCLK' in svg[0] and 'cycles ↑ PCLK' in svg[1] and 'cycles ↑' not in svg[2],
          'the picture of the viewer and a static WaveSVG with cycles: true draw the band; without it, none')
    page.reload(); page.wait_for_load_state('networkidle')
    got = js("const o = v.cycOpt(), u = v.cycData().ups; v.setCursor('c0'); return [o.cycles, o.cycleClock, v.hdrH, o.cycleZero === u[3], v.cursor === u[3]];")
    check(got == [True, None, 40, True, True], f'kept in this browser over a reload (the clock found: none set), cycle 0 and c0 too {got}')
    got = js("""const ups = v.cycData().ups, c = v.cursor; return [v.parseIn('c2', v.suEl), v.parseIn('c2', v.cuEl, true) === ups[5],
        (await v.run([{ op: 'cycles', on: false, clock: 'PADDR' }]))[0].error, v.cycOpt().cycles];""")
    check(got[0] is None and got[1] and 'not a 1-bit signal' in (got[2] or '') and got[3] is True,
          f'c2 is a time on the waves (cursor), not a span; a bad command changes nothing {got}')
    # a state with null (the clock found, the first edge) over a page that sets both: null stays
    got = js("""WaveFW.configure({ cycleClock: 'PSEL', cycleZero: 20000 }); await v.run([{ op: 'cycles', clock: null, zero: null }]); const st = v.state();
        v.setCycles(null); const page = [v.cycOpt().cycleClock, v.cycOpt().cycleZero]; await v.setState(st); const back = [v.cycOpt().cycleClock, v.cycOpt().cycleZero];
        v.setCycles(null); WaveFW.configure({ cycleClock: null, cycleZero: null }); return [page, back];""")
    check(got == [['PSEL', 20000], [None, None]], f'a saved null (the clock found, the first edge) comes back null over the page\'s settings {got}')
    # two clocks of other periods: the band's one counts the Δ and c3, a name that is also a path's tail takes the exact path
    got = page.evaluate("""(() => { const ck = (p, n) => { const tv = []; for (let i = 0; i < n; i++) tv.push([i * p, '0'], [i * p + p / 2, '1']); return tv; };
        const el = document.body.appendChild(document.createElement('div')), w = new WaveFW.WaveView(el, { signal: [['tb', { name: 'clk', path: 'tb.clk',
          tv: ck(10, 30) }], { name: 'clk', path: 'clk', tv: ck(30, 10) }], time: { t0: 0, unit: 'ps' } }, {});
        return w.run([{ op: 'cycles', on: true, clock: 'clk' }]).then(r => { w.select(w.M.rows.find(x => x.full === 'tb.clk')); w.setCursor(15); w.setCursor2(105);
          const out = [r[0].clock, w.cycData().clk.full, w.delta2().endsWith('· 3 clk'), (w.setCursor('c3'), w.cursor)]; w.destroy(); el.remove(); return out; }); })()""")
    check(got == ['clk', 'clk', True, 105], f'clock "clk" over tb.clk: the exact path; Δ in its cycles (3 of 30 ps), c3 its edge {got}')
    # the menu: Cycles ▸ on a 1-bit row; "Cycle 0 at this edge" at the time clicked
    got = js("""const r = v.M.rows.find(x => x.name === 'PSEL'), ups = v.cycData(true).ups; v.menu(200, 300, r, ups[7] + 2);
        const m = document.querySelector('.wv-menu'), items = [...m.querySelectorAll('.subc + .sub button[data-m]')].map(b => b.dataset.m);
        m.querySelector('button[data-m=cyc0]').click(); const z = v.cycOpt().cycleZero === ups[7];
        v.menu(200, 300, r, ups[1]); document.querySelector('.wv-menu button[data-m=cyclk]').click(); const c = v.cycOpt().cycleClock;
        v.menu(200, 300, r, ups[1]); document.querySelector('.wv-menu button[data-m=cycx]').click();
        return [items, z, c, v.cycOpt().cycles, v.hdrH === v.S.headerHeight];""")
    check(got == [['cycon', 'cyclk', 'cyc0', 'cycx'], True, 'PSEL', False, True],
          f'the menu: on / off, this clock, cycle 0 at the edge clicked, reset (the band gone) {got}')
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (cycles)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def undo(browser, build):
    """V7: undo / redo of the edits — a batch of commands, a menu action, a field — by ctrl+Z, ctrl+shift+Z / ctrl+Y and
    the bar's ↶ ↷; the cursor and the window are not steps; a new edit after an undo drops the redo; a text field keeps
    its own ctrl+Z."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('viewer: undo')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    js = lambda e: page.evaluate(f"(async () => {{ const v = document.querySelector('.wv').waveView; {e} }})()")
    w = page.locator('.wv').first
    st = lambda: js("const s = v.state(); return [s.bookmarks.length, s.radix.PADDR || null, s.hidden.length, s.config.highlight.length];")
    s0 = st()
    js("await v.run([{ op: 'bookmark', t: '30ns', signal: 'PSEL', text: 'x' }]); await v.run([{ op: 'radix', signals: 'PADDR', radix: 'dec' }, "
       "{ op: 'hide', signals: 'PSLVERR' }]); await v.run([{ op: 'cursor', t: '90ns' }, { op: 'view', from: '20ns', to: '120ns' }]); return 0;")
    s1, n1 = st(), js("return v.undoS.length;")
    w.locator('canvas').click(position={'x': 300, 'y': 120}); page.wait_for_timeout(50)
    cur0 = js("return [v.cursor, v.t0, v.span];")
    page.keyboard.press('Control+z'); page.wait_for_timeout(100)
    s2, toast, cur = st(), w.locator('.bar .toast').inner_text(), js("return [v.cursor, v.t0, v.span];")
    page.keyboard.press('Control+z'); page.wait_for_timeout(100); s3 = st()
    page.keyboard.press('Control+Shift+z'); page.wait_for_timeout(100); s4 = st()
    dis = js("return [...v.root.querySelectorAll('button.undo')].map(b => b.disabled);")
    check(n1 == 2 and s1 != s0 and s2[1:3] == s0[1:3] and s2[0] == s1[0] and 'radix' in toast and 'hidden' in toast and s3 == s0 and s4 == s2
          and dis == [False, False] and cur == cur0,
          f'two batches, two steps (the cursor and the window none): ctrl+Z takes back radix + hide, then the bookmark; ctrl+shift+Z gives one '
          f'back; ↶ ↷ enabled {s0} {s1} {s2} {s3} {s4} {toast!r} {dis}')
    # the menu: a colour by the colour field is a step; a new edit drops the redo; ↶ in the bar
    js("v.menu(200, 300, v.M.rows.find(r => r.name === 'PADDR'), 50000); const i = document.querySelector('.wv-menu input[type=color]'); i.value = '#ff0000'; "
       "i.dispatchEvent(new Event('input', { bubbles: true })); i.dispatchEvent(new Event('change', { bubbles: true })); return 0;")
    page.wait_for_timeout(100)
    got = js("return [v.state().paint.PADDR || null, v.redoS.length];")
    w.locator('button[data-act=undo]').click(); page.wait_for_timeout(100)
    got.append(js("return v.state().paint.PADDR || null;"))
    check(got == ['#ff0000', 0, None], f'the menu\'s colour is a step, a new edit drops the redo, ↶ in the bar takes it back {got}')
    # a text field keeps its own ctrl+Z; a bookmark's text typed is one step when the field is left
    w.locator('input.q').fill('PSEL'); n = js("return v.undoS.length;"); w.locator('input.q').press('Control+z'); page.wait_for_timeout(100)
    check(js("return v.undoS.length;") == n, 'ctrl+Z in a text field is the field\'s, not the viewer\'s')
    w.locator('input.q').fill(''); w.locator('input.q').press('Enter')
    t0 = js("return v.bms[0].text;"); n = js("return v.undoS.length;")
    tx = w.locator('.notes li[data-n="1"] input.txt'); tx.click(); page.wait_for_timeout(50)   # a person types after the click's look
    page.keyboard.press('End'); page.keyboard.type(' abc'); tx.blur(); page.wait_for_timeout(100)
    got = [js("return v.undoS.length;") - n, js("return v.bms[0].text;")]
    w.locator('canvas').click(position={'x': 600, 'y': 150}); page.keyboard.press('Control+z'); page.wait_for_timeout(100)
    got.append(js("return v.bms[0].text;") == t0)
    check(got[0] == 1 and got[1] == t0 + ' abc' and got[2], f'a bookmark\'s text typed: one step when the field is left, undone whole {got}')
    # a real drag of a bookmark: one step, undone to its time and signal
    box = w.locator('canvas').bounding_box(); p = js("return v.bmGeo.pos.get(2);"); b0 = js("return [v.bms[1].t, v.bms[1].signal];"); n = js("return v.undoS.length;")
    page.mouse.move(box['x'] + p[0], box['y'] + p[1]); page.mouse.down(); page.mouse.move(box['x'] + p[0] + 120, box['y'] + p[1] + 40, steps=8); page.mouse.up()
    page.wait_for_timeout(100); b1 = js("return [v.bms[1].t, v.bms[1].signal];"); d = js("return v.undoS.length;") - n
    page.keyboard.press('Control+z'); page.wait_for_timeout(100)
    check(b1 != b0 and d == 1 and js("return [v.bms[1].t, v.bms[1].signal];") == b0, f'a bookmark dragged: one step, undone to where it was {b0} {b1} {d}')
    # a folded group of yours and the selection in it stay through an undo of something else; a highlight keeps its colours
    got = js("""await v.run([{ op: 'group', name: 'gv', signals: 'PREADY' }, { op: 'group', name: 'gu', signals: 'PSEL,PENABLE' }]);
        const f = v.ugRows().find(r => r.name === 'gv'), g = v.ugRows().find(r => r.name === 'gu'); WaveFW.internal.peek(v).collapsed.add(f.id);
        v.select(v.ugRows().find(r => r.ug === g)); v.draw();
        await v.run([{ op: 'highlight', add: ['PSEL', 'PWRITE'] }]); await v.run([{ op: 'highlight', remove: 'PSEL' }]); const c0 = [...v.picks.values()];
        await v.run([{ op: 'paint', signals: 'PADDR', color: '#00ff00' }]); await v.undo(); return [v.ugRows().includes(g), WaveFW.internal.peek(v).collapsed.has(f.id),
        !!v.sel && v.sel.ug === g, JSON.stringify([...v.picks.values()]) === JSON.stringify(c0), v.state().paint.PADDR || null];""")
    check(got == [True, True, True, True, None], f'undo of a paint: your group (its row, folded), the selection in it, the highlight\'s colours stay {got}')
    # the Russian layout (ctrl+Я is ctrl+Z by its place), ctrl+Y, a viewer by the focus, two undos at once, the gaps' clock null
    got = js("""await v.run([{ op: 'hide', signals: 'PRESETn' }]); v.canvas.focus();
        v.canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'я', code: 'KeyZ', ctrlKey: true, bubbles: true, cancelable: true }));
        await new Promise(r => setTimeout(r, 50)); const a = v.state().hidden.length;
        v.canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', code: 'KeyY', ctrlKey: true, bubbles: true, cancelable: true }));
        await new Promise(r => setTimeout(r, 50)); const b = v.state().hidden.length;
        await v.run([{ op: 'hide', signals: 'PREADY' }]); const r = await Promise.all([v.undo(), v.undo()]); const c = v.state().hidden.length;
        WaveFW.configure({ gapClock: 'PCLK' }); v.setGaps({ gapClock: null }); await v.run([{ op: 'paint', signals: 'PADDR', color: '#0000ff' }]); await v.undo();
        const d = v.gapOpt().gapClock; v.setGaps(null); WaveFW.configure({ gapClock: null }); return [a, b, r.filter(Boolean).length, c, d];""")
    check(got == [0, 1, 1, 1, None], f'ctrl+Я undoes, ctrl+Y redoes; two undos at once: one; a cleared gaps\' clock stays cleared over the page\'s {got}')
    # Load…: one step of its own, the next edit another
    got = js("""const s = v.state(); s.radix = { PADDR: 'bin' }; const n = v.undoS.length; await v.loadState(JSON.stringify(s));
        await v.run([{ op: 'paint', signals: 'PWDATA', color: '#123456' }]); const k = v.undoS.length - n; await v.undo();
        return [k, v.state().radix.PADDR, v.state().paint.PWDATA || null];""")
    check(got == [2, 'bin', None], f'a load is a step of its own: an undo after a paint keeps the load {got}')
    got = js("""const n = v.undoS.length, pr = v.run([{ op: 'paint', signals: 'PSEL', color: '#abcdef' }, { op: 'picture', format: 'png' },
        { op: 'hide', signals: 'PWRITE' }]); document.dispatchEvent(new PointerEvent('pointerdown')); document.dispatchEvent(new PointerEvent('pointerup'));
        await new Promise(r => setTimeout(r, 0)); await pr; const k = v.undoS.length - n; await v.undo();
        return [k, v.state().paint.PSEL || null, v.state().hidden.includes('PWRITE')];""")
    check(got == [1, None, False], f'a batch with a picture to wait for and a click meanwhile: one step {got}')
    # Codex, second look: the arrows stay when a bookmark's text is undone; the highlight's colours on the screen; no undo in a
    # batch not done; a group renamed and undone is the same group, folded as it was
    got = js("""const na = v.arrowList().length; await v.run([{ op: 'bookmark', n: 1, text: 'changed' }]); await v.undo();
        const a = v.arrowList().length === na;
        await v.run([{ op: 'highlight', set: ['PSEL', 'PWRITE'] }]); await v.run([{ op: 'highlight', remove: 'PSEL' }]); const h0 = v.highlighted();
        await v.run([{ op: 'highlight', clear: true }]); await v.undo(); const h = JSON.stringify(v.highlighted()) === JSON.stringify(h0);
        const pr = v.run([{ op: 'paint', signals: 'PSEL', color: '#ff00ff' }, { op: 'picture', format: 'png' }]); const busy = await v.undo(); await pr;
        await v.run([{ op: 'group', name: 'gr', signals: 'PCLK' }]); const g = v.ugRows().find(r => r.name === 'gr'); WaveFW.internal.peek(v).collapsed.add(g.id);
        await v.run([{ op: 'group', name: 'gr', rename: 'gs' }]); await v.undo(); const g2 = v.ugRows().find(r => r.name === 'gr');
        return [a, h, busy, g2 === g, WaveFW.internal.peek(v).collapsed.has(g.id), v.state().paint.PSEL];""")
    check(got == [True, True, '', True, True, '#ff00ff'], f'arrows kept, highlight colours, no undo in a batch not done, a rename undone: the same group {got}')
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (undo)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def order(browser, build):
    """V6: the order of your groups' rows — alt+↑ / alt+↓ move the selected signal in its group, alt+shift the group among
    yours, a drag in the names moves a signal (to another group too) or a group; one step to undo each; a drag over the
    other names still selects their text."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('viewer: the order of your groups')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    js = lambda e: page.evaluate(f"(async () => {{ const v = document.querySelector('.wv').waveView; {e} }})()")
    w = page.locator('.wv').first
    groups = lambda: js("return v.ugroups.map(g => [g.name, ...g.signals]);")
    js("await v.run([{ op: 'group', name: 'gA', signals: 'PSEL,PENABLE,PWRITE' }, { op: 'group', name: 'gB', signals: 'PADDR' }]); "
       "v.select(v.ugRows().find(r => r.ug && r.ug.name === 'gA' && r.orig.name === 'PENABLE')); v.canvas.focus(); return 0;")
    page.keyboard.press('Alt+ArrowUp'); page.wait_for_timeout(50); a = groups(); s1 = js("return v.sel && v.sel.ug && [v.sel.ug.name, v.sel.orig.name];")
    page.keyboard.press('Alt+ArrowDown'); page.keyboard.press('Alt+ArrowDown'); page.keyboard.press('Alt+ArrowDown'); page.wait_for_timeout(50); b = groups()
    page.keyboard.press('Alt+Shift+ArrowDown'); page.wait_for_timeout(50); c = groups()
    page.keyboard.press('Control+z'); page.wait_for_timeout(100); d = groups()
    check(a[0] == ['gA', 'PENABLE', 'PSEL', 'PWRITE'] and s1 == ['gA', 'PENABLE'] and b[0] == ['gA', 'PSEL', 'PWRITE', 'PENABLE'] and [g[0] for g in c] == ['gB', 'gA']
          and [g[0] for g in d] == ['gA', 'gB'], f'alt+↑ / alt+↓: the signal in its group (kept selected, at the end it stays); alt+shift+↓ the group; '
          f'ctrl+Z one step {a} {s1} {b} {c} {d}')
    # a drag in the names: PSEL of gA onto PADDR of gB (below its middle): out of gA, after PADDR in gB, one step
    idx = lambda g, n: js(f"return WaveFW.internal.peek(v).vis.findIndex(r => r.ug && r.ug.name === '{g}' && r.orig.name === '{n}');")
    hdr = lambda g: js(f"return WaveFW.internal.peek(v).vis.findIndex(r => r.user && r.name === '{g}');")
    box = lambda i: w.locator(f'.names .row[data-r="{i}"]').bounding_box()
    n0 = js("return v.undoS.length;")
    p, q = box(idx('gA', 'PSEL')), box(idx('gB', 'PADDR'))
    page.mouse.move(p['x'] + 30, p['y'] + p['height'] / 2); page.mouse.down(); page.mouse.move(q['x'] + 30, q['y'] + q['height'] * 0.8, steps=8)
    line = js("return !!WaveFW.internal.peek(v).namesEl.querySelector('.row.drop-a');"); page.mouse.up(); page.wait_for_timeout(100)
    e, n1 = groups(), js("return v.undoS.length;") - n0
    check(line and e == [['gA', 'PWRITE', 'PENABLE'], ['gB', 'PADDR', 'PSEL']] and n1 == 1, f'a drag: a line where it goes; the signal into the other group after '
          f'the row dropped on; one step {line} {e} {n1}')
    # a group's header dragged above the other's; a drag over the dump's names selects their text (no move)
    p, q = box(hdr('gB')), box(hdr('gA'))
    page.mouse.move(p['x'] + 30, p['y'] + p['height'] / 2); page.mouse.down(); page.mouse.move(q['x'] + 30, q['y'] + 3, steps=8); page.mouse.up(); page.wait_for_timeout(100)
    f = [g[0] for g in groups()]
    r1, r2 = box(js("return WaveFW.internal.peek(v).vis.findIndex(r => !r.ug && r.name === 'PSEL');")), box(js("return WaveFW.internal.peek(v).vis.findIndex(r => !r.ug && r.name === 'PRDATA');"))
    page.mouse.move(r1['x'] + 20, r1['y'] + r1['height'] / 2); page.mouse.down(); page.mouse.move(r2['x'] + 60, r2['y'] + r2['height'] / 2, steps=8); page.mouse.up()
    sel = page.evaluate("String(getSelection())")
    check(f == ['gB', 'gA'] and groups()[0][0] == 'gB' and 'PSEL' in sel, f'a header dragged over the other: the group before it; a drag over the dump\'s '
          f'names selects text {f} {sel[:40]!r}')
    # cross-group drag undone and redone: both lists back; onto itself: nothing, no step
    page.keyboard.press('Escape'); w.locator('canvas').click(position={'x': 600, 'y': 150})
    g0 = groups(); page.keyboard.press('Control+z'); page.wait_for_timeout(100); g1 = groups(); page.keyboard.press('Control+Shift+z'); page.wait_for_timeout(100)
    n0 = js("return v.undoS.length;"); p = box(idx('gA', 'PWRITE'))
    page.mouse.move(p['x'] + 30, p['y'] + 5); page.mouse.down(); page.mouse.move(p['x'] + 30, p['y'] + 15, steps=4); page.mouse.up(); page.wait_for_timeout(100)
    check(groups() == g0 and g1 != g0 and js("return v.undoS.length;") == n0, f'a drag undone and redone (both groups); dropped onto itself: nothing {g0} {g1}')
    # let go outside the names: the drag ends there (nothing moved), the next click on a name selects it
    p = box(idx('gA', 'PWRITE')); cb = w.locator('canvas').bounding_box()
    page.mouse.move(p['x'] + 30, p['y'] + 5); page.mouse.down(); page.mouse.move(cb['x'] + 300, cb['y'] + 200, steps=6); page.mouse.up(); page.wait_for_timeout(100)
    left = js("return WaveFW.internal.peek(v).namesEl.classList.contains('wv-drag');"); g2 = groups()
    w.locator(f'.names .row[data-r="{idx("gA", "PENABLE")}"] .n').click(); page.wait_for_timeout(50)
    check(not left and g2 == g0 and js("return v.sel && v.sel.ug && v.sel.orig.name;") == 'PENABLE', f'let go over the waves: no move, the drag over, a click selects {left} {g2}')
    # from the names: the focused row moves and keeps the focus (twice); a header with the focus moves its group
    w.locator(f'.names .row[data-r="{idx("gB", "PADDR")}"]').focus(); page.keyboard.press('Alt+ArrowDown'); page.wait_for_timeout(80)
    page.keyboard.press('Alt+ArrowUp'); page.wait_for_timeout(80); page.keyboard.press('Alt+ArrowDown'); page.wait_for_timeout(80)
    foc = js("const a = document.activeElement, r = a && a.dataset.r != null && WaveFW.internal.peek(v).vis[+a.dataset.r]; return r && r.ug && [r.ug.name, r.orig.name];")
    gb = [g for g in groups() if g[0] == 'gB'][0]; second = groups()[1][0]
    w.locator(f'.names .row[data-r="{hdr(second)}"]').focus(); page.keyboard.press('Alt+ArrowUp'); page.wait_for_timeout(80)
    check(foc == ['gB', 'PADDR'] and gb == ['gB', 'PSEL', 'PADDR'] and groups()[0][0] == second, f'alt+arrows in the names: the focus stays on the row moved; '
          f'a header with the focus moves its group {foc} {gb} {groups()}')
    # the focus on a module of the dump (not one of yours): nothing moves, though a signal of a group of yours is selected
    js("v.select(v.ugRows().find(r => r.ug)); return 0;"); g3 = groups()
    mod = js("return WaveFW.internal.peek(v).vis.findIndex(r => r.type === 'group' && !r.user);")
    w.locator(f'.names .row[data-r="{mod}"]').focus()
    page.keyboard.press('Alt+Shift+ArrowDown'); page.wait_for_timeout(80)
    check(groups() == g3, f'alt+shift+↓ on a module of the dump: none of your groups moves {g3} {groups()}')
    # a run picked in two groups to a third: each loses only the rows picked in it
    got = js("""await v.run([{ op: 'group', name: 'gA', signals: 'PSEL,PWRITE' }, { op: 'group', name: 'gB', signals: 'PSEL' }, { op: 'group', name: 'gC', signals: 'PADDR' }]);
        const R = (g, n) => v.ugRows().find(r => r.ug && r.ug.name === g && r.orig.name === n); v.selRun = new Set([R('gA', 'PWRITE'), R('gB', 'PSEL')]);
        await v.moveRows([...v.selRun], v.ugRows().find(r => r.user && r.name === 'gC')); v.selRun = new Set();
        return v.ugroups.map(g => [g.name, ...g.signals.map(f => f.split('.').pop())]);""")
    check(got[:3] == [['gA', 'PSEL'], ['gB'], ['gC', 'PADDR', 'PWRITE', 'PSEL']], f'a run from two groups: PSEL stays in gA where it was not picked {got}')
    got = js("return [(await v.run([{ op: 'group', name: 'gA', move: 1 }]))[0].at, (await v.run([{ op: 'group', name: 'gA', move: 'sideways' }]))[0].error];")
    check(got[0] == 1 and 'move: up, down, top, bottom' in got[1], f'group move: a number, a bad one said {got}')
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (order)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def savepage(browser, build):
    """V2: Save page writes the page as it was read with every viewer's state in its edits (tools/viewedit.py's block):
    opened in another browser it shows what you saw; its waves byte for byte the page's; the live link's token left out;
    savePage: false hides the button."""
    import re as _re
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('viewer: Save page')
    d = build / 'smoke' / 'savepage'
    d.mkdir(parents=True, exist_ok=True)
    src = apb.read_text(encoding='utf-8')
    live = '  <script id="wavefw-live" data-x="1" type="application/json">{"port": 8742, "token": "SECRET-TOKEN"}</script>\n'   # not as viewedit writes it
    pa, pb = d / 'a.html', d / 'b.view.html'
    pa.write_text(src.replace('<script>window.WAVEFW_CONFIG', live + '<script>window.WAVEFW_CONFIG', 1), encoding='utf-8')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.route('http://127.0.0.1:8742/**', lambda r: r.abort())   # the live link of the copy: no agent here
    page.goto(pa.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()')
    V = "WaveFW.views().find(v => v.editKey() === 'exact')"
    keys = ['bookmarks', 'arrows', 'groups', 'paint', 'radix', 'hidden', 'cursor', 'from', 'to']
    pick = lambda st: {k: st.get(k) for k in keys} | {'highlight': st['config']['highlight'], 'cycles': st['config']['cycles']}
    want = page.evaluate(f"""(async () => {{ const v = {V}; await v.run([{{ op: 'bookmark', t: '75ns', signal: 'PSEL', text: 'mine <!--<script> </script>' }},
        {{ op: 'group', name: 'ctl', signals: 'PSEL,PENABLE' }}, {{ op: 'paint', signals: 'PADDR', color: '#ff8800' }}, {{ op: 'radix', signals: 'PWDATA', radix: 'dec' }},
        {{ op: 'hide', signals: 'PSLVERR' }}, {{ op: 'highlight', set: 'PREADY' }}, {{ op: 'cycles', on: true }}, {{ op: 'cursor', t: '95ns' }},
        {{ op: 'view', from: '30ns', to: '150ns' }}]); return v.state(); }})()""")
    text = page.evaluate('WaveFW.pageText()')
    again = page.evaluate('WaveFW.pageText()')   # twice: one block of edits, the next revision of nothing new
    blocks = lambda t: len(_re.findall(r'^<script type="application/json" id="wavefw-edits">', t, _re.M))
    shown = page.locator('.wv button[data-act=spage]').first.is_visible()
    pb.write_text(text, encoding='utf-8')
    data = lambda t: _re.search(r'<script>\nwindow\.WAVES = (.*?)\n</script>', t, _re.S).group(1)
    same = data(text) == data(src)
    ctx.close()
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})   # another browser: nothing kept
    page = ctx.new_page(); page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(pb.as_uri()); page.wait_for_load_state('networkidle'); page.wait_for_timeout(200 * SCALE)
    got = page.evaluate(f"{V}.state()")
    toast = page.evaluate(f"{V}.root.querySelector('.toast').textContent")
    diff = {k: (pick(want)[k], pick(got)[k]) for k in pick(want) if pick(want)[k] != pick(got)[k]}
    check(not diff and 'edits applied' in toast and same and shown, f'the saved page opens in another browser as it was left (differs: {diff}), '
          f'its waves byte for byte the page\'s ({same}), the button there ({shown}) {toast!r}')
    check('SECRET-TOKEN' not in text and 'id="wavefw-live"' not in text.split('<script>\n')[0] and blocks(text) == 1 and blocks(again) == 1,
          'the live link (its block written another way, its token) is not in the saved page; one block of edits, saved twice too')
    # the person who opens it: a ƒ row and a bookmark text of theirs stay over a reload (the page's revision is applied once)
    page.evaluate(f"(v => {{ v.root.querySelector('input.svq').value = 'PSEL && PENABLE'; v.root.querySelector('button[data-x=add]').click(); }})({V})")
    page.evaluate(f"{V}.run([{{ op: 'bookmark', n: 1, text: 'theirs' }}])"); page.wait_for_timeout(300 * SCALE)
    page.reload(); page.wait_for_load_state('networkidle'); page.wait_for_timeout(300 * SCALE)
    kept = page.evaluate(f"""(v => [v.bms[0].text, v.svaExprs ? JSON.stringify(v.extraJSON.map(f => f()).filter(Boolean)).includes('PSEL && PENABLE') : null])({V})""")
    check(kept == ['theirs', True], f'the person\'s own edits (a bookmark, a ƒ row) stay over a reload: the page\'s are applied once {kept}')
    # a page that is not all in itself (docs/index.html: wavefw.js beside it): no button, Save page says why
    page.goto((ROOT / 'docs' / 'index.html').as_uri()); page.wait_for_load_state('networkidle')
    why = page.evaluate("(() => { try { WaveFW.pageText(); return 'saved'; } catch (e) { return e.message; } })()")
    hid = page.locator('.wv button[data-act=spage]').first.is_hidden()
    check(hid and 'all in itself' in why, f'docs/index.html (wavefw.js beside it): no Save page, it says why {why!r}')
    page.goto((ROOT / 'tests' / 'conformance.html').as_uri()); page.wait_for_load_state('networkidle')   # its viewers built before the page was read
    vis = page.locator('.wv button[data-act=spage]').evaluate_all('bs => bs.filter(b => !b.hidden).length')
    check(vis == 0, f'tests/conformance.html (its viewers built early, wavefw.js beside it): no Save page on any viewer ({vis} shown)')
    page.evaluate("WaveFW.configure({ savePage: false })")
    check(page.locator('.wv button[data-act=spage]').first.is_hidden(), 'savePage: false hides the button')
    page.evaluate("WaveFW.configure({ savePage: true })")
    check(not errs, 'no page errors (save page)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def compare(browser, build):
    """V1: a second dump over the waves (Compare…): the APB example's VCD with one change of PREADY made later and PSLVERR
    left out — ≠ on PREADY, PSLVERR struck, a red band where they differ (on the screen and in the picture), ]d [d to it;
    a clock-sampled view refuses; ✕ compares no more."""
    apb, vcd = build / 'examples' / 'apb' / 'apb.html', build / 'examples' / 'apb' / 'apb.vcd'
    if not need(apb, vcd, how='make examples'):
        return
    print('viewer: compare with a second dump')
    lines, out, moved = vcd.read_text().split('\n'), [], None
    for ln in lines:
        if ln.strip().startswith('$var') and ln.split()[3] == '&':   # PSLVERR: not in B
            continue
        if ln in ('0&', '1&'):
            continue
        out.append(ln)
    t, k = 0, None
    for i, ln in enumerate(out):   # B: the first rise of PREADY after 100 ns happens 10 ns later
        if ln.startswith('#'):
            t = int(ln[1:])
        elif ln == '1%' and t > 100000 and k is None:
            k, moved = i, t
    out.pop(k); j = next(i for i in range(k, len(out)) if out[i].startswith('#') and int(out[i][1:]) >= moved + 10000)
    out.insert(j + 1, '1%')
    b = build / 'smoke' / 'compare'; b.mkdir(parents=True, exist_ok=True); bv = b / 'b.vcd'; bv.write_text('\n'.join(out))
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()')
    V = "WaveFW.views().find(v => v.editKey() === 'exact')"
    w = page.locator('.wv').nth(page.evaluate(f"WaveFW.views().indexOf({V})"))
    w.locator('input.cfile').set_input_files(str(bv)); page.wait_for_timeout(300 * SCALE)
    got = page.evaluate(f"""(v => {{ const c = v.cmp, R = n => v.M.rows.find(r => r.name === n);
        const el = n => WaveFW.internal.peek(v).rowEls[WaveFW.internal.peek(v).vis.indexOf(R(n))]; return c && [c.differ, c.missing, c.first, el('PREADY').classList.contains('cmpd'),
        el('PSLVERR').classList.contains('cmpm'), el('PSEL').classList.contains('cmpd'), v.root.querySelector('button[data-act=dcmpx]').textContent,
        c.rows.get(R('PREADY')).spans]; }})({V})""")
    check(got and got[0] == 1 and got[1] == 1 and got[2] == moved and got[3] and got[4] and not got[5] and got[6] == '≠ 1 ✕' and got[7] == [[moved, moved + 10000]],
          f'B ({bv.name}): PREADY ≠ from {moved} for 10 ns, PSLVERR struck (not in B), PSEL the same; ≠ 1 ✕ in the bar {got}')
    page.evaluate(f"(v => {{ v.cursor = 0; v.canvas.focus(); }})({V})")
    page.keyboard.press(']'); page.keyboard.press('d'); page.wait_for_timeout(50); c1 = page.evaluate(f"{V}.cursor")
    page.keyboard.press('['); page.keyboard.press('d'); page.wait_for_timeout(50); c2 = page.evaluate(f"{V}.cursor")
    pic1 = page.evaluate(f"(v => (v.zoomTo(v.M.t0, v.M.t1), v.toSVG()))({V})")
    pic2 = page.evaluate(f"(v => {{ const c = v.cmp; v.cmp = null; const s = v.toSVG(); v.cmp = c; return s; }})({V})")
    check(c1 == moved and c2 == moved and pic1.count('<rect') == pic2.count('<rect') + 2, f']d to the difference (round the ends with [d); the picture '
          f'has its band (2 more rects: the shade and the line) {c1} {c2} {pic1.count("<rect")} {pic2.count("<rect")}')
    ref = page.evaluate("WaveFW.views()[0].compare('$timescale 1ns $end $scope module t $end $var wire 1 ! a $end $upscope $end $enddefinitions $end #0 0!', 'x.vcd')")
    toast = page.evaluate("WaveFW.views()[0].root.querySelector('.toast').textContent")
    w.locator('button[data-act=dcmpx]').click()
    gone = page.evaluate(f"(v => [v.cmp, WaveFW.internal.peek(v).namesEl.querySelectorAll('.cmpd, .cmpm').length, v.root.querySelector('button[data-act=dcmpx]').hidden])({V})")
    check(ref is None and 'clock-sampled' in toast and gone == [None, 0, True], f'a clock-sampled view refuses; ✕ compares no more {toast!r} {gone}')
    # Codex's cases: a packed struct by its vector (its group marked), a string the same as itself, the time both dumps
    # cover, a signal B's reader left out (dumpBudget) apart from one B lacks, a newer compare or none meanwhile, a group
    # of yours made after the compare marked
    got = page.evaluate("""(async () => {
      const mk = doc => { const el = document.body.appendChild(document.createElement('div')); return new WaveFW.WaveView(el, doc, {}); };
      const vcd = (vars, body) => `$timescale 1ps $end $scope module tb $end ${vars} $upscope $end $enddefinitions $end ${body}`;
      const w = mk({ signal: [['tb', { name: 'st', path: 'tb.st', width: 8, tv: [[0, '00'], [10, '12']], fields: [{ name: 'hi', msb: 7, lsb: 4 },
          { name: 'lo', msb: 3, lsb: 0 }] }, { name: 's', path: 'tb.s', kind: 'string', tv: [[0, 'Hello']] },
          { name: 'a', path: 'tb.a', tv: [[0, '0'], [30, '1']] }, { name: 'q', path: 'tb.q', tv: [[0, '0']] }]], time: { t0: 0, t1: 40, unit: 'ps' } });
      const B = vcd('$var wire 8 ! st [7:0] $end $var string 1 \" s $end $var wire 1 # a $end $var wire 1 $ q $end',
        '#0 b0 ! sHello \" 0# 0$ #10 b00010011 ! #20 1# #40');
      const r = await w.compare(B, 'b.vcd'), g = Object.values(w.M.groups).find(x => x.name === 'st');
      const marked = WaveFW.internal.peek(w).rowEls[WaveFW.internal.peek(w).vis.indexOf(g)].classList.contains('cmpd');
      const sp = w.cmp.rows.get(w.M.rows.find(x => x.name === 'a')).spans;
      WaveFW.configure({ dumpBudget: 3 }); const r2 = await w.compare(B, 'b.vcd'); WaveFW.configure({ dumpBudget: 3000000 });
      const slow = { name: 'slow.vcd', text: () => new Promise(res => setTimeout(() => res(B), 80)) }, pr = w.compare(slow); await w.compare(null);
      const r3 = await pr, gone = w.cmp;
      await w.compare(B, 'b.vcd'); await w.run([{ op: 'group', name: 'mine', signals: 'tb.a' }]);
      const k = WaveFW.internal.peek(w).vis.find(x => x.ug && x.orig.name === 'a');
      const kmark = WaveFW.internal.peek(w).rowEls[WaveFW.internal.peek(w).vis.indexOf(k)].classList.contains('cmpd');
      // a path B's reader left out is not matched to another signal of the same name; no time in common: nothing compared
      const u = mk({ signal: [['tb', ['u', { name: 'a', path: 'tb.u.a', tv: [[0, '0']] }]]], time: { t0: 0, t1: 40, unit: 'ps' } });
      WaveFW.configure({ dumpBudget: 1 });
      const r4 = await u.compare('$timescale 1ps $end $scope module tb $end $var wire 1 ! a $end $scope module u $end $var wire 1 " a $end $upscope $end ' +
        '$upscope $end $enddefinitions $end #0 0! 1" #40', 'b2.vcd');
      WaveFW.configure({ dumpBudget: 3000000 });
      const r5 = await u.compare('$timescale 1ps $end $scope module tb $end $scope module u $end $var wire 1 ! a $end $upscope $end $upscope $end ' +
        '$enddefinitions $end #100 0! #140', 'late.vcd'), t5 = u.root.querySelector('.toast').textContent;
      u.destroy(); w.destroy();
      return [r.differ, r.compared, marked, sp, r.to, [r2.missing, r2.omitted > 0], r3, gone, kmark, [r4.omitted, r4.differ], r5, /no time in common/.test(t5)]; })()""")
    check(got == [2, 4, True, [[20, 30]], 40, [0, True], None, None, True, [1, 0], None, True], f'a struct by its vector (its group ≠), a string the '
          f'same as itself, [from, to) both cover, dumpBudget apart (not matched to another tb.a), a compare superseded is dropped, a new group of '
          f'yours marked, no time in common said {got}')
    check(not errs, 'no page errors (compare)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def edit(browser, build):
    """The viewer's commands (view.run, wavefw/src/edit.js) and their twin tools/viewedit.py: the same list of commands,
    the same state from a page's edits as from the commands run in it, the edits applied once (what the browser keeps
    stays yours after a reload), errors said; your groups and markers in the lists and the menu; a page live through
    tools/wavemcp.py (view_live, view_edit, view_get with a picture)."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('viewer: commands, page edits, live')
    sys.path.insert(0, str(ROOT / 'tools'))
    import viewedit
    d = build / 'smoke' / 'edit'
    d.mkdir(parents=True, exist_ok=True)
    pa, pb, pl = d / 'edited.html', d / 'fresh.html', d / 'live.html'
    for x in (pa, pb, pl):
        x.write_bytes(apb.read_bytes())
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.on('console', lambda m: errs.append(m.text) if m.type == 'error' and 'fonts.g' not in m.text else None)
    V = "WaveFW.views().find(v => v.editKey() === 'exact')"
    def open_(path, idle=True):
        page.goto(path.as_uri()); page.wait_for_load_state('networkidle' if idle else 'load'); page.evaluate('SVA.ready()'); page.wait_for_timeout(200 * SCALE)
    open_(pb); page.evaluate('localStorage.clear()'); open_(pb)
    cmds = page.evaluate("Object.fromEntries(Object.entries(WaveFW.commands()).map(([k, c]) => [k, c.args]))")
    check(cmds == viewedit.COMMANDS, f'WaveFW.commands() and tools/viewedit.py COMMANDS: one list (differ: '
          f'{sorted(set(cmds.items()) ^ set(viewedit.COMMANDS.items()))})')
    run = page.evaluate(f"ops => {V}.run(ops).then(res => ({{res, st: {V}.state()}}))", EDIT_OPS)
    check(not [r for r in run['res'] if 'error' in r], f'every command runs in the page ({[r for r in run["res"] if "error" in r][:2]})')
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'viewedit.py'), str(pa), '--view', 'exact', '--ops', json.dumps(EDIT_OPS)],
                       capture_output=True, text=True)
    py = json.loads(r.stdout or '[]')
    check(r.returncode == 0 and len(py) == len(EDIT_OPS) and not [x for x in py if 'error' in x], f'viewedit.py: the same commands on the page\'s file {r.stderr.strip()}')
    open_(pa)
    page.wait_for_function(f"localStorage.getItem('wavefw.edits:' + {V}.storeId)")
    st = page.evaluate(f"{V}.state()")
    for x in (run['st'], st):
        x['config']['fold'] = sorted(x['config']['fold'])   # the ids of the groups made: in another order, the same set
    diff = sorted(k for k in set(run['st']) | set(st) if run['st'].get(k) != st.get(k))
    diff += [f'config.{k}: {run["st"]["config"].get(k)!r} / {st["config"].get(k)!r}' for k in sorted(set(run['st']['config']) | set(st['config']))
             if run['st']['config'].get(k) != st['config'].get(k)]
    check(not diff and 'edits applied (r1)' in page.evaluate(f"{V}.root.querySelector('.toast').textContent"),
          f'a page with these edits opens with the state the commands give in the page (differs: {diff})')
    # the person changes what the browser keeps; a reload keeps it, and the edits' cursor, window, highlight again
    page.evaluate(f"{V}.run([{{op: 'bookmark', n: 1, text: 'mine'}}, {{op: 'highlight', clear: true}}, {{op: 'cursor', t: 5000}}])")
    open_(pa)
    got = page.evaluate(f"(v => [v.bms[0].text, v.highlighted(), v.cursor, v.umarks.length])({V})")
    check(got == ['mine', ['@payload', 'PREADY'], 150000, 2], f'reloaded: your bookmark text stays, the edits\' highlight and cursor come again {got}')
    viewedit.edit_page(str(pa), [{'op': 'bookmark', 'n': 1, 'text': 'agent again'}], 'exact')
    open_(pa)
    check(page.evaluate(f"{V}.bms[0].text") == 'agent again', 'a newer revision of the edits replaces what it names')
    # errors: said, the rest done; names
    bad = page.evaluate(f"{V}.run([{{op: 'nope'}}, {{op: 'cursor', t: 1, x: 2}}, {{op: 'bookmark', signal: 'P'}}, {{op: 'hide', signals: 'PRESETn'}}])")
    check([('error' in x) for x in bad] == [True, True, True, False] and 'no signal "P"' in bad[2]['error'],
          f'a bad command is said, the others run {[x.get("error", "ok")[:40] for x in bad]}')
    # your groups: at the top, their rows read through to the signal (radix), out of the group by the menu; markers drawn in the picture
    page.evaluate('localStorage.clear()'); open_(pb)
    ui = page.evaluate(f"""(async v => {{
        await v.run([{{op: 'group', name: 'g1', signals: ['PADDR', 'PSEL']}}, {{op: 'marker', t: 90000, label: 'mk'}}]);
        const vis = WaveFW.internal.peek(v).vis, top = vis.slice(0, 3).map(r => r.name), copy = vis[1];
        v.setRadix(copy, 'bin'); const rx = v.M.rows.find(r => r.full === 'PADDR').radix;
        v.hide([copy]); const left = v.ugroups[0].signals;
        const lists = [...v.notesEl.querySelectorAll('.nh b')].map(b => b.textContent);
        return [top, rx, left, lists, v.toSVG().includes('>mk<')]; }})({V})""")
    check(ui == [['g1', 'PADDR', 'PSEL'], 'bin', ['PSEL'], ['Markers', 'Groups'], True],   # no bookmarks: their lists not there
          f'your group at the top (its rows are the signals: radix), Hide takes a row out of the group, the lists, a marker in the picture {ui}')
    # a bookmark of a signal in your group is drawn there (where you look), a highlight of it lights its row there too, a
    # name of the dump's longer path (apb_tb.PSEL) is the page's PSEL; an id that is a name: said, the others run
    got = page.evaluate(f"""(async v => {{
        const r = await v.run([{{op: 'bookmark', t: 60000, signal: 'apb_tb.PSEL', text: 'in g1'}}, {{op: 'highlight', set: 'PSEL'}},
          {{op: 'arrow', id: 'my-arrow', from: 1, to: 2}}]);
        v.draw(); const o = WaveFW.internal.peek(v).lay.find(o => o.row.ug && o.row.name === 'PSEL'), y = v.bmGeo.pos.get(r[0].n)[1];
        return [r[0].n > 0, Math.abs(y - (o.y + o.h / 2)) < o.h, v.hl.on.has(o.row), r[2].error || ''];
      }})({V})""")
    check(got[:3] == [True, True, True] and got[3].startswith('id: the number of the arrow'),
          f'your group: the bookmark on its row, the highlight on its row; the dump\'s path of a signal; an id that is a name said {got}')
    # the menu: a new group, a marker here, the group deleted from its header
    page.evaluate(f"(v => v.menu(200, 200, v.M.rows.find(r => r.name === 'PWRITE'), 70000))({V})")
    page.locator('.wv-menu .subg').hover(); page.locator('.wv-menu button[data-m=ugnew]').click()
    page.evaluate(f"(v => v.menu(200, 200, WaveFW.internal.peek(v).vis.find(r => r.user && r.name === 'group 2'), 70000))({V})")
    page.locator('.wv-menu .subg').hover(); page.locator('.wv-menu button[data-m=ugdel]').click()
    page.evaluate(f"(v => v.menu(200, 200, v.M.rows.find(r => r.name === 'PWRITE'), 70000))({V})")
    page.locator('.wv-menu button[data-m=umark]').click()
    got = page.evaluate(f"(v => [v.ugroups.map(g => g.name), v.markList().map(m => m.t)])({V})")
    check(got == [['g1'], [90000, 70000]], f'the menu: New group with it, Delete this group, Marker here {got}')
    # where the rows scroll: the bar's buttons, the bar sticking to the top with the page, folded; kept after a reload
    page.evaluate('localStorage.clear()'); open_(pb)
    page.set_viewport_size({'width': 1300, 'height': 600})
    w = page.locator('.wv').nth(page.evaluate(f"WaveFW.views().indexOf({V})"))
    lay = lambda: page.evaluate(f"""(v => {{ const b = v.root.querySelector('.bar').getBoundingClientRect(), c = v.canvas.getBoundingClientRect();
        return [v.root.classList.contains('wv-scroll'), v.root.querySelector('[data-act=scroll]').textContent, Math.round(b.top), Math.round(c.top - b.bottom),
          v.root.querySelector('.bar .tools').offsetHeight > 0]; }})({V})""")
    first = lay()
    w.locator('button[data-act=scroll]').click(); flip = lay()
    if not flip[0]:   # now with the page: back to a window and again, the button both ways
        w.locator('button[data-act=scroll]').click(); flip = lay()
    w.locator('button[data-act=scroll]').click()
    into = f"(v => window.scrollTo(0, v.bodyEl.getBoundingClientRect().top + scrollY + 150))({V})"   # among its rows
    page.evaluate(into); page.wait_for_timeout(200 * SCALE); paged = lay()
    w.locator('button[data-act=tools]').click(); page.evaluate(into); page.wait_for_timeout(200 * SCALE); folded = lay()
    open_(pb); kept = lay()
    check(flip[:2] == [True, 'Scroll: window'] and paged[:2] == [False, 'Scroll: page'] and abs(paged[2]) <= 1 and abs(paged[3]) <= 1 and folded[4] is False
          and abs(folded[2]) <= 1 and abs(folded[3]) <= 1
          and kept[1] == 'Scroll: page' and kept[4] is False, f'Scroll: window / page; with the page the bar sticks to the top over its rows (the canvas '
          f'under it), ▴ folds the tools; kept after a reload {first} {flip} {paged} {folded} {kept}')
    got = page.evaluate(f"{V}.run({{op: 'layout', scroll: 'window', height: 300, tools: 'open'}}).then(r => [r[0], {V}.bodyEl.clientHeight])")
    check(got[0].get('scroll') == 'window' and got[0].get('tools') == 'open' and got[1] <= 300, f'layout: the rows in a window 300 px high again {got}')
    # ctrl+G: your groups in a list, Enter goes there; the right button's Groups ▸
    page.evaluate(f"{V}.run([{{op: 'group', name: 'gA', signals: 'PSEL'}}, {{op: 'group', name: 'gB', signals: 'PWDATA,PRDATA'}}])")
    w.locator('canvas').click(position={'x': 300, 'y': 80}); page.keyboard.press('Control+g')
    items = page.locator('.wv-groups button').all_inner_texts()
    page.keyboard.press('ArrowDown'); page.keyboard.press('Enter')
    went = page.evaluate(f"(v => [v.sel && v.sel.full, !!(v.sel && v.sel.ug)])({V})")
    page.evaluate(f"(v => v.menu(200, 200, v.M.rows.find(r => r.name === 'PWRITE'), 70000))({V})")
    page.locator('.wv-menu .subg').hover()
    sub_ = page.locator('.wv-menu .subg + .sub').inner_text()
    page.locator('.wv-menu button[data-m=ugto][data-g="0"]').click()
    into = page.evaluate(f"{V}.ugroups[0].signals")
    check([x.split('\n')[0] for x in items] == ['gA', 'gB'] and went == ['PWDATA', True] and 'Into “gA”' in sub_ and 'Go to' in sub_ and into == ['PSEL', 'PWRITE'],
          f'ctrl+G: the list of your groups, Enter goes to one; Groups ▸ in the menu: into a group, go to {items} {went} {into}')
    pic = page.evaluate(f"{V}.run({{op: 'picture', format: 'png'}}).then(r => r[0])")
    check(pic.get('bytes', 0) > 2000 and pic.get('png', '').startswith('iVBOR'), f'picture: a PNG of the screen, base64 ({pic.get("bytes")} bytes)')
    check(not errs, 'no page errors (edit)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    # live: wavemcp.py as an agent's MCP server, the page connected to it
    env = dict(os.environ, WAVEFW_LIVE_PORT='0', XDG_CACHE_HOME=str(d / 'cache'))
    mcp = subprocess.Popen([sys.executable, '-I', str(ROOT / 'tools' / 'wavemcp.py')], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)
    n = [0]
    def tool(name, **a):
        n[0] += 1
        mcp.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': n[0], 'method': 'tools/call', 'params': {'name': name, 'arguments': a}}) + '\n')
        mcp.stdin.flush()
        res = json.loads(mcp.stdout.readline())['result']
        try:
            body = json.loads(res['content'][0]['text'])
        except ValueError:
            body = res['content'][0]['text']
        return body, res['isError'], [c for c in res['content'] if c['type'] == 'image']
    try:
        tool('view_live', page=str(pl))
        page.evaluate('localStorage.clear()'); open_(pl, idle=False)
        page.wait_for_function("[...document.querySelectorAll('.wv button[data-act=live]')].every(b => b.textContent === '● live')", timeout=8000 * SCALE)
        r = tool('view_edit', page=str(pl), view='exact', ops=[{'op': 'bookmark', 't': 60, 'signal': 'PSEL', 'text': 'agent'},
                                                                {'op': 'highlight', 'add': 'PSEL'}, {'op': 'cursor', 't': 75}])[0]
        seen = page.evaluate(f"(v => [v.bms.map(b => [b.t, b.text]), v.highlighted(), v.cursor])({V})")
        check(r.get('live') == str(pl) and seen == [[[60000, 'agent']], ['PSEL'], 75000] and r['results'][2] == {'op': 'cursor', 't': 75},
              f'view_edit on a live page: in the browser at once, times in ns {seen} {r.get("results")}')
        page.evaluate(f"{V}.run({{op: 'bookmark', n: 1, text: 'person'}})")
        g, err, img = tool('view_get', page=str(pl), view='exact', picture=True)
        check(not err and g['bookmarks'] == [{'n': 1, 't': 60, 'signal': 'PSEL', 'text': 'person'}] and g['cursor'] == 75 and len(img) == 1,
              f'view_get on a live page: the person\'s edits, a picture {g if err else g.get("bookmarks")}')
        page.goto('about:blank'); page.wait_for_timeout(300 * SCALE)
        r = tool('view_edit', page=str(pl), view='exact', ops=[{'op': 'marker', 't': 10}])[0]
        check(r.get('page') == str(pl) and 'written into the page' in r.get('note', ''), f'the page closed: the edit goes into its file {r}')
    finally:
        mcp.stdin.close(); mcp.wait(10)
    ctx.close()


def ranges(browser, build):
    """A range on the waves (shift+drag, the right button) with its ends on edges, the right button's menu: zoom,
    bookmarks at the ends, the picture as SVG / PNG / clipboard, the colour of the signal under the pointer."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('viewer: range and menu')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000}, accept_downloads=True)
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()'); page.evaluate('localStorage.clear()')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    c = page.locator('.wv canvas').first; c.scroll_into_view_if_needed(); box = c.bounding_box()
    r = js("""(() => { const o = WaveFW.internal.peek(v).lay.find(o => o.row.name === 'PSEL'), k = v.pxPerT(), e = o.row.tr.filter((e, i) => i && e.t > v.t0 && e.t < v.t0 + v.span);
        return [o.y + o.h / 2 - (WaveFW.internal.peek(v).oy || 0), (e[0].t - v.t0) * k, (e[1].t - v.t0) * k, e[0].t, e[1].t]; })()""")
    cur0 = js('v.cursor')
    page.keyboard.down('Control'); page.mouse.move(box['x'] + r[1] + 4, box['y'] + r[0]); page.mouse.down()
    page.mouse.move(box['x'] + r[2] - 3, box['y'] + r[0], steps=5); page.mouse.up(); page.keyboard.up('Control')
    got = [js('v.range'), js('v.cursor') == cur0, 'Δ 20 ns' in js('v.curEl.textContent')]
    check(got == [[r[3], r[4]], True, True], f'ctrl+drag: a range from edge to edge of PSEL (4 px off each), Δ in the readout, the cursor stays {got} / {r[3:]}')
    # on a bus: its changes in the range and the values it took
    bus = js("""(() => { const s = v.M.rows.find(r => r.name === 'PADDR'), a = v.M.t0, b = v.M.t1; v.setRange(a, b, s); const t = v.rangeText(), n = s.tr.filter((o, i) => i && o.t > a && o.t <= b).length;
        const vals = new Set(s.tr.map(o => o.raw ?? o.v ?? o.k)).size; v.setRange(RA, RB, v.M.rows.find(r => r.name === 'PSEL')); return [t, n, vals]; })()""".replace('RA', str(r[3])).replace('RB', str(r[4])))
    check(f'{bus[1]} changes of PADDR ({bus[2]} values)' in bus[0], f'a range measured on a bus: its changes and the values it took ({bus[0]!r})')
    page.mouse.move(box['x'] + r[1] + 3, box['y'] + r[0]); page.mouse.down(button='right'); page.mouse.move(box['x'] + r[2] + 2, box['y'] + r[0], steps=5); page.mouse.up(button='right')
    menu = page.locator('.wv-menu')
    items = menu.locator('button[data-m]').evaluate_all('bs => bs.map(b => b.dataset.m)')
    check(js('v.range') == [r[3], r[4]] and items[:6] == ['zoom', 'marks', 'copyd', 'copyimg', 'png', 'svg'] and {'hl', 'hide', 'mark', 'copyname', 'clear'} <= set(items) and 'PSEL' in menu.inner_text(),
          f'the right button: the same range, then its menu (range, picture, the signal under the pointer) {items}')
    with page.expect_download() as dl:
        menu.locator('button[data-m=svg]').click()
    svg = pathlib.Path(dl.value.path()).read_text(encoding='utf-8')
    ok = page.evaluate("s => !new DOMParser().parseFromString(s, 'image/svg+xml').querySelector('parsererror')", svg)
    check(menu.count() == 0 and ok and 'var(' not in svg and '>PSEL<' in svg and dl.value.suggested_filename.endswith('.svg'),
          f'Save image as SVG: a standalone picture (the colours put in, no var()), the names in it ({len(svg)} chars, {dl.value.suggested_filename})')
    page.mouse.click(box['x'] + 5, box['y'] + r[0], button='right')
    with page.expect_download() as dl:
        menu.locator('button[data-m=png]').click()
    png = pathlib.Path(dl.value.path()).read_bytes()
    page.evaluate("window.__img = null; navigator.clipboard.write = items => (window.__img = items.map(i => i.types).flat(), Promise.resolve()); 0")
    page.mouse.click(box['x'] + 5, box['y'] + r[0], button='right'); menu.locator('button[data-m=copyimg]').click()
    page.wait_for_function('window.__img')
    check(png[:8] == bytes([137, 80, 78, 71, 13, 10, 26, 10]) and len(png) > 5000 and page.evaluate('window.__img') == ['image/png'],
          f'Save image as PNG ({len(png)} bytes), Copy image: a PNG to the clipboard')
    nb = js('v.bms.length'); page.mouse.click(box['x'] + 5, box['y'] + r[0], button='right'); menu.locator('button[data-m=marks]').click()
    mk = js("[v.bms.length, v.bms.slice(-2).map(b => [b.t, b.signal]), v.arrows[v.arrows.length - 1].label]")
    lane = js("(() => { v.draw(); const m = v.bmGeo.mids.find(x => x[0] === v.arrows.length - 1), o = WaveFW.internal.peek(v).lay.find(o => o.row.name === 'PSEL'); return [m[2] < o.y, o.y]; })()")
    check(lane[0], f'the arrow between the two bookmarks of one signal runs in its label lane above the row, not through the signal {lane}')
    y2 = js("(o => o.y + o.h / 2 - (WaveFW.internal.peek(v).oy || 0))(WaveFW.internal.peek(v).lay.find(o => o.row.name === 'PSEL'))")   # the arrow's label lane moved it
    page.mouse.click(box['x'] + 5, box['y'] + y2, button='right')
    menu.locator('input[type=color]').evaluate("i => { i.value = '#2f9e44'; i.dispatchEvent(new Event('input', { bubbles: true })); }")
    page.keyboard.press('Escape'); col = js("v.strokeOf(v.M.rows.find(r => r.name === 'PSEL'))")
    page.mouse.click(box['x'] + 5, box['y'] + r[0], button='right'); menu.locator('button[data-m=zoom]').click(); z = js('[v.t0, v.t0 + v.span]')
    check(mk == [nb + 2, [[r[3], 'PSEL'], [r[4], 'PSEL']], '20 ns / 50 MHz'] and col == '#2f9e44' and menu.count() == 0 and z == [r[3], r[4]],
          f'the menu: bookmarks at the ends with an arrow "Δ", the colour of PSEL, Esc closes it, zoom to the range {mk} {col} {z}')
    c.focus(); page.keyboard.press('Escape'); js('(v.setRange(1, 2), 0)'); page.keyboard.down('Control'); page.mouse.click(box['x'] + 50, box['y'] + r[0]); page.keyboard.up('Control')
    check(js('v.range') is None, 'Esc, or a ctrl+click, clears the range')
    # shift+drag: zoom into the range dragged over (the band shown meanwhile), l: back
    w0 = js('[v.t0, v.span]'); want = js('[v.t0 + 100 / v.pxPerT(), 200 / v.pxPerT()]')
    page.keyboard.down('Shift'); page.mouse.move(box['x'] + 100, box['y'] + 30); page.mouse.down(); page.mouse.move(box['x'] + 200, box['y'] + 30, steps=3)
    band = js('!!v.zband'); page.mouse.move(box['x'] + 300, box['y'] + 30, steps=3); page.mouse.up(); page.keyboard.up('Shift')
    w1 = js('[v.t0, v.span, v.range]'); c.focus(); page.keyboard.press('l')
    check(band and abs(w1[0] - want[0]) <= want[1] * 0.02 and abs(w1[1] - want[1]) <= want[1] * 0.02 and w1[2] is None and js('[v.t0, v.span]') == w0,
          f'shift+drag zooms into the range dragged over (as the middle button), no measured range; l: back {w0} -> {w1}')
    # gaps: the menu's row turns them on (kept in this browser, in the state); the picture and WaveDrom leave out the idle stretches
    page.mouse.click(box['x'] + 5, box['y'] + r[0], button='right')
    sub = [menu.locator('.subh + .sub').is_hidden()]; menu.locator('.subh').hover(); sub.append(menu.locator('.subh + .sub').is_visible())
    check(sub == [True, True], f'the gaps are a submenu: hidden, open on the pointer {sub}')
    menu.locator('input.gi').fill('3'); menu.locator('input.gk').fill('0'); menu.locator('input.gk').dispatch_event('change'); menu.locator('input.gon').check()
    g = js("""(() => { const S = v.M.rows.find(r => r.name === 'PSEL'), a = v.M.t0, b = v.M.t1, cuts = v.cutsOf(a, b, [S]), wd = v.toWaveDrom(a, b, [S]).signal.map(s => s.wave);
        const n = v.cutsOf(v.t0, v.t0 + v.span, v.screenRows()).length - 1, on = v.toSVG(); v.setGaps({ gaps: false }); const off = v.toSVG(), wd0 = v.toWaveDrom(a, b, [S]).signal[0].wave;
        v.setGaps({ gaps: true }); return [cuts.length - 1, wd, wd0.length, n, on !== off, v.state().config.gapIdle, (localStorage.getItem(v.lookKey) || '').includes('"gap"')]; })()""")
    gaps = lambda w: [i for i, ch in enumerate(w) if ch == '|']
    check(g[0] >= 1 and len(g[1]) == 2 and len(gaps(g[1][0])) == g[0] and gaps(g[1][0]) == gaps(g[1][1]) and len(g[1][0]) < g[2] and g[4] and g[5] == 3 and g[6]
          and menu.locator('.gn').inner_text() == f'Gaps: {g[3]}', f'the menu\'s gaps (idle 3, keep 0): "|" in every WaveDrom wave at the same cells, the picture '
          f'shorter, kept in this browser and in the state {g} {menu.locator(".gn").inner_text()!r}')
    cm = menu.evaluate("m => !m.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))")
    check(cm, 'a contextmenu on the open menu (Windows: the release of the right button) opens no browser menu over it')
    page.keyboard.press('Escape')
    # the signals the gaps follow: Gaps by this signal (// in the names), only them in the picture, ✕: every signal again
    page.mouse.click(box['x'] + 5, box['y'] + y2, button='right'); menu.locator('.subh').click(); menu.locator('button[data-m=gref]').click()
    ref = js("[[...v.gapRefSet()].map(r => r.name), v.gapOpt().gaps, [...WaveFW.internal.peek(v).namesEl.querySelectorAll('.row.gref .n')].map(e => e.textContent)]")
    page.mouse.click(box['x'] + 5, box['y'] + y2, button='right'); menu.locator('.subh').click(); by = menu.locator('.gp').nth(1).inner_text()
    menu.locator('input.gonly').check(); only = js("[v.exportRows().filter(r => r.type !== 'lane').map(r => r.name), v.toWaveDrom(v.M.t0, v.M.t1).signal.map(s => s.name)]")
    menu.locator('button[data-m=grefx]').click(); after = js('[v.gapRefSet().size, v.exportRows().length]')
    check(ref[0] == ['PSEL'] and ref[1] and ref[2] == ['PSEL'] and 'by 1 signal' in by and only == [['PSEL'], ['PCLK', 'PSEL']] and after == [0, 0],
          f'Gaps by this signal: the gaps follow PSEL (// in the names), "only them": the picture and WaveDrom take PSEL alone; ✕: every signal again {ref} {by!r} {only} {after}')
    # the clock the gaps count: Gaps: cycles of this clock (↑ in the names), the cycles under the axis in its name
    ck = js("""(() => { const C = v.M.rows.find(r => r.name === 'PCLK' && r.tr), P = v.M.rows.find(r => r.name === 'PSEL' && r.tr);
        v.menu(10, 10, C); const item = v.menuEl.querySelector('button[data-m=gclk]').textContent; v.menuEl.querySelector('button[data-m=gclk]').click();
        v.setGaps({ gapIdle: 3, gapKeep: 0, gapSignals: [P.full] }); const svg = v.toSVG({ from: v.M.t0, to: v.M.t1 });
        return [item, v.gapClockRow() === C, [...WaveFW.internal.peek(v).namesEl.querySelectorAll('.row.gclk .n')].map(e => e.textContent), /· \\d+ PCLK/.test(svg),
          v.cutsOf(v.M.t0, v.M.t1, [P]).length > 1]; })()""")
    aux = js("""(() => { const A = v.M.rows.find(r => r.name === 'PENABLE' && r.tr), P = v.M.rows.find(r => r.name === 'PSEL' && r.tr);
        v.menu(10, 10, A); v.menuEl.querySelector('button[data-m=gaux]').click(); v.setGaps({ gapOnly: true, gapCount: 'edges' });
        const rows = v.exportRows().filter(r => r.type !== 'lane').map(r => r.name), names = [...WaveFW.internal.peek(v).namesEl.querySelectorAll('.row.gaux .n')].map(e => e.textContent);
        v.menu(10, 10, P); v.menuEl.querySelector('button[data-m=gaux]').click();   // one role per signal: PSEL leaves the ones the gaps follow
        const moved = [v.gapRefSet().size, v.gapRows().aux.size]; v.setGaps({ gapOnly: false }); return [rows, names, moved]; })()""")
    check(aux == [['PCLK', 'PSEL', 'PENABLE'], ['PENABLE'], [0, 2]],
          f'Gaps: count its changes: PENABLE counted (+ in the names), "only them" takes the three kinds; one role per signal {aux}')
    check(ck[0] == 'Count in cycles of this clock' and ck[1] and ck[2] == ['PCLK'] and ck[3] and ck[4],
          f'Gaps: cycles of this clock: the gaps count PCLK (↑ in the names), "· N PCLK" under the axis of the picture {ck}')
    rs = js("""(() => { v.setGaps({ gaps: true, gapIdle: 5, gapAux: ['x'] }); v.menu(10, 10, null); v.menuEl.querySelector('button[data-m=greset]').click();
        const g = v.gapOpt(); return [g.gaps, g.gapIdle, g.gapAux.length, g.gapSignals.length, g.gapClock, !!v.local.gap, v.menuEl]; })()""")
    check(rs == [False, 16, 0, 0, None, False, None], f'Reset the gaps: every gap setting of the viewer back to the settings, the menu closed {rs}')
    js('(v.setGaps(null), 0)')
    # radix and hide from the menu (a bus of the dump: apb_tb.PADDR), the Hidden button, kept over a reload and in the state
    page.goto((build / 'examples' / 'apb' / 'apb_all.html').as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    c.scroll_into_view_if_needed(); box = c.bounding_box()
    yb = lambda n: js(f"(o => o.y + o.h / 2 - (WaveFW.internal.peek(v).oy || 0))(WaveFW.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.{n}'))")
    # the rows the clicks go to in view (the bar may wrap to more lines and the rows' window be shorter)
    js("(o => { if (v.root.classList.contains('wv-scroll')) v.bodyEl.scrollTop = Math.max(0, o.y - 60); v.draw(); })(WaveFW.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.PADDR'))")
    page.wait_for_timeout(100); box = c.bounding_box()
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PADDR'), button='right'); menu.locator('select:not(.gcnt)').select_option('bin')
    rx = [js("v.valueAt(v.M.rows.find(r => r.full === 'apb_tb.PADDR'), v.cursor)"), menu.count()]
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PWDATA'), button='right'); menu.locator('button[data-m=hide]').click()
    hid = [js("WaveFW.internal.peek(v).vis.some(r => r.full === 'apb_tb.PWDATA')"), page.locator('.wv button[data-act=unhide]').first.inner_text(), js('v.state().hidden'), js('v.state().radix')]
    page.reload(); page.wait_for_load_state('networkidle')
    kept = [js("WaveFW.internal.peek(v).vis.some(r => r.full === 'apb_tb.PWDATA')"), js("v.M.rows.find(r => r.full === 'apb_tb.PADDR').radix")]
    page.locator('.wv button[data-act=unhide]').first.click(); js("(v.setRadix('apb_tb.PADDR', null), 0)")
    back = [js("WaveFW.internal.peek(v).vis.some(r => r.full === 'apb_tb.PWDATA')"), js("v.M.rows.find(r => r.full === 'apb_tb.PADDR').radix || ''"), js('localStorage.getItem(v.rowsKey)')]
    check((rx[0].startswith('0b') or set(rx[0]) <= set('01_')) and rx[1] == 0 and hid[:2] == [False, 'Hidden: 1 ✕'] and hid[2] == ['apb_tb.PWDATA'] and hid[3] == {'apb_tb.PADDR': 'bin'}
          and kept == [False, 'bin'] and back == [True, '', None],
          f'the menu: Radix bin on PADDR, Hide PWDATA, Hidden: 1 ✕ in the bar; kept over a reload and in the state; shown again, the page\'s radix back {rx} {hid} {kept} {back}')
    # a highlighted row clicked: the colour, the radix and Hide of the menu go to every highlighted row
    js("(v.highlight(null), ['PADDR', 'PWDATA', 'PSEL'].forEach(n => v.toggleHighlight(v.M.rows.find(r => r.full === 'apb_tb.' + n))), 0)")
    page.wait_for_timeout(50); box = c.bounding_box()   # Highlight: 3 ✕ came into the bar: it may wrap and move the waves
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PADDR'), button='right')
    head = menu.locator(':scope > .mh').last.inner_text(); menu.locator('select:not(.gcnt)').select_option('bin')
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PADDR'), button='right')
    menu.locator('input[type=color]').evaluate("i => { i.value = '#2f9e44'; i.dispatchEvent(new Event('input', { bubbles: true })); }"); page.keyboard.press('Escape')
    many = js("['PADDR', 'PWDATA', 'PSEL', 'PENABLE'].map(n => [v.painted.get('apb_tb.' + n) || '', v.M.rows.find(r => r.full === 'apb_tb.' + n).radix || ''])")
    js("(v.highlight(null), v.unpaint(), ['PADDR', 'PWDATA'].forEach(n => v.setRadix('apb_tb.' + n, null)), 0)")
    check('3 signals' in head and many[0] == ['#2f9e44', 'bin'] and many[1] == ['#2f9e44', 'bin'] and many[2][0] == '#2f9e44' and many[3][0] == '',
          f'right button on a highlighted row: the colour and the radix go to all the highlighted rows, not the others ({head!r} {many})')
    # shift+click on the waves: the second cursor, Δ in time and in cycles of the clock; x swaps; keys 1–9: bookmarks
    js("(v.reset(), v.select('apb_tb.PSEL'), v.cursor = 25000, v.draw(), 0)")
    c.click(position={'x': 600, 'y': yb('PCLK')}, modifiers=['Shift'])
    c2 = js("[v.cursor2, v.delta2(), v.curEl.textContent, v.cycles(v.clockFor(), v.cursor, v.cursor2), v.M.rows.find(r => r.full === 'apb_tb.PCLK').tr.filter(o => o.k === '1' && o.t > v.cursor && o.t <= v.cursor2).length, v.state().cursor2]")
    c.focus(); page.keyboard.press('x'); sw = js('[v.cursor, v.cursor2]'); page.keyboard.press('x')
    nb = js("(v.bms = [], v.mark('one'), v.cursor = 0, v.draw(), v.bms[0].t)"); page.keyboard.press('1'); k1 = js('v.cursor')
    dt = page.locator('.wv .notes .dt').first.inner_text(); page.keyboard.press('Escape'); gone = js('v.cursor2')
    check(c2[0] and c2[0] != 25000 and c2[3] == c2[4] and c2[3] > 0 and f'{c2[3]} PCLK' in c2[1] and 'cursor 2' in c2[2] and c2[5] == c2[0] and sw == [c2[0], 25000]
          and k1 == nb and dt == 'at the cursor' and gone is None,
          f'shift+click: the second cursor (on an edge), Δ and the PCLK cycles between, in the state; x swaps, 1 goes to bookmark 1, its Δ; Esc clears it {c2} {sw} {dt!r}')
    js("(v.bms = [], v.arrows = [], v.changed(true), 0)")
    # the edge kind "= value": the next / previous time the selected signal becomes it (hex, Verilog, decimal, an enum
    # label); "X / Z": the next x or z of the selected signal or of any shown one
    want = js("(r => [r.tr.find(o => o.raw && parseInt(o.raw, 16) === 0x40).t, v.M.rows.find(r => r.full === 'apb_tb.phase').tr.find(o => o.v === 'ACCESS').t])(v.M.rows.find(r => r.full === 'apb_tb.PADDR'))")
    js("(v.reset(), v.select('apb_tb.PADDR'), v.cursor = 0, 0)")
    page.locator('.wv select.edge').first.select_option('value'); ev = page.locator('.wv input.ev').first
    shown = ev.is_visible(); ev.fill('0x40'); ev.press('Enter'); f1 = js('v.cursor')
    js('(v.cursor = 0, 0)'); ev.fill("8'h40"); ev.press('Enter'); f2 = js('v.cursor'); ev.fill('64'); js('(v.cursor = 0, 0)'); ev.press('Enter'); f3 = js('v.cursor')
    js('(v.cursor = v.M.t1, 0)'); ev.press('Shift+Enter'); back = js('v.cursor')
    js("(v.select('apb_tb.phase'), v.cursor = 0, 0)"); ev.fill('access'); ev.press('Enter'); f4 = js('v.cursor')
    ev.fill('0x99'); ev.press('Enter'); none = page.locator('.wv .bar .toast').first.inner_text()
    xz = js("""(() => { const r = v.M.rows.find(r => r.full === 'apb_tb.PSLVERR'), keep = r.tr; r.tr = [...keep.filter(o => o.t < 33000), { t: 33000, k: 'x' }, { t: 34000, k: '0' }, ...keep.filter(o => o.t > 34000)];   // an X to find
        v.select(null); v.cursor = v.M.t0; v.setEdgeKind('xz'); const xs = WaveFW.internal.peek(v).vis.filter(r => r.type === 'sig' && r.tr).flatMap(r => r.tr.filter((o, i) => (o.k === 'x' || o.k === 'z' || (o.raw && /[xz]/i.test(o.raw))) && o.t > v.cursor && !(i && (r.tr[i - 1].k === 'x' || r.tr[i - 1].k === 'z'))).map(o => o.t));
        const exp = xs.length ? Math.min(...xs) : null; v.edge(1); const got = v.cursor; r.tr = keep; v.draw(); return [exp, got]; })()""")
    js("(v.setEdgeKind('any'), 0)"); hid = not ev.is_visible()
    check(shown and f1 == want[0] and f2 == want[0] and f3 == want[0] and back == want[0] and f4 == want[1] and 'no 0x99 after the cursor' in none and xz == [33000, 33000] and hid,
          f'= value: the selected signal becomes 0x40 / 8\'h40 / 64 (shift+Enter: before), an enum label (ACCESS); none: said; X / Z: the first one of any signal {[f1, f2, f3, back, f4]} {want} {none!r} {xz}')
    # the menu's Radix: fixed point (sq and its fraction bits), float; enumColors: a state's own fill
    js("(v.reset(), 0)"); page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PWDATA'), button='right')
    menu.locator('select:not(.gcnt)').select_option('sq'); qf = menu.locator('input.qf'); qopen = [qf.is_visible(), menu.count()]
    qf.fill('16'); qf.dispatch_event('input'); fx = js("[v.M.rows.find(r => r.full === 'apb_tb.PWDATA').radix, v.valueAt(v.M.rows.find(r => r.full === 'apb_tb.PWDATA'), 60000)]")
    page.keyboard.press('Escape'); js("(v.setRadix('apb_tb.PWDATA', 'float'), 0)"); fl = js("v.valueAt(v.M.rows.find(r => r.full === 'apb_tb.PWDATA'), 60000)")
    js("(v.setRadix('apb_tb.PWDATA', null), 0)")
    page.evaluate("WaveFW.configure({enumColors: {ACCESS: '#ff00aa', 1: 'c8'}})"); esvg = js('v.toSVG()'); page.evaluate("WaveFW.configure({enumColors: null})")
    check(qopen == [True, 1] and fx == ['sq16', '-13569.9999847412109375'] and fl == '-8323073' and '#ff00aa' in esvg,
          f'Radix: fixed sq with 16 fraction bits (the menu stays open for them), float; enumColors fill the ACCESS state {fx} {fl}')
    # Analog from the menu: the bus as a step plot three rows high, kept over a reload and in the state; As a bus: back
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('n_done'), button='right'); menu.locator('button[data-m=analog]').click()
    an = js("[(o => [o.h, v.rowH.sig])(WaveFW.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.n_done')), v.state().analog, Math.round(v.rowEl(v.M.rows.find(r => r.full === 'apb_tb.n_done')).getBoundingClientRect().height)]")
    page.reload(); page.wait_for_load_state('networkidle'); c.scroll_into_view_if_needed(); box = c.bounding_box()
    kept = js("v.M.rows.find(r => r.full === 'apb_tb.n_done').analog")
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('n_done'), button='right'); label = menu.locator('button[data-m=analog]').inner_text(); menu.locator('button[data-m=analog]').click()
    off = js("[v.M.rows.find(r => r.full === 'apb_tb.n_done').analog, (o => o.h)(WaveFW.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.n_done'))]")
    parsed = page.evaluate("WaveFW.parse({ signal: [{ name: 'lvl', wave: '=.=', data: ['1', '9'], analog: 2 }] }).rows[0].analog")
    check(an[0] == [3 * an[0][1], an[0][1]] and an[1] == {'apb_tb.n_done': 3} and an[2] == 3 * an[0][1] and kept == 3 and label == 'As a bus' and off == [False, an[0][1]] and parsed == 2,
          f'Analog: a step plot three rows high (names too), kept over a reload and in the state; As a bus: back; "analog" in the WaveJSON {an} {kept} {off}')
    js("(v.setAnalog('apb_tb.n_done', null), localStorage.clear(), 0)")
    # a click on a name selects it, shift+click every signal from it to the clicked one: selected, nothing dimmed, the
    # selection's tint inside the bus values too
    px = lambda n: js(f"""(() => {{ v.draw(); const o = WaveFW.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.{n}'), r = window.devicePixelRatio || 1, x = Math.round(v.canvas.width / 2 / r);
        return [...v.canvas.getContext('2d').getImageData(Math.round(x * r), Math.round((o.y + o.h / 2 + 5 - (WaveFW.internal.peek(v).oy || 0)) * r), 1, 1).data].slice(0, 3); }})()""")
    names = page.locator('.wv .names').first
    p0 = px('PADDR'); js("(v.highlight(null), 0)")
    names.locator('.row:not(.grp)', has_text='PREADY').first.locator('.n').click()
    names.locator('.row:not(.grp)', has_text='PWDATA').first.locator('.n').click(modifiers=['Shift'])
    run = js("[[...v.selRun].map(r => r.name), v.sel && v.sel.name, v.picks.size, document.querySelectorAll('.wv .names .row.dim').length, String(getSelection()), v.root.querySelectorAll('.names .row.sel').length]")
    p1 = px('PADDR')
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PADDR'), button='right'); menu.locator('input[type=color]').evaluate("i => { i.value = '#2f9e44'; i.dispatchEvent(new Event('input', { bubbles: true })); }"); page.keyboard.press('Escape')
    col = js("['PREADY', 'PADDR', 'PWDATA', 'PRDATA'].map(n => v.painted.get('apb_tb.' + n) || '')")
    js("(v.unpaint(), 0)"); names.locator('.row:not(.grp)', has_text='PSEL').first.locator('.n').click(); one = js('[v.selRun.size, v.sel.name]')
    check(run[0][0] == 'PREADY' and run[0][-1] == 'PWDATA' and len(run[0]) >= 4 and run[1] == 'PWDATA' and run[2:] == [0, 0, '', len(run[0])] and p1 != p0
          and col[:3] == ['#2f9e44'] * 3 and col[3] == '' and one == [0, 'PSEL'],
          f'shift+click a name: every signal from the last clicked one selected (no dimming, no text selected), the tint inside a bus value {p0} -> {p1}; the menu colours the run; a click: one again {run} {col} {one}')
    # alt+drag: a box — its time the range, the signals it touches selected, then the menu; Save as WaveDrom takes them
    ya, yb = yb('PSEL'), yb('PREADY'); x0, x1 = 120, 420
    page.keyboard.down('Alt'); page.mouse.move(box['x'] + x0, box['y'] + ya); page.mouse.down(); page.mouse.move(box['x'] + x1, box['y'] + yb, steps=5)
    drawn = js('!!v.box'); page.mouse.up(); page.keyboard.up('Alt')
    bx = js("[[...v.selRun].map(r => r.name), v.range && v.range.map(t => Math.round(t)), Math.round(v.t0 + 120 / v.pxPerT()), Math.round(v.t0 + 420 / v.pxPerT()), v.box]")
    head2 = menu.locator('.mh').first.inner_text() if menu.count() else ''
    with page.expect_download() as dl:
        menu.locator('button[data-m=wdjson]').click()
    wd2 = [x['name'] for x in json.loads(pathlib.Path(dl.value.path()).read_text(encoding='utf-8'))['signal']]
    check(drawn and bx[0] == ['PSEL', 'PENABLE', 'PWRITE', 'PREADY'] and abs(bx[1][0] - bx[2]) <= 1 and abs(bx[1][1] - bx[3]) <= 1 and bx[4] is None
          and wd2 == ['PCLK', 'PSEL', 'PENABLE', 'PWRITE', 'PREADY'],
          f'alt+drag: a box (drawn while dragging); its time the range, its signals selected, the menu opens; WaveDrom of those signals {bx} {head2!r} {wd2}')
    js("(v.reset(), 0)")
    # the highlighted rows: the picture has them only; WaveDrom of them over the range, a cell per clock cycle
    js("(v.highlight(null), ['PADDR', 'PWDATA', 'PSEL'].forEach(n => v.toggleHighlight(v.M.rows.find(r => r.full === 'apb_tb.' + n))), v.setRange(0, 200000), 0)")
    pmenu = lambda: js("(v.menu(200, 200, v.M.rows.find(r => r.full === 'apb_tb.PADDR')), 0)")   # the right button itself: above
    settle(page)   # the highlight drawn before the picture
    pick = lambda m: menu.locator(f'button[data-m={m}]').click()   # a menu opened right after another one closed (its stale listener closed it)
    pmenu()
    with page.expect_download() as dl:
        pick('svg')
    svg = pathlib.Path(dl.value.path()).read_text(encoding='utf-8')
    pmenu()
    with page.expect_download() as dl:
        pick('wdjson')
    wd = json.loads(pathlib.Path(dl.value.path()).read_text(encoding='utf-8')); name = dl.value.suggested_filename
    sig = {x['name']: x for x in wd['signal']}
    back = page.evaluate("d => { const M = WaveFW.parse(d); return M.rows.filter(r => r.type === 'sig').map(r => r.name); }", wd)
    js("(v.highlight(null), v.setRange(null), 0)")
    check('>PADDR<' in svg and '>PWDATA<' in svg and '>PRDATA<' not in svg and '>PREADY<' not in svg,
          'with rows highlighted, Save image draws those rows only')
    check(name.endswith('.wavedrom.json') and list(sig) == ['PCLK', 'PSEL', 'PADDR', 'PWDATA'] and set(sig['PCLK']['wave'][1:]) == {'.'} and sig['PCLK']['wave'][0] == 'p'
          and len({len(x['wave']) for x in wd['signal']}) == 1 and sig['PADDR']['data'][:3] == ['0x00', '0x04', '0x40'] and back == list(sig),
          f'Save as WaveDrom: the highlighted signals and their clock (p...), a cell per cycle, bus values as data; WaveFW reads it back {name} {[(k, x["wave"][:24]) for k, x in sig.items()]}')
    # ctrl+F with the bar scrolled away: the find group floats over the waves, in the window; Esc puts it back
    js("(document.body.style.paddingBottom = '3000px', scrollTo(0, scrollY + v.root.querySelector('.bar').getBoundingClientRect().bottom + 40), v.canvas.focus({ preventScroll: true }), 0)")
    page.keyboard.press('Control+f')
    fl = js("(g => { const b = g.getBoundingClientRect(), w = v.wcol.getBoundingClientRect(); return [g.classList.contains('float'), document.activeElement === v.qEl, b.top >= 0 && b.bottom <= innerHeight, b.right <= w.right + 1, v.root.querySelector('.bar').getBoundingClientRect().bottom < 0]; })(v.qEl.closest('.find'))")
    page.keyboard.type('pdata'); settle(page); page.keyboard.press('Enter'); found = js('v.found.size')
    page.keyboard.press('Escape'); docked = js("[v.qEl.closest('.find').classList.contains('float'), document.activeElement === v.canvas, v.found.size]")
    js("(document.body.style.paddingBottom = '', scrollTo(0, 0), 0)"); js("(v.focusFind(), 0)"); inbar = js("v.qEl.closest('.find').classList.contains('float')")
    check(fl == [True] * 5 and found >= 2 and docked == [False, True, 0] and not inbar,
          f'ctrl+F with the bar off the screen: the find group floats over the waves, focused, n/Enter work; Esc: back in the bar; the bar on the screen: no float {fl} {found} {docked} {inbar}')
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (range, menu)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def sva_docs(page):
    v = page.locator('#ex-sva')
    page.evaluate('SVA.ready()')
    got = page.evaluate("document.querySelector('#ex-sva').waveView.sva.bindings.map(b => [b.assert, b.scope, b.state, b.results && b.results.assertions[0].attempts.map(a => [a.start, a.end, a.result])])")
    want = [['a_req_ack', '', 'bound', [[2, 3, 'pass'], [6, 9, 'fail'], [11, 13, 'pass']]], ['c_req', '', 'bound', [[2, 3, 'pass']]]]
    check(got == want, f'docs: the assertion bound in the WaveJSON is evaluated in the page {got}')
    shown = page.evaluate("SVA.panels().filter(p => !p.el.hidden).map(p => p.v.root.id)")
    check(shown == ['ex-sva', 'ex-apb'] and page.locator('.wv .tg.sv button[data-sv=load]').count() == page.locator('.wv').count(),
          f'docs: only the viewers with assertions list them ({shown}); every viewer has Load file…')
    apb = page.evaluate("(() => { const v = document.querySelector('#ex-apb').waveView; return [v.sva.bindings.filter(b => b.state === 'bound' && b.results).length, WaveFW.internal.peek(v).vis.filter(r => r.sva).length]; })()")
    leg = page.locator('#ex-apb-svg svg').inner_html() if page.locator('#ex-apb-svg svg').count() else ''
    check(apb == [14, 14] and '(!PREADY)[*2]  (cons)' in leg and '##1 PREADY  (cons)' in leg and '(ante)' in leg,
          f'docs: the APB example with its 14 checks bound and drawn {apb}; the SVG of apb_read_waits with the legend of its steps')
    v.locator('li[data-a="a_req_ack"] button[data-sv=fail]').click()
    check('cursor cycle 7 ' in v.locator('.cur').inner_text() and 'no ack within [1:3]' in v.locator('.bar .toast').inner_text() and 'attempt 2: fail' in v.locator('li[data-a="a_req_ack"]').inner_text(),
          f'docs: Go to first failure selects the attempt, the cursor at its start ({v.locator(".cur").inner_text()}, {v.locator(".bar .toast").inner_text()})')
    mk = page.evaluate("document.querySelector('#ex-sva').waveView.sva.bindings[0].draw.lane.marks.map(k => [k[0], k[1] < k[3] && k[3] < k[2], k[4]])")
    check(['fail', True, True] in mk and ['pass', False, True] in mk,
          f'docs: an attempt is a bracket from its start to its end; the failure green up to its last good step, then red {mk}')
    page.keyboard.press('Escape')
    rows = page.evaluate("WaveFW.internal.peek(document.querySelector('#ex-sva').waveView).vis.filter(r => r.cls && !/^sva-x|^sva-expr/.test(r.cls)).map(r => [r.cls, r.name])")
    check(rows[:4] == [['sva-g fails', '⚑ a_req_ack · 2 pass · 1 fail'], ['sva-lane', 'attempts'], ['sva-step', '1. req'], ['sva-step', '2. ##[1:3] ack']]
          and [r[1] for r in rows if r[0] == 'sva-copy'][:4] == ['clk', 'rst_n', 'req', 'ack'], f'docs: the assertion group under the top: lane, steps, the bound signals {rows[:6]}')
    page.wait_for_function("WaveFW.internal.peek(document.querySelector('#ex-sva').waveView).vis.filter(r => (r.cls || '').startsWith('sva-expr') && r.tr.length).length === 2")
    xr = page.evaluate("""(() => { const v = document.querySelector('#ex-sva').waveView, rs = WaveFW.internal.peek(v).vis.filter(r => (r.cls || '').startsWith('sva-expr'));
      return [WaveFW.internal.peek(v).vis[WaveFW.internal.peek(v).vis.findIndex(r => r.cls === 'sva-xg') - 1].name, rs.map(r => [r.name, r.tr.filter(o => o.k === '1').map(o => o.t)])]; })()""")
    check(xr[0] == 'ack' and xr[1] == [['ƒ req && !ack', [2, 6, 11]], ['ƒ @(posedge clk) $past(req) && !ack', [8, 13]]],
          f'docs: the WaveJSON\'s "exprs" are rows ƒ under the top\'s signals: after every change of their signals, or sampled at the clock {xr}')
    svg = page.locator('#ex-sva-svg svg')
    page.wait_for_function("(document.querySelector('#ex-sva-svg svg') || {}).innerHTML.includes('ƒ req')")
    txt = svg.inner_html() if svg.count() else ''
    check('ƒ expressions (2)' in txt and 'ƒ req &amp;&amp; !ack' in txt, 'docs: the static SVG draws the expressions too')
    check('⚑ a_req_ack · 2 pass · 1 fail' in txt and '##[1:3] ack  (cons)' in txt and 'no ack within [1:3]' in txt and '>1T<' in txt,
          'docs: the static SVG of the same JSON, evaluated in the page: the group, the arrows with their labels, the legend of the steps')
    fl = page.evaluate("""(() => { const fig = document.querySelector('#ex-apb-svg svg'); return [document.querySelector('#ex-sva-svg svg').innerHTML.match(/>(▶ start|✕ fail|✓ pass)</g),
        fig ? fig.innerHTML.match(/>(▶ start|✓ pass)</g) : null]; })()""")
    check(fl == [['>▶ start<', '>✕ fail<', '>▶ start<', '>✓ pass<'], ['>▶ start<', '>✓ pass<']],
          f'docs: the static SVGs show the first failure (else the first attempt) of each assertion with its start and end flags {fl}')


def sva_nesting(browser, build):
    """The WebAssembly engine at the nesting limit (500 levels, docs/sva/ENGINE.md): an expression of the page (exprs)
    499 parentheses deep, an assertion 498 deep (its property takes the rest) parsed, taken apart (explain) and
    evaluated; one level more is an error, never a crashed tab (the module's stack: sva/.cargo/config.toml). Its own
    page: a crash takes nothing else with it."""
    page = browser.new_page()
    page.goto((ROOT / 'docs' / 'index.html').as_uri()); page.wait_for_load_state('networkidle')
    try:
        r = page.evaluate("""async () => {
          const e = await SVA.engine(), deep = n => '('.repeat(n) + 'a' + ')'.repeat(n);
          const src = n => `module m; a_n: assert property (@(posedge clk) ${deep(n)} |-> b); endmodule`, tr = { signals: { a: [1, 0, 1], b: [1, 1, 1] } };
          const msg = o => (o.errors || []).map(x => x.msg || x).join('; ');
          const x = e.call({ files: [src(498)], trace: tr, explain: { assert: 'a_n', from: 0, to: 2 } }), v = e.call({ files: [src(498)], trace: tr });
          return { exprs: e.call({ exprs: [deep(499)], trace: tr }).exprs[0].values, parsed: msg(e.call({ source: src(498) })), explain: x.explain && x.explain.length,
            pass: v.assertions && v.assertions[0].stats.pass, over: msg(e.call({ source: src(499) })), overExpr: JSON.stringify(e.call({ exprs: [deep(501)] }).exprs[0].errors || []) };
        }""")
    except Exception as e:   # noqa: BLE001 — a crashed tab is this check's failure
        r = {'crash': str(e)[:80]}
    check(not r.get('crash') and r['exprs'] == [1, 0, 1] and r['parsed'] == '' and r['explain'] == 2 and r['pass'] == 2
          and 'nested too deeply' in r['over'] and 'nested too deeply' in r['overExpr'],
          f'WebAssembly at the nesting limit: exprs 499 deep, an assertion 498 deep parsed, explained, evaluated; one more an error, no crash {r}')
    page.close()


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
    check(r['tedges'] == [10, 30] and r['tany'] == [10, 20, 30] and r['tb'] == ['0', '1', 'hff', None],
          f'sva.js: tvSampler edges as IEEE 9.4.2 (x → 1 a posedge, 1 → x a negedge) and values {r["tedges"]} {r["tany"]} {r["tb"]}')
    # the labels of a clock-sampled view read back (vcd2wavedrom's label(): the row's radix), and "raw" next to them
    lb = page.evaluate("""[SVA.fromLabel('0x1F'), SVA.fromLabel('0101', 'bin'), SVA.fromLabel('-3', 'signed', 8), SVA.fromLabel('0o17'),
        SVA.fromLabel('"AB"', 'ascii'), SVA.fromLabel('12'), SVA.fromLabel('0x1x'), SVA.fromLabel('IDLE')]""")
    check(lb == ['h1F', '0101', 253, 15, 'h4142', 12, 'h1x', 'x'], f'sva.js: bus labels back to values (hex, bin, signed, oct, ascii, dec, x) {lb}')
    raw = page.evaluate("""(() => { const W = WaveFW.parse({ signal: [{ name: 'clk', wave: 'p...' }, { name: 'd', wave: '=.=.', data: ['0101', '0011'], radix: 'bin', width: 4 },
        { name: 'e', wave: '=.=.', data: ['?', '?'], raw: ['a', '5'], width: 4 }], time: { t0: 0, cycle: 10 } });
      const rows = Object.fromEntries(W.rows.map(r => [r.name, r])), s = SVA.rowSampler(rows); return [s.column('d', [15, 25]), s.column('e', [15, 25]), s.width('e')]; })()""")
    check(raw == [['0101', '0011'], ['ha', 'h5'], 4], f'sva.js: a clock-sampled bus: its label by radix, or its "raw" value; "width" {raw}')
    ss = page.evaluate("""(() => { const n = new Set(['PSEL', 'PENABLE', 'PADDR', 'req', 'u.full', 'hb', 'd']);
      return [SVA.stepSignals('PSEL && !PENABLE && PADDR[7:4] == 0 && PSEL', n), SVA.stepSignals("##[1:3] $rose(req) && d == 8'hb && u.full.x", n),
        SVA.stepSignals("st == pkg::IDLE && $past(d, 2) != 4'bxx01", n), SVA.stepSignals(`"req" || 1'b1`, n)]; })()""")
    ex = page.evaluate("""(async () => { const e = await SVA.engine(), X = SVA.expressions;
      const r = e.call({ files: ['package p; localparam int TWO = 2; endpackage'], exprs: ['a && !b', 'd == p::TWO', 'a +', '$rose(a)'], trace: { signals: { a: [0, 1, 1, 0], b: [1, 1, 0, 0], d: [2, 2, 3, 2] }, widths: { d: 4 } } });
      return [r.exprs.map(x => x.values || x.errors), r.exprs[1].signals, X.splitClock('@( negedge clk_i ) a ##1 b'), X.splitClock(' a'), [X.tvValue(1, 1), X.tvValue('x', 1), X.tvValue(300, 12), X.tvValue('hABC', 12), X.tvValue('1x0101', 6)]]; })()""")
    check(ex[0][:2] == [[0, 0, 1, 0], [1, 1, 0, 1]] and '1:4' in ex[0][2][0] and ex[0][3] == [0, 1, 0, 0] and ex[1] == [{'name': 'd'}]
          and ex[2] == {'clock': {'edge': 'negedge', 'signal': 'clk_i'}, 'body': 'a ##1 b'} and ex[3]['clock'] is None and ex[4] == ['1', 'x', '12c', 'abc', "'b1x0101"],
          f'sva.js: expressions through the engine (values per cycle, package constants, errors with line:col), the clock prefix, values as "tv" {ex}')
    pp = page.evaluate("SVA.propParts('a && b |-> ##[1:3] c intersect (d ##1 e) or f throughout g iff error_or')")
    check(pp == ['a && b', '|-> ##[1:3] c', 'intersect (d', '##1 e)', 'or f', 'throughout g', 'iff error_or'],
          f'sva.js: a property in parts that wrap whole, each from an operator (an operator alone joins the next part) {pp}')
    check(ss == [['PSEL', 'PENABLE', 'PADDR'], ['req', 'd', 'u.full'], ['d'], []],
          f'sva.js: the signals a step reads, from its label (system functions, based literals, strings, unknown names skipped; a.b.c -> a.b) {ss}')


UNITS_SETUP = r"""
const I = WaveFW.internal, F = WaveFW;
const D = (w, v, r, extra) => F.decode(Object.assign({ width: w }, extra || {}), v, r);
const UM = F.parse({ signal: [['tb',
  { name: 'b', path: 'tb.b', tv: [[0, '0'], [10, '1'], [20, 'x'], [30, '1'], [40, '0']] },
  { name: 'd', path: 'tb.d', width: 8, tv: [[0, '00'], [10, 'fd'], [20, 'x'], [30, '03'], [40, 'fd']] },
  { name: 'st', path: 'tb.st', width: 2, enum: { 0: 'IDLE', 1: 'RUN' }, tv: [[0, '0'], [10, '1'], [20, '0']] },
  { name: 's_pix_valid', path: 'tb.u.s_pix_valid', tv: [[0, '0']] }]], time: { t0: 0, unit: 'ps' } });
const R = n => UM.rows.find(r => r.name === n);
const PW = s => { const w = I.parseWant(s); return w && [w.n == null ? null : String(w.n), w.neg, w.text]; };
const VI = (n, i, w) => I.valueIs(R(n), R(n).tr[i], I.parseWant(w));
const FE = (n, t, dir, kind, want) => I.findEdge(R(n), t, dir, kind, want == null ? null : I.parseWant(want));
const FR = (n, f) => { const r = I.fieldRow(R(n), f, 1, []); return r && r.tr.map(o => (o.k === '=' ? o.raw : o.k)); };
const FIND = (n, q, o) => { const m = I.findRow(R(n), q.split(' '), UM, o || {}); return m && m.idx; };
const AV = (o, w, r, extra) => I.analogValue(Object.assign({ width: w }, extra || {}), o, r);
const VW = (text, o) => F.vcdToWave(text, o);
const XZ = F.parse(F.vcdToWave(`$timescale 1ns $end $scope module tb $end $var wire 8 ! b [7:0] $end $upscope $end $enddefinitions $end
#0 b1x0z1z0x ! #10 bz ! #20 bx1 ! #30 b101 !`).doc);
const MX = F.parse({ signal: [{ name: 'v', width: 4, tv: [[0, "'b10x1"], [1, "'b10z1"], [2, "'b11x1"], [3, "'b11x1"]] }] });
const RT = (b, w) => I.bitsOf(F.parse({ signal: [{ name: 'v', width: w, tv: [[0, I.vcdHex(b, w)]] }] }).rows[0].tr[0], w);
const XT = F.parse({ signal: [{ name: 'e', tv: [[0, '0'], [1e12, '1'], [1e12 + 1, '0'], [1e12 + 2, '1']] }] }).rows[0];
const vcd = (vars, body) => `$timescale 1ns $end $scope module tb $end ${vars} $upscope $end $enddefinitions $end ${body}`;
const tvOf = (doc, name) => { const walk = a => { for (const x of a) { if (Array.isArray(x)) { const r = walk(x.slice(1)); if (r) return r; }
  else if (x && x.name === name) return x; } return null; }; const s = walk(doc.signal); return s && s.tv; };
// a port of the bus decoders on a WaveJSON model: cycle c is [10c, 10c + 10), the clock rises at 10c + 5, the signals
// change at 10c; cols: name -> a value per cycle (a string of bits for 1-bit names, else an array of hex)
const BUS = (scope, cols, clk = 'clk', clk0 = '0') => {
  const n = Math.max(...Object.values(cols).map(c => c.length)), sig = [];
  const ck = [[0, clk0]]; for (let c = 0; c < n; c++) ck.push([10 * c + 5, '1'], [10 * c + 10, '0']);
  sig.push({ name: clk, path: `tb.${scope}.${clk}`, tv: ck });
  for (const [k, c] of Object.entries(cols)) {
    const one = typeof c === 'string', tv = [];
    for (let i = 0; i < c.length; i++) { const v = one ? c[i] : c[i].toString(16); if (!tv.length || tv[tv.length - 1][1] !== v) tv.push([10 * i, v]); }
    sig.push(Object.assign({ name: k, path: `tb.${scope}.${k}`, tv }, one ? {} : { width: 32 }));
  }
  const M = F.parse({ signal: [['tb', [scope, ...sig]]], time: { t0: 0, unit: 'ps' } });
  return WaveBus.findPorts(M, { busDetect: true, buses: null }).map(p => { const D = WaveBus.decode(p, null);
    return [p.proto, D.tx.map(x => [x.kind, x.label, x.lat, !!x.err])]; });
};
"""

UNITS = [   # (JavaScript expression, its JSON value); NaN / ±Infinity / undefined as strings
    # decode: every radix, masked to the width, exact fixed point, IEEE halves / singles / doubles
    ("D(8, 'ff', 'signed')", '-1'), ("D(8, '7f', 'signed')", '127'), ("D(8, '80', 'signed')", '-128'),
    ("D(8, '1ff', 'signed')", '-1'), ("D(64, 'ffffffffffffffff', 'signed')", '-1'), ("D(1, '1', 'signed')", '1'),
    ("D(8, 'ff', 'dec')", '255'), ("D(8, 'ff', 'unsigned')", '255'), ("D(72, 'ffffffffffffffffff', 'dec')", '4722366482869645213695'),
    ("D(4, 'a', 'bin')", '1010'), ("D(8, '5', 'bin')", '00000101'), ("D(8, '08', 'oct')", '0o10'), ("D(8, 'ab', 'hex')", '0xAB'),
    ("D(16, '4142', 'ascii')", '"AB"'), ("D(16, '0041', 'ascii')", '"A"'), ("D(8, '', 'ascii')", '""'), ("D(8, '07', 'ascii')", '"."'),
    ("D(8, 'x1', 'hex')", 'x1'), ("D(8, 'z', 'dec')", 'z'), ("D(3, '5')", '5'), ("D(8, 'ab')", '0xAB'), ("F.decode({ width: 8 })", '?'),
    ("D(8, 'ff', 'sq4')", '-0.0625'), ("D(8, '18', 'q4')", '1.5'), ("D(8, '80', 'sq4')", '-8'), ("D(8, '01', 'q8')", '0.00390625'),
    ("D(8, '10', 'q4')", '1'), ("D(60, 'f'.repeat(15), 'q4')", '72057594037927935.9375'), ("D(8, 'ff', 'q0')", '255'),
    ("D(16, '3c00', 'float')", '1'), ("D(16, '8000', 'float')", '-0'), ("D(16, '0000', 'float')", '0'), ("D(16, '0001', 'float')", '5.96e-08'),
    ("D(16, '7c00', 'float')", 'inf'), ("D(16, 'fc00', 'float')", '-inf'), ("D(16, '7e00', 'float')", 'nan'), ("D(16, '3555', 'float')", '0.3333'),
    ("D(32, '3fc00000', 'float')", '1.5'), ("D(32, '1ffffffff', 'float')", 'nan'), ("D(32, '00000001', 'float')", '1.401298e-45'),
    ("D(64, '3ff0000000000000', 'float')", '1'), ("D(64, '400921fb54442d18', 'float')", '3.14159265358979'),
    ("D(64, '10000000000000000', 'float')", '0'), ("D(12, 'abc', 'float')", '0xABC'),
    ("D(2, '1', null, { enum: { 1: 'RUN' } })", 'RUN'), ("D(2, '3', null, { enum: { 1: 'RUN' } })", '3'),
    # gfmt / toFloat
    ("I.gfmt(0.1 + 0.2)", '0.3'), ("I.gfmt(1e21)", '1e+21'), ("I.gfmt(-0)", '-0'), ("I.gfmt(NaN)", 'nan'), ("I.gfmt(-Infinity)", '-inf'),
    ("I.gfmt(1234567.8)", '1234568'), ("I.gfmt(12345678)", '1.234568e+07'), ("I.gfmt(0.00001234)", '1.234e-05'),
    ("I.gfmt(Math.PI, 15)", '3.14159265358979'), ("I.toFloat(0x3c00n, 16)", 1), ("I.toFloat(0x400n, 16)", 0.00006103515625),
    ("I.toFloat(1n, 16)", 5.960464477539063e-8), ("I.toFloat(0x40490fdbn, 32)", 3.1415927410125732), ("I.toFloat(0n, 8)", None),
    # bits and hex: GTKWave's z policy (a nibble all z: z, with an x or a partial z: x)
    ("I.hexOf('1010')", 'a'), ("I.hexOf('zzzz')", 'z'), ("I.hexOf('zz10')", 'x'), ("I.hexOf('x000')", 'x'), ("I.hexOf('110100')", '34'),
    ("I.hexOf('zzzz0001')", 'z1'), ("I.vcdHex('101', 8)", '05'), ("I.vcdHex('x', 8)", 'x'), ("I.vcdHex('z01', 8)", "'bzzzzzz01"),
    ("I.vcdHex('1', 1)", '1'), ("I.vcdHex('111111111', 8)", 'ff'), ("I.vcdHex('zzzz', 4)", 'z'),
    ("I.bitsOf({ k: '=', raw: 'a' }, 4)", '1010'), ("I.bitsOf({ k: '=', v: '0x1F' }, 8)", '00011111'), ("I.bitsOf({ k: '=', v: '12' }, 6)", '001100'),
    ("I.bitsOf({ k: 'z' }, 3)", 'zzz'), ("I.bitsOf(null, 2)", 'xx'), ("I.bitsOf({ k: '=', v: 'IDLE' }, 4)", 'xxxx'), ("I.bitsOf({ k: '=', raw: 'x1' }, 6)", 'xx0001'),
    # known bits among x / z: kept ("'b" and the bits in "tv"), hex only for the label
    ("I.vcdHex('10x1', 4)", "'b10x1"), ("I.vcdHex('x1', 8)", "'bxxxxxxx1"), ("I.vcdHex('1010xxxx', 8)", 'ax'), ("I.mixedBits('zzzz0001')", False),
    ("I.bitsVal('10x1')", {'k': '=', 'raw': 'x', 'bits': '10x1'}), ("I.bitsVal('xxxx')", {'k': 'x'}), ("I.bitsOf({ k: '=', raw: 'x', bits: '10x1' }, 4)", '10x1'),
    ("XZ.rows.find(r => r.name === 'b').tr.map(o => [o.t, o.k, o.raw || null, o.bits || null])", [[0, '=', 'xx', '1x0z1z0x'], [10000, 'z', None, None],
      [20000, '=', 'xx', 'xxxxxxx1'], [30000, '=', '05', None]]),
    ("I.fieldRow(XZ.rows.find(r => r.name === 'b'), { name: 'b0', msb: 0 }, 1, []).tr.map(o => o.k)", ['x', 'z', '1']),
    # a step from the cursor on a long run: the event 1 ps away is next (1e-9 · t jumped over it at 1 s)
    ("F.util.stepTo([1e12 + 1, 1e12 + 500, 1e12 + 2000], 1e12, 1)", 0), ("F.util.stepTo([1e12 - 2000, 1e12 - 1], 1e12, -1)", 1),
    ("F.util.stepTo([1e12, 1e12 + 1, 1e12 + 2], 1e12, 1)", 1), ("F.util.stepTo([1e12, 1e12 + 1, 1e12 + 2], 1e12 + 2, -1)", 1),
    ("F.util.stepTo([10, F.parseT('85.12us'), 9e7], F.parseT('85.12us'), 1)", 2), ("F.util.stepTo([10, F.parseT('85.12us'), 9e7], F.parseT('85.12us'), -1)", 0),
    ("I.edgeGlyph(XT, 1e12 + 1)", '↓'), ("I.findEdge(XT, 1e12, 1, 'any')", 1e12 + 1), ("I.findEdge(XT, 1e12 + 2, -1, 'any')", 1e12 + 1),
    ("VW(vcd('$var wire 1 ! a $end $scope module u $end $var wire 1 \" b $end $upscope $end', '#0 0! 0\" #1 1! 1\"'), { budget: 2 }).doc.meta",
     {'omitted': {'why': 'dumpBudget', 'paths': {'tb.u': ['b']}}}),
    ("F.decode({ width: 8 }, 'xz', 'bin')", 'xxxxzzzz'),
    # a second dump compared: values as values (bits, a real's number, a string's text), the stretches that differ in one pass
    ("(r => [\"1\", \"'b00000001\", '01'].map(v => I.cmpKey(r, F.parse({ signal: [{ name: 'v', width: 8, tv: [[0, v]] }] }).rows[0].tr[0])))({ width: 8 })",
     ['00000001', '00000001', '00000001']),
    ("[I.cmpKey({ width: 8 }, null) === I.cmpKey({ width: 8 }, { k: 'x' }), I.cmpKey({ kind: 'string' }, { k: 'x' }) === I.cmpKey({ kind: 'string' }, "
     "{ k: '=', v: 'x' })]", [True, False]),
    ("[['1.0', '1'], ['Hello', 'Hello']].map(([p, q], i) => I.cmpKey({ kind: ['real', 'string'][i] }, { k: '=', v: p }) === "
     "I.cmpKey({ kind: ['real', 'string'][i] }, { k: '=', v: q }))", [True, True]),
    ("(P => I.diffSpans(P([[0, '0'], [10, '1'], [20, '0'], [40, '1']]), P([[0, '0'], [12, '1'], [20, '0'], [35, '1'], [40, '0']]), 0, 50))"
     "(tv => F.parse({ signal: [{ name: 'a', tv }] }).rows[0])", [[10, 12], [35, 50]]),
    ("(P => I.diffSpans(P([[0, '0'], [10, '1']]), P([[0, '0'], [10, '1']]), 0, 20))(tv => F.parse({ signal: [{ name: 'a', tv }] }).rows[0])", []),
    # the clock cycles: cycle 0, the cycle at a time, the time of a cycle, the edges counted, the clock by a name, the band's marks
    ("[null, 20, 21, 35].map(z => I.cycZero([10, 20, 30], z))", [0, 1, 2, 3]), ("[5, 10, 25, 30].map(t => I.cycAt([10, 20, 30], 1, t))", [-2, -1, 0, 1]),
    ("[-1, -2, 1, 2].map(n => I.cycTime([10, 20, 30], 1, n))", [10, None, 30, None]),
    ("[[[0, '1'], [5, '0'], [10, '1']], [[0, '1']], [[0, '0'], [5, '1']]].map(tv => I.cycUps(F.parse({ signal: [{ name: 'c', tv }] }).rows[0]))",
     [[10], [], [5]]),
    ("I.cycUps(F.parse({ signal: [{ name: 'clk', wave: 'p..' }] }).rows[0]).length", 3),
    ("(M => [I.cycClock(M.rows, 'clk').full, I.cycClock(M.rows, null).full, I.cycClock(M.rows, 'nope')])(F.parse({ signal: [['tb', { name: 'clk', "
     "path: 'tb.clk', tv: [[0, '0'], [5, '1'], [10, '0'], [15, '1']] }], { name: 'clk', path: 'clk', tv: [[0, '0'], [7, '1']] }] }))", ['clk', 'tb.clk', None]),
    ("I.cycClock(F.parse({ signal: [{ name: 'clk', wave: 'p.' }] }).rows, null).name", 'clk'),
    ("I.cycMarks({ ups: [0, 1, 2, 3, 1000], iz: 0, from: 0, to: 1000, X: t => t, xR: 1100 }, t => 6 * t.length)",
     {'ticks': [0, 3, 1000], 'labels': [[0, '0'], [1000, '4']]}),
    ("I.cycMarks({ ups: [0, 10, 20, 30, 40, 50], iz: 2, from: 0, to: 50, X: t => 5 * t, xR: 120 }, t => 6 * t.length).labels",
     [[0, '-2'], [50, '-1'], [100, '0']]),
    ("I.cycMarks({ ups: [0, 100, 200], iz: 0, from: 99, to: 200, X: t => t - 99, xL: 0, xR: 300 }, t => 6 * t.length).labels", [[-99, '0'], [101, '2']]),
    ("(r => I.cycUps(I.fieldRow(r, { name: 'c', msb: 0 }, 1, [])))(F.parse({ signal: [{ name: 'reg', width: 2, tv: [[0, '1'], [5, '0'], [10, '1']] }] }).rows[0])",
     [10]),
    ("I.cycMarks({ ups: [0, 10, 20, 30, 40, 50], iz: 2, from: 0, to: 50, X: t => 2 * t, xR: 200 }, t => 6 * t.length).labels", [[40, '0']]),
    # "'b" values: transitions by their bits (x and z apart), any width, clock-sampled "raw", the samplers, the value search, enum colours
    ("MX.rows[0].tr.map(o => o.bits)", ['10x1', '10z1', '11x1']), ("I.fieldRow(MX.rows[0], { name: 'lo', msb: 1, lsb: 0 }, 1, []).tr.map(o => o.bits)",
     ['x1', 'z1', 'x1']),
    ("[['z01', 3], ['z0001', 5], ['zz0001', 6], ['z00000001', 9], ['1x0101', 6]].map(([b, w]) => RT(b, w))", ['z01', 'z0001', 'zz0001', 'z00000001', '1x0101']),
    ("I.bitsOf(F.parse({ signal: [{ name: 'v', width: 4, wave: '=', data: ['x'], raw: [\"'b10x1\"] }] }).rows[0].tr[0], 4)", '10x1'),
    ("SVA.tvSampler({ b: { width: 4, tv: [[0, \"'b10x1\"]] } }).before('b', 1)", '10x1'),
    ("[\"'b10x1\", \"4'b10x1\", \"'b10z1\", \"4'hx\"].map(q => MX.rows[0].tr.map(o => I.valueIs(MX.rows[0], o, I.parseWant(q), 'hex')))",
     [[True, False, False], [True, False, False], [False, True, False], [False, False, False]]),
    ("I.enumColor({ width: 4, radix: 'bin', enumColors: { '10x1': 'red' } }, MX.rows[0].tr[0], {})", 'red'),
    ("[\"8'hx5\", \"8'hxx\"].map(q => { const r = F.parse({ signal: [{ name: 'v', width: 8, wave: '=', data: ['x5'], raw: ['x5'] }] }).rows[0];\n"
     "  return I.valueIs(r, r.tr[0], I.parseWant(q)); })", [True, False]),
    ("[\"4'bx1\", \"'bx1\"].map(q => { const r = F.parse({ signal: [{ name: 'v', width: 8, tv: [[0, \"'b0000xxx1\"]] }] }).rows[0];\n"
     "  return I.valueIs(r, r.tr[0], I.parseWant(q)); })", [True, False]), ("SVA.expressions.tvValue('10x1', 4)", "'b10x1"),
    # fieldRow: in range, one bit, outside the vector (left out, never NaN)
    ("FR('d', { name: 'hi', msb: 7, lsb: 4 })", ['0', 'f', 'x', '0', 'f']), ("FR('d', { name: 'b0', msb: 0 })", ['0', '1', 'x', '1']),
    ("FR('d', { name: 'bad', msb: 11, lsb: 8 })", None), ("FR('d', { name: 'rev', msb: 2, lsb: 5 })", None), ("FR('d', { msb: 1, lsb: 0 })", None),
    # parseWant / valueIs / findEdge / edgeGlyph: negatives, enum labels, x / z on bits and buses
    ("PW('0x40')", ['64', False, '0x40']), ("PW(\"'h40\")", ['64', False, "'h40"]), ("PW(\"8'd64\")", ['64', False, "8'd64"]),
    ("PW('64')", ['64', False, '64']), ("PW('-3')", ['3', True, '-3']), ("PW(\"'b101\")", ['5', False, "'b101"]), ("PW('0o17')", ['15', False, '0o17']),
    ("PW('1_000')", ['1000', False, '1_000']), ("PW('IDLE')", [None, False, 'IDLE']), ("PW('\"go\"')", [None, False, 'go']), ("PW('ab')", [None, False, 'ab']),
    ("PW('  ')", None),
    ("VI('d', 1, '0xfd')", True), ("VI('d', 1, '-3')", True), ("VI('d', 1, '253')", True), ("VI('d', 2, 'x')", False), ("VI('st', 1, 'RUN')", True),
    ("VI('st', 1, '1')", True), ("VI('b', 1, '1')", True), ("VI('b', 0, '1')", False),
    ("FE('b', 0, 1, 'rise')", 10), ("FE('b', 10, 1, 'rise')", 30), ("FE('b', 50, -1, 'fall')", 40), ("FE('b', 0, 1, 'any')", 10),
    ("FE('b', 10, 1, 'xz')", 20), ("FE('d', 0, 1, 'value', '-3')", 10), ("FE('d', 10, 1, 'value', '-3')", 40), ("FE('d', 40, 1, 'value', '-3')", None),
    ("FE('st', 0, 1, 'value', 'RUN')", 10), ("FE('d', 25, -1, 'any')", 20), ("FE('d', -5, 1, 'any')", 10),
    ("I.edgeGlyph(R('b'), 10)", '↑'), ("I.edgeGlyph(R('b'), 40)", '↓'), ("I.edgeGlyph(R('b'), 15)", ''), ("I.edgeGlyph(R('d'), 30)", '= 0x03'),
    ("I.edgeGlyph(R('b'), 0)", ''), ("I.edgeGlyph(R('b'), 20)", 'x'),
    # the search: fuzzy letters in order, the scope before a dot, whole names, a regex
    ("FIND('s_pix_valid', 'pxvd')", [2, 4, 6, 10]), ("FIND('s_pix_valid', 'dvp')", None), ("FIND('s_pix_valid', 'tb.valid')", [6, 7, 8, 9, 10]), ("FIND('s_pix_valid', 'u.valid')", None),
    ("FIND('s_pix_valid', 'pix_valid', { full: true })", None), ("FIND('s_pix_valid', 's_pix_valid', { full: true })", list(range(11))),
    ("FIND('s_pix_valid', 'x', { re: /v.l/ })", [6, 7, 8]),
    # times: negatives, µs and us, plain numbers in the model's unit
    ("F.fmtTime(-1234567, 1000)", '-1235 ns'), ("F.fmtExact(-1500)", '-1.5 ns'), ("F.fmtExact(1234567)", '1.234567 µs'),
    ("F.parseT('-2ns')", -2000), ("F.parseT('1.5µs')", 1500000), ("F.parseT('1.5us')", 1500000), ("F.parseT('1.5 US')", 1500000),
    ("F.parseT('3')", 3), ("F.parseT('1e-3ns')", 1), ("F.parseT('ns')", 'undefined'), ("F.parseT('1.5 ks')", 'undefined'), ("F.parseT('')", 'undefined'),
    ("I.niceStep(3)", 5), ("I.niceStep(0.3)", 1), ("I.niceStep(12)", 20), ("I.niceStep(51)", 100), ("I.niceStep(7, true)", 10),
    ("I.cycMap({ t0: 5, cycle: 10 })(3)", 35), ("I.cycMap(null)(4)", 4), ("I.cycMap({ cycle: 10, skip: [[2, 5]] })(3)", 70),
    ("I.cycMap({ cycle: 10, skip: [[2, 5]] })(2.5)", 45),
    # gaps: the parts kept, a gap's ends on the rising edges (the cycle of a change and keep more kept), a gap's length
    ("I.idleCuts([50, 60, 1000], 0, 2000, 160, 20, Array.from({ length: 200 }, (_, i) => i * 10), 20)", [[0, 90], [980, 1030], [1980, 2000]]),
    ("I.idleCuts([50], 0, 1000, 200, 10)", [[0, 60], [990, 1000]]), ("I.idleCuts([50], 0, 100, 200, 10)", [[0, 100]]),
    ("I.idleCuts([], 0, 100, 50, 45, [], 20)", [[0, 100]]), ("I.idleCuts([], 0, 100, 50, 0)", [[0, 100]]),
    ("['rise', 'fall', 'any'].map(k => I.gapText(R('b'), 5, 45, k))", ['2↑', '1↓', '4↕']), ("I.gapText(R('d'), 5, 45, 'rise')", '4×'),
    ("I.gapText(R('b'), 41, 50, 'rise')", ''), ("[I.gapText(R('b'), 5, 45, 'edges'), I.gapText(R('d'), 5, 45, 'edges')]", ['2↑ 1↓', '4×']), ("I.gapRefs(UM.rows, 'tb.b, st, *pix*').map(r => r.name)", ['b', 'st', 's_pix_valid']),
    ("I.gapRefs(UM.rows, null).length", 0),
    ("[40000, 6400, 1000, 3e6, 7e11, 3e13].map(I.fmtFreq)", ['25 MHz', '156.3 MHz', '1 GHz', '333.3 kHz', '1.429 Hz', '0.033 Hz']),
    ("I.gapLen('16', 10)", 160), ("I.gapLen(2, 10)", 20), ("I.gapLen('2ns', 10)", 2000), ("I.gapLen('x', 10)", 'undefined'),
    ("(M => [M({}), M({ gaps: true }), M({ gaps: true, gapIdle: 12 }), M({ gaps: true, gapIdle: '600ps', gapKeep: 1 })])(o => +WaveSVG.toString({ signal: "
     "[{ name: 'clk', wave: 'p' + '.'.repeat(99) }, { name: 'd', wave: '=' + '.'.repeat(60) + '=', data: 'A B' }], time: { t0: 0, cycle: 10 } }, "
     "Object.assign({ cyclePx: 10 }, o)).match(/width=\"(\\d+)\"/)[1])", [1051, 167, 167, 479]),   # 1000 px of waves; 100 px kept and two gaps of 8 px; 420 px and one

    ("I.parseWave({ wave: 'p..' }, c => c).tr.map(o => [o.t, o.k])", [[0, '1'], [0.5, '0'], [1, '1'], [1.5, '0'], [2, '1'], [2.5, '0']]),
    ("I.parseWave({ wave: '0=.x', data: 'A' }, c => 10 * c).tr.map(o => [o.t, o.k, o.v ?? null])", [[0, '0', None], [10, '=', 'A'], [30, 'x', None]]),
    ("I.parseWave({ wave: '0|1' }, c => c).gaps", [1.5]),
    # analog values: from the raw value (enum codes, signed, fixed), a WaveDrom cell's hex or number, x / z a gap
    ("AV({ k: '=', raw: 'ff' }, 8)", 255), ("AV({ k: '=', raw: 'ff' }, 8, 'signed')", -1), ("AV({ k: '=', raw: '18' }, 8, 'q4')", 1.5),
    ("AV({ k: '=', raw: 'x1' }, 8)", 'NaN'), ("AV({ k: '1' }, 1)", 1), ("AV({ k: '=', raw: '1', v: 'RUN' }, 2, null, { enum: { 1: 'RUN' } })", 1),
    ("AV({ k: '=', v: '2.5' }, 64, null, { kind: 'real' })", 2.5), ("AV({ k: '=', v: '0x10' }, 8)", 16), ("AV({ k: '=', v: 'IDLE' }, 8)", 'NaN'),
    ("AV({ k: '=', v: '-12' }, 8)", -12),
    ("I.enumColor({ enumColors: { RUN: 3 } }, { k: '=', v: 'RUN' }, {})", 'c3'), ("I.enumColor({}, { k: '=', raw: '1', v: 'x' }, { enumColors: { 1: '#f00' } })", '#f00'),
    ("I.enumColor({}, { k: '0' }, { enumColors: { 0: 2 } })", None),
    # one rule for edges and steps
    ("F.util.isEdge('posedge', '0', '1')", True), ("F.util.isEdge('posedge', '0', 'x')", True), ("F.util.isEdge('posedge', 'x', '1')", True),
    ("F.util.isEdge('posedge', 'z', '1')", True), ("F.util.isEdge('posedge', 'x', '0')", False), ("F.util.isEdge('negedge', '1', 'z')", True),
    ("F.util.isEdge('edge', 'x', '0')", True), ("F.util.isEdge('posedge', null, '1')", False), ("F.util.isEdge('posedge', '1', '1')", False),
    ("F.util.stepTo([10, 20, 30], 20, 1)", 2), ("F.util.stepTo([10, 20, 30], 20, -1)", 0), ("F.util.stepTo([10, 20, 30], 30, 1)", 0),
    ("F.util.stepTo([10, 20, 30], 5, -1)", 2), ("F.util.stepTo([], 5, 1)", -1), ("F.util.stepTo([10, 20], 20 + 1e-12, -1)", 0),
    ("I.stripPfx('i_data', ['i_', 'o_'])", ['i_', 'data']), ("I.stripPfx('i_', ['i_'])", ['', 'i_']),
    # the page's VCD reader
    ("tvOf(VW(vcd('$var wire 1 ! clk $end $var wire 4 \" d [3:0] $end', '#0 0! b0 \" #5 1! b101 \" #10 0! bz1 \"')).doc, 'd')",
     [[0, '0'], [5000, '5'], [10000, "'bzzz1"]]),
    ("VW(vcd('$var wire 1 ! clk $end', '#0 0! #5 1!')).doc.time", {'t0': 0, 't1': 5000, 'cycle': 125, 'unit': 'ps'}),
    ("tvOf(VW(vcd('$var wire 1 ! s $end', '#0 0! $comment #99 $end #10 1!')).doc, 's')", [[0, '0'], [10000, '1']]),
    ("tvOf(VW(vcd('$var wire 4 ! v $end', '#0 bUUUU ! #10 b01HL !')).doc, 'v')", [[0, 'x'], [10000, '6']]),
    ("tvOf(VW(vcd('$var string 1 ! msg $end', '#0 sHello ! #10 sWorld !')).doc, 'msg')", [[0, 'Hello'], [10000, 'World']]),
    ("tvOf(VW(vcd('$var real 64 ! r $end', '#0 r1.5 ! #10 r2.25 !')).doc, 'r')", [[0, '1.5'], [10000, '2.25']]),
    ("tvOf(VW(vcd('$var wire 1 ! \\\\a.b $end', '#0 1!')).doc, '\\\\a.b')", [[0, '1']]),
    ("tvOf(VW(vcd('$var wire 1 ! m[1] $end $var wire 1 \" m[0] $end', '#0 1! 0\" #10 1\"')).doc, 'm')", [[0, '2'], [10000, '3']]),
    ("(() => { try { VW(vcd('$var wire 1 ! s $end', '#10 0! #5 1!')); return 'no error'; } catch (e) { return e.message.slice(0, 14); } })()", 'time goes back'),
    ("VW(vcd('$var wire 1 ! a $end $scope module u $end $var wire 1 \" b $end $upscope $end', '#0 0! 0\" #1 1! 1\"'), { budget: 2 }).shown", 1),
    # bus decoders on a model built in the page: per protocol, an x-valued valid, a clock starting at x, W before AW
    ("BUS('u_apb', { PSEL: '0111000', PENABLE: '0011000', PREADY: '0001000', PWRITE: '0111000', PADDR: [0, 0x10, 0x10, 0x10, 0, 0, 0], PWDATA: [0, 0x55, 0x55, 0x55, 0, 0, 0] }, 'PCLK')",
     [['apb', [['W', 'W 0x10 ← 0x55', 3, False]]]]),
    ("BUS('u_axis', { m_axis_tvalid: '01110', m_axis_tready: '00110', m_axis_tlast: '00010', m_axis_tdata: [0, 5, 5, 6, 0] }, 'aclk')",
     [['axis', [['P', '2 beats 0x5', 3, False]]]]),
    ("BUS('u_axis', { m_axis_tvalid: '0xx10', m_axis_tready: '01111', m_axis_tlast: '00010', m_axis_tdata: [0, 5, 5, 6, 0] }, 'aclk')",
     [['axis', [['P', '0x6', 1, False]]]]),
    ("BUS('u_axis', { m_axis_tvalid: '0110', m_axis_tready: '0110', m_axis_tlast: '0110', m_axis_tdata: [0, 5, 6, 0] }, 'aclk', 'x')",
     [['axis', [['P', '0x5', 1, False], ['P', '0x6', 1, False]]]]),
    ("BUS('u_axi', { s_axi_awvalid: '00010', s_axi_awready: '00010', s_axi_awaddr: [0, 0, 0, 0x40, 0], s_axi_wvalid: '01000', s_axi_wready: '01000', s_axi_wdata: [0, 0xa1, 0, 0, 0], s_axi_bvalid: '000001', s_axi_bready: '111111', s_axi_bresp: [0, 0, 0, 0, 0, 0], s_axi_arvalid: '000000', s_axi_arready: '000000', s_axi_araddr: [0, 0, 0, 0, 0, 0], s_axi_rvalid: '000000', s_axi_rready: '111111', s_axi_rdata: [0, 0, 0, 0, 0, 0], s_axi_rresp: [0, 0, 0, 0, 0, 0] }, 'aclk')",
     [['axi', [['W', 'W 0x40 ← 0xa1', 5, False]]]]),
    # the expressions of sva.js
    ("SVA.expressions.splitClock('@(posedge clk) a ##1 b')", {'clock': {'edge': 'posedge', 'signal': 'clk'}, 'body': 'a ##1 b'}),
    ("SVA.expressions.splitClock('a && b').clock", None), ("SVA.expressions.tvValue(5, 4)", '5'), ("SVA.expressions.tvValue('hz', 4)", 'z'),
    ("SVA.expressions.tvValue('zzzz0001', 8)", 'z1'), ("SVA.expressions.tvValue('zz01', 4)", "'bzz01"), ("I.gfmt(0.0001234)", '0.0001234'),
    ("SVA.stepSignals('a && $past(b) == 4\\'hc', new Set(['a', 'b']))", ['a', 'b']), ("SVA.propParts('a |-> b')", ['a', '|-> b']),
]


def units(browser, build):
    """The pure functions of the viewer (WaveFW.internal, unstable), the page's VCD reader, the bus decoders and the
    expressions of sva.js on a blank page: one case per line of UNITS, all in one evaluate."""
    page = browser.new_page()
    page.goto('about:blank')
    for f in ('wavefw.config.js', 'wavefw.js', 'sva.wasm.js', 'bus.js', 'sva.js'):
        page.add_script_tag(path=str(ROOT / 'wavefw' / f))
    page.add_script_tag(content=UNITS_SETUP)
    got = page.evaluate("""cases => cases.map(c => { try { return JSON.stringify((0, eval)(c), (k, x) => typeof x === 'number' && !isFinite(x) ? String(x) :
        typeof x === 'bigint' ? x + 'n' : x === undefined ? 'undefined' : x); } catch (e) { return JSON.stringify('ERR ' + e.message); } })""", [c for c, _ in UNITS])
    bad = [f'{c} = {g} (want {json.dumps(w, ensure_ascii=False)})' for (c, w), g in zip(UNITS, got) if json.loads(g) != w]
    check(not bad, f'{len(UNITS)} unit cases: decode, bits, fields, the value search, times, analog, edges, the VCD reader, the bus decoders, sva.js'
          + ('' if not bad else f' — {len(bad)} wrong:\n      ' + '\n      '.join(bad)))
    page.close()


def sva_hardening(browser, build):
    """Stage 6.1 on the example pages: evaluation cost, results kept, panel updates in place, the dump state, storage
    rules, prefixes at run time, the rows hook."""
    import json
    apb_all, apb, axi = (build / 'examples' / x for x in ('apb/apb_all.html', 'apb/apb.html', 'axi_lite/axi_lite.html'))
    if not need(apb_all, apb, axi, how='make examples'):
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
    check(t[0] < 1000 * SCALE and t[1] == 100, f'100 bindings of one instance evaluated in {t[0]:.0f} ms (< {1000 * SCALE:.0f}), all with their counts ({t[1]})')
    page.reload(); page.wait_for_load_state('networkidle')
    t = page.evaluate("""async () => { const t0 = performance.now(); await SVA.ready(); const p = SVA.panels()[0];
        return [performance.now() - t0, p.bindings.length, p.bindings.filter(b => b.results).length, p.bindings.filter(b => b.via).length]; }""")
    check(t[1] == 100 and t[2] == 100 and t[3] == 0 and t[0] < 500 * SCALE, f'after a reload the results come from this browser, not evaluated again ({t[2]} of {t[1]}, {t[0]:.0f} ms)')
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
    pfx.fill('x_'); settle(page); page.evaluate('SVA.ready()')
    st1 = page.evaluate("(() => { const b = SVA.panels()[0].bindings.find(b => b.assert === 'a_pfx'); return [b.state, b.results && b.results.assertions[0].stats.pass]; })()")
    check(st0 == 'cannot' and st1 == ['bound', 5], f'a new prefix in the sort field binds x_PSEL to PSEL ({st0} -> {st1})')
    pfx.fill('i_,o_,s_,m_')
    # the rows hook: a row of a plugin under u_regs folds, sorts and is found with it
    hook = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, g = Object.values(v.M.groups).find(g => g.name === 'u_regs');
        const src = v.M.rows.find(r => r.full === 'apb_tb.u_regs.PSEL'), row = { type: 'sig', name: 'probe_row', full: 'apb_tb.u_regs.probe_row', tr: src.tr, width: 1 };
        v.extraRows.push(x => (x === g ? [row] : [])); v.expandAll();
        const at = () => WaveFW.internal.peek(v).vis.indexOf(row), kids = () => WaveFW.internal.peek(v).vis.filter(r => r.anc.includes(g.id));
        const H0 = WaveFW.internal.peek(v).lay.H, pos = [at(), kids().indexOf(row), kids().length];
        const own = () => kids().filter(r => r.anc[r.anc.length - 1] === g.id && r.type === 'sig' && !r.cls && r !== row);
        v.setSort('desc'); const sorted = kids().indexOf(row) > Math.max(...own().map(r => kids().indexOf(r)));
        v.setSort('none'); v.find('probe'); const found = v.found.has(row); v.clearFind();
        WaveFW.internal.peek(v).collapsed.add(g.id); v.renderNames(); v.draw(); const folded = at() === -1;
        WaveFW.internal.peek(v).collapsed.delete(g.id); v.renderNames(); v.draw();
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
    if not need(apb, apb_all, how='make examples'):
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
        WaveFW.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveFW.internal.peek(v).vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
        return [b.assert, st.g.name, st.lane.drawn, o.kind === 'cover' ? o.attempts.length : o.stats.pass + o.stats.fail + o.stats.active + o.stats.disabled + o.stats.capped, WaveFW.internal.peek(v).vis.includes(st.lane), st.g.anc.length]; });""")
    bad = [x for x in g if x[2] != x[3] or not x[4] or x[5] != 0]
    check(len(g) == 14 and not bad and g[10][1] == '⚑ apb_demo_no_wait · 3 pass · 2 fail', f'apb: 14 assertion groups at the top of the view with their counts, bars = attempts listed {bad[:3]} {g[10][:2]}')
    # a click on the first failing bar: the attempt is selected, the cursor at its start, a red arrow with the reason
    hit = js("""const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait'), st = b.draw;
        WaveFW.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveFW.internal.peek(v).vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
        const o = WaveFW.internal.peek(v).lay.find(o => o.row === st.lane), h = st.lane.hits.find(h => h[4].r === 'fail'), r = v.canvas.getBoundingClientRect();
        return [r.left + (h[0] + h[1]) / 2, r.top + o.y - WaveFW.internal.peek(v).oy + (h[2] + h[3]) / 2, b.results.cycles[h[4].a.start]];""")
    page.mouse.click(hit[0], hit[1])
    sel = js("""const st = p.selA.b.draw; return [p.selA.b.assert, p.selA.i, v.cursor, (st.g.arrows || []).filter(a => a.col === 'sva-fail').map(a => [a.label, a.front]),
        v.extraPicks.size, document.querySelectorAll('.wv .names .row.hl').length, p.el.querySelector('li[data-a="apb_demo_no_wait"]').innerText];""")
    check(sel[:3] == ['apb_demo_no_wait', 1, hit[2]] and ['expected PREADY', True] in sel[3] and sel[4] >= 5 and sel[5] >= 5 and 'attempt 2: fail' in sel[6],
          f'click on a failing bar: the attempt selected, the cursor at its start, a red arrow "expected PREADY", the bound signals highlighted, the panel line says so {sel[:6]}')
    # the selected attempt on the signals its steps read (the bound rows and their copies), start / end flags in the band
    flow = js("""const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait'), g = b.draw.g, src = b.res ? b.res.map : null;
        const out = [g.flow.filter(f => f.flag).map(f => f.flag), g.flow.filter(f => f.on === 'src').map(f => [f.s, f.fail])];
        const w = p.bindings.find(b => b.assert === 'apb_read_waits'); p.select(w, 0); v.draw();
        out.push(w.draw.g.flow.filter(f => f.flag).map(f => f.flag), w.draw.g.flow.filter(f => f.on === 'src').map(f => f.s), w.draw.g.flow.filter(f => f.on === 'cp').map(f => f.s));
        const row = n => WaveFW.internal.peek(v).lay.find(o => o.row === w.res.map[n]), y = n => row(n).y + row(n).h / 2;
        out.push(['PSEL', 'PREADY'].map(n => w.draw.g.flow.some(f => f.on === 'src' && Math.abs(f.y - y(n)) < 0.5)));
        out.push(w.draw.lane.marks.map(k => [k[0], k[3], k[4]]));
        p.select(b, 1); v.draw(); return out;""")
    check(flow[0] == ['▶ ✕ fail'] and flow[1] == [[1, False], [1, False], [2, True]] and flow[2] == ['▶ start', '✓ pass']
          and flow[3] == [1, 1, 1, 1, 2, 2, 3] and flow[4] == flow[3] and flow[5] == [True, True] and ['pass', None, True] in flow[6],
          f'the selected attempt on its signals: step 1 on PSEL and PENABLE, the ✕ on PREADY, ▶ ✕ fail in one cycle; apb_read_waits 1 (4 signals), 2 2 3 on PREADY, ▶ start … ✓ pass {flow}')
    # the list of assertions is a table: a header, the same columns on every line, two lines per assertion (name and
    # instance over kind and property, results)
    tab = js("""const ol = p.el.querySelector('ol.asv'), hd = [...ol.querySelectorAll(':scope > li.hd > span')].map(e => e.textContent);
        const ls = [...ol.querySelectorAll(':scope > li[data-a]')].slice(0, 4), q = (li, sel) => li.querySelector(sel).getBoundingClientRect();
        const has = sel => ls.filter(li => li.querySelector(sel)), x = sel => has(sel).map(li => Math.round(q(li, sel).left));
        const below = (a, b) => has(b).length > 0 && has(b).every(li => q(li, b).top >= q(li, a).bottom - 1);
        return [hd, ls.map(li => li.querySelector('.an').lastChild.textContent), ['.nm', '.pr', '.b1 .bp', '.b1 .bs', '.ab'].map(x),
            [below('.nm', '.pr'), below('.b1 .bp', '.b1 .bs'), below('.ab', '.b1 .bb')]];""")
    check(tab[0] == ['#', 'Assertion · property', 'Bound to · results', ''] and tab[1] == ['1', '2', '3', '4']
          and all(len(set(c)) == 1 for c in tab[2]) and tab[2][0] == tab[2][1] and tab[2][2] == tab[2][3] and all(tab[3]),
          f'the assertions are a table: a header, numbered lines, name over property, instance over results, buttons in columns {tab}')
    at = page.locator('.wv').first.locator('.sva li[data-a="apb_read_waits"] code.at')
    sel0 = js('return [p.selA.b.assert, p.selA.i];')
    at.scroll_into_view_if_needed(); bb = at.bounding_box()
    page.mouse.move(bb['x'] + 2, bb['y'] + 4); page.mouse.down(); page.mouse.move(bb['x'] + bb['width'] - 2, bb['y'] + bb['height'] - 4, steps=6); page.mouse.up()
    pc = [page.evaluate('getSelection().toString()'), at.get_attribute('title').split('\n')[0], at.locator('.pp').count(), bb['height'] > 20, js('return [p.selA.b.assert, p.selA.i];') == sel0]
    page.evaluate('getSelection().removeAllRanges()')
    check(pc[0] == pc[1] and pc[2] >= 2 and pc[3] and pc[4],
          f'Property: wraps at its operators, the mouse selects it in the draggable line and it copies as the one-line text (no jump to the waves) {pc}')
    # Why: the selected attempt taken apart, a column per cycle, the step that failed in red
    why = js("""const w = p.el.querySelector('.svw'), t = w.querySelector('table'); if (!t) return [w.innerText];
        return [[...t.querySelectorAll('thead button')].map(b => b.textContent), [...t.querySelectorAll('tbody tr')].map(r => r.querySelector('th').textContent),
          [...t.querySelectorAll('td.miss')].map(c => c.textContent), t.querySelectorAll('td.hit').length];""")
    check(why[0] == ['10'] and why[1][:4] == ['1. PSEL && PENABLE ante', 'PSEL', 'PENABLE', '2. PREADY cons'] and why[2] == ['0'] and why[3] == 1,
          f'Why: the failing attempt\'s booleans and their parts at cycle 10, the antecedent matched, PREADY red {why}')
    w2 = js("""p.select(p.bindings.find(b => b.assert === 'apb_read_waits'), 0);
        return new Promise(r => setTimeout(() => { const t = p.el.querySelector('.svw table'); const bs = [...t.querySelectorAll('thead button')];
          bs[2].click(); r([bs.map(b => b.textContent), t.querySelectorAll('td.hit').length, t.querySelectorAll('td.miss').length, v.cursor, +bs[2].dataset.t]); }, 100));""")
    check(len(w2[0]) == 4 and w2[1] == 4 and w2[2] == 0 and w2[3] == w2[4], f'Why of a passing 4-cycle attempt: 4 columns, a ring where each step matched, a cycle header moves the cursor {w2}')
    js("p.select(p.bindings.find(b => b.assert === 'apb_demo_no_wait'), 1);")
    # ]f / [f: next / previous failure (round the end); the go-to buttons; Esc
    v = page.locator('.wv').first
    v.locator('canvas').focus()
    seq = []
    for k in (']f', ']f', '[f'):
        page.keyboard.press(k[0]); page.keyboard.press(k[1]); seq.append(js('return [p.selA.i, v.cursor];'))
    btns = v.locator('.bar .svj button.fail')
    check([x[0] for x in seq] == [2, 1, 2] and seq[0][1] == 115000 and btns.count() == 2, f']f / [f step through the two failures, round the end {seq}; {btns.count()} failure buttons in go to')
    page.keyboard.press('Escape')
    esc = js("return [p.selA, v.extraPicks.size, p.el.querySelector('li[data-a=\"apb_demo_no_wait\"]').innerText.includes('attempt'), p.el.querySelector('.svw').hidden];")
    btns.nth(1).click()
    check(esc == [None, 0, False, True] and js('return p.selA && p.selA.i;') == 2, f'Esc clears the selection and Why {esc}; the second failure button selects that attempt')
    # tooltips: a circle names its step, the ✕ its reason once; a bar gives start → end
    tips = js("""const st = p.bindings.find(b => b.assert === 'apb_demo_no_wait').draw;
        WaveFW.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveFW.internal.peek(v).vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'start' }); v.draw();
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
    v.locator('canvas').focus(); page.keyboard.press(']'); page.keyboard.press('a'); nav.append(js(geo)[0]); page.keyboard.press('['); page.keyboard.press('a'); nav.append(js(geo)[0])
    order = js("return p.drawn().map(b => b.assert);")
    k = order.index('apb_setup_then_access')
    check(nav[0][:3] == ['apb_demo_no_wait', 1, 'fail'] and nav[1][:3] == ['apb_demo_no_wait', 2, 'fail'] and nav[2][2] == 'pass'
          and all(x[3] == span0 and abs(x[4] - 0.5) < 0.1 and x[5] and x[6] for x in nav[:3]) and nav[3] == order[(k + 1) % len(order)] and nav[4] == 'apb_setup_then_access',
          f'a click on an assertion: its first failure at the same zoom ({span0} ps), the attempt in the middle {nav[0][4]}; again: the next failure; a passing one: a pass; ]a / [a: the next / previous assertion {nav}')
    page.keyboard.press('Escape')
    # sorting, find, Expand / Collapse keep the groups where they are
    js("v.setSort('desc');")
    pos = js("""const top = WaveFW.internal.peek(v).vis.filter(r => r.type === 'sig' && !r.anc.length && !r.cls), gs = WaveFW.internal.peek(v).vis.filter(r => r.sva);
        return [Math.max(...top.map(r => WaveFW.internal.peek(v).vis.indexOf(r))) < Math.min(...gs.map(r => WaveFW.internal.peek(v).vis.indexOf(r))), gs.length];""")
    js("v.setSort('none'); v.find('demo_no_wait');")
    found = js("return [...v.found.keys()].filter(r => r.sva).map(r => r.sva);")
    js("v.find('PREADY');")
    found += js("return [...v.found.keys()].filter(r => r.cls === 'sva-step').map(r => r.name);")
    js('v.clearFind(); v.collapseAll();')
    col = js("return [WaveFW.internal.peek(v).vis.filter(r => r.sva).length, WaveFW.internal.peek(v).vis.filter(r => r.cls === 'sva-lane').length];")
    js('v.expandAll();')
    exp = js("return WaveFW.internal.peek(v).vis.filter(r => r.cls === 'sva-lane').length;")
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
        const b = p.bindings[p.bindings.length - 1]; WaveFW.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveFW.internal.peek(v).vis.indexOf(b.draw.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
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
        p.select(b, 0); v.draw(); const open = st.g.flow.filter(f => f.flag).map(f => f.flag);
        p.unselect(); p.bindings.pop(); p.redraw(); return [val, arrows.filter(l => l.includes('trace cut')), st.g.full, st.g.name, open];""")
    check(inj[0].startswith('active') and len(inj[1]) == 1 and '… 21T (trace cut)' in inj[1] and inj[2] == 'probe' and inj[3] == '⚑ probe · 71 pass · 0 fail · 1 active'
          and inj[4] == ['▶ start', '… not ended'],
          f'a long active attempt behind 70 later ones shows in the value column, its end flag "… not ended"; a truncated trace draws its cut; a top-scope name without "@" {inj}')
    # the whole hierarchy: bound to the slave, the group under u_regs, after its signals, also when sorted and folded
    page.goto(apb_all.as_uri()); page.wait_for_load_state('networkidle')
    page.evaluate("async () => { localStorage.clear(); await SVA.loadFiles([{ name: 'apb.sv', text: %s }]); await SVA.ready(); SVA.panels()[0].bind('apb_setup_access', 'apb_tb.u_regs'); await SVA.ready(); }" % json.dumps((ROOT / 'tests' / 'sva' / 'apb.sv').read_text()))
    u = js("""const g = Object.values(v.M.groups).find(g => g.name === 'u_regs'), b = p.bindings[0], st = b.draw;
        v.expandAll(); const kids = () => WaveFW.internal.peek(v).vis.filter(r => r.anc.includes(g.id)), own = () => kids().filter(r => r.anc[r.anc.length - 1] === g.id && r.type === 'sig' && !r.cls);
        const after = () => kids().indexOf(st.g) > Math.max(...own().map(r => kids().indexOf(r)));
        const a = [st.g.anc[st.g.anc.length - 1] === g.id, after(), st.g.name]; v.setSort('asc'); a.push(after()); v.setSort('none');
        WaveFW.internal.peek(v).collapsed.add(g.id); v.renderNames(); a.push(WaveFW.internal.peek(v).vis.includes(st.g)); WaveFW.internal.peek(v).collapsed.delete(g.id); v.renderNames(); v.draw(); return a;""")
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


def sva_edit(browser, build):
    """✎ and ⟳ on the APB page: an assertion edited in the page is parsed and evaluated again (only its bindings), kept
    over a reload, marked, reverted; a text that does not parse changes nothing; ⟳ reads its file again (a picked file's
    handle, faked here: the browser's picker cannot be driven), Watch reads it when it changes."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('assertions: edit in the page, read from the disk')
    ctx = browser.new_context(viewport={'width': 1360, 'height': 1400})
    page = ctx.new_page()
    errs = []; page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    v = page.locator('.wv').first
    st = lambda lab: page.evaluate(f"SVA.panels()[0].bindings.filter(b => b.assert === '{lab}').map(b => b.results ? [b.results.assertions[0].stats.pass, b.results.assertions[0].stats.fail] : null)")
    others = page.evaluate("(window.__keep = SVA.panels()[0].bindings.filter(b => b.assert !== 'apb_demo_no_wait').map(b => b.results), window.__keep.length)")
    li = v.locator('.sva li[data-a="apb_demo_no_wait"]')
    li.locator('button[data-sv=edit]').click()
    ta = li.locator('textarea.src'); text = ta.input_value()
    check(text.strip().startswith('apb_demo_no_wait: assert property (`ACCESS |-> PREADY)') and text.strip().endswith('else $error("demo: a wait state");') and st('apb_demo_no_wait') == [[3, 2]],
          f'✎ opens the statement with its action block {text.strip()[:60]!r}… (now {st("apb_demo_no_wait")})')
    ta.fill(text.replace('|-> PREADY)', '|-> ##[0:2] PREADY)')); ta.press('Control+Enter')
    page.wait_for_function("(() => { const b = SVA.panels()[0].bindings.find(b => b.assert === 'apb_demo_no_wait'); return b.results && !b.running; })()"); page.evaluate('SVA.ready()')
    same = page.evaluate("SVA.panels()[0].bindings.filter(b => b.assert !== 'apb_demo_no_wait').every((b, i) => b.results === window.__keep[i])")
    marked = [e.get_attribute('data-a') for e in v.locator('.sva li[data-a]').all() if e.locator('.ed').count()]
    steps = page.evaluate("WaveFW.internal.peek(SVA.panels()[0].v).vis.filter(r => r.cls === 'sva-step').map(r => r.name)")
    check(st('apb_demo_no_wait') == [[5, 0]] and same and marked == ['apb_demo_no_wait'] and '2. ##[0:2] PREADY' in steps and li.locator('textarea.src').count() == 0,
          f'ctrl+Enter applies: only its binding evaluated again ({st("apb_demo_no_wait")}, the other {others} kept), only its line marked {marked}, its steps on the waves {[s for s in steps if "PREADY" in s][:2]}')
    page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    page.wait_for_function("(() => { const b = SVA.panels()[0].bindings.find(b => b.assert === 'apb_demo_no_wait'); return b.results && !b.running; })()")
    check(st('apb_demo_no_wait') == [[5, 0]] and page.evaluate("SVA.fileList().filter(f => f.origin === 'local').map(f => f.name)") == ['apb.sva'],
          f'after a reload the edit is kept in this browser and evaluated, not the results built into the page ({st("apb_demo_no_wait")})')
    li.locator('button[data-sv=edit]').click(); ta = li.locator('textarea.src'); good = ta.input_value()
    ta.fill(good.replace('##[0:2] PREADY)', '##[0:2] PREADY')); li.locator('button[data-sv=apply]').click()
    page.wait_for_function("document.querySelector('.wv .sva li[data-a=\"apb_demo_no_wait\"] .em') && document.querySelector('.wv .sva li[data-a=\"apb_demo_no_wait\"] .em').textContent")
    em = li.locator('.em').inner_text()
    check('apb.sva:' in em and li.locator('textarea.src').input_value().endswith('PREADY\n        else $error("demo: a wait state");') and st('apb_demo_no_wait') == [[5, 0]],
          f'a text that does not parse is not applied: the editor keeps it and says why ({em[:70]!r}), the assertion stays as it was')
    li.locator('button[data-sv=revert]').click()
    page.wait_for_function("SVA.fileList().every(f => f.origin !== 'local')")
    page.wait_for_function("(() => { const b = SVA.panels()[0].bindings.find(b => b.assert === 'apb_demo_no_wait'); return b.results && !b.running; })()"); page.evaluate('SVA.ready()')
    check(st('apb_demo_no_wait') == [[3, 2]] and v.locator('.sva .ed').count() == 0, f'Revert: the file of the page and its counts are back ({st("apb_demo_no_wait")})')
    # ⟳ and Watch with a picked file: the browser's picker returns a handle; here a fake one over a text the test changes
    page.evaluate("""(() => { const f = SVA.statement('apb_demo_no_wait');
        window.__disk = { text: null, t: 1, picks: 0 };
        window.showOpenFilePicker = async () => { window.__disk.picks++; return [{ kind: 'file', name: 'apb.sva', queryPermission: async () => 'granted',
          getFile: async () => new File([window.__disk.text], 'apb.sva', { lastModified: window.__disk.t }) }]; };
        SVA.watchMs = 100; })()""")
    disk = (ROOT / 'examples' / 'apb' / 'apb.sva').read_text()
    page.evaluate(f"window.__disk.text = {json.dumps(disk.replace('|-> PREADY)', '|-> ##[0:1] PREADY)'))}")
    li.locator('button[data-sv=reload]').click()
    page.wait_for_function("SVA.fileList().some(f => f.origin === 'local')")
    page.wait_for_function("(() => { const b = SVA.panels()[0].bindings.find(b => b.assert === 'apb_demo_no_wait'); return b.results && !b.running; })()"); page.evaluate('SVA.ready()')
    r1 = st('apb_demo_no_wait'); mark = li.locator('.ed').inner_text() if li.locator('.ed').count() else ''
    check(r1 != [[3, 2]] and page.evaluate('window.__disk.picks') == 1 and mark == 'changed', f'⟳: the file picked once is read and evaluated ({r1}), its changed assertion marked {mark!r}')
    v.locator('.sva button[data-sv=watch]').click()
    page.evaluate(f"(window.__disk.text = {json.dumps(disk)}, window.__disk.t = 2)")
    page.wait_for_function("(() => { const b = SVA.panels()[0].bindings.find(b => b.assert === 'apb_demo_no_wait'); return b.results && !b.running && b.results.assertions[0].stats.fail === 2; })()", timeout=10000)
    page.evaluate('SVA.ready()'); toast = v.locator('.bar .toast').inner_text()
    check(st('apb_demo_no_wait') == [[3, 2]] and page.evaluate('window.__disk.picks') == 1 and 'changed on the disk' in toast,
          f'Watch: a change of the file on the disk is read and evaluated without asking again ({st("apb_demo_no_wait")}, {toast!r})')
    page.evaluate('SVA.watch(false)')
    check(not errs, 'no page errors' + (': ' + ' | '.join(errs[:2]) if errs else ''))
    ctx.close()


def sva_report(browser, build):
    """Stage 8 in the APB page: totals and table against sva eval's report, the count filter, the failure list, exports."""
    import json, subprocess
    apb, sva = build / 'examples' / 'apb' / 'apb.html', build / 'sva-target' / 'release' / 'sva'
    if not need(apb, how='make examples') or not need(sva, how='make sva-build'):
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
        WaveFW.internal.peek(p.v).namesEl.querySelector(`.row[data-r="${WaveFW.internal.peek(p.v).vis.indexOf(b.draw.lane)}"]`).scrollIntoView({ block: 'center' }); p.v.draw();
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
    if not need(sva, how='make sva-build') or not need(apb, apb_all, how='make examples'):
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
    except Exception as e:   # noqa: BLE001 — svabuild.WaveError (tools/common.py), a one-line message
        fb = str(e)
    check(m.returncode != 0 and 'no file matches SVA=nonexist.sva' in m.stderr and 'no sva binary at /nonexist/sva' in fb, f'make html SVA=nonexist.sva stops ({m.stderr.strip()[-60:]}); --sva-bin /nonexist/sva: {fb}')


def sva_page(page, ex):
    page.evaluate('SVA.ready()')
    p = page.evaluate("""SVA.panels().map(p => ({ key: p.v.root.dataset.wave, n: p.el.querySelectorAll('ol.asv > li[data-a]').length, tv: p.v.M.rows.some(r => r.src && r.src.tv),
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
    if not need(sva, how='make sva-build'):
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
    if not need(path, how='make examples'):
        return
    print('assertions: binding on ' + path.name)
    ctx = browser.new_context(viewport={'width': 1360, 'height': 2700})   # the panel and the module rows on one screen (drag)
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(path.as_uri()); page.wait_for_load_state('networkidle')
    v = page.locator('.wv').first
    check(v.locator('.sva').is_hidden() and v.locator('button[data-sv=load]').count() == 1, 'apb_all: no assertion loaded: the panel is hidden, Load file… is in the bar')
    v.locator('input.svfile').set_input_files([str(ROOT / 'tests' / 'sva' / 'apb.sv'), str(ROOT / 'tests' / 'sva' / 'third_party' / 'saravana_apb_ahb' / 'apb_assertions.sv')])
    page.wait_for_function("SVA.panels()[0].el.querySelectorAll('ol.asv > li[data-a]').length > 0")
    page.evaluate('SVA.ready()')
    n = v.locator('.sva ol.asv > li[data-a]').count()
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
    # the instance path in the Bound to column: wraps after its dots in a narrow column, copies as one line
    sp = v.locator('.sva li[data-a="apb_setup_access"] .b1 b.sp')
    cp = sp.evaluate("""e => { const h1 = e.getBoundingClientRect().height; e.style.display = 'inline-block'; e.style.width = '8ch'; const h2 = e.getBoundingClientRect().height;
        e.style.display = e.style.width = ''; return [e.querySelectorAll('wbr').length, h2 > h1 * 1.5, getComputedStyle(e).userSelect]; }""")
    sp.scroll_into_view_if_needed(); bb = sp.bounding_box(); page.mouse.move(bb['x'] + 1, bb['y'] + bb['height'] / 2); page.mouse.down()
    page.mouse.move(bb['x'] + bb['width'] - 1, bb['y'] + bb['height'] / 2, steps=5); page.mouse.up()
    cp += [page.evaluate('getSelection().toString()'), page.evaluate('SVA.panels()[0].selA')]
    page.evaluate('getSelection().removeAllRanges()')
    check(cp == [1, True, 'text', 'apb_tb.u_regs', None], f'Bound to: the instance path wraps after its dots in a narrow column, the mouse selects it in the draggable line and it copies as one line (no jump to the waves) {cp}')
    native = None
    if need(sva, how='make sva-build'):
        out = build / 'sva' / 'apb_regs.smoke.json'
        subprocess.run([str(sva), 'eval', '--waves', str(build / 'examples' / 'apb' / 'apb.vcd'), '--scope', 'apb_tb.u_regs', '--resolve', 'scope', '--sva', str(ROOT / 'tests' / 'sva' / 'apb.sv'),
                        '--assert', 'apb_setup_access', '--out', str(out)], capture_output=True)
        native = json.loads(out.read_text())['assertions'][0]['stats']
    check(st[:1] == [['apb_setup_access', 'apb_tb.u_regs', 'bound', 'page', native or st[0][4]]] and 'apb_tb.u_regs' in li.inner_text() and '3 pass' in li.inner_text(),
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
    settle(page)
    li2 = v.locator('.sva li[data-a="apb_enable_sel"]')
    li2.drag_to(v.locator('.names .row.grp', has_text='u_master'))
    page.evaluate('SVA.ready()')
    check('apb_tb.u_master' in li2.inner_text() and '5 pass' in li2.inner_text(), f'drop on the u_master row binds it there ({li2.inner_text()[:160]!r})')
    li2.drag_to(v.locator('.names .row.grp', has_text='u_count'))
    settle(page)
    toast = v.locator('.bar .toast').inner_text()
    check('cannot bind apb_enable_sel to apb_tb.u_count: PENABLE, PSEL' in toast and page.evaluate("SVA.panels()[0].bindings.length") == 2, f'drop on u_count: not bound ({toast})')
    li2.drag_to(v.locator('.names .row:not(.grp)', has_text='PREADY').nth(2))   # a signal row: its module (u_regs)
    page.evaluate('SVA.ready()')
    check(li2.locator('ul.bnd > li').count() == 2 and 'apb_tb.u_regs' in li2.inner_text(), 'drop on a signal row binds to its module; two instances: one line each')
    li2.locator('ul.bnd > li', has_text='u_master').locator('button[data-sv=unbind]').click()
    check(li2.locator('ul.bnd > li').count() == 0 and 'apb_tb.u_regs' in li2.inner_text(), 'Unbind removes that binding only')
    v.locator('.sva button[data-sv=json]').click()
    js = v.locator('.sva textarea.json').input_value()
    binds = json.loads('{' + js + '}')['bind']
    check(binds == [{'assert': 'apb_setup_access', 'scope': 'apb_tb.u_regs'}, {'assert': 'apb_enable_sel', 'scope': 'apb_tb.u_regs'}], f'JSON: the bindings for the config {binds}')
    page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    st = page.evaluate("SVA.panels()[0].bindings.map(b => [b.assert, b.scope, b.state, b.results && b.results.assertions[0].stats.pass])")
    check(st == [['apb_setup_access', 'apb_tb.u_regs', 'bound', 3], ['apb_enable_sel', 'apb_tb.u_regs', 'bound', 5]] and v.locator('.sva ol.asv > li[data-a]').count() == 29,
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
    if need(wasm, how='make sva-build'):
        check(raw == wasm.read_bytes(), 'wavefw/sva.wasm.js is the module of the current build (make sva-build writes it)')


# sva eval over the example dumps (make sva-build, make examples): (pass, fail) per assertion where they are not
# (n, 0); every testbench has one deliberately wrong assertion
SVA_EXAMPLES = {
    'apb': (['--scope', 'apb_tb', '--sva', 'examples/apb/apb_tb.sv', '--sva', 'examples/apb/apb.sva'], 14, {'apb_demo_no_wait': (3, 2)}),
    'axi_lite': (['--scope', 'axi_lite_tb.u_slave', '--sva', 'examples/axi_lite/axi_lite.sva'], 19, {'axi_demo_aw_at_once': (0, 1)}),
    'fsm': (['--scope', 'fsm_tb.u_rx', '--sva', 'examples/fsm/uart_pkg.sv', '--sva', 'examples/fsm/fsm.sva'], 15, {'fsm_demo_short_data': (0, 2)}),
}


def sva_third_party(build):
    """tests/sva/third_party/units.json: every evaluation over an example dump, no failure but the listed ones."""
    import json, subprocess
    sva = build / 'sva-target' / 'release' / 'sva'
    if not need(sva, how='make sva-build'):
        return
    tp = ROOT / 'tests' / 'sva' / 'third_party'
    for u in json.loads((tp / 'units.json').read_text())['units']:
        for e in u.get('eval', []):
            dump = build / 'examples' / e['example'] / f'{e["example"]}.fst'
            if not need(dump, how='make examples'):
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
    if not need(sva, how='make sva-build'):
        return
    print('sva eval')
    for ex, (args, n, fails_) in SVA_EXAMPLES.items():
        dump = build / 'examples' / ex / f'{ex}.fst'
        if not need(dump, how='make examples'):
            continue
        out = build / 'sva' / f'{ex}.smoke.json'
        out.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([str(sva), 'eval', '--waves', str(dump), *args, '--out', str(out)], cwd=ROOT, capture_output=True, text=True)
        doc = json.loads(out.read_text()) if out.exists() else {'assertions': []}
        got = {a['name']: (a['stats']['pass'], a['stats']['fail']) for a in doc['assertions'] if a['kind'] != 'cover' and a['stats']['fail']}
        traces = all(a['trace'] for o in doc['assertions'] for a in o['attempts'] if a['result'] == 'fail')
        check(r.returncode == 1 and len(doc['assertions']) == n and got == fails_ and traces,
              f'sva eval {ex}: {len(doc["assertions"])} assertions, only the deliberate failures {got} (with traces), exit {r.returncode}')


def conformance(page):
    """tests/conformance.html: per case the same lanes and the same texts (names, bus labels, tick / tock, edge labels)
    as stock WaveDrom 3.5.0 (tests/vendor/) draws."""
    got = page.evaluate("""[...document.querySelectorAll('.case')].map((c, i) => { const st = c.querySelector('.stock svg'), mine = c.querySelector('.mine svg'),
        tx = s => s ? [...s.querySelectorAll('text')].map(t => t.textContent.trim()).filter(Boolean).sort() : [];
        return [c.querySelector('h2').firstChild.textContent.trim(), st ? st.querySelectorAll('[id^=wavelane_draw_]').length : -1,
                WaveFW.parse(CASES[i][1]).rows.filter(r => r.type !== 'group').length, tx(st), tx(mine)]; })""")
    check(len(got) == 11, f'conformance: {len(got)} cases')
    for title, lanes, rows, stock, mine in got:
        diff = '' if stock == mine else f': only in stock {sorted(set(stock) - set(mine))}, only in wavefw {sorted(set(mine) - set(stock))}, {len(stock)} / {len(mine)} texts'
        check(lanes == rows and stock == mine, f'conformance "{title}": {rows} lanes ({lanes} in stock WaveDrom), the same texts{diff}')


def synth_vcd(path):
    """A VCD for the hierarchy checks: tb_top (12 signals) over a binary tree of 255 scopes, 8 levels deep, 8 signals
    each (16 in dut_i); every scope's clk is the top clock's net (one id code: "same" in the page), values from a fixed LCG."""
    levels = ['dut_i', 'dev{}_i', 'core{}_i', 'pipe{}_i', 'stage{}_i', 'unit{}_i', 'cell{}_i', 'leaf{}_i']
    sigs, out = [], ['$date synthetic $end', '$timescale 1ns $end', '$scope module tb_top $end', '$var wire 1 ! clk $end']
    code = lambda n: ''.join(chr(34 + (n // 93 ** k) % 93) for k in range(3))

    def var(w, name):
        c = code(len(sigs))
        sigs.append((c, w))
        out.append(f'$var wire {w} {c} {name} $end')

    def scope(depth, k):
        out.append(f'$scope module {levels[depth].format(k)} $end')
        out.append('$var wire 1 ! clk $end')
        for name, w in (('s_pix_valid', 1), ('fifo_s_val', 1), ('data_q', 8), ('state', 3), ('cnt', 4), ('ready', 1), ('err', 1)):
            var(w, name)
        for r in range(8 if depth == 0 else 0):   # the top instance: enough rows of its own to highlight while folded
            var(16, f'cfg_reg{r}')
        if depth + 1 < len(levels):
            for c in (0, 1):
                scope(depth + 1, 2 * k + c)
        out.append('$upscope $end')

    for k in range(11):
        var(8 if k % 3 == 0 else 1, f'tb_sig{k}')
    scope(0, 0)
    out += ['$upscope $end', '$enddefinitions $end']
    x = 12345
    for t in range(0, 400, 5):
        out += [f'#{t}', f'{(t // 5) & 1}!']
        for c, w in sigs:
            x = (x * 1103515245 + 12345) & 0x7fffffff
            if t == 0 or x % 7 == 0:
                v = x >> 8
                out.append(f'{v & 1}{c}' if w == 1 else f'b{v & ((1 << w) - 1):b} {c}')
    path.write_text('\n'.join(out) + '\n')
    return len(sigs) + 1


def synth_page(build):
    """BUILD/smoke/synth.html from synth_vcd() through mkconfig.py (tools/base.config.json) and mkhtml.py."""
    d = build / 'smoke'
    d.mkdir(parents=True, exist_ok=True)
    vcd, cfg, page = d / 'synth.vcd', d / 'synth.config.json', d / 'synth.html'
    n = synth_vcd(vcd)
    py = lambda *a: subprocess.run([sys.executable, '-I', *map(str, a)], capture_output=True, text=True)
    r = py(ROOT / 'tools' / 'mkconfig.py', vcd, '--out', cfg, '--force')
    if r.returncode == 0:
        r = py(ROOT / 'tools' / 'mkhtml.py', '--config', cfg, '--no-sva', '--reproducible', '--out', page)
    check(r.returncode == 0 and page.exists(), f'synthetic page of {n} signals in 255 scopes built ({page.name})'
          + (': ' + r.stderr.strip()[-300:] if r.returncode else ''))
    return page


def bus_vcd(path):
    """A dump with one port of every protocol bus.js decodes, each with known transfers: AXI4 (a burst, reads answered
    out of order by ID, SLVERR), AXI4-Stream (a stall), APB (a wait state, PSLVERR), AHB (pipelined, a wait state in a
    burst), Avalon-MM (waitrequest, pipelined reads), Avalon-ST, Wishbone classic and pipelined, OBI. Cycle c is
    [10c, 10c + 10) ns; the registered signals change at the rising edge 10c."""
    N, mods = 20, {}
    def port(mod, sigs):   # sigs: name -> width
        mods[mod] = {n: [w, [0] * N] for n, w in sigs.items()}
    def put(mod, c0, c1, **vals):   # cycles c0..c1 (inclusive)
        for n, v in vals.items():
            for c in range(c0, c1 + 1): mods[mod][n][1][c] = v
    port('u_axi', dict(s_axi_awvalid=1, s_axi_awready=1, s_axi_awaddr=32, s_axi_awid=4, s_axi_awlen=8, s_axi_wvalid=1, s_axi_wready=1, s_axi_wdata=32, s_axi_wlast=1,
                       s_axi_bvalid=1, s_axi_bready=1, s_axi_bresp=2, s_axi_bid=4, s_axi_arvalid=1, s_axi_arready=1, s_axi_araddr=32, s_axi_arid=4, s_axi_arlen=8,
                       s_axi_rvalid=1, s_axi_rready=1, s_axi_rdata=32, s_axi_rresp=2, s_axi_rid=4, s_axi_rlast=1))
    a = 'u_axi'; put(a, 0, N - 1, s_axi_bready=1, s_axi_rready=1)
    put(a, 2, 3, s_axi_awvalid=1, s_axi_awaddr=0x100, s_axi_awid=1, s_axi_awlen=1); put(a, 3, 3, s_axi_awready=1)
    put(a, 4, 4, s_axi_wvalid=1, s_axi_wready=1, s_axi_wdata=0xa1); put(a, 5, 5, s_axi_wvalid=1, s_axi_wready=1, s_axi_wdata=0xa2, s_axi_wlast=1)
    put(a, 7, 7, s_axi_bvalid=1, s_axi_bid=1)
    put(a, 9, 9, s_axi_arvalid=1, s_axi_arready=1, s_axi_araddr=0x200, s_axi_arid=2); put(a, 10, 10, s_axi_arvalid=1, s_axi_arready=1, s_axi_araddr=0x300, s_axi_arid=3, s_axi_arlen=1)
    put(a, 12, 12, s_axi_rvalid=1, s_axi_rid=3, s_axi_rdata=0x31); put(a, 13, 13, s_axi_rvalid=1, s_axi_rid=3, s_axi_rdata=0x32, s_axi_rlast=1)
    put(a, 14, 14, s_axi_rvalid=1, s_axi_rid=2, s_axi_rdata=0x21, s_axi_rlast=1)
    put(a, 16, 16, s_axi_awvalid=1, s_axi_awready=1, s_axi_awaddr=0x400, s_axi_awid=1, s_axi_wvalid=1, s_axi_wready=1, s_axi_wdata=0xbad, s_axi_wlast=1)
    put(a, 17, 17, s_axi_bvalid=1, s_axi_bid=1, s_axi_bresp=2)
    port('u_axis', dict(m_axis_tvalid=1, m_axis_tready=1, m_axis_tdata=8, m_axis_tlast=1))
    put('u_axis', 2, 4, m_axis_tvalid=1); put('u_axis', 2, 3, m_axis_tdata=5); put('u_axis', 3, 4, m_axis_tready=1); put('u_axis', 4, 4, m_axis_tdata=6, m_axis_tlast=1)
    port('u_apb', dict(PSEL=1, PENABLE=1, PREADY=1, PADDR=16, PWRITE=1, PWDATA=32, PRDATA=32, PSLVERR=1))
    put('u_apb', 2, 4, PSEL=1, PADDR=0x10, PWRITE=1, PWDATA=0x55); put('u_apb', 3, 4, PENABLE=1); put('u_apb', 4, 4, PREADY=1)
    put('u_apb', 6, 7, PSEL=1, PADDR=0x14); put('u_apb', 7, 7, PENABLE=1, PREADY=1, PRDATA=0x77, PSLVERR=1)
    port('u_ahb', dict(HTRANS=2, HADDR=32, HWRITE=1, HWDATA=32, HRDATA=32, HREADY=1, HRESP=1))
    h = 'u_ahb'; put(h, 0, N - 1, HREADY=1)
    put(h, 2, 2, HTRANS=2, HADDR=0x20, HWRITE=1); put(h, 3, 3, HWDATA=0x99, HTRANS=2, HADDR=0x24); put(h, 4, 4, HRDATA=0x88)
    put(h, 6, 6, HTRANS=2, HADDR=0x40, HWRITE=1); put(h, 7, 7, HTRANS=3, HADDR=0x44, HWRITE=1, HWDATA=1); put(h, 8, 9, HTRANS=3, HADDR=0x48, HWRITE=1, HWDATA=2)
    put(h, 8, 8, HREADY=0); put(h, 10, 10, HWDATA=3)
    port('u_avmm', dict(avs_address=16, avs_read=1, avs_write=1, avs_writedata=32, avs_readdata=32, avs_readdatavalid=1, avs_waitrequest=1))
    m = 'u_avmm'; put(m, 2, 3, avs_write=1, avs_address=0x8, avs_writedata=0x11); put(m, 2, 2, avs_waitrequest=1)
    put(m, 5, 5, avs_read=1, avs_address=0xc); put(m, 6, 6, avs_read=1, avs_address=0x10); put(m, 7, 7, avs_readdatavalid=1, avs_readdata=0xa); put(m, 8, 8, avs_readdatavalid=1, avs_readdata=0xb)
    port('u_avst', dict(asi_valid=1, asi_ready=1, asi_data=8, asi_startofpacket=1, asi_endofpacket=1))
    put('u_avst', 0, N - 1, asi_ready=1); put('u_avst', 2, 4, asi_valid=1); put('u_avst', 2, 2, asi_startofpacket=1, asi_data=1); put('u_avst', 3, 3, asi_data=2); put('u_avst', 4, 4, asi_data=3, asi_endofpacket=1)
    port('u_wb', dict(wb_cyc_o=1, wb_stb_o=1, wb_we_o=1, wb_adr_o=16, wb_dat_o=32, wb_dat_i=32, wb_ack_i=1))
    put('u_wb', 2, 3, wb_cyc_o=1, wb_stb_o=1, wb_we_o=1, wb_adr_o=0x30, wb_dat_o=0x12); put('u_wb', 3, 3, wb_ack_i=1)
    put('u_wb', 5, 6, wb_cyc_o=1, wb_stb_o=1, wb_adr_o=0x34); put('u_wb', 6, 6, wb_ack_i=1, wb_dat_i=0xab)
    port('u_wbp', dict(wbp_cyc_o=1, wbp_stb_o=1, wbp_we_o=1, wbp_adr_o=16, wbp_dat_o=32, wbp_dat_i=32, wbp_ack_i=1, wbp_stall_i=1))
    put('u_wbp', 2, 6, wbp_cyc_o=1); put('u_wbp', 2, 4, wbp_stb_o=1); put('u_wbp', 2, 2, wbp_adr_o=0x50); put('u_wbp', 3, 4, wbp_adr_o=0x54); put('u_wbp', 3, 3, wbp_stall_i=1)
    put('u_wbp', 5, 5, wbp_ack_i=1, wbp_dat_i=0xc1); put('u_wbp', 6, 6, wbp_ack_i=1, wbp_dat_i=0xc2)
    port('u_obi', dict(data_req_o=1, data_gnt_i=1, data_addr_o=32, data_we_o=1, data_wdata_o=32, data_rvalid_i=1, data_rdata_i=32, data_err_i=1))
    o = 'u_obi'; put(o, 2, 2, data_req_o=1, data_gnt_i=1, data_addr_o=0x60, data_we_o=1, data_wdata_o=7); put(o, 3, 4, data_req_o=1, data_addr_o=0x64); put(o, 4, 4, data_gnt_i=1)
    put(o, 4, 4, data_rvalid_i=1); put(o, 6, 6, data_rvalid_i=1, data_rdata_i=0x99)
    ids, lines, k = {}, ['$timescale 1ns $end', '$scope module tb $end', '$var wire 1 ! clk $end'], 0
    code = lambda i: ''.join(chr(34 + (i // 90 ** j) % 90) for j in range(1 + (i >= 90)))
    for mod, sigs in mods.items():
        lines.append(f'$scope module {mod} $end')
        for n, (w, _) in sigs.items():
            k += 1; ids[(mod, n)] = code(k); lines.append(f'$var wire {w} {ids[(mod, n)]} {n}{f" [{w - 1}:0]" if w > 1 else ""} $end')
        lines.append('$upscope $end')
    lines += ['$upscope $end', '$enddefinitions $end']
    fmt = lambda w, v, i: f'{v}{i}' if w == 1 else f'b{v:b} {i}'
    last = {}
    for c in range(N + 1):
        lines.append(f'#{10 * c}'); lines.append(('1' if c else '0') + '!')
        for mod, sigs in mods.items():
            for n, (w, vals) in sigs.items():
                v = vals[c] if c < N else 0
                if last.get((mod, n)) != v: lines.append(fmt(w, v, ids[(mod, n)])); last[(mod, n)] = v
        lines.append(f'#{10 * c + 5}'); lines.append('0!')
    path.write_text('\n'.join(lines) + '\n')


def buses(browser, build):
    """Stage 11: bus.js on a dump with a port of every protocol (bus_vcd), and on the APB / AXI-Lite example pages."""
    d = build / 'smoke'; d.mkdir(parents=True, exist_ok=True)
    vcd, cfg, html = d / 'buses.vcd', d / 'buses.config.json', d / 'buses.html'
    bus_vcd(vcd)
    py = lambda *a: subprocess.run([sys.executable, '-I', *map(str, a)], capture_output=True, text=True)
    r = py(ROOT / 'tools' / 'mkconfig.py', vcd, '--out', cfg, '--force')
    if r.returncode == 0:
        r = py(ROOT / 'tools' / 'mkhtml.py', '--config', cfg, '--no-sva', '--reproducible', '--out', html)
    check(r.returncode == 0, 'the bus page built' + (': ' + r.stderr.strip()[-300:] if r.returncode else ''))
    if r.returncode:
        return
    print('buses')
    page = browser.new_page(viewport={'width': 1400, 'height': 1000})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(html.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()')
    got = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView;
        return Object.fromEntries(v.buses.list().map(p => [p.scope.split('.').pop(), [p.label || p.proto, p.D.tx.map(x => x.label + (x.err ? ' !' : '') + ' ' + x.lat)]])); })()""")
    want = {
        'u_axi': ['AXI4', ['W 0x100 ← 0xa1 ×2 6', 'R 0x200 → 0x21 6', 'R 0x300 → 0x31 ×2 4', 'W 0x400 ← 0xbad ! 2']],
        'u_axis': ['axis', ['2 beats 0x5 3']],
        'u_apb': ['apb', ['W 0x10 ← 0x55 3', 'R 0x14 → 0x77 ! 2']],
        'u_ahb': ['ahb', ['W 0x20 ← 0x99 2', 'R 0x24 → 0x88 2', 'W 0x40 ← 0x1 ×3 5']],
        'u_avmm': ['avmm', ['W 0x8 ← 0x11 2', 'R 0xc → 0xa 3', 'R 0x10 → 0xb 3']],
        'u_avst': ['avst', ['3 beats 0x1 3']],
        'u_wb': ['Wishbone', ['W 0x30 ← 0x12 2', 'R 0x34 → 0xab 2']],
        'u_wbp': ['Wishbone pipelined', ['R 0x50 → 0xc1 4', 'R 0x54 → 0xc2 4']],
        'u_obi': ['obi', ['W 0x60 ← 0x7 3', 'R 0x64 → 0x99 4']],
    }
    for k, w in want.items():
        check(got.get(k) == w, f'{k}: {w[0]}: the transfers, their errors and cycles {got.get(k)}')
    # a click on a transaction (on the folded group's header): the cursor at its start, its range, its signals highlighted
    sel = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, p = v.buses.list().find(p => p.proto === 'apb'), x = p.D.tx[1];
        v.buses.select(p, x); return [v.cursor === x.t0, v.range && v.range[0] === x.t0 && v.range[1] === x.t1, v.extraPicks.size, WaveFW.internal.peek(v).vis.some(r => r === v.buses.st.get(p.key).g)]; })()""")
    c = page.locator('.wv canvas').first; c.focus(); page.evaluate("document.querySelector('.wv').waveView.cursor = 0")
    page.keyboard.press(']'); page.keyboard.press('t'); t1 = page.evaluate("document.querySelector('.wv').waveView.cursor")
    check(sel[:2] == [True, True] and sel[2] >= 8 and sel[3] and t1 == 20000, f'a transaction selected: the cursor at its start, its range measured, its signals highlighted; ]t: the first one {sel} {t1}')
    svg = page.evaluate("WaveFW.WaveSVG.toString(WAVES[Object.keys(WAVES)[0]])")
    check(svg.count('⇄') >= 9 and 'W 0x100' in svg, f'the static SVG draws the ports and their transactions ({svg.count("⇄")} ports)')
    check(not errs, 'no page errors (buses)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    for ex, want2 in (('apb/apb.html', ['W 0x4 ← 0xcafe0001', 'R 0x4 → 0xcafe0001', 'W 0x40 ← 0xdeadbeef !']), ('axi_lite/axi_lite.html', ['W 0x8 ← 0x1234abcd', 'R 0x8 → 0x1234abcd'])):
        if not need(build / 'examples' / ex, how='make examples'):
            continue
        page.goto((build / 'examples' / ex).as_uri()); page.wait_for_load_state('networkidle')
        g = page.evaluate("document.querySelector('.wv').waveView.buses.list().map(p => p.D.tx.map(x => x.label + (x.err ? ' !' : '')))")
        check(g == [want2], f'{ex}: its port found and decoded {g}')
    page.close()


# the assertion list starts folded (svaOpen: false); the sections that work in it open it through the settings file
# hook (window.WAVEFW_CONFIG, as a page's wavefw.config.js would): every page of these contexts gets svaOpen: true
SVA_OPEN = """(() => { let c = { svaOpen: true }; Object.defineProperty(window, 'WAVEFW_CONFIG', { configurable: true,
    get: () => c, set: v => { c = Object.assign({}, v, { svaOpen: true }); } }); })()"""
PLAIN = {}


def sva_open(b):
    """Every page of the run: svaOpen through the settings hook (but PLAIN['new_page']), the default timeout."""
    nc, np = b.new_context, b.new_page
    def plain(*a, **k):
        pg = np(*a, **k); pg.set_default_timeout(TIMEOUT); pg.set_default_navigation_timeout(4 * TIMEOUT); return pg
    PLAIN['new_page'] = plain
    def new_context(*a, **k):
        ctx = nc(*a, **k); ctx.add_init_script(SVA_OPEN); ctx.set_default_timeout(TIMEOUT); ctx.set_default_navigation_timeout(4 * TIMEOUT); return ctx
    def new_page(*a, **k):
        pg = plain(*a, **k); pg.add_init_script(SVA_OPEN); return pg
    b.new_context, b.new_page = new_context, new_page


def tips(browser, build):
    """Every control of a viewer has a tooltip (what it does, its keys), ours instead of the browser's; ? shows the keys."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('tooltips and help')
    page = browser.new_page(viewport={'width': 1400, 'height': 1000})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    js('(v.mark("x"), 0)')   # the bookmark list too
    plain = PLAIN['new_page'](); plain.goto(apb.as_uri()); plain.wait_for_load_state('networkidle')
    fold = plain.evaluate("[...document.querySelectorAll('.wv')].map(e => [e.waveView.sva.open, !!e.querySelector('.sva .svr'), e.querySelector('.sva button.tw').getAttribute('aria-expanded')])")
    plain.locator('.wv .sva button.tw').first.click(); opened = plain.evaluate("document.querySelector('.wv').waveView.sva.open"); plain.close()
    check(fold and all(f == [False, False, 'false'] for f in fold) and opened, f'the assertion list starts folded (svaOpen: false); ▸ Assertions opens it {fold}')
    lines = page.evaluate("[...document.querySelector('.wv .bar .tools').children].map(l => [l.dataset.ln, [...l.querySelectorAll(':scope > .tg')].map(g => g.dataset.tg), Math.round(l.getBoundingClientRect().top)])")
    got = {l[0]: l[1] for l in lines}
    check([l[0] for l in lines] == ['time', 'find', 'expr', 'rows'] and got['time'][:3] == ['cursor', 'view', 'edges'] and got['find'] == ['find'] and got['expr'] == ['expression']
          and got['rows'] == ['list', 'style', 'state', 'dump', 'assertions'] and len({l[2] for l in lines}) == 4,
          f'the bar: one line per kind (time, find, expression, rows and files), the plugins\' groups on theirs {lines}')
    miss = page.evaluate("""[...document.querySelector('.wv').querySelectorAll('button, input:not([type=file]), select, .mk')].filter(e => !WaveFW.tips.of(e)).map(e => e.outerHTML.slice(0, 80))""")
    check(not miss, f'every button, field and list of a viewer (bar, assertions, bookmarks) has a tooltip (missing: {miss[:5]})')
    b = page.locator('.wv button[data-act=in]').first; b.hover(); until(page, "!!document.querySelector('.wv-tip')")
    tip = page.locator('.wv-tip')
    got = [tip.count() == 1 and tip.locator('span').first.inner_text(), tip.locator('kbd').all_inner_texts(), b.get_attribute('title')]
    page.mouse.move(5, 5); until(page, "!document.querySelector('.wv-tip')"); got.append(tip.count())
    check(got == ['Zoom in', ['i', '+', 'ctrl+wheel'], None, 0], f'hover: "Zoom in" and its keys after a moment, no browser tooltip, gone when the pointer leaves {got}')
    # in the right button's menu a tooltip waits menuTipDelay (2 s)
    c = page.locator('.wv canvas').first; c.scroll_into_view_if_needed(); cb = c.bounding_box(); page.mouse.click(cb['x'] + 200, cb['y'] + 60, button='right')
    page.locator('.wv-menu button[data-m=png]').hover(); page.wait_for_timeout(800); early = page.locator('.wv-tip').count()
    until(page, "!!document.querySelector('.wv-tip')", 4000); late = page.locator('.wv-tip').count(); page.keyboard.press('Escape')
    check([early, late] == [0, 1], f'a tooltip in the menu waits menuTipDelay: none after 0.8 s, there after 2 s {[early, late]}')
    page.locator('.wv canvas').first.click(); page.keyboard.press('?')
    hl = page.locator('.wv-help')
    hk = [hl.count(), hl.locator('h4').all_inner_texts(), ']f' in hl.inner_text() and ']t' in hl.inner_text()]
    page.keyboard.press('Escape'); hk.append(hl.count()); page.locator('.wv button[data-act=help]').first.click(); hk.append(hl.count())
    page.mouse.click(5, 5); hk.append(hl.count())
    check(hk[0] == 1 and hk[1][:5] == ['ZOOM AND MOVE', 'CURSOR AND EDGES', 'SIGNALS', 'FIND', 'MEASURE AND MARK'] and hk[2] and hk[3:] == [0, 1, 0],
          f'? (key and button): the keys and the mouse by what they do, the plugins\' too (]f, ]t); Esc or a click outside closes it {hk}')
    c = page.locator('.wv canvas').first; bb = c.bounding_box(); page.mouse.click(bb['x'] + 200, bb['y'] + 60, button='right')
    kk = page.locator('.wv-menu button[data-m=copyname] .kk').inner_text() if page.locator('.wv-menu button[data-m=copyname]').count() else None
    page.keyboard.press('Escape')
    check(kk == 'yy', f'the menu shows the keys of its items (Copy the path: {kk})')
    check(not errs, 'no page errors (tooltips, help)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    page.close()


def spike(browser, build):
    """make sva-spike: sva-core as WebAssembly in a page."""
    path = build / 'sva' / 'spike.html'
    if not need(path, how='make sva-spike'):
        return
    print(path.name)
    page = browser.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(path.as_uri())
    page.wait_for_function('window.SPIKE', timeout=10000)
    s = page.evaluate('window.SPIKE')
    got = [(x['start'], x['result'], x['end']) for x in s['report']['attempts']]
    check(not errs and got == [(1, 'pass', 3), (4, 'fail', 7), (8, 'disabled', 9), (11, 'active', 11)],
          f'sva spike: the WebAssembly build gives the native results {got} ({s["wasm"]} B, one call {s["callUs"]:.0f} µs)')
    tv = s['tv']
    want_ = {'attempts': 32764, 'pass': 2016, 'fail': 32, 'vacuous': 30716, 'disabled': 0, 'active': 0, 'capped': 0}
    check(tv['cycles'] == 32768 and tv['stats'] == want_ and tv['ms'] < 1000 * SCALE,
          f'sva spike: evaluate(parsed, tvSampler) over 32768 clock edges in {tv["ms"]:.0f} ms (< {1000 * SCALE:.0f}): {tv["stats"]}')
    page.close()


SECTIONS = {   # section: what it checks (smoke.py --list)
    'pages': 'every page in both schemes: no console errors, no error boxes, drawn canvases, static SVGs, a PNG',
    'units': 'the pure functions of the viewer (WaveFW.internal), the VCD reader, the bus decoders, sva.js expressions: a table of cases',
    'readers': 'the page\'s VCD reader against the tools\' on every fixture of tests/unit/vcd (one rule, the same transitions)',
    'docs': 'docs/index.html: cursor, zoom, sorting, settings, styles, highlight, cursor fields, themes, bookmarks',
    'sva_docs': 'docs/index.html: the assertions section and the unit checks of wavefw/sva.js',
    'conformance': 'tests/conformance.html against stock WaveDrom: lanes and texts per case',
    'hierarchy': 'the synthetic page (and work/test_stream_video.html): scopes as groups, highlight, Collapse / Expand, "same"',
    'find': 'the synthetic page (and work/test_stream_video.html): fuzzy find, Open, Paint, Copy, Esc, n / N',
    'deep': 'the synthetic page (and work/test_stream_video.html): every level on the page, virtualised canvas',
    'fst': 'BUILD/demo_fst.html (make demo-fst): FSM state names and hierarchy from the FST',
    'examples': 'the example pages (make examples): bookmarks, arrows, colours, state names, their assertions',
    'big': 'every built page: redraw time, Sort',
    'wavefw': 'wavefw.js is the concatenation of wavefw/src/*.js; the pure functions (parse, fuzzy, decode, sortRows, fmtTime, parseT)',
    'api_docs': 'docs/index.html § API made from the exports of WaveFW, the viewer methods, every default setting',
    'plugin_api': 'the plugin API: tokens, tools, panels, rows, marks, listeners, keys, events, plugin groups, enums by path; sva.js on it only',
    'viewer': 'stage 9.4: keys, wheel, exact cursor, buttons, value tip, storage keys, data-theme, long values, find, destroy, keyboard, click time, Esc folding, print',
    'spike': 'BUILD/sva/spike.html (make sva-spike): the WebAssembly engine in a page',
    'sva_bind': 'apb_all.html: Load file…, Bind…, drag and drop, reload, a config through mkhtml.py',
    'sva_hardening': 'stage 6.1 on the example pages',
    'sva_waves': 'stage 7: the assertion groups on the waves',
    'sva_exprs': 'stage 10: expressions in the bar (search, rows ƒ, kept, JSON), names in a hierarchy',
    'dump': 'a VCD opened in the page (Open…, dropped on a viewer), ⟳, wavefw/viewer.html',
    'state': 'Save / Load… of a viewer (the APB and AXI-Lite pages): its state to a file and back, on other waves',
    'edit': 'the viewer\'s commands, a page\'s edits (tools/viewedit.py) with the same state, your groups and markers, a page live through wavemcp.py',
    'compare': 'a second dump compared: ≠ on the names that differ, struck when it lacks them, red bands, ]d [d, in the picture; clock-sampled refused',
    'savepage': 'Save page: the page with your view in its edits opens elsewhere as you left it; its waves as they were; the live token left out',
    'order': 'your groups\' rows in another order: alt+↑ / alt+↓ (shift: the group), a drag in the names, group move; one step each',
    'undo': 'ctrl+Z / ctrl+shift+Z and ↶ ↷: the edits undone and redone a step at a time (a batch of commands, a menu action), not the cursor',
    'cycles': 'the clock cycles under the time axis: numbers, the cursor\'s cycle, c147, cycle 0, Δ, the menu, the pictures, kept',
    'ranges': 'a range on the waves (shift+drag, the right button) and its menu: zoom, bookmarks, the picture, a colour',
    'tips': 'every control has a tooltip with its keys; ? shows the keys and the mouse',
    'buses': 'stage 11: bus transactions (AXI4, AXI4-Stream, APB, AHB, Avalon-MM / ST, Wishbone, OBI) on a dump of every protocol and the examples',
    'sva_report': 'stage 8: the report against sva eval',
    'sva_edit': 'an assertion edited in the page (✎, Apply, kept, Revert, a bad text) and read from the disk again (⟳, Watch)',
    'sva_report_hardening': 'stage 8.1: names, aliases, recovery, caps, print, mkconfig --update, make html SVA=',
    'sva_wasm': 'wavefw/sva.wasm.js is the module of the current build (make sva-build)',
    'sva_third_party': 'tests/sva/third_party over the example dumps (sva eval)',
    'sva_eval': 'sva eval over the example dumps: only the deliberate failures fail',
}


VERSION = re.search(r"version: '([^']+)'", (ROOT / 'wavefw' / 'src' / 'boot.js').read_text()).group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=str(ROOT / 'out'), help='the Makefile BUILD directory (demo.html, demo_fst.html)')
    ap.add_argument('--out', help='screenshots (default: BUILD/shots)')
    ap.add_argument('--strict', action='store_true', help='a skipped page or section fails the run (make check)')
    ap.add_argument('--only', help='comma-separated sections (--list)')
    ap.add_argument('--list', action='store_true', help='list the sections and exit')
    a = ap.parse_args()
    if a.list:
        for k, t in SECTIONS.items():
            print(f'{k:22} {t}')
        return
    ONLY.update(x for x in (a.only or '').split(',') if x)
    if ONLY - set(SECTIONS):
        sys.exit(f'smoke: unknown section(s) {", ".join(sorted(ONLY - set(SECTIONS)))} (--list)')
    a.out = a.out or os.path.join(a.build, 'shots')
    build = pathlib.Path(a.build).resolve()   # as_uri() needs an absolute path
    ERRDIR[0] = str(build / 'smoke')
    synth = synth_page(build) if any(want(x) for x in ('pages', 'hierarchy', 'find', 'deep', 'big', 'viewer')) else None
    # the build products smoke expects (missing: SKIPPED) and the user's own pages under work/ (checked when there)
    expected = {build / 'demo.html': 'make html', build / 'demo_fst.html': 'make demo-fst'}
    expected.update({build / 'examples' / ex / f'{ex}{s}.html': 'make examples' for ex in EXAMPLES for s in ('', '_all')})
    user = [x for x in (ROOT / 'work' / 'dump.html', ROOT / 'work' / 'test_stream_video.html') if x.exists()]
    for path, how in expected.items():
        if not path.exists():
            skip(path, how)
    BUILT[:] = [x for x in expected if x.exists()] + user + ([synth] if synth and synth.exists() else [])
    print('user pages: ' + (', '.join(str(x.relative_to(ROOT)) for x in user) or 'none under work/ (make html WAVES=work/x.vcd)'))
    os.makedirs(a.out, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        sva_open(b)
        for path in PAGES + BUILT:
            tsv = path.name == 'test_stream_video.html'
            own = (['docs', 'sva_docs', 'viewer', 'wavefw', 'plugin_api', 'api_docs'] if path == PAGES[0] else ['conformance'] if path == PAGES[1] else
                   ['hierarchy', 'find', 'deep', 'viewer'] if path == synth or tsv else ['fst'] if path.name == 'demo_fst.html' else
                   ['examples'] if path.stem in EXAMPLES or path.stem == 'fsm_all' else [])
            own += ['big'] if path in BUILT else []
            if not want('pages') and not any(want(x) for x in own):
                continue
            for scheme in ('light', 'dark') if want('pages') else ('light',):
                print(f'{path.name} [{scheme}]')
                page = b.new_page(color_scheme=scheme, viewport={'width': 1360, 'height': 900})
                COUNT[1] += 1
                errs = []
                page.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
                page.on('pageerror', lambda e: errs.append(str(e)))
                page.goto(path.as_uri())
                page.wait_for_load_state('networkidle')
                page.evaluate('document.fonts.ready')
                settle(page)
                errs = [e for e in errs if 'fonts.g' not in e]   # offline Google Fonts is not a page error
                if want('pages'):
                    check(not errs, 'no console/page errors' + (': ' + ' | '.join(errs[:3]) if errs else ''))
                    check(page.locator('.wvf-err').count() == 0, 'no wavefw error boxes')
                    n = page.locator('.wv canvas').count()
                    blank = page.evaluate('''() => [...document.querySelectorAll('.wv canvas')].filter(c => c.width === 0 || c.height === 0).length''')
                    check(n > 0 and blank == 0, f'{n} viewers, all canvases drawn')
                    if path not in BUILT:
                        check(page.locator('.wvs svg').count() > 0, f'{page.locator(".wvs svg").count()} static SVGs')
                stale = path in user and page.evaluate('window.WaveFW && WaveFW.version') != VERSION
                if stale:   # the user's page, built with another wavefw.js: the general checks only
                    print(f'  note: {path.name} was built with wavefw {page.evaluate("window.WaveFW && WaveFW.version")}, this is {VERSION}: rebuild it (make html WAVES=…) for the rest')
                if scheme == 'light' and not stale:
                    if path == PAGES[0]:
                        for fn in (interact, sorting, settings, styles, highlight, cursor, themes, bookmarks):
                            run('docs', fn, page)
                        run('sva_docs', sva_docs, page)
                        run('sva_docs', sva_units, page)
                        run('viewer', viewer, page)
                        run('wavefw', wavefw_units, page)
                        run('viewer', viewer_fixes, page)
                        run('plugin_api', plugin_api, page)
                        run('api_docs', api_docs, page)
                    if path == PAGES[1]:
                        run('conformance', conformance, page)
                    if path == synth or tsv:
                        P = TSV if tsv else SYNTH
                        run('hierarchy', hierarchy, page, P)
                        run('find', find, page, P)
                        run('deep', deep, page, P)
                        if path == synth:
                            run('viewer', viewer_big, page, P)
                    if path.name == 'demo_fst.html':
                        run('fst', fst, page)
                    if path.stem in EXAMPLES:
                        run('examples', example, page, path.stem)
                        run('examples', sva_page, page, path.stem)
                    if path.stem == 'fsm_all':
                        run('examples', fsm_vcd, page)
                    if path in BUILT:
                        run('big', big, page)
                if want('pages'):
                    shot = os.path.join(a.out, f'{path.stem}_{scheme}.png')
                    page.screenshot(path=shot, full_page=True)
                    print('  shot ' + shot)
                page.close()
        run('spike', spike, b, build)
        run('units', units, b, build)
        run('sva_docs', sva_nesting, b, build)
        run('sva_bind', sva_bind, b, build)
        run('sva_hardening', sva_hardening, b, build)
        run('sva_waves', sva_waves, b, build)
        run('sva_exprs', sva_exprs, b, build)
        run('state', state, b, build)
        run('edit', edit, b, build)
        run('cycles', cycles, b, build)
        run('undo', undo, b, build)
        run('order', order, b, build)
        run('savepage', savepage, b, build)
        run('compare', compare, b, build)
        run('dump', dump, b, build)
        run('readers', readers, b, build)
        run('ranges', ranges, b, build)
        run('buses', buses, b, build)
        run('tips', tips, b, build)
        run('sva_report', sva_report, b, build)
        run('sva_edit', sva_edit, b, build)
        run('sva_report_hardening', sva_report_hardening, b, build)
        b.close()
    run('sva_wasm', sva_wasm, build)
    run('sva_third_party', sva_third_party, build)
    run('sva_eval', sva_examples, build)
    print()
    if skips:
        pages = sorted({w for _, w, _ in skips if w.endswith('.html')})
        secs = sorted({sec for sec, _, _ in skips})
        hows = sorted({h for _, _, h in skips})
        print(f'SKIPPED {len(pages)} pages / {len(secs)} sections ({", ".join(secs)}) (run {", ".join(hows)})'
              + (': a failure with --strict' if a.strict else ''))
    else:
        print('SKIPPED 0 pages / 0 sections')
    print(f'{COUNT[0]} checks on {COUNT[1]} pages, ' + (f'FAILED: {len(fails)}' if fails else 'all checks passed'))
    for f in fails:
        print('  FAIL ' + f)
    sys.exit(1 if fails or (a.strict and skips) else 0)


if __name__ == '__main__':
    main()
