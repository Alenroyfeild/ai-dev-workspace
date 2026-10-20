"""Ways the assistant could switch the ws guards off (review of PR 255). String-only: no candidate command is ever executed."""
import json
import unittest
from pathlib import Path
from unittest import mock

from test_guards_hunt import GuardTestCase
from ws import guards

ASK = 'Ask the user to remove the guards pack themselves.'
GUARD = 'python3 /kit/bin/ws --workspace-root /ws guard --hook --client claude'
MATCHER = 'Bash|PowerShell|Write|Edit|MultiEdit|Monitor|NotebookEdit'


def config(command=GUARD, matcher=MATCHER, **extra):
    group = {'hooks': [{'type': 'command', 'timeout': 10, 'command': command}]}
    if matcher is not None: group['matcher'] = matcher
    return json.dumps({'hooks': {'PreToolUse': [group], 'SessionStart': []}, 'permissions': {}, **extra}, indent=2) + '\n'


class ShellRoutesTests(GuardTestCase):
    def test_adjacent_redirects_onto_hook_files_are_denied(self):
        for op in ('>', '>>', '1>', '2>', '&>', '>|', '2>>', '&>>'):
            for target in ('.codex/hooks.json', '.claude/settings.local.json', '.claude/settings.json'):
                with self.subTest(op=op, target=target):
                    for command in (f"echo '{{}}'{op}{target}", f'echo {{}}{op}{target}', f'echo {{}} {op}{target}', f'echo {{}} {op} {target}'):
                        self.assertIn(ASK, self.deny(command), command)
        self.assertIn(ASK, self.deny("echo '{}'>.codex/hooks.json", 'PowerShell'))
        self.assertIn(ASK, self.deny("echo '{}'>.codex\\hooks.json", 'PowerShell'))
        self.assertIn(ASK, self.deny("'{}' > .claude\\settings.json"))  # PowerShell text under a Bash-named tool

    def test_redirects_elsewhere_and_data_are_allowed(self):
        self.check(allowed=("echo '{}'>/tmp/x.json", 'echo hi>notes.txt', 'ls 2>&1', 'ls 2>/dev/null', 'cat .claude/settings.json>/tmp/x', 'cat .claude/settings.json 2>&1 | head',
                            'git commit -m "a > .claude/settings.json"', 'echo hi > other/settings.json', 'cp .claude/settings.json /tmp/backup.json',
                            'cat x.json > /dev/null && ls'))

    def test_overwrite_copy_move_and_link_onto_hook_files_are_denied(self):
        self.check(denied=('cp /tmp/empty .claude/settings.local.json', 'cp -f /tmp/empty .claude/settings.json', 'cp /tmp/empty .claude/settings.json > /dev/null', 'mv /tmp/empty .claude/settings.local.json',
                           'mv .claude/settings.json /tmp/x', 'echo {} | tee .claude/settings.json', 'echo {} | tee -a .codex/hooks.json', 'dd if=/tmp/empty of=.claude/settings.local.json',
                           'dd of=.codex/hooks.json if=/dev/null', 'install -m 644 /tmp/empty .claude/settings.json', 'ln -sf /dev/null .claude/settings.local.json', 'ln -sf /tmp/empty .codex/hooks.json',
                           'sudo cp /tmp/empty .claude/settings.json', 'bash -c "cp /tmp/empty .claude/settings.json"', 'cd x && cp /tmp/e ./.claude/settings.local.json', 'cp a b ~/.claude/settings.json'))
        self.assertIn(ASK, self.deny('cp /tmp/empty .claude/settings.local.json'))

    def test_copy_from_or_into_other_files_is_allowed(self):
        self.check(allowed=('cp .claude/settings.json /tmp/backup.json', 'cp .claude/settings.json .claude/settings.json.bak', 'install .claude/settings.json /tmp', 'ln -s .claude/settings.json /tmp/link',
                            'dd if=.claude/settings.json of=/tmp/x', 'cp /tmp/a other/settings.json', 'cp /tmp/a .claude/commands.md', 'tee /tmp/log', 'ln -sf /tmp/a .claude/skills'))

    def test_powershell_writers_onto_hook_files_are_denied(self):
        for command in ('Set-Content .claude/settings.local.json "{}"', 'Set-Content -Path .claude\\settings.json -Value "{}"', 'Set-Content -Path:.claude\\settings.json "{}"', "'{}' | Out-File .codex\\hooks.json",
                        'Out-File -FilePath .codex/hooks.json', 'Add-Content .claude/settings.json "x"', 'Copy-Item C:\\tmp\\empty.json .claude\\settings.local.json', 'Copy-Item -Path C:\\a -Destination .claude\\settings.json',
                        'Move-Item C:\\tmp\\empty.json .claude\\settings.local.json', 'Move-Item .codex/hooks.json C:\\tmp', 'sc .claude/settings.json x', 'copy C:\\a .claude\\settings.json', 'Clear-Content .claude/settings.json',
                        'Remove-Item .claude/settings.json', 'Rename-Item .codex\\hooks.json x.json'):
            for tool in ('PowerShell', 'Bash'):
                with self.subTest(command=command, tool=tool): self.assertIn(ASK, self.deny(command, tool))
        self.assertIn(ASK, self.deny('powershell -Command "Set-Content .claude/settings.json x"'))

    def test_powershell_reads_and_other_targets_are_allowed(self):
        for command in ('Get-Content .claude/settings.json', 'Copy-Item .claude\\settings.json C:\\tmp\\backup.json', 'Set-Content notes.txt "x"', 'Out-File other\\settings.json',
                        'Copy-Item C:\\a .claude\\commands', 'Get-Content .claude/settings.json | Set-Content backup.json'):
            for tool in ('PowerShell', 'Bash'):
                with self.subTest(command=command, tool=tool): self.assertEqual(self.deny(command, tool), '', command)

    def test_ws_start_undo_is_denied(self):
        for command in ('ws start --undo', './bin/ws start --undo', 'ws --workspace-root . start --undo', 'python3 /kit/bin/ws start --undo', 'python3 -m ws start --undo', 'ws start --und', 'ws start --yes --undo',
                        'bash -c "ws start --undo"', 'cd repo && ws start --undo', 'ws-plugin start --undo', 'env X=1 ws start --undo'):
            with self.subTest(command=command): self.assertIn(ASK, self.deny(command))
        self.assertIn(ASK, self.deny('ws start --undo', 'PowerShell'))
        self.check(allowed=('ws start', 'ws start --dry-run', 'ws start --yes', 'ws status', 'echo start --undo', 'git start --undo', 'ws task start --undo-me', 'ws pack add guards'))


    def test_undo_text_is_data_unless_ws_is_the_command(self):
        self.check(allowed=('echo ws start --undo', "printf '%s' 'ws start --undo'", 'python3 -c "print(\"ws start --undo\")"',
                            'ws task start --undo', 'ws --workspace-root start status --undo'))
        self.check(denied=('sudo ws start --undo', 'env X=1 python3 -m ws start --undo',
                           'ws --workspace-root=. start --undo', 'bash -c "ws start --undo"'))


