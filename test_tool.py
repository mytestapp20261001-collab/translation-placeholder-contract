import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("local_tool", HERE / "tool.py")
tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)

class Tests(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, str(HERE/'tool.py'), *map(str,args)], capture_output=True, text=True)
    def codes(self, *args):
        return [item['code'] for item in tool.audit(*args)['findings']]
    def test_cli_bad_args(self):
        result = self.cli('--unknown')
        self.assertEqual(result.returncode, 2); self.assertEqual(json.loads(result.stdout)['status'], 'error')
    def test_read_size_limit(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'big'; path.write_text(' '*(tool.MAX_BYTES+1))
            with self.assertRaises(tool.BadInput): tool.read_text(path)
    def good(self): return json.loads((HERE/'examples/pass.json').read_text())
    def test_pass(self): self.assertEqual(tool.audit(self.good())['status'],'pass')
    def test_findings(self):
        codes=self.codes(json.loads((HERE/'examples/fail.json').read_text()))
        self.assertEqual(set(codes),{'missing_translation','extra_translation_key','placeholder_mismatch'})
    def test_cli_examples(self):
        for name, expected in [('pass',0),('fail',1)]:
            result=self.cli(HERE/f'examples/{name}.json')
            self.assertEqual(result.returncode,expected,result.stdout+result.stderr); json.loads(result.stdout)
    def test_reordered_named_fields(self):
        data={'source':{'x':'{a} {b}'},'translations':{'fr':{'x':'{b} {a}'}}}
        self.assertEqual(tool.audit(data)['status'],'pass')
    def test_automatic_equals_numeric(self): self.assertEqual(tool.placeholders('{} {}'),tool.placeholders('{0} {1}'))
    def test_escaped_braces(self): self.assertFalse(tool.placeholders('{{name}}'))
    def test_nested_spec(self): self.assertEqual(sum(tool.placeholders('{value:{width}.{precision}f}').values()),3)
    def test_spec_change(self):
        data={'source':{'x':'{x:.2f}'},'translations':{'fr':{'x':'{x:.3f}'}}}
        self.assertIn('placeholder_mismatch',self.codes(data))
    def test_repeated_field(self):
        data={'source':{'x':'{a} {a}'},'translations':{'fr':{'x':'{a}'}}}
        self.assertIn('placeholder_mismatch',self.codes(data))
    def test_mixed_numeric(self):
        with self.assertRaises(tool.BadInput): tool.placeholders('{} {1}')
    def test_attributes_rejected(self):
        with self.assertRaises(tool.BadInput): tool.placeholders('{obj.secret}')
    def test_malformed_brace(self):
        with self.assertRaises(tool.BadInput): tool.placeholders('{name')
    def test_icu_rejected(self):
        with self.assertRaises(tool.BadInput): tool.placeholders('{count, plural, one {x} other {y}}')
    def test_empty_translation(self):
        data={'source':{'x':'Hello'},'translations':{'fr':{'x':''}}}
        self.assertIn('empty_translation',self.codes(data))
    def test_bad_shape(self):
        with self.assertRaises(tool.BadInput): tool.audit([])
    def test_json_malformed_cli(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bad.json'
            for text in ['{','{"x":1,"x":2}','{"x":NaN}']:
                path.write_text(text); result=self.cli(path)
                self.assertEqual(result.returncode,2); json.loads(result.stdout)

if __name__ == "__main__": unittest.main()
