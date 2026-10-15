import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from ws import cli


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_beta_kit_version_is_published_as_pep440(self):
        result = subprocess.run(
            [sys.executable, 'setup.py', '--version'], cwd=ROOT,
            check=True, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), '0.1.0b5')

    def test_cli_prints_kit_version_without_a_command(self):
        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as exit_info:
            cli.main(['--version'])
        self.assertEqual(exit_info.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), 'ws 0.1.0-beta.5')


if __name__ == '__main__':
    unittest.main()
