import contextlib
import io
import os
import unittest
from unittest import mock

from test_ws import Base
from ws import cli, core


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

    def test_hook_with_empty_or_broken_stdin_is_a_clear_error_not_a_json_message(self):
        for stdin in ('', '{bad'):
            code, err = self.ws('brief', '--hook', stdin=stdin)
            self.assertEqual(code, 2)
            self.assertIn('Hook input must be a JSON object', err)
            self.assertNotIn('bug in ws', err)

    def test_undo_guesses_point_to_start_undo(self):
        for word, hint in (('undo', '`ws start --undo`'), ('uninstall', '`ws start --undo`'), ('remove', '`ws start --undo`')):
            err = io.StringIO()
            with contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as raised:
                cli.main([word])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn(hint, err.getvalue())
            self.assertLess(len(err.getvalue().splitlines()), 6, err.getvalue())  # not the 49-command list

    def test_no_claimed_task_errors_say_how_to_get_an_id(self):
        code, err = self.ws('remember', 'use Postgres')
        self.assertEqual(code, 2)
        for text in ('ws task list', 'ws task new <id> "<title>"'): self.assertIn(text, err)
        self.assertIn('ws task new <id> "<title>"', core.brief(self.root))

    def test_checkpoint_defaults_the_id_to_the_only_claimed_task(self):
        code, err = self.ws('checkpoint', '--status', 'in_progress', '--next', 'x')
        self.assertEqual(code, 2); self.assertIn('ws task list', err)  # nothing claimed: same hint as remember
        core.claim(self.root, 'T-1', 'synthetic')
        code, err = self.ws('checkpoint', '--status', 'in_progress', '--next', 'Write the schema.')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(core.task_read(self.root, 'T-1', ['Next action'])['sections']['Next action'], 'Write the schema.')


if __name__ == '__main__':
    unittest.main()
