"""Hand-edited records must honor private spans on the brief's read path."""
from test_ws import Base
from ws import core


class BriefPrivateReadTests(Base):
    def setUp(self):
        super().setUp()
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect public behavior.')

    def test_private_handoff_is_stripped_before_decisions_are_ranked(self):
        target = core.task_path(self.root, 'T-1')
        body = ('Decision: retain the public setting.\n<private>\n'
                'Decision: HIDDEN_HANDOFF_741 use private route.\n</private>')
        target.write_text(core.set_section(target.read_text(), 'Handoff', body))
        before = target.read_bytes()
        brief, summary = core.brief_and_summary(self.root)
        self.assertNotIn('HIDDEN_HANDOFF_741', brief + summary)
        self.assertNotIn('<private>', brief)
        self.assertIn('retain the public setting', brief)
        self.assertEqual(target.read_bytes(), before)

    def test_private_next_action_blockers_and_title_never_reach_brief_or_summary(self):
        target = core.task_path(self.root, 'T-1'); text = target.read_text()
        text = core.set_meta(text, {'title': 'Public <private>HIDDEN_TITLE_742</private>'})
        text = core.set_section(text, 'Next action', 'Inspect <private>HIDDEN_NEXT_743</private> public behavior.')
        text = core.set_section(text, 'Blockers', '<private>HIDDEN_BLOCKER_744</private> Waiting.')
        target.write_text(text); before = target.read_bytes()
        brief, summary = core.brief_and_summary(self.root)
        for canary in ('HIDDEN_TITLE_742', 'HIDDEN_NEXT_743', 'HIDDEN_BLOCKER_744'):
            self.assertNotIn(canary, brief + summary)
        self.assertIn('public behavior', brief)
        self.assertEqual(target.read_bytes(), before)

    def test_private_dead_end_is_removed_before_line_budget_drops_its_opener(self):
        target = core.task_path(self.root, 'T-1')
        for name in ('Do not redo', 'Failures'):
            with self.subTest(section=name):
                body = ('Public ' * 30 + '<private>\nHIDDEN_DEADEND_745\n</private>\nPublic retry rule.')
                target.write_text(core.set_section(target.read_text(), name, body))
                before = target.read_bytes()
                brief, summary = core.brief_and_summary(self.root)
                self.assertNotIn('HIDDEN_DEADEND_745', brief + summary)
                self.assertIn('Public retry rule', brief)
                self.assertEqual(target.read_bytes(), before)
