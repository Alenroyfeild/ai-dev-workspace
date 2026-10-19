"""Windows hardening round 2: every case simulates Windows (mocked core.WINDOWS, home, errors), so it runs on macOS, Linux and Windows CI."""
import base64
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_ws import Base, KIT
from ws import cli, core, guards, upgrade, workers

WIN_HOME = 'C:\\Users\\me'


class WindowsGuardTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(os.path, 'expanduser', side_effect=lambda p: WIN_HOME + p[1:] if p.startswith('~') else p)
        patch.start(); self.addCleanup(patch.stop)

    def deny(self, command, tool='Bash'):
        return guards.reason(tool, {'command': command})

    def test_git_bash_drive_and_home_forms_are_denied(self):
        for command in ('rm -rf /c/*', 'rm -rf /c', 'rm -rf /c/', 'rm -rf C:/', 'rm -rf C:/*', 'rm -rf c:', 'rm -rf C:\\\\', 'rm -rf /c/Users/me', 'rm -rf /c/Users/me/*',
                        'rm -rf /C/users/ME', 'rm -rf C:/Users/me', 'rm -rf "$USERPROFILE"', 'rm -rf $USERPROFILE/*', 'rm -rf ${USERPROFILE}',
                        'rm -rf %USERPROFILE%', 'rm -rf $env:USERPROFILE', 'rm -rf "%USERPROFILE%/."', 'rm -fr /d/*', 'rm -r -f /c/*'):
            with self.subTest(command): self.assertTrue(self.deny(command))

    def test_subpaths_and_other_folders_are_allowed(self):
        for command in ('rm -rf C:/Users/me/project/build', 'rm -rf /c/Users/me/project/build', 'rm -rf "$USERPROFILE/project/build"',
                        'rm -rf %USERPROFILE%/x', 'rm -rf C:/Users/me/.cache/x', 'rm -rf C:/temp/x', 'rm -rf /c/temp', 'rm -rf C:/Users/other',
                        'rm -rf ./build', 'rm -rf /tmp/x', 'rm -f /c/x.txt', 'rm /c/*'):
            with self.subTest(command): self.assertEqual(self.deny(command), '')

    def test_powershell_and_pwsh_wrappers_under_bash_are_unwrapped(self):
        for command in ('powershell -Command "Remove-Item -Recurse -Force $HOME"', 'powershell.exe -NoProfile -Command "Remove-Item -Recurse -Force $HOME"',
                        'pwsh -c "ri -r -fo ~"', 'pwsh -c "Remove-Item -Recurse -Force $env:USERPROFILE"', 'powershell -Command Remove-Item -Recurse -Force C:\\',
                        'powershell -c "Remove-Item -Recurse -Force C:\\Users\\me"', "powershell -c 'Remove-Item -Recurse -Force C:/'",
                        'powershell -Command "cd x; Remove-Item -Recurse -Force ~"', '/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -c "ri -r -fo ~"',
                        'powershell -Command "Remove-Item -Path \\"$HOME\\" -Recurse -Force"', 'echo hi && pwsh -c "rm -r -fo $HOME"'):
            with self.subTest(command): self.assertTrue(self.deny(command))
        encoded = base64.b64encode('Remove-Item -Recurse -Force $HOME'.encode('utf-16-le')).decode()
        self.assertTrue(self.deny(f'powershell -NoProfile -EncodedCommand {encoded}'))

    def test_cmd_wrappers_are_unwrapped(self):
        for command in ('cmd /c rd /s /q %USERPROFILE%', 'cmd /c "rd /s /q %USERPROFILE%"', 'cmd.exe /c rmdir /s /q C:\\', 'cmd /d /s /c "rmdir /s /q C:\\Users\\me"',
                        'cmd /c rmdir /S /Q %USERPROFILE%\\*', 'cmd /c "del /s /q %USERPROFILE%"', 'cmd /c rd /s /q %SystemDrive%\\', 'cmd /c echo hi && rd /s /q C:\\'):
            with self.subTest(command): self.assertTrue(self.deny(command))

    def test_nested_git_force_and_hard_reset_are_denied(self):
        for command in ('powershell -Command "git push --force"', 'pwsh -c "git push -f origin main"', 'cmd /c git push --force', 'cmd /c "git reset --hard"',
                        'powershell -Command "git reset --hard HEAD~1"', 'pwsh -c "cd x; git clean -fd"', 'powershell -c "powershell -c \\"git push --force\\""'):
            with self.subTest(command): self.assertTrue(self.deny(command))

    def test_harmless_wrapped_commands_are_allowed(self):
        for command in ('powershell -Command "Get-ChildItem"', 'pwsh -c "git push --force-with-lease"', 'cmd /c dir', 'cmd /c "rd /s /q build"',
                        'powershell -Command "Remove-Item -Recurse -Force C:\\Users\\me\\project\\build"', 'cmd /c rd /s /q %USERPROFILE%\\project\\build',
                        'cmd /c rd /q C:\\', 'powershell -Command "Remove-Item -Recurse $HOME"', 'git log --grep cmd -n 5', 'echo cmd /c', 'powershell -File build.ps1',
                        'powershell -c "Remove-Item -Recurse -Force C:\\temp"'):
            with self.subTest(command): self.assertEqual(self.deny(command), '')

    def test_powershell_tool_sees_the_same_forms(self):
        for command in ('Remove-Item -Recurse -Force C:/', 'Remove-Item -Recurse -Force /c/*', 'Remove-Item -Recurse -Force %USERPROFILE%', 'cmd /c rd /s /q %USERPROFILE%',
                        'Remove-Item -Recurse -Force $env:USERPROFILE'):
            with self.subTest(command): self.assertTrue(self.deny(command, 'PowerShell'))
        self.assertEqual(self.deny('Remove-Item -Recurse -Force C:/Users/me/project/build', 'PowerShell'), '')

    def test_real_posix_home_still_denied_and_subpaths_allowed(self):
        with mock.patch.object(os.path, 'expanduser', side_effect=lambda p: '/home/me' + p[1:] if p.startswith('~') else p):
            for command in ('rm -rf ~', 'rm -rf $HOME/*', 'rm -rf /home/me', 'rm -rf /*', 'rm -rf /'): self.assertTrue(self.deny(command), command)
            for command in ('rm -rf ~/project', 'rm -rf /home/me/project/build', 'rm -rf /home/other'): self.assertEqual(self.deny(command), '', command)


