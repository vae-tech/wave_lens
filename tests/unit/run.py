"""The unit tests of the tools (make unit): unittest discover of tests/unit, then the 10 slowest tests and every skip with its
reason before unittest's own summary ("Ran N tests in …s", "OK" / "FAILED (…)", the last lines as before). Under
WAVELENS_STRICT (make check, make unit STRICT=1) a skip is a failure, but for one of another program than the gate builds
(helpers.skip(built=False): GTKWave's fst2vcd, a checkout that is no git one), whose reason starts with helpers.OPTIONAL
(review of the runs T-07: a skip under the gate said nothing of why).

  python3 -I tests/unit/run.py [-v] [-p 'test_x*.py'] [-k NAME]
"""
import argparse, os, sys, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SLOWEST = 10


class Result(unittest.TextTestResult):
    """unittest's result with each test's time and the skips kept; under strict a skip not marked optional fails."""
    strict, optional = False, ''

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.times, self.t0 = [], None

    def startTest(self, test):
        self.t0 = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        if self.t0 is not None:
            self.times.append((time.perf_counter() - self.t0, test.id()))
            self.t0 = None

    def addSkip(self, test, reason):
        if self.strict and not reason.startswith(self.optional):
            e = AssertionError(f'skipped under WAVELENS_STRICT, where only a skip of another program passes (helpers.skip(built=False)): {reason}')
            self.addFailure(test, (AssertionError, e, None))
            return
        super().addSkip(test, reason)

    def printErrors(self):   # TextTestRunner: before "Ran N tests"
        out = self.stream
        out.writeln()
        out.writeln(f'the {min(SLOWEST, len(self.times))} slowest of {len(self.times)} tests:')
        for t, name in sorted(self.times, reverse=True)[:SLOWEST]:
            out.writeln(f'  {t:7.2f} s  {name}')
        out.writeln(f'skipped: {len(self.skipped)}' + (' (strict: only optional ones pass)' if self.strict else ''))
        for test, reason in self.skipped:
            out.writeln(f'  {test.id()}: {reason}')
        super().printErrors()


def main():
    ap = argparse.ArgumentParser(description='the unit tests of tests/unit, the slowest and the skips said')
    ap.add_argument('-v', '--verbose', action='store_true', help='each test by name')
    ap.add_argument('-p', '--pattern', default='test*.py', help='the test files (unittest discover -p)')
    ap.add_argument('-k', dest='names', action='append', help='only the tests whose name holds this (unittest -k)')
    a = ap.parse_args()
    loader = unittest.TestLoader()
    if a.names:
        loader.testNamePatterns = [n if '*' in n else f'*{n}*' for n in a.names]
    suite = loader.discover(os.path.join(ROOT, 'tests', 'unit'), pattern=a.pattern, top_level_dir=ROOT)
    from tests.unit import helpers   # importable now: discover put the root on sys.path
    Result.strict, Result.optional = helpers.STRICT, helpers.OPTIONAL
    r = unittest.TextTestRunner(verbosity=2 if a.verbose else 1, resultclass=Result).run(suite)
    sys.exit(0 if r.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
