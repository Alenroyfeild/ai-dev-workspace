import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from test_ws import Base
from ws import cli, core


class SetupTests(Base):
    def setUp(self):
        home = tempfile.TemporaryDirectory(); self.addCleanup(home.cleanup); self.home = Path(home.name)
        env = mock.patch.dict(os.environ, {'HOME': home.name, 'CODEX_HOME': home.name + '/.codex'})
        env.start(); self.addCleanup(env.stop); super().setUp()

    def run_setup(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli.main(['--workspace-root', str(self.root), 'setup', *args])
        self.assertEqual(result, 0); return json.loads(output.getvalue())

    def test_preview_is_read_only_and_reports_paths_then_apply_uses_vscode_alias(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with mock.patch.object(core, 'connect', side_effect=AssertionError('preview must not connect')):
            report = self.run_setup('--assistants', 'copilot')
        self.assertTrue(report['dry_run'])
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertIn('.vscode/mcp.json', report['config_paths'])
        self.assertIn('trust', report['note'].lower())
        report = self.run_setup('--assistants', 'vscode', '--apply')
        self.assertEqual(report['preset'], 'copilot-only')
        self.assertTrue(core.client_connected(self.root, 'vscode'))
        self.assertEqual((self.root / '.mcp.json').read_bytes(), before[Path('.mcp.json')])
        self.assertTrue((self.root / '.github/hooks/ai-dev-workspace.json').exists())

    @unittest.skipIf(os.name == 'nt', 'Symlink creation requires privileges on Windows')
    def test_client_symlink_refused_before_metadata_changes(self):
        from ws import setup
        (self.root / '.vscode').mkdir()
        outside = self.home / 'user.json'; outside.write_text('{"user":"keep"}')
        (self.root / '.vscode/mcp.json').symlink_to(outside)
        before = (self.root / 'routing.json').read_bytes()
        with self.assertRaises(core.WsError): setup.configure(self.root, ['copilot'])
        self.assertEqual((self.root / 'routing.json').read_bytes(), before)
        self.assertEqual(outside.read_text(), '{"user":"keep"}')

    def test_connection_failure_reports_partial_and_cli_returns_error(self):
        output = io.StringIO()
        with mock.patch.object(core, 'connect', side_effect=core.WsError('Fixture conflict')), contextlib.redirect_stdout(output):
            code = cli.main(['--workspace-root', str(self.root), 'setup', '--assistants', 'copilot', '--apply'])
        self.assertEqual(code, 2)
        self.assertTrue(json.loads(output.getvalue())['partial'])

    def test_flags_preserve_user_data_connect_selected_and_show_doctor_preset(self):
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        data['user_note'] = 'Keep Unicode Ω and spacing'; data['role_overrides']['worker'] = {'effort': 'low'}
        path.write_bytes((json.dumps(data, ensure_ascii=False, indent=3) + '\n').replace('\n', '\r\n').encode()); before = path.read_bytes()
        with mock.patch.object(core.shutil, 'which', return_value=None), mock.patch.object(core, '_has_app', return_value=False), \
                mock.patch.object(core, 'connect', return_value={'connected': True}) as connect:
            report = self.run_setup('--assistants', 'codex', '--apply')
        self.assertEqual(report['preset'], 'codex-only')
        self.assertEqual(connect.call_args.args[:2], (self.root.resolve(), 'codex'))
        self.assertFalse(connect.call_args.kwargs.get('skills', True))
        updated = json.loads(path.read_text())
        self.assertEqual(updated['user_note'], data['user_note']); self.assertEqual(updated['role_overrides'], data['role_overrides'])
        self.assertIn('"user_note": "Keep Unicode Ω and spacing"', path.read_text())
        self.assertEqual(before[before.index(b'"user_note"'):], path.read_bytes()[path.read_bytes().index(b'"user_note"'):])
        backups = list((self.root / '.ws/backups').rglob('routing.json')); self.assertEqual(backups[0].read_bytes(), before)
        self.assertEqual(core.doctor(self.root)['setup']['preset'], 'codex-only')
        self.assertFalse((self.home / '.codex/config.toml').exists())

    def test_interactive_asks_which_assistants_and_copilot_uses_project_mcp(self):
        with mock.patch.object(core.shutil, 'which', return_value=None), mock.patch.object(core, '_has_app', return_value=False), \
                mock.patch('builtins.input', return_value='copilot') as ask, mock.patch.object(cli.sys.stdin, 'isatty', return_value=True):
            report = self.run_setup('--apply')
        ask.assert_called_once(); self.assertEqual(report['preset'], 'copilot-only')
        self.assertTrue(report['connections'][0]['connected']); self.assertTrue(core.client_connected(self.root, 'vscode'))
        self.assertIn('hooks', report['connections'][0])

    def test_invalid_choice_and_unselected_override_leave_workspace_unchanged(self):
        from ws import setup
        path = self.root / 'routing.json'; data = json.loads(path.read_text())
        data['role_overrides']['reviewer'] = {'provider': 'claude'}; path.write_text(json.dumps(data))
        before = path.read_bytes()
        with self.assertRaises(core.WsError): setup.configure(self.root, ['codex'])
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(core.WsError): setup.configure(self.root, ['unknown'])
        self.assertEqual(path.read_bytes(), before)

    def test_unmanaged_config_is_not_overwritten(self):
        from ws import setup
        path = self.root / 'routing.json'; path.write_text('{ "user": "keep me" }\n')
        with self.assertRaises(core.WsError): setup.configure(self.root, ['codex'])
        self.assertEqual(path.read_text(), '{ "user": "keep me" }\n')

    def test_detect_only_is_read_only_and_never_runs_clients(self):
        from ws import setup
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with mock.patch.object(core.shutil, 'which', return_value='/fixture/cli'), \
                mock.patch.object(core, '_has_app', return_value=False), mock.patch.object(core.subprocess, 'run', side_effect=AssertionError('must not execute')):
            report = setup.detect()
        self.assertTrue(all(item['cli_available'] for item in report))
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
