"""Guards pack hardening from the 2026-10-19 bypass hunt. String-only: no candidate command is ever executed."""
import os
import posixpath
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from guard_hunt_cases import CASES
from ws import guards

FAKE = 'ghp_' + 'A1b2C3d4' * 5
SK = 'sk-' + 'Zy9x' * 8


def fill(value, home):
    if isinstance(value, str): return value.replace('@@HOME@@', home).replace('@@FAKE@@', FAKE).replace('@@SK@@', SK).replace('@@AKIA@@', 'AKIA')
    if isinstance(value, list): return [fill(v, home) for v in value]
    if isinstance(value, dict): return {k: fill(v, home) for k, v in value.items()}
    return value


class GuardTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        # A fixed POSIX-style home that is not under the temp folder: a home inside /tmp makes `rm -rf /tmp/*` a parent-of-home delete on Linux, and backslash paths lose their slashes in shlex on Windows.
        self.home = '/wsguard/home'  # last folder is `home`: the recorded `@@HOME@@/../home` round trip needs it
        self.work = str((Path(self.tmp.name) / 'work').resolve())  # a real folder for the cwd argument
        os.makedirs(self.work)
        patch = mock.patch.dict(os.environ, {'HOME': self.home, 'USERPROFILE': self.home}); patch.start(); self.addCleanup(patch.stop)

    def deny(self, command, tool='Bash'):
        return guards.reason(tool, {'command': command}, self.work)

    def check(self, denied=(), allowed=(), tool='Bash'):
        for command in denied:
            with self.subTest(deny=command): self.assertTrue(self.deny(command, tool), command)
        for command in allowed:
            with self.subTest(allow=command): self.assertEqual(self.deny(command, tool), '', command)


class HuntRegressionTests(GuardTestCase):
    def test_every_recorded_hunt_case(self):
        for tool, payload, want, label in CASES:
            payload = fill(payload, self.home)
            with self.subTest(label=label, payload=str(payload)[:100]):
                self.assertEqual('deny' if guards.reason(tool, payload, self.work) else 'allow', 'deny' if want == 'd' else 'allow')


class SegmentationTests(GuardTestCase):
    def test_wrapped_grouped_and_continued_commands_are_checked(self):
        self.check(denied=(
            '(cd repo && git reset --hard)', '(git push -f origin x)', '{ git reset --hard; }', 'for b in a b; do git push -f origin $b; done',
            'if [ -n "$X" ]; then git reset --hard; fi', 'while read b; do git push --force origin $b; done < list', 'if true; then :; else git clean -fd; fi',
            'echo $(git reset --hard)', 'x=$(git clean -fdx)', 'echo `git clean -fdx`', 'echo "$(git reset --hard)"', 'if ! git reset --hard; then :; fi',
            '(rm -rf ~)', '{ rm -rf ~; }', 'for d in a; do rm -rf ~; done', 'echo $(rm -rf ~)',
            'FOO=1 rm -rf ~', 'GIT_TRACE=1 git reset --hard', 'FOO=1 git push -f', 'A=1 B=2 git push --force',
            'env FOO=1 rm -rf ~', 'env -i git reset --hard', 'env -u X git reset --hard', 'env GIT_SSH_COMMAND=x git push --force',
            'sudo -u me git reset --hard', 'sudo -E rm -rf ~', 'sudo -- rm -rf ~', 'sudo -Eu me git push -f', 'command -p rm -rf ~', 'command -- rm -rf ~', 'time -p rm -rf ~',
            'timeout 30 git push -f', 'timeout -s KILL 5 git reset --hard', 'nice -n 5 rm -rf ~', 'nice -n5 git push -f', 'xargs -n1 git push -f', 'echo ~ | xargs rm -rf',
            'busybox rm -rf ~', 'doas rm -rf ~', 'setsid git push -f', 'stdbuf -o0 git reset --hard', 'ionice -c 3 rm -rf ~', 'nohup git push -f &', 'exec git reset --hard',
            '! rm -rf ~', 'echo a & rm -rf ~', 'echo a &rm -rf ~', 'ls |& rm -rf ~', 'echo ok;git reset --hard', 'true&&git reset --hard', 'false||git reset --hard',
            'rm \\\n-rf ~', 'rm -r\\\nf ~', 'git reset \\\n  --hard', 'git push \\\n  -f origin x', 'git push origin x \\\n  --force', 'git reset --hard\\',
            'sudo env FOO=1 timeout 5 nice -n 1 git push -f', 'echo hi\nrm -rf ~', 'wsl rm -rf ~', 'wsl -d Ubuntu -u me git reset --hard',
            'git --config-env a=B reset --hard', 'git --exec-path reset --hard', 'git --git-dir=x -C y reset --hard'))
        self.check(allowed=(
            'timeout 30 git status', 'sudo -u me ls', 'FOO=1 git status', 'env -i make', 'nice -n 5 make', 'xargs -n1 echo', 'echo ~ | xargs ls', 'echo a & ls',
            '(cd repo && git status)', '{ git status; }', 'for b in a b; do git fetch origin $b; done', 'git push --force-with-lease origin x', 'git push \\\n  --force-with-lease',
            'git reset \\\n  --soft HEAD~1', 'echo $(git status)', 'x=$(date)', 'sudo -u me git push origin x', 'rm -rf build', '(cd ~/proj && rm -rf build)', 'FOO=1 rm -rf ./dist'))

    def test_shell_strings_heredocs_and_pipes_into_a_shell_are_checked(self):
        self.check(denied=('bash <<EOF\nrm -rf ~\nEOF', "sh <<'EOF'\ngit reset --hard\nEOF", 'sh <<< "rm -rf ~"', "echo 'rm -rf ~' | sh", "echo 'git push -f' | bash", "su -c 'rm -rf ~'",
                           'bash -x -c "git reset --hard"', 'bash -l -c "git reset --hard"', 'bash --norc -c "git reset --hard"', "eval 'rm -rf ~'", 'eval rm -rf ~',
                           'cat <<EOF\n$(git reset --hard)\nEOF', 'cat <<EOF\n`git reset --hard`\nEOF'),
                   allowed=("cat <<'EOF'\n$(git reset --hard)\nEOF", 'bash script.sh', "echo 'ls' | sh", 'bash -c "git status"', "eval 'ls'", 'bash <<EOF\nls\nEOF'))


