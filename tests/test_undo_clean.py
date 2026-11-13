"""End-to-end removal of a disposable ws start setup."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from testutil import seeded_repo


KIT = Path(__file__).resolve().parents[1]
CLEANUP = ("import pathlib, shutil, subprocess; "
           "repo = pathlib.Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], "
           "encoding='utf-8').strip()).resolve(); "
           "shutil.rmtree(pathlib.Path.home() / '.ai-dev-workspace' / repo.name)")


def snapshot_files(root):
    files = {}
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            files[name] = ('symlink', os.readlink(path))
        elif path.is_file():
            files[name] = ('file', hashlib.sha256(path.read_bytes()).hexdigest())
    return files


class UndoCleanTests(unittest.TestCase):
    def test_start_undo_and_documented_cleanup_leave_no_new_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            home = base / 'home'
            home.mkdir()
            (home / 'unrelated.txt').write_text('Keep this user file.\n', encoding='utf-8')
            project = base / "toy project's"
            project.mkdir()
            seeded_repo(project, 'feature/undo-clean', {'README.md': 'Keep this tracked file.\n'})
            exclude = project / '.git' / 'info' / 'exclude'
            exclude.write_text('user-private-file\n', encoding='utf-8')
            before_home = snapshot_files(home)
            before_repo = snapshot_files(project)
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(('WS_', 'GIT_')) and key not in (
                       'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'GEMINI_CLI_HOME', 'PYTHONPATH')}
            env.update(HOME=str(home), USERPROFILE=str(home), CODEX_HOME=str(home / '.codex'),
                       CLAUDE_CONFIG_DIR=str(home / '.claude'), XDG_CONFIG_HOME=str(home / '.config'),
                       APPDATA=str(home / '.config'), LOCALAPPDATA=str(home / '.local'),
                       PYTHONDONTWRITEBYTECODE='1', WS_OFFLINE='1')
            for args in (('start', '--yes'), ('start', '--undo')):
                run = subprocess.run([sys.executable, str(KIT / 'bin' / 'ws'), *args],
                                     cwd=project, env=env, capture_output=True, text=True, timeout=120)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertTrue((home / '.ai-dev-workspace' / project.name / 'workspace.json').is_file())
            cleanup = CLEANUP
            run = subprocess.run([sys.executable, '-c', cleanup], cwd=project, env=env,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(snapshot_files(project), before_repo)
            self.assertEqual(snapshot_files(home), before_home)
            self.assertIn('python -c "' + CLEANUP + '"',
                          (KIT / 'docs' / 'REPO-START.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
