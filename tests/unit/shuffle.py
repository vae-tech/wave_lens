"""The unit tests in another order (review VI T10: a test that passes only after another one): every test of tests/unit
one by one, shuffled by a seed (make unit-shuffle SEED=n; the seed is printed, so an order that fails can be run again).

  python3 -I tests/unit/shuffle.py [SEED]
"""
import os, random, sys, unittest


def flat(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from flat(t)
        else:
            yield t


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else random.randrange(1 << 30)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tests = list(flat(unittest.defaultTestLoader.discover(os.path.join(root, 'tests', 'unit'), top_level_dir=root)))
    random.Random(seed).shuffle(tests)
    print(f'shuffle: {len(tests)} tests, seed {seed}', file=sys.stderr)
    r = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(tests))
    print(f'shuffle: seed {seed}', file=sys.stderr)
    sys.exit(0 if r.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
