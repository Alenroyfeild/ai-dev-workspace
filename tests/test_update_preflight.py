"""Update checks inspect disposable installations without changing Git state."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from ws import cli, core


class UpdatePreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        environment = mock.patch.dict(os.environ, {
            'HOME': str(self.home), 'USERPROFILE': str(self.home),
            'CODEX_HOME': str(self.home / '.codex'), 'WS_OFFLINE': '1',
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_AUTHOR_NAME': 'Fixture', 'GIT_COMMITTER_NAME': 'Fixture',
            'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
            'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.seed, self.kit = self.root / 'seed', self.root / 'kit'
        self.seed.mkdir()
        self.git(self.seed, 'init', '-q', '-b', 'main')
        self.git(self.root, 'init', '--bare', '-q', '-b', 'main', 'origin.git')
        (self.seed / 'kit.json').write_text(json.dumps({'version': '0.1.0', 'repo': 'fixture/kit'}), encoding='utf-8')
        self.git(self.seed, 'add', 'kit.json')
        self.commit(self.seed, 'initial')
        self.git(self.seed, 'remote', 'add', 'origin', str(self.root / 'origin.git'))
        self.git(self.seed, 'push', '-q', '-u', 'origin', 'main')
        self.git(self.root, 'clone', '-q', str(self.root / 'origin.git'), str(self.kit))
        (self.kit / 'packs').mkdir()  # CLI help eagerly enumerates this directory.
        for name, value in (('KIT', self.kit), ('PACKAGED', False)):
            patch = mock.patch.object(core, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def git(self, repo, *args):
        return subprocess.run(['git', '--no-optional-locks', '-C', str(repo), *args],
                              check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, repo, message):
        (repo / 'tracked.txt').write_text(message, encoding='utf-8')
        self.git(repo, 'add', 'tracked.txt')
        self.git(repo, 'commit', '-qm', message)

    def snapshot(self):
        return (self.git(self.kit, 'rev-parse', 'HEAD'),
                self.git(self.kit, 'rev-parse', '--abbrev-ref', 'HEAD'),
                hashlib.sha256((self.kit / '.git' / 'index').read_bytes()).hexdigest(),
                (self.kit / '.git' / 'config').read_bytes())

    def check(self):
        before = self.snapshot()
        stdout = io.StringIO()
        with mock.patch('subprocess.run', wraps=subprocess.run) as commands, \
                mock.patch.object(core, '_get_json', side_effect=AssertionError('offline network')) as network, \
                contextlib.redirect_stdout(stdout):
            self.assertEqual(cli.main(['update', '--check']), 0)
        network.assert_not_called()
        self.assertEqual(self.snapshot(), before, 'check changed HEAD, branch, index or config')
        for call in commands.call_args_list:
            self.assertFalse({'pull', 'fetch', 'reset', 'switch', 'checkout', 'merge', 'rebase'} & set(call.args[0]))
        result = json.loads(stdout.getvalue())
        self.assertTrue(result['offline'])
        return result['preflight']

    def test_clean_checkout(self):
        report = self.check()
        self.assertEqual(report['installation'], 'source')
        self.assertEqual(report['branch'], 'main')
        self.assertEqual(report['upstream'], 'origin/main')
        self.assertEqual((report['ahead'], report['behind']), (0, 0))
        self.assertEqual(report['dirty_files'], [])

    def test_ahead_lists_local_commits_and_choices(self):
        self.commit(self.kit, 'local-only')
        report = self.check()
        self.assertEqual(report['state'], 'ahead')
        self.assertEqual((report['ahead'], report['behind']), (1, 0))
        self.assertIn('local-only', '\n'.join(report['local_commits']))
        self.assertTrue(all(word in ' '.join(report['choices']).lower() for word in ('merge', 'rebase', 'skip')))

    def test_diverged_counts_each_side(self):
        self.commit(self.kit, 'local-side')
        self.commit(self.seed, 'remote-side')
        self.git(self.seed, 'push', '-q', 'origin', 'main')
        self.git(self.kit, 'fetch', '-q', 'origin')  # fixture setup, never part of check
        report = self.check()
        self.assertEqual(report['state'], 'diverged')
        self.assertEqual((report['ahead'], report['behind']), (1, 1))
        self.assertIn('local-side', '\n'.join(report['local_commits']))
        self.assertNotIn('remote-side', '\n'.join(report['local_commits']))

    def test_no_upstream_lists_history_without_guessing_local_only(self):
        self.git(self.kit, 'branch', '--unset-upstream')
        report = self.check()
        self.assertEqual(report['state'], 'no-upstream')
        self.assertIsNone(report['upstream'])
        self.assertIsNone(report['ahead'])
        self.assertTrue(report['local_commits'])
        self.assertIn('no upstream', ' '.join(report['notes']).lower())
        self.assertTrue(report['choices'])

    def test_dirty_files_including_spaces_are_reported(self):
        (self.kit / 'tracked.txt').write_text('uncommitted', encoding='utf-8')
        (self.kit / 'space name.txt').write_text('untracked', encoding='utf-8')
        report = self.check()
        self.assertEqual(set(report['dirty_files']), {'tracked.txt', 'space name.txt'})
        self.assertEqual(report['state'], 'dirty')
        self.assertIn('stash', ' '.join(report['choices']).lower())
        self.assertEqual((self.kit / 'tracked.txt').read_text(), 'uncommitted')

    def test_detached_is_reported_without_switching(self):
        self.git(self.kit, 'checkout', '-q', '--detach')
        report = self.check()
        self.assertEqual(report['state'], 'detached')
        self.assertIsNone(report['branch'])
        self.assertTrue(report['choices'])

    def test_behind_only_suggests_fast_forward_as_text(self):
        self.commit(self.seed, 'upstream-side')
        self.git(self.seed, 'push', '-q', 'origin', 'main')
        self.git(self.kit, 'fetch', '-q', 'origin')
        report = self.check()
        self.assertEqual((report['ahead'], report['behind']), (0, 1))
        self.assertIn('fast-forward', ' '.join(report['choices']).lower())

    def test_package_uses_package_route_not_parent_repo(self):
        with mock.patch.object(core, 'PACKAGED', True), \
                mock.patch('subprocess.run', side_effect=AssertionError('package Git lookup')), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(cli.main(['update', '--check']), 0)
        report = json.loads(stdout.getvalue())['preflight']
        self.assertEqual(report['installation'], 'package')
        self.assertIsNone(report['branch'])
        self.assertIn('pipx upgrade', ' '.join(report['choices']))

    def test_missing_git_is_an_actionable_preflight_not_a_crash(self):
        with mock.patch('subprocess.run', side_effect=FileNotFoundError('git unavailable')), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(cli.main(['update', '--check']), 0)
        report = json.loads(stdout.getvalue())['preflight']
        self.assertEqual(report['state'], 'unavailable')
        self.assertIn('git unavailable', report['error'])

    def test_shallow_history_is_labelled_as_partial(self):
        shallow = self.root / 'shallow'
        self.git(self.root, 'clone', '-q', '--depth', '1', (self.root / 'origin.git').as_uri(), str(shallow))
        (shallow / 'packs').mkdir()
        self.kit = shallow
        with mock.patch.object(core, 'KIT', shallow):
            self.assertIn('shallow', ' '.join(self.check()['notes']).lower())

    def test_source_archive_does_not_inspect_an_ancestor_repo(self):
        (self.kit / '.git').rename(self.kit / '.git-held')
        with mock.patch('subprocess.run', side_effect=AssertionError('archive Git lookup')), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(cli.main(['update', '--check']), 0)
        self.assertEqual(json.loads(stdout.getvalue())['preflight']['state'], 'not-a-clone')

    def test_online_release_check_still_runs_alongside_local_preflight(self):
        before = self.snapshot()
        with mock.patch.dict(os.environ, {'WS_OFFLINE': '0'}), \
                mock.patch.object(core, '_get_json', return_value=[{'tag_name': 'v9.9.9'}]) as request, \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(cli.main(['update', '--check']), 0)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result['latest'], '9.9.9')
        self.assertEqual(result['preflight']['branch'], 'main')
        request.assert_called_once()
        self.assertEqual(self.snapshot(), before)
