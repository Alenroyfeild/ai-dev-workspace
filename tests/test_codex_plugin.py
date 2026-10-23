import json
import unittest
from pathlib import Path

from test_ws import Base
from ws import core

KIT = Path(__file__).resolve().parents[1]
LAUNCH = 'sh "${PLUGIN_ROOT}/bin/ws-python" "${PLUGIN_ROOT}/bin/ws-plugin" --client codex'


def load(path):
    return json.loads((KIT / path).read_text(encoding='utf-8'))


class CodexPluginTests(Base):
    def test_manifest_matches_the_kit(self):
        manifest = load('.codex-plugin/plugin.json')
        claude = load('.claude-plugin/plugin.json')
        self.assertEqual(manifest['version'], core.kit_meta()['version'])  # a release bump must not miss the Codex manifest
        for key in ('name', 'description', 'homepage', 'repository', 'license', 'author'):
            self.assertEqual(manifest[key], claude[key], key)
        self.assertEqual(manifest['skills'], './skills/')
        self.assertTrue((KIT / 'skills/handoff/SKILL.md').is_file())

    def test_hooks_are_the_ws_start_events_plus_the_guard(self):
        hooks = load(load('.codex-plugin/plugin.json')['hooks'])['hooks']
        self.assertEqual(set(hooks), set(core.memory_hooks(self.root, 'codex')['hooks']) | {'PreToolUse'})
        for event, entries in hooks.items():
            self.assertEqual(entries[0]['hooks'][0]['command'], LAUNCH, event)

    def test_every_manifest_names_its_own_hooks_file_and_no_default_file_exists(self):
        # Codex and Cursor both auto-discover hooks/hooks.json with different payloads, so it must not exist.
        self.assertFalse((KIT / 'hooks/hooks.json').exists())
        self.assertEqual(load('.claude-plugin/plugin.json')['hooks'], './hooks/claude-hooks.json')
        self.assertEqual(load('.codex-plugin/plugin.json')['hooks'], './hooks/codex-hooks.json')
        for name in ('claude', 'codex'):
            self.assertTrue((KIT / f'hooks/{name}-hooks.json').is_file(), name)

    def test_claude_plugin_loading_is_unchanged(self):
        claude = load('.claude-plugin/plugin.json')
        self.assertEqual(claude['mcpServers']['ai-dev-workspace']['args'], ['${CLAUDE_PLUGIN_ROOT}/mcp/server.py', '--plugin'])
        self.assertNotIn('${PLUGIN_ROOT}', json.dumps(load('hooks/claude-hooks.json')))


if __name__ == '__main__':
    unittest.main()