class QuotesAndHeredocFalsePositiveTests(GuardTestCase):
    def test_quoted_text_and_heredoc_bodies_are_data(self):
        self.check(allowed=(
            'git commit -m "fix; git push -f is blocked"', "echo 'a; git push -f'", 'echo "x | git clean -fd"', 'git commit -m "docs: a && git reset --hard && b"',
            "cat > docs.md <<'EOF'\nUse git push --force only on your own branch\nrm -rf ~ is blocked\nEOF",
            'git commit -m "$(cat <<\'EOF\'\nGuards: git push -f is dangerous\nand rm -rf ~ too\nEOF\n)"',
            'cat > notes.md <<EOF\ngit push -f\nEOF', 'echo x # y; rm -rf ~', "echo \"it's; fine\" && git status", 'grep -n "git push -f" README.md | head',
            "echo '(rm -rf ~)'", 'printf "%s\\n" "git reset --hard"'))

    def test_dry_runs_are_allowed(self):
        self.check(allowed=('git clean -n -f', 'git clean -fdn', 'git clean -nfd', 'git clean -dfn', 'git clean --dry-run -fd', 'git clean -fd --dry-run', 'git push -f --dry-run',
                            'git push -n -f', 'git push --dry-run --force', 'git push origin -- -f', 'git push origin HEAD -- -fn'),
                   denied=('git clean -fd', 'git clean -ffdx', 'git push -f', 'git push --force origin x', 'git push origin +main -- x'))
        self.check(allowed=('Remove-Item -Recurse -Force ~ -WhatIf', 'Get-ChildItem ~ | Remove-Item -r -fo -WhatIf', 'Remove-Item -Recurse -Force -whatif $HOME'),
                   denied=('Remove-Item -Recurse -Force ~', 'Get-ChildItem ~ | Remove-Item -r -fo'), tool='PowerShell')

    def test_code_identifiers_are_not_secrets(self):
        for code in ('token = self.refresh_token_v2()', 'password = get_password2(user)', 'api_key = config.api_key_v1', 'secret = settings.SECRET_KEY_2',
                     'const token = useAuthToken2();', 'password: Optional[str] = None', 'token = request.headers.get("x")', '$token = Get-Token2',
                     '$password = ConvertTo-SecureString $env:PW -AsPlainText -Force', 'api_key = os.environ["API_KEY"]', 'secret = process.env.APP_SECRET_2'):
            with self.subTest(code): self.assertEqual(guards.reason('Write', {'file_path': 'a.py', 'content': code + '\n'}), '', code)

    def test_lookalike_names_are_not_muted_tests(self):
        self.assertEqual(guards.reason('Edit', {'old_string': 'x', 'new_string': 'df.xit(1)\nmodel.fit(X, y)\ndef fit(model): pass'}), '')


