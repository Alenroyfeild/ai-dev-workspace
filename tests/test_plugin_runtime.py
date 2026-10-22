"""Plugin entrypoints, only fixture homes and stdio subprocesses."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from ws import core
from testutil import isolate_home

KIT = Path(__file__).resolve().parents[1]


class PluginRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        isolate_home(self, self.base)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True, capture_output=True)
        self.root = self.base / 'memory'
        core.init(self.root, 'synthetic', clients=[])
        cfg = core.config(self.root); cfg['repos'] = [str(self.repo)]
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        (self.repo / '.ws-start.json').write_text(json.dumps({'workspace': str(self.root), 'files': {}}))
        core.task_new(self.root, 'T1', 'Synthetic memory')
        core.claim(self.root, 'T1', 'fixture')
        core.remember(self.root, 'Store totals as integer cents.')
        self.env = dict(os.environ, WS_ROOT=str(self.root), WS_OFFLINE='1', PYTHONDONTWRITEBYTECODE='1')

    def wire(self, cwd):
        messages = [dict(jsonrpc='2.0', id=1, method='initialize', params={'protocolVersion': '2025-11-25'}),
                    dict(jsonrpc='2.0', id=2, method='tools/list'),
                    dict(jsonrpc='2.0', id=3, method='tools/call', params={'name': 'brief', 'arguments': {}}),
                    dict(jsonrpc='2.0', id=4, method='resources/list')]
        result = subprocess.run([sys.executable, str(KIT/'mcp/server.py'), '--plugin'], cwd=cwd,
                                env=self.env, input='\n'.join(map(json.dumps, messages))+'\n',
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        return [json.loads(line)['result'] for line in result.stdout.splitlines()]

    def hook(self, payload):
        from ws import plugin_runtime
        output = io.StringIO()
        with mock.patch('sys.stdin', io.StringIO(json.dumps(payload))), contextlib.redirect_stdout(output):
            result = plugin_runtime.main(['--client', 'codex'])
        self.assertEqual(result, 0)
        return json.loads(output.getvalue())

    def test_outside_repo_ignores_ambient_workspace_and_never_dispatches_hook(self):
        from ws import cli
        with mock.patch.dict(os.environ, self.env), mock.patch.object(cli, 'main', side_effect=AssertionError('must not dispatch')):
            self.assertEqual(self.hook({'cwd': str(self.base), 'hook_event_name': 'SessionStart'}), {})

    def test_linked_hook_reuses_cli_with_bound_root_and_original_payload(self):
        from ws import cli
        payload = {'cwd': str(self.repo), 'hook_event_name': 'Stop', 'session_id': 'fixture'}
        def dispatch(args):
            self.assertEqual(args, ['--workspace-root', str(self.root), 'nudge', '--hook', '--client', 'codex'])
            self.assertEqual(json.load(sys.stdin), payload)
            print('{}')
            return 0
        with mock.patch.object(cli, 'main', side_effect=dispatch) as handler:
            self.assertEqual(self.hook(payload), {})
            handler.assert_called_once()

    def test_mcp_outside_repo_starts_but_does_not_expose_ambient_memory(self):
        before = {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
        replies = self.wire(self.base)
        self.assertEqual([t['name'] for t in replies[1]['tools']], ['brief'])
        self.assertLess(len(json.dumps(replies[1])), 500)
        self.assertTrue(replies[2]['isError'])
        self.assertIn('No ai-dev-workspace here: run `ws start`', replies[2]['content'][0]['text'])
        self.assertEqual(replies[3]['resources'], [])
        self.assertNotIn('integer cents', json.dumps(replies))
        self.assertEqual(before, {p: p.read_bytes() for p in self.base.rglob('*') if p.is_file()})

    def test_mcp_inside_linked_repo_reads_the_bound_memory(self):
        nested = self.repo / 'src'; nested.mkdir()
        replies = self.wire(nested)
        self.assertFalse(replies[2]['isError'])
        self.assertIn('integer cents', replies[2]['content'][0]['text'])

    def test_invalid_repo_link_fails_closed(self):
        cfg = core.config(self.root); cfg['repos'] = []
        (self.root / 'workspace.json').write_text(json.dumps(cfg))
        self.assertEqual(self.hook({'cwd': str(self.repo), 'hook_event_name': 'SessionStart'}), {})
        self.assertTrue(self.wire(self.repo)[2]['isError'])


class DoctorAutoPullTextTests(unittest.TestCase):
    def test_doctor_text_reports_the_saved_auto_pull_state(self):
        from ws.cli import text_doctor
        for consent in (True, False, None):
            with self.subTest(consent=consent):
                line = text_doctor({'team_workspace': {'privacy': 'attested', 'auto_pull': consent}})
                self.assertIn('automatic pulls ' + ('enabled (read-only)' if consent is True else 'off (consent required)'), line)
                self.assertNotIn('not active yet', line)