class WrapperLongOptionTests(GuardTestCase):
    def test_long_wrapper_options_with_a_separate_value_still_reach_the_command(self):
        for prefix in ('sudo --user root', 'sudo --group staff', 'sudo --host box', 'sudo --prompt p', 'sudo --chdir /tmp', 'sudo --close-from 5', 'sudo --role r', 'sudo --type t', 'sudo --other-user me',
                       'sudo --user root --preserve-env', 'sudo --non-interactive --user root', 'sudo --us root', 'env --chdir /tmp', 'env --unset FOO', 'env --ignore-environment --unset FOO', 'env --chdir /tmp --unset X',
                       'timeout --signal KILL 5', 'timeout --kill-after 3 5', 'timeout --signal=KILL --kill-after 3 5', 'nice --adjustment 5', 'nice --adjustment=5', 'sudo --user=root', 'env --chdir=/tmp', 'sudo -u root',
                       'env -C /tmp', 'env -u FOO', 'timeout -s KILL 5', 'nice -n 5', 'stdbuf --output L', 'ionice --class 2'):
            for command in ('git reset --hard', 'git push --force origin x', 'rm -rf ~'):
                with self.subTest(prefix=prefix, command=command): self.assertTrue(self.deny(f'{prefix} {command}'), f'{prefix} {command}')

    def test_safe_commands_behind_those_options_are_allowed(self):
        self.check(allowed=('sudo --user root git status', 'env --chdir /tmp git status', 'env --unset FOO git log', 'timeout --signal KILL 5 git status', 'nice --adjustment 5 git diff', 'sudo --user=root ls',
                            'sudo --user root rm -rf build', 'env --chdir /tmp rm -rf build'))


    def test_env_split_strings_are_commands_not_discarded_option_values(self):
        for option in ("-S '{cmd}'", "--split-string '{cmd}'", "--split-string='{cmd}'", "-S'{cmd}'"):
            for command in ('git reset --hard', 'rm -rf ~', 'ws start --undo'):
                with self.subTest(option=option, command=command):
                    self.assertTrue(self.deny('sudo env -i ' + option.format(cmd=command)))
            self.assertEqual(self.deny('env ' + option.format(cmd='git status')), '')
            self.assertEqual(self.deny('env ' + option.format(cmd='echo ws start --undo')), '')
        self.assertTrue(self.deny("env -S 'git reset' --hard"))
        self.assertEqual(self.deny("env -S 'echo' 'git reset --hard'"), '')