class PowerShellEverywhereTests(GuardTestCase):
    def test_powershell_rules_run_under_every_tool_name(self):
        for tool in ('Bash', 'shell', 'shell_command', 'exec_command', 'local_shell', 'Monitor', 'PowerShell'):
            for command in ('Remove-Item -Recurse -Force ~', 'Remove-Item -r -fo $HOME', 'Remove-Item -Recurse -Force C:\\', 'ri -Recurse -Force "$env:USERPROFILE"'):
                with self.subTest(tool=tool, command=command): self.assertTrue(guards.reason(tool, {'command': command}, self.work))
            with self.subTest(tool=tool): self.assertEqual(guards.reason(tool, {'command': 'Remove-Item -Recurse -Force .\\build'}, self.work), '')

    def test_codex_payload_keys(self):
        self.assertTrue(guards.reason('exec_command', {'cmd': 'rm -rf ~'}))
        self.assertTrue(guards.reason('exec_command', {'cmd': ['bash', '-lc', 'git reset --hard']}))
        self.assertEqual(guards.reason('exec_command', {'cmd': 'git status'}), '')
        patch = '*** Begin Patch\n*** Update File: t.py\n-def test_a():\n+@pytest.mark.skip\n+def test_a():\n*** End Patch'
        self.assertTrue(guards.reason('apply_patch', {'input': patch}))
        self.assertTrue(guards.reason('Whatever', {'input': patch}))
        self.assertEqual(guards.reason('Whatever', {'input': 'rm -rf ~'}), '')  # `input` is only read as a patch
        self.assertEqual(guards.reason('apply_patch', {'input': '*** Begin Patch\n*** Update File: t.py\n-x = 1\n+x = 2\n*** End Patch'}), '')

    def test_positional_and_nested_powershell(self):
        self.check(denied=("pwsh 'Remove-Item -Recurse -Force ~'", 'powershell Remove-Item -Recurse -Force ~', 'pwsh -NoProfile -ExecutionPolicy Bypass Remove-Item -Recurse -Force ~',
                           'powershell -Command "& {Remove-Item -Recurse -Force ~}"', "pwsh -c \"iex 'Remove-Item -Recurse -Force ~'\"", "iex 'Remove-Item -Recurse -Force ~'",
                           'Invoke-Expression "Remove-Item -Recurse -Force ~"', 'powershell -Command "Remove-Item -Recurse -Force `"$HOME`""',
                           'if ($true) { Remove-Item -Recurse -Force ~ }', 'Start-Job { Remove-Item -Recurse -Force $HOME }', 'Invoke-Command -ScriptBlock { Remove-Item -r -fo C:\\ }',
                           'foreach ($x in 1) { Remove-Item -Recurse -Force ~ }', 'Remove-Item -Path:~ -Recurse -Force', 'Remove-Item -LiteralPath:$HOME -Recurse -Force',
                           'Remove-Item -Recurse -Force ${env:USERPROFILE}', 'Remove-Item -Recurse -Force $HOME\\*.*', 'Remove-Item -Recurse -Force $env:SystemDrive\\',
                           'cmd //c "rd /s /q C:\\"', 'cmd //c rd /s /q %USERPROFILE%', 'cmd /k "rmdir /s /q C:\\"'),
                   allowed=('pwsh -File build.ps1', 'pwsh -NoProfile -File x.ps1 -Recurse -Force', "pwsh 'Get-ChildItem'", 'powershell Get-Date', "iex 'Get-Date'",
                            'Remove-Item -Path:.\\build -Recurse -Force', 'cmd //c dir', 'cmd //c "rd /s /q build"', 'Start-Job { Remove-Item -Recurse -Force .\\x }'))


