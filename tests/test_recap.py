import datetime
import json
import subprocess
import sys
import unittest

import test_sharing
from test_ws import Base, KIT
from ws import core, knowledge, sharing


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
            'Handoff': 'Decision: store totals in integer cents\n<!-- ws:captured:x -->\nDecision: captured guess\n<!-- /ws:captured -->'})
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

    def test_rejects_unclear_since(self):
        for bad in ('last week', '7', '2026/10/01'):
            with self.assertRaisesRegex(core.WsError, '--since 7d'):
                core.recap(self.root, bad)

    def test_cli_markdown_and_json(self):
        run = lambda *a: subprocess.run([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(self.root), 'recap', *a],
                                        capture_output=True, text=True, check=True).stdout
        self.assertIn('### Recap since', run())
        self.assertEqual(json.loads(run('--json', '--since', '30d'))['tasks'][0]['id'], 'T-1')


class TeamRecapTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def test_includes_recent_team_notes_labelled_untrusted(self):
        item = knowledge.add(self.root, 'The payments API rejects floats.', 'domain', True)
        sharing.apply(self.root, sharing.preview(self.root, item, author='sam'))
        result = core.recap(self.root)
        self.assertEqual(result['team'][0]['author'], 'sam')
        self.assertIn('untrusted', result['markdown'])
        self.assertIn('sam: The payments API rejects floats.', result['markdown'])
