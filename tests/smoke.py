#!/usr/bin/env python3
"""smoke.py — headless Chromium check of docs/index.html and tests/conformance.html (Python playwright).

For each page and colour scheme: no console errors / page errors / wavelens error boxes, every viewer has a
drawn canvas, and on docs/index.html the viewer interaction works (cursor click updates the value column, wheel
zoom changes the view span, Fit restores it, jump buttons move the cursor, group folding hides rows, a lazy
card builds its viewer when opened, Sort with ignored prefixes, settings layers, edge styles and radix). Pages built by
`make html` / `make demo-fst` / `make examples` (BUILD/demo.html, BUILD/demo_fst.html, BUILD/examples/<ex>/<ex>.html and
<ex>_all.html, work/dump.html, work/test_stream_video.html: scope hierarchy, folding, "same", bookmarks and arrows of the
examples, FSM state names) and BUILD/sva/spike.html (make sva-spike: the WebAssembly engine, evaluate() over a synthetic
32k-edge "tv" model in under a second) are checked too when they exist, and `sva eval` over the example dumps (only the
deliberate failures fail). Assertions in pages (wavelens/sva.js): the section of docs/index.html, the example pages (bound from
their configs; evaluated again in the page they give the native counts, also through the Web Worker), the binding flow on
apb_all.html (Load file…, Bind…, "cannot bind", drag and drop, several instances, reload, the JSON through a config and
mkhtml.py), wavelens/sva.wasm.js against the build, and the third-party checkers of tests/sva/third_party over the example
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
    names = lambda: [re.sub(r'\s*\[\d+:\d+\]$', '', x.strip()) for x in v.locator('.names .row .n').all_inner_texts()]   # the names, not their widths
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
    check(pfx == 'bit_,rx_', f'JSON config beats wavelens.config.js ({pfx!r})')
    ex.locator('button[data-act=sort]').click()
    en = [re.sub(r'\s*\[\d+:\d+\]$', '', x.strip()) for x in ex.locator('.names .row .n').all_inner_texts()]
    check(en == ['clk', 'data', '▾ mc_tx', 'busy', 'bit_cnt', 'done', 'state', 'txd', 'rst_n', 'rx_sr', 'start'], f'group sorted as a block, members inside {en}')
    ex.locator('button[data-act=sort]').click(); ex.locator('button[data-act=sort]').click()


def settings(page):
    js = page.evaluate
    v = '#ex-handshake-view'
    canvas_h = lambda: js(f"document.querySelector('{v} canvas').getBoundingClientRect().height")
    check(js("WaveLens.configure({}).sortIgnore.join(',')") == 'i_,o_', 'wavelens.config.js loaded as global settings')
    h0, svg_h = canvas_h(), js("document.querySelector('.wvs svg').getAttribute('height')")
    js("WaveLens.configure({rowHeight: 34, nameWidth: 260, traceWidth: 2})")
    h1, w = canvas_h(), js(f"document.querySelector('{v} .names').getBoundingClientRect().width")
    check(h1 > h0 + 20 and abs(w - 260) < 2, f'configure(rowHeight, nameWidth) restyles viewers (canvas {h0:.0f}->{h1:.0f}px, names {w:.0f}px)')
    check(js("document.querySelector('.wvs svg').getAttribute('height')") != svg_h, 'static SVGs are re-rendered by configure()')
    js("WaveLens.configure({rowHeight: null, nameWidth: 200, traceWidth: null})")
    check(canvas_h() == h0, 'null restores the default')


def styles(page):
    svg = lambda st: page.locator(f'#ex-style-{st} svg')
    texts = svg('square').locator('text').all_text_contents()
    check(all(t in texts for t in ('0x41', '-128', '01000001', '"A"')), f'per-signal radix hex/signed/bin/ascii {texts}')
    html = {st: svg(st).inner_html() for st in ('wavedrom', 'questa', 'square')}
    check(len(set(html.values())) == 3, 'styles wavedrom / questa / square draw different edges')
    dec = page.evaluate("[WaveLens.decode({width: 8}, 'a5', 'signed'), WaveLens.decode({width: 12}, 'a5', 'oct'), WaveLens.decode({width: 4, enum: {5: 'RUN'}}, '5', 'bin')]")
    check(dec == ['-91', '0o245', 'RUN'], f'decode radixes, enum first {dec}')
    # float (IEEE 754 of 16 / 32 / 64 bits) and fixed point q<F> / sq<F>: the page and vcd2wavedrom.py write the same text
    cases = [('3f800000', 32, 'float'), ('c0490fdb', 32, 'float'), ('3c00', 16, 'float'), ('400921fb54442d18', 64, 'float'), ('00000001', 32, 'float'),
             ('cafe0001', 32, 'float'), ('7f800000', 32, 'float'), ('4b189680', 32, 'float'), ('0180', 16, 'q8'), ('ff80', 16, 'sq8'), ('0001', 16, 'sq15'), ('fffe', 16, 'q1'), ('12', 8, 'float')]
    jsv = page.evaluate("cs => cs.map(([v, w, r]) => WaveLens.decode({ width: w }, v, r))", cases)
    sys.path.insert(0, str(ROOT / 'tools')); import vcd2wavedrom as v2w
    pyv = [v2w.label(v, w, None, r) for v, w, r in cases]
    check(jsv == pyv and jsv[:4] == ['1', '-3.141593', '1', '3.14159265358979'] and jsv[8:11] == ['1.5', '-0.5', '0.000030517578125'] and jsv[-1] == '0x12',
          f'radix float and fixed point (q8, sq15, exact): the page and vcd2wavedrom.py agree {jsv}')
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    data = ex.locator('.names .row', has_text='data').first.locator('.v')
    page.evaluate("WaveLens.configure({radix: 'bin'})")
    check(data.inner_text() == '00000000', f'configure({{radix: "bin"}}) changes the value column ({data.inner_text()!r})')
    page.evaluate("WaveLens.configure({radix: null})")
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
    run0 = page.evaluate("(() => { const v = document.getElementById('ex-hl-view').waveView; return [v.picks.size, WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig').map(r => r.name)]; })()")
    sig = run0[1]; first, last = sig[0], sig[3]
    page.evaluate("(() => { document.getElementById('ex-hl-view').waveView.highlight(null); })()")
    rows.filter(has_text=first).first.locator('.n').click(modifiers=['Control']); rows.filter(has_text=last).first.locator('.n').click(modifiers=['Control', 'Shift'])
    run = page.evaluate(f"""(() => {{ const v = document.getElementById('ex-hl-view').waveView, i = WaveLens.internal.peek(v).vis.findIndex(r => r.name === {json.dumps(first)}), j = WaveLens.internal.peek(v).vis.findIndex(r => r.name === {json.dumps(last)});
        return [WaveLens.internal.peek(v).vis.slice(i, j + 1).filter(r => r.type === 'sig').every(r => v.picks.has(r)), v.picks.size, String(getSelection())]; }})()""")
    check(run[0] and run[1] >= 4 and run[2] == '', f'ctrl+shift+click: every row from the last ctrl+clicked name to this one highlighted, no text selected ({first} … {last}: {run})')
    page.evaluate("(() => { const v = document.getElementById('ex-hl-view').waveView; v.highlight(null); ['tx', 'irq', 'clk'].forEach(n => v.toggleHighlight(n)); })()")
    rx = v.locator('.names .row.grp', has_text='rx')
    rx.locator('.mk').click()
    check(n('dim') == 0 and rx.get_attribute('aria-expanded') == 'true', 'the mark on a group highlights it without folding it')
    rx.locator('.mk').click()
    v.locator('canvas').focus(); page.keyboard.press('Escape')
    check(n('hl') == 0 and n('dim') == 0 and not btn.is_visible(), 'Esc clears the highlight')
    svg = page.evaluate("WaveLens.WaveSVG.toString(document.getElementById('ex-hl').textContent, {highlight: 'rx'})")
    check('opacity:0.3' in svg and 'var(--wave-hl1)' not in svg, 'static SVG dims the rows the highlight setting leaves out, no tint')
    page.evaluate("WaveLens.configure({highlight: ['state']})")
    ex = page.locator('.bench > div.wv[data-wave="DEMO_WAVES.exact"]')
    check(ex.locator('.names .row.hl').count() == 1 and v.locator('.names .row.hl').count() == 0,
          'configure({highlight}) picks in every viewer without its own setting')
    page.evaluate("WaveLens.configure({highlight: null})")
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
    ly, ry = js("[v.bmGeo.mids[0][2], ...(o => [o.y, o.y + o.h])(WaveLens.internal.peek(v).lay.find(o => o.row.type === 'lane'))]"), None
    check(ly[1] <= ly[0] <= ly[2] and lanes.first.bounding_box()['height'] == 16, f'label 2T is drawn inside its 16 px lane ({ly})')
    page.evaluate("WaveLens.configure({laneHeight: 24})")
    h24 = lanes.first.bounding_box()['height']
    page.evaluate("WaveLens.configure({arrowLabels: 'overlay'})")
    check(h24 == 24 and lanes.count() == 0, f'laneHeight sets the lane height ({h24}); arrowLabels "overlay" removes the lanes')
    page.evaluate("WaveLens.configure({laneHeight: null, arrowLabels: null})")
    svg = page.locator('#ex-bm-svg svg').get_attribute('height')
    check(int(svg) == int(page.evaluate("WaveLens.WaveSVG.toString(document.getElementById('ex-bm-src').textContent, {arrowLabels: 'overlay'})").split('height="')[1].split('"')[0]) + 32, 'static SVG adds the same lanes (2 × 16 px)')
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
    rowy = lambda name: js(f"(o => o.y + o.h / 2)(WaveLens.internal.peek(v).lay.find(o => o.row.name === '{name}'))")
    xof = lambda t: js(f'({t} - v.t0) * v.canvas.getBoundingClientRect().width / v.span')
    p2 = pos(2); page.mouse.move(box['x'] + p2[0], box['y'] + p2[1]); page.mouse.down()
    page.mouse.move(box['x'] + xof(9.05), box['y'] + rowy('data'), steps=6); page.mouse.up()
    check(js('[v.bms[1].t, v.bms[1].signal]') == [9, 'bus.data'], f'dragging circle 2 moves it to another row and time, snapped to the edge ({js("[v.bms[1].t, v.bms[1].signal]")})')
    # lifted: dragged onto the top quarter of its row, the circle goes into a lane above the signal (a leader down to it)
    top = js("(o => o.y + 2)(WaveLens.internal.peek(v).lay.find(o => o.row.name === 'data'))"); p2 = pos(2)
    page.mouse.move(box['x'] + p2[0], box['y'] + p2[1]); page.mouse.down(); page.mouse.move(box['x'] + p2[0], box['y'] + top, steps=6); page.mouse.up()
    up = js("[v.bms[1].lift, v.bmGeo.pos.get(2)[1], (o => [o.y, o.y + o.h / 2])(WaveLens.internal.peek(v).lay.find(o => o.row.name === 'data')), v.rowsL.some(r => r.type === 'lane' && r.ids.includes('b:bus.data')), v.bookmarks()[1].lift]")
    p2 = pos(2); page.mouse.move(box['x'] + p2[0], box['y'] + p2[1]); page.mouse.down(); page.mouse.move(box['x'] + p2[0], box['y'] + rowy('data') + 4, steps=6); page.mouse.up()
    down = js("[v.bms[1].lift, v.rowsL.some(r => r.type === 'lane' && r.ids.includes('b:bus.data'))]")
    bl.nth(1).locator('button[data-bm=lift]').click(); btn = js("[v.bms[1].lift, v.bmGeo.pos.get(2)[1] < (o => o.y)(WaveLens.internal.peek(v).lay.find(o => o.row.name === 'data'))]")
    bl.nth(1).locator('button[data-bm=lift]').click()   # ↥ again: under the signal (↧), then on the row again
    under = js("[v.bms[1].lift, (o => v.bmGeo.pos.get(2)[1] > o.y + o.h)(WaveLens.internal.peek(v).lay.find(o => o.row.name === 'data'))]")
    bl.nth(1).locator('button[data-bm=lift]').click()
    check(up[0] is True and up[1] < up[2][0] and up[3] and up[4] is True and down == [False, False] and btn == [True, True] and under == ['below', True]
          and not js('v.bms[1].lift'), f'a circle dragged to the top of its row goes into a lane above the signal (kept in the JSON), lower down back on '
          f'the row; ↥ does the same, again: under the signal, again: on the row {up} {down} {btn} {under}')
    # the lane of a lifted bookmark does not depend on arrowLabels: with "overlay" the arrows' labels stay on the arrows
    page.evaluate("WaveLens.configure({arrowLabels: 'overlay'})")
    bl.nth(1).locator('button[data-bm=lift]').click()
    ov = js("[v.rowsL.filter(r => r.type === 'lane').map(r => r.ids.join(',')), v.bmGeo.pos.get(2)[1] < (o => o.y)(WaveLens.internal.peek(v).lay.find(o => o.row.name === 'data'))]")
    bl.nth(1).locator('button[data-bm=lift]').click(); bl.nth(1).locator('button[data-bm=lift]').click()   # (above, under, off)
    page.evaluate("WaveLens.configure({arrowLabels: null})")
    check(ov == [['b:bus.data'], True], f'arrowLabels "overlay": a lifted bookmark still gets its lane, the arrow labels none {ov}')
    tip = js("(() => { const p = v.bmGeo.pos.get(1), c = v.canvas, r = c.getBoundingClientRect(); c.dispatchEvent(new PointerEvent('pointermove', "
             "{clientX: r.left + p[0], clientY: r.top + p[1], bubbles: true})); return c.title; })()")
    check(tip.startswith('Bookmark 1: ') and '— drag to move it' in tip, f'the tooltip of a circle has its text {tip!r}')
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
    leg = page.evaluate("WaveLens.parse({signal: [{name: 'a', wave: '01'}], bookmarks: [{n: 1, t: 0}, {n: 2, t: 1, to: 1, label: 'x'}]}).arrows")
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


def pageshot(browser, build):
    """tools/pageshot.py on the APB page: a PNG per view and theme with the sizes its manifest says, one view by its key,
    a view the page has not (exit 1)."""
    import struct
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    d = build / 'smoke' / 'pageshot'
    run_ = lambda *a: subprocess.run([sys.executable, str(ROOT / 'tools' / 'pageshot.py'), str(apb), '--out', str(d), *a], capture_output=True, text=True,
                                     env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'), timeout=300 * SCALE)
    r = run_()
    made = json.loads(r.stdout or '[]')
    size = lambda p: struct.unpack('>II', open(p, 'rb').read()[16:24])
    ok = [size(m['path']) == (m['width'], m['height']) for m in made]
    check(r.returncode == 0 and len(made) == 6 and all(ok) and {m['theme'] for m in made} == {'dark', 'light'} and (d / 'manifest.json').exists(),
          f'pageshot: 3 views × 2 themes, each PNG as big as its manifest says {[(m["view"], m["theme"]) for m in made]} {r.stderr.strip()[-200:]}')
    r1, r2 = run_('--view', 'exact', '--theme', 'dark'), run_('--view', 'nope')
    one = json.loads(r1.stdout or '[]')
    check(r1.returncode == 0 and [(m['view'], m['theme']) for m in one] == [('exact', 'dark')] and r2.returncode == 1 and 'no view "nope"' in r2.stderr,
          f'pageshot --view exact: one PNG; a view not there: exit 1 with the views it has {r2.stderr.strip()[:200]}')


def markup(page):
    """A viewer made here (a clock, a state bus, a strobe): a bookmark lifted "below" its signal (a lane under the row, the
    circle there, a leader up to it), labels by the circles, an arrow's {dt} / {cycles} / {cycles:clk} filled at its ends
    (and again when an end moves), spans over every row and over one row; WaveSVG draws the same; an old bookmark with
    "to" and "label" is still an arrow."""
    r = page.evaluate("""(async () => {
      const ns = 1000, ck = [], st = [[0, '0'], [30 * ns, '1'], [70 * ns, '2'], [110 * ns, '0']];
      for (let t = 0; t <= 150; t += 5) ck.push([t * ns, (t / 5) % 2 ? '1' : '0']);
      const j = { signal: [{ name: 'clk', tv: ck }, { name: 's', width: 2, tv: st }, { name: 'q', tv: [[0, '0'], [40 * ns, '1'], [60 * ns, '0']] }],
        time: { t0: 0, unit: 'ps' },
        bookmarks: [{ n: 1, t: 30 * ns, signal: 's', label: 'go', lift: 'below' }, { n: 2, t: 70 * ns, signal: 's', label: 'two' }, { n: 3, t: 40 * ns, signal: 'q', lift: true }],
        arrows: [{ from: 1, to: 2, label: '{dt} {cycles} {cycles:clk}' }], spans: [{ from: 20 * ns, to: 50 * ns, label: 'phase A', color: 'c7' },
          { from: 60 * ns, to: 90 * ns, signals: ['q'], label: 'pulse' }] };
      const el = document.body.appendChild(document.createElement('div')); el.id = 'markup-test';
      const v = new WaveLens.WaveView(el, j, { key: 'markup-test' }); localStorage.removeItem(v.bmKey);
      v.setBookmarks(j.bookmarks, j.arrows); v.spans = j.spans.map(x => Object.assign({}, x)); v.draw();
      const lay = WaveLens.internal.peek(v).lay, row = n => lay.find(o => o.row.type === 'sig' && o.row.name === n), ids = v.rowsL.filter(r => r.type === 'lane').map(r => r.ids.join(','));
      const p1 = v.bmGeo.pos.get(1), sRow = row('s'), lane = lay[lay.indexOf(sRow) + 1];
      const svgV = v.toSVG(), svgS = WaveLens.WaveSVG.toString(j);
      const old = WaveLens.parse({ signal: [{ name: 'a', wave: '0101' }], bookmarks: [{ n: 1, t: 1, label: 'Δ', to: 2 }, { n: 2, t: 3, label: 'mine' }] });
      await v.run([{ op: 'bookmark', n: 2, t: 110 * ns }]); const moved = v.toSVG();
      const out = { ids, below: !!lane && lane.row.type === 'lane' && p1[1] > sRow.y + sRow.h && p1[1] < lane.y + lane.h, json: v.bookmarks()[0].lift,
        texts: ['go', 'two', '40 ns', 'phase A', 'pulse'].map(t => [svgV.includes('>' + t), svgS.includes('>' + t)]), cyc: svgS.includes('>40 ns ? 4<'),
        moved: moved.includes('80 ns'), old: [old.arrows.map(a => a.label), old.bookmarks.map(b => b.label)], spans: v.spanList() };
      v.destroy && v.destroy(); el.remove(); return out; })()""")
    lanes = ','.join(r['ids']).split(',')
    check('b:q' in lanes and 'b:s:below' in lanes and r['below'] and r['json'] == 'below',
          f'a bookmark lifted "below": a lane under its row, the circle in it (in the JSON "below"); "lift": true above {r["ids"]} {r["below"]}')
    check(all(a and b for a, b in r['texts']) and r['cyc'], f'labels by the circles, {{dt}} {{cycles:clk}} filled ({{cycles}}: "?" in an exact view), the spans\' labels: in the viewer\'s picture and the static SVG {r["texts"]}')
    check(r['moved'] and r['old'] == [['Δ'], ['', 'mine']] and len(r['spans']) == 2,
          f'the arrow\'s {{dt}} follows a moved end (40 → 80 ns); an old bookmark with "to" keeps its label on the arrow {r["old"]}')


def find(page, P):
    v = page.locator('.wv').first
    q, cnt = v.locator('input.q'), v.locator('.find .cnt')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    pre = js('[...WaveLens.internal.peek(v).collapsed].sort((a, b) => a - b)')   # the folding before the search
    q.fill(P['fuzzy']); settle(page)
    names = js("[...v.found.keys()].map(r => r.name)")
    sub = lambda n: re.search('.*'.join(P['fuzzy']), n) is not None
    check(P['hit'] in names and all(sub(n) for n in names) and cnt.inner_text().startswith(f'{len(names)} found'),   # "· k not in the page" may follow
          f'fuzzy "{P["fuzzy"]}": letters in order, not contiguous {sorted(set(names))[:8]} ({cnt.inner_text()})')
    nf = len(names)
    marks = v.locator('.names .row .n b.fm').first.evaluate("b => b.closest('.n').innerHTML")
    check('<b class="fm">p</b>' in marks and '<b class="fm">v</b>' in marks, 'matched letters are marked in the names')
    folded = js("Object.keys(v.M.groups).length - WaveLens.internal.peek(v).collapsed.size")
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
        mid.append(js("""(() => { const q = WaveLens.internal.peek(v).namesEl.querySelector('.row.sel').getBoundingClientRect(), own = v.root.classList.contains('wv-scroll'),
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
    check(js('[...WaveLens.internal.peek(v).collapsed].sort((a, b) => a - b)') == pre, f'Open off: the folding from before the search is back ({len(pre)} folded)')
    v.locator('button[data-act=fopen]').click()
    v.locator('button[data-act=fselect]').click(); settle(page)
    fs = js("[[...v.selRun].every(r => v.found.has(r)), v.selRun.size, [...v.found.keys()].filter(r => r.type === 'sig' && r.tr && v.shown(r)).length, v.found.has(v.sel)]")
    mh, ug = js("(v.menu(300, 300, v.sel), ['.mh', 'button[data-m=ugnew]'].map(q => (document.querySelector('.wv-menu ' + q) || {}).textContent))")
    js('(v.closeMenu(), 0)')
    one = fs[1] == 1   # a page where the path finds one signal: the menu names it
    check(fs[0] and fs[1] == fs[2] >= 1 and fs[3] and (one and ug == 'New group with it' or f'{fs[1]} selected' in mh and f'New group of the {fs[1]}' in ug),
          f'Select: the found signals selected, the right button takes them all ({fs[1]}: "{mh}", "{ug}")')
    other = js("v.M.rows.find(r => r.type === 'sig' && r.tr && !v.found.has(r)).full")
    js(f"(v.select('{other}'), 0)"); v.locator('button[data-act=fselect]').click(modifiers=['Control']); settle(page)
    check(js(f"[v.selRun.size, [...v.selRun].some(r => r.full === '{other}')]") == [fs[1] + 1, True], 'ctrl+click Select: added to the selection there was')
    n0 = js('v.allRows().length'); v.locator('button[data-act=fmask]').click(); settle(page)
    mk = js("""(() => { const f = [...v.found.keys()], all = v.allRows(), ok = r => v.found.has(r) || r.anc.some(id => f.some(x => x.id === id && x.type === 'group')) ||
        (r.type === 'group' && f.some(x => x.anc.includes(r.id))); return [all.every(ok), all.filter(r => v.found.has(r)).length, f.length, all.length]; })()""")
    check(mk[0] and mk[1] == mk[2] and mk[3] < n0 and js('v.state().config.findMask'), f'Mask: the found rows and the modules on the way only ({mk[3]} of {n0} rows)')
    v.locator('button[data-act=fmask]').click(); settle(page)
    check(js('v.allRows().length') == n0, 'Mask off: every row again')
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
          and js('[...WaveLens.internal.peek(v).collapsed].sort((a, b) => a - b)') == want and js('v.t0') == t0 and y1 is not None and (abs(y1 - y0) <= 1 or end),
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
        for (const r of WaveLens.internal.peek(v).vis) { const p = r.anc.length ? r.anc[r.anc.length - 1] : -1;
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
    covered = page.evaluate(f"(() => {{ const M = WaveLens.parse(WAVES.{P['view']}); return M.rows.filter(r => r.type === 'sig' && r.full.includes('.{P['inst']}.')).length; }})()")
    check(v.locator('.names .row.hl').count() > 10 and v.locator('.names .row.dim').count() > 10, f'highlighting the instance {P["inst"]} ({covered} signals in it) dims the other rows')
    dev.locator('.mk').click()
    n0 = v.locator('.names .row').count()
    v.locator('button[data-act=collapse]').click()
    n1 = v.locator('.names .row').count()
    v.locator('button[data-act=expand]').click()
    n2 = v.locator('.names .row').count()
    check(n1 == 1 and n2 > n0, f'Collapse folds every instance, Expand opens all ({n0} -> {n1} -> {n2} rows)')
    same = page.evaluate(f"(() => {{ const M = WaveLens.parse(WAVES.{P['view']}), s = M.rows.filter(r => r.src && r.src.same); return [s.length, s.filter(r => r.tr.length > 2).length]; }})()")
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
    if ex == 'apb':   # bookmark 6 "at" an event (the build gave its time), the exact view's marker "on" an event object
        at = page.evaluate("""(async () => { const v = document.querySelector('.wv').waveView, b = v.bookmarks().find(b => b.n === 6),
            x = [...document.querySelectorAll('.wv')].map(e => e.waveView).find(w => w.M.markers.some(m => m.label === 'error'));
            const ok = [b && b.t, b && b.at, x && x.M.markers.find(m => m.label === 'error').t];
            const el = document.body.appendChild(document.createElement('div')), w = new WaveLens.WaveView(el, { signal: [{ name: 'a', tv: [[0, '0'], [10, '1']] }],
              bookmarks: [{ n: 1, t: 10, at: 'posedge a', signal: 'a' }, { n: 2, t: 10, at: { signal: 'a', edge: 'rise' } }] }, {});
            const kept = w.bookmarks().map(b => b.at); await w.run([{ op: 'bookmark', n: 1, t: 5 }]);
            const moved = w.bookmarks().map(b => b.at === undefined); w.destroy && w.destroy(); el.remove(); return [ok, kept, moved]; })()""")
        check(at == [[155000, 'posedge PSLVERR', 155000], ['posedge a', {'signal': 'a', 'edge': 'rise'}], [True, False]],
              f'apb: bookmark 6 at "posedge PSLVERR" (155 ns, its event kept), marker on an event; moved, the event goes {at}')
        # a bookmark's link: its button opens that view's section; with a bookmark number, that viewer goes to it
        lk = page.evaluate("""(async () => { const vs = WaveLens.views(), t = vs.find(v => v.root.dataset.wave === 'WAVES.transfers'),
            x = vs.find(v => v.root.dataset.wave === 'WAVES.exact'); window.scrollTo(0, 0);
            const li = t.notesEl.querySelector('li[data-n="6"] button[data-bm=link]'), info = li && [li.textContent.trim(), li.disabled];
            li.click(); await new Promise(r => setTimeout(r, 300)); const top = document.getElementById('exact').getBoundingClientRect().top;
            await x.run([{ op: 'bookmark', n: 9, t: '20ns', link: { view: 'transfers', bookmark: 3 } }, { op: 'bookmark', n: 8, t: '30ns', link: 'nowhere' }]);
            x.notesEl.querySelector('li[data-n="9"] button[data-bm=link]').click(); await new Promise(r => setTimeout(r, 300));
            const out = [info, Math.abs(top) < 5, t.cursor, t.bms.find(b => b.n === 3).t, x.notesEl.querySelector('li[data-n="8"] button[data-bm=link]').disabled];
            await x.run([{ op: 'bookmark', n: 9, delete: true }, { op: 'bookmark', n: 8, delete: true }]); return out; })()""")
        check(lk[0] == ['→ exact', False] and lk[1] and lk[2] == lk[3] and lk[4] is True,
              f'apb: bookmark 6\'s link "exact": its button scrolls to that section; a link with a bookmark moves that viewer to it; to no view: disabled {lk}')
    if ex == 'axi_lite':
        check(v.locator('.names .row.grp.hl').count() == 3 and v.locator('.names .row.dim').count() > 0, 'axi_lite: highlight of the write channels from the config')
        col = lambda n: v.locator('.names .row:not(.sva-g):not(.sva-step):not(.sva-copy)', has_text=n).first.locator('.n').evaluate('e => getComputedStyle(e).color')
        check([col('AWVALID'), col('WDATA'), col('RRESP')] == ['rgb(51, 154, 240)', 'rgb(55, 178, 77)', 'rgb(16, 152, 173)'],
              f'axi_lite: groupColors give every channel its colour ({col("AWVALID")}, {col("WDATA")}, {col("RRESP")})')
        svg = page.evaluate("""WaveLens.WaveSVG.toString({signal: [['g', {name: 'a', wave: '01'}, {name: 'b', wave: '10', color: '#ff0000'}], {name: 'c', wave: '01'}]},
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
        if (g) { g.anc.forEach(id => WaveLens.internal.peek(v).collapsed.delete(id)); v.renderNames(); v.cursor = 420000; v.draw(); }
        return g && [g.path, g.sig.width, v.M.rows.filter(r => r.anc.includes(g.id)).map(r => [r.name, r.width]), [100000, 420000, 905000].map(t => v.valueAt(g.sig, t)),
          v.valueAt(v.M.rows.find(r => r.full === 'fsm_tb.status.state'), 420000), v.vals && v.rowEl(g).querySelector('.v').textContent]; })()""")
    check(fv and fv[0] == 'fsm_tb.status' and fv[1] == 16 and [n for n, _ in fv[2]] == ['state', 'bit_cnt', 'valid', 'frame_err', 'data'] and [w for _, w in fv[2]] == [3, 3, 1, 1, 8]
          and fv[4] == 'STOP' and fv[5] == fv[3][1] and (not STRUCT_VALS or fv[3] == STRUCT_VALS),
          f'fsm_all (VCD + mkconfig --sv): the 16-bit status taken apart into its fields (state by name), the same whole values as the FST\'s struct scope {fv} {STRUCT_VALS}')


def deep(page, P):
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    check(js('Math.max(...v.M.rows.map(r => r.depth))') >= 8 and js('Object.keys(v.M.groups).length') > 200, 'every level of the hierarchy is on the page')
    js('(v.expandAll(), 0)')
    n, H, hc, ch = js('[WaveLens.internal.peek(v).vis.length, WaveLens.internal.peek(v).lay.H, v.hc, v.canvas.getBoundingClientRect().height]')
    check(n > 1700 and H > 32767 and hc == ch and hc < 1000, f'Expand: {n} rows, {H} px of rows, canvas only {ch:.0f} px (the visible part)')
    page.locator('.wv .body').first.evaluate('e => e.scrollTop = 20000'); settle(page)
    oy = js('WaveLens.internal.peek(v).oy')
    row = js(f"WaveLens.internal.peek(v).lay.find(o => o.row.type === 'sig' && o.y > {oy} + 100).row.full")
    check(oy == 20000 and js("document.querySelector('.wv canvas').getBoundingClientRect().top - document.querySelector('.wv .body').getBoundingClientRect().top") == 0,
          f'rows scroll under a canvas that stays in view (offset {oy}, first row {row})')
    js('(v.collapseAll(), 0)')


def modules(page, P):
    """The Modules panel (t, wavelens/src/modules.js) on the synthetic page: the tree of its 255 modules, a click goes to a
    module (opened, unhidden, its first signal in the middle), a box over names keeps Only those (the way to them as
    headers), ctrl / shift+click, Space, Only matches, pause and clear, the find outside Only, exports, undo, the state,
    the twin in tools/viewedit.py; then a tree of 10 000 modules against the clock."""
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    rows = page.locator('.wv-mods .mn')
    name = lambda n: page.locator('.wv-mods .mn', has_text=n).first.locator('.nm')
    toast = lambda: js("v.root.querySelector('.bar .toast').textContent")
    vis = lambda: js("WaveLens.internal.peek(v).vis.map(r => r.full || r.name)")
    page.locator('.wv canvas').first.click(); page.keyboard.press('t'); settle(page)
    first = [rows.nth(i).locator('.nm').inner_text() for i in range(rows.count())]
    check(page.locator('.wv-mods').count() == 1 and first == ['tb_top', 'dut_i', 'dev0_i', 'dev1_i'] and rows.nth(0).locator('.ct').inner_text() == '12 / 2060',
          f't opens the Modules panel: the modules two levels deep, the counts own / with the submodules {first} {rows.nth(0).locator(".ct").inner_text()}')
    js("(v.hide(['tb_top.dut_i.dev1_i']), 0)")
    name('dev1_i').click(); settle(page)
    got = js("[v.sel && v.sel.full, v.hiddenRows.size, WaveLens.internal.peek(v).vis.includes(v.sel)]")
    check(got == ['tb_top.dut_i.dev1_i.clk', 0, True] and toast().startswith('tb_top.dut_i.dev1_i'),
          f'a click on a module goes there: shown again (Hide), opened, its first signal selected {got} {toast()!r}')
    # a box over two names: Only those; the way to them stays as headers, their own signals go
    js("(v.highlight(['tb_top.tb_sig0']), 0)")
    a, b = rows.nth(2).bounding_box(), rows.nth(3).bounding_box()
    page.mouse.move(a['x'] + 120, a['y'] + 6); page.mouse.down(); page.mouse.move(b['x'] + 120, b['y'] + 12, steps=4)
    pv = page.locator('.wv-mods .mn.pv').count()
    page.mouse.up(); settle(page)
    got = js("v.onlyState()")
    shown = vis()
    check(pv == 2 and got == {'modules': ['tb_top.dut_i.dev0_i', 'tb_top.dut_i.dev1_i'], 'on': True} and shown[:2] == ['tb_top', 'tb_top.dut_i'] and
          'tb_top.tb_sig0' not in shown and 'tb_top.dut_i.cfg_reg0' not in shown and page.locator('.wv-mods .mn.on').count() == 2,
          f'a box over two names keeps Only them: the way to them as headers, the signals of the others gone (preview {pv}) {got} {shown[:4]}')
    chip = page.locator('.wv .bar button[data-act=onlyp]')
    check(chip.is_visible() and chip.inner_text() == 'Only: 2 modules ‖', f'the bar says it ({chip.inner_text()!r})')
    wd = page.evaluate("(() => { const v = document.querySelector('.wv').waveView; return JSON.stringify(v.toWaveDrom()); })()")
    check('tb_sig0' not in wd, 'a highlighted signal Only leaves out is not in WaveDrom')
    page.locator('.wv input.q').first.fill('cfg_reg'); settle(page)
    cnt = page.locator('.wv .find .cnt').first.inner_text()
    check('8 outside Only' in cnt, f'the find counts the matches Only leaves out ({cnt!r})')
    page.locator('.wv input.q').first.fill(''); page.locator('.wv canvas').first.click(); page.keyboard.press('Escape'); settle(page)
    js("(v.highlight(null), 0)")
    # ctrl+click: one in / out; a module under a picked one: said; shift+click: a run
    page.keyboard.press('t'); settle(page)
    name('dev1_i').click(modifiers=['Control']); settle(page)
    check(js("v.onlyState().modules") == ['tb_top.dut_i.dev0_i'], f'ctrl+click takes a module out of Only {js("v.onlyState().modules")}')
    name('dev0_i').click(); settle(page)   # in Only: a plain click only goes there
    name('dev1_i').click(); settle(page)   # outside Only: paused (kept), there
    got = js("[v.onlyState(), v.sel && v.sel.full]")
    check(got == [{'modules': ['tb_top.dut_i.dev0_i'], 'on': False}, 'tb_top.dut_i.dev1_i.clk'] and 'Only paused' in toast() and
          chip.inner_text() == 'Only paused: 1 module ▶', f'a click on a module outside Only pauses it (the set kept) and goes there {got} {chip.inner_text()!r}')
    chip.click(); settle(page)
    check(js("v.onlyState().on") and not js("WaveLens.internal.peek(v).vis.some(r => r.full && r.full.startsWith('tb_top.dut_i.dev1_i'))"),
          'the bar\'s Only ▶ resumes it')
    page.keyboard.press('Control+z'); settle(page)
    check(js("v.onlyState().on") is False, f'ctrl+Z takes Only back a step ({js("v.onlyState()")})')
    page.keyboard.press('Control+Shift+z'); settle(page)
    page.keyboard.press('t'); settle(page)
    name('dev0_i').click(modifiers=['Shift']); settle(page)   # the anchor: dev1_i (the last click)
    check(js("v.onlyState().modules") == ['tb_top.dut_i.dev0_i', 'tb_top.dut_i.dev1_i'], f'shift+click keeps Only the run {js("v.onlyState().modules")}')
    # the filter: Only matches (shift+Enter); keys in the tree
    q = page.locator('.wv-mods .mq'); q.fill('unit1'); settle(page)
    hits = page.locator('.wv-mods .mn.hit').count(); q.press('Shift+Enter'); settle(page)
    got = js("v.onlyState().modules")
    check(hits >= 11 and len(got) == hits, f'Only matches: the {hits} modules the filter finds ({len(got)})')
    page.evaluate("document.querySelector('.wv').waveView.run({op: 'only', modules: ['unit1_i', 'unit17_i']})")
    # ↓ ↓ ↓ Enter: dev0_i, on the way to unit1_i: its own signals left out, the first one of unit1_i selected
    q.fill(''); q.press('ArrowDown'); page.keyboard.press('ArrowDown'); page.keyboard.press('ArrowDown'); page.keyboard.press('Enter'); settle(page)
    sel = js("v.sel && v.sel.full") or ''
    check(sel.startswith('tb_top.dut_i.dev0_i.') and '.unit1_i.' in sel and 'Only paused' not in toast(),
          f'↓ Enter in the tree go to a module on the way to Only\'s: its first signal Only keeps ({sel})')
    page.keyboard.press(' '); settle(page)
    got = js("v.onlyState()")
    check(got['on'] and len(got['modules']) == 2 and got['modules'][0] == 'tb_top.dut_i.dev0_i' and got['modules'][1].endswith('.unit17_i'),
          f'Space puts the module into Only (unit1_i under it: in it) {got}')
    page.keyboard.press('Escape'); settle(page)
    check(page.locator('.wv-mods').count() == 0 and js("v.sel && v.sel.full") == sel and js("!!v.only"),
          'Esc in the panel closes it: no reset of the viewer, Only stays')
    # the state, the command, the twin
    st = js("v.state().only")
    miss = page.evaluate("(async () => { const v = document.querySelector('.wv').waveView; return v.setState({wavelens: 'state', version: 3, "
                         "only: {modules: ['tb_top.dut_i.dev1_i', 'tb_top.nope'], on: true}}); })()")
    check(st == got and miss == ['tb_top.nope'] and js("v.onlyState().modules") == ['tb_top.dut_i.dev1_i'],
          f'Only in the saved state and back (a path not of a module: said) {st} {miss}')
    ops = [{'op': 'only', 'modules': ['dev0_i', 'core1_i']}, {'op': 'select', 'signal': 'tb_top.tb_sig0'}, {'op': 'only', 'on': False},
           {'op': 'only', 'on': True}, {'op': 'only'}, {'op': 'unfold', 'all': True},
           {'op': 'select', 'signals': ['tb_top.dut_i.dev0_i.ready', 'tb_top.dut_i.dev1_i.ready']},
           {'op': 'fold', 'all': True}, {'op': 'only', 'modules': ['dev1_i', 'core3_i'], 'open': False}, {'op': 'only', 'modules': ['dev1_i', 'core3_i']}]
    res = page.evaluate("ops => document.querySelector('.wv').waveView.run(ops)", ops)
    sys.path.insert(0, str(ROOT / 'tools'))
    import viewedit
    py = viewedit.Editor(viewedit.Model(page.evaluate("WAVES.all"))).run(ops)
    pst = viewedit.Editor(viewedit.Model(page.evaluate("WAVES.all"))); pst.run(ops)
    jsf = sorted(js("v.state().config.fold")); pyf = sorted(pst.fold())
    check(jsf == pyf and 'tb_top.dut_i.dev1_i.core3_i' not in jsf and 'tb_top.dut_i.dev1_i' not in jsf and 'tb_top.dut_i.dev0_i' in jsf,
          f'the folding the command only leaves: the same in the page and in tools/viewedit.py ({len(jsf)} / {len(pyf)} folded)')
    check(res == py and res[0]['only'] == {'modules': ['tb_top.dut_i.dev0_i'], 'on': True} and res[1]['select'] is None and
          res[6]['select'] == 'tb_top.dut_i.dev0_i.ready',
          f'the command only: the same in the page and in tools/viewedit.py (a submodule of one picked: in it; a signal it leaves out: not selected) {res} {py}')
    bad = page.evaluate("document.querySelector('.wv').waveView.run([{op: 'only', modules: 'nope'}, {op: 'only', clear: true}])")
    check('no module "nope"' in bad[0].get('error', '') and bad[1]['only'] is None and not chip.is_visible(), f'a name that is no module: said; clear {bad}')
    # what Only leaves out stays out (review of the implementation, O1 O2 O4 O6 O7 O13)
    D0, D1 = 'tb_top.dut_i.dev0_i', 'tb_top.dut_i.dev1_i'
    got = page.evaluate(f"""(async () => {{ const v = document.querySelector('.wv').waveView, out = [];
        await v.run([{{op: 'only', modules: '{D0}'}}, {{op: 'select', signals: ['{D0}.ready', '{D1}.ready']}}]);
        out.push([...v.selRun].map(r => r.full), JSON.stringify(v.toWaveDrom()).includes('"ready"'), v.toWaveDrom().signal.length);
        await v.run([{{op: 'hide', signals: '{D0}.cnt'}}]); const r = await v.run([{{op: 'show', signals: '{D0}.cnt'}}, {{op: 'select', signal: '{D0}.cnt'}}]);
        out.push(r[1].select);
        await v.run([{{op: 'gaps', on: true, signals: '{D1}.err', only: true}}]); out.push(v.exportRows());
        await v.run([{{op: 'gaps', reset: true}}, {{op: 'highlight', clear: true}}, {{op: 'select', signal: null}}]);
        return out; }})()""")
    check(got[0] == [f'{D0}.ready'] and got[3] == f'{D0}.cnt' and got[4] == [],
          f'Only: a run of signals keeps the ones in the view, a batch show → select selects, gaps "only them" outside Only: no rows {got}')
    js("(v.highlight(['" + D0 + ".ready', '" + D1 + ".err']), v.menu(300, 300, v.M.rows.find(r => r.full === '" + D0 + ".ready')), 0)")
    hide = page.locator('.wv-menu button[data-m=hide]')
    label = hide.inner_text()
    hide.click()
    got = js("[...v.hiddenRows]")
    check(got == [f'{D0}.ready'], f'Hide of the highlighted rows leaves the ones Only takes away alone ({label!r} → {got})')
    js("(v.unhide(), v.highlight(null), v.hide(['" + D1 + "']), 0)")
    page.locator('.wv input.q').first.fill('err'); settle(page)
    n0 = js("v.found.size")
    js(f"(v.goScope('{D1}'), 0)"); settle(page)
    n1 = js("v.found.size")
    check(n1 > n0 and js("v.onlyState().on") is False and js("v.hiddenRows.size") == 0,
          f'a click on a module hidden and outside Only: shown, Only paused, the find finds what they left out ({n0} → {n1})')
    page.locator('.wv input.q').first.fill(''); settle(page)
    # the panel: opened and closed again, drawn once per change; a box below the names or cancelled with Esc changes nothing;
    # Hide replaced by another of the same size is drawn
    js(f"(v.setOnly({{modules: ['{D0}']}}), 0)")
    for _ in range(5):
        js('(v.modules(false), v.modules(true), 0)')
    renders = page.evaluate("""(() => { const v = document.querySelector('.wv').waveView, M = v.mods, R = M.render.bind(M); let n = 0;
        M.render = f => { n++; return R(f); }; v.select(v.M.rows.find(r => r.full.endsWith('dev0_i.cnt'))); return n; })()""")
    check(renders == 1 and page.locator('.wv-mods').count() == 1, f'the panel opened and closed five times: one panel, drawn once for a selection ({renders})')
    js('(v.collapseAll(), 0)'); settle(page)
    check(js('v.sel') is None and page.locator('.wv-mods .mn.cur').count() == 0, 'the selected signal folded away: its ● in the tree goes too')
    before = js('JSON.stringify(v.onlyState())')
    box = page.locator('.wv-mods .mtr').bounding_box(); last = rows.nth(rows.count() - 1).bounding_box()
    y0 = last['y'] + last['height'] + 10
    if y0 + 30 < box['y'] + box['height']:
        page.mouse.move(box['x'] + 150, y0); page.mouse.down(); page.mouse.move(box['x'] + 150, y0 + 30, steps=3); page.mouse.up(); settle(page)
    a = rows.nth(0).bounding_box(); page.locator('.wv-mods .mq').fill('dev'); settle(page)
    page.mouse.move(a['x'] + 150, a['y'] + 5); page.mouse.down(); page.mouse.move(a['x'] + 150, a['y'] + 40, steps=3)
    page.locator('.wv-mods .mq').focus(); page.keyboard.press('Escape'); page.mouse.up(); settle(page)
    check(js('JSON.stringify(v.onlyState())') == before and page.locator('.wv-mods .mq').input_value() == 'dev',
          f'a box over no name, a box cancelled by Esc (the focus in the filter): Only as it was {js("JSON.stringify(v.onlyState())")}')
    page.locator('.wv-mods .mq').fill(''); settle(page)
    js(f"(v.hide(['{D0}']), 0)"); settle(page)
    js(f"(v.setState({{wavelens: 'state', version: 3, hidden: ['{D1}']}}), 0)"); settle(page)
    struck = [rows.nth(i).locator('.nm').inner_text() for i in range(rows.count()) if 'hid' in (rows.nth(i).get_attribute('class') or '')]
    check(struck == ['dev1_i'], f'a hidden module replaced by another: the tree strikes the new one ({struck})')
    js("(v.unhide(), v.setOnly(null), v.modules(false), 0)")
    # the modules a box names open on the waves, the nested ones too (the set keeps the outermost), the way to them open,
    # the ones under them folded as they were; two subtrees: the way between them as headers
    js("(v.setOnly(null), v.modules(true), v.collapseAll(), v.mods.subtree(v.mods.roots[0], true), 0)"); settle(page)
    a, b = rows.nth(2).bounding_box(), rows.nth(5).bounding_box()   # dev0_i core0_i pipe0_i stage0_i
    page.mouse.move(a['x'] + 150, a['y'] + 6); page.mouse.down(); page.mouse.move(b['x'] + 150, b['y'] + 12, steps=4); page.mouse.up(); settle(page)
    got = js("[v.onlyState().modules, WaveLens.internal.peek(v).vis.filter(r => r.type === 'group' && !WaveLens.internal.peek(v).collapsed.has(r.id)).map(r => r.name), "
             "WaveLens.internal.peek(v).vis.filter(r => r.type === 'group' && WaveLens.internal.peek(v).collapsed.has(r.id)).map(r => r.name)]")
    check(got[0] == ['tb_top.dut_i.dev0_i'] and got[1] == ['tb_top', 'dut_i', 'dev0_i', 'core0_i', 'pipe0_i', 'stage0_i'] and
          got[2] == ['unit0_i', 'unit1_i', 'stage1_i', 'pipe1_i', 'core1_i'], f'a box opens every module it names and the way to them, the others stay folded {got}')
    r = page.evaluate("document.querySelector('.wv').waveView.run([{op: 'fold', all: true}, {op: 'only', modules: ['core1_i', 'core2_i']}])")
    got = js("[WaveLens.internal.peek(v).vis.filter(r => r.type === 'group' && !WaveLens.internal.peek(v).collapsed.has(r.id)).map(r => r.name), "
             "WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig').map(r => r.full.split('.').slice(-2, -1)[0])]")
    check(got[0] == ['tb_top', 'dut_i', 'dev0_i', 'core1_i', 'dev1_i', 'core2_i'] and set(got[1]) == {'core1_i', 'core2_i'},
          f'two subtrees: the modules between them open as headers only, the signals of the two picked {got}')
    # with the find and its Open on: Open goes off, so the next search does not fold the module again
    page.evaluate("document.querySelector('.wv').waveView.run([{op: 'find', query: 'cnt', open: true}, {op: 'only', modules: 'stage4_i'}])"); settle(page)
    got = js("[v.findOpen, WaveLens.internal.peek(v).collapsed.has(v.scopeOf(v.onlyState().modules[0]).id), v.q]")
    page.locator('.wv input.q').first.fill('cnt '); settle(page)
    got.append(js("WaveLens.internal.peek(v).collapsed.has(v.scopeOf(v.onlyState().modules[0]).id)"))
    check(got == [False, False, 'cnt', False], f'with the find\'s Open on: Open switched off, the module stays open while the query changes {got}')
    page.locator('.wv input.q').first.fill(''); settle(page)
    # the find's Open on when Only opens: the folding from before the search back (as the twin has it), then the picked opened;
    # open false: the folding as the search left it
    ops2 = [{'op': 'only', 'clear': True}, {'op': 'fold', 'all': True}, {'op': 'unfold', 'groups': ['tb_top', 'dut_i', 'dev0_i', 'core0_i']},
            {'op': 'find', 'query': 'stage5_i', 'open': True}, {'op': 'only', 'modules': 'dev0_i'}]
    page.evaluate("ops => document.querySelector('.wv').waveView.run(ops)", ops2); settle(page)
    tw = viewedit.Editor(viewedit.Model(page.evaluate("WAVES.all"))); tw.run(ops2)
    got = [sorted(js("v.state().config.fold")) == sorted(tw.fold()), js("WaveLens.internal.peek(v).collapsed.has(v.scopeOf('tb_top.dut_i.dev0_i.core0_i').id)"), js('v.findOpen')]
    check(got == [True, False, False], f'the find\'s Open on: the folding from before the search back, the modules picked open, as the twin has it {got}')
    page.evaluate("document.querySelector('.wv').waveView.run([{op: 'only', clear: true}, {op: 'find', query: 'stage5_i', open: true}])"); settle(page)
    before = js("[...WaveLens.internal.peek(v).collapsed].sort((a, b) => a - b).join()")
    page.evaluate("document.querySelector('.wv').waveView.run({op: 'only', modules: 'dev0_i', open: false})"); settle(page)
    check(js("[...WaveLens.internal.peek(v).collapsed].sort((a, b) => a - b).join()") == before and js('v.findOpen'), 'only … open: false with the find\'s Open on: the folding as it was')
    page.evaluate("document.querySelector('.wv').waveView.run([{op: 'find', query: ''}, {op: 'only', clear: true}])"); settle(page)
    folded = js("[...WaveLens.internal.peek(v).collapsed].length")
    page.evaluate("document.querySelector('.wv').waveView.run([{op: 'only', on: false}, {op: 'only', on: true}, {op: 'only', clear: true}])")
    check(js("[...WaveLens.internal.peek(v).collapsed].length") == folded, 'pause, resume and clear fold or open nothing')
    js("(v.expandAll(), 0)")
    js("(v.modules(false), 0)")
    # the panel's frame: a click on its text or a button keeps ↑ ↓ in the tree; its edges and corners size it, in the window,
    # not under its least size; closed and opened again: where it was, its size
    js("(v.panelBox = null, v.modules(true), 0)"); settle(page)
    foc = "document.activeElement.closest('.wv-mods .mn') && +document.activeElement.dataset.i"
    page.locator('.wv-mods .mh b').click(); page.keyboard.press('ArrowDown'); a = js(foc)
    page.locator('.wv-mods .ms').click(); page.keyboard.press('ArrowDown'); b = js(foc)
    page.locator('.wv-mods button[data-a=loc]').click(); settle(page); page.keyboard.press('Home'); c = js(foc)
    check([a, b, c] == [1, 2, 0], f'a click on the header, the status line, a button: ↓ Home go on in the tree {[a, b, c]}')
    pb = lambda: {k: round(x) for k, x in page.locator('.wv-mods').bounding_box().items()}
    def size(s, dx, dy):
        h = page.locator(f'.wv-mods .rz-{s}').bounding_box(); x, y = h['x'] + h['width'] / 2, h['y'] + h['height'] / 2
        page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x + dx, y + dy, steps=3); page.mouse.up(); return pb()
    b0 = pb(); b1 = size('nw', -40, -30); b2 = size('se', 30, 20); b3 = size('e', -5000, 0); b4 = size('n', 0, 9000)
    vw = page.viewport_size
    check(b1 == {'x': b0['x'] - 40, 'y': b0['y'] - 30, 'width': b0['width'] + 40, 'height': b0['height'] + 30} and
          (b2['width'], b2['height']) == (min(b1['width'] + 30, vw['width'] - b1['x']), min(b1['height'] + 20, vw['height'] - b1['y'])) and
          b3['width'] == 220 and b3['x'] == b2['x'] and b4['height'] == 160 and b4['y'] + 160 == b3['y'] + b3['height'] and
          js(foc) is not None, f'the corners and the edges size the panel, in the window, 220 × 160 at least, the focus in the tree {[b0, b1, b2, b3, b4]}')
    page.keyboard.press('Escape'); js("(v.modules(true), 0)"); settle(page)
    check(pb() == b4, f'closed and opened again: where it was, its size {pb()} {b4}')
    # sized wide, then a window made narrow (the drawer) and short: the drawer's own size, all of it in the window; a
    # smaller window that is not narrow: the panel back in it, no bigger than 96vw × 92vh
    vw = page.viewport_size; b5 = size('se', 2000, 2000)
    page.set_viewport_size({'width': 500, 'height': 420}); settle(page)
    dr = js("(() => { const b = v.mods.el.getBoundingClientRect(), t = v.mods.tree.getBoundingClientRect(); "
            "return [Math.round(b.width), Math.round(b.height), Math.round(t.bottom), innerHeight, Math.round(Math.min(innerWidth * 0.88, 340))]; })()")
    page.set_viewport_size({'width': 900, 'height': 500}); settle(page); sm = pb()
    page.set_viewport_size(vw); settle(page)
    check(dr[0] == dr[4] and dr[1] <= dr[3] and dr[2] <= dr[3] and sm['x'] >= 0 and sm['x'] + sm['width'] <= 900 and sm['y'] + sm['height'] <= 500
          and sm['width'] <= 864 and sm['height'] <= 460, f'sized wide, then a narrow window: the drawer\'s size, its tree in it; a smaller one: back in it {b5} {dr} {sm}')
    js("(v.modules(false), v.panelBox = null, 0)")
    # 10 000 modules: the panel opens, every one open, a filter
    t = page.evaluate("""(() => { const el = document.createElement('div'); document.body.append(el);
        const mk = (d, k) => d === 0 ? [`m${k}`, {name: 'a', wave: '01'}] : [`m${k}`, {name: 'a', wave: '01'}, ...Array.from({length: 10}, (_, i) => mk(d - 1, i))];
        const v = new WaveLens.WaveView(el, {signal: [mk(4, 0)]}), T = performance.now();
        v.modules(true); const t1 = performance.now(); v.mods.subtree(v.mods.roots[0], true); const t2 = performance.now();
        const n = [v.scopes().length, v.mods.rows.length, v.mods.el.querySelectorAll('.mn').length];
        v.mods.qEl.value = v.mods.q = 'm7 m3'; v.mods.render(); const t3 = performance.now();
        v.destroy(); el.remove(); return [t1 - T, t2 - t1, t3 - t2, ...n]; })()""")
    check(t[3] == 11111 and t[4] == 11111 and t[0] + t[1] + t[2] < 3000 * SCALE,
          f'{t[3]} modules: the panel opens in {t[0]:.0f} ms, all of them open in {t[1]:.0f} ms ({t[5]} rows), a filter in {t[2]:.0f} ms')


def big(page):
    t = page.evaluate('() => { const t0 = performance.now(); WaveLens.redrawAll(); return performance.now() - t0; }')
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
    near = js("""(() => { const k = v.pxPerT(), o = WaveLens.internal.peek(v).lay.find(o => o.row.type === 'sig' && o.row.tr && o.row.tr.some((e, i) => i && e.t > v.t0 + v.span * 0.1 && e.t < v.t0 + v.span * 0.9));
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
    sigs = js("WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig' && r.tr).map(r => r.full)"); keys.append([a == sigs[1], b == sigs[0], g1 == sigs[0], g2 == sigs[-1]])
    js('(v.select(WaveLens.internal.peek(v).vis.filter(r => r.type === "sig" && r.tr && r.tr.length > 3)[0]), v.cursor = v.M.t0, v.draw(), 0)')
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
    press('z', 'Shift+M'); vk.append(js('WaveLens.internal.peek(v).collapsed.size') == ng); press('z', 'Shift+R'); vk.append(js('WaveLens.internal.peek(v).collapsed.size') == 0)
    press('g', 'x'); vk.append(js('WaveLens.internal.peek(v).collapsed.size') == 0)   # an unknown sequence does nothing
    check(all(vk), f'vim: ]m [m next / previous bookmark round the ends, * finds the selected name, yy copies it, zM / zR fold / open every group ({ng}) {vk}')
    check(keys[:6] == [0.5, 0.5, True, 0.5, True, True] and all(keys[6]) and all(keys[7]) and keys[8] and keys[9],
          f'keys as in Questa: i o zoom in / out, f full, l the window before the last zoom (i i l: x0.5), End / Home, Tab / shift+Tab the next / previous edge (the focus stays; nothing selected: Tab leaves the waves); vim: j k, gg, G {keys}')
    # the value under the pointer
    c.scroll_into_view_if_needed(); box = c.bounding_box()
    y = js("(o => o.y + o.h / 2 - WaveLens.internal.peek(v).oy)(WaveLens.internal.peek(v).lay.find(o => o.row.name === 'state'))")
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
    n = page.evaluate("""(() => { let n = 0; const d = document.querySelector('#wv-t94'); d.addEventListener('wavelens:destroy', () => n++); d.remove(); WaveLens.upgrade(); return [n, WaveLens.views().includes(window.__t94)]; })()""")
    check(n == [1, False], f'a viewer whose element left the page is destroyed by the next upgrade (wavelens:destroy once, out of WaveLens.views()) {n}')
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
    el0 = js('WaveLens.internal.peek(v).namesEl.children[5] === WaveLens.internal.peek(v).rowEls[4]')
    t = page.evaluate("""(async () => { const v = document.querySelector('.wv').waveView, t = [], keep = WaveLens.internal.peek(v).rowEls[10];
        for (let i = 0; i < 5; i++) { const n = WaveLens.internal.peek(v).namesEl.querySelectorAll('.row:not(.grp) .n')[3 + i], t0 = performance.now(); n.click(); t.push(performance.now() - t0);
          await new Promise(r => requestAnimationFrame(r)); }
        t.sort((a, b) => a - b); return [t[2], WaveLens.internal.peek(v).rowEls[10] === keep, WaveLens.internal.peek(v).vis.length]; })()""")
    check(el0 and t[1] and t[0] < 10 * SCALE, f'a click on a name with {t[2]} rows takes {t[0]:.1f} ms (< {10 * SCALE:.0f}) and keeps the rows of the names column')
    q, body = page.locator('.wv').first.locator('input.q'), page.locator('.wv .body').first
    q.fill(P['fuzzy']); settle(page); q.press('Enter'); q.press('Enter'); settle(page)
    row = js('v.fiRow && v.fiRow.full'); y0 = js('v.rowTop(v.fiRow)')
    q.press('Escape'); settle(page)
    after = js('[WaveLens.internal.peek(v).collapsed.size, v.found.size]'); r = js(f"v.M.rows.find(x => x.full === '{row}')"); y1 = js(f"v.rowTop(v.M.rows.find(x => x.full === '{row}'))")
    check(after == [0, 0] and y0 is not None and y1 is not None and abs(y1 - y0) <= 1, f'Esc after find + Open: every module open again as before the search {after}; the row stepped to stays in place ({y0:.0f} -> {y1:.0f} px)')
    page.emulate_media(media='print'); page.evaluate("dispatchEvent(new Event('beforeprint'))")
    pr = js("[[...v.wcol.querySelectorAll('canvas.wv-print')].reduce((s, c) => s + c.getBoundingClientRect().height, 0), WaveLens.internal.peek(v).lay.H, getComputedStyle(v.bodyEl).overflowY, v.wcol.querySelectorAll('canvas.wv-print').length]")
    page.evaluate("dispatchEvent(new Event('afterprint'))"); page.emulate_media(media='screen'); settle(page)
    check(abs(pr[0] - pr[1]) < 1 and pr[2] == 'visible' and pr[3] >= 2 and js("v.wcol.querySelectorAll('canvas.wv-print').length") == 0,
          f'print: every row on {pr[3]} canvases ({pr[0]:.0f} of {pr[1]} px), no scroll box; afterprint gives the screen canvas back')
    wd = page.evaluate("""(() => { const ck = [], d8 = []; for (let c = 0; c < 3000; c++) { ck.push([10 * c, '0'], [10 * c + 5, '1']); d8.push([10 * c, (c % 256).toString(16)]); }
        const el = document.body.appendChild(document.createElement('div')), w = new WaveLens.WaveView(el, { signal: [{ name: 'clk', tv: ck },
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
        const el = document.body.appendChild(document.createElement('div')), w = new WaveLens.WaveView(el, { signal: [{ name: 'clk', tv: ck },
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
    r = page.evaluate("""(() => { const F = WaveLens, D = F.decode, warn = console.warn, warned = [];
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


def wavelens_units(page):
    """wavelens/wavelens.js is the concatenation of wavelens/src/*.js (make wavelens), and the pure functions of the model."""
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'wavelenscat.py'), '--check'], capture_output=True, text=True)
    check(r.returncode == 0, 'wavelens/wavelens.js is the concatenation of wavelens/src/*.js' + (': ' + r.stderr.strip() if r.returncode else ''))
    got = page.evaluate("""(() => { const F = WaveLens, M = F.parse({ signal: [{ name: 'clk', wave: 'p..' }, ['g', { name: 'b', wave: '=.=', data: 'A B' }, {}, { name: 'a', tv: [[0, '0'], [5, '1']] }]],
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
        check(got[k] == want[k], f'WaveLens pure functions, {k}: {got[k]}' + ('' if got[k] == want[k] else f' (want {want[k]})'))


def plugin_api(page):
    """The plugin API (stage 9.4): tokens, highlight tokens, tools, panels, rows, marks, listeners, keys with help,
    events, plugin groups that leave, enums by path; sva.js uses nothing else of the viewer."""
    import re as _re
    bad = []
    for f in ('sva.js', 'bus.js'):   # the two plugins: the API, not the viewer's fields (moveTo, fold, select, setCursor …)
        src = (ROOT / 'wavelens' / f).read_text()
        bad += [f'{f}: {p}' for p in ('.namesEl', ".bar .tools", "textContent === 'go to'", 'v.keys.', '.vis[+') if p in src]
        bad += [f'{f}: {m}' for m in _re.findall(r'\bv\.(?:t0|cursor|span|sel) = |\bv\.collapsed\.(?:add|delete)\(', src)]
    import re as _re2
    cfg_keys = set(_re2.findall(r'^ {2}(\w+):', (ROOT / 'wavelens' / 'wavelens.config.js').read_text(), _re2.M))
    lacking = sorted(cfg_keys - set(page.evaluate('Object.keys(WaveLens.defaults)')) - {'theme', 'colors', 'nameWidth', 'fontMono', 'fontBody'} - ({'busDetect', 'buses'} if not page.evaluate('!!window.WaveBus') else set()))
    check(not lacking, f'WaveLens.defaults has every setting of wavelens.config.js (the plugins register theirs: registerDefaults) {lacking}')
    own = sorted(set(_re.findall(r'\b\w+\.(?:lay|oy|vis|collapsed|rowEls|namesEl)\b', pathlib.Path(__file__).read_text())))
    check(not own, f'tests/smoke.py reads the fields of a viewer through WaveLens.internal.peek(v) only (one place to change) {own or ""}')
    check(not bad, f'sva.js and bus.js use the API only (none of {bad or "namesEl, .bar .tools, the go-to label, v.keys, vis[data-r], v.t0 / cursor / span / sel =, WaveLens.internal.peek(v).collapsed.add / delete"})')
    page.evaluate("""(() => { const d = document.createElement('div'); d.id = 'wv-api'; d.style.cssText = '--my-col: #123456; width: 900px'; document.body.appendChild(d);
        const M = { signal: [['tb', ['u', { name: 'state', path: 'tb.u.state', width: 2, tv: [[0, '0'], [10, '1']] }], ['w', { name: 'state', path: 'tb.w.state', width: 2, tv: [[0, '0'], [10, '1']] }]]],
          time: { t0: 0, cycle: 10, t1: 40 } };
        WaveLens.enums['tb.u.state'] = { 0: 'IDLE', 1: 'RUN' };
        const v = window.__api = new WaveView(d, M, { cursor: 20 }), ev = window.__ev = [];
        for (const n of ['cursor', 'view', 'select']) d.addEventListener('wavelens:' + n, () => ev.push(n));
        const row = { type: 'sig', name: 'plugin row', height: 20, draw: (P, o) => P.rect(o.xL, o.y, o.xR - o.xL, o.h, '--my-col') };
        v.extraRows.push(g => g && g.name === 'u' ? [row] : []); v.renderNames(); v.draw(); window.__row = row; })()""")
    t = lambda e: page.evaluate(f'(() => {{ const v = window.__api, row = window.__row; return {e}; }})()')
    px = page.evaluate("""(() => { const v = window.__api, o = WaveLens.internal.peek(v).lay.find(o => o.row === window.__row), d = devicePixelRatio || 1, c = v.canvas;
        return [...c.getContext('2d').getImageData(Math.round(c.width * 0.27), Math.round((o.y + o.h / 2 - WaveLens.internal.peek(v).oy) * d), 1, 1).data].slice(0, 3); })()""")
    check(px == [0x12, 0x34, 0x56], f'a plugin row paints in any custom property of the page ("--my-col"): {px}')
    reg = page.evaluate("(WaveLens.registerTokens({'my-tok': '--my-col'}), [WaveLens.registerTokens({})['my-tok'], 'sva-pass' in WaveLens.registerTokens({})])")
    check(reg == ['--my-col', True], f'WaveLens.registerTokens adds a colour name (sva.js registers its own) {reg}')
    hv = t("(v.extraPicks = new Map([[row, 'hl3']]), v.renderNames(), v.rowEl(row).style.getPropertyValue('--hl'))")
    check(hv == 'var(--wave-hl3)', f'extraPicks takes a token per row ({hv})')
    tools = t("""(() => { const a = v.addTool('go to', '<button type="button" class="t1">x</button>'), b = v.addTool('go to', '<button type="button" class="t2">y</button>');
        return [a === b, a.dataset.tg, a.querySelectorAll('button').length, a.querySelector('.tl').textContent]; })()""")
    panel = t("(() => { const p = document.createElement('div'); v.addPanel(p); return p.previousElementSibling === v.root.querySelector('.bar'); })()")
    check(tools == [True, 'go to', 2, 'go to'] and panel, f'addTool finds or makes a tool group by its label {tools}; addPanel puts a panel under the bar {panel}')
    rows = t("""(() => { const el = v.rowEl(row), y = WaveLens.internal.peek(v).lay.find(o => o.row === row).y + 2; return [v.rowAt(el) === row, v.rowAt(el.firstChild) === row, v.rowAt(y) === row, v.rowAt(document.body)]; })()""")
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
    check(ev == ['cursor', 'view', 'select'], f'events wavelens:cursor, wavelens:view, wavelens:select, once per change {ev}')
    en = t("[v.valueAt(v.M.rows.find(r => r.full === 'tb.u.state'), 15), v.valueAt(v.M.rows.find(r => r.full === 'tb.w.state'), 15)]")
    check(en == ['RUN', '1'], f'WaveLens.enums by full path: only tb.u.state gets the names {en}')
    gh = page.evaluate("""(() => { const d = document.createElement('div'); document.body.appendChild(d);
        const M = WaveLens.parse({ signal: [['g', { name: 'a', wave: '01' }]] }), mk = () => [{ type: 'group', name: 'p', id: WaveLens.rowId() }];
        const n = []; for (let i = 0; i < 3; i++) { WaveLens.WaveSVG.render(d, M, { extraRows: [g => g && g.name === 'g' ? mk() : []] }); n.push(Object.keys(M.groups).length); }
        d.remove(); delete WaveLens.enums['tb.u.state']; return n; })()""")
    check(gh == [2, 2, 2], f'the groups of SVG plugins leave the model when the figure is drawn again (groups after 3 renders {gh})')
    page.evaluate("(() => { const d = document.querySelector('#wv-api'); d.remove(); WaveLens.upgrade(); })()")


def api_docs(page):
    """docs/index.html § API is made from the exports: a line for every key of WaveLens and no line for a key that is not
    there; the viewer methods it lists exist; the settings table names every default."""
    got = page.evaluate("""(() => ({ keys: Object.keys(WaveLens).sort(), doc: Object.keys(WAVELENS_API).sort(),
        rows: document.querySelectorAll('#api-wavelens tr[data-api]').length, todo: document.querySelector('#api-wavelens').textContent.includes('not described yet'),
        view: Object.keys(VIEW_API).filter(k => typeof WaveView.prototype[k] !== 'function'),
        settings: Object.keys(WaveLens.defaults).filter(k => !document.querySelector('#api').parentElement.textContent.includes(k)) }))()""")
    check(got['keys'] == got['doc'] and got['rows'] == len(got['keys']) and not got['todo'],
          f'docs § API: one line per export of WaveLens ({len(got["keys"])}; not described: {sorted(set(got["keys"]) - set(got["doc"]))}, gone: {sorted(set(got["doc"]) - set(got["keys"]))})')
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
    page.evaluate("WaveLens.setTheme('white')")
    check(css('html', '--bg') == '#ffffff' and css(ex, '--wave-bus') == '#000000', 'WaveLens.setTheme("white") themes the page and all waves')
    check(px(ex, 5, 5) == [243, 244, 246], 'global white theme redraws existing viewers')
    page.evaluate("WaveLens.setColors({trace: '#ff0000'})")
    check(css(ex, '--wave-1') == '#ff0000', 'WaveLens.setColors applies to all waves')
    check(css('#ex-palette-view', '--wave-1') == '#7ee787', 'a wave with its own palette keeps it')
    page.evaluate("WaveLens.setColors({trace: null}); WaveLens.setTheme('auto')")
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
    page.wait_for_function("WaveLens.internal.peek(document.querySelector('.wv').waveView).vis.filter(r => (r.cls || '').startsWith('sva-expr')).length === 2")
    toast = v.locator('.bar .toast').inner_text()
    rows = js("return WaveLens.internal.peek(v).vis.filter(r => (r.cls || '').startsWith('sva-expr')).map(r => [r.name, r.tr.filter(o => o.k === '1').map(o => o.t)]);")
    check(rows == [['ƒ PSEL && !PREADY', [45000, 85000, 145000]], ['ƒ @(posedge PCLK) PSEL && PENABLE && !PREADY', [105000]]] and 'not found: nope' in toast,
          f'+ Row: two rows ƒ (the clocked one at the edge after its cycle); a name that is not there is said, no row {rows} {toast!r}')
    jtxt = page.evaluate("document.querySelector('.wv').waveView.extraJSON.map(f => f()).filter(Boolean).join('\\n')")
    page.reload(); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    page.wait_for_function("WaveLens.internal.peek(document.querySelector('.wv').waveView).vis.filter(r => (r.cls || '').startsWith('sva-expr') && r.tr.length).length === 2")
    v.locator('.names .row', has_text='ƒ PSEL && !PREADY').first.click()
    got = [inp.input_value()]
    v.locator('button[data-x=del]').click()
    got.append(js("return WaveLens.internal.peek(v).vis.filter(r => (r.cls || '').startsWith('sva-expr')).map(r => r.name);"))
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


WL_VERSION = (ROOT / 'VERSION').read_text().strip()   # the version the bar shows
READERS_BAD = {'backwards': 'time goes back', 'unsorted': 'time goes back', 'noend': 'no $enddefinitions'}
READ_PAGE = """t => { try { const r = WaveLens.vcdToWave(t), out = {};
    const walk = a => a.forEach(x => Array.isArray(x) ? walk(x.slice(1)) : (out[x.path] = { tv: x.tv, kind: x.kind || null, width: x.width || 1,
      enum: x.enum || null }));
    walk(r.doc.signal); return { sigs: out, t0: r.doc.time.t0 }; } catch (e) { return { err: String(e.message || e) }; } }"""


# a case of tests/unit/types/contract.json in the page -> {labels, fields, notes, run} put on by the types, or {error}
CONTRACT_JS = """cs => cs.map(c => { let sv; try { sv = WaveLens.svTypes(JSON.parse(JSON.stringify(c.types)), 'contract'); } catch (e) { return { error: true }; }
    const rows = c.signals.map(x => Object.assign({ name: x.path.split('.').pop(), path: x.path, width: x.width, tv: [[0, '0']] },
      x.kind === 'integer' ? { radix: 'signed' } : {},   // (the VCD reader's mark of an integer)
      x.enum ? { enum: Object.assign({}, x.enum) } : {}, x.fields ? { fields: x.fields } : {}));
    const notes = []; WaveLens.svApply({ signal: rows }, sv, notes);
    const labels = Object.fromEntries(rows.filter(r => r.svEnum).map(r => [r.path, r.enum]));
    const fields = Object.fromEntries(rows.filter(r => r.svFields).map(r => [r.path, r.fields]));
    const run = WaveLens.internal.svFingerprint(sv, c.date, new Set(c.modules || []));
    const missing = c.dump ? WaveLens.internal.svMissingNotes(sv, WaveLens.internal.svMissing(sv, c.dump.paths, new Set(c.dump.scopes))) : [];
    const out = { labels, fields, notes, run, missing };
    return Object.fromEntries(Object.entries(out).filter(([, v]) => (Array.isArray(v) ? v.length : Object.keys(v).length))); })"""


def gen_types_case(seed):
    """review VI T6: a types file and a dump's signals from a seed, for the twins side by side: roots the types have or not
    (tb, top, TOP above, other), elements of arrays (x[3], x.[2], x.[-1]), widths about 32, 53 and 64, enums with keys
    that do not fit, fields, a map, the row's own labels, a width that differs."""
    import random
    rnd = random.Random(seed)
    W = [1, 2, 3, 31, 32, 33, 53, 54, 63, 64]
    sigs, rows = {}, []
    for k in range(rnd.randint(1, 6)):
        w = rnd.choice(W)
        path = rnd.choice(['tb', 'dut']) + rnd.choice(['', '.u', '.u.core', f'.g[{k}]']) + f'.s{k}'
        if rnd.random() < 0.6:
            keys = {str(rnd.getrandbits(w + (1 if rnd.random() < 0.1 else 0))) for _ in range(rnd.randint(1, 4))}
            sigs[path] = {'width': w, 'enum': {x: f'L{x}' for x in sorted(keys)}}
        else:
            hi = rnd.randint(0, w - 1)
            sigs[path] = {'width': w, 'fields': [{'name': 'hi', 'msb': w - 1, 'lsb': hi}] + ([{'name': 'lo', 'msb': hi - 1, 'lsb': 0}] if hi else [])}
        top = rnd.choice(['', '', 'TOP.', 'other.', 'top.'])
        tail = rnd.choice(['', '', '[2]', '.[1]', '.[-1]'])
        row = {'path': top + path + tail, 'width': w if rnd.random() < 0.85 else w + 1}
        if rnd.random() < 0.15:
            row['enum'] = {'0': 'MINE'}
        rows.append(row)
    t = {'wavelens': 'types', 'signals': sigs}
    if rnd.random() < 0.3:
        t['map'] = {'top': rnd.choice(['tb', 'dut'])}
    return {'name': f'seed {seed}', 'types': t, 'signals': rows}


def tools_signals(f):
    """vcd2wavedrom.py --exact --hierarchy over every variable of the dump f -> ({path: signal, an alias with its tv}, stderr)"""
    import json
    sys.path.insert(0, str(ROOT / 'tools'))
    import dumpscan
    d = dumpscan.read(str(f), None)
    paths = [p for p, v in d.vars.items() if v.kind != 'event']
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'vcd2wavedrom.py'), '--waves', str(f), '--exact', '--hierarchy', '--signals', ','.join(paths)],
                       capture_output=True, text=True)
    if r.returncode:
        return None, r.stderr
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
    return tools, r.stderr


def page_vs_tools(f, got):
    """The page's read of f (READ_PAGE) against the tools' -> what differs ([] the same)."""
    tools, err = tools_signals(f)
    if tools is None or 'err' in got:
        return [f'page: {got.get("err")}, tools: {err.strip()[:80]}']
    bad = []
    for p, it in tools.items():
        pg = got['sigs'].get(p)
        if pg is None:
            bad.append(f'{p}: not in the page'); continue
        tv = pg['tv']
        if not tv or tv[0][0] > it['tv'][0][0]:   # the page starts at the first change, the tools at the window's start
            tv = [[it['tv'][0][0], None if pg['kind'] else 'x']] + tv
        fl = lambda q: [[float(t), v] for t, v in q]   # times above 2^53 ps: JavaScript numbers round them (dumpscan warns)
        if fl(tv) != fl(it['tv']) or pg['kind'] != it.get('kind') or pg['width'] != it.get('width', 1) or pg['enum'] != it.get('enum'):
            bad.append(f'{p}: page {tv[:4]} {pg["kind"]} w{pg["width"]}, tools {it["tv"][:4]} {it.get("kind")} w{it.get("width", 1)}')
    bad += [f'{p}: only in the page' for p in sorted(set(got['sigs']) - set(tools))[:3]]
    return bad


def gen_vcd(seed):
    """review VI T5: a small VCD from a seed and what it holds, written down apart from both readers -> (text, model:
    {path: {width, tv: [[ps, value as the tools write it]]}}, the paths an escaped name gives (the readers only)).
    Its parts: a timescale of four, a header $comment that names $enddefinitions and $var, a $date in UTF-8, buses of
    1-64 bits written short (b1: zero-extended, bx: all x), a vector declared bit by bit, one code under two names
    (an alias in another scope), an escaped name with é in it, an enum table, changes at one time on one line or many,
    $comment in the body, $dumpvars, values that never repeat the one before. The escaped name is in no model: the
    readers are compared with each other on it."""
    import random
    rnd = random.Random(seed)
    unit, step = rnd.choice([('1ns', 1000), ('10ps', 10), ('1ps', 1), ('100ns', 100000)])
    codes = (chr(33 + i) for i in range(90) if chr(33 + i) not in '#$')
    head = [f'$date Sa 24 Okt 2026 — été {seed} $end', f'$timescale {unit} $end']
    if rnd.random() < 0.7:
        head.insert(rnd.randint(0, 2), '$comment the header ends at $enddefinitions $end')
    head.append('$attrbegin misc 07 st_t 3 IDLE RUN DONE 00 01 10 1 $end')
    head.append('$scope module tb $end')
    sigs = []   # [code, width, path or None (escaped), kind: 'bit' | 'bus' | 'part']
    def var(w, name, path, kind='bus', code=None):
        c = code or next(codes)
        head.append(f'$var wire {w} {c} {name} $end')
        sigs.append([c, w, path, kind])
        return c
    var(1, 'clk', 'tb.clk', 'bit')
    for k in range(rnd.randint(1, 4)):
        w = rnd.choice([2, 3, 8, 13, 32, 64])
        var(w, f'v{k} [{w - 1}:0]', f'tb.v{k}')
    head.append('$attrbegin misc 07 "" 1 $end')
    var(2, 'state [1:0]', 'tb.state')
    parts = [var(1, f'd[{i}]', None, 'part') for i in range(4)]   # tb.d: one vector of 4 bits
    var(1, '\\esc$x\u00e9', None, 'bit')
    head.append('$scope module u $end')
    alias = sigs[1]
    head.append(f'$var wire {alias[1]} {alias[0]} alias [{alias[1] - 1}:0] $end')
    head += ['$upscope $end', '$upscope $end', '$enddefinitions $end']
    cur = {s[0]: None for s in sigs}
    def value(s):
        while True:
            if s[3] == 'part':
                v = rnd.choice('01')
            elif s[1] == 1:
                v = rnd.choice('01xz')
            else:
                v = rnd.choice(['x', 'z'] + [rnd.getrandbits(s[1])] * 6)
            if v != cur[s[0]]:
                return v
    def text(s, v):
        if s[1] == 1:
            return f'{v}{s[0]}'
        return f'b{v if isinstance(v, str) else format(v, "b")} {s[0]}'
    model = {s[2]: {'width': s[1], 'tv': []} for s in sigs if s[2]}
    model['tb.state']['enum'] = {'0': 'IDLE', '1': 'RUN', '2': 'DONE'}   # the table the $attrbegin before it names
    model['tb.u.alias'] = model[alias[2]]
    model['tb.d'] = {'width': 4, 'tv': []}
    body, t = [], 0
    for n in range(rnd.randint(5, 30)):
        moved = sigs if n == 0 else rnd.sample(sigs, rnd.randint(1, len(sigs)))
        toks = []
        for s in moved:
            v = value(s); cur[s[0]] = v; toks.append(text(s, v))
            if s[2]:
                hx = v if isinstance(v, str) and s[1] > 1 else (v if s[1] == 1 else format(v, f'0{(s[1] + 3) // 4}x'))
                model[s[2]]['tv'].append([t * step, hx])
        if n == 0 or any(s[3] == 'part' for s in moved):
            model['tb.d']['tv'].append([t * step, format(int(''.join(cur[c] for c in reversed(parts)), 2), 'x')])
        if n == 0:
            body += [f'#{t}', '$dumpvars', *toks, '$end']
        elif rnd.random() < 0.3:
            body.append(f'#{t} ' + ' '.join(toks))
        else:
            body += [f'#{t}', *toks]
        if rnd.random() < 0.15:
            body.append('$comment in the body: $var $end')
        t += rnd.randint(1, 7)
    return '\n'.join(head + body) + '\n', model


def vscode_tab(browser, build):
    """The VS Code extension's tab (vscode/media/host.js before the viewer) under the CSP of vscode/extension.js, with a
    fake acquireVsCodeApi answering as the extension host does: the dump fetched by its URI and opened (an enum table
    read), localStorage as the dump's store (given, then each write posted), Save state -> a save of the .view.json,
    Load… -> a pick whose file is loaded, Open… -> a pick for a tab of its own, the clipboard, "changed" read again by
    itself, the live link's EventSource and POSTs relayed with the dump's path; no CSP violation."""
    import base64, json, time, urllib.parse
    print('vscode: the extension\'s tab (host.js) with a fake VS Code')
    src = 'https://wavelens.test'
    files = {'/host.js': ROOT / 'vscode' / 'media' / 'host.js', '/dump.vcd': ROOT / 'tests' / 'unit' / 'vcd' / 'enum.vcd'}
    files.update({'/media/' + f: ROOT / 'wavelens' / f for f in ('wavelens.css', 'wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js')})
    ext = (ROOT / 'vscode' / 'extension.js').read_text(encoding='utf-8')
    csp = re.search(r'content="(default-src[^"]+)"', ext).group(1).replace('${src}', src).replace('${nonce}', 'N0NCE')
    host = {'name': 'enum.vcd', 'path': '/host/dumps/enum.vcd', 'store': {'wavelens.given': 'yes'}, 'autoReload': False, 'keysLeft': ['ctrl+G'],
            'build': {'branch': 'dev', 'commit': 'abc1234', 'dirty': True, 'by': 'the extension of the repository'}}
    scripts = ''.join(f'<script nonce="N0NCE" src="{src}/media/{f}"></script>' for f in ('wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js'))
    html = (f'<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="{csp}">'
            '<style>kbd { color: #ccc; background-color: rgba(128, 128, 128, 0.17); padding: 1px 3px; }'   # VS Code's webview styles
            ' code { color: #d7ba7d; background-color: rgba(10, 10, 10, 0.4); padding: 1px 3px; }</style>'
            f'<link rel="stylesheet" href="{src}/media/wavelens.css"></head><body class="vscode-light">'
            f'<script type="application/json" id="wavelens-host">{json.dumps(host)}</script>'
            '<script type="application/wavedrom">{ "signal": [{ "name": "reading…", "wave": "x..." }] }</script>'
            f'<script nonce="N0NCE" src="{src}/host.js"></script>{scripts}</body></html>')
    fake = """(() => { window.__sent = []; const reply = m => setTimeout(() => window.postMessage(m, '*'), 0);
      window.acquireVsCodeApi = () => ({ getState() {}, setState() {}, postMessage(m) { window.__sent.push(m);
        if (m.type === 'source') reply({ id: m.id, src: '%s' + (window.__LAZY ? '/head.vcd' : window.__DUMP || '/dump.vcd'), name: 'enum.vcd', lazy: !!window.__LAZY });
        if (m.type === 'codes') window.lazyCodes(m.codes).then(text => reply({ id: m.id, text }));
        if (m.type === 'save') reply(window.__cancel ? { id: m.id, cancel: true } : { id: m.id, path: '/host/dumps/' + m.name });
        if (m.type === 'clip') reply({ id: m.id, ok: true });
        if (m.type === 'sources') reply(window.__TYPES ? { id: m.id, types: window.__TYPES, typesName: 'enum.types.json', texts: [] } : { id: m.id,
          texts: window.__SRC || ['package p; typedef enum logic [1:0] {OFF, ON = 2, HOLD} mode_t; endpackage', 'module m; p::mode_t plain, state; endmodule'] });
        if (m.type === 'pick') reply({ id: m.id, files: /fst/.test(m.accept) ? [] : [{ name: 's.view.json', mtime: 1, b64: btoa(JSON.stringify(window.__S)) }] });
        if (m.type === 'http') reply({ id: m.id, status: 200, text: 'ok' }); } }); })();""" % src
    page = browser.new_page()
    errs = []
    page.on('console', lambda m: errs.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.add_init_script(fake + "document.addEventListener('securitypolicyviolation', e => window.__csp = (window.__csp || []).concat(e.violatedDirective + ' ' + e.blockedURI));")
    dump2 = (ROOT / 'tests' / 'unit' / 'vcd' / 'enum.vcd').read_text().replace('b11 #', 'b1 #')   # the run of after "changed": tb.plain 1 at 5 ns, not 3
    page.route(src + '/**', lambda r: r.fulfill(path=str(files[urllib.parse.urlparse(r.request.url).path])) if urllib.parse.urlparse(r.request.url).path in files
               else r.fulfill(status=404))
    page.route(src + '/', lambda r: r.fulfill(body=html, content_type='text/html'))
    page.route(src + '/dump2.vcd', lambda r: r.fulfill(body=dump2, content_type='text/plain'))   # (the last route first)
    page.goto(src + '/')

    def until(expr, timeout=5000):   # wait_for_function evaluates a string: the CSP refuses it (no 'unsafe-eval')
        end = time.monotonic() + timeout / 1000
        while not page.evaluate(expr):
            if time.monotonic() > end:
                raise TimeoutError(f'not true in {timeout / 1000} s: {expr}')
            page.wait_for_timeout(50)
    until("window.__sent && window.__sent.some(m => m.type === 'ready')", timeout=15000)
    sent = lambda t: page.evaluate(f"window.__sent.filter(m => m.type === '{t}')")
    ready = sent('ready')[0]
    js = lambda e: page.evaluate(f"(async () => {{ const v = WaveLens.views().find(x => x.root.isConnected); return {e}; }})()")
    check(ready.get('shown') == 4 and ready.get('name') == 'enum.vcd', f'the dump fetched and opened: {ready}')
    check(js("WaveLens.internal.peek(v).vis.filter(r => r.enum).map(r => r.full).join(',')") == 'tb.state,tb.plain,tb.st.s', 'its enum tables on the rows')
    lab = js("[...new Set(WaveLens.internal.peek(v).vis.find(r => r.full === 'tb.plain').tr.map(o => o.v))].concat(WaveLens.internal.peek(v).vis.find(r => r.full === 'tb.state').enum[0])")
    check(lab[-1] == 'IDLE' and set(lab[:-1]) <= {'OFF', 'ON', 'HOLD'} and len(lab) > 1,
          f'wavelens.sources: the workspace\'s typedef enum names a VCD\'s bus without a table; the dump\'s own table stays ({lab})')
    # the workspace's sources gone (review IV A6): ⟳ takes their names away; the ones picked with Sources… stay and win a name
    labels = "(() => { const v = WaveLens.views().find(x => x.root.isConnected), r = n => WaveLens.internal.peek(v).vis.find(x => x.full === n); " \
             "return [r('tb.plain').enum ? Object.values(r('tb.plain').enum).join(',') : null, r('tb.state').enum[0]]; })()"
    n0 = len(sent('loaded'))
    page.evaluate("window.__SRC = []; window.postMessage({ type: 'reload' }, '*')"); until(f"window.__sent.filter(m => m.type === 'loaded').length > {n0}", timeout=5000)
    gone = page.evaluate(labels)
    page.evaluate("(async () => { const v = WaveLens.views().find(x => x.root.isConnected); await v.setSources(['module m; typedef enum logic [1:0] {P0, P1, P2, P3} q_t; q_t plain; endmodule'], true); })()")
    until("(v => v && WaveLens.internal.peek(v).vis.some(r => r.full === 'tb.plain' && r.enum))(WaveLens.views().find(x => x.root.isConnected))", timeout=5000)
    n0 = len(sent('loaded'))
    page.evaluate("window.__SRC = null; window.postMessage({ type: 'reload' }, '*')"); until(f"window.__sent.filter(m => m.type === 'loaded').length > {n0}", timeout=5000)
    both = page.evaluate(labels)
    check(gone == [None, 'IDLE'] and both == ['P0,P1,P2,P3', 'IDLE'], f'the workspace\'s sources gone: no names; picked ones stay over the workspace\'s {gone} {both}')
    # enum.types.json beside the dump (the extension reads it, by path): its table on tb.plain, the names of the picked sources not
    # used beside it; gone again: the sources as before
    n0 = len(sent('loaded'))
    page.evaluate("""window.__TYPES = JSON.stringify({ wavelens: 'types', version: 1, signals: { 'tb.plain': { width: 2, enum: { 0: 'T0', 1: 'T1', 2: 'T2', 3: 'T3' } },
        'tb.other': { width: 2, enum: { 0: 'NO' } } } }); window.postMessage({ type: 'reload' }, '*')""")
    until(f"window.__sent.filter(m => m.type === 'loaded').length > {n0}", timeout=5000)
    typed = page.evaluate(labels)
    n0 = len(sent('loaded'))
    page.evaluate("window.__TYPES = null; window.postMessage({ type: 'reload' }, '*')"); until(f"window.__sent.filter(m => m.type === 'loaded').length > {n0}", timeout=5000)
    check(typed == ['T0,T1,T2,T3', 'IDLE'] and page.evaluate(labels) == ['P0,P1,P2,P3', 'IDLE'],
          f'the types beside the dump: tb.plain by its path, not the sources\' name; gone: the sources again {typed}')
    check(js("localStorage.getItem('wavelens.given')") == 'yes' and js("(localStorage.setItem('wavelens.k', 'v'), localStorage.getItem('wavelens.k'))") == 'v' and
          any(m['key'] == 'wavelens.k' and m['value'] == 'v' for m in sent('store')), 'localStorage: the store given, a write posted')
    js("(v.saveState(), 0)"); until("window.__sent.some(m => m.type === 'save')", timeout=5000); settle(page)
    sv = sent('save')[0]
    check(sv['name'].endswith('.view.json') and 'wavelens' in json.loads(base64.b64decode(sv['b64'])), f'Save state: a save of {sv["name"]} with the state')
    st = json.loads(base64.b64decode(sv['b64']))
    st['bookmarks'] = [{'n': 4, 't': 10000, 'text': 'from the file'}]
    page.evaluate('s => { window.__S = s; }', st)
    js("(v.sfile.click(), 0)"); until("WaveLens.views().find(x => x.root.isConnected).state().bookmarks.some(b => b.text === 'from the file')", timeout=5000)
    check(sent('pick')[0]['accept'].startswith('.json'), 'Load…: a pick of a .json, its state loaded (a bookmark from the file)')
    n = len(sent('pick'))
    js("(v.openDump(), 0)"); until(f"window.__sent.filter(m => m.type === 'pick').length > {n}", timeout=5000)
    check('.fst' in sent('pick')[-1]['accept'] and not page.evaluate('!!window.showOpenFilePicker'), 'Open…: a pick of a dump (no showOpenFilePicker)')
    js("navigator.clipboard.writeText('PSEL')")
    check(any(m.get('text') == 'PSEL' for m in sent('clip')), 'the clipboard through VS Code')
    # review VI T9: "changed" fetches the dump once more and reads it: one more source and load than before, the new values
    plain = "(v => v.M.rows.find(r => r.full === 'tb.plain').tr.map(o => o.raw).join(','))(WaveLens.views().find(x => x.root.isConnected))"
    was, n_src, n_load = page.evaluate(plain), len(sent('source')), len(sent('loaded'))
    page.evaluate("window.__DUMP = '/dump2.vcd'; window.postMessage({ type: 'changed', auto: true }, '*')")
    until(f"window.__sent.filter(m => m.type === 'loaded').length > {n_load}", timeout=5000)
    now = page.evaluate(plain); page.evaluate("window.__DUMP = null")
    check(len(sent('source')) == n_src + 1 and len(sent('loaded')) == n_load + 1 and was != now,
          f'changed with autoReload: the dump fetched once more and its new values shown ({was} -> {now})')
    page.evaluate("window.postMessage({ type: 'live', link: '8742:tok123' }, '*')")
    until("window.__sent.some(m => m.type === 'es-open')", timeout=5000)
    es = sent('es-open')[0]
    page.evaluate(f"window.postMessage({{ type: 'es', sid: {es['sid']}, event: 'open' }}, '*')")
    until("window.__sent.some(m => m.type === 'http' && /hello/.test(m.url))", timeout=5000)
    hello = next(m for m in sent('http') if '/hello' in m['url'])
    check(es['url'].startswith('http://127.0.0.1:8742/events?token=tok123') and json.loads(hello['body'])['path'] == host['path'],
          'live: the EventSource and the hello relayed, the page named by the dump\'s path')
    page.evaluate("window.postMessage({ type: 'es', sid: %d, event: 'cmd', data: JSON.stringify({ rid: 5, ops: [{ op: 'marker', t: 20000 }] }) }, '*')" % es['sid'])
    until("window.__sent.some(m => m.type === 'http' && /reply/.test(m.url))", timeout=5000)
    rep = json.loads(next(m for m in sent('http') if '/reply' in m['url'])['body'])
    check(rep.get('rid') == 5 and rep['results'][0].get('op') == 'marker', f'live: a command run, its answer posted ({rep})')
    check(page.evaluate("document.documentElement.dataset.theme") == 'light', 'the theme from VS Code\'s body class')
    page.evaluate("document.body.className = 'vscode-dark'"); settle(page)
    check(page.evaluate("document.documentElement.dataset.theme") == 'dark', 'and again when VS Code\'s theme changes')
    # wavelens.theme: one of the viewer's whatever VS Code's kind; vscode: VS Code's own colours (its --vscode-* on <html>)
    page.evaluate("window.postMessage({ type: 'theme', theme: 'white' }, '*')"); settle(page)
    check(page.evaluate("[document.documentElement.dataset.theme, getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()]") ==
          ['white', '#ffffff'], 'wavelens.theme white: the white theme in a dark VS Code')
    page.evaluate("""document.documentElement.style.setProperty('--vscode-editor-background', '#102030');
      document.documentElement.style.setProperty('--vscode-editor-foreground', '#e0e0d0');
      document.documentElement.style.setProperty('--vscode-sideBar-background', '#182838');
      window.postMessage({ type: 'theme', theme: 'vscode' }, '*')"""); settle(page)
    look = page.evaluate("""(() => { const h = document.documentElement, c = getComputedStyle(h), v = WaveLens.views().find(x => x.root.isConnected),
      cv = v.root.querySelector('canvas'), d = window.devicePixelRatio || 1, p = cv.getContext('2d').getImageData(5 * d, cv.height - 3 * d, 1, 1).data;
      return [h.dataset.theme, h.classList.contains('wl-vscode'), c.getPropertyValue('--bg').trim(), c.getPropertyValue('--wave-1').trim(), [...p.slice(0, 3)]]; })()""")
    check(look[:4] == ['dark', True, '#102030', '#e0e0d0'] and look[4] in ([16, 32, 48], [24, 40, 56]), f'wavelens.theme vscode: VS Code\'s colours on the waves ({look})')
    page.evaluate("window.postMessage({ type: 'theme', theme: 'auto' }, '*')"); settle(page)
    check(page.evaluate("[document.documentElement.dataset.theme, document.documentElement.classList.contains('wl-vscode')]") == ['dark', False],
          'wavelens.theme auto: by VS Code\'s kind again')
    # VS Code's webview styles kbd and code by its theme: the viewer's own (a tooltip's keys) keep the viewer's colours
    tip = page.evaluate("""() => { const t = document.createElement('div'); t.className = 'wv-tip'; t.innerHTML = '<kbd>z</kbd><code>c</code>';
      document.querySelector('.wv').append(t); const c = e => getComputedStyle(e), r = [c(t).color, c(t.firstChild).color,
      c(t.lastChild).color, c(t.lastChild).backgroundColor]; t.remove(); return r; }""")
    check(tip[0] == tip[1] == tip[2] and tip[3] == 'rgba(0, 0, 0, 0)', f'a tooltip\'s keys in its own colour, not VS Code\'s ({tip})')
    # VS Code's webview listens on its window and gives every keydown to the workbench: the viewer's own keys stop before
    page.evaluate("window.__fwd = []; window.addEventListener('keydown', e => window.__fwd.push((e.ctrlKey ? 'ctrl+' : '') + (e.altKey ? 'alt+' : '') + e.key))")
    page.locator('.wv canvas').first.click()
    for k in ('Control+g', 'Escape', 'Alt+ArrowDown', 'Control+z', 'Control+p', 'F1', 'Control+Shift+F', 'Control+Shift+G'):
        page.keyboard.press(k)
        page.keyboard.press('Escape')
    fwd = page.evaluate('window.__fwd')
    check('ctrl+g' in fwd and 'ctrl+z' not in fwd and 'ctrl+p' in fwd and 'F1' in fwd and fwd.count('ctrl+F') == 1 and fwd.count('ctrl+G') == 1,
          f'keys: the viewer\'s stay in the tab; the rest (ctrl+shift+F / G too) and wavelens.keysToVSCode\'s ctrl+G go to VS Code ({fwd})')
    # ctrl+G is VS Code's there: gl lists the groups; the bar's version line has the extension's build; ◐ asks VS Code's list of themes
    page.locator('.wv canvas').first.click(); page.keyboard.press('g'); page.keyboard.press('l'); settle(page)
    gl = page.evaluate("!!document.querySelector('.wv .wv-menu')"); page.keyboard.press('Escape')
    ver = page.evaluate("[document.querySelector('.wv .bar .ver').textContent, document.querySelector('.wv .bar .ver').title]")
    page.locator('.wv button[data-act=theme]').first.click(); settle(page)
    check(gl and ver[0] == WL_VERSION + ' · dev@abc1234*' and 'with changes not committed' in ver[1] and sent('theme'),
          f'VS Code: gl opens the groups list; the build in the bar ({ver}); ◐ asks the extension for its list of themes ({sent("theme")})')
    # the assertions in the page under the CSP: the engine inlined (wasm-unsafe-eval) and in a Web Worker from a Blob
    sv = page.evaluate("""async () => { await SVA.loadFiles([{ name: 't.sva', text: 'module t (input logic clk, input logic [1:0] state); ' +
        'a_st: assert property (@(posedge clk) state != 2\\'d3); endmodule' }]); await SVA.ready();
      const p = SVA.panels()[0], out = [];
      for (const lim of [100000, 0]) { SVA.syncLimit = lim; const b = p.bind('a_st', 'tb'); await SVA.ready(); await p.queue;
        out.push([b.via || 'page', b.state, b.error || b.workerError || null, b.results ? b.results.assertions[0].stats.pass : null]); p.unbind(b); }
      SVA.syncLimit = null; return out; }""")
    check([x[0] for x in sv] == ['page', 'worker'] and all(x[2] is None and x[3] for x in sv), f'assertions in the page and in a worker under the CSP ({sv})')
    # a large dump (the extension's wavelens.lazy): its FST's header, then the signals shown read through "codes" (sva vcd
    # --codes of the FST), the top level open; an assertion reads its signals first: the same counts as from the whole dump
    import shutil, tempfile
    exe = build / 'sva-target' / 'release' / 'sva'
    if need(exe, how='make sva-build'):
        tmp = pathlib.Path(tempfile.mkdtemp(prefix='wl-lazy-')); shutil.copy(files['/dump.vcd'], tmp / 'enum.vcd')
        subprocess.run([exe, 'fst', str(tmp / 'enum.vcd'), '--no-types', '-q'], check=True)
        (tmp / 'head.vcd').write_text(subprocess.run([exe, 'vcd', str(tmp / 'enum.fst'), '--header'], capture_output=True, text=True, check=True).stdout)
        files['/head.vcd'] = tmp / 'head.vcd'
        page.expose_function('lazyCodes', lambda codes: subprocess.run([exe, 'vcd', str(tmp / 'enum.fst'), '--codes', '-'], input='\n'.join(codes),
                                                                        capture_output=True, text=True).stdout)
        n0 = len(sent('loaded'))
        page.evaluate("window.__LAZY = true; window.__TYPES = null; window.__SRC = []; window.postMessage({ type: 'reload' }, '*')")
        until(f"window.__sent.filter(m => m.type === 'loaded').length > {n0}", timeout=5000)
        until("(v => v && v.lazy && !WaveLens.internal.peek(v).vis.some(r => r.lazy))(WaveLens.views().find(x => x.root.isConnected))", timeout=5000)
        lz = [js("v.M.rows.filter(r => r.type === 'sig').length"), js("v.M.rows.filter(r => r.lazy).map(r => r.full)"), len(sent('codes'))]
        sv2 = page.evaluate("""async () => { const p = SVA.panels()[0], b = p.bind('a_st', 'tb'); await SVA.ready(); await p.queue;
          const out = [b.state, b.error || null, b.results ? b.results.assertions[0].stats.pass : null]; p.unbind(b); return out; }""")
        check(lz[0] >= 4 and lz[1] == [] and lz[2] >= 1 and sv2 == ['bound', None, sv[0][3]],
              f'a large dump: its header first, the signals on the screen read through "codes" (a struct\'s header: its fields, for its whole value); '
              f'an assertion reads its own (the counts of the whole dump) {lz} {sv2} / {sv[0][3]}')
        page.evaluate("window.__LAZY = false")
        shutil.rmtree(tmp, ignore_errors=True)
    # a save cancelled in the dialog: no "saved"
    page.evaluate("window.__cancel = true")
    js("(v.saveState(), 0)"); page.wait_for_timeout(400)
    check(js("v.root.querySelector('.bar .toast').textContent") == 'not saved', 'a save cancelled says so')
    check(not page.evaluate('window.__csp || []') and not errs, f'no CSP violation, no error: {page.evaluate("window.__csp || []")} {errs[:3]}')
    page.close()


def readers(browser, build):
    """The page's VCD reader (WaveLens.vcdToWave, wavelens/src/vcd.js) and the tools' (vcd2wavedrom.py --exact over
    dumpscan.py) give the same transitions, kinds and widths for every fixture of tests/unit/vcd: one rule for
    references, merged codes, vectors in parts (bits, ranges apart, two bits under one code), texts (realtime …, inf,
    nan), VHDL values, tokens apart by any white space, comments in the body, x / z, enum tables; the dumps the tools refuse the
    page refuses too."""
    import json
    sys.path.insert(0, str(ROOT / 'tools'))
    import dumpscan
    print('readers: the page\'s VCD reader against the tools\'')
    page = browser.new_page()
    page.goto('about:blank'); page.add_script_tag(path=str(ROOT / 'wavelens' / 'wavelens.js'))
    fixtures = sorted((ROOT / 'tests' / 'unit' / 'vcd').glob('*.vcd'))
    # a File read in pieces (vcdToWaveFile, review V X3: never all of it in memory) is read as its text at once: every fixture
    # cut into pieces of 1, 3, 7 and 64 characters (a token, a value and its code, a $comment, a character of UTF-8 cut in
    # two): the same doc, notes and their lines, the same error
    cut = page.evaluate("""async ts => { const out = [];
        const one = r => JSON.stringify(r, (k, v) => (k === 'size' ? undefined : v));
        for (const [name, t] of ts) { let a; try { a = one(WaveLens.vcdToWave(t)); } catch (e) { a = 'error ' + e.message + ' ' + e.line; }
          for (const n of [1, 3, 7, 64]) { let b; try { b = one(await WaveLens.vcdToWaveFile(new File([t], name), {}, n)); }
            catch (e) { b = 'error ' + e.message + ' ' + e.line; } if (a !== b) out.push(`${name} in ${n}`); } }
        return out; }""", [[f.name, f.read_text(encoding='utf-8', errors='replace')] for f in fixtures] + [
          ['comment.vcd', '$timescale 1ns $end\n$scope module t $end\n$var wire 4 ! a [3:0] $end\n$var wire 1 " b $end\n$upscope $end\n$enddefinitions $end\n'
           '#0\nb0000 !\n0"\n$comment a long one\nover lines $end\n#5\nb\n1010\n!\n1"\n#7 b1 ! 0"\n#9\nb11\n!\n$comment no end'],
          ['utf8.vcd', '$date Sa 24 Okt 2026 — été $end\n$scope module t $end\n$var wire 1 ! é $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n#5\n1!\n'],
          ['back.vcd', '$scope module t $end\n$var wire 1 ! a $end\n$upscope $end\n$enddefinitions $end\n#10\n0!\n#5\n1!\n']])
    check(not cut, f'a dump read in pieces of 1, 3, 7, 64 characters: the same doc, notes and lines as its text at once {cut}')
    # review VI: "$enddefinitions" in a header's $comment is not its end (A1: the fixture head_comment in pieces above); an
    # FST's enum table of 64 bits keeps 2^53 and 2^53 + 1 apart (A2); a types file's "map" not an object of texts is an
    # error, as in svtypes.py (A3); a row's own labels stay before the file's and the inspector says so (A4, svWhy: own);
    # an FSM of a clock-sampled row with labels that look like numbers counts its states by the table (A6)
    six = page.evaluate("""() => { const I = WaveLens.internal, out = [];
        const t = '$attrbegin misc 07 w 2 EVEN ODD 1' + '0'.repeat(53) + ' 1' + '0'.repeat(52) + '1 1 $end\\n$scope module t $end\\n' +
          '$attrbegin misc 07 "" 1 $end\\n$var logic 64 ! w [63:0] $end\\n$upscope $end\\n$enddefinitions $end\\n#0\\nb1 !\\n';
        out.push(WaveLens.vcdToWave(t).doc.signal[0][1].enum);
        for (const m of [['tb=dut'], 'tb', { tb: 1 }]) { try { I.svTypes({ wavelens: 'types', map: m }); out.push('no error'); } catch (e) { out.push(/"map" is/.test(e.message)); } }
        out.push(I.svTypes({ wavelens: 'types', map: null }).map);
        const sv = I.svTypes({ wavelens: 'types', signals: { 't.s': { width: 1, enum: { 0: 'OTHER0', 1: 'OTHER1' } }, 't.u': { width: 1, enum: { 0: 'U0', 1: 'U1' } },
          't.n': { width: 2, enum: { 0: 'N0' } } } }, 'other.types.json'), why = new Map();
        const doc = { signal: [{ name: 's', path: 't.s', tv: [[0, '0']], enum: { 0: 'MINE0', 1: 'MINE1' } }, { name: 'u', path: 't.u', tv: [[0, '0']] },
          { name: 'n', path: 't.n', tv: [[0, '0']], enum: { 0: 'OWN' } }] };
        out.push([I.svApply(doc, sv, [], why), doc.signal[0].enum[0], doc.signal[1].enum[1], ...['t.s', 't.u', 't.n'].map(p => why.get(p).status + ' ' + why.get(p).labels)]);
        const of = (p, e, w) => WaveView.prototype.typesOf.call({ opts: { svWhy: why, sv } }, { full: p, path: p, enum: e, width: w });
        out.push([of('t.s', doc.signal[0].enum, 1), of('t.n', doc.signal[2].enum, 1)].map(o => o.status + ': ' + o.why));
        const r = { width: 1, enum: { 0: '1', 1: '2' }, tr: [{ t: 0, k: '=', v: '1' }, { t: 10, k: '=', v: '2' }, { t: 20, k: '=', v: '1' }] }, st = I.fsmStats(r, 30);
        out.push([[...st.vals.keys()], st.bad.length, st.unseen.length]);
        // T8: x before the first state, the same time twice, z between, partly known bits, the last state held to t1
        const f = I.fsmStats({ width: 2, enum: { 0: 'A', 1: 'B', 2: 'C' }, tr: [{ t: 0, k: 'x' }, { t: 10, k: '=', raw: '0', v: 'A' }, { t: 20, k: '=', raw: '1', v: 'B' },
          { t: 20, k: '=', raw: '1', v: 'B' }, { t: 30, k: 'z' }, { t: 35, k: '=', bits: 'x1', v: '?' }, { t: 40, k: '=', raw: '0', v: 'A' }] }, 100);
        out.push([f.seq.map(x => x.join('@')).join(' '), [...f.vals.values()].map(x => `${x.key}:${x.time}:${x.entries.length}`).join(' '),
          [...f.trans.keys()].join(' '), f.unseen.join(), f.trans.get('x>0').times.join(), f.bad.map(x => x.key).join(), f.keyOf('B'), f.keyOf('Z'), f.name('2'), f.name('3')]);
        return out; }""")
    check(six[0] == {'9007199254740992': 'EVEN', '9007199254740993': 'ODD'} and six[1:4] == [True] * 3 and six[4] == {} and
          six[5] == [1, 'MINE0', 'U1', 'typed own', 'typed types', 'width own'] and six[6][0].startswith('own: its own labels') and
          'its own labels stay' in six[6][1] and six[7] == [['0', '1'], 0, 0] and
          six[8] == ['0@x 10@0 20@1 30@z 35@x 40@0', 'x:15:2 0:70:2 1:10:1 z:5:1', 'x>0 0>1 1>z z>x', '2', '10,40', 'x,z', '1', 'z', 'C', '3 (no label)'],
          f'review VI A2 A3 A4 A6 T8: 64-bit table keys exact, a bad map an error, own labels kept and said so, labels like numbers; an FSM\'s states '
          f'and changes over x, z, a time twice, the last one held {six}')
    same, differ = [], []
    for f in fixtures:
        text = f.read_text(encoding='utf-8', errors='replace')
        got = page.evaluate(READ_PAGE, text)
        if f.stem in READERS_BAD:
            r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'vcd2wavedrom.py'), '--waves', str(f), '--exact', '--signals', 'tb.s'], capture_output=True, text=True)
            ok = READERS_BAD[f.stem] in (got.get('err') or '') and r.returncode == 1 and READERS_BAD[f.stem] in r.stderr
            (same if ok else differ).append(f.stem + ('' if ok else f' (page: {got.get("err")}, tools: {r.stderr.strip()[:80]})'))
            continue
        bad = page_vs_tools(f, got)
        (differ if bad else same).append(f.stem + (f' ({bad[:3]})' if bad else ''))
    check(not differ and len(same) == len(fixtures), f'the page and the tools read {len(same)} of {len(fixtures)} fixtures the same' + (f'; differ: {differ}' if differ else ''))
    # review VI T5: 40 generated dumps (gen_vcd) against what they hold, the page against the tools, and the page's read of
    # a File in pieces of BYTES (a stream of 1, 2, 3, 5, 64 bytes a read: an é or — cut in two) against its text at once,
    # the parser given the whole text or pieces of that many characters; three small ones cut in two at every byte (the
    # parser: the whole, or pieces of k characters)
    import tempfile
    gen_bad, cut_bad, n_cuts = [], [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for seed in range(1, 41):
            text, model = gen_vcd(seed)
            got = page.evaluate(READ_PAGE, text)
            if 'err' in got:
                gen_bad.append(f'{seed}: {got["err"]}'); continue
            for pth, m in model.items():
                pg = got['sigs'].get(pth)
                if pg is None or pg['width'] != m['width'] or pg['tv'] != m['tv'] or pg['enum'] != m.get('enum'):
                    gen_bad.append(f'{seed} {pth}: page {pg and (pg["width"], pg["tv"][:3])}, written {m["width"], m["tv"][:3]}'); break
            f = pathlib.Path(tmp) / f'gen{seed}.vcd'; f.write_text(text, encoding='utf-8')
            gen_bad += [f'{seed} tools: {x}' for x in page_vs_tools(f, got)[:2]]
            res = page.evaluate("""async ([name, t, sizes, every]) => { const one = r => JSON.stringify(r, (k, v) => (k === 'size' ? undefined : v));
                const bytes = new TextEncoder().encode(t), whole = one(WaveLens.vcdToWave(t)), bad = [];
                const file = cuts => ({ name, size: bytes.length, stream() { let i = 0, j = 0; return new ReadableStream({ pull(c) {
                  if (i >= bytes.length) { c.close(); return; } const e = Math.min(bytes.length, cuts(j++, i)); c.enqueue(bytes.slice(i, e)); i = e; } }); } });
                // chunk 1 << 20: the decoder's cuts only (a small dump reaches the parser whole); chunk n, k: the parser's too
                for (const n of sizes) for (const ch of [1 << 20, n]) { const got = one(await WaveLens.vcdToWaveFile(file((j, i) => i + n), {}, ch));
                  if (got !== whole) bad.push(`bytes ${n}, pieces of ${ch}`); }
                if (every) for (let k = 1; k < bytes.length; k++) for (const ch of [1 << 20, k]) {
                  const got = one(await WaveLens.vcdToWaveFile(file((j, i) => (j ? bytes.length : k)), {}, ch));
                  if (got !== whole) { bad.push(`cut at ${k}, pieces of ${ch}`); k = bytes.length; break; } }
                return [bad, every ? bytes.length - 1 : 0]; }""", [f.name, text, [1, 2, 3, 5, 64], seed <= 3])
            cut_bad += [f'{seed} {x}' for x in res[0]]; n_cuts += res[1]
    check(not gen_bad, f'40 generated dumps: the page reads what they hold (every value, the bits of a vector, the alias, the enum), the tools the same '
          f'{gen_bad[:3]}')
    check(not cut_bad and n_cuts > 300, f'a File read in pieces of 1, 2, 3, 5, 64 bytes, three of them cut in two at each of {n_cuts} bytes, the parser '
          f'given those pieces too: its text at once {cut_bad[:3]}')
    # review VI T15: a File of 18 MB in pieces of 8 MB (Open…) takes about the time of its text at once, both in a budget
    rd = page.evaluate("""async n => { let s = '$timescale 1ns $end\\n$scope module tb $end\\n';
        for (let i = 0; i < 64; i++) s += `$var wire 8 ${String.fromCharCode(33 + i)} s${i} [7:0] $end\\n`;
        const parts = [s + '$upscope $end\\n$enddefinitions $end\\n']; let t = 0, c = 0;
        while (c < n) { let l = '#' + (++t) + '\\n'; for (let k = 0; k < 8; k++) { l += 'b' + ((t * 7 + k * 13) & 255).toString(2) + ' ' +
          String.fromCharCode(33 + ((t + k * 5) & 63)) + '\\n'; c++; } parts.push(l); }
        const text = parts.join(''), f = new File([text], 'big.vcd');
        let t0 = performance.now(); const a = WaveLens.vcdToWave(text, { budget: 1e9 }); const whole = performance.now() - t0;
        t0 = performance.now(); const b = await WaveLens.vcdToWaveFile(f, { budget: 1e9 }); const file = performance.now() - t0;
        return [text.length, whole, file, a.changes, b.changes]; }""", 1500000)
    check(rd[3] == rd[4] == 1500000 and rd[2] < 15000 * SCALE and rd[2] < 2 * rd[1] + 500,
          f'a VCD of {rd[0] / 1e6:.0f} MB: Open… in pieces {rd[2] / 1e3:.1f} s, its text at once {rd[1] / 1e3:.1f} s, {rd[4]} changes')
    # the names of SystemVerilog sources (a VCD has no enum tables): the page's svTables gives what mkconfig.py --sv does
    import mkconfig
    sys.path.insert(0, str(ROOT)); from tests.unit.test_mkconfig import Sources   # its source text with nested structs
    srcs = [sorted((ROOT / 'examples' / 'fsm').glob('*.sv')), None]
    with tempfile.TemporaryDirectory() as d:
        (pathlib.Path(d) / 'p.sv').write_text(Sources.SV); srcs[1] = [pathlib.Path(d) / 'p.sv']
        got = []
        for fs in srcs:
            py = {'enums': {k: {str(a): b for a, b in v.items()} for k, v in mkconfig.sv_enums([str(f) for f in fs]).items()},
                  'fields': mkconfig.sv_structs([str(f) for f in fs])}
            js = page.evaluate("ts => { const t = WaveLens.svTables(ts); return { enums: t.enums, fields: t.fields }; }", [f.read_text() for f in fs])
            got.append((py == js, len(py['enums']), len(py['fields'])))
    check(all(g[0] for g in got) and all(g[1] for g in got) and got[1][2], f'the sources\' enum names and struct fields: the page and mkconfig.py --sv the same {got}')
    # and both against the tables the fixture should give (equal and both wrong would pass the line above)
    want = json.loads((ROOT / 'tests' / 'unit' / 'sv' / 'sources.json').read_text())
    js = page.evaluate("t => { const r = WaveLens.svTables([t]); return [r.enums, r.fields, r.notes.map(n => /^(?:enum |struct )?(\\w+)/.exec(n)[1])]; }",
                       (ROOT / 'tests' / 'unit' / 'sv' / 'sources.sv').read_text())
    # svApply (review IV A8, N2, C2; Codex C7, C8): array elements (also a negative index) get the array's table, a clock-sampled
    # row (no tv) and a table that does not fit are left alone, an empty table is not applied
    ap = page.evaluate("""() => { const tv = [[0, '1'], [10, '4']], doc = { signal: [['tb', ['sel', { name: '[-1]', path: 'tb.sel.[-1]', width: 3, tv },
        { name: 'sel[2]', path: 'tb.sel[2]', width: 3, tv }], { name: 'sel', path: 'tb.sel', width: 3, wave: '==', data: ['1', '4'] },
        { name: 'narrow', path: 'tb.narrow', width: 2, tv: [[0, '1']] }, { name: 'none', path: 'tb.none', width: 3, tv }]] };
      const n = WaveLens.svApply(doc, { enums: { sel: { 1: 'A0', 2: 'A1', 4: 'A2' }, narrow: { 4: 'BIG' }, none: {} }, fields: {} });
      const [, g, clk, nar, none] = doc.signal[0]; return [n, g[1].enum && g[1].enum[4], g[2].enum && g[2].enum[1], !!clk.enum, !!nar.enum, !!none.enum]; }""")
    check(ap == [2, 'A2', 'A0', False, False, False], f'svApply: array elements (a negative index too) named; a clock-sampled row, a table too wide, an empty one left alone {ap}')
    check(js == [want['enums'], want['fields'], want['notes']], f'tests/unit/sv/sources.sv: the page gives the expected tables and notes {js if js != [want["enums"], want["fields"], want["notes"]] else ""}')
    # the types by path (tools/svtypes.py's twin): Questa's describe of the corpus gives the expected tables, every form of
    # tests/unit/types/describe.json its entry or its note
    T = ROOT / 'tests' / 'unit' / 'types'
    tw, cases = json.loads((T / 'types.expected.json').read_text()), json.loads((T / 'describe.json').read_text())['cases']
    js = page.evaluate("t => { const r = WaveLens.svTypes(t, 'questa.types.json'); return [r.paths, r.notes]; }", (T / 'questa.types.json').read_text())
    check(js == [tw['signals'], tw['notes']], f'tests/unit/types/questa.types.json: the page gives the expected types by path {js if js[0] != tw["signals"] else js[1]}')
    js = page.evaluate("""cs => cs.map(c => { const r = WaveLens.svTypes({ wavelens: 'types', describe: { x: c.describe } });
        return [r.paths.x || null, r.notes.length ? r.notes[0].slice(3) : null]; })""", cases)
    bad = [c['describe'][:30] for c, g in zip(cases, js) if g != [c['entry'], c['note']]]
    check(not bad, f'tests/unit/types/describe.json: every form of describe as svtypes.py reads it {bad}')
    # svApply by path (review V A2, A8): another root of the dump with a tb below is not the types' tb, a TOP above the
    # design is skipped; an empty types file still keeps the names of the sources out
    got = page.evaluate("""() => { const tv = [[0, '1']], s = (path, width = 2) => ({ name: path.split('.').pop(), path, width, tv });
      const ty = WaveLens.svTypes({ wavelens: 'types', producer: { tool: 'Q' }, signals: { 'tb.u.state': { width: 2, enum: { 1: 'A' } } } });
      const d1 = { signal: [s('tb.u.state'), s('other.tb.u.state')] }, d2 = { signal: [s('TOP.tb.u.state'), s('TOP.clk', 1)] };
      const n1 = WaveLens.svApply(d1, ty), n2 = WaveLens.svApply(d2, ty);
      const d3 = { signal: [s('tb.u.state')] }, empty = WaveLens.svTypes({ wavelens: 'types', signals: {} });
      const n3 = WaveLens.svApply(d3, Object.assign(empty, { enums: { state: { 1: 'BYNAME' } } }));
      return [n1, !!d1.signal[0].enum, !!d1.signal[1].enum, n2, d2.signal[0].enum && d2.signal[0].enum[1], n3]; }""")
    check(got == [1, True, False, 1, 'A', 0], f'types by path: other.tb.state not tb.state, TOP. skipped; an empty types file: no labels by name {got}')
    # a 64-bit enum (Verilator's, review V A3): 2^53 and 2^53 + 1 are two labels, -1 (2^64 - 1) fits the width
    got = page.evaluate("""() => { const ty = WaveLens.svTypes({ wavelens: 'types', signals: { 'tb.w': { width: 64,
        enum: { '9007199254740992': 'EVEN', '9007199254740993': 'ODD', '18446744073709551615': 'ALL' } } } });
      const doc = { signal: [{ name: 'w', path: 'tb.w', width: 64, tv: [[0, '20000000000000'], [10, '20000000000001'], [20, 'ffffffffffffffff']] }] };
      const n = WaveLens.svApply(doc, ty), el = document.createElement('div'); document.body.append(el);
      const v = new WaveLens.WaveView(el, doc, {}), r = v.M.rows.find(x => x.full === 'tb.w'), out = [n, ...[5, 15, 25].map(t => v.valueAt(r, t))];
      v.destroy(); el.remove(); return out; }""")
    check(got == [1, 'EVEN', 'ODD', 'ALL'], f'a 64-bit enum: its table taken, 2^53 + 1 not 2^53, -1 by its label {got}')
    # review VI T6: tests/unit/types/contract.json through the page's twin (svTypes, svApply, svFingerprint), as svtypes.py
    # gives it (tests/unit/test_svtypes.py Contract)
    contract = json.loads((T / 'contract.json').read_text(encoding='utf-8'))['cases']
    got = page.evaluate(CONTRACT_JS, contract)
    bad = [f'{c["name"]}: {g} (want {c["want"]})' for c, g in zip(contract, got) if g != c['want']]
    check(not bad and len(got) == len(contract), f'the types contract: {len(contract)} cases, the page as svtypes.py {bad[:2]}')
    sys.path.insert(0, str(ROOT)); from tests.unit.test_svtypes import contract_py
    gen = [gen_types_case(seed) for seed in range(200)]
    got = page.evaluate(CONTRACT_JS, gen)
    bad = [f'{seed}: page {g}, svtypes.py {contract_py(c)}' for seed, (c, g) in enumerate(zip(gen, got)) if g != contract_py(c)]
    typed = sum(1 for g in got if g.get('labels') or g.get('fields'))
    check(not bad and typed > 50, f'200 generated types files and dumps: the page as svtypes.py ({typed} with labels or fields) {bad[:2]}')
    # known bits among x / z reach the page's engine as bits (they were x by the hex: the page and sva eval disagreed)
    for f in ('wavelens.config.js', 'sva.wasm.js', 'sva.js'):
        page.add_script_tag(path=str(ROOT / 'wavelens' / f))
    got = page.evaluate("""async t => { const M = WaveLens.parse(WaveLens.vcdToWave(t).doc), X = SVA.expressions, out = [];
        for (const text of ['b[0]', 'b[3:0] == 4\\'b0z0x', 'b[7:4] === 4\\'b1x0z']) { const r = await X.valueOf(M, [], { text, scope: 'tb' });
          out.push(r.err || r.times.map((t, i) => [t, String(r.values[i])])); }
        return out; }""", (ROOT / 'tests' / 'unit' / 'vcd' / 'xz.vcd').read_text())
    check(got == [[[0, 'x'], [10000, 'x'], [20000, '1'], [30000, '1']], [[0, '0'], [10000, 'x'], [20000, 'x'], [30000, 'x']],
                  [[0, '1'], [10000, '0'], [20000, '0'], [30000, '0']]],
          f'xz.vcd in the page\'s engine: bit 0 of bx1 is 1 (not x), 1x0z1z0x keeps its known bits (== on a known bit that differs: 0, not x) {got}')
    page.close()


def axis_in_sight(browser, build):
    """The time axis never leaves while the rows scroll (axi_lite_all.html, every group open, a window shorter than the
    viewer): in the viewer's own box the box fits under the bar and its end does not scroll the page on; the page
    scrolled past the viewer's top, the wheel over the rows brings the bar back; with the page, at the end of the rows
    the axis stays under the bar (the canvas gets shorter)."""
    pg = build / 'examples' / 'axi_lite' / 'axi_lite_all.html'
    if not need(pg, how='make examples'):
        return
    print('the axis in sight')
    page = browser.new_page(viewport={'width': 1200, 'height': 600})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(pg.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    geo = ("(() => { const v = document.querySelector('.wv').waveView, b = v.root.querySelector('.bar').getBoundingClientRect(); return "
           "[Math.round(b.top), Math.round(v.canvas.getBoundingClientRect().top - b.bottom), Math.round(v.bodyEl.getBoundingClientRect().bottom), "
           "Math.round(scrollY), Math.round(v.bodyEl.scrollTop)]; })()")
    js("(v.setScroll('window'), v.expandAll(), v.root.querySelector('.bar').scrollIntoView(), 0)"); settle(page)
    page.mouse.move(700, 450); a = page.evaluate(geo)
    for _ in range(8):
        page.mouse.wheel(0, 600); page.wait_for_timeout(60 * SCALE)
    settle(page); b = page.evaluate(geo)
    check(a[0] == b[0] == 0 and a[1] == b[1] == 0 and a[2] <= 600 and b[3] == a[3] and b[4] > 1000,
          f'its own box: no taller than the window under the bar, its end does not scroll the page on, the bar and the axis stay {a} {b}')
    page.evaluate("window.scrollBy(0, 150)"); settle(page); c = page.evaluate(geo)
    page.mouse.move(700, 300); page.mouse.wheel(0, -100); settle(page); d = page.evaluate(geo)
    check(c[0] == -150 and d[0] == 0 and d[1] == 0, f'the page past the viewer\'s top: the wheel over the rows brings the bar and the axis back {c} {d}')
    js("(v.zoom(0.25, 0.5), 0)")   # zoomed in: a pan has room
    page.evaluate("window.scrollBy(0, 150)"); settle(page); t0 = js("v.t0"); y0 = page.evaluate('scrollY')
    page.keyboard.down('Shift'); page.mouse.wheel(0, 100); page.keyboard.up('Shift'); settle(page)
    check(page.evaluate('scrollY') == y0 and js("v.t0") != t0, f'shift+wheel over the rows: a pan, the page stays {y0} {page.evaluate("scrollY")}')
    page.evaluate("window.scrollBy(0, -150)")
    page.set_viewport_size({'width': 1000, 'height': 160}); settle(page)
    lo = js("[v.bodyEl.clientHeight, WaveLens.internal.peek(v).hdrH, v.hc, WaveLens.internal.peek(v).lay.H]")
    page.set_viewport_size({'width': 1200, 'height': 600}); settle(page)
    check(lo[0] >= 120 and lo[2] < lo[3], f'a window lower than the bar: the box keeps 120 px of rows (the axis and some rows), not 0 {lo}')
    js("(v.setScroll('page'), 0)"); settle(page)
    seen = []
    for y in (300, 900, 1500, 1900):   # the page among the rows, then their last ones in sight
        page.evaluate(f"window.scrollTo(0, document.querySelector('.wv .wcol').getBoundingClientRect().top + scrollY + {y})"); settle(page)
        g = page.evaluate(geo); seen.append(g[:2] + [js("v.hc")])
    check(all(g[0] == 0 and g[1] == 0 for g in seen) and seen[-1][2] < seen[0][2],
          f'with the page: the bar on top, the axis under it to the last rows (the canvas shorter there) {seen}')
    check(not errs, f'no page errors {errs}')
    page.close()


def lazy_vcd(seed=7, subs=6, mods=5, cores=3, sigs=10, steps=400):
    """A dump of a design's shape for the lazy reading: tb (clk, rst_n), subN (ctl), subN.modM (data, valid, clk, an FSM's
    state with its enum table), subN.modM.coreK (sN of 1–32 bits); random changes -> its text."""
    import random
    rnd = random.Random(seed)
    out, vs, names = ['$timescale 1ns $end', '$attrbegin misc 07 st_t 3 IDLE RUN DONE 00 01 10 1 $end', '$scope module tb $end'], [], []
    def var(w, name, ref=False):
        names.append(name)
        n, c = len(vs) + 1, ''
        while n:
            n -= 1; c += chr(33 + n % 94); n //= 94
        vs.append((c, w))
        if ref:
            out.append('$attrbegin misc 07 "" 1 $end')
        out.append(f'$var wire {w} {c} {name}' + (f' [{w - 1}:0]' if w > 1 else '') + ' $end')
    var(1, 'clk'); var(1, 'rst_n')
    for a in range(subs):
        out.append(f'$scope module sub{a} $end'); var(8, 'ctl')
        for b in range(mods):
            out.append(f'$scope module mod{b} $end'); var(32, 'data'); var(1, 'valid'); var(1, 'clk'); var(2, 'state', ref=True)
            for c in range(cores):
                out.append(f'$scope module core{c} $end')
                for d in range(sigs):
                    var(rnd.choice([1, 1, 4, 8, 32]), f's{d}')
                out.append('$upscope $end')
            out.append('$upscope $end')
        out.append('$upscope $end')
    out += ['$upscope $end', '$enddefinitions $end', '#0', '$dumpvars'] + [f'0{c}' if w == 1 else f'b0 {c}' for c, w in vs] + ['$end']
    clks = [i for i, x in enumerate(names) if x == 'clk']
    for t in range(1, steps):
        out.append(f'#{t * 5}')
        out += [f'{t % 2}{vs[i][0]}' for i in clks]
        for i in rnd.sample([i for i in range(len(vs)) if i not in clks], 40):
            c, w = vs[i]
            out.append(f'{rnd.getrandbits(1)}{c}' if w == 1 else f'b{rnd.randrange(3) if w == 2 else rnd.getrandbits(w):b} {c}')
    return '\n'.join(out) + '\n'


def lazy_dump(browser, build):
    """A large dump read as it is needed (the VS Code tab, wavelens.lazy: the header of its FST from sva vcd --header, then
    the signals shown from sva vcd --codes): every module and signal at once, the top level open and its modules folded;
    the signals on the screen read after a frame (only those), a module opened: its own; every signal read gives the
    rows the whole text gives (the fixtures, generated dumps, a design-shaped one, the examples); an assertion bound to a
    folded module and the FSM panel read theirs first (the counts and the states of the whole dump); the picture command
    its rows; a page without a reader shows what it has."""
    import shutil, tempfile
    exe = build / 'sva-target' / 'release' / 'sva'
    pg = build / 'examples' / 'apb' / 'apb.html'
    if not need(exe, pg, how='make sva-build examples'):
        return
    print('lazy: a large dump read as it is needed')
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='wl-lazy-'))
    parts = {}   # name -> its FST

    def fst_of(name, text):   # -> (the whole text of its FST, its header)
        v, f = tmp / (name + '.vcd'), tmp / (name + '.fst')
        v.write_text(text, encoding='utf-8')
        if subprocess.run([str(exe), 'fst', str(v), '--no-types', '-q'], capture_output=True).returncode:
            return None
        parts[name] = f
        rd = lambda *a: subprocess.run([str(exe), 'vcd', str(f), *a], capture_output=True, text=True, check=True).stdout
        return rd(), rd('--header')
    asked = []

    def codes(name, cs):
        asked.append((name, len(cs)))
        return subprocess.run([str(exe), 'vcd', str(parts[name]), '--codes', '-'], input='\n'.join(cs), capture_output=True, text=True, check=True).stdout
    page = browser.new_page(viewport={'width': 1400, 'height': 900})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.expose_function('lazyCodes', codes)
    page.goto(pg.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('SVA.ready()')
    js = lambda e: page.evaluate(f"(async () => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    open_ = ("([n, t, lazy]) => { const f = new File([t], n + '.fst'); if (lazy) { f.wlLazy = true; f.wlLoad = c => window.lazyCodes(n, c); } "
             "return document.querySelector('.wv').waveView.openDump(f).then(() => 0); }")
    # every signal read: the rows of the whole text (fixtures, generated dumps, the design-shaped one, the examples)
    same = """async ([n, whole, head]) => { const a = document.createElement('div'), b = document.createElement('div'); document.body.append(a, b);
      const va = new WaveLens.WaveView(a, WaveLens.vcdToWave(whole, { name: n, budget: Infinity }).doc, {});
      const vb = new WaveLens.WaveView(b, WaveLens.vcdToWave(head, { name: n, lazy: true }).doc, { loadCodes: c => window.lazyCodes(n, c) });
      const was = vb.M.rows.filter(r => r.lazy).length; await vb.need(vb.M.rows);
      const key = v => JSON.stringify([v.M.t0, v.M.t1, v.M.rows.map(r => [r.type, r.full, r.width, r.kind || null,
        (r.type === 'sig' ? r.tr : r.sig ? r.sig.tr : []).map(o => [o.t, o.k, o.raw ?? null, o.v ?? null, o.bits ?? null])])]);
      const out = [key(va) === key(vb), was, vb.M.rows.filter(r => r.lazy).length]; va.destroy(); vb.destroy(); a.remove(); b.remove(); return out; }"""
    dumps = [(f.stem, f.read_text(encoding='utf-8', errors='replace')) for f in sorted((ROOT / 'tests' / 'unit' / 'vcd').glob('*.vcd'))]
    dumps += [(f'gen{s}', gen_vcd(s)[0]) for s in range(10)] + [('design', lazy_vcd())]
    dumps += [(f'ex_{x}', (build / 'examples' / x / f'{x}.vcd').read_text()) for x in ('apb', 'axi_lite', 'fsm') if (build / 'examples' / x / f'{x}.vcd').exists()]
    bad, n = [], 0
    for name, text in dumps:
        w = fst_of(name, text)
        if w is None:
            continue   # a dump sva fst refuses (time back, cut off)
        r = page.evaluate(same, [name, *w]); n += 1
        if not r[0] or r[2] or (r[1] == 0 and 'signal' in w[0] and '$var' in w[1] and False):
            bad.append((name, r))
    check(not bad and n >= 40, f'{n} dumps read as they are needed, every signal: the rows of the whole text {bad}')
    # the design-shaped dump: the top level open, its modules folded; the signals on the screen read, only those
    whole, head = fst_of('design', lazy_vcd())
    asked.clear()
    page.evaluate(open_, ['design', head, True]); settle(page); page.wait_for_timeout(300)
    vis = "WaveLens.internal.peek(v).vis"
    g1 = js(f"[v.lazy, v.M.rows.filter(r => r.type === 'sig').length, {vis}.length, {vis}.filter(r => r.lazy).length, "
            f"v.M.rows.filter(r => r.type === 'sig' && !r.lazy).map(r => r.full)]")
    check(g1[0] and g1[1] == 1028 and g1[2] <= 12 and g1[3] == 0 and sorted(g1[4]) == ['tb.clk', 'tb.rst_n'] and asked == [('design', 2)],
          f'its header: every signal there ({g1[1]}), the top level open, its modules folded; the two on the screen read, nothing more {g1[:4]} {asked}')
    js("(v.fold(Object.values(v.M.groups).find(g => g.path === 'tb.sub2').id, false), v.fold(Object.values(v.M.groups).find(g => g.path === 'tb.sub2.mod3').id, "
       "false), 0)"); settle(page); page.wait_for_timeout(300)
    g2 = js(f"[{vis}.filter(r => r.lazy).length, v.M.rows.filter(r => r.full.startsWith('tb.sub2.mod3.') && r.type === 'sig' && r.depth === 3).every(r => !r.lazy), "
            "v.M.rows.filter(r => r.full.startsWith('tb.sub4.') && r.type === 'sig').every(r => r.lazy), "
            "(r => [r.tr.length > 5, r.tr[0].t])(v.M.rows.find(r => r.full === 'tb.sub2.mod3.data'))]")
    check(g2[0] == 0 and g2[1] and g2[2] and g2[3] == [True, 0], f"a module opened: its signals read and drawn, the others' not {g2} {asked}")
    # an assertion bound to a folded module reads its signals first: the counts of the whole dump
    js("(SVA.loadFiles([{ name: 'lz.sva', text: 'module lz (input logic clk, input logic [1:0] state); ' + "
       "'a_lz: assert property (@(posedge clk) state != 2\\'d3); c_lz: cover property (@(posedge clk) state == 2\\'d2); endmodule' }]), 0)")
    bind = """async () => { await SVA.ready(); const p = SVA.panels().find(x => x.v === document.querySelector('.wv').waveView), out = [];
      for (const a of ['a_lz', 'c_lz']) { const b = p.bind(a, 'tb.sub1.mod2'); await SVA.ready(); await p.queue; const s = b.results ? b.results.assertions[0].stats : {};
        out.push([b.state, b.error || null, s.pass, s.fail, s.attempts]); p.unbind(b); } return out; }"""
    js("(v.collapseAll(), 0)"); settle(page)
    lazy_sv = page.evaluate(bind)
    read = js("v.M.rows.filter(r => r.full.startsWith('tb.sub1.mod2.') && r.depth === 3 && !r.lazy).map(r => r.name).sort()")
    page.evaluate(open_, ['design', whole, False]); settle(page)
    whole_sv = page.evaluate(bind)
    check(lazy_sv == whole_sv and lazy_sv[0][4] > 100 and {'clk', 'state'} <= set(read), f'an assertion bound to a folded module reads its signals first: '
          f'the counts of the whole dump {lazy_sv} / {whole_sv} {read}')
    # the FSM panel and fsm_stats: the FSMs read; picture: its rows
    st_whole = js("v.run([{ op: 'fsm_stats', signal: 'tb.sub5.mod4.state' }])")
    page.evaluate(open_, ['design', head, True]); settle(page)
    st_lazy = js("v.run([{ op: 'fsm_stats', signal: 'tb.sub5.mod4.state' }])")
    js("(v.fsmPanel(true), 0)"); settle(page); page.wait_for_timeout(300)
    fs = js("[v.fsms().length, v.fsms().filter(r => r.lazy).length, v.fsmP && v.fsmP.seenOf(v.fsms()[0])]")
    js("(v.fsmPanel(false), v.fold(Object.values(v.M.groups).find(g => g.path === 'tb.sub0').id, false), 0)")
    pic = js("(async () => { const r = await v.run([{ op: 'picture', format: 'svg' }]); return [!!r[0].svg, WaveLens.internal.peek(v).vis.filter(r => r.lazy).length]; })()")
    check(st_lazy == st_whole and 'error' not in st_lazy[0] and fs[0] == 30 and fs[1] == 0 and fs[2] and fs[2][0] == 3 and pic == [True, 0],
          f'fsm_stats and the FSM panel read the FSMs (the states of the whole dump), picture its rows {fs} {pic} {str(st_lazy)[:120]}')
    # a page without the reader (a saved one): its rows as they are, nothing waits
    nl = page.evaluate("""h => { const a = document.createElement('div'); document.body.append(a);
      const v = new WaveLens.WaveView(a, WaveLens.vcdToWave(h, { lazy: true }).doc, {}); const out = [v.lazy, v.M.rows.filter(r => r.lazy).length];
      v.destroy(); a.remove(); return out; }""", head)
    check(nl == [False, 0], f'without a reader: no row waits to be read {nl}')
    check(not errs, f'no page errors {errs[:3]}')
    page.close()
    shutil.rmtree(tmp, ignore_errors=True)

def bookmark_view(browser, build):
    """Going to a bookmark puts the waves where they were when it was made (axi_lite_all.html, every group open): the
    row then at the top under the axis at the top again, its time bookmarkLeft (0.2) of the waves from the left, the span
    kept; with the page and in the viewer's own box, through 1–9, ]m, the list (gm) and the command; the way to that row
    opened when its module was folded since; a bookmark without a top (an older one): its signal brought into sight, as it
    is when its top is gone; its signal folded since: opened and selected; the list's cursor button takes the screen too;
    at 1200×320 and 480×600."""
    pg = build / 'examples' / 'axi_lite' / 'axi_lite_all.html'
    if not need(pg, how='make examples'):
        return
    print('bookmarks: the view where they were made')
    page = browser.new_page(viewport={'width': 1200, 'height': 600})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(pg.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    js = lambda e: page.evaluate(f"(async () => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    # where a row is against the top of the rows under the axis (px, 0: at the top), the cursor's place in the window
    at = ("(p => { const r = WaveLens.internal.peek(v).vis.find(q => (q.full || q.path) === p), y = r && v.rowTop(r); "
          "return y == null ? null : Math.round(y - v.canvas.getBoundingClientRect().top - v.hdrH); })")
    frac = "Math.round((v.cursor - v.t0) / v.span * 100) / 100"
    # a signal's row between the axis and the bottom of the waves on the screen (its element, not v.inSight)
    seen = ("(p => { const k = WaveLens.internal.peek(v).vis.findIndex(r => r.full === p), "
            "el = k >= 0 && v.root.querySelector(`.names .row[data-r=\"${k}\"]`); if (!el) return false; "
            "const q = el.getBoundingClientRect(), c = v.canvas.getBoundingClientRect(), own = v.root.classList.contains('wv-scroll'), "
            "bot = Math.min(innerHeight, own ? v.bodyEl.getBoundingClientRect().bottom : c.bottom); "
            "return q.top >= c.top + v.hdrH - 1 && q.bottom <= bot + 1; })")
    js("(v.setScroll('page'), v.expandAll(), v.zoom(0.1, 0.5), 0)"); settle(page)
    page.evaluate("window.scrollTo(0, document.querySelector('.wv .wcol').getBoundingClientRect().top + scrollY + 700)"); settle(page)
    top1 = js("v.topNow()")
    sig = js("(() => { const c = v.canvas.getBoundingClientRect(); return WaveLens.internal.peek(v).vis.find(r => r.type === 'sig' && v.rowTop(r) > c.top + 200).full; })()")
    t1 = js(f"(v.select(v.M.rows.find(r => r.full === {json.dumps(sig)})), v.cursor = v.t0 + v.span * 0.7, v.mark('one'))")
    b1 = js(f"v.bms.find(b => b.n === {t1})")
    check(top1 and b1['top'] == top1 and js(f"{at}({json.dumps(top1)})") <= 0 < js(f"{at}({json.dumps(top1)})") + js("v.rowH.sig"),
          f'a new bookmark keeps the row at the top of the waves under the axis {top1} {b1}')
    span = js("v.span")
    page.evaluate("window.scrollTo(0, 0)"); js("(v.t0 = v.M.t0, v.draw(), v.canvas.focus({preventScroll: true}), 0)"); settle(page)
    page.keyboard.press(str(t1)); settle(page)
    g1 = [js("v.cursor") == b1['t'], js(frac), js("v.span") == span, js(f"{at}({json.dumps(top1)})"), js("v.sel && v.sel.full")]
    check(g1[0] and g1[1] == 0.2 and g1[2] and abs(g1[3]) <= 1 and g1[4] == sig,
          f'1–9: the cursor on it 0.2 of the waves from the left, the span kept, the row of then at the top again, its signal selected {g1}')
    # in the viewer's own box: a bookmark by the command (the row at the top now), then ]m and the list from elsewhere
    js("(v.setScroll('window'), 0)"); settle(page); js("(v.bodyEl.scrollTop = 1500, 0)"); settle(page)
    top2 = js("v.topNow()")
    n2 = js(f"(await v.run([{{op: 'bookmark', t: v.t0 + v.span / 2, signal: {json.dumps(sig)}, text: 'two'}}]))[0].n")
    t2 = js(f"v.bms.find(b => b.n === {n2}).top")   # the command: top only as given (its file twin has no screen)
    js(f"(v.run([{{op: 'bookmark', n: {n2}, top: v.topNow()}}]), 0)"); settle(page)
    check(t2 is None and js(f"v.bms.find(b => b.n === {n2}).top") == top2 and top2 != top1,
          f'the command: no top of its own, top: v.topNow() the row at the top of the box {t2} {top2}')
    js("(v.bodyEl.scrollTop = 0, v.t0 = v.M.t0, v.cursor = v.M.t0, v.draw(), v.canvas.focus({preventScroll: true}), 0)"); settle(page)
    want = sorted([(b1['t'], top1), (js(f"v.bms.find(b => b.n === {n2}).t"), top2)])
    page.keyboard.press(']'); page.keyboard.press('m'); settle(page)
    g2 = [js("v.cursor") == want[0][0], js(frac), js(f"{at}({json.dumps(want[0][1])})")]
    check(g2[0] and g2[1] == 0.2 and abs(g2[2]) <= 1, f']m in the own box: the first bookmark in time, where it was made {g2}')
    js("(v.bodyEl.scrollTop = 0, v.draw(), 0)"); settle(page)
    page.keyboard.press('g'); page.keyboard.press('m'); settle(page)
    page.locator('.wv-marks button[data-i]').last.click(); settle(page)
    g3 = [js("v.cursor") == want[1][0], js(frac), js(f"{at}({json.dumps(want[1][1])})"), page.locator('.wv-marks').count()]
    page.keyboard.press('Escape'); settle(page)
    check(g3[0] and g3[1] == 0.2 and abs(g3[2]) <= 1 and g3[3] == 1, f'Markers…: a bookmark picked, the waves where it was made, the list stays {g3}')
    # its module folded since: the way to the row opened, the row at the top; bookmarkLeft 0.5: in the middle
    js("(v.collapseAll(), v.bodyEl.scrollTop = 0, v.S.bookmarkLeft = 0.5, v.draw(), 0)"); settle(page)
    r = js(f"(await v.run([{{op: 'bookmark', n: {t1}, go: true}}]))[0]")
    g4 = [js(frac), js(f"{at}({json.dumps(top1)})"), r.get('top') == top1, js("v.bms.length"),
          js("v.bodyEl.scrollHeight - v.bodyEl.clientHeight - v.bodyEl.scrollTop <= 1")]
    check(g4[0] == 0.5 and g4[1] is not None and (abs(g4[1]) <= 1 or g4[1] > 0 and g4[4]) and g4[2] and g4[3] == 2,
          f'go to it with every module folded: the way opened, its row at the top as far as the scroll goes; bookmarkLeft 0.5: in the middle; '
          f'go changes nothing of it {g4} {r}')
    # a bookmark of before (no top): its signal brought into the box
    js("(v.S.bookmarkLeft = 0.2, v.expandAll(), 0)"); settle(page)
    last = js("WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig').pop().full")
    js(f"(await v.run([{{op: 'bookmark', n: 9, t: v.M.t0 + v.span, signal: {json.dumps(last)}, top: null}}]), v.bodyEl.scrollTop = 0, v.draw(), 0)"); settle(page)
    page.keyboard.press('9'); settle(page)
    check(js(f"{seen}({json.dumps(last)})") and js("v.bms.find(b => b.n === 9).top") is None,
          f'a bookmark without a top: its signal brought into sight (its row between the axis and the bottom of the box)')
    st = js("v.bookmarks()")
    check([b.get('top') for b in st] == [top1, top2, None], f'the bookmarks\' JSON keeps top (Save, this browser) {st}')
    # its signal's module folded since (the row of then elsewhere): opened, the signal selected and there, the row at the top
    fold = f"(() => {{ const s = v.M.rows.find(r => r.full === {json.dumps(sig)}); v.sel = null; v.fold(s.anc[s.anc.length - 1], true); return 0; }})()"
    js(f"({fold}, v.bodyEl.scrollTop = 0, v.draw(), v.canvas.focus({{preventScroll: true}}), 0)"); settle(page)
    page.keyboard.press(str(t1)); settle(page)
    g5 = [js("v.sel && v.sel.full"), js(f"WaveLens.internal.peek(v).vis.some(r => r.full === {json.dumps(sig)})"), js(f"{at}({json.dumps(top1)})")]
    check(g5[0] == sig and g5[1] and g5[2] is not None and abs(g5[2]) <= 1, f'its signal folded since: opened and selected, the row of then at the top {g5}')
    # its row of then gone (a name no row has now: an older page's): the signal brought into sight instead, opened
    js(f"(v.bms.find(b => b.n === {t1}).top = 'no.such.row', {fold}, v.bodyEl.scrollTop = 0, v.draw(), v.canvas.focus({{preventScroll: true}}), 0)")
    settle(page); page.keyboard.press(str(t1)); settle(page)
    g6 = [js("v.sel && v.sel.full"), js(f"{seen}({json.dumps(sig)})")]
    check(g6 == [sig, True], f'its row of then gone: its signal opened, selected and brought into sight {g6}')
    js(f"(v.bms.find(b => b.n === {t1}).top = {json.dumps(top1)}, 0)")
    # the list under the waves: "cursor" moves a bookmark to the cursor and to the screen of now (its top as a new one's)
    js("(v.bodyEl.scrollTop = 900, v.cursor = v.t0 + v.span / 3, v.draw(), 0)"); settle(page)
    now = js("[v.topNow(), v.cursor]")
    page.locator('.wv').first.locator('.notes li[data-n="9"] button[data-bm=here]').click(); settle(page)
    g7 = js("(b => [b.top, b.t])(v.bms.find(b => b.n === 9))")
    check(now[0] and g7 == now, f'the list\'s cursor button: the bookmark at the cursor and the row at the top now {g7} {now}')
    check(not errs, f'no page errors {errs}')
    page.close()
    # other sizes: a low window (the waves a few rows high) and a narrow one, with the page's scroll
    for w, h in ((1200, 320), (480, 600)):
        page = browser.new_page(viewport={'width': w, 'height': h})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.goto(pg.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
        js("(v.setScroll('page'), v.expandAll(), v.zoom(0.1, 0.5), 0)"); settle(page)
        page.evaluate("window.scrollTo(0, document.querySelector('.wv .wcol').getBoundingClientRect().top + scrollY + 500)"); settle(page)
        top = js("v.topNow()"); n = js("(v.cursor = v.t0 + v.span * 0.6, v.mark('size'))")
        page.evaluate("window.scrollTo(0, 0)"); js("(v.t0 = v.M.t0, v.draw(), v.canvas.focus({preventScroll: true}), 0)"); settle(page)
        page.keyboard.press(str(n)); settle(page)
        g = [top, js(f"{at}({json.dumps(top)})"), js(frac)]
        check(top and g[1] is not None and abs(g[1]) <= 1 and g[2] == 0.2, f'{w}×{h}: the row of then at the top again, the bookmark 0.2 from the left {g}')
        check(not errs, f'{w}×{h}: no page errors {errs}')
        page.close()

def fsm_panel(browser, build):
    """The state machines (wavelens/src/fsm.js) on fsm_all.html (the FSM example's VCD, its types beside it): T opens the
    tree of the modules with an FSM, each FSM with its state at the cursor and its states reached; a click goes to one
    folded away; Only FSMs keeps them and the modules on the way; Add to view puts them into a view the find's Mask made;
    the command fsm, the fields, the state saved and loaded, undo; ✕ in the bar."""
    pg = build / 'examples' / 'fsm' / 'fsm_all.html'
    if not need(pg, how='make examples'):
        return
    print('the FSM panel')
    page = browser.new_page(viewport={'width': 1360, 'height': 1000})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(pg.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    run = lambda ops: page.evaluate("ops => document.querySelector('.wv').waveView.run(ops)", ops)
    sigs = "WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig').map(r => r.full)"
    check(js("[v.fsms(false).map(r => r.full), v.fsms().length]") == [['fsm_tb.state', 'fsm_tb.u_rx.state'], 3] and
          page.locator('.wv .bar button[data-act=fsms]').count() == 1, 'the FSMs: the two state buses, the struct\'s state field among the fields; FSMs in the bar')
    js("(v.collapseAll(), 0)")
    js("(v.canvas.focus(), 0)"); page.keyboard.press('Shift+T'); settle(page)
    rows = page.locator('.wv-fsms .mn')
    tree = [rows.nth(i).locator('.nm').inner_text() for i in range(rows.count())]
    st = page.locator('.wv-fsms .mn.fs').first.locator('.ct').inner_text()
    check(tree == ['fsm_tb', 'state', 'u_rx', 'state'] and st == '5/5', f'T: the modules with an FSM and their FSMs, the states reached of the table {tree} {st}')
    page.locator('.wv-fsms .mn.fs').nth(1).click(); settle(page)
    check(js("[v.sel && v.sel.full, WaveLens.internal.peek(v).vis.includes(v.sel)]") == ['fsm_tb.u_rx.state', True], 'a click: the FSM opened, selected')
    # the details' rows by the keys: ↓ Enter the next time of that change, shift+Enter back, → ← the tabs, Esc the tree
    page.locator('.wv-fsms .fdt button[data-t=changes]').click(); page.locator('.wv-fsms .fdb tr[data-r]').nth(0).click(); settle(page)
    for k in ('ArrowDown', 'ArrowDown', 'Enter'):
        page.keyboard.press(k)
    settle(page); c1 = js("v.cursor"); page.keyboard.press('Enter'); settle(page); c2 = js("v.cursor"); page.keyboard.press('Shift+Enter'); settle(page)
    dk = [js("document.activeElement.dataset.r"), page.locator('.wv-fsms .fdb tr.fk').inner_text().split()[0:3], c1, c2, js("v.cursor")]
    page.keyboard.press('ArrowRight'); dk.append(js("v.fsmP.tab")); page.keyboard.press('ArrowLeft'); dk.append(js("v.fsmP.tab"))
    page.keyboard.press('Escape'); dk.append(js("!!document.activeElement.closest('.wv-fsms .mtr')"))
    check(dk[0] == '2' and dk[1] == ['DATA', '→', 'STOP'] and dk[2] == 385000 and dk[3] > dk[2] and dk[4] == dk[2] and dk[5:] == ['graph', 'changes', True],
          f'the details by the keys: ↓ ↓ Enter the next DATA → STOP, again the one after, shift+Enter back; → ← the tabs; Esc the tree {dk}')
    page.locator('.wv-fsms .fdt button[data-t=states]').click()
    page.locator('.wv-fsms .mn.fs').nth(1).click(); settle(page)
    page.locator('.wv-fsms .mh b').click(); page.keyboard.press('ArrowUp'); up = js("document.activeElement.dataset.i")
    check(up == '2' and page.locator('.wv-fsms .rz').count() == 8, f'a click on the header: ↑ goes on in the tree (from the FSM clicked); its 8 edges and corners {up}')
    page.locator('.wv-fsms button[data-a=only]').click(); settle(page)
    only = js(sigs)
    check(only == ['fsm_tb.state', 'fsm_tb.u_rx.state'] and 'FSMs only: 2' in js("v.root.querySelector('.bar button[data-act=fsmx]').textContent"),
          f'Only FSMs: the two of them, the modules on the way, the bar says it {only}')
    js("(v.setFsm(null), 0)")
    run([{'op': 'find', 'query': 'rxd', 'mask': True, 'regex': False}])
    masked = js(sigs)
    page.locator('.wv-fsms button[data-a=add]').click(); settle(page)
    added = js(sigs)
    check(set(masked) == {'fsm_tb.rxd', 'fsm_tb.u_rx.rxd'} and added == ['fsm_tb.rxd', 'fsm_tb.state', 'fsm_tb.u_rx.rxd', 'fsm_tb.u_rx.state'],
          f'Add to view: the find\'s Mask kept, the FSMs in it too {masked} {added}')
    saved = js("v.state().fsm")
    run([{'op': 'find', 'query': ''}])
    res = run([{'op': 'fsm', 'mode': 'only', 'signals': '*u_rx.state'}, {'op': 'fsm', 'fields': True, 'mode': 'only'}, {'op': 'fsm', 'mode': 'odd'}])
    check(saved == {'mode': 'add', 'signals': ['fsm_tb.state', 'fsm_tb.u_rx.state']} and res[0]['fsm'] == {'mode': 'only', 'signals': ['fsm_tb.u_rx.state']} and
          res[1]['fsm']['signals'] == ['fsm_tb.state', 'fsm_tb.status.state', 'fsm_tb.u_rx.state'] and 'only or add' in res[2].get('error', ''),
          f'the state has the layer; the command: one FSM, every one with fields, a wrong mode refused {saved} {res}')
    page.evaluate("(async () => { const v = document.querySelector('.wv').waveView; await v.run([{ op: 'fsm', clear: true }]); v.undo(); })()"); settle(page)
    back = js("v.fsmState() && v.fsmState().signals.length")
    page.evaluate("s => document.querySelector('.wv').waveView.setState(s)", {'wavelens': 'state', 'fsm': {'mode': 'only', 'signals': ['fsm_tb.state', 'tb.nope']}})
    loaded = js("[v.fsmState(), " + sigs + "]")
    page.locator('.wv .bar button[data-act=fsmx]').click(); settle(page)
    check(back == 3 and loaded == [{'mode': 'only', 'signals': ['fsm_tb.state']}, ['fsm_tb.state']] and js("v.fsm") is None and
          page.locator('.wv .bar button[data-act=fsmx]').is_hidden(), f'undo brings the layer back; a state loads it (a path not here left out); ✕ clears it {back} {loaded}')
    # review V: a state with the layer takes the selection off a signal it leaves out (A13); a plugin's row above every
    # module stays with Only FSMs, as with Only (C10); ↑ ↓ in the panel keep its rows (A14); going to an FSM switches the
    # find's Open off, so the next search does not fold it again (A12)
    js("(v.setFsm(null), v.select(v.M.rows.find(r => r.full === 'fsm_tb.rxd')), 0)")
    page.evaluate("s => document.querySelector('.wv').waveView.setState(s)", {'wavelens': 'state', 'fsm': {'mode': 'only', 'signals': ['fsm_tb.state']}})
    gone = js("v.sel")
    js("(v.extraRows.push(g => g ? [] : [{ type: 'sig', name: 'fx', full: 'fx', width: 1, tr: [{ t: 0, k: '0' }], gaps: [] }]), v.setFsm({ mode: 'only' }), 0)")
    fx = js(sigs)
    js("(v.extraRows.pop(), v.setFsm(null), 0)")
    check(gone is None and fx == ['fx', 'fsm_tb.state'], f'a state with the layer: the selection left out goes; Only FSMs keeps a plugin\'s row on top {gone} {fx}')
    js("(v.fsmPanel(true), 0)"); settle(page)
    page.evaluate("(window.fsmRow = document.querySelector('.wv-fsms .mn'), document.querySelector('.wv').waveView.fsmP.focusRow(0), 0)")
    page.keyboard.press('ArrowDown'); page.keyboard.press('ArrowDown'); settle(page)
    same = page.evaluate("[window.fsmRow === document.querySelector('.wv-fsms .mn'), document.activeElement.dataset.i, document.activeElement.tabIndex]")
    check(same == [True, '2', 0], f'↑ ↓ in the panel: the focus moves, its rows stay (no new HTML each step) {same}')
    folded = js("""(() => { const u = Object.values(v.M.groups).find(g => g.path === 'fsm_tb.u_rx'); v.findOpen = true;
        v.find('status'); const before = WaveLens.internal.peek(v).collapsed.has(u.id); v.goFsm('fsm_tb.u_rx.state'); v.find('statu');
        return [before, WaveLens.internal.peek(v).collapsed.has(u.id), v.findOpen, WaveLens.internal.peek(v).vis.some(r => r.full === 'fsm_tb.u_rx.state')]; })()""")
    js("(v.find(''), 0)")
    check(folded == [True, False, False, True], f'an FSM gone to during a search with Open: its module stays open at the next search (Open off) {folded}')
    # Sources… with two types files (A9): no exception, the panel open again in the new viewer with its filter (C3)
    page.locator('.wv-fsms .mq').fill('rx'); settle(page)
    two = page.evaluate("""(async () => { let v = document.querySelector('.wv').waveView;
        const f = (name, sig) => new File([JSON.stringify({ wavelens: 'types', producer: { tool: name }, signals: sig })], name);
        v = await v.setSources([f('a.types.json', { 'fsm_tb.rxd': { width: 1, enum: { 0: 'LO', 1: 'HI' } } }),
          f('b.types.json', { 'fsm_tb.u_rx.rst_n': { width: 1, enum: { 0: 'RESET', 1: 'RUN' } } })]);
        return [v.fsms().map(r => r.full), !!v.fsmP, v.fsmP && v.fsmP.q, v.root.querySelector('.bar .toast').textContent]; })()""")
    check('fsm_tb.rxd' in two[0] and 'fsm_tb.u_rx.rst_n' in two[0] and two[1] and two[2] == 'rx' and '2 typed paths (b.types.json' in two[3],
          f'Sources… with two types files: both read; the FSM panel open again with its filter, the new FSMs in it {two}')
    # the states reached (A11): x and z are none, a value with x bits is none; a clock-sampled row counts too
    seen = page.evaluate("""(() => { const el = document.createElement('div'); document.body.append(el);
        const e = { 1: 'A', 16: 'B', 2: 'C' }, doc = { signal: [{ name: 'ex', width: 8, enum: e, tv: [[0, '10'], [10, "'b0001xxxx"], [20, 'x'], [30, '2']] },
          { name: 'cs', width: 8, enum: e, wave: '===', data: ['16', '2', '2'] }] };
        const v = new WaveLens.WaveView(el, doc, {}); v.fsmPanel(true);
        const out = v.fsms().map(r => v.fsmP.seenOf(r)), P = v.fsmP, named = [P.mine.map(r => r.name), P.others];
        P.el.querySelector('.fa').click(); out.push(named, P.mine.map(r => r.name)); v.destroy(); el.remove(); return out; })()""")
    check(seen == [[2, 3], [2, 3], [['cs'], 1], ['ex', 'cs']], f'the states reached: an exact row with x bits and a clock-sampled row count their own '
          f'values; the panel lists the ones named as a state (cs), all enums the others too (C8) {seen}')
    # the features of review V: an FSM's details (X1: its states, the times it entered each, its changes; X2: the diagram
    # of them), a click there takes the cursor to the next entry / change; fsm_stats and fsm_go; the right button's menu and
    # a box over the tree (X6)
    page.goto(pg.as_uri()); page.wait_for_load_state('networkidle')
    js("(v.fsmPanel(true), 0)"); settle(page)
    page.locator('.wv-fsms .mn.fs').nth(1).click(); settle(page)
    det = js("[v.fsmP.det && v.fsmP.det.full, document.querySelector('.wv-fsms .fdn').textContent, document.querySelector('.wv-fsms .fdm').textContent, "
             "[...document.querySelectorAll('.wv-fsms .fst tr[data-k]')].map(r => r.firstChild.textContent)]")
    page.locator('.wv-fsms .fst tr[data-k="2"]').evaluate("el => el.click()"); settle(page)
    went = js("[v.cursor, v.sel && v.sel.full]")
    page.locator('.wv-fsms .fdt button[data-t=changes]').click(); settle(page)
    ch = js("[...document.querySelectorAll('.wv-fsms .fst tr[data-f]')].map(r => r.dataset.f + '>' + r.dataset.t + ' ' + r.children[3].textContent)")
    page.locator('.wv-fsms .fdt button[data-t=graph]').click(); settle(page)
    gr = js("[document.querySelectorAll('.wv-fsms .fsg .fn').length, document.querySelectorAll('.wv-fsms .fsg .fa').length, "
            "document.querySelector('.wv-fsms .fsg .fn.now') && document.querySelector('.wv-fsms .fsg .fn.now').dataset.k]")
    page.locator('.wv-fsms .fsg .fa[data-f="3"][data-t="4"] path.hit').dispatch_event('click'); settle(page)
    arc = js("v.cursor")
    check(det == ['fsm_tb.u_rx.state', 'u_rx.state', '5/5 states · 9 changes', ['IDLE', 'START', 'DATA', 'STOP', 'ERROR']] and went == [65000, 'fsm_tb.u_rx.state']
          and '0>1 2' in ch and '3>4 1' in ch and len(ch) == 6 and gr == [5, 6, '2'] and arc == 905000,
          f'an FSM\'s details: its states, a click the next entry; its changes; the diagram, a click on an arc the next time {det} {went} {ch} {gr} {arc}')
    res = page.evaluate("""async () => { const v = document.querySelector('.wv').waveView; return await v.run([{ op: 'fsm_stats', signal: 'fsm_tb.u_rx.state' },
      { op: 'fsm_go', signal: 'fsm_tb.u_rx.state', state: 'STOP', first: true }, { op: 'fsm_go', signal: 'fsm_tb.u_rx.state', from: 'DATA', to: 'STOP' },
      { op: 'fsm_go', signal: 'fsm_tb.state', state: 'NOPE' }]); }""")
    st = res[0]
    check([x['entries'] for x in st['states']] == [3, 2, 2, 2, 1] and st['never'] == [] and st['changes'][0]['count'] == 2 and res[1]['t'] == 385000 and
          res[2]['t'] == 865000 and 'never NOPE' in res[3]['error'], f'fsm_stats: the entries of each state, its changes; fsm_go: a state, a change, one it never is {res[1:]}')
    # review VI T8: fsm_go as a table — before, on and after an entry, back, round to the first / the last, the first one, a
    # state by its value or its label, a change, one it never makes
    go = page.evaluate("""async () => { const el = document.createElement('div'); document.body.append(el);
        const doc = { signal: [{ name: 'st', path: 'st', width: 2, enum: { 0: 'A', 1: 'B', 2: 'C' }, tv: [[0, '0'], [10, '1'], [20, '0'], [30, '1'], [40, '2']] }],
          time: { t0: 0, t1: 50 } };
        const v = new WaveLens.WaveView(el, doc, {}), out = [];
        for (const [c, op] of [[0, { state: 'B' }], [10, { state: 'B' }], [30, { state: 'B' }], [30, { state: 'B', dir: -1 }], [5, { state: 'B', dir: -1 }],
            [35, { state: 'B', first: true }], [15, { state: '1' }], [15, { from: 'A', to: 'B' }], [31, { from: 'B', to: 'C', dir: -1 }], [0, { from: 'C', to: 'A' }],
            [0, { state: 'NOPE' }]]) {
          v.setCursor(c); const r = (await v.run([Object.assign({ op: 'fsm_go', signal: 'st' }, op)]))[0];
          out.push(r.error ? 'never' : r.t + (/round/.test(v.root.querySelector('.bar .toast').textContent) ? ' round' : '')); }
        v.destroy(); el.remove(); return out; }""")
    check(go == ['10', '30', '10 round', '10', '30 round', '10', '30', '30', '40 round', 'never', 'never'],
          f'fsm_go: the next entry after the cursor (on one: the one after), back, round to the first and the last, the first, by value, a change {go}')
    # and a run of what one does with the panel: Only FSMs, hide one, undo it, Add an FSM to a view of one signal, Save and
    # Load: the layer and the rows come back
    seq = page.evaluate("""async () => { const v = document.querySelector('.wv').waveView, vis = () => WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig').map(r => r.full);
        const out = [vis().length]; await v.run([{ op: 'fsm', mode: 'only' }]); out.push(vis());
        await v.run([{ op: 'hide', signals: 'fsm_tb.state' }]); out.push(vis()); await v.undo(); out.push(vis());
        await v.run([{ op: 'fsm', clear: true }]); out.push(vis().length);
        await v.run([{ op: 'fsm', mode: 'add', signals: 'fsm_tb.u_rx.state' }, { op: 'only', modules: ['fsm_tb.u_rx'] }]); const st = v.state(), a = vis();
        await v.run([{ op: 'fsm', clear: true }, { op: 'only', clear: true }]); const b = vis().length; await v.setState(st);
        out.push([a.includes('fsm_tb.u_rx.state'), b > a.length, JSON.stringify(vis()) === JSON.stringify(a), JSON.stringify(v.fsmState())]);
        await v.run([{ op: 'fsm', clear: true }, { op: 'only', clear: true }]); return out; }""")
    check(seq[1] == ['fsm_tb.state', 'fsm_tb.u_rx.state'] and seq[2] == ['fsm_tb.u_rx.state'] and seq[3] == seq[1] and seq[4] == seq[0] and
          seq[5][:3] == [True, True, True] and 'fsm_tb.u_rx.state' in seq[5][3],
          f'Only FSMs, Hide, undo, the layer off: as before; Add with Only, Save and Load: the same rows and layer {seq}')
    # review VI T15: the panel over many FSMs (150 modules, 10 each): open, ↓ in its tree, the cursor's states, its DOM —
    # and 10 times more of them grows by about 10 times, not more
    big = page.evaluate("""async () => { const size = async nm => { const el = document.createElement('div'); document.body.append(el);
        const sig = [], e = { 0: 'IDLE', 1: 'RUN', 2: 'DONE' };
        for (let m = 0; m < nm; m++) { const g = ['u' + m]; for (let k = 0; k < 10; k++) g.push({ name: 'state' + k, path: `tb.u${m}.state${k}`, width: 2, enum: e,
          tv: [[0, '0'], [10 + k, '1'], [30 + m, '2']] }); sig.push(g); }
        const v = new WaveLens.WaveView(el, { signal: [['tb', ...sig]] }, {});
        let t = performance.now(); v.fsmPanel(true); const open = performance.now() - t, p = v.fsmP, tree = p.el.querySelector('.mtr'), keys = [];
        p.focusRow(0);
        for (let i = 0; i < 30; i++) { t = performance.now(); tree.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })); keys.push(performance.now() - t); }
        const moved = p.fi; t = performance.now(); v.setCursor(25); const cur = performance.now() - t;
        const n = p.el.querySelectorAll('*').length, fsms = v.fsms().length; v.destroy(); el.remove();
        return { open, key: Math.max(...keys), moved, cur, n, fsms }; };
      return [await size(15), await size(150)]; }""")
    s1, s2 = big
    check(s2['fsms'] == 1500 and s2['moved'] == 30 and s2['open'] < 1500 * SCALE and s2['key'] < 50 * SCALE and s2['cur'] < 500 * SCALE and
          s2['n'] < 12 * s1['n'] and s2['open'] < 25 * max(s1['open'], 5),
          f'1500 FSMs: the panel opens in {s2["open"]:.0f} ms, ↓ in {s2["key"]:.1f} ms at most, the cursor in {s2["cur"]:.0f} ms, {s2["n"]} elements '
          f'(150 FSMs: {s1["n"]}, {s1["open"]:.0f} ms)')
    page.locator('.wv-fsms .mn.mm').first.click(button='right'); settle(page)
    menu = js("[...document.querySelectorAll('.wv-menu button')].map(b => b.querySelector('span').textContent)")
    page.locator('.wv-menu button[data-mm=only]').click(); settle(page)
    only = js(sigs)
    js("(v.setFsm(null), 0)")
    bb = page.locator('.wv-fsms .mrows').bounding_box()
    page.mouse.move(bb['x'] + 40, bb['y'] + 3); page.mouse.down(); page.mouse.move(bb['x'] + 40, bb['y'] + 4 * 22 - 4, steps=6); page.mouse.up(); settle(page)
    box = js("[...v.fsmP.pick].map(r => r.full).sort()")
    check(menu == ['Go to the module', 'Only its FSMs', 'Add its FSMs to the view', 'Pick its FSMs', 'Copy scope path'] and only == ['fsm_tb.state', 'fsm_tb.u_rx.state']
          and box == ['fsm_tb.state', 'fsm_tb.u_rx.state'], f'the right button on a module: Only its FSMs; a box over the tree picks the FSMs in it {menu} {only} {box}')
    check(not errs, 'no page errors (fsm)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    page.close()


def dump(browser, build):
    """A VCD opened in the page (Open…, a file dropped on the viewer): the same waves as mkhtml.py builds from it; ⟳ reads
    it again with the view kept; wavelens/viewer.html starts empty; an FST is refused with what to do."""
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
    vals = "(ts => Object.fromEntries(v.M.rows.filter(r => r.type === 'sig' && r.tr).map(r => [r.full, ts.map(t => (o => o ? o.raw ?? o.k : '')(r.tr[WaveLens.lastLE ? WaveLens.lastLE(r.tr, t) : r.tr.filter(o => o.t <= t).length - 1]))])))([0, 33000, 95000, 150000, 190000])"
    before = js(vals)
    page.locator('.wv input.dfile').first.set_input_files(str(vcd))
    page.wait_for_function("document.querySelector('.wv').waveView && document.querySelector('.wv').waveView.opts.dumpSrc", timeout=60000)
    after = js(vals); info = js("[v.M.title, v.root.querySelector('.bar .toast').textContent, !v.reloadBtn.hidden, document.querySelectorAll('.wv .names .row.bus-g').length]")
    same = [p for p in before if before[p] != after.get(p)]
    check(not same and set(before) <= set(after) and info[0] == 'apb.vcd' and 'signals' in info[1] and info[2] and info[3] > 0,
          f'Open… a VCD: the values of mkhtml.py\'s {len(before)} signals (it leaves constants out: {len(after)} here), the bus port found again; ⟳ shown {info} {same[:3]}')
    js("(v.cursor = 95000, v.t0 = 20000, v.span = 100000, WaveLens.internal.peek(v).collapsed.add(Object.values(v.M.groups).find(g => g.name === 'u_count').id), v.draw(), 0)")
    page.locator('.wv button[data-act=dreload]').first.click()
    page.wait_for_function("document.querySelector('.wv').waveView.root.querySelector('.bar .toast').textContent.includes('signals')", timeout=60000)
    kept = js("[v.cursor, v.t0, v.span, [...WaveLens.internal.peek(v).collapsed].map(id => v.M.groups[id].name)]")
    check(kept[:3] == [95000, 20000, 100000] and 'u_count' in kept[3], f'⟳: the dump read again, the cursor, the window and the folding kept {kept}')
    fst = vcd.with_suffix('.fst')
    if fst.exists():
        page.locator('.wv input.dfile').first.set_input_files(str(fst))
        until(page, "document.querySelector('.wv').waveView.root.querySelector('.bar .toast').textContent.includes('fst2vcd')")
        check('fst2vcd' in js("v.root.querySelector('.bar .toast').textContent") and js('v.M.title') == 'apb.vcd', 'an FST is not read in the page: the toast says fst2vcd / make html, the waves stay')
    page.goto((ROOT / 'wavelens' / 'viewer.html').as_uri()); page.wait_for_load_state('networkidle')
    page.locator('.wv input.dfile').first.set_input_files(str(vcd))
    page.wait_for_function("document.querySelector('.wv').waveView && document.querySelector('.wv').waveView.opts.dumpSrc", timeout=60000)
    rows = page.evaluate("(() => { const v = document.querySelector('.wv').waveView, n = WaveLens.internal.peek(v).namesEl.querySelectorAll('.row[data-r]'), o = WaveLens.internal.peek(v).lay; return [v.M.rows.filter(r => r.type === 'sig').length, [...n].slice(0, 12).every((el, i) => Math.abs(el.getBoundingClientRect().height - o[i].h) < 0.5)]; })()")
    check(rows[0] == len(after) and rows[1], f'wavelens/viewer.html: empty, a VCD opened in it, its names column as tall as the waves\' rows (no page box-sizing needed) {rows}')
    dropped = page.evaluate("""(() => { const r = document.querySelector('.wv'), text = '$timescale 1ns $end $scope module t $end $var wire 1 ! a $end $upscope $end $enddefinitions $end #0 0! #5 1! #9 0!';
        const dt = new DataTransfer(); dt.items.add(new File([text.replace(/ #/g, '\\n#')], 'drop.vcd')); r.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); return 0; })()""")
    page.wait_for_function("document.querySelector('.wv').waveView.M.title === 'drop.vcd'", timeout=30000)
    d = page.evaluate("(v => [v.M.rows.filter(r => r.type === 'sig').map(r => r.full), v.valueAt(v.M.rows.find(r => r.full === 't.a'), 7000)])(document.querySelector('.wv').waveView)")
    check(d == [['t.a'], '1'], f'a VCD dropped on the viewer replaces its waves {d}')
    # dropped again: one live viewer, one wavelens:dump per drop (the old viewer's listeners on the element are gone)
    two = page.evaluate(r"""(async () => { const r = document.querySelector('.wv'); let n = 0; r.addEventListener('wavelens:dump', () => n++);
        const vcd = '$timescale 1ns $end\n$scope module t $end\n$var wire 1 ! b $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n#5\n1!\n';
        const drop = name => { const dt = new DataTransfer(); dt.items.add(new File([vcd], name)); r.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true })); };
        drop('d2.vcd'); await new Promise(f => setTimeout(f, 300)); drop('d3.vcd'); await new Promise(f => setTimeout(f, 300));
        return [n, WaveLens.views().filter(v => v.root === r).length, r.waveView.M.title, r.waveView.canvas.isConnected]; })()""")
    check(two == [2, 1, 'd3.vcd', True], f'dropped twice: one live viewer, one wavelens:dump each, its canvas in the page {two}')
    # a VCD as Questa writes it (no enum tables: reg [1:0], an int-based enum as integer): Sources… names the states from the
    # SystemVerilog sources, the view kept; ⟳ reads them again with the names
    sv = page.evaluate(r"""(async () => { const r = document.querySelector('.wv');
        const vcd = '$timescale 1ns $end\n$scope module tb $end\n$var reg 2 " state [1:0] $end\n$var integer 32 # color $end\n$upscope $end\n' +
          '$enddefinitions $end\n#0\nb0 "\nb11 #\n#10\nb1 "\nb111 #\n#20\nb10 "\nb1100 #\n';
        const dt = new DataTransfer(); dt.items.add(new File([vcd], 'questa.vcd')); r.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
        await new Promise(f => setTimeout(f, 400)); let v = r.waveView; const before = v.valueAt(v.M.rows.find(x => x.full === 'tb.color'), 15000);
        v.cursor = 12000; v.draw();
        v = await v.setSources([new File(['module tb; typedef enum logic [1:0] {IDLE, START, DATA, STOP} state_t; typedef enum {RED = 3, GREEN = 7, ' +
          'BLUE = 12} color_t; state_t state; color_t color; endmodule'], 'tb.sv')]);
        const at = t => ['tb.state', 'tb.color'].map(p => v.valueAt(v.M.rows.find(x => x.full === p), t));
        const named = at(15000), cur = v.cursor; await v.reloadDump(); v = r.waveView;
        const kept = at(25000);
        // the sources changed (review IV A7): picked again, the new names replace the ones the sources gave; none: numbers again
        v = await v.setSources([new File(['module tb; typedef enum logic [1:0] {OFF, WARM, HOT, BURN} state_t; state_t state; endmodule'], 'tb.sv')]);
        const renamed = at(25000)[0];
        v = await v.setSources([new File(['module tb; endmodule'], 'empty.sv')], true);
        return [before, named, cur, kept, renamed, at(25000)[0]]; })()""")
    # a new simulation under the same name (review IV B1, B9, review C1/C8): ⟳ of the changed file evaluates the new run
    # (req |=> ack: the first run passes, the second has no ack: req is sampled at cycle 3, the attempt fails at 4), the bookmark and the
    # window kept; a dump dropped again too. The fingerprint tells apart waves that serialise alike without separators
    rerun = page.evaluate(r"""(async () => { const r = document.querySelector('.wv');
        const run = ack => '$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! clk $end\n$var wire 1 " req $end\n$var wire 1 # ack $end\n' +
          '$upscope $end\n$enddefinitions $end\n#0\n0!\n0"\n0#\n' + Array.from({ length: 12 }, (_, i) => `#${i * 10 + 5}\n1!\n` +
          (i === 2 ? '1"\n' : i === 3 ? '0"\n' + (ack ? '1#\n' : '') : i === 4 ? '0#\n' : '') + `#${i * 10 + 10}\n0!\n`).join('');
        let cur = new File([run(true)], 'run.vcd');
        const handle = { kind: 'file', name: 'run.vcd', getFile: async () => cur };   // what ⟳ reads again (the VS Code tab's way)
        const stats = async () => { const p = SVA.panels().find(x => x.v === r.waveView); await SVA.ready(); await p.queue; await new Promise(f => setTimeout(f, 300));
          await p.queue; const b = p.bindings.find(x => x.assert === 'a_ra'), a = b && b.results && b.results.assertions[0], st = a && a.stats;
          return st ? [st.pass, st.fail, (a.attempts || []).filter(x => x.result === 'fail').map(x => [x.start, x.failed_at ?? x.end])] : [b && b.state, b && b.error]; };
        let v = await r.waveView.openDump(cur, handle);
        await SVA.loadFiles([{ name: 'ra.sva', text: 'module tb (input logic clk, input logic req, input logic ack); ' +
          'a_ra: assert property (@(posedge clk) req |=> ack); endmodule' }]);
        await SVA.ready(); SVA.panels().find(x => x.v === r.waveView).bind('a_ra', 'tb');
        const first = await stats();
        v = r.waveView; v.mark('kept'); v.t0 = 20000; v.span = 50000; v.draw();
        cur = new File([run(false)], 'run.vcd'); await v.reloadDump(); v = r.waveView;
        const second = await stats(), kept = [v.bms.some(b => b.text === 'kept'), v.t0, v.span];
        const dt = new DataTransfer(); dt.items.add(new File([run(true)], 'run.vcd')); r.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
        await new Promise(f => setTimeout(f, 400)); const third = await stats();
        const id = doc => SVA.waveId(WaveLens.parse(doc)), d8 = tv => ({ signal: [{ name: 'd', width: 8, tv }], time: { t0: 0, t1: 100, unit: 'ps' } });
        const cs = raw => ({ signal: [{ name: 'f', width: 32, wave: '=', data: ['1'], raw: [raw] }] });   // a clock-sampled row: its raw
        const fp = [id(d8([[0, '0'], [1, '23']])) !== id(d8([[0, '0'], [12, '3']])), id(d8([[0, "'b000010x1"]])) !== id(d8([[0, "'b000000x1"]])),
          id(cs('3f800001')) !== id(cs('3f800002'))];
        return [first, second, kept, third, fp]; })()""")
    # an older Open… still reading does not replace a newer one (review IV B12); a compare that fails says the one before stays (B26)
    late = page.evaluate(r"""(async () => { const r = document.querySelector('.wv'), v = r.waveView;
        const vcd = n => `$timescale 1ns $end\n$scope module tb $end\n$var wire 1 ! ${n} $end\n$upscope $end\n$enddefinitions $end\n#0\n0!\n#50\n1!\n`;
        const slow = (n, ms) => ({ name: n + '.vcd', text: () => new Promise(f => setTimeout(() => f(vcd(n)), ms)) });
        const a = v.openDump(slow('slow', 400)); await new Promise(f => setTimeout(f, 50)); await v.openDump(new File([vcd('b')], 'fast.vcd')); await a;
        const order1 = r.waveView.M.title;
        const p1 = r.waveView.openDump(slow('first', 150)), p2 = r.waveView.openDump(slow('later', 400)); await p1; await p2;   // the first read ends first
        const w = r.waveView, title = [order1, w.M.title], n = WaveLens.views().filter(x => x.root === r).length;
        w.useSources({ enums: { x: { 0: 'E0' } }, fields: {}, notes: [], files: 1 }, 'workspace');
        w.useSources({ enums: {}, fields: { x: [{ name: 'f', msb: 0, lsb: 0 }] }, notes: [], files: 1 }, 'manual');
        const merged = [Object.keys(w.opts.sv.enums), Object.keys(w.opts.sv.fields)];
        await w.setSources(['module m; typedef enum {A = 1 << 2, B} t_t; t_t later; endmodule']);
        const noted = r.querySelector('.bar .toast').textContent; w.useSources(null, 'workspace'); w.useSources(null, 'manual');
        await w.compare(new File([vcd('b').replace('1!', '0!')], 'other.vcd'));
        await w.compare(new File([vcd('b').replace('#0', '#900000').replace('#50', '#900050')], 'far.vcd'));
        return [title, n, w.cmp && w.cmp.name, r.querySelector('.bar .toast').textContent, merged, noted]; })()""")
    check(late[:3] == [['fast.vcd', 'later.vcd'], 1, 'other.vcd'] and 'still compared with other.vcd' in late[3],
          f'the latest Open… stays, whichever read ends first; a failed compare says which one stays {late[:4]}')
    check(late[4] == [[], ['x']] and 'not used' in late[5] and 't_t' in late[5],
          f'the picked sources win a name over the workspace\'s across enum / struct; notes of picked sources said though nothing applies {late[4:]}')
    check(rerun[0] == [1, 0, []] and rerun[1] == [0, 1, [[3, 4]]] and rerun[2] == [True, 20000, 50000] and rerun[3][:2] == [1, 0] and rerun[4] == [True, True, True],
          f'a new run under the same name (⟳ of the changed file, a drop) is evaluated again, the bookmark and the window kept; distinct fingerprints {rerun}')
    check(sv[0] == '7' and sv[1] == ['START', 'GREEN'] and sv[2] == 12000 and sv[3] == ['DATA', 'BLUE'],
          f'a Questa VCD: an integer reads as decimal; Sources… names the states (the cursor kept), ⟳ keeps the names {sv}')
    check(sv[4] == 'HOT' and sv[5] == '2', f'Sources… again: the new names replace the sources\' old ones; sources without them: the number again {sv[4:]}')
    # Questa's VCD of the corpus and its types file (tools/questa/wavelens_types.tcl): Sources… with the .json names every path
    # its own way (four leaf states of four widths, a struct with an enum field), the plain `state` stays a number, the sources'
    # names are not used beside it
    T = ROOT / 'tests' / 'unit' / 'types'
    page.locator('.wv input.dfile').first.set_input_files(str(T / 'questa.vcd'))
    page.wait_for_function("document.querySelector('.wv').waveView.M.title === 'questa.vcd'", timeout=30000)
    page.locator('.wv input.srcfile').first.set_input_files([str(T / 'questa.types.json'), str(T / 'types_pkg.sv')])
    page.wait_for_function("document.querySelector('.wv').waveView.M.rows.some(r => r.full === 'types_tb.u_l3.state' && r.enum)", timeout=30000)
    ty = js("""(r => [r('types_tb.u_l3.state').enum[7], r('types_tb.gen[1].u_l.state').enum[31], !!r('types_tb.u_plain.state').enum,
        v.M.rows.filter(x => x.full.startsWith('types_tb.o.')).map(x => x.name).join(','), v.root.querySelector('.bar .toast').textContent])
        (n => v.M.rows.find(x => x.full === n))""")
    check(ty[:4] == ['L_LAST', 'L_LAST', False, 'oh,in.st,in.code,pair,flag'] and 'typed paths' in ty[4] and '2 not used' in ty[4],
          f'Sources… with a types file: each path its own table (widths 3 and 5), the plain state a number, a struct\'s fields; the union and the .sv not read: notes {ty}')
    # the types inspector (X4: the right button's Type…, the command types), the root map ("map": the dump's scopes as the
    # types name them) and the run's fingerprint (X5: a types file of another day, an instance the dump does not have)
    tj = json.loads((T / 'questa.types.json').read_text())
    other = dict(tj, describe={k.replace('types_tb.', 'tb.', 1): x for k, x in tj['describe'].items()}, map={'types_tb': 'tb'},
                 producer=dict(tj['producer'], date='2026-10-01T10:00:00'), instances={'tb': 'types_tb', 'tb.u_gone': 'leaf', 'tb.u_l2': 'leaf'})
    ins = page.evaluate("""async t => { let v = document.querySelector('.wv').waveView;
        v = await v.setSources([new File([JSON.stringify(t)], 'other.types.json')], true);
        const o = await v.run([{ op: 'types', signals: ['types_tb.state', 'types_tb.u_plain.state', 'types_tb.clk'] }]);
        const r = v.M.rows.find(x => x.full === 'types_tb.state'), box = v.typesBox(r, 50, 50).why, shown = document.querySelector('.wv-types').innerText;
        v.closeMenu(); return [o[0].types.map(x => x.status), o[0].types[0].why, o[0].run, box, shown.includes('run:') || shown.includes('day')]; }""", other)
    check(ins[0] == ['typed', 'plain', 'plain'] and "types_tb.state as the types name it" in ins[1] and len(ins[2]) == 2 and '23 days before' in ins[2][0] and
          'tb.u_gone' in ins[2][1] and ins[3] == ins[1] and ins[4], f'Type…: a path through the map, a plain vector the types know; the run: another day, '
          f'an instance not in the dump {ins}')
    # the bar of viewer.html: the version, ◐ (no theme button of the page's own), the theme kept in this browser
    th = page.evaluate("""() => { const b = document.querySelector('.wv button[data-act=theme]'); b.click(); b.click();
        return [document.querySelector('.wv .bar .ver').textContent, document.documentElement.dataset.theme, localStorage.getItem('wavelens-theme')]; }""")
    check(th == [WL_VERSION, 'white', 'white'], f'viewer.html: the version in the bar; ◐ auto -> light -> white, kept in this browser {th}')
    page.evaluate("localStorage.removeItem('wavelens-theme'); WaveLens.setTheme('auto')")
    check(not errs, 'no page errors (dump)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    page.close()


def log_panel(browser, build):
    """The log under the viewer (log.js): hidden until something is done in the page; a dump read, the types taken said
    there; a types file or a saved state that is not JSON: an error with its line, column and a caret, the log opened;
    folded: the last entry and the counts; Problems, Clear; "log": false never shows it; the place of an error from the
    messages of V8, Firefox and an end too soon."""
    viewer, T = ROOT / 'wavelens' / 'viewer.html', ROOT / 'tests' / 'unit' / 'types'
    print('the log')
    page = browser.new_page(viewport={'width': 1200, 'height': 800})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(viewer.as_uri()); page.wait_for_load_state('networkidle')
    js = lambda e, *a: page.evaluate(f"async a => {{ const v = document.querySelector('.wv').waveView; return {e}; }}", *a)
    strip = "(el => [el.hidden, el.querySelector('.lf') && el.querySelector('.lf').getAttribute('aria-expanded'), el.innerText])(document.querySelector('.wv .wlog'))"
    check(js(strip)[0] and js('v.logList().length') == 0, 'the log: hidden on a page where nothing was done yet')
    page.locator('.wv input.dfile').first.set_input_files(str(T / 'questa.vcd'))
    page.wait_for_function("document.querySelector('.wv').waveView.M.title === 'questa.vcd'")
    got = js(strip)
    check(not got[0] and got[1] == 'false' and 'questa.vcd: 29 of 29 signals, 1ns' in got[2], f'Open… a dump: the log shown folded, its line the read {got}')
    good = (T / 'questa.types.json').read_text(encoding='utf-8')
    bad = good.replace('"types_tb.state":', '"types_tb.state"', 1)
    js("(await v.setSources([new File([a], 'questa.types.json')]), 0)", bad)
    e = js("[v.logList().slice(-1)[0], document.querySelector('.wv .wlog .lj').innerText, document.querySelector('.wv .wlog .lf').getAttribute('aria-expanded')]")
    j = e[0].get('json') or {}
    check(e[0]['level'] == 'error' and 'not a types file at line 27, column 22' in e[0]['text'] and (j.get('line'), j.get('col')) == (27, 22) and
          e[1].startswith('questa.types.json:27:22\n') and e[1].endswith('\n' + ' ' * 21 + '^') and e[2] == 'true',
          f'a types file that is not JSON: an error with its line and column, the line and a caret under it, the log opened {e[0]["text"]!r} {e[1]!r}')
    js("(await v.setSources([new File([a], 'questa.types.json')]), 0)", good)
    page.wait_for_function("document.querySelector('.wv').waveView.M.rows.some(r => r.full === 'types_tb.state' && r.enum)")
    got = js("v.logList().map(e => e.level + ' ' + e.text)")
    check(any(x.startswith('ok questa.types.json: 9 typed paths') for x in got) and 'ok labels or fields for 9 signals' in got,
          f'the types taken: their paths and the signals labelled, in the log {got[-4:]}')
    page.locator('.wv .wlog button[data-l=only]').click()
    only = js("[...document.querySelectorAll('.wv .wlog .lb > li')].map(li => li.className)")
    page.locator('.wv .wlog button[data-l=fold]').click()
    fold = js(strip)
    check(set(only) == {'lv-error', 'lv-warning'} and fold[1] == 'false' and '✖ 1' in fold[2] and 'labels or fields for 9 signals' in fold[2],
          f'Problems: only the errors and warnings; folded: the counts and the last entry {only} {fold}')
    st = js("(await v.loadState(a), v.logList().slice(-1)[0])", '{\n  "from": 1,,\n}')
    check(st['level'] == 'error' and (st['json']['line'], st['json']['col']) == (2, 13) and 'not JSON at line 2, column 13' in st['text'],
          f'Load… of a state that is not JSON: its line and column {st}')
    js("(v.logClear(), 0)")
    check(js("v.logList().length") == 0 and not js(strip)[0], 'Clear: an empty log, still shown')
    js("(WaveLens.configure({ log: false }), 0)")
    check(js(strip)[0], '"log": false: never shown')
    js("(WaveLens.configure({ log: 'auto' }), 0)")
    w = js("a.map(([t, m]) => WaveLens.internal.jsonWhere(t, new Error(m)))", [
        ['{\n "a" 1}', "JSON.parse: expected ':' after property name in object at line 2 column 6 of the JSON data"],
        ['{\n "a" 1}', 'Unexpected number in JSON at position 7'], ['{"a": [1,', 'Unexpected end of JSON input'],
        ['{', "JSON Parse error: Expected '}'"]])
    check([x and [x['line'], x['col']] for x in w] == [[2, 6], [2, 6], [1, 10], None],
          f'the place of a JSON error from the messages of Firefox, V8 (a position), an end too soon; none from Safari {w}')
    check(not errs, 'no page errors (log)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    page.close()


def int_enums(browser, build):
    """A Questa 2023 VCD writes a variable of an enum type as integer 32 (tests/unit/types/int_enum.vcd): its types file
    (Sources…) labels the integers by their codes, they are FSMs; a reg of 32 bits stays a number; a value no code of
    its enum and only x (a VCD of wlf2vcd) are said in the log; Type… tells it; a real of the design is no note."""
    T = ROOT / 'tests' / 'unit' / 'types'
    print('enums on integers of the dump')
    page = browser.new_page(viewport={'width': 1200, 'height': 800})
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto((ROOT / 'wavelens' / 'viewer.html').as_uri()); page.wait_for_load_state('networkidle')
    page.locator('.wv input.dfile').first.set_input_files(str(T / 'int_enum.vcd'))
    page.wait_for_function("document.querySelector('.wv').waveView.M.title === 'int_enum.vcd'")
    page.locator('.wv input.srcfile').first.set_input_files(str(T / 'int_enum.types.json'))
    page.wait_for_function("document.querySelector('.wv').waveView.M.rows.some(r => r.full === 'top.dec.r_state' && r.enum)")
    got = page.evaluate("""(v => ({ tr: Object.fromEntries(v.M.rows.filter(r => r.type === 'sig' && r.full.startsWith('top.dec.r_')).map(r =>
        [r.full.split('.').pop(), (r.tr || []).map(o => o.v).join('|')])), fsms: v.fsms().map(f => f.full || f.path).sort(),
        log: v.logList().map(e => e.level + ' ' + e.text), why: v.typesOf(v.M.rows.find(r => r.full === 'top.dec.act_edge_sel')).why }))
        (document.querySelector('.wv').waveView)""")
    check(got['tr']['r_state'] == 'IDLE|SYNC|DATA|ERR|IDLE' and got['tr']['r_odd'] == 'IDLE|SYNC|0x00000006|ERR' and
          got['tr']['r_wide'].startswith('0x00000000|0x00000001'),
          f'an enum on an integer of 32 bits: its labels by the codes, a value no code of it a number; a reg of 32 bits a number {got["tr"]}')
    check(got['fsms'] == ['top.dec.act_edge_sel', 'top.dec.next_state', 'top.dec.r_lost', 'top.dec.r_odd', 'top.dec.r_state'],
          f'the integers labelled are FSMs {got["fsms"]}')
    log = got['log']
    check(any('5 enums of the types on integers of the dump' in x for x in log) and
          any(x.startswith('warning 1 signal left as it is') for x in log) and
          any('r_odd: an integer of 32 bits labelled by its enum of 3: 1 value no code of it (6)' in x for x in log) and
          any('r_lost: only x in the dump' in x and 'wlf2vcd' in x for x in log) and not any('Floating point' in x for x in log),
          f'the log: the integers labelled, the reg left, a value no code, only x (wlf2vcd?), no note of a real {log}')
    check('on an integer of 32 bits in the dump' in got['why'] and '1 bits' in got['why'], f'Type…: an enum on an integer {got["why"]!r}')
    check(not errs, 'no page errors (int_enums)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
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
            WaveLens.internal.peek(v).vis.some(r => (r.cls || '').startsWith('sva-expr')), [...v.notesEl.querySelectorAll('input.txt')].some(i => i.value === 'saved here')]; })()""")
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
    pinned = page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('wavelens.look:'))")
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
    {'op': 'bookmark', 'n': 3, 'signal': 'PREADY', 'label': 'ready', 'lift': 'below'}, {'op': 'arrow', 'id': 1, 'label': '{dt} · {cycles:PCLK}'},
    {'op': 'span', 'from': '50ns', 'to': '70ns', 'label': 'setup', 'color': 'c7'}, {'op': 'span', 'from': '110ns', 'to': '90ns', 'signals': ['PREADY', 'PENABLE']},
    {'op': 'span', 'id': 2, 'label': 'wait'}, {'op': 'span', 'from': 1, 'to': 2}, {'op': 'span', 'id': 3, 'delete': True},
    {'op': 'marker', 't': '100ns', 'label': 'M', 'color': '#c00'}, {'op': 'marker', 't': '140ns'}, {'op': 'marker', 'id': 2, 'label': 'second'},
    {'op': 'group', 'name': 'ctl', 'signals': ['PSEL', 'PENABLE'], 'color': '#08f'}, {'op': 'group', 'name': 'ctl', 'add': 'PWRITE'},
    {'op': 'group', 'name': 'data', 'signals': 'P*DATA'}, {'op': 'group', 'name': 'data', 'rename': 'payload'},
    {'op': 'highlight', 'add': ['PSEL', 'payload']}, {'op': 'highlight', 'add': 'PREADY', 'remove': 'PSEL'},
    {'op': 'paint', 'signals': 'PADDR', 'color': '#123456'}, {'op': 'paint', 'signals': ['PWDATA', 'PRDATA'], 'color': '#654321'},
    {'op': 'paint', 'signals': 'PRDATA', 'color': None}, {'op': 'hide', 'signals': 'PSLVERR'}, {'op': 'radix', 'signals': 'PADDR', 'radix': 'dec'},
    {'op': 'analog', 'signals': 'PWDATA', 'rows': 2},
    {'op': 'bookmark', 'n': 1, 'top': 'apb_tb.PCLK', 'go': True}, {'op': 'select', 'signal': 'PENABLE'}, {'op': 'cursor', 't': '150ns'}, {'op': 'cursor2', 't': '170ns'},
    {'op': 'view', 'from': '40ns', 'to': '180ns'}, {'op': 'bookmark', 'n': 5, 't': 0, 'go': True}, {'op': 'bookmark', 'n': 6, 't': '205ns', 'top': 'PADDR', 'go': True},
    {'op': 'cursor', 't': '150ns'}, {'op': 'view', 'from': '40ns', 'to': '180ns'}, {'op': 'range', 'from': '100ns', 'to': '60ns', 'signal': 'PCLK'},
    {'op': 'sort', 'dir': 'desc', 'ignore': 'P'}, {'op': 'style', 'name': 'questa'}, {'op': 'fold', 'groups': 'ctl'},
    {'op': 'find', 'query': 'pw', 'case': True, 'open': False}, {'op': 'gaps', 'on': True, 'idle': 8},
    {'op': 'layout', 'scroll': 'page', 'tools': 'fold'}, {'op': 'group', 'name': 'ctl', 'go': True},
    {'op': 'cycles', 'on': True, 'clock': 'PCLK', 'zero': '50ns'}, {'op': 'group', 'name': 'payload', 'move': 1},
    {'op': 'bits', 'signals': ['PADDR', 'PWDATA']}, {'op': 'bits', 'signals': 'PWDATA', 'on': False},
    {'op': 'bookmark', 't': '60ns', 'signal': 'PADDR[2]', 'text': 'a bit'},
]


def bits(browser, build):
    """A bus's width after its name ([7:0], a field's [msb:lsb]) and the bus bit by bit: a click on the width, b, the
    menu's Bits, the command; its bits' values, kept over a reload and in the state, a bookmark on a bit, the pictures."""
    apb = build / 'examples' / 'apb' / 'apb.html'
    if not need(apb, how='make examples'):
        return
    print('viewer: bus widths, bits')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.goto(apb.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    js = lambda e: page.evaluate(f"(async () => {{ const v = document.querySelector('.wv').waveView; {e} }})()")
    row = lambda n: page.locator('.wv').first.locator(f'.names .row:has(.n[title="{n}"])').first
    tags = js("""const t = n => (e => e ? e.textContent : null)(v.rowEl(v.M.rows.find(r => r.full === n)).querySelector('.wd'));
        const I = WaveLens.internal, M = WaveLens.parse({ signal: [{ name: 's', wave: '=', data: ['0x1f'], width: 8, fields: [{ name: 'hi', msb: 7, lsb: 4 },
          { name: 'b', msb: 0 }] }, { name: 'r', tv: [[0, '1.5']], kind: 'real' }] });
        return [t('PADDR'), t('PWDATA'), t('PCLK'), M.rows.map(r => I.widthTag(r))];""")
    check(tags == ['[7:0]', '[31:0]', None, ['[7:0]', '[7:4]', '', '']],
          f'the width after a bus\'s name, none on a bit; a struct\'s whole value, its field\'s place [msb:lsb], none on a real {tags}')
    row('PADDR').locator('.wd').click()
    got = js("""const vis = WaveLens.internal.peek(v).vis, i = vis.findIndex(r => r.full === 'PADDR'), b = vis.slice(i + 1).filter(r => r.type === 'sig').slice(0, 8);
        return [b.map(r => r.name).join(' '), b.map(r => v.valueAt(r, 60000)).join(''), v.state().bits, v.rowEl(vis[i]).querySelector('.wd').classList.contains('open'),
          b.every(r => r.depth === vis[i].depth + 1)];""")
    check(got == ['[7] [6] [5] [4] [3] [2] [1] [0]', '00000100', ['PADDR'], True, True],
          f'a click on [7:0]: the bus bit by bit under it, the highest first, each its bit of the value (0x04 at 60 ns), in the state {got}')
    page.reload(); page.wait_for_load_state('networkidle')
    kept = js("return [v.state().bits, WaveLens.internal.peek(v).vis.filter(r => r.bit != null).length]")
    js("(v.select(v.sigByPath('PADDR[2]')), v.canvas.focus(), 0)"); page.keyboard.press('b')
    key = js("return [v.state().bits, v.sel && v.sel.full]")
    js("(v.select('PWDATA'), v.canvas.focus(), 0)"); page.keyboard.press('b'); key2 = js("return v.state().bits"); page.keyboard.press('b')
    check(kept == [['PADDR'], 8] and key == [[], 'PADDR'] and key2 == ['PWDATA'],
          f'kept over a reload; b on a bit folds its bus (the bus selected), on a bus shows its bits {kept} {key} {key2}')
    c = page.locator('.wv canvas').first; c.scroll_into_view_if_needed(); box = c.bounding_box()
    y = js("const o = WaveLens.internal.peek(v).lay.find(o => o.row.full === 'PRDATA'); return o.y + o.h / 2 - (WaveLens.internal.peek(v).oy || 0)")
    page.mouse.click(box['x'] + 300, box['y'] + y, button='right'); menu = page.locator('.wv-menu')
    lab = menu.locator('button[data-m=bits]').inner_text().split('\n')[0]; menu.locator('button[data-m=bits]').click()
    m = js("return v.state().bits")
    r = js("""const r = await v.run([{ op: 'bits', signals: 'PRDATA', on: false }, { op: 'bits', signals: 'PCLK' }, { op: 'bits', signals: 'PADDR', on: 1 },
          { op: 'bookmark', t: 60000, signal: 'PADDR[2]', text: 'bit 2' }, { op: 'bookmark', t: 60000, signal: 'PADDR[8]' }]);
        const n = r[3].n; v.goMark(n); return [r.map(x => x.error || x.signals || x.n), v.state().bits, v.sel && v.sel.full, v.bookmarks().find(b => b.n === n).signal];""")
    check(lab.startswith('Bits: 32 rows') and m == ['PRDATA'] and r[0][:3] == [1, 'not a bus: PCLK', 'on: true or false'] and 'no signal "PADDR[8]"' in r[0][4] and
          r[1:] == [['PADDR'], 'PADDR[2]', 'PADDR[2]'], f'the menu\'s Bits; the command (not a bus, on); a bookmark on a bit: going to it shows the bits {lab} {m} {r}')
    pic = js("""const a = v.toSVG(); WaveLens.configure({ showWidth: false }); const b = v.toSVG(), n = WaveLens.internal.peek(v).namesEl.querySelectorAll('.wd').length;
        WaveLens.configure({ showWidth: true }); return [a.includes('>[7:0]</text>'), a.includes('>[2]</text>'), b.includes('[7:0]'), n,
          WaveSVG.toString(v.M.src).includes('>[31:0]</text>')];""")
    check(pic == [True, True, False, 0, True], f'the picture has the widths and the bits shown; showWidth: false, none in the names or the picture; WaveSVG too {pic}')
    vis = "WaveLens.internal.peek(v).vis.filter(r => r.bit != null)"
    hid = js(f"""await v.run([{{ op: 'bits', signals: 'PADDR' }}, {{ op: 'hide', signals: 'PADDR' }}]); const a = {vis}.length;
        await v.run([{{ op: 'show' }}, {{ op: 'hide', signals: 'PADDR[3]' }}]); const b = {vis}.map(r => r.name).join(' ');
        await v.run([{{ op: 'show' }}, {{ op: 'find', query: 'PADDR', mask: true }}]); const c = {vis}.length;
        await v.run([{{ op: 'find', query: '', mask: false }}]); return [a, b, c];""")
    check(hid == [0, '[7] [6] [5] [4] [2] [1] [0]', 8], f'the bits go with their bus: hidden with it, one hidden by its path, kept under it by the find\'s Mask {hid}')
    lazy = page.evaluate("""(() => { const s = { type: 'sig', full: 'd', width: 4, depth: 0, anc: [], tr: [{ t: 0, k: '=', raw: '5' }, { t: 5, k: 'x' }] };
        const b = WaveLens.internal.bitRows(s), a = b.map(r => r.tr.map(o => o.k).join('')).join(' ');
        s.tr = [{ t: 0, k: '=', raw: 'a', bits: '1z10' }]; return [a, b.map(r => r.tr.map(o => o.k).join('')).join(' '), b.map(r => r.full).join(' ')]; })()""")
    check(lazy == ['0x 1x 0x 1x', '1 z 1 0', 'd[3] d[2] d[1] d[0]'], f'bit rows: x and z bit by bit, read again when the bus\'s changes are new (a lazy dump) {lazy}')
    check(not errs, 'no page errors (bits)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


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
    got = js("""const h0 = v.hdrH, r = await v.run([{ op: 'cycles', on: true }]), ups = WaveLens.views()[0] && v.cycData().ups;
        v.setCursor(ups[2] + 1); const t = v.curEl.textContent, lab = WaveLens.internal.peek(v).namesEl.querySelector('.hdr .cyc')?.textContent;
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
    svg = js("return [v.toSVG(), WaveLens.WaveSVG.toString(v.M.src, { cycles: true }), WaveLens.WaveSVG.toString(v.M.src, {})];")
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
    got = js("""WaveLens.configure({ cycleClock: 'PSEL', cycleZero: 20000 }); await v.run([{ op: 'cycles', clock: null, zero: null }]); const st = v.state();
        v.setCycles(null); const page = [v.cycOpt().cycleClock, v.cycOpt().cycleZero]; await v.setState(st); const back = [v.cycOpt().cycleClock, v.cycOpt().cycleZero];
        v.setCycles(null); WaveLens.configure({ cycleClock: null, cycleZero: null }); return [page, back];""")
    check(got == [['PSEL', 20000], [None, None]], f'a saved null (the clock found, the first edge) comes back null over the page\'s settings {got}')
    # two clocks of other periods: the band's one counts the Δ and c3, a name that is also a path's tail takes the exact path
    got = page.evaluate("""(() => { const ck = (p, n) => { const tv = []; for (let i = 0; i < n; i++) tv.push([i * p, '0'], [i * p + p / 2, '1']); return tv; };
        const el = document.body.appendChild(document.createElement('div')), w = new WaveLens.WaveView(el, { signal: [['tb', { name: 'clk', path: 'tb.clk',
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
    js("v.root.scrollIntoView(); v.draw(); return 0;"); page.wait_for_timeout(50)   # the bookmark in sight, whatever the clicks scrolled
    box = w.locator('canvas').bounding_box(); p = js("const p = v.bmGeo.pos.get(2); return [p[0], p[1] - (WaveLens.internal.peek(v).oy || 0)];"); b0 = js("return [v.bms[1].t, v.bms[1].signal];"); n = js("return v.undoS.length;")
    page.mouse.move(box['x'] + p[0], box['y'] + p[1]); page.mouse.down(); page.mouse.move(box['x'] + p[0] + 120, box['y'] + p[1] + 40, steps=8); page.mouse.up()
    page.wait_for_timeout(100); b1 = js("return [v.bms[1].t, v.bms[1].signal];"); d = js("return v.undoS.length;") - n
    page.keyboard.press('Control+z'); page.wait_for_timeout(100)
    check(b1 != b0 and d == 1 and js("return [v.bms[1].t, v.bms[1].signal];") == b0, f'a bookmark dragged: one step, undone to where it was {b0} {b1} {d}')
    # a folded group of yours and the selection in it stay through an undo of something else; a highlight keeps its colours
    got = js("""await v.run([{ op: 'group', name: 'gv', signals: 'PREADY' }, { op: 'group', name: 'gu', signals: 'PSEL,PENABLE' }]);
        const f = v.ugRows().find(r => r.name === 'gv'), g = v.ugRows().find(r => r.name === 'gu'); WaveLens.internal.peek(v).collapsed.add(f.id);
        v.select(v.ugRows().find(r => r.ug === g)); v.draw();
        await v.run([{ op: 'highlight', add: ['PSEL', 'PWRITE'] }]); await v.run([{ op: 'highlight', remove: 'PSEL' }]); const c0 = [...v.picks.values()];
        await v.run([{ op: 'paint', signals: 'PADDR', color: '#00ff00' }]); await v.undo(); return [v.ugRows().includes(g), WaveLens.internal.peek(v).collapsed.has(f.id),
        !!v.sel && v.sel.ug === g, JSON.stringify([...v.picks.values()]) === JSON.stringify(c0), v.state().paint.PADDR || null];""")
    check(got == [True, True, True, True, None], f'undo of a paint: your group (its row, folded), the selection in it, the highlight\'s colours stay {got}')
    # the Russian layout (ctrl+Я is ctrl+Z by its place), ctrl+Y, a viewer by the focus, two undos at once, the gaps' clock null
    got = js("""await v.run([{ op: 'hide', signals: 'PRESETn' }]); v.canvas.focus();
        v.canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'я', code: 'KeyZ', ctrlKey: true, bubbles: true, cancelable: true }));
        await new Promise(r => setTimeout(r, 50)); const a = v.state().hidden.length;
        v.canvas.dispatchEvent(new KeyboardEvent('keydown', { key: 'y', code: 'KeyY', ctrlKey: true, bubbles: true, cancelable: true }));
        await new Promise(r => setTimeout(r, 50)); const b = v.state().hidden.length;
        await v.run([{ op: 'hide', signals: 'PREADY' }]); const r = await Promise.all([v.undo(), v.undo()]); const c = v.state().hidden.length;
        WaveLens.configure({ gapClock: 'PCLK' }); v.setGaps({ gapClock: null }); await v.run([{ op: 'paint', signals: 'PADDR', color: '#0000ff' }]); await v.undo();
        const d = v.gapOpt().gapClock; v.setGaps(null); WaveLens.configure({ gapClock: null }); return [a, b, r.filter(Boolean).length, c, d];""")
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
        await v.run([{ op: 'group', name: 'gr', signals: 'PCLK' }]); const g = v.ugRows().find(r => r.name === 'gr'); WaveLens.internal.peek(v).collapsed.add(g.id);
        await v.run([{ op: 'group', name: 'gr', rename: 'gs' }]); await v.undo(); const g2 = v.ugRows().find(r => r.name === 'gr');
        return [a, h, busy, g2 === g, WaveLens.internal.peek(v).collapsed.has(g.id), v.state().paint.PSEL];""")
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
    idx = lambda g, n: js(f"return WaveLens.internal.peek(v).vis.findIndex(r => r.ug && r.ug.name === '{g}' && r.orig.name === '{n}');")
    hdr = lambda g: js(f"return WaveLens.internal.peek(v).vis.findIndex(r => r.user && r.name === '{g}');")
    box = lambda i: w.locator(f'.names .row[data-r="{i}"]').bounding_box()
    n0 = js("return v.undoS.length;")
    p, q = box(idx('gA', 'PSEL')), box(idx('gB', 'PADDR'))
    page.mouse.move(p['x'] + 30, p['y'] + p['height'] / 2); page.mouse.down(); page.mouse.move(q['x'] + 30, q['y'] + q['height'] * 0.8, steps=8)
    line = js("return !!WaveLens.internal.peek(v).namesEl.querySelector('.row.drop-a');"); page.mouse.up(); page.wait_for_timeout(100)
    e, n1 = groups(), js("return v.undoS.length;") - n0
    check(line and e == [['gA', 'PWRITE', 'PENABLE'], ['gB', 'PADDR', 'PSEL']] and n1 == 1, f'a drag: a line where it goes; the signal into the other group after '
          f'the row dropped on; one step {line} {e} {n1}')
    # a group's header dragged above the other's; a drag over the dump's names selects their text (no move)
    p, q = box(hdr('gB')), box(hdr('gA'))
    page.mouse.move(p['x'] + 30, p['y'] + p['height'] / 2); page.mouse.down(); page.mouse.move(q['x'] + 30, q['y'] + 3, steps=8); page.mouse.up(); page.wait_for_timeout(100)
    f = [g[0] for g in groups()]
    r1, r2 = box(js("return WaveLens.internal.peek(v).vis.findIndex(r => !r.ug && r.name === 'PSEL');")), box(js("return WaveLens.internal.peek(v).vis.findIndex(r => !r.ug && r.name === 'PRDATA');"))
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
    left = js("return WaveLens.internal.peek(v).namesEl.classList.contains('wv-drag');"); g2 = groups()
    w.locator(f'.names .row[data-r="{idx("gA", "PENABLE")}"] .n').click(); page.wait_for_timeout(50)
    check(not left and g2 == g0 and js("return v.sel && v.sel.ug && v.sel.orig.name;") == 'PENABLE', f'let go over the waves: no move, the drag over, a click selects {left} {g2}')
    # from the names: the focused row moves and keeps the focus (twice); a header with the focus moves its group
    w.locator(f'.names .row[data-r="{idx("gB", "PADDR")}"]').focus(); page.keyboard.press('Alt+ArrowDown'); page.wait_for_timeout(80)
    page.keyboard.press('Alt+ArrowUp'); page.wait_for_timeout(80); page.keyboard.press('Alt+ArrowDown'); page.wait_for_timeout(80)
    foc = js("const a = document.activeElement, r = a && a.dataset.r != null && WaveLens.internal.peek(v).vis[+a.dataset.r]; return r && r.ug && [r.ug.name, r.orig.name];")
    gb = [g for g in groups() if g[0] == 'gB'][0]; second = groups()[1][0]
    w.locator(f'.names .row[data-r="{hdr(second)}"]').focus(); page.keyboard.press('Alt+ArrowUp'); page.wait_for_timeout(80)
    check(foc == ['gB', 'PADDR'] and gb == ['gB', 'PSEL', 'PADDR'] and groups()[0][0] == second, f'alt+arrows in the names: the focus stays on the row moved; '
          f'a header with the focus moves its group {foc} {gb} {groups()}')
    # the focus on a module of the dump (not one of yours): nothing moves, though a signal of a group of yours is selected
    js("v.select(v.ugRows().find(r => r.ug)); return 0;"); g3 = groups()
    mod = js("return WaveLens.internal.peek(v).vis.findIndex(r => r.type === 'group' && !r.user);")
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
    # the right button on a name: the viewer's menu for that row; your group's row: Move up / down, to the top / bottom; its
    # header: the group among yours; a signal of the dump: how to move it; text selected in the names: the browser's menu
    js("await v.run([{ op: 'group', name: 'gA', signals: 'PSEL,PENABLE,PWRITE' }, { op: 'group', name: 'gB', signals: 'PADDR' }]); return 0;")
    def names_menu(i):
        page.keyboard.press('Escape'); r = box(i)
        page.mouse.click(r['x'] + 30, r['y'] + r['height'] / 2, button='right'); page.wait_for_timeout(80)
        return page.evaluate("[...document.querySelectorAll('.wv-menu > button[data-m]')].map(b => b.dataset.m)")
    def pick(i, m):
        names_menu(i); page.locator(f'.wv-menu > button[data-m={m}]').click(); page.wait_for_timeout(100)
    ms = names_menu(idx('gA', 'PENABLE'))
    pick(idx('gA', 'PENABLE'), 'mvdn'); a = groups()[0]; pick(idx('gA', 'PENABLE'), 'mvtop'); b = groups()[0]
    pick(idx('gA', 'PSEL'), 'mvbot'); c = groups()[0]; pick(idx('gA', 'PWRITE'), 'mvup'); d = groups()[0]
    check({'mvup', 'mvdn', 'mvtop', 'mvbot', 'copyname', 'hide'} <= set(ms) and a == ['gA', 'PSEL', 'PWRITE', 'PENABLE'] and
          b == ['gA', 'PENABLE', 'PSEL', 'PWRITE'] and c == ['gA', 'PENABLE', 'PWRITE', 'PSEL'] and d == ['gA', 'PWRITE', 'PENABLE', 'PSEL'],
          f'the right button on a name of your group: its menu moves it (down, to the top, to the bottom, up) {ms} {a} {b} {c} {d}')
    top = names_menu(idx('gA', 'PWRITE')); hm = names_menu(hdr('gA'))
    pick(hdr('gA'), 'mvdn'); e = [g[0] for g in groups()]
    pick(hdr('gA'), 'ugfold'); folded = idx('gA', 'PWRITE') < 0; pick(hdr('gA'), 'ugfold')
    dm = names_menu(js("return WaveLens.internal.peek(v).vis.findIndex(r => !r.ug && r.name === 'PRDATA');"))
    hint = page.evaluate("[...document.querySelectorAll('.wv-menu .sub .mh')].some(h => /to move it/.test(h.textContent))")
    page.keyboard.press('Escape')
    check('mvup' not in top and 'mvtop' not in top and {'mvdn', 'ugfold'} <= set(hm) and 'fold' not in hm and e[:2] == ['gB', 'gA'] and folded and
          not {'mvup', 'mvdn'} & set(dm) and 'copyname' in dm and hint,
          f'the first row: no Move up; a header: the group moves among yours, folds; a signal of the dump: its menu and how to move it {top} {hm} {e} {dm}')
    r1 = box(js("return WaveLens.internal.peek(v).vis.findIndex(r => !r.ug && r.name === 'PSEL');"))
    page.mouse.dblclick(r1['x'] + 20, r1['y'] + r1['height'] / 2); page.mouse.click(r1['x'] + 20, r1['y'] + r1['height'] / 2, button='right')
    page.wait_for_timeout(80); native = page.evaluate("!document.querySelector('.wv-menu') && !!String(getSelection())"); page.keyboard.press('Escape')
    check(native, 'text selected in the names: the right button leaves it to the browser (copy)')
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
    live = '  <script id="wavelens-live" data-x="1" type="application/json">{"port": 8742, "token": "SECRET-TOKEN"}</script>\n'   # not as viewedit writes it
    pa, pb = d / 'a.html', d / 'b.view.html'
    pa.write_text(src.replace('<script>window.WAVELENS_CONFIG', live + '<script>window.WAVELENS_CONFIG', 1), encoding='utf-8')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    page.route('http://127.0.0.1:8742/**', lambda r: r.abort())   # the live link of the copy: no agent here
    page.goto(pa.as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()')
    V = "WaveLens.views().find(v => v.editKey() === 'exact')"
    keys = ['bookmarks', 'arrows', 'groups', 'paint', 'radix', 'hidden', 'cursor', 'from', 'to']
    pick = lambda st: {k: st.get(k) for k in keys} | {'highlight': st['config']['highlight'], 'cycles': st['config']['cycles']}
    want = page.evaluate(f"""(async () => {{ const v = {V}; await v.run([{{ op: 'bookmark', t: '75ns', signal: 'PSEL', text: 'mine <!--<script> </script>' }},
        {{ op: 'group', name: 'ctl', signals: 'PSEL,PENABLE' }}, {{ op: 'paint', signals: 'PADDR', color: '#ff8800' }}, {{ op: 'radix', signals: 'PWDATA', radix: 'dec' }},
        {{ op: 'hide', signals: 'PSLVERR' }}, {{ op: 'highlight', set: 'PREADY' }}, {{ op: 'cycles', on: true }}, {{ op: 'cursor', t: '95ns' }},
        {{ op: 'view', from: '30ns', to: '150ns' }}]); return v.state(); }})()""")
    text = page.evaluate('WaveLens.pageText()')
    again = page.evaluate('WaveLens.pageText()')   # twice: one block of edits, the next revision of nothing new
    blocks = lambda t: len(_re.findall(r'^<script type="application/json" id="wavelens-edits">', t, _re.M))
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
    check('SECRET-TOKEN' not in text and 'id="wavelens-live"' not in text.split('<script>\n')[0] and blocks(text) == 1 and blocks(again) == 1,
          'the live link (its block written another way, its token) is not in the saved page; one block of edits, saved twice too')
    # the person who opens it: a ƒ row and a bookmark text of theirs stay over a reload (the page's revision is applied once)
    page.evaluate(f"(v => {{ v.root.querySelector('input.svq').value = 'PSEL && PENABLE'; v.root.querySelector('button[data-x=add]').click(); }})({V})")
    page.evaluate(f"{V}.run([{{ op: 'bookmark', n: 1, text: 'theirs' }}])"); page.wait_for_timeout(300 * SCALE)
    page.reload(); page.wait_for_load_state('networkidle'); page.wait_for_timeout(300 * SCALE)
    kept = page.evaluate(f"""(v => [v.bms[0].text, v.svaExprs ? JSON.stringify(v.extraJSON.map(f => f()).filter(Boolean)).includes('PSEL && PENABLE') : null])({V})""")
    check(kept == ['theirs', True], f'the person\'s own edits (a bookmark, a ƒ row) stay over a reload: the page\'s are applied once {kept}')
    # a page that is not all in itself (docs/index.html: wavelens.js beside it): no button, Save page says why
    page.goto((ROOT / 'docs' / 'index.html').as_uri()); page.wait_for_load_state('networkidle')
    why = page.evaluate("(() => { try { WaveLens.pageText(); return 'saved'; } catch (e) { return e.message; } })()")
    hid = page.locator('.wv button[data-act=spage]').first.is_hidden()
    check(hid and 'all in itself' in why, f'docs/index.html (wavelens.js beside it): no Save page, it says why {why!r}')
    page.goto((ROOT / 'tests' / 'conformance.html').as_uri()); page.wait_for_load_state('networkidle')   # its viewers built before the page was read
    vis = page.locator('.wv button[data-act=spage]').evaluate_all('bs => bs.filter(b => !b.hidden).length')
    check(vis == 0, f'tests/conformance.html (its viewers built early, wavelens.js beside it): no Save page on any viewer ({vis} shown)')
    page.evaluate("WaveLens.configure({ savePage: false })")
    check(page.locator('.wv button[data-act=spage]').first.is_hidden(), 'savePage: false hides the button')
    page.evaluate("WaveLens.configure({ savePage: true })")
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
    V = "WaveLens.views().find(v => v.editKey() === 'exact')"
    w = page.locator('.wv').nth(page.evaluate(f"WaveLens.views().indexOf({V})"))
    w.locator('input.cfile').set_input_files(str(bv)); page.wait_for_timeout(300 * SCALE)
    got = page.evaluate(f"""(v => {{ const c = v.cmp, R = n => v.M.rows.find(r => r.name === n);
        const el = n => WaveLens.internal.peek(v).rowEls[WaveLens.internal.peek(v).vis.indexOf(R(n))]; return c && [c.differ, c.missing, c.first, el('PREADY').classList.contains('cmpd'),
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
    ref = page.evaluate("WaveLens.views()[0].compare('$timescale 1ns $end $scope module t $end $var wire 1 ! a $end $upscope $end $enddefinitions $end #0 0!', 'x.vcd')")
    toast = page.evaluate("WaveLens.views()[0].root.querySelector('.toast').textContent")
    w.locator('button[data-act=dcmpx]').click()
    gone = page.evaluate(f"(v => [v.cmp, WaveLens.internal.peek(v).namesEl.querySelectorAll('.cmpd, .cmpm').length, v.root.querySelector('button[data-act=dcmpx]').hidden])({V})")
    check(ref is None and 'clock-sampled' in toast and gone == [None, 0, True], f'a clock-sampled view refuses; ✕ compares no more {toast!r} {gone}')
    # Codex's cases: a packed struct by its vector (its group marked), a string the same as itself, the time both dumps
    # cover, a signal B's reader left out (dumpBudget) apart from one B lacks, a newer compare or none meanwhile, a group
    # of yours made after the compare marked
    got = page.evaluate("""(async () => {
      const mk = doc => { const el = document.body.appendChild(document.createElement('div')); return new WaveLens.WaveView(el, doc, {}); };
      const vcd = (vars, body) => `$timescale 1ps $end $scope module tb $end ${vars} $upscope $end $enddefinitions $end ${body}`;
      const w = mk({ signal: [['tb', { name: 'st', path: 'tb.st', width: 8, tv: [[0, '00'], [10, '12']], fields: [{ name: 'hi', msb: 7, lsb: 4 },
          { name: 'lo', msb: 3, lsb: 0 }] }, { name: 's', path: 'tb.s', kind: 'string', tv: [[0, 'Hello']] },
          { name: 'a', path: 'tb.a', tv: [[0, '0'], [30, '1']] }, { name: 'q', path: 'tb.q', tv: [[0, '0']] }]], time: { t0: 0, t1: 40, unit: 'ps' } });
      const B = vcd('$var wire 8 ! st [7:0] $end $var string 1 \" s $end $var wire 1 # a $end $var wire 1 $ q $end',
        '#0 b0 ! sHello \" 0# 0$ #10 b00010011 ! #20 1# #40');
      const r = await w.compare(B, 'b.vcd'), g = Object.values(w.M.groups).find(x => x.name === 'st');
      const marked = WaveLens.internal.peek(w).rowEls[WaveLens.internal.peek(w).vis.indexOf(g)].classList.contains('cmpd');
      const sp = w.cmp.rows.get(w.M.rows.find(x => x.name === 'a')).spans;
      WaveLens.configure({ dumpBudget: 3 }); const r2 = await w.compare(B, 'b.vcd'); WaveLens.configure({ dumpBudget: 3000000 });
      const slow = { name: 'slow.vcd', text: () => new Promise(res => setTimeout(() => res(B), 80)) }, pr = w.compare(slow); await w.compare(null);
      const r3 = await pr, gone = w.cmp;
      await w.compare(B, 'b.vcd'); await w.run([{ op: 'group', name: 'mine', signals: 'tb.a' }]);
      const k = WaveLens.internal.peek(w).vis.find(x => x.ug && x.orig.name === 'a');
      const kmark = WaveLens.internal.peek(w).rowEls[WaveLens.internal.peek(w).vis.indexOf(k)].classList.contains('cmpd');
      // a path B's reader left out is not matched to another signal of the same name; no time in common: nothing compared
      const u = mk({ signal: [['tb', ['u', { name: 'a', path: 'tb.u.a', tv: [[0, '0']] }]]], time: { t0: 0, t1: 40, unit: 'ps' } });
      WaveLens.configure({ dumpBudget: 1 });
      const r4 = await u.compare('$timescale 1ps $end $scope module tb $end $var wire 1 ! a $end $scope module u $end $var wire 1 " a $end $upscope $end ' +
        '$upscope $end $enddefinitions $end #0 0! 1" #40', 'b2.vcd');
      WaveLens.configure({ dumpBudget: 3000000 });
      const r5 = await u.compare('$timescale 1ps $end $scope module tb $end $scope module u $end $var wire 1 ! a $end $upscope $end $upscope $end ' +
        '$enddefinitions $end #100 0! #140', 'late.vcd'), t5 = u.root.querySelector('.toast').textContent;
      u.destroy(); w.destroy();
      return [r.differ, r.compared, marked, sp, r.to, [r2.missing, r2.omitted > 0], r3, gone, kmark, [r4.omitted, r4.differ], r5, /no time in common/.test(t5)]; })()""")
    check(got == [2, 4, True, [[20, 30]], 40, [0, False], None, None, True, [0, 1], None, True], f'a struct by its vector (its group ≠), a string the '
          f'same as itself, [from, to) both cover, B read for these rows only (no dumpBudget: none left out; tb.u.a by its path), a compare '
          f'superseded is dropped, a new group of yours marked, no time in common said {got}')
    # stage 14.3: a result already made (sva diff's, the WaveJSON "compare"): the page opens with its bands, the static SVG
    # draws them, the state keeps it, the command compare gives one and takes it off; B large: read once, the page's
    # signals only, its progress said, ≠ … ✕ stops it
    big = b / 'big.vcd'
    if not big.exists():
        n, out = 2000, ['$timescale 1ps $end', '$scope module tb $end']
        code = lambda i: ''.join(chr(33 + d) for d in ([i % 94] if i < 94 else [i // 94 % 94, i % 94]))
        out += [f'$var wire 8 {code(i)} s{i} [7:0] $end' for i in range(n)] + ['$upscope $end', '$enddefinitions $end']
        for t in range(0, 5000):
            out.append(f'#{t * 10}')
            out += [f'b{(t + i) & 255:b} {code(i)}' for i in range(t % 7, n, 7)]
        big.write_text('\n'.join(out) + '\n')
    page.evaluate("(() => { const i = document.createElement('input'); i.type = 'file'; i.id = 'bigin'; document.body.append(i); })()")
    page.set_input_files('#bigin', str(big))
    got = page.evaluate("""(async () => {
      const mk = doc => { const el = document.body.appendChild(document.createElement('div')); return new WaveLens.WaveView(el, doc, {}); };
      const doc = { signal: [['tb', { name: 'a', path: 'tb.a', tv: [[0, '0'], [30, '1']] }, { name: 'b', path: 'tb.b', tv: [[0, '0']] },
          { name: 'c', path: 'tb.c', tv: [[0, '1']] }]], time: { t0: 0, t1: 40, unit: 'ps' },
        compare: { name: 'b.vcd', from: 0, to: 40, signals: { 'tb.a': { spans: [[20, 30]], b: 'top.a' }, 'tb.b': { spans: [], b: 'top.b' } }, missing: ['tb.c'] } };
      const w = mk(doc), R = n => w.M.rows.find(r => r.name === n), el = n => WaveLens.internal.peek(w).rowEls[WaveLens.internal.peek(w).vis.indexOf(R(n))];
      const open = [w.cmp && w.cmp.differ, w.cmp && w.cmp.compared, el('a').classList.contains('cmpd'), el('c').classList.contains('cmpm'),
        w.root.querySelector('button[data-act=dcmpx]').textContent];
      const svgWith = WaveSVG.toString(doc), svgNo = WaveSVG.toString(Object.assign({}, doc, { compare: undefined }));
      const st = w.state().compare, rows = Object.fromEntries((await w.run([{ op: 'rows' }]))[0].rows.map(r => [r[0], r[2] || '']));
      const off = (await w.run([{ op: 'compare', off: true }]))[0], none = [w.cmp, w.state().compare];
      const on = (await w.run([{ op: 'compare', result: doc.compare }]))[0], dump = (await w.run([{ op: 'compare', dump: 'b.vcd' }]))[0].error || '';
      await w.setState({ wavelens: 'state', version: 3, compare: null }); const cleared = w.cmp;
      w.destroy();
      // B large: 2000 buses, this page shows 7 of them
      const sigs = [0, 1, 2, 3, 4, 5, 6].map(i => ({ name: 's' + i, path: 'tb.s' + i, width: 8, tv: [[0, '00']] }));
      const v = mk({ signal: [['tb', ...sigs]], time: { t0: 0, t1: 49990, unit: 'ps' } }), toasts = [];
      const obs = new MutationObserver(() => { const t = v.root.querySelector('.toast'); if (t) toasts.push(t.textContent); });
      obs.observe(v.root, { subtree: true, childList: true, characterData: true });
      const f = document.getElementById('bigin').files[0], t0 = performance.now(), r = await v.compare(f), ms = performance.now() - t0;
      obs.disconnect();
      const rd = v.compare(f); await new Promise(res => setTimeout(res, 5)); const reading = v.root.querySelector('button[data-act=dcmpx]').textContent;
      v.compareStop(); const stopped = await rd, kept = v.cmp && v.cmp.name;
      v.destroy();
      return { open, bands: (svgWith.match(/<rect/g) || []).length - (svgNo.match(/<rect/g) || []).length, st: !!(st && st.signals['tb.a']), rows,
        off: [off.off, ...none], on: [on.differ, on.compared, on.missing], dump: /pick it with Compare/.test(dump), cleared, big: [r && r.compared, r && r.differ],
        ms, progress: toasts.some(x => /MB of big\\.vcd read/.test(x)), reading, stopped, kept };
    })()""")
    check(got['open'] == [1, 2, True, True, '≠ 1 ✕'] and got['bands'] == 2 and got['st'] and [got['rows'].get(k) for k in ('tb.a', 'tb.b', 'tb.c')] == ['≠', '', 'missing'],
          f'a page with "compare" opens with its bands (a ≠, a struck row, ≠ 1 ✕), the static SVG draws them, the state keeps it, rows marks them {got}')
    check(got['off'] == [True, None, None] and got['on'] == [1, 2, 1] and got['dump'] and got['cleared'] is None,
          f'the command compare: off, a result, dump refused in a page (no file read by itself); a state with compare null clears it {got}')
    check(got['big'] == [7, 7] and got['ms'] < 5000 * SCALE and got['progress'] and got['reading'] == '≠ … ✕' and got['stopped'] is None
          and got['kept'] == 'big.vcd', f'B of {big.stat().st_size >> 20} MB, 2000 signals: the page\'s 7 read once in {got["ms"]:.0f} ms '
          f'(< {5000 * SCALE:.0f}), its progress said; ≠ … ✕ stops a read, the compare before it kept {got}')
    check(not errs, 'no page errors (compare)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def view_review(browser, build):
    """The review of 0.15, the viewer: Clear keeps your markers, cycleZero a time, a run lays its rows out before a
    picture or an edge, undo after a button's release nobody heard, the rows of a hidden module, a state that clears what
    it has not, a match by name said, ±inf and nan apart, names every object inherits refused, ids and ranges checked;
    compare and analog at scale (the marks, the bands a pixel apart one, a busy bus one bar per pixel)."""
    print('viewer: the review of 0.15')
    d = build / 'smoke' / 'view_review'
    d.mkdir(parents=True, exist_ok=True)
    pg = d / 'review.html'
    pg.write_text(f'''<!doctype html><html><head><meta charset="utf-8"><title>review</title>
<link rel="stylesheet" href="{(ROOT / 'wavelens' / 'wavelens.css').as_uri()}"></head><body><div id="w"></div>
<script src="{(ROOT / 'wavelens' / 'wavelens.js').as_uri()}"></script></body></html>''', encoding='utf-8')
    ctx = browser.new_context(viewport={'width': 1400, 'height': 1000})
    page = ctx.new_page()
    errs = []
    page.on('pageerror', lambda e: errs.append(str(e)))
    # the helpers of every check: a viewer of its own (opts.key: its own storage), a small hierarchy, a VCD of B
    helpers = """() => {
      window.mk = (doc, o = {}) => { const el = document.body.appendChild(document.createElement('div')); return new WaveLens.WaveView(el, doc, o); };
      window.small = cfg => ({ signal: [['tb', { name: 'clk', path: 'tb.clk', tv: Array.from({ length: 40 }, (_, i) => [i * 5000, i % 2 ? '1' : '0']) },
        ['u', { name: 'a', path: 'tb.u.a', tv: [[0, '0'], [1000, '1']] }, { name: 'data', path: 'tb.u.data', width: 8, tv: [[0, '00'], [20000, '3a']] }]]],
        time: { t0: 0, t1: 200000, unit: 'ps' }, config: cfg || {} });
      window.sleep = ms => new Promise(r => setTimeout(r, ms));
      window.vcd = (vars, body) => `$timescale 1ps $end ${vars} $enddefinitions $end ${body}`; }"""
    page.goto(pg.as_uri()); page.wait_for_load_state('load'); page.evaluate('localStorage.clear()'); page.evaluate(helpers)
    js = lambda e: page.evaluate(f"(async () => {{ {e} }})()")
    # V1: Clear takes the bookmarks and arrows, not your markers (they share this browser's copy); the page's come back
    page.evaluate("""async () => { const v = mk(small(), { key: 'v1' }); await v.run([{ op: 'bookmark', t: 1000 }, { op: 'bookmark', t: 6000 },
        { op: 'arrow', from: 1, to: 2 }, { op: 'marker', t: 2000, label: 'M' }]); v.notesEl.querySelector('button[data-bm=clear]').click(); }""")
    page.reload(); page.wait_for_load_state('load'); page.evaluate(helpers)
    got = js("""const doc = { signal: [{ name: 'a', path: 'a', tv: [[0, '0'], [10, '1']] }], time: { t0: 0, t1: 100, unit: 'ps' } };
        const v = mk(doc, { key: 'v1' }); return [v.umarks.map(m => m.label), v.bms.length, v.arrows.length];""")
    check(got == [['M'], 0, 0], f'Clear: the bookmarks and arrows gone, your markers kept over a reload {got}')
    page.evaluate('localStorage.clear()')
    # V2: cycleZero "50ns" is 50 ns (as gapIdle and the cursor read a time), in the viewer and in a static SVG
    got = js("""const v = mk(small({ cycles: true, cycleZero: '50ns' }), { key: 'v2' }), d = v.cycData();
        const svg = z => WaveLens.WaveSVG.toString(small({ cycles: true, cycleZero: z }), {}).replace(/wvfclip\\d+/g, '');
        return [v.cycOpt().cycleZero, d.ups[d.iz], svg('50ns') === svg(50000), svg('50ns') !== svg(50)];""")
    check(got == [50000, 55000, True, True], f'cycleZero "50ns": 50 000 ps, cycle 0 the edge at 55 ns, the static SVG the same as 50000 {got}')
    # V3: a run lays its rows out before a command that reads them: a picture after a hide, an edge of the shown signals
    got = js("""const v = mk(small(), { key: 'v3' }), names = s => [...s.matchAll(/>(clk|a|data)<\\/text>/g)].map(m => m[1]);
        const r = await v.run([{ op: 'hide', signals: 'tb.u.a' }, { op: 'picture', format: 'svg' }]);
        await v.run({ op: 'show' }); v.select(null); v.setCursor(0);
        const e = await v.run([{ op: 'hide', signals: 'tb.u.a' }, { op: 'edge', dir: 1, kind: 'any' }]);
        return [names(r[1].svg), e[1].t];""")
    check(got[0] == ['clk', 'data'] and got[1] == 5000, f'in one run: the picture after a hide has no hidden row, an edge after it is of a shown signal {got}')
    # V4: a button down whose release nobody heard (the browser's menu, the window left): undo still records and undoes
    got = js("""const v = mk(small(), { key: 'v4' }); await sleep(30);
        const row = () => WaveLens.internal.peek(v).namesEl.querySelector('.row[data-r="1"]'), out = [];
        for (const end of [el => el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2 })),
          () => window.dispatchEvent(new Event('blur'))]) {
          row().dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 2 })); end(row()); v.closeMenu();
          await v.run({ op: 'bookmark', t: 5000 }); await sleep(30); out.push([(await v.undo(-1)).split(',')[0], v.bms.length]);
        }
        return out;""")
    check(got == [['bookmarks', 0], ['bookmarks', 0]], f'a press ended by the context menu, by the window losing the focus: the next edit is a step, undone {got}')
    # V5: rows lists the signals of a hidden module too, where they stand
    got = js("""const v = mk(small(), { key: 'v5' }), r = await v.run([{ op: 'hide', signals: 'tb.u' }, { op: 'rows' }]); return r[1].rows.map(x => x[0]);""")
    check(got == ['tb', 'tb.clk', 'tb.u', 'tb.u.a', 'tb.u.data'], f'rows: a hidden module\'s signals too, in their place {got}')
    # A10: a state says no second cursor, no range, the edge kind: loaded over a viewer that has them, it clears them
    got = js("""const v = mk(small(), { key: 'a10' }), st = v.state(); v.setCursor2(30000); v.setRange(10000, 20000); v.setEdgeKind('rise');
        await v.setState(st); return [st.cursor2, st.range, st.edge, v.cursor2, v.range, v.edgeKind];""")
    check(got == [None, None, {'kind': 'any', 'value': ''}, None, None, 'any'],
          f'state(): cursor2 null, range null, the edge kind; set_state clears what was set after it {got}')
    # A8, A5: a signal found by its short name only is said (toast, its tooltip, the bar); reals inf, -inf and nan apart
    got = js("""const v = mk({ signal: [['tb', ['a', { name: 'ready', path: 'tb.a.ready', tv: [[0, '0'], [10, '1']] }], { name: 'q', path: 'tb.q', tv: [[0, '0']] },
          { name: 'r1', path: 'tb.r1', kind: 'real', tv: [[0, 'inf']] }, { name: 'r2', path: 'tb.r2', kind: 'real', tv: [[0, 'nan']] },
          { name: 'r3', path: 'tb.r3', kind: 'real', tv: [[0, '-inf']] }]], time: { t0: 0, t1: 40, unit: 'ps' } }, { key: 'a8' });
        const B = vcd('$scope module tb $end $scope module b $end $var wire 1 ! ready $end $upscope $end $var wire 1 " q $end $var real 64 # r1 $end ' +
          '$var real 64 $ r2 $end $var real 64 % r3 $end $upscope $end', '#0 0! 0" r-Infinity # rNaN $ r-Infinity % #10 1! #40');
        const r = await v.compare(B, 'b.vcd'), toast = v.root.querySelector('.toast').textContent, row = v.M.rows.find(x => x.full === 'tb.a.ready');
        const reals = ['r1', 'r2', 'r3'].map(n => v.cmp.rows.get(v.M.rows.find(x => x.name === n)).spans.length);
        return [r.byName, toast.includes('matched by name: tb.a.ready → tb.b.ready'), (v.rowEl(row).title || '').includes('matched by name'),
          v.root.querySelector('button[data-act=dcmpx]').title.includes('matched by name'), (v.rowEl(v.M.rows.find(x => x.full === 'tb.q')).title || ''), reals];""")
    check(got == [1, True, True, True, '', [1, 0, 0]], f'tb.a.ready compared with tb.b.ready by its name: said in the toast, its tooltip and the bar, '
          f'an exact match not; a real inf / -inf differs, nan / nan and -inf / -inf do not {got}')
    # M6: names every object has ("constructor", "toString") are no shape, line, style, kind or command; in this browser's copy, the default
    got = js("""const v = mk(small(), { key: 'm6' }), key = v.bmKey;
        const r = await v.run([{ op: 'bookmark', t: 1000 }, { op: 'bookmark', t: 6000 }, { op: 'arrow', from: 1, to: 2, line: 'constructor' },
          { op: 'arrow', from: 1, to: 2, shape: 'toString' }, { op: 'style', name: 'constructor' }, { op: 'edge', kind: 'constructor' }, { op: 'constructor' }]);
        v.destroy(); localStorage.setItem(key, JSON.stringify({ bookmarks: [{ n: 1, t: 1000 }, null, { n: 2, t: 6000 }],
          arrows: [{ from: 1, to: 2, line: 'constructor', shape: 'toString', head: 'valueOf' }, null] }));
        let w = null, err = ''; try { w = mk(small(), { key: 'm6' }); w.draw(); } catch (e) { err = e.message; }
        const st = w && await w.setState({ wavelens: 'state', version: 3, arrows: [{ from: 1, to: 2, line: 'hasOwnProperty' }], bookmarks: [{ n: 1, t: 1 }, { n: 2, t: 9 }] });
        return [r.slice(2).map(x => (x.error || '').split(':')[0].slice(0, 12)), err, w && w.arrows.map(a => [a.shape, a.head, a.line]), w && w.bms.length, !!st];""")
    check(got == [['line', 'shape', 'name', 'kind', 'no command "'], '', [['~', '>', 'solid']], 2, True],
          f'"constructor" / "toString": refused by the commands; a copy in this browser with them (and a null) opens, the defaults taken {got}')
    # B13 / B14: ids are numbers (2.0 is 2; true and 1.5 are not), marker id "all" only deletes, a range outside the waves is refused
    got = js("""const v = mk(small(), { key: 'b13' });
        const r = await v.run([{ op: 'bookmark', t: 1000 }, { op: 'bookmark', t: 6000 }, { op: 'bookmark', n: true, text: 'x' }, { op: 'bookmark', n: 1.5 },
          { op: 'arrow', from: true, to: 2 }, { op: 'arrow', from: 1.5, to: 2 }, { op: 'marker', t: 1000 }, { op: 'marker', id: true, label: 'y' },
          { op: 'marker', id: 'all', label: 'oops' }, { op: 'bookmark', n: 2.0, text: 'two' }, { op: 'range', from: 300000, to: 400000 },
          { op: 'range', from: 150000, to: 400000 }]);
        await v.setState({ wavelens: 'state', version: 3, range: { from: 300000, to: 400000, signal: null } });
        return [r.map(x => (x.error ? 'error' : 'ok')), v.umarks.length, v.arrows.length, v.bms.find(b => b.n === 2).text, v.range];""")
    check(got == [['ok', 'ok', 'error', 'error', 'error', 'error', 'ok', 'error', 'error', 'ok', 'error', 'ok'], 1, 0, 'two', None],
          f'n / id / from true or 1.5: refused, 2.0 taken; marker id "all" without delete refused; a range past the end refused, one that '
          f'reaches into the waves cut to them; a state\'s range outside them none, not the wrong way round {got}')
    # V7: compare at scale — the marks of 6000 signals (a map of the rows, not a search per row), the bands of a clock a
    # picosecond late (a band per pixel at most), the analog plot of a busy bus (a bar per pixel column)
    got = js("""const sig = [], vars = [], b0 = [], b1 = [];
        for (let m = 0; m < 120; m++) { const mod = ['m' + m]; vars.push(`$scope module m${m} $end`);
          for (let k = 0; k < 50; k++) { const i = m * 50 + k; mod.push({ name: 's' + k, path: `top.m${m}.s${k}`, width: 8, tv: [[0, '00'], [100, i % 2 ? '01' : '02']] });
            vars.push(`$var wire 8 v${i} s${k} $end`); b0.push(`b0 v${i}`); b1.push(`b1 v${i}`); }
          sig.push(mod); vars.push('$upscope $end'); }
        const v = mk({ signal: [['top', ...sig]], time: { t0: 0, t1: 1000, unit: 'ps' } }, { key: 'v7a' });
        const r = await v.compare(vcd('$scope module top $end ' + vars.join(' ') + ' $upscope $end', '#0 ' + b0.join(' ') + ' #100 ' + b1.join(' ') + ' #1000'), 'b.vcd');
        let t = performance.now(); v.cmpMarks(); const marks = performance.now() - t;
        t = performance.now(); await v.compare(null); const clear = performance.now() - t; v.destroy(); return [r.differ, marks, clear];""")
    check(got[0] == 3000 and got[1] < 300 * SCALE and got[2] < 600 * SCALE, f'6000 signals compared: their marks in {got[1]:.0f} ms, compared no '
          f'more in {got[2]:.0f} ms ({got[0]} differ; it took 941 / 1068 ms)')
    got = js("""const N = 100000, tv = [], body = [];
        for (let i = 0; i < N; i++) { tv.push([i * 10, i % 2 ? '1' : '0']); body.push(`#${i ? i * 10 + 1 : 0} ${i % 2 ? 1 : 0}!`); }
        const v = mk({ signal: [{ name: 'clk', path: 'clk', tv }], time: { t0: 0, t1: N * 10, unit: 'ps' } }, { key: 'v7b' });
        const r = await v.compare(vcd('$var wire 1 ! clk $end', body.join(' ') + ` #${N * 10}`), 'b.vcd'); v.fit();
        let t = performance.now(); v.draw(); const draw = performance.now() - t;
        const pic = v.toSVG(), c = v.cmp; v.cmp = null; const pic0 = v.toSVG(); v.cmp = c;
        const n = s => s.split('<rect').length - 1, w = v.canvas.getBoundingClientRect().width; v.destroy();
        return [r.differ, c.rows.values().next().value.spans.length, n(pic) - n(pic0), draw, Math.ceil(2 * w)];""")
    check(got[0] == 1 and got[1] == 99999 and 0 < got[2] <= 2 * got[4] and got[3] < 250 * SCALE, f'a clock 1 ps late, {got[1]} stretches: '
          f'{got[2]} rects in the picture (2 per band, a band per pixel at most), drawn in {got[3]:.0f} ms (it took 2.6 s at a million)')
    got = js("""const N = 40000, tv = []; for (let i = 0; i < N; i++) tv.push([i * 20, ((i * 7919) % 65536).toString(16)]);
        const v = mk({ signal: [{ name: 'bus', path: 'bus', width: 16, tv, analog: 3 }], time: { t0: 0, t1: N * 20, unit: 'ps' } }, { key: 'v7c' }); v.fit();
        let t = performance.now(); v.draw(); const draw = performance.now() - t, svg = v.toSVG({ rows: 'all' });
        const d = [...svg.matchAll(/<path d="([^"]*)"/g)].map(m => m[1].length).sort((a, b) => b - a)[0]; v.destroy(); return [draw, svg.length, d];""")
    check(got[0] < 200 * SCALE and got[1] < 400000, f'a bus of 40 000 changes as a step plot: drawn in {got[0]:.0f} ms, its picture {got[1] // 1024} KB '
          f'(the longest path {got[2] // 1024} KB; it took 2.5 s and 3 MB at 40 000)')
    page.evaluate('localStorage.clear()')
    check(not errs, 'no page errors (view_review)' + (': ' + ' | '.join(errs[:3]) if errs else ''))
    ctx.close()


def edit(browser, build):
    """The viewer's commands (view.run, wavelens/src/edit.js) and their twin tools/viewedit.py: the same list of commands,
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
    V = "WaveLens.views().find(v => v.editKey() === 'exact')"
    def open_(path, idle=True):
        page.goto(path.as_uri()); page.wait_for_load_state('networkidle' if idle else 'load'); page.evaluate('SVA.ready()'); page.wait_for_timeout(200 * SCALE)
    # a page whose data says "<!--<script>" and "</script>" (a name, a value, the title, an edit's text): it opens whole
    hj, hp = d / 'hostile.json', d / 'hostile.html'
    hj.write_text(json.dumps({'signal': [{'name': '<!--<script>', 'wave': '==', 'data': ['</script><b>', 'x<!--y']}], 'head': {'text': '<!--<script>'}}))
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'mkhtml.py'), f'k={hj}', '--title', '<!--<script> t', '--out', str(hp)],
                       capture_output=True, text=True)
    viewedit.edit_page(str(hp), [{'op': 'marker', 't': 1, 'label': '<!--<script>'}])
    open_(hp)
    got = page.evaluate("[WaveLens.views().length, WaveLens.views()[0].M.rows[0].name, WaveLens.views()[0].markList()[0].label, "
                        "typeof WaveBus !== 'undefined']")   # bus.js: a script after the data
    check(r.returncode == 0 and got == [1, '<!--<script>', '<!--<script>', True], f'a page with "<!--<script>" in its data opens whole {got} {r.stderr[-200:]}')
    open_(pb); page.evaluate('localStorage.clear()'); open_(pb)
    cmds = page.evaluate("Object.fromEntries(Object.entries(WaveLens.commands()).map(([k, c]) => [k, c.args]))")
    check(cmds == viewedit.COMMANDS, f'WaveLens.commands() and tools/viewedit.py COMMANDS: one list (differ: '
          f'{sorted(set(cmds.items()) ^ set(viewedit.COMMANDS.items()))})')
    run = page.evaluate(f"ops => {V}.run(ops).then(res => ({{res, st: {V}.state()}}))", EDIT_OPS)
    check(not [r for r in run['res'] if 'error' in r], f'every command runs in the page ({[r for r in run["res"] if "error" in r][:2]})')
    r = subprocess.run([sys.executable, '-I', str(ROOT / 'tools' / 'viewedit.py'), str(pa), '--view', 'exact', '--ops', json.dumps(EDIT_OPS)],
                       capture_output=True, text=True)
    py = json.loads(r.stdout or '[]')
    check(r.returncode == 0 and len(py) == len(EDIT_OPS) and not [x for x in py if 'error' in x], f'viewedit.py: the same commands on the page\'s file {r.stderr.strip()}')
    # go once the file knows the window (the view command before it): at the start and the end of the waves, clamped alike
    at = next(i for i, o in enumerate(EDIT_OPS) if o['op'] == 'view')
    gos = [(run['res'][i], py[i]) for i, o in enumerate(EDIT_OPS) if o['op'] == 'bookmark' and o.get('go') and at < i < len(py)]
    check(len(gos) == 2 and all(a == b for a, b in gos) and [a['from'] for a, _ in gos] == [0, 65000],
          f'go to a bookmark at the ends of the waves: the same cursor, window (within the waves) and top in both {gos}')
    open_(pa)
    page.wait_for_function(f"localStorage.getItem('wavelens.edits:' + {V}.storeId)")
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
        const vis = WaveLens.internal.peek(v).vis, top = vis.slice(0, 3).map(r => r.name), copy = vis[1];
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
        v.draw(); const o = WaveLens.internal.peek(v).lay.find(o => o.row.ug && o.row.name === 'PSEL'), y = v.bmGeo.pos.get(r[0].n)[1];
        return [r[0].n > 0, Math.abs(y - (o.y + o.h / 2)) < o.h, v.hl.on.has(o.row), r[2].error || ''];
      }})({V})""")
    check(got[:3] == [True, True, True] and got[3].startswith('id: the number of the arrow'),
          f'your group: the bookmark on its row, the highlight on its row; the dump\'s path of a signal; an id that is a name said {got}')
    # the menu: a new group, a marker here, the group deleted from its header
    page.evaluate(f"(v => v.menu(200, 200, v.M.rows.find(r => r.name === 'PWRITE'), 70000))({V})")
    page.locator('.wv-menu .subg').hover(); page.locator('.wv-menu button[data-m=ugnew]').click()
    page.evaluate(f"(v => v.menu(200, 200, WaveLens.internal.peek(v).vis.find(r => r.user && r.name === 'group 2'), 70000))({V})")
    page.locator('.wv-menu .subg').hover(); page.locator('.wv-menu button[data-m=ugdel]').click()
    page.evaluate(f"(v => v.menu(200, 200, v.M.rows.find(r => r.name === 'PWRITE'), 70000))({V})")
    y0 = page.evaluate('scrollY'); page.locator('.wv-menu button[data-m=umark]').click()
    ask = page.locator('.wv-ask'); asked = [ask.count(), page.evaluate("document.activeElement.placeholder"), ask.locator('.mh').inner_text()]
    page.keyboard.type('burst'); page.keyboard.press('Enter')
    got = page.evaluate(f"(v => [v.ugroups.map(g => g.name), v.markList().map(m => [m.t, m.label || ''])])({V})")
    check(got == [['g1'], [[90000, 'mk'], [70000, 'burst']]] and asked[:2] == [1, 'its label'] and ask.count() == 0 and page.evaluate('scrollY') == y0,
          f'the menu: New group with it, Delete this group; Marker here asks its label over the waves (Enter: added, the page where it was) {got} {asked}')
    page.evaluate(f"(v => v.menu(200, 200, v.M.rows.find(r => r.name === 'PWRITE'), 70000))({V})")
    page.locator('.wv-menu button[data-m=umark]').click(); page.keyboard.type('no'); page.keyboard.press('Escape')
    n_esc = page.evaluate(f"(v => v.markList().length)({V})")
    page.evaluate(f"(v => v.menu(200, 200, v.M.rows.find(r => r.name === 'PWRITE'), 70000))({V})")
    page.locator('.wv-menu button[data-m=mark]').click(); page.keyboard.type('write'); page.locator('.wv-ask button[data-m=ok]').click()
    bm = page.evaluate(f"(v => {{ const b = v.bms[v.bms.length - 1]; return [b.signal, b.text, document.activeElement === v.canvas]; }})({V})")
    check(n_esc == 2 and bm[1:] == ['write', True] and bm[0].endswith('PWRITE'),
          f'Esc in it: no marker; Bookmark here asks its text too (Add: added, the keys back on the waves) {n_esc} {bm}')
    # gm: the markers (by time) and the bookmarks in a list over the waves; ↓ the first, each step the cursor on it and the
    # waves at its time with their span, a bookmark's signal selected; a click too; Enter closes it there; the page stays
    page.evaluate(f"(v => {{ v.run({{op: 'view', from: '0ns', to: '40ns'}}); v.canvas.focus({{preventScroll: true}}); }})({V})"); settle(page)
    y0, sp = page.evaluate('scrollY'), page.evaluate(f"(v => v.span)({V})")
    page.keyboard.press('g'); page.keyboard.press('m'); settle(page)
    st = lambda: page.evaluate(f"(v => [v.cursor, Math.round(v.t0 + v.span / 2), v.span, v.sel && v.sel.name])({V})")
    lst = page.locator('.wv-marks button[data-i]'); n_l = lst.count(); seen = []
    for k in ('ArrowDown', 'ArrowDown', 'ArrowDown', 'ArrowUp'):
        page.keyboard.press(k); seen.append(st())
    lst.nth(n_l - 1).click(); seen.append(st()); page.keyboard.press('Enter')
    mk_t, bm_t = page.evaluate(f"(v => [v.markers.map(m => m.t).sort((a, b) => a - b), v.bms.map(b => b.t).sort((a, b) => a - b)])({V})")
    want = (mk_t + bm_t)[:3] + [(mk_t + bm_t)[1]]
    # a marker in the middle; a bookmark 0.2 of the waves from the left (bookmarkLeft), its rows as they were (bookmark_view)
    placed = lambda i, x: x[1] == x[0] if i < len(mk_t) else round(x[1] - x[2] / 2 + x[2] * 0.2) == x[0]   # i: its place in the list
    check(n_l == len(mk_t) + len(bm_t) and [x[0] for x in seen[:4]] == want
          and all(placed(i, x) and x[2] == sp for i, x in zip([0, 1, 2, 1, n_l - 1], seen))
          and seen[4][0] == bm_t[-1] and seen[4][3] and page.locator('.wv-marks').count() == 0,
          f'gm: the markers and bookmarks in a list, ↓ ↓ ↓ ↑ and a click go to each at the same span, a marker in the middle, a bookmark '
          f'0.2 from the left; Enter closes it {seen}')
    # where the rows scroll: the bar's buttons, the bar sticking to the top with the page, folded; kept after a reload
    page.evaluate('localStorage.clear()'); open_(pb)
    page.set_viewport_size({'width': 1300, 'height': 600})
    w = page.locator('.wv').nth(page.evaluate(f"WaveLens.views().indexOf({V})"))
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
    env = dict(os.environ, WAVELENS_LIVE_PORT='0', XDG_CACHE_HOME=str(d / 'cache'))
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
    r = js("""(() => { const o = WaveLens.internal.peek(v).lay.find(o => o.row.name === 'PSEL'), k = v.pxPerT(), e = o.row.tr.filter((e, i) => i && e.t > v.t0 && e.t < v.t0 + v.span);
        return [o.y + o.h / 2 - (WaveLens.internal.peek(v).oy || 0), (e[0].t - v.t0) * k, (e[1].t - v.t0) * k, e[0].t, e[1].t]; })()""")
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
    lane = js("(() => { v.draw(); const m = v.bmGeo.mids.find(x => x[0] === v.arrows.length - 1), o = WaveLens.internal.peek(v).lay.find(o => o.row.name === 'PSEL'); return [m[2] < o.y, o.y]; })()")
    check(lane[0], f'the arrow between the two bookmarks of one signal runs in its label lane above the row, not through the signal {lane}')
    y2 = js("(o => o.y + o.h / 2 - (WaveLens.internal.peek(v).oy || 0))(WaveLens.internal.peek(v).lay.find(o => o.row.name === 'PSEL'))")   # the arrow's label lane moved it
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
    ref = js("[[...v.gapRefSet()].map(r => r.name), v.gapOpt().gaps, [...WaveLens.internal.peek(v).namesEl.querySelectorAll('.row.gref .n')].map(e => e.textContent)]")
    page.mouse.click(box['x'] + 5, box['y'] + y2, button='right'); menu.locator('.subh').click(); by = menu.locator('.gp').nth(1).inner_text()
    menu.locator('input.gonly').check(); only = js("[v.exportRows().filter(r => r.type !== 'lane').map(r => r.name), v.toWaveDrom(v.M.t0, v.M.t1).signal.map(s => s.name)]")
    menu.locator('button[data-m=grefx]').click(); after = js('[v.gapRefSet().size, (v.exportRows() || []).length]')
    check(ref[0] == ['PSEL'] and ref[1] and ref[2] == ['PSEL'] and 'by 1 signal' in by and only == [['PSEL'], ['PCLK', 'PSEL']] and after == [0, 0],
          f'Gaps by this signal: the gaps follow PSEL (// in the names), "only them": the picture and WaveDrom take PSEL alone; ✕: every signal again {ref} {by!r} {only} {after}')
    # the clock the gaps count: Gaps: cycles of this clock (↑ in the names), the cycles under the axis in its name
    ck = js("""(() => { const C = v.M.rows.find(r => r.name === 'PCLK' && r.tr), P = v.M.rows.find(r => r.name === 'PSEL' && r.tr);
        v.menu(10, 10, C); const item = v.menuEl.querySelector('button[data-m=gclk]').textContent; v.menuEl.querySelector('button[data-m=gclk]').click();
        v.setGaps({ gapIdle: 3, gapKeep: 0, gapSignals: [P.full] }); const svg = v.toSVG({ from: v.M.t0, to: v.M.t1 });
        return [item, v.gapClockRow() === C, [...WaveLens.internal.peek(v).namesEl.querySelectorAll('.row.gclk .n')].map(e => e.textContent), /· \\d+ PCLK/.test(svg),
          v.cutsOf(v.M.t0, v.M.t1, [P]).length > 1]; })()""")
    aux = js("""(() => { const A = v.M.rows.find(r => r.name === 'PENABLE' && r.tr), P = v.M.rows.find(r => r.name === 'PSEL' && r.tr);
        v.menu(10, 10, A); v.menuEl.querySelector('button[data-m=gaux]').click(); v.setGaps({ gapOnly: true, gapCount: 'edges' });
        const rows = v.exportRows().filter(r => r.type !== 'lane').map(r => r.name), names = [...WaveLens.internal.peek(v).namesEl.querySelectorAll('.row.gaux .n')].map(e => e.textContent);
        v.menu(10, 10, P); v.menuEl.querySelector('button[data-m=gaux]').click();   // one role per signal: PSEL leaves the ones the gaps follow
        const moved = [v.gapRefSet().size, v.gapRows().aux.size]; v.setGaps({ gapOnly: false }); return [rows, names, moved]; })()""")
    check(aux == [['PCLK', 'PSEL', 'PENABLE'], ['PENABLE'], [0, 2]],
          f'Gaps: count its changes: PENABLE counted (+ in the names), "only them" takes the three kinds; one role per signal {aux}')
    # the marks: on the row between the name and the value (a bus's [7:0] and a long name cut them before); a signal marked +
    # counted with the default texts too ("time, cycles"), its count over the gap in the picture
    mk = js("""(() => { const D = v.M.rows.find(r => r.name === 'PADDR' && r.tr), R = v.M.rows.find(r => r.name === 'PRESETn' && r.tr),
        P = v.M.rows.find(r => r.name === 'PSEL' && r.tr);
        v.setGaps({ gaps: true, gapIdle: 3, gapKeep: 0, gapSignals: [D.full, P.full], gapAux: [R.full], gapCount: 'clock' });
        const el = [...WaveLens.internal.peek(v).namesEl.querySelectorAll('.row.gref')].find(e => e.querySelector('.wd')), n = el.querySelector('.n'), mark = getComputedStyle(el, '::after');
        const got = [n.textContent, mark.content, getComputedStyle(n, '::after').content, mark.order];   // read now: the rows are built again below
        const svg = v.toSVG({ from: v.M.t0, to: v.M.t1 }); v.menu(10, 10, null); const opt = v.menuEl.querySelector('.gcnt option[value=clock]').textContent;
        v.closeMenu(); v.setGaps({ gapAux: null, gapCount: 'off' }); v.menu(10, 10, R); v.menuEl.querySelector('button[data-m=gaux]').click();
        return [...got, /\\d+↑/.test(svg), opt, v.gapOpt().gapCount]; })()""")
    check(mk == ['PADDR[7:0]', '"//"', 'none', '1', True, 'time, cycles, +', 'clock'],
          f'Gaps: the // of a bus with its width a mark of the row (never cut with the name); a signal marked + counted with "time, cycles" (N↑ '
          f'over a gap), Count its changes turns the texts on {mk}')
    js('(v.setGaps({ gapAux: null, gapSignals: null, gapCount: "clock" }), 0)')
    check(ck[0] == 'Count in cycles of this clock' and ck[1] and ck[2] == ['PCLK'] and ck[3] and ck[4],
          f'Gaps: cycles of this clock: the gaps count PCLK (↑ in the names), "· N PCLK" under the axis of the picture {ck}')
    rs = js("""(() => { v.setGaps({ gaps: true, gapIdle: 5, gapAux: ['x'] }); v.menu(10, 10, null); v.menuEl.querySelector('button[data-m=greset]').click();
        const g = v.gapOpt(); return [g.gaps, g.gapIdle, g.gapAux.length, g.gapSignals.length, g.gapClock, !!v.local.gap, v.menuEl]; })()""")
    check(rs == [False, 16, 0, 0, None, False, None], f'Reset the gaps: every gap setting of the viewer back to the settings, the menu closed {rs}')
    js('(v.setGaps(null), 0)')
    # radix and hide from the menu (a bus of the dump: apb_tb.PADDR), the Hidden button, kept over a reload and in the state
    page.goto((build / 'examples' / 'apb' / 'apb_all.html').as_uri()); page.wait_for_load_state('networkidle'); page.evaluate('localStorage.clear()'); page.reload(); page.wait_for_load_state('networkidle')
    c.scroll_into_view_if_needed(); box = c.bounding_box()
    yb = lambda n: js(f"(o => o.y + o.h / 2 - (WaveLens.internal.peek(v).oy || 0))(WaveLens.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.{n}'))")
    # the rows the clicks go to in view (the bar may wrap to more lines and the rows' window be shorter)
    js("(o => { if (v.root.classList.contains('wv-scroll')) v.bodyEl.scrollTop = Math.max(0, o.y - 60); v.draw(); })(WaveLens.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.PADDR'))")
    page.wait_for_timeout(100); box = c.bounding_box()
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PADDR'), button='right'); menu.locator('select:not(.gcnt)').select_option('bin')
    rx = [js("v.valueAt(v.M.rows.find(r => r.full === 'apb_tb.PADDR'), v.cursor)"), menu.count()]
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('PWDATA'), button='right'); menu.locator('button[data-m=hide]').click()
    hid = [js("WaveLens.internal.peek(v).vis.some(r => r.full === 'apb_tb.PWDATA')"), page.locator('.wv button[data-act=unhide]').first.inner_text(), js('v.state().hidden'), js('v.state().radix')]
    page.reload(); page.wait_for_load_state('networkidle')
    kept = [js("WaveLens.internal.peek(v).vis.some(r => r.full === 'apb_tb.PWDATA')"), js("v.M.rows.find(r => r.full === 'apb_tb.PADDR').radix")]
    page.locator('.wv button[data-act=unhide]').first.click(); js("(v.setRadix('apb_tb.PADDR', null), 0)")
    back = [js("WaveLens.internal.peek(v).vis.some(r => r.full === 'apb_tb.PWDATA')"), js("v.M.rows.find(r => r.full === 'apb_tb.PADDR').radix || ''"), js('localStorage.getItem(v.rowsKey)')]
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
    dt = page.locator('.wv .notes .dt').first.inner_text(); here = js("[...document.querySelectorAll('.wv .notes li[data-n]')].map(li => li.classList.contains('here'))")
    page.keyboard.press('Escape'); gone = js('v.cursor2')
    js('(v.cursor = 0, v.draw(), 0)'); away = js("document.querySelector('.wv .notes li[data-n]').classList.contains('here')")
    check(c2[0] and c2[0] != 25000 and c2[3] == c2[4] and c2[3] > 0 and f'{c2[3]} PCLK' in c2[1] and 'cursor 2' in c2[2] and c2[5] == c2[0] and sw == [c2[0], 25000]
          and k1 == nb and dt == '' and here == [True] and not away and gone is None,
          f'shift+click: the second cursor (on an edge), Δ and the PCLK cycles between, in the state; x swaps, 1 goes to bookmark 1, its line marked '
          f'in the list (no Δ), not once the cursor moves; Esc clears it {c2} {sw} {dt!r} {here} {away}')
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
        v.select(null); v.cursor = v.M.t0; v.setEdgeKind('xz'); const xs = WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig' && r.tr).flatMap(r => r.tr.filter((o, i) => (o.k === 'x' || o.k === 'z' || (o.raw && /[xz]/i.test(o.raw))) && o.t > v.cursor && !(i && (r.tr[i - 1].k === 'x' || r.tr[i - 1].k === 'z'))).map(o => o.t));
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
    page.evaluate("WaveLens.configure({enumColors: {ACCESS: '#ff00aa', 1: 'c8'}})"); esvg = js('v.toSVG()'); page.evaluate("WaveLens.configure({enumColors: null})")
    check(qopen == [True, 1] and fx == ['sq16', '-13569.9999847412109375'] and fl == '-8323073' and '#ff00aa' in esvg,
          f'Radix: fixed sq with 16 fraction bits (the menu stays open for them), float; enumColors fill the ACCESS state {fx} {fl}')
    # Analog from the menu: the bus as a step plot three rows high, kept over a reload and in the state; As a bus: back
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('n_done'), button='right'); menu.locator('button[data-m=analog]').click()
    an = js("[(o => [o.h, v.rowH.sig])(WaveLens.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.n_done')), v.state().analog, Math.round(v.rowEl(v.M.rows.find(r => r.full === 'apb_tb.n_done')).getBoundingClientRect().height)]")
    page.reload(); page.wait_for_load_state('networkidle'); c.scroll_into_view_if_needed(); box = c.bounding_box()
    kept = js("v.M.rows.find(r => r.full === 'apb_tb.n_done').analog")
    page.mouse.click(box['x'] + 300, c.bounding_box()['y'] + yb('n_done'), button='right'); label = menu.locator('button[data-m=analog]').inner_text(); menu.locator('button[data-m=analog]').click()
    off = js("[v.M.rows.find(r => r.full === 'apb_tb.n_done').analog, (o => o.h)(WaveLens.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.n_done'))]")
    parsed = page.evaluate("WaveLens.parse({ signal: [{ name: 'lvl', wave: '=.=', data: ['1', '9'], analog: 2 }] }).rows[0].analog")
    check(an[0] == [3 * an[0][1], an[0][1]] and an[1] == {'apb_tb.n_done': 3} and an[2] == 3 * an[0][1] and kept == 3 and label == 'As a bus' and off == [False, an[0][1]] and parsed == 2,
          f'Analog: a step plot three rows high (names too), kept over a reload and in the state; As a bus: back; "analog" in the WaveJSON {an} {kept} {off}')
    js("(v.setAnalog('apb_tb.n_done', null), localStorage.clear(), 0)")
    # a click on a name selects it, shift+click every signal from it to the clicked one: selected, nothing dimmed, the
    # selection's tint inside the bus values too
    px = lambda n: js(f"""(() => {{ v.draw(); const o = WaveLens.internal.peek(v).lay.find(o => o.row.full === 'apb_tb.{n}'), r = window.devicePixelRatio || 1, x = Math.round(v.canvas.width / 2 / r);
        return [...v.canvas.getContext('2d').getImageData(Math.round(x * r), Math.round((o.y + o.h / 2 + 5 - (WaveLens.internal.peek(v).oy || 0)) * r), 1, 1).data].slice(0, 3); }})()""")
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
    back = page.evaluate("d => { const M = WaveLens.parse(d); return M.rows.filter(r => r.type === 'sig').map(r => r.name); }", wd)
    js("(v.highlight(null), v.setRange(null), 0)")
    check('>PADDR<' in svg and '>PWDATA<' in svg and '>PRDATA<' not in svg and '>PREADY<' not in svg,
          'with rows highlighted, Save image draws those rows only')
    check(name.endswith('.wavedrom.json') and list(sig) == ['PCLK', 'PSEL', 'PADDR', 'PWDATA'] and set(sig['PCLK']['wave'][1:]) == {'.'} and sig['PCLK']['wave'][0] == 'p'
          and len({len(x['wave']) for x in wd['signal']}) == 1 and sig['PADDR']['data'][:3] == ['0x00', '0x04', '0x40'] and back == list(sig),
          f'Save as WaveDrom: the highlighted signals and their clock (p...), a cell per cycle, bus values as data; WaveLens reads it back {name} {[(k, x["wave"][:24]) for k, x in sig.items()]}')
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
    apb = page.evaluate("(() => { const v = document.querySelector('#ex-apb').waveView; return [v.sva.bindings.filter(b => b.state === 'bound' && b.results).length, WaveLens.internal.peek(v).vis.filter(r => r.sva).length]; })()")
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
    rows = page.evaluate("WaveLens.internal.peek(document.querySelector('#ex-sva').waveView).vis.filter(r => r.cls && !/^sva-x|^sva-expr/.test(r.cls)).map(r => [r.cls, r.name])")
    check(rows[:4] == [['sva-g fails', '⚑ a_req_ack · 2 pass · 1 fail'], ['sva-lane', 'attempts'], ['sva-step', '1. req'], ['sva-step', '2. ##[1:3] ack']]
          and [r[1] for r in rows if r[0] == 'sva-copy'][:4] == ['clk', 'rst_n', 'req', 'ack'], f'docs: the assertion group under the top: lane, steps, the bound signals {rows[:6]}')
    page.wait_for_function("WaveLens.internal.peek(document.querySelector('#ex-sva').waveView).vis.filter(r => (r.cls || '').startsWith('sva-expr') && r.tr.length).length === 2")
    xr = page.evaluate("""(() => { const v = document.querySelector('#ex-sva').waveView, rs = WaveLens.internal.peek(v).vis.filter(r => (r.cls || '').startsWith('sva-expr'));
      return [WaveLens.internal.peek(v).vis[WaveLens.internal.peek(v).vis.findIndex(r => r.cls === 'sva-xg') - 1].name, rs.map(r => [r.name, r.tr.filter(o => o.k === '1').map(o => o.t)])]; })()""")
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
    """wavelens/sva.js on hand-made models: scopes, the name rules, samplers."""
    # the page's bindings: "results.cycles" names a table of "sva.cycles" (mkhtml.py keeps the times once per clock), an
    # array is read as it is (older pages), a name not in the table is the binding's error
    pb = page.evaluate("""(() => { const r = c => ({ clock: 'tb.clk', unit: 'ps', cycles: c, assertions: [{ name: 'a' }] });
      const M = WaveLens.parse({ signal: [{ name: 'clk', wave: 'p..' }], sva: { cycles: { 'tb.clk': [5, 15] },
        bind: [{ assert: 'a', scope: 's', results: r('tb.clk') }, { assert: 'b', scope: 's', results: r([1, 2, 3]) }, { assert: 'c', scope: 's', results: r('nope') }] } });
      const b = SVA.pageBinds(M); return [b.map(x => x.results && x.results.cycles), b[2].error, SVA.pageBinds(M) === b, M.src.sva.bind[0].results.cycles]; })()""")
    check(pb == [[[5, 15], [1, 2, 3], None], 'no cycles table "nope" in the page', True, 'tb.clk'],
          f'the page\'s bindings take their times from "sva.cycles" (once per clock), an array as it is, a missing table is an error {pb}')
    r = page.evaluate("""(() => {
      const tv = (...p) => p.map(([t, v]) => [t, v]);
      const M = WaveLens.parse({ signal: [['tb', { name: 'clk', path: 'tb.clk', tv: tv([0, '0'], [5, '1'], [10, '0'], [15, '1']) },
        ['dut', { name: 'VALID', path: 'tb.dut.s_valid', tv: tv([0, '0']) }, { name: 'data', path: 'tb.dut.data', width: 8, tv: tv([0, '00'], [7, 'ab']) },
          { name: 'ready', path: 'tb.dut.ready', tv: tv([0, '1']) }, ['u_fifo', { name: 'full', path: 'tb.dut.u_fifo.full', tv: tv([0, '0']) }]]]] });
      const v = { M, sortIgnore: ['s_', 'i_'] }, I = SVA.scopeInfo(M);
      const a = { signals: [{ name: 'clk' }, { name: 'valid' }, { name: 'u_fifo.full' }, { name: 'data', width: 16 }, { name: 'VALID' }] };
      const res = SVA.resolve(v, a, 'tb.dut');
      const map = Object.fromEntries(Object.entries(res.map).map(([n, r]) => [n, r.full]));
      const cand = SVA.candidates(v, { signals: [{ name: 'clk' }, { name: 'ready' }] });
      const strict = SVA.resolve({ M, sortIgnore: [] }, { signals: [{ name: 'clk' }, { name: 'valid' }] }, 'tb.dut');
      const W = WaveLens.parse({ signal: [{ name: 'clk', wave: 'p...' }, { name: 'st', wave: '3.4.', data: ['IDLE', 'RUN'], enum: { 0: 'IDLE', 1: 'RUN' } },
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
    raw = page.evaluate("""(() => { const W = WaveLens.parse({ signal: [{ name: 'clk', wave: 'p...' }, { name: 'd', wave: '=.=.', data: ['0101', '0011'], radix: 'bin', width: 4 },
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
const I = WaveLens.internal, F = WaveLens;
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
    # what the reader noticed, by its line: an unknown code, a word that is no value, too many bits, a $timescale it cannot read;
    # an error it cannot read past says its line; the parameters of the dump
    ("VW('$timescale 1ns $end\\n$scope module tb $end\\n$var wire 2 ! a $end\\n$upscope $end\\n$enddefinitions $end\\n#0\\nb00 !\\n1?\\nfoo\\n#5\\nb101 !\\n')"
     ".log.map(x => [x.level, x.line, x.text.split(' ')[0]])", [['warning', 8, 'a'], ['warning', 9, '"foo"'], ['warning', 11, '3']]),
    ("(r => [r.log[0].line, r.log[0].text.slice(0, 11), r.info.timescale])(VW('$timescale\\n 1 parsec $end\\n$var wire 1 ! a $end $enddefinitions $end #0 1!'))",
     [1, '$timescale ', None]),
    # a width that is not a number of bits is 1, as its note says (review IV A13)
    ("(r => [r.doc.signal[0].width ?? 1, r.doc.signal[0].tv, r.log[0].text.includes('1 taken')])(VW('$var wire -1 ! a $end $enddefinitions $end #0 1!'))",
     [1, [[0, '1']], True]),
    # an integer variable (Questa's int-based enum) is signed decimal; with an enum table, its labels
    ("VW('$scope module tb $end $var integer 32 ! c $end $var reg 2 \" s $end $upscope $end $enddefinitions $end #0 b1100 ! b1 \"').doc.signal[0].slice(1).map(x => x.radix || null)",
     ['signed', None]),
    ("(() => { try { VW('$var wire 1 ! s $end $enddefinitions $end\\n#10\\n0!\\n#5\\n1!'); } catch (e) { return [e.line, / \(line 4\)$/.test(e.message)]; } })()",
     [4, True]),
    ("(r => [r.info.version, r.info.timescale, r.info.t1, r.info.signals, r.info.changes, r.log.length])(VW('$version Icarus  Verilog $end $timescale 10ps $end "
     "$scope module tb $end $var wire 1 ! a $end $upscope $end $enddefinitions $end #0 0! #3 1!'))", ['Icarus Verilog', '10ps', 30, 1, 2, 0]),
    ("(r => r.log.map(x => x.text.slice(0, 7)))(VW(vcd('$var wire 1 ! a $end', '#0 ' + '0? '.repeat(25))))", ['a value'] * 20 + ['no valu', '1 signa', '5 more ']),
    # bus decoders on a model built in the page: per protocol, an x-valued valid, a clock starting at x, W before AW
    ("BUS('u_apb', { PSEL: '0111000', PENABLE: '0011000', PREADY: '0001000', PWRITE: '0111000', PADDR: [0, 0x10, 0x10, 0x10, 0, 0, 0], PWDATA: [0, 0x55, 0x55, 0x55, 0, 0, 0] }, 'PCLK')",
     [['apb', [['W', 'W 0x10 ← 0x55', 3, False]]]]),
    # review IV B15: an APB transfer still waiting when the dump ends is open; PSEL dropped before PREADY: an error
    ("BUS('u_apb', { PSEL: '0111', PENABLE: '0011', PREADY: '0000', PWRITE: '0111', PADDR: [0, 0x10, 0x10, 0x10], PWDATA: [0, 0x55, 0x55, 0x55] }, 'PCLK')",
     [['apb', [['W', 'W 0x10 ← 0x55', None, False]]]]),
    ("BUS('u_apb', { PSEL: '01100', PENABLE: '00100', PREADY: '00000', PWRITE: '00000', PADDR: [0, 0x20, 0x20, 0, 0] }, 'PCLK')",
     [['apb', [['R', 'R 0x20 → ?', 2, True]]]]),
    # review IV B14 / B15: pipelined Wishbone, a request acked in its own cycle; one not acked when the dump ends (open)
    ("BUS('u_wb', { wb_cyc_o: '01111', wb_stb_o: '01010', wb_stall_i: '00000', wb_ack_i: '01000', wb_we_o: '00000', wb_adr_o: [0, 0x10, 0, 0x14, 0], "
     "wb_dat_i: [0, 0x55, 0, 0, 0] })", [['wb', [['R', 'R 0x10 → 0x55', 1, False], ['R', 'R 0x14 → ?', None, False]]]]),
    # review IV D5: a pipelined request stalled to the end (never accepted) is open; stalled when CYC drops: an error
    ("BUS('u_wb', { wb_cyc_o: '0111', wb_stb_o: '0111', wb_stall_i: '0111', wb_ack_i: '0000', wb_we_o: '0000', wb_adr_o: [0, 0x10, 0x10, 0x10] })",
     [['wb', [['R', 'R 0x10 → ?', None, False]]]]),
    ("BUS('u_wb', { wb_cyc_o: '01100', wb_stb_o: '01100', wb_stall_i: '01100', wb_ack_i: '00000', wb_we_o: '00000', wb_adr_o: [0, 0x10, 0x10, 0, 0] })",
     [['wb', [['R', 'R 0x10 → ?', 2, True]]]]),
    # … and one whose CYC drops before its ack: an error, not lost
    ("BUS('u_wb', { wb_cyc_o: '01110', wb_stb_o: '01010', wb_stall_i: '00000', wb_ack_i: '01000', wb_we_o: '00000', wb_adr_o: [0, 0x10, 0, 0x14, 0], "
     "wb_dat_i: [0, 0x55, 0, 0, 0] })", [['wb', [['R', 'R 0x10 → 0x55', 1, False], ['R', 'R 0x14 → ?', 1, True]]]]),
    # review IV B13: AXI3, W beats of IDs 1 and 2 interleaved (1:A1, 2:B1 last, 1:A2 last): each burst to the AW of its ID
    ("BUS('u_axi', { s_axi_awvalid: '0110000000', s_axi_awready: '0110000000', s_axi_awaddr: [0, 0x100, 0x200, 0, 0, 0, 0, 0, 0, 0], "
     "s_axi_awid: [0, 1, 2, 0, 0, 0, 0, 0, 0, 0], s_axi_awlen: [0, 1, 0, 0, 0, 0, 0, 0, 0, 0], s_axi_wvalid: '0001110000', s_axi_wready: '0001110000', "
     "s_axi_wid: [0, 0, 0, 1, 2, 1, 0, 0, 0, 0], s_axi_wdata: [0, 0, 0, 0xa1, 0xb1, 0xa2, 0, 0, 0, 0], s_axi_wlast: '0000110000', "
     "s_axi_bvalid: '0000001100', s_axi_bready: '0000001100', s_axi_bid: [0, 0, 0, 0, 0, 0, 2, 1, 0, 0], s_axi_bresp: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0], "
     "s_axi_arvalid: '0000000000', s_axi_arready: '0000000000', s_axi_rvalid: '0000000000' }, 'aclk').map(([p, t]) => [p, t.map(x => x[1])])",
     [['axi', ['W 0x100 ← 0xa1 ×2', 'W 0x200 ← 0xb1']]]),
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
    """The pure functions of the viewer (WaveLens.internal, unstable), the page's VCD reader, the bus decoders and the
    expressions of sva.js on a blank page: one case per line of UNITS, all in one evaluate."""
    page = browser.new_page()
    page.goto('about:blank')
    for f in ('wavelens.config.js', 'wavelens.js', 'sva.wasm.js', 'bus.js', 'sva.js'):
        page.add_script_tag(path=str(ROOT / 'wavelens' / f))
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
    # ✕ fires wavelens:sva for the bindings it removes
    n = page.evaluate("""(() => { let n = 0; const r = document.querySelector('.wv'); r.addEventListener('wavelens:sva', () => n++);
        document.querySelector('.wv .sva li[data-a="m7"] button[data-sv=del]').click(); return n; })()""")
    check(n == 1, f'✕ on a bound assertion fires wavelens:sva ({n})')
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
        const at = () => WaveLens.internal.peek(v).vis.indexOf(row), kids = () => WaveLens.internal.peek(v).vis.filter(r => r.anc.includes(g.id));
        const H0 = WaveLens.internal.peek(v).lay.H, pos = [at(), kids().indexOf(row), kids().length];
        const own = () => kids().filter(r => r.anc[r.anc.length - 1] === g.id && r.type === 'sig' && !r.cls && r !== row);
        v.setSort('desc'); const sorted = kids().indexOf(row) > Math.max(...own().map(r => kids().indexOf(r)));
        v.setSort('none'); v.find('probe'); const found = v.found.has(row); v.clearFind();
        WaveLens.internal.peek(v).collapsed.add(g.id); v.renderNames(); v.draw(); const folded = at() === -1;
        WaveLens.internal.peek(v).collapsed.delete(g.id); v.renderNames(); v.draw();
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
# the bindings of the exact views evaluated over the dump only (their signals not in the view): view:assertion
SVA_DUMP_ONLY = {'axi_lite': {'WAVES.exact:axi_done'},
                 'fsm': {'WAVES.status:' + a for a in ('fsm_from_idle', 'fsm_from_start', 'fsm_from_data', 'fsm_from_stop', 'fsm_from_error',
                         'fsm_start_bit', 'fsm_error_exit', 'fsm_data_bits', 'fsm_frame_time', 'fsm_demo_short_data', 'fsm_valid',
                         'fsm_frame_err', 'fsm_one_flag', 'fsm_cov_byte', 'fsm_cov_error')}}


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
        WaveLens.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveLens.internal.peek(v).vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
        return [b.assert, st.g.name, st.lane.drawn, o.kind === 'cover' ? o.attempts.length : o.stats.pass + o.stats.fail + o.stats.active + o.stats.disabled + o.stats.capped, WaveLens.internal.peek(v).vis.includes(st.lane), st.g.anc.length]; });""")
    bad = [x for x in g if x[2] != x[3] or not x[4] or x[5] != 0]
    check(len(g) == 14 and not bad and g[10][1] == '⚑ apb_demo_no_wait · 3 pass · 2 fail', f'apb: 14 assertion groups at the top of the view with their counts, bars = attempts listed {bad[:3]} {g[10][:2]}')
    # a click on the first failing bar: the attempt is selected, the cursor at its start, a red arrow with the reason
    hit = js("""const b = p.bindings.find(b => b.assert === 'apb_demo_no_wait'), st = b.draw;
        WaveLens.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveLens.internal.peek(v).vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
        const o = WaveLens.internal.peek(v).lay.find(o => o.row === st.lane), h = st.lane.hits.find(h => h[4].r === 'fail'), r = v.canvas.getBoundingClientRect();
        return [r.left + (h[0] + h[1]) / 2, r.top + o.y - WaveLens.internal.peek(v).oy + (h[2] + h[3]) / 2, b.results.cycles[h[4].a.start]];""")
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
        const row = n => WaveLens.internal.peek(v).lay.find(o => o.row === w.res.map[n]), y = n => row(n).y + row(n).h / 2;
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
        WaveLens.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveLens.internal.peek(v).vis.indexOf(st.lane)}"]`).scrollIntoView({ block: 'start' }); v.draw();
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
    pos = js("""const top = WaveLens.internal.peek(v).vis.filter(r => r.type === 'sig' && !r.anc.length && !r.cls), gs = WaveLens.internal.peek(v).vis.filter(r => r.sva);
        return [Math.max(...top.map(r => WaveLens.internal.peek(v).vis.indexOf(r))) < Math.min(...gs.map(r => WaveLens.internal.peek(v).vis.indexOf(r))), gs.length];""")
    js("v.setSort('none'); v.find('demo_no_wait');")
    found = js("return [...v.found.keys()].filter(r => r.sva).map(r => r.sva);")
    js("v.find('PREADY');")
    found += js("return [...v.found.keys()].filter(r => r.cls === 'sva-step').map(r => r.name);")
    js('v.clearFind(); v.collapseAll();')
    col = js("return [WaveLens.internal.peek(v).vis.filter(r => r.sva).length, WaveLens.internal.peek(v).vis.filter(r => r.cls === 'sva-lane').length];")
    js('v.expandAll();')
    exp = js("return WaveLens.internal.peek(v).vis.filter(r => r.cls === 'sva-lane').length;")
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
        const b = p.bindings[p.bindings.length - 1]; WaveLens.internal.peek(v).namesEl.querySelector(`.row[data-r="${WaveLens.internal.peek(v).vis.indexOf(b.draw.lane)}"]`).scrollIntoView({ block: 'center' }); v.draw();
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
        v.expandAll(); const kids = () => WaveLens.internal.peek(v).vis.filter(r => r.anc.includes(g.id)), own = () => kids().filter(r => r.anc[r.anc.length - 1] === g.id && r.type === 'sig' && !r.cls);
        const after = () => kids().indexOf(st.g) > Math.max(...own().map(r => kids().indexOf(r)));
        const a = [st.g.anc[st.g.anc.length - 1] === g.id, after(), st.g.name]; v.setSort('asc'); a.push(after()); v.setSort('none');
        WaveLens.internal.peek(v).collapsed.add(g.id); v.renderNames(); a.push(WaveLens.internal.peek(v).vis.includes(st.g)); WaveLens.internal.peek(v).collapsed.delete(g.id); v.renderNames(); v.draw(); return a;""")
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
    steps = page.evaluate("WaveLens.internal.peek(SVA.panels()[0].v).vis.filter(r => r.cls === 'sva-step').map(r => r.name)")
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
        WaveLens.internal.peek(p.v).namesEl.querySelector(`.row[data-r="${WaveLens.internal.peek(p.v).vis.indexOf(b.draw.lane)}"]`).scrollIntoView({ block: 'center' }); p.v.draw();
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
    form = page.evaluate("""Object.values(window.WAVES).filter(d => d.sva && (d.sva.bind || []).some(b => b.results)).map(d => [Object.keys(d.sva.cycles || {}).length,
        d.sva.bind.filter(b => b.results).every(b => typeof b.results.cycles === 'string' && Array.isArray(d.sva.cycles[b.results.cycles]))])""")
    check(form and all(k >= 1 and ok for k, ok in form), f'{ex}: the bindings name their times in "sva.cycles", once per clock (not an array each) {form}')
    check(all(x['n'] == n and len(x['binds']) == n for x in p), f'{ex}: every viewer lists the {n} assertions of the config, all bound ({[(x["n"], len(x["binds"])) for x in p]})')
    deliberate = SVA_EXAMPLES[ex][2]
    fails = sorted({b[0] for x in p for b in x['binds'] if b[2] != 'cover' and b[3]})
    states = {b[1] for x in p for b in x['binds']}
    check(fails == sorted(deliberate) and states <= {'bound', 'dump'}, f'{ex}: results from sva eval at build time, only {fails} fails ({states})')
    # the exact views again in the page: sva eval's results (built with the page), also through the Web Worker — not only
    # the counts (review VI T4: a failure moved to another cycle had the same totals): the clock, the cycles' times, each
    # attempt's start, end, verdict, failing cycle, witness and antecedent ends, by time; a binding left out by name only
    # (SVA_DUMP_ONLY: evaluated over the dump at build time, its signals not in the page)
    diff = page.evaluate("""async () => { const out = [];
        const norm = (r, a) => { const u = { ps: 1, ns: 1e3, us: 1e6, ms: 1e9, fs: 1e-3 }[r.unit] || 1, T = c => (c == null ? null : Math.round(r.cycles[c] * u));
          return JSON.stringify({ clock: String(r.clock).split('.').pop(), cycles: r.cycles.map(c => Math.round(c * u)), name: a.name, kind: a.kind,
            stats: Object.keys(a.stats).sort().map(k => k + '=' + a.stats[k]).join(' '),
            attempts: (a.attempts || []).map(x => [T(x.start), T(x.end), x.result, T(x.failed_at), (x.trace || []).map(([s, c]) => s + '@' + T(c)),
              (x.ante_end || []).map(T)]) }); };
        for (const p of SVA.panels()) { if (!p.v.M.rows.some(r => r.src && r.src.tv)) continue;
          for (const [i, b] of p.bindings.entries()) { if (b.state !== 'bound') { out.push([b.assert, b.state, null, p.v.root.dataset.wave]); continue; }
            const nat = norm(b.results, b.results.assertions[0]); SVA.syncLimit = i === 0 ? 0 : 100000;
            await p.evaluate(b); const pag = norm(b.results, b.results.assertions[0]);
            out.push([b.assert, b.via, nat === pag && !b.error, nat === pag ? '' : nat.slice(0, 200) + ' / ' + pag.slice(0, 200), p.v.root.dataset.wave]); } }
        SVA.syncLimit = 100000; return out; }""")
    done = [d for d in diff if d[2] is not None]
    left = sorted({f'{d[3]}:{d[0]}' for d in diff if d[2] is None})
    bad = [d for d in done if not d[2]]
    want = sorted(SVA_DUMP_ONLY.get(ex, ()))
    views = {d[-1] for d in diff}   # each exact view: all n, evaluated again or left out by name
    check(views and all(sum(d[-1] == w for d in diff) == n for w in views) and not bad and done[0][1] == 'worker' and left == want,
          f'{ex}: {len(done)} bindings evaluated again in the page give sva eval\'s results attempt by attempt (first through a worker: '
          f'{done[0][1] if done else None}); {len(left)} left out by name' + (f'; differ {bad[:2]}' if bad else '') +
          ('' if left == want else f'; left out {left}, want {want}'))


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
    """wavelens/sva.wasm.js (committed) is the packed module of the current build."""
    import base64, zlib
    wasm = build / 'sva-target' / 'wasm32-unknown-unknown' / 'wasm' / 'sva_wasm.wasm'
    js = (ROOT / 'wavelens' / 'sva.wasm.js').read_text()
    m = re.search(r'"size": (\d+), "deflate": "([^"]+)"', js)
    raw = zlib.decompress(base64.b64decode(m.group(2)), -15) if m else b''
    check(m and len(raw) == int(m.group(1)) and raw[:4] == b'\0asm', f'wavelens/sva.wasm.js: a WebAssembly module, {len(raw)} B ({len(js)} B in the page)')
    if need(wasm, how='make sva-build'):
        check(raw == wasm.read_bytes(), 'wavelens/sva.wasm.js is the module of the current build (make sva-build writes it)')


# sva eval over the example dumps (make sva-build, make examples): (pass, fail) per assertion where they are not
# (n, 0); every testbench has one deliberately wrong assertion
SVA_EXAMPLES = {
    'apb': (['--scope', 'apb_tb', '--sva', 'examples/apb/apb_tb.sv', '--sva', 'examples/apb/apb.sva'], 14, {'apb_demo_no_wait': (3, 2)}),
    'axi_lite': (['--scope', 'axi_lite_tb.u_slave', '--sva', 'examples/axi_lite/axi_lite.sva'], 19, {'axi_demo_aw_at_once': (0, 1)}),
    'fsm': (['--scope', 'fsm_tb.u_rx', '--sva', 'examples/fsm/uart_pkg.sv', '--sva', 'examples/fsm/fsm.sva'], 15, {'fsm_demo_short_data': (0, 2)}),
}


# review VI T4: what each third-party evaluation must find, not only "no failure": the attempts that pass, fail, are
# vacuous, disabled or capped (the asserts and assumes), the covers and how many of them match (tests/sva/third_party
# stays as it came: the expectations are here)
THIRD_PARTY = {
    ('saravana_apb', 'apb_tb.u_regs'): {'pass': 46, 'fail': 0, 'vacuous': 203, 'disabled': 0, 'capped': 0, 'covered': 4, 'covers': 4},
    ('saravana_apb', 'apb_tb.u_master'): {'pass': 46, 'fail': 0, 'vacuous': 203, 'disabled': 0, 'capped': 0, 'covered': 4, 'covers': 4},
    ('yosyshq_axi4_lite', 'axi_lite_tb.u_slave'): {'pass': 23, 'fail': 0, 'vacuous': 432, 'disabled': 0, 'capped': 0, 'covered': 3, 'covers': 4},
    ('yosyshq_axi4_lite', 'axi_lite_tb.u_master'): {'pass': 23, 'fail': 0, 'vacuous': 432, 'disabled': 0, 'capped': 0, 'covered': 3, 'covers': 4},
    ('opentitan_apb', 'apb_tb.u_regs'): {'pass': 86, 'fail': 0, 'vacuous': 104, 'disabled': 0, 'capped': 0, 'covered': 2, 'covers': 2},
    ('sindhugd_axi4lite', 'axi_lite_tb.u_slave'): {'pass': 4, 'fail': 0, 'vacuous': 176, 'disabled': 0, 'capped': 0, 'covered': 0, 'covers': 0},
}


def sva_third_party(build):
    """tests/sva/third_party/units.json: every evaluation over an example dump, no failure but the listed ones, the
    totals of THIRD_PARTY (a vacuous run is not a pass)."""
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
            tot = {k: sum(a['stats'].get(k, 0) for a in doc['assertions'] if a['kind'] != 'cover') for k in ('pass', 'fail', 'vacuous', 'disabled', 'capped')}
            tot.update(covered=sum(1 for a in doc['assertions'] if a['kind'] == 'cover' and a['stats'].get('matches', a['stats']['pass'])),
                       covers=sum(1 for a in doc['assertions'] if a['kind'] == 'cover'))
            want = THIRD_PARTY.get((u['name'], e['scope']))
            check(ok and tot == want, f'third party {u["name"]} at {e["scope"]}: {len(doc["assertions"])} assertions, {tot} (want {want}), failures {fails}, '
                  f'missing {missing}, exit {r.returncode}')


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
                WaveLens.parse(CASES[i][1]).rows.filter(r => r.type !== 'group').length, tx(st), tx(mine)]; })""")
    check(len(got) == 11, f'conformance: {len(got)} cases')
    for title, lanes, rows, stock, mine in got:
        diff = '' if stock == mine else f': only in stock {sorted(set(stock) - set(mine))}, only in wavelens {sorted(set(mine) - set(stock))}, {len(stock)} / {len(mine)} texts'
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


def bar_tools(page, P):
    """The right button on the bar: its tool groups with a tick each; a click leaves one out (the menu stays open), Hide
    all leaves every line of tools out, / still floats the find; kept in this browser and in the state; Show all; a field
    keeps the browser's own menu."""
    print('bar_tools: the right button on the bar')
    v = page.locator('.wv').first
    js = lambda e: page.evaluate(f"(() => {{ const v = document.querySelector('.wv').waveView; return {e}; }})()")
    m, ticks = page.locator('.wv-menu.wv-tools'), lambda: m.locator('button[data-tg]').evaluate_all("bs => bs.map(b => [b.dataset.tg, b.getAttribute('aria-checked')])")
    v.locator('.bar .tg[data-tg="list"] .tl').click(button='right'); settle(page)
    t = ticks()
    check(m.count() == 1 and {'cursor', 'view', 'find', 'list', 'state'} <= {n for n, _ in t} and all(c == 'true' for _, c in t),
          f'the right button on the bar: a menu of its tool groups, each ticked {[n for n, _ in t]}')
    m.locator('button[data-tg="cursor"]').click(); settle(page)
    check(m.count() == 1 and v.locator('.bar .tg[data-tg="cursor"]').is_hidden() and dict(ticks())['cursor'] == 'false' and
          js('v.state().config.toolsHidden') == ['cursor'] and 'cursor' in (js('localStorage.getItem(v.lookKey)') or ''),
          'a click leaves the cursor out: the menu stays open, its tick off; in the state and in this browser')
    h0 = js("v.root.querySelector('.bar').getBoundingClientRect().height")
    m.locator('button[data-m=none]').click(); settle(page)
    left = js("[...v.root.querySelectorAll('.bar .tools .tln')].filter(l => l.querySelector('.tg') && l.offsetHeight).length")
    h1 = js("v.root.querySelector('.bar').getBoundingClientRect().height")
    check(left == 0 and h1 < h0 and all(c == 'false' for _, c in ticks()), f'Hide all: no line of tools left, the bar {h0:.0f} -> {h1:.0f} px')
    page.keyboard.press('Escape'); settle(page)
    v.locator('canvas').evaluate('c => c.focus({ preventScroll: true })'); page.keyboard.press('/'); settle(page)
    fl = [m.count(), v.locator('.tg.find.float').is_visible(), page.evaluate('document.activeElement.matches("input.q")')]
    check(fl == [0, True, True], f'Esc closes the menu; / floats the find that is left out of the bar {fl}')
    page.keyboard.press('Escape'); settle(page)
    check(v.locator('.tg.find').is_hidden(), 'Esc puts it back: left out again')
    v.locator('.bar .head').click(button='right'); settle(page); m.locator('button[data-m=all]').click(); settle(page)
    check(v.locator('.bar .tools .tg.off').count() == 0 and js('v.state().config.toolsHidden') == [] and 'toolsHidden' not in (js('localStorage.getItem(v.lookKey)') or ''),
          'Show all: every group again, nothing kept')
    page.keyboard.press('Escape')
    v.locator('input.q').dispatch_event('contextmenu'); settle(page)
    check(m.count() == 0, 'the right button in a field: the browser\'s menu (paste), not this one')


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
        v.buses.select(p, x); return [v.cursor === x.t0, v.range && v.range[0] === x.t0 && v.range[1] === x.t1, v.extraPicks.size, WaveLens.internal.peek(v).vis.some(r => r === v.buses.st.get(p.key).g)]; })()""")
    c = page.locator('.wv canvas').first; c.focus(); page.evaluate("document.querySelector('.wv').waveView.cursor = 0")
    page.keyboard.press(']'); page.keyboard.press('t'); t1 = page.evaluate("document.querySelector('.wv').waveView.cursor")
    check(sel[:2] == [True, True] and sel[2] >= 8 and sel[3] and t1 == 20000, f'a transaction selected: the cursor at its start, its range measured, its signals highlighted; ]t: the first one {sel} {t1}')
    svg = page.evaluate("WaveLens.WaveSVG.toString(WAVES[Object.keys(WAVES)[0]])")
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
# hook (window.WAVELENS_CONFIG, as a page's wavelens.config.js would): every page of these contexts gets svaOpen: true
SVA_OPEN = """(() => { let c = { svaOpen: true }; Object.defineProperty(window, 'WAVELENS_CONFIG', { configurable: true,
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
    miss = page.evaluate("""[...document.querySelector('.wv').querySelectorAll('button, input:not([type=file]), select, .mk')].filter(e => !WaveLens.tips.of(e)).map(e => e.outerHTML.slice(0, 80))""")
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
    'units': 'the pure functions of the viewer (WaveLens.internal), the VCD reader, the bus decoders, sva.js expressions: a table of cases',
    'readers': 'the page\'s VCD reader against the tools\' on every fixture of tests/unit/vcd (one rule, the same transitions)',
    'lazy_dump': 'a large dump read as it is needed (the VS Code tab): every module at once, the signals shown read, the same rows as the whole text',
    'pageshot': 'tools/pageshot.py: a PNG per view and theme of a page in a headless Chromium, the manifest, a view by key, a view not there',
    'markup': 'markup on the waves: a bookmark lifted under its signal, its label by the circle, {dt} / {cycles} in arrow labels, spans; the SVG the same',
    'bookmark_view': 'going to a bookmark: the rows scrolled as when it was made, its time bookmarkLeft from the left (1–9, ]m, Markers…, the command)',
    'vscode': 'the VS Code extension\'s tab (host.js, its CSP) with a fake VS Code: the dump, the store, save, pick, clipboard, reload, live',
    'docs': 'docs/index.html: cursor, zoom, sorting, settings, styles, highlight, cursor fields, themes, bookmarks',
    'sva_docs': 'docs/index.html: the assertions section and the unit checks of wavelens/sva.js',
    'conformance': 'tests/conformance.html against stock WaveDrom: lanes and texts per case',
    'hierarchy': 'the synthetic page (and work/test_stream_video.html): scopes as groups, highlight, Collapse / Expand, "same"',
    'find': 'the synthetic page (and work/test_stream_video.html): fuzzy find, Open, Paint, Copy, Esc, n / N',
    'deep': 'the synthetic page (and work/test_stream_video.html): every level on the page, virtualised canvas',
    'modules': 'the synthetic page: the Modules panel (t), a click goes to a module, a box keeps Only those, the keys, the twin; 10 000 modules',
    'bar_tools': 'the synthetic page: the right button on the bar, its tool groups shown or left out (Show all, Hide all)',
    'fst': 'BUILD/demo_fst.html (make demo-fst): FSM state names and hierarchy from the FST',
    'examples': 'the example pages (make examples): bookmarks, arrows, colours, state names, their assertions',
    'big': 'every built page: redraw time, Sort',
    'wavelens': 'wavelens.js is the concatenation of wavelens/src/*.js; the pure functions (parse, fuzzy, decode, sortRows, fmtTime, parseT)',
    'api_docs': 'docs/index.html § API made from the exports of WaveLens, the viewer methods, every default setting',
    'plugin_api': 'the plugin API: tokens, tools, panels, rows, marks, listeners, keys, events, plugin groups, enums by path; sva.js on it only',
    'viewer': 'stage 9.4: keys, wheel, exact cursor, buttons, value tip, storage keys, data-theme, long values, find, destroy, keyboard, click time, Esc folding, print',
    'spike': 'BUILD/sva/spike.html (make sva-spike): the WebAssembly engine in a page',
    'sva_bind': 'apb_all.html: Load file…, Bind…, drag and drop, reload, a config through mkhtml.py',
    'sva_hardening': 'stage 6.1 on the example pages',
    'sva_waves': 'stage 7: the assertion groups on the waves',
    'sva_exprs': 'stage 10: expressions in the bar (search, rows ƒ, kept, JSON), names in a hierarchy',
    'dump': 'a VCD opened in the page (Open…, dropped on a viewer), ⟳, wavelens/viewer.html',
    'log': 'the log under the viewer: what was done, an error of a JSON file with its line, column and caret',
    'int_enums': 'a Questa VCD\'s enum as integer 32: labelled by the types, a value no code of it and only x said',
    'fsm': 'the FSM panel (T) on the FSM example\'s VCD with its types: the tree, go to one, Only FSMs, add them to a masked view, the command, the state',
    'axis': 'the time axis never leaves while the rows scroll: the own box fits under the bar, the wheel brings the bar back, with the page to the last rows',
    'state': 'Save / Load… of a viewer (the APB and AXI-Lite pages): its state to a file and back, on other waves',
    'edit': 'the viewer\'s commands, a page\'s edits (tools/viewedit.py) with the same state, your groups and markers, a page live through wavemcp.py',
    'view_review': 'the review of 0.15: Clear keeps markers, cycleZero a time, a run lays out before a picture, undo after a lost release, rows of '
                   'hidden modules, states clear, matched by name, ±inf, inherited names, ids and ranges; compare and analog at scale',
    'compare': 'a second dump compared: ≠ on the names that differ, struck when it lacks them, red bands, ]d [d, in the picture; clock-sampled refused',
    'savepage': 'Save page: the page with your view in its edits opens elsewhere as you left it; its waves as they were; the live token left out',
    'order': 'your groups\' rows in another order: alt+↑ / alt+↓ (shift: the group), a drag in the names, group move; one step each',
    'undo': 'ctrl+Z / ctrl+shift+Z and ↶ ↷: the edits undone and redone a step at a time (a batch of commands, a menu action), not the cursor',
    'cycles': 'the clock cycles under the time axis: numbers, the cursor\'s cycle, c147, cycle 0, Δ, the menu, the pictures, kept',
    'bits': 'a bus\'s width after its name and the bus bit by bit: a click on [7:0], b, the menu, the command, kept, a bookmark on a bit, the pictures',
    'ranges': 'a range on the waves (shift+drag, the right button) and its menu: zoom, bookmarks, the picture, a colour',
    'tips': 'every control has a tooltip with its keys; ? shows the keys and the mouse',
    'buses': 'stage 11: bus transactions (AXI4, AXI4-Stream, APB, AHB, Avalon-MM / ST, Wishbone, OBI) on a dump of every protocol and the examples',
    'sva_report': 'stage 8: the report against sva eval',
    'sva_edit': 'an assertion edited in the page (✎, Apply, kept, Revert, a bad text) and read from the disk again (⟳, Watch)',
    'sva_report_hardening': 'stage 8.1: names, aliases, recovery, caps, print, mkconfig --update, make html SVA=',
    'sva_wasm': 'wavelens/sva.wasm.js is the module of the current build (make sva-build)',
    'sva_third_party': 'tests/sva/third_party over the example dumps (sva eval)',
    'sva_eval': 'sva eval over the example dumps: only the deliberate failures fail',
}


VERSION = re.search(r"version: '([^']+)'", (ROOT / 'wavelens' / 'src' / 'boot.js').read_text()).group(1)


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
    synth = synth_page(build) if any(want(x) for x in ('pages', 'hierarchy', 'find', 'deep', 'big', 'viewer', 'modules', 'bar_tools')) else None
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
            own = (['docs', 'sva_docs', 'viewer', 'wavelens', 'plugin_api', 'api_docs', 'markup'] if path == PAGES[0] else ['conformance'] if path == PAGES[1] else
                   ['hierarchy', 'find', 'deep', 'viewer'] + (['modules', 'bar_tools'] if path == synth else []) if path == synth or tsv else ['fst'] if path.name == 'demo_fst.html' else
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
                    check(page.locator('.wvf-err').count() == 0, 'no wavelens error boxes')
                    n = page.locator('.wv canvas').count()
                    blank = page.evaluate('''() => [...document.querySelectorAll('.wv canvas')].filter(c => c.width === 0 || c.height === 0).length''')
                    check(n > 0 and blank == 0, f'{n} viewers, all canvases drawn')
                    if path not in BUILT:
                        check(page.locator('.wvs svg').count() > 0, f'{page.locator(".wvs svg").count()} static SVGs')
                stale = path in user and page.evaluate('window.WaveLens && WaveLens.version') != VERSION
                if stale:   # the user's page, built with another wavelens.js: the general checks only
                    print(f'  note: {path.name} was built with wavelens {page.evaluate("window.WaveLens && WaveLens.version")}, this is {VERSION}: rebuild it (make html WAVES=…) for the rest')
                if scheme == 'light' and not stale:
                    if path == PAGES[0]:
                        for fn in (interact, sorting, settings, styles, highlight, cursor, themes, bookmarks):
                            run('docs', fn, page)
                        run('sva_docs', sva_docs, page)
                        run('sva_docs', sva_units, page)
                        run('viewer', viewer, page)
                        run('wavelens', wavelens_units, page)
                        run('viewer', viewer_fixes, page)
                        run('plugin_api', plugin_api, page)
                        run('api_docs', api_docs, page)
                        run('markup', markup, page)
                    if path == PAGES[1]:
                        run('conformance', conformance, page)
                    if path == synth or tsv:
                        P = TSV if tsv else SYNTH
                        run('hierarchy', hierarchy, page, P)
                        run('find', find, page, P)
                        run('deep', deep, page, P)
                        if path == synth:
                            run('viewer', viewer_big, page, P)
                            run('modules', modules, page, P)
                            run('bar_tools', bar_tools, page, P)
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
        run('bits', bits, b, build)
        run('undo', undo, b, build)
        run('order', order, b, build)
        run('savepage', savepage, b, build)
        run('compare', compare, b, build)
        run('view_review', view_review, b, build)
        run('dump', dump, b, build)
        run('log', log_panel, b, build)
        run('int_enums', int_enums, b, build)
        run('fsm', fsm_panel, b, build)
        run('axis', axis_in_sight, b, build)
        run('bookmark_view', bookmark_view, b, build)
        run('pageshot', pageshot, b, build)
        run('lazy_dump', lazy_dump, b, build)
        run('readers', readers, b, build)
        run('vscode', vscode_tab, b, build)
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
