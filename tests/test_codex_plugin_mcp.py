import json
import subprocess
import sys
import unittest

import test_plugin_runtime


class CodexPluginMcpTests(unittest.TestCase):
    setUp = test_plugin_runtime.PluginRuntimeTests.setUp

    def test_declared_server_preserves_repo_cwd_and_is_inactive_elsewhere(self):
        kit = test_plugin_runtime.KIT
        manifest = json.loads((kit / '.codex-plugin/plugin.json').read_text(encoding='utf-8'))
        server = json.loads((kit / manifest['mcpServers']).read_text(encoding='utf-8'))['mcpServers']['ai-dev-workspace']
        args = [arg.replace('${CLAUDE_PLUGIN_ROOT}', str(kit)) for arg in server['args']]
        messages = [dict(jsonrpc='2.0', id=1, method='initialize', params={'protocolVersion': '2025-11-25'}),
                    dict(jsonrpc='2.0', id=2, method='tools/list'),
                    dict(jsonrpc='2.0', id=3, method='tools/call', params={'name': 'brief', 'arguments': {}})]
        for cwd in (self.base, self.repo):
            with self.subTest(cwd=cwd):
                result = subprocess.run([sys.executable, *args], cwd=cwd, env=self.env,
                                        input='\n'.join(map(json.dumps, messages)) + '\n',
                                        capture_output=True, text=True, encoding='utf-8', timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                replies = [json.loads(line)['result'] for line in result.stdout.splitlines()]
                if cwd == self.base:
                    self.assertEqual([t['name'] for t in replies[1]['tools']], ['brief'])
                    self.assertTrue(replies[2]['isError'])
                    self.assertNotIn('integer cents', json.dumps(replies))
                else:
                    self.assertFalse(replies[2]['isError'])
                    self.assertIn('integer cents', replies[2]['content'][0]['text'])
