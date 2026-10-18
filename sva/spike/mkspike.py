#!/usr/bin/env python3
"""mkspike.py — the spike page: spike.html with wavefw/sva.js and sva_wasm.wasm (base64) inlined (opens from file://).

  mkspike.py WASM OUT.html
"""
import base64, os, sys

wasm, out = sys.argv[1:3]
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spike.html'), encoding='utf-8') as f:
    page = f.read()
here = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(here, '..', '..', 'wavefw', 'sva.js'), encoding='utf-8') as f:
    page = page.replace('/*SVA_JS*/', f.read())
with open(wasm, 'rb') as f:
    b64 = base64.b64encode(f.read()).decode()
with open(out, 'w', encoding='utf-8') as f:
    f.write(page.replace('/*WASM_BASE64*/', b64))
print(f'mkspike: {os.path.getsize(wasm)} B wasm, {len(b64)} B base64 -> {out}', file=sys.stderr)
