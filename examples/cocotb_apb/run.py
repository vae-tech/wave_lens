#!/usr/bin/env python3
"""run.py — the example's regression on Verilator or Questa, and its page: one command, from anywhere.

  python3 run.py                        # Verilator: out/sim/ (the build, dump.vcd, results.xml), out/apb.marks.json, out/cocotb_apb.html
  python3 run.py --sim questa           # the same on Questa (vlog, vsim on PATH)
  python3 run.py --sim questa --out DIR --views tests --wavelens PATH/TO/WaveLens
  python3 run.py --no-marks             # plain cocotb: the test's calls do nothing but check (no page)
  python3 run.py --test test_wait_states   # one test

To take it to a design of your own, copy this file, the test and the config: HDL, TOP and MODULE below are all it knows of
this design. --wavelens (or WAVELENS_HOME) is a checkout of WaveLens, by default the one this example sits in. The exit
status is cocotb's: 0 when every test went as expected (the last one is expected to fail: it finds the slave's bug).
"""
import argparse, os, subprocess, sys

from cocotb_tools.check_results import get_results
from cocotb_tools.runner import get_runner

HERE = os.path.dirname(os.path.abspath(__file__))
HDL = [os.path.join(HERE, 'cocotb_apb_tb.sv')]
TOP, MODULE, CONFIG = 'cocotb_apb_tb', 'test_apb', os.path.join(HERE, 'cocotb_apb.config.json')
# what differs by simulator: the build's and the simulation's options. The dump is dump.vcd in both: Verilator traces by itself,
# Questa takes $dumpvars from the testbench
SIMS = {'verilator': {'build_args': ['-Wno-fatal'], 'build': {'timescale': ('1ns', '1ps'), 'waves': True}, 'test': {'waves': True}},
        'questa': {'build_args': [], 'build': {}, 'test': {'test_args': ['-voptargs=+acc']}}}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sim', choices=SIMS, default='verilator')
    ap.add_argument('--out', default='out', help='the directory of the run (default out)')
    ap.add_argument('--views', choices=('whole', 'tests', 'both'), default='both', help='mkhtml.py --marks-views (default both)')
    ap.add_argument('--wavelens', default=os.environ.get('WAVELENS_HOME') or os.path.dirname(os.path.dirname(HERE)),
                    help='a checkout of WaveLens (default WAVELENS_HOME, else the one this file is in)')
    ap.add_argument('--no-marks', action='store_true', help='WAVELENS_MARKS=off: plain cocotb, no marks, no page')
    ap.add_argument('--test', help='only this test')
    a = ap.parse_args()
    out, home, sim = os.path.abspath(a.out), os.path.abspath(a.wavelens), SIMS[a.sim]
    work = os.path.join(out, 'sim')   # the build and the run: vsim finds its library where it runs
    os.makedirs(out, exist_ok=True)
    marks = 'off' if a.no_marks else os.path.join(out, 'apb.marks.json')
    if os.path.exists(marks):
        os.remove(marks)   # (a page of this run, or none)
    runner = get_runner(a.sim)
    runner.build(sources=HDL, hdl_toplevel=TOP, build_dir=work, build_args=sim['build_args'], **sim['build'])
    sys.path[:0] = [HERE, os.path.join(home, 'python')]   # the runner hands sys.path to the simulator's Python
    xml = runner.test(hdl_toplevel=TOP, test_module=MODULE, build_dir=work, test_dir=work, testcase=a.test,
                      extra_env={'WAVELENS_MARKS': marks, 'PYTHONDONTWRITEBYTECODE': '1'}, **sim['test'])
    total, failed = get_results(xml)
    print(f'run.py: {a.sim}: {total} tests, {failed} failed: {out}')
    if not a.no_marks and not os.path.exists(marks):
        print(f'run.py: no wavelens_cocotb under {home}: the tests ran without their marks, no page')
    elif not a.no_marks:
        page = os.path.join(out, 'cocotb_apb.html')
        subprocess.run([sys.executable, '-I', os.path.join(home, 'tools', 'mkhtml.py'), '--config', CONFIG, '--waves', os.path.join(work, 'dump.vcd'),
                        '--marks', marks, '--marks-views', a.views, '--no-sva', '--out', page], check=True)
        print(f'run.py: {page}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
