"""Pins the generated client config to the official docs verified in docs/CLIENT-VERIFICATION.md."""
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from ws import core, cli

ROOT = Path(__file__).resolve().parents[1]


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
        for client in ('claude', 'codex', 'cursor', 'vscode', 'gemini'):
            for event, entries in self.hooks(client).items():
                for entry in entries:
                    for hook in entry.get('hooks', [entry]):
                        with self.subTest(client=client, event=event):
                            self.assertEqual(hook['timeout'], 10000 if client == 'gemini' else 10)

    def test_session_start_context_output(self):
        for client in ('codex', 'cursor', 'vscode', 'gemini'):
            output = io.StringIO()
            with mock.patch.object(core, 'find_root', return_value=ROOT), \
                    mock.patch.object(core, 'brief', return_value='Saved next action.'), \
                    mock.patch.object(cli.assist, 'observe'), \
                    mock.patch('sys.stdin', io.StringIO('{"hook_event_name":"SessionStart"}')), \
                    mock.patch('sys.stdout', output):
                self.assertEqual(cli.main(['brief', '--hook', '--client', client]), 0)
            expected = ({'additional_context': 'Saved next action.'} if client == 'cursor' else
                        {'hookSpecificOutput': {'hookEventName': 'SessionStart', 'additionalContext': 'Saved next action.'}})
            self.assertEqual(json.loads(output.getvalue()), expected)

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
