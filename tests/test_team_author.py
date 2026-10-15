import contextlib
import io
import unittest
from unittest import mock
import test_sharing
from ws import cli, core, knowledge, sharing, team


class TeamAuthorTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def save(self, args):
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main(['--workspace-root', str(self.root), *args])

    def test_default_git_name_and_override_reach_team_records(self):
        (self.base / '.gitconfig').write_text('[user]\n name = Fixture Writer / QA\n', encoding='utf-8')
        self.assertEqual(self.save(['know', 'add', 'Receipt checks need checksums.', '--team', '--yes']), 0)
        self.assertEqual(knowledge.list_entries(self.root, layer='team')['entries'][0]['author'], 'Fixture-Writer-QA')
        self.assertEqual(self.save(['know', 'add', 'Queues need bounded retries.', '--team', '--author', 'qa.test', '--yes']), 0)
        self.assertEqual({r['author'] for r in knowledge.list_entries(self.root, layer='team')['entries']}, {'Fixture-Writer-QA', 'qa.test'})

    def test_shared_decision_lesson_and_task_accept_explicit_alias(self):
        for args in (['remember', 'Keep stable receipts.', '--team'],
                     ['lesson', 'add', 'A retry loop stalled; bound retries.', '--team'],
                     ['share', 'task:T1']):
            self.assertEqual(self.save([*args, '--author', 'fixture', '--yes']), 0)
        for path in (self.clone / 'entries').glob('*.md'):
            if not path.name.endswith('.index.md'):
                self.assertEqual(core.parse_meta(path.read_text())['author'], 'fixture')

    def test_alias_fallback_and_length_are_portable(self):
        for name, expected in [('', 'local'), ('名字', 'local'), ('A' * 80, 'A' * 40)]:
            with mock.patch.object(team, '_git', return_value=name):
                self.assertEqual(sharing.default_author(self.root), expected)
        with mock.patch.object(team, '_git', side_effect=core.WsError('Git unavailable')):
            self.assertEqual(sharing.default_author(self.root), 'local')

    def test_preview_decline_never_copies_and_invalid_override_is_refused(self):
        with mock.patch('builtins.input', return_value='n') as confirm:
            self.assertEqual(self.save(['know', 'add', 'Portable receipt contract.', '--team', '--author', 'fixture']), 0)
        self.assertEqual(confirm.call_count, 1)
        self.assertFalse((self.clone / 'entries').exists())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(self.save(['know', 'add', 'Portable receipt contract.', '--team', '--author', 'bad/name', '--yes']), 0)
        self.assertFalse((self.clone / 'entries').exists())

    def test_brief_label_is_short_and_details_keep_full_provenance(self):
        item = knowledge.add(self.root, 'The receipt verifier needs a checksum field.', 'repo', True)
        plan = sharing.preview(self.root, item, author='fixture'); sharing.apply(self.root, plan)
        core.checkpoint(self.root, 'T1', 'in_progress', 'Inspect the receipt verifier.')
        text = core.brief(self.root)
        self.assertIn('Team (untrusted, fixture, ' + plan['date'] + '):', text)
        self.assertNotIn(plan['entry'], text); self.assertNotIn(plan['source_sha'][:8], text)
        self.assertLess(len(text.split()), 200)
        detail = knowledge.show(self.root, 'team:' + plan['entry'])
        self.assertEqual(detail['source_sha'], plan['source_sha'])
        self.assertEqual(detail['team'], core.config(self.root)['team_workspace']['id'])
