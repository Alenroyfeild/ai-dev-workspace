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

    def branchless_task(self, task_id, repo=None, worker='fixture-worker', status='in_progress'):
        core.task_new(self.root, task_id, 'Branchless fixture', repo=str(self.root) if repo is None else repo)
        core.claim(self.root, task_id, worker)
        core.checkpoint(self.root, task_id, status, 'Continue ' + task_id,
                        notes={'Handoff': 'Saved facts for ' + task_id})
        return core.task_path(self.root, task_id).read_bytes()

    def test_one_locally_claimed_branchless_task_is_selected_without_writes(self):
        before = self.branchless_task('BENCH-1', repo='.')
        self.assertIn('Continue BENCH-1', self.hook())
        self.assertEqual([t['id'] for t in core.task_list(self.root)], ['BENCH-1'])
        self.assertEqual(core.task_path(self.root, 'BENCH-1').read_bytes(), before)
        self.assertEqual(core.task_read(self.root, 'BENCH-1', ['Next action'])['meta'].get('branch', ''), '')

    def test_multiple_locally_claimed_branchless_tasks_fall_back_without_hook_error(self):
        first = self.branchless_task('T-1'); second = self.branchless_task('T-2')
        self.hook()
        tasks = core.task_list(self.root)
        self.assertEqual(len([t for t in tasks if t['id'].startswith('BR-')]), 1)
        self.assertEqual(core.task_path(self.root, 'T-1').read_bytes(), first)
        self.assertEqual(core.task_path(self.root, 'T-2').read_bytes(), second)

    def test_done_branchless_task_is_not_selected(self):
        before = self.branchless_task('DONE', status='done')
        self.assertNotIn('Continue DONE', self.hook())
        self.assertTrue(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))
        self.assertEqual(core.task_path(self.root, 'DONE').read_bytes(), before)

    def test_branchless_task_for_another_repo_is_not_selected(self):
        other = self.root / 'other'; other.mkdir()
        subprocess.run(['git', 'init', '-q', str(other)], check=True, capture_output=True)
        before = self.branchless_task('OTHER', repo=str(other))
        self.assertNotIn('Continue OTHER', self.hook())
        self.assertTrue(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))
        self.assertEqual(core.task_path(self.root, 'OTHER').read_bytes(), before)

    def test_unclaimed_branchless_task_is_not_selected(self):
        core.task_new(self.root, 'FREE', 'Unclaimed', repo=str(self.root))
        before = core.task_path(self.root, 'FREE').read_bytes()
        self.hook()
        self.assertTrue(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))
        self.assertEqual(core.task_path(self.root, 'FREE').read_bytes(), before)

    def test_foreign_claim_without_local_token_is_not_selected(self):
        before = self.branchless_task('FOREIGN', worker='another-worker')
        core._local_claim_path(self.root, 'FOREIGN').unlink()
        self.assertNotIn('Continue FOREIGN', self.hook())
        self.assertTrue(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))
        self.assertEqual(core.task_path(self.root, 'FOREIGN').read_bytes(), before)

    def test_local_claim_for_a_different_worker_is_not_selected(self):
        before = self.branchless_task('FOREIGN', worker='another-worker')
        path = core._local_claim_path(self.root, 'FOREIGN')
        local = json.loads(path.read_text()); local['worker'] = 'local-worker'; path.write_text(json.dumps(local))
        self.assertNotIn('Continue FOREIGN', self.hook())
        self.assertTrue(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))
        self.assertEqual(core.task_path(self.root, 'FOREIGN').read_bytes(), before)

    def test_ineligible_tasks_do_not_make_one_valid_claim_ambiguous(self):
        before = self.branchless_task('ELIGIBLE')
        self.branchless_task('DONE', status='done')
        core.task_new(self.root, 'FREE', 'Unclaimed', repo=str(self.root))
        other = self.root / 'other'; other.mkdir()
        subprocess.run(['git', 'init', '-q', str(other)], check=True, capture_output=True)
        self.branchless_task('OTHER', repo=str(other))
        self.branchless_task('FOREIGN', worker='another-worker')
        core._local_claim_path(self.root, 'FOREIGN').unlink()
        self.assertIn('Continue ELIGIBLE', self.hook())
        self.assertEqual(core.task_path(self.root, 'ELIGIBLE').read_bytes(), before)
        self.assertFalse(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))

    def test_branch_match_wins_over_claimed_branchless_task(self):
        before = self.branchless_task('GENERIC')
        core.task_new(self.root, 'BRANCH', 'Branch task', branch='feature/a', repo=str(self.root))
        core.claim(self.root, 'BRANCH', 'branch-worker')
        core.checkpoint(self.root, 'BRANCH', 'in_progress', 'Continue BRANCH')
        output = self.hook()
        self.assertIn('Continue BRANCH', output)
        self.assertEqual(core.task_path(self.root, 'GENERIC').read_bytes(), before)
        self.assertFalse(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))

    def test_corrupt_local_claim_never_breaks_hook(self):
        self.branchless_task('BROKEN')
        core._local_claim_path(self.root, 'BROKEN').write_text('[]')
        self.hook()
        self.assertTrue(any(t['id'].startswith('BR-') for t in core.task_list(self.root)))

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

    def test_remember_follows_branch_with_multiple_local_claims(self):
        self.hook(); first = core.task_list(self.root)[0]['id']
        core.remember(self.root, 'keep amber')
        before = core.task_path(self.root, first).read_bytes()
        core.task_new(self.root, 'LEGACY', 'Generic legacy task'); core.claim(self.root, 'LEGACY', 'local')
        self.git('switch', '-qc', 'feature/b'); self.hook()
        saved = core.remember(self.root, 'keep violet')
        self.assertNotEqual(saved['task'], first)
        core.checkpoint(self.root, saved['task'], 'in_progress', 'Inspect violet', notes={'Handoff': 'Handoff rewritten.'})
        self.assertIn('keep violet', core.brief(self.root))
        self.assertNotIn('keep amber', core.brief(self.root))
        self.assertEqual(before, core.task_path(self.root, first).read_bytes())
        self.git('switch', '-q', 'feature/a')
        self.assertIn('keep amber', core.brief(self.root))

    def test_stop_keeps_the_session_task_after_git_branch_switch(self):
        start = {'hook_event_name': 'SessionStart', 'session_id': 'session-a', 'cwd': str(self.root)}
        with mock.patch('sys.stdin', io.StringIO(json.dumps(start))), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', 'codex']), 0)
        first = core.task_list(self.root)[0]['id']
        start['session_id'] = 'overlapping-session'
        with mock.patch('sys.stdin', io.StringIO(json.dumps(start))), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', 'codex']), 0)
        self.git('switch', '-qc', 'feature/b'); self.hook()
        second = next(t['id'] for t in core.task_list(self.root) if t['branch'] == 'feature/b')
        before = core.task_path(self.root, second).read_bytes()
        transcript = self.root / 'session-a.jsonl'
        transcript.write_text('\n'.join(map(json.dumps, [
            {'type': 'user', 'message': {'content': 'Decided: only amber.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next step: inspect amber.'}]}}])))
        stop = {'hook_event_name': 'Stop', 'session_id': 'session-a', 'transcript_path': str(transcript)}
        with mock.patch('sys.stdin', io.StringIO(json.dumps(stop))), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'nudge', '--hook', '--client', 'codex']), 0)
        self.assertIn('only amber', core.task_read(self.root, first, ['Handoff'])['sections']['Handoff'])
        self.assertEqual(before, core.task_path(self.root, second).read_bytes())
        first_after = core.task_path(self.root, first).read_bytes()
        start['session_id'] = 'session-a'  # Same session now spans tasks: capture must fail closed.
        with mock.patch('sys.stdin', io.StringIO(json.dumps(start))), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', 'codex']), 0)
        before = core.task_path(self.root, second).read_bytes()
        stop['session_id'] = 'session-a'
        with mock.patch('sys.stdin', io.StringIO(json.dumps(stop))), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'nudge', '--hook', '--client', 'codex']), 0)
        self.assertEqual(first_after, core.task_path(self.root, first).read_bytes())
        self.assertEqual(before, core.task_path(self.root, second).read_bytes())
        stop['session_id'] = 'unknown-session'
        with mock.patch('sys.stdin', io.StringIO(json.dumps(stop))), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'nudge', '--hook', '--client', 'codex']), 0)
        self.assertEqual(before, core.task_path(self.root, second).read_bytes())

    def test_session_bindings_keep_recent_200_and_fail_closed_after_eviction(self):
        from ws import assist
        self.hook()
        task = core.sole_local_claim(self.root)
        def start(session):
            assist.observe(self.root, {'hook_event_name': 'SessionStart', 'session_id': session})
        for i in range(3):
            start(str(i))
        data = assist.state(self.root)  # seed the other bindings directly: 200 hook runs only repeat the same step
        data['session_tasks'].update({core.digest_text(str(i)): task for i in range(3, 200)})
        assist.save(self.root, data)
        start('0')  # Refresh an existing binding before the next insertion.
        start('200')
        self.assertEqual(len(assist.state(self.root)['session_tasks']), 200)
        self.assertEqual(assist.session_task(self.root, '0'), task)
        self.assertEqual(assist.session_task(self.root, '1'), '')
        self.assertEqual(assist.session_task(self.root, '200'), task)
        data = assist.state(self.root)
        data['session_tasks'][core.digest_text('0')] = ''
        assist.save(self.root, data)
        start('0')
        self.assertEqual(assist.session_task(self.root, '0'), '')
        self.assertEqual(len(assist.state(self.root)['session_tasks']), 200)

    def test_git_lookup_failure_keeps_saved_memory_readable(self):
        self.hook()
        task = core.sole_local_claim(self.root)
        core.remember(self.root, 'keep amber for the guard', task_id=task)
        with mock.patch('ws.core._task_git', return_value=''):
            self.assertIn('keep amber for the guard', core.brief(self.root))

    def test_git_lookup_failure_refuses_automatic_capture(self):
        self.hook()
        task = core.sole_local_claim(self.root)
        before = core.task_path(self.root, task).read_bytes()
        transcript = self.root / 'unavailable-git.jsonl'
        transcript.write_text('\n'.join(map(json.dumps, [
            {'type': 'user', 'message': {'content': 'Decided: keep violet for the guard.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                {'type': 'text', 'text': 'Next step: inspect violet.'}]}}])))
        with mock.patch('ws.core._task_git', return_value=''):
            for binding in (None, task):
                self.assertFalse(core.capture_decisions(self.root, str(transcript), task_id=binding))
                self.assertEqual(before, core.task_path(self.root, task).read_bytes())

    def test_session_start_without_eligible_claim_invalidates_old_binding(self):
        from ws import assist
        self.hook()
        task = core.sole_local_claim(self.root)
        payload = {'hook_event_name': 'SessionStart', 'session_id': 'same-session'}
        assist.observe(self.root, payload)
        self.assertEqual(assist.session_task(self.root, 'same-session'), task)
        with mock.patch('ws.core.sole_local_claim', return_value=''):
            assist.observe(self.root, payload)
        self.assertEqual(assist.session_task(self.root, 'same-session'), '')
