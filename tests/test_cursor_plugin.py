import json
import re
import unittest
from pathlib import Path

from test_ws import Base
from ws import core, guards, repo as repo_setup

KIT = Path(__file__).resolve().parents[1]
LAUNCH = 'sh ./bin/ws-python ./bin/ws-plugin --client cursor'


def load(path):
    return json.loads((KIT / path).read_text(encoding='utf-8'))


class CursorPluginTests(Base):
    def test_manifest_matches_the_kit(self):
        manifest = load('.cursor-plugin/plugin.json')
        claude = load('.claude-plugin/plugin.json')
        self.assertEqual(manifest['version'], core.kit_meta()['version'])  # a release bump must not miss the Cursor manifest
        self.assertRegex(manifest['name'], r'^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$')
        for key in ('name', 'description', 'homepage', 'repository', 'license', 'author'):
            self.assertEqual(manifest[key], claude[key], key)
        self.assertEqual((manifest['rules'], manifest['skills'], manifest['hooks']), ('./rules/', './skills/', './hooks/cursor-hooks.json'))
        self.assertEqual(manifest['mcpServers']['ai-dev-workspace']['args'], ['${CURSOR_PLUGIN_ROOT}/mcp/server.py', '--plugin'])
        entry = load('.cursor-plugin/marketplace.json')['plugins'][0]
        self.assertEqual((entry['name'], entry['source'], entry['version']), (manifest['name'], './', manifest['version']))
        self.assertTrue(load('.cursor-plugin/marketplace.json')['owner']['name'])
        for path in manifest['rules'], manifest['skills']:  # paths stay inside the plugin
            self.assertTrue(path.startswith('./') and '..' not in path)

    def test_hooks_are_the_ws_start_events_plus_the_guard(self):
        data = load('hooks/cursor-hooks.json')
        self.assertEqual(data['version'], 1)
        self.assertEqual(set(data['hooks']), set(core.memory_hooks(self.root, 'cursor')['hooks']) | {'beforeSubmitPrompt', 'preToolUse'})
        for event, entries in data['hooks'].items():
            self.assertEqual(entries[0]['command'], LAUNCH, event)  # Cursor entries are flat, not nested like Claude and Codex

    def test_shipped_rule_is_the_generator_output(self):
        # So the plugin rule cannot drift from the text ws start writes into .cursor/rules.
        self.assertEqual((KIT / 'rules/ai-dev-workspace.mdc').read_text(encoding='utf-8'), repo_setup.plugin_cursor_rule())
        text = repo_setup.plugin_cursor_rule()
        self.assertTrue(text.startswith('---\ndescription: '))
        self.assertIn('\nalwaysApply: true\n---\n', text)
        self.assertIn(repo_setup.memory_instructions('X', 'ws'), text.replace(repo_setup.plugin_where(), 'X'))
        self.assertNotRegex(text, r'/Users/|/home/|[A-Z]:\\')

    def test_ws_start_rule_uses_the_same_instruction_text(self):
        command = core.command_line([core.python_command(), str(core.KIT / 'bin/ws'), '--workspace-root', str(self.root)])
        repo = self.root.parent / 'r'; repo.mkdir()
        import subprocess
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        desired = repo_setup.render(repo, self.root, ['cursor'], lambda name: None)
        self.assertEqual(desired['.cursor/rules/ws-current-task.mdc'].decode(),
                         '---\nalwaysApply: true\n---\n' + repo_setup.memory_instructions(self.root, command))

    def test_cursor_guard_dialect(self):
        deny = guards.hook({'tool_name': 'Shell', 'tool_input': {'command': 'rm -rf ~'}}, client='cursor')
        self.assertEqual(deny['permission'], 'deny')
        self.assertIn('ws guards', deny['user_message']); self.assertEqual(deny['user_message'], deny['agent_message'])
        # Cursor blocks a permission hook that prints something it cannot read, so an allow must be explicit.
        self.assertEqual(guards.hook({'tool_name': 'Shell', 'tool_input': {'command': 'ls'}}, client='cursor'), {'permission': 'allow'})
        self.assertEqual(guards.hook('not a payload', client='cursor'), {'permission': 'allow'})

    def test_no_default_hooks_file_and_each_manifest_names_its_own(self):
        self.assertFalse((KIT / 'hooks/hooks.json').exists())
        self.assertEqual(load('.cursor-plugin/plugin.json')['hooks'], './hooks/cursor-hooks.json')
        self.assertEqual(load('.codex-plugin/plugin.json')['hooks'], './hooks/codex-hooks.json')
        self.assertEqual(load('.claude-plugin/plugin.json')['hooks'], './hooks/claude-hooks.json')

    def test_other_manifests_are_untouched_by_the_cursor_files(self):
        self.assertEqual(load('.claude-plugin/plugin.json')['mcpServers']['ai-dev-workspace']['args'], ['${CLAUDE_PLUGIN_ROOT}/mcp/server.py', '--plugin'])
        self.assertNotIn('cursor', json.dumps(load('.codex-plugin/plugin.json')).lower())
        self.assertNotIn('CURSOR_PLUGIN_ROOT', json.dumps(load('hooks/claude-hooks.json')) + json.dumps(load('hooks/codex-hooks.json')))


if __name__ == '__main__':
    unittest.main()
