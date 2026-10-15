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

    def test_rerun_after_kit_upgrade_hints_refresh_without_rewriting(self):
        self.assertEqual(self.start('--yes')[0], 0)
        link = self.repo / '.ws-start.json'
        self.assertNotIn('older ai-dev-workspace version', self.start()[2])
        state = json.loads(link.read_text()); state['kit_version'] = '0.0.1'; link.write_text(json.dumps(state))
        wiring = (self.repo / 'CLAUDE.local.md').read_bytes()
        code, _, err = self.start()
        self.assertEqual(code, 0)
        self.assertIn('ws start --undo && ws start', err)
        self.assertEqual((self.repo / 'CLAUDE.local.md').read_bytes(), wiring)

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

    def test_correction_instruction_is_written_and_undo_restores_user_text(self):
        instruction = ('When the user corrects an earlier decision, call the MCP `remember` tool '
                       'with the corrected decision, saying what it replaces.')
        originals = {'CLAUDE.local.md': b'Private Claude notes.\n',
                     'AGENTS.override.md': b'Private Codex notes.\n'}
        for name, content in originals.items():
            (self.repo / name).write_bytes(content)
        self.assertEqual(self.start('--yes')[0], 0)
        for name, content in originals.items():
            self.assertTrue((self.repo / name).read_bytes().startswith(content))
            self.assertIn(instruction, (self.repo / name).read_text())
        self.assertEqual(self.start('--undo')[0], 0)
        for name, content in originals.items():
            self.assertEqual((self.repo / name).read_bytes(), content)

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
        self.assertFalse(repo.branch_task(root, self.repo.resolve(), 'a' * 79 + '.tail').endswith('.'))

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

    def test_existing_codex_config_is_manual_and_never_read_or_written(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'not TOML: \xff'; config.write_bytes(original)
        code, output, preview = self.start('--yes')
        self.assertEqual(code, 0); self.assertIn('manual step pending', output)
        self.assertIn(config.resolve().as_posix(), preview); self.assertIn('[mcp_servers.ai-dev-workspace]', preview)
        self.assertEqual(config.read_bytes(), original)
        state = json.loads((self.repo / '.ws-start.json').read_text())
        self.assertEqual(state['codex_status'], 'manual step pending')
        self.assertNotIn('.codex/config.toml', state['files'])
        self.assertIn('manual step pending', cli.text_doctor(core.doctor(core.find_root())))
        self.assertIn('manual step pending', self.start('--yes')[1])
        self.assertEqual(self.start('--undo')[0], 0); self.assertEqual(config.read_bytes(), original)

    def test_old_setup_manual_status_requires_confirmation(self):
        config, _ = self.old_start(); config.write_bytes(b'not TOML')
        record = self.repo / '.ws-start.json'; before = record.read_bytes()
        with mock.patch('builtins.input', return_value='n') as ask: self.start()
        ask.assert_called_once(); self.assertEqual(record.read_bytes(), before)
        self.start('--dry-run'); self.assertEqual(record.read_bytes(), before)

    def test_existing_config_deleted_during_confirmation_stops_setup(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(); config.write_text('user config')
        def deleted(): config.unlink(); return 'y'
        with mock.patch('builtins.input', side_effect=deleted): self.assertEqual(self.start()[0], 2)
        self.assertFalse((self.repo / '.ws-start.json').exists())

    def test_new_codex_config_is_owned_and_undo_removes_it(self):
        self.assertEqual(self.start('--yes')[0], 0)
        config = self.repo / '.codex/config.toml'; workspace = core.find_root()
        self.assertEqual(config.read_text(), core.codex_mcp_config(workspace))
        self.assertTrue(core.client_connected(workspace, 'codex'))
        self.assertFalse(config.with_name('config.toml.ws-backup').exists())
        self.assertEqual(self.start('--undo')[0], 0); self.assertFalse(config.exists())
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')

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

    def test_codex_connection_accepts_trailing_table_comment(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); config = self.repo / '.codex/config.toml'
        config.write_text(core.codex_mcp_config(workspace).replace(']\nenabled', '] # server table\nenabled'))
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertTrue(core.client_connected(workspace, 'codex'))

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

    def test_global_codex_write_refuses_disabled_quoted_workspace_table(self):
        self.assertEqual(self.start('--yes')[0], 0)
        config = self.home / '.codex/config.toml'; config.parent.mkdir()
        config.write_text('["mcp_servers" . "ai-dev-workspace"]\nenabled = false\ncommand = "old"\nargs = []\n')
        before = config.read_bytes()
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            with self.assertRaisesRegex(core.WsError, 'already has a different workspace entry'):
                core._connect_config(core.find_root(), 'codex', write=True)
        self.assertEqual(config.read_bytes(), before)

    def test_global_codex_write_refuses_workspace_entry_in_parent_table(self):
        self.assertEqual(self.start('--yes')[0], 0)
        config = self.home / '.codex/config.toml'; config.parent.mkdir()
        config.write_text('[mcp_servers]\nai-dev-workspace = { enabled = false, command = "old", args = [] }\n')
        before = config.read_bytes()
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            with self.assertRaisesRegex(core.WsError, 'already has a different workspace entry'):
                core._connect_config(core.find_root(), 'codex', write=True)
        self.assertEqual(config.read_bytes(), before)

    def test_project_codex_parent_entry_blocks_global_connected_fallback(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); project = self.repo / '.codex/config.toml'; project.parent.mkdir(exist_ok=True)
        project.write_text('[mcp_servers]\nai-dev-workspace = { enabled = false, command = "other", args = [] }\n')
        global_config = self.home / '.codex/config.toml'; global_config.parent.mkdir()
        global_config.write_text(core.codex_mcp_config(workspace))
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertFalse(core.client_connected(workspace, 'codex'))

    def test_global_codex_write_refuses_quoted_root_server_table(self):
        self.assertEqual(self.start('--yes')[0], 0)
        config = self.home / '.codex/config.toml'; config.parent.mkdir()
        config.write_text('"mcp_servers" = { "ai-dev-workspace" = { enabled = false } }\n')
        before = config.read_bytes()
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            with self.assertRaisesRegex(core.WsError, 'already has a different workspace entry'):
                core._connect_config(core.find_root(), 'codex', write=True)
        self.assertEqual(config.read_bytes(), before)

    def test_global_codex_write_refuses_unicode_escaped_workspace_key(self):
        self.assertEqual(self.start('--yes')[0], 0)
        config = self.home / '.codex/config.toml'; config.parent.mkdir()
        config.write_text('[mcp_servers."ai-dev-\\u0077orkspace"]\nenabled = false\ncommand = "old"\nargs = []\n')
        before = config.read_bytes()
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            with self.assertRaisesRegex(core.WsError, 'already has a different workspace entry'):
                core._connect_config(core.find_root(), 'codex', write=True)
        self.assertEqual(config.read_bytes(), before)

    def test_global_codex_write_finds_workspace_key_after_nested_array_value(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); config = self.home / '.codex/config.toml'; config.parent.mkdir()
        original = 'values = [\n  [1, 2],\n]\nmcp_servers.ai-dev-workspace.command = "other"\n'; config.write_text(original)
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            with self.assertRaisesRegex(core.WsError, 'already has a different workspace entry'):
                core._connect_config(workspace, 'codex', write=True)
        self.assertEqual(config.read_text(), original)

    def test_codex_connection_ignores_fake_table_in_multiline_string(self):
        workspace = self.home / 'ws'; core.init(workspace, 'fixture', repos=[str(self.repo)], clients=[])
        project = self.repo / '.codex/config.toml'; project.parent.mkdir(exist_ok=True)
        project.write_text('note = """\n[mcp_servers.ai-dev-workspace]\ncommand = "other"\nargs = []\n"""\n')
        global_config = self.home / '.codex/config.toml'; global_config.parent.mkdir()
        global_config.write_text(core.codex_mcp_config(workspace))
        with mock.patch.object(Path, 'cwd', return_value=self.repo): self.assertTrue(core.client_connected(workspace, 'codex'))

    def test_codex_connection_preserves_hash_in_literal_command_path(self):
        workspace = self.home / 'ws'; core.init(workspace, 'fixture', repos=[str(self.repo)], clients=[])
        server = {'command': 'tool#path', 'args': ['tool#path']}
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(exist_ok=True)
        config.write_text("[mcp_servers.ai-dev-workspace]\ncommand = 'tool#path'\nargs = ['tool#path']\n")
        with mock.patch('ws.core.mcp_command', return_value=server), mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertTrue(core.client_connected(workspace, 'codex'))

    def test_codex_client_connected_preserves_backslashes_in_toml_literal_strings(self):
        workspace = self.home / 'ws'; core.init(workspace, 'fixture', repos=[str(self.repo)], clients=[])
        server = {'command': r'C:\tmp\tool', 'args': [r'C:\tmp\tool']}
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(exist_ok=True)
        config.write_text("[mcp_servers.ai-dev-workspace]\nenabled = true\ncommand = 'C:\\tmp\\tool'\nargs = ['C:\\tmp\\tool']\n")
        with mock.patch('ws.core.mcp_command', return_value=server), mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertTrue(core.client_connected(workspace, 'codex'))

    def test_codex_client_connected_parses_literal_string_ending_in_backslash(self):
        workspace = self.home / 'ws'; core.init(workspace, 'fixture', repos=[str(self.repo)], clients=[])
        server = {'command': 'tool\\', 'args': ['tool\\']}
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(exist_ok=True)
        config.write_text("[mcp_servers.ai-dev-workspace]\ncommand = 'tool\\'\nargs = ['tool\\']\n")
        with mock.patch('ws.core.mcp_command', return_value=server), mock.patch.object(Path, 'cwd', return_value=self.repo):
            self.assertTrue(core.client_connected(workspace, 'codex'))

    def test_codex_client_connected_rejects_invalid_enabled_value(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); server = core.mcp_command(workspace)
        config = self.repo / '.codex/config.toml'
        config.write_text(core.codex_mcp_config(workspace).replace('enabled = true', 'enabled = "false"'))
        with mock.patch.object(Path, 'cwd', return_value=self.repo): self.assertFalse(core.client_connected(workspace, 'codex'))

    def test_codex_client_connected_parses_final_enabled_scalar_without_newline(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); server = core.mcp_command(workspace)
        config = self.repo / '.codex/config.toml'
        config.write_text('[mcp_servers.ai-dev-workspace]\ncommand = ' + json.dumps(server['command']) + '\nargs = ' + json.dumps(server['args']) + '\nenabled = true')
        with mock.patch.object(Path, 'cwd', return_value=self.repo): self.assertTrue(core.client_connected(workspace, 'codex'))

    def test_global_codex_write_allows_server_key_inside_other_table(self):
        self.assertEqual(self.start('--yes')[0], 0)
        workspace = core.find_root(); config = self.home / '.codex/config.toml'; config.parent.mkdir()
        original = '[other]\nmcp_servers = {}\n'; config.write_text(original)
        with mock.patch.object(Path, 'cwd', return_value=self.repo):
            result = core._connect_config(workspace, 'codex', write=True)
        self.assertTrue(result['connected'])
        self.assertIn('[mcp_servers.ai-dev-workspace]', config.read_text())
        self.assertEqual(config.with_name('config.toml.ws-backup').read_text(), original)

    def test_start_does_not_overwrite_config_created_during_confirmation(self):
        config = self.repo / '.codex/config.toml'
        def create_config():
            config.parent.mkdir(); config.write_text('model = "created during prompt"\n'); return 'y'
        with mock.patch('builtins.input', side_effect=create_config):
            self.assertEqual(self.start()[0], 2)
        self.assertEqual(config.read_text(), 'model = "created during prompt"\n')
        self.assertFalse((self.repo / '.ws-start.json').exists())

    def test_start_does_not_overwrite_record_created_during_confirmation(self):
        record = self.repo / '.ws-start.json'
        def create_record(): record.write_text('{"user": "keep"}\n'); return 'y'
        with mock.patch('builtins.input', side_effect=create_record): self.assertEqual(self.start()[0], 2)
        self.assertEqual(record.read_text(), '{"user": "keep"}\n')

    def old_start(self):
        self.assertEqual(self.start('--yes')[0], 0)
        config = self.repo / '.codex/config.toml'; config.unlink(missing_ok=True)
        link = self.repo / '.ws-start.json'; state = json.loads(link.read_text()); state['files'].pop('.codex/config.toml', None)
        old = base64.b64decode(state['exclude_block']); block = old.replace(b'/.codex/config.toml\n', b'')
        exclude = Path(state['exclude']); exclude.write_bytes(exclude.read_bytes().replace(old, block))
        state['exclude_block'] = base64.b64encode(block).decode(); link.write_text(json.dumps(state))
        return config, exclude

    def test_codex_migration_refuses_tracked_start_record(self):
        self.old_start()
        link = self.repo / '.ws-start.json'
        subprocess.run(['git', 'add', '-f', '.ws-start.json'], check=True)
        before = link.read_bytes()
        self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(link.read_bytes(), before)
        self.assertFalse((self.repo / '.codex/config.toml').exists())

    def test_codex_migration_preserves_record_edited_during_confirmation(self):
        self.old_start()
        link = self.repo / '.ws-start.json'
        def edit_record():
            state = json.loads(link.read_text()); state['concurrent_note'] = 'keep'; link.write_text(json.dumps(state)); return 'y'
        with mock.patch('builtins.input', side_effect=edit_record):
            self.assertEqual(self.start()[0], 2)
        self.assertEqual(json.loads(link.read_text())['concurrent_note'], 'keep')
        self.assertFalse((self.repo / '.codex/config.toml').exists())

    def test_start_rechecks_tracked_targets_after_confirmation(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir()
        original = b'model = "fixture"\n'; config.write_bytes(original)
        def track_config():
            (self.repo / 'AGENTS.override.md').write_text('Tracked concurrently\n')
            subprocess.run(['git', 'add', 'AGENTS.override.md'], check=True); return 'y'
        with mock.patch('builtins.input', side_effect=track_config):
            self.assertEqual(self.start()[0], 2)
        self.assertEqual(config.read_bytes(), original)
        self.assertFalse((self.repo / '.ws-start.json').exists())

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

    def test_new_start_undo_recovers_when_partial_exclude_line_preexisted(self):
        exclude = self.repo / '.git/info/exclude'; before = b'/.ws-start.json\n'
        exclude.write_bytes(before); write = core.atomic_write
        def interrupted(target, data):
            if Path(target).resolve() == exclude.resolve():
                exclude.write_bytes(data[:data.find(b'/CLAUDE.local.md')])
                raise OSError('fixture interrupted first exclude write')
            return write(target, data)
        with mock.patch('ws.repo.core.atomic_write', side_effect=interrupted): self.assertEqual(self.start('--yes')[0], 2)
        self.assertEqual(self.start('--undo')[0], 0)
        self.assertEqual(exclude.read_bytes(), before)
        self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain']), b'')

    def test_start_keeps_existing_tracked_codex_config_and_backup(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(); config.write_text('model="fixture"\n')
        backup = config.with_name('config.toml.ws-backup'); backup.write_text('Earlier backup\n')
        subprocess.run(['git', 'add', '.codex/config.toml'], check=True)
        self.assertEqual(self.start('--yes')[0], 0)
        self.assertEqual(config.read_text(), 'model="fixture"\n'); self.assertEqual(backup.read_text(), 'Earlier backup\n')
        self.assertEqual(self.start('--undo')[0], 0)
        self.assertEqual(config.read_text(), 'model="fixture"\n'); self.assertEqual(backup.read_text(), 'Earlier backup\n')

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

    def test_global_codex_connection_skips_manual_paste_and_project_creation(self):
        config = self.repo / '.codex/config.toml'; config.parent.mkdir(); original = b'not TOML: \xff'; config.write_bytes(original)
        self.assertEqual(self.start('--yes')[0], 0); root = core.find_root()
        global_config = self.home / '.codex/config.toml'; global_config.parent.mkdir()
        global_config.write_text(core.codex_mcp_config(root)); global_before = global_config.read_bytes()
        code, output, preview = self.start('--yes')
        self.assertEqual(code, 0); self.assertIn('connected via global config', output)
        self.assertNotIn('manual step pending', output + preview); self.assertNotIn('[mcp_servers', preview)
        report = core.doctor(root); self.assertTrue(report['configured_clients']['codex'])
        self.assertEqual(report['codex_manual_pending'], []); self.assertNotIn('manual step pending', cli.text_doctor(report))
        self.assertEqual(config.read_bytes(), original); self.assertEqual(self.start('--undo')[0], 0)
        config.unlink(); code, output, preview = self.start('--yes')
        self.assertEqual(code, 0); self.assertIn('connected via global config', output); self.assertFalse(config.exists())
        self.assertEqual(global_config.read_bytes(), global_before)
        global_config.unlink(); config.write_text(core.codex_mcp_config(root))
        self.assertTrue(core.client_connected(root, 'codex'))
        config.unlink(); self.assertEqual(self.start('--undo')[0], 0)
