import json

from test_ws import Base
from mcp import server
from ws import core


class ToolProfileTests(Base):
    def listed(self):
        reply = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
        return [tool['name'] for tool in reply['result']['tools']]

    def configure(self, value):
        cfg = core.config(self.root); cfg['mcp_tools'] = value
        (self.root / 'workspace.json').write_text(json.dumps(cfg))

    def test_core_profile_is_the_default_and_much_smaller(self):
        self.assertEqual(self.listed(), [n for n in server.TOOLS if n in server.CORE_TOOLS])
        self.assertEqual(len(self.listed()), 7)
        core_bytes = core.tool_costs(self.root, usage={})['mcp_schema_bytes']
        self.configure('all')
        self.assertLess(core_bytes * 2, core.tool_costs(self.root, usage={})['mcp_schema_bytes'])

    def test_all_custom_and_invalid_values(self):
        self.configure('all'); self.assertEqual(self.listed(), list(server.TOOLS))
        self.configure(['status', 'brief']); self.assertEqual(self.listed(), ['brief', 'status'])
        self.configure(5); self.assertEqual(len(self.listed()), len(server.CORE_TOOLS))

    def test_unlisted_tools_stay_callable(self):
        self.assertNotIn('status', self.listed())
        reply = server.handle(self.root, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'status', 'arguments': {}}})
        self.assertFalse(reply['result']['isError'])

    def test_core_covers_memory_and_framework_recipe_tools(self):
        for name in ('brief', 'remember', 'checkpoint', 'find_task', 'add_lesson', 'search_vault', 'read_task'):
            self.assertIn(name, self.listed())

    def test_doctor_reports_the_profile(self):
        self.assertEqual(core.doctor(self.root)['mcp_tools'], {'profile': 'core', 'listed': 7})

    def test_doctor_reports_effective_core_for_invalid_settings(self):
        for value in ('everything', None, 5):
            with self.subTest(value=value):
                self.configure(value)
                self.assertEqual(core.doctor(self.root)['mcp_tools'], {'profile': 'core', 'listed': 7})
