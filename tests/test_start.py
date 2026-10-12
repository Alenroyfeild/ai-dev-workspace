import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core


class StartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'; self.home.mkdir()
        self.repo = Path(self.tmp.name) / 'repo'; self.repo.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'), WS_OFFLINE='1')
        patch.start(); self.addCleanup(patch.stop)
        subprocess.run(['git', 'init', '-q', '-b', 'feature/synthetic'], cwd=self.repo, check=True)
        (self.repo / 'AGENTS.md').write_text('User rules remain.\n')
        subprocess.run(['git', 'add', 'AGENTS.md'], cwd=self.repo, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'fixture'], cwd=self.repo, check=True)
        self.old = Path.cwd(); os.chdir(self.repo); self.addCleanup(os.chdir, self.old)

    def start(self, *args):
        output = io.StringIO(); preview = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(preview): result = cli.main(['start', *args])
        return result, output.getvalue(), preview.getvalue()

    def test_preview_confirmation_external_memory_repeat_and_undo(self):
        before = (self.repo / '.git/info/exclude').read_bytes()
        code, _, preview = self.start('--dry-run')
        self.assertEqual(code, 0); self.assertIn('CLAUDE.local.md', preview); self.assertIn('.claude/settings.local.json', preview)
        self.assertIn(str(self.home / '.ai-dev-workspace/repo'), preview)
        with mock.patch('builtins.input', return_value='n') as ask: self.assertEqual(self.start()[0], 0)
        ask.assert_called_once(); self.assertFalse((self.home / '.ai-dev-workspace').exists())
        with mock.patch('builtins.input', return_value='y') as ask: code, output, preview = self.start()
        ask.assert_called_once(); self.assertEqual(code, 0); self.assertEqual(len(output.splitlines()), 3)
        workspace = core.find_root(); self.assertEqual(workspace, (self.home / '.ai-dev-workspace/repo').resolve())
        self.assertFalse((self.repo / 'workspace.json').exists()); self.assertFalse((self.repo / '.gitignore').exists())
        self.assertEqual((self.repo / 'AGENTS.md').read_text(), 'User rules remain.\n')
        task = core.task_list(workspace)[0]; self.assertEqual(task['title'], 'feature/synthetic'); self.assertTrue(task['claimed_by'])
        for relative in ('CLAUDE.local.md', 'AGENTS.override.md', '.claude/settings.local.json', '.codex/hooks.json', '.mcp.json'):
            self.assertTrue((self.repo / relative).is_file()); self.assertIn(relative, preview)
        self.assertFalse((self.home / '.claude').exists()); self.assertFalse((self.home / '.codex').exists())
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.repo), b'')
        snapshot = {p: p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        self.assertEqual(self.start('--yes')[0], 0); self.assertEqual(snapshot, {p:p.read_bytes() for p in self.repo.rglob('*') if p.is_file()})
        self.assertEqual(self.start('--undo')[0], 0)
        self.assertEqual((self.repo / '.git/info/exclude').read_bytes(), before)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.repo), b'')
        self.assertTrue((workspace / 'workspace.json').exists())

    def test_existing_local_settings_restored_and_user_edits_kept(self):
        local = self.repo / '.claude/settings.local.json'; local.parent.mkdir()
        local.write_text('{"permissions":{"allow":["Read"]},"hooks":{}}')
        before = local.read_bytes(); self.assertEqual(self.start('--yes')[0], 0)
        (self.repo / '.git/info/exclude').write_bytes((self.repo / '.git/info/exclude').read_bytes() + b'\nuser-pattern\n')
        self.assertEqual(self.start('--undo')[0], 0); self.assertEqual(local.read_bytes(), before)
        self.assertIn(b'user-pattern', (self.repo / '.git/info/exclude').read_bytes())

    def test_detached_tracked_targets_and_workspace_collision_fail_before_writes(self):
        subprocess.run(['git', 'checkout', '-q', '--detach'], check=True)
        self.assertEqual(self.start('--yes')[0], 2); self.assertFalse((self.repo / '.ws-start.json').exists())
        subprocess.run(['git', 'checkout', '-q', 'feature/synthetic'], check=True)
        (self.repo / '.mcp.json').write_text('{}'); subprocess.run(['git', 'add', '.mcp.json'], check=True)
        self.assertEqual(self.start('--yes')[0], 2); self.assertFalse((self.repo / '.ws-start.json').exists())
        self.assertFalse((self.home / '.ai-dev-workspace').exists())
        workspace = self.home / '.ai-dev-workspace/repo'; core.init(workspace, 'other', clients=[])
        original = (workspace / 'workspace.json').read_bytes()
        self.assertEqual(self.start('--yes')[0], 2); self.assertEqual((workspace / 'workspace.json').read_bytes(), original)

    def test_workspace_override_and_undo_preserves_modified_local_file(self):
        workspace = self.home / 'private memory'
        self.assertEqual(self.start('--yes', '--workspace', str(workspace))[0], 0)
        local = self.repo / 'CLAUDE.local.md'; local.write_text('User changed this file\n')
        self.assertEqual(self.start('--undo')[0], 2); self.assertEqual(local.read_text(), 'User changed this file\n')
