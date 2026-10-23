import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'bin/ws'


class CliPolishTests(unittest.TestCase):
    def run_ws(self, *args, env=None, cwd=ROOT):
        return subprocess.run([sys.executable, str(CLI), *args], cwd=cwd, env=env,
                              text=True, capture_output=True)

    def test_short_help_only_shows_daily_commands_and_all_help_keeps_rest(self):
        short = self.run_ws('--help')
        self.assertEqual(short.returncode, 0, short.stderr)
        usage = short.stdout.splitlines()[0]
        self.assertIn('{demo,start,status,task,claim,checkpoint,remember,search,lesson,doctor}', usage)
        self.assertNotIn('init', usage)
        for command in ('start', 'status', 'task', 'claim', 'checkpoint', 'search', 'lesson', 'doctor'):
            self.assertIn('    ' + command, short.stdout)
        for command in ('init', 'route', 'tools', 'delegate', 'feedback', 'upgrade'):
            self.assertNotIn('    ' + command, short.stdout)
        invalid = self.run_ws('not-a-command')
        self.assertIn('COMMAND ...', invalid.stderr)
        self.assertNotIn('{demo,start,status,task,claim,checkpoint,remember,search,lesson,doctor}', invalid.stderr)

        full = self.run_ws('help', 'all')
        self.assertEqual(full.returncode, 0, full.stderr)
        for command in ('init', 'start', 'status', 'task', 'claim', 'checkpoint', 'search', 'doctor',
                        'route', 'tools', 'delegate', 'feedback', 'upgrade'):
            self.assertIn('    ' + command, full.stdout)

    def test_readme_is_short_and_points_to_extended_docs(self):
        readme = (ROOT / 'README.md').read_text()
        self.assertLessEqual(len(readme.splitlines()), 180)
        first_12 = '\n'.join(readme.splitlines()[:12])
        self.assertIn('Your assistant remembers work between sessions in Markdown you own.', first_12)
        self.assertIn('## Quick start', first_12)
        self.assertIn('<!-- Demo GIF -->', readme)
        sections = ('## Quick start', '## Use cases', '## Example', '## Features', '## How it works',
                    '## Results', '## Compared with', '## Compatibility', '## Privacy & safety',
                    '## Documentation', '## Status & contributing')
        self.assertEqual(sorted(readme.index(section) for section in sections),
                         [readme.index(section) for section in sections])
        self.assertIn('docs/OVERVIEW.md', readme)
        self.assertIn('cd ~/code/myapp && ws start', readme)
        for status in ('Claude Code | supported, tested live on macOS | CI-tested',
                       'Codex | supported, tested live on macOS | CI-tested',
                       'Cursor | supported, fixture-tested; live reports welcome | CI-tested',
                       'Copilot (VS Code) | supported, fixture-tested; live reports welcome | CI-tested',
                       'Gemini CLI | supported, fixture-tested; live reports welcome | CI-tested',
                       'Antigravity | supported, fixture-tested; rules, MCP (hooks coming in beta.6) | CI-tested'):
            self.assertIn(status, readme)
        self.assertIn('[Something broke]', readme)
        self.assertIn('https://github.com/Alenroyfeild/ai-dev-workspace/issues/new?template=bug.yml', readme)
        self.assertNotIn('## FAQ', readme)

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

    def test_connection_probe_keeps_the_bom_tolerant_json_reader(self):
        from ws import core
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / 'workspace.json').write_text('{}', encoding='utf-8')
            data = {'mcpServers': {'ai-dev-workspace': core.mcp_command(workspace)}}
            (workspace / '.mcp.json').write_text('\ufeff' + json.dumps(data), encoding='utf-8')
            self.assertTrue(core.client_connected(workspace, 'claude'))

    def test_doctor_verdict_json_flag_and_empty_preset_parentheses(self):
        from ws import cli
        good = {'core': {'python3': True, 'git': True}, 'workspace': '/w', 'valid': True,
                'setup': {'preset': 'not selected', 'assistants': []}, 'configured_clients': {'claude': True, 'codex': True, 'cursor': False}}
        lines = cli.text_doctor(good).splitlines()
        self.assertEqual(lines[0], 'OK: workspace valid; Claude connected; Codex connected')
        self.assertIn('Setup preset: not selected', lines); self.assertNotIn('()', '\n'.join(lines))
        bad = cli.text_doctor(dict(good, configured_clients={'claude': False})).splitlines()[0]
        self.assertTrue(bad.startswith('Needs attention: no assistant connected'), bad); self.assertIn('ws start', bad)
        self.assertTrue(cli.text_doctor(dict(good, valid=False)).startswith('Needs attention: workspace invalid'))
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'; home.mkdir(); workspace = Path(temporary) / 'workspace'
            env = dict(os.environ, HOME=str(home), USER='demo', WS_ROOT=str(workspace))
            self.assertEqual(self.run_ws('init', str(workspace), '--name', 'v', env=env).returncode, 0)
            with mock.patch.object(cli, 'human', return_value=True), contextlib.redirect_stdout(io.StringIO()) as stream:
                self.assertEqual(cli.main(['--workspace-root', str(workspace), 'doctor', '--json']), 0)
            self.assertIsInstance(json.loads(stream.getvalue()), dict)  # --json beats a terminal
            with mock.patch.object(cli, 'human', return_value=True), contextlib.redirect_stdout(io.StringIO()) as stream:
                cli.main(['--workspace-root', str(workspace), 'doctor'])
            self.assertTrue(stream.getvalue().startswith(('OK:', 'Needs attention:')), stream.getvalue()[:80])  # terminal default is text

    def test_unreadable_workspace_keeps_json_and_actionable_doctor_verdict(self):
        from ws import cli
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'home'; home.mkdir()
            workspace = Path(temporary) / 'workspace'; workspace.mkdir()
            (workspace / 'workspace.json').write_text('{ invalid', encoding='utf-8')
            env = dict(HOME=str(home), USERPROFILE=str(home), WS_OFFLINE='1')
            with mock.patch.dict(os.environ, env), mock.patch.object(cli, 'human', return_value=True):
                for mode in ('--json', '--text'):
                    with self.subTest(mode=mode), contextlib.redirect_stdout(io.StringIO()) as stream:
                        self.assertEqual(cli.main(['--workspace-root', str(workspace), 'doctor', mode]), 0)
                        output = stream.getvalue()
                        if mode == '--json':
                            report = json.loads(output)
                            self.assertIn('workspace.json is unreadable', report['workspace_error'])
                            verdict = cli.doctor_verdict(report)
                        else:
                            verdict = output.splitlines()[0]
                        self.assertTrue(verdict.startswith('Needs attention: workspace.json is unreadable'), verdict)
                        self.assertIn('fix or restore', verdict)

    def test_doctor_verdict_asks_for_ws_upgrade_when_workspace_is_older(self):
        from ws import cli, core
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / 'workspace'
            env = dict(os.environ, HOME=temporary)
            self.assertEqual(self.run_ws('init', str(workspace), '--name', 'u', env=env).returncode, 0)
            self.assertFalse(core.doctor(workspace)['upgrade_due'])
            cfg = core.config(workspace); cfg['kit_version'] = '0.0.1'
            (workspace / 'workspace.json').write_text(json.dumps(cfg))
            report = core.doctor(workspace)
            self.assertTrue(report['upgrade_due'])
            self.assertTrue(cli.text_doctor(report).startswith('Needs attention: workspace was written by an older kit. Next: ws upgrade --dry-run'))

    def test_ws_error_includes_next_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary) / 'workspace'
            env = dict(os.environ, HOME=temporary)
            init = self.run_ws('init', str(workspace), '--name', 'error-demo', env=env)
            self.assertEqual(init.returncode, 0, init.stderr)
            env['WS_ROOT'] = str(workspace)
            result = self.run_ws('search', 'x', env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Next: run `ws search --help`', result.stderr)  # names the failing command

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
