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

    def test_read_task_defaults_to_resume_sections_and_full_record_is_explicit(self):
        sections = ['Next action', 'Blockers', 'Handoff']
        core.task_new(self.root, 'T-1', 'Section read proof')
        core.claim(self.root, 'T-1', 'synthetic')
        core.checkpoint(self.root, 'T-1', 'in_progress', 'Run the selected-section check',
                        notes={'Blockers': 'None', 'Handoff': 'Keep this decision.'})
        full = core.task_read(self.root, 'T-1')['text']
        expected = {name: core.section(full, name) for name in sections}
        result = self.rpc('tools/call', name='read_task', arguments={'id': 'T-1'})['result']['content'][0]['text']
        selected = json.loads(result)
        self.assertEqual(selected['sections'], expected)
        complete = self.rpc('tools/call', name='read_task', arguments={'id': 'T-1', 'sections': []})
        self.assertEqual(json.loads(complete['result']['content'][0]['text'])['text'], full)

    def call(self, name, **arguments):
        result = self.rpc('tools/call', name=name, arguments=arguments)['result']
        return result['isError'], result['content'][0]['text']

    def test_remember_saves_a_decision_the_brief_lists(self):
        core.task_new(self.root, 'T-1', 'Remember proof')
        core.claim(self.root, 'T-1', 'synthetic')
        failed, text = self.call('remember', text='use Postgres, not SQLite')
        self.assertFalse(failed)
        self.assertEqual(json.loads(text), {'task': 'T-1', 'remembered': 'use Postgres, not SQLite'})
        self.assertIn('use Postgres, not SQLite', json.loads(self.call('brief')[1]))
        core.task_new(self.root, 'T-2', 'Other')
        self.assertFalse(self.call('remember', text='ship on Monday', task='T-2')[0])
        self.assertIn('Decision: ship on Monday', core.task_read(self.root, 'T-2', ['Handoff'])['sections']['Handoff'])

    def test_remember_errors_use_the_mcp_error_shape(self):
        core.task_new(self.root, 'T-1', 'Remember proof')
        failed, text = self.call('remember', text='use Postgres')  # nothing claimed
        self.assertTrue(failed)
        self.assertIn('WsError: No single claimed task', text)
        core.claim(self.root, 'T-1', 'synthetic')
        failed, text = self.call('remember', text='never ship Friday #private')
        self.assertTrue(failed)
        self.assertIn('marked private', text)
        self.assertEqual(self.rpc('tools/call', name='remember', arguments={})['error']['code'], -32602)

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
