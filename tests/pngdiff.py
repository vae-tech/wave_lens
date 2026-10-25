#!/usr/bin/env python3
"""pngdiff.py — pictures compared pixel by pixel (review VI T13: shots-check fails on a picture that changed, not only
says so), standard library only: the PNGs playwright writes (8-bit RGB / RGBA, not interlaced) read with zlib.

A pixel differs when one of its channels moves by more than --tol (default 32 of 255: anti-aliasing of another
machine's fonts stays under it) from the pixel there and from the 8 around it (text placed a pixel off is the same); a picture differs when more than --max pixels do (default 48: fewer than a changed
letter; a share of the picture would let a word through in a big one) or its size is another. For each one that
differs a picture of the difference (the new one faded, the pixels that moved in red) goes to --diff. A picture made
(in GOT) that is not in WANT fails too: a shot added and not committed.

  python3 -I tests/pngdiff.py WANT_DIR GOT_DIR [--diff DIR] [--tol 32] [--max 48]   exit 1: a picture differs, is missing or new
"""
import argparse, os, struct, sys, zlib


def read(path):
    """A PNG -> (width, height, rows: [bytes of RGB per row])."""
    with open(path, 'rb') as f:
        data = f.read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError(f'{path}: not a PNG')
    pos, idat, head = 8, [], None
    while pos < len(data):
        n, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        if kind == b'IHDR':
            head = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
    w, h, depth, color, _, _, lace = head
    if depth != 8 or color not in (2, 6) or lace:
        raise ValueError(f'{path}: a PNG of 8-bit RGB or RGBA, not interlaced, is what it reads (depth {depth}, colour {color})')
    bpp = 3 if color == 2 else 4
    raw, stride, rows, prev = zlib.decompress(b''.join(idat)), w * bpp, [], bytearray(w * bpp)
    for y in range(h):
        ft, line = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):   # the filters of PNG: none, sub, up, average, Paeth
            a = line[i - bpp] if i >= bpp else 0
            b, c = prev[i], prev[i - bpp] if i >= bpp else 0
            if ft == 1:
                line[i] = (line[i] + a) & 255
            elif ft == 2:
                line[i] = (line[i] + b) & 255
            elif ft == 3:
                line[i] = (line[i] + (a + b) // 2) & 255
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        rows.append(bytes(line) if bpp == 3 else bytes(x for j in range(0, stride, 4) for x in line[j:j + 3]))
    return w, h, rows


def write(path, w, h, rows):
    """RGB rows -> a PNG."""
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    raw = b''.join(b'\x00' + r for r in rows)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 6)) +
                chunk(b'IEND', b''))


def compare(want, got, tol=32, diff=None):
    """-> (pixels that differ, all pixels, None or why they cannot be compared); diff: the picture of the difference."""
    (w1, h1, a), (w2, h2, b) = read(want), read(got)
    if (w1, h1) != (w2, h2):
        return w2 * h2, w2 * h2, f'{w1}x{h1} -> {w2}x{h2}'
    n, out = 0, []
    near = lambda r, i, q: max(abs(r[i] - q[0]), abs(r[i + 1] - q[1]), abs(r[i + 2] - q[2])) <= tol
    for y, (ra, rb) in enumerate(zip(a, b)):
        if ra == rb:
            if diff:
                out.append(bytes(200 + x // 5 for x in rb))
            continue
        line = bytearray()
        for i in range(0, len(rb), 3):
            q = rb[i:i + 3]
            # a pixel moved when the old picture has none like it there or one pixel around (a glyph a pixel up or down,
            # as Chromium places the text of a <select> now and then, is the same picture; a changed word is not)
            moved = not near(ra, i, q) and not any(near(a[yy], ii, q) for yy in (y - 1, y, y + 1) if 0 <= yy < h1
                                                    for ii in (i - 3, i, i + 3) if 0 <= ii < len(ra))
            n += moved
            line += b'\xff\x00\x00' if moved else bytes(200 + x // 5 for x in rb[i:i + 3])
        out.append(bytes(line))
    if diff and n:
        write(diff, w2, h2, out)
    return n, w2 * h2, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('want', help='the committed pictures (docs/img, tests/visual)')
    ap.add_argument('got', help='the ones made now')
    ap.add_argument('--diff', help='the pictures of the differences (default: GOT/diff)')
    ap.add_argument('--tol', type=int, default=32)
    ap.add_argument('--max', type=int, default=48, help='the pixels that may differ in a picture (default: %(default)s)')
    a = ap.parse_args()
    dd = a.diff or os.path.join(a.got, 'diff')
    names = sorted(f for f in os.listdir(a.want) if f.endswith('.png'))
    bad, near = [], []
    for f in names:
        g = os.path.join(a.got, f)
        if not os.path.exists(g):
            bad.append(f'{f}: not made'); continue
        with open(os.path.join(a.want, f), 'rb') as x, open(g, 'rb') as y:
            if x.read() == y.read():
                continue
        os.makedirs(dd, exist_ok=True)
        n, total, why = compare(os.path.join(a.want, f), g, a.tol, os.path.join(dd, f))
        if why or n > a.max:
            bad.append(f'{f}: {why or f"{n} of {total} pixels ({100 * n / total:.2f} %)"}')
        else:
            near.append(f'{f} ({n} px)')
    new = sorted(set(f for f in os.listdir(a.got) if f.endswith('.png')) - set(names))
    bad += [f'{f}: made, not in {a.want} (a new shot: make shots, then commit it)' for f in new]
    if near:
        print(f'pngdiff: {a.want}: within the tolerance: {", ".join(near)}')
    if bad:
        print(f'pngdiff: {a.want}: {len(bad)} of {len(names)} pictures differ (the differences in {dd}; meant: make shots, then commit them):\n  ' +
              '\n  '.join(bad))
        sys.exit(1)
    print(f'pngdiff: {a.want}: the {len(names)} pictures are current')


if __name__ == '__main__':
    main()
