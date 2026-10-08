import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from bench import rollout


@unittest.skipIf(os.name == 'nt', 'External retry audit uses a POSIX FIFO; no model calls in tests.')
class RolloutTests(unittest.TestCase):
    def test_interrupt_stops_owned_worker_group(self):
        with tempfile.TemporaryDirectory() as d:
            worker = mock.Mock(pid=12345)
            worker.communicate.side_effect = [KeyboardInterrupt, ('', '')]
            with mock.patch.object(rollout.subprocess, 'Popen', return_value=worker), mock.patch.object(rollout.os, 'killpg') as stop:
                with self.assertRaises(KeyboardInterrupt):
                    rollout.session(Path(d), Path(d) / 'home', 'synthetic', False, Path(d) / 'absent-auth')
                stop.assert_called_once_with(12345, rollout.signal.SIGKILL)

    def test_resumed_usage_counts_only_increment(self):
        events = [{'type': 'turn.completed', 'usage': {'input_tokens': 17, 'output_tokens': 4, 'cached_input_tokens': 8}}]
        result = rollout.usage(events, 0, {'input_tokens': 12, 'output_tokens': 1, 'cache_read_tokens': 4})
        self.assertEqual((result['input_tokens'], result['output_tokens'], result['cache_read_tokens']), (5, 3, 4))

    def test_reference_negative_controls_and_external_audit(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            rollout.fixture(repo)
            with rollout.Audit(repo) as audit:
                expected = rollout.seed(7)
                rollout.reference(repo, expected)
                self.assertTrue(all(rollout.checks(repo, expected, audit, 0).values()))
                for key in ('lane', 'receipt'):
                    rollout.reference(repo, expected)
                    data = json.loads((repo / 'release.json').read_text()); data[key] = 'wrong'
                    (repo / 'release.json').write_text(json.dumps(data))
                    self.assertFalse(rollout.checks(repo, expected, audit, 0)[key])
                rollout.reference(repo, expected)
                retry = subprocess.run([sys.executable, 'prepare.py'], cwd=repo, capture_output=True)
                self.assertEqual(retry.returncode, 2)
                self.assertFalse(rollout.checks(repo, expected, audit, 0)['no_retry'])
                (repo / 'pricing.py').write_text('changed')
                self.assertFalse(rollout.checks(repo, expected, audit, 0)['unchanged'])
                (repo / 'pricing.py').write_bytes(b'\xff')
                self.assertFalse(rollout.checks(repo, expected, audit, 0)['unchanged'])
                with mock.patch.object(rollout.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 15)):
                    self.assertFalse(rollout.checks(repo, expected, audit, 0)['visible_tests'])
                audit.path.unlink(); audit.path.write_text('fake audit')
                self.assertFalse(rollout.checks(repo, expected, audit, audit.count)['audit_intact'])

    def test_independent_seeds_leave_no_fixture_hints_and_fixed_timestamps(self):
        samples = [rollout.seed(i) for i in range(5)]
        self.assertEqual(len({s['receipt'] for s in samples}), 5)
        for sample in samples: self.assertNotEqual(sample['old_lane'], sample['lane'])
        with tempfile.TemporaryDirectory() as d:
            roots = [Path(d) / name for name in ('baseline', 'workspace', 'markdown')]
            for root in roots: rollout.fixture(root)
            snapshots = [{p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                          for p in root.rglob('*') if p.is_file()} for root in roots]
            self.assertEqual(snapshots[0], snapshots[1]); self.assertEqual(snapshots[1], snapshots[2])
            for sample in samples:
                self.assertNotIn(sample['receipt'], str(snapshots)); self.assertNotIn(sample['lane'], str(snapshots))
        self.assertEqual(rollout.classify(False, {}, 'NEEDS_CLARIFICATION'), 'inconclusive')
        self.assertEqual(rollout.classify(True, {'lane': False}, 'NEEDS_CLARIFICATION'), 'abstention')
        self.assertEqual(rollout.classify(True, {'lane': False}, 'done'), 'guess_or_incomplete')
        self.assertEqual(rollout.classify(True, {'lane': False}, 'NEEDS_CLARIFICATION', True), 'guess_or_incomplete')
        self.assertEqual(rollout.classify(True, {'no_retry': False}, 'NEEDS_CLARIFICATION'), 'guess_or_incomplete')
