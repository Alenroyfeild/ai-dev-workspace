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
    def test_claude_transport_isolates_home_and_preserves_resume(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {'WS_BENCH_PROVIDER': 'claude'}):
            root = Path(d) / 'fixture'; root.mkdir()
            home = Path(d) / 'home'
            worker = mock.Mock(returncode=0)
            worker.communicate.return_value = ('not json\n[]\n' + json.dumps({'type': 'result', 'session_id': 'synthetic-session',
                'result': 'Saved synthetic decision.', 'usage': {'input_tokens': 7, 'output_tokens': 3}, 'total_cost_usd': 0.01}), '')
            with mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker) as launch, \
                    mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300 (Claude Code)')):
                result, message, session = rollout_transport.session(root, home, 'synthetic prompt', False, Path(d) / 'absent', resume='prior-session')
            args = launch.call_args.args[0]; env = launch.call_args.kwargs['env']
            self.assertEqual(env['HOME'], str(home))
            self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(home / '.claude'))
            self.assertEqual(args[args.index('--resume') + 1], 'prior-session')
            self.assertEqual(args[args.index('--mcp-config') + 1], '{"mcpServers": {}}')
            policy = json.loads(args[args.index('--settings') + 1])
            self.assertTrue(policy['permissions']['blockReadsOutsideWorkingDirectories'])
            self.assertTrue(policy['sandbox']['failIfUnavailable'])
            self.assertFalse(policy['sandbox']['allowUnsandboxedCommands'])
            self.assertTrue(result['completed']); self.assertEqual(result['input_tokens'], 7)
            self.assertEqual((message, session), ('Saved synthetic decision.', 'synthetic-session'))

    def test_claude_rejects_unsupported_isolation_version(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.100')), \
                mock.patch.object(rollout_transport.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(RuntimeError, 'no fallback'):
                rollout_transport.claude_session(Path(d), Path(d) / 'home', 'synthetic', False)
            launch.assert_not_called()

    def test_claude_interrupt_stops_owned_worker_group(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rollout_transport.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='2.1.300')):
            worker = mock.Mock(pid=12345)
            worker.communicate.side_effect = [KeyboardInterrupt, ('', '')]
            with mock.patch.object(rollout_transport.subprocess, 'Popen', return_value=worker), mock.patch.object(rollout_transport.os, 'killpg') as stop:
                with self.assertRaises(KeyboardInterrupt):
                    rollout_transport.claude_session(Path(d), Path(d) / 'home', 'synthetic', False)
                stop.assert_called_once_with(12345, rollout_transport.signal.SIGKILL)

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
