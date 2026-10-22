import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from ws import cli, core, knowledge, sharing, team, team_auto, team_sync

IDENT = ('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid')


class TeamSyncRobustTests(unittest.TestCase):
    """Two workspaces (alice hosts, bob links) sharing one local bare team repo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        p = mock.patch.dict(os.environ, HOME=str(self.base), USERPROFILE=str(self.base), WS_OFFLINE='1')
        p.start(); self.addCleanup(p.stop)
        self.remote = self.base / 'team.git'; team._git(self.base, 'init', '--bare', '-q', str(self.remote))
        self.a, self.b = self.base / 'alice', self.base / 'bob'
        for root in (self.a, self.b): core.init(root, 'synthetic', clients=[])
        team.manage(self.a, 'init', str(self.remote), apply=True, attest=True)
        self.sync(self.a)
        team.manage(self.b, 'link', str(self.remote), apply=True, attest=True)
        self.ca, self.cb = self.a / '.ws/team', self.b / '.ws/team'

    def sync(self, root):
        return team_sync.apply(root, team_sync.preview(root))

    def share(self, root, text):
        item = knowledge.add(root, text, 'repo', True)
        sharing.apply(root, sharing.preview(root, item, author=root.name))

    def published_index(self):
        return team._git(self.remote, 'show', 'HEAD:INDEX.md')

    def check_race(self, bob_has_pulled_before):
        if bob_has_pulled_before:  # bob's INDEX.md becomes a tracked, modified file
            self.share(self.a, 'Alice first note about queues.'); self.sync(self.a); team_auto.pull(self.b)
        self.share(self.a, 'Alice second note about caches.'); self.share(self.b, 'Bob note about retries.')
        self.sync(self.a)
        self.assertTrue(self.sync(self.b)['pushed'])  # was: "Team sync Git operation stopped"
        index = self.published_index()
        for words in ('Alice second note', 'Bob note about retries'): self.assertIn(words, index)
        self.assertEqual('', team._git(self.cb, 'status', '--porcelain'))

    def test_second_publisher_with_untracked_index_syncs_and_index_lists_both(self):
        self.check_race(False)

    def test_second_publisher_with_modified_index_syncs_and_index_lists_both(self):
        self.check_race(True)

    def test_real_pull_conflict_names_the_file_and_the_recovery_command(self):
        (self.ca / 'notice.md').write_text('one\n')
        team._git(self.ca, 'add', 'notice.md'); team._git(self.ca, *IDENT, 'commit', '-qm', 'n'); team._git(self.ca, 'push', '-q', 'origin', 'HEAD')
        team_auto.pull(self.b); (self.cb / 'notice.md').write_text('bob edit\n')
        (self.ca / 'notice.md').write_text('two\n')
        team._git(self.ca, *IDENT, 'commit', '-qam', 'n2'); team._git(self.ca, 'push', '-q', 'origin', 'HEAD')
        with self.assertRaises(core.WsError) as caught: team_sync.preview(self.b)
        self.assertIn('notice.md', str(caught.exception)); self.assertIn('git -C', str(caught.exception))
        self.assertEqual('bob edit\n', (self.cb / 'notice.md').read_text())

    def corrupt(self, root=None):
        (self.cb / 'team.json').write_text('{ not json')

    def test_corrupt_manifest_error_names_the_path_everywhere(self):
        self.corrupt(); path = str(self.cb / 'team.json')
        for call in (lambda: team_sync.preview(self.b), lambda: knowledge._bases(self.b, 'team')):
            with self.assertRaises(core.WsError) as caught: call()
            self.assertIn(path, str(caught.exception))
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = cli.main(['--workspace-root', str(self.b), 'know', 'list', '--layer', 'team'])
        self.assertEqual(2, code); self.assertIn(path, err.getvalue()); self.assertNotIn('Traceback', err.getvalue())

    def test_corrupt_manifest_does_not_block_private_reads(self):
        item = knowledge.add(self.b, 'Private note about queues.', 'other', False)
        self.corrupt()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            listing = knowledge.list_entries(self.b)
            hits = core.search(self.b, 'queues', category='other')
        self.assertEqual(1, len(listing['entries'])); self.assertIn('team.json', listing['warnings'][0])
        self.assertEqual(1, len(hits)); self.assertIn('team.json', err.getvalue())
        with self.assertRaises(core.WsError): knowledge.list_entries(self.b, layer='team')

    def test_doctor_reports_a_corrupt_manifest(self):
        self.assertFalse(core.doctor(self.b)['team_workspace'].get('problem'))
        self.corrupt()
        self.assertIn('team.json', core.doctor(self.b)['team_workspace']['problem'])
        self.assertIn('team.json', cli.text_doctor(core.doctor(self.b)))

    def test_pull_only_still_pulls_a_teammates_revert_after_a_corrupt_manifest(self):
        good = (self.ca / 'team.json').read_text()
        (self.ca / 'team.json').write_text('{ not json')
        team._git(self.ca, *IDENT, 'commit', '-qam', 'oops'); team._git(self.ca, 'push', '-q', 'origin', 'HEAD')
        with self.assertRaises(core.WsError) as caught: team_auto.pull(self.b)  # pulled, then refused to use it
        self.assertIn('team.json', str(caught.exception))
        self.assertEqual('{ not json', (self.cb / 'team.json').read_text())
        (self.ca / 'team.json').write_text(good)
        team._git(self.ca, *IDENT, 'commit', '-qam', 'revert'); team._git(self.ca, 'push', '-q', 'origin', 'HEAD')
        self.assertTrue(team_auto.pull(self.b)['updated'])  # was blocked by the local corrupt manifest
        self.assertEqual(good, (self.cb / 'team.json').read_text())
        knowledge._bases(self.b, 'team')

    def push_from_alice(self, name, text):
        (self.ca / name).write_text(text)
        team._git(self.ca, 'add', name); team._git(self.ca, *IDENT, 'commit', '-qm', name); team._git(self.ca, 'push', '-q', 'origin', 'HEAD')

    def test_failed_pull_keeps_the_local_index(self):
        self.push_from_alice('notice.md', 'one\n')
        (self.cb / 'notice.md').write_text('bob edit\n'); (self.cb / 'INDEX.md').write_text('local index\n')
        with self.assertRaises(core.WsError): team_sync.preview(self.b)
        self.assertEqual('local index\n', (self.cb / 'INDEX.md').read_text())

    def test_pulled_foreign_index_is_a_warning_not_a_failed_pull(self):
        self.push_from_alice('INDEX.md', 'teammate hand-written index\n')
        (self.cb / 'INDEX.md').write_text('local index\n')
        err = io.StringIO()
        with contextlib.redirect_stderr(err): result = team_auto.pull(self.b)
        self.assertTrue(result['updated']); self.assertIn('INDEX.md', err.getvalue())
        self.assertEqual('teammate hand-written index\n', (self.cb / 'INDEX.md').read_text())


if __name__ == '__main__':
    unittest.main()
