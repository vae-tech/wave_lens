#!/usr/bin/env python3
"""vscode_e2e.py — the VS Code extension (vscode/) end to end in a real VS Code: in WSL, the VS Code of Windows connected
to this distribution (Remote - WSL, the same split as Remote-SSH: the extension on Linux, the tab on Windows); elsewhere
a local `code`. A window of its own (its own user data under BUILD/vscode-e2e) runs vscode/test/e2e.js: each dump
opens in a wavefw tab, a picture of it is written, the store and the reload are checked; the results and the pictures
in BUILD/vscode-e2e. Needs VS Code (WAVEFW_CODE: its Code.exe or code) and, in WSL, its Remote - WSL extension.

  vscode_e2e.py [--build out] [--installed] [DUMP …]   (default: the FSM example's VCD and FST, test_stream_video.fst)

--installed: the extension installed in VS Code (make vsix, then code --install-extension …), not vscode/ of the
repository (the window runs an empty extension of its own for the tests).
"""
import argparse, json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIN_CODE = '/mnt/c/Program Files/Microsoft VS Code/Code.exe'


def find_code():
    if os.environ.get('WAVEFW_CODE'):
        return os.environ['WAVEFW_CODE']
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
        sys.exit('vscode_e2e: no VS Code (WAVEFW_CODE)')
    out = os.path.join(b, 'vscode-e2e')
    os.makedirs(out, exist_ok=True)
    if os.path.exists(os.path.join(out, 'result.json')):
        os.remove(os.path.join(out, 'result.json'))
    distro = os.environ.get('WSL_DISTRO_NAME')
    # what to do, for e2e.js on the side of the extension (the environment of Code.exe does not reach the WSL side)
    cfg = os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.expanduser('~/.cache'), 'wavefw', 'e2e.json')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w', encoding='utf-8') as f:
        json.dump({'out': out, 'dumps': dumps}, f)
    env = dict(os.environ)
    env.pop('ELECTRON_RUN_AS_NODE', None)
    dev = os.path.join(ROOT, 'vscode')
    if a.installed:   # an extension that is not wavefw for the development path: the installed wavefw stays
        dev = os.path.join(out, 'empty')
        os.makedirs(dev, exist_ok=True)
        with open(os.path.join(dev, 'package.json'), 'w', encoding='utf-8') as f:
            json.dump({'name': 'wavefw-e2e', 'publisher': 'wavefw', 'version': '0.0.0', 'engines': {'vscode': '^1.80.0'}}, f)
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
            res = json.load(f)
    except OSError:
        sys.exit(f'vscode_e2e: no results (VS Code exit {code_rc}): see {out}')
    for t in res:
        print(f"  {'ok  ' if t['pass'] else 'FAIL'} {t['name']}: {json.dumps(t.get('info'), ensure_ascii=False)}")
    bad = [t for t in res if not t['pass']]
    print(f'vscode_e2e: {len(res) - len(bad)} of {len(res)} passed; pictures in {out}')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
