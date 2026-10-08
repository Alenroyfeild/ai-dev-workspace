import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock
from test_ws import Base, KIT
from ws import core


class SessionClientTests(Base):
    def test_gemini_json_and_stream_only_search_current_conversation_text(self):
        directory = self.root / 'gemini'; directory.mkdir()
        (directory / 'legacy.json').write_text(json.dumps({'messages': [
            {'id': 'u', 'type': 'user', 'timestamp': '2026-10-07T12:00:00Z', 'content': 'Searchneedle legacy token=syntheticsecret123456'},
            {'id': 'a', 'type': 'gemini', 'content': [{'text': 'Searchneedle response'}], 'thoughts': ['secret-thought'], 'toolCalls': [{'result': 'private-output'}]}]}))
        stream = [{'id': 'u', 'type': 'user', 'content': 'Searchneedle obsolete'},
                  {'$patch': {'id': 'u', 'content': 'Searchneedle patched'}},
                  {'id': 'drop', 'type': 'user', 'content': 'Searchneedle discarded'}, {'$rewindTo': 'drop'}]
        (directory / 'stream.jsonl').write_text('\n'.join(map(json.dumps, stream)))
        hits = core.session_search('Searchneedle', {'gemini': directory})
        self.assertEqual(len(hits), 3)
        text = json.dumps(hits)
        self.assertIn('patched', text); self.assertNotIn('obsolete', text); self.assertNotIn('discarded', text)
        self.assertNotIn('syntheticsecret123456', text)
        self.assertEqual(core.session_search('private-output', {'gemini': directory}), [])
        self.assertEqual(core.session_search('secret-thought', {'gemini': directory}), [])
        self.assertTrue(all(set(h) == {'date', 'tool', 'session_file', 'snippet'} for h in hits))

    def test_cursor_jsonl_redaction_caps_and_bad_files(self):
        directory = self.root / 'cursor'; directory.mkdir()
        entries = [{'role': 'assistant', 'timestamp': '2026-10-08T00:00:00Z', 'message': {'content': [
            {'type': 'text', 'text': 'Searchneedle token=syntheticsecret123456 ' + 'x' * 1000},
            {'type': 'tool_result', 'content': 'private-output'}]}}]
        (directory / 'conversation.jsonl').write_text('invalid json\n' + '\n'.join(map(json.dumps, entries * 25)))
        (directory / 'malformed.jsonl').write_text(json.dumps({'role': 'assistant', 'message': []}))
        huge = directory / 'huge.jsonl'
        with huge.open('wb') as f: f.truncate(50 * 1024 * 1024 + 1)
        (directory / 'link.jsonl').symlink_to(directory / 'conversation.jsonl')
        hits = core.session_search('Searchneedle', {'cursor': directory})
        self.assertEqual(len(hits), 20)
        self.assertTrue(all(h['date'] == '2026-10-08' and len(h['snippet']) <= 252 for h in hits))
        self.assertNotIn('syntheticsecret123456', json.dumps(hits))
        self.assertEqual(core.session_search('private-output', {'cursor': directory}), [])

    def test_cli_finds_default_client_folders_in_isolated_home(self):
        home = Path(self.tmp.name) / 'home'; cursor = home / '.cursor/projects/fixture/agent-transcripts'; gemini = home / '.gemini/tmp/fixture/chats'
        cursor.mkdir(parents=True); gemini.mkdir(parents=True)
        (cursor / 'chat.txt').write_text(json.dumps({'role': 'user', 'message': {'content': 'Searchneedle Cursor fixture'}}))
        (gemini / 'session.json').write_text(json.dumps({'messages': [{'type': 'user', 'content': 'Searchneedle Gemini fixture'}]}))
        run = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'sessions', 'search', 'Searchneedle'], cwd=self.root,
                             env={**os.environ, 'HOME': str(home), 'USERPROFILE': str(home), 'CODEX_HOME': str(home / '.codex')}, text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual({h['tool'] for h in json.loads(run.stdout)}, {'cursor', 'gemini'})
