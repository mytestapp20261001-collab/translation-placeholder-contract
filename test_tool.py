import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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

class FindingBudgetTests(unittest.TestCase):
    cli = Tests.cli
    def test_exact_finding_budget_is_complete(self):
        source = {f'key{i:03d}': 'text' for i in range(100)}
        data = {'source': source, 'translations': {f'locale{i}': {} for i in range(100)}}
        result = tool.audit(data)
        self.assertEqual(result['status'], 'findings')
        self.assertEqual(len(result['findings']), tool.MAX_FINDINGS)
        self.assertEqual(result['summary'], {'source_keys': 100, 'locales': 100, 'entries': 100})
        self.assertEqual(result['findings'][-1]['locale_index'], 99)
        self.assertEqual(result, tool.audit(data))

    def test_one_over_finding_budget_rejects_without_extra_allocation(self):
        source = {f'key{i:03d}': 'text' for i in range(101)}
        translations = {f'locale{i}': {} for i in range(99)}
        translations['last'] = dict(list(source.items())[:-2])
        data = {'source': source, 'translations': translations}
        with mock.patch.object(tool, 'finding', wraps=tool.finding) as emit:
            with self.assertRaisesRegex(tool.BadInput, r'^finding budget exceeded \(10000\)$'):
                tool.audit(data)
        self.assertEqual(emit.call_count, tool.MAX_FINDINGS)

    def test_every_finding_category_shares_the_budget(self):
        cases = [
            {'source': {'a': 'text', 'b': 'text'}, 'translations': {'fr': {}}},
            {'source': {'a': 'text'}, 'translations': {'fr': {'a': 'text', 'b': '', 'c': ''}}},
            {'source': {'a': 'text', 'b': 'text'}, 'translations': {'fr': {'a': '', 'b': ''}}},
            {'source': {'a': '{x}', 'b': '{x}'}, 'translations': {'fr': {'a': '{y}', 'b': '{y}'}}},
            {'source': {'a': '{x}'}, 'translations': {'fr': {'a': ''}}},
        ]
        with mock.patch.object(tool, 'MAX_FINDINGS', 1):
            for data in cases:
                with self.subTest(data=data), self.assertRaises(tool.BadInput):
                    tool.audit(data)

    def test_empty_and_placeholder_findings_count_separately(self):
        source = {f'key{i}': '{name}' for i in range(tool.MAX_FINDINGS // 2)}
        values = dict.fromkeys(source, '')
        result = tool.audit({'source': source, 'translations': {'fr': values}})
        self.assertEqual(len(result['findings']), tool.MAX_FINDINGS)
        self.assertEqual([row['code'] for row in result['findings'][:2]],
                         ['empty_translation', 'placeholder_mismatch'])
        values['extra'] = ''
        with self.assertRaises(tool.BadInput):
            tool.audit({'source': source, 'translations': {'fr': values}})

    def test_cli_finding_budget_is_small_non_echoing_error(self):
        data = {'source': {f'private_key{i}': 'private text' for i in range(1000)},
                'translations': {f'private_locale{i}': {} for i in range(100)}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'contract.json'
            path.write_text(json.dumps(data))
            self.assertLess(path.stat().st_size, tool.MAX_BYTES)
            result = self.cli(path)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, '')
        self.assertLess(len(result.stdout.encode()), 256)
        self.assertNotIn('private', result.stdout)
        self.assertEqual(json.loads(result.stdout), {
            'schema_version': 1, 'tool': tool.TOOL, 'status': 'error',
            'error': 'finding budget exceeded (10000)'})

class MaintenanceReceiptTests(unittest.TestCase):
    def test_maintenance_receipt_is_fail_closed(self):
        spec = importlib.util.spec_from_file_location('release_validation', HERE / 'scripts/validate_release.py')
        validation = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validation)
        record = json.loads((HERE / 'docs/MIGRATION.json').read_text())
        receipt = json.loads((HERE / 'docs/MAINTENANCE_2026-10-22.json').read_text())
        original = {entry['path']: entry['sha256'] for entry in record['preserved_files']}
        self.assertEqual(validation.maintenance_hashes(record, None), original)
        result = validation.maintenance_hashes(record, receipt)
        for change in receipt['changes']:
            self.assertEqual(result[change['path']], change['current_sha256'])
        for path in original.keys() - {'tool.py', 'test_tool.py'}:
            self.assertEqual(result[path], original[path])
        invalid = []
        for field, value in [('path', '../tool.py'), ('path', 'README.md'), ('path', 'SKILL.md'),
                             ('path', 'docs/MIGRATION.json'), ('original_sha256', '0' * 64),
                             ('current_sha256', 'invalid'), ('reason', '')]:
            candidate = copy.deepcopy(receipt)
            candidate['changes'][0][field] = value
            invalid.append(candidate)
        candidate = copy.deepcopy(receipt)
        candidate['changes'].append(candidate['changes'][0].copy())
        invalid.append(candidate)
        for field, value in [('schema_version', True), ('repository_id', 0),
                             ('repository', 'wrong/owner'), ('base_commit', 'invalid'), ('changes', [])]:
            candidate = copy.deepcopy(receipt)
            candidate[field] = value
            invalid.append(candidate)
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validation.maintenance_hashes(record, candidate)

if __name__ == "__main__": unittest.main()
