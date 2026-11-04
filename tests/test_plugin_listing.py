import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_KEYWORDS = [
    'memory',
    'session-memory',
    'handoff',
    'decisions',
    'claude-code',
    'codex',
    'cursor',
    'mcp',
    'markdown',
    'guards',
]

SHARED_DISPLAY_NAME = 'AI Dev Workspace'
SHARED_SHORT_DESC = 'Memory your AI agents share'
DEVELOPER_NAME = 'Alenroyfeild'
CATEGORY = 'Productivity'
BRAND_COLOR = '#4F46E5'
BRAND_COLOR_DARK = '#6366F1'

CLAUDE_CODEX_LONG_DESC = (
    'Local Markdown memory that Claude Code and Codex share: a short brief at session start, '
    'saved decisions and dead ends, checkpoints, search and opt-in safety guards. '
    'Inactive until you run ws start in a repo.'
)

CURSOR_LONG_DESC = (
    'Local Markdown memory that Claude Code, Codex and Cursor (preview) share: a short brief at session start, '
    'saved decisions and dead ends, checkpoints, search and opt-in safety guards. '
    'Inactive until you run ws start in a repo.'
)

SERVER_JSON_DESC = 'Local Markdown task memory shared by Claude Code and Codex over stdio MCP.'


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))


class PluginListingTests(unittest.TestCase):
    def test_claude_manifest_and_marketplace(self):
        manifest = load('.claude-plugin/plugin.json')
        self.assertEqual(manifest['displayName'], SHARED_DISPLAY_NAME)
        self.assertEqual(manifest['description'], CLAUDE_CODEX_LONG_DESC)
        self.assertEqual(manifest['keywords'], EXPECTED_KEYWORDS)
        self.assertEqual(manifest['author']['name'], DEVELOPER_NAME)
        self.assertEqual(manifest['icon'], './assets/icon.png')
        self.assertTrue((ROOT / manifest['icon']).is_file())

        entry = load('.claude-plugin/marketplace.json')['plugins'][0]
        self.assertEqual(entry['description'], CLAUDE_CODEX_LONG_DESC)
        self.assertEqual(entry['category'], CATEGORY)
        self.assertEqual(entry['tags'], EXPECTED_KEYWORDS)

    def test_codex_manifest_and_interface(self):
        manifest = load('.codex-plugin/plugin.json')
        self.assertEqual(manifest['description'], CLAUDE_CODEX_LONG_DESC)
        self.assertEqual(manifest['author']['name'], DEVELOPER_NAME)

        interface = manifest['interface']
        self.assertEqual(interface['displayName'], SHARED_DISPLAY_NAME)
        self.assertEqual(interface['shortDescription'], SHARED_SHORT_DESC)
        self.assertEqual(interface['longDescription'], CLAUDE_CODEX_LONG_DESC)
        self.assertEqual(interface['developerName'], DEVELOPER_NAME)
        self.assertEqual(interface['category'], CATEGORY)
        self.assertEqual(interface['capabilities'], [])
        self.assertEqual(interface['websiteURL'], 'https://github.com/Alenroyfeild/ai-dev-workspace')
        self.assertEqual(interface['supportURL'], 'https://github.com/Alenroyfeild/ai-dev-workspace/issues')
        self.assertEqual(interface['brandColor'], BRAND_COLOR)
        self.assertEqual(interface['brandColorDark'], BRAND_COLOR_DARK)
        self.assertEqual(interface['logo'], './assets/mark-square.svg')
        self.assertEqual(interface['logoDark'], './assets/mark-square-dark.svg')
        self.assertEqual(interface['composerIcon'], './assets/icon.svg')

        for field in ('logo', 'logoDark', 'composerIcon'):
            rel_path = interface[field]
            self.assertTrue(rel_path.startswith('./'), f'{field} must be a relative ./ path')
            self.assertTrue((ROOT / rel_path).is_file(), f'{field} file must exist: {rel_path}')

    def test_cursor_manifest_and_marketplace(self):
        manifest = load('.cursor-plugin/plugin.json')
        self.assertNotIn('displayName', manifest)
        self.assertEqual(manifest['description'], CURSOR_LONG_DESC)
        self.assertEqual(manifest['keywords'], EXPECTED_KEYWORDS)
        self.assertEqual(manifest['author']['name'], DEVELOPER_NAME)
        self.assertEqual(manifest['logo'], './assets/mark-square.svg')
        self.assertTrue((ROOT / manifest['logo']).is_file())

        entry = load('.cursor-plugin/marketplace.json')['plugins'][0]
        self.assertEqual(entry['description'], CURSOR_LONG_DESC)
        self.assertEqual(entry['category'], CATEGORY)
        self.assertEqual(entry['tags'], EXPECTED_KEYWORDS)

    def test_server_json_description(self):
        server = load('server.json')
        self.assertEqual(server['description'], SERVER_JSON_DESC)

    def test_all_referenced_assets_exist_and_open_cleanly(self):
        assets_dir = ROOT / 'assets'
        self.assertTrue(assets_dir.is_dir(), 'assets directory must exist')
        for asset in assets_dir.iterdir():
            if asset.suffix == '.png':
                data = asset.read_bytes()
                self.assertTrue(data.startswith(b'\x89PNG\r\n\x1a\n'), f'{asset.name} invalid PNG signature')
            elif asset.suffix == '.svg':
                tree = ET.parse(asset)
                self.assertIsNotNone(tree.getroot(), f'{asset.name} failed to parse SVG XML')


if __name__ == '__main__':
    unittest.main()
