import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    def test_demo_runs_without_model_calls_and_shows_the_daily_loop(self):
        result = subprocess.run([str(ROOT / 'scripts/demo.sh')], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ('ws init ', 'ws connect claude', 'ws task new ', 'ws claim ',
                        'ws checkpoint ', 'ws brief', 'ws delegate '):
            self.assertIn('$ ' + command, result.stdout)
        self.assertIn("--token '<claim-token>'", result.stdout)
        self.assertIn('delegate was prepared; no model was called', result.stdout)


if __name__ == '__main__':
    unittest.main()
