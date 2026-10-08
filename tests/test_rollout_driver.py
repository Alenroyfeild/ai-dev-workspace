import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from bench import rollout_run


class RolloutDriverTests(unittest.TestCase):
    def test_interruption_keeps_completed_runs_without_seed_hints(self):
        with tempfile.TemporaryDirectory() as d:
            args = argparse.Namespace(n=5, seed=42, output=Path(d) / 'result.json')
            benchmark = SimpleNamespace(seed=lambda n: n, trial=mock.Mock(side_effect=[{'arm': 'baseline', 'result': 'abstention'}, RuntimeError('interrupted')]),
                run=SimpleNamespace(KIT=Path(d), command=lambda *a: SimpleNamespace(stdout='fixture')))
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(RuntimeError):
                rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            result = json.loads(args.output.read_text())
            self.assertEqual(len(result['runs']), 1); self.assertIsNone(result['seed'])
            benchmark.trial.side_effect = None; benchmark.trial.return_value = {'result': 'pass'}
            with contextlib.redirect_stdout(io.StringIO()): rollout_run.run_trials(benchmark, args, Path(d) / 'absent-auth')
            result = json.loads(args.output.read_text())
            self.assertEqual(result['seed'], 42); self.assertEqual(len(result['runs']), 15)
