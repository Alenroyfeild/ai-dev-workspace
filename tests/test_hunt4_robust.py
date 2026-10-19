import contextlib
import io
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core, repo as wsrepo


class Hunt4RobustTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve(); self.home = self.base / 'home'; self.home.mkdir()
        self.repo = self.base / 'repo'; self.repo.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'), WS_OFFLINE='1', WS_ROOT='')
        patch.start(); self.addCleanup(patch.stop)
        self.git('init', '-q', '-b', 'feature/synthetic')
        self.git('-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture')
        self.old = Path.cwd(); os.chdir(self.repo); self.addCleanup(os.chdir, self.old)
        detection = mock.patch('ws.setup.detect', return_value=[]); detection.start(); self.addCleanup(detection.stop)

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.repo), *args], check=True, capture_output=True)

    def ws(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def started(self):
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        root = core.find_root(self.repo)
        return root, wsrepo.branch_task(root, self.repo, 'feature/synthetic')

    # A: relinking a moved repo keeps its task records

    def test_move_rewrites_repo_of_this_repos_records_only(self):
        root, task = self.started()
        self.assertEqual(core.task_read(root, task, ['Objective'])['meta']['repo'], str(self.repo))
        core.task_new(root, 'elsewhere', 'Other repo', repo='/not/this/repo')
        os.chdir(self.base); moved = self.base / 'moved'; self.repo.rename(moved); os.chdir(moved); self.repo = moved
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        self.assertEqual(core.task_read(root, task, ['Objective'])['meta']['repo'], str(moved))
        self.assertEqual(core.task_read(root, 'elsewhere', ['Objective'])['meta']['repo'], '/not/this/repo')
        self.assertEqual(wsrepo.branch_task(root, moved, 'feature/synthetic'), task)  # no duplicate task is suggested

    def test_copy_leaves_the_original_repos_records_alone(self):
        root, task = self.started()
        original = self.repo; copy = self.base / 'copy'
        os.chdir(self.base); shutil.copytree(original, copy); os.chdir(copy); self.repo = copy
        self.assertEqual(self.ws('start', '--yes')[0], 0)
        self.assertEqual(core.task_read(root, task, ['Objective'])['meta']['repo'], str(original))

    # B: odd bytes and unwritable files give clear errors, never a traceback

    def test_non_utf8_task_file_does_not_crash_read_commands(self):
        root, task = self.started()
        with core.task_path(root, task).open('ab') as stream: stream.write(b'\xff\xfe\x80 junk\n')
        for command in (['brief'], ['recap'], ['task', 'list']):
            code, _, err = self.ws(*command)
            self.assertEqual(code, 0, (command, err))

    def test_non_utf8_task_file_write_gives_clear_error(self):
        root, task = self.started()
        with core.task_path(root, task).open('ab') as stream: stream.write(b'\xff\xfe\x80 junk\n')
        code, _, err = self.ws('checkpoint', task, '--status', 'in_progress', '--next', 'n')
        self.assertEqual(code, 2); self.assertTrue(err.startswith('ws: ')); self.assertNotIn('Traceback', err)

    def test_non_utf8_learnings_file_does_not_crash_lesson_search(self):
        root, _ = self.started()
        (root / 'vault' / 'Learnings.md').write_bytes(b'- 2026-01-01 old \xff lesson #t\n')
        code, out, err = self.ws('lesson', 'search', 'lesson')
        self.assertEqual(code, 0, err); self.assertIn('lesson', out)
        self.assertEqual(self.ws('brief')[0], 0)

    def test_learnings_that_is_a_directory_gives_clear_error(self):
        root, _ = self.started()
        learnings = root / 'vault' / 'Learnings.md'
        if learnings.exists(): learnings.unlink()
        learnings.mkdir()
        code, _, err = self.ws('lesson', 'add', 'a lesson that cannot be saved')
        self.assertEqual(code, 2); self.assertTrue(err.startswith('ws: ')); self.assertNotIn('Traceback', err)
        self.assertEqual(len(err.strip().splitlines()), 1, err)

    @unittest.skipIf(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0), 'needs POSIX permissions and a non-root user')
    def test_read_only_vault_directory_gives_clear_error(self):
        root, _ = self.started()
        vault = root / 'vault'; mode = vault.stat().st_mode
        vault.chmod(stat.S_IRUSR | stat.S_IXUSR); self.addCleanup(vault.chmod, mode)
        code, _, err = self.ws('lesson', 'add', 'a lesson under a read-only vault')
        self.assertEqual(code, 2); self.assertTrue(err.startswith('ws: ')); self.assertNotIn('Traceback', err)

    def test_os_error_without_a_path_keeps_its_own_message(self):
        self.started()
        with mock.patch('ws.core.lesson_add', side_effect=OSError('launchd registration failed')):
            code, _, err = self.ws('lesson', 'add', 'any lesson')
        self.assertEqual(code, 2); self.assertIn('launchd registration failed', err); self.assertNotIn('Cannot read or write', err)

    # C: ws pack add before ws start

    def test_pack_add_before_start_says_to_run_start_first(self):
        code, _, err = self.ws('pack', 'add', 'guards')
        self.assertEqual(code, 2)
        self.assertIn('`ws start` first', err); self.assertIn('ws pack add guards', err)
        self.assertFalse((self.repo / '.ws-start.json').exists())


if __name__ == '__main__':
    unittest.main()
