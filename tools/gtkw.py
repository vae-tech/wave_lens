#!/usr/bin/env python3
"""gtkw.py — a GTKWave save file (.gtkw, .sav) read: its dump, its traces in order with their radix and colour, its groups, the
time it starts at and its markers. mkconfig.py --gtkw makes a view of a config of it (signals, the window, groups, radix, analog
and markers in the view's "state"), so a project that lived in GTKWave opens the same rows in WaveLens.

    python3 -I tools/gtkw.py run.gtkw            # what it reads, as JSON

What it reads: [dumpfile] (the dump), [timestart] (the window's start), the "*" line (the primary marker and the named
ones A…Z) with [markername_A] text (their names), "@flags" before the traces (hex 0x2, dec 0x4, bin 0x8, oct 0x10, signed
0x400, ascii 0x800, analog 0x8000 / 0x10000, a group's begin 0x800000 and end 0x1000000, a blank row 0x200), "-text" rows
(a comment: a group's name when it begins one; groups nest), [color] N (GTKWave's colours 1…7), the traces' names, an alias
("+{name} path": the row's name), a bit of a bus ("tb.data[3]": the bus shown bit by bit). What it leaves (said in the notes):
the size and place of the window, the tree, the zoom (the window's end is not in the file), translate filters ("^1 file"),
vectors built of bits ("#{name} …"), the [sst_*] lines.
Times: GTKWave keeps a VCD's times in the dimension of its $timescale (a tick of "10 ns" is 10 ns: the number multiplies
the ticks), so a time of the file is in that dimension (ns), not in ticks; view_of turns it into ps (dim_ps).
"""
import json, re, sys

TR_HEX, TR_DEC, TR_BIN, TR_OCT, TR_BLANK, TR_SIGNED, TR_ASCII = 0x2, 0x4, 0x8, 0x10, 0x200, 0x400, 0x800
TR_ANALOG = 0x8000 | 0x10000
TR_GRP_BEGIN, TR_GRP_END, TR_COLLAPSED, TR_CLOSED = 0x800000, 0x1000000, 0x1000, 0x400000
# GTKWave's trace colours ([color] 1…7: red orange yellow green blue indigo violet)
COLORS = {1: '#e03131', 2: '#f08c00', 3: '#fab005', 4: '#2f9e44', 5: '#1971c2', 6: '#5f3dc4', 7: '#ae3ec9'}
SKIPPED = ('[size]', '[pos]', '[dumpfile_mtime]', '[dumpfile_size]', '[savefile]', '[treeopen]', '[sst_', '[signals_width]', '[sst_expanded]', '[sst_vpaned_height]', '[pattern_trace]', '[*]')


def radix_of(flags):
    """The radix of a trace's flags, as the viewer names them (None: its own)."""
    if flags & TR_ASCII:
        return 'ascii'
    if flags & TR_SIGNED and flags & TR_DEC:
        return 'signed'
    for bit, r in ((TR_BIN, 'bin'), (TR_OCT, 'oct'), (TR_DEC, 'dec'), (TR_HEX, 'hex')):
        if flags & bit:
            return r
    return None


def dim_ps(unit_ps):
    """The dimension of a $timescale in ps (its number left out: 10000 for "10 ns" -> 1000), GTKWave's unit of a save file's times."""
    if not unit_ps or unit_ps <= 0:
        return 1
    import math
    return 10 ** (3 * math.floor(math.log10(unit_ps) / 3 + 1e-9))


def trace_path(name):
    """A trace's name -> the signal's path: a vector's own range after it left out ("tb.data[7:0]" -> "tb.data"); a bit stays ("tb.data[3]")."""
    return re.sub(r'\[\d+:\d+\]$', '', name.strip())


