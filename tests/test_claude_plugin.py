import json
import unittest
from pathlib import Path

from test_ws import Base
from ws import core

KIT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((KIT / path).read_text(encoding='utf-8'))


class ClaudePluginTests(Base):
    def test_manifest_matches_the_kit(self):
        manifest = load('.claude-plugin/plugin.json')
        self.assertEqual(manifest['version'], core.kit_meta()['version'])  # a release bump must not miss the plugin
        entry = load('.claude-plugin/marketplace.json')['plugins'][0]
        self.assertEqual((entry['name'], entry['source']), (manifest['name'], './'))
        self.assertEqual(manifest['mcpServers']['ai-dev-workspace']['args'], ['${CLAUDE_PLUGIN_ROOT}/mcp/server.py', '--plugin'])
        for skill in entry['skills']:  # only the skills ws start installs; not every folder under skills/
            self.assertTrue((KIT / skill / 'SKILL.md').is_file(), skill)
        self.assertEqual(sorted(Path(s).name for s in entry['skills']), ['handoff', 'lesson', 'pickup'])

    def test_hooks_cover_the_same_events_as_ws_start(self):
        hooks = load(load('.claude-plugin/plugin.json')['hooks'])['hooks']
        self.assertEqual(set(hooks), set(core.memory_hooks(self.root, 'claude')['hooks']))
        for event, entries in hooks.items():
            command = entries[0]['hooks'][0]['command']
            self.assertEqual(command, 'python3 "${CLAUDE_PLUGIN_ROOT}/bin/ws-plugin" --client claude', event)


if __name__ == '__main__':
    unittest.main()
