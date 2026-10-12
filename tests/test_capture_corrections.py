import json
import subprocess
import sys
from test_ws import Base, KIT
from ws import core


class CorrectionCaptureTests(Base):
    def setUp(self):
        super().setUp()
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect preparation.')
        self.path = self.root / 'correction.jsonl'
        self.path.write_bytes((KIT / 'tests/fixtures/rollout-correction-turn.jsonl').read_bytes())

    def test_real_correction_turn_without_tools_is_memory(self):
        self.assertTrue(core.capture_decisions(self.root, str(self.path), 'codex'))
        brief = core.brief(self.root)
        for value in ('lane-8217', '8fa857d2b34257a7088af39d25b5c29d', 'Never retry preparation'):
            self.assertIn(value, brief)
        self.assertFalse(core.capture_decisions(self.root, str(self.path), 'codex'))
        self.assertLess(len(brief.split()), 200)

    def test_checkpoint_keeps_captures_when_explicit_handoff_is_replaced(self):
        with self.path.open('a') as stream:
            stream.write(json.dumps({'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'read'}}) + '\n')
        core.capture_decisions(self.root, str(self.path), 'codex')
        captured = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Review the latest manifest.', notes={'Handoff': 'Decision: preserve rows [2,4].'})
        handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertIn('Decision: preserve rows [2,4].', handoff)
        self.assertIn(captured[captured.index('<!-- ws:captured:'):].strip(), handoff)
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Review.', notes={'Handoff': handoff})
        self.assertEqual(core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff'].count('### Captured'), 1)

    def test_session_end_hook_captures_the_real_correction(self):
        for client in ('codex', 'claude'):
            with self.subTest(client=client):
                hooks = core.memory_hooks(self.root, client)['hooks']
                self.assertIn('SessionEnd', hooks)
                if client == 'claude':
                    from ws.transcripts import records
                    self.path.write_text('\n'.join(json.dumps(r) for r in records(self.path.read_text().splitlines(), 'codex')))
                result = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'nudge', '--hook', '--client', client],
                    cwd=self.root, input=json.dumps({'hook_event_name': 'SessionEnd', 'transcript_path': str(self.path)}),
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('lane-8217', core.brief(self.root))

    def test_correction_only_capture_still_requires_local_claim_and_privacy(self):
        entries = [{'type': 'user', 'message': {'content': 'Only secret-lane #private'}},
                   {'type': 'assistant', 'message': {'content': 'Understood.'}}]
        self.path.write_text('\n'.join(map(json.dumps, entries)))
        self.assertFalse(core.capture_decisions(self.root, str(self.path)))
        self.path.write_text(json.dumps({'type': 'user', 'message': {'content': 'Only amber. token=syntheticsecret123456'}}))
        self.assertTrue(core.capture_decisions(self.root, str(self.path)))
        self.assertNotIn('syntheticsecret123456', core.brief(self.root))
        (self.root / '.ws/claims/T-1.json').unlink()
        self.assertFalse(core.capture_decisions(self.root, str(self.path)))
