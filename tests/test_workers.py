import contextlib
import io
import json
import os
import subprocess
from pathlib import Path
from unittest import mock
from test_ws import Base
from ws import cli, core, workers


class WorkerPrepareTests(Base):
    def setUp(self):
        super().setUp()
        self.repo = self.root / 'source'; self.repo.mkdir()
        self.git('init', '-q', '-b', 'feature/fixture')
        (self.repo / 'calc.py').write_text('answer = 1\n')
        (self.repo / '.gitignore').write_text('ignored.txt\n')
        self.git('add', '.'); self.git('-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'fixture')
        cfg = core.config(self.root); cfg['repos'] = [str(self.repo)]; (self.root / 'workspace.json').write_text(json.dumps(cfg))
        core.task_new(self.root, 'W-1', 'Fix fixture', objective='Update calc.py', repo=str(self.repo))
        core.claim(self.root, 'W-1', 'lead')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def prepare(self, **kw):
        with mock.patch('ws.orchestration.route', return_value=dict(provider='codex', model='fixture', effort='low', available=False)):
            return workers.prepare(self.root, 'W-1', ['calc.py'], **kw)

    def test_preview_writes_nothing_and_warns_about_dirty_source(self):
        (self.repo / 'calc.py').write_text('uncommitted\n'); (self.repo / 'ignored.txt').write_text('private fixture\n')
        before = core.task_read(self.root, 'W-1')['sha']; result = self.prepare()
        self.assertEqual(result['base'], self.git('rev-parse', 'HEAD')); self.assertTrue(result['source_dirty'])
        self.assertEqual(result['scope'], ['calc.py']); self.assertFalse(result['applied'])
        self.assertFalse((self.root / '.ws/workers').exists()); self.assertNotIn('claim_token', result)
        self.assertEqual(core.task_read(self.root, 'W-1')['sha'], before)

    def test_private_clone_uses_committed_bytes_and_separate_git_metadata(self):
        (self.repo / 'calc.py').write_text('user edit\n'); (self.repo / 'ignored.txt').write_text('private fixture\n')
        before = self.git('status', '--porcelain'); head = self.git('rev-parse', 'HEAD')
        result = self.prepare(apply=True); checkout = Path(result['checkout'])
        self.assertEqual((checkout / 'calc.py').read_text(), 'answer = 1\n'); self.assertFalse((checkout / 'ignored.txt').exists())
        common = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', '--git-common-dir'], text=True).strip()
        self.assertTrue(Path(common).resolve().is_relative_to(Path(result['directory']).resolve()))
        self.assertNotEqual(Path(common).resolve(), (self.repo / '.git').resolve())
        self.assertEqual(subprocess.check_output(['git', '-C', str(checkout), 'remote'], text=True), '')
        self.assertFalse((Path(common) / 'objects/info/alternates').exists())
        (checkout / 'calc.py').write_text('worker edit\n')
        self.assertEqual((self.repo / 'calc.py').read_text(), 'user edit\n'); self.assertEqual(self.git('status', '--porcelain'), before)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        state = json.loads(Path(result['record']).read_text()); self.assertEqual(state['state'], 'prepared'); self.assertTrue(state['complete'])
        self.assertEqual(state['task_sha'], core.task_read(self.root, 'W-1')['sha'])

    def test_invalid_scope_base_repository_and_claim_refused_without_clone(self):
        for scope in ([], ['../outside'], ['/tmp/outside'], ['.git/config'], ['.codex/config.toml'], ['C:\\outside'], ['\\outside'], ['calc.py\noutside'], ['calc.py\ttests'], ['calc.py\x7f']):
            with self.subTest(scope=scope), self.assertRaises(core.WsError): workers.prepare(self.root, 'W-1', scope)
        for base in ('--help', 'missing-commit'):
            with self.subTest(base=base), self.assertRaises(core.WsError): self.prepare(base=base, apply=True)
        cfg = core.config(self.root)
        for repos in ([], None, [None], ['']):
            cfg['repos'] = repos; (self.root / 'workspace.json').write_text(json.dumps(cfg))
            with self.subTest(repos=repos), self.assertRaises(core.WsError): self.prepare(apply=True)
        cfg['repos'] = [str(self.repo)]; (self.root / 'workspace.json').write_text(json.dumps(cfg))
        (self.root / '.ws/claims/W-1.json').unlink()
        with self.assertRaises(core.WsError): self.prepare(apply=True)
        self.assertFalse((self.root / '.ws/workers').exists())

    def test_gitlinks_refused_and_clone_failure_retains_an_incomplete_record(self):
        self.git('update-index', '--add', '--cacheinfo', '160000,' + self.git('rev-parse', 'HEAD') + ',dependency')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'gitlink')
        with self.assertRaisesRegex(core.WsError, 'submodule'): self.prepare(apply=True)
        original = workers.git
        def interrupted(repo, *args):
            if args[0] == 'fetch': raise core.WsError('fixture fetch failed')
            return original(repo, *args)
        with mock.patch('ws.workers.git', side_effect=interrupted):
            with self.assertRaises(core.WsError): self.prepare(base='HEAD~1', apply=True)
        state = json.loads(next((self.root / '.ws/workers').glob('*/run.json')).read_text())
        self.assertFalse(state['complete']); self.assertIn('failed', state['reason'])

    def test_cli_decline_and_yes_use_one_confirmation(self):
        prefix = ['--workspace-root', str(self.root)]
        with mock.patch('builtins.input', return_value='n') as ask, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(prefix + ['worker', 'prepare', 'W-1', '--scope', 'calc.py']), 0)
        ask.assert_called_once(); self.assertFalse((self.root / '.ws/workers').exists())
        with mock.patch('builtins.input', side_effect=AssertionError('yes must not prompt')), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(prefix + ['worker', 'prepare', 'W-1', '--scope', 'calc.py', '--yes']), 0)
        self.assertTrue(json.loads(output.getvalue())['applied'])

    def test_confirmation_rechecks_claim_and_storage_before_writing(self):
        def changed(_):
            core.release(self.root, 'W-1'); return True
        with self.assertRaisesRegex(core.WsError, 'changed'):
            self.prepare(apply=True, confirm=changed)
        core.claim(self.root, 'W-1', 'lead')
        original = Path.is_symlink
        def redirected(_):
            def is_link(path):
                return path == self.root.resolve() / '.ws/workers' or original(path)
            self.link = mock.patch.object(Path, 'is_symlink', is_link); self.link.start(); return True
        try:
            with self.assertRaisesRegex(core.WsError, 'symlink'): self.prepare(apply=True, confirm=redirected)
        finally: self.link.stop()
        self.assertFalse((self.root / '.ws/workers').exists())

    def test_prepare_copies_a_local_commit_not_reachable_from_any_branch(self):
        head = self.git('rev-parse', 'HEAD')
        commit = self.git('-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit-tree', 'HEAD^{tree}', '-p', head, '-m', 'unreferenced fixture')
        result = self.prepare(base=commit, apply=True)
        self.assertEqual(subprocess.check_output(['git', '-C', result['checkout'], 'rev-parse', 'HEAD'], text=True).strip(), commit)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)

    def test_claim_released_or_replaced_during_clone_keeps_run_incomplete(self):
        original = workers.git
        for replacement in (False, True):
            with self.subTest(replacement=replacement):
                if not core.task_read(self.root, 'W-1', ['Objective'])['meta'].get('claimed_by'):
                    core.claim(self.root, 'W-1', 'lead')
                def changed(repo, *args):
                    result = original(repo, *args)
                    if args[0] == 'worktree':
                        core.release(self.root, 'W-1')
                        if replacement: core.claim(self.root, 'W-1', 'replacement')
                    return result
                with mock.patch('ws.workers.git', side_effect=changed), self.assertRaisesRegex(core.WsError, 'claim'):
                    self.prepare(apply=True)
        records = [json.loads(p.read_text()) for p in (self.root / '.ws/workers').glob('*/run.json')]
        self.assertTrue(all(not r['complete'] and 'claim' in r['reason'] for r in records))

    def test_task_edited_during_clone_keeps_stale_brief_incomplete(self):
        original = workers.git
        def changed(repo, *args):
            result = original(repo, *args)
            if args[0] == 'worktree': core.checkpoint(self.root, 'W-1', 'in_progress', 'Use the revised objective')
            return result
        with mock.patch('ws.workers.git', side_effect=changed), self.assertRaisesRegex(core.WsError, 'Task changed'):
            self.prepare(apply=True)
        state = json.loads(next((self.root / '.ws/workers').glob('*/run.json')).read_text())
        self.assertFalse(state['complete'])

    def test_private_copy_excludes_unrelated_branch_objects(self):
        self.git('checkout', '-qb', 'private-fixture')
        (self.repo / 'private.txt').write_text('unrelated synthetic private content\n')
        self.git('add', 'private.txt')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'private fixture')
        unrelated = self.git('rev-parse', 'HEAD'); self.git('checkout', '-q', 'feature/fixture')
        result = self.prepare(apply=True)
        self.assertFalse((Path(result['checkout']) / 'private.txt').exists())
        check = subprocess.run(['git', '-C', str(Path(result['directory']) / 'source.git'), 'cat-file', '-e', unrelated], capture_output=True)
        self.assertNotEqual(check.returncode, 0)

    def test_write_launch_gate_is_closed_without_writes(self):
        plan = self.prepare(apply=True); before = Path(plan['record']).read_bytes()
        with mock.patch('ws.workers.orchestration.worker_run', side_effect=AssertionError('launch')):
            with self.assertRaisesRegex(core.WsError, 'O2d'): workers.launch(self.root, plan['id'])
        self.assertEqual(Path(plan['record']).read_bytes(), before)

    def test_internal_probe_launch_collects_snapshot_and_protects_source(self):
        plan = self.prepare(apply=True); checkout = Path(plan['checkout']); source = self.git('status', '--porcelain')
        binding = dict(provider='codex', model='fixture', effort='low', available=True, executable='codex', timeout_seconds=10)
        def run(binding, repo, body, receipt=None):
            self.assertNotIn('--sandbox', binding['headless']); self.assertNotIn('-s', binding['headless'])
            self.assertIn('--ignore-user-config', binding['headless']); self.assertIn('default_permissions="worker-private"', binding['headless'])
            (checkout / 'calc.py').write_text('answer = 2\n')
            receipt(json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'python3 -m unittest','exit_code':0}}))
            return 0, 'synthetic checked', 1, 2, True
        with mock.patch('ws.orchestration.route', return_value=binding), mock.patch('ws.orchestration.worker_run', side_effect=run):
            result = workers._launch(self.root, plan['id'])
        self.assertEqual(result['state'], 'needs-review'); self.assertFalse(result['blocked'])
        self.assertEqual(result['changed'], ['calc.py']); self.assertTrue(result['tree']); self.assertTrue(result['diff_sha'])
        self.assertEqual(result['checks'][0]['exit_code'], 0)
        self.assertEqual((self.repo / 'calc.py').read_text(), 'answer = 1\n'); self.assertEqual(self.git('status', '--porcelain'), source)
        profile = (Path(plan['directory']) / 'worker.config.toml').read_text()
        self.assertIn('":minimal" = "read"', profile); self.assertIn('"enabled" = false', profile)
        self.assertNotIn(str(Path.home() / '.codex'), profile)

    def test_collection_blocks_ignored_out_of_scope_secrets_binary_and_symlinks(self):
        for name, data in (('ignored.txt', b'ignored change'), ('calc.py', b'api_key=' + b'x'*20), ('calc.py', b'\xffbinary')):
            with self.subTest(name=name, data=data):
                plan = self.prepare(apply=True); (Path(plan['checkout']) / name).write_bytes(data)
                result = workers.collect(self.root, plan['id'])
                self.assertTrue(result['blocked']); self.assertIn(name, result['changed'])
                self.assertNotIn('x'*20, json.dumps(result))
        plan = self.prepare(apply=True)
        (Path(plan['checkout']) / 'escape').symlink_to(self.repo / 'calc.py')
        self.assertTrue(workers.collect(self.root, plan['id'])['blocked'])

    def test_collection_refuses_changed_claim_and_launch_keeps_gate_closed(self):
        plan = self.prepare(apply=True); (self.root / '.ws/claims/W-1.json').unlink()
        result = workers.collect(self.root, plan['id'])
        self.assertTrue(result['blocked']); self.assertIn('claim', result['reason'].lower())

    def test_launch_failure_or_missing_command_evidence_blocks_collection(self):
        binding = dict(provider='codex', model='fixture', effort='low', available=True, executable='codex', timeout_seconds=10)
        for code in (0, 1):
            plan = self.prepare(apply=True)
            with mock.patch('ws.orchestration.route', return_value=binding), mock.patch('ws.orchestration.worker_run', return_value=(code, 'fixture', 0, 0, False)):
                result = workers._launch(self.root, plan['id'])
            self.assertEqual(result['state'], 'needs-review'); self.assertTrue(result['blocked'])
            self.assertFalse(result['usage']['known'])

    def test_collection_rejects_fifo_before_staging(self):
        if not hasattr(os, 'mkfifo'): self.skipTest('POSIX FIFO fixture')
        plan = self.prepare(apply=True); os.mkfifo(Path(plan['checkout']) / 'fifo')
        original = workers.git
        def guarded(repo, *args, **kwargs):
            if args[0] == 'add': raise AssertionError('special file reached staging')
            return original(repo, *args, **kwargs)
        with mock.patch('ws.workers.git', side_effect=guarded):
            self.assertTrue(workers.collect(self.root, plan['id'])['blocked'])

    def test_collection_records_invalid_utf8_git_output_as_blocked(self):
        plan = self.prepare(apply=True); original = workers.git
        def invalid(repo, *args, **kwargs):
            if '--name-only' in args: raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'fixture')
            return original(repo, *args, **kwargs)
        with mock.patch('ws.workers.git', side_effect=invalid): result = workers.collect(self.root, plan['id'])
        self.assertTrue(result['blocked']); self.assertEqual(result['state'], 'needs-review')
        self.assertTrue(json.loads(Path(plan['record']).read_text())['blocked'])
