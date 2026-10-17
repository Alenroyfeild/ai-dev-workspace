import json
import subprocess
import sys

from test_ws import Base, KIT
from ws import core


class PrNotesTests(Base):
    def test_lists_explicit_decisions_checks_and_open_items(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.remember(self.root, 'store totals in integer cents, never floats')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Open the PR.', notes={
            'Objective': 'Fix rounding in checkout totals.',
            'Acceptance criteria': '- Totals match the payments API to the cent.',
            'Checks': '- python3 -m unittest tests.test_totals',
            'Blockers': 'Waiting for the tax table from finance.',
            'Handoff': 'Decision: store totals in integer cents, never floats\nReason: the payments API rejects floats'})
        notes = core.pr_notes(self.root)
        md = notes['markdown']
        self.assertEqual((notes['task'], notes['decisions']), ('T-1', 1))
        for expected in ('**Goal:** Fix rounding in checkout totals.', '#### Decisions\n- store totals in integer cents, never floats',
                         '  - Why: the payments API rejects floats', '#### Acceptance criteria', 'tests.test_totals',
                         '#### Open items\nWaiting for the tax table', 'ai-dev-workspace'):
            self.assertIn(expected, md)

    def test_captured_guesses_placeholders_and_link_are_left_out(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={
            'Handoff': '<!-- ws:captured:2026-10-15 -->\nDecision: guessed by capture\n<!-- /ws:captured -->'})
        md = core.pr_notes(self.root, 'T-1', link=False)['markdown']
        self.assertNotIn('guessed by capture', md)
        self.assertNotIn('Open items', md)  # template "None yet." is not an open item
        self.assertNotIn('ai-dev-workspace', md)
        self.assertIn('No decisions or checks saved yet', md)

    def test_secrets_private_text_and_home_paths_are_redacted(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={
            'Checks': 'Ran /Users/alice/code/app/run.sh with token=ghp_' + 'a' * 36 + ' <private>internal host</private>'})
        md = core.pr_notes(self.root, 'T-1')['markdown']
        for leaked in ('/Users/alice', 'ghp_' + 'a' * 36, 'internal host'):
            self.assertNotIn(leaked, md)

    def test_without_a_task_it_says_how_to_pick_one(self):
        with self.assertRaisesRegex(core.WsError, 'ws pr-notes <ID>'):
            core.pr_notes(self.root)

    def test_cli_prints_markdown_and_json(self):
        core.remember(self.root, 'use Postgres', 'T-1')
        run = lambda *args: subprocess.run([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(self.root), 'pr-notes', 'T-1', *args],
                                           capture_output=True, text=True, check=True).stdout
        self.assertIn('- use Postgres', run('--no-link'))
        self.assertEqual(json.loads(run('--json'))['decisions'], 1)

    def test_wrapped_lines_continue_and_unterminated_captures_are_dropped(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'x', notes={'Handoff':
            'Decision: store totals in integer cents\n  because the payments API rejects floats\n'
            'Reason: rounding drift\n  showed up in refunds\n<!-- ws:captured:2026-10-16 -->\nDecision: captured guess'})
        md = core.pr_notes(self.root, 'T-1', link=False)['markdown']
        self.assertIn('- store totals in integer cents because the payments API rejects floats', md)
        self.assertIn('  - Why: rounding drift showed up in refunds', md)
        self.assertNotIn('captured guess', md)
