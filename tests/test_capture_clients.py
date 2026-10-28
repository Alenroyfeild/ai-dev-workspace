import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock
from test_ws import Base, KIT
from ws import core
from testutil import run_ws


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
            run = run_ws('brief', '--hook', '--client', client, cwd=self.root, input=json.dumps({'hook_event_name': event}))
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


class GeminiConnectTests(Base):
    def test_gemini_settings_get_server_and_hooks_and_keep_user_keys(self):
        path = self.root / '.gemini/settings.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'theme': 'user', 'hooks': {'AfterAgent': [{'hooks': [{'type': 'command', 'command': 'user-hook'}]}]}}))
        for _ in range(2):  # idempotent
            core.connect(self.root, 'gemini')
        data = json.loads(path.read_text())
        self.assertEqual(data['theme'], 'user')
        self.assertIn('ai-dev-workspace', data['mcpServers'])
        after = [h['command'] for g in data['hooks']['AfterAgent'] for h in g['hooks']]
        self.assertIn('user-hook', after)
        self.assertEqual(sum('nudge --hook --client gemini' in c for c in after), 1)
        self.assertTrue(core.client_connected(self.root, 'gemini'))


class CodexCatchupTests(Base):
    SID = '11111111-1111-4111-8111-111111111111'
    NEW = '22222222-2222-4222-8222-222222222222'

    def setUp(self):
        super().setUp()
        self.home = (self.root.parent / 'codex').resolve()
        patch = mock.patch.dict(os.environ, CODEX_HOME=str(self.home))
        patch.start(); self.addCleanup(patch.stop)
        self.sessions = self.home / 'sessions/2026/10/27'
        self.sessions.mkdir(parents=True)
        core.claim(self.root, 'T-1', 'local')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect fixture.', notes={'Handoff': 'Decision: preserve rows.'})
        self.path = self.transcript(self.SID, '2026-10-27T10:00:00Z', 'Decided: only amber.')
        self.start(self.SID)
        self.stop(self.path, self.SID)

    def transcript(self, sid, stamp, text):
        path = self.sessions / ('rollout-' + sid + '.jsonl')
        entries = [{'type': 'session_meta', 'payload': {'id': sid, 'timestamp': stamp}},
                   {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}},
                   {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'read_file'}},
                   {'type': 'response_item', 'payload': {'type': 'message', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': 'Next step: inspect fixture.'}]}}]
        path.write_text('\n'.join(map(json.dumps, entries)) + '\n', encoding='utf-8')
        return path

    def append(self, path=None, text='Correction: decided to use cobalt; only replacement receipt opaque-fixture is valid.'):
        with (path or self.path).open('a', encoding='utf-8') as out:
            out.write(json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}}) + '\n')

    def start(self, sid=NEW, client='codex'):
        result = run_ws('brief', '--hook', '--client', client, cwd=self.root,
                        input=json.dumps({'hook_event_name': 'SessionStart', 'session_id': sid}))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def stop(self, path, sid):
        result = run_ws('nudge', '--hook', '--client', 'codex', cwd=self.root,
                        input=json.dumps({'hook_event_name': 'Stop', 'session_id': sid, 'transcript_path': str(path)}))
        self.assertEqual(result.returncode, 0, result.stderr)

    def handoff(self):
        return core.task_read(self.root, 'T-1', ['Handoff'])['sections']['Handoff']

    def cursor(self):
        return (self.root / '.ws/codex-capture/T-1.json').read_bytes()

    def test_resumed_correction_without_callback_reaches_next_brief_once(self):
        self.append()
        self.assertNotIn('cobalt', core.brief(self.root))  # Ordinary reads do not trigger capture.
        injected = json.loads(self.start())['hookSpecificOutput']['additionalContext']
        self.assertIn('cobalt', injected); self.assertIn('opaque-fixture', injected)
        self.assertLessEqual(len(injected.split()), 200)
        handoff = self.handoff()
        self.assertEqual(handoff.count('### Captured '), 1)
        self.assertEqual(handoff.count('opaque-fixture'), 1)
        self.assertIn('Decision: preserve rows.', handoff)
        self.assertEqual(core.task_read(self.root, 'T-1', ['Next action'])['sections']['Next action'], 'Inspect fixture.')
        cursor = json.loads(self.cursor())
        self.assertEqual(set(cursor), {'client', 'session_id', 'size', 'sha256', 'started'})
        self.assertEqual(cursor['started'], '2026-10-27T10:00:00+00:00')
        self.assertEqual(cursor['session_id'], self.SID)
        before = self.cursor()
        with mock.patch.object(core, '_capture_decisions', wraps=core._capture_decisions) as capture:
            self.start(); self.assertEqual(capture.call_count, 0)
        self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)

    def test_private_markers_and_secrets_remain_filtered(self):
        secret = 'sk-' + 'synthetic' * 6
        self.append(text='Decided: cobalt. <private>only hidden-canary</private> Never log API_KEY=' + secret)
        self.append(text='Only private-canary #private')
        self.append(text='/private only command-canary')
        self.start(); text = self.handoff()
        self.assertIn('cobalt', text)
        for hidden in (secret, 'hidden-canary', 'private-canary', 'command-canary'):
            self.assertNotIn(hidden, text)

    def test_older_callback_cannot_displace_newer_session(self):
        newer = self.transcript(self.NEW, '2026-10-27T11:00:00Z', 'Decided: only violet.')
        self.start(self.NEW); self.stop(newer, self.NEW)
        before = self.cursor(); handoff = self.handoff()
        newer.unlink()  # Ordering must survive removal of the tracked newer transcript too.
        self.append(); self.stop(self.path, self.SID)
        self.assertFalse(core.capture_decisions(self.root, str(self.path), 'codex'))
        self.start()
        self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)
        self.assertIn('violet', core.brief(self.root))

    def test_archived_tracked_session_does_not_block_newer_capture(self):
        archived = self.home / 'archived_sessions'; archived.mkdir()
        self.path.rename(archived / self.path.name)
        newer = self.transcript(self.NEW, '2026-10-27T11:00:00Z', 'Decided: only violet.')
        self.start(self.NEW); self.stop(newer, self.NEW)
        self.assertIn('violet', self.handoff())
        self.assertEqual(json.loads(self.cursor())['session_id'], self.NEW)

    def test_deleted_tracked_session_and_old_cursor_migrate_to_newer_capture(self):
        cursor = self.root / '.ws/codex-capture/T-1.json'
        old = json.loads(self.cursor()); old.pop('started')
        cursor.write_text(json.dumps(old))
        self.path.unlink()
        newer = self.transcript(self.NEW, '2026-10-27T11:00:00Z', 'Decided: only violet.')
        self.start(self.NEW); self.stop(newer, self.NEW)
        self.assertIn('violet', self.handoff())
        self.assertEqual(json.loads(self.cursor())['started'], '2026-10-27T11:00:00+00:00')

    def test_invalid_start_stamps_leave_cursor_and_memory_unchanged(self):
        self.append(); cursor = self.root / '.ws/codex-capture/T-1.json'
        original = json.loads(self.cursor()); handoff = self.handoff()
        for stamp in ('not-a-date', '2026-10-27T10:00:00', None):
            with self.subTest(stamp=stamp):
                bad = dict(original, started=stamp); cursor.write_text(json.dumps(bad))
                self.assertIn('T-1', self.start())
                self.assertEqual(json.loads(self.cursor()), bad); self.assertEqual(self.handoff(), handoff)

    def test_rejected_sources_do_not_advance_or_hide_the_brief(self):
        original = self.path.read_bytes(); cursor = self.cursor(); handoff = self.handoff()
        for case in ('missing', 'malformed', 'duplicate', 'oversized', 'substituted', 'truncated', 'wrong_id'):
            with self.subTest(case=case):
                self.path.write_bytes(original)
                extra = self.sessions / ('copy-' + self.SID + '.jsonl')
                if case == 'missing': self.path.unlink()
                elif case == 'malformed': self.path.write_bytes(original + b'{unfinished')
                elif case == 'duplicate': extra.write_bytes(original)
                elif case == 'oversized':
                    with self.path.open('ab') as out: out.truncate(50 * 1024 * 1024 + 1)
                elif case == 'substituted': self.path.write_bytes(original.replace(b'amber', b'other'))
                elif case == 'truncated': self.path.write_bytes(original[:100])
                else: self.path.write_bytes(original.replace(self.SID.encode(), self.NEW.encode()))
                self.assertIn('T-1', self.start())
                self.assertEqual(self.cursor(), cursor); self.assertEqual(self.handoff(), handoff)
                if extra.exists(): extra.unlink()

    def test_disabled_unclaimed_wrong_branch_and_other_clients_skip(self):
        self.append(); before = self.cursor(); handoff = self.handoff()
        with mock.patch.object(core, 'config', return_value=dict(core.config(self.root), capture=False)):
            self.start()
        local = self.root / '.ws/claims/T-1.json'; saved = local.read_bytes(); local.unlink()
        self.start(); local.write_text(json.dumps({'worker': 'other', 'token': 'wrong'})); self.start(); local.write_bytes(saved)
        task = core.task_path(self.root, 'T-1'); old = task.read_text()
        task.write_text(core.set_meta(old, {'branch': 'another-branch'}))
        with mock.patch.object(core, '_task_git', return_value='current-branch'):
            self.start()
        task.write_text(old)
        self.start(client='claude')
        self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)

    def test_read_failure_and_malformed_cursor_leave_memory_and_cursor_unchanged(self):
        from ws import transcripts
        self.append(); before = self.cursor(); handoff = self.handoff()
        original_open = os.open
        def denied(path, *args, **kwargs):
            if Path(path) == self.path: raise PermissionError
            return original_open(path, *args, **kwargs)
        with mock.patch.object(transcripts.os, 'open', side_effect=denied):
            self.assertIn('T-1', self.start())
        self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)
        cursor = self.root / '.ws/codex-capture/T-1.json'
        cursor.write_text('{bad')
        self.assertIn('T-1', self.start())
        self.assertEqual(cursor.read_text(), '{bad'); self.assertEqual(self.handoff(), handoff)

    def test_new_client_home_does_not_search_the_previous_home(self):
        self.append(); before = self.cursor(); handoff = self.handoff()
        with mock.patch.dict(os.environ, CODEX_HOME=str(self.root.parent / 'empty-client-home')):
            self.assertIn('T-1', self.start())
        self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)

    def test_task_write_failure_does_not_advance_cursor(self):
        self.append(); before = self.cursor(); handoff = self.handoff()
        write = core.atomic_write
        def denied(path, text):
            if path.resolve() == core.task_path(self.root, 'T-1').resolve(): raise OSError('fixture')
            return write(path, text)
        with mock.patch.object(core, 'atomic_write', side_effect=denied):
            self.assertIn('T-1', self.start())
        self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)

    @unittest.skipUnless(os.name == 'nt', 'native junction fixture needs Windows')
    def test_windows_junction_session_directory_is_refused(self):
        outside = self.root.parent / 'outside-sessions'; self.sessions.rename(outside)
        try:
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(self.sessions), str(outside)], check=True, capture_output=True)
            before = self.cursor(); handoff = self.handoff(); self.start()
            self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)
        finally:
            if self.sessions.exists(): os.rmdir(self.sessions)
            outside.rename(self.sessions)

    def test_symlink_and_reparse_sources_are_refused(self):
        from testutil import needs_symlinks
        @needs_symlinks
        def exercise():
            original = self.path.read_bytes(); outside = self.root / 'outside.jsonl'
            outside.write_bytes(original); self.path.unlink(); self.path.symlink_to(outside)
            before = self.cursor(); handoff = self.handoff()
            self.start()
            self.assertEqual(self.cursor(), before); self.assertEqual(self.handoff(), handoff)
            self.path.unlink(); self.path.write_bytes(original)
        exercise()
        # A junction/reparse point is not necessarily reported by is_symlink on Windows.
        from ws import transcripts
        with mock.patch.object(transcripts, 'unsafe', side_effect=lambda p: Path(p) == self.sessions):
            before = self.cursor(); self.append(); self.start(); self.assertEqual(self.cursor(), before)
