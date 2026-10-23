#!/usr/bin/env python3
"""mkspike.py — the spike page: spike.html with wavelens/sva.js and sva_wasm.wasm (base64) inlined (opens from file://).

  mkspike.py WASM OUT.html
"""
import argparse, base64, os, sys

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('wasm', help='sva_wasm.wasm (make sva-build)')
ap.add_argument('out', help='the page to write')
a = ap.parse_args()
wasm, out = a.wasm, a.out
if not os.path.isfile(wasm):
    ap.error(f'no such file: {wasm} (make sva-build)')
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spike.html'), encoding='utf-8') as f:
    page = f.read()
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, '..', '..', 'wavelens', 'sva.js'), encoding='utf-8') as f:
    page = page.replace('/*SVA_JS*/', f.read())
with open(wasm, 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
with open(out, 'w', encoding='utf-8') as f:
    f.write(page.replace('/*WASM_BASE64*/', b64))
print(f'mkspike: {os.path.getsize(wasm)} B wasm, {len(b64)} B base64 -> {out}', file=sys.stderr)
