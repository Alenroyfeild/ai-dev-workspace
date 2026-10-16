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
