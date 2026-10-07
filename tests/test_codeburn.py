import json
from unittest import mock
from test_ws import Base
from ws import core
from mcp import server


class CodeburnTests(Base):
    def fixture(self):
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Synthetic next')
        data = {'schema': 'codeburn.export.v2', 'records': [dict(project=str(self.root),
            sessionId='synthetic', timestamp=core.now(), provider='codex', model='Sol-synthetic',
            inputTokens=10, outputTokens=3, cacheReadTokens=20, cacheWriteTokens=5)]}
        def export(command, **kwargs):
            self.assertEqual(command[:4], ['codeburn', 'export', '-f', 'json'])
            path = command[command.index('-o') + 1]
            from pathlib import Path
            Path(path).write_text(json.dumps(data))
            return mock.Mock(returncode=0, stderr='')
        return data, export

    def test_import_real_schema_deduplicates_preserves_task_and_guard(self):
        data, export = self.fixture()
        path = core.task_path(self.root, 'T-1'); before = path.read_bytes()
        core.run_log(self.root, 'T-1', 'attempt 1', 'codex', result='failed')
        core.run_log(self.root, 'T-1', 'attempt 2', 'codex', result='failed')
        with mock.patch.object(core.shutil, 'which', return_value='codeburn'), mock.patch.object(core.subprocess, 'run', side_effect=export):
            self.assertEqual(core.import_codeburn(self.root)['imported'], 1)
            self.assertEqual(core.import_codeburn(self.root)['imported'], 0)
            reply = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                'params': {'name': 'import_usage', 'arguments': {'task': 'T-1'}}})
            self.assertNotIn('error', reply)
            self.assertFalse(reply['result'].get('isError', False), reply)
        entry = core.run_entries(self.root, 'T-1')[-1]
        self.assertEqual((entry['source'], entry['tokens_in'], entry['tokens_out']), ('codeburn', 35, 3))
        self.assertEqual(entry['at'], data['records'][0]['timestamp'])
        self.assertNotIn(str(self.root), json.dumps(entry))
        self.assertEqual(path.read_bytes(), before)
        self.assertIn('stop: two failed attempts', core.brief(self.root))

    def test_import_skips_ambiguous_other_projects_and_invalid_counts(self):
        data, export = self.fixture(); core.task_new(self.root, 'T-2', 'Same-window task')
        with mock.patch.object(core.shutil, 'which', return_value='codeburn'), mock.patch.object(core.subprocess, 'run', side_effect=export):
            self.assertEqual(core.import_codeburn(self.root)['ambiguous'], 1)
            self.assertEqual(core.import_codeburn(self.root, task_id='T-1')['imported'], 1)
            data['records'][0]['project'] = '/tmp/unrelated-synthetic'
            self.assertEqual(core.import_codeburn(self.root, task_id='T-1')['imported'], 0)
            data['records'][0]['inputTokens'] = True
            with self.assertRaises(core.WsError): core.import_codeburn(self.root, task_id='T-1')
        with mock.patch.object(core.shutil, 'which', return_value=None), self.assertRaisesRegex(core.WsError, 'npm install -g codeburn'):
            core.import_codeburn(self.root)
        with self.assertRaises(core.WsError): core.import_codeburn(self.root, since='not-a-date')

    def test_reimport_updates_the_existing_session_entry(self):
        data, export = self.fixture()
        with mock.patch.object(core.shutil, 'which', return_value='codeburn'), \
                mock.patch.object(core.subprocess, 'run', side_effect=export):
            self.assertEqual(core.import_codeburn(self.root)['imported'], 1)
            data['records'][0].update(inputTokens=40, outputTokens=8, cacheReadTokens=50, cacheWriteTokens=10)
            data['records'][0]['timestamp'] = core.now()
            self.assertEqual(core.import_codeburn(self.root)['imported'], 1)
        entries = [entry for entry in core.run_entries(self.root, 'T-1') if entry.get('source') == 'codeburn']
        self.assertEqual(len(entries), 1)
        self.assertEqual((entries[0]['tokens_in'], entries[0]['tokens_out']), (100, 8))
