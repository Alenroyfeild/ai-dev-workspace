import errno
import base64
import json
import os
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
from test_ws import Base, KIT
from ws import core, upgrade


class PortabilityTests(Base):
    def test_percent_hook_encodes_all_paths_and_upgrade_checks_exact_launcher(self):
        root = Path(self.tmp.name) / 'workspace%WS_ESCAPE% with spaces'
        fake_kit = Path(self.tmp.name) / 'kit%WS_ESCAPE%'
        python = str(Path(self.tmp.name) / 'runtime%WS_ESCAPE%/python.exe')
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.object(core, 'KIT', fake_kit), mock.patch.object(core, 'python_command', return_value=python):
            hooks = core.memory_hooks(root, 'codex')
        for event, groups in hooks['hooks'].items():
            command = groups[0]['hooks'][0]['command']
            self.assertNotIn('%', command)
            args = core.encoded_hook_args(shlex.split(command))
            self.assertEqual(args[:4], [python, str(fake_kit / 'bin/ws'), '--workspace-root', str(root)])
            action = 'paste' if event == 'UserPromptSubmit' else 'brief' if event == 'SessionStart' else 'nudge'
            self.assertEqual(args[4:], [action, '--hook', '--client', 'codex'])
            self.assertTrue(upgrade.managed_command(command))
            self.assertFalse(upgrade.managed_command(command + ' && echo unsafe'))
            parts = shlex.split(command)
            script = base64.b64decode(parts[-1]).decode('utf-16-le').replace('exit $p.ExitCode', 'echo unsafe')
            altered = ' '.join(parts[:-1] + [base64.b64encode(script.encode('utf-16-le')).decode('ascii')])
            self.assertFalse(upgrade.managed_command(altered))
        self.assertFalse(upgrade.managed_command(core.encoded_hook_command(['cmd.exe', '/c', 'echo unsafe'])))
        old = json.dumps(hooks); self.assertEqual(upgrade.hooks(old, old), old)

    @unittest.skipIf(os.name != 'nt', 'requires actual cmd.exe and Windows PowerShell')
    def test_cmd_percent_paths_keep_unicode_stdin_capture_and_exit_code(self):
        base = Path(self.tmp.name); root = base / 'workspace%WS_ESCAPE% & violet-é'
        kit = base / 'kit%WS_KIT%'; home = base / 'home'; home.mkdir()
        shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
        with mock.patch.object(core, 'KIT', kit):
            core.init(root, 'Synthetic percent proof'); core.task_new(root, 'PERCENT-1', 'Violet guard')
            core.claim(root, 'PERCENT-1', 'synthetic'); core.checkpoint(root, 'PERCENT-1', 'in_progress', 'Read the violet → guard')
            hooks = core.memory_hooks(root)['hooks']
        env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home), 'CODEX_HOME': str(home / '.codex'), 'WS_OFFLINE': '1', 'WS_ESCAPE': 'expanded', 'WS_KIT': 'expanded-kit'}
        def run(command, payload):
            return subprocess.run(['cmd.exe', '/d', '/v:on', '/s', '/c', command], cwd=base, env=env,
                                  input=json.dumps(payload, ensure_ascii=False), encoding='utf-8', capture_output=True, timeout=30)
        unsafe = core.command_line([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(root)]) + ' brief --hook'
        legacy = subprocess.run(unsafe, shell=True, cwd=base, env=env, input='{}', encoding='utf-8', capture_output=True, timeout=30)
        self.assertNotEqual(legacy.returncode, 0)  # Same shell framing as the existing non-percent positive-control test.
        transcript = root / 'session.jsonl'
        transcript.write_text('\n'.join(map(json.dumps, [{'type': 'user', 'message': {'content': 'Decided: only violet.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use'}, {'type': 'text', 'text': 'Next action: read violet.'}]}}])))
        for event in ('SessionStart', 'PreCompact', 'Stop'):
            result = run(hooks[event][0]['hooks'][0]['command'], {'hook_event_name': event, 'transcript_path': str(transcript), 'prompt': 'violet → guard'})
            self.assertEqual(result.returncode, 0, result.stderr)
            if event == 'SessionStart': self.assertIn('Read the violet → guard', result.stdout)
            elif event == 'Stop' or result.stdout.strip(): json.loads(result.stdout)
            if event != 'SessionStart': self.assertIn('only violet', core.task_read(root, 'PERCENT-1', ['Handoff'])['sections']['Handoff'])
        self.assertIn('only violet', core.task_read(root, 'PERCENT-1', ['Handoff'])['sections']['Handoff'])
        invalid = run(hooks['SessionStart'][0]['hooks'][0]['command'], [])
        self.assertEqual(invalid.returncode, 2); self.assertIn('Hook input must be a JSON object', invalid.stderr)
        with mock.patch.object(core, 'KIT', kit):
            core.upgrade_workspace(root); self.assertEqual(core.upgrade_workspace(root)['changes'], [])

    def test_lock_contends_and_releases_after_exception(self):
        with self.assertRaisesRegex(RuntimeError, 'synthetic'):
            with core.lock(self.root):
                with self.assertRaisesRegex(core.WsError, 'Another workspace update'):
                    with core.lock(self.root): pass
                raise RuntimeError('synthetic')
        with core.lock(self.root): pass

    def test_windows_lock_uses_one_nonblocking_byte_at_offset_zero(self):
        native = mock.Mock(LK_NBLCK=2, LK_UNLCK=0)
        stream = mock.Mock(); stream.fileno.return_value = 7
        with mock.patch.object(core, 'WINDOWS', True), mock.patch.dict(sys.modules, {'msvcrt': native}):
            core.file_lock(stream)
            core.file_lock(stream, release=True)
        self.assertEqual(stream.seek.call_args_list, [mock.call(0), mock.call(0)])
        self.assertEqual(native.locking.call_args_list, [mock.call(7, 2, 1), mock.call(7, 0, 1)])

    def test_generated_hook_runs_from_another_cwd_with_spaces_and_no_env_prefix(self):
        root = Path(self.tmp.name) / 'workspace with spaces'
        core.init(root, 'Synthetic portability proof')
        core.task_new(root, 'T-1', 'Unicode violet → guard')
        core.claim(root, 'T-1', 'synthetic')
        core.checkpoint(root, 'T-1', 'in_progress', 'Inspect the synthetic violet guard')
        hook = core.memory_hooks(root)['hooks']['SessionStart'][0]['hooks'][0]['command']
        self.assertNotIn('env WS_ROOT=', hook)
        self.assertIn('--workspace-root', hook)
        run = subprocess.run(hook, shell=True, cwd=self.tmp.name, input='{}', text=True,
                             capture_output=True, timeout=10, env={**os.environ, 'HOME': self.tmp.name, 'WS_OFFLINE': '1'})
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn('Inspect the synthetic violet guard', run.stdout)
        pointer = root / 'GEMINI.md'
        pointer.write_bytes(pointer.read_bytes().replace(b'Follow', b'Altered').replace(b'\n', b'\r\n'))
        core.upgrade_workspace(root)
        self.assertIn('Follow', pointer.read_text())
        repo = root / ('repo' if os.name == 'nt' else r'repo\Users'); repo.mkdir()
        core.codebase_map(root, repo); core.codebase_map(root, repo)

    def test_windows_command_quotes_metacharacter_and_drive_root_paths(self):
        with mock.patch.object(core, 'WINDOWS', True):
            command = core.command_line(['C:\\Python\\python.exe', 'C:\\kit&tools\\bin\\ws', '--workspace-root', 'C:\\'])
        self.assertEqual(command, '"C:\\Python\\python.exe" "C:\\kit&tools\\bin\\ws" --workspace-root "C:\\\\"')
