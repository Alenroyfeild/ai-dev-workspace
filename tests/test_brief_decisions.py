import json
from test_ws import Base, KIT
from ws import core


class BriefDecisionTests(Base):
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