class HomeAndRootTests(GuardTestCase):
    def test_parents_of_home_and_mounted_drives_are_denied(self):
        self.check(denied=('rm -rf ~/..', 'rm -rf $HOME/..', 'rm -rf ~/../', 'rm -rf "$HOME/.."', f'rm -rf {posixpath.dirname(self.home)}', 'rm -rf /mnt/c', 'rm -rf /mnt/c/', 'rm -rf /cygdrive/c/',
                           'rm -rf /mnt/d/*', 'rm -r ~', 'rm -R $HOME', 'rm --recursive ~/', 'rm -r /', 'sudo rm -r ~'),
                   allowed=('rm -rf ~/proj/build', 'rm -r build', 'rm -r ~/.cache', 'rm -f ~', 'rm ~', 'rm -rf /tmp/x', 'rm -rf /a', 'rm -rf /d', 'rm -rf /mnt/data'))
        self.check(denied=('Remove-Item -Recurse -Force ~\\..', 'Remove-Item -Recurse -Force $HOME\\..'), tool='PowerShell')

    def test_a_cd_to_home_or_root_makes_wildcards_dangerous(self):
        self.check(denied=('cd ~ && rm -rf *', 'cd ~ && rm -rf .', 'cd && rm -rf *', 'cd $HOME; rm -rf ./*', 'cd / && rm -rf *', 'pushd ~ && rm -rf .*', '(cd ~ && rm -rf *)', 'cd ~\nrm -rf *',
                           'cd "$HOME" && rm -rf .'),
                   allowed=('cd ~/proj && rm -rf *', 'cd /tmp && rm -rf *', 'cd ~ && cd proj && rm -rf *', 'cd ~ && rm -rf build', 'rm -rf *', 'cd ~ && ls *', 'cd /tmp/x ; rm -rf .'))

    def test_a_bare_single_letter_folder_is_a_drive_only_on_a_windows_home(self):
        with mock.patch.object(os.path, 'expanduser', side_effect=lambda p: 'C:\\Users\\me' + p[1:] if p.startswith('~') else p):
            self.check(denied=('rm -rf /c', 'rm -rf /c/*', 'rm -rf /mnt/c', 'rm -rf C:/Users', 'rm -rf /c/Users'), allowed=('rm -rf /c/Users/me/proj', 'rm -rf /c/temp'))


class SecretsAndMutedTestsTests(GuardTestCase):
    def write(self, content, name='a.env'):
        return guards.reason('Write', {'file_path': name, 'content': content}, self.work)

    def test_short_named_passwords_are_secrets(self):
        for text in ('DB_PASSWORD=Sup3rS3cret', 'password=correcthorsebatterystaple', 'export DB_PASSWORD=hunter22', 'passwd: "abcdefgh"', 'pwd = "abcdefgh"', 'secret=abcdefghij', 'token: "abcdefghijk"',
                     '{"password": "abcdefgh"}', 'api_token=abcd1234'):
            with self.subTest(text):
                self.assertIn('secret', self.deny(text)); self.assertTrue(self.write(text))
        for text in ('DB_PASSWORD=hunter2', 'password=abc', 'password: Optional', 'pwd=/home/me/work', 'PWD=$(pwd)', 'password=********', 'password=xxxxxxxx', 'password=password', 'token=<your token>',
                     'password = "enter your password here"', 'DB_PASSWORD=changeme1', 'password=${DB_PASSWORD}', 'maxtoken=12345678', 'tokenizer=aaaaaaaaa', 'secret_key=abcdefghijk', 'token=12345678'):
            with self.subTest(text):
                self.assertEqual(self.deny(text), '', text); self.assertEqual(self.write(text), '', text)

    def test_private_key_block_forms(self):
        self.assertTrue(self.write('-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQOYBF\n-----END PGP PRIVATE KEY BLOCK-----\n', 'a.asc'))

    def test_more_ways_to_mute_a_test_are_denied(self):
        for added in ('pytest.skip("x")', 'self.skipTest("x")', '@pytest.mark.xfail', '@unittest.expectedFailure', '@unittest.skipUnless(False, "x")', '@skip', '@pytest.mark.skipif(not False, reason="x")',
                      "fit('a', () => {})", "fdescribe('a', () => {})", "it.skip.each([1])('a', f)", "test.only.each([1])('a', f)", "it.todo('a')", "it.failing('a', f)", "test.concurrent.skip('a', f)",
                      'this.skip()', 't.Skipf("x")', 'b.Skip("x")', '@Disabled', '@Ignore("x")', '#[ignore]', 'skip "x"', 'xit "x" do', "specify.skip('a', f)"):
            with self.subTest(added): self.assertTrue(guards.reason('Edit', {'file_path': 't', 'old_string': 'def test_a():', 'new_string': added + '\ndef test_a():'}), added)
        for added in ('@pytest.mark.skipif(sys.platform == "win32", reason="x")', 'df.xit(1)', 'model.fit(X, y)', 'def fit(self, X): pass', '@Override', 'skipped = 3'):
            with self.subTest(added): self.assertEqual(guards.reason('Edit', {'file_path': 't', 'old_string': 'def test_a():', 'new_string': added + '\ndef test_a():'}), '', added)

    def test_shell_edits_of_test_files_are_checked(self):
        self.check(denied=("sed -i 's/def test_a/@pytest.mark.skip\\ndef test_a/' tests/test_a.py", "sed -i 's/it(/it.only(/' app.test.js", "sed -i '' 's/test(/xtest(/' a.spec.js",
                           "cat >> tests/test_a.py <<'EOF'\n@pytest.mark.skip\ndef test_b(): pass\nEOF", "echo '@pytest.mark.skip' >> test_a.py", "perl -pi -e 's/it\\(/it.skip(/' a.test.js"),
                   allowed=("sed -i 's/@pytest.mark.skip//' tests/test_a.py", "sed -i 's/foo/bar/' tests/test_a.py", "grep -rn 'pytest.mark.skip' tests", "grep 'xit(' tests/a.spec.js > hits.txt",
                            "cat > docs.md <<'EOF'\n@pytest.mark.skip\nEOF", "echo 'it.skip(' > notes.txt", "sed -i 's/it(/it.only(/' app.js"))

    def test_notebook_edit_and_monitor_are_guarded(self):
        self.assertTrue(guards.reason('NotebookEdit', {'notebook_path': 'a.ipynb', 'new_source': 'API_KEY = "' + 'q7Rt' * 5 + '"'}))
        self.assertEqual(guards.reason('NotebookEdit', {'notebook_path': 'a.ipynb', 'new_source': 'print(1)'}), '')
        self.assertTrue(guards.reason('Monitor', {'command': 'git reset --hard'}))
        self.assertEqual(guards.reason('Monitor', {'command': 'tail -f log'}), '')


