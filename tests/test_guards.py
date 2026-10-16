import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import core, guards

KIT = Path(__file__).resolve().parents[1]


class GuardRuleTests(unittest.TestCase):
    def deny(self, command):
        return guards.reason('Bash', {'command': command})

    def test_destructive_commands_are_denied(self):
        for command in ('rm -rf ~', 'rm -fr /', 'sudo rm -rf "$HOME"', 'cd x && rm -r -f ~/', 'git reset --hard HEAD~1',
                        'git push -f origin main', 'git push --force', 'git push origin +main', 'git clean -fdx',
                        "bash -lc 'git reset --hard'", 'echo ok; git push -uf origin x'):
            with self.subTest(command): self.assertTrue(self.deny(command))

    def test_review_findings_git_options_long_flags_token_swap_skipif(self):
        for command in ('git -C sample reset --hard', 'git -C sample push -f', 'git -c core.x=1 --no-pager reset --hard', 'git clean --force -d'):
            with self.subTest(command): self.assertTrue(self.deny(command))
        self.assertEqual(self.deny('git -C sample status'), '')
        old, new = 'ghp_' + 'A1b2' * 9, 'ghp_' + 'C3d4' * 9
        self.assertTrue(guards.reason('Edit', {'old_string': 'TOKEN = "' + old + '"', 'new_string': 'TOKEN = "' + new + '"'}))
        self.assertEqual(guards.reason('Edit', {'old_string': 'TOKEN = "' + old + '"', 'new_string': '# TOKEN = "' + old + '"'}), '')
        for added in ('@pytest.mark.skipif(True, reason="x")', '@unittest.skipIf(1, "x")'):
            with self.subTest(added): self.assertTrue(guards.reason('Edit', {'old_string': 'def test_a():', 'new_string': added + '\ndef test_a():'}))
        self.assertEqual(guards.reason('Edit', {'old_string': 'def test_a():', 'new_string': '@pytest.mark.skipif(sys.platform == "win32", reason="posix")\ndef test_a():'}), '')

    def test_everyday_commands_are_allowed(self):
        for command in ('rm -rf build/', 'rm -rf ./dist', 'rm file.txt', 'git reset HEAD~1', 'git reset --soft HEAD~1',
                        'git push --force-with-lease', 'git push -u origin feature', 'git clean -n', 'echo "rm -rf ~"',
                        'grep -rf patterns.txt .', 'git log --format=%H'):
            with self.subTest(command): self.assertEqual(self.deny(command), '')

    def test_powershell_destructive_commands_are_denied(self):
        for command in ('Remove-Item -Recurse -Force ~', 'remove-item $HOME -recurse -force', 'rm -r -fo $env:USERPROFILE', 'ri -Recurse -Force C:\\',
                        'del C:/ -r -f', 'Remove-Item -Force -Recurse -Path "C:\\*"', 'rd / -Recurse -Force', 'erase -Recurse -Force \\',
                        'rmdir ~/* -r -f', 'Remove-Item -Recurse:$true -Force -Path ~\\*', 'cd x; Remove-Item -Recurse -Force D:\\',
                        'git reset --hard', 'git -C sample push -f', 'git clean -fdx', 'Get-Date; git push --force origin main',
                        'git status && git reset --hard HEAD~1', 'git log | git clean -f', 'git status\ngit push -f',
                        'echo ' + 'ghp_' + 'A1b2' * 9, '$env:API_KEY = "' + 'q7Rt' * 5 + '"'):
            with self.subTest(command): self.assertTrue(guards.reason('PowerShell', {'command': command}))

    def test_powershell_everyday_commands_are_allowed(self):
        for command in ('Remove-Item -Recurse -Force .\\build', 'rm -r -fo dist', 'Remove-Item ~', 'Remove-Item -Recurse $HOME\\old',
                        'Remove-Item C:\\temp\\x -Recurse -Force', 'Remove-Item -Force C:\\', 'Get-ChildItem ~', 'git status', 'git reset --soft HEAD~1',
                        'git push --force-with-lease', 'Write-Output "Remove-Item -Recurse -Force ~"', '$env:API_KEY = $env:OTHER'):
            with self.subTest(command): self.assertEqual(guards.reason('PowerShell', {'command': command}), '')

    def test_powershell_rules_do_not_apply_to_other_tools(self):
        self.assertEqual(self.deny('Remove-Item -Recurse -Force ~'), '')
        self.assertEqual(guards.reason('SomeNewTool', {'path': 'x'}), '')
        self.assertEqual(guards.reason('SomeNewTool', None), '')

    def test_codex_argv_command_is_unwrapped(self):
        self.assertTrue(guards.reason('shell', {'command': ['bash', '-lc', 'git reset --hard']}))
        self.assertEqual(guards.reason('shell', {'command': ['bash', '-lc', 'git status']}), '')

    def test_secret_in_command_is_denied(self):
        self.assertIn('secret', self.deny('curl -H "Authorization: Bearer ghp_' + 'a' * 36 + '" https://x.invalid'))

    def test_variable_references_and_placeholders_are_not_secrets(self):
        for command in ('export API_KEY=$API_KEY', 'GITHUB_TOKEN="${GITHUB_TOKEN}" make release', 'psql postgres://user:password@localhost/db',
                        'echo "token: <your-token-here>"'):
            with self.subTest(command): self.assertEqual(self.deny(command), '')
        self.assertEqual(guards.reason('Write', {'file_path': '.env.example', 'content': 'API_KEY=your-api-key-here\nDB_PASSWORD=changeme\n'}), '')

    def test_placeholder_words_only_skip_at_the_start(self):
        self.assertIn('secret', self.deny('export API_KEY=q7Rt9yourZ8kLm2'))  # a real value that happens to contain "your"
        self.assertEqual(self.deny('export API_KEY=your-api-key-here1'), '')

    def test_real_looking_tokens_are_denied(self):
        for command in ('gh auth login --with-token ghp_' + 'A1b2' * 9, 'curl -u x:sk-' + 'Z9y8' * 6 + ' https://x.invalid',
                        'export AWS_ACCESS_KEY_ID=AKIA' + 'ABCD1234EFGH5678', 'export API_KEY=' + 'q7Rt' * 5):
            with self.subTest(command): self.assertIn('secret', self.deny(command))
        self.assertTrue(guards.reason('Write', {'file_path': 'k.pem', 'content': '-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----\n'}))

    def test_padded_bearer_and_authorization_values_are_denied(self):
        value = 'Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA=='
        for text in ('Authorization: Bearer ' + value, 'curl -H "Authorization: Bearer ' + value + '" https://x.invalid', 'Bearer ' + value):
            with self.subTest(text): self.assertIn('secret', self.deny(text))
        self.assertTrue(guards.reason('Edit', {'old_string': 'x', 'new_string': 'Authorization: Bearer ' + value}))

    def test_newly_skipped_tests_are_denied(self):
        self.assertTrue(guards.reason('Edit', {'file_path': 't.py', 'old_string': 'def test_a():', 'new_string': '@unittest.skip("x")\ndef test_a():'}))
        self.assertTrue(guards.reason('Edit', {'old_string': "it('works'", 'new_string': "it.only('works'"}))
        self.assertTrue(guards.reason('apply_patch', {'command': "*** Begin Patch\n*** Update File: a.test.js\n-it('a', f)\n+xit('a', f)\n*** End Patch"}))

    def test_existing_skip_moved_or_kept_is_allowed(self):
        self.assertEqual(guards.reason('Edit', {'old_string': '@pytest.mark.skip\ndef test_a(): pass', 'new_string': '@pytest.mark.skip\ndef test_a(): return'}), '')
        self.assertEqual(guards.reason('Write', {'file_path': 'new.py', 'content': 'print(1)\n'}), '')

    def test_off_switch_and_bad_input_allow(self):
        with mock.patch.dict(os.environ, {'WS_GUARDS': 'off'}): self.assertEqual(self.deny('git reset --hard'), '')
        self.assertEqual(guards.reason('Bash', None), '')
        self.assertEqual(guards.reason('Bash', {'command': 42}), '')

    def test_hook_cli_denies_in_the_shared_format_and_fails_open(self):
        run = lambda data: subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'guard', '--hook', '--client', 'codex'], input=data,
                                          capture_output=True, text=True, cwd=KIT)
        result = run(json.dumps({'hook_event_name': 'PreToolUse', 'tool_name': 'Bash', 'tool_input': {'command': 'git push -f'}}))
        out = json.loads(result.stdout)['hookSpecificOutput']
        self.assertEqual((result.returncode, out['hookEventName'], out['permissionDecision']), (0, 'PreToolUse', 'deny'))
        self.assertIn('WS_GUARDS=off', out['permissionDecisionReason'])
        self.assertEqual(json.loads(run('not json').stdout), {})


