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

    def hook(self, command, payload, client='codex'):
        result = subprocess.run([sys.executable, str(KIT / 'bin/ws'), '--workspace-root', str(self.root), command,
                                 '--hook', '--client', client], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def stale(self):
        self.path.write_text(json.dumps({'type': 'user', 'message': {'content':
            'We decided to use lane-old; only approval receipt old-receipt is valid. Never send secrets.'}}))
        core.capture_decisions(self.root, str(self.path), 'codex')

    def correction(self):
        return json.loads((KIT / 'tests/fixtures/rollout-correction-turn.jsonl').read_text().splitlines()[0])['payload']['content'][0]['text']

    def test_prompt_hook_saves_correction_before_transcript_flush_and_stale_reads(self):
        self.stale()
        self.hook('paste', {'prompt': self.correction(), 'transcript_path': str(self.path), 'session_id': 'synthetic'})
        for event in ('Stop', 'SessionEnd'):
            self.hook('nudge', {'hook_event_name': event, 'transcript_path': str(self.path)})
            text = core.brief(self.root)
            self.assertIn('lane-8217', text)
            self.assertIn('8fa857d2b34257a7088af39d25b5c29d', text)
            self.assertNotIn('lane-old', text); self.assertNotIn('old-receipt', text)
            self.assertIn('Never send secrets', text)

    def test_transcript_correction_supersedes_old_values_and_stale_checkpoint_is_labelled(self):
        self.stale()
        with self.path.open('a') as stream:
            stream.write('\n' + json.dumps({'type': 'user', 'message': {'content': self.correction()}}))
        core.capture_decisions(self.root, str(self.path), 'codex')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Use lane-old with old-receipt.')
        text = core.brief(self.root)
        self.assertIn('lane-8217', text)
        old_lines = [line for line in text.splitlines() if 'lane-old' in line or 'old-receipt' in line]
        self.assertTrue(all('superseded' in line for line in old_lines), text)

    def test_checkpoint_keeps_only_newest_capture_and_drops_conflicting_constraints(self):
        self.stale()
        other = self.root / 'newer.jsonl'; other.write_bytes((KIT / 'tests/fixtures/rollout-correction-turn.jsonl').read_bytes())
        core.capture_decisions(self.root, str(other), 'codex')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Review.', notes={'Handoff': 'Decision: use lane-final.'})
        handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertLessEqual(handoff.count('### Captured'), 1)
        self.assertNotIn('lane-old', handoff); self.assertNotIn('lane-8217', handoff)
        self.hook('nudge', {'hook_event_name': 'Stop', 'transcript_path': str(other)})
        self.assertNotIn('lane-8217', core.brief(self.root))

    def test_prompt_capture_keeps_privacy_disabled_and_foreign_claim_rules(self):
        for client in ('claude', 'codex', 'cursor', 'gemini'):
            self.hook('paste', {'prompt': 'Correction: only amber. <private>only hidden</private> token=syntheticsecret123456'}, client)
            text = core.brief(self.root)
            self.assertIn('amber', text); self.assertNotIn('hidden', text); self.assertNotIn('syntheticsecret123456', text)
        before = core.task_path(self.root, 'T-1').read_bytes()
        self.hook('paste', {'prompt': 'Only leak #private'})
        self.assertEqual(before, core.task_path(self.root, 'T-1').read_bytes())
        cfg = core.config(self.root); cfg['capture'] = False
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        self.hook('paste', {'prompt': 'Only disabled.'})
        self.assertEqual(before, core.task_path(self.root, 'T-1').read_bytes())
        cfg['capture'] = True; (self.root / 'workspace.json').write_text(json.dumps(cfg))
        (self.root / '.ws/claims/T-1.json').unlink()
        self.hook('paste', {'prompt': 'Only foreign.'})
        self.assertEqual(before, core.task_path(self.root, 'T-1').read_bytes())

    def test_prompt_does_not_turn_phase_instructions_into_persistent_rules(self):
        self.hook('paste', {'prompt': 'Only lane-new is valid. Do not fix preparation or edit code; report what happened and stop.'})
        text = core.brief(self.root)
        self.assertIn('lane-new', text); self.assertNotIn('edit code', text)

    def test_tool_only_transcript_entry_still_allows_a_summary(self):
        self.path.write_text('\n'.join(map(json.dumps, [
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'read'}},
            {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'Next step: inspect the result.'}]}}])))
        self.assertTrue(core.capture_decisions(self.root, str(self.path), 'codex'))
        self.assertIn('inspect the result', core.brief(self.root))

    def test_correction_replaces_its_subject_and_retains_other_rules(self):
        self.hook('paste', {'prompt': 'We decided: language is Python. Never send secrets.'})
        self.hook('paste', {'prompt': 'Correction: language is Go.'})
        text = core.brief(self.root)
        self.assertIn('language is Go', text); self.assertNotIn('Python', text)
        self.assertIn('Never send secrets', text)

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
