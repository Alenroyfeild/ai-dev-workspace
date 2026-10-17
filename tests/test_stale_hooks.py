import io
import json
import os
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock
from test_ws import Base
from ws import cli, core, repo as repo_setup


class StaleHookTests(Base):
    def started(self):
        repo = self.root.parent / 'app'; repo.mkdir()
        subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
        cwd = os.getcwd(); os.chdir(repo)
        try:  # back out before cleanup: Windows cannot delete the current directory
            with mock.patch('ws.setup.detect', return_value=[]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                repo_setup.start(yes=True)
        finally: os.chdir(cwd)
        return repo, core.find_root(repo)

    def move_kit(self, repo, name='.claude/settings.local.json'):
        file = repo / name
        file.write_text(file.read_text().replace(str(core.KIT), str(repo.parent / 'gone-kit')))
        return file

    def test_healthy_setup_reports_nothing(self):
        repo, root = self.started()
        self.assertEqual(repo_setup.stale_hooks(root), [])
        self.assertNotIn('Hooks point', cli.text_doctor(core.doctor(root)))

    def test_deleted_kit_is_reported_in_doctor(self):
        repo, root = self.started(); self.move_kit(repo)
        gone = str(repo.parent / 'gone-kit' / 'bin/ws')
        self.assertEqual(repo_setup.stale_hooks(root), [{'repo': str(repo.resolve()), 'file': '.claude/settings.local.json', 'missing': gone}])
        text = cli.text_doctor(core.doctor(root))
        self.assertIn('Hooks point to a missing kit or workspace', text); self.assertIn(gone, text); self.assertIn('ws start --undo', text)

    def test_missing_interpreter_and_other_workspace_are_reported(self):
        repo, root = self.started()
        file = repo / '.codex/hooks.json'; file.write_text(file.read_text().replace(core.python_command(), str(repo.parent / 'no-python'), 1))
        other = repo / '.claude/settings.local.json'; other.write_text(other.read_text().replace(str(root), str(repo.parent / 'other-ws')))
        found = {i['file']: i['missing'] for i in repo_setup.stale_hooks(root)}
        self.assertEqual(found['.codex/hooks.json'], str(repo.parent / 'no-python'))
        self.assertEqual(found['.claude/settings.local.json'], str(repo.parent / 'other-ws'))

    def test_users_own_hooks_are_ignored(self):
        repo, root = self.started()
        file = repo / '.claude/settings.local.json'; data = json.loads(file.read_text())
        data['hooks']['PostToolUse'] = [{'hooks': [{'type': 'command', 'command': '/nowhere/lint --fix'}]}]
        file.write_text(json.dumps(data))
        self.assertEqual(repo_setup.stale_hooks(root), [])

    def test_broken_json_does_not_crash_doctor(self):
        repo, root = self.started(); self.move_kit(repo)
        (repo / '.codex/hooks.json').write_text('{not json')
        report = core.doctor(root)
        self.assertEqual([i['file'] for i in report['stale_hooks']], ['.claude/settings.local.json'])
