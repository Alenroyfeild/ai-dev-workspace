import importlib.util
import json
import unittest
from pathlib import Path
from ws import core
from test_ws import Base


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workspace_mcp', ROOT / 'mcp' / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


class McpDescriptionTests(Base):
    def setUp(self):
        super().setUp()
        cfg = core.config(self.root); cfg['mcp_tools'] = 'all'
        (self.root / 'workspace.json').write_text(json.dumps(cfg))

    def test_cost_counts_full_tool_descriptors(self):
        result = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['result']['tools']
        expected = sum(len(json.dumps({key: item[key] for key in ('name', 'description', 'inputSchema')},
                                      separators=(',', ':')).encode()) for item in result)
        costs = core.tool_costs(self.root, usage={})
        self.assertEqual({item['name'] for item in costs['mcp_tools']}, set(server.TOOLS))
        self.assertEqual(costs['mcp_schema_bytes'], expected)
        self.assertIn('description', costs['mcp_schema_scope'])

    def test_tools_list_keeps_all_tools_and_safety_meaning_with_smaller_payload(self):
        result = server.handle(self.root, {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})['result']['tools']
        names = {item['name'] for item in result}
        self.assertEqual(names, set(server.TOOLS))
        self.assertEqual(len(names), 28)
        size = sum(len(json.dumps({key: item[key] for key in ('name', 'description', 'inputSchema')},
                                  separators=(',', ':')).encode()) for item in result)
        self.assertLessEqual(size, 7500)  # Includes three knowledge tools and optional category search; measured 7434 bytes.
        descriptions = ' '.join(item['description'] for item in result).lower()
        for intent in ('never execute', 'ask before', 'redacted', 'preview-only', 'skip ambiguous'):
            self.assertIn(intent, descriptions)


if __name__ == '__main__':
    unittest.main()
