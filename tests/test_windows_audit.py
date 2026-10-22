"""Windows-only behaviour found by the audit, simulated on any OS (CI runs the real thing)."""
import ast
import io
import ntpath
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_ws import Base, KIT
from ws import assist, cli, codeburn, core, guards, upgrade


class Utf8Stream(io.StringIO):
    def reconfigure(self, **kwargs): self.settings = kwargs


class WindowsAuditTests(Base):
    def test_ws_console_script_switches_streams_to_utf8_on_windows(self):
        # pip/pipx install `ws` as ws.cli:main and skip bin/ws, whose cp1252 pipes cannot print task titles like "é".
        streams = [Utf8Stream(), Utf8Stream(), Utf8Stream()]
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(sys, 'stdin', streams[0]), \
                mock.patch.object(sys, 'stdout', streams[1]), mock.patch.object(sys, 'stderr', streams[2]):
            with self.assertRaises(SystemExit): cli.main(['--version'])
        self.assertEqual([getattr(s, 'settings', None) for s in streams], [{'encoding': 'utf-8'}] * 3)

    def test_codeburn_runs_the_resolved_executable_not_the_bare_name(self):
        # Windows npm shims are codeburn.CMD: which() finds them, but CreateProcess with the bare name does not.
        shim = r'C:\npm\codeburn.CMD'
        seen = []
        def run(command, **kwargs):
            seen.append(command[0]); raise OSError('stop here')
        with mock.patch.object(core.shutil, 'which', return_value=shim), mock.patch.object(core.subprocess, 'run', side_effect=run), \
                mock.patch.object(assist.subprocess, 'run', side_effect=run):
            with self.assertRaises(core.WsError): codeburn.import_usage(self.root)
            assist._scan()
        self.assertEqual(seen, [shim, shim])

    def test_guards_match_the_home_folder_with_either_slash_and_any_case_on_windows(self):
        home = r'C:\Users\Me'
        with mock.patch.object(guards.os, 'path', ntpath), mock.patch.dict(guards.os.environ, {'USERPROFILE': home}):
            for command in ('rm -rf C:/Users/Me', 'rm -rf c:/users/me/'):
                with self.subTest(command): self.assertTrue(guards.reason('Bash', {'command': command}))
            for command in ('Remove-Item -Recurse -Force C:/Users/Me', r'Remove-Item -Recurse -Force c:\users\me\\', r'rm -r -fo "C:\Users\ME"'):
                with self.subTest(command): self.assertTrue(guards.reason('PowerShell', {'command': command}))
            for command in (r'Remove-Item -Recurse -Force C:\Users\Me\old', r'Remove-Item -Recurse -Force C:\Users\Meg'):
                with self.subTest(command): self.assertEqual(guards.reason('PowerShell', {'command': command}), '')

    def test_upgrade_recognises_windows_quoted_hook_commands(self):
        # core.command_line quotes every argument for Windows; posix shlex eats the backslashes and the hook looked foreign.
        arguments = [r'C:\Users\Me\py\python.exe', r'C:\kit\bin\ws', '--workspace-root', r'C:\Users\Me\ws', 'brief', '--hook']
        with mock.patch.object(core, 'WINDOWS', True):
            command = core.command_line(arguments)
            self.assertTrue(upgrade.managed_command(command))
            self.assertFalse(upgrade.managed_command(core.command_line([r'C:\tools\evil.exe', *arguments[1:]])))

    def test_text_io_always_names_its_encoding(self):
        # Windows defaults to cp1252: git paths, notes and AGENTS.md with non-ASCII text crash or turn to mojibake.
        missing = []
        for path in [*(KIT / 'ws').glob('*.py'), *(KIT / 'mcp').glob('*.py'), KIT / 'bin' / 'ws']:
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if not isinstance(node, ast.Call): continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ''
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == 'os': continue  # os.open takes flags
                keywords = {k.arg: k.value for k in node.keywords}
                if name == 'open':
                    mode = keywords.get('mode') or next(iter(node.args[0 if isinstance(func, ast.Attribute) else 1:][:1]), None)
                    if isinstance(mode, ast.Constant) and 'b' in str(mode.value): continue
                    bad = 'encoding' not in keywords
                elif name in ('read_text', 'write_text'):
                    bad = 'encoding' not in keywords and len(node.args) < (1 if name == 'read_text' else 2)
                else:
                    bad = name in ('run', 'Popen', 'check_output') and bool(keywords.get('text') or keywords.get('universal_newlines')) and 'encoding' not in keywords
                if bad: missing.append(f'{path.relative_to(KIT)}:{node.lineno} {name}')
        self.assertEqual(missing, [])


if __name__ == '__main__':
    unittest.main()
