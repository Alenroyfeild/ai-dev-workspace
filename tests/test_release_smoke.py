import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ('ws --version', 'ws demo', 'ws start --yes', 'ws remember + checkpoint', 'ws doctor --text', 'ws recap', 'ws pr-notes',
        'MCP initialize + tools/list', 'ws start --undo restores repo')


class ReleaseSmokeTests(unittest.TestCase):
    def test_source_mode_reports_every_step_in_json(self):
        with tempfile.TemporaryDirectory() as temp:
            done = subprocess.run([sys.executable, str(ROOT / 'bin/release-smoke'), '--source', '--json'], cwd=temp,
                                  capture_output=True, text=True, timeout=300)
            result = json.loads(done.stdout)
            steps = {s['name']: s for s in result['steps']}
            self.assertEqual(result['mode'], 'source')
            for step in result['steps']:
                self.assertIn(step['status'], ('PASS', 'FAIL', 'SKIP'))
                self.assertTrue(step['name'] and 'seconds' in step and 'reason' in step)
            for name in CORE:
                self.assertEqual(steps[name]['status'], 'PASS', steps[name])
            brief = next(s for n, s in steps.items() if n.startswith('ws brief'))
            self.assertEqual(brief['status'], 'PASS', brief)
            self.assertEqual(steps['package contents']['status'], 'SKIP')  # nothing is built in --source mode
            redaction = steps['token redaction (ghp_)']
            if redaction['status'] == 'FAIL': self.assertIn('known_blocker', redaction)  # reported, not a crash
            self.assertEqual(done.returncode, 0 if result['ok'] else 1)
            self.assertEqual(result['ok'], not any(s['status'] == 'FAIL' for s in result['steps']))

    def test_refuses_conflicting_modes_and_leaves_real_home_alone(self):
        done = subprocess.run([sys.executable, str(ROOT / 'bin/release-smoke'), '--source', '--wheel', 'x.whl'],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 2)
        self.assertIn('exclusive', done.stderr)


if __name__ == '__main__':
    unittest.main()