class AtomicWriteRetryTests(Base):
    def target(self):
        return Path(self.tmp.name) / 'out' / 'file.txt'

    def test_windows_retries_a_file_held_by_another_program(self):
        real, calls = os.replace, []
        def flaky(source, target):
            calls.append(1)
            if len(calls) < 3: raise PermissionError(13, 'in use', None, 32)
            return real(source, target)
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(os, 'replace', side_effect=flaky), mock.patch.object(core.time, 'sleep') as sleep:
            core.atomic_write(self.target(), 'ok')
        self.assertEqual(self.target().read_text(), 'ok'); self.assertEqual((len(calls), sleep.call_count), (3, 2))
        self.assertEqual([p.name for p in self.target().parent.iterdir()], ['file.txt'])  # no temp file left

    def test_windows_gives_up_after_a_few_tries_and_cleans_up(self):
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(os, 'replace', side_effect=PermissionError(13, 'in use', None, 5)) as replace, mock.patch.object(core.time, 'sleep'):
            with self.assertRaises(PermissionError): core.atomic_write(self.target(), 'x')
        self.assertEqual(replace.call_count, 6); self.assertEqual(list(self.target().parent.iterdir()), [])

    def test_posix_does_not_retry(self):
        with mock.patch.object(core, 'WINDOWS', False), mock.patch.object(os, 'replace', side_effect=PermissionError(13, 'no', None)) as replace, mock.patch.object(core.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError): core.atomic_write(self.target(), 'x')
        self.assertEqual((replace.call_count, sleep.call_count), (1, 0))


BOM = b'\xef\xbb\xbf'


