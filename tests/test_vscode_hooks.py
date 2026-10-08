import json
import subprocess
import sys
from test_ws import Base, KIT
from ws import core


class VscodeHookTests(Base):
    def transcript(self):
        return [
            {'type': 'session.start', 'data': {'version': 1, 'producer': 'copilot-agent'}},
            {'type': 'user.message', 'data': {'content': 'Decided: never rebuild cached receipts. token=syntheticsecret123456', 'attachments': ['Never capture attachments.']}},
            {'type': 'tool.execution_start', 'data': {'toolName': 'read_file', 'arguments': 'Never capture tool arguments.'}},
            {'type': 'tool.execution_complete', 'data': {'result': {'content': 'Never capture tool output.'}}},
            {'type': 'assistant.message', 'data': {'content': 'Next action: use the safe exporter.', 'reasoningText': 'Never capture reasoning.', 'toolRequests': []}},
        ]

    def test_vscode_transcript_capture_is_bounded_idempotent_and_owned(self):
        core.claim(self.root, 'T-1', 'synthetic')
        path = self.root / 'local.jsonl'; entries = self.transcript(); path.write_text('\n'.join(map(json.dumps, entries)))
        before = core.task_read(self.root, 'T-1', ['Evidence', 'Next action'])['sections']
        self.assertTrue(core.capture_decisions(self.root, str(path), 'vscode'))
        self.assertFalse(core.capture_decisions(self.root, str(path), 'vscode'))
        handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertIn('never rebuild', handoff); self.assertIn('safe exporter', handoff)
        for bad in ('syntheticsecret123456', 'attachments', 'tool arguments', 'tool output', 'reasoning'): self.assertNotIn(bad, handoff)
        entries[-1]['data']['content'] = 'Next action: finish validation. ' + 'word ' * 200
        path.write_text('\n'.join(map(json.dumps, entries)))
        self.assertTrue(core.capture_decisions(self.root, str(path), 'vscode'))
        handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertEqual(handoff.count('### Captured'), 1); self.assertNotIn('safe exporter', handoff)
        self.assertLess(len(handoff.split()), 150)
        self.assertEqual(before, core.task_read(self.root, 'T-1', ['Evidence', 'Next action'])['sections'])
        for version in (2, True, '1'):
            entries[0]['data']['version'] = version; path.write_text('\n'.join(map(json.dumps, entries)))
            self.assertFalse(core.capture_decisions(self.root, str(path), 'vscode'))
        entries[0]['data']['version'] = 1; entries[2]['data'] = None; entries[-1]['data']['toolRequests'] = [None, {'name': 1}]
        path.write_text('\n'.join(map(json.dumps, entries)))
        self.assertFalse(core.capture_decisions(self.root, str(path), 'vscode'))
        entries = self.transcript(); path.write_text('\n'.join(map(json.dumps, entries)))
        (self.root / '.ws/claims/T-1.json').unlink()
        self.assertFalse(core.capture_decisions(self.root, str(path), 'vscode'))

    def test_vscode_connect_upgrade_and_cli_hooks_keep_user_commands(self):
        core.claim(self.root, 'T-1', 'synthetic'); core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect cached receipts.')
        core.connect(self.root, 'vscode')
        path = self.root / '.github/hooks/ai-dev-workspace.json'; data = json.loads(path.read_text())
        self.assertEqual(set(data['hooks']), {'SessionStart', 'Stop', 'PreCompact'})
        user = {'type': 'command', 'command': 'echo user hook'}; data['hooks']['Stop'].append(user)
        data['custom'] = 'keep'; path.write_text(json.dumps(data))
        core.upgrade_workspace(self.root)
        self.assertEqual(json.loads(path.read_text())['hooks']['Stop'][-1], user)
        self.assertEqual(json.loads(path.read_text())['custom'], 'keep')
        self.assertEqual(core.upgrade_workspace(self.root)['changes'], [])
        transcript = self.root / 'local.jsonl'; transcript.write_text('\n'.join(map(json.dumps, self.transcript())))
        for command, event in (('brief', 'SessionStart'), ('nudge', 'PreCompact'), ('nudge', 'Stop')):
            run = subprocess.run([sys.executable, str(KIT / 'bin/ws'), command, '--hook', '--client', 'vscode'], cwd=self.root,
                                 input=json.dumps({'hook_event_name': event, 'transcript_path': str(transcript)}), capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads(run.stdout)
            if event == 'SessionStart': self.assertIn('Inspect cached receipts', result['hookSpecificOutput']['additionalContext'])
            else: self.assertEqual(result, {})  # capture never blocks the agent
        self.assertIn('never rebuild', core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff'])
