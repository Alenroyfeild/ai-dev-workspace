"""Pins the generated client config to the official docs verified in docs/CLIENT-VERIFICATION.md."""
import unittest

from ws import core


class ClientDocShapeTests(unittest.TestCase):
    def hooks(self, client):
        return core.memory_hooks('/r', client)['hooks']

    def test_event_names_and_timeout_units(self):
        self.assertEqual(set(self.hooks('cursor')), {'sessionStart', 'preCompact', 'stop', 'sessionEnd', 'beforeSubmitPrompt'})
        self.assertEqual(set(self.hooks('gemini')), {'SessionStart', 'PreCompress', 'AfterAgent', 'SessionEnd', 'BeforeAgent'})
        self.assertEqual(set(self.hooks('vscode')), {'SessionStart', 'PreCompact', 'Stop'})
        self.assertEqual(set(self.hooks('codex')), {'SessionStart', 'PreCompact', 'Stop', 'UserPromptSubmit'})
        self.assertEqual(core.memory_hooks('/r', 'cursor')['version'], 1)
        # Gemini timeouts are milliseconds; Cursor, VS Code, Claude Code and Codex use seconds.
        self.assertEqual(self.hooks('gemini')['SessionStart'][0]['hooks'][0]['timeout'], 10000)
        self.assertEqual(self.hooks('cursor')['sessionStart'][0]['timeout'], 10)
        self.assertEqual(self.hooks('vscode')['SessionStart'][0]['timeout'], 10)

    def test_entry_nesting(self):
        # Cursor and VS Code take flat hook entries; Claude Code, Codex and Gemini nest them under "hooks".
        self.assertEqual(self.hooks('cursor')['stop'][0]['type'], 'command')
        self.assertEqual(self.hooks('vscode')['Stop'][0]['type'], 'command')
        for client in ('claude', 'codex', 'gemini'):
            self.assertEqual(self.hooks(client)['SessionStart'][0]['hooks'][0]['type'], 'command')

    def test_static_config_locations(self):
        self.assertEqual(core.MCP_LOCATIONS['vscode'], ('.vscode/mcp.json', 'servers'))
        self.assertEqual(core.MCP_LOCATIONS['gemini'], ('.gemini/settings.json', 'mcpServers'))
        self.assertEqual(core.MCP_LOCATIONS['cursor'], ('.cursor/mcp.json', 'mcpServers'))
        self.assertEqual(core.NATIVE_FILES, ('.github/copilot-instructions.md', '.cursor/rules/ws-current-task.mdc'))
        self.assertTrue(core.CURSOR_RULE_HEAD.startswith('---\ndescription:'))
        self.assertIn('alwaysApply: true', core.CURSOR_RULE_HEAD)


if __name__ == '__main__':
    unittest.main()
