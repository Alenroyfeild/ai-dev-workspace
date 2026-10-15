import json
from unittest import mock
from test_ws import Base
from ws import cli, core
from mcp import server


CORE = {'brief', 'remember', 'checkpoint', 'search_vault', 'find_task', 'read_task'}


class McpProfileTests(Base):
    def configure(self, **values):
        cfg = core.config(self.root); cfg.update(values)
        (self.root / 'workspace.json').write_text(json.dumps(cfg))

    def rpc(self, method, **params):
        return server.handle(self.root, dict(jsonrpc='2.0', id=1, method=method, params=params))

    def test_default_core_and_hidden_calls_cannot_write(self):
        self.assertEqual({t['name'] for t in self.rpc('tools/list')['result']['tools']}, CORE)
        before = core.task_list(self.root)
        response = self.rpc('tools/call', name='new_task', arguments={'id': 'NO', 'title': 'Hidden'})
        self.assertEqual(response['error']['code'], -32602)
        self.assertEqual(core.task_list(self.root), before)

    def test_explicit_extra_and_full_profile(self):
        self.configure(mcp_tools=['new_task'])
        self.assertEqual({t['name'] for t in self.rpc('tools/list')['result']['tools']}, CORE | {'new_task'})
        self.assertFalse(self.rpc('tools/call', name='new_task', arguments={'id': 'YES', 'title': 'Opted in'})['result']['isError'])
        self.configure(mcp_tool_profile='full', mcp_tools=[])
        self.assertEqual({t['name'] for t in self.rpc('tools/list')['result']['tools']}, set(server.TOOLS))

    def test_bad_configuration_fails_closed(self):
        for profile, extra in [('typo', []), ('core', 'new_task'), ('core', [None]), ('full', ['typo'])]:
            with self.subTest(profile=profile, extra=extra):
                self.configure(mcp_tool_profile=profile, mcp_tools=extra)
                self.assertIn('error', self.rpc('tools/list'))
                self.assertIn('error', self.rpc('tools/call', name='brief'))

    def test_doctor_names_mcp_profile_separately_from_external_tool_policy(self):
        self.configure(mcp_tool_profile='full', tool_profile='lean')
        with mock.patch.dict('os.environ', WS_OFFLINE='1'):
            report = core.doctor(self.root)
        self.assertEqual(report['mcp_tool_profile'], 'full')
        self.assertEqual(report['tool_profile'], 'lean')
        self.assertIn('MCP tool profile: full', cli.text_doctor(report))