def parse(text):
    """A save file's text -> {waves, from, markers: [{t, label}], signals: [{path, radix?, color?, analog?, group?}], groups: [{name, signals,
    closed}], notes} (times in the dump's units)."""
    out = {'waves': None, 'from': None, 'markers': [], 'signals': [], 'groups': [], 'notes': []}
    flags, color, stack, skipped, names = 0, None, [], set(), {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('[dumpfile]'):
            out['waves'] = line[len('[dumpfile]'):].strip().strip('"') or None
        elif line.startswith('[timestart]'):
            try:
                out['from'] = int(line.split()[1])
            except (IndexError, ValueError):
                out['notes'].append(f'[timestart]: not a time: {line}')
        elif line.startswith('[color]'):
            try:
                color = COLORS.get(int(line.split()[1]))
            except (IndexError, ValueError):
                color = None
        elif re.match(r'\[markername(_[A-Z])?\]', line):   # [markername_A] reset done: the name of a named marker
            m = re.match(r'\[markername_([A-Z])\]\s*(.*)', line)
            if m and m.group(2).strip():
                names[m.group(1)] = m.group(2).strip()
        elif line.startswith('['):
            skipped.add(line.split(']')[0] + ']')
        elif line.startswith('*'):   # *zoom primary-marker named-markers…
            parts = line[1:].split()
            times = []
            for k, x in enumerate(parts[1:]):
                try:
                    t = int(x)
                except ValueError:
                    continue
                if t >= 0:
                    times.append((t, 'marker' if k == 0 else chr(ord('A') + k - 1)))
            out['markers'] = [{'t': t, 'label': lab} for t, lab in times]
        elif line.startswith('@'):
            try:
                flags = int(line[1:], 16)
            except ValueError:
                out['notes'].append(f'flags not read: {line}')
                flags = 0
        elif line.startswith('-'):   # a comment row: a group's name when it begins one (groups nest: the innermost holds a trace)
            name = line[1:].strip()
            if flags & TR_GRP_BEGIN:
                group = {'name': name or f'group {len(out["groups"]) + 1}', 'signals': [], 'closed': bool(flags & (TR_CLOSED | TR_COLLAPSED))}
                if stack:
                    group['parent'] = stack[-1]['name']
                out['groups'].append(group)
                stack.append(group)
            elif flags & TR_GRP_END and stack:
                stack.pop()
            color = None
        elif line.startswith('^'):   # a translate filter of the trace that follows (a file or a process): not the viewer's
            out['notes'].append(f'translate filter left out: {line[:60]}')
        elif line.startswith('#'):   # a GTKWave comment or a vector built of bits ("#{name} a b c"): not a signal of the dump
            out['notes'].append(f'not read: {line[:60]}')
        else:
            if flags & TR_BLANK:
                continue
            alias = None
            m = re.match(r'\+\{([^}]*)\}\s*(\S.*)$', line)   # +{name} path: an alias, the row's name in GTKWave
            if m:
                alias, line = m.group(1).strip() or None, m.group(2)
            s = {'path': trace_path(line)}
            if alias:
                s['alias'] = alias
            b = re.match(r'(.+)\[(\d+)\]$', s['path'])
            if b:   # a bit of a bus: the bus, shown bit by bit
                s.update(path=b.group(1), bit=int(b.group(2)))
            r = radix_of(flags)
            if r:
                s['radix'] = r
            if flags & TR_ANALOG:
                s['analog'] = True
            if color:
                s['color'] = color
            if stack:
                s['group'] = stack[-1]['name']
                stack[-1]['signals'].append(s['path'])
            out['signals'].append(s)
            color = None
    for m in out['markers']:   # a named marker with its name: "A reset done"
        if m['label'] in names:
            m['label'] = f'{m["label"]} {names[m["label"]]}'
    for k in sorted(skipped):
        if not k.startswith(SKIPPED):
            out['notes'].append(f'{k} left out')
    if out['from'] is not None or out['markers']:
        out['notes'].append('the window\'s end is not in the file (its zoom only): the view ends where the dump does')
    return out


def view_of(g, unit_ps=1, known=None):
    """A parsed save file -> (a view of a config: signals, from, state {groups, radix, analog, paint, bits, markers}, the notes); known: the
    dump's paths (a trace that is not in it is left out, said); unit_ps: the dump's tick in ps (its times: dim_ps of it). The aliases go into
    the config's catalog (aliases_of)."""
    notes, sigs = list(g['notes']), []
    for s in g['signals']:
        if known is not None and s['path'] not in known:
            notes.append(f'{s["path"]}: not in the dump, left out')
            continue
        if s['path'] not in [x['path'] for x in sigs]:
            sigs.append(s)
    paths = [s['path'] for s in sigs]
    tick = dim_ps(unit_ps)   # GTKWave's times: in the dimension of the $timescale
    tick = int(tick) if float(tick).is_integer() else tick
    st = {}
    groups = [{'name': x['name'], 'signals': [p for p in x['signals'] if p in paths]} for x in g['groups']]
    groups = [x for x in groups if x['signals']]
    if groups:
        st['groups'] = groups
    for k, key in (('radix', 'radix'), ('color', 'paint')):
        m = {s['path']: s[k] for s in sigs if s.get(k)}
        if m:
            st[key] = m
    an = {s['path']: 3 for s in sigs if s.get('analog')}
    if an:
        st['analog'] = an
    bits = list(dict.fromkeys(s['path'] for s in g['signals'] if s.get('bit') is not None and s['path'] in paths))
    if bits:
        st['bits'] = bits
    if g['markers']:
        st['markers'] = [{'t': m['t'] * tick, 'label': m['label']} for m in g['markers']]
    view = {'signals': ','.join(paths), 'exact': True}
    if g['from']:
        view['from'] = f'{g["from"] * tick}ps'
    if st:
        view['state'] = st
    return view, notes


def aliases_of(g):
    """The aliases of the save file's traces -> {path: alias} (the catalog's "alias": the row's name)."""
    return {s['path']: s['alias'] for s in g['signals'] if s.get('alias')}


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] in ('-h', '--help'):
        print(__doc__)
        sys.exit(0 if len(sys.argv) == 2 else 2)
    with open(sys.argv[1], encoding='utf-8', errors='replace') as f:
        print(json.dumps(parse(f.read()), indent=1, ensure_ascii=False))
