"""Latency guards for the hooks that run on every prompt/session. Count work, never wall time, so they cannot flake."""
import collections
import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import cli, core

KIT = Path(__file__).resolve().parents[1]
HEAVY = ('urllib.request', 'http.client', 'ssl', 'difflib', 'sqlite3', 'ws.orchestration', 'ws.workers', 'ws.setup', 'ws.repo')


class HookLatencyTests(Base):
    def hook(self, argv, payload):
        out = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(out):
            code = cli.main(['--workspace-root', str(self.root), *argv])
        return code, out.getvalue()

    def git_repo(self):
        repo = self.root / 'fixture'; repo.mkdir()
        run = lambda *a: subprocess.run(['git', '-C', str(repo), '-c', 'user.name=S', '-c', 'user.email=s@example.invalid', *a], check=True, capture_output=True)
        run('init', '-q'); (repo / 'export.py').write_text('v1\n'); run('add', '.'); run('commit', '-qm', 'one')
        name = run('symbolic-ref', '--short', 'HEAD').stdout.decode().strip()  # a branch-bound task is what makes the brief ask git where HEAD is
        core.task_new(self.root, 'ST-1', 'Publish daily output', branch=name, repo=str(repo))
        core.claim(self.root, 'ST-1', 'synthetic')
        core.checkpoint(self.root, 'ST-1', 'in_progress', 'Finish export.py output.')
        return repo

    def recorded_git(self, argv, payload):
        real, calls = subprocess.run, []
        def spy(cmd, *args, **kwargs):
            if cmd and cmd[0] == 'git': calls.append(tuple(cmd))
            return real(cmd, *args, **kwargs)
        with mock.patch.object(subprocess, 'run', spy):
            self.hook(argv, payload)
        return calls

    def test_importing_the_cli_does_not_load_network_or_rare_command_modules(self):
        script = f'import sys, json; sys.path.insert(0, {str(KIT)!r}); import ws.cli; print(json.dumps([m for m in {HEAVY!r} if m in sys.modules]))'
        proc = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': ''})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [])

    def test_prompt_hook_spawns_nothing_and_walks_no_tree(self):
        self.git_repo()
        boom = AssertionError('UserPromptSubmit must not spawn processes or walk the tree')
        with mock.patch.object(subprocess, 'run', side_effect=boom), mock.patch.object(subprocess, 'Popen', side_effect=boom), \
                mock.patch.object(os, 'walk', side_effect=boom), mock.patch.object(Path, 'rglob', side_effect=boom), \
                mock.patch.object(Path, 'glob', side_effect=boom):
            for client in ('claude', 'codex'):
                code, out = self.hook(['paste', '--hook', '--client', client], {'hook_event_name': 'UserPromptSubmit', 'prompt': 'please fix the export'})
                self.assertEqual((code, json.loads(out)), (0, {}))

    def test_session_start_runs_each_git_command_once(self):
        self.git_repo()
        for client in ([], ['--client', 'codex']):
            calls = self.recorded_git(['brief', '--hook', *client], {'hook_event_name': 'SessionStart', 'session_id': 's1'})
            repeated = {c[3:]: n for c, n in collections.Counter(calls).items() if n > 1}
            self.assertTrue(calls)
            self.assertEqual(repeated, {})

    def test_lessons_without_paths_need_no_file_listing(self):
        self.git_repo()
        core.lesson_add(self.root, 'export writes twice -> dedupe before saving')
        calls = self.recorded_git(['brief', '--hook'], {'hook_event_name': 'SessionStart', 'session_id': 's1'})
        self.assertEqual([c[3:] for c in calls if c[3] == 'ls-files' or '--name-only' in c], [])  # the memory check's own diff stays


if __name__ == '__main__':
    unittest.main()
