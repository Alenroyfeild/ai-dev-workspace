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
        self.assertEqual(report['support'], 'rules+MCP+hooks; fixture-tested')
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
                self.assertIn(str(repo.resolve() / '.agents/hooks.json'), err.getvalue())
                result = wiring.start(workspace=memory, yes=True)
                self.assertIn('antigravity', result['assistants'])
                self.assertEqual(json.loads((repo / '.agents/mcp_config.json').read_text())['mcpServers']['ai-dev-workspace'], core.mcp_command(memory))
                self.assertIn('MCP', gemini.read_text())
                self.assertTrue(gemini.read_bytes().startswith(original))
                self.assertTrue((repo / '.agents/hooks.json').exists())
                hooks = json.loads((repo / '.agents/hooks.json').read_text())['hooks']
                self.assertIn('SessionStart', hooks)
                self.assertIn('brief --hook --client antigravity', hooks['SessionStart'][0]['hooks'][0]['command'])
                wiring.start(remove=True)
        finally:
            os.chdir(cwd)
        self.assertEqual(gemini.read_bytes(), original)
        self.assertFalse((repo / '.agents/mcp_config.json').exists())
        self.assertFalse((repo / '.agents/hooks.json').exists())
        self.assertFalse((repo / '.agents').exists())
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

    def test_antigravity_hooks_with_guards_pack(self):
        core.pack_add(self.root, 'guards')
        hooks = core.pack_hooks(self.root, 'antigravity')
        self.assertIn('PreToolUse', hooks)
        self.assertTrue(hooks['PreToolUse'][0]['hooks'][0]['command'].endswith(core.command_line(['guard', '--hook', '--client', 'antigravity'])))

    def test_brief_hook_stdin_camelcase_and_stdout_steps(self):
        transcript = self.root / 'transcript.jsonl'
        transcript.write_text('{"type": "user"}\n')
        payload = {
            'conversationId': 'conv-agy-42',
            'transcriptPath': str(transcript),
            'workspacePaths': [str(self.root)],
        }
        out = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(out):
            code = cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', 'antigravity'])
        self.assertEqual(code, 0)
        output = json.loads(out.getvalue())
        self.assertIn('injectSteps', output)
        self.assertEqual(len(output['injectSteps']), 1)
        self.assertIn('systemMessage', output['injectSteps'][0]['systemMessage'])
        # Verify observe recorded session ID from conversationId
        state = cli.assist.state(self.root)
        self.assertIn(core.digest_text('conv-agy-42'), state.get('session_tasks', {}))

    def test_guard_hook_stdin_camelcase_deny_and_allow(self):
        # Deny destructive git push -f
        payload_deny = {
            'toolCall': {'name': 'run_command', 'args': {'CommandLine': 'git push -f origin main'}},
            'conversationId': 'conv-1',
            'transcriptPath': str(self.root / 't.jsonl'),
            'workspacePaths': [str(self.root)],
        }
        out = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload_deny))), contextlib.redirect_stdout(out):
            code = cli.main(['guard', '--hook', '--client', 'antigravity'])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report.get('decision'), 'deny')
        self.assertIn('ws guards:', report.get('reason', ''))

        # Allow benign command
        payload_allow = {
            'toolCall': {'name': 'run_command', 'args': {'CommandLine': 'git status'}},
            'conversationId': 'conv-1',
            'transcriptPath': str(self.root / 't.jsonl'),
            'workspacePaths': [str(self.root)],
        }
        out = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload_allow))), contextlib.redirect_stdout(out):
            code = cli.main(['guard', '--hook', '--client', 'antigravity'])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report, {})

    def test_start_undo_cleans_empty_agents_directory_only_when_ws_created_it(self):
        repo1 = self.root.parent / 'app-clean-agents'; repo1.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo1, check=True)
        memory1 = self.root.parent / 'memory-clean'
        detected = [{'assistant': 'antigravity', 'cli_available': True, 'apps': []}]
        cwd = os.getcwd(); os.chdir(repo1)
        try:
            with mock.patch.object(setup, 'detect', return_value=detected):
                wiring.start(workspace=memory1, yes=True)
                self.assertTrue((repo1 / '.agents').exists())
                wiring.start(remove=True)
                self.assertFalse((repo1 / '.agents').exists())
        finally:
            os.chdir(cwd)
        repo = self.root.parent / 'app-with-agents'; repo.mkdir()
        subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=repo, check=True)
        user_agents = repo / '.agents'; user_agents.mkdir()
        user_file = user_agents / 'custom_rule.md'; user_file.write_text('custom')
        memory = self.root.parent / 'memory-custom'
        detected = [{'assistant': 'antigravity', 'cli_available': True, 'apps': []}]
        cwd = os.getcwd(); os.chdir(repo)
        try:
            with mock.patch.object(setup, 'detect', return_value=detected):
                wiring.start(workspace=memory, yes=True)
                self.assertTrue((repo / '.agents/mcp_config.json').exists())
                self.assertTrue((repo / '.agents/hooks.json').exists())
                wiring.start(remove=True)
                self.assertFalse((repo / '.agents/mcp_config.json').exists())
                self.assertFalse((repo / '.agents/hooks.json').exists())
                self.assertTrue(user_agents.exists())
                self.assertEqual(user_file.read_text(), 'custom')
        finally:
            os.chdir(cwd)