class DisablingTheGuardTests(GuardTestCase):
    HOOKS = '{"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 bin/ws guard --hook --client claude"}]}], "SessionStart": []}}'

    def test_removing_the_hook_from_settings_is_denied(self):
        remove = {'file_path': '.claude/settings.json', 'old_string': '"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "python3 bin/ws guard --hook --client claude"}]}], ', 'new_string': ''}
        why = guards.reason('Edit', remove)
        self.assertIn('Ask the user to remove the guards pack themselves.', why)
        self.assertTrue(guards.reason('Edit', {**remove, 'file_path': '.claude/settings.local.json'}))
        self.assertTrue(guards.reason('Edit', {**remove, 'file_path': '/home/me/.claude/settings.json'}))
        self.assertTrue(guards.reason('MultiEdit', {'file_path': '.codex/hooks.json', 'edits': [{'old_string': remove['old_string'], 'new_string': ''}]}))
        self.assertTrue(guards.reason('Edit', {'file_path': '.claude/settings.local.json', 'old_string': '{}', 'new_string': '{"env": {"WS_GUARDS": "off"}}'}))
        (Path(self.work) / '.claude').mkdir(); (Path(self.work) / '.claude/settings.json').write_text(self.HOOKS)
        self.assertTrue(guards.reason('Write', {'file_path': '.claude/settings.json', 'content': '{"hooks": {}}'}, self.work))
        self.assertEqual(guards.reason('Write', {'file_path': '.claude/settings.json', 'content': self.HOOKS.replace('"SessionStart": []', '"Stop": []')}, self.work), '')

    def test_other_edits_of_those_files_and_other_files_are_allowed(self):
        self.assertEqual(guards.reason('Edit', {'file_path': '.claude/settings.json', 'old_string': '"matcher": "Bash"', 'new_string': '"matcher": "Bash|Write"'}), '')
        self.assertEqual(guards.reason('Edit', {'file_path': 'other/settings.json', 'old_string': '"PreToolUse": [], ', 'new_string': ''}), '')
        self.assertEqual(guards.reason('Edit', {'file_path': '.claude/settings.json', 'old_string': '"permissions": {}', 'new_string': '"permissions": {"allow": ["Bash(ls)"]}'}), '')

    def test_patch_and_shell_routes(self):
        patch = '*** Begin Patch\n*** Update File: .codex/hooks.json\n-      "PreToolUse": [],\n*** End Patch'
        self.assertIn('guards', guards.reason('apply_patch', {'command': patch}))
        self.assertTrue(guards.reason('apply_patch', {'command': '*** Begin Patch\n*** Delete File: .codex/hooks.json\n*** End Patch'}))
        self.assertEqual(guards.reason('apply_patch', {'command': '*** Begin Patch\n*** Update File: .codex/hooks.json\n-  "a": 1\n+  "a": 2\n*** End Patch'}), '')
        self.check(denied=('ws pack remove guards', 'python3 bin/ws pack remove guards', 'cd x && ./bin/ws --workspace-root . pack remove guards', 'rm .claude/settings.json', 'mv .claude/settings.json /tmp/x',
                           "sed -i 's/guard//' .claude/settings.json", 'jq . x > .claude/settings.local.json', 'echo {} > .codex/hooks.json', 'rm -f ~/.claude/settings.json', 'bash -c "ws pack remove guards"',
                           'echo hi >> .claude/settings.json'),  # appending breaks the JSON, which switches the hooks off
                   allowed=('ws pack add guards', 'ws pack remove ios', 'cat .claude/settings.json', 'cat .claude/settings.json > /tmp/x', 'git add .claude/settings.json', 'ls .codex', 'rm settings.json',
                            'echo hi >> notes/settings.json'))
        self.assertIn('Ask the user to remove the guards pack themselves.', self.deny('ws pack remove guards'))


