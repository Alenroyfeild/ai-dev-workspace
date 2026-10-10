import json
import contextlib
import io
import os
from unittest import mock
from test_ws import Base, KIT
from ws import core, cli


class BriefDecisionTests(Base):
    def test_marked_explicit_decision_precedes_next_action_without_modal_words(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect the implementation.',
                        notes={'Handoff': 'Planning background. ' * 80 + '\nDecision: minimal dependencies.'})
        brief = core.brief(self.root)
        self.assertIn('Explicit Handoff (saved task record): Decision: minimal dependencies.', brief)
        self.assertLess(brief.index('Decision: minimal dependencies'), brief.index('Next action:'))

    def test_astra_full_checkpoint_keeps_all_captured_decisions(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress',
                        'Implement the empty email case in the login entry point, then add focused tests for whitespace and malformed input. Run the authentication suite and check the signup and recovery callers before preparing the patch for review. Do not change normalize().',
                        notes={'Handoff': 'Use the existing login helper and preserve the public result shape. Keep tests focused on the rejected input cases. We have already ruled out a database or dependency change. The code review should remain limited to authentication and its tests.',
                               'Blockers': 'Waiting for a review of the new error message text before release. Local unit tests can proceed now; no schema migration or new service is required.'})
        prompt = json.loads((KIT / 'bench/scenarios/decisions.json').read_text())['session1']
        path = self.root / 'full.jsonl'
        path.write_text('\n'.join(map(json.dumps, [
            {'type': 'user', 'message': {'content': prompt}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                {'type': 'text', 'text': 'Next step: implement the decisions in login.py.'}]}}])))
        self.assertTrue(core.capture_decisions(self.root, str(path)))
        before = core.task_path(self.root, 'T-1').read_bytes()
        brief = core.brief(self.root)
        for decision in ('missing_email', 'invalid_email', 'recovery.py', 'login_rejected'):
            self.assertIn(decision, brief)
        self.assertIn('[truncated: see task record]', brief)
        self.assertLess(len(brief.split()), 200)
        self.assertEqual(core.task_path(self.root, 'T-1').read_bytes(), before)

    def test_rollout_correction_survives_full_checkpoint_and_native_writeback(self):
        core.task_new(self.root, 'R-1', 'Finish the interrupted rollout manifest while retaining every previously verified behavior and the approved receipt')
        core.claim(self.root, 'R-1', 'synthetic')
        core.connect(self.root, 'cursor')
        core.checkpoint(self.root, 'R-1', 'in_progress', 'Review the manifest and visible tests. ' * 12,
                        notes={'Handoff': ('Earlier investigation background. ' * 70) +
                                         'Explicit decision: preserve rows [2,4]; do not add a dependency.',
                               'Blockers': 'Waiting for a review of the manifest. ' * 12})
        path = self.root / 'rollout.jsonl'
        correction = json.loads((KIT / 'bench/scenarios/rollout.json').read_text())['correct'].format(
            lane='lane-new', receipt='new-receipt') + ' Do not write notes manually; stop now.'
        path.write_text('\n'.join(map(json.dumps, [
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}}
            for text in ('We decided to use lane-old; only original receipt old-receipt is valid.',
                         correction)
        ] + [{'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'Read'}},
             {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Next step: finish release.json with lane-new and new-receipt.'}]}}])))
        self.assertTrue(core.capture_decisions(self.root, str(path), 'codex'))
        before = core.task_path(self.root, 'R-1').read_bytes()
        core.refresh_native(self.root)
        brief = core.brief(self.root)
        for text in [brief] + [(self.root / name).read_text() for name in core.NATIVE_FILES]:
            for fact in ('lane-new', 'new-receipt', 'Never retry preparation', 'do not add a dependency'):
                self.assertIn(fact, text)
        self.assertLess(brief.index('lane-new'), brief.index('Explicit Handoff'))
        self.assertIn('[truncated: see task record]', brief)
        self.assertLess(len(brief.split()), 200)
        self.assertEqual(core.task_path(self.root, 'R-1').read_bytes(), before)

    def test_recorded_explicit_handoff_reaches_brief_and_native_rules(self):
        fixture = json.loads((KIT / 'tests/fixtures/explicit-handoff.json').read_text())
        core.task_new(self.root, 'APP-1', 'Reject empty email')
        core.claim(self.root, 'APP-1', 'synthetic')
        core.connect(self.root, 'cursor')
        with mock.patch.dict(os.environ, {'WS_ROOT': str(self.root)}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(fixture['argv']), fixture['exit'])
        for text in [core.brief(self.root)] + [(self.root / name).read_text() for name in core.NATIVE_FILES]:
            self.assertIn('Return False for empty email; do not add a dependency.', text)
            self.assertIn('Explicit Handoff (saved task record)', text)
        self.assertLess(len(core.brief(self.root).split()), 200)

    def test_explicit_notes_and_automatic_capture_have_separate_sources(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect input.', notes={'Handoff': 'Keep the explicit no-dependency decision.'})
        transcript = self.root / 'capture.jsonl'
        transcript.write_text('\n'.join(map(json.dumps, [
            {'type': 'user', 'message': {'content': 'Decided: use violet only.'}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next step: inspect input.'}]}}])))
        core.capture_decisions(self.root, str(transcript))
        brief = core.brief(self.root)
        self.assertIn('Explicit Handoff (saved task record): Keep the explicit', brief)
        self.assertIn('Captured last session (unverified):', brief)
        self.assertNotIn('violet', next(line for line in brief.splitlines() if line.startswith('Explicit Handoff')))
        before = core.task_path(self.root, 'T-1').read_bytes()
        core.brief(self.root); self.assertEqual(core.task_path(self.root, 'T-1').read_bytes(), before)

    def test_long_explicit_handoff_keeps_latest_words_and_labels_truncation(self):
        core.claim(self.root, 'T-1', 'synthetic')
        note = ('Old context. ' * 200) + 'Latest correction: do not add a dependency. api_key=synthetic123456789abcdef'
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect input.', notes={'Handoff': note})
        brief = core.brief(self.root)
        self.assertIn('Latest correction: do not add a dependency.', brief)
        self.assertIn('[truncated', brief)
        self.assertNotIn('synthetic123456789abcdef', brief)
        self.assertLess(len(brief.split()), 200)

    def test_numbered_decisions_from_the_benchmark_prompt_all_reach_the_brief(self):
        # Regression: the brief showed none of the four decisions (session instructions used the budget,
        # and the one long decision sentence was clipped in the middle).
        prompt = json.loads((KIT / 'bench/scenarios/decisions.json').read_text())['session1']
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Investigate.')
        path = self.root / 'session.jsonl'
        path.write_text('\n'.join(map(json.dumps, [
            {'type': 'user', 'message': {'content': prompt}},
            {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                {'type': 'text', 'text': 'Next step: implement the decisions in login.py.'}]}}])))
        self.assertTrue(core.capture_decisions(self.root, str(path)))
        brief = core.brief(self.root)
        for decision in ('missing_email', 'invalid_email', 'recovery.py', 'login_rejected'):
            self.assertIn(decision, brief)
        self.assertNotIn('later session', brief)  # session mechanics are not decisions
        self.assertLess(len(brief.split()), 200)