class EditRouteTests(GuardTestCase):
    def put(self, text, name='.claude/settings.local.json'):
        path = Path(self.work) / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')
        return name

    def edit(self, name, old, new, tool='Edit'):
        return guards.reason(tool, {'file_path': name, 'old_string': old, 'new_string': new}, self.work)

    def test_changing_the_guard_command_or_matcher_is_denied_even_if_the_words_remain(self):
        name = self.put(config())
        for old, new in ((GUARD, 'echo guard'), (GUARD, 'echo guard --hook PreToolUse'), (GUARD, GUARD + ' || true'), ('guard --hook', 'guard --hook-off'), ('"matcher": "' + MATCHER + '"', '"matcher": "NoSuchTool"'),
                         ('"matcher": "' + MATCHER + '"', '"matcher": "Bash"'), ('"matcher": "' + MATCHER + '"', '"matcher": "Read"'), ('"PreToolUse"', '"PostToolUse"'), ('"type": "command"', '"type": "prompt"')):
            with self.subTest(old=old, new=new): self.assertIn(ASK, self.edit(name, old, new))
        self.assertIn(ASK, self.edit(name, '"command"', '"cmd"'))

    def test_removing_the_entry_or_the_file_content_is_denied(self):
        name = self.put(config())
        self.assertIn(ASK, guards.reason('Write', {'file_path': name, 'content': '{}\n'}, self.work))
        self.assertIn(ASK, guards.reason('Write', {'file_path': name, 'content': '{ not json'}, self.work))
        self.assertIn(ASK, guards.reason('Write', {'file_path': name, 'content': json.dumps({'hooks': {'PreToolUse': []}})}, self.work))
        self.assertIn(ASK, guards.reason('MultiEdit', {'file_path': name, 'edits': [{'old_string': 'python3', 'new_string': 'true'}, {'old_string': '"timeout": 10', 'new_string': '"timeout": 11'}]}, self.work))
        self.assertIn(ASK, self.edit(name, '"permissions": {}', '"disableAllHooks": true'))
        self.assertIn(ASK, self.edit(name, '"permissions": {}', '"env": {"WS_GUARDS": "off"}'))
        other = self.put(config(), '.codex/hooks.json')
        self.assertIn(ASK, self.edit(other, GUARD, 'true'))

    def test_a_replace_all_edit_and_an_edit_of_an_absolute_path_are_checked(self):
        name = self.put(config())
        self.assertIn(ASK, guards.reason('Edit', {'file_path': str(Path(self.work) / name), 'old_string': 'guard', 'new_string': 'guarx', 'replace_all': True}, self.work))
        self.assertEqual(guards.reason('Edit', {'file_path': str(Path(self.work) / name), 'old_string': '"permissions": {}', 'new_string': '"permissions": {"allow": ["Bash(ls)"]}'}, self.work), '')

    def test_unrelated_edits_of_those_files_are_allowed(self):
        name = self.put(config())
        self.assertEqual(self.edit(name, '"permissions": {}', '"permissions": {"allow": ["Bash(ls)"]}'), '')
        self.assertEqual(self.edit(name, '"SessionStart": []', '"Stop": []'), '')
        self.assertEqual(self.edit(name, '"matcher": "' + MATCHER + '"', '"matcher": "' + MATCHER + '|Read"'), '')  # wider than before still covers every guarded tool
        self.assertEqual(self.edit(name, '"timeout": 10', '"timeout": 20'), '')
        self.assertEqual(guards.reason('Write', {'file_path': name, 'content': config(model='opus')}, self.work), '')
        self.assertEqual(guards.reason('Write', {'file_path': name, 'content': config(matcher='*')}, self.work), '')
        self.assertEqual(guards.reason('Write', {'file_path': name, 'content': config(matcher=None)}, self.work), '')
        self.assertEqual(self.edit(name, 'no such text', 'x'), '')  # the edit would fail on its own
        plain = self.put('{"permissions": {}}\n', '.claude/settings.json')
        self.assertEqual(self.edit(plain, '"permissions": {}', '"hooks": {}'), '')  # no guard hook there to protect
        self.assertEqual(guards.reason('Write', {'file_path': 'notes.json', 'content': '{}'}, self.work), '')

    def test_quoted_windows_guard_commands_are_protected(self):
        from ws import core
        with mock.patch.object(core, 'WINDOWS', True):
            command = core.command_line([r'C:\Python\python.exe', r'C:\kit\bin\ws', '--workspace-root', r'C:\ws', 'guard', '--hook', '--client', 'claude'])
            name = self.put(config(command))
            self.assertIn(ASK, guards.reason('Write', {'file_path': name, 'content': '{}'}, self.work))
            self.assertEqual(self.edit(name, '"permissions": {}', '"model": "opus"'), '')

    def test_encoded_windows_launcher_entries_are_recognized(self):
        from ws import core
        command = core.encoded_hook_command(['C:\\Python\\python.exe', 'C:\\kit\\bin\\ws', '--workspace-root', 'C:\\ws', 'guard', '--hook', '--client', 'claude'])
        name = self.put(config(command))
        self.assertIn(ASK, self.edit(name, command, 'echo guard'))
        self.assertEqual(self.edit(name, '"permissions": {}', '"model": "opus"'), '')

    def test_other_pretooluse_hooks_are_not_ours_to_protect(self):
        name = self.put(config('echo audit'))
        self.assertEqual(self.edit(name, 'echo audit', 'echo other'), '')


