"""Release-copy contracts; fixture coverage is not live-client proof."""
import re
import unittest
from pathlib import Path

from ws import packaging

ROOT = Path(__file__).resolve().parents[1]
FILES = ('README.md', 'docs/ADVANCED.md', 'docs/OVERVIEW.md', 'docs/SETUP.md',
         'docs/PACKS.md', 'docs/CLIENT-VERIFICATION.md', 'llms.txt', 'llms-full.txt')

# The version currently published on PyPI. Bumped after PyPI publish.
PUBLISHED_VERSION = '0.1.0-beta.7'
PUBLISHED_CANONICAL = packaging.package_version(PUBLISHED_VERSION)
PUBLISHED_BETA = PUBLISHED_VERSION.split('-')[-1] if '-' in PUBLISHED_VERSION else PUBLISHED_VERSION


class PublishedDocsTests(unittest.TestCase):
    def test_released_features_are_not_still_marked_as_future(self):
        pattern = rf'(?i)coming (?:in |next \(){re.escape(PUBLISHED_BETA)}|merged on dev, not released|not released yet'
        for name in FILES:
            with self.subTest(file=name):
                text = (ROOT / name).read_text(encoding='utf-8')
                self.assertNotRegex(text, pattern)
        self.assertIn(f'v{PUBLISHED_VERSION} on PyPI', (ROOT / 'README.md').read_text())

    def test_pypi_readme_passes_the_final_release_metadata_gate(self):
        text = (ROOT / 'README.md').read_text().casefold()
        self.assertNotIn(f'coming in {PUBLISHED_BETA}'.casefold(), text)
        self.assertNotIn('not released', text)
        coming = text.split('## coming next', 1)[1].split('\n## ', 1)[0]
        for line in coming.splitlines():
            if line.startswith('- **'):
                self.assertIn('parked', line)
                self.assertIn('unavailable', line)

    def test_readme_plugins_keep_preview_and_their_distinct_limits(self):
        text = (ROOT / 'README.md').read_text()
        expected = {'Claude Code plugin': ('ws start', 'directory', 'Windows'),
                    'Codex plugin': ('trusted', 'desktop', 'no MCP'),
                    'Cursor plugin': ('fixture-tested', 'not submitted')}
        for name, limits in expected.items():
            row = next((line for line in text.splitlines() if line.startswith('| ' + name + ' |')), '')
            with self.subTest(plugin=name):
                self.assertIn('| Preview |', row)
                for limit in limits:
                    self.assertIn(limit.casefold(), row.casefold())
        coming = text.split('## Coming next', 1)[1].split('\n## ', 1)[0]
        self.assertIn('PLG3', coming)
        self.assertIn('PLG5', coming)
        for released in ('Gateway provider', 'Behavior pack', 'Digest MCP', 'Skills packaging'):
            self.assertNotIn(released, coming)

    def test_antigravity_hooks_are_fixture_tested_not_live_or_capture(self):
        for name in ('docs/OVERVIEW.md', 'docs/SETUP.md'):
            text = (ROOT / name).read_text()
            hooks = next(line for line in text.splitlines() if line.startswith('| Hooks |'))
            self.assertIn('fixture-tested; SessionStart/PreToolUse', hooks)
            capture = next(line for line in text.splitlines() if line.startswith('| Automatic capture |'))
            self.assertTrue(capture.endswith('| not wired |'))
        text = (ROOT / 'docs/SETUP.md').read_text()
        self.assertIn('a signed-in native session is not yet proved', text)

    def test_summaries_keep_all_plugin_limits_and_released_guide_links(self):
        for name in ('llms.txt', 'llms-full.txt'):
            text = (ROOT / name).read_text()
            with self.subTest(file=name):
                self.assertIn(f'published {PUBLISHED_CANONICAL}', text)
                for limit in ('trusted manual desktop install', 'no MCP', 'not submitted', 'fixture-tested'):
                    self.assertIn(limit, text)
                self.assertNotIn('/blob/dev/docs/guides/', text)

    def test_release_labels_follow_the_candidate_changelog(self):
        text = (ROOT / 'README.md').read_text()
        for name, label in (('Lesson promotion', 'Stable'), ('Skills packaging', 'Stable'),
                            ('`digest_file` MCP tool', 'Preview')):
            with self.subTest(feature=name):
                self.assertIn('| ' + name + ' | ' + label + ' |', text)
