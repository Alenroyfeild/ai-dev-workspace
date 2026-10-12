import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core, setup


class StartTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'; self.home.mkdir()
        self.repo = Path(self.tmp.name) / 'repo'; self.repo.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                                CODEX_HOME=str(self.home / '.codex'), WS_OFFLINE='1')
        patch.start(); self.addCleanup(patch.stop)
        subprocess.run(['git', 'init', '-q', '-b', 'feature/synthetic'], cwd=self.repo, check=True)
        self.old_cwd = Path.cwd(); os.chdir(self.repo); self.addCleanup(os.chdir, self.old_cwd)
        self.detected = [dict(assistant=name, cli_available=True, apps=[]) for name in ('claude', 'codex', 'cursor', 'copilot', 'gemini')]

    def start(self, *args):
        output = io.StringIO(); preview = io.StringIO()
        with mock.patch.object(setup, 'detect', return_value=self.detected), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(preview):
            result = cli.main(['start', *args])
        return result, output.getvalue(), preview.getvalue()

    def test_preview_decline_then_first_start_and_repeat_status(self):
        (self.repo / 'AGENTS.md').write_text('User rules remain.\n')
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        code, _, preview = self.start('--dry-run')
        self.assertEqual(code, 0); self.assertIn('AGENTS.md', preview)
        self.assertEqual(before, {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()})
        with mock.patch('builtins.input', return_value='n') as ask:
            self.assertEqual(self.start()[0], 0)
        ask.assert_called_once(); self.assertFalse((self.repo / 'workspace.json').exists())
        with mock.patch('builtins.input', return_value='y') as ask:
            code, output, _ = self.start()
        ask.assert_called_once(); self.assertEqual(code, 2); self.assertEqual(len(output.splitlines()), 3)
        self.assertEqual((self.repo / 'AGENTS.md').read_text(), 'User rules remain.\n')
        task = core.task_list(self.repo)[0]
        self.assertEqual(task['title'], 'feature/synthetic'); self.assertEqual(task['branch'], 'feature/synthetic')
        self.assertTrue(core._local_claim_matches(self.repo, task['id'], core.task_read(self.repo, task['id'], ['Next action'])['meta']))
        for path in ('.mcp.json', '.codex/hooks.json', '.cursor/hooks.json', '.vscode/mcp.json', '.gemini/settings.json'):
            self.assertTrue((self.repo / path).is_file(), path)
        self.assertFalse((self.home / '.codex/config.toml').exists())
        before = {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()}
        with mock.patch.object(core, 'init', side_effect=AssertionError('repeat must only show status')):
            code, output, _ = self.start('--yes')
        self.assertEqual(code, 0); self.assertEqual(len(output.splitlines()), 3)
        self.assertEqual(before, {p.relative_to(self.repo): p.read_bytes() for p in self.repo.rglob('*') if p.is_file()})

    @unittest.skipIf(os.name == 'nt', 'Symlink creation requires Windows privileges')
    def test_symlink_target_and_unmanaged_routing_refused_before_any_write(self):
        outside = self.home / 'outside'; outside.mkdir()
        (self.repo / 'vault').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.start('--yes')[0], 2); self.assertFalse((self.repo / 'workspace.json').exists())
        self.assertEqual(list(outside.iterdir()), [])
        (self.repo / 'vault').unlink(); (self.repo / 'routing.json').write_text('{"user":"keep"}')
        self.assertEqual(self.start('--yes')[0], 2); self.assertFalse((self.repo / 'workspace.json').exists())
        self.assertEqual((self.repo / 'routing.json').read_text(), '{"user":"keep"}')

    def test_only_detected_clients_connected_and_partial_setup_reported(self):
        self.detected = [dict(assistant='codex', cli_available=True, apps=[])]
        code, _, _ = self.start('--yes'); self.assertEqual(code, 0)
        self.assertFalse((self.repo / '.mcp.json').exists())
        self.assertFalse((self.repo / '.claude/settings.json').exists())
        self.assertEqual(core.config(self.repo)['assistants'], ['codex'])

    def test_detached_head_refuses_before_initialization(self):
        with mock.patch.object(setup, 'branch', return_value=''):
            self.assertEqual(self.start('--yes')[0], 2)
        self.assertFalse((self.repo / 'workspace.json').exists())

    def test_existing_client_config_is_preserved_and_partial_is_reported(self):
        self.detected = [dict(assistant='claude', cli_available=True, apps=[])]
        path = self.repo / '.mcp.json'; path.write_text('{"mcpServers":{"user":{"command":"synthetic"}}}')
        before = path.read_bytes()
        code, output, preview = self.start('--yes')
        self.assertEqual(code, 2); self.assertIn('Partial setup:', output)
        self.assertIn('conflict', preview.lower()); self.assertEqual(path.read_bytes(), before)

    def test_preserved_hook_settings_report_partial_even_when_mcp_connects(self):
        self.detected = [dict(assistant='claude', cli_available=True, apps=[])]
        path = self.repo / '.claude/settings.json'; path.parent.mkdir()
        path.write_text('{"hooks":{"SessionStart":[]}}')
        before = path.read_bytes()
        code, output, _ = self.start('--yes')
        self.assertEqual(code, 2); self.assertIn('Partial setup:', output)
        self.assertEqual(path.read_bytes(), before)
