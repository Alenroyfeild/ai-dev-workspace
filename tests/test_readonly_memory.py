import contextlib
import io
import json
from unittest import mock

from test_ws import Base, core, server
from ws import cli


class ReadOnlyMemoryTests(Base):
    def setUp(self):
        super().setUp()
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Verify the amber guard',
                        notes={'Handoff': 'Decision: keep amber.'})

    def test_codex_start_context_survives_readonly_assist_metadata(self):
        payload = {'hook_event_name': 'SessionStart', 'session_id': 'synthetic-session',
                   'source': 'startup', 'cwd': str(self.root), 'transcript_path': None}
        output = io.StringIO()
        with mock.patch.object(core, 'lock', side_effect=PermissionError('read-only workspace')), \
                mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), \
                contextlib.redirect_stdout(output):
            result = cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', 'codex'])
        self.assertEqual(result, 0)
        hook = json.loads(output.getvalue())['hookSpecificOutput']
        self.assertEqual(hook['hookEventName'], 'SessionStart')
        self.assertIn('Decision: keep amber', hook['additionalContext'])

    def test_plain_brief_and_mcp_reads_require_no_writes(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        output = io.StringIO()
        with mock.patch.object(core, 'lock', side_effect=AssertionError('read acquired write lock')), \
                mock.patch.object(core, 'atomic_write', side_effect=AssertionError('read wrote data')), \
                contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'brief']), 0)
            calls = [('tools/call', {'name': 'brief', 'arguments': {}})] + [
                ('resources/read', {'uri': item['uri']}) for item in server.resources(self.root)]
            for method, params in calls:
                reply = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1,
                                                 'method': method, 'params': params})
                self.assertNotIn('error', reply)
                self.assertFalse(reply['result'].get('isError'))
                self.assertIn('Decision: keep amber', json.dumps(reply))
        self.assertIn('Decision: keep amber', output.getvalue())
        self.assertEqual(before, {p.relative_to(self.root): p.read_bytes()
                                 for p in self.root.rglob('*') if p.is_file()})

    def test_codex_null_transcript_keeps_context_and_session_tracking(self):
        from ws import assist
        payload = {'hook_event_name': 'SessionStart', 'session_id': 'synthetic-session',
                   'source': 'startup', 'cwd': str(self.root), 'transcript_path': None}
        output = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['--workspace-root', str(self.root), 'brief', '--hook', '--client', 'codex']), 0)
        self.assertIn('keep amber', json.loads(output.getvalue())['hookSpecificOutput']['additionalContext'])
        self.assertEqual(assist.state(self.root)['sessions']['T-1']['count'], 1)
