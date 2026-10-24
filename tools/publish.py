#!/usr/bin/env python3
"""publish.py — the public branch: one commit per release, its tree the release's without the internal files.

  publish.py 0.18 "Rename to WaveLens, new guides"   [--from dev/v0.18] [--branch master] [--dry-run]

The work and its history stay on dev (tagged dev/vX.Y); the public branch (master) gets one commit per version: the
tree of --from (default the tag dev/vX.Y) less INTERNAL (the reviews, the roadmap prompts and the paths that
prompts/INTERNAL lists, one per line), the date of that commit, the author of the repository, the message
"vX.Y: <message>" and nothing else; the tag vX.Y on it. An empty branch starts at the first version. Only the public
branch and the vX.Y tags go to GitHub (DEVELOPMENT.md § Versions).
"""
import argparse, os, subprocess, sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import WaveError, run_main  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERNAL = ['docs/reviews', 'prompts']   # on dev only, with what prompts/INTERNAL names


def git(*args, env=None, check=True):
    r = subprocess.run(['git', '-C', ROOT, *args], capture_output=True, text=True, env=env)
    if check and r.returncode:
        raise WaveError(f'git {" ".join(args)}: {r.stderr.strip()}')
    return r.stdout.strip() if r.returncode == 0 else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('version', help='MAJOR.MINOR')
    ap.add_argument('message', help='one short line: what the version brings')
    ap.add_argument('--from', dest='src', help='the commit to publish (default: the tag dev/vVERSION)')
    ap.add_argument('--branch', default='master', help='the public branch (default master)')
    ap.add_argument('--dry-run', action='store_true', help='say what would be made, make nothing')
    a = ap.parse_args()
    tag = f'v{a.version}'
    src = git('rev-parse', '--verify', '-q', f'{a.src or "dev/" + tag}^{{commit}}', check=False)
    if not src:
        raise WaveError(f'no commit {a.src or "dev/" + tag} (tag the release on dev first: git tag -a dev/{tag})')
    if git('rev-parse', '--verify', '-q', f'refs/tags/{tag}', check=False):
        raise WaveError(f'the tag {tag} is there already')
    parent = git('rev-parse', '--verify', '-q', f'refs/heads/{a.branch}', check=False)
    internal = INTERNAL + (git('show', f'{src}:prompts/INTERNAL', check=False) or '').split()
    index = os.path.join(git('rev-parse', '--absolute-git-dir'), 'publish.index')
    env = dict(os.environ, GIT_INDEX_FILE=index)
    try:   # the tree without INTERNAL, in an index of its own (the work tree and its index stay as they are)
        git('read-tree', f'{src}^{{tree}}', env=env)
        git('rm', '--cached', '-r', '-q', '-f', '--ignore-unmatch', '--', *internal, env=env)
        tree = git('write-tree', env=env)
    finally:
        if os.path.exists(index):
            os.remove(index)
    if parent and git('rev-parse', f'{parent}^{{tree}}') == tree:
        raise WaveError(f'{a.branch} has this tree already: nothing to publish')
    msg = f'{tag}: {a.message.strip()}'
    if a.dry_run:
        print(f'publish: {a.branch} <- "{msg}" (tree {tree[:10]} of {src[:10]}{", the first commit" if not parent else ""})')
        return 0
    date = git('log', '-1', '--format=%cI', src)
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    commit = git('commit-tree', tree, *(['-p', parent] if parent else []), '-m', msg, env=env)
    git('update-ref', f'refs/heads/{a.branch}', commit, *([parent] if parent else ['']))
    git('tag', '-a', tag, '-m', f'WaveLens {a.version}', commit, env=env)
    print(f'publish: {a.branch} {commit[:10]} "{msg}", tag {tag}')
    return 0


if __name__ == '__main__':
    run_main(main, 'publish')
