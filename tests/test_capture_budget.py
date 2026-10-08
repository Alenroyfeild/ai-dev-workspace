import json
from test_ws import Base
from ws import core


class CaptureBudgetTests(Base):
    def test_recent_correction_and_next_step_survive_both_caps(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Validate the amber lane',
                        notes={'Handoff': 'Verified human note.', 'Evidence': 'Verified evidence.'})
        before = core.task_read(self.root, 'T-1', ['Next action', 'Evidence'])['sections']
        path = self.root / 'budget.jsonl'
        entries = [
            {'type': 'user', 'message': {'content': 'Always ' + 'early-context ' * 110 + '. We must use the cobalt lane.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                {'type': 'text', 'text': 'background ' * 110 + '. Next step: validate cobalt.'}]}},
        ]
        path.write_text('\n'.join(map(json.dumps, entries)))
        self.assertTrue(core.capture_decisions(self.root, str(path)))
        handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertIn('must use the cobalt lane', handoff)
        self.assertIn('validate cobalt', handoff)
        self.assertLessEqual(len(handoff[handoff.index('### Captured'):].split()), 150)
        brief = core.brief(self.root)
        self.assertIn('must use the cobalt lane', brief)
        self.assertIn('validate cobalt', brief)
        self.assertIn('differs from saved checkpoint', brief)
        self.assertEqual(before, core.task_read(self.root, 'T-1', ['Next action', 'Evidence'])['sections'])
        self.assertTrue(handoff.startswith('Verified human note.'))
        self.assertFalse(core.capture_decisions(self.root, str(path)))

    def test_newest_next_step_within_summary_wins(self):
        core.claim(self.root, 'T-1', 'synthetic')
        path = self.root / 'steps.jsonl'
        text = 'Next step: ' + 'old ' * 60 + '. Next action: validate cobalt.'
        path.write_text(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': text}]}}))
        core.capture_decisions(self.root, str(path))
        self.assertIn('validate cobalt', core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff'])

    def test_late_cue_in_one_sentence_and_same_plan_are_not_lost(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Validate cobalt.')
        path = self.root / 'late-cue.jsonl'
        path.write_text('\n'.join(map(json.dumps, [
            {'type': 'user', 'message': {'content': 'Always ' + 'old-context ' * 110 + 'but we must use cobalt.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                {'type': 'text', 'text': 'Next step: Validate cobalt.'}]}}
        ])))
        core.capture_decisions(self.root, str(path))
        brief = core.brief(self.root)
        self.assertIn('must use cobalt', brief)
        self.assertNotIn('differs from saved checkpoint', brief)

    def test_last_next_action_clause_without_colon(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Validate amber.')
        path = self.root / 'clauses.jsonl'
        path.write_text(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text':
                'The next step is ' + 'old ' * 60 + '; the next action is validate cobalt.'}]}}))
        core.capture_decisions(self.root, str(path))
        brief = core.brief(self.root)
        self.assertIn('validate cobalt', brief)
        self.assertIn('differs from saved checkpoint', brief)
