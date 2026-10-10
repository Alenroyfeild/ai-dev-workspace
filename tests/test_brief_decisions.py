import json
import contextlib
import io
import os
from unittest import mock
from test_ws import Base, KIT
from ws import core, cli


class BriefDecisionTests(Base):
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
