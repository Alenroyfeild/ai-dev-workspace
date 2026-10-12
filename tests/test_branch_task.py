import contextlib
import concurrent.futures
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core


class BranchTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'; self.home = Path(self.tmp.name) / 'home'; self.home.mkdir()
        patch = mock.patch.dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home), CODEX_HOME=str(self.home / '.codex'), WS_OFFLINE='1')
        patch.start(); self.addCleanup(patch.stop)
        core.init(self.root, 'synthetic', repos=[str(self.root)], clients=[])
        self.git('init', '-q', '-b', 'feature/a')
        (self.root / 'app.py').write_text('value = 1\n'); self.git('add', 'app.py')
        self.git('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'fixture')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def hook(self, client='codex'):
        output = io.StringIO()
        event = 'sessionStart' if client == 'cursor' else 'SessionStart'
        with mock.patch('sys.stdin', io.StringIO(json.dumps(dict(hook_event_name=event, cwd=str(self.root))))), \
                mock.patch('sys.stdout', output), mock.patch('ws.assist.observe'):
            code = cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', client])
        self.assertEqual(code, 0); return output.getvalue()

    def test_session_start_switches_brief_and_capture_without_changing_previous_task(self):
        self.assertIn('feature/a', self.hook())
        first = core.task_list(self.root)[0]['id']
        core.checkpoint(self.root, first, 'in_progress', 'Inspect the amber result.', notes={'Handoff': 'Decision: use amber.'})
        before = core.task_path(self.root, first).read_bytes()
        self.git('switch', '-qc', 'feature/b'); self.assertIn('feature/b', self.hook())
        second = next(t['id'] for t in core.task_list(self.root) if t['branch'] == 'feature/b')
        self.assertNotIn('use amber', core.brief(self.root))
        transcript = self.root / 'session.jsonl'
        transcript.write_text('\n'.join(map(json.dumps, [
            {'type':'user', 'message':{'content':'Never change the public return shape.'}},
            {'type':'assistant', 'message':{'content':[{'type':'tool_use','name':'Read'}, {'type':'text','text':'Next step: inspect input.'}]}}])))
        self.assertTrue(core.capture_decisions(self.root, str(transcript)))
        self.assertIn('public return shape', core.task_read(self.root, second, ['Handoff'])['sections']['Handoff'])
        self.assertEqual(before, core.task_path(self.root, first).read_bytes())
        self.git('switch', '-q', 'feature/a'); self.assertIn('use amber', self.hook())
        self.assertEqual(before, core.task_path(self.root, first).read_bytes())

    def test_every_session_start_client_creates_only_one_local_task(self):
        for client in ('claude', 'codex', 'cursor', 'vscode', 'gemini'): self.hook(client)
        tasks = core.task_list(self.root); self.assertEqual(len(tasks), 1)
        meta = core.task_read(self.root, tasks[0]['id'], ['Next action'])['meta']
        self.assertTrue(core._local_claim_matches(self.root, tasks[0]['id'], meta))

    def test_capture_false_never_creates_or_claims_a_branch_task(self):
        cfg = core.config(self.root); cfg['capture'] = False
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        self.hook(); self.assertEqual(core.task_list(self.root), [])

    def test_foreign_claim_ambiguous_tasks_and_outside_cwd_are_refused(self):
        core.task_new(self.root, 'T-1', 'existing', branch='feature/a', repo=str(self.root)); core.claim(self.root, 'T-1', 'other')
        (self.root / '.ws/claims/T-1.json').unlink()
        before = core.task_path(self.root, 'T-1').read_bytes()
        with self.assertRaises(core.WsError): core.session_task(self.root, str(self.root))
        self.assertEqual(before, core.task_path(self.root, 'T-1').read_bytes())
        core.task_new(self.root, 'T-2', 'another', branch='feature/a', repo=str(self.root))
        with self.assertRaises(core.WsError): core.session_task(self.root, str(self.root))
        with self.assertRaises(core.WsError): core.session_task(self.root, str(self.home))
        self.assertEqual(len(core.task_list(self.root)), 2)

    def test_concurrent_creators_cannot_overwrite_the_same_task(self):
        barrier = threading.Barrier(2); serial = threading.Lock(); original = core.lock
        @contextlib.contextmanager
        def together(root):
            barrier.wait(timeout=5)
            with serial, original(root): yield
        with mock.patch.object(core, 'lock', together), concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(core.task_new, self.root, 'T-1', title) for title in ('first', 'second')]
            self.assertEqual(sum(future.exception() is None for future in futures), 1)

    def test_relative_repo_reuses_record_and_invalid_cwd_is_rejected(self):
        core.task_new(self.root, 'T-1', 'existing', branch='feature/a', repo='.')
        self.assertEqual(core.session_task(self.root, str(self.root)), 'T-1')
        self.assertEqual(len(core.task_list(self.root)), 1)
        with self.assertRaises(core.WsError): core.session_task(self.root, {'cwd':'invalid'})

    def test_completed_branch_does_not_inject_a_stale_next_action_or_reopen(self):
        self.hook(); task = core.task_list(self.root)[0]['id']
        core.checkpoint(self.root, task, 'done', 'STALE_COMPLETED_ACTION')
        before = core.task_path(self.root, task).read_bytes()
        self.assertNotIn('STALE_COMPLETED_ACTION', self.hook())
        self.assertEqual(before, core.task_path(self.root, task).read_bytes())
        self.assertEqual(len(core.task_list(self.root)), 1)
