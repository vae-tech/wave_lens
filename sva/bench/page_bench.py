#!/usr/bin/env python3
"""page_bench.py — the engine in a page over real "tv" transitions: wavefw/sva.js + the WebAssembly build (the spike page
of make sva-spike) in headless Chromium, evaluate(parsed, tvSampler) over WaveJSON from tools/vcd2wavedrom.py --exact.

  python3 tools/vcd2wavedrom.py --waves work/test_stream_video.vcd --exact --scope SCOPE --signals a,b,... --out tv.json
  python3 sva/bench/page_bench.py SPIKE.html tv.json checks.sva      (docs/sva/ENGINE.md, Performance)
"""
import json, pathlib, sys
from playwright.sync_api import sync_playwright

spike, tvfile, sva = sys.argv[1:4]
j = json.load(open(tvfile))
items = []
def walk(a):
    for it in a:
        if isinstance(it, list):
            walk(it)
        elif isinstance(it, dict) and it.get('name'):
            items.append(it)
walk(j['signal'])
by_path = {it['path']: it['tv'] for it in items if it.get('path') and it.get('tv')}
sigs = {it['name']: {'tv': it.get('tv') or by_path[it['same']], 'width': it.get('width', 1)} for it in items}
source = pathlib.Path(sva).read_text()
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.goto(pathlib.Path(spike).resolve().as_uri())
    page.wait_for_function('window.SPIKE')
    r = page.evaluate('''async ([source, sigs]) => {
        const bytes = Uint8Array.from(atob(WASM), c => c.charCodeAt(0)), sva = await SVA.load(bytes);
        const parsed = sva.parse(source), sampler = SVA.tvSampler(sigs), out = [];
        for (const a of parsed.assertions) {
            const t = performance.now(), res = sva.evaluate(parsed, sampler, { assert: [a.label] });
            const o = res.assertions[0];
            out.push({ name: a.label, ms: performance.now() - t, cycles: res.cycles.length, stats: o.stats, missing: o.missing });
        }
        const t = performance.now(), all = sva.evaluate(parsed, sampler);
        out.push({ name: 'all', ms: performance.now() - t, bytes: JSON.stringify(all).length });
        return out;
    }''', [source, sigs])
    for x in r:
        print(json.dumps(x))
    b.close()
