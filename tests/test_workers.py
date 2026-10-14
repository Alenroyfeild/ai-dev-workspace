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

    def complete_worker(self, plan):
        record = Path(plan['record']); state = json.loads(record.read_text())
        state.update(started_at='fixture', finished_at='fixture', worker_exit=0,
                     checks=[dict(command='python3 -m unittest', exit_code=0)])
        record.write_text(json.dumps(state))

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
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'worker', 'launch', plan['id']]), 2)
        self.assertIn('O2d', errors.getvalue())
        self.assertEqual(Path(plan['record']).read_bytes(), before)

    def test_internal_probe_launch_collects_snapshot_and_protects_source(self):
        plan = self.prepare(apply=True); checkout = Path(plan['checkout']); source = self.git('status', '--porcelain')
        binding = dict(provider='codex', model='fixture', effort='low', available=True, executable='codex', timeout_seconds=10)
        def run(binding, repo, body, receipt=None):
            self.assertNotIn('--sandbox', binding['headless']); self.assertNotIn('-s', binding['headless'])
            self.assertIn('shell_environment_policy.inherit="none"', binding['headless'])
            self.assertIn('--ignore-user-config', binding['headless']); self.assertIn('default_permissions="worker-private"', binding['headless'])
            (checkout / 'calc.py').write_bytes(b'answer = 2\r\n')
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
        self.assertNotIn(json.dumps(str(Path.home() / '.codex')) + ' = ', next(line for line in profile.splitlines() if line.startswith('permissions.')))

    def test_profile_reads_only_resolved_codex_install(self):
        plan = self.prepare(apply=True); directory = Path(plan['directory'])
        home = self.root / 'synthetic-home'
        package = home / '.codex/packages/standalone/releases/fixture'
        executable = package / 'bin/codex'; executable.parent.mkdir(parents=True)
        executable.write_text('fixture executable')
        manifest = package / 'codex-package.json'
        manifest.write_text(json.dumps(dict(layoutVersion=1, variant='codex', entrypoint='bin/codex')))
        alias = home / '.local/bin/codex'; alias.parent.mkdir(parents=True)
        alias.symlink_to(executable)
        with mock.patch('ws.workers.Path.home', return_value=home): workers._profile(directory, alias)
        profile = (directory / 'worker.config.toml').read_text().splitlines()[3]
        self.assertIn(json.dumps(str(executable.resolve())) + ' = "read"', profile)
        self.assertIn(json.dumps(str(package.resolve())) + ' = "read"', profile)
        for path in (home, home / '.codex', alias.parent, home / '.codex/config.toml', home / '.codex/auth.json'):
            self.assertNotIn(json.dumps(str(path)) + ' = ', profile)
        for metadata in ([], dict(layoutVersion=1, variant='codex', entrypoint='../other')):
            manifest.write_text(json.dumps(metadata))
            with mock.patch('ws.workers.Path.home', return_value=home): workers._profile(directory, alias)
            profile = (directory / 'worker.config.toml').read_text().splitlines()[3]
            self.assertNotIn(json.dumps(str(package.resolve())) + ' = ', profile)
        manifest.write_text(json.dumps(dict(layoutVersion=1, variant='codex', entrypoint='bin/codex')))
        with mock.patch('ws.workers.Path.home', return_value=package): workers._profile(directory, alias)
        profile = (directory / 'worker.config.toml').read_text().splitlines()[3]
        self.assertNotIn(json.dumps(str(package.resolve())) + ' = ', profile)
        unrelated = self.root / 'unrelated'; other = unrelated / 'bin/codex'
        other.parent.mkdir(parents=True); other.write_text('lookalike executable')
        (unrelated / 'secret.txt').write_text('synthetic private file')
        (unrelated / 'codex-package.json').write_text(manifest.read_text())
        with mock.patch('ws.workers.Path.home', return_value=home): workers._profile(directory, other)
        profile = (directory / 'worker.config.toml').read_text().splitlines()[3]
        self.assertNotIn(json.dumps(str(unrelated.resolve())) + ' = ', profile)

    def test_collection_blocks_ignored_out_of_scope_secrets_binary_and_symlinks(self):
        for name, data in (('ignored.txt', b'ignored change'), ('calc.py', b'api_key=' + b'x'*20), ('calc.py', b'\xffbinary')):
            with self.subTest(name=name, data=data):
                plan = self.prepare(apply=True); (Path(plan['checkout']) / name).write_bytes(data)
                self.complete_worker(plan)
                result = workers.collect(self.root, plan['id'])
                self.assertTrue(result['blocked']); self.assertIn(name, result['changed'])
                if data.startswith(b'\xff'): self.assertEqual(result['binary_files'], [name])
                self.assertNotIn('x'*20, json.dumps(result))
        plan = self.prepare(apply=True)
        (Path(plan['checkout']) / 'escape').symlink_to(self.repo / 'calc.py')
        self.complete_worker(plan)
        self.assertTrue(workers.collect(self.root, plan['id'])['blocked'])

    def test_collection_blocks_prepared_run_without_worker_evidence(self):
        plan = self.prepare(apply=True)
        (Path(plan['checkout']) / 'calc.py').write_text('answer = 2\n')
        result = workers.collect(self.root, plan['id'])
        self.assertTrue(result['blocked'])
        self.assertIn('completed worker', result['reason'])

    def test_collection_preserves_leading_space_in_changed_filename(self):
        plan = self.prepare(apply=True); (Path(plan['checkout']) / ' calc.py').write_text('api_key=' + 'x'*20)
        self.complete_worker(plan)
        result = workers.collect(self.root, plan['id'])
        self.assertTrue(result['blocked']); self.assertIn(' calc.py', result['changed'])

    def test_collection_disables_rename_detection_for_scope_check(self):
        (self.repo / 'outside.txt').write_text('answer = 1\n')
        self.git('add', 'outside.txt'); self.git('-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'add out-of-scope file')
        with mock.patch('ws.orchestration.route', return_value=dict(provider='codex', model='fixture', effort='low', available=False)):
            plan = workers.prepare(self.root, 'W-1', ['allowed.py'], apply=True)
        checkout = Path(plan['checkout']); (checkout / 'outside.txt').rename(checkout / 'allowed.py')
        self.complete_worker(plan)
        result = workers.collect(self.root, plan['id'])
        self.assertTrue(result['blocked']); self.assertIn('outside.txt', result['changed'])

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
        plan = self.prepare(apply=True); os.mkfifo(Path(plan['checkout']) / 'fifo'); self.complete_worker(plan)
        original = workers.git
        def guarded(repo, *args, **kwargs):
            if args[0] == 'add': raise AssertionError('special file reached staging')
            return original(repo, *args, **kwargs)
        with mock.patch('ws.workers.git', side_effect=guarded):
            self.assertTrue(workers.collect(self.root, plan['id'])['blocked'])

    def test_collection_records_invalid_utf8_git_output_as_blocked(self):
        plan = self.prepare(apply=True); self.complete_worker(plan); original = workers.git
        def invalid(repo, *args, **kwargs):
            if '--name-only' in args: raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'fixture')
            return original(repo, *args, **kwargs)
        with mock.patch('ws.workers.git', side_effect=invalid): result = workers.collect(self.root, plan['id'])
        self.assertTrue(result['blocked']); self.assertEqual(result['state'], 'needs-review')
        self.assertTrue(json.loads(Path(plan['record']).read_text())['blocked'])

    def test_secret_scan_uses_snapshot_even_if_checkout_changes_after_staging(self):
        plan = self.prepare(apply=True); self.complete_worker(plan); target = Path(plan['checkout']) / 'calc.py'
        target.write_text('api_key=' + 'x'*20); original = workers.git
        def changed(repo, *args, **kwargs):
            result = original(repo, *args, **kwargs)
            if args[0] == 'add': target.write_text('safe after staging\n')
            return result
        with mock.patch('ws.workers.git', side_effect=changed): result = workers.collect(self.root, plan['id'])
        self.assertTrue(result['blocked']); self.assertEqual(result['secret_files'], ['calc.py'])

    def test_collection_blocks_any_configured_filter_before_staging(self):
        plan = self.prepare(apply=True); self.complete_worker(plan)
        workers.git(Path(plan['checkout']), 'config', 'filter.fixture.clean', 'fixture-unused')
        with mock.patch('ws.workers.git', wraps=workers.git) as calls: result = workers.collect(self.root, plan['id'])
        self.assertFalse(any(c.args[1] == 'add' for c in calls.call_args_list))
        self.assertTrue(result['blocked']); self.assertIn('filter driver configured', result['reason'])

    def test_collection_blocks_oversized_regular_file_before_staging(self):
        (self.repo / 'asset.txt').write_bytes(b'x' * (1024 * 1024 + 1))
        self.git('add', 'asset.txt'); self.git('-c', 'user.name=Fixture', '-c', 'user.email=f@example.invalid', 'commit', '-qm', 'large base asset')
        allowed = self.prepare(apply=True); self.complete_worker(allowed)
        (Path(allowed['checkout']) / 'calc.py').write_text('answer = 2\n')
        self.assertFalse(workers.collect(self.root, allowed['id'])['blocked'])
        plan = self.prepare(apply=True); self.complete_worker(plan)
        (Path(plan['checkout']) / 'calc.py').write_bytes(b'x' * (1024 * 1024 + 1))
        with mock.patch('ws.workers.git', wraps=workers.git) as calls: result = workers.collect(self.root, plan['id'])
        self.assertFalse(any(c.args[1] == 'add' for c in calls.call_args_list))
        self.assertTrue(result['blocked']); self.assertEqual(result['reason'], 'Changed file exceeds the 1 MiB scan limit.')
        for field in ('tree', 'diff_sha', 'checks'): self.assertNotIn(field, result)

    def test_failed_repeat_collection_clears_snapshot_and_check_fields(self):
        plan = self.prepare(apply=True); self.complete_worker(plan)
        (Path(plan['checkout']) / 'calc.py').write_bytes(b'answer = 2\n')
        first = workers.collect(self.root, plan['id']); self.assertFalse(first['blocked'])
        self.assertTrue(first['tree']); self.assertTrue(first['diff_sha']); self.assertTrue(first['checks'])
        (Path(plan['checkout']) / 'ignored.txt').write_bytes(b'outside scope')
        failed = workers.collect(self.root, plan['id']); self.assertTrue(failed['blocked'])
        record = json.loads(Path(plan['record']).read_text())
        for field in ('tree', 'diff_sha', 'checks'):
            self.assertNotIn(field, failed); self.assertNotIn(field, record)

    def collected_for_review(self):
        plan = self.prepare(apply=True); self.complete_worker(plan)
        (Path(plan['checkout']) / 'calc.py').write_text('answer = 2\n')
        self.assertFalse(workers.collect(self.root, plan['id'])['blocked'])
        return plan

    def test_review_uses_verified_tree_bytes_instead_of_forged_patch(self):
        for changed_hash in (False, True):
            with self.subTest(changed_hash=changed_hash):
                plan = self.collected_for_review(); original = workers.collect
                def forged_after_collection(root, run_id):
                    result = original(root, run_id)
                    (Path(plan['directory']) / 'diff.patch').write_text('forged after collection\n')
                    if changed_hash:
                        record = Path(plan['record']); state = json.loads(record.read_text())
                        state['diff_sha'] = '0' * 64; record.write_text(json.dumps(state))
                    return result
                with mock.patch.object(workers, 'collect', side_effect=forged_after_collection):
                    if changed_hash:
                        with self.assertRaisesRegex(core.WsError, 'Worker diff changed since collection; collect again'):
                            workers.review(self.root, plan['id'], approve=True)
                        self.assertNotIn('review', json.loads(Path(plan['record']).read_text()))
                    else:
                        result = workers.review(self.root, plan['id'], approve=True)
                        self.assertIn('answer = 2', result['diff']); self.assertNotIn('forged', result['diff'])

    def test_collection_preserves_terminal_transition_before_record_write(self):
        for terminal in ('accepted', 'discarded'):
            with self.subTest(terminal=terminal):
                plan = self.collected_for_review(); workers.review(self.root, plan['id'], approve=True)
                original = workers.git; transitioned = False
                def transition(repo, *args, **kw):
                    nonlocal transitioned
                    result = original(repo, *args, **kw)
                    if args[:3] == ('diff', '--cached', '--check') and not transitioned:
                        transitioned = True
                        getattr(workers, 'accept' if terminal == 'accepted' else 'discard')(self.root, plan['id'], apply=True)
                    return result
                with mock.patch.object(workers, 'git', side_effect=transition):
                    with self.assertRaisesRegex(core.WsError, 'Worker state changed during collection'):
                        workers.collect(self.root, plan['id'])
                self.assertEqual(json.loads(Path(plan['record']).read_text())['state'], terminal)

    def test_blocked_review_directs_new_run_even_after_checkout_repair(self):
        plan = self.prepare(apply=True); self.complete_worker(plan)
        extra = Path(plan['checkout']) / 'outside.txt'; extra.write_text('out of scope\n')
        self.assertTrue(workers.collect(self.root, plan['id'])['blocked']); extra.unlink()
        message = 'Blocked: start a new run with ws worker prepare'
        self.assertEqual(workers.review(self.root, plan['id'])['message'], message)
        with self.assertRaisesRegex(core.WsError, message): workers.review(self.root, plan['id'], approve=True)
        self.complete_worker(plan)
        with self.assertRaisesRegex(core.WsError, message): workers.collect(self.root, plan['id'])

    def test_accept_warns_later_edits_are_excluded_from_reviewed_snapshot(self):
        plan = self.collected_for_review(); workers.review(self.root, plan['id'], approve=True)
        self.assertNotIn('later edits', workers.accept(self.root, plan['id']).get('warning', ''))
        original = workers.collect
        def later_edit(root, run_id):
            result = original(root, run_id); (Path(plan['checkout']) / 'calc.py').write_text('answer = 99\n')
            return result
        with mock.patch.object(workers, 'collect', side_effect=later_edit), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'worker', 'accept', plan['id'], '--yes']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['warning'], 'later edits in the worker checkout are not included')
        self.assertEqual(self.git('show', result['branch'] + ':calc.py'), 'answer = 2')
        self.assertEqual((Path(plan['checkout']) / 'calc.py').read_text(), 'answer = 99\n')

    def test_review_and_accept_preserve_dirty_source_and_import_exact_snapshot(self):
        plan = self.collected_for_review(); branch = 'ws/worker/' + plan['id']
        (self.repo / 'calc.py').write_text('user edit\n'); (self.repo / 'ignored.txt').write_text('private\n')
        before = (self.git('status', '--porcelain'), self.git('rev-parse', 'HEAD'), (self.repo / '.git/index').read_bytes())
        with self.assertRaisesRegex(core.WsError, 'review'): workers.accept(self.root, plan['id'], apply=True)
        shown = workers.review(self.root, plan['id']); self.assertIn('answer = 2', shown['diff'])
        approved = workers.review(self.root, plan['id'], approve=True)
        self.assertEqual(approved['review']['reviewer'], 'lead')
        self.assertFalse(workers.accept(self.root, plan['id'])['applied'])
        self.assertFalse(workers.accept(self.root, plan['id'], apply=True, confirm=lambda _: False)['applied'])
        result = workers.accept(self.root, plan['id'], apply=True)
        self.assertEqual(result['branch'], branch); self.assertEqual(result['state'], 'accepted')
        self.assertEqual(self.git('show', branch + ':calc.py'), 'answer = 2')
        self.assertEqual(self.git('rev-parse', branch + '^'), plan['base'])
        self.assertEqual(before, (self.git('status', '--porcelain'), self.git('rev-parse', 'HEAD'), (self.repo / '.git/index').read_bytes()))
        self.assertFalse((self.repo / '.git/FETCH_HEAD').exists())
        with self.assertRaises(core.WsError): workers.collect(self.root, plan['id'])
        with self.assertRaises(core.WsError): workers.discard(self.root, plan['id'], apply=True)

    def test_accept_revalidates_content_checks_filters_claim_and_source(self):
        for mutation in ('content', 'checks', 'filter', 'claim', 'source'):
            with self.subTest(mutation=mutation):
                plan = self.collected_for_review(); workers.review(self.root, plan['id'], approve=True)
                record = Path(plan['record']); state = json.loads(record.read_text())
                local = self.root / '.ws/claims/W-1.json'; receipt = local.read_bytes()
                if mutation == 'content': (Path(plan['checkout']) / 'calc.py').write_text('answer = 3\n')
                elif mutation == 'checks':
                    state['checks'][0]['command'] = 'different check'; record.write_text(json.dumps(state))
                elif mutation == 'filter': workers.git(Path(plan['checkout']), 'config', 'filter.fixture.clean', 'unused')
                elif mutation == 'claim': local.unlink()
                else: state['source'] = str(self.root); record.write_text(json.dumps(state))
                with self.assertRaises(core.WsError): workers.accept(self.root, plan['id'], apply=True)
                self.assertEqual(self.git('for-each-ref', '--format=%(refname)', 'refs/heads/ws/worker/'), '')
                if mutation in ('content', 'checks', 'filter'): self.assertNotIn('review', workers.review(self.root, plan['id']))
                if mutation == 'claim': local.write_bytes(receipt)

    def test_accept_refuses_existing_branch_without_overwriting_it(self):
        plan = self.collected_for_review(); workers.review(self.root, plan['id'], approve=True)
        branch = 'ws/worker/' + plan['id']; self.git('branch', branch)
        with self.assertRaisesRegex(core.WsError, 'exists'): workers.accept(self.root, plan['id'], apply=True)
        self.assertEqual(self.git('rev-parse', branch), self.git('rev-parse', 'HEAD'))
        plan = self.collected_for_review(); workers.review(self.root, plan['id'], approve=True)
        ref = 'refs/heads/ws/worker/' + plan['id']; target = 'refs/heads/missing-fixture'
        self.git('symbolic-ref', ref, target)
        with self.assertRaisesRegex(core.WsError, 'exists'): workers.accept(self.root, plan['id'], apply=True)
        self.assertEqual(self.git('symbolic-ref', ref), target)
        self.assertEqual(self.git('for-each-ref', '--format=%(refname)', target), '')

    def test_accept_uses_same_home_alias_resolution_as_preparation(self):
        with mock.patch.dict(os.environ, {'HOME': str(self.root), 'USERPROFILE': str(self.root)}):
            task = core.task_path(self.root, 'W-1')
            task.write_text(task.read_text().replace(str(self.repo), '~/source'))
            plan = self.collected_for_review(); workers.review(self.root, plan['id'], approve=True)
            result = workers.accept(self.root, plan['id'], apply=True)
            self.assertEqual(self.git('show', result['branch'] + ':calc.py'), 'answer = 2')

    def test_accept_pending_receipt_recovers_without_rewriting_refs(self):
        for failure in ('accepted', 'update-ref'):
            plan = self.collected_for_review(); workers.review(self.root, plan['id'], approve=True)
            write, git = core.atomic_write, workers.git
            def interrupted_write(path, content):
                if Path(path) == Path(plan['record']) and json.loads(content)['state'] == failure: raise OSError('fixture write failed')
                return write(path, content)
            def interrupted_git(repo, *args, **kw):
                if args[0] == failure: raise OSError('fixture ref failed')
                return git(repo, *args, **kw)
            with mock.patch.object(core, 'atomic_write', side_effect=interrupted_write), mock.patch.object(workers, 'git', side_effect=interrupted_git):
                with self.assertRaises(OSError): workers.accept(self.root, plan['id'], apply=True)
            pending = json.loads(Path(plan['record']).read_text()); self.assertEqual(pending['state'], 'accepting')
            with self.assertRaises(core.WsError): workers.discard(self.root, plan['id'], apply=True)
            with self.assertRaises(core.WsError): workers.collect(self.root, plan['id'])
            if failure == 'update-ref':
                self.git('branch', pending['branch'])
                with self.assertRaises(core.WsError): workers.accept(self.root, plan['id'], apply=True)
                self.assertEqual(self.git('rev-parse', pending['branch']), plan['base'])
                self.git('branch', '-D', pending['branch'])  # Remove only the test-created collision.
            with mock.patch.object(workers, 'git', wraps=git) as calls:
                result = workers.accept(self.root, plan['id'], apply=True)
            self.assertEqual(result['commit'], pending['commit']); self.assertEqual(result['state'], 'accepted')
            self.assertEqual(sum(c.args[1] == 'update-ref' for c in calls.call_args_list), int(failure == 'update-ref'))

    def test_discard_readonly_retry_is_limited_to_owned_regular_paths(self):
        plan = self.prepare(apply=True); directory = Path(plan['directory']); owned = directory / 'source.git/config'
        original = workers.shutil.rmtree
        def readonly(path, onerror=None):
            if path == directory / 'source.git':
                error = PermissionError('fixture readonly')
                if onerror is None: raise error
                with mock.patch.object(workers.os, 'chmod') as chmod:
                    retry = mock.Mock(); onerror(retry, str(owned), (PermissionError, error, None))
                    self.assertEqual([c.args[0] for c in chmod.call_args_list], [str(owned), str(owned.parent)])
                    retry.assert_called_once_with(str(owned)); chmod.reset_mock()
                    with mock.patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(PermissionError):
                        onerror(retry, str(owned), (PermissionError, error, None))
                    for outside in (self.repo / 'calc.py', directory.parent / 'other-run/file'):
                        with self.assertRaises(PermissionError): onerror(retry, str(outside), (PermissionError, error, None))
                    chmod.assert_not_called()
            return original(path, onerror=onerror)
        with mock.patch.object(workers.shutil, 'rmtree', side_effect=readonly):
            self.assertEqual(workers.discard(self.root, plan['id'], apply=True)['state'], 'discarded')

    def test_discard_readonly_directory_and_file_without_changing_source(self):
        plan = self.prepare(apply=True); checkout = Path(plan['checkout']); file = checkout / 'calc.py'
        before = (self.repo / 'calc.py').stat().st_mode
        file.chmod(0o444); checkout.chmod(0o555)
        try:
            self.assertEqual(workers.discard(self.root, plan['id'], apply=True)['state'], 'discarded')
            self.assertEqual((self.repo / 'calc.py').stat().st_mode, before)
        finally:
            if checkout.exists(): checkout.chmod(0o755)

    def test_discard_only_owned_artifacts_preserves_sibling_and_source(self):
        plan = self.prepare(apply=True); sibling = self.prepare(apply=True)
        original = (self.repo / 'calc.py').read_bytes()
        try: (Path(plan['checkout']) / 'link').symlink_to(self.repo, target_is_directory=True)
        except OSError: pass
        self.assertFalse(workers.discard(self.root, plan['id'])['applied'])
        self.assertFalse(workers.discard(self.root, plan['id'], apply=True, confirm=lambda _: False)['applied'])
        result = workers.discard(self.root, plan['id'], apply=True)
        self.assertEqual(result['state'], 'discarded')
        self.assertEqual([p.name for p in Path(plan['directory']).iterdir()], ['run.json'])
        self.assertTrue(Path(sibling['checkout']).is_dir()); self.assertEqual((self.repo / 'calc.py').read_bytes(), original)
        self.assertFalse(workers.discard(self.root, plan['id'], apply=True)['applied'])
        self.assertEqual(workers.review(self.root, plan['id'])['state'], 'discarded')

    def test_review_refuses_ineligible_run_and_discard_refuses_escaped_owner(self):
        plan = self.prepare(apply=True)
        with self.assertRaises(core.WsError): workers.review(self.root, plan['id'], approve=True)
        record = Path(plan['record']); state = json.loads(record.read_text()); state['directory'] = str(self.repo)
        record.write_text(json.dumps(state))
        with self.assertRaises(core.WsError): workers.discard(self.root, plan['id'], apply=True)
        self.assertTrue(Path(plan['checkout']).exists()); self.assertTrue((self.repo / 'calc.py').exists())

    def test_worker_review_accept_and_discard_cli_actions(self):
        plan = self.collected_for_review()
        for action, flags in (('review', ['--approve', '--yes']), ('accept', ['--yes'])):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(['--workspace-root', str(self.root), 'worker', action, plan['id'], *flags]), 0)
            self.assertEqual(json.loads(output.getvalue())['id'], plan['id'])
        plan = self.prepare(apply=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'worker', 'discard', plan['id'], '--yes']), 0)
