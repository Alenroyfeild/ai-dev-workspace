import contextlib
import io
import json
import unittest
from unittest import mock
import test_sharing
from ws import cli, core, sharing


class RunbookTests(unittest.TestCase):
    setUp = test_sharing.SharingTests.setUp
    def finished(self):
        path = core.task_path(self.root, 'T1'); text = path.read_text()
        for name, body in [('Steps', 'Read the queue; test bounded retries.'), ('Failures', 'Unbounded retry loop deadlocked.'),
                           ('Outcome', 'Bounded retries pass all checks.'), ('Handoff', 'Decision: Use bounded queues because retries must terminate.\n<private>private note\nDecision: hidden private decision\n</private>\n<!-- ws:captured:x -->\n### Captured today\nHidden capture\n<!-- /ws:captured -->')]:
            text = core.set_section(text, name, body)
        path.write_text(core.set_meta(text, {'status': 'done'})); return path

    def test_runbook_requires_finished_task_and_uses_exact_same_gate(self):
        with self.assertRaises(core.WsError): sharing.preview(self.root, 'task:T1', as_format='runbook')
        source = self.finished(); before = source.read_bytes()
        with mock.patch('builtins.input', return_value='n') as confirm, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'share', 'T1', '--as', 'runbook']), 0)
        self.assertEqual(confirm.call_count, 1); self.assertFalse((self.clone / 'entries').exists())
        plan = sharing.preview(self.root, 'task:T1', as_format='runbook')
        for wanted in ('category: runbook', 'Read the queue', 'Unbounded retry loop', 'because retries must terminate', 'Bounded retries pass'):
            self.assertIn(wanted, plan['content'])
        for unwanted in ('Hidden capture', 'private note', 'hidden private decision', 'claim_token:', '## Next action', '## Handoff'):
            self.assertNotIn(unwanted, plan['content'])
        sharing.apply(self.root, plan); self.assertEqual(before, source.read_bytes())
        self.assertTrue(sharing.preview(self.root, 'task:T1', as_format='runbook')['unchanged'])

    def test_runbook_and_normal_task_have_separate_receipts_and_stale_preview_refuses(self):
        path = self.finished(); task = sharing.preview(self.root, 'task:T1'); sharing.apply(self.root, task)
        runbook = sharing.preview(self.root, 'task:T1', as_format='runbook'); self.assertNotEqual(task['entry'], runbook['entry'])
        sharing.apply(self.root, runbook)
        removal = sharing.preview(self.root, 'task:T1', unshare=True, as_format='runbook'); sharing.apply(self.root, removal)
        self.assertTrue((self.clone / task['destination']).exists())
        plan = sharing.preview(self.root, 'task:T1', as_format='runbook'); path.write_text(path.read_text()+'\nChanged.\n')
        with self.assertRaises(core.WsError): sharing.apply(self.root, plan)

    def test_checkpoint_sections_supply_steps_dead_ends_and_explicit_outcome(self):
        path = core.task_path(self.root, 'T1')
        core.checkpoint(self.root, 'T1', 'done', 'Review runbook.', notes={'Evidence': 'Read queue implementation.',
            'Checks': 'Bounded retries pass.', 'Failures': 'Unbounded retries failed.', 'Do not redo': 'Avoid infinite loops.',
            'Handoff': 'Decision: Use bounded queues.\nReason: Termination is required.\nOutcome: Stable receipts pass.'})
        plan = sharing.preview(self.root, 'task:T1', as_format='runbook')
        for wanted in ('Read queue', 'Bounded retries pass.', 'Avoid infinite loops.', 'Reason: Termination', 'Stable receipts pass.'):
            self.assertIn(wanted, plan['content'])
