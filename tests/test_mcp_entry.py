import json
import os
import subprocess
import sys

from test_ws import Base, KIT


class McpEntryTests(Base):
    def test_console_script_serves_mcp_over_stdio(self):
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                     'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
        env = dict(os.environ, WS_ROOT=str(self.root))
        run = subprocess.run([sys.executable, '-c', 'from ws.cli import mcp_main; mcp_main()'], cwd=KIT, env=env, text=True,
                             input=''.join(json.dumps(r) + '\n' for r in requests), capture_output=True, timeout=60)
        replies = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual(replies[0]['result']['serverInfo']['name'], 'ai-dev-workspace')
        self.assertIn('brief', [t['name'] for t in replies[1]['result']['tools']])

    def test_package_declares_the_mcp_command_and_registry_marker(self):
        self.assertIn("'ai-dev-workspace=ws.cli:mcp_main'", (KIT / 'setup.py').read_text())
        self.assertIn('mcp-name: io.github.Alenroyfeild/ai-dev-workspace', (KIT / 'README.md').read_text())
