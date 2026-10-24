"""tools/svtypes.py: Questa's describe and Verilator's --json-only as the types of a dump's signals, by their paths."""
import json, os, shutil, subprocess, unittest

from tests.unit import helpers as H
import svtypes as S
from common import WaveError

T = os.path.join(H.ROOT, 'tests', 'unit', 'types')
CORPUS = ['+incdir+' + T, os.path.join(T, 'types_pkg.sv'), os.path.join(T, 'types_tb.sv')]
VERILATOR = shutil.which('verilator')
# a node for vscode/svtypes.js (the extension's twin of svtypes.py verilator): WAVELENS_NODE, node, or VS Code's in WSL
NODE = os.environ.get('WAVELENS_NODE') or shutil.which('node') or next(iter(sorted(__import__('glob').glob(
    os.path.expanduser('~/.vscode-server/bin/*/node')))), None)


def readj(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def want():
    return readj(os.path.join(T, 'types.expected.json'))


class Describe(unittest.TestCase):
    def test_cases(self):
        # tests/unit/types/describe.json: the forms of describe seen in Questa 2021.1 (the page reads the same file: smoke
        # readers): ascending ranges, a table wrapped onto more lines, an array of enums, a union in a struct, what it refuses
        for c in readj(os.path.join(T, 'describe.json'))['cases']:
            sigs, notes = S.from_describe({'x': c['describe']})
            self.assertEqual((sigs.get('x'), notes[0][3:] if notes else None), (c['entry'], c['note']), c['describe'])

    def test_questa_corpus(self):
        # Questa's describe of the corpus (tools/questa/wavelens_types.tcl, committed): every path its own table, the
        # parameterised leaf four different ones, the plain `state` of u_plain nothing, the union a note
        t = S.load(os.path.join(T, 'questa.types.json'))
        w = want()
        self.assertEqual(t['signals'], w['signals'])
        self.assertEqual(t['notes'], w['notes'])
        self.assertNotIn('types_tb.u_plain.state', t['signals'])

    def test_not_a_types_file(self):
        with self.assertRaisesRegex(WaveError, 'not a WaveLens types file'):
            S.read({'signals': {}})


class Apply(unittest.TestCase):
    def test_paths_widths_top_and_elements(self):
        t = {'signals': {'tb.u.state': {'width': 2, 'enum': {'0': 'A', '3': 'B'}}, 'tb.arr': {'width': 2, 'enum': {'1': 'X'}},
                         'tb.s': {'width': 4, 'fields': [{'name': 'a', 'msb': 3, 'lsb': 2}, {'name': 'b', 'msb': 1, 'lsb': 0}]}}}
        sig = lambda *pw: [{'path': p, 'width': w, 'enum': {}, 'fields': None} for p, w in pw]
        sigs = sig(('tb.u.state', 2), ('tb.v.state', 2), ('other.tb.u.state', 2), ('tb.arr[3]', 2), ('tb.s', 5))
        ne, nf, notes, given = S.apply(t, sigs)
        got = {s['path']: s['enum'] for s in sigs}
        self.assertEqual(got['tb.u.state'], {0: 'A', 3: 'B'})
        self.assertEqual(got['tb.v.state'], {})   # the same name in another instance: not its type
        self.assertEqual(got['other.tb.u.state'], {})   # another root of the dump with a tb below: not the types' tb
        self.assertEqual(got['tb.arr[3]'], {1: 'X'})   # an element of an unpacked array
        self.assertEqual((ne, nf), (2, 0))
        self.assertEqual(notes, ['tb.s: 5 bits in the dump, 4 in the types: left as it is'])
        self.assertEqual(given, {'tb.u.state', 'tb.arr[3]'})
        sigs = sig(('TOP.tb.u.state', 2), ('TOP.clk', 1), ('TOP.x.tb.u.state', 2))   # Verilator's FST: a TOP above the design
        S.apply(t, sigs)
        self.assertEqual([s['enum'] for s in sigs], [{0: 'A', 3: 'B'}, {}, {}])

    def test_check_the_questa_dump(self):
        rc, out, err = H.run_tool('svtypes', 'check', os.path.join(T, 'questa.types.json'), os.path.join(T, 'questa.vcd'))
        self.assertEqual(rc, 0, err)
        self.assertIn('8 get enum labels, 1 get fields; 0 width differs, 0 typed paths not in the dump', out)

    def test_mkconfig_takes_the_types_beside_the_dump(self):
        # tb.vcd -> tb.types.json by itself; the types win over --sv (which would guess by name), and --update replaces
        # the tables they gave before while an "enum" of the user's on another signal stays
        with H.tmp() as d:
            for n in ('questa.vcd', 'questa.types.json'):
                shutil.copy(os.path.join(T, n), d)
            dump, out = os.path.join(d, 'questa.vcd'), os.path.join(d, 'c.json')
            rc, _, err = H.run_tool('mkconfig', dump, '--out', out, '--sv', os.path.join(T, 'types_pkg.sv'))
            self.assertEqual(rc, 0, err)
            self.assertIn('--types: questa.types.json', err)
            self.assertIn('--sv is not used', err)
            sig = readj(out)['signals']
            self.assertEqual(sig['types_tb.u_l3.state']['enum'], {'0': 'L_IDLE', '1': 'L_RUN', '7': 'L_LAST'})
            self.assertEqual(sig['types_tb.gen[1].u_l.state']['enum']['31'], 'L_LAST')
            self.assertNotIn('enum', sig['types_tb.u_plain.state'])
            self.assertEqual([f['name'] for f in sig['types_tb.o']['fields']], ['oh', 'in.st', 'in.code', 'pair', 'flag'])
            self.assertIn('types_tb.o', readj(out)['typed'])
            # --update: what the types gave and nobody edited follows the file (a struct that became an enum: no fields
            # left; a type gone: its labels gone); an edited table and the user's own stay
            cfg = readj(out)
            cfg['signals']['types_tb.state']['enum'] = {'0': 'MY_IDLE'}   # edited: stays
            cfg['signals']['types_tb.u_plain.state']['enum'] = {'1': 'MINE'}   # the user's own: stays
            with open(out, 'w') as f:
                json.dump(cfg, f)
            ty = readj(os.path.join(d, 'questa.types.json'))
            ty['describe']['types_tb.o'] = ty['describe']['types_tb.al'].replace('(2 downto 0)', '(20 downto 0)')   # a struct -> an enum
            del ty['describe']['types_tb.u_l2.state']   # no type any more
            ty['describe']['types_tb.u_plain.state'] = 'Verilog enum: (1 downto 0) [2 enumeration values]\n  (P0=0,P1=1)'
            with open(os.path.join(d, 'questa.types.json'), 'w') as f:
                json.dump(ty, f)
            rc, _, err = H.run_tool('mkconfig', dump, '--out', out, '--update')
            self.assertEqual(rc, 0, err)
            cfg = readj(out)
            sig = cfg['signals']
            self.assertEqual(sig['types_tb.state']['enum'], {'0': 'MY_IDLE'})
            self.assertEqual(sig['types_tb.u_plain.state']['enum'], {'1': 'MINE'})
            self.assertIn('keep the "enum" / "fields" written here', err)
            self.assertEqual(sig['types_tb.o']['enum']['4'], 'ERROR')
            self.assertNotIn('fields', sig['types_tb.o'])
            self.assertNotIn('enum', sig['types_tb.u_l2.state'])
            self.assertNotIn('types_tb.state', cfg['typed'])
            self.assertNotIn('types_tb.u_plain.state', cfg['typed'])
            self.assertIn('types_tb.o', cfg['typed'])

    def test_update_through_a_life(self):
        # review VI T6: one signal's type over five runs of mkconfig --update: an enum, a struct, a plain vector, gone,
        # an enum again, then edited by the user (and stays though the file changes); a table of the user's on another
        # signal stays all the way, and "typed" names what the types gave
        F = [{'name': 'hi', 'msb': 3, 'lsb': 2}, {'name': 'lo', 'msb': 1, 'lsb': 0}]
        steps = [({'width': 4, 'enum': {'0': 'A0'}}, {'enum': {'0': 'A0'}}), ({'width': 4, 'fields': F}, {'fields': F}), ({'width': 4}, {}),
                 (None, {}), ({'width': 4, 'enum': {'1': 'B1'}}, {'enum': {'1': 'B1'}})]
        head = '$timescale 1ns $end\n$scope module tb $end\n$var wire 4 ! a [3:0] $end\n$var wire 4 " b [3:0] $end\n$upscope $end\n$enddefinitions $end\n'
        with H.tmp() as d:
            dump, out, ty = H.vcd(d, '#0\nb0 !\nb0 "\n#5\nb1 !\n', head, 'tb.vcd'), os.path.join(d, 'c.json'), os.path.join(d, 'tb.types.json')
            for i, (entry, want) in enumerate(steps):
                with open(ty, 'w') as f:
                    json.dump({'wavelens': 'types', 'signals': {'tb.a': entry} if entry else {}}, f)
                rc, _, err = H.run_tool('mkconfig', dump, '--out', out, *(['--update'] if i else []))
                self.assertEqual(rc, 0, err)
                cfg = readj(out)
                if not i:
                    cfg['signals']['tb.b']['enum'] = {'0': 'MINE'}
                    with open(out, 'w') as f:
                        json.dump(cfg, f)
                a = cfg['signals']['tb.a']
                with self.subTest(i):
                    self.assertEqual({k: a[k] for k in ('enum', 'fields') if k in a}, want)
                    self.assertEqual(cfg['signals']['tb.b'].get('enum'), {'0': 'MINE'})
                    self.assertEqual('tb.a' in cfg.get('typed', {}), bool(want))
            cfg['signals']['tb.a']['enum'] = {'1': 'EDITED'}   # the user's edit of what the types gave: it stays
            with open(out, 'w') as f:
                json.dump(cfg, f)
            with open(ty, 'w') as f:
                json.dump({'wavelens': 'types', 'signals': {'tb.a': {'width': 4, 'enum': {'2': 'C2'}}}}, f)
            rc, _, err = H.run_tool('mkconfig', dump, '--out', out, '--update')
            self.assertEqual(rc, 0, err)
            self.assertEqual(readj(out)['signals']['tb.a']['enum'], {'1': 'EDITED'})

    def test_map_and_fingerprint(self):
        # review V X4 / X5: the dump's scopes as the types name them ("map", --map: the longest prefix); the run's
        # fingerprint: written more than a day apart, an instance of the types under a module the dump has but not in it
        t = {'signals': {'tb.u.state': {'width': 2, 'enum': {'1': 'A'}}}, 'map': {'top': 'tb', 'top.wrap': 'tb'}, 'producer': {'date': '2026-10-01T10:00:00'},
             'instances': {'tb.u': 'm', 'tb.gone': 'm', 'other.x': 'm'}}
        self.assertEqual([S.remap(p, t['map']) for p in ('top.u.state', 'top.wrap.u.state', 'topx.u', 'top')], ['tb.u.state', 'tb.u.state', 'topx.u', 'tb'])
        sigs = [{'path': 'top.wrap.u.state', 'width': 2, 'enum': {}, 'fields': None}]
        self.assertEqual(S.apply(t, sigs)[0], 1)
        self.assertEqual(S.map_arg(['a.b=c']), {'a.b': 'c'})
        with self.assertRaisesRegex(WaveError, 'DUMP=TYPES'):
            S.map_arg(['nope'])
        run = S.fingerprint(t, 'Sat Oct 24 13:30:00 2026', {'top', 'top.u'})
        self.assertEqual(len(run), 2)
        self.assertIn('23 days before the dump', run[0])
        self.assertIn('tb.gone', run[1])
        self.assertNotIn('other.x', run[1])   # its module is not the dump's: a part of the design the dump has none of
        # review VI A3: a "map" that is not an object of texts is an error (the page's svTypes too), none or null no map
        for bad in (['tb=dut'], 'tb', [], {'tb': 1}):
            with self.assertRaisesRegex(WaveError, '"map" is'):
                S.read({'wavelens': 'types', 'map': bad})
        self.assertEqual([S.read({'wavelens': 'types', 'map': m})['map'] for m in (None, {})], [{}, {}])
        self.assertEqual(S.fingerprint(dict(t, instances={}), 'Fri Oct 02 10:00:00 2026', set()), [])   # the same day
        with self.assertRaisesRegex(WaveError, '"map" is'):
            S.read({'wavelens': 'types', 'map': ['a']})

    def test_dump_date_and_modules(self):
        import dumpscan
        d = dumpscan.read(os.path.join(T, 'questa.vcd'), None)
        self.assertEqual(d.date, 'Sat Oct 24 13:30:00 2026')
        self.assertIn('types_tb.gen[1].u_l', d.modules)
        rc, out, err = H.run_tool('svtypes', 'check', os.path.join(T, 'questa.types.json'), os.path.join(T, 'questa.vcd'), '--map', 'x=y')
        self.assertEqual(rc, 0, err)
        self.assertNotIn('run:', out)   # the fixture's types and VCD: one run

    def test_mkconfig_types_map(self):
        with H.tmp() as d:
            ty = readj(os.path.join(T, 'questa.types.json'))
            ty['describe'] = {k.replace('types_tb.', 'tb.', 1): x for k, x in ty['describe'].items()}
            with open(os.path.join(d, 'renamed.types.json'), 'w') as f:
                json.dump(ty, f)
            out = os.path.join(d, 'c.json')
            rc, _, err = H.run_tool('mkconfig', os.path.join(T, 'questa.vcd'), '--out', out, '--types', os.path.join(d, 'renamed.types.json'),
                                    '--types-map', 'types_tb=tb')
            self.assertEqual(rc, 0, err)
            self.assertEqual(readj(out)['signals']['types_tb.state']['enum']['4'], 'ERROR')

    @H.needs(shutil.which('tclsh'), 'tclsh')
    def test_questa_paths(self):
        # tools/questa/wavelens_types.tcl: Questa's object paths as the dump's (a dataset of any name, escaped identifiers)
        tcl = os.path.join(H.ROOT, 'tools', 'questa', 'wavelens_types.tcl')
        cases = {'sim:/tb/gen[0]/u_l/state': 'tb.gen[0].u_l.state', 'old-run:/tb/state': 'tb.state', '/tb/x': 'tb.x',
                 'w.2:/tb/\\a-b /c': 'tb.a-b.c'}
        script = f'source {{{tcl}}}\n' + ''.join(f'puts [::wavelens::path {{{k}}}]\n' for k in cases)
        out = subprocess.run(['tclsh'], input=script, capture_output=True, text=True, check=True).stdout.split('\n')
        self.assertEqual(out[:len(cases)], list(cases.values()))

    def test_mkconfig_types_file_missing(self):
        rc, _, err = H.run_tool('mkconfig', os.path.join(T, 'questa.vcd'), '--out', os.devnull, '--force', '--types', 'nope.types.json')
        self.assertNotEqual(rc, 0)
        self.assertIn('nope.types.json', err)


@H.needs(VERILATOR, 'verilator (Verilator 5)')
class Verilator(unittest.TestCase):
    def test_corpus_as_questa(self):
        # the second elaborator of the same corpus: the same table for every path, the same note
        tree, _ = S.run_verilator(CORPUS, 'types_tb')
        sigs, notes = S.verilator_types(tree)
        self.assertEqual(sigs, want()['signals'])
        self.assertEqual(notes, want()['notes'])

    def test_fsm_as_its_fst(self):
        # the oracle of the FSM example: Verilator's own FST carries the enum tables of the same design
        fst = os.path.join(H.BUILD, 'examples', 'fsm', 'fsm.fst')
        if not os.path.exists(fst):
            H.skip(self, f'{fst}: make example EX=fsm')
        import dumpscan
        own = {p: v['enum'] for p, v in dumpscan.scan(fst).items() if v['enum'] and not p.endswith(']')}
        ex = os.path.join(H.ROOT, 'examples', 'fsm')
        tree, _ = S.run_verilator([os.path.join(ex, 'uart_pkg.sv'), os.path.join(ex, 'fsm_tb.sv')], 'fsm_tb')
        sigs, _ = S.verilator_types(tree)
        table = lambda e: {int(k): v for k, v in e.items()}
        self.assertEqual(table(sigs['fsm_tb.state']['enum']), own['fsm_tb.state'])
        self.assertEqual(table(sigs['fsm_tb.u_rx.state']['enum']), own['fsm_tb.u_rx.state'])
        st = [f for f in sigs['fsm_tb.status']['fields'] if f['name'] == 'state'][0]
        self.assertEqual((table(st['enum']), st['msb'], st['lsb']), (own['fsm_tb.status.state'], 15, 13))

    def test_packages_arrays_escaped(self):
        # review V A4, A6, C12: the names as the VCD has them (u-l.st-x, not u__02dl.st__02dx), an array of any
        # dimensions its element's type (two[1][2] by lookup), a package's variable under the package's name
        tree, _ = S.run_verilator([os.path.join(T, 'vl_extra.sv')], 'vl_extra')
        sigs, notes = S.verilator_types(tree)
        abc = {'width': 2, 'enum': {'0': 'A', '1': 'B', '2': 'C'}}
        self.assertEqual(sigs, {'vl_extra.two': abc, 'vl_extra.three': abc, 'vl_extra.u-l.st-x': abc, 'p.pstate': abc})
        self.assertEqual(S.lookup(sigs, 'vl_extra.three[1][0][1]'), abc)

    @H.needs(NODE, 'node (or VS Code\'s, ~/.vscode-server/bin/*/node)')
    def test_the_extensions_twin(self):
        # vscode/svtypes.js (the command Make the types with Verilator) gives what svtypes.py verilator gives: the corpus,
        # the FSM example, the Verilator-only cases
        ex = os.path.join(H.ROOT, 'examples', 'fsm')
        for top, args in (('types_tb', CORPUS), ('fsm_tb', [os.path.join(ex, 'uart_pkg.sv'), os.path.join(ex, 'fsm_tb.sv')]),
                          ('vl_extra', [os.path.join(T, 'vl_extra.sv')])):
            with H.tmp() as d:
                js, py = os.path.join(d, 'js.json'), os.path.join(d, 'py.json')
                r = subprocess.run([NODE, os.path.join(H.ROOT, 'vscode', 'svtypes.js'), '--top', top, '--out', js, '--', *args], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                rc, _, err = H.run_tool('svtypes', 'verilator', '--top', top, '--out', py, '--', *args)
                self.assertEqual(rc, 0, err)
                a, b = readj(js), readj(py)
                self.assertEqual((a['signals'], a['notes']), (b['signals'], b['notes']), top)
                self.assertEqual((a['producer']['top'], a['producer']['args']), (top, args))
        # review VI A5: the arguments typed in VS Code reach no shell: a file's * ? expanded from the workspace's folder
        # (the test: from tests/unit/types), the options as they are, a name that matches nothing an error
        r = subprocess.run([NODE, '-e', '''const s = require(process.argv[1]); const out = [s.expand(['-f', 'a.f', '+incdir+x*', 'vl_*.sv', './types_?kg.sv'], process.argv[2])];
            for (const a of ['nope_*.sv', 'x*/a.sv']) { try { s.expand([a], process.argv[2]); out.push('no error'); } catch (e) { out.push(e.message); } }
            console.log(JSON.stringify(out));''', os.path.join(H.ROOT, 'vscode', 'svtypes.js'), T], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got[0], ['-f', 'a.f', '+incdir+x*', 'vl_extra.sv', 'types_pkg.sv'])
        self.assertIn('no file of', got[1])
        self.assertIn('only in a file', got[2])

    def test_cli_writes_the_file(self):
        with H.tmp() as d:
            out = os.path.join(d, 'x.types.json')
            rc, _, err = H.run_tool('svtypes', 'verilator', '--top', 'types_tb', '--out', out, '--', *CORPUS)
            self.assertEqual(rc, 0, err)
            self.assertEqual(S.load(out)['signals'], want()['signals'])
            self.assertIn('8 enum and 1 struct signals', err)
            rc, _, err = H.run_tool('svtypes', 'verilator', '--top', 'nope', '--out', out, '--', *CORPUS)
            self.assertNotEqual(rc, 0)
            self.assertIn('verilator --json-only failed', err)



def contract_py(c):
    """A case of tests/unit/types/contract.json through svtypes.py -> what the contract says (the page's twin: smoke readers)."""
    try:
        t = S.read(json.loads(json.dumps(c['types'])))
    except WaveError:
        return {'error': True}
    sigs = [{'path': x['path'], 'width': x['width'], 'enum': dict(x.get('enum') or {}), 'fields': x.get('fields')} for x in c['signals']]
    own = {x['path'] for x in c['signals'] if x.get('enum')}, {x['path'] for x in c['signals'] if x.get('fields')}
    _, _, notes, given = S.apply(t, sigs)
    out = {'labels': {x['path']: {str(k): v for k, v in x['enum'].items()} for x in sigs if x['path'] in given and x['enum'] and x['path'] not in own[0]},
           'fields': {x['path']: x['fields'] for x in sigs if x['path'] in given and x['fields'] and x['path'] not in own[1]},
           'notes': notes, 'run': S.fingerprint(t, c.get('date'), c.get('modules', []))}
    return {k: v for k, v in out.items() if v}


class Contract(unittest.TestCase):
    # review VI T6: the cases both twins must give (the page's run of them: tests/smoke.py readers)
    def test_the_cases(self):
        with open(os.path.join(T, 'contract.json'), encoding='utf-8') as f:
            cases = json.load(f)['cases']
        self.assertGreater(len(cases), 15)
        for c in cases:
            with self.subTest(c['name']):
                self.assertEqual(contract_py(c), c['want'])


if __name__ == '__main__':
    unittest.main()
