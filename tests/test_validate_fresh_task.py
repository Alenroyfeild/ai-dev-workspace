import contextlib
import io
import os
import subprocess
from unittest import mock

from test_ws import Base
from ws import core, repo as repo_setup


class FreshTaskValidateTests(Base):
    def test_fresh_ws_start_is_valid(self):
        repo = self.root.parent / 'app'; repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        subprocess.run(['git', '-c', 'user.name=F', '-c', 'user.email=f@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'i'], cwd=repo, check=True)
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch('ws.setup.detect', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                repo_setup.start(yes=True)
        finally: os.chdir(cwd)  # Windows cannot delete the current directory
        self.assertEqual(core.validate(core.find_root(repo))['errors'], [])

    def test_checkpointed_task_with_empty_next_is_still_flagged(self):
        core.claim(self.root, 'T-1', 'synthetic'); core.checkpoint(self.root, 'T-1', 'in_progress', 'Do it.')
        path = core.task_path(self.root, 'T-1'); text = path.read_text()
        path.write_text(core.set_section(text, 'Next action', ''))
        self.assertIn('T-1.md: empty Next action', core.validate(self.root)['errors'])

    def test_task_file_with_an_invalid_id_name_is_reported_not_silently_hidden(self):
        (self.root / 'vault/Tasks/my task.md').write_text(core.task_path(self.root, 'T-1').read_text().replace('id: T-1', 'id: my task'))
        self.assertEqual(['T-1'], [t['id'] for t in core.task_list(self.root)])
        errors = core.validate(self.root)['errors']
        self.assertEqual(1, len(errors)); self.assertIn('my task.md: task file hidden', errors[0])