class PatchRouteTests(GuardTestCase):
    def put(self, text, name):
        path = Path(self.work) / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding='utf-8')

    def patch(self, *sections):
        return guards.reason('apply_patch', {'command': '*** Begin Patch\n' + '\n'.join(sections) + '\n*** End Patch'}, self.work)

    def test_patch_that_changes_the_guard_command_is_denied(self):
        self.put(config(), '.codex/hooks.json')
        why = self.patch('*** Update File: .codex/hooks.json', '@@', f'-        "command": "{GUARD}"', '+        "command": "echo guard"')
        self.assertIn(ASK, why)

    def test_a_hook_removal_cannot_be_masked_by_text_in_another_file(self):
        self.put(config(), '.claude/settings.json'); self.put('{"hooks": {}}\n', '.claude/settings.local.json')
        removal = ['*** Update File: .claude/settings.json', '@@', '-  "hooks": {', '-    "PreToolUse": [', '+  "hooks": {', '+    "PostToolUse": [']
        masking = ['*** Update File: .claude/settings.local.json', '@@', '-{"hooks": {}}', '+{"hooks": {"PreToolUse": [{"hooks": [{"command": "x guard"}]}]}}']
        self.assertIn(ASK, self.patch(*removal)); self.assertIn(ASK, self.patch(*masking, *removal)); self.assertIn(ASK, self.patch(*removal, *masking))

    def test_a_new_secret_or_skip_in_one_file_is_not_masked_by_a_removal_in_another(self):
        self.put('@pytest.mark.skip\ndef test_old(): pass\n', 'tests/test_old.py'); self.put('def test_b(): pass\n', 'tests/test_b.py')
        why = self.patch('*** Update File: tests/test_old.py', '@@', '-@pytest.mark.skip', '+', '*** Update File: tests/test_b.py', '@@', '+@pytest.mark.skip', ' def test_b(): pass')
        self.assertIn('skips', why)

    def test_move_delete_and_add_of_hook_files(self):
        self.put(config(), '.codex/hooks.json')
        self.assertIn(ASK, self.patch('*** Delete File: .codex/hooks.json'))
        self.assertIn(ASK, self.patch('*** Update File: .codex/hooks.json', '*** Move to: /tmp/x.json', '@@', ' {'))
        self.assertIn(ASK, self.patch('*** Add File: .codex/hooks.json', '+{}'))

    def test_unrelated_patches_are_allowed(self):
        self.put(config(), '.codex/hooks.json'); self.put('x = 1\n', 'a.py')
        self.assertEqual(self.patch('*** Update File: .codex/hooks.json', '@@', '-  "permissions": {}', '+  "permissions": {"allow": []}'), '')
        self.assertEqual(self.patch('*** Update File: a.py', '@@', '-x = 1', '+x = 2'), '')
        self.assertEqual(self.patch('*** Add File: new.py', '+print(1)'), '')
        self.assertEqual(self.patch('*** Update File: .codex/hooks.json', '@@', '-    "SessionStart": []', '+    "Stop": []', '*** Update File: a.py', '@@', '-x = 1', '+x = 3'), '')


if __name__ == '__main__':
    unittest.main()
