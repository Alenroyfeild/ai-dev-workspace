import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ('README.md', 'docs/SETUP.md')


class CompatibilityDocsTests(unittest.TestCase):
    def test_client_compatibility_table_is_identical(self):
        tables = []
        for name in DOCS:
            lines = (ROOT / name).read_text(encoding='utf-8').splitlines()
            start = next(i for i, line in enumerate(lines) if line.startswith('| Capability |'))
            end = next(i for i in range(start, len(lines)) if lines[i].startswith('| Automatic capture |'))
            tables.append('\n'.join(lines[start:end + 1]))
        self.assertTrue(all(table == tables[0] for table in tables[1:]))

    def test_first_user_docs_avoid_overclaims_and_duplicate_sections(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        commands = (ROOT / 'docs/COMMANDS.md').read_text(encoding='utf-8')
        setup = (ROOT / 'docs/SETUP.md').read_text(encoding='utf-8')
        advanced = (ROOT / 'docs/ADVANCED.md').read_text(encoding='utf-8')
        for claim in ('exactly where it left off', 'in any assistant', 'stops repeating the same mistakes',
                      'Everything stays in your folder', 'The only network call'):
            self.assertNotIn(claim, readme)
        self.assertEqual(readme.count('when product decisions were given in one session'), 1)
        self.assertEqual(sum(line.startswith('`ws assist`') for line in commands.splitlines()), 1)
        self.assertEqual(sum(line.startswith('`ws run import codeburn') for line in commands.splitlines()), 1)
        self.assertNotIn('acpx', setup)
        for detail in ('role_overrides', 'tool_profile', 'tool_overrides', 'ws tools --cost'):
            self.assertIn(detail, advanced)


if __name__ == '__main__':
    unittest.main()
