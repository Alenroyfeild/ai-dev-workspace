import re
import subprocess
import sys
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]


def parser_commands():
    """Top-level command names from `ws help all` (indented four spaces under Commands)."""
    out = subprocess.run([sys.executable, str(KIT / 'bin/ws'), 'help', 'all'], capture_output=True, text=True, check=True).stdout
    return re.findall(r'^    ([a-z][a-z-]*)(?:\s{2,}|$)', out.split('\nCommands:')[1], re.M)


def documented(docs, name):
    return re.search(r'`ws ' + re.escape(name) + r'(?=[\s`\[<"])', docs) is not None


class CommandsDocTests(unittest.TestCase):
    def test_every_top_level_command_is_in_commands_md(self):
        docs = (KIT / 'docs/COMMANDS.md').read_text(encoding='utf-8')
        names = parser_commands()
        self.assertGreater(len(names), 30, names)
        self.assertEqual([n for n in names if not documented(docs, n)], [], 'add these commands to docs/COMMANDS.md')

    def test_check_catches_a_missing_name(self):
        self.assertFalse(documented('`ws status` and `ws start --yes`', 'nudge'))
        self.assertTrue(documented('| `ws nudge` | x |', 'nudge'))


if __name__ == '__main__':
    unittest.main()