class BomTests(Base):
    def stdin(self, payload):
        return mock.patch.object(sys, 'stdin', io.TextIOWrapper(io.BytesIO(BOM + json.dumps(payload).encode()), encoding='cp1252'))

    def test_workspace_json_with_bom_is_read(self):
        path = self.root / 'workspace.json'; path.write_bytes(BOM + path.read_bytes())
        self.assertEqual(core.config(self.root)['name'], 'demo')

    def test_mcp_json_with_bom_still_counts_as_connected(self):
        core.connect(self.root, 'claude')
        self.assertTrue(core.client_connected(self.root, 'claude'))
        path = self.root / '.mcp.json'; path.write_bytes(BOM + path.read_bytes())
        self.assertTrue(core.client_connected(self.root, 'claude'))

    def test_settings_json_with_bom_is_upgraded_in_place_not_parked(self):
        old = json.dumps(core.memory_hooks(self.root, 'claude'))
        stale = old.replace('"timeout": 10', '"timeout": 99')
        merged = upgrade.hooks('\ufeff' + stale, old)
        self.assertIsNotNone(merged); self.assertEqual(json.loads(merged), json.loads(old))

    def test_audit_reads_bom_hook_and_mcp_files(self):
        from ws import audit
        hooks = self.root / 'hooks.json'; hooks.write_bytes(BOM + json.dumps({'hooks': {'SessionStart': [{'hooks': [{'command': 'x'}]}]}}).encode())
        self.assertTrue(audit._session_start_command(hooks))
        (self.root / '.mcp.json').write_bytes(BOM + json.dumps({'mcpServers': {'a': {}}}).encode())
        self.assertIn('a', audit._mcp_servers(self.root))

    def test_hook_stdin_with_bom_is_parsed_even_when_stdin_is_a_legacy_codepage(self):
        with self.stdin({'a': 'é'}): self.assertEqual(core.stdin_json(), {'a': 'é'})

    def test_guard_denies_a_bom_prefixed_payload(self):
        with self.stdin({'tool_name': 'Bash', 'tool_input': {'command': 'git push --force'}}), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.main(['guard']), 0)
        self.assertEqual(json.loads(out.getvalue())['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_plain_json_helper_strips_only_a_leading_bom(self):
        self.assertEqual(core.json_loads('\ufeff{"a": "\ufeff"}'), {'a': '\ufeff'})


class SkillLinkFallbackTests(Base):
    def setUp(self):
        super().setUp()
        self.home = Path(self.tmp.name) / 'home'
        refused = OSError(22, 'A required privilege is not held by the client', None, 1314)
        for patch in (mock.patch.object(Path, 'home', return_value=self.home), mock.patch.object(Path, 'symlink_to', side_effect=refused)):
            patch.start(); self.addCleanup(patch.stop)

    def test_refused_symlink_falls_back_to_a_copy_and_connect_still_succeeds(self):
        result = core.connect(self.root, 'claude', skills=True)
        copied = result['skills']['copied']
        self.assertIn('thinkbeforeact', copied)
        self.assertEqual(result['skills']['linked'], [])
        skill = self.home / '.claude/skills/thinkbeforeact'
        self.assertTrue((skill / 'SKILL.md').is_file()); self.assertFalse(skill.is_symlink())
        self.assertTrue(core.client_connected(self.root, 'claude'))  # configs were written before the skills step

    def test_windows_uses_a_junction_first(self):
        def mklink(command, **_):
            Path(command[-2]).mkdir(parents=True)  # what mklink /J does: a directory entry that resolves to the target
            return subprocess.CompletedProcess(command, 0)
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(subprocess, 'run', side_effect=mklink) as run:
            result = core.link_skills('claude', self.root)
        self.assertIn('thinkbeforeact', result['linked']); self.assertEqual(result['copied'], [])
        self.assertEqual(run.call_args[0][0][:4], ['cmd', '/c', 'mklink', '/J'])

    def test_failed_junction_falls_back_to_a_copy(self):
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            result = core.link_skills('claude', self.root)
        self.assertIn('thinkbeforeact', result['copied'])

    def test_cli_reports_copies_and_exits_zero(self):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = cli.main(['--workspace-root', str(self.root), 'connect', 'claude', '--skills'])
        self.assertEqual(code, 0); self.assertIn('copied because links are not allowed', err.getvalue())


class PluginLauncherTests(unittest.TestCase):
    def test_every_plugin_hook_goes_through_the_launcher_and_manifest_has_no_other_python3_hook(self):
        hooks = json.loads((KIT / 'hooks/claude-hooks.json').read_text())['hooks']
        self.assertEqual(len(hooks), 4)
        for entries in hooks.values():
            self.assertTrue(entries[0]['hooks'][0]['command'].startswith('sh "${CLAUDE_PLUGIN_ROOT}/bin/ws-python" '), entries)

    @unittest.skipIf(os.name == 'nt', 'needs POSIX fake interpreters; the Windows path is CI/manual only')
    def test_launcher_picks_the_first_working_python(self):
        sh = shutil.which('sh'); tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp)
        def fake(name, body):
            path = tmp / name; path.write_text('#!/bin/sh\n' + body); path.chmod(0o755)
        def run(*extra):
            return subprocess.run([sh, str(KIT / 'bin/ws-python'), 'ARG'], capture_output=True, text=True, env={'PATH': str(tmp)})
        fake('python', 'echo "python $@"')
        self.assertEqual(run().stdout.strip(), 'python ARG')  # no python3 at all (python.org install)
        fake('python3', 'exit 9')  # the Microsoft Store stub: present but unusable
        self.assertEqual(run().stdout.strip(), 'python ARG')
        fake('python3', 'echo "python3 $@"')
        self.assertEqual(run().stdout.strip(), 'python3 ARG')
        (tmp / 'python').unlink(); (tmp / 'python3').unlink()
        none = run(); self.assertEqual(none.returncode, 1); self.assertIn('no Python 3.9+', none.stderr)
        fake('py', 'echo "py $@"')  # `py -3`
        self.assertEqual(run().stdout.strip(), 'py -3 ARG')


class WindowsHookQuotingTests(unittest.TestCase):
    def test_dollar_backtick_and_bang_paths_use_the_encoded_launcher(self):
        for name in ('$work', 'a`b', 'x!y', '%P%', 'C$'):
            root = Path('C:/Users/me') / name
            with self.subTest(name), mock.patch.object(core, 'WINDOWS', True), mock.patch.object(core, 'python_command', return_value='C:\\Python\\python.exe'):
                for groups in core.memory_hooks(root, 'claude')['hooks'].values():
                    command = groups[0]['hooks'][0]['command']
                    self.assertTrue(command.startswith('powershell.exe '), command)
                    self.assertTrue(all(c not in command for c in '$`!%'), command)
                    self.assertEqual(core.encoded_hook_args(command.split())[3], str(root))

    def test_ordinary_windows_paths_keep_the_quoted_command(self):
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(core, 'python_command', return_value='C:\\Python\\python.exe'):
            command = core.memory_hooks(Path('C:/Users/me/work space'), 'claude')['hooks']['SessionStart'][0]['hooks'][0]['command']
        self.assertTrue(command.startswith('"C:\\Python\\python.exe"'), command)

    def test_posix_is_untouched(self):
        with mock.patch.object(core, 'WINDOWS', False):
            command = core.memory_hooks(Path('/tmp/$work'), 'claude')['hooks']['SessionStart'][0]['hooks'][0]['command']
        self.assertNotIn('powershell', command)


class GitTimeoutTests(Base):
    def test_windows_gets_a_longer_probe_timeout_posix_keeps_two_seconds(self):
        with mock.patch.object(core, 'WINDOWS', True): self.assertGreaterEqual(core.git_timeout(), 5)
        with mock.patch.object(core, 'WINDOWS', False): self.assertEqual(core.git_timeout(), 2)

    def test_branch_probe_passes_the_timeout_to_git(self):
        from ws import setup
        for windows, expected in ((True, 6), (False, 2)):
            with mock.patch.object(core, 'WINDOWS', windows), mock.patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'main\n')) as run:
                self.assertEqual(setup.branch(self.root), 'main')
            self.assertEqual(run.call_args.kwargs['timeout'], expected)

    def test_slow_cold_git_start_still_finds_the_branch(self):
        from ws import setup
        slow = subprocess.TimeoutExpired('git', 2)
        def run(*a, timeout, **k):
            if timeout < 5: raise slow
            return subprocess.CompletedProcess([], 0, 'feature/x\n')
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(subprocess, 'run', side_effect=run):
            self.assertEqual(setup.branch(self.root), 'feature/x')


