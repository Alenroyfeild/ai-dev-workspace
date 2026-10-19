"""Bug hunt round 2: doctor reports a broken repo link, guards see ~/$HOME spellings, deep JSON never crashes hooks or digest."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core, guards, repo as repo_setup

KIT = Path(__file__).resolve().parents[1]
DEEP = '[' * 200000 + ']' * 200000


def run(*args, cwd, stdin='', home=None, **env):
    return subprocess.run([sys.executable, *map(str, args)], cwd=cwd, input=stdin, capture_output=True, text=True,
                          env=dict(os.environ, HOME=str(home), USERPROFILE=str(home), WS_OFFLINE='1', **env))


class DoctorBrokenLinkTests(Base):
    def started(self):
        repo = self.root.parent / 'app'; repo.mkdir()
        subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                repo_setup.start(yes=True)
        finally: os.chdir(cwd)
        return repo, core.find_root(repo)

    def doctor_text(self, repo):
        done = run(KIT / 'bin/ws', 'doctor', '--text', cwd=repo, home=self.tmp.name)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_corrupt_repo_link_is_reported(self):
        repo, _ = self.started()
        (repo / '.ws-start.json').write_text('{bad')
        text = self.doctor_text(repo)
        self.assertIn('Needs attention', text)
        self.assertIn('ws start --undo', text)

    def test_corrupt_workspace_json_is_reported_from_a_started_repo(self):
        repo, root = self.started()
        for bad in ('{bad', '', '[]'):
            (root / 'workspace.json').write_text(bad)
            with self.subTest(bad=bad): self.assertIn('Needs attention', self.doctor_text(repo))

    def test_corrupt_workspace_json_in_the_workspace_itself_is_reported(self):
        (self.root / 'workspace.json').write_text('[]')
        done = run(KIT / 'bin/ws', 'doctor', '--text', cwd=self.root, home=self.tmp.name)
        self.assertNotIn('Traceback', done.stderr)
        self.assertIn('Needs attention', done.stdout)

    def test_json_report_carries_the_error_and_no_workspace_stays_quiet(self):
        repo, _ = self.started()
        (repo / '.ws-start.json').write_text('{bad')
        self.assertIn('workspace_error', json.loads(run(KIT / 'bin/ws', 'doctor', cwd=repo, home=self.tmp.name).stdout))
        plain = Path(self.tmp.name) / 'nothing'; plain.mkdir()
        # no workspace at all is not a broken link (ws doctor may still say 'no workspace found')
        self.assertNotIn('workspace_error', json.loads(run(KIT / 'bin/ws', 'doctor', cwd=plain, home=self.tmp.name).stdout))

    def test_session_start_with_corrupt_workspace_json_does_not_blame_team_pull(self):
        (self.root / 'workspace.json').write_text('{bad')
        from ws import team_auto
        self.assertIsNone(team_auto.maybe_pull(self.root))

    def test_session_start_with_deeply_nested_workspace_json_fails_open(self):
        (self.root / 'workspace.json').write_text('{"team_workspace":' + '[' * 5000 + '0' + ']' * 5000 + '}')
        from ws import team_auto
        result = team_auto.maybe_pull(self.root)  # contract: no exception; decoders differ (3.12+ parses it, older ones overflow)
        self.assertTrue(result is None or isinstance(result, dict) and 'error' not in result and 'Traceback' not in json.dumps(result))


class GuardSpellingTests(unittest.TestCase):
    def deny(self, command, tool='Bash'):
        return guards.reason(tool, {'command': command})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        home = str(Path(self.tmp.name).resolve())
        patch = mock.patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home}); patch.start(); self.addCleanup(patch.stop)

    def test_home_and_root_spellings_are_denied(self):
        for command in ('rm -rf ${HOME}/*', 'rm -rf ~//', 'rm -rf ~/.', 'rm -rf $HOME/.', 'rm -rf $HOME//', 'rm -rf //', 'rm -rf /.',
                        'rm -rf "${HOME}"/*', 'rm -rf ~/./', 'rm -rf $HOME/.*', 'rm -rf ${HOME}//*', 'rm -rf /*'):
            with self.subTest(command): self.assertTrue(self.deny(command))

    def test_subpaths_are_allowed(self):
        for command in ('rm -rf ~/project/build', 'rm -rf $HOME/project/build', 'rm -rf ${HOME}/x/*', 'rm -rf ~/.cache/x',
                        'rm -rf ~/project/.', 'rm -rf /tmp/x', 'rm -rf ./build'):
            with self.subTest(command): self.assertEqual(self.deny(command), '')

    def test_powershell_spellings(self):
        for command in ('Remove-Item -Recurse -Force ${HOME}/*', 'Remove-Item -Recurse -Force ~//', 'Remove-Item -Recurse -Force ~/.',
                        'Remove-Item -Recurse -Force $HOME\\.', 'Remove-Item -Recurse -Force C:\\.', 'Remove-Item -Recurse -Force $env:USERPROFILE\\.'):
            with self.subTest(command): self.assertTrue(guards.reason('PowerShell', {'command': command}))
        for command in ('Remove-Item -Recurse -Force ~/project/build', 'Remove-Item -Recurse -Force $HOME\\old\\.', 'Remove-Item -Recurse -Force C:\\temp\\x'):
            with self.subTest(command): self.assertEqual(guards.reason('PowerShell', {'command': command}), '')


class DeepJsonTests(Base):
    def test_plugin_entrypoint_fails_open(self):
        done = run(KIT / 'bin/ws-plugin', '--client', 'claude', cwd=self.root, stdin=DEEP, home=self.tmp.name)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, '{}'), done.stderr[-300:])
        self.assertNotIn('Traceback', done.stderr)
        self.assertEqual(done.stderr.count('\n'), 1)

    def test_digest_and_paste_report_cleanly(self):
        f = Path(self.tmp.name) / 'deep.json'; f.write_text('[' * 5000 + ']' * 5000)
        for argv, stdin in ((['digest', str(f)], ''), (['paste'], '[' * 5000 + ']' * 5000)):
            with self.subTest(argv[0]):
                done = run(KIT / 'bin/ws', '--workspace-root', self.root, *argv, cwd=self.root, stdin=stdin, home=self.tmp.name)
                self.assertNotIn('Traceback', done.stderr)
                self.assertEqual(done.returncode, 0, done.stderr)

    def test_paste_hook_with_deep_payload_fails_open(self):
        done = run(KIT / 'bin/ws', '--workspace-root', self.root, 'paste', '--hook', cwd=self.root, stdin=DEEP, home=self.tmp.name)
        self.assertEqual((done.returncode, done.stdout.strip()), (0, '{}'), done.stderr[-300:])
        self.assertNotIn('Traceback', done.stderr)


class HelpCommandTests(unittest.TestCase):
    def test_help_for_a_command_shows_its_options(self):
        done = run(KIT / 'bin/ws', 'help', 'checkpoint', cwd=KIT, home=tempfile.gettempdir())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('--status', done.stdout)


if __name__ == '__main__':
    unittest.main()
