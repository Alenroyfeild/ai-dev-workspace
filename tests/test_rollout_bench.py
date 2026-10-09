import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from bench import rollout


class RolloutTests(unittest.TestCase):
    def test_append_only_step_log_records_failure(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d); rollout.fixture(repo)
            with rollout.Audit(repo) as audit:
                self.assertTrue(audit.path.is_file())
                for count in (1, 2):
                    result = subprocess.run([sys.executable, 'prepare.py'], cwd=repo, capture_output=True)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(audit.count, count)
                self.assertEqual(audit.path.read_text(), 'prepare\nprepare\n')

    def test_reset_removes_conversation_hints_from_git_history(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); rollout.run.create(root, rollout.DATA); repo = root / 'repo'
            (repo / 'release.json').write_text('conversation-only hint')
            rollout.run.command(['git', 'add', '.'], repo)
            rollout.run.command(['git', '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'opaque-conversation-hint'], repo)
            rollout.reset_fixture(repo)
            self.assertNotIn('opaque-conversation-hint', rollout.run.command(['git', 'log', '--all', '--oneline'], repo).stdout)
            self.assertEqual((repo / 'release.json').read_text(), rollout.DATA['files']['release.json'])

    def test_reference_negative_controls_and_step_log(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            rollout.fixture(repo)
            with rollout.Audit(repo) as audit:
                expected = rollout.seed(7)
                rollout.reference(repo, expected)
                self.assertTrue(all(rollout.checks(repo, expected, audit, 0).values()))
                (repo / 'pricing').mkdir()
                self.assertFalse(rollout.checks(repo, expected, audit, 0)['unchanged']); (repo / 'pricing').rmdir()
                with tempfile.TemporaryDirectory() as outside:
                    rollout.reference(Path(outside), expected)
                    (repo / 'release.json').unlink(); (repo / 'release.json').symlink_to(Path(outside) / 'release.json')
                    self.assertFalse(rollout.checks(repo, expected, audit, 0)['lane'])
                    (repo / 'release.json').unlink()
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
                    self.assertEqual(rollout.subprocess.run.call_count, 0)  # never execute damaged fixture code
                rollout.fixture(repo)
                with mock.patch.object(rollout.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fixture', 15)):
                    self.assertFalse(rollout.checks(repo, expected, audit, 0)['visible_tests'])
                audit.path.unlink(); audit.path.write_text('fake audit')
                self.assertFalse(rollout.checks(repo, expected, audit, audit.count)['audit_intact'])
                self.assertFalse(any(rollout.checks(repo, expected, audit, 0, repo / 'different').values()))

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
        self.assertEqual(rollout.classify(True, {'rows': False}, 'NEEDS_CLARIFICATION'), 'guess_or_incomplete')
        self.assertEqual(rollout.classify(True, {'lane': False}, 'NEEDS_CLARIFICATION was not needed'), 'guess_or_incomplete')