class CrlfCheckoutTests(Base):
    def git(self, repo, *args):
        return subprocess.run(['git', '-c', 'user.name=T', '-c', 'user.email=t@example.invalid', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()

    def checkout(self, attributes):
        repo = Path(self.tmp.name) / 'checkout-repo'; repo.mkdir()
        self.git(repo, 'init', '-q', '-b', 'main')
        (repo / '.gitattributes').write_text(attributes); (repo / 'a.txt').write_bytes(b'one\ntwo\n')
        self.git(repo, 'add', '.'); self.git(repo, 'commit', '-qm', 'x')
        (repo / 'a.txt').unlink(); self.git(repo, 'checkout', '--', 'a.txt')  # re-checkout applies eol=crlf
        return repo, self.git(repo, 'rev-parse', 'HEAD^{tree}')

    def test_crlf_worktree_is_not_reported_as_a_later_edit(self):
        repo, tree = self.checkout('*.txt text eol=crlf\n')
        self.assertEqual((repo / 'a.txt').read_bytes(), b'one\r\ntwo\r\n')  # the Windows autocrlf situation
        self.assertFalse(self.later(repo, tree))

    def later(self, repo, tree):
        directory = Path(self.tmp.name) / 'run'; directory.mkdir()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        shutil.copytree(repo, directory / 'checkout')  # the worker's checkout dir
        return workers._later_edits(directory, {'tree': tree})

    def test_a_real_edit_is_still_reported_with_crlf_conversion_on(self):
        repo, tree = self.checkout('*.txt text eol=crlf\n')
        (repo / 'a.txt').write_bytes(b'one\r\nCHANGED\r\n')
        self.assertTrue(self.later(repo, tree))
