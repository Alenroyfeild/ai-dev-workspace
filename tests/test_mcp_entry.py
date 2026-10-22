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
        self.assertEqual(run.returncode, 0, run.stderr)  # clean exit when stdin closes, not a crash after replying
        replies = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual(replies[0]['result']['serverInfo']['name'], 'ai-dev-workspace')
        self.assertIn('brief', [t['name'] for t in replies[1]['result']['tools']])

    def test_no_workspace_still_introspects_and_tool_calls_fail_cleanly(self):
        # Directory sites start the server in an empty folder; it must list tools, not crash.
        import tempfile
        requests = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                     'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 't', 'version': '1'}}},
                    {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
                    {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'brief', 'arguments': {}}}]
        with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if k != 'WS_ROOT'}
            env.update(HOME=home, USERPROFILE=home)
            run = subprocess.run([sys.executable, str(KIT / 'mcp/server.py')], cwd=empty, env=env, text=True,
                                 input=''.join(json.dumps(r) + '\n' for r in requests), capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotIn('Traceback', run.stderr)
        replies = [json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual(replies[0]['result']['serverInfo']['name'], 'ai-dev-workspace')
        self.assertIn('brief', [t['name'] for t in replies[1]['result']['tools']])
        self.assertTrue(replies[2]['result']['isError'])
        self.assertEqual(replies[2]['result']['content'][0]['text'],
                         'No ai-dev-workspace here: run `ws start` in your repo (or pass --workspace-root).')

    def test_package_declares_the_mcp_command_and_registry_marker(self):
        self.assertIn("'ai-dev-workspace=ws.cli:mcp_main'", (KIT / 'setup.py').read_text())
        self.assertIn('mcp-name: io.github.Alenroyfeild/ai-dev-workspace', (KIT / 'README.md').read_text())
