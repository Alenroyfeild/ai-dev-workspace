import errno
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock
from test_ws import Base, KIT
from ws import core


class PortabilityTests(Base):
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

    def test_windows_command_quotes_metacharacter_and_drive_root_paths(self):
        with mock.patch.object(core, 'WINDOWS', True):
            command = core.command_line(['C:\\Python\\python.exe', 'C:\\kit&tools\\bin\\ws', '--workspace-root', 'C:\\'])
        self.assertEqual(command, '"C:\\Python\\python.exe" "C:\\kit&tools\\bin\\ws" --workspace-root "C:\\\\"')