class GuardHookWiringTests(Base):
    def test_pre_tool_use_hook_only_with_the_pack(self):
        self.assertEqual(core.pack_hooks(self.root, 'claude'), {})
        result = core.pack_add(self.root, 'guards')
        self.assertTrue(any('ws start again' in line for line in result['next']))
        claude = core.pack_hooks(self.root, 'claude')['PreToolUse'][0]
        codex = core.pack_hooks(self.root, 'codex')['PreToolUse'][0]
        self.assertEqual(claude['matcher'], 'Bash|PowerShell|Write|Edit|MultiEdit')
        self.assertNotIn('matcher', codex)
        self.assertTrue(codex['hooks'][0]['command'].endswith(core.command_line(['guard', '--hook', '--client', 'codex'])))  # Windows quotes args
        self.assertEqual(core.pack_hooks(self.root, 'cursor'), {})
        self.assertNotIn('PreToolUse', core.memory_hooks(self.root, 'claude')['hooks'])  # kit fingerprint unchanged

    def test_remove_drops_rules_and_config_only(self):
        agents = (self.root / 'AGENTS.md').read_text()
        core.pack_add(self.root, 'guards')
        self.assertIn('## Guards pack', (self.root / 'AGENTS.md').read_text())
        from ws import packs
        result = packs.remove(self.root, 'guards')
        self.assertEqual((result['removed'], result['kept']), (True, []))
        self.assertEqual((self.root / 'AGENTS.md').read_text().rstrip('\n'), agents.rstrip('\n'))
        self.assertNotIn('guards', core.config(self.root)['packs'])
        with self.assertRaises(core.WsError): packs.remove(self.root, 'ios')  # built-in pack with vault files
