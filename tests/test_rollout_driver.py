import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from bench import rollout_run, rollout_transport


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


@unittest.skipIf(os.name == "nt", "Owned process cleanup uses POSIX process groups.")
class RolloutTransportTests(unittest.TestCase):
    def test_interrupt_stops_owned_worker_group(self):
        with tempfile.TemporaryDirectory() as d:
            worker = mock.Mock(pid=12345)
            worker.communicate.side_effect = [KeyboardInterrupt, ('', '')]
            with mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker), mock.patch.object(rollout_transport.os, 'killpg') as stop:
                with self.assertRaises(KeyboardInterrupt):
                    rollout_transport.session(Path(d), Path(d) / 'home', 'synthetic', False, Path(d) / 'absent-auth')
                stop.assert_called_once_with(12345, rollout_transport.signal.SIGKILL)

    def test_resumed_usage_counts_only_increment(self):
        events = [{'type': 'turn.completed', 'usage': {'input_tokens': 17, 'output_tokens': 4, 'cached_input_tokens': 8}}]
        result = rollout_transport.usage(events, 0, {'input_tokens': 12, 'output_tokens': 1, 'cache_read_tokens': 4})
        self.assertEqual((result['input_tokens'], result['output_tokens'], result['cache_read_tokens']), (5, 3, 4))

