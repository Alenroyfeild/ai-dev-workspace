import json

from test_ws import Base
from testutil import run_ws
from ws import core


class VerbatimHandoffTests(Base):
    def setUp(self):
        super().setUp()
        core.claim(self.root, 'T-1', 'fixture')

    def start_context(self, client):
        result = run_ws('--workspace-root', self.root, 'brief', '--hook', '--client', client,
                        input=json.dumps({'hook_event_name': 'SessionStart', 'source': 'startup'}))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['hookSpecificOutput']['additionalContext']

    def test_session_start_preserves_saved_markdown(self):
        action = 'Run the focused check.\n  Verify src/router.py first.'
        handoff = ('### Decisions\n- Keep the *existing* router.\n  Preserve its return shape.\n\n'
                   '### Files touched\n- src/router.py\n- tests/test_router.py')
        dead_ends = '- Skip the global retry.\n  It repeats the failing request.'
        core.checkpoint(self.root, 'T-1', 'in_progress', action,
                        notes={'Handoff': handoff, 'Do not redo': dead_ends})
        path = core.task_path(self.root, 'T-1')
        before = path.read_bytes()
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                brief = self.start_context(client)
                self.assertIn('Status: in_progress', brief)
                self.assertIn('Next action:\n' + action, brief)
                self.assertIn('Explicit Handoff (saved task record):\n' + handoff, brief)
                self.assertIn('Do not redo:\n' + dead_ends, brief)
        self.assertEqual(path.read_bytes(), before)

    def test_legacy_handoff_preserves_order_and_filters_private_text(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect input.')
        path = core.task_path(self.root, 'T-1')
        explicit = 'Decision: keep the first setting.\nDecision: keep the second setting.'
        path.write_text(core.set_section(path.read_text(), 'Handoff',
                                         explicit + '\n<private>\nhidden handoff canary\n</private>'),
                        encoding='utf-8')
        brief = core.brief(self.root)
        self.assertIn(explicit, brief)
        self.assertNotIn('hidden handoff canary', brief)

    def test_long_handoff_keeps_whole_lines_and_points_to_record(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect input.',
                        notes={'Handoff': 'old material ' * 250 + '\nDecision: preserve the recent correction.'})
        brief = core.brief(self.root)
        self.assertIn('Decision: preserve the recent correction.', brief)
        self.assertIn('[truncated: see task record]', brief)
        self.assertNotIn('old material', brief)
        self.assertLess(len(brief.split()), 200)

    def test_oversized_legacy_paragraph_has_a_labelled_preview(self):
        paragraph = ' '.join(f'legacy{i}' for i in range(300))
        for decision in ('', ' Decision: keep the router.'):
            with self.subTest(decision=decision):
                core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect input.',
                                notes={'Handoff': paragraph + '.' + decision})
                brief = core.brief(self.root)
                self.assertIn('legacy0', brief)
                self.assertIn('legacy299', brief)
                if decision:
                    self.assertIn(decision.strip(), brief)
                self.assertIn('[truncated: see task record]', brief)
                self.assertLess(len(brief.split()), 200)

    def test_oversized_legacy_line_does_not_hide_fitting_lines(self):
        paragraph = ' '.join(f'legacy{i}' for i in range(300))
        first, last = 'First saved line fits.', 'Last saved line fits.'
        for tail in ('', '\n' + last):
            with self.subTest(tail=tail):
                core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect input.',
                                notes={'Handoff': first + '\n' + paragraph + tail})
                brief = core.brief(self.root)
                self.assertIn(first, brief)
                if tail:
                    self.assertLess(brief.index(first), brief.index(last))
                self.assertIn('[truncated: see task record]', brief)
                self.assertLess(len(brief.split()), 200)

    def test_unclosed_private_marker_hides_saved_action_without_calling_it_missing(self):
        action = 'Saved next step after a private span.'
        canary = 'private canary must stay hidden'
        core.checkpoint(self.root, 'T-1', 'in_progress', action)
        path = core.task_path(self.root, 'T-1')
        path.write_text(core.set_section(path.read_text(encoding='utf-8'), 'Objective',
                                         'Overview <private>' + canary), encoding='utf-8')
        before = path.read_bytes()
        brief, summary = core.brief_and_summary(self.root)
        self.assertIn('Next action: Saved text hidden by private markers.', brief)
        self.assertNotIn('Not saved yet', brief)
        self.assertNotIn('No saved memory yet', summary)
        for value in (action, canary):
            self.assertNotIn(value, brief + summary)
        self.assertEqual(path.read_bytes(), before)
