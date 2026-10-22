"""Vendor-shaped hook fixtures; no Antigravity process or global configuration."""
import contextlib
import io
import json
import os
import subprocess
from unittest import mock

from test_ws import Base
from ws import cli, core, guards, packs, repo, setup


class AntigravityHookTests(Base):
    def test_session_start_has_direct_handlers(self):
        # https://antigravity.google/docs/hooks/: named definition, direct SessionStart handlers.
        definition = core.memory_hooks(self.root, 'antigravity')['hooks']
        self.assertEqual(set(definition), {'SessionStart'})
        self.assertIn('brief --hook --client antigravity', definition['SessionStart'][0]['command'])

    def test_connect_installs_hooks_and_only_opted_in_guards(self):
        target = self.root / '.agents/hooks.json'
        core.connect(self.root, 'antigravity')
        original = json.loads(target.read_text())
        self.assertNotIn('PreToolUse', original['hooks'])
        core.pack_add(self.root, 'guards')
        result = core.connect(self.root, 'antigravity')
        self.assertIn('hooks', result)
        self.assertIn('guard --hook --client antigravity', target.read_text())
        before = target.read_bytes()
        core.connect(self.root, 'antigravity')
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse((self.root / '.gemini').exists())

    def test_reconnect_after_guards_removed_keeps_only_user_handlers(self):
        core.pack_add(self.root, 'guards'); core.connect(self.root, 'antigravity')
        target = self.root / '.agents/hooks.json'; data = json.loads(target.read_text())
        user = {'type': 'command', 'command': 'echo user-hook'}
        data['hooks']['PreToolUse'][0]['hooks'].append(user)
        target.write_text(json.dumps(data))
        packs.remove(self.root, 'guards')
        core.connect(self.root, 'antigravity')
        handlers = json.loads(target.read_text())['hooks']['PreToolUse']
        self.assertEqual(handlers, [{'hooks': [user]}])

    def test_native_file_tools_deny_secrets_and_disabling_guards(self):
        secret = 'sk-' + 'synthetic1234567890' * 3
        cases = [('write_to_file', {'TargetFile': 'app.py', 'CodeContent': secret}),
                 ('replace_file_content', {'TargetFile': 'app.py', 'TargetContent': 'old', 'ReplacementContent': secret}),
                 ('multi_replace_file_content', {'TargetFile': 'app.py', 'ReplacementChunks': [
                     {'TargetContent': 'old', 'ReplacementContent': secret}]}),
                 ('write_to_file', {'TargetFile': '.agents/hooks.json', 'CodeContent': '{}'}),
                 ('write_to_file', {'TargetFile': '.agents/hooks.json', 'CodeContent': json.dumps(
                     {'hooks': {'enabled': False, 'PreToolUse': [{'hooks': [
                         {'command': 'ws guard --hook --client antigravity'}]}]}})})]
        target = self.root / '.agents/hooks.json'
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps({'hooks': {'PreToolUse': [{'hooks': [
            {'command': 'ws guard --hook --client antigravity'}]}]}}))
        for name, args in cases:
            with self.subTest(tool=name, file=args['TargetFile']):
                result = guards.hook({'toolCall': {'name': name, 'args': args},
                                      'workspacePaths': [str(self.root)]}, client='antigravity')
                self.assertEqual(result.get('decision'), 'deny', result)

    def test_safe_tool_uses_vendor_allow_decision(self):
        result = guards.hook({'toolCall': {'name': 'run_command', 'args': {'CommandLine': 'git status'}}},
                             client='antigravity')
        self.assertEqual(result, {'decision': 'allow'})

    def test_path_content_tools_deny_secret_and_hook_disable(self):
        target = self.root / '.agents/hooks.json'; target.parent.mkdir(exist_ok=True)
        original = {'hooks': {'PreToolUse': [{'hooks': [
            {'command': 'ws guard --hook --client antigravity'}]}]}}
        target.write_text(json.dumps(original))
        disabled = {'hooks': {**original['hooks'], 'enabled': False}}
        secret = 'sk-' + 'synthetic1234567890' * 3
        for tool in ('write_file', 'edit_file'):
            for args in ({'Path': 'app.py', 'Content': secret},
                         {'Path': str(target), 'Content': '{}'},
                         {'Path': str(target), 'Content': json.dumps(disabled)},
                         {'Path': 'app.py', 'Target': 'old', 'Replacement': secret}):
                with self.subTest(tool=tool, args=tuple(args)):
                    result = guards.hook({'toolCall': {'name': tool, 'args': args},
                                          'workspacePaths': [str(self.root)]}, client='antigravity')
                    self.assertEqual(result.get('decision'), 'deny', result)
        self.assertEqual(guards.hook({'toolCall': {'name': 'write_file', 'args': {
            'Path': 'app.py', 'Content': 'public text'}}}, client='antigravity'), {'decision': 'allow'})

    def test_connected_hook_upgrades_and_keeps_user_definition(self):
        core.connect(self.root, 'antigravity')
        target = self.root / '.agents/hooks.json'; data = json.loads(target.read_text())
        data['hooks']['SessionStart'][0]['timeout'] = 99
        data['user-hook'] = {'Stop': [{'command': 'echo keep'}]}
        target.write_text(json.dumps(data))
        core.upgrade_workspace(self.root)
        updated = json.loads(target.read_text())
        self.assertEqual(updated['hooks']['SessionStart'][0]['timeout'], 10)
        self.assertEqual(updated['user-hook'], data['user-hook'])

    def test_camelcase_bad_shapes_fail_open(self):
        for command in ('brief', 'guard'):
            for payload in ([], {'conversationId': [], 'transcriptPath': {}, 'workspacePaths': [5]},
                            {'toolCall': {'name': [], 'args': {'ReplacementChunks': [None, 4]}}}):
                output = io.StringIO()
                with self.subTest(command=command, payload=payload), mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(['--workspace-root', str(self.root), command, '--hook', '--client', 'antigravity']), 0)
                self.assertNotEqual(json.loads(output.getvalue()).get('decision'), 'deny')

    def test_camelcase_brief_maps_fields_and_never_reads_transcript(self):
        payload = {'conversationId': 'fixture-session', 'transcriptPath': str(self.root / 'absent.jsonl'),
                   'workspacePaths': [str(self.root)]}
        output = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output), \
                mock.patch.object(cli.assist, 'observe', wraps=cli.assist.observe) as observe, \
                mock.patch.object(core, 'capture_decisions') as capture:
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', 'antigravity']), 0)
        self.assertEqual(observe.call_args.args[1]['session_id'], payload['conversationId'])
        self.assertEqual(observe.call_args.args[1]['transcript_path'], payload['transcriptPath'])
        capture.assert_not_called()  # Antigravity transcript capture is outside this adapter's scope.
        self.assertIn('task', json.loads(output.getvalue())['injectSteps'][0]['systemMessage']['systemMessage'])

    def test_undo_keeps_preexisting_empty_agents_and_user_hook_definitions(self):
        for had_directory in (False, True):
            with self.subTest(preexisting=had_directory):
                code = self.root.parent / ('code-' + str(had_directory)); code.mkdir()
                subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=code, check=True)
                directory = code / '.agents'
                if had_directory: directory.mkdir()
                previous = os.getcwd(); os.chdir(code)
                try:
                    with mock.patch.object(setup, 'detect', return_value=[{'assistant': 'antigravity', 'cli_available': True, 'apps': []}]), \
                            contextlib.redirect_stderr(io.StringIO()):
                        memory = self.root.parent / ('memory-' + str(had_directory))
                        repo.start(yes=True, workspace=memory)
                        core.pack_add(memory, 'guards')
                        repo.start(yes=True)
                        self.assertIn('guard --hook --client antigravity', (directory / 'hooks.json').read_text())
                        if not had_directory:
                            path = directory / 'hooks.json'; data = json.loads(path.read_text())
                            data['user-hook'] = {'Stop': [{'command': 'echo keep'}]}
                            path.write_text(json.dumps(data))
                        repo.start(remove=True)
                    self.assertTrue(directory.exists())  # user-created directory or user-added hook remains
                    if not had_directory:
                        self.assertEqual(json.loads((directory / 'hooks.json').read_text()),
                                         {'user-hook': {'Stop': [{'command': 'echo keep'}]}})
                finally:
                    os.chdir(previous)
