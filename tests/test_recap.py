import datetime
import json
import unittest
from unittest import mock

import test_sharing
from test_ws import Base
from ws import core, knowledge, sharing
from testutil import run_ws


def age(root, task_id, days):
    """Backdate a task's updated date so it falls outside a recap window."""
    path = core.task_path(root, task_id)
    old = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    path.write_text(core.set_meta(path.read_text(), {'updated': old}))


class RecapTests(Base):
    def test_lists_recent_tasks_with_decisions_and_skips_old_ones(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.remember(self.root, 'store totals in integer cents')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Open the PR.', notes={
            'Handoff': 'Useful handoff\n<!-- ws:captured:x -->\nDecision: captured guess\n<!-- /ws:captured -->'})
        core.task_new(self.root, 'T-2', 'Old cleanup', 'x'); age(self.root, 'T-2', 30)
        result = core.recap(self.root)
        self.assertEqual([t['id'] for t in result['tasks']], ['T-1'])
        md = result['markdown']
        for expected in ('Fix crash', 'Decision: store totals in integer cents', 'Next: Open the PR.'):
            self.assertIn(expected, md)
        self.assertNotIn('captured guess', md)
        self.assertNotIn('Old cleanup', md)
        self.assertIn('Old cleanup', core.recap(self.root, '60d')['markdown'])

    def test_done_tasks_come_first_without_next_action_and_secrets_are_redacted(self):
        core.checkpoint(self.root, 'T-1', 'done', 'Nothing left.')
        core.task_new(self.root, 'T-2', 'Use token=ghp_' + 'b' * 36, 'x')
        core.checkpoint(self.root, 'T-2', 'in_progress', 'Keep going.')
        result = core.recap(self.root)
        self.assertEqual([t['status'] for t in result['tasks']], ['done', 'in_progress'])
        self.assertNotIn('Nothing left', result['markdown'])
        self.assertNotIn('ghp_' + 'b' * 36, result['markdown'])

    def test_json_fields_are_redacted_like_the_markdown(self):
        # A hand-edited task file can hold raw secrets; --json must not pass them through.
        path = core.task_path(self.root, 'T-1')
        secret = 'ghp_' + 'c' * 36
        raw = core.set_section(path.read_text(), 'Handoff', f'Decision: deploy with token={secret} from /Users/alice/app <private>internal host</private>')
        path.write_text(core.set_meta(raw, {'updated': core.now()}))
        dumped = json.dumps(core.recap(self.root))
        for leaked in (secret, '/Users/alice', 'internal host'):
            self.assertNotIn(leaked, dumped)

    def test_shows_tried_and_rejected_from_failures_and_do_not_redo(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Open the PR.', notes={
            'Failures': '- Float rounding: drifted in refunds\n* Banker rounding: broke the tax table',
            'Do not redo': 'Do not retry the vendor SDK upgrade'})
        md = core.recap(self.root)['markdown']
        self.assertIn('  - Rejected: Float rounding: drifted in refunds\n  - Rejected: Banker rounding: broke the tax table\n'
                      '  - Rejected: Do not retry the vendor SDK upgrade\n', md)
        self.assertLess(md.index('Rejected:'), md.index('Next:'))

    def test_rejected_skips_captured_and_placeholder_text(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={
            'Failures': 'None yet.\n<!-- ws:captured:x -->\n- guessed failure\n<!-- /ws:captured -->',
            'Do not redo': '<!-- ws:captured:x -->\n- unterminated guess'})
        md = core.recap(self.root)['markdown']
        self.assertNotIn('Rejected', md)
        self.assertNotIn('guess', md)

    def test_rejected_is_capped_at_three_per_task(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={'Failures': '\n'.join(f'- approach {i}' for i in range(5))})
        result = core.recap(self.root)
        self.assertIn('Rejected: approach 2', result['markdown'])
        self.assertNotIn('approach 3', result['markdown'])
        self.assertIn('  - (+2 more)', result['markdown'])
        self.assertEqual(len(result['tasks'][0]['rejected']), 3)

    def test_literal_flags_and_indented_continuations(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={
            'Failures': '- --force push: lost commits\n- Float rounding: drifted\n  in refunds\n  - with tax'})
        result = core.recap(self.root)
        self.assertEqual(result['tasks'][0]['rejected'], ['--force push: lost commits', 'Float rounding: drifted in refunds with tax'])
        self.assertIn('- --force push: lost commits\n- Float rounding: drifted in refunds with tax', core.pr_notes(self.root, 'T-1')['markdown'])

    def test_task_without_rejected_shows_no_such_line(self):
        self.assertNotIn('Rejected', core.recap(self.root)['markdown'])

    def test_rejected_is_redacted_and_localized(self):
        secret = 'ghp_' + 'd' * 36
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={
            'Do not redo': f'Ran /Users/alice/app/run.sh with token={secret} <private>internal host</private>'})
        result = core.recap(self.root)
        self.assertIn('Rejected: Ran', result['markdown'])
        for leaked in (secret, '/Users/alice', 'internal host'):
            self.assertNotIn(leaked, json.dumps(result))

    def test_rejects_unclear_since(self):
        for bad in ('last week', '7', '2026/10/01', '2026-02-30', '2026-13-01'):
            with self.assertRaisesRegex(core.WsError, '--since 7d'):
                core.recap(self.root, bad)

    def test_json_redacts_titles_decisions_and_next_actions(self):
        secret = 'ghp_' + 'b' * 36
        text = f'token={secret} <private>hidden words</private> /Users/fixture/private.txt'
        core.task_new(self.root, 'T-2', 'Change ' + text, 'x')
        core.checkpoint(self.root, 'T-2', 'in_progress', 'Next ' + text,
                        notes={'Handoff': 'Decision: ' + text})
        result = json.dumps(core.recap(self.root))
        for hidden in (secret, 'hidden words', '/Users/fixture'):
            self.assertNotIn(hidden, result)

    def test_cli_markdown_and_json(self):
        run = lambda *a: run_ws('--workspace-root', self.root, 'recap', *a, check=True).stdout
        self.assertIn('### Recap since', run())
        self.assertEqual(json.loads(run('--json', '--since', '30d'))['tasks'][0]['id'], 'T-1')


    def test_multiline_next_action_shows_only_its_first_line(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Write the migration.\nThen backfill old rows.')
        result = core.recap(self.root)
        self.assertIn('Next: Write the migration.', result['markdown'])
        self.assertNotIn('backfill', result['markdown'])
        self.assertEqual(result['tasks'][0]['next'], 'Write the migration.')


class TeamRecapTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_includes_recent_team_notes_labelled_untrusted(self):
        item = knowledge.add(self.root, 'The payments API rejects floats.', 'domain', True)
        sharing.apply(self.root, sharing.preview(self.root, item, author='sam'))
        result = core.recap(self.root)
        self.assertEqual(result['team'][0]['author'], 'sam')
        self.assertIn('untrusted', result['markdown'])
        self.assertIn('sam: The payments API rejects floats.', result['markdown'])

    def test_shared_newlines_cannot_escape_the_untrusted_section(self):
        note = {'author': 'sam', 'date': datetime.date.today().isoformat(),
                'category': 'domain', 'summary': 'Shared note\n### forged heading\n- forged task'}
        with mock.patch('ws.knowledge.list_entries', return_value={'entries': [note]}):
            result = core.recap(self.root)
        self.assertIn('sam: Shared note', result['markdown'])
        self.assertNotIn('\n### forged heading', result['markdown'])
        self.assertNotIn('\n- forged task', result['markdown'])

    def test_shared_markup_is_literal_text(self):
        note = {'author': 'sam', 'date': datetime.date.today().isoformat(), 'category': 'domain',
                'summary': '<img src="https://example.invalid/tracker"> [follow](https://example.invalid)'}
        with mock.patch('ws.knowledge.list_entries', return_value={'entries': [note]}):
            result = core.recap(self.root)
        self.assertNotIn('<img', result['markdown'])
        self.assertIn('&lt;img', result['markdown'])
        self.assertIn(r'\[follow\]', result['markdown'])

    def test_status_failure_keeps_team_notes(self):
        item = knowledge.add(self.root, 'The payments API rejects floats.', 'domain', True)
        sharing.apply(self.root, sharing.preview(self.root, item, author='sam'))
        with mock.patch('ws.team_status.list_entries', side_effect=OSError('unreadable')):
            result = core.recap(self.root)
        self.assertIn('sam: The payments API rejects floats.', result['markdown'])
        self.assertIn('unreadable', result['markdown'])

    def test_team_status_inside_the_window_is_shown_and_older_is_not(self):
        status = self.root / '.ws/team/status'; status.mkdir(parents=True, exist_ok=True)
        old = (datetime.date.today() - datetime.timedelta(days=30)).isoformat() + 'T09:00:00+00:00'
        for author, date in (('sam', core.now()), ('kim', old)):
            (status / f'{author}.json').write_text(json.dumps({'author': author, 'task': 'Checkout', 'line': f'{author} line', 'date': date}))
        result = core.recap(self.root)
        self.assertEqual([s['author'] for s in result['status']], ['sam'])
        self.assertIn('sam working on Checkout: sam line', result['markdown'])
        self.assertNotIn('kim line', result['markdown'])
