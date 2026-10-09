import json
import subprocess
import sys
from unittest import mock
from test_ws import Base, KIT
from ws import core


class CaptureHealthTests(Base):
    def test_capture_and_health_share_one_lock(self):
        def capturing(*args):
            with self.assertRaises(core.WsError), core.lock(self.root): pass
            return 'captured'
        with mock.patch.object(core, '_capture_decisions', side_effect=capturing):
            self.assertTrue(core.capture_decisions(self.root, 'synthetic'))
        (self.root / '.ws/capture-health.json').write_bytes(b'\xff')
        self.assertEqual(core.capture_health(self.root)['reason'], 'unreadable_health')

    def hook(self, path):
        result = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'nudge', '--hook'],
            cwd=self.root, input=json.dumps({'hook_event_name': 'Stop', 'transcript_path': str(path)}),
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return core.doctor(self.root)['capture_health']

    def test_hook_reports_distinct_safe_outcomes(self):
        path = self.root / 'private-transcript.jsonl'
        path.write_text(json.dumps({'unsupported': 'private transcript text'}))
        health = self.hook(path)
        self.assertEqual(health['reason'], 'unsupported_transcript')
        core.claim(self.root, 'T-1', 'synthetic')
        core.task_new(self.root, 'T-2', 'Synthetic second', 'Synthetic')
        core.claim(self.root, 'T-2', 'synthetic')
        path.write_text(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next step: private transcript text.'}]}}))
        self.assertEqual(self.hook(path)['reason'], 'ambiguous_claims')
        core.release(self.root, 'T-2')
        health = self.hook(path)
        self.assertEqual(health['outcome'], 'captured')
        self.assertEqual(self.hook(path)['outcome'], 'unchanged')
        diagnostic = json.dumps(core.doctor(self.root)['capture_health'])
        self.assertNotIn('private transcript', diagnostic)
        self.assertNotIn(str(path), diagnostic)
        out = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'doctor', '--text'], cwd=self.root, capture_output=True, text=True)
        self.assertIn('Last capture:', out.stdout)
        self.assertIn('unchanged', out.stdout)

    def test_missing_transcript_and_idle_session(self):
        self.assertEqual(self.hook(self.root / 'missing')['reason'], 'unreadable_transcript')
        path = self.root / 'idle.jsonl'
        path.write_text(json.dumps({'type': 'user', 'message': {'content': 'Only synthetic.'}}))
        self.assertEqual(self.hook(path)['reason'], 'no_work_or_memory')
        with mock.patch('pathlib.Path.exists', side_effect=PermissionError('private details')):
            self.assertEqual(core.capture_health(self.root)['reason'], 'unreadable_health')

    def test_diagnostic_write_failure_preserves_capture_result(self):
        core.claim(self.root, 'T-1', 'synthetic')
        path = self.root / 'worked.jsonl'
        path.write_text(json.dumps({'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next step: validate cobalt.'}]}}))
        original = core.atomic_write
        def write(target, text):
            if target.name == 'capture-health.json': raise PermissionError('private details')
            return original(target, text)
        with mock.patch.object(core, 'atomic_write', side_effect=write):
            self.assertTrue(core.capture_decisions(self.root, str(path)))
            self.assertFalse(core.capture_decisions(self.root, str(path)))
        self.assertIn('validate cobalt', core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff'])
