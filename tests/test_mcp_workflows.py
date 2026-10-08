import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import server
from ws import core


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'workspace'
        core.init(self.root, 'workflow-test')

    def rpc(self, method, **params):
        return server.handle(self.root, {'jsonrpc': '2.0', 'id': 1,
                                         'method': method, 'params': params})

    def test_prompts_are_the_skill_steps(self):
        caps = self.rpc('initialize')['result']['capabilities']
        self.assertIn('prompts', caps)
        prompts = self.rpc('prompts/list')['result']['prompts']
        self.assertEqual({p['name'] for p in prompts}, {'handoff', 'pickup', 'lesson'})
        for prompt in prompts:
            result = self.rpc('prompts/get', name=prompt['name'])['result']
            skill = (core.KIT / 'skills' / prompt['name'] / 'SKILL.md').read_text()
            body = skill.split('---', 2)[2].strip()
            self.assertEqual(result['messages'], [{'role': 'user', 'content': {
                'type': 'text', 'text': body}}])
        for params in ({'name': '../secret'}, {'name': []},
                       {'name': 'pickup', 'arguments': {'unexpected': 'value'}}):
            self.assertEqual(self.rpc('prompts/get', **params)['error']['code'], -32602)

    def test_resources_follow_local_claims_and_live_brief(self):
        self.assertIn('resources', self.rpc('initialize')['result']['capabilities'])
        self.assertEqual(len(self.rpc('resources/list')['result']['resources']), 1)
        core.task_new(self.root, 'T-1', 'Workflow proof')
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Inspect synthetic guard')
        resources = self.rpc('resources/list')['result']['resources']
        self.assertEqual({r['uri'] for r in resources}, {'workspace://brief', 'workspace://tasks/T-1'})
        for resource in resources:
            content = self.rpc('resources/read', uri=resource['uri'])['result']['contents'][0]
            expected = core.brief(self.root) if resource['name'] == 'brief' else core.task_read(self.root, 'T-1')['text']
            self.assertEqual(content['text'], core.redact(expected))
            self.assertEqual(content['mimeType'], resource['mimeType'])
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Run synthetic check')
        self.assertIn('Run synthetic check', self.rpc('resources/read', uri='workspace://brief')['result']['contents'][0]['text'])
        (self.root / '.ws/claims/T-1.json').unlink()
        self.assertEqual(len(self.rpc('resources/list')['result']['resources']), 1)
        for uri in ('workspace://tasks/T-1', 'file:///etc/passwd', 'workspace://tasks/../secret'):
            self.assertEqual(self.rpc('resources/read', uri=uri)['error']['code'], -32002)
        self.assertEqual(self.rpc('resources/read', uri=[])['error']['code'], -32602)

    def test_stdio_protocol_recovers_after_bad_workflow_requests(self):
        messages = [('initialize', {}), ('prompts/list', {}), ('prompts/get', {'name': 'handoff'}),
                    ('resources/list', {}), ('resources/read', {'uri': 'workspace://brief'}),
                    ('prompts/get', {'name': '../../secret'}), ('resources/read', {'uri': '/etc/passwd'}), ('ping', {})]
        payload = '\n'.join(json.dumps({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params})
                            for i, (method, params) in enumerate(messages)) + '\n'
        proc = subprocess.run([sys.executable, str(core.KIT / 'mcp/server.py'), '--root', str(self.root)],
                              input=payload, capture_output=True, text=True, timeout=10,
                              env={**os.environ, 'HOME': self.tmp.name, 'CODEX_HOME': str(Path(self.tmp.name) / '.codex')})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual(len(replies), len(messages))
        self.assertIn('messages', replies[2]['result'])
        self.assertIn('contents', replies[4]['result'])
        self.assertEqual(replies[-1]['result'], {})
