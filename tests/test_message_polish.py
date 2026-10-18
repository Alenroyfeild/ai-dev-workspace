import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core

CLI = Path(__file__).resolve().parents[1] / 'bin/ws'


class MessagePolishTests(Base):
    def ws(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch('sys.stdin', io.StringIO('')):
            code = cli.main(['--workspace-root', str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_mistyped_command_gets_a_short_hint_not_every_command_name(self):
        result = subprocess.run([sys.executable, str(CLI), 'frobnicate'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ws: unknown command 'frobnicate'. Run ws --help", result.stderr)
        self.assertNotIn('choose from', result.stderr)
        result = subprocess.run([sys.executable, str(CLI), 'pack', 'lisst'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ws pack: unknown choice 'lisst'. Choose from: add, remove", result.stderr)
        result = subprocess.run([sys.executable, str(CLI), 'statuss'], text=True, capture_output=True)
        self.assertIn("ws: unknown command 'statuss'; did you mean: status, start? Run ws --help", result.stderr)

    def test_doctor_text_has_no_empty_parens_and_reads_the_capture_state(self):
        text = cli.text_doctor({'setup': {'preset': 'not selected', 'assistants': []},
                                'capture_health': {'outcome': 'not_run', 'reason': 'not_run'}, 'configured_clients': {'claude': True}})
        self.assertIn('Setup preset: not selected\n', text + '\n')
        self.assertNotIn('()', text)
        self.assertIn('Last capture: not run yet', text)
        self.assertNotIn('unknown, unknown', text)
        self.assertIn('Workspace-level connections: claude', text)
        text = cli.text_doctor({'capture_health': {'outcome': 'unknown', 'reason': 'unreadable_health'}})
        self.assertIn('Last capture outcome: unknown (unreadable_health)', text)

    def test_digest_of_a_directory_says_pass_a_file(self):
        err = self.ws('digest', str(self.root))[2]
        self.assertIn('is a directory; pass a file.', err)
        self.assertNotIn('50 MB', err)

    def test_team_init_and_link_without_a_remote_show_the_form(self):
        for action in ('init', 'link'):
            code, _, err = self.ws('team', action)
            self.assertEqual(code, 2)
            self.assertIn(f'The remote is missing: run `ws team {action} <private-repo>`.', err)


if __name__ == '__main__':
    unittest.main()
