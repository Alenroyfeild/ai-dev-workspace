import contextlib
import io
import os
import unittest
from unittest import mock

from test_ws import Base
from ws import cli


class CliErrorTests(Base):
    def ws(self, *args, stdin=''):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()), mock.patch('sys.stdin', io.StringIO(stdin)):
            code = cli.main(['--workspace-root', str(self.root), *args])
        return code, err.getvalue()

    def test_unknown_task_is_named_not_a_file_error(self):
        for args in (('checkpoint', 'nosuch', '--status', 'done', '--next', 'x'), ('claim', 'nosuch'), ('release', 'nosuch')):
            code, err = self.ws(*args)
            self.assertEqual(code, 2)
            self.assertIn('No task nosuch. Create it with `ws task new nosuch "<title>"`.', err)
            self.assertNotIn('Errno', err); self.assertNotIn(str(self.root), err)

    def test_claim_defaults_the_worker_from_windows_username(self):  # Windows sets USERNAME, not USER
        with mock.patch.dict(os.environ, {'USERNAME': 'winuser'}):
            os.environ.pop('USER', None)
            code, err = self.ws('claim', 'nosuch')
        self.assertEqual(code, 2); self.assertIn('No task nosuch.', err)

    def test_note_without_equals_says_the_expected_shape(self):
        code, err = self.ws('checkpoint', 'T-1', '--status', 'in_progress', '--next', 'x', '--note', 'nosplit')
        self.assertEqual(code, 2)
        self.assertIn('--note needs SECTION=TEXT', err); self.assertIn('"nosplit"', err)

    def test_hook_with_empty_or_broken_stdin_fails_open_with_a_clear_note(self):
        for stdin in ('', '{bad'):
            code, err = self.ws('brief', '--hook', stdin=stdin)
            self.assertEqual(code, 0)  # fail open: exit 2 would block the client
            self.assertIn('Hook input must be a JSON object', err)
            self.assertNotIn('bug in ws', err)


if __name__ == '__main__':
    unittest.main()
