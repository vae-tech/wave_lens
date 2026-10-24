"""wavejson.py — readable WaveJSON text, shared by vcd2wavedrom.py, embed.py and mkhtml.py.

Line breaks: one top-level key per line, one signal per line, a group opens a block with one member per line, and long
"tv" transition lists are wrapped (`wrap` [t, v] pairs per line), so generated files stay readable and diff well.
"""
import json


def ints(o):  # 25000.0 -> 25000 so times stay readable
    if isinstance(o, float) and o.is_integer():
        return int(o)
    if isinstance(o, (list, tuple)):   # (a tuple: a transition of the reader's)
        return [ints(x) for x in o]
    if isinstance(o, dict):
        return {k: ints(v) for k, v in o.items()}
    return o


def _j(v):
    return json.dumps(v, ensure_ascii=False, separators=(', ', ': '))


SAFE = frozenset('0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ\'_.+- ')


def _pair(p):
    """A [t, v] transition as _j(ints(p)) writes it, without json for the usual ones (a whole time, a value of plain characters;
    the reader's times are floats of ps: 5000.0 as ints() writes it)."""
    t, v = p
    if type(t) is float and t.is_integer():
        t = int(t)
    if type(t) is int and type(v) is str and SAFE.issuperset(v):
        return f'[{t}, "{v}"]'
    return _j(ints(list(p)))


def _sig(s, ind, wrap):
    if isinstance(s, list):   # group: ["name", member, …]
        if not any(isinstance(m, (dict, list)) for m in s):
            return _j(ints(s))
        named = isinstance(s[0], str) if s else False
        rows = ',\n'.join(ind + '  ' + _sig(m, ind + '  ', wrap) for m in s[1 if named else 0:])
        return '[' + (_j(s[0]) + ',' if named else '') + '\n' + rows + '\n' + ind + ']'
    tv = s.get('tv') if isinstance(s, dict) else None
    if not tv or len(tv) <= wrap:
        return _j(ints(s))
    head = _j(ints({k: v for k, v in s.items() if k != 'tv'}))
    lines = [', '.join(map(_pair, tv[i:i + wrap])) for i in range(0, len(tv), wrap)]
    return head[:-1] + (', ' if len(head) > 2 else '') + '"tv": [\n' + ',\n'.join(ind + '    ' + x for x in lines) + '\n' + ind + '  ]}'


def count(signal):
    """Signals in a WaveJSON "signal" array, nested groups included."""
    return sum(count(s[1:] if s and isinstance(s[0], str) else s) if isinstance(s, list) else
               1 if isinstance(s, dict) and ('wave' in s or 'tv' in s or 'same' in s) else 0 for s in signal)


def dumps(doc, indent='', wrap=16):
    """WaveJSON doc -> text (no trailing newline). `indent` prefixes every line after the first."""
    parts = []   # (ints of the signals as they are written: no copy of a big dump's transitions)
    for k, v in doc.items():
        if k == 'signal':
            rows = ',\n'.join(indent + '  ' + _sig(s, indent + '  ', wrap) for s in v)
            parts.append(f'"signal": [\n{rows}\n{indent} ]')
        else:
            parts.append(json.dumps(k) + ': ' + _j(ints(v)))
    return '{\n' + indent + ' ' + (',\n' + indent + ' ').join(parts) + '\n' + indent + '}'


def dumps_many(docs, wrap=16):
    """{key: doc} -> text with one key per line (the embed.py data.js format)."""
    return '{\n' + ',\n'.join(f'{json.dumps(k)}: {dumps(d, " ", wrap)}' for k, d in docs.items()) + '\n}'
