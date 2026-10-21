import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core, repo as repo_setup


class PluginDuplicateTests(Base):
    def started_repo(self):
        repo = self.root.parent / 'app'; repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        subprocess.run(['git', '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'i'], cwd=repo, check=True)
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                repo_setup.start(yes=True)
        finally: os.chdir(cwd)  # Windows cannot delete the current directory
        return repo, core.find_root(repo)

    def enable(self, path, value=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text()) if path.is_file() else {}
        data['enabledPlugins'] = {repo_setup.PLUGIN: value}
        path.write_text(json.dumps(data))

    def test_no_plugin_no_warning(self):
        repo, root = self.started_repo()
        self.assertEqual(repo_setup.plugin_duplicates(root), [])
        self.assertEqual(core.doctor(root)['claude_plugin_duplicates'], [])

    def test_user_scope_plugin_with_repo_hooks_is_reported(self):
        repo, root = self.started_repo()
        self.enable(Path.home() / '.claude/settings.json')
        self.assertEqual(core.doctor(root)['claude_plugin_duplicates'], [str(repo.resolve())])
        self.assertIn('plugin and ws start hooks both active', cli.text_doctor(core.doctor(root)))

    def test_local_scope_false_overrides_user_true(self):
        repo, root = self.started_repo()
        self.enable(Path.home() / '.claude/settings.json')
        self.enable(repo / '.claude/settings.local.json', False)
        self.assertFalse(repo_setup.claude_plugin_enabled(repo))
        self.assertEqual(repo_setup.plugin_duplicates(root), [])

    def test_broken_settings_are_ignored(self):
        repo, _ = self.started_repo()
        (Path.home() / '.claude').mkdir(parents=True, exist_ok=True)
        (Path.home() / '.claude/settings.json').write_text('{not json')
        self.assertFalse(repo_setup.claude_plugin_enabled(repo))

    def test_start_leaves_claude_to_an_enabled_plugin(self):
        self.enable(Path.home() / '.claude/settings.json')
        repo, root = self.started_repo()
        state = json.loads((repo / '.ws-start.json').read_text())
        self.assertNotIn('.claude/settings.local.json', state['files'])
        self.assertNotIn('.mcp.json', state['files'])
        self.assertIn('.codex/hooks.json', state['files'])  # other clients keep their wiring
        self.assertTrue((repo / 'CLAUDE.local.md').is_file())
        self.assertEqual(repo_setup.plugin_duplicates(root), [])

    def test_start_output_names_the_plugin(self):
        self.enable(Path.home() / '.claude/settings.json')
        repo = self.root.parent / 'app2'; repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        subprocess.run(['git', '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'i'], cwd=repo, check=True)
        cwd = os.getcwd(); os.chdir(repo); out = io.StringIO()
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                cli.main(['start', '--yes'])
        finally: os.chdir(cwd)
        self.assertIn('assistants: codex, claude (plugin)', out.getvalue())

    def test_dry_run_after_enabling_the_plugin_still_warns_about_two_briefs(self):
        repo, root = self.started_repo()  # set up before the plugin existed, so ws start's Claude hooks are in place
        self.enable(Path.home() / '.claude/settings.json')
        cwd = os.getcwd(); os.chdir(repo); err = io.StringIO()
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                cli.main(['start', '--dry-run'])
        finally: os.chdir(cwd)
        self.assertIn('Claude Code plugin is also enabled, so Claude gets two briefs per session', err.getvalue())
        self.assertIn(str(repo.resolve() / '.mcp.json'), err.getvalue())  # the preview names what the rerun would take out

    def test_corrupt_start_record_is_skipped(self):
        repo, root = self.started_repo()
        self.enable(Path.home() / '.claude/settings.json')
        (repo / '.ws-start.json').write_text('{not json')
        self.assertEqual(repo_setup.plugin_duplicates(root), [])

    def start_here(self, repo, *args):
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                return cli.main(['start', '--yes', *args])
        finally: os.chdir(cwd)

    def test_plugin_start_keeps_opted_in_pack_hooks_but_not_memory_hooks(self):
        repo, root = self.started_repo()
        core.pack_add(root, 'guards'); core.pack_add(root, 'discipline')
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.enable(Path.home() / '.claude/settings.json')
        self.assertEqual(self.start_here(repo), 0)
        state = json.loads((repo / '.ws-start.json').read_text())
        self.assertIn('.claude/settings.local.json', state['files'])
        self.assertNotIn('.mcp.json', state['files'])  # the plugin brings the MCP server
        hooks = json.loads((repo / '.claude/settings.local.json').read_text())['hooks']
        self.assertEqual(sorted(hooks), ['PostToolUseFailure', 'PreToolUse'])  # no duplicated brief/nudge/paste hooks
        self.assertEqual(repo_setup.plugin_duplicates(root), [])
        self.assertEqual(repo_setup.stale_hooks(root), [])
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertFalse((repo / '.claude/settings.local.json').exists())

    def state(self, repo):
        return json.loads((repo / '.ws-start.json').read_text())

    def hooks(self, repo):
        return json.loads((repo / '.claude/settings.local.json').read_text()).get('hooks', {})

    def excluded(self, repo):
        return (repo / '.git/info/exclude').read_text()

    def test_packs_added_after_plugin_first_setup_install_their_hooks(self):
        self.enable(Path.home() / '.claude/settings.json')
        repo, root = self.started_repo()
        self.assertNotIn('.claude/settings.local.json', self.state(repo)['files'])
        core.pack_add(root, 'guards'); core.pack_add(root, 'discipline')
        self.assertEqual(self.start_here(repo), 0)
        self.assertEqual(sorted(self.hooks(repo)), ['PostToolUseFailure', 'PreToolUse'])
        state = self.state(repo)
        self.assertEqual(state['files']['.claude/settings.local.json']['before'], None)  # recorded like start() does
        self.assertEqual(state['hook_packs'], ['guards', 'discipline'])
        self.assertIn('/.claude/settings.local.json', self.excluded(repo))
        self.assertNotIn('.mcp.json', state['files'])
        self.assertEqual(self.start_here(repo), 0)  # settled: a rerun changes nothing
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertFalse((repo / '.claude').exists())
        self.assertNotIn('ws:start', self.excluded(repo))

    def test_packs_later_keep_the_users_own_claude_settings(self):
        self.enable(Path.home() / '.claude/settings.json')
        repo = self.root.parent / 'app3'; repo.mkdir()
        (repo / '.claude').mkdir()
        mine = json.dumps({'permissions': {'allow': ['Bash(ls)']}})
        (repo / '.claude/settings.local.json').write_text(mine)
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        subprocess.run(['git', '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'i'], cwd=repo, check=True)
        self.assertEqual(self.start_here(repo), 0)
        root = core.find_root(repo)
        core.pack_add(root, 'guards')
        self.assertEqual(self.start_here(repo), 0)
        data = json.loads((repo / '.claude/settings.local.json').read_text())
        self.assertEqual(data['permissions'], {'allow': ['Bash(ls)']})
        self.assertEqual(sorted(data['hooks']), ['PreToolUse'])
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertEqual((repo / '.claude/settings.local.json').read_text(), mine)

    def test_removing_the_packs_again_takes_out_the_only_ws_content(self):
        self.enable(Path.home() / '.claude/settings.json')
        repo, root = self.started_repo()
        core.pack_add(root, 'guards')
        self.assertEqual(self.start_here(repo), 0)
        self.assertEqual(sorted(self.hooks(repo)), ['PreToolUse'])
        cfg = core.config(root); cfg['packs'].remove('guards'); (root / 'workspace.json').write_text(json.dumps(cfg))  # no pack-remove command; edit the config
        self.assertEqual(self.start_here(repo), 0)
        self.assertFalse((repo / '.claude/settings.local.json').exists())
        self.assertNotIn('.claude/settings.local.json', self.state(repo)['files'])
        self.assertEqual(self.state(repo)['hook_packs'], [])
        self.assertEqual(self.start_here(repo, '--undo'), 0)

    def test_enabling_the_plugin_later_drops_ws_claude_memory_wiring_and_keeps_packs(self):
        repo, root = self.started_repo()
        core.pack_add(root, 'guards')
        self.assertEqual(self.start_here(repo), 0)
        self.assertIn('SessionStart', self.hooks(repo))
        self.assertIn('ai-dev-workspace', json.loads((repo / '.mcp.json').read_text())['mcpServers'])
        self.enable(Path.home() / '.claude/settings.json')
        self.assertEqual(self.start_here(repo), 0)
        self.assertEqual(sorted(self.hooks(repo)), ['PreToolUse'])
        self.assertFalse((repo / '.mcp.json').exists())
        state = self.state(repo)
        self.assertNotIn('.mcp.json', state['files']); self.assertTrue(state['plugin'])
        self.assertIn('.codex/hooks.json', state['files']); self.assertTrue((repo / 'CLAUDE.local.md').is_file())
        self.assertEqual(repo_setup.plugin_duplicates(root), [])
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertFalse((repo / '.claude').exists())

    def test_enabling_the_plugin_later_removes_the_whole_file_without_packs(self):
        repo, root = self.started_repo()
        self.enable(Path.home() / '.claude/settings.json')
        self.assertEqual(self.start_here(repo), 0)
        self.assertFalse((repo / '.claude/settings.local.json').exists())
        self.assertEqual(repo_setup.plugin_duplicates(root), [])
        self.assertEqual(self.start_here(repo, '--undo'), 0)

    def test_disabling_the_plugin_restores_ws_claude_wiring(self):
        repo, root = self.started_repo()
        self.enable(Path.home() / '.claude/settings.json')
        self.assertEqual(self.start_here(repo), 0)
        self.enable(Path.home() / '.claude/settings.json', False)
        self.assertEqual(self.start_here(repo), 0)
        self.assertIn('SessionStart', self.hooks(repo))
        self.assertIn('ai-dev-workspace', json.loads((repo / '.mcp.json').read_text())['mcpServers'])
        state = self.state(repo)
        self.assertFalse(state['plugin']); self.assertIn('.mcp.json', state['files'])
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertFalse((repo / '.mcp.json').exists())

    def test_dry_run_lists_the_new_file_and_writes_nothing(self):
        self.enable(Path.home() / '.claude/settings.json')
        repo, root = self.started_repo()
        core.pack_add(root, 'guards')
        cwd = os.getcwd(); os.chdir(repo); err = io.StringIO()
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                cli.main(['start', '--dry-run'])
        finally: os.chdir(cwd)
        self.assertIn(str(repo.resolve() / '.claude/settings.local.json'), err.getvalue())
        self.assertFalse((repo / '.claude').exists())
        self.assertEqual(self.state(repo)['hook_packs'], [])

    def test_a_tracked_claude_settings_file_is_not_created_by_a_rerun(self):
        self.enable(Path.home() / '.claude/settings.json')
        repo, root = self.started_repo()
        (repo / '.claude').mkdir(); (repo / '.claude/settings.local.json').write_text('{}')
        subprocess.run(['git', 'add', '-f', '.claude/settings.local.json'], cwd=repo, check=True)
        core.pack_add(root, 'guards')
        self.assertEqual(self.start_here(repo), 2)  # refused: tracked
        self.assertEqual((repo / '.claude/settings.local.json').read_text(), '{}')

    # --- pre-review fixes: a user-edited file must not freeze the plugin/pack refresh ---

    def edit_local_note(self, repo):
        with (repo / 'CLAUDE.local.md').open('a') as handle: handle.write('\nmy note\n')

    def settings_user(self):
        return Path.home() / '.claude/settings.json'

    def test_kept_file_does_not_block_plugin_off_after_on(self):
        repo, root = self.started_repo()
        self.edit_local_note(repo)
        self.enable(self.settings_user()); self.start_here(repo)
        self.assertFalse((repo / '.claude/settings.local.json').exists())
        self.enable(self.settings_user(), False); self.start_here(repo)
        self.assertIn('SessionStart', self.hooks(repo))
        self.assertIn('ai-dev-workspace', json.loads((repo / '.mcp.json').read_text())['mcpServers'])
        self.assertEqual(self.start_here(repo, '--undo'), 2)  # CLAUDE.local.md stays: it is edited

    def test_kept_file_does_not_block_plugin_on_after_off(self):
        self.enable(self.settings_user())
        repo, root = self.started_repo()
        self.edit_local_note(repo)
        self.enable(self.settings_user(), False); self.start_here(repo)
        self.assertIn('SessionStart', self.hooks(repo))
        self.enable(self.settings_user()); self.start_here(repo)
        self.assertFalse((repo / '.claude/settings.local.json').exists())  # no second brief
        self.assertFalse((repo / '.mcp.json').exists())
        self.assertEqual(repo_setup.plugin_duplicates(root), [])
        self.assertTrue(self.state(repo)['plugin'])

    def test_kept_file_plus_plugin_and_guards_is_not_reported_as_two_briefs(self):
        repo, root = self.started_repo()
        self.edit_local_note(repo)
        core.pack_add(root, 'guards')
        self.enable(self.settings_user()); self.start_here(repo)
        self.assertEqual(sorted(self.hooks(repo)), ['PreToolUse'])
        self.assertEqual(repo_setup.plugin_duplicates(root), [])

    def test_kept_file_does_not_block_pack_removal(self):
        repo, root = self.started_repo()
        self.edit_local_note(repo)
        core.pack_add(root, 'guards'); self.start_here(repo)
        self.assertIn('PreToolUse', self.hooks(repo))
        cfg = core.config(root); cfg['packs'].remove('guards'); (root / 'workspace.json').write_text(json.dumps(cfg))
        self.start_here(repo)
        self.assertNotIn('PreToolUse', self.hooks(repo))

    # --- doctor: plugin switched off after ws start left Claude to it ---

    def test_doctor_warns_when_the_plugin_is_gone_after_start(self):
        self.enable(self.settings_user())
        repo, root = self.started_repo()
        self.assertEqual(repo_setup.plugin_missing(root), [])
        self.settings_user().unlink()
        self.assertEqual(repo_setup.plugin_missing(root), [str(repo.resolve())])
        report = core.doctor(root)
        self.assertEqual(report['claude_plugin_missing'], [str(repo.resolve())])
        self.assertIn('run ws start to restore Claude hooks', cli.text_doctor(report))
        self.start_here(repo)
        self.assertEqual(repo_setup.plugin_missing(root), [])

    # --- a tracked or user-owned MCP file cannot be silently skipped when the plugin goes off ---

    def repo_with(self, name, files):
        repo = self.root.parent / name; repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        for rel, text in files.items(): (repo / rel).write_text(text)
        subprocess.run(['git', 'add', '-f', '.'], cwd=repo, check=True)
        subprocess.run(['git', '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'i'], cwd=repo, check=True)
        return repo

    def test_tracked_mcp_json_refuses_plugin_off_naming_file_and_plugin(self):
        self.enable(self.settings_user())
        repo = self.repo_with('app4', {'.mcp.json': '{"mcpServers": {"t": {"command": "x"}}}'})
        self.assertEqual(self.start_here(repo), 0)
        self.enable(self.settings_user(), False)
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(core.WsError) as caught:
                repo_setup.start(yes=True)
        finally: os.chdir(cwd)
        self.assertIn('.mcp.json', str(caught.exception)); self.assertIn('plugin', str(caught.exception))

    def test_own_workspace_mcp_entry_refuses_plugin_off_naming_file_and_plugin(self):
        self.enable(self.settings_user())
        repo = self.repo_with('app5', {})
        (repo / '.mcp.json').write_text('{"mcpServers": {"ai-dev-workspace": {"command": "mine"}}}')
        self.assertEqual(self.start_here(repo), 0)
        self.enable(self.settings_user(), False)
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(core.WsError) as caught:
                repo_setup.start(yes=True)
        finally: os.chdir(cwd)
        self.assertIn('.mcp.json', str(caught.exception)); self.assertIn('plugin', str(caught.exception))
        self.assertIn('"mine"', (repo / '.mcp.json').read_text())

    # --- git clean -fdx removes the record but not the exclude block ---

    def test_start_after_git_clean_reuses_the_exclude_block_and_undo_works(self):
        repo, root = self.started_repo()
        subprocess.run(['git', 'clean', '-fdxq'], cwd=repo, check=True)
        self.assertFalse((repo / '.ws-start.json').exists())
        self.assertEqual(self.start_here(repo), 0)
        self.assertEqual(self.excluded(repo).count('# ws:start:'), 1)
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertNotIn('ws:start', self.excluded(repo))

    def test_start_after_git_clean_with_a_different_block_leaves_no_old_block(self):
        repo, root = self.started_repo()
        subprocess.run(['git', 'clean', '-fdxq'], cwd=repo, check=True)
        self.enable(self.settings_user())
        self.assertEqual(self.start_here(repo), 0)
        self.assertEqual(self.excluded(repo).count('# ws:start:'), 1)
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertNotIn('ws:start', self.excluded(repo))

    def test_users_own_exclude_lines_survive_a_stale_block_cleanup(self):
        repo, root = self.started_repo()
        exclude = repo / '.git/info/exclude'
        exclude.write_text(exclude.read_text() + 'my-own-ignore\n')
        subprocess.run(['git', 'clean', '-fdxq'], cwd=repo, check=True)
        self.start_here(repo); self.start_here(repo, '--undo')
        self.assertIn('my-own-ignore', exclude.read_text()); self.assertNotIn('ws:start', exclude.read_text())

    def test_a_damaged_stale_block_is_refused_and_user_lines_survive(self):
        repo, root = self.started_repo(); exclude = repo / '.git/info/exclude'
        subprocess.run(['git', 'clean', '-fdxq'], cwd=repo, check=True)
        damaged = exclude.read_text().replace('# /ws:start\n', '') + '\nuser-important-ignore\n# /ws:start\n'
        exclude.write_text(damaged)
        err = io.StringIO()
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertNotEqual(cli.main(['start', '--yes']), 0)
        finally: os.chdir(cwd)
        self.assertIn('exclude', err.getvalue()); self.assertIn('damaged', err.getvalue())
        self.assertEqual(exclude.read_text(), damaged)
        self.assertFalse((repo / '.ws-start.json').exists())

    def test_a_stale_block_next_to_user_lines_only_loses_its_own_lines(self):
        repo, root = self.started_repo(); exclude = repo / '.git/info/exclude'
        subprocess.run(['git', 'clean', '-fdxq'], cwd=repo, check=True)
        exclude.write_text('before-ignore\n' + exclude.read_text() + 'after-ignore\n')
        self.assertEqual(self.start_here(repo), 0)
        text = exclude.read_text()
        self.assertIn('before-ignore', text); self.assertIn('after-ignore', text); self.assertEqual(text.count('# ws:start:'), 1)

    # --- ws stops owning a file: it leaves the exclude block ---

    def test_a_file_ws_no_longer_owns_leaves_the_exclude_block(self):
        repo, root = self.started_repo()
        self.assertIn('/.mcp.json', self.excluded(repo).splitlines())
        self.enable(self.settings_user())
        self.assertEqual(self.start_here(repo), 0)
        self.assertNotIn('/.mcp.json', self.excluded(repo).splitlines())
        (repo / '.mcp.json').write_text('{"mcpServers": {"user-server": {"command": "example"}}}')
        self.assertNotEqual(subprocess.run(['git', 'check-ignore', '-q', '.mcp.json'], cwd=repo).returncode, 0)  # the user's file shows in git status
        self.assertEqual(self.start_here(repo, '--undo'), 0)  # undo still finds the shrunk block
        self.assertNotIn('ws:start', self.excluded(repo))

    # --- environment quirks ---

    def test_a_bom_in_settings_does_not_hide_the_plugin(self):
        repo, root = self.started_repo()
        path = self.settings_user(); path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'\xef\xbb\xbf' + json.dumps({'enabledPlugins': {repo_setup.PLUGIN: True}}).encode())
        self.assertTrue(repo_setup.claude_plugin_enabled(repo))

    def test_a_bom_in_a_hook_file_does_not_hide_stale_hooks(self):
        repo, root = self.started_repo()
        path = repo / '.claude/settings.local.json'
        data = json.loads(path.read_text())  # decoded: raw JSON text doubles Windows backslashes
        for groups in data['hooks'].values():
            for group in groups:
                for hook in group['hooks']: hook['command'] = hook['command'].replace(str(core.KIT), str(core.KIT) + '-moved')
        path.write_bytes(b'\xef\xbb\xbf' + json.dumps(data).encode())
        self.assertTrue(repo_setup.stale_hooks(root))

    def test_claude_config_dir_is_honoured_for_user_settings(self):
        repo, root = self.started_repo()
        elsewhere = Path(self.tmp.name) / 'claude-config'
        self.enable(elsewhere / 'settings.json')
        self.assertFalse(repo_setup.claude_plugin_enabled(repo))
        with mock.patch.dict(os.environ, CLAUDE_CONFIG_DIR=str(elsewhere)):
            self.assertTrue(repo_setup.claude_plugin_enabled(repo))

    def test_crlf_exclude_file_still_refreshes_and_undoes(self):
        self.enable(self.settings_user())
        repo, root = self.started_repo()
        exclude = repo / '.git/info/exclude'
        exclude.write_bytes(exclude.read_bytes().replace(b'\n', b'\r\n'))
        self.enable(self.settings_user(), False)
        self.assertEqual(self.start_here(repo), 0)
        self.assertIn('SessionStart', self.hooks(repo))
        self.assertEqual(self.start_here(repo, '--undo'), 0)
        self.assertNotIn('ws:start', exclude.read_text())

    def test_two_briefs_note_ignores_another_repo(self):
        repo, root = self.started_repo()  # started before the plugin, so it really has two briefs
        other = self.repo_with('other', {'f': 'x'})
        cfg = core.config(root); cfg['repos'].append(str(other.resolve())); (root / 'workspace.json').write_text(json.dumps(cfg))
        self.enable(self.settings_user())
        self.assertEqual(repo_setup.plugin_duplicates(root, only=other), [])
        self.assertEqual(repo_setup.plugin_duplicates(root, only=repo), [str(repo.resolve())])
        cwd = os.getcwd(); os.chdir(other); err = io.StringIO()
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                cli.main(['start', '--yes', '--no-import', '--workspace', str(root)])
        finally: os.chdir(cwd)
        self.assertNotIn('two briefs', err.getvalue())
