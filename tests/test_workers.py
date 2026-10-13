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
        for scope in ([], ['../outside'], ['/tmp/outside'], ['.git/config'], ['.codex/config.toml'], ['C:\\outside'], ['calc.py\noutside'], ['calc.py\ttests'], ['calc.py\x7f']):
            with self.subTest(scope=scope), self.assertRaises(core.WsError): workers.prepare(self.root, 'W-1', scope)
        for base in ('--help', 'missing-commit'):
            with self.subTest(base=base), self.assertRaises(core.WsError): self.prepare(base=base, apply=True)
        cfg = core.config(self.root); cfg['repos'] = []; (self.root / 'workspace.json').write_text(json.dumps(cfg))
        with self.assertRaises(core.WsError): self.prepare(apply=True)
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
            if args[0] == 'clone': raise core.WsError('fixture clone failed')
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
