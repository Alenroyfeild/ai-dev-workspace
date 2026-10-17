import os
import subprocess
import sys
import unittest
from pathlib import Path
import test_sharing
from ws import core, knowledge, sharing, team

CLI = Path(__file__).resolve().parents[1] / 'bin/ws'


class PromptEofTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp

    def ws(self, *args):  # stdin closed, like an assistant's shell
        return subprocess.run([sys.executable, str(CLI), '--workspace-root', str(self.root), *args], stdin=subprocess.DEVNULL,
                              text=True, capture_output=True, env=dict(os.environ))

    def sources(self):
        return [p for p in (self.root / 'vault/Knowledge').glob('*.md') if not p.name.endswith('.index.md') and p.name != 'INDEX.md']

    def test_closed_stdin_at_share_prompt_is_no_confirmation_not_traceback(self):
        result = self.ws('know', 'add', 'Queues stay bounded.', '--team')
        self.assertNotEqual(result.returncode, 0); self.assertNotIn('Traceback', result.stderr)
        self.assertIn('No confirmation', result.stderr)
        self.assertFalse(list((self.clone / 'entries').glob('*')))  # nothing copied to the team clone

    def test_closed_stdin_at_sync_prompt_publishes_nothing(self):
        item = knowledge.add(self.root, 'Receipt checksum is CEDAR41.', 'repo', True)
        sharing.apply(self.root, sharing.preview(self.root, item))
        result = self.ws('sync')
        self.assertNotEqual(result.returncode, 0); self.assertNotIn('Traceback', result.stderr)
        self.assertEqual('', team._git(self.remote, 'for-each-ref'))

    def test_rerun_after_declined_team_add_reuses_the_record(self):
        for _ in range(2): self.ws('know', 'add', 'Queues stay bounded.', '--category', 'domain', '--team')
        self.assertEqual(1, len(self.sources()))

    def test_rerun_after_declined_remember_or_lesson_reuses_the_record(self):
        for directory, args in (('Decisions', ('remember', 'A bounded decision remains portable.', '--team')),
                                ('Lessons', ('lesson', 'add', 'A timeout happened; always bound retries.', '--team'))):
            for _ in range(2): self.ws(*args)
            records = [p for p in (self.root / 'vault' / directory).glob('*.md') if p.name != 'INDEX.md' and not p.name.endswith('.index.md')]
            self.assertEqual(1, len(records), directory)

    def test_same_text_in_another_scope_or_category_is_a_new_record(self):
        a = knowledge.add(self.root, 'Queues stay bounded.', 'domain', True)
        self.assertEqual(a, knowledge.add(self.root, 'Queues stay bounded.', 'domain', True))
        self.assertNotEqual(a, knowledge.add(self.root, 'Queues stay bounded.', 'domain'))
        self.assertNotEqual(a, knowledge.add(self.root, 'Queues stay bounded.', 'repo', True))


if __name__ == '__main__':
    unittest.main()
