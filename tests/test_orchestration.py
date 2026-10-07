import json
import os
from unittest import mock
from test_ws import Base
from ws import core, orchestration
from mcp import server


class OrchestrationTests(Base):
    def fake(self, code='import sys; print("UNVERIFIED sample.py:1 synthetic finding")'):
        directory = self.root / 'bin'; directory.mkdir(exist_ok=True)
        for name in ('codex', 'ollama'):
            p = directory / name; p.write_text('#!' + __import__('sys').executable + '\n' + code + '\n'); p.chmod(0o755)
        return mock.patch.dict(os.environ, {'PATH': str(directory)})

    def test_binding_overrides_no_fallback_and_upgrade(self):
        with self.fake():
            binding = orchestration.route(self.root, 'explorer')
            self.assertEqual((binding['provider'], binding['family'], binding['effort']), ('codex', 'luna', 'high'))
            planner = orchestration.route(self.root, 'planner')  # claude preferred but absent: visible fallback to codex
            self.assertEqual((planner['provider'], planner['family'], planner['available']), ('codex', 'sol', True))
            self.assertEqual(planner['skipped'], [{'provider': 'claude', 'reason': 'CLI not on PATH'}])
            path = self.root / 'routing.json'; d = json.loads(path.read_text())
            d['role_overrides']['planner'] = {'provider': 'claude'}  # an explicitly pinned provider never falls back
            path.write_text(json.dumps(d))
            self.assertFalse(orchestration.route(self.root, 'planner')['available'])
            with self.assertRaises(core.WsError): orchestration.delegate(self.root, 'T-1', 'planner')
            d['role_overrides'] = {}
            d['role_overrides']['explorer'] = {'provider': 'codex', 'model': 'gpt-6.1-sol', 'effort': 'low'}
            path.write_text(json.dumps(d))
            self.assertEqual(orchestration.route(self.root, 'explorer')['model'], 'gpt-6.1-sol')
            core.upgrade_workspace(self.root)
            self.assertEqual(json.loads(path.read_text())['role_overrides'], d['role_overrides'])

    def test_bounded_prepare_run_evidence_and_write_role_refusal(self):
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect synthetic files', notes={'Evidence': 'Keep human evidence.'})
        with self.fake():
            prepared = orchestration.delegate(self.root, 'T-1', 'explorer')
            text = (__import__('pathlib').Path(prepared['brief'])).read_text()
            for section in ('Objective', 'Next action', 'Blockers', 'Evidence', 'Allowed paths', 'Output contract'):
                self.assertIn(section, text)
            self.assertLessEqual(len(text.split()), 400)
            self.assertIn('read-only', prepared['command'])
            with self.assertRaises(core.WsError): orchestration.delegate(self.root, 'T-1', 'worker', run=True)
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
            self.assertEqual(result['exit_code'], 0)
            evidence = core.task_read(self.root, 'T-1', ['Evidence'])['sections']['Evidence']
            self.assertIn('Keep human evidence.', evidence); self.assertIn('unverified', evidence)
            self.assertIn('luna', core.trace(self.root, 'T-1'))
            reply = server.handle(self.root, {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'delegate','arguments':{'task':'T-1','role':'explorer','run':True}}})
            self.assertIn('error', reply)

    def test_provider_failure_is_logged_without_fallback(self):
        with self.fake('import sys; print("synthetic failure"); sys.exit(3)'):
            result = orchestration.delegate(self.root, 'T-1', 'explorer', run=True)
            self.assertEqual(result['exit_code'], 3)
            self.assertEqual(core.run_entries(self.root, 'T-1')[-1]['result'], 'failed')
