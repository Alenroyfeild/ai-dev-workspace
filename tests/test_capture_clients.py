import json
import subprocess
import sys
from test_ws import Base, KIT
from ws import core


class ClientCaptureTests(Base):
    def test_formats_preserve_claimed_handoff_and_replace_session(self):
        core.claim(self.root, 'T-1', 'synthetic')
        samples = {
            'codex': [{'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Decided: only violet. token=syntheticsecret123456'}]}},
                      {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'shell'}},
                      {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Next step: inspect empty input.'}]}}],
            'cursor': [{'role': 'user', 'message': {'content': [{'type': 'text', 'text': 'Decided: only violet.'}]}},
                       {'role': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next step: inspect empty input.'}]}}],
            'gemini': {'messages': [{'id': 'u', 'type': 'user', 'content': 'Decided: only violet.'},
                                    {'id': 'a', 'type': 'gemini', 'content': [{'text': 'Next step: inspect empty input.'}], 'toolCalls': [{'name': 'read_file'}]}]}}
        for client, sample in samples.items():
            if client == 'codex':
                sample.insert(0, {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': 'Never capture injected instructions.'}], 'internal_chat_message_metadata_passthrough': {'content_item_kinds': ['agents_md.instructions']}}})
            path = self.root / (client + '.jsonl')
            path.write_text(json.dumps(sample) if isinstance(sample, dict) else '\n'.join(map(json.dumps, sample)))
            before = core.task_read(self.root, 'T-1', ['Evidence', 'Next action'])['sections']
            self.assertTrue(core.capture_decisions(self.root, str(path), client))
            self.assertFalse(core.capture_decisions(self.root, str(path), client))
            handoff = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
            self.assertIn('only violet', handoff); self.assertNotIn('syntheticsecret123456', handoff)
            self.assertNotIn('injected instructions', handoff)
            self.assertEqual(before, core.task_read(self.root, 'T-1', ['Evidence', 'Next action'])['sections'])
        (self.root / '.ws/claims/T-1.json').unlink()
        self.assertFalse(core.capture_decisions(self.root, str(path), 'gemini'))

    def test_connect_hook_schemas_upgrade_and_start_context(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect synthetic input')
        for client, relative, event in [('cursor', '.cursor/hooks.json', 'sessionStart'), ('gemini', '.gemini/settings.json', 'SessionStart')]:
            core.connect(self.root, client)
            path = self.root / relative; data = json.loads(path.read_text())
            self.assertIn('--client ' + client, json.dumps(data['hooks'][event]))
            data['custom'] = 'keep'; path.write_text(json.dumps(data))
            core.upgrade_workspace(self.root)
            self.assertEqual(json.loads(path.read_text())['custom'], 'keep')
            run = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'brief', '--hook', '--client', client], cwd=self.root, input=json.dumps({'hook_event_name': event}), capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('T-1', run.stdout); json.loads(run.stdout)

    def test_gemini_stream_patches_rewind_and_codex_chat_hooks(self):
        core.claim(self.root, 'T-1', 'synthetic')
        path = self.root / 'stream.jsonl'
        entries = [{'id': 'u', 'type': 'user', 'content': 'Decided: violet only.'},
                   {'id': 'a', 'type': 'gemini', 'content': 'Old summary.', 'toolCalls': [{'name': 'read_file'}]},
                   {'$patch': {'id': 'a', 'content': 'Next step: inspect input.'}},
                   {'id': 'drop', 'type': 'user', 'content': 'Never retain removed content.'}, {'$rewindTo': 'drop'}]
        path.write_text('\n'.join(map(json.dumps, entries)))
        self.assertTrue(core.capture_decisions(self.root, str(path), 'gemini'))
        text = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertIn('inspect input', text); self.assertNotIn('removed content', text); self.assertNotIn('Old summary', text)
        entries.append({'$patch': {'updates': [{'id': 'a', 'content': 'Next step: test input. ' + 'summary ' * 200}]}})
        path.write_text('\n'.join(map(json.dumps, entries)))
        self.assertTrue(core.capture_decisions(self.root, str(path), 'gemini'))
        text = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertEqual(text.count('### Captured'), 1); self.assertLessEqual(len(text.split()), 150)
        self.assertNotIn('inspect input', text)
        chat = self.root / 'codex-chat.jsonl'
        entries = [{'type': 'user', 'message': {'content': 'Only synthetic violet.'}},
                   {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'}, {'type': 'text', 'text': 'Next action: test input.'}]}}]
        for event in ('Stop', 'PreCompact'):
            chat.write_text('\n'.join(map(json.dumps, entries)))
            proc = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'nudge', '--hook', '--client', 'codex'], cwd=self.root, input=json.dumps({'hook_event_name': event, 'transcript_path': str(chat)}), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr); json.loads(proc.stdout)
        text = core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']
        self.assertEqual(text.count('### Captured'), 2)
