"""Example launch boundaries without optional framework dependencies."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from test_ws import Base, KIT


class FrameworkExamplesTests(Base):
    def run_plan(self, *args):
        script = KIT / 'docs/examples/frameworks/common.py'
        code = "import runpy,json; d=runpy.run_path(" + repr(str(script)) + "); print(json.dumps({'plan':d['PLAN'],'connection':d['connection']()}))"
        return subprocess.run([sys.executable, '-c', code, str(self.root), *args],
                              env={**os.environ, 'EXAMPLE_SECRET': 'synthetic-only', 'HOME': str(self.root / 'home')},
                              text=True, capture_output=True, timeout=10)

    def test_resume_has_no_write_or_seed_and_server_receives_no_credentials(self):
        result = self.run_plan('resume')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual([name for name, _ in data['plan']], ['find_task', 'brief'])
        self.assertNotIn('EXAMPLE_SECRET', data['connection']['env'])
        self.assertEqual(data['connection']['args'][-1], str(self.root.resolve()))
        self.assertNotEqual(self.run_plan('resume', '--decision', 'hidden answer').returncode, 0)
        self.assertNotEqual(self.run_plan('write').returncode, 0)
        written = self.run_plan('write', '--decision', 'Keep the old index.')
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertEqual([name for name, _ in json.loads(written.stdout)['plan']],
                         ['find_task', 'brief', 'checkpoint', 'add_lesson'])
