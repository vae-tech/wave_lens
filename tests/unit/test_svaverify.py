"""tools/svaverify.py: the parts that need no Verilator (the blanking that keeps the line numbers, the spans)."""
import os, unittest

from tests.unit import helpers as H
import svabuild
import svaverify as V


class Blank(unittest.TestCase):
    def test_keeps_lines_and_columns(self):
        text = 'a: assert property (x |-> y)\n    else $error("m");\nb: assert property (z);\n'
        out = V.blank(text, [(0, text.index(';') + 1)])
        self.assertEqual(out.count('\n'), text.count('\n'))
        self.assertEqual(out.splitlines()[2], 'b: assert property (z);')
        self.assertEqual(set(''.join(out.splitlines()[:2])), {' '})


@H.needs(svabuild.find_bin(), 'the sva CLI (make sva-build)')
class Spans(unittest.TestCase):
    def test_assertions_with_actions_and_declarations(self):
        f = 'examples/axi_lite/axi_lite.sva'
        items = {x['label']: x for x in V.parse(svabuild.find_bin(), [f])[f]}
        self.assertTrue(items['s_hs']['text'].startswith('sequence s_hs') and items['s_hs']['text'].endswith('endsequence'))
        a = next(x for x in items.values() if x['kind'] == 'assert')
        self.assertTrue(a['text'].startswith(a['label']) and a['text'].endswith(';'))
        self.assertTrue(os.path.exists(os.path.join(H.ROOT, f)))


if __name__ == '__main__':
    unittest.main()
