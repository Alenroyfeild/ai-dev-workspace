import io
import json
import os
import subprocess
import sys
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

    def swap(self, file, old, new):  # hook files are JSON, so Windows backslashes are stored doubled
        esc = lambda v: json.dumps(str(v))[1:-1]
        file.write_text(file.read_text().replace(esc(old), esc(new)))

    def move_kit(self, repo, name='.claude/settings.local.json'):
        file = repo / name
        self.swap(file, core.KIT, repo.parent / 'gone-kit')
        return file

    def test_windows_built_commands_are_parsed_and_dead_paths_found(self):
        repo, root = self.started()
        with mock.patch.object(core, 'WINDOWS', True):
            live = core.command_line([sys.executable, str(core.KIT / 'bin/ws'), '--workspace-root', str(root)]) + ' brief --hook'
            dead = core.command_line([sys.executable, str(repo.parent / 'gone kit' / 'bin' / 'ws'), '--workspace-root', str(root)]) + ' brief --hook'
            self.assertEqual(repo_setup._missing_in_hook(live, root), '')
            self.assertEqual(repo_setup._missing_in_hook(dead, root), str(repo.parent / 'gone kit' / 'bin' / 'ws'))

    def test_healthy_setup_reports_nothing(self):
        repo, root = self.started()
        self.assertEqual(repo_setup.stale_hooks(root), [])
        self.assertNotIn('Hooks point', cli.text_doctor(core.doctor(root)))

    def test_deleted_kit_is_reported_in_doctor(self):
        repo, root = self.started(); self.move_kit(repo)
        gone = str(repo.parent / 'gone-kit' / 'bin' / 'ws')
        found = repo_setup.stale_hooks(root)  # repo may differ by 8.3 short names or case on Windows
        self.assertEqual([(Path(i['repo']).resolve(), i['file'], i['missing']) for i in found], [(repo.resolve(), '.claude/settings.local.json', gone)])
        text = cli.text_doctor(core.doctor(root))
        self.assertIn('Hooks point to a missing kit or workspace', text); self.assertIn(gone, text); self.assertIn('run ws start again in that repo', text)

    def test_missing_interpreter_and_other_workspace_are_reported(self):
        repo, root = self.started()
        file = repo / '.codex/hooks.json'; self.swap(file, core.python_command(), repo.parent / 'no-python')
        self.swap(repo / '.claude/settings.local.json', root, repo.parent / 'other-ws')
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

    def test_plain_rerun_refreshes_hooks_from_a_moved_kit(self):
        import hashlib
        repo, root = self.started(); file = self.move_kit(repo)
        link = repo / '.ws-start.json'; state = json.loads(link.read_text())  # as if the old kit wrote these bytes
        state['files']['.claude/settings.local.json']['sha'] = hashlib.sha256(file.read_bytes()).hexdigest(); link.write_text(json.dumps(state))
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                repo_setup.start(yes=True)
        finally: os.chdir(cwd)
        self.assertEqual(repo_setup.stale_hooks(root), [])
        self.assertIn(json.dumps(str(core.KIT))[1:-1], file.read_text())

    def test_corrupt_start_record_does_not_crash_doctor(self):
        repo, root = self.started()
        (repo / '.ws-start.json').write_text('{not json')
        report = core.doctor(root)
        self.assertEqual((report['stale_hooks'], report['codex_manual_pending']), ([], []))
