import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ('README.md', 'docs/SETUP.md', 'docs/COMMANDS.md', 'docs/CONCEPTS.md', 'docs/WINDOWS.md')


class CompatibilityDocsTests(unittest.TestCase):
    def test_client_compatibility_table_is_identical(self):
        tables = []
        for name in DOCS:
            lines = (ROOT / name).read_text(encoding='utf-8').splitlines()
            start = next(i for i, line in enumerate(lines) if line.startswith('| Capability |'))
            end = next(i for i in range(start, len(lines)) if lines[i].startswith('| Automatic capture |'))
            tables.append('\n'.join(lines[start:end + 1]))
        self.assertTrue(all(table == tables[0] for table in tables[1:]))


if __name__ == '__main__':
    unittest.main()
