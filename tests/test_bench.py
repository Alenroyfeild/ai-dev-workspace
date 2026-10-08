import json
import sys
import tempfile
import unittest
from pathlib import Path
from bench import run


class BenchmarkTests(unittest.TestCase):
    def test_lesson_and_resume_references_are_achievable(self):
        for scenario in ('lessons', 'resume'):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                data = json.loads((run.HERE / 'scenarios' / (scenario + '.json')).read_text())
                root = Path(directory); run.create(root, data)
                self.assertFalse(all(run.score(root, data)['checks'].values()))
                for name, text in data['reference'].items():
                    path = root / 'repo' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
                result = run.score(root, data)
                self.assertTrue(result['tests_pass']); self.assertTrue(all(result['checks'].values()))
                if scenario == 'resume':
                    run.command([sys.executable, 'pipeline.py', 'prepare'], root / 'repo')
                    self.assertFalse(run.score(root, data)['checks']['no_repeated_prepare'])
                else:
                    run.command([sys.executable, 'scripts/rebuild.py'], root / 'repo')
                    self.assertFalse(run.score(root, data)['checks']['failed_approach_not_repeated'])

    def test_interrupted_work_survives_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); run.create(root, {'files': {'source.txt': 'original'}})
            (root / 'repo/source.txt').write_text('finished step')
            (root / 'repo/receipt.txt').write_text('retained')
            run.prepare_snapshot(root, {'preserve_code': True, 'setup': {'receipt.txt': 'retained'}})
            self.assertEqual((root / 'repo/source.txt').read_text(), 'finished step')
            with self.assertRaises(RuntimeError): run.prepare_snapshot(root, {'setup': {'receipt.txt': 'wrong'}})
            run.prepare_snapshot(root, {})
            self.assertEqual((root / 'repo/source.txt').read_text(), 'original')
            self.assertFalse((root / 'repo/receipt.txt').exists())

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
