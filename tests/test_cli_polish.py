import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'bin/ws'


class CliPolishTests(unittest.TestCase):
    def run_ws(self, *args, env=None, cwd=ROOT):
        return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, env=env,
                              text=True, capture_output=True)

    def test_help_lists_commands_in_groups(self):
        result = self.run_ws('--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        for group in ('Setup:', 'Daily:', 'Orchestration:', 'Measure:', 'Maintain:'):
            self.assertIn(group, result.stdout)
        for command in ('init', 'claim', 'checkpoint', 'route', 'tools', 'doctor', 'feedback'):
            self.assertIn('    ' + command, result.stdout)

    def test_text_reports_and_default_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); home = root / 'home'; home.mkdir()
            fake_bin = root / 'bin'; fake_bin.mkdir()
            provider = fake_bin / 'codex'; provider.write_text('#!/bin/sh\nexit 97\n'); provider.chmod(0o755)
            env = dict(os.environ, HOME=str(home), USER='demo')
            env['PATH'] = str(fake_bin) + os.pathsep + env['PATH']
            init = self.run_ws('init', str(root / 'workspace'), '--name', 'cli-demo', env=env)
            self.assertEqual(init.returncode, 0, init.stderr)
            env['WS_ROOT'] = str(root / 'workspace')
            status = self.run_ws('status', env=env)
            self.assertEqual(json.loads(status.stdout)['workspace'], 'cli-demo')
            self.assertIsInstance(json.loads(self.run_ws('doctor', env=env).stdout), dict)
            self.assertIn('provider', json.loads(self.run_ws('route', 'explorer', env=env).stdout))
            status_text = self.run_ws('status', '--text', env=env)
            self.assertIn('Workspace: cli-demo', status_text.stdout)
            doctor_text = self.run_ws('doctor', '--text', env=env)
            self.assertIn('Core:', doctor_text.stdout)
            route_text = self.run_ws('route', '--text', env=env)
            self.assertIn('Role:', route_text.stdout)

    def test_ws_error_includes_next_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / 'workspace'
            env = dict(os.environ, HOME=temporary)
            init = self.run_ws('init', str(workspace), '--name', 'error-demo', env=env)
            self.assertEqual(init.returncode, 0, init.stderr)
            env['WS_ROOT'] = str(workspace)
            result = self.run_ws('search', 'x', env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Next: run `ws --help`', result.stderr)

    def test_connect_codex_explains_preview_and_project_skills(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            home, workspace, repo = base / 'home', base / 'workspace', base / 'repo'
            home.mkdir(); repo.mkdir()
            env = dict(os.environ, HOME=str(home), USER='fixture')
            initialized = self.run_ws('init', str(workspace), '--repo', str(repo), env=env)
            self.assertEqual(initialized.returncode, 0, initialized.stderr)
            result = self.run_ws('connect', 'codex', env=env, cwd=workspace)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('preview only; not applied', result.stderr)
            self.assertIn('ws connect codex --write', result.stderr)
            self.assertIn('Project skills: available', result.stderr)


if __name__ == '__main__':
    unittest.main()
