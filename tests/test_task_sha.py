import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ws import core
from mcp import server
from testutil import isolate_home, rmtree_owned


class TaskShaTests(unittest.TestCase):
    """W1/W2 from a real 0.2.0 migration: empty expected_sha must not skip the stale-write check silently."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(rmtree_owned, self.tmp.name, self.tmp.name)
        isolate_home(self, self.tmp.name)
        self.root = Path(self.tmp.name) / 'workspace'
        core.init(self.root, 'fixture')
        core.task_new(self.root, 'T1', 'demo')
        core.claim(self.root, 'T1', 'w1')

    def cli(self, *args):
        env = dict(os.environ, WS_ROOT=str(self.root), WS_OFFLINE='1')
        p = subprocess.run([sys.executable, '-m', 'ws.cli', *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    def test_task_sha_prints_the_sha_checkpoint_accepts(self):
        code, out, err = self.cli('task', 'sha', 'T1')
        self.assertEqual(code, 0, err)
        sha = json.loads(out) if out.startswith('"') else out
        self.assertEqual(sha, core.task_read(self.root, 'T1')['sha'])
        core.checkpoint(self.root, 'T1', 'in_progress', 'next step', expected_sha=sha)

    def test_empty_expected_sha_is_refused_and_task_unchanged(self):
        before = core.task_path(self.root, 'T1').read_bytes()
        for empty in ('', '   '):
            with self.assertRaisesRegex(core.WsError, 'expected_sha is empty.*ws task sha T1'):
                core.checkpoint(self.root, 'T1', 'in_progress', 'next step', expected_sha=empty)
        self.assertEqual(core.task_path(self.root, 'T1').read_bytes(), before)

    def test_empty_expected_sha_refused_from_cli(self):
        code, out, err = self.cli('checkpoint', 'T1', '--status', 'in_progress', '--next', 'x', '--expected-sha', '')
        self.assertNotEqual(code, 0)
        self.assertIn('ws task sha T1', out + err)

    def test_stale_sha_names_the_command(self):
        sha = core.task_read(self.root, 'T1')['sha']
        core.checkpoint(self.root, 'T1', 'in_progress', 'first')
        with self.assertRaisesRegex(core.WsError, 'changed since you read it.*ws task sha T1'):
            core.checkpoint(self.root, 'T1', 'in_progress', 'second', expected_sha=sha)

    def test_omitted_expected_sha_still_saves(self):
        core.checkpoint(self.root, 'T1', 'in_progress', 'no check requested')
        self.assertIn('no check requested', core.task_path(self.root, 'T1').read_text())


if __name__ == '__main__':
    unittest.main()
