import json
import subprocess
import sys
from unittest import mock
from test_ws import Base, KIT
from ws import core


class CaptureHealthTests(Base):
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
