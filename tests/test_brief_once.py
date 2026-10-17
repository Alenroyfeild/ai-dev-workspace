import contextlib
import io
import json
from unittest import mock

from test_ws import Base
from ws import cli, core


class BriefOnceTests(Base):
    def run_hook(self, client):
        core.claim(self.root, 'T-1', 'synthetic'); core.checkpoint(self.root, 'T-1', 'in_progress', 'Finish the export.')
        calls = []
        real = core._brief
        def counted(*args, **kwargs):
            calls.append(args); return real(*args, **kwargs)
        out = io.StringIO()
        payload = json.dumps({'hook_event_name': 'SessionStart', 'session_id': 's'})
        with mock.patch.object(core, '_brief', counted), mock.patch('sys.stdin', io.StringIO(payload)), contextlib.redirect_stdout(out):
            cli.main(['--workspace-root', str(self.root), 'brief', '--hook'] + ([] if client == 'claude' else ['--client', client]))
        return calls, json.loads(out.getvalue())

    def test_claude_and_codex_hooks_build_the_brief_once(self):
        for client in ('claude', 'codex'):
            with self.subTest(client):
                calls, data = self.run_hook(client)
                self.assertEqual(len(calls), 1)
                self.assertIn('Finish the export.', data['hookSpecificOutput']['additionalContext'])
                self.assertIn('Remembered', data.get('systemMessage', 'Remembered'))
