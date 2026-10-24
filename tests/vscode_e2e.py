#!/usr/bin/env python3
"""vscode_e2e.py — the VS Code extension (vscode/) end to end in a real VS Code: in WSL, the VS Code of Windows connected
to this distribution (Remote - WSL, the same split as Remote-SSH: the extension on Linux, the tab on Windows); elsewhere
a local `code`. A window of its own (its own user data under BUILD/vscode-e2e) runs vscode/test/e2e.js: each dump
opens in a wavelens tab, a picture of it is written, the store and the reload are checked; the results and the pictures
in BUILD/vscode-e2e. Needs VS Code (WAVELENS_CODE: its Code.exe or code) and, in WSL, its Remote - WSL extension.

  vscode_e2e.py [--build out] [--installed] [DUMP …]   (default: the FSM example's VCD and FST, test_stream_video.fst)

--installed: the extension installed in VS Code (make vsix, then code --install-extension …), not vscode/ of the
repository (the window runs an empty extension of its own for the tests).
"""
import argparse, json, os, shutil, subprocess, sys, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# the checks a run must have (review VI T11: a run that stops early, or one whose list lost a check, is a failure, not
# fewer passes); 'open NAME' for each dump; the FSM VCD's Verilator checks when it is one of them
REQUIRED = ['active at startup', 'activate', 'store over reopening', 'reload on a new write', 'reload: the new values',
            'the log: Problems on the lines', 'the log: cleared with the tab', "theme: the command's list picks one",
            'sources: a Questa VCD named from the workspace', 'types: the file beside the dump wins over the sources, read again when written',
            'a dump in a folder with a space', 'agent: view_live opens the dump', 'agent: view_edit / view_get on the tab',
            'agent: its link note removed on exit']
FSM = ['types: the command makes them with Verilator, the tab reads them', "types: Verilator, a file's name of ? expanded"]
WIN_CODE = '/mnt/c/Program Files/Microsoft VS Code/Code.exe'


def find_code():
    if os.environ.get('WAVELENS_CODE'):
        return os.environ['WAVELENS_CODE']
    if os.environ.get('WSL_DISTRO_NAME'):
        user = subprocess.run(['cmd.exe', '/c', 'echo %USERNAME%'], capture_output=True, text=True, cwd='/mnt/c').stdout.strip()
        for p in (f'/mnt/c/Users/{user}/AppData/Local/Programs/Microsoft VS Code/Code.exe', WIN_CODE):
            if os.path.isfile(p):
                return p
    return shutil.which('code')


def winpath(p):
    return subprocess.run(['wslpath', '-w', p], capture_output=True, text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--build', default=os.environ.get('BUILD') or os.path.join(ROOT, 'out'))
    ap.add_argument('--timeout', type=float, default=600)
    ap.add_argument('--installed', action='store_true', help='the installed extension, not vscode/')
    ap.add_argument('dumps', nargs='*')
    a = ap.parse_args()
    b = os.path.abspath(a.build)
    dumps = [os.path.abspath(d) for d in a.dumps] or [p for p in (os.path.join(b, 'examples', 'fsm', 'fsm.vcd'),
                                                                   os.path.join(b, 'examples', 'fsm', 'fsm.fst'),
                                                                   os.path.join(ROOT, 'examples', 'test_video', 'test_stream_video.fst'))
                                                         if os.path.isfile(p)]
    if not dumps:
        sys.exit('vscode_e2e: no dumps (make examples)')
    code = find_code()
    if not code:
        sys.exit('vscode_e2e: no VS Code (WAVELENS_CODE)')
    out = os.path.join(b, 'vscode-e2e')
    os.makedirs(out, exist_ok=True)
    if os.path.exists(os.path.join(out, 'result.json')):
        os.remove(os.path.join(out, 'result.json'))
    distro = os.environ.get('WSL_DISTRO_NAME')
    run_id = uuid.uuid4().hex   # the results of this run only: an old result.json is not taken
    # what to do, for e2e.js on the side of the extension (the environment of Code.exe does not reach the WSL side)
    cfg = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'wavelens', 'e2e.json')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w', encoding='utf-8') as f:
        json.dump({'out': out, 'dumps': dumps, 'run': run_id}, f)
    env = dict(os.environ)
    env.pop('ELECTRON_RUN_AS_NODE', None)
    dev = os.path.join(ROOT, 'vscode')
    if a.installed:   # an extension that is not wavelens for the development path: the installed wavelens stays
        dev = os.path.join(out, 'empty')
        os.makedirs(dev, exist_ok=True)
        with open(os.path.join(dev, 'package.json'), 'w', encoding='utf-8') as f:
            json.dump({'name': 'wavelens-e2e', 'publisher': 'wavelens', 'version': '0.0.0', 'engines': {'vscode': '^1.80.0'}}, f)
    if distro:   # Code.exe of Windows, the extension and the tests on this side (vscode-remote URIs)
        rem = lambda p: f'vscode-remote://wsl+{distro}{p}'
        ud = winpath(os.path.join(out, 'user-data'))
        argv = [code, '--remote', f'wsl+{distro}', '--user-data-dir', ud, '--new-window', '--disable-workspace-trust',
                f'--extensionDevelopmentPath={rem(dev)}',
                f'--extensionTestsPath={rem(os.path.join(ROOT, "vscode", "test", "e2e.js"))}',
                '--folder-uri', rem(os.path.dirname(dumps[0]))]
    else:
        argv = [code, '--user-data-dir', os.path.join(out, 'user-data'), '--new-window', '--disable-workspace-trust',
                f'--extensionDevelopmentPath={dev}', f'--extensionTestsPath={os.path.join(ROOT, "vscode", "test", "e2e.js")}',
                os.path.dirname(dumps[0])]
    print('vscode_e2e:', ' '.join(argv[:3]), '…', flush=True)
    try:
        r = subprocess.run(argv, env=env, timeout=a.timeout, cwd='/mnt/c' if distro else None, stdin=subprocess.DEVNULL)
        code_rc = r.returncode
    except subprocess.TimeoutExpired:
        code_rc = 'timeout'
    try:
        with open(os.path.join(out, 'result.json'), encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        sys.exit(f'vscode_e2e: no results (VS Code exit {code_rc}): see {out}')
    if not isinstance(doc, dict) or doc.get('run') != run_id or not doc.get('done'):
        sys.exit(f'vscode_e2e: the results are not of this run, or it did not end (VS Code exit {code_rc}): see {out}')
    res = doc['results']
    for t in res:
        print(f"  {'ok  ' if t['pass'] else 'FAIL'} {t['name']}: {json.dumps(t.get('info'), ensure_ascii=False)}")
    want = REQUIRED + ['open ' + os.path.basename(d) for d in dumps] + (FSM if any(d.endswith('fsm.vcd') for d in dumps) else [])
    missing = [n for n in want if n not in {t['name'] for t in res}]
    for n in missing:
        print(f'  FAIL {n}: not run')
    bad = [t for t in res if not t['pass']]
    print(f'vscode_e2e: {len(res) - len(bad)} of {len(res)} passed' + (f', {len(missing)} not run' if missing else '') + f'; pictures in {out}')
    sys.exit(1 if bad or missing or code_rc == 'timeout' else 0)


if __name__ == '__main__':
    main()
