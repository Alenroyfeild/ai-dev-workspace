"""Contracts joining the approved beta.5 queue features (F7)."""
import unittest
from pathlib import Path
from unittest import mock

from test_ws import Base
from ws import core, knowledge


class ReadmeIntegrationTests(unittest.TestCase):
    def test_readme_keeps_the_remove_link_within_the_line_budget(self):
        text = (Path(__file__).resolve().parents[1] / 'README.md').read_text(encoding='utf-8')
        self.assertIn('[remove it](docs/TUTORIAL.md#remove-it)', text)
        self.assertLessEqual(len(text.splitlines()), 40)


class MemoryIntegrationTests(Base):
    def test_newest_catalog_warning_keeps_the_capped_brief_hint(self):
        warning = knowledge.CAP_PREFIX + ' 100 of 123 team entries; use ws know show for omitted IDs.'
        with mock.patch.object(core, 'config', return_value={'team_workspace': True}), \
                mock.patch.object(knowledge, 'list_entries', return_value={'entries': [], 'warnings': [warning]}):
            fields = knowledge.brief_fields(self.root, 'Receipt approval', '')
        self.assertIn(('More team notes:', 'ws know list --layer team', 12), fields)
        self.assertTrue(knowledge.CAP_WARNING.startswith(knowledge.CAP_PREFIX))

    def test_shared_lesson_metadata_pattern_ignores_trailing_whitespace(self):
        core.lesson_add(self.root, 'Stable cache policy avoids rebuilds.', area='metadataonlyterm')
        path = core.vault(self.root) / 'Learnings.md'
        path.write_text(path.read_text().replace(' -->', ' -->   \t'), encoding='utf-8')
        self.assertEqual(core.lesson_search(self.root, 'metadataonlyterm'), [])
        lines = core.relevant_lessons(self.root, {'id': 'T-1', 'title': 'metadataonlyterm'})
        self.assertEqual(len(lines), 1)
        self.assertIn('Stable cache policy avoids rebuilds.', lines[0])
        self.assertNotIn('<!--', lines[0])