class LinearTimeTests(GuardTestCase):
    def decide(self, command, tool='Bash'):
        start = time.perf_counter()
        why = guards.reason(tool, {'command': command}, self.work)
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 5.0, f'{len(command)} bytes took {elapsed:.2f}s')
        return why

    def test_the_hunts_slow_inputs_decide_quickly(self):
        for size in (20000, 200000):
            inputs = {'colons': 'a:' * (size // 2), 'path': '/a' * (size // 2), 'heredoc': "cat <<'EOF'\n" + 'word powershell ' * (size // 16) + '\nEOF', 'words': 'powershell ' * (size // 11),
                      'wrappers': 'powershell -c x; ' * (size // 17), 'cmd': 'cmd /c x && ' * (size // 12), 'parens': '(' * size, 'subs': '$(' * (size // 2), 'quotes': '"' * size,
                      'newlines': '\n' * size, 'backslashes': '\\' * size, 'sudo': 'sudo ' * (size // 5), 'env': 'FOO=1 ' * (size // 6), 'timeout': 'timeout 5 ' * (size // 10),
                      'markers': '<<A ' * (size // 4), 'passwords': 'password=aaaaaaaa ' * (size // 18), 'enc': 'pwsh -enc ' + 'A' * size, 'skips': '@pytest.mark.skip ' * (size // 18)}
            for name, text in inputs.items():
                for tool in ('Bash', 'PowerShell'):
                    with self.subTest(size=size, name=name, tool=tool): self.decide(text, tool)

    def test_padding_cannot_hide_a_destructive_command(self):
        for size in (20000, 200000):
            for pad in ('a:' * (size // 2), '/a' * (size // 2), 'x' * size):
                with self.subTest(size=size, pad=pad[:4]):
                    self.assertTrue(self.decide(f': {pad}; git reset --hard'))
                    self.assertTrue(self.decide(f': {pad}; rm -rf ~', 'PowerShell'))
                    self.assertTrue(self.decide(f"cat <<'EOF'\n{'powershell ' * (size // 11)}\nEOF\ngit reset --hard"))
                    self.assertEqual(self.decide(f"cat <<'EOF'\n{'powershell git push -f ' * (size // 22)}\nEOF"), '')

    def test_too_many_nested_commands_are_denied_not_allowed(self):
        self.assertIn('too long', self.decide('powershell -c x; ' * 20000))
        self.assertIn('nested too deeply', guards.command_reason('bash -c "git status"', False, None, 21))
        self.assertEqual(guards.command_reason('bash -c "git status"', False, None, 19), '')
        self.assertEqual(self.deny("bash -c 'ls'"), '')


if __name__ == '__main__':
    unittest.main()
