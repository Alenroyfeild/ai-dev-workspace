import json
import tempfile
import unittest
from pathlib import Path
from bench import run


class BenchmarkTests(unittest.TestCase):
    def test_fixture_hidden_checks_and_reference(self):
        data = json.loads((run.HERE / 'scenarios/decisions.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run.create(root, data)
            self.assertEqual(sum(run.score(root, data)['checks'].values()), 2)
            for name, text in data['reference'].items(): (root / 'repo' / name).write_text(text)
            result = run.score(root, data)
            self.assertTrue(result['tests_pass']); self.assertTrue(all(result['checks'].values()))
            (root / 'repo/shop/auth/login.py').write_text('invalid Python syntax !')
            self.assertFalse(all(run.score(root, data)['checks'].values()))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError): run.create(Path(directory), {'files': {'../outside': 'no'}})

    def test_provider_usage_is_parsed_and_failure_is_not_success(self):
        events = [{'type': 'item.completed', 'item': {'type': 'command_execution'}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 12, 'output_tokens': 3}}]
        result = run.metrics('codex', events, 0)
        self.assertEqual((result['tool_calls'], result['input_tokens'], result['output_tokens']), (1, 12, 3))
        self.assertFalse(run.metrics('codex', [], 1)['completed'])
