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
        detection = mock.patch('ws.setup.detect', return_value=[]); detection.start(); self.addCleanup(detection.stop)

    def start(self, *args):
        output = io.StringIO(); preview = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(preview): result = cli.main(['start', *args])
        return result, output.getvalue(), preview.getvalue().replace(os.sep, '/')

    def test_preview_confirmation_external_memory_repeat_and_undo(self):
        before = (self.repo / '.git/info/exclude').read_bytes()
        code, _, preview = self.start('--dry-run')
        self.assertEqual(code, 0); self.assertIn('CLAUDE.local.md', preview); self.assertIn('.claude/settings.local.json', preview)
        self.assertIn((self.home / '.ai-dev-workspace/repo').resolve().as_posix(), preview)
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
        core.checkpoint(workspace, task['id'], 'in_progress', 'Continue the saved next action')
        subprocess.run(['git', 'checkout', '-q', '--detach'], check=True)
        code, output, _ = self.start('--undo')
        self.assertEqual(code, 0); self.assertIn('Removed repo wiring', output)
        self.assertEqual((self.repo / '.git/info/exclude').read_bytes(), before)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.repo), b'')
        self.assertTrue((workspace / 'workspace.json').exists())
        subprocess.run(['git', 'checkout', '-q', 'feature/synthetic'], check=True)
        self.assertEqual(self.start('--yes')[0], 0)
        self.assertIn('Continue the saved next action', core.task_read(workspace, task['id'])['text'])

    def test_existing_local_settings_restored_and_user_edits_kept(self):
        local = self.repo / '.claude/settings.local.json'; local.parent.mkdir()
        local.write_text('{"permissions":{"allow":["Read"]},"hooks":{}}')
        before = local.read_bytes(); self.assertEqual(self.start('--yes')[0], 0)
        link = self.repo / '.ws-start.json'; state = json.loads(link.read_text())
        saved = local.read_bytes(); exclude = state['exclude']; state['exclude'] = str(self.home / 'elsewhere')
        link.write_text(json.dumps(state)); self.assertEqual(self.start('--undo')[0], 2); self.assertEqual(local.read_bytes(), saved)
        state['exclude'] = exclude
        state['exclude'] = str(Path(state['exclude']).parent / '..' / 'info/exclude'); link.write_text(json.dumps(state))
        git_exclude = self.repo / '.git/info/exclude'; original = git_exclude.read_bytes()
        git_exclude.write_bytes(original.replace(b'# /ws:start', b'# user-edited'))
        self.assertEqual(self.start('--undo')[0], 2); self.assertEqual(local.read_bytes(), saved); self.assertTrue(link.exists())
        git_exclude.write_bytes(original)
        (self.repo / '.git/info/exclude').write_bytes((self.repo / '.git/info/exclude').read_bytes() + b'\nuser-pattern\n')
        self.assertEqual(self.start('--undo')[0], 0); self.assertEqual(local.read_bytes(), before)
        self.assertIn(b'user-pattern', (self.repo / '.git/info/exclude').read_bytes())
        self.assertEqual(self.start('--yes')[0], 0); local.unlink()
        self.assertEqual(self.start('--undo')[0], 2); self.assertFalse(local.exists())

    def test_readable_branch_id_has_no_saved_placeholder_next(self):
        self.assertEqual(self.start('--yes')[0], 0)
        root = core.find_root(); task = core.task_list(root)[0]
        self.assertEqual(task['id'], 'feature-synthetic')
        record = core.task_read(root, task['id'], ['Next action'])
        self.assertEqual(record['sections']['Next action'], '')
        self.assertEqual(int(record['meta'].get('checkpoint_count', 0)), 0)
        self.assertIn('Next action: Not saved yet', core.brief(root))
        core.remember(root, 'keep amber')
        self.assertIn('keep amber', core.brief(root))

    def test_readable_id_collision_keeps_existing_record(self):
        root = self.home / '.ai-dev-workspace/repo'
        core.init(root, 'synthetic', repos=[str(self.repo.resolve())], clients=[])
        core.task_new(root, 'feature-synthetic', 'User record', branch='feature/other', repo=str(self.repo.resolve()))
        before = core.task_path(root, 'feature-synthetic').read_bytes()
        self.assertEqual(self.start('--yes')[0], 0)
        tasks = core.task_list(root); self.assertEqual(len(tasks), 2)
        current = next(t for t in tasks if t['branch'] == 'feature/synthetic')
        self.assertRegex(current['id'], r'^feature-synthetic-[0-9a-f]{8}$')
        self.assertEqual(before, core.task_path(root, 'feature-synthetic').read_bytes())

    def test_old_hashed_branch_task_keeps_its_id_and_saved_next(self):
        root = self.home / '.ai-dev-workspace/repo'
        core.init(root, 'synthetic', repos=[str(self.repo.resolve())], clients=[])
        core.task_new(root, 'BR-legacy', 'Legacy branch', branch='feature/synthetic', repo=str(self.repo.resolve()))
        core.claim(root, 'BR-legacy', 'local')
        core.checkpoint(root, 'BR-legacy', 'in_progress', 'Preserve this saved step')
        self.assertEqual(self.start('--yes')[0], 0)
        self.assertEqual([t['id'] for t in core.task_list(root)], ['BR-legacy'])
        self.assertIn('Preserve this saved step', core.brief(root))

    def test_repeat_status_uses_this_repo_and_portable_names_are_bounded(self):
        from ws import repo
        self.assertEqual(self.start('--yes')[0], 0)
        root = core.find_root(); task = core.task_list(root)[0]['id']
        core.task_new(root, 'AAA', 'Other repo task', branch='feature/synthetic', repo=str(self.home / 'other-repo'))
        self.assertIn('Next: task ' + task, self.start('--yes')[1])
        self.assertEqual(repo.branch_task(root, self.repo.resolve(), 'CON'), 'branch-CON')
        self.assertEqual(repo.branch_task(root, self.repo.resolve(), '测试'), 'branch')
        self.assertLessEqual(len(repo.branch_task(root, self.repo.resolve(), 'feature/' + 'a' * 100)), 80)

    def test_concurrent_checkpoint_is_not_cleared_during_setup(self):
        original = core.claim
        template = core.section((core.KIT / 'template/vault/Templates/Task.md').read_text(), 'Next action')
        def claim_then_checkpoint(root, task, worker):
            result = original(root, task, worker)
            core.checkpoint(root, task, 'ready', template)
            return result
        with mock.patch.object(core, 'claim', side_effect=claim_then_checkpoint):
            self.assertEqual(self.start('--yes')[0], 0)
        record = core.task_read(core.find_root(), 'feature-synthetic', ['Next action'])
        self.assertEqual(record['sections']['Next action'], template)
        self.assertEqual(record['meta']['checkpoint_count'], '1')

    def test_detached_tracked_targets_and_workspace_collision_fail_before_writes(self):
        with mock.patch('ws.repo.subprocess.run', side_effect=subprocess.TimeoutExpired('git', 10)):
            self.assertEqual(self.start('--yes')[0], 2)
        self.assertFalse((self.repo / '.ws-start.json').exists())
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
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')

    def test_interrupted_setup_reports_partial_and_can_be_undone(self):
        with mock.patch('ws.repo.record_file', side_effect=OSError('fixture interrupted write')):
            self.assertEqual(self.start('--yes')[0], 2)
        code, output, _ = self.start('--yes')
        self.assertEqual(code, 2); self.assertIn('Partial setup', output)
        self.assertEqual(self.start('--undo')[0], 0)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')
        self.assertEqual(self.start('--yes')[0], 0)

    def test_detected_secondary_clients_share_confirmation_and_private_undo(self):
        detected = [dict(assistant=c, cli_available=True, apps=[]) for c in ('cursor', 'copilot', 'gemini')]
        with mock.patch('ws.setup.detect', return_value=detected), mock.patch('builtins.input', return_value='y') as ask:
            code, output, preview = self.start()
        ask.assert_called_once(); self.assertEqual(code, 0)
        self.assertIn('normally shared', preview); self.assertIn('local VS Code', preview)
        for name, event in (('.cursor/hooks.json', 'sessionStart'), ('.github/hooks/ws.json', 'SessionStart'), ('.gemini/settings.json', 'SessionStart')):
            hooks = json.loads((self.repo / name).read_text())['hooks']
            self.assertIn(event, hooks); self.assertIn(name, preview)
        for name in ('.cursor/mcp.json', '.vscode/mcp.json', '.github/copilot-instructions.md', '.cursor/rules/ws-current-task.mdc', 'GEMINI.md'):
            self.assertTrue((self.repo / name).exists()); self.assertIn(name, preview)
        self.assertTrue((self.repo / '.cursor/rules/ws-current-task.mdc').read_text().startswith('---\n'))
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')
        self.assertEqual(self.start('--undo')[0], 0)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')
        with mock.patch('ws.setup.detect', return_value=detected): self.assertEqual(self.start('--yes', '--undo', '--dry-run')[0], 2)
