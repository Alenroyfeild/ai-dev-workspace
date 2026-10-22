import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core, orchestration, repo as wiring, setup
from testutil import needs_symlinks


class AntigravityTests(Base):
    def test_connect_cli_writes_only_project_mcp_and_is_idempotent(self):
        agents = (self.root / 'AGENTS.md').read_bytes()
        gemini = (self.root / 'GEMINI.md').read_bytes()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(['--workspace-root', str(self.root), 'connect', 'antigravity'])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report['support'], 'rules+MCP; fixture-tested')
        target = self.root / '.agents/mcp_config.json'
        self.assertEqual(json.loads(target.read_text())['mcpServers']['ai-dev-workspace'], core.mcp_command(self.root))
        self.assertTrue(core.client_connected(self.root, 'antigravity'))
        self.assertEqual(core.connect(self.root, 'antigravity')['path'], str(target))
        self.assertFalse(target.with_name(target.name + '.ws-new').exists())
        self.assertEqual((self.root / 'AGENTS.md').read_bytes(), agents)
        self.assertEqual((self.root / 'GEMINI.md').read_bytes(), gemini)
        self.assertFalse((Path.home() / '.gemini').exists())
        self.assertNotIn('hooks', report)
        self.assertTrue(core.doctor(self.root)['configured_clients']['antigravity'])

    def test_connect_keeps_existing_config_and_stages_a_merged_proposal(self):
        target = self.root / '.agents/mcp_config.json'
        target.parent.mkdir(exist_ok=True)
        original = b'{"mcpServers":{"user-server":{"command":"fixture-command"}}}\n'
        target.write_bytes(original)
        result = core.connect(self.root, 'antigravity')
        self.assertFalse(result['connected'])
        self.assertEqual(target.read_bytes(), original)
        proposal = json.loads(Path(result['path']).read_text())
        self.assertEqual(proposal['mcpServers']['user-server']['command'], 'fixture-command')
        self.assertIn('ai-dev-workspace', proposal['mcpServers'])

    def test_detect_uses_cli_and_app_without_running_them(self):
        with mock.patch.object(core.shutil, 'which', side_effect=lambda name: '/fixture/agy' if name == 'agy' else None), \
                mock.patch.object(core, '_has_app', side_effect=lambda name: name == 'Antigravity'), \
                mock.patch.object(setup.subprocess, 'run', side_effect=AssertionError('must not run clients')):
            detected = next(row for row in setup.detect() if row['assistant'] == 'antigravity')
        self.assertTrue(detected['cli_available'])
        self.assertEqual(detected['apps'], ['Antigravity'])

    def test_start_preview_apply_and_undo_are_repo_local(self):
        repo = self.root.parent / 'app'; repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        memory = self.root.parent / 'private-memory'
        gemini = repo / 'GEMINI.md'; original = b'Keep my project instructions.\n'; gemini.write_bytes(original)
        detected = [{'assistant': 'antigravity', 'cli_available': True, 'apps': []}]
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch.object(setup, 'detect', return_value=detected), contextlib.redirect_stderr(io.StringIO()) as err:
                wiring.start(workspace=memory, dry_run=True)
                self.assertFalse(memory.exists())
                self.assertFalse((repo / wiring.LINK).exists())
                self.assertFalse((repo / '.agents/mcp_config.json').exists())
                self.assertIn(str(repo.resolve() / '.agents/mcp_config.json'), err.getvalue())
                result = wiring.start(workspace=memory, yes=True)
                self.assertIn('antigravity', result['assistants'])
                self.assertEqual(json.loads((repo / '.agents/mcp_config.json').read_text())['mcpServers']['ai-dev-workspace'], core.mcp_command(memory))
                self.assertIn('MCP', gemini.read_text())
                self.assertTrue(gemini.read_bytes().startswith(original))
                self.assertFalse((repo / '.agents/hooks.json').exists())
                wiring.start(remove=True)
        finally:
            os.chdir(cwd)
        self.assertEqual(gemini.read_bytes(), original)
        self.assertFalse((repo / '.agents/mcp_config.json').exists())
        self.assertFalse((Path.home() / '.gemini').exists())

    def test_project_mcp_config_starts_the_existing_server(self):
        core.connect(self.root, 'antigravity')
        checks = core.mcp_doctor(self.root, ('antigravity',))
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0]['ok'], checks)

    def test_single_assistant_setup_stays_preparation_only(self):
        report = setup.configure(self.root, ['antigravity'])
        self.assertFalse(report['partial'])
        self.assertEqual(report['preset'], 'antigravity-only')
        with mock.patch.object(core.shutil, 'which', return_value='/fixture/agy') as found:
            route = orchestration.route(self.root, 'explorer')
            self.assertEqual(route['provider'], 'antigravity')
            self.assertFalse(route['can_run'])
            self.assertEqual({call.args[0] for call in found.call_args_list}, {'agy'})
            with self.assertRaisesRegex(core.WsError, 'preparation-only'):
                orchestration.delegate(self.root, 'T-1', 'explorer', run=True)

    @needs_symlinks
    def test_project_config_cannot_escape_through_a_symlink(self):
        target = self.root / '.agents/mcp_config.json'
        target.parent.mkdir(exist_ok=True)
        outside = self.root.parent / 'user-config.json'
        outside.write_text('keep me')
        target.symlink_to(outside)
        with self.assertRaises(core.WsError):
            core.connect(self.root, 'antigravity')
        self.assertEqual(outside.read_text(), 'keep me')
