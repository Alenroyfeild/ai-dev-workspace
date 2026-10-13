import contextlib
import base64
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

    def test_codex_project_config_backed_up_and_legacy_connect_preserved(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'model = "fixture"\n[mcp_servers.other]\ncommand = "other"\n'
        config.write_bytes(original)
        self.assertEqual(self.start('--yes')[0], 0)
        self.assertEqual(config.with_name('config.toml.ws-backup').read_bytes(), original)
        workspace = core.find_root(); self.assertTrue(core.client_connected(workspace, 'codex'))
        self.assertIn('[mcp_servers.other]', config.read_text()); self.assertFalse((self.home / '.codex').exists())
        with mock.patch('ws.core.Path.cwd', return_value=workspace): self.assertTrue(core.connect(workspace, 'codex', write=True)['connected'])
        self.assertTrue((self.home / '.codex/config.toml').exists())
        config.write_text('[mcp_servers.ai-dev-workspace]\ncommand="wrong"\nargs=[]\n')
        self.assertFalse(core.client_connected(workspace, 'codex'))
        config.write_bytes(original + ('\n' + core.codex_mcp_config(workspace)).encode())
        self.assertEqual(self.start('--undo')[0], 0); self.assertEqual(config.read_bytes(), original)
        self.assertFalse(config.with_name('config.toml.ws-backup').exists())

    def test_codex_start_allows_unrelated_servers_in_parent_table(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'model = "fixture"\n[mcp_servers]\nother = { command = "other" }\n'
        config.write_bytes(original)
        self.assertEqual(self.start('--yes')[0], 0)
        self.assertIn('[mcp_servers.ai-dev-workspace]', config.read_text())
        self.assertIn('other = { command = "other" }', config.read_text())

    def test_codex_start_allows_mcp_servers_key_inside_unrelated_table(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = '[other]\nmcp_servers = { note = "unrelated" }\n'
        config.write_text(original)
        self.assertEqual(self.start('--yes')[0], 0)
        self.assertIn(original, config.read_text())
        self.assertIn('[mcp_servers.ai-dev-workspace]', config.read_text())

    def test_codex_start_rejects_duplicate_server_in_parent_table(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        for original in (b'[mcp_servers]\nai-dev-workspace = { command = "other" }\n',
                         b'[mcp_servers]\nai-dev-workspace.command = "other"\n'):
            with self.subTest(original=original):
                config.write_bytes(original)
                self.assertEqual(self.start('--yes')[0], 2)
                self.assertEqual(config.read_bytes(), original)

    def test_codex_start_rejects_duplicate_server_in_quoted_parent_table(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'["mcp_servers"]\n"ai-dev-workspace" = { command = "other" }\n'
        config.write_bytes(original)
        self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(config.read_bytes(), original)

    def test_codex_start_rejects_nested_workspace_server_table(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'[mcp_servers.ai-dev-workspace.env]\nTOKEN = "fixture"\n'
        config.write_bytes(original)
        self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(config.read_bytes(), original)

    def test_codex_write_installs_global_config_even_when_project_is_connected(self):
        self.assertEqual(self.start('--yes')[0], 0)
        project = self.repo / '.codex/config.toml'
        self.assertTrue(project.is_file())
        with mock.patch.object(Path, 'home', return_value=self.home):
            result = core.connect(core.find_root(), 'codex', write=True)
            self.assertTrue(result['connected'])
            self.assertTrue((self.home / '.codex/config.toml').is_file())

    def test_codex_connection_parses_bracket_in_quoted_args(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root()
        server = dict(command='python3', args=['/tmp/a]b/server.py'])
        with mock.patch('ws.core.mcp_command', return_value=server):
            config = self.repo / '.codex/config.toml'
            config.write_text(core.codex_mcp_config(workspace))
            config.write_text(config.read_text().replace('args = ["/tmp/a]b/server.py"]', 'args = [\n  # fixture comment\n  "/tmp/a]b/server.py", # trailing comment\n]'))
            with mock.patch.object(Path, 'cwd', return_value=self.repo):
                self.assertTrue(core.client_connected(workspace, 'codex'))

    def test_codex_connection_accepts_indented_values_and_honors_indented_disable(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); config = self.repo / '.codex/config.toml'
        block = core.codex_mcp_config(workspace).replace('\nenabled', '\n  enabled').replace('\ncommand', '\n  command').replace('\nargs', '\n  args')
        config.write_text(block)
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertTrue(core.client_connected(workspace, 'codex'))
            config.write_text(block.replace('  enabled = true', '  enabled = false'))
            self.assertFalse(core.client_connected(workspace, 'codex'))

    def test_codex_connection_reads_quoted_field_names(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); config = self.repo / '.codex/config.toml'
        block = core.codex_mcp_config(workspace).replace('enabled = true', '"enabled" = true').replace('command =', '"command" =').replace('args =', '"args" =')
        config.write_text(block)
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertTrue(core.client_connected(workspace, 'codex'))
            config.write_text(block.replace('"enabled" = true', '"enabled" = false'))
            self.assertFalse(core.client_connected(workspace, 'codex'))

    def test_codex_connection_handles_indented_table_and_bounds_its_section(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); config = self.repo / '.codex/config.toml'
        block = core.codex_mcp_config(workspace).replace('[mcp_servers', '  [mcp_servers').replace('\nenabled', '\n  enabled').replace('\ncommand', '\n  command').replace('\nargs', '\n  args')
        config.write_text(block)
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertTrue(core.client_connected(workspace, 'codex'))
            server = core.mcp_command(workspace)
            config.write_text('  [mcp_servers.ai-dev-workspace]\n  enabled = true\n  [mcp_servers.other]\n  command = ' + json.dumps(server['command']) + '\n  args = ' + json.dumps(server['args']) + '\n')
            self.assertFalse(core.client_connected(workspace, 'codex'))

    def test_codex_config_keeps_non_bmp_path_as_valid_unicode(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root()
        server = dict(command='/tmp/🦄/python', args=['/tmp/🦄/server.py'])
        with mock.patch('ws.core.mcp_command', return_value=server):
            config = self.repo / '.codex/config.toml'
            config.write_text(core.codex_mcp_config(workspace))
            self.assertIn('🦄', config.read_text())
            with mock.patch.object(Path, 'cwd', return_value=self.repo):
                self.assertTrue(core.client_connected(workspace, 'codex'))

    def test_undo_keeps_backup_when_user_edits_codex_config(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'model = "fixture"\n'
        config.write_bytes(original)
        self.assertEqual(self.start('--yes')[0], 0)
        backup = config.with_name('config.toml.ws-backup')
        config.write_text(config.read_text() + '# user edit\n')
        self.assertEqual(self.start('--undo')[0], 2)
        self.assertIn('# user edit', config.read_text())
        self.assertEqual(backup.read_bytes(), original)

    def test_undo_keeps_backup_when_generated_codex_config_was_deleted(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'model = "fixture"\n'; config.write_bytes(original)
        self.assertEqual(self.start('--yes')[0], 0)
        backup = config.with_name('config.toml.ws-backup'); config.unlink()
        self.assertEqual(self.start('--undo')[0], 2)
        self.assertEqual(backup.read_bytes(), original)

    def test_start_does_not_overwrite_config_created_during_confirmation(self):
        config = self.repo / '.codex/config.toml'
        def create_config():
            config.parent.mkdir(); config.write_text('model = "created during prompt"\n'); return 'y'
        with mock.patch('builtins.input', side_effect=create_config):
            self.assertEqual(self.start()[0], 2)
        self.assertEqual(config.read_text(), 'model = "created during prompt"\n')
        self.assertFalse((self.repo / '.ws-start.json').exists())

    def old_start(self):
        self.assertEqual(self.start('--yes')[0], 0)
        config = self.repo / '.codex/config.toml'; config.unlink(missing_ok=True)
        link = self.repo / '.ws-start.json'; state = json.loads(link.read_text()); state['files'].pop('.codex/config.toml', None)
        old = base64.b64decode(state['exclude_block']); block = old.replace(b'/.codex/config.toml\n', b'')
        exclude = Path(state['exclude']); exclude.write_bytes(exclude.read_bytes().replace(old, block))
        state['exclude_block'] = base64.b64encode(block).decode(); link.write_text(json.dumps(state))
        return config, exclude

    def test_existing_start_gets_codex_connection_after_one_confirm(self):
        config, _ = self.old_start()
        hooks = (self.repo / '.codex/hooks.json').read_bytes()
        with mock.patch('builtins.input', return_value='n') as ask: self.assertEqual(self.start()[0], 0)
        ask.assert_called_once(); self.assertFalse(config.exists())
        with mock.patch('builtins.input', return_value='y') as ask: self.assertEqual(self.start()[0], 0)
        ask.assert_called_once(); self.assertTrue(core.client_connected(core.find_root(), 'codex'))
        self.assertEqual((self.repo / '.codex/hooks.json').read_bytes(), hooks)
        self.assertEqual(self.start('--undo')[0], 0); self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')

    def test_codex_migration_undo_recovers_interrupted_exclusion_write(self):
        _, exclude = self.old_start(); write = core.atomic_write
        def interrupted(target, data):
            if Path(target).resolve() == exclude.resolve(): raise OSError('fixture interrupted exclude write')
            return write(target, data)
        with mock.patch('ws.repo.core.atomic_write', side_effect=interrupted): self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(self.start('--undo')[0], 0)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')

    def test_new_start_undo_recovers_interrupted_exclusion_write(self):
        exclude = self.repo / '.git/info/exclude'; before = exclude.read_bytes(); write = core.atomic_write
        def interrupted(target, data):
            if Path(target).resolve() == exclude.resolve(): raise OSError('fixture interrupted first exclude write')
            return write(target, data)
        with mock.patch('ws.repo.core.atomic_write', side_effect=interrupted): self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(self.start('--undo')[0], 0); self.assertEqual(exclude.read_bytes(), before)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')

    def test_codex_existing_backup_and_tracked_config_refused_before_writes(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(); config.write_text('model="fixture"\n')
        backup = config.with_name('config.toml.ws-backup'); backup.write_text('Earlier backup\n')
        self.assertEqual(self.start('--yes')[0], 2); self.assertEqual(backup.read_text(), 'Earlier backup\n')
        backup.unlink(); subprocess.run(['git', 'add', '.codex/config.toml'], check=True)
        self.assertEqual(self.start('--yes')[0], 2); self.assertFalse((self.repo / '.ws-start.json').exists())
        self.assertEqual(config.read_text(), 'model="fixture"\n'); self.assertFalse((self.home / '.ai-dev-workspace').exists())

    def test_codex_start_rejects_backup_even_without_config(self):
        backup = self.repo / '.codex/config.toml.ws-backup'; backup.parent.mkdir()
        backup.write_text('Saved user config\n')
        self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(backup.read_text(), 'Saved user config\n')
        self.assertFalse((self.repo / '.ws-start.json').exists())

    def test_codex_start_rechecks_backup_created_during_confirmation(self):
        backup = self.repo / '.codex/config.toml.ws-backup'
        def create_backup():
            backup.parent.mkdir(); backup.write_text('Concurrent backup\n'); return 'y'
        with mock.patch('builtins.input', side_effect=create_backup):
            self.assertEqual(self.start()[0], 2)
        self.assertEqual(backup.read_text(), 'Concurrent backup\n')
        self.assertFalse((self.repo / '.ws-start.json').exists())

    def test_codex_start_refuses_project_config_symlink(self):
        target = self.repo / '.codex/config.toml'; target.parent.mkdir()
        outside = self.home / 'config.toml'; outside.write_text('model = "fixture"\n')
        target.symlink_to(outside)
        self.assertEqual(self.start('--yes')[0], 2)
        self.assertTrue(target.is_symlink())
        self.assertEqual(outside.read_text(), 'model = "fixture"\n')

    def test_migration_refuses_a_link_to_another_workspace(self):
        config, _ = self.old_start(); other = self.home / 'other'; core.init(other, 'other', clients=[])
        link = self.repo / '.ws-start.json'; state = json.loads(link.read_text()); state['workspace'] = str(other); link.write_text(json.dumps(state))
        self.assertEqual(self.start('--yes')[0], 2); self.assertFalse(config.exists()); self.assertEqual(core.task_list(other), [])

    def test_start_refuses_existing_spaced_toml_workspace_keys(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        for text in ('[mcp_servers . ai-dev-workspace]\ncommand="fixture"\n', 'mcp_servers . "ai-dev-workspace" . command="fixture"\n', '["mcp_servers"."ai-dev-workspace"]\ncommand="fixture"\n', '"mcp_servers"."ai-dev-workspace".command="fixture"\n', '"mcp_servers" = { other = { command = "other" } }\n', '[mcp_servers."ai-dev-\\u0077orkspace"]\ncommand="fixture"\n'):
            with self.subTest(text=text):
                config.write_text(text)
                self.assertEqual(self.start('--yes')[0], 2)
                self.assertEqual(config.read_text(), text)
                self.assertFalse((self.repo / '.ws-start.json').exists())
                self.assertFalse((config.parent / 'config.toml.ws-backup').exists())

    def test_migration_keeps_a_config_created_after_confirmation(self):
        config, exclude = self.old_start(); write = core.atomic_write
        def edited(target, data):
            result = write(target, data)
            if Path(target).resolve() == exclude.resolve(): config.write_text('User edit\n')
            return result
        with mock.patch('ws.repo.core.atomic_write', side_effect=edited): self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(config.read_text(), 'User edit\n')

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
